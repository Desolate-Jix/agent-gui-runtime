from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter

from app.core.input_controller import input_controller
from app.core.ocr_service import ocr_service
from app.core.runtime_artifacts import RuntimeTimer, new_learned_instruction_id, write_trace
from app.core.screenshot import screenshot_service
from app.gate.window import validate_bound_window_for_app
from app.core.transition_memory import transition_memory
from app.core.verifier import verifier
from app.core.window_manager import window_manager
from app.gate.scroll import build_scroll_effect_validation, build_scroll_precondition_decision, build_scroll_safe_point
from app.operation.mousetester import should_verify_mouse_tester_semantics, target_bbox_from_recommended, verify_mouse_tester_post_click_semantics
from app.trace.actions import write_execute_trace_if_enabled
from app.models.request import (
    ClickTextRequest,
    ExecuteConfirmedPointRequest,
    ExecuteRecognitionPlanRequest,
    ScrollRequest,
    TypeTextRequest,
    VisionRecognitionPlanOverlayRequestModel,
    VisionRecognitionPlanRequestModel,
)
from app.models.response import APIResponse, ActionResultData, ErrorModel
from app.schemas.transition import TransitionRecord
from app.seek.scroll_containers import (
    discover_seek_scroll_containers,
    get_scroll_container,
    seek_scroll_target_for_goal,
)
from modules.ocr.matching import bbox_center, find_text_matches
from modules.region.geometry import (
    window_rect as window_rect_module,
)

try:
    from PIL import Image
except Exception:  # pragma: no cover - depends on optional runtime imaging support
    Image = None  # type: ignore[assignment]

router = APIRouter(prefix="/action", tags=["action"])

APPROVED_PLANS_DIR = Path("logs/approved-plans")
APPROVED_PLANS_DIR.mkdir(parents=True, exist_ok=True)
APPROVED_PLAN_TTL_SECONDS = 300
LEARNED_INSTRUCTIONS_DIR = Path("artifacts/local-learning/instructions")
LEARNED_INSTRUCTIONS_DIR.mkdir(parents=True, exist_ok=True)

def _run_recognition_plan_for_execution(request: VisionRecognitionPlanRequestModel) -> APIResponse:
    from app.api.vision import recognition_plan

    return recognition_plan(request)


def _render_recognition_plan_overlay_for_execution(trace_path: str) -> Optional[dict[str, Any]]:
    from app.api.vision import render_recognition_plan_overlay_route

    response = render_recognition_plan_overlay_route(
        VisionRecognitionPlanOverlayRequestModel(
            trace_path=trace_path,
            include_rejected=True,
            include_points=True,
            label_candidates=True,
            label_reasons=True,
        )
    )
    if not response.success or not response.data:
        return None
    return response.data.get("result")


def _extract_action_point(plan: dict[str, Any]) -> Optional[dict[str, int]]:
    point = (plan.get("pre_click_decision") or {}).get("selected_click_point")
    if not point:
        return None
    return {"x": int(point["x"]), "y": int(point["y"])}


def _low_risk_visual_fast_lane_profile(
    *,
    request: ExecuteRecognitionPlanRequest,
    plan: dict[str, Any],
    pre_click: dict[str, Any],
    selected_point: Optional[dict[str, int]],
) -> dict[str, Any]:
    execution_path = plan.get("execution_path") if isinstance(plan.get("execution_path"), dict) else {}
    selected_candidate_id = pre_click.get("selected_candidate_id")
    selected_texts = _selected_target_texts(plan=plan, selected_candidate_id=selected_candidate_id)
    matched_final_submit_terms = _matched_final_submit_terms(
        _final_submit_guard_evidence_texts(selected_texts, goal=request.goal)
    )
    allowed = (
        bool(execution_path.get("visual_asset_fast_lane_used"))
        and bool(pre_click.get("allowed"))
        and selected_point is not None
        and not matched_final_submit_terms
    )
    reasons: list[str] = []
    if not execution_path.get("visual_asset_fast_lane_used"):
        reasons.append("visual_asset_fast_lane_not_used")
    if not pre_click.get("allowed"):
        reasons.append("pre_click_not_allowed")
    if selected_point is None:
        reasons.append("missing_selected_click_point")
    if matched_final_submit_terms:
        reasons.append("final_submit_like_target")
    return {
        "contract_version": "low_risk_visual_fast_lane_profile_v1",
        "allowed": allowed,
        "selected_candidate_id": selected_candidate_id,
        "selected_texts": selected_texts,
        "matched_final_submit_terms": matched_final_submit_terms,
        "reasons": reasons,
    }


def _should_render_recognition_overlay_for_execution(
    *,
    request: ExecuteRecognitionPlanRequest,
    low_risk_visual_fast_lane: dict[str, Any],
) -> bool:
    if request.dry_run:
        return True
    return not bool(low_risk_visual_fast_lane.get("allowed"))


def _click_timing_options(
    *,
    low_risk_visual_fast_lane: dict[str, Any],
) -> dict[str, Any]:
    if low_risk_visual_fast_lane.get("allowed"):
        return {
            "contract_version": "click_timing_options_v1",
            "settle_ms": 20,
            "hold_ms": 20,
            "reason": "low_risk_visual_asset_fast_lane",
        }
    return {
        "contract_version": "click_timing_options_v1",
        "settle_ms": 200,
        "hold_ms": 70,
        "reason": "default_guarded_click",
    }


FINAL_SUBMIT_GUARD_TERMS = (
    "submit application",
    "send application",
    "complete application",
    "submit",
)


FINAL_SUBMIT_AUTH_CONTRACTS = {"final_submit_decision_v1", "pre_submit_suitability_audit_v1"}
FINAL_SUBMIT_HARD_RISK_FLAGS = {
    "unsupported_yes_answer",
    "unsupported_yes_answers",
    "unsupported_answer_risk",
    "unsupported_employer_answer",
    "missing_current_live_match_decision",
}


def _final_submit_authorization(metadata: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("final_submit_decision", "final_submit_authorization", "pre_submit_suitability_audit"):
        value = metadata.get(key)
        if isinstance(value, dict):
            return value
    return None


def _validate_final_submit_authorization(metadata: dict[str, Any]) -> dict[str, Any]:
    authorization = _final_submit_authorization(metadata)
    errors: list[str] = []
    if authorization is None:
        return {
            "contract_version": "final_submit_authorization_check_v1",
            "valid": False,
            "authorization": None,
            "errors": ["missing_final_submit_decision_v1"],
        }

    contract_version = str(authorization.get("contract_version") or "")
    if contract_version not in FINAL_SUBMIT_AUTH_CONTRACTS:
        errors.append("unsupported_final_submit_authorization_contract")

    allow_final_submit = authorization.get("allow_final_submit") is True or authorization.get("submit_gate") == "allow"
    if not allow_final_submit:
        errors.append("allow_final_submit_not_true")

    if authorization.get("user_reviewed_current_job") is not True:
        errors.append("current_job_not_user_reviewed")

    match_decision = str(authorization.get("match_decision") or authorization.get("decision") or "")
    user_override = authorization.get("user_override_match_review") is True
    if match_decision != "strong_apply" and not user_override:
        errors.append("match_decision_not_strong_apply")

    unsupported_yes_answers = authorization.get("unsupported_yes_answers") is True
    unsupported_answer_risks = authorization.get("unsupported_answer_risks")
    if isinstance(unsupported_answer_risks, list) and unsupported_answer_risks:
        unsupported_yes_answers = True
    risk_flags = [str(item or "") for item in authorization.get("risk_flags") or []]
    hard_risks = [flag for flag in risk_flags if flag in FINAL_SUBMIT_HARD_RISK_FLAGS]
    if unsupported_yes_answers or hard_risks:
        errors.append("unsupported_answer_or_hard_risk_present")

    return {
        "contract_version": "final_submit_authorization_check_v1",
        "valid": not errors,
        "authorization": authorization,
        "errors": errors,
        "match_decision": match_decision,
        "user_override_match_review": user_override,
    }


def _final_submit_guard_decision(
    *,
    request: ExecuteRecognitionPlanRequest,
    plan: dict[str, Any],
    pre_click: dict[str, Any],
) -> dict[str, Any]:
    metadata = request.metadata or {}
    enabled = bool(metadata.get("forbid_final_submit"))
    selected_candidate_id = pre_click.get("selected_candidate_id")
    selected_texts = _selected_target_texts(plan=plan, selected_candidate_id=selected_candidate_id)
    selected_texts = _final_submit_guard_evidence_texts(selected_texts, goal=request.goal)
    matched_terms = _matched_final_submit_terms(selected_texts)
    authorization_check = _validate_final_submit_authorization(metadata) if matched_terms else None
    allowed = not matched_terms or (not enabled and bool(authorization_check and authorization_check.get("valid")))
    if not matched_terms:
        reason = "no_final_submit_candidate_detected" if enabled else "guard_not_needed"
    elif enabled:
        reason = "final_submit_candidate_blocked"
    elif authorization_check and authorization_check.get("valid"):
        reason = "structured_final_submit_authorization_accepted"
    else:
        reason = "final_submit_requires_structured_authorization"
    return {
        "contract_version": "final_submit_guard_v1",
        "enabled": enabled,
        "allowed": allowed,
        "selected_candidate_id": selected_candidate_id,
        "selected_texts": selected_texts,
        "matched_terms": matched_terms,
        "authorization_required": bool(matched_terms),
        "authorization_check": authorization_check,
        "reason": reason,
    }


def _selected_target_texts(*, plan: dict[str, Any], selected_candidate_id: Any) -> list[str]:
    texts: list[str] = []
    recommended = plan.get("recommended_target") if isinstance(plan.get("recommended_target"), dict) else {}
    if not selected_candidate_id or recommended.get("candidate_id") == selected_candidate_id:
        texts.extend(_target_text_values(recommended))

    candidate_result = plan.get("candidate_result") if isinstance(plan.get("candidate_result"), dict) else {}
    for candidate in candidate_result.get("candidates") or []:
        if isinstance(candidate, dict) and candidate.get("candidate_id") == selected_candidate_id:
            texts.extend(_target_text_values(candidate))

    narrow_search = plan.get("narrow_search_result") if isinstance(plan.get("narrow_search_result"), dict) else {}
    for result in narrow_search.get("results") or []:
        if isinstance(result, dict) and result.get("candidate_id") == selected_candidate_id:
            texts.extend(_target_text_values(result))

    return _unique_nonempty_strings(texts)


def _target_text_values(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("label", "text", "matched_text", "candidate_id"):
        value = payload.get(key)
        if isinstance(value, str):
            values.append(value)
    element = payload.get("element") if isinstance(payload.get("element"), dict) else {}
    for key in ("label", "text", "role", "semantic_role"):
        value = element.get(key)
        if isinstance(value, str):
            values.append(value)
    return values


def _unique_nonempty_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split())
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _matched_final_submit_terms(texts: list[str]) -> list[str]:
    haystack = " ".join(texts).casefold()
    return [term for term in FINAL_SUBMIT_GUARD_TERMS if term in haystack]


def _final_submit_guard_evidence_texts(texts: list[str], *, goal: str) -> list[str]:
    goal_key = " ".join(str(goal or "").split()).casefold()
    filtered: list[str] = []
    for text in texts:
        key = " ".join(str(text or "").split()).casefold()
        if not key:
            continue
        if key == goal_key:
            continue
        # Direct grounding may reuse the full instruction as a temporary candidate label.
        # The final-submit guard must inspect target evidence, not negative constraints in the goal.
        if "do not click" in key or "don't click" in key or key.startswith("click the "):
            continue
        filtered.append(text)
    return filtered


def _point_in_rect(point: dict[str, int], rect: dict[str, int]) -> bool:
    return (
        int(rect["x"]) <= int(point["x"]) <= int(rect["x"]) + int(rect["width"])
        and int(rect["y"]) <= int(point["y"]) <= int(rect["y"]) + int(rect["height"])
    )


def _execution_attempt_verified(
    *,
    request: ExecuteRecognitionPlanRequest,
    post_click_verification: dict[str, Any],
    semantic_post_click_verification: dict[str, Any],
) -> bool:
    if not request.enable_post_click_verification:
        return True
    if semantic_post_click_verification.get("applicable"):
        return bool(post_click_verification.get("verified")) and bool(semantic_post_click_verification.get("verified"))
    return bool(post_click_verification.get("verified"))


def _apply_metadata_post_click_policy(
    request: ExecuteRecognitionPlanRequest,
    post_click_verification: dict[str, Any],
) -> dict[str, Any]:
    """Tighten generic verification when an action declares a semantic result requirement."""
    if not isinstance(post_click_verification, dict):
        return post_click_verification
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    verification_policy = metadata.get("verification_policy") if isinstance(metadata.get("verification_policy"), dict) else {}
    expected_rule = str(
        verification_policy.get("expected_semantic_rule")
        or verification_policy.get("post_click")
        or ""
    ).strip()
    semantic_required_rules = {
        "search_results_list_becomes_visible",
        "article_heading_matches_clicked_result",
        "detail_title_company_must_match_clicked_card",
    }
    semantic_required = (
        verification_policy.get("require_semantic_rule_pass") is True
        or verification_policy.get("rule_type") == "semantic_required"
        or expected_rule in semantic_required_rules
    )
    focus_only_allowed = verification_policy.get("focus_only_is_success") is True or verification_policy.get("allow_focus_only_success") is True
    if not semantic_required or focus_only_allowed:
        return post_click_verification

    diff = post_click_verification.get("diff") if isinstance(post_click_verification.get("diff"), dict) else {}
    diff_changed = bool(diff.get("changed"))
    basis = post_click_verification.get("verification_basis") if isinstance(post_click_verification.get("verification_basis"), dict) else {}
    focus_only = bool(basis.get("cursor_and_focus")) and not diff_changed
    if focus_only and post_click_verification.get("verified") is True:
        tightened = dict(post_click_verification)
        tightened["verified"] = False
        tightened["verification_status"] = "unverified"
        tightened["failure_reason"] = "semantic_verification_missing"
        tightened["weak_evidence"] = ["cursor_and_focus"]
        tightened["required_semantic_rule"] = expected_rule or None
        tightened["verification_basis"] = dict(basis)
        tightened["verification_basis"]["focus_only_rejected"] = True
        return tightened
    if semantic_required:
        tightened = dict(post_click_verification)
        tightened["required_semantic_rule"] = expected_rule or None
        tightened["verification_policy_applied"] = "semantic_required"
        return tightened
    return post_click_verification


def _retry_allowed_after_attempt(
    *,
    request: ExecuteRecognitionPlanRequest,
    pre_click: dict[str, Any],
    attempt_index: int,
    attempt_verified: bool,
) -> tuple[bool, str]:
    if attempt_verified:
        return False, "attempt_verified"
    if not request.enable_post_click_verification:
        return False, "post_click_verification_disabled"
    if attempt_index >= int(request.max_execution_attempts):
        return False, "max_execution_attempts_reached"
    if not pre_click.get("allowed"):
        return False, "pre_click_not_allowed"

    selected_candidate_id = pre_click.get("selected_candidate_id")
    selected_decision = None
    for item in pre_click.get("candidate_decisions") or []:
        if item.get("candidate_id") == selected_candidate_id:
            selected_decision = item
            break
    selected_reasons = set((selected_decision or {}).get("reasons") or [])
    blocked_reasons = {
        "candidate_goal_text_mismatch",
        "local_ocr_text_mismatch",
        "candidate_not_eligible",
        "interaction_policy_blocked",
        "ad_like_candidate",
        "refined_point_outside_candidate_bbox",
    }
    if selected_reasons & blocked_reasons:
        return False, "selected_candidate_not_retry_safe"
    return True, "verification_failed_retry_safe"


def _window_rect(bound: Any) -> dict[str, int]:
    return window_rect_module(bound)


def _bound_window_snapshot(bound: Any) -> dict[str, Any]:
    rect = _window_rect(bound)
    return {
        "handle": int(bound.handle),
        "title": bound.title,
        "process_id": getattr(bound, "process_id", None),
        "process_name": getattr(bound, "process_name", None),
        "rect": rect,
    }


def _size_from_rect(rect: dict[str, Any]) -> dict[str, int]:
    return {"width": int(rect.get("width") or 0), "height": int(rect.get("height") or 0)}


def _positive_size(size: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(size, dict):
        return None
    try:
        width = int(size.get("width") or 0)
        height = int(size.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {"width": width, "height": height}


def _coordinate_size_from_live_capture(live_capture: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(live_capture, dict):
        return None
    window_size = _positive_size(live_capture.get("window_size") if isinstance(live_capture.get("window_size"), dict) else None)
    if window_size is not None:
        return window_size
    return _positive_size({"width": live_capture.get("image_width"), "height": live_capture.get("image_height")})


def _record_coordinate_window_size(record: dict[str, Any]) -> dict[str, int]:
    explicit = _positive_size(record.get("coordinate_window_size") if isinstance(record.get("coordinate_window_size"), dict) else None)
    if explicit is not None:
        return explicit
    live_capture = record.get("live_capture") if isinstance(record.get("live_capture"), dict) else None
    capture_size = _coordinate_size_from_live_capture(live_capture)
    if capture_size is not None:
        return capture_size
    window = record.get("bound_window") if isinstance(record.get("bound_window"), dict) else {}
    rect = window.get("rect") if isinstance(window.get("rect"), dict) else {}
    return _size_from_rect(rect)


def _normalize_window_token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _bound_window_matches_request(bound: Any, request: ExecuteRecognitionPlanRequest) -> dict[str, Any]:
    return validate_bound_window_for_app(
        expected_app_name=request.app_name,
        bound_window=_bound_window_snapshot(bound),
    )


def _approved_plan_path(approved_plan_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "", approved_plan_id)
    if not safe_id:
        raise ValueError("approved_plan_id is empty or invalid")
    return APPROVED_PLANS_DIR / f"{safe_id}.json"


def _learned_instruction_path(learned_instruction_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "", learned_instruction_id)
    if not safe_id:
        raise ValueError("learned_instruction_id is empty or invalid")
    return LEARNED_INSTRUCTIONS_DIR / safe_id / "learned_instruction.json"


def _instruction_learning_enabled(request: ExecuteRecognitionPlanRequest) -> bool:
    write_policy = request.write_policy.model_dump() if hasattr(request.write_policy, "model_dump") else {}
    return bool(write_policy.get("element_memory", True)) and str(request.learning_mode or "").strip().casefold() in {"instruction", "instruction_learning"}


def _element_memory_enabled(request: ExecuteRecognitionPlanRequest) -> bool:
    write_policy = request.write_policy.model_dump() if hasattr(request.write_policy, "model_dump") else {}
    return bool(write_policy.get("element_memory", True))


def _rect_from_bbox(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict):
        return None
    try:
        x = int(value.get("x") or 0)
        y = int(value.get("y") or 0)
        width = int(value.get("width") if value.get("width") is not None else value.get("w"))
        height = int(value.get("height") if value.get("height") is not None else value.get("h"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _bbox_payload(rect: dict[str, int] | None) -> dict[str, int] | None:
    if rect is None:
        return None
    return {"x": int(rect["x"]), "y": int(rect["y"]), "w": int(rect["width"]), "h": int(rect["height"])}


def _write_execute_trace_if_enabled(request: ExecuteRecognitionPlanRequest, **kwargs: Any) -> str | None:
    return write_execute_trace_if_enabled(request, write_trace_fn=write_trace, **kwargs)


def _execute_plan_request_defaults(request: ExecuteRecognitionPlanRequest) -> tuple[Optional[str], dict[str, Any]]:
    """Return execution-mode defaults without mutating the API request."""
    metadata = dict(request.metadata or {})
    provider_mode = request.provider_mode
    if request.agent_mode != "execute":
        return provider_mode, metadata

    provider_mode = provider_mode or "local_grounding"
    vista_direct_defaults = {
        "enabled": True,
        "timeout_seconds": 45.0,
        "max_edge": 640,
        "refine": True,
        "refine_roi_size": 512,
        "refine_max_edge": 640,
    }
    vista_direct = metadata.get("vista_direct_grounding")
    if vista_direct is None or vista_direct is True:
        metadata["vista_direct_grounding"] = dict(vista_direct_defaults)
    elif isinstance(vista_direct, dict):
        merged = dict(vista_direct_defaults)
        merged.update(vista_direct)
        metadata["vista_direct_grounding"] = merged
    metadata.setdefault(
        "execute_mode_policy",
        {
            "state_match": "path_graph_when_available",
            "recall": "top_k_relevant_nodes",
            "grounding": "local_model_or_direct_point",
            "requires_pre_click_gate": True,
            "requires_post_click_verification": bool(request.enable_post_click_verification),
        },
    )
    return provider_mode, metadata


def _agent_execution_guidance(
    *,
    request: ExecuteRecognitionPlanRequest,
    status: str,
    result: Optional[dict[str, Any]] = None,
    failure_reason: Optional[str] = None,
) -> dict[str, Any]:
    result = result or {}
    approved_plan_id = result.get("approved_plan_id") or request.approved_plan_id
    fallback_plan = result.get("fallback_plan")
    guidance: dict[str, Any] = {
        "contract_version": "agent_execute_guidance_v1",
        "status": status,
        "goal": request.goal,
        "agent_mode": request.agent_mode,
        "safe_to_click_now": False,
        "failure_reason": failure_reason,
    }
    if status == "dry_run_ready":
        if approved_plan_id:
            guidance.update(
                {
                    "safe_to_click_now": True,
                    "next_action": "execute_approved_plan",
                    "next_request": {
                        "endpoint": "POST /action/execute_recognition_plan",
                        "body": {
                            "goal": request.goal,
                            "app_name": request.app_name,
                            "state_hint": request.state_hint,
                            "approved_plan_id": approved_plan_id,
                            "capture_live": True,
                            "dry_run": False,
                            "enable_post_click_verification": request.enable_post_click_verification,
                            "max_execution_attempts": request.max_execution_attempts,
                            "metadata": request.metadata,
                        },
                    },
                }
            )
        else:
            guidance.update(
                {
                    "next_action": "bind_window_or_run_real_capture",
                    "reason": "dry_run_plan_was_allowed_but_no_bound_window_was_available_to_save_an_approved_plan",
                }
            )
    elif status == "executed_verified":
        guidance.update({"next_action": "done"})
    elif status in {"blocked", "execution_failed", "verification_failed"}:
        guidance.update(
            {
                "next_action": "recover_with_fallback_plan",
                "fallback_plan": fallback_plan,
            }
        )
    else:
        guidance["next_action"] = "inspect_trace"
    return guidance


def _image_path_from(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        image_path = value.get("image_path") or value.get("path") or value.get("diff_image_path")
        return str(image_path) if image_path else None
    if isinstance(value, str) and value:
        return value
    return None


def _latest_attempt(result: dict[str, Any]) -> dict[str, Any]:
    attempts = result.get("attempts")
    if isinstance(attempts, list) and attempts:
        attempt = attempts[-1]
        return attempt if isinstance(attempt, dict) else {}
    return {}


def _agent_step_result(
    *,
    request: ExecuteRecognitionPlanRequest,
    status: str,
    result: Optional[dict[str, Any]] = None,
    failure_reason: Optional[str] = None,
) -> dict[str, Any]:
    result = result or {}
    attempt = _latest_attempt(result)
    pre_action_state = attempt.get("pre_action_state") if isinstance(attempt.get("pre_action_state"), dict) else None
    post_click = result.get("post_click_verification")
    if not isinstance(post_click, dict):
        post_click = attempt.get("post_click_verification") if isinstance(attempt.get("post_click_verification"), dict) else {}
    semantic_post_click = result.get("semantic_post_click_verification")
    if not isinstance(semantic_post_click, dict):
        semantic_post_click = (
            attempt.get("semantic_post_click_verification")
            if isinstance(attempt.get("semantic_post_click_verification"), dict)
            else {}
        )
    overlay = result.get("recognition_plan_overlay") if isinstance(result.get("recognition_plan_overlay"), dict) else {}
    guidance = result.get("agent_execution_guidance") if isinstance(result.get("agent_execution_guidance"), dict) else {}
    execution_path = result.get("execution_path") if isinstance(result.get("execution_path"), dict) else {}
    selected_point = result.get("selected_click_point")
    if selected_point is None:
        selected_point = attempt.get("click_point")
    return {
        "contract_version": "agent_step_result_v1",
        "agent_mode": request.agent_mode,
        "goal": request.goal,
        "status": status,
        "dry_run": bool(request.dry_run),
        "action_executed": bool(execution_path.get("action_executed") or attempt.get("click_result")),
        "failure_reason": failure_reason,
        "approved_plan_id": result.get("approved_plan_id") or request.approved_plan_id,
        "selected_click_point": selected_point,
        "pre_click_allowed": bool((result.get("pre_click_decision") or {}).get("allowed")),
        "evidence": {
            "input_image_path": _image_path_from(result.get("image_path")),
            "live_capture_image_path": _image_path_from(result.get("live_capture")),
            "recognition_plan_trace_path": _image_path_from(result.get("recognition_plan_trace_path")),
            "coordinate_overlay_path": _image_path_from(overlay.get("output_path") or overlay.get("overlay_path")),
            "action_trace_path": _image_path_from(result.get("trace_path")),
        },
        "post_click": {
            "enabled": bool(request.enable_post_click_verification and not request.dry_run),
            "verified": post_click.get("verified"),
            "before_image_path": _image_path_from(pre_action_state) or _image_path_from(post_click.get("before")),
            "after_image_path": _image_path_from(post_click.get("after")),
            "diff_image_path": _image_path_from(post_click.get("diff")),
            "verification_basis": post_click.get("verification_basis"),
        },
        "semantic_post_click": {
            "applicable": bool(semantic_post_click.get("applicable")),
            "verified": semantic_post_click.get("verified"),
            "reason": semantic_post_click.get("reason") or semantic_post_click.get("failure_reason"),
        },
        "final_submit_guard": result.get("final_submit_guard"),
        "next_agent_action": guidance.get("next_action") or "inspect_trace",
        "fallback_plan": result.get("fallback_plan"),
    }


def _execute_fallback_plan(
    *,
    request: ExecuteRecognitionPlanRequest,
    failure_reason: str,
    plan: Optional[dict[str, Any]] = None,
    pre_click: Optional[dict[str, Any]] = None,
    attempts: Optional[list[dict[str, Any]]] = None,
    error: Any = None,
) -> dict[str, Any]:
    pre_click = pre_click or {}
    plan = plan or {}
    attempts = attempts or []
    reasons = [str(item) for item in (pre_click.get("reasons") or [])]
    for decision in pre_click.get("candidate_decisions") or []:
        reasons.extend(str(item) for item in (decision.get("reasons") or []))
    reason_set = set(reasons)
    steps: list[dict[str, Any]] = []

    if reason_set & {"missing_local_ocr_text", "local_ocr_text_mismatch", "narrow_search_status:fallback"}:
        steps.append(
            {
                "name": "local_rescan_top_candidates",
                "endpoint": "POST /vision/recognition_plan",
                "scope": "top-k candidate crops",
                "reason": "local OCR evidence did not validate the selected candidate",
            }
        )
    if (plan.get("path_graph_recall") or {}).get("status") == "ready":
        steps.append(
            {
                "name": "path_graph_review",
                "endpoint": "POST /vision/locate_target",
                "scope": "recalled PathGraph candidates",
                "reason": "PathGraph recall was available and may need correction",
            }
        )
    candidate_summary = (plan.get("candidate_result") or {}).get("summary") if isinstance(plan.get("candidate_result"), dict) else {}
    returned_count = int(candidate_summary.get("returned_count") or 0) if isinstance(candidate_summary, dict) else 0
    if failure_reason in {"recognition_plan_failed", "pre_click_rejected"} and (
        returned_count == 0
        or "no_candidate_passed_pre_click_checks" in reason_set
        or "missing_candidate" in reason_set
    ):
        seek_context = " ".join(str(value or "") for value in [request.app_name, request.state_hint, request.goal]).casefold()
        seek_target = seek_scroll_target_for_goal(request.goal) if "seek" in seek_context else None
        suggested_request: dict[str, Any] = {
            "direction": "down",
            "wheel_clicks": 4,
            "dry_run": False,
            "enable_verification": True,
        }
        if seek_target is not None:
            suggested_request.update(
                {
                    "contract_version": "scroll_request_v2",
                    "scroll_scope": "container",
                    "target_pane": seek_target["target_pane"],
                    "target_container_id": seek_target["target_container_id"],
                    "reason": seek_target["reason"],
                    "expected_effect": {
                        "target_container_content_should_change": True,
                        "same_semantic_page_should_remain": True,
                        "non_target_panes_should_remain_mostly_stable": True,
                    },
                }
            )
        steps.append(
            {
                "name": "request_scroll",
                "endpoint": "POST /action/scroll",
                "scope": suggested_request.get("target_pane") or "current bound window",
                "reason": "visible information may be incomplete; scroll the relevant container before the next gated attempt",
                "suggested_request": suggested_request,
                "next_after_success": {
                    "endpoint": "POST /action/execute_recognition_plan",
                    "reason": "rerun the same goal after the scroll produces a new screenshot/state",
                },
                "safety": {
                    "auto_click_allowed": False,
                    "scroll_is_click_permission": False,
                    "must_rerun_pre_click_decision": True,
                },
            }
        )
    if failure_reason in {"recognition_plan_failed", "pre_click_rejected"}:
        steps.append(
            {
                "name": "full_ocr_refresh",
                "endpoint": "POST /vision/recognition_plan",
                "scope": "full screenshot",
                "reason": "refresh OCR/page structure before another gated attempt",
            }
        )
    if failure_reason in {"post_click_verification_failed", "semantic_post_click_verification_failed", "recognition_plan_click_failed"}:
        steps.append(
            {
                "name": "post_click_state_observe",
                "endpoint": "POST /vision/observe_screen",
                "scope": "current bound window",
                "reason": "verify the actual post-click state before retrying",
            }
        )
    steps.append(
        {
            "name": "model_reground",
            "endpoint": "POST /vision/recognition_plan",
            "scope": "gated no-click plan",
            "reason": "fallback attempts must return through pre_click_decision_v1",
        }
    )

    return {
        "contract_version": "execute_fallback_plan_v1",
        "status": "planned",
        "failure_reason": failure_reason,
        "goal": request.goal,
        "error": error,
        "pre_click_reasons": sorted(set(reasons)),
        "attempt_count": len(attempts),
        "steps": steps,
        "safety": {
            "auto_click_allowed": False,
            "must_pass_pre_click_gate": True,
            "execute_endpoint": "POST /action/execute_recognition_plan",
        },
    }


def _save_execute_transition_memory(
    *,
    request: ExecuteRecognitionPlanRequest,
    bound: Any,
    base_result: dict[str, Any],
    verified: bool,
) -> dict[str, Any]:
    if not _element_memory_enabled(request):
        return {
            "contract_version": "execute_transition_memory_v1",
            "status": "disabled_by_write_policy",
            "write_policy_element_memory": False,
        }
    if not verified or bound is None or request.dry_run:
        return {
            "contract_version": "execute_transition_memory_v1",
            "status": "not_written",
            "write_policy_element_memory": True,
            "reason": "requires_verified_real_click_with_bound_window",
        }

    plan = base_result.get("recognition_plan") if isinstance(base_result.get("recognition_plan"), dict) else {}
    pre_click = base_result.get("pre_click_decision") if isinstance(base_result.get("pre_click_decision"), dict) else {}
    selected_candidate_id = pre_click.get("selected_candidate_id") or ((plan.get("pre_click_decision") or {}).get("selected_candidate_id") if isinstance(plan.get("pre_click_decision"), dict) else None)
    state_match = ((plan.get("path_graph_recall") or {}).get("state_match") or {}) if isinstance(plan.get("path_graph_recall"), dict) else {}
    from_state_id = str(state_match.get("state_id") or request.state_hint or request.app_name or "unknown_state")
    transition_id = f"exec-{uuid.uuid4().hex}"
    confidence_values = [
        float(item.get("confidence") or 0.0)
        for item in (base_result.get("attempts") or [])
        if isinstance(item, dict)
    ]
    confidence = max(confidence_values, default=1.0 if verified else 0.0)
    record = TransitionRecord(
        transition_id=transition_id,
        from_state_id=from_state_id,
        action_id=str(selected_candidate_id or request.goal),
        to_state_id=None,
        success_type="verified_click",
        confidence=confidence,
        evidence={
            "contract_version": "execute_transition_evidence_v1",
            "goal": request.goal,
            "app_name": request.app_name,
            "bound_window": _bound_window_snapshot(bound),
            "image_path": base_result.get("image_path"),
            "recognition_plan_trace_path": base_result.get("recognition_plan_trace_path"),
            "action_trace_path": base_result.get("trace_path"),
            "selected_click_point": base_result.get("selected_click_point"),
            "selected_candidate_id": selected_candidate_id,
            "click_result": base_result.get("click_result"),
            "post_click_verification": base_result.get("post_click_verification"),
            "semantic_post_click_verification": base_result.get("semantic_post_click_verification"),
            "attempt_count": len(base_result.get("attempts") or []),
            "path_graph_recall": plan.get("path_graph_recall") if isinstance(plan, dict) else None,
        },
        side_effects=["real_click_dispatched"],
        case_path=base_result.get("trace_path"),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    path = transition_memory.save(record)
    return {
        "contract_version": "execute_transition_memory_v1",
        "status": "written",
        "write_policy_element_memory": True,
        "transition_id": transition_id,
        "transition_path": path,
        "from_state_id": from_state_id,
        "action_id": record.action_id,
    }


def _save_approved_plan(
    *,
    request: ExecuteRecognitionPlanRequest,
    bound: Any,
    image_path: str,
    live_capture: Optional[dict[str, Any]],
    plan: dict[str, Any],
    pre_click: dict[str, Any],
    selected_point: dict[str, Any],
    plan_trace_path: Optional[str],
    overlay: Optional[dict[str, Any]],
) -> dict[str, Any]:
    approved_plan_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(seconds=APPROVED_PLAN_TTL_SECONDS)
    bound_window = _bound_window_snapshot(bound)
    coordinate_window_size = _coordinate_size_from_live_capture(live_capture) or _size_from_rect(bound_window.get("rect") or {})
    record = {
        "contract_version": "approved_recognition_plan_v1",
        "approved_plan_id": approved_plan_id,
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_seconds": APPROVED_PLAN_TTL_SECONDS,
        "goal": request.goal,
        "task": request.task,
        "app_name": request.app_name,
        "state_hint": request.state_hint,
        "provider_mode": request.provider_mode,
        "top_k": request.top_k,
        "request_metadata": request.metadata,
        "bound_window": bound_window,
        "coordinate_window_size": coordinate_window_size,
        "image_path": image_path,
        "live_capture": live_capture,
        "recognition_plan": plan,
        "recognition_plan_trace_path": plan_trace_path,
        "recognition_plan_overlay": overlay,
        "pre_click_decision": pre_click,
        "selected_click_point": selected_point,
    }
    path = _approved_plan_path(approved_plan_id)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "approved_plan_id": approved_plan_id,
        "approved_plan_path": str(path.resolve()),
        "expires_at": expires_at.isoformat(),
        "ttl_seconds": APPROVED_PLAN_TTL_SECONDS,
    }


def _load_approved_plan(approved_plan_id: str) -> dict[str, Any]:
    path = _approved_plan_path(approved_plan_id)
    if not path.exists():
        raise ValueError(f"approved_plan_id not found: {approved_plan_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("contract_version") != "approved_recognition_plan_v1":
        raise ValueError("approved plan has an invalid contract")
    return payload


def _validate_approved_plan_reuse(
    *,
    request: ExecuteRecognitionPlanRequest,
    bound: Any,
    record: dict[str, Any],
    selected_point: dict[str, Any],
) -> dict[str, Any]:
    expires_at = datetime.fromisoformat(str(record.get("expires_at")))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if now > expires_at:
        raise ValueError("approved_plan_expired")
    if request.goal != record.get("goal"):
        raise ValueError("approved_plan_goal_mismatch")

    current_window = _bound_window_snapshot(bound)
    approved_window = record.get("bound_window") if isinstance(record.get("bound_window"), dict) else {}
    if int(current_window.get("handle") or 0) != int(approved_window.get("handle") or 0):
        raise ValueError("approved_plan_window_handle_mismatch")

    current_rect = current_window.get("rect") or {}
    current_size = _size_from_rect(current_rect)
    approved_size = _record_coordinate_window_size(record)
    if current_size != approved_size:
        raise ValueError("approved_plan_window_size_mismatch")

    if not _point_in_rect(selected_point, {"x": 0, "y": 0, "width": current_size["width"] - 1, "height": current_size["height"] - 1}):
        raise ValueError("approved_plan_point_outside_window")

    return {
        "contract_version": "approved_plan_reuse_validation_v1",
        "approved_plan_id": record.get("approved_plan_id"),
        "valid": True,
        "checked_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "current_window": current_window,
        "approved_window": approved_window,
        "current_coordinate_window_size": current_size,
        "approved_coordinate_window_size": approved_size,
        "selected_click_point": selected_point,
    }


def _copy_learning_file(source: Any, destination: Path, *, missing_sources: list[str]) -> Optional[str]:
    if not source:
        return None
    source_path = Path(str(source))
    if not source_path.exists() or not source_path.is_file():
        missing_sources.append(str(source_path))
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)
    return str(destination.resolve())


def _learning_target_bbox(plan: dict[str, Any], selected_point: dict[str, Any]) -> dict[str, int]:
    target_bbox = target_bbox_from_recommended(plan.get("recommended_target") or {})
    if target_bbox is not None:
        return target_bbox
    x = int(selected_point.get("x", 0))
    y = int(selected_point.get("y", 0))
    return {"x": max(0, x - 48), "y": max(0, y - 48), "width": 96, "height": 96}


def _crop_learning_target(
    *,
    source_image_path: Any,
    destination: Path,
    target_bbox: dict[str, int],
    missing_sources: list[str],
) -> Optional[str]:
    if Image is None:
        return None
    if not source_image_path:
        return None
    source_path = Path(str(source_image_path))
    if not source_path.exists() or not source_path.is_file():
        missing_sources.append(str(source_path))
        return None
    try:
        with Image.open(source_path) as image:
            width, height = image.size
            x1 = max(0, int(target_bbox["x"]))
            y1 = max(0, int(target_bbox["y"]))
            x2 = min(width, x1 + max(1, int(target_bbox["width"])))
            y2 = min(height, y1 + max(1, int(target_bbox["height"])))
            if x2 <= x1 or y2 <= y1:
                return None
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.crop((x1, y1, x2, y2)).save(destination)
            return str(destination.resolve())
    except Exception:
        return None


def _persist_learned_instruction_assets(
    *,
    learned_instruction_id: str,
    bundle_dir: Path,
    image_path: str,
    plan: dict[str, Any],
    selected_point: dict[str, Any],
    post_click_verification: dict[str, Any],
) -> dict[str, Any]:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    missing_sources: list[str] = []
    before_path = ((post_click_verification.get("before") or {}).get("image_path"))
    after_path = ((post_click_verification.get("after") or {}).get("image_path"))
    diff_path = ((post_click_verification.get("diff") or {}).get("diff_image_path"))
    target_bbox = _learning_target_bbox(plan, selected_point)
    source_for_crop = before_path or image_path

    assets = {
        "contract_version": "learned_instruction_artifacts_v1",
        "learned_instruction_id": learned_instruction_id,
        "bundle_dir": str(bundle_dir.resolve()),
        "source_image_path": _copy_learning_file(image_path, bundle_dir / "source_window.png", missing_sources=missing_sources),
        "pre_action_image_path": _copy_learning_file(before_path, bundle_dir / "pre_action.png", missing_sources=missing_sources),
        "post_action_image_path": _copy_learning_file(after_path, bundle_dir / "post_action.png", missing_sources=missing_sources),
        "diff_image_path": _copy_learning_file(diff_path, bundle_dir / "post_action_diff.png", missing_sources=missing_sources),
        "target_crop_path": _crop_learning_target(
            source_image_path=source_for_crop,
            destination=bundle_dir / "target_crop.png",
            target_bbox=target_bbox,
            missing_sources=missing_sources,
        ),
        "target_bbox": target_bbox,
        "selected_click_point": selected_point,
        "missing_sources": sorted(set(missing_sources)),
    }
    return assets


def _save_learned_instruction(
    *,
    request: ExecuteRecognitionPlanRequest,
    bound: Any,
    image_path: str,
    live_capture: Optional[dict[str, Any]],
    plan: dict[str, Any],
    pre_click: dict[str, Any],
    selected_point: dict[str, Any],
    click_result: dict[str, Any],
    post_click_verification: dict[str, Any],
    semantic_post_click_verification: dict[str, Any],
    plan_trace_path: Optional[str],
    action_trace_path: Optional[str],
) -> dict[str, Any]:
    learned_instruction_id = new_learned_instruction_id()
    created_at = datetime.now(timezone.utc)
    path = _learned_instruction_path(learned_instruction_id)
    bundle_dir = path.parent
    bound_window = _bound_window_snapshot(bound)
    coordinate_window_size = _coordinate_size_from_live_capture(live_capture) or _size_from_rect(bound_window.get("rect") or {})
    learning_artifacts = _persist_learned_instruction_assets(
        learned_instruction_id=learned_instruction_id,
        bundle_dir=bundle_dir,
        image_path=image_path,
        plan=plan,
        selected_point=selected_point,
        post_click_verification=post_click_verification,
    )
    record = {
        "contract_version": "learned_instruction_v1",
        "learned_instruction_id": learned_instruction_id,
        "created_at": created_at.isoformat(),
        "instruction": {
            "original": request.goal,
            "normalized": request.goal,
        },
        "task": request.task,
        "app_name": request.app_name,
        "state_hint": request.state_hint,
        "provider_mode": request.provider_mode,
        "top_k": request.top_k,
        "request_metadata": request.metadata,
        "bound_window": bound_window,
        "coordinate_window_size": coordinate_window_size,
        "image_path": image_path,
        "live_capture": live_capture,
        "learning_artifacts": learning_artifacts,
        "recognition_plan": plan,
        "recognition_plan_trace_path": plan_trace_path,
        "action_trace_path": action_trace_path,
        "pre_click_decision": pre_click,
        "selected_click_point": selected_point,
        "click_result": click_result,
        "post_click_verification": post_click_verification,
        "semantic_post_click_verification": semantic_post_click_verification,
        "reuse_policy": {
            "mode": "same_window_exact",
            "match_goal": True,
            "match_app_name": True,
            "match_window_handle": True,
            "match_window_size": True,
            "fallback_to_model": True,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "learned_instruction_id": learned_instruction_id,
        "learned_instruction_path": str(path.resolve()),
        "learned_instruction_bundle_dir": str(path.parent.resolve()),
        "learned_instruction_artifacts": learning_artifacts,
        "learning_mode": "instruction",
    }


def _update_learned_instruction_action_trace(base_result: dict[str, Any]) -> None:
    learned_path = base_result.get("learned_instruction_path")
    action_trace_path = base_result.get("trace_path")
    if not learned_path or not action_trace_path:
        return
    path = Path(str(learned_path))
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return
    payload["action_trace_path"] = action_trace_path
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_execute_transition_action_trace(base_result: dict[str, Any]) -> None:
    writeback = base_result.get("element_memory_writeback")
    action_trace_path = base_result.get("trace_path")
    if not isinstance(writeback, dict) or not action_trace_path:
        return
    writeback["action_trace_path"] = action_trace_path
    transition_path = writeback.get("transition_path")
    if not transition_path:
        return
    path = Path(str(transition_path))
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {}
        payload["evidence"] = evidence
    evidence["action_trace_path"] = action_trace_path
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _rewrite_execute_trace_result(*, trace_path: Optional[str], success: bool, request: ExecuteRecognitionPlanRequest, result: dict[str, Any]) -> None:
    if not trace_path:
        return
    path = Path(str(trace_path))
    if not path.exists():
        return
    payload = {"success": success, "request": request.model_dump(), "result": result}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_learned_instruction(learned_instruction_id: str) -> dict[str, Any]:
    path = _learned_instruction_path(learned_instruction_id)
    if not path.exists():
        raise ValueError(f"learned_instruction_id not found: {learned_instruction_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("contract_version") != "learned_instruction_v1":
        raise ValueError("learned instruction has an invalid contract")
    return payload


def _validate_learned_instruction_reuse(
    *,
    request: ExecuteRecognitionPlanRequest,
    bound: Any,
    record: dict[str, Any],
    selected_point: dict[str, Any],
) -> dict[str, Any]:
    instruction = record.get("instruction") if isinstance(record.get("instruction"), dict) else {}
    if request.goal != instruction.get("original"):
        raise ValueError("learned_instruction_goal_mismatch")
    if request.app_name and record.get("app_name") and request.app_name != record.get("app_name"):
        raise ValueError("learned_instruction_app_mismatch")

    current_window = _bound_window_snapshot(bound)
    learned_window = record.get("bound_window") if isinstance(record.get("bound_window"), dict) else {}
    if int(current_window.get("handle") or 0) != int(learned_window.get("handle") or 0):
        raise ValueError("learned_instruction_window_handle_mismatch")

    current_rect = current_window.get("rect") or {}
    current_size = _size_from_rect(current_rect)
    learned_size = _record_coordinate_window_size(record)
    if current_size != learned_size:
        raise ValueError("learned_instruction_window_size_mismatch")

    if not _point_in_rect(selected_point, {"x": 0, "y": 0, "width": current_size["width"] - 1, "height": current_size["height"] - 1}):
        raise ValueError("learned_instruction_point_outside_window")

    return {
        "contract_version": "learned_instruction_reuse_validation_v1",
        "learned_instruction_id": record.get("learned_instruction_id"),
        "valid": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "reuse_policy": record.get("reuse_policy"),
        "current_window": current_window,
        "learned_window": learned_window,
        "current_coordinate_window_size": current_size,
        "learned_coordinate_window_size": learned_size,
        "selected_click_point": selected_point,
    }


@router.post("/execute_recognition_plan", response_model=APIResponse)
def execute_recognition_plan(request: ExecuteRecognitionPlanRequest) -> APIResponse:
    timer = RuntimeTimer()
    bound = window_manager.get_bound_window()
    live_capture: Optional[dict[str, Any]] = None

    def attach_timings(result: dict[str, Any]) -> dict[str, Any]:
        result["timings"] = timer.to_dict()
        return result

    if request.approved_plan_id and request.dry_run:
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="approved_plan_id can only be used for real execution",
            data={"approved_plan_id": request.approved_plan_id, "timings": timings},
            error=ErrorModel(code="approved_plan_dry_run_not_allowed", details="First create the approved plan with dry_run=true, then reuse it with dry_run=false"),
        )

    if request.approved_plan_id and request.learned_instruction_id:
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="Only one reuse source can be selected",
            data={"approved_plan_id": request.approved_plan_id, "learned_instruction_id": request.learned_instruction_id, "timings": timings},
            error=ErrorModel(code="reuse_source_conflict", details="Use either approved_plan_id or learned_instruction_id, not both"),
        )

    learned_instruction_reuse_validation: dict[str, Any] | None = None
    learned_record: dict[str, Any] | None = None
    if request.learned_instruction_id:
        if bound is None:
            timings = timer.to_dict()
            return APIResponse(
                success=False,
                message="No bound window is currently available",
                data={"timings": timings},
                error=ErrorModel(
                    code="no_bound_window",
                    details="Bind the target window before reusing a learned instruction",
                ),
            )
        try:
            with timer.step("load_learned_instruction"):
                learned_record = _load_learned_instruction(request.learned_instruction_id)
            plan = learned_record["recognition_plan"]
            pre_click = learned_record.get("pre_click_decision") or {}
            selected_point = learned_record.get("selected_click_point")
            if not isinstance(selected_point, dict):
                raise ValueError("learned_instruction_missing_selected_click_point")
            with timer.step("validate_learned_instruction_reuse"):
                learned_instruction_reuse_validation = _validate_learned_instruction_reuse(
                    request=request,
                    bound=bound,
                    record=learned_record,
                    selected_point=selected_point,
                )
            image_path = str(learned_record.get("image_path") or "")
            live_capture = learned_record.get("live_capture") if isinstance(learned_record.get("live_capture"), dict) else None
            plan_trace_path = learned_record.get("recognition_plan_trace_path") or plan.get("trace_path")
            overlay = None
        except Exception as exc:
            timings = timer.to_dict()
            trace_path = _write_execute_trace_if_enabled(
                request,
                category="actions",
                operation="execute_recognition_plan",
                payload={
                    "success": False,
                    "request": request.model_dump(),
                    "learned_instruction_id": request.learned_instruction_id,
                    "failure_reason": "learned_instruction_reuse_failed",
                    "error": str(exc),
                    "timings": timings,
                },
                name_hint=request.app_name or "recognition_plan",
            )
            return APIResponse(
                success=False,
                message="Learned instruction could not be reused",
                data={"trace_path": trace_path, "learned_instruction_id": request.learned_instruction_id, "timings": timings},
                error=ErrorModel(code="learned_instruction_reuse_failed", details=str(exc)),
            )
        execution_path = {
            "vision_model_used": False,
            "page_structure_used": False,
            "candidate_rank_used": False,
            "narrow_search_used": False,
            "pre_click_decision_used": True,
            "post_click_verification_used": bool(request.enable_post_click_verification and not request.dry_run),
            "coordinate_source": "learned_instruction_v1.selected_click_point",
            "selection_source": "learned_instruction_v1",
            "approved_plan_reused": False,
            "recognition_plan_reused": True,
            "instruction_learning_reused": True,
            "action_executed": False,
            "dry_run": bool(request.dry_run),
            "retry_policy_used": True,
            "max_execution_attempts": int(request.max_execution_attempts),
        }
    approval_reuse_validation: dict[str, Any] | None = None
    if request.approved_plan_id:
        if bound is None:
            timings = timer.to_dict()
            return APIResponse(
                success=False,
                message="No bound window is currently available",
                data={"timings": timings},
                error=ErrorModel(
                    code="no_bound_window",
                    details="Bind the target window before reusing an approved recognition plan",
                ),
            )
        try:
            with timer.step("load_approved_plan"):
                approved_record = _load_approved_plan(request.approved_plan_id)
            plan = approved_record["recognition_plan"]
            pre_click = approved_record.get("pre_click_decision") or {}
            selected_point = approved_record.get("selected_click_point")
            if not isinstance(selected_point, dict):
                raise ValueError("approved_plan_missing_selected_click_point")
            with timer.step("validate_approved_plan_reuse"):
                approval_reuse_validation = _validate_approved_plan_reuse(
                    request=request,
                    bound=bound,
                    record=approved_record,
                    selected_point=selected_point,
                )
            image_path = str(approved_record.get("image_path") or "")
            live_capture = approved_record.get("live_capture") if isinstance(approved_record.get("live_capture"), dict) else None
            plan_trace_path = approved_record.get("recognition_plan_trace_path") or plan.get("trace_path")
            overlay = approved_record.get("recognition_plan_overlay") if isinstance(approved_record.get("recognition_plan_overlay"), dict) else None
        except Exception as exc:
            timings = timer.to_dict()
            trace_path = _write_execute_trace_if_enabled(
                request,
                category="actions",
                operation="execute_recognition_plan",
                payload={
                    "success": False,
                    "request": request.model_dump(),
                    "approved_plan_id": request.approved_plan_id,
                    "failure_reason": "approved_plan_reuse_failed",
                    "error": str(exc),
                    "timings": timings,
                },
                name_hint=request.app_name or "recognition_plan",
            )
            return APIResponse(
                success=False,
                message="Approved recognition plan could not be reused",
                data={"trace_path": trace_path, "approved_plan_id": request.approved_plan_id, "timings": timings},
                error=ErrorModel(code="approved_plan_reuse_failed", details=str(exc)),
            )
        execution_path = {
            "vision_model_used": False,
            "page_structure_used": False,
            "candidate_rank_used": False,
            "narrow_search_used": False,
            "pre_click_decision_used": True,
            "post_click_verification_used": bool(request.enable_post_click_verification),
            "coordinate_source": "approved_plan_v1.selected_click_point",
            "selection_source": "approved_recognition_plan_v1",
            "approved_plan_reused": True,
            "recognition_plan_reused": True,
            "action_executed": False,
            "dry_run": False,
            "retry_policy_used": True,
            "max_execution_attempts": int(request.max_execution_attempts),
        }
    elif not request.learned_instruction_id:
        if request.capture_live:
            if bound is None:
                timings = timer.to_dict()
                return APIResponse(
                    success=False,
                    message="No bound window is currently available",
                    data={"timings": timings},
                    error=ErrorModel(
                        code="no_bound_window",
                        details="Bind the MouseTester window before calling /action/execute_recognition_plan with live capture",
                    ),
                )
            bound_validation = _bound_window_matches_request(bound, request)
            if not bound_validation.get("valid"):
                timings = timer.to_dict()
                trace_path = _write_execute_trace_if_enabled(
                    request,
                    category="actions",
                    operation="execute_recognition_plan",
                    payload={
                        "success": False,
                        "request": request.model_dump(),
                        "failure_reason": "bound_window_mismatch",
                        "bound_window_validation": bound_validation,
                        "timings": timings,
                    },
                    name_hint=request.app_name or "recognition_plan",
                )
                return APIResponse(
                    success=False,
                    message="Bound window does not match requested app",
                    data={"trace_path": trace_path, "bound_window_validation": bound_validation, "timings": timings},
                    error=ErrorModel(code="bound_window_mismatch", details=bound_validation),
                )
            try:
                with timer.step("capture_live_window"):
                    live_capture = screenshot_service.capture_window(
                        save_image=True,
                        purpose="recognition_plan_execution",
                        name_hint=request.app_name or "recognition_plan",
                    )
            except Exception as exc:
                timings = timer.to_dict()
                trace_path = _write_execute_trace_if_enabled(
                    request,
                    category="actions",
                    operation="execute_recognition_plan",
                    payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
                    name_hint=request.app_name or "recognition_plan",
                )
                return APIResponse(
                    success=False,
                    message="Live capture failed",
                    data={"trace_path": trace_path, "timings": timings},
                    error=ErrorModel(code="live_capture_failed", details=str(exc)),
                )
            image_path = str(Path(str(live_capture["image_path"])).resolve())
        elif request.image_path:
            with timer.step("use_saved_image_source"):
                image_path = request.image_path
            if not request.allow_saved_image_execution and not request.dry_run:
                timings = timer.to_dict()
                trace_path = _write_execute_trace_if_enabled(
                    request,
                    category="actions",
                    operation="execute_recognition_plan",
                    payload={
                        "success": False,
                        "request": request.model_dump(),
                        "failure_reason": "saved_image_execution_not_allowed",
                        "timings": timings,
                    },
                    name_hint=request.app_name or "recognition_plan",
                )
                return APIResponse(
                    success=False,
                    message="Saved-image execution requires explicit override",
                    data={"trace_path": trace_path, "timings": timings},
                    error=ErrorModel(
                        code="saved_image_execution_not_allowed",
                        details="Use capture_live=true, dry_run=true, or allow_saved_image_execution=true",
                    ),
                )
        else:
            timings = timer.to_dict()
            return APIResponse(
                success=False,
                message="No screenshot source provided",
                data={"timings": timings},
                error=ErrorModel(code="missing_image_source", details="Provide image_path or set capture_live=true"),
            )

        effective_provider_mode, effective_metadata = _execute_plan_request_defaults(request)
        plan_request = VisionRecognitionPlanRequestModel(
            image_path=image_path,
            task=request.task,
            app_name=request.app_name,
            goal=request.goal,
            state_hint=request.state_hint,
            provider_mode=effective_provider_mode,
            agent_mode=request.agent_mode,
            learn_depth=request.learn_depth,
            write_policy=request.write_policy,
            metadata=effective_metadata,
            top_k=request.top_k,
            observe_trace_path=request.observe_trace_path,
        )
        with timer.step("recognition_plan"):
            plan_response = _run_recognition_plan_for_execution(plan_request)
        if not plan_response.success or not plan_response.data:
            timings = timer.to_dict()
            fallback_plan = _execute_fallback_plan(
                request=request,
                failure_reason="recognition_plan_failed",
                error=plan_response.error.model_dump() if plan_response.error else None,
            )
            failed_result: dict[str, Any] = {
                "contract_version": "execute_recognition_plan_v1",
                "agent_mode": request.agent_mode,
                "learn_depth": request.learn_depth,
                "goal": request.goal,
                "image_path": image_path,
                "live_capture": live_capture,
                "recognition_plan_response": plan_response.model_dump(),
                "fallback_plan": fallback_plan,
            }
            failed_result["agent_execution_guidance"] = _agent_execution_guidance(
                request=request,
                status="blocked",
                result=failed_result,
                failure_reason="recognition_plan_failed",
            )
            failed_result["agent_step_result"] = _agent_step_result(
                request=request,
                status="blocked",
                result=failed_result,
                failure_reason="recognition_plan_failed",
            )
            failed_result["timings"] = timings
            trace_path = _write_execute_trace_if_enabled(
                request,
                category="actions",
                operation="execute_recognition_plan",
                payload={
                    "success": False,
                    "request": request.model_dump(),
                    "result": failed_result,
                    "failure_reason": "recognition_plan_failed",
                },
                name_hint=request.app_name or "recognition_plan",
            )
            failed_result["trace_path"] = trace_path
            failed_result["agent_step_result"] = _agent_step_result(
                request=request,
                status="blocked",
                result=failed_result,
                failure_reason="recognition_plan_failed",
            )
            _rewrite_execute_trace_result(trace_path=trace_path, success=False, request=request, result=failed_result)
            return APIResponse(
                success=False,
                message="Recognition plan failed",
                data={
                    "trace_path": trace_path,
                    "recognition_plan_response": plan_response.model_dump(),
                    "fallback_plan": fallback_plan,
                    "agent_execution_guidance": failed_result["agent_execution_guidance"],
                    "agent_step_result": failed_result["agent_step_result"],
                    "timings": timings,
                },
                error=ErrorModel(code="recognition_plan_failed", details=plan_response.error.model_dump() if plan_response.error else None),
            )

        plan = plan_response.data["result"]
        pre_click = plan.get("pre_click_decision") or {}
        selected_point = _extract_action_point(plan)
        plan_trace_path = plan.get("trace_path")
        low_risk_visual_fast_lane = _low_risk_visual_fast_lane_profile(
            request=request,
            plan=plan,
            pre_click=pre_click,
            selected_point=selected_point,
        )
        should_render_overlay = _should_render_recognition_overlay_for_execution(
            request=request,
            low_risk_visual_fast_lane=low_risk_visual_fast_lane,
        )
        with timer.step(
            "render_recognition_plan_overlay",
            has_plan_trace=bool(plan_trace_path),
            enabled=bool(should_render_overlay),
        ):
            overlay = _render_recognition_plan_overlay_for_execution(plan_trace_path) if plan_trace_path and should_render_overlay else None
        execution_path = {
            "vision_model_used": bool((plan.get("execution_path") or {}).get("vision_model_used")),
            "page_structure_used": True,
            "candidate_rank_used": True,
            "narrow_search_used": True,
            "pre_click_decision_used": True,
            "post_click_verification_used": bool(request.enable_post_click_verification and not request.dry_run),
            "coordinate_source": "pre_click_decision_v1.selected_click_point",
            "selection_source": "recognition_plan_v1",
            "approved_plan_reused": False,
            "recognition_plan_reused": False,
            "action_executed": False,
            "dry_run": bool(request.dry_run),
            "retry_policy_used": True,
            "max_execution_attempts": int(request.max_execution_attempts),
            "low_risk_visual_fast_lane": low_risk_visual_fast_lane,
            "recognition_plan_overlay_rendered": bool(overlay),
        }

    if "low_risk_visual_fast_lane" not in locals():
        low_risk_visual_fast_lane = _low_risk_visual_fast_lane_profile(
            request=request,
            plan=plan,
            pre_click=pre_click,
            selected_point=selected_point,
        )
    click_timing = _click_timing_options(low_risk_visual_fast_lane=low_risk_visual_fast_lane)
    if isinstance(execution_path, dict):
        execution_path["low_risk_visual_fast_lane"] = low_risk_visual_fast_lane
        execution_path["click_timing_reason"] = click_timing["reason"]
        execution_path["recognition_plan_overlay_rendered"] = bool(overlay)

    base_result: dict[str, Any] = {
        "contract_version": "execute_recognition_plan_v1",
        "agent_mode": request.agent_mode,
        "learn_depth": request.learn_depth,
        "mode_contract_version": "execute_plan_v1" if request.agent_mode == "execute" else ("learn_screen_deep_v1" if request.learn_depth == "deep" else "learn_screen_fast_v1"),
        "write_policy": request.write_policy.model_dump(),
        "goal": request.goal,
        "image_path": image_path,
        "live_capture": live_capture,
        "recognition_plan": plan,
        "recognition_plan_trace_path": plan_trace_path,
        "recognition_plan_overlay": overlay,
        "pre_click_decision": pre_click,
        "selected_click_point": selected_point,
        "approved_plan_id": request.approved_plan_id,
        "approved_plan_reuse_validation": approval_reuse_validation,
        "learned_instruction_id": request.learned_instruction_id,
        "learning_mode": request.learning_mode,
        "learned_instruction_reuse_validation": learned_instruction_reuse_validation,
        "learned_instruction_artifacts": (learned_record.get("learning_artifacts") if isinstance(learned_record, dict) else None),
        "execution_path": execution_path,
        "effective_execution_options": {
            "provider_mode": plan_request.provider_mode if "plan_request" in locals() else request.provider_mode,
            "metadata": plan_request.metadata if "plan_request" in locals() else request.metadata,
            "click_timing": click_timing,
        },
    }

    base_result["final_submit_guard"] = _final_submit_guard_decision(
        request=request,
        plan=plan,
        pre_click=pre_click,
    )
    if not base_result["final_submit_guard"]["allowed"]:
        base_result["agent_execution_guidance"] = _agent_execution_guidance(
            request=request,
            status="blocked",
            result=base_result,
            failure_reason="final_submit_guard_rejected",
        )
        base_result["agent_step_result"] = _agent_step_result(
            request=request,
            status="blocked",
            result=base_result,
            failure_reason="final_submit_guard_rejected",
        )
        attach_timings(base_result)
        base_result["trace_path"] = _write_execute_trace_if_enabled(
            request,
            category="actions",
            operation="execute_recognition_plan",
            payload={
                "success": False,
                "request": request.model_dump(),
                "result": base_result,
                "failure_reason": "final_submit_guard_rejected",
            },
            name_hint=request.app_name or "recognition_plan",
        )
        base_result["agent_step_result"] = _agent_step_result(
            request=request,
            status="blocked",
            result=base_result,
            failure_reason="final_submit_guard_rejected",
        )
        _rewrite_execute_trace_result(trace_path=base_result.get("trace_path"), success=False, request=request, result=base_result)
        return APIResponse(
            success=False,
            message="Final submit guard blocked the selected target",
            data=base_result,
            error=ErrorModel(code="final_submit_guard_rejected", details=base_result["final_submit_guard"]),
        )

    if not pre_click.get("allowed") or selected_point is None:
        base_result["fallback_plan"] = _execute_fallback_plan(
            request=request,
            failure_reason="pre_click_rejected",
            plan=plan,
            pre_click=pre_click,
        )
        base_result["agent_execution_guidance"] = _agent_execution_guidance(
            request=request,
            status="blocked",
            result=base_result,
            failure_reason="pre_click_rejected",
        )
        base_result["agent_step_result"] = _agent_step_result(
            request=request,
            status="blocked",
            result=base_result,
            failure_reason="pre_click_rejected",
        )
        attach_timings(base_result)
        base_result["trace_path"] = _write_execute_trace_if_enabled(
            request,
            category="actions",
            operation="execute_recognition_plan",
            payload={
                "success": False,
                "request": request.model_dump(),
                "result": base_result,
                "failure_reason": "pre_click_rejected",
            },
            name_hint=request.app_name or "recognition_plan",
        )
        base_result["agent_step_result"] = _agent_step_result(
            request=request,
            status="blocked",
            result=base_result,
            failure_reason="pre_click_rejected",
        )
        _rewrite_execute_trace_result(trace_path=base_result.get("trace_path"), success=False, request=request, result=base_result)
        return APIResponse(
            success=False,
            message="Recognition plan was rejected before click",
            data=base_result,
            error=ErrorModel(code="pre_click_rejected", details=pre_click.get("reasons")),
        )

    if request.dry_run:
        if bound is not None and selected_point is not None:
            with timer.step("save_approved_plan"):
                approval = _save_approved_plan(
                    request=request,
                    bound=bound,
                    image_path=image_path,
                    live_capture=live_capture,
                    plan=plan,
                    pre_click=pre_click,
                    selected_point=selected_point,
                    plan_trace_path=plan_trace_path,
                    overlay=overlay,
                )
            base_result.update(approval)
            base_result["approved_plan_id"] = approval["approved_plan_id"]
        base_result["agent_execution_guidance"] = _agent_execution_guidance(
            request=request,
            status="dry_run_ready",
            result=base_result,
        )
        base_result["agent_step_result"] = _agent_step_result(
            request=request,
            status="dry_run_ready",
            result=base_result,
        )
        attach_timings(base_result)
        base_result["trace_path"] = _write_execute_trace_if_enabled(
            request,
            category="actions",
            operation="execute_recognition_plan",
            payload={"success": True, "request": request.model_dump(), "result": base_result},
            name_hint=request.app_name or "recognition_plan",
        )
        base_result["agent_step_result"] = _agent_step_result(
            request=request,
            status="dry_run_ready",
            result=base_result,
        )
        _rewrite_execute_trace_result(trace_path=base_result.get("trace_path"), success=True, request=request, result=base_result)
        data = ActionResultData(action="execute_recognition_plan", result=base_result)
        return APIResponse(success=True, message="Recognition plan accepted; dry run did not click", data=data.model_dump(), error=None)

    attempts: list[dict[str, Any]] = []
    final_attempt: dict[str, Any] | None = None
    try:
        for attempt_index in range(1, int(request.max_execution_attempts) + 1):
            with timer.step("execution_attempt", attempt=attempt_index):
                with timer.step("capture_pre_action_state", attempt=attempt_index, enabled=request.enable_post_click_verification):
                    before_state = (
                        verifier.capture_pre_action_state(action_name="execute_recognition_plan")
                        if request.enable_post_click_verification
                        else None
                    )
                with timer.step("click_point", attempt=attempt_index):
                    click_result = input_controller.click_point(
                        selected_point["x"],
                        selected_point["y"],
                        move_before_click=True,
                        settle_ms=int(click_timing["settle_ms"]),
                        hold_ms=int(click_timing["hold_ms"]),
                    )
                with timer.step("post_click_verification", attempt=attempt_index, enabled=request.enable_post_click_verification):
                    post_click_verification = (
                        verifier.verify_action(
                            "execute_recognition_plan",
                            before_state=before_state,
                            click_result=click_result,
                        )
                        if request.enable_post_click_verification
                        else {"verified": None, "verification_skipped": True}
                    )
                    post_click_verification = _apply_metadata_post_click_policy(request, post_click_verification)
                with timer.step(
                    "semantic_post_click_verification",
                    attempt=attempt_index,
                    enabled=request.enable_post_click_verification and should_verify_mouse_tester_semantics(request=request, plan=plan),
                ):
                    semantic_post_click_verification = (
                        verify_mouse_tester_post_click_semantics(
                            request=request,
                            plan=plan,
                            generic_verification=post_click_verification,
                        )
                        if request.enable_post_click_verification and should_verify_mouse_tester_semantics(request=request, plan=plan)
                        else {"applicable": False, "verified": None, "verification_skipped": True}
                    )
                attempt_verified = _execution_attempt_verified(
                    request=request,
                    post_click_verification=post_click_verification,
                    semantic_post_click_verification=semantic_post_click_verification,
                )
                retry_allowed, retry_reason = _retry_allowed_after_attempt(
                    request=request,
                    pre_click=pre_click,
                    attempt_index=attempt_index,
                    attempt_verified=attempt_verified,
                )
            attempt = {
                "attempt": attempt_index,
                "pre_action_state": before_state,
                "click_point": selected_point,
                "click_result": click_result,
                "post_click_verification": post_click_verification,
                "semantic_post_click_verification": semantic_post_click_verification,
                "verified": attempt_verified,
                "retry_allowed": retry_allowed,
                "retry_reason": retry_reason,
            }
            attempts.append(attempt)
            final_attempt = attempt
            if attempt_verified or not retry_allowed:
                break
    except Exception as exc:
        base_result["execution_path"]["action_executed"] = bool(attempts)
        base_result["attempts"] = attempts
        base_result["fallback_plan"] = _execute_fallback_plan(
            request=request,
            failure_reason="recognition_plan_click_failed",
            plan=plan,
            pre_click=pre_click,
            attempts=attempts,
            error=str(exc),
        )
        base_result["agent_execution_guidance"] = _agent_execution_guidance(
            request=request,
            status="execution_failed",
            result=base_result,
            failure_reason="recognition_plan_click_failed",
        )
        base_result["agent_step_result"] = _agent_step_result(
            request=request,
            status="execution_failed",
            result=base_result,
            failure_reason="recognition_plan_click_failed",
        )
        attach_timings(base_result)
        base_result["trace_path"] = _write_execute_trace_if_enabled(
            request,
            category="actions",
            operation="execute_recognition_plan",
            payload={
                "success": False,
                "request": request.model_dump(),
                "result": base_result,
                "error": str(exc),
            },
            name_hint=request.app_name or "recognition_plan",
        )
        base_result["agent_step_result"] = _agent_step_result(
            request=request,
            status="execution_failed",
            result=base_result,
            failure_reason="recognition_plan_click_failed",
        )
        _rewrite_execute_trace_result(trace_path=base_result.get("trace_path"), success=False, request=request, result=base_result)
        return APIResponse(
            success=False,
            message="Recognition-plan click failed",
            data=base_result,
            error=ErrorModel(code="recognition_plan_click_failed", details=str(exc)),
        )

    final_attempt = final_attempt or {}
    verified = bool(final_attempt.get("verified"))
    post_click_verification = final_attempt.get("post_click_verification") or {}
    semantic_post_click_verification = final_attempt.get("semantic_post_click_verification") or {}
    click_result = final_attempt.get("click_result") or {}
    base_result.update(
        {
            "click_result": click_result,
            "post_click_verification": post_click_verification,
            "semantic_post_click_verification": semantic_post_click_verification,
            "attempts": attempts,
        }
    )
    base_result["execution_path"]["action_executed"] = bool(attempts)
    base_result["execution_path"]["execution_attempt_count"] = len(attempts)
    base_result["execution_path"]["retry_count"] = max(0, len(attempts) - 1)
    base_result["execution_path"]["semantic_post_click_verification_used"] = bool(semantic_post_click_verification.get("applicable"))
    attach_timings(base_result)

    if not verified:
        error_code = "semantic_post_click_verification_failed" if semantic_post_click_verification.get("applicable") else "post_click_verification_failed"
        base_result["fallback_plan"] = _execute_fallback_plan(
            request=request,
            failure_reason=error_code,
            plan=plan,
            pre_click=pre_click,
            attempts=attempts,
        )
        base_result["agent_execution_guidance"] = _agent_execution_guidance(
            request=request,
            status="verification_failed",
            result=base_result,
            failure_reason=error_code,
        )
        base_result["agent_step_result"] = _agent_step_result(
            request=request,
            status="verification_failed",
            result=base_result,
            failure_reason=error_code,
        )
        attach_timings(base_result)
        base_result["trace_path"] = _write_execute_trace_if_enabled(
            request,
            category="actions",
            operation="execute_recognition_plan",
            payload={"success": False, "request": request.model_dump(), "result": base_result},
            name_hint=request.app_name or "recognition_plan",
        )
        base_result["agent_step_result"] = _agent_step_result(
            request=request,
            status="verification_failed",
            result=base_result,
            failure_reason=error_code,
        )
        _rewrite_execute_trace_result(trace_path=base_result.get("trace_path"), success=False, request=request, result=base_result)
        return APIResponse(
            success=False,
            message="Recognition-plan click executed but post-click verification failed",
            data=base_result,
            error=ErrorModel(
                code=error_code,
                details={
                    "post_click_verification": post_click_verification,
                    "semantic_post_click_verification": semantic_post_click_verification,
                },
            ),
        )

    if _instruction_learning_enabled(request) and bound is not None and not request.learned_instruction_id:
        with timer.step("save_learned_instruction"):
            learning_record = _save_learned_instruction(
                request=request,
                bound=bound,
                image_path=image_path,
                live_capture=live_capture,
                plan=plan,
                pre_click=pre_click,
                selected_point=selected_point,
                click_result=click_result,
                post_click_verification=post_click_verification,
                semantic_post_click_verification=semantic_post_click_verification,
                plan_trace_path=plan_trace_path,
                action_trace_path=None,
            )
        base_result.update(learning_record)
        attach_timings(base_result)

    with timer.step("save_execute_transition_memory", enabled=_element_memory_enabled(request)):
        base_result["element_memory_writeback"] = _save_execute_transition_memory(
            request=request,
            bound=bound,
            base_result=base_result,
            verified=verified,
        )
    base_result["agent_execution_guidance"] = _agent_execution_guidance(
        request=request,
        status="executed_verified",
        result=base_result,
    )
    base_result["agent_step_result"] = _agent_step_result(
        request=request,
        status="executed_verified",
        result=base_result,
    )
    attach_timings(base_result)
    base_result["trace_path"] = _write_execute_trace_if_enabled(
        request,
        category="actions",
        operation="execute_recognition_plan",
        payload={"success": True, "request": request.model_dump(), "result": base_result},
        name_hint=request.app_name or "recognition_plan",
    )
    _update_execute_transition_action_trace(base_result)
    _update_learned_instruction_action_trace(base_result)
    base_result["agent_step_result"] = _agent_step_result(
        request=request,
        status="executed_verified",
        result=base_result,
    )
    _rewrite_execute_trace_result(trace_path=base_result.get("trace_path"), success=True, request=request, result=base_result)

    data = ActionResultData(action="execute_recognition_plan", result=base_result)
    return APIResponse(success=True, message="Recognition-plan click executed and verified", data=data.model_dump(), error=None)


@router.post("/execute_confirmed_point", response_model=APIResponse)
def execute_confirmed_point(request: ExecuteConfirmedPointRequest) -> APIResponse:
    """Dispatch a point explicitly confirmed in the review UI."""
    timer = RuntimeTimer()
    with timer.step("get_bound_window"):
        bound = window_manager.get_bound_window()
    if bound is None:
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="No bound window is currently available",
            data={"timings": timings},
            error=ErrorModel(code="no_bound_window", details="Bind a target window before executing a confirmed point"),
        )

    with timer.step("validate_confirmed_point"):
        point = {"x": int(request.x), "y": int(request.y)}
        bbox = request.bbox.model_dump() if request.bbox is not None else None
    if bbox is not None and not _point_in_rect(point, bbox):
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="Confirmed point is outside its reviewed candidate box",
            data={"point": point, "bbox": bbox, "timings": timings},
            error=ErrorModel(code="confirmed_point_outside_bbox", details={"point": point, "bbox": bbox}),
        )

    with timer.step("validate_bound_window_rect"):
        rect = _window_rect(bound)
    if not _point_in_rect(point, {"x": 0, "y": 0, "width": rect["width"] - 1, "height": rect["height"] - 1}):
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="Confirmed point is outside the currently bound window",
            data={"point": point, "window_size": {"width": rect["width"], "height": rect["height"]}, "timings": timings},
            error=ErrorModel(code="confirmed_point_outside_window", details=point),
        )

    result: dict[str, Any] = {
        "contract_version": "execute_confirmed_point_v1",
        "label": request.label,
        "confirmed_point": point,
        "candidate_bbox": bbox,
        "source_trace_path": request.source_trace_path,
        "bound_window": {"handle": int(bound.handle), "title": bound.title, "width": rect["width"], "height": rect["height"]},
        "execution_path": {
            "coordinate_source": "human_confirmed_candidate_center",
            "selection_source": "settings_panel_candidate_review",
            "action_executed": False,
            "dry_run": bool(request.dry_run),
        },
    }
    if request.dry_run:
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="actions",
            operation="execute_confirmed_point",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.label or "confirmed_point",
        )
        data = ActionResultData(action="execute_confirmed_point", result=result)
        return APIResponse(success=True, message="Confirmed point accepted; dry run did not click", data=data.model_dump(), error=None)

    try:
        with timer.step("click_point"):
            result["click_result"] = input_controller.click_point(
                point["x"],
                point["y"],
                move_before_click=True,
                settle_ms=200,
                hold_ms=70,
            )
        result["execution_path"]["action_executed"] = True
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="actions",
            operation="execute_confirmed_point",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.label or "confirmed_point",
        )
        data = ActionResultData(action="execute_confirmed_point", result=result)
        return APIResponse(success=True, message="Confirmed coordinate click dispatched", data=data.model_dump(), error=None)
    except Exception as exc:
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="actions",
            operation="execute_confirmed_point",
            payload={"success": False, "request": request.model_dump(), "result": result, "error": str(exc)},
            name_hint=request.label or "confirmed_point",
        )
        return APIResponse(
            success=False,
            message="Confirmed coordinate click failed",
            data=result,
            error=ErrorModel(code="confirmed_point_click_failed", details=str(exc)),
        )


@router.post("/click_text", response_model=APIResponse)
def click_text(request: ClickTextRequest) -> APIResponse:
    bound = window_manager.get_bound_window()
    if bound is None:
        return APIResponse(
            success=False,
            message="No bound window is currently available",
            data=None,
            error=ErrorModel(code="no_bound_window", details="Bind a target window before calling /action/click_text"),
        )

    try:
        action_name = f"click_text:{request.text}"
        execution_path = {
            "vision_model_used": False,
            "page_structure_used": False,
            "coordinate_source": "ocr_bbox_center",
            "selection_source": "ocr_text_match",
        }
        capture = screenshot_service.capture_window(
            roi=request.roi,
            save_image=True,
            purpose="click_text_scan",
            name_hint=request.text,
        )
        ocr_result = ocr_service.scan_image(capture["image_path"])
        matches = find_text_matches(ocr_result, request.text, partial_match=request.partial_match)
        if not matches:
            trace_path = write_trace(
                category="actions",
                operation="click_text",
                payload={
                    "success": False,
                    "request": request.model_dump(),
                    "execution_path": execution_path,
                    "capture": capture,
                    "ocr_result": ocr_result.to_dict(),
                    "failure_reason": "text_not_found",
                },
                name_hint=request.text,
            )
            return APIResponse(
                success=False,
                message="Requested text was not found in OCR result",
                data={
                    "query": request.text,
                    "partial_match": request.partial_match,
                    "execution_path": execution_path,
                    "trace_path": trace_path,
                    "matches": [match.to_dict() for match in find_text_matches(ocr_result, request.text, partial_match=True)],
                    "ocr_result": ocr_result.to_dict(),
                },
                error=ErrorModel(code="text_not_found", details=request.text),
            )

        roi_payload = capture.get("roi") or {}
        attempts: list[dict[str, Any]] = []
        selected_result: Optional[dict[str, Any]] = None
        candidate_matches = matches[: request.max_retries]

        for index, candidate in enumerate(candidate_matches, start=1):
            center = bbox_center(candidate.bbox)
            window_x = int(center["x"] + int(roi_payload.get("x", 0)))
            window_y = int(center["y"] + int(roi_payload.get("y", 0)))

            before_state = verifier.capture_pre_action_state(roi=request.roi, action_name=action_name) if request.enable_validation else None
            click_result = input_controller.click_point(window_x, window_y, move_before_click=True, settle_ms=100, hold_ms=70)
            verification = (
                verifier.verify_action(
                    action_name,
                    roi=request.roi,
                    before_state=before_state,
                    click_result=click_result,
                )
                if request.enable_validation
                else {"verified": None, "verification_skipped": True}
            )
            success = True if not request.enable_validation else bool(verification.get("verified"))
            attempt = {
                "attempt": index,
                "match": candidate.to_dict(),
                "window_point": {"x": window_x, "y": window_y},
                "click_result": click_result,
                "verification": verification,
                "success": success,
            }
            attempts.append(attempt)
            if success:
                selected_result = attempt
                break

        if selected_result is None:
            trace_path = write_trace(
                category="actions",
                operation="click_text",
                payload={
                    "success": False,
                    "request": request.model_dump(),
                    "execution_path": execution_path,
                    "capture": capture,
                    "ocr_result": ocr_result.to_dict(),
                    "attempts": attempts,
                    "failure_reason": "verification_failed",
                },
                name_hint=request.text,
            )
            return APIResponse(
                success=False,
                message="Text candidates were clicked but verification did not succeed",
                data={
                    "query": request.text,
                    "partial_match": request.partial_match,
                    "execution_path": execution_path,
                    "trace_path": trace_path,
                    "capture": {
                        "image_path": capture.get("image_path"),
                        "roi": capture.get("roi"),
                        "roi_adjusted": capture.get("roi_adjusted"),
                        "window_size": capture.get("window_size"),
                    },
                    "ocr_match_count": len(ocr_result.matches),
                    "attempts": attempts,
                },
                error=ErrorModel(code="click_text_not_verified", details=request.text),
            )

        result = {
            "query": request.text,
            "partial_match": request.partial_match,
            "selected_match": selected_result["match"],
            "window_point": selected_result["window_point"],
            "capture": {
                "image_path": capture.get("image_path"),
                "roi": capture.get("roi"),
                "roi_adjusted": capture.get("roi_adjusted"),
                "window_size": capture.get("window_size"),
            },
            "execution_path": execution_path,
            "ocr_match_count": len(ocr_result.matches),
            "attempts": attempts,
            "click_result": selected_result["click_result"],
            "verification": selected_result["verification"],
        }
        result["trace_path"] = write_trace(
            category="actions",
            operation="click_text",
            payload={
                "success": True,
                "request": request.model_dump(),
                "execution_path": execution_path,
                "result": result,
                "ocr_result": ocr_result.to_dict(),
            },
            name_hint=request.text,
        )
        data = ActionResultData(action="click_text", result=result)
        return APIResponse(success=True, message="Text clicked successfully", data=data.model_dump(), error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Text click failed",
            data=None,
            error=ErrorModel(code="click_text_failed", details=str(exc)),
        )


@router.post("/type_text", response_model=APIResponse)
def type_text(request: TypeTextRequest) -> APIResponse:
    bound = window_manager.get_bound_window()
    if bound is None:
        return APIResponse(
            success=False,
            message="No bound window is currently available",
            data=None,
            error=ErrorModel(code="no_bound_window", details="Bind a target window before calling /action/type_text"),
        )
    if request.click_before_typing and (request.x is None or request.y is None):
        return APIResponse(
            success=False,
            message="Text input point is incomplete",
            data=None,
            error=ErrorModel(code="missing_input_point", details="Provide x and y when click_before_typing=true"),
        )

    result: dict[str, Any] = {
        "contract_version": "type_text_result_v1",
        "dry_run": request.dry_run,
        "text_length": len(request.text),
        "click_before_typing": request.click_before_typing,
        "point": {"x": request.x, "y": request.y} if request.x is not None and request.y is not None else None,
        "clear_existing": request.clear_existing,
        "submit": request.submit,
        "path_graph_action_context": request.metadata.get("path_graph_action_context")
        if isinstance(request.metadata, dict)
        else None,
        "path_graph_assisted": bool(
            isinstance(request.metadata, dict) and request.metadata.get("path_graph_action_context")
        ),
        "execution_path": {
            "vision_model_used": False,
            "page_structure_used": False,
            "input_backend": "SendInput+clipboard",
            "action_executed": False,
        },
    }
    if request.dry_run:
        result["trace_path"] = write_trace(
            category="actions",
            operation="type_text",
            payload={"success": True, "request": request.model_dump(exclude={"text"}), "result": result},
            name_hint="type_text_dry_run",
        )
        data = ActionResultData(action="type_text", result=result)
        return APIResponse(success=True, message="Text input dry-run validated", data=data.model_dump(), error=None)

    try:
        result["type_result"] = input_controller.type_text(
            request.text,
            x=request.x,
            y=request.y,
            click_before_typing=request.click_before_typing,
            clear_existing=request.clear_existing,
            submit=request.submit,
            restore_clipboard=request.restore_clipboard,
        )
        result["execution_path"]["action_executed"] = True
        result["trace_path"] = write_trace(
            category="actions",
            operation="type_text",
            payload={"success": True, "request": request.model_dump(exclude={"text"}), "result": result},
            name_hint="type_text",
        )
        data = ActionResultData(action="type_text", result=result)
        return APIResponse(success=True, message="Text input dispatched", data=data.model_dump(), error=None)
    except Exception as exc:
        result["trace_path"] = write_trace(
            category="actions",
            operation="type_text",
            payload={"success": False, "request": request.model_dump(exclude={"text"}), "result": result, "error": str(exc)},
            name_hint="type_text",
        )
        return APIResponse(
            success=False,
            message="Text input failed",
            data=result,
            error=ErrorModel(code="type_text_failed", details=str(exc)),
        )


@router.post("/scroll", response_model=APIResponse)
def scroll(request: ScrollRequest) -> APIResponse:
    timer = RuntimeTimer()
    with timer.step("get_bound_window"):
        bound = window_manager.get_bound_window()
    if bound is None:
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="No bound window is currently available",
            data={"timings": timings},
            error=ErrorModel(code="no_bound_window", details="Bind a target window before calling /action/scroll"),
        )

    with timer.step("validate_scroll_request"):
        rect = _window_rect(bound)
        window_size = {"width": int(rect["width"]), "height": int(rect["height"])}
        scroll_containers = None
        target_container = None
        if request.scroll_scope == "container" or request.target_container_id:
            scroll_containers = discover_seek_scroll_containers(
                window_title=getattr(bound, "title", None),
                app_name=request.target_container_id or request.target_pane,
                window_size=window_size,
            )
            target_container = get_scroll_container(scroll_containers, request.target_container_id)
        container_rect = _rect_from_bbox(request.container_bbox)
        if container_rect is None and target_container is not None:
            container_rect = _rect_from_bbox(target_container.get("bbox"))
        point = build_scroll_safe_point(container_rect or {"x": 0, "y": 0, "width": rect["width"], "height": rect["height"]}, explicit_x=request.x, explicit_y=request.y)
        precondition = build_scroll_precondition_decision(
            request=request,
            window_rect=window_size,
            point=point,
            container_rect=container_rect,
            target_container=target_container,
        )
        if precondition["decision"] != "ALLOW":
            timings = timer.to_dict()
            return APIResponse(
                success=False,
                message="Scroll precondition rejected",
                data={
                    "contract_version": "scroll_action_v2" if request.scroll_scope != "window" or request.target_container_id else "scroll_action_v1",
                    "point": point,
                    "window_size": window_size,
                    "scroll_containers": scroll_containers,
                    "target_container": target_container,
                    "precondition_decision": precondition,
                    "timings": timings,
                },
                error=ErrorModel(code="scroll_precondition_rejected", details=precondition),
            )

    action_name = f"scroll_{request.direction}"
    path_graph_context = (
        request.metadata.get("path_graph_action_context") if isinstance(request.metadata, dict) else None
    )
    result: dict[str, Any] = {
        "contract_version": "scroll_action_v2" if request.scroll_scope != "window" or request.target_container_id else "scroll_action_v1",
        "goal_id": request.goal_id,
        "task_chain_id": request.task_chain_id,
        "source_trace_path": request.source_trace_path,
        "path_graph_action_context": path_graph_context,
        "path_graph_assisted": bool(path_graph_context),
        "artifact_is_authorization": False if path_graph_context else None,
        "scroll_scope": request.scroll_scope,
        "target_pane": request.target_pane or (target_container or {}).get("pane_role"),
        "target_container_id": request.target_container_id,
        "container_bbox": _bbox_payload(container_rect),
        "coordinate_window_size": window_size,
        "direction": request.direction,
        "wheel_clicks": request.wheel_clicks,
        "point": point,
        "reason": request.reason,
        "missing_evidence": list(request.missing_evidence or []),
        "expected_effect": dict(request.expected_effect or {}),
        "scroll_history": list(request.scroll_history or []),
        "dry_run": request.dry_run,
        "bound_window": {"handle": int(bound.handle), "title": bound.title, "width": rect["width"], "height": rect["height"]},
        "scroll_containers": scroll_containers,
        "target_container": target_container,
        "resolved_target": {
            "x": point["x"],
            "y": point["y"],
            "point_inside_container": _point_in_rect(point, container_rect) if container_rect is not None else None,
            "target_point_policy": request.target_point_policy,
        },
        "precondition_decision": precondition,
        "execution_path": {
            "vision_model_used": False,
            "page_structure_used": False,
            "input_backend": "SendInput",
            "action_type": "scroll",
            "action_executed": False,
            "verification_used": bool(request.enable_verification and not request.dry_run),
        },
    }
    if request.dry_run:
        result["scroll_effect_validation"] = {
            "contract_version": "scroll_effect_validation_v1",
            "status": "not_run_dry_run",
            "target_container_id": request.target_container_id,
            "target_pane": result.get("target_pane"),
        }
        result["outcome"] = {"status": "dry_run_ready", "should_retry_goal": False}
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="actions",
            operation="scroll",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=action_name,
        )
        data = ActionResultData(action="scroll", result=result)
        return APIResponse(success=True, message="Scroll dry-run validated", data=data.model_dump(), error=None)

    try:
        with timer.step("capture_pre_scroll_state", enabled=request.enable_verification):
            before_state = verifier.capture_pre_action_state(action_name=action_name) if request.enable_verification else None
        with timer.step("scroll_window"):
            result["scroll_result"] = input_controller.scroll_window(
                direction=request.direction,
                wheel_clicks=request.wheel_clicks,
                x=point["x"],
                y=point["y"],
                settle_ms=100,
            )
        result["execution_path"]["action_executed"] = True
        with timer.step("post_scroll_verification", enabled=request.enable_verification):
            result["post_scroll_verification"] = (
                verifier.verify_action(
                    action_name,
                    before_state=before_state,
                    click_result=result["scroll_result"],
                )
                if request.enable_verification
                else {"verified": None, "verification_skipped": True}
            )
        result["scroll_effect_validation"] = build_scroll_effect_validation(
            request=request,
            post_scroll_verification=result.get("post_scroll_verification"),
            target_container=target_container,
        )
        result["outcome"] = {
            "status": result["scroll_effect_validation"]["status"],
            "should_retry_goal": True,
            "next_after_success": {
                "endpoint": "POST /action/execute_recognition_plan",
                "reason": "rerun the same goal after container-aware scroll evidence is recorded",
            },
        }
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="actions",
            operation="scroll",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=action_name,
        )
        data = ActionResultData(action="scroll", result=result)
        return APIResponse(success=True, message="Scroll dispatched", data=data.model_dump(), error=None)
    except Exception as exc:
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="actions",
            operation="scroll",
            payload={"success": False, "request": request.model_dump(), "result": result, "error": str(exc)},
            name_hint=action_name,
        )
        return APIResponse(
            success=False,
            message="Scroll failed",
            data=result,
            error=ErrorModel(code="scroll_failed", details=str(exc)),
        )
