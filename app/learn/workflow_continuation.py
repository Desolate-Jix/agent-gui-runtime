from __future__ import annotations

from copy import deepcopy
from typing import Any


LEARNING_STAGE_WORKER_CONTINUATION_CONTRACT_VERSION = (
    "learning_stage_worker_continuation_v1"
)

_TERMINAL_TASK_STAGE = {
    "panel_learning_two_stage_understanding": "numbered_map",
    "panel_learning_calibration_sequence": "precise_calibration",
    "panel_learning_model_review_repair": "review_repair",
}
_SCREEN_UNDERSTANDING_TASKS = {
    "vision_observe_screen",
    "panel_learning_recognition_trial",
}


class LearningStageWorkerContinuationError(ValueError):
    """已接纳的 worker 结果不能按声明的阶段继续。"""


def interpret_learning_stage_worker_result(
    *,
    stage: str,
    task_kind: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    """将已接纳结果解释为中间结果或可终结的阶段决策。"""

    normalized_stage = _required_text(stage, "stage")
    normalized_task_kind = _required_text(task_kind, "task_kind")
    if not isinstance(response, dict):
        raise LearningStageWorkerContinuationError(
            "adopted worker response must be an object"
        )

    if (
        normalized_stage == "screen_understanding"
        and normalized_task_kind in _SCREEN_UNDERSTANDING_TASKS
    ):
        if response.get("success") is not True:
            return _decision(
                stage=normalized_stage,
                task_kind=normalized_task_kind,
                stage_finished=True,
                continuation_status="terminal_result",
                outcome="failed",
                reason=_response_failure_reason(response),
                evidence_refs={},
            )
        result = _response_result(response)
        if normalized_task_kind == "vision_observe_screen":
            return _screen_observe_decision(result)
        return _screen_trial_decision(result)

    if (
        normalized_stage == "fusion"
        and normalized_task_kind == "panel_learning_recognition_trial"
    ):
        if response.get("success") is not True:
            return _decision(
                stage=normalized_stage,
                task_kind=normalized_task_kind,
                stage_finished=True,
                continuation_status="terminal_result",
                outcome="failed",
                reason=_response_failure_reason(response),
                evidence_refs={},
            )
        return _fusion_trial_decision(_response_result(response))

    terminal_stage = _TERMINAL_TASK_STAGE.get(normalized_task_kind)
    if terminal_stage is None:
        return _decision(
            stage=normalized_stage,
            task_kind=normalized_task_kind,
            stage_finished=False,
            continuation_status="intermediate_result",
            outcome=None,
            reason="worker result requires another stage-specific backend step",
            evidence_refs={},
        )
    if terminal_stage != normalized_stage:
        raise LearningStageWorkerContinuationError(
            "terminal worker task does not belong to the declared stage"
        )

    if response.get("success") is not True:
        return _decision(
            stage=normalized_stage,
            task_kind=normalized_task_kind,
            stage_finished=True,
            continuation_status="terminal_result",
            outcome="failed",
            reason=_response_failure_reason(response),
            evidence_refs={},
        )

    result = _response_result(response)
    if normalized_task_kind == "panel_learning_two_stage_understanding":
        return _numbered_map_decision(result)
    if normalized_task_kind == "panel_learning_calibration_sequence":
        return _precise_calibration_decision(result)
    return _review_repair_decision(result)


def _screen_observe_decision(result: dict[str, Any]) -> dict[str, Any]:
    image_path = _first_text(
        result.get("image_path"),
        _nested(result, "capture", "image_path"),
        _nested(result, "live_capture", "image_path"),
        _nested(result, "operation_context", "capture_id"),
    )
    if not image_path:
        return _decision(
            stage="screen_understanding",
            task_kind="vision_observe_screen",
            stage_finished=True,
            continuation_status="terminal_result",
            outcome="failed",
            reason="observe result is missing immutable source image identity",
            evidence_refs={},
        )

    screen_map = (
        deepcopy(result.get("screen_map"))
        if isinstance(result.get("screen_map"), dict)
        else {}
    )
    screen_size = _first_dict(
        result.get("screen_size"),
        result.get("viewport_size"),
        result.get("image_size"),
        _nested(result, "capture", "image_size"),
        _nested(result, "live_capture", "image_size"),
        _nested(result, "operation_context", "viewport_size"),
    )
    screen_summary = _first_text(
        result.get("screen_summary"),
        _nested(result, "screen_map", "summary", "screen_summary"),
        _nested(result, "screen_reading", "screen_summary"),
    )
    interface_classification = (
        deepcopy(result.get("interface_classification"))
        if isinstance(result.get("interface_classification"), dict)
        else {}
    )
    trace_path = _first_text(result.get("trace_path"))
    app_name = _first_text(
        result.get("app_name"),
        _nested(result, "screen_map", "app_id"),
        "unknown_app",
    )
    state_hint = _first_text(
        result.get("suggested_state_hint"),
        result.get("state_guess"),
        _nested(result, "screen_map", "state_id"),
    )
    evidence_count = _screen_map_evidence_count(screen_map)
    next_worker = {
        "task_kind": "panel_learning_recognition_trial",
        "payload": {
            "app_name": app_name,
            "state_hint": state_hint,
            "summary": (
                screen_summary
                or "learn a reusable UI workflow template from this screen"
            ),
            "observation_evidence": {
                "contract_version": "panel_learning_draft_observation_evidence_v1",
                "evidence_source": "backend_adopted_observe_result",
                "evidence_quality": (
                    "screen_map_available_no_recent_learn_deep"
                    if evidence_count > 0
                    else "screenshot_only_no_recent_learn_deep"
                ),
                "current_image_path": image_path,
                "screen_size": screen_size,
                "screen_summary": screen_summary,
                "interface_classification": interface_classification,
                "screen_map": screen_map,
                "model_roles": {
                    "screen_understanding": {
                        "stage": "Learn Fast",
                        "trace_path": trace_path,
                    },
                    "coordinate_calibration": {
                        "stage": "Learn Deep",
                        "status": "not_run",
                        "trace_path": "",
                    },
                },
                "calibrated_targets": [],
                "review_boxes": [],
                "learn_all_targets_summary": {
                    "status": "",
                    "target_count": 0,
                    "calibration_target_count": 0,
                    "validated_count": 0,
                    "coordinate_calibration_status": "not_run",
                },
                "no_click_authorization": True,
                "execute_binding_enabled": False,
            },
            "two_stage_report_path": None,
        },
    }
    decision = _decision(
        stage="screen_understanding",
        task_kind="vision_observe_screen",
        stage_finished=False,
        continuation_status="next_worker_ready",
        outcome=None,
        reason="observe result accepted; recognition trial worker is required",
        evidence_refs={
            "image_path": image_path,
            "trace_path": trace_path,
        },
    )
    decision["next_worker"] = next_worker
    return decision


def _screen_trial_decision(result: dict[str, Any]) -> dict[str, Any]:
    trial_path = _first_text(result.get("trial_path"))
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    draft_counts = (
        summary.get("draft_section_counts")
        if isinstance(summary.get("draft_section_counts"), dict)
        else {}
    )
    screen_inventory_count = _non_negative_int(
        summary.get("screen_inventory_count")
    )
    region_count = _non_negative_int(draft_counts.get("regions"))
    usable = bool(trial_path) and (
        screen_inventory_count > 0 or region_count > 0
    )
    return _decision(
        stage="screen_understanding",
        task_kind="panel_learning_recognition_trial",
        stage_finished=True,
        continuation_status="terminal_result",
        outcome="completed" if usable else "safe_stopped",
        reason=(
            "screen-understanding draft contains usable inventory"
            if usable
            else (
                "safe stop · no usable screen inventory "
                f"(inventory={screen_inventory_count}, regions={region_count})"
            )
        ),
        evidence_refs={"trial_path": trial_path},
    )


def _fusion_trial_decision(result: dict[str, Any]) -> dict[str, Any]:
    trial_path = _first_text(result.get("trial_path"))
    usable = bool(trial_path)
    return _decision(
        stage="fusion",
        task_kind="panel_learning_recognition_trial",
        stage_finished=True,
        continuation_status="terminal_result",
        outcome="completed" if usable else "safe_stopped",
        reason=(
            "fused learning trial artifact ready"
            if usable
            else "safe stop · fused learning trial artifact is missing"
        ),
        evidence_refs={"trial_path": trial_path},
    )


def _numbered_map_decision(result: dict[str, Any]) -> dict[str, Any]:
    gate = result.get("stage1_gate")
    gate_status = (
        str(gate.get("status") or "").strip()
        if isinstance(gate, dict)
        else ""
    )
    if not gate_status:
        gate_status = str(result.get("status") or "").strip()
    allowed = (
        gate_status == "passed"
        and result.get("stage2_numbering_skipped") is not True
    )
    overlay_path = _first_text(
        result.get("compiled_overlay_path"),
        _nested(result, "fusion", "compiled_overlay_path"),
        result.get("coordinate_overlay_path"),
        result.get("full_screen_understanding_overlay_path"),
        _nested(result, "fusion", "full_screen_understanding_overlay_path"),
        _nested(result, "learn_all_targets", "overlay_path"),
        _nested(result, "summary", "overlay_path"),
    )
    return _decision(
        stage="numbered_map",
        task_kind="panel_learning_two_stage_understanding",
        stage_finished=True,
        continuation_status="terminal_result",
        outcome="completed" if allowed else "safe_stopped",
        reason=(
            "numbered selection map ready"
            if allowed
            else f"Stage1 gate blocked Stage2 · {gate_status or 'unknown'}"
        ),
        evidence_refs={
            "report_path": _first_text(result.get("report_path")),
            "overlay_path": overlay_path,
        },
    )


def _precise_calibration_decision(result: dict[str, Any]) -> dict[str, Any]:
    sequence = (
        result.get("calibration_sequence")
        if isinstance(result.get("calibration_sequence"), dict)
        else {}
    )
    if (
        sequence.get("contract_version")
        != "learning_calibration_sequence_result_v1"
        or str(sequence.get("status") or "").strip() != "completed"
        or not _is_non_negative_int(sequence.get("remaining_count"))
    ):
        return _decision(
            stage="precise_calibration",
            task_kind="panel_learning_calibration_sequence",
            stage_finished=True,
            continuation_status="terminal_result",
            outcome="failed",
            reason="calibration sequence result contract is incomplete",
            evidence_refs={},
        )

    learn_targets = (
        result.get("learn_all_targets")
        if isinstance(result.get("learn_all_targets"), dict)
        else {}
    )
    validation = (
        learn_targets.get("vista_coordinate_validation")
        if isinstance(learn_targets.get("vista_coordinate_validation"), dict)
        else {}
    )
    batch = (
        validation.get("batch")
        if isinstance(validation.get("batch"), dict)
        else {}
    )
    blocked = (
        validation.get("batch_aborted") is True
        or str(validation.get("status") or "").strip() == "blocked"
        or str(learn_targets.get("status") or "").strip() == "blocked"
        or str(result.get("location_status") or "").strip()
        == "learn_calibration_blocked"
    )
    overlay_path = _first_text(
        learn_targets.get("overlay_path"),
        _nested(
            result,
            "calibration_sequence",
            "artifact_inputs",
            "overlay_path",
        ),
    )
    if blocked:
        return _decision(
            stage="precise_calibration",
            task_kind="panel_learning_calibration_sequence",
            stage_finished=True,
            continuation_status="terminal_result",
            outcome="safe_stopped",
            reason="safe stop · calibration evidence was blocked",
            evidence_refs={"overlay_path": overlay_path},
        )

    remaining_count = int(sequence["remaining_count"])
    resumable = batch.get("resumable") is True
    if remaining_count != 0 or resumable:
        return _decision(
            stage="precise_calibration",
            task_kind="panel_learning_calibration_sequence",
            stage_finished=True,
            continuation_status="terminal_result",
            outcome="failed",
            reason=(
                "calibration sequence terminated incomplete · "
                f"remaining_count={remaining_count}, "
                f"resumable={str(resumable).lower()}"
            ),
            evidence_refs={},
        )

    artifact_inputs = (
        deepcopy(sequence.get("artifact_inputs"))
        if isinstance(sequence.get("artifact_inputs"), dict)
        else {}
    )
    decision = _decision(
        stage="precise_calibration",
        task_kind="panel_learning_calibration_sequence",
        stage_finished=True,
        continuation_status="terminal_result",
        outcome="completed",
        reason="precise calibration sequence completed",
        evidence_refs={"overlay_path": overlay_path},
    )
    decision["artifact_request"] = artifact_inputs
    return decision


def _review_repair_decision(result: dict[str, Any]) -> dict[str, Any]:
    integrity_gate = result.get("integrity_gate")
    integrity_passed = (
        integrity_gate.get("passed") is True
        if isinstance(integrity_gate, dict)
        else False
    )
    report_path = _first_text(result.get("final_stage2_report_path"))
    revision = _first_text(result.get("final_numbering_revision"))
    allowed = (
        result.get("calibration_permission") is True
        and integrity_passed
        and bool(report_path)
        and bool(revision)
    )
    overlay_path = _first_text(
        result.get("final_repaired_overlay_path"),
        _nested(result, "three_image_evidence", "final_repaired_fusion"),
    )
    failure_categories = (
        integrity_gate.get("failure_categories")
        if isinstance(integrity_gate, dict)
        else None
    )
    failure_reason = (
        ", ".join(str(item) for item in failure_categories if str(item).strip())
        if isinstance(failure_categories, list)
        else ""
    )
    return _decision(
        stage="review_repair",
        task_kind="panel_learning_model_review_repair",
        stage_finished=True,
        continuation_status="terminal_result",
        outcome="completed" if allowed else "safe_stopped",
        reason=(
            "model review / repair integrity gate passed"
            if allowed
            else f"safe stop · {failure_reason or 'review requires human review'}"
        ),
        evidence_refs={
            "final_stage2_report_path": report_path,
            "final_overlay_path": overlay_path,
            "final_numbering_revision": revision,
        },
    )


def _decision(
    *,
    stage: str,
    task_kind: str,
    stage_finished: bool,
    continuation_status: str,
    outcome: str | None,
    reason: str,
    evidence_refs: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": LEARNING_STAGE_WORKER_CONTINUATION_CONTRACT_VERSION,
        "stage": stage,
        "task_kind": task_kind,
        "stage_finished": stage_finished,
        "continuation_status": continuation_status,
        "outcome": outcome,
        "reason": reason,
        "evidence_refs": deepcopy(evidence_refs),
    }


def _response_result(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, dict):
        result = data.get("result")
        if isinstance(result, dict) and result:
            return deepcopy(result)
        if data:
            return deepcopy(data)
    direct_result = response.get("result")
    if isinstance(direct_result, dict) and direct_result:
        return deepcopy(direct_result)
    return deepcopy(response)


def _response_failure_reason(response: dict[str, Any]) -> str:
    message = _first_text(response.get("message"))
    error = response.get("error")
    if isinstance(error, dict):
        details = _first_text(error.get("details"), error.get("message"))
    else:
        details = _first_text(error)
    return f"worker response failed · {message or details or 'unknown error'}"


def _nested(source: dict[str, Any], *path: str) -> Any:
    current: Any = source
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _first_dict(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return deepcopy(value)
    return {}


def _screen_map_evidence_count(screen_map: dict[str, Any]) -> int:
    total = 0
    for key in ("candidates", "regions", "sections", "inventory"):
        value = screen_map.get(key)
        if isinstance(value, list):
            total += len(value)
    return total


def _is_non_negative_int(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _first_text(*values: Any) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise LearningStageWorkerContinuationError(f"{field} is required")
    return normalized
