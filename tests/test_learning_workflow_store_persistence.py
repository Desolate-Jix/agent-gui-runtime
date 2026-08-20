from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from app.api import panel as panel_api
from app.learn.workflow_state import LearningWorkflowTransitionError
from app.learn.workflow_service import project_learning_workflow_runtime_attachment
from app.learn.workflow_store import (
    LearningWorkflowRunStore,
    resolve_learning_workflow_store_path,
)
from app.learn.workflow_worker import LearningStageWorkerRegistry
from app.main import app


def test_workflow_store_recovers_committed_state_after_restart(tmp_path) -> None:
    state_path = tmp_path / "learning-workflow-runs.json"
    first_store = LearningWorkflowRunStore(
        max_runs=4,
        state_path=state_path,
    )
    first_store.transition(
        run_id="restart-run",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
        reason="开始学习界面",
    )
    first_store.close()

    restarted_store = LearningWorkflowRunStore(
        max_runs=4,
        state_path=state_path,
    )
    recovered = restarted_store.get("restart-run")

    assert recovered["revision"] == 1
    assert recovered["current_stage"] == "bind_capture"
    assert recovered["current_reason"] == "开始学习界面"
    continued = restarted_store.transition(
        run_id="restart-run",
        expected_revision=recovered["revision"],
        stage="bind_capture",
        outcome="safe_stopped",
        reason="恢复后停止",
    )
    assert continued["revision"] == 2
    assert continued["current_reason"] == "恢复后停止"
    restarted_store.close()


def test_persistent_workflow_store_rejects_a_second_writer(tmp_path) -> None:
    state_path = tmp_path / "learning-workflow-runs.json"
    first_store = LearningWorkflowRunStore(state_path=state_path)

    with pytest.raises(
        LearningWorkflowTransitionError,
        match="already owned",
    ):
        LearningWorkflowRunStore(state_path=state_path)

    first_store.close()


def test_workflow_store_uses_dedicated_runtime_state_path_by_default(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH", raising=False)

    state_path = resolve_learning_workflow_store_path(project_root=tmp_path)

    assert state_path == (
        tmp_path / "runtime_state" / "learning-workflow-runs.json"
    ).resolve()


def test_workflow_store_can_be_explicitly_in_memory(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH", ":memory:")

    assert resolve_learning_workflow_store_path() is None


def test_failed_persistence_commit_does_not_publish_new_revision(
    tmp_path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "learning-workflow-runs.json"
    store = LearningWorkflowRunStore(state_path=state_path)
    store.transition(
        run_id="atomic-run",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )
    committed_bytes = state_path.read_bytes()

    def fail_replace(source, target) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("app.learn.workflow_store.os.replace", fail_replace)
    with pytest.raises(
        LearningWorkflowTransitionError,
        match="persistence commit failed",
    ):
        store.transition(
            run_id="atomic-run",
            expected_revision=1,
            stage="bind_capture",
            outcome="completed",
            evidence_refs={"image_path": "artifacts/example.png"},
        )

    assert store.get("atomic-run")["revision"] == 1
    assert state_path.read_bytes() == committed_bytes
    store.close()


def test_workflow_store_rejects_malformed_persistence(tmp_path) -> None:
    state_path = tmp_path / "learning-workflow-runs.json"
    state_path.write_text("{", encoding="utf-8")

    with pytest.raises(
        LearningWorkflowTransitionError,
        match="persistence is unreadable",
    ):
        LearningWorkflowRunStore(state_path=state_path)


def test_workflow_store_rejects_snapshot_tampering(tmp_path) -> None:
    state_path = tmp_path / "learning-workflow-runs.json"
    store = LearningWorkflowRunStore(state_path=state_path)
    store.transition(
        run_id="tampered-run",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )
    store.close()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["runs"][0]["revision"] = 7
    state_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with pytest.raises(
        LearningWorkflowTransitionError,
        match="does not match event history",
    ):
        LearningWorkflowRunStore(state_path=state_path)


def test_workflow_store_persists_terminal_run_eviction(tmp_path) -> None:
    state_path = tmp_path / "learning-workflow-runs.json"
    store = LearningWorkflowRunStore(max_runs=2, state_path=state_path)
    store.transition(
        run_id="terminal-run",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )
    store.transition(
        run_id="terminal-run",
        expected_revision=1,
        stage="bind_capture",
        outcome="safe_stopped",
        reason="用户停止",
    )
    for run_id in ("active-run", "replacement-run"):
        store.transition(
            run_id=run_id,
            expected_revision=0,
            stage="bind_capture",
            outcome="running",
        )
    store.close()

    restarted_store = LearningWorkflowRunStore(
        max_runs=2,
        state_path=state_path,
    )
    with pytest.raises(
        LearningWorkflowTransitionError,
        match="workflow run not found",
    ):
        restarted_store.get("terminal-run")
    assert restarted_store.get("active-run")["revision"] == 1
    assert restarted_store.get("replacement-run")["revision"] == 1
    restarted_store.close()


def test_restarted_running_operation_is_projected_as_detached(tmp_path) -> None:
    store = LearningWorkflowRunStore()
    state = store.transition(
        run_id="detached-run",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )
    state = store.transition(
        run_id="detached-run",
        expected_revision=state["revision"],
        stage="bind_capture",
        outcome="completed",
        evidence_refs={"image_path": "artifacts/example.png"},
    )
    state = store.transition(
        run_id="detached-run",
        expected_revision=state["revision"],
        stage="screen_understanding",
        outcome="running",
        evidence_refs={
            "stage_execution": {
                "contract_version": "learning_workflow_stage_operation_v1",
                "owner": "backend_lease",
                "operation_id": "operation-before-restart",
                "started_at": "2026-07-25T00:00:00+00:00",
                "lease_expires_at": "2026-07-25T01:00:00+00:00",
            }
        },
    )
    restarted_registry = LearningStageWorkerRegistry(
        result_root=tmp_path / "worker-results",
    )

    attachment = project_learning_workflow_runtime_attachment(
        workflow_state=state,
        worker_registry=restarted_registry,
    )

    assert attachment["status"] == "running_detached"
    assert attachment["recovery_status"] == "recovery_required"
    assert attachment["worker_confirmed"] is False
    assert attachment["operation_id"] == "operation-before-restart"


def test_running_operation_is_attached_only_when_registry_confirms_worker() -> None:
    class ConfirmedWorkerRegistry:
        def attachment_by_operation(self, *, run_id, stage, operation_id):
            assert run_id == "attached-run"
            assert stage == "screen_understanding"
            assert operation_id == "operation-attached"
            return {
                "worker_id": "worker-attached",
                "status": "running",
                "runtime_attached": True,
                "result_available": False,
            }

    store = LearningWorkflowRunStore()
    state = store.transition(
        run_id="attached-run",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )
    state = store.transition(
        run_id="attached-run",
        expected_revision=state["revision"],
        stage="bind_capture",
        outcome="completed",
        evidence_refs={"image_path": "artifacts/example.png"},
    )
    state = store.transition(
        run_id="attached-run",
        expected_revision=state["revision"],
        stage="screen_understanding",
        outcome="running",
        evidence_refs={
            "stage_execution": {
                "contract_version": "learning_workflow_stage_operation_v1",
                "owner": "backend_lease",
                "operation_id": "operation-attached",
            }
        },
    )

    attachment = project_learning_workflow_runtime_attachment(
        workflow_state=state,
        worker_registry=ConfirmedWorkerRegistry(),
    )

    assert attachment["status"] == "running_attached"
    assert attachment["recovery_status"] == "none"
    assert attachment["worker_confirmed"] is True
    assert attachment["worker_id"] == "worker-attached"


def test_restarted_worker_journal_is_not_reported_as_runtime_attached() -> None:
    class JournalWorkerRegistry:
        def attachment_by_operation(self, *, run_id, stage, operation_id):
            assert run_id == "journal-run"
            assert stage == "screen_understanding"
            assert operation_id == "operation-journal"
            return {
                "worker_id": "worker-journal",
                "status": "detached_running",
                "runtime_attached": False,
                "result_available": False,
            }

    store = LearningWorkflowRunStore()
    state = store.transition(
        run_id="journal-run",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )
    state = store.transition(
        run_id="journal-run",
        expected_revision=state["revision"],
        stage="bind_capture",
        outcome="completed",
        evidence_refs={"image_path": "artifacts/example.png"},
    )
    state = store.transition(
        run_id="journal-run",
        expected_revision=state["revision"],
        stage="screen_understanding",
        outcome="running",
        evidence_refs={
            "stage_execution": {
                "contract_version": "learning_workflow_stage_operation_v1",
                "owner": "backend_lease",
                "operation_id": "operation-journal",
            }
        },
    )

    attachment = project_learning_workflow_runtime_attachment(
        workflow_state=state,
        worker_registry=JournalWorkerRegistry(),
    )

    assert attachment["status"] == "running_detached"
    assert attachment["recovery_status"] == "recovery_required"
    assert attachment["worker_confirmed"] is False
    assert attachment["journal_confirmed"] is True
    assert attachment["result_available"] is False


def test_restarted_worker_result_is_projected_as_available_for_explicit_resume() -> None:
    class CompletedWorkerRegistry:
        def attachment_by_operation(self, *, run_id, stage, operation_id):
            assert run_id == "result-run"
            assert stage == "screen_understanding"
            assert operation_id == "operation-result"
            return {
                "worker_id": "worker-result",
                "status": "completed",
                "runtime_attached": False,
                "result_available": True,
                "result_adopted": False,
            }

    store = LearningWorkflowRunStore()
    state = store.transition(
        run_id="result-run",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )
    state = store.transition(
        run_id="result-run",
        expected_revision=state["revision"],
        stage="bind_capture",
        outcome="completed",
        evidence_refs={"image_path": "artifacts/example.png"},
    )
    state = store.transition(
        run_id="result-run",
        expected_revision=state["revision"],
        stage="screen_understanding",
        outcome="running",
        evidence_refs={
            "stage_execution": {
                "contract_version": "learning_workflow_stage_operation_v1",
                "owner": "backend_lease",
                "operation_id": "operation-result",
            }
        },
    )

    attachment = project_learning_workflow_runtime_attachment(
        workflow_state=state,
        worker_registry=CompletedWorkerRegistry(),
    )

    assert attachment["status"] == "worker_finished"
    assert attachment["recovery_status"] == "result_available"
    assert attachment["worker_confirmed"] is False
    assert attachment["journal_confirmed"] is True
    assert attachment["result_available"] is True
    assert attachment["result_adopted"] is False


def test_restarted_adopted_worker_result_projects_continuation_required() -> None:
    class AdoptedWorkerRegistry:
        def attachment_by_operation(self, *, run_id, stage, operation_id):
            assert run_id == "adopted-run"
            assert stage == "screen_understanding"
            assert operation_id == "operation-adopted"
            return {
                "worker_id": "worker-adopted",
                "status": "completed",
                "runtime_attached": False,
                "result_available": True,
                "result_adopted": True,
            }

    store = LearningWorkflowRunStore()
    state = store.transition(
        run_id="adopted-run",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )
    state = store.transition(
        run_id="adopted-run",
        expected_revision=state["revision"],
        stage="bind_capture",
        outcome="completed",
        evidence_refs={"image_path": "artifacts/example.png"},
    )
    state = store.transition(
        run_id="adopted-run",
        expected_revision=state["revision"],
        stage="screen_understanding",
        outcome="running",
        evidence_refs={
            "stage_execution": {
                "contract_version": "learning_workflow_stage_operation_v1",
                "owner": "backend_lease",
                "operation_id": "operation-adopted",
            }
        },
    )

    attachment = project_learning_workflow_runtime_attachment(
        workflow_state=state,
        worker_registry=AdoptedWorkerRegistry(),
    )

    assert attachment["status"] == "worker_finished"
    assert attachment["recovery_status"] == "result_adopted"
    assert attachment["result_available"] is True
    assert attachment["result_adopted"] is True


def test_workflow_state_endpoint_exposes_runtime_attachment(
    tmp_path,
    monkeypatch,
) -> None:
    store = LearningWorkflowRunStore()
    state = store.transition(
        run_id="endpoint-detached-run",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )
    state = store.transition(
        run_id="endpoint-detached-run",
        expected_revision=state["revision"],
        stage="bind_capture",
        outcome="completed",
        evidence_refs={"image_path": "artifacts/example.png"},
    )
    store.transition(
        run_id="endpoint-detached-run",
        expected_revision=state["revision"],
        stage="screen_understanding",
        outcome="running",
        evidence_refs={
            "stage_execution": {
                "contract_version": "learning_workflow_stage_operation_v1",
                "owner": "backend_lease",
                "operation_id": "operation-before-api-restart",
                "started_at": "2026-07-25T00:00:00+00:00",
                "lease_expires_at": "2026-07-25T01:00:00+00:00",
            }
        },
    )
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(
        panel_api,
        "learning_stage_worker_registry",
        LearningStageWorkerRegistry(result_root=tmp_path / "worker-results"),
    )

    response = TestClient(app).get(
        "/panel/learning_workflow_state/endpoint-detached-run"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["runtime_attachment"]["status"] == "running_detached"
    assert (
        payload["data"]["runtime_attachment"]["recovery_status"]
        == "recovery_required"
    )
