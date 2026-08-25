from __future__ import annotations

import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from app.learn.hybrid.vista_refinement import (
    build_vista_requests,
    validate_vista_proposal,
)
from app.learn.recognition.uei.canonical import canonical_json_bytes


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
    cancellation_event: Any | None = None,
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
    hybrid_vista_requests = request["hybrid_vista_requests"]
    hybrid_authoritative_context = request.get("hybrid_authoritative_context")
    hybrid_request_by_id = {
        item["candidate_id"]: item for item in hybrid_vista_requests
    }

    resume_results: list[dict[str, Any]] = []
    previous_completed_signature = ""
    transient_recovery_attempts = 0
    latest_batch: dict[str, Any] = {}

    for batch_index in range(1, maximum_batches + 1):
        if _cancellation_requested(cancellation_event):
            return _failure_response(
                "calibration_cancelled",
                batch_count=batch_index - 1,
                final_numbering_revision=source_revision,
                remaining_count=max(0, candidate_count - len(resume_results)),
                completed_results=resume_results,
            )
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
        if hybrid_vista_requests:
            metadata["learn_hybrid_vista_requests"] = deepcopy(
                hybrid_vista_requests
            )
            metadata["learn_hybrid_vista_authoritative_context"] = deepcopy(
                hybrid_authoritative_context
            )
            metadata["final_numbering_revision"] = source_revision
        locate_payload["metadata"] = metadata

        if _cancellation_requested(cancellation_event):
            return _failure_response(
                "calibration_cancelled",
                batch_count=batch_index - 1,
                final_numbering_revision=source_revision,
                remaining_count=max(0, candidate_count - len(resume_results)),
                completed_results=resume_results,
            )
        if (
            cancellation_event is not None
            and hasattr(cancellation_event, "run_if_not_cancelled")
        ):
            allowed, response = cancellation_event.run_if_not_cancelled(
                "vista_batch_acquisition",
                lambda: locate(locate_payload),
            )
            if not allowed:
                return _failure_response(
                    "calibration_cancelled",
                    batch_count=batch_index - 1,
                    final_numbering_revision=source_revision,
                    remaining_count=max(
                        0,
                        candidate_count - len(resume_results),
                    ),
                    completed_results=resume_results,
                )
        else:
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
        if hybrid_request_by_id:
            lineage_error = _hybrid_resume_lineage_error(
                resume_results,
                request_by_id=hybrid_request_by_id,
                source_revision=source_revision,
            )
            if lineage_error:
                return _failure_response(
                    "calibration_hybrid_resume_lineage_mismatch",
                    batch_count=batch_index,
                    final_numbering_revision=source_revision,
                    remaining_count=max(0, candidate_count - len(resume_results)),
                    lineage_error=lineage_error,
                )
            coverage_error = _hybrid_batch_coverage_error(
                latest_batch,
                resume_results,
                request_by_id=hybrid_request_by_id,
            )
            if coverage_error:
                return _failure_response(
                    "calibration_hybrid_batch_coverage_mismatch",
                    batch_count=batch_index,
                    final_numbering_revision=source_revision,
                    coverage_error=coverage_error,
                )
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
                hybrid_vista_requests=hybrid_vista_requests,
                hybrid_vista_results=resume_results,
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
    learning_pipeline_mode = str(
        payload.get("learning_pipeline_mode") or "incumbent"
    ).strip()
    if learning_pipeline_mode not in {"incumbent", "hybrid_v1_1"}:
        raise LearningCalibrationSequenceError(
            "learning_pipeline_mode must be incumbent or hybrid_v1_1"
        )
    hybrid_vista_requests: list[dict[str, Any]] = []
    hybrid_authoritative_context: dict[str, Any] | None = None
    if learning_pipeline_mode == "hybrid_v1_1":
        try:
            from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle

            bundle = load_and_verify_hybrid_capture_bundle(
                project_root=Path(str(payload.get("project_root") or "")),
                bundle_ref=payload.get("hybrid_capture_bundle_ref"),
                expected_run_id=str(payload.get("run_id") or ""),
                expected_workflow_revision=int(payload.get("workflow_revision")),
            )
            if canonical_json_bytes(bundle) != canonical_json_bytes(payload.get("capture_bundle")):
                raise ValueError("capture bundle does not match authoritative artifact store")
            hybrid_authoritative_context = {
                "fusion_result": deepcopy(payload.get("hybrid_fusion_result")),
                "capture_bundle": deepcopy(bundle),
                "omni_inventory": deepcopy(payload.get("omni_inventory")),
                "qwen_bindings": deepcopy(payload.get("qwen_bindings")),
                "qwen_cleanup_receipt": deepcopy(payload.get("qwen_cleanup_receipt")),
                "workflow_revision": int(payload.get("workflow_revision")),
                "project_root": str(payload.get("project_root") or ""),
                "hybrid_capture_bundle_ref": deepcopy(payload.get("hybrid_capture_bundle_ref")),
                "run_id": str(payload.get("run_id") or ""),
            }
            hybrid_vista_requests = build_vista_requests(
                payload.get("hybrid_fusion_result"),
                bundle,
                omni_inventory=payload.get("omni_inventory"),
                qwen_bindings=payload.get("qwen_bindings"),
                qwen_cleanup_receipt=payload.get("qwen_cleanup_receipt"),
                expected_workflow_revision=int(payload.get("workflow_revision")),
            )
        except (TypeError, ValueError) as exc:
            raise LearningCalibrationSequenceError(
                f"Hybrid VISTA request lineage is invalid: {exc}"
            ) from exc
        if len(hybrid_vista_requests) != candidate_count:
            raise LearningCalibrationSequenceError(
                "Hybrid candidate_count must equal exact BOUND request count"
            )
        if any(
            item.get("source_revision") != source_revision
            for item in hybrid_vista_requests
        ):
            raise LearningCalibrationSequenceError(
                "Hybrid calibration source revision does not match fusion"
            )
    return {
        "learning_pipeline_mode": learning_pipeline_mode,
        "profile_id": str(payload.get("profile_id") or "").strip() or None,
        "candidate_count": candidate_count,
        "calibration_source_revision": source_revision,
        "locate_payload": deepcopy(locate_payload),
        "hybrid_vista_requests": hybrid_vista_requests,
        "hybrid_authoritative_context": hybrid_authoritative_context,
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
    hybrid_vista_requests: list[dict[str, Any]] | None = None,
    hybrid_vista_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized = deepcopy(response)
    result = _response_result(normalized)
    sequence = {
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
    if hybrid_vista_requests:
        sequence.update(
            {
                "hybrid_vista_requests": deepcopy(hybrid_vista_requests),
                "hybrid_vista_results": deepcopy(hybrid_vista_results or []),
                "qwen_cleanup_receipt": deepcopy(
                    hybrid_vista_requests[0]["qwen_cleanup_receipt"]
                ),
                "review_projection_required": True,
            }
        )
    result["calibration_sequence"] = sequence
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
        normalized = {
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
        if isinstance(item.get("hybrid_vista_request"), dict):
            normalized["hybrid_vista_request"] = deepcopy(
                item["hybrid_vista_request"]
            )
        if isinstance(item.get("hybrid_vista_proposal"), dict):
            normalized["hybrid_vista_proposal"] = deepcopy(
                item["hybrid_vista_proposal"]
            )
        completed.append(normalized)
    return completed


def _hybrid_resume_lineage_error(
    results: list[dict[str, Any]],
    *,
    request_by_id: dict[str, dict[str, Any]],
    source_revision: str,
) -> str:
    seen: set[str] = set()
    for result in results:
        candidate_id = str(result.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id in seen:
            return "duplicate_or_missing_candidate_id"
        seen.add(candidate_id)
        expected = request_by_id.get(candidate_id)
        if expected is None:
            return f"unknown_candidate_id:{candidate_id}"
        if result.get("final_numbering_revision") != source_revision:
            return f"stale_source_revision:{candidate_id}"
        submitted = result.get("hybrid_vista_request")
        proposal = result.get("hybrid_vista_proposal")
        if not isinstance(submitted, dict) or not isinstance(proposal, dict):
            return f"missing_hybrid_lineage:{candidate_id}"
        if canonical_json_bytes(submitted) != canonical_json_bytes(expected):
            return f"request_lineage_mismatch:{candidate_id}"
        for field in (
            "candidate_id",
            "candidate_bbox_ref",
            "roi_ref",
            "affine_transform_ref",
            "source_revision",
            "capture_sha256",
        ):
            if proposal.get(field) != expected.get(field):
                return f"proposal_{field}_mismatch:{candidate_id}"
        revalidated = validate_vista_proposal(
            request=expected,
            raw_result=proposal.get("raw_provider_result"),
        )
        if canonical_json_bytes(revalidated) != canonical_json_bytes(proposal):
            return f"proposal_raw_evidence_mismatch:{candidate_id}"
    return ""


def _cancellation_requested(cancellation_event: Any | None) -> bool:
    return bool(
        cancellation_event is not None
        and hasattr(cancellation_event, "is_set")
        and cancellation_event.is_set()
    )


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


def _hybrid_batch_coverage_error(
    batch: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    request_by_id: dict[str, dict[str, Any]],
) -> str:
    requested = list(request_by_id)
    result_ids = [str(item.get("candidate_id") or "").strip() for item in results]
    completed = batch.get("completed_candidate_ids")
    if not isinstance(completed, list) or completed != result_ids:
        return "completed_candidate_ids_do_not_equal_result_ids"
    if batch.get("completed_count") != len(result_ids):
        return "completed_count_does_not_equal_result_count"
    if len(set(result_ids)) != len(result_ids) or not set(result_ids).issubset(request_by_id):
        return "result_id_set_is_invalid"
    remaining = [candidate_id for candidate_id in requested if candidate_id not in set(result_ids)]
    if batch.get("remaining_count") != len(remaining):
        return "remaining_count_does_not_equal_exact_difference"
    declared_remaining = batch.get("remaining_candidate_ids")
    if declared_remaining is not None and declared_remaining != remaining:
        return "remaining_candidate_ids_do_not_equal_exact_difference"
    if batch.get("resumable") is not True and (remaining or set(result_ids) != set(requested)):
        return "terminal_result_set_does_not_equal_request_set"
    return ""


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
