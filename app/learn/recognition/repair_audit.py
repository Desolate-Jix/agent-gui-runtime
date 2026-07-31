from __future__ import annotations

from typing import Any


GENERAL_REPAIR_RULES = [
    "preserve_atomic_children_before_parent_removal",
    "same_parent_and_overlap_required_for_aggregation",
    "rough_roi_is_search_scope_only",
    "final_bbox_from_atomic_union_and_parent_clip",
    "missing_atomic_evidence_blocks_auto_repair",
    "model_review_required_to_classify_false_card",
]


def audit_stage2_repair_readiness(stage2: dict[str, Any]) -> dict[str, Any]:
    group_count = 0
    eligible_ids: list[str] = []
    missing_ids: list[str] = []
    outside_parent_ids: list[str] = []
    card_like_ids: list[str] = []
    atomic_item_count = 0

    for parent in stage2.get("regions", []):
        if not isinstance(parent, dict):
            continue
        parent_bbox = parent.get("bbox")
        items = {
            str(item.get("item_id") or ""): item
            for item in parent.get("numbered_items", [])
            if isinstance(item, dict) and item.get("item_id")
        }
        atomic_item_count += len(items)
        for group in parent.get("subregion_groups", []):
            if not isinstance(group, dict):
                continue
            group_count += 1
            group_id = str(group.get("group_id") or f"unnamed_group_{group_count}")
            role = str(group.get("role") or "").casefold()
            if "card" in role or "tile" in role:
                card_like_ids.append(group_id)
            member_ids = sorted(
                {
                    str(item_id)
                    for item_id in (group.get("member_item_ids") or group.get("child_item_ids") or [])
                    if item_id
                }
            )
            has_complete_evidence = bool(member_ids) and all(
                item_id in items and _valid_bbox(items[item_id].get("bbox")) for item_id in member_ids
            )
            inside_parent = _contains(parent_bbox, group.get("bbox"))
            if not inside_parent:
                outside_parent_ids.append(group_id)
            if has_complete_evidence and inside_parent:
                eligible_ids.append(group_id)
            else:
                missing_ids.append(group_id)

    return {
        "contract_version": "learning_repair_readiness_audit_v1",
        "root_region_count": sum(isinstance(item, dict) for item in stage2.get("regions", [])),
        "atomic_item_count": atomic_item_count,
        "group_count": group_count,
        "deterministic_repair_eligible": len(eligible_ids),
        "requires_model_or_human_review": len(missing_ids),
        "eligible_group_ids": sorted(eligible_ids),
        "missing_atomic_evidence_group_ids": sorted(missing_ids),
        "outside_parent_group_ids": sorted(outside_parent_ids),
        "card_like_group_ids": sorted(card_like_ids),
        "false_card_classification": "not_evaluated_without_model_review",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "real_clicks": 0,
    }


def summarize_nine_interface_repair_audits(cases: list[dict[str, Any]]) -> dict[str, Any]:
    signatures = {
        str(case.get("structure_signature") or "unknown")
        for case in cases
        if isinstance(case, dict)
    }
    return {
        "attempted": len(cases),
        "structure_family_count": len(signatures),
        "deterministic_repair_eligible": sum(
            int(case.get("deterministic_repair_eligible") or 0) for case in cases
        ),
        "requires_model_or_human_review": sum(
            int(case.get("requires_model_or_human_review") or 0) for case in cases
        ),
        "outside_parent_group_count": sum(
            len(case.get("outside_parent_group_ids") or []) for case in cases
        ),
        "model_review_coverage": {"attempted": 0, "rate": "not_covered"},
        "general_rules": list(GENERAL_REPAIR_RULES),
        "interpretation": (
            "Cross-interface repair-readiness audit over fixed Stage2 assets; "
            "not model-review quality, recognition accuracy, or runtime authorization."
        ),
    }


def _contains(parent_value: Any, child_value: Any) -> bool:
    if not _valid_bbox(parent_value) or not _valid_bbox(child_value):
        return False
    px1, py1, px2, py2 = _edges(parent_value)
    cx1, cy1, cx2, cy2 = _edges(child_value)
    return px1 <= cx1 and py1 <= cy1 and cx2 <= px2 and cy2 <= py2


def _valid_bbox(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and int(value.get("w") or 0) > 0
        and int(value.get("h") or 0) > 0
    )


def _edges(value: dict[str, Any]) -> tuple[int, int, int, int]:
    x = int(value.get("x") or 0)
    y = int(value.get("y") or 0)
    return x, y, x + int(value.get("w") or 0), y + int(value.get("h") or 0)
