from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any


FINALIZATION_CONTRACT = "learning_review_final_numbering_v1"


def finalize_reviewed_stage2_for_calibration(
    *,
    source_stage2: dict[str, Any],
    recomposed_stage2: dict[str, Any],
    screenshot_path: str | Path,
    expected_capture_sha256: str,
    workflow_state: str,
    replacement_integrity_gate: dict[str, Any],
    repair_pending_count: int,
) -> dict[str, Any]:
    """把复核完成的 Stage2 固化为只读、版本绑定的校准输入。"""

    screenshot = Path(screenshot_path).resolve()
    actual_capture_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    source_graph_revision = stage2_graph_revision(source_stage2)
    reviewed_graph_revision = stage2_graph_revision(recomposed_stage2)
    final_numbering_revision = hashlib.sha256(
        f"{FINALIZATION_CONTRACT}:{actual_capture_sha256}:{reviewed_graph_revision}".encode("utf-8")
    ).hexdigest()

    finalized = deepcopy(recomposed_stage2)
    failure_categories: set[str] = set()
    expected_checksum = str(expected_capture_sha256 or "").strip().casefold()
    capture_status = "current_capture"
    if not expected_checksum or expected_checksum != actual_capture_sha256:
        capture_status = "stale_capture"
        failure_categories.add("stale_capture")

    replacement_failures = replacement_integrity_gate.get("failure_categories")
    if isinstance(replacement_failures, list):
        failure_categories.update(str(item) for item in replacement_failures if str(item or "").strip())
    if replacement_integrity_gate.get("passed") is not True:
        failure_categories.add("replacement_integrity_gate_failed")
    if int(replacement_integrity_gate.get("needs_human_review") or 0) > 0:
        failure_categories.add("needs_human_review")
    if str(workflow_state or "") != "completed_review_only":
        failure_categories.add("workflow_not_completed")
    if int(repair_pending_count or 0) > 0:
        failure_categories.add("repair_pending")

    source_item_ids = _item_ids(source_stage2)
    final_item_ids = _item_ids(finalized)
    if set(source_item_ids) != set(final_item_ids):
        failure_categories.add("atomic_identity_set_changed")
    duplicate_item_ids = sorted(item_id for item_id, count in Counter(final_item_ids).items() if count > 1)
    if duplicate_item_ids:
        failure_categories.add("duplicate_atomic_identity")
    source_control_parent_ids = _control_parent_ids(source_stage2)
    final_control_parent_ids = _control_parent_ids(finalized)
    if set(source_control_parent_ids) != set(final_control_parent_ids):
        failure_categories.add("control_parent_identity_set_changed")
    duplicate_control_parent_ids = sorted(
        control_id for control_id, count in Counter(final_control_parent_ids).items() if count > 1
    )
    if duplicate_control_parent_ids:
        failure_categories.add("duplicate_control_parent_identity")

    region_map: dict[str, str] = {}
    item_map: dict[str, str] = {}
    group_map: dict[str, str] = {}
    control_parent_map: dict[str, str] = {}
    prefix = final_numbering_revision[:12]
    regions = finalized.get("regions") if isinstance(finalized.get("regions"), list) else []
    final_id_counter = 0
    for region_index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            failure_categories.add("invalid_region_record")
            continue
        region_id = str(region.get("region_id") or "").strip()
        region_bbox = _bbox(region.get("bbox"))
        if not region_id or region_bbox is None:
            failure_categories.add("invalid_region_record")
            continue
        final_region_id = f"final-region:{prefix}:{region_index:04d}"
        region["final_region_id"] = final_region_id
        region["source_region_id"] = region_id
        region_map[region_id] = final_region_id

        items = region.get("numbered_items") if isinstance(region.get("numbered_items"), list) else []
        for item_index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                failure_categories.add("invalid_atomic_record")
                continue
            item_id = str(item.get("item_id") or "").strip()
            item_bbox = _bbox(item.get("bbox"))
            if not item_id or item_bbox is None:
                failure_categories.add("invalid_atomic_record")
                continue
            if not _contains(region_bbox, item_bbox):
                failure_categories.add("child_outside_parent")
            final_id_counter += 1
            final_item_id = f"final-item:{prefix}:{final_id_counter:05d}"
            item["final_item_id"] = final_item_id
            item["source_item_id"] = item_id
            item["final_graph_revision"] = final_numbering_revision
            item_map[item_id] = final_item_id

        groups = region.get("subregion_groups") if isinstance(region.get("subregion_groups"), list) else []
        group_ids = {
            str(group.get("group_id") or "").strip()
            for group in groups
            if isinstance(group, dict) and str(group.get("group_id") or "").strip()
        }
        parent_group_ids = {
            str(group.get("parent_group_id") or group.get("resolved_parent_group_id") or "").strip()
            for group in groups
            if isinstance(group, dict)
            and str(group.get("parent_group_id") or group.get("resolved_parent_group_id") or "").strip()
        }
        leaf_owners: dict[str, list[str]] = defaultdict(list)
        item_ids_in_region = {
            str(item.get("item_id") or "").strip()
            for item in items
            if isinstance(item, dict) and str(item.get("item_id") or "").strip()
        }
        controls = region.get("control_parents") if isinstance(region.get("control_parents"), list) else []
        for control_index, control in enumerate(controls, start=1):
            if not isinstance(control, dict):
                failure_categories.add("invalid_control_parent_record")
                continue
            control_id = str(control.get("object_id") or "").strip()
            control_bbox = _bbox(control.get("bbox"))
            if not control_id or control_bbox is None:
                failure_categories.add("invalid_control_parent_record")
                continue
            if not _contains(region_bbox, control_bbox):
                failure_categories.add("control_parent_outside_region")
            member_ids = [
                str(member_id or "").strip()
                for member_id in control.get("member_object_ids", [])
                if str(member_id or "").strip()
            ] if isinstance(control.get("member_object_ids"), list) else []
            unknown_members = [
                member_id
                for member_id in member_ids
                if not member_id.startswith("raw_visual_candidate_") and member_id not in item_ids_in_region
            ]
            if unknown_members:
                failure_categories.add("unknown_control_parent_member")
            final_control_id = f"final-control:{prefix}:{region_index:04d}:{control_index:04d}"
            control["final_control_parent_id"] = final_control_id
            control["source_control_parent_id"] = control_id
            control["final_graph_revision"] = final_numbering_revision
            control_parent_map[control_id] = final_control_id
        for group_index, group in enumerate(groups, start=1):
            if not isinstance(group, dict):
                failure_categories.add("invalid_group_record")
                continue
            group_id = str(group.get("group_id") or "").strip()
            group_bbox = _bbox(group.get("bbox"))
            if not group_id or group_bbox is None:
                failure_categories.add("invalid_group_record")
                continue
            if not _contains(region_bbox, group_bbox):
                failure_categories.add("child_outside_parent")
            parent_group_id = str(
                group.get("parent_group_id") or group.get("resolved_parent_group_id") or ""
            ).strip()
            if parent_group_id and parent_group_id not in group_ids:
                failure_categories.add("orphan_group_parent")
            member_ids = [
                str(item_id or "").strip()
                for item_id in group.get("member_item_ids", [])
                if str(item_id or "").strip()
            ] if isinstance(group.get("member_item_ids"), list) else []
            if any(item_id not in item_ids_in_region for item_id in member_ids):
                failure_categories.add("unknown_group_member")
            if group_id not in parent_group_ids:
                for item_id in member_ids:
                    leaf_owners[item_id].append(group_id)
            final_group_id = f"final-group:{prefix}:{region_index:04d}:{group_index:04d}"
            group["final_group_id"] = final_group_id
            group["source_group_id"] = group_id
            group["final_graph_revision"] = final_numbering_revision
            group_map[group_id] = final_group_id
        if any(len(owner_ids) > 1 for owner_ids in leaf_owners.values()):
            failure_categories.add("multiple_leaf_ownership")

    if _safety_fingerprint(source_stage2) != _safety_fingerprint(recomposed_stage2):
        failure_categories.add("action_safety_semantics_changed")
    if _unsafe_authorization_flag_paths(recomposed_stage2):
        failure_categories.add("unsafe_authorization_flag")

    ordered_failures = sorted(failure_categories)
    finalized["contract_version"] = FINALIZATION_CONTRACT
    finalized["graph_revision"] = final_numbering_revision
    finalized["source_graph_revision"] = source_graph_revision
    finalized["reviewed_graph_revision"] = reviewed_graph_revision
    finalized["display_only"] = True
    finalized["execute_binding_enabled"] = False
    finalized["artifact_is_authorization"] = False
    finalized["final_numbering"] = {
        "contract_version": FINALIZATION_CONTRACT,
        "revision": final_numbering_revision,
        "source_graph_revision": source_graph_revision,
        "reviewed_graph_revision": reviewed_graph_revision,
        "capture_sha256": actual_capture_sha256,
        "source_ids_are_calibration_ids": False,
        "region_count": len(region_map),
        "item_count": len(item_map),
        "group_count": len(group_map),
        "control_parent_count": len(control_parent_map),
        "provisional_to_final_id_map": {
            "regions": region_map,
            "items": item_map,
            "groups": group_map,
            "control_parents": control_parent_map,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    integrity_gate = {
        "contract_version": "learning_review_final_integrity_gate_v1",
        "passed": not ordered_failures,
        "failure_categories": ordered_failures,
        "capture_status": capture_status,
        "expected_capture_sha256": expected_checksum,
        "actual_capture_sha256": actual_capture_sha256,
        "source_atomic_count": len(source_item_ids),
        "final_atomic_count": len(final_item_ids),
        "duplicate_atomic_ids": duplicate_item_ids,
        "source_control_parent_count": len(source_control_parent_ids),
        "final_control_parent_count": len(final_control_parent_ids),
        "duplicate_control_parent_ids": duplicate_control_parent_ids,
        "workflow_state": str(workflow_state or ""),
        "repair_pending_count": int(repair_pending_count or 0),
        "replacement_integrity_gate_passed": replacement_integrity_gate.get("passed") is True,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    finalized["final_numbering"]["integrity_gate"] = deepcopy(integrity_gate)
    return {
        "contract_version": FINALIZATION_CONTRACT,
        "source_graph_revision": source_graph_revision,
        "reviewed_graph_revision": reviewed_graph_revision,
        "final_numbering_revision": final_numbering_revision,
        "finalized_stage2": finalized,
        "integrity_gate": integrity_gate,
        "calibration_permission": integrity_gate["passed"],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "real_clicks": 0,
    }


def _item_ids(stage2: dict[str, Any]) -> list[str]:
    return [
        str(item.get("item_id") or "").strip()
        for region in stage2.get("regions", [])
        if isinstance(region, dict)
        for item in region.get("numbered_items", [])
        if isinstance(item, dict) and str(item.get("item_id") or "").strip()
    ]


def _control_parent_ids(stage2: dict[str, Any]) -> list[str]:
    return [
        str(parent.get("object_id") or "").strip()
        for region in stage2.get("regions", [])
        if isinstance(region, dict)
        for parent in region.get("control_parents", [])
        if isinstance(parent, dict) and str(parent.get("object_id") or "").strip()
    ]


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        bbox = {key: int(round(float(value.get(key)))) for key in ("x", "y", "w", "h")}
    except (TypeError, ValueError):
        return None
    return bbox if bbox["w"] > 0 and bbox["h"] > 0 else None


def _contains(parent: dict[str, int], child: dict[str, int]) -> bool:
    return (
        parent["x"] <= child["x"]
        and parent["y"] <= child["y"]
        and child["x"] + child["w"] <= parent["x"] + parent["w"]
        and child["y"] + child["h"] <= parent["y"] + parent["h"]
    )


def stage2_graph_revision(stage2: dict[str, Any]) -> str:
    canonical = json.dumps(stage2, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safety_fingerprint(value: Any) -> list[tuple[str, str]]:
    tracked_keys = {
        "action",
        "action_type",
        "semantic_action",
        "danger",
        "danger_level",
        "final_submit",
        "final_submit_forbidden",
    }
    records: list[tuple[str, str]] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            identity = next(
                (
                    f"{key}:{str(node.get(key) or '').strip()}"
                    for key in ("item_id", "group_id", "region_id")
                    if str(node.get(key) or "").strip()
                ),
                "",
            )
            owner_path = f"{path}/{identity}" if identity else path
            for key in sorted(node):
                if key == "model_review_decision":
                    continue
                child_path = f"{owner_path}.{key}" if owner_path else str(key)
                if key in tracked_keys:
                    records.append((child_path, json.dumps(node[key], ensure_ascii=False, sort_keys=True)))
                visit(node[key], owner_path)
        elif isinstance(node, list):
            for item in node:
                visit(item, path)

    visit(value, "")
    return sorted(records)


def _unsafe_authorization_flag_paths(value: Any) -> list[str]:
    unsafe_paths: list[str] = []

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                child_path = f"{path}.{key}" if path else str(key)
                if key in {"execute_binding_enabled", "artifact_is_authorization"} and child is True:
                    unsafe_paths.append(child_path)
                visit(child, child_path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{path}[{index}]")

    visit(value, "")
    return unsafe_paths
