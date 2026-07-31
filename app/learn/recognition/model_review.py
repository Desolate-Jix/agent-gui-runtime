from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


REVIEW_PATCH_CONTRACT = "learning_overlay_model_review_patch_v1"
ALLOWED_REVIEW_ROLES = {
    "card",
    "content_region",
    "input_region",
    "list_container",
    "list_item",
    "member_list",
    "message_item",
    "navigation",
    "review_only",
    "tab",
    "toolbar",
}
MISSING_CANDIDATE_PROVISIONAL_ROLES = ALLOWED_REVIEW_ROLES | {
    "bottom_bar",
    "conversation_row",
    "status_bar",
}
ALLOWED_REPAIR_ROUTES = {"precise_locator", "stage1_repartition"}
FOCUSED_CARD_REVIEW_ROLES = {
    "card",
    "message_item",
    "recommendation_item",
    "section_parent",
    "tile_card_group",
    "tile_card_parent",
}
FOCUSED_SAFE_CONTAINER_ROLES = {"list_container", "member_list"}
FOCUSED_GEOMETRY_QUALITIES = {"exact_semantic_unit", "overmerged", "fragment", "uncertain"}
FOCUSED_PARENT_RELATIONS = {"valid_child", "distinct_pane", "uncertain"}
FOCUSED_OBSERVED_ROLE_ALIASES = {
    "message_bubble": "message_item",
}
REVIEW_ROLE_ALIASES = {
    "news_card": "card",
}
# 几何重复足以证明表格行结构，但不能证明普通行属于聊天或列表语义。
DETERMINISTIC_LEAF_REVIEW_ROLES = {"table_row"}
DETERMINISTIC_BAR_REVIEW_ROLES = {"topbar_control_cluster", "topbar_control_strip"}
FORBIDDEN_MODEL_GEOMETRY_KEYS = {"bbox", "final_bbox", "click_point", "candidate_point"}
REVIEW_PATCH_FIELDS = {
    "contract_version",
    "group_reviews",
    "keep",
    "remove",
    "relabel",
    "missing",
    "needs_human_review",
    "protocol_adjustments",
}


def build_model_review_prompt(stage2: dict[str, Any]) -> str:
    evidence = _compact_review_evidence(stage2)
    required_review_ids = sorted(record["review_id"] for record in _group_review_records(stage2))
    return (
        "Review the composite GUI overlay against the supplied Stage2 region JSON. "
        "The image contains the current boxes and IDs. Detect obvious semantic grouping errors and missing content.\n\n"
        "Review IDs are opaque and carry no semantics. Source roles and labels are hypotheses under review, not ground truth. "
        "Use screenshot pixels and member_evidence "
        "to verify semantics. When a source label conflicts with visible content, relabel or remove it instead of preserving "
        "the label. After proposed removals, check whether a coherent visible pane would be left without a semantic region; "
        "report that pane in missing.\n\n"
        "A card must be one coherent visual/content unit. A long list container, member column, conversation list, "
        "toolbar, or unrelated repeated rows must not be promoted to card/tile_card_parent/recommendation_item. "
        "Use content_region for a coherent code, document, or detail pane; filenames and source code are not message evidence. "
        "Overlapping or nested boxes are allowed only when the child is genuinely contained by the parent.\n\n"
        'Return exactly one JSON object with arrays "group_reviews" and "missing". '
        'Each group_reviews entry is {"region_id":"...","decision":"keep|remove|relabel|needs_human_review",'
        '"new_role":null,"reason":"..."}. '
        'decision must be one of ["keep","remove","relabel","needs_human_review"]. '
        "Every opaque review ID must appear exactly once in group_reviews. "
        "Keep each reason under 16 words so every required review fits in the response. "
        "Do not return an empty audit when subregion_groups are present. "
        "This phase reviews existing groups only, so missing must be an empty array. Missing-region detection runs in a separate "
        "candidate audit and must not be guessed here. Do not request stage1_repartition in this phase.\n\n"
        "Do not invent a final bbox, click point, action, new region ID, or new parent ID. rough_roi is only a coarse search area. "
        "Do not remove a box merely because it is large. Do not change Stage1 roots. When uncertain, use needs_human_review.\n\n"
        "Allowed new_role values: "
        + ", ".join(sorted(ALLOWED_REVIEW_ROLES))
        + ".\nRequired opaque review IDs: "
        + json.dumps(required_review_ids, ensure_ascii=False, separators=(",", ":"))
        + ".\n\nStage2 evidence:\n"
        + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    )


def build_missing_region_audit_prompt(
    stage2: dict[str, Any],
    candidates: dict[str, Any],
) -> str:
    evidence = _compact_review_evidence(stage2)
    return (
        "Audit uncovered visible GUI regions only. The image shows the current reviewed semantic boxes over the original "
        "screenshot. Find coherent visible panes or local objects that have no semantic box at all. Do not review, remove, "
        "or relabel existing boxes. Empty background, spacing, separators, clipped fragments, and decorative chrome are not "
        "missing regions. A missing region must be visibly coherent, useful for describing the interface, and substantially "
        "uncovered by every existing semantic box.\n\n"
        'Magenta M-prefixed boxes are program-generated uncovered-evidence candidates, not accepted regions. Select only candidates '
        'that correspond to a real missing semantic unit. Return exactly one JSON object with one array named "missing". Each '
        'entry is {"candidate_id":"M01","description":"...","expected_role":"...",'
        '"repair_route":"precise_locator|stage1_repartition","reason":"..."}. Return {"missing":[]} when no candidate qualifies. '
        "Stage1 roots in the JSON are structural parent boundaries and do not count as semantic coverage. Do not return rough_roi, "
        "bbox, final_bbox, click_point, candidate_point, actions, group reviews, parent IDs, or new IDs. "
        "Use stage1_repartition only when a Stage1 root combines separate structural panes; otherwise use precise_locator.\n\n"
        "Allowed expected_role values: "
        + ", ".join(sorted(ALLOWED_REVIEW_ROLES))
        + ".\n\nReviewed Stage2 evidence:\n"
        + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
        + "\n\nUncovered evidence candidates:\n"
        + json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
    )


def enforce_group_review_only_patch(patch: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(patch)
    missing = result.get("missing", [])
    discarded_count = len(missing) if isinstance(missing, list) else 0
    result["missing"] = []
    if discarded_count:
        adjustments = result.setdefault("protocol_adjustments", [])
        if not isinstance(adjustments, list):
            raise ValueError("group review protocol_adjustments must be a list")
        adjustments.append(
            {
                "category": "group_review_missing_suggestion_discarded",
                "discarded_count": discarded_count,
            }
        )
    return result


def parse_missing_region_audit_response(raw_text: str) -> dict[str, Any]:
    parsed = parse_model_review_response(raw_text)
    if set(parsed) != {"missing"}:
        raise ValueError("missing region audit response must contain only the missing array")
    missing = parsed.get("missing")
    if not isinstance(missing, list) or any(not isinstance(item, dict) for item in missing):
        raise ValueError("missing region audit missing must be a list of objects")
    return {"missing": deepcopy(missing)}


def build_missing_region_candidate_review_prompt(
    stage2: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    if not candidate_id:
        raise ValueError("missing region candidate requires candidate_id")
    evidence = _missing_region_candidate_context(stage2, candidate)
    return (
        f"Audit exactly one magenta GUI proposal {candidate_id}. The magenta rectangle is only a program question marker, "
        "not an accepted semantic region and not evidence that the area is already covered. Decide whether the visible content "
        "inside it is a coherent reusable GUI semantic unit. Accept repeated card rows, lists, panes, toolbars, navigation, or "
        "input areas. Reject empty space, decoration, separators, clipped fragments, isolated labels, or a box that mixes unrelated "
        "sections. The model may classify only; the program owns all geometry.\n\n"
        'Return exactly {"candidate_id":"M01","decision":"accept_candidate|reject_candidate",'
        '"description":"...","expected_role":"...","repair_route":"precise_locator|stage1_repartition",'
        '"reason":"..."}. Do not return bbox, rough_roi, point, action, parent ID, new ID, or any other key. '
        "Use stage1_repartition only when the structural parent itself combines separate panes; otherwise use precise_locator.\n\n"
        "Allowed expected_role values: "
        + ", ".join(sorted(ALLOWED_REVIEW_ROLES))
        + ".\n\nParent and local overlap context:\n"
        + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
        + "\n\nCandidate evidence:\n"
        + json.dumps(candidate, ensure_ascii=False, separators=(",", ":"))
    )


def _missing_region_candidate_context(
    stage2: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    parent_region_id = str(candidate.get("parent_region_id") or "")
    candidate_bbox = candidate.get("rough_roi") if isinstance(candidate.get("rough_roi"), dict) else {}
    parent = next(
        (
            root
            for root in stage2.get("regions", [])
            if isinstance(root, dict) and str(root.get("region_id") or "") == parent_region_id
        ),
        {},
    )
    candidate_area = _bbox_area(candidate_bbox)
    overlapping_groups: list[dict[str, Any]] = []
    for group in parent.get("subregion_groups", []) if isinstance(parent, dict) else []:
        if not isinstance(group, dict) or not isinstance(group.get("bbox"), dict):
            continue
        if _bbox_overlap_area(candidate_bbox, group["bbox"]) / max(1, candidate_area) < 0.05:
            continue
        overlapping_groups.append(
            {
                "group_id": str(group.get("group_id") or ""),
                "role": str(group.get("role") or "review_only"),
                "label": _short_text(group.get("label")),
                "bbox": deepcopy(group["bbox"]),
            }
        )
    overlapping_groups.sort(
        key=lambda item: (
            -_bbox_overlap_area(candidate_bbox, item["bbox"]),
            str(item["group_id"]),
        )
    )
    return {
        "parent_region_id": parent_region_id,
        "parent_label": _short_text(parent.get("label") if isinstance(parent, dict) else ""),
        "parent_bbox": deepcopy(parent.get("bbox") or {}) if isinstance(parent, dict) else {},
        "overlapping_existing_groups": overlapping_groups[:8],
        "overlapping_group_count": len(overlapping_groups),
    }


def parse_missing_region_candidate_review_response(
    raw_text: str,
    *,
    expected_candidate_id: str,
) -> dict[str, Any]:
    parsed = parse_model_review_response(raw_text)
    required_fields = {
        "candidate_id",
        "decision",
        "description",
        "expected_role",
        "repair_route",
        "reason",
    }
    if set(parsed) != required_fields:
        raise ValueError("missing region candidate review must contain exactly the required fields")
    candidate_id = str(parsed.get("candidate_id") or "").strip()
    if candidate_id != expected_candidate_id:
        raise ValueError(f"missing region candidate review returned {candidate_id}, expected {expected_candidate_id}")
    decision = str(parsed.get("decision") or "").strip()
    if decision not in {"accept_candidate", "reject_candidate"}:
        raise ValueError(f"invalid missing region candidate decision: {decision}")
    expected_role = str(parsed.get("expected_role") or "").strip()
    if decision == "reject_candidate":
        # 拒绝决定本身已经说明候选不应升级为语义区域，模型附带的临时角色不能反向制造协议失败。
        expected_role = "review_only"
    if expected_role not in MISSING_CANDIDATE_PROVISIONAL_ROLES:
        raise ValueError(f"invalid missing region candidate expected_role: {expected_role}")
    repair_route = str(parsed.get("repair_route") or "").strip()
    if repair_route not in {"precise_locator", "stage1_repartition"}:
        raise ValueError(f"invalid missing region candidate repair_route: {repair_route}")
    description = str(parsed.get("description") or "").strip()
    reason = str(parsed.get("reason") or "").strip()
    if not description or not reason:
        raise ValueError("missing region candidate review requires description and reason")
    return {
        "candidate_id": candidate_id,
        "decision": decision,
        "description": description,
        "expected_role": expected_role,
        "repair_route": repair_route,
        "reason": reason,
    }


def resolve_missing_region_audit_candidates(
    audit_patch: dict[str, Any],
    candidates: dict[str, Any],
) -> dict[str, Any]:
    candidates_by_id = {
        str(item.get("candidate_id") or ""): item
        for item in candidates.get("candidates", [])
        if isinstance(item, dict) and str(item.get("candidate_id") or "")
    }
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    allowed_fields = {"candidate_id", "description", "expected_role", "repair_route", "reason"}
    for item in audit_patch.get("missing", []):
        unexpected = sorted(set(item).difference(allowed_fields))
        if unexpected:
            raise ValueError(f"unexpected missing audit fields: {', '.join(unexpected)}")
        candidate_id = str(item.get("candidate_id") or "").strip()
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None:
            raise ValueError(f"unknown missing region candidate_id: {candidate_id}")
        if candidate_id in seen:
            raise ValueError(f"duplicate missing region candidate_id: {candidate_id}")
        seen.add(candidate_id)
        resolved.append(
            {
                "description": str(item.get("description") or "").strip(),
                "parent_region_id": str(candidate.get("parent_region_id") or "").strip(),
                "expected_role": str(item.get("expected_role") or "").strip(),
                "rough_roi": deepcopy(candidate.get("rough_roi") or {}),
                "repair_route": str(item.get("repair_route") or "precise_locator").strip(),
                "reason": str(item.get("reason") or "").strip(),
                "candidate_id": candidate_id,
                "candidate_member_item_ids": deepcopy(candidate.get("member_item_ids") or []),
                "geometry_source": str(candidate.get("generation_source") or ""),
            }
        )
    return {"missing": resolved}


def consolidate_missing_region_candidates(candidates: dict[str, Any]) -> dict[str, Any]:
    source_candidates = [
        deepcopy(item)
        for item in candidates.get("candidates", [])
        if isinstance(item, dict) and str(item.get("candidate_id") or "").strip()
    ]
    consolidated: list[dict[str, Any]] = []
    for candidate in source_candidates:
        candidate_id = str(candidate["candidate_id"]).strip()
        candidate["candidate_id"] = candidate_id
        candidate["merged_candidate_ids"] = [candidate_id]
        candidate["evidence_families"] = sorted(
            {str(candidate.get("evidence_family") or "unknown").strip() or "unknown"}
        )
        match_index = next(
            (
                index
                for index, existing in enumerate(consolidated)
                if _missing_candidates_share_semantic_footprint(existing, candidate)
            ),
            None,
        )
        if match_index is None:
            consolidated.append(candidate)
            continue
        existing = consolidated[match_index]
        existing["rough_roi"] = _bbox_union([existing["rough_roi"], candidate["rough_roi"]])
        existing["member_item_ids"] = sorted(
            {
                str(item_id).strip()
                for item_id in [
                    *(existing.get("member_item_ids") or []),
                    *(candidate.get("member_item_ids") or []),
                ]
                if str(item_id).strip()
            }
        )
        role_counts: dict[str, int] = {}
        for source in (existing.get("source_role_counts") or {}, candidate.get("source_role_counts") or {}):
            for role, count in source.items():
                role_counts[str(role)] = role_counts.get(str(role), 0) + int(count or 0)
        existing["source_role_counts"] = role_counts
        existing["merged_candidate_ids"] = sorted(
            {
                str(item_id)
                for item_id in [
                    *(existing.get("merged_candidate_ids") or []),
                    *(candidate.get("merged_candidate_ids") or []),
                ]
                if item_id
            }
        )
        existing["evidence_families"] = sorted(
            {
                str(family)
                for family in [
                    *(existing.get("evidence_families") or []),
                    *(candidate.get("evidence_families") or []),
                ]
                if family
            }
        )
        existing["evidence_family"] = "+".join(existing["evidence_families"])
        existing["generation_source"] = "uncovered_atomic_evidence_cluster_consolidated_v1"

    result = deepcopy(candidates)
    result["candidates"] = consolidated
    result["raw_candidate_count"] = len(source_candidates)
    result["candidate_count"] = len(consolidated)
    result["consolidated_candidate_count"] = len(source_candidates) - len(consolidated)
    return result


def enforce_missing_candidate_decision_policy(
    decision: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    result = deepcopy(decision)
    model_role = str(result.get("expected_role") or "review_only")
    result["model_expected_role"] = model_role
    result["policy_adjustment"] = "none"
    if result.get("decision") != "accept_candidate":
        return result

    role_counts = {
        str(role).casefold(): int(count or 0)
        for role, count in (candidate.get("source_role_counts") or {}).items()
        if int(count or 0) > 0
    }
    roles = set(role_counts)
    if roles and roles.issubset({"group", "pane", "separator"}):
        result["decision"] = "reject_candidate"
        result["expected_role"] = "review_only"
        result["policy_adjustment"] = "rejected_generic_container_evidence_only"
        result["reason"] = "; ".join(
            filter(
                None,
                [
                    str(result.get("reason") or "").strip(),
                    "atomic evidence contains only generic container roles",
                ],
            )
        )
        return result

    parent_region_id = str(candidate.get("parent_region_id") or "").casefold()
    member_count = len(candidate.get("member_item_ids") or [])
    rejection_reason = ""
    rejection_category = ""
    if "left_nav" in parent_region_id and model_role == "navigation":
        rejection_category = "rejected_redundant_parent_navigation_region"
        rejection_reason = "atomic navigation controls already belong directly to the navigation parent"
    elif "conversation_list" in parent_region_id and model_role == "message_item":
        rejection_category = "rejected_parent_semantic_conflict"
        rejection_reason = "message_item cannot be introduced inside a conversation-list parent without message evidence"
    elif "bottom_composer" in parent_region_id and model_role not in {"input_region", "toolbar", "review_only"}:
        rejection_category = "rejected_parent_semantic_conflict"
        rejection_reason = "bottom-composer candidates must remain input, toolbar, or review-only regions"
    elif member_count < 2 and roles and roles.issubset({"text", "label", "heading", "title"}):
        rejection_category = "rejected_insufficient_atomic_evidence"
        rejection_reason = "one text fragment is insufficient evidence for a new semantic region"
    if rejection_category:
        result["decision"] = "reject_candidate"
        result["expected_role"] = "review_only"
        result["policy_adjustment"] = rejection_category
        result["reason"] = "; ".join(
            filter(None, [str(result.get("reason") or "").strip(), rejection_reason])
        )
        return result

    normalized_role: str | None = None
    if model_role in {"status_bar", "bottom_bar"} or roles.intersection(
        {"status_bar", "status_bar_evidence", "bottom_bar", "bottom_bar_evidence"}
    ):
        normalized_role = "review_only"
    elif roles.intersection({"tab", "nav_item", "navigation", "menu_item"}):
        normalized_role = "navigation"
    elif roles.intersection({"input", "edit", "textbox", "search_box"}):
        normalized_role = "input_region"
    elif model_role == "conversation_row":
        normalized_role = "list_item"
    elif sum(role_counts.get(role, 0) for role in ("button", "text_button", "control")) >= 2:
        normalized_role = "toolbar"

    if normalized_role is not None and normalized_role != model_role:
        result["expected_role"] = normalized_role
        result["policy_adjustment"] = f"normalized_role_from_atomic_evidence:{model_role}->{normalized_role}"
    return result


def _missing_candidates_share_semantic_footprint(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if str(left.get("parent_region_id") or "") != str(right.get("parent_region_id") or ""):
        return False
    left_bbox = left.get("rough_roi") if isinstance(left.get("rough_roi"), dict) else {}
    right_bbox = right.get("rough_roi") if isinstance(right.get("rough_roi"), dict) else {}
    left_area = _bbox_area(left_bbox)
    right_area = _bbox_area(right_bbox)
    smaller_area = min(left_area, right_area)
    larger_area = max(left_area, right_area)
    if smaller_area <= 0 or larger_area <= 0 or smaller_area / larger_area < 0.25:
        return False
    return _bbox_overlap_area(left_bbox, right_bbox) / smaller_area >= 0.8


def merge_missing_region_audit(
    base_patch: dict[str, Any],
    audit_patch: dict[str, Any] | None,
    *,
    protocol_error: str | None = None,
) -> dict[str, Any]:
    merged = deepcopy(base_patch)
    existing = merged.setdefault("missing", [])
    if not isinstance(existing, list):
        raise ValueError("base review patch missing must be a list")
    if protocol_error:
        needs_review = merged.setdefault("needs_human_review", [])
        if not isinstance(needs_review, list):
            raise ValueError("base review patch needs_human_review must be a list")
        needs_review.append(
            {
                "region_id": "",
                "reason": f"missing region audit protocol failure: {protocol_error}",
            }
        )
        return merged
    if audit_patch is None:
        raise ValueError("missing region audit patch is required when protocol_error is absent")
    for item in audit_patch.get("missing", []):
        if item not in existing:
            existing.append(deepcopy(item))
    return merged


def build_missing_region_candidates(stage2: dict[str, Any]) -> dict[str, Any]:
    raw_candidates: list[dict[str, Any]] = []
    suppressed_explicit_item_count = 0
    for root in stage2.get("regions", []):
        if not isinstance(root, dict) or not isinstance(root.get("bbox"), dict):
            continue
        parent_region_id = str(root.get("region_id") or "").strip()
        if not parent_region_id:
            continue
        root_bbox = root["bbox"]
        root_area = _bbox_area(root_bbox)
        groups = [
            group
            for group in root.get("subregion_groups", [])
            if isinstance(group, dict) and isinstance(group.get("bbox"), dict)
        ]
        owned_ids = {
            str(item_id or "").strip()
            for group in groups
            for item_id in group.get("member_item_ids", [])
            if str(item_id or "").strip()
        }
        uncovered: list[dict[str, Any]] = []
        for item in root.get("numbered_items", []):
            if not isinstance(item, dict) or not isinstance(item.get("bbox"), dict):
                continue
            if item.get("render_in_main_overlay") is False:
                suppressed_explicit_item_count += 1
                continue
            item_id = str(item.get("item_id") or "").strip()
            item_bbox = item["bbox"]
            item_area = _bbox_area(item_bbox)
            if not item_id or item_id in owned_ids or item_area < max(64, int(root_area * 0.00005)):
                continue
            if any(
                _bbox_overlap_area(item_bbox, group["bbox"]) / max(1, item_area) >= 0.8
                and _bbox_area(group["bbox"]) <= item_area * 1.5
                for group in groups
            ):
                continue
            uncovered.append(item)
        family_items: dict[str, list[dict[str, Any]]] = {}
        for item in uncovered:
            family_items.setdefault(_atomic_evidence_family(item), []).append(item)
        for family in sorted(family_items):
            for cluster in _cluster_uncovered_atomic_items(family_items[family]):
                boxes = [item["bbox"] for item in cluster]
                roi = _bbox_union(boxes)
                if _bbox_area(roi) < max(256, int(root_area * 0.001)):
                    continue
                role_counts: dict[str, int] = {}
                for item in cluster:
                    role = str(item.get("role") or item.get("item_type") or "unknown").strip() or "unknown"
                    role_counts[role] = role_counts.get(role, 0) + 1
                raw_candidates.append(
                    {
                        "parent_region_id": parent_region_id,
                        "rough_roi": roi,
                        "member_item_ids": sorted(str(item.get("item_id") or "") for item in cluster),
                        "source_role_counts": dict(sorted(role_counts.items())),
                        "evidence_family": family,
                        "generation_source": "uncovered_atomic_evidence_cluster_v2",
                        "_priority_score": min(len(cluster), 10) * 2
                        + min((_bbox_area(roi) / max(1, root_area)) * 100, 10),
                    }
                )
    ranked_candidates = sorted(
        raw_candidates,
        key=lambda item: (
            -float(item["_priority_score"]),
            -_bbox_area(item["rough_roi"]),
            int(item["rough_roi"].get("y") or 0),
            int(item["rough_roi"].get("x") or 0),
        ),
    )[:16]
    selected_candidates = [
        {key: value for key, value in candidate.items() if not key.startswith("_")}
        for candidate in ranked_candidates
    ]
    selected_candidates.sort(
        key=lambda item: (
            int(item["rough_roi"].get("y") or 0),
            int(item["rough_roi"].get("x") or 0),
            str(item["parent_region_id"]),
        )
    )
    candidates = [
        {"candidate_id": f"M{index:02d}", **candidate}
        for index, candidate in enumerate(selected_candidates, start=1)
    ]
    return {
        "contract_version": "learning_missing_region_candidates_v1",
        "raw_candidate_count": len(raw_candidates),
        "truncated_candidate_count": max(0, len(raw_candidates) - len(candidates)),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "suppressed_explicit_item_count": suppressed_explicit_item_count,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def exclude_candidates_covered_by_missing_repairs(
    candidates: dict[str, Any],
    review_patch: dict[str, Any],
    *,
    coverage_threshold: float = 0.8,
) -> dict[str, Any]:
    repair_boxes = [
        item["rough_roi"]
        for item in review_patch.get("missing", [])
        if isinstance(item, dict) and isinstance(item.get("rough_roi"), dict)
    ]
    kept: list[dict[str, Any]] = []
    excluded_ids: list[str] = []
    for candidate in candidates.get("candidates", []):
        if not isinstance(candidate, dict) or not isinstance(candidate.get("rough_roi"), dict):
            continue
        candidate_area = _bbox_area(candidate["rough_roi"])
        covered = any(
            _bbox_overlap_area(candidate["rough_roi"], repair_box) / max(1, candidate_area)
            >= coverage_threshold
            for repair_box in repair_boxes
        )
        if covered:
            excluded_ids.append(str(candidate.get("candidate_id") or ""))
        else:
            kept.append(deepcopy(candidate))
    result = deepcopy(candidates)
    result["candidates"] = kept
    result["candidate_count"] = len(kept)
    result["excluded_candidate_ids"] = excluded_ids
    result["existing_repair_coverage_threshold"] = coverage_threshold
    return result


def _cluster_uncovered_atomic_items(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    remaining = list(items)
    clusters: list[list[dict[str, Any]]] = []
    while remaining:
        cluster = [remaining.pop(0)]
        changed = True
        while changed:
            changed = False
            for item in list(remaining):
                if any(_atomic_evidence_nearby(item["bbox"], member["bbox"]) for member in cluster):
                    cluster.append(item)
                    remaining.remove(item)
                    changed = True
        clusters.append(cluster)
    return clusters


def _atomic_evidence_family(item: dict[str, Any]) -> str:
    role = str(item.get("role") or item.get("item_type") or "unknown").strip().lower()
    if any(token in role for token in ("card", "tile", "media", "recommendation")):
        return "visual_card"
    if any(token in role for token in ("nav", "sidebar", "tab")):
        return "navigation"
    if any(token in role for token in ("button", "control", "action", "input", "field")):
        return "control"
    if any(token in role for token in ("list", "message", "row", "member")):
        return "list_content"
    if any(token in role for token in ("text", "heading", "label", "title")):
        return "text"
    return f"other:{role or 'unknown'}"


def _atomic_evidence_nearby(left: dict[str, Any], right: dict[str, Any]) -> bool:
    lx1, ly1, lx2, ly2 = _bbox_edges(left)
    rx1, ry1, rx2, ry2 = _bbox_edges(right)
    horizontal_overlap = max(0, min(lx2, rx2) - max(lx1, rx1))
    vertical_overlap = max(0, min(ly2, ry2) - max(ly1, ry1))
    horizontal_gap = max(0, max(lx1, rx1) - min(lx2, rx2))
    vertical_gap = max(0, max(ly1, ry1) - min(ly2, ry2))
    min_width = max(1, min(lx2 - lx1, rx2 - rx1))
    min_height = max(1, min(ly2 - ly1, ry2 - ry1))
    same_row = vertical_overlap / min_height >= 0.25 and horizontal_gap <= max(40, int(min_width * 0.4))
    same_column = horizontal_overlap / min_width >= 0.25 and vertical_gap <= max(24, int(min_height * 0.35))
    return same_row or same_column


def partition_model_review_scope(stage2: dict[str, Any]) -> dict[str, Any]:
    model_stage2 = deepcopy(stage2)
    deterministic_keep_reviews: list[dict[str, Any]] = []
    model_group_count = 0
    for root in model_stage2.get("regions", []):
        if not isinstance(root, dict):
            continue
        root_bbox = root.get("bbox") if isinstance(root.get("bbox"), dict) else {}
        model_groups: list[dict[str, Any]] = []
        for group in root.get("subregion_groups", []):
            if not isinstance(group, dict):
                continue
            deterministic_source = ""
            deterministic_reason = ""
            if _is_valid_deterministic_leaf_group(group, root_bbox=root_bbox):
                deterministic_source = "deterministic_leaf_invariant"
                deterministic_reason = "deterministic leaf-row geometry and parent containment passed"
            elif _is_valid_deterministic_table_group(group, root_bbox=root_bbox):
                deterministic_source = "deterministic_table_structure_invariant"
                deterministic_reason = "deterministic aligned-table parent and row hierarchy passed"
            elif _is_valid_deterministic_partial_visible_group(group, root_bbox=root_bbox):
                deterministic_source = "deterministic_partial_visibility_invariant"
                deterministic_reason = "source-proven partial visibility geometry and parent containment passed"
            elif _is_valid_deterministic_bar_group(group, root_bbox=root_bbox):
                deterministic_source = "deterministic_bar_structure_invariant"
                deterministic_reason = "deterministic bar reconstruction and parent containment passed"
            if deterministic_source:
                deterministic_keep_reviews.append(
                    {
                        "region_id": str(group.get("group_id") or ""),
                        "decision": "keep",
                        "new_role": None,
                        "reason": deterministic_reason,
                        "review_source": deterministic_source,
                    }
                )
                continue
            model_groups.append(group)
            model_group_count += 1
        root["subregion_groups"] = model_groups
    return {
        "contract_version": "learning_model_review_scope_v1",
        "model_stage2": model_stage2,
        "deterministic_keep_reviews": deterministic_keep_reviews,
        "model_group_count": model_group_count,
        "deterministic_keep_count": len(deterministic_keep_reviews),
    }


def merge_deterministic_review_keeps(
    patch: dict[str, Any],
    deterministic_keep_reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = deepcopy(patch)
    reviews = [
        deepcopy(item)
        for item in merged.get("group_reviews", [])
        if isinstance(item, dict)
    ]
    seen = {str(item.get("region_id") or "") for item in reviews}
    adjustments = [
        deepcopy(item)
        for item in merged.get("protocol_adjustments", [])
        if isinstance(item, dict)
    ]
    for review in deterministic_keep_reviews:
        region_id = str(review.get("region_id") or "")
        if not region_id or region_id in seen:
            continue
        reviews.append(deepcopy(review))
        seen.add(region_id)
        adjustments.append(
            {
                "category": "deterministic_leaf_review_preserved",
                "region_id": region_id,
            }
        )
    merged["group_reviews"] = reviews
    merged["protocol_adjustments"] = adjustments
    return merged


def _is_valid_deterministic_leaf_group(
    group: dict[str, Any],
    *,
    root_bbox: dict[str, Any],
) -> bool:
    if str(group.get("role") or "") not in DETERMINISTIC_LEAF_REVIEW_ROLES:
        return False
    bbox = group.get("bbox") if isinstance(group.get("bbox"), dict) else {}
    try:
        gx1, gy1, gx2, gy2 = _bbox_edges(bbox)
        rx1, ry1, rx2, ry2 = _bbox_edges(root_bbox)
    except (TypeError, ValueError):
        return False
    if gx1 < rx1 or gy1 < ry1 or gx2 > rx2 or gy2 > ry2:
        return False
    root_width = max(1, rx2 - rx1)
    root_height = max(1, ry2 - ry1)
    group_width = gx2 - gx1
    group_height = gy2 - gy1
    if group_width <= 0 or group_height <= 0:
        return False
    if group_height / root_height > 0.25 or (group_width * group_height) / (root_width * root_height) > 0.25:
        return False
    if group.get("child_group_ids") or group.get("resolved_child_group_ids"):
        return False
    members = group.get("member_item_ids") or group.get("member_numbers") or []
    return isinstance(members, list) and bool(members)


def _is_valid_deterministic_bar_group(
    group: dict[str, Any],
    *,
    root_bbox: dict[str, Any],
) -> bool:
    if str(group.get("role") or "") not in DETERMINISTIC_BAR_REVIEW_ROLES:
        return False
    if str(group.get("source") or "") != "stage2_direct_bar_parent_reconstruction":
        return False
    bbox = group.get("bbox") if isinstance(group.get("bbox"), dict) else {}
    try:
        gx1, gy1, gx2, gy2 = _bbox_edges(bbox)
        rx1, ry1, rx2, ry2 = _bbox_edges(root_bbox)
    except (TypeError, ValueError):
        return False
    if gx1 < rx1 or gy1 < ry1 or gx2 > rx2 or gy2 > ry2 or gx2 <= gx1 or gy2 <= gy1:
        return False
    members = group.get("member_item_ids") or group.get("member_numbers") or []
    return isinstance(members, list) and bool(members)


def _is_valid_deterministic_table_group(
    group: dict[str, Any],
    *,
    root_bbox: dict[str, Any],
) -> bool:
    if str(group.get("role") or "") != "table_group":
        return False
    if str(group.get("source") or "") != "stage2_dense_aligned_table_parent_synthesis":
        return False
    bbox = group.get("bbox") if isinstance(group.get("bbox"), dict) else {}
    try:
        gx1, gy1, gx2, gy2 = _bbox_edges(bbox)
        rx1, ry1, rx2, ry2 = _bbox_edges(root_bbox)
    except (TypeError, ValueError):
        return False
    if gx1 < rx1 or gy1 < ry1 or gx2 > rx2 or gy2 > ry2 or gx2 <= gx1 or gy2 <= gy1:
        return False
    child_ids = group.get("child_group_ids")
    child_roles = group.get("child_group_roles")
    members = group.get("member_item_ids") or group.get("member_numbers") or []
    return (
        isinstance(child_ids, list)
        and len(child_ids) >= 2
        and isinstance(child_roles, list)
        and len(child_roles) == len(child_ids)
        and all(str(role or "") == "table_row" for role in child_roles)
        and isinstance(members, list)
        and bool(members)
    )


def _is_valid_deterministic_partial_visible_group(
    group: dict[str, Any],
    *,
    root_bbox: dict[str, Any],
) -> bool:
    if str(group.get("role") or "") != "partial_visible_card_group":
        return False
    if str(group.get("expected_item_role") or "") != "partial_visible_card":
        return False
    if str(group.get("source") or "") != "stage2_primary_content_card_row_grouping":
        return False
    bbox = group.get("bbox") if isinstance(group.get("bbox"), dict) else {}
    try:
        gx1, gy1, gx2, gy2 = _bbox_edges(bbox)
        rx1, ry1, rx2, ry2 = _bbox_edges(root_bbox)
    except (TypeError, ValueError):
        return False
    return gx1 >= rx1 and gy1 >= ry1 and gx2 <= rx2 and gy2 <= ry2 and gx2 > gx1 and gy2 > gy1


def parse_model_review_response(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.casefold().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model review response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("model review response must be a JSON object")
    return parsed


def normalize_model_review_protocol(
    stage2: dict[str, Any],
    patch: dict[str, Any],
    *,
    review_id_map: dict[str, str],
) -> dict[str, Any]:
    normalized = deepcopy(patch)
    reviews = normalized.get("group_reviews")
    if not isinstance(reviews, list):
        normalized.setdefault("protocol_adjustments", [])
        return normalized

    valid_group_ids = _group_ids(stage2)
    source_roles = {
        str(record.get("group_id") or "").strip(): str(record.get("role") or "").strip()
        for record in _group_review_records(stage2)
        if str(record.get("group_id") or "").strip()
    }
    adjustments: list[dict[str, Any]] = []
    normalized_reviews: list[dict[str, Any]] = []
    protocol_needs_review = [
        deepcopy(item)
        for item in normalized.get("needs_human_review", [])
        if isinstance(item, dict)
    ]
    seen_group_ids: set[str] = set()
    for review in reviews:
        if not isinstance(review, dict):
            normalized_reviews.append(review)
            continue
        item = deepcopy(review)
        supplied_id = str(item.get("region_id") or "").strip()
        resolved_id = _resolve_model_review_region_id(
            supplied_id,
            review_id_map=review_id_map,
        )
        if resolved_id != supplied_id:
            item["region_id"] = resolved_id
            item["model_supplied_region_id"] = supplied_id
            adjustments.append(
                {
                    "category": "overlay_alias_resolved",
                    "model_supplied_region_id": supplied_id,
                    "resolved_region_id": resolved_id,
                }
            )

        decision = str(item.get("decision") or "").strip()
        model_requested_role = str(item.get("new_role") or "").strip()
        requested_role = REVIEW_ROLE_ALIASES.get(model_requested_role, model_requested_role)
        if decision == "relabel" and requested_role != model_requested_role:
            item["new_role"] = requested_role
            adjustments.append(
                {
                    "category": "review_role_alias_canonicalized",
                    "region_id": resolved_id,
                    "model_requested_role": model_requested_role,
                    "canonical_role": requested_role,
                }
            )
        source_role = source_roles.get(resolved_id, "")
        if decision == "relabel" and requested_role and requested_role == source_role:
            item["decision"] = "keep"
            item["new_role"] = None
            adjustments.append(
                {
                    "category": "same_role_relabel_normalized_to_keep",
                    "region_id": resolved_id,
                    "role": source_role,
                }
            )
        elif decision == "relabel" and requested_role not in ALLOWED_REVIEW_ROLES:
            item["decision"] = "needs_human_review"
            item["new_role"] = None
            item["model_requested_role"] = requested_role
            item["reason"] = (
                f"unsupported relabel role requires human review: {requested_role}; "
                + str(item.get("reason") or "").strip()
            ).strip()
            adjustments.append(
                {
                    "category": "unsupported_relabel_safe_stopped",
                    "region_id": resolved_id,
                    "model_requested_role": requested_role,
                }
            )
        if resolved_id and resolved_id not in valid_group_ids:
            adjustments.append(
                {
                    "category": "unknown_region_reference_rejected",
                    "model_supplied_region_id": supplied_id,
                    "resolved_region_id": resolved_id,
                }
            )
            protocol_needs_review.append(
                {
                    "region_id": "",
                    "reason": f"model review referenced unknown region_id: {resolved_id}",
                }
            )
            continue
        if resolved_id in seen_group_ids:
            adjustments.append(
                {
                    "category": "duplicate_group_review_safe_stopped",
                    "region_id": resolved_id,
                }
            )
            for existing in normalized_reviews:
                if str(existing.get("region_id") or "") == resolved_id:
                    existing["decision"] = "needs_human_review"
                    existing["new_role"] = None
                    existing["reason"] = "duplicate model review entries require human review"
                    break
            continue
        seen_group_ids.add(resolved_id)
        normalized_reviews.append(item)

    for missing_group_id in sorted(valid_group_ids.difference(seen_group_ids)):
        normalized_reviews.append(
            {
                "region_id": missing_group_id,
                "decision": "needs_human_review",
                "new_role": None,
                "reason": "model omitted required group review; safe-stopped by protocol completion",
            }
        )
        adjustments.append(
            {
                "category": "omitted_group_safe_stopped",
                "region_id": missing_group_id,
            }
        )

    normalized["group_reviews"] = normalized_reviews
    normalized["needs_human_review"] = protocol_needs_review
    normalized["protocol_adjustments"] = adjustments
    return normalized


def _resolve_model_review_region_id(
    supplied_id: str,
    *,
    review_id_map: dict[str, str],
) -> str:
    exact = str(review_id_map.get(supplied_id) or "")
    if exact:
        return exact
    for review_id, region_id in review_id_map.items():
        if supplied_id.startswith(f"{review_id}_"):
            return str(region_id)
    return supplied_id


def focused_card_review_records(stage2: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        deepcopy(record)
        for record in _group_review_records(stage2)
        if str(record.get("role") or "") in FOCUSED_CARD_REVIEW_ROLES
    ]


def build_focused_group_review_prompt(record: dict[str, Any]) -> str:
    review_id = str(record.get("review_id") or "")
    return (
        "Audit exactly one highlighted GUI group in the supplied review overlay. "
        "The opaque review ID carries no semantics. Judge the pixels and member evidence, not the current role or parent name. "
        "Decide whether the highlighted group is one coherent card, a content pane, a container of multiple independent rows, "
        "a message, or an invalid merged wrapper. Filename lists and source-code text are not conversation/message evidence.\n"
        f"Exact region_id: {review_id}\n"
        f"Source role hypothesis: {record.get('role')}\n"
        f"Current bbox: {json.dumps(record.get('bbox') or {}, separators=(',', ':'))}\n"
        f"Member count: {int(record.get('member_count') or 0)}\n"
        f"Member evidence: {json.dumps(record.get('member_evidence') or [], ensure_ascii=False, separators=(',', ':'))}\n"
        f"Stage1 parent role/label hypothesis: {record.get('parent_label')}\n"
        f"Stage1 parent bbox: {json.dumps(record.get('parent_bbox') or {}, separators=(',', ':'))}\n"
        "Return one JSON object with exact keys region_id, decision, new_role, observed_role, geometry_quality, "
        "parent_relation, structural_repair, reason. geometry_quality must be exact_semantic_unit, overmerged, "
        "fragment, or uncertain. parent_relation must be valid_child, distinct_pane, or uncertain. "
        "region_id must exactly equal the supplied exact region_id. decision must be keep, remove, relabel, "
        "or needs_human_review. new_role must be null unless decision is relabel. Allowed new_role values are "
        + ", ".join(sorted(ALLOWED_REVIEW_ROLES))
        + ". observed_role must use the same allowed role list. If the current group is an incorrect merged wrapper "
        "and its pixels are already represented by valid child "
        "items, remove the wrapper. Relabel only when the bbox itself is one complete, useful semantic unit. "
        "When decision is remove with structural_repair, observed_role must differ from the source role and name the "
        "replacement structure. Source code, document, and detail panes use content_region, not message_item. "
        "Use member_list for repeated people rows with avatars, names, roles, or member badges; use list_container "
        "for other repeated rows; use content_region for a coherent code, document, or detail pane. "
        + ". structural_repair must be none or stage1_repartition. Use stage1_repartition only when this group "
        "reveals a visually distinct pane/list that the current Stage1 parent incorrectly merged with another pane. "
        "If the region contains many independent rows, it is not one coherent card. Do not return a bbox or click point."
    )


def parse_focused_group_review_response(
    raw_text: str,
    *,
    expected_region_id: str,
    source_region_id: str | None = None,
    source_role: str | None = None,
) -> dict[str, Any]:
    parsed = parse_model_review_response(raw_text)
    region_id = str(parsed.get("region_id") or "").strip()
    if region_id != expected_region_id:
        raise ValueError(f"focused review must use exact region_id: {expected_region_id}")
    decision = str(parsed.get("decision") or "").strip()
    if decision not in {"keep", "remove", "relabel", "needs_human_review"}:
        raise ValueError(f"unsupported focused review decision: {decision}")
    new_role = parsed.get("new_role")
    if decision == "relabel":
        new_role = str(new_role or "").strip()
        if new_role not in ALLOWED_REVIEW_ROLES:
            raise ValueError(f"unsupported role: {new_role}")
    else:
        new_role = None
    structural_repair = str(parsed.get("structural_repair") or "none").strip()
    if structural_repair not in {"none", "stage1_repartition"}:
        raise ValueError(f"unsupported structural_repair: {structural_repair}")
    observed_role = str(parsed.get("observed_role") or "").strip()
    observed_role_normalized = ""
    if source_region_id and observed_role == source_region_id:
        recovered_role = FOCUSED_OBSERVED_ROLE_ALIASES.get(str(source_role or "").strip(), str(source_role or "").strip())
        if recovered_role in ALLOWED_REVIEW_ROLES | FOCUSED_CARD_REVIEW_ROLES:
            # 模型偶尔把目标区域 ID 复制进角色字段；这里只允许从同一输入记录恢复已知角色。
            observed_role = recovered_role
            observed_role_normalized = "source_role_from_copied_region_id"
    observed_role = FOCUSED_OBSERVED_ROLE_ALIASES.get(observed_role, observed_role)
    if observed_role not in ALLOWED_REVIEW_ROLES | FOCUSED_CARD_REVIEW_ROLES:
        raise ValueError(f"unsupported observed_role: {observed_role}")
    geometry_quality = str(parsed.get("geometry_quality") or "").strip()
    if geometry_quality not in FOCUSED_GEOMETRY_QUALITIES:
        raise ValueError(f"unsupported geometry_quality: {geometry_quality}")
    parent_relation = str(parsed.get("parent_relation") or "").strip()
    if parent_relation not in FOCUSED_PARENT_RELATIONS:
        raise ValueError(f"unsupported parent_relation: {parent_relation}")

    model_decision = decision
    preserve_container_relabel = (
        geometry_quality == "overmerged"
        and parent_relation == "valid_child"
        and decision == "relabel"
        and new_role in FOCUSED_SAFE_CONTAINER_ROLES
    )
    if (geometry_quality in {"overmerged", "fragment"} and not preserve_container_relabel) or parent_relation == "distinct_pane":
        decision = "remove"
        new_role = None
    elif geometry_quality == "uncertain" or parent_relation == "uncertain":
        decision = "needs_human_review"
        new_role = None
    if parent_relation == "distinct_pane":
        structural_repair = "stage1_repartition"
    result = {
        "region_id": region_id,
        "decision": decision,
        "new_role": new_role,
        "observed_role": observed_role,
        "geometry_quality": geometry_quality,
        "parent_relation": parent_relation,
        "model_decision": model_decision,
        "structural_repair": structural_repair,
        "reason": str(parsed.get("reason") or "").strip(),
    }
    if observed_role_normalized:
        result["observed_role_normalized"] = observed_role_normalized
    return result


def enforce_focused_semantic_transition(
    record: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    checked = deepcopy(review)
    source_role = str(record.get("role") or "").strip()
    target_role = str(checked.get("new_role") or "").strip()
    observed_role = str(checked.get("observed_role") or "").strip()
    if (
        checked.get("decision") == "remove"
        and checked.get("structural_repair") == "stage1_repartition"
        and observed_role == source_role
    ):
        if checked.get("geometry_quality") == "overmerged" and int(record.get("member_count") or 0) > 0:
            # 过度合并父框可以直接删除；其原子子项仍由现有父区承载，不需要重建同角色父框。
            checked["structural_repair"] = "none"
            checked["semantic_transition_normalized"] = "overmerged_wrapper_children_reparented"
            return checked
        checked["decision"] = "needs_human_review"
        checked["new_role"] = None
        checked["structural_repair"] = "none"
        checked["semantic_transition_blocked"] = "repair_recreates_rejected_role"
        checked["reason"] = (
            "structural repair cannot recreate the rejected source role; "
            + str(checked.get("reason") or "").strip()
        ).strip()
        return checked
    if (
        checked.get("decision") == "remove"
        and checked.get("structural_repair") == "stage1_repartition"
        and checked.get("geometry_quality") == "exact_semantic_unit"
        and observed_role in ALLOWED_REVIEW_ROLES
        and not (source_role in FOCUSED_CARD_REVIEW_ROLES and observed_role == "message_item")
    ):
        checked["decision"] = "relabel"
        checked["new_role"] = observed_role
        checked["structural_repair"] = "none"
        checked["semantic_transition_normalized"] = "exact_unit_relabel_in_place"
        return checked
    if (
        checked.get("decision") == "remove"
        and checked.get("structural_repair") == "stage1_repartition"
        and checked.get("geometry_quality") in {"exact_semantic_unit", "overmerged"}
    ):
        checked["structural_repair"] = "none"
        checked["semantic_transition_normalized"] = "overmerged_wrapper_children_reparented"
        return checked
    if (
        checked.get("decision") == "relabel"
        and source_role in FOCUSED_CARD_REVIEW_ROLES
        and target_role == "message_item"
    ):
        checked["decision"] = "needs_human_review"
        checked["new_role"] = None
        checked["semantic_transition_blocked"] = "card_family_to_message_item"
        checked["reason"] = (
            "cross-family relabel requires independent message/thread evidence; "
            + str(checked.get("reason") or "").strip()
        ).strip()
    return checked


def merge_focused_group_reviews(
    *,
    stage2: dict[str, Any],
    base_patch: dict[str, Any],
    focused_reviews: list[dict[str, Any]],
) -> dict[str, Any]:
    merged = deepcopy(base_patch)
    base_reviews = merged.get("group_reviews")
    if not isinstance(base_reviews, list):
        raise ValueError("base review patch must contain group_reviews")
    records = {str(item["group_id"]): item for item in _group_review_records(stage2)}
    by_id = {
        str(item.get("region_id") or ""): deepcopy(item)
        for item in base_reviews
        if isinstance(item, dict) and str(item.get("region_id") or "")
    }
    missing = [deepcopy(item) for item in merged.get("missing", []) if isinstance(item, dict)]
    for review in focused_reviews:
        if not isinstance(review, dict):
            raise ValueError("focused review must be a JSON object")
        region_id = str(review.get("region_id") or "").strip()
        record = records.get(region_id)
        if record is None or str(record.get("role") or "") not in FOCUSED_CARD_REVIEW_ROLES:
            raise ValueError(f"focused review references unsupported region_id: {region_id}")
        decision = str(review.get("decision") or "").strip()
        if decision not in {"keep", "remove", "relabel", "needs_human_review"}:
            raise ValueError(f"unsupported focused review decision: {decision}")
        new_role = review.get("new_role")
        if decision == "relabel":
            new_role = str(new_role or "").strip()
            if new_role not in ALLOWED_REVIEW_ROLES:
                raise ValueError(f"unsupported role: {new_role}")
        else:
            new_role = None
        structural_repair = str(review.get("structural_repair") or "none").strip()
        if structural_repair not in {"none", "stage1_repartition"}:
            raise ValueError(f"unsupported structural_repair: {structural_repair}")
        by_id[region_id] = {
            "region_id": region_id,
            "decision": decision,
            "new_role": new_role,
            "reason": str(review.get("reason") or "").strip(),
            "review_source": "focused_card_review",
        }
        if structural_repair == "stage1_repartition":
            expected_role = str(review.get("observed_role") or new_role or "list_container")
            repair = {
                "description": f"Recover structural {expected_role} identified by focused review",
                "parent_region_id": record["parent_region_id"],
                "expected_role": expected_role,
                "rough_roi": deepcopy(record["bbox"]),
                "repair_route": "stage1_repartition",
                "reason": str(review.get("reason") or "").strip(),
            }
            _add_missing_repair(missing, repair)
    for repair in _edge_aligned_repartition_repairs(stage2, focused_reviews):
        _add_missing_repair(missing, repair)
    merged["group_reviews"] = [by_id[key] for key in sorted(by_id)]
    merged["missing"] = missing
    return merged


def _edge_aligned_repartition_repairs(
    stage2: dict[str, Any],
    focused_reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = {str(item["group_id"]): item for item in _group_review_records(stage2)}
    roots = {
        str(root.get("region_id") or ""): root
        for root in stage2.get("regions", [])
        if isinstance(root, dict) and isinstance(root.get("bbox"), dict)
    }
    buckets: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for review in focused_reviews:
        if (
            not isinstance(review, dict)
            or review.get("decision") != "remove"
            or review.get("geometry_quality") != "overmerged"
            or review.get("observed_role") not in {"list_container", "member_list"}
        ):
            continue
        record = records.get(str(review.get("region_id") or ""))
        if record is None:
            continue
        root = roots.get(str(record.get("parent_region_id") or ""))
        if root is None:
            continue
        rx1, _ry1, rx2, _ry2 = _bbox_edges(root["bbox"])
        x1, _y1, x2, _y2 = _bbox_edges(record["bbox"])
        edge_margin = max(12, int((rx2 - rx1) * 0.08))
        side = "left" if abs(x1 - rx1) <= edge_margin else "right" if abs(x2 - rx2) <= edge_margin else ""
        if side:
            buckets.setdefault((str(record["parent_region_id"]), side), []).append((record, review))

    repairs: list[dict[str, Any]] = []
    for (parent_id, _side), entries in buckets.items():
        if len(entries) < 2:
            continue
        root_bbox = roots[parent_id]["bbox"]
        parent_x1, parent_y1, parent_x2, parent_y2 = _bbox_edges(root_bbox)
        ordered = sorted(entries, key=lambda item: _bbox_edges(item[0]["bbox"])[1])
        max_gap = max(24, int((parent_y2 - parent_y1) * 0.18))
        if any(
            _bbox_edges(current[0]["bbox"])[1] - _bbox_edges(previous[0]["bbox"])[3] > max_gap
            for previous, current in zip(ordered, ordered[1:])
        ):
            continue
        boxes = [entry[0]["bbox"] for entry in ordered]
        union = _bbox_union(boxes)
        if union["h"] < int((parent_y2 - parent_y1) * 0.45):
            continue
        if union["w"] > int((parent_x2 - parent_x1) * 0.45):
            continue
        expected_role = (
            "member_list" if any(entry[1].get("observed_role") == "member_list" for entry in ordered) else "list_container"
        )
        repairs.append(
            {
                "description": f"Recover edge-aligned {expected_role} from removed review fragments",
                "parent_region_id": parent_id,
                "expected_role": expected_role,
                "rough_roi": union,
                "repair_route": "stage1_repartition",
                "reason": "multiple removed list fragments form one continuous edge pane",
            }
        )
    return repairs


def _bbox_union(boxes: list[dict[str, Any]]) -> dict[str, int]:
    edges = [_bbox_edges(box) for box in boxes]
    x1 = min(edge[0] for edge in edges)
    y1 = min(edge[1] for edge in edges)
    x2 = max(edge[2] for edge in edges)
    y2 = max(edge[3] for edge in edges)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _add_missing_repair(missing: list[dict[str, Any]], repair: dict[str, Any]) -> None:
    repair_signature = _missing_signature(repair)
    repair_roi = repair.get("rough_roi") if isinstance(repair.get("rough_roi"), dict) else {}
    for index, existing in enumerate(missing):
        if _missing_signature(existing) != repair_signature:
            continue
        existing_roi = existing.get("rough_roi") if isinstance(existing.get("rough_roi"), dict) else {}
        if not existing_roi or not repair_roi:
            return
        overlap = _bbox_overlap_area(existing_roi, repair_roi)
        existing_area = _bbox_area(existing_roi)
        repair_area = _bbox_area(repair_roi)
        smaller_area = min(existing_area, repair_area)
        if smaller_area > 0 and overlap / smaller_area >= 0.8:
            merged = deepcopy(repair if repair_area >= existing_area else existing)
            merged["rough_roi"] = _bbox_union([existing_roi, repair_roi])
            merged["reason"] = "; ".join(
                dict.fromkeys(
                    str(value).strip()
                    for value in (existing.get("reason"), repair.get("reason"))
                    if str(value or "").strip()
                )
            )
            missing[index] = merged
            return
    missing.append(deepcopy(repair))


def _bbox_area(box: dict[str, Any]) -> int:
    try:
        x1, y1, x2, y2 = _bbox_edges(box)
    except (TypeError, ValueError):
        return 0
    return max(0, x2 - x1) * max(0, y2 - y1)


def _bbox_overlap_area(left: dict[str, Any], right: dict[str, Any]) -> int:
    try:
        lx1, ly1, lx2, ly2 = _bbox_edges(left)
        rx1, ry1, rx2, ry2 = _bbox_edges(right)
    except (TypeError, ValueError):
        return 0
    return max(0, min(lx2, rx2) - max(lx1, rx1)) * max(0, min(ly2, ry2) - max(ly1, ry1))


def validate_review_patch(
    stage2: dict[str, Any],
    patch: dict[str, Any],
    *,
    require_complete_group_coverage: bool = False,
) -> dict[str, Any]:
    if not isinstance(stage2, dict) or not isinstance(patch, dict):
        raise ValueError("stage2 and review patch must be JSON objects")
    unexpected_fields = sorted(set(patch).difference(REVIEW_PATCH_FIELDS))
    if unexpected_fields:
        raise ValueError(f"unexpected review patch fields: {', '.join(unexpected_fields)}")
    root_ids, editable_ids = _region_ids(stage2)
    normalized = {
        "contract_version": REVIEW_PATCH_CONTRACT,
        "keep": _action_list(patch, "keep"),
        "remove": _action_list(patch, "remove"),
        "relabel": _action_list(patch, "relabel"),
        "missing": _action_list(patch, "missing"),
        "needs_human_review": _action_list(patch, "needs_human_review"),
        "protocol_adjustments": _action_list(patch, "protocol_adjustments"),
    }
    group_reviews = _action_list(patch, "group_reviews")
    for review in group_reviews:
        decision = str(review.get("decision") or "").strip()
        if decision not in {"keep", "remove", "relabel", "needs_human_review"}:
            raise ValueError(f"unsupported group review decision: {decision}")
        action = {
            "region_id": review.get("region_id"),
            "reason": review.get("reason"),
        }
        if review.get("review_source"):
            action["review_source"] = str(review.get("review_source"))
        if decision == "relabel":
            action["new_role"] = review.get("new_role")
        normalized[decision].append(action)
    seen_actions: dict[str, str] = {}
    for action_name in ("keep", "remove", "relabel"):
        for action in normalized[action_name]:
            region_id = str(action.get("region_id") or "").strip()
            if region_id not in editable_ids:
                raise ValueError(f"unknown region_id or immutable Stage1 root: {region_id}")
            previous = seen_actions.get(region_id)
            if previous and previous != action_name:
                raise ValueError(f"conflicting review actions for region_id: {region_id}")
            seen_actions[region_id] = action_name
            action["region_id"] = region_id
            action["reason"] = str(action.get("reason") or "").strip()
            if action_name == "relabel":
                new_role = str(action.get("new_role") or "").strip()
                if new_role not in ALLOWED_REVIEW_ROLES:
                    raise ValueError(f"unsupported role: {new_role}")
                action["new_role"] = new_role

    for item in normalized["missing"]:
        forbidden = sorted(FORBIDDEN_MODEL_GEOMETRY_KEYS.intersection(item))
        if forbidden:
            raise ValueError(f"model review cannot provide final geometry: {', '.join(forbidden)}")
        parent_id = str(item.get("parent_region_id") or "").strip()
        if parent_id not in root_ids:
            raise ValueError(f"missing target must reference an existing Stage1 parent: {parent_id}")
        role = str(item.get("expected_role") or "").strip()
        if role not in ALLOWED_REVIEW_ROLES:
            raise ValueError(f"unsupported role: {role}")
        repair_route = str(item.get("repair_route") or "precise_locator").strip()
        if repair_route not in ALLOWED_REPAIR_ROUTES:
            raise ValueError(f"unsupported repair_route: {repair_route}")
        rough_roi = _rough_roi(item.get("rough_roi"))
        item.update(
            {
                "description": str(item.get("description") or "").strip(),
                "parent_region_id": parent_id,
                "expected_role": role,
                "repair_route": repair_route,
                "rough_roi": rough_roi,
                "reason": str(item.get("reason") or "").strip(),
            }
        )

    for item in normalized["needs_human_review"]:
        region_id = str(item.get("region_id") or "").strip()
        if region_id and region_id not in editable_ids and region_id not in root_ids:
            raise ValueError(f"unknown region_id: {region_id}")
        if region_id in editable_ids:
            previous = seen_actions.get(region_id)
            if previous and previous != "needs_human_review":
                raise ValueError(f"conflicting review actions for region_id: {region_id}")
            seen_actions[region_id] = "needs_human_review"
        item["region_id"] = region_id
        item["reason"] = str(item.get("reason") or "").strip()

    group_ids = _group_ids(stage2)
    missing_group_ids = sorted(group_ids.difference(seen_actions))
    if require_complete_group_coverage and missing_group_ids:
        raise ValueError(
            "review coverage missing subregion_group IDs: " + ", ".join(missing_group_ids)
        )

    normalized.update(
        {
            "status": "valid",
            "expected_group_count": len(group_ids),
            "reviewed_group_count": len(group_ids.intersection(seen_actions)),
            "coverage_complete": not missing_group_ids,
            "source_group_review_count": len(group_reviews),
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "real_clicks": 0,
        }
    )
    return normalized


def apply_review_patch(stage2: dict[str, Any], validated_patch: dict[str, Any]) -> dict[str, Any]:
    if validated_patch.get("status") != "valid":
        raise ValueError("review patch must pass validation before application")
    reviewed = deepcopy(stage2)
    remove_ids = {str(item["region_id"]) for item in validated_patch.get("remove", [])}
    relabel_by_id = {str(item["region_id"]): item for item in validated_patch.get("relabel", [])}
    keep_by_id = {str(item["region_id"]): item for item in validated_patch.get("keep", [])}
    source_parent_by_group_id = {
        str(group.get("group_id") or ""): str(
            group.get("parent_group_id") or group.get("resolved_parent_group_id") or ""
        )
        for root in stage2.get("regions", [])
        if isinstance(root, dict)
        for group in root.get("subregion_groups", [])
        if isinstance(group, dict) and str(group.get("group_id") or "")
    }

    for root in reviewed.get("regions", []):
        if not isinstance(root, dict):
            continue
        root["numbered_items"] = _apply_to_collection(
            root.get("numbered_items"),
            id_key="item_id",
            remove_ids=remove_ids,
            relabel_by_id=relabel_by_id,
            keep_by_id=keep_by_id,
        )
        root["subregion_groups"] = _apply_to_collection(
            root.get("subregion_groups"),
            id_key="group_id",
            remove_ids=remove_ids,
            relabel_by_id=relabel_by_id,
            keep_by_id=keep_by_id,
        )
        _reparent_groups_after_review_removal(
            root["subregion_groups"],
            source_parent_by_group_id=source_parent_by_group_id,
            removed_group_ids=remove_ids,
        )

    reviewed["model_review_summary"] = {
        "contract_version": "learning_overlay_model_review_summary_v1",
        "removed": len(remove_ids),
        "relabeled": len(relabel_by_id),
        "kept": len(keep_by_id),
        "missing": len(validated_patch.get("missing", [])),
        "needs_human_review": len(validated_patch.get("needs_human_review", [])),
        "missing_repairs": deepcopy(validated_patch.get("missing", [])),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "real_clicks": 0,
    }
    return reviewed


def _reparent_groups_after_review_removal(
    groups: list[dict[str, Any]],
    *,
    source_parent_by_group_id: dict[str, str],
    removed_group_ids: set[str],
) -> None:
    surviving_ids = {
        str(group.get("group_id") or "")
        for group in groups
        if isinstance(group, dict) and str(group.get("group_id") or "")
    }
    for group in groups:
        if not isinstance(group, dict):
            continue
        parent_id = str(group.get("parent_group_id") or group.get("resolved_parent_group_id") or "")
        if not parent_id or parent_id in surviving_ids or parent_id not in removed_group_ids:
            continue
        removed_parent_id = parent_id
        visited: set[str] = set()
        while parent_id and parent_id in removed_group_ids and parent_id not in visited:
            visited.add(parent_id)
            parent_id = str(source_parent_by_group_id.get(parent_id) or "")
        new_parent_id = parent_id if parent_id in surviving_ids else ""
        if new_parent_id:
            group["parent_group_id"] = new_parent_id
            group["resolved_parent_group_id"] = new_parent_id
        else:
            group.pop("parent_group_id", None)
            group.pop("resolved_parent_group_id", None)
        group["model_review_reparenting"] = {
            "removed_parent_group_id": removed_parent_id,
            "new_parent_group_id": new_parent_id or None,
            "reason": "removed_review_wrapper_reparented_to_nearest_surviving_ancestor",
            "display_only": True,
        }


def build_missing_locator_tasks(
    stage2: dict[str, Any],
    validated_patch: dict[str, Any],
    screenshot_path: str,
) -> dict[str, Any]:
    if validated_patch.get("status") != "valid":
        raise ValueError("review patch must pass validation before repair handoff")
    root_ids, _editable_ids = _region_ids(stage2)
    precise_regions: list[dict[str, Any]] = []
    stage1_repairs: list[dict[str, Any]] = []
    for index, missing in enumerate(validated_patch.get("missing", []), start=1):
        parent_id = str(missing.get("parent_region_id") or "")
        if parent_id not in root_ids:
            raise ValueError(f"missing target references unknown Stage1 parent: {parent_id}")
        route = str(missing.get("repair_route") or "precise_locator")
        base = {
            "repair_request_id": f"model_review_missing_{index}",
            "description": str(missing.get("description") or ""),
            "expected_role": str(missing.get("expected_role") or "review_only"),
            "parent_region_id": parent_id,
            "rough_roi": deepcopy(missing.get("rough_roi") or {}),
            "reason": str(missing.get("reason") or ""),
            "repair_route": route,
            "candidate_id": str(missing.get("candidate_id") or ""),
            "candidate_member_item_ids": sorted(
                {
                    str(item_id).strip()
                    for item_id in missing.get("candidate_member_item_ids", [])
                    if str(item_id).strip()
                }
            ),
            "candidate_geometry_source": str(missing.get("geometry_source") or ""),
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        if route == "stage1_repartition":
            stage1_repairs.append(base)
            continue
        precise_regions.append(
            {
                **base,
                "region_no": index,
                "label": base["description"],
                "prompt": f"Locate missing {base['expected_role']}: {base['description']}",
                "bbox": deepcopy(base["rough_roi"]),
                "bbox_quality": "rough_roi_only_requires_precise_grounding",
                "requires_precise_grounding": True,
                "semantic_action": "inspect_region",
            }
        )
    return {
        "contract_version": "learning_overlay_missing_repair_handoff_v1",
        "screenshot_path": str(screenshot_path),
        "regions": precise_regions,
        "stage1_repair_requests": stage1_repairs,
        "precise_locator_count": len(precise_regions),
        "stage1_repartition_count": len(stage1_repairs),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "real_clicks": 0,
    }


def score_review_against_adjudication(
    before_stage2: dict[str, Any],
    after_stage2: dict[str, Any],
    adjudication: dict[str, Any],
) -> dict[str, Any]:
    expectations = adjudication.get("region_expectations")
    if not isinstance(expectations, dict):
        expectations = {}
    before_roles = _role_by_id(before_stage2)
    after_roles = _role_by_id(after_stage2)
    before_passed = sum(_role_matches(before_roles, str(region_id), str(role)) for region_id, role in expectations.items())
    after_passed = sum(_role_matches(after_roles, str(region_id), str(role)) for region_id, role in expectations.items())
    attempted = len(expectations)
    before_metric = _metric(before_passed, attempted)
    after_metric = _metric(after_passed, attempted)

    expected_missing = {
        _missing_signature(item)
        for item in adjudication.get("missing_expectations", [])
        if isinstance(item, dict)
    }
    actual_missing = {
        _missing_signature(item)
        for item in (after_stage2.get("model_review_summary") or {}).get("missing_repairs", [])
        if isinstance(item, dict)
    }
    missing_attempted = len(expected_missing)
    return {
        "contract_version": "learning_overlay_model_review_adjudication_v1",
        "adjudicated_region_alignment": {
            "before": before_metric,
            "after": after_metric,
            "delta": _rate_delta(before_metric, after_metric),
        },
        "missing_target_recall": {
            "before": _metric(0, missing_attempted),
            "after": _metric(len(expected_missing.intersection(actual_missing)), missing_attempted),
        },
        "interpretation": (
            "Human-adjudicated alignment for explicitly labeled regions in this fixture only; "
            "this is not general recognition accuracy, model accuracy, or end-to-end success."
        ),
    }


def render_review_overlays(
    *,
    screenshot_path: str | Path,
    before_stage2: dict[str, Any],
    after_stage2: dict[str, Any],
    validated_patch: dict[str, Any],
    out_dir: str | Path,
) -> dict[str, Any]:
    source = Path(screenshot_path)
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as raw:
        reviewed_canvas = raw.convert("RGB")
        diff_canvas = raw.convert("RGB")
    font = ImageFont.load_default()
    reviewed_draw = ImageDraw.Draw(reviewed_canvas)
    diff_draw = ImageDraw.Draw(diff_canvas)
    relabeled = {str(item.get("region_id") or "") for item in validated_patch.get("relabel", [])}

    rendered_semantic_region_ids: list[str] = []
    rendered_control_parent_ids: list[str] = []
    suppressed_grouped_atomic_item_count = 0
    suppressed_explicit_atomic_item_count = 0
    suppressed_control_parent_member_ids: list[str] = []
    rendered_grouped_atomic_item_count = 0
    unlabeled_atomic_item_count = 0
    suppressed_explicit_group_count = 0
    for root in after_stage2.get("regions", []):
        if not isinstance(root, dict) or not isinstance(root.get("bbox"), dict):
            continue
        root_id = str(root.get("region_id") or "")
        root_label = str(root.get("label") or "root")
        _draw_labeled_box(reviewed_draw, root["bbox"], f"{root_id} {root_label}", color=(18, 83, 150), font=font)

        groups = []
        for item in root.get("subregion_groups", []):
            if not isinstance(item, dict):
                continue
            if item.get("render_in_main_overlay") is False:
                suppressed_explicit_group_count += 1
                continue
            groups.append(item)
        control_parents = [
            item
            for item in root.get("control_parents", [])
            if isinstance(item, dict)
            and isinstance(item.get("bbox"), dict)
            and item.get("render_in_main_overlay") is not False
        ]
        control_parent_member_ids = {
            str(item_id)
            for control_parent in control_parents
            for item_id in control_parent.get("member_object_ids", [])
            if str(item_id).strip()
        }
        grouped_item_ids = {
            str(item_id)
            for group in groups
            for item_id in group.get("member_item_ids", [])
            if str(item_id)
        }
        for control_parent in control_parents:
            control_parent_id = str(control_parent.get("object_id") or "")
            label = str(control_parent.get("label") or control_parent_id or "control")
            _draw_labeled_box(
                reviewed_draw,
                control_parent["bbox"],
                f"CP {label}",
                color=(0, 158, 115),
                font=font,
            )
            if control_parent_id:
                rendered_control_parent_ids.append(control_parent_id)
        for item in root.get("numbered_items", []):
            if not isinstance(item, dict) or not isinstance(item.get("bbox"), dict):
                continue
            if item.get("render_in_main_overlay") is False:
                suppressed_explicit_atomic_item_count += 1
                continue
            item_id = str(item.get("item_id") or "")
            if item_id in control_parent_member_ids:
                suppressed_grouped_atomic_item_count += 1
                suppressed_control_parent_member_ids.append(item_id)
                continue
            grouped = item_id in grouped_item_ids
            role = str(item.get("role") or "review_only")
            color = (36, 170, 82) if item_id in relabeled else ((238, 129, 25) if grouped else (25, 118, 210))
            x1, y1, x2, y2 = _bbox_edges(item["bbox"])
            reviewed_draw.rectangle((x1, y1, x2, y2), outline=color, width=2)
            if grouped:
                rendered_grouped_atomic_item_count += 1
            unlabeled_atomic_item_count += 1
            rendered_semantic_region_ids.append(item_id)

        for group in groups:
            if not isinstance(group.get("bbox"), dict):
                continue
            group_id = str(group.get("group_id") or "")
            role = str(group.get("role") or "review_only")
            color = (36, 170, 82) if group_id in relabeled else (25, 118, 210)
            _draw_labeled_box(reviewed_draw, group["bbox"], f"{group_id} {role}", color=color, font=font)
            rendered_semantic_region_ids.append(group_id)

    for region_id, role, bbox in _iter_editable_regions(after_stage2):
        color = (36, 170, 82) if region_id in relabeled else (25, 118, 210)
        if region_id in relabeled:
            _draw_labeled_box(diff_draw, bbox, f"RELABEL {region_id} -> {role}", color=color, font=font)

    before_boxes = {region_id: (role, bbox) for region_id, role, bbox in _iter_editable_regions(before_stage2)}
    for removal in validated_patch.get("remove", []):
        region_id = str(removal.get("region_id") or "")
        role_bbox = before_boxes.get(region_id)
        if role_bbox is None:
            continue
        _role, bbox = role_bbox
        _draw_labeled_box(diff_draw, bbox, f"REMOVE {region_id}", color=(214, 45, 45), font=font)
        x1, y1, x2, y2 = _bbox_edges(bbox)
        diff_draw.line((x1, y1, x2, y2), fill=(214, 45, 45), width=3)
        diff_draw.line((x1, y2, x2, y1), fill=(214, 45, 45), width=3)

    for missing in validated_patch.get("missing", []):
        bbox = missing.get("rough_roi")
        if not isinstance(bbox, dict):
            continue
        label = f"MISSING {missing.get('expected_role')} -> {missing.get('repair_route')}"
        _draw_dashed_box(reviewed_draw, bbox, label, color=(184, 74, 201), font=font)
        _draw_dashed_box(diff_draw, bbox, label, color=(184, 74, 201), font=font)

    reviewed_path = output / "reviewed_overlay.png"
    diff_path = output / "review_diff_overlay.png"
    reviewed_canvas.save(reviewed_path)
    diff_canvas.save(diff_path)
    return {
        "reviewed_overlay_path": str(reviewed_path.resolve()),
        "diff_overlay_path": str(diff_path.resolve()),
        "rendered_semantic_region_ids": rendered_semantic_region_ids,
        "rendered_control_parent_count": len(rendered_control_parent_ids),
        "rendered_control_parent_ids": rendered_control_parent_ids,
        "suppressed_grouped_atomic_item_count": suppressed_grouped_atomic_item_count,
        "suppressed_explicit_atomic_item_count": suppressed_explicit_atomic_item_count,
        "suppressed_explicit_group_count": suppressed_explicit_group_count,
        "suppressed_control_parent_member_count": len(suppressed_control_parent_member_ids),
        "suppressed_control_parent_member_ids": suppressed_control_parent_member_ids,
        "rendered_grouped_atomic_item_count": rendered_grouped_atomic_item_count,
        "unlabeled_atomic_item_count": unlabeled_atomic_item_count,
    }


def render_model_review_input_overlay(
    screenshot_path: str | Path,
    stage2: dict[str, Any],
    out_path: str | Path,
    *,
    include_stage1_roots: bool = True,
    missing_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source = Path(screenshot_path)
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as raw:
        canvas = raw.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    font = _overlay_font(16)
    small_font = _overlay_font(13)
    root_box_count = 0
    if include_stage1_roots:
        for index, root in enumerate(stage2.get("regions", []), start=1):
            if not isinstance(root, dict) or not isinstance(root.get("bbox"), dict):
                continue
            _draw_labeled_box(
                draw,
                root["bbox"],
                f"S{index} {str(root.get('label') or '')[:28]}",
                color=(20, 104, 190),
                font=font,
            )
            root_box_count += 1
    review_id_map: dict[str, str] = {}
    for record in _group_review_records(stage2):
        review_id = str(record["review_id"])
        region_id = str(record["group_id"])
        review_id_map[review_id] = region_id
        _draw_labeled_box(
            draw,
            record["bbox"],
            f"{review_id} {record['role']}",
            color=(234, 116, 0),
            font=small_font,
        )
    candidate_count = 0
    for candidate in missing_candidates or []:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("rough_roi"), dict):
            continue
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id:
            continue
        _draw_labeled_box(
            draw,
            candidate["rough_roi"],
            f"{candidate_id} uncovered candidate",
            color=(190, 32, 180),
            font=small_font,
        )
        candidate_count += 1
    canvas.save(output)
    return {
        "contract_version": "learning_overlay_model_review_input_v1",
        "overlay_path": str(output.resolve()),
        "review_id_map": review_id_map,
        "group_count": len(review_id_map),
        "stage1_root_boxes_rendered": root_box_count,
        "missing_candidate_boxes_rendered": candidate_count,
        "atomic_item_boxes_rendered": 0,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def render_focused_group_review_overlay(
    screenshot_path: str | Path,
    record: dict[str, Any],
    out_path: str | Path,
) -> dict[str, Any]:
    source = Path(screenshot_path)
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    bbox = record.get("bbox")
    if not isinstance(bbox, dict):
        raise ValueError("focused review record requires bbox")
    with Image.open(source) as raw:
        screenshot = raw.convert("RGB")
    x1, y1, x2, y2 = _bbox_edges(bbox)
    x1 = max(0, min(screenshot.width - 1, x1))
    y1 = max(0, min(screenshot.height - 1, y1))
    x2 = max(x1 + 1, min(screenshot.width, x2))
    y2 = max(y1 + 1, min(screenshot.height, y2))

    context = screenshot.convert("RGBA")
    shade = Image.new("RGBA", context.size, (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    dim = (0, 0, 0, 145)
    shade_draw.rectangle((0, 0, screenshot.width, y1), fill=dim)
    shade_draw.rectangle((0, y2, screenshot.width, screenshot.height), fill=dim)
    shade_draw.rectangle((0, y1, x1, y2), fill=dim)
    shade_draw.rectangle((x2, y1, screenshot.width, y2), fill=dim)
    context = Image.alpha_composite(context, shade).convert("RGB")
    context_draw = ImageDraw.Draw(context)
    font = _overlay_font(18)
    _draw_labeled_box(
        context_draw,
        {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
        f"TARGET {record.get('review_id')} {record.get('role')}",
        color=(225, 35, 35),
        font=font,
    )

    panel_width = max(480, min(900, screenshot.width))
    canvas = Image.new("RGB", (screenshot.width + panel_width, screenshot.height), "white")
    canvas.paste(context, (0, 0))
    panel_draw = ImageDraw.Draw(canvas)
    panel_draw.text(
        (screenshot.width + 20, 18),
        f"MAGNIFIED TARGET: {record.get('review_id')}\n{record.get('region_id')}",
        fill=(20, 20, 20),
        font=font,
    )
    crop = screenshot.crop((x1, y1, x2, y2))
    max_w = panel_width - 40
    max_h = max(1, screenshot.height - 90)
    scale = min(max_w / crop.width, max_h / crop.height)
    scaled = crop.resize(
        (max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
        Image.Resampling.LANCZOS,
    )
    crop_x = screenshot.width + (panel_width - scaled.width) // 2
    crop_y = 75 + max(0, (max_h - scaled.height) // 2)
    canvas.paste(scaled, (crop_x, crop_y))
    panel_draw.rectangle(
        (crop_x, crop_y, crop_x + scaled.width - 1, crop_y + scaled.height - 1),
        outline=(225, 35, 35),
        width=4,
    )
    canvas.save(output)
    return {
        "contract_version": "learning_overlay_focused_group_review_input_v1",
        "overlay_path": str(output.resolve()),
        "target_region_id": str(record.get("region_id") or ""),
        "review_id": str(record.get("review_id") or ""),
        "crop_bbox": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _action_list(patch: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = patch.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"review patch field {key} must be a list of objects")
    return deepcopy(value)


def _compact_review_evidence(stage2: dict[str, Any]) -> dict[str, Any]:
    records_by_group = {record["group_id"]: record for record in _group_review_records(stage2)}
    roots: list[dict[str, Any]] = []
    for root in stage2.get("regions", []):
        if not isinstance(root, dict):
            continue
        items = [item for item in root.get("numbered_items", []) if isinstance(item, dict)]
        items_by_id = {
            str(item.get("item_id") or ""): item
            for item in items
            if str(item.get("item_id") or "")
        }
        role_counts: dict[str, int] = {}
        for item in items:
            role = str(item.get("role") or "review_only")
            role_counts[role] = role_counts.get(role, 0) + 1
        roots.append(
            {
                "region_id": root.get("region_id"),
                "label": _short_text(root.get("label")),
                "bbox": root.get("bbox"),
                "numbered_item_count": len(items),
                "numbered_item_role_counts": role_counts,
                "subregion_groups": [
                    {
                        "review_id": records_by_group.get(str(group.get("group_id") or ""), {}).get("review_id"),
                        "source_role_hypothesis": group.get("role"),
                        "source_label_hypothesis": _short_text(group.get("label")),
                        "bbox": group.get("bbox"),
                        "member_count": len(group.get("member_item_ids") or group.get("child_item_ids") or []),
                        "member_evidence": _compact_member_evidence(group, items_by_id),
                    }
                    for group in root.get("subregion_groups", [])
                    if isinstance(group, dict)
                ],
            }
        )
    return {
        "contract_version": "learning_overlay_model_review_evidence_v1",
        "roots": roots,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _compact_member_evidence(
    group: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    member_ids = [
        str(item_id)
        for item_id in (group.get("member_item_ids") or group.get("child_item_ids") or [])
        if str(item_id)
    ]
    # 首尾采样既限制提示词体积，也保留长区域中可能改变语义的内容。
    sampled_ids = member_ids[:4]
    for item_id in member_ids[-2:]:
        if item_id not in sampled_ids:
            sampled_ids.append(item_id)
    evidence: list[dict[str, Any]] = []
    for item_id in sampled_ids:
        item = items_by_id.get(item_id)
        if not isinstance(item, dict):
            continue
        evidence.append(
            {
                "item_id": item_id,
                "source_role_hypothesis": item.get("role"),
                "label": _short_text(
                    item.get("label")
                    or item.get("text")
                    or item.get("name")
                    or item.get("semantic_text")
                ),
                "bbox": item.get("bbox"),
            }
        )
    return evidence


def _group_review_records(stage2: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for root in stage2.get("regions", []):
        if not isinstance(root, dict):
            continue
        items_by_id = {
            str(item.get("item_id") or ""): item
            for item in root.get("numbered_items", [])
            if isinstance(item, dict) and str(item.get("item_id") or "")
        }
        for group in root.get("subregion_groups", []):
            if not isinstance(group, dict) or not isinstance(group.get("bbox"), dict):
                continue
            group_id = str(group.get("group_id") or "").strip()
            if not group_id:
                continue
            records.append(
                {
                    "review_id": f"G{len(records) + 1:02d}",
                    "group_id": group_id,
                    "region_id": group_id,
                    "role": str(group.get("role") or "review_only"),
                    "bbox": group["bbox"],
                    "member_count": len(group.get("member_item_ids") or group.get("child_item_ids") or []),
                    "member_evidence": _compact_member_evidence(group, items_by_id),
                    "parent_region_id": str(root.get("region_id") or ""),
                    "parent_label": str(root.get("label") or ""),
                    "parent_bbox": deepcopy(root.get("bbox") or {}),
                }
            )
    return records


def _overlay_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _short_text(value: Any, limit: int = 48) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit] + "..."


def _region_ids(stage2: dict[str, Any]) -> tuple[set[str], set[str]]:
    root_ids: set[str] = set()
    editable_ids: set[str] = set()
    for root in stage2.get("regions", []):
        if not isinstance(root, dict):
            continue
        root_id = str(root.get("region_id") or "").strip()
        if root_id:
            root_ids.add(root_id)
        for item in root.get("numbered_items", []):
            if isinstance(item, dict) and str(item.get("item_id") or "").strip():
                editable_ids.add(str(item["item_id"]).strip())
        for group in root.get("subregion_groups", []):
            if isinstance(group, dict) and str(group.get("group_id") or "").strip():
                editable_ids.add(str(group["group_id"]).strip())
    return root_ids, editable_ids


def _group_ids(stage2: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for root in stage2.get("regions", []):
        if not isinstance(root, dict):
            continue
        for group in root.get("subregion_groups", []):
            if isinstance(group, dict) and str(group.get("group_id") or "").strip():
                result.add(str(group["group_id"]).strip())
    return result


def _rough_roi(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("missing target requires rough_roi")
    try:
        roi = {key: int(value[key]) for key in ("x", "y", "w", "h")}
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("rough_roi must contain integer x/y/w/h") from exc
    if roi["w"] <= 0 or roi["h"] <= 0 or roi["x"] < 0 or roi["y"] < 0:
        raise ValueError("rough_roi must be positive and non-negative")
    return roi


def _apply_to_collection(
    value: Any,
    *,
    id_key: str,
    remove_ids: set[str],
    relabel_by_id: dict[str, dict[str, Any]],
    keep_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        item = deepcopy(raw)
        region_id = str(item.get(id_key) or "")
        if region_id in remove_ids:
            continue
        if region_id in relabel_by_id:
            action = relabel_by_id[region_id]
            item["role"] = action["new_role"]
            item["model_review_decision"] = {
                "action": "relabel",
                "reason": action.get("reason") or "",
                "review_source": action.get("review_source") or "model_review",
                "display_only": True,
            }
        elif region_id in keep_by_id:
            action = keep_by_id[region_id]
            item["model_review_decision"] = {
                "action": "keep",
                "reason": action.get("reason") or "",
                "review_source": action.get("review_source") or "model_review",
                "display_only": True,
            }
        output.append(item)
    return output


def _role_by_id(stage2: dict[str, Any]) -> dict[str, str]:
    return {region_id: role for region_id, role, _bbox_value in _iter_editable_regions(stage2)}


def _role_matches(roles: dict[str, str], region_id: str, expected_role: str) -> int:
    if expected_role == "__remove__":
        return int(region_id not in roles)
    return int(roles.get(region_id) == expected_role)


def _metric(passed: int, attempted: int) -> dict[str, Any]:
    if attempted <= 0:
        return {"passed": int(passed), "attempted": 0, "rate": "not_covered"}
    return {"passed": int(passed), "attempted": int(attempted), "rate": round(passed / attempted, 4)}


def _rate_delta(before: dict[str, Any], after: dict[str, Any]) -> float | str:
    if not isinstance(before.get("rate"), (int, float)) or not isinstance(after.get("rate"), (int, float)):
        return "not_covered"
    return round(float(after["rate"]) - float(before["rate"]), 4)


def _missing_signature(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("parent_region_id") or ""),
        str(item.get("expected_role") or ""),
        str(item.get("repair_route") or "precise_locator"),
    )


def _iter_editable_regions(stage2: dict[str, Any]):
    for root in stage2.get("regions", []):
        if not isinstance(root, dict):
            continue
        for item in root.get("numbered_items", []):
            if isinstance(item, dict) and isinstance(item.get("bbox"), dict):
                yield str(item.get("item_id") or ""), str(item.get("role") or "review_only"), item["bbox"]
        for group in root.get("subregion_groups", []):
            if isinstance(group, dict) and isinstance(group.get("bbox"), dict):
                yield str(group.get("group_id") or ""), str(group.get("role") or "review_only"), group["bbox"]


def _draw_labeled_box(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, Any],
    label: str,
    *,
    color: tuple[int, int, int],
    font: ImageFont.ImageFont,
) -> None:
    x1, y1, x2, y2 = _bbox_edges(bbox)
    draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
    draw.text((x1 + 2, y1 + 2), label, fill=color, font=font)


def _draw_dashed_box(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, Any],
    label: str,
    *,
    color: tuple[int, int, int],
    font: ImageFont.ImageFont,
) -> None:
    x1, y1, x2, y2 = _bbox_edges(bbox)
    dash = 10
    for x in range(x1, x2, dash * 2):
        draw.line((x, y1, min(x + dash, x2), y1), fill=color, width=3)
        draw.line((x, y2, min(x + dash, x2), y2), fill=color, width=3)
    for y in range(y1, y2, dash * 2):
        draw.line((x1, y, x1, min(y + dash, y2)), fill=color, width=3)
        draw.line((x2, y, x2, min(y + dash, y2)), fill=color, width=3)
    draw.text((x1 + 2, y1 + 2), label, fill=color, font=font)


def _bbox_edges(bbox: dict[str, Any]) -> tuple[int, int, int, int]:
    x1 = int(bbox.get("x") or 0)
    y1 = int(bbox.get("y") or 0)
    x2 = x1 + max(1, int(bbox.get("w") or bbox.get("width") or 1))
    y2 = y1 + max(1, int(bbox.get("h") or bbox.get("height") or 1))
    return x1, y1, x2, y2
