from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.learn.recognition.roi import restore_local_point_to_screen


def build_grounding_request(
    *,
    item: dict[str, Any],
    roi_crop: dict[str, Any],
    goal: str | None = None,
) -> dict[str, Any]:
    """为 ROI grounding 模型构造稳定请求合同。"""

    return {
        "contract_version": "learn_grounding_request_v1",
        "authorization": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_action_requires_gate": True,
            "final_submit_forbidden": True,
        },
        "goal": str(goal or item.get("label") or item.get("item_id") or "locate target"),
        "target": {
            "item_id": item.get("item_id"),
            "label": str(item.get("label") or ""),
            "item_type": str(item.get("item_type") or ""),
            "role": str(item.get("role") or ""),
            "candidate_bbox": deepcopy(item.get("bbox") or {}),
            "candidate_bbox_in_roi": _candidate_bbox_in_roi(
                item.get("bbox") if isinstance(item.get("bbox"), dict) else {},
                roi_crop.get("coordinate_transform") if isinstance(roi_crop.get("coordinate_transform"), dict) else {},
            ),
            "source_evidence": deepcopy(item.get("source_evidence") or []),
            "interactable_evidence": deepcopy(item.get("interactable_evidence") or {}),
        },
        "roi_crop": deepcopy(roi_crop),
        "accepted_output_contracts": [
            "screen_point",
            "roi_local_point",
            "coordinate_space=uground_0_999 + point_999/raw_output",
            "coordinate_space=normalized_0_1000 + point_1000/raw_output",
            "coordinate_space=normalized_0_1 + normalized_point/raw_output",
        ],
        "required_evidence": [
            "coordinate_transform_replay",
            "screenshot_freshness",
            "point_inside_expected_bbox",
        ],
    }


def normalize_grounding_result_to_screen(
    result: dict[str, Any],
    *,
    roi_crop: dict[str, Any],
) -> dict[str, Any]:
    """把不同 grounding 模型的 ROI-local / normalized 点位还原成整屏点位。"""

    normalized = deepcopy(result) if isinstance(result, dict) else {}
    if isinstance(normalized.get("screen_point"), dict):
        return normalized

    local_point = local_point_from_grounding_result(normalized, roi_crop=roi_crop)
    if local_point is None:
        return normalized

    transform = roi_crop.get("coordinate_transform") if isinstance(roi_crop.get("coordinate_transform"), dict) else {}
    normalized["screen_point"] = restore_local_point_to_screen(transform, local_point)
    normalized.setdefault("debug", {})
    normalized["debug"]["local_point_restored_to_screen"] = True
    normalized["debug"]["restored_local_point"] = local_point
    normalized["debug"]["coordinate_space"] = str(normalized.get("coordinate_space") or "roi_pixel")
    evidence = normalized.get("evidence") if isinstance(normalized.get("evidence"), dict) else {}
    evidence.setdefault("coordinate_transform_replay", True)
    normalized["evidence"] = evidence
    return normalized


def local_point_from_grounding_result(
    result: dict[str, Any],
    *,
    roi_crop: dict[str, Any],
) -> dict[str, int] | None:
    for key in ("roi_local_point", "local_point"):
        value = result.get(key) if isinstance(result, dict) else None
        if isinstance(value, dict):
            return {"x": _int_or_zero(value.get("x")), "y": _int_or_zero(value.get("y"))}

    coordinate_space = str(result.get("coordinate_space") or "").casefold() if isinstance(result, dict) else ""
    if coordinate_space in {"roi_local_point", "local_point", "roi_pixel", "roi_pixels"}:
        point = _point_from_mapping_or_text(result.get("roi_local_point") or result.get("local_point") or result.get("raw_output"))
        if point is None:
            return None
        return {"x": _int_or_zero(point.get("x")), "y": _int_or_zero(point.get("y"))}

    if coordinate_space in {"uground_0_999", "normalized_0_999"}:
        point = _point_from_mapping_or_text(result.get("point_999") or result.get("normalized_point") or result.get("raw_output"))
        if point is None:
            return None
        crop = roi_crop.get("crop_size") if isinstance(roi_crop.get("crop_size"), dict) else {}
        return {
            "x": _int_or_zero((_float_or_zero(point.get("x")) / 999.0) * max(1, _int_or_zero(crop.get("width")))),
            "y": _int_or_zero((_float_or_zero(point.get("y")) / 999.0) * max(1, _int_or_zero(crop.get("height")))),
        }

    if coordinate_space in {"normalized_0_1000", "vista_normalized_0_1000", "0_1000", "normalized"}:
        point = _point_from_mapping_or_text(result.get("point_1000") or result.get("normalized_point") or result.get("raw_output"))
        if point is None:
            return None
        crop = roi_crop.get("crop_size") if isinstance(roi_crop.get("crop_size"), dict) else {}
        return {
            "x": _int_or_zero((_float_or_zero(point.get("x")) / 1000.0) * max(1, _int_or_zero(crop.get("width")))),
            "y": _int_or_zero((_float_or_zero(point.get("y")) / 1000.0) * max(1, _int_or_zero(crop.get("height")))),
        }

    if coordinate_space in {"normalized_0_1", "roi_normalized_0_1"}:
        point = _point_from_mapping_or_text(result.get("normalized_point") or result.get("raw_output"))
        if point is None:
            return None
        crop = roi_crop.get("crop_size") if isinstance(roi_crop.get("crop_size"), dict) else {}
        return {
            "x": _int_or_zero(_float_or_zero(point.get("x")) * max(1, _int_or_zero(crop.get("width")))),
            "y": _int_or_zero(_float_or_zero(point.get("y")) * max(1, _int_or_zero(crop.get("height")))),
        }

    return None


def _point_from_mapping_or_text(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list) and len(value) >= 2:
        return {"x": value[0], "y": value[1]}
    text = str(value or "")
    if not text:
        return None
    matches = re.findall(r"-?\d+(?:\.\d+)?", text)
    if len(matches) < 2:
        return None
    return {"x": matches[0], "y": matches[1]}


def _candidate_bbox_in_roi(candidate_bbox: dict[str, Any], transform: dict[str, Any]) -> dict[str, int]:
    bbox = _normalized_bbox(candidate_bbox)
    roi = _normalized_bbox(transform.get("roi_bbox") if isinstance(transform, dict) else {})
    scale_x = _positive_float(transform.get("scale_x") if isinstance(transform, dict) else None, 1.0)
    scale_y = _positive_float(transform.get("scale_y") if isinstance(transform, dict) else None, 1.0)
    return {
        "x": _int_or_zero((bbox["x"] - roi["x"]) * scale_x),
        "y": _int_or_zero((bbox["y"] - roi["y"]) * scale_y),
        "w": max(0, _int_or_zero(bbox["w"] * scale_x)),
        "h": max(0, _int_or_zero(bbox["h"] * scale_y)),
    }


def _normalized_bbox(value: dict[str, Any] | None) -> dict[str, int]:
    value = value if isinstance(value, dict) else {}
    return {
        "x": _int_or_zero(value.get("x")),
        "y": _int_or_zero(value.get("y")),
        "w": max(0, _int_or_zero(value.get("w"))),
        "h": max(0, _int_or_zero(value.get("h"))),
    }


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0
