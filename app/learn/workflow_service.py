from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from app.learn.calibration_artifact import (
    LearningCalibrationArtifactError,
    create_learning_calibration_artifact,
)
from app.learn.calibration_sequence import (
    LEARNING_CALIBRATION_SEQUENCE_REQUEST_CONTRACT_VERSION,
)
from app.learn.hybrid.gpu_lifecycle import assert_next_provider_safe_to_start
from app.learn.hybrid.review_projection import project_hybrid_review
from app.learn.recognition.uei.canonical import content_sha256, seal_immutable
from app.learn.workflow_continuation import (
    LEARNING_STAGE_WORKER_CONTINUATION_CONTRACT_VERSION,
    interpret_learning_stage_worker_result,
)
from app.learn.workflow_contracts import normalize_learning_pipeline_mode
from app.learn.workflow_evidence import verify_learning_workflow_completion_evidence
from app.learn.workflow_store import LearningWorkflowRunStore
from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle


LEARNING_WORKFLOW_STAGE_OPERATION_CONTRACT_VERSION = (
    "learning_workflow_stage_operation_v1"
)
LEARNING_WORKFLOW_NEXT_STAGE_OPERATION_CONTRACT_VERSION = (
    "learning_workflow_next_stage_operation_v1"
)
_NEXT_MANAGED_STAGE: dict[str, tuple[str, str, str]] = {
    "screen_understanding": (
        "numbered_map",
        "panel_learning_two_stage_understanding",
        "backend continuation · Stage1 region gate and two-stage numbering",
    ),
    "numbered_map": (
        "precise_calibration",
        "panel_learning_calibration_sequence",
        "backend continuation · precise calibration dry-run",
    ),
    "precise_calibration": (
        "review_repair",
        "panel_learning_model_review_repair",
        "backend continuation · model review and repair",
    ),
    "review_repair": (
        "fusion",
        "panel_learning_recognition_trial",
        "backend continuation · fused learning draft",
    ),
}
_BACKEND_CONTINUATION_LEASE_SECONDS = 1800


class LearningWorkflowStageOperationError(ValueError):
    """学习阶段运行租约无效，拒绝接收过期或越权结果。"""


_BENCHMARK_V2_WINDOW_BINDING_FIELD = "_benchmark_v2_window_binding"
_BENCHMARK_V2_WINDOW_ADOPTION_CONTRACT = (
    "portfolio_hybrid_benchmark_v2_worker_window_binding_adoption_v1"
)


def _reject_client_benchmark_v2_window_binding(payload: Mapping[str, object]) -> None:
    if _BENCHMARK_V2_WINDOW_BINDING_FIELD in payload:
        raise LearningWorkflowStageOperationError(
            "_benchmark_v2_window_binding is server-owned"
        )


def inject_benchmark_v2_worker_window_binding(
    *,
    payload: dict[str, Any],
    operation_ref: Mapping[str, object],
    owner: Mapping[str, object],
    capture_ref: Mapping[str, object],
) -> dict[str, Any]:
    """在server-owned worker payload cut-point注入sealed窗口绑定。"""

    if not isinstance(payload, dict):
        raise LearningWorkflowStageOperationError("worker payload must be an object")
    _reject_client_benchmark_v2_window_binding(payload)
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        serialize_worker_window_binding,
    )

    child = deepcopy(payload)
    child[_BENCHMARK_V2_WINDOW_BINDING_FIELD] = serialize_worker_window_binding(
        operation_ref=operation_ref,
        owner=owner,
        capture_ref=capture_ref,
    )
    return child


def validate_benchmark_v2_worker_window_binding_adoption(
    *,
    worker_payload: Mapping[str, object],
    generic_adoption: Mapping[str, object],
    operation_ref: Mapping[str, object],
    owner: Mapping[str, object],
    capture_ref: Mapping[str, object],
) -> dict[str, object]:
    """用server refs与generic digest重建benchmark专用adoption receipt。"""

    from app.learn.hybrid.benchmark_v2_contracts import require_sha256
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        ADOPTED_RECEIPT_CONTRACT,
        NORMAL_CLEAR_RECEIPT_CONTRACT,
        serialize_worker_window_binding,
        validate_spawned_worker_observation_payload,
        validate_spawned_worker_uia_snapshot,
    )

    try:
        if not isinstance(worker_payload, Mapping):
            raise ValueError("worker payload is invalid")
        serialized = worker_payload.get(_BENCHMARK_V2_WINDOW_BINDING_FIELD)
        if not isinstance(serialized, Mapping):
            raise ValueError("sealed worker binding is missing")
        expected_serialized = serialize_worker_window_binding(
            operation_ref=operation_ref,
            owner=owner,
            capture_ref=capture_ref,
        )
        if dict(serialized) != expected_serialized:
            raise ValueError("serialized worker binding differs from server refs")
        handler_payload = {
            key: deepcopy(item)
            for key, item in worker_payload.items()
            if key != _BENCHMARK_V2_WINDOW_BINDING_FIELD
        }
        validate_spawned_worker_observation_payload(
            payload=handler_payload,
            serialized=serialized,
        )
        if (
            not isinstance(generic_adoption, Mapping)
            or generic_adoption.get("contract_version")
            != "learning_stage_worker_result_adoption_v1"
            or generic_adoption.get("status") != "adopted"
        ):
            raise ValueError("generic adoption envelope is invalid")
        generic_receipt = generic_adoption.get("receipt")
        response = generic_adoption.get("response")
        if not isinstance(generic_receipt, Mapping) or not isinstance(response, Mapping):
            raise ValueError("generic adoption receipt or response is invalid")
        receipt_fields = {
            "contract_version",
            "worker_id",
            "run_id",
            "stage",
            "operation_id",
            "task_kind",
            "model_request_id",
            "payload_sha256",
            "result_sha256",
            "adopted_at",
        }
        if (
            set(generic_receipt) != receipt_fields
            or generic_receipt.get("contract_version")
            != "learning_stage_worker_result_adoption_v1"
            or generic_receipt.get("operation_id") != operation_ref.get("operation_id")
            or generic_receipt.get("task_kind") != "vision_observe_screen"
        ):
            raise ValueError("generic adoption lineage differs")
        encoded_payload = json.dumps(
            worker_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        worker_payload_sha256 = hashlib.sha256(encoded_payload).hexdigest()
        if generic_receipt.get("payload_sha256") != worker_payload_sha256:
            raise ValueError("generic adoption full payload SHA differs")
        worker_result_sha256 = require_sha256(
            generic_receipt.get("result_sha256"), "worker_result_sha256"
        )
        evidence = response.get("_benchmark_v2_window_binding_evidence")
        if not isinstance(evidence, Mapping) or set(evidence) != {
            "adopted_receipt",
            "normal_clear_receipt",
            "snapshot",
        }:
            raise ValueError("worker binding evidence is invalid")
        snapshot = evidence["snapshot"]
        if not isinstance(snapshot, Mapping):
            raise ValueError("worker binding snapshot evidence is invalid")
        snapshot_ref = validate_spawned_worker_uia_snapshot(
            snapshot=snapshot,
            serialized=serialized,
            owner=owner,
        )
        adopted = evidence["adopted_receipt"]
        expected_adopted: dict[str, object] = {
            "contract_version": ADOPTED_RECEIPT_CONTRACT,
            "operation_id": serialized["operation_id"],
            "binding_payload_sha256": serialized["payload_sha256"],
            "capture_sha256": serialized["capture_sha256"],
            "uia_root_hwnd": serialized["expected_uia_root_hwnd"],
            "uia_owner_pid": serialized["expected_uia_owner_pid"],
            "snapshot_ref": snapshot_ref,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        expected_adopted["content_sha256"] = content_sha256(expected_adopted)
        if adopted != expected_adopted:
            raise ValueError("worker binding adopted receipt differs")
        normal = evidence["normal_clear_receipt"]
        if (
            not isinstance(normal, Mapping)
            or set(normal)
            != {
                "contract_version",
                "operation_id",
                "binding_payload_sha256",
                "worker_pid",
                "cleared",
                "prior_binding_restored",
                "restored_hwnd",
                "artifact_is_authorization",
                "execute_binding_enabled",
                "content_sha256",
            }
            or normal.get("contract_version") != NORMAL_CLEAR_RECEIPT_CONTRACT
            or normal.get("operation_id") != serialized["operation_id"]
            or normal.get("binding_payload_sha256") != serialized["payload_sha256"]
            or isinstance(normal.get("worker_pid"), bool)
            or not isinstance(normal.get("worker_pid"), int)
            or int(normal["worker_pid"]) <= 0
            or normal.get("cleared") is not True
            or normal.get("prior_binding_restored") is not False
            or normal.get("restored_hwnd") is not None
            or normal.get("artifact_is_authorization") is not False
            or normal.get("execute_binding_enabled") is not False
            or normal.get("content_sha256") != content_sha256(normal)
        ):
            raise ValueError("worker binding normal clear receipt differs")
        rebuilt: dict[str, object] = {
            "contract_version": _BENCHMARK_V2_WINDOW_ADOPTION_CONTRACT,
            "worker_id": generic_receipt["worker_id"],
            "run_id": generic_receipt["run_id"],
            "stage": generic_receipt["stage"],
            "operation_id": generic_receipt["operation_id"],
            "task_kind": "vision_observe_screen",
            "binding_payload_sha256": serialized["payload_sha256"],
            "worker_payload_sha256": worker_payload_sha256,
            "worker_result_sha256": worker_result_sha256,
            "capture_sha256": serialized["capture_sha256"],
            "uia_root_hwnd": serialized["expected_uia_root_hwnd"],
            "uia_owner_pid": serialized["expected_uia_owner_pid"],
            "snapshot_ref": snapshot_ref,
            "normal_clear_receipt_ref": normal["content_sha256"],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        rebuilt["content_sha256"] = content_sha256(rebuilt)
        return rebuilt
    except (TypeError, ValueError) as error:
        raise LearningWorkflowStageOperationError(
            f"benchmark-v2 worker binding adoption invalid: {error}"
        ) from error


def build_learning_pipeline_initial_worker_request(
    *,
    learning_pipeline_mode: str = "incumbent",
    payload: dict[str, Any],
) -> dict[str, Any]:
    """构造显式流水线模式的首个受管 worker 请求。"""

    mode = normalize_learning_pipeline_mode(learning_pipeline_mode)
    if not isinstance(payload, dict):
        raise LearningWorkflowStageOperationError(
            "learning pipeline payload must be an object"
        )
    _reject_client_benchmark_v2_window_binding(payload)
    if mode == "incumbent":
        return {
            "task_kind": "vision_observe_screen",
            "payload": deepcopy(payload),
        }

    required = {
        "run_id",
        "workflow_revision",
        "hybrid_capture_bundle_ref",
        "request_ref",
        "registration_ref",
        "manifest_ref",
        "capture_image_path",
        "hybrid_config",
        "capture_bundle",
    }
    missing = sorted(field for field in required if field not in payload)
    if missing:
        raise LearningWorkflowStageOperationError(
            f"Hybrid pipeline payload missing: {', '.join(missing)}"
        )
    orchestration = {
        "run_id": deepcopy(payload["run_id"]),
        "workflow_revision": deepcopy(payload["workflow_revision"]),
        "hybrid_capture_bundle_ref": deepcopy(
            payload["hybrid_capture_bundle_ref"]
        ),
        "capture_image_path": deepcopy(payload["capture_image_path"]),
        "hybrid_config": deepcopy(payload["hybrid_config"]),
        "capture_bundle": deepcopy(payload["capture_bundle"]),
    }
    omni_payload = {
        key: deepcopy(payload[key])
        for key in (
            "run_id",
            "workflow_revision",
            "hybrid_capture_bundle_ref",
            "request_ref",
            "registration_ref",
            "manifest_ref",
            "capture_image_path",
        )
    }
    omni_payload.update(
        {
            "learning_pipeline_mode": "hybrid_v1_1",
            "_hybrid_orchestration": orchestration,
        }
    )
    return {
        "task_kind": "panel_learning_hybrid_omni_discovery",
        "payload": omni_payload,
    }


def project_learning_workflow_runtime_attachment(
    *,
    workflow_state: dict[str, Any],
    worker_registry: Any,
) -> dict[str, Any]:
    """区分持久化 running 状态与当前进程真实持有的 worker。"""

    current_stage = str(workflow_state.get("current_stage") or "")
    stage_record = (
        workflow_state.get("stages", {}).get(current_stage)
        if isinstance(workflow_state.get("stages"), dict)
        else None
    )
    result = {
        "contract_version": "learning_workflow_runtime_attachment_v1",
        "stage": current_stage or None,
        "operation_id": None,
        "worker_id": None,
        "worker_status": None,
        "worker_confirmed": False,
        "journal_confirmed": False,
        "runtime_attached": False,
        "result_available": False,
        "result_adopted": False,
        "status": "not_applicable",
        "recovery_status": "none",
    }
    if not isinstance(stage_record, dict) or stage_record.get("status") != "running":
        return result
    evidence_refs = stage_record.get("evidence_refs")
    stage_execution = (
        evidence_refs.get("stage_execution")
        if isinstance(evidence_refs, dict)
        else None
    )
    if (
        not isinstance(stage_execution, dict)
        or stage_execution.get("contract_version")
        != LEARNING_WORKFLOW_STAGE_OPERATION_CONTRACT_VERSION
        or stage_execution.get("owner") != "backend_lease"
    ):
        result["status"] = "running_not_managed"
        return result

    operation_id = str(stage_execution.get("operation_id") or "")
    result["operation_id"] = operation_id or None
    attachment = worker_registry.attachment_by_operation(
        run_id=str(workflow_state.get("run_id") or ""),
        stage=current_stage,
        operation_id=operation_id,
    )
    if not isinstance(attachment, dict):
        result["status"] = "running_detached"
        result["recovery_status"] = "recovery_required"
        return result

    worker_status = str(attachment.get("status") or "unknown")
    runtime_attached = attachment.get("runtime_attached") is True
    result_available = attachment.get("result_available") is True
    result_adopted = attachment.get("result_adopted") is True
    result.update(
        {
            "worker_id": attachment.get("worker_id"),
            "worker_status": worker_status,
            "worker_confirmed": runtime_attached,
            "journal_confirmed": True,
            "runtime_attached": runtime_attached,
            "result_available": result_available,
            "result_adopted": result_adopted,
        }
    )
    if worker_status == "running" and runtime_attached:
        result["status"] = "running_attached"
    elif worker_status in {"running", "detached_running"}:
        result["status"] = "running_detached"
        result["recovery_status"] = "recovery_required"
    else:
        result["status"] = "worker_finished"
        if worker_status == "completed" and result_available:
            result["recovery_status"] = (
                "result_adopted" if result_adopted else "result_available"
            )
        elif worker_status == "failed":
            result["recovery_status"] = "worker_failed"
        elif worker_status in {"cancelled", "cancel_failed"}:
            result["recovery_status"] = "worker_cancelled"
        else:
            result["recovery_status"] = "result_pending"
    return result


def transition_learning_workflow_run(
    *,
    store: LearningWorkflowRunStore,
    project_root: str | Path,
    run_id: str,
    expected_revision: int,
    stage: str,
    outcome: str,
    reason: str = "",
    evidence_refs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """在同一服务边界内完成证据校验和工作流状态迁移。"""

    previous_state = store.get(run_id) if outcome == "completed" else None
    verified_evidence_refs = verify_learning_workflow_completion_evidence(
        stage=stage,
        outcome=outcome,
        evidence_refs=evidence_refs or {},
        project_root=project_root,
        previous_state=previous_state,
    )
    return store.transition(
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        outcome=outcome,
        reason=reason,
        evidence_refs=verified_evidence_refs,
    )


def start_learning_workflow_stage_operation(
    *,
    store: LearningWorkflowRunStore,
    project_root: str | Path,
    run_id: str,
    expected_revision: int,
    stage: str,
    reason: str = "",
    lease_seconds: int = 600,
    now: datetime | None = None,
    operation_id: str | None = None,
    learning_pipeline_mode: str = "incumbent",
) -> dict[str, Any]:
    """由服务端签发阶段租约，并将对应阶段推进为 running。"""

    if not isinstance(lease_seconds, int) or lease_seconds < 1:
        raise LearningWorkflowStageOperationError(
            "lease_seconds must be a positive integer"
        )
    issued_at = _utc_datetime(now)
    normalized_operation_id = str(operation_id or uuid4()).strip()
    if not normalized_operation_id:
        raise LearningWorkflowStageOperationError("operation_id is required")
    lease_expires_at = issued_at + timedelta(seconds=lease_seconds)
    pipeline_mode = normalize_learning_pipeline_mode(learning_pipeline_mode)
    stage_execution = {
        "contract_version": LEARNING_WORKFLOW_STAGE_OPERATION_CONTRACT_VERSION,
        "operation_id": normalized_operation_id,
        "stage": stage,
        "owner": "backend_lease",
        "started_at": issued_at.isoformat(),
        "lease_expires_at": lease_expires_at.isoformat(),
    }
    if pipeline_mode == "hybrid_v1_1":
        stage_execution["learning_pipeline_mode"] = pipeline_mode
    state = transition_learning_workflow_run(
        store=store,
        project_root=project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        outcome="running",
        reason=reason,
        evidence_refs={"stage_execution": stage_execution},
    )
    return {
        "contract_version": LEARNING_WORKFLOW_STAGE_OPERATION_CONTRACT_VERSION,
        "operation_id": normalized_operation_id,
        "stage": stage,
        "status": "running",
        "started_at": issued_at.isoformat(),
        "lease_expires_at": lease_expires_at.isoformat(),
        "workflow_state": state,
    }


def heartbeat_learning_workflow_stage_operation(
    *,
    store: LearningWorkflowRunStore,
    project_root: str | Path,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    lease_seconds: int = 600,
    now: datetime | None = None,
) -> dict[str, Any]:
    """续租当前受管阶段，并将续租记录写入可回放事件历史。"""

    if not isinstance(lease_seconds, int) or lease_seconds < 1:
        raise LearningWorkflowStageOperationError(
            "lease_seconds must be a positive integer"
        )
    current = store.get(run_id)
    _require_revision(current, expected_revision)
    stage_execution = _managed_stage_execution(current, stage)
    normalized_operation_id = str(operation_id or "").strip()
    if stage_execution["operation_id"] != normalized_operation_id:
        raise LearningWorkflowStageOperationError(
            "operation_id does not match the active stage operation"
        )
    heartbeat_at = _utc_datetime(now)
    current_expiry = _parse_utc_datetime(
        stage_execution.get("lease_expires_at"),
        field="lease_expires_at",
    )
    if heartbeat_at > current_expiry:
        raise LearningWorkflowStageOperationError(
            "stage operation lease expired before heartbeat"
        )

    renewed_expiry = max(
        current_expiry,
        heartbeat_at + timedelta(seconds=lease_seconds),
    )
    renewed_execution = deepcopy(stage_execution)
    heartbeat_count = renewed_execution.get("heartbeat_count", 0)
    if not isinstance(heartbeat_count, int) or heartbeat_count < 0:
        raise LearningWorkflowStageOperationError(
            "stage operation heartbeat_count is invalid"
        )
    renewed_execution.update(
        {
            "last_heartbeat_at": heartbeat_at.isoformat(),
            "heartbeat_count": heartbeat_count + 1,
            "lease_expires_at": renewed_expiry.isoformat(),
        }
    )
    stage_record = current["stages"][stage]
    state = transition_learning_workflow_run(
        store=store,
        project_root=project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        outcome="running",
        reason=str(stage_record.get("reason") or ""),
        evidence_refs={"stage_execution": renewed_execution},
    )
    return {
        "contract_version": LEARNING_WORKFLOW_STAGE_OPERATION_CONTRACT_VERSION,
        "operation_id": normalized_operation_id,
        "stage": stage,
        "status": "running",
        "started_at": renewed_execution["started_at"],
        "last_heartbeat_at": renewed_execution["last_heartbeat_at"],
        "heartbeat_count": renewed_execution["heartbeat_count"],
        "lease_expires_at": renewed_execution["lease_expires_at"],
        "workflow_state": state,
    }


def cancel_learning_workflow_stage_operation(
    *,
    store: LearningWorkflowRunStore,
    project_root: str | Path,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    reason: str,
    now: datetime | None = None,
    backend_compute_termination: str = "not_covered",
    model_service_compute_termination: str = "not_covered",
    worker_id: str | None = None,
    model_request_id: str | None = None,
    model_request_cancellation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """取消当前受管阶段的状态所有权，不伪装成已终止后端计算。"""

    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise LearningWorkflowStageOperationError(
            "stage operation cancellation requires a reason"
        )
    stage_execution = require_active_learning_workflow_stage_operation(
        store=store,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        operation_id=operation_id,
        now=now,
        expiry_action="cancellation",
    )
    normalized_operation_id = str(operation_id or "").strip()
    cancelled_at = _utc_datetime(now)
    normalized_compute_termination = str(
        backend_compute_termination or "not_covered"
    ).strip()
    if normalized_compute_termination not in {
        "not_covered",
        "not_running",
        "terminated",
        "termination_failed",
    }:
        raise LearningWorkflowStageOperationError(
            "backend_compute_termination is invalid"
        )
    normalized_model_termination = str(
        model_service_compute_termination or "not_covered"
    ).strip()
    if normalized_model_termination not in {
        "not_covered",
        "not_supported",
        "request_not_active",
        "cancellation_acknowledged_pending",
        "terminated",
        "cancel_failed",
    }:
        raise LearningWorkflowStageOperationError(
            "model_service_compute_termination is invalid"
        )

    cancelled_execution = deepcopy(stage_execution)
    cancellation = {
        "contract_version": "learning_workflow_stage_cancellation_v1",
        "requested_at": cancelled_at.isoformat(),
        "requested_by": "panel_user",
        "state_cancellation": "completed",
        "backend_compute_termination": normalized_compute_termination,
        "model_service_compute_termination": normalized_model_termination,
    }
    normalized_worker_id = str(worker_id or "").strip()
    if normalized_worker_id:
        cancellation["worker_id"] = normalized_worker_id
    normalized_model_request_id = str(model_request_id or "").strip()
    if normalized_model_request_id:
        cancellation["model_request_id"] = normalized_model_request_id
    if isinstance(model_request_cancellation, dict):
        cancellation["model_request_cancellation"] = deepcopy(
            model_request_cancellation
        )
    cancelled_execution.update(
        {
            "finished_at": cancelled_at.isoformat(),
            "result_outcome": "safe_stopped",
            "cancellation": cancellation,
        }
    )
    state = transition_learning_workflow_run(
        store=store,
        project_root=project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        outcome="safe_stopped",
        reason=normalized_reason,
        evidence_refs={"stage_execution": cancelled_execution},
    )
    return {
        "contract_version": LEARNING_WORKFLOW_STAGE_OPERATION_CONTRACT_VERSION,
        "operation_id": normalized_operation_id,
        "stage": stage,
        "status": "safe_stopped",
        "cancellation_status": "state_cancelled",
        "backend_compute_termination": normalized_compute_termination,
        "model_service_compute_termination": normalized_model_termination,
        "worker_id": normalized_worker_id or None,
        "model_request_id": normalized_model_request_id or None,
        "started_at": stage_execution["started_at"],
        "lease_expires_at": stage_execution["lease_expires_at"],
        "finished_at": cancelled_at.isoformat(),
        "workflow_state": state,
    }


def require_active_learning_workflow_stage_operation(
    *,
    store: LearningWorkflowRunStore,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    now: datetime | None = None,
    expiry_action: str = "worker execution",
) -> dict[str, Any]:
    """验证 worker 只绑定当前未过期 operation，不修改工作流状态。"""

    current = store.get(run_id)
    _require_revision(current, expected_revision)
    stage_execution = _managed_stage_execution(current, stage)
    normalized_operation_id = str(operation_id or "").strip()
    if stage_execution["operation_id"] != normalized_operation_id:
        raise LearningWorkflowStageOperationError(
            "operation_id does not match the active stage operation"
        )
    checked_at = _utc_datetime(now)
    lease_expires_at = _parse_utc_datetime(
        stage_execution.get("lease_expires_at"),
        field="lease_expires_at",
    )
    if checked_at > lease_expires_at:
        raise LearningWorkflowStageOperationError(
            f"stage operation lease expired before {expiry_action}"
        )
    return deepcopy(stage_execution)


def finish_learning_workflow_stage_operation(
    *,
    store: LearningWorkflowRunStore,
    project_root: str | Path,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    outcome: str,
    reason: str = "",
    evidence_refs: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """仅接收当前未过期租约持有者提交的阶段结果。"""

    if outcome not in {"completed", "failed", "safe_stopped"}:
        raise LearningWorkflowStageOperationError(
            "stage operation outcome must complete, fail, or safe stop"
        )
    current = store.get(run_id)
    _require_revision(current, expected_revision)
    stage_execution = _managed_stage_execution(current, stage)
    normalized_operation_id = str(operation_id or "").strip()
    if stage_execution["operation_id"] != normalized_operation_id:
        raise LearningWorkflowStageOperationError(
            "operation_id does not match the active stage operation"
        )
    finished_at = _utc_datetime(now)
    lease_expires_at = _parse_utc_datetime(
        stage_execution.get("lease_expires_at"),
        field="lease_expires_at",
    )
    if finished_at > lease_expires_at:
        raise LearningWorkflowStageOperationError(
            "stage operation lease expired before result completion"
        )

    finished_execution = deepcopy(stage_execution)
    finished_execution.update(
        {
            "finished_at": finished_at.isoformat(),
            "result_outcome": outcome,
        }
    )
    structured_evidence = (
        deepcopy(evidence_refs) if isinstance(evidence_refs, dict) else {}
    )
    structured_evidence["stage_execution"] = finished_execution
    state = transition_learning_workflow_run(
        store=store,
        project_root=project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        outcome=outcome,
        reason=reason,
        evidence_refs=structured_evidence,
    )
    return {
        "contract_version": LEARNING_WORKFLOW_STAGE_OPERATION_CONTRACT_VERSION,
        "operation_id": normalized_operation_id,
        "stage": stage,
        "status": outcome,
        "started_at": stage_execution["started_at"],
        "lease_expires_at": stage_execution["lease_expires_at"],
        "finished_at": finished_at.isoformat(),
        "workflow_state": state,
    }


def _managed_hybrid_large_review_projection(
    *,
    orchestration: dict[str, Any],
    managed_projection: dict[str, Any],
) -> dict[str, Any]:
    """从已验证 managed 父证据构建 Task 8 只读投影。"""

    bundle = orchestration.get("capture_bundle")
    inventory = orchestration.get("omni_inventory")
    bindings = orchestration.get("qwen_bindings")
    fusion = orchestration.get("fusion_result")
    if not all(isinstance(item, dict) for item in (bundle, inventory, bindings, fusion)):
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review parent evidence is incomplete"
        )
    normalized_parents: list[dict[str, Any]] = []
    for label, parent in (
        ("Omni inventory", inventory),
        ("Qwen bindings", bindings),
        ("fusion result", fusion),
    ):
        declared = parent.get("content_sha256")
        if declared != content_sha256(parent):
            raise LearningWorkflowStageOperationError(
                f"managed Hybrid review {label} hash mismatch"
            )
        normalized = deepcopy(parent)
        normalized.pop("content_sha256", None)
        normalized_parents.append(normalized)
    inventory, bindings, fusion = normalized_parents
    inventory_by_id = {
        item.get("candidate_id"): item
        for item in inventory.get("candidates", [])
        if isinstance(item, dict)
    }
    vista_proposals: list[dict[str, Any]] = []
    for proposal in managed_projection.get("proposals", []):
        if not isinstance(proposal, dict):
            raise LearningWorkflowStageOperationError(
                "managed Hybrid review proposal is invalid"
            )
        candidate_id = proposal.get("candidate_id")
        candidate = inventory_by_id.get(candidate_id)
        roi_source = proposal.get("roi_ref")
        point = proposal.get("canonical_point")
        if (
            not isinstance(candidate, dict)
            or not isinstance(roi_source, dict)
            or not isinstance(point, dict)
        ):
            raise LearningWorkflowStageOperationError(
                "managed Hybrid review proposal lost parent evidence"
            )
        bbox_ref = seal_immutable(
            {
                "contract_version": "hybrid_candidate_bbox_ref_v1",
                "candidate_id": candidate_id,
                "provider_result_ref": deepcopy(candidate["provider_result_ref"]),
                "coordinate_space": candidate["coordinate_space"],
                "xyxy": deepcopy(candidate["bbox_original"]),
            }
        )
        roi_ref = seal_immutable(
            {
                "contract_version": "hybrid_permitted_roi_v1",
                "roi_id": roi_source["roi_id"],
                "candidate_id": candidate_id,
                "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
                "coordinate_space": roi_source["coordinate_space"],
                "xyxy": deepcopy(roi_source["xyxy"]),
                "permitted_for_refinement": True,
            }
        )
        vista_proposals.append(
            {
                "candidate_id": candidate_id,
                "fusion_state": "BOUND",
                "candidate_bbox_ref": bbox_ref,
                "roi_ref": roi_ref,
                "point": deepcopy(point),
                "confidence": 0.0,
                "evidence": [
                    "managed_hybrid_review_projection/"
                    + str(managed_projection.get("content_sha256") or "")
                ],
                "status": proposal.get("status"),
                "review_required": True,
            }
        )
    try:
        return project_hybrid_review(
            capture_bundle=bundle,
            omni_inventory=inventory,
            qwen_bindings=bindings,
            fusion_result=fusion,
            vista_proposals={
                "contract_version": "hybrid_vista_proposals_v1",
                "capture_identity": deepcopy(bundle["capture_identity"]),
                "proposals": vista_proposals,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "final_submit_forbidden": True,
                "real_action_requires_gate": True,
                "authorization_scope": "display_and_review_only",
            },
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise LearningWorkflowStageOperationError(
            f"managed Hybrid review could not build Task 8 projection · {exc}"
        ) from exc


def _persist_managed_hybrid_review_trial(
    *,
    project_root: str | Path,
    run_id: str,
    workflow_revision: int,
    operation_id: str,
    worker_id: str,
    result_sha256: str,
    response: dict[str, Any],
    current: dict[str, Any],
) -> str:
    """将服务端接纳的 Hybrid review 结果固化为既有 trial 格式。"""

    if (
        response.get("contract_version")
        != "learning_hybrid_managed_stage_result_v1"
        or response.get("learning_pipeline_mode") != "hybrid_v1_1"
        or response.get("task_kind")
        != "panel_learning_hybrid_review_projection"
        or response.get("outcome") != "completed"
    ):
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review worker response is invalid"
        )
    stage_execution = _managed_stage_execution(current, "screen_understanding")
    lineage = response.get("supervisor_lineage")
    if (
        not isinstance(lineage, dict)
        or lineage.get("run_id") != run_id
        or lineage.get("workflow_revision") != workflow_revision
        or lineage.get("operation_id") != operation_id
        or lineage.get("stage") != "screen_understanding"
        or stage_execution.get("operation_id") != operation_id
    ):
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review supervisor lineage is stale"
        )
    orchestration = response.get("orchestration")
    projection = response.get("result")
    if not isinstance(orchestration, dict) or not isinstance(projection, dict):
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review lost projection lineage"
        )
    if (
        orchestration.get("run_id") != run_id
        or orchestration.get("workflow_revision") != workflow_revision
    ):
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review orchestration is stale"
        )
    bundle_ref = orchestration.get("hybrid_capture_bundle_ref")
    if not isinstance(bundle_ref, dict):
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review capture bundle ref is missing"
        )
    root = Path(project_root).resolve()
    try:
        bundle = load_and_verify_hybrid_capture_bundle(
            project_root=root,
            bundle_ref=deepcopy(bundle_ref),
            expected_run_id=run_id,
            expected_workflow_revision=workflow_revision,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise LearningWorkflowStageOperationError(
            f"managed Hybrid review capture bundle is invalid · {exc}"
        ) from exc
    orchestration_bundle = orchestration.get("capture_bundle")
    if (
        not isinstance(orchestration_bundle, dict)
        or orchestration_bundle.get("bundle_ref") != bundle_ref
        or orchestration_bundle.get("capture_lineage_ref")
        != bundle.get("capture_lineage_ref")
    ):
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review capture bundle lineage mismatch"
        )
    if projection.get("hybrid_capture_bundle_ref") != bundle_ref:
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review projection bundle lineage mismatch"
        )
    proposals = projection.get("proposals")
    if not isinstance(proposals, list):
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review projection proposals are invalid"
        )
    capture_lineage_ref = bundle.get("capture_lineage_ref")
    for proposal in proposals:
        roi_ref = proposal.get("roi_ref") if isinstance(proposal, dict) else None
        if (
            not isinstance(roi_ref, dict)
            or roi_ref.get("capture_lineage_ref") != capture_lineage_ref
        ):
            raise LearningWorkflowStageOperationError(
                "managed Hybrid review projection capture lineage mismatch"
            )
    if (
        projection.get("contract_version") != "hybrid_review_projection_v1"
        or projection.get("outcome") != "completed"
        or projection.get("review_status") != "REVIEW_REQUIRED"
        or projection.get("automatic_acceptance") is not False
        or projection.get("execute_binding_enabled") is not False
        or projection.get("no_live_click_authorization") is not True
    ):
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review projection is authorizing"
        )
    capture_image_path = str(orchestration.get("capture_image_path") or "").strip()
    if not capture_image_path:
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review capture image path is missing"
        )
    image_path = (root / capture_image_path).resolve()
    try:
        image_path.relative_to(root)
    except ValueError as exc:
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review capture image path escaped project root"
        ) from exc
    if (
        not image_path.is_file()
        or hashlib.sha256(image_path.read_bytes()).hexdigest()
        != bundle["capture_identity"]["artifact_sha256"]
    ):
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review capture image identity mismatch"
        )
    exact_worker_id = str(worker_id or "").strip()
    exact_result_sha256 = str(result_sha256 or "").strip()
    if not exact_worker_id or len(exact_result_sha256) != 64:
        raise LearningWorkflowStageOperationError(
            "managed Hybrid review adopted result identity is incomplete"
        )
    managed_lineage = {
        "run_id": run_id,
        "workflow_revision": workflow_revision,
        "operation_id": operation_id,
        "worker_id": exact_worker_id,
        "result_sha256": exact_result_sha256,
        "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
        "hybrid_capture_bundle_ref": deepcopy(bundle_ref),
    }
    large_review_projection = _managed_hybrid_large_review_projection(
        orchestration=orchestration,
        managed_projection=projection,
    )
    trial = {
        "contract_version": "learning_template_draft_v1",
        "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
        "states": [],
        "regions": [],
        "action_templates": [],
        "page_details": {
            "screen": {
                "source_image_path": image_path.relative_to(root).as_posix(),
                "source_image_sha256": bundle["capture_identity"][
                    "artifact_sha256"
                ],
            }
        },
        "hybrid_review_projection": large_review_projection,
        "managed_hybrid_review_projection": deepcopy(projection),
        "managed_hybrid_lineage": managed_lineage,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
    }
    encoded = (
        json.dumps(trial, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    identity_bytes = json.dumps(
        managed_lineage,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    trial_id = hashlib.sha256(identity_bytes).hexdigest()
    trial_path = (
        root
        / "artifacts"
        / "learning-runs"
        / "hybrid-managed-review"
        / f"trial_{trial_id}.json"
    )
    trial_path.parent.mkdir(parents=True, exist_ok=True)
    if trial_path.exists():
        if trial_path.read_bytes() != encoded:
            raise LearningWorkflowStageOperationError(
                "managed Hybrid review trial identity collision"
            )
    else:
        temporary = trial_path.with_name(
            f".{trial_path.name}.{uuid4().hex}.tmp"
        )
        temporary.write_bytes(encoded)
        temporary.replace(trial_path)
    return trial_path.relative_to(root).as_posix()


def continue_learning_stage_worker_result(
    *,
    store: LearningWorkflowRunStore,
    worker_registry: Any,
    project_root: str | Path,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    worker_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """解释已接纳结果，并在成功终结后签发唯一下一阶段租约。"""

    adopted = worker_registry.read_adopted_result(
        worker_id=worker_id,
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
    )
    receipt = adopted.get("receipt")
    response = adopted.get("response")
    if not isinstance(receipt, dict) or not isinstance(response, dict):
        raise LearningWorkflowStageOperationError(
            "adopted worker result is missing receipt or response"
        )
    task_kind = str(receipt.get("task_kind") or "").strip()
    result_sha256 = str(receipt.get("result_sha256") or "").strip()
    normalized_worker_id = str(worker_id or "").strip()
    if not task_kind or not result_sha256 or not normalized_worker_id:
        raise LearningWorkflowStageOperationError(
            "adopted worker result identity is incomplete"
        )

    response_for_return = deepcopy(response)
    current = store.get(run_id)
    learning_pipeline_mode = normalize_learning_pipeline_mode(
        _learning_pipeline_mode_for_stage(current, stage)
    )
    if task_kind == "vision_observe_screen" and response.get("success") is True:
        response = _verify_hybrid_observe_handoff(
            response=response,
            project_root=project_root,
            run_id=run_id,
            expected_revision=expected_revision,
            current=current,
        )
    decision = _interpret_hybrid_post_calibration_worker_result(
        stage=stage,
        task_kind=task_kind,
        response=response,
    ) if learning_pipeline_mode == "hybrid_v1_1" else None
    if decision is None:
        decision = interpret_learning_stage_worker_result(
            stage=stage,
            task_kind=task_kind,
            response=response,
            learning_pipeline_mode=learning_pipeline_mode,
        )
    artifact_request = decision.pop("artifact_request", None)
    replay = _matching_worker_continuation_replay(
        workflow_state=current,
        stage=stage,
        operation_id=operation_id,
        worker_id=normalized_worker_id,
        task_kind=task_kind,
        result_sha256=result_sha256,
    )
    if replay:
        next_stage_operation, current = _ensure_next_managed_stage_operation(
            store=store,
            project_root=project_root,
            run_id=run_id,
            completed_stage=stage,
            outcome=str(replay["outcome"]),
            now=now,
        )
        next_stage_worker = _start_next_managed_stage_worker(
            store=store,
            worker_registry=worker_registry,
            project_root=project_root,
            run_id=run_id,
            completed_stage=stage,
            workflow_state=current,
            next_stage_operation=next_stage_operation,
            now=now,
        )
        return {
            **decision,
            "stage_finished": True,
            "continuation_status": "terminal_result",
            "outcome": replay["outcome"],
            "response": response_for_return,
            "workflow_state": current,
            "idempotent_replay": True,
            "next_stage_operation": deepcopy(next_stage_operation),
            "next_stage_worker": deepcopy(next_stage_worker),
        }

    if (
        learning_pipeline_mode == "hybrid_v1_1"
        and stage == "screen_understanding"
        and task_kind == "panel_learning_hybrid_review_projection"
        and decision.get("stage_finished") is True
        and decision.get("outcome") == "completed"
    ):
        trial_path = _persist_managed_hybrid_review_trial(
            project_root=project_root,
            run_id=run_id,
            workflow_revision=expected_revision,
            operation_id=str(operation_id or "").strip(),
            worker_id=normalized_worker_id,
            result_sha256=result_sha256,
            response=response,
            current=current,
        )
        decision = deepcopy(decision)
        decision["evidence_refs"] = {
            **deepcopy(decision.get("evidence_refs") or {}),
            "trial_path": trial_path,
        }

    if decision["stage_finished"] is not True:
        require_active_learning_workflow_stage_operation(
            store=store,
            run_id=run_id,
            expected_revision=expected_revision,
            stage=stage,
            operation_id=operation_id,
            now=now,
            expiry_action="worker result continuation",
        )
        next_worker_request = decision.get("next_worker")
        next_worker = None
        if isinstance(next_worker_request, dict):
            next_task_kind = str(
                next_worker_request.get("task_kind") or ""
            ).strip()
            next_payload = next_worker_request.get("payload")
            if not next_task_kind or not isinstance(next_payload, dict):
                raise LearningWorkflowStageOperationError(
                    "worker continuation next_worker contract is invalid"
                )
            next_worker = worker_registry.start(
                run_id=run_id,
                stage=stage,
                operation_id=operation_id,
                task_kind=next_task_kind,
                payload=deepcopy(next_payload),
                reuse_active_identical=True,
                **(
                    {"authoritative_workflow_revision": expected_revision}
                    if next_payload.get("learning_pipeline_mode") == "hybrid_v1_1"
                    else {}
                ),
            )
            decision = {
                **decision,
                "continuation_status": "next_worker_started",
            }
        return {
            **decision,
            "response": response_for_return,
            "workflow_state": current,
            "idempotent_replay": False,
            "next_worker": deepcopy(next_worker),
        }

    if (
        stage == "precise_calibration"
        and task_kind == "panel_learning_calibration_sequence"
        and decision["outcome"] == "completed"
    ):
        try:
            if not isinstance(artifact_request, dict):
                raise LearningCalibrationArtifactError(
                    "calibration sequence did not provide artifact inputs"
                )
            artifact_result = create_learning_calibration_artifact(
                run_id=run_id,
                trace_path=artifact_request.get("trace_path") or "",
                source_image_path=artifact_request.get("source_image_path") or "",
                numbering_report_path=(
                    artifact_request.get("numbering_report_path") or ""
                ),
                overlay_path=artifact_request.get("overlay_path") or "",
                project_root=project_root,
            )
        except (LearningCalibrationArtifactError, OSError) as exc:
            decision = {
                **decision,
                "outcome": "failed",
                "reason": f"calibration artifact persistence failed · {exc}",
                "evidence_refs": {},
            }
        else:
            artifact = (
                artifact_result.get("artifact")
                if isinstance(artifact_result.get("artifact"), dict)
                else {}
            )
            decision = {
                **decision,
                "evidence_refs": {
                    "result_path": str(
                        artifact_result.get("result_path") or ""
                    ).strip(),
                    "overlay_path": str(
                        artifact.get("overlay_path") or ""
                    ).strip(),
                },
            }

    continuation_evidence = deepcopy(decision["evidence_refs"])
    continuation_evidence["worker_continuation"] = {
        "contract_version": LEARNING_STAGE_WORKER_CONTINUATION_CONTRACT_VERSION,
        "worker_id": normalized_worker_id,
        "operation_id": str(operation_id or "").strip(),
        "task_kind": task_kind,
        "result_sha256": result_sha256,
    }
    finished = finish_learning_workflow_stage_operation(
        store=store,
        project_root=project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        operation_id=operation_id,
        outcome=str(decision["outcome"]),
        reason=str(decision["reason"]),
        evidence_refs=continuation_evidence,
        now=now,
    )
    next_stage_operation, workflow_state = _ensure_next_managed_stage_operation(
        store=store,
        project_root=project_root,
        run_id=run_id,
        completed_stage=stage,
        outcome=str(decision["outcome"]),
        now=now,
    )
    next_stage_worker = _start_next_managed_stage_worker(
        store=store,
        worker_registry=worker_registry,
        project_root=project_root,
        run_id=run_id,
        completed_stage=stage,
        workflow_state=workflow_state,
        next_stage_operation=next_stage_operation,
        now=now,
    )
    return {
        **decision,
        "response": response_for_return,
        "workflow_state": workflow_state,
        "idempotent_replay": False,
        "next_stage_operation": deepcopy(next_stage_operation),
        "next_stage_worker": deepcopy(next_stage_worker),
    }


def _verify_hybrid_observe_handoff(
    *, response: dict[str, Any], project_root: str | Path, run_id: str,
    expected_revision: int, current: dict[str, Any],
) -> dict[str, Any]:
    verified_response = deepcopy(response)
    data = verified_response.get("data")
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        result = data["result"]
    elif isinstance(verified_response.get("result"), dict):
        result = verified_response["result"]
    else:
        result = verified_response
    result.pop("_hybrid_capture_bundle_verified", None)
    bundle_ref = result.get("hybrid_capture_bundle_ref")
    if bundle_ref is None:
        return verified_response
    _require_revision(current, expected_revision)
    current_revision = current.get("revision")
    if isinstance(current_revision, bool) or not isinstance(current_revision, int):
        raise LearningWorkflowStageOperationError(
            "authoritative workflow revision is invalid"
        )
    try:
        load_and_verify_hybrid_capture_bundle(
            project_root=Path(project_root),
            bundle_ref=bundle_ref,
            expected_run_id=run_id,
            expected_workflow_revision=current_revision,
        )
    except (OSError, TypeError, ValueError) as error:
        raise LearningWorkflowStageOperationError(
            f"hybrid capture handoff verification failed: {error}"
        ) from error
    result["_hybrid_capture_bundle_verified"] = True
    return verified_response


def _ensure_next_managed_stage_operation(
    *,
    store: LearningWorkflowRunStore,
    project_root: str | Path,
    run_id: str,
    completed_stage: str,
    outcome: str,
    now: datetime | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    current = store.get(run_id)
    if (
        str(completed_stage or "").strip() == "screen_understanding"
        and normalize_learning_pipeline_mode(
            _learning_pipeline_mode_for_stage(current, completed_stage)
        )
        == "hybrid_v1_1"
    ):
        return None, current
    next_spec = _NEXT_MANAGED_STAGE.get(str(completed_stage or "").strip())
    if outcome != "completed" or next_spec is None:
        return None, current

    next_stage, task_kind, reason = next_spec
    stages = current.get("stages")
    next_record = stages.get(next_stage) if isinstance(stages, dict) else None
    if (
        current.get("current_stage") == next_stage
        and isinstance(next_record, dict)
        and next_record.get("status") == "running"
    ):
        execution = _managed_stage_execution(current, next_stage)
        return (
            _next_stage_operation_descriptor(
                execution=execution,
                task_kind=task_kind,
            ),
            current,
        )

    completed_record = (
        stages.get(completed_stage) if isinstance(stages, dict) else None
    )
    if (
        current.get("current_stage") != completed_stage
        or not isinstance(completed_record, dict)
        or completed_record.get("status") != "completed"
        or not isinstance(next_record, dict)
        or next_record.get("status") != "pending"
    ):
        return None, current

    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=project_root,
        run_id=run_id,
        expected_revision=int(current["revision"]),
        stage=next_stage,
        reason=reason,
        lease_seconds=_BACKEND_CONTINUATION_LEASE_SECONDS,
        now=now,
    )
    return (
        {
            "contract_version": (
                LEARNING_WORKFLOW_NEXT_STAGE_OPERATION_CONTRACT_VERSION
            ),
            "operation_id": started["operation_id"],
            "stage": started["stage"],
            "status": started["status"],
            "started_at": started["started_at"],
            "lease_expires_at": started["lease_expires_at"],
            "task_kind": task_kind,
            "owner": "backend_continuation",
        },
        started["workflow_state"],
    )


def _start_next_managed_stage_worker(
    *,
    store: LearningWorkflowRunStore,
    worker_registry: Any,
    project_root: str | Path,
    run_id: str,
    completed_stage: str,
    workflow_state: dict[str, Any],
    next_stage_operation: dict[str, Any] | None,
    now: datetime | None,
) -> dict[str, Any] | None:
    if not isinstance(next_stage_operation, dict):
        return None
    try:
        payload = _build_next_managed_stage_payload(
            project_root=project_root,
            completed_stage=completed_stage,
            workflow_state=workflow_state,
        )
        if payload is None:
            raise LearningWorkflowStageOperationError(
                "backend continuation produced no next-stage worker payload"
            )
        return worker_registry.start(
            run_id=run_id,
            stage=str(next_stage_operation["stage"]),
            operation_id=str(next_stage_operation["operation_id"]),
            task_kind=str(next_stage_operation["task_kind"]),
            payload=payload,
            reuse_active_identical=True,
            **(
                {
                    "authoritative_workflow_revision": int(
                        workflow_state["revision"]
                    )
                }
                if payload.get("learning_pipeline_mode") == "hybrid_v1_1"
                else {}
            ),
        )
    except Exception as exc:
        failure_reason = f"backend continuation worker start failed · {exc}"
        try:
            finish_learning_workflow_stage_operation(
                store=store,
                project_root=project_root,
                run_id=run_id,
                expected_revision=int(workflow_state["revision"]),
                stage=str(next_stage_operation["stage"]),
                operation_id=str(next_stage_operation["operation_id"]),
                outcome="failed",
                reason=failure_reason,
                evidence_refs={
                    "worker_start_failure": {
                        "contract_version": "learning_stage_worker_start_failure_v1",
                        "task_kind": str(next_stage_operation["task_kind"]),
                        "details": str(exc),
                    }
                },
                now=now,
            )
        except Exception as close_exc:
            raise LearningWorkflowStageOperationError(
                f"{failure_reason}; operation close failed · {close_exc}"
            ) from exc
        raise LearningWorkflowStageOperationError(failure_reason) from exc


def _build_next_managed_stage_payload(
    *,
    project_root: str | Path,
    completed_stage: str,
    workflow_state: dict[str, Any],
) -> dict[str, Any] | None:
    evidence_refs = _completed_stage_evidence(workflow_state, completed_stage)
    if completed_stage == "review_repair":
        report_path = _required_evidence_text(evidence_refs, "final_stage2_report_path")
        report = _load_continuation_json(
            project_root=project_root,
            path_value=report_path,
            label="reviewed Stage2 report",
        )
        observe_bundle = (
            report.get("observe_bundle")
            if isinstance(report.get("observe_bundle"), dict)
            else {}
        )
        fusion = (
            report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
        )
        source_image_path = str(
            report.get("source_image_path")
            or observe_bundle.get("image_path")
            or observe_bundle.get("source_image_path")
            or ""
        ).strip()
        if not source_image_path:
            raise LearningWorkflowStageOperationError(
                "reviewed Stage2 report is missing source image evidence"
            )
        screen_reading = (
            observe_bundle.get("screen_reading")
            if isinstance(observe_bundle.get("screen_reading"), dict)
            else {}
        )
        screen_summary = str(
            screen_reading.get("screen_summary") or ""
        ).strip()
        overlay_path = str(
            evidence_refs.get("final_repaired_overlay_path")
            or fusion.get("compiled_overlay_path")
            or fusion.get("full_screen_understanding_overlay_path")
            or ""
        ).strip()
        review_boxes = (
            deepcopy(fusion.get("fused_review_boxes"))
            if isinstance(fusion.get("fused_review_boxes"), list)
            else []
        )
        return {
            "app_name": str(report.get("app_name") or "unknown_app").strip()
            or "unknown_app",
            "state_hint": str(report.get("state_hint") or "").strip(),
            "summary": screen_summary
            or "learn a reusable UI workflow template from this screen",
            "observation_evidence": {
                "contract_version": "panel_learning_draft_observation_evidence_v1",
                "evidence_source": "backend_managed_continuation",
                "model_roles": {
                    "screen_understanding": {
                        "stage": "Learn Fast",
                        "expected_model_family": "8B",
                    },
                    "coordinate_calibration": {
                        "stage": "Learn Deep",
                        "expected_model_family": "4B",
                        "status": "model_validation_completed",
                    },
                },
                "current_image_path": source_image_path,
                "screen_size": deepcopy(observe_bundle.get("screen_size"))
                if isinstance(observe_bundle.get("screen_size"), dict)
                else {},
                "screen_summary": screen_summary,
                "screen_map": deepcopy(observe_bundle.get("screen_map"))
                if isinstance(observe_bundle.get("screen_map"), dict)
                else None,
                "coordinate_overlay_path": overlay_path,
                "calibrated_targets": [],
                "review_boxes": review_boxes,
                "evidence_quality": (
                    "review_boxes_available_no_executable_targets"
                    if review_boxes
                    else "screenshot_only_no_recent_learn_deep"
                ),
                "no_click_authorization": True,
                "execute_binding_enabled": False,
            },
            "two_stage_report_path": report_path,
        }
    if completed_stage == "precise_calibration":
        result_path = _required_evidence_text(evidence_refs, "result_path")
        calibration = _load_continuation_json(
            project_root=project_root,
            path_value=result_path,
            label="calibration result",
        )
        numbering_report_path = str(
            calibration.get("numbering_report_path") or ""
        ).strip()
        source_image_path = str(calibration.get("source_image_path") or "").strip()
        overlay_path = str(calibration.get("overlay_path") or "").strip()
        if not numbering_report_path or not source_image_path or not overlay_path:
            raise LearningWorkflowStageOperationError(
                "calibration result is missing review-repair evidence"
            )
        return {
            "two_stage_report_path": numbering_report_path,
            "screenshot_path": source_image_path,
            "composite_overlay_path": overlay_path,
            "model_profile_id": "learn_mode_qwen3_vl_8b",
            "timeout_seconds": 240,
        }
    if completed_stage == "numbered_map":
        report_path = _required_evidence_text(evidence_refs, "report_path")
        report = _load_continuation_json(
            project_root=project_root,
            path_value=report_path,
            label="numbered map report",
        )
        observe_bundle = (
            report.get("observe_bundle")
            if isinstance(report.get("observe_bundle"), dict)
            else {}
        )
        stage2 = (
            report.get("stage2_numbering")
            if isinstance(report.get("stage2_numbering"), dict)
            else {}
        )
        candidate_count = int(stage2.get("calibration_candidate_count") or 0)
        if candidate_count <= 0:
            raise LearningWorkflowStageOperationError(
                "numbered map report has no calibration candidates"
            )
        source_revision = str(
            report.get("source_graph_revision")
            or stage2.get("source_graph_revision")
            or stage2.get("graph_revision")
            or (
                stage2.get("final_numbering", {}).get("revision")
                if isinstance(stage2.get("final_numbering"), dict)
                else ""
            )
            or ""
        ).strip()
        if not source_revision:
            raise LearningWorkflowStageOperationError(
                "numbered map report is missing calibration source revision"
            )
        source_image_path = str(
            observe_bundle.get("image_path")
            or observe_bundle.get("source_image_path")
            or report.get("source_image_override")
            or ""
        ).strip()
        if not source_image_path:
            raise LearningWorkflowStageOperationError(
                "numbered map report is missing source image evidence"
            )
        observe_trace_path = str(
            report.get("source_trace_path")
            or observe_bundle.get("trace_path")
            or ""
        ).strip()
        return {
            "contract_version": (
                LEARNING_CALIBRATION_SEQUENCE_REQUEST_CONTRACT_VERSION
            ),
            "profile_id": None,
            "candidate_count": candidate_count,
            "calibration_source_revision": source_revision,
            "maximum_batch_size": 8,
            "locate_payload": {
                "goal": "learn all visible controls",
                "provider_mode": "local_grounding",
                "capture_live": False,
                "image_path": source_image_path,
                "app_name": str(report.get("app_name") or "unknown").strip()
                or "unknown",
                "state_hint": str(report.get("state_hint") or "unknown").strip()
                or "unknown",
                "observe_trace_path": observe_trace_path or None,
                "agent_mode": "learn",
                "learn_depth": "deep",
                "dry_run": True,
                "trace": True,
                "metadata": {
                    "learning_interface_flow": True,
                    "no_live_click_authorization": True,
                    "learn_all_targets": True,
                    "two_stage_report_path": report_path,
                },
            },
        }
    if completed_stage != "screen_understanding":
        return None
    trial_path = _required_evidence_text(evidence_refs, "trial_path")
    trial = _load_continuation_json(
        project_root=project_root,
        path_value=trial_path,
        label="screen understanding trial",
    )
    observe_bundle = (
        trial.get("observe_bundle")
        if isinstance(trial.get("observe_bundle"), dict)
        else {}
    )
    source_image_path = str(
        observe_bundle.get("image_path")
        or observe_bundle.get("source_image_path")
        or ""
    ).strip()
    if not source_image_path:
        raise LearningWorkflowStageOperationError(
            "screen understanding trial is missing source image evidence"
        )
    return {
        "app_name": str(trial.get("app_name") or "unknown").strip() or "unknown",
        "state_hint": str(trial.get("state_hint") or "unknown").strip() or "unknown",
        "trace_path": trial_path,
        "source_image_path": source_image_path,
        "require_stage1_gate": True,
        "stage2_region_strategy": "partitioned",
    }


def _completed_stage_evidence(
    workflow_state: dict[str, Any],
    stage: str,
) -> dict[str, Any]:
    stages = workflow_state.get("stages")
    stage_record = stages.get(stage) if isinstance(stages, dict) else None
    evidence_refs = (
        stage_record.get("evidence_refs") if isinstance(stage_record, dict) else None
    )
    if not isinstance(evidence_refs, dict):
        raise LearningWorkflowStageOperationError(
            f"{stage} completion evidence is missing"
        )
    return evidence_refs


def _required_evidence_text(evidence_refs: dict[str, Any], field: str) -> str:
    value = str(evidence_refs.get(field) or "").strip()
    if not value:
        raise LearningWorkflowStageOperationError(
            f"completion evidence is missing {field}"
        )
    return value


def _load_continuation_json(
    *,
    project_root: str | Path,
    path_value: str,
    label: str,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    candidate = Path(path_value)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise LearningWorkflowStageOperationError(
            f"{label} path escapes project root"
        ) from exc
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LearningWorkflowStageOperationError(
            f"{label} could not be loaded: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise LearningWorkflowStageOperationError(f"{label} must be a JSON object")
    return payload


def _next_stage_operation_descriptor(
    *,
    execution: dict[str, Any],
    task_kind: str,
) -> dict[str, Any]:
    return {
        "contract_version": LEARNING_WORKFLOW_NEXT_STAGE_OPERATION_CONTRACT_VERSION,
        "operation_id": str(execution.get("operation_id") or ""),
        "stage": str(execution.get("stage") or ""),
        "status": "running",
        "started_at": execution.get("started_at"),
        "lease_expires_at": execution.get("lease_expires_at"),
        "task_kind": task_kind,
        "owner": "backend_continuation",
    }


def _interpret_hybrid_post_calibration_worker_result(
    *,
    stage: str,
    task_kind: str,
    response: dict[str, Any],
) -> dict[str, Any] | None:
    """只解释 Hybrid 的校准后两步，避免进入 incumbent review-repair。"""

    if task_kind not in {
        "panel_learning_calibration_sequence",
        "panel_learning_hybrid_review_projection",
    }:
        return None
    if stage != "screen_understanding":
        raise LearningWorkflowStageOperationError(
            "Hybrid post-calibration task must remain in screen_understanding"
        )
    if (
        not isinstance(response, dict)
        or response.get("contract_version")
        != "learning_hybrid_managed_stage_result_v1"
        or response.get("learning_pipeline_mode") != "hybrid_v1_1"
        or response.get("task_kind") != task_kind
    ):
        raise LearningWorkflowStageOperationError(
            "Hybrid post-calibration worker result contract is invalid"
        )
    result = response.get("result")
    orchestration = response.get("orchestration")
    if not isinstance(result, dict) or not isinstance(orchestration, dict):
        raise LearningWorkflowStageOperationError(
            "Hybrid post-calibration result lost orchestration lineage"
        )
    if response.get("outcome") != "completed":
        return {
            "stage": stage,
            "task_kind": task_kind,
            "stage_finished": True,
            "continuation_status": "terminal_result",
            "outcome": "safe_stopped",
            "reason": f"SAFE_STOP · {task_kind} failed",
            "evidence_refs": {},
        }
    if task_kind == "panel_learning_hybrid_review_projection":
        if (
            result.get("contract_version") != "hybrid_review_projection_v1"
            or result.get("outcome") != "completed"
            or result.get("review_status") != "REVIEW_REQUIRED"
            or result.get("automatic_acceptance") is not False
            or result.get("completed_count") != len(result.get("proposals") or [])
            or result.get("requested_candidate_ids") != result.get("completed_candidate_ids")
        ):
            raise LearningWorkflowStageOperationError(
                "Hybrid review projection result is invalid"
            )
        return {
            "stage": stage,
            "task_kind": task_kind,
            "stage_finished": True,
            "continuation_status": "terminal_result",
            "outcome": "completed",
            "reason": "Hybrid managed review projection completed",
            "evidence_refs": {
                "hybrid_review_projection": deepcopy(result),
                "hybrid_capture_bundle_ref": deepcopy(
                    orchestration.get("hybrid_capture_bundle_ref")
                ),
            },
        }

    sequence = _hybrid_calibration_sequence_payload(result)
    results = sequence.get("hybrid_vista_results")
    requests = sequence.get("hybrid_vista_requests")
    if (
        sequence.get("contract_version")
        != "learning_calibration_sequence_result_v1"
        or sequence.get("status") != "completed"
        or sequence.get("remaining_count") != 0
        or not isinstance(results, list)
        or not results
        or not isinstance(requests, list)
        or len(requests) != len(results)
        or sequence.get("completed_count") != len(results)
    ):
        raise LearningWorkflowStageOperationError(
            "Hybrid calibration completion is incomplete"
        )
    requested_ids = [str(item.get("candidate_id") or "") for item in requests if isinstance(item, dict)]
    result_ids = [str(item.get("candidate_id") or "") for item in results if isinstance(item, dict)]
    if requested_ids != result_ids or len(set(requested_ids)) != len(requested_ids):
        raise LearningWorkflowStageOperationError(
            "Hybrid calibration request/result identity coverage is invalid"
        )
    cleanup_receipt = sequence.get("qwen_cleanup_receipt")
    if not isinstance(cleanup_receipt, dict):
        raise LearningWorkflowStageOperationError(
            "Hybrid calibration lost Qwen cleanup receipt"
        )
    vista_cleanup_receipt = orchestration.get("vista_cleanup_receipt")
    if not isinstance(vista_cleanup_receipt, dict):
        raise LearningWorkflowStageOperationError(
            "Hybrid calibration lost VISTA cleanup receipt"
        )
    try:
        assert_next_provider_safe_to_start(
            vista_cleanup_receipt,
            "review",
            expected_lineage=response.get("supervisor_lineage"),
            expected_provider_result_sha256=content_sha256(sequence),
        )
    except RuntimeError as error:
        raise LearningWorkflowStageOperationError(str(error)) from error
    payload = {
        "learning_pipeline_mode": "hybrid_v1_1",
        "hybrid_vista_results": deepcopy(results),
        "hybrid_vista_requests": deepcopy(requests),
        "qwen_cleanup_receipt": deepcopy(cleanup_receipt),
        "vista_cleanup_receipt": deepcopy(vista_cleanup_receipt),
        "hybrid_capture_bundle_ref": deepcopy(
            orchestration.get("hybrid_capture_bundle_ref")
        ),
        "calibration_sequence": deepcopy(sequence),
        "_hybrid_orchestration": deepcopy(orchestration),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "stage": stage,
        "task_kind": task_kind,
        "stage_finished": False,
        "continuation_status": "intermediate_result",
        "outcome": None,
        "reason": "Hybrid calibration advances only to managed review projection",
        "evidence_refs": {
            "hybrid_capture_bundle_ref": deepcopy(
                orchestration.get("hybrid_capture_bundle_ref")
            )
        },
        "next_worker": {
            "task_kind": "panel_learning_hybrid_review_projection",
            "payload": payload,
            "payload_sha256": hashlib.sha256(encoded).hexdigest(),
        },
    }


def _hybrid_calibration_sequence_payload(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data")
    nested_result = data.get("result") if isinstance(data, dict) else None
    sequence = (
        nested_result.get("calibration_sequence")
        if isinstance(nested_result, dict)
        else None
    )
    if not isinstance(sequence, dict):
        sequence = result.get("calibration_sequence")
    return deepcopy(sequence) if isinstance(sequence, dict) else {}


def recover_expired_learning_workflow_stage_operation(
    *,
    store: LearningWorkflowRunStore,
    project_root: str | Path,
    run_id: str,
    expected_revision: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """将已过期的服务端托管阶段明确终止，避免刷新后永久 running。"""

    current = store.get(run_id)
    _require_revision(current, expected_revision)
    stage = str(current.get("current_stage") or "")
    stage_record = (
        current.get("stages", {}).get(stage)
        if isinstance(current.get("stages"), dict)
        else None
    )
    if not isinstance(stage_record, dict) or stage_record.get("status") != "running":
        return _recovery_result(
            current,
            recovered=False,
            status="not_running",
        )
    evidence_refs = stage_record.get("evidence_refs")
    stage_execution = (
        evidence_refs.get("stage_execution")
        if isinstance(evidence_refs, dict)
        else None
    )
    if (
        not isinstance(stage_execution, dict)
        or stage_execution.get("contract_version")
        != LEARNING_WORKFLOW_STAGE_OPERATION_CONTRACT_VERSION
        or stage_execution.get("owner") != "backend_lease"
    ):
        return _recovery_result(
            current,
            recovered=False,
            status="not_managed",
        )

    recovered_at = _utc_datetime(now)
    lease_expires_at = _parse_utc_datetime(
        stage_execution.get("lease_expires_at"),
        field="lease_expires_at",
    )
    if recovered_at <= lease_expires_at:
        return _recovery_result(
            current,
            recovered=False,
            status="lease_active",
        )

    recovered_execution = deepcopy(stage_execution)
    recovered_execution.update(
        {
            "finished_at": recovered_at.isoformat(),
            "result_outcome": "failed",
            "recovery_status": "expired_operation_failed",
        }
    )
    state = transition_learning_workflow_run(
        store=store,
        project_root=project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        outcome="failed",
        reason=f"{stage} stage operation lease expired",
        evidence_refs={"stage_execution": recovered_execution},
    )
    return _recovery_result(
        state,
        recovered=True,
        status="expired_operation_failed",
    )


def _learning_pipeline_mode_for_stage(
    state: dict[str, Any],
    stage: str,
) -> object:
    stages = state.get("stages")
    record = stages.get(stage) if isinstance(stages, dict) else None
    evidence_refs = record.get("evidence_refs") if isinstance(record, dict) else None
    execution = (
        evidence_refs.get("stage_execution")
        if isinstance(evidence_refs, dict)
        else None
    )
    if not isinstance(execution, dict):
        return "incumbent"
    return execution.get("learning_pipeline_mode", "incumbent")


def _managed_stage_execution(
    state: dict[str, Any],
    stage: str,
) -> dict[str, Any]:
    if state.get("current_stage") != stage:
        raise LearningWorkflowStageOperationError(
            f"stage is not the active workflow stage: {stage}"
        )
    stages = state.get("stages")
    record = stages.get(stage) if isinstance(stages, dict) else None
    if not isinstance(record, dict) or record.get("status") != "running":
        raise LearningWorkflowStageOperationError(f"stage is not running: {stage}")
    evidence_refs = record.get("evidence_refs")
    execution = (
        evidence_refs.get("stage_execution")
        if isinstance(evidence_refs, dict)
        else None
    )
    if (
        not isinstance(execution, dict)
        or execution.get("contract_version")
        != LEARNING_WORKFLOW_STAGE_OPERATION_CONTRACT_VERSION
        or execution.get("owner") != "backend_lease"
    ):
        raise LearningWorkflowStageOperationError(
            "stage is not managed by a backend lease"
        )
    if str(execution.get("stage") or "") != stage:
        raise LearningWorkflowStageOperationError(
            "stage operation evidence does not match the active stage"
        )
    return deepcopy(execution)


def _require_revision(state: dict[str, Any], expected_revision: int) -> None:
    current_revision = state.get("revision")
    if current_revision != expected_revision:
        raise LearningWorkflowStageOperationError(
            f"workflow revision conflict: expected {expected_revision}, "
            f"current {current_revision}"
        )


def _utc_datetime(value: datetime | None) -> datetime:
    candidate = value or datetime.now(timezone.utc)
    if candidate.tzinfo is None:
        raise LearningWorkflowStageOperationError(
            "stage operation timestamps must include a timezone"
        )
    return candidate.astimezone(timezone.utc)


def _parse_utc_datetime(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise LearningWorkflowStageOperationError(
            f"stage operation {field} is missing"
        )
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise LearningWorkflowStageOperationError(
            f"stage operation {field} is invalid"
        ) from exc
    return _utc_datetime(parsed)


def _recovery_result(
    state: dict[str, Any],
    *,
    recovered: bool,
    status: str,
) -> dict[str, Any]:
    return {
        "contract_version": LEARNING_WORKFLOW_STAGE_OPERATION_CONTRACT_VERSION,
        "recovered": recovered,
        "recovery_status": status,
        "workflow_state": state,
    }


def _matching_worker_continuation_replay(
    *,
    workflow_state: dict[str, Any],
    stage: str,
    operation_id: str,
    worker_id: str,
    task_kind: str,
    result_sha256: str,
) -> dict[str, str] | None:
    stages = workflow_state.get("stages")
    stage_record = stages.get(stage) if isinstance(stages, dict) else None
    if not isinstance(stage_record, dict):
        return None
    outcome = str(stage_record.get("status") or "").strip()
    if outcome not in {"completed", "failed", "safe_stopped"}:
        return None
    evidence_refs = stage_record.get("evidence_refs")
    if not isinstance(evidence_refs, dict):
        return None
    continuation = evidence_refs.get("worker_continuation")
    stage_execution = evidence_refs.get("stage_execution")
    if not isinstance(continuation, dict) or not isinstance(stage_execution, dict):
        return None
    expected = {
        "worker_id": worker_id,
        "operation_id": str(operation_id or "").strip(),
        "task_kind": task_kind,
        "result_sha256": result_sha256,
    }
    if any(str(continuation.get(key) or "").strip() != value for key, value in expected.items()):
        return None
    if str(stage_execution.get("operation_id") or "").strip() != expected[
        "operation_id"
    ]:
        return None
    return {"outcome": outcome}
