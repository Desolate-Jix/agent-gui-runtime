from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from app.agent.navigation_reading import build_navigation_reading_context
from app.agent.navigation_reading_controller import (
    run_navigation_reading_controller,
)
from app.learn.interface_workflow_review import (
    load_interface_workflow_agent_context,
)


def load_reviewed_workflow_interface_evidence(
    *,
    project_root: str | Path,
    application_identity_key: str,
    workflow_id: str,
    interface_id: str,
) -> dict[str, Any]:
    """加载已审核流程中的单界面 Agent 证据，不提供执行授权。"""

    requested_workflow_id = _required_text(workflow_id, "workflow_id")
    requested_interface_id = _required_text(interface_id, "interface_id")
    context = load_interface_workflow_agent_context(
        project_root=Path(project_root),
        application_identity_key=_required_text(
            application_identity_key,
            "application_identity_key",
        ),
    )
    workflow = next(
        (
            item
            for item in context.get("agent_evidence_workflows") or []
            if isinstance(item, dict)
            and str(item.get("workflow_id") or "") == requested_workflow_id
        ),
        None,
    )
    if workflow is None:
        blocked = next(
            (
                item
                for item in context.get("blocked_interfaces") or []
                if isinstance(item, dict)
                and str(item.get("workflow_id") or "") == requested_workflow_id
            ),
            None,
        )
        if blocked is not None:
            raise ValueError(
                "reviewed workflow is not agent_usable: "
                f"{requested_workflow_id} ({blocked.get('reason') or 'human_review_required'})"
            )
        raise ValueError(f"reviewed workflow not found: {requested_workflow_id}")

    evidence = next(
        (
            item
            for item in workflow.get("interfaces") or []
            if isinstance(item, dict)
            and str((item.get("interface") or {}).get("interface_id") or "")
            == requested_interface_id
        ),
        None,
    )
    if evidence is None:
        blocked = next(
            (
                item
                for item in context.get("blocked_interfaces") or []
                if isinstance(item, dict)
                and str(item.get("workflow_id") or "") == requested_workflow_id
                and str(item.get("interface_id") or "") == requested_interface_id
            ),
            None,
        )
        if blocked is not None:
            raise ValueError(
                "reviewed workflow interface is not agent_usable: "
                f"{requested_workflow_id}/{requested_interface_id} "
                f"({blocked.get('reason') or 'human_review_required'})"
            )
        raise ValueError(
            "reviewed workflow interface not found: "
            f"{requested_workflow_id}/{requested_interface_id}"
        )
    readiness = evidence.get("readiness") if isinstance(evidence.get("readiness"), dict) else {}
    if readiness.get("status") != "agent_usable":
        missing = ", ".join(str(item) for item in readiness.get("missing_fields") or [])
        suffix = f": {missing}" if missing else ""
        raise ValueError(
            "reviewed workflow interface is not agent_usable"
            f"{suffix}"
        )
    if evidence.get("artifact_is_authorization") is not False:
        raise ValueError("reviewed workflow evidence must not authorize execution")
    return deepcopy(evidence)


def build_reviewed_workflow_navigation_context(
    *,
    project_root: str | Path,
    application_identity_key: str,
    workflow_id: str,
    interface_id: str,
    goal: str,
    observation: dict[str, Any],
    read_progress: dict[str, Any] | None = None,
    task_progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把正式多界面学习资产接入通用 Agent 单步决策上下文。"""

    evidence = load_reviewed_workflow_interface_evidence(
        project_root=project_root,
        application_identity_key=application_identity_key,
        workflow_id=workflow_id,
        interface_id=interface_id,
    )
    return build_navigation_reading_context(
        goal=goal,
        interface_evidence=evidence,
        observation=observation,
        read_progress=read_progress,
        task_progress=task_progress,
    )


def build_reviewed_workflow_live_suite(
    *,
    project_root: str | Path,
    application_identity_key: str,
    workflow_id: str,
) -> dict[str, Any]:
    """把正式多界面流程编译为通用实时观察与执行输入。"""

    root = Path(project_root).resolve()
    identity_key = _required_text(
        application_identity_key,
        "application_identity_key",
    )
    requested_workflow_id = _required_text(workflow_id, "workflow_id")
    context = load_interface_workflow_agent_context(
        project_root=root,
        application_identity_key=identity_key,
    )
    workflow = next(
        (
            item
            for item in context.get("agent_evidence_workflows") or []
            if isinstance(item, dict)
            and str(item.get("workflow_id") or "") == requested_workflow_id
        ),
        None,
    )
    raw_workflow = next(
        (
            item
            for item in context.get("workflows") or []
            if isinstance(item, dict)
            and str((item.get("workflow") or {}).get("workflow_id") or "")
            == requested_workflow_id
        ),
        None,
    )
    if workflow is None or raw_workflow is None:
        raise ValueError(f"reviewed workflow not found: {requested_workflow_id}")
    if raw_workflow.get("artifact_is_authorization") is not False:
        raise ValueError("reviewed workflow must not authorize execution")

    interfaces = [
        deepcopy(item)
        for item in workflow.get("interfaces") or []
        if isinstance(item, dict)
    ]
    if len(interfaces) < 2:
        raise ValueError("reviewed workflow must contain at least two interfaces")

    interface_specs: list[dict[str, Any]] = []
    evidence_by_interface: dict[str, dict[str, Any]] = {}
    asset_paths: dict[str, str] = {}
    workflow_path = (
        root
        / "artifacts"
        / "interface-workflow-reviews"
        / requested_workflow_id
        / "reviewed_workflow.json"
    )
    for evidence in interfaces:
        interface = evidence.get("interface")
        if not isinstance(interface, dict):
            raise ValueError("reviewed workflow interface metadata is required")
        interface_id = _required_text(interface.get("interface_id"), "interface_id")
        readiness = evidence.get("readiness")
        if not isinstance(readiness, dict) or readiness.get("status") != "agent_usable":
            raise ValueError(
                f"reviewed workflow interface is not agent_usable: {interface_id}"
            )
        if evidence.get("artifact_is_authorization") is not False:
            raise ValueError("reviewed workflow evidence must not authorize execution")

        identity_markers = list(
            dict.fromkeys(
                str(anchor.get("label") or "").strip()
                for anchor in evidence.get("identity_anchors") or []
                if isinstance(anchor, dict)
                and str(anchor.get("label") or "").strip()
            )
        )
        if not identity_markers:
            raise ValueError(
                f"reviewed workflow interface has no identity anchors: {interface_id}"
            )
        visible_control_markers = list(
            dict.fromkeys(
                str(marker).strip()
                for control in evidence.get("semantic_controls") or []
                if isinstance(control, dict)
                for marker in control.get("visible_text_anchors") or []
                if str(marker).strip()
            )
        )
        visible_identity_markers = list(
            dict.fromkeys([*identity_markers, *visible_control_markers])
        )
        spec: dict[str, Any] = {
            "interface_id": interface_id,
            "surface_type": str(interface.get("surface_type") or "unknown_surface"),
            "identity_markers": identity_markers,
            "identity_marker_sets": [visible_identity_markers],
        }
        dynamic_content = [
            item
            for item in evidence.get("dynamic_content") or []
            if isinstance(item, dict)
            and str(item.get("read_policy") or "") == "on_demand"
        ]
        if len(dynamic_content) > 1:
            raise ValueError(
                "reviewed workflow interface has multiple runtime read targets: "
                f"{interface_id}"
            )
        if dynamic_content:
            target = dynamic_content[0]
            spec["read_target"] = {
                "content_id": _required_text(target.get("content_id"), "content_id"),
                "scroll_scope": str(target.get("scroll_scope") or "page"),
                "target_pane": str(target.get("target_pane") or "page"),
                "wheel_clicks": int(
                    target.get("wheel_clicks") or target.get("max_scrolls") or 3
                ),
                "bottom_markers": [
                    str(marker).strip()
                    for marker in target.get("bottom_markers") or []
                    if str(marker).strip()
                ],
            }
        interface_specs.append(spec)
        evidence_by_interface[interface_id] = evidence
        asset_paths[interface_id] = str(workflow_path)

    transitions = [
        {
            "transition_id": str(action.get("action_id") or ""),
            "source_interface_id": str(action.get("source_interface_id") or ""),
            "target_interface_id": str(action.get("target_interface_id") or ""),
            "source_control_id": str(action.get("source_control_id") or ""),
            "action_type": str(action.get("action_type") or ""),
            "display_name": str(action.get("display_name") or ""),
            "agent_description": str(action.get("agent_description") or ""),
            "operation_goal": str(action.get("operation_goal") or ""),
            "requires_completed_read": action.get("requires_completed_read"),
            "risk_level": str(action.get("risk_level") or "unknown"),
            "review_status": str(action.get("review_status") or "needs_human_review"),
            "success_conditions": list(action.get("success_conditions") or []),
        }
        for evidence in interfaces
        for action in evidence.get("available_actions") or []
        if isinstance(action, dict)
    ]
    application_identity = (
        context.get("application_identity")
        if isinstance(context.get("application_identity"), dict)
        else {}
    )
    return {
        "contract_version": "reviewed_workflow_live_suite_v1",
        "source": "reviewed_multi_interface_workflow",
        "suite_id": requested_workflow_id,
        "goal": _required_text(workflow.get("goal"), "goal"),
        "app_name": _required_text(application_identity.get("name"), "app_name"),
        "initial_interface_id": _required_text(
            workflow.get("entry_interface_id"),
            "entry_interface_id",
        ),
        "interface_specs": interface_specs,
        "transitions": transitions,
        "evidence_by_interface": evidence_by_interface,
        "asset_paths": asset_paths,
        "application_identity": deepcopy(application_identity),
        "manifest_path": str(workflow_path),
        "artifact_is_authorization": False,
    }


def run_reviewed_workflow_navigation_live_smoke(
    *,
    project_root: str | Path,
    application_identity_key: str,
    workflow_id: str,
    out_dir: str | Path,
    runtime_endpoint: str,
    decision_endpoint: str,
    decision_model: str,
    max_steps: int = 18,
    request_timeout_seconds: float = 90.0,
    decision_timeout_seconds: float = 45.0,
) -> dict[str, Any]:
    """从正式多界面学习资产启动低风险实时演练。"""

    from app.agent.navigation_reading_live_smoke import (
        run_navigation_reading_live_suite,
    )

    suite = build_reviewed_workflow_live_suite(
        project_root=project_root,
        application_identity_key=application_identity_key,
        workflow_id=workflow_id,
    )
    return run_navigation_reading_live_suite(
        suite=suite,
        out_dir=out_dir,
        workflow_project_root=project_root,
        runtime_endpoint=runtime_endpoint,
        decision_endpoint=decision_endpoint,
        decision_model=decision_model,
        max_steps=max_steps,
        request_timeout_seconds=request_timeout_seconds,
        decision_timeout_seconds=decision_timeout_seconds,
        persist_session_workflow=True,
    )


def run_reviewed_workflow_navigation_controller(
    *,
    project_root: str | Path,
    application_identity_key: str,
    workflow_id: str,
    goal: str,
    session_id: str,
    observe_current: Callable[[], dict[str, Any]],
    decide: Callable[[dict[str, Any]], dict[str, Any]],
    execute_operation: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    initial_read_progress: dict[str, Any] | None = None,
    max_steps: int = 12,
) -> dict[str, Any]:
    """从正式多界面学习资产启动连续 Agent 控制器。"""

    requested_workflow_id = _required_text(workflow_id, "workflow_id")
    context = load_interface_workflow_agent_context(
        project_root=Path(project_root),
        application_identity_key=_required_text(
            application_identity_key,
            "application_identity_key",
        ),
    )
    workflow = next(
        (
            item
            for item in context.get("agent_evidence_workflows") or []
            if isinstance(item, dict)
            and str(item.get("workflow_id") or "") == requested_workflow_id
        ),
        None,
    )
    raw_workflow = next(
        (
            item
            for item in context.get("workflows") or []
            if isinstance(item, dict)
            and str((item.get("workflow") or {}).get("workflow_id") or "")
            == requested_workflow_id
        ),
        None,
    )
    if workflow is None or raw_workflow is None:
        raise ValueError(f"reviewed workflow not found: {requested_workflow_id}")

    evidence_by_interface: dict[str, dict[str, Any]] = {}
    for evidence in workflow.get("interfaces") or []:
        if not isinstance(evidence, dict):
            continue
        interface = evidence.get("interface")
        interface_id = str(
            (interface if isinstance(interface, dict) else {}).get("interface_id") or ""
        ).strip()
        if not interface_id:
            continue
        readiness = evidence.get("readiness")
        if not isinstance(readiness, dict) or readiness.get("status") != "agent_usable":
            raise ValueError(
                f"reviewed workflow interface is not agent_usable: {interface_id}"
            )
        if evidence.get("artifact_is_authorization") is not False:
            raise ValueError("reviewed workflow evidence must not authorize execution")
        evidence_by_interface[interface_id] = deepcopy(evidence)

    if len(evidence_by_interface) < 2:
        raise ValueError("reviewed workflow must contain at least two agent_usable interfaces")

    controller = run_navigation_reading_controller(
        goal=_required_text(goal, "goal"),
        workflow_id=requested_workflow_id,
        session_id=_required_text(session_id, "session_id"),
        observe_current=observe_current,
        load_interface_evidence=lambda interface_id: deepcopy(
            evidence_by_interface[interface_id]
        ),
        decide=decide,
        execute_operation=execute_operation,
        initial_read_progress=initial_read_progress,
        max_steps=max_steps,
    )
    raw_nodes = [item for item in raw_workflow.get("nodes") or [] if isinstance(item, dict)]
    raw_edges = [item for item in raw_workflow.get("edges") or [] if isinstance(item, dict)]
    return {
        "contract_version": "reviewed_workflow_navigation_controller_report_v1",
        "source_workflow": {
            "source": "reviewed_multi_interface_workflow",
            "workflow_id": requested_workflow_id,
            "entry_interface_id": str(workflow.get("entry_interface_id") or ""),
            "interface_count": len(raw_nodes),
            "transition_count": len(raw_edges),
        },
        "controller": controller,
        "safety": {
            "historical_coordinates_used": False,
            "fresh_grounding_required": True,
            "gate_required": True,
            "artifact_is_authorization": False,
        },
    }


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
