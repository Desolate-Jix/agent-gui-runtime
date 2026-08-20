from __future__ import annotations

from typing import Any

from app.gate.actions import classify_action_taxonomy, infer_low_level_action_type


PATH_GRAPH_ACTION_CONTEXT_CONTRACT = "path_graph_action_context_v1"
EXECUTE_STEP_RESPONSE_CONTRACT = "execute_step_response_v1"


def build_path_graph_action_context(
    runtime_path_graph: dict[str, Any] | None,
    selected_action: dict[str, Any] | None,
    *,
    state_id: str | None = None,
) -> dict[str, Any]:
    graph = runtime_path_graph if isinstance(runtime_path_graph, dict) else {}
    action = selected_action if isinstance(selected_action, dict) else {}
    action_template_id = str(action.get("action_template_id") or action.get("action_id") or "")
    template = _action_template(graph, action_template_id)
    scroll_target = _dict(template.get("scroll_target"))
    return {
        "contract_version": PATH_GRAPH_ACTION_CONTEXT_CONTRACT,
        "graph_id": graph.get("graph_id"),
        "state_id": state_id,
        "action_template_id": action_template_id,
        "selected_action_id": action.get("action_id") or action.get("action_template_id"),
        "target_entity_id": action.get("target_entity_id"),
        "skill_ref": template.get("learned_skill_ref") or action.get("learned_skill_ref"),
        "target_container_id": scroll_target.get("target_container_id") or action.get("scroll_container_id"),
        "verification_rule_refs": action.get("verification_refs") or template.get("verification_rule_refs") or [],
        "safety_policy_refs": ["safety:no_final_submit", "safety:artifact_guidance_only"],
        "artifact_is_authorization": False,
        "requires_gate": True,
    }


def build_execute_step_plan(
    runtime_path_graph: dict[str, Any] | None,
    selected_action: dict[str, Any] | None,
    *,
    state_id: str | None = None,
    safety: dict[str, Any] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    graph = runtime_path_graph if isinstance(runtime_path_graph, dict) else {}
    action = selected_action if isinstance(selected_action, dict) else {}
    action_template_id = str(action.get("action_template_id") or action.get("action_id") or "")
    template = _action_template(graph, action_template_id)
    context = build_path_graph_action_context(graph, action, state_id=state_id)
    transition = _transition_for_action(graph, action_template_id, state_id=state_id)
    low_level_type = infer_low_level_action_type(action_template_id, template)
    taxonomy = classify_action_taxonomy(action_template_id, template, label=action.get("label"))
    if low_level_type == "scroll":
        low_level_request = _scroll_request(template, action_template_id, context, dry_run=dry_run)
    elif low_level_type == "click":
        low_level_request = _click_request(template, action, context, safety=safety, dry_run=dry_run)
    elif low_level_type == "input":
        low_level_request = _input_request(template, action, action_template_id, context, safety=safety, dry_run=dry_run)
    else:
        low_level_type = "unsupported"
        low_level_request = None
    reject_reasons = []
    if low_level_request is None:
        reject_reasons.append("missing_input_text" if low_level_type == "input" else f"unsupported_low_level_action_type:{low_level_type}")
    return {
        "contract_version": EXECUTE_STEP_RESPONSE_CONTRACT,
        "status": "planned" if low_level_request else "rejected",
        "action_template_id": action_template_id,
        "low_level_action_type": low_level_type,
        "action_taxonomy": taxonomy,
        "reject_reasons": reject_reasons,
        "path_graph_assisted": bool(graph),
        "artifact_is_authorization": False,
        "path_graph_action_context": context,
        "path_graph_runtime_state_v1": _path_graph_runtime_state(
            graph,
            transition,
            context,
            action_template_id=action_template_id,
            state_id=state_id,
            low_level_action_type=low_level_type,
            verification_status="not_run_plan_only",
        ),
        "low_level_request": low_level_request,
        "verification": {
            "verified": None,
            "rule_ids": context.get("verification_rule_refs") or [],
            "status": "not_run_plan_only",
        },
        "next": {"return_to_agent": True, "suggested_next_call": "available_actions"},
    }


def _scroll_request(
    template: dict[str, Any],
    action_template_id: str,
    context: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    scroll_target = _dict(template.get("scroll_target"))
    container_id = str(scroll_target.get("target_container_id") or context.get("target_container_id") or "")
    pane = str(scroll_target.get("target_pane") or "").strip() or None
    page_scroll = pane == "page" or container_id.endswith(":page")
    return {
        "contract_version": "scroll_request_v2",
        "goal_id": f"path_graph:{action_template_id}",
        "task_chain_id": "path_graph_execute_step",
        "scroll_scope": "page" if page_scroll else ("container" if container_id else "window"),
        "target_pane": pane,
        "target_container_id": None if page_scroll else (container_id or None),
        "direction": "down",
        "wheel_clicks": 4,
        "reason": f"path_graph_action:{action_template_id}",
        "expected_effect": _dict(template.get("verification_policy")),
        "dry_run": dry_run,
        "enable_verification": not dry_run,
        "metadata": {"path_graph_action_context": context},
    }


def _click_request(
    template: dict[str, Any],
    action: dict[str, Any],
    context: dict[str, Any],
    *,
    safety: dict[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    safety_payload = safety if isinstance(safety, dict) else {}
    goal = str(template.get("goal_template") or "Click the selected path graph target")
    taxonomy = classify_action_taxonomy(context.get("action_template_id") or "", template, label=action.get("label"))
    return {
        "goal": goal,
        "approved_plan_id": action.get("approved_plan_id") or None,
        "task": "click_target",
        "agent_mode": "execute",
        "top_k": 5,
        "capture_live": True,
        "dry_run": dry_run,
        "metadata": {
            "path_graph_action_context": context,
            "selected_available_action": action,
            "candidate_constraints": _dict(template.get("candidate_constraints")),
            "verification_policy": _dict(template.get("verification_policy")),
            "forbid_final_submit": safety_payload.get("forbid_final_submit", True),
            "action_taxonomy": taxonomy,
            "artifact_is_authorization": False,
            "seeded_candidate": _dict(action.get("seeded_candidate")) or _dict(template.get("seeded_candidate")),
        },
    }


def _input_request(
    template: dict[str, Any],
    action: dict[str, Any],
    action_template_id: str,
    context: dict[str, Any],
    *,
    safety: dict[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any] | None:
    input_policy = _dict(template.get("input_policy"))
    safety_payload = _dict(safety)
    target = _dict(action.get("input_target")) or _dict(template.get("input_target"))
    point = _dict(action.get("target_point")) or _dict(target.get("click_point"))
    text = str(
        action.get("text")
        or action.get("input_text")
        or action.get("value")
        or template.get("default_text")
        or ""
    )
    if not text:
        return None
    submit_requested = bool(action.get("submit", False))
    submit_allowed = bool(input_policy.get("submit_allowed", False))
    return {
        "text": text,
        "x": _optional_int(point.get("x")),
        "y": _optional_int(point.get("y")),
        "click_before_typing": bool(point.get("x") is not None and point.get("y") is not None),
        "clear_existing": bool(action.get("clear_existing", input_policy.get("clear_existing", False))),
        "submit": bool(submit_requested and submit_allowed),
        "restore_clipboard": True,
        "dry_run": dry_run,
        "metadata": {
            "path_graph_action_context": context,
            "action_template_id": action_template_id,
            "input_policy": input_policy,
            "input_category": input_policy.get("input_category"),
            "safety": safety_payload,
        },
    }


def _action_template(graph: dict[str, Any], action_template_id: str) -> dict[str, Any]:
    for item in graph.get("action_templates") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("action_template_id") or item.get("action_id") or "") == action_template_id:
            return item
    return {}


def _transition_for_action(graph: dict[str, Any], action_template_id: str, *, state_id: str | None = None) -> dict[str, Any]:
    fallback: dict[str, Any] = {}
    for item in graph.get("transitions") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("action_template_id") or item.get("action_id") or "") != action_template_id:
            continue
        if not fallback:
            fallback = item
        if not state_id or str(item.get("from_state_id") or "") == state_id:
            return item
    return fallback


def _path_graph_runtime_state(
    graph: dict[str, Any],
    transition: dict[str, Any],
    context: dict[str, Any],
    *,
    action_template_id: str,
    state_id: str | None,
    low_level_action_type: str,
    verification_status: str,
) -> dict[str, Any]:
    before_state_id = transition.get("from_state_id") or state_id
    after_state_id = transition.get("to_state_id") or before_state_id
    return {
        "contract_version": "path_graph_runtime_state_v1",
        "graph_id": graph.get("graph_id"),
        "before_state_id": before_state_id,
        "after_state_id": after_state_id,
        "action_template_id": action_template_id,
        "transition_id": transition.get("transition_id"),
        "skill_ref": context.get("skill_ref"),
        "low_level_action_type": low_level_action_type,
        "verification_status": verification_status,
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
