#!/usr/bin/env python3
"""Render observed GitHub asset download totals as a self-contained SVG."""

from datetime import date, timedelta
from html import escape


DOWNLOAD_KEYS = ("installer", "update", "extension")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _observations(history, recent_only=True):
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
    if recent_only:
        cutoff = observations[-1][0] - timedelta(days=89)
        observations = [(day, row) for day, row in observations if day >= cutoff]
    return observations


def _estimate_points(estimate, observations):
    """Validate the frozen estimate and its bridge to the first observation."""
    if estimate is None:
        return []
    if not isinstance(estimate, dict):
        raise ValueError("Historical estimate must be an object")
    points = estimate.get("points", [])
    if not isinstance(points, list):
        raise ValueError("Historical estimate points must be a list")
    if not points:
        return []
    parsed = []
    previous = None
    for index, point in enumerate(points):
        if not isinstance(point, dict) or not isinstance(point.get("date"), str):
            raise ValueError(f"Estimate point {index} must have a date string")
        try:
            estimated_on = date.fromisoformat(point["date"])
        except ValueError as error:
            raise ValueError(f"Estimate point {index} has an invalid date") from error
        if estimated_on.isoformat() != point["date"]:
            raise ValueError(f"Estimate point {index} date must use YYYY-MM-DD")
        if previous is not None and estimated_on <= previous:
            raise ValueError("Estimate dates must be unique and strictly increasing")
        if type(point.get("total")) is not int or point["total"] < 0:
            raise ValueError(f"Estimate point {index} has an invalid total")
        parsed.append((estimated_on, point["total"]))
        previous = estimated_on
    first_day, first_row = observations[0]
    first_total = sum(first_row[key] for key in DOWNLOAD_KEYS)
    if estimate.get("cutoff") != first_day.isoformat() or parsed[-1] != (first_day, first_total):
        raise ValueError("Historical estimate must end at the first observed date and total")
    if parsed[0][1] != 0:
        raise ValueError("Historical estimate must start at zero")
    return parsed


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


def render_chart(history, language="en", estimate=None):
    """Return an accessible SVG of summed downloads with optional early estimates.

    ``history`` is a date-ordered list of dictionaries containing ``date``
    (YYYY-MM-DD UTC), ``installer``, ``update`` and ``extension`` integer totals.
    ``estimate`` may contain a ``cutoff`` date and ordered ``points`` with ``date``
    and ``total`` fields; its last point must match the first observation. With an
    estimate the entire history is shown; otherwise the last 90 calendar days are
    shown. Missing dates remain missing, and totals may decrease when assets disappear.
    This function performs no network or filesystem operations.
    """
    if language not in ("en", "zh-CN"):
        raise ValueError("Chart language must be en or zh-CN")
    observations = _observations(history, recent_only=False)
    estimated = _estimate_points(estimate, observations)
    if not estimated:
        observations = _observations(history)
    chinese = language == "zh-CN"
    first = estimated[0][0] if estimated else observations[0][0]
    latest = observations[-1][0]
    totals = [(day, sum(row[key] for key in DOWNLOAD_KEYS)) for day, row in observations]
    axis_start = first.replace(day=1)
    span = (latest - axis_start).days
    ticks = _vertical_ticks(max(total for _, total in estimated + totals))
    top, bottom, right = (75 if estimated else 65), 360, 870
    left = max(86, 42 + len(f"{ticks[-1]:,}") * 10)
    width = right - left

    def x(day):
        return left + width * (day - axis_start).days / span if span else left + width / 2

    def y(value):
        return bottom - (bottom - top) * value / ticks[-1]

    title = "累计下载历史" if chinese else "Cumulative download history"
    observed_first = observations[0][0]
    period = observed_first.isoformat() if observed_first == latest else f"{observed_first.isoformat()} – {latest.isoformat()}"
    description = (
        f"{period} UTC 的安装器、更新包及扩展资产累计下载总数之和。"
        f"最新观测：{totals[-1][1]:,}。未观测日期不代表零下载；资产删除可能使总数下降。"
        if chinese else
        f"Combined cumulative downloads of installer, update package and extension assets "
        f"observed from {period} UTC. Latest observation: {totals[-1][1]:,}. "
        "Missing days are not zero; totals may decrease when assets are removed."
    )
    estimate_note = "早期历史按版本发布日期估算" if chinese else "Earlier history estimated by release date"
    if estimated:
        description += f" {estimate_note}."
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="440" '
        f'viewBox="0 0 900 440" role="img" aria-labelledby="chart-title chart-desc" '
        f'lang="{language}">',
        f'<title id="chart-title">{escape(title)}</title>',
        f'<desc id="chart-desc">{escape(description)}</desc>',
        '<rect width="900" height="440" fill="#ffffff"/>',
        '<g font-family="Arial, Helvetica, sans-serif" fill="#111111">',
        f'<path d="M {left} {top} V {bottom} H {right}" fill="none" stroke="#111111" stroke-width="1"/>',
    ]
    legends = [("估算" if chinese else "Estimated", True), ("实测" if chinese else "Observed", False)] if estimated else [("实测" if chinese else "Observed", False)]
    for index, (label, dashed) in enumerate(legends):
        column = 310 + index * 180 if estimated else 390
        dash_attribute = ' stroke-dasharray="7 5"' if dashed else ""
        parts.extend([
            f'<line x1="{column}" y1="29" x2="{column + 28}" y2="29" '
            f'stroke="#f04426" stroke-width="2"{dash_attribute}/>',
            f'<text x="{column + 40}" y="35" font-size="18">{label}</text>',
        ])
    if estimated:
        parts.append(f'<text x="{left}" y="57" font-size="14" fill="#555555">{estimate_note}</text>')
    for value in ticks:
        position = y(value)
        parts.extend([
            f'<line x1="{left - 5}" y1="{position:.2f}" x2="{left}" y2="{position:.2f}" '
            'stroke="#111111" stroke-width="1"/>',
            f'<text x="{left - 12}" y="{position + 5:.2f}" text-anchor="end" '
            f'font-size="16">{value:,}</text>',
        ])
    month_ticks = []
    month = axis_start
    while month <= latest:
        month_ticks.append(month)
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    for tick_date in month_ticks:
        position = x(tick_date)
        anchor = "middle" if not span else "start" if tick_date == axis_start else "end" if tick_date == latest else "middle"
        label = f"{tick_date.year}年{tick_date.month}月" if chinese else f"{MONTHS[tick_date.month - 1]} {tick_date.year}"
        parts.extend([
            f'<line x1="{position:.2f}" y1="{bottom}" x2="{position:.2f}" '
            f'y2="{bottom + 5}" stroke="#111111" stroke-width="1"/>',
            f'<text x="{position:.2f}" y="389" text-anchor="{anchor}" '
            f'font-size="16">{label}</text>',
        ])
    if estimated:
        coordinates = " ".join(f"{x(day):.2f},{y(total):.2f}" for day, total in estimated)
        parts.append(
            f'<polyline id="series-estimated" points="{coordinates}" fill="none" stroke="#f04426" '
            'stroke-width="2" stroke-dasharray="7 5" stroke-linecap="round" stroke-linejoin="round"/>'
        )
    if len(totals) > 1:
        coordinates = " ".join(f"{x(day):.2f},{y(total):.2f}" for day, total in totals)
        parts.append(
            f'<polyline id="series-observed" points="{coordinates}" fill="none" stroke="#f04426" '
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
