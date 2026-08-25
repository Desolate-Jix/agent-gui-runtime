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


def restore_local_point_to_screen_exact(
    transform: dict[str, Any],
    local_point: dict[str, Any],
) -> dict[str, float]:
    """严格投影 ROI 点；拒绝越界，不执行裁剪或取最近点。"""

    roi, crop, scale_x, scale_y = _validated_exact_transform(transform)
    x = _finite_number(local_point.get("x") if isinstance(local_point, dict) else None, "local_point.x")
    y = _finite_number(local_point.get("y") if isinstance(local_point, dict) else None, "local_point.y")
    if not (0.0 < x < crop["width"] and 0.0 < y < crop["height"]):
        raise ValueError("local point is outside exact ROI crop")
    return {
        "x": roi["x"] + (x / scale_x),
        "y": roi["y"] + (y / scale_y),
    }


def project_screen_point_to_local_exact(
    transform: dict[str, Any],
    screen_point: dict[str, Any],
) -> dict[str, float]:
    """严格反投影截图点；拒绝 ROI 外坐标，不执行裁剪。"""

    roi, crop, scale_x, scale_y = _validated_exact_transform(transform)
    x = _finite_number(screen_point.get("x") if isinstance(screen_point, dict) else None, "screen_point.x")
    y = _finite_number(screen_point.get("y") if isinstance(screen_point, dict) else None, "screen_point.y")
    if not (
        roi["x"] < x < roi["x"] + roi["w"]
        and roi["y"] < y < roi["y"] + roi["h"]
    ):
        raise ValueError("screen point is outside exact ROI")
    local_x = (x - roi["x"]) * scale_x
    local_y = (y - roi["y"]) * scale_y
    if not (0.0 < local_x < crop["width"] and 0.0 < local_y < crop["height"]):
        raise ValueError("screen point cannot be represented by exact ROI transform")
    return {"x": local_x, "y": local_y}


def _validated_exact_transform(
    transform: dict[str, Any],
) -> tuple[dict[str, int], dict[str, int], float, float]:
    if not isinstance(transform, dict):
        raise ValueError("coordinate transform must be an object")
    roi = _normalize_bbox(transform.get("roi_bbox"))
    crop = _normalize_size(transform.get("crop_size"))
    if roi["w"] <= 0 or roi["h"] <= 0 or crop["width"] <= 0 or crop["height"] <= 0:
        raise ValueError("coordinate transform geometry must be positive")
    scale_x = _finite_number(transform.get("scale_x"), "coordinate_transform.scale_x")
    scale_y = _finite_number(transform.get("scale_y"), "coordinate_transform.scale_y")
    if scale_x <= 0.0 or scale_y <= 0.0:
        raise ValueError("coordinate transform scale must be positive")
    expected_x = crop["width"] / roi["w"]
    expected_y = crop["height"] / roi["h"]
    if abs(scale_x - expected_x) > 1e-6 or abs(scale_y - expected_y) > 1e-6:
        raise ValueError("coordinate transform scale does not match exact ROI geometry")
    return roi, crop, scale_x, scale_y


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    normalized = float(value)
    if normalized != normalized or normalized in {float("inf"), float("-inf")}:
        raise ValueError(f"{field} must be a finite number")
    return normalized


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
