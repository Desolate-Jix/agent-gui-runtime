from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.learn.continuous_workflow_projection import (
    persist_continuous_session_workflow_candidate,
)
from app.learn.interface_workflow_review import load_interface_workflow_agent_context


class _MemoryStore:
    def __init__(self, memories: dict[str, dict[str, Any]]) -> None:
        self._memories = memories

    def registry(self) -> dict[str, Any]:
        return {
            "active_by_interface": {
                interface_id: f"sha256-{interface_id}"
                for interface_id in self._memories
            }
        }

    def load_active(self, interface_id: str) -> dict[str, Any]:
        return self._memories[interface_id]


def _evidence(name: str) -> dict[str, str]:
    return {
        "capture_id": f"artifacts/screenshots/{name}.png",
        "screenshot_sha256": f"sha256-{name}",
        "trace_path": f"logs/traces/{name}.json",
    }


def _memory(interface_id: str, *, action_type: str | None = None) -> dict[str, Any]:
    actions = []
    if action_type:
        actions.append(
            {
                "action_id": f"{interface_id}:{action_type}",
                "action_type": action_type,
                "target_element_id": f"{interface_id}:primary",
                "display_name": action_type.replace("_", " ").title(),
            }
        )
    return {
        "contract_version": "reviewed_interface_memory_v1",
        "interface_id": interface_id,
        "source": {
            "reviewed_candidate_path": f"artifacts/reviews/{interface_id}.json",
            "screenshot_path": f"artifacts/screenshots/{interface_id}.png",
            "screenshot_sha256": f"sha256-{interface_id}",
        },
        "review": {
            "reviewed_by_human": True,
            "review_status": "approved_as_assisted_template",
        },
        "states": [{"state_id": f"{interface_id}:state", "display_name": interface_id}],
        "elements": [
            {
                "element_id": f"{interface_id}:primary",
                "semantic_name": "Primary control",
                "role": "button",
            }
        ],
        "actions": actions,
        "verification_rules": [],
        "blockers": [],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _session() -> dict[str, Any]:
    return {
        "contract_version": "continuous_task_session_v1",
        "session_id": "demo-session",
        "workflow_id": "generic-job-review-flow",
        "status": "safe_stop",
        "events": [
            {
                "sequence": 1,
                "event_type": "interface_observed",
                "details": {
                    "interface_id": "job_results",
                    "surface_type": "results_list",
                    "memory_available": True,
                    "knowledge_source": "reviewed_interface_memory",
                    "evidence": _evidence("results"),
                },
            },
            {
                "sequence": 2,
                "event_type": "action_verified",
                "details": {
                    "action_type": "open_detail",
                    "action_executed": True,
                    "post_action_verified": True,
                    "evidence": _evidence("detail"),
                    "transition_audit": {"gate_result": "allowed"},
                },
            },
            {
                "sequence": 3,
                "event_type": "interface_observed",
                "details": {
                    "interface_id": "job_detail",
                    "surface_type": "detail",
                    "memory_available": True,
                    "knowledge_source": "reviewed_interface_memory",
                    "evidence": _evidence("detail"),
                },
            },
            {
                "sequence": 4,
                "event_type": "action_verified",
                "details": {
                    "action_type": "open_apply_flow",
                    "action_executed": True,
                    "post_action_verified": True,
                    "evidence": _evidence("apply"),
                    "transition_audit": {"gate_result": "allowed"},
                },
            },
            {
                "sequence": 5,
                "event_type": "interface_observed",
                "details": {
                    "interface_id": "application_form",
                    "surface_type": "form_step",
                    "memory_available": True,
                    "knowledge_source": "reviewed_interface_memory",
                    "evidence": _evidence("apply"),
                },
            },
        ],
        "safety": {
            "final_submit_forbidden": True,
            "final_submit_executed": False,
            "gate_required": True,
        },
    }


def test_continuous_session_persists_reloadable_multi_interface_workflow(
    tmp_path: Path,
) -> None:
    store = _MemoryStore(
        {
            "job_results": _memory("job_results", action_type="open_detail"),
            "job_detail": _memory("job_detail", action_type="open_apply_flow"),
            "application_form": _memory("application_form"),
        }
    )

    result = persist_continuous_session_workflow_candidate(
        session=_session(),
        runtime_report={
            "contract_version": "navigation_reading_controller_report_v1",
            "final_status": "safe_stop",
            "stop_reason": "goal_complete",
            "trace_path": "logs/smoke/example/navigation_reading_live_smoke_report.json",
            "steps": [
                {
                    "interface_id": "job_results",
                    "semantic_action": "open_detail",
                    "gate_allowed": True,
                    "dispatch_success": True,
                    "effect_verified": True,
                }
            ],
            "session": {"must_not_be_embedded": True},
        },
        application_identity={
            "name": "Microsoft Edge",
            "process": "msedge.exe",
            "url": "https://www.seek.co.nz/jobs",
        },
        goal="Review a job and open the application form without submitting",
        memory_store=store,
        project_root=tmp_path,
    )

    assert result["status"] == "saved"
    assert result["node_count"] == 3
    assert result["edge_count"] == 2
    assert result["reviewed_memory_node_count"] == 3
    assert result["runtime_observation_only_node_count"] == 0
    assert result["agent_context_reload"] == {
        "status": "passed",
        "workflow_found": True,
        "interface_count": 3,
        "transition_count": 2,
        "agent_usable_interface_count": 0,
        "needs_human_review_interface_count": 3,
    }
    assert result["multi_interface_requirement_met"] is True
    assert result["demo_readiness"]["status"] == "needs_human_review"
    assert result["demo_readiness"]["reason"] == "agent_evidence_needs_human_review"
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False

    workflow = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert [node["node_id"] for node in workflow["nodes"]] == [
        "job_results",
        "job_detail",
        "application_form",
    ]
    assert [edge["action_type"] for edge in workflow["edges"]] == [
        "open_detail",
        "open_apply_flow",
    ]
    assert workflow["safety"]["final_submit_forbidden"] is True
    assert workflow["runtime_report"] == {
        "contract_version": "navigation_reading_controller_report_v1",
        "final_status": "safe_stop",
        "stop_reason": "goal_complete",
        "trace_path": "logs/smoke/example/navigation_reading_live_smoke_report.json",
        "steps": [
            {
                "interface_id": "job_results",
                "semantic_action": "open_detail",
                "gate_allowed": True,
                "dispatch_success": True,
                "effect_verified": True,
            }
        ],
        "artifact_is_authorization": False,
    }
    assert "session" not in workflow["runtime_report"]

    context = load_interface_workflow_agent_context(
        application_identity_key="web:seek.co.nz",
        project_root=tmp_path,
    )
    assert context["workflow_count"] == 1
    assert len(context["agent_evidence_workflows"][0]["interfaces"]) == 3
    assert context["artifact_is_authorization"] is False


def test_runtime_only_interface_is_saved_for_review_but_not_claimed_agent_usable(
    tmp_path: Path,
) -> None:
    session = _session()
    store = _MemoryStore(
        {
            "job_results": _memory("job_results", action_type="open_detail"),
            "application_form": _memory("application_form"),
        }
    )

    result = persist_continuous_session_workflow_candidate(
        session=session,
        application_identity={"url": "https://www.seek.co.nz/jobs"},
        goal="Review a job without submitting",
        memory_store=store,
        project_root=tmp_path,
    )

    assert result["status"] == "saved_needs_human_review"
    assert result["reviewed_memory_node_count"] == 2
    assert result["runtime_observation_only_node_count"] == 1
    assert result["agent_context_reload"]["status"] == "failed"
    assert result["agent_context_reload"]["interface_count"] == 2
    assert result["agent_context_reload"]["transition_count"] == 0
    assert result["agent_context_reload"]["reason"] == (
        "agent_context_counts_do_not_match_saved_workflow"
    )
    assert result["multi_interface_requirement_met"] is False
    assert result["demo_readiness"]["status"] == "needs_human_review"
    assert result["demo_readiness"]["reason"] == "runtime_observation_only_nodes_present"
    context = load_interface_workflow_agent_context(
        application_identity_key="web:seek.co.nz",
        project_root=tmp_path,
    )
    evidence_workflow = context["agent_evidence_workflows"][0]
    assert [
        item["interface"]["interface_id"]
        for item in evidence_workflow["interfaces"]
    ] == ["job_results", "application_form"]
    assert context["workflows"][0]["edges"] == []
    assert [
        item["readiness"]["status"] for item in evidence_workflow["interfaces"]
    ] == ["needs_human_review", "needs_human_review"]
    assert context["agent_usable_interfaces"] == []
    assert context["agent_ready"] is False
    assert any(
        item["interface_id"] == "job_detail"
        for item in context["blocked_interfaces"]
    )
    workflow = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    detail = next(node for node in workflow["nodes"] if node["node_id"] == "job_detail")
    assert detail["agent_evidence_status"] == "runtime_observation_only"
    assert detail["review_status"] == "needs_human_review"
    assert workflow["workflow"]["review_status"] == "needs_human_review"


def test_continuous_projection_rejects_final_action_transition(tmp_path: Path) -> None:
    session = _session()
    session["events"][1]["details"]["action_type"] = "final_submit"

    with pytest.raises(ValueError, match="final action"):
        persist_continuous_session_workflow_candidate(
            session=session,
            application_identity={"url": "https://www.seek.co.nz/jobs"},
            goal="Forbidden transition",
            memory_store=_MemoryStore({}),
            project_root=tmp_path,
        )


def test_projection_uses_the_control_selected_by_the_agent_decision(
    tmp_path: Path,
) -> None:
    session = _session()
    session["events"] = session["events"][:3]
    session["events"][1]["details"]["transition_audit"] = {
        "agent_decision": {
            "semantic_action": "open_detail",
            "source_control_id": "open_updates",
            "expected_target_interface_id": "job_detail",
        },
        "gate_result": {"allowed": True},
    }
    source_memory = _memory("job_results")
    source_memory["elements"] = [
        {"element_id": "open_incident", "semantic_name": "Open incident"},
        {"element_id": "open_updates", "semantic_name": "Open updates"},
    ]
    source_memory["actions"] = [
        {
            "action_id": "open_incident_action",
            "action_type": "open_detail",
            "target_element_id": "open_incident",
        },
        {
            "action_id": "open_updates_action",
            "action_type": "open_detail",
            "target_element_id": "open_updates",
        },
    ]

    result = persist_continuous_session_workflow_candidate(
        session=session,
        application_identity={"url": "https://navigation.test"},
        goal="Open the selected branch",
        memory_store=_MemoryStore(
            {
                "job_results": source_memory,
                "job_detail": _memory("job_detail"),
            }
        ),
        project_root=tmp_path,
    )

    workflow = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert workflow["edges"][0]["source_control_id"] == "open_updates"
