from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from app.gate.candidates import validate_action_candidate_freshness


FORM_FILL_ACTION_RESULT_CONTRACT = "form_fill_action_result_v1"
FORM_DROPDOWN_ACTION_RESULT_CONTRACT = "form_dropdown_action_result_v1"
FORM_CHOICE_ACTION_RESULT_CONTRACT = "form_choice_action_result_v1"
_FINAL_ACTION_TERMS = ("submit", "send", "complete", "confirm", "payment", "purchase", "pay now")


def execute_form_text_fill(
    *,
    question: dict[str, Any],
    answer_decision: dict[str, Any],
    policy_gate: dict[str, Any],
    candidate: dict[str, Any],
    current_capture_id: str,
    current_viewport_size: dict[str, Any],
    approved_value: str,
    action_gate: dict[str, Any],
    clear_existing: bool,
    dispatch: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """执行一次当前截图范围内、经过双重 Gate 的文本填写。"""

    result = _base_result(question=question, answer_decision=answer_decision, candidate=candidate)
    if _is_final_action(question=question, action_gate=action_gate):
        return _blocked(result, "final_action_forbidden", unsafe_prevented=True)
    if not _policy_gate_allowed(question=question, answer_decision=answer_decision, policy_gate=policy_gate):
        return _blocked(result, "form_policy_not_allowed")
    if clear_existing is not True:
        return _blocked(result, "clear_existing_required")
    if not _approved_value_matches(answer_decision=answer_decision, approved_value=approved_value):
        return _blocked(result, "approved_value_evidence_mismatch")

    freshness_decision = validate_action_candidate_freshness(
        candidate,
        current_capture_id=current_capture_id,
        current_viewport_size=current_viewport_size,
    )
    result["freshness_decision"] = freshness_decision
    if not freshness_decision.get("allowed"):
        return _blocked(result, "candidate_freshness_rejected")
    result["capture_id"] = current_capture_id

    action_gate_reason = _action_gate_rejection_reason(action_gate=action_gate, candidate=candidate)
    if action_gate_reason:
        return _blocked(result, action_gate_reason)

    point = candidate["click_point"]
    result["one_time_action_authorized"] = True
    result["dispatch_attempted"] = True
    try:
        dispatch_result = dispatch(
            text=approved_value,
            x=int(point["x"]),
            y=int(point["y"]),
            click_before_typing=True,
            clear_existing=True,
            submit=False,
            restore_clipboard=True,
        )
    except Exception as exc:
        result["dispatch_success"] = False
        result["blocked_reason"] = "input_dispatch_failed"
        result["dispatch_error_type"] = type(exc).__name__
        return result

    result["dispatch_success"] = bool(dispatch_result.get("success")) if isinstance(dispatch_result, dict) else False
    if isinstance(dispatch_result, dict) and isinstance(dispatch_result.get("trace_path"), str):
        result["dispatch_trace_path"] = dispatch_result["trace_path"]
    return result


def verify_form_text_fill_effect(
    *,
    fill_result: dict[str, Any],
    current_capture_id: str,
    observed_question_id: str,
    before_value: str,
    observed_value: str,
) -> dict[str, Any]:
    """核对文本填写是否真的改变了当前字段，不把字段原文写入结果。"""

    before_text = before_value if isinstance(before_value, str) else ""
    observed_text = observed_value if isinstance(observed_value, str) else ""
    before_hash = _value_hash(before_text)
    observed_hash = _value_hash(observed_text)
    expected_hash = str(fill_result.get("value_hash") or "")
    expected_length = _safe_int(fill_result.get("value_length"))
    failure_reasons: list[str] = []
    if fill_result.get("contract_version") != FORM_FILL_ACTION_RESULT_CONTRACT:
        failure_reasons.append("fill_result_contract_invalid")
    if fill_result.get("dispatch_attempted") is not True or fill_result.get("dispatch_success") is not True:
        failure_reasons.append("fill_dispatch_not_successful")
    if str(fill_result.get("capture_id") or "") != str(current_capture_id or ""):
        failure_reasons.append("capture_id_mismatch")
    if str(fill_result.get("question_id") or "") != str(observed_question_id or ""):
        failure_reasons.append("question_id_mismatch")
    if before_hash == observed_hash:
        failure_reasons.append("field_value_unchanged")
    if observed_hash != expected_hash or len(observed_text) != expected_length:
        failure_reasons.append("observed_value_mismatch")
    return {
        "contract_version": "form_fill_effect_verification_v1",
        "question_id": fill_result.get("question_id"),
        "capture_id": current_capture_id,
        "verified": not failure_reasons,
        "status": "text_fill_effect_verified" if not failure_reasons else "verification_failed",
        "failure_reasons": failure_reasons,
        "value_changed": before_hash != observed_hash,
        "expected_value_hash": expected_hash,
        "expected_value_length": expected_length,
        "before_value_hash": before_hash,
        "before_value_length": len(before_text),
        "observed_value_hash": observed_hash,
        "observed_value_length": len(observed_text),
        "pii_redacted": True,
        "artifact_is_authorization": False,
    }


def execute_form_dropdown_open(
    *,
    question: dict[str, Any],
    answer_decision: dict[str, Any],
    policy_gate: dict[str, Any],
    candidate: dict[str, Any],
    current_capture_id: str,
    current_viewport_size: dict[str, Any],
    action_gate: dict[str, Any],
    dispatch: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """打开当前问题的下拉框；选项必须在下一张截图中重新定位。"""

    result = _base_dropdown_result(
        phase="open_dropdown",
        question=question,
        answer_decision=answer_decision,
        candidate=candidate,
    )
    if _is_final_action(question=question, action_gate=action_gate):
        return _blocked(result, "final_action_forbidden", unsafe_prevented=True)
    if not _policy_gate_allowed(question=question, answer_decision=answer_decision, policy_gate=policy_gate):
        return _blocked(result, "form_policy_not_allowed")
    if str(candidate.get("question_id") or "") != str(question.get("question_id") or ""):
        return _blocked(result, "dropdown_question_ownership_mismatch")
    freshness_decision = validate_action_candidate_freshness(
        candidate,
        current_capture_id=current_capture_id,
        current_viewport_size=current_viewport_size,
    )
    result["freshness_decision"] = freshness_decision
    if not freshness_decision.get("allowed"):
        return _blocked(result, "candidate_freshness_rejected")
    result["capture_id"] = current_capture_id
    action_gate_reason = _action_gate_rejection_reason_for_semantic_action(
        action_gate=action_gate,
        candidate=candidate,
        semantic_action="open_dropdown",
    )
    if action_gate_reason:
        return _blocked(result, action_gate_reason)
    return _dispatch_click(result=result, candidate=candidate, dispatch=dispatch)


def execute_form_option_select(
    *,
    question: dict[str, Any],
    answer_decision: dict[str, Any],
    policy_gate: dict[str, Any],
    open_result: dict[str, Any],
    candidate: dict[str, Any],
    current_capture_id: str,
    current_viewport_size: dict[str, Any],
    approved_option: str,
    action_gate: dict[str, Any],
    dispatch: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """只从打开下拉框后的新截图中选择唯一、启用且归属明确的选项。"""

    result = _base_dropdown_result(
        phase="select_option",
        question=question,
        answer_decision=answer_decision,
        candidate=candidate,
    )
    if _is_final_action(question=question, action_gate=action_gate):
        return _blocked(result, "final_action_forbidden", unsafe_prevented=True)
    if not _policy_gate_allowed(question=question, answer_decision=answer_decision, policy_gate=policy_gate):
        return _blocked(result, "form_policy_not_allowed")
    if (
        open_result.get("contract_version") != FORM_DROPDOWN_ACTION_RESULT_CONTRACT
        or open_result.get("phase") != "open_dropdown"
        or open_result.get("dispatch_attempted") is not True
        or open_result.get("dispatch_success") is not True
        or open_result.get("question_id") != question.get("question_id")
    ):
        return _blocked(result, "dropdown_open_not_verified")
    if str(open_result.get("capture_id") or "") == str(current_capture_id or ""):
        return _blocked(result, "dropdown_reobserve_required")
    if str(candidate.get("question_id") or "") != str(question.get("question_id") or ""):
        return _blocked(result, "option_question_ownership_mismatch")
    if candidate.get("enabled") is not True:
        return _blocked(result, "option_disabled")
    if _safe_int(candidate.get("matching_label_count")) != 1:
        return _blocked(result, "option_label_ambiguous")
    if not _approved_option_matches(
        answer_decision=answer_decision,
        approved_option=approved_option,
        candidate=candidate,
    ):
        return _blocked(result, "approved_option_evidence_mismatch")
    freshness_decision = validate_action_candidate_freshness(
        candidate,
        current_capture_id=current_capture_id,
        current_viewport_size=current_viewport_size,
    )
    result["freshness_decision"] = freshness_decision
    if not freshness_decision.get("allowed"):
        return _blocked(result, "candidate_freshness_rejected")
    result["capture_id"] = current_capture_id
    action_gate_reason = _action_gate_rejection_reason_for_semantic_action(
        action_gate=action_gate,
        candidate=candidate,
        semantic_action="select_option",
    )
    if action_gate_reason:
        return _blocked(result, action_gate_reason)
    return _dispatch_click(result=result, candidate=candidate, dispatch=dispatch)


def verify_form_option_select_effect(
    *,
    select_result: dict[str, Any],
    current_capture_id: str,
    observed_question_id: str,
    observed_value: str,
) -> dict[str, Any]:
    """在选择后的新截图中核对选中值，只保留哈希和长度。"""

    observed_text = observed_value if isinstance(observed_value, str) else ""
    observed_hash = _value_hash(observed_text)
    expected_hash = str(select_result.get("value_hash") or "")
    expected_length = _safe_int(select_result.get("value_length"))
    failure_reasons: list[str] = []
    if select_result.get("contract_version") != FORM_DROPDOWN_ACTION_RESULT_CONTRACT:
        failure_reasons.append("select_result_contract_invalid")
    if select_result.get("phase") != "select_option":
        failure_reasons.append("select_result_phase_invalid")
    if select_result.get("dispatch_attempted") is not True or select_result.get("dispatch_success") is not True:
        failure_reasons.append("option_select_dispatch_not_successful")
    if str(select_result.get("capture_id") or "") == str(current_capture_id or ""):
        failure_reasons.append("selection_reobserve_required")
    if str(select_result.get("question_id") or "") != str(observed_question_id or ""):
        failure_reasons.append("question_id_mismatch")
    if observed_hash != expected_hash or len(observed_text) != expected_length:
        failure_reasons.append("observed_option_mismatch")
    return {
        "contract_version": "form_option_select_effect_verification_v1",
        "question_id": select_result.get("question_id"),
        "capture_id": current_capture_id,
        "verified": not failure_reasons,
        "status": "option_select_effect_verified" if not failure_reasons else "verification_failed",
        "failure_reasons": failure_reasons,
        "expected_value_hash": expected_hash,
        "expected_value_length": expected_length,
        "observed_value_hash": observed_hash,
        "observed_value_length": len(observed_text),
        "pii_redacted": True,
        "artifact_is_authorization": False,
    }


def execute_form_choice_select(
    *,
    question: dict[str, Any],
    answer_decision: dict[str, Any],
    policy_gate: dict[str, Any],
    candidate: dict[str, Any],
    current_capture_id: str,
    current_viewport_size: dict[str, Any],
    approved_value: str,
    expected_checked: bool,
    action_gate: dict[str, Any],
    semantic_action: str,
    dispatch: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """在当前截图中选择一个唯一 radio 或切换一个 checkbox。"""

    result = _base_choice_result(
        question=question,
        answer_decision=answer_decision,
        candidate=candidate,
        expected_checked=expected_checked,
        semantic_action=semantic_action,
    )
    field_type = str(question.get("field_type") or "").strip().casefold()
    valid_pair = (field_type, semantic_action) in {
        ("radio", "select_radio"),
        ("checkbox", "toggle_checkbox"),
    }
    if not valid_pair or (field_type == "radio" and expected_checked is not True):
        return _blocked(result, "choice_action_type_mismatch")
    if _is_final_action(question=question, action_gate=action_gate):
        return _blocked(result, "final_action_forbidden", unsafe_prevented=True)
    if not _policy_gate_allowed(question=question, answer_decision=answer_decision, policy_gate=policy_gate):
        return _blocked(result, "form_policy_not_allowed")
    if str(candidate.get("question_id") or "") != str(question.get("question_id") or ""):
        return _blocked(result, "choice_question_ownership_mismatch")
    if candidate.get("enabled") is not True:
        return _blocked(result, "choice_disabled")
    if _safe_int(candidate.get("matching_label_count")) != 1:
        return _blocked(result, "choice_label_ambiguous")
    if not _approved_choice_matches(
        answer_decision=answer_decision,
        approved_value=approved_value,
        candidate=candidate,
    ):
        return _blocked(result, "approved_choice_evidence_mismatch")

    freshness_decision = validate_action_candidate_freshness(
        candidate,
        current_capture_id=current_capture_id,
        current_viewport_size=current_viewport_size,
    )
    result["freshness_decision"] = freshness_decision
    if not freshness_decision.get("allowed"):
        return _blocked(result, "candidate_freshness_rejected")
    result["capture_id"] = current_capture_id

    if candidate.get("checked") is expected_checked:
        result["status"] = "already_satisfied"
        result["action_required"] = False
        result["state_satisfied"] = True
        return result

    action_gate_reason = _action_gate_rejection_reason_for_semantic_action(
        action_gate=action_gate,
        candidate=candidate,
        semantic_action=semantic_action,
    )
    if action_gate_reason:
        return _blocked(result, action_gate_reason)
    return _dispatch_click(result=result, candidate=candidate, dispatch=dispatch)


def verify_form_choice_select_effect(
    *,
    choice_result: dict[str, Any],
    current_capture_id: str,
    observed_question_id: str,
    observed_checked: bool,
) -> dict[str, Any]:
    """核对 radio/checkbox 的最终 checked 状态，不把选择值写入结果。"""

    failure_reasons: list[str] = []
    already_satisfied = choice_result.get("status") == "already_satisfied"
    if choice_result.get("contract_version") != FORM_CHOICE_ACTION_RESULT_CONTRACT:
        failure_reasons.append("choice_result_contract_invalid")
    if not already_satisfied and (
        choice_result.get("dispatch_attempted") is not True
        or choice_result.get("dispatch_success") is not True
    ):
        failure_reasons.append("choice_dispatch_not_successful")
    if not already_satisfied and str(choice_result.get("capture_id") or "") == str(current_capture_id or ""):
        failure_reasons.append("choice_reobserve_required")
    if str(choice_result.get("question_id") or "") != str(observed_question_id or ""):
        failure_reasons.append("question_id_mismatch")
    if not isinstance(observed_checked, bool) or observed_checked is not choice_result.get("expected_checked"):
        failure_reasons.append("observed_checked_state_mismatch")
    return {
        "contract_version": "form_choice_select_effect_verification_v1",
        "question_id": choice_result.get("question_id"),
        "capture_id": current_capture_id,
        "verified": not failure_reasons,
        "status": "choice_effect_verified" if not failure_reasons else "verification_failed",
        "failure_reasons": failure_reasons,
        "expected_checked": choice_result.get("expected_checked"),
        "observed_checked": observed_checked if isinstance(observed_checked, bool) else None,
        "already_satisfied": already_satisfied,
        "pii_redacted": True,
        "artifact_is_authorization": False,
    }


def _base_result(
    *,
    question: dict[str, Any],
    answer_decision: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    value_length = _safe_int(answer_decision.get("value_length"))
    return {
        "contract_version": FORM_FILL_ACTION_RESULT_CONTRACT,
        "question_id": question.get("question_id"),
        "candidate_id": candidate.get("candidate_id"),
        "policy": answer_decision.get("policy"),
        "value_reference": answer_decision.get("value_reference"),
        "value_hash": answer_decision.get("value_hash"),
        "value_length": value_length,
        "value_preview": f"<redacted:{value_length} chars>",
        "pii_redacted": True,
        "clear_existing": True,
        "submit": False,
        "dispatch_attempted": False,
        "dispatch_success": False,
        "fill_effect_success": None,
        "one_time_action_authorized": False,
        "artifact_is_authorization": False,
        "unsafe_prevented": False,
    }


def _base_dropdown_result(
    *,
    phase: str,
    question: dict[str, Any],
    answer_decision: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    value_length = _safe_int(answer_decision.get("value_length"))
    return {
        "contract_version": FORM_DROPDOWN_ACTION_RESULT_CONTRACT,
        "phase": phase,
        "question_id": question.get("question_id"),
        "candidate_id": candidate.get("candidate_id"),
        "policy": answer_decision.get("policy"),
        "value_reference": answer_decision.get("value_reference"),
        "value_hash": answer_decision.get("value_hash"),
        "value_length": value_length,
        "value_preview": f"<redacted:{value_length} chars>",
        "pii_redacted": True,
        "submit": False,
        "dispatch_attempted": False,
        "dispatch_success": False,
        "one_time_action_authorized": False,
        "artifact_is_authorization": False,
        "unsafe_prevented": False,
    }


def _base_choice_result(
    *,
    question: dict[str, Any],
    answer_decision: dict[str, Any],
    candidate: dict[str, Any],
    expected_checked: bool,
    semantic_action: str,
) -> dict[str, Any]:
    value_length = _safe_int(answer_decision.get("value_length"))
    return {
        "contract_version": FORM_CHOICE_ACTION_RESULT_CONTRACT,
        "question_id": question.get("question_id"),
        "candidate_id": candidate.get("candidate_id"),
        "semantic_action": semantic_action,
        "policy": answer_decision.get("policy"),
        "value_reference": answer_decision.get("value_reference"),
        "value_hash": answer_decision.get("value_hash"),
        "value_length": value_length,
        "value_preview": f"<redacted:{value_length} chars>",
        "expected_checked": expected_checked,
        "pii_redacted": True,
        "submit": False,
        "action_required": True,
        "state_satisfied": False,
        "dispatch_attempted": False,
        "dispatch_success": False,
        "one_time_action_authorized": False,
        "artifact_is_authorization": False,
        "unsafe_prevented": False,
    }


def _blocked(result: dict[str, Any], reason: str, *, unsafe_prevented: bool = False) -> dict[str, Any]:
    result["blocked_reason"] = reason
    result["unsafe_prevented"] = unsafe_prevented
    return result


def _policy_gate_allowed(
    *,
    question: dict[str, Any],
    answer_decision: dict[str, Any],
    policy_gate: dict[str, Any],
) -> bool:
    return bool(
        policy_gate.get("contract_version") == "form_action_gate_decision_v1"
        and policy_gate.get("policy_allowed") is True
        and policy_gate.get("requires_current_grounding") is True
        and policy_gate.get("requires_action_gate") is True
        and policy_gate.get("question_id") == question.get("question_id") == answer_decision.get("question_id")
        and policy_gate.get("policy") == answer_decision.get("policy")
        and answer_decision.get("policy") in {"auto_fill", "derived_with_evidence"}
    )


def _approved_value_matches(*, answer_decision: dict[str, Any], approved_value: str) -> bool:
    if not isinstance(approved_value, str) or not approved_value:
        return False
    expected_hash = str(answer_decision.get("value_hash") or "")
    expected_length = _safe_int(answer_decision.get("value_length"))
    actual_hash = hashlib.sha256(approved_value.encode("utf-8")).hexdigest()
    return bool(expected_hash and expected_hash == actual_hash and expected_length == len(approved_value))


def _approved_option_matches(
    *,
    answer_decision: dict[str, Any],
    approved_option: str,
    candidate: dict[str, Any],
) -> bool:
    if not _approved_value_matches(answer_decision=answer_decision, approved_value=approved_option):
        return False
    return str(candidate.get("option_label") or "") == approved_option


def _approved_choice_matches(
    *,
    answer_decision: dict[str, Any],
    approved_value: str,
    candidate: dict[str, Any],
) -> bool:
    if not _approved_value_matches(answer_decision=answer_decision, approved_value=approved_value):
        return False
    return str(candidate.get("option_value") or "") == approved_value


def _action_gate_rejection_reason(*, action_gate: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    return _action_gate_rejection_reason_for_semantic_action(
        action_gate=action_gate,
        candidate=candidate,
        semantic_action="fill_field",
    )


def _action_gate_rejection_reason_for_semantic_action(
    *,
    action_gate: dict[str, Any],
    candidate: dict[str, Any],
    semantic_action: str,
) -> str | None:
    if action_gate.get("contract_version") != "pre_click_decision_v1":
        return "action_gate_missing_or_invalid"
    if action_gate.get("allowed") is not True:
        return "action_gate_rejected"
    if str(action_gate.get("semantic_action") or "").strip() != semantic_action:
        return "action_gate_semantic_action_mismatch"
    if action_gate.get("selected_candidate_id") != candidate.get("candidate_id"):
        return "action_gate_candidate_mismatch"
    if _point(action_gate.get("selected_click_point")) != _point(candidate.get("click_point")):
        return "action_gate_point_mismatch"
    return None


def _dispatch_click(
    *,
    result: dict[str, Any],
    candidate: dict[str, Any],
    dispatch: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    point = candidate["click_point"]
    result["one_time_action_authorized"] = True
    result["dispatch_attempted"] = True
    try:
        dispatch_result = dispatch(x=int(point["x"]), y=int(point["y"]))
    except Exception as exc:
        result["dispatch_success"] = False
        result["blocked_reason"] = "click_dispatch_failed"
        result["dispatch_error_type"] = type(exc).__name__
        return result
    result["dispatch_success"] = bool(dispatch_result.get("success")) if isinstance(dispatch_result, dict) else False
    if isinstance(dispatch_result, dict) and isinstance(dispatch_result.get("trace_path"), str):
        result["dispatch_trace_path"] = dispatch_result["trace_path"]
    return result


def _is_final_action(*, question: dict[str, Any], action_gate: dict[str, Any]) -> bool:
    if str(question.get("risk") or "").strip() == "final_submit":
        return True
    semantic_action = str(action_gate.get("semantic_action") or "").strip().casefold()
    if semantic_action in {"final_submit", "send", "confirm", "payment"}:
        return True
    label = " ".join(str(question.get("label") or "").casefold().split())
    return str(question.get("field_type") or "").strip() == "action" and any(term in label for term in _FINAL_ACTION_TERMS)


def _point(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        return {"x": int(value.get("x")), "y": int(value.get("y"))}
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _value_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
