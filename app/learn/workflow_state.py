from __future__ import annotations

from copy import deepcopy
from typing import Any


LEARNING_WORKFLOW_STAGES = (
    "bind_capture",
    "screen_understanding",
    "numbered_map",
    "precise_calibration",
    "review_repair",
    "fusion",
    "page_details",
    "pathgraph_draft",
    "complete",
)

_OUTCOMES = {"running", "completed", "failed", "safe_stopped"}
_TERMINAL_OUTCOMES = {"failed", "safe_stopped"}
LEARNING_WORKFLOW_CONTRACT_VERSION = "learning_workflow_state_v2"
LEARNING_WORKFLOW_COMPLETION_EVIDENCE: dict[str, tuple[str, ...]] = {
    "bind_capture": ("image_path",),
    "screen_understanding": ("trial_path",),
    "numbered_map": ("report_path", "overlay_path"),
    "precise_calibration": ("result_path", "overlay_path"),
    "review_repair": ("final_stage2_report_path", "final_overlay_path"),
    "fusion": ("trial_path",),
    "page_details": ("source_path",),
    "pathgraph_draft": ("scaffold_path",),
    "complete": (),
}


class LearningWorkflowTransitionError(ValueError):
    """学习工作流状态转换不满足顺序或终态约束。"""


def transition_learning_workflow_state(
    *,
    previous_state: dict[str, Any] | None,
    run_id: str,
    stage: str,
    outcome: str,
    reason: str = "",
    evidence_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按固定依赖顺序推进学习流程，不根据显示文案猜测状态。"""

    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        raise LearningWorkflowTransitionError("run_id is required")
    if stage not in LEARNING_WORKFLOW_STAGES:
        raise LearningWorkflowTransitionError(f"unknown stage: {stage}")
    if outcome not in _OUTCOMES:
        raise LearningWorkflowTransitionError(f"unknown outcome: {outcome}")

    state = _initial_state(normalized_run_id) if previous_state is None else _validated_copy(
        previous_state,
        normalized_run_id,
    )
    return _apply_transition(
        state,
        stage=stage,
        outcome=outcome,
        reason=reason,
        evidence_refs=evidence_refs,
    )


def validate_learning_workflow_state(state: dict[str, Any]) -> dict[str, Any]:
    """使用正式事件重放逻辑验证并复制持久化状态。"""

    run_id = str(state.get("run_id") or "") if isinstance(state, dict) else ""
    return _validated_copy(state, run_id)


def _apply_transition(
    state: dict[str, Any],
    *,
    stage: str,
    outcome: str,
    reason: str = "",
    evidence_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if stage not in LEARNING_WORKFLOW_STAGES:
        raise LearningWorkflowTransitionError(f"unknown stage: {stage}")
    if outcome not in _OUTCOMES:
        raise LearningWorkflowTransitionError(f"unknown outcome: {outcome}")
    if state["terminal"] is True:
        raise LearningWorkflowTransitionError("workflow is terminal and cannot continue")

    current_stage = state.get("current_stage")
    target_index = LEARNING_WORKFLOW_STAGES.index(stage)
    current_index = LEARNING_WORKFLOW_STAGES.index(current_stage) if current_stage else -1
    current_status = state["stages"][stage]["status"]
    structured_evidence = deepcopy(evidence_refs) if isinstance(evidence_refs, dict) else {}

    if current_stage is None:
        if stage != LEARNING_WORKFLOW_STAGES[0] or outcome != "running":
            raise LearningWorkflowTransitionError("workflow must start with bind_capture running")
    elif stage == current_stage:
        if current_status != "running":
            raise LearningWorkflowTransitionError(f"stage is not running: {stage}")
        if outcome == "running":
            _validate_managed_running_renewal(
                state["stages"][stage],
                structured_evidence,
            )
    elif target_index < current_index:
        raise LearningWorkflowTransitionError(
            f"cannot move backward from {current_stage} to {stage}"
        )
    elif target_index > current_index + 1:
        raise LearningWorkflowTransitionError(
            f"cannot skip from {current_stage} to {stage}"
        )
    else:
        if state["stages"][current_stage]["status"] != "completed":
            raise LearningWorkflowTransitionError(
                f"cannot advance before completing {current_stage}"
            )
        if outcome != "running":
            raise LearningWorkflowTransitionError("new stage must start with running")

    _validate_transition_evidence(
        stage=stage,
        outcome=outcome,
        reason=reason,
        evidence_refs=structured_evidence,
    )
    stage_record = state["stages"][stage]
    stage_record["status"] = outcome
    stage_record["reason"] = str(reason or "")
    stage_record["evidence_refs"] = structured_evidence
    state["current_stage"] = stage
    state["current_reason"] = str(reason or "")
    state["current_evidence_refs"] = structured_evidence
    state["revision"] += 1

    if outcome in _TERMINAL_OUTCOMES:
        state["workflow_status"] = outcome
        state["terminal"] = True
    elif stage == LEARNING_WORKFLOW_STAGES[-1] and outcome == "completed":
        state["workflow_status"] = "completed"
        state["terminal"] = True
    else:
        state["workflow_status"] = "running"

    state["events"].append(
        {
            "revision": state["revision"],
            "stage": stage,
            "outcome": outcome,
            "reason": str(reason or ""),
            "evidence_refs": structured_evidence,
        }
    )
    return state


def _validate_managed_running_renewal(
    stage_record: dict[str, Any],
    evidence_refs: dict[str, Any],
) -> None:
    current_evidence = stage_record.get("evidence_refs")
    current_execution = (
        current_evidence.get("stage_execution")
        if isinstance(current_evidence, dict)
        else None
    )
    renewed_execution = evidence_refs.get("stage_execution")
    if (
        not isinstance(current_execution, dict)
        or not isinstance(renewed_execution, dict)
        or current_execution.get("owner") != "backend_lease"
        or renewed_execution.get("owner") != "backend_lease"
        or not str(current_execution.get("operation_id") or "")
        or renewed_execution.get("operation_id") != current_execution.get("operation_id")
        or renewed_execution.get("started_at") != current_execution.get("started_at")
    ):
        raise LearningWorkflowTransitionError(
            "running stage renewal requires the same managed operation"
        )


def _initial_state(run_id: str) -> dict[str, Any]:
    return {
        "contract_version": LEARNING_WORKFLOW_CONTRACT_VERSION,
        "run_id": run_id,
        "revision": 0,
        "workflow_status": "idle",
        "terminal": False,
        "current_stage": None,
        "current_reason": "",
        "current_evidence_refs": {},
        "stage_order": list(LEARNING_WORKFLOW_STAGES),
        "stages": {
            stage: {"status": "pending", "reason": "", "evidence_refs": {}}
            for stage in LEARNING_WORKFLOW_STAGES
        },
        "events": [],
        "completion_evidence_requirements": {
            stage: list(fields)
            for stage, fields in LEARNING_WORKFLOW_COMPLETION_EVIDENCE.items()
        },
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _validated_copy(previous_state: dict[str, Any], run_id: str) -> dict[str, Any]:
    if not isinstance(previous_state, dict):
        raise LearningWorkflowTransitionError("previous_state must be an object")
    state = deepcopy(previous_state)
    if state.get("contract_version") != LEARNING_WORKFLOW_CONTRACT_VERSION:
        raise LearningWorkflowTransitionError("unsupported workflow state contract")
    if str(state.get("run_id") or "") != run_id:
        raise LearningWorkflowTransitionError("run_id does not match previous_state")
    if state.get("stage_order") != list(LEARNING_WORKFLOW_STAGES):
        raise LearningWorkflowTransitionError("stage_order does not match authoritative order")
    stages = state.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(LEARNING_WORKFLOW_STAGES):
        raise LearningWorkflowTransitionError("workflow stages are incomplete")
    if not isinstance(state.get("events"), list):
        raise LearningWorkflowTransitionError("workflow events must be a list")
    if not isinstance(state.get("revision"), int) or state["revision"] < 0:
        raise LearningWorkflowTransitionError("workflow revision is invalid")
    replayed = _initial_state(run_id)
    for expected_revision, event in enumerate(state["events"], start=1):
        if not isinstance(event, dict):
            raise LearningWorkflowTransitionError("workflow event must be an object")
        if event.get("revision") != expected_revision:
            raise LearningWorkflowTransitionError("workflow event revision is invalid")
        replayed = _apply_transition(
            replayed,
            stage=str(event.get("stage") or ""),
            outcome=str(event.get("outcome") or ""),
            reason=str(event.get("reason") or ""),
            evidence_refs=event.get("evidence_refs") if isinstance(event.get("evidence_refs"), dict) else {},
        )
    if replayed != state:
        raise LearningWorkflowTransitionError("previous_state does not match event history")
    return state


def _validate_transition_evidence(
    *,
    stage: str,
    outcome: str,
    reason: str,
    evidence_refs: dict[str, Any],
) -> None:
    if outcome in _TERMINAL_OUTCOMES and not str(reason or "").strip():
        raise LearningWorkflowTransitionError(f"{outcome} requires a reason")
    if outcome != "completed":
        return
    required_fields = LEARNING_WORKFLOW_COMPLETION_EVIDENCE[stage]
    missing_fields = [
        field
        for field in required_fields
        if not isinstance(evidence_refs.get(field), str)
        or not str(evidence_refs.get(field) or "").strip()
    ]
    if missing_fields:
        raise LearningWorkflowTransitionError(
            f"{stage} completed requires evidence: {', '.join(missing_fields)}"
        )
