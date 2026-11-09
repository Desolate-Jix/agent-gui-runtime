#!/usr/bin/env python3
"""Render observed GitHub asset download totals as a self-contained SVG."""

from datetime import date, timedelta
from html import escape


SERIES = (
    ("installer", "Execution installer", "执行版安装器", "#60a5fa", None, 6),
    ("update", "Runtime update package", "Runtime 更新包", "#67e8f9", "10 6", 4.5),
    ("extension", "Amadeus extension", "Amadeus 扩展", "#2dd4bf", "3 6", 3),
)


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
        for key, *_ in SERIES:
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
    Missing dates remain missing, and totals may decrease when assets disappear.
    This function performs no network or filesystem operations.
    """
    if language not in ("en", "zh-CN"):
        raise ValueError("Chart language must be en or zh-CN")
    observations = _observations(history)
    chinese = language == "zh-CN"
    first, latest = observations[0][0], observations[-1][0]
    latest_row = observations[-1][1]
    span = (latest - first).days
    ticks = _vertical_ticks(max(row[key] for _, row in observations for key, *_ in SERIES))
    top, bottom, right = 190, 386, 920
    left = max(84, 28 + len(f"{ticks[-1]:,}") * 11)
    width = right - left

    def x(day):
        return left + width * (day - first).days / span if span else left + width / 2

    def y(value):
        return bottom - (bottom - top) * value / ticks[-1]

    title = "累计下载趋势" if chinese else "Cumulative downloads"
    period = first.isoformat() if first == latest else f"{first.isoformat()} – {latest.isoformat()}"
    subtitle = (
        f"每日快照 · {period} UTC · 最近 90 天"
        if chinese else f"Daily snapshots · {period} UTC · Last 90 days"
    )
    footnote = (
        "每日观测总数；未观测日期不代表零下载。"
        if chinese else "Observed daily totals; missing days are not zero."
    )
    waiting = "等待更多每日观测数据" if chinese else "Waiting for more daily observations"
    latest_summary = "; ".join(
        f"{zh if chinese else en}: {latest_row[key]:,}"
        for key, en, zh, *_ in SERIES
    )
    description = (
        f"{period} UTC 的 GitHub Releases 资产累计下载总数。{footnote} 最新观测：{latest_summary}。"
        if chinese else
        f"Cumulative GitHub Releases asset download totals observed from {period} UTC. "
        f"{footnote} Latest observation: {latest_summary}."
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="960" height="500" '
        f'viewBox="0 0 960 500" role="img" aria-labelledby="chart-title chart-desc" '
        f'lang="{language}">',
        f'<title id="chart-title">{escape(title)}</title>',
        f'<desc id="chart-desc">{escape(description)}</desc>',
        '<rect x="1" y="1" width="958" height="498" rx="18" fill="#0b1424" stroke="#25364d"/>',
        '<g font-family="system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif">',
        f'<text x="32" y="44" fill="#f1f5f9" font-size="28" font-weight="700">{escape(title)}</text>',
        f'<text x="32" y="75" fill="#a9bad0" font-size="17">{escape(subtitle)}</text>',
    ]
    for index, (key, english, zh, color, dash, _) in enumerate(SERIES):
        column = 32 + index * 302
        dash_attribute = f' stroke-dasharray="{dash}"' if dash else ""
        parts.extend([
            f'<line x1="{column}" y1="111" x2="{column + 28}" y2="111" '
            f'stroke="{color}" stroke-width="3" stroke-linecap="round"{dash_attribute}/>',
            f'<text x="{column + 39}" y="117" fill="#cbd5e1" font-size="20">'
            f'{escape(zh if chinese else english)}</text>',
            f'<text x="{column + 39}" y="149" fill="{color}" font-size="27" '
            f'font-weight="700">{latest_row[key]:,}</text>',
        ])
    axis_label = "累计下载次数" if chinese else "Cumulative downloads"
    parts.append(f'<text x="{left}" y="177" fill="#a9bad0" font-size="17">{axis_label}</text>')
    for value in ticks:
        position = y(value)
        parts.extend([
            f'<line x1="{left}" y1="{position:.2f}" x2="{right}" y2="{position:.2f}" '
            'stroke="#293a50" stroke-width="1"/>',
            f'<text x="{left - 14}" y="{position + 6:.2f}" text-anchor="end" '
            f'fill="#a9bad0" font-size="18">{value:,}</text>',
        ])
    date_offsets = sorted({round(index * span / min(5, span)) for index in range(min(5, span) + 1)}) if span else [0]
    for offset in date_offsets:
        tick_date = first + timedelta(days=offset)
        position = x(tick_date)
        anchor = "middle" if not span else "start" if offset == 0 else "end" if offset == span else "middle"
        parts.extend([
            f'<line x1="{position:.2f}" y1="{bottom}" x2="{position:.2f}" '
            f'y2="{bottom + 6}" stroke="#53677f"/>',
            f'<text x="{position:.2f}" y="416" text-anchor="{anchor}" '
            f'fill="#a9bad0" font-size="18">{tick_date.isoformat()}</text>',
        ])
    for key, english, zh, color, dash, radius in SERIES:
        label = zh if chinese else english
        parts.append(f'<g id="series-{key}"><title>{escape(label)}</title>')
        if len(observations) > 1:
            coordinates = " ".join(f"{x(day):.2f},{y(row[key]):.2f}" for day, row in observations)
            dash_attribute = f' stroke-dasharray="{dash}"' if dash else ""
            parts.append(
                f'<polyline points="{coordinates}" fill="none" stroke="{color}" '
                f'stroke-width="3" stroke-linecap="round" stroke-linejoin="round"{dash_attribute}/>'
            )
        marked = observations if len(observations) <= 14 else observations[-1:]
        for day, row in marked:
            parts.append(
                f'<circle cx="{x(day):.2f}" cy="{y(row[key]):.2f}" r="{radius}" '
                f'fill="{color}" stroke="#0b1424" stroke-width="1.5">'
                f'<title>{escape(label)} · {day.isoformat()} UTC: {row[key]:,}</title></circle>'
            )
        parts.append('</g>')
    date_label = "日期（UTC）" if chinese else "Date (UTC)"
    parts.append(f'<text x="{right}" y="447" text-anchor="end" fill="#a9bad0" font-size="17">{date_label}</text>')
    parts.append(f'<text x="32" y="480" fill="#a9bad0" font-size="17">{escape(footnote)}</text>')
    if len(observations) == 1:
        parts.append(f'<text x="{left}" y="447" fill="#cbd5e1" font-size="17">{waiting}</text>')
    parts.extend(['</g>', '</svg>'])
    return "\n".join(parts) + "\n"
