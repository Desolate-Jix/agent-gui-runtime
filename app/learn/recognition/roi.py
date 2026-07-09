from __future__ import annotations

from typing import Any


def build_roi_crop_metadata(
    *,
    source_image_size: dict[str, Any],
    candidate_bbox: dict[str, Any],
    crop_size: dict[str, Any],
    expand_scale: float = 2.0,
) -> dict[str, Any]:
    source = _normalize_size(source_image_size)
    bbox = _normalize_bbox(candidate_bbox)
    crop = _normalize_size(crop_size)
    roi_bbox = _expanded_roi_bbox(source, bbox, expand_scale=max(1.0, float(expand_scale or 1.0)))
    scale_x = crop["width"] / roi_bbox["w"] if roi_bbox["w"] > 0 else 1.0
    scale_y = crop["height"] / roi_bbox["h"] if roi_bbox["h"] > 0 else 1.0
    return {
        "contract_version": "learn_roi_crop_v1",
        "source_image_size": source,
        "candidate_bbox": bbox,
        "crop_size": crop,
        "expand_scale": float(expand_scale or 1.0),
        "coordinate_transform": {
            "contract_version": "coordinate_transform_v1",
            "source_image_size": source,
            "roi_bbox": roi_bbox,
            "crop_size": crop,
            "scale_x": round(scale_x, 6),
            "scale_y": round(scale_y, 6),
        },
    }


def bounded_roi_crop_size_for_bbox(
    candidate_bbox: dict[str, Any],
    *,
    expand_scale: float = 2.0,
    max_width: int = 768,
    max_height: int = 512,
) -> dict[str, int]:
    """为模型定位生成有上限的 ROI 图尺寸。"""

    bbox = _normalize_bbox(candidate_bbox)
    raw_width = max(1, int(round(bbox["w"] * max(1.0, float(expand_scale or 1.0)))))
    raw_height = max(1, int(round(bbox["h"] * max(1.0, float(expand_scale or 1.0)))))
    return {
        "width": min(max(1, int(max_width)), raw_width),
        "height": min(max(1, int(max_height)), raw_height),
    }


def restore_local_point_to_screen(transform: dict[str, Any], local_point: dict[str, Any]) -> dict[str, int]:
    roi = _normalize_bbox(transform.get("roi_bbox") if isinstance(transform, dict) else {})
    scale_x = _positive_float(transform.get("scale_x") if isinstance(transform, dict) else None, 1.0)
    scale_y = _positive_float(transform.get("scale_y") if isinstance(transform, dict) else None, 1.0)
    x = _int_or_zero(local_point.get("x") if isinstance(local_point, dict) else None)
    y = _int_or_zero(local_point.get("y") if isinstance(local_point, dict) else None)
    return {
        "x": int(round(roi["x"] + (x / scale_x))),
        "y": int(round(roi["y"] + (y / scale_y))),
    }


def _expanded_roi_bbox(source: dict[str, int], bbox: dict[str, int], *, expand_scale: float) -> dict[str, int]:
    target_w = max(1, int(round(bbox["w"] * expand_scale)))
    target_h = max(1, int(round(bbox["h"] * expand_scale)))
    center_x = bbox["x"] + bbox["w"] / 2
    center_y = bbox["y"] + bbox["h"] / 2
    x = int(round(center_x - target_w / 2))
    y = int(round(center_y - target_h / 2))
    x = max(0, min(x, max(0, source["width"] - target_w)))
    y = max(0, min(y, max(0, source["height"] - target_h)))
    w = min(target_w, max(0, source["width"] - x))
    h = min(target_h, max(0, source["height"] - y))
    return {"x": x, "y": y, "w": w, "h": h}


def _normalize_bbox(value: dict[str, Any] | None) -> dict[str, int]:
    value = value if isinstance(value, dict) else {}
    return {
        "x": _int_or_zero(value.get("x")),
        "y": _int_or_zero(value.get("y")),
        "w": max(0, _int_or_zero(value.get("w"))),
        "h": max(0, _int_or_zero(value.get("h"))),
    }


def _normalize_size(value: dict[str, Any] | None) -> dict[str, int]:
    value = value if isinstance(value, dict) else {}
    return {
        "width": max(0, _int_or_zero(value.get("width"))),
        "height": max(0, _int_or_zero(value.get("height"))),
    }


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
