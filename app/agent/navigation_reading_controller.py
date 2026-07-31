from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from app.agent.continuous_task_session import (
    create_continuous_task_session,
    observe_interface,
    record_action_result,
    record_agent_decision,
    record_gate_rejection,
    record_read_result,
    refresh_current_observation,
)
from app.agent.navigation_reading import (
    build_navigation_reading_context,
    validate_navigation_reading_decision,
)


CONTROLLER_REPORT_CONTRACT = "navigation_reading_controller_report_v1"
OPERATION_RESULT_CONTRACT = "navigation_reading_operation_result_v1"
FINAL_STATUSES = {
    "safe_stop",
    "needs_human_review",
    "paused_for_learning",
}
MODEL_DECISION_SOURCES = {
    "actual_model_call",
    "recorded_output_per_config",
}


def run_navigation_reading_controller(
    *,
    goal: str,
    workflow_id: str,
    session_id: str,
    observe_current: Callable[[], dict[str, Any]],
    load_interface_evidence: Callable[[str], dict[str, Any]],
    decide: Callable[[dict[str, Any]], dict[str, Any]],
    execute_operation: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    initial_read_progress: dict[str, Any] | None = None,
    max_steps: int = 12,
) -> dict[str, Any]:
    goal = _required_text(goal, "goal")
    limit = max(1, int(max_steps))
    session = create_continuous_task_session(
        session_id=session_id,
        workflow_id=workflow_id,
    )
    steps: list[dict[str, Any]] = []
    visited_interfaces: list[str] = []
    interface_visit_history: list[str] = []
    decision_sources: dict[str, int] = {}
    read_progress_by_interface: dict[str, dict[str, Any]] = {}
    if initial_read_progress:
        read_progress_by_interface["__initial__"] = deepcopy(initial_read_progress)

    observation = _validated_observation(observe_current())
    session, interface_evidence = _accept_full_observation(
        session=session,
        observation=observation,
        load_interface_evidence=load_interface_evidence,
    )
    _append_unique(visited_interfaces, observation["interface_id"])
    interface_visit_history.append(observation["interface_id"])

    for index in range(limit):
        if session.get("status") in FINAL_STATUSES:
            break
        if session.get("status") != "ready_for_agent_decision":
            break

        interface_id = observation["interface_id"]
        read_progress = read_progress_by_interface.get(interface_id)
        if read_progress is None and "__initial__" in read_progress_by_interface:
            read_progress = read_progress_by_interface.pop("__initial__")
            read_progress_by_interface[interface_id] = read_progress
        if read_progress is None:
            read_progress = session.get("current_read_state")

        context = build_navigation_reading_context(
            goal=goal,
            interface_evidence=interface_evidence,
            observation=observation,
            read_progress=read_progress,
            task_progress=_task_progress(
                steps=steps,
                interface_visit_history=interface_visit_history,
                read_progress_by_interface=read_progress_by_interface,
            ),
        )
        raw_decision = _validated_decision(decide(deepcopy(context)))
        decision_source = str(
            raw_decision.get("decision_source") or "unspecified"
        ).strip()
        decision_sources[decision_source] = decision_sources.get(decision_source, 0) + 1
        plan = validate_navigation_reading_decision(context, raw_decision)
        session = record_agent_decision(session, decision_plan=plan)
        step = {
            "sequence": index + 1,
            "interface_id": interface_id,
            "capture_id": observation["capture_id"],
            "choice_id": plan["choice_id"],
            "decision_type": plan["decision_type"],
            "semantic_action": plan["semantic_action"],
            "decision_source": decision_source,
            "decision_audit": deepcopy(raw_decision.get("decision_audit") or {}),
            "case_outcome": "pending",
            "action_executed": False,
            "dispatch_success": False,
            "effect_verified": False,
        }

        if plan["semantic_action"] == "safe_stop":
            step["case_outcome"] = "safe_stop"
            steps.append(step)
            break
        if plan["semantic_action"] == "stop_reading":
            read_progress_by_interface[interface_id] = _stopped_read_progress(
                read_progress
            )
            step["case_outcome"] = "bounded_read_stop"
            steps.append(step)
            continue

        operation = _validated_operation_result(
            execute_operation(deepcopy(plan), deepcopy(context))
        )
        if not _same_freshness(
            plan["freshness"],
            operation.get("source_freshness"),
        ):
            session = record_gate_rejection(
                session,
                reason="stale_operation_source",
                evidence=plan["freshness"],
            )
            session["stop_reason"] = "stale_operation_source"
            step["case_outcome"] = "safe_intercept"
            steps.append(step)
            break

        gate_result = operation["gate_result"]
        if gate_result.get("allowed") is not True:
            session = record_gate_rejection(
                session,
                reason=str(gate_result.get("reason") or "gate_rejected"),
                evidence=plan["freshness"],
            )
            step["case_outcome"] = "safe_intercept"
            steps.append(step)
            break

        if plan["semantic_action"] in {"read", "scroll"}:
            step["action_executed"] = bool(operation.get("action_dispatched"))
            step["dispatch_success"] = bool(operation.get("action_dispatched"))
            step["effect_verified"] = bool(operation.get("effect_verified"))
            session = record_read_result(
                session,
                action_type=plan["semantic_action"],
                action_dispatched=bool(operation.get("action_dispatched")),
                effect_verified=bool(operation.get("effect_verified")),
                read_report=operation.get("read_report"),
                evidence=plan["freshness"],
            )
            step["case_outcome"] = _read_outcome(session)
            steps.append(step)
            if session.get("status") in FINAL_STATUSES:
                break
            read_progress_by_interface[interface_id] = _merge_read_progress(
                previous=read_progress,
                read_report=operation["read_report"],
                action_type=plan["semantic_action"],
                selected_choice=_selected_choice(context, plan["choice_id"]),
            )
            observation = _validated_observation(observe_current())
            if observation["interface_id"] != interface_id:
                session["status"] = "needs_human_review"
                session["stop_reason"] = "unexpected_interface_after_read"
                break
            session = refresh_current_observation(
                session,
                interface_id=interface_id,
                surface_type=observation["surface_type"],
                evidence=_observation_evidence(observation),
            )
            interface_evidence = load_interface_evidence(interface_id)
            continue

        step["action_executed"] = bool(operation.get("action_executed"))
        step["dispatch_success"] = bool(operation.get("action_executed"))
        step["effect_verified"] = bool(operation.get("post_action_verified"))
        session = record_action_result(
            session,
            action_type=plan["semantic_action"],
            action_executed=bool(operation.get("action_executed")),
            post_action_verified=bool(operation.get("post_action_verified")),
            evidence=plan["freshness"],
            transition_audit={
                "agent_decision": deepcopy(plan),
                "gate_result": deepcopy(gate_result),
                "operation_result_contract": OPERATION_RESULT_CONTRACT,
            },
        )
        step["case_outcome"] = (
            "passed"
            if session.get("status") == "ready_for_observation"
            else "failed"
        )
        steps.append(step)
        if session.get("status") in FINAL_STATUSES:
            break

        observation = _validated_observation(observe_current())
        expected_target = str(plan.get("expected_target_interface_id") or "").strip()
        if expected_target and observation["interface_id"] != expected_target:
            session["status"] = "needs_human_review"
            session["stop_reason"] = "destination_interface_mismatch"
            break
        session, interface_evidence = _accept_full_observation(
            session=session,
            observation=observation,
            load_interface_evidence=load_interface_evidence,
        )
        _append_unique(visited_interfaces, observation["interface_id"])
        interface_visit_history.append(observation["interface_id"])

    if (
        len(steps) >= limit
        and session.get("status") not in FINAL_STATUSES
    ):
        session["status"] = "safe_stop"
        session["stop_reason"] = "max_steps_reached"

    return {
        "contract_version": CONTROLLER_REPORT_CONTRACT,
        "goal": goal,
        "workflow_id": workflow_id,
        "session_id": session_id,
        "final_status": session.get("status"),
        "stop_reason": session.get("stop_reason"),
        "visited_interfaces": visited_interfaces,
        "interface_visit_history": interface_visit_history,
        "steps": steps,
        "decision_source_breakdown": decision_sources,
        "actual_model_call_count": sum(
            count
            for source, count in decision_sources.items()
            if source in MODEL_DECISION_SOURCES
        ),
        "session": session,
        "safety": {
            "final_submit_forbidden": True,
            "final_submit_executed": False,
            "artifact_is_authorization": False,
        },
    }


def _task_progress(
    *,
    steps: list[dict[str, Any]],
    interface_visit_history: list[str],
    read_progress_by_interface: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    bounded_read_content_ids: list[str] = []
    completed_read_content_ids: list[str] = []
    for progress in read_progress_by_interface.values():
        if not isinstance(progress, dict):
            continue
        content_id = str(progress.get("content_id") or "").strip()
        if not content_id:
            continue
        if progress.get("status") == "reading_stopped":
            _append_unique(bounded_read_content_ids, content_id)
        if progress.get("status") == "reached_bottom":
            _append_unique(completed_read_content_ids, content_id)
    completed_choice_ids = [
        str(step.get("choice_id") or "").strip()
        for step in steps
        if step.get("case_outcome") in {"passed", "bounded_read_stop"}
        and str(step.get("choice_id") or "").strip()
    ]
    return {
        "sequence": len(steps),
        "visited_interfaces": list(interface_visit_history),
        "completed_choice_ids": completed_choice_ids,
        "last_outcome": (
            str(steps[-1].get("case_outcome") or "not_started")
            if steps
            else "not_started"
        ),
        "bounded_read_content_ids": bounded_read_content_ids,
        "completed_read_content_ids": completed_read_content_ids,
    }


def _accept_full_observation(
    *,
    session: dict[str, Any],
    observation: dict[str, Any],
    load_interface_evidence: Callable[[str], dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    interface_id = observation["interface_id"]
    evidence = load_interface_evidence(interface_id)
    memory_sha = _required_sha256(
        evidence.get("asset_sha256")
        or evidence.get("source_asset_sha256"),
        "asset_sha256",
    )
    current = observe_interface(
        session,
        interface_id=interface_id,
        surface_type=observation["surface_type"],
        memory_object_sha256=memory_sha,
        evidence=_observation_evidence(observation),
    )
    return current, evidence


def _validated_observation(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("contract_version") != "current_interface_observation_v1"
    ):
        raise ValueError("current_interface_observation_v1 is required")
    return {
        "contract_version": "current_interface_observation_v1",
        "interface_id": _required_text(value.get("interface_id"), "interface_id"),
        "surface_type": _required_text(value.get("surface_type"), "surface_type"),
        "capture_id": _required_text(value.get("capture_id"), "capture_id"),
        "screenshot_sha256": _required_text(
            value.get("screenshot_sha256"),
            "screenshot_sha256",
        ),
        "trace_path": _required_text(value.get("trace_path"), "trace_path"),
    }


def _validated_decision(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Agent decision must be an object")
    _required_text(value.get("choice_id"), "choice_id")
    _required_text(value.get("reason"), "reason")
    return deepcopy(value)


def _validated_operation_result(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or value.get("contract_version") != OPERATION_RESULT_CONTRACT
    ):
        raise ValueError(f"{OPERATION_RESULT_CONTRACT} is required")
    gate_result = value.get("gate_result")
    if not isinstance(gate_result, dict) or not isinstance(
        gate_result.get("allowed"),
        bool,
    ):
        raise ValueError("operation result requires a boolean Gate decision")
    return deepcopy(value)


def _observation_evidence(observation: dict[str, Any]) -> dict[str, str]:
    return {
        "capture_id": observation["capture_id"],
        "screenshot_sha256": observation["screenshot_sha256"],
        "trace_path": observation["trace_path"],
    }


def _same_freshness(expected: dict[str, Any], actual: Any) -> bool:
    if not isinstance(actual, dict):
        return False
    return all(
        str(actual.get(key) or "") == str(expected.get(key) or "")
        for key in ("capture_id", "screenshot_sha256", "trace_path")
    )


def _merge_read_progress(
    *,
    previous: dict[str, Any] | None,
    read_report: dict[str, Any],
    action_type: str,
    selected_choice: dict[str, Any],
) -> dict[str, Any]:
    result = deepcopy(previous or {})
    result.setdefault(
        "strategy",
        str(selected_choice.get("read_strategy") or "finite_detail"),
    )
    result.setdefault(
        "content_id",
        str(selected_choice.get("content_id") or "").strip() or None,
    )
    result.setdefault(
        "max_scrolls",
        int(
            selected_choice.get("max_scrolls")
            if selected_choice.get("max_scrolls") is not None
            else (3 if result["strategy"] == "infinite_collection" else 6)
        ),
    )
    result.setdefault("max_items", int(selected_choice.get("max_items") or 0))
    result["status"] = str(read_report.get("stop_reason") or "unknown")
    result["reached_bottom"] = read_report.get("reached_bottom") is True
    result["unique_line_count"] = int(read_report.get("unique_line_count") or 0)
    if action_type == "scroll":
        result["scrolls_used"] = int(result.get("scrolls_used") or 0) + 1
    return result


def _selected_choice(context: dict[str, Any], choice_id: str) -> dict[str, Any]:
    return next(
        (
            deepcopy(choice)
            for choice in context.get("choices") or []
            if isinstance(choice, dict) and choice.get("choice_id") == choice_id
        ),
        {},
    )


def _stopped_read_progress(previous: dict[str, Any] | None) -> dict[str, Any]:
    result = deepcopy(previous or {})
    result["status"] = "reading_stopped"
    result["completion"] = "bounded_stop"
    return result


def _read_outcome(session: dict[str, Any]) -> str:
    if session.get("status") == "safe_stop":
        return "safe_intercept"
    if session.get("status") == "needs_human_review":
        return "failed"
    return "passed"


def _append_unique(values: list[str], value: str) -> None:
    if not values or values[-1] != value:
        values.append(value)


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _required_sha256(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name).casefold()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{field_name} must be a SHA-256 hex digest")
    return text
