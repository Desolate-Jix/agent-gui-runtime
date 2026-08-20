from __future__ import annotations

from copy import deepcopy
from typing import Any


_CARD_ROLES = {
    "content_card",
    "job_card",
    "media_card",
    "news_card",
    "recommendation_item",
    "search_result_card",
    "tile_card_parent",
    "video_card",
}

_OPEN_DETAIL_ACTIONS = {
    "open_detail",
    "open_item",
    "open_link",
    "open_result",
}


def build_agent_peer_card_inventory(
    *,
    numbered_regions: list[dict[str, Any]],
    stage2_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把当前截图中的同类卡片证据投影为不含坐标的 Agent 只读清单。"""

    policy = stage2_policy if isinstance(stage2_policy, dict) else {}
    review_policy = policy.get("repeated_peer_layout_review")
    review_policy = review_policy if isinstance(review_policy, dict) else {}
    peer_item_family = str(review_policy.get("peer_item_family") or "").strip()
    if not peer_item_family:
        return _empty_inventory(
            peer_item_family="",
            reason="peer_item_family_not_declared",
        )

    member_lookup = _numbered_item_lookup(numbered_regions)
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    duplicate_candidate_ids: list[str] = []
    for region in numbered_regions:
        if not isinstance(region, dict):
            continue
        for collection_name in ("subregion_groups", "numbered_items"):
            collection = region.get(collection_name)
            if not isinstance(collection, list):
                continue
            for candidate in collection:
                if not isinstance(candidate, dict) or not _is_card_candidate(candidate):
                    continue
                candidate_id = _candidate_id(candidate)
                if candidate_id in seen_ids:
                    if candidate_id not in duplicate_candidate_ids:
                        duplicate_candidate_ids.append(candidate_id)
                    continue
                seen_ids.add(candidate_id)
                items.append(
                    _agent_item(
                        candidate_id,
                        candidate,
                        member_lookup=member_lookup,
                    )
                )

    if not items:
        result = _empty_inventory(
            peer_item_family=peer_item_family,
            reason="no_current_peer_card_evidence",
        )
        result["duplicate_candidate_ids"] = duplicate_candidate_ids
        return result

    readable_item_count = sum(
        item.get("agent_decision_status") == "readable_candidate" for item in items
    )
    return {
        "contract_version": "agent_peer_card_inventory_v1",
        "status": "current_peer_items_projected",
        "reason": "",
        "peer_item_family": peer_item_family,
        "current_visual_evidence_required": True,
        "item_count": len(items),
        "readable_item_count": readable_item_count,
        "review_candidate_count": len(items) - readable_item_count,
        "items": items,
        "duplicate_candidate_ids": duplicate_candidate_ids,
        "interpretation": (
            "current-screen semantic inventory for Agent review; "
            "not executable geometry or action authorization"
        ),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _empty_inventory(*, peer_item_family: str, reason: str) -> dict[str, Any]:
    return {
        "contract_version": "agent_peer_card_inventory_v1",
        "status": "not_covered",
        "reason": reason,
        "peer_item_family": peer_item_family,
        "current_visual_evidence_required": True,
        "item_count": 0,
        "readable_item_count": 0,
        "review_candidate_count": 0,
        "items": [],
        "duplicate_candidate_ids": [],
        "interpretation": (
            "no current-screen peer-card inventory is available; "
            "class prior alone cannot create evidence"
        ),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _is_card_candidate(candidate: dict[str, Any]) -> bool:
    role = str(candidate.get("role") or candidate.get("box_type") or "").casefold()
    return role in _CARD_ROLES


def _candidate_id(candidate: dict[str, Any]) -> str:
    for key in ("item_id", "group_id", "candidate_id", "number"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    identity = (
        str(candidate.get("role") or candidate.get("box_type") or "card"),
        str(candidate.get("label") or candidate.get("text") or ""),
    )
    return "anonymous:" + ":".join(identity)


def _numbered_item_lookup(
    numbered_regions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for region in numbered_regions:
        if not isinstance(region, dict):
            continue
        numbered_items = region.get("numbered_items")
        if not isinstance(numbered_items, list):
            continue
        for item in numbered_items:
            if not isinstance(item, dict):
                continue
            item_id = _candidate_id(item)
            if item_id:
                lookup[item_id] = item
    return lookup


def _agent_item(
    candidate_id: str,
    candidate: dict[str, Any],
    *,
    member_lookup: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    content_summary = _content_summary(candidate, member_lookup=member_lookup)
    semantic_name = content_summary[0] if content_summary else "Unlabelled peer card"
    inferred_neighbor = candidate.get("layout_neighbor_proposal") is True
    candidate_kind = _candidate_kind(candidate, inferred_neighbor=inferred_neighbor)
    explicit_action = _explicit_action(candidate)
    readable = bool(content_summary) and candidate_kind not in {
        "inferred_neighbor",
        "text_only_group",
    }
    return {
        "candidate_id": candidate_id,
        "semantic_name": semantic_name,
        "content_summary": content_summary,
        "source_kind": str(
            candidate.get("source")
            or candidate.get("evidence_source")
            or "current_stage2_candidate"
        ),
        "candidate_kind": candidate_kind,
        "agent_decision_status": (
            "readable_candidate" if readable else "review_only_candidate"
        ),
        "review_status": str(candidate.get("status") or "needs_human_review"),
        "inferred_neighbor": inferred_neighbor,
        "capabilities": {
            "read_current_content": readable,
            "open_detail_candidate": bool(explicit_action and readable),
            "requires_fresh_localization": True,
            "requires_gate": True,
        },
    }


def _candidate_kind(
    candidate: dict[str, Any],
    *,
    inferred_neighbor: bool,
) -> str:
    if inferred_neighbor:
        return "inferred_neighbor"
    source = str(
        candidate.get("source") or candidate.get("evidence_source") or ""
    ).casefold()
    if "text_tile_card_parent" in source:
        return "text_only_group"
    if str(candidate.get("role") or "").casefold() == "tile_card_parent":
        return "visual_card_parent"
    return "atomic_card"


def _content_summary(
    candidate: dict[str, Any],
    *,
    member_lookup: dict[str, dict[str, Any]],
) -> list[str]:
    values: list[str] = []
    _append_content_values(values, candidate)
    member_ids = candidate.get("member_item_ids")
    if isinstance(member_ids, list):
        for member_id in member_ids:
            member = member_lookup.get(str(member_id or "").strip())
            if member is not None:
                _append_content_values(values, member)
    return deepcopy(values[:8])


def _append_content_values(
    values: list[str],
    candidate: dict[str, Any],
) -> None:
    for key in (
        "label",
        "title",
        "text",
        "content",
        "subtitle",
        "source_name",
        "publisher",
        "timestamp_text",
    ):
        value = candidate.get(key)
        if isinstance(value, str):
            normalized = " ".join(value.split())
            if normalized and normalized not in values:
                values.append(normalized)
        elif isinstance(value, list):
            for entry in value:
                normalized = " ".join(str(entry or "").split())
                if normalized and normalized not in values:
                    values.append(normalized)


def _explicit_action(candidate: dict[str, Any]) -> str:
    if candidate.get("interactable") is not True:
        return ""
    actions = [
        candidate.get("action_semantic"),
        candidate.get("semantic_action"),
        candidate.get("action_type"),
        *(candidate.get("allowed_actions") or []),
    ]
    for action in actions:
        normalized = str(action or "").strip().casefold()
        if normalized in _OPEN_DETAIL_ACTIONS:
            return normalized
    return ""
