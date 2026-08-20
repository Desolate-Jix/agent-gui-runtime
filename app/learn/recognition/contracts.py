from __future__ import annotations

from copy import deepcopy
from typing import Any


LEARN_OBSERVE_BUNDLE_CONTRACT = "learn_observe_bundle_v1"
SCREEN_INVENTORY_ITEM_CONTRACT = "screen_inventory_item_v2"
PARSER_CANDIDATE_CONTRACT = "parser_candidate_v1"
LEARN_CANDIDATE_CLASSIFICATION_CONTRACT = "learn_candidate_classification_v1"
LEARNING_RECOGNITION_DRAFT_SOURCE = "learn_recognition_pipeline_v2"


def build_inventory_item(
    *,
    item_id: str,
    label: str,
    item_type: str,
    bbox: dict[str, Any] | None = None,
    role: str = "text",
    text: str | None = None,
    source_evidence: list[str] | None = None,
    evidence_level: str = "unknown",
    interactable_evidence: dict[str, Any] | None = None,
    click_candidate: bool = False,
    risk_hint: str = "low",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "contract_version": SCREEN_INVENTORY_ITEM_CONTRACT,
        "item_id": str(item_id),
        "label": str(label or ""),
        "item_type": str(item_type or "readable"),
        "role": str(role or "text"),
        "bbox": _normalized_bbox(bbox),
        "text": str(text if text is not None else label or ""),
        "source_evidence": [str(item) for item in (source_evidence or []) if str(item or "").strip()],
        "interactable_evidence": _default_interactable_evidence(interactable_evidence),
        "click_candidate": bool(click_candidate),
        "risk_hint": str(risk_hint or "low"),
        "evidence_level": str(evidence_level or "unknown"),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_action_requires_gate": True,
        "metadata": deepcopy(metadata) if isinstance(metadata, dict) else {},
    }


def build_learning_template_draft_from_validated_items(
    *,
    state_guess: str,
    summary: str,
    valid_items: list[dict[str, Any]],
    evidence_refs: dict[str, Any] | None = None,
    page_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    states = [
        {
            "state_id": _slug_or_default(state_guess, "state_1"),
            "label": str(state_guess or "unknown_state"),
            "summary": str(summary or ""),
        }
    ]
    regions: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for index, item in enumerate(valid_items):
        if not isinstance(item, dict):
            continue
        region_id = str(item.get("region_id") or f"region_{index + 1}")
        action_id = str(item.get("action_template_id") or f"action_{index + 1}")
        semantic_action = str(item.get("semantic_action") or _semantic_action_for_item(item))
        regions.append(
            {
                "region_id": region_id,
                "label": str(item.get("label") or item.get("item_id") or region_id),
                "role": str(item.get("role") or item.get("item_type") or "actionable"),
                "bbox": deepcopy(item.get("bbox") or {}),
                "source_item_id": item.get("item_id"),
                "grounding_status": "validated",
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        action = {
            "action_template_id": action_id,
            "label": str(item.get("label") or item.get("item_id") or f"action {index + 1}"),
            "target_entity": region_id,
            "target_region_id": region_id,
            "semantic_action": semantic_action,
            "action_kind": semantic_action,
            "low_level_action_type": "input" if semantic_action == "fill_field" else "click",
            "source_item_id": item.get("item_id"),
            "bbox": deepcopy(item.get("bbox") or {}),
            "click_point": deepcopy(item.get("click_point") or item.get("screen_point") or {}),
            "requires_gate": True,
            "candidate_freshness_required": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "verification_rule_ids": [
                "target_region_still_visible",
                "point_inside_validated_region",
                "no_final_submit_surface",
            ],
        }
        if semantic_action == "open_detail":
            action["transition_hint"] = _open_detail_transition_hint(region_id)
        actions.append(action)
    return {
        "contract_version": "learning_template_draft_v1",
        "screen_summary": str(summary or ""),
        "state_guess": str(state_guess or ""),
        "states": states,
        "regions": regions,
        "action_templates": actions,
        "blockers": _default_blockers(),
        "verification_rules": _default_verification_rules(),
        "agent_decision_points": [],
        "operation_skills": _operation_skills_for_actions(actions),
        "gate_contracts": _default_gate_contracts(),
        "learning_source": LEARNING_RECOGNITION_DRAFT_SOURCE,
        "evidence_refs": deepcopy(evidence_refs) if isinstance(evidence_refs, dict) else {},
        "page_details": deepcopy(page_details) if isinstance(page_details, dict) else _empty_page_details(),
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_action_requires_gate": True,
            "final_submit_forbidden": True,
        },
    }


def build_parser_candidate_evidence(
    *,
    item: dict[str, Any],
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = source_context if isinstance(source_context, dict) else {}
    evidence_level = str(item.get("evidence_level") or "unknown")
    source_evidence = [str(value) for value in item.get("source_evidence", []) if str(value or "").strip()] if isinstance(item.get("source_evidence"), list) else []
    interactable_evidence = item.get("interactable_evidence") if isinstance(item.get("interactable_evidence"), dict) else {}
    is_interactable = _has_interactable_evidence(interactable_evidence)
    review_only = not is_interactable
    return {
        "schema_version": PARSER_CANDIDATE_CONTRACT,
        "source_type": _candidate_source_type(source_evidence),
        "source_run_id": str(context.get("source_run_id") or context.get("run_id") or ""),
        "screenshot_sha256": str(context.get("screenshot_sha256") or ""),
        "coordinate_space": str(context.get("coordinate_space") or "image"),
        "image_size": deepcopy(context.get("image_size") or {}),
        "window_rect": deepcopy(context.get("window_rect") or {}),
        "candidate_id": str(item.get("item_id") or ""),
        "bbox": deepcopy(item.get("bbox") if isinstance(item.get("bbox"), dict) else {}),
        "text": str(item.get("text") or item.get("label") or ""),
        "label": str(item.get("label") or ""),
        "role_hint": str(item.get("role") or "unknown"),
        "evidence_kind": _candidate_evidence_kind(evidence_level),
        "is_interactable_evidence": is_interactable,
        "review_only": review_only,
        "grounding_eligible": is_interactable,
        "grounding_block_reason": "" if is_interactable else _candidate_block_reason(evidence_level),
        "raw_payload_path": str(context.get("raw_payload_path") or ""),
        "freshness": {
            "same_screenshot": bool(context.get("same_screenshot", bool(context.get("screenshot_sha256")))),
            "capture_time": str(context.get("capture_time") or ""),
            "stale": bool(context.get("stale")),
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _open_detail_transition_hint(source_region_id: str) -> dict[str, Any]:
    return {
        "contract_version": "learn_open_detail_transition_hint_v1",
        "transition_type": "open_detail",
        "source_region_id": source_region_id,
        "expected_next_state_role": "detail_view",
        "target_surface": "detail_pane_or_detail_page",
        "requires_post_action_observe": True,
        "candidate_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _default_interactable_evidence(value: dict[str, Any] | None) -> dict[str, Any]:
    evidence = deepcopy(value) if isinstance(value, dict) else {}
    return {
        "uia_invokable": bool(evidence.get("uia_invokable")),
        "dom_clickable": bool(evidence.get("dom_clickable")),
        "omniparser_interactable": bool(evidence.get("omniparser_interactable")),
        "calibrated_target_validated": bool(evidence.get("calibrated_target_validated")),
        "execute_candidate_ranked": bool(evidence.get("execute_candidate_ranked")),
        "cross_evidence_overlap": bool(evidence.get("cross_evidence_overlap")),
        "vision_claim": bool(evidence.get("vision_claim")),
    }


def _has_interactable_evidence(evidence: dict[str, Any]) -> bool:
    return any(
        bool(evidence.get(key))
        for key in (
            "uia_invokable",
            "dom_clickable",
            "omniparser_interactable",
            "calibrated_target_validated",
            "execute_candidate_ranked",
            "cross_evidence_overlap",
        )
    )


def _candidate_source_type(sources: list[str]) -> str:
    normalized = [source.casefold() for source in sources if source.strip()]
    if len(normalized) > 1:
        return "mixed"
    if not normalized:
        return "unknown"
    mapping = {
        "vision": "qwen_vlm",
        "ocr": "ocr",
        "uia": "uia",
        "dom": "dom",
        "omniparser": "omniparser",
        "calibrated_target": "calibrated_target",
        "execute_candidate_result": "execute_candidate_no_dispatch",
    }
    return mapping.get(normalized[0], normalized[0])


def _candidate_evidence_kind(evidence_level: str) -> str:
    text = str(evidence_level or "").casefold()
    mapping = {
        "semantic_region_only": "semantic_region",
        "ocr_text_only": "ocr_text_anchor",
        "uia_control": "uia_interactable",
        "omniparser_interactable": "omniparser_interactable",
        "calibrated_target": "calibrated_interactable",
        "execute_candidate_result": "no_dispatch_candidate",
        "cross_evidence_grounded": "cross_evidence_interactable",
    }
    return mapping.get(text, text or "unknown")


def _candidate_block_reason(evidence_level: str) -> str:
    text = str(evidence_level or "").casefold()
    if text == "semantic_region_only":
        return "semantic_region_only_without_interactable_evidence"
    if text == "ocr_text_only":
        return "ocr_only_without_interactable_evidence"
    return "missing_interactable_evidence"


def _normalized_bbox(value: dict[str, Any] | None) -> dict[str, int]:
    if not isinstance(value, dict):
        return {"x": 0, "y": 0, "w": 0, "h": 0}
    return {
        "x": _int_or_zero(value.get("x")),
        "y": _int_or_zero(value.get("y")),
        "w": max(0, _int_or_zero(value.get("w"))),
        "h": max(0, _int_or_zero(value.get("h"))),
    }


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _slug_or_default(value: str, default: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "")).strip("_")
    return slug or default


def _semantic_action_for_item(item: dict[str, Any]) -> str:
    item_type = str(item.get("item_type") or "").casefold()
    role = str(item.get("role") or "").casefold()
    if item_type == "form_field" or "input" in role or "textbox" in role:
        return "fill_field"
    if _looks_like_open_detail_card(item):
        return "open_detail"
    return "activate"


def _looks_like_open_detail_card(item: dict[str, Any]) -> bool:
    item_type = str(item.get("item_type") or "").casefold()
    role = str(item.get("role") or "").casefold()
    if "card" not in {item_type, role}:
        return False
    text = _item_text_blob(item)
    if not any(term in text for term in ("job", "listing", "result", "title", "company")):
        return False
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    text_lines = metadata.get("text_lines") if isinstance(metadata.get("text_lines"), list) else []
    meaningful_lines = [str(line).strip() for line in text_lines if str(line or "").strip()]
    return len(meaningful_lines) >= 1 or ":" in str(item.get("label") or "")


def _item_text_blob(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    parts: list[str] = [
        str(item.get("label") or ""),
        str(item.get("text") or ""),
        str(metadata.get("description") or ""),
    ]
    if isinstance(metadata.get("text_lines"), list):
        parts.extend(str(line) for line in metadata.get("text_lines", []))
    return " ".join(parts).casefold()


def _default_blockers() -> list[dict[str, Any]]:
    return [
        {
            "blocker_id": "final_submit_guard",
            "label": "Block final submit/send/confirm/payment actions",
            "blocked_terms": ["submit", "send", "complete", "confirm", "payment"],
            "scope": "active_application_or_form_surface",
            "severity": "hard_block",
        },
        {
            "blocker_id": "stale_or_unverified_grounding",
            "label": "Block stale screenshots or unverified coordinate transforms",
            "requires": ["fresh_capture", "coordinate_transform_replay", "point_inside_validated_region"],
            "severity": "hard_block",
        },
    ]


def _default_verification_rules() -> list[dict[str, Any]]:
    return [
        {
            "rule_id": "target_region_still_visible",
            "label": "Target region must still be visible in the current capture",
            "required": True,
        },
        {
            "rule_id": "point_inside_validated_region",
            "label": "Resolved point must remain inside the validated region bbox",
            "required": True,
        },
        {
            "rule_id": "no_final_submit_surface",
            "label": "Do not execute if the candidate is a final submit/send/confirm/payment control",
            "required": True,
        },
    ]


def _operation_skills_for_actions(actions: list[dict[str, Any]]) -> list[str]:
    skills = {"observe_screen", "locate_element"}
    for action in actions:
        low_level = str(action.get("low_level_action_type") or "")
        if low_level == "input":
            skills.add("type_text")
        elif low_level == "click":
            skills.add("click_target")
    return sorted(skills)


def _default_gate_contracts() -> list[dict[str, Any]]:
    return [
        {
            "contract_id": "pre_click_decision_v1",
            "required": True,
            "checks": [
                "fresh_capture_id",
                "point_inside_bbox",
                "candidate_score_margin",
                "danger_zone_rejection",
            ],
        },
        {
            "contract_id": "final_submit_guard_v1",
            "required": True,
            "blocked_actions": ["final_submit", "send", "confirm", "payment"],
        },
    ]


def _empty_page_details() -> dict[str, Any]:
    return {
        "contract_version": "learning_draft_page_details_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "inventory_summary": {},
        "review_only_regions": [],
        "grounding_candidates": [],
        "danger_zones": [],
        "interpretation": "Read-only page understanding details; not click authorization.",
    }
