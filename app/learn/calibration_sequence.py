from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Callable


LEARNING_CALIBRATION_SEQUENCE_REQUEST_CONTRACT_VERSION = (
    "learning_calibration_sequence_request_v1"
)
LEARNING_CALIBRATION_SEQUENCE_RESULT_CONTRACT_VERSION = (
    "learning_calibration_sequence_result_v1"
)
_RETRYABLE_ABORT_REASONS = {"request_timeout", "model_busy"}


class LearningCalibrationSequenceError(ValueError):
    """精准校准批次序列请求不完整或不一致。"""


def run_learning_calibration_sequence(
    payload: dict[str, Any],
    *,
    locate_runner: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    profile_loader: Callable[[str, str | None], dict[str, Any]] | None = None,
    resource_preflight_builder: Callable[
        [dict[str, Any]], dict[str, Any]
    ]
    | None = None,
    model_status_checker: Callable[
        [dict[str, Any]], dict[str, Any]
    ]
    | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """在一个后端 worker 内完成所有 VISTA 校准批次。"""

    request = _validated_request(payload)
    locate = locate_runner or _run_locate_target
    load_profile = profile_loader or _load_profile
    build_preflight = resource_preflight_builder or _build_resource_preflight
    check_status = model_status_checker or _check_model_status

    profile = load_profile("locate", request["profile_id"])
    candidate_count = request["candidate_count"]
    source_revision = request["calibration_source_revision"]
    maximum_batch_size = request["maximum_batch_size"]
    maximum_transient_attempts = request["maximum_transient_recovery_attempts"]
    maximum_batches = candidate_count + 2 + maximum_transient_attempts
    base_payload = request["locate_payload"]

    resume_results: list[dict[str, Any]] = []
    previous_completed_signature = ""
    transient_recovery_attempts = 0
    latest_batch: dict[str, Any] = {}

    for batch_index in range(1, maximum_batches + 1):
        preflight = build_preflight(profile)
        if (
            str(preflight.get("resource_mode") or "") == "critical"
            or preflight.get("model_launch_allowed") is False
        ):
            return _failure_response(
                "calibration_batch_resource_blocked",
                batch_count=batch_index - 1,
                final_numbering_revision=source_revision,
                remaining_count=max(0, candidate_count - len(resume_results)),
                resource_preflight=preflight,
            )

        recommended_batch_size = _positive_int(
            preflight.get("recommended_batch_size"),
            default=2,
        )
        active_batch_size = min(maximum_batch_size, recommended_batch_size)
        locate_payload = deepcopy(base_payload)
        metadata = (
            deepcopy(locate_payload.get("metadata"))
            if isinstance(locate_payload.get("metadata"), dict)
            else {}
        )
        metadata["learn_vista_coordinate_validation"] = {
            "enabled": True,
            "max_targets": "all",
            "batch_size": active_batch_size,
            "resume_results": deepcopy(resume_results),
            "resume_revision": source_revision,
            "stop_on_failure": False,
            "use_numbered_overlay": True,
        }
        locate_payload["metadata"] = metadata

        response = locate(locate_payload)
        if not isinstance(response, dict):
            return _failure_response(
                "calibration_worker_response_invalid",
                batch_count=batch_index,
                final_numbering_revision=source_revision,
            )
        if response.get("success") is not True:
            return deepcopy(response)

        validation = _calibration_validation(response)
        if not validation:
            return _failure_response(
                "calibration_validation_missing",
                batch_count=batch_index,
                final_numbering_revision=source_revision,
            )
        latest_batch = (
            deepcopy(validation.get("batch"))
            if isinstance(validation.get("batch"), dict)
            else {}
        )
        resume_results = _completed_resume_results(validation)
        completed_ids = _completed_candidate_ids(latest_batch, resume_results)
        completed_signature = "|".join(completed_ids)
        remaining_count = _non_negative_int(
            latest_batch.get("remaining_count"),
            default=max(0, candidate_count - len(completed_ids)),
        )
        resumable = latest_batch.get("resumable") is True
        abort_reason = str(validation.get("abort_reason") or "").strip()

        if not resumable:
            if remaining_count != 0:
                return _failure_response(
                    "calibration_terminal_batch_incomplete",
                    batch_count=batch_index,
                    final_numbering_revision=source_revision,
                    remaining_count=remaining_count,
                    batch=latest_batch,
                )
            return _attach_sequence_result(
                response,
                batch_count=batch_index,
                completed_count=len(completed_ids),
                remaining_count=0,
                transient_recovery_attempts=transient_recovery_attempts,
                final_numbering_revision=source_revision,
                artifact_inputs=_calibration_artifact_inputs(
                    response,
                    locate_payload=base_payload,
                ),
            )

        if abort_reason in _RETRYABLE_ABORT_REASONS:
            transient_recovery_attempts += 1
            if transient_recovery_attempts > maximum_transient_attempts:
                return _failure_response(
                    "calibration_transient_retry_limit_exceeded",
                    batch_count=batch_index,
                    final_numbering_revision=source_revision,
                    remaining_count=remaining_count,
                    abort_reason=abort_reason,
                    batch=latest_batch,
                )
            idle_status = _wait_for_model_idle(
                profile,
                check_status=check_status,
                sleep=sleep,
                maximum_checks=request["model_idle_maximum_checks"],
                poll_seconds=request["model_idle_poll_seconds"],
            )
            if idle_status.get("ready") is not True:
                return _failure_response(
                    "calibration_model_idle_wait_failed",
                    batch_count=batch_index,
                    final_numbering_revision=source_revision,
                    remaining_count=remaining_count,
                    abort_reason=abort_reason,
                    model_idle_wait=idle_status,
                    batch=latest_batch,
                )
            previous_completed_signature = (
                completed_signature or previous_completed_signature
            )
            continue

        if (
            not completed_signature
            or completed_signature == previous_completed_signature
        ):
            return _failure_response(
                "calibration_batch_no_progress",
                batch_count=batch_index,
                final_numbering_revision=source_revision,
                remaining_count=remaining_count,
                batch=latest_batch,
            )
        previous_completed_signature = completed_signature

    return _failure_response(
        "calibration_batch_limit_exceeded",
        batch_count=maximum_batches,
        final_numbering_revision=source_revision,
        remaining_count=_non_negative_int(
            latest_batch.get("remaining_count"),
            default=max(0, candidate_count - len(resume_results)),
        ),
        batch=latest_batch,
    )


def _validated_request(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LearningCalibrationSequenceError(
            "calibration sequence payload must be an object"
        )
    contract_version = str(payload.get("contract_version") or "").strip()
    if contract_version != LEARNING_CALIBRATION_SEQUENCE_REQUEST_CONTRACT_VERSION:
        raise LearningCalibrationSequenceError(
            "unsupported calibration sequence request contract"
        )
    locate_payload = payload.get("locate_payload")
    if not isinstance(locate_payload, dict):
        raise LearningCalibrationSequenceError("locate_payload is required")
    if not str(locate_payload.get("goal") or "").strip():
        raise LearningCalibrationSequenceError(
            "locate_payload goal is required"
        )
    metadata = locate_payload.get("metadata")
    if not isinstance(metadata, dict) or metadata.get("learn_all_targets") is not True:
        raise LearningCalibrationSequenceError(
            "locate_payload must enable learn_all_targets"
        )
    if locate_payload.get("dry_run") is not True:
        raise LearningCalibrationSequenceError(
            "calibration sequence requires dry_run=true"
        )
    candidate_count = _positive_int(payload.get("candidate_count"), default=0)
    if candidate_count <= 0:
        raise LearningCalibrationSequenceError("candidate_count must be positive")
    source_revision = str(
        payload.get("calibration_source_revision") or ""
    ).strip()
    if not source_revision:
        raise LearningCalibrationSequenceError(
            "calibration_source_revision is required"
        )
    return {
        "profile_id": str(payload.get("profile_id") or "").strip() or None,
        "candidate_count": candidate_count,
        "calibration_source_revision": source_revision,
        "locate_payload": deepcopy(locate_payload),
        "maximum_batch_size": min(
            32,
            _positive_int(payload.get("maximum_batch_size"), default=8),
        ),
        "maximum_transient_recovery_attempts": min(
            10,
            _non_negative_int(
                payload.get("maximum_transient_recovery_attempts"),
                default=3,
            ),
        ),
        "model_idle_maximum_checks": min(
            600,
            _positive_int(payload.get("model_idle_maximum_checks"), default=180),
        ),
        "model_idle_poll_seconds": max(
            0.05,
            min(10.0, _positive_float(
                payload.get("model_idle_poll_seconds"),
                default=1.0,
            )),
        ),
    }


def _run_locate_target(payload: dict[str, Any]) -> dict[str, Any]:
    from app.api.models.request import VisionLocateTargetRequestModel
    from app.api.vision import locate_target

    response = locate_target(VisionLocateTargetRequestModel.model_validate(payload))
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if isinstance(response, dict):
        return deepcopy(response)
    raise LearningCalibrationSequenceError(
        f"locate runner returned unsupported response: {type(response).__name__}"
    )


def _load_profile(stage: str, profile_id: str | None) -> dict[str, Any]:
    from app.core.model_server import profile_for_stage

    return profile_for_stage(stage, profile_id)


def _build_resource_preflight(profile: dict[str, Any]) -> dict[str, Any]:
    from app.core.gpu_resources import build_model_resource_preflight

    return build_model_resource_preflight(profile)


def _check_model_status(profile: dict[str, Any]) -> dict[str, Any]:
    from app.core.model_server import check_model_server

    return check_model_server(profile, timeout=1.0)


def _wait_for_model_idle(
    profile: dict[str, Any],
    *,
    check_status: Callable[[dict[str, Any]], dict[str, Any]],
    sleep: Callable[[float], None],
    maximum_checks: int,
    poll_seconds: float,
) -> dict[str, Any]:
    last_status: dict[str, Any] = {}
    for check_index in range(1, maximum_checks + 1):
        last_status = check_status(profile)
        status = str(last_status.get("status") or "").strip().casefold()
        if status == "running":
            return {
                "ready": True,
                "checks": check_index,
                "status": status,
            }
        if status not in {"busy", "loading", "starting"}:
            return {
                "ready": False,
                "checks": check_index,
                "status": status or "unknown",
                "model_status": deepcopy(last_status),
            }
        if check_index < maximum_checks:
            sleep(poll_seconds)
    return {
        "ready": False,
        "checks": maximum_checks,
        "status": str(last_status.get("status") or "timeout"),
        "reason": "timeout",
        "model_status": deepcopy(last_status),
    }


def _calibration_validation(response: dict[str, Any]) -> dict[str, Any]:
    result = _response_result(response)
    learn_all_targets = result.get("learn_all_targets")
    if isinstance(learn_all_targets, dict):
        validation = learn_all_targets.get("vista_coordinate_validation")
        if isinstance(validation, dict):
            return deepcopy(validation)
    validation = result.get("vista_coordinate_validation")
    return deepcopy(validation) if isinstance(validation, dict) else {}


def _response_result(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, dict):
        result = data.get("result")
        if isinstance(result, dict):
            return result
        return data
    result = response.get("result")
    return result if isinstance(result, dict) else response


def _calibration_artifact_inputs(
    response: dict[str, Any],
    *,
    locate_payload: dict[str, Any],
) -> dict[str, str]:
    result = _response_result(response)
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    metadata = (
        locate_payload.get("metadata")
        if isinstance(locate_payload.get("metadata"), dict)
        else {}
    )
    learn_targets = (
        result.get("learn_all_targets")
        if isinstance(result.get("learn_all_targets"), dict)
        else {}
    )
    return {
        "trace_path": _first_text(
            data.get("trace_path"),
            data.get("execute_step_trace_path"),
            result.get("trace_path"),
            result.get("execute_step_trace_path"),
        ),
        "source_image_path": _first_text(locate_payload.get("image_path")),
        "numbering_report_path": _first_text(
            metadata.get("two_stage_report_path")
        ),
        "overlay_path": _first_text(learn_targets.get("overlay_path")),
    }


def _attach_sequence_result(
    response: dict[str, Any],
    *,
    batch_count: int,
    completed_count: int,
    remaining_count: int,
    transient_recovery_attempts: int,
    final_numbering_revision: str,
    artifact_inputs: dict[str, str],
) -> dict[str, Any]:
    normalized = deepcopy(response)
    result = _response_result(normalized)
    result["calibration_sequence"] = {
        "contract_version": LEARNING_CALIBRATION_SEQUENCE_RESULT_CONTRACT_VERSION,
        "status": "completed",
        "batch_count": batch_count,
        "completed_count": completed_count,
        "remaining_count": remaining_count,
        "transient_recovery_attempts": transient_recovery_attempts,
        "final_numbering_revision": final_numbering_revision,
        "artifact_inputs": deepcopy(artifact_inputs),
        "no_live_click_authorization": True,
        "dry_run": True,
    }
    return normalized


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _completed_resume_results(
    validation: dict[str, Any],
) -> list[dict[str, Any]]:
    results = validation.get("results")
    if not isinstance(results, list):
        return []
    completed: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        if str(item.get("failure_category") or "").strip() in (
            _RETRYABLE_ABORT_REASONS
        ):
            continue
        precise_evidence = (
            item.get("precise_locator_evidence")
            if isinstance(item.get("precise_locator_evidence"), dict)
            else {}
        )
        completed.append(
            {
                "contract_version": item.get("contract_version"),
                "status": item.get("status"),
                "failure_category": item.get("failure_category"),
                "candidate_id": item.get("candidate_id"),
                "final_numbering_revision": item.get(
                    "final_numbering_revision"
                ),
                "label": item.get("label"),
                "role": item.get("role"),
                "bbox": deepcopy(item.get("bbox")),
                "previous_click_point": deepcopy(
                    item.get("previous_click_point")
                ),
                "vista_point": deepcopy(item.get("vista_point")),
                "vista_point_inside_bbox": item.get(
                    "vista_point_inside_bbox"
                ),
                "vista_point_inside_selected_bbox": item.get(
                    "vista_point_inside_selected_bbox"
                ),
                "updated_click_point": deepcopy(
                    item.get("updated_click_point")
                ),
                "precise_locator_evidence": {
                    "selected_candidate": deepcopy(
                        precise_evidence.get("selected_candidate")
                    ),
                    "dry_run_gate": deepcopy(
                        precise_evidence.get("dry_run_gate")
                    ),
                    "evidence_availability": precise_evidence.get(
                        "evidence_availability"
                    ),
                },
            }
        )
    return completed


def _completed_candidate_ids(
    batch: dict[str, Any],
    resume_results: list[dict[str, Any]],
) -> list[str]:
    values = batch.get("completed_candidate_ids")
    if isinstance(values, list):
        return [
            str(item).strip()
            for item in values
            if str(item or "").strip()
        ]
    return [
        str(item.get("candidate_id") or "").strip()
        for item in resume_results
        if str(item.get("candidate_id") or "").strip()
    ]


def _failure_response(
    failure_category: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "success": False,
        "message": failure_category,
        "data": {
            "contract_version": LEARNING_CALIBRATION_SEQUENCE_RESULT_CONTRACT_VERSION,
            "failure_category": failure_category,
            **deepcopy(details),
            "no_live_click_authorization": True,
            "dry_run": True,
        },
        "error": {
            "code": failure_category,
            "details": failure_category,
        },
    }


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _non_negative_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _positive_float(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
