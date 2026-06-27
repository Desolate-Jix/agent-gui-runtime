from __future__ import annotations

from typing import Any

from app.execute.action_kinds import classify_action_taxonomy, infer_action_kind, infer_low_level_action_type


AVAILABLE_ACTIONS_CONTRACT = "available_actions_v1"


def build_available_actions(
    runtime_path_graph: dict[str, Any] | None,
    *,
    current_state_id: str | None = None,
    include_guarded_apply: bool = False,
    path_graph_resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the action menu that Execute Mode may ask an agent to choose from."""

    graph = runtime_path_graph if isinstance(runtime_path_graph, dict) else {}
    resolution = path_graph_resolution if isinstance(path_graph_resolution, dict) else {}
    resolved_state_id = current_state_id or resolution.get("state_id")
    resolution_matched = resolution.get("matched", True) is not False and resolution.get("usage_allowed", True) is not False
    transitions = [item for item in graph.get("transitions") or [] if isinstance(item, dict)]
    templates = {
        str(item.get("action_template_id") or item.get("action_id")): item
        for item in graph.get("action_templates") or []
        if isinstance(item, dict)
    }
    actions: list[dict[str, Any]] = []
    for transition in transitions if resolution_matched else []:
        if resolved_state_id and transition.get("from_state_id") != resolved_state_id:
            continue
        action_id = str(transition.get("action_template_id") or "").strip()
        if not action_id:
            continue
        template = templates.get(action_id) or {}
        if _is_guarded_apply(action_id, template, transition) and not include_guarded_apply:
            continue
        actions.append(_available_action(graph, transition, template, action_id))
    return {
        "contract_version": AVAILABLE_ACTIONS_CONTRACT,
        "graph_id": graph.get("graph_id"),
        "app_id": graph.get("app_id"),
        "page_type": graph.get("page_type"),
        "current_state_id": resolved_state_id,
        "path_graph_resolution": resolution or None,
        "artifact_assisted": bool(graph),
        "artifact_is_authorization": False,
        "actions": actions,
    }


def _available_action(
    graph: dict[str, Any],
    transition: dict[str, Any],
    template: dict[str, Any],
    action_id: str,
) -> dict[str, Any]:
    scroll_target = template.get("scroll_target") if isinstance(template.get("scroll_target"), dict) else {}
    low_level_action_type = infer_low_level_action_type(action_id, template)
    action_kind = infer_action_kind(action_id, template)
    taxonomy = classify_action_taxonomy(action_id, template, label=template.get("label"))
    input_policy = template.get("input_policy") if isinstance(template.get("input_policy"), dict) else {}
    return {
        "action_template_id": action_id,
        "transition_id": transition.get("transition_id"),
        "action_kind": action_kind,
        "action_taxonomy": taxonomy,
        "low_level_action_type": low_level_action_type,
        "label": _label_for_action(action_id),
        "from_state_id": transition.get("from_state_id"),
        "to_state_id": transition.get("to_state_id"),
        "target_entity": template.get("target_entity"),
        "scroll_container_id": scroll_target.get("target_container_id"),
        "input_target": template.get("input_target") if isinstance(template.get("input_target"), dict) else None,
        "input_policy": input_policy
        if input_policy
        else (
            {"requires_agent_text": True, "submit_allowed": False, "text_is_not_stored_by_menu": True}
            if low_level_action_type == "input"
            else None
        ),
        "learned_skill_ref": template.get("learned_skill_ref"),
        "skill_ref": template.get("skill_ref") or template.get("learned_skill_ref"),
        "verification_refs": transition.get("verification_refs") or [],
        "requires_current_validation": template.get("requires_current_validation", True),
        "artifact_is_authorization": False,
        "coordinate_policy_ref": graph.get("coordinate_policy", {}).get("coordinate_space"),
        "safety": {
            "final_submit_allowed": False,
            "final_submit": taxonomy.get("final_submit") is True,
            "open_apply_flow": taxonomy.get("open_apply_flow") is True,
            "real_action_requires_gate": True,
            "guidance_only": True,
        },
    }


def _is_guarded_apply(action_id: str, template: dict[str, Any], transition: dict[str, Any]) -> bool:
    policy = template.get("availability_policy") if isinstance(template.get("availability_policy"), dict) else {}
    return (
        action_id == "apply_entry"
        or policy.get("default_available") is False
        or transition.get("default_available") is False
    )


def _label_for_action(action_id: str) -> str:
    return {
        "open_job_card": "Open job card",
        "read_detail": "Read detail pane",
        "load_more_results": "Load more results",
        "apply_entry": "Open apply entry",
    }.get(action_id, action_id.replace("_", " ").title())
