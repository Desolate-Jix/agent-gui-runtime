from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "form_workflow_turn_decision_v1"
FORM_INVENTORY_CONTRACT = "form_question_inventory_v1"
FORM_ANSWER_PLAN_CONTRACT = "form_answer_plan_v1"
ACTION_TYPES = {
    "fill_field",
    "select_option",
    "upload_file",
    "continue_next_step",
    "request_user_review",
    "safe_stop",
}
AUTO_FILL_POLICIES = {
    "auto_fill",
    "derived_with_evidence",
    "approved_reviewed_answer",
    "reused_reviewed_policy",
    "reviewed_file_upload",
}
SELECTION_FIELD_TYPES = {"select", "radio", "checkbox"}
REVIEW_POLICIES = {"needs_user_review", "blocked_sensitive", "unsupported"}


def plan_form_workflow_turn(
    *,
    interface_id: str,
    surface_status: str,
    observation_evidence: dict[str, Any] | None,
    inventory: dict[str, Any] | None,
    answer_plan: dict[str, Any] | None,
    completed_question_ids: list[str] | None,
    previous_verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    interface_id = _required_text(interface_id, "interface_id")
    status = _required_text(surface_status, "surface_status").casefold()
    evidence = observation_evidence if isinstance(observation_evidence, dict) else {}
    capture_id = _clean(evidence.get("capture_id"))

    if status != "ready":
        reason = status if status in {"login_required", "wrong_surface", "blocked_surface"} else "surface_not_ready"
        return _stop(interface_id=interface_id, capture_id=capture_id, reason=reason)
    if isinstance(previous_verification, dict) and previous_verification.get("verified") is False:
        return _stop(
            interface_id=interface_id,
            capture_id=capture_id,
            reason="previous_action_verification_failed",
        )
    if not capture_id:
        return _stop(interface_id=interface_id, capture_id=None, reason="observation_evidence_missing")

    inventory_payload = inventory if isinstance(inventory, dict) else {}
    plan_payload = answer_plan if isinstance(answer_plan, dict) else {}
    if (
        inventory_payload.get("contract_version") != FORM_INVENTORY_CONTRACT
        or plan_payload.get("contract_version") != FORM_ANSWER_PLAN_CONTRACT
    ):
        return _stop(
            interface_id=interface_id,
            capture_id=capture_id,
            reason="invalid_form_step_contract",
        )
    if (
        _clean(inventory_payload.get("capture_id")) != capture_id
        or _clean(plan_payload.get("capture_id")) != capture_id
    ):
        return _stop(
            interface_id=interface_id,
            capture_id=capture_id,
            reason="stale_form_step_evidence",
        )
    if inventory_payload.get("danger_actions"):
        return _stop(
            interface_id=interface_id,
            capture_id=capture_id,
            reason="final_submit_visible",
            unsafe_prevented=True,
        )

    completed = {_clean(item) for item in completed_question_ids or [] if _clean(item)}
    decisions = {
        _clean(item.get("question_id")): item
        for item in plan_payload.get("decisions") or []
        if isinstance(item, dict) and _clean(item.get("question_id"))
    }
    for question in _ordered_questions(inventory_payload):
        question_id = _question_id(question)
        if not question_id or question_id in completed:
            continue
        decision = decisions.get(question_id)
        if decision is None:
            return _review(
                interface_id=interface_id,
                capture_id=capture_id,
                question_id=question_id,
                reason="answer_decision_missing",
            )
        policy = _clean(decision.get("policy")).casefold()
        if policy == "final_submit":
            return _stop(
                interface_id=interface_id,
                capture_id=capture_id,
                reason="final_submit_visible",
                unsafe_prevented=True,
            )
        if policy in REVIEW_POLICIES or policy not in AUTO_FILL_POLICIES:
            return _review(
                interface_id=interface_id,
                capture_id=capture_id,
                question_id=question_id,
                reason=policy or "answer_policy_unknown",
            )
        field_type = _clean(
            decision.get("field_type") or question.get("field_type") or question.get("answer_type")
        ).casefold()
        if field_type == "file_upload" and policy == "reviewed_file_upload":
            action_type = "upload_file"
        else:
            action_type = "select_option" if field_type in SELECTION_FIELD_TYPES else "fill_field"
        return _operation(
            interface_id=interface_id,
            capture_id=capture_id,
            action_type=action_type,
            question_id=question_id,
            field_type=field_type or "unknown",
            value_reference=decision.get("value_reference"),
            invalidates_after_success=["capture", "grounding"],
            expected_target_interface_id=interface_id,
        )

    continue_action = inventory_payload.get("continue_action")
    if isinstance(continue_action, dict):
        if _clean(continue_action.get("capture_id")) != capture_id:
            return _stop(
                interface_id=interface_id,
                capture_id=capture_id,
                reason="stale_form_step_evidence",
            )
        return _operation(
            interface_id=interface_id,
            capture_id=capture_id,
            action_type="continue_next_step",
            question_id=None,
            field_type="action",
            value_reference=None,
            invalidates_after_success=["capture", "form_inventory", "grounding"],
            expected_target_interface_id=None,
            target_id=_clean(continue_action.get("action_id")) or None,
        )
    return _review(
        interface_id=interface_id,
        capture_id=capture_id,
        question_id=None,
        reason="no_safe_form_action_available",
    )


def _ordered_questions(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for collection in ("questions", "fields"):
        for item in inventory.get(collection) or []:
            if not isinstance(item, dict):
                continue
            question_id = _question_id(item)
            if not question_id or question_id in seen:
                continue
            seen.add(question_id)
            ordered.append(item)
    return ordered


def _question_id(item: dict[str, Any]) -> str:
    return _clean(item.get("question_id") or item.get("field_id") or item.get("id"))


def _base(*, interface_id: str, capture_id: str | None, action_type: str, reason: str) -> dict[str, Any]:
    if action_type not in ACTION_TYPES:
        raise ValueError(f"unsupported form workflow action: {action_type}")
    return {
        "contract_version": CONTRACT_VERSION,
        "interface_id": interface_id,
        "capture_id": capture_id,
        "semantic_action": action_type,
        "action_type": action_type,
        "reason": reason,
        "question_id": None,
        "operation": None,
        "operation_count": 0,
        "requires_gate": False,
        "requires_post_action_verification": False,
        "requires_fresh_observation_after_action": False,
        "invalidates_after_success": [],
        "dispatch_authorized": False,
        "artifact_is_authorization": False,
        "unsafe_prevented": False,
    }


def _operation(
    *,
    interface_id: str,
    capture_id: str,
    action_type: str,
    question_id: str | None,
    field_type: str,
    value_reference: Any,
    invalidates_after_success: list[str],
    expected_target_interface_id: str | None,
    target_id: str | None = None,
) -> dict[str, Any]:
    result = _base(
        interface_id=interface_id,
        capture_id=capture_id,
        action_type=action_type,
        reason="next_safe_form_action",
    )
    result.update(
        {
            "question_id": question_id,
            "expected_target_interface_id": expected_target_interface_id,
            "operation": {
                "action_type": action_type,
                "question_id": question_id,
                "target_id": target_id or question_id,
                "field_type": field_type,
                "value_reference": value_reference,
                "capture_id": capture_id,
                "requires_fresh_grounding": True,
            },
            "operation_count": 1,
            "requires_gate": True,
            "requires_post_action_verification": True,
            "requires_fresh_observation_after_action": True,
            "invalidates_after_success": list(invalidates_after_success),
        }
    )
    return result


def _review(
    *,
    interface_id: str,
    capture_id: str,
    question_id: str | None,
    reason: str,
) -> dict[str, Any]:
    result = _base(
        interface_id=interface_id,
        capture_id=capture_id,
        action_type="request_user_review",
        reason=reason,
    )
    result["question_id"] = question_id
    return result


def _stop(
    *,
    interface_id: str,
    capture_id: str | None,
    reason: str,
    unsafe_prevented: bool = False,
) -> dict[str, Any]:
    result = _base(
        interface_id=interface_id,
        capture_id=capture_id,
        action_type="safe_stop",
        reason=reason,
    )
    result["unsafe_prevented"] = bool(unsafe_prevented)
    return result


def _required_text(value: Any, field_name: str) -> str:
    text = _clean(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
