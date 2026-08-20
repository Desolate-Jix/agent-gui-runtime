from __future__ import annotations

from copy import deepcopy
from typing import Any


CONTEXT_CONTRACT = "navigation_reading_agent_context_v1"
DECISION_PLAN_CONTRACT = "navigation_reading_decision_plan_v1"
_READ_STRATEGIES = {"finite_detail", "infinite_collection"}
_FORBIDDEN_ACTIONS = {
    "confirm",
    "final_apply",
    "final_submit",
    "payment",
    "send",
    "submit",
}


def build_navigation_reading_context(
    *,
    goal: str,
    interface_evidence: dict[str, Any],
    observation: dict[str, Any],
    read_progress: dict[str, Any] | None = None,
    task_progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建只含语义选择的 Agent 上下文，不携带可复用坐标。"""

    goal = _required_text(goal, "goal")
    evidence = _validated_interface_evidence(interface_evidence)
    current_observation = _validated_observation(
        observation,
        expected_interface_id=evidence["interface"]["interface_id"],
    )
    read_state = _normalized_read_state(read_progress)
    progress = _normalized_task_progress(task_progress)

    choices: list[dict[str, Any]] = []
    if read_state["status"] == "wrong_scope_detected":
        choices.append(_safe_stop_choice("wrong_scope_detected"))
    elif (
        read_state["strategy"] == "infinite_collection"
        and read_state["completion"] == "budget_exhausted"
        and read_state["status"] != "reading_stopped"
    ):
        choices.append(_stop_reading_choice())
        choices.append(_safe_stop_choice("agent_requested_safe_stop"))
    else:
        choices.extend(
            _transition_choices(
                evidence.get("available_actions"),
                semantic_controls=evidence.get("semantic_controls"),
                read_state=read_state,
            )
        )
        choices.extend(
            _read_choices(
                evidence.get("deferred_reads"),
                read_state=read_state,
            )
        )
        if _can_scroll(read_state):
            choices.append(
                {
                    "choice_id": "scroll:current_read_region",
                    "decision_type": "scroll_for_more",
                    "semantic_action": "scroll",
                    "display_name": "Scroll current read region",
                    "agent_description": (
                        "Scroll the currently reviewed read region, then verify "
                        "target content changed and non-target panes stayed stable."
                    ),
                    "expected_effect": {
                        "target_content_must_change_or_reach_bottom": True,
                        "non_target_panes_must_remain_stable": True,
                    },
                }
            )
        if (
            read_state["strategy"] == "infinite_collection"
            and read_state["status"] != "reading_stopped"
        ):
            choices.append(_stop_reading_choice())
        choices.append(_safe_stop_choice("agent_requested_safe_stop"))

    completed_choice_ids = set(progress["completed_choice_ids"])
    choices = [
        choice
        for choice in choices
        if not (
            choice.get("decision_type") == "follow_transition"
            and choice.get("choice_id") in completed_choice_ids
        )
    ]

    execution = evidence.get("execution_contract")
    return {
        "contract_version": CONTEXT_CONTRACT,
        "goal": goal,
        "interface": deepcopy(evidence["interface"]),
        "current_observation": current_observation,
        "read_state": read_state,
        "task_progress": progress,
        "semantic_controls": deepcopy(evidence.get("semantic_controls") or []),
        "choices": choices,
        "verification_rules": deepcopy(evidence.get("verification_rules") or []),
        "blockers": deepcopy(evidence.get("blockers") or []),
        "execution_contract": {
            "current_capture_required": True,
            "current_target_resolution_required": True,
            "historical_coordinates_forbidden": True,
            "gate_required": True,
            "operation_required": True,
            "trace_required": True,
            "post_action_verification_required": True,
            "final_submit_forbidden": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "source_contract": deepcopy(execution or {}),
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _normalized_task_progress(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {
            "sequence": 0,
            "visited_interfaces": [],
            "completed_choice_ids": [],
            "last_outcome": "not_started",
            "bounded_read_content_ids": [],
            "completed_read_content_ids": [],
        }
    if not isinstance(value, dict):
        raise ValueError("task_progress must be an object")
    return {
        "sequence": _non_negative_int(value.get("sequence"), "task progress sequence"),
        "visited_interfaces": _semantic_text_list(
            value.get("visited_interfaces"),
            "visited_interfaces",
        ),
        "completed_choice_ids": _semantic_text_list(
            value.get("completed_choice_ids"),
            "completed_choice_ids",
        ),
        "last_outcome": str(value.get("last_outcome") or "not_started").strip(),
        "bounded_read_content_ids": _semantic_text_list(
            value.get("bounded_read_content_ids"),
            "bounded_read_content_ids",
        ),
        "completed_read_content_ids": _semantic_text_list(
            value.get("completed_read_content_ids"),
            "completed_read_content_ids",
        ),
    }


def _semantic_text_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [
        _required_text(item, field_name)
        for item in value
    ]


def validate_navigation_reading_decision(
    context: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """把 Agent 选择校验为单步语义计划，真实目标仍需 Operation 重新定位。"""

    if not isinstance(context, dict) or context.get("contract_version") != CONTEXT_CONTRACT:
        raise ValueError("invalid navigation reading Agent context")
    if not isinstance(decision, dict):
        raise ValueError("Agent decision is required")
    choice_id = _required_text(decision.get("choice_id"), "choice_id")
    reason = _required_text(decision.get("reason"), "reason")
    selected = next(
        (
            item
            for item in context.get("choices") or []
            if isinstance(item, dict) and item.get("choice_id") == choice_id
        ),
        None,
    )
    if selected is None:
        raise ValueError(f"Agent choice is not available: {choice_id}")

    semantic_action = _normalize_action(selected.get("semantic_action"))
    if _is_forbidden_action(semantic_action):
        raise ValueError("final or destructive action is forbidden")
    observation = context.get("current_observation")
    if not isinstance(observation, dict):
        raise ValueError("current observation is missing")

    return {
        "contract_version": DECISION_PLAN_CONTRACT,
        "goal": context.get("goal"),
        "interface_id": (context.get("interface") or {}).get("interface_id"),
        "choice_id": choice_id,
        "decision_type": selected.get("decision_type"),
        "semantic_action": semantic_action,
        "reason": reason,
        "source_control_id": selected.get("source_control_id"),
        "operation_goal": selected.get("operation_goal"),
        "content_id": selected.get("content_id"),
        "expected_target_interface_id": selected.get("target_interface_id"),
        "expected_effect": deepcopy(selected.get("expected_effect") or {}),
        "freshness": {
            "capture_id": observation["capture_id"],
            "screenshot_sha256": observation["screenshot_sha256"],
            "trace_path": observation["trace_path"],
        },
        "requires_operation_resolution": semantic_action not in {
            "safe_stop",
            "stop_reading",
        },
        "requires_gate": semantic_action not in {"safe_stop", "stop_reading"},
        "requires_post_action_verification": semantic_action not in {
            "safe_stop",
            "stop_reading",
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _validated_interface_evidence(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("contract_version") != "agent_evidence_context_v1":
        raise ValueError("navigation reading requires agent_evidence_context_v1")
    readiness = value.get("readiness") if isinstance(value.get("readiness"), dict) else {}
    if readiness.get("status") != "agent_usable":
        raise ValueError("navigation reading requires an agent_usable reviewed interface")
    interface = value.get("interface") if isinstance(value.get("interface"), dict) else {}
    _required_text(interface.get("interface_id"), "interface_id")
    if value.get("artifact_is_authorization") is not False:
        raise ValueError("reviewed interface evidence must not authorize execution")
    _validate_actionable_semantic_controls(value)
    return deepcopy(value)


def _validate_actionable_semantic_controls(value: dict[str, Any]) -> None:
    controls = {
        str(item.get("control_id") or ""): item
        for item in value.get("semantic_controls") or []
        if isinstance(item, dict) and str(item.get("control_id") or "")
    }
    for action in value.get("available_actions") or []:
        if not isinstance(action, dict):
            continue
        source_control_id = _required_text(
            action.get("source_control_id"),
            "source_control_id",
        )
        control = controls.get(source_control_id)
        if not control:
            raise ValueError("available action requires a semantic control")
        semantic_name = str(control.get("semantic_name") or "").strip()
        purpose = str(control.get("purpose") or "").strip()
        risk_class = str(control.get("risk_class") or "").strip()
        action_type = _normalize_action(action.get("action_type"))
        allowed_actions = control.get("allowed_actions")
        verification = control.get("verification_rule")
        has_verification = isinstance(verification, dict) and bool(
            verification.get("rule_ids") or verification.get("success_conditions")
        )
        if (
            not semantic_name
            or not purpose
            or not risk_class
            or not isinstance(allowed_actions, list)
            or action_type not in allowed_actions
            or not has_verification
        ):
            raise ValueError("available action has an incomplete semantic control")


def _validated_observation(
    value: dict[str, Any],
    *,
    expected_interface_id: str,
) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or value.get("contract_version") != "current_interface_observation_v1"
    ):
        raise ValueError("current_interface_observation_v1 is required")
    interface_id = _required_text(value.get("interface_id"), "interface_id")
    if interface_id != expected_interface_id:
        raise ValueError("current observation interface identity mismatch")
    return {
        "contract_version": "current_interface_observation_v1",
        "interface_id": interface_id,
        "capture_id": _required_text(value.get("capture_id"), "capture_id"),
        "screenshot_sha256": _required_text(
            value.get("screenshot_sha256"),
            "screenshot_sha256",
        ),
        "trace_path": _required_text(value.get("trace_path"), "trace_path"),
    }


def _normalized_read_state(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {
            "strategy": None,
            "status": "not_started",
            "completion": "not_started",
            "content_id": None,
            "scrolls_used": 0,
            "max_scrolls": 0,
            "items_read": 0,
            "max_items": 0,
        }
    if not isinstance(value, dict):
        raise ValueError("read_progress must be an object")
    strategy = _required_text(value.get("strategy"), "read strategy")
    if strategy not in _READ_STRATEGIES:
        raise ValueError(f"unsupported read strategy: {strategy}")
    batch_stop_reason = _required_text(
        value.get("status") or "reading",
        "read status",
    )
    scrolls_used = _non_negative_int(value.get("scrolls_used"), "scrolls_used")
    max_scrolls = _non_negative_int(value.get("max_scrolls"), "max_scrolls")
    items_read = _non_negative_int(value.get("items_read"), "items_read")
    max_items = _non_negative_int(value.get("max_items"), "max_items")
    budget_remaining = (
        (max_scrolls <= 0 or scrolls_used < max_scrolls)
        and (max_items <= 0 or items_read < max_items)
    )
    status = (
        "capture_batch_complete"
        if batch_stop_reason == "captures_exhausted" and budget_remaining
        else batch_stop_reason
    )

    if status == "wrong_scope_detected":
        completion = "blocked_wrong_scope"
    elif status == "reading_stopped":
        completion = "bounded_stop"
    elif strategy == "finite_detail":
        completion = "complete" if status == "reached_bottom" else "incomplete"
    elif (
        (max_scrolls > 0 and scrolls_used >= max_scrolls)
        or (max_items > 0 and items_read >= max_items)
    ):
        completion = "budget_exhausted"
    else:
        completion = "incomplete"
    return {
        "strategy": strategy,
        "status": status,
        "batch_stop_reason": batch_stop_reason,
        "completion": completion,
        "content_id": str(value.get("content_id") or "").strip() or None,
        "scrolls_used": scrolls_used,
        "max_scrolls": max_scrolls,
        "items_read": items_read,
        "max_items": max_items,
    }


def _transition_choices(
    value: Any,
    *,
    semantic_controls: Any,
    read_state: dict[str, Any],
) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    controls_by_id = {
        str(item.get("control_id") or ""): item
        for item in (
            semantic_controls if isinstance(semantic_controls, list) else []
        )
        if isinstance(item, dict) and str(item.get("control_id") or "")
    }
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        semantic_action = _normalize_action(item.get("action_type"))
        if not semantic_action or _is_forbidden_action(semantic_action):
            continue
        requires_completed_read = str(
            item.get("requires_completed_read") or ""
        ).strip()
        if requires_completed_read and (
            read_state.get("content_id") != requires_completed_read
            or read_state.get("status") != "reached_bottom"
        ):
            continue
        action_id = _required_text(item.get("action_id"), "action_id")
        source_control_id = str(item.get("source_control_id") or "")
        choices.append(
            {
                "choice_id": f"transition:{action_id}",
                "decision_type": "follow_transition",
                "semantic_action": semantic_action,
                "display_name": str(item.get("display_name") or semantic_action),
                "agent_description": str(item.get("agent_description") or ""),
                "operation_goal": str(
                    item.get("operation_goal")
                    or item.get("agent_description")
                    or item.get("display_name")
                    or semantic_action
                ),
                "source_control_id": source_control_id,
                "source_control": deepcopy(controls_by_id[source_control_id]),
                "target_interface_id": str(item.get("target_interface_id") or ""),
                "requires_completed_read": requires_completed_read or None,
                "risk_level": str(item.get("risk_level") or "unknown"),
                "success_conditions": deepcopy(item.get("success_conditions") or []),
            }
        )
    return choices


def _read_choices(
    value: Any,
    *,
    read_state: dict[str, Any],
) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        content_id = _required_text(item.get("content_id"), "content_id")
        if (
            read_state.get("content_id") == content_id
            and read_state.get("completion") in {
                "incomplete",
                "complete",
                "bounded_stop",
            }
        ):
            continue
        read_strategy = str(item.get("read_strategy") or "").strip()
        if not read_strategy:
            read_strategy = (
                "infinite_collection"
                if item.get("content_behavior") == "dynamic_collection"
                else "finite_detail"
            )
        choices.append(
            {
                "choice_id": f"read:{content_id}",
                "decision_type": "read_region",
                "semantic_action": "read",
                "display_name": str(item.get("label") or content_id),
                "agent_description": str(item.get("agent_description") or ""),
                "content_id": content_id,
                "read_policy": str(item.get("read_policy") or "on_demand"),
                "read_strategy": read_strategy,
                "completion_policy": str(
                    item.get("completion_policy")
                    or (
                        "budget_or_no_new_content"
                        if read_strategy == "infinite_collection"
                        else "reached_bottom_required"
                    )
                ),
                "max_scrolls": _non_negative_int(
                    item.get("max_scrolls")
                    if item.get("max_scrolls") is not None
                    else (3 if read_strategy == "infinite_collection" else 6),
                    "max_scrolls",
                ),
                "max_items": _non_negative_int(
                    item.get("max_items"),
                    "max_items",
                ),
            }
        )
    return choices


def _can_scroll(read_state: dict[str, Any]) -> bool:
    strategy = read_state.get("strategy")
    if strategy not in _READ_STRATEGIES:
        return False
    if read_state.get("status") in {
        "reached_bottom",
        "reading_stopped",
        "wrong_scope_detected",
    }:
        return False
    max_scrolls = int(read_state.get("max_scrolls") or 0)
    if max_scrolls <= 0 or int(read_state.get("scrolls_used") or 0) >= max_scrolls:
        return False
    max_items = int(read_state.get("max_items") or 0)
    if max_items > 0 and int(read_state.get("items_read") or 0) >= max_items:
        return False
    return True


def _safe_stop_choice(reason: str) -> dict[str, Any]:
    return {
        "choice_id": f"safe_stop:{reason}",
        "decision_type": "safe_stop",
        "semantic_action": "safe_stop",
        "display_name": "Safe stop",
        "agent_description": "Stop without another GUI action and retain Trace evidence.",
        "stop_reason": reason,
    }


def _stop_reading_choice() -> dict[str, Any]:
    return {
        "choice_id": "read:stop_budgeted_collection",
        "decision_type": "stop_reading",
        "semantic_action": "stop_reading",
        "display_name": "Stop collection reading",
        "agent_description": (
            "Stop when the information goal or configured read budget "
            "has been satisfied."
        ),
    }


def _is_forbidden_action(value: str) -> bool:
    normalized = _normalize_action(value)
    return normalized in _FORBIDDEN_ACTIONS or any(
        token in normalized
        for token in (
            "confirm_purchase",
            "final_apply",
            "final_submit",
            "payment",
            "place_order",
            "purchase",
            "send_application",
            "send_message",
            "submit_application",
        )
    )


def _normalize_action(value: Any) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _non_negative_int(value: Any, field_name: str) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if number < 0:
        raise ValueError(f"{field_name} must not be negative")
    return number
