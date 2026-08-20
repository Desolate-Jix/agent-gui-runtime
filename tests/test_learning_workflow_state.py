from __future__ import annotations

import pytest

from app.learn.workflow_state import (
    LEARNING_WORKFLOW_STAGES,
    LearningWorkflowTransitionError,
    transition_learning_workflow_state,
)
from app.learn.workflow_store import LearningWorkflowRunStore


def _completion_evidence(stage: str) -> dict[str, str]:
    evidence_by_stage = {
        "bind_capture": {"image_path": "artifacts/screenshots/capture.png"},
        "screen_understanding": {"trial_path": "artifacts/learning-runs/trial.json"},
        "numbered_map": {
            "report_path": "artifacts/learning-runs/stage2.json",
            "overlay_path": "artifacts/review-overlays/stage2.png",
        },
        "precise_calibration": {
            "result_path": "artifacts/learning-runs/calibration-result.json",
            "overlay_path": "artifacts/review-overlays/calibrated.png",
        },
        "review_repair": {
            "final_stage2_report_path": "artifacts/learning-runs/final-stage2.json",
            "final_overlay_path": "artifacts/review-overlays/final.png",
        },
        "fusion": {"trial_path": "artifacts/learning-runs/fused-trial.json"},
        "page_details": {"source_path": "artifacts/learning-runs/page-detail.json"},
        "pathgraph_draft": {"scaffold_path": "artifacts/learning-runs/pathgraph.json"},
        "complete": {},
    }
    return evidence_by_stage[stage]


def _advance_to(stage: str) -> dict:
    state: dict | None = None
    for current in LEARNING_WORKFLOW_STAGES:
        state = transition_learning_workflow_state(
            previous_state=state,
            run_id="run-demo",
            stage=current,
            outcome="running",
            reason=f"{current} started",
        )
        if current == stage:
            return state
        state = transition_learning_workflow_state(
            previous_state=state,
            run_id="run-demo",
            stage=current,
            outcome="completed",
            reason=f"{current} completed",
            evidence_refs=_completion_evidence(current),
        )
    raise AssertionError(f"unknown stage: {stage}")


def test_workflow_state_advances_in_authoritative_order() -> None:
    state = _advance_to("numbered_map")

    assert state["contract_version"] == "learning_workflow_state_v2"
    assert state["current_stage"] == "numbered_map"
    assert state["workflow_status"] == "running"
    assert state["revision"] == 5
    assert state["stages"]["bind_capture"]["status"] == "completed"
    assert state["stages"]["screen_understanding"]["status"] == "completed"
    assert state["stages"]["numbered_map"]["status"] == "running"
    assert state["stages"]["precise_calibration"]["status"] == "pending"


def test_workflow_state_rejects_skipped_and_backward_transitions() -> None:
    state = _advance_to("screen_understanding")

    with pytest.raises(LearningWorkflowTransitionError, match="cannot skip"):
        transition_learning_workflow_state(
            previous_state=state,
            run_id="run-demo",
            stage="precise_calibration",
            outcome="running",
        )

    with pytest.raises(LearningWorkflowTransitionError, match="cannot move backward"):
        transition_learning_workflow_state(
            previous_state=state,
            run_id="run-demo",
            stage="bind_capture",
            outcome="running",
        )


@pytest.mark.parametrize("outcome", ["failed", "safe_stopped"])
def test_terminal_workflow_state_cannot_continue(outcome: str) -> None:
    state = _advance_to("precise_calibration")
    terminal = transition_learning_workflow_state(
        previous_state=state,
        run_id="run-demo",
        stage="precise_calibration",
        outcome=outcome,
        reason="evidence gate stopped the run",
    )

    assert terminal["workflow_status"] == outcome
    assert terminal["terminal"] is True
    assert terminal["stages"]["review_repair"]["status"] == "pending"

    with pytest.raises(LearningWorkflowTransitionError, match="terminal"):
        transition_learning_workflow_state(
            previous_state=terminal,
            run_id="run-demo",
            stage="review_repair",
            outcome="running",
        )


def test_workflow_completion_requires_every_stage() -> None:
    state: dict | None = None
    for stage in LEARNING_WORKFLOW_STAGES:
        state = transition_learning_workflow_state(
            previous_state=state,
            run_id="run-demo",
            stage=stage,
            outcome="running",
        )
        state = transition_learning_workflow_state(
            previous_state=state,
            run_id="run-demo",
            stage=stage,
            outcome="completed",
            evidence_refs=_completion_evidence(stage),
        )

    assert state is not None
    assert state["workflow_status"] == "completed"
    assert state["terminal"] is True
    assert all(item["status"] == "completed" for item in state["stages"].values())


def test_workflow_state_preserves_structured_evidence_without_message_inference() -> None:
    state = transition_learning_workflow_state(
        previous_state=None,
        run_id="run-demo",
        stage="bind_capture",
        outcome="running",
        reason="the word failed is only explanatory text",
        evidence_refs={"capture_id": "capture-1", "trace_path": "logs/demo.json"},
    )

    assert state["workflow_status"] == "running"
    assert state["current_reason"] == "the word failed is only explanatory text"
    assert state["current_evidence_refs"]["capture_id"] == "capture-1"
    assert state["stages"]["bind_capture"]["status"] == "running"


@pytest.mark.parametrize(
    ("stage", "missing_field"),
    [
        ("bind_capture", "image_path"),
        ("screen_understanding", "trial_path"),
        ("numbered_map", "report_path"),
        ("numbered_map", "overlay_path"),
        ("precise_calibration", "result_path"),
        ("precise_calibration", "overlay_path"),
        ("review_repair", "final_stage2_report_path"),
        ("review_repair", "final_overlay_path"),
        ("fusion", "trial_path"),
        ("page_details", "source_path"),
        ("pathgraph_draft", "scaffold_path"),
    ],
)
def test_workflow_stage_completion_requires_authoritative_evidence(
    stage: str,
    missing_field: str,
) -> None:
    state = _advance_to(stage)
    evidence = _completion_evidence(stage)
    evidence.pop(missing_field)

    with pytest.raises(
        LearningWorkflowTransitionError,
        match=f"{stage} completed requires evidence: {missing_field}",
    ):
        transition_learning_workflow_state(
            previous_state=state,
            run_id="run-demo",
            stage=stage,
            outcome="completed",
            reason=f"{stage} completed",
            evidence_refs=evidence,
        )


@pytest.mark.parametrize("outcome", ["failed", "safe_stopped"])
def test_workflow_terminal_outcome_requires_reason(outcome: str) -> None:
    state = _advance_to("screen_understanding")

    with pytest.raises(LearningWorkflowTransitionError, match="requires a reason"):
        transition_learning_workflow_state(
            previous_state=state,
            run_id="run-demo",
            stage="screen_understanding",
            outcome=outcome,
        )


def test_workflow_state_rejects_tampered_previous_stage_status() -> None:
    state = _advance_to("screen_understanding")
    state["stages"]["screen_understanding"]["status"] = "completed"
    state["stages"]["numbered_map"]["status"] = "completed"

    with pytest.raises(LearningWorkflowTransitionError, match="does not match event history"):
        transition_learning_workflow_state(
            previous_state=state,
            run_id="run-demo",
            stage="numbered_map",
            outcome="running",
        )


def test_workflow_run_store_is_authoritative_and_returns_copies() -> None:
    store = LearningWorkflowRunStore(max_runs=4)
    state = store.transition(
        run_id="run-store",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
        reason="started",
    )
    state["stages"]["bind_capture"]["status"] = "completed"

    persisted = store.get("run-store")

    assert persisted["revision"] == 1
    assert persisted["stages"]["bind_capture"]["status"] == "running"


def test_workflow_run_store_rejects_stale_revision() -> None:
    store = LearningWorkflowRunStore(max_runs=4)
    store.transition(
        run_id="run-store",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )

    with pytest.raises(LearningWorkflowTransitionError, match="revision conflict"):
        store.transition(
            run_id="run-store",
            expected_revision=0,
            stage="bind_capture",
            outcome="completed",
        )

    completed = store.transition(
        run_id="run-store",
        expected_revision=1,
        stage="bind_capture",
        outcome="completed",
        evidence_refs=_completion_evidence("bind_capture"),
    )
    assert completed["revision"] == 2


def test_workflow_run_store_rejects_unknown_run_recovery() -> None:
    store = LearningWorkflowRunStore(max_runs=4)

    with pytest.raises(LearningWorkflowTransitionError, match="workflow run not found"):
        store.get("missing-run")
