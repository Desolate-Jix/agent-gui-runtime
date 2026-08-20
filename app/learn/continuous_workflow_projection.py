from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Protocol

from app.learn.application_interface_graph import (
    save_workflow_review_as_application_assets,
)
from app.learn.application_identity import normalize_application_identity
from app.learn.interface_workflow_review import (
    INTERFACE_WORKFLOW_REVIEW_CONTRACT,
    load_interface_workflow_agent_context,
    save_interface_workflow_review_candidate,
)


_SESSION_CONTRACT = "continuous_task_session_v1"
_FINAL_ACTIONS = {"final_submit", "submit", "send", "complete", "confirm", "payment"}
_RUNTIME_REPORT_FIELDS = {
    "contract_version",
    "final_status",
    "stop_reason",
    "steps",
    "decision_source_breakdown",
    "actual_model_call_count",
    "trace_path",
    "source_report_path",
    "safety",
}


class ReviewedMemoryStore(Protocol):
    def registry(self) -> dict[str, Any]: ...

    def load_active(self, interface_id: str) -> dict[str, Any]: ...


def persist_continuous_session_workflow_candidate(
    *,
    session: dict[str, Any],
    runtime_report: dict[str, Any] | None = None,
    application_identity: dict[str, Any],
    goal: str,
    memory_store: ReviewedMemoryStore,
    project_root: str | Path,
) -> dict[str, Any]:
    """把连续观察记录冻结成可重载、不可授权执行的多界面流程。"""

    review = build_continuous_session_workflow_review(
        session=session,
        application_identity=application_identity,
        goal=goal,
        memory_store=memory_store,
        runtime_report=runtime_report,
    )
    nodes = review["nodes"]
    if len(nodes) < 2:
        return {
            "contract_version": "continuous_workflow_projection_result_v1",
            "status": "not_covered",
            "reason": "multi_interface_observation_required",
            "node_count": len(nodes),
            "edge_count": len(review["edges"]),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }

    save_result = save_interface_workflow_review_candidate(
        review,
        project_root=Path(project_root),
    )
    projection_result: dict[str, Any] | None = None
    if save_result.get("application_identity_key"):
        projection_result = save_workflow_review_as_application_assets(
            review,
            project_root=project_root,
        )

    reviewed_count = sum(
        node.get("agent_evidence_status") == "reviewed_interface_memory"
        for node in nodes
    )
    runtime_only_count = len(nodes) - reviewed_count
    unresolved_edges = sum(
        not str(edge.get("target_control_id") or "").strip()
        for edge in review["edges"]
    )
    agent_context_reload = _reload_agent_workflow_context(
        project_root=Path(project_root),
        application_identity_key=str(
            save_result.get("application_identity_key") or ""
        ),
        workflow_id=str(save_result.get("workflow_id") or ""),
        expected_interface_count=len(nodes),
        expected_transition_count=len(review["edges"]),
    )
    multi_interface_requirement_met = bool(
        len(nodes) >= 2
        and review["edges"]
        and agent_context_reload["status"] == "passed"
    )
    demo_readiness = _demo_readiness(
        agent_context_reload=agent_context_reload,
        runtime_only_count=runtime_only_count,
        unresolved_edges=unresolved_edges,
    )
    return {
        "contract_version": "continuous_workflow_projection_result_v1",
        "status": "saved" if runtime_only_count == 0 else "saved_needs_human_review",
        **save_result,
        "reviewed_memory_node_count": reviewed_count,
        "runtime_observation_only_node_count": runtime_only_count,
        "unresolved_transition_count": unresolved_edges,
        "application_asset_projection": projection_result,
        "agent_context_reload": agent_context_reload,
        "multi_interface_requirement_met": multi_interface_requirement_met,
        "demo_readiness": demo_readiness,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _reload_agent_workflow_context(
    *,
    project_root: Path,
    application_identity_key: str,
    workflow_id: str,
    expected_interface_count: int,
    expected_transition_count: int,
) -> dict[str, Any]:
    if not application_identity_key or not workflow_id:
        return {
            "status": "failed",
            "workflow_found": False,
            "interface_count": 0,
            "transition_count": 0,
            "agent_usable_interface_count": 0,
            "needs_human_review_interface_count": 0,
            "reason": "saved_workflow_identity_missing",
        }

    context = load_interface_workflow_agent_context(
        project_root=project_root,
        application_identity_key=application_identity_key,
    )
    evidence = next(
        (
            item
            for item in context.get("agent_evidence_workflows") or []
            if isinstance(item, dict)
            and str(item.get("workflow_id") or "") == workflow_id
        ),
        None,
    )
    if evidence is None:
        return {
            "status": "failed",
            "workflow_found": False,
            "interface_count": 0,
            "transition_count": 0,
            "agent_usable_interface_count": 0,
            "needs_human_review_interface_count": 0,
            "reason": "saved_workflow_not_visible_to_agent",
        }

    interfaces = [
        item
        for item in evidence.get("interfaces") or []
        if isinstance(item, dict)
    ]
    transition_count = sum(
        bool(str(action.get("target_interface_id") or "").strip())
        for interface in interfaces
        for action in [
            *(interface.get("available_actions") or []),
            *(interface.get("actions_needing_review") or []),
        ]
        if isinstance(action, dict)
    )
    agent_usable_count = sum(
        (interface.get("readiness") or {}).get("status") == "agent_usable"
        for interface in interfaces
        if isinstance(interface.get("readiness"), dict)
    )
    counts_match = (
        len(interfaces) == expected_interface_count
        and transition_count == expected_transition_count
    )
    result = {
        "status": "passed" if counts_match else "failed",
        "workflow_found": True,
        "interface_count": len(interfaces),
        "transition_count": transition_count,
        "agent_usable_interface_count": agent_usable_count,
        "needs_human_review_interface_count": len(interfaces) - agent_usable_count,
    }
    if not counts_match:
        result["reason"] = "agent_context_counts_do_not_match_saved_workflow"
    return result


def _demo_readiness(
    *,
    agent_context_reload: dict[str, Any],
    runtime_only_count: int,
    unresolved_edges: int,
) -> dict[str, Any]:
    if runtime_only_count:
        reason = "runtime_observation_only_nodes_present"
    elif unresolved_edges:
        reason = "transition_source_controls_unresolved"
    elif agent_context_reload.get("status") != "passed":
        reason = "agent_context_reload_failed"
    elif agent_context_reload.get("needs_human_review_interface_count"):
        reason = "agent_evidence_needs_human_review"
    else:
        return {
            "status": "ready_for_agent_dry_run",
            "reason": "reviewed_multi_interface_workflow_reloaded",
        }
    return {"status": "needs_human_review", "reason": reason}


def build_continuous_session_workflow_review(
    *,
    session: dict[str, Any],
    application_identity: dict[str, Any],
    goal: str,
    memory_store: ReviewedMemoryStore,
    runtime_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(session, dict) or session.get("contract_version") != _SESSION_CONTRACT:
        raise ValueError("continuous workflow projection requires continuous_task_session_v1")

    normalized_application_identity = normalize_application_identity(application_identity)
    memories = _active_memories(memory_store)
    nodes: list[dict[str, Any]] = []
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    current_interface_id = ""
    pending_action: dict[str, Any] | None = None

    for event in _ordered_events(session.get("events")):
        event_type = str(event.get("event_type") or "").strip()
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        if event_type == "action_verified":
            action_type = str(details.get("action_type") or "unknown_action").strip().casefold()
            if action_type in _FINAL_ACTIONS:
                raise ValueError(f"final action cannot be learned as a transition: {action_type}")
            pending_action = {
                "source_interface_id": current_interface_id,
                "action_type": action_type,
                "details": deepcopy(details),
            }
            continue
        if event_type != "interface_observed":
            continue

        interface_id = str(details.get("interface_id") or "").strip()
        if not interface_id:
            continue
        memory = memories.get(interface_id)
        node = nodes_by_id.get(interface_id)
        if node is None:
            node = _workflow_node(
                interface_id=interface_id,
                details=details,
                memory=memory,
            )
            nodes_by_id[interface_id] = node
            nodes.append(node)
        else:
            node["observation_count"] = int(node.get("observation_count") or 0) + 1
            _merge_observation_evidence(node, details)

        if pending_action and pending_action["source_interface_id"]:
            source_id = str(pending_action["source_interface_id"])
            if source_id != interface_id and source_id in nodes_by_id:
                edges.append(
                    _workflow_edge(
                        index=len(edges),
                        source_node=nodes_by_id[source_id],
                        target_node_id=interface_id,
                        action=pending_action,
                    )
                )
            pending_action = None
        current_interface_id = interface_id

    session_workflow_id = str(session.get("workflow_id") or session.get("session_id") or "workflow")
    workflow_id = f"workflow_{_stable_hash({'session_workflow_id': session_workflow_id, 'application': normalized_application_identity})[:12]}"
    runtime_only_count = sum(
        node.get("agent_evidence_status") != "reviewed_interface_memory"
        for node in nodes
    )
    review = {
        "contract_version": INTERFACE_WORKFLOW_REVIEW_CONTRACT,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "workflow": {
            "workflow_id": workflow_id,
            "goal": str(goal or "").strip(),
            "application_identity": normalized_application_identity,
            "entry_node_id": nodes[0]["node_id"] if nodes else "",
            "node_ids": [node["node_id"] for node in nodes],
            "edge_ids": [edge["edge_id"] for edge in edges],
            "review_status": (
                "needs_human_review" if runtime_only_count else "reviewed_memory_projection"
            ),
            "published_memory_version": None,
            "source_session_id": str(session.get("session_id") or ""),
        },
        "nodes": nodes,
        "edges": edges,
        "invalid_sources": [],
        "safety": {
            "review_draft_only": True,
            "runtime_requires_fresh_capture": True,
            "runtime_requires_fresh_grounding": True,
            "runtime_requires_gate": True,
            "final_submit_forbidden": True,
            "send_delete_confirm_payment_forbidden": True,
        },
    }
    runtime_projection = _project_runtime_report(runtime_report)
    if runtime_projection is not None:
        review["runtime_report"] = runtime_projection
    return review


def _project_runtime_report(
    runtime_report: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """保留面板审计需要的运行证据，排除重复且体积较大的会话事件。"""

    if not isinstance(runtime_report, dict):
        return None
    projected = {
        key: deepcopy(value)
        for key, value in runtime_report.items()
        if key in _RUNTIME_REPORT_FIELDS
    }
    projected["steps"] = [
        deepcopy(step)
        for step in runtime_report.get("steps") or []
        if isinstance(step, dict)
    ]
    projected["artifact_is_authorization"] = False
    return projected


def _active_memories(memory_store: ReviewedMemoryStore) -> dict[str, dict[str, Any]]:
    registry = memory_store.registry()
    active = (
        registry.get("active_by_interface")
        if isinstance(registry.get("active_by_interface"), dict)
        else {}
    )
    memories: dict[str, dict[str, Any]] = {}
    for interface_id in active:
        try:
            memory = memory_store.load_active(str(interface_id))
        except (KeyError, ValueError):
            continue
        if isinstance(memory, dict):
            memories[str(interface_id)] = memory
    return memories


def _workflow_node(
    *,
    interface_id: str,
    details: dict[str, Any],
    memory: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence = _observation_evidence(details)
    if memory is None:
        return {
            "node_id": interface_id,
            "display_name": interface_id.replace("_", " ").strip().title(),
            "surface_type": str(details.get("surface_type") or "unknown_surface"),
            "state_signature": interface_id,
            "source_paths": _source_paths(details, None),
            "observation_count": 1,
            "evidence": evidence,
            "evidence_status": "observation_only",
            "states": [],
            "regions": [],
            "controls": [],
            "action_candidates": [],
            "blockers": [],
            "verification_rules": [],
            "review_status": "needs_human_review",
            "reviewed_by_human": False,
            "agent_evidence_status": "runtime_observation_only",
            "manual_revision": {},
            "display_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }

    controls = []
    for item in memory.get("elements") or []:
        if not isinstance(item, dict):
            continue
        control = deepcopy(item)
        control_id = str(control.get("control_id") or control.get("element_id") or "").strip()
        if control_id:
            control["control_id"] = control_id
        controls.append(control)
    return {
        "node_id": interface_id,
        "display_name": _memory_display_name(memory, interface_id),
        "surface_type": str(details.get("surface_type") or "unknown_surface"),
        "state_signature": interface_id,
        "source_paths": _source_paths(details, memory),
        "observation_count": 1,
        "evidence": evidence,
        "evidence_status": "ready",
        "agent_description": str(memory.get("agent_description") or "").strip(),
        "content_descriptors": deepcopy(memory.get("content_descriptors") or []),
        "states": deepcopy(memory.get("states") or []),
        "regions": [],
        "controls": controls,
        "action_candidates": deepcopy(memory.get("actions") or []),
        "blockers": deepcopy(memory.get("blockers") or []),
        "verification_rules": deepcopy(memory.get("verification_rules") or []),
        "review_status": str(
            (memory.get("review") or {}).get("review_status")
            if isinstance(memory.get("review"), dict)
            else "approved_as_assisted_template"
        ),
        "reviewed_by_human": bool(
            (memory.get("review") or {}).get("reviewed_by_human")
            if isinstance(memory.get("review"), dict)
            else False
        ),
        "agent_evidence_status": "reviewed_interface_memory",
        "manual_revision": deepcopy(memory.get("manual_revision") or {}),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _workflow_edge(
    *,
    index: int,
    source_node: dict[str, Any],
    target_node_id: str,
    action: dict[str, Any],
) -> dict[str, Any]:
    action_type = str(action.get("action_type") or "unknown_action")
    details = action.get("details") if isinstance(action.get("details"), dict) else {}
    audit = details.get("transition_audit") if isinstance(details.get("transition_audit"), dict) else {}
    target_control_id = _source_control_for_action(
        source_node,
        action_type,
        transition_audit=audit,
    )
    source_node_id = str(source_node["node_id"])
    edge_id = f"edge_{_stable_hash([source_node_id, target_node_id, action_type, index])[:12]}"
    return {
        "edge_id": edge_id,
        "operation_id": edge_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "display_name": action_type.replace("_", " ").title(),
        "agent_description": f"Use {action_type} to move from {source_node_id} to {target_node_id}.",
        "action_type": action_type,
        "target_region_id": "",
        "target_control_id": target_control_id,
        "source_control_id": target_control_id,
        "risk_level": "low",
        "requires_user_confirmation": False,
        "preconditions": ["current interface matches source node"],
        "success_conditions": [f"current interface matches {target_node_id}"],
        "failure_conditions": ["destination interface verification failed"],
        "gate_policy": "fresh_grounding_and_gate_required",
        "verification_evidence": deepcopy(details.get("evidence") or {}),
        "transition_audit": deepcopy(audit),
        "review_status": (
            "observed_and_gate_verified" if target_control_id else "needs_human_review"
        ),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _source_control_for_action(
    node: dict[str, Any],
    action_type: str,
    *,
    transition_audit: dict[str, Any],
) -> str:
    decision = (
        transition_audit.get("agent_decision")
        if isinstance(transition_audit.get("agent_decision"), dict)
        else {}
    )
    decision_action = str(
        decision.get("semantic_action") or decision.get("action_type") or ""
    ).strip().casefold()
    selected_control_id = str(decision.get("source_control_id") or "").strip()
    known_control_ids = {
        str(item.get("control_id") or item.get("element_id") or "").strip()
        for item in node.get("controls") or []
        if isinstance(item, dict)
    }
    if (
        selected_control_id
        and decision_action == action_type.casefold()
        and selected_control_id in known_control_ids
    ):
        return selected_control_id

    for action in node.get("action_candidates") or []:
        if not isinstance(action, dict):
            continue
        candidate_type = str(
            action.get("action_type") or action.get("semantic_action") or ""
        ).strip().casefold()
        if candidate_type != action_type.casefold():
            continue
        return str(
            action.get("target_control_id")
            or action.get("target_element_id")
            or action.get("target_region_id")
            or ""
        ).strip()
    return ""


def _observation_evidence(details: dict[str, Any]) -> dict[str, Any]:
    source = details.get("evidence") if isinstance(details.get("evidence"), dict) else {}
    return {
        "source_screenshot_path": str(source.get("screenshot_path") or ""),
        "source_screenshot_sha256": str(source.get("screenshot_sha256") or ""),
        "trace_path": str(source.get("trace_path") or ""),
    }


def _merge_observation_evidence(node: dict[str, Any], details: dict[str, Any]) -> None:
    evidence = _observation_evidence(details)
    if evidence.get("source_screenshot_path"):
        node["evidence"] = evidence


def _source_paths(
    details: dict[str, Any],
    memory: dict[str, Any] | None,
) -> list[str]:
    values: list[str] = []
    if memory is not None and isinstance(memory.get("source"), dict):
        values.append(str(memory["source"].get("reviewed_candidate_path") or ""))
    evidence = details.get("evidence") if isinstance(details.get("evidence"), dict) else {}
    values.append(str(evidence.get("trace_path") or ""))
    return list(dict.fromkeys(value for value in values if value))


def _memory_display_name(memory: dict[str, Any], interface_id: str) -> str:
    states = memory.get("states") if isinstance(memory.get("states"), list) else []
    first = states[0] if states and isinstance(states[0], dict) else {}
    return str(
        first.get("display_name")
        or first.get("name")
        or interface_id.replace("_", " ").title()
    ).strip()


def _ordered_events(value: Any) -> list[dict[str, Any]]:
    events = [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []
    return sorted(events, key=lambda item: int(item.get("sequence") or 0))


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
