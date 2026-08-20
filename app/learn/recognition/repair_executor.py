from __future__ import annotations

from typing import Any


GEOMETRY_SOURCE = "deterministic_atomic_evidence_union_v1"


def execute_deterministic_repair(stage2: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    request_id = str(request.get("repair_request_id") or "")
    parent_id = str(request.get("parent_region_id") or "")
    parent = _parent_region(stage2, parent_id)
    child_ids = sorted({str(item_id) for item_id in request.get("source_child_item_ids", []) if item_id})
    item_boxes = _item_boxes(parent)
    missing = sorted(item_id for item_id in child_ids if item_id not in item_boxes)
    if not child_ids or missing:
        return _failed_result(
            request_id,
            "atomic_evidence_missing",
            missing_child_item_ids=missing or child_ids,
        )

    evidence_bbox = _bbox_union([item_boxes[item_id] for item_id in child_ids])
    clipped = _clip_bbox(evidence_bbox, parent.get("bbox"))
    if clipped is None:
        return _failed_result(request_id, "atomic_evidence_outside_parent")

    replacement_id = f"{request_id}_deterministic_region"
    model_rough_roi = dict(request.get("rough_roi") or {})
    return {
        "repair_request_id": request_id,
        "status": "passed",
        "repair_route": str(request.get("repair_route") or "stage1_repartition"),
        "geometry_source": GEOMETRY_SOURCE,
        "replacement_regions": [
            {
                "region_id": replacement_id,
                "parent_region_id": parent_id,
                "role": str(request.get("expected_role") or "review_only"),
                "label": str(request.get("description") or request.get("expected_role") or "review region"),
                "bbox": clipped,
                "member_item_ids": child_ids,
            }
        ],
        "evidence": {
            "source_child_item_ids": child_ids,
            "source_removed_region_ids": sorted(
                {str(region_id) for region_id in request.get("source_removed_region_ids", []) if region_id}
            ),
            "atomic_union_bbox": dict(clipped),
            "model_rough_roi": model_rough_roi,
            "atomic_union_equals_rough_roi": clipped == model_rough_roi,
            "rough_roi_used_as_final_geometry": False,
        },
        "safety": _safety(),
    }


def execute_deterministic_repairs(stage2: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    results = [
        execute_deterministic_repair(stage2, request)
        for request in contract.get("requests", [])
        if isinstance(request, dict)
    ]
    return {
        "contract_version": "learning_review_repair_results_v1",
        "results": results,
        "safety": _safety(),
    }


def _parent_region(stage2: dict[str, Any], parent_id: str) -> dict[str, Any]:
    for region in stage2.get("regions", []):
        if isinstance(region, dict) and str(region.get("region_id") or "") == parent_id:
            if not _valid_bbox(region.get("bbox")):
                raise ValueError(f"repair parent bbox is invalid: {parent_id}")
            return region
    raise ValueError(f"repair parent is missing: {parent_id}")


def _item_boxes(parent: dict[str, Any]) -> dict[str, dict[str, int]]:
    return {
        str(item.get("item_id") or ""): _normalized_bbox(item["bbox"])
        for item in parent.get("numbered_items", [])
        if isinstance(item, dict) and item.get("item_id") and _valid_bbox(item.get("bbox"))
    }


def _bbox_union(boxes: list[dict[str, int]]) -> dict[str, int]:
    x1 = min(box["x"] for box in boxes)
    y1 = min(box["y"] for box in boxes)
    x2 = max(box["x"] + box["w"] for box in boxes)
    y2 = max(box["y"] + box["h"] for box in boxes)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _clip_bbox(value: dict[str, int], parent_value: Any) -> dict[str, int] | None:
    parent = _normalized_bbox(parent_value)
    x1 = max(value["x"], parent["x"])
    y1 = max(value["y"], parent["y"])
    x2 = min(value["x"] + value["w"], parent["x"] + parent["w"])
    y2 = min(value["y"] + value["h"], parent["y"] + parent["h"])
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and int(value.get("w") or 0) > 0
        and int(value.get("h") or 0) > 0
    )


def _normalized_bbox(value: Any) -> dict[str, int]:
    if not _valid_bbox(value):
        raise ValueError("bbox must have positive width and height")
    return {
        "x": int(value.get("x") or 0),
        "y": int(value.get("y") or 0),
        "w": int(value["w"]),
        "h": int(value["h"]),
    }


def _failed_result(
    request_id: str,
    failure_category: str,
    *,
    missing_child_item_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "repair_request_id": request_id,
        "status": "failed",
        "failure_category": failure_category,
        "missing_child_item_ids": missing_child_item_ids or [],
        "replacement_regions": [],
        "safety": _safety(),
    }


def _safety() -> dict[str, Any]:
    return {
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "real_clicks": 0,
        "live_fills": 0,
        "live_submits": 0,
    }
