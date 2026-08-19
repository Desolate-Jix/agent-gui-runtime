from __future__ import annotations

from copy import deepcopy
from typing import Any


def apply_grounding_eligibility_gate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给学习候选打 ROI grounding 资格；不授权点击。"""

    gated: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entry = deepcopy(item)
        decision = evaluate_grounding_eligibility(entry)
        entry["review_only"] = bool(decision["review_only"])
        entry["grounding_eligible"] = bool(decision["grounding_eligible"])
        entry["grounding_block_reason"] = str(decision["grounding_block_reason"])
        entry["evidence_strength"] = str(decision["evidence_strength"])
        entry["eligible_for"] = list(decision["eligible_for"])
        entry["artifact_is_authorization"] = False
        entry["execute_binding_enabled"] = False
        entry["real_action_requires_gate"] = True
        entry["surface_zone"] = _surface_zone(entry)
        entry["roi_diagnostic"] = {"split_roi_required": False, "split_roi_reason": ""}
        gated.append(entry)
    _annotate_split_roi_diagnostics(gated)
    return gated


def evaluate_grounding_eligibility(item: dict[str, Any]) -> dict[str, Any]:
    label = str(item.get("label") or item.get("text") or "")
    item_type = str(item.get("item_type") or "").casefold()
    role = str(item.get("role") or "").casefold()
    evidence_level = str(item.get("evidence_level") or "").casefold()
    sources = _sources(item)
    interactable = item.get("interactable_evidence") if isinstance(item.get("interactable_evidence"), dict) else {}
    open_detail_card = _looks_like_open_detail_card(item, interactable=interactable)

    parser_candidate = (
        item.get("parser_candidate")
        if isinstance(item.get("parser_candidate"), dict)
        else None
    )
    parser_candidate_block = (
        parser_candidate_freshness_block(parser_candidate)
        if parser_candidate
        and str(parser_candidate.get("schema_version") or "")
        == "parser_candidate_v1"
        else ""
    )
    if parser_candidate_block:
        return _blocked(
            parser_candidate_block,
            evidence_strength=_evidence_strength(sources, interactable),
        )
    if _surface_zone(item) == "browser_chrome":
        return _blocked("browser_chrome_not_page_surface", evidence_strength=_evidence_strength(sources, interactable))
    if _looks_like_danger_action(label) or item_type == "danger_zone":
        return _blocked("danger_zone", evidence_strength="danger_zone")
    if evidence_level == "ocr_text_only" and item_type != "form_field":
        return _blocked(
            "ocr_text_only_without_interactable_evidence",
            evidence_strength="ocr_text_anchor_only",
        )
    if evidence_level == "semantic_region_only" and not _has_interactable_evidence(interactable):
        return _blocked(
            "semantic_region_only_without_interactable_evidence",
            evidence_strength="semantic_only",
        )
    if role in {"text", "section", "group"} and not _has_direct_interactable_evidence(interactable):
        return _blocked(
            "non_actionable_role_without_direct_interactable_evidence",
            evidence_strength=_evidence_strength(sources, interactable),
        )
    if item_type in {"readable", "layout"} and not open_detail_card:
        strength = "semantic_only" if "vision" in sources else "ocr_text_anchor_only" if "ocr" in sources else "unknown_or_stale"
        return _blocked("non_actionable_item_type", evidence_strength=strength)
    if item_type not in {"actionable", "form_field"} and not open_detail_card:
        return _blocked("not_actionable_type", evidence_strength=_evidence_strength(sources, interactable))
    if not _has_interactable_evidence(interactable) and not _has_multi_source_interactable_surrogate(sources):
        return _blocked(
            "actionable_without_sufficient_grounding_evidence",
            evidence_strength=_evidence_strength(sources, interactable),
        )
    return {
        "grounding_eligible": True,
        "review_only": False,
        "grounding_block_reason": "",
        "evidence_strength": _evidence_strength(sources, interactable),
        "eligible_for": ["roi_grounding"],
    }


def summarize_grounding_eligibility(items: list[dict[str, Any]]) -> dict[str, Any]:
    valid_items = [item for item in items if isinstance(item, dict)]
    attempted = len(valid_items)
    eligible_items = [item for item in valid_items if item.get("grounding_eligible") is True]
    blocked_items = [item for item in valid_items if item.get("grounding_eligible") is not True]
    semantic_only = [item for item in valid_items if item.get("evidence_strength") == "semantic_only"]
    ocr_only = [item for item in valid_items if item.get("evidence_strength") == "ocr_text_anchor_only"]
    leaks = [item for item in eligible_items if _is_non_actionable(item)]
    split_roi_items = [item for item in valid_items if (item.get("roi_diagnostic") or {}).get("split_roi_required") is True]
    browser_chrome_items = [item for item in valid_items if item.get("surface_zone") == "browser_chrome"]
    return {
        "contract_version": "learn_grounding_eligibility_gate_report_v1",
        "evaluation_scope": "learn_mode_grounding_eligibility_gate",
        "execution_scope": "no_action_no_execute_no_live_click",
        "not_accuracy": True,
        "not_e2e_success": True,
        "not_execute_mode_default": True,
        "grounding_eligibility": {
            "attempted": attempted,
            "eligible": len(eligible_items),
            "blocked": len(blocked_items),
        },
        "semantic_only_rejection": _rejection_metric(semantic_only),
        "ocr_only_rejection": _rejection_metric(ocr_only),
        "non_actionable_leaked_to_grounding": {
            "passed": 1 if not leaks else 0,
            "attempted": 1,
            "rate": 1.0 if not leaks else 0.0,
            "leaked_count": len(leaks),
            "leaked_item_ids": [str(item.get("item_id") or "") for item in leaks],
            "interpretation": "non-actionable items must not enter ROI grounding",
        },
        "browser_chrome_rejection": _rejection_metric(browser_chrome_items),
        "split_roi_required": {
            "attempted": len(split_roi_items),
            "count": len(split_roi_items),
            "item_ids": [str(item.get("item_id") or "") for item in split_roi_items],
            "interpretation": "split ROI is a diagnostic for ambiguous overlapping targets; it is not click authorization",
        },
        "grounding_eligible_breakdown": _eligible_breakdown(eligible_items),
        "interpretation": (
            "grounding_eligible only means the item may enter ROI grounding; it is not click permission, "
            "Execute authorization, PathGraph promotion, or a recognition accuracy metric"
        ),
    }


def parser_candidate_freshness_block(candidate: dict[str, Any]) -> str:
    """Return the fail-closed reason for a parser candidate, if any."""

    freshness = (
        candidate.get("freshness")
        if isinstance(candidate.get("freshness"), dict)
        else {}
    )
    if bool(freshness.get("stale")):
        return "parser_candidate_stale"
    if not (
        str(candidate.get("screenshot_sha256") or "").strip()
        and str(candidate.get("capture_id") or "").strip()
        and str(candidate.get("source_run_id") or "").strip()
    ):
        return "parser_candidate_missing_current_screenshot_identity"
    if not bool(freshness.get("same_screenshot")):
        return "parser_candidate_screenshot_mismatch"
    image_size = (
        candidate.get("image_size")
        if isinstance(candidate.get("image_size"), dict)
        else {}
    )
    if _positive_int(image_size.get("width")) <= 0 or _positive_int(image_size.get("height")) <= 0:
        return "parser_candidate_invalid_image_size"
    is_omniparser = str(candidate.get("source_type") or "").casefold() == "omniparser"
    if is_omniparser and str(candidate.get("coordinate_space") or "") not in {
        "image_normalized_xyxy",
        "image_pixel_xyxy",
    }:
        return "parser_candidate_invalid_coordinate_space"
    bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else {}
    if not _valid_bbox(bbox, image_size=image_size):
        return "parser_candidate_invalid_bbox"
    if not is_omniparser:
        return ""
    if str(candidate.get("provider_status") or "").casefold() != "success":
        return "parser_provider_not_success"
    if str(candidate.get("provider_contract_version") or "") != "screen_parser_result_v1":
        return "parser_candidate_legacy_provider_contract"
    if str(candidate.get("provider") or "").casefold() != "omniparser":
        return "parser_candidate_invalid_provider"
    if not (
        str(candidate.get("model_revision") or "").strip()
        and str(candidate.get("profile_id") or "").strip()
    ):
        return "parser_candidate_missing_provider_or_model_revision"
    current_image_size = (
        candidate.get("current_image_size")
        if isinstance(candidate.get("current_image_size"), dict)
        else {}
    )
    if (
        _positive_int(current_image_size.get("width")) <= 0
        or _positive_int(current_image_size.get("height")) <= 0
    ):
        return "parser_candidate_invalid_current_image_size"
    if (
        _positive_int(image_size.get("width"))
        != _positive_int(current_image_size.get("width"))
        or _positive_int(image_size.get("height"))
        != _positive_int(current_image_size.get("height"))
    ):
        return "parser_candidate_image_size_mismatch"
    return ""

def _positive_int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _valid_bbox(bbox: dict[str, Any], *, image_size: dict[str, Any]) -> bool:
    width = _positive_int(image_size.get("width"))
    height = _positive_int(image_size.get("height"))
    x = _positive_int(bbox.get("x"))
    y = _positive_int(bbox.get("y"))
    box_width = _positive_int(bbox.get("w", bbox.get("width")))
    box_height = _positive_int(bbox.get("h", bbox.get("height")))
    return (
        box_width > 0
        and box_height > 0
        and x >= 0
        and y >= 0
        and x + box_width <= width
        and y + box_height <= height
    )


def _blocked(reason: str, *, evidence_strength: str) -> dict[str, Any]:
    return {
        "grounding_eligible": False,
        "review_only": True,
        "grounding_block_reason": reason,
        "evidence_strength": evidence_strength,
        "eligible_for": [],
    }


def _sources(item: dict[str, Any]) -> set[str]:
    return {
        str(value).casefold()
        for value in item.get("source_evidence", [])
        if str(value or "").strip()
    } if isinstance(item.get("source_evidence"), list) else set()


def _surface_zone(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    explicit = str(item.get("surface_zone") or metadata.get("surface_zone") or metadata.get("surface") or "").casefold()
    if explicit in {"browser_chrome", "web_page", "modal", "toolbar", "content_area", "unknown"}:
        return explicit
    role = str(item.get("role") or "").casefold()
    label = str(item.get("label") or item.get("text") or "").casefold()
    if role in {"address_bar", "browser_tab", "browser_toolbar", "extension_button"}:
        return "browser_chrome"
    if "address and search bar" in label or "browser address" in label:
        return "browser_chrome"
    return "unknown"


def _annotate_split_roi_diagnostics(items: list[dict[str, Any]]) -> None:
    eligible = [item for item in items if item.get("grounding_eligible") is True]
    for index, left in enumerate(eligible):
        for right in eligible[index + 1 :]:
            if _label_key(left) == _label_key(right):
                continue
            if _overlap_ratio(left.get("bbox"), right.get("bbox")) < 0.45:
                continue
            for item in (left, right):
                item["roi_diagnostic"] = {
                    "split_roi_required": True,
                    "split_roi_reason": "overlapping_distinct_grounding_targets",
                    "other_item_id": str((right if item is left else left).get("item_id") or ""),
                }


def _label_key(item: dict[str, Any]) -> str:
    return " ".join(str(item.get("label") or item.get("text") or "").casefold().split())


def _overlap_ratio(left: Any, right: Any) -> float:
    intersection = _intersection_area(left, right)
    smaller = min(_bbox_area(left), _bbox_area(right))
    return 0.0 if smaller <= 0 else intersection / smaller


def _intersection_area(left: Any, right: Any) -> float:
    lb = left if isinstance(left, dict) else {}
    rb = right if isinstance(right, dict) else {}
    lx1 = _float(lb.get("x"))
    ly1 = _float(lb.get("y"))
    lx2 = lx1 + max(0.0, _float(lb.get("w", lb.get("width"))))
    ly2 = ly1 + max(0.0, _float(lb.get("h", lb.get("height"))))
    rx1 = _float(rb.get("x"))
    ry1 = _float(rb.get("y"))
    rx2 = rx1 + max(0.0, _float(rb.get("w", rb.get("width"))))
    ry2 = ry1 + max(0.0, _float(rb.get("h", rb.get("height"))))
    return max(0.0, min(lx2, rx2) - max(lx1, rx1)) * max(0.0, min(ly2, ry2) - max(ly1, ry1))


def _bbox_area(value: Any) -> float:
    bbox = value if isinstance(value, dict) else {}
    return max(0.0, _float(bbox.get("w", bbox.get("width")))) * max(0.0, _float(bbox.get("h", bbox.get("height"))))


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _evidence_strength(sources: set[str], interactable: dict[str, Any]) -> str:
    if bool(interactable.get("calibrated_target_validated")):
        return "human_calibrated_interactable"
    if bool(interactable.get("execute_candidate_ranked")):
        return "no_dispatch_execute_candidate"
    if _has_interactable_evidence(interactable):
        source_count = len(sources)
        if source_count >= 2 or bool(interactable.get("cross_evidence_overlap")):
            return "multi_source_interactable"
        return "single_interactable_source"
    if sources == {"vision"}:
        return "semantic_only"
    if sources == {"ocr"}:
        return "ocr_text_anchor_only"
    return "unknown_or_stale"


def _has_interactable_evidence(interactable: dict[str, Any]) -> bool:
    return any(
        bool(interactable.get(key))
        for key in (
            "uia_invokable",
            "uia_value_pattern",
            "uia_editable",
            "dom_clickable",
            "dom_editable",
            "omniparser_interactable",
            "calibrated_target_validated",
            "execute_candidate_ranked",
            "cross_evidence_overlap",
        )
    )


def _has_direct_interactable_evidence(interactable: dict[str, Any]) -> bool:
    """只接受能证明动作能力的证据；几何校准与重叠本身不代表可交互。"""

    return any(
        bool(interactable.get(key))
        for key in (
            "uia_invokable",
            "uia_value_pattern",
            "uia_editable",
            "dom_clickable",
            "dom_editable",
            "omniparser_interactable",
            "execute_candidate_ranked",
        )
    )


def _has_multi_source_interactable_surrogate(sources: set[str]) -> bool:
    return len(sources.intersection({"ocr", "uia", "dom", "omniparser"})) >= 2


def _looks_like_open_detail_card(item: dict[str, Any], *, interactable: dict[str, Any]) -> bool:
    role = str(item.get("role") or "").casefold()
    item_type = str(item.get("item_type") or "").casefold()
    if role != "card" and item_type != "card":
        return False
    if not _has_interactable_evidence(interactable):
        return False
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    text_parts = [
        str(item.get("label") or ""),
        str(item.get("text") or ""),
        str(metadata.get("description") or ""),
    ]
    if isinstance(metadata.get("text_lines"), list):
        text_parts.extend(str(value) for value in metadata.get("text_lines", []))
    text = " ".join(text_parts).casefold()
    return any(term in text for term in ("job", "listing", "result", "company"))


def _looks_like_danger_action(label: str) -> bool:
    text = str(label or "").casefold()
    return any(
        token in text
        for token in (
            "submit application",
            "send application",
            "complete application",
            "review and submit",
            "confirm",
            "payment",
            "delete",
        )
    )


def _is_non_actionable(item: dict[str, Any]) -> bool:
    item_type = str(item.get("item_type") or "").casefold()
    role = str(item.get("role") or "").casefold()
    strength = str(item.get("evidence_strength") or "").casefold()
    interactable = item.get("interactable_evidence") if isinstance(item.get("interactable_evidence"), dict) else {}
    if _looks_like_open_detail_card(item, interactable=interactable):
        return False
    if role in {"text", "section", "group"}:
        return not _has_direct_interactable_evidence(interactable)
    return item_type in {"readable", "layout"} or strength in {"semantic_only", "ocr_text_anchor_only", "danger_zone"}


def _rejection_metric(items: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = len(items)
    passed = len([item for item in items if item.get("grounding_eligible") is not True])
    return {
        "passed": passed,
        "attempted": attempted,
        "rate": "not_covered" if attempted == 0 else round(passed / attempted, 4),
    }


def _eligible_breakdown(items: list[dict[str, Any]]) -> dict[str, int]:
    breakdown = {
        "semantic_only": 0,
        "ocr_only": 0,
        "uia_interactable": 0,
        "dom_interactable": 0,
        "omniparser_interactable": 0,
        "human_calibrated": 0,
        "no_dispatch_execute_candidate": 0,
    }
    for item in items:
        sources = _sources(item)
        interactable = item.get("interactable_evidence") if isinstance(item.get("interactable_evidence"), dict) else {}
        if item.get("evidence_strength") == "semantic_only":
            breakdown["semantic_only"] += 1
        if item.get("evidence_strength") == "ocr_text_anchor_only":
            breakdown["ocr_only"] += 1
        if "uia" in sources or bool(interactable.get("uia_invokable")) or bool(interactable.get("uia_value_pattern")):
            breakdown["uia_interactable"] += 1
        if "dom" in sources or bool(interactable.get("dom_clickable")) or bool(interactable.get("dom_editable")):
            breakdown["dom_interactable"] += 1
        if "omniparser" in sources or bool(interactable.get("omniparser_interactable")):
            breakdown["omniparser_interactable"] += 1
        if bool(interactable.get("calibrated_target_validated")) or "calibrated_target" in sources:
            breakdown["human_calibrated"] += 1
        if bool(interactable.get("execute_candidate_ranked")) or "execute_candidate_result" in sources:
            breakdown["no_dispatch_execute_candidate"] += 1
    return breakdown
