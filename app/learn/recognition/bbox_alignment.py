from __future__ import annotations

from typing import Any


def bbox_overlap(a: dict[str, Any], b: dict[str, Any]) -> dict[str, float]:
    ax, ay, aw, ah = bbox_numbers(a)
    bx, by, bw, bh = bbox_numbers(b)
    area_a = aw * ah
    area_b = bw * bh
    if area_a <= 0 or area_b <= 0:
        return {"iou": 0.0, "vision_coverage": 0.0, "support_coverage": 0.0, "area_ratio": 0.0}
    x1 = max(ax, bx)
    y1 = max(ay, by)
    x2 = min(ax + aw, bx + bw)
    y2 = min(ay + ah, by + bh)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = area_a + area_b - intersection
    return {
        "iou": round(intersection / union, 4) if union > 0 else 0.0,
        "vision_coverage": round(intersection / area_a, 4),
        "support_coverage": round(intersection / area_b, 4),
        "area_ratio": round(area_a / area_b, 4),
    }


def bbox_numbers(bbox: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        _float_or_zero(bbox.get("x")),
        _float_or_zero(bbox.get("y")),
        max(0.0, _float_or_zero(bbox.get("w"))),
        max(0.0, _float_or_zero(bbox.get("h"))),
    )


def cross_evidence_overlap_is_acceptable(overlap: dict[str, float]) -> bool:
    if overlap["iou"] >= 0.35:
        return True
    if overlap["vision_coverage"] >= 0.65 and overlap["support_coverage"] >= 0.65:
        return True
    return overlap["support_coverage"] >= 0.9 and 0.5 <= overlap["area_ratio"] <= 2.5


def evaluate_bbox_alignment(parser_bbox: dict[str, Any], support_bbox: dict[str, Any]) -> dict[str, Any]:
    overlap = bbox_overlap(parser_bbox, support_bbox)
    passed = cross_evidence_overlap_is_acceptable(overlap)
    return {
        "method": "learn_recognition_cross_evidence_overlap_v1",
        "passed": passed,
        "thresholds": {
            "iou_min": 0.35,
            "mutual_coverage_min": 0.65,
            "support_coverage_min": 0.9,
            "area_ratio_min": 0.5,
            "area_ratio_max": 2.5,
        },
        **overlap,
    }


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
