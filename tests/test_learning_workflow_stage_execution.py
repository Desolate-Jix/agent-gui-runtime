from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import panel as panel_api
from app.learn import workflow_service
from app.learn.workflow_service import (
    LearningWorkflowStageOperationError,
    cancel_learning_workflow_stage_operation,
    finish_learning_workflow_stage_operation,
    recover_expired_learning_workflow_stage_operation,
    start_learning_workflow_stage_operation,
)
from app.learn.workflow_state import (
    LEARNING_WORKFLOW_COMPLETION_EVIDENCE,
    LEARNING_WORKFLOW_STAGES,
)
from app.learn.workflow_store import LearningWorkflowRunStore
from app.main import app


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def _hybrid_supervised_lineage(
    *,
    run_id: str,
    workflow_revision: int,
    operation_id: str,
    stage: str = "screen_understanding",
) -> dict:
    return {
        "run_id": run_id,
        "workflow_revision": workflow_revision,
        "operation_id": operation_id,
        "stage": stage,
        "stage_execution_id": hashlib.sha256(
            json.dumps(
                {
                    "run_id": run_id,
                    "workflow_revision": workflow_revision,
                    "operation_id": operation_id,
                    "stage": stage,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }


def _observed_hybrid_cleanup_receipt(
    provider: str,
    *,
    lineage: dict,
    predecessor: dict,
    provider_result: dict,
) -> dict:
    from app.learn.hybrid.gpu_lifecycle import release_hybrid_provider
    from app.learn.hybrid.windows_process_scope import process_scope_name
    from app.learn.recognition.uei.canonical import content_sha256

    process_identity = {
        "pid": 5100 + len(provider),
        "create_time_ns": 100_000_000_000,
    }
    if provider == "omni":
        provider_identity = {
            "provider_invocation_id": "invocation/controlled-omni",
            "provider_receipt_ref": {
                "id": "receipt/controlled-omni",
                "content_sha256": "a" * 64,
            },
            "process_identity": process_identity,
        }
    elif provider == "qwen":
        provider_identity = {
            "lease_id": "controlled-qwen-lease",
            "incarnation_id": "qwen-controlled",
            "profile_id": "qwen-profile",
            "server_process_identity": process_identity,
        }
    else:
        provider_identity = {
            "incarnation_id": "vista-controlled",
            "profile_id": "vista-profile",
            "process_identities": [process_identity],
        }
    provider_identity["process_scope_name"] = process_scope_name(lineage, provider)
    inventory = {
        "contract_version": "hybrid_provider_process_inventory_v2",
        "provider": provider,
        "observer_contract": f"hybrid_{provider}_cleanup_observer_v1",
        "release_status": "verified",
        "termination_reason": "completed",
        "lineage": lineage,
        "provider_lease_identity": provider_identity,
        "predecessor_sha256": content_sha256(predecessor),
        "provider_result_sha256": content_sha256(provider_result),
        "provider_processes_after": [],
        "helper_processes_after": [],
        "orphan_descendant_pids": [],
        "active_listeners_after": [],
        "lease_files_after": [],
        "source_cleanup_evidence": {"status": "verified"},
    }
    return release_hybrid_provider(provider, process_inventory=lambda _: inventory)


def _completion_evidence(stage: str) -> dict[str, str]:
    return {
        field: f"artifacts/learning-runs/run-stage-operation/{stage}-{field}.json"
        for field in LEARNING_WORKFLOW_COMPLETION_EVIDENCE[stage]
    }


def _store_at_completed_review() -> tuple[LearningWorkflowRunStore, dict]:
    store = LearningWorkflowRunStore()
    state: dict | None = None
    for stage in LEARNING_WORKFLOW_STAGES:
        state = store.transition(
            run_id="run-stage-operation",
            expected_revision=0 if state is None else state["revision"],
            stage=stage,
            outcome="running",
        )
        state = store.transition(
            run_id="run-stage-operation",
            expected_revision=state["revision"],
            stage=stage,
            outcome="completed",
            evidence_refs=_completion_evidence(stage),
        )
        if stage == "review_repair":
            return store, state
    raise AssertionError("review_repair stage was not reached")


def _store_at_completed_bind_capture() -> tuple[LearningWorkflowRunStore, dict]:
    store = LearningWorkflowRunStore()
    state = store.transition(
        run_id="run-stage-operation",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )
    state = store.transition(
        run_id="run-stage-operation",
        expected_revision=state["revision"],
        stage="bind_capture",
        outcome="completed",
        evidence_refs=_completion_evidence("bind_capture"),
    )
    return store, state


def _store_at_completed_screen_understanding() -> tuple[
    LearningWorkflowRunStore,
    dict,
]:
    store, state = _store_at_completed_bind_capture()
    state = store.transition(
        run_id="run-stage-operation",
        expected_revision=state["revision"],
        stage="screen_understanding",
        outcome="running",
    )
    state = store.transition(
        run_id="run-stage-operation",
        expected_revision=state["revision"],
        stage="screen_understanding",
        outcome="completed",
        evidence_refs=_completion_evidence("screen_understanding"),
    )
    return store, state


def _store_at_completed_numbered_map() -> tuple[LearningWorkflowRunStore, dict]:
    store = LearningWorkflowRunStore()
    state: dict | None = None
    for stage in LEARNING_WORKFLOW_STAGES:
        state = store.transition(
            run_id="run-stage-operation",
            expected_revision=0 if state is None else state["revision"],
            stage=stage,
            outcome="running",
        )
        state = store.transition(
            run_id="run-stage-operation",
            expected_revision=state["revision"],
            stage=stage,
            outcome="completed",
            evidence_refs=_completion_evidence(stage),
        )
        if stage == "numbered_map":
            return store, state
    raise AssertionError("numbered_map stage was not reached")


def _store_at_completed_precise_calibration() -> tuple[LearningWorkflowRunStore, dict]:
    store = LearningWorkflowRunStore()
    state: dict | None = None
    for stage in LEARNING_WORKFLOW_STAGES:
        state = store.transition(
            run_id="run-stage-operation",
            expected_revision=0 if state is None else state["revision"],
            stage=stage,
            outcome="running",
        )
        state = store.transition(
            run_id="run-stage-operation",
            expected_revision=state["revision"],
            stage=stage,
            outcome="completed",
            evidence_refs=_completion_evidence(stage),
        )
        if stage == "precise_calibration":
            return store, state
    raise AssertionError("precise_calibration stage was not reached")


def _write_trial(tmp_path: Path) -> Path:
    trial_path = (
        tmp_path
        / "artifacts"
        / "learning-runs"
        / "run-stage-operation"
        / "fusion-trial.json"
    )
    trial_path.parent.mkdir(parents=True, exist_ok=True)
    trial_path.write_text(
        json.dumps(
            {"contract_version": "learning_model_trial_v1"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return trial_path


def test_stage_operation_start_issues_server_owned_lease() -> None:
    store, review_state = _store_at_completed_review()

    result = start_learning_workflow_stage_operation(
        store=store,
        project_root=Path("."),
        run_id="run-stage-operation",
        expected_revision=review_state["revision"],
        stage="fusion",
        reason="fusing reviewed learning evidence",
        lease_seconds=600,
        now=NOW,
        operation_id="operation-fusion-1",
    )

    assert result["contract_version"] == "learning_workflow_stage_operation_v1"
    assert result["operation_id"] == "operation-fusion-1"
    assert result["stage"] == "fusion"
    assert result["status"] == "running"
    assert result["started_at"] == NOW.isoformat()
    assert result["lease_expires_at"] == (NOW + timedelta(seconds=600)).isoformat()
    state = result["workflow_state"]
    assert state["stages"]["fusion"]["status"] == "running"
    execution = state["stages"]["fusion"]["evidence_refs"]["stage_execution"]
    assert execution["owner"] == "backend_lease"
    assert execution["operation_id"] == "operation-fusion-1"


def test_stage_operation_matching_finish_completes_with_verified_evidence(
    tmp_path: Path,
) -> None:
    store, review_state = _store_at_completed_review()
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-stage-operation",
        expected_revision=review_state["revision"],
        stage="fusion",
        lease_seconds=600,
        now=NOW,
        operation_id="operation-fusion-2",
    )
    trial_path = _write_trial(tmp_path)

    result = finish_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-stage-operation",
        expected_revision=started["workflow_state"]["revision"],
        stage="fusion",
        operation_id="operation-fusion-2",
        outcome="completed",
        reason="fusion trial ready",
        evidence_refs={"trial_path": str(trial_path)},
        now=NOW + timedelta(seconds=30),
    )

    assert result["status"] == "completed"
    state = result["workflow_state"]
    assert state["stages"]["fusion"]["status"] == "completed"
    evidence = state["stages"]["fusion"]["evidence_refs"]
    assert evidence["evidence_integrity"]["verified"] is True
    assert evidence["stage_execution"]["operation_id"] == "operation-fusion-2"
    assert evidence["stage_execution"]["finished_at"] == (
        NOW + timedelta(seconds=30)
    ).isoformat()


def test_stage_operation_rejects_mismatched_operation_id() -> None:
    store, review_state = _store_at_completed_review()
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=Path("."),
        run_id="run-stage-operation",
        expected_revision=review_state["revision"],
        stage="fusion",
        lease_seconds=600,
        now=NOW,
        operation_id="operation-fusion-owner",
    )

    with pytest.raises(
        LearningWorkflowStageOperationError,
        match="operation_id does not match",
    ):
        finish_learning_workflow_stage_operation(
            store=store,
            project_root=Path("."),
            run_id="run-stage-operation",
            expected_revision=started["workflow_state"]["revision"],
            stage="fusion",
            operation_id="operation-fusion-stale",
            outcome="failed",
            reason="stale caller",
            now=NOW + timedelta(seconds=10),
        )

    persisted = store.get("run-stage-operation")
    assert persisted["revision"] == started["workflow_state"]["revision"]
    assert persisted["stages"]["fusion"]["status"] == "running"


def test_stage_operation_rejects_late_finish_after_lease_expiry() -> None:
    store, review_state = _store_at_completed_review()
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=Path("."),
        run_id="run-stage-operation",
        expected_revision=review_state["revision"],
        stage="fusion",
        lease_seconds=60,
        now=NOW,
        operation_id="operation-fusion-expired",
    )

    with pytest.raises(
        LearningWorkflowStageOperationError,
        match="lease expired",
    ):
        finish_learning_workflow_stage_operation(
            store=store,
            project_root=Path("."),
            run_id="run-stage-operation",
            expected_revision=started["workflow_state"]["revision"],
            stage="fusion",
            operation_id="operation-fusion-expired",
            outcome="failed",
            reason="late result",
            now=NOW + timedelta(seconds=61),
        )

    assert store.get("run-stage-operation")["stages"]["fusion"]["status"] == "running"


def test_stage_operation_heartbeat_extends_lease_and_remains_replayable(
    tmp_path: Path,
) -> None:
    store, review_state = _store_at_completed_review()
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-stage-operation",
        expected_revision=review_state["revision"],
        stage="fusion",
        lease_seconds=600,
        now=NOW,
        operation_id="operation-fusion-heartbeat",
    )

    heartbeat = workflow_service.heartbeat_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-stage-operation",
        expected_revision=started["workflow_state"]["revision"],
        stage="fusion",
        operation_id="operation-fusion-heartbeat",
        lease_seconds=600,
        now=NOW + timedelta(seconds=590),
    )

    assert heartbeat["status"] == "running"
    assert heartbeat["heartbeat_count"] == 1
    assert heartbeat["last_heartbeat_at"] == (
        NOW + timedelta(seconds=590)
    ).isoformat()
    assert heartbeat["lease_expires_at"] == (
        NOW + timedelta(seconds=1190)
    ).isoformat()
    replayed = store.get("run-stage-operation")
    assert replayed == heartbeat["workflow_state"]

    trial_path = _write_trial(tmp_path)
    finished = finish_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-stage-operation",
        expected_revision=heartbeat["workflow_state"]["revision"],
        stage="fusion",
        operation_id="operation-fusion-heartbeat",
        outcome="completed",
        reason="completed after renewed lease",
        evidence_refs={"trial_path": str(trial_path)},
        now=NOW + timedelta(seconds=900),
    )

    assert finished["status"] == "completed"
    execution = finished["workflow_state"]["stages"]["fusion"]["evidence_refs"][
        "stage_execution"
    ]
    assert execution["heartbeat_count"] == 1
    assert execution["lease_expires_at"] == (
        NOW + timedelta(seconds=1190)
    ).isoformat()


def test_stage_operation_heartbeat_rejects_expired_or_mismatched_owner() -> None:
    store, review_state = _store_at_completed_review()
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=Path("."),
        run_id="run-stage-operation",
        expected_revision=review_state["revision"],
        stage="fusion",
        lease_seconds=600,
        now=NOW,
        operation_id="operation-fusion-heartbeat-owner",
    )
    revision = started["workflow_state"]["revision"]

    with pytest.raises(
        LearningWorkflowStageOperationError,
        match="operation_id does not match",
    ):
        workflow_service.heartbeat_learning_workflow_stage_operation(
            store=store,
            project_root=Path("."),
            run_id="run-stage-operation",
            expected_revision=revision,
            stage="fusion",
            operation_id="operation-fusion-stale-owner",
            lease_seconds=600,
            now=NOW + timedelta(seconds=30),
        )

    with pytest.raises(
        LearningWorkflowStageOperationError,
        match="lease expired before heartbeat",
    ):
        workflow_service.heartbeat_learning_workflow_stage_operation(
            store=store,
            project_root=Path("."),
            run_id="run-stage-operation",
            expected_revision=revision,
            stage="fusion",
            operation_id="operation-fusion-heartbeat-owner",
            lease_seconds=600,
            now=NOW + timedelta(seconds=601),
        )

    persisted = store.get("run-stage-operation")
    assert persisted["revision"] == revision
    assert persisted["stages"]["fusion"]["status"] == "running"


def test_stage_operation_cancel_safe_stops_owned_operation_and_rejects_late_result(
    tmp_path: Path,
) -> None:
    store, review_state = _store_at_completed_review()
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-stage-operation",
        expected_revision=review_state["revision"],
        stage="fusion",
        lease_seconds=600,
        now=NOW,
        operation_id="operation-fusion-cancel",
    )

    cancelled = cancel_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-stage-operation",
        expected_revision=started["workflow_state"]["revision"],
        stage="fusion",
        operation_id="operation-fusion-cancel",
        reason="user requested cancellation",
        now=NOW + timedelta(seconds=30),
    )

    assert cancelled["status"] == "safe_stopped"
    assert cancelled["cancellation_status"] == "state_cancelled"
    assert cancelled["backend_compute_termination"] == "not_covered"
    state = cancelled["workflow_state"]
    assert state["terminal"] is True
    assert state["workflow_status"] == "safe_stopped"
    assert state["stages"]["fusion"]["status"] == "safe_stopped"
    execution = state["stages"]["fusion"]["evidence_refs"]["stage_execution"]
    assert execution["operation_id"] == "operation-fusion-cancel"
    assert execution["result_outcome"] == "safe_stopped"
    assert execution["cancellation"]["requested_at"] == (
        NOW + timedelta(seconds=30)
    ).isoformat()
    assert execution["cancellation"]["requested_by"] == "panel_user"
    assert execution["cancellation"]["backend_compute_termination"] == "not_covered"

    with pytest.raises(LearningWorkflowStageOperationError, match="not running"):
        workflow_service.heartbeat_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-stage-operation",
            expected_revision=state["revision"],
            stage="fusion",
            operation_id="operation-fusion-cancel",
            now=NOW + timedelta(seconds=31),
        )

    with pytest.raises(LearningWorkflowStageOperationError, match="not running"):
        finish_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-stage-operation",
            expected_revision=state["revision"],
            stage="fusion",
            operation_id="operation-fusion-cancel",
            outcome="completed",
            reason="late result",
            evidence_refs={"trial_path": str(_write_trial(tmp_path))},
            now=NOW + timedelta(seconds=31),
        )


def test_stage_operation_cancel_rejects_mismatched_or_expired_owner() -> None:
    store, review_state = _store_at_completed_review()
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=Path("."),
        run_id="run-stage-operation",
        expected_revision=review_state["revision"],
        stage="fusion",
        lease_seconds=60,
        now=NOW,
        operation_id="operation-fusion-cancel-owner",
    )
    revision = started["workflow_state"]["revision"]

    with pytest.raises(
        LearningWorkflowStageOperationError,
        match="operation_id does not match",
    ):
        cancel_learning_workflow_stage_operation(
            store=store,
            project_root=Path("."),
            run_id="run-stage-operation",
            expected_revision=revision,
            stage="fusion",
            operation_id="operation-fusion-stale-owner",
            reason="wrong owner",
            now=NOW + timedelta(seconds=30),
        )

    with pytest.raises(
        LearningWorkflowStageOperationError,
        match="lease expired before cancellation",
    ):
        cancel_learning_workflow_stage_operation(
            store=store,
            project_root=Path("."),
            run_id="run-stage-operation",
            expected_revision=revision,
            stage="fusion",
            operation_id="operation-fusion-cancel-owner",
            reason="late cancellation",
            now=NOW + timedelta(seconds=61),
        )

    persisted = store.get("run-stage-operation")
    assert persisted["revision"] == revision
    assert persisted["stages"]["fusion"]["status"] == "running"


def test_expired_stage_operation_recovery_marks_exact_stage_failed() -> None:
    store, review_state = _store_at_completed_review()
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=Path("."),
        run_id="run-stage-operation",
        expected_revision=review_state["revision"],
        stage="fusion",
        lease_seconds=60,
        now=NOW,
        operation_id="operation-fusion-recover",
    )

    result = recover_expired_learning_workflow_stage_operation(
        store=store,
        project_root=Path("."),
        run_id="run-stage-operation",
        expected_revision=started["workflow_state"]["revision"],
        now=NOW + timedelta(seconds=61),
    )

    assert result["recovered"] is True
    assert result["recovery_status"] == "expired_operation_failed"
    state = result["workflow_state"]
    assert state["terminal"] is True
    assert state["workflow_status"] == "failed"
    assert state["stages"]["fusion"]["status"] == "failed"
    assert "lease expired" in state["stages"]["fusion"]["reason"]
    assert state["stages"]["page_details"]["status"] == "pending"


def test_stage_operation_recovery_does_not_change_live_or_legacy_running_stage() -> None:
    store, review_state = _store_at_completed_review()
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=Path("."),
        run_id="run-stage-operation",
        expected_revision=review_state["revision"],
        stage="fusion",
        lease_seconds=600,
        now=NOW,
        operation_id="operation-fusion-live",
    )

    live = recover_expired_learning_workflow_stage_operation(
        store=store,
        project_root=Path("."),
        run_id="run-stage-operation",
        expected_revision=started["workflow_state"]["revision"],
        now=NOW + timedelta(seconds=30),
    )

    assert live["recovered"] is False
    assert live["recovery_status"] == "lease_active"
    assert live["workflow_state"]["revision"] == started["workflow_state"]["revision"]

    legacy_store, legacy_review = _store_at_completed_review()
    legacy_running = legacy_store.transition(
        run_id="run-stage-operation",
        expected_revision=legacy_review["revision"],
        stage="fusion",
        outcome="running",
    )
    legacy = recover_expired_learning_workflow_stage_operation(
        store=legacy_store,
        project_root=Path("."),
        run_id="run-stage-operation",
        expected_revision=legacy_running["revision"],
        now=NOW + timedelta(days=1),
    )

    assert legacy["recovered"] is False
    assert legacy["recovery_status"] == "not_managed"
    assert legacy["workflow_state"]["revision"] == legacy_running["revision"]


def test_stage_operation_api_round_trip_and_direct_fusion_transition_rejection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store, review_state = _store_at_completed_review()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    client = TestClient(app)

    direct = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": review_state["revision"],
            "stage": "fusion",
            "outcome": "running",
        },
    ).json()
    assert direct["success"] is False
    assert direct["error"]["code"] == "learning_workflow_stage_operation_required"

    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": review_state["revision"],
            "stage": "fusion",
            "reason": "panel fusion",
            "lease_seconds": 600,
        },
    ).json()
    assert started["success"] is True
    operation_id = started["data"]["operation_id"]
    trial_path = _write_trial(tmp_path)

    finished = client.post(
        "/panel/finish_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["data"]["workflow_state"]["revision"],
            "stage": "fusion",
            "operation_id": operation_id,
            "outcome": "completed",
            "reason": "fusion trial ready",
            "evidence_refs": {"trial_path": str(trial_path)},
        },
    ).json()

    assert finished["success"] is True
    assert finished["data"]["workflow_state"]["stages"]["fusion"]["status"] == "completed"


def test_stage_operation_heartbeat_api_renews_owned_operation(
    monkeypatch,
) -> None:
    store, review_state = _store_at_completed_review()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": review_state["revision"],
            "stage": "fusion",
            "reason": "panel fusion",
            "lease_seconds": 30,
        },
    ).json()["data"]

    heartbeat = client.post(
        "/panel/heartbeat_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "fusion",
            "operation_id": started["operation_id"],
            "lease_seconds": 600,
        },
    ).json()

    assert heartbeat["success"] is True
    assert heartbeat["data"]["heartbeat_count"] == 1
    assert heartbeat["data"]["workflow_state"]["revision"] == (
        started["workflow_state"]["revision"] + 1
    )
    assert (
        heartbeat["data"]["workflow_state"]["stages"]["fusion"]["evidence_refs"][
            "stage_execution"
        ]["operation_id"]
        == started["operation_id"]
    )


def test_stage_operation_cancel_api_safe_stops_owned_operation(
    monkeypatch,
) -> None:
    store, review_state = _store_at_completed_review()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": review_state["revision"],
            "stage": "fusion",
            "reason": "panel fusion",
            "lease_seconds": 600,
        },
    ).json()["data"]

    cancelled = client.post(
        "/panel/cancel_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "fusion",
            "operation_id": started["operation_id"],
            "reason": "user requested cancellation",
        },
    ).json()

    assert cancelled["success"] is True
    assert cancelled["data"]["status"] == "safe_stopped"
    assert cancelled["data"]["cancellation_status"] == "state_cancelled"
    assert cancelled["data"]["backend_compute_termination"] == "not_covered"


def test_guarded_stage_worker_api_preserves_full_response_bytes(
    monkeypatch,
) -> None:
    store, review_state = _store_at_completed_review()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)

    class _WorkerRegistry:
        def start(self, **kwargs):
            assert kwargs["run_id"] == "run-stage-operation"
            assert kwargs["stage"] == "fusion"
            assert kwargs["task_kind"] == "panel_learning_recognition_trial"
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-1",
                "run_id": kwargs["run_id"],
                "stage": kwargs["stage"],
                "operation_id": kwargs["operation_id"],
                "task_kind": kwargs["task_kind"],
                "status": "running",
                "backend_compute_owner": "backend_process_worker",
            }

        def status(self, **kwargs):
            assert kwargs["worker_id"] == "worker-1"
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-1",
                "run_id": kwargs["run_id"],
                "stage": "fusion",
                "operation_id": kwargs["operation_id"],
                "task_kind": "panel_learning_recognition_trial",
                "status": "completed",
                "backend_compute_owner": "backend_process_worker",
                "result_available": True,
                "result_adopted": False,
            }

        def adopt_result(self, **kwargs):
            assert kwargs["worker_id"] == "worker-1"
            assert kwargs["stage"] == "fusion"
            return {
                "contract_version": "learning_stage_worker_result_adoption_v1",
                "status": "adopted",
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-1",
                    "result_sha256": "a" * 64,
                },
                "response": {"success": True, "data": {"trial_path": "trial.json"}},
            }

    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", _WorkerRegistry())
    client = TestClient(app)
    started_operation = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": review_state["revision"],
            "stage": "fusion",
            "reason": "panel fusion",
            "lease_seconds": 600,
        },
    ).json()["data"]

    started_worker = client.post(
        "/panel/start_learning_stage_worker",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started_operation["workflow_state"]["revision"],
            "stage": "fusion",
            "operation_id": started_operation["operation_id"],
            "task_kind": "panel_learning_recognition_trial",
            "payload": {"app_name": "test"},
        },
    ).json()
    assert json.dumps(started_worker, sort_keys=True) == json.dumps(
        {
            "success": True,
            "message": "Learning stage worker started",
            "data": {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-1",
                "run_id": "run-stage-operation",
                "stage": "fusion",
                "operation_id": started_operation["operation_id"],
                "task_kind": "panel_learning_recognition_trial",
                "status": "running",
                "backend_compute_owner": "backend_process_worker",
            },
            "error": None,
        },
        sort_keys=True,
    )

    worker_status = client.get(
        "/panel/learning_stage_worker/worker-1",
        params={
            "run_id": "run-stage-operation",
            "operation_id": started_operation["operation_id"],
        },
    ).json()
    assert json.dumps(worker_status, sort_keys=True) == json.dumps(
        {
            "success": True,
            "message": "Learning stage worker status",
            "data": {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-1",
                "run_id": "run-stage-operation",
                "stage": "fusion",
                "operation_id": started_operation["operation_id"],
                "task_kind": "panel_learning_recognition_trial",
                "status": "completed",
                "backend_compute_owner": "backend_process_worker",
                "result_available": True,
                "result_adopted": False,
            },
            "error": None,
        },
        sort_keys=True,
    )

    adopted = client.post(
        "/panel/adopt_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started_operation["workflow_state"]["revision"],
            "stage": "fusion",
            "operation_id": started_operation["operation_id"],
            "worker_id": "worker-1",
        },
    ).json()
    assert json.dumps(adopted, sort_keys=True) == json.dumps(
        {
            "success": True,
            "message": "Learning stage worker result adopted",
            "data": {
                "contract_version": "learning_stage_worker_result_adoption_v1",
                "status": "adopted",
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-1",
                    "result_sha256": "a" * 64,
                },
                "response": {
                    "success": True,
                    "data": {"trial_path": "trial.json"},
                },
            },
            "error": None,
        },
        sort_keys=True,
    )


def test_continuation_finishes_numbered_map_from_adopted_worker_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    store, screen_state = _store_at_completed_screen_understanding()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    report_path = tmp_path / "artifacts" / "numbered-map-report.json"
    overlay_path = tmp_path / "artifacts" / "numbered-map-overlay.png"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "app_name": "qq",
                "state_hint": "chat",
                "source_trace_path": "logs/traces/vision/qq-observe.json",
                "observe_bundle": {
                    "image_path": "artifacts/screenshots/qq.png",
                },
                "source_graph_revision": "numbering-revision-1",
                "stage2_numbering": {
                    "calibration_candidate_count": 3,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overlay_path.write_bytes(b"overlay")

    class _WorkerRegistry:
        def __init__(self) -> None:
            self.started: list[dict] = []

        def read_adopted_result(self, **kwargs):
            assert kwargs["stage"] == "numbered_map"
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-numbered",
                    "task_kind": "panel_learning_two_stage_understanding",
                    "result_sha256": "a" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "result": {
                            "report_path": "artifacts/numbered-map-report.json",
                            "compiled_overlay_path": (
                                "artifacts/numbered-map-overlay.png"
                            ),
                            "stage1_gate": {"status": "passed"},
                            "stage2_numbering_skipped": False,
                        }
                    },
                },
            }

        def start(self, **kwargs):
            self.started.append(kwargs)
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-calibration-auto",
                "run_id": kwargs["run_id"],
                "stage": kwargs["stage"],
                "operation_id": kwargs["operation_id"],
                "task_kind": kwargs["task_kind"],
                "status": "running",
            }

    registry = _WorkerRegistry()
    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", registry)
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": screen_state["revision"],
            "stage": "numbered_map",
            "reason": "numbering",
            "lease_seconds": 600,
        },
    ).json()["data"]
    request = {
        "run_id": "run-stage-operation",
        "expected_revision": started["workflow_state"]["revision"],
        "stage": "numbered_map",
        "operation_id": started["operation_id"],
        "worker_id": "worker-numbered",
    }

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json=request,
    ).json()

    assert continued["success"] is True
    assert continued["data"]["contract_version"] == (
        "learning_stage_worker_continuation_v1"
    )
    assert continued["data"]["stage_finished"] is True
    assert continued["data"]["outcome"] == "completed"
    workflow_state = continued["data"]["workflow_state"]
    assert workflow_state["stages"]["numbered_map"]["status"] == "completed"
    evidence = workflow_state["stages"]["numbered_map"]["evidence_refs"]
    assert evidence["worker_continuation"]["worker_id"] == "worker-numbered"
    assert evidence["worker_continuation"]["result_sha256"] == "a" * 64
    next_operation = continued["data"]["next_stage_operation"]
    assert next_operation["stage"] == "precise_calibration"
    assert next_operation["task_kind"] == "panel_learning_calibration_sequence"
    assert workflow_state["current_stage"] == "precise_calibration"
    assert workflow_state["stages"]["precise_calibration"]["status"] == "running"
    next_worker = continued["data"]["next_stage_worker"]
    assert next_worker["worker_id"] == "worker-calibration-auto"
    calibration_start = registry.started[0]
    assert calibration_start["stage"] == "precise_calibration"
    assert calibration_start["operation_id"] == next_operation["operation_id"]
    assert calibration_start["task_kind"] == "panel_learning_calibration_sequence"
    assert calibration_start["reuse_active_identical"] is True
    assert calibration_start["payload"] == {
        "contract_version": "learning_calibration_sequence_request_v1",
        "profile_id": None,
        "candidate_count": 3,
        "calibration_source_revision": "numbering-revision-1",
        "maximum_batch_size": 8,
        "locate_payload": {
            "goal": "learn all visible controls",
            "provider_mode": "local_grounding",
            "capture_live": False,
            "image_path": "artifacts/screenshots/qq.png",
            "app_name": "qq",
            "state_hint": "chat",
            "observe_trace_path": "logs/traces/vision/qq-observe.json",
            "agent_mode": "learn",
            "learn_depth": "deep",
            "dry_run": True,
            "trace": True,
            "metadata": {
                "learning_interface_flow": True,
                "no_live_click_authorization": True,
                "learn_all_targets": True,
                "two_stage_report_path": "artifacts/numbered-map-report.json",
            },
        },
    }

    repeated = client.post(
        "/panel/continue_learning_stage_worker_result",
        json=request,
    ).json()
    assert repeated["success"] is True
    assert repeated["data"]["idempotent_replay"] is True
    assert repeated["data"]["workflow_state"]["revision"] == workflow_state["revision"]
    assert repeated["data"]["next_stage_operation"]["operation_id"] == (
        next_operation["operation_id"]
    )
    assert repeated["data"]["next_stage_worker"]["worker_id"] == (
        "worker-calibration-auto"
    )
    assert len(registry.started) == 2


def test_continuation_closes_next_operation_when_worker_start_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    store, screen_state = _store_at_completed_screen_understanding()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    report_path = tmp_path / "artifacts" / "numbered-map-report.json"
    overlay_path = tmp_path / "artifacts" / "numbered-map-overlay.png"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "app_name": "qq",
                "state_hint": "chat",
                "observe_bundle": {
                    "image_path": "artifacts/screenshots/qq.png",
                },
                "stage2_numbering": {
                    "calibration_candidate_count": 3,
                    "graph_revision": "numbering-revision-1",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overlay_path.write_bytes(b"overlay")

    class _WorkerRegistry:
        def read_adopted_result(self, **_kwargs):
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-numbered",
                    "task_kind": "panel_learning_two_stage_understanding",
                    "result_sha256": "a" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "result": {
                            "report_path": "artifacts/numbered-map-report.json",
                            "compiled_overlay_path": "artifacts/numbered-map-overlay.png",
                            "stage1_gate": {"status": "passed"},
                            "stage2_numbering_skipped": False,
                        }
                    },
                },
            }

        def start(self, **_kwargs):
            raise LearningStageWorkerError("worker process start failed")

    monkeypatch.setattr(
        panel_api,
        "learning_stage_worker_registry",
        _WorkerRegistry(),
    )
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": screen_state["revision"],
            "stage": "numbered_map",
            "reason": "numbering",
            "lease_seconds": 600,
        },
    ).json()["data"]

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "numbered_map",
            "operation_id": started["operation_id"],
            "worker_id": "worker-numbered",
        },
    ).json()

    assert continued["success"] is False
    workflow_state = store.get("run-stage-operation")
    assert workflow_state["workflow_status"] == "failed", continued
    assert workflow_state["terminal"] is True
    assert workflow_state["stages"]["precise_calibration"]["status"] == "failed"
    assert "worker start failed" in workflow_state["current_reason"]


def test_stage_worker_request_accepts_backend_calibration_task_kind() -> None:
    request = panel_api.PanelStartLearningStageWorkerRequest.model_validate(
        {
            "run_id": "run-1",
            "expected_revision": 1,
            "stage": "precise_calibration",
            "operation_id": "operation-1",
            "task_kind": "panel_learning_calibration_sequence",
            "payload": {},
        }
    )

    assert request.task_kind == "panel_learning_calibration_sequence"


def test_continuation_safe_stops_blocked_numbered_map(
    monkeypatch,
) -> None:
    store, screen_state = _store_at_completed_screen_understanding()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)

    class _WorkerRegistry:
        def read_adopted_result(self, **kwargs):
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-blocked",
                    "task_kind": "panel_learning_two_stage_understanding",
                    "result_sha256": "b" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "result": {
                            "stage1_gate": {"status": "blocked"},
                            "stage2_numbering_skipped": True,
                        }
                    },
                },
            }

    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", _WorkerRegistry())
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": screen_state["revision"],
            "stage": "numbered_map",
            "reason": "numbering",
            "lease_seconds": 600,
        },
    ).json()["data"]

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "numbered_map",
            "operation_id": started["operation_id"],
            "worker_id": "worker-blocked",
        },
    ).json()

    assert continued["success"] is True
    assert continued["data"]["stage_finished"] is True
    assert continued["data"]["outcome"] == "safe_stopped"
    assert continued["data"]["workflow_state"]["terminal"] is True


def test_continuation_persists_calibration_artifact_and_finishes_stage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    store, numbered_state = _store_at_completed_numbered_map()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    source_image = tmp_path / "artifacts" / "screenshots" / "capture.png"
    numbering_report = tmp_path / "artifacts" / "numbered-map-report.json"
    overlay_path = tmp_path / "artifacts" / "review-overlays" / "calibrated.png"
    trace_path = tmp_path / "logs" / "traces" / "vision" / "calibration.json"
    for path in (source_image, numbering_report, overlay_path, trace_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    source_image.write_bytes(b"capture")
    numbering_report.write_text('{"status":"passed"}', encoding="utf-8")
    overlay_path.write_bytes(b"overlay")
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {
                    "image_path": str(source_image),
                    "metadata": {
                        "two_stage_report_path": str(numbering_report),
                        "learning_interface_flow": True,
                        "no_live_click_authorization": True,
                    },
                },
                "result": {
                    "image_path": str(source_image),
                    "learn_all_targets": {
                        "overlay_path": str(overlay_path),
                        "vista_coordinate_validation": {
                            "validated_count": 3,
                            "failed_count": 0,
                            "batch": {
                                "completed_count": 3,
                                "remaining_count": 0,
                                "resumable": False,
                            },
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class _WorkerRegistry:
        def __init__(self) -> None:
            self.started: list[dict] = []

        def read_adopted_result(self, **kwargs):
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-calibration",
                    "task_kind": "panel_learning_calibration_sequence",
                    "result_sha256": "c" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "result": {
                            "image_path": str(source_image),
                            "learn_all_targets": {
                                "overlay_path": str(overlay_path),
                                "vista_coordinate_validation": {
                                    "status": "completed",
                                    "validated_count": 3,
                                    "failed_count": 0,
                                    "batch": {
                                        "completed_count": 3,
                                        "remaining_count": 0,
                                        "resumable": False,
                                    },
                                },
                            },
                            "calibration_sequence": {
                                "contract_version": (
                                    "learning_calibration_sequence_result_v1"
                                ),
                                "status": "completed",
                                "remaining_count": 0,
                                "artifact_inputs": {
                                    "trace_path": str(trace_path),
                                    "source_image_path": str(source_image),
                                    "numbering_report_path": str(numbering_report),
                                    "overlay_path": str(overlay_path),
                                },
                            },
                        }
                    },
                },
            }

        def start(self, **kwargs):
            self.started.append(kwargs)
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-review-auto",
                "run_id": kwargs["run_id"],
                "stage": kwargs["stage"],
                "operation_id": kwargs["operation_id"],
                "task_kind": kwargs["task_kind"],
                "status": "running",
            }

    registry = _WorkerRegistry()
    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", registry)
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": numbered_state["revision"],
            "stage": "precise_calibration",
            "reason": "calibration",
            "lease_seconds": 600,
        },
    ).json()["data"]

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "precise_calibration",
            "operation_id": started["operation_id"],
            "worker_id": "worker-calibration",
        },
    ).json()

    assert continued["success"] is True
    assert continued["data"]["stage_finished"] is True
    assert continued["data"]["outcome"] == "completed"
    workflow_state = continued["data"]["workflow_state"]
    stage = workflow_state["stages"]["precise_calibration"]
    assert stage["status"] == "completed"
    result_path = stage["evidence_refs"]["result_path"]
    assert result_path == (
        "artifacts/learning-runs/run-stage-operation/calibration_result.json"
    )
    assert (tmp_path / result_path).is_file()
    assert stage["evidence_refs"]["overlay_path"] == (
        "artifacts/review-overlays/calibrated.png"
    )
    assert stage["evidence_refs"]["worker_continuation"]["worker_id"] == (
        "worker-calibration"
    )
    next_operation = continued["data"]["next_stage_operation"]
    assert next_operation["stage"] == "review_repair"
    assert next_operation["task_kind"] == "panel_learning_model_review_repair"
    assert workflow_state["current_stage"] == "review_repair"
    assert workflow_state["stages"]["review_repair"]["status"] == "running"
    next_worker = continued["data"]["next_stage_worker"]
    assert next_worker["worker_id"] == "worker-review-auto"
    assert registry.started == [
        {
            "run_id": "run-stage-operation",
            "stage": "review_repair",
            "operation_id": next_operation["operation_id"],
            "task_kind": "panel_learning_model_review_repair",
            "payload": {
                "two_stage_report_path": "artifacts/numbered-map-report.json",
                "screenshot_path": "artifacts/screenshots/capture.png",
                "composite_overlay_path": (
                    "artifacts/review-overlays/calibrated.png"
                ),
                "model_profile_id": "learn_mode_qwen3_vl_8b",
                "timeout_seconds": 240,
            },
            "reuse_active_identical": True,
        }
    ]


def test_continuation_fails_calibration_when_artifact_evidence_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    store, numbered_state = _store_at_completed_numbered_map()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    class _WorkerRegistry:
        def read_adopted_result(self, **kwargs):
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-calibration-missing",
                    "task_kind": "panel_learning_calibration_sequence",
                    "result_sha256": "d" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "result": {
                            "calibration_sequence": {
                                "contract_version": (
                                    "learning_calibration_sequence_result_v1"
                                ),
                                "status": "completed",
                                "remaining_count": 0,
                                "artifact_inputs": {
                                    "trace_path": "logs/missing-trace.json",
                                    "source_image_path": (
                                        "artifacts/screenshots/missing.png"
                                    ),
                                    "numbering_report_path": (
                                        "artifacts/missing-report.json"
                                    ),
                                    "overlay_path": (
                                        "artifacts/review-overlays/missing.png"
                                    ),
                                },
                            },
                        }
                    },
                },
            }

    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", _WorkerRegistry())
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": numbered_state["revision"],
            "stage": "precise_calibration",
            "reason": "calibration",
            "lease_seconds": 600,
        },
    ).json()["data"]
    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "precise_calibration",
            "operation_id": started["operation_id"],
            "worker_id": "worker-calibration-missing",
        },
    ).json()

    assert continued["success"] is True
    assert continued["data"]["outcome"] == "failed"
    assert "artifact persistence failed" in continued["data"]["reason"]
    assert continued["data"]["workflow_state"]["stages"][
        "precise_calibration"
    ]["status"] == "failed"


def test_continuation_starts_recognition_trial_after_observe(
    monkeypatch,
) -> None:
    store, bind_state = _store_at_completed_bind_capture()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)

    class _WorkerRegistry:
        def __init__(self) -> None:
            self.started_payloads = []

        def read_adopted_result(self, **kwargs):
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-observe",
                    "task_kind": "vision_observe_screen",
                    "result_sha256": "c" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "result": {
                            "app_name": "example_app",
                            "state_guess": "home",
                            "image_path": "artifacts/screen.png",
                            "screen_size": {"width": 1280, "height": 720},
                            "screen_summary": "Example home screen",
                            "interface_classification": {
                                "category": "feed_workspace",
                                "confidence": 0.97,
                                "reason": "Visible repeated news cards",
                                "structure_signals": {
                                    "feed_items": True,
                                    "news_items": True,
                                },
                            },
                            "screen_map": {
                                "candidates": [
                                    {
                                        "candidate_id": "region-1",
                                        "label": "Search",
                                        "bbox": {"x": 10, "y": 20, "w": 200, "h": 40},
                                    }
                                ]
                            },
                            "trace_path": "logs/observe.json",
                        }
                    },
                },
            }

        def start(self, **kwargs):
            self.started_payloads.append(kwargs)
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-trial",
                "run_id": kwargs["run_id"],
                "stage": kwargs["stage"],
                "operation_id": kwargs["operation_id"],
                "task_kind": kwargs["task_kind"],
                "status": "running",
                "backend_compute_owner": "backend_process_worker",
            }

    registry = _WorkerRegistry()
    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", registry)
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": bind_state["revision"],
            "stage": "screen_understanding",
            "reason": "observe",
            "lease_seconds": 600,
        },
    ).json()["data"]
    running_revision = started["workflow_state"]["revision"]

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": running_revision,
            "stage": "screen_understanding",
            "operation_id": started["operation_id"],
            "worker_id": "worker-observe",
        },
    ).json()

    assert continued["success"] is True
    assert continued["data"]["stage_finished"] is False
    assert continued["data"]["continuation_status"] == "next_worker_started"
    assert continued["data"]["workflow_state"]["revision"] == running_revision
    assert continued["data"]["workflow_state"]["stages"]["screen_understanding"][
        "status"
    ] == "running"
    assert continued["data"]["next_worker"]["worker_id"] == "worker-trial"
    assert continued["data"]["next_worker"]["task_kind"] == (
        "panel_learning_recognition_trial"
    )
    assert len(registry.started_payloads) == 1
    next_payload = registry.started_payloads[0]
    assert next_payload["stage"] == "screen_understanding"
    assert next_payload["task_kind"] == "panel_learning_recognition_trial"
    assert next_payload["payload"]["app_name"] == "example_app"
    assert next_payload["payload"]["state_hint"] == "home"
    assert next_payload["payload"]["observation_evidence"]["current_image_path"] == (
        "artifacts/screen.png"
    )
    assert next_payload["payload"]["observation_evidence"]["screen_map"][
        "candidates"
    ][0]["candidate_id"] == "region-1"
    assert next_payload["payload"]["observation_evidence"][
        "interface_classification"
    ] == {
        "category": "feed_workspace",
        "confidence": 0.97,
        "reason": "Visible repeated news cards",
        "structure_signals": {
            "feed_items": True,
            "news_items": True,
        },
    }

    repeated = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": running_revision,
            "stage": "screen_understanding",
            "operation_id": started["operation_id"],
            "worker_id": "worker-observe",
        },
    ).json()
    assert repeated["success"] is True
    assert repeated["data"]["next_worker"]["worker_id"] == "worker-trial"
    assert len(registry.started_payloads) == 2


def test_continuation_forwards_only_a_persisted_verified_hybrid_capture_ref(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from tests.test_learn_hybrid_capture import _bundle

    store, bind_state = _store_at_completed_bind_capture()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    running_revision = 0

    class _WorkerRegistry:
        def __init__(self) -> None:
            self.started_payloads = []

        def read_adopted_result(self, **kwargs):
            bundle = _bundle(
                tmp_path,
                run_id="run-stage-operation",
                revision=running_revision,
            )
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-observe-hybrid",
                    "task_kind": "vision_observe_screen",
                    "result_sha256": "d" * 64,
                },
                "response": {
                    "success": True,
                    "data": {"result": {
                        "image_path": "artifacts/screenshots/capture.png",
                        "hybrid_capture_bundle_ref": bundle["bundle_ref"],
                        "screen_size": {"width": 8, "height": 6},
                    }},
                },
            }

        def start(self, **kwargs):
            self.started_payloads.append(kwargs)
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-trial-hybrid",
                "run_id": kwargs["run_id"],
                "stage": kwargs["stage"],
                "operation_id": kwargs["operation_id"],
                "task_kind": kwargs["task_kind"],
                "status": "running",
                "backend_compute_owner": "backend_process_worker",
            }

    registry = _WorkerRegistry()
    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", registry)
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": bind_state["revision"],
            "stage": "screen_understanding",
            "reason": "observe hybrid",
            "lease_seconds": 600,
        },
    ).json()["data"]
    running_revision = started["workflow_state"]["revision"]
    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": running_revision,
            "stage": "screen_understanding",
            "operation_id": started["operation_id"],
            "worker_id": "worker-observe-hybrid",
        },
    ).json()

    assert continued["success"] is True
    evidence = registry.started_payloads[0]["payload"]["observation_evidence"]
    assert evidence["hybrid_capture_bundle_ref"]["id"].startswith("hybrid-capture/")
    assert "current_image_path" not in evidence
    assert "_hybrid_capture_bundle_verified" not in continued["data"]["response"]["data"]["result"]


@pytest.mark.parametrize("ref_kind", ["missing", "cross_run", "stale_revision"])
def test_continuation_rejects_unverified_hybrid_ref_before_starting_next_worker(
    monkeypatch,
    tmp_path: Path,
    ref_kind: str,
) -> None:
    from tests.test_learn_hybrid_capture import _bundle

    store, bind_state = _store_at_completed_bind_capture()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    running_revision = 0

    class _WorkerRegistry:
        started = False

        def read_adopted_result(self, **kwargs):
            if ref_kind == "missing":
                bundle_ref = {
                    "id": "hybrid-capture/fabricated",
                    "content_sha256": "a" * 64,
                }
            else:
                bundle = _bundle(
                    tmp_path,
                    run_id=("run-other" if ref_kind == "cross_run" else "run-stage-operation"),
                    revision=(running_revision - 1 if ref_kind == "stale_revision" else running_revision),
                )
                bundle_ref = bundle["bundle_ref"]
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-observe-forged",
                    "task_kind": "vision_observe_screen",
                    "result_sha256": "e" * 64,
                },
                "response": {
                    "success": True,
                    "data": {"result": {
                        "image_path": "artifacts/screenshots/legacy.png",
                        "hybrid_capture_bundle_ref": bundle_ref,
                    }},
                },
            }

        def start(self, **kwargs):
            self.started = True
            raise AssertionError("unverified hybrid ref reached next worker")

    registry = _WorkerRegistry()
    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", registry)
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": bind_state["revision"],
            "stage": "screen_understanding",
            "reason": "observe forged",
            "lease_seconds": 600,
        },
    ).json()["data"]
    running_revision = started["workflow_state"]["revision"]
    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "screen_understanding",
            "operation_id": started["operation_id"],
            "worker_id": "worker-observe-forged",
        },
    ).json()

    assert continued["success"] is False
    assert continued["error"]["code"] == "learning_stage_worker_result_continuation_invalid"
    assert "hybrid capture handoff verification failed" in continued["error"]["details"]
    assert registry.started is False


def test_continuation_finishes_screen_understanding_from_trial(
    monkeypatch,
    tmp_path: Path,
) -> None:
    store, bind_state = _store_at_completed_bind_capture()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    trial_path = tmp_path / "artifacts" / "screen-understanding-trial.json"
    trial_path.parent.mkdir(parents=True)
    trial_path.write_text(
        json.dumps(
            {
                "artifact_type": "learn_recognition_trial",
                "app_name": "notepad",
                "state_hint": "editor",
                "observe_bundle": {
                    "image_path": "artifacts/screenshots/notepad.png",
                    "trace_path": "logs/traces/vision/notepad-observe.json",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class _WorkerRegistry:
        def __init__(self) -> None:
            self.started: list[dict] = []

        def read_adopted_result(self, **kwargs):
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-trial",
                    "task_kind": "panel_learning_recognition_trial",
                    "result_sha256": "e" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "trial_path": "artifacts/screen-understanding-trial.json",
                        "summary": {
                            "screen_inventory_count": 2,
                            "draft_section_counts": {
                                "regions": 2,
                                "action_templates": 0,
                            },
                        },
                    },
                },
            }

        def start(self, **kwargs):
            self.started.append(kwargs)
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-numbered-auto",
                "run_id": kwargs["run_id"],
                "stage": kwargs["stage"],
                "operation_id": kwargs["operation_id"],
                "task_kind": kwargs["task_kind"],
                "status": "running",
            }

    registry = _WorkerRegistry()
    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", registry)
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": bind_state["revision"],
            "stage": "screen_understanding",
            "reason": "observe",
            "lease_seconds": 600,
        },
    ).json()["data"]

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "screen_understanding",
            "operation_id": started["operation_id"],
            "worker_id": "worker-trial",
        },
    ).json()

    assert continued["success"] is True
    assert continued["data"]["stage_finished"] is True
    assert continued["data"]["outcome"] == "completed"
    assert continued["data"]["workflow_state"]["stages"]["screen_understanding"][
        "status"
    ] == "completed"
    evidence = continued["data"]["workflow_state"]["stages"][
        "screen_understanding"
    ]["evidence_refs"]
    assert evidence["trial_path"] == "artifacts/screen-understanding-trial.json"
    next_operation = continued["data"]["next_stage_operation"]
    assert next_operation["stage"] == "numbered_map"
    assert next_operation["task_kind"] == "panel_learning_two_stage_understanding"
    assert continued["data"]["workflow_state"]["current_stage"] == "numbered_map"
    assert continued["data"]["workflow_state"]["stages"]["numbered_map"]["status"] == (
        "running"
    )
    next_worker = continued["data"]["next_stage_worker"]
    assert next_worker["worker_id"] == "worker-numbered-auto"
    assert registry.started == [
        {
            "run_id": "run-stage-operation",
            "stage": "numbered_map",
            "operation_id": next_operation["operation_id"],
            "task_kind": "panel_learning_two_stage_understanding",
            "payload": {
                "app_name": "notepad",
                "state_hint": "editor",
                "trace_path": "artifacts/screen-understanding-trial.json",
                "source_image_path": "artifacts/screenshots/notepad.png",
                "require_stage1_gate": True,
                "stage2_region_strategy": "partitioned",
            },
            "reuse_active_identical": True,
        }
    ]


def test_continuation_safe_stops_screen_understanding_without_trial_evidence(
    monkeypatch,
) -> None:
    store, bind_state = _store_at_completed_bind_capture()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)

    class _WorkerRegistry:
        def read_adopted_result(self, **kwargs):
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-trial-empty",
                    "task_kind": "panel_learning_recognition_trial",
                    "result_sha256": "f" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "trial_path": "",
                        "summary": {
                            "screen_inventory_count": 0,
                            "draft_section_counts": {
                                "regions": 0,
                                "action_templates": 0,
                            },
                        },
                    },
                },
            }

    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", _WorkerRegistry())
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": bind_state["revision"],
            "stage": "screen_understanding",
            "reason": "observe",
            "lease_seconds": 600,
        },
    ).json()["data"]

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "screen_understanding",
            "operation_id": started["operation_id"],
            "worker_id": "worker-trial-empty",
        },
    ).json()

    assert continued["success"] is True
    assert continued["data"]["stage_finished"] is True
    assert continued["data"]["outcome"] == "safe_stopped"
    assert continued["data"]["workflow_state"]["terminal"] is True


def test_continuation_fails_screen_understanding_when_observe_response_failed(
    monkeypatch,
) -> None:
    store, bind_state = _store_at_completed_bind_capture()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)

    class _WorkerRegistry:
        def read_adopted_result(self, **kwargs):
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-observe-failed",
                    "task_kind": "vision_observe_screen",
                    "result_sha256": "1" * 64,
                },
                "response": {
                    "success": False,
                    "message": "Screen observation failed",
                    "error": {
                        "code": "observe_screen_failed",
                        "details": "model protocol error",
                    },
                },
            }

    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", _WorkerRegistry())
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": bind_state["revision"],
            "stage": "screen_understanding",
            "reason": "observe",
            "lease_seconds": 600,
        },
    ).json()["data"]

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "screen_understanding",
            "operation_id": started["operation_id"],
            "worker_id": "worker-observe-failed",
        },
    ).json()

    assert continued["success"] is True
    assert continued["data"]["stage_finished"] is True
    assert continued["data"]["outcome"] == "failed"
    assert "Screen observation failed" in continued["data"]["reason"]
    assert continued["data"]["workflow_state"]["stages"]["screen_understanding"][
        "status"
    ] == "failed"


def test_continuation_finishes_fusion_from_trial_artifact(
    monkeypatch,
    tmp_path: Path,
) -> None:
    store, review_state = _store_at_completed_review()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    trial_path = tmp_path / "artifacts" / "fusion-trial.json"
    trial_path.parent.mkdir(parents=True)
    trial_path.write_text(
        '{"contract_version":"learning_model_trial_v1"}',
        encoding="utf-8",
    )

    class _WorkerRegistry:
        def read_adopted_result(self, **kwargs):
            assert kwargs["stage"] == "fusion"
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-fusion",
                    "task_kind": "panel_learning_recognition_trial",
                    "result_sha256": "9" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "trial_path": "artifacts/fusion-trial.json",
                        "summary": {
                            "screen_inventory_count": 0,
                            "draft_section_counts": {"regions": 0},
                        },
                    },
                },
            }

    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", _WorkerRegistry())
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": review_state["revision"],
            "stage": "fusion",
            "reason": "fusion",
            "lease_seconds": 600,
        },
    ).json()["data"]
    request = {
        "run_id": "run-stage-operation",
        "expected_revision": started["workflow_state"]["revision"],
        "stage": "fusion",
        "operation_id": started["operation_id"],
        "worker_id": "worker-fusion",
    }

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json=request,
    ).json()

    assert continued["success"] is True
    assert continued["data"]["stage_finished"] is True
    assert continued["data"]["outcome"] == "completed"
    workflow_state = continued["data"]["workflow_state"]
    assert workflow_state["stages"]["fusion"]["status"] == "completed"
    evidence = workflow_state["stages"]["fusion"]["evidence_refs"]
    assert evidence["trial_path"] == "artifacts/fusion-trial.json"
    assert evidence["worker_continuation"]["worker_id"] == "worker-fusion"

    repeated = client.post(
        "/panel/continue_learning_stage_worker_result",
        json=request,
    ).json()
    assert repeated["success"] is True
    assert repeated["data"]["idempotent_replay"] is True
    assert repeated["data"]["workflow_state"]["revision"] == workflow_state["revision"]


def test_continuation_safe_stops_fusion_without_trial_artifact(
    monkeypatch,
) -> None:
    store, review_state = _store_at_completed_review()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)

    class _WorkerRegistry:
        def read_adopted_result(self, **kwargs):
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-fusion-empty",
                    "task_kind": "panel_learning_recognition_trial",
                    "result_sha256": "8" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "trial_path": "",
                        "summary": {},
                    },
                },
            }

    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", _WorkerRegistry())
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": review_state["revision"],
            "stage": "fusion",
            "reason": "fusion",
            "lease_seconds": 600,
        },
    ).json()["data"]

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "fusion",
            "operation_id": started["operation_id"],
            "worker_id": "worker-fusion-empty",
        },
    ).json()

    assert continued["success"] is True
    assert continued["data"]["stage_finished"] is True
    assert continued["data"]["outcome"] == "safe_stopped"
    assert continued["data"]["workflow_state"]["terminal"] is True
    assert continued["data"]["workflow_state"]["stages"]["fusion"]["status"] == (
        "safe_stopped"
    )


def test_continuation_finishes_review_repair_from_integrity_gate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    store, calibration_state = _store_at_completed_precise_calibration()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    report_path = tmp_path / "artifacts" / "review-report.json"
    overlay_path = tmp_path / "artifacts" / "review-overlay.png"
    source_image_path = tmp_path / "artifacts" / "screenshots" / "qq.png"
    report_path.parent.mkdir(parents=True)
    source_image_path.parent.mkdir(parents=True)
    source_image_path.write_bytes(b"screenshot")
    report_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "app_name": "qq",
                "state_hint": "chat",
                "source_image_path": "artifacts/screenshots/qq.png",
                "observe_bundle": {
                    "screen_size": {"width": 1280, "height": 960},
                    "screen_reading": {"screen_summary": "QQ chat window"},
                    "screen_map": {"contract_version": "screen_map_v1"},
                },
                "fusion": {
                    "compiled_overlay_path": "artifacts/review-overlay.png",
                    "fused_review_boxes": [
                        {
                            "candidate_id": "message-input",
                            "label": "message input",
                            "bbox": {"x": 500, "y": 800, "width": 400, "height": 80},
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overlay_path.write_bytes(b"overlay")

    class _WorkerRegistry:
        def __init__(self) -> None:
            self.started: list[dict] = []

        def read_adopted_result(self, **kwargs):
            return {
                "receipt": {
                    "contract_version": "learning_stage_worker_result_adoption_v1",
                    "worker_id": "worker-review",
                    "task_kind": "panel_learning_model_review_repair",
                    "result_sha256": "d" * 64,
                },
                "response": {
                    "success": True,
                    "data": {
                        "result": {
                            "calibration_permission": True,
                            "integrity_gate": {"passed": True},
                            "final_stage2_report_path": (
                                "artifacts/review-report.json"
                            ),
                            "final_repaired_overlay_path": (
                                "artifacts/review-overlay.png"
                            ),
                            "final_numbering_revision": "revision-1",
                        }
                    },
                },
            }

        def start(self, **kwargs):
            self.started.append(kwargs)
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-fusion-auto",
                "run_id": kwargs["run_id"],
                "stage": kwargs["stage"],
                "operation_id": kwargs["operation_id"],
                "task_kind": kwargs["task_kind"],
                "status": "running",
            }

    registry = _WorkerRegistry()
    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", registry)
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": calibration_state["revision"],
            "stage": "review_repair",
            "reason": "review",
            "lease_seconds": 600,
        },
    ).json()["data"]

    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "review_repair",
            "operation_id": started["operation_id"],
            "worker_id": "worker-review",
        },
    ).json()

    assert continued["success"] is True, continued
    assert continued["data"]["stage_finished"] is True
    assert continued["data"]["outcome"] == "completed"
    assert continued["data"]["workflow_state"]["stages"]["review_repair"][
        "status"
    ] == "completed"
    next_operation = continued["data"]["next_stage_operation"]
    assert next_operation["stage"] == "fusion"
    assert next_operation["task_kind"] == "panel_learning_recognition_trial"
    assert continued["data"]["workflow_state"]["current_stage"] == "fusion"
    assert continued["data"]["workflow_state"]["stages"]["fusion"]["status"] == (
        "running"
    )
    next_worker = continued["data"]["next_stage_worker"]
    assert next_worker["worker_id"] == "worker-fusion-auto"
    fusion_start = registry.started[0]
    assert fusion_start["stage"] == "fusion"
    assert fusion_start["operation_id"] == next_operation["operation_id"]
    assert fusion_start["task_kind"] == "panel_learning_recognition_trial"
    assert fusion_start["reuse_active_identical"] is True
    fusion_payload = fusion_start["payload"]
    assert fusion_payload["app_name"] == "qq"
    assert fusion_payload["state_hint"] == "chat"
    assert fusion_payload["summary"] == "QQ chat window"
    assert fusion_payload["two_stage_report_path"] == "artifacts/review-report.json"
    evidence = fusion_payload["observation_evidence"]
    assert evidence["current_image_path"] == "artifacts/screenshots/qq.png"
    assert evidence["coordinate_overlay_path"] == "artifacts/review-overlay.png"
    assert evidence["review_boxes"][0]["candidate_id"] == "message-input"
    assert evidence["no_click_authorization"] is True
    assert evidence["execute_binding_enabled"] is False


def test_stage_worker_request_accepts_managed_observe_task() -> None:
    request = panel_api.PanelStartLearningStageWorkerRequest.model_validate(
        {
            "run_id": "run-observe",
            "expected_revision": 1,
            "stage": "screen_understanding",
            "operation_id": "operation-observe",
            "task_kind": "vision_observe_screen",
            "payload": {"capture_live": False, "image_path": "screen.png"},
        }
    )

    assert request.task_kind == "vision_observe_screen"


def test_stage_operation_cancel_api_records_worker_termination(
    monkeypatch,
) -> None:
    store, review_state = _store_at_completed_review()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)

    class _WorkerRegistry:
        def cancel_by_operation(self, **kwargs):
            assert kwargs["stage"] == "fusion"
            return {
                "contract_version": "learning_stage_worker_v1",
                "worker_id": "worker-1",
                "status": "cancelled",
                "backend_compute_termination": "terminated",
                "model_service_compute_termination": "terminated",
                "model_request_id": "learn-worker-1",
                "model_request_cancellation": {
                    "contract_version": "model_request_cancellation_v1",
                    "status": "terminated",
                },
            }

    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", _WorkerRegistry())
    client = TestClient(app)
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": review_state["revision"],
            "stage": "fusion",
            "reason": "panel fusion",
            "lease_seconds": 600,
        },
    ).json()["data"]

    cancelled = client.post(
        "/panel/cancel_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["workflow_state"]["revision"],
            "stage": "fusion",
            "operation_id": started["operation_id"],
            "reason": "user requested cancellation",
        },
    ).json()

    assert cancelled["success"] is True
    assert cancelled["data"]["backend_compute_termination"] == "terminated"
    assert cancelled["data"]["model_service_compute_termination"] == "terminated"
    cancellation = cancelled["data"]["workflow_state"]["stages"]["fusion"][
        "evidence_refs"
    ]["stage_execution"]["cancellation"]
    assert cancellation["backend_compute_termination"] == "terminated"
    assert cancellation["model_service_compute_termination"] == "terminated"
    assert cancellation["model_request_id"] == "learn-worker-1"
    assert cancellation["worker_id"] == "worker-1"


def test_precise_calibration_api_requires_managed_stage_operation(
    monkeypatch,
) -> None:
    store, numbered_state = _store_at_completed_numbered_map()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    client = TestClient(app)

    direct = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": numbered_state["revision"],
            "stage": "precise_calibration",
            "outcome": "running",
        },
    ).json()
    assert direct["success"] is False
    assert direct["error"]["code"] == "learning_workflow_stage_operation_required"

    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": numbered_state["revision"],
            "stage": "precise_calibration",
            "reason": "panel precise calibration",
            "lease_seconds": 600,
        },
    ).json()
    assert started["success"] is True
    operation_id = started["data"]["operation_id"]

    finished = client.post(
        "/panel/finish_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["data"]["workflow_state"]["revision"],
            "stage": "precise_calibration",
            "operation_id": operation_id,
            "outcome": "failed",
            "reason": "locator model unavailable",
        },
    ).json()

    assert finished["success"] is True
    workflow_state = finished["data"]["workflow_state"]
    assert workflow_state["stages"]["precise_calibration"]["status"] == "failed"
    assert workflow_state["stages"]["review_repair"]["status"] == "pending"


def test_review_repair_api_requires_managed_stage_operation(
    monkeypatch,
) -> None:
    store, calibration_state = _store_at_completed_precise_calibration()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    client = TestClient(app)

    direct = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": calibration_state["revision"],
            "stage": "review_repair",
            "outcome": "running",
        },
    ).json()
    assert direct["success"] is False
    assert direct["error"]["code"] == "learning_workflow_stage_operation_required"

    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": calibration_state["revision"],
            "stage": "review_repair",
            "reason": "panel model review and repair",
            "lease_seconds": 600,
        },
    ).json()
    assert started["success"] is True
    operation_id = started["data"]["operation_id"]

    finished = client.post(
        "/panel/finish_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["data"]["workflow_state"]["revision"],
            "stage": "review_repair",
            "operation_id": operation_id,
            "outcome": "failed",
            "reason": "review model unavailable",
        },
    ).json()

    assert finished["success"] is True
    workflow_state = finished["data"]["workflow_state"]
    assert workflow_state["stages"]["review_repair"]["status"] == "failed"
    assert workflow_state["stages"]["fusion"]["status"] == "pending"


@pytest.mark.parametrize(
    ("stage", "store_factory", "next_stage"),
    [
        (
            "screen_understanding",
            _store_at_completed_bind_capture,
            "numbered_map",
        ),
        (
            "numbered_map",
            _store_at_completed_screen_understanding,
            "precise_calibration",
        ),
    ],
)
def test_inference_stage_api_requires_managed_stage_operation(
    monkeypatch,
    stage: str,
    store_factory,
    next_stage: str,
) -> None:
    store, previous_state = store_factory()
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    client = TestClient(app)

    direct = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": previous_state["revision"],
            "stage": stage,
            "outcome": "running",
        },
    ).json()
    assert direct["success"] is False
    assert direct["error"]["code"] == "learning_workflow_stage_operation_required"

    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": previous_state["revision"],
            "stage": stage,
            "reason": f"panel {stage}",
            "lease_seconds": 600,
        },
    ).json()
    assert started["success"] is True

    finished = client.post(
        "/panel/finish_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": started["data"]["workflow_state"]["revision"],
            "stage": stage,
            "operation_id": started["data"]["operation_id"],
            "outcome": "failed",
            "reason": f"{stage} model unavailable",
        },
    ).json()

    assert finished["success"] is True
    workflow_state = finished["data"]["workflow_state"]
    assert workflow_state["stages"][stage]["status"] == "failed"
    assert workflow_state["stages"][next_stage]["status"] == "pending"


def test_panel_fusion_uses_managed_stage_operation() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    start = panel_js.index("async function runLearningInterfaceFlow")
    end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", start)
    body = panel_js[start:end]

    assert "/panel/start_learning_workflow_stage_operation" in panel_js
    assert "/panel/finish_learning_workflow_stage_operation" in panel_js
    assert "/panel/recover_learning_workflow_stage_operation" in panel_js
    assert 'transitionLearningWorkflowState(\n      "fusion"' not in body
    assert "backendContinuationStageWorker" in panel_js
    assert "continuationData?.next_stage_operation" in panel_js
    assert "continuationData?.next_stage_worker" in panel_js
    assert "runLearningDraftTrial(" not in body
    assert "nextLearningStageOperation(" not in body


def test_panel_uses_backend_issued_operations_after_screen_understanding() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    start = panel_js.index("async function runLearningInterfaceFlow")
    end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", start)
    body = panel_js[start:end]

    assert body.count("await startLearningWorkflowStageOperation(") == 1
    assert "followContinuationChain: true" in body
    assert "nextLearningStageOperation(" not in body
    assert "backendContinuationStageWorker" in panel_js
    assert "activeLearningStageOperation = nextStage.operation" in panel_js


def test_panel_precise_calibration_uses_managed_stage_operation() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    start = panel_js.index("async function runLearningInterfaceFlow")
    end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", start)
    body = panel_js[start:end]
    assert 'transitionLearningWorkflowState(\n      "precise_calibration"' not in body
    assert "runLearningDeepCalibration(" not in body
    assert 'taskKind === "panel_learning_calibration_sequence"' in panel_js
    assert "lastLearningDeepCalibrationResponse = response" in panel_js


def test_panel_review_repair_uses_managed_stage_operation() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    start = panel_js.index("async function runLearningInterfaceFlow")
    end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", start)
    body = panel_js[start:end]
    assert 'transitionLearningWorkflowState(\n      "review_repair"' not in body
    assert "runLearningModelReviewRepair(" not in body
    assert 'taskKind === "panel_learning_model_review_repair"' in panel_js
    assert "lastLearningReviewRepairResponse = response" in panel_js


@pytest.mark.parametrize(
    ("stage", "operation_name", "next_operation_name"),
    [
        (
            "screen_understanding",
            "screenUnderstandingOperation",
            "numberedMapOperation",
        ),
    ],
)
def test_panel_inference_stage_uses_managed_stage_operation(
    stage: str,
    operation_name: str,
    next_operation_name: str,
) -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    start = panel_js.index("async function runLearningInterfaceFlow")
    end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", start)
    body = panel_js[start:end]
    operation_start = body.index(
        f"const {operation_name} = await startLearningWorkflowStageOperation"
    )
    operation_body = body[operation_start:]

    assert f'transitionLearningWorkflowState(\n      "{stage}"' not in operation_body
    assert f"{operation_name}.operation_id" in operation_body
    assert f"activeLearningStageOperation = {operation_name}" in operation_body
    assert 'screenUnderstandingOperation,\n        "completed"' not in operation_body
    assert 'screenUnderstandingOperation,\n        "safe_stopped"' not in operation_body
    assert "nextLearningStageOperation(" not in operation_body
    assert "followContinuationChain: true" in operation_body
    assert "learningStageContinuationFinished(trialResponse)" in operation_body


def test_panel_numbered_map_uses_backend_continuation() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    start = panel_js.index("async function runLearningInterfaceFlow")
    end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", start)
    body = panel_js[start:end]
    assert "runLearningTwoStageUnderstanding(" not in body
    assert "continuationData?.next_stage_worker" in panel_js
    assert "backendContinuationStageWorker(continuationData)" in panel_js
    assert "/panel/continue_learning_stage_worker_result" in panel_js


def test_panel_managed_model_tasks_run_with_heartbeat() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    start = panel_js.index("async function runLearningInterfaceFlow")
    end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", start)
    body = panel_js[start:end]

    assert "/panel/heartbeat_learning_workflow_stage_operation" in panel_js
    assert "async function runLearningStageTaskWithHeartbeat" in panel_js
    assert body.count("runLearningStageTaskWithHeartbeat(") == 1
    assert (
        "runLearningStageTaskWithHeartbeat(\n"
        "      screenUnderstandingOperation"
    ) in body
    assert "taskContext.operation" in panel_js
    assert "activeLearningStageTaskContext.operation = nextStage.operation" in panel_js


def test_panel_suspends_heartbeat_while_backend_continuation_changes_stage() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    heartbeat_start = panel_js.index("async function runLearningStageTaskWithHeartbeat")
    worker_start = panel_js.index("async function pollManagedLearningStageWorker")
    heartbeat_body = panel_js[heartbeat_start:worker_start]
    worker_end = panel_js.index("function learningStageContinuation", worker_start)
    worker_body = panel_js[worker_start:worker_end]

    assert "heartbeatSuspended: false" in heartbeat_body
    assert "taskContext.heartbeatSuspended" in heartbeat_body
    suspend_at = worker_body.index("heartbeatContext.heartbeatSuspended = true")
    continue_at = worker_body.index('"/panel/continue_learning_stage_worker_result"')
    adopt_next_at = worker_body.index(
        "activeLearningStageTaskContext.operation = nextStage.operation"
    )
    resume_at = worker_body.index(
        "activeLearningStageTaskContext.heartbeatSuspended = false",
        adopt_next_at,
    )
    assert suspend_at < continue_at < adopt_next_at < resume_at


def test_panel_exposes_authoritative_managed_stage_cancellation() -> None:
    panel_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")

    assert 'id="learningInterfaceCancelBtn"' in panel_html
    assert 'data-i18n="learning_interface_cancel"' in panel_html
    assert "/panel/cancel_learning_workflow_stage_operation" in panel_js
    assert "async function cancelActiveLearningInterfaceFlow" in panel_js
    assert 'on("learningInterfaceCancelBtn", "click", cancelActiveLearningInterfaceFlow)' in panel_js
    assert "signal: taskController.signal" in panel_js
    assert "operation," in panel_js
    assert "options.signal" in panel_js
    assert "if (options.signal?.aborted)" in panel_js
    assert "signal: options.signal" in panel_js


def test_panel_runs_managed_stage_requests_through_backend_worker() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert "/panel/start_learning_stage_worker" in panel_js
    assert "/panel/learning_stage_worker/" in panel_js
    assert "vision_observe_screen" in panel_js
    assert "panel_learning_recognition_trial" in panel_js
    assert "panel_learning_two_stage_understanding" in panel_js
    assert "panel_learning_model_review_repair" in panel_js
    assert "panel_learning_calibration_sequence" in panel_js
    assert '"vision_locate_target"' not in panel_js
    assert "backend_process_worker" in panel_js
    assert "backend_compute_termination" in panel_js
    assert "activeLearningStageTaskContext?.cancelled === true" in panel_js


def test_panel_production_flow_follows_backend_started_stage_workers() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("async function runLearningInterfaceFlow")
    end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", start)
    body = panel_js[start:end]

    assert "followContinuationChain: true" in body
    assert "next_stage_worker" in panel_js
    assert "runLearningTwoStageUnderstanding(" not in body
    assert "runLearningDeepCalibration(" not in body
    assert "runLearningModelReviewRepair(" not in body
    assert "runLearningDraftTrial(" not in body
    assert "nextLearningStageOperation(" not in body


def test_hybrid_managed_worker_order_reaches_calibration_without_pre_omni_qwen(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.learn.workflow_continuation import interpret_learning_stage_worker_result
    from app.learn.workflow_service import build_learning_pipeline_initial_worker_request
    from app.learn import workflow_worker
    from tests.test_learn_hybrid_vista_refinement import _cleanup_receipt
    from app.learn.recognition.uei.canonical import seal_immutable

    bundle_ref = {"id": "hybrid-capture/test", "content_sha256": "1" * 64}
    capture_bundle = {
        "contract_version": "hybrid_capture_bundle_v1",
        "bundle_id": bundle_ref["id"],
        "content_sha256": bundle_ref["content_sha256"],
    }
    config = {"contract_version": "hybrid_config_v1", "config_sha256": "2" * 64}
    omni_inventory = seal_immutable({
        "contract_version": "hybrid_omni_inventory_v1",
        "candidates": [{"candidate_id": "candidate/one"}],
    })
    qwen_bindings = seal_immutable({
        "contract_version": "hybrid_qwen_bindings_v1",
    })
    fusion_result = {
        "contract_version": "hybrid_fusion_result_v1",
        "config_sha256": config["config_sha256"],
        "candidates": [
            {
                "candidate_id": "candidate/one",
                "state": "BOUND",
                "vista_eligible": True,
            }
        ],
    }
    monkeypatch.setattr(workflow_worker, "_ensure_learning_stage_model_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(workflow_worker, "validate_hybrid_qwen_task_payload", lambda payload: None)
    monkeypatch.setattr(workflow_worker, "run_hybrid_omni_task", lambda payload, **kwargs: {
        "contract_version": "hybrid_omni_discovery_result_v1",
        "outcome": "completed",
        "hybrid_capture_bundle_ref": bundle_ref,
        "inventory": omni_inventory,
        "cleanup_status": "clean",
        "provider_claim_status": "complete",
        "provider_receipt_ref": {"id": "receipt/omni", "content_sha256": "8" * 64},
    })
    monkeypatch.setattr(workflow_worker, "run_hybrid_qwen_task", lambda payload, **kwargs: {
        "qwen_bindings": qwen_bindings,
        "qwen_cleanup_receipt": _cleanup_receipt(),
    })
    monkeypatch.setattr(workflow_worker, "run_hybrid_fusion_task", lambda payload, **kwargs: fusion_result)
    lineage = _hybrid_supervised_lineage(
        run_id="run-hybrid",
        workflow_revision=7,
        operation_id="operation-hybrid-chain",
    )

    def observed_inventory(provider: str, **kwargs) -> dict:
        from app.learn.hybrid.windows_process_scope import process_scope_name

        process_identity = {
            "pid": 5200 + len(provider),
            "create_time_ns": 100_000_000_000,
        }
        provider_identity = (
            {
                "provider_invocation_id": "invocation/controlled-omni-chain",
                "provider_receipt_ref": {
                    "id": "receipt/controlled-omni-chain",
                    "content_sha256": "b" * 64,
                },
                "process_identity": process_identity,
            }
            if provider == "omni"
            else {
                "lease_id": "controlled-qwen-chain-lease",
                "incarnation_id": "qwen-controlled-chain",
                "profile_id": "qwen-profile",
                "server_process_identity": process_identity,
            }
        )
        provider_identity["process_scope_name"] = process_scope_name(
            kwargs["lineage"], provider
        )
        return {
            "contract_version": "hybrid_provider_process_inventory_v2",
            "provider": provider,
            "observer_contract": f"hybrid_{provider}_cleanup_observer_v1",
            "release_status": "verified",
            "termination_reason": "completed",
            "lineage": kwargs["lineage"],
            "provider_lease_identity": provider_identity,
            "predecessor_sha256": kwargs["predecessor_sha256"],
            "provider_result_sha256": kwargs["provider_result_sha256"],
            "provider_processes_after": [],
            "helper_processes_after": [],
            "orphan_descendant_pids": [],
            "active_listeners_after": [],
            "lease_files_after": [],
            "source_cleanup_evidence": {"status": "verified"},
        }

    monkeypatch.setattr(
        workflow_worker,
        "_observe_hybrid_omni_cleanup",
        lambda result, **kwargs: observed_inventory("omni", **kwargs),
    )
    monkeypatch.setattr(
        "app.core.model_server.observe_hybrid_qwen_cleanup",
        lambda receipt, **kwargs: observed_inventory("qwen", **kwargs),
    )

    current = build_learning_pipeline_initial_worker_request(
        learning_pipeline_mode="hybrid_v1_1",
        payload={
            "run_id": "run-hybrid",
            "workflow_revision": 7,
            "hybrid_capture_bundle_ref": bundle_ref,
            "request_ref": {"id": "request/test", "content_sha256": "5" * 64},
            "registration_ref": {"id": "registration/test", "content_sha256": "6" * 64},
            "manifest_ref": {"id": "manifest/test", "content_sha256": "7" * 64},
            "capture_image_path": "artifacts/capture.png",
            "hybrid_config": config,
            "capture_bundle": capture_bundle,
        },
    )
    task_kinds: list[str] = []
    payload_hashes: list[str] = []
    for _ in range(3):
        task_kinds.append(current["task_kind"])
        from app.learn.hybrid.windows_process_scope import process_scope_name

        provider = {
            "panel_learning_hybrid_omni_discovery": "omni",
            "panel_learning_hybrid_qwen_binding": "qwen",
        }.get(current["task_kind"], "vista")
        current["payload"]["_hybrid_supervisor"] = {
            "contract_version": "hybrid_worker_supervisor_context_v1",
            "worker_id": "worker-hybrid-chain",
            "provider_lease_path": str(tmp_path / "vista-lease.json"),
            "lineage": lineage,
            "process_scope_name": process_scope_name(lineage, provider),
        }
        response = workflow_worker.execute_learning_stage_worker_task(
            current["task_kind"], current["payload"]
        )
        decision = interpret_learning_stage_worker_result(
            stage="screen_understanding",
            task_kind=current["task_kind"],
            response=response,
            learning_pipeline_mode="hybrid_v1_1",
        )
        assert decision["outcome"] is None
        current = decision["next_worker"]
        payload_hashes.append(current["payload_sha256"])
        assert current["payload"]["hybrid_capture_bundle_ref"] == bundle_ref
    task_kinds.append(current["task_kind"])

    assert task_kinds == [
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
        "panel_learning_calibration_sequence",
    ]
    assert task_kinds[0] != "vision_observe_screen"
    assert "panel_learning_model_review_repair" not in task_kinds
    assert len(set(payload_hashes)) == len(payload_hashes)


@pytest.mark.parametrize(
    "task_kind",
    [
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
    ],
)
def test_hybrid_stage_failure_is_explicit_safe_stop(task_kind: str) -> None:
    from app.learn.workflow_continuation import interpret_learning_stage_worker_result

    decision = interpret_learning_stage_worker_result(
        stage="screen_understanding",
        task_kind=task_kind,
        response={
            "contract_version": "learning_hybrid_managed_stage_result_v1",
            "learning_pipeline_mode": "hybrid_v1_1",
            "task_kind": task_kind,
            "outcome": "failed",
            "result": {"failure_reason": "controlled_failure"},
            "orchestration": {},
        },
        learning_pipeline_mode="hybrid_v1_1",
    )

    assert decision["stage_finished"] is True
    assert decision["outcome"] == "safe_stopped"
    assert decision["reason"].startswith("SAFE_STOP")


def test_hybrid_calibration_continues_only_to_managed_review_projection() -> None:
    from app.learn import workflow_worker
    from app.learn.workflow_service import (
        _interpret_hybrid_post_calibration_worker_result,
    )
    from app.learn.hybrid.vista_refinement import build_vista_requests, validate_vista_proposal
    from tests.test_learn_hybrid_vista_refinement import _authoritative_inputs

    fusion, bundle, inventory, bindings, receipt = _authoritative_inputs()
    request = build_vista_requests(fusion, bundle, omni_inventory=inventory,
        qwen_bindings=bindings, qwen_cleanup_receipt=receipt,
        expected_workflow_revision=bundle["workflow_revision"])[0]

    lineage = _hybrid_supervised_lineage(
        run_id="run-hybrid-review",
        workflow_revision=11,
        operation_id="operation-hybrid-review",
    )
    orchestration = {
        "run_id": "run-hybrid-review",
        "workflow_revision": 11,
        "hybrid_capture_bundle_ref": {
            "id": "hybrid-capture/review",
            "content_sha256": "1" * 64,
        },
        "fusion_result": {
            "contract_version": "hybrid_fusion_result_v1",
            "content_sha256": "2" * 64,
        },
        "capture_bundle": {
            "contract_version": "hybrid_capture_bundle_v1",
            "content_sha256": "3" * 64,
        },
    }
    bbox = request["candidate_bbox_ref"]["xyxy"]
    raw = {"status":"PROPOSED", "candidate_id":request["candidate_id"], "capture_id":request["capture_id"],
        "capture_sha256":request["capture_sha256"], "source_revision":request["source_revision"],
        "affine_transform_ref":deepcopy(request["affine_transform_ref"]), "point_coordinate_space":"capture_pixel_xyxy",
        "point":[(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2], "provenance":{"provider":"fake-vista"}}
    proposal = validate_vista_proposal(request=request, raw_result=raw)
    vista_result = {"candidate_id": request["candidate_id"], "hybrid_vista_request": deepcopy(request),
        "hybrid_vista_proposal": proposal}
    calibration_sequence = {
        "contract_version": "learning_calibration_sequence_result_v1",
        "status": "completed",
        "remaining_count": 0,
        "completed_count": 1,
        "hybrid_vista_requests": [request],
        "hybrid_vista_results": [vista_result],
        "qwen_cleanup_receipt": receipt,
    }
    vista_cleanup_receipt = _observed_hybrid_cleanup_receipt(
        "vista",
        lineage=lineage,
        predecessor=orchestration["fusion_result"],
        provider_result=calibration_sequence,
    )
    orchestration["vista_cleanup_receipt"] = vista_cleanup_receipt
    response = {
        "contract_version": "learning_hybrid_managed_stage_result_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "task_kind": "panel_learning_calibration_sequence",
        "outcome": "completed",
        "result": {
            "success": True,
            "data": {
                "result": {
                    "calibration_sequence": calibration_sequence
                }
            },
        },
        "orchestration": orchestration,
        "supervisor_lineage": lineage,
    }

    decision = _interpret_hybrid_post_calibration_worker_result(
        stage="screen_understanding",
        task_kind="panel_learning_calibration_sequence",
        response=response,
    )

    assert decision is not None
    assert decision["stage_finished"] is False
    assert decision["next_worker"]["task_kind"] == "panel_learning_hybrid_review_projection"
    assert "panel_learning_model_review_repair" not in str(decision)
    assert decision["next_worker"]["payload"]["qwen_cleanup_receipt"] == receipt
    assert decision["next_worker"]["payload"]["vista_cleanup_receipt"] == vista_cleanup_receipt

    review_payload = decision["next_worker"]["payload"]
    review_payload["_hybrid_supervisor"] = {
        "contract_version": "hybrid_worker_supervisor_context_v1",
        "worker_id": "worker-hybrid-review",
        "provider_lease_path": "unused-review-lease.json",
        "lineage": lineage,
    }
    review_response = workflow_worker.execute_learning_stage_worker_task(
        decision["next_worker"]["task_kind"], review_payload
    )
    review_decision = _interpret_hybrid_post_calibration_worker_result(
        stage="screen_understanding",
        task_kind="panel_learning_hybrid_review_projection",
        response=review_response,
    )

    assert review_decision is not None
    assert review_decision["stage_finished"] is True
    assert review_decision["outcome"] == "completed"
    projection = review_response["result"]
    assert projection["contract_version"] == "hybrid_review_projection_v1"
    assert projection["review_status"] == "REVIEW_REQUIRED"
    assert projection["automatic_acceptance"] is False
    assert projection["proposals"][0]["raw_provider_result"] == raw


def test_hybrid_persistence_driver_uses_all_managed_fake_provider_boundaries(
    tmp_path: Path,
) -> None:
    """捕获持久化证明绕过 managed Hybrid 顺序或绕过 Large Review Save。"""

    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        build_managed_hybrid_review_source,
    )

    result = build_managed_hybrid_review_source(tmp_path)

    assert result["provider_boundary_trace"] == [
        "omni",
        "qwen",
        "fusion",
        "vista",
        "review",
    ]
    assert result["large_review_save"]["status"] == "saved"
    saved_candidate = json.loads(
        Path(result["large_review_save"]["reviewed_candidate_path"]).read_text(
            encoding="utf-8"
        )
    )
    serialized = json.dumps(saved_candidate, ensure_ascii=False)
    assert '"hybrid_review_projection"' in serialized
    assert '"vista_proposal"' in serialized
    assert '"human_point_proposal"' in serialized
    assert saved_candidate["artifact_is_authorization"] is False
    assert saved_candidate["execute_binding_enabled"] is False


def test_public_hybrid_review_continuation_persists_authoritative_trial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """捕获公共 Hybrid 终态缺少服务端 trial_path 而无法完成阶段。"""

    from scripts.prove_portfolio_hybrid_v1_1_persistence import (
        _build_capture,
        _create_capture_image,
    )

    store, bind_state = _store_at_completed_bind_capture()
    config_path = tmp_path / "configs" / "learn_hybrid_v1_1.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(Path("configs/learn_hybrid_v1_1.json").read_bytes())
    monkeypatch.setattr(panel_api, "learning_workflow_run_store", store)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    client = TestClient(app)
    operation = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": bind_state["revision"],
            "stage": "screen_understanding",
            "reason": "public managed Hybrid review",
            "lease_seconds": 600,
            "learning_pipeline_mode": "hybrid_v1_1",
        },
    ).json()["data"]
    workflow_revision = operation["workflow_state"]["revision"]
    image_path = _create_capture_image(tmp_path)
    bundle = _build_capture(
        tmp_path,
        image_path=image_path,
        run_id="run-stage-operation",
        revision=workflow_revision,
    )
    lineage = _hybrid_supervised_lineage(
        run_id="run-stage-operation",
        workflow_revision=workflow_revision,
        operation_id=operation["operation_id"],
    )
    projection = {
        "contract_version": "hybrid_review_projection_v1",
        "outcome": "completed",
        "review_status": "REVIEW_REQUIRED",
        "automatic_acceptance": False,
        "completed_count": 1,
        "requested_candidate_ids": ["candidate/one"],
        "completed_candidate_ids": ["candidate/one"],
        "hybrid_capture_bundle_ref": deepcopy(bundle["bundle_ref"]),
        "proposals": [
            {
                "candidate_id": "candidate/one",
                "roi_ref": {
                    "capture_lineage_ref": deepcopy(
                        bundle["capture_lineage_ref"]
                    )
                },
            }
        ],
        "execute_binding_enabled": False,
        "no_live_click_authorization": True,
    }
    task8_projection = {
        "contract_version": "hybrid_review_projection_v2",
        "content_sha256": "e" * 64,
        "screen_facts": {
            "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"])
        },
    }
    monkeypatch.setattr(
        workflow_service,
        "_managed_hybrid_large_review_projection",
        lambda **_kwargs: deepcopy(task8_projection),
    )
    response = {
        "contract_version": "learning_hybrid_managed_stage_result_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "task_kind": "panel_learning_hybrid_review_projection",
        "outcome": "completed",
        "result": deepcopy(projection),
        "orchestration": {
            "run_id": "run-stage-operation",
            "workflow_revision": workflow_revision,
            "hybrid_capture_bundle_ref": deepcopy(bundle["bundle_ref"]),
            "capture_bundle": deepcopy(bundle),
            "capture_image_path": image_path.relative_to(tmp_path).as_posix(),
        },
        "supervisor_lineage": lineage,
        "lifecycle_evidence": {},
    }

    class _AdoptedRegistry:
        def read_adopted_result(self, **_kwargs):
            return {
                "receipt": {
                    "task_kind": "panel_learning_hybrid_review_projection",
                    "result_sha256": "d" * 64,
                },
                "response": deepcopy(response),
            }

    monkeypatch.setattr(panel_api, "learning_stage_worker_registry", _AdoptedRegistry())
    continued = client.post(
        "/panel/continue_learning_stage_worker_result",
        json={
            "run_id": "run-stage-operation",
            "expected_revision": workflow_revision,
            "stage": "screen_understanding",
            "operation_id": operation["operation_id"],
            "worker_id": "worker-public-hybrid-review",
        },
    ).json()

    assert continued["success"] is True
    evidence = continued["data"]["workflow_state"]["stages"][
        "screen_understanding"
    ]["evidence_refs"]
    trial_path = tmp_path / evidence["trial_path"]
    assert trial_path.is_file()
    trial = json.loads(trial_path.read_text(encoding="utf-8"))
    assert trial["hybrid_review_projection"] == task8_projection
    assert trial["managed_hybrid_review_projection"] == projection
    assert trial["capture_lineage_ref"] == bundle["capture_lineage_ref"]
    assert trial["managed_hybrid_lineage"] == {
        "run_id": "run-stage-operation",
        "workflow_revision": workflow_revision,
        "operation_id": operation["operation_id"],
        "worker_id": "worker-public-hybrid-review",
        "result_sha256": "d" * 64,
        "capture_lineage_ref": bundle["capture_lineage_ref"],
        "hybrid_capture_bundle_ref": bundle["bundle_ref"],
    }
    assert evidence["evidence_integrity"]["artifacts"]["trial_path"][
        "sha256"
    ] == hashlib.sha256(trial_path.read_bytes()).hexdigest()


def test_explicit_incumbent_mode_preserves_continuation_byte_for_byte() -> None:
    from app.learn.workflow_continuation import interpret_learning_stage_worker_result

    response = {
        "success": True,
        "data": {
            "trial_path": "artifacts/trial.json",
            "summary": {
                "screen_inventory_count": 1,
                "draft_section_counts": {"regions": 1},
            },
        },
    }
    implicit = interpret_learning_stage_worker_result(
        stage="screen_understanding",
        task_kind="panel_learning_recognition_trial",
        response=response,
    )
    explicit = interpret_learning_stage_worker_result(
        stage="screen_understanding",
        task_kind="panel_learning_recognition_trial",
        response=response,
        learning_pipeline_mode="incumbent",
    )

    assert json.dumps(explicit, sort_keys=True) == json.dumps(implicit, sort_keys=True)


def test_guarded_wrapper_surface_has_exact_single_composition_signatures() -> None:
    import inspect

    expected = {
        "start_guarded_learning_stage_worker",
        "status_guarded_learning_stage_worker",
        "adopt_guarded_learning_stage_worker_result",
        "continue_guarded_learning_stage_worker_result",
        "cancel_guarded_learning_workflow_stage_operation",
        "heartbeat_guarded_learning_workflow_stage_operation",
        "finish_guarded_learning_workflow_stage_operation",
        "recover_guarded_learning_workflow_stage_operation",
        "project_guarded_learning_workflow_runtime_attachment",
    }
    for name in expected:
        function = getattr(workflow_service, name)
        parameters = inspect.signature(function).parameters
        assert "composition" in parameters
        assert "store" not in parameters
        assert "worker_registry" not in parameters
        assert "project_root" not in parameters


def test_task5_binding_resolver_composition_is_exact_root_bound_and_fail_closed(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        compose_test_server_worker_window_binding_resolver,
        get_production_server_worker_window_binding_resolver,
        validate_server_worker_window_binding_resolver_binding,
    )

    resolver = compose_test_server_worker_window_binding_resolver(
        authority_root=tmp_path.resolve(),
    )
    with pytest.raises(TypeError):
        json.dumps(resolver)
    validate_server_worker_window_binding_resolver_binding(
        resolver,
        project_root=tmp_path.resolve(),
        composition_kind="test",
    )
    with pytest.raises(ValueError, match="Task 5 composition root"):
        validate_server_worker_window_binding_resolver_binding(
            compose_test_server_worker_window_binding_resolver(
                authority_root=(tmp_path / "other-root").resolve(),
            ),
            project_root=tmp_path.resolve(),
            composition_kind="test",
        )
    with pytest.raises(ValueError, match="production/test"):
        validate_server_worker_window_binding_resolver_binding(
            get_production_server_worker_window_binding_resolver(),
            project_root=tmp_path.resolve(),
            composition_kind="test",
        )

    composition = workflow_service.compose_test_learning_workflow_service(
        store=object(),
        worker_registry=object(),
        project_root=tmp_path,
        benchmark_supervision_root=None,
        provider_case_resolver=None,
        benchmark_v2_worker_binding_resolver=None,
    )
    assert composition.benchmark_v2_worker_binding_resolver is None
    with pytest.raises(ValueError, match="benchmark composition"):
        workflow_service.compose_test_learning_workflow_service(
            store=object(),
            worker_registry=object(),
            project_root=tmp_path,
            benchmark_supervision_root=None,
            provider_case_resolver=None,
            benchmark_v2_worker_binding_resolver=resolver,
        )


def test_guarded_start_status_adopt_preserve_order_values_and_compensation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    active_checks = 0

    class _Registry:
        def start(self, **kwargs):
            events.append("start")
            return {"worker_id": "worker-guarded", "payload": deepcopy(kwargs["payload"])}

        def status(self, **_kwargs):
            events.append("status")
            return {"worker_id": "worker-guarded", "status": "completed"}

        def adopt_result(self, **_kwargs):
            events.append("adopt")
            return {"status": "adopted", "receipt": {"result_sha256": "a" * 64}}

        def cancel_by_operation(self, **_kwargs):
            events.append("cancel")
            return {"status": "cancelled"}

    registry = _Registry()
    composition = workflow_service.LearningWorkflowServiceComposition(
        store=object(),
        worker_registry=registry,
        project_root=tmp_path,
        composition_kind="test",
        benchmark_supervision_root=None,
        provider_case_resolver=None,
    )

    def _active(**_kwargs):
        nonlocal active_checks
        active_checks += 1
        events.append("precheck" if active_checks == 1 else "postcheck")
        return {"operation_id": "operation-guarded"}

    monkeypatch.setattr(
        workflow_service,
        "require_active_learning_workflow_stage_operation",
        _active,
    )
    started = workflow_service.start_guarded_learning_stage_worker(
        composition=composition,
        run_id="run-guarded",
        expected_revision=3,
        stage="fusion",
        operation_id="operation-guarded",
        task_kind="panel_learning_recognition_trial",
        payload={"app_name": "fixture"},
    )
    assert started == {
        "worker_id": "worker-guarded",
        "payload": {"app_name": "fixture"},
    }
    assert events == ["precheck", "start", "postcheck"]

    events.clear()
    assert workflow_service.status_guarded_learning_stage_worker(
        composition=composition,
        worker_id="worker-guarded",
        run_id="run-guarded",
        operation_id="operation-guarded",
    ) == {"worker_id": "worker-guarded", "status": "completed"}
    assert events == ["status"]

    events.clear()
    active_checks = 0
    assert workflow_service.adopt_guarded_learning_stage_worker_result(
        composition=composition,
        worker_id="worker-guarded",
        run_id="run-guarded",
        expected_revision=3,
        stage="fusion",
        operation_id="operation-guarded",
    ) == {"status": "adopted", "receipt": {"result_sha256": "a" * 64}}
    assert events == ["precheck", "adopt"]

    events.clear()
    active_checks = 0

    def _postcheck_failure(**_kwargs):
        nonlocal active_checks
        active_checks += 1
        events.append("precheck" if active_checks == 1 else "postcheck")
        if active_checks == 2:
            raise LearningWorkflowStageOperationError("postcheck failed")
        return {"operation_id": "operation-guarded"}

    monkeypatch.setattr(
        workflow_service,
        "require_active_learning_workflow_stage_operation",
        _postcheck_failure,
    )
    with pytest.raises(LearningWorkflowStageOperationError, match="postcheck failed"):
        workflow_service.start_guarded_learning_stage_worker(
            composition=composition,
            run_id="run-guarded",
            expected_revision=3,
            stage="fusion",
            operation_id="operation-guarded",
            task_kind="panel_learning_recognition_trial",
            payload={"app_name": "fixture"},
        )
    assert events == ["precheck", "start", "postcheck", "cancel"]


def test_guarded_benchmark_start_fails_closed_before_registry_start(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    class _Registry:
        def start(self, **_kwargs):
            calls.append("start")
            raise AssertionError("benchmark C2 must not reach generic Registry.start")

    composition = workflow_service.LearningWorkflowServiceComposition(
        store=object(),
        worker_registry=_Registry(),
        project_root=tmp_path,
        composition_kind="test",
        benchmark_supervision_root=None,
        provider_case_resolver=None,
    )
    monkeypatch.setattr(
        workflow_service,
        "require_active_learning_workflow_stage_operation",
        lambda **_kwargs: calls.append("precheck") or {},
    )
    with pytest.raises(
        LearningWorkflowStageOperationError,
        match="benchmark_v2 incumbent orchestration is unavailable before C3",
    ):
        workflow_service.start_guarded_learning_stage_worker(
            composition=composition,
            run_id="run-guarded",
            expected_revision=3,
            stage="screen_understanding",
            operation_id="operation-guarded",
            task_kind="vision_observe_screen",
            payload={
                "benchmark_v2_incumbent": {
                    "provider_case_ref": {
                        "case_id": "case",
                        "case_content_sha256": "a" * 64,
                    }
                }
            },
        )
    assert calls == ["precheck"]


def test_guarded_remaining_wrappers_delegate_deep_equal_and_cancel_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class _Registry:
        def cancel_by_operation(self, **_kwargs):
            events.append("registry.cancel")
            return {
                "backend_compute_termination": "terminated",
                "model_service_compute_termination": "request_not_active",
                "worker_id": "worker-guarded",
                "model_request_id": "request-guarded",
                "model_request_cancellation": {"status": "request_not_active"},
            }

        def attachment_by_operation(self, **_kwargs):
            events.append("registry.attachment")
            return None

    composition = workflow_service.LearningWorkflowServiceComposition(
        store=object(),
        worker_registry=_Registry(),
        project_root=tmp_path,
        composition_kind="test",
        benchmark_supervision_root=None,
        provider_case_resolver=None,
    )
    monkeypatch.setattr(
        workflow_service,
        "require_active_learning_workflow_stage_operation",
        lambda **_kwargs: events.append("precheck") or {"operation_id": "operation"},
    )

    def _delegate(name: str, result: dict[str, object]):
        def _call(**kwargs):
            events.append(name)
            assert kwargs["store"] is composition.store
            assert Path(kwargs["project_root"]) == tmp_path
            return deepcopy(result)

        return _call

    monkeypatch.setattr(
        workflow_service,
        "continue_learning_stage_worker_result",
        _delegate("continue", {"kind": "continue"}),
    )
    monkeypatch.setattr(
        workflow_service,
        "heartbeat_learning_workflow_stage_operation",
        _delegate("heartbeat", {"kind": "heartbeat"}),
    )
    monkeypatch.setattr(
        workflow_service,
        "finish_learning_workflow_stage_operation",
        _delegate("finish", {"kind": "finish"}),
    )
    monkeypatch.setattr(
        workflow_service,
        "recover_expired_learning_workflow_stage_operation",
        _delegate("recover", {"kind": "recover"}),
    )

    assert workflow_service.continue_guarded_learning_stage_worker_result(
        composition=composition,
        run_id="run",
        expected_revision=1,
        stage="fusion",
        operation_id="operation",
        worker_id="worker",
    ) == {"kind": "continue"}
    assert workflow_service.heartbeat_guarded_learning_workflow_stage_operation(
        composition=composition,
        run_id="run",
        expected_revision=1,
        stage="fusion",
        operation_id="operation",
    ) == {"kind": "heartbeat"}
    assert workflow_service.finish_guarded_learning_workflow_stage_operation(
        composition=composition,
        run_id="run",
        expected_revision=1,
        stage="fusion",
        operation_id="operation",
        outcome="failed",
    ) == {"kind": "finish"}
    assert workflow_service.recover_guarded_learning_workflow_stage_operation(
        composition=composition,
        run_id="run",
        expected_revision=1,
    ) == {"kind": "recover"}

    def _cancel(**kwargs):
        events.append("stage.cancel")
        assert kwargs["_prechecked_stage_execution"] == {"operation_id": "operation"}
        return {"kind": "cancel"}

    monkeypatch.setattr(
        workflow_service,
        "cancel_learning_workflow_stage_operation",
        _cancel,
    )
    cancelled = workflow_service.cancel_guarded_learning_workflow_stage_operation(
        composition=composition,
        run_id="run",
        expected_revision=1,
        stage="fusion",
        operation_id="operation",
        reason="cancel",
    )
    assert cancelled == {
        "kind": "cancel",
        "worker_termination": {
            "backend_compute_termination": "terminated",
            "model_service_compute_termination": "request_not_active",
            "worker_id": "worker-guarded",
            "model_request_id": "request-guarded",
            "model_request_cancellation": {"status": "request_not_active"},
        },
    }
    assert events[-3:] == ["precheck", "registry.cancel", "stage.cancel"]


def test_guarded_nonbenchmark_probe_reuses_the_only_store_read(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    current = {"run_id": "run", "revision": 1, "current_stage": "fusion"}

    class _Store:
        def get(self, run_id):
            assert run_id == "run"
            calls.append("store.get")
            return current

    composition = workflow_service.LearningWorkflowServiceComposition(
        store=_Store(), worker_registry=object(), project_root=tmp_path,
        composition_kind="test", benchmark_supervision_root=None,
        provider_case_resolver=None,
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_incumbent_operation_from_state",
        lambda *_args: None,
    )

    def delegated(**kwargs):
        calls.append("continue")
        assert kwargs["_preloaded_current"] is current
        return {"status": "continued"}

    monkeypatch.setattr(
        workflow_service, "continue_learning_stage_worker_result", delegated
    )
    assert workflow_service.continue_guarded_learning_stage_worker_result(
        composition=composition, run_id="run", expected_revision=1,
        stage="fusion", operation_id="operation", worker_id="worker",
    ) == {"status": "continued"}
    assert calls == ["store.get", "continue"]


def test_guarded_benchmark_internal_value_error_maps_to_stage_operation_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    composition = workflow_service.LearningWorkflowServiceComposition(
        store=object(), worker_registry=object(), project_root=tmp_path,
        composition_kind="test", benchmark_supervision_root=object(),
        provider_case_resolver=object(),
    )
    monkeypatch.setattr(
        workflow_service,
        "_resume_benchmark_v2_incumbent_operation",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("invalid closed parent")),
    )
    monkeypatch.setattr(
        workflow_service,
        "require_active_learning_workflow_stage_operation",
        lambda **_kwargs: {"benchmark_v2_incumbent": {}},
    )
    with pytest.raises(
        LearningWorkflowStageOperationError, match="invalid closed parent"
    ):
        workflow_service.adopt_guarded_learning_stage_worker_result(
            composition=composition, worker_id="worker", run_id="run",
            expected_revision=1, stage="screen_understanding",
            operation_id="operation",
        )


def test_guarded_no_direct_registry_calls_outside_composition_owner() -> None:
    import ast

    allowed_owner = "_LearningWorkflowRegistryOwner"
    for relative in ("app/api/panel.py", "app/learn/workflow_service.py"):
        path = Path(__file__).resolve().parents[1] / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        violations: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {
                "start",
                "status",
                "adopt_result",
                "read_adopted_result",
                "cancel_by_operation",
                "attachment_by_operation",
            }:
                continue
            ancestor = parents.get(node)
            owner_class = None
            while ancestor is not None:
                if isinstance(ancestor, ast.ClassDef):
                    owner_class = ancestor.name
                    break
                ancestor = parents.get(ancestor)
            if owner_class != allowed_owner:
                violations.append(node.lineno)
        assert violations == [], f"direct Registry calls remain in {relative}: {violations}"


def test_duplicate_hybrid_continue_recovers_same_next_worker_without_inference(
    tmp_path: Path,
) -> None:
    from app.learn.workflow_service import continue_learning_stage_worker_result

    store, bind_state = _store_at_completed_bind_capture()
    bundle_ref = {"id": "hybrid-capture/test", "content_sha256": "1" * 64}
    orchestration = {
        "run_id": "run-stage-operation",
        "workflow_revision": bind_state["revision"],
        "hybrid_capture_bundle_ref": bundle_ref,
        "capture_image_path": "artifacts/capture.png",
        "hybrid_config": {"config_sha256": "2" * 64},
        "capture_bundle": {"content_sha256": "3" * 64},
    }

    class _WorkerRegistry:
        def __init__(self) -> None:
            self.started: dict[tuple[str, str], dict[str, object]] = {}
            self.inference_starts = 0

        def read_adopted_result(self, **_kwargs):
            return {
                "receipt": {
                    "worker_id": "worker-hybrid-omni",
                    "task_kind": "panel_learning_hybrid_omni_discovery",
                    "result_sha256": "4" * 64,
                },
                "response": {
                    "contract_version": "learning_hybrid_managed_stage_result_v1",
                    "learning_pipeline_mode": "hybrid_v1_1",
                    "task_kind": "panel_learning_hybrid_omni_discovery",
                    "outcome": "completed",
                    "result": {
                        "contract_version": "hybrid_omni_discovery_result_v1",
                        "outcome": "completed",
                        "hybrid_capture_bundle_ref": bundle_ref,
                        "inventory": {
                            "contract_version": "hybrid_omni_inventory_v1",
                            "content_sha256": "5" * 64,
                            "candidates": [],
                        },
                    },
                    "orchestration": orchestration,
                },
            }

        def start(self, **kwargs):
            key = (
                kwargs["task_kind"],
                json.dumps(kwargs["payload"], sort_keys=True),
            )
            if key not in self.started:
                self.inference_starts += 1
                self.started[key] = {
                    "worker_id": "worker-hybrid-qwen",
                    "payload_sha256": "6" * 64,
                }
            return self.started[key]

    registry = _WorkerRegistry()
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-stage-operation",
        expected_revision=bind_state["revision"],
        stage="screen_understanding",
        operation_id="operation-hybrid",
        learning_pipeline_mode="hybrid_v1_1",
    )
    request = {
        "store": store,
        "worker_registry": registry,
        "project_root": tmp_path,
        "run_id": "run-stage-operation",
        "expected_revision": started["workflow_state"]["revision"],
        "stage": "screen_understanding",
        "operation_id": "operation-hybrid",
        "worker_id": "worker-hybrid-omni",
    }

    first = continue_learning_stage_worker_result(**request)
    duplicate = continue_learning_stage_worker_result(**request)

    assert first["next_worker"] == duplicate["next_worker"]
    assert first["next_worker"]["worker_id"] == "worker-hybrid-qwen"
    assert registry.inference_starts == 1


@pytest.mark.parametrize(
    ("task_kind", "handler_target"),
    [
        (
            "panel_learning_hybrid_omni_discovery",
            "app.learn.workflow_worker.run_hybrid_omni_task",
        ),
        (
            "panel_learning_hybrid_qwen_binding",
            "app.learn.workflow_worker.run_hybrid_qwen_task",
        ),
        (
            "panel_learning_hybrid_fusion",
            "app.learn.workflow_worker.run_hybrid_fusion_task",
        ),
        (
            "panel_learning_calibration_sequence",
            "app.learn.workflow_worker.run_learning_calibration_sequence",
        ),
    ],
)
def test_raised_hybrid_handler_failure_is_adoptable_and_idempotently_safe_stops(
    tmp_path: Path,
    monkeypatch,
    task_kind: str,
    handler_target: str,
) -> None:
    from app.learn import workflow_worker
    from app.learn.workflow_worker import LearningStageWorkerRegistry
    from app.core import model_server

    handler_calls = 0
    lifecycle_calls: list[dict[str, object]] = []
    managed_lease = (
        {
            "lease_id": "lease-controlled",
            "incarnation_id": "incarnation-controlled",
            "owner_request_id": "owner-controlled",
            "profile_id": "qwen-controlled",
            "server_process_identity": {"pid": 1, "create_time_ns": 1},
            "server_socket": {"host": "127.0.0.1", "port": 13240},
        }
        if task_kind == "panel_learning_hybrid_qwen_binding"
        else None
    )

    def raise_controlled(*_args, **_kwargs):
        nonlocal handler_calls
        handler_calls += 1
        raise RuntimeError(f"controlled {task_kind} failure")

    monkeypatch.setattr(handler_target, raise_controlled)
    monkeypatch.setattr(
        workflow_worker,
        "_ensure_learning_stage_model_ready",
        lambda *_args, **_kwargs: managed_lease,
    )
    monkeypatch.setattr(
        workflow_worker,
        "validate_hybrid_qwen_task_payload",
        lambda _payload: None,
    )

    def reconcile_failure(**kwargs):
        lifecycle_calls.append(kwargs)
        return {
            "status": "cancellation_acknowledged_pending",
            "lifecycle_state": "request_in_flight",
        }

    monkeypatch.setattr(
        model_server,
        "reconcile_qwen_model_lease_failure",
        reconcile_failure,
    )

    class _InlineProcess:
        def __init__(self, *, target, args, name) -> None:
            self.target = target
            self.args = args
            self.name = name
            self.pid = None
            self.exitcode = None
            self.started = False

        def start(self) -> None:
            self.started = True
            self.target(*self.args)
            self.exitcode = 0

        def is_alive(self) -> bool:
            return False

        def join(self, timeout=None) -> None:
            del timeout

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path / task_kind,
        process_factory=lambda **kwargs: _InlineProcess(**kwargs),
    )
    store, bind_state = _store_at_completed_bind_capture()
    operation = start_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-stage-operation",
        expected_revision=bind_state["revision"],
        stage="screen_understanding",
        operation_id=f"operation-{task_kind}",
        learning_pipeline_mode="hybrid_v1_1",
    )
    workflow_revision = bind_state["revision"]
    lineage = _hybrid_supervised_lineage(
        run_id="run-stage-operation",
        workflow_revision=workflow_revision,
        operation_id=operation["operation_id"],
    )
    omni_inventory = {
        "contract_version": "hybrid_omni_inventory_v1",
        "items": [],
    }
    qwen_bindings = {
        "contract_version": "hybrid_qwen_bindings_v1",
        "items": [],
    }
    fusion_result = {
        "contract_version": "hybrid_fusion_result_v1",
        "items": [],
    }
    orchestration: dict[str, object] = {
        "workflow_revision": workflow_revision,
        "omni_inventory": omni_inventory,
        "qwen_bindings": qwen_bindings,
        "fusion_result": fusion_result,
    }
    if task_kind in {
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_calibration_sequence",
    }:
        previous_provider = (
            "omni"
            if task_kind == "panel_learning_hybrid_qwen_binding"
            else "qwen"
        )
        receipt_name = (
            "omni_cleanup_receipt"
            if previous_provider == "omni"
            else "qwen_gpu_cleanup_receipt"
        )
        predecessor = (
            {"contract_version": "hybrid_capture_bundle_v1", "items": []}
            if previous_provider == "omni"
            else omni_inventory
        )
        provider_result = (
            omni_inventory if previous_provider == "omni" else qwen_bindings
        )
        orchestration[receipt_name] = _observed_hybrid_cleanup_receipt(
            previous_provider,
            lineage=lineage,
            predecessor=predecessor,
            provider_result=provider_result,
        )
    payload = {
        "learning_pipeline_mode": "hybrid_v1_1",
        "workflow_revision": workflow_revision,
        "hybrid_capture_bundle_ref": {
            "id": "hybrid-capture/controlled-handler-failure",
            "content_sha256": "c" * 64,
        },
        "_hybrid_orchestration": orchestration,
    }
    started = registry.start(
        run_id="run-stage-operation",
        stage="screen_understanding",
        operation_id=operation["operation_id"],
        task_kind=task_kind,
        payload=payload,
        authoritative_workflow_revision=workflow_revision,
        reuse_active_identical=True,
    )
    status = registry.status(
        worker_id=started["worker_id"],
        run_id="run-stage-operation",
        operation_id=operation["operation_id"],
    )
    if task_kind in {
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
    }:
        assert status["status"] == "recovery_required"
        assert status["result_available"] is False
        assert handler_calls == 1
        if managed_lease is not None:
            assert lifecycle_calls == [
                {
                    "model_lease": managed_lease,
                    "compute_completed": False,
                    "reason": "managed_hybrid_handler_failed",
                }
            ]
        return
    assert status["status"] == "completed"

    first_adoption = registry.adopt_result(
        worker_id=started["worker_id"],
        run_id="run-stage-operation",
        stage="screen_understanding",
        operation_id=operation["operation_id"],
    )
    duplicate_adoption = registry.adopt_result(
        worker_id=started["worker_id"],
        run_id="run-stage-operation",
        stage="screen_understanding",
        operation_id=operation["operation_id"],
    )
    assert duplicate_adoption["receipt"] == first_adoption["receipt"]
    adopted = registry.read_adopted_result(
        worker_id=started["worker_id"],
        run_id="run-stage-operation",
        stage="screen_understanding",
        operation_id=operation["operation_id"],
    )
    failure_result = adopted["response"]["result"]
    assert failure_result["error_type"] == "RuntimeError"
    if managed_lease is not None:
        assert failure_result["model_lifecycle"] == {
            "status": "cancellation_acknowledged_pending",
            "lifecycle_state": "request_in_flight",
        }
        assert lifecycle_calls == [
            {
                "model_lease": managed_lease,
                "compute_completed": False,
                "reason": "managed_hybrid_handler_failed",
            }
        ]

    continuation_request = {
        "store": store,
        "worker_registry": registry,
        "project_root": tmp_path,
        "run_id": "run-stage-operation",
        "expected_revision": operation["workflow_state"]["revision"],
        "stage": "screen_understanding",
        "operation_id": operation["operation_id"],
        "worker_id": started["worker_id"],
    }
    continued = workflow_service.continue_learning_stage_worker_result(
        **continuation_request
    )
    duplicate = workflow_service.continue_learning_stage_worker_result(
        **continuation_request
    )

    assert continued["outcome"] == "safe_stopped"
    assert continued["reason"].startswith("SAFE_STOP")
    assert duplicate["idempotent_replay"] is True
    assert duplicate["workflow_state"]["revision"] == continued["workflow_state"]["revision"]
    assert handler_calls == 1
