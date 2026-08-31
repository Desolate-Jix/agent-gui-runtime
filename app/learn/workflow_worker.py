from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import time
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from threading import RLock, get_ident, local
from typing import Any, Callable, Iterator, Mapping
from uuid import uuid4

from app.core.model_server import (
    abort_qwen_model_request_acquisition,
    cancel_model_request,
    observe_qwen_model_request_acquisition,
    observe_qwen_model_request_cleanup,
    prepare_qwen_model_request_acquisition_owner,
)
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

BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS = 5000
_BENCHMARK_RESERVATION_VERSION = "benchmark_worker_identity_reservation_v1"
_BENCHMARK_ANCHOR_VERSION = "benchmark_worker_operation_anchor_v1"
_BENCHMARK_SUPERVISION_VERSION = "benchmark_worker_supervision_v1"
_BENCHMARK_EXPECTED_SUPERVISION_VERSION = "benchmark_worker_expected_supervision_v1"
_BENCHMARK_CONFIRMATION_VERSION = "benchmark_worker_anchor_confirmation_v1"
_BENCHMARK_SOURCE_VERSION = "benchmark_v2_incumbent_handler_payload_source_v1"
_BENCHMARK_PROVIDER_JOURNAL_VERSION = "benchmark_provider_registry_journal_v1"
_BENCHMARK_PROVIDER_CLEANUP_JOURNAL_VERSION = (
    "benchmark_provider_cleanup_registry_journal_v1"
)
_BENCHMARK_V2_REVIEW_NO_PROVIDER_ABSENCE_CONTRACT = (
    "benchmark_v2_hybrid_no_provider_live_absence_observation_v1"
)
_BENCHMARK_V2_REVIEW_NO_PROVIDER_CLEANUP_CONTRACT = (
    "benchmark_v2_hybrid_no_provider_cleanup_ref_v1"
)
_BENCHMARK_PRIVATE_MARKERS = frozenset({
    "_benchmark_worker_supervision",
    "_benchmark_worker_bootstrap",
    "_benchmark_worker_handler_payload_source",
})


@dataclass(frozen=True)
class BenchmarkWorkerSupervisionRoot:
    """绑定 benchmark worker 日志根、能力和只读 workflow store。"""

    authority_kind: str
    journal_root: Path
    root_capability: object
    read_only_store_authority: object
    store_identity_sha256: str


@dataclass(frozen=True)
class _BenchmarkStoreAuthority:
    getter: Callable[[str], dict[str, Any]]
    capability: object
    identity_sha256: str

    def get(self, run_id: str) -> dict[str, Any]:
        return self.getter(run_id)


_BENCHMARK_ROOTS: dict[int, BenchmarkWorkerSupervisionRoot] = {}
_BENCHMARK_TEST_ROOTS_BY_PATH: dict[str, BenchmarkWorkerSupervisionRoot] = {}
_BENCHMARK_TEST_STORE_CAPABILITIES: dict[int, BenchmarkWorkerSupervisionRoot] = {}
_BENCHMARK_CONTROLLER_LOCAL = local()
_BENCHMARK_INSPECTION_ABANDONED_POLICY = object()
_PRODUCTION_BENCHMARK_ROOT: BenchmarkWorkerSupervisionRoot | None = None
_PRODUCTION_BENCHMARK_ROOT_LOCK = RLock()


def _benchmark_root_digest(
    *, authority_kind: str, journal_root: Path, workflow_store: object,
    memory_store_token: str | None = None,
) -> str:
    state_path = getattr(workflow_store, "_state_path", None)
    if state_path is None:
        if (
            not isinstance(memory_store_token, str)
            or len(memory_store_token) != 64
            or any(character not in "0123456789abcdef" for character in memory_store_token)
        ):
            raise LearningStageWorkerError(
                "benchmark memory store token is invalid"
            )
        state_identity = f"memory:{memory_store_token}"
    else:
        state_identity = str(Path(state_path).resolve()).casefold()
    return content_sha256({
        "contract_version": "benchmark_worker_store_identity_v1",
        "authority_kind": authority_kind,
        "store_class": f"{type(workflow_store).__module__}.{type(workflow_store).__qualname__}",
        "canonical_state_path_or_memory_token": state_identity,
    })


def _benchmark_paths_overlap(left: Path, right: Path) -> bool:
    left_value = left.resolve()
    right_value = right.resolve()
    return (
        left_value == right_value
        or left_value.is_relative_to(right_value)
        or right_value.is_relative_to(left_value)
    )


def _benchmark_test_memory_store_token(root_path: Path) -> str:
    import secrets

    token_path = root_path / ".benchmark-test-memory-store-token.json"
    root_path.mkdir(parents=True, exist_ok=True)
    if not token_path.exists():
        token = seal_immutable({
            "contract_version": "benchmark_worker_test_memory_store_token_v1",
            "journal_root": str(root_path),
            "memory_store_token": secrets.token_hex(32),
        })
        try:
            _write_json_create_only(token_path, token)
        except LearningStageWorkerError:
            if not token_path.exists():
                raise
    persisted = _read_json_object(
        token_path,
        label="benchmark test memory store token",
    )
    if (
        set(persisted)
        != {
            "contract_version", "journal_root", "memory_store_token",
            "content_sha256",
        }
        or persisted.get("contract_version")
        != "benchmark_worker_test_memory_store_token_v1"
        or persisted.get("journal_root") != str(root_path)
        or content_sha256(persisted) != persisted.get("content_sha256")
        or not isinstance(persisted.get("memory_store_token"), str)
        or len(persisted["memory_store_token"]) != 64
        or any(
            character not in "0123456789abcdef"
            for character in persisted["memory_store_token"]
        )
    ):
        raise LearningStageWorkerError(
            "benchmark test memory store token is invalid"
        )
    return persisted["memory_store_token"]


def compose_test_benchmark_worker_supervision_root(
    *,
    journal_root: str | Path,
    test_capability: object,
    workflow_store: object,
    test_store_capability: object,
) -> BenchmarkWorkerSupervisionRoot:
    """测试专用根；两个显式能力避免意外借用 production store。"""

    if test_capability is None or test_store_capability is None:
        raise LearningStageWorkerError("benchmark supervision capability is required")
    root_path = Path(journal_root).resolve()
    from app.learn.workflow_store import learning_workflow_run_store

    production_journal_root = (
        _PROJECT_ROOT / "logs" / "workflow-workers"
    ).resolve()
    production_state_path = Path(
        getattr(learning_workflow_run_store, "_state_path", None)
        or (_PROJECT_ROOT / "runtime_state" / "learning-workflow-runs.json")
    ).resolve()
    candidate_state_path = getattr(workflow_store, "_state_path", None)
    if (
        workflow_store is learning_workflow_run_store
        or _benchmark_paths_overlap(root_path, production_journal_root)
        or _benchmark_paths_overlap(root_path, production_state_path)
        or (
            candidate_state_path is not None
            and (
                _benchmark_paths_overlap(
                    Path(candidate_state_path), production_state_path
                )
                or _benchmark_paths_overlap(
                    Path(candidate_state_path), production_journal_root
                )
            )
        )
    ):
        raise LearningStageWorkerError(
            "benchmark test root overlaps production authority"
        )
    root_key = str(root_path).casefold()
    if (
        id(test_capability) in _BENCHMARK_ROOTS
        or id(test_store_capability) in _BENCHMARK_TEST_STORE_CAPABILITIES
        or root_key in _BENCHMARK_TEST_ROOTS_BY_PATH
    ):
        raise LearningStageWorkerError(
            "benchmark cross-test capability or root reuse is invalid"
        )
    memory_token = (
        _benchmark_test_memory_store_token(root_path)
        if candidate_state_path is None
        else None
    )
    identity_sha256 = _benchmark_root_digest(
        authority_kind="test_only", journal_root=root_path,
        workflow_store=workflow_store,
        memory_store_token=memory_token,
    )
    authority = _BenchmarkStoreAuthority(
        lambda run_id: workflow_store.get(run_id),
        test_store_capability,
        identity_sha256,
    )
    root = BenchmarkWorkerSupervisionRoot(
        authority_kind="test_only",
        journal_root=root_path,
        root_capability=test_capability,
        read_only_store_authority=authority,
        store_identity_sha256=identity_sha256,
    )
    _BENCHMARK_ROOTS[id(test_capability)] = root
    _BENCHMARK_TEST_ROOTS_BY_PATH[root_key] = root
    _BENCHMARK_TEST_STORE_CAPABILITIES[id(test_store_capability)] = root
    return root


def get_production_benchmark_worker_supervision_root(
) -> BenchmarkWorkerSupervisionRoot:
    """延迟绑定 production singleton store 的只读 getter authority。"""

    global _PRODUCTION_BENCHMARK_ROOT
    if _PRODUCTION_BENCHMARK_ROOT is not None:
        return _PRODUCTION_BENCHMARK_ROOT
    with _PRODUCTION_BENCHMARK_ROOT_LOCK:
        if _PRODUCTION_BENCHMARK_ROOT is None:
            from app.learn.workflow_store import learning_workflow_run_store

            journal_root = (_PROJECT_ROOT / "logs" / "workflow-workers").resolve()
            capability = object()
            store_capability = object()
            identity_sha256 = _benchmark_root_digest(
                authority_kind="production_workflow_service",
                journal_root=journal_root,
                workflow_store=learning_workflow_run_store,
                memory_store_token=content_sha256({
                    "authority_kind": "production_workflow_service",
                    "journal_root": str(journal_root).casefold(),
                    "store_class": (
                        f"{type(learning_workflow_run_store).__module__}."
                        f"{type(learning_workflow_run_store).__qualname__}"
                    ),
                }),
            )
            authority = _BenchmarkStoreAuthority(
                lambda run_id: learning_workflow_run_store.get(run_id),
                store_capability,
                identity_sha256,
            )
            root = BenchmarkWorkerSupervisionRoot(
                authority_kind="production_workflow_service",
                journal_root=journal_root,
                root_capability=capability,
                read_only_store_authority=authority,
                store_identity_sha256=identity_sha256,
            )
            _BENCHMARK_ROOTS[id(capability)] = root
            _PRODUCTION_BENCHMARK_ROOT = root
    return _PRODUCTION_BENCHMARK_ROOT


def _validate_benchmark_supervision_root(
    root: object,
    *,
    expected_journal_root: Path | None = None,
) -> BenchmarkWorkerSupervisionRoot:
    if not isinstance(root, BenchmarkWorkerSupervisionRoot):
        raise LearningStageWorkerError("benchmark supervision root is required")
    registered = _BENCHMARK_ROOTS.get(id(root.root_capability))
    if registered is not root:
        raise LearningStageWorkerError("benchmark supervision root capability is invalid")
    if not isinstance(root.read_only_store_authority, _BenchmarkStoreAuthority):
        raise LearningStageWorkerError("benchmark store authority capability is invalid")
    if root.store_identity_sha256 != root.read_only_store_authority.identity_sha256:
        raise LearningStageWorkerError("benchmark store identity is invalid")
    if expected_journal_root is not None and root.journal_root != expected_journal_root:
        raise LearningStageWorkerError("benchmark supervision journal root does not match")
    return root


def _benchmark_supervision_inputs_ref(
    root: BenchmarkWorkerSupervisionRoot,
) -> dict[str, str]:
    validated = _validate_benchmark_supervision_root(root)
    return {
        "content_sha256": content_sha256(
            {
                "authority_kind": validated.authority_kind,
                "store_identity_sha256": validated.store_identity_sha256,
                "journal_root": str(validated.journal_root.resolve()),
            }
        )
    }


_WINDOWS_RESERVED_ARTIFACT_STEMS = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_BENCHMARK_OPERATION_ARTIFACT_KEY_PREFIX = "operation-key-v1-"
_BENCHMARK_OPERATION_STATE_SUFFIXES = (
    ".benchmark-reservation.json",
    ".benchmark-anchor-confirmation.json",
    ".benchmark-provider.json",
    ".benchmark-provider-cleanup.json",
    ".benchmark-store-decision.json",
    ".benchmark-pre-anchor-abort.json",
    ".benchmark-pre-anchor-abort-receipt.json",
    ".benchmark-controller-abandoned-revalidation.json",
)


def _benchmark_operation_artifact_path(
    root: Path,
    operation_id: str,
    suffix: str,
) -> Path:
    """将语义 operation id 投影为稳定且可跨 Windows 持久化的文件名。"""

    if not isinstance(operation_id, str) or not operation_id:
        raise LearningStageWorkerError("benchmark operation id is invalid")
    if not isinstance(suffix, str) or not suffix.startswith(".benchmark-"):
        raise LearningStageWorkerError("benchmark operation artifact suffix is invalid")
    safe_ascii = all(
        character.isascii()
        and (character.isalnum() or character in {"-", "_", "."})
        for character in operation_id
    )
    reserved_stem = operation_id.split(".", 1)[0].upper()
    if (
        safe_ascii
        and operation_id == operation_id.lower()
        and len(operation_id) <= 96
        and reserved_stem not in _WINDOWS_RESERVED_ARTIFACT_STEMS
        and not operation_id.casefold().startswith(
            _BENCHMARK_OPERATION_ARTIFACT_KEY_PREFIX
        )
    ):
        stem = operation_id
    else:
        digest = content_sha256(
            {
                "contract_version": "benchmark_worker_operation_artifact_key_v1",
                "operation_id": operation_id,
            }
        )
        stem = f"{_BENCHMARK_OPERATION_ARTIFACT_KEY_PREFIX}{digest}"
    return root / f"{stem}{suffix}"


def _validate_benchmark_reservation_supervision(
    reservation: Mapping[str, object],
    *,
    supervision_root: BenchmarkWorkerSupervisionRoot | None,
    expected_journal_root: Path,
) -> None:
    root = _validate_benchmark_supervision_root(
        supervision_root,
        expected_journal_root=expected_journal_root.resolve(),
    )
    if (
        reservation.get("authority_kind") != root.authority_kind
        or reservation.get("supervision_inputs_ref")
        != _benchmark_supervision_inputs_ref(root)
    ):
        raise LearningStageWorkerError(
            "benchmark reservation supervision identity does not match"
        )


def _benchmark_controller_abandoned_revalidate(
    *,
    root: BenchmarkWorkerSupervisionRoot,
    controller_name: str,
    run_id: str,
    stage: str,
    operation_id: str,
) -> dict[str, Any]:
    """abandoned admission 前只读重验 store、journal 与可重算 OS identity。"""

    store_state = "indeterminate"
    store_state_sha256 = None
    error_value = None
    try:
        current = root.read_only_store_authority.get(run_id)
    except BaseException as error:
        from app.learn.workflow_state import LearningWorkflowTransitionError

        if (
            isinstance(error, LearningWorkflowTransitionError)
            and str(error) == "workflow run not found"
        ):
            store_state = "absent"
        else:
            error_value = {
                "stage": "store",
                "error_type": type(error).__name__,
                "message": str(error),
            }
    else:
        if isinstance(current, dict):
            store_state = "present"
            store_state_sha256 = content_sha256(current)
        else:
            error_value = {
                "stage": "store",
                "error_type": "TypeError",
                "message": "benchmark controller store state is invalid",
            }

    reservation = None
    reservation_ref = None
    reservation_path = _benchmark_operation_artifact_path(
        root.journal_root,
        operation_id,
        ".benchmark-reservation.json",
    )
    if reservation_path.exists():
        try:
            candidate = _read_json_object(
                reservation_path,
                label="benchmark controller abandoned reservation",
            )
            if (
                content_sha256(candidate) != candidate.get("content_sha256")
                or candidate.get("run_id") != run_id
                or candidate.get("stage") != stage
                or candidate.get("operation_id") != operation_id
            ):
                raise LearningStageWorkerError(
                    "benchmark controller abandoned reservation is invalid"
                )
            reservation = candidate
            reservation_ref = {"content_sha256": candidate["content_sha256"]}
        except BaseException as error:
            if error_value is None:
                error_value = {
                    "stage": "reservation",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }

    owners: list[dict[str, Any]] = []
    for owner_path in root.journal_root.glob("*.benchmark-owner.json"):
        try:
            candidate = _read_json_object(
                owner_path,
                label="benchmark controller abandoned owner",
            )
        except BaseException as error:
            if error_value is None:
                error_value = {
                    "stage": "owner",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
            continue
        if (
            candidate.get("run_id") == run_id
            and candidate.get("stage") == stage
            and candidate.get("operation_id") == operation_id
        ):
            if content_sha256(candidate) != candidate.get("content_sha256"):
                error_value = {
                    "stage": "owner",
                    "error_type": "LearningStageWorkerError",
                    "message": "benchmark controller abandoned owner is invalid",
                }
            owners.append(candidate)
    owner = owners[0] if len(owners) == 1 else None
    if len(owners) > 1 and error_value is None:
        error_value = {
            "stage": "owner",
            "error_type": "LearningStageWorkerError",
            "message": "benchmark controller abandoned owner is ambiguous",
        }
    owner_ref = (
        {"content_sha256": owner["content_sha256"]}
        if owner is not None
        else None
    )
    job_probe = None
    process_probe = None
    if reservation is not None:
        from app.learn.hybrid.windows_process_scope import (
            benchmark_worker_scope_name_v1,
        )

        try:
            scope_name = benchmark_worker_scope_name_v1(
                authority_kind=reservation["authority_kind"],
                run_id=run_id,
                stage=stage,
                operation_id=operation_id,
                worker_id=reservation["worker_id"],
                payload_sha256=reservation["payload_sha256"],
                execution_nonce=reservation["execution_nonce"],
            )
            job_probe = _benchmark_cleanup_replay_job_probe(scope_name)
            process_identity = (
                owner.get("process_identity") if owner is not None else None
            )
            if process_identity is not None:
                process_probe = _benchmark_cleanup_replay_process_probe(
                    process_identity
                )
        except BaseException as error:
            if error_value is None:
                error_value = {
                    "stage": "os",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
    clean = (
        error_value is None
        and store_state == "absent"
        and reservation is None
        and owner is None
    )
    observation = seal_immutable({
        "contract_version": (
            "benchmark_worker_controller_abandoned_revalidation_v1"
        ),
        "authority_kind": root.authority_kind,
        "controller_name": controller_name,
        "run_id": run_id,
        "stage": stage,
        "operation_id": operation_id,
        "store_state": store_state,
        "store_state_content_sha256": store_state_sha256,
        "reservation_ref": reservation_ref,
        "owner_ref": owner_ref,
        "job_probe": deepcopy(job_probe),
        "process_probe": deepcopy(process_probe),
        "error": error_value,
        "outcome": "verified_clean" if clean else "recovery_required",
        "artifact_is_authorization": False,
    })
    _write_json_atomic(
        _benchmark_operation_artifact_path(
            root.journal_root,
            operation_id,
            ".benchmark-controller-abandoned-revalidation.json",
        ),
        observation,
    )
    return observation


def _benchmark_controller_state_path(
    root: BenchmarkWorkerSupervisionRoot,
    controller_name: str,
) -> Path:
    return root.journal_root / (
        f"{content_sha256({'controller_name': controller_name})}"
        ".benchmark-controller-state.json"
    )


def _persist_benchmark_controller_state(
    *,
    root: BenchmarkWorkerSupervisionRoot,
    controller_name: str,
    state: str,
    release_result: dict[str, Any],
    close_result: dict[str, Any],
    predecessor_content_sha256: str | None,
) -> dict[str, Any]:
    value = seal_immutable({
        "contract_version": "benchmark_worker_controller_state_v1",
        "authority_kind": root.authority_kind,
        "controller_name": controller_name,
        "state": state,
        "thread_id": get_ident(),
        "release_result": deepcopy(release_result),
        "close_result": deepcopy(close_result),
        "predecessor_content_sha256": predecessor_content_sha256,
    })
    _write_json_atomic(
        _benchmark_controller_state_path(root, controller_name),
        value,
    )
    return value


def _load_benchmark_controller_state(
    root: BenchmarkWorkerSupervisionRoot,
    controller_name: str,
) -> dict[str, Any] | None:
    path = _benchmark_controller_state_path(root, controller_name)
    if not path.exists():
        return None
    value = _read_json_object(path, label="benchmark controller state")
    if (
        value.get("contract_version") != "benchmark_worker_controller_state_v1"
        or value.get("authority_kind") != root.authority_kind
        or value.get("controller_name") != controller_name
        or value.get("state") not in {"recovery_required", "clean"}
        or content_sha256(value) != value.get("content_sha256")
    ):
        raise LearningStageWorkerError("benchmark controller state is invalid")
    return value


def _benchmark_checked_release_mutex(handle: object) -> None:
    import win32event

    result = win32event.ReleaseMutex(handle)
    if result is False:
        raise LearningStageWorkerError(
            "benchmark worker controller ReleaseMutex returned false"
        )


def _benchmark_checked_close_handle(handle: object) -> None:
    import win32api

    result = win32api.CloseHandle(handle)
    if result is False:
        raise LearningStageWorkerError(
            "benchmark worker controller CloseHandle returned false"
        )


def _benchmark_controller_error_code(error: BaseException) -> int | None:
    code = getattr(error, "winerror", None)
    if code is None and getattr(error, "args", None):
        first = error.args[0]
        code = first if isinstance(first, int) else None
    return code


def _recover_benchmark_controller_local_entry(
    *,
    root: BenchmarkWorkerSupervisionRoot,
    controller_name: str,
    entry: dict[str, Any],
    held: dict[str, dict[str, Any]],
) -> None:
    """同一thread仅清理保留的uncertain ownership；本次绝不进入business body。"""

    import win32event

    predecessor = entry.get("state_ref")
    if entry["state"] == "release_uncertain":
        outcome = win32event.WaitForSingleObject(entry["handle"], 0)
        if outcome not in {win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED}:
            raise LearningStageWorkerError(
                "benchmark worker controller recovery wait failed"
            )
        successful_releases = 0
        for _ in range(int(entry["depth"]) + 1):
            try:
                _benchmark_checked_release_mutex(entry["handle"])
                successful_releases += 1
            except BaseException as error:
                if (
                    successful_releases > 0
                    and _benchmark_controller_error_code(error) == 288
                ):
                    break
                raise LearningStageWorkerError(
                    "benchmark worker controller recovery release failed"
                ) from error
        if successful_releases == 0:
            raise LearningStageWorkerError(
                "benchmark worker controller recovery release failed"
            )
        entry["depth"] = 0
    try:
        _benchmark_checked_close_handle(entry["handle"])
    except BaseException as error:
        if _benchmark_controller_error_code(error) != 6:
            raise LearningStageWorkerError(
                "benchmark worker controller recovery close failed"
            ) from error
    clean = _persist_benchmark_controller_state(
        root=root,
        controller_name=controller_name,
        state="clean",
        release_result={"status": "reconciled"},
        close_result={"status": "closed_or_already_closed"},
        predecessor_content_sha256=predecessor,
    )
    entry["state_ref"] = clean["content_sha256"]
    held.pop(controller_name, None)


def _join_benchmark_failed_launch_process(process: object | None) -> dict[str, Any]:
    if process is None:
        return {"not_applicable": True}
    process.join(5)
    alive_after = bool(process.is_alive())
    result = {
        "join_timeout_seconds": 5,
        "alive_after": alive_after,
        "exitcode": getattr(process, "exitcode", None),
    }
    if alive_after:
        raise LearningStageWorkerError(
            "benchmark failed launch process remained alive after join"
        )
    return result


def _unlink_benchmark_failed_launch_beacon(path: Path) -> dict[str, Any]:
    existed_before = path.exists()
    path.unlink(missing_ok=True)
    return {
        "existed_before": existed_before,
        "absent_after": not path.exists(),
    }


def _benchmark_failed_launch_process_terminate(process: object) -> object:
    return process.terminate()


def _benchmark_failed_launch_process_close(process: object) -> object:
    return process.close()


def _benchmark_failed_launch_event_close(handle: object) -> object:
    import win32api

    return win32api.CloseHandle(handle)


def _benchmark_failed_launch_job_terminate(scope: object) -> object:
    return scope.terminate()


def _benchmark_failed_launch_job_close(scope: object) -> object:
    return scope.close()


def _benchmark_failed_launch_job_stable_zero(scope: object | None) -> dict[str, Any]:
    if scope is None:
        return {"not_applicable": True, "samples": [[], [], []]}
    samples: list[list[int]] = []
    for _ in range(3):
        samples.append(scope.pids())
        if samples[-1]:
            time.sleep(0.02)
    if samples != [[], [], []]:
        raise LearningStageWorkerError(
            "benchmark failed launch Job did not reach stable zero"
        )
    return {"samples": samples}


def _benchmark_failed_launch_close_already_proven(
    resource: str,
    error: BaseException,
) -> bool:
    if resource == "process_close":
        return isinstance(error, ValueError) and "closed" in str(error).casefold()
    return _benchmark_controller_error_code(error) == 6


@contextmanager
def hold_benchmark_worker_controller(
    *,
    supervision_root: BenchmarkWorkerSupervisionRoot,
    run_id: str,
    stage: str,
    operation_id: str,
    timeout_ms: int = BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS,
    _abandoned_policy: object | None = None,
) -> Iterator[object]:
    """持有 operation 级命名 Mutex；同线程递归共享一个 guard。"""

    root = _validate_benchmark_supervision_root(supervision_root)
    if (
        _abandoned_policy is not None
        and _abandoned_policy is not _BENCHMARK_INSPECTION_ABANDONED_POLICY
    ):
        raise LearningStageWorkerError(
            "benchmark controller abandoned policy is invalid"
        )
    inspection_fail_closed = (
        _abandoned_policy is _BENCHMARK_INSPECTION_ABANDONED_POLICY
    )
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 0 < timeout_ms <= 0xFFFFFFFE:
        raise LearningStageWorkerError("benchmark controller timeout is invalid")
    from app.learn.hybrid.windows_process_scope import (
        benchmark_worker_controller_mutex_name_v1,
    )
    import win32api
    import win32event

    run_value = _required_text(run_id, "run_id")
    stage_value = _required_text(stage, "stage")
    operation_value = _required_text(operation_id, "operation_id")
    name = benchmark_worker_controller_mutex_name_v1(
        authority_kind=root.authority_kind,
        run_id=run_value,
        stage=stage_value,
        operation_id=operation_value,
    )
    held = getattr(_BENCHMARK_CONTROLLER_LOCAL, "held", None)
    if held is None:
        held = {}
        _BENCHMARK_CONTROLLER_LOCAL.held = held
    existing = held.get(name)
    if existing is not None:
        if existing["root"] is not root:
            raise LearningStageWorkerError(
                "benchmark worker controller guard root does not match"
            )
        if existing.get("state") != "active":
            _recover_benchmark_controller_local_entry(
                root=root,
                controller_name=name,
                entry=existing,
                held=held,
            )
            raise LearningStageWorkerError(
                "benchmark worker controller recovery required"
            )
        outcome = win32event.WaitForSingleObject(existing["handle"], timeout_ms)
        if outcome not in {win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED}:
            if outcome == win32event.WAIT_TIMEOUT:
                raise LearningStageWorkerError("benchmark worker controller mutex timed out")
            raise LearningStageWorkerError("benchmark worker controller mutex wait failed")
        if outcome == win32event.WAIT_ABANDONED:
            if inspection_fail_closed:
                try:
                    _benchmark_checked_release_mutex(existing["handle"])
                except BaseException as release_error:
                    state = _persist_benchmark_controller_state(
                        root=root,
                        controller_name=name,
                        state="recovery_required",
                        release_result={
                            "status": "error",
                            "error_type": type(release_error).__name__,
                            "message": str(release_error),
                        },
                        close_result={"status": "retained"},
                        predecessor_content_sha256=existing.get("state_ref"),
                    )
                    existing["state"] = "release_uncertain"
                    existing["state_ref"] = state["content_sha256"]
                    raise LearningStageWorkerError(
                        "benchmark worker controller cleanup failed"
                    ) from release_error
                raise LearningStageWorkerError(
                    "benchmark worker controller abandoned during read-only inspection"
                )
            revalidation = _benchmark_controller_abandoned_revalidate(
                root=root,
                controller_name=name,
                run_id=run_value,
                stage=stage_value,
                operation_id=operation_value,
            )
            if revalidation["outcome"] != "verified_clean":
                _persist_benchmark_controller_state(
                    root=root,
                    controller_name=name,
                    state="recovery_required",
                    release_result={"status": "owned_pending_release"},
                    close_result={"status": "open_pending_release"},
                    predecessor_content_sha256=revalidation[
                        "content_sha256"
                    ],
                )
                raise LearningStageWorkerError(
                    "benchmark worker controller recovery required"
                )
        existing["depth"] += 1
        primary: BaseException | None = None
        release_error: BaseException | None = None
        try:
            yield existing["guard"]
        except BaseException as error:
            primary = error
        try:
            _benchmark_checked_release_mutex(existing["handle"])
        except BaseException as error:
            release_error = error
        if release_error is None:
            existing["depth"] -= 1
        if release_error is not None:
            state = _persist_benchmark_controller_state(
                root=root,
                controller_name=name,
                state="recovery_required",
                release_result={
                    "status": "error",
                    "error_type": type(release_error).__name__,
                    "message": str(release_error),
                },
                close_result={"status": "retained"},
                predecessor_content_sha256=existing.get("state_ref"),
            )
            existing["state"] = "release_uncertain"
            existing["state_ref"] = state["content_sha256"]
            _record_benchmark_controller_cleanup_failure(
                root=root, name=name, recursion_level=existing["depth"],
                primary=primary,
                release={"status": "error", "error_type": type(release_error).__name__, "message": str(release_error)},
                close={"status": "retained"},
            )
        if primary is not None:
            if release_error is not None:
                raise LearningStageWorkerError(str(primary)) from primary
            raise primary
        if release_error is not None:
            raise LearningStageWorkerError(
                "benchmark worker controller cleanup failed"
            ) from release_error
        return

    durable_state = _load_benchmark_controller_state(root, name)
    if durable_state is not None and durable_state["state"] == "recovery_required":
        raise LearningStageWorkerError(
            "benchmark worker controller recovery required"
        )
    handle = win32event.CreateMutex(None, False, name)
    admitted = False
    business_admitted = False
    primary: BaseException | None = None
    try:
        outcome = win32event.WaitForSingleObject(handle, timeout_ms)
        if outcome == win32event.WAIT_TIMEOUT:
            timeout_error = LearningStageWorkerError(
                "benchmark worker controller mutex timed out"
            )
            try:
                win32api.CloseHandle(handle)
                handle = None
            except BaseException as close_error:
                _record_benchmark_controller_cleanup_failure(
                    root=root, name=name, recursion_level=0,
                    primary=timeout_error,
                    release={"status": "not_owned"},
                    close={"status": "error", "error_type": type(close_error).__name__, "message": str(close_error)},
                )
            raise timeout_error
        if outcome not in {win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED}:
            raise LearningStageWorkerError("benchmark worker controller mutex wait failed")
        admitted = True
        revalidation = None
        if outcome == win32event.WAIT_ABANDONED:
            if inspection_fail_closed:
                _persist_benchmark_controller_state(
                    root=root,
                    controller_name=name,
                    state="recovery_required",
                    release_result={"status": "owned_pending_release"},
                    close_result={"status": "open_pending_release"},
                    predecessor_content_sha256=(
                        durable_state["content_sha256"]
                        if durable_state is not None
                        else None
                    ),
                )
                raise LearningStageWorkerError(
                    "benchmark worker controller abandoned during read-only inspection"
                )
            revalidation = _benchmark_controller_abandoned_revalidate(
                root=root,
                controller_name=name,
                run_id=run_value,
                stage=stage_value,
                operation_id=operation_value,
            )
            if revalidation["outcome"] != "verified_clean":
                _persist_benchmark_controller_state(
                    root=root,
                    controller_name=name,
                    state="recovery_required",
                    release_result={"status": "owned_pending_release"},
                    close_result={"status": "open_pending_release"},
                    predecessor_content_sha256=revalidation[
                        "content_sha256"
                    ],
                )
                raise LearningStageWorkerError(
                    "benchmark worker controller recovery required"
                )
        fresh_state = _load_benchmark_controller_state(root, name)
        if (
            fresh_state is not None
            and fresh_state["state"] == "recovery_required"
        ):
            raise LearningStageWorkerError(
                "benchmark worker controller recovery required"
            )
        guard = seal_immutable({
            "contract_version": "benchmark_worker_controller_guard_v1",
            "controller_name": name,
            "thread_id": get_ident(),
            "acquire_outcome": (
                "abandoned_revalidated_clean"
                if outcome == win32event.WAIT_ABANDONED
                else "acquired"
            ),
            "abandoned_revalidation_ref": (
                {"content_sha256": revalidation["content_sha256"]}
                if revalidation is not None
                else None
            ),
        })
        held[name] = {
            "guard": guard,
            "handle": handle,
            "depth": 1,
            "root": root,
            "state": "active",
            "state_ref": (
                durable_state["content_sha256"]
                if durable_state is not None
                else None
            ),
        }
        business_admitted = True
        try:
            yield guard
        except BaseException as error:
            primary = error
    finally:
        release_error: BaseException | None = None
        close_error: BaseException | None = None
        release_result: dict[str, Any] = {"status": "not_owned"}
        close_result: dict[str, Any] = {"status": "not_open"}
        entry = held.get(name)
        release_fence = None
        if (
            business_admitted
            and admitted
            and handle is not None
            and entry is not None
            and entry.get("state") == "active"
        ):
            release_fence = _persist_benchmark_controller_state(
                root=root,
                controller_name=name,
                state="recovery_required",
                release_result={"status": "pending"},
                close_result={"status": "pending"},
                predecessor_content_sha256=entry.get("state_ref"),
            )
            entry["state_ref"] = release_fence["content_sha256"]
        if (
            admitted
            and handle is not None
            and (entry is None or entry.get("state") == "active")
        ):
            try:
                _benchmark_checked_release_mutex(handle)
                release_result = {"status": "released"}
            except BaseException as error:
                release_error = error
                release_result = {"status": "error", "error_type": type(error).__name__, "message": str(error)}
                close_result = {"status": "retained"}
                predecessor = (
                    entry.get("state_ref")
                    if entry is not None
                    else (
                        _load_benchmark_controller_state(root, name) or {}
                    ).get("content_sha256")
                )
                state = _persist_benchmark_controller_state(
                    root=root,
                    controller_name=name,
                    state="recovery_required",
                    release_result=release_result,
                    close_result={"status": "retained"},
                    predecessor_content_sha256=predecessor,
                )
                if entry is None:
                    entry = {
                        "guard": None,
                        "handle": handle,
                        "depth": 1,
                        "root": root,
                    }
                    held[name] = entry
                entry["state"] = "release_uncertain"
                entry["state_ref"] = state["content_sha256"]
        if release_error is None and (
            not admitted
            or entry is None
            or entry.get("state") == "active"
        ):
            try:
                if handle is not None:
                    _benchmark_checked_close_handle(handle)
                    close_result = {"status": "closed"}
            except BaseException as error:
                close_error = error
                close_result = {"status": "error", "error_type": type(error).__name__, "message": str(error)}
                if entry is not None:
                    state = _persist_benchmark_controller_state(
                        root=root,
                        controller_name=name,
                        state="recovery_required",
                        release_result=release_result,
                        close_result=close_result,
                        predecessor_content_sha256=entry.get("state_ref"),
                    )
                    entry["state"] = "close_pending"
                    entry["depth"] = 0
                    entry["state_ref"] = state["content_sha256"]
                else:
                    predecessor = (
                        _load_benchmark_controller_state(root, name) or {}
                    ).get("content_sha256")
                    state = _persist_benchmark_controller_state(
                        root=root,
                        controller_name=name,
                        state="recovery_required",
                        release_result=release_result,
                        close_result=close_result,
                        predecessor_content_sha256=predecessor,
                    )
                    entry = {
                        "guard": None,
                        "handle": handle,
                        "depth": 0,
                        "root": root,
                        "state": "close_pending",
                        "state_ref": state["content_sha256"],
                    }
                    held[name] = entry
            else:
                if business_admitted and release_fence is not None:
                    _persist_benchmark_controller_state(
                        root=root,
                        controller_name=name,
                        state="clean",
                        release_result={"status": "released"},
                        close_result={"status": "closed"},
                        predecessor_content_sha256=release_fence[
                            "content_sha256"
                        ],
                    )
                held.pop(name, None)
        if release_error is not None or close_error is not None:
            _record_benchmark_controller_cleanup_failure(
                root=root, name=name, recursion_level=1, primary=primary,
                release=release_result, close=close_result,
            )
        if primary is not None:
            if release_error is not None or close_error is not None:
                raise LearningStageWorkerError(str(primary)) from primary
            raise primary
        if release_error is not None or close_error is not None:
            cause = release_error or close_error
            raise LearningStageWorkerError(
                "benchmark worker controller cleanup failed"
            ) from cause


def _record_benchmark_controller_cleanup_failure(
    *, root: BenchmarkWorkerSupervisionRoot, name: str, recursion_level: int,
    primary: BaseException | None, release: dict[str, Any], close: dict[str, Any],
) -> dict[str, Any]:
    artifacts = sorted(
        path.name for pattern in (
            "*.benchmark-reservation.json", "*.benchmark-owner.json",
            "*.benchmark-beacon.json", "*.benchmark-cleanup*.json",
            "*.benchmark-store-decision.json",
        ) for path in root.journal_root.glob(pattern)
    )
    snapshot = seal_immutable({
        "contract_version": "benchmark_worker_controller_mutation_snapshot_v1",
        "artifact_names": artifacts,
    })
    sidecar = seal_immutable({
        "contract_version": "benchmark_worker_controller_cleanup_failure_v1",
        "authority_kind": root.authority_kind,
        "controller_name": name, "thread_id": get_ident(),
        "recursion_level": recursion_level,
        "primary_exception": (
            {"error_type": type(primary).__name__, "message": str(primary)}
            if primary is not None else None
        ),
        "release_result": deepcopy(release), "close_result": deepcopy(close),
        "mutation_snapshot_ref": {"content_sha256": snapshot["content_sha256"]},
        "predecessor_content_sha256": None,
    })
    root.journal_root.mkdir(parents=True, exist_ok=True)
    path = root.journal_root / f"{sidecar['content_sha256']}.benchmark-controller-cleanup-failure.json"
    _write_json_atomic(path, sidecar)
    return sidecar


def _benchmark_source_ref(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "benchmark_v2_incumbent_handler_payload_source_ref_v1",
        "content_sha256": source["content_sha256"],
    }


def _benchmark_exact_ref(value: object, label: str) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"content_sha256"}
        or not isinstance(value.get("content_sha256"), str)
        or len(value["content_sha256"]) != 64
        or any(
            character not in "0123456789abcdef"
            for character in value["content_sha256"]
        )
    ):
        raise LearningStageWorkerError(f"{label} must be an exact content ref")
    return deepcopy(value)


def _validate_benchmark_source(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LearningStageWorkerError("benchmark handler payload source must be an object")
    source = deepcopy(value)
    exact = {
        "contract_version", "provider_corpus_file_ref", "provider_case_ref",
        "projection_contract_version", "projection_rules_content_sha256",
        "window_binding_ref", "capture_ref", "handler_payload_sha256",
        "predecessor_content_sha256", "content_sha256",
    }
    if set(source) != exact or source.get("contract_version") != _BENCHMARK_SOURCE_VERSION:
        raise LearningStageWorkerError("benchmark handler payload source shape is invalid")
    digest = source.pop("content_sha256")
    if content_sha256(source) != digest:
        raise LearningStageWorkerError("benchmark handler payload source digest is invalid")
    source["content_sha256"] = digest
    corpus = source["provider_corpus_file_ref"]
    if not isinstance(corpus, dict) or set(corpus) != {
        "contract_version", "relative_path", "file_sha256", "source_parent_ref",
        "content_sha256",
    }:
        raise LearningStageWorkerError("benchmark provider corpus ref shape is invalid")
    corpus_raw = deepcopy(corpus); corpus_digest = corpus_raw.pop("content_sha256")
    if content_sha256(corpus_raw) != corpus_digest:
        raise LearningStageWorkerError("benchmark provider corpus ref digest is invalid")
    if corpus.get("relative_path") != "provider-corpus.v2.json":
        raise LearningStageWorkerError("benchmark provider corpus path is invalid")
    _benchmark_exact_ref(
        corpus.get("source_parent_ref"), "benchmark corpus parent ref"
    )
    if corpus.get("content_sha256") != source["predecessor_content_sha256"]:
        raise LearningStageWorkerError("benchmark handler payload source predecessor is invalid")
    case_ref = source.get("provider_case_ref")
    if not isinstance(case_ref, dict) or set(case_ref) != {"case_id", "case_content_sha256"}:
        raise LearningStageWorkerError("benchmark provider case ref shape is invalid")
    if not isinstance(case_ref["case_id"], str) or not case_ref["case_id"]:
        raise LearningStageWorkerError("benchmark provider case id is invalid")
    for ref_key in ("window_binding_ref", "capture_ref"):
        ref = source.get(ref_key)
        if not isinstance(ref, dict) or set(ref) != {"id", "content_sha256"}:
            raise LearningStageWorkerError(f"benchmark {ref_key} shape is invalid")
    if source.get("projection_contract_version") != "benchmark_v2_observe_screen_payload_projection_v1":
        raise LearningStageWorkerError("benchmark payload projection contract is invalid")
    for key in ("handler_payload_sha256", "projection_rules_content_sha256"):
        value_digest = source.get(key)
        if (
            not isinstance(value_digest, str)
            or len(value_digest) != 64
            or any(
                character not in "0123456789abcdef"
                for character in value_digest
            )
        ):
            raise LearningStageWorkerError(f"benchmark {key} is invalid")
    for digest_value in (
        corpus.get("file_sha256"), case_ref.get("case_content_sha256"),
        source["window_binding_ref"].get("content_sha256"),
        source["capture_ref"].get("content_sha256"),
    ):
        if (
            not isinstance(digest_value, str)
            or len(digest_value) != 64
            or any(
                character not in "0123456789abcdef"
                for character in digest_value
            )
        ):
            raise LearningStageWorkerError("benchmark source contains an invalid digest")
    return source


def compose_benchmark_worker_operation_anchor_v1(
    *,
    supervision_root: BenchmarkWorkerSupervisionRoot,
    reservation: dict[str, Any],
    handler_payload_source: dict[str, Any],
    window_binding_ref: dict[str, Any],
    capture_ref: dict[str, Any],
    predecessor_content_sha256: str | None,
) -> dict[str, Any]:
    root = _validate_benchmark_supervision_root(supervision_root)
    source = _validate_benchmark_source(handler_payload_source)
    if reservation.get("handler_payload_source_ref") != _benchmark_source_ref(source):
        raise LearningStageWorkerError("benchmark reservation source does not match")
    identity = {
        "contract_version": _BENCHMARK_ANCHOR_VERSION,
        "run_id": reservation["run_id"], "stage": reservation["stage"],
        "operation_id": reservation["operation_id"],
        "workflow_revision": reservation["workflow_revision"],
        "task_kind": reservation["task_kind"], "worker_id": reservation["worker_id"],
        "execution_nonce": reservation["execution_nonce"],
        "payload_sha256": reservation["payload_sha256"],
        "reservation_ref": {"content_sha256": reservation["content_sha256"]},
        "supervision_inputs_ref": deepcopy(reservation["supervision_inputs_ref"]),
        "handler_payload_source_ref": _benchmark_source_ref(source),
        "window_binding_ref": deepcopy(window_binding_ref),
        "capture_ref": deepcopy(capture_ref),
    }
    anchor_identity_sha256 = content_sha256(identity)
    from app.learn.hybrid.windows_process_scope import benchmark_worker_scope_name_v1
    scope_name = benchmark_worker_scope_name_v1(
        authority_kind=root.authority_kind, run_id=reservation["run_id"],
        stage=reservation["stage"], operation_id=reservation["operation_id"],
        worker_id=reservation["worker_id"], payload_sha256=reservation["payload_sha256"],
        execution_nonce=reservation["execution_nonce"],
    )
    expected = seal_immutable({
        "contract_version": _BENCHMARK_EXPECTED_SUPERVISION_VERSION,
        "authority_kind": root.authority_kind,
        "operation_anchor_ref": {"content_sha256": anchor_identity_sha256},
        "reservation_ref": identity["reservation_ref"],
        "supervision_inputs_ref": reservation["supervision_inputs_ref"],
        "handler_payload_source_ref": identity["handler_payload_source_ref"],
        "run_id": identity["run_id"], "stage": identity["stage"],
        "operation_id": identity["operation_id"], "workflow_revision": identity["workflow_revision"],
        "worker_id": identity["worker_id"], "task_kind": identity["task_kind"],
        "payload_sha256": identity["payload_sha256"], "execution_nonce": identity["execution_nonce"],
        "scope_name": scope_name, "startup_gate_timeout_ms": 15_000,
        "artifact_is_authorization": False, "execute_binding_enabled": False,
    })
    body = {
        **identity,
        "expected_supervision_ref": {"content_sha256": expected["content_sha256"]},
        "anchor_identity_sha256": anchor_identity_sha256,
        "predecessor_content_sha256": predecessor_content_sha256,
    }
    return seal_immutable(body)


def validate_benchmark_worker_operation_anchor_v1(
    value: object,
    *,
    supervision_root: BenchmarkWorkerSupervisionRoot,
    expected_reservation: dict[str, Any],
) -> dict[str, Any]:
    _validate_benchmark_supervision_root(supervision_root)
    if not isinstance(value, dict):
        raise LearningStageWorkerError("benchmark worker operation anchor is invalid")
    source = expected_reservation.get("handler_payload_source")
    expected = compose_benchmark_worker_operation_anchor_v1(
        supervision_root=supervision_root,
        reservation=expected_reservation,
        handler_payload_source=source,
        window_binding_ref=source["window_binding_ref"],
        capture_ref=source["capture_ref"],
        predecessor_content_sha256=value.get("predecessor_content_sha256"),
    )
    if value != expected:
        raise LearningStageWorkerError("benchmark worker operation anchor identity mismatch")
    return deepcopy(expected)


def compose_benchmark_worker_supervision_v1(
    *, supervision_root: BenchmarkWorkerSupervisionRoot,
    reservation: dict[str, Any], expected_operation_anchor: dict[str, Any],
    supervisor_process_identity: dict[str, Any], startup_gate_timeout_ms: int,
) -> dict[str, Any]:
    root = _validate_benchmark_supervision_root(supervision_root)
    anchor = validate_benchmark_worker_operation_anchor_v1(
        expected_operation_anchor,
        supervision_root=root,
        expected_reservation=reservation,
    )
    if startup_gate_timeout_ms != 15_000:
        raise LearningStageWorkerError("benchmark startup gate timeout does not match anchor")
    source_ref = reservation["handler_payload_source_ref"]
    body = {
        "contract_version": _BENCHMARK_SUPERVISION_VERSION,
        "authority_kind": root.authority_kind,
        "expected_supervision_ref": anchor["expected_supervision_ref"],
        "operation_anchor_ref": {"content_sha256": anchor["anchor_identity_sha256"]},
        "reservation_ref": {"content_sha256": reservation["content_sha256"]},
        "supervision_inputs_ref": reservation["supervision_inputs_ref"],
        "handler_payload_source_ref": source_ref,
        "run_id": reservation["run_id"], "stage": reservation["stage"],
        "operation_id": reservation["operation_id"],
        "workflow_revision": reservation["workflow_revision"],
        "worker_id": reservation["worker_id"], "task_kind": reservation["task_kind"],
        "payload_sha256": reservation["payload_sha256"],
        "execution_nonce": reservation["execution_nonce"],
        "supervisor_process_identity": deepcopy(supervisor_process_identity),
        "startup_gate_timeout_ms": startup_gate_timeout_ms,
        "scope_name": __import__(
            "app.learn.hybrid.windows_process_scope", fromlist=["benchmark_worker_scope_name_v1"]
        ).benchmark_worker_scope_name_v1(
            authority_kind=root.authority_kind,
            run_id=reservation["run_id"], stage=reservation["stage"],
            operation_id=reservation["operation_id"], worker_id=reservation["worker_id"],
            payload_sha256=reservation["payload_sha256"],
            execution_nonce=reservation["execution_nonce"],
        ),
        "artifact_is_authorization": False, "execute_binding_enabled": False,
    }
    return seal_immutable(body)


def validate_benchmark_worker_supervision_v1(
    value: object, *, supervision_root: BenchmarkWorkerSupervisionRoot,
    expected_operation_anchor: dict[str, Any],
) -> dict[str, Any]:
    root = _validate_benchmark_supervision_root(supervision_root)
    if not isinstance(value, dict):
        raise LearningStageWorkerError("benchmark worker supervision is invalid")
    exact = {
        "contract_version", "authority_kind", "expected_supervision_ref",
        "operation_anchor_ref", "reservation_ref", "supervision_inputs_ref",
        "handler_payload_source_ref", "run_id", "stage", "operation_id",
        "workflow_revision", "worker_id", "task_kind", "payload_sha256",
        "execution_nonce", "scope_name", "supervisor_process_identity",
        "startup_gate_timeout_ms", "artifact_is_authorization",
        "execute_binding_enabled", "content_sha256",
    }
    if set(value) != exact or value.get("contract_version") != _BENCHMARK_SUPERVISION_VERSION:
        raise LearningStageWorkerError("benchmark worker supervision shape is invalid")
    raw = deepcopy(value); digest = raw.pop("content_sha256")
    if content_sha256(raw) != digest:
        raise LearningStageWorkerError("benchmark worker supervision digest is invalid")
    if value["operation_anchor_ref"] != {"content_sha256": expected_operation_anchor["anchor_identity_sha256"]}:
        raise LearningStageWorkerError("benchmark worker supervision anchor mismatch")
    if value["expected_supervision_ref"] != expected_operation_anchor["expected_supervision_ref"]:
        raise LearningStageWorkerError("benchmark worker expected supervision mismatch")
    for key in (
        "run_id", "stage", "operation_id", "workflow_revision", "worker_id",
        "task_kind", "payload_sha256", "execution_nonce", "supervision_inputs_ref",
        "handler_payload_source_ref",
    ):
        if value.get(key) != expected_operation_anchor.get(key):
            raise LearningStageWorkerError(
                f"benchmark worker supervision {key} mismatch"
            )
    if (
        value.get("authority_kind") != root.authority_kind
        or value.get("reservation_ref") != expected_operation_anchor.get("reservation_ref")
        or value.get("startup_gate_timeout_ms") != 15_000
        or value.get("artifact_is_authorization") is not False
        or value.get("execute_binding_enabled") is not False
    ):
        raise LearningStageWorkerError("benchmark worker supervision authority is invalid")
    return deepcopy(value)


class LearningStageWorkerError(ValueError):
    """学习阶段 worker 请求无效或不属于当前 operation。"""


class LearningStageWorkerCleanupError(LearningStageWorkerError):
    """学习阶段 worker 启动清理无法证明为完成。"""

    def __init__(
        self,
        evidence: dict[str, Any],
        message: str = "Hybrid worker start cleanup is indeterminate",
    ) -> None:
        super().__init__(message)
        self.cleanup_evidence = deepcopy(evidence)


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
        and persisted_result.get("status") == "success"
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
        capture_bundle = deepcopy(orchestration.get("capture_bundle"))
        if isinstance(capture_bundle, dict):
            capture_bundle.pop("bundle_ref", None)
        execution_payload.setdefault(
            "hybrid_fusion_result",
            deepcopy(orchestration.get("fusion_result")),
        )
        execution_payload.setdefault(
            "capture_bundle",
            capture_bundle,
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
            assert isinstance(orchestration, dict)
            orchestration["hybrid_vista_requests"] = deepcopy(
                execution_payload["hybrid_vista_requests"]
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
            calibration_options: dict[str, Any] = {}
            if cancellation_event is not None:
                calibration_options["cancellation_event"] = cancellation_event
            from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
                current_benchmark_dispatch_context,
            )

            # 只有 Benchmark-v2 的 server-owned context 才启用新的 lease cut-point；
            # 既有非 benchmark handler 的调用合同保持不变。
            if current_benchmark_dispatch_context() is not None:
                calibration_options["model_lease"] = model_lease
            response = calibration_handler(execution_payload, **calibration_options)
        elif normalized_kind == "vision_observe_screen":
            screen_reader_options: dict[str, Any] = {
                "managed_model_lease": model_lease,
            }
            if cancellation_event is not None:
                screen_reader_options["cancellation_event"] = cancellation_event
            response = observe_result_to_legacy_response(
                run_observe_task(
                    ObserveScreenTaskInput.model_validate(execution_payload),
                    project_root=_PROJECT_ROOT,
                    screen_reader=partial(
                        read_screen,
                        **screen_reader_options,
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
            provider_result = (
                deepcopy(response)
                if isinstance(response, dict) and response.get("success") is False
                else _hybrid_calibration_result(response)
            )
            vista_receipt = _release_hybrid_vista_lease(
                model_lease,
                lineage=supervisor_lineage,
                predecessor_sha256=_artifact_digest(
                    orchestration.get("fusion_result")
                ),
                provider_result_sha256=_artifact_digest(provider_result),
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
                "recovered_lease_ref": {
                    "content_sha256": document["content_sha256"]
                },
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


def _project_vista_no_acquisition_reconciliation(
    record: dict[str, Any], reconciliation: Mapping[str, object]
) -> dict[str, Any]:
    scope = reconciliation.get("scope_cleanup_evidence")
    samples = scope.get("samples") if isinstance(scope, Mapping) else None
    empty_scope_fields = (
        "observed_member_pids_before",
        "observed_member_identities_before",
        "member_pids_after",
        "member_identities_after",
        "active_listeners_after",
    )
    if (
        set(reconciliation)
        != {"contract_version", "status", "scope_cleanup_evidence", "recovered_lease_ref"}
        or reconciliation.get("contract_version")
        != "hybrid_supervisor_reconciliation_v2"
        or reconciliation.get("status") != "verified"
        or not isinstance(scope, Mapping)
        or set(scope)
        != {
            "contract_version", "scope_name", "authority", "cleanup_status",
            *empty_scope_fields, "pid_file_after", "stable_zero_observations",
            "samples", "scope_absent_after_owner_close",
        }
        or scope.get("contract_version") != "hybrid_windows_process_scope_v1"
        or scope.get("scope_name") != record.get("provider_scope_name")
        or scope.get("authority") != "windows_job_object"
        or scope.get("cleanup_status") != "verified"
        or any(scope.get(name) != [] for name in empty_scope_fields)
        or scope.get("pid_file_after") is not None
        or isinstance(scope.get("stable_zero_observations"), bool)
        or not isinstance(scope.get("stable_zero_observations"), int)
        or scope["stable_zero_observations"] < 3
        or not isinstance(samples, list)
        or len(samples) < 3
        or any(
            sample != {"pids": [], "process_identities": [], "listeners": []}
            for sample in samples
        )
        or not isinstance(scope.get("scope_absent_after_owner_close"), bool)
    ):
        raise LearningStageWorkerError(
            "recovered Hybrid VISTA stable-zero evidence is invalid"
        )

    worker_id = _required_text(record.get("worker_id"), "worker_id")
    owner_path = Path(str(record.get("provider_owner_path") or ""))
    runtime_path = Path(str(record.get("provider_runtime_path") or ""))
    owner = _load_hybrid_provider_owner(
        owner_path,
        identity={name: str(record[name]) for name in (
            "worker_id", "run_id", "stage", "operation_id", "task_kind",
            "model_request_id", "payload_sha256",
        )},
        workflow_revision=int(record["workflow_revision"]),
        journal_scope_name=str(record["provider_scope_name"]),
        runtime_file=runtime_path.name,
    )
    runtime = _read_json_object(runtime_path, label="Hybrid VISTA runtime owner")
    context = {
        "provider_lease_path": str(record.get("provider_lease_path") or ""),
        "worker_id": worker_id,
        "process_scope_name": str(record.get("provider_scope_name") or ""),
    }
    lease = _load_supervised_vista_lease(context)
    lineage = owner["lineage"]
    expected_owner = seal_immutable({
        "contract_version": HYBRID_PROVIDER_OWNER_CONTRACT_VERSION,
        "worker_id": worker_id,
        "task_kind": record["task_kind"],
        "model_request_id": record["model_request_id"],
        "provider": "vista",
        "lineage": lineage,
        "process_scope_name": record["provider_scope_name"],
        "provider_runtime_file": runtime_path.name,
        "predecessor_sha256": owner["predecessor_sha256"],
    })
    expected_runtime = seal_immutable({
        "contract_version": HYBRID_PROVIDER_RUNTIME_CONTRACT_VERSION,
        "state": "acquiring",
        "worker_id": worker_id,
        "model_request_id": record["model_request_id"],
        "provider": "vista",
        "lineage": lineage,
        "process_scope_name": record["provider_scope_name"],
        "provider_identity": None,
        "cleanup_observation": None,
    })
    expected_lease = seal_immutable({
        "contract_version": "hybrid_supervised_provider_lease_v2",
        "state": "recovered",
        "worker_id": worker_id,
        "lineage": lineage,
        "process_scope_name": record["provider_scope_name"],
        "profile_id": lease.get("profile_id"),
        "predecessor_sha256": owner["predecessor_sha256"],
        "model_lease": None,
        "cleanup_receipt": None,
        "scope_cleanup_evidence": deepcopy(dict(scope)),
    })
    if (
        owner != expected_owner
        or runtime != expected_runtime
        or lease != expected_lease
        or reconciliation.get("recovered_lease_ref")
        != {"content_sha256": lease["content_sha256"]}
    ):
        raise LearningStageWorkerError(
            "recovered Hybrid VISTA owner lineage is invalid"
        )
    return {
        "outcome": "verified_not_acquired",
        "acquisition_owner_ref": {"content_sha256": owner["content_sha256"]},
        "runtime_owner_ref": {"content_sha256": runtime["content_sha256"]},
        "recovered_lease_ref": {"content_sha256": lease["content_sha256"]},
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
    benchmark_bootstrap: dict[str, Any] | None = None,
) -> None:
    if benchmark_bootstrap is not None:
        _wait_for_benchmark_worker_startup_gate(benchmark_bootstrap)
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
    binding_context = None
    dispatch_context_manager = None
    binding_lifecycle: dict[str, object] | None = None
    binding_entered = False
    dispatch_entered = False
    try:
        execution_payload = deepcopy(payload)
        has_dispatch_context = "_benchmark_v2_dispatch_context" in execution_payload
        dispatch_context = execution_payload.pop(
            "_benchmark_v2_dispatch_context", None
        )
        if has_dispatch_context:
            expected_provider = {
                "panel_learning_hybrid_omni_discovery": "omni",
                "panel_learning_hybrid_qwen_binding": "qwen",
                "panel_learning_calibration_sequence": "vista",
                "vision_observe_screen": "qwen",
            }.get(task_kind)
            if expected_provider is None or not isinstance(dispatch_context, dict):
                raise LearningStageWorkerError(
                    "benchmark dispatch context is not valid for this task"
                )
            from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
                install_benchmark_dispatch_attestor,
                validate_benchmark_dispatch_context,
            )

            validated_dispatch = validate_benchmark_dispatch_context(dispatch_context)
            if validated_dispatch["provider"] != expected_provider:
                raise LearningStageWorkerError(
                    "benchmark dispatch context provider differs from task"
                )
            dispatch_context_manager = install_benchmark_dispatch_attestor(
                dispatch_context=validated_dispatch
            )
            dispatch_context_manager.__enter__()
            dispatch_entered = True
        has_serialized_binding = "_benchmark_v2_window_binding" in execution_payload
        serialized_binding = execution_payload.pop(
            "_benchmark_v2_window_binding", None
        )
        if has_serialized_binding:
            if task_kind != "vision_observe_screen":
                raise LearningStageWorkerError(
                    "benchmark-v2 window binding is limited to vision_observe_screen"
                )
            if not isinstance(serialized_binding, dict):
                raise LearningStageWorkerError(
                    "benchmark-v2 window binding must be a sealed object"
                )
            from app.learn.hybrid.benchmark_v2_worker_binding import (
                install_spawned_worker_window_binding,
                resolve_spawned_worker_binding_operation_id,
                validate_spawned_worker_observation_payload,
            )

            validate_spawned_worker_observation_payload(
                payload=execution_payload,
                serialized=serialized_binding,
            )
            binding_operation_id = resolve_spawned_worker_binding_operation_id(
                serialized=serialized_binding,
                worker_identity=identity,
                observation_payload=execution_payload,
            )
            binding_context = install_spawned_worker_window_binding(
                serialized=serialized_binding,
                worker_operation_id=binding_operation_id,
            )
            binding_lifecycle = binding_context.__enter__()
            binding_entered = True
        response = execute_learning_stage_worker_task(
            task_kind,
            execution_payload,
            cancellation_event=cancellation_event,
        )
        if dispatch_entered:
            from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
                compose_benchmark_dispatch_context_ref,
                current_benchmark_dispatch_receipt_refs,
            )

            dispatch_refs = current_benchmark_dispatch_receipt_refs()
            if isinstance(response, dict) and response.get(
                "contract_version"
            ) == "learning_hybrid_managed_stage_result_v1":
                orchestration = response.get("orchestration")
                if not isinstance(orchestration, dict):
                    raise LearningStageWorkerError(
                        "Hybrid dispatch receipt projection lost orchestration"
                    )
                existing_refs = orchestration.get(
                    "benchmark_v2_provider_dispatch_receipt_refs", []
                )
                if not isinstance(existing_refs, list):
                    raise LearningStageWorkerError(
                        "Hybrid dispatch receipt projection is invalid"
                    )
                orchestration["benchmark_v2_provider_dispatch_receipt_refs"] = [
                    *deepcopy(existing_refs),
                    *deepcopy(dispatch_refs),
                ]
                provider_context_refs = orchestration.get(
                    "benchmark_v2_provider_dispatch_context_refs", {}
                )
                if not isinstance(provider_context_refs, dict):
                    raise LearningStageWorkerError(
                        "Hybrid dispatch context lineage is invalid"
                    )
                provider_context_refs = deepcopy(provider_context_refs)
                provider = str(validated_dispatch["provider"])
                if dispatch_refs:
                    context_ref = compose_benchmark_dispatch_context_ref(
                        context=validated_dispatch
                    )
                    prior_context_ref = provider_context_refs.get(provider)
                    if prior_context_ref not in (None, context_ref):
                        raise LearningStageWorkerError(
                            "Hybrid dispatch context lineage differs"
                        )
                    provider_context_refs[provider] = context_ref
                else:
                    provider_context_refs.pop(provider, None)
                orchestration[
                    "benchmark_v2_provider_dispatch_context_refs"
                ] = provider_context_refs
                if task_kind == "panel_learning_calibration_sequence":
                    managed_result = response.get("result")
                    managed_outcome = response.get("outcome")
                    if managed_outcome == "completed":
                        sequence = (
                            _hybrid_calibration_result(managed_result)
                            if isinstance(managed_result, dict)
                            else None
                        )
                        batch_count = (
                            sequence.get("batch_count")
                            if isinstance(sequence, dict)
                            else None
                        )
                        valid_batch_count = (
                            not isinstance(batch_count, bool)
                            and isinstance(batch_count, int)
                            and batch_count >= 1
                        )
                    elif managed_outcome == "failed":
                        if (
                            isinstance(managed_result, dict)
                            and managed_result.get("success") is False
                        ):
                            failure_data = managed_result.get("data")
                            batch_count = (
                                failure_data.get("batch_count")
                                if isinstance(failure_data, dict)
                                else None
                            )
                            valid_batch_count = (
                                not isinstance(batch_count, bool)
                                and isinstance(batch_count, int)
                                and batch_count >= 0
                            )
                        elif (
                            isinstance(managed_result, dict)
                            and managed_result.get("contract_version")
                            == "learning_hybrid_stage_failure_v1"
                        ):
                            batch_count = len(dispatch_refs)
                            valid_batch_count = True
                        else:
                            batch_count = None
                            valid_batch_count = False
                    else:
                        batch_count = None
                        valid_batch_count = False
                    if not valid_batch_count or len(dispatch_refs) != batch_count:
                        raise LearningStageWorkerError(
                            "Hybrid VISTA dispatch receipts differ from batch_count"
                        )
                    orchestration[
                        "benchmark_v2_vista_batch_count"
                    ] = batch_count
            elif isinstance(response, dict):
                response["_benchmark_v2_provider_dispatch_receipt_refs"] = deepcopy(
                    dispatch_refs
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
        binding_cleanup_error: BaseException | None = None
        if dispatch_entered and dispatch_context_manager is not None:
            try:
                dispatch_context_manager.__exit__(None, None, None)
            except BaseException as cleanup_error:
                binding_cleanup_error = cleanup_error
        if binding_entered and binding_context is not None:
            try:
                binding_context.__exit__(None, None, None)
            except BaseException as cleanup_error:
                binding_cleanup_error = cleanup_error
        if binding_lifecycle is not None:
            adopted_receipt = binding_lifecycle.get("adopted_receipt")
            normal_clear_receipt = binding_lifecycle.get("normal_clear_receipt")
            if isinstance(adopted_receipt, dict):
                envelope["benchmark_v2_window_binding_adopted_receipt"] = deepcopy(
                    adopted_receipt
                )
            if isinstance(normal_clear_receipt, dict):
                envelope["normal_clear_receipt"] = deepcopy(normal_clear_receipt)
                envelope["normal_binding_evidence_ref"] = {
                    "content_sha256": content_sha256(normal_clear_receipt)
                }
            snapshot = binding_lifecycle.get("snapshot")
            response_payload = envelope.get("response")
            if (
                isinstance(adopted_receipt, dict)
                and isinstance(normal_clear_receipt, dict)
                and isinstance(snapshot, dict)
                and isinstance(response_payload, dict)
            ):
                response_payload["_benchmark_v2_window_binding_evidence"] = {
                    "adopted_receipt": deepcopy(adopted_receipt),
                    "normal_clear_receipt": deepcopy(normal_clear_receipt),
                    "snapshot": deepcopy(snapshot),
                }
        if binding_cleanup_error is not None:
            envelope = {
                "contract_version": LEARNING_STAGE_WORKER_RESULT_CONTRACT_VERSION,
                **deepcopy(identity),
                "status": "failed",
                "finished_at": _utc_now_iso(),
                "error": {
                    "type": type(binding_cleanup_error).__name__,
                    "details": str(binding_cleanup_error),
                },
                **(
                    {
                        "benchmark_v2_window_binding_adopted_receipt": deepcopy(
                            binding_lifecycle["adopted_receipt"]
                        )
                    }
                    if isinstance(binding_lifecycle, dict)
                    and isinstance(binding_lifecycle.get("adopted_receipt"), dict)
                    else {}
                ),
            }
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


def _wait_for_benchmark_worker_startup_gate(bootstrap: dict[str, Any]) -> None:
    """子进程第一项动作：发布身份并在 named Event 前保持 handler fence。"""

    import psutil
    import win32api
    import win32event

    event_name = _required_text(bootstrap.get("event_name"), "benchmark event_name")
    beacon_path = Path(_required_text(bootstrap.get("beacon_path"), "benchmark beacon_path"))
    timeout_ms = bootstrap.get("startup_gate_timeout_ms")
    if not isinstance(timeout_ms, int) or timeout_ms <= 0:
        os._exit(191)
    event_handle = None
    try:
        event_handle = win32event.OpenEvent(
            win32event.EVENT_MODIFY_STATE | 0x00100000, False, event_name
        )
        identity = {
            "pid": os.getpid(),
            "create_time_ns": int(round(psutil.Process().create_time() * 1_000_000_000)),
        }
        beacon = seal_immutable({
            "contract_version": "benchmark_worker_identity_beacon_v1",
            "worker_id": bootstrap["worker_id"],
            "operation_anchor_ref": deepcopy(bootstrap["operation_anchor_ref"]),
            "process_identity": identity,
            "predecessor_content_sha256": bootstrap["supervision_ref"]["content_sha256"],
        })
        if beacon_path.exists():
            os._exit(192)
        _write_json_atomic(beacon_path, beacon)
        outcome = win32event.WaitForSingleObject(event_handle, timeout_ms)
        if outcome != win32event.WAIT_OBJECT_0:
            os._exit(193)
    except BaseException:
        os._exit(194)
    finally:
        if event_handle is not None:
            try:
                win32api.CloseHandle(event_handle)
            except BaseException:
                os._exit(195)


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
        benchmark_supervision_root: BenchmarkWorkerSupervisionRoot | None = None,
    ) -> None:
        self._result_root = Path(result_root).resolve()
        self._result_root.mkdir(parents=True, exist_ok=True)
        context = multiprocessing.get_context("spawn")
        self._process_context = context
        self._process_factory = process_factory or context.Process
        self._model_request_cancel = model_request_cancel or cancel_model_request
        self._benchmark_supervision_root = (
            _validate_benchmark_supervision_root(
                benchmark_supervision_root,
                expected_journal_root=self._result_root,
            )
            if benchmark_supervision_root is not None
            else None
        )
        self._lock = RLock()
        self._benchmark_reservations: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._benchmark_reservations_by_ref: dict[str, dict[str, Any]] = {}
        self._benchmark_provider_journals: dict[
            tuple[str, str, str], dict[str, Any]
        ] = {}
        self._benchmark_provider_cleanup_journals: dict[
            tuple[str, str, str], dict[str, Any]
        ] = {}
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
        self._failed_start_cleanups: dict[
            tuple[str, str, str], dict[str, Any]
        ] = {}
        self._load_benchmark_reservations()
        self._load_benchmark_provider_journals()
        self._load_journals()
        self._load_unattached_benchmark_owners()

    def _load_benchmark_reservations(self) -> None:
        for path in sorted(self._result_root.glob("*.benchmark-reservation.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise LearningStageWorkerError(
                    f"benchmark reservation is unreadable: {path.name}: {error}"
                ) from error
            reservation = self._validate_benchmark_reservation(value)
            key = (
                reservation["run_id"], reservation["stage"],
                reservation["operation_id"],
            )
            if key in self._benchmark_reservations:
                raise LearningStageWorkerError("duplicate benchmark reservation operation")
            self._validate_benchmark_reservation_identity_reuse(
                reservation, key=key
            )
            self._benchmark_reservations[key] = reservation
            self._benchmark_reservations_by_ref[reservation["content_sha256"]] = reservation
            if reservation["reservation_state"] != "reserved":
                original_body = deepcopy(reservation)
                original_body.pop("content_sha256")
                original_body["reservation_state"] = "reserved"
                original_body["abort_observation_ref"] = None
                original_body["predecessor_content_sha256"] = reservation[
                    "handler_payload_source"
                ]["content_sha256"]
                original = seal_immutable(original_body)
                self._benchmark_reservations_by_ref[original["content_sha256"]] = original

    def _load_unattached_benchmark_owners(self) -> None:
        for owner_path in sorted(self._result_root.glob("*.benchmark-owner.json")):
            try:
                owner = json.loads(owner_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise LearningStageWorkerError(
                    f"benchmark owner journal is unreadable: {error}"
                ) from error
            worker_id = owner.get("worker_id")
            if worker_id in self._records:
                continue
            raw = deepcopy(owner); digest = raw.pop("content_sha256", None)
            if (
                owner.get("contract_version") != "benchmark_worker_owner_journal_v1"
                or content_sha256(raw) != digest
            ):
                raise LearningStageWorkerError("benchmark owner journal is invalid")
            operation_key = (owner.get("run_id"), owner.get("stage"), owner.get("operation_id"))
            reservation = self._benchmark_reservations.get(operation_key)
            if not isinstance(reservation, dict) or reservation.get("worker_id") != worker_id:
                raise LearningStageWorkerError("benchmark owner reservation identity mismatch")
            record = {
                "contract_version": LEARNING_STAGE_WORKER_CONTRACT_VERSION,
                "worker_id": worker_id, "run_id": owner["run_id"], "stage": owner["stage"],
                "operation_id": owner["operation_id"], "task_kind": reservation["task_kind"],
                "model_request_id": owner["model_request_id"],
                "payload_sha256": owner["payload_sha256"],
                "status": "recovery_required", "started_at": None, "finished_at": None,
                "result_path": str(self._result_root / f"{worker_id}.result.json"),
                "journal_path": str(self._result_root / f"{worker_id}.worker.json"),
                "process": None, "payload": {}, "recovered_from_journal": True,
                "benchmark_owner_path": str(owner_path),
                "benchmark_beacon_path": str(self._result_root / f"{worker_id}.benchmark-beacon.json"),
                "benchmark_event_handle": None, "benchmark_scope": None,
                "benchmark_reservation": reservation,
            }
            self._records[worker_id] = record
            self._workers_by_operation.setdefault(operation_key, []).append(worker_id)

    def _validate_benchmark_reservation(self, value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise LearningStageWorkerError("benchmark reservation must be an object")
        exact = {
            "contract_version", "authority_kind", "run_id", "stage", "operation_id",
            "workflow_revision", "task_kind", "payload_sha256", "handler_payload_source",
            "handler_payload_source_ref", "worker_id", "model_request_id", "execution_nonce",
            "supervision_inputs_ref", "reservation_state", "abort_observation_ref",
            "predecessor_content_sha256", "content_sha256",
        }
        if set(value) != exact or value.get("contract_version") != _BENCHMARK_RESERVATION_VERSION:
            raise LearningStageWorkerError("benchmark reservation shape is invalid")
        source = _validate_benchmark_source(value.get("handler_payload_source"))
        if value.get("handler_payload_source_ref") != _benchmark_source_ref(source):
            raise LearningStageWorkerError("benchmark reservation source ref is invalid")
        raw = deepcopy(value); digest = raw.pop("content_sha256")
        if content_sha256(raw) != digest:
            raise LearningStageWorkerError("benchmark reservation digest is invalid")
        if value.get("reservation_state") not in {
            "reserved", "anchored", "launching", "launched",
            "cancelled_before_launch", "aborted_before_anchor",
        }:
            raise LearningStageWorkerError("benchmark reservation state is invalid")
        _validate_benchmark_reservation_supervision(
            value,
            supervision_root=self._benchmark_supervision_root,
            expected_journal_root=self._result_root,
        )
        return deepcopy(value)

    def _benchmark_reservation_path(self, operation_id: str) -> Path:
        return _benchmark_operation_artifact_path(
            self._result_root,
            operation_id,
            ".benchmark-reservation.json",
        )

    def _validate_benchmark_reservation_identity_reuse(
        self,
        reservation: Mapping[str, object],
        *,
        key: tuple[str, str, str],
    ) -> None:
        for existing_key, existing in self._benchmark_reservations.items():
            if existing_key == key:
                continue
            if (
                existing.get("worker_id") == reservation.get("worker_id")
                or existing.get("model_request_id")
                == reservation.get("model_request_id")
            ):
                raise LearningStageWorkerError(
                    "benchmark worker/model request identity reuse is invalid"
                )

    def _persist_benchmark_reservation(self, reservation: dict[str, Any]) -> None:
        _write_json_atomic(
            self._benchmark_reservation_path(reservation["operation_id"]), reservation
        )

    def _benchmark_anchored_reservation(
        self, current: Mapping[str, object]
    ) -> dict[str, Any]:
        value = deepcopy(dict(current))
        _validate_benchmark_reservation_supervision(
            value,
            supervision_root=self._benchmark_supervision_root,
            expected_journal_root=self._result_root,
        )
        if value.get("reservation_state") == "anchored":
            return value
        original_body = deepcopy(value)
        original_body.pop("content_sha256", None)
        original_body["reservation_state"] = "reserved"
        original_body["abort_observation_ref"] = None
        original_body["predecessor_content_sha256"] = value[
            "handler_payload_source"
        ]["content_sha256"]
        original = seal_immutable(original_body)
        if value.get("reservation_state") not in {
            "launching",
            "launched",
            "cancelled_before_launch",
        }:
            raise LearningStageWorkerError(
                "benchmark provider reservation has no anchored lineage"
            )
        return self._transition_benchmark_reservation(original, "anchored")

    @staticmethod
    def _validate_benchmark_provider_runtime_owner(
        value: object, *, anchored: Mapping[str, object]
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LearningStageWorkerError(
                "benchmark provider runtime owner is required"
            )
        owner = deepcopy(dict(value))
        expected_fields = {
            "contract_version",
            "authority_kind",
            "run_id",
            "stage",
            "operation_id",
            "worker_id",
            "model_request_id",
            "reservation_ref",
            "payload_sha256",
            "content_sha256",
        }
        expected_identity = {
            field: anchored[field]
            for field in (
                "authority_kind",
                "run_id",
                "stage",
                "operation_id",
                "worker_id",
                "model_request_id",
                "payload_sha256",
            )
        }
        if (
            set(owner) != expected_fields
            or owner.get("contract_version")
            != "benchmark_provider_runtime_owner_v1"
            or content_sha256(owner) != owner.get("content_sha256")
            or any(
                owner.get(field) != expected
                for field, expected in expected_identity.items()
            )
            or owner.get("reservation_ref")
            != {"content_sha256": anchored["content_sha256"]}
        ):
            raise LearningStageWorkerError(
                "benchmark provider runtime owner identity does not match"
            )
        _benchmark_exact_ref(
            owner["reservation_ref"], "benchmark provider owner reservation ref"
        )
        return owner

    @staticmethod
    def _validate_benchmark_provider_owner(
        value: object,
        *,
        model_request_id: str,
        runtime_owner: Mapping[str, object],
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LearningStageWorkerError(
                "benchmark provider acquisition owner is missing"
            )
        owner = deepcopy(dict(value))
        if (
            set(owner)
            != {
                "contract_version",
                "model_request_id",
                "runtime_owner_ref",
                "acquisition_intent_ref",
                "owner_state",
                "content_sha256",
            }
            or owner.get("contract_version")
            != "benchmark_provider_acquisition_owner_v1"
            or owner.get("model_request_id") != model_request_id
            or owner.get("runtime_owner_ref") != runtime_owner
            or owner.get("owner_state") != "acquisition_prepared"
            or content_sha256(owner) != owner.get("content_sha256")
        ):
            raise LearningStageWorkerError(
                "benchmark provider acquisition owner is invalid"
            )
        _benchmark_exact_ref(
            owner.get("acquisition_intent_ref"),
            "benchmark provider acquisition intent ref",
        )
        return owner

    @staticmethod
    def _validate_benchmark_provider_acquisition_observation(
        value: object,
        *,
        model_request_id: str,
        acquisition_owner_ref: Mapping[str, object],
        acquisition_intent_ref: Mapping[str, object],
        runtime_owner_ref: Mapping[str, object],
        expected_state: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LearningStageWorkerError(
                "benchmark provider acquisition observation is missing"
            )
        observation = deepcopy(dict(value))
        if (
            set(observation)
            != {
                "contract_version",
                "model_request_id",
                "acquisition_owner_ref",
                "acquisition_intent_ref",
                "runtime_owner_ref",
                "prepared_materialization_ledger_ref",
                "materialization_ledger_ref",
                "materialization_state",
                "materialization_revision",
                "content_sha256",
            }
            or observation.get("contract_version")
            != "qwen_model_request_acquisition_observation_v1"
            or observation.get("model_request_id")
            != model_request_id
            or observation.get("acquisition_owner_ref")
            != acquisition_owner_ref
            or observation.get("acquisition_intent_ref")
            != acquisition_intent_ref
            or observation.get("runtime_owner_ref")
            != runtime_owner_ref
            or observation.get("materialization_state")
            not in {
                "prepared_never_materialized",
                "materialization_possible",
                "aborted_never_materialized",
            }
            or observation.get("materialization_revision") not in {0, 1}
            or (
                observation.get("materialization_state")
                == "prepared_never_materialized"
                and (
                    observation.get("materialization_revision") != 0
                    or observation.get("materialization_ledger_ref")
                    != observation.get("prepared_materialization_ledger_ref")
                )
            )
            or (
                observation.get("materialization_state")
                != "prepared_never_materialized"
                and observation.get("materialization_revision") != 1
            )
            or (
                expected_state is not None
                and observation.get("materialization_state") != expected_state
            )
            or (
                expected_revision is not None
                and observation.get("materialization_revision")
                != expected_revision
            )
            or content_sha256(observation)
            != observation.get("content_sha256")
        ):
            raise LearningStageWorkerError(
                "benchmark provider acquisition observation is invalid"
            )
        _benchmark_exact_ref(
            observation.get("acquisition_owner_ref"),
            "benchmark provider observed acquisition owner ref",
        )
        _benchmark_exact_ref(
            observation.get("acquisition_intent_ref"),
            "benchmark provider observed acquisition intent ref",
        )
        _benchmark_exact_ref(
            observation.get("prepared_materialization_ledger_ref"),
            "benchmark provider prepared materialization ledger ref",
        )
        _benchmark_exact_ref(
            observation.get("materialization_ledger_ref"),
            "benchmark provider materialization ledger ref",
        )
        return observation

    @staticmethod
    def _benchmark_provider_prepared_observation_ref(
        observation: Mapping[str, object],
    ) -> dict[str, str]:
        prepared_body = {
            field: deepcopy(observation[field])
            for field in (
                "contract_version",
                "model_request_id",
                "acquisition_owner_ref",
                "acquisition_intent_ref",
                "runtime_owner_ref",
                "prepared_materialization_ledger_ref",
            )
        }
        prepared_body["materialization_ledger_ref"] = deepcopy(
            observation["prepared_materialization_ledger_ref"]
        )
        prepared_body["materialization_state"] = "prepared_never_materialized"
        prepared_body["materialization_revision"] = 0
        return {"content_sha256": content_sha256(prepared_body)}

    @classmethod
    def _validate_benchmark_provider_journal_observation_lineage(
        cls,
        journal: Mapping[str, object],
        observation: Mapping[str, object],
    ) -> None:
        prepared_observation_ref = (
            cls._benchmark_provider_prepared_observation_ref(observation)
        )
        prepared_ledger_ref = observation[
            "prepared_materialization_ledger_ref"
        ]
        if (
            journal.get("prepared_acquisition_observation_ref")
            != prepared_observation_ref
            or journal.get("prepared_materialization_ledger_ref")
            != prepared_ledger_ref
        ):
            raise LearningStageWorkerError(
                "benchmark provider prepared acquisition lineage drifted"
            )
        stored_is_prepared = (
            journal.get("acquisition_observation_ref")
            == prepared_observation_ref
            and journal.get("materialization_ledger_ref")
            == prepared_ledger_ref
        )
        stored_is_current = (
            journal.get("acquisition_observation_ref")
            == {"content_sha256": observation["content_sha256"]}
            and journal.get("materialization_ledger_ref")
            == observation["materialization_ledger_ref"]
        )
        if not stored_is_prepared and not stored_is_current:
            raise LearningStageWorkerError(
                "benchmark provider current acquisition lineage drifted"
            )

    @staticmethod
    def _benchmark_provider_journal_projection(
        journal: Mapping[str, object],
    ) -> dict[str, Any]:
        return seal_immutable(
            {
                "contract_version": "benchmark_provider_acquisition_ref_v1",
                **{
                    field: deepcopy(journal[field])
                    for field in (
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
                    )
                },
                "runtime_owner_ref": {
                    "content_sha256": journal["runtime_owner_ref"]["content_sha256"]
                },
            }
        )

    @staticmethod
    def _benchmark_provider_journal_with_observation(
        journal: Mapping[str, object],
        observation: Mapping[str, object],
    ) -> dict[str, Any]:
        body = deepcopy(dict(journal))
        body.pop("content_sha256")
        body["acquisition_observation_ref"] = {
            "content_sha256": observation["content_sha256"]
        }
        body["materialization_ledger_ref"] = deepcopy(
            observation["materialization_ledger_ref"]
        )
        return seal_immutable(body)

    def _validate_benchmark_provider_journal(
        self, value: object
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LearningStageWorkerError("benchmark provider journal is invalid")
        journal = deepcopy(dict(value))
        if set(journal) != {
            "contract_version",
            "authority_kind",
            "run_id",
            "stage",
            "operation_id",
            "worker_id",
            "model_request_id",
            "payload_sha256",
            "reservation_ref",
            "runtime_owner_ref",
            "acquisition_owner_ref",
            "acquisition_intent_ref",
            "prepared_acquisition_observation_ref",
            "prepared_materialization_ledger_ref",
            "acquisition_observation_ref",
            "materialization_ledger_ref",
            "content_sha256",
        } or journal.get("contract_version") != _BENCHMARK_PROVIDER_JOURNAL_VERSION:
            raise LearningStageWorkerError("benchmark provider journal is invalid")
        if content_sha256(journal) != journal.get("content_sha256"):
            raise LearningStageWorkerError("benchmark provider journal seal is invalid")
        key = (
            journal.get("run_id"),
            journal.get("stage"),
            journal.get("operation_id"),
        )
        current = self._benchmark_reservations.get(key)
        if current is None:
            raise LearningStageWorkerError(
                "benchmark provider reservation identity is missing"
            )
        anchored = self._benchmark_anchored_reservation(current)
        runtime_owner = self._validate_benchmark_provider_runtime_owner(
            journal.get("runtime_owner_ref"), anchored=anchored
        )
        expected_identity = {
            field: anchored[field]
            for field in (
                "authority_kind",
                "run_id",
                "stage",
                "operation_id",
                "worker_id",
                "model_request_id",
                "payload_sha256",
            )
        }
        if (
            any(
                journal.get(field) != expected
                for field, expected in expected_identity.items()
            )
            or journal.get("reservation_ref")
            != {"content_sha256": anchored["content_sha256"]}
        ):
            raise LearningStageWorkerError(
                "benchmark provider journal identity does not match"
            )
        _benchmark_exact_ref(
            journal.get("acquisition_owner_ref"),
            "benchmark provider acquisition owner ref",
        )
        _benchmark_exact_ref(
            journal.get("acquisition_intent_ref"),
            "benchmark provider acquisition intent ref",
        )
        _benchmark_exact_ref(
            journal.get("prepared_acquisition_observation_ref"),
            "benchmark provider prepared acquisition observation ref",
        )
        _benchmark_exact_ref(
            journal.get("prepared_materialization_ledger_ref"),
            "benchmark provider prepared materialization ledger ref",
        )
        _benchmark_exact_ref(
            journal.get("acquisition_observation_ref"),
            "benchmark provider acquisition observation ref",
        )
        _benchmark_exact_ref(
            journal.get("materialization_ledger_ref"),
            "benchmark provider materialization ledger ref",
        )
        if journal["runtime_owner_ref"] != runtime_owner:
            raise LearningStageWorkerError("benchmark provider runtime owner drifted")
        return journal

    def _load_benchmark_provider_journals(self) -> None:
        for path in sorted(self._result_root.glob("*.benchmark-provider.json")):
            try:
                journal = self._validate_benchmark_provider_journal(
                    _read_json_object(path, label="benchmark provider journal")
                )
                observation = (
                    self._validate_benchmark_provider_acquisition_observation(
                        observe_qwen_model_request_acquisition(
                            journal["model_request_id"],
                            acquisition_intent_ref=journal[
                                "acquisition_intent_ref"
                            ],
                            runtime_owner_ref=journal["runtime_owner_ref"],
                        ),
                        model_request_id=journal["model_request_id"],
                        acquisition_owner_ref=journal[
                            "acquisition_owner_ref"
                        ],
                        acquisition_intent_ref=journal[
                            "acquisition_intent_ref"
                        ],
                        runtime_owner_ref=journal["runtime_owner_ref"],
                    )
                )
                self._validate_benchmark_provider_journal_observation_lineage(
                    journal, observation
                )
            except LearningStageWorkerError:
                raise
            except (OSError, RuntimeError, ValueError, UnicodeError) as error:
                raise LearningStageWorkerError(
                    f"benchmark provider journal is unreadable: {path.name}"
                ) from error
            key = (journal["run_id"], journal["stage"], journal["operation_id"])
            if key in self._benchmark_provider_journals:
                raise LearningStageWorkerError("duplicate benchmark provider journal")
            self._benchmark_provider_journals[key] = journal
        for path in sorted(
            self._result_root.glob("*.benchmark-provider-cleanup.json")
        ):
            journal = self._validate_benchmark_provider_cleanup_journal(
                _read_json_object(path, label="benchmark provider cleanup journal")
            )
            key = (journal["run_id"], journal["stage"], journal["operation_id"])
            if key in self._benchmark_provider_cleanup_journals:
                raise LearningStageWorkerError(
                    "duplicate benchmark provider cleanup journal"
                )
            self._benchmark_provider_cleanup_journals[key] = journal

    def _require_benchmark_root(
        self, supplied: BenchmarkWorkerSupervisionRoot
    ) -> BenchmarkWorkerSupervisionRoot:
        root = _validate_benchmark_supervision_root(
            supplied, expected_journal_root=self._result_root
        )
        if root is not self._benchmark_supervision_root:
            raise LearningStageWorkerError("benchmark supervision root capability does not match Registry")
        return root

    def prepare_benchmark_worker_identity(
        self, *, run_id: str, stage: str, operation_id: str,
        workflow_revision: int, task_kind: str,
        handler_payload_source: dict[str, Any],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        root = self._require_benchmark_root(supervision_root)
        run = _required_text(run_id, "run_id"); stage_value = _required_text(stage, "stage")
        operation = _required_text(operation_id, "operation_id")
        kind = _required_text(task_kind, "task_kind")
        if kind != "vision_observe_screen":
            raise LearningStageWorkerError("benchmark worker task_kind must be vision_observe_screen")
        if isinstance(workflow_revision, bool) or not isinstance(workflow_revision, int) or workflow_revision < 0:
            raise LearningStageWorkerError("benchmark workflow revision is invalid")
        source = _validate_benchmark_source(handler_payload_source)
        key = (run, stage_value, operation)
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=run, stage=stage_value, operation_id=operation
        ):
            with self._lock:
                existing = self._benchmark_reservations.get(key)
                if existing is not None:
                    if (
                        existing["workflow_revision"] == workflow_revision
                        and existing["task_kind"] == kind
                        and existing["handler_payload_source_ref"] == _benchmark_source_ref(source)
                    ):
                        return deepcopy(existing)
                    raise LearningStageWorkerError("benchmark operation already has a different reservation")
                worker_id = uuid4().hex
                body = {
                    "contract_version": _BENCHMARK_RESERVATION_VERSION,
                    "authority_kind": root.authority_kind,
                    "run_id": run, "stage": stage_value, "operation_id": operation,
                    "workflow_revision": workflow_revision, "task_kind": kind,
                    "payload_sha256": source["handler_payload_sha256"],
                    "handler_payload_source": source,
                    "handler_payload_source_ref": _benchmark_source_ref(source),
                    "worker_id": worker_id,
                    "model_request_id": f"learn-worker-{worker_id}",
                    "execution_nonce": uuid4().hex,
                    "supervision_inputs_ref": _benchmark_supervision_inputs_ref(root),
                    "reservation_state": "reserved", "abort_observation_ref": None,
                    "predecessor_content_sha256": source["content_sha256"],
                }
                reservation = seal_immutable(body)
                self._validate_benchmark_reservation_identity_reuse(
                    reservation, key=key
                )
                self._persist_benchmark_reservation(reservation)
                self._benchmark_reservations[key] = reservation
                self._benchmark_reservations_by_ref[reservation["content_sha256"]] = reservation
                return deepcopy(reservation)

    def inspect_prepared_benchmark_worker_identity(
        self, *, run_id: str, stage: str, operation_id: str,
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        root = self._require_benchmark_root(supervision_root)
        key = (_required_text(run_id, "run_id"), _required_text(stage, "stage"), _required_text(operation_id, "operation_id"))
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=key[0], stage=key[1], operation_id=key[2]
        ):
            with self._lock:
                value = self._benchmark_reservations.get(key)
                if value is None:
                    raise LearningStageWorkerError("benchmark reservation not found")
                _validate_benchmark_reservation_supervision(
                    value,
                    supervision_root=root,
                    expected_journal_root=self._result_root,
                )
                return deepcopy(value)

    def attest_benchmark_pre_reservation_absence(
        self,
        *,
        run_id: str,
        stage: str,
        operation_id: str,
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        root = self._require_benchmark_root(supervision_root)
        key = (
            _required_text(run_id, "run_id"),
            _required_text(stage, "stage"),
            _required_text(operation_id, "operation_id"),
        )
        with hold_benchmark_worker_controller(
            supervision_root=root,
            run_id=key[0],
            stage=key[1],
            operation_id=key[2],
        ):
            with self._lock:
                durable_artifact_present = any(
                    _benchmark_operation_artifact_path(
                        self._result_root,
                        key[2],
                        suffix,
                    ).exists()
                    for suffix in _BENCHMARK_OPERATION_STATE_SUFFIXES
                )
                worker_ids = list(self._workers_by_operation.get(key, []))
                matching_records = [
                    worker_id
                    for worker_id, record in self._records.items()
                    if (
                        record.get("run_id"),
                        record.get("stage"),
                        record.get("operation_id"),
                    )
                    == key
                ]
                if (
                    key in self._benchmark_reservations
                    or key in self._benchmark_provider_journals
                    or key in self._benchmark_provider_cleanup_journals
                    or durable_artifact_present
                    or worker_ids
                    or matching_records
                ):
                    raise LearningStageWorkerError(
                        "benchmark pre-reservation operation has durable worker state"
                    )
                return seal_immutable(
                    {
                        "contract_version": (
                            "benchmark_worker_pre_reservation_absence_v1"
                        ),
                        "authority_kind": root.authority_kind,
                        "supervision_inputs_ref": _benchmark_supervision_inputs_ref(
                            root
                        ),
                        "run_id": key[0],
                        "stage": key[1],
                        "operation_id": key[2],
                        "reservation_present": False,
                        "provider_journal_present": False,
                        "provider_cleanup_journal_present": False,
                        "worker_ids": [],
                        "artifact_is_authorization": False,
                        "execute_binding_enabled": False,
                    }
                )

    def inspect_benchmark_worker_launch_owner(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
        reservation_ref: Mapping[str, object],
        expected_operation_anchor: Mapping[str, object],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> Mapping[str, object]:
        root = self._require_benchmark_root(supervision_root)
        worker = _required_text(worker_id, "worker_id")
        run = _required_text(run_id, "run_id")
        stage_value = _required_text(stage, "stage")
        operation = _required_text(operation_id, "operation_id")
        exact_reservation_ref = _benchmark_exact_ref(
            dict(reservation_ref), "benchmark launch owner reservation ref"
        )
        anchor = (
            deepcopy(dict(expected_operation_anchor))
            if isinstance(expected_operation_anchor, Mapping)
            else expected_operation_anchor
        )
        key = (run, stage_value, operation)
        with hold_benchmark_worker_controller(
            supervision_root=root,
            run_id=run,
            stage=stage_value,
            operation_id=operation,
            _abandoned_policy=_BENCHMARK_INSPECTION_ABANDONED_POLICY,
        ):
            with self._lock:
                original = self._benchmark_reservations_by_ref.get(
                    exact_reservation_ref["content_sha256"]
                )
                if original is None:
                    raise LearningStageWorkerError(
                        "benchmark launch owner reservation ref not found"
                    )
                original = self._validate_benchmark_reservation(original)
                if original.get("reservation_state") != "reserved":
                    raise LearningStageWorkerError(
                        "benchmark launch owner reservation ref is not original"
                    )
                if any(
                    original.get(field) != expected
                    for field, expected in (
                        ("run_id", run),
                        ("stage", stage_value),
                        ("operation_id", operation),
                        ("worker_id", worker),
                    )
                ):
                    raise LearningStageWorkerError(
                        "benchmark launch owner identity does not match"
                    )
                validated_anchor = validate_benchmark_worker_operation_anchor_v1(
                    anchor,
                    supervision_root=root,
                    expected_reservation=original,
                )
                current = self._benchmark_reservations.get(key)
                if current is None:
                    raise LearningStageWorkerError(
                        "benchmark launch owner current reservation is missing"
                    )
                current = self._validate_benchmark_reservation(current)
                record = self._records.get(worker)
                return _inspect_benchmark_worker_launch_owner_locked(
                    result_root=self._result_root,
                    original_reservation=original,
                    current_reservation=current,
                    expected_operation_anchor=validated_anchor,
                    supervision_root=root,
                    record=record,
                )

    def _benchmark_by_ref(self, reservation_ref: object) -> dict[str, Any]:
        ref = _benchmark_exact_ref(reservation_ref, "benchmark reservation ref")
        reservation = self._benchmark_reservations_by_ref.get(ref["content_sha256"])
        if reservation is None:
            raise LearningStageWorkerError("benchmark reservation ref not found")
        _validate_benchmark_reservation_supervision(
            reservation,
            supervision_root=self._benchmark_supervision_root,
            expected_journal_root=self._result_root,
        )
        return reservation

    def confirm_prepared_benchmark_worker_anchor(
        self, *, reservation_ref: dict[str, Any], expected_operation_anchor: dict[str, Any],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        root = self._require_benchmark_root(supervision_root)
        initial = self._benchmark_by_ref(reservation_ref)
        key = (initial["run_id"], initial["stage"], initial["operation_id"])
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=key[0], stage=key[1], operation_id=key[2]
        ):
            with self._lock:
                current = self._benchmark_reservations[key]
                validate_benchmark_worker_operation_anchor_v1(
                    expected_operation_anchor, supervision_root=root,
                    expected_reservation=initial,
                )
                confirmation_path = _benchmark_operation_artifact_path(
                    self._result_root,
                    initial["operation_id"],
                    ".benchmark-anchor-confirmation.json",
                )
                if current["reservation_state"] == "anchored":
                    receipt = _compose_benchmark_anchor_confirmation(
                        reservation=initial,
                        anchored_reservation=current,
                        operation_anchor=expected_operation_anchor,
                    )
                    if confirmation_path.exists():
                        persisted = _validate_benchmark_anchor_confirmation(
                            _read_json_object(
                                confirmation_path,
                                label="benchmark anchor confirmation",
                            ),
                            reservation=initial,
                            anchored_reservation=current,
                            operation_anchor=expected_operation_anchor,
                        )
                        if persisted != receipt:
                            raise LearningStageWorkerError(
                                "benchmark anchor confirmation replay does not match"
                            )
                        return persisted
                    _write_json_atomic(confirmation_path, receipt)
                    return deepcopy(receipt)
                if current["reservation_state"] != "reserved":
                    raise LearningStageWorkerError("benchmark reservation cannot be anchored")
                anchored_body = deepcopy(current); anchored_body.pop("content_sha256")
                anchored_body["reservation_state"] = "anchored"
                anchored_body["predecessor_content_sha256"] = current["content_sha256"]
                anchored = seal_immutable(anchored_body)
                receipt = _compose_benchmark_anchor_confirmation(
                    reservation=current,
                    anchored_reservation=anchored,
                    operation_anchor=expected_operation_anchor,
                )
                self._persist_benchmark_reservation(anchored)
                _write_json_atomic(confirmation_path, receipt)
                self._benchmark_reservations[key] = anchored
                self._benchmark_reservations_by_ref[anchored["content_sha256"]] = anchored
                return deepcopy(receipt)

    def prepare_benchmark_provider_acquisition(
        self,
        *,
        reservation_ref: Mapping[str, object],
        runtime_owner_ref: Mapping[str, object],
    ) -> dict[str, Any]:
        supplied_ref = _benchmark_exact_ref(
            reservation_ref, "benchmark provider reservation ref"
        )
        with self._lock:
            reservation = self._benchmark_reservations_by_ref.get(
                supplied_ref["content_sha256"]
            )
            root = self._benchmark_supervision_root
            if reservation is None:
                raise LearningStageWorkerError(
                    "benchmark provider reservation ref not found"
                )
            if root is None:
                raise LearningStageWorkerError(
                    "benchmark provider supervision root is missing"
                )
            _validate_benchmark_reservation_supervision(
                reservation,
                supervision_root=root,
                expected_journal_root=self._result_root,
            )
            key = (
                reservation["run_id"],
                reservation["stage"],
                reservation["operation_id"],
            )
        with hold_benchmark_worker_controller(
            supervision_root=root,
            run_id=key[0],
            stage=key[1],
            operation_id=key[2],
        ):
            return self._prepare_benchmark_provider_acquisition_under_controller(
                reservation_ref=reservation_ref,
                runtime_owner_ref=runtime_owner_ref,
            )

    def _prepare_benchmark_provider_acquisition_under_controller(
        self,
        *,
        reservation_ref: Mapping[str, object],
        runtime_owner_ref: Mapping[str, object],
    ) -> dict[str, Any]:
        supplied_ref = _benchmark_exact_ref(
            reservation_ref, "benchmark provider reservation ref"
        )
        with self._lock:
            reservation = self._benchmark_reservations_by_ref.get(
                supplied_ref["content_sha256"]
            )
            if reservation is None:
                raise LearningStageWorkerError(
                    "benchmark provider reservation ref not found"
                )
            key = (
                reservation["run_id"],
                reservation["stage"],
                reservation["operation_id"],
            )
            current = self._benchmark_reservations.get(key)
            if (
                current != reservation
                or current.get("reservation_state") != "anchored"
                or self._benchmark_supervision_root is None
                or current.get("authority_kind")
                != self._benchmark_supervision_root.authority_kind
            ):
                raise LearningStageWorkerError(
                    "benchmark provider reservation must be the current anchored reservation"
                )
            runtime_owner = self._validate_benchmark_provider_runtime_owner(
                runtime_owner_ref, anchored=current
            )
            snapshot_ref = current["content_sha256"]
            existing = deepcopy(self._benchmark_provider_journals.get(key))

        try:
            production_owner = self._validate_benchmark_provider_owner(
                prepare_qwen_model_request_acquisition_owner(
                    current["model_request_id"],
                    runtime_owner_ref=runtime_owner,
                ),
                model_request_id=current["model_request_id"],
                runtime_owner=runtime_owner,
            )
            production_observation = (
                self._validate_benchmark_provider_acquisition_observation(
                    observe_qwen_model_request_acquisition(
                        current["model_request_id"],
                        acquisition_intent_ref=production_owner[
                            "acquisition_intent_ref"
                        ],
                        runtime_owner_ref=runtime_owner,
                    ),
                    model_request_id=production_owner["model_request_id"],
                    acquisition_owner_ref={
                        "content_sha256": production_owner["content_sha256"]
                    },
                    acquisition_intent_ref=production_owner[
                        "acquisition_intent_ref"
                    ],
                    runtime_owner_ref=production_owner["runtime_owner_ref"],
                    expected_state="prepared_never_materialized",
                    expected_revision=0,
                )
            )
        except LearningStageWorkerError:
            raise
        except (OSError, RuntimeError, ValueError, UnicodeError) as error:
            raise LearningStageWorkerError(
                "benchmark provider production acquisition preparation failed"
            ) from error

        owner_ref = {"content_sha256": production_owner["content_sha256"]}
        candidate = seal_immutable(
            {
                "contract_version": _BENCHMARK_PROVIDER_JOURNAL_VERSION,
                **{
                    field: deepcopy(current[field])
                    for field in (
                        "authority_kind",
                        "run_id",
                        "stage",
                        "operation_id",
                        "worker_id",
                        "model_request_id",
                        "payload_sha256",
                    )
                },
                "reservation_ref": {"content_sha256": snapshot_ref},
                "runtime_owner_ref": deepcopy(runtime_owner),
                "acquisition_owner_ref": owner_ref,
                "acquisition_intent_ref": deepcopy(
                    production_owner["acquisition_intent_ref"]
                ),
                "prepared_acquisition_observation_ref": {
                    "content_sha256": production_observation["content_sha256"]
                },
                "prepared_materialization_ledger_ref": deepcopy(
                    production_observation[
                        "prepared_materialization_ledger_ref"
                    ]
                ),
                "acquisition_observation_ref": {
                    "content_sha256": production_observation["content_sha256"]
                },
                "materialization_ledger_ref": deepcopy(
                    production_observation["materialization_ledger_ref"]
                ),
            }
        )
        if existing is not None and existing != candidate:
            raise LearningStageWorkerError(
                "benchmark provider acquisition replay conflicts with Registry journal"
            )
        with self._lock:
            current_after = self._benchmark_reservations.get(key)
            if (
                current_after is None
                or current_after.get("content_sha256") != snapshot_ref
                or current_after.get("reservation_state") != "anchored"
            ):
                raise LearningStageWorkerError(
                    "benchmark provider acquisition Registry snapshot changed"
                )
            persisted = self._benchmark_provider_journals.get(key)
            if persisted is not None:
                if persisted != candidate:
                    raise LearningStageWorkerError(
                        "benchmark provider acquisition Registry journal changed"
                    )
                return self._benchmark_provider_journal_projection(persisted)
            path = _benchmark_operation_artifact_path(
                self._result_root,
                current["operation_id"],
                ".benchmark-provider.json",
            )
            if path.exists():
                persisted = self._validate_benchmark_provider_journal(
                    _read_json_object(path, label="benchmark provider journal")
                )
                if persisted != candidate:
                    raise LearningStageWorkerError(
                        "benchmark provider acquisition Registry journal conflicts"
                    )
            else:
                _write_json_create_only(path, candidate)
                persisted = candidate
            self._benchmark_provider_journals[key] = deepcopy(persisted)
            return self._benchmark_provider_journal_projection(persisted)

    @staticmethod
    def _validate_benchmark_provider_cleanup_receipt(
        value: object, *, provider_journal: Mapping[str, object]
    ) -> dict[str, Any] | None:
        if not isinstance(value, Mapping):
            return None
        receipt = deepcopy(dict(value))
        if receipt.get("status") == "cleanup_pending":
            return None
        receipt_fields = {
            "contract_version",
            "outcome",
            "model_request_id",
            "acquisition_intent_ref",
            "runtime_owner_ref",
            "lease_ref",
            "profile_ref",
            "server_process_identity",
            "socket_ref",
            "job_scope_ref",
            "finalization_token",
            "lease_state_ref",
            "owner_tombstone_ref",
            "release_reason",
            "termination_observation_ref",
            "scope_stable_zero_ref",
            "listener_stable_zero_ref",
            "no_active_lease_observation_ref",
            "no_owned_runtime_observation_ref",
            "content_sha256",
        }
        if (
            set(receipt) != receipt_fields
            or receipt.get("contract_version")
            != "qwen_model_request_cleanup_receipt_v1"
            or receipt.get("outcome")
            not in {"verified_not_acquired", "verified_exact_process_exited"}
            or receipt.get("model_request_id")
            != provider_journal["model_request_id"]
            or receipt.get("acquisition_intent_ref")
            != provider_journal["acquisition_intent_ref"]
            or receipt.get("runtime_owner_ref")
            != provider_journal["runtime_owner_ref"]
            or content_sha256(receipt) != receipt.get("content_sha256")
        ):
            return None
        for field in (
            "acquisition_intent_ref",
            "lease_ref",
            "profile_ref",
            "socket_ref",
            "job_scope_ref",
            "lease_state_ref",
            "owner_tombstone_ref",
            "termination_observation_ref",
            "scope_stable_zero_ref",
            "listener_stable_zero_ref",
            "no_active_lease_observation_ref",
            "no_owned_runtime_observation_ref",
        ):
            ref = receipt.get(field)
            if ref is not None:
                try:
                    _benchmark_exact_ref(ref, f"benchmark provider receipt {field}")
                except LearningStageWorkerError:
                    return None
        return receipt

    @staticmethod
    def _benchmark_provider_cleanup_projection(
        provider_journal: Mapping[str, object],
        *,
        receipt: Mapping[str, object] | None,
    ) -> dict[str, Any]:
        return seal_immutable(
            {
                "contract_version": "benchmark_provider_cleanup_ref_v1",
                "status": (
                    "cleanup_verified" if receipt is not None else "cleanup_pending"
                ),
                "outcome": (
                    receipt["outcome"] if receipt is not None else "indeterminate"
                ),
                **{
                    field: deepcopy(provider_journal[field])
                    for field in (
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
                    )
                },
                "runtime_owner_ref": {
                    "content_sha256": provider_journal["runtime_owner_ref"][
                        "content_sha256"
                    ]
                },
                "cleanup_receipt_ref": (
                    {"content_sha256": receipt["content_sha256"]}
                    if receipt is not None
                    else None
                ),
            }
        )

    def _validate_benchmark_provider_cleanup_journal(
        self, value: object
    ) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise LearningStageWorkerError(
                "benchmark provider cleanup journal is invalid"
            )
        journal = deepcopy(dict(value))
        if set(journal) != {
            "contract_version",
            "authority_kind",
            "run_id",
            "stage",
            "operation_id",
            "worker_id",
            "model_request_id",
            "payload_sha256",
            "reservation_ref",
            "runtime_owner_ref",
            "acquisition_owner_ref",
            "acquisition_intent_ref",
            "cleanup_receipt_ref",
            "content_sha256",
        } or journal.get("contract_version") != _BENCHMARK_PROVIDER_CLEANUP_JOURNAL_VERSION:
            raise LearningStageWorkerError(
                "benchmark provider cleanup journal is invalid"
            )
        if content_sha256(journal) != journal.get("content_sha256"):
            raise LearningStageWorkerError(
                "benchmark provider cleanup journal seal is invalid"
            )
        key = (
            journal.get("run_id"),
            journal.get("stage"),
            journal.get("operation_id"),
        )
        provider = self._benchmark_provider_journals.get(key)
        if provider is None:
            raise LearningStageWorkerError(
                "benchmark provider cleanup owner journal is missing"
            )
        expected = {
            field: deepcopy(provider[field])
            for field in (
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
            )
        }
        expected["runtime_owner_ref"] = {
            "content_sha256": provider["runtime_owner_ref"]["content_sha256"]
        }
        if (
            any(
                journal.get(field) != expected_value
                for field, expected_value in expected.items()
            )
        ):
            raise LearningStageWorkerError(
                "benchmark provider cleanup journal identity does not match"
            )
        _benchmark_exact_ref(
            journal.get("cleanup_receipt_ref"),
            "benchmark provider cleanup receipt ref",
        )
        return journal

    def _validate_benchmark_provider_cancelled_before_launch(
        self,
        *,
        current: Mapping[str, object],
        provider_journal: Mapping[str, object],
    ) -> dict[str, Any]:
        reservation = self._validate_benchmark_reservation(dict(current))
        root = self._benchmark_supervision_root
        if root is None or reservation.get("reservation_state") != "cancelled_before_launch":
            raise LearningStageWorkerError(
                "benchmark provider cancellation authority is missing"
            )
        persisted = self._validate_benchmark_reservation(
            _read_json_object(
                self._benchmark_reservation_path(reservation["operation_id"]),
                label="benchmark provider cancelled reservation",
            )
        )
        if persisted != reservation:
            raise LearningStageWorkerError(
                "benchmark provider cancelled reservation is not durable"
            )
        original_body = deepcopy(reservation)
        original_body.pop("content_sha256")
        original_body["reservation_state"] = "reserved"
        original_body["abort_observation_ref"] = None
        original_body["predecessor_content_sha256"] = reservation[
            "handler_payload_source"
        ]["content_sha256"]
        original = seal_immutable(original_body)
        if self._benchmark_reservations_by_ref.get(
            original["content_sha256"]
        ) != original:
            raise LearningStageWorkerError(
                "benchmark provider original reservation lineage is missing"
            )
        anchored = _benchmark_transitioned_reservation(original, "anchored")
        if provider_journal.get("reservation_ref") != {
            "content_sha256": anchored["content_sha256"]
        }:
            raise LearningStageWorkerError(
                "benchmark provider anchored reservation lineage does not match"
            )
        source = original["handler_payload_source"]
        operation_anchor = compose_benchmark_worker_operation_anchor_v1(
            supervision_root=root,
            reservation=original,
            handler_payload_source=source,
            window_binding_ref=source["window_binding_ref"],
            capture_ref=source["capture_ref"],
            predecessor_content_sha256=None,
        )
        receipt_path = self._result_root / (
            f"{reservation['worker_id']}.benchmark-cleanup.json"
        )
        receipt = _validate_benchmark_cleanup_receipt(
            _read_json_object(
                receipt_path,
                label="benchmark provider B1 cleanup receipt",
            ),
            result_root=self._result_root,
            worker_id=reservation["worker_id"],
            run_id=reservation["run_id"],
            stage=reservation["stage"],
            operation_id=reservation["operation_id"],
            operation_anchor=operation_anchor,
            original_reservation=original,
            current_reservation=reservation,
            supervision_root=root,
        )
        if (
            receipt.get("outcome") != "verified_not_launched"
            or receipt.get("reservation_abort_ref")
            != reservation.get("abort_observation_ref")
        ):
            raise LearningStageWorkerError(
                "benchmark provider B1 cancellation receipt is invalid"
            )
        return receipt

    def reconcile_benchmark_provider_cleanup(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
    ) -> dict[str, Any]:
        worker = _required_text(worker_id, "worker_id")
        run = _required_text(run_id, "run_id")
        stage_value = _required_text(stage, "stage")
        operation = _required_text(operation_id, "operation_id")
        root = self._benchmark_supervision_root
        if root is None:
            raise LearningStageWorkerError(
                "benchmark provider supervision root is missing"
            )
        with self._lock:
            current = self._benchmark_reservations.get(
                (run, stage_value, operation)
            )
            if current is None:
                raise LearningStageWorkerError(
                    "benchmark provider cleanup identity does not match"
                )
            _validate_benchmark_reservation_supervision(
                current,
                supervision_root=root,
                expected_journal_root=self._result_root,
            )
        with hold_benchmark_worker_controller(
            supervision_root=root,
            run_id=run,
            stage=stage_value,
            operation_id=operation,
        ):
            return self._reconcile_benchmark_provider_cleanup_under_controller(
                worker_id=worker,
                run_id=run,
                stage=stage_value,
                operation_id=operation,
            )

    def _reconcile_benchmark_provider_cleanup_under_controller(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
    ) -> dict[str, Any]:
        worker = _required_text(worker_id, "worker_id")
        run = _required_text(run_id, "run_id")
        stage_value = _required_text(stage, "stage")
        operation = _required_text(operation_id, "operation_id")
        key = (run, stage_value, operation)
        with self._lock:
            current = self._benchmark_reservations.get(key)
            provider = self._benchmark_provider_journals.get(key)
            if (
                current is None
                or provider is None
                or current.get("worker_id") != worker
                or provider.get("worker_id") != worker
                or provider.get("model_request_id")
                != current.get("model_request_id")
            ):
                raise LearningStageWorkerError(
                    "benchmark provider cleanup identity does not match"
                )
            anchored = self._benchmark_anchored_reservation(current)
            if provider.get("reservation_ref") != {
                "content_sha256": anchored["content_sha256"]
            }:
                raise LearningStageWorkerError(
                    "benchmark provider cleanup reservation lineage does not match"
                )
            provider = self._validate_benchmark_provider_journal(provider)
            snapshot_ref = current["content_sha256"]
            cancellation_candidate = (
                current.get("reservation_state") == "cancelled_before_launch"
            )

        try:
            acquisition_observation = (
                self._validate_benchmark_provider_acquisition_observation(
                    observe_qwen_model_request_acquisition(
                        provider["model_request_id"],
                        acquisition_intent_ref=provider[
                            "acquisition_intent_ref"
                        ],
                        runtime_owner_ref=provider["runtime_owner_ref"],
                    ),
                    model_request_id=provider["model_request_id"],
                    acquisition_owner_ref=provider["acquisition_owner_ref"],
                    acquisition_intent_ref=provider["acquisition_intent_ref"],
                    runtime_owner_ref=provider["runtime_owner_ref"],
                )
            )
            self._validate_benchmark_provider_journal_observation_lineage(
                provider, acquisition_observation
            )
        except (
            LearningStageWorkerError,
            OSError,
            RuntimeError,
            ValueError,
            UnicodeError,
        ):
            return self._benchmark_provider_cleanup_projection(
                provider, receipt=None
            )
        cancellation_valid = False
        if cancellation_candidate:
            try:
                self._validate_benchmark_provider_cancelled_before_launch(
                    current=current,
                    provider_journal=provider,
                )
                cancellation_valid = True
            except LearningStageWorkerError:
                return self._benchmark_provider_cleanup_projection(
                    provider, receipt=None
                )
        with self._lock:
            current_before_side_effect = self._benchmark_reservations.get(key)
            if (
                current_before_side_effect is None
                or current_before_side_effect.get("content_sha256")
                != snapshot_ref
            ):
                return self._benchmark_provider_cleanup_projection(
                    provider, receipt=None
                )
            _validate_benchmark_reservation_supervision(
                current_before_side_effect,
                supervision_root=self._benchmark_supervision_root,
                expected_journal_root=self._result_root,
            )
        abort_allowed = (
            cancellation_valid
            and acquisition_observation["materialization_state"]
            == "prepared_never_materialized"
            and acquisition_observation["materialization_revision"] == 0
        )
        if abort_allowed:
            try:
                abort_result = abort_qwen_model_request_acquisition(
                    provider["model_request_id"],
                    acquisition_intent_ref=provider["acquisition_intent_ref"],
                    runtime_owner_ref=provider["runtime_owner_ref"],
                    reason="benchmark_operation_cancelled_before_launch",
                )
                if (
                    not isinstance(abort_result, Mapping)
                    or abort_result.get("contract_version")
                    != "benchmark_provider_acquisition_abort_v1"
                    or abort_result.get("model_request_id")
                    != provider["model_request_id"]
                    or abort_result.get("acquisition_intent_ref")
                    != provider["acquisition_intent_ref"]
                    or abort_result.get("runtime_owner_ref")
                    != provider["runtime_owner_ref"]
                    or abort_result.get("owner_state") != "acquisition_aborted"
                    or content_sha256(abort_result)
                    != abort_result.get("content_sha256")
                ):
                    raise LearningStageWorkerError(
                        "benchmark provider production abort is invalid"
                    )
            except LearningStageWorkerError:
                raise
            except (OSError, RuntimeError, ValueError, UnicodeError):
                return self._benchmark_provider_cleanup_projection(
                    provider, receipt=None
                )
            try:
                acquisition_observation = (
                    self._validate_benchmark_provider_acquisition_observation(
                        observe_qwen_model_request_acquisition(
                            provider["model_request_id"],
                            acquisition_intent_ref=provider[
                                "acquisition_intent_ref"
                            ],
                            runtime_owner_ref=provider["runtime_owner_ref"],
                        ),
                        model_request_id=provider["model_request_id"],
                        acquisition_owner_ref=provider[
                            "acquisition_owner_ref"
                        ],
                        acquisition_intent_ref=provider[
                            "acquisition_intent_ref"
                        ],
                        runtime_owner_ref=provider["runtime_owner_ref"],
                        expected_state="aborted_never_materialized",
                        expected_revision=1,
                    )
                )
                self._validate_benchmark_provider_journal_observation_lineage(
                    provider, acquisition_observation
                )
            except (
                LearningStageWorkerError,
                OSError,
                RuntimeError,
                ValueError,
                UnicodeError,
            ):
                return self._benchmark_provider_cleanup_projection(
                    provider, receipt=None
                )
        current_provider = self._benchmark_provider_journal_with_observation(
            provider,
            acquisition_observation,
        )
        with self._lock:
            current_after_observation = self._benchmark_reservations.get(key)
            if (
                current_after_observation is None
                or current_after_observation.get("content_sha256")
                != snapshot_ref
            ):
                return self._benchmark_provider_cleanup_projection(
                    provider, receipt=None
                )
            durable_provider = self._benchmark_provider_journals.get(key)
            if durable_provider != provider:
                return self._benchmark_provider_cleanup_projection(
                    provider, receipt=None
                )
            if current_provider != provider:
                _write_json_atomic(
                    _benchmark_operation_artifact_path(
                        self._result_root,
                        operation,
                        ".benchmark-provider.json",
                    ),
                    current_provider,
                )
                self._benchmark_provider_journals[key] = deepcopy(
                    current_provider
                )
                provider = current_provider
        try:
            observed = observe_qwen_model_request_cleanup(
                provider["model_request_id"]
            )
        except (OSError, RuntimeError, ValueError, UnicodeError):
            observed = None
        receipt = self._validate_benchmark_provider_cleanup_receipt(
            observed, provider_journal=provider
        )
        if receipt is not None and (
            (
                receipt["outcome"] == "verified_not_acquired"
                and acquisition_observation["materialization_state"]
                != "aborted_never_materialized"
            )
            or (
                receipt["outcome"] == "verified_exact_process_exited"
                and acquisition_observation["materialization_state"]
                != "materialization_possible"
            )
        ):
            receipt = None

        with self._lock:
            current_after = self._benchmark_reservations.get(key)
            if (
                current_after is None
                or current_after.get("content_sha256") != snapshot_ref
            ):
                return self._benchmark_provider_cleanup_projection(
                    provider, receipt=None
                )
            if receipt is None:
                return self._benchmark_provider_cleanup_projection(
                    provider, receipt=None
                )
            candidate = seal_immutable(
                {
                    "contract_version": _BENCHMARK_PROVIDER_CLEANUP_JOURNAL_VERSION,
                    **{
                        field: deepcopy(provider[field])
                        for field in (
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
                        )
                    },
                    "runtime_owner_ref": {
                        "content_sha256": provider["runtime_owner_ref"][
                            "content_sha256"
                        ]
                    },
                    "cleanup_receipt_ref": {
                        "content_sha256": receipt["content_sha256"]
                    },
                }
            )
            existing = self._benchmark_provider_cleanup_journals.get(key)
            if existing is not None:
                if existing != candidate:
                    return self._benchmark_provider_cleanup_projection(
                        provider, receipt=None
                    )
                return self._benchmark_provider_cleanup_projection(
                    provider, receipt=receipt
                )
            path = _benchmark_operation_artifact_path(
                self._result_root,
                operation,
                ".benchmark-provider-cleanup.json",
            )
            if path.exists():
                persisted = self._validate_benchmark_provider_cleanup_journal(
                    _read_json_object(
                        path, label="benchmark provider cleanup journal"
                    )
                )
                if persisted != candidate:
                    return self._benchmark_provider_cleanup_projection(
                        provider, receipt=None
                    )
            else:
                _write_json_create_only(path, candidate)
                persisted = candidate
            self._benchmark_provider_cleanup_journals[key] = deepcopy(persisted)
            return self._benchmark_provider_cleanup_projection(
                provider, receipt=receipt
            )

    def launch_prepared_benchmark_worker(
        self, *, reservation_ref: dict[str, Any], expected_operation_anchor: dict[str, Any],
        authoritative_payload: dict[str, Any], supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        root = self._require_benchmark_root(supervision_root)
        reservation = self._benchmark_by_ref(reservation_ref)
        key = (reservation["run_id"], reservation["stage"], reservation["operation_id"])
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=key[0], stage=key[1], operation_id=key[2]
        ):
            with self._lock:
                current = self._benchmark_reservations[key]
                if current["reservation_state"] != "anchored":
                    raise LearningStageWorkerError("benchmark reservation must be anchored before launch")
                original = self._benchmark_reservations_by_ref.get(
                    expected_operation_anchor.get("reservation_ref", {}).get("content_sha256", "")
                )
                if original is None:
                    raise LearningStageWorkerError("benchmark anchor reservation ref is invalid")
                validate_benchmark_worker_operation_anchor_v1(
                    expected_operation_anchor, supervision_root=root,
                    expected_reservation=original,
                )
                if not isinstance(authoritative_payload, dict) or _payload_sha256(authoritative_payload) != current["payload_sha256"]:
                    raise LearningStageWorkerError("benchmark authoritative payload identity mismatch")
                # 后续 gate/Job 启动只允许走专用实现；此处先保持在所有验证之后。
                return self._launch_validated_benchmark_worker(
                    current=current, anchor=expected_operation_anchor,
                    authoritative_payload=deepcopy(authoritative_payload), root=root,
                )

    def recover_launching_benchmark_worker(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
        reservation_ref: Mapping[str, object],
        expected_operation_anchor: Mapping[str, object],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        """在同一 B1 reservation 下恢复已分配但尚未持久化完成的 launch。"""

        import win32api
        import win32event
        from app.learn.hybrid.windows_process_scope import WindowsProcessScope

        root = self._require_benchmark_root(supervision_root)
        worker = _required_text(worker_id, "worker_id")
        run = _required_text(run_id, "run_id")
        stage_value = _required_text(stage, "stage")
        operation = _required_text(operation_id, "operation_id")
        exact_reservation_ref = _benchmark_exact_ref(
            dict(reservation_ref), "benchmark launch recovery reservation ref"
        )
        key = (run, stage_value, operation)
        with hold_benchmark_worker_controller(
            supervision_root=root,
            run_id=key[0],
            stage=key[1],
            operation_id=key[2],
        ):
            with self._lock:
                original = self._benchmark_reservations_by_ref.get(
                    exact_reservation_ref["content_sha256"]
                )
                if original is None or any(
                    original.get(field) != expected
                    for field, expected in (
                        ("worker_id", worker),
                        ("run_id", run),
                        ("stage", stage_value),
                        ("operation_id", operation),
                    )
                ):
                    raise LearningStageWorkerError(
                        "benchmark launch recovery identity does not match"
                    )
                current = self._benchmark_reservations.get(key)
                if current is None:
                    raise LearningStageWorkerError(
                        "benchmark launch recovery reservation is missing"
                    )
                anchor = validate_benchmark_worker_operation_anchor_v1(
                    deepcopy(dict(expected_operation_anchor)),
                    supervision_root=root,
                    expected_reservation=original,
                )
                inspection = _inspect_benchmark_worker_launch_owner_locked(
                    result_root=self._result_root,
                    original_reservation=original,
                    current_reservation=current,
                    expected_operation_anchor=anchor,
                    supervision_root=root,
                    record=self._records.get(original["worker_id"]),
                )
                if inspection["reservation_state"] == "launched":
                    if (
                        inspection["owner_phase"] != "gate_released"
                        or inspection["assignment_state"] != "proven"
                    ):
                        raise LearningStageWorkerError(
                            "benchmark launched recovery owner is invalid"
                        )
                    return self._benchmark_launch_recovery_projection(
                        inspection=inspection,
                        outcome="recovered_gate_released",
                        gate_release_performed=False,
                    )
                if inspection["reservation_state"] != "launching":
                    raise LearningStageWorkerError(
                        "benchmark launch recovery requires launching reservation"
                    )

                owner_phase = inspection["owner_phase"]
                if owner_phase not in {"assignment_proven", "gate_released"}:
                    return self._cleanup_unrecoverable_benchmark_launch_locked(
                        original=original,
                        current=current,
                        anchor=anchor,
                        inspection=inspection,
                        root=root,
                    )

                process_identity = _validate_exact_benchmark_process_identity(
                    inspection["process_identity"],
                    label="launch recovery worker",
                )
                if self._benchmark_process_incarnation_absent(process_identity):
                    return self._cleanup_unrecoverable_benchmark_launch_locked(
                        original=original,
                        current=current,
                        anchor=anchor,
                        inspection=inspection,
                        root=root,
                    )
                scope = None
                event_handle = None
                try:
                    scope = WindowsProcessScope(inspection["scope_name"], create=False)
                    if (
                        scope.pids() != [process_identity["pid"]]
                        or scope.job_policy()
                        != {
                            "kill_on_job_close": True,
                            "breakaway_ok": False,
                            "silent_breakaway_ok": False,
                            "owner_handle_authority": "registry_parent",
                        }
                    ):
                        raise LearningStageWorkerError(
                            "benchmark launch recovery Job membership is invalid"
                        )
                    event_name = _benchmark_worker_gate_event_name(
                        inspection["scope_name"]
                    )
                    event_handle = win32event.OpenEvent(
                        win32event.EVENT_MODIFY_STATE | 0x00100000,
                        False,
                        event_name,
                    )
                    gate_wait = win32event.WaitForSingleObject(event_handle, 0)
                    if owner_phase == "assignment_proven":
                        if gate_wait != win32event.WAIT_TIMEOUT:
                            raise LearningStageWorkerError(
                                "benchmark launch recovery closed gate is invalid"
                            )
                        win32event.SetEvent(event_handle)
                        owner = _read_json_object(
                            self._result_root
                            / f"{original['worker_id']}.benchmark-owner.json",
                            label="benchmark launch recovery owner",
                        )
                        supervision = compose_benchmark_worker_supervision_v1(
                            supervision_root=root,
                            reservation=original,
                            expected_operation_anchor=anchor,
                            supervisor_process_identity=owner[
                                "supervisor_process_identity"
                            ],
                            startup_gate_timeout_ms=15_000,
                        )
                        released = self._benchmark_owner_journal(
                            current=current,
                            anchor=anchor,
                            supervision=supervision,
                            scope_name=inspection["scope_name"],
                            supervisor_identity=owner[
                                "supervisor_process_identity"
                            ],
                            phase="gate_released",
                            process_identity=process_identity,
                            beacon_ref=owner["beacon_ref"],
                            assignment_ref=owner["assignment_observation_ref"],
                            gate_state="released",
                            predecessor=owner["content_sha256"],
                        )
                        _write_json_atomic(
                            self._result_root
                            / f"{original['worker_id']}.benchmark-owner.json",
                            released,
                        )
                        gate_release_performed = True
                    else:
                        if gate_wait != win32event.WAIT_OBJECT_0:
                            raise LearningStageWorkerError(
                                "benchmark launch recovery released gate is invalid"
                            )
                        gate_release_performed = False

                    launched = self._transition_benchmark_reservation(
                        current, "launched"
                    )
                    self._persist_benchmark_reservation(launched)
                    self._benchmark_reservations[key] = launched
                    self._benchmark_reservations_by_ref[
                        launched["content_sha256"]
                    ] = launched
                    process = _RecoveredBenchmarkProcess(
                        process_identity=process_identity
                    )
                    record = self._install_recovered_benchmark_record(
                        original=original,
                        reservation=launched,
                        anchor=anchor,
                        scope=scope,
                        event_handle=event_handle,
                        process=process,
                    )
                    scope = None
                    event_handle = None
                    inspection = _inspect_benchmark_worker_launch_owner_locked(
                        result_root=self._result_root,
                        original_reservation=original,
                        current_reservation=launched,
                        expected_operation_anchor=anchor,
                        supervision_root=root,
                        record=record,
                    )
                    return self._benchmark_launch_recovery_projection(
                        inspection=inspection,
                        outcome="recovered_gate_released",
                        gate_release_performed=gate_release_performed,
                    )
                except BaseException:
                    if event_handle is not None:
                        win32api.CloseHandle(event_handle)
                    if scope is not None:
                        scope.close()
                    return self._cleanup_unrecoverable_benchmark_launch_locked(
                        original=original,
                        current=current,
                        anchor=anchor,
                        inspection=inspection,
                        root=root,
                    )

    @staticmethod
    def _benchmark_launch_recovery_projection(
        *,
        inspection: Mapping[str, object],
        outcome: str,
        gate_release_performed: bool,
        cleanup_ref: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        return seal_immutable(
            {
                "contract_version": "benchmark_worker_launch_recovery_v1",
                "outcome": outcome,
                **{
                    field: deepcopy(inspection[field])
                    for field in (
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
                    )
                },
                "gate_release_performed": gate_release_performed,
                "spawn_retry": False,
                "cleanup_ref": deepcopy(dict(cleanup_ref))
                if isinstance(cleanup_ref, Mapping)
                else None,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )

    def _install_recovered_benchmark_record(
        self,
        *,
        original: dict[str, Any],
        reservation: dict[str, Any],
        anchor: dict[str, Any],
        scope: Any,
        event_handle: Any,
        process: Any,
    ) -> dict[str, Any]:
        owner_path = self._result_root / f"{original['worker_id']}.benchmark-owner.json"
        owner = _read_json_object(owner_path, label="benchmark recovered owner")
        supervision = compose_benchmark_worker_supervision_v1(
            supervision_root=self._benchmark_supervision_root,
            reservation=original,
            expected_operation_anchor=anchor,
            supervisor_process_identity=owner["supervisor_process_identity"],
            startup_gate_timeout_ms=15_000,
        )
        record = {
            "contract_version": LEARNING_STAGE_WORKER_CONTRACT_VERSION,
            **{
                field: original[field]
                for field in (
                    "worker_id",
                    "run_id",
                    "stage",
                    "operation_id",
                    "task_kind",
                    "model_request_id",
                    "payload_sha256",
                )
            },
            "status": "running",
            "started_at": _utc_now_iso(),
            "finished_at": None,
            "result_path": str(
                self._result_root / f"{original['worker_id']}.result.json"
            ),
            "journal_path": str(
                self._result_root / f"{original['worker_id']}.worker.json"
            ),
            "process": process,
            "payload": {},
            "cancellation_event": None,
            "completion_event": None,
            "provider_scope": None,
            "provider_scope_name": None,
            "recovered_from_journal": False,
            "benchmark_owner_path": str(owner_path),
            "benchmark_beacon_path": str(
                self._result_root / f"{original['worker_id']}.benchmark-beacon.json"
            ),
            "benchmark_event_handle": event_handle,
            "benchmark_scope": scope,
            "benchmark_anchor": deepcopy(anchor),
            "benchmark_supervision": supervision,
            "benchmark_reservation": reservation,
        }
        key = (original["run_id"], original["stage"], original["operation_id"])
        self._persist_record_journal(record)
        self._records[original["worker_id"]] = record
        self._active_by_operation[key] = original["worker_id"]
        workers = self._workers_by_operation.setdefault(key, [])
        if original["worker_id"] not in workers:
            workers.append(original["worker_id"])
        self._workers_by_invocation[
            (*key, original["task_kind"], original["payload_sha256"])
        ] = original["worker_id"]
        return record

    def _cleanup_unrecoverable_benchmark_launch_locked(
        self,
        *,
        original: dict[str, Any],
        current: dict[str, Any],
        anchor: dict[str, Any],
        inspection: Mapping[str, object],
        root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        """清理不能精确恢复的 launching cut，并持久化可重放的 SAFE_STOP 父证据。"""

        import win32api
        import win32event
        from app.learn.hybrid.windows_process_scope import WindowsProcessScope

        worker = original["worker_id"]
        cleanup_path = self._result_root / f"{worker}.benchmark-launch-recovery-cleanup.json"
        if cleanup_path.exists():
            cleanup = _read_json_object(
                cleanup_path, label="benchmark launch recovery cleanup"
            )
            _validate_benchmark_launch_recovery_cleanup(
                cleanup,
                original=original,
                current=current,
                anchor=anchor,
                inspection=inspection,
            )
            self._retest_benchmark_launch_recovery_absence(cleanup)
            return self._benchmark_launch_recovery_projection(
                inspection=inspection,
                outcome="verified_cleanup_safe_stop",
                gate_release_performed=False,
                cleanup_ref={"content_sha256": cleanup["content_sha256"]},
            )

        process_identity = inspection.get("process_identity")
        beacon_path = self._result_root / f"{worker}.benchmark-beacon.json"
        if process_identity is None and beacon_path.exists():
            beacon = _read_json_object(
                beacon_path, label="benchmark launch recovery beacon"
            )
            expected_beacon = seal_immutable(
                {
                    "contract_version": "benchmark_worker_identity_beacon_v1",
                    "worker_id": worker,
                    "operation_anchor_ref": deepcopy(
                        inspection["operation_anchor_ref"]
                    ),
                    "process_identity": deepcopy(beacon.get("process_identity")),
                    "predecessor_content_sha256": inspection["supervision_ref"][
                        "content_sha256"
                    ],
                }
            )
            if beacon != expected_beacon:
                raise LearningStageWorkerError(
                    "benchmark launch recovery beacon is invalid"
                )
            process_identity = _validate_exact_benchmark_process_identity(
                beacon["process_identity"], label="launch recovery beacon worker"
            )
        termination = None
        if process_identity is not None:
            termination = self._terminate_exact_benchmark_process(process_identity)

        scope_name = inspection.get("scope_name")
        if not isinstance(scope_name, str):
            from app.learn.hybrid.windows_process_scope import (
                benchmark_worker_scope_name_v1,
            )

            scope_name = benchmark_worker_scope_name_v1(
                authority_kind=original["authority_kind"],
                run_id=original["run_id"],
                stage=original["stage"],
                operation_id=original["operation_id"],
                worker_id=worker,
                payload_sha256=original["payload_sha256"],
                execution_nonce=original["execution_nonce"],
            )
        try:
            scope = WindowsProcessScope(scope_name, create=False)
        except BaseException as error:
            if _windows_error_code(error) != 2:
                raise LearningStageWorkerError(
                    "benchmark launch recovery Job probe is indeterminate"
                ) from error
        else:
            try:
                if scope.pids():
                    scope.terminate()
                if scope.pids():
                    raise LearningStageWorkerError(
                        "benchmark launch recovery Job did not reach zero"
                    )
            finally:
                scope.close()
        event_name = _benchmark_worker_gate_event_name(scope_name)
        try:
            event = win32event.OpenEvent(
                win32event.EVENT_MODIFY_STATE | 0x00100000,
                False,
                event_name,
            )
        except BaseException as error:
            if _windows_error_code(error) != 2:
                raise LearningStageWorkerError(
                    "benchmark launch recovery Event probe is indeterminate"
                ) from error
        else:
            win32api.CloseHandle(event)
        beacon_path.unlink(missing_ok=True)
        cleanup = seal_immutable(
            {
                "contract_version": "benchmark_worker_launch_recovery_cleanup_v1",
                "outcome": "verified_launch_artifacts_absent",
                "authority_kind": original["authority_kind"],
                "run_id": original["run_id"],
                "stage": original["stage"],
                "operation_id": original["operation_id"],
                "worker_id": worker,
                "model_request_id": original["model_request_id"],
                "payload_sha256": original["payload_sha256"],
                "execution_nonce": original["execution_nonce"],
                "reservation_ref": {"content_sha256": original["content_sha256"]},
                "current_reservation_ref": {
                    "content_sha256": current["content_sha256"]
                },
                "operation_anchor_ref": deepcopy(
                    inspection["operation_anchor_ref"]
                ),
                "supervision_ref": deepcopy(inspection["supervision_ref"]),
                "process_identity": deepcopy(process_identity),
                "scope_name": scope_name,
                "termination_observation": deepcopy(termination),
                "job_absent": True,
                "event_absent": True,
                "beacon_absent": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        _write_json_create_only(cleanup_path, cleanup)
        self._retest_benchmark_launch_recovery_absence(cleanup)
        record = self._records.get(worker)
        if record is not None:
            record["status"] = "cancelled"
            record["finished_at"] = _utc_now_iso()
            self._active_by_operation.pop(
                (original["run_id"], original["stage"], original["operation_id"]),
                None,
            )
        return self._benchmark_launch_recovery_projection(
            inspection=inspection,
            outcome="verified_cleanup_safe_stop",
            gate_release_performed=False,
            cleanup_ref={"content_sha256": cleanup["content_sha256"]},
        )

    def _retest_benchmark_launch_recovery_absence(
        self, cleanup: Mapping[str, object]
    ) -> None:
        import win32api
        import win32event
        from app.learn.hybrid.windows_process_scope import WindowsProcessScope

        identity = cleanup.get("process_identity")
        if identity is not None and not self._benchmark_process_incarnation_absent(
            identity
        ):
            raise LearningStageWorkerError(
                "benchmark launch recovery worker remains present"
            )
        try:
            scope = WindowsProcessScope(str(cleanup["scope_name"]), create=False)
        except BaseException as error:
            if _windows_error_code(error) != 2:
                raise LearningStageWorkerError(
                    "benchmark launch recovery Job absence is indeterminate"
                ) from error
        else:
            try:
                members = scope.pids()
            finally:
                scope.close()
            raise LearningStageWorkerError(
                f"benchmark launch recovery Job remains present: {members}"
            )
        try:
            handle = win32event.OpenEvent(
                0x00100000,
                False,
                _benchmark_worker_gate_event_name(str(cleanup["scope_name"])),
            )
        except BaseException as error:
            if _windows_error_code(error) != 2:
                raise LearningStageWorkerError(
                    "benchmark launch recovery Event absence is indeterminate"
                ) from error
        else:
            win32api.CloseHandle(handle)
            raise LearningStageWorkerError(
                "benchmark launch recovery Event remains present"
            )
        if (
            self._result_root
            / f"{cleanup['worker_id']}.benchmark-beacon.json"
        ).exists():
            raise LearningStageWorkerError(
                "benchmark launch recovery beacon remains present"
            )

    def _launch_validated_benchmark_worker(
        self, *, current: dict[str, Any], anchor: dict[str, Any],
        authoritative_payload: dict[str, Any], root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        """创建 gate/Job/owner，证明 exact assignment 后才释放 child。"""
        import psutil
        import win32api
        import win32event
        from app.learn.hybrid.windows_process_scope import (
            WindowsProcessScope,
            assign_exact_process_identity_to_scope,
            benchmark_worker_scope_name_v1,
        )

        scope_name = benchmark_worker_scope_name_v1(
            authority_kind=root.authority_kind, run_id=current["run_id"],
            stage=current["stage"], operation_id=current["operation_id"],
            worker_id=current["worker_id"], payload_sha256=current["payload_sha256"],
            execution_nonce=current["execution_nonce"],
        )
        supervisor_identity = {
            "pid": os.getpid(),
            "create_time_ns": int(round(psutil.Process().create_time() * 1_000_000_000)),
        }
        original = self._benchmark_reservations_by_ref[anchor["reservation_ref"]["content_sha256"]]
        supervision = compose_benchmark_worker_supervision_v1(
            supervision_root=root, reservation=original,
            expected_operation_anchor=anchor,
            supervisor_process_identity=supervisor_identity,
            startup_gate_timeout_ms=15_000,
        )
        event_name = f"Local\\AgentGuiBenchmarkWorkerGate-{content_sha256({'scope_name': scope_name})}"
        beacon_path = self._result_root / f"{current['worker_id']}.benchmark-beacon.json"
        owner_path = self._result_root / f"{current['worker_id']}.benchmark-owner.json"
        result_path = self._result_root / f"{current['worker_id']}.result.json"
        journal_path = self._result_root / f"{current['worker_id']}.worker.json"
        event_handle = None
        scope = None
        process = None
        process_identity = None
        beacon_ref = None
        assignment_ref = None
        launch_identity_anchor = None
        owner = None
        gate_released = False
        operation_key = (current["run_id"], current["stage"], current["operation_id"])
        try:
            event_handle = win32event.CreateEvent(None, True, False, event_name)
            if win32api.GetLastError() == 183:
                raise LearningStageWorkerError("benchmark startup Event collision")
            scope = WindowsProcessScope(scope_name, create=True)
            owner = self._benchmark_owner_journal(
                current=current, anchor=anchor, supervision=supervision,
                scope_name=scope_name, supervisor_identity=supervisor_identity,
                phase="acquiring", process_identity=None, beacon_ref=None,
                assignment_ref=None, gate_state="closed", predecessor=None,
            )
            _write_json_atomic(owner_path, owner)
            launching = self._transition_benchmark_reservation(current, "launching")
            self._persist_benchmark_reservation(launching)
            self._benchmark_reservations[operation_key] = launching
            self._benchmark_reservations_by_ref[launching["content_sha256"]] = launching
            identity = {
                "worker_id": current["worker_id"], "run_id": current["run_id"],
                "stage": current["stage"], "operation_id": current["operation_id"],
                "task_kind": current["task_kind"], "model_request_id": current["model_request_id"],
                "payload_sha256": current["payload_sha256"],
            }
            bootstrap = {
                "event_name": event_name, "beacon_path": str(beacon_path),
                "worker_id": current["worker_id"],
                "operation_anchor_ref": {"content_sha256": anchor["anchor_identity_sha256"]},
                "supervision_ref": {"content_sha256": supervision["content_sha256"]},
                "startup_gate_timeout_ms": 15_000,
            }
            process = self._process_factory(
                target=_run_learning_stage_worker_entry,
                args=(str(result_path), current["task_kind"], deepcopy(authoritative_payload),
                      current["model_request_id"], deepcopy(identity), None, None, bootstrap),
                name=f"learning-stage-{current['stage']}-{current['worker_id'][:8]}",
            )
            process.start()
            deadline = time.monotonic() + 15.0
            beacon = None
            while time.monotonic() < deadline:
                if beacon_path.exists():
                    try:
                        beacon = json.loads(beacon_path.read_text(encoding="utf-8"))
                        break
                    except (OSError, UnicodeError, json.JSONDecodeError):
                        pass
                if not process.is_alive():
                    break
                time.sleep(0.01)
            if not isinstance(beacon, dict):
                raise LearningStageWorkerError("benchmark worker startup beacon timed out")
            process_identity = beacon.get("process_identity")
            if not isinstance(process_identity, dict) or process_identity.get("pid") != process.pid:
                raise LearningStageWorkerError("benchmark worker beacon identity mismatch")
            assignment = assign_exact_process_identity_to_scope(
                scope_name=scope_name, process_identity=process_identity
            )
            assignment_body = deepcopy(assignment)
            assignment_body.pop("content_sha256", None)
            assignment_body["predecessor_content_sha256"] = owner[
                "content_sha256"
            ]
            assignment = seal_immutable(assignment_body)
            _write_json_atomic(
                self._result_root
                / f"{current['worker_id']}.benchmark-assignment.json",
                assignment,
            )
            beacon_ref = {"content_sha256": beacon["content_sha256"]}
            assignment_ref = {
                "content_sha256": assignment["content_sha256"]
            }
            owner = self._benchmark_owner_journal(
                current=launching, anchor=anchor, supervision=supervision,
                scope_name=scope_name, supervisor_identity=supervisor_identity,
                phase="assignment_proven", process_identity=process_identity,
                beacon_ref=beacon_ref,
                assignment_ref=assignment_ref,
                gate_state="closed", predecessor=owner["content_sha256"],
            )
            _write_json_atomic(owner_path, owner)
            launch_identity_anchor = _compose_benchmark_launch_identity_anchor(
                anchored_reservation=current,
                launching_reservation=launching,
                operation_anchor=anchor,
                supervision=supervision,
                supervisor_process_identity=supervisor_identity,
                beacon_ref=beacon_ref,
                process_identity=process_identity,
                assignment=assignment,
            )
            _write_json_create_only(
                self._result_root
                / (
                    f"{current['worker_id']}"
                    ".benchmark-launch-identity-anchor.json"
                ),
                launch_identity_anchor,
            )
            win32event.SetEvent(event_handle)
            gate_released = True
            owner = self._benchmark_owner_journal(
                current=launching, anchor=anchor, supervision=supervision,
                scope_name=scope_name, supervisor_identity=supervisor_identity,
                phase="gate_released", process_identity=process_identity,
                beacon_ref=beacon_ref,
                assignment_ref=assignment_ref,
                gate_state="released", predecessor=owner["content_sha256"],
            )
            _write_json_atomic(owner_path, owner)
            launched = self._transition_benchmark_reservation(launching, "launched")
            self._persist_benchmark_reservation(launched)
            self._benchmark_reservations[operation_key] = launched
            self._benchmark_reservations_by_ref[launched["content_sha256"]] = launched
            record = {
                "contract_version": LEARNING_STAGE_WORKER_CONTRACT_VERSION, **identity,
                "status": "running", "started_at": _utc_now_iso(), "finished_at": None,
                "result_path": str(result_path), "journal_path": str(journal_path),
                "process": process, "payload": deepcopy(authoritative_payload),
                "cancellation_event": None, "completion_event": None,
                "provider_scope": None, "provider_scope_name": None,
                "recovered_from_journal": False,
                "benchmark_owner_path": str(owner_path), "benchmark_beacon_path": str(beacon_path),
                "benchmark_event_handle": event_handle, "benchmark_scope": scope,
                "benchmark_anchor": deepcopy(anchor), "benchmark_supervision": supervision,
                "benchmark_reservation": launched,
            }
            self._persist_record_journal(record)
            self._records[current["worker_id"]] = record
            self._active_by_operation[operation_key] = current["worker_id"]
            self._workers_by_operation.setdefault(operation_key, []).append(current["worker_id"])
            self._workers_by_invocation[(*operation_key, current["task_kind"], current["payload_sha256"])] = current["worker_id"]
            return self._public_record(record)
        except BaseException as primary_error:
            failed_beacon = None
            if beacon_path.exists():
                try:
                    failed_beacon = json.loads(beacon_path.read_text(encoding="utf-8"))
                except BaseException:
                    failed_beacon = None
            failed_process_identity = deepcopy(process_identity)
            if process is not None and isinstance(getattr(process, "pid", None), int):
                if failed_process_identity is None:
                    try:
                        failed_process_identity = {
                            "pid": process.pid,
                            "create_time_ns": int(
                                round(psutil.Process(process.pid).create_time() * 1_000_000_000)
                            ),
                        }
                    except BaseException:
                        failed_process_identity = None

            cleanup_entry = {
                "cleanup_kind": "benchmark_failed_launch_v1",
                "benchmark_process": process,
                "benchmark_event_handle": event_handle,
                "benchmark_scope": scope,
                "beacon_path": beacon_path,
                "attempt": 0,
                "step_states": {
                    name: {"status": "pending"}
                    for name in (
                        "process_terminate", "job_terminate", "process_join",
                        "job_stable_zero", "process_close", "event_close",
                        "beacon_unlink", "job_close",
                    )
                },
                "authority_kind": root.authority_kind,
                "run_id": current["run_id"],
                "stage": current["stage"],
                "operation_id": current["operation_id"],
                "worker_id": current["worker_id"],
                "scope_name": scope_name,
                "process_identity": deepcopy(failed_process_identity),
                "assignment_observation_ref": deepcopy(assignment_ref),
                "launch_identity_anchor_ref": (
                    {"content_sha256": launch_identity_anchor["content_sha256"]}
                    if isinstance(launch_identity_anchor, dict)
                    else None
                ),
                "primary_error": {
                    "error_type": type(primary_error).__name__,
                    "message": str(primary_error),
                },
                "predecessor_content_sha256": (
                    owner["content_sha256"]
                    if isinstance(owner, dict)
                    else current["content_sha256"]
                ),
            }
            self._failed_start_cleanups[operation_key] = cleanup_entry
            cleanup_observation = self._retry_benchmark_failed_launch_cleanup(
                operation_key
            )
            if isinstance(owner, dict):
                failed_owner = self._benchmark_owner_journal(
                    current=self._benchmark_reservations.get(operation_key, current),
                    anchor=anchor, supervision=supervision,
                    scope_name=scope_name, supervisor_identity=supervisor_identity,
                    phase="recovery_required",
                    process_identity=failed_process_identity,
                    beacon_ref=(
                        deepcopy(beacon_ref)
                        if isinstance(beacon_ref, dict)
                        else (
                            {"content_sha256": failed_beacon.get("content_sha256")}
                            if isinstance(failed_beacon, dict)
                            and failed_beacon.get("process_identity")
                            == failed_process_identity
                            else None
                        )
                    ),
                    assignment_ref=assignment_ref,
                    gate_state=(
                        "released_before_failure"
                        if gate_released
                        else "not_released_due_to_failure"
                    ),
                    predecessor=owner["content_sha256"],
                )
                owner_body = deepcopy(failed_owner)
                owner_body.pop("content_sha256")
                owner_body["exit_observation_ref"] = {
                    "content_sha256": cleanup_observation["content_sha256"]
                }
                failed_owner = seal_immutable(owner_body)
                _write_json_atomic(owner_path, failed_owner)
            if cleanup_observation["cleanup_status"] != "verified":
                raise LearningStageWorkerCleanupError(
                    cleanup_observation,
                    "Benchmark worker launch cleanup is indeterminate",
                ) from primary_error
            raise

    def _retry_benchmark_failed_launch_cleanup(
        self,
        operation_key: tuple[str, str, str],
    ) -> dict[str, Any]:
        entry = self._failed_start_cleanups.get(operation_key)
        if (
            not isinstance(entry, dict)
            or entry.get("cleanup_kind") != "benchmark_failed_launch_v1"
        ):
            raise LearningStageWorkerError(
                "benchmark failed launch cleanup authority is missing"
            )
        states = entry["step_states"]
        process = entry["benchmark_process"]
        scope = entry["benchmark_scope"]
        event_handle = entry["benchmark_event_handle"]
        failures: list[dict[str, str]] = []
        if (
            states["process_join"].get("status") == "completed"
            and states["process_join"].get("result", {}).get("alive_after")
            is False
            and states["process_close"].get("status") == "completed"
        ):
            states["process_terminate"] = {
                "status": "completed",
                "result": {"superseded_by_absent_closed_process": True},
            }
        if (
            states["job_stable_zero"].get("status") == "completed"
            and states["job_close"].get("status") == "completed"
        ):
            states["job_terminate"] = {
                "status": "completed",
                "result": {"superseded_by_stable_zero_closed_job": True},
            }

        def attempt(
            name: str,
            action: Callable[[], object],
            *,
            close_resource: str | None = None,
        ) -> None:
            if states[name].get("status") == "completed":
                return
            try:
                result = action()
                if result is False:
                    raise LearningStageWorkerError(
                        f"benchmark failed launch {name} returned false"
                    )
            except BaseException as error:
                if (
                    close_resource is not None
                    and _benchmark_failed_launch_close_already_proven(
                        close_resource, error
                    )
                ):
                    states[name] = {
                        "status": "completed",
                        "result": {"already_closed": True},
                    }
                    if close_resource == "job_close" and scope is not None:
                        scope._closed = True
                    return
                failure = {
                    "step": name,
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
                failures.append(failure)
                states[name] = {"status": "error", **failure}
                return
            states[name] = {"status": "completed", "result": deepcopy(result)}

        def terminate_process() -> dict[str, Any]:
            if process is None:
                return {"not_applicable": True}
            alive_before = bool(process.is_alive())
            if alive_before:
                result = _benchmark_failed_launch_process_terminate(process)
                if result is False:
                    return False
            return {
                "alive_before": alive_before,
                "terminate_called": alive_before,
            }

        def terminate_job() -> dict[str, Any]:
            if scope is None:
                return {"not_applicable": True}
            result = _benchmark_failed_launch_job_terminate(scope)
            if result is False:
                return False
            return {"terminate_called": True}

        attempt("process_terminate", terminate_process)
        attempt("job_terminate", terminate_job)
        attempt(
            "process_join",
            lambda: _join_benchmark_failed_launch_process(process),
        )
        if states["process_join"].get("status") == "completed":
            attempt(
                "job_stable_zero",
                lambda: _benchmark_failed_launch_job_stable_zero(scope),
            )
            attempt(
                "process_close",
                lambda: (
                    {"not_applicable": True}
                    if process is None
                    else _benchmark_failed_launch_process_close(process)
                ),
                close_resource="process_close",
            )
        attempt(
            "event_close",
            lambda: (
                {"not_applicable": True}
                if event_handle is None
                else _benchmark_failed_launch_event_close(event_handle)
            ),
            close_resource="event_close",
        )
        attempt(
            "beacon_unlink",
            lambda: _unlink_benchmark_failed_launch_beacon(entry["beacon_path"]),
        )
        if states["job_stable_zero"].get("status") == "completed":
            attempt(
                "job_close",
                lambda: (
                    {"not_applicable": True}
                    if scope is None
                    else _benchmark_failed_launch_job_close(scope)
                ),
                close_resource="job_close",
            )
        verified = all(
            state.get("status") == "completed" for state in states.values()
        )
        attempt_index = int(entry["attempt"])
        observation = seal_immutable({
            "contract_version": "benchmark_worker_launch_failure_cleanup_v1",
            "authority_kind": entry["authority_kind"],
            "run_id": entry["run_id"],
            "stage": entry["stage"],
            "operation_id": entry["operation_id"],
            "worker_id": entry["worker_id"],
            "scope_name": entry["scope_name"],
            "process_identity": deepcopy(entry["process_identity"]),
            "assignment_observation_ref": deepcopy(
                entry["assignment_observation_ref"]
            ),
            "launch_identity_anchor_ref": deepcopy(
                entry["launch_identity_anchor_ref"]
            ),
            "primary_error": deepcopy(entry["primary_error"]),
            **deepcopy(states),
            "cleanup_failures": deepcopy(failures),
            "cleanup_status": "verified" if verified else "indeterminate",
            "cleanup_attempt": attempt_index,
            "predecessor_content_sha256": entry[
                "predecessor_content_sha256"
            ],
            "artifact_is_authorization": False,
        })
        path = self._result_root / (
            f"{entry['worker_id']}.benchmark-launch-failure-cleanup.json"
            if attempt_index == 0
            else (
                f"{entry['worker_id']}.benchmark-launch-failure-cleanup-"
                f"retry-{attempt_index:04d}.json"
            )
        )
        _write_json_atomic(path, observation)
        entry["attempt"] = attempt_index + 1
        entry["predecessor_content_sha256"] = observation["content_sha256"]
        if verified:
            self._failed_start_cleanups.pop(operation_key, None)
        return observation

    @staticmethod
    def _transition_benchmark_reservation(current: dict[str, Any], state: str) -> dict[str, Any]:
        body = deepcopy(current); body.pop("content_sha256")
        body["reservation_state"] = state
        body["predecessor_content_sha256"] = current["content_sha256"]
        return seal_immutable(body)

    @staticmethod
    def _benchmark_owner_journal(
        *, current: dict[str, Any], anchor: dict[str, Any], supervision: dict[str, Any],
        scope_name: str, supervisor_identity: dict[str, int], phase: str,
        process_identity: dict[str, int] | None, beacon_ref: dict[str, Any] | None,
        assignment_ref: dict[str, Any] | None, gate_state: str,
        predecessor: str | None,
    ) -> dict[str, Any]:
        return seal_immutable({
            "contract_version": "benchmark_worker_owner_journal_v1",
            "authority_kind": current["authority_kind"],
            "operation_anchor_ref": {"content_sha256": anchor["anchor_identity_sha256"]},
            "reservation_ref": {"content_sha256": current["content_sha256"]},
            "supervision_ref": {"content_sha256": supervision["content_sha256"]},
            "run_id": current["run_id"], "stage": current["stage"],
            "operation_id": current["operation_id"], "worker_id": current["worker_id"],
            "model_request_id": current["model_request_id"], "payload_sha256": current["payload_sha256"],
            "execution_nonce": current["execution_nonce"], "scope_name": scope_name,
            "supervisor_process_identity": deepcopy(supervisor_identity), "phase": phase,
            "process_identity": deepcopy(process_identity), "beacon_ref": deepcopy(beacon_ref),
            "assignment_observation_ref": deepcopy(assignment_ref),
            "job_policy": ({"kill_on_job_close": True, "breakaway_ok": False,
                            "silent_breakaway_ok": False,
                            "owner_handle_authority": "registry_parent"}
                           if assignment_ref is not None else None),
            "gate_state": gate_state, "exit_observation_ref": None,
            "stable_zero_observation_ref": None, "exact_handle_observation_refs": None,
            "cleanup_finalization_intent": None, "cleanup_receipt_ref": None,
            "predecessor_content_sha256": predecessor,
        })

    def abort_prepared_benchmark_worker_before_anchor(
        self, *, reservation_ref: dict[str, Any], run_id: str, stage: str,
        operation_id: str, workflow_revision: int,
        expected_operation_anchor: dict[str, Any], reason: str,
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        root = self._require_benchmark_root(supervision_root)
        run = _required_text(run_id, "run_id"); stage_value = _required_text(stage, "stage")
        operation = _required_text(operation_id, "operation_id")
        if reason not in {"store_cas_lost", "cancelled", "stale"}:
            raise LearningStageWorkerError("benchmark pre-anchor abort reason is invalid")
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=run, stage=stage_value, operation_id=operation
        ):
            # store 回调必须发生在 Registry 锁外。
            if getattr(self._lock, "_is_owned", lambda: False)():
                raise LearningStageWorkerError("benchmark store callback under Registry lock")
            try:
                state = root.read_only_store_authority.get(run)
            except BaseException as error:
                from app.learn.workflow_state import (
                    LearningWorkflowTransitionError,
                )

                if (
                    isinstance(error, LearningWorkflowTransitionError)
                    and str(error) == "workflow run not found"
                ):
                    state = None
                else:
                    raise LearningStageWorkerError(
                        "benchmark pre-anchor abort store decision is indeterminate"
                    ) from error
            reservation = self._benchmark_by_ref(reservation_ref)
            validate_benchmark_worker_operation_anchor_v1(
                expected_operation_anchor, supervision_root=root,
                expected_reservation=reservation,
            )
            if state is None:
                current_incumbent_ref = None
                current_anchor_ref = None
                current_operation_id = None
                current_stage = None
                current_operation_outcome = None
                outcome = "matching_anchor_absent_stale"
                predicate = "workflow_run_not_found"
            else:
                if not isinstance(state, dict):
                    raise LearningStageWorkerError(
                        "benchmark pre-anchor abort store state is invalid"
                    )
                evidence = state.get("current_evidence_refs")
                if not isinstance(evidence, dict):
                    evidence = state.get("evidence_refs")
                stage_execution = (
                    evidence.get("stage_execution")
                    if isinstance(evidence, dict)
                    else None
                )
                incumbent = (
                    stage_execution.get("benchmark_v2_incumbent")
                    if isinstance(stage_execution, dict)
                    else None
                )
                current_incumbent_ref = None
                current_anchor_ref = None
                if incumbent is not None:
                    if (
                        not isinstance(incumbent, dict)
                        or content_sha256(incumbent)
                        != incumbent.get("content_sha256")
                    ):
                        raise LearningStageWorkerError(
                            "benchmark current incumbent document is invalid"
                        )
                    current_incumbent_ref = {
                        "content_sha256": incumbent["content_sha256"]
                    }
                    current_anchor_ref = _benchmark_exact_ref(
                        incumbent.get("operation_anchor_ref"),
                        "benchmark current operation anchor ref",
                    )
                current_operation_id = (
                    stage_execution.get("operation_id")
                    if isinstance(stage_execution, dict)
                    else None
                )
                current_stage = state.get("current_stage")
                stages = state.get("stages")
                current_operation_outcome = (
                    stages.get(current_stage, {}).get("status")
                    if isinstance(stages, dict)
                    and isinstance(current_stage, str)
                    and isinstance(stages.get(current_stage), dict)
                    else None
                )
                expected_anchor_ref = {
                    "content_sha256": expected_operation_anchor["content_sha256"]
                }
                if current_anchor_ref == expected_anchor_ref:
                    outcome = "matching_anchor_present"
                    predicate = "current_operation_anchor_exact_match"
                elif state.get("revision") != workflow_revision:
                    outcome = "matching_anchor_absent_store_cas_lost"
                    predicate = "current_revision_conflicts"
                elif state.get("terminal") is True:
                    outcome = "matching_anchor_absent_cancelled"
                    predicate = "current_operation_is_terminal"
                elif current_stage != stage or current_operation_id != operation:
                    outcome = "matching_anchor_absent_stale"
                    predicate = "current_operation_identity_replaced"
                else:
                    outcome = "indeterminate"
                    predicate = "same_revision_operation_without_anchor"
            expected_outcome_by_reason = {
                "store_cas_lost": "matching_anchor_absent_store_cas_lost",
                "cancelled": "matching_anchor_absent_cancelled",
                "stale": "matching_anchor_absent_stale",
            }
            if outcome == "matching_anchor_present":
                raise LearningStageWorkerError(
                    "benchmark worker operation anchor already exists"
                )
            if outcome == "indeterminate" or expected_outcome_by_reason[reason] != outcome:
                raise LearningStageWorkerError(
                    "benchmark pre-anchor abort decision is indeterminate"
                )
            decision = seal_immutable({
                "contract_version": "benchmark_worker_store_anchor_decision_v1",
                "authority_kind": root.authority_kind,
                "store_identity_sha256": root.store_identity_sha256,
                "store_state_found": state is not None,
                "current_state_content_sha256": (
                    content_sha256(state) if state is not None else None
                ),
                "current_revision": (
                    state.get("revision") if state is not None else None
                ),
                "current_stage": current_stage,
                "current_operation_id": current_operation_id,
                "current_operation_outcome": current_operation_outcome,
                "current_incumbent_document_ref": current_incumbent_ref,
                "current_operation_anchor_ref": current_anchor_ref,
                "run_id": run, "stage": stage_value, "operation_id": operation,
                "workflow_revision": workflow_revision,
                "reservation_ref": {"content_sha256": reservation["content_sha256"]},
                "expected_operation_anchor_ref": {
                    "content_sha256": expected_operation_anchor["anchor_identity_sha256"]
                },
                "reason": reason,
                "outcome": outcome,
                "predicate": predicate,
            })
            with self._lock:
                current = self._benchmark_reservations.get((run, stage_value, operation))
                receipt_path = _benchmark_operation_artifact_path(
                    self._result_root,
                    operation,
                    ".benchmark-pre-anchor-abort-receipt.json",
                )
                if current is not None and current.get("reservation_state") == "aborted_before_anchor":
                    if receipt_path.exists():
                        receipt = _read_json_object(
                            receipt_path,
                            label="benchmark pre-anchor abort receipt",
                        )
                        return _validate_benchmark_pre_anchor_abort_receipt(
                            receipt,
                            reservation=reservation,
                            aborted_reservation=current,
                            decision=decision,
                            result_root=self._result_root,
                            reason=reason,
                        )
                    observation_path = _benchmark_operation_artifact_path(
                        self._result_root,
                        operation,
                        ".benchmark-pre-anchor-abort.json",
                    )
                    if not observation_path.exists():
                        raise LearningStageWorkerError("benchmark pre-anchor abort replay does not match")
                    observation = _validate_benchmark_pre_anchor_abort_observation(
                        reservation=reservation,
                        aborted_reservation=current,
                        decision=decision,
                        result_root=self._result_root,
                        reason=reason,
                    )
                    receipt = _compose_benchmark_pre_anchor_abort_receipt(
                        reservation=reservation,
                        aborted_reservation=current,
                        decision=decision,
                        observation=observation,
                        reason=reason,
                    )
                    _write_json_atomic(receipt_path, receipt)
                    return receipt
                if current != reservation or current.get("reservation_state") != "reserved":
                    raise LearningStageWorkerError("benchmark reservation is not abortable")
                forbidden_paths = (
                    self._result_root / f"{current['worker_id']}.benchmark-owner.json",
                    self._result_root / f"{current['worker_id']}.benchmark-beacon.json",
                    self._result_root / f"{current['worker_id']}.result.json",
                    self._result_root / f"{current['worker_id']}.worker.json",
                )
                if current["worker_id"] in self._records or any(path.exists() for path in forbidden_paths):
                    raise LearningStageWorkerError("benchmark pre-anchor abort found launch artifacts")
                absence = self._persist_benchmark_pre_anchor_absence_observations(
                    reservation=current,
                )
                decision_path = _benchmark_operation_artifact_path(
                    self._result_root,
                    operation,
                    ".benchmark-store-decision.json",
                )
                _write_json_atomic(decision_path, decision)
                observation = seal_immutable({
                    "contract_version": "benchmark_worker_pre_anchor_abort_observation_v1",
                    "store_decision_ref": {"content_sha256": decision["content_sha256"]},
                    "reservation_ref": {"content_sha256": current["content_sha256"]},
                    "reason": reason,
                    "owner_absence_observation_ref": absence[
                        "owner_absence_observation_ref"
                    ],
                    "process_event_job_beacon_absence_observation_ref": absence[
                        "process_event_job_beacon_absence_observation_ref"
                    ],
                    "result_absence_observation_ref": absence[
                        "result_absence_observation_ref"
                    ],
                    "provider_absence_observation_ref": absence[
                        "provider_absence_observation_ref"
                    ],
                    "predecessor_content_sha256": absence[
                        "provider_absence_observation_ref"
                    ]["content_sha256"],
                })
                observation_path = _benchmark_operation_artifact_path(
                    self._result_root,
                    operation,
                    ".benchmark-pre-anchor-abort.json",
                )
                _write_json_atomic(observation_path, observation)
                aborted_body = deepcopy(current); aborted_body.pop("content_sha256")
                aborted_body["reservation_state"] = "aborted_before_anchor"
                aborted_body["abort_observation_ref"] = {"content_sha256": observation["content_sha256"]}
                aborted_body["predecessor_content_sha256"] = current["content_sha256"]
                aborted = seal_immutable(aborted_body)
                self._persist_benchmark_reservation(aborted)
                self._benchmark_reservations[(run, stage_value, operation)] = aborted
                self._benchmark_reservations_by_ref[aborted["content_sha256"]] = aborted
                receipt = _compose_benchmark_pre_anchor_abort_receipt(
                    reservation=current,
                    aborted_reservation=aborted,
                    decision=decision,
                    observation=observation,
                    reason=reason,
                )
                _write_json_atomic(receipt_path, receipt)
                return receipt

    def _persist_benchmark_pre_anchor_absence_observations(
        self,
        *,
        reservation: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        import win32api
        import win32event
        from app.learn.hybrid.windows_process_scope import (
            WindowsProcessScope,
            benchmark_worker_scope_name_v1,
        )

        worker = reservation["worker_id"]
        scope_name = benchmark_worker_scope_name_v1(
            authority_kind=reservation["authority_kind"],
            run_id=reservation["run_id"],
            stage=reservation["stage"],
            operation_id=reservation["operation_id"],
            worker_id=worker,
            payload_sha256=reservation["payload_sha256"],
            execution_nonce=reservation["execution_nonce"],
        )
        event_name = (
            "Local\\AgentGuiBenchmarkWorkerGate-"
            + content_sha256({"scope_name": scope_name})
        )

        def error_code(error: BaseException) -> int | None:
            code = getattr(error, "winerror", None)
            if code is None and getattr(error, "args", None):
                first = error.args[0]
                code = first if isinstance(first, int) else None
            return code

        try:
            job = WindowsProcessScope(scope_name, create=False)
        except BaseException as error:
            if error_code(error) != 2:
                raise LearningStageWorkerError(
                    "benchmark pre-anchor Job probe is indeterminate"
                ) from error
        else:
            try:
                job.close()
            finally:
                raise LearningStageWorkerError(
                    "benchmark pre-anchor owner Job is present"
                )
        try:
            event = win32event.OpenEvent(0x00100000, False, event_name)
        except BaseException as error:
            if error_code(error) != 2:
                raise LearningStageWorkerError(
                    "benchmark pre-anchor Event probe is indeterminate"
                ) from error
        else:
            try:
                win32api.CloseHandle(event)
            finally:
                raise LearningStageWorkerError(
                    "benchmark pre-anchor startup Event is present"
                )

        owner_path = self._result_root / f"{worker}.benchmark-owner.json"
        beacon_path = self._result_root / f"{worker}.benchmark-beacon.json"
        worker_path = self._result_root / f"{worker}.worker.json"
        result_path = self._result_root / f"{worker}.result.json"
        provider_path = self._result_root / f"{worker}.provider-owner.json"
        if worker in self._records or any(
            path.exists() for path in (owner_path, beacon_path, worker_path)
        ):
            raise LearningStageWorkerError(
                "benchmark pre-anchor launch artifacts are present"
            )
        if result_path.exists():
            raise LearningStageWorkerError(
                "benchmark pre-anchor result artifact is present"
            )
        if provider_path.exists():
            raise LearningStageWorkerError(
                "benchmark pre-anchor provider owner is present"
            )

        predecessor = reservation["content_sha256"]
        observations: dict[str, dict[str, Any]] = {}
        specs = (
            (
                "owner",
                {"registry_record_absent": True, "owner_journal_absent": True},
                "owner_absence_observation_ref",
            ),
            (
                "process_event_job_beacon",
                {
                    "worker_journal_absent": True,
                    "startup_event_absent": True,
                    "owner_job_absent": True,
                    "beacon_absent": True,
                    "scope_name": scope_name,
                    "event_name": event_name,
                },
                "process_event_job_beacon_absence_observation_ref",
            ),
            (
                "result",
                {"result_absent": True},
                "result_absence_observation_ref",
            ),
            (
                "provider",
                {"provider_owner_absent": True},
                "provider_absence_observation_ref",
            ),
        )
        for kind, checks, ref_name in specs:
            observation = seal_immutable({
                "contract_version": (
                    "benchmark_worker_pre_anchor_absence_observation_v1"
                ),
                "observation_kind": kind,
                "outcome": "absent",
                "reservation_ref": {
                    "content_sha256": reservation["content_sha256"]
                },
                "run_id": reservation["run_id"],
                "stage": reservation["stage"],
                "operation_id": reservation["operation_id"],
                "worker_id": worker,
                "checks": checks,
                "predecessor_content_sha256": predecessor,
            })
            _write_json_atomic(
                self._result_root
                / f"{worker}.pre-anchor-{kind}-absence.json",
                observation,
            )
            observations[ref_name] = {
                "content_sha256": observation["content_sha256"]
            }
            predecessor = observation["content_sha256"]
        return observations

    def observe_benchmark_worker_cleanup(
        self, *, worker_id: str, run_id: str, stage: str, operation_id: str,
        terminate: bool, expected_operation_anchor: dict[str, Any],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        """关闭 Registry 独占 handles，并仅以 fresh Job/PID absence 签收。"""

        import psutil
        import win32api
        from app.learn.hybrid.windows_process_scope import WindowsProcessScope

        root = self._require_benchmark_root(supervision_root)
        run = _required_text(run_id, "run_id"); stage_value = _required_text(stage, "stage")
        operation = _required_text(operation_id, "operation_id"); worker = _required_text(worker_id, "worker_id")
        key = (run, stage_value, operation)
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=run, stage=stage_value, operation_id=operation
        ):
            with self._lock:
                reservation = self._benchmark_reservations.get(key)
                if reservation is None or reservation["worker_id"] != worker:
                    raise LearningStageWorkerError("benchmark worker cleanup identity does not match")
                original = self._benchmark_reservations_by_ref.get(
                    expected_operation_anchor.get("reservation_ref", {}).get("content_sha256", "")
                )
                if original is None:
                    raise LearningStageWorkerError("benchmark cleanup anchor reservation is invalid")
                validate_benchmark_worker_operation_anchor_v1(
                    expected_operation_anchor, supervision_root=root,
                    expected_reservation=original,
                )
                retained_cleanup = self._failed_start_cleanups.get(key)
                if (
                    isinstance(retained_cleanup, dict)
                    and retained_cleanup.get("cleanup_kind")
                    == "benchmark_failed_launch_v1"
                ):
                    retry_observation = (
                        self._retry_benchmark_failed_launch_cleanup(key)
                    )
                    if retry_observation["cleanup_status"] != "verified":
                        raise LearningStageWorkerCleanupError(
                            retry_observation,
                            "Benchmark worker launch cleanup is indeterminate",
                        )
                    return {
                        "contract_version": (
                            "benchmark_worker_failed_launch_cleanup_retry_v1"
                        ),
                        "status": "recovery_required",
                        "worker_id": worker,
                        "process_identity": deepcopy(
                            retry_observation["process_identity"]
                        ),
                        "cleanup_status": "verified",
                        "cleanup_observation_ref": {
                            "content_sha256": retry_observation[
                                "content_sha256"
                            ]
                        },
                    }
                receipt_path = self._result_root / f"{worker}.benchmark-cleanup.json"
                if receipt_path.exists():
                    validated_receipt = _validate_benchmark_cleanup_receipt(
                        _read_json_object(
                            receipt_path, label="benchmark cleanup receipt"
                        ),
                        result_root=self._result_root,
                        worker_id=worker,
                        run_id=run,
                        stage=stage_value,
                        operation_id=operation,
                        operation_anchor=expected_operation_anchor,
                        original_reservation=original,
                        current_reservation=reservation,
                        supervision_root=root,
                    )
                    if validated_receipt["outcome"] == (
                        "verified_exact_worker_exited"
                    ):
                        _benchmark_cleanup_replay_live_reattest(
                            result_root=self._result_root,
                            worker_id=worker,
                            run_id=run,
                            stage=stage_value,
                            operation_id=operation,
                            original_reservation=original,
                            validated_receipt=validated_receipt,
                        )
                    return deepcopy(validated_receipt)
                record = self._records.get(worker)
                if (
                    reservation["reservation_state"] == "cancelled_before_launch"
                    and record is None
                ):
                    no_launch = _validate_benchmark_not_launched_observation(
                        result_root=self._result_root,
                        worker_id=worker,
                        original_reservation=original,
                        cancelled_reservation=reservation,
                        operation_anchor=expected_operation_anchor,
                    )
                    receipt = _compose_benchmark_not_launched_receipt(
                        cancelled_reservation=reservation,
                        operation_anchor=expected_operation_anchor,
                        observation=no_launch,
                    )
                    _write_benchmark_cleanup_receipt_atomic(receipt_path, receipt)
                    return receipt
                if reservation["reservation_state"] == "anchored" and record is None:
                    absence = self._persist_benchmark_pre_anchor_absence_observations(
                        reservation=reservation,
                    )
                    no_launch = seal_immutable({
                        "contract_version": (
                            "benchmark_worker_not_launched_observation_v1"
                        ),
                        "outcome": "verified_no_launch_artifacts",
                        "authority_kind": reservation["authority_kind"],
                        "reservation_ref": {
                            "content_sha256": reservation["content_sha256"]
                        },
                        "run_id": run,
                        "stage": stage_value,
                        "operation_id": operation,
                        "worker_id": worker,
                        **deepcopy(absence),
                        "predecessor_content_sha256": absence[
                            "provider_absence_observation_ref"
                        ]["content_sha256"],
                        "artifact_is_authorization": False,
                        "execute_binding_enabled": False,
                    })
                    _write_json_atomic(
                        self._result_root
                        / f"{worker}.benchmark-not-launched.json",
                        no_launch,
                    )
                    cancelled_body = deepcopy(reservation)
                    cancelled_body.pop("content_sha256")
                    cancelled_body["reservation_state"] = (
                        "cancelled_before_launch"
                    )
                    cancelled_body["abort_observation_ref"] = {
                        "content_sha256": no_launch["content_sha256"]
                    }
                    cancelled_body["predecessor_content_sha256"] = reservation[
                        "content_sha256"
                    ]
                    cancelled = seal_immutable(cancelled_body)
                    self._persist_benchmark_reservation(cancelled)
                    self._benchmark_reservations[key] = cancelled
                    self._benchmark_reservations_by_ref[cancelled["content_sha256"]] = cancelled
                    receipt = _compose_benchmark_not_launched_receipt(
                        cancelled_reservation=cancelled,
                        operation_anchor=expected_operation_anchor,
                        observation=no_launch,
                    )
                    _write_benchmark_cleanup_receipt_atomic(receipt_path, receipt)
                    return receipt
                if record is None:
                    raise LearningStageWorkerError("benchmark worker cleanup recovery is required")
                intent_path = self._result_root / f"{worker}.benchmark-cleanup-intent.json"
                if intent_path.exists() and record.get("benchmark_scope") is None:
                    return self._complete_benchmark_cleanup_from_intent(
                        record=record, reservation=reservation,
                        expected_operation_anchor=expected_operation_anchor,
                        receipt_path=receipt_path, intent_path=intent_path,
                    )
                if record.get("recovered_from_journal") and record.get("benchmark_owner_path"):
                    owner = json.loads(
                        Path(record["benchmark_owner_path"]).read_text(encoding="utf-8")
                    )
                    if owner.get("phase") == "recovery_required":
                        process_identity = owner.get("process_identity")
                        if not self._benchmark_process_incarnation_absent(process_identity):
                            termination = self._terminate_exact_benchmark_process(
                                process_identity
                            )
                        else:
                            termination = {
                                "outcome": "exact_incarnation_already_absent",
                                "process_identity": deepcopy(process_identity),
                            }
                        return {
                            "contract_version": "benchmark_worker_pre_assignment_cleanup_v1",
                            "status": "recovery_required", "worker_id": worker,
                            "process_identity": deepcopy(process_identity),
                            "exact_process_termination": termination,
                            "cleanup_receipt": None,
                        }
                    if owner.get("phase") in {"acquiring", "identity_published"}:
                        beacon_path = Path(record["benchmark_beacon_path"])
                        if not beacon_path.exists():
                            raise LearningStageWorkerError(
                                "benchmark pre-assignment recovery is required"
                            )
                        beacon = json.loads(beacon_path.read_text(encoding="utf-8"))
                        process_identity = beacon.get("process_identity")
                        termination = self._terminate_exact_benchmark_process(
                            process_identity
                        )
                        beacon_path.unlink(missing_ok=True)
                        owner_body = deepcopy(owner); owner_body.pop("content_sha256")
                        owner_body.update({
                            "phase": "recovery_required",
                            "process_identity": process_identity,
                            "beacon_ref": {"content_sha256": beacon["content_sha256"]},
                            "exit_observation_ref": {
                                "content_sha256": content_sha256(termination)
                            },
                            "gate_state": "not_released_due_to_failure",
                            "predecessor_content_sha256": owner["content_sha256"],
                        })
                        recovered_owner = seal_immutable(owner_body)
                        _write_json_atomic(
                            Path(record["benchmark_owner_path"]), recovered_owner
                        )
                        return {
                            "contract_version": "benchmark_worker_pre_assignment_cleanup_v1",
                            "status": "recovery_required",
                            "worker_id": worker,
                            "process_identity": deepcopy(process_identity),
                            "exact_process_termination": termination,
                            "cleanup_receipt": None,
                        }
                    if owner.get("phase") not in {
                        "assignment_proven", "gate_released", "cleanup_finalization_intent"
                    } or not isinstance(owner.get("assignment_observation_ref"), dict):
                        raise LearningStageWorkerError(
                            "benchmark pre-assignment recovery is required"
                        )
                    supervisor_identity = owner.get("supervisor_process_identity")
                    supervisor_absent = self._benchmark_process_incarnation_absent(
                        supervisor_identity
                    )
                    if not supervisor_absent:
                        raise LearningStageWorkerError(
                            "benchmark live-supervisor recovery requires prior finalization intent"
                        )
                    supervisor_observation = (
                        self._persist_benchmark_absence_observation(
                            worker_id=worker,
                            observation_kind="supervisor",
                            scope_name=None,
                            process_identity=supervisor_identity,
                            predecessor_content_sha256=owner[
                                "content_sha256"
                            ],
                        )
                    )
                    scope = None
                    zero_samples: list[object] = []
                    try:
                        scope = WindowsProcessScope(owner["scope_name"], create=False)
                    except BaseException as error:
                        code = getattr(error, "winerror", None)
                        if code is None and getattr(error, "args", None):
                            first = error.args[0]
                            code = first if isinstance(first, int) else None
                        if code != 2:
                            raise LearningStageWorkerError(
                                "benchmark recovered Job probe is indeterminate"
                            ) from error
                        for _ in range(3):
                            try:
                                WindowsProcessScope(
                                    owner["scope_name"], create=False
                                )
                            except BaseException as sample_error:
                                sample_code = getattr(
                                    sample_error, "winerror", None
                                )
                                if (
                                    sample_code is None
                                    and getattr(sample_error, "args", None)
                                ):
                                    first = sample_error.args[0]
                                    sample_code = (
                                        first
                                        if isinstance(first, int)
                                        else None
                                    )
                                if sample_code != 2:
                                    raise LearningStageWorkerError(
                                        "benchmark recovered Job stable-zero probe is indeterminate"
                                    ) from sample_error
                                zero_samples.append({
                                    "probe": "OpenJob",
                                    "outcome": "absent",
                                    "error_code": 2,
                                })
                            else:
                                raise LearningStageWorkerError(
                                    "benchmark recovered Job reappeared"
                                )
                    if scope is not None:
                        try:
                            if terminate and scope.pids():
                                scope.terminate()
                            for _ in range(3):
                                members = scope.pids()
                                zero_samples.append(members)
                                if members:
                                    raise LearningStageWorkerError(
                                        "benchmark recovered Job did not reach stable zero"
                                    )
                                time.sleep(0.02)
                        finally:
                            scope.close()
                    stable_zero = seal_immutable({
                        "contract_version": (
                            "benchmark_worker_stable_zero_observation_v1"
                        ),
                        "worker_id": worker,
                        "scope_name": owner["scope_name"],
                        "samples": zero_samples,
                        "predecessor_content_sha256": supervisor_observation[
                            "content_sha256"
                        ],
                    })
                    _write_json_atomic(
                        self._result_root / f"{worker}.stable-zero.json",
                        stable_zero,
                    )
                    job_absence = self._persist_benchmark_absence_observation(
                        worker_id=worker,
                        observation_kind="job",
                        scope_name=owner["scope_name"],
                        process_identity=None,
                        predecessor_content_sha256=stable_zero[
                            "content_sha256"
                        ],
                    )
                    process_identity = owner.get("process_identity")
                    worker_absence = self._persist_benchmark_absence_observation(
                        worker_id=worker,
                        observation_kind="worker",
                        scope_name=None,
                        process_identity=process_identity,
                        predecessor_content_sha256=job_absence[
                            "content_sha256"
                        ],
                    )
                    beacon_path = Path(record["benchmark_beacon_path"])
                    if beacon_path.exists():
                        beacon_path.unlink()
                    intent = seal_immutable({
                        "contract_version": "benchmark_worker_cleanup_finalization_intent_v1",
                        "supervision_ref": owner["supervision_ref"],
                        "assignment_proven_ref": owner["assignment_observation_ref"],
                        "run_id": run, "stage": stage_value, "operation_id": operation,
                        "worker_id": worker, "supervisor_process_identity": supervisor_identity,
                        "process_identity": process_identity, "scope_name": owner["scope_name"],
                        "gate_state": owner["gate_state"],
                        "exit_observation_ref": {"content_sha256": supervisor_observation["content_sha256"]},
                        "stable_zero_observation_ref": {"content_sha256": stable_zero["content_sha256"]},
                        "exact_owned_handles": {
                            "worker_process": "closed_by_verified_supervisor_exit",
                            "startup_event": "closed_by_verified_supervisor_exit",
                            "beacon_file": "closed_by_verified_supervisor_exit",
                            "owner_job": "closed_by_verified_supervisor_exit",
                        },
                        "exact_handle_observation_refs": {},
                        "owner_job_handle_close_planned": True,
                        "cleanup_receipt_id": content_sha256({"worker_id": worker, "scope_name": owner["scope_name"]}),
                        "predecessor_content_sha256": owner["content_sha256"],
                    })
                    _write_json_atomic(
                        self._result_root / f"{worker}.benchmark-cleanup-intent.json", intent
                    )
                    owner_body = deepcopy(owner)
                    owner_body.pop("content_sha256")
                    owner_body.update({
                        "phase": "cleanup_finalization_intent",
                        "exit_observation_ref": intent["exit_observation_ref"],
                        "stable_zero_observation_ref": intent[
                            "stable_zero_observation_ref"
                        ],
                        "exact_handle_observation_refs": {},
                        "cleanup_finalization_intent": {
                            "content_sha256": intent["content_sha256"]
                        },
                        "predecessor_content_sha256": owner["content_sha256"],
                    })
                    owner = seal_immutable(owner_body)
                    _write_json_atomic(
                        Path(record["benchmark_owner_path"]), owner
                    )
                    receipt = seal_immutable({
                        "contract_version": "benchmark_worker_cleanup_receipt_v1",
                        "outcome": "verified_exact_worker_exited",
                        "operation_anchor_ref": {"content_sha256": expected_operation_anchor["anchor_identity_sha256"]},
                        "reservation_ref": {"content_sha256": reservation["content_sha256"]},
                        "supervision_ref": owner["supervision_ref"],
                        "run_id": run, "stage": stage_value, "operation_id": operation,
                        "worker_id": worker, "process_identity": process_identity,
                        "assignment_proven_ref": owner["assignment_observation_ref"],
                        "finalization_intent_ref": {"content_sha256": intent["content_sha256"]},
                        "exact_handle_observation_refs": {},
                        "job_absence_observation_ref": {"content_sha256": job_absence["content_sha256"]},
                        "worker_absence_observation_ref": {"content_sha256": worker_absence["content_sha256"]},
                        "supervisor_absence_observation_ref": {"content_sha256": supervisor_observation["content_sha256"]},
                        "reservation_abort_ref": None,
                        "artifact_is_authorization": False,
                        "execute_binding_enabled": False,
                    })
                    _write_benchmark_cleanup_receipt_atomic(receipt_path, receipt)
                    return receipt
                process = record.get("process")
                owner_path = Path(record["benchmark_owner_path"])
                owner = json.loads(owner_path.read_text(encoding="utf-8"))
                launch_identity_anchor = _read_json_object(
                    self._result_root
                    / f"{worker}.benchmark-launch-identity-anchor.json",
                    label="benchmark launch identity anchor",
                )
                if content_sha256(launch_identity_anchor) != (
                    launch_identity_anchor.get("content_sha256")
                ):
                    raise LearningStageWorkerError(
                        "benchmark launch identity anchor is invalid"
                    )
                process_identity = deepcopy(
                    launch_identity_anchor.get("process_identity")
                )
                if process_identity != owner.get("process_identity"):
                    raise LearningStageWorkerError(
                        "benchmark launch process identity does not match owner"
                    )
                handle_refs: dict[str, Any] = deepcopy(
                    record.get("benchmark_handle_refs") or {}
                )
                exit_ref = record.get("benchmark_exit_observation_ref")
                exit_path = self._result_root / f"{worker}.exit-join.json"
                if exit_ref is None:
                    if terminate and process is not None and process.is_alive():
                        process.terminate()
                    try:
                        if process is not None:
                            process.join(15)
                            if process.is_alive():
                                raise LearningStageWorkerError(
                                    "benchmark worker did not exit"
                                )
                        process_exitcode = getattr(process, "exitcode", None)
                        if isinstance(process_exitcode, bool) or not isinstance(
                            process_exitcode, int
                        ):
                            raise LearningStageWorkerError(
                                "benchmark worker exitcode is unavailable"
                            )
                    except BaseException as error:
                        failure = _compose_benchmark_exit_join_observation(
                            worker_id=worker,
                            process_identity=process_identity,
                            exitcode=getattr(process, "exitcode", None),
                            join_result=None,
                            join_error={
                                "error_type": type(error).__name__,
                                "message": str(error),
                            },
                            predecessor_content_sha256=owner["content_sha256"],
                        )
                        _write_json_atomic(
                            self._result_root / f"{worker}.exit-join-error.json",
                            failure,
                        )
                        raise
                    exit_observation = _compose_benchmark_exit_join_observation(
                        worker_id=worker,
                        process_identity=process_identity,
                        exitcode=process_exitcode,
                        join_result="joined",
                        join_error=None,
                        predecessor_content_sha256=owner["content_sha256"],
                    )
                    _write_json_atomic(exit_path, exit_observation)
                    exit_ref = {
                        "content_sha256": exit_observation["content_sha256"]
                    }
                    record["benchmark_exit_observation_ref"] = deepcopy(exit_ref)
                    record["benchmark_process_exitcode"] = process_exitcode
                else:
                    exit_observation = _validate_benchmark_artifact_ref(
                        path=exit_path,
                        ref=exit_ref,
                        contract_version=(
                            "benchmark_worker_exit_join_observation_v1"
                        ),
                    )
                    process_exitcode = exit_observation.get("exitcode")
                if "worker_process" not in handle_refs:
                    _benchmark_handle_fault_hook("worker_process", "before_call")
                    process_handle_identity = _benchmark_handle_identity(
                        handle_kind="worker_process",
                        launch_identity_anchor=launch_identity_anchor,
                        scope_name=owner["scope_name"],
                    )
                    try:
                        if process is not None:
                            process.close()
                    except BaseException as error:
                        failure = _compose_benchmark_handle_observation(
                            worker_id=worker,
                            handle_kind="worker_process",
                            handle_identity=process_handle_identity,
                            call_result=None,
                            call_error={
                                "error_type": type(error).__name__,
                                "message": str(error),
                            },
                            predecessor_content_sha256=exit_ref["content_sha256"],
                        )
                        _write_json_atomic(
                            self._result_root
                            / f"{worker}.worker-process-close-error.json",
                            failure,
                        )
                        raise
                    observation = _compose_benchmark_handle_observation(
                        worker_id=worker,
                        handle_kind="worker_process",
                        handle_identity=process_handle_identity,
                        call_result="success",
                        call_error=None,
                        predecessor_content_sha256=exit_ref["content_sha256"],
                    )
                    _write_json_atomic(
                        self._result_root / f"{worker}.worker-process-close.json",
                        observation,
                    )
                    handle_refs["worker_process"] = {"content_sha256": observation["content_sha256"]}
                    record["benchmark_handle_refs"] = deepcopy(handle_refs)
                    record["benchmark_process_exitcode"] = process_exitcode
                    _benchmark_handle_fault_hook("worker_process", "after_success")
                event_handle = record.get("benchmark_event_handle")
                if "startup_event" not in handle_refs:
                    _benchmark_handle_fault_hook("startup_event", "before_call")
                    event_identity = _benchmark_handle_identity(
                        handle_kind="startup_event",
                        launch_identity_anchor=launch_identity_anchor,
                        scope_name=owner["scope_name"],
                    )
                    try:
                        if event_handle is not None:
                            win32api.CloseHandle(event_handle)
                    except BaseException as error:
                        failure = _compose_benchmark_handle_observation(
                            worker_id=worker,
                            handle_kind="startup_event",
                            handle_identity=event_identity,
                            call_result=None,
                            call_error={
                                "error_type": type(error).__name__,
                                "message": str(error),
                            },
                            predecessor_content_sha256=handle_refs[
                                "worker_process"
                            ]["content_sha256"],
                        )
                        _write_json_atomic(
                            self._result_root
                            / f"{worker}.startup-event-close-error.json",
                            failure,
                        )
                        raise
                    record["benchmark_event_handle"] = None
                    observation = _compose_benchmark_handle_observation(
                        worker_id=worker,
                        handle_kind="startup_event",
                        handle_identity=event_identity,
                        call_result="success",
                        call_error=None,
                        predecessor_content_sha256=handle_refs[
                            "worker_process"
                        ]["content_sha256"],
                    )
                    _write_json_atomic(
                        self._result_root / f"{worker}.startup-event-close.json",
                        observation,
                    )
                    handle_refs["startup_event"] = {"content_sha256": observation["content_sha256"]}
                    record["benchmark_handle_refs"] = deepcopy(handle_refs)
                    _benchmark_handle_fault_hook("startup_event", "after_success")
                beacon_path = Path(record["benchmark_beacon_path"])
                if "beacon_file" not in handle_refs:
                    _benchmark_handle_fault_hook("beacon_file", "before_call")
                    beacon_identity = _benchmark_handle_identity(
                        handle_kind="beacon_file",
                        launch_identity_anchor=launch_identity_anchor,
                        scope_name=owner["scope_name"],
                    )
                    try:
                        if beacon_path.exists():
                            beacon_path.unlink()
                    except BaseException as error:
                        failure = _compose_benchmark_handle_observation(
                            worker_id=worker,
                            handle_kind="beacon_file",
                            handle_identity=beacon_identity,
                            call_result=None,
                            call_error={
                                "error_type": type(error).__name__,
                                "message": str(error),
                            },
                            predecessor_content_sha256=handle_refs[
                                "startup_event"
                            ]["content_sha256"],
                        )
                        _write_json_atomic(
                            self._result_root
                            / f"{worker}.beacon-file-close-error.json",
                            failure,
                        )
                        raise
                    observation = _compose_benchmark_handle_observation(
                        worker_id=worker,
                        handle_kind="beacon_file",
                        handle_identity=beacon_identity,
                        call_result="success",
                        call_error=None,
                        predecessor_content_sha256=handle_refs[
                            "startup_event"
                        ]["content_sha256"],
                    )
                    _write_json_atomic(
                        self._result_root / f"{worker}.beacon-file-close.json",
                        observation,
                    )
                    handle_refs["beacon_file"] = {"content_sha256": observation["content_sha256"]}
                    record["benchmark_handle_refs"] = deepcopy(handle_refs)
                    _benchmark_handle_fault_hook("beacon_file", "after_success")
                scope = record.get("benchmark_scope")
                if scope is None:
                    raise LearningStageWorkerError("benchmark owner Job handle is unavailable")
                zero_samples = []
                for _ in range(3):
                    members = scope.pids()
                    zero_samples.append(members)
                    if members:
                        if terminate:
                            scope.terminate()
                        time.sleep(0.05)
                if any(zero_samples):
                    raise LearningStageWorkerError("benchmark Job did not reach stable zero")
                stable_zero = seal_immutable({
                    "contract_version": "benchmark_worker_stable_zero_observation_v1",
                    "worker_id": worker,
                    "scope_name": owner["scope_name"],
                    "samples": zero_samples,
                    "predecessor_content_sha256": handle_refs[
                        "beacon_file"
                    ]["content_sha256"],
                })
                _write_json_atomic(
                    self._result_root / f"{worker}.stable-zero.json",
                    stable_zero,
                )
                stable_zero_ref = {
                    "content_sha256": stable_zero["content_sha256"]
                }
                intent = seal_immutable({
                    "contract_version": "benchmark_worker_cleanup_finalization_intent_v1",
                    "supervision_ref": {"content_sha256": record["benchmark_supervision"]["content_sha256"]},
                    "assignment_proven_ref": owner["assignment_observation_ref"],
                    "run_id": run, "stage": stage_value, "operation_id": operation,
                    "worker_id": worker,
                    "supervisor_process_identity": owner["supervisor_process_identity"],
                    "process_identity": process_identity, "scope_name": owner["scope_name"],
                    "gate_state": owner["gate_state"],
                    "exit_observation_ref": deepcopy(exit_ref),
                    "stable_zero_observation_ref": stable_zero_ref,
                    "exact_owned_handles": {"worker_process": "closed_explicitly",
                        "startup_event": "closed_explicitly", "beacon_file": "closed_explicitly",
                        "owner_job": "open"},
                    "exact_handle_observation_refs": handle_refs,
                    "owner_job_handle_close_planned": True,
                    "cleanup_receipt_id": content_sha256({"worker_id": worker, "scope_name": owner["scope_name"]}),
                    "predecessor_content_sha256": owner["content_sha256"],
                })
                intent_path = self._result_root / f"{worker}.benchmark-cleanup-intent.json"
                _write_json_atomic(intent_path, intent)
                owner_body = deepcopy(owner); owner_body.pop("content_sha256")
                owner_body.update({
                    "phase": "cleanup_finalization_intent",
                    "exit_observation_ref": intent["exit_observation_ref"],
                    "stable_zero_observation_ref": stable_zero_ref,
                    "exact_handle_observation_refs": handle_refs,
                    "cleanup_finalization_intent": {
                        "content_sha256": intent["content_sha256"]
                    },
                    "predecessor_content_sha256": owner["content_sha256"],
                })
                owner = seal_immutable(owner_body)
                _write_json_atomic(owner_path, owner)
                _benchmark_handle_fault_hook("owner_job", "before_call")
                owner_job_identity = _benchmark_handle_identity(
                    handle_kind="owner_job",
                    launch_identity_anchor=launch_identity_anchor,
                    scope_name=owner["scope_name"],
                )
                try:
                    scope.close()
                except BaseException as error:
                    failure = _compose_benchmark_handle_observation(
                        worker_id=worker,
                        handle_kind="owner_job",
                        handle_identity=owner_job_identity,
                        call_result=None,
                        call_error={
                            "error_type": type(error).__name__,
                            "message": str(error),
                        },
                        predecessor_content_sha256=intent["content_sha256"],
                    )
                    _write_json_atomic(
                        self._result_root
                        / f"{worker}.owner-job-close-error.json",
                        failure,
                    )
                    raise
                record["benchmark_scope"] = None
                _benchmark_handle_fault_hook("owner_job", "after_success")
                owner_job_observation = _compose_benchmark_handle_observation(
                    worker_id=worker,
                    handle_kind="owner_job",
                    handle_identity=owner_job_identity,
                    call_result="success",
                    call_error=None,
                    predecessor_content_sha256=intent["content_sha256"],
                )
                _write_json_atomic(
                    self._result_root / f"{worker}.owner-job-close.json",
                    owner_job_observation,
                )
                handle_refs["owner_job"] = {
                    "content_sha256": owner_job_observation["content_sha256"]
                }
                job_absence = self._persist_benchmark_absence_observation(
                    worker_id=worker,
                    observation_kind="job",
                    scope_name=owner["scope_name"],
                    process_identity=None,
                    predecessor_content_sha256=owner_job_observation[
                        "content_sha256"
                    ],
                )
                worker_absence = self._persist_benchmark_absence_observation(
                    worker_id=worker,
                    observation_kind="worker",
                    scope_name=None,
                    process_identity=process_identity,
                    predecessor_content_sha256=job_absence["content_sha256"],
                )
                receipt = seal_immutable({
                    "contract_version": "benchmark_worker_cleanup_receipt_v1",
                    "outcome": "verified_exact_worker_exited",
                    "operation_anchor_ref": {"content_sha256": expected_operation_anchor["anchor_identity_sha256"]},
                    "reservation_ref": {"content_sha256": reservation["content_sha256"]},
                    "supervision_ref": {"content_sha256": record["benchmark_supervision"]["content_sha256"]},
                    "run_id": run, "stage": stage_value, "operation_id": operation,
                    "worker_id": worker, "process_identity": process_identity,
                    "assignment_proven_ref": owner["assignment_observation_ref"],
                    "finalization_intent_ref": {"content_sha256": intent["content_sha256"]},
                    "exact_handle_observation_refs": handle_refs,
                    "job_absence_observation_ref": {"content_sha256": job_absence["content_sha256"]},
                    "worker_absence_observation_ref": {"content_sha256": worker_absence["content_sha256"]},
                    "supervisor_absence_observation_ref": None, "reservation_abort_ref": None,
                    "artifact_is_authorization": False, "execute_binding_enabled": False,
                })
                _write_benchmark_cleanup_receipt_atomic(receipt_path, receipt)
                record["status"] = "cancelled" if terminate else record.get("status", "completed")
                self._active_by_operation.pop(key, None)
                return receipt

    def verify_benchmark_worker_cleanup_receipt(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
        receipt: Mapping[str, object],
        expected_operation_anchor: dict[str, Any],
        supervision_root: BenchmarkWorkerSupervisionRoot,
    ) -> dict[str, Any]:
        """在 B1 controller/Registry authority 下重读并验证 cleanup 全部叶子。"""

        root = self._require_benchmark_root(supervision_root)
        worker = _required_text(worker_id, "worker_id")
        run = _required_text(run_id, "run_id")
        stage_value = _required_text(stage, "stage")
        operation = _required_text(operation_id, "operation_id")
        key = (run, stage_value, operation)
        with hold_benchmark_worker_controller(
            supervision_root=root,
            run_id=run,
            stage=stage_value,
            operation_id=operation,
        ):
            with self._lock:
                current = self._benchmark_reservations.get(key)
                if current is None or current.get("worker_id") != worker:
                    raise LearningStageWorkerError(
                        "benchmark cleanup verification identity does not match"
                    )
                original = self._benchmark_reservations_by_ref.get(
                    expected_operation_anchor.get("reservation_ref", {}).get(
                        "content_sha256", ""
                    )
                )
                if original is None:
                    raise LearningStageWorkerError(
                        "benchmark cleanup verification anchor is invalid"
                    )
                validate_benchmark_worker_operation_anchor_v1(
                    expected_operation_anchor,
                    supervision_root=root,
                    expected_reservation=original,
                )
                receipt_path = (
                    self._result_root / f"{worker}.benchmark-cleanup.json"
                )
                persisted = _read_json_object(
                    receipt_path, label="benchmark cleanup receipt"
                )
                validated = _validate_benchmark_cleanup_receipt(
                    persisted,
                    result_root=self._result_root,
                    worker_id=worker,
                    run_id=run,
                    stage=stage_value,
                    operation_id=operation,
                    operation_anchor=expected_operation_anchor,
                    original_reservation=original,
                    current_reservation=current,
                    supervision_root=root,
                )
                if not isinstance(receipt, Mapping) or dict(receipt) != validated:
                    raise LearningStageWorkerError(
                        "benchmark cleanup receipt differs from B1 authority"
                    )
                if validated["outcome"] == "verified_exact_worker_exited":
                    _benchmark_cleanup_replay_live_reattest(
                        result_root=self._result_root,
                        worker_id=worker,
                        run_id=run,
                        stage=stage_value,
                        operation_id=operation,
                        original_reservation=original,
                        validated_receipt=validated,
                    )
                return deepcopy(validated)

    def _complete_benchmark_cleanup_from_intent(
        self, *, record: dict[str, Any], reservation: dict[str, Any],
        expected_operation_anchor: dict[str, Any], receipt_path: Path,
        intent_path: Path,
    ) -> dict[str, Any]:
        """只以已封闭 intent 加 fresh Job/PID absence 续写同一 receipt。"""

        from app.learn.hybrid.windows_process_scope import WindowsProcessScope
        owner = json.loads(Path(record["benchmark_owner_path"]).read_text(encoding="utf-8"))
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        raw = deepcopy(intent); digest = raw.pop("content_sha256", None)
        if content_sha256(raw) != digest or owner.get("cleanup_finalization_intent") != {"content_sha256": digest}:
            raise LearningStageWorkerError("benchmark cleanup finalization intent is invalid")
        owned = intent.get("exact_owned_handles")
        if not isinstance(owned, dict) or any(
            owned.get(kind) != "closed_explicitly"
            for kind in ("worker_process", "startup_event", "beacon_file")
        ) or owned.get("owner_job") != "open":
            raise LearningStageWorkerError("benchmark non-Job handle closure is unproven")
        process_identity = intent["process_identity"]
        job_absence = self._persist_benchmark_absence_observation(
            worker_id=intent["worker_id"],
            observation_kind="job",
            scope_name=intent["scope_name"],
            process_identity=None,
            predecessor_content_sha256=intent["content_sha256"],
        )
        worker_absence = self._persist_benchmark_absence_observation(
            worker_id=intent["worker_id"],
            observation_kind="worker",
            scope_name=None,
            process_identity=process_identity,
            predecessor_content_sha256=job_absence["content_sha256"],
        )
        supervisor_absent = self._benchmark_process_incarnation_absent(
            intent["supervisor_process_identity"]
        )
        supervisor_observation = (
            self._persist_benchmark_absence_observation(
                worker_id=intent["worker_id"],
                observation_kind="supervisor",
                scope_name=None,
                process_identity=intent["supervisor_process_identity"],
                predecessor_content_sha256=worker_absence[
                    "content_sha256"
                ],
            )
            if supervisor_absent
            else None
        )
        receipt = seal_immutable({
            "contract_version": "benchmark_worker_cleanup_receipt_v1",
            "outcome": "verified_exact_worker_exited",
            "operation_anchor_ref": {"content_sha256": expected_operation_anchor["anchor_identity_sha256"]},
            "reservation_ref": {"content_sha256": reservation["content_sha256"]},
            "supervision_ref": intent["supervision_ref"],
            "run_id": intent["run_id"], "stage": intent["stage"],
            "operation_id": intent["operation_id"], "worker_id": intent["worker_id"],
            "process_identity": process_identity,
            "assignment_proven_ref": intent["assignment_proven_ref"],
            "finalization_intent_ref": {"content_sha256": intent["content_sha256"]},
            "exact_handle_observation_refs": intent["exact_handle_observation_refs"],
            "job_absence_observation_ref": {"content_sha256": job_absence["content_sha256"]},
            "worker_absence_observation_ref": {"content_sha256": worker_absence["content_sha256"]},
            "supervisor_absence_observation_ref": (
                {"content_sha256": supervisor_observation["content_sha256"]}
                if supervisor_observation is not None else None
            ),
            "reservation_abort_ref": None, "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        })
        _write_benchmark_cleanup_receipt_atomic(receipt_path, receipt)
        return receipt

    @staticmethod
    def _benchmark_process_incarnation_absent(identity: object) -> bool:
        if not isinstance(identity, dict) or set(identity) != {"pid", "create_time_ns"}:
            raise LearningStageWorkerError("benchmark process identity is invalid")
        import psutil
        try:
            process = psutil.Process(identity["pid"])
            observed = int(round(process.create_time() * 1_000_000_000))
        except psutil.NoSuchProcess:
            return True
        except psutil.Error as error:
            raise LearningStageWorkerError(
                "benchmark process incarnation probe is indeterminate"
            ) from error
        return abs(observed - identity["create_time_ns"]) >= 1_000

    def _persist_benchmark_absence_observation(
        self,
        *,
        worker_id: str,
        observation_kind: str,
        scope_name: str | None,
        process_identity: object,
        predecessor_content_sha256: str,
    ) -> dict[str, Any]:
        if observation_kind == "job":
            from app.learn.hybrid.windows_process_scope import WindowsProcessScope

            try:
                probe = WindowsProcessScope(
                    _required_text(scope_name, "benchmark scope_name"),
                    create=False,
                )
            except BaseException as error:
                code = getattr(error, "winerror", None)
                if code is None and getattr(error, "args", None):
                    first = error.args[0]
                    code = first if isinstance(first, int) else None
                if code != 2:
                    raise LearningStageWorkerError(
                        "benchmark Job absence probe is indeterminate"
                    ) from error
            else:
                try:
                    members = probe.pids()
                except BaseException as error:
                    raise LearningStageWorkerError(
                        "benchmark Job absence probe is indeterminate"
                    ) from error
                finally:
                    try:
                        probe.close()
                    except BaseException as error:
                        raise LearningStageWorkerError(
                            "benchmark Job probe handle close is indeterminate"
                        ) from error
                raise LearningStageWorkerError(
                    f"benchmark Job remains present: {members}"
                )
        elif observation_kind in {"worker", "supervisor"}:
            if not self._benchmark_process_incarnation_absent(process_identity):
                raise LearningStageWorkerError(
                    f"benchmark {observation_kind} incarnation remains present"
                )
        else:
            raise LearningStageWorkerError(
                "benchmark absence observation kind is invalid"
            )
        observation = seal_immutable({
            "contract_version": "benchmark_worker_absence_observation_v1",
            "observation_kind": observation_kind,
            "outcome": "absent",
            "worker_id": worker_id,
            "scope_name": scope_name,
            "process_identity": deepcopy(process_identity),
            "predecessor_content_sha256": predecessor_content_sha256,
        })
        _write_json_atomic(
            self._result_root
            / f"{worker_id}.{observation_kind}-absence.json",
            observation,
        )
        return observation

    @staticmethod
    def _terminate_exact_benchmark_process(identity: object) -> dict[str, Any]:
        if not isinstance(identity, dict) or set(identity) != {"pid", "create_time_ns"}:
            raise LearningStageWorkerError("benchmark pre-assignment process identity is invalid")
        import psutil
        import win32api
        import win32con
        import win32event
        import win32process

        expected_pid = identity["pid"]
        try:
            before = int(round(psutil.Process(expected_pid).create_time() * 1_000_000_000))
        except psutil.Error:
            before = None
        if before is None or abs(before - identity["create_time_ns"]) >= 1_000:
            return {"outcome": "exact_incarnation_already_absent", "process_identity": deepcopy(identity)}
        handle = win32api.OpenProcess(
            int(win32con.PROCESS_QUERY_INFORMATION)
            | int(win32con.PROCESS_TERMINATE)
            | 0x00100000,
            False, expected_pid,
        )
        try:
            after = int(round(psutil.Process(expected_pid).create_time() * 1_000_000_000))
            if abs(after - identity["create_time_ns"]) >= 1_000:
                raise LearningStageWorkerError(
                    "benchmark pre-assignment process incarnation changed"
                )
            win32process.TerminateProcess(handle, 198)
            win32event.WaitForSingleObject(handle, 10_000)
        finally:
            win32api.CloseHandle(handle)
        if not LearningStageWorkerRegistry._benchmark_process_incarnation_absent(identity):
            raise LearningStageWorkerError(
                "benchmark pre-assignment process termination is indeterminate"
            )
        return {"outcome": "verified_exact_incarnation_terminated", "process_identity": deepcopy(identity)}

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
            benchmark_owner_path = self._result_root / f"{worker_id}.benchmark-owner.json"
            if benchmark_owner_path.exists():
                try:
                    benchmark_owner = json.loads(
                        benchmark_owner_path.read_text(encoding="utf-8")
                    )
                except (OSError, UnicodeError, json.JSONDecodeError) as error:
                    raise LearningStageWorkerError(
                        f"benchmark owner journal is unreadable: {error}"
                    ) from error
                if (
                    benchmark_owner.get("contract_version")
                    != "benchmark_worker_owner_journal_v1"
                    or benchmark_owner.get("worker_id") != worker_id
                    or benchmark_owner.get("run_id") != record["run_id"]
                    or benchmark_owner.get("operation_id") != record["operation_id"]
                ):
                    raise LearningStageWorkerError("benchmark owner journal identity mismatch")
                owner_raw = deepcopy(benchmark_owner)
                owner_digest = owner_raw.pop("content_sha256", None)
                if content_sha256(owner_raw) != owner_digest:
                    raise LearningStageWorkerError("benchmark owner journal digest is invalid")
                record["benchmark_owner_path"] = str(benchmark_owner_path)
                record["benchmark_beacon_path"] = str(
                    self._result_root / f"{worker_id}.benchmark-beacon.json"
                )
                record["benchmark_event_handle"] = None
                record["benchmark_scope"] = None
                record["benchmark_reservation"] = self._benchmark_reservations.get(
                    operation_key
                )
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
        if isinstance(record.get("start_cleanup_evidence"), dict):
            payload["start_cleanup_evidence"] = deepcopy(
                record["start_cleanup_evidence"]
            )
        if isinstance(record.get("benchmark_provider_cleanup_ref"), dict):
            payload["benchmark_provider_cleanup_ref"] = deepcopy(
                record["benchmark_provider_cleanup_ref"]
            )
        if isinstance(record.get("benchmark_v2_no_provider_cleanup_ref"), dict):
            payload["benchmark_v2_no_provider_cleanup_ref"] = deepcopy(
                record["benchmark_v2_no_provider_cleanup_ref"]
            )
            payload["benchmark_v2_no_provider_cleanup_state"] = "sealed"
        elif record.get("benchmark_v2_no_provider_cleanup_state") == "sealed":
            payload["benchmark_v2_no_provider_cleanup_state"] = "sealed"
        _write_json_atomic(journal_path, payload)

    def _cleanup_failed_start_or_retain(
        self,
        *,
        operation_key: tuple[str, str, str],
        provider_scope: Any,
        process: Any,
        artifact_paths: tuple[Path, ...],
    ) -> dict[str, Any]:
        try:
            return _cleanup_failed_worker_start(
                provider_scope=provider_scope,
                process=process,
                artifact_paths=artifact_paths,
            )
        except LearningStageWorkerCleanupError as error:
            self._failed_start_cleanups[operation_key] = {
                "provider_scope": provider_scope,
                "process": process,
                "artifact_paths": tuple(artifact_paths),
                "cleanup_evidence": deepcopy(error.cleanup_evidence),
            }
            raise

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
        reserved_markers = sorted(_BENCHMARK_PRIVATE_MARKERS.intersection(payload))
        if reserved_markers:
            raise LearningStageWorkerError(
                f"benchmark worker marker is reserved: {reserved_markers[0]}"
            )
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
            if operation_key in self._failed_start_cleanups:
                raise LearningStageWorkerError(
                    "operation has indeterminate worker start cleanup"
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
                        self._cleanup_failed_start_or_retain(
                            operation_key=operation_key,
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
                        self._cleanup_failed_start_or_retain(
                            operation_key=operation_key,
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
                self._cleanup_failed_start_or_retain(
                    operation_key=operation_key,
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
                self._cleanup_failed_start_or_retain(
                    operation_key=operation_key,
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
            except BaseException as start_error:
                try:
                    cleanup_evidence = self._cleanup_failed_start_or_retain(
                        operation_key=operation_key,
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
                except LearningStageWorkerCleanupError as cleanup_error:
                    record["status"] = "recovery_required"
                    record["start_cleanup_evidence"] = deepcopy(
                        cleanup_error.cleanup_evidence
                    )
                    try:
                        self._persist_record_journal(record)
                    except BaseException as journal_error:
                        cleanup_error.cleanup_evidence["failures"].append({
                            "step": "recovery_journal_write",
                            "error_type": type(journal_error).__name__,
                            "message": str(journal_error),
                        })
                        record["start_cleanup_evidence"] = deepcopy(
                            cleanup_error.cleanup_evidence
                        )
                    raise cleanup_error from start_error
                self._active_by_operation.pop(operation_key, None)
                self._records.pop(worker_id, None)
                workers = self._workers_by_operation.get(operation_key, [])
                if worker_id in workers:
                    workers.remove(worker_id)
                if not workers:
                    self._workers_by_operation.pop(operation_key, None)
                self._workers_by_invocation.pop(invocation_key, None)
                record["start_cleanup_evidence"] = cleanup_evidence
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

    def inspect_completed_result_identity(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
    ) -> dict[str, Any]:
        """在 Registry 锁内只读返回当前已验证完成结果的封闭身份。"""

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
                    "learning stage worker result identity ownership does not match"
                )
            self._refresh_record(record)
            worker_result = record.get("worker_result")
            if (
                record.get("status") != "completed"
                or not isinstance(worker_result, dict)
                or worker_result.get("status") != "completed"
            ):
                raise LearningStageWorkerError(
                    "learning stage worker has no completed result to inspect"
                )
            normal_binding_evidence_ref = _closed_content_sha256_ref(
                worker_result.get("normal_binding_evidence_ref"),
                label="normal binding evidence ref",
            )
            provider_cleanup_evidence_ref = _closed_content_sha256_ref(
                worker_result.get("provider_cleanup_evidence_ref"),
                label="provider cleanup evidence ref",
            )
            return {
                "contract_version": (
                    "learning_stage_worker_completed_result_identity_v1"
                ),
                "status": "completed",
                "worker_id": record["worker_id"],
                "run_id": record["run_id"],
                "stage": record["stage"],
                "operation_id": record["operation_id"],
                "task_kind": record["task_kind"],
                "model_request_id": record["model_request_id"],
                "payload_sha256": record["payload_sha256"],
                "result_sha256": _payload_sha256(worker_result),
                "result_available": True,
                "normal_binding_evidence_ref": normal_binding_evidence_ref,
                "provider_cleanup_evidence_ref": provider_cleanup_evidence_ref,
            }

    def adopt_result(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
        result_validator: Callable[[Mapping[str, object]], None] | None = None,
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
            response = worker_result.get("response")
            if result_validator is not None:
                if not isinstance(response, Mapping):
                    raise LearningStageWorkerError(
                        "learning stage worker adoption response is unavailable"
                    )
                result_validator(deepcopy(dict(response)))

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

    @staticmethod
    def _review_dispatch_presence(record: Mapping[str, object]) -> tuple[bool, bool]:
        def contains_review(value: object) -> bool:
            if isinstance(value, Mapping):
                if value.get("provider") == "review" or "review" in value:
                    return True
                return any(contains_review(child) for child in value.values())
            if isinstance(value, list):
                return any(contains_review(child) for child in value)
            return False

        context_present = False
        receipt_present = False
        sources: list[Mapping[str, object]] = []
        payload = record.get("payload")
        if isinstance(payload, Mapping):
            sources.append(payload)
        worker_result = record.get("worker_result")
        response = (
            worker_result.get("response")
            if isinstance(worker_result, Mapping)
            else None
        )
        if isinstance(response, Mapping):
            sources.append(response)
        for source in sources:
            if "_benchmark_v2_dispatch_context" in source:
                context_present = True
            orchestration = source.get("orchestration")
            private_orchestration = source.get("_hybrid_orchestration")
            for container in (source, orchestration, private_orchestration):
                if not isinstance(container, Mapping):
                    continue
                for name in (
                    "benchmark_v2_provider_dispatch_context_refs",
                    "_benchmark_v2_provider_dispatch_context_refs",
                ):
                    if name in container and contains_review(container[name]):
                        context_present = True
                for name in (
                    "benchmark_v2_provider_dispatch_receipt_refs",
                    "_benchmark_v2_provider_dispatch_receipt_refs",
                ):
                    if name in container and contains_review(container[name]):
                        receipt_present = True
        return context_present, receipt_present

    def attest_completed_review_no_provider_cleanup(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
        service_binding_ref: Mapping[str, object],
        terminal_prepared_continuation_receipt_ref: Mapping[str, object],
        returned_worker_ref: Mapping[str, object],
        worker_cleanup_ref: Mapping[str, object],
    ) -> dict[str, Any]:
        worker = _required_text(worker_id, "worker_id")
        operation_key = (
            _required_text(run_id, "run_id"),
            _required_text(stage, "stage"),
            _required_text(operation_id, "operation_id"),
        )
        binding_ref = _benchmark_exact_ref(
            dict(service_binding_ref),
            "benchmark review no-provider cleanup service binding ref",
        )
        continuation_ref = _benchmark_exact_ref(
            dict(terminal_prepared_continuation_receipt_ref),
            "benchmark review no-provider cleanup continuation receipt ref",
        )
        with self._lock:
            record = self._records.get(worker)
            latest = self._latest_operation_record(operation_key)
            if record is None or latest is not record:
                raise LearningStageWorkerError(
                    "benchmark review no-provider cleanup current ownership differs"
                )
            self._refresh_record(record)
            public = self._public_record(record)
            if (
                record.get("benchmark_v2_no_provider_cleanup_state") == "sealed"
                and not isinstance(
                    record.get("benchmark_v2_no_provider_cleanup_ref"), Mapping
                )
            ):
                raise LearningStageWorkerError(
                    "benchmark review no-provider cleanup persisted proof is missing"
                )
            returned = _validate_benchmark_v2_review_worker_ref(
                returned_worker_ref,
                identity=record,
            )
            cleanup_fields = {
                "contract_version",
                "run_id",
                "stage",
                "operation_id",
                "worker_id",
                "model_request_id",
                "payload_sha256",
                "backend_compute_termination",
                "model_service_compute_termination",
                "cancellation_ref",
                "artifact_is_authorization",
                "execute_binding_enabled",
                "content_sha256",
            }
            cleanup = deepcopy(dict(worker_cleanup_ref))
            if (
                set(cleanup) != cleanup_fields
                or cleanup.get("contract_version")
                != "benchmark_v2_hybrid_worker_cleanup_ref_v1"
                or cleanup.get("backend_compute_termination")
                not in {"not_running", "terminated"}
                or cleanup.get("model_service_compute_termination")
                not in {"request_not_active", "terminated"}
                or any(
                    cleanup.get(name) != record.get(name)
                    for name in (
                        "run_id",
                        "stage",
                        "operation_id",
                        "worker_id",
                        "model_request_id",
                        "payload_sha256",
                    )
                )
                or cleanup.get("artifact_is_authorization") is not False
                or cleanup.get("execute_binding_enabled") is not False
                or cleanup.get("content_sha256") != content_sha256(cleanup)
            ):
                raise LearningStageWorkerError(
                    "benchmark review no-provider cleanup worker cleanup lineage differs"
                )
            _benchmark_exact_ref(
                cleanup.get("cancellation_ref"),
                "benchmark review no-provider cleanup cancellation ref",
            )
            process = record.get("process")
            process_alive = bool(
                process is not None
                and callable(getattr(process, "is_alive", None))
                and process.is_alive()
            )
            expected_role = HYBRID_STAGE_HANDLER_REGISTRY.get(
                str(record.get("task_kind") or ""), {}
            ).get("provider")
            context_present, receipt_present = self._review_dispatch_presence(record)
            artifact_paths = {
                "lease": self._result_root / f"{worker}.provider-lease.json",
                "owner": self._result_root / f"{worker}.provider-owner.json",
                "runtime": self._result_root / f"{worker}.provider-runtime.json",
            }
            provider_journal = self._benchmark_provider_journals.get(operation_key)
            cleanup_journal = self._benchmark_provider_cleanup_journals.get(
                operation_key
            )
            if (
                record.get("task_kind")
                != "panel_learning_hybrid_review_projection"
                or expected_role != "review"
                or record.get("status") != "completed"
                or public.get("runtime_attached") is not False
                or public.get("result_available") is not True
                or public.get("result_adopted") is not True
                or process_alive
                or record.get("provider_scope") is not None
                or record.get("provider_scope_name") is not None
                or record.get("provider_owner_path") is not None
                or record.get("provider_runtime_path") is not None
                or record.get("benchmark_provider_cleanup_ref") is not None
                or provider_journal is not None
                or cleanup_journal is not None
                or context_present
                or receipt_present
                or any(path.exists() for path in artifact_paths.values())
            ):
                raise LearningStageWorkerError(
                    "benchmark review no-provider cleanup live artifact absence differs"
                )
            observation = seal_immutable(
                {
                    "contract_version": (
                        _BENCHMARK_V2_REVIEW_NO_PROVIDER_ABSENCE_CONTRACT
                    ),
                    **{
                        name: record[name]
                        for name in (
                            "run_id",
                            "stage",
                            "operation_id",
                            "worker_id",
                            "model_request_id",
                            "payload_sha256",
                            "task_kind",
                        )
                    },
                    "provider_role": "review",
                    "current_worker_ref": deepcopy(returned),
                    "latest_operation_worker_ref": deepcopy(returned),
                    "review_dispatch_context_absent": True,
                    "review_dispatch_receipt_absent": True,
                    "provider_scope_absent": True,
                    "provider_journal_absent": True,
                    "provider_cleanup_journal_absent": True,
                    "deterministic_provider_lease_artifact_absent": True,
                    "deterministic_provider_owner_artifact_absent": True,
                    "deterministic_provider_runtime_artifact_absent": True,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )
            projection = seal_immutable(
                {
                    "contract_version": (
                        _BENCHMARK_V2_REVIEW_NO_PROVIDER_CLEANUP_CONTRACT
                    ),
                    "status": "cleanup_verified",
                    "outcome": "verified_review_provider_not_applicable",
                    "authority_kind": (
                        "benchmark_v2_workflow_service_review_no_provider_cleanup"
                    ),
                    **{
                        name: record[name]
                        for name in (
                            "run_id",
                            "stage",
                            "operation_id",
                            "worker_id",
                            "model_request_id",
                            "payload_sha256",
                            "task_kind",
                        )
                    },
                    "provider_role": "review",
                    "worker_status": "completed",
                    "runtime_attached": False,
                    "result_available": True,
                    "result_adopted": True,
                    "continuation_phase": "terminal_prepared",
                    "cancellation_backend_termination": cleanup[
                        "backend_compute_termination"
                    ],
                    "cancellation_model_request_termination": cleanup[
                        "model_service_compute_termination"
                    ],
                    "service_binding_ref": binding_ref,
                    "terminal_prepared_continuation_receipt_ref": continuation_ref,
                    "returned_worker_ref": deepcopy(returned),
                    "worker_cleanup_ref": {
                        "content_sha256": cleanup["content_sha256"]
                    },
                    "live_absence_observation": observation,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )
            projection = _validate_benchmark_v2_review_no_provider_cleanup_projection(
                projection,
                identity=record,
            )
            existing = record.get("benchmark_v2_no_provider_cleanup_ref")
            if existing is not None:
                persisted = _validate_benchmark_v2_review_no_provider_cleanup_projection(
                    existing,
                    identity=record,
                )
                if persisted != projection:
                    raise LearningStageWorkerError(
                        "benchmark review no-provider cleanup replay lineage differs"
                    )
                return persisted
            record["benchmark_v2_no_provider_cleanup_ref"] = deepcopy(projection)
            record["benchmark_v2_no_provider_cleanup_state"] = "sealed"
            self._persist_record_journal(record)
            return deepcopy(projection)

    def materialize_completed_hybrid_provider_cleanup(
        self,
        *,
        worker_id: str,
        run_id: str,
        stage: str,
        operation_id: str,
        dispatch_context_ref: Mapping[str, object],
    ) -> dict[str, Any]:
        """只从已完成 worker 的持久化 provider 证据补建清理投影。"""

        worker = _required_text(worker_id, "worker_id")
        operation_key = (
            _required_text(run_id, "run_id"),
            _required_text(stage, "stage"),
            _required_text(operation_id, "operation_id"),
        )
        from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
            read_latest_benchmark_dispatch_receipt,
            validate_benchmark_dispatch_context_ref,
            validate_benchmark_dispatch_receipt_refs,
        )

        try:
            exact_context_ref = validate_benchmark_dispatch_context_ref(
                dispatch_context_ref
            )
        except (TypeError, ValueError) as error:
            raise LearningStageWorkerError(
                "completed Hybrid cleanup dispatch context is invalid"
            ) from error
        provider = exact_context_ref["provider"]
        expected_task_kind = {
            "omni": "panel_learning_hybrid_omni_discovery",
            "qwen": "panel_learning_hybrid_qwen_binding",
            "vista": "panel_learning_calibration_sequence",
        }.get(provider)
        if expected_task_kind is None:
            raise LearningStageWorkerError(
                "completed Hybrid cleanup provider is unsupported"
            )
        context = exact_context_ref["dispatch_context"]
        context_operation = context["operation_ref"]
        if any(
            context_operation[name] != expected
            for name, expected in zip(
                ("run_id", "stage", "operation_id"), operation_key
            )
        ):
            raise LearningStageWorkerError(
                "completed Hybrid cleanup dispatch operation differs"
            )

        with self._lock:
            record = self._records.get(worker)
            latest = self._latest_operation_record(operation_key)
            if record is None or latest is not record:
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup worker ownership does not match"
                )
            self._refresh_record(record)
            public = self._public_record(record)
            result_envelope = record.get("worker_result")
            response = (
                result_envelope.get("response")
                if isinstance(result_envelope, Mapping)
                else None
            )
            if (
                record.get("run_id") != operation_key[0]
                or record.get("stage") != operation_key[1]
                or record.get("operation_id") != operation_key[2]
                or record.get("task_kind") != expected_task_kind
                or public.get("status") != "completed"
                or public.get("runtime_attached") is not False
                or public.get("result_available") is not True
                or not isinstance(response, Mapping)
                or response.get("contract_version")
                != "learning_hybrid_managed_stage_result_v1"
                or response.get("learning_pipeline_mode") != "hybrid_v1_1"
                or response.get("task_kind") != record.get("task_kind")
                or response.get("outcome") == "completed"
            ):
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup worker is not terminal-safe"
                )
            orchestration = response.get("orchestration")
            if provider == "vista":
                if (
                    public.get("result_adopted") is not True
                    or not isinstance(record.get("result_adoption"), Mapping)
                    or response.get("outcome") != "failed"
                    or not isinstance(orchestration, Mapping)
                    or orchestration.get("benchmark_v2_vista_batch_count") != 0
                ):
                    raise LearningStageWorkerError(
                        "completed Hybrid VISTA cleanup adoption is invalid"
                    )
                try:
                    _validated_result_adoption(
                        dict(record["result_adoption"]),
                        identity={
                            name: str(record[name])
                            for name in (
                                "worker_id",
                                "run_id",
                                "stage",
                                "operation_id",
                                "task_kind",
                                "model_request_id",
                                "payload_sha256",
                            )
                        },
                    )
                except (TypeError, ValueError) as error:
                    raise LearningStageWorkerError(
                        "completed Hybrid VISTA cleanup adoption is invalid"
                    ) from error
                result_contexts = (
                    orchestration.get("benchmark_v2_provider_dispatch_context_refs")
                )
                receipt_refs = (
                    orchestration.get("benchmark_v2_provider_dispatch_receipt_refs")
                )
                has_vista_receipt = (
                    isinstance(receipt_refs, Mapping)
                    and "vista" in receipt_refs
                ) or (
                    isinstance(receipt_refs, list)
                    and any(
                        isinstance(ref, Mapping) and ref.get("provider") == "vista"
                        for ref in receipt_refs
                    )
                )
                if (
                    not isinstance(result_contexts, Mapping)
                    or set(result_contexts) != {"omni", "qwen"}
                    or "vista" in result_contexts
                    or orchestration.get("vista_cleanup_receipt") is not None
                ) or has_vista_receipt:
                    raise LearningStageWorkerError(
                        "completed Hybrid VISTA cleanup has dispatch evidence"
                    )
                operation_identity = {
                    name: deepcopy(context_operation[name])
                    for name in (
                        "run_id",
                        "stage",
                        "operation_id",
                        "window_binding_ref",
                        "capture_ref",
                    )
                }
                try:
                    exact_pre_vista_contexts = {
                        expected_provider: validate_benchmark_dispatch_context_ref(
                            result_contexts.get(expected_provider)
                        )
                        for expected_provider in ("omni", "qwen")
                    }
                    if any(
                        exact_pre_vista_contexts[name]["provider"] != name
                        or any(
                            exact_pre_vista_contexts[name]["dispatch_context"][
                                "operation_ref"
                            ][field]
                            != operation_identity[field]
                            for field in operation_identity
                        )
                        or exact_pre_vista_contexts[name]["dispatch_context"][
                            "receipt_journal_path"
                        ]
                        != context["receipt_journal_path"]
                        for name in ("omni", "qwen")
                    ):
                        raise ValueError("VISTA pre-dispatch contexts differ")
                    validate_benchmark_dispatch_receipt_refs(
                        receipt_journal_path=Path(context["receipt_journal_path"]),
                        receipt_refs=receipt_refs,
                        operation_identity=operation_identity,
                        expected_provider_counts={"omni": 1, "qwen": 1},
                        expected_dispatch_contexts={
                            name: exact_pre_vista_contexts[name]["dispatch_context"]
                            for name in ("omni", "qwen")
                        },
                    )
                except (OSError, TypeError, ValueError) as error:
                    raise LearningStageWorkerError(
                        "completed Hybrid VISTA cleanup dispatch evidence is invalid"
                    ) from error
                if read_latest_benchmark_dispatch_receipt(
                    dispatch_context=context
                ) is not None:
                    raise LearningStageWorkerError(
                        "completed Hybrid VISTA cleanup dispatch receipt is present"
                    )
                reconciliation = _reconcile_supervised_vista_record(record)
                from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
                    project_authoritative_vista_supervisor_cleanup,
                )

                try:
                    if "recovered_lease_ref" in reconciliation:
                        authoritative = (
                            _project_vista_no_acquisition_reconciliation(
                                record, reconciliation
                            )
                        )
                    else:
                        authoritative = project_authoritative_vista_supervisor_cleanup(
                            record=record,
                            supervisor_reconciliation=reconciliation,
                        )
                    cooperative_cleanup = _hybrid_vista_cleanup_evidence(record)
                except (LearningStageWorkerError, TypeError, ValueError) as error:
                    raise LearningStageWorkerError(
                        "completed Hybrid VISTA cleanup evidence is invalid"
                    ) from error
                exact_receipt = cooperative_cleanup.get("vista_cleanup_receipt")
                lifecycle = response.get("lifecycle_evidence")
                managed_result = response.get("result")
                result_lifecycle = (
                    managed_result.get("model_lifecycle")
                    if isinstance(managed_result, Mapping)
                    else None
                )
                lifecycle_receipt = (
                    lifecycle.get("vista_cleanup_receipt")
                    if isinstance(lifecycle, Mapping)
                    else None
                )
                result_receipt = (
                    result_lifecycle.get("vista_cleanup_receipt")
                    if isinstance(result_lifecycle, Mapping)
                    else None
                )
                identity_fields = (
                    "run_id",
                    "stage",
                    "operation_id",
                    "worker_id",
                    "model_request_id",
                    "payload_sha256",
                )
                if authoritative.get("outcome") == "verified_not_acquired":
                    if (
                        set(authoritative)
                        != {
                            "outcome", "acquisition_owner_ref",
                            "runtime_owner_ref", "recovered_lease_ref",
                        }
                        or cooperative_cleanup
                        != {
                            "contract_version": (
                                "hybrid_vista_cooperative_cleanup_v1"
                            ),
                            "cleanup_status": "not_acquired",
                            "vista_cleanup_receipt": None,
                        }
                        or exact_receipt is not None
                    ):
                        raise LearningStageWorkerError(
                            "completed Hybrid VISTA cleanup evidence differs"
                        )
                    projection_specific = {
                        "outcome": "verified_not_acquired",
                        "provider": "vista",
                        "task_kind": "panel_learning_calibration_sequence",
                        "acquisition_owner_ref": deepcopy(
                            dict(authoritative["acquisition_owner_ref"])
                        ),
                        "runtime_owner_ref": deepcopy(
                            dict(authoritative["runtime_owner_ref"])
                        ),
                        "recovered_lease_ref": deepcopy(
                            dict(authoritative["recovered_lease_ref"])
                        ),
                    }
                else:
                    runtime_identity = authoritative.get("runtime_identity")
                    acquisition_owner_ref = authoritative.get(
                        "acquisition_owner_ref"
                    )
                    authoritative_receipt = authoritative.get("cleanup_receipt")
                    if (
                        cooperative_cleanup.get("cleanup_status") != "verified"
                        or not isinstance(exact_receipt, Mapping)
                        or not isinstance(managed_result, Mapping)
                        or managed_result.get("contract_version")
                        != "learning_hybrid_stage_failure_v1"
                        or not isinstance(result_lifecycle, Mapping)
                        or (
                            isinstance(lifecycle_receipt, Mapping)
                            and isinstance(result_receipt, Mapping)
                            and lifecycle_receipt != result_receipt
                        )
                        or exact_receipt != authoritative_receipt
                        or not isinstance(runtime_identity, Mapping)
                        or not isinstance(acquisition_owner_ref, Mapping)
                        or not isinstance(
                            runtime_identity.get("content_sha256"), str
                        )
                        or not isinstance(
                            acquisition_owner_ref.get("content_sha256"), str
                        )
                        or not isinstance(exact_receipt.get("content_sha256"), str)
                    ):
                        raise LearningStageWorkerError(
                            "completed Hybrid VISTA cleanup evidence differs"
                        )
                    projection_specific = {
                        "outcome": "verified_exact_process_exited",
                        "acquisition_owner_ref": deepcopy(
                            dict(acquisition_owner_ref)
                        ),
                        "runtime_owner_ref": {
                            "content_sha256": runtime_identity["content_sha256"]
                        },
                        "cleanup_receipt_ref": {
                            "content_sha256": exact_receipt["content_sha256"]
                        },
                    }
                context_owner_ref = {
                    "content_sha256": context["content_sha256"]
                }
                projection_body = {
                    "contract_version": "benchmark_provider_cleanup_ref_v1",
                    "status": "cleanup_verified",
                    "authority_kind": (
                        "benchmark_v2_workflow_service_dispatch_cleanup"
                    ),
                    **{name: str(record[name]) for name in identity_fields},
                    "reservation_ref": deepcopy(context_owner_ref),
                    "acquisition_intent_ref": deepcopy(context_owner_ref),
                    **projection_specific,
                }
                projection = seal_immutable(projection_body)
                projection = _validate_hybrid_benchmark_provider_cleanup_projection(
                    projection, identity=record
                )
                existing = record.get("benchmark_provider_cleanup_ref")
                if existing is not None and not isinstance(existing, Mapping):
                    raise LearningStageWorkerError(
                        "completed Hybrid VISTA cleanup projection is invalid"
                    )
                if isinstance(existing, Mapping):
                    validated_existing = (
                        _validate_hybrid_benchmark_provider_cleanup_projection(
                            existing,
                            identity=record,
                        )
                    )
                    if validated_existing != projection:
                        raise LearningStageWorkerError(
                            "completed Hybrid cleanup projection replay differs"
                        )
                else:
                    record["benchmark_provider_cleanup_ref"] = deepcopy(projection)
                    self._persist_record_journal(record)
                return deepcopy(projection)
            result_contexts = (
                orchestration.get("benchmark_v2_provider_dispatch_context_refs")
                if isinstance(orchestration, Mapping)
                else None
            )
            if provider == "qwen":
                if (
                    not isinstance(result_contexts, Mapping)
                    or set(result_contexts) != {"omni", "qwen"}
                ):
                    raise LearningStageWorkerError(
                        "completed Hybrid Qwen cleanup worker contexts are invalid"
                    )
                try:
                    exact_result_contexts = {
                        expected_provider: validate_benchmark_dispatch_context_ref(
                            result_contexts.get(expected_provider)
                        )
                        for expected_provider in ("omni", "qwen")
                    }
                    if (
                        exact_result_contexts["qwen"] != exact_context_ref
                        or any(
                            exact_result_contexts[expected_provider][
                                "dispatch_context"
                            ]["operation_ref"][field]
                            != context_operation[field]
                            or exact_result_contexts[expected_provider][
                                "dispatch_context"
                            ]["receipt_journal_path"]
                            != context["receipt_journal_path"]
                            for expected_provider in ("omni", "qwen")
                            for field in (
                                "run_id",
                                "stage",
                                "operation_id",
                                "window_binding_ref",
                                "capture_ref",
                            )
                        )
                    ):
                        raise ValueError("Qwen dispatch contexts differ")
                    validate_benchmark_dispatch_receipt_refs(
                        receipt_journal_path=Path(context["receipt_journal_path"]),
                        receipt_refs=orchestration.get(
                            "benchmark_v2_provider_dispatch_receipt_refs"
                        ),
                        operation_identity={
                            name: deepcopy(context_operation[name])
                            for name in (
                                "run_id",
                                "stage",
                                "operation_id",
                                "window_binding_ref",
                                "capture_ref",
                            )
                        },
                        expected_provider_counts={"omni": 1, "qwen": 1},
                        expected_dispatch_contexts={
                            name: exact_result_contexts[name]["dispatch_context"]
                            for name in ("omni", "qwen")
                        },
                    )
                except (OSError, TypeError, ValueError) as error:
                    raise LearningStageWorkerError(
                        "completed Hybrid Qwen cleanup dispatch evidence is invalid"
                    ) from error
            else:
                result_context_ref = (
                    result_contexts.get(provider)
                    if isinstance(result_contexts, Mapping)
                    else None
                )
                try:
                    exact_result_context_ref = validate_benchmark_dispatch_context_ref(
                        result_context_ref
                    )
                except (TypeError, ValueError) as error:
                    raise LearningStageWorkerError(
                        "completed Hybrid cleanup worker context is invalid"
                    ) from error
                if exact_result_context_ref != exact_context_ref:
                    raise LearningStageWorkerError(
                        "completed Hybrid cleanup service and worker contexts differ"
                    )
                operation_identity = {
                    name: deepcopy(context_operation[name])
                    for name in (
                        "run_id",
                        "stage",
                        "operation_id",
                        "window_binding_ref",
                        "capture_ref",
                    )
                }
                try:
                    validate_benchmark_dispatch_receipt_refs(
                        receipt_journal_path=Path(context["receipt_journal_path"]),
                        receipt_refs=(
                            orchestration.get(
                                "benchmark_v2_provider_dispatch_receipt_refs"
                            )
                            if isinstance(orchestration, Mapping)
                            else None
                        ),
                        operation_identity=operation_identity,
                        expected_provider_counts={provider: 1},
                        expected_dispatch_contexts={provider: context},
                    )
                except (OSError, TypeError, ValueError) as error:
                    raise LearningStageWorkerError(
                        "completed Hybrid cleanup dispatch receipt is invalid"
                    ) from error

            if provider == "qwen":
                if (
                    public.get("result_adopted") is not True
                    or not isinstance(record.get("result_adoption"), Mapping)
                ):
                    raise LearningStageWorkerError(
                        "completed Hybrid Qwen cleanup adoption is invalid"
                    )
                try:
                    _validated_result_adoption(
                        dict(record["result_adoption"]),
                        identity={
                            name: str(record[name])
                            for name in (
                                "worker_id",
                                "run_id",
                                "stage",
                                "operation_id",
                                "task_kind",
                                "model_request_id",
                                "payload_sha256",
                            )
                        },
                    )
                except (TypeError, ValueError) as error:
                    raise LearningStageWorkerError(
                        "completed Hybrid Qwen cleanup adoption is invalid"
                    ) from error
                _detach_proven_dead_worker_process(record)
                reconciliation = _reconcile_hybrid_provider_scope_record(record)
                provider_cleanup_evidence = reconciliation.get(
                    "provider_cleanup_evidence"
                )
                if (
                    reconciliation.get("contract_version")
                    != "hybrid_supervisor_reconciliation_v3"
                    or reconciliation.get("status") != "verified"
                    or not isinstance(provider_cleanup_evidence, Mapping)
                    or provider_cleanup_evidence.get("contract_version")
                    != "hybrid_qwen_abnormal_reconciliation_v1"
                    or provider_cleanup_evidence.get("status") != "verified"
                ):
                    raise LearningStageWorkerError(
                        "completed Hybrid Qwen cleanup reconciliation is indeterminate"
                    )
                record["supervisor_reconciliation"] = deepcopy(reconciliation)
                projection = self._compose_hybrid_benchmark_provider_cleanup(
                    record=record,
                    worker_termination={
                        "worker_id": record["worker_id"],
                        "model_request_id": record["model_request_id"],
                    },
                    dispatch_context=context,
                )
                if projection is None:
                    raise LearningStageWorkerError(
                        "completed Hybrid cleanup projection is unavailable"
                    )
                existing = record.get("benchmark_provider_cleanup_ref")
                if isinstance(existing, Mapping):
                    validated_existing = (
                        _validate_hybrid_benchmark_provider_cleanup_projection(
                            existing,
                            identity=record,
                        )
                    )
                    if validated_existing != projection:
                        raise LearningStageWorkerError(
                            "completed Hybrid cleanup projection replay differs"
                        )
                else:
                    record["benchmark_provider_cleanup_ref"] = deepcopy(projection)
                    self._persist_record_journal(record)
                return deepcopy(projection)

            runtime_path = record.get("provider_runtime_path")
            if not isinstance(runtime_path, str) or not runtime_path:
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup runtime owner is missing"
                )
            from app.learn.recognition.uei.omniparser_shadow_adapter import (
                _load_omniparser_owner,
            )

            try:
                runtime_owner = _load_omniparser_owner(Path(runtime_path))
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup runtime owner is invalid"
                ) from error
            if runtime_owner.get("state") != "released":
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup runtime owner is not released"
                )
            reconciliation = _reconcile_hybrid_provider_scope_record(record)
            observation = reconciliation.get("provider_cleanup_evidence")
            cleanup_observation = (
                observation.get("cleanup_observation")
                if isinstance(observation, Mapping)
                else None
            )
            if (
                reconciliation.get("status") != "verified"
                or not isinstance(cleanup_observation, Mapping)
                or cleanup_observation.get("cleanup_status") != "verified"
                or cleanup_observation.get("inventory_observable") is not True
                or cleanup_observation.get("provider_processes_after") != []
                or cleanup_observation.get("orphan_descendant_identities") != []
                or cleanup_observation.get("active_listeners_after") != []
                or cleanup_observation.get("lease_files_after") != []
            ):
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup provider state is indeterminate"
                )
            scope_name = str(cleanup_observation.get("process_scope_name") or "")
            job_probe = _benchmark_cleanup_replay_job_probe(scope_name)
            if job_probe.get("outcome") != "job_name_absent":
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup Job absence is indeterminate"
                )
            identities = [
                cleanup_observation.get("process_identity"),
                *list(cleanup_observation.get("descendant_identities") or []),
            ]
            exact_identities = [
                _validate_exact_benchmark_process_identity(
                    identity,
                    label="completed Hybrid cleanup process",
                )
                for identity in identities
            ]
            if len(
                {
                    (identity["pid"], identity["create_time_ns"])
                    for identity in exact_identities
                }
            ) != len(exact_identities):
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup process identities are duplicated"
                )
            for identity in exact_identities:
                process_probe = _benchmark_cleanup_replay_process_probe(identity)
                if process_probe.get("outcome") not in {
                    "no_such_process",
                    "different_incarnation",
                }:
                    raise LearningStageWorkerError(
                        "completed Hybrid cleanup process absence is indeterminate"
                    )
            lease_path = cleanup_observation.get("lease_path")
            if isinstance(lease_path, str) and lease_path and Path(lease_path).exists():
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup resource lease is present"
                )
            projection = self._compose_hybrid_benchmark_provider_cleanup(
                record=record,
                worker_termination={
                    "worker_id": record["worker_id"],
                    "model_request_id": record["model_request_id"],
                },
                dispatch_context=context,
            )
            if projection is None:
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup projection is unavailable"
                )
            existing = record.get("benchmark_provider_cleanup_ref")
            if isinstance(existing, Mapping):
                validated_existing = (
                    _validate_hybrid_benchmark_provider_cleanup_projection(
                        existing,
                        identity=record,
                    )
                )
                if validated_existing != projection:
                    raise LearningStageWorkerError(
                        "completed Hybrid cleanup projection replay differs"
                    )
            else:
                record["benchmark_provider_cleanup_ref"] = deepcopy(projection)
                self._persist_record_journal(record)
            return deepcopy(projection)

    def cancel_by_operation(
        self,
        *,
        run_id: str,
        stage: str,
        operation_id: str,
    ) -> dict[str, Any]:
        result = self._cancel_by_operation_impl(
            run_id=run_id,
            stage=stage,
            operation_id=operation_id,
        )
        operation_key = (str(run_id).strip(), str(stage).strip(), str(operation_id).strip())
        with self._lock:
            record = self._latest_operation_record(operation_key)
            if record is None:
                return result
            existing = record.get("benchmark_provider_cleanup_ref")
            if isinstance(existing, Mapping):
                projection = _validate_hybrid_benchmark_provider_cleanup_projection(
                    existing, identity=record
                )
            else:
                projection = self._compose_hybrid_benchmark_provider_cleanup(
                    record=record,
                    worker_termination=result,
                )
                if projection is not None:
                    record["benchmark_provider_cleanup_ref"] = deepcopy(projection)
                    self._persist_record_journal(record)
        if projection is not None:
            result = deepcopy(result)
            result["benchmark_provider_cleanup_ref"] = deepcopy(projection)
        return result

    def _compose_hybrid_benchmark_provider_cleanup(
        self,
        *,
        record: Mapping[str, object],
        worker_termination: Mapping[str, object],
        dispatch_context: Mapping[str, object] | None = None,
    ) -> dict[str, Any] | None:
        payload = record.get("payload")
        context_value = (
            dispatch_context
            if dispatch_context is not None
            else payload.get("_benchmark_v2_dispatch_context")
            if isinstance(payload, Mapping)
            else None
        )
        if context_value is None:
            return None
        from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
            project_authoritative_benchmark_provider_cleanup,
            read_latest_benchmark_dispatch_receipt,
            validate_benchmark_dispatch_context,
        )

        context = validate_benchmark_dispatch_context(context_value)
        provider = str(context["provider"])
        expected_provider = {
            "panel_learning_hybrid_omni_discovery": "omni",
            "panel_learning_hybrid_qwen_binding": "qwen",
            "panel_learning_calibration_sequence": "vista",
        }.get(str(record.get("task_kind") or ""))
        if expected_provider != provider:
            raise LearningStageWorkerError(
                "benchmark Hybrid provider cleanup context differs from worker task"
            )
        receipt = read_latest_benchmark_dispatch_receipt(
            dispatch_context=context
        )
        if receipt is None:
            return None
        identity_fields = (
            "run_id",
            "stage",
            "operation_id",
            "worker_id",
            "model_request_id",
            "payload_sha256",
        )
        if any(
            not isinstance(record.get(name), str) or not record.get(name)
            for name in identity_fields
        ) or any(
            worker_termination.get(name) != record[name]
            for name in ("worker_id", "model_request_id")
        ):
            raise LearningStageWorkerError(
                "benchmark Hybrid provider cleanup worker identity differs"
            )
        authoritative = project_authoritative_benchmark_provider_cleanup(
            provider=provider,
            record=record,
            worker_termination=worker_termination,
        )
        if authoritative is None:
            return None
        runtime_owner_ref = deepcopy(receipt["provider_runtime_attestation_ref"])
        if authoritative["runtime_identity"]["content_sha256"] != runtime_owner_ref[
            "content_sha256"
        ]:
            return None
        cleanup_receipt = seal_immutable(
            {
                "contract_version": (
                    "benchmark_v2_hybrid_provider_cleanup_binding_v1"
                ),
                "provider": provider,
                **{name: str(record[name]) for name in identity_fields},
                "dispatch_context_ref": {
                    "content_sha256": context["content_sha256"]
                },
                "dispatch_receipt_ref": {
                    "content_sha256": receipt["content_sha256"]
                },
                "runtime_owner_ref": runtime_owner_ref,
                "predecessor_content_sha256": receipt["content_sha256"],
                "authoritative_cleanup_contract": authoritative[
                    "authoritative_cleanup_contract"
                ],
                "authoritative_cleanup_ref": deepcopy(
                    authoritative["authoritative_cleanup_ref"]
                ),
                "outcome": "verified_exact_process_exited",
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        receipt_path = self._result_root / (
            f"{record['worker_id']}.benchmark-v2-hybrid-provider-cleanup.json"
        )
        if receipt_path.exists():
            persisted = _read_json_object(
                receipt_path,
                label="benchmark Hybrid provider cleanup receipt",
            )
            if persisted != cleanup_receipt:
                raise LearningStageWorkerError(
                    "benchmark Hybrid provider cleanup receipt replay differs"
                )
        else:
            _write_json_create_only(receipt_path, cleanup_receipt)
        projection = seal_immutable(
            {
                "contract_version": "benchmark_provider_cleanup_ref_v1",
                "status": "cleanup_verified",
                "outcome": "verified_exact_process_exited",
                "authority_kind": (
                    "benchmark_v2_workflow_service_dispatch_cleanup"
                ),
                **{name: str(record[name]) for name in identity_fields},
                "reservation_ref": {
                    "content_sha256": context["content_sha256"]
                },
                "acquisition_owner_ref": {
                    "content_sha256": receipt["content_sha256"]
                },
                "acquisition_intent_ref": runtime_owner_ref,
                "runtime_owner_ref": runtime_owner_ref,
                "cleanup_receipt_ref": {
                    "content_sha256": cleanup_receipt["content_sha256"]
                },
            }
        )
        return _validate_hybrid_benchmark_provider_cleanup_projection(
            projection, identity=record
        )

    def _cancel_by_operation_impl(
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
        if (
            record.get("status") == "recovery_required"
            and isinstance(record.get("start_cleanup_evidence"), dict)
            and record["start_cleanup_evidence"].get("cleanup_status")
            == "indeterminate"
        ):
            return
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
                "benchmark_event_handle",
                "benchmark_scope",
                "benchmark_anchor",
                "benchmark_supervision",
                "benchmark_reservation",
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


def _detach_proven_dead_worker_process(record: dict[str, Any]) -> None:
    process = record.get("process")
    if process is None:
        return
    is_alive = getattr(process, "is_alive", None)
    join = getattr(process, "join", None)
    if not callable(is_alive) or not callable(join):
        raise LearningStageWorkerError(
            "completed Hybrid cleanup worker process state is indeterminate"
        )
    try:
        if is_alive():
            raise LearningStageWorkerError(
                "completed Hybrid cleanup worker process remains active"
            )
        join(timeout=0)
        exitcode = getattr(process, "exitcode", None)
        if is_alive() or isinstance(exitcode, bool) or not isinstance(exitcode, int):
            raise LearningStageWorkerError(
                "completed Hybrid cleanup worker process state is indeterminate"
            )
        close = getattr(process, "close", None)
        if close is not None:
            if not callable(close):
                raise LearningStageWorkerError(
                    "completed Hybrid cleanup worker process state is indeterminate"
                )
            close()
    except LearningStageWorkerError:
        raise
    except Exception as error:
        raise LearningStageWorkerError(
            "completed Hybrid cleanup worker process state is indeterminate"
        ) from error
    record["process"] = None


def _cleanup_failed_worker_start(
    *,
    provider_scope: Any,
    process: Any,
    artifact_paths: tuple[Path, ...],
) -> dict[str, Any]:
    """清理尚未成功启动的 worker 所有权与精确工件。"""

    failures: list[dict[str, str]] = []

    def record_failure(step: str, error: BaseException) -> None:
        failures.append({
            "step": step,
            "error_type": type(error).__name__,
            "message": str(error),
        })

    if process is not None:
        try:
            is_alive = getattr(process, "is_alive", None)
            alive_before = bool(callable(is_alive) and is_alive())
        except BaseException as error:
            alive_before = True
            record_failure("process_observe_before", error)
        if alive_before:
            try:
                terminate = getattr(process, "terminate", None)
                if callable(terminate):
                    terminate()
                else:
                    raise RuntimeError("process terminate is unavailable")
            except BaseException as error:
                record_failure("process_terminate", error)
            try:
                join = getattr(process, "join", None)
                if callable(join):
                    join(timeout=5)
                else:
                    raise RuntimeError("process join is unavailable")
            except BaseException as error:
                record_failure("process_join", error)
        try:
            is_alive = getattr(process, "is_alive", None)
            if callable(is_alive) and is_alive():
                raise RuntimeError("worker process remains active")
        except BaseException as error:
            record_failure("process_observe_after", error)
        try:
            close = getattr(process, "close", None)
            if callable(close):
                close()
        except BaseException as error:
            record_failure("process_close", error)
    scope_name = str(getattr(provider_scope, "name", "") or "")
    if provider_scope is not None:
        try:
            provider_scope.close()
        except BaseException as error:
            record_failure("provider_scope_close", error)
    if not failures and scope_name:
        try:
            from app.learn.hybrid.windows_process_scope import (
                observe_process_scope_cleanup,
            )

            scope_evidence = observe_process_scope_cleanup(
                scope_name,
                terminate=False,
                stable_zero_observations=3,
            )
            if scope_evidence.get("cleanup_status") != "verified":
                raise RuntimeError("provider scope is not reusable")
        except BaseException as error:
            record_failure("provider_scope_reuse_observation", error)
    else:
        scope_evidence = None
    if not failures:
        for path in artifact_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                record_failure("artifact_unlink", error)
    artifacts_after = [
        str(path.resolve()) for path in artifact_paths if path.exists()
    ]
    evidence = {
        "contract_version": "hybrid_worker_start_cleanup_v1",
        "cleanup_status": "indeterminate" if failures else "verified",
        "process_present": process is not None,
        "provider_scope_name": scope_name or None,
        "provider_scope_cleanup": scope_evidence,
        "artifact_paths_after": artifacts_after,
        "failures": failures,
    }
    if failures:
        raise LearningStageWorkerCleanupError(evidence)
    return evidence


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


def _benchmark_cleanup_replay_job_probe(scope_name: str) -> dict[str, Any]:
    """只读检查 unique named Job 当前是否仍存在，并关闭 probe handle。"""

    from app.learn.hybrid.windows_process_scope import WindowsProcessScope

    scope = None
    members: list[int] | None = None
    error_value: dict[str, Any] | None = None
    close_state = "not_opened"
    try:
        scope = WindowsProcessScope(
            _required_text(scope_name, "benchmark cleanup replay scope_name"),
            create=False,
        )
    except Exception as error:
        code = getattr(error, "winerror", None)
        if code is None and getattr(error, "args", None):
            first = error.args[0]
            code = first if isinstance(first, int) else None
        if code == 2:
            outcome = "job_name_absent"
        else:
            outcome = "indeterminate"
            error_value = {
                "stage": "open",
                "error_type": type(error).__name__,
                "message": str(error),
                "winerror": code,
            }
    else:
        try:
            members = scope.pids()
            outcome = "job_name_present"
        except Exception as error:
            outcome = "indeterminate"
            error_value = {
                "stage": "query",
                "error_type": type(error).__name__,
                "message": str(error),
                "winerror": getattr(error, "winerror", None),
            }
        finally:
            try:
                scope.close()
                close_state = "closed"
            except Exception as error:
                close_state = "error"
                close_error = {
                    "stage": "close",
                    "error_type": type(error).__name__,
                    "message": str(error),
                    "winerror": getattr(error, "winerror", None),
                }
                error_value = (
                    close_error
                    if error_value is None
                    else {
                        "primary_error": error_value,
                        "close_error": close_error,
                    }
                )
                outcome = "indeterminate"
    return seal_immutable({
        "contract_version": "benchmark_worker_cleanup_replay_job_probe_v1",
        "scope_name": scope_name,
        "outcome": outcome,
        "member_pids": members,
        "temporary_handle_close": close_state,
        "error": error_value,
    })


def _benchmark_cleanup_replay_process_probe(
    identity: object,
) -> dict[str, Any]:
    """只读复核历史 cleanup 所绑定的 exact process incarnation。"""

    import psutil

    expected = _validate_exact_benchmark_process_identity(
        identity,
        label="benchmark cleanup replay worker",
    )
    observed_identity: dict[str, int] | None = None
    error_value: dict[str, str] | None = None
    try:
        process = psutil.Process(expected["pid"])
        observed_identity = {
            "pid": expected["pid"],
            "create_time_ns": int(
                round(process.create_time() * 1_000_000_000)
            ),
        }
    except psutil.NoSuchProcess:
        outcome = "no_such_process"
    except Exception as error:
        outcome = "indeterminate"
        error_value = {
            "error_type": type(error).__name__,
            "message": str(error),
        }
    else:
        outcome = (
            "same_incarnation_live"
            if abs(
                observed_identity["create_time_ns"]
                - expected["create_time_ns"]
            ) < 1_000
            else "different_incarnation"
        )
    return seal_immutable({
        "contract_version": (
            "benchmark_worker_cleanup_replay_process_probe_v1"
        ),
        "expected_process_identity": expected,
        "observed_process_identity": observed_identity,
        "outcome": outcome,
        "error": error_value,
    })


def _benchmark_cleanup_replay_live_reattest(
    *,
    result_root: Path,
    worker_id: str,
    run_id: str,
    stage: str,
    operation_id: str,
    original_reservation: dict[str, Any],
    validated_receipt: dict[str, Any],
) -> dict[str, Any]:
    """在返回历史 receipt 前只读复核 unique Job 与 exact worker 当前均缺席。"""

    from app.learn.hybrid.windows_process_scope import (
        benchmark_worker_scope_name_v1,
    )

    launch_anchor = _read_json_object(
        result_root
        / f"{worker_id}.benchmark-launch-identity-anchor.json",
        label="benchmark cleanup replay launch identity anchor",
    )
    if (
        launch_anchor.get("contract_version")
        != "benchmark_worker_launch_identity_anchor_v1"
        or content_sha256(launch_anchor)
        != launch_anchor.get("content_sha256")
    ):
        raise LearningStageWorkerError(
            "benchmark cleanup replay launch identity anchor is invalid"
        )
    process_identity = _validate_exact_benchmark_process_identity(
        launch_anchor.get("process_identity"),
        label="benchmark cleanup replay worker",
    )
    if validated_receipt.get("process_identity") != process_identity:
        raise LearningStageWorkerError(
            "benchmark cleanup replay process identity is invalid"
        )
    scope_name = benchmark_worker_scope_name_v1(
        authority_kind=original_reservation["authority_kind"],
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
        worker_id=worker_id,
        payload_sha256=original_reservation["payload_sha256"],
        execution_nonce=original_reservation["execution_nonce"],
    )
    job_probe = _benchmark_cleanup_replay_job_probe(scope_name)
    if job_probe["outcome"] == "job_name_present":
        raise LearningStageWorkerError(
            "benchmark cleanup replay Job name is present"
        )
    if job_probe["outcome"] != "job_name_absent":
        raise LearningStageWorkerError(
            "benchmark cleanup replay Job probe is indeterminate"
        )
    process_probe = _benchmark_cleanup_replay_process_probe(process_identity)
    if process_probe["outcome"] == "same_incarnation_live":
        raise LearningStageWorkerError(
            "benchmark cleanup replay worker incarnation is live"
        )
    if process_probe["outcome"] not in {
        "no_such_process",
        "different_incarnation",
    }:
        raise LearningStageWorkerError(
            "benchmark cleanup replay process probe is indeterminate"
        )
    return seal_immutable({
        "contract_version": "benchmark_worker_cleanup_replay_revalidation_v1",
        "cleanup_receipt_ref": {
            "content_sha256": validated_receipt["content_sha256"]
        },
        "launch_identity_anchor_ref": {
            "content_sha256": launch_anchor["content_sha256"]
        },
        "scope_name": scope_name,
        "process_identity": process_identity,
        "job_probe_ref": {"content_sha256": job_probe["content_sha256"]},
        "process_probe_ref": {
            "content_sha256": process_probe["content_sha256"]
        },
        "outcome": "current_live_state_absent",
        "artifact_is_authorization": False,
    })


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


def _write_json_create_only(path: Path, payload: dict[str, Any]) -> None:
    """以 deterministic create-only bytes 发布不可覆盖的 launch anchor。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
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
        _flush_windows_directory(path.parent)
    except FileExistsError as error:
        raise LearningStageWorkerError(
            "benchmark launch identity anchor already exists"
        ) from error


def _compose_benchmark_anchor_confirmation(
    *,
    reservation: dict[str, Any],
    anchored_reservation: dict[str, Any],
    operation_anchor: dict[str, Any],
) -> dict[str, Any]:
    return seal_immutable(
        {
            "contract_version": _BENCHMARK_CONFIRMATION_VERSION,
            "outcome": "verified_anchor_confirmed",
            "reservation_ref": {
                "content_sha256": reservation["content_sha256"]
            },
            "anchored_reservation_ref": {
                "content_sha256": anchored_reservation["content_sha256"]
            },
            "operation_anchor_ref": {
                "content_sha256": operation_anchor["content_sha256"]
            },
            "expected_supervision_ref": deepcopy(
                operation_anchor["expected_supervision_ref"]
            ),
            "handler_payload_source_ref": deepcopy(
                reservation["handler_payload_source_ref"]
            ),
            "run_id": reservation["run_id"],
            "stage": reservation["stage"],
            "operation_id": reservation["operation_id"],
            "workflow_revision": reservation["workflow_revision"],
            "worker_id": reservation["worker_id"],
            "payload_sha256": reservation["payload_sha256"],
            "execution_nonce": reservation["execution_nonce"],
            "prior_state": "reserved",
            "new_state": "anchored",
            "predecessor_content_sha256": reservation["content_sha256"],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def _validate_benchmark_anchor_confirmation(
    value: object,
    *,
    reservation: dict[str, Any],
    anchored_reservation: dict[str, Any],
    operation_anchor: dict[str, Any],
) -> dict[str, Any]:
    expected = _compose_benchmark_anchor_confirmation(
        reservation=reservation,
        anchored_reservation=anchored_reservation,
        operation_anchor=operation_anchor,
    )
    if value != expected:
        raise LearningStageWorkerError(
            "benchmark anchor confirmation is invalid"
        )
    return deepcopy(expected)


def _validate_benchmark_artifact_ref(
    *,
    path: Path,
    ref: object,
    contract_version: str,
) -> dict[str, Any]:
    exact_ref = _benchmark_exact_ref(ref, f"{contract_version} ref")
    value = _read_json_object(path, label=contract_version)
    if (
        value.get("contract_version") != contract_version
        or value.get("content_sha256") != exact_ref["content_sha256"]
        or content_sha256(value) != value.get("content_sha256")
    ):
        raise LearningStageWorkerError(f"{contract_version} is invalid")
    predecessor = value.get("predecessor_content_sha256")
    if predecessor is not None:
        _benchmark_exact_ref(
            {"content_sha256": predecessor},
            f"{contract_version} predecessor",
        )
    return value


def _benchmark_pre_anchor_absence_specs(
    reservation: dict[str, Any],
) -> tuple[tuple[str, dict[str, Any], str], ...]:
    from app.learn.hybrid.windows_process_scope import benchmark_worker_scope_name_v1

    scope_name = benchmark_worker_scope_name_v1(
        authority_kind=reservation["authority_kind"],
        run_id=reservation["run_id"],
        stage=reservation["stage"],
        operation_id=reservation["operation_id"],
        worker_id=reservation["worker_id"],
        payload_sha256=reservation["payload_sha256"],
        execution_nonce=reservation["execution_nonce"],
    )
    event_name = (
        "Local\\AgentGuiBenchmarkWorkerGate-"
        + content_sha256({"scope_name": scope_name})
    )
    return (
        (
            "owner",
            {"registry_record_absent": True, "owner_journal_absent": True},
            "owner_absence_observation_ref",
        ),
        (
            "process_event_job_beacon",
            {
                "worker_journal_absent": True,
                "startup_event_absent": True,
                "owner_job_absent": True,
                "beacon_absent": True,
                "scope_name": scope_name,
                "event_name": event_name,
            },
            "process_event_job_beacon_absence_observation_ref",
        ),
        ("result", {"result_absent": True}, "result_absence_observation_ref"),
        (
            "provider",
            {"provider_owner_absent": True},
            "provider_absence_observation_ref",
        ),
    )


def _validate_benchmark_pre_anchor_absence_chain(
    *,
    result_root: Path,
    reservation: dict[str, Any],
    refs: dict[str, Any],
) -> str:
    predecessor = reservation["content_sha256"]
    exact_fields = {
        "contract_version", "observation_kind", "outcome",
        "reservation_ref", "run_id", "stage", "operation_id",
        "worker_id", "checks", "predecessor_content_sha256",
        "content_sha256",
    }
    for kind, expected_checks, field in _benchmark_pre_anchor_absence_specs(
        reservation
    ):
        artifact = _validate_benchmark_artifact_ref(
            path=(
                result_root
                / f"{reservation['worker_id']}.pre-anchor-{kind}-absence.json"
            ),
            ref=refs.get(field),
            contract_version="benchmark_worker_pre_anchor_absence_observation_v1",
        )
        if (
            set(artifact) != exact_fields
            or artifact.get("observation_kind") != kind
            or artifact.get("outcome") != "absent"
            or artifact.get("reservation_ref")
            != {"content_sha256": reservation["content_sha256"]}
            or artifact.get("run_id") != reservation["run_id"]
            or artifact.get("stage") != reservation["stage"]
            or artifact.get("operation_id") != reservation["operation_id"]
            or artifact.get("worker_id") != reservation["worker_id"]
            or artifact.get("checks") != expected_checks
            or artifact.get("predecessor_content_sha256") != predecessor
        ):
            raise LearningStageWorkerError(
                "benchmark pre-anchor absence lineage is invalid"
            )
        predecessor = artifact["content_sha256"]
    return predecessor


def _compose_benchmark_not_launched_receipt(
    *,
    cancelled_reservation: dict[str, Any],
    operation_anchor: dict[str, Any],
    observation: dict[str, Any],
) -> dict[str, Any]:
    return seal_immutable({
        "contract_version": "benchmark_worker_cleanup_receipt_v1",
        "outcome": "verified_not_launched",
        "operation_anchor_ref": {
            "content_sha256": operation_anchor["anchor_identity_sha256"]
        },
        "reservation_ref": {
            "content_sha256": cancelled_reservation["content_sha256"]
        },
        "supervision_ref": None,
        "run_id": cancelled_reservation["run_id"],
        "stage": cancelled_reservation["stage"],
        "operation_id": cancelled_reservation["operation_id"],
        "worker_id": cancelled_reservation["worker_id"],
        "process_identity": None,
        "assignment_proven_ref": None,
        "finalization_intent_ref": None,
        "exact_handle_observation_refs": None,
        "job_absence_observation_ref": None,
        "worker_absence_observation_ref": None,
        "supervisor_absence_observation_ref": None,
        "reservation_abort_ref": {
            "content_sha256": observation["content_sha256"]
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    })


def _validate_benchmark_not_launched_observation(
    *,
    result_root: Path,
    worker_id: str,
    original_reservation: dict[str, Any],
    cancelled_reservation: dict[str, Any],
    operation_anchor: dict[str, Any],
) -> dict[str, Any]:
    anchored_body = deepcopy(original_reservation)
    anchored_body.pop("content_sha256")
    anchored_body["reservation_state"] = "anchored"
    anchored_body["predecessor_content_sha256"] = original_reservation[
        "content_sha256"
    ]
    anchored = seal_immutable(anchored_body)
    observation_ref = cancelled_reservation.get("abort_observation_ref")
    observation = _validate_benchmark_artifact_ref(
        path=result_root / f"{worker_id}.benchmark-not-launched.json",
        ref=observation_ref,
        contract_version="benchmark_worker_not_launched_observation_v1",
    )
    exact_fields = {
        "contract_version", "outcome", "authority_kind",
        "reservation_ref", "run_id", "stage", "operation_id",
        "worker_id", "owner_absence_observation_ref",
        "process_event_job_beacon_absence_observation_ref",
        "result_absence_observation_ref", "provider_absence_observation_ref",
        "predecessor_content_sha256", "artifact_is_authorization",
        "execute_binding_enabled", "content_sha256",
    }
    terminal_body = deepcopy(anchored)
    terminal_body.pop("content_sha256")
    terminal_body["reservation_state"] = "cancelled_before_launch"
    terminal_body["abort_observation_ref"] = observation_ref
    terminal_body["predecessor_content_sha256"] = anchored["content_sha256"]
    expected_cancelled = seal_immutable(terminal_body)
    if (
        cancelled_reservation != expected_cancelled
        or operation_anchor.get("reservation_ref")
        != {"content_sha256": original_reservation["content_sha256"]}
        or set(observation) != exact_fields
        or observation.get("outcome") != "verified_no_launch_artifacts"
        or observation.get("authority_kind") != original_reservation["authority_kind"]
        or observation.get("reservation_ref")
        != {"content_sha256": anchored["content_sha256"]}
        or observation.get("run_id") != original_reservation["run_id"]
        or observation.get("stage") != original_reservation["stage"]
        or observation.get("operation_id") != original_reservation["operation_id"]
        or observation.get("worker_id") != worker_id
        or observation.get("artifact_is_authorization") is not False
        or observation.get("execute_binding_enabled") is not False
    ):
        raise LearningStageWorkerError(
            "benchmark cleanup receipt no-launch observation is invalid"
        )
    predecessor = _validate_benchmark_pre_anchor_absence_chain(
        result_root=result_root,
        reservation=anchored,
        refs=observation,
    )
    if observation.get("predecessor_content_sha256") != predecessor:
        raise LearningStageWorkerError(
            "benchmark cleanup no-launch absence lineage is invalid"
        )
    return observation


def _benchmark_transitioned_reservation(
    parent: dict[str, Any], state: str
) -> dict[str, Any]:
    body = deepcopy(parent)
    body.pop("content_sha256")
    body["reservation_state"] = state
    body["predecessor_content_sha256"] = parent["content_sha256"]
    return seal_immutable(body)


def _compose_benchmark_launch_identity_anchor(
    *,
    anchored_reservation: dict[str, Any],
    launching_reservation: dict[str, Any],
    operation_anchor: dict[str, Any],
    supervision: dict[str, Any],
    supervisor_process_identity: dict[str, int],
    beacon_ref: dict[str, Any],
    process_identity: dict[str, int],
    assignment: dict[str, Any],
) -> dict[str, Any]:
    return seal_immutable({
        "contract_version": "benchmark_worker_launch_identity_anchor_v1",
        "authority_kind": anchored_reservation["authority_kind"],
        "anchored_reservation_ref": {
            "content_sha256": anchored_reservation["content_sha256"]
        },
        "launching_reservation_ref": {
            "content_sha256": launching_reservation["content_sha256"]
        },
        "operation_anchor_ref": {
            "content_sha256": operation_anchor["anchor_identity_sha256"]
        },
        "actual_supervision_ref": {
            "content_sha256": supervision["content_sha256"]
        },
        "supervisor_process_identity": deepcopy(supervisor_process_identity),
        "beacon_ref": deepcopy(beacon_ref),
        "process_identity": deepcopy(process_identity),
        "assignment_observation_ref": {
            "content_sha256": assignment["content_sha256"]
        },
        "assignment_predecessor_content_sha256": assignment[
            "predecessor_content_sha256"
        ],
        "predecessor_content_sha256": assignment["content_sha256"],
    })


def _benchmark_handle_identity(
    *,
    handle_kind: str,
    launch_identity_anchor: dict[str, Any],
    scope_name: str,
) -> dict[str, Any]:
    if handle_kind == "worker_process":
        return {"process_identity": deepcopy(
            launch_identity_anchor["process_identity"]
        )}
    if handle_kind == "startup_event":
        return {
            "event_name": (
                "Local\\AgentGuiBenchmarkWorkerGate-"
                + content_sha256({"scope_name": scope_name})
            )
        }
    if handle_kind == "beacon_file":
        return {"beacon_ref": deepcopy(launch_identity_anchor["beacon_ref"])}
    if handle_kind == "owner_job":
        return {"scope_name": scope_name}
    raise LearningStageWorkerError("benchmark handle kind is invalid")


def _compose_benchmark_handle_observation(
    *,
    worker_id: str,
    handle_kind: str,
    handle_identity: dict[str, Any],
    call_result: str | None,
    call_error: dict[str, str] | None,
    predecessor_content_sha256: str,
) -> dict[str, Any]:
    return seal_immutable({
        "contract_version": "benchmark_worker_handle_close_observation_v1",
        "handle_kind": handle_kind,
        "handle_identity": deepcopy(handle_identity),
        "call_result": call_result,
        "call_error": deepcopy(call_error),
        "observed_at": _utc_now_iso(),
        "worker_id": worker_id,
        "predecessor_content_sha256": predecessor_content_sha256,
    })


def _compose_benchmark_exit_join_observation(
    *,
    worker_id: str,
    process_identity: dict[str, int],
    exitcode: int | None,
    join_result: str | None,
    join_error: dict[str, str] | None,
    predecessor_content_sha256: str,
) -> dict[str, Any]:
    return seal_immutable({
        "contract_version": "benchmark_worker_exit_join_observation_v1",
        "worker_id": worker_id,
        "process_identity": deepcopy(process_identity),
        "exitcode": exitcode,
        "join_result": join_result,
        "join_error": deepcopy(join_error),
        "observed_at": _utc_now_iso(),
        "predecessor_content_sha256": predecessor_content_sha256,
    })


def _validate_exact_benchmark_process_identity(
    value: object, *, label: str
) -> dict[str, int]:
    if (
        not isinstance(value, dict)
        or set(value) != {"pid", "create_time_ns"}
        or isinstance(value.get("pid"), bool)
        or not isinstance(value.get("pid"), int)
        or value["pid"] <= 0
        or isinstance(value.get("create_time_ns"), bool)
        or not isinstance(value.get("create_time_ns"), int)
        or value["create_time_ns"] <= 0
    ):
        raise LearningStageWorkerError(f"benchmark {label} identity is invalid")
    return {"pid": value["pid"], "create_time_ns": value["create_time_ns"]}


def _windows_error_code(error: BaseException) -> int | None:
    code = getattr(error, "winerror", None)
    if code is None and getattr(error, "args", None):
        first = error.args[0]
        code = first if isinstance(first, int) else None
    return code


def _benchmark_worker_gate_event_name(scope_name: str) -> str:
    return (
        "Local\\AgentGuiBenchmarkWorkerGate-"
        + content_sha256({"scope_name": scope_name})
    )


class _RecoveredBenchmarkProcess:
    """为 fresh Registry 持有 exact worker 句柄，不伪造第二次 spawn。"""

    def __init__(self, *, process_identity: Mapping[str, object]) -> None:
        import win32api
        import win32con

        self._identity = _validate_exact_benchmark_process_identity(
            dict(process_identity), label="recovered worker"
        )
        self.pid = self._identity["pid"]
        self._handle = win32api.OpenProcess(
            int(win32con.PROCESS_QUERY_INFORMATION)
            | int(win32con.PROCESS_TERMINATE)
            | 0x00100000,
            False,
            self.pid,
        )
        self._closed = False
        self._exitcode: int | None = None
        if LearningStageWorkerRegistry._benchmark_process_incarnation_absent(
            self._identity
        ):
            self.close()
            raise LearningStageWorkerError(
                "benchmark recovered process incarnation is absent"
            )

    def is_alive(self) -> bool:
        import win32event

        if self._closed:
            raise ValueError("benchmark recovered process handle is closed")
        if LearningStageWorkerRegistry._benchmark_process_incarnation_absent(
            self._identity
        ):
            return False
        return win32event.WaitForSingleObject(self._handle, 0) == win32event.WAIT_TIMEOUT

    def terminate(self) -> None:
        import win32process

        if self._closed:
            raise ValueError("benchmark recovered process handle is closed")
        if not LearningStageWorkerRegistry._benchmark_process_incarnation_absent(
            self._identity
        ):
            win32process.TerminateProcess(self._handle, 198)

    def join(self, timeout: float | int | None = None) -> None:
        import win32event
        import win32process

        if self._closed:
            raise ValueError("benchmark recovered process handle is closed")
        milliseconds = (
            0xFFFFFFFF if timeout is None else max(0, int(float(timeout) * 1000))
        )
        outcome = win32event.WaitForSingleObject(self._handle, milliseconds)
        if outcome == win32event.WAIT_OBJECT_0:
            self._exitcode = int(win32process.GetExitCodeProcess(self._handle))

    @property
    def exitcode(self) -> int | None:
        if self._exitcode is None and not self._closed and not self.is_alive():
            import win32process

            self._exitcode = int(win32process.GetExitCodeProcess(self._handle))
        return self._exitcode

    def close(self) -> None:
        if not self._closed:
            import win32api

            win32api.CloseHandle(self._handle)
            self._closed = True


def _validate_benchmark_launch_recovery_cleanup(
    value: object,
    *,
    original: Mapping[str, object],
    current: Mapping[str, object],
    anchor: Mapping[str, object],
    inspection: Mapping[str, object],
) -> dict[str, Any]:
    exact = {
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
        "supervision_ref",
        "process_identity",
        "scope_name",
        "termination_observation",
        "job_absent",
        "event_absent",
        "beacon_absent",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != exact
        or content_sha256(value) != value.get("content_sha256")
        or value.get("contract_version")
        != "benchmark_worker_launch_recovery_cleanup_v1"
        or value.get("outcome") != "verified_launch_artifacts_absent"
        or any(
            value.get(field) != original.get(field)
            for field in (
                "authority_kind",
                "run_id",
                "stage",
                "operation_id",
                "worker_id",
                "model_request_id",
                "payload_sha256",
                "execution_nonce",
            )
        )
        or value.get("reservation_ref")
        != {"content_sha256": original["content_sha256"]}
        or value.get("current_reservation_ref")
        != {"content_sha256": current["content_sha256"]}
        or value.get("operation_anchor_ref")
        != {"content_sha256": anchor["anchor_identity_sha256"]}
        or value.get("supervision_ref") != inspection.get("supervision_ref")
        or value.get("job_absent") is not True
        or value.get("event_absent") is not True
        or value.get("beacon_absent") is not True
        or value.get("artifact_is_authorization") is not False
        or value.get("execute_binding_enabled") is not False
    ):
        raise LearningStageWorkerError(
            "benchmark launch recovery cleanup is invalid"
        )
    identity = value.get("process_identity")
    if identity is not None:
        _validate_exact_benchmark_process_identity(
            identity, label="launch recovery cleanup worker"
        )
        termination = value.get("termination_observation")
        if (
            not isinstance(termination, dict)
            or termination.get("process_identity") != identity
            or termination.get("outcome")
            not in {
                "verified_exact_incarnation_terminated",
                "exact_incarnation_already_absent",
            }
        ):
            raise LearningStageWorkerError(
                "benchmark launch recovery termination is invalid"
            )
    elif value.get("termination_observation") is not None:
        raise LearningStageWorkerError(
            "benchmark launch recovery termination is invalid"
        )
    return deepcopy(value)


def _benchmark_launch_owner_reservation_lineage(
    original: dict[str, Any],
    current: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    anchored = _benchmark_transitioned_reservation(original, "anchored")
    launching = _benchmark_transitioned_reservation(anchored, "launching")
    launched = _benchmark_transitioned_reservation(launching, "launched")
    expected = {
        "anchored": anchored,
        "launching": launching,
        "launched": launched,
    }.get(current.get("reservation_state"))
    if expected is None or current != expected:
        raise LearningStageWorkerError(
            "benchmark launch owner current reservation lineage is invalid"
        )
    return anchored, launching, launched


def _benchmark_launch_owner_exact_ref_map(
    value: object,
    *,
    label: str,
    exact_keys: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LearningStageWorkerError(f"benchmark {label} is invalid")
    if exact_keys is not None and set(value) != exact_keys:
        raise LearningStageWorkerError(f"benchmark {label} shape is invalid")
    return {
        key: _benchmark_exact_ref(ref, f"benchmark {label} {key}")
        for key, ref in value.items()
    }


def _validate_benchmark_launch_owner_assignment(
    *,
    result_root: Path,
    worker_id: str,
    owner: dict[str, Any],
    acquiring_owner: dict[str, Any],
    scope_name: str,
) -> tuple[dict[str, Any], dict[str, int], dict[str, str]]:
    assignment_ref = _benchmark_exact_ref(
        owner.get("assignment_observation_ref"),
        "benchmark launch owner assignment ref",
    )
    assignment = _validate_benchmark_artifact_ref(
        path=result_root / f"{worker_id}.benchmark-assignment.json",
        ref=assignment_ref,
        contract_version="benchmark_worker_scope_assignment_v1",
    )
    process_identity = _validate_exact_benchmark_process_identity(
        owner.get("process_identity"), label="launch owner worker"
    )
    exact_job_policy = {
        "kill_on_job_close": True,
        "breakaway_ok": False,
        "silent_breakaway_ok": False,
        "owner_handle_authority": "registry_parent",
    }
    if (
        set(assignment)
        != {
            "contract_version",
            "scope_name",
            "process_identity",
            "observed_member_identities",
            "job_policy",
            "temporary_process_handle_close",
            "temporary_job_handle_close",
            "predecessor_content_sha256",
            "content_sha256",
        }
        or assignment.get("scope_name") != scope_name
        or assignment.get("process_identity") != process_identity
        or assignment.get("observed_member_identities") != [process_identity]
        or assignment.get("job_policy") != exact_job_policy
        or assignment.get("temporary_process_handle_close")
        != {"handle_kind": "temporary_process", "status": "closed"}
        or assignment.get("temporary_job_handle_close")
        != {"handle_kind": "temporary_job", "status": "closed"}
        or assignment.get("predecessor_content_sha256")
        != acquiring_owner["content_sha256"]
        or owner.get("job_policy") != exact_job_policy
    ):
        raise LearningStageWorkerError(
            "benchmark launch owner assignment proof is invalid"
        )
    beacon_ref = _benchmark_exact_ref(
        owner.get("beacon_ref"), "benchmark launch owner beacon ref"
    )
    return assignment, process_identity, beacon_ref


def _validate_benchmark_launch_owner_record(
    *,
    record: dict[str, Any] | None,
    original_reservation: dict[str, Any],
    current_reservation: dict[str, Any],
    operation_anchor: dict[str, Any],
    supervision: dict[str, Any],
    process_identity: dict[str, int],
    scope_name: str,
) -> None:
    if record is None:
        return
    for field in (
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
    ):
        if record.get(field) != original_reservation[field]:
            raise LearningStageWorkerError(
                "benchmark launch owner Registry record identity is invalid"
            )
    record_anchor = record.get("benchmark_anchor")
    if record_anchor is not None and record_anchor != operation_anchor:
        raise LearningStageWorkerError(
            "benchmark launch owner Registry anchor is invalid"
        )
    record_supervision = record.get("benchmark_supervision")
    if record_supervision is not None and record_supervision != supervision:
        raise LearningStageWorkerError(
            "benchmark launch owner Registry supervision is invalid"
        )
    record_reservation = record.get("benchmark_reservation")
    if record_reservation is not None and record_reservation != current_reservation:
        raise LearningStageWorkerError(
            "benchmark launch owner Registry reservation is invalid"
        )
    process = record.get("process")
    process_is_alive = False
    if process is not None:
        try:
            record_pid = getattr(process, "pid", None)
            process_is_alive = bool(process.is_alive())
        except ValueError:
            record_pid = None
        if record_pid is not None and record_pid != process_identity["pid"]:
            raise LearningStageWorkerError(
                "benchmark launch owner Registry process identity is invalid"
            )
        if process_is_alive:
            import psutil

            try:
                observed_create_time_ns = int(
                    round(
                        psutil.Process(process_identity["pid"]).create_time()
                        * 1_000_000_000
                    )
                )
            except psutil.Error as error:
                raise LearningStageWorkerError(
                    "benchmark launch owner live process identity is indeterminate"
                ) from error
            if (
                abs(
                    observed_create_time_ns
                    - process_identity["create_time_ns"]
                )
                >= 1_000
            ):
                raise LearningStageWorkerError(
                    "benchmark launch owner live process incarnation is invalid"
                )
    scope = record.get("benchmark_scope")
    if scope is not None and getattr(scope, "name", None) != scope_name:
        raise LearningStageWorkerError(
            "benchmark launch owner Registry scope identity is invalid"
        )
    if scope is not None:
        member_pids = scope.pids()
        expected_member_pids = [process_identity["pid"]] if process_is_alive else []
        if member_pids != expected_member_pids:
            raise LearningStageWorkerError(
                "benchmark launch owner Registry scope membership is invalid"
            )


def _validate_benchmark_launch_owner_cleanup_intent(
    *,
    result_root: Path,
    worker_id: str,
    owner: dict[str, Any],
    gate_owner: dict[str, Any],
    supervision: dict[str, Any],
    process_identity: dict[str, int],
    assignment_ref: dict[str, str],
    scope_name: str,
) -> dict[str, Any]:
    intent_ref = _benchmark_exact_ref(
        owner.get("cleanup_finalization_intent"),
        "benchmark launch owner cleanup intent ref",
    )
    intent = _validate_benchmark_artifact_ref(
        path=result_root / f"{worker_id}.benchmark-cleanup-intent.json",
        ref=intent_ref,
        contract_version="benchmark_worker_cleanup_finalization_intent_v1",
    )
    exact_intent_fields = {
        "contract_version",
        "supervision_ref",
        "assignment_proven_ref",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "supervisor_process_identity",
        "process_identity",
        "scope_name",
        "gate_state",
        "exit_observation_ref",
        "stable_zero_observation_ref",
        "exact_owned_handles",
        "exact_handle_observation_refs",
        "owner_job_handle_close_planned",
        "cleanup_receipt_id",
        "predecessor_content_sha256",
        "content_sha256",
    }
    exact_handles = {
        "worker_process": "closed_explicitly",
        "startup_event": "closed_explicitly",
        "beacon_file": "closed_explicitly",
        "owner_job": "open",
    }
    handle_refs = _benchmark_launch_owner_exact_ref_map(
        intent.get("exact_handle_observation_refs"),
        label="launch owner handle refs",
        exact_keys={"worker_process", "startup_event", "beacon_file"},
    )
    if (
        set(intent) != exact_intent_fields
        or intent.get("supervision_ref")
        != {"content_sha256": supervision["content_sha256"]}
        or intent.get("assignment_proven_ref") != assignment_ref
        or any(
            intent.get(field) != gate_owner[field]
            for field in ("run_id", "stage", "operation_id", "worker_id")
        )
        or intent.get("supervisor_process_identity")
        != gate_owner["supervisor_process_identity"]
        or intent.get("process_identity") != process_identity
        or intent.get("scope_name") != scope_name
        or intent.get("gate_state") != "released"
        or intent.get("exact_owned_handles") != exact_handles
        or intent.get("owner_job_handle_close_planned") is not True
        or intent.get("cleanup_receipt_id")
        != content_sha256({"worker_id": worker_id, "scope_name": scope_name})
        or intent.get("predecessor_content_sha256")
        != gate_owner["content_sha256"]
    ):
        raise LearningStageWorkerError(
            "benchmark launch owner cleanup intent is invalid"
        )
    exit_ref = _benchmark_exact_ref(
        intent.get("exit_observation_ref"),
        "benchmark launch owner exit observation ref",
    )
    stable_zero_ref = _benchmark_exact_ref(
        intent.get("stable_zero_observation_ref"),
        "benchmark launch owner stable-zero ref",
    )
    expected_owner_body = deepcopy(gate_owner)
    expected_owner_body.pop("content_sha256")
    expected_owner_body.update(
        {
            "phase": "cleanup_finalization_intent",
            "exit_observation_ref": exit_ref,
            "stable_zero_observation_ref": stable_zero_ref,
            "exact_handle_observation_refs": handle_refs,
            "cleanup_finalization_intent": intent_ref,
            "predecessor_content_sha256": gate_owner["content_sha256"],
        }
    )
    if owner != seal_immutable(expected_owner_body):
        raise LearningStageWorkerError(
            "benchmark launch owner cleanup journal lineage is invalid"
        )
    return intent


def _inspect_benchmark_worker_launch_owner_locked(
    *,
    result_root: Path,
    original_reservation: dict[str, Any],
    current_reservation: dict[str, Any],
    expected_operation_anchor: dict[str, Any],
    supervision_root: BenchmarkWorkerSupervisionRoot,
    record: dict[str, Any] | None,
) -> dict[str, Any]:
    anchored, launching, launched = _benchmark_launch_owner_reservation_lineage(
        original_reservation, current_reservation
    )
    worker_id = original_reservation["worker_id"]
    owner_path = result_root / f"{worker_id}.benchmark-owner.json"
    assignment_path = result_root / f"{worker_id}.benchmark-assignment.json"
    launch_anchor_path = (
        result_root / f"{worker_id}.benchmark-launch-identity-anchor.json"
    )
    cleanup_intent_path = (
        result_root / f"{worker_id}.benchmark-cleanup-intent.json"
    )
    cleanup_receipt_path = result_root / f"{worker_id}.benchmark-cleanup.json"
    supervision_ref = None
    owner_phase = None
    assignment_state = "not_proven"
    process_identity = None
    scope_name = None
    assignment_proven_ref = None

    if not owner_path.exists():
        exact_absence_paths = (
            assignment_path,
            launch_anchor_path,
            cleanup_intent_path,
            cleanup_receipt_path,
            result_root / f"{worker_id}.benchmark-beacon.json",
            result_root / f"{worker_id}.worker.json",
            result_root / f"{worker_id}.result.json",
        )
        if (
            current_reservation != anchored
            or record is not None
            or any(path.exists() for path in exact_absence_paths)
        ):
            raise LearningStageWorkerError(
                "benchmark launch owner absence is ambiguous"
            )
    else:
        owner = _read_json_object(owner_path, label="benchmark launch owner journal")
        owner_fields = {
            "contract_version",
            "authority_kind",
            "operation_anchor_ref",
            "reservation_ref",
            "supervision_ref",
            "run_id",
            "stage",
            "operation_id",
            "worker_id",
            "model_request_id",
            "payload_sha256",
            "execution_nonce",
            "scope_name",
            "supervisor_process_identity",
            "phase",
            "process_identity",
            "beacon_ref",
            "assignment_observation_ref",
            "job_policy",
            "gate_state",
            "exit_observation_ref",
            "stable_zero_observation_ref",
            "exact_handle_observation_refs",
            "cleanup_finalization_intent",
            "cleanup_receipt_ref",
            "predecessor_content_sha256",
            "content_sha256",
        }
        if (
            set(owner) != owner_fields
            or owner.get("contract_version")
            != "benchmark_worker_owner_journal_v1"
            or content_sha256(owner) != owner.get("content_sha256")
            or owner.get("authority_kind")
            != original_reservation["authority_kind"]
            or owner.get("operation_anchor_ref")
            != {
                "content_sha256": expected_operation_anchor[
                    "anchor_identity_sha256"
                ]
            }
            or any(
                owner.get(field) != original_reservation[field]
                for field in (
                    "run_id",
                    "stage",
                    "operation_id",
                    "worker_id",
                    "model_request_id",
                    "payload_sha256",
                    "execution_nonce",
                )
            )
            or owner.get("cleanup_receipt_ref") is not None
        ):
            raise LearningStageWorkerError(
                "benchmark launch owner journal identity is invalid"
            )
        supervisor_identity = _validate_exact_benchmark_process_identity(
            owner.get("supervisor_process_identity"),
            label="launch owner supervisor",
        )
        supervision = compose_benchmark_worker_supervision_v1(
            supervision_root=supervision_root,
            reservation=original_reservation,
            expected_operation_anchor=expected_operation_anchor,
            supervisor_process_identity=supervisor_identity,
            startup_gate_timeout_ms=15_000,
        )
        supervision_ref = {"content_sha256": supervision["content_sha256"]}
        internal_scope_name = supervision["scope_name"]
        if (
            owner.get("supervision_ref") != supervision_ref
            or owner.get("scope_name") != internal_scope_name
        ):
            raise LearningStageWorkerError(
                "benchmark launch owner supervision identity is invalid"
            )
        acquiring_owner = LearningStageWorkerRegistry._benchmark_owner_journal(
            current=anchored,
            anchor=expected_operation_anchor,
            supervision=supervision,
            scope_name=internal_scope_name,
            supervisor_identity=supervisor_identity,
            phase="acquiring",
            process_identity=None,
            beacon_ref=None,
            assignment_ref=None,
            gate_state="closed",
            predecessor=None,
        )
        owner_phase = owner.get("phase")
        if owner_phase == "acquiring":
            if (
                current_reservation not in (anchored, launching)
                or owner != acquiring_owner
                or any(
                    path.exists()
                    for path in (
                        assignment_path,
                        launch_anchor_path,
                        cleanup_intent_path,
                        cleanup_receipt_path,
                    )
                )
            ):
                raise LearningStageWorkerError(
                    "benchmark launch owner pre-assignment state is invalid"
                )
        elif owner_phase in {
            "assignment_proven",
            "gate_released",
            "cleanup_finalization_intent",
        }:
            assignment, process_identity, beacon_ref = (
                _validate_benchmark_launch_owner_assignment(
                    result_root=result_root,
                    worker_id=worker_id,
                    owner=owner,
                    acquiring_owner=acquiring_owner,
                    scope_name=internal_scope_name,
                )
            )
            assignment_proven_ref = {
                "content_sha256": assignment["content_sha256"]
            }
            assigned_owner = LearningStageWorkerRegistry._benchmark_owner_journal(
                current=launching,
                anchor=expected_operation_anchor,
                supervision=supervision,
                scope_name=internal_scope_name,
                supervisor_identity=supervisor_identity,
                phase="assignment_proven",
                process_identity=process_identity,
                beacon_ref=beacon_ref,
                assignment_ref=assignment_proven_ref,
                gate_state="closed",
                predecessor=acquiring_owner["content_sha256"],
            )
            launch_identity_anchor = _read_json_object(
                launch_anchor_path, label="benchmark launch identity anchor"
            )
            expected_launch_identity_anchor = (
                _compose_benchmark_launch_identity_anchor(
                    anchored_reservation=anchored,
                    launching_reservation=launching,
                    operation_anchor=expected_operation_anchor,
                    supervision=supervision,
                    supervisor_process_identity=supervisor_identity,
                    beacon_ref=beacon_ref,
                    process_identity=process_identity,
                    assignment=assignment,
                )
            )
            if launch_identity_anchor != expected_launch_identity_anchor:
                raise LearningStageWorkerError(
                    "benchmark launch owner launch identity anchor is invalid"
                )
            gate_owner = LearningStageWorkerRegistry._benchmark_owner_journal(
                current=launching,
                anchor=expected_operation_anchor,
                supervision=supervision,
                scope_name=internal_scope_name,
                supervisor_identity=supervisor_identity,
                phase="gate_released",
                process_identity=process_identity,
                beacon_ref=beacon_ref,
                assignment_ref=assignment_proven_ref,
                gate_state="released",
                predecessor=assigned_owner["content_sha256"],
            )
            if owner_phase == "assignment_proven":
                if (
                    current_reservation != launching
                    or owner != assigned_owner
                    or cleanup_intent_path.exists()
                    or cleanup_receipt_path.exists()
                ):
                    raise LearningStageWorkerError(
                        "benchmark launch owner assignment phase is invalid"
                    )
            elif owner_phase == "gate_released":
                if (
                    current_reservation not in (launching, launched)
                    or owner != gate_owner
                    or cleanup_intent_path.exists()
                    or cleanup_receipt_path.exists()
                ):
                    raise LearningStageWorkerError(
                        "benchmark launch owner gate phase is invalid"
                    )
            else:
                if current_reservation != launched:
                    raise LearningStageWorkerError(
                        "benchmark launch owner cleanup reservation is invalid"
                    )
                _validate_benchmark_launch_owner_cleanup_intent(
                    result_root=result_root,
                    worker_id=worker_id,
                    owner=owner,
                    gate_owner=gate_owner,
                    supervision=supervision,
                    process_identity=process_identity,
                    assignment_ref=assignment_proven_ref,
                    scope_name=internal_scope_name,
                )
                owner_job_close_path = (
                    result_root / f"{worker_id}.owner-job-close.json"
                )
                job_absence_path = (
                    result_root / f"{worker_id}.job-absence.json"
                )
                if (
                    (
                        owner_job_close_path.exists()
                        or job_absence_path.exists()
                    )
                    and not cleanup_receipt_path.exists()
                ):
                    raise LearningStageWorkerError(
                        "benchmark launch owner cleanup receipt is missing"
                    )
                if cleanup_receipt_path.exists():
                    _validate_benchmark_cleanup_receipt(
                        _read_json_object(
                            cleanup_receipt_path,
                            label="benchmark cleanup receipt",
                        ),
                        result_root=result_root,
                        worker_id=worker_id,
                        run_id=original_reservation["run_id"],
                        stage=original_reservation["stage"],
                        operation_id=original_reservation["operation_id"],
                        operation_anchor=expected_operation_anchor,
                        original_reservation=original_reservation,
                        current_reservation=current_reservation,
                        supervision_root=supervision_root,
                    )
            _validate_benchmark_launch_owner_record(
                record=record,
                original_reservation=original_reservation,
                current_reservation=current_reservation,
                operation_anchor=expected_operation_anchor,
                supervision=supervision,
                process_identity=process_identity,
                scope_name=internal_scope_name,
            )
            assignment_state = "proven"
            scope_name = internal_scope_name
        else:
            raise LearningStageWorkerError(
                "benchmark launch owner phase is invalid"
            )

    return seal_immutable(
        {
            "contract_version": "benchmark_worker_launch_owner_inspection_v1",
            "authority_kind": original_reservation["authority_kind"],
            "run_id": original_reservation["run_id"],
            "stage": original_reservation["stage"],
            "operation_id": original_reservation["operation_id"],
            "worker_id": original_reservation["worker_id"],
            "model_request_id": original_reservation["model_request_id"],
            "payload_sha256": original_reservation["payload_sha256"],
            "execution_nonce": original_reservation["execution_nonce"],
            "reservation_ref": {
                "content_sha256": original_reservation["content_sha256"]
            },
            "current_reservation_ref": {
                "content_sha256": current_reservation["content_sha256"]
            },
            "operation_anchor_ref": {
                "content_sha256": expected_operation_anchor[
                    "anchor_identity_sha256"
                ]
            },
            "expected_supervision_ref": deepcopy(
                expected_operation_anchor["expected_supervision_ref"]
            ),
            "supervision_ref": supervision_ref,
            "reservation_state": current_reservation["reservation_state"],
            "owner_phase": owner_phase,
            "assignment_state": assignment_state,
            "process_identity": deepcopy(process_identity),
            "scope_name": scope_name,
            "assignment_proven_ref": deepcopy(assignment_proven_ref),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def _validate_benchmark_cleanup_absence_artifact(
    *,
    result_root: Path,
    worker_id: str,
    kind: str,
    ref: object,
    predecessor: str,
    scope_name: str | None,
    process_identity: dict[str, int] | None,
) -> dict[str, Any]:
    artifact = _validate_benchmark_artifact_ref(
        path=result_root / f"{worker_id}.{kind}-absence.json",
        ref=ref,
        contract_version="benchmark_worker_absence_observation_v1",
    )
    if (
        set(artifact)
        != {
            "contract_version", "observation_kind", "outcome",
            "worker_id", "scope_name", "process_identity",
            "predecessor_content_sha256", "content_sha256",
        }
        or artifact.get("observation_kind") != kind
        or artifact.get("outcome") != "absent"
        or artifact.get("worker_id") != worker_id
        or artifact.get("scope_name") != scope_name
        or artifact.get("process_identity") != process_identity
        or artifact.get("predecessor_content_sha256") != predecessor
    ):
        raise LearningStageWorkerError(
            "benchmark cleanup receipt absence observation is invalid"
        )
    return artifact


def _validate_benchmark_cleanup_handle_artifact(
    *,
    result_root: Path,
    worker_id: str,
    kind: str,
    suffix: str,
    ref: object,
    predecessor: str,
    handle_identity: dict[str, Any],
) -> dict[str, Any]:
    artifact = _validate_benchmark_artifact_ref(
        path=result_root / f"{worker_id}.{suffix}",
        ref=ref,
        contract_version="benchmark_worker_handle_close_observation_v1",
    )
    if (
        set(artifact)
        != {
            "contract_version", "handle_kind", "handle_identity",
            "call_result", "call_error", "observed_at", "worker_id",
            "predecessor_content_sha256", "content_sha256",
        }
        or artifact.get("handle_kind") != kind
        or artifact.get("handle_identity") != handle_identity
        or artifact.get("call_result") != "success"
        or artifact.get("call_error") is not None
        or not isinstance(artifact.get("observed_at"), str)
        or not artifact["observed_at"]
        or artifact.get("worker_id") != worker_id
        or artifact.get("predecessor_content_sha256") != predecessor
    ):
        raise LearningStageWorkerError(
            "benchmark cleanup receipt handle observation is invalid"
        )
    return artifact


def _validate_benchmark_launched_cleanup_receipt(
    value: dict[str, Any],
    *,
    result_root: Path,
    worker_id: str,
    run_id: str,
    stage: str,
    operation_id: str,
    operation_anchor: dict[str, Any],
    original_reservation: dict[str, Any],
    current_reservation: dict[str, Any],
    supervision_root: BenchmarkWorkerSupervisionRoot,
) -> dict[str, Any]:
    from app.learn.hybrid.windows_process_scope import benchmark_worker_scope_name_v1

    anchored = _benchmark_transitioned_reservation(
        original_reservation, "anchored"
    )
    launching = _benchmark_transitioned_reservation(anchored, "launching")
    launched = _benchmark_transitioned_reservation(launching, "launched")
    if current_reservation != launched:
        raise LearningStageWorkerError(
            "benchmark cleanup current reservation lineage is invalid"
        )
    scope_name = benchmark_worker_scope_name_v1(
        authority_kind=original_reservation["authority_kind"],
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
        worker_id=worker_id,
        payload_sha256=original_reservation["payload_sha256"],
        execution_nonce=original_reservation["execution_nonce"],
    )
    launch_identity_anchor = _read_json_object(
        result_root
        / f"{worker_id}.benchmark-launch-identity-anchor.json",
        label="benchmark launch identity anchor",
    )
    launch_anchor_fields = {
        "contract_version", "authority_kind", "anchored_reservation_ref",
        "launching_reservation_ref", "operation_anchor_ref",
        "actual_supervision_ref", "supervisor_process_identity",
        "beacon_ref", "process_identity", "assignment_observation_ref",
        "assignment_predecessor_content_sha256",
        "predecessor_content_sha256", "content_sha256",
    }
    if (
        set(launch_identity_anchor) != launch_anchor_fields
        or launch_identity_anchor.get("contract_version")
        != "benchmark_worker_launch_identity_anchor_v1"
        or content_sha256(launch_identity_anchor)
        != launch_identity_anchor.get("content_sha256")
        or launch_identity_anchor.get("authority_kind")
        != original_reservation["authority_kind"]
        or launch_identity_anchor.get("anchored_reservation_ref")
        != {"content_sha256": anchored["content_sha256"]}
        or launch_identity_anchor.get("launching_reservation_ref")
        != {"content_sha256": launching["content_sha256"]}
        or launch_identity_anchor.get("operation_anchor_ref")
        != {"content_sha256": operation_anchor["anchor_identity_sha256"]}
    ):
        raise LearningStageWorkerError(
            "benchmark launch identity anchor is invalid"
        )
    process_identity = _validate_exact_benchmark_process_identity(
        launch_identity_anchor.get("process_identity"), label="worker"
    )
    supervisor_identity = _validate_exact_benchmark_process_identity(
        launch_identity_anchor.get("supervisor_process_identity"),
        label="supervisor",
    )
    beacon_ref = _benchmark_exact_ref(
        launch_identity_anchor.get("beacon_ref"),
        "benchmark launch beacon ref",
    )
    supervision = compose_benchmark_worker_supervision_v1(
        supervision_root=supervision_root,
        reservation=original_reservation,
        expected_operation_anchor=operation_anchor,
        supervisor_process_identity=supervisor_identity,
        startup_gate_timeout_ms=15_000,
    )
    acquiring_owner = LearningStageWorkerRegistry._benchmark_owner_journal(
        current=anchored,
        anchor=operation_anchor,
        supervision=supervision,
        scope_name=scope_name,
        supervisor_identity=supervisor_identity,
        phase="acquiring",
        process_identity=None,
        beacon_ref=None,
        assignment_ref=None,
        gate_state="closed",
        predecessor=None,
    )
    assignment = _validate_benchmark_artifact_ref(
        path=result_root / f"{worker_id}.benchmark-assignment.json",
        ref=launch_identity_anchor.get("assignment_observation_ref"),
        contract_version="benchmark_worker_scope_assignment_v1",
    )
    exact_job_policy = {
        "kill_on_job_close": True,
        "breakaway_ok": False,
        "silent_breakaway_ok": False,
        "owner_handle_authority": "registry_parent",
    }
    if (
        set(assignment)
        != {
            "contract_version", "scope_name", "process_identity",
            "observed_member_identities", "job_policy",
            "temporary_process_handle_close", "temporary_job_handle_close",
            "predecessor_content_sha256",
            "content_sha256",
        }
        or assignment.get("scope_name") != scope_name
        or assignment.get("process_identity") != process_identity
        or assignment.get("observed_member_identities") != [process_identity]
        or assignment.get("job_policy") != exact_job_policy
        or assignment.get("temporary_process_handle_close")
        != {"handle_kind": "temporary_process", "status": "closed"}
        or assignment.get("temporary_job_handle_close")
        != {"handle_kind": "temporary_job", "status": "closed"}
        or assignment.get("predecessor_content_sha256")
        != acquiring_owner["content_sha256"]
    ):
        raise LearningStageWorkerError(
            "benchmark cleanup assignment observation is invalid"
        )

    owner = _read_json_object(
        result_root / f"{worker_id}.benchmark-owner.json",
        label="benchmark owner journal",
    )
    owner_fields = {
        "contract_version", "authority_kind", "operation_anchor_ref",
        "reservation_ref", "supervision_ref", "run_id", "stage",
        "operation_id", "worker_id", "model_request_id", "payload_sha256",
        "execution_nonce", "scope_name", "supervisor_process_identity",
        "phase", "process_identity", "beacon_ref",
        "assignment_observation_ref", "job_policy", "gate_state",
        "exit_observation_ref", "stable_zero_observation_ref",
        "exact_handle_observation_refs", "cleanup_finalization_intent",
        "cleanup_receipt_ref", "predecessor_content_sha256",
        "content_sha256",
    }
    if set(owner) != owner_fields or content_sha256(owner) != owner.get(
        "content_sha256"
    ):
        raise LearningStageWorkerError("benchmark owner journal shape is invalid")
    assignment_ref = {"content_sha256": assignment["content_sha256"]}
    expected_launch_identity_anchor = _compose_benchmark_launch_identity_anchor(
        anchored_reservation=anchored,
        launching_reservation=launching,
        operation_anchor=operation_anchor,
        supervision=supervision,
        supervisor_process_identity=supervisor_identity,
        beacon_ref=beacon_ref,
        process_identity=process_identity,
        assignment=assignment,
    )
    if launch_identity_anchor != expected_launch_identity_anchor:
        raise LearningStageWorkerError(
            "benchmark launch identity anchor lineage is invalid"
        )
    assigned_owner = LearningStageWorkerRegistry._benchmark_owner_journal(
        current=launching,
        anchor=operation_anchor,
        supervision=supervision,
        scope_name=scope_name,
        supervisor_identity=supervisor_identity,
        phase="assignment_proven",
        process_identity=process_identity,
        beacon_ref=beacon_ref,
        assignment_ref=assignment_ref,
        gate_state="closed",
        predecessor=acquiring_owner["content_sha256"],
    )
    gate_owner = LearningStageWorkerRegistry._benchmark_owner_journal(
        current=launching,
        anchor=operation_anchor,
        supervision=supervision,
        scope_name=scope_name,
        supervisor_identity=supervisor_identity,
        phase="gate_released",
        process_identity=process_identity,
        beacon_ref=beacon_ref,
        assignment_ref=assignment_ref,
        gate_state="released",
        predecessor=assigned_owner["content_sha256"],
    )
    if (
        owner.get("operation_anchor_ref")
        != {"content_sha256": operation_anchor["anchor_identity_sha256"]}
        or owner.get("reservation_ref")
        != {"content_sha256": launching["content_sha256"]}
        or owner.get("supervision_ref")
        != {"content_sha256": supervision["content_sha256"]}
        or owner.get("run_id") != run_id
        or owner.get("stage") != stage
        or owner.get("operation_id") != operation_id
        or owner.get("worker_id") != worker_id
        or owner.get("model_request_id")
        != original_reservation["model_request_id"]
        or owner.get("payload_sha256") != original_reservation["payload_sha256"]
        or owner.get("execution_nonce") != original_reservation["execution_nonce"]
        or owner.get("scope_name") != scope_name
        or owner.get("process_identity") != process_identity
        or owner.get("assignment_observation_ref") != assignment_ref
        or owner.get("job_policy") != exact_job_policy
        or owner.get("phase") != "cleanup_finalization_intent"
        or owner.get("gate_state") != "released"
        or owner.get("cleanup_receipt_ref") is not None
        or owner.get("predecessor_content_sha256")
        != gate_owner["content_sha256"]
    ):
        raise LearningStageWorkerError("benchmark owner journal lineage is invalid")

    intent = _validate_benchmark_artifact_ref(
        path=result_root / f"{worker_id}.benchmark-cleanup-intent.json",
        ref=value.get("finalization_intent_ref"),
        contract_version="benchmark_worker_cleanup_finalization_intent_v1",
    )
    intent_fields = {
        "contract_version", "supervision_ref", "assignment_proven_ref",
        "run_id", "stage", "operation_id", "worker_id",
        "supervisor_process_identity", "process_identity", "scope_name",
        "gate_state", "exit_observation_ref", "stable_zero_observation_ref",
        "exact_owned_handles", "exact_handle_observation_refs",
        "owner_job_handle_close_planned", "cleanup_receipt_id",
        "predecessor_content_sha256", "content_sha256",
    }
    if (
        set(intent) != intent_fields
        or intent.get("supervision_ref")
        != {"content_sha256": supervision["content_sha256"]}
        or intent.get("assignment_proven_ref") != assignment_ref
        or intent.get("run_id") != run_id
        or intent.get("stage") != stage
        or intent.get("operation_id") != operation_id
        or intent.get("worker_id") != worker_id
        or intent.get("supervisor_process_identity") != supervisor_identity
        or intent.get("process_identity") != process_identity
        or intent.get("scope_name") != scope_name
        or intent.get("gate_state") != "released"
        or intent.get("predecessor_content_sha256")
        != gate_owner["content_sha256"]
        or intent.get("cleanup_receipt_id")
        != content_sha256({"worker_id": worker_id, "scope_name": scope_name})
        or intent.get("owner_job_handle_close_planned") is not True
        or owner.get("cleanup_finalization_intent")
        != {"content_sha256": intent["content_sha256"]}
        or owner.get("exit_observation_ref") != intent.get("exit_observation_ref")
        or owner.get("stable_zero_observation_ref")
        != intent.get("stable_zero_observation_ref")
        or owner.get("exact_handle_observation_refs")
        != intent.get("exact_handle_observation_refs")
    ):
        raise LearningStageWorkerError(
            "benchmark cleanup finalization intent lineage is invalid"
        )
    stable_zero = _validate_benchmark_artifact_ref(
        path=result_root / f"{worker_id}.stable-zero.json",
        ref=intent.get("stable_zero_observation_ref"),
        contract_version="benchmark_worker_stable_zero_observation_v1",
    )
    if (
        set(stable_zero)
        != {
            "contract_version", "worker_id", "scope_name", "samples",
            "predecessor_content_sha256", "content_sha256",
        }
        or stable_zero.get("worker_id") != worker_id
        or stable_zero.get("scope_name") != scope_name
    ):
        raise LearningStageWorkerError(
            "benchmark cleanup stable-zero observation is invalid"
        )

    receipt_handle_refs = value.get("exact_handle_observation_refs")
    intent_handle_refs = intent.get("exact_handle_observation_refs")
    supervisor_ref = value.get("supervisor_absence_observation_ref")
    if supervisor_ref is None:
        exit_observation = _validate_benchmark_artifact_ref(
            path=result_root / f"{worker_id}.exit-join.json",
            ref=intent.get("exit_observation_ref"),
            contract_version="benchmark_worker_exit_join_observation_v1",
        )
        if (
            set(exit_observation)
            != {
                "contract_version", "worker_id", "process_identity",
                "exitcode", "join_result", "join_error", "observed_at",
                "predecessor_content_sha256", "content_sha256",
            }
            or exit_observation.get("worker_id") != worker_id
            or exit_observation.get("process_identity") != process_identity
            or isinstance(exit_observation.get("exitcode"), bool)
            or not isinstance(exit_observation.get("exitcode"), int)
            or exit_observation.get("join_result") != "joined"
            or exit_observation.get("join_error") is not None
            or not isinstance(exit_observation.get("observed_at"), str)
            or not exit_observation["observed_at"]
            or exit_observation.get("predecessor_content_sha256")
            != gate_owner["content_sha256"]
        ):
            raise LearningStageWorkerError(
                "benchmark exit/join observation is invalid"
            )
        expected_owned = {
            "worker_process": "closed_explicitly",
            "startup_event": "closed_explicitly",
            "beacon_file": "closed_explicitly",
            "owner_job": "open",
        }
        if (
            intent.get("exact_owned_handles") != expected_owned
            or not isinstance(intent_handle_refs, dict)
            or set(intent_handle_refs)
            != {"worker_process", "startup_event", "beacon_file"}
            or not isinstance(receipt_handle_refs, dict)
            or set(receipt_handle_refs)
            not in (
                {"worker_process", "startup_event", "beacon_file"},
                {"worker_process", "startup_event", "beacon_file", "owner_job"},
            )
            or any(
                receipt_handle_refs.get(kind) != intent_handle_refs.get(kind)
                for kind in ("worker_process", "startup_event", "beacon_file")
            )
        ):
            raise LearningStageWorkerError(
                "benchmark cleanup receipt handle refs are invalid"
            )
        predecessor = exit_observation["content_sha256"]
        for kind, suffix in (
            ("worker_process", "worker-process-close.json"),
            ("startup_event", "startup-event-close.json"),
            ("beacon_file", "beacon-file-close.json"),
        ):
            artifact = _validate_benchmark_cleanup_handle_artifact(
                result_root=result_root,
                worker_id=worker_id,
                kind=kind,
                suffix=suffix,
                ref=intent_handle_refs[kind],
                predecessor=predecessor,
                handle_identity=_benchmark_handle_identity(
                    handle_kind=kind,
                    launch_identity_anchor=launch_identity_anchor,
                    scope_name=scope_name,
                ),
            )
            predecessor = artifact["content_sha256"]
        if (
            stable_zero.get("samples") != [[], [], []]
            or stable_zero.get("predecessor_content_sha256") != predecessor
        ):
            raise LearningStageWorkerError(
                "benchmark cleanup stable-zero observation is invalid"
            )
        job_predecessor = intent["content_sha256"]
        if "owner_job" in receipt_handle_refs:
            owner_job = _validate_benchmark_cleanup_handle_artifact(
                result_root=result_root,
                worker_id=worker_id,
                kind="owner_job",
                suffix="owner-job-close.json",
                ref=receipt_handle_refs["owner_job"],
                predecessor=intent["content_sha256"],
                handle_identity=_benchmark_handle_identity(
                    handle_kind="owner_job",
                    launch_identity_anchor=launch_identity_anchor,
                    scope_name=scope_name,
                ),
            )
            job_predecessor = owner_job["content_sha256"]
    else:
        expected_owned = {
            "worker_process": "closed_by_verified_supervisor_exit",
            "startup_event": "closed_by_verified_supervisor_exit",
            "beacon_file": "closed_by_verified_supervisor_exit",
            "owner_job": "closed_by_verified_supervisor_exit",
        }
        if (
            intent.get("exact_owned_handles") != expected_owned
            or intent_handle_refs != {}
            or receipt_handle_refs != {}
        ):
            raise LearningStageWorkerError(
                "benchmark cleanup dead-supervisor handles are invalid"
            )
        supervisor_absence = _validate_benchmark_cleanup_absence_artifact(
            result_root=result_root,
            worker_id=worker_id,
            kind="supervisor",
            ref=supervisor_ref,
            predecessor=gate_owner["content_sha256"],
            scope_name=None,
            process_identity=supervisor_identity,
        )
        samples = stable_zero.get("samples")
        open_job_absent = [
            {"probe": "OpenJob", "outcome": "absent", "error_code": 2},
            {"probe": "OpenJob", "outcome": "absent", "error_code": 2},
            {"probe": "OpenJob", "outcome": "absent", "error_code": 2},
        ]
        if (
            samples not in ([[], [], []], open_job_absent)
            or stable_zero.get("predecessor_content_sha256")
            != supervisor_absence["content_sha256"]
            or intent.get("exit_observation_ref") != supervisor_ref
        ):
            raise LearningStageWorkerError(
                "benchmark cleanup dead-supervisor stable-zero is invalid"
            )
        job_predecessor = stable_zero["content_sha256"]

    expected_final_owner_body = deepcopy(gate_owner)
    expected_final_owner_body.pop("content_sha256")
    expected_final_owner_body.update({
        "phase": "cleanup_finalization_intent",
        "exit_observation_ref": deepcopy(intent["exit_observation_ref"]),
        "stable_zero_observation_ref": deepcopy(
            intent["stable_zero_observation_ref"]
        ),
        "exact_handle_observation_refs": deepcopy(intent_handle_refs),
        "cleanup_finalization_intent": {
            "content_sha256": intent["content_sha256"]
        },
        "predecessor_content_sha256": gate_owner["content_sha256"],
    })
    if owner != seal_immutable(expected_final_owner_body):
        raise LearningStageWorkerError("benchmark owner journal lineage is invalid")

    job_absence = _validate_benchmark_cleanup_absence_artifact(
        result_root=result_root,
        worker_id=worker_id,
        kind="job",
        ref=value.get("job_absence_observation_ref"),
        predecessor=job_predecessor,
        scope_name=scope_name,
        process_identity=None,
    )
    worker_absence = _validate_benchmark_cleanup_absence_artifact(
        result_root=result_root,
        worker_id=worker_id,
        kind="worker",
        ref=value.get("worker_absence_observation_ref"),
        predecessor=job_absence["content_sha256"],
        scope_name=None,
        process_identity=process_identity,
    )
    if supervisor_ref is not None:
        expected_supervisor_ref = supervisor_ref
    else:
        expected_supervisor_ref = None
    expected = seal_immutable({
        "contract_version": "benchmark_worker_cleanup_receipt_v1",
        "outcome": "verified_exact_worker_exited",
        "operation_anchor_ref": {
            "content_sha256": operation_anchor["anchor_identity_sha256"]
        },
        "reservation_ref": {
            "content_sha256": current_reservation["content_sha256"]
        },
        "supervision_ref": {"content_sha256": supervision["content_sha256"]},
        "run_id": run_id,
        "stage": stage,
        "operation_id": operation_id,
        "worker_id": worker_id,
        "process_identity": process_identity,
        "assignment_proven_ref": assignment_ref,
        "finalization_intent_ref": {
            "content_sha256": intent["content_sha256"]
        },
        "exact_handle_observation_refs": deepcopy(receipt_handle_refs),
        "job_absence_observation_ref": {
            "content_sha256": job_absence["content_sha256"]
        },
        "worker_absence_observation_ref": {
            "content_sha256": worker_absence["content_sha256"]
        },
        "supervisor_absence_observation_ref": deepcopy(expected_supervisor_ref),
        "reservation_abort_ref": None,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    })
    if value != expected:
        raise LearningStageWorkerError("benchmark cleanup receipt is invalid")
    return deepcopy(expected)


def _validate_benchmark_cleanup_receipt(
    value: object,
    *,
    result_root: Path,
    worker_id: str,
    run_id: str,
    stage: str,
    operation_id: str,
    operation_anchor: dict[str, Any],
    original_reservation: dict[str, Any],
    current_reservation: dict[str, Any],
    supervision_root: BenchmarkWorkerSupervisionRoot,
) -> dict[str, Any]:
    exact = {
        "contract_version", "outcome", "operation_anchor_ref",
        "reservation_ref", "supervision_ref", "run_id", "stage",
        "operation_id", "worker_id", "process_identity",
        "assignment_proven_ref", "finalization_intent_ref",
        "exact_handle_observation_refs", "job_absence_observation_ref",
        "worker_absence_observation_ref", "supervisor_absence_observation_ref",
        "reservation_abort_ref", "artifact_is_authorization",
        "execute_binding_enabled", "content_sha256",
    }
    if not isinstance(value, dict) or set(value) != exact:
        raise LearningStageWorkerError("benchmark cleanup receipt shape is invalid")
    if content_sha256(value) != value.get("content_sha256"):
        raise LearningStageWorkerError("benchmark cleanup receipt digest is invalid")
    if (
        value.get("contract_version") != "benchmark_worker_cleanup_receipt_v1"
        or value.get("run_id") != run_id
        or value.get("stage") != stage
        or value.get("operation_id") != operation_id
        or value.get("worker_id") != worker_id
        or value.get("operation_anchor_ref")
        != {"content_sha256": operation_anchor["anchor_identity_sha256"]}
        or value.get("reservation_ref")
        != {"content_sha256": current_reservation["content_sha256"]}
        or value.get("artifact_is_authorization") is not False
        or value.get("execute_binding_enabled") is not False
    ):
        raise LearningStageWorkerError("benchmark cleanup receipt identity is invalid")
    outcome = value.get("outcome")
    if outcome == "verified_not_launched":
        observation = _validate_benchmark_not_launched_observation(
            result_root=result_root,
            worker_id=worker_id,
            original_reservation=original_reservation,
            cancelled_reservation=current_reservation,
            operation_anchor=operation_anchor,
        )
        expected = _compose_benchmark_not_launched_receipt(
            cancelled_reservation=current_reservation,
            operation_anchor=operation_anchor,
            observation=observation,
        )
        if value != expected:
            raise LearningStageWorkerError(
                "benchmark cleanup receipt not-launched lineage is invalid"
            )
        return deepcopy(expected)
    if outcome != "verified_exact_worker_exited":
        raise LearningStageWorkerError("benchmark cleanup receipt outcome is invalid")
    if value.get("reservation_abort_ref") is not None:
        raise LearningStageWorkerError("benchmark cleanup receipt lineage is invalid")
    return _validate_benchmark_launched_cleanup_receipt(
        value,
        result_root=result_root,
        worker_id=worker_id,
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
        operation_anchor=operation_anchor,
        original_reservation=original_reservation,
        current_reservation=current_reservation,
        supervision_root=supervision_root,
    )


def _validate_persisted_benchmark_store_decision(
    *,
    result_root: Path,
    reservation: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    persisted = _validate_benchmark_artifact_ref(
        path=_benchmark_operation_artifact_path(
            result_root,
            reservation["operation_id"],
            ".benchmark-store-decision.json",
        ),
        ref={"content_sha256": decision["content_sha256"]},
        contract_version="benchmark_worker_store_anchor_decision_v1",
    )
    exact_fields = {
        "contract_version", "authority_kind", "store_identity_sha256",
        "store_state_found", "current_state_content_sha256",
        "current_revision", "current_stage", "current_operation_id",
        "current_operation_outcome", "current_incumbent_document_ref",
        "current_operation_anchor_ref", "run_id", "stage", "operation_id",
        "workflow_revision", "reservation_ref",
        "expected_operation_anchor_ref", "reason", "outcome", "predicate",
        "content_sha256",
    }
    if set(persisted) != exact_fields or persisted != decision:
        raise LearningStageWorkerError(
            "benchmark pre-anchor store decision is invalid"
        )
    return persisted


def _validate_benchmark_pre_anchor_abort_observation(
    *,
    reservation: dict[str, Any],
    aborted_reservation: dict[str, Any],
    decision: dict[str, Any],
    result_root: Path,
    reason: str,
) -> dict[str, Any]:
    _validate_persisted_benchmark_store_decision(
        result_root=result_root,
        reservation=reservation,
        decision=decision,
    )
    observation_ref = aborted_reservation.get("abort_observation_ref")
    try:
        observation = _validate_benchmark_artifact_ref(
            path=_benchmark_operation_artifact_path(
                result_root,
                reservation["operation_id"],
                ".benchmark-pre-anchor-abort.json",
            ),
            ref=observation_ref,
            contract_version="benchmark_worker_pre_anchor_abort_observation_v1",
        )
    except LearningStageWorkerError as error:
        raise LearningStageWorkerError(
            "benchmark pre-anchor abort observation is invalid"
        ) from error
    exact_fields = {
        "contract_version", "store_decision_ref", "reservation_ref", "reason",
        "owner_absence_observation_ref",
        "process_event_job_beacon_absence_observation_ref",
        "result_absence_observation_ref", "provider_absence_observation_ref",
        "predecessor_content_sha256", "content_sha256",
    }
    terminal_body = deepcopy(reservation)
    terminal_body.pop("content_sha256")
    terminal_body["reservation_state"] = "aborted_before_anchor"
    terminal_body["abort_observation_ref"] = observation_ref
    terminal_body["predecessor_content_sha256"] = reservation["content_sha256"]
    expected_aborted = seal_immutable(terminal_body)
    if (
        aborted_reservation != expected_aborted
        or set(observation) != exact_fields
        or observation.get("store_decision_ref")
        != {"content_sha256": decision["content_sha256"]}
        or observation.get("reservation_ref")
        != {"content_sha256": reservation["content_sha256"]}
        or observation.get("reason") != reason
    ):
        raise LearningStageWorkerError(
            "benchmark pre-anchor abort observation is invalid"
        )
    predecessor = _validate_benchmark_pre_anchor_absence_chain(
        result_root=result_root,
        reservation=reservation,
        refs=observation,
    )
    if observation.get("predecessor_content_sha256") != predecessor:
        raise LearningStageWorkerError(
            "benchmark pre-anchor abort observation is invalid"
        )
    return observation


def _compose_benchmark_pre_anchor_abort_receipt(
    *,
    reservation: dict[str, Any],
    aborted_reservation: dict[str, Any],
    decision: dict[str, Any],
    observation: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    return seal_immutable({
        "contract_version": "benchmark_worker_pre_anchor_abort_receipt_v1",
        "outcome": "verified_aborted_before_anchor",
        "authority_kind": reservation["authority_kind"],
        "reservation_ref": {
            "content_sha256": reservation["content_sha256"]
        },
        "store_anchor_decision_ref": {
            "content_sha256": decision["content_sha256"]
        },
        "abort_observation_ref": {
            "content_sha256": observation["content_sha256"]
        },
        "aborted_reservation_ref": {
            "content_sha256": aborted_reservation["content_sha256"]
        },
        "run_id": reservation["run_id"],
        "stage": reservation["stage"],
        "operation_id": reservation["operation_id"],
        "workflow_revision": reservation["workflow_revision"],
        "worker_id": reservation["worker_id"],
        "model_request_id": reservation["model_request_id"],
        "payload_sha256": reservation["payload_sha256"],
        "handler_payload_source_ref": deepcopy(
            reservation["handler_payload_source_ref"]
        ),
        "execution_nonce": reservation["execution_nonce"],
        "reason": reason,
        "prior_state": "reserved",
        "owner_absence_observation_ref": deepcopy(
            observation["owner_absence_observation_ref"]
        ),
        "process_event_job_beacon_absence_observation_ref": deepcopy(
            observation[
                "process_event_job_beacon_absence_observation_ref"
            ]
        ),
        "result_absence_observation_ref": deepcopy(
            observation["result_absence_observation_ref"]
        ),
        "provider_absence_observation_ref": deepcopy(
            observation["provider_absence_observation_ref"]
        ),
        "predecessor_content_sha256": observation["content_sha256"],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    })


def _validate_benchmark_pre_anchor_abort_receipt(
    value: object,
    *,
    reservation: dict[str, Any],
    aborted_reservation: dict[str, Any],
    decision: dict[str, Any],
    result_root: Path,
    reason: str,
) -> dict[str, Any]:
    observation = _validate_benchmark_pre_anchor_abort_observation(
        reservation=reservation,
        aborted_reservation=aborted_reservation,
        decision=decision,
        result_root=result_root,
        reason=reason,
    )
    expected = _compose_benchmark_pre_anchor_abort_receipt(
        reservation=reservation,
        aborted_reservation=aborted_reservation,
        decision=decision,
        observation=observation,
        reason=reason,
    )
    if value != expected:
        raise LearningStageWorkerError(
            "benchmark pre-anchor abort receipt is invalid"
        )
    return deepcopy(expected)


def _benchmark_cleanup_fault_hook(stage: str, path: Path) -> None:
    """测试故障切点；production 默认不执行副作用。"""

    del stage, path


def _benchmark_handle_fault_hook(handle_kind: str, stage: str) -> None:
    """测试真实 close 前后故障切点；production 默认无副作用。"""

    del handle_kind, stage


def _write_benchmark_cleanup_receipt_atomic(
    path: Path, payload: dict[str, Any]
) -> None:
    """按 temp/write/file flush/directory flush/replace 五阶段提交回执。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    )
    try:
        _benchmark_cleanup_fault_hook("temp_create", path)
        with temporary_path.open("x", encoding="utf-8", newline="\n") as handle:
            _benchmark_cleanup_fault_hook("write", path)
            json.dump(
                payload, handle, ensure_ascii=False, sort_keys=True, allow_nan=False
            )
            handle.write("\n")
            handle.flush()
            _benchmark_cleanup_fault_hook("file_flush", path)
            os.fsync(handle.fileno())
        _benchmark_cleanup_fault_hook("directory_fsync", path)
        _flush_windows_directory(path.parent)
        _benchmark_cleanup_fault_hook("atomic_replace", path)
        os.replace(temporary_path, path)
    except BaseException as error:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        if isinstance(error, LearningStageWorkerError):
            raise
        raise LearningStageWorkerError(
            f"failed to persist benchmark cleanup receipt {path}: {error}"
        ) from error


def _flush_windows_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateFileW(
        str(path), 0x40000000, 0x00000007, None, 3, 0x02000000, None
    )
    invalid = wintypes.HANDLE(-1).value
    if handle == invalid:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not kernel32.FlushFileBuffers(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if not kernel32.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


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


def _validate_hybrid_benchmark_provider_cleanup_projection(
    value: object,
    *,
    identity: Mapping[str, object],
) -> dict[str, Any]:
    common_fields = {
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
        "content_sha256",
    }
    if not isinstance(value, Mapping):
        raise LearningStageWorkerError(
            "benchmark Hybrid provider cleanup projection is not closed"
        )
    projection = deepcopy(dict(value))
    vista_not_acquired = (
        projection.get("outcome") == "verified_not_acquired"
        and identity.get("task_kind") == "panel_learning_calibration_sequence"
    )
    evidence_ref_name = (
        "recovered_lease_ref" if vista_not_acquired else "cleanup_receipt_ref"
    )
    outcome_fields = (
        {"provider", "task_kind", evidence_ref_name}
        if vista_not_acquired
        else {evidence_ref_name}
    )
    if set(projection) != common_fields | outcome_fields:
        raise LearningStageWorkerError(
            "benchmark Hybrid provider cleanup projection is not closed"
        )
    if (
        projection.get("contract_version") != "benchmark_provider_cleanup_ref_v1"
        or projection.get("status") != "cleanup_verified"
        or projection.get("outcome")
        not in {"verified_not_acquired", "verified_exact_process_exited"}
        or projection.get("authority_kind")
        != "benchmark_v2_workflow_service_dispatch_cleanup"
        or (
            vista_not_acquired
            and (
                projection.get("provider") != "vista"
                or projection.get("task_kind")
                != "panel_learning_calibration_sequence"
            )
        )
        or any(
            projection.get(name) != identity.get(name)
            for name in (
                "run_id",
                "stage",
                "operation_id",
                "worker_id",
                "model_request_id",
                "payload_sha256",
            )
        )
        or content_sha256(projection) != projection.get("content_sha256")
    ):
        raise LearningStageWorkerError(
            "benchmark Hybrid provider cleanup projection lineage differs"
        )
    for name in (
        "reservation_ref",
        "acquisition_owner_ref",
        "acquisition_intent_ref",
        "runtime_owner_ref",
        evidence_ref_name,
    ):
        _benchmark_exact_ref(
            projection.get(name), f"benchmark Hybrid provider cleanup {name}"
        )
    if (
        vista_not_acquired
        and projection["reservation_ref"] != projection["acquisition_intent_ref"]
    ):
        raise LearningStageWorkerError(
            "benchmark Hybrid provider no-acquisition cleanup lineage differs"
        )
    return projection


def _validate_benchmark_v2_review_worker_ref(
    value: object,
    *,
    identity: Mapping[str, object],
) -> dict[str, Any]:
    fields = {
        "contract_version",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "task_kind",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise LearningStageWorkerError(
            "benchmark review no-provider cleanup worker ref is not closed"
        )
    worker_ref = deepcopy(dict(value))
    if (
        worker_ref.get("contract_version")
        != "benchmark_v2_workflow_service_generic_worker_ref_v1"
        or worker_ref.get("task_kind")
        != "panel_learning_hybrid_review_projection"
        or any(
            worker_ref.get(name) != identity.get(name)
            for name in (
                "run_id",
                "stage",
                "operation_id",
                "worker_id",
                "model_request_id",
                "payload_sha256",
                "task_kind",
            )
        )
        or worker_ref.get("content_sha256") != content_sha256(worker_ref)
    ):
        raise LearningStageWorkerError(
            "benchmark review no-provider cleanup worker lineage differs"
        )
    return worker_ref


def _validate_benchmark_v2_review_no_provider_absence(
    value: object,
    *,
    identity: Mapping[str, object],
    returned_worker_ref: Mapping[str, object],
) -> dict[str, Any]:
    fields = {
        "contract_version",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "task_kind",
        "provider_role",
        "current_worker_ref",
        "latest_operation_worker_ref",
        "review_dispatch_context_absent",
        "review_dispatch_receipt_absent",
        "provider_scope_absent",
        "provider_journal_absent",
        "provider_cleanup_journal_absent",
        "deterministic_provider_lease_artifact_absent",
        "deterministic_provider_owner_artifact_absent",
        "deterministic_provider_runtime_artifact_absent",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise LearningStageWorkerError(
            "benchmark review no-provider cleanup absence observation is not closed"
        )
    observation = deepcopy(dict(value))
    identity_fields = (
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "task_kind",
    )
    if (
        observation.get("contract_version")
        != _BENCHMARK_V2_REVIEW_NO_PROVIDER_ABSENCE_CONTRACT
        or observation.get("provider_role") != "review"
        or any(
            observation.get(name) != identity.get(name) for name in identity_fields
        )
        or observation.get("current_worker_ref") != returned_worker_ref
        or observation.get("latest_operation_worker_ref") != returned_worker_ref
        or any(
            observation.get(name) is not True
            for name in (
                "review_dispatch_context_absent",
                "review_dispatch_receipt_absent",
                "provider_scope_absent",
                "provider_journal_absent",
                "provider_cleanup_journal_absent",
                "deterministic_provider_lease_artifact_absent",
                "deterministic_provider_owner_artifact_absent",
                "deterministic_provider_runtime_artifact_absent",
            )
        )
        or observation.get("artifact_is_authorization") is not False
        or observation.get("execute_binding_enabled") is not False
        or observation.get("content_sha256") != content_sha256(observation)
    ):
        raise LearningStageWorkerError(
            "benchmark review no-provider cleanup absence lineage differs"
        )
    return observation


def _validate_benchmark_v2_review_no_provider_cleanup_projection(
    value: object,
    *,
    identity: Mapping[str, object],
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
        "task_kind",
        "provider_role",
        "worker_status",
        "runtime_attached",
        "result_available",
        "result_adopted",
        "continuation_phase",
        "cancellation_backend_termination",
        "cancellation_model_request_termination",
        "service_binding_ref",
        "terminal_prepared_continuation_receipt_ref",
        "returned_worker_ref",
        "worker_cleanup_ref",
        "live_absence_observation",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise LearningStageWorkerError(
            "benchmark review no-provider cleanup projection is not closed"
        )
    projection = deepcopy(dict(value))
    returned_worker_ref = _validate_benchmark_v2_review_worker_ref(
        projection.get("returned_worker_ref"), identity=identity
    )
    identity_fields = (
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "task_kind",
    )
    if (
        projection.get("contract_version")
        != _BENCHMARK_V2_REVIEW_NO_PROVIDER_CLEANUP_CONTRACT
        or projection.get("status") != "cleanup_verified"
        or projection.get("outcome")
        != "verified_review_provider_not_applicable"
        or projection.get("authority_kind")
        != "benchmark_v2_workflow_service_review_no_provider_cleanup"
        or projection.get("provider_role") != "review"
        or projection.get("worker_status") != "completed"
        or projection.get("runtime_attached") is not False
        or projection.get("result_available") is not True
        or projection.get("result_adopted") is not True
        or projection.get("continuation_phase") != "terminal_prepared"
        or projection.get("cancellation_backend_termination")
        not in {"not_running", "terminated"}
        or projection.get("cancellation_model_request_termination")
        not in {"request_not_active", "terminated"}
        or any(projection.get(name) != identity.get(name) for name in identity_fields)
        or projection.get("artifact_is_authorization") is not False
        or projection.get("execute_binding_enabled") is not False
        or projection.get("content_sha256") != content_sha256(projection)
    ):
        raise LearningStageWorkerError(
            "benchmark review no-provider cleanup projection lineage differs"
        )
    for name in (
        "service_binding_ref",
        "terminal_prepared_continuation_receipt_ref",
        "worker_cleanup_ref",
    ):
        _benchmark_exact_ref(
            projection.get(name), f"benchmark review no-provider cleanup {name}"
        )
    projection["returned_worker_ref"] = returned_worker_ref
    projection["live_absence_observation"] = (
        _validate_benchmark_v2_review_no_provider_absence(
            projection.get("live_absence_observation"),
            identity=identity,
            returned_worker_ref=returned_worker_ref,
        )
    )
    return projection


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
    provider_cleanup_ref = payload.get("benchmark_provider_cleanup_ref")
    if provider_cleanup_ref is not None:
        provider_cleanup_ref = (
            _validate_hybrid_benchmark_provider_cleanup_projection(
                provider_cleanup_ref,
                identity=identity,
            )
        )
    no_provider_cleanup_ref = payload.get("benchmark_v2_no_provider_cleanup_ref")
    no_provider_cleanup_state = payload.get(
        "benchmark_v2_no_provider_cleanup_state"
    )
    if no_provider_cleanup_state not in {None, "sealed"}:
        raise LearningStageWorkerError(
            "benchmark review no-provider cleanup persisted state is invalid"
        )
    if no_provider_cleanup_ref is not None:
        no_provider_cleanup_ref = (
            _validate_benchmark_v2_review_no_provider_cleanup_projection(
                no_provider_cleanup_ref,
                identity=identity,
            )
        )
    if (no_provider_cleanup_ref is None) != (no_provider_cleanup_state is None):
        raise LearningStageWorkerError(
            "benchmark review no-provider cleanup persisted proof is missing"
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
        "benchmark_provider_cleanup_ref": provider_cleanup_ref,
        "benchmark_v2_no_provider_cleanup_ref": no_provider_cleanup_ref,
        "benchmark_v2_no_provider_cleanup_state": no_provider_cleanup_state,
        "start_cleanup_evidence": (
            deepcopy(payload.get("start_cleanup_evidence"))
            if isinstance(payload.get("start_cleanup_evidence"), dict)
            else None
        ),
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


def _closed_content_sha256_ref(
    value: Any,
    *,
    label: str,
) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"content_sha256"}:
        raise LearningStageWorkerError(
            f"worker result {label} must be a closed content SHA-256 object"
        )
    content_sha256 = value.get("content_sha256")
    if (
        not isinstance(content_sha256, str)
        or len(content_sha256) != 64
        or any(character not in "0123456789abcdef" for character in content_sha256)
    ):
        raise LearningStageWorkerError(
            f"worker result {label} must contain lowercase SHA-256"
        )
    return {"content_sha256": content_sha256}


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
        and isinstance(managed_result, dict)
        and managed_result.get("contract_version")
        == "learning_hybrid_stage_failure_v1"
        and isinstance(managed_result.get("failure_reason"), str)
        and bool(managed_result["failure_reason"].strip())
        and model_lifecycle == {"status": "model_lease_not_acquired"}
        and lifecycle is None
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


_PRODUCTION_LEARNING_STAGE_WORKER_REGISTRY: LearningStageWorkerRegistry | None = None
_PRODUCTION_LEARNING_STAGE_WORKER_REGISTRY_LOCK = RLock()
learning_stage_worker_registry: LearningStageWorkerRegistry | None = None


def get_production_learning_stage_worker_registry() -> LearningStageWorkerRegistry:
    """仅在父端服务组合真正使用时创建 production Registry。"""

    global _PRODUCTION_LEARNING_STAGE_WORKER_REGISTRY
    global learning_stage_worker_registry
    if _PRODUCTION_LEARNING_STAGE_WORKER_REGISTRY is None:
        with _PRODUCTION_LEARNING_STAGE_WORKER_REGISTRY_LOCK:
            if _PRODUCTION_LEARNING_STAGE_WORKER_REGISTRY is None:
                _PRODUCTION_LEARNING_STAGE_WORKER_REGISTRY = (
                    LearningStageWorkerRegistry(
                        result_root=Path(__file__).resolve().parents[2]
                        / "logs"
                        / "workflow-workers",
                        benchmark_supervision_root=(
                            get_production_benchmark_worker_supervision_root()
                        ),
                    )
                )
    learning_stage_worker_registry = _PRODUCTION_LEARNING_STAGE_WORKER_REGISTRY
    return _PRODUCTION_LEARNING_STAGE_WORKER_REGISTRY
