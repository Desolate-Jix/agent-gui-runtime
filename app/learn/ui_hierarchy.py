from __future__ import annotations

import re
from collections import Counter
from copy import deepcopy
from typing import Any


_LEVEL_RANK = {
    "screen": 0,
    "structure_region": 1,
    "section": 2,
    "component_group": 3,
    "component": 4,
    "content": 5,
}

_SECTION_ROLES = {
    "section_parent",
    "hero_panel",
    "page_section",
    "form_section",
}

_COMPONENT_GROUP_ROLES = {
    "list_group",
    "media_card_group",
    "tile_card_group",
    "partial_visible_card_group",
    "topbar_control_strip",
    "member_list_group",
    "conversation_group",
}

_CONTENT_ROLES = {
    "text",
    "readable",
    "label",
    "heading",
    "section_title",
    "icon",
    "image_label",
    "metadata",
}


def build_ui_hierarchy_graph(
    *,
    structure_regions: list[dict[str, Any]],
    numbered_regions: list[dict[str, Any]],
    screen_size: dict[str, int],
) -> dict[str, Any]:
    screen_bbox = {
        "x": 0,
        "y": 0,
        "w": max(1, _int(screen_size.get("width"))),
        "h": max(1, _int(screen_size.get("height"))),
    }
    root = _node(
        node_id="uih:screen",
        level="screen",
        component_type="screen",
        bbox=screen_bbox,
        parent_id="",
        source_ref="screen",
        label="Screen",
        evidence=["screenshot_coordinate_space"],
        confidence=1.0,
        review_status="review_only",
    )
    nodes: list[dict[str, Any]] = [root]
    clipped_node_ids: list[str] = []
    structure_by_source: dict[str, dict[str, Any]] = {}
    numbered_by_region = {
        str(region.get("region_id") or ""): region
        for region in numbered_regions
        if str(region.get("region_id") or "").strip()
    }

    ordered_structures = sorted(
        [region for region in structure_regions if _bbox(region.get("bbox")) or _bbox(region.get("precise_bbox"))],
        key=lambda region: (*_bbox_sort_key(_bbox(region.get("bbox")) or _bbox(region.get("precise_bbox")) or {}), str(region.get("region_id") or "")),
    )
    for index, region in enumerate(ordered_structures, start=1):
        source_ref = str(region.get("region_id") or region.get("zone_id") or f"structure_{index}")
        raw_bbox = _bbox(region.get("bbox")) or _bbox(region.get("precise_bbox")) or screen_bbox
        bbox, clipped = _clip_with_flag(raw_bbox, screen_bbox)
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        node = _node(
            node_id=f"uih:structure:{_slug(source_ref)}",
            level="structure_region",
            component_type=_structure_type(region),
            bbox=bbox,
            parent_id=root["node_id"],
            source_ref=source_ref,
            label=str(region.get("label") or source_ref),
            evidence=_evidence(region, extra=[str(validation.get("evidence") or "")]),
            confidence=_confidence(region, validation),
            review_status="needs_review" if clipped else "review_only",
        )
        if clipped:
            clipped_node_ids.append(node["node_id"])
        nodes.append(node)
        structure_by_source[source_ref] = node

    group_nodes_by_region: dict[str, dict[str, dict[str, Any]]] = {}
    group_payloads_by_region: dict[str, dict[str, dict[str, Any]]] = {}
    for structure_ref, structure_node in structure_by_source.items():
        numbered_region = numbered_by_region.get(structure_ref, {})
        groups = numbered_region.get("subregion_groups") if isinstance(numbered_region.get("subregion_groups"), list) else []
        payload_by_id = {
            str(group.get("group_id") or f"group_{index}"): group
            for index, group in enumerate(groups, start=1)
            if isinstance(group, dict)
        }
        parent_refs = _group_parent_refs(payload_by_id)
        node_by_id: dict[str, dict[str, Any]] = {}
        for group_id, group in sorted(payload_by_id.items(), key=lambda pair: (*_bbox_sort_key(_bbox(pair[1].get("bbox")) or {}), pair[0])):
            level = _group_level(group)
            node_by_id[group_id] = _node(
                node_id=f"uih:group:{_slug(structure_ref)}:{_slug(group_id)}",
                level=level,
                component_type=str(group.get("role") or "component_group"),
                bbox=_bbox(group.get("bbox")) or structure_node["bbox"],
                parent_id="",
                source_ref=group_id,
                label=str(group.get("label") or group_id),
                member_item_ids=[str(item_id) for item_id in group.get("member_item_ids", []) if str(item_id or "").strip()],
                evidence=_evidence(group),
                confidence=_confidence(group),
                review_status="review_only",
            )
        for group_id, node in node_by_id.items():
            parent_group_id = parent_refs.get(group_id) or _smallest_containing_group_id(
                group_id,
                payload_by_id=payload_by_id,
                node_by_id=node_by_id,
            )
            parent = node_by_id.get(parent_group_id) if parent_group_id else structure_node
            if parent is None or parent["node_id"] == node["node_id"]:
                parent = structure_node
            clipped_bbox, clipped = _clip_with_flag(node["bbox"], parent["bbox"])
            node["bbox"] = clipped_bbox
            node["parent_id"] = parent["node_id"]
            if clipped:
                node["review_status"] = "needs_review"
                clipped_node_ids.append(node["node_id"])
            nodes.append(node)
        group_nodes_by_region[structure_ref] = node_by_id
        group_payloads_by_region[structure_ref] = payload_by_id

    duplicate_owner_item_ids: list[str] = []
    for structure_ref, structure_node in structure_by_source.items():
        numbered_region = numbered_by_region.get(structure_ref, {})
        items = numbered_region.get("numbered_items") if isinstance(numbered_region.get("numbered_items"), list) else []
        node_by_group = group_nodes_by_region.get(structure_ref, {})
        payload_by_group = group_payloads_by_region.get(structure_ref, {})
        for index, item in enumerate(sorted(items, key=lambda entry: (*_bbox_sort_key(_bbox(entry.get("bbox")) or {}), str(entry.get("item_id") or ""))), start=1):
            item_id = str(item.get("item_id") or item.get("number") or f"item_{index}")
            level = _item_level(item)
            claims = [
                group_id
                for group_id, group in payload_by_group.items()
                if item_id in {str(member) for member in group.get("member_item_ids", [])}
                and _LEVEL_RANK.get(node_by_group[group_id]["level"], 0) < _LEVEL_RANK[level]
            ]
            if not claims:
                claims.extend(
                    group_id
                    for group_id, group_node in node_by_group.items()
                    if _LEVEL_RANK.get(group_node["level"], 0) < _LEVEL_RANK[level]
                    and _contains_ratio(_bbox(item.get("bbox")) or {}, group_node["bbox"]) >= 0.999
                )
            owner_group_id, competing_claims = _select_item_owner(claims, node_by_group)
            parent = node_by_group.get(owner_group_id) if owner_group_id else structure_node
            raw_bbox = _bbox(item.get("bbox")) or parent["bbox"]
            bbox, clipped = _clip_with_flag(raw_bbox, parent["bbox"])
            review_status = "needs_review" if clipped or competing_claims else "review_only"
            node = _node(
                node_id=f"uih:item:{_slug(structure_ref)}:{_slug(item_id)}",
                level=level,
                component_type=str(item.get("role") or item.get("item_type") or "review_item"),
                bbox=bbox,
                parent_id=parent["node_id"],
                source_ref=item_id,
                label=str(item.get("label") or item.get("text") or item_id),
                member_item_ids=[item_id],
                evidence=_evidence(item),
                confidence=_confidence(item),
                review_status=review_status,
                ownership_claims=[node_by_group[claim]["node_id"] for claim in claims if claim in node_by_group],
                competing_owner_ids=[node_by_group[claim]["node_id"] for claim in competing_claims if claim in node_by_group],
            )
            if clipped:
                clipped_node_ids.append(node["node_id"])
            if competing_claims:
                duplicate_owner_item_ids.append(item_id)
            nodes.append(node)

    node_by_id = {node["node_id"]: node for node in nodes}
    for node in nodes:
        node["children"] = []
    for node in nodes:
        parent_id = str(node.get("parent_id") or "")
        if parent_id and parent_id in node_by_id:
            node_by_id[parent_id]["children"].append(node["node_id"])
    for node in nodes:
        node["children"].sort()

    orphan_nodes = [node["node_id"] for node in nodes if node["level"] != "screen" and node["parent_id"] not in node_by_id]
    reachable_node_ids: set[str] = set()
    pending_node_ids = [root["node_id"]]
    while pending_node_ids:
        node_id = pending_node_ids.pop()
        if node_id in reachable_node_ids or node_id not in node_by_id:
            continue
        reachable_node_ids.add(node_id)
        pending_node_ids.extend(str(child_id) for child_id in node_by_id[node_id].get("children", []))
    unreachable_node_ids = [
        node["node_id"]
        for node in nodes
        if node["level"] != "screen" and node["node_id"] not in reachable_node_ids
    ]
    cycle_node_ids: set[str] = set()
    for node in nodes:
        path: list[str] = []
        index_by_id: dict[str, int] = {}
        current_id = node["node_id"]
        while current_id and current_id in node_by_id:
            if current_id in index_by_id:
                cycle_node_ids.update(path[index_by_id[current_id] :])
                break
            index_by_id[current_id] = len(path)
            path.append(current_id)
            current_id = str(node_by_id[current_id].get("parent_id") or "")
    outside_nodes = [
        node["node_id"]
        for node in nodes
        if node["level"] != "screen"
        and node["parent_id"] in node_by_id
        and _contains_ratio(node["bbox"], node_by_id[node["parent_id"]]["bbox"]) < 0.999
    ]
    levels = Counter(node["level"] for node in nodes)
    ownership_audits = [
        region.get("ownership_resolution")
        for region in numbered_regions
        if isinstance(region, dict) and isinstance(region.get("ownership_resolution"), dict)
    ]
    resolved_ownership_conflict_count = sum(int(audit.get("conflict_count") or 0) for audit in ownership_audits)
    ambiguous_ownership_tie_count = sum(int(audit.get("ambiguous_tie_count") or 0) for audit in ownership_audits)
    edges = [
        {"edge_type": "contains", "parent_id": node["parent_id"], "child_id": node["node_id"]}
        for node in nodes
        if node["level"] != "screen" and node["parent_id"]
    ]
    validation_passed = not (
        orphan_nodes
        or outside_nodes
        or clipped_node_ids
        or duplicate_owner_item_ids
        or cycle_node_ids
        or unreachable_node_ids
    )
    return {
        "contract_version": "ui_hierarchy_graph_v1",
        "root_node_id": root["node_id"],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "runtime_pathgraph_promotion": False,
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "level_counts": dict(sorted(levels.items())),
            "structure_region_count": levels.get("structure_region", 0),
            "component_count": levels.get("component", 0),
            "content_count": levels.get("content", 0),
            "resolved_ownership_conflict_count": resolved_ownership_conflict_count,
            "ambiguous_ownership_tie_count": ambiguous_ownership_tie_count,
            "ownership_review_required": any(bool(audit.get("needs_human_review")) for audit in ownership_audits),
        },
        "validation": {
            "passed": validation_passed,
            "status": "passed" if validation_passed else "needs_review",
            "orphan_node_count": len(orphan_nodes),
            "orphan_node_ids": orphan_nodes,
            "child_outside_parent_count": len(outside_nodes),
            "child_outside_parent_ids": outside_nodes,
            "clipped_node_count": len(clipped_node_ids),
            "clipped_node_ids": clipped_node_ids,
            "cycle_node_count": len(cycle_node_ids),
            "cycle_node_ids": sorted(cycle_node_ids),
            "unreachable_from_root_count": len(unreachable_node_ids),
            "unreachable_from_root_ids": unreachable_node_ids,
            "duplicate_primary_owner_count": len(duplicate_owner_item_ids),
            "duplicate_primary_owner_item_ids": duplicate_owner_item_ids,
            "interpretation": "hierarchy contract validation; not model accuracy or Execute authorization",
        },
    }


def _node(
    *,
    node_id: str,
    level: str,
    component_type: str,
    bbox: dict[str, int],
    parent_id: str,
    source_ref: str,
    label: str,
    evidence: list[str],
    confidence: float,
    review_status: str,
    member_item_ids: list[str] | None = None,
    ownership_claims: list[str] | None = None,
    competing_owner_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": "ui_hierarchy_node_v1",
        "node_id": node_id,
        "level": level,
        "component_type": component_type,
        "label": label,
        "bbox": deepcopy(bbox),
        "parent_id": parent_id,
        "children": [],
        "source_ref": source_ref,
        "member_item_ids": list(member_item_ids or []),
        "evidence": evidence,
        "confidence": confidence,
        "review_status": review_status,
        "ownership_claims": list(ownership_claims or []),
        "competing_owner_ids": list(competing_owner_ids or []),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _group_parent_refs(payload_by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    parents: dict[str, str] = {}
    for group_id, group in payload_by_id.items():
        explicit = str(group.get("resolved_parent_group_id") or group.get("parent_group_id") or "").strip()
        if explicit and explicit in payload_by_id:
            parents[group_id] = explicit
        for child_id in group.get("child_group_ids", []) if isinstance(group.get("child_group_ids"), list) else []:
            child_ref = str(child_id or "").strip()
            if child_ref and child_ref in payload_by_id:
                parents.setdefault(child_ref, group_id)
    return parents


def _smallest_containing_group_id(
    group_id: str,
    *,
    payload_by_id: dict[str, dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
) -> str:
    node = node_by_id[group_id]
    rank = _LEVEL_RANK[node["level"]]
    candidates: list[tuple[int, str]] = []
    for candidate_id, candidate in node_by_id.items():
        if candidate_id == group_id or _LEVEL_RANK[candidate["level"]] >= rank:
            continue
        if _contains_ratio(node["bbox"], candidate["bbox"]) >= 0.985:
            candidates.append((_area(candidate["bbox"]), candidate_id))
    candidates.sort(key=lambda pair: (pair[0], pair[1]))
    return candidates[0][1] if candidates else ""


def _select_item_owner(claims: list[str], node_by_group: dict[str, dict[str, Any]]) -> tuple[str, list[str]]:
    unique_claims = sorted(set(claim for claim in claims if claim in node_by_group))
    if not unique_claims:
        return "", []
    ordered = sorted(
        unique_claims,
        key=lambda claim: (-_LEVEL_RANK[node_by_group[claim]["level"]], _area(node_by_group[claim]["bbox"]), claim),
    )
    winner = ordered[0]
    winner_node_id = node_by_group[winner]["node_id"]
    competing = [
        claim
        for claim in ordered[1:]
        if not _node_is_ancestor(node_by_group[claim]["node_id"], winner_node_id, node_by_group)
    ]
    return winner, competing


def _node_is_ancestor(ancestor_node_id: str, node_id: str, node_by_group: dict[str, dict[str, Any]]) -> bool:
    by_node_id = {node["node_id"]: node for node in node_by_group.values()}
    current = by_node_id.get(node_id)
    seen: set[str] = set()
    while current and current["node_id"] not in seen:
        seen.add(current["node_id"])
        parent_id = str(current.get("parent_id") or "")
        if parent_id == ancestor_node_id:
            return True
        current = by_node_id.get(parent_id)
    return False


def _group_level(group: dict[str, Any]) -> str:
    role = str(group.get("role") or "").casefold()
    if role in _SECTION_ROLES or role.endswith("section_parent"):
        return "section"
    if role in _COMPONENT_GROUP_ROLES or role.endswith("_group") or role.endswith("_strip"):
        return "component_group"
    return "component"


def _item_level(item: dict[str, Any]) -> str:
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if role in _CONTENT_ROLES or "text" in role or role.endswith("_label"):
        return "content"
    return "component"


def _structure_type(region: dict[str, Any]) -> str:
    text = " ".join(str(region.get(key) or "") for key in ("region_id", "zone_id", "label", "role")).casefold()
    for token, result in (
        ("modal", "modal"),
        ("overlay", "overlay"),
        ("top", "top_bar"),
        ("header", "top_bar"),
        ("left", "left_sidebar"),
        ("right", "right_sidebar"),
        ("bottom", "bottom_bar"),
        ("main", "main_content"),
        ("primary", "main_content"),
    ):
        if token in text:
            return result
    return "structure_region"


def _evidence(payload: dict[str, Any], *, extra: list[str] | None = None) -> list[str]:
    values: list[str] = []
    for key in ("source", "bbox_policy", "parent_child_policy"):
        value = str(payload.get(key) or "").strip()
        if value:
            values.append(value)
    for value in payload.get("source_evidence", []) if isinstance(payload.get("source_evidence"), list) else []:
        text = str(value or "").strip()
        if text:
            values.append(text)
    for value in extra or []:
        text = str(value or "").strip()
        if text:
            values.append(text)
    return sorted(set(values))


def _confidence(payload: dict[str, Any], nested: dict[str, Any] | None = None) -> float:
    candidates = [payload.get("confidence"), payload.get("score")]
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    candidates.append(metadata.get("confidence"))
    if nested:
        candidates.extend([nested.get("confidence"), nested.get("score")])
    for candidate in candidates:
        try:
            value = float(candidate)
        except (TypeError, ValueError):
            continue
        return round(max(0.0, min(1.0, value)), 4)
    return 0.5


def _clip_with_flag(inner: dict[str, int], outer: dict[str, int]) -> tuple[dict[str, int], bool]:
    x1 = max(outer["x"], inner["x"])
    y1 = max(outer["y"], inner["y"])
    x2 = min(outer["x"] + outer["w"], inner["x"] + inner["w"])
    y2 = min(outer["y"] + outer["h"], inner["y"] + inner["h"])
    clipped = {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}
    return clipped, clipped != inner


def _contains_ratio(inner: dict[str, int], outer: dict[str, int]) -> float:
    if not inner or not outer:
        return 0.0
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
        x = int(value.get("x"))
        y = int(value.get("y"))
        w = int(value.get("w"))
        h = int(value.get("h"))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _bbox_sort_key(bbox: dict[str, int]) -> tuple[int, int, int, int]:
    return (bbox.get("y", 0), bbox.get("x", 0), bbox.get("h", 0), bbox.get("w", 0))


def _area(bbox: dict[str, int]) -> int:
    return max(1, int(bbox.get("w", 1)) * int(bbox.get("h", 1)))


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", str(value or "").strip()).strip("-")
    return cleaned or "unknown"


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
