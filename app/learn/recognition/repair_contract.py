from __future__ import annotations

from copy import deepcopy
from typing import Any


CONTRACT_VERSION = "learning_generic_repair_requests_v1"


def compile_generic_repair_requests(
    stage2: dict[str, Any],
    validated_patch: dict[str, Any],
    repair_handoff: dict[str, Any],
) -> dict[str, Any]:
    if validated_patch.get("status") != "valid":
        raise ValueError("review patch must be validated before repair request compilation")

    groups = _group_records(stage2)
    removed_ids = {
        str(item.get("region_id") or "")
        for item in validated_patch.get("remove", [])
        if isinstance(item, dict) and item.get("region_id")
    }
    requests: list[dict[str, Any]] = []
    for handoff_key in ("stage1_repair_requests", "regions"):
        for source in repair_handoff.get(handoff_key, []):
            if not isinstance(source, dict):
                continue
            parent_id = str(source.get("parent_region_id") or "")
            rough_roi = deepcopy(source.get("rough_roi") or source.get("bbox") or {})
            candidate_id = str(source.get("candidate_id") or "").strip()
            matched = [] if candidate_id else [
                record
                for group_id, record in groups.items()
                if group_id in removed_ids
                and record["parent_region_id"] == parent_id
                and _bbox_overlap_ratio(record["bbox"], rough_roi) > 0.2
            ]
            matched.sort(key=lambda item: item["group_id"])
            candidate_member_ids = {
                str(item_id).strip()
                for item_id in source.get("candidate_member_item_ids", [])
                if str(item_id).strip()
            }
            child_ids = sorted(
                candidate_member_ids if candidate_id else {
                    child_id
                    for record in matched
                    for child_id in record["member_item_ids"]
                    if child_id
                }.union(candidate_member_ids)
            )
            requests.append(
                {
                    "repair_request_id": str(source.get("repair_request_id") or ""),
                    "repair_route": str(source.get("repair_route") or "precise_locator"),
                    "parent_region_id": parent_id,
                    "source_removed_region_ids": [record["group_id"] for record in matched],
                    "source_child_item_ids": child_ids,
                    "source_candidate_id": candidate_id,
                    "source_candidate_geometry": str(source.get("candidate_geometry_source") or ""),
                    "rough_roi": rough_roi,
                    "expected_role": str(source.get("expected_role") or "review_only"),
                    "description": str(source.get("description") or ""),
                    "completion_contract": {
                        "all_source_children_preserved": True,
                        "replacement_inside_parent": True,
                        "replacement_geometry_requires_evidence": True,
                        "rough_roi_is_not_final_geometry": True,
                        "no_duplicate_replacement_ids": True,
                    },
                    "safety": _safety(),
                }
            )

    return {
        "contract_version": CONTRACT_VERSION,
        "requests": requests,
        "request_count": len(requests),
        "linked_removed_region_count": len(
            {
                region_id
                for request in requests
                for region_id in request["source_removed_region_ids"]
            }
        ),
        "safety": _safety(),
    }


def _group_records(stage2: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for root in stage2.get("regions", []):
        if not isinstance(root, dict):
            continue
        parent_id = str(root.get("region_id") or "")
        for group in root.get("subregion_groups", []):
            if not isinstance(group, dict):
                continue
            group_id = str(group.get("group_id") or "")
            bbox = group.get("bbox")
            if not group_id or not isinstance(bbox, dict):
                continue
            records[group_id] = {
                "group_id": group_id,
                "parent_region_id": parent_id,
                "bbox": deepcopy(bbox),
                "member_item_ids": sorted(
                    {
                        str(item_id)
                        for item_id in (group.get("member_item_ids") or group.get("child_item_ids") or [])
                        if item_id
                    }
                ),
            }
    return records


def _bbox_overlap_ratio(left: dict[str, Any], right: dict[str, Any]) -> float:
    lx1, ly1, lx2, ly2 = _bbox_edges(left)
    rx1, ry1, rx2, ry2 = _bbox_edges(right)
    intersection = max(0, min(lx2, rx2) - max(lx1, rx1)) * max(
        0, min(ly2, ry2) - max(ly1, ry1)
    )
    left_area = max(1, (lx2 - lx1) * (ly2 - ly1))
    return intersection / left_area


def _bbox_edges(value: dict[str, Any]) -> tuple[int, int, int, int]:
    x = int(value.get("x") or 0)
    y = int(value.get("y") or 0)
    return x, y, x + int(value.get("w") or 0), y + int(value.get("h") or 0)


def _safety() -> dict[str, Any]:
    return {
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "real_clicks": 0,
        "live_fills": 0,
        "live_submits": 0,
    }
