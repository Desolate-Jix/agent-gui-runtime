from __future__ import annotations

from copy import deepcopy
from typing import Any


SESSION_CONTRACT = "continuous_task_session_v1"
FINAL_ACTIONS = {"final_submit", "submit", "send", "complete", "confirm", "payment"}


def create_continuous_task_session(*, session_id: str, workflow_id: str) -> dict[str, Any]:
    return {
        "contract_version": SESSION_CONTRACT,
        "session_id": _required_text(session_id, "session_id"),
        "workflow_id": _required_text(workflow_id, "workflow_id"),
        "status": "ready_for_observation",
        "current_interface_id": None,
        "current_surface_type": None,
        "current_memory_object_sha256": None,
        "current_observation_evidence": None,
        "current_read_state": None,
        "current_form_step_context": None,
        "pending_agent_decision": None,
        "pending_learning": None,
        "pending_apply_confirmation": None,
        "stop_reason": None,
        "forbidden_next_actions": [],
        "events": [],
        "safety": {
            "final_submit_forbidden": True,
            "final_submit_executed": False,
            "historical_coordinates_forbidden": True,
            "current_capture_required": True,
            "gate_required": True,
        },
    }


def observe_interface(
    session: dict[str, Any],
    *,
    interface_id: str,
    surface_type: str,
    memory_object_sha256: str | None,
    evidence: dict[str, Any],
    learning_required: bool = True,
    knowledge_source: str = "reviewed_interface_memory",
) -> dict[str, Any]:
    current = _validated_session(session)
    previous_status = current.get("status")
    pending_decision = (
        deepcopy(current.get("pending_agent_decision"))
        if isinstance(current.get("pending_agent_decision"), dict)
        else None
    )
    interface_id = _required_text(interface_id, "interface_id")
    surface_type = _required_text(surface_type, "surface_type")
    evidence = _validated_evidence(evidence)
    current["current_interface_id"] = interface_id
    current["current_surface_type"] = surface_type
    current["current_memory_object_sha256"] = memory_object_sha256
    current["current_observation_evidence"] = evidence
    current["current_read_state"] = None
    current["current_form_step_context"] = None
    current["pending_agent_decision"] = None
    current["pending_apply_confirmation"] = None
    _append_event(
        current,
        "interface_observed",
        {
            "interface_id": interface_id,
            "surface_type": surface_type,
            "memory_available": bool(memory_object_sha256),
            "learning_required": bool(learning_required),
            "knowledge_source": _required_text(knowledge_source, "knowledge_source"),
            "evidence": evidence,
        },
    )

    if surface_type in {"external_ats", "external_ats_login", "login_required_external_ats"}:
        return _safe_stop(
            current,
            reason="external_ats_not_supported",
            forbidden_next_actions=["continue_next_step", "fill_field", "final_submit"],
        )
    if surface_type == "final_submit_visible":
        return _safe_stop(
            current,
            reason="final_submit_visible",
            forbidden_next_actions=["final_submit", "send", "complete", "confirm"],
        )
    if previous_status == "waiting_for_destination_observation":
        expected_interface_id = str(
            (pending_decision or {}).get("expected_target_interface_id") or ""
        ).strip()
        if expected_interface_id and interface_id != expected_interface_id:
            current["pending_agent_decision"] = None
            _append_event(
                current,
                "destination_observation_rejected",
                {
                    "expected_interface_id": expected_interface_id,
                    "actual_interface_id": interface_id,
                    "evidence": evidence,
                },
            )
            return _safe_stop(
                current,
                reason="destination_interface_mismatch",
                forbidden_next_actions=["click", "scroll", "input", "final_submit"],
            )
        current["pending_agent_decision"] = None
        _append_event(
            current,
            "destination_observation_verified",
            {
                "expected_interface_id": expected_interface_id or None,
                "actual_interface_id": interface_id,
                "evidence": evidence,
            },
        )
    if learning_required and not memory_object_sha256:
        current["status"] = "paused_for_learning"
        current["pending_learning"] = {
            "interface_id": interface_id,
            "surface_type": surface_type,
            "source_capture_id": evidence["capture_id"],
            "required_result": "reviewed_interface_memory_publish",
        }
        return current

    current["status"] = "ready_for_agent_decision"
    current["pending_learning"] = None
    return current


def refresh_current_observation(
    session: dict[str, Any],
    *,
    interface_id: str,
    surface_type: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    current = _validated_session(session)
    if current.get("status") != "ready_for_agent_decision":
        raise ValueError("continuous session is not ready for observation refresh")
    interface_id = _required_text(interface_id, "interface_id")
    if interface_id != current.get("current_interface_id"):
        raise ValueError("observation refresh cannot change the current interface")
    surface_type = _required_text(surface_type, "surface_type")
    evidence = _validated_evidence(evidence)
    current["current_surface_type"] = surface_type
    current["current_observation_evidence"] = evidence
    current["current_form_step_context"] = None
    current["pending_agent_decision"] = None
    _append_event(
        current,
        "observation_refreshed",
        {
            "interface_id": interface_id,
            "surface_type": surface_type,
            "evidence": evidence,
            "read_state_preserved": current.get("current_read_state") is not None,
        },
    )
    return current


def resume_after_learning(
    session: dict[str, Any],
    *,
    interface_id: str,
    memory_object_sha256: str,
) -> dict[str, Any]:
    current = _validated_session(session)
    if current.get("status") != "paused_for_learning":
        raise ValueError("continuous session is not paused for learning")
    pending = current.get("pending_learning") if isinstance(current.get("pending_learning"), dict) else {}
    if pending.get("interface_id") != interface_id:
        raise ValueError("learned interface does not match pending learning state")
    current["current_memory_object_sha256"] = _required_text(memory_object_sha256, "memory_object_sha256")
    current["pending_learning"] = None
    current["status"] = "ready_for_agent_decision"
    _append_event(
        current,
        "learning_completed",
        {
            "interface_id": interface_id,
            "memory_object_sha256": memory_object_sha256,
            "reviewed_memory_required": True,
        },
    )
    return current


def bind_form_step_context(
    session: dict[str, Any],
    *,
    capture_id: str,
    inventory_fingerprint: str,
    grounding_fingerprint: str,
) -> dict[str, Any]:
    current = _validated_session(session)
    if current.get("status") != "ready_for_agent_decision":
        raise ValueError("continuous session is not ready for form step binding")
    observed = current.get("current_observation_evidence")
    capture_id = _required_text(capture_id, "capture_id")
    if not isinstance(observed, dict) or observed.get("capture_id") != capture_id:
        raise ValueError("form step context does not use the current capture")
    current["current_form_step_context"] = {
        "capture_id": capture_id,
        "inventory_fingerprint": _required_text(
            inventory_fingerprint,
            "inventory_fingerprint",
        ),
        "grounding_fingerprint": _required_text(
            grounding_fingerprint,
            "grounding_fingerprint",
        ),
        "valid": True,
        "invalidated_by": None,
    }
    _append_event(
        current,
        "form_step_context_bound",
        {
            "capture_id": capture_id,
            "inventory_fingerprint": current["current_form_step_context"]["inventory_fingerprint"],
            "grounding_fingerprint": current["current_form_step_context"]["grounding_fingerprint"],
            "artifact_is_authorization": False,
        },
    )
    return current


def record_form_workflow_turn(
    session: dict[str, Any],
    *,
    decision: dict[str, Any],
) -> dict[str, Any]:
    current = _validated_session(session)
    if current.get("status") != "ready_for_agent_decision":
        raise ValueError("continuous session is not ready for a form workflow turn")
    if (
        not isinstance(decision, dict)
        or decision.get("contract_version") != "form_workflow_turn_decision_v1"
    ):
        raise ValueError("invalid form workflow turn decision")
    action_type = _required_text(
        decision.get("action_type") or decision.get("semantic_action"),
        "action_type",
    ).casefold()
    if action_type in FINAL_ACTIONS:
        raise ValueError("final submit action is forbidden")
    observed = current.get("current_observation_evidence")
    context = current.get("current_form_step_context")
    decision_capture_id = _required_text(decision.get("capture_id"), "capture_id")
    if (
        not isinstance(observed, dict)
        or observed.get("capture_id") != decision_capture_id
        or not isinstance(context, dict)
        or context.get("valid") is not True
        or context.get("capture_id") != decision_capture_id
    ):
        raise ValueError("form workflow turn does not use current bound evidence")

    if action_type == "safe_stop":
        return _safe_stop(
            current,
            reason=str(decision.get("reason") or "form_workflow_safe_stop"),
            forbidden_next_actions=["click", "input", "continue_next_step", "final_submit"],
        )
    if action_type == "request_user_review":
        current["status"] = "needs_human_review"
        current["pending_agent_decision"] = None
        _append_event(
            current,
            "form_user_review_requested",
            {
                "question_id": decision.get("question_id"),
                "reason": decision.get("reason"),
                "action_executed": False,
            },
        )
        return current
    if action_type not in {
        "fill_field",
        "select_option",
        "upload_file",
        "continue_next_step",
    }:
        raise ValueError("unsupported form workflow action")
    if decision.get("operation_count") != 1 or not isinstance(decision.get("operation"), dict):
        raise ValueError("form workflow turn must contain exactly one operation")

    current["pending_agent_decision"] = deepcopy(decision)
    current["status"] = "ready_for_operation"
    _append_event(
        current,
        "form_workflow_turn_recorded",
        {
            "action_type": action_type,
            "question_id": decision.get("question_id"),
            "capture_id": decision_capture_id,
            "artifact_is_authorization": False,
            "current_capture_required": True,
            "gate_required": True,
        },
    )
    return current


def record_agent_decision(
    session: dict[str, Any],
    *,
    decision_plan: dict[str, Any],
) -> dict[str, Any]:
    current = _validated_session(session)
    if current.get("status") != "ready_for_agent_decision":
        raise ValueError("continuous session is not ready for an Agent decision")
    if (
        not isinstance(decision_plan, dict)
        or decision_plan.get("contract_version")
        != "navigation_reading_decision_plan_v1"
    ):
        raise ValueError("invalid navigation reading decision plan")
    interface_id = _required_text(decision_plan.get("interface_id"), "interface_id")
    if interface_id != current.get("current_interface_id"):
        raise ValueError("Agent decision interface does not match current interface")
    semantic_action = _required_text(
        decision_plan.get("semantic_action"),
        "semantic_action",
    ).casefold()
    if semantic_action in FINAL_ACTIONS:
        raise ValueError("final submit action is forbidden")
    freshness = _validated_evidence(decision_plan.get("freshness"))
    observed = current.get("current_observation_evidence")
    if not isinstance(observed, dict) or freshness["capture_id"] != observed.get("capture_id"):
        raise ValueError("Agent decision does not use the current capture")

    if semantic_action == "safe_stop":
        return _safe_stop(
            current,
            reason=str(decision_plan.get("choice_id") or "agent_requested_safe_stop"),
            forbidden_next_actions=["click", "scroll", "input", "final_submit"],
        )
    if semantic_action == "stop_reading":
        read_state = deepcopy(current.get("current_read_state") or {})
        read_state["status"] = "reading_stopped"
        read_state["completion"] = "bounded_stop"
        current["current_read_state"] = read_state
        current["status"] = "ready_for_agent_decision"
        current["pending_agent_decision"] = None
        _append_event(
            current,
            "reading_stopped",
            {
                "decision_plan": deepcopy(decision_plan),
                "task_continues": True,
                "final_submit_executed": False,
            },
        )
        return current

    current["pending_agent_decision"] = deepcopy(decision_plan)
    current["status"] = "ready_for_operation"
    _append_event(
        current,
        "agent_decision_recorded",
        {
            "decision_plan": deepcopy(decision_plan),
            "artifact_is_authorization": False,
            "current_capture_required": True,
            "gate_required": True,
        },
    )
    return current


def request_apply_entry_confirmation(
    session: dict[str, Any],
    *,
    job_id: str,
    job_title: str,
) -> dict[str, Any]:
    current = _validated_session(session)
    if current.get("status") != "ready_for_agent_decision":
        raise ValueError("continuous session is not ready for apply entry confirmation")
    current["status"] = "awaiting_apply_entry_confirmation"
    current["pending_apply_confirmation"] = {
        "job_id": _required_text(job_id, "job_id"),
        "job_title": _required_text(job_title, "job_title"),
        "action_type": "open_apply_flow",
    }
    _append_event(current, "apply_entry_confirmation_requested", current["pending_apply_confirmation"])
    return current


def confirm_apply_entry(session: dict[str, Any], *, approved: bool) -> dict[str, Any]:
    current = _validated_session(session)
    if current.get("status") != "awaiting_apply_entry_confirmation":
        raise ValueError("continuous session is not awaiting apply entry confirmation")
    pending = deepcopy(current.get("pending_apply_confirmation"))
    current["pending_apply_confirmation"] = None
    _append_event(
        current,
        "apply_entry_confirmation_recorded",
        {"approved": bool(approved), "job": pending},
    )
    if not approved:
        return _safe_stop(
            current,
            reason="apply_entry_not_approved",
            forbidden_next_actions=["open_apply_flow", "fill_field", "final_submit"],
        )
    current["status"] = "ready_for_agent_decision"
    return current


def record_gate_rejection(
    session: dict[str, Any],
    *,
    reason: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    current = _validated_session(session)
    if current.get("status") != "ready_for_operation":
        raise ValueError("continuous session is not awaiting an Operation")
    pending = (
        current.get("pending_agent_decision")
        if isinstance(current.get("pending_agent_decision"), dict)
        else None
    )
    if pending is None:
        raise ValueError("Gate rejection requires a pending Agent decision")
    current["pending_agent_decision"] = None
    _append_event(
        current,
        "gate_rejected",
        {
            "reason": _required_text(reason, "gate rejection reason"),
            "semantic_action": pending.get("semantic_action"),
            "evidence": _validated_evidence(evidence),
            "action_executed": False,
        },
    )
    return _safe_stop(
        current,
        reason="gate_rejected",
        forbidden_next_actions=["click", "scroll", "input", "final_submit"],
    )


def record_action_result(
    session: dict[str, Any],
    *,
    action_type: str,
    action_executed: bool,
    post_action_verified: bool,
    evidence: dict[str, Any],
    transition_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = _validated_session(session)
    action_type = _required_text(action_type, "action_type").casefold()
    if action_type in FINAL_ACTIONS:
        raise ValueError("final submit action is forbidden")
    pending = (
        current.get("pending_agent_decision")
        if isinstance(current.get("pending_agent_decision"), dict)
        else None
    )
    is_form_turn = (
        isinstance(pending, dict)
        and pending.get("contract_version") == "form_workflow_turn_decision_v1"
    )
    if pending and str(pending.get("semantic_action") or "").casefold() != action_type:
        raise ValueError("action result does not match pending Agent decision")
    evidence = _validated_evidence(evidence)
    if not action_executed or not post_action_verified:
        current["status"] = "needs_human_review"
        _append_event(
            current,
            "action_not_verified",
            {
                "action_type": action_type,
                "action_executed": bool(action_executed),
                "post_action_verified": bool(post_action_verified),
                "evidence": evidence,
                "transition_audit": deepcopy(transition_audit or {}),
            },
        )
        if is_form_turn:
            _invalidate_form_step_context(current, invalidated_by="verification_failed")
        return current
    current["status"] = "waiting_for_destination_observation"
    _append_event(
        current,
        "action_verified",
        {
            "action_type": action_type,
            "action_executed": True,
            "post_action_verified": True,
            "verification_scope": "action_effect_only",
            "destination_observation_required": True,
            "evidence": evidence,
            "transition_audit": deepcopy(transition_audit or {}),
        },
    )
    if is_form_turn:
        _invalidate_form_step_context(current, invalidated_by=action_type)
    return current


def record_read_result(
    session: dict[str, Any],
    *,
    action_type: str,
    action_dispatched: bool,
    effect_verified: bool,
    read_report: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    current = _validated_session(session)
    action_type = _required_text(action_type, "action_type").casefold()
    if action_type not in {"read", "scroll"}:
        raise ValueError("read result action_type must be read or scroll")
    if (
        not isinstance(read_report, dict)
        or read_report.get("contract_version") != "read_region_batch_v1"
    ):
        raise ValueError("read_region_batch_v1 report is required")
    evidence = _validated_evidence(evidence)
    stop_reason = str(read_report.get("stop_reason") or "unknown")
    wrong_scope = (
        read_report.get("wrong_scope_detected") is True
        or stop_reason == "wrong_scope_detected"
    )
    if wrong_scope:
        current["pending_agent_decision"] = None
        current["current_read_state"] = {
            "status": "wrong_scope_detected",
            "completion": "blocked",
            "unique_line_count": int(read_report.get("unique_line_count") or 0),
            "evidence": evidence,
        }
        return _safe_stop(
            current,
            reason="wrong_scope_detected",
            forbidden_next_actions=["scroll", "click", "input", "final_submit"],
        )

    if not action_dispatched or not effect_verified:
        current["status"] = "needs_human_review"
        current["pending_agent_decision"] = None
        _append_event(
            current,
            "read_effect_not_verified",
            {
                "action_type": action_type,
                "action_dispatched": bool(action_dispatched),
                "effect_verified": bool(effect_verified),
                "read_report": deepcopy(read_report),
                "evidence": evidence,
            },
        )
        return current

    reached_bottom = (
        read_report.get("reached_bottom") is True
        or stop_reason == "reached_bottom"
    )
    current["current_read_state"] = {
        "status": stop_reason,
        "completion": (
            "complete"
            if reached_bottom
            else str(read_report.get("completion_status") or "incomplete")
        ),
        "reached_bottom": reached_bottom,
        "unique_line_count": int(read_report.get("unique_line_count") or 0),
        "evidence": evidence,
    }
    current["pending_agent_decision"] = None
    current["status"] = "ready_for_agent_decision"
    _append_event(
        current,
        "read_effect_verified",
        {
            "action_type": action_type,
            "action_dispatched": True,
            "effect_verified": True,
            "read_state": deepcopy(current["current_read_state"]),
        },
    )
    return current


def _safe_stop(
    session: dict[str, Any],
    *,
    reason: str,
    forbidden_next_actions: list[str],
) -> dict[str, Any]:
    session["status"] = "safe_stop"
    session["stop_reason"] = reason
    session["forbidden_next_actions"] = list(forbidden_next_actions)
    session["safety"]["final_submit_executed"] = False
    _append_event(
        session,
        "safe_stop",
        {
            "reason": reason,
            "forbidden_next_actions": list(forbidden_next_actions),
            "final_submit_executed": False,
        },
    )
    return session


def _invalidate_form_step_context(
    session: dict[str, Any],
    *,
    invalidated_by: str,
) -> None:
    previous = session.get("current_form_step_context")
    session["current_form_step_context"] = {
        "capture_id": None,
        "inventory_fingerprint": None,
        "grounding_fingerprint": None,
        "valid": False,
        "invalidated_by": invalidated_by,
    }
    session["current_observation_evidence"] = None
    _append_event(
        session,
        "form_step_context_invalidated",
        {
            "invalidated_by": invalidated_by,
            "previous_capture_id": (
                previous.get("capture_id") if isinstance(previous, dict) else None
            ),
            "capture_invalidated": True,
            "inventory_invalidated": True,
            "grounding_invalidated": True,
        },
    )


def _validated_session(session: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(session, dict) or session.get("contract_version") != SESSION_CONTRACT:
        raise ValueError("invalid continuous task session")
    if session.get("status") == "safe_stop":
        raise ValueError("continuous task session already stopped")
    current = deepcopy(session)
    current.setdefault("current_observation_evidence", None)
    current.setdefault("current_read_state", None)
    current.setdefault("current_form_step_context", None)
    current.setdefault("pending_agent_decision", None)
    return current


def _validated_evidence(evidence: dict[str, Any]) -> dict[str, str]:
    if not isinstance(evidence, dict):
        raise ValueError("continuous task session evidence is required")
    validated = {
        "capture_id": _required_text(evidence.get("capture_id"), "capture_id"),
        "screenshot_sha256": _required_text(evidence.get("screenshot_sha256"), "screenshot_sha256"),
        "trace_path": _required_text(evidence.get("trace_path"), "trace_path"),
    }
    screenshot_path = str(evidence.get("screenshot_path") or "").strip()
    if screenshot_path:
        validated["screenshot_path"] = screenshot_path
    return validated


def _append_event(session: dict[str, Any], event_type: str, details: dict[str, Any]) -> None:
    events = session.setdefault("events", [])
    events.append(
        {
            "sequence": len(events) + 1,
            "event_type": event_type,
            "details": deepcopy(details),
        }
    )


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
