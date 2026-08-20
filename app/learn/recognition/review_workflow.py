from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.learn.recognition.model_review import (
    ALLOWED_REVIEW_ROLES,
    apply_review_patch,
    build_missing_locator_tasks,
)
from app.learn.recognition.repair_contract import compile_generic_repair_requests


WORKFLOW_CONTRACT = "learning_review_repair_workflow_v1"
TRUSTED_REPAIR_GEOMETRY_SOURCES = {
    "deterministic_atomic_evidence_union_v1",
    "deterministic_stage1_repartition_v1",
    "precise_locator_gate_passed_v1",
}


def build_removal_resolutions(
    stage2: dict[str, Any],
    reviewed_stage2: dict[str, Any],
    validated_patch: dict[str, Any],
    repair_handoff: dict[str, Any],
) -> list[dict[str, Any]]:
    if validated_patch.get("status") != "valid":
        raise ValueError("review patch must be validated before resolving removals")
    removed = [item for item in validated_patch.get("remove", []) if isinstance(item, dict)]
    groups = _group_records(stage2)
    reviewed_item_ids = _numbered_item_ids(reviewed_stage2)
    repairs = [
        deepcopy(item)
        for key in ("stage1_repair_requests", "regions")
        for item in repair_handoff.get(key, [])
        if isinstance(item, dict)
    ]
    repairs.sort(key=lambda item: 0 if item.get("repair_route") == "stage1_repartition" else 1)

    resolutions: list[dict[str, Any]] = []
    for removal in removed:
        region_id = str(removal.get("region_id") or "")
        record = groups.get(region_id)
        if record is None:
            raise ValueError(f"removed group does not exist in source Stage2: {region_id}")
        preserved = sorted(set(record["member_item_ids"]).intersection(reviewed_item_ids))
        repair = next(
            (
                item
                for item in repairs
                if item.get("repair_route") == "stage1_repartition"
                and not str(item.get("candidate_id") or "").strip()
                and item.get("parent_region_id") == record["parent_region_id"]
                and _bbox_overlap_ratio(record["bbox"], item.get("rough_roi") or item.get("bbox") or {}) > 0.2
            ),
            None,
        )
        if repair is not None:
            route = str(repair.get("repair_route") or "precise_locator")
            resolutions.append(
                {
                    "removed_region_id": region_id,
                    "content_disposition": route,
                    "preserved_child_ids": preserved,
                    "replacement_region_ids": [],
                    "replacement_parent_id": record["parent_region_id"],
                    "repair_request_id": str(repair.get("repair_request_id") or ""),
                    "repair_route": route,
                    "coverage_status": "repair_pending",
                    "reason": "removed wrapper overlaps a declared repair request",
                }
            )
            continue
        if preserved:
            resolutions.append(
                {
                    "removed_region_id": region_id,
                    "content_disposition": "children_reparented",
                    "preserved_child_ids": preserved,
                    "replacement_region_ids": [],
                    "replacement_parent_id": record["parent_region_id"],
                    "repair_request_id": None,
                    "repair_route": None,
                    "coverage_status": "resolved",
                    "reason": "existing atomic children remain under the Stage1 parent",
                }
            )
            continue
        resolutions.append(
            {
                "removed_region_id": region_id,
                "content_disposition": "needs_human_review",
                "preserved_child_ids": [],
                "replacement_region_ids": [],
                "replacement_parent_id": record["parent_region_id"],
                "repair_request_id": None,
                "repair_route": None,
                "coverage_status": "unresolved",
                "reason": "removed wrapper has no preserved atomic children or repair request",
            }
        )
    return resolutions


def run_review_repair_workflow(
    *,
    stage2: dict[str, Any],
    validated_patch: dict[str, Any],
    screenshot_path: str,
    repair_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reviewed = apply_review_patch(stage2, validated_patch)
    repair_handoff = build_missing_locator_tasks(stage2, validated_patch, screenshot_path)
    generic_repair_requests = compile_generic_repair_requests(
        stage2,
        validated_patch,
        repair_handoff,
    )
    resolutions = build_removal_resolutions(stage2, reviewed, validated_patch, repair_handoff)
    recomposed = deepcopy(reviewed)
    result_by_id = _repair_results_by_id(repair_results)
    workflow_errors: list[dict[str, str]] = []
    repair_requests = {
        str(item.get("repair_request_id") or ""): item
        for key in ("stage1_repair_requests", "regions")
        for item in repair_handoff.get(key, [])
        if isinstance(item, dict) and item.get("repair_request_id")
    }
    applied_request_ids: set[str] = set()

    for resolution in resolutions:
        if resolution["coverage_status"] != "repair_pending":
            continue
        request_id = str(resolution.get("repair_request_id") or "")
        repair = result_by_id.get(request_id)
        if repair is None:
            continue
        if repair.get("status") != "passed":
            resolution["coverage_status"] = "repair_failed"
            workflow_errors.append({"repair_request_id": request_id, "category": "repair_failed"})
            continue
        geometry_source = str(repair.get("geometry_source") or "")
        if geometry_source not in TRUSTED_REPAIR_GEOMETRY_SOURCES:
            resolution["coverage_status"] = "repair_failed"
            workflow_errors.append({"repair_request_id": request_id, "category": "untrusted_repair_geometry"})
            continue
        try:
            replacement_ids = _apply_replacement_regions(
                recomposed,
                repair,
                expected_parent_id=str(resolution.get("replacement_parent_id") or ""),
            )
        except ValueError as exc:
            resolution["coverage_status"] = "repair_failed"
            workflow_errors.append(
                {"repair_request_id": request_id, "category": "replacement_incomplete", "message": str(exc)}
            )
            continue
        resolution["replacement_region_ids"] = replacement_ids
        resolution["coverage_status"] = "resolved"
        resolution["reason"] = "trusted repair result supplied replacement regions"
        applied_request_ids.add(request_id)

    for request_id, request in repair_requests.items():
        if request_id in applied_request_ids:
            continue
        repair = result_by_id.get(request_id)
        if repair is None:
            continue
        if repair.get("status") != "passed":
            workflow_errors.append({"repair_request_id": request_id, "category": "repair_failed"})
            continue
        geometry_source = str(repair.get("geometry_source") or "")
        if geometry_source not in TRUSTED_REPAIR_GEOMETRY_SOURCES:
            workflow_errors.append({"repair_request_id": request_id, "category": "untrusted_repair_geometry"})
            continue
        try:
            _apply_replacement_regions(
                recomposed,
                repair,
                expected_parent_id=str(request.get("parent_region_id") or ""),
            )
        except ValueError as exc:
            workflow_errors.append(
                {"repair_request_id": request_id, "category": "replacement_incomplete", "message": str(exc)}
            )
            continue
        applied_request_ids.add(request_id)

    pending_request_ids = sorted(set(repair_requests).difference(result_by_id))

    gate = run_replacement_integrity_gate(
        recomposed_stage2=recomposed,
        validated_patch=validated_patch,
        resolutions=resolutions,
        workflow_errors=workflow_errors,
        pending_repair_request_ids=pending_request_ids,
    )
    pending_count = len(
        {
            str(item.get("repair_request_id") or "")
            for item in resolutions
            if item.get("coverage_status") == "repair_pending" and item.get("repair_request_id")
        }.union(pending_request_ids)
    )
    if "untrusted_repair_geometry" in gate["failure_categories"] or "repair_failed" in gate["failure_categories"]:
        state = "repair_failed"
    elif pending_count:
        state = "repair_pending"
    elif gate["failure_categories"]:
        state = "needs_human_review" if "needs_human_review" in gate["failure_categories"] else "replacement_incomplete"
    else:
        state = "completed_review_only"
    return {
        "contract_version": WORKFLOW_CONTRACT,
        "workflow_state": state,
        "state_path": [
            "pending",
            "full_review",
            "focused_review",
            "patch_validated",
            *(("repair_pending", "repair_running") if repair_handoff["precise_locator_count"] + repair_handoff["stage1_repartition_count"] else ()),
            *(("recomposing", "replacement_verification") if result_by_id else ()),
            state,
        ],
        "completed": state == "completed_review_only",
        "completed_review_only": state == "completed_review_only",
        "reviewed_stage2": reviewed,
        "recomposed_stage2": recomposed,
        "repair_handoff": repair_handoff,
        "generic_repair_requests": generic_repair_requests,
        "removal_resolutions": resolutions,
        "replacement_integrity_gate": gate,
        "repair_pending_count": pending_count,
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "real_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
    }


def run_replacement_integrity_gate(
    *,
    recomposed_stage2: dict[str, Any],
    validated_patch: dict[str, Any],
    resolutions: list[dict[str, Any]],
    workflow_errors: list[dict[str, str]] | None = None,
    pending_repair_request_ids: list[str] | None = None,
) -> dict[str, Any]:
    errors = workflow_errors or []
    failure_categories = {str(item.get("category") or "") for item in errors if item.get("category")}
    if pending_repair_request_ids:
        failure_categories.add("repair_pending")
    removed_ids = [str(item.get("region_id") or "") for item in validated_patch.get("remove", [])]
    resolved_ids = [str(item.get("removed_region_id") or "") for item in resolutions]
    if len(resolved_ids) != len(set(resolved_ids)) or sorted(removed_ids) != sorted(resolved_ids):
        failure_categories.add("removal_resolution_mismatch")
    item_ids = _numbered_item_ids(recomposed_stage2)
    group_ids = set(_group_records(recomposed_stage2))
    for resolution in resolutions:
        status = str(resolution.get("coverage_status") or "")
        if status == "repair_pending":
            failure_categories.add("repair_pending")
        elif status == "repair_failed" and not failure_categories.intersection(
            {"untrusted_repair_geometry", "replacement_incomplete"}
        ):
            failure_categories.add("repair_failed")
        elif status == "unresolved":
            failure_categories.add("needs_human_review")
        if any(child_id not in item_ids for child_id in resolution.get("preserved_child_ids", [])):
            failure_categories.add("preserved_child_missing")
        if status == "resolved" and resolution.get("repair_request_id"):
            replacements = resolution.get("replacement_region_ids", [])
            if not replacements or any(region_id not in group_ids for region_id in replacements):
                failure_categories.add("replacement_incomplete")
    if validated_patch.get("needs_human_review"):
        failure_categories.add("needs_human_review")
    ordered = sorted(failure_categories, key=_failure_priority)
    return {
        "contract_version": "learning_review_replacement_integrity_gate_v1",
        "passed": not ordered,
        "removed": len(removed_ids),
        "resolved": sum(item.get("coverage_status") == "resolved" for item in resolutions),
        "repair_pending": len(
            {
                str(item.get("repair_request_id") or "")
                for item in resolutions
                if item.get("coverage_status") == "repair_pending" and item.get("repair_request_id")
            }.union(pending_repair_request_ids or [])
        ),
        "needs_human_review": sum(item.get("coverage_status") == "unresolved" for item in resolutions)
        + len(validated_patch.get("needs_human_review", [])),
        "failure_categories": ordered,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _repair_results_by_id(repair_results: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if repair_results is None:
        return {}
    if repair_results.get("contract_version") != "learning_review_repair_results_v1":
        raise ValueError("unsupported repair results contract")
    results = repair_results.get("results")
    if not isinstance(results, list) or any(not isinstance(item, dict) for item in results):
        raise ValueError("repair results must be a list of objects")
    output: dict[str, dict[str, Any]] = {}
    for item in results:
        request_id = str(item.get("repair_request_id") or "")
        if not request_id or request_id in output:
            raise ValueError(f"invalid or duplicate repair_request_id: {request_id}")
        output[request_id] = deepcopy(item)
    return output


def _apply_replacement_regions(
    stage2: dict[str, Any],
    repair: dict[str, Any],
    *,
    expected_parent_id: str,
) -> list[str]:
    replacements = repair.get("replacement_regions")
    if not isinstance(replacements, list) or not replacements:
        raise ValueError("passed repair requires replacement_regions")
    roots = {
        str(root.get("region_id") or ""): root
        for root in stage2.get("regions", [])
        if isinstance(root, dict)
    }
    parent = roots.get(expected_parent_id)
    if parent is None:
        raise ValueError(f"replacement parent is missing: {expected_parent_id}")
    groups = parent.setdefault("subregion_groups", [])
    existing_ids = {str(item.get("group_id") or "") for item in groups if isinstance(item, dict)}
    replacement_ids: list[str] = []
    for replacement in replacements:
        if not isinstance(replacement, dict):
            raise ValueError("replacement region must be an object")
        region_id = str(replacement.get("region_id") or "")
        if not region_id:
            raise ValueError("replacement region_id is required")
        if replacement.get("parent_region_id") != expected_parent_id:
            raise ValueError(f"replacement parent mismatch: {region_id}")
        role = str(replacement.get("role") or "")
        if role not in ALLOWED_REVIEW_ROLES:
            raise ValueError(f"unsupported replacement role: {role}")
        bbox = replacement.get("bbox")
        if not _valid_bbox(bbox):
            raise ValueError(f"replacement bbox is invalid: {region_id}")
        if region_id not in existing_ids:
            replacement_member_ids = {
                str(item_id or "").strip()
                for item_id in replacement.get("member_item_ids", [])
                if str(item_id or "").strip()
            }
            child_group_ids: list[str] = []
            for existing_group in groups:
                if not isinstance(existing_group, dict):
                    continue
                existing_group_id = str(existing_group.get("group_id") or "").strip()
                existing_bbox = existing_group.get("bbox")
                existing_member_ids = {
                    str(item_id or "").strip()
                    for item_id in existing_group.get("member_item_ids", [])
                    if str(item_id or "").strip()
                }
                if (
                    existing_group_id
                    and not str(existing_group.get("parent_group_id") or "").strip()
                    and bool(replacement_member_ids.intersection(existing_member_ids))
                    and (
                        _bbox_contains(bbox, existing_bbox)
                        or (
                            bool(existing_member_ids)
                            and existing_member_ids.issubset(replacement_member_ids)
                            and _bbox_coverage(existing_bbox, bbox) >= 0.8
                        )
                    )
                ):
                    existing_group["parent_group_id"] = region_id
                    child_group_ids.append(existing_group_id)
            replacement_group = {
                "group_id": region_id,
                "role": role,
                "label": str(replacement.get("label") or role),
                "bbox": deepcopy(bbox),
                "member_item_ids": sorted(replacement_member_ids),
                "repair_evidence": {
                    "repair_request_id": repair.get("repair_request_id"),
                    "geometry_source": repair.get("geometry_source"),
                    "display_only": True,
                },
            }
            if child_group_ids:
                replacement_group["child_group_ids"] = sorted(child_group_ids)
            groups.append(replacement_group)
            existing_ids.add(region_id)
        replacement_ids.append(region_id)
    return replacement_ids


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and int(value.get("w") or 0) > 0
        and int(value.get("h") or 0) > 0
    )


def _bbox_contains(parent: Any, child: Any) -> bool:
    if not _valid_bbox(parent) or not _valid_bbox(child):
        return False
    return (
        int(parent.get("x") or 0) <= int(child.get("x") or 0)
        and int(parent.get("y") or 0) <= int(child.get("y") or 0)
        and int(child.get("x") or 0) + int(child["w"])
        <= int(parent.get("x") or 0) + int(parent["w"])
        and int(child.get("y") or 0) + int(child["h"])
        <= int(parent.get("y") or 0) + int(parent["h"])
    )


def _bbox_coverage(subject: Any, covering: Any) -> float:
    if not _valid_bbox(subject) or not _valid_bbox(covering):
        return 0.0
    subject_x1 = int(subject.get("x") or 0)
    subject_y1 = int(subject.get("y") or 0)
    subject_x2 = subject_x1 + int(subject["w"])
    subject_y2 = subject_y1 + int(subject["h"])
    covering_x1 = int(covering.get("x") or 0)
    covering_y1 = int(covering.get("y") or 0)
    covering_x2 = covering_x1 + int(covering["w"])
    covering_y2 = covering_y1 + int(covering["h"])
    intersection = max(0, min(subject_x2, covering_x2) - max(subject_x1, covering_x1)) * max(
        0,
        min(subject_y2, covering_y2) - max(subject_y1, covering_y1),
    )
    return intersection / max(1, int(subject["w"]) * int(subject["h"]))


def _failure_priority(category: str) -> tuple[int, str]:
    order = {
        "untrusted_repair_geometry": 0,
        "repair_failed": 1,
        "repair_pending": 2,
        "needs_human_review": 3,
        "removal_resolution_mismatch": 4,
        "preserved_child_missing": 5,
        "replacement_incomplete": 6,
    }
    return order.get(category, 99), category


def _group_records(stage2: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for root in stage2.get("regions", []):
        if not isinstance(root, dict):
            continue
        parent_id = str(root.get("region_id") or "")
        for group in root.get("subregion_groups", []):
            if not isinstance(group, dict) or not isinstance(group.get("bbox"), dict):
                continue
            group_id = str(group.get("group_id") or "")
            if not group_id:
                continue
            records[group_id] = {
                "parent_region_id": parent_id,
                "bbox": deepcopy(group["bbox"]),
                "member_item_ids": list(group.get("member_item_ids") or group.get("child_item_ids") or []),
            }
    return records


def _numbered_item_ids(stage2: dict[str, Any]) -> set[str]:
    return {
        str(item.get("item_id") or "")
        for root in stage2.get("regions", [])
        if isinstance(root, dict)
        for item in root.get("numbered_items", [])
        if isinstance(item, dict) and item.get("item_id")
    }


def _bbox_overlap_ratio(left: dict[str, Any], right: dict[str, Any]) -> float:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return 0.0
    lx1, ly1, lx2, ly2 = _bbox_edges(left)
    rx1, ry1, rx2, ry2 = _bbox_edges(right)
    intersection = max(0, min(lx2, rx2) - max(lx1, rx1)) * max(0, min(ly2, ry2) - max(ly1, ry1))
    left_area = max(1, (lx2 - lx1) * (ly2 - ly1))
    return intersection / left_area


def _bbox_edges(bbox: dict[str, Any]) -> tuple[int, int, int, int]:
    x = int(bbox.get("x") or 0)
    y = int(bbox.get("y") or 0)
    return x, y, x + max(0, int(bbox.get("w") or 0)), y + max(0, int(bbox.get("h") or 0))
