#!/usr/bin/env python3
"""Record daily release downloads and refresh the bilingual README charts."""

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen

from render_download_chart import render_chart


REPOSITORY = "Desolate-Jix/agent-gui-runtime"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases"
START = b"<!-- DOWNLOAD-STATS:START -->"
END = b"<!-- DOWNLOAD-STATS:END -->"
COMPONENTS = (
    ("installer", r"AgentGUIRuntimeExecution-Setup.*\.exe", "Execution installer", "执行版安装器"),
    ("update", r"AgentGUIRuntimeExecution-update\.zip", "Runtime update package", "Runtime 更新包"),
    ("extension", r"amadeus_agent_gui_runtime-.*\.whl", "Amadeus extension", "Amadeus 扩展"),
)


def fetch_releases(token=None):
    """Fetch every release page; a failed or malformed page aborts the update."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "agent-gui-runtime-download-stats",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    releases = []
    page = 1
    while True:
        request = Request(f"{API_URL}?per_page=100&page={page}", headers=headers)
        with urlopen(request, timeout=30) as response:
            batch = json.load(response)
        if not isinstance(batch, list):
            raise ValueError(f"Release API page {page} is not a list")
        releases.extend(batch)
        if len(batch) < 100:
            return releases
        page += 1


def summarize(releases):
    """Return totals and the newest matching release for each component."""
    if not isinstance(releases, list):
        raise ValueError("Releases must be a list")
    stats = {
        key: {"downloads": 0, "files": 0, "latest": None}
        for key, *_ in COMPONENTS
    }
    for index, release in enumerate(releases):
        context = f"Release {index}"
        if not isinstance(release, dict) or type(release.get("draft")) is not bool:
            raise ValueError(f"{context} must be an object with a boolean draft field")
        if release["draft"]:
            continue
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise ValueError(f"{context} assets must be a list")
        matched = {key: {"downloads": 0, "files": 0} for key, *_ in COMPONENTS}
        for asset in assets:
            if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
                raise ValueError(f"{context} asset must have a string name")
            count = asset.get("download_count")
            if type(count) is not int or count < 0:
                raise ValueError(f"{context} asset {asset['name']!r} has an invalid download_count")
            for key, pattern, *_ in COMPONENTS:
                if re.fullmatch(pattern, asset["name"]):
                    matched[key]["downloads"] += count
                    matched[key]["files"] += 1
        if not any(value["files"] for value in matched.values()):
            continue
        tag = release.get("tag_name")
        published = release.get("published_at")
        if not isinstance(tag, str) or not tag.strip() or not isinstance(published, str):
            raise ValueError(f"{context} must have tag_name and published_at strings")
        try:
            published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{context} has an invalid published_at") from error
        if published_at.utcoffset() is None:
            raise ValueError(f"{context} published_at must include a timezone")
        for key, value in matched.items():
            if not value["files"]:
                continue
            item = stats[key]
            item["downloads"] += value["downloads"]
            item["files"] += value["files"]
            latest = item["latest"]
            if latest is None or (published_at, tag) > (latest["published_at"], latest["tag"]):
                item["latest"] = {"tag": tag, "published_at": published_at, **value}
    for key, item in stats.items():
        if not item["files"]:
            raise ValueError(f"No matching assets found for {key}; refusing to replace existing statistics")
    return stats


def record_snapshot(history, stats, day):
    """Keep one measured snapshot per UTC day, without inventing earlier data."""
    if not isinstance(history, list):
        raise ValueError("Download history must be a list")
    previous = None
    for row in history:
        if not isinstance(row, dict) or not isinstance(row.get("date"), str):
            raise ValueError("History rows must have an ISO date")
        observed = date.fromisoformat(row["date"])
        if observed.isoformat() != row["date"] or (previous and observed <= previous):
            raise ValueError("History dates must be unique, ISO-formatted and increasing")
        for key, *_ in COMPONENTS:
            if type(row.get(key)) is not int or row[key] < 0:
                raise ValueError(f"History {key} must be a nonnegative integer")
        previous = observed
    today = date.fromisoformat(day)
    if today.isoformat() != day or (previous and today < previous):
        raise ValueError("Snapshot date must not precede the existing history")
    snapshot = {"date": day, **{key: stats[key]["downloads"] for key, *_ in COMPONENTS}}
    for key, *_ in COMPONENTS:
        if type(snapshot[key]) is not int or snapshot[key] < 0:
            raise ValueError(f"Snapshot {key} must be a nonnegative integer")
    # Replace today's observation; preserve earlier observations, including declines.
    return history[:-1] + [snapshot] if previous == today else history + [snapshot]


def render_block(stats, language, updated_at, first_date):
    """Render only the content between the existing comment markers."""
    chinese = language == "zh-CN"
    chart_path = f"docs/assets/downloads/download-trend.{language}.svg"
    lines = [
        f"![{'按日期记录的累计下载趋势' if chinese else 'Cumulative downloads over time'}]({chart_path})",
        "",
        (f"横轴为 UTC 日期，纵轴为累计下载次数；每天保留一条实测快照。记录始于 **{first_date}**，不回填此前的每日数据。图中最多显示最近 90 天，[查看完整记录](docs/data/download-history.json)。" if chinese else
         f"The horizontal axis shows UTC dates; the vertical axis shows cumulative downloads. One measured snapshot is kept per day, starting **{first_date}**; earlier daily data is not reconstructed. The chart shows up to 90 days; [view the full history](docs/data/download-history.json)."),
        "",
        "<details>",
        "<summary>当前下载明细</summary>" if chinese else "<summary>Current download totals</summary>",
        "",
        "| 组件 | 累计下载 | 最新版下载 |" if chinese else "| Component | Total downloads | Latest release downloads |",
        "| --- | ---: | --- |",
    ]
    for key, _, english, chinese_label in COMPONENTS:
        item = stats[key]
        latest = item["latest"]
        tag = latest["tag"]
        label = tag.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("|", "\\|")
        url = f"https://github.com/{REPOSITORY}/releases/tag/{quote(tag, safe='')}"
        total = f"{item['downloads']:,}"
        lines.append(f"| {chinese_label if chinese else english} | {total} | [{label}]({url}) · {latest['downloads']:,} |")
    lines += ["", "</details>"]
    if chinese:
        lines += [
            "",
            "统计 GitHub Releases 中安装器、更新 ZIP 和扩展 wheel 的累计下载次数；不含历史预览版、旧便携包、源码、视频及验证附件。包含作者测试、重复和自动化下载，不代表独立用户数。",
            "",
            f"更新时间：{updated_at}。每日自动刷新。",
        ]
    else:
        lines += [
            "",
            "Cumulative GitHub Releases downloads of installer, update ZIP and extension wheel assets; excludes historical previews, legacy portable packages, source archives, videos and verification attachments. Includes author testing, repeat and automated downloads; these are not unique user counts.",
            "",
            f"Updated: {updated_at}. Refreshed daily.",
        ]
    return "\n".join(lines)


def replace_block(content, block):
    """Preserve every byte outside the markers and use their existing newline."""
    if content.count(START) != 1 or content.count(END) != 1:
        raise ValueError("Expected exactly one complete DOWNLOAD-STATS marker pair")
    start = content.index(START) + len(START)
    end = content.index(END)
    if start > end:
        raise ValueError("DOWNLOAD-STATS markers are out of order")
    newline = b"\r\n" if content[start:start + 2] == b"\r\n" else b"\n"
    replacement = newline + block.encode("utf-8").replace(b"\n", newline) + newline
    return content[:start] + replacement + content[end:]


def update_outputs(root, stats, day):
    """Prepare both charts, history and README blocks before writing outputs."""
    root = Path(root)
    history_path = root / "docs/data/download-history.json"
    history = record_snapshot(json.loads(history_path.read_text(encoding="utf-8")), stats, day)
    pending = [(history_path, (json.dumps(history, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))]
    for filename, language in (("README.md", "en"), ("README.zh-CN.md", "zh-CN")):
        chart = render_chart(history, language).encode("utf-8")
        pending.append((root / f"docs/assets/downloads/download-trend.{language}.svg", chart))
        path = root / filename
        original = path.read_bytes()
        replacement = replace_block(original, render_block(stats, language, day + " UTC", history[0]["date"]))
        pending.append((path, replacement))
    for path, replacement in pending:
        if not path.exists() or replacement != path.read_bytes():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(replacement)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--releases-json", type=Path, help="Use an offline GitHub releases JSON list")
    arguments = parser.parse_args()
    if arguments.releases_json:
        releases = json.loads(arguments.releases_json.read_text(encoding="utf-8"))
    else:
        releases = fetch_releases(os.environ.get("GITHUB_TOKEN"))
    stats = summarize(releases)
    day = datetime.now(timezone.utc).date().isoformat()
    update_outputs(Path(__file__).resolve().parents[2], stats, day)
    print("Updated README download statistics: " + ", ".join(
        f"{key}={item['downloads']} downloads/{item['files']} files" for key, item in stats.items()
    ))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"Download statistics update failed: {error}", file=sys.stderr)
        sys.exit(1)
