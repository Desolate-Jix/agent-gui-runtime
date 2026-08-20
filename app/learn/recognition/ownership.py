from __future__ import annotations

from copy import deepcopy
from typing import Any


def resolve_group_ownership(groups: list[dict[str, Any]]) -> dict[str, Any]:
    accepted_groups = [deepcopy(group) for group in groups if isinstance(group, dict)]
    by_id = {
        str(group.get("group_id") or f"group_{index}"): group
        for index, group in enumerate(accepted_groups, start=1)
    }
    parent_by_id = _parent_map(by_id)
    for group_id, parent_group_id in parent_by_id.items():
        if group_id in by_id and parent_group_id in by_id:
            by_id[group_id]["resolved_parent_group_id"] = parent_group_id
    parent_bbox_reconciliations = _reconcile_parent_bounds(by_id, parent_by_id)
    claims_by_item: dict[str, list[str]] = {}
    for group_id, group in by_id.items():
        for item_id in group.get("member_item_ids", []) if isinstance(group.get("member_item_ids"), list) else []:
            item_ref = str(item_id or "").strip()
            if item_ref:
                claims_by_item.setdefault(item_ref, []).append(group_id)

    rejected_claims: list[dict[str, Any]] = []
    source_item_owner_map: dict[str, str] = {}
    ambiguous_tie_count = 0
    for item_id, claims in sorted(claims_by_item.items()):
        leaves = _leaf_claims(sorted(set(claims)), parent_by_id)
        if not leaves:
            continue
        scored = sorted(
            ((_claim_score(by_id[group_id]), group_id) for group_id in leaves),
            key=lambda pair: (-pair[0][0], -pair[0][1], pair[0][2], pair[1]),
        )
        winner_score, winner_id = scored[0]
        source_item_owner_map[item_id] = winner_id
        if len(scored) == 1:
            continue
        top_tied = [pair for pair in scored if pair[0][:2] == winner_score[:2]]
        ambiguous = len(top_tied) > 1
        if ambiguous:
            ambiguous_tie_count += 1
        for loser_score, loser_id in scored[1:]:
            _remove_group_member(by_id[loser_id], item_id)
            rejected_claims.append(
                {
                    "item_id": item_id,
                    "winner_group_id": winner_id,
                    "loser_group_id": loser_id,
                    "winner_role": str(by_id[winner_id].get("role") or ""),
                    "loser_role": str(by_id[loser_id].get("role") or ""),
                    "winner_source": str(by_id[winner_id].get("source") or ""),
                    "loser_source": str(by_id[loser_id].get("source") or ""),
                    "winner_score": list(winner_score),
                    "loser_score": list(loser_score),
                    "reason": (
                        "semantic_evidence_tie_geometric_tiebreak_needs_review"
                        if ambiguous and loser_score[:2] == winner_score[:2]
                        else "stronger_semantic_or_evidence_precedence"
                    ),
                }
            )

    accepted_groups, invalidated_groups = _remove_groups_without_required_members(accepted_groups)
    accepted_group_ids = {
        str(group.get("group_id") or "").strip()
        for group in accepted_groups
        if str(group.get("group_id") or "").strip()
    }
    source_item_owner_map = {
        item_id: owner_id
        for item_id, owner_id in source_item_owner_map.items()
        if owner_id in accepted_group_ids
    }

    return {
        "contract_version": "recognition_group_ownership_resolution_v1",
        "accepted_groups": accepted_groups,
        "audit": {
            "contract_version": "recognition_group_ownership_audit_v1",
            "claim_item_count": len(claims_by_item),
            "accepted_owner_count": len(source_item_owner_map),
            "conflict_count": len(rejected_claims),
            "ambiguous_tie_count": ambiguous_tie_count,
            "needs_human_review": ambiguous_tie_count > 0,
            "source_item_owner_map": source_item_owner_map,
            "rejected_claims": rejected_claims,
            "invalidated_group_count": len(invalidated_groups),
            "invalidated_groups": invalidated_groups,
            "parent_bbox_reconciliation_count": len(parent_bbox_reconciliations),
            "parent_bbox_reconciliations": parent_bbox_reconciliations,
            "precedence_policy": [
                "explicit_visual_component_boundary",
                "repeated_structural_pattern",
                "ocr_row_or_column_relationship",
                "model_semantic_proposal",
                "geometry_only_inference",
            ],
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
            "interpretation": "semantic ownership resolution audit; not model accuracy or Execute authorization",
        },
    }


def _remove_groups_without_required_members(
    groups: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    invalidated: list[dict[str, Any]] = []
    for group in groups:
        role = str(group.get("role") or "").casefold()
        source = str(group.get("source") or "").casefold()
        policy = str(group.get("parent_child_policy") or "").casefold()
        requires_pair = role == "tile_card_parent" and (
            "text_tile_card_parent" in source
            or policy == "paired_title_subtitle_text_tile_without_visible_card_bbox"
        )
        members = [
            str(item_id).strip()
            for item_id in group.get("member_item_ids", [])
            if str(item_id).strip()
        ] if isinstance(group.get("member_item_ids"), list) else []
        unique_members = list(dict.fromkeys(members))
        if not requires_pair or len(unique_members) >= 2:
            accepted.append(group)
            continue
        invalidated.append(
            {
                "group_id": str(group.get("group_id") or ""),
                "role": str(group.get("role") or ""),
                "source": str(group.get("source") or ""),
                "surviving_member_item_ids": unique_members,
                "required_member_count": 2,
                "reason": "required_title_subtitle_pair_not_preserved_after_ownership",
            }
        )
    return accepted, invalidated


def _reconcile_parent_bounds(
    by_id: dict[str, dict[str, Any]],
    parent_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    reconciliations: list[dict[str, Any]] = []
    for _ in range(max(1, len(by_id))):
        changed = False
        for child_id, parent_id in sorted(parent_by_id.items()):
            child_bbox = _bbox(by_id.get(child_id, {}).get("bbox"))
            parent_bbox = _bbox(by_id.get(parent_id, {}).get("bbox"))
            if not child_bbox or not parent_bbox or _contains_ratio(child_bbox, parent_bbox) >= 1.0:
                continue
            expanded = _bbox_union(parent_bbox, child_bbox)
            if expanded == parent_bbox:
                continue
            by_id[parent_id]["bbox"] = expanded
            record = {
                "parent_group_id": parent_id,
                "child_group_id": child_id,
                "previous_parent_bbox": parent_bbox,
                "reconciled_parent_bbox": expanded,
                "reason": "resolved_parent_must_contain_child_group",
            }
            by_id[parent_id].setdefault("bbox_reconciliations", []).append(deepcopy(record))
            reconciliations.append(record)
            changed = True
        if not changed:
            break
    return reconciliations


def _parent_map(by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    parent_by_id: dict[str, str] = {}
    for group_id, group in by_id.items():
        explicit_parent = str(group.get("parent_group_id") or "").strip()
        if explicit_parent in by_id and explicit_parent != group_id:
            parent_by_id[group_id] = explicit_parent
        for child_id in group.get("child_group_ids", []) if isinstance(group.get("child_group_ids"), list) else []:
            child_ref = str(child_id or "").strip()
            if child_ref in by_id and child_ref != group_id:
                parent_by_id.setdefault(child_ref, group_id)
    semantic_topbar_groups = [
        (group_id, group)
        for group_id, group in by_id.items()
        if str(group.get("role") or "").casefold() == "topbar_semantic_group"
    ]
    topbar_strips = [
        (group_id, group)
        for group_id, group in by_id.items()
        if str(group.get("role") or "").casefold() == "topbar_control_strip"
    ]
    for semantic_id, semantic_group in semantic_topbar_groups:
        members = {str(item_id) for item_id in semantic_group.get("member_item_ids", [])}
        matching_strips = [
            strip_id
            for strip_id, strip_group in topbar_strips
            if members.intersection(str(item_id) for item_id in strip_group.get("member_item_ids", []))
        ]
        if matching_strips:
            parent_by_id[semantic_id] = sorted(matching_strips)[0]
    for group_id, group in by_id.items():
        if str(group.get("role") or "").casefold() != "topbar_control_cluster":
            continue
        members = {str(item_id) for item_id in group.get("member_item_ids", [])}
        matching_parents = [
            semantic_id
            for semantic_id, semantic_group in semantic_topbar_groups
            if members.intersection(str(item_id) for item_id in semantic_group.get("member_item_ids", []))
            and _bbox(group.get("bbox"))
            and _bbox(semantic_group.get("bbox"))
            and _contains_ratio(_bbox(group.get("bbox")), _bbox(semantic_group.get("bbox"))) >= 0.985
        ]
        if matching_parents:
            parent_by_id[group_id] = sorted(matching_parents)[0]
    for group_id, group in by_id.items():
        if group_id in parent_by_id:
            continue
        group_bbox = _bbox(group.get("bbox"))
        group_rank = _hierarchy_rank(group)
        if not group_bbox:
            continue
        candidates: list[tuple[int, str]] = []
        for candidate_id, candidate in by_id.items():
            if candidate_id == group_id or _hierarchy_rank(candidate) >= group_rank:
                continue
            candidate_bbox = _bbox(candidate.get("bbox"))
            if candidate_bbox and _contains_ratio(group_bbox, candidate_bbox) >= 0.985:
                candidates.append((_area(candidate_bbox), candidate_id))
        candidates.sort(key=lambda pair: (pair[0], pair[1]))
        if candidates:
            parent_by_id[group_id] = candidates[0][1]
    return parent_by_id


def _leaf_claims(claims: list[str], parent_by_id: dict[str, str]) -> list[str]:
    return [
        claim
        for claim in claims
        if not any(claim != other and _is_ancestor(claim, other, parent_by_id) for other in claims)
    ]


def _is_ancestor(ancestor: str, node: str, parent_by_id: dict[str, str]) -> bool:
    current = node
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        current = parent_by_id.get(current, "")
        if current == ancestor:
            return True
    return False


def _claim_score(group: dict[str, Any]) -> tuple[int, int, int]:
    role = str(group.get("role") or "").casefold()
    source = str(group.get("source") or "").casefold()
    semantic_score = 50
    if role in {"list_row", "table_row"}:
        semantic_score = 100
    elif role == "conversation_row":
        semantic_score = 98
    elif role in {"hero_text_panel", "hero_code_panel", "form_field_group"}:
        semantic_score = 96
    elif role in {"topbar_control_cluster", "media_card", "visual_card"}:
        semantic_score = 94
    elif role == "tile_card_parent" and "primary_tile_card" in source:
        semantic_score = 92
    elif role in {"message_parent", "input_toolbar_region", "notice_parent"}:
        semantic_score = 88
    elif role == "topbar_semantic_group":
        semantic_score = 68
    elif role == "tile_card_parent" and "text_tile" in source:
        semantic_score = 40
    elif role == "ungrouped_review_region":
        semantic_score = 20

    evidence_score = 50
    if any(token in source for token in ("visual", "primary_tile_card", "media_card")):
        evidence_score = 95
    elif any(token in source for token in ("date_title", "repeated", "hero", "direct_bar")):
        evidence_score = 85
    elif "ocr" in source:
        evidence_score = 70
    elif any(token in source for token in ("semantic_model", "model_proposal")):
        evidence_score = 55
    elif any(token in source for token in ("inferred", "text_tile", "orphan")):
        evidence_score = 35
    return semantic_score, evidence_score, _area(_bbox(group.get("bbox")) or {"w": 1, "h": 1})


def _remove_group_member(group: dict[str, Any], item_id: str) -> None:
    members = group.get("member_item_ids") if isinstance(group.get("member_item_ids"), list) else []
    numbers = group.get("member_numbers") if isinstance(group.get("member_numbers"), list) else []
    if len(numbers) == len(members):
        kept_pairs = [(member, number) for member, number in zip(members, numbers) if str(member) != item_id]
        group["member_item_ids"] = [member for member, _number in kept_pairs]
        group["member_numbers"] = [number for _member, number in kept_pairs]
    else:
        group["member_item_ids"] = [member for member in members if str(member) != item_id]


def _hierarchy_rank(group: dict[str, Any]) -> int:
    role = str(group.get("role") or "").casefold()
    if role == "section_parent" or role.endswith("section_parent") or role in {"hero_panel", "topbar_control_strip"}:
        return 1
    if role in {
        "list_group",
        "media_card_group",
        "tile_card_group",
        "partial_visible_card_group",
        "topbar_semantic_group",
    }:
        return 2
    return 3


def _contains_ratio(inner: dict[str, int], outer: dict[str, int]) -> float:
    x1 = max(inner["x"], outer["x"])
    y1 = max(inner["y"], outer["y"])
    x2 = min(inner["x"] + inner["w"], outer["x"] + outer["w"])
    y2 = min(inner["y"] + inner["h"], outer["y"] + outer["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    return intersection / max(1, _area(inner))


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        bbox = {key: int(value.get(key)) for key in ("x", "y", "w", "h")}
    except (TypeError, ValueError):
        return None
    if bbox["w"] <= 0 or bbox["h"] <= 0:
        return None
    return bbox


def _area(bbox: dict[str, int]) -> int:
    return max(1, int(bbox.get("w", 1)) * int(bbox.get("h", 1)))


def _bbox_union(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    x1 = min(left["x"], right["x"])
    y1 = min(left["y"], right["y"])
    x2 = max(left["x"] + left["w"], right["x"] + right["w"])
    y2 = max(left["y"] + left["h"], right["y"] + right["h"])
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
