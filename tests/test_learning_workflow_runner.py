from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import panel as panel_api
from app.main import app
from app.learn.workflow_runner import run_learning_workflow_readonly_tail
from app.learn.workflow_state import (
    LEARNING_WORKFLOW_COMPLETION_EVIDENCE,
    LEARNING_WORKFLOW_STAGES,
    LearningWorkflowTransitionError,
)
from app.learn.workflow_store import LearningWorkflowRunStore


def _completion_evidence(stage: str) -> dict[str, str]:
    return {
        field: f"artifacts/learning-runs/run-demo/{stage}-{field}.json"
        for field in LEARNING_WORKFLOW_COMPLETION_EVIDENCE[stage]
    }


def _store_at_completed_fusion() -> tuple[LearningWorkflowRunStore, dict]:
    store = LearningWorkflowRunStore()
    state: dict | None = None
    for stage in LEARNING_WORKFLOW_STAGES:
        state = store.transition(
            run_id="run-demo",
            expected_revision=0 if state is None else state["revision"],
            stage=stage,
            outcome="running",
        )
        state = store.transition(
            run_id="run-demo",
            expected_revision=state["revision"],
            stage=stage,
            outcome="completed",
            evidence_refs=_completion_evidence(stage),
        )
        if stage == "fusion":
            return store, state
    raise AssertionError("fusion stage was not reached")


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def test_readonly_tail_runner_owns_page_detail_pathgraph_and_completion(
    tmp_path: Path,
) -> None:
    store, fusion_state = _store_at_completed_fusion()
    source_path = _write_json(
        tmp_path / "artifacts" / "learning-runs" / "run-demo" / "trial_result.json",
        {"contract_version": "learning_model_trial_v1"},
    )
    calls: list[tuple[str, str]] = []

    def build_page_detail(**kwargs):
        calls.append(("page_details", str(kwargs["source_path"])))
        return {
            "contract_version": "learn_page_detail_candidate_v1",
            "report_path": str(
                _write_json(
                    Path(kwargs["out_dir"]) / "learn_page_detail_candidate.json",
                    {
                        "contract_version": "learn_page_detail_candidate_v1",
                        "source_path": str(source_path),
                    },
                )
            ),
        }

    def build_scaffold(**kwargs):
        calls.append(("pathgraph_draft", str(kwargs["source_path"])))
        return {
            "contract_version": "learn_mode_demo_scaffold_v1",
            "report_path": str(
                _write_json(
                    Path(kwargs["out_dir"]) / "learn_mode_demo_scaffold.json",
                    {
                        "contract_version": "learn_mode_demo_scaffold_v1",
                        "source_path": str(kwargs["source_path"]),
                    },
                )
            ),
        }

    result = run_learning_workflow_readonly_tail(
        run_id="run-demo",
        expected_revision=fusion_state["revision"],
        source_path=source_path,
        project_root=tmp_path,
        store=store,
        page_detail_builder=build_page_detail,
        scaffold_builder=build_scaffold,
    )

    assert result["success"] is True
    assert result["contract_version"] == "learning_workflow_readonly_tail_v1"
    assert [item[0] for item in calls] == ["page_details", "pathgraph_draft"]
    assert calls[1][1].endswith("learn_page_detail_candidate.json")
    state = result["workflow_state"]
    assert state["workflow_status"] == "completed"
    assert state["terminal"] is True
    assert state["stages"]["page_details"]["status"] == "completed"
    assert state["stages"]["pathgraph_draft"]["status"] == "completed"
    assert state["stages"]["complete"]["status"] == "completed"
    assert result["display_only"] is True
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    assert result["real_clicks"] == 0


def test_readonly_tail_runner_marks_page_detail_failure_terminal(
    tmp_path: Path,
) -> None:
    store, fusion_state = _store_at_completed_fusion()
    source_path = _write_json(
        tmp_path / "artifacts" / "learning-runs" / "run-demo" / "trial_result.json",
        {"contract_version": "learning_model_trial_v1"},
    )
    scaffold_called = False

    def fail_page_detail(**_kwargs):
        raise RuntimeError("page detail builder failed")

    def build_scaffold(**_kwargs):
        nonlocal scaffold_called
        scaffold_called = True
        return {}

    result = run_learning_workflow_readonly_tail(
        run_id="run-demo",
        expected_revision=fusion_state["revision"],
        source_path=source_path,
        project_root=tmp_path,
        store=store,
        page_detail_builder=fail_page_detail,
        scaffold_builder=build_scaffold,
    )

    assert result["success"] is False
    assert result["failed_stage"] == "page_details"
    assert result["failure_category"] == "stage_execution_failed"
    assert "page detail builder failed" in result["error"]
    assert result["workflow_state"]["workflow_status"] == "failed"
    assert result["workflow_state"]["stages"]["page_details"]["status"] == "failed"
    assert scaffold_called is False


def test_readonly_tail_runner_marks_pathgraph_failure_without_completing(
    tmp_path: Path,
) -> None:
    store, fusion_state = _store_at_completed_fusion()
    source_path = _write_json(
        tmp_path / "artifacts" / "learning-runs" / "run-demo" / "trial_result.json",
        {"contract_version": "learning_model_trial_v1"},
    )

    def build_page_detail(**kwargs):
        return {
            "report_path": str(
                _write_json(
                    Path(kwargs["out_dir"]) / "learn_page_detail_candidate.json",
                    {"contract_version": "learn_page_detail_candidate_v1"},
                )
            )
        }

    def fail_scaffold(**_kwargs):
        raise RuntimeError("PathGraph scaffold builder failed")

    result = run_learning_workflow_readonly_tail(
        run_id="run-demo",
        expected_revision=fusion_state["revision"],
        source_path=source_path,
        project_root=tmp_path,
        store=store,
        page_detail_builder=build_page_detail,
        scaffold_builder=fail_scaffold,
    )

    assert result["success"] is False
    assert result["failed_stage"] == "pathgraph_draft"
    assert result["failure_category"] == "stage_execution_failed"
    assert "PathGraph scaffold builder failed" in result["error"]
    state = result["workflow_state"]
    assert state["workflow_status"] == "failed"
    assert state["terminal"] is True
    assert state["stages"]["page_details"]["status"] == "completed"
    assert state["stages"]["pathgraph_draft"]["status"] == "failed"
    assert state["stages"]["complete"]["status"] == "pending"


def test_readonly_tail_runner_rejects_stale_revision_before_building(
    tmp_path: Path,
) -> None:
    store, fusion_state = _store_at_completed_fusion()
    source_path = _write_json(
        tmp_path / "artifacts" / "learning-runs" / "run-demo" / "trial_result.json",
        {"contract_version": "learning_model_trial_v1"},
    )
    builder_called = False

    def build_page_detail(**_kwargs):
        nonlocal builder_called
        builder_called = True
        return {}

    with pytest.raises(LearningWorkflowTransitionError, match="revision conflict"):
        run_learning_workflow_readonly_tail(
            run_id="run-demo",
            expected_revision=fusion_state["revision"] - 1,
            source_path=source_path,
            project_root=tmp_path,
            store=store,
            page_detail_builder=build_page_detail,
            scaffold_builder=lambda **_kwargs: {},
        )

    assert builder_called is False


def test_panel_readonly_tail_endpoint_runs_backend_owned_stages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store, fusion_state = _store_at_completed_fusion()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    source_path = _write_json(
        tmp_path / "artifacts" / "learning-runs" / "run-demo" / "trial_result.json",
        {"contract_version": "learning_model_trial_v1"},
    )

    def build_page_detail(**kwargs):
        return {
            "report_path": str(
                _write_json(
                    Path(kwargs["out_dir"]) / "learn_page_detail_candidate.json",
                    {"contract_version": "learn_page_detail_candidate_v1"},
                )
            )
        }

    def build_scaffold(**kwargs):
        return {
            "report_path": str(
                _write_json(
                    Path(kwargs["out_dir"]) / "learn_mode_demo_scaffold.json",
                    {"contract_version": "learn_mode_demo_scaffold_v1"},
                )
            )
        }

    monkeypatch.setattr(panel_api, "build_learn_page_detail_candidate", build_page_detail)
    monkeypatch.setattr(panel_api, "build_learn_demo_scaffold", build_scaffold)

    def write_runner_trace(**kwargs):
        assert kwargs["operation"] == "run-learning-workflow-readonly-tail"
        return str(
            _write_json(
                tmp_path / "logs" / "traces" / "panel" / "readonly-tail.json",
                kwargs["payload"],
            )
        )

    monkeypatch.setattr(panel_api, "write_trace", write_runner_trace)

    response = TestClient(app).post(
        "/panel/run_learning_workflow_readonly_tail",
        json={
            "run_id": "run-demo",
            "expected_revision": fusion_state["revision"],
            "source_path": str(source_path),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["workflow_state"]["workflow_status"] == "completed"
    assert payload["data"]["real_clicks"] == 0
    assert payload["data"]["trace_path"].endswith("readonly-tail.json")


def test_panel_uses_backend_runner_for_readonly_tail() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    start = panel_js.index("async function completeLearningInterfaceReadonlyFlow")
    end = panel_js.index("async function runLearningDraftTrial", start)
    body = panel_js[start:end]

    assert "/panel/run_learning_workflow_readonly_tail" in body
    assert 'transitionLearningWorkflowState("page_details"' not in body
    assert 'transitionLearningWorkflowState("pathgraph_draft"' not in body
    assert 'transitionLearningWorkflowState("complete"' not in body
