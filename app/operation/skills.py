from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.runtime_architecture.contracts import AppProfile
from app.runtime_architecture.profiles import get_app_profile


class OperationSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["operation_skill_v2"] = "operation_skill_v2"
    skill_id: str
    category: Literal["observe", "locate", "click", "input", "scroll", "read", "form", "window", "verify", "app_specific"]
    description: str
    side_effect_class: Literal["read_only", "navigation", "write", "dangerous"] = "read_only"
    requires_gate: bool = True
    maps_to_apis: list[str] = Field(default_factory=list)
    semantic_actions: list[str] = Field(default_factory=list)
    input_contract: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    evidence_requirements: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    decision_boundary: dict[str, list[str]] = Field(default_factory=dict)
    authorization_contract: dict[str, Any] = Field(default_factory=dict)
    trace_contract: dict[str, Any] = Field(default_factory=dict)


def _operation_skill(
    *,
    skill_id: str,
    category: Literal["observe", "locate", "click", "input", "scroll", "read", "form", "window", "verify", "app_specific"],
    description: str,
    side_effect_class: Literal["read_only", "navigation", "write", "dangerous"] = "read_only",
    requires_gate: bool = True,
    maps_to_apis: list[str] | None = None,
    semantic_actions: list[str] | None = None,
    input_required: list[str] | None = None,
    input_optional: list[str] | None = None,
    output_fields: list[str] | None = None,
    preconditions: list[str] | None = None,
    evidence_requirements: list[str] | None = None,
    failure_modes: list[str] | None = None,
    agent_decides: list[str] | None = None,
    gate_decides: list[str] | None = None,
    skill_must_not_decide: list[str] | None = None,
    requires_authorized_intent: bool = True,
    requires_gate_decision: bool | None = None,
) -> OperationSkill:
    gate_required = bool(requires_gate if requires_gate_decision is None else requires_gate_decision)
    trace_required_fields = [
        "authorized_intent_id",
        "semantic_action",
        "skill_id",
        "capture_id",
        "window_binding_id",
        "evidence_refs",
        "result_status",
    ]
    if gate_required:
        trace_required_fields.insert(3, "gate_decision_id")
    return OperationSkill(
        skill_id=skill_id,
        category=category,
        description=description,
        side_effect_class=side_effect_class,
        requires_gate=requires_gate,
        maps_to_apis=maps_to_apis or [],
        semantic_actions=semantic_actions or [skill_id],
        input_contract={
            "contract_version": "operation_skill_input_contract_v1",
            "required_fields": input_required or ["authorized_intent_id", "current_observation"],
            "optional_fields": input_optional or [],
            "freshness_policy": "current_capture_required_for_coordinates",
        },
        output_contract={
            "contract_version": "operation_skill_output_contract_v1",
            "required_fields": output_fields
            or ["status", "evidence_refs", "trace_path", "failure_reason", "safety_counters"],
            "must_surface_failures": True,
        },
        preconditions=preconditions or ["bound_window_verified"],
        evidence_requirements=evidence_requirements or ["input_goal", "current_observation_or_capture", "trace_ref"],
        failure_modes=failure_modes
        or ["target_not_found", "ambiguous_target", "stale_capture_or_coordinates", "gate_rejected", "postcondition_not_verified"],
        decision_boundary={
            "agent_decides": agent_decides or ["intent", "semantic_action", "business_goal"],
            "gate_decides": gate_decides or ["safety", "freshness", "scope", "danger"],
            "skill_must_not_decide": skill_must_not_decide
            or ["business_suitability", "profile_truth", "privacy_consent", "final_submit_approval"],
        },
        authorization_contract={
            "contract_version": "operation_skill_authorization_contract_v1",
            "requires_authorized_intent_id": bool(requires_authorized_intent),
            "requires_gate_decision_id": gate_required,
            "required_fields_when_gate_required": ["gate_decision_id", "gate_policy_version", "allowed_action_scope"],
            "path_graph_may_only_provide": ["roi_hint", "expected_transition", "historical_label"],
            "path_graph_must_not_provide": ["click_authorization"],
        },
        trace_contract={
            "contract_version": "operation_skill_trace_contract_v1",
            "required_event_fields": trace_required_fields,
            "record_decision_boundary": True,
        },
    )


_BASE_OPERATION_SKILLS: tuple[OperationSkill, ...] = (
    _operation_skill(
        skill_id="observe_screen",
        category="observe",
        description="Capture and understand the current screen before the Agent decides the next intent.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /vision/observe_screen", "POST /execute/observe"],
        semantic_actions=["observe_screen", "read_current_state"],
        input_required=["authorized_intent_id", "window_binding_id"],
        output_fields=["capture_id", "viewport_size", "screen_summary", "screen_inventory", "trace_path"],
        preconditions=["target_window_bound_or_bindable"],
        evidence_requirements=["window_binding_id", "screenshot_path", "ocr_or_uia_evidence", "trace_ref"],
        failure_modes=["no_bound_window", "capture_failed", "ocr_or_vision_failed"],
        requires_authorized_intent=True,
        requires_gate_decision=False,
    ),
    _operation_skill(
        skill_id="locate_element",
        category="locate",
        description="Locate a target element from the current observation without executing a real action.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /vision/locate_target"],
        semantic_actions=["locate_element", "rank_candidates"],
        input_required=["authorized_intent_id", "goal", "capture_id", "viewport_size"],
        output_fields=["candidate_refs", "bbox", "click_point", "confidence", "trace_path"],
        preconditions=["current_capture_available"],
        evidence_requirements=["capture_id", "ocr_anchors_or_uia_controls", "candidate_ranking_evidence"],
        failure_modes=["target_not_found", "ambiguous_target", "low_confidence"],
        requires_gate_decision=False,
    ),
    _operation_skill(
        skill_id="click_target",
        category="click",
        description="Click a fresh, gated target in the bound window.",
        side_effect_class="navigation",
        maps_to_apis=["POST /action/execute_recognition_plan", "POST /action/execute_confirmed_point"],
        semantic_actions=["click_target", "open_detail", "continue_next_step"],
        input_required=["authorized_intent_id", "gate_decision_id", "capture_id", "viewport_size", "window_binding_id", "target_bbox", "click_point"],
        output_fields=["click_result", "post_click_verification", "trace_path", "safety_counters"],
        preconditions=["bound_window_verified", "point_inside_bbox", "candidate_freshness_current", "gate_allows_navigation"],
        evidence_requirements=["pre_click_decision_v1", "candidate_freshness_v1", "before_screenshot", "after_screenshot_or_state"],
        failure_modes=["confirmed_point_outside_bbox", "stale_capture_or_coordinates", "ambiguous_target", "dangerous_target_blocked", "post_click_verification_failed"],
        gate_decides=["freshness", "point_scope", "danger", "final_submit_block"],
    ),
    _operation_skill(
        skill_id="type_text",
        category="input",
        description="Type Agent-provided text into a verified field without submitting by default.",
        side_effect_class="write",
        maps_to_apis=["POST /action/type_text"],
        semantic_actions=["fill_field", "type_text"],
        input_required=["authorized_intent_id", "gate_decision_id", "field_id", "value_source", "text_length", "window_binding_id"],
        output_fields=["type_result", "post_fill_verification", "trace_path", "safety_counters"],
        preconditions=["field_verified", "value_source_allowed", "submit_false_by_default", "gate_allows_write"],
        evidence_requirements=["field_inventory_ref", "value_source_hash", "before_screenshot", "post_fill_verification"],
        failure_modes=["field_not_found", "field_not_safe_to_fill", "clipboard_write_failed", "post_fill_value_unverified", "final_submit_visible_after_fill"],
        skill_must_not_decide=["truthfulness_of_value", "privacy_consent", "profile_mutation_approval", "final_submit_approval"],
    ),
    _operation_skill(
        skill_id="scroll_region",
        category="scroll",
        description="Scroll a scoped container and verify the intended content changed.",
        side_effect_class="navigation",
        maps_to_apis=["POST /action/scroll"],
        semantic_actions=["scroll_region", "load_more_content"],
        input_required=["authorized_intent_id", "gate_decision_id", "target_container_id", "scroll_scope", "direction", "capture_id"],
        output_fields=["scroll_result", "scroll_effect_validation", "trace_path"],
        preconditions=["target_container_verified", "scroll_safe_point_inside_container", "gate_allows_navigation"],
        evidence_requirements=["scroll_precondition_decision_v1", "before_container_snapshot", "after_container_snapshot"],
        failure_modes=["wrong_scope_detected", "container_not_scrollable", "no_effect_detected", "non_target_pane_changed"],
    ),
    _operation_skill(
        skill_id="read_region",
        category="read",
        description="Read a known screen region through OCR/UI evidence.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /vision/ocr_region", "POST /execute/read_region_batch"],
        semantic_actions=["read_region", "read_region_batch"],
        input_required=["authorized_intent_id", "region_id", "roi", "capture_id"],
        output_fields=["text_lines", "snapshot_id", "trace_path"],
        preconditions=["roi_inside_window", "capture_available"],
        evidence_requirements=["roi", "ocr_result", "trace_ref"],
        failure_modes=["ocr_failed", "empty_region", "wrong_region"],
        requires_gate_decision=False,
    ),
    _operation_skill(
        skill_id="read_full_page",
        category="read",
        description="Read full page content when a scoped region is not enough for Agent decisions.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /vision/observe_screen"],
        semantic_actions=["read_full_page", "observe_full_page"],
        input_required=["authorized_intent_id", "capture_id"],
        output_fields=["screen_summary", "screen_inventory", "text_lines", "trace_path"],
        preconditions=["capture_available"],
        evidence_requirements=["screenshot_path", "ocr_or_uia_evidence", "trace_ref"],
        failure_modes=["capture_failed", "ocr_or_vision_failed", "page_too_large_for_single_read"],
        requires_gate_decision=False,
    ),
    _operation_skill(
        skill_id="detect_form",
        category="form",
        description="Detect fields, selected values, and safe fill targets in the active form.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /execute/form_inventory"],
        semantic_actions=["detect_form", "inventory_fields"],
        input_required=["authorized_intent_id", "capture_id", "flow_container_id"],
        output_fields=["form_inventory", "safe_fill_candidates", "risky_fields", "trace_path"],
        preconditions=["active_form_or_flow_container_visible"],
        evidence_requirements=["field_labels", "control_types", "container_scope"],
        failure_modes=["form_not_found", "ambiguous_fields", "dangerous_fields_present"],
        requires_gate_decision=False,
    ),
    _operation_skill(
        skill_id="bind_window",
        category="window",
        description="Bind or launch the target app/window before screen operations.",
        side_effect_class="navigation",
        maps_to_apis=["POST /apps/open", "POST /session/bind_window"],
        semantic_actions=["bind_window", "open_app"],
        input_required=["authorized_intent_id", "app_name"],
        output_fields=["window_binding_id", "process_name", "window_title", "rect", "trace_path"],
        preconditions=["app_name_known_or_user_selected"],
        evidence_requirements=["process_name", "window_title", "window_rect"],
        failure_modes=["app_not_found", "ambiguous_window", "window_bind_failed"],
        requires_gate_decision=False,
    ),
    _operation_skill(
        skill_id="verify_change",
        category="verify",
        description="Verify before/after screen change, focus, OCR, or scoped UI diff evidence.",
        side_effect_class="read_only",
        requires_gate=False,
        maps_to_apis=["POST /execute/verify_diff"],
        semantic_actions=["verify_change", "verify_postcondition"],
        input_required=["authorized_intent_id", "before_evidence_ref", "after_capture_id", "expected_effect"],
        output_fields=["verified", "diff_summary", "failure_reason", "trace_path"],
        preconditions=["before_and_after_evidence_available"],
        evidence_requirements=["before_screenshot", "after_screenshot", "expected_effect"],
        failure_modes=["no_change_detected", "wrong_change_detected", "verification_evidence_missing"],
        requires_gate_decision=False,
    ),
    _operation_skill(
        skill_id="open_apply_flow",
        category="click",
        description="Open an application flow; this is not final submit.",
        side_effect_class="navigation",
        maps_to_apis=["POST /action/execute_recognition_plan"],
        semantic_actions=["open_apply_flow"],
        input_required=["authorized_intent_id", "gate_decision_id", "job_id", "target_container_id", "capture_id", "click_point"],
        output_fields=["application_flow_started", "current_url", "application_flow_state", "trace_path", "safety_counters"],
        preconditions=["job_detail_verified", "apply_click_is_not_final_submit", "gate_allows_open_apply_flow"],
        evidence_requirements=["latest_detail_snapshot", "pre_click_decision_v1", "url_snapshot_when_available", "post_click_application_state"],
        failure_modes=["apply_button_not_found", "external_account_or_privacy_required", "login_required", "captcha_or_verification_required", "final_submit_visible"],
        agent_decides=["job_suitability", "whether_to_attempt_apply_entry", "external_apply_allowed"],
        gate_decides=["apply_is_not_final_submit", "active_container_scope", "account_privacy_boundary", "final_submit_block"],
        skill_must_not_decide=["job_suitability", "privacy_consent", "account_creation", "final_submit_approval"],
    ),
)


_SEEK_SKILL_ALIASES: dict[str, str] = {
    "locate_job_card": "locate_element",
    "open_job_detail": "click_target",
    "read_full_job_detail": "read_full_page",
    "scroll_results_list": "scroll_region",
    "scroll_detail_pane": "scroll_region",
    "reset_detail_pane_to_header": "scroll_region",
    "open_apply_entry": "open_apply_flow",
    "observe_application_flow": "observe_screen",
    "read_application_form": "detect_form",
    "verify_page_change": "verify_change",
}


def list_operation_skills(app_id: str | None = None) -> list[dict[str, Any]]:
    profile = _profile_for_app(app_id)
    base = {skill.skill_id: skill.model_dump() for skill in _BASE_OPERATION_SKILLS}
    if not profile:
        return list(base.values())
    skills: list[dict[str, Any]] = []
    for skill_id in profile.operation_skills:
        if skill_id in base:
            payload = dict(base[skill_id])
            payload["profile_skill_id"] = skill_id
            skills.append(payload)
            continue
        base_skill_id = _SEEK_SKILL_ALIASES.get(skill_id)
        if base_skill_id and base_skill_id in base:
            payload = dict(base[base_skill_id])
            semantic_actions = list(payload.get("semantic_actions") or [])
            if skill_id not in semantic_actions:
                semantic_actions.append(skill_id)
            payload.update(
                {
                    "skill_id": skill_id,
                    "base_skill_id": base_skill_id,
                    "profile_skill_id": skill_id,
                    "category": "app_specific",
                    "description": f"{profile.display_name} profile skill backed by {base_skill_id}.",
                    "semantic_actions": semantic_actions,
                }
            )
            skills.append(payload)
            continue
        skills.append(
            _operation_skill(
                skill_id=skill_id,
                category="app_specific",
                description=f"{profile.display_name} profile-specific operation skill.",
                side_effect_class="navigation",
                maps_to_apis=["POST /action/execute_recognition_plan"],
                semantic_actions=[skill_id],
                input_required=["authorized_intent_id", "gate_decision_id", "capture_id", "window_binding_id"],
                output_fields=["status", "evidence_refs", "trace_path", "failure_reason", "safety_counters"],
                preconditions=["bound_window_verified", "gate_allows_profile_specific_action"],
            ).model_dump()
        )
    return skills


def build_operation_skill_catalog(app_id: str | None = None) -> dict[str, Any]:
    profile = _profile_for_app(app_id)
    return {
        "contract_version": "operation_skill_catalog_v2",
        "execution_model": "agentic_loop_first",
        "skill_contract_version": "operation_skill_v2",
        "decision_model": "agent_decides_gate_authorizes_operation_executes",
        "path_graph_policy": "guidance_only_not_authorization",
        "app_id": profile.app_id if profile else app_id,
        "profile_path": _profile_path(app_id) if profile else None,
        "skills": list_operation_skills(app_id),
    }


def _profile_for_app(app_id: str | None) -> AppProfile | None:
    if not app_id:
        return None
    profile, _path = get_app_profile(app_id)
    return profile


def _profile_path(app_id: str | None) -> str | None:
    if not app_id:
        return None
    _profile, path = get_app_profile(app_id)
    return str(Path(path))
