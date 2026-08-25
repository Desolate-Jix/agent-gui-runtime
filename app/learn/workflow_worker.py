from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from app.core.model_server import cancel_model_request
from app.learn.workflow_contracts import (
    normalize_learning_pipeline_mode,
    ModelReviewTaskInput,
    RecognitionTaskInput,
    TwoStageUnderstandingTaskInput,
)
from app.learn.workflow_task_result_adapter import (
    model_review_result_to_legacy_response,
    observe_result_to_legacy_response,
    recognition_result_to_legacy_response,
    two_stage_result_to_legacy_response,
)
from app.learn.workflow_tasks.hybrid_fusion import run_hybrid_fusion_task
from app.learn.workflow_tasks.hybrid_omni import run_hybrid_omni_task
from app.learn.workflow_tasks.hybrid_qwen import (
    run_hybrid_qwen_task,
    validate_hybrid_qwen_task_payload,
)
from app.learn.workflow_tasks.hybrid_review import (
    run_hybrid_review_projection_task,
)
from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.workflow_tasks.model_review import run_model_review_task
from app.learn.workflow_tasks.observe import run_observe_task
from app.learn.workflow_tasks.recognition import run_recognition_task
from app.learn.workflow_tasks.two_stage import run_two_stage_understanding_task
from app.operation.observe.contracts import ObserveScreenTaskInput
from app.operation.observe.screen_reader import read_screen


LEARNING_STAGE_WORKER_CONTRACT_VERSION = "learning_stage_worker_v1"
LEARNING_STAGE_WORKER_JOURNAL_CONTRACT_VERSION = "learning_stage_worker_journal_v1"
LEARNING_STAGE_WORKER_RESULT_CONTRACT_VERSION = "learning_stage_worker_result_v2"
LEARNING_STAGE_WORKER_RESULT_ADOPTION_CONTRACT_VERSION = (
    "learning_stage_worker_result_adoption_v1"
)
SUPPORTED_LEARNING_STAGE_TASK_KINDS = frozenset(
    {
        "panel_learning_recognition_trial",
        "panel_learning_two_stage_understanding",
        "panel_learning_model_review_repair",
        "panel_learning_calibration_sequence",
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
        "panel_learning_hybrid_review_projection",
        "vision_observe_screen",
        "vision_locate_target",
    }
)
_MODEL_STAGE_BY_TASK_KIND = {
    "panel_learning_recognition_trial": "observe",
    "panel_learning_two_stage_understanding": "observe",
    "panel_learning_model_review_repair": "observe",
    "panel_learning_calibration_sequence": "locate",
    "panel_learning_hybrid_qwen_binding": "understanding",
    "vision_observe_screen": "observe",
}
_MANAGED_QWEN_TASK_KINDS = frozenset(
    {
        "panel_learning_recognition_trial",
        "panel_learning_two_stage_understanding",
        "panel_learning_model_review_repair",
        "panel_learning_hybrid_qwen_binding",
        "vision_observe_screen",
    }
)
_HYBRID_MANAGED_TASK_KINDS = frozenset(
    {
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
        "panel_learning_calibration_sequence",
        "panel_learning_hybrid_review_projection",
    }
)
_MODEL_READY_WAIT_SECONDS = 180.0
_HYBRID_OMNI_CLEANUP_WAIT_SECONDS = 35.0
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LearningStageWorkerError(ValueError):
    """学习阶段 worker 请求无效或不属于当前 operation。"""


class _ManagedCancellationEvent:
    """用同一进程锁原子化 cancel 与受保护的 lease/spawn transition。"""

    def __init__(self, *, event: Any, lock: Any) -> None:
        self._event = event
        self._lock = lock

    def is_set(self) -> bool:
        return bool(self._event.is_set())

    def set(self) -> None:
        with self._lock:
            self._event.set()

    def run_if_not_cancelled(
        self,
        stage: str,
        action: Callable[[], Any],
    ) -> tuple[bool, Any | None]:
        del stage
        with self._lock:
            if self._event.is_set():
                return False, None
            return True, action()


def execute_learning_stage_worker_task(
    task_kind: str,
    payload: dict[str, Any],
    *,
    cancellation_event: Any | None = None,
) -> dict[str, Any]:
    """在隔离进程内执行白名单 API 处理器，并返回可序列化响应。"""

    normalized_kind = str(task_kind or "").strip()
    if normalized_kind not in SUPPORTED_LEARNING_STAGE_TASK_KINDS:
        raise LearningStageWorkerError(f"unsupported task_kind: {normalized_kind}")
    if not isinstance(payload, dict):
        raise LearningStageWorkerError("worker payload must be an object")

    learning_pipeline_mode = normalize_learning_pipeline_mode(
        payload.get("learning_pipeline_mode", "incumbent")
    )
    execution_payload = deepcopy(payload)
    orchestration = execution_payload.pop("_hybrid_orchestration", None)
    execution_payload.pop("learning_pipeline_mode", None)
    if (
        learning_pipeline_mode == "hybrid_v1_1"
        and normalized_kind == "panel_learning_calibration_sequence"
        and isinstance(orchestration, dict)
    ):
        execution_payload["learning_pipeline_mode"] = "hybrid_v1_1"
        execution_payload.setdefault(
            "hybrid_fusion_result",
            deepcopy(orchestration.get("fusion_result")),
        )
        execution_payload.setdefault(
            "capture_bundle",
            deepcopy(orchestration.get("capture_bundle")),
        )
        for key in (
            "omni_inventory",
            "qwen_bindings",
            "qwen_cleanup_receipt",
            "hybrid_capture_bundle_ref",
            "run_id",
            "workflow_revision",
        ):
            execution_payload.setdefault(key, deepcopy(orchestration.get(key)))
        execution_payload.setdefault("project_root", str(_PROJECT_ROOT))

    model_lease: dict[str, Any] | None = None
    lifecycle_evidence: dict[str, Any] = {}
    try:
        if normalized_kind == "panel_learning_hybrid_qwen_binding":
            validate_hybrid_qwen_task_payload(execution_payload)
        model_lease = _ensure_learning_stage_model_ready(
            normalized_kind,
            execution_payload,
            cancellation_event=cancellation_event,
        )
        if normalized_kind == "panel_learning_hybrid_qwen_binding":
            response = run_hybrid_qwen_task(
                execution_payload,
                cancellation_event=cancellation_event,
                model_lease=model_lease,
                include_cleanup_receipt=True,
            )
            if not isinstance(response, dict) or not isinstance(
                response.get("qwen_cleanup_receipt"), dict
            ):
                raise LearningStageWorkerError(
                    "Hybrid Qwen task did not produce exact cleanup receipt"
                )
            lifecycle_evidence["qwen_cleanup_receipt"] = deepcopy(
                response["qwen_cleanup_receipt"]
            )
            response = response.get("qwen_bindings")
        elif normalized_kind == "panel_learning_hybrid_fusion":
            response = run_hybrid_fusion_task(
                execution_payload,
                cancellation_event=cancellation_event,
            )
            if learning_pipeline_mode == "hybrid_v1_1":
                response = seal_immutable(response)
        elif normalized_kind == "panel_learning_hybrid_omni_discovery":
            response = run_hybrid_omni_task(
                execution_payload,
                cancellation_event=cancellation_event,
            )
        elif normalized_kind == "panel_learning_hybrid_review_projection":
            response = run_hybrid_review_projection_task(
                execution_payload,
                cancellation_event=cancellation_event,
            )
        elif normalized_kind == "panel_learning_recognition_trial":
            response = recognition_result_to_legacy_response(
                run_recognition_task(
                    RecognitionTaskInput.model_validate(execution_payload),
                    project_root=_PROJECT_ROOT,
                )
            )
        elif normalized_kind == "panel_learning_two_stage_understanding":
            response = two_stage_result_to_legacy_response(
                run_two_stage_understanding_task(
                    TwoStageUnderstandingTaskInput.model_validate(execution_payload),
                    project_root=_PROJECT_ROOT,
                )
            )
        elif normalized_kind == "panel_learning_model_review_repair":
            review_task_options: dict[str, Any] = {}
            if model_lease is not None:
                from app.learn.recognition import panel_review_pipeline

                review_task_options["review_runner"] = partial(
                    panel_review_pipeline.run_panel_learning_model_review_repair,
                    managed_model_lease=deepcopy(model_lease),
                )
            response = model_review_result_to_legacy_response(
                run_model_review_task(
                    ModelReviewTaskInput.model_validate(execution_payload),
                    project_root=_PROJECT_ROOT,
                    **review_task_options,
                )
            )
        elif normalized_kind == "panel_learning_calibration_sequence":
            from app.learn.calibration_sequence import run_learning_calibration_sequence

            if cancellation_event is None:
                response = run_learning_calibration_sequence(execution_payload)
            else:
                response = run_learning_calibration_sequence(
                    execution_payload,
                    cancellation_event=cancellation_event,
                )
        elif normalized_kind == "vision_observe_screen":
            response = observe_result_to_legacy_response(
                run_observe_task(
                    ObserveScreenTaskInput.model_validate(execution_payload),
                    project_root=_PROJECT_ROOT,
                    screen_reader=partial(
                        read_screen,
                        managed_model_lease=model_lease,
                    ),
                )
            )
        else:
            from app.api.models.request import VisionLocateTargetRequestModel
            from app.api.vision import locate_target

            response = locate_target(
                VisionLocateTargetRequestModel.model_validate(execution_payload)
            )
    except BaseException as error:
        if (
            learning_pipeline_mode == "hybrid_v1_1"
            and normalized_kind in _HYBRID_MANAGED_TASK_KINDS
        ):
            lifecycle_evidence = _reconcile_hybrid_handler_failure(
                model_lease=model_lease,
                error=error,
            )
            return _hybrid_managed_failure_result(
                task_kind=normalized_kind,
                error=error,
                orchestration=orchestration,
                lifecycle_evidence=lifecycle_evidence,
            )
        if model_lease is not None and normalized_kind != "panel_learning_hybrid_qwen_binding":
            from app.core.model_server import reconcile_qwen_model_lease_failure

            reconcile_qwen_model_lease_failure(
                model_lease=model_lease,
                compute_completed=False,
                reason="managed_consumer_failed",
            )
        raise
    if model_lease is not None and normalized_kind != "panel_learning_hybrid_qwen_binding":
        from app.core.model_server import reconcile_qwen_model_lease_failure

        reconcile_qwen_model_lease_failure(
            model_lease=model_lease,
            compute_completed=False,
            reason="managed_consumer_completed",
        )

    if hasattr(response, "model_dump"):
        normalized_response = response.model_dump(mode="json")
    elif isinstance(response, dict):
        normalized_response = deepcopy(response)
    else:
        raise LearningStageWorkerError(
            f"worker task returned unsupported response type: {type(response).__name__}"
        )
    if (
        learning_pipeline_mode == "hybrid_v1_1"
        and normalized_kind in _HYBRID_MANAGED_TASK_KINDS
    ):
        if not isinstance(orchestration, dict):
            raise LearningStageWorkerError(
                "Hybrid managed worker payload is missing orchestration context"
            )
        declared_outcome = str(normalized_response.get("outcome") or "").strip()
        outcome = (
            declared_outcome
            if declared_outcome
            else "failed" if normalized_response.get("success") is False else "completed"
        )
        return {
            "contract_version": "learning_hybrid_managed_stage_result_v1",
            "learning_pipeline_mode": "hybrid_v1_1",
            "task_kind": normalized_kind,
            "outcome": outcome,
            "result": normalized_response,
            "orchestration": deepcopy(orchestration),
            "lifecycle_evidence": deepcopy(lifecycle_evidence),
        }
    return normalized_response


def _reconcile_hybrid_handler_failure(
    *,
    model_lease: dict[str, Any] | None,
    error: BaseException,
) -> dict[str, Any]:
    if model_lease is None:
        return {"status": "model_lease_not_acquired"}
    from app.core.model_server import reconcile_qwen_model_lease_failure

    try:
        return deepcopy(
            reconcile_qwen_model_lease_failure(
                model_lease=model_lease,
                compute_completed=False,
                reason="managed_hybrid_handler_failed",
            )
        )
    except BaseException as cleanup_error:
        error.add_note(
            "Hybrid model lifecycle reconciliation failed: "
            f"{type(cleanup_error).__name__}: {cleanup_error}"
        )
        return {
            "status": "reconciliation_failed",
            "error_type": type(cleanup_error).__name__,
            "details": str(cleanup_error),
        }


def _hybrid_managed_failure_result(
    *,
    task_kind: str,
    error: BaseException,
    orchestration: object,
    lifecycle_evidence: dict[str, Any],
) -> dict[str, Any]:
    error_notes = [str(note) for note in getattr(error, "__notes__", [])]
    diagnostics = getattr(error, "diagnostics", None)
    failure = {
        "contract_version": "learning_hybrid_stage_failure_v1",
        "failure_reason": str(error) or type(error).__name__,
        "error_type": type(error).__name__,
        "error_notes": error_notes,
        "model_lifecycle": deepcopy(lifecycle_evidence),
    }
    if isinstance(diagnostics, dict):
        failure["diagnostics"] = deepcopy(diagnostics)
    return {
        "contract_version": "learning_hybrid_managed_stage_result_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "task_kind": task_kind,
        "outcome": "failed",
        "result": failure,
        "orchestration": (
            deepcopy(orchestration) if isinstance(orchestration, dict) else {}
        ),
    }


def _ensure_learning_stage_model_ready(
    task_kind: str,
    payload: dict[str, Any],
    *,
    cancellation_event: Any | None = None,
) -> dict[str, Any] | None:
    """后端 worker 自行完成模型资源检查和服务准备。"""

    stage = _MODEL_STAGE_BY_TASK_KIND.get(task_kind)
    if not stage:
        return None
    if task_kind == "vision_observe_screen":
        if payload.get("capture_live") is False and not str(
            payload.get("image_path") or ""
        ).strip():
            return None
        requested_provider = str(payload.get("provider_mode") or "").strip().casefold()
        if requested_provider not in {"", "local", "local_grounding", "local_understanding"}:
            return None
    if task_kind == "panel_learning_model_review_repair":
        profile_id = str(payload.get("model_profile_id") or "").strip() or None
    elif task_kind == "panel_learning_calibration_sequence":
        profile_id = str(payload.get("profile_id") or "").strip() or None
    else:
        profile_id = None

    from app.core.gpu_resources import build_model_resource_preflight
    from app.core.model_server import (
        ensure_and_acquire_qwen_model_lease,
        ensure_model_server,
        _mark_qwen_model_request_in_flight,
        profile_for_stage,
    )

    def validate_profile(profile: dict[str, Any]) -> None:
        provider_mode = str(profile.get("provider_mode") or "").strip().casefold()
        if not provider_mode.startswith("local"):
            raise LearningStageWorkerError(
                f"managed Qwen profile is not local for {stage}"
            )
        preflight = build_model_resource_preflight(profile)
        if (
            str(preflight.get("resource_mode") or "").strip().casefold() == "critical"
            or preflight.get("model_launch_allowed") is False
        ):
            reason_codes = preflight.get("reason_codes")
            reasons = (
                ", ".join(str(item) for item in reason_codes)
                if isinstance(reason_codes, list)
                else "critical_resource_load"
            )
            raise LearningStageWorkerError(
                f"model resource preflight blocked {stage}: {reasons}"
            )

    def ensure_and_publish() -> dict[str, Any] | None:
        if task_kind in _MANAGED_QWEN_TASK_KINDS:
            request_id = str(os.environ.get("AGENT_GUI_MODEL_REQUEST_ID") or "").strip()
            if not request_id:
                raise LearningStageWorkerError("Qwen model request identity is unavailable")
            try:
                lease = ensure_and_acquire_qwen_model_lease(
                    stage=stage,
                    profile_id=profile_id,
                    request_id=request_id,
                    wait_seconds=_MODEL_READY_WAIT_SECONDS,
                    profile_validator=validate_profile,
                )
                if task_kind != "panel_learning_hybrid_qwen_binding":
                    _mark_qwen_model_request_in_flight(lease)
                return lease
            except RuntimeError as error:
                raise LearningStageWorkerError(str(error)) from error
        profile = profile_for_stage(stage, profile_id)
        provider_mode = str(profile.get("provider_mode") or "").strip().casefold()
        if not provider_mode.startswith("local"):
            return None
        validate_profile(profile)
        readiness = ensure_model_server(
            stage=stage,
            profile_id=profile_id,
            wait_until_ready=True,
            wait_seconds=_MODEL_READY_WAIT_SECONDS,
        )
        after = readiness.get("after")
        before = readiness.get("before")
        status = str(
            (after.get("status") if isinstance(after, dict) else "")
            or (before.get("status") if isinstance(before, dict) else "")
        ).strip()
        if status != "running":
            raise LearningStageWorkerError(
                f"model service not ready for {stage}: {status or 'unknown'}"
            )
        return None

    if (
        task_kind in _MANAGED_QWEN_TASK_KINDS
        and cancellation_event is not None
        and hasattr(cancellation_event, "run_if_not_cancelled")
    ):
        allowed, result = cancellation_event.run_if_not_cancelled(
            "qwen_ensure_and_lease",
            ensure_and_publish,
        )
        if not allowed:
            raise LearningStageWorkerError("Qwen cancelled before model acquisition")
        return result
    return ensure_and_publish()


def _run_learning_stage_worker_entry(
    result_path: str,
    task_kind: str,
    payload: dict[str, Any],
    model_request_id: str,
    identity: dict[str, Any],
    cancellation_event: Any,
    completion_event: Any,
) -> None:
    result_file = Path(result_path)
    previous_request_id = os.environ.get("AGENT_GUI_MODEL_REQUEST_ID")
    os.environ["AGENT_GUI_MODEL_REQUEST_ID"] = model_request_id
    try:
        response = execute_learning_stage_worker_task(
            task_kind,
            payload,
            cancellation_event=cancellation_event,
        )
        envelope = {
            "contract_version": LEARNING_STAGE_WORKER_RESULT_CONTRACT_VERSION,
            **deepcopy(identity),
            "status": "completed",
            "finished_at": _utc_now_iso(),
            "response": response,
        }
    except BaseException as exc:
        envelope = {
            "contract_version": LEARNING_STAGE_WORKER_RESULT_CONTRACT_VERSION,
            **deepcopy(identity),
            "status": "failed",
            "finished_at": _utc_now_iso(),
            "error": {
                "type": type(exc).__name__,
                "details": str(exc),
            },
        }
    finally:
        if previous_request_id is None:
            os.environ.pop("AGENT_GUI_MODEL_REQUEST_ID", None)
        else:
            os.environ["AGENT_GUI_MODEL_REQUEST_ID"] = previous_request_id
    _write_worker_result(result_file, envelope)
    if completion_event is not None:
        completion_event.set()


def _write_worker_result(path: Path, payload: dict[str, Any]) -> None:
    _write_json_atomic(path, payload)


class LearningStageWorkerRegistry:
    """管理进程隔离的学习阶段任务；状态所有权仍由 workflow service 掌握。"""

    def __init__(
        self,
        *,
        result_root: str | Path,
        process_factory: Callable[..., Any] | None = None,
        model_request_cancel: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._result_root = Path(result_root).resolve()
        self._result_root.mkdir(parents=True, exist_ok=True)
        context = multiprocessing.get_context("spawn")
        self._process_context = context
        self._process_factory = process_factory or context.Process
        self._model_request_cancel = model_request_cancel or cancel_model_request
        self._lock = RLock()
        self._records: dict[str, dict[str, Any]] = {}
        self._active_by_operation: dict[tuple[str, str, str], str] = {}
        self._workers_by_operation: dict[
            tuple[str, str, str],
            list[str],
        ] = {}
        self._workers_by_invocation: dict[
            tuple[str, str, str, str, str],
            str,
        ] = {}
        self._load_journals()

    def _load_journals(self) -> None:
        for journal_path in sorted(self._result_root.glob("*.worker.json")):
            record = _load_worker_journal(
                journal_path=journal_path,
                result_root=self._result_root,
            )
            worker_id = record["worker_id"]
            operation_key = (
                record["run_id"],
                record["stage"],
                record["operation_id"],
            )
            invocation_key = (
                *operation_key,
                record["task_kind"],
                record["payload_sha256"],
            )
            if worker_id in self._records:
                raise LearningStageWorkerError(
                    f"duplicate durable worker_id: {worker_id}"
                )
            if invocation_key in self._workers_by_invocation:
                raise LearningStageWorkerError(
                    "duplicate durable worker invocation identity"
                )
            self._records[worker_id] = record
            self._workers_by_operation.setdefault(operation_key, []).append(worker_id)
            self._workers_by_invocation[invocation_key] = worker_id
            self._refresh_record(record)

    def _persist_record_journal(self, record: dict[str, Any]) -> None:
        journal_path = Path(record["journal_path"])
        payload = {
            key: deepcopy(record.get(key))
            for key in (
                "worker_id",
                "run_id",
                "stage",
                "operation_id",
                "task_kind",
                "model_request_id",
                "payload_sha256",
                "status",
                "started_at",
                "finished_at",
            )
        }
        if payload["status"] == "detached_running":
            payload["status"] = "running"
        payload["contract_version"] = LEARNING_STAGE_WORKER_JOURNAL_CONTRACT_VERSION
        payload["result_file"] = Path(record["result_path"]).name
        if isinstance(record.get("result_adoption"), dict):
            payload["result_adoption"] = deepcopy(record["result_adoption"])
        _write_json_atomic(journal_path, payload)

    def start(
        self,
        *,
        run_id: str,
        stage: str,
        operation_id: str,
        task_kind: str,
        payload: dict[str, Any],
        reuse_active_identical: bool = False,
    ) -> dict[str, Any]:
        normalized_run_id = _required_text(run_id, "run_id")
        normalized_stage = _required_text(stage, "stage")
        normalized_operation_id = _required_text(operation_id, "operation_id")
        normalized_task_kind = _required_text(task_kind, "task_kind")
        if normalized_task_kind not in SUPPORTED_LEARNING_STAGE_TASK_KINDS:
            raise LearningStageWorkerError(
                f"unsupported task_kind: {normalized_task_kind}"
            )
        if not isinstance(payload, dict):
            raise LearningStageWorkerError("worker payload must be an object")
        payload_sha256 = _payload_sha256(payload)

        operation_key = (
            normalized_run_id,
            normalized_stage,
            normalized_operation_id,
        )
        invocation_key = (
            *operation_key,
            normalized_task_kind,
            payload_sha256,
        )
        with self._lock:
            previous_worker_id = self._workers_by_invocation.get(invocation_key)
            if previous_worker_id:
                previous = self._records.get(previous_worker_id)
                if previous:
                    self._refresh_record(previous)
                    if (
                        previous["status"] == "running"
                        and previous.get("process") is not None
                    ):
                        if reuse_active_identical:
                            return self._public_record(previous)
                        raise LearningStageWorkerError(
                            "operation already has an active worker"
                        )
                    return self._public_record(previous)

            active_record = self._active_or_detached_operation_record(operation_key)
            if active_record is not None:
                raise LearningStageWorkerError(
                    "operation already has an active worker with a different "
                    "task or payload identity"
                )

            worker_id = uuid4().hex
            model_request_id = f"learn-worker-{worker_id}"
            result_path = self._result_root / f"{worker_id}.result.json"
            journal_path = self._result_root / f"{worker_id}.worker.json"
            identity = {
                "worker_id": worker_id,
                "run_id": normalized_run_id,
                "stage": normalized_stage,
                "operation_id": normalized_operation_id,
                "task_kind": normalized_task_kind,
                "model_request_id": model_request_id,
                "payload_sha256": payload_sha256,
            }
            cancellation_event = (
                _ManagedCancellationEvent(
                    event=self._process_context.Event(),
                    lock=self._process_context.Lock(),
                )
                if normalized_task_kind == "panel_learning_hybrid_omni_discovery"
                or normalized_task_kind in _MANAGED_QWEN_TASK_KINDS
                else None
            )
            completion_event = (
                self._process_context.Event()
                if normalized_task_kind == "panel_learning_hybrid_omni_discovery"
                else None
            )
            process = self._process_factory(
                target=_run_learning_stage_worker_entry,
                args=(
                    str(result_path),
                    normalized_task_kind,
                    deepcopy(payload),
                    model_request_id,
                    deepcopy(identity),
                    cancellation_event,
                    completion_event,
                ),
                name=f"learning-stage-{normalized_stage}-{worker_id[:8]}",
            )
            record = {
                "contract_version": LEARNING_STAGE_WORKER_CONTRACT_VERSION,
                **identity,
                "status": "running",
                "started_at": _utc_now_iso(),
                "finished_at": None,
                "result_path": str(result_path),
                "journal_path": str(journal_path),
                "process": process,
                "payload": deepcopy(payload),
                "cancellation_event": cancellation_event,
                "completion_event": completion_event,
                "recovered_from_journal": False,
            }
            self._persist_record_journal(record)
            self._records[worker_id] = record
            self._active_by_operation[operation_key] = worker_id
            self._workers_by_operation.setdefault(operation_key, []).append(worker_id)
            self._workers_by_invocation[invocation_key] = worker_id
            try:
                process.start()
            except BaseException:
                record["status"] = "failed"
                record["finished_at"] = _utc_now_iso()
                self._active_by_operation.pop(operation_key, None)
                self._persist_record_journal(record)
                raise
            return self._public_record(record)

    def status(
        self,
        *,
        worker_id: str,
        run_id: str,
        operation_id: str,
    ) -> dict[str, Any]:
        normalized_worker_id = _required_text(worker_id, "worker_id")
        with self._lock:
            record = self._records.get(normalized_worker_id)
            if not record:
                raise LearningStageWorkerError("learning stage worker not found")
            if (
                record["run_id"] != str(run_id or "").strip()
                or record["operation_id"] != str(operation_id or "").strip()
            ):
                raise LearningStageWorkerError(
                    "learning stage worker ownership does not match"
                )
            self._refresh_record(record)
            return self._public_record(record)

    def adopt_result(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
    ) -> dict[str, Any]:
        """显式接纳身份匹配的完成结果，并持久化不可含原始响应的回执。"""

        normalized_worker_id = _required_text(worker_id, "worker_id")
        normalized_run_id = _required_text(run_id, "run_id")
        normalized_stage = _required_text(stage, "stage")
        normalized_operation_id = _required_text(operation_id, "operation_id")
        with self._lock:
            record = self._records.get(normalized_worker_id)
            if not record:
                raise LearningStageWorkerError("learning stage worker not found")
            if (
                record["run_id"] != normalized_run_id
                or record["stage"] != normalized_stage
                or record["operation_id"] != normalized_operation_id
            ):
                raise LearningStageWorkerError(
                    "learning stage worker adoption ownership does not match"
                )
            self._refresh_record(record)
            worker_result = record.get("worker_result")
            if (
                record.get("status") != "completed"
                or not isinstance(worker_result, dict)
                or worker_result.get("status") != "completed"
            ):
                raise LearningStageWorkerError(
                    "learning stage worker has no completed result to adopt"
                )

            result_sha256 = _payload_sha256(worker_result)
            receipt = record.get("result_adoption")
            if isinstance(receipt, dict):
                if receipt.get("result_sha256") != result_sha256:
                    raise LearningStageWorkerError(
                        "adopted worker result digest no longer matches"
                    )
            else:
                receipt = {
                    "contract_version": (
                        LEARNING_STAGE_WORKER_RESULT_ADOPTION_CONTRACT_VERSION
                    ),
                    "worker_id": record["worker_id"],
                    "run_id": record["run_id"],
                    "stage": record["stage"],
                    "operation_id": record["operation_id"],
                    "task_kind": record["task_kind"],
                    "model_request_id": record["model_request_id"],
                    "payload_sha256": record["payload_sha256"],
                    "result_sha256": result_sha256,
                    "adopted_at": _utc_now_iso(),
                }
                record["result_adoption"] = receipt
                self._persist_record_journal(record)

            return {
                "contract_version": (
                    LEARNING_STAGE_WORKER_RESULT_ADOPTION_CONTRACT_VERSION
                ),
                "status": "adopted",
                "receipt": deepcopy(receipt),
                "response": deepcopy(worker_result.get("response")),
            }

    def read_adopted_result(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
    ) -> dict[str, Any]:
        """只读取已经显式接纳且摘要仍匹配的 worker 结果。"""

        normalized_worker_id = _required_text(worker_id, "worker_id")
        normalized_run_id = _required_text(run_id, "run_id")
        normalized_stage = _required_text(stage, "stage")
        normalized_operation_id = _required_text(operation_id, "operation_id")
        with self._lock:
            record = self._records.get(normalized_worker_id)
            if not record:
                raise LearningStageWorkerError("learning stage worker not found")
            if (
                record["run_id"] != normalized_run_id
                or record["stage"] != normalized_stage
                or record["operation_id"] != normalized_operation_id
            ):
                raise LearningStageWorkerError(
                    "learning stage worker result ownership does not match"
                )
            self._refresh_record(record)
            worker_result = record.get("worker_result")
            receipt = record.get("result_adoption")
            if not isinstance(receipt, dict):
                raise LearningStageWorkerError(
                    "learning stage worker result has not been adopted"
                )
            if (
                record.get("status") != "completed"
                or not isinstance(worker_result, dict)
                or worker_result.get("status") != "completed"
            ):
                raise LearningStageWorkerError(
                    "adopted learning stage worker result is unavailable"
                )
            result_sha256 = _payload_sha256(worker_result)
            if receipt.get("result_sha256") != result_sha256:
                raise LearningStageWorkerError(
                    "adopted worker result digest no longer matches"
                )
            return {
                "contract_version": (
                    LEARNING_STAGE_WORKER_RESULT_ADOPTION_CONTRACT_VERSION
                ),
                "status": "adopted",
                "receipt": deepcopy(receipt),
                "response": deepcopy(worker_result.get("response")),
            }

    def attachment_by_operation(
        self,
        *,
        run_id: str,
        stage: str,
        operation_id: str,
    ) -> dict[str, Any] | None:
        """读取当前进程是否仍持有指定 operation 的 worker。"""

        operation_key = (
            str(run_id or "").strip(),
            str(stage or "").strip(),
            str(operation_id or "").strip(),
        )
        with self._lock:
            record = self._latest_operation_record(operation_key)
            if record is not None:
                return self._public_record(record)
        return None

    def cancel_by_operation(
        self,
        *,
        run_id: str,
        stage: str,
        operation_id: str,
    ) -> dict[str, Any]:
        operation_key = (
            _required_text(run_id, "run_id"),
            _required_text(stage, "stage"),
            _required_text(operation_id, "operation_id"),
        )
        with self._lock:
            record = self._latest_operation_record(operation_key)
            if not record:
                return {
                    "contract_version": LEARNING_STAGE_WORKER_CONTRACT_VERSION,
                    "status": "not_running",
                    "worker_id": None,
                    "backend_compute_termination": "not_covered",
                    "model_service_compute_termination": "not_covered",
                    "model_request_cancellation": {
                        "contract_version": "model_request_cancellation_v1",
                        "status": "not_covered",
                        "model_service_compute_termination": "not_covered",
                    },
                }
            self._refresh_record(record)
            if record["status"] not in {"running", "detached_running"}:
                if (
                    record["task_kind"] in _MANAGED_QWEN_TASK_KINDS
                    and isinstance(record.get("cancellation_pending"), dict)
                ):
                    retry = self._model_request_cancel(
                        request_id=record["model_request_id"],
                        task_kind=record["task_kind"],
                        payload=deepcopy(record["payload"]),
                    )
                    termination = retry.get("model_service_compute_termination")
                    if termination in {"terminated", "request_not_active"}:
                        record["status"] = "cancelled"
                        record["finished_at"] = record.get("finished_at") or _utc_now_iso()
                        record.pop("cancellation_pending", None)
                        self._active_by_operation.pop(operation_key, None)
                        self._persist_record_journal(record)
                        return {
                            **self._public_record(record),
                            "backend_compute_termination": "terminated",
                            "model_service_compute_termination": termination,
                            "model_request_cancellation": deepcopy(retry),
                        }
                    record["cancellation_pending"] = deepcopy(retry)
                    self._persist_record_journal(record)
                    return {
                        **self._public_record(record),
                        "status": "cancellation_pending",
                        "backend_compute_termination": "terminated",
                        "model_service_compute_termination": termination,
                        "model_request_cancellation": deepcopy(retry),
                    }
                return {
                    **self._public_record(record),
                    "backend_compute_termination": "not_running",
                    "model_service_compute_termination": "request_not_active",
                    "model_request_cancellation": {
                        "contract_version": "model_request_cancellation_v1",
                        "status": "request_not_active",
                        "request_id": record.get("model_request_id"),
                        "model_service_compute_termination": "request_not_active",
                    },
                }

            process = record.get("process")
            if process is None:
                if record["task_kind"] in _MANAGED_QWEN_TASK_KINDS:
                    try:
                        model_cancellation = self._model_request_cancel(
                            request_id=record["model_request_id"],
                            task_kind=record["task_kind"],
                            payload=deepcopy(record.get("payload") or {}),
                        )
                    except Exception as exc:
                        model_cancellation = {
                            "contract_version": "model_request_cancellation_v1",
                            "status": "cancel_failed",
                            "request_id": record["model_request_id"],
                            "model_service_compute_termination": "cancel_failed",
                            "error": str(exc),
                        }
                    termination = model_cancellation.get(
                        "model_service_compute_termination",
                        "cancellation_acknowledged_pending",
                    )
                    if termination not in {"terminated", "request_not_active"}:
                        record["cancellation_pending"] = deepcopy(model_cancellation)
                        self._persist_record_journal(record)
                    return {
                        **self._public_record(record),
                        "status": (
                            str(record.get("status") or "detached_running")
                            if termination in {"terminated", "request_not_active"}
                            else "cancellation_pending"
                        ),
                        "backend_compute_termination": "not_covered",
                        "model_service_compute_termination": termination,
                        "model_request_cancellation": deepcopy(model_cancellation),
                    }
                return {
                    **self._public_record(record),
                    "backend_compute_termination": "not_covered",
                    "model_service_compute_termination": "not_covered",
                    "model_request_cancellation": {
                        "contract_version": "model_request_cancellation_v1",
                        "status": "not_covered",
                        "request_id": record.get("model_request_id"),
                        "model_service_compute_termination": "not_covered",
                        "reason": "worker process handle is detached after API restart",
                    },
                }
            if record["task_kind"] == "panel_learning_hybrid_omni_discovery":
                cancellation_event = record.get("cancellation_event")
                if cancellation_event is not None:
                    cancellation_event.set()
                model_cancellation = {
                    "contract_version": "model_request_cancellation_v1",
                    "status": "not_covered",
                    "request_id": record["model_request_id"],
                    "model_service_compute_termination": "not_covered",
                    "reason": "Hybrid Omni uses its internal cooperative cancellation event",
                }
                completion_event = record.get("completion_event")
                handshake_complete = bool(
                    completion_event is not None
                    and completion_event.wait(
                        timeout=_HYBRID_OMNI_CLEANUP_WAIT_SECONDS
                    )
                )
                if not handshake_complete:
                    raise LearningStageWorkerError(
                        "Hybrid Omni cooperative cleanup handshake timed out; "
                        "worker remains attached"
                    )
                process.join(timeout=2.0)
                self._refresh_record(record)
                if record.get("status") != "completed":
                    raise LearningStageWorkerError(
                        "Hybrid Omni cooperative cleanup result is invalid"
                    )
                cooperative_cleanup = _hybrid_omni_cleanup_evidence(record)
                if cooperative_cleanup is None:
                    raise LearningStageWorkerError(
                        "Hybrid Omni completed while cancellation was pending"
                    )
                if process.is_alive():
                    raise LearningStageWorkerError(
                        "Hybrid Omni cleanup completed but worker exit is still pending"
                    )
                return {
                    **self._public_record(record),
                    "backend_compute_termination": "terminated",
                    "model_service_compute_termination": "not_covered",
                    "model_request_cancellation": deepcopy(model_cancellation),
                    "cooperative_cleanup": cooperative_cleanup,
                }
            else:
                if record["task_kind"] in _MANAGED_QWEN_TASK_KINDS:
                    cancellation_event = record.get("cancellation_event")
                    if cancellation_event is not None:
                        cancellation_event.set()
                try:
                    model_cancellation = self._model_request_cancel(
                        request_id=record["model_request_id"],
                        task_kind=record["task_kind"],
                        payload=deepcopy(record["payload"]),
                    )
                except Exception as exc:
                    model_cancellation = {
                        "contract_version": "model_request_cancellation_v1",
                        "status": "cancel_failed",
                        "request_id": record["model_request_id"],
                        "model_service_compute_termination": "cancel_failed",
                        "error": str(exc),
                    }
                if (
                    record["task_kind"] in _MANAGED_QWEN_TASK_KINDS
                    and model_cancellation.get("model_service_compute_termination")
                    not in {"terminated", "request_not_active"}
                ):
                    record["cancellation_pending"] = deepcopy(model_cancellation)
                    self._persist_record_journal(record)
                    return {
                        **self._public_record(record),
                        "status": "cancellation_pending",
                        "backend_compute_termination": "pending",
                        "model_service_compute_termination": model_cancellation.get(
                            "model_service_compute_termination",
                            "cancellation_acknowledged_pending",
                        ),
                        "model_request_cancellation": deepcopy(model_cancellation),
                    }
            if process.is_alive():
                process.terminate()
                process.join(timeout=3.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=2.0)
            terminated = not process.is_alive()
            record["status"] = "cancelled" if terminated else "cancel_failed"
            record["finished_at"] = _utc_now_iso()
            if terminated:
                if self._active_by_operation.get(operation_key) == record["worker_id"]:
                    self._active_by_operation.pop(operation_key, None)
            self._persist_record_journal(record)
            return {
                **self._public_record(record),
                "backend_compute_termination": (
                    "terminated" if terminated else "termination_failed"
                ),
                "model_service_compute_termination": model_cancellation.get(
                    "model_service_compute_termination",
                    "cancel_failed",
                ),
                "model_request_cancellation": deepcopy(model_cancellation),
            }

    def _operation_records(
        self,
        operation_key: tuple[str, str, str],
    ) -> list[dict[str, Any]]:
        records = [
            self._records[worker_id]
            for worker_id in self._workers_by_operation.get(operation_key, [])
            if worker_id in self._records
        ]
        for record in records:
            self._refresh_record(record)
        return sorted(
            records,
            key=lambda item: (
                str(item.get("started_at") or ""),
                str(item.get("worker_id") or ""),
            ),
        )

    def _active_or_detached_operation_record(
        self,
        operation_key: tuple[str, str, str],
    ) -> dict[str, Any] | None:
        records = self._operation_records(operation_key)
        attached = [
            item
            for item in records
            if item.get("status") == "running" and item.get("process") is not None
        ]
        if attached:
            return attached[-1]
        detached = [
            item for item in records if item.get("status") == "detached_running"
        ]
        return detached[-1] if detached else None

    def _latest_operation_record(
        self,
        operation_key: tuple[str, str, str],
    ) -> dict[str, Any] | None:
        records = self._operation_records(operation_key)
        if not records:
            return None
        active = self._active_or_detached_operation_record(operation_key)
        return active or records[-1]

    def _refresh_record(self, record: dict[str, Any]) -> None:
        if record["status"] in {"cancelled", "cancel_failed"}:
            return
        if (
            record["status"] in {"completed", "failed"}
            and isinstance(record.get("worker_result"), dict)
        ):
            return

        result_path = Path(record["result_path"])
        if result_path.is_file():
            try:
                result = _load_worker_result(result_path, record)
            except LearningStageWorkerError as exc:
                result = {
                    "contract_version": LEARNING_STAGE_WORKER_RESULT_CONTRACT_VERSION,
                    "status": "failed",
                    "error": {
                        "type": "WorkerResultIdentityMismatch",
                        "details": str(exc),
                    },
                }
            result_adoption = record.get("result_adoption")
            if (
                result.get("status") == "completed"
                and isinstance(result_adoption, dict)
                and result_adoption.get("result_sha256") != _payload_sha256(result)
            ):
                result = {
                    "contract_version": LEARNING_STAGE_WORKER_RESULT_CONTRACT_VERSION,
                    "status": "failed",
                    "error": {
                        "type": "WorkerResultAdoptionDigestMismatch",
                        "details": (
                            "adopted worker result digest does not match "
                            "the durable adoption receipt"
                        ),
                    },
                }
            record["worker_result"] = result
            record["status"] = (
                "completed" if result.get("status") == "completed" else "failed"
            )
            record["finished_at"] = (
                result.get("finished_at")
                or record.get("finished_at")
                or _utc_now_iso()
            )
            operation_key = (
                record["run_id"],
                record["stage"],
                record["operation_id"],
            )
            if self._active_by_operation.get(operation_key) == record["worker_id"]:
                self._active_by_operation.pop(operation_key, None)
            self._persist_record_journal(record)
            return

        process = record.get("process")
        if process is None:
            if record["status"] in {"running", "detached_running"}:
                record["status"] = "detached_running"
                return
            if record["status"] in {"completed", "failed"}:
                record["status"] = "failed"
                record["worker_result"] = {
                    "contract_version": LEARNING_STAGE_WORKER_RESULT_CONTRACT_VERSION,
                    "status": "failed",
                    "error": {
                        "type": "WorkerResultMissing",
                        "details": "durable worker journal has no matching result envelope",
                    },
                }
                record["finished_at"] = record.get("finished_at") or _utc_now_iso()
                self._persist_record_journal(record)
            return

        if process.is_alive():
            record["status"] = "running"
            return

        process.join(timeout=0)
        record["status"] = "failed"
        record["worker_result"] = {
            "contract_version": LEARNING_STAGE_WORKER_RESULT_CONTRACT_VERSION,
            "status": "failed",
            "error": {
                "type": "WorkerResultMissing",
                "details": (
                    "worker exited without writing its result envelope "
                    f"(exitcode={getattr(process, 'exitcode', None)})"
                ),
            },
        }
        record["finished_at"] = _utc_now_iso()
        operation_key = (
            record["run_id"],
            record["stage"],
            record["operation_id"],
        )
        if self._active_by_operation.get(operation_key) == record["worker_id"]:
            self._active_by_operation.pop(operation_key, None)
        self._persist_record_journal(record)

    @staticmethod
    def _public_record(record: dict[str, Any]) -> dict[str, Any]:
        result = {
            key: deepcopy(value)
            for key, value in record.items()
            if key not in {
                "payload",
                "process",
                "worker_result",
                "result_adoption",
                "cancellation_event",
                "completion_event",
            }
        }
        process = record.get("process")
        result["pid"] = getattr(process, "pid", None)
        result["backend_compute_owner"] = "backend_process_worker"
        worker_result = record.get("worker_result")
        result["runtime_attached"] = bool(
            process is not None and record.get("status") == "running"
        )
        result["result_available"] = bool(
            isinstance(worker_result, dict)
            and worker_result.get("status") == "completed"
        )
        adoption_receipt = record.get("result_adoption")
        result["result_adopted"] = bool(
            isinstance(adoption_receipt, dict)
            and record.get("status") == "completed"
        )
        result["adoption_receipt"] = (
            deepcopy(adoption_receipt)
            if isinstance(adoption_receipt, dict)
            else None
        )
        if isinstance(worker_result, dict):
            if worker_result.get("status") != "completed":
                result["error"] = deepcopy(worker_result.get("error"))
        return result


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise LearningStageWorkerError(f"{field} is required")
    return normalized


def _payload_sha256(payload: dict[str, Any]) -> str:
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LearningStageWorkerError(
            f"worker payload is not JSON serializable: {exc}"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    )
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except (OSError, TypeError, ValueError) as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise LearningStageWorkerError(
            f"failed to persist worker JSON {path}: {exc}"
        ) from exc


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LearningStageWorkerError(
            f"{label} is unreadable: {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise LearningStageWorkerError(f"{label} must contain a JSON object")
    return value


def _load_worker_journal(
    *,
    journal_path: Path,
    result_root: Path,
) -> dict[str, Any]:
    payload = _read_json_object(journal_path, label="worker journal")
    if payload.get("contract_version") != LEARNING_STAGE_WORKER_JOURNAL_CONTRACT_VERSION:
        raise LearningStageWorkerError(
            f"unsupported worker journal contract: {payload.get('contract_version')}"
        )

    identity = {
        key: _required_text(payload.get(key), key)
        for key in (
            "worker_id",
            "run_id",
            "stage",
            "operation_id",
            "task_kind",
            "model_request_id",
            "payload_sha256",
            "status",
            "started_at",
        )
    }
    worker_id = identity["worker_id"]
    if journal_path.name != f"{worker_id}.worker.json":
        raise LearningStageWorkerError(
            "worker journal filename does not match worker_id"
        )
    if identity["task_kind"] not in SUPPORTED_LEARNING_STAGE_TASK_KINDS:
        raise LearningStageWorkerError(
            f"worker journal has unsupported task_kind: {identity['task_kind']}"
        )
    payload_hash = identity["payload_sha256"]
    if len(payload_hash) != 64 or any(
        character not in "0123456789abcdef" for character in payload_hash
    ):
        raise LearningStageWorkerError(
            "worker journal payload_sha256 must be lowercase SHA-256"
        )
    persisted_status = identity["status"]
    if persisted_status not in {
        "running",
        "completed",
        "failed",
        "cancelled",
        "cancel_failed",
    }:
        raise LearningStageWorkerError(
            f"worker journal has invalid status: {persisted_status}"
        )

    result_file = _required_text(payload.get("result_file"), "result_file")
    expected_result_file = f"{worker_id}.result.json"
    if result_file != expected_result_file or Path(result_file).name != result_file:
        raise LearningStageWorkerError(
            "worker journal result_file does not match worker_id"
        )
    if "payload" in payload:
        raise LearningStageWorkerError(
            "worker journal must not persist the raw payload"
        )
    result_adoption = payload.get("result_adoption")
    if result_adoption is not None:
        result_adoption = _validated_result_adoption(
            result_adoption,
            identity=identity,
        )

    result_path = (result_root / result_file).resolve()
    if result_path.parent != result_root.resolve():
        raise LearningStageWorkerError(
            "worker journal result_file escapes the result root"
        )
    return {
        "contract_version": LEARNING_STAGE_WORKER_CONTRACT_VERSION,
        **identity,
        "status": (
            "detached_running" if persisted_status == "running" else persisted_status
        ),
        "finished_at": payload.get("finished_at"),
        "result_path": str(result_path),
        "journal_path": str(journal_path.resolve()),
        "process": None,
        "payload": None,
        "cancellation_event": None,
        "completion_event": None,
        "result_adoption": result_adoption,
        "recovered_from_journal": True,
    }


def _validated_result_adoption(
    value: Any,
    *,
    identity: dict[str, str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LearningStageWorkerError("worker result adoption must be an object")
    if (
        value.get("contract_version")
        != LEARNING_STAGE_WORKER_RESULT_ADOPTION_CONTRACT_VERSION
    ):
        raise LearningStageWorkerError(
            "worker result adoption has unsupported contract"
        )
    for key in (
        "worker_id",
        "run_id",
        "stage",
        "operation_id",
        "task_kind",
        "model_request_id",
        "payload_sha256",
    ):
        if _required_text(value.get(key), key) != identity[key]:
            raise LearningStageWorkerError(
                f"worker result adoption identity mismatch: {key}"
            )
    result_sha256 = _required_text(value.get("result_sha256"), "result_sha256")
    if len(result_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in result_sha256
    ):
        raise LearningStageWorkerError(
            "worker result adoption result_sha256 must be lowercase SHA-256"
        )
    _required_text(value.get("adopted_at"), "adopted_at")
    return deepcopy(value)


def _load_worker_result(
    result_path: Path,
    record: dict[str, Any],
) -> dict[str, Any]:
    payload = _read_json_object(result_path, label="worker result")
    if payload.get("contract_version") != LEARNING_STAGE_WORKER_RESULT_CONTRACT_VERSION:
        raise LearningStageWorkerError(
            f"unsupported worker result contract: {payload.get('contract_version')}"
        )
    for key in (
        "worker_id",
        "run_id",
        "stage",
        "operation_id",
        "task_kind",
        "model_request_id",
        "payload_sha256",
    ):
        actual = payload.get(key)
        expected = record.get(key)
        if actual != expected:
            raise LearningStageWorkerError(
                f"worker result identity mismatch for {key}: "
                f"expected {expected!r}, got {actual!r}"
            )

    status = payload.get("status")
    if status not in {"completed", "failed"}:
        raise LearningStageWorkerError(
            f"worker result has invalid status: {status}"
        )
    if status == "completed" and not isinstance(payload.get("response"), dict):
        raise LearningStageWorkerError(
            "completed worker result must contain an object response"
        )
    if status == "failed" and not isinstance(payload.get("error"), dict):
        raise LearningStageWorkerError(
            "failed worker result must contain an object error"
        )
    return payload


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hybrid_omni_cleanup_evidence(
    record: dict[str, Any],
) -> dict[str, Any] | None:
    result = record.get("worker_result")
    response = result.get("response") if isinstance(result, dict) else None
    if not isinstance(response, dict) or response.get("outcome") != "failed":
        return None
    receipt_ref = response.get("provider_receipt_ref")
    error_ref = response.get("provider_error_ref")
    if (
        response.get("contract_version") != "hybrid_omni_discovery_result_v1"
        or response.get("failure_reason") != "runtime_cancelled"
        or response.get("provider_reason_class") != "runtime_provider_failed"
        or response.get("provider_status") != "failed"
        or response.get("provider_claim_status") != "complete"
        or response.get("cleanup_status") != "clean"
        or not _is_immutable_ref(receipt_ref)
        or not _is_immutable_ref(error_ref)
        or not isinstance(response.get("provider_invocation_id"), str)
        or not response["provider_invocation_id"].startswith("invocation/")
    ):
        raise LearningStageWorkerError(
            "Hybrid Omni cooperative cleanup evidence is invalid"
        )
    return {
        "contract_version": "hybrid_omni_cooperative_cleanup_v1",
        "provider_invocation_id": response["provider_invocation_id"],
        "provider_claim_status": "complete",
        "provider_result_ref": deepcopy(response.get("provider_result_ref")),
        "provider_error_ref": deepcopy(error_ref),
        "provider_receipt_ref": deepcopy(receipt_ref),
        "provider_reason_class": "runtime_provider_failed",
        "failure_reason": "runtime_cancelled",
        "cleanup_status": "clean",
    }


def _is_immutable_ref(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"id", "content_sha256"}
        and isinstance(value.get("id"), str)
        and bool(value["id"])
        and isinstance(value.get("content_sha256"), str)
        and len(value["content_sha256"]) == 64
        and all(character in "0123456789abcdef" for character in value["content_sha256"])
    )


learning_stage_worker_registry = LearningStageWorkerRegistry(
    result_root=Path(__file__).resolve().parents[2] / "logs" / "workflow-workers"
)
