#!/usr/bin/env python3
"""Render observed GitHub asset download totals as a self-contained SVG."""

from datetime import date, timedelta
from html import escape


DOWNLOAD_KEYS = ("installer", "update", "extension")


def _observations(history):
    """Validate the observations without sorting or changing their values."""
    if not isinstance(history, list) or not history:
        raise ValueError("Download history must be a non-empty list")
    observations = []
    previous = None
    for index, row in enumerate(history):
        if not isinstance(row, dict) or not isinstance(row.get("date"), str):
            raise ValueError(f"History row {index} must have a date string")
        try:
            observed_on = date.fromisoformat(row["date"])
        except ValueError as error:
            raise ValueError(f"History row {index} has an invalid date") from error
        if observed_on.isoformat() != row["date"]:
            raise ValueError(f"History row {index} date must use YYYY-MM-DD")
        if previous is not None and observed_on <= previous:
            raise ValueError("History dates must be unique and strictly increasing")
        for key in DOWNLOAD_KEYS:
            if type(row.get(key)) is not int or row[key] < 0:
                raise ValueError(f"History row {index} has an invalid {key} total")
        observations.append((observed_on, row))
        previous = observed_on
    cutoff = observations[-1][0] - timedelta(days=89)
    return [(day, row) for day, row in observations if day >= cutoff]


def _vertical_ticks(maximum):
    """Use integer 1/2/5 steps and leave an all-zero chart readable."""
    if maximum == 0:
        return list(range(6))
    minimum_step = (maximum + 4) // 5
    magnitude = 10 ** (len(str(minimum_step)) - 1)
    step = next(value * magnitude for value in (1, 2, 5, 10)
                if value * magnitude >= minimum_step)
    upper = ((maximum + step - 1) // step) * step
    return list(range(0, upper + 1, step))


def render_chart(history, language="en"):
    """Return an accessible SVG for the last 90 calendar days of observations.

    ``history`` is a date-ordered list of dictionaries containing ``date``
    (YYYY-MM-DD UTC), ``installer``, ``update`` and ``extension`` integer totals.
    The curve sums the three components. Missing dates remain missing, and totals
    may decrease when assets disappear.
    This function performs no network or filesystem operations.
    """
    if language not in ("en", "zh-CN"):
        raise ValueError("Chart language must be en or zh-CN")
    observations = _observations(history)
    chinese = language == "zh-CN"
    first, latest = observations[0][0], observations[-1][0]
    totals = [(day, sum(row[key] for key in DOWNLOAD_KEYS)) for day, row in observations]
    span = (latest - first).days
    ticks = _vertical_ticks(max(total for _, total in totals))
    top, bottom, right = 65, 360, 870
    left = max(86, 42 + len(f"{ticks[-1]:,}") * 10)
    width = right - left

    def x(day):
        return left + width * (day - first).days / span if span else left + width / 2

    def y(value):
        return bottom - (bottom - top) * value / ticks[-1]

    title = "累计下载历史" if chinese else "Cumulative download history"
    period = first.isoformat() if first == latest else f"{first.isoformat()} – {latest.isoformat()}"
    description = (
        f"{period} UTC 的安装器、更新包及扩展资产累计下载总数之和。"
        f"最新观测：{totals[-1][1]:,}。未观测日期不代表零下载；资产删除可能使总数下降。"
        if chinese else
        f"Combined cumulative downloads of installer, update package and extension assets "
        f"observed from {period} UTC. Latest observation: {totals[-1][1]:,}. "
        "Missing days are not zero; totals may decrease when assets are removed."
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="440" '
        f'viewBox="0 0 900 440" role="img" aria-labelledby="chart-title chart-desc" '
        f'lang="{language}">',
        f'<title id="chart-title">{escape(title)}</title>',
        f'<desc id="chart-desc">{escape(description)}</desc>',
        '<rect width="900" height="440" fill="#ffffff"/>',
        '<g font-family="Arial, Helvetica, sans-serif" fill="#111111">',
        '<line x1="279" y1="29" x2="307" y2="29" stroke="#f04426" stroke-width="2"/>',
        '<text x="317" y="35" font-size="18">Desolate-Jix/agent-gui-runtime</text>',
        f'<path d="M {left} {top} V {bottom} H {right}" fill="none" stroke="#111111" stroke-width="1"/>',
    ]
    for value in ticks:
        position = y(value)
        parts.extend([
            f'<line x1="{left - 5}" y1="{position:.2f}" x2="{left}" y2="{position:.2f}" '
            'stroke="#111111" stroke-width="1"/>',
            f'<text x="{left - 12}" y="{position + 5:.2f}" text-anchor="end" '
            f'font-size="16">{value:,}</text>',
        ])
    date_offsets = sorted({round(index * span / min(5, span)) for index in range(min(5, span) + 1)}) if span else [0]
    for offset in date_offsets:
        tick_date = first + timedelta(days=offset)
        position = x(tick_date)
        anchor = "middle" if not span else "start" if offset == 0 else "end" if offset == span else "middle"
        parts.extend([
            f'<line x1="{position:.2f}" y1="{bottom}" x2="{position:.2f}" '
            f'y2="{bottom + 5}" stroke="#111111" stroke-width="1"/>',
            f'<text x="{position:.2f}" y="389" text-anchor="{anchor}" '
            f'font-size="16">{tick_date.isoformat()}</text>',
        ])
    if len(totals) > 1:
        coordinates = " ".join(f"{x(day):.2f},{y(total):.2f}" for day, total in totals)
        parts.append(
            f'<polyline points="{coordinates}" fill="none" stroke="#f04426" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    else:
        day, total = totals[0]
        parts.append(f'<circle cx="{x(day):.2f}" cy="{y(total):.2f}" r="3" fill="#f04426"/>')
    date_label = "日期" if chinese else "Date"
    downloads_label = "累计下载" if chinese else "Downloads"
    parts.append(f'<text x="{(left + right) / 2:.2f}" y="427" text-anchor="middle" font-size="18">{date_label}</text>')
    parts.append(
        f'<text x="23" y="{(top + bottom) / 2:.2f}" text-anchor="middle" font-size="18" '
        f'transform="rotate(-90 23 {(top + bottom) / 2:.2f})">{downloads_label}</text>'
    )
    parts.extend(['</g>', '</svg>'])
    return "\n".join(parts) + "\n"
