from __future__ import annotations

from typing import Any, Optional


def window_rect(bound: Any) -> dict[str, int]:
    left = int(bound.rect.left)
    top = int(bound.rect.top)
    right = int(bound.rect.right)
    bottom = int(bound.rect.bottom)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def window_size_bucket(rect: dict[str, int]) -> str:
    return f"{rect['width']}x{rect['height']}"


def locate_mouse_tester_panel(bound: Any) -> dict[str, Any]:
    rect = window_rect(bound)
    return {
        "x": int(rect["width"] * 0.16),
        "y": int(rect["height"] * 0.48),
        "width": int(rect["width"] * 0.48),
        "height": int(rect["height"] * 0.40),
        "source": "window_relative_fixed_roi",
    }


def generate_zone_points(
    zone: dict[str, Any],
    preferred_norm_point: Optional[dict[str, float]] = None,
) -> list[dict[str, Any]]:
    inset_x = max(8, int(zone["width"] * 0.18))
    inset_y = max(8, int(zone["height"] * 0.18))
    left = zone["x"] + inset_x
    right = zone["x"] + zone["width"] - inset_x
    top = zone["y"] + inset_y
    bottom = zone["y"] + zone["height"] - inset_y
    mid_x = int(round((left + right) / 2))
    mid_y = int(round((top + bottom) / 2))
    points = [
        {"x": left, "y": top, "label": "top_left"},
        {"x": mid_x, "y": top, "label": "top_center"},
        {"x": right, "y": top, "label": "top_right"},
        {"x": left, "y": mid_y, "label": "center_left"},
        {"x": mid_x, "y": mid_y, "label": "center"},
        {"x": right, "y": mid_y, "label": "center_right"},
        {"x": left, "y": bottom, "label": "bottom_left"},
        {"x": mid_x, "y": bottom, "label": "bottom_center"},
        {"x": right, "y": bottom, "label": "bottom_right"},
    ]
    if preferred_norm_point is not None:
        preferred = {
            "x": int(zone["x"] + zone["width"] * preferred_norm_point["nx"]),
            "y": int(zone["y"] + zone["height"] * preferred_norm_point["ny"]),
            "label": "preferred_cached_point",
        }
        points = [preferred] + [
            point
            for point in points
            if point["x"] != preferred["x"] or point["y"] != preferred["y"]
        ]
    return points


def normalized_point(zone: dict[str, Any], point: dict[str, Any]) -> dict[str, float]:
    return {
        "nx": round((point["x"] - zone["x"]) / max(1, zone["width"]), 4),
        "ny": round((point["y"] - zone["y"]) / max(1, zone["height"]), 4),
    }
