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
from app.learn.recognition.uei.canonical import content_sha256, seal_immutable
from app.learn.hybrid.gpu_lifecycle import (
    assert_next_provider_safe_to_start,
    release_hybrid_provider,
    validate_hybrid_cleanup_receipt,
    validate_hybrid_lineage,
)
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
HYBRID_PROVIDER_OWNER_CONTRACT_VERSION = "hybrid_supervised_provider_owner_v1"
HYBRID_PROVIDER_RUNTIME_CONTRACT_VERSION = "hybrid_supervised_provider_runtime_v1"
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
HYBRID_STAGE_HANDLER_REGISTRY = {
    "panel_learning_hybrid_omni_discovery": {
        "handler": "run_hybrid_omni_task",
        "provider": "omni",
        "previous_cleanup_receipt": None,
    },
    "panel_learning_hybrid_qwen_binding": {
        "handler": "run_hybrid_qwen_task",
        "provider": "qwen",
        "previous_cleanup_receipt": "omni_cleanup_receipt",
    },
    "panel_learning_hybrid_fusion": {
        "handler": "run_hybrid_fusion_task",
        "provider": None,
        "previous_cleanup_receipt": None,
    },
    "panel_learning_calibration_sequence": {
        "handler": "run_learning_calibration_sequence",
        "provider": "vista",
        "previous_cleanup_receipt": "qwen_gpu_cleanup_receipt",
    },
    "panel_learning_hybrid_review_projection": {
        "handler": "run_hybrid_review_projection_task",
        "provider": "review",
        "previous_cleanup_receipt": "vista_cleanup_receipt",
    },
}
HYBRID_LIFECYCLE_COMPONENT_REGISTRY = {
    "start_guard": ("worker", "_assert_hybrid_provider_start_guard"),
    "omni_cleanup_observer": ("worker", "_observe_hybrid_omni_cleanup"),
    "qwen_cleanup_observer": ("model_server", "observe_hybrid_qwen_cleanup"),
    "vista_cleanup_observer": ("model_server", "release_hybrid_vista_model_lease"),
    "supervisor_reconciliation": ("worker", "_reconcile_supervised_vista_record"),
    "review_guard": ("worker", "_assert_hybrid_provider_start_guard"),
    "windows_owner_scope": ("process_scope", "windows_process_scope_available"),
    "explicit_handle_scope": ("process_scope", "scoped_process_launch_ready"),
    "owner_lineage_validator": ("worker", "_load_hybrid_provider_owner"),
    "omni_abnormal_reconciler": ("omni_adapter", "reconcile_omniparser_invocation_owner"),
    "qwen_abnormal_reconciler": ("model_server", "reconcile_hybrid_qwen_owner"),
}
_MODEL_READY_WAIT_SECONDS = 180.0
_HYBRID_OMNI_CLEANUP_WAIT_SECONDS = 35.0
_HYBRID_VISTA_CLEANUP_WAIT_SECONDS = 35.0
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LearningStageWorkerError(ValueError):
    """学习阶段 worker 请求无效或不属于当前 operation。"""


def run_learning_calibration_sequence(
    payload: dict[str, Any],
    **kwargs: Any,
) -> Any:
    """延迟解析既有校准处理器，保留测试替换和真实注册链。"""
    from app.learn.calibration_sequence import (
        run_learning_calibration_sequence as calibration_handler,
    )

    return calibration_handler(payload, **kwargs)


def resolve_hybrid_stage_handler(task_kind: str) -> Callable[..., Any]:
    spec = HYBRID_STAGE_HANDLER_REGISTRY.get(str(task_kind or "").strip())
    if not isinstance(spec, dict):
        raise LearningStageWorkerError(f"Hybrid handler is not registered: {task_kind}")
    handler_name = str(spec.get("handler") or "").strip()
    handler = globals().get(handler_name)
    if not callable(handler):
        raise LearningStageWorkerError(
            f"Hybrid registered handler is unavailable: {handler_name}"
        )
    return handler


def hybrid_registered_handler_chain_ready() -> bool:
    return bool(hybrid_registered_lifecycle_status()["ready"])


def hybrid_registered_lifecycle_status() -> dict[str, Any]:
    expected_lifecycle = {
        "panel_learning_hybrid_omni_discovery": ("omni", None),
        "panel_learning_hybrid_qwen_binding": ("qwen", "omni_cleanup_receipt"),
        "panel_learning_hybrid_fusion": (None, None),
        "panel_learning_calibration_sequence": ("vista", "qwen_gpu_cleanup_receipt"),
        "panel_learning_hybrid_review_projection": ("review", "vista_cleanup_receipt"),
    }
    expected_components = {
        "start_guard": ("worker", "_assert_hybrid_provider_start_guard"),
        "omni_cleanup_observer": ("worker", "_observe_hybrid_omni_cleanup"),
        "qwen_cleanup_observer": ("model_server", "observe_hybrid_qwen_cleanup"),
        "vista_cleanup_observer": ("model_server", "release_hybrid_vista_model_lease"),
        "supervisor_reconciliation": ("worker", "_reconcile_supervised_vista_record"),
        "review_guard": ("worker", "_assert_hybrid_provider_start_guard"),
        "windows_owner_scope": ("process_scope", "windows_process_scope_available"),
        "explicit_handle_scope": ("process_scope", "scoped_process_launch_ready"),
        "owner_lineage_validator": ("worker", "_load_hybrid_provider_owner"),
        "omni_abnormal_reconciler": ("omni_adapter", "reconcile_omniparser_invocation_owner"),
        "qwen_abnormal_reconciler": ("model_server", "reconcile_hybrid_qwen_owner"),
    }
    components: dict[str, bool] = {}
    for component, (owner, function_name) in expected_components.items():
        configured = HYBRID_LIFECYCLE_COMPONENT_REGISTRY.get(component)
        if owner == "worker":
            resolved = globals().get(function_name)
        elif owner == "model_server":
            from app.core import model_server

            resolved = getattr(model_server, function_name, None)
        elif owner == "omni_adapter":
            from app.learn.recognition.uei import omniparser_shadow_adapter

            resolved = getattr(omniparser_shadow_adapter, function_name, None)
        else:
            from app.learn.hybrid import windows_process_scope

            resolved = getattr(windows_process_scope, function_name, None)
        components[component] = (
            configured == (owner, function_name)
            and callable(resolved)
            and (resolved() is True if owner == "process_scope" else True)
        )
    try:
        handlers_ready = set(HYBRID_STAGE_HANDLER_REGISTRY) == set(expected_lifecycle) and all(
            callable(resolve_hybrid_stage_handler(task_kind))
            and (
                HYBRID_STAGE_HANDLER_REGISTRY[task_kind].get("provider"),
                HYBRID_STAGE_HANDLER_REGISTRY[task_kind].get(
                    "previous_cleanup_receipt"
                ),
            )
            == lifecycle
            for task_kind, lifecycle in expected_lifecycle.items()
        )
    except LearningStageWorkerError:
        handlers_ready = False
    components["handlers"] = handlers_ready
    return {
        "contract_version": "hybrid_registered_lifecycle_status_v1",
        "ready": all(components.values()),
        "components": components,
    }


def _assert_hybrid_provider_start_guard(
    task_kind: str,
    orchestration: object,
    *,
    supervisor_lineage: object,
    execution_payload: dict[str, Any],
) -> None:
    spec = HYBRID_STAGE_HANDLER_REGISTRY.get(task_kind)
    if not isinstance(spec, dict):
        raise LearningStageWorkerError(f"Hybrid handler is not registered: {task_kind}")
    receipt_name = spec.get("previous_cleanup_receipt")
    if receipt_name is None:
        return
    if not isinstance(orchestration, dict) or not isinstance(
        orchestration.get(str(receipt_name)), dict
    ):
        raise LearningStageWorkerError(
            f"{receipt_name} is required before Hybrid provider start"
        )
    try:
        expected_result_sha256 = _hybrid_previous_provider_result_sha256(
            task_kind,
            orchestration=orchestration,
            execution_payload=execution_payload,
        )
        assert_next_provider_safe_to_start(
            orchestration[str(receipt_name)],
            str(spec.get("provider") or ""),
            expected_lineage=validate_hybrid_lineage(supervisor_lineage),
            expected_provider_result_sha256=expected_result_sha256,
        )
    except (TypeError, ValueError, RuntimeError) as error:
        raise LearningStageWorkerError(str(error)) from error


def _hybrid_previous_provider_result_sha256(
    task_kind: str,
    *,
    orchestration: object,
    execution_payload: dict[str, Any],
) -> str:
    context = orchestration if isinstance(orchestration, dict) else {}
    if task_kind == "panel_learning_hybrid_qwen_binding":
        value = context.get("omni_inventory")
    elif task_kind == "panel_learning_calibration_sequence":
        value = context.get("qwen_bindings")
    elif task_kind == "panel_learning_hybrid_review_projection":
        value = execution_payload.get("calibration_sequence")
    else:
        raise LearningStageWorkerError(
            f"Hybrid provider predecessor is undefined for {task_kind}"
        )
    if not isinstance(value, dict):
        raise LearningStageWorkerError(
            "Hybrid previous provider result is unavailable"
        )
    return _artifact_digest(value)


def _omni_cleanup_receipt(
    result: object,
    *,
    lineage: dict[str, Any],
    predecessor_sha256: str,
) -> dict[str, Any]:
    if not isinstance(result, dict) or not isinstance(result.get("inventory"), dict):
        raise LearningStageWorkerError("Hybrid Omni cleanup result is invalid")
    inventory = _observe_hybrid_omni_cleanup(
        result,
        lineage=lineage,
        predecessor_sha256=predecessor_sha256,
        provider_result_sha256=_artifact_digest(result["inventory"]),
    )
    return release_hybrid_provider(
        "omni",
        process_inventory=lambda provider: deepcopy(inventory),
    )


def _observe_hybrid_omni_cleanup(
    result: dict[str, Any],
    *,
    lineage: dict[str, Any],
    predecessor_sha256: str,
    provider_result_sha256: str,
) -> dict[str, Any]:
    from app.learn.recognition.uei.store import UEIObjectStore
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        load_omniparser_invocation_cleanup_observation,
    )

    receipt_ref = result.get("provider_receipt_ref")
    result_ref = result.get("provider_result_ref")
    if not isinstance(receipt_ref, dict) or not isinstance(result_ref, dict):
        raise LearningStageWorkerError("Hybrid Omni provider refs are unavailable")
    store = UEIObjectStore(root=_PROJECT_ROOT / "artifacts" / "uei-shadow-store")
    receipt = store.get(receipt_ref, contract_version="provider_runtime_receipt_v1")
    persisted_result = store.get(result_ref, contract_version="provider_safe_result_v1")
    invocation_id = str(result.get("provider_invocation_id") or "").strip()
    expected_suffix = invocation_id.rsplit("/", 1)[-1]
    omni_inventory = result.get("inventory")
    refs_match = (
        receipt.get("receipt_id") == f"receipt/{expected_suffix}"
        and persisted_result.get("result_id") == f"result/{expected_suffix}"
        and receipt.get("result_ref") == result_ref
        and receipt.get("provider_id") == "local.runtime/omniparser"
        and receipt.get("profile_id") == "local.runtime/omniparser/shadow-v2"
        and receipt.get("cleanup_status") == "clean"
        and receipt.get("status") == "succeeded"
        and persisted_result.get("status") == "succeeded"
        and persisted_result.get("provider_id") == receipt.get("provider_id")
        and persisted_result.get("profile_id") == receipt.get("profile_id")
        and persisted_result.get("capture_lineage_ref")
        == receipt.get("capture_lineage_ref")
        and isinstance(omni_inventory, dict)
        and omni_inventory.get("provider_result_ref") == result_ref
    )
    cleanup_observation = load_omniparser_invocation_cleanup_observation(invocation_id)
    from app.learn.hybrid.windows_process_scope import process_scope_name

    exact_lineage = validate_hybrid_lineage(lineage)
    expected_scope_name = process_scope_name(exact_lineage, "omni")
    scope_cleanup = cleanup_observation.get("process_scope_cleanup")
    scope_acquisition = cleanup_observation.get("process_scope_acquisition")
    provider_processes = deepcopy(cleanup_observation["provider_processes_after"])
    orphan_identities = deepcopy(cleanup_observation["orphan_descendant_identities"])
    lease_files = deepcopy(cleanup_observation["lease_files_after"])
    active_listeners = deepcopy(cleanup_observation["active_listeners_after"])
    inventory_observable = cleanup_observation.get("inventory_observable") is True
    verified = (
        refs_match
        and cleanup_observation.get("cleanup_status") == "verified"
        and cleanup_observation.get("process_scope_name") == expected_scope_name
        and isinstance(scope_cleanup, dict)
        and scope_cleanup.get("scope_name") == expected_scope_name
        and scope_cleanup.get("cleanup_status") == "verified"
        and isinstance(scope_acquisition, dict)
        and scope_acquisition.get("scope_name") == expected_scope_name
        and cleanup_observation.get("process_identity", {}).get("pid")
        in scope_acquisition.get("member_pids", [])
        and inventory_observable
        and not provider_processes
        and not orphan_identities
        and not active_listeners
        and not lease_files
    )
    return {
        "contract_version": "hybrid_provider_process_inventory_v2",
        "provider": "omni",
        "observer_contract": "hybrid_omni_cleanup_observer_v1",
        "release_status": "verified" if verified else "failed",
        "termination_reason": "completed" if verified else "cleanup_failed",
        "lineage": exact_lineage,
        "provider_lease_identity": {
            "provider_invocation_id": invocation_id,
            "provider_receipt_ref": deepcopy(receipt_ref),
            "process_identity": deepcopy(cleanup_observation["process_identity"]),
            "process_scope_name": expected_scope_name,
        },
        "predecessor_sha256": predecessor_sha256,
        "provider_result_sha256": provider_result_sha256,
        "provider_processes_after": provider_processes,
        "helper_processes_after": orphan_identities,
        "orphan_descendant_pids": [identity["pid"] for identity in orphan_identities],
        "active_listeners_after": active_listeners,
        "lease_files_after": lease_files,
        "source_cleanup_evidence": {
            "contract_version": "hybrid_omni_cleanup_evidence_v2",
            "status": "verified" if verified else "failed",
            "provider_receipt": deepcopy(receipt),
            "provider_result_ref": deepcopy(result_ref),
            "inventory_observable": inventory_observable,
            "adapter_cleanup_observation": cleanup_observation,
        },
    }


def _qwen_gpu_cleanup_receipt(
    result: object,
    *,
    lineage: dict[str, Any],
    predecessor_sha256: str,
    provider_result_sha256: str,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise LearningStageWorkerError("Hybrid Qwen cleanup receipt is required")
    from app.core.model_server import observe_hybrid_qwen_cleanup

    try:
        inventory = observe_hybrid_qwen_cleanup(
            result,
            lineage=lineage,
            predecessor_sha256=predecessor_sha256,
            provider_result_sha256=provider_result_sha256,
        )
    except ValueError as error:
        raise LearningStageWorkerError(str(error)) from error
    return release_hybrid_provider(
        "qwen",
        process_inventory=lambda provider: deepcopy(inventory),
    )


def _artifact_digest(value: object) -> str:
    if not isinstance(value, dict):
        raise LearningStageWorkerError("Hybrid predecessor artifact is unavailable")
    declared = value.get("content_sha256")
    if isinstance(declared, str) and len(declared) == 64:
        if _is_immutable_ref(value):
            return declared
        if declared != content_sha256(value):
            raise LearningStageWorkerError(
                "Hybrid predecessor artifact seal mismatch"
            )
        return declared
    return content_sha256(value)


def _hybrid_provider_lineage(
    *, run_id: str, workflow_revision: int, operation_id: str, stage: str
) -> dict[str, Any]:
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


def _write_hybrid_provider_owner(
    path: Path,
    *,
    worker_id: str,
    task_kind: str,
    model_request_id: str,
    provider: str,
    lineage: dict[str, Any],
    process_scope_name_value: str,
    runtime_file: str,
    predecessor_sha256: str,
) -> dict[str, Any]:
    document = seal_immutable({
        "contract_version": HYBRID_PROVIDER_OWNER_CONTRACT_VERSION,
        "worker_id": worker_id,
        "task_kind": task_kind,
        "model_request_id": model_request_id,
        "provider": provider,
        "lineage": validate_hybrid_lineage(lineage),
        "process_scope_name": process_scope_name_value,
        "provider_runtime_file": runtime_file,
        "predecessor_sha256": predecessor_sha256,
    })
    _write_json_atomic(path, document)
    return document


def _load_hybrid_provider_owner(
    path: Path,
    *,
    identity: dict[str, str],
    workflow_revision: int,
    journal_scope_name: str,
    runtime_file: str,
) -> dict[str, Any]:
    from app.learn.hybrid.windows_process_scope import (
        process_scope_name,
        validate_process_scope_name,
    )

    document = _read_json_object(path, label="Hybrid provider owner")
    if document.get("content_sha256") != content_sha256(document):
        raise LearningStageWorkerError("Hybrid provider owner seal is invalid")
    provider = str(
        HYBRID_STAGE_HANDLER_REGISTRY.get(identity["task_kind"], {}).get("provider")
        or ""
    )
    lineage = _hybrid_provider_lineage(
        run_id=identity["run_id"],
        workflow_revision=workflow_revision,
        operation_id=identity["operation_id"],
        stage=identity["stage"],
    )
    expected_scope = process_scope_name(lineage, provider)
    validate_process_scope_name(journal_scope_name)
    if (
        document.get("contract_version") != HYBRID_PROVIDER_OWNER_CONTRACT_VERSION
        or document.get("worker_id") != identity["worker_id"]
        or document.get("task_kind") != identity["task_kind"]
        or document.get("model_request_id") != identity["model_request_id"]
        or document.get("provider") != provider
        or document.get("lineage") != lineage
        or document.get("process_scope_name") != expected_scope
        or journal_scope_name != expected_scope
        or document.get("provider_runtime_file") != runtime_file
        or not isinstance(document.get("predecessor_sha256"), str)
        or len(str(document.get("predecessor_sha256"))) != 64
    ):
        raise LearningStageWorkerError("Hybrid provider owner lineage is invalid")
    return document


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
    supervisor_context = execution_payload.pop("_hybrid_supervisor", None)
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
        hybrid_handler: Callable[..., Any] | None = (
            resolve_hybrid_stage_handler(normalized_kind)
            if normalized_kind in HYBRID_STAGE_HANDLER_REGISTRY
            else None
        )
        if learning_pipeline_mode == "hybrid_v1_1":
            if not isinstance(supervisor_context, dict):
                raise LearningStageWorkerError(
                    "Hybrid supervisor-owned lineage is required"
                )
            supervisor_lineage = validate_hybrid_lineage(
                supervisor_context.get("lineage")
            )
            _assert_hybrid_provider_start_guard(
                normalized_kind,
                orchestration,
                supervisor_lineage=supervisor_lineage,
                execution_payload=execution_payload,
            )
        else:
            supervisor_lineage = None
        if normalized_kind == "panel_learning_hybrid_qwen_binding":
            validate_hybrid_qwen_task_payload(execution_payload)
        model_lease = _ensure_learning_stage_model_ready(
            normalized_kind,
            execution_payload,
            cancellation_event=cancellation_event,
            supervisor_context=supervisor_context,
        )
        if normalized_kind == "panel_learning_hybrid_qwen_binding":
            assert hybrid_handler is not None
            response = hybrid_handler(
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
            if learning_pipeline_mode == "hybrid_v1_1":
                qwen_bindings = response.get("qwen_bindings")
                qwen_gpu_receipt = _qwen_gpu_cleanup_receipt(
                    response["qwen_cleanup_receipt"],
                    lineage=supervisor_lineage,
                    predecessor_sha256=_artifact_digest(
                        orchestration.get("omni_inventory")
                    ),
                    provider_result_sha256=_artifact_digest(qwen_bindings),
                )
                lifecycle_evidence["qwen_gpu_cleanup_receipt"] = deepcopy(
                    qwen_gpu_receipt
                )
                assert isinstance(orchestration, dict)
                orchestration["qwen_cleanup_receipt"] = deepcopy(
                    response["qwen_cleanup_receipt"]
                )
                orchestration["qwen_gpu_cleanup_receipt"] = deepcopy(qwen_gpu_receipt)
            response = response.get("qwen_bindings")
        elif normalized_kind == "panel_learning_hybrid_fusion":
            assert hybrid_handler is not None
            response = hybrid_handler(
                execution_payload,
                cancellation_event=cancellation_event,
            )
            if learning_pipeline_mode == "hybrid_v1_1":
                response = seal_immutable(response)
        elif normalized_kind == "panel_learning_hybrid_omni_discovery":
            assert hybrid_handler is not None
            response = hybrid_handler(
                execution_payload,
                cancellation_event=cancellation_event,
            )
            if learning_pipeline_mode == "hybrid_v1_1":
                predecessor = execution_payload.get("hybrid_capture_bundle_ref")
                if not isinstance(predecessor, dict) and isinstance(orchestration, dict):
                    predecessor = orchestration.get("hybrid_capture_bundle_ref")
                omni_receipt = _omni_cleanup_receipt(
                    response,
                    lineage=supervisor_lineage,
                    predecessor_sha256=_artifact_digest(predecessor),
                )
                lifecycle_evidence["omni_cleanup_receipt"] = deepcopy(omni_receipt)
                assert isinstance(orchestration, dict)
                orchestration["omni_cleanup_receipt"] = deepcopy(omni_receipt)
        elif normalized_kind == "panel_learning_hybrid_review_projection":
            assert hybrid_handler is not None
            response = hybrid_handler(
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
            calibration_handler = (
                hybrid_handler
                if learning_pipeline_mode == "hybrid_v1_1"
                else run_learning_calibration_sequence
            )
            if cancellation_event is None:
                response = calibration_handler(execution_payload)
            else:
                response = calibration_handler(
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
                task_kind=normalized_kind,
                supervisor_context=supervisor_context,
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
    if (
        learning_pipeline_mode == "hybrid_v1_1"
        and normalized_kind == "panel_learning_calibration_sequence"
        and model_lease is not None
    ):
        try:
            vista_receipt = _release_hybrid_vista_lease(
                model_lease,
                lineage=supervisor_lineage,
                predecessor_sha256=_artifact_digest(
                    orchestration.get("fusion_result")
                ),
                provider_result_sha256=_artifact_digest(
                    _hybrid_calibration_result(response)
                ),
            )
        except BaseException as error:
            lifecycle_evidence = {
                "status": "reconciliation_failed",
                "error_type": type(error).__name__,
                "details": str(error),
            }
            return _hybrid_managed_failure_result(
                task_kind=normalized_kind,
                error=error,
                orchestration=orchestration,
                lifecycle_evidence=lifecycle_evidence,
            )
        lifecycle_evidence["vista_cleanup_receipt"] = deepcopy(vista_receipt)
        _mark_supervised_vista_released(supervisor_context, vista_receipt)
        assert isinstance(orchestration, dict)
        orchestration["vista_cleanup_receipt"] = deepcopy(vista_receipt)
    elif model_lease is not None and normalized_kind != "panel_learning_hybrid_qwen_binding":
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
            "supervisor_lineage": deepcopy(supervisor_lineage),
        }
    return normalized_response


def _reconcile_hybrid_handler_failure(
    *,
    model_lease: dict[str, Any] | None,
    error: BaseException,
    task_kind: str,
    supervisor_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if model_lease is None:
        return {"status": "model_lease_not_acquired"}
    if task_kind == "panel_learning_calibration_sequence":
        try:
            if not isinstance(supervisor_context, dict):
                raise LearningStageWorkerError("Hybrid VISTA supervisor context is unavailable")
            lease_document = _load_supervised_vista_lease(supervisor_context)
            receipt = _release_hybrid_vista_lease(
                model_lease,
                lineage=lease_document["lineage"],
                predecessor_sha256=lease_document["predecessor_sha256"],
                provider_result_sha256=content_sha256({
                    "failure_type": type(error).__name__,
                    "failure_reason": str(error),
                }),
            )
            _mark_supervised_vista_released(supervisor_context, receipt)
            return {"vista_cleanup_receipt": receipt}
        except BaseException as cleanup_error:
            error.add_note(
                "Hybrid VISTA lifecycle reconciliation failed: "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            )
            return {
                "status": "reconciliation_failed",
                "error_type": type(cleanup_error).__name__,
                "details": str(cleanup_error),
            }

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


def _release_hybrid_vista_lease(
    model_lease: dict[str, Any],
    *,
    lineage: dict[str, Any],
    predecessor_sha256: str,
    provider_result_sha256: str,
) -> dict[str, Any]:
    from app.core.model_server import release_hybrid_vista_model_lease

    inventory = release_hybrid_vista_model_lease(
        model_lease,
        lineage=lineage,
        predecessor_sha256=predecessor_sha256,
        provider_result_sha256=provider_result_sha256,
    )
    try:
        return release_hybrid_provider(
            "vista", process_inventory=lambda provider: deepcopy(inventory)
        )
    except (TypeError, ValueError, RuntimeError) as error:
        raise LearningStageWorkerError(str(error)) from error


def _hybrid_calibration_result(response: object) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise LearningStageWorkerError("Hybrid VISTA result is unavailable")
    data = response.get("data")
    nested = data.get("result") if isinstance(data, dict) else None
    sequence = (
        nested.get("calibration_sequence") if isinstance(nested, dict) else None
    )
    if not isinstance(sequence, dict):
        sequence = response.get("calibration_sequence")
    if not isinstance(sequence, dict):
        raise LearningStageWorkerError("Hybrid VISTA calibration result is unavailable")
    return deepcopy(sequence)


def _publish_supervised_vista_lease(
    supervisor_context: object,
    model_lease: dict[str, Any],
    *,
    predecessor_sha256: str,
) -> None:
    if (
        not isinstance(supervisor_context, dict)
        or supervisor_context.get("contract_version")
        != "hybrid_worker_supervisor_context_v1"
        or not isinstance(supervisor_context.get("provider_lease_path"), str)
        or not isinstance(supervisor_context.get("worker_id"), str)
    ):
        raise LearningStageWorkerError("Hybrid VISTA supervisor context is invalid")
    document = _load_supervised_vista_lease(supervisor_context)
    if document.get("state") not in {"acquiring", "recovery_required"}:
        raise LearningStageWorkerError(
            "Hybrid VISTA acquiring journal is unavailable before lease publication"
        )
    if model_lease.get("process_scope_name") != document.get("process_scope_name"):
        raise LearningStageWorkerError("Hybrid VISTA process scope mismatch")
    document.pop("content_sha256", None)
    document["state"] = "acquired"
    document["predecessor_sha256"] = predecessor_sha256
    document["model_lease"] = deepcopy(model_lease)
    document = seal_immutable(document)
    _write_json_atomic(Path(supervisor_context["provider_lease_path"]), document)


def _publish_supervised_vista_acquiring(
    supervisor_context: dict[str, Any],
    *,
    predecessor_sha256: str,
    profile_id: str | None,
) -> None:
    document = seal_immutable({
        "contract_version": "hybrid_supervised_provider_lease_v2",
        "state": "acquiring",
        "worker_id": supervisor_context["worker_id"],
        "lineage": validate_hybrid_lineage(supervisor_context.get("lineage")),
        "process_scope_name": _required_text(
            supervisor_context.get("process_scope_name"), "process_scope_name"
        ),
        "profile_id": str(profile_id or "").strip() or None,
        "predecessor_sha256": predecessor_sha256,
        "model_lease": None,
        "cleanup_receipt": None,
        "scope_cleanup_evidence": None,
    })
    _write_json_atomic(Path(supervisor_context["provider_lease_path"]), document)


def _load_supervised_vista_lease(
    supervisor_context: dict[str, Any],
) -> dict[str, Any]:
    path = Path(str(supervisor_context.get("provider_lease_path") or ""))
    document = _read_json_object(path, label="Hybrid VISTA supervisor lease")
    digest = document.pop("content_sha256", None)
    if digest != content_sha256(document):
        raise LearningStageWorkerError("Hybrid VISTA supervisor lease seal is invalid")
    if (
        document.get("contract_version") != "hybrid_supervised_provider_lease_v2"
        or document.get("worker_id") != supervisor_context.get("worker_id")
        or document.get("state")
        not in {"acquiring", "acquired", "recovery_required", "recovered", "released"}
        or not isinstance(document.get("process_scope_name"), str)
        or (
            document.get("state") in {"acquired", "released"}
            and not isinstance(document.get("model_lease"), dict)
        )
    ):
        raise LearningStageWorkerError("Hybrid VISTA supervisor lease is invalid")
    document["lineage"] = validate_hybrid_lineage(document.get("lineage"))
    document["content_sha256"] = digest
    return document


def _mark_supervised_vista_released(
    supervisor_context: object,
    cleanup_receipt: dict[str, Any],
) -> None:
    if not isinstance(supervisor_context, dict):
        raise LearningStageWorkerError("Hybrid VISTA supervisor context is invalid")
    document = _load_supervised_vista_lease(supervisor_context)
    document.pop("content_sha256", None)
    document["state"] = "released"
    document["cleanup_receipt"] = deepcopy(cleanup_receipt)
    _write_json_atomic(
        Path(supervisor_context["provider_lease_path"]),
        seal_immutable(document),
    )


def _reconcile_supervised_vista_record(record: dict[str, Any]) -> dict[str, Any]:
    """父进程用持久化 lease 或 Job Object 权威回收。"""
    context = {
        "provider_lease_path": str(record.get("provider_lease_path") or ""),
        "worker_id": str(record.get("worker_id") or ""),
        "process_scope_name": str(record.get("provider_scope_name") or ""),
    }
    try:
        document = _load_supervised_vista_lease(context)
        if document.get("state") == "released":
            receipt = document.get("cleanup_receipt")
            if not isinstance(receipt, dict):
                raise LearningStageWorkerError(
                    "released Hybrid VISTA lease lost cleanup receipt"
                )
            return {
                "contract_version": "hybrid_supervisor_reconciliation_v1",
                "status": "verified",
                "cleanup_receipt": deepcopy(receipt),
            }
        if document.get("state") == "recovered":
            evidence = document.get("scope_cleanup_evidence")
            if not isinstance(evidence, dict) or evidence.get("cleanup_status") != "verified":
                raise LearningStageWorkerError(
                    "recovered Hybrid VISTA scope lost cleanup evidence"
                )
            return {
                "contract_version": "hybrid_supervisor_reconciliation_v2",
                "status": "verified",
                "scope_cleanup_evidence": deepcopy(evidence),
            }
        if document.get("state") in {"acquiring", "recovery_required"}:
            return _reconcile_vista_scope_without_lease(record, document)
        receipt = _release_hybrid_vista_lease(
            document["model_lease"],
            lineage=document["lineage"],
            predecessor_sha256=document["predecessor_sha256"],
            provider_result_sha256=content_sha256({
                "worker_id": context["worker_id"],
                "outcome": "outer_worker_terminated",
            }),
        )
        _mark_supervised_vista_released(context, receipt)
        return {
            "contract_version": "hybrid_supervisor_reconciliation_v2",
            "status": "verified",
            "cleanup_receipt": receipt,
        }
    except BaseException as error:
        fallback = _reconcile_vista_scope_without_lease(record, None)
        if fallback.get("status") == "verified":
            return fallback
        return {
            "contract_version": "hybrid_supervisor_reconciliation_v2",
            "status": "indeterminate",
            "error_type": type(error).__name__,
            "details": str(error),
            "scope_reconciliation": fallback,
        }


def _reconcile_vista_scope_without_lease(
    record: dict[str, Any],
    document: dict[str, Any] | None,
) -> dict[str, Any]:
    from app.core.model_server import model_profile_pid_path, profile_for_stage
    from app.learn.hybrid.windows_process_scope import observe_process_scope_cleanup

    scope_name = str(
        (document or {}).get("process_scope_name")
        or record.get("provider_scope_name")
        or ""
    )
    profile_id = (document or {}).get("profile_id") or record.get("provider_profile_id")
    try:
        profile = profile_for_stage("locate", str(profile_id or "").strip() or None)
        port = int(profile.get("port") or 0)
        evidence = observe_process_scope_cleanup(
            scope_name,
            terminate=True,
            listener_ports=[port] if port > 0 else [],
            pid_file=model_profile_pid_path(profile),
            remove_owned_pid_file=True,
            stable_zero_observations=3,
        )
    except BaseException as error:
        return {
            "contract_version": "hybrid_supervisor_reconciliation_v2",
            "status": "indeterminate",
            "error_type": type(error).__name__,
            "details": str(error),
        }
    if evidence.get("cleanup_status") != "verified":
        return {
            "contract_version": "hybrid_supervisor_reconciliation_v2",
            "status": "indeterminate",
            "scope_cleanup_evidence": evidence,
        }
    if isinstance(document, dict):
        document.pop("content_sha256", None)
        document["state"] = "recovered"
        document["scope_cleanup_evidence"] = deepcopy(evidence)
        _write_json_atomic(
            Path(str(record.get("provider_lease_path") or "")),
            seal_immutable(document),
        )
    return {
        "contract_version": "hybrid_supervisor_reconciliation_v2",
        "status": "verified",
        "scope_cleanup_evidence": evidence,
    }


def _reconcile_hybrid_provider_scope_record(
    record: dict[str, Any],
) -> dict[str, Any]:
    if record.get("provider_recovery_blocked") is True:
        return {
            "contract_version": "hybrid_supervisor_reconciliation_v3",
            "status": "indeterminate",
            "details": str(record.get("provider_owner_error") or "provider owner is invalid"),
        }
    if record.get("task_kind") == "panel_learning_calibration_sequence":
        return _reconcile_supervised_vista_record(record)
    if record.get("task_kind") == "panel_learning_hybrid_omni_discovery":
        try:
            from app.learn.recognition.uei.omniparser_shadow_adapter import (
                reconcile_omniparser_invocation_owner,
            )

            evidence = reconcile_omniparser_invocation_owner(
                Path(str(record.get("provider_runtime_path") or "")),
                expected_lineage=validate_hybrid_lineage(record.get("provider_lineage")),
                expected_scope_name=str(record.get("provider_scope_name") or ""),
            )
        except BaseException as error:
            return {
                "contract_version": "hybrid_supervisor_reconciliation_v3",
                "status": "indeterminate",
                "error_type": type(error).__name__,
                "details": str(error),
            }
        return {
            "contract_version": "hybrid_supervisor_reconciliation_v3",
            "status": "verified" if evidence.get("status") == "verified" else "indeterminate",
            "provider_cleanup_evidence": evidence,
            "scope_cleanup_evidence": deepcopy(
                evidence.get("cleanup_observation", {}).get("process_scope_cleanup")
            ),
        }
    if record.get("task_kind") == "panel_learning_hybrid_qwen_binding":
        try:
            from app.core.model_server import reconcile_hybrid_qwen_owner

            evidence = reconcile_hybrid_qwen_owner(
                Path(str(record.get("provider_runtime_path") or "")),
                expected_lineage=validate_hybrid_lineage(record.get("provider_lineage")),
                expected_scope_name=str(record.get("provider_scope_name") or ""),
            )
        except BaseException as error:
            return {
                "contract_version": "hybrid_supervisor_reconciliation_v3",
                "status": "indeterminate",
                "error_type": type(error).__name__,
                "details": str(error),
            }
        return {
            "contract_version": "hybrid_supervisor_reconciliation_v3",
            "status": "verified" if evidence.get("status") == "verified" else "indeterminate",
            "provider_cleanup_evidence": evidence,
            "scope_cleanup_evidence": deepcopy(evidence.get("scope_cleanup_evidence")),
        }
    from app.learn.hybrid.windows_process_scope import observe_process_scope_cleanup

    scope_name = str(record.get("provider_scope_name") or "")
    listener_ports: list[int] = []
    pid_file = None
    evidence = observe_process_scope_cleanup(
        scope_name,
        terminate=True,
        listener_ports=listener_ports,
        pid_file=pid_file,
        remove_owned_pid_file=pid_file is not None,
        stable_zero_observations=3,
    )
    return {
        "contract_version": "hybrid_supervisor_reconciliation_v2",
        "status": (
            "verified"
            if evidence.get("cleanup_status") == "verified"
            else "indeterminate"
        ),
        "scope_cleanup_evidence": evidence,
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
    supervisor_context: dict[str, Any] | None = None,
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
        if (
            task_kind == "panel_learning_calibration_sequence"
            and payload.get("learning_pipeline_mode") == "hybrid_v1_1"
        ):
            from app.core.model_server import build_hybrid_vista_model_lease
            try:
                lease = build_hybrid_vista_model_lease(profile, readiness)
            except ValueError as error:
                raise LearningStageWorkerError(str(error)) from error
            _publish_supervised_vista_lease(
                supervisor_context,
                lease,
                predecessor_sha256=_artifact_digest(payload.get("hybrid_fusion_result")),
            )
            return lease
        return None

    managed_vista_acquisition = (
        task_kind == "panel_learning_calibration_sequence"
        and payload.get("learning_pipeline_mode") == "hybrid_v1_1"
    )
    if (
        (task_kind in _MANAGED_QWEN_TASK_KINDS or managed_vista_acquisition)
        and cancellation_event is not None
        and hasattr(cancellation_event, "run_if_not_cancelled")
    ):
        allowed, result = cancellation_event.run_if_not_cancelled(
            "vista_ensure_and_lease"
            if managed_vista_acquisition
            else "qwen_ensure_and_lease",
            ensure_and_publish,
        )
        if not allowed:
            provider = "VISTA" if managed_vista_acquisition else "Qwen"
            raise LearningStageWorkerError(
                f"{provider} cancelled before model acquisition"
            )
        return result
    if (
        managed_vista_acquisition
        and cancellation_event is not None
        and hasattr(cancellation_event, "is_set")
        and cancellation_event.is_set()
    ):
        raise LearningStageWorkerError("VISTA cancelled before model acquisition")
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
    previous_process_scope = os.environ.get("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME")
    previous_provider_runtime = os.environ.get("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH")
    previous_hybrid_lineage = os.environ.get("AGENT_GUI_HYBRID_LINEAGE_JSON")
    os.environ["AGENT_GUI_MODEL_REQUEST_ID"] = model_request_id
    supervisor = payload.get("_hybrid_supervisor")
    process_scope_name = (
        str(supervisor.get("process_scope_name") or "").strip()
        if isinstance(supervisor, dict)
        else ""
    )
    if process_scope_name:
        os.environ["AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME"] = process_scope_name
        os.environ["AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH"] = str(
            supervisor.get("provider_runtime_path") or ""
        )
        os.environ["AGENT_GUI_HYBRID_LINEAGE_JSON"] = json.dumps(
            supervisor.get("lineage"),
            sort_keys=True,
            separators=(",", ":"),
        )
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
        if previous_process_scope is None:
            os.environ.pop("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", None)
        else:
            os.environ["AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME"] = previous_process_scope
        if previous_provider_runtime is None:
            os.environ.pop("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", None)
        else:
            os.environ["AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH"] = previous_provider_runtime
        if previous_hybrid_lineage is None:
            os.environ.pop("AGENT_GUI_HYBRID_LINEAGE_JSON", None)
        else:
            os.environ["AGENT_GUI_HYBRID_LINEAGE_JSON"] = previous_hybrid_lineage
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
        if payload["status"] in {"reconciliation_pending", "recovery_required"}:
            payload["status"] = "running"
        payload["contract_version"] = LEARNING_STAGE_WORKER_JOURNAL_CONTRACT_VERSION
        payload["result_file"] = Path(record["result_path"]).name
        provider_lease_path = record.get("provider_lease_path")
        if isinstance(provider_lease_path, str):
            payload["provider_lease_file"] = Path(provider_lease_path).name
        if isinstance(record.get("provider_scope_name"), str):
            payload["provider_scope_name"] = record["provider_scope_name"]
        if isinstance(record.get("workflow_revision"), int):
            payload["workflow_revision"] = record["workflow_revision"]
        if isinstance(record.get("provider_owner_path"), str):
            payload["provider_owner_file"] = Path(record["provider_owner_path"]).name
        if isinstance(record.get("provider_runtime_path"), str):
            payload["provider_runtime_file"] = Path(record["provider_runtime_path"]).name
        if isinstance(record.get("provider_profile_id"), str):
            payload["provider_profile_id"] = record["provider_profile_id"]
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
        authoritative_workflow_revision: int | None = None,
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
        normalized_payload = deepcopy(payload)
        hybrid_requested = normalized_payload.get("learning_pipeline_mode") == "hybrid_v1_1"
        if hybrid_requested:
            if (
                isinstance(authoritative_workflow_revision, bool)
                or not isinstance(authoritative_workflow_revision, int)
                or authoritative_workflow_revision < 0
            ):
                raise LearningStageWorkerError(
                    "Hybrid authoritative workflow revision is required"
                )
            supplied_revision = normalized_payload.get("workflow_revision")
            if (
                supplied_revision is not None
                and supplied_revision != authoritative_workflow_revision
            ):
                raise LearningStageWorkerError(
                    "Hybrid payload workflow revision does not match authoritative revision"
                )
            normalized_payload["workflow_revision"] = authoritative_workflow_revision
        payload_sha256 = _payload_sha256(normalized_payload)

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
            provider_lease_path = self._result_root / f"{worker_id}.provider-lease.json"
            provider_owner_path = self._result_root / f"{worker_id}.provider-owner.json"
            provider_runtime_path = self._result_root / f"{worker_id}.provider-runtime.json"
            identity = {
                "worker_id": worker_id,
                "run_id": normalized_run_id,
                "stage": normalized_stage,
                "operation_id": normalized_operation_id,
                "task_kind": normalized_task_kind,
                "model_request_id": model_request_id,
                "payload_sha256": payload_sha256,
            }
            hybrid_vista_task = (
                normalized_task_kind == "panel_learning_calibration_sequence"
                and hybrid_requested
            )
            child_payload = deepcopy(normalized_payload)
            provider_scope = None
            provider_scope_name = None
            provider_profile_id = None
            workflow_revision = None
            provider = ""
            if hybrid_requested:
                revision_value = authoritative_workflow_revision
                assert isinstance(revision_value, int)
                workflow_revision = revision_value
                lineage = _hybrid_provider_lineage(
                    run_id=normalized_run_id,
                    workflow_revision=revision_value,
                    operation_id=normalized_operation_id,
                    stage=normalized_stage,
                )
                child_payload["_hybrid_supervisor"] = {
                    "contract_version": "hybrid_worker_supervisor_context_v1",
                    "lineage": lineage,
                    "provider_lease_path": str(provider_lease_path),
                    "provider_runtime_path": str(provider_runtime_path),
                    "worker_id": worker_id,
                }
                provider = str(
                    HYBRID_STAGE_HANDLER_REGISTRY.get(normalized_task_kind, {}).get(
                        "provider"
                    )
                    or ""
                )
                if provider in {"omni", "qwen", "vista"}:
                    from app.learn.hybrid.windows_process_scope import (
                        WindowsProcessScope,
                        process_scope_name,
                    )

                    provider_scope_name = process_scope_name(lineage, provider)
                    provider_scope = WindowsProcessScope(
                        provider_scope_name, create=True
                    )
                    try:
                        child_payload["_hybrid_supervisor"][
                            "process_scope_name"
                        ] = provider_scope_name
                        orchestration = normalized_payload.get("_hybrid_orchestration")
                        if provider == "omni":
                            predecessor = normalized_payload.get("hybrid_capture_bundle_ref")
                        elif provider == "qwen":
                            predecessor = (
                                orchestration.get("omni_inventory")
                                if isinstance(orchestration, dict)
                                else None
                            )
                        else:
                            predecessor = (
                                orchestration.get("fusion_result")
                                if isinstance(orchestration, dict)
                                else normalized_payload.get("hybrid_fusion_result")
                            )
                        predecessor_sha256 = _artifact_digest(predecessor)
                        _write_hybrid_provider_owner(
                            provider_owner_path,
                            worker_id=worker_id,
                            task_kind=normalized_task_kind,
                            model_request_id=model_request_id,
                            provider=provider,
                            lineage=lineage,
                            process_scope_name_value=provider_scope_name,
                            runtime_file=provider_runtime_path.name,
                            predecessor_sha256=predecessor_sha256,
                        )
                        _write_json_atomic(
                            provider_runtime_path,
                            seal_immutable({
                                "contract_version": HYBRID_PROVIDER_RUNTIME_CONTRACT_VERSION,
                                "state": "acquiring",
                                "worker_id": worker_id,
                                "model_request_id": model_request_id,
                                "provider": provider,
                                "lineage": lineage,
                                "process_scope_name": provider_scope_name,
                                "provider_identity": None,
                                "cleanup_observation": None,
                            }),
                        )
                    except BaseException:
                        _cleanup_failed_worker_start(
                            provider_scope=provider_scope,
                            process=None,
                            artifact_paths=(
                                result_path,
                                journal_path,
                                provider_lease_path,
                                provider_owner_path,
                                provider_runtime_path,
                            ),
                        )
                        provider_scope = None
                        raise
                if hybrid_vista_task:
                    provider_profile_id = (
                        str(normalized_payload.get("profile_id") or "").strip()
                        or None
                    )
                    orchestration = normalized_payload.get("_hybrid_orchestration")
                    predecessor = normalized_payload.get("hybrid_fusion_result")
                    if not isinstance(predecessor, dict) and isinstance(
                        orchestration, dict
                    ):
                        predecessor = orchestration.get("fusion_result")
                    try:
                        _publish_supervised_vista_acquiring(
                            child_payload["_hybrid_supervisor"],
                            predecessor_sha256=_artifact_digest(predecessor),
                            profile_id=provider_profile_id,
                        )
                    except BaseException:
                        _cleanup_failed_worker_start(
                            provider_scope=provider_scope,
                            process=None,
                            artifact_paths=(
                                result_path,
                                journal_path,
                                provider_lease_path,
                                provider_owner_path,
                                provider_runtime_path,
                            ),
                        )
                        provider_scope = None
                        raise
            process = None
            try:
                cancellation_event = (
                    _ManagedCancellationEvent(
                        event=self._process_context.Event(),
                        lock=self._process_context.Lock(),
                    )
                    if normalized_task_kind == "panel_learning_hybrid_omni_discovery"
                    or normalized_task_kind in _MANAGED_QWEN_TASK_KINDS
                    or hybrid_vista_task
                    else None
                )
                completion_event = (
                    self._process_context.Event()
                    if normalized_task_kind == "panel_learning_hybrid_omni_discovery"
                    or hybrid_vista_task
                    else None
                )
                process = self._process_factory(
                    target=_run_learning_stage_worker_entry,
                    args=(
                        str(result_path),
                        normalized_task_kind,
                        child_payload,
                        model_request_id,
                        deepcopy(identity),
                        cancellation_event,
                        completion_event,
                    ),
                    name=f"learning-stage-{normalized_stage}-{worker_id[:8]}",
                )
            except BaseException:
                _cleanup_failed_worker_start(
                    provider_scope=provider_scope,
                    process=process,
                    artifact_paths=(
                        result_path,
                        journal_path,
                        provider_lease_path,
                        provider_owner_path,
                        provider_runtime_path,
                    ),
                )
                provider_scope = None
                raise
            record = {
                "contract_version": LEARNING_STAGE_WORKER_CONTRACT_VERSION,
                **identity,
                "status": "running",
                "started_at": _utc_now_iso(),
                "finished_at": None,
                "result_path": str(result_path),
                "journal_path": str(journal_path),
                "provider_lease_path": str(provider_lease_path),
                "provider_scope_name": provider_scope_name,
                "provider_scope": provider_scope,
                "provider_owner_path": (
                    str(provider_owner_path) if provider_scope_name else None
                ),
                "provider_runtime_path": (
                    str(provider_runtime_path) if provider_scope_name else None
                ),
                "provider": provider or None,
                "provider_lineage": deepcopy(lineage) if hybrid_requested else None,
                "workflow_revision": workflow_revision,
                "provider_profile_id": provider_profile_id,
                "process": process,
                "payload": deepcopy(normalized_payload),
                "cancellation_event": cancellation_event,
                "completion_event": completion_event,
                "recovered_from_journal": False,
            }
            try:
                self._persist_record_journal(record)
            except BaseException:
                _cleanup_failed_worker_start(
                    provider_scope=provider_scope,
                    process=process,
                    artifact_paths=(
                        result_path,
                        journal_path,
                        provider_lease_path,
                        provider_owner_path,
                        provider_runtime_path,
                    ),
                )
                record["provider_scope"] = None
                raise
            self._records[worker_id] = record
            self._active_by_operation[operation_key] = worker_id
            self._workers_by_operation.setdefault(operation_key, []).append(worker_id)
            self._workers_by_invocation[invocation_key] = worker_id
            try:
                process.start()
            except BaseException:
                self._active_by_operation.pop(operation_key, None)
                self._records.pop(worker_id, None)
                workers = self._workers_by_operation.get(operation_key, [])
                if worker_id in workers:
                    workers.remove(worker_id)
                if not workers:
                    self._workers_by_operation.pop(operation_key, None)
                self._workers_by_invocation.pop(invocation_key, None)
                _cleanup_failed_worker_start(
                    provider_scope=provider_scope,
                    process=process,
                    artifact_paths=(
                        result_path,
                        journal_path,
                        provider_lease_path,
                        provider_owner_path,
                        provider_runtime_path,
                    ),
                )
                record["provider_scope"] = None
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
            if record["status"] not in {
                "running",
                "detached_running",
                "reconciliation_pending",
                "recovery_required",
            }:
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
                if (
                    record["task_kind"] == "panel_learning_calibration_sequence"
                    and isinstance(record.get("provider_scope_name"), str)
                    and record.get("provider_scope_name")
                ):
                    reconciliation = _reconcile_supervised_vista_record(record)
                    record["supervisor_reconciliation"] = reconciliation
                    record["status"] = (
                        "cancelled"
                        if reconciliation.get("status") == "verified"
                        else "recovery_required"
                    )
                    self._persist_record_journal(record)
                    if reconciliation.get("status") == "verified":
                        _close_provider_scope(record)
                    return {
                        **self._public_record(record),
                        "backend_compute_termination": "not_covered",
                        "model_service_compute_termination": (
                            "terminated"
                            if reconciliation.get("status") == "verified"
                            else "indeterminate"
                        ),
                        "model_request_cancellation": {
                            "contract_version": "model_request_cancellation_v1",
                            "status": "supervisor_reconciled"
                            if reconciliation.get("status") == "verified"
                            else "recovery_required",
                            "model_service_compute_termination": (
                                "terminated"
                                if reconciliation.get("status") == "verified"
                                else "indeterminate"
                            ),
                        },
                        "supervisor_reconciliation": reconciliation,
                    }
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
            elif (
                record["task_kind"] == "panel_learning_calibration_sequence"
                and record.get("payload", {}).get("learning_pipeline_mode")
                == "hybrid_v1_1"
            ):
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
                completion_event = record.get("completion_event")
                handshake_complete = bool(
                    completion_event is not None
                    and completion_event.wait(
                        timeout=_HYBRID_VISTA_CLEANUP_WAIT_SECONDS
                    )
                )
                if not handshake_complete:
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=3.0)
                    reconciliation = _reconcile_supervised_vista_record(record)
                    record["supervisor_reconciliation"] = reconciliation
                    if reconciliation.get("status") != "verified":
                        record["status"] = "recovery_required"
                        self._persist_record_journal(record)
                        return {
                            **self._public_record(record),
                            "status": "recovery_required",
                            "backend_compute_termination": "terminated"
                            if not process.is_alive()
                            else "termination_failed",
                            "model_service_compute_termination": "indeterminate",
                            "model_request_cancellation": deepcopy(model_cancellation),
                            "supervisor_reconciliation": reconciliation,
                        }
                    record["status"] = "cancelled"
                    record["finished_at"] = _utc_now_iso()
                    self._active_by_operation.pop(operation_key, None)
                    self._persist_record_journal(record)
                    _close_provider_scope(record)
                    return {
                        **self._public_record(record),
                        "backend_compute_termination": "terminated",
                        "model_service_compute_termination": "terminated",
                        "model_request_cancellation": deepcopy(model_cancellation),
                        "supervisor_reconciliation": reconciliation,
                    }
                process.join(timeout=2.0)
                self._refresh_record(record)
                if record.get("status") != "completed":
                    raise LearningStageWorkerError(
                        "Hybrid VISTA cooperative cleanup result is invalid"
                    )
                cooperative_cleanup = _hybrid_vista_cleanup_evidence(record)
                if process.is_alive():
                    raise LearningStageWorkerError(
                        "Hybrid VISTA cleanup completed but worker exit is still pending"
                    )
                return {
                    **self._public_record(record),
                    "backend_compute_termination": "terminated",
                    "model_service_compute_termination": model_cancellation.get(
                        "model_service_compute_termination",
                        "request_not_active",
                    ),
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
            item
            for item in records
            if item.get("status") in {
                "detached_running", "reconciliation_pending", "recovery_required"
            }
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
            if isinstance(record.get("provider_scope_name"), str) and record.get(
                "provider_scope_name"
            ):
                reconciliation = _reconcile_hybrid_provider_scope_record(record)
                record["supervisor_reconciliation"] = reconciliation
                if reconciliation.get("status") != "verified":
                    record["status"] = "recovery_required"
                    self._persist_record_journal(record)
                    return
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
            _close_provider_scope(record)
            return

        process = record.get("process")
        if process is None:
            if (
                isinstance(record.get("provider_scope_name"), str)
                and record.get("provider_scope_name")
            ):
                reconciliation = _reconcile_hybrid_provider_scope_record(record)
                record["supervisor_reconciliation"] = reconciliation
                if reconciliation.get("status") != "verified":
                    record["status"] = "recovery_required"
                    self._persist_record_journal(record)
                    return
                record["status"] = "failed"
                record["worker_result"] = {
                    "contract_version": LEARNING_STAGE_WORKER_RESULT_CONTRACT_VERSION,
                    "status": "failed",
                    "error": {
                        "type": "WorkerResultMissing",
                        "details": (
                            "recovered Hybrid provider worker has no result envelope "
                            "after verified supervisor cleanup"
                        ),
                    },
                }
                record["finished_at"] = record.get("finished_at") or _utc_now_iso()
                self._persist_record_journal(record)
                _close_provider_scope(record)
                return
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
        if isinstance(record.get("provider_scope_name"), str) and record.get(
            "provider_scope_name"
        ):
            reconciliation = _reconcile_hybrid_provider_scope_record(record)
            record["supervisor_reconciliation"] = reconciliation
            if reconciliation.get("status") != "verified":
                record["status"] = "recovery_required"
                self._persist_record_journal(record)
                return
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
        _close_provider_scope(record)

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
                "provider_scope",
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


def _close_provider_scope(record: dict[str, Any]) -> None:
    scope = record.get("provider_scope")
    if scope is None:
        return
    try:
        scope.close()
    finally:
        record["provider_scope"] = None


def _cleanup_failed_worker_start(
    *,
    provider_scope: Any,
    process: Any,
    artifact_paths: tuple[Path, ...],
) -> None:
    """清理尚未成功启动的 worker 所有权与精确工件。"""

    if process is not None:
        try:
            is_alive = getattr(process, "is_alive", None)
            if callable(is_alive) and is_alive():
                terminate = getattr(process, "terminate", None)
                if callable(terminate):
                    terminate()
                join = getattr(process, "join", None)
                if callable(join):
                    join(timeout=5)
        except BaseException:
            pass
        try:
            close = getattr(process, "close", None)
            if callable(close):
                close()
        except BaseException:
            pass
    if provider_scope is not None:
        try:
            provider_scope.close()
        except BaseException:
            pass
    for path in artifact_paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


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
    provider_lease_file = payload.get("provider_lease_file")
    provider_lease_path = None
    if provider_lease_file is not None:
        provider_lease_file = _required_text(
            provider_lease_file, "provider_lease_file"
        )
        if (
            provider_lease_file != f"{worker_id}.provider-lease.json"
            or Path(provider_lease_file).name != provider_lease_file
        ):
            raise LearningStageWorkerError(
                "worker journal provider_lease_file does not match worker_id"
            )
        candidate = (result_root / provider_lease_file).resolve()
        if candidate.parent != result_root.resolve():
            raise LearningStageWorkerError(
                "worker journal provider_lease_file escapes the result root"
            )
        provider_lease_path = str(candidate)
    provider_scope_name = payload.get("provider_scope_name")
    provider_owner_path = None
    provider_runtime_path = None
    provider_recovery_blocked = False
    provider_owner_error = None
    provider_owner_document = None
    workflow_revision = payload.get("workflow_revision")
    if provider_scope_name is not None:
        provider_scope_name = _required_text(
            provider_scope_name, "provider_scope_name"
        )
        owner_file_value = payload.get("provider_owner_file")
        runtime_file_value = payload.get("provider_runtime_file")
        owner_file = (
            str(owner_file_value).strip()
            if isinstance(owner_file_value, str)
            else ""
        )
        runtime_file = (
            str(runtime_file_value).strip()
            if isinstance(runtime_file_value, str)
            else ""
        )
        if (
            not owner_file
            or not runtime_file
            or owner_file != f"{worker_id}.provider-owner.json"
            or runtime_file != f"{worker_id}.provider-runtime.json"
            or Path(owner_file).name != owner_file
            or Path(runtime_file).name != runtime_file
            or isinstance(workflow_revision, bool)
            or not isinstance(workflow_revision, int)
            or workflow_revision < 0
        ):
            provider_recovery_blocked = True
            provider_owner_error = "Hybrid provider owner journal fields are invalid"
        else:
            provider_owner_candidate = (result_root / owner_file).resolve()
            provider_runtime_candidate = (result_root / runtime_file).resolve()
            if (
                provider_owner_candidate.parent != result_root.resolve()
                or provider_runtime_candidate.parent != result_root.resolve()
            ):
                provider_recovery_blocked = True
                provider_owner_error = "Hybrid provider owner path escapes result root"
            else:
                provider_owner_path = str(provider_owner_candidate)
                provider_runtime_path = str(provider_runtime_candidate)
                try:
                    provider_owner_document = _load_hybrid_provider_owner(
                        provider_owner_candidate,
                        identity=identity,
                        workflow_revision=workflow_revision,
                        journal_scope_name=provider_scope_name,
                        runtime_file=runtime_file,
                    )
                except (LearningStageWorkerError, ValueError) as error:
                    provider_recovery_blocked = True
                    provider_owner_error = str(error)
        if provider_recovery_blocked:
            provider_scope_name = None
    provider_profile_id = payload.get("provider_profile_id")
    if provider_profile_id is not None:
        provider_profile_id = _required_text(
            provider_profile_id, "provider_profile_id"
        )
    return {
        "contract_version": LEARNING_STAGE_WORKER_CONTRACT_VERSION,
        **identity,
        "status": (
            "recovery_required"
            if provider_recovery_blocked
            else "detached_running" if persisted_status == "running" else persisted_status
        ),
        "finished_at": payload.get("finished_at"),
        "result_path": str(result_path),
        "journal_path": str(journal_path.resolve()),
        "provider_lease_path": provider_lease_path,
        "provider_scope_name": provider_scope_name,
        "provider_scope": None,
        "provider_owner_path": provider_owner_path,
        "provider_runtime_path": provider_runtime_path,
        "provider_recovery_blocked": provider_recovery_blocked,
        "provider_owner_error": provider_owner_error,
        "provider": (
            provider_owner_document.get("provider")
            if isinstance(provider_owner_document, dict)
            else None
        ),
        "provider_lineage": (
            deepcopy(provider_owner_document.get("lineage"))
            if isinstance(provider_owner_document, dict)
            else None
        ),
        "workflow_revision": workflow_revision if isinstance(workflow_revision, int) else None,
        "provider_profile_id": provider_profile_id,
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


def _hybrid_vista_cleanup_evidence(record: dict[str, Any]) -> dict[str, Any]:
    result_envelope = record.get("worker_result")
    response = (
        result_envelope.get("response")
        if isinstance(result_envelope, dict)
        else None
    )
    if (
        not isinstance(response, dict)
        or response.get("contract_version")
        != "learning_hybrid_managed_stage_result_v1"
        or response.get("task_kind") != "panel_learning_calibration_sequence"
    ):
        raise LearningStageWorkerError(
            "Hybrid VISTA cooperative cleanup evidence is invalid"
        )
    lifecycle = response.get("lifecycle_evidence")
    receipt = (
        lifecycle.get("vista_cleanup_receipt")
        if isinstance(lifecycle, dict)
        else None
    )
    managed_result = response.get("result")
    model_lifecycle = (
        managed_result.get("model_lifecycle")
        if isinstance(managed_result, dict)
        else None
    )
    if not isinstance(receipt, dict) and isinstance(model_lifecycle, dict):
        receipt = model_lifecycle.get("vista_cleanup_receipt")
    if isinstance(receipt, dict):
        try:
            validate_hybrid_cleanup_receipt(receipt)
        except (TypeError, ValueError) as error:
            raise LearningStageWorkerError(str(error)) from error
        return {
            "contract_version": "hybrid_vista_cooperative_cleanup_v1",
            "cleanup_status": "verified",
            "vista_cleanup_receipt": deepcopy(receipt),
        }
    if (
        response.get("outcome") == "failed"
        and isinstance(model_lifecycle, dict)
        and model_lifecycle.get("status") == "model_lease_not_acquired"
        and "cancelled before model acquisition"
        in str(managed_result.get("failure_reason") or "")
    ):
        return {
            "contract_version": "hybrid_vista_cooperative_cleanup_v1",
            "cleanup_status": "not_acquired",
            "vista_cleanup_receipt": None,
        }
    raise LearningStageWorkerError(
        "Hybrid VISTA cooperative cleanup evidence is invalid"
    )


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
