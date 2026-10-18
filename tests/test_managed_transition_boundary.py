from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.learn import workflow_service as service
from app.learn.workflow_state import (
    LEARNING_WORKFLOW_COMPLETION_EVIDENCE,
    LEARNING_WORKFLOW_STAGES,
    LearningWorkflowTransitionError,
)
from app.learn.workflow_store import LearningWorkflowRunStore


MANAGED_STAGES = LEARNING_WORKFLOW_STAGES[1:6]
NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)
RUN_ID = "managed-boundary-isolated"


def _evidence(stage):
    return {key: f"synthetic/{stage}/{key}.json" for key in LEARNING_WORKFLOW_COMPLETION_EVIDENCE[stage]}


@pytest.fixture
def store(tmp_path):
    instance = LearningWorkflowRunStore(state_path=tmp_path / "workflow.json")
    yield instance
    instance.close()


def _before_stage(store, target):
    state = None
    for stage in LEARNING_WORKFLOW_STAGES[:LEARNING_WORKFLOW_STAGES.index(target)]:
        # 仅构造隔离前置状态；被测公开边界不使用底层入口。
        state = store.transition(run_id=RUN_ID, expected_revision=0 if state is None else state["revision"], stage=stage, outcome="running")
        state = store.transition(run_id=RUN_ID, expected_revision=state["revision"], stage=stage, outcome="completed", evidence_refs=_evidence(stage))
    return state


def _assert_rejected_without_mutation(store, tmp_path, monkeypatch, state, stage, outcome, evidence):
    before = deepcopy(state)
    durable_before = (tmp_path / "workflow.json").read_bytes()
    calls = []
    original_transition = store.transition
    original_verify = service.verify_learning_workflow_completion_evidence

    def transition(**kwargs):
        calls.append("write")
        return original_transition(**kwargs)

    def verify(**kwargs):
        calls.append("verify")
        return original_verify(**kwargs)

    monkeypatch.setattr(store, "transition", transition)
    monkeypatch.setattr(service, "verify_learning_workflow_completion_evidence", verify)
    with pytest.raises(service.LearningWorkflowStageOperationError, match=f"{stage} must use a managed workflow stage operation") as exc:
        service.transition_learning_workflow_run(store=store, project_root=tmp_path, run_id=RUN_ID, expected_revision=state["revision"], stage=stage, outcome=outcome, reason="controlled request", evidence_refs=evidence)
    assert type(exc.value).__name__ == "LearningWorkflowManagedStageOperationRequiredError"
    assert calls == []
    assert store.get(RUN_ID) == before
    assert (tmp_path / "workflow.json").read_bytes() == durable_before


@pytest.mark.parametrize("stage", MANAGED_STAGES)
def test_public_managed_start_rejects_before_any_mutation(store, tmp_path, monkeypatch, stage):
    state = _before_stage(store, stage)
    _assert_rejected_without_mutation(store, tmp_path, monkeypatch, state, stage, "running", {})


@pytest.mark.parametrize("stage", MANAGED_STAGES)
@pytest.mark.parametrize("outcome", ["running", "completed", "failed", "safe_stopped"])
def test_public_managed_current_transition_cannot_finish_or_forge_renewal(store, tmp_path, monkeypatch, stage, outcome):
    state = _before_stage(store, stage)
    operation = service.start_learning_workflow_stage_operation(store=store, project_root=tmp_path, run_id=RUN_ID, expected_revision=state["revision"], stage=stage, now=NOW)
    state = operation["workflow_state"]
    evidence = deepcopy(state["stages"][stage]["evidence_refs"])
    evidence["stage_execution"]["lease_expires_at"] = (NOW + timedelta(days=99)).isoformat()
    evidence["stage_execution"]["heartbeat_count"] = 999
    _assert_rejected_without_mutation(store, tmp_path, monkeypatch, state, stage, outcome, evidence)


@pytest.mark.parametrize("case,expected", [
    ("stale", "revision conflict"),
    ("missing", "workflow run not found"),
    ("skip", "cannot skip"),
    ("backward", "cannot move backward"),
    ("before_complete", "cannot advance before completing"),
    ("terminal", "workflow is terminal"),
    ("unknown_outcome", "unknown outcome"),
])
def test_invalid_requests_preserve_original_transition_errors(store, tmp_path, case, expected):
    state = _before_stage(store, "screen_understanding")
    target, outcome, run_id = "screen_understanding", "running", RUN_ID
    if case in {"backward", "before_complete", "terminal"}:
        state = service.start_learning_workflow_stage_operation(store=store, project_root=tmp_path, run_id=RUN_ID, expected_revision=state["revision"], stage=target, now=NOW)["workflow_state"]
    if case == "terminal":
        state = store.transition(run_id=RUN_ID, expected_revision=state["revision"], stage=target, outcome="failed", reason="synthetic terminal")
    revision = state["revision"]
    if case == "stale":
        revision -= 1
    elif case == "missing":
        run_id = "missing-run"
    elif case == "skip":
        target = "fusion"
    elif case == "backward":
        target = "bind_capture"
    elif case == "before_complete":
        target = "numbered_map"
    elif case == "unknown_outcome":
        outcome = "invalid"
    durable_before = (tmp_path / "workflow.json").read_bytes()
    with pytest.raises(LearningWorkflowTransitionError, match=expected):
        service.transition_learning_workflow_run(store=store, project_root=tmp_path, run_id=run_id, expected_revision=revision, stage=target, outcome=outcome)
    assert store.get(RUN_ID) == state
    assert (tmp_path / "workflow.json").read_bytes() == durable_before


def test_policy_snapshot_race_still_uses_store_revision_compare_and_swap(store, tmp_path, monkeypatch):
    state = service.transition_learning_workflow_run(store=store, project_root=tmp_path, run_id=RUN_ID, expected_revision=0, stage="bind_capture", outcome="running")
    original_get = store.get
    writer_states = []

    def read_then_concurrent_write(run_id):
        snapshot = original_get(run_id)
        if not writer_states:
            writer_states.append(store.transition(run_id=RUN_ID, expected_revision=state["revision"], stage="bind_capture", outcome="completed", evidence_refs=_evidence("bind_capture")))
        return snapshot

    monkeypatch.setattr(store, "get", read_then_concurrent_write)
    with pytest.raises(LearningWorkflowTransitionError, match="revision conflict"):
        service.transition_learning_workflow_run(store=store, project_root=tmp_path, run_id=RUN_ID, expected_revision=state["revision"], stage="screen_understanding", outcome="running")
    assert original_get(RUN_ID) == writer_states[0]
    assert writer_states[0]["revision"] == state["revision"] + 1
    assert len(writer_states[0]["events"]) == len(state["events"]) + 1


@pytest.mark.parametrize("revision", [2.0, "2", None, -1])
def test_invalid_revision_type_is_not_relabelled_as_managed_policy(store, tmp_path, revision):
    state = _before_stage(store, "screen_understanding")
    before = (tmp_path / "workflow.json").read_bytes()
    with pytest.raises(LearningWorkflowTransitionError, match="expected_revision must be a non-negative integer"):
        service.transition_learning_workflow_run(store=store, project_root=tmp_path, run_id=RUN_ID, expected_revision=revision, stage="screen_understanding", outcome="running")
    assert store.get(RUN_ID) == state
    assert (tmp_path / "workflow.json").read_bytes() == before


@pytest.mark.parametrize("stage", ["screen_understanding", "fusion"])
def test_specialized_heartbeat_renews_real_managed_lease(store, tmp_path, stage):
    state = _before_stage(store, stage)
    operation = service.start_learning_workflow_stage_operation(store=store, project_root=tmp_path, run_id=RUN_ID, expected_revision=state["revision"], stage=stage, now=NOW)
    state = operation["workflow_state"]
    result = service.heartbeat_learning_workflow_stage_operation(store=store, project_root=tmp_path, run_id=RUN_ID, expected_revision=state["revision"], stage=stage, operation_id=operation["operation_id"], now=NOW + timedelta(seconds=30))
    assert result["workflow_state"]["revision"] == state["revision"] + 1
    assert result["operation_id"] == operation["operation_id"]
    assert result["lease_expires_at"] > operation["lease_expires_at"]
    assert store.get(RUN_ID) == result["workflow_state"]


@pytest.mark.parametrize("entry", ["public", "managed"])
def test_existing_downstream_zero_guard_observes_actual_store_writes(store, tmp_path, monkeypatch, entry):
    from test_portfolio_hybrid_v1_1_benchmark_v2_worker_binding import _install_downstream_zero_guard

    state = _before_stage(store, "screen_understanding")
    before = (tmp_path / "workflow.json").read_bytes()
    calls = _install_downstream_zero_guard(monkeypatch)
    with pytest.raises(AssertionError, match="Task 5 negative reached workflow_store_cas"):
        if entry == "public":
            service.transition_learning_workflow_run(store=store, project_root=tmp_path, run_id="new-public-run", expected_revision=0, stage="bind_capture", outcome="running")
        else:
            service.start_learning_workflow_stage_operation(store=store, project_root=tmp_path, run_id=RUN_ID, expected_revision=state["revision"], stage="screen_understanding", now=NOW)
    assert calls["workflow_store_cas"] == 1
    assert sum(calls.values()) == 1
    assert store.get(RUN_ID) == state
    assert (tmp_path / "workflow.json").read_bytes() == before
