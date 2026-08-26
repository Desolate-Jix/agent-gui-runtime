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
from typing import Any, Callable, Iterator
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

BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS = 5000
_BENCHMARK_RESERVATION_VERSION = "benchmark_worker_identity_reservation_v1"
_BENCHMARK_ANCHOR_VERSION = "benchmark_worker_operation_anchor_v1"
_BENCHMARK_SUPERVISION_VERSION = "benchmark_worker_supervision_v1"
_BENCHMARK_EXPECTED_SUPERVISION_VERSION = "benchmark_worker_expected_supervision_v1"
_BENCHMARK_CONFIRMATION_VERSION = "benchmark_worker_anchor_confirmation_v1"
_BENCHMARK_SOURCE_VERSION = "benchmark_v2_incumbent_handler_payload_source_v1"
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
_BENCHMARK_CONTROLLER_LOCAL = local()
_PRODUCTION_BENCHMARK_ROOT: BenchmarkWorkerSupervisionRoot | None = None


def _benchmark_root_digest(
    *, authority_kind: str, journal_root: Path, workflow_store: object
) -> str:
    state_path = getattr(workflow_store, "_state_path", None)
    state_identity = (
        str(Path(state_path).resolve()).casefold()
        if state_path is not None
        else f"memory:{content_sha256({'journal_root': str(journal_root.resolve()).casefold()})}"
    )
    return content_sha256({
        "contract_version": "benchmark_worker_store_identity_v1",
        "authority_kind": authority_kind,
        "store_class": f"{type(workflow_store).__module__}.{type(workflow_store).__qualname__}",
        "canonical_state_path_or_memory_token": state_identity,
    })


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
    identity_sha256 = _benchmark_root_digest(
        authority_kind="test_only", journal_root=root_path,
        workflow_store=workflow_store,
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
    return root


def get_production_benchmark_worker_supervision_root(
) -> BenchmarkWorkerSupervisionRoot:
    """延迟绑定 production singleton store 的只读 getter authority。"""

    global _PRODUCTION_BENCHMARK_ROOT
    if _PRODUCTION_BENCHMARK_ROOT is not None:
        return _PRODUCTION_BENCHMARK_ROOT
    from app.learn.workflow_store import learning_workflow_run_store
    journal_root = (_PROJECT_ROOT / "logs" / "workflow-workers").resolve()
    capability = object()
    store_capability = object()
    identity_sha256 = _benchmark_root_digest(
        authority_kind="production_workflow_service", journal_root=journal_root,
        workflow_store=learning_workflow_run_store,
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
    return root


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


@contextmanager
def hold_benchmark_worker_controller(
    *,
    supervision_root: BenchmarkWorkerSupervisionRoot,
    run_id: str,
    stage: str,
    operation_id: str,
    timeout_ms: int = BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS,
) -> Iterator[object]:
    """持有 operation 级命名 Mutex；同线程递归共享一个 guard。"""

    root = _validate_benchmark_supervision_root(supervision_root)
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 0 < timeout_ms <= 0xFFFFFFFE:
        raise LearningStageWorkerError("benchmark controller timeout is invalid")
    from app.learn.hybrid.windows_process_scope import (
        benchmark_worker_controller_mutex_name_v1,
    )
    import win32api
    import win32event

    name = benchmark_worker_controller_mutex_name_v1(
        authority_kind=root.authority_kind,
        run_id=_required_text(run_id, "run_id"),
        stage=_required_text(stage, "stage"),
        operation_id=_required_text(operation_id, "operation_id"),
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
        outcome = win32event.WaitForSingleObject(existing["handle"], timeout_ms)
        if outcome not in {win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED}:
            if outcome == win32event.WAIT_TIMEOUT:
                raise LearningStageWorkerError("benchmark worker controller mutex timed out")
            raise LearningStageWorkerError("benchmark worker controller mutex wait failed")
        existing["depth"] += 1
        primary: BaseException | None = None
        release_error: BaseException | None = None
        try:
            yield existing["guard"]
        except BaseException as error:
            primary = error
        try:
            win32event.ReleaseMutex(existing["handle"])
        except BaseException as error:
            release_error = error
        finally:
            existing["depth"] -= 1
        if release_error is not None:
            _record_benchmark_controller_cleanup_failure(
                root=root, name=name, recursion_level=existing["depth"] + 1,
                primary=primary,
                release={"status": "error", "error_type": type(release_error).__name__, "message": str(release_error)},
                close={"status": "not_outermost"},
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

    handle = win32event.CreateMutex(None, False, name)
    admitted = False
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
        guard = object()
        held[name] = {"guard": guard, "handle": handle, "depth": 1, "root": root}
        try:
            yield guard
        except BaseException as error:
            primary = error
        held.pop(name, None)
    finally:
        release_error: BaseException | None = None
        close_error: BaseException | None = None
        release_result: dict[str, Any] = {"status": "not_owned"}
        close_result: dict[str, Any] = {"status": "not_open"}
        if admitted and handle is not None:
            try:
                win32event.ReleaseMutex(handle)
                release_result = {"status": "released"}
            except BaseException as error:
                release_error = error
                release_result = {"status": "error", "error_type": type(error).__name__, "message": str(error)}
        try:
            if handle is not None:
                win32api.CloseHandle(handle)
                close_result = {"status": "closed"}
        except BaseException as error:
            close_error = error
            close_result = {"status": "error", "error_type": type(error).__name__, "message": str(error)}
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

    def __init__(self, evidence: dict[str, Any]) -> None:
        super().__init__("Hybrid worker start cleanup is indeterminate")
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
    binding_lifecycle: dict[str, object] | None = None
    binding_entered = False
    try:
        execution_payload = deepcopy(payload)
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
                validate_spawned_worker_observation_payload,
            )

            validate_spawned_worker_observation_payload(
                payload=execution_payload,
                serialized=serialized_binding,
            )
            binding_context = install_spawned_worker_window_binding(
                serialized=serialized_binding,
                worker_operation_id=str(identity.get("operation_id") or ""),
            )
            binding_lifecycle = binding_context.__enter__()
            binding_entered = True
        response = execute_learning_stage_worker_task(
            task_kind,
            execution_payload,
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
        binding_cleanup_error: BaseException | None = None
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
        return deepcopy(value)

    def _benchmark_reservation_path(self, operation_id: str) -> Path:
        return self._result_root / f"{operation_id}.benchmark-reservation.json"

    def _persist_benchmark_reservation(self, reservation: dict[str, Any]) -> None:
        _write_json_atomic(
            self._benchmark_reservation_path(reservation["operation_id"]), reservation
        )

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
                    "supervision_inputs_ref": {
                        "content_sha256": content_sha256({
                            "authority_kind": root.authority_kind,
                            "store_identity_sha256": root.store_identity_sha256,
                            "journal_root": str(root.journal_root),
                        })
                    },
                    "reservation_state": "reserved", "abort_observation_ref": None,
                    "predecessor_content_sha256": source["content_sha256"],
                }
                reservation = seal_immutable(body)
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
                return deepcopy(value)

    def _benchmark_by_ref(self, reservation_ref: object) -> dict[str, Any]:
        ref = _benchmark_exact_ref(reservation_ref, "benchmark reservation ref")
        reservation = self._benchmark_reservations_by_ref.get(ref["content_sha256"])
        if reservation is None:
            raise LearningStageWorkerError("benchmark reservation ref not found")
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
                confirmation_path = self._result_root / f"{initial['operation_id']}.benchmark-anchor-confirmation.json"
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
            assignment = seal_immutable(assignment_body)
            _write_json_atomic(
                self._result_root
                / f"{current['worker_id']}.benchmark-assignment.json",
                assignment,
            )
            owner = self._benchmark_owner_journal(
                current=launching, anchor=anchor, supervision=supervision,
                scope_name=scope_name, supervisor_identity=supervisor_identity,
                phase="assignment_proven", process_identity=process_identity,
                beacon_ref={"content_sha256": beacon["content_sha256"]},
                assignment_ref={"content_sha256": assignment["content_sha256"]},
                gate_state="closed", predecessor=owner["content_sha256"],
            )
            _write_json_atomic(owner_path, owner)
            win32event.SetEvent(event_handle)
            owner = self._benchmark_owner_journal(
                current=launching, anchor=anchor, supervision=supervision,
                scope_name=scope_name, supervisor_identity=supervisor_identity,
                phase="gate_released", process_identity=process_identity,
                beacon_ref={"content_sha256": beacon["content_sha256"]},
                assignment_ref={"content_sha256": assignment["content_sha256"]},
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
        except BaseException:
            failed_beacon = None
            if beacon_path.exists():
                try:
                    failed_beacon = json.loads(beacon_path.read_text(encoding="utf-8"))
                except BaseException:
                    failed_beacon = None
            failed_process_identity = None
            if process is not None and isinstance(getattr(process, "pid", None), int):
                try:
                    import psutil
                    failed_process_identity = {
                        "pid": process.pid,
                        "create_time_ns": int(
                            round(psutil.Process(process.pid).create_time() * 1_000_000_000)
                        ),
                    }
                except BaseException:
                    failed_process_identity = None
            if process is not None:
                try:
                    if process.is_alive(): process.terminate()
                    process.join(5)
                except BaseException:
                    pass
                try: process.close()
                except BaseException: pass
            if event_handle is not None:
                try: win32api.CloseHandle(event_handle)
                except BaseException: pass
            if scope is not None:
                try: scope.close()
                except BaseException: pass
            if isinstance(failed_process_identity, dict) and isinstance(locals().get("owner"), dict):
                try:
                    failed_owner = self._benchmark_owner_journal(
                        current=self._benchmark_reservations.get(operation_key, current),
                        anchor=anchor, supervision=supervision,
                        scope_name=scope_name, supervisor_identity=supervisor_identity,
                        phase="recovery_required",
                        process_identity=failed_process_identity,
                        beacon_ref=(
                            {"content_sha256": failed_beacon.get("content_sha256")}
                            if isinstance(failed_beacon, dict)
                            and failed_beacon.get("process_identity") == failed_process_identity
                            else None
                        ),
                        assignment_ref=None, gate_state="not_released_due_to_failure",
                        predecessor=owner["content_sha256"],
                    )
                    _write_json_atomic(owner_path, failed_owner)
                    beacon_path.unlink(missing_ok=True)
                except BaseException:
                    pass
            raise

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
                receipt_path = self._result_root / f"{operation}.benchmark-pre-anchor-abort-receipt.json"
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
                    observation_path = self._result_root / f"{operation}.benchmark-pre-anchor-abort.json"
                    if not observation_path.exists():
                        raise LearningStageWorkerError("benchmark pre-anchor abort replay does not match")
                    observation = json.loads(observation_path.read_text(encoding="utf-8"))
                    if (
                        current.get("abort_observation_ref")
                        != {"content_sha256": observation.get("content_sha256")}
                        or observation.get("store_decision_ref")
                        != {"content_sha256": decision["content_sha256"]}
                    ):
                        raise LearningStageWorkerError("benchmark pre-anchor abort replay does not match")
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
                decision_path = self._result_root / f"{operation}.benchmark-store-decision.json"
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
                observation_path = self._result_root / f"{operation}.benchmark-pre-anchor-abort.json"
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
                receipt_path = self._result_root / f"{worker}.benchmark-cleanup.json"
                if receipt_path.exists():
                    return _validate_benchmark_cleanup_receipt(
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
                record = self._records.get(worker)
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
                    receipt = seal_immutable({
                        "contract_version": "benchmark_worker_cleanup_receipt_v1",
                        "outcome": "verified_not_launched",
                        "operation_anchor_ref": {"content_sha256": expected_operation_anchor["anchor_identity_sha256"]},
                        "reservation_ref": {"content_sha256": cancelled["content_sha256"]},
                        "supervision_ref": None, "run_id": run, "stage": stage_value,
                        "operation_id": operation, "worker_id": worker,
                        "process_identity": None, "assignment_proven_ref": None,
                        "finalization_intent_ref": None, "exact_handle_observation_refs": None,
                        "job_absence_observation_ref": None, "worker_absence_observation_ref": None,
                        "supervisor_absence_observation_ref": None,
                        "reservation_abort_ref": {"content_sha256": no_launch["content_sha256"]},
                        "artifact_is_authorization": False, "execute_binding_enabled": False,
                    })
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
                process_identity = None
                owner_path = Path(record["benchmark_owner_path"])
                owner = json.loads(owner_path.read_text(encoding="utf-8"))
                process_identity = owner.get("process_identity")
                handle_refs: dict[str, Any] = deepcopy(
                    record.get("benchmark_handle_refs") or {}
                )
                process_exitcode = record.get("benchmark_process_exitcode")
                if "worker_process" not in handle_refs:
                    if terminate and process is not None and process.is_alive():
                        process.terminate()
                    if process is not None:
                        process.join(15)
                        if process.is_alive():
                            raise LearningStageWorkerError("benchmark worker did not exit")
                    process_exitcode = getattr(process, "exitcode", None)
                    _benchmark_handle_fault_hook("worker_process", "before_call")
                    if process is not None:
                        process.close()
                    observation = seal_immutable({
                        "contract_version": "benchmark_worker_handle_close_observation_v1",
                        "handle_kind": "worker_process", "result": "closed",
                        "worker_id": worker, "predecessor_content_sha256": owner["content_sha256"],
                    })
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
                    if event_handle is not None:
                        win32api.CloseHandle(event_handle)
                    record["benchmark_event_handle"] = None
                    observation = seal_immutable({
                        "contract_version": "benchmark_worker_handle_close_observation_v1",
                        "handle_kind": "startup_event", "result": "closed",
                        "worker_id": worker, "predecessor_content_sha256": handle_refs["worker_process"]["content_sha256"],
                    })
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
                    if beacon_path.exists():
                        beacon_path.unlink()
                    observation = seal_immutable({
                        "contract_version": "benchmark_worker_handle_close_observation_v1",
                        "handle_kind": "beacon_file", "result": "closed",
                        "worker_id": worker, "predecessor_content_sha256": handle_refs["startup_event"]["content_sha256"],
                    })
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
                    "exit_observation_ref": {"content_sha256": content_sha256({"exitcode": process_exitcode})},
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
                scope.close()
                record["benchmark_scope"] = None
                _benchmark_handle_fault_hook("owner_job", "after_success")
                owner_job_observation = seal_immutable({
                    "contract_version": "benchmark_worker_handle_close_observation_v1",
                    "handle_kind": "owner_job",
                    "result": "closed",
                    "worker_id": worker,
                    "predecessor_content_sha256": intent["content_sha256"],
                })
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
        launched_fields = (
            "supervision_ref", "process_identity", "assignment_proven_ref",
            "finalization_intent_ref", "exact_handle_observation_refs",
            "job_absence_observation_ref", "worker_absence_observation_ref",
            "supervisor_absence_observation_ref",
        )
        if (
            current_reservation.get("reservation_state")
            != "cancelled_before_launch"
            or any(value.get(field) is not None for field in launched_fields)
            or value.get("reservation_abort_ref") is None
        ):
            raise LearningStageWorkerError(
                "benchmark cleanup receipt not-launched lineage is invalid"
            )
        observation = _validate_benchmark_artifact_ref(
            path=result_root / f"{worker_id}.benchmark-not-launched.json",
            ref=value["reservation_abort_ref"],
            contract_version="benchmark_worker_not_launched_observation_v1",
        )
        no_launch_fields = {
            "contract_version", "outcome", "authority_kind",
            "reservation_ref", "run_id", "stage", "operation_id",
            "worker_id", "owner_absence_observation_ref",
            "process_event_job_beacon_absence_observation_ref",
            "result_absence_observation_ref", "provider_absence_observation_ref",
            "predecessor_content_sha256", "artifact_is_authorization",
            "execute_binding_enabled", "content_sha256",
        }
        if (
            set(observation) != no_launch_fields
            or observation.get("authority_kind")
            != original_reservation["authority_kind"]
            or observation.get("reservation_ref")
            != {
                "content_sha256": current_reservation[
                    "predecessor_content_sha256"
                ]
            }
            or observation.get("run_id") != run_id
            or observation.get("stage") != stage
            or observation.get("operation_id") != operation_id
            or observation.get("worker_id") != worker_id
            or
            current_reservation.get("abort_observation_ref")
            != value["reservation_abort_ref"]
            or observation.get("outcome")
            != "verified_no_launch_artifacts"
        ):
            raise LearningStageWorkerError(
                "benchmark cleanup receipt no-launch observation is invalid"
            )
        predecessor = observation["reservation_ref"]["content_sha256"]
        for field, kind in (
            ("owner_absence_observation_ref", "owner"),
            (
                "process_event_job_beacon_absence_observation_ref",
                "process_event_job_beacon",
            ),
            ("result_absence_observation_ref", "result"),
            ("provider_absence_observation_ref", "provider"),
        ):
            artifact = _validate_benchmark_artifact_ref(
                path=result_root
                / f"{worker_id}.pre-anchor-{kind}-absence.json",
                ref=observation.get(field),
                contract_version=(
                    "benchmark_worker_pre_anchor_absence_observation_v1"
                ),
            )
            if (
                set(artifact)
                != {
                    "contract_version", "observation_kind", "outcome",
                    "reservation_ref", "run_id", "stage", "operation_id",
                    "worker_id", "checks", "predecessor_content_sha256",
                    "content_sha256",
                }
                or artifact.get("observation_kind") != kind
                or artifact.get("outcome") != "absent"
                or artifact.get("reservation_ref")
                != observation["reservation_ref"]
                or artifact.get("run_id") != run_id
                or artifact.get("stage") != stage
                or artifact.get("operation_id") != operation_id
                or artifact.get("worker_id") != worker_id
                or artifact.get("predecessor_content_sha256") != predecessor
            ):
                raise LearningStageWorkerError(
                    "benchmark cleanup no-launch absence lineage is invalid"
                )
            predecessor = artifact["content_sha256"]
        return deepcopy(value)
    if outcome != "verified_exact_worker_exited":
        raise LearningStageWorkerError("benchmark cleanup receipt outcome is invalid")
    if value.get("reservation_abort_ref") is not None:
        raise LearningStageWorkerError("benchmark cleanup receipt lineage is invalid")
    owner_path = result_root / f"{worker_id}.benchmark-owner.json"
    owner = _read_json_object(owner_path, label="benchmark owner journal")
    if content_sha256(owner) != owner.get("content_sha256"):
        raise LearningStageWorkerError("benchmark owner journal digest is invalid")
    supervision = compose_benchmark_worker_supervision_v1(
        supervision_root=supervision_root,
        reservation=original_reservation,
        expected_operation_anchor=operation_anchor,
        supervisor_process_identity=owner.get("supervisor_process_identity"),
        startup_gate_timeout_ms=15_000,
    )
    if (
        value.get("supervision_ref")
        != {"content_sha256": supervision["content_sha256"]}
        or value.get("assignment_proven_ref")
        != owner.get("assignment_observation_ref")
        or value.get("process_identity") != owner.get("process_identity")
    ):
        raise LearningStageWorkerError(
            "benchmark cleanup receipt supervision is invalid"
        )
    assignment = _validate_benchmark_artifact_ref(
        path=result_root / f"{worker_id}.benchmark-assignment.json",
        ref=value.get("assignment_proven_ref"),
        contract_version="benchmark_worker_scope_assignment_v1",
    )
    if (
        assignment.get("process_identity") != value.get("process_identity")
        or assignment.get("scope_name") != owner.get("scope_name")
    ):
        raise LearningStageWorkerError(
            "benchmark cleanup assignment observation is invalid"
        )
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
        or intent.get("supervision_ref") != value.get("supervision_ref")
        or intent.get("assignment_proven_ref")
        != value.get("assignment_proven_ref")
        or intent.get("process_identity") != value.get("process_identity")
        or intent.get("worker_id") != worker_id
        or intent.get("owner_job_handle_close_planned") is not True
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
        or stable_zero.get("scope_name") != owner.get("scope_name")
        or not isinstance(stable_zero.get("samples"), list)
        or len(stable_zero["samples"]) != 3
    ):
        raise LearningStageWorkerError(
            "benchmark cleanup stable-zero observation is invalid"
        )
    handle_refs = value.get("exact_handle_observation_refs")
    if not isinstance(handle_refs, dict):
        raise LearningStageWorkerError(
            "benchmark cleanup receipt handle refs are invalid"
        )
    handle_paths = {
        "worker_process": "worker-process-close.json",
        "startup_event": "startup-event-close.json",
        "beacon_file": "beacon-file-close.json",
        "owner_job": "owner-job-close.json",
    }
    for kind in ("worker_process", "startup_event", "beacon_file"):
        if (
            handle_refs.get(kind) is None
            and value.get("supervisor_absence_observation_ref") is not None
            and isinstance(intent.get("exact_owned_handles"), dict)
            and intent["exact_owned_handles"].get(kind)
            == "closed_by_verified_supervisor_exit"
        ):
            continue
        artifact = _validate_benchmark_artifact_ref(
            path=result_root / f"{worker_id}.{handle_paths[kind]}",
            ref=handle_refs.get(kind),
            contract_version="benchmark_worker_handle_close_observation_v1",
        )
        if (
            set(artifact)
            != {
                "contract_version", "handle_kind", "result", "worker_id",
                "predecessor_content_sha256", "content_sha256",
            }
            or artifact.get("handle_kind") != kind
            or artifact.get("result") != "closed"
            or artifact.get("worker_id") != worker_id
        ):
            raise LearningStageWorkerError(
                "benchmark cleanup receipt handle observation is invalid"
            )
    if handle_refs.get("owner_job") is not None:
        artifact = _validate_benchmark_artifact_ref(
            path=result_root / f"{worker_id}.{handle_paths['owner_job']}",
            ref=handle_refs["owner_job"],
            contract_version="benchmark_worker_handle_close_observation_v1",
        )
        if (
            set(artifact)
            != {
                "contract_version", "handle_kind", "result", "worker_id",
                "predecessor_content_sha256", "content_sha256",
            }
            or artifact.get("handle_kind") != "owner_job"
            or artifact.get("result") != "closed"
            or artifact.get("worker_id") != worker_id
        ):
            raise LearningStageWorkerError(
                "benchmark cleanup receipt Job observation is invalid"
            )
    for kind, field in (
        ("job", "job_absence_observation_ref"),
        ("worker", "worker_absence_observation_ref"),
        ("supervisor", "supervisor_absence_observation_ref"),
    ):
        ref = value.get(field)
        if ref is None and kind == "supervisor":
            continue
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
            or (
                kind == "job"
                and artifact.get("scope_name") != owner.get("scope_name")
            )
            or (
                kind == "worker"
                and artifact.get("process_identity")
                != value.get("process_identity")
            )
            or (
                kind == "supervisor"
                and artifact.get("process_identity")
                != owner.get("supervisor_process_identity")
            )
        ):
            raise LearningStageWorkerError(
                "benchmark cleanup receipt absence observation is invalid"
            )
    return deepcopy(value)


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
    decision_path = (
        result_root
        / f"{reservation['operation_id']}.benchmark-store-decision.json"
    )
    persisted_decision = _validate_benchmark_artifact_ref(
        path=decision_path,
        ref={"content_sha256": decision["content_sha256"]},
        contract_version="benchmark_worker_store_anchor_decision_v1",
    )
    decision_fields = {
        "contract_version", "authority_kind", "store_identity_sha256",
        "store_state_found", "current_state_content_sha256",
        "current_revision", "current_stage", "current_operation_id",
        "current_operation_outcome", "current_incumbent_document_ref",
        "current_operation_anchor_ref", "run_id", "stage", "operation_id",
        "workflow_revision", "reservation_ref",
        "expected_operation_anchor_ref", "reason", "outcome", "predicate",
        "content_sha256",
    }
    if set(persisted_decision) != decision_fields or persisted_decision != decision:
        raise LearningStageWorkerError(
            "benchmark pre-anchor store decision is invalid"
        )
    observation = _validate_benchmark_artifact_ref(
        path=result_root
        / f"{reservation['operation_id']}.benchmark-pre-anchor-abort.json",
        ref=(
            value.get("abort_observation_ref")
            if isinstance(value, dict)
            else None
        ),
        contract_version="benchmark_worker_pre_anchor_abort_observation_v1",
    )
    observation_fields = {
        "contract_version", "store_decision_ref", "reservation_ref", "reason",
        "owner_absence_observation_ref",
        "process_event_job_beacon_absence_observation_ref",
        "result_absence_observation_ref", "provider_absence_observation_ref",
        "predecessor_content_sha256", "content_sha256",
    }
    if (
        set(observation) != observation_fields
        or observation.get("store_decision_ref")
        != {"content_sha256": decision["content_sha256"]}
        or observation.get("reservation_ref")
        != {"content_sha256": reservation["content_sha256"]}
        or observation.get("reason") != reason
    ):
        raise LearningStageWorkerError(
            "benchmark pre-anchor abort observation is invalid"
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
    paths = {
        "owner_absence_observation_ref": "owner",
        "process_event_job_beacon_absence_observation_ref": (
            "process_event_job_beacon"
        ),
        "result_absence_observation_ref": "result",
        "provider_absence_observation_ref": "provider",
    }
    predecessor = reservation["content_sha256"]
    for field, kind in paths.items():
        artifact = _validate_benchmark_artifact_ref(
            path=result_root
            / f"{reservation['worker_id']}.pre-anchor-{kind}-absence.json",
            ref=value[field],
            contract_version=(
                "benchmark_worker_pre_anchor_absence_observation_v1"
            ),
        )
        if (
            set(artifact) != {
                "contract_version", "observation_kind", "outcome",
                "reservation_ref", "run_id", "stage", "operation_id",
                "worker_id", "checks", "predecessor_content_sha256",
                "content_sha256",
            }
            or
            artifact.get("observation_kind") != kind
            or artifact.get("outcome") != "absent"
            or artifact.get("reservation_ref")
            != {"content_sha256": reservation["content_sha256"]}
            or artifact.get("run_id") != reservation["run_id"]
            or artifact.get("stage") != reservation["stage"]
            or artifact.get("operation_id") != reservation["operation_id"]
            or artifact.get("worker_id") != reservation["worker_id"]
            or artifact.get("predecessor_content_sha256") != predecessor
        ):
            raise LearningStageWorkerError(
                "benchmark pre-anchor absence lineage is invalid"
            )
        predecessor = artifact["content_sha256"]
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
    result_root=Path(__file__).resolve().parents[2] / "logs" / "workflow-workers",
    benchmark_supervision_root=get_production_benchmark_worker_supervision_root(),
)
