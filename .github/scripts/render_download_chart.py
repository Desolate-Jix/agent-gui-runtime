#!/usr/bin/env python3
"""Render current release download counts accumulated by UTC release date."""

from datetime import date, datetime, timedelta, timezone
from html import escape


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _release_totals(snapshot):
    """Aggregate current counts by release day and prepend a zero baseline."""
    if not isinstance(snapshot, dict):
        raise ValueError("Download snapshot must be an object")
    counts_as_of = snapshot.get("counts_as_of")
    try:
        if not isinstance(counts_as_of, str) or date.fromisoformat(counts_as_of).isoformat() != counts_as_of:
            raise ValueError
    except ValueError as error:
        raise ValueError("counts_as_of must use YYYY-MM-DD") from error
    releases = snapshot.get("releases")
    if not isinstance(releases, list) or not releases:
        raise ValueError("Snapshot releases must be a non-empty list")
    daily = {}
    for index, release in enumerate(releases):
        if not isinstance(release, dict):
            raise ValueError(f"Release {index} must be an object")
        downloads = release.get("downloads")
        if type(downloads) is not int or downloads < 0:
            raise ValueError(f"Release {index} has an invalid downloads count")
        published = release.get("published_at")
        if not isinstance(published, str):
            raise ValueError(f"Release {index} must have a published_at string")
        try:
            published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
            if published_at.utcoffset() is None:
                raise ValueError
        except ValueError as error:
            raise ValueError(f"Release {index} has an invalid timezone-aware published_at") from error
        release_day = published_at.astimezone(timezone.utc).date()
        daily[release_day] = daily.get(release_day, 0) + downloads
    first_day = min(daily)
    origin = first_day.replace(day=1) if first_day.day != 1 else first_day - timedelta(days=1)
    totals = [(origin, 0)]
    running = 0
    for day, downloads in sorted(daily.items()):
        running += downloads
        totals.append((day, running))
    return counts_as_of, totals


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


def render_chart(snapshot, language="en"):
    """Return a self-contained SVG of current downloads accumulated by release date.

    ``snapshot`` contains ``counts_as_of`` (YYYY-MM-DD) and a non-empty ``releases``
    list. Each release supplies a timezone-aware ``published_at`` and nonnegative
    integer ``downloads``. Releases on the same UTC date are grouped and their
    current counts accumulated. The curve does not show when downloads occurred.
    This function performs no network or filesystem operations.
    """
    if language not in ("en", "zh-CN"):
        raise ValueError("Chart language must be en or zh-CN")
    counts_as_of, totals = _release_totals(snapshot)
    chinese = language == "zh-CN"
    first, latest = totals[0][0], totals[-1][0]
    span = (latest - first).days
    ticks = _vertical_ticks(totals[-1][1])
    top, bottom, right = 75, 360, 870
    left = max(86, 42 + len(f"{ticks[-1]:,}") * 10)
    width = right - left

    def x(day):
        return left + width * (day - first).days / span

    def y(value):
        return bottom - (bottom - top) * value / ticks[-1]

    title = "按版本发布日期累计下载量" if chinese else "Cumulative downloads by release date"
    note = f"截至 {counts_as_of}" if chinese else f"As of {counts_as_of}"
    description = (
        f"截至 {counts_as_of}，将各版本当前下载次数按 UTC 发布日期同日汇总后累加，"
        f"合计 {totals[-1][1]:,}。横轴并非下载发生日期。"
        if chinese else
        f"As of {counts_as_of}, current download counts for each release are grouped by "
        f"UTC publication date and accumulated, totaling {totals[-1][1]:,}. "
        "The horizontal axis does not represent when downloads occurred."
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="440" '
        f'viewBox="0 0 900 440" role="img" aria-labelledby="chart-title chart-desc" '
        f'lang="{language}">',
        f'<title id="chart-title">{escape(title)}</title>',
        f'<desc id="chart-desc">{escape(description)}</desc>',
        '<rect width="900" height="440" fill="#ffffff"/>',
        '<g font-family="Arial, Helvetica, sans-serif" fill="#111111">',
        f'<text x="450" y="29" text-anchor="middle" font-size="22" font-weight="600">{escape(title)}</text>',
        f'<text x="450" y="54" text-anchor="middle" font-size="14" fill="#555555">{note}</text>',
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
    month = first.replace(day=1)
    if month < first:
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    while month <= latest:
        position = x(month)
        anchor = "start" if month == first else "end" if month == latest else "middle"
        label = f"{month.year}年{month.month}月" if chinese else f"{MONTHS[month.month - 1]} {month.year}"
        parts.extend([
            f'<line x1="{position:.2f}" y1="{bottom}" x2="{position:.2f}" '
            f'y2="{bottom + 5}" stroke="#111111" stroke-width="1"/>',
            f'<text x="{position:.2f}" y="389" text-anchor="{anchor}" '
            f'font-size="16">{label}</text>',
        ])
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    coordinates = " ".join(f"{x(day):.2f},{y(total):.2f}" for day, total in totals)
    parts.append(
        f'<polyline id="series-downloads" points="{coordinates}" fill="none" stroke="#f04426" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
    )
    date_label = "版本发布日期" if chinese else "Release date"
    downloads_label = "累计下载" if chinese else "Downloads"
    parts.append(f'<text x="{(left + right) / 2:.2f}" y="427" text-anchor="middle" font-size="18">{date_label}</text>')
    parts.append(
        f'<text x="23" y="{(top + bottom) / 2:.2f}" text-anchor="middle" font-size="18" '
        f'transform="rotate(-90 23 {(top + bottom) / 2:.2f})">{downloads_label}</text>'
    )
    parts.extend(['</g>', '</svg>'])
    return "\n".join(parts) + "\n"
