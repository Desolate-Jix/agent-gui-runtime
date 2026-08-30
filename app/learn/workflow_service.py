from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Literal, Mapping
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
from app.learn.workflow_state import LearningWorkflowTransitionError
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


@dataclass(frozen=True)
class LearningWorkflowServiceComposition:
    store: LearningWorkflowRunStore
    worker_registry: object
    project_root: Path
    composition_kind: Literal["production", "test"]
    benchmark_supervision_root: object | None
    provider_case_resolver: object | None
    benchmark_v2_worker_binding_resolver: object | None = None
    _factory_mint: object | None = field(default=None, repr=False, compare=False)


class _LearningWorkflowRegistryOwner:
    """集中持有 Registry 调用，避免组合依赖在调用链中被拆散。"""

    def __init__(self, registry: object) -> None:
        self._registry = registry

    def start_worker(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.start(**kwargs)

    def worker_status(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.status(**kwargs)

    def adopt_worker_result(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.adopt_result(**kwargs)

    def read_worker_result(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.read_adopted_result(**kwargs)

    def cancel_worker(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.cancel_by_operation(**kwargs)

    def project_worker_attachment(
        self, **kwargs: Any
    ) -> dict[str, Any] | None:
        return self._registry.attachment_by_operation(**kwargs)

    def prepare_benchmark_identity(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.prepare_benchmark_worker_identity(**kwargs)

    def inspect_benchmark_identity(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.inspect_prepared_benchmark_worker_identity(**kwargs)

    def confirm_benchmark_anchor(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.confirm_prepared_benchmark_worker_anchor(**kwargs)

    def prepare_benchmark_provider(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.prepare_benchmark_provider_acquisition(**kwargs)

    def launch_benchmark_worker(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.launch_prepared_benchmark_worker(**kwargs)

    def recover_benchmark_launch(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.recover_launching_benchmark_worker(**kwargs)

    def inspect_benchmark_result(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.inspect_completed_result_identity(**kwargs)

    def inspect_benchmark_launch_owner(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.inspect_benchmark_worker_launch_owner(**kwargs)

    def observe_benchmark_cleanup(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.observe_benchmark_worker_cleanup(**kwargs)

    def verify_benchmark_cleanup(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.verify_benchmark_worker_cleanup_receipt(**kwargs)

    def reconcile_benchmark_provider(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.reconcile_benchmark_provider_cleanup(**kwargs)

    def abort_benchmark_before_anchor(self, **kwargs: Any) -> dict[str, Any]:
        return self._registry.abort_prepared_benchmark_worker_before_anchor(
            **kwargs
        )


_LEARNING_WORKFLOW_OPERATION_LOCKS_GUARD = RLock()
_LEARNING_WORKFLOW_OPERATION_LOCKS: dict[tuple[int, str, str], RLock] = {}
_PRODUCTION_LEARNING_WORKFLOW_SERVICE_COMPOSITION: (
    LearningWorkflowServiceComposition | None
) = None
_DEFAULT_TEST_WORKER_BINDING_RESOLVER = object()
_LEARNING_WORKFLOW_SERVICE_COMPOSITION_MINT = object()


@dataclass(frozen=True)
class _LearningWorkflowServiceCompositionMint:
    secret: object
    store: object
    worker_registry: object
    project_root: Path
    composition_kind: str
    benchmark_supervision_root: object | None
    provider_case_resolver: object | None
    benchmark_v2_worker_binding_resolver: object | None


def _require_minted_learning_workflow_service_composition(
    composition: object,
) -> LearningWorkflowServiceComposition:
    mint = getattr(composition, "_factory_mint", None)
    if (
        not isinstance(composition, LearningWorkflowServiceComposition)
        or not isinstance(mint, _LearningWorkflowServiceCompositionMint)
        or mint.secret is not _LEARNING_WORKFLOW_SERVICE_COMPOSITION_MINT
        or mint.store is not composition.store
        or mint.worker_registry is not composition.worker_registry
        or mint.project_root != composition.project_root
        or mint.composition_kind != composition.composition_kind
        or mint.benchmark_supervision_root
        is not composition.benchmark_supervision_root
        or mint.provider_case_resolver is not composition.provider_case_resolver
        or mint.benchmark_v2_worker_binding_resolver
        is not composition.benchmark_v2_worker_binding_resolver
    ):
        raise LearningWorkflowStageOperationError(
            "learning workflow service composition must be factory-minted"
        )
    return composition


def get_learning_workflow_operation_lock(
    *,
    store: LearningWorkflowRunStore,
    run_id: str,
    operation_id: str,
) -> RLock:
    if not isinstance(store, LearningWorkflowRunStore):
        raise ValueError("workflow operation lock requires LearningWorkflowRunStore")
    normalized_run_id = str(run_id or "").strip()
    normalized_operation_id = str(operation_id or "").strip()
    if not normalized_run_id or not normalized_operation_id:
        raise ValueError("workflow operation lock identity is required")
    key = (id(store), normalized_run_id, normalized_operation_id)
    with _LEARNING_WORKFLOW_OPERATION_LOCKS_GUARD:
        lock = _LEARNING_WORKFLOW_OPERATION_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _LEARNING_WORKFLOW_OPERATION_LOCKS[key] = lock
        return lock


def _validate_learning_workflow_service_composition(
    *,
    store: LearningWorkflowRunStore,
    worker_registry: object,
    project_root: str | Path,
    composition_kind: Literal["production", "test"],
    benchmark_supervision_root: object | None,
    provider_case_resolver: object | None,
    benchmark_v2_worker_binding_resolver: object | None,
) -> LearningWorkflowServiceComposition:
    from app.learn.workflow_worker import LearningStageWorkerRegistry

    benchmark_enabled = benchmark_supervision_root is not None
    if composition_kind == "production" or benchmark_enabled:
        if not isinstance(store, LearningWorkflowRunStore):
            raise ValueError("composition store must be LearningWorkflowRunStore")
        if not isinstance(worker_registry, LearningStageWorkerRegistry):
            raise ValueError("composition Registry must be LearningStageWorkerRegistry")
    root = Path(project_root).resolve()
    benchmark_capabilities = (
        benchmark_supervision_root,
        provider_case_resolver,
        benchmark_v2_worker_binding_resolver,
    )
    if any(value is None for value in benchmark_capabilities) and any(
        value is not None for value in benchmark_capabilities
    ):
        raise ValueError(
            "benchmark composition requires supervision, case resolver, and Task 5 resolver"
        )
    if benchmark_enabled:
        journal_root = Path(
            getattr(benchmark_supervision_root, "journal_root", "")
        ).resolve()
        if not journal_root.is_relative_to(root):
            raise ValueError(
                "benchmark supervision root must be inside the composition project root"
            )
        registry_root = getattr(worker_registry, "_benchmark_supervision_root", None)
        if registry_root is not benchmark_supervision_root:
            raise ValueError("composition Registry and supervision root do not match")
        from app.learn.hybrid.benchmark_v2_provider_corpus import (
            validate_provider_case_resolver_binding,
        )

        validate_provider_case_resolver_binding(
            provider_case_resolver,
            workflow_store=store,
            benchmark_supervision_root=benchmark_supervision_root,
            composition_kind=composition_kind,
        )
        from app.learn.hybrid.benchmark_v2_worker_binding import (
            validate_server_worker_window_binding_resolver_binding,
        )

        validate_server_worker_window_binding_resolver_binding(
            benchmark_v2_worker_binding_resolver,
            project_root=root,
            composition_kind=composition_kind,
        )
    resolved_root = Path(root)
    mint = _LearningWorkflowServiceCompositionMint(
        secret=_LEARNING_WORKFLOW_SERVICE_COMPOSITION_MINT,
        store=store,
        worker_registry=worker_registry,
        project_root=resolved_root,
        composition_kind=composition_kind,
        benchmark_supervision_root=benchmark_supervision_root,
        provider_case_resolver=provider_case_resolver,
        benchmark_v2_worker_binding_resolver=benchmark_v2_worker_binding_resolver,
    )
    return LearningWorkflowServiceComposition(
        store=store,
        worker_registry=worker_registry,
        project_root=resolved_root,
        composition_kind=composition_kind,
        benchmark_supervision_root=benchmark_supervision_root,
        provider_case_resolver=provider_case_resolver,
        benchmark_v2_worker_binding_resolver=benchmark_v2_worker_binding_resolver,
        _factory_mint=mint,
    )


def compose_test_learning_workflow_service_unit(
    *,
    store: object,
    worker_registry: object,
    project_root: str | Path,
    benchmark_supervision_root: object | None = None,
    provider_case_resolver: object | None = None,
    benchmark_v2_worker_binding_resolver: object | None = None,
) -> LearningWorkflowServiceComposition:
    """仅供隔离单元测试的显式 factory seam；mint 仍绑定全部 exact component。"""

    root = Path(project_root).resolve()
    mint = _LearningWorkflowServiceCompositionMint(
        secret=_LEARNING_WORKFLOW_SERVICE_COMPOSITION_MINT,
        store=store,
        worker_registry=worker_registry,
        project_root=root,
        composition_kind="test",
        benchmark_supervision_root=benchmark_supervision_root,
        provider_case_resolver=provider_case_resolver,
        benchmark_v2_worker_binding_resolver=benchmark_v2_worker_binding_resolver,
    )
    return LearningWorkflowServiceComposition(
        store=store,
        worker_registry=worker_registry,
        project_root=root,
        composition_kind="test",
        benchmark_supervision_root=benchmark_supervision_root,
        provider_case_resolver=provider_case_resolver,
        benchmark_v2_worker_binding_resolver=benchmark_v2_worker_binding_resolver,
        _factory_mint=mint,
    )


def compose_test_learning_workflow_service(
    *,
    store: LearningWorkflowRunStore,
    worker_registry: object,
    project_root: str | Path,
    benchmark_supervision_root: object | None = None,
    provider_case_resolver: object | None = None,
    benchmark_v2_worker_binding_resolver: object | None = (
        _DEFAULT_TEST_WORKER_BINDING_RESOLVER
    ),
) -> LearningWorkflowServiceComposition:
    if benchmark_v2_worker_binding_resolver is _DEFAULT_TEST_WORKER_BINDING_RESOLVER:
        if benchmark_supervision_root is None:
            benchmark_v2_worker_binding_resolver = None
        else:
            from app.learn.hybrid.benchmark_v2_worker_binding import (
                compose_test_server_worker_window_binding_resolver,
            )

            benchmark_v2_worker_binding_resolver = (
                compose_test_server_worker_window_binding_resolver(
                    authority_root=Path(project_root).resolve(),
                )
            )
    return _validate_learning_workflow_service_composition(
        store=store,
        worker_registry=worker_registry,
        project_root=project_root,
        composition_kind="test",
        benchmark_supervision_root=benchmark_supervision_root,
        provider_case_resolver=provider_case_resolver,
        benchmark_v2_worker_binding_resolver=benchmark_v2_worker_binding_resolver,
    )


def get_production_learning_workflow_service_composition(
) -> LearningWorkflowServiceComposition:
    global _PRODUCTION_LEARNING_WORKFLOW_SERVICE_COMPOSITION
    if _PRODUCTION_LEARNING_WORKFLOW_SERVICE_COMPOSITION is not None:
        return _PRODUCTION_LEARNING_WORKFLOW_SERVICE_COMPOSITION
    from app.learn.hybrid.benchmark_v2_provider_corpus import (
        get_production_provider_case_resolver,
    )
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        get_production_server_worker_window_binding_resolver,
    )
    from app.learn.workflow_store import learning_workflow_run_store
    from app.learn.workflow_worker import (
        get_production_benchmark_worker_supervision_root,
        get_production_learning_stage_worker_registry,
    )

    learning_stage_worker_registry = get_production_learning_stage_worker_registry()
    composition = _validate_learning_workflow_service_composition(
        store=learning_workflow_run_store,
        worker_registry=learning_stage_worker_registry,
        project_root=Path(__file__).resolve().parents[2],
        composition_kind="production",
        benchmark_supervision_root=get_production_benchmark_worker_supervision_root(),
        provider_case_resolver=get_production_provider_case_resolver(),
        benchmark_v2_worker_binding_resolver=(
            get_production_server_worker_window_binding_resolver()
        ),
    )
    _PRODUCTION_LEARNING_WORKFLOW_SERVICE_COMPOSITION = composition
    return composition


class LearningWorkflowStageOperationError(ValueError):
    """学习阶段运行租约无效，拒绝接收过期或越权结果。"""


_BENCHMARK_V2_C2_UNAVAILABLE = (
    "benchmark_v2 incumbent orchestration is unavailable before C3"
)


def _has_benchmark_v2_incumbent_marker(value: object) -> bool:
    return isinstance(value, Mapping) and "benchmark_v2_incumbent" in value


def _reject_benchmark_v2_incumbent_before_c3(value: object) -> None:
    if _has_benchmark_v2_incumbent_marker(value):
        raise LearningWorkflowStageOperationError(_BENCHMARK_V2_C2_UNAVAILABLE)


def _stage_execution_document(
    workflow_state: Mapping[str, object],
    stage: str,
) -> object:
    stages = workflow_state.get("stages")
    stage_record = stages.get(stage) if isinstance(stages, Mapping) else None
    evidence_refs = (
        stage_record.get("evidence_refs")
        if isinstance(stage_record, Mapping)
        else None
    )
    return (
        evidence_refs.get("stage_execution")
        if isinstance(evidence_refs, Mapping)
        else None
    )


_BENCHMARK_V2_WINDOW_BINDING_FIELD = "_benchmark_v2_window_binding"
_BENCHMARK_V2_DISPATCH_CONTEXT_FIELD = "_benchmark_v2_dispatch_context"
_BENCHMARK_V2_WINDOW_ADOPTION_CONTRACT = (
    "portfolio_hybrid_benchmark_v2_worker_window_binding_adoption_v1"
)


def _reject_client_benchmark_v2_window_binding(payload: Mapping[str, object]) -> None:
    if _BENCHMARK_V2_WINDOW_BINDING_FIELD in payload:
        raise LearningWorkflowStageOperationError(
            "_benchmark_v2_window_binding is server-owned"
        )
    if _BENCHMARK_V2_DISPATCH_CONTEXT_FIELD in payload:
        raise LearningWorkflowStageOperationError(
            "_benchmark_v2_dispatch_context is server-owned"
        )


def inject_benchmark_v2_worker_window_binding(
    *,
    payload: dict[str, Any],
    operation_ref: Mapping[str, object],
    owner: Mapping[str, object],
    capture_ref: Mapping[str, object],
    publisher: object | None = None,
    run_id: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """在server-owned worker payload cut-point注入sealed窗口绑定。"""

    if not isinstance(payload, dict):
        raise LearningWorkflowStageOperationError("worker payload must be an object")
    _reject_client_benchmark_v2_window_binding(payload)
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        publish_server_worker_window_binding,
        serialize_worker_window_binding,
    )

    child = deepcopy(payload)
    if publisher is None:
        if run_id is not None or stage is not None:
            raise LearningWorkflowStageOperationError(
                "worker binding publication requires an opaque publisher"
            )
        serialized = serialize_worker_window_binding(
            operation_ref=operation_ref,
            owner=owner,
            capture_ref=capture_ref,
        )
    else:
        if not isinstance(run_id, str) or not isinstance(stage, str):
            raise LearningWorkflowStageOperationError(
                "worker binding publication requires run and stage"
            )
        authority = publish_server_worker_window_binding(
            publisher=publisher,
            run_id=run_id,
            stage=stage,
            operation_id=str(operation_ref.get("operation_id") or ""),
            owner=owner,
            capture_ref=capture_ref,
        )
        serialized = authority["serialized_window_binding"]
    child[_BENCHMARK_V2_WINDOW_BINDING_FIELD] = deepcopy(dict(serialized))
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
        _validate_normal_clear_receipt,
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
            or not _benchmark_v2_generic_receipt_matches_binding_operation(
                generic_operation_id=generic_receipt.get("operation_id"),
                binding_operation_id=operation_ref.get("operation_id"),
            )
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
        normal = _validate_normal_clear_receipt(
            receipt=normal,
            serialized=serialized,
        )
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


def _benchmark_v2_generic_receipt_matches_binding_operation(
    *, generic_operation_id: object, binding_operation_id: object
) -> bool:
    generic = str(generic_operation_id or "")
    binding = str(binding_operation_id or "")
    if not generic or not binding:
        return False
    if generic == binding:
        return True
    separator = _BENCHMARK_V2_INCUMBENT_CHILD_SEPARATOR
    if separator not in generic:
        return False
    parent, token = generic.rsplit(separator, 1)
    return parent == binding and len(token) == 64 and all(
        character in "0123456789abcdef" for character in token
    )


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
    attachment = _LearningWorkflowRegistryOwner(
        worker_registry
    ).project_worker_attachment(
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
    _preloaded_current: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """续租当前受管阶段，并将续租记录写入可回放事件历史。"""

    if not isinstance(lease_seconds, int) or lease_seconds < 1:
        raise LearningWorkflowStageOperationError(
            "lease_seconds must be a positive integer"
        )
    current = (
        _preloaded_current
        if isinstance(_preloaded_current, Mapping)
        else store.get(run_id)
    )
    _require_revision(current, expected_revision)
    stage_execution = _managed_stage_execution(current, stage)
    _reject_benchmark_v2_incumbent_before_c3(stage_execution)
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
    _prechecked_stage_execution: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """取消当前受管阶段的状态所有权，不伪装成已终止后端计算。"""

    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise LearningWorkflowStageOperationError(
            "stage operation cancellation requires a reason"
        )
    stage_execution = (
        deepcopy(dict(_prechecked_stage_execution))
        if isinstance(_prechecked_stage_execution, Mapping)
        else require_active_learning_workflow_stage_operation(
            store=store,
            run_id=run_id,
            expected_revision=expected_revision,
            stage=stage,
            operation_id=operation_id,
            now=now,
            expiry_action="cancellation",
        )
    )
    _reject_benchmark_v2_incumbent_before_c3(stage_execution)
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


def _benchmark_v2_incumbent_operation_from_state(
    workflow_state: Mapping[str, object],
    stage: str,
) -> dict[str, Any] | None:
    stage_execution = _stage_execution_document(workflow_state, stage)
    operation = (
        stage_execution.get("benchmark_v2_incumbent")
        if isinstance(stage_execution, Mapping)
        else None
    )
    if operation is None:
        return None
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        validate_benchmark_v2_incumbent_operation,
    )

    try:
        return validate_benchmark_v2_incumbent_operation(operation)
    except (TypeError, ValueError) as error:
        raise LearningWorkflowStageOperationError(
            f"benchmark_v2 incumbent operation is invalid: {error}"
        ) from error


def _require_benchmark_v2_operation_identity(
    operation: Mapping[str, object],
    *,
    run_id: str,
    stage: str,
    operation_id: str,
) -> None:
    if (
        operation.get("run_id") != run_id
        or operation.get("stage") != stage
        or operation.get("operation_id") != operation_id
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent operation identity differs"
        )


def _call_benchmark_v2_operation(callback):
    try:
        return callback()
    except (
        LearningWorkflowStageOperationError,
        LearningWorkflowTransitionError,
    ):
        raise
    except (TypeError, ValueError) as error:
        raise LearningWorkflowStageOperationError(
            f"benchmark_v2 incumbent closed state is invalid: {error}"
        ) from error


def _benchmark_v2_request(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "provider_case_ref",
        "window_binding_ref",
        "capture_ref",
    }:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent request is not closed"
        )
    request = deepcopy(dict(value))
    for name in ("provider_case_ref", "window_binding_ref", "capture_ref"):
        if not isinstance(request[name], Mapping):
            raise LearningWorkflowStageOperationError(
                f"benchmark_v2 incumbent {name} is invalid"
            )
    return request


def _benchmark_v2_stage_execution(
    workflow_state: Mapping[str, object],
    stage: str,
) -> dict[str, Any]:
    value = _stage_execution_document(workflow_state, stage)
    if not isinstance(value, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent stage execution is missing"
        )
    return deepcopy(dict(value))


def _persist_benchmark_v2_incumbent_operation(
    *,
    composition: LearningWorkflowServiceComposition,
    workflow_state: Mapping[str, object],
    stage: str,
    operation: Mapping[str, object],
    sidecars: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    stage_execution = _benchmark_v2_stage_execution(workflow_state, stage)
    stage_execution["benchmark_v2_incumbent"] = deepcopy(dict(operation))
    if isinstance(sidecars, Mapping):
        for name, value in sidecars.items():
            stage_execution[name] = deepcopy(value)
    stages = workflow_state.get("stages")
    stage_record = stages.get(stage) if isinstance(stages, Mapping) else None
    evidence_refs = (
        deepcopy(dict(stage_record.get("evidence_refs")))
        if isinstance(stage_record, Mapping)
        and isinstance(stage_record.get("evidence_refs"), Mapping)
        else {}
    )
    evidence_refs["stage_execution"] = stage_execution
    state = transition_learning_workflow_run(
        store=composition.store,
        project_root=composition.project_root,
        run_id=str(workflow_state.get("run_id") or ""),
        expected_revision=int(workflow_state["revision"]),
        stage=stage,
        outcome="running",
        reason=(
            str(stage_record.get("reason") or "")
            if isinstance(stage_record, Mapping)
            else ""
        ),
        evidence_refs=evidence_refs,
    )
    if int(operation["current_document_revision"]) != int(state["revision"]):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent document revision differs from store revision"
        )
    return state


def _benchmark_v2_runtime_owner(
    *,
    anchored_reservation: Mapping[str, object],
) -> dict[str, Any]:
    from app.learn.recognition.uei.canonical import seal_immutable

    return seal_immutable(
        {
            "contract_version": "benchmark_provider_runtime_owner_v1",
            "authority_kind": anchored_reservation["authority_kind"],
            "run_id": anchored_reservation["run_id"],
            "stage": anchored_reservation["stage"],
            "operation_id": anchored_reservation["operation_id"],
            "worker_id": anchored_reservation["worker_id"],
            "model_request_id": anchored_reservation["model_request_id"],
            "reservation_ref": {
                "content_sha256": anchored_reservation["content_sha256"]
            },
            "payload_sha256": anchored_reservation["payload_sha256"],
        }
    )


def _benchmark_v2_source_projection(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    stage: str,
    operation_id: str,
    request: Mapping[str, object],
    dispatch_revision: int | None = None,
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_incumbent_payload_projection,
    )

    if composition.provider_case_resolver is None:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent provider case resolver is unavailable"
        )
    if composition.benchmark_v2_worker_binding_resolver is None:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent Task5 resolver is unavailable"
        )
    try:
        from app.learn.hybrid.benchmark_v2_worker_binding import (
            resolve_server_worker_window_binding,
        )

        binding_run_id, binding_operation_id = (
            _benchmark_v2_incumbent_parent_binding_identity(
                run_id=run_id,
                stage=stage,
                operation_id=operation_id,
                request=request,
            )
        )
        resolution = resolve_server_worker_window_binding(
            resolver=composition.benchmark_v2_worker_binding_resolver,
            run_id=binding_run_id,
            stage=stage,
            operation_id=binding_operation_id,
            window_binding_ref=request["window_binding_ref"],
            capture_ref=request["capture_ref"],
        )
        resolved_dispatch_revision = (
            int(dispatch_revision)
            if dispatch_revision is not None
            else 0
        )
        dispatch_context = _benchmark_v2_dispatch_context_from_serialized(
            composition=composition,
            window_binding={
                "run_id": run_id,
                "stage": stage,
                "operation_id": operation_id,
                "window_binding_ref": deepcopy(request["window_binding_ref"]),
                "capture_ref": deepcopy(request["capture_ref"]),
            },
            serialized_window_binding=resolution["serialized_window_binding"],
            task_kind="vision_observe_screen",
            revision=resolved_dispatch_revision,
        )
        projection = compose_benchmark_v2_incumbent_payload_projection(
            provider_case_resolver=composition.provider_case_resolver,
            provider_case_ref=request["provider_case_ref"],
            window_binding_ref=request["window_binding_ref"],
            capture_ref=request["capture_ref"],
            serialized_window_binding=resolution["serialized_window_binding"],
            dispatch_context=dispatch_context,
        )
        projection["worker_binding_resolution"] = deepcopy(dict(resolution))
        return projection
    except (TypeError, ValueError) as error:
        raise LearningWorkflowStageOperationError(
            f"benchmark_v2 incumbent source projection is invalid: {error}"
        ) from error


def _benchmark_v2_incumbent_parent_binding_identity(
    *,
    run_id: str,
    stage: str,
    operation_id: str,
    request: Mapping[str, object],
) -> tuple[str, str]:
    """从确定性子槽恢复原 Task5 窗口 authority 身份。"""

    separator = _BENCHMARK_V2_INCUMBENT_CHILD_SEPARATOR
    if separator not in run_id and separator not in operation_id:
        return run_id, operation_id
    if separator not in run_id or separator not in operation_id:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent child binding identity is incomplete"
        )
    parent_run_id, run_token = run_id.rsplit(separator, 1)
    parent_operation_id, operation_token = operation_id.rsplit(separator, 1)
    case_ref = request.get("provider_case_ref")
    case_id = case_ref.get("case_id") if isinstance(case_ref, Mapping) else None
    expected_token = content_sha256(
        {
            "contract_version": "benchmark_v2_incumbent_child_slot_identity_v1",
            "parent_run_id": parent_run_id,
            "parent_stage": stage,
            "parent_operation_id": parent_operation_id,
            "case_id": case_id,
        }
    )
    if (
        not parent_run_id
        or not parent_operation_id
        or run_token != operation_token
        or run_token != expected_token
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent child binding identity is stale"
        )
    return parent_run_id, parent_operation_id

def _benchmark_v2_sidecars(
    workflow_state: Mapping[str, object], stage: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    stage_execution = _benchmark_v2_stage_execution(workflow_state, stage)
    operation = stage_execution.get("benchmark_v2_incumbent")
    anchor = stage_execution.get("benchmark_v2_operation_anchor")
    if not isinstance(operation, Mapping) or not isinstance(anchor, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent durable sidecars are missing"
        )
    source = operation.get("handler_payload_source")
    if not isinstance(source, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent closed source is missing"
        )
    request = {
        "provider_case_ref": deepcopy(source.get("provider_case_ref")),
        "window_binding_ref": deepcopy(operation.get("window_binding_ref")),
        "capture_ref": deepcopy(operation.get("capture_ref")),
    }
    return _benchmark_v2_request(request), deepcopy(dict(anchor))


def _benchmark_v2_sealed_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise LearningWorkflowStageOperationError(f"{label} is invalid")
    sealed = deepcopy(dict(value))
    digest = sealed.get("content_sha256")
    if not isinstance(digest, str) or content_sha256(sealed) != digest:
        raise LearningWorkflowStageOperationError(f"{label} seal is invalid")
    return sealed


def _inspect_benchmark_v2_result_snapshot(
    *,
    registry: _LearningWorkflowRegistryOwner,
    operation: Mapping[str, object],
) -> dict[str, Any]:
    inspected = registry.inspect_benchmark_result(
        worker_id=operation["worker_ref"]["worker_id"],
        run_id=operation["run_id"],
        stage=operation["stage"],
        operation_id=operation["operation_id"],
    )
    expected_fields = {
        "contract_version",
        "status",
        "worker_id",
        "run_id",
        "stage",
        "operation_id",
        "task_kind",
        "model_request_id",
        "payload_sha256",
        "result_sha256",
        "result_available",
        "normal_binding_evidence_ref",
        "provider_cleanup_evidence_ref",
    }
    worker = operation["worker_ref"]
    if (
        not isinstance(inspected, Mapping)
        or set(inspected) != expected_fields
        or inspected.get("contract_version")
        != "learning_stage_worker_completed_result_identity_v1"
        or inspected.get("status") != "completed"
        or inspected.get("result_available") is not True
        or inspected.get("task_kind") != "vision_observe_screen"
        or any(
            inspected.get(name) != operation[name]
            for name in ("run_id", "stage", "operation_id")
        )
        or any(
            inspected.get(name) != worker[name]
            for name in ("worker_id", "model_request_id", "payload_sha256")
        )
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent A inspection identity differs"
        )
    sealed = seal_immutable(dict(inspected))
    anchored = operation.get("result_identity_ref")
    if anchored is not None and sealed != anchored:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent A inspection changed after first snapshot"
        )
    return sealed


def _inspect_benchmark_v2_launch_owner(
    *,
    registry: _LearningWorkflowRegistryOwner,
    operation: Mapping[str, object],
    anchor: Mapping[str, object],
    root: object,
    require_assignment: bool,
) -> dict[str, Any]:
    inspected = registry.inspect_benchmark_launch_owner(
        worker_id=operation["worker_ref"]["worker_id"],
        run_id=operation["run_id"],
        stage=operation["stage"],
        operation_id=operation["operation_id"],
        reservation_ref=operation["reservation_ref"],
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    owner = _benchmark_v2_sealed_mapping(
        inspected, "benchmark_v2 incumbent B1 launch owner inspection"
    )
    exact_fields = {
        "contract_version",
        "authority_kind",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "execution_nonce",
        "reservation_ref",
        "current_reservation_ref",
        "operation_anchor_ref",
        "expected_supervision_ref",
        "supervision_ref",
        "reservation_state",
        "owner_phase",
        "assignment_state",
        "process_identity",
        "scope_name",
        "assignment_proven_ref",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    worker = operation["worker_ref"]
    if (
        set(owner) != exact_fields
        or owner.get("contract_version")
        != "benchmark_worker_launch_owner_inspection_v1"
        or owner.get("authority_kind") != root.authority_kind
        or owner.get("artifact_is_authorization") is not False
        or owner.get("execute_binding_enabled") is not False
        or any(
            owner.get(name) != operation[name]
            for name in ("run_id", "stage", "operation_id", "execution_nonce")
        )
        or any(
            owner.get(name) != worker[name]
            for name in ("worker_id", "model_request_id", "payload_sha256")
        )
        or owner.get("reservation_ref") != operation["reservation_ref"]
        or owner.get("operation_anchor_ref") != operation["operation_anchor_ref"]
        or owner.get("expected_supervision_ref")
        != operation["expected_supervision_ref"]
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B1 launch owner lineage differs"
        )
    process_fields = (
        owner.get("process_identity"),
        owner.get("scope_name"),
        owner.get("assignment_proven_ref"),
    )
    if owner.get("assignment_state") == "not_proven":
        if any(value is not None for value in process_fields):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent B1 pre-assignment identity is ambiguous"
            )
        if require_assignment:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent B1 assignment is not proven"
            )
    elif owner.get("assignment_state") == "proven":
        if any(value is None for value in process_fields):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent B1 assignment identity is incomplete"
            )
        supervision_ref = worker.get("supervision_ref")
        if supervision_ref is not None and owner.get("supervision_ref") != supervision_ref:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent B1 actual supervision differs"
            )
        if require_assignment and (
            owner.get("reservation_state") != "launched"
            or owner.get("owner_phase")
            not in {"gate_released", "cleanup_finalization_intent"}
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent B1 launch is not gate-released"
            )
    else:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B1 assignment state is invalid"
        )
    return owner


def _validate_benchmark_v2_launch_recovery_parent(
    *,
    recovery: object,
    operation: Mapping[str, object],
    root: object,
) -> dict[str, Any]:
    projection = _benchmark_v2_sealed_mapping(
        recovery, "benchmark_v2 incumbent B1 launch recovery"
    )
    exact_fields = {
        "contract_version",
        "outcome",
        "authority_kind",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "execution_nonce",
        "reservation_ref",
        "current_reservation_ref",
        "operation_anchor_ref",
        "expected_supervision_ref",
        "supervision_ref",
        "reservation_state",
        "owner_phase",
        "assignment_state",
        "process_identity",
        "scope_name",
        "assignment_proven_ref",
        "gate_release_performed",
        "spawn_retry",
        "cleanup_ref",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    worker = operation["worker_ref"]
    if (
        set(projection) != exact_fields
        or projection.get("contract_version")
        != "benchmark_worker_launch_recovery_v1"
        or projection.get("outcome")
        not in {"recovered_gate_released", "verified_cleanup_safe_stop"}
        or projection.get("authority_kind") != root.authority_kind
        or any(
            projection.get(field) != operation[field]
            for field in ("run_id", "stage", "operation_id", "execution_nonce")
        )
        or any(
            projection.get(field) != worker[field]
            for field in ("worker_id", "model_request_id", "payload_sha256")
        )
        or projection.get("reservation_ref") != operation["reservation_ref"]
        or projection.get("operation_anchor_ref")
        != operation["operation_anchor_ref"]
        or projection.get("expected_supervision_ref")
        != operation["expected_supervision_ref"]
        or projection.get("spawn_retry") is not False
        or projection.get("artifact_is_authorization") is not False
        or projection.get("execute_binding_enabled") is not False
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B1 launch recovery lineage differs"
        )
    if projection["outcome"] == "recovered_gate_released":
        if (
            projection.get("reservation_state") != "launched"
            or projection.get("owner_phase") != "gate_released"
            or projection.get("assignment_state") != "proven"
            or any(
                projection.get(field) is None
                for field in (
                    "supervision_ref",
                    "process_identity",
                    "scope_name",
                    "assignment_proven_ref",
                )
            )
            or projection.get("cleanup_ref") is not None
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent B1 launch recovery is incomplete"
            )
    elif (
        projection.get("reservation_state") != "launching"
        or not isinstance(projection.get("cleanup_ref"), Mapping)
        or set(projection["cleanup_ref"]) != {"content_sha256"}
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B1 launch cleanup is incomplete"
        )
    return projection


def _resolve_benchmark_v2_result_binding(
    *,
    composition: LearningWorkflowServiceComposition,
    operation: Mapping[str, object],
    result_identity: Mapping[str, object],
    launch_owner: Mapping[str, object],
) -> dict[str, Any]:
    if composition.benchmark_v2_worker_binding_resolver is None:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent Task5 resolver is unavailable"
        )
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        resolve_server_worker_window_binding,
    )

    try:
        resolution = resolve_server_worker_window_binding(
            resolver=composition.benchmark_v2_worker_binding_resolver,
            run_id=operation["run_id"],
            stage=operation["stage"],
            operation_id=operation["operation_id"],
            window_binding_ref=operation["window_binding_ref"],
            capture_ref=operation["capture_ref"],
            worker_process_identity=launch_owner["process_identity"],
            normal_binding_evidence_ref=result_identity[
                "normal_binding_evidence_ref"
            ],
        )
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        raise LearningWorkflowStageOperationError(
            f"benchmark_v2 incumbent Task5 result binding is invalid: {error}"
        ) from error
    if resolution.get("worker_process_identity") != launch_owner["process_identity"]:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent Task5 and B1 process identity differ"
        )
    if resolution.get("normal_binding_evidence_ref") != result_identity[
        "normal_binding_evidence_ref"
    ]:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent Task5 and A normal parent differ"
        )
    return deepcopy(dict(resolution))


def _validate_benchmark_v2_provider_preparation_parent(
    *,
    provider: object,
    operation: Mapping[str, object],
    reservation_ref: Mapping[str, object],
    runtime_owner: Mapping[str, object],
    authority_kind: str,
) -> dict[str, Any]:
    projection = _benchmark_v2_sealed_mapping(
        provider, "benchmark_v2 incumbent B2 preparation"
    )
    exact_fields = {
        "contract_version",
        "authority_kind",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "reservation_ref",
        "acquisition_owner_ref",
        "acquisition_intent_ref",
        "prepared_acquisition_observation_ref",
        "prepared_materialization_ledger_ref",
        "acquisition_observation_ref",
        "materialization_ledger_ref",
        "runtime_owner_ref",
        "content_sha256",
    }
    worker = operation["worker_ref"]
    if (
        set(projection) != exact_fields
        or projection.get("contract_version")
        != "benchmark_provider_acquisition_ref_v1"
        or projection.get("authority_kind") != authority_kind
        or any(
            projection.get(name) != operation[name]
            for name in ("run_id", "stage", "operation_id")
        )
        or any(
            projection.get(name) != worker[name]
            for name in ("worker_id", "model_request_id", "payload_sha256")
        )
        or projection.get("reservation_ref") != reservation_ref
        or projection.get("runtime_owner_ref")
        != {"content_sha256": runtime_owner.get("content_sha256")}
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B2 preparation lineage differs"
        )
    for name in (
        "reservation_ref",
        "acquisition_owner_ref",
        "acquisition_intent_ref",
        "prepared_acquisition_observation_ref",
        "prepared_materialization_ledger_ref",
        "acquisition_observation_ref",
        "materialization_ledger_ref",
        "runtime_owner_ref",
    ):
        ref = projection.get(name)
        if (
            not isinstance(ref, Mapping)
            or set(ref) != {"content_sha256"}
            or not isinstance(ref.get("content_sha256"), str)
            or len(ref["content_sha256"]) != 64
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent B2 preparation refs differ"
            )
    return projection


def _validate_benchmark_v2_worker_cleanup_parent(
    *,
    cleanup: object,
    operation: Mapping[str, object],
    launch_owner: Mapping[str, object],
    allowed_outcomes: set[str],
) -> dict[str, Any]:
    receipt = _benchmark_v2_sealed_mapping(
        cleanup, "benchmark_v2 incumbent B1 cleanup"
    )
    exact_fields = {
        "contract_version",
        "outcome",
        "operation_anchor_ref",
        "reservation_ref",
        "supervision_ref",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "process_identity",
        "assignment_proven_ref",
        "finalization_intent_ref",
        "exact_handle_observation_refs",
        "job_absence_observation_ref",
        "worker_absence_observation_ref",
        "supervisor_absence_observation_ref",
        "reservation_abort_ref",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    worker = operation["worker_ref"]
    if (
        set(receipt) != exact_fields
        or receipt.get("contract_version") != "benchmark_worker_cleanup_receipt_v1"
        or receipt.get("outcome") not in allowed_outcomes
        or receipt.get("operation_anchor_ref") != operation["operation_anchor_ref"]
        or any(
            receipt.get(name) != operation[name]
            for name in ("run_id", "stage", "operation_id")
        )
        or receipt.get("worker_id") != worker["worker_id"]
        or receipt.get("artifact_is_authorization") is not False
        or receipt.get("execute_binding_enabled") is not False
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B1 cleanup lineage differs"
        )
    if receipt.get("reservation_ref") != launch_owner["current_reservation_ref"]:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B1 cleanup owner differs"
        )
    if receipt["outcome"] == "verified_exact_worker_exited":
        if (
            receipt.get("supervision_ref") != launch_owner["supervision_ref"]
            or receipt.get("process_identity") != launch_owner["process_identity"]
            or receipt.get("assignment_proven_ref")
            != launch_owner["assignment_proven_ref"]
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent B1 cleanup owner differs"
            )
    elif any(
        receipt.get(name) is not None
        for name in (
            "supervision_ref",
            "process_identity",
            "assignment_proven_ref",
        )
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B1 no-launch cleanup is ambiguous"
        )
    return receipt


def _validate_benchmark_v2_post_cleanup_launch_owner(
    *,
    before: Mapping[str, object],
    after: Mapping[str, object],
) -> dict[str, Any]:
    stable_fields = {
        "contract_version",
        "authority_kind",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "execution_nonce",
        "reservation_ref",
        "operation_anchor_ref",
        "expected_supervision_ref",
        "supervision_ref",
        "assignment_state",
        "process_identity",
        "scope_name",
        "assignment_proven_ref",
        "artifact_is_authorization",
        "execute_binding_enabled",
    }
    if any(after.get(name) != before.get(name) for name in stable_fields):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B1 cleanup reinspection lineage differs"
        )
    if before.get("assignment_state") == "proven":
        if (
            after.get("owner_phase") != "cleanup_finalization_intent"
            or after.get("reservation_state") != "launched"
            or after.get("current_reservation_ref")
            != before.get("current_reservation_ref")
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent B1 cleanup reinspection phase differs"
            )
    elif any(
        after.get(name) != before.get(name)
        for name in ("owner_phase", "reservation_state", "current_reservation_ref")
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B1 no-launch reinspection differs"
        )
    return deepcopy(dict(after))


def _validate_benchmark_v2_provider_cleanup_parent(
    *,
    cleanup: object,
    operation: Mapping[str, object],
    result_identity: Mapping[str, object] | None,
    authority_kind: str,
    allowed_outcomes: set[str],
) -> dict[str, Any]:
    projection = _benchmark_v2_sealed_mapping(
        cleanup, "benchmark_v2 incumbent B2 cleanup"
    )
    exact_fields = {
        "contract_version",
        "status",
        "outcome",
        "authority_kind",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "reservation_ref",
        "acquisition_owner_ref",
        "acquisition_intent_ref",
        "runtime_owner_ref",
        "cleanup_receipt_ref",
        "content_sha256",
    }
    worker = operation["worker_ref"]
    if (
        set(projection) != exact_fields
        or projection.get("contract_version") != "benchmark_provider_cleanup_ref_v1"
        or projection.get("status") != "cleanup_verified"
        or projection.get("outcome") not in allowed_outcomes
        or projection.get("authority_kind") != authority_kind
        or any(
            projection.get(name) != operation[name]
            for name in ("run_id", "stage", "operation_id")
        )
        or any(
            projection.get(name) != worker[name]
            for name in ("worker_id", "model_request_id", "payload_sha256")
        )
        or projection.get("acquisition_intent_ref")
        != operation["acquisition_intent_ref"]
        or projection.get("reservation_ref")
        != operation["provider_reservation_ref"]
        or projection.get("acquisition_owner_ref")
        != operation["acquisition_owner_ref"]
        or projection.get("runtime_owner_ref")
        != {
            "content_sha256": operation["runtime_owner_ref"]["content_sha256"]
        }
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B2 cleanup lineage differs"
        )
    if result_identity is not None and projection.get(
        "cleanup_receipt_ref"
    ) != result_identity.get("provider_cleanup_evidence_ref"):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent B2 and A cleanup parent differ"
        )
    return projection


def _validate_benchmark_v2_generic_adoption(
    *,
    adoption: object,
    operation: Mapping[str, object],
    result_identity: Mapping[str, object],
) -> tuple[dict[str, Any], dict[str, str]]:
    if not isinstance(adoption, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent generic adoption is invalid"
        )
    envelope = deepcopy(dict(adoption))
    receipt = envelope.get("receipt")
    response = envelope.get("response")
    expected_receipt_fields = {
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
    worker = operation["worker_ref"]
    if (
        envelope.get("contract_version")
        != "learning_stage_worker_result_adoption_v1"
        or envelope.get("status") != "adopted"
        or not isinstance(receipt, Mapping)
        or set(receipt) != expected_receipt_fields
        or not isinstance(response, Mapping)
        or receipt.get("contract_version")
        != "learning_stage_worker_result_adoption_v1"
        or receipt.get("task_kind") != "vision_observe_screen"
        or any(
            receipt.get(name) != operation[name]
            for name in ("run_id", "stage", "operation_id")
        )
        or any(
            receipt.get(name) != worker[name]
            for name in ("worker_id", "model_request_id", "payload_sha256")
        )
        or receipt.get("result_sha256") != result_identity["result_sha256"]
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent generic adoption lineage differs"
        )
    return envelope, {"content_sha256": content_sha256(dict(receipt))}


def _start_benchmark_v2_incumbent_operation(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    task_kind: str,
    request: Mapping[str, object],
    parent_window_binding: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_incumbent_operation,
        transition_benchmark_v2_incumbent_operation,
        validate_benchmark_v2_incumbent_payload_projection,
    )
    from app.learn.workflow_worker import (
        compose_benchmark_worker_operation_anchor_v1,
        hold_benchmark_worker_controller,
    )

    if task_kind != "vision_observe_screen":
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent task_kind must be vision_observe_screen"
        )
    root = composition.benchmark_supervision_root
    if root is None:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent supervision root is unavailable"
        )
    closed_request = _benchmark_v2_request(request)
    if parent_window_binding is not None:
        slot = _benchmark_v2_incumbent_child_slot(
            provider_case_ref=closed_request["provider_case_ref"],
            window_binding=parent_window_binding,
        )
        if any(
            slot[name] != expected
            for name, expected in (
                ("run_id", run_id),
                ("stage", stage),
                ("operation_id", operation_id),
            )
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent child start identity is stale"
            )
    registry = _LearningWorkflowRegistryOwner(composition.worker_registry)
    operation_lock = get_learning_workflow_operation_lock(
        store=composition.store,
        run_id=run_id,
        operation_id=operation_id,
    )
    with operation_lock:
        with hold_benchmark_worker_controller(
            supervision_root=root,
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        ):
            stage_execution = require_active_learning_workflow_stage_operation(
                store=composition.store,
                run_id=run_id,
                expected_revision=expected_revision,
                stage=stage,
                operation_id=operation_id,
            )
            current = composition.store.get(run_id)
            operation = _benchmark_v2_incumbent_operation_from_state(current, stage)
            anchor: dict[str, Any]
            confirmation: dict[str, Any]
            if operation is None:
                projection = _benchmark_v2_source_projection(
                    composition=composition,
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                    request=closed_request,
                    dispatch_revision=int(current["revision"]) + 1,
                )
                reservation = registry.prepare_benchmark_identity(
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                    workflow_revision=expected_revision,
                    task_kind=task_kind,
                    handler_payload_source=projection["handler_payload_source"],
                    supervision_root=root,
                )
                anchor = compose_benchmark_worker_operation_anchor_v1(
                    supervision_root=root,
                    reservation=reservation,
                    handler_payload_source=projection["handler_payload_source"],
                    window_binding_ref=projection["handler_payload_source"][
                        "window_binding_ref"
                    ],
                    capture_ref=projection["handler_payload_source"]["capture_ref"],
                    predecessor_content_sha256=None,
                )
                operation = compose_benchmark_v2_incumbent_operation(
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                    operation_anchor_ref={
                        "content_sha256": anchor["anchor_identity_sha256"]
                    },
                    reservation_ref={
                        "content_sha256": reservation["content_sha256"]
                    },
                    supervision_inputs_ref=reservation["supervision_inputs_ref"],
                    expected_supervision_ref=anchor["expected_supervision_ref"],
                    prepared_revision=int(current["revision"]) + 1,
                    handler_payload_source=projection["handler_payload_source"],
                    handler_payload_source_ref=projection[
                        "handler_payload_source_ref"
                    ],
                    window_binding_ref=projection["handler_payload_source"][
                        "window_binding_ref"
                    ],
                    capture_ref=projection["handler_payload_source"]["capture_ref"],
                    execution_nonce=reservation["execution_nonce"],
                    worker_ref={
                        "worker_id": reservation["worker_id"],
                        "model_request_id": reservation["model_request_id"],
                        "payload_sha256": reservation["payload_sha256"],
                        "execution_nonce": reservation["execution_nonce"],
                        "reservation_ref": {
                            "content_sha256": reservation["content_sha256"]
                        },
                        "supervision_ref": None,
                    },
                )
                try:
                    current = _persist_benchmark_v2_incumbent_operation(
                        composition=composition,
                        workflow_state=current,
                        stage=stage,
                        operation=operation,
                        sidecars={
                            "benchmark_v2_operation_anchor": anchor,
                        },
                    )
                except LearningWorkflowTransitionError as original_error:
                    fresh = composition.store.get(run_id)
                    persisted = _benchmark_v2_incumbent_operation_from_state(
                        fresh, stage
                    )
                    if persisted is not None:
                        operation = persisted
                        current = fresh
                        closed_request, anchor = _benchmark_v2_sidecars(
                            current, stage
                        )
                    elif (
                        int(fresh["revision"]) == int(current["revision"])
                        and _benchmark_v2_stage_execution(
                            fresh, stage
                        ).get("operation_id")
                        == operation_id
                    ):
                        current = _persist_benchmark_v2_incumbent_operation(
                            composition=composition,
                            workflow_state=fresh,
                            stage=stage,
                            operation=operation,
                            sidecars={
                                "benchmark_v2_operation_anchor": anchor,
                            },
                        )
                    else:
                        registry.abort_benchmark_before_anchor(
                            reservation_ref={
                                "content_sha256": reservation["content_sha256"]
                            },
                            run_id=run_id,
                            stage=stage,
                            operation_id=operation_id,
                            workflow_revision=expected_revision,
                            expected_operation_anchor=anchor,
                            reason="store_cas_lost",
                            supervision_root=root,
                        )
                        raise original_error
            else:
                persisted_request, anchor = _benchmark_v2_sidecars(current, stage)
                if closed_request != persisted_request:
                    raise LearningWorkflowStageOperationError(
                        "benchmark_v2 incumbent request differs from current source"
                    )
                closed_request = persisted_request

            if operation["phase"] == "prepared":
                confirmation = registry.confirm_benchmark_anchor(
                    reservation_ref=operation["reservation_ref"],
                    expected_operation_anchor=anchor,
                    supervision_root=root,
                )
                anchored = registry.inspect_benchmark_identity(
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                    supervision_root=root,
                )
                runtime_owner = _benchmark_v2_runtime_owner(
                    anchored_reservation=anchored
                )
                provider_reservation_ref = confirmation["anchored_reservation_ref"]
                provider = _validate_benchmark_v2_provider_preparation_parent(
                    provider=registry.prepare_benchmark_provider(
                        reservation_ref=provider_reservation_ref,
                        runtime_owner_ref=runtime_owner,
                    ),
                    operation=operation,
                    reservation_ref=provider_reservation_ref,
                    runtime_owner=runtime_owner,
                    authority_kind=root.authority_kind,
                )
                operation = transition_benchmark_v2_incumbent_operation(
                    operation,
                    to_phase="provider_owner_prepared",
                    changes={
                        "provider_reservation_ref": provider["reservation_ref"],
                        "acquisition_owner_ref": provider[
                            "acquisition_owner_ref"
                        ],
                        "acquisition_intent_ref": provider[
                            "acquisition_intent_ref"
                        ],
                        "runtime_owner_ref": provider["runtime_owner_ref"],
                    },
                )
                current = _persist_benchmark_v2_incumbent_operation(
                    composition=composition,
                    workflow_state=current,
                    stage=stage,
                    operation=operation,
                )
            else:
                anchored = registry.inspect_benchmark_identity(
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                    supervision_root=root,
                )
                confirmation = registry.confirm_benchmark_anchor(
                    reservation_ref=operation["reservation_ref"],
                    expected_operation_anchor=anchor,
                    supervision_root=root,
                )

            if operation["phase"] == "provider_owner_prepared":
                fresh_projection = _benchmark_v2_source_projection(
                    composition=composition,
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                    request=closed_request,
                    dispatch_revision=int(operation["prepared_revision"]),
                )
                try:
                    authoritative_payload = (
                        validate_benchmark_v2_incumbent_payload_projection(
                            payload=fresh_projection["authoritative_payload"],
                            handler_payload_source=operation[
                                "handler_payload_source"
                            ],
                            provider_case_resolver=composition.provider_case_resolver,
                            serialized_window_binding=fresh_projection[
                                "worker_binding_resolution"
                            ]["serialized_window_binding"],
                            dispatch_context=fresh_projection[
                                "authoritative_payload"
                            ].get(_BENCHMARK_V2_DISPATCH_CONTEXT_FIELD),
                        )
                    )
                except (TypeError, ValueError) as error:
                    raise LearningWorkflowStageOperationError(
                        f"benchmark_v2 incumbent authoritative payload is invalid: {error}"
                    ) from error
                operation = transition_benchmark_v2_incumbent_operation(
                    operation,
                    to_phase="worker_starting",
                    changes={},
                )
                current = _persist_benchmark_v2_incumbent_operation(
                    composition=composition,
                    workflow_state=current,
                    stage=stage,
                    operation=operation,
                )
                started = registry.launch_benchmark_worker(
                    reservation_ref=confirmation["anchored_reservation_ref"],
                    expected_operation_anchor=anchor,
                    authoritative_payload=authoritative_payload,
                    supervision_root=root,
                )
            elif operation["phase"] == "worker_starting":
                reservation_state = anchored.get("reservation_state")
                if reservation_state == "anchored":
                    fresh_projection = _benchmark_v2_source_projection(
                        composition=composition,
                        run_id=run_id,
                        stage=stage,
                        operation_id=operation_id,
                        request=closed_request,
                        dispatch_revision=int(operation["prepared_revision"]),
                    )
                    try:
                        authoritative_payload = (
                            validate_benchmark_v2_incumbent_payload_projection(
                                payload=fresh_projection["authoritative_payload"],
                                handler_payload_source=operation[
                                    "handler_payload_source"
                                ],
                                provider_case_resolver=(
                                    composition.provider_case_resolver
                                ),
                                serialized_window_binding=fresh_projection[
                                    "worker_binding_resolution"
                                ]["serialized_window_binding"],
                                dispatch_context=fresh_projection[
                                    "authoritative_payload"
                                ].get(_BENCHMARK_V2_DISPATCH_CONTEXT_FIELD),
                            )
                        )
                    except (TypeError, ValueError) as error:
                        raise LearningWorkflowStageOperationError(
                            "benchmark_v2 incumbent authoritative payload is "
                            f"invalid: {error}"
                        ) from error
                    started = registry.launch_benchmark_worker(
                        reservation_ref=confirmation["anchored_reservation_ref"],
                        expected_operation_anchor=anchor,
                        authoritative_payload=authoritative_payload,
                        supervision_root=root,
                    )
                elif reservation_state in {"launching", "launched"}:
                    recovery = _validate_benchmark_v2_launch_recovery_parent(
                        recovery=registry.recover_benchmark_launch(
                            worker_id=operation["worker_ref"]["worker_id"],
                            run_id=run_id,
                            stage=stage,
                            operation_id=operation_id,
                            reservation_ref=operation["reservation_ref"],
                            expected_operation_anchor=anchor,
                            supervision_root=root,
                        ),
                        operation=operation,
                        root=root,
                    )
                    if recovery["outcome"] == "verified_cleanup_safe_stop":
                        operation = transition_benchmark_v2_incumbent_operation(
                            operation,
                            to_phase="safe_stopped",
                            changes={"worker_cleanup_ref": recovery},
                        )
                        _persist_benchmark_v2_incumbent_operation(
                            composition=composition,
                            workflow_state=current,
                            stage=stage,
                            operation=operation,
                        )
                        return {
                            "contract_version": "benchmark_v2_incumbent_resume_v1",
                            "status": "safe_stopped",
                            "operation": deepcopy(operation),
                        }
                    started = registry.worker_status(
                        worker_id=operation["worker_ref"]["worker_id"],
                        run_id=run_id,
                        operation_id=operation_id,
                    )
                else:
                    raise LearningWorkflowStageOperationError(
                        "benchmark_v2 incumbent worker launch state is indeterminate"
                    )
            elif operation["phase"] in {
                "worker_bound",
                "result_ready",
                "terminal_intent",
                "adopted",
                "complete",
            }:
                if operation["phase"] == "complete":
                    return {
                        "contract_version": "benchmark_v2_incumbent_resume_v1",
                        "status": "complete",
                        "terminal_receipt": deepcopy(operation["terminal_receipt"]),
                    }
                return registry.worker_status(
                    worker_id=operation["worker_ref"]["worker_id"],
                    run_id=run_id,
                    operation_id=operation_id,
                )
            else:
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 incumbent start cannot resume current phase"
                )

            launch_owner = _inspect_benchmark_v2_launch_owner(
                registry=registry,
                operation=operation,
                anchor=anchor,
                root=root,
                require_assignment=True,
            )
            worker_ref = deepcopy(operation["worker_ref"])
            worker_ref["supervision_ref"] = deepcopy(
                launch_owner["supervision_ref"]
            )
            operation = transition_benchmark_v2_incumbent_operation(
                operation,
                to_phase="worker_bound",
                changes={"worker_ref": worker_ref},
            )
            current = _persist_benchmark_v2_incumbent_operation(
                composition=composition,
                workflow_state=current,
                stage=stage,
                operation=operation,
            )
            try:
                require_active_learning_workflow_stage_operation(
                    store=composition.store,
                    run_id=run_id,
                    expected_revision=int(current["revision"]),
                    stage=stage,
                    operation_id=operation_id,
                )
            except (
                LearningWorkflowStageOperationError,
                LearningWorkflowTransitionError,
            ) as original_error:
                try:
                    _cancel_benchmark_v2_incumbent_operation(
                        composition=composition,
                        run_id=run_id,
                        expected_revision=int(current["revision"]),
                        stage=stage,
                        operation_id=operation_id,
                        reason="benchmark start postcheck failed",
                    )
                except Exception:
                    raise original_error
                raise
            return started


def _rebuild_benchmark_v2_window_adoption(
    *,
    composition: LearningWorkflowServiceComposition,
    operation: Mapping[str, object],
    generic_adoption: Mapping[str, object],
    authoritative_payload: Mapping[str, object],
    launch_owner: Mapping[str, object],
    result_identity: Mapping[str, object],
) -> dict[str, object]:
    resolver = composition.benchmark_v2_worker_binding_resolver
    if resolver is None:
        if composition.composition_kind == "test":
            return None
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent Task5 resolver is unavailable"
        )
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        validate_benchmark_v2_worker_window_binding_adoption_from_resolver,
    )

    try:
        binding_run_id, binding_operation_id = (
            _benchmark_v2_incumbent_parent_binding_identity(
                run_id=str(operation["run_id"]),
                stage=str(operation["stage"]),
                operation_id=str(operation["operation_id"]),
                request={
                    "provider_case_ref": operation["handler_payload_source"][
                        "provider_case_ref"
                    ]
                },
            )
        )
        return validate_benchmark_v2_worker_window_binding_adoption_from_resolver(
            resolver=resolver,
            run_id=binding_run_id,
            stage=operation["stage"],
            operation_id=binding_operation_id,
            window_binding_ref=operation["window_binding_ref"],
            capture_ref=operation["capture_ref"],
            worker_process_identity=launch_owner["process_identity"],
            normal_binding_evidence_ref=result_identity[
                "normal_binding_evidence_ref"
            ],
            worker_payload=authoritative_payload,
            generic_adoption=generic_adoption,
        )
    except (OSError, TypeError, ValueError, UnicodeError) as error:
        raise LearningWorkflowStageOperationError(
            f"benchmark_v2 incumbent Task5 adoption is invalid: {error}"
        ) from error


def _recover_or_resume_benchmark_v2_incumbent_operation(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    worker_id: str | None = None,
) -> dict[str, Any]:
    """预结果阶段从 durable source 恢复，结果阶段才要求 A first-snapshot。"""

    _require_minted_learning_workflow_service_composition(composition)
    current = composition.store.get(run_id)
    operation = _benchmark_v2_incumbent_operation_from_state(current, stage)
    if operation is None:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent operation is missing"
        )
    _require_benchmark_v2_operation_identity(
        operation,
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
    )
    expected_worker_id = operation["worker_ref"]["worker_id"]
    if worker_id is not None and worker_id != expected_worker_id:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent worker identity differs"
        )
    if operation["phase"] in {
        "prepared",
        "provider_owner_prepared",
        "worker_starting",
    }:
        request, _anchor = _benchmark_v2_sidecars(current, stage)
        return _start_benchmark_v2_incumbent_operation(
            composition=composition,
            run_id=run_id,
            expected_revision=expected_revision,
            stage=stage,
            operation_id=operation_id,
            task_kind="vision_observe_screen",
            request=request,
        )
    return _resume_benchmark_v2_incumbent_operation(
        composition=composition,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        operation_id=operation_id,
        worker_id=worker_id,
    )


def _resume_benchmark_v2_incumbent_operation(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    worker_id: str | None = None,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_incumbent_terminal_intent,
        compose_benchmark_v2_incumbent_terminal_receipt,
        replay_benchmark_v2_incumbent_terminal,
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.workflow_worker import hold_benchmark_worker_controller

    root = composition.benchmark_supervision_root
    if root is None:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent supervision root is unavailable"
        )
    registry = _LearningWorkflowRegistryOwner(composition.worker_registry)
    with get_learning_workflow_operation_lock(
        store=composition.store, run_id=run_id, operation_id=operation_id
    ):
        with hold_benchmark_worker_controller(
            supervision_root=root,
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        ):
            current = composition.store.get(run_id)
            if int(current["revision"]) != expected_revision:
                raise LearningWorkflowTransitionError(
                    f"workflow revision conflict: expected {expected_revision}, current {current['revision']}"
                )
            operation = _benchmark_v2_incumbent_operation_from_state(current, stage)
            if operation is None:
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 incumbent operation is missing"
                )
            _require_benchmark_v2_operation_identity(
                operation,
                run_id=run_id,
                stage=stage,
                operation_id=operation_id,
            )
            if operation["phase"] in {"complete", "cancelled", "safe_stopped"}:
                terminal = replay_benchmark_v2_incumbent_terminal(operation)
                return {
                    "contract_version": "benchmark_v2_incumbent_resume_v1",
                    "status": terminal["phase"],
                    "terminal_receipt": deepcopy(terminal["terminal_receipt"]),
                    "operation": terminal,
                }
            expected_worker_id = operation["worker_ref"]["worker_id"]
            if worker_id is not None and worker_id != expected_worker_id:
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 incumbent worker identity differs"
                )
            request, anchor = _benchmark_v2_sidecars(current, stage)
            result_identity = _inspect_benchmark_v2_result_snapshot(
                registry=registry,
                operation=operation,
            )
            if operation["phase"] == "worker_bound":
                operation = transition_benchmark_v2_incumbent_operation(
                    operation,
                    to_phase="result_ready",
                    changes={"result_identity_ref": result_identity},
                )
                current = _persist_benchmark_v2_incumbent_operation(
                    composition=composition,
                    workflow_state=current,
                    stage=stage,
                    operation=operation,
                )
            launch_owner: dict[str, Any] | None = None
            worker_cleanup: dict[str, Any] | None = None
            provider_cleanup: dict[str, Any] | None = None
            if operation["phase"] in {"result_ready", "terminal_intent", "adopted"}:
                launch_owner = _inspect_benchmark_v2_launch_owner(
                    registry=registry,
                    operation=operation,
                    anchor=anchor,
                    root=root,
                    require_assignment=True,
                )
                _resolve_benchmark_v2_result_binding(
                    composition=composition,
                    operation=operation,
                    result_identity=result_identity,
                    launch_owner=launch_owner,
                )
                observed_worker_cleanup = registry.observe_benchmark_cleanup(
                        worker_id=expected_worker_id,
                        run_id=run_id,
                        stage=stage,
                        operation_id=operation_id,
                        terminate=True,
                        expected_operation_anchor=anchor,
                        supervision_root=root,
                    )
                verified_worker_cleanup = registry.verify_benchmark_cleanup(
                    worker_id=expected_worker_id,
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                    receipt=observed_worker_cleanup,
                    expected_operation_anchor=anchor,
                    supervision_root=root,
                )
                worker_cleanup = _validate_benchmark_v2_worker_cleanup_parent(
                    cleanup=verified_worker_cleanup,
                    operation=operation,
                    launch_owner=launch_owner,
                    allowed_outcomes={"verified_exact_worker_exited"},
                )
                if worker_cleanup.get("supervisor_absence_observation_ref") is None:
                    _validate_benchmark_v2_post_cleanup_launch_owner(
                        before=launch_owner,
                        after=_inspect_benchmark_v2_launch_owner(
                            registry=registry,
                            operation=operation,
                            anchor=anchor,
                            root=root,
                            require_assignment=False,
                        ),
                    )
                provider_cleanup = _validate_benchmark_v2_provider_cleanup_parent(
                    cleanup=registry.reconcile_benchmark_provider(
                        worker_id=expected_worker_id,
                        run_id=run_id,
                        stage=stage,
                        operation_id=operation_id,
                    ),
                    operation=operation,
                    result_identity=result_identity,
                    authority_kind=root.authority_kind,
                    allowed_outcomes={"verified_exact_process_exited"},
                )
                existing_intent = operation.get("terminal_intent")
                if existing_intent is not None and (
                    existing_intent.get("result_sha256")
                    != result_identity["result_sha256"]
                    or existing_intent.get("normal_binding_evidence_ref")
                    != result_identity["normal_binding_evidence_ref"]
                    or existing_intent.get("provider_cleanup_evidence_ref")
                    != result_identity["provider_cleanup_evidence_ref"]
                    or existing_intent.get("worker_cleanup_evidence_ref")
                    != worker_cleanup
                ):
                    raise LearningWorkflowStageOperationError(
                        "benchmark_v2 incumbent terminal intent parents differ"
                    )
            if operation["phase"] == "result_ready":
                assert worker_cleanup is not None
                intent = compose_benchmark_v2_incumbent_terminal_intent(
                    operation=operation,
                    result_sha256=result_identity["result_sha256"],
                    normal_binding_evidence_ref=result_identity[
                        "normal_binding_evidence_ref"
                    ],
                    provider_cleanup_evidence_ref=result_identity[
                        "provider_cleanup_evidence_ref"
                    ],
                    worker_cleanup_evidence_ref=worker_cleanup,
                    intent_at=_utc_datetime(None).isoformat(),
                )
                operation = transition_benchmark_v2_incumbent_operation(
                    operation,
                    to_phase="terminal_intent",
                    changes={"terminal_intent": intent},
                )
                current = _persist_benchmark_v2_incumbent_operation(
                    composition=composition,
                    workflow_state=current,
                    stage=stage,
                    operation=operation,
                )
            generic_adoption: dict[str, Any] | None = None
            if operation["phase"] == "terminal_intent":
                validated_before_adoption: dict[str, dict[str, Any]] = {}
                incumbent_validator: Callable[[Mapping[str, object]], None] | None = None
                if not (
                    composition.composition_kind == "test"
                    and composition.benchmark_v2_worker_binding_resolver is None
                ):
                    def _validate_incumbent_before_adoption(
                        candidate: Mapping[str, object],
                    ) -> None:
                        validated_before_adoption["response"] = (
                            _validate_benchmark_v2_dispatch_response(
                                composition=composition,
                                response=candidate,
                                window_binding={
                                    "run_id": operation["run_id"],
                                    "stage": operation["stage"],
                                    "operation_id": operation["operation_id"],
                                    "window_binding_ref": operation[
                                        "window_binding_ref"
                                    ],
                                    "capture_ref": operation["capture_ref"],
                                },
                                expected_provider_counts={"qwen": 1},
                                hybrid=False,
                                dispatch_revision=int(
                                    operation["prepared_revision"]
                                ),
                            )
                        )

                    incumbent_validator = _validate_incumbent_before_adoption
                generic_adoption, generic_ref = _validate_benchmark_v2_generic_adoption(
                    adoption=registry.adopt_worker_result(
                        worker_id=expected_worker_id,
                        run_id=run_id,
                        stage=stage,
                        operation_id=operation_id,
                        **(
                            {"result_validator": incumbent_validator}
                            if incumbent_validator is not None
                            else {}
                        ),
                    ),
                    operation=operation,
                    result_identity=result_identity,
                )
                generic_response = generic_adoption.get("response")
                if not isinstance(generic_response, Mapping):
                    raise LearningWorkflowStageOperationError(
                        "benchmark_v2 incumbent adoption lost its response"
                )
                generic_adoption = deepcopy(generic_adoption)
                if incumbent_validator is not None:
                    validated_response = validated_before_adoption.get("response")
                    if (
                        not isinstance(validated_response, dict)
                        or generic_response != validated_response
                    ):
                        raise LearningWorkflowStageOperationError(
                            "benchmark_v2 incumbent adoption bypassed dispatch validation"
                        )
                    generic_adoption["response"] = validated_response
                else:
                    generic_adoption["response"] = (
                        _validate_benchmark_v2_dispatch_response(
                            composition=composition,
                            response=generic_response,
                            window_binding={
                                "run_id": operation["run_id"],
                                "stage": operation["stage"],
                                "operation_id": operation["operation_id"],
                                "window_binding_ref": operation[
                                    "window_binding_ref"
                                ],
                                "capture_ref": operation["capture_ref"],
                            },
                            expected_provider_counts={"qwen": 1},
                            hybrid=False,
                            dispatch_revision=int(operation["prepared_revision"]),
                        )
                    )
                operation = transition_benchmark_v2_incumbent_operation(
                    operation,
                    to_phase="adopted",
                    changes={"generic_adoption_ref": generic_ref},
                )
                current = _persist_benchmark_v2_incumbent_operation(
                    composition=composition,
                    workflow_state=current,
                    stage=stage,
                    operation=operation,
                )
            if operation["phase"] != "adopted":
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 incumbent completion is pending"
                )
            if generic_adoption is None:
                generic_adoption, replay_generic_ref = (
                    _validate_benchmark_v2_generic_adoption(
                        adoption=registry.adopt_worker_result(
                            worker_id=expected_worker_id,
                            run_id=run_id,
                            stage=stage,
                            operation_id=operation_id,
                        ),
                        operation=operation,
                        result_identity=result_identity,
                    )
                )
                if replay_generic_ref != operation["generic_adoption_ref"]:
                    raise LearningWorkflowStageOperationError(
                        "benchmark_v2 incumbent generic adoption replay differs"
                    )
                replay_response = generic_adoption.get("response")
                if not isinstance(replay_response, Mapping):
                    raise LearningWorkflowStageOperationError(
                        "benchmark_v2 incumbent adoption replay lost its response"
                    )
                generic_adoption = deepcopy(generic_adoption)
                generic_adoption["response"] = _validate_benchmark_v2_dispatch_response(
                    composition=composition,
                    response=replay_response,
                    window_binding={
                        "run_id": operation["run_id"],
                        "stage": operation["stage"],
                        "operation_id": operation["operation_id"],
                        "window_binding_ref": operation["window_binding_ref"],
                        "capture_ref": operation["capture_ref"],
                    },
                    expected_provider_counts={"qwen": 1},
                    hybrid=False,
                    dispatch_revision=int(operation["prepared_revision"]),
                )
            projection = _benchmark_v2_source_projection(
                composition=composition,
                run_id=run_id,
                stage=stage,
                operation_id=operation_id,
                request=request,
                dispatch_revision=int(operation["prepared_revision"]),
            )
            window_adoption = _rebuild_benchmark_v2_window_adoption(
                composition=composition,
                operation=operation,
                generic_adoption=generic_adoption,
                authoritative_payload=projection["authoritative_payload"],
                launch_owner=launch_owner,
                result_identity=result_identity,
            )
            assert worker_cleanup is not None and provider_cleanup is not None
            receipt = compose_benchmark_v2_incumbent_terminal_receipt(
                operation=operation,
                outcome="benchmark_v2_incumbent_observe_complete",
                window_adoption_ref=window_adoption,
                worker_cleanup_ref=worker_cleanup,
                provider_cleanup_ref=provider_cleanup,
                terminal_at=_utc_datetime(None).isoformat(),
            )
            operation = transition_benchmark_v2_incumbent_operation(
                operation,
                to_phase="complete",
                changes={
                    "window_adoption_ref": window_adoption,
                    "worker_cleanup_ref": worker_cleanup,
                    "provider_cleanup_ref": provider_cleanup,
                    "terminal_receipt": receipt,
                },
            )
            _persist_benchmark_v2_incumbent_operation(
                composition=composition,
                workflow_state=current,
                stage=stage,
                operation=operation,
            )
            return {
                "contract_version": "benchmark_v2_incumbent_resume_v1",
                "status": "complete",
                "terminal_receipt": deepcopy(receipt),
                "operation": deepcopy(operation),
            }


def _cancel_benchmark_v2_incumbent_operation(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    reason: str,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        advance_benchmark_v2_incumbent_cancel_cleanup,
        compose_benchmark_v2_incumbent_cancel_intent,
        replay_benchmark_v2_incumbent_terminal,
        transition_benchmark_v2_incumbent_operation,
    )
    from app.learn.workflow_worker import hold_benchmark_worker_controller

    root = composition.benchmark_supervision_root
    if root is None:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent supervision root is unavailable"
        )
    registry = _LearningWorkflowRegistryOwner(composition.worker_registry)
    with get_learning_workflow_operation_lock(
        store=composition.store, run_id=run_id, operation_id=operation_id
    ):
        with hold_benchmark_worker_controller(
            supervision_root=root,
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        ):
            current = composition.store.get(run_id)
            if int(current["revision"]) != expected_revision:
                raise LearningWorkflowTransitionError(
                    f"workflow revision conflict: expected {expected_revision}, current {current['revision']}"
                )
            operation = _benchmark_v2_incumbent_operation_from_state(current, stage)
            if operation is None:
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 incumbent operation is missing"
                )
            _require_benchmark_v2_operation_identity(
                operation,
                run_id=run_id,
                stage=stage,
                operation_id=operation_id,
            )
            if operation["phase"] in {"complete", "cancelled", "safe_stopped"}:
                terminal = replay_benchmark_v2_incumbent_terminal(operation)
                return {
                    "contract_version": "benchmark_v2_incumbent_cancel_v1",
                    "status": terminal["phase"],
                    "terminal_receipt": deepcopy(terminal["terminal_receipt"]),
                    "operation": terminal,
                }
            if operation["terminal_intent"] is not None:
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 incumbent completion intent already won"
                )
            request, anchor = _benchmark_v2_sidecars(current, stage)
            del request
            if operation["phase"] == "prepared":
                confirmation = registry.confirm_benchmark_anchor(
                    reservation_ref=operation["reservation_ref"],
                    expected_operation_anchor=anchor,
                    supervision_root=root,
                )
                anchored = registry.inspect_benchmark_identity(
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                    supervision_root=root,
                )
                provider_reservation_ref = confirmation["anchored_reservation_ref"]
                runtime_owner = _benchmark_v2_runtime_owner(
                    anchored_reservation=anchored
                )
                provider = _validate_benchmark_v2_provider_preparation_parent(
                    provider=registry.prepare_benchmark_provider(
                        reservation_ref=provider_reservation_ref,
                        runtime_owner_ref=runtime_owner,
                    ),
                    operation=operation,
                    reservation_ref=provider_reservation_ref,
                    runtime_owner=runtime_owner,
                    authority_kind=root.authority_kind,
                )
                operation = transition_benchmark_v2_incumbent_operation(
                    operation,
                    to_phase="provider_owner_prepared",
                    changes={
                        "provider_reservation_ref": provider["reservation_ref"],
                        "acquisition_owner_ref": provider[
                            "acquisition_owner_ref"
                        ],
                        "acquisition_intent_ref": provider[
                            "acquisition_intent_ref"
                        ],
                        "runtime_owner_ref": provider["runtime_owner_ref"],
                    },
                )
                current = _persist_benchmark_v2_incumbent_operation(
                    composition=composition,
                    workflow_state=current,
                    stage=stage,
                    operation=operation,
                )
            launch_owner = _inspect_benchmark_v2_launch_owner(
                registry=registry,
                operation=operation,
                anchor=anchor,
                root=root,
                require_assignment=False,
            )
            if operation["phase"] not in {"cancel_intent", "cleanup_pending"}:
                intent = compose_benchmark_v2_incumbent_cancel_intent(
                    operation=operation,
                    reason=str(reason or "benchmark operation cancelled"),
                    intent_at=_utc_datetime(None).isoformat(),
                    process_identity=launch_owner["process_identity"],
                    scope_name=launch_owner["scope_name"],
                    assignment_proven_ref=launch_owner[
                        "assignment_proven_ref"
                    ],
                )
                operation = transition_benchmark_v2_incumbent_operation(
                    operation,
                    to_phase="cancel_intent",
                    changes={"cancel_intent": intent},
                )
                current = _persist_benchmark_v2_incumbent_operation(
                    composition=composition,
                    workflow_state=current,
                    stage=stage,
                    operation=operation,
                )
            else:
                intent = operation["cancel_intent"]
                if any(
                    intent.get(name) != launch_owner.get(name)
                    for name in (
                        "process_identity",
                        "scope_name",
                        "assignment_proven_ref",
                    )
                ):
                    raise LearningWorkflowStageOperationError(
                        "benchmark_v2 incumbent cancel intent B1 identity differs"
                    )
            observed_worker_cleanup = registry.observe_benchmark_cleanup(
                    worker_id=operation["worker_ref"]["worker_id"],
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                    terminate=True,
                    expected_operation_anchor=anchor,
                    supervision_root=root,
                )
            verified_worker_cleanup = registry.verify_benchmark_cleanup(
                worker_id=operation["worker_ref"]["worker_id"],
                run_id=run_id,
                stage=stage,
                operation_id=operation_id,
                receipt=observed_worker_cleanup,
                expected_operation_anchor=anchor,
                supervision_root=root,
            )
            worker_cleanup = _validate_benchmark_v2_worker_cleanup_parent(
                cleanup=verified_worker_cleanup,
                operation=operation,
                launch_owner=launch_owner,
                allowed_outcomes={
                    "verified_not_launched",
                    "verified_exact_worker_exited",
                },
            )
            replay_owner = launch_owner
            if worker_cleanup.get("supervisor_absence_observation_ref") is None:
                replay_owner = _validate_benchmark_v2_post_cleanup_launch_owner(
                    before=launch_owner,
                    after=_inspect_benchmark_v2_launch_owner(
                        registry=registry,
                        operation=operation,
                        anchor=anchor,
                        root=root,
                        require_assignment=False,
                    ),
                )
            provider_cleanup = _validate_benchmark_v2_provider_cleanup_parent(
                cleanup=registry.reconcile_benchmark_provider(
                    worker_id=operation["worker_ref"]["worker_id"],
                    run_id=run_id,
                    stage=stage,
                    operation_id=operation_id,
                ),
                operation=operation,
                result_identity=None,
                authority_kind=root.authority_kind,
                allowed_outcomes={
                    "verified_not_acquired",
                    "verified_exact_process_exited",
                },
            )
            if launch_owner["assignment_state"] == "proven":
                if any(
                    replay_owner.get(name) != operation["cancel_intent"].get(name)
                    for name in (
                        "process_identity",
                        "scope_name",
                        "assignment_proven_ref",
                    )
                ):
                    raise LearningWorkflowStageOperationError(
                        "benchmark_v2 incumbent B1 cleanup replay identity differs"
                    )
            provider_outcome = provider_cleanup.get("outcome")
            worker_verified = worker_cleanup.get("outcome") in {
                "verified_not_launched",
                "verified_exact_worker_exited",
            }
            if provider_outcome == "verified_not_acquired":
                materialization_state = "aborted_never_materialized"
                lease_acquired = False
            elif provider_outcome == "verified_exact_process_exited":
                materialization_state = "materialization_possible"
                lease_acquired = True
            else:
                materialization_state = "materialization_possible"
                lease_acquired = False
            cleanup_changes = {
                "worker_cleanup_ref": worker_cleanup if worker_verified else None,
                "provider_cleanup_ref": (
                    provider_cleanup
                    if provider_outcome
                    in {"verified_not_acquired", "verified_exact_process_exited"}
                    else None
                ),
            }
            if operation["phase"] == "cancel_intent":
                operation = transition_benchmark_v2_incumbent_operation(
                    operation,
                    to_phase="cleanup_pending",
                    changes=cleanup_changes,
                )
                current = _persist_benchmark_v2_incumbent_operation(
                    composition=composition,
                    workflow_state=current,
                    stage=stage,
                    operation=operation,
                )
            operation = advance_benchmark_v2_incumbent_cancel_cleanup(
                operation,
                worker_cleanup_ref=cleanup_changes["worker_cleanup_ref"],
                provider_cleanup_ref=cleanup_changes["provider_cleanup_ref"],
                provider_materialization_state=materialization_state,
                provider_lease_acquired=lease_acquired,
                terminal_at=_utc_datetime(None).isoformat(),
            )
            _persist_benchmark_v2_incumbent_operation(
                composition=composition,
                workflow_state=current,
                stage=stage,
                operation=operation,
            )
            result = {
                "contract_version": "benchmark_v2_incumbent_cancel_v1",
                "status": operation["phase"],
                "terminal_receipt": deepcopy(operation["terminal_receipt"]),
                "operation": deepcopy(operation),
            }
            if operation["phase"] == "cleanup_pending":
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 incumbent cleanup is pending"
                )
            return result


def start_guarded_learning_stage_worker(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    task_kind: str,
    payload: Mapping[str, object],
    reuse_active_identical: bool = False,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    if _has_benchmark_v2_incumbent_marker(payload):
        if (
            composition.benchmark_supervision_root is None
            or composition.provider_case_resolver is None
        ):
            require_active_learning_workflow_stage_operation(
                store=composition.store,
                run_id=run_id,
                expected_revision=expected_revision,
                stage=stage,
                operation_id=operation_id,
            )
            raise LearningWorkflowStageOperationError(
                _BENCHMARK_V2_C2_UNAVAILABLE
            )
        return _call_benchmark_v2_operation(
            lambda: _start_benchmark_v2_incumbent_operation(
                composition=composition,
                run_id=run_id,
                expected_revision=expected_revision,
                stage=stage,
                operation_id=operation_id,
                task_kind=task_kind,
                request=payload["benchmark_v2_incumbent"],
            )
        )
    stage_execution = require_active_learning_workflow_stage_operation(
        store=composition.store,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        operation_id=operation_id,
    )
    worker_payload = deepcopy(dict(payload))
    authoritative_hybrid_revision = expected_revision
    if worker_payload.get("learning_pipeline_mode") == "hybrid_v1_1":
        benchmark_binding = _benchmark_v2_hybrid_service_binding_from_execution(
            stage_execution
        )
        if benchmark_binding is not None:
            authoritative_hybrid_revision = (
                _require_benchmark_v2_hybrid_payload_workflow_revision(
                    payload=worker_payload,
                    binding=benchmark_binding,
                )
            )
            if composition.composition_kind == "production":
                _require_benchmark_v2_hybrid_capture_bundle(
                    project_root=composition.project_root,
                    binding=benchmark_binding,
                )
    result = _LearningWorkflowRegistryOwner(
        composition.worker_registry
    ).start_worker(
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
        task_kind=task_kind,
        payload=worker_payload,
        reuse_active_identical=reuse_active_identical,
        authoritative_workflow_revision=(
            authoritative_hybrid_revision
            if worker_payload.get("learning_pipeline_mode") == "hybrid_v1_1"
            else None
        ),
    )
    try:
        require_active_learning_workflow_stage_operation(
            store=composition.store,
            run_id=run_id,
            expected_revision=expected_revision,
            stage=stage,
            operation_id=operation_id,
        )
    except (
        LearningWorkflowStageOperationError,
        LearningWorkflowTransitionError,
    ) as original_error:
        try:
            _LearningWorkflowRegistryOwner(
                composition.worker_registry
            ).cancel_worker(
                run_id=run_id,
                stage=stage,
                operation_id=operation_id,
            )
        except Exception:
            raise original_error
        raise
    return result


def _benchmark_v2_workflow_service_worker_ref(
    operation: Mapping[str, object],
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_contracts import (
        content_sha256 as benchmark_content_sha256,
    )

    worker = operation.get("worker_ref")
    if not isinstance(worker, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 workflow service worker ref is missing"
        )
    return seal_immutable(
        {
            "contract_version": "benchmark_v2_workflow_service_worker_ref_v1",
            "run_id": str(operation["run_id"]),
            "stage": str(operation["stage"]),
            "operation_id": str(operation["operation_id"]),
            "worker_id": str(worker["worker_id"]),
            "model_request_id": str(worker["model_request_id"]),
            "payload_sha256": str(worker["payload_sha256"]),
            "execution_nonce": str(worker["execution_nonce"]),
            "task6_worker_content_sha256": benchmark_content_sha256(dict(worker)),
        }
    )


_BENCHMARK_V2_INCUMBENT_CHILD_SEPARATOR = "::benchmark-v2-incumbent::"


def _benchmark_v2_incumbent_child_slot(
    *,
    provider_case_ref: Mapping[str, object],
    window_binding: Mapping[str, object],
) -> dict[str, Any]:
    """为一个父窗口绑定生成可恢复、确定性的 incumbent 子槽。"""

    from app.learn.hybrid.benchmark_v2_contracts import require_sha256
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        validate_benchmark_v2_workflow_window_binding,
    )

    binding = validate_benchmark_v2_workflow_window_binding(window_binding)
    if not isinstance(provider_case_ref, Mapping) or set(provider_case_ref) != {
        "case_id",
        "case_content_sha256",
    }:
        raise ValueError("benchmark incumbent child slot requires one closed case ref")
    case_id = str(provider_case_ref.get("case_id") or "").strip()
    if not case_id:
        raise ValueError("benchmark incumbent child slot case id is invalid")
    case_sha256 = require_sha256(
        provider_case_ref.get("case_content_sha256"),
        "benchmark incumbent child slot case SHA",
    )
    token = content_sha256(
        {
            "contract_version": "benchmark_v2_incumbent_child_slot_identity_v1",
            "parent_run_id": str(binding["run_id"]),
            "parent_stage": str(binding["stage"]),
            "parent_operation_id": str(binding["operation_id"]),
            # 同一 case_id 必须命中同一槽，SHA 漂移才能被已有状态拒绝。
            "case_id": case_id,
        }
    )
    suffix = f"{_BENCHMARK_V2_INCUMBENT_CHILD_SEPARATOR}{token}"
    return seal_immutable(
        {
            "contract_version": "benchmark_v2_incumbent_child_slot_v1",
            "provider_case_ref": {
                "case_id": case_id,
                "case_content_sha256": case_sha256,
            },
            "parent_window_binding": binding,
            "run_id": f"{binding['run_id']}{suffix}",
            "stage": str(binding["stage"]),
            "operation_id": f"{binding['operation_id']}{suffix}",
            "slot_token": token,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def _lookup_benchmark_v2_incumbent_workflow_service(
    *,
    composition: LearningWorkflowServiceComposition,
    provider_case_ref: Mapping[str, object],
    window_binding: Mapping[str, object],
) -> dict[str, Any] | None:
    """只观察确定性子槽；存在但不完整时要求显式恢复。"""

    _require_minted_learning_workflow_service_composition(composition)
    slot = _benchmark_v2_incumbent_child_slot(
        provider_case_ref=provider_case_ref,
        window_binding=window_binding,
    )
    try:
        current = composition.store.get(str(slot["run_id"]))
    except LearningWorkflowTransitionError as error:
        if str(error) == "workflow run not found":
            return None
        raise
    try:
        if (
            not isinstance(current, Mapping)
            or current.get("run_id") != slot["run_id"]
            or current.get("current_stage") != slot["stage"]
        ):
            raise LearningWorkflowStageOperationError(
                "incumbent child workflow identity is incomplete"
            )
        stage_execution = _benchmark_v2_stage_execution(current, str(slot["stage"]))
        operation = _benchmark_v2_incumbent_operation_from_state(
            current, str(slot["stage"])
        )
        if operation is None:
            raise LearningWorkflowStageOperationError(
                "incumbent child operation is missing"
            )
        _require_benchmark_v2_operation_identity(
            operation,
            run_id=str(slot["run_id"]),
            stage=str(slot["stage"]),
            operation_id=str(slot["operation_id"]),
        )
        source = operation["handler_payload_source"]
        binding = slot["parent_window_binding"]
        if (
            source.get("provider_case_ref") != slot["provider_case_ref"]
            or source.get("window_binding_ref") != binding["window_binding_ref"]
            or source.get("capture_ref") != binding["capture_ref"]
        ):
            raise LearningWorkflowStageOperationError(
                "incumbent child parent lineage is stale"
            )
        if operation["phase"] not in {
            "worker_bound",
            "result_ready",
            "terminal_intent",
            "adopted",
            "complete",
            "cancel_intent",
            "cleanup_pending",
            "cancelled",
            "safe_stopped",
        }:
            raise LearningWorkflowStageOperationError(
                "incumbent child launch is incomplete"
            )
        if int(operation["current_document_revision"]) != int(current["revision"]):
            raise LearningWorkflowStageOperationError(
                "incumbent child document revision is stale"
            )
        return _project_benchmark_v2_workflow_service_step(
            composition=composition,
            workflow_state=current,
            stage_execution=stage_execution,
            operation=operation,
            status=_benchmark_v2_workflow_service_phase_status(operation),
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, LearningWorkflowStageOperationError) and str(
            error
        ).startswith("benchmark_v2 incumbent lookup recovery_required"):
            raise
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent lookup recovery_required: " + str(error)
        ) from error


def _validate_benchmark_v2_actual_incumbent_worker_cleanup(
    *, cleanup: object, operation: Mapping[str, object]
) -> dict[str, Any]:
    receipt = _benchmark_v2_sealed_mapping(
        cleanup, "benchmark actual incumbent worker cleanup"
    )
    fields = {
        "contract_version",
        "outcome",
        "operation_anchor_ref",
        "reservation_ref",
        "supervision_ref",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "process_identity",
        "assignment_proven_ref",
        "finalization_intent_ref",
        "exact_handle_observation_refs",
        "job_absence_observation_ref",
        "worker_absence_observation_ref",
        "supervisor_absence_observation_ref",
        "reservation_abort_ref",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    worker = operation["worker_ref"]
    if (
        set(receipt) != fields
        or receipt.get("contract_version") != "benchmark_worker_cleanup_receipt_v1"
        or receipt.get("outcome")
        not in {"verified_not_launched", "verified_exact_worker_exited"}
        or receipt.get("operation_anchor_ref") != operation["operation_anchor_ref"]
        or any(
            receipt.get(name) != operation[name]
            for name in ("run_id", "stage", "operation_id")
        )
        or receipt.get("worker_id") != worker["worker_id"]
        or receipt.get("artifact_is_authorization") is not False
        or receipt.get("execute_binding_enabled") is not False
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark actual incumbent worker cleanup lineage differs"
        )
    if receipt["outcome"] == "verified_not_launched":
        if receipt.get("reservation_abort_ref") is None or any(
            receipt.get(name) is not None
            for name in (
                "process_identity",
                "assignment_proven_ref",
                "finalization_intent_ref",
                "job_absence_observation_ref",
                "worker_absence_observation_ref",
                "supervisor_absence_observation_ref",
            )
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark actual incumbent no-launch cleanup is incomplete"
            )
    else:
        for name in (
            "process_identity",
            "assignment_proven_ref",
            "finalization_intent_ref",
            "job_absence_observation_ref",
            "worker_absence_observation_ref",
            "supervisor_absence_observation_ref",
        ):
            if receipt.get(name) is None:
                raise LearningWorkflowStageOperationError(
                    f"benchmark actual incumbent cleanup {name} is missing"
                )
    return receipt


def _attest_benchmark_v2_actual_operations_stable_zero(
    *,
    composition: LearningWorkflowServiceComposition,
    operation_refs: list[Mapping[str, object]],
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        BENCHMARK_V2_ACTUAL_OPERATIONS_STABLE_ZERO_CONTRACT,
        validate_benchmark_v2_actual_operations_stable_zero,
        validate_benchmark_v2_workflow_service_operation_ref,
    )

    _require_minted_learning_workflow_service_composition(composition)
    if not isinstance(operation_refs, list) or len(operation_refs) != 6:
        raise ValueError("benchmark actual stable-zero requires exactly six operations")
    supplied = [
        validate_benchmark_v2_workflow_service_operation_ref(item)
        for item in operation_refs
    ]
    hybrid_refs = [item for item in supplied if item["mode"] == "hybrid_v1_1"]
    incumbent_refs = [
        item for item in supplied if item["mode"] == "incumbent_qwen_only"
    ]
    if len(hybrid_refs) != 1 or len(incumbent_refs) != 5:
        raise ValueError("benchmark actual stable-zero requires exact 1 Hybrid + 5 incumbents")
    hybrid_ref = hybrid_refs[0]
    current, stage_execution, binding, worker_record, exact_hybrid = (
        _benchmark_v2_hybrid_service_context(
            composition=composition,
            operation_ref=hybrid_ref,
        )
    )
    hybrid_status = _benchmark_v2_hybrid_service_status(
        workflow_state=current,
        stage=str(exact_hybrid["stage"]),
        worker_record=worker_record,
    )
    hybrid_step = _project_benchmark_v2_hybrid_step(
        composition=composition,
        workflow_state=current,
        stage_execution=stage_execution,
        binding=binding,
        worker_record=worker_record,
        status=hybrid_status,
    )
    hybrid_cleanup = hybrid_step["cleanup_refs"]
    if hybrid_status == "complete":
        provider_cleanup_value = worker_record.get("benchmark_provider_cleanup_ref")
        if not isinstance(provider_cleanup_value, Mapping):
            raise LearningWorkflowStageOperationError(
                "benchmark actual Hybrid provider cleanup is incomplete"
            )
        hybrid_provider_cleanup = _validate_benchmark_v2_hybrid_provider_cleanup(
            cleanup=provider_cleanup_value,
            worker_record=worker_record,
        )
        if (
            hybrid_provider_cleanup.get("outcome")
            != "verified_exact_process_exited"
            or worker_record.get("status") != "completed"
            or worker_record.get("runtime_attached") is not False
            or worker_record.get("result_available") is not True
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark actual Hybrid completed worker cleanup is incomplete"
            )
        hybrid_worker_cleanup = seal_immutable(
            {
                "contract_version": (
                    "benchmark_v2_hybrid_completed_worker_cleanup_ref_v1"
                ),
                "run_id": exact_hybrid["run_id"],
                "stage": exact_hybrid["stage"],
                "operation_id": exact_hybrid["operation_id"],
                "worker_id": exact_hybrid["worker_ref"]["worker_id"],
                "model_request_id": exact_hybrid["worker_ref"]["model_request_id"],
                "payload_sha256": exact_hybrid["worker_ref"]["payload_sha256"],
                "worker_status": "completed",
                "runtime_attached": False,
                "result_available": True,
                "authoritative_worker_record_sha256": content_sha256(
                    dict(worker_record)
                ),
                "provider_cleanup_ref": {
                    "content_sha256": hybrid_provider_cleanup["content_sha256"]
                },
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
    elif hybrid_status == "safe_stopped" and all(
        isinstance(hybrid_cleanup.get(name), Mapping)
        for name in ("worker_cleanup_ref", "provider_cleanup_ref")
    ):
        hybrid_worker_cleanup = deepcopy(hybrid_cleanup["worker_cleanup_ref"])
        hybrid_provider_cleanup = deepcopy(hybrid_cleanup["provider_cleanup_ref"])
    else:
        raise LearningWorkflowStageOperationError(
            "benchmark actual Hybrid authoritative cleanup is incomplete"
        )
    cleanup_entries: list[dict[str, Any]] = [
        {
            "operation_ref_sha256": exact_hybrid["content_sha256"],
            "terminal_receipt_ref": seal_immutable(
                {
                    "contract_version": "benchmark_v2_hybrid_terminal_state_ref_v1",
                    "operation_ref_sha256": exact_hybrid["content_sha256"],
                    "run_id": exact_hybrid["run_id"],
                    "stage": exact_hybrid["stage"],
                    "operation_id": exact_hybrid["operation_id"],
                    "worker_id": exact_hybrid["worker_ref"]["worker_id"],
                    "model_request_id": exact_hybrid["worker_ref"][
                        "model_request_id"
                    ],
                    "workflow_state_ref": exact_hybrid["workflow_state_ref"],
                    "stage_execution_ref": exact_hybrid["stage_execution_ref"],
                    "status": hybrid_status,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            ),
            "worker_cleanup_ref": hybrid_worker_cleanup,
            "provider_cleanup_ref": hybrid_provider_cleanup,
        }
    ]
    exact_operations = [exact_hybrid]
    root = composition.benchmark_supervision_root
    authority_kind = getattr(root, "authority_kind", None)
    if not isinstance(authority_kind, str) or not authority_kind:
        raise LearningWorkflowStageOperationError(
            "benchmark actual incumbent cleanup authority is unavailable"
        )
    incumbent_reservations: set[str] = set()
    for item in incumbent_refs:
        child_current = composition.store.get(str(item["run_id"]))
        child_execution = _benchmark_v2_stage_execution(
            child_current, str(item["stage"])
        )
        operation = _benchmark_v2_incumbent_operation_from_state(
            child_current, str(item["stage"])
        )
        if operation is None or operation["phase"] not in {"complete", "cancelled"}:
            raise LearningWorkflowStageOperationError(
                "benchmark actual incumbent terminal cleanup is incomplete"
            )
        expected_ref = _project_benchmark_v2_workflow_service_operation_ref(
            workflow_state=child_current,
            stage_execution=child_execution,
            operation=operation,
            status=str(operation["phase"]),
        )
        if item != expected_ref:
            raise LearningWorkflowStageOperationError(
                "benchmark actual incumbent operation ref is stale"
            )
        parent_run_id, parent_operation_id = (
            _benchmark_v2_incumbent_parent_binding_identity(
                run_id=str(operation["run_id"]),
                stage=str(operation["stage"]),
                operation_id=str(operation["operation_id"]),
                request={
                    "provider_case_ref": operation["handler_payload_source"][
                        "provider_case_ref"
                    ]
                },
            )
        )
        if (
            parent_run_id != exact_hybrid["run_id"]
            or parent_operation_id != exact_hybrid["operation_id"]
            or operation["window_binding_ref"] != exact_hybrid["window_binding_ref"]
            or operation["capture_ref"] != exact_hybrid["capture_ref"]
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark actual incumbent parent lineage is stale"
            )
        worker_cleanup = _validate_benchmark_v2_actual_incumbent_worker_cleanup(
            cleanup=operation["worker_cleanup_ref"], operation=operation
        )
        incumbent_reservations.add(str(operation["reservation_ref"]["content_sha256"]))
        provider_cleanup = _validate_benchmark_v2_provider_cleanup_parent(
            cleanup=operation["provider_cleanup_ref"],
            operation=operation,
            result_identity=operation.get("result_identity_ref"),
            authority_kind=authority_kind,
            allowed_outcomes={
                "verified_not_acquired",
                "verified_exact_process_exited",
            },
        )
        cleanup_entries.append(
            {
                "operation_ref_sha256": expected_ref["content_sha256"],
                "terminal_receipt_ref": deepcopy(operation["terminal_receipt"]),
                "worker_cleanup_ref": worker_cleanup,
                "provider_cleanup_ref": provider_cleanup,
            }
        )
        exact_operations.append(expected_ref)
    if len(incumbent_reservations) != 5:
        raise LearningWorkflowStageOperationError(
            "benchmark actual incumbent reservation identities are duplicated"
        )
    receipt = seal_immutable(
        {
            "contract_version": (
                BENCHMARK_V2_ACTUAL_OPERATIONS_STABLE_ZERO_CONTRACT
            ),
            "operation_refs": exact_operations,
            "cleanup_entries": cleanup_entries,
            "window_binding_ref": deepcopy(exact_hybrid["window_binding_ref"]),
            "capture_ref": deepcopy(exact_hybrid["capture_ref"]),
            "cleanup_status": "stable_zero",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    return validate_benchmark_v2_actual_operations_stable_zero(receipt)


def _benchmark_v2_workflow_service_phase_status(
    operation: Mapping[str, object],
    *,
    worker_status: str | None = None,
) -> str:
    phase = operation.get("phase")
    if phase in {"complete", "cancelled", "safe_stopped", "cleanup_pending"}:
        return str(phase)
    if phase in {"result_ready", "terminal_intent", "adopted"}:
        return "advanced"
    if worker_status is None or worker_status == "running":
        return "pending"
    if worker_status == "completed":
        return "advanced"
    raise LearningWorkflowStageOperationError(
        f"benchmark_v2 incumbent worker status is not adoptable: {worker_status}"
    )


def _project_benchmark_v2_workflow_service_operation_ref(
    *,
    workflow_state: Mapping[str, object],
    stage_execution: Mapping[str, object],
    operation: Mapping[str, object],
    status: str,
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_workflow_service_operation_ref,
    )
    from app.learn.hybrid.benchmark_v2_contracts import (
        content_sha256 as benchmark_content_sha256,
    )

    source = operation.get("handler_payload_source")
    provider_case_ref = (
        source.get("provider_case_ref") if isinstance(source, Mapping) else None
    )
    if not isinstance(provider_case_ref, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 workflow service provider case ref is missing"
        )
    return compose_benchmark_v2_workflow_service_operation_ref(
        mode="incumbent_qwen_only",
        run_id=str(operation["run_id"]),
        stage=str(operation["stage"]),
        operation_id=str(operation["operation_id"]),
        workflow_state_ref={
            "run_id": str(workflow_state["run_id"]),
            "revision": int(workflow_state["revision"]),
            "content_sha256": benchmark_content_sha256(dict(workflow_state)),
        },
        stage_execution_ref={
            "run_id": str(operation["run_id"]),
            "stage": str(operation["stage"]),
            "operation_id": str(operation["operation_id"]),
            "revision": int(workflow_state["revision"]),
            "content_sha256": benchmark_content_sha256(dict(stage_execution)),
        },
        request_ref={
            "id": str(provider_case_ref["case_id"]),
            "content_sha256": str(provider_case_ref["case_content_sha256"]),
        },
        window_binding_ref=operation["window_binding_ref"],
        capture_ref=operation["capture_ref"],
        worker_ref=_benchmark_v2_workflow_service_worker_ref(operation),
        status=status,
        predecessor_content_sha256=operation.get("predecessor_content_sha256"),
    )


def _benchmark_v2_workflow_service_context(
    *,
    composition: LearningWorkflowServiceComposition,
    operation_ref: Mapping[str, object],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        validate_benchmark_v2_workflow_service_operation_ref,
    )

    _require_minted_learning_workflow_service_composition(composition)
    supplied = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
    if supplied["mode"] != "incumbent_qwen_only":
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid workflow service is unavailable before Amendment S3"
        )
    current = composition.store.get(supplied["run_id"])
    stage_execution = _benchmark_v2_stage_execution(current, supplied["stage"])
    operation = _benchmark_v2_incumbent_operation_from_state(
        current, supplied["stage"]
    )
    if operation is None:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent operation is missing"
        )
    _require_benchmark_v2_operation_identity(
        operation,
        run_id=supplied["run_id"],
        stage=supplied["stage"],
        operation_id=supplied["operation_id"],
    )
    if int(operation["current_document_revision"]) != int(current["revision"]):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 workflow service document revision is stale"
        )
    phase_status = _benchmark_v2_workflow_service_phase_status(operation)
    if phase_status in {"complete", "cancelled", "safe_stopped", "cleanup_pending"}:
        allowed_statuses = {phase_status}
    elif phase_status == "advanced":
        allowed_statuses = {"advanced"}
    else:
        allowed_statuses = {"pending", "advanced"}
    if supplied["status"] not in allowed_statuses:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 workflow service operation status is stale"
        )
    expected = _project_benchmark_v2_workflow_service_operation_ref(
        workflow_state=current,
        stage_execution=stage_execution,
        operation=operation,
        status=supplied["status"],
    )
    if supplied != expected:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 workflow service operation ref is stale"
        )
    return current, stage_execution, operation, supplied


def _read_benchmark_v2_workflow_service_adopted_projection(
    *,
    composition: LearningWorkflowServiceComposition,
    operation: Mapping[str, object],
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_adopted_result_projection,
    )

    result_identity = operation.get("result_identity_ref")
    if not isinstance(result_identity, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent adopted result identity is missing"
        )
    worker = operation["worker_ref"]
    adoption, adoption_ref = _validate_benchmark_v2_generic_adoption(
        adoption=_LearningWorkflowRegistryOwner(
            composition.worker_registry
        ).read_worker_result(
            worker_id=worker["worker_id"],
            run_id=operation["run_id"],
            stage=operation["stage"],
            operation_id=operation["operation_id"],
        ),
        operation=operation,
        result_identity=result_identity,
    )
    if adoption_ref != operation.get("generic_adoption_ref"):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent adopted result replay differs"
        )
    response = adoption.get("response")
    if not isinstance(response, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent adopted response body is missing"
        )
    return compose_benchmark_v2_adopted_result_projection(
        mode="incumbent_qwen_only",
        run_id=str(operation["run_id"]),
        stage=str(operation["stage"]),
        operation_id=str(operation["operation_id"]),
        worker_ref=_benchmark_v2_workflow_service_worker_ref(operation),
        model_request_ref={
            "id": str(worker["model_request_id"]),
            "content_sha256": str(worker["payload_sha256"]),
        },
        payload_ref={"content_sha256": str(worker["payload_sha256"])},
        result_ref={
            "content_sha256": str(result_identity["result_sha256"]),
        },
        adoption_ref=adoption_ref,
        response=response,
        terminal_receipt=operation["terminal_receipt"],
        window_adoption_ref=operation["window_adoption_ref"],
        worker_cleanup_ref=operation["worker_cleanup_ref"],
        provider_cleanup_ref=operation["provider_cleanup_ref"],
    )


def _project_benchmark_v2_workflow_service_step(
    *,
    composition: LearningWorkflowServiceComposition,
    workflow_state: Mapping[str, object],
    stage_execution: Mapping[str, object],
    operation: Mapping[str, object],
    status: str,
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_workflow_service_step,
    )

    operation_ref = _project_benchmark_v2_workflow_service_operation_ref(
        workflow_state=workflow_state,
        stage_execution=stage_execution,
        operation=operation,
        status=status,
    )
    projection = None
    if status == "complete":
        projection = _read_benchmark_v2_workflow_service_adopted_projection(
            composition=composition,
            operation=operation,
        )
    return compose_benchmark_v2_workflow_service_step(
        operation_ref=operation_ref,
        observed_task_kind="vision_observe_screen",
        adopted_result_projection=projection,
        terminal_receipt=operation.get("terminal_receipt"),
        cleanup_refs={
            "worker_cleanup_ref": operation.get("worker_cleanup_ref"),
            "provider_cleanup_ref": operation.get("provider_cleanup_ref"),
        },
    )


def _benchmark_v2_parent_has_hybrid_binding(
    *,
    composition: LearningWorkflowServiceComposition,
    window_binding: Mapping[str, object],
) -> bool:
    try:
        current = composition.store.get(str(window_binding["run_id"]))
        stage_execution = _benchmark_v2_stage_execution(
            current, str(window_binding["stage"])
        )
    except (LearningWorkflowTransitionError, LearningWorkflowStageOperationError):
        return False
    binding = _benchmark_v2_hybrid_service_binding_from_execution(stage_execution)
    if binding is None:
        return False
    if binding["window_binding"] != dict(window_binding):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent parent Hybrid binding is stale"
        )
    return True


def _ensure_benchmark_v2_incumbent_child_workflow_run(
    *,
    composition: LearningWorkflowServiceComposition,
    slot: Mapping[str, object],
) -> dict[str, Any]:
    """仅由 WorkflowService 为实际 benchmark 建立一个 incumbent 子 run。"""

    parent_binding = slot["parent_window_binding"]
    parent_current = composition.store.get(str(parent_binding["run_id"]))
    parent_execution = _benchmark_v2_stage_execution(
        parent_current, str(parent_binding["stage"])
    )
    service_binding = _benchmark_v2_hybrid_service_binding_from_execution(
        parent_execution
    )
    if (
        service_binding is None
        or service_binding["window_binding"] != parent_binding
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent child parent binding is unavailable"
        )
    capture_image_path = str(
        service_binding["screen_group"].get("capture_image_path") or ""
    ).strip()
    if not capture_image_path:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent child capture image is unavailable"
        )
    run_id = str(slot["run_id"])
    stage = str(slot["stage"])
    operation_id = str(slot["operation_id"])
    start_intent = seal_immutable(
        {
            "contract_version": "benchmark_v2_incumbent_child_run_start_intent_v1",
            "provider_case_ref": deepcopy(slot["provider_case_ref"]),
            "parent_run_id": str(parent_binding["run_id"]),
            "parent_stage": str(parent_binding["stage"]),
            "parent_operation_id": str(parent_binding["operation_id"]),
            "window_binding_ref": deepcopy(parent_binding["window_binding_ref"]),
            "capture_ref": deepcopy(parent_binding["capture_ref"]),
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    try:
        current = composition.store.get(run_id)
    except LearningWorkflowTransitionError as error:
        if str(error) != "workflow run not found":
            raise
        current = transition_learning_workflow_run(
            store=composition.store,
            project_root=composition.project_root,
            run_id=run_id,
            expected_revision=0,
            stage="bind_capture",
            outcome="running",
            reason="benchmark_v2 incumbent child capture binding",
            evidence_refs={"benchmark_v2_incumbent_child_start_intent": start_intent},
        )
    if current.get("current_stage") == "bind_capture":
        record = current["stages"]["bind_capture"]
        evidence = record.get("evidence_refs")
        if (
            not isinstance(evidence, Mapping)
            or evidence.get("benchmark_v2_incumbent_child_start_intent")
            != start_intent
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent child run start intent is stale"
            )
        if record.get("status") == "running":
            current = transition_learning_workflow_run(
                store=composition.store,
                project_root=composition.project_root,
                run_id=run_id,
                expected_revision=int(current["revision"]),
                stage="bind_capture",
                outcome="completed",
                reason="benchmark_v2 incumbent child capture bound",
                evidence_refs={
                    "image_path": capture_image_path,
                    "benchmark_v2_incumbent_child_start_intent": start_intent,
                },
            )
        current = start_learning_workflow_stage_operation(
            store=composition.store,
            project_root=composition.project_root,
            run_id=run_id,
            expected_revision=int(current["revision"]),
            stage=stage,
            operation_id=operation_id,
            reason="benchmark_v2 incumbent child workflow service start",
        )["workflow_state"]
    if current.get("current_stage") != stage:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent child run stage is stale"
        )
    execution = _benchmark_v2_stage_execution(current, stage)
    if execution.get("operation_id") != operation_id:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 incumbent child operation slot is stale"
        )
    return current


def _start_benchmark_v2_incumbent_workflow_service(
    *,
    composition: LearningWorkflowServiceComposition,
    provider_case_ref: Mapping[str, object],
    window_binding: Mapping[str, object],
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    if _benchmark_v2_parent_has_hybrid_binding(
        composition=composition,
        window_binding=window_binding,
    ):
        slot = _benchmark_v2_incumbent_child_slot(
            provider_case_ref=provider_case_ref,
            window_binding=window_binding,
        )
        run_id = str(slot["run_id"])
        stage = str(slot["stage"])
        operation_id = str(slot["operation_id"])
        with get_learning_workflow_operation_lock(
            store=composition.store,
            run_id=run_id,
            operation_id=operation_id,
        ):
            existing = _lookup_benchmark_v2_incumbent_workflow_service(
                composition=composition,
                provider_case_ref=provider_case_ref,
                window_binding=window_binding,
            )
            if existing is not None:
                return existing
            current = _ensure_benchmark_v2_incumbent_child_workflow_run(
                composition=composition,
                slot=slot,
            )
            request = {
                "provider_case_ref": deepcopy(dict(provider_case_ref)),
                "window_binding_ref": deepcopy(
                    dict(window_binding["window_binding_ref"])
                ),
                "capture_ref": deepcopy(dict(window_binding["capture_ref"])),
            }
            _start_benchmark_v2_incumbent_operation(
                composition=composition,
                run_id=run_id,
                expected_revision=int(current["revision"]),
                stage=stage,
                operation_id=operation_id,
                task_kind="vision_observe_screen",
                request=request,
                parent_window_binding=window_binding,
            )
            started = _lookup_benchmark_v2_incumbent_workflow_service(
                composition=composition,
                provider_case_ref=provider_case_ref,
                window_binding=window_binding,
            )
            if started is None:
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 incumbent child start lost its durable slot"
                )
            return started
    run_id = str(window_binding["run_id"])
    stage = str(window_binding["stage"])
    operation_id = str(window_binding["operation_id"])
    with get_learning_workflow_operation_lock(
        store=composition.store,
        run_id=run_id,
        operation_id=operation_id,
    ):
        current = composition.store.get(run_id)
        require_active_learning_workflow_stage_operation(
            store=composition.store,
            run_id=run_id,
            expected_revision=int(current["revision"]),
            stage=stage,
            operation_id=operation_id,
        )
        existing = _benchmark_v2_incumbent_operation_from_state(current, stage)
        request = {
            "provider_case_ref": deepcopy(dict(provider_case_ref)),
            "window_binding_ref": deepcopy(dict(window_binding["window_binding_ref"])),
            "capture_ref": deepcopy(dict(window_binding["capture_ref"])),
        }
        if existing is not None:
            existing_source = existing["handler_payload_source"]
            if any(existing_source[name] != request[name] for name in request):
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 workflow service start lineage is stale"
                )
            if existing["phase"] in {"complete", "cancelled", "safe_stopped"}:
                stage_execution = _benchmark_v2_stage_execution(current, stage)
                return _project_benchmark_v2_workflow_service_step(
                    composition=composition,
                    workflow_state=current,
                    stage_execution=stage_execution,
                    operation=existing,
                    status=_benchmark_v2_workflow_service_phase_status(existing),
                )
        _start_benchmark_v2_incumbent_operation(
            composition=composition,
            run_id=run_id,
            expected_revision=int(current["revision"]),
            stage=stage,
            operation_id=operation_id,
            task_kind="vision_observe_screen",
            request=request,
        )
        current = composition.store.get(run_id)
        stage_execution = _benchmark_v2_stage_execution(current, stage)
        operation = _benchmark_v2_incumbent_operation_from_state(current, stage)
        if operation is None:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent start did not persist an operation"
            )
        source = operation["handler_payload_source"]
        if any(source[name] != request[name] for name in request):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 workflow service start result lineage differs"
            )
        return _project_benchmark_v2_workflow_service_step(
            composition=composition,
            workflow_state=current,
            stage_execution=stage_execution,
            operation=operation,
            status=_benchmark_v2_workflow_service_phase_status(operation),
        )


def _poll_benchmark_v2_incumbent_workflow_service(
    *,
    composition: LearningWorkflowServiceComposition,
    operation_ref: Mapping[str, object],
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    supplied_run_id = str(operation_ref.get("run_id") or "")
    supplied_operation_id = str(operation_ref.get("operation_id") or "")
    with get_learning_workflow_operation_lock(
        store=composition.store,
        run_id=supplied_run_id,
        operation_id=supplied_operation_id,
    ):
        current, stage_execution, operation, supplied = (
            _benchmark_v2_workflow_service_context(
                composition=composition,
                operation_ref=operation_ref,
            )
        )
        durable_status = _benchmark_v2_workflow_service_phase_status(operation)
        if durable_status in {
            "complete",
            "cancelled",
            "safe_stopped",
            "cleanup_pending",
            "advanced",
        }:
            return _project_benchmark_v2_workflow_service_step(
                composition=composition,
                workflow_state=current,
                stage_execution=stage_execution,
                operation=operation,
                status=durable_status,
            )
        worker = operation["worker_ref"]
        status_result = status_guarded_learning_stage_worker(
            composition=composition,
            worker_id=worker["worker_id"],
            run_id=operation["run_id"],
            operation_id=operation["operation_id"],
        )
        worker_status = str(status_result.get("status") or "")
        projected_status = _benchmark_v2_workflow_service_phase_status(
            operation,
            worker_status=worker_status,
        )
        if supplied["status"] == "advanced" and projected_status != "advanced":
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 workflow service advanced status is stale"
            )
        return _project_benchmark_v2_workflow_service_step(
            composition=composition,
            workflow_state=current,
            stage_execution=stage_execution,
            operation=operation,
            status=projected_status,
        )


def _adopt_benchmark_v2_incumbent_workflow_service(
    *,
    composition: LearningWorkflowServiceComposition,
    operation_ref: Mapping[str, object],
    worker_ref: Mapping[str, object],
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    supplied_run_id = str(operation_ref.get("run_id") or "")
    supplied_operation_id = str(operation_ref.get("operation_id") or "")
    with get_learning_workflow_operation_lock(
        store=composition.store,
        run_id=supplied_run_id,
        operation_id=supplied_operation_id,
    ):
        current, stage_execution, operation, supplied = (
            _benchmark_v2_workflow_service_context(
                composition=composition,
                operation_ref=operation_ref,
            )
        )
        expected_worker_ref = _benchmark_v2_workflow_service_worker_ref(operation)
        if dict(worker_ref) != expected_worker_ref or supplied["worker_ref"] != expected_worker_ref:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 workflow service adopted worker ref is stale"
            )
        durable_status = _benchmark_v2_workflow_service_phase_status(operation)
        if durable_status in {"complete", "cancelled", "safe_stopped"}:
            return _project_benchmark_v2_workflow_service_step(
                composition=composition,
                workflow_state=current,
                stage_execution=stage_execution,
                operation=operation,
                status=durable_status,
            )
        if supplied["status"] != "advanced":
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent adoption requires an advanced service step"
            )
        if durable_status != "advanced":
            worker_status = status_guarded_learning_stage_worker(
                composition=composition,
                worker_id=operation["worker_ref"]["worker_id"],
                run_id=operation["run_id"],
                operation_id=operation["operation_id"],
            )
            if str(worker_status.get("status") or "") != "completed":
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 incumbent worker result is not complete"
                )
        _resume_benchmark_v2_incumbent_operation(
            composition=composition,
            run_id=operation["run_id"],
            expected_revision=int(current["revision"]),
            stage=operation["stage"],
            operation_id=operation["operation_id"],
            worker_id=operation["worker_ref"]["worker_id"],
        )
        current = composition.store.get(operation["run_id"])
        stage_execution = _benchmark_v2_stage_execution(current, operation["stage"])
        operation = _benchmark_v2_incumbent_operation_from_state(
            current, operation["stage"]
        )
        if operation is None:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent resume did not persist an operation"
            )
        status = _benchmark_v2_workflow_service_phase_status(operation)
        if status not in {"complete", "cancelled", "safe_stopped"}:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent resume did not reach a terminal phase"
            )
        return _project_benchmark_v2_workflow_service_step(
            composition=composition,
            workflow_state=current,
            stage_execution=stage_execution,
            operation=operation,
            status=status,
        )


def _cancel_benchmark_v2_incumbent_workflow_service(
    *,
    composition: LearningWorkflowServiceComposition,
    operation_ref: Mapping[str, object],
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    supplied_run_id = str(operation_ref.get("run_id") or "")
    supplied_operation_id = str(operation_ref.get("operation_id") or "")
    with get_learning_workflow_operation_lock(
        store=composition.store,
        run_id=supplied_run_id,
        operation_id=supplied_operation_id,
    ):
        current, stage_execution, operation, _supplied = (
            _benchmark_v2_workflow_service_context(
                composition=composition,
                operation_ref=operation_ref,
            )
        )
        durable_status = _benchmark_v2_workflow_service_phase_status(operation)
        if durable_status in {"complete", "cancelled", "safe_stopped"}:
            return _project_benchmark_v2_workflow_service_step(
                composition=composition,
                workflow_state=current,
                stage_execution=stage_execution,
                operation=operation,
                status=durable_status,
            )
        _cancel_benchmark_v2_incumbent_operation(
            composition=composition,
            run_id=operation["run_id"],
            expected_revision=int(current["revision"]),
            stage=operation["stage"],
            operation_id=operation["operation_id"],
            reason="benchmark workflow service cancellation requested",
        )
        current = composition.store.get(operation["run_id"])
        stage_execution = _benchmark_v2_stage_execution(current, operation["stage"])
        operation = _benchmark_v2_incumbent_operation_from_state(
            current, operation["stage"]
        )
        if operation is None:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent cancel did not persist an operation"
            )
        status = _benchmark_v2_workflow_service_phase_status(operation)
        return _project_benchmark_v2_workflow_service_step(
            composition=composition,
            workflow_state=current,
            stage_execution=stage_execution,
            operation=operation,
            status=status,
        )


_BENCHMARK_V2_HYBRID_SERVICE_BINDING_CONTRACT = (
    "benchmark_v2_workflow_service_hybrid_binding_v1"
)
_BENCHMARK_V2_HYBRID_SERVICE_BINDING_FIELD = (
    "benchmark_v2_workflow_service_hybrid"
)
_BENCHMARK_V2_HYBRID_CONTINUATION_RECEIPT_CONTRACT = (
    "benchmark_v2_workflow_service_hybrid_continuation_receipt_v1"
)

_BENCHMARK_V2_PROVIDER_TASKS = {
    "panel_learning_hybrid_omni_discovery": "omni",
    "panel_learning_hybrid_qwen_binding": "qwen",
    "panel_learning_calibration_sequence": "vista",
    "vision_observe_screen": "qwen",
}


def _benchmark_v2_dispatch_journal_path(
    *, composition: LearningWorkflowServiceComposition, window_binding: Mapping[str, object]
) -> Path:
    from app.learn.hybrid.benchmark_v2_contracts import content_sha256 as benchmark_sha

    journal_key = benchmark_sha(
        {
            "run_id": str(window_binding["run_id"]),
            "stage": str(window_binding["stage"]),
            "operation_id": str(window_binding["operation_id"]),
        }
    )
    return (
        Path(composition.project_root)
        / "runtime_state"
        / "benchmark-v2-provider-dispatch"
        / f"{journal_key}.jsonl"
    ).resolve()


def _benchmark_v2_dispatch_context_for_worker(
    *,
    composition: LearningWorkflowServiceComposition,
    window_binding: Mapping[str, object],
    task_kind: str,
    revision: int,
) -> dict[str, Any] | None:
    provider = _BENCHMARK_V2_PROVIDER_TASKS.get(task_kind)
    if provider is None:
        return None
    resolver = composition.benchmark_v2_worker_binding_resolver
    if resolver is None:
        # 旧的纯内存 S3 单元测试没有 Task5 绑定解析器；生产组合始终提供解析器。
        if composition.composition_kind == "test":
            return None
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 dispatch Task5 resolver is unavailable"
        )
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        resolve_server_worker_window_binding,
    )

    try:
        binding = deepcopy(dict(window_binding))
        resolution = resolve_server_worker_window_binding(
            resolver=resolver,
            run_id=str(binding["run_id"]),
            stage=str(binding["stage"]),
            operation_id=str(binding["operation_id"]),
            window_binding_ref=binding["window_binding_ref"],
            capture_ref=binding["capture_ref"],
        )
        return _benchmark_v2_dispatch_context_from_serialized(
            composition=composition,
            window_binding=binding,
            serialized_window_binding=resolution["serialized_window_binding"],
            task_kind=task_kind,
            revision=revision,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise LearningWorkflowStageOperationError(
            f"benchmark_v2 dispatch context is invalid: {error}"
        ) from error


def _benchmark_v2_dispatch_context_from_serialized(
    *,
    composition: LearningWorkflowServiceComposition,
    window_binding: Mapping[str, object],
    serialized_window_binding: Mapping[str, object],
    task_kind: str,
    revision: int,
) -> dict[str, Any] | None:
    provider = _BENCHMARK_V2_PROVIDER_TASKS.get(task_kind)
    if provider is None:
        return None
    from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
        compose_benchmark_dispatch_context,
    )

    binding = deepcopy(dict(window_binding))
    operation_ref = {
        "run_id": str(binding["run_id"]),
        "stage": str(binding["stage"]),
        "operation_id": str(binding["operation_id"]),
        "revision": int(revision),
        "window_binding_ref": deepcopy(binding["window_binding_ref"]),
        "capture_ref": deepcopy(binding["capture_ref"]),
    }
    return compose_benchmark_dispatch_context(
        provider=provider,
        operation_ref=operation_ref,
        window_binding=serialized_window_binding,
        receipt_journal_path=_benchmark_v2_dispatch_journal_path(
            composition=composition,
            window_binding=binding,
        ),
    )


def _inject_benchmark_v2_dispatch_context(
    *, payload: Mapping[str, object], context: Mapping[str, object] | None
) -> dict[str, Any]:
    result = deepcopy(dict(payload))
    if _BENCHMARK_V2_DISPATCH_CONTEXT_FIELD in result:
        raise LearningWorkflowStageOperationError(
            "_benchmark_v2_dispatch_context is server-owned"
        )
    if context is not None:
        result[_BENCHMARK_V2_DISPATCH_CONTEXT_FIELD] = deepcopy(dict(context))
    return result


def _validate_benchmark_v2_dispatch_response(
    *,
    composition: LearningWorkflowServiceComposition,
    response: Mapping[str, object],
    window_binding: Mapping[str, object],
    expected_provider_counts: Mapping[str, int],
    hybrid: bool,
    dispatch_revision: int | None,
    provider_dispatch_context_refs: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
        validate_benchmark_dispatch_context_ref,
        validate_benchmark_dispatch_receipt_refs,
    )

    result = deepcopy(dict(response))
    if (
        composition.composition_kind == "test"
        and composition.benchmark_v2_worker_binding_resolver is None
    ):
        return result
    if hybrid:
        orchestration = result.get("orchestration")
        if not isinstance(orchestration, Mapping):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 Hybrid response lost dispatch receipts"
            )
        refs = orchestration.get("benchmark_v2_provider_dispatch_receipt_refs")
        projected_context_refs = orchestration.get(
            "benchmark_v2_provider_dispatch_context_refs"
        )
        if not isinstance(projected_context_refs, Mapping):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 Hybrid dispatch contexts are unavailable"
            )
        if not isinstance(provider_dispatch_context_refs, Mapping):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 server-issued dispatch contexts are unavailable"
            )
        expected_context_refs: dict[str, dict[str, Any]] = {}
        expected_contexts: dict[str, dict[str, Any]] = {}
        for provider in expected_provider_counts:
            try:
                context_ref = validate_benchmark_dispatch_context_ref(
                    provider_dispatch_context_refs[provider]
                )
            except (KeyError, TypeError, ValueError) as error:
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 server-issued dispatch context is invalid"
                ) from error
            expected_context_refs[provider] = context_ref
            expected_contexts[provider] = deepcopy(context_ref["dispatch_context"])
        try:
            projected = {
                provider: validate_benchmark_dispatch_context_ref(context_ref)
                for provider, context_ref in projected_context_refs.items()
            }
        except (TypeError, ValueError) as error:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 Hybrid projected dispatch context is invalid"
            ) from error
        if projected != expected_context_refs:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 Hybrid dispatch context lineage is stale"
            )
    else:
        refs = result.get("_benchmark_v2_provider_dispatch_receipt_refs")
        if (
            isinstance(dispatch_revision, bool)
            or not isinstance(dispatch_revision, int)
            or dispatch_revision < 0
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent dispatch revision is unavailable"
            )
        resolved_dispatch_revision = dispatch_revision
    provider_task = {
        "omni": "panel_learning_hybrid_omni_discovery",
        "qwen": (
            "panel_learning_hybrid_qwen_binding"
            if hybrid
            else "vision_observe_screen"
        ),
        "vista": "panel_learning_calibration_sequence",
    }
    if not hybrid:
        expected_contexts = {}
        for provider in expected_provider_counts:
            context = _benchmark_v2_dispatch_context_for_worker(
                composition=composition,
                window_binding=window_binding,
                task_kind=provider_task[provider],
                revision=resolved_dispatch_revision,
            )
            if not isinstance(context, dict):
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 dispatch context reconstruction failed"
                )
            expected_contexts[provider] = context
    try:
        verified = validate_benchmark_dispatch_receipt_refs(
            receipt_journal_path=_benchmark_v2_dispatch_journal_path(
                composition=composition,
                window_binding=window_binding,
            ),
            receipt_refs=refs,
            operation_identity={
                "run_id": str(window_binding["run_id"]),
                "stage": str(window_binding["stage"]),
                "operation_id": str(window_binding["operation_id"]),
                "window_binding_ref": deepcopy(window_binding["window_binding_ref"]),
                "capture_ref": deepcopy(window_binding["capture_ref"]),
            },
            expected_provider_counts=expected_provider_counts,
            expected_dispatch_contexts=expected_contexts,
        )
    except (OSError, TypeError, ValueError) as error:
        raise LearningWorkflowStageOperationError(
            f"benchmark_v2 dispatch receipts are invalid: {error}"
        ) from error
    if hybrid:
        assert isinstance(result["orchestration"], dict)
        result["orchestration"][
            "benchmark_v2_provider_dispatch_receipt_refs"
        ] = verified
    else:
        result["_benchmark_v2_provider_dispatch_receipt_refs"] = verified
    return result


def _benchmark_v2_expected_dispatch_counts(
    *, task_kind: str, response: Mapping[str, object]
) -> dict[str, int]:
    orchestration = response.get("orchestration")
    if not isinstance(orchestration, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 Hybrid response lost orchestration"
        )
    if task_kind == "panel_learning_hybrid_omni_discovery":
        return {"omni": 1}
    if task_kind in {
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
    }:
        return {"omni": 1, "qwen": 1}
    if task_kind not in {
        "panel_learning_calibration_sequence",
        "panel_learning_hybrid_review_projection",
    }:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 Hybrid dispatch task is invalid"
        )
    batch_count = orchestration.get("benchmark_v2_vista_batch_count")
    if isinstance(batch_count, bool) or not isinstance(batch_count, int) or batch_count < 1:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 VISTA batch_count is unavailable"
        )
    if task_kind == "panel_learning_calibration_sequence":
        result = response.get("result")
        if not isinstance(result, dict):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 VISTA result is unavailable"
            )
        sequence = _hybrid_calibration_sequence_payload(result)
        if sequence.get("batch_count") != batch_count:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 VISTA receipt count differs from calibration batch_count"
            )
    return {"omni": 1, "qwen": 1, "vista": batch_count}


def _validate_benchmark_v2_hybrid_adoption(
    *,
    composition: LearningWorkflowServiceComposition,
    response: Mapping[str, object],
    window_binding: Mapping[str, object],
    task_kind: str,
    provider_dispatch_context_refs: Mapping[str, object],
) -> dict[str, Any]:
    if (
        composition.composition_kind == "test"
        and composition.benchmark_v2_worker_binding_resolver is None
    ):
        return deepcopy(dict(response))
    return _validate_benchmark_v2_dispatch_response(
        composition=composition,
        response=response,
        window_binding=window_binding,
        expected_provider_counts=_benchmark_v2_expected_dispatch_counts(
            task_kind=task_kind, response=response
        ),
        hybrid=True,
        dispatch_revision=None,
        provider_dispatch_context_refs=provider_dispatch_context_refs,
    )


def _compose_benchmark_v2_hybrid_service_binding(
    *,
    screen_group: Mapping[str, object],
    window_binding: Mapping[str, object],
    continuation_receipt: Mapping[str, object] | None = None,
    provider_dispatch_context_refs: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_contracts import (
        content_sha256 as benchmark_content_sha256,
    )

    body = {
        "contract_version": _BENCHMARK_V2_HYBRID_SERVICE_BINDING_CONTRACT,
        "screen_group": deepcopy(dict(screen_group)),
        "window_binding": deepcopy(dict(window_binding)),
        "continuation_receipt": (
            deepcopy(dict(continuation_receipt))
            if isinstance(continuation_receipt, Mapping)
            else None
        ),
        "provider_dispatch_context_refs": deepcopy(
            dict(provider_dispatch_context_refs or {})
        ),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = benchmark_content_sha256(body)
    return _validate_benchmark_v2_hybrid_service_binding(body)


def _validate_benchmark_v2_hybrid_service_binding(value: object) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_contracts import (
        content_sha256 as benchmark_content_sha256,
    )
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        validate_benchmark_v2_hybrid_screen_group_start,
        validate_benchmark_v2_workflow_window_binding,
    )
    from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
        validate_benchmark_dispatch_context_ref,
    )

    fields = {
        "contract_version",
        "screen_group",
        "window_binding",
        "continuation_receipt",
        "provider_dispatch_context_refs",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid service binding is not closed"
        )
    binding = deepcopy(dict(value))
    if (
        binding["contract_version"]
        != _BENCHMARK_V2_HYBRID_SERVICE_BINDING_CONTRACT
        or binding["artifact_is_authorization"] is not False
        or binding["execute_binding_enabled"] is not False
        or binding["content_sha256"] != benchmark_content_sha256(binding)
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid service binding is invalid"
        )
    try:
        binding["screen_group"] = validate_benchmark_v2_hybrid_screen_group_start(
            binding["screen_group"]
        )
        binding["window_binding"] = validate_benchmark_v2_workflow_window_binding(
            binding["window_binding"]
        )
        if binding["continuation_receipt"] is not None:
            binding["continuation_receipt"] = (
                _validate_benchmark_v2_hybrid_continuation_receipt(
                    binding["continuation_receipt"]
                )
            )

        context_refs = binding["provider_dispatch_context_refs"]
        if not isinstance(context_refs, Mapping):
            raise ValueError("provider dispatch context refs are invalid")
        normalized_context_refs: dict[str, dict[str, Any]] = {}
        if any(
            provider not in {"omni", "qwen", "vista"}
            for provider in context_refs
        ):
            raise ValueError("provider dispatch context refs contain an unknown provider")
        for provider, context_ref in context_refs.items():
            validated_ref = validate_benchmark_dispatch_context_ref(context_ref)
            if validated_ref["provider"] != provider:
                raise ValueError("provider dispatch context ref key differs")
            normalized_context_refs[provider] = validated_ref
        binding["provider_dispatch_context_refs"] = normalized_context_refs
    except (TypeError, ValueError) as error:
        raise LearningWorkflowStageOperationError(
            f"benchmark_v2 hybrid service binding lineage is invalid: {error}"
        ) from error
    return binding


def _benchmark_v2_hybrid_binding_identity_sha256(
    binding: Mapping[str, object],
) -> str:
    from app.learn.hybrid.benchmark_v2_contracts import (
        content_sha256 as benchmark_content_sha256,
    )

    return benchmark_content_sha256(
        {
            "contract_version": binding.get("contract_version"),
            "screen_group": deepcopy(binding.get("screen_group")),
            "window_binding": deepcopy(binding.get("window_binding")),
            "artifact_is_authorization": binding.get("artifact_is_authorization"),
            "execute_binding_enabled": binding.get("execute_binding_enabled"),
        }
    )


def _validate_benchmark_v2_hybrid_continuation_receipt(
    value: object,
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_contracts import (
        content_sha256 as benchmark_content_sha256,
    )

    fields = {
        "contract_version",
        "receipt_phase",
        "binding_identity_sha256",
        "consumed_operation_ref_sha256",
        "returned_worker_ref",
        "returned_status",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid continuation receipt is not closed"
        )
    receipt = deepcopy(dict(value))
    if (
        receipt["contract_version"]
        != _BENCHMARK_V2_HYBRID_CONTINUATION_RECEIPT_CONTRACT
        or receipt["artifact_is_authorization"] is not False
        or receipt["execute_binding_enabled"] is not False
        or receipt["receipt_phase"] not in {"returned", "terminal_prepared"}
        or receipt["content_sha256"] != benchmark_content_sha256(receipt)
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid continuation receipt is invalid"
        )
    for name in (
        "binding_identity_sha256",
        "consumed_operation_ref_sha256",
    ):
        digest = receipt[name]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise LearningWorkflowStageOperationError(
                f"benchmark_v2 hybrid continuation receipt {name} is invalid"
            )
    expected_worker = _benchmark_v2_hybrid_worker_ref(receipt["returned_worker_ref"])
    if receipt["returned_worker_ref"] != expected_worker:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid continuation receipt worker ref is invalid"
        )
    receipt["returned_worker_ref"] = expected_worker
    if receipt["receipt_phase"] == "terminal_prepared":
        if receipt["returned_status"] is not None:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid terminal-prepared receipt claimed an outcome"
            )
    elif receipt["returned_status"] not in {
        "pending",
        "advanced",
        "complete",
        "safe_stopped",
    }:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid returned receipt status is invalid"
        )
    return receipt


def _compose_benchmark_v2_hybrid_continuation_receipt(
    *,
    binding: Mapping[str, object],
    consumed_operation_ref: Mapping[str, object],
    worker_record: Mapping[str, object],
    returned_status: str | None,
    receipt_phase: str = "returned",
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_contracts import (
        content_sha256 as benchmark_content_sha256,
    )

    body = {
        "contract_version": _BENCHMARK_V2_HYBRID_CONTINUATION_RECEIPT_CONTRACT,
        "receipt_phase": receipt_phase,
        "binding_identity_sha256": _benchmark_v2_hybrid_binding_identity_sha256(
            binding
        ),
        "consumed_operation_ref_sha256": str(
            consumed_operation_ref.get("content_sha256") or ""
        ),
        "returned_worker_ref": _benchmark_v2_hybrid_worker_ref(worker_record),
        "returned_status": returned_status,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = benchmark_content_sha256(body)
    return _validate_benchmark_v2_hybrid_continuation_receipt(body)


def _benchmark_v2_hybrid_binding_with_continuation_receipt(
    *,
    binding: Mapping[str, object],
    receipt: Mapping[str, object],
) -> dict[str, Any]:
    current = _validate_benchmark_v2_hybrid_service_binding(binding)
    return _compose_benchmark_v2_hybrid_service_binding(
        screen_group=current["screen_group"],
        window_binding=current["window_binding"],
        continuation_receipt=receipt,
        provider_dispatch_context_refs=current["provider_dispatch_context_refs"],
    )


def _benchmark_v2_hybrid_binding_with_dispatch_context(
    *,
    binding: Mapping[str, object],
    context: Mapping[str, object],
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
        compose_benchmark_dispatch_context_ref,
    )

    current = _validate_benchmark_v2_hybrid_service_binding(binding)
    context_ref = compose_benchmark_dispatch_context_ref(context=context)
    provider = str(context_ref["provider"])
    refs = deepcopy(current["provider_dispatch_context_refs"])
    existing = refs.get(provider)
    if existing is not None and existing != context_ref:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 provider dispatch context was already issued and differs"
        )
    refs[provider] = context_ref
    return _compose_benchmark_v2_hybrid_service_binding(
        screen_group=current["screen_group"],
        window_binding=current["window_binding"],
        continuation_receipt=current["continuation_receipt"],
        provider_dispatch_context_refs=refs,
    )


def _benchmark_v2_hybrid_service_binding_from_execution(
    stage_execution: Mapping[str, object],
) -> dict[str, Any] | None:
    value = stage_execution.get(_BENCHMARK_V2_HYBRID_SERVICE_BINDING_FIELD)
    if value is None:
        return None
    return _validate_benchmark_v2_hybrid_service_binding(value)


def _benchmark_v2_exact_json_equal(left: object, right: object) -> bool:
    from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes

    try:
        return canonical_json_bytes(left) == canonical_json_bytes(right)
    except (TypeError, ValueError):
        return False


def _benchmark_v2_hybrid_lineage_workflow_revision(
    binding: Mapping[str, object],
) -> int:
    """从持久化绑定取得不可变截图 revision，不得用可变 store CAS 替代。"""

    screen_group = binding.get("screen_group")
    window_binding = binding.get("window_binding")
    capture_bundle = (
        screen_group.get("capture_bundle")
        if isinstance(screen_group, Mapping)
        else None
    )
    bundle_ref = (
        screen_group.get("hybrid_capture_bundle_ref")
        if isinstance(screen_group, Mapping)
        else None
    )
    if (
        not isinstance(capture_bundle, Mapping)
        or capture_bundle.get("bundle_ref") != bundle_ref
        or not isinstance(window_binding, Mapping)
        or capture_bundle.get("run_id") != window_binding.get("run_id")
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid capture bundle lineage is invalid"
        )
    revision = (
        capture_bundle.get("workflow_revision")
        if isinstance(capture_bundle, Mapping)
        else None
    )
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid capture workflow revision is invalid"
        )
    return revision


def _require_benchmark_v2_hybrid_payload_workflow_revision(
    *, payload: Mapping[str, object], binding: Mapping[str, object]
) -> int:
    revision = _benchmark_v2_hybrid_lineage_workflow_revision(binding)
    screen_group = binding["screen_group"]
    window_binding = binding["window_binding"]
    orchestration = payload.get("_hybrid_orchestration")
    supplied_revision = payload.get("workflow_revision")
    orchestration_revision = (
        orchestration.get("workflow_revision")
        if isinstance(orchestration, Mapping)
        else None
    )
    if (
        (
            "workflow_revision" in payload
            and (
                isinstance(supplied_revision, bool)
                or not isinstance(supplied_revision, int)
                or supplied_revision != revision
            )
        )
        or not isinstance(orchestration, Mapping)
        or isinstance(orchestration_revision, bool)
        or not isinstance(orchestration_revision, int)
        or orchestration_revision != revision
        or orchestration.get("run_id") != window_binding["run_id"]
        or not _benchmark_v2_exact_json_equal(
            orchestration.get("hybrid_capture_bundle_ref"),
            screen_group["hybrid_capture_bundle_ref"],
        )
        or orchestration.get("capture_image_path")
        != screen_group["capture_image_path"]
        or not _benchmark_v2_exact_json_equal(
            orchestration.get("hybrid_config"),
            screen_group["hybrid_config"],
        )
        or not _benchmark_v2_exact_json_equal(
            orchestration.get("capture_bundle"),
            screen_group["capture_bundle"],
        )
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid payload workflow lineage is stale"
        )
    for name, expected in (
        ("run_id", window_binding["run_id"]),
        (
            "hybrid_capture_bundle_ref",
            screen_group["hybrid_capture_bundle_ref"],
        ),
        ("capture_image_path", screen_group["capture_image_path"]),
        ("capture_bundle", screen_group["capture_bundle"]),
    ):
        if name in payload and not _benchmark_v2_exact_json_equal(
            payload[name], expected
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid payload workflow lineage is stale"
            )
    return revision


def _require_benchmark_v2_hybrid_capture_bundle(
    *, project_root: str | Path, binding: Mapping[str, object]
) -> int:
    revision = _benchmark_v2_hybrid_lineage_workflow_revision(binding)
    screen_group = binding["screen_group"]
    window_binding = binding["window_binding"]
    try:
        loaded = load_and_verify_hybrid_capture_bundle(
            project_root=Path(project_root).resolve(),
            bundle_ref=deepcopy(screen_group["hybrid_capture_bundle_ref"]),
            expected_run_id=str(window_binding["run_id"]),
            expected_workflow_revision=revision,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise LearningWorkflowStageOperationError(
            f"benchmark_v2 hybrid capture bundle is invalid · {exc}"
        ) from exc
    expanded_bundle = deepcopy(dict(screen_group["capture_bundle"]))
    expanded_bundle.pop("bundle_ref", None)
    if not _benchmark_v2_exact_json_equal(loaded, expanded_bundle):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid expanded capture bundle is stale"
        )
    return revision


def _persist_benchmark_v2_hybrid_service_binding(
    *,
    composition: LearningWorkflowServiceComposition,
    workflow_state: Mapping[str, object],
    stage: str,
    binding: Mapping[str, object],
) -> dict[str, Any]:
    stage_execution = _benchmark_v2_stage_execution(workflow_state, stage)
    if stage_execution.get("learning_pipeline_mode") != "hybrid_v1_1":
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid service requires a Hybrid v1.1 stage operation"
        )
    existing = _benchmark_v2_hybrid_service_binding_from_execution(stage_execution)
    validated = _validate_benchmark_v2_hybrid_service_binding(binding)
    if existing is not None:
        if (
            _benchmark_v2_hybrid_binding_identity_sha256(existing)
            != _benchmark_v2_hybrid_binding_identity_sha256(validated)
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid service binding is stale"
            )
        if existing == validated:
            return deepcopy(dict(workflow_state))
    stage_execution[_BENCHMARK_V2_HYBRID_SERVICE_BINDING_FIELD] = validated
    stages = workflow_state.get("stages")
    stage_record = stages.get(stage) if isinstance(stages, Mapping) else None
    evidence_refs = (
        deepcopy(dict(stage_record.get("evidence_refs")))
        if isinstance(stage_record, Mapping)
        and isinstance(stage_record.get("evidence_refs"), Mapping)
        else {}
    )
    evidence_refs["stage_execution"] = stage_execution
    return transition_learning_workflow_run(
        store=composition.store,
        project_root=composition.project_root,
        run_id=str(workflow_state["run_id"]),
        expected_revision=int(workflow_state["revision"]),
        stage=stage,
        outcome="running",
        reason=(
            str(stage_record.get("reason") or "")
            if isinstance(stage_record, Mapping)
            else ""
        ),
        evidence_refs=evidence_refs,
    )


def _benchmark_v2_hybrid_worker_ref(record: Mapping[str, object]) -> dict[str, Any]:
    fields = (
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "task_kind",
    )
    if any(not isinstance(record.get(name), str) or not record.get(name) for name in fields):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid worker identity is incomplete"
        )
    return seal_immutable(
        {
            "contract_version": "benchmark_v2_workflow_service_generic_worker_ref_v1",
            **{name: str(record[name]) for name in fields},
        }
    )


def _persist_benchmark_v2_hybrid_continuation_receipt(
    *,
    composition: LearningWorkflowServiceComposition,
    workflow_state: Mapping[str, object],
    stage: str,
    binding: Mapping[str, object],
    consumed_operation_ref: Mapping[str, object],
    worker_record: Mapping[str, object],
    returned_status: str | None,
    receipt_phase: str = "returned",
) -> dict[str, Any]:
    receipt = _compose_benchmark_v2_hybrid_continuation_receipt(
        binding=binding,
        consumed_operation_ref=consumed_operation_ref,
        worker_record=worker_record,
        returned_status=returned_status,
        receipt_phase=receipt_phase,
    )
    updated_binding = _benchmark_v2_hybrid_binding_with_continuation_receipt(
        binding=binding,
        receipt=receipt,
    )
    return _persist_benchmark_v2_hybrid_service_binding(
        composition=composition,
        workflow_state=workflow_state,
        stage=stage,
        binding=updated_binding,
    )


def _benchmark_v2_hybrid_continuation_predecessor(
    *,
    binding: Mapping[str, object],
    worker_record: Mapping[str, object],
    status: str,
) -> str | None:
    current = _validate_benchmark_v2_hybrid_service_binding(binding)
    receipt = current.get("continuation_receipt")
    if receipt is None:
        return None
    validated_receipt = _validate_benchmark_v2_hybrid_continuation_receipt(receipt)
    identity_matches = (
        validated_receipt["binding_identity_sha256"]
        == _benchmark_v2_hybrid_binding_identity_sha256(current)
        and validated_receipt["returned_worker_ref"]
        == _benchmark_v2_hybrid_worker_ref(worker_record)
    )
    status_matches = (
        validated_receipt["receipt_phase"] == "returned"
        and validated_receipt["returned_status"] == status
    ) or (
        validated_receipt["receipt_phase"] == "terminal_prepared"
        and status in {"complete", "safe_stopped"}
    )
    if not identity_matches or not status_matches:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid continuation receipt differs from current step"
        )
    return str(validated_receipt["consumed_operation_ref_sha256"])


def _benchmark_v2_hybrid_attachment(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    stage: str,
    operation_id: str,
) -> dict[str, Any]:
    record = _LearningWorkflowRegistryOwner(
        composition.worker_registry
    ).project_worker_attachment(
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
    )
    if not isinstance(record, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid worker attachment is missing"
        )
    result = deepcopy(dict(record))
    _benchmark_v2_hybrid_worker_ref(result)
    return result


def _benchmark_v2_hybrid_service_status(
    *,
    workflow_state: Mapping[str, object],
    stage: str,
    worker_record: Mapping[str, object],
) -> str:
    stages = workflow_state.get("stages")
    stage_record = stages.get(stage) if isinstance(stages, Mapping) else None
    stage_status = stage_record.get("status") if isinstance(stage_record, Mapping) else None
    if stage_status == "completed":
        return "complete"
    if stage_status in {"safe_stopped", "failed"}:
        return "safe_stopped"
    if stage_status != "running":
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid workflow stage is not projectable"
        )
    worker_status = worker_record.get("status")
    if worker_status == "running":
        return "pending"
    if worker_status == "completed" and worker_record.get("result_available") is True:
        return "advanced"
    raise LearningWorkflowStageOperationError(
        f"benchmark_v2 hybrid worker status is not projectable: {worker_status}"
    )


def _project_benchmark_v2_hybrid_operation_ref(
    *,
    workflow_state: Mapping[str, object],
    stage_execution: Mapping[str, object],
    binding: Mapping[str, object],
    worker_record: Mapping[str, object],
    status: str,
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_contracts import (
        content_sha256 as benchmark_content_sha256,
    )
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_workflow_service_operation_ref,
    )

    current_binding = _validate_benchmark_v2_hybrid_service_binding(binding)
    window_binding = current_binding["window_binding"]
    screen_group = current_binding["screen_group"]
    return compose_benchmark_v2_workflow_service_operation_ref(
        mode="hybrid_v1_1",
        run_id=str(window_binding["run_id"]),
        stage=str(window_binding["stage"]),
        operation_id=str(window_binding["operation_id"]),
        workflow_state_ref={
            "run_id": str(workflow_state["run_id"]),
            "revision": int(workflow_state["revision"]),
            "content_sha256": benchmark_content_sha256(dict(workflow_state)),
        },
        stage_execution_ref={
            "run_id": str(window_binding["run_id"]),
            "stage": str(window_binding["stage"]),
            "operation_id": str(window_binding["operation_id"]),
            "revision": int(workflow_state["revision"]),
            "content_sha256": benchmark_content_sha256(dict(stage_execution)),
        },
        request_ref=screen_group["request_ref"],
        window_binding_ref=window_binding["window_binding_ref"],
        capture_ref=window_binding["capture_ref"],
        worker_ref=_benchmark_v2_hybrid_worker_ref(worker_record),
        status=status,
        predecessor_content_sha256=(
            _benchmark_v2_hybrid_continuation_predecessor(
                binding=current_binding,
                worker_record=worker_record,
                status=status,
            )
        ),
    )


def _benchmark_v2_hybrid_service_context(
    *,
    composition: LearningWorkflowServiceComposition,
    operation_ref: Mapping[str, object],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        validate_benchmark_v2_workflow_service_operation_ref,
    )

    _require_minted_learning_workflow_service_composition(composition)
    supplied = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
    if supplied["mode"] != "hybrid_v1_1":
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 workflow service operation is not Hybrid v1.1"
        )
    current = composition.store.get(supplied["run_id"])
    stage_execution = _benchmark_v2_stage_execution(current, supplied["stage"])
    binding = _benchmark_v2_hybrid_service_binding_from_execution(stage_execution)
    if binding is None:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid service binding is missing"
        )
    window_binding = binding["window_binding"]
    if any(
        supplied[name] != window_binding[name]
        for name in ("run_id", "stage", "operation_id")
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid service operation identity is stale"
        )
    worker_record = _benchmark_v2_hybrid_attachment(
        composition=composition,
        run_id=supplied["run_id"],
        stage=supplied["stage"],
        operation_id=supplied["operation_id"],
    )
    current_status = _benchmark_v2_hybrid_service_status(
        workflow_state=current,
        stage=supplied["stage"],
        worker_record=worker_record,
    )
    allowed_statuses = (
        {current_status}
        if current_status in {"complete", "safe_stopped"}
        else {"pending", "advanced"}
    )
    if supplied["status"] not in allowed_statuses:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid service operation status is stale"
        )
    expected = _project_benchmark_v2_hybrid_operation_ref(
        workflow_state=current,
        stage_execution=stage_execution,
        binding=binding,
        worker_record=worker_record,
        status=supplied["status"],
    )
    if supplied != expected:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid service operation ref is stale"
        )
    return current, stage_execution, binding, worker_record, supplied


def _read_benchmark_v2_hybrid_adopted_projection(
    *,
    composition: LearningWorkflowServiceComposition,
    worker_record: Mapping[str, object],
    binding: Mapping[str, object],
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_adopted_result_projection,
    )

    adoption = _LearningWorkflowRegistryOwner(
        composition.worker_registry
    ).read_worker_result(
        worker_id=worker_record["worker_id"],
        run_id=worker_record["run_id"],
        stage=worker_record["stage"],
        operation_id=worker_record["operation_id"],
    )
    receipt = adoption.get("receipt") if isinstance(adoption, Mapping) else None
    response = adoption.get("response") if isinstance(adoption, Mapping) else None
    if not isinstance(receipt, Mapping) or not isinstance(response, Mapping):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid adopted result is incomplete"
        )
    expected = {
        "worker_id": worker_record["worker_id"],
        "run_id": worker_record["run_id"],
        "stage": worker_record["stage"],
        "operation_id": worker_record["operation_id"],
        "task_kind": worker_record["task_kind"],
        "model_request_id": worker_record["model_request_id"],
        "payload_sha256": worker_record["payload_sha256"],
    }
    if any(receipt.get(name) != value for name, value in expected.items()):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid adopted result lineage differs"
        )
    response = _validate_benchmark_v2_hybrid_adoption(
        composition=composition,
        response=response,
        window_binding=binding["window_binding"],
        task_kind=str(worker_record["task_kind"]),
        provider_dispatch_context_refs=binding[
            "provider_dispatch_context_refs"
        ],
    )
    result_sha256 = receipt.get("result_sha256")
    if not isinstance(result_sha256, str) or len(result_sha256) != 64:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid adopted result SHA is invalid"
        )
    return compose_benchmark_v2_adopted_result_projection(
        mode="hybrid_v1_1",
        run_id=str(worker_record["run_id"]),
        stage=str(worker_record["stage"]),
        operation_id=str(worker_record["operation_id"]),
        worker_ref=_benchmark_v2_hybrid_worker_ref(worker_record),
        model_request_ref={
            "id": str(worker_record["model_request_id"]),
            "content_sha256": str(worker_record["payload_sha256"]),
        },
        payload_ref={"content_sha256": str(worker_record["payload_sha256"])},
        result_ref={"content_sha256": result_sha256},
        adoption_ref={"content_sha256": content_sha256(dict(receipt))},
        response=response,
        terminal_receipt=None,
        window_adoption_ref=None,
        worker_cleanup_ref=None,
        provider_cleanup_ref=None,
    )


def _project_benchmark_v2_hybrid_step(
    *,
    composition: LearningWorkflowServiceComposition,
    workflow_state: Mapping[str, object],
    stage_execution: Mapping[str, object],
    binding: Mapping[str, object],
    worker_record: Mapping[str, object],
    status: str,
) -> dict[str, Any]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_provider_dispatch_context_projection,
        compose_benchmark_v2_workflow_service_step,
    )
    from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
        validate_benchmark_dispatch_context_ref,
    )

    projection = None
    if status == "complete":
        projection = _read_benchmark_v2_hybrid_adopted_projection(
            composition=composition,
            worker_record=worker_record,
            binding=binding,
        )
    worker_cleanup_ref = None
    provider_cleanup_ref = None
    if status == "safe_stopped":
        cancellation = stage_execution.get("cancellation")
        if isinstance(cancellation, Mapping):
            worker_identity = _benchmark_v2_hybrid_worker_ref(worker_record)
            worker_cleanup_ref = seal_immutable(
                {
                    "contract_version": (
                        "benchmark_v2_hybrid_worker_cleanup_ref_v1"
                    ),
                    "run_id": worker_identity["run_id"],
                    "stage": worker_identity["stage"],
                    "operation_id": worker_identity["operation_id"],
                    "worker_id": worker_identity["worker_id"],
                    "model_request_id": worker_identity["model_request_id"],
                    "payload_sha256": worker_identity["payload_sha256"],
                    "backend_compute_termination": str(
                        cancellation.get("backend_compute_termination")
                        or "not_covered"
                    ),
                    "model_service_compute_termination": str(
                        cancellation.get("model_service_compute_termination")
                        or "not_covered"
                    ),
                    "cancellation_ref": {
                        "content_sha256": content_sha256(dict(cancellation))
                    },
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )
        provider_cleanup_value = worker_record.get(
            "benchmark_provider_cleanup_ref"
        )
        if isinstance(provider_cleanup_value, Mapping):
            provider_cleanup_ref = _validate_benchmark_v2_hybrid_provider_cleanup(
                cleanup=provider_cleanup_value,
                worker_record=worker_record,
            )
    provider_context_projection = None
    provider = _BENCHMARK_V2_PROVIDER_TASKS.get(str(worker_record["task_kind"]))
    if provider is not None:
        context_ref_value = binding["provider_dispatch_context_refs"].get(provider)
        if isinstance(context_ref_value, Mapping):
            context_ref = validate_benchmark_dispatch_context_ref(context_ref_value)
            context = context_ref["dispatch_context"]
            provider_context_projection = (
                compose_benchmark_v2_provider_dispatch_context_projection(
                    provider=str(context["provider"]),
                    context_content_sha256=str(context["content_sha256"]),
                    operation_ref=context["operation_ref"],
                )
            )
    return compose_benchmark_v2_workflow_service_step(
        operation_ref=_project_benchmark_v2_hybrid_operation_ref(
            workflow_state=workflow_state,
            stage_execution=stage_execution,
            binding=binding,
            worker_record=worker_record,
            status=status,
        ),
        observed_task_kind=str(worker_record["task_kind"]),
        provider_dispatch_context_projection=provider_context_projection,
        adopted_result_projection=projection,
        terminal_receipt=None,
        cleanup_refs={
            "worker_cleanup_ref": worker_cleanup_ref,
            "provider_cleanup_ref": provider_cleanup_ref,
        },
    )


def _validate_benchmark_v2_hybrid_provider_cleanup(
    *,
    cleanup: object,
    worker_record: Mapping[str, object],
) -> dict[str, Any]:
    fields = {
        "contract_version",
        "status",
        "outcome",
        "authority_kind",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "reservation_ref",
        "acquisition_owner_ref",
        "acquisition_intent_ref",
        "runtime_owner_ref",
        "cleanup_receipt_ref",
        "content_sha256",
    }
    if not isinstance(cleanup, Mapping) or set(cleanup) != fields:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid provider cleanup is not closed"
        )
    projection = deepcopy(dict(cleanup))
    if (
        projection.get("contract_version") != "benchmark_provider_cleanup_ref_v1"
        or projection.get("status") != "cleanup_verified"
        or projection.get("outcome")
        not in {"verified_not_acquired", "verified_exact_process_exited"}
        or projection.get("authority_kind")
        != "benchmark_v2_workflow_service_dispatch_cleanup"
        or any(
            projection.get(name) != worker_record.get(name)
            for name in (
                "run_id",
                "stage",
                "operation_id",
                "worker_id",
                "model_request_id",
                "payload_sha256",
            )
        )
        or projection.get("content_sha256") != content_sha256(projection)
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid provider cleanup lineage differs"
        )
    for name in (
        "reservation_ref",
        "acquisition_owner_ref",
        "acquisition_intent_ref",
        "runtime_owner_ref",
        "cleanup_receipt_ref",
    ):
        ref = projection.get(name)
        if (
            not isinstance(ref, Mapping)
            or set(ref) != {"content_sha256"}
            or not isinstance(ref.get("content_sha256"), str)
            or len(str(ref["content_sha256"])) != 64
            or any(
                character not in "0123456789abcdef"
                for character in str(ref["content_sha256"])
            )
        ):
            raise LearningWorkflowStageOperationError(
                f"benchmark_v2 hybrid provider cleanup {name} is invalid"
            )
    return projection


def _replay_benchmark_v2_hybrid_consumed_operation_ref(
    *,
    composition: LearningWorkflowServiceComposition,
    operation_ref: Mapping[str, object],
) -> dict[str, Any] | None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        validate_benchmark_v2_workflow_service_operation_ref,
    )

    supplied = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
    if supplied["mode"] != "hybrid_v1_1":
        return None
    current = composition.store.get(supplied["run_id"])
    stage_execution = _benchmark_v2_stage_execution(current, supplied["stage"])
    binding = _benchmark_v2_hybrid_service_binding_from_execution(stage_execution)
    if binding is None:
        return None
    receipt_value = binding.get("continuation_receipt")
    if receipt_value is None:
        return None
    receipt = _validate_benchmark_v2_hybrid_continuation_receipt(receipt_value)
    if receipt["consumed_operation_ref_sha256"] != supplied["content_sha256"]:
        return None
    window_binding = binding["window_binding"]
    screen_group = binding["screen_group"]
    if (
        any(
            supplied[name] != window_binding[name]
            for name in ("run_id", "stage", "operation_id")
        )
        or supplied["request_ref"] != screen_group["request_ref"]
        or supplied["window_binding_ref"] != window_binding["window_binding_ref"]
        or supplied["capture_ref"] != window_binding["capture_ref"]
        or receipt["binding_identity_sha256"]
        != _benchmark_v2_hybrid_binding_identity_sha256(binding)
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid consumed operation binding is stale"
        )
    worker_record = _benchmark_v2_hybrid_attachment(
        composition=composition,
        run_id=supplied["run_id"],
        stage=supplied["stage"],
        operation_id=supplied["operation_id"],
    )
    actual_status = _benchmark_v2_hybrid_service_status(
        workflow_state=current,
        stage=supplied["stage"],
        worker_record=worker_record,
    )
    worker_matches = receipt["returned_worker_ref"] == (
        _benchmark_v2_hybrid_worker_ref(worker_record)
    )
    if not worker_matches:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid consumed operation replay is stale"
        )
    if receipt["receipt_phase"] == "terminal_prepared":
        if actual_status == "advanced":
            return None
        if actual_status not in {"complete", "safe_stopped"}:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid terminal-prepared replay is not recoverable"
            )
        returned_status = actual_status
    else:
        returned_status = str(receipt["returned_status"])
        status_is_compatible = actual_status == returned_status or (
            returned_status == "pending" and actual_status == "advanced"
        )
        if not status_is_compatible:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid consumed operation replay is stale"
            )
    return _project_benchmark_v2_hybrid_step(
        composition=composition,
        workflow_state=current,
        stage_execution=stage_execution,
        binding=binding,
        worker_record=worker_record,
        status=returned_status,
    )


def _benchmark_v2_hybrid_terminal_prepared_context(
    *,
    composition: LearningWorkflowServiceComposition,
    operation_ref: Mapping[str, object],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        validate_benchmark_v2_workflow_service_operation_ref,
    )

    supplied = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
    if supplied["mode"] != "hybrid_v1_1":
        return None
    current = composition.store.get(supplied["run_id"])
    stage_execution = _benchmark_v2_stage_execution(current, supplied["stage"])
    binding = _benchmark_v2_hybrid_service_binding_from_execution(stage_execution)
    if binding is None:
        return None
    receipt_value = binding.get("continuation_receipt")
    if receipt_value is None:
        return None
    receipt = _validate_benchmark_v2_hybrid_continuation_receipt(receipt_value)
    if (
        receipt["receipt_phase"] != "terminal_prepared"
        or receipt["consumed_operation_ref_sha256"] != supplied["content_sha256"]
    ):
        return None
    window_binding = binding["window_binding"]
    screen_group = binding["screen_group"]
    if (
        any(
            supplied[name] != window_binding[name]
            for name in ("run_id", "stage", "operation_id")
        )
        or supplied["request_ref"] != screen_group["request_ref"]
        or supplied["window_binding_ref"] != window_binding["window_binding_ref"]
        or supplied["capture_ref"] != window_binding["capture_ref"]
        or receipt["binding_identity_sha256"]
        != _benchmark_v2_hybrid_binding_identity_sha256(binding)
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid terminal-prepared binding is stale"
        )
    worker_record = _benchmark_v2_hybrid_attachment(
        composition=composition,
        run_id=supplied["run_id"],
        stage=supplied["stage"],
        operation_id=supplied["operation_id"],
    )
    if receipt["returned_worker_ref"] != _benchmark_v2_hybrid_worker_ref(
        worker_record
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid terminal-prepared worker is stale"
        )
    status = _benchmark_v2_hybrid_service_status(
        workflow_state=current,
        stage=supplied["stage"],
        worker_record=worker_record,
    )
    if status != "advanced":
        return None
    return current, stage_execution, binding, worker_record, supplied


def _lookup_benchmark_v2_hybrid_workflow_service(
    *,
    composition: LearningWorkflowServiceComposition,
    screen_group: Mapping[str, object],
    window_binding: Mapping[str, object],
) -> dict[str, Any] | None:
    """只读重建已存在的 Hybrid step；不存在时绝不创建 worker。"""

    _require_minted_learning_workflow_service_composition(composition)
    run_id = str(window_binding["run_id"])
    stage = str(window_binding["stage"])
    operation_id = str(window_binding["operation_id"])
    with get_learning_workflow_operation_lock(
        store=composition.store,
        run_id=run_id,
        operation_id=operation_id,
    ):
        try:
            current = composition.store.get(run_id)
        except LearningWorkflowTransitionError as error:
            if str(error) == "workflow run not found":
                return None
            raise
        if current.get("current_stage") != stage:
            return None
        stage_execution = _benchmark_v2_stage_execution(current, stage)
        binding = _benchmark_v2_hybrid_service_binding_from_execution(
            stage_execution
        )
        if binding is None:
            return None
        proposed = _compose_benchmark_v2_hybrid_service_binding(
            screen_group=screen_group,
            window_binding=window_binding,
        )
        if (
            _benchmark_v2_hybrid_binding_identity_sha256(binding)
            != _benchmark_v2_hybrid_binding_identity_sha256(proposed)
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid lookup binding is stale"
            )
        attachment = _LearningWorkflowRegistryOwner(
            composition.worker_registry
        ).project_worker_attachment(
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        )
        if not isinstance(attachment, Mapping):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid lookup recovery_required: "
                "durable binding has no worker attachment"
            )
        worker_record = deepcopy(dict(attachment))
        _benchmark_v2_hybrid_worker_ref(worker_record)
        status = _benchmark_v2_hybrid_service_status(
            workflow_state=current,
            stage=stage,
            worker_record=worker_record,
        )
        return _project_benchmark_v2_hybrid_step(
            composition=composition,
            workflow_state=current,
            stage_execution=stage_execution,
            binding=binding,
            worker_record=worker_record,
            status=status,
        )


def _ensure_benchmark_v2_hybrid_workflow_run(
    *,
    composition: LearningWorkflowServiceComposition,
    screen_group: Mapping[str, object],
    window_binding: Mapping[str, object],
) -> dict[str, Any]:
    """在 service owner 内幂等建立 exact benchmark run 与受管 stage。"""

    run_id = str(window_binding["run_id"])
    stage = str(window_binding["stage"])
    operation_id = str(window_binding["operation_id"])
    start_intent = seal_immutable(
        {
            "contract_version": "benchmark_v2_hybrid_run_start_intent_v1",
            "screen_group_ref": {
                "id": str(screen_group["screen_group"]),
                "content_sha256": str(screen_group["content_sha256"]),
            },
            "request_ref": deepcopy(screen_group["request_ref"]),
            "window_binding_ref": deepcopy(window_binding["window_binding_ref"]),
            "capture_ref": deepcopy(window_binding["capture_ref"]),
            "capture_image_path": str(screen_group["capture_image_path"]),
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    try:
        current = composition.store.get(run_id)
    except LearningWorkflowTransitionError as error:
        if str(error) != "workflow run not found":
            raise
        current = transition_learning_workflow_run(
            store=composition.store,
            project_root=composition.project_root,
            run_id=run_id,
            expected_revision=0,
            stage="bind_capture",
            outcome="running",
            reason="benchmark_v2 hybrid capture binding",
            evidence_refs={"benchmark_v2_hybrid_start_intent": start_intent},
        )

    if current.get("current_stage") == "bind_capture":
        record = current["stages"]["bind_capture"]
        evidence = record.get("evidence_refs")
        existing_intent = (
            evidence.get("benchmark_v2_hybrid_start_intent")
            if isinstance(evidence, Mapping)
            else None
        )
        if existing_intent != start_intent:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid run start intent is stale"
            )
        if record.get("status") == "running":
            current = transition_learning_workflow_run(
                store=composition.store,
                project_root=composition.project_root,
                run_id=run_id,
                expected_revision=int(current["revision"]),
                stage="bind_capture",
                outcome="completed",
                reason="benchmark_v2 hybrid capture bound",
                evidence_refs={
                    "image_path": str(screen_group["capture_image_path"]),
                    "benchmark_v2_hybrid_start_intent": start_intent,
                },
            )
        completed_record = current["stages"]["bind_capture"]
        completed_evidence = completed_record.get("evidence_refs")
        if (
            completed_record.get("status") != "completed"
            or not isinstance(completed_evidence, Mapping)
            or completed_evidence.get("benchmark_v2_hybrid_start_intent")
            != start_intent
            or not isinstance(completed_evidence.get("evidence_integrity"), Mapping)
            or completed_evidence["evidence_integrity"].get("verified") is not True
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid bind_capture evidence is not recoverable"
            )
        current = start_learning_workflow_stage_operation(
            store=composition.store,
            project_root=composition.project_root,
            run_id=run_id,
            expected_revision=int(current["revision"]),
            stage=stage,
            operation_id=operation_id,
            learning_pipeline_mode="hybrid_v1_1",
            reason="benchmark_v2 hybrid workflow service start",
        )["workflow_state"]

    if current.get("current_stage") != stage:
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid run stage is stale"
        )
    execution = _benchmark_v2_stage_execution(current, stage)
    if (
        execution.get("operation_id") != operation_id
        or execution.get("learning_pipeline_mode") != "hybrid_v1_1"
    ):
        raise LearningWorkflowStageOperationError(
            "benchmark_v2 hybrid run operation is stale"
        )
    return current


def _start_benchmark_v2_hybrid_workflow_service(
    *,
    composition: LearningWorkflowServiceComposition,
    screen_group: Mapping[str, object],
    window_binding: Mapping[str, object],
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    run_id = str(window_binding["run_id"])
    stage = str(window_binding["stage"])
    operation_id = str(window_binding["operation_id"])
    with get_learning_workflow_operation_lock(
        store=composition.store,
        run_id=run_id,
        operation_id=operation_id,
    ):
        current = _ensure_benchmark_v2_hybrid_workflow_run(
            composition=composition,
            screen_group=screen_group,
            window_binding=window_binding,
        )
        stage_execution = _benchmark_v2_stage_execution(current, stage)
        proposed_binding = _compose_benchmark_v2_hybrid_service_binding(
            screen_group=screen_group,
            window_binding=window_binding,
        )
        binding = _benchmark_v2_hybrid_service_binding_from_execution(
            stage_execution
        )
        if binding is None:
            require_active_learning_workflow_stage_operation(
                store=composition.store,
                run_id=run_id,
                expected_revision=int(current["revision"]),
                stage=stage,
                operation_id=operation_id,
            )
            current = _persist_benchmark_v2_hybrid_service_binding(
                composition=composition,
                workflow_state=current,
                stage=stage,
                binding=proposed_binding,
            )
            stage_execution = _benchmark_v2_stage_execution(current, stage)
            binding = _benchmark_v2_hybrid_service_binding_from_execution(
                stage_execution
            )
        elif (
            _benchmark_v2_hybrid_binding_identity_sha256(binding)
            != _benchmark_v2_hybrid_binding_identity_sha256(proposed_binding)
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid service start binding is stale"
            )
        assert binding is not None
        lineage_workflow_revision = (
            _benchmark_v2_hybrid_lineage_workflow_revision(binding)
        )
        attachment = _LearningWorkflowRegistryOwner(
            composition.worker_registry
        ).project_worker_attachment(
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        )
        if not isinstance(attachment, Mapping):
            initial = build_learning_pipeline_initial_worker_request(
                learning_pipeline_mode="hybrid_v1_1",
                payload={
                    "run_id": run_id,
                    "workflow_revision": lineage_workflow_revision,
                    "hybrid_capture_bundle_ref": deepcopy(
                        screen_group["hybrid_capture_bundle_ref"]
                    ),
                    "request_ref": deepcopy(screen_group["request_ref"]),
                    "registration_ref": deepcopy(screen_group["registration_ref"]),
                    "manifest_ref": deepcopy(screen_group["manifest_ref"]),
                    "capture_image_path": str(screen_group["capture_image_path"]),
                    "hybrid_config": deepcopy(screen_group["hybrid_config"]),
                    "capture_bundle": deepcopy(screen_group["capture_bundle"]),
                },
            )
            provider = _BENCHMARK_V2_PROVIDER_TASKS.get(str(initial["task_kind"]))
            initial_context = None
            if provider is not None:
                context_ref = binding["provider_dispatch_context_refs"].get(provider)
                if isinstance(context_ref, Mapping):
                    initial_context = deepcopy(context_ref["dispatch_context"])
                else:
                    initial_context = _benchmark_v2_dispatch_context_for_worker(
                        composition=composition,
                        window_binding=binding["window_binding"],
                        task_kind=str(initial["task_kind"]),
                        revision=int(current["revision"]),
                    )
                    if isinstance(initial_context, Mapping):
                        binding = _benchmark_v2_hybrid_binding_with_dispatch_context(
                            binding=binding,
                            context=initial_context,
                        )
                        current = _persist_benchmark_v2_hybrid_service_binding(
                            composition=composition,
                            workflow_state=current,
                            stage=stage,
                            binding=binding,
                        )
                        stage_execution = _benchmark_v2_stage_execution(current, stage)
                        binding = _benchmark_v2_hybrid_service_binding_from_execution(
                            stage_execution
                        )
                        if binding is None:
                            raise LearningWorkflowStageOperationError(
                                "benchmark_v2 initial dispatch context was not persisted"
                            )
            initial_payload = _inject_benchmark_v2_dispatch_context(
                payload=initial["payload"],
                context=initial_context,
            )
            start_guarded_learning_stage_worker(
                composition=composition,
                run_id=run_id,
                expected_revision=int(current["revision"]),
                stage=stage,
                operation_id=operation_id,
                task_kind=str(initial["task_kind"]),
                payload=initial_payload,
                reuse_active_identical=True,
            )
        worker_record = _benchmark_v2_hybrid_attachment(
            composition=composition,
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        )
        status = _benchmark_v2_hybrid_service_status(
            workflow_state=current,
            stage=stage,
            worker_record=worker_record,
        )
        return _project_benchmark_v2_hybrid_step(
            composition=composition,
            workflow_state=current,
            stage_execution=stage_execution,
            binding=binding,
            worker_record=worker_record,
            status=status,
        )


def _continue_benchmark_v2_hybrid_workflow_service(
    *,
    composition: LearningWorkflowServiceComposition,
    operation_ref: Mapping[str, object],
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    run_id = str(operation_ref.get("run_id") or "")
    operation_id = str(operation_ref.get("operation_id") or "")
    with get_learning_workflow_operation_lock(
        store=composition.store,
        run_id=run_id,
        operation_id=operation_id,
    ):
        prepared = _benchmark_v2_hybrid_terminal_prepared_context(
            composition=composition,
            operation_ref=operation_ref,
        )
        if prepared is None:
            replay = _replay_benchmark_v2_hybrid_consumed_operation_ref(
                composition=composition,
                operation_ref=operation_ref,
            )
            if replay is not None:
                return replay
            current, stage_execution, binding, worker_record, supplied = (
                _benchmark_v2_hybrid_service_context(
                    composition=composition,
                    operation_ref=operation_ref,
                )
            )
            stage = str(supplied["stage"])
            status = _benchmark_v2_hybrid_service_status(
                workflow_state=current,
                stage=stage,
                worker_record=worker_record,
            )
            if status in {"complete", "safe_stopped"}:
                return _project_benchmark_v2_hybrid_step(
                    composition=composition,
                    workflow_state=current,
                    stage_execution=stage_execution,
                    binding=binding,
                    worker_record=worker_record,
                    status=status,
                )
            worker_status = status_guarded_learning_stage_worker(
                composition=composition,
                worker_id=worker_record["worker_id"],
                run_id=run_id,
                operation_id=operation_id,
            )
            worker_record = _benchmark_v2_hybrid_attachment(
                composition=composition,
                run_id=run_id,
                stage=stage,
                operation_id=operation_id,
            )
            status = _benchmark_v2_hybrid_service_status(
                workflow_state=current,
                stage=stage,
                worker_record=worker_record,
            )
            if supplied["status"] == "advanced" and status != "advanced":
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 hybrid advanced status is stale"
                )
            if status == "pending":
                return _project_benchmark_v2_hybrid_step(
                    composition=composition,
                    workflow_state=current,
                    stage_execution=stage_execution,
                    binding=binding,
                    worker_record=worker_record,
                    status=status,
                )
            if str(worker_status.get("status") or "") != "completed":
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 hybrid worker is not complete"
                )
            validated_before_adoption: dict[str, dict[str, Any]] = {}
            result_validator: Callable[[Mapping[str, object]], None] | None = None
            if not (
                composition.composition_kind == "test"
                and composition.benchmark_v2_worker_binding_resolver is None
            ):
                def _validate_before_adoption(
                    candidate: Mapping[str, object],
                ) -> None:
                    validated_before_adoption["response"] = (
                        _validate_benchmark_v2_hybrid_adoption(
                            composition=composition,
                            response=candidate,
                            window_binding=binding["window_binding"],
                            task_kind=str(worker_record["task_kind"]),
                            provider_dispatch_context_refs=binding[
                                "provider_dispatch_context_refs"
                            ],
                        )
                    )

                result_validator = _validate_before_adoption
            generic_adoption = adopt_guarded_learning_stage_worker_result(
                composition=composition,
                worker_id=worker_record["worker_id"],
                run_id=run_id,
                expected_revision=int(current["revision"]),
                stage=stage,
                operation_id=operation_id,
                _result_validator=result_validator,
            )
            adopted_response = (
                generic_adoption.get("response")
                if isinstance(generic_adoption, Mapping)
                else None
            )
            if not isinstance(adopted_response, Mapping):
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 Hybrid adoption lost its response"
                )
            if result_validator is not None:
                validated_response = validated_before_adoption.get("response")
                if (
                    not isinstance(validated_response, dict)
                    or adopted_response != validated_response
                ):
                    raise LearningWorkflowStageOperationError(
                        "benchmark_v2 Hybrid adoption bypassed dispatch validation"
                    )
            else:
                validated_response = _validate_benchmark_v2_hybrid_adoption(
                    composition=composition,
                    response=adopted_response,
                    window_binding=binding["window_binding"],
                    task_kind=str(worker_record["task_kind"]),
                    provider_dispatch_context_refs=binding[
                        "provider_dispatch_context_refs"
                    ],
                )
            generic_adoption = deepcopy(dict(generic_adoption))
            generic_adoption["response"] = validated_response
            if worker_record["task_kind"] == (
                "panel_learning_hybrid_review_projection"
            ):
                current = _persist_benchmark_v2_hybrid_continuation_receipt(
                    composition=composition,
                    workflow_state=current,
                    stage=stage,
                    binding=binding,
                    consumed_operation_ref=supplied,
                    worker_record=worker_record,
                    returned_status=None,
                    receipt_phase="terminal_prepared",
                )
                stage_execution = _benchmark_v2_stage_execution(current, stage)
                binding = _benchmark_v2_hybrid_service_binding_from_execution(
                    stage_execution
                )
                if binding is None:
                    raise LearningWorkflowStageOperationError(
                        "benchmark_v2 hybrid terminal preparation lost its service binding"
                    )
        else:
            current, stage_execution, binding, worker_record, supplied = prepared
            stage = str(supplied["stage"])
            if worker_record["task_kind"] != (
                "panel_learning_hybrid_review_projection"
            ):
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 hybrid terminal preparation task is stale"
                )
        issued_dispatch_contexts: list[dict[str, Any]] = []
        continuation = continue_guarded_learning_stage_worker_result(
            composition=composition,
            run_id=run_id,
            expected_revision=int(current["revision"]),
            stage=stage,
            operation_id=operation_id,
            worker_id=worker_record["worker_id"],
            _benchmark_dispatch_context_sink=(
                lambda context: issued_dispatch_contexts.append(
                    deepcopy(dict(context))
                )
            ),
        )
        current = composition.store.get(run_id)
        stage_execution = _benchmark_v2_stage_execution(current, stage)
        binding = _benchmark_v2_hybrid_service_binding_from_execution(stage_execution)
        if binding is None:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid continuation lost its service binding"
            )
        for issued_context in issued_dispatch_contexts:
            binding = _benchmark_v2_hybrid_binding_with_dispatch_context(
                binding=binding,
                context=issued_context,
            )
        worker_record = _benchmark_v2_hybrid_attachment(
            composition=composition,
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        )
        status = _benchmark_v2_hybrid_service_status(
            workflow_state=current,
            stage=stage,
            worker_record=worker_record,
        )
        if status not in {"complete", "safe_stopped"}:
            current = _persist_benchmark_v2_hybrid_continuation_receipt(
                composition=composition,
                workflow_state=current,
                stage=stage,
                binding=binding,
                consumed_operation_ref=supplied,
                worker_record=worker_record,
                returned_status=status,
            )
            stage_execution = _benchmark_v2_stage_execution(current, stage)
            binding = _benchmark_v2_hybrid_service_binding_from_execution(
                stage_execution
            )
            if binding is None:
                raise LearningWorkflowStageOperationError(
                    "benchmark_v2 hybrid continuation receipt was not persisted"
                )
        if status in {"complete", "safe_stopped"} and (
            continuation.get("next_stage_operation") is not None
            or continuation.get("next_stage_worker") is not None
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid terminal continuation started a generic next stage"
            )
        return _project_benchmark_v2_hybrid_step(
            composition=composition,
            workflow_state=current,
            stage_execution=stage_execution,
            binding=binding,
            worker_record=worker_record,
            status=status,
        )


def _cancel_benchmark_v2_hybrid_workflow_service(
    *,
    composition: LearningWorkflowServiceComposition,
    operation_ref: Mapping[str, object],
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    run_id = str(operation_ref.get("run_id") or "")
    operation_id = str(operation_ref.get("operation_id") or "")
    with get_learning_workflow_operation_lock(
        store=composition.store,
        run_id=run_id,
        operation_id=operation_id,
    ):
        prepared = _benchmark_v2_hybrid_terminal_prepared_context(
            composition=composition,
            operation_ref=operation_ref,
        )
        if prepared is None:
            current, stage_execution, binding, worker_record, supplied = (
                _benchmark_v2_hybrid_service_context(
                    composition=composition,
                    operation_ref=operation_ref,
                )
            )
        else:
            current, stage_execution, binding, worker_record, supplied = prepared
        stage = str(supplied["stage"])
        status = _benchmark_v2_hybrid_service_status(
            workflow_state=current,
            stage=stage,
            worker_record=worker_record,
        )
        if status in {"complete", "safe_stopped"}:
            return _project_benchmark_v2_hybrid_step(
                composition=composition,
                workflow_state=current,
                stage_execution=stage_execution,
                binding=binding,
                worker_record=worker_record,
                status=status,
            )
        cancel_guarded_learning_workflow_stage_operation(
            composition=composition,
            run_id=run_id,
            expected_revision=int(current["revision"]),
            stage=stage,
            operation_id=operation_id,
            reason="benchmark workflow service hybrid cancellation requested",
        )
        current = composition.store.get(run_id)
        stage_execution = _benchmark_v2_stage_execution(current, stage)
        binding = _benchmark_v2_hybrid_service_binding_from_execution(stage_execution)
        if binding is None:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 hybrid cancellation lost its service binding"
            )
        worker_record = _benchmark_v2_hybrid_attachment(
            composition=composition,
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        )
        status = _benchmark_v2_hybrid_service_status(
            workflow_state=current,
            stage=stage,
            worker_record=worker_record,
        )
        return _project_benchmark_v2_hybrid_step(
            composition=composition,
            workflow_state=current,
            stage_execution=stage_execution,
            binding=binding,
            worker_record=worker_record,
            status=status,
        )


def status_guarded_learning_stage_worker(
    *,
    composition: LearningWorkflowServiceComposition,
    worker_id: str,
    run_id: str,
    operation_id: str,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    return _LearningWorkflowRegistryOwner(
        composition.worker_registry
    ).worker_status(
        worker_id=worker_id,
        run_id=run_id,
        operation_id=operation_id,
    )


def adopt_guarded_learning_stage_worker_result(
    *,
    composition: LearningWorkflowServiceComposition,
    worker_id: str,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    _result_validator: Callable[[Mapping[str, object]], None] | None = None,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    stage_execution = require_active_learning_workflow_stage_operation(
        store=composition.store,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        operation_id=operation_id,
    )
    if _has_benchmark_v2_incumbent_marker(stage_execution):
        return _call_benchmark_v2_operation(
            lambda: _recover_or_resume_benchmark_v2_incumbent_operation(
                composition=composition,
                run_id=run_id,
                expected_revision=expected_revision,
                stage=stage,
                operation_id=operation_id,
                worker_id=worker_id,
            )
        )
    return _LearningWorkflowRegistryOwner(
        composition.worker_registry
    ).adopt_worker_result(
        worker_id=worker_id,
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
        **(
            {"result_validator": _result_validator}
            if _result_validator is not None
            else {}
        ),
    )


def continue_guarded_learning_stage_worker_result(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    worker_id: str,
    now: datetime | None = None,
    _benchmark_dispatch_context_sink: Callable[[Mapping[str, object]], None]
    | None = None,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    store_get = getattr(composition.store, "get", None)
    current = store_get(run_id) if callable(store_get) else None
    if isinstance(current, Mapping) and (
        _benchmark_v2_incumbent_operation_from_state(current, stage) is not None
    ):
        return _call_benchmark_v2_operation(
            lambda: _recover_or_resume_benchmark_v2_incumbent_operation(
                composition=composition,
                run_id=run_id,
                expected_revision=expected_revision,
                stage=stage,
                operation_id=operation_id,
                worker_id=worker_id,
            )
        )
    benchmark_hybrid_binding = (
        _benchmark_v2_hybrid_service_binding_from_execution(
            _benchmark_v2_stage_execution(current, stage)
        )
        if isinstance(current, Mapping)
        else None
    )
    if (
        benchmark_hybrid_binding is not None
        and composition.composition_kind == "production"
    ):
        _require_benchmark_v2_hybrid_capture_bundle(
            project_root=composition.project_root,
            binding=benchmark_hybrid_binding,
        )

    def _dispatch_context_factory(task_kind: str) -> Mapping[str, object] | None:
        assert isinstance(current, Mapping)
        binding = benchmark_hybrid_binding
        if binding is None:
            return None
        context = _benchmark_v2_dispatch_context_for_worker(
            composition=composition,
            window_binding=binding["window_binding"],
            task_kind=task_kind,
            revision=int(current["revision"]),
        )
        if (
            isinstance(context, Mapping)
            and _benchmark_dispatch_context_sink is not None
        ):
            _benchmark_dispatch_context_sink(deepcopy(dict(context)))
        return context

    return continue_learning_stage_worker_result(
        store=composition.store,
        worker_registry=composition.worker_registry,
        project_root=composition.project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        operation_id=operation_id,
        worker_id=worker_id,
        now=now,
        _preloaded_current=current if isinstance(current, Mapping) else None,
        _benchmark_dispatch_context_factory=(
            _dispatch_context_factory
            if isinstance(current, Mapping) and benchmark_hybrid_binding is not None
            else None
        ),
    )


def cancel_guarded_learning_workflow_stage_operation(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    reason: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    stage_execution = require_active_learning_workflow_stage_operation(
        store=composition.store,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        operation_id=operation_id,
        now=now,
        expiry_action="cancellation",
    )
    if _has_benchmark_v2_incumbent_marker(stage_execution):
        return _call_benchmark_v2_operation(
            lambda: _cancel_benchmark_v2_incumbent_operation(
                composition=composition,
                run_id=run_id,
                expected_revision=expected_revision,
                stage=stage,
                operation_id=operation_id,
                reason=reason,
            )
        )
    worker_termination = _LearningWorkflowRegistryOwner(
        composition.worker_registry
    ).cancel_worker(
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
    )
    result = cancel_learning_workflow_stage_operation(
        store=composition.store,
        project_root=composition.project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        operation_id=operation_id,
        reason=reason,
        now=now,
        backend_compute_termination=str(
            worker_termination.get("backend_compute_termination")
            or "not_covered"
        ),
        model_service_compute_termination=str(
            worker_termination.get("model_service_compute_termination")
            or "not_covered"
        ),
        worker_id=str(worker_termination.get("worker_id") or "") or None,
        model_request_id=(
            str(worker_termination.get("model_request_id") or "") or None
        ),
        model_request_cancellation=worker_termination.get(
            "model_request_cancellation"
        ),
        _prechecked_stage_execution=stage_execution,
    )
    return {**result, "worker_termination": deepcopy(worker_termination)}


def heartbeat_guarded_learning_workflow_stage_operation(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    lease_seconds: int = 600,
    now: datetime | None = None,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    store_get = getattr(composition.store, "get", None)
    current = store_get(run_id) if callable(store_get) else None
    if isinstance(current, Mapping):
        operation = _benchmark_v2_incumbent_operation_from_state(current, stage)
        if operation is not None:
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent heartbeat is managed by durable replay"
            )
    return heartbeat_learning_workflow_stage_operation(
        store=composition.store,
        project_root=composition.project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        operation_id=operation_id,
        lease_seconds=lease_seconds,
        now=now,
        _preloaded_current=current if isinstance(current, Mapping) else None,
    )


def finish_guarded_learning_workflow_stage_operation(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    expected_revision: int,
    stage: str,
    operation_id: str,
    outcome: str,
    reason: str = "",
    evidence_refs: Mapping[str, object] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    store_get = getattr(composition.store, "get", None)
    current = store_get(run_id) if callable(store_get) else None
    if isinstance(current, Mapping) and (
        _benchmark_v2_incumbent_operation_from_state(current, stage) is not None
    ):
        if outcome == "completed":
            return _call_benchmark_v2_operation(
                lambda: _recover_or_resume_benchmark_v2_incumbent_operation(
                    composition=composition,
                    run_id=run_id,
                    expected_revision=expected_revision,
                    stage=stage,
                    operation_id=operation_id,
                )
            )
        return _call_benchmark_v2_operation(
            lambda: _cancel_benchmark_v2_incumbent_operation(
                composition=composition,
                run_id=run_id,
                expected_revision=expected_revision,
                stage=stage,
                operation_id=operation_id,
                reason=reason or f"benchmark finish requested {outcome}",
            )
        )
    return finish_learning_workflow_stage_operation(
        store=composition.store,
        project_root=composition.project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        stage=stage,
        operation_id=operation_id,
        outcome=outcome,
        reason=reason,
        evidence_refs=(
            deepcopy(dict(evidence_refs))
            if isinstance(evidence_refs, Mapping)
            else None
        ),
        now=now,
        _preloaded_current=current if isinstance(current, Mapping) else None,
    )


def recover_guarded_learning_workflow_stage_operation(
    *,
    composition: LearningWorkflowServiceComposition,
    run_id: str,
    expected_revision: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    store_get = getattr(composition.store, "get", None)
    current = store_get(run_id) if callable(store_get) else None
    stage = str(current.get("current_stage") or "") if isinstance(current, Mapping) else ""
    operation = (
        _benchmark_v2_incumbent_operation_from_state(current, stage)
        if isinstance(current, Mapping)
        else None
    )
    if operation is not None:
        return _call_benchmark_v2_operation(
            lambda: _recover_or_resume_benchmark_v2_incumbent_operation(
                composition=composition,
                run_id=run_id,
                expected_revision=expected_revision,
                stage=stage,
                operation_id=operation["operation_id"],
                worker_id=operation["worker_ref"]["worker_id"],
            )
        )
    return recover_expired_learning_workflow_stage_operation(
        store=composition.store,
        project_root=composition.project_root,
        run_id=run_id,
        expected_revision=expected_revision,
        now=now,
        _preloaded_current=current if isinstance(current, Mapping) else None,
    )


def project_guarded_learning_workflow_runtime_attachment(
    *,
    composition: LearningWorkflowServiceComposition,
    workflow_state: Mapping[str, object],
) -> dict[str, Any]:
    _require_minted_learning_workflow_service_composition(composition)
    return project_learning_workflow_runtime_attachment(
        workflow_state=deepcopy(dict(workflow_state)),
        worker_registry=composition.worker_registry,
    )


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
    _preloaded_current: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """仅接收当前未过期租约持有者提交的阶段结果。"""

    if outcome not in {"completed", "failed", "safe_stopped"}:
        raise LearningWorkflowStageOperationError(
            "stage operation outcome must complete, fail, or safe stop"
        )
    current = (
        _preloaded_current
        if isinstance(_preloaded_current, Mapping)
        else store.get(run_id)
    )
    _require_revision(current, expected_revision)
    stage_execution = _managed_stage_execution(current, stage)
    _reject_benchmark_v2_incumbent_before_c3(stage_execution)
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
    _preloaded_current: Mapping[str, object] | None = None,
    _benchmark_dispatch_context_factory: Callable[[str], Mapping[str, object] | None]
    | None = None,
) -> dict[str, Any]:
    """解释已接纳结果，并在成功终结后签发唯一下一阶段租约。"""

    registry_owner = _LearningWorkflowRegistryOwner(worker_registry)
    adopted = registry_owner.read_worker_result(
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
    current = (
        _preloaded_current
        if isinstance(_preloaded_current, Mapping)
        else store.get(run_id)
    )
    _reject_benchmark_v2_incumbent_before_c3(
        _stage_execution_document(current, stage)
    )
    learning_pipeline_mode = normalize_learning_pipeline_mode(
        _learning_pipeline_mode_for_stage(current, stage)
    )
    benchmark_hybrid_binding = None
    hybrid_lineage_workflow_revision = expected_revision
    if learning_pipeline_mode == "hybrid_v1_1":
        benchmark_hybrid_binding = (
            _benchmark_v2_hybrid_service_binding_from_execution(
                _benchmark_v2_stage_execution(current, stage)
            )
        )
        if benchmark_hybrid_binding is not None:
            hybrid_lineage_workflow_revision = (
                _benchmark_v2_hybrid_lineage_workflow_revision(
                    benchmark_hybrid_binding
                )
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
            workflow_revision=hybrid_lineage_workflow_revision,
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
            if benchmark_hybrid_binding is not None:
                _require_benchmark_v2_hybrid_payload_workflow_revision(
                    payload=next_payload,
                    binding=benchmark_hybrid_binding,
                )
            if _benchmark_dispatch_context_factory is not None:
                next_payload = _inject_benchmark_v2_dispatch_context(
                    payload=next_payload,
                    context=_benchmark_dispatch_context_factory(next_task_kind),
                )
            next_worker = registry_owner.start_worker(
                run_id=run_id,
                stage=stage,
                operation_id=operation_id,
                task_kind=next_task_kind,
                payload=deepcopy(next_payload),
                reuse_active_identical=True,
                **(
                    {
                        "authoritative_workflow_revision": (
                            hybrid_lineage_workflow_revision
                        )
                    }
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
        return _LearningWorkflowRegistryOwner(worker_registry).start_worker(
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
    _preloaded_current: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """将已过期的服务端托管阶段明确终止，避免刷新后永久 running。"""

    current = (
        _preloaded_current
        if isinstance(_preloaded_current, Mapping)
        else store.get(run_id)
    )
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
    _reject_benchmark_v2_incumbent_before_c3(stage_execution)
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
