"""Benchmark-v2 真实屏幕组准备边界；不授予任何桌面动作权限。"""

from __future__ import annotations

import base64
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import psutil
from threading import RLock
import time
from typing import Any, Callable, Iterator, Mapping, Protocol

from app.core.ocr_service import ocr_service
from app.learn.hybrid import benchmark_v2_actual
from app.learn.hybrid import benchmark_v2_dispatch_attestation
from app.learn.hybrid import benchmark_v2_window_owner
from app.learn.hybrid.benchmark_v2_contracts import (
    canonical_json_bytes,
    content_sha256,
)
from app.learn.hybrid.benchmark_v2_incumbent_operation import (
    BENCHMARK_V2_WORKFLOW_SERVICE_STEP_CONTRACT,
    compose_benchmark_v2_hybrid_screen_group_start,
    compose_benchmark_v2_workflow_window_binding,
    get_production_benchmark_v2_workflow_service,
    validate_benchmark_v2_actual_completed_hybrid_cleanup,
    validate_benchmark_v2_actual_operations_stable_zero,
    validate_benchmark_v2_hybrid_screen_group_start,
    validate_benchmark_v2_incumbent_pre_reservation_recovery,
    validate_benchmark_v2_provider_dispatch_context_projection,
    validate_benchmark_v2_workflow_window_binding,
    validate_benchmark_v2_workflow_service_operation_ref,
    validate_benchmark_v2_workflow_service_step,
)
from app.learn.hybrid.benchmark_v2_lifecycle import (
    append_benchmark_v2_attempt_event,
    compose_benchmark_v2_attempt_cleanup_receipt,
    compose_benchmark_v2_lifecycle_probe_receipt_v2,
    compose_benchmark_v2_probe_stable_zero_evidence_v1,
    read_benchmark_v2_attempt_journal,
    validate_benchmark_v2_lifecycle_probe_receipt_v2,
    validate_benchmark_v2_probe_stable_zero_evidence_v1,
)
from app.learn.hybrid.benchmark_v2_provider_corpus import (
    get_production_provider_case_resolver,
    load_provider_corpus,
    provider_case_resolver_case_refs,
    provider_case_resolver_corpus_file_ref,
    validate_provider_manifest,
)
from app.learn.hybrid.benchmark_v2_window_owner import (
    close_owned_window,
    launch_owned_window,
    snapshot_owned_window,
)
from app.learn.hybrid.benchmark_v2_worker_binding import (
    get_production_server_worker_window_binding_publisher,
    publish_server_worker_window_binding,
)
from app.learn.hybrid.capture import (
    seal_hybrid_capture_bundle,
    seal_hybrid_capture_identity,
)
from app.learn.hybrid.contracts import load_hybrid_config
from app.learn.recognition.uei.builtin_learning_projection import (
    seal_builtin_ocr_evidence,
    seal_builtin_uia_evidence,
)
from app.learn.recognition.uei.canonical import (
    content_sha256 as runtime_content_sha256,
)
from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.store import UEIObjectStore


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SCREENSHOT_ROOT = Path("artifacts") / "screenshots" / "benchmark-v2"
_AUTHORITY_ROOT = (
    _PROJECT_ROOT / "runtime_state" / "benchmark-v2-worker-window-binding-authority"
).resolve()
_OMNI_PROVIDER_ID = "local.runtime/omniparser"
_OMNI_PROFILE_ID = "local.runtime/omniparser/shadow-v2"
_OMNI_PROVIDER_VERSION = "v2.0.1"
_SAFE_LIMITS = {
    "max_json_bytes": 1024 * 1024,
    "max_depth": 8,
    "max_array_items": 4096,
    "max_object_properties": 64,
    "max_string_chars": 4096,
    "allowed_json_types": [
        "object",
        "array",
        "string",
        "number",
        "boolean",
        "null",
    ],
}
_PROBE_TARGET_TASKS = {
    "omni": "panel_learning_hybrid_omni_discovery",
    "qwen": "panel_learning_hybrid_qwen_binding",
    "vista": "panel_learning_calibration_sequence",
}
_PROBE_KINDS = {"cancel", "timeout"}
_PROBE_POLL_SECONDS = 0.02
_PROBE_DEADLINE_SECONDS = 120.0
_PROBE_DEADLINE_DURATION_NS = 120_000_000_000
_PROBE_MAX_STAGNANT_READS = 4096
_PROBE_MAX_CONTINUES = 4096
_PROBE_CONTEXT_CONTRACT = "benchmark_v2_probe_context_v1"
_PROBE_REQUEST_CONTRACT = "benchmark_v2_probe_request_in_flight_v1"
_PROBE_TRIGGER_CONTRACT = "benchmark_v2_probe_trigger_receipt_v2"
_PROBE_TRIGGER_INTENT_CONTRACT = "benchmark_v2_probe_trigger_intent_v1"
_PROBE_TRIGGER_TERMINAL_CONTRACT = "benchmark_v2_probe_trigger_terminal_v1"
_PROBE_DEADLINE_EXPIRATION_CONTRACT = (
    "benchmark_v2_probe_monotonic_deadline_expiration_v1"
)
_PROBE_CONTEXT_FIELDS = {
    "contract_version",
    "attempt_ref",
    "provider_id",
    "probe_kind",
    "operation_ref",
    "provider_dispatch_context_projection",
    "window_binding_ref",
    "capture_ref",
    "screen_group_ref",
    "service_event_ref",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_PROBE_REQUEST_FIELDS = {
    "contract_version",
    "attempt_ref",
    "provider_id",
    "probe_kind",
    "operation_ref",
    "provider_dispatch_context_projection",
    "request_state",
    "dispatch_receipt_ref",
    "provider_runtime_attestation_ref",
    "attempt_event_ref",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_PROBE_TRIGGER_INTENT_FIELDS = {
    "contract_version",
    "attempt_ref",
    "provider_id",
    "probe_kind",
    "operation_ref",
    "request_in_flight_ref",
    "dispatch_receipt_ref",
    "dispatch_runtime_parent_ref",
    "process_identities",
    "evidence_scope",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_PROBE_TRIGGER_FIELDS = {
    "contract_version",
    "attempt_ref",
    "provider_id",
    "probe_kind",
    "request_in_flight_ref",
    "trigger_intent_ref",
    "service_terminal_ref",
    "cleanup_binding_ref",
    "probe_trigger_terminal_ref",
    "absence_observations",
    "evidence_scope",
    "attempt_event_ref",
    "outcome",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_ACTUAL_DIRECTORY = "actual-screen-groups"
_ACTUAL_INTENT_CONTRACT = "benchmark_v2_actual_service_intent_v1"
_ACTUAL_RESULT_CONTRACT = "benchmark_v2_actual_service_result_v1"
_ACTUAL_LIFECYCLE_CONTRACT = "benchmark_v2_actual_stable_zero_v1"
_ACTUAL_PROJECTION_RECORD_CONTRACT = "benchmark_v2_actual_projection_record_v1"
_ACTUAL_CALL_INTENT_CONTRACT = "benchmark_v2_actual_service_call_intent_v1"
_ACTUAL_CALL_RESULT_CONTRACT = "benchmark_v2_actual_service_call_result_v1"
_PRE_VISTA_EVIDENCE_CONTRACT = "benchmark_v2_actual_pre_vista_evidence_v1"
_PRE_VISTA_EVIDENCE_FIELDS = {
    "contract_version",
    "provider_group_ref",
    "omni_inventory_envelope",
    "qwen_bindings_envelope",
    "fusion_result_envelope",
    "submitted_vista_request_envelopes",
    "safety",
    "content_sha256",
}
_PRE_VISTA_ENVELOPE_FIELDS = {"ref", "canonical_bytes_b64"}
_PRE_VISTA_REF_FIELDS = {"id", "content_sha256"}
_PRE_VISTA_SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
}


class BenchmarkV2ScreenGroupIterator(Iterator[Mapping[str, object]], Protocol):
    def close(self) -> None: ...

    def __enter__(self) -> "BenchmarkV2ScreenGroupIterator": ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...


class BenchmarkV2ProductionRuntimePort(Protocol):
    def load_provider_manifest(self, *, path: Path) -> Mapping[str, object]: ...

    def prepare_screen_groups(
        self,
        *,
        provider_manifest: Mapping[str, object],
        partition: str,
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> BenchmarkV2ScreenGroupIterator: ...

    def run_actual_screen_group(
        self,
        *,
        provider_group: Mapping[str, object],
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> Mapping[str, object]: ...

    def begin_probe(
        self,
        *,
        provider_id: str,
        probe_kind: str,
        provider_manifest: Mapping[str, object],
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> Mapping[str, object]: ...

    def read_server_journal(
        self, *, probe_context: Mapping[str, object]
    ) -> Mapping[str, object]: ...

    def trigger_probe(
        self,
        *,
        probe_context: Mapping[str, object],
        probe_kind: str,
        request_in_flight_journal: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def finalize_probe_lifecycle_receipt(
        self,
        *,
        provider_manifest: Mapping[str, object],
        attempt_ref: Mapping[str, object],
        cleanup_receipt: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def cleanup_attempt(
        self, *, attempt: Mapping[str, object], reason: str
    ) -> Mapping[str, object]: ...

    def resource_counts(self) -> Mapping[str, int]: ...


class _OwnedScreenGroupIterator:
    __slots__ = ("_iterator", "_cleanup", "_iterator_done", "_closed")

    def __init__(
        self,
        iterator: Iterator[Mapping[str, object]],
        *,
        cleanup: Callable[[], object],
    ) -> None:
        self._iterator = iterator
        self._cleanup = cleanup
        self._iterator_done = False
        self._closed = False

    def __iter__(self) -> "_OwnedScreenGroupIterator":
        return self

    def __next__(self) -> Mapping[str, object]:
        if self._closed:
            raise StopIteration
        if self._iterator_done:
            raise RuntimeError("benchmark screen-group cleanup is still pending")
        try:
            return next(self._iterator)
        except StopIteration:
            self._iterator_done = True
            self._closed = True
            raise
        except BaseException:
            self._iterator_done = True
            raise

    def close(self) -> None:
        if self._closed:
            return
        if not self._iterator_done:
            close = getattr(self._iterator, "close", None)
            if not callable(close):
                raise RuntimeError("benchmark screen-group iterator is not closable")
            try:
                close()
            finally:
                self._iterator_done = True
        self._cleanup()
        self._closed = True

    def __enter__(self) -> "_OwnedScreenGroupIterator":
        if self._closed:
            raise RuntimeError("benchmark screen-group iterator is already closed")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        self.close()


class _LoadedProviderManifest(dict[str, object]):
    __slots__ = ("_source_path", "_corpus", "_case_refs", "_corpus_file_ref")

    def __init__(
        self,
        value: Mapping[str, object],
        *,
        source_path: Path,
        corpus: Mapping[str, object],
        case_refs: list[Mapping[str, object]],
        corpus_file_ref: Mapping[str, object],
    ) -> None:
        super().__init__(deepcopy(dict(value)))
        self._source_path = source_path
        self._corpus = deepcopy(dict(corpus))
        self._case_refs = [deepcopy(dict(item)) for item in case_refs]
        self._corpus_file_ref = deepcopy(dict(corpus_file_ref))


class _ActualScreenGroupService:
    """仅为一次真实屏幕组保存 WorkflowService 的恢复与清理证据。"""

    __slots__ = (
        "_delegate",
        "_group",
        "_binding",
        "_intent_ref",
        "_result_path",
        "_call_root",
        "_cleanup_results",
    )

    def __init__(
        self,
        *,
        delegate: object,
        group: Mapping[str, object],
        binding: Mapping[str, object],
        intent_ref: Mapping[str, object],
        result_path: Path,
    ) -> None:
        self._delegate = delegate
        self._group = deepcopy(dict(group))
        self._binding = deepcopy(dict(binding))
        self._intent_ref = deepcopy(dict(intent_ref))
        self._result_path = Path(result_path)
        self._call_root = self._result_path.parent / "incumbent-calls"
        self._cleanup_results: list[dict[str, Any]] = []

    @property
    def cleanup_results(self) -> list[dict[str, Any]]:
        return deepcopy(self._cleanup_results)

    def start_hybrid_operation(
        self,
        *,
        screen_group: Mapping[str, object],
        window_binding: Mapping[str, object],
    ) -> Mapping[str, object]:
        if dict(screen_group) != self._group or dict(window_binding) != self._binding:
            raise ValueError("benchmark actual service start lineage is stale")
        lookup = getattr(self._delegate, "lookup_hybrid_operation", None)
        if not callable(lookup):
            raise RuntimeError("WorkflowService lookup_hybrid_operation is unavailable")
        recovered = lookup(
            screen_group=deepcopy(self._group),
            window_binding=deepcopy(self._binding),
        )
        recorded = _read_actual_service_result(
            self._result_path,
            intent_ref=self._intent_ref,
            group=self._group,
            binding=self._binding,
        )
        if recovered is None:
            if recorded is not None:
                raise RuntimeError(
                    "benchmark actual service result exists but exact lookup is unavailable"
                )
            start = getattr(self._delegate, "start_hybrid_operation", None)
            if not callable(start):
                raise TypeError("WorkflowService start_hybrid_operation is unavailable")
            recovered = start(
                screen_group=deepcopy(self._group),
                window_binding=deepcopy(self._binding),
            )
        step = validate_benchmark_v2_workflow_service_step(recovered)
        _validate_actual_service_step(step, group=self._group, binding=self._binding)
        if recorded is None:
            result = _sealed_record(
                {
                    "contract_version": _ACTUAL_RESULT_CONTRACT,
                    "intent_ref": deepcopy(self._intent_ref),
                    "provider_group_ref": _actual_group_ref(self._group),
                    "service_step": step,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )
            try:
                _write_create_only_json(self._result_path, result)
            except BaseException as persistence_error:
                try:
                    self.cancel_operation(operation_ref=step["operation_ref"])
                except BaseException as cleanup_error:
                    raise BaseExceptionGroup(
                        "benchmark actual service result persistence and exact cleanup failed",
                        [persistence_error, cleanup_error],
                    )
                persistence_error.add_note(
                    "exact WorkflowService operation was authoritatively cancelled"
                )
                raise
        return step

    def continue_hybrid_operation(
        self, *, operation_ref: Mapping[str, object]
    ) -> Mapping[str, object]:
        return self._call("continue_hybrid_operation", operation_ref=operation_ref)

    def start_incumbent_observe(
        self,
        *,
        provider_case_ref: Mapping[str, object],
        window_binding: Mapping[str, object],
    ) -> Mapping[str, object]:
        if dict(window_binding) != self._binding:
            raise ValueError("benchmark actual incumbent window lineage is stale")
        case_ref = _actual_case_ref(self._group, provider_case_ref)
        return self._incumbent_call(
            call_kind="start",
            provider_case_ref=case_ref,
            operation_ref=None,
            worker_ref=None,
        )

    def poll_incumbent_observe(
        self, *, operation_ref: Mapping[str, object]
    ) -> Mapping[str, object]:
        operation = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
        case_ref = _actual_case_for_operation(self._group, operation)
        return self._incumbent_call(
            call_kind="poll",
            provider_case_ref=case_ref,
            operation_ref=operation,
            worker_ref=None,
        )

    def adopt_and_terminalize_incumbent(
        self,
        *,
        operation_ref: Mapping[str, object],
        worker_ref: Mapping[str, object],
    ) -> Mapping[str, object]:
        operation = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
        case_ref = _actual_case_for_operation(self._group, operation)
        return self._incumbent_call(
            call_kind="adopt",
            provider_case_ref=case_ref,
            operation_ref=operation,
            worker_ref=worker_ref,
        )

    def _incumbent_call(
        self,
        *,
        call_kind: str,
        provider_case_ref: Mapping[str, object],
        operation_ref: Mapping[str, object] | None,
        worker_ref: Mapping[str, object] | None,
    ) -> dict[str, Any]:
        intent = _actual_incumbent_call_intent(
            intent_ref=self._intent_ref,
            group=self._group,
            binding=self._binding,
            call_kind=call_kind,
            provider_case_ref=provider_case_ref,
            operation_ref=operation_ref,
            worker_ref=worker_ref,
        )
        paths = _actual_incumbent_call_paths(self._call_root, intent=intent)
        intent_ref = _write_create_only_json(paths["intent"], intent)
        recorded = _read_actual_incumbent_call_result(
            paths["result"],
            intent_ref=intent_ref,
            provider_case_ref=provider_case_ref,
            binding=self._binding,
        )
        if (
            call_kind == "poll"
            and recorded is not None
            and recorded["service_step"]["operation_ref"]["status"] != "pending"
        ):
            return deepcopy(recorded["service_step"])
        lookup = getattr(self._delegate, "lookup_incumbent_observe", None)
        if not callable(lookup):
            raise RuntimeError("WorkflowService lookup_incumbent_observe is unavailable")

        def mutate(name: str, **kwargs: object) -> Mapping[str, object]:
            try:
                return self._call(name, **kwargs)
            except BaseException as mutation_error:
                recovered_value = lookup(
                    provider_case_ref=deepcopy(dict(provider_case_ref)),
                    window_binding=deepcopy(self._binding),
                )
                if recovered_value is None:
                    raise
                recovered_step = _validate_actual_incumbent_step(
                    recovered_value,
                    provider_case_ref=provider_case_ref,
                    binding=self._binding,
                    expected_operation=operation_ref,
                )
                if (
                    operation_ref is not None
                    and recovered_step["operation_ref"] == operation_ref
                ):
                    raise
                mutation_error.add_note(
                    "lost WorkflowService response recovered by exact incumbent lookup"
                )
                return recovered_step

        current_value = lookup(
            provider_case_ref=deepcopy(dict(provider_case_ref)),
            window_binding=deepcopy(self._binding),
        )
        if current_value is None:
            if call_kind != "start" or recorded is not None:
                raise RuntimeError(
                    "benchmark actual incumbent durable call has no recoverable operation"
                )
            returned = mutate(
                "start_incumbent_observe",
                provider_case_ref=provider_case_ref,
                window_binding=self._binding,
            )
        else:
            current = _validate_actual_incumbent_step(
                current_value,
                provider_case_ref=provider_case_ref,
                binding=self._binding,
                expected_operation=operation_ref,
            )
            if recorded is not None and call_kind != "poll":
                return current
            if call_kind == "start":
                returned = current
            elif current["operation_ref"] != operation_ref:
                if call_kind == "adopt" and _is_actual_incumbent_read_only_advance(
                    current_step=current,
                    advanced_operation=operation_ref,
                ):
                    returned = mutate(
                        "adopt_and_terminalize_incumbent",
                        operation_ref=operation_ref,
                        worker_ref=worker_ref,
                    )
                else:
                    returned = current
            elif call_kind == "poll":
                returned = mutate(
                    "poll_incumbent_observe",
                    operation_ref=operation_ref,
                )
            else:
                returned = mutate(
                    "adopt_and_terminalize_incumbent",
                    operation_ref=operation_ref,
                    worker_ref=worker_ref,
                )
        step = _validate_actual_incumbent_step(
            returned,
            provider_case_ref=provider_case_ref,
            binding=self._binding,
            expected_operation=operation_ref,
        )
        if call_kind == "poll" and (
            recorded is not None
            or step["operation_ref"]["status"] == "pending"
        ):
            return step
        result = _sealed_record(
            {
                "contract_version": _ACTUAL_CALL_RESULT_CONTRACT,
                "intent_ref": intent_ref,
                "service_step": step,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        try:
            _write_create_only_json(paths["result"], result)
        except BaseException as persistence_error:
            try:
                recovered = lookup(
                    provider_case_ref=deepcopy(dict(provider_case_ref)),
                    window_binding=deepcopy(self._binding),
                )
                if recovered is None:
                    raise RuntimeError(
                        "benchmark actual incumbent mutation was not recoverable"
                    )
                recovered_step = _validate_actual_incumbent_step(
                    recovered,
                    provider_case_ref=provider_case_ref,
                    binding=self._binding,
                    expected_operation=operation_ref,
                )
                self.cancel_operation(
                    operation_ref=recovered_step["operation_ref"]
                )
            except BaseException as cleanup_error:
                raise BaseExceptionGroup(
                    "benchmark actual incumbent result persistence and exact cleanup failed",
                    [persistence_error, cleanup_error],
                )
            persistence_error.add_note(
                "exact incumbent operation was recovered by lookup and cancelled"
            )
            raise
        return step

    def cancel_operation(
        self, *, operation_ref: Mapping[str, object]
    ) -> Mapping[str, object]:
        result = self._call("cancel_operation", operation_ref=operation_ref)
        terminal = _validate_service_terminal(result)
        supplied = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
        _validate_actual_terminal_successor(
            terminal=terminal["operation_ref"],
            supplied=supplied,
        )
        looked_up = self._lookup_terminal_cleanup(terminal["operation_ref"])
        if (
            looked_up["operation_ref"] != terminal["operation_ref"]
            or looked_up["status"] != terminal["status"]
            or looked_up["cleanup_refs"] != terminal["cleanup_refs"]
        ):
            raise ValueError(
                "benchmark actual cleanup terminal differs from exact service lookup"
            )
        self._cleanup_results.append(terminal)
        return terminal

    def attest_operations_stable_zero(self) -> dict[str, Any]:
        operation_refs = [
            deepcopy(item["operation_ref"]) for item in self._cleanup_results
        ]
        if len(operation_refs) != 6:
            raise ValueError(
                "benchmark actual service cleanup operation multiset is incomplete"
            )
        attest = getattr(
            self._delegate, "attest_actual_operations_stable_zero", None
        )
        if not callable(attest):
            raise RuntimeError(
                "WorkflowService actual stable-zero attestation is unavailable"
            )
        attestation = validate_benchmark_v2_actual_operations_stable_zero(
            attest(operation_refs=deepcopy(operation_refs))
        )
        if attestation["operation_refs"] != operation_refs:
            raise ValueError(
                "benchmark actual stable-zero attestation operation lineage is stale"
            )
        return attestation

    def _lookup_terminal_cleanup(
        self, operation_ref: Mapping[str, object]
    ) -> dict[str, Any]:
        operation = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
        if operation["mode"] == "hybrid_v1_1":
            lookup = getattr(self._delegate, "lookup_hybrid_operation", None)
            kwargs = {
                "screen_group": deepcopy(self._group),
                "window_binding": deepcopy(self._binding),
            }
        else:
            lookup = getattr(self._delegate, "lookup_incumbent_observe", None)
            matches = [
                item
                for item in self._group["case_refs"]
                if {
                    "id": str(item["case_id"]),
                    "content_sha256": str(item["case_content_sha256"]),
                }
                == operation["request_ref"]
            ]
            if len(matches) != 1:
                raise ValueError(
                    "benchmark actual incumbent cleanup request lineage is stale"
                )
            kwargs = {
                "provider_case_ref": deepcopy(matches[0]),
                "window_binding": deepcopy(self._binding),
            }
        if not callable(lookup):
            raise RuntimeError(
                "WorkflowService exact terminal cleanup lookup is unavailable"
            )
        step = lookup(**kwargs)
        if step is None:
            raise ValueError(
                "benchmark actual cleanup was not confirmed by exact service lookup"
            )
        return validate_benchmark_v2_workflow_service_step(step)

    def _call(self, name: str, **kwargs: object) -> Mapping[str, object]:
        method = getattr(self._delegate, name, None)
        if not callable(method):
            raise TypeError(f"WorkflowService {name} is unavailable")
        return method(**deepcopy(kwargs))


def _is_actual_incumbent_read_only_advance(
    *,
    current_step: Mapping[str, object],
    advanced_operation: Mapping[str, object],
) -> bool:
    """确认 lookup 的 pending 与已记录 advanced 仅有只读状态差异。"""

    if (
        current_step.get("mode") != "incumbent_qwen_only"
        or current_step.get("status") != "pending"
        or advanced_operation.get("mode") != "incumbent_qwen_only"
        or advanced_operation.get("status") != "advanced"
        or current_step.get("adopted_result_projection") is not None
        or current_step.get("terminal_receipt") is not None
        or current_step.get("cleanup_refs")
        != {"worker_cleanup_ref": None, "provider_cleanup_ref": None}
    ):
        return False
    current_operation = current_step.get("operation_ref")
    if not isinstance(current_operation, Mapping):
        return False
    stable_current = {
        name: deepcopy(value)
        for name, value in current_operation.items()
        if name not in {"status", "content_sha256"}
    }
    stable_advanced = {
        name: deepcopy(value)
        for name, value in advanced_operation.items()
        if name not in {"status", "content_sha256"}
    }
    return stable_current == stable_advanced


class _ActualScreenGroupWindowOwner:
    """只记录本次适配器通过运行时关闭的精确窗口回执。"""

    __slots__ = ("_runtime", "_group", "_binding", "_close_ref")

    def __init__(
        self,
        *,
        runtime: "_BenchmarkV2ProductionRuntime",
        group: Mapping[str, object],
        binding: Mapping[str, object],
    ) -> None:
        self._runtime = runtime
        self._group = deepcopy(dict(group))
        self._binding = deepcopy(dict(binding))
        self._close_ref: dict[str, Any] | None = None

    @property
    def close_ref(self) -> dict[str, Any] | None:
        return deepcopy(self._close_ref)

    def open_screen_group(
        self, *, provider_group: Mapping[str, object]
    ) -> Mapping[str, object]:
        if dict(provider_group) != self._group:
            raise ValueError("benchmark actual window group lineage is stale")
        binding = self._runtime.open_screen_group(provider_group=provider_group)
        if dict(binding) != self._binding:
            raise ValueError("benchmark actual opened window lineage is stale")
        return binding

    def close_screen_group(
        self, *, window_binding: Mapping[str, object], reason: str
    ) -> Mapping[str, object]:
        if dict(window_binding) != self._binding:
            raise ValueError("benchmark actual window close lineage is stale")
        close_ref = _sealed_parent(
            self._runtime.close_screen_group(
                window_binding=window_binding,
                reason=reason,
            ),
            name="benchmark actual runtime window close ref",
        )
        if self._close_ref is not None and self._close_ref != close_ref:
            raise ValueError("benchmark actual window close replay differs")
        self._close_ref = close_ref
        return deepcopy(close_ref)


class _ActualScreenGroupLifecycle:
    __slots__ = (
        "_runtime",
        "_attempt",
        "_group",
        "_binding",
        "_service",
        "_window_owner",
        "_stable_ref",
    )

    def __init__(
        self,
        *,
        runtime: "_BenchmarkV2ProductionRuntime",
        attempt: Mapping[str, object],
        group: Mapping[str, object],
        binding: Mapping[str, object],
        service: _ActualScreenGroupService,
        window_owner: _ActualScreenGroupWindowOwner,
    ) -> None:
        self._runtime = runtime
        self._attempt = deepcopy(dict(attempt))
        self._group = deepcopy(dict(group))
        self._binding = deepcopy(dict(binding))
        self._service = service
        self._window_owner = window_owner
        self._stable_ref: dict[str, Any] | None = None

    @property
    def stable_ref(self) -> dict[str, Any] | None:
        return deepcopy(self._stable_ref)

    def stable_zero(
        self,
        *,
        provider_group: Mapping[str, object],
        window_binding: Mapping[str, object],
        execution_refs: list[Mapping[str, object]],
        window_close_ref: Mapping[str, object],
    ) -> Mapping[str, object]:
        if dict(provider_group) != self._group or dict(window_binding) != self._binding:
            raise ValueError("benchmark actual lifecycle group/window lineage is stale")
        close_ref = _sealed_parent(window_close_ref, name="actual window close ref")
        if self._window_owner.close_ref != close_ref:
            raise ValueError(
                "benchmark actual window close was not issued by the exact runtime owner"
            )
        executions = [
            _identity_ref(item, name="actual execution ref") for item in execution_refs
        ]
        if len(executions) != 6 or len({item["id"] for item in executions}) != 6:
            raise ValueError("benchmark actual execution cleanup multiset is incomplete")
        cleanup_results = self._service.cleanup_results
        if len(cleanup_results) != 6:
            raise ValueError("benchmark actual service cleanup evidence is incomplete")
        cleanup_ids = {
            f"{item['operation_ref']['mode']}/{item['operation_ref']['operation_id']}"
            for item in cleanup_results
        }
        if cleanup_ids != {item["id"] for item in executions}:
            raise ValueError("benchmark actual service cleanup lineage is stale")
        service_stable_zero = self._service.attest_operations_stable_zero()
        counts = dict(self._runtime.resource_counts())
        stable = _sealed_record(
            {
                "contract_version": _ACTUAL_LIFECYCLE_CONTRACT,
                "attempt_ref": deepcopy(self._attempt),
                "provider_group_ref": _actual_group_ref(self._group),
                "window_binding_ref": deepcopy(self._binding["window_binding_ref"]),
                "execution_refs": executions,
                "window_close_ref": close_ref,
                "service_stable_zero_attestation": service_stable_zero,
                "diagnostic_resource_counts": counts,
                "cleanup_status": "stable_zero",
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        self._stable_ref = stable
        return stable


class _ActualScreenGroupPredictionSink:
    __slots__ = ("_attempt", "_group", "_lifecycle", "_path", "_projection")

    def __init__(
        self,
        *,
        attempt: Mapping[str, object],
        group: Mapping[str, object],
        lifecycle: _ActualScreenGroupLifecycle,
        path: Path,
    ) -> None:
        self._attempt = deepcopy(dict(attempt))
        self._group = deepcopy(dict(group))
        self._lifecycle = lifecycle
        self._path = Path(path)
        self._projection: dict[str, Any] | None = None

    @property
    def projection(self) -> dict[str, Any] | None:
        return deepcopy(self._projection)

    def write_screen_group(
        self, *, projection: Mapping[str, object]
    ) -> Mapping[str, object]:
        stable = self._lifecycle.stable_ref
        if stable is None:
            raise ValueError("benchmark actual stable-zero evidence is missing before sink")
        current = _validate_actual_projection(
            projection,
            group=self._group,
            lifecycle_ref=stable,
        )
        record = _sealed_record(
            {
                "contract_version": _ACTUAL_PROJECTION_RECORD_CONTRACT,
                "attempt_ref": deepcopy(self._attempt),
                "provider_group_ref": _actual_group_ref(self._group),
                "projection": current,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        _write_create_only_json(self._path, record)
        self._projection = current
        return _content_ref(record, name="actual projection record")


class _BenchmarkV2ProductionRuntime:
    __slots__ = (
        "_project_root",
        "_authority_root",
        "_lock",
        "_active",
        "_pending_cleanup",
        "_preparing",
        "_attempt_states",
        "_monotonic_ns",
        "_wait_hook",
    )

    def __init__(
        self,
        *,
        project_root: Path,
        authority_root: Path,
        monotonic_ns: Callable[[], int] | None = None,
        wait_hook: Callable[[], None] | None = None,
    ) -> None:
        self._project_root = Path(project_root).resolve()
        self._authority_root = Path(authority_root).resolve()
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._wait_hook = wait_hook or self._wait_for_probe_deadline
        if not callable(self._monotonic_ns) or not callable(self._wait_hook):
            raise ValueError("benchmark probe monotonic clock and wait hook must be callable")
        self._lock = RLock()
        self._active: dict[str, Any] | None = None
        self._pending_cleanup: dict[str, object] | None = None
        self._preparing = False
        self._attempt_states: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _wait_for_probe_deadline() -> None:
        time.sleep(_PROBE_POLL_SECONDS)

    def load_provider_manifest(self, *, path: Path) -> Mapping[str, object]:
        manifest_path = _canonical_file(path, name="provider manifest")
        raw = manifest_path.read_bytes()
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("provider manifest is not canonical UTF-8 JSON") from error
        if raw != canonical_json_bytes(decoded, pretty=True):
            raise ValueError("provider manifest bytes are not canonical")
        if not isinstance(decoded, Mapping):
            raise ValueError("provider manifest must be an object")
        manifest = validate_provider_manifest(decoded)
        ref = manifest["provider_corpus_ref"]
        corpus_path = (manifest_path.parent / str(ref["relative_path"])).resolve()
        if corpus_path.parent != manifest_path.parent or not corpus_path.is_file():
            raise ValueError("provider corpus source is missing")
        corpus = load_provider_corpus(
            child_path=corpus_path,
            expected_sha256=str(ref["file_sha256"]),
        )
        if (
            corpus.get("content_sha256") != ref["content_sha256"]
            or corpus.get("source_parent_ref") != ref["source_parent_ref"]
        ):
            raise ValueError("provider manifest and corpus lineage differ")
        resolver = get_production_provider_case_resolver()
        case_refs = provider_case_resolver_case_refs(resolver)
        corpus_file_ref = provider_case_resolver_corpus_file_ref(resolver)
        expected_case_refs = {
            (str(case["case_id"]), content_sha256(case)) for case in corpus["cases"]
        }
        observed_case_refs = {
            (str(case["case_id"]), str(case["case_content_sha256"]))
            for case in case_refs
        }
        if expected_case_refs != observed_case_refs:
            raise ValueError("production provider case resolver differs from corpus")
        resolver_parent_ref = corpus_file_ref.get("source_parent_ref")
        manifest_parent_ref = ref.get("source_parent_ref")
        if (
            corpus_file_ref.get("file_sha256") != ref["file_sha256"]
            or not isinstance(resolver_parent_ref, Mapping)
            or not isinstance(manifest_parent_ref, Mapping)
            or resolver_parent_ref.get("content_sha256")
            != manifest_parent_ref.get("content_sha256")
        ):
            raise ValueError("production provider corpus ref differs from manifest")
        return _LoadedProviderManifest(
            manifest,
            source_path=manifest_path,
            corpus=corpus,
            case_refs=case_refs,
            corpus_file_ref=corpus_file_ref,
        )

    def prepare_screen_groups(
        self,
        *,
        provider_manifest: Mapping[str, object],
        partition: str,
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> BenchmarkV2ScreenGroupIterator:
        loaded = _loaded_manifest(provider_manifest)
        if partition not in {"regression", "holdout"}:
            raise ValueError("benchmark partition is invalid")
        attempt = _sealed_parent(attempt_ref, name="attempt ref")
        directory = Path(attempt_dir)
        if not directory.is_absolute():
            directory = directory.resolve()
        if directory != directory.resolve():
            raise ValueError("benchmark attempt directory must be canonical")
        append_benchmark_v2_attempt_event(
            journal_path=_benchmark_v2_attempt_journal_path(
                project_root=self._project_root,
                attempt_ref=attempt,
            ),
            attempt_ref=attempt,
            phase="prepared",
            event_kind="attempt_prepared",
            resource_ref=_runtime_resource_ref(
                "attempt_directory",
                {"attempt_dir": str(directory)},
            ),
        )
        groups = _partition_groups(loaded, partition=partition)
        owner_token = object()

        def generate() -> Iterator[Mapping[str, object]]:
            for screen_group, cases, case_refs in groups:
                with self._lock:
                    if (
                        self._active is not None
                        or self._pending_cleanup is not None
                        or self._preparing
                    ):
                        raise RuntimeError("benchmark runtime already owns one live screen group")
                    self._preparing = True
                try:
                    prepared = self._prepare_one(
                        loaded=loaded,
                        attempt_ref=attempt,
                        attempt_dir=directory,
                        partition=partition,
                        screen_group=screen_group,
                        cases=cases,
                        case_refs=case_refs,
                        owner_token=owner_token,
                    )
                finally:
                    with self._lock:
                        self._preparing = False
                try:
                    yield deepcopy(prepared["screen_group_start"])
                finally:
                    self._close_active(
                        owner_token=owner_token,
                        reason="benchmark_v2_screen_group_iterator_advanced",
                    )

        return _OwnedScreenGroupIterator(
            generate(),
            cleanup=lambda: self._close_active(
                owner_token=owner_token,
                reason="benchmark_v2_screen_group_iterator_closed"
            ),
        )

    def run_actual_screen_group(
        self,
        *,
        provider_group: Mapping[str, object],
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> Mapping[str, object]:
        group = validate_benchmark_v2_hybrid_screen_group_start(provider_group)
        attempt = _sealed_parent(attempt_ref, name="attempt ref")
        if group["attempt_ref"] != attempt:
            raise ValueError("benchmark actual screen group attempt is stale")
        directory = _canonical_attempt_directory(attempt_dir)
        paths = _actual_screen_group_paths(
            attempt_dir=directory,
            attempt_ref=attempt,
            screen_group=str(group["screen_group"]),
        )
        replay = _read_actual_projection_record(
            paths["projection"],
            attempt=attempt,
            group=group,
        )
        if replay is not None:
            return replay

        with self._lock:
            active = self._active
            if (
                active is None
                or active["screen_group_start"] != group
                or active["attempt_ref"] != attempt
                or active["attempt_dir"] != str(directory)
            ):
                raise ValueError(
                    "benchmark actual screen group is stale or cross-attempt"
                )
            if active.get("actual_running") is True:
                raise RuntimeError("benchmark actual screen group is already running")
            active["actual_running"] = True
            binding = validate_benchmark_v2_workflow_window_binding(
                active["workflow_window_binding"]
            )

        try:
            intent = _sealed_record(
                {
                    "contract_version": _ACTUAL_INTENT_CONTRACT,
                    "attempt_ref": attempt,
                    "provider_group": group,
                    "window_binding": binding,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )
            intent_ref = _write_create_only_json(paths["intent"], intent)
            delegate = get_production_benchmark_v2_workflow_service()
            service = _ActualScreenGroupService(
                delegate=delegate,
                group=group,
                binding=binding,
                intent_ref=intent_ref,
                result_path=paths["result"],
            )
            window_owner = _ActualScreenGroupWindowOwner(
                runtime=self,
                group=group,
                binding=binding,
            )
            lifecycle = _ActualScreenGroupLifecycle(
                runtime=self,
                attempt=attempt,
                group=group,
                binding=binding,
                service=service,
                window_owner=window_owner,
            )
            sink = _ActualScreenGroupPredictionSink(
                attempt=attempt,
                group=group,
                lifecycle=lifecycle,
                path=paths["projection"],
            )
            returned = benchmark_v2_actual.run_screen_group(
                provider_group=deepcopy(group),
                service=service,
                window_owner=window_owner,
                lifecycle=lifecycle,
                prediction_sink=sink,
            )
            stable = lifecycle.stable_ref
            persisted = sink.projection
            if stable is None or persisted is None:
                raise RuntimeError(
                    "benchmark actual adapter returned without cleanup/prediction evidence"
                )
            projection = _validate_actual_projection(
                returned,
                group=group,
                lifecycle_ref=stable,
            )
            if projection != persisted:
                raise ValueError(
                    "benchmark actual adapter returned a different-content projection"
                )
            replay = _read_actual_projection_record(
                paths["projection"],
                attempt=attempt,
                group=group,
            )
            if replay != projection:
                raise ValueError("benchmark actual durable projection replay differs")
            return projection
        finally:
            with self._lock:
                if self._active is active:
                    active.pop("actual_running", None)

    def open_screen_group(
        self, *, provider_group: Mapping[str, object]
    ) -> Mapping[str, object]:
        with self._lock:
            active = self._active
            if (
                active is None
                or provider_group.get("content_sha256")
                != active["screen_group_start"]["content_sha256"]
            ):
                raise ValueError("benchmark screen group is not the current owned group")
            return deepcopy(active["workflow_window_binding"])

    def close_screen_group(
        self, *, window_binding: Mapping[str, object], reason: str
    ) -> Mapping[str, object]:
        with self._lock:
            active = self._active
            if (
                active is None
                or window_binding.get("content_sha256")
                != active["workflow_window_binding"]["content_sha256"]
            ):
                raise ValueError("benchmark window binding is not the current owned group")
            owner_token = active["owner_token"]
        return self._close_active(owner_token=owner_token, reason=reason)

    def begin_probe(
        self,
        *,
        provider_id: str,
        probe_kind: str,
        provider_manifest: Mapping[str, object],
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
    ) -> Mapping[str, object]:
        provider = _probe_provider(provider_id)
        kind = _probe_kind(probe_kind)
        attempt = _sealed_parent(attempt_ref, name="attempt ref")
        if attempt.get("partition") == "holdout":
            raise ValueError("benchmark lifecycle probes are forbidden for holdout")
        attempt_key = str(attempt["content_sha256"])
        with self._lock:
            if attempt_key in self._attempt_states:
                existing = self._attempt_states[attempt_key].get("probe_context")
                if isinstance(existing, Mapping):
                    context = _validate_probe_context(existing)
                    if (
                        context["provider_id"] == provider
                        and context["probe_kind"] == kind
                    ):
                        return context
                raise RuntimeError("benchmark attempt already owns a different probe")

        iterator = self.prepare_screen_groups(
            provider_manifest=provider_manifest,
            partition="regression",
            attempt_ref=attempt,
            attempt_dir=attempt_dir,
        )
        service = get_production_benchmark_v2_workflow_service()
        state: dict[str, Any] | None = None
        try:
            screen_group = next(iterator)
            binding = self.open_screen_group(provider_group=screen_group)
            state = {
                "attempt_ref": attempt,
                "iterator": iterator,
                "service": service,
                "latest_operation_ref": None,
                "screen_group": deepcopy(dict(screen_group)),
                "window_binding": deepcopy(dict(binding)),
                "probe_context": None,
                "provider_id": provider,
                "probe_kind": kind,
                "request_in_flight": None,
                "service_terminal": None,
                "window_cleanup": None,
            }
            with self._lock:
                if attempt_key in self._attempt_states:
                    raise RuntimeError("benchmark attempt probe was started concurrently")
                self._attempt_states[attempt_key] = state
            append_benchmark_v2_attempt_event(
                journal_path=_benchmark_v2_attempt_journal_path(
                    project_root=self._project_root,
                    attempt_ref=attempt,
                ),
                attempt_ref=attempt,
                phase="prepared",
                event_kind="service_start_intent",
                resource_ref=_runtime_resource_ref(
                    "workflow_service_start_intent",
                    {
                        "screen_group": deepcopy(dict(screen_group)),
                        "window_binding": deepcopy(dict(binding)),
                    },
                ),
            )
            step = service.start_hybrid_operation(
                screen_group=deepcopy(dict(screen_group)),
                window_binding=deepcopy(dict(binding)),
            )
            operation = _service_operation_from_step(step, name="probe start")
            _validate_probe_operation_lineage(
                operation=operation,
                binding=binding,
                request_ref=screen_group["request_ref"],
            )
            state["latest_operation_ref"] = operation
            target_task = _PROBE_TARGET_TASKS[provider]
            deadline = time.monotonic() + _PROBE_DEADLINE_SECONDS
            continues = 0
            while step.get("observed_task_kind") != target_task:
                if step.get("status") in {
                    "complete",
                    "cancelled",
                    "safe_stopped",
                    "failed",
                }:
                    raise RuntimeError(
                        "benchmark probe target was not reached before terminal state"
                    )
                if continues >= _PROBE_MAX_CONTINUES:
                    raise TimeoutError("benchmark probe cascade exceeded its step bound")
                if time.monotonic() >= deadline:
                    raise TimeoutError("benchmark probe cascade exceeded its deadline")
                previous = operation
                state["continuation_in_flight"] = deepcopy(previous)
                step = service.continue_hybrid_operation(operation_ref=previous)
                operation = _service_operation_from_step(
                    step,
                    name="probe continuation",
                    predecessor=previous,
                )
                _validate_probe_operation_lineage(
                    operation=operation,
                    binding=binding,
                    request_ref=screen_group["request_ref"],
                )
                state["latest_operation_ref"] = operation
                state["continuation_in_flight"] = None
                continues += 1
                if operation["content_sha256"] == previous["content_sha256"]:
                    time.sleep(_PROBE_POLL_SECONDS)

            context_projection = _provider_context_projection_from_step(
                step=step,
                provider=provider,
                service_operation=operation,
            )

            screen_group_ref = {
                "id": str(screen_group["screen_group"]),
                "content_sha256": str(screen_group["content_sha256"]),
            }
            service_resource = _service_operation_resource(
                operation=operation,
                binding=binding,
                screen_group=screen_group,
            )
            service_event = append_benchmark_v2_attempt_event(
                journal_path=_benchmark_v2_attempt_journal_path(
                    project_root=self._project_root,
                    attempt_ref=attempt,
                ),
                attempt_ref=attempt,
                phase="prepared",
                event_kind="service_started",
                resource_ref=service_resource,
            )
            context_body: dict[str, Any] = {
                "contract_version": _PROBE_CONTEXT_CONTRACT,
                "attempt_ref": attempt,
                "provider_id": provider,
                "probe_kind": kind,
                "operation_ref": operation,
                "provider_dispatch_context_projection": context_projection,
                "window_binding_ref": deepcopy(operation["window_binding_ref"]),
                "capture_ref": deepcopy(operation["capture_ref"]),
                "screen_group_ref": screen_group_ref,
                "service_event_ref": _event_ref(service_event),
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
            context_body["content_sha256"] = content_sha256(context_body)
            context = _validate_probe_context(context_body)
            state["probe_context"] = context
            return deepcopy(context)
        except BaseException as primary:
            try:
                if state is not None:
                    self.cleanup_attempt(
                        attempt=attempt,
                        reason="benchmark_probe_start_failed",
                    )
                else:
                    iterator.close()
            except BaseException as cleanup:
                raise BaseExceptionGroup(
                    "benchmark probe start and cleanup failed", [primary, cleanup]
                )
            raise

    def read_server_journal(
        self, *, probe_context: Mapping[str, object]
    ) -> Mapping[str, object]:
        context = _validate_probe_context(probe_context)
        state = self._probe_state(context)
        existing = state.get("request_in_flight")
        if isinstance(existing, Mapping):
            return _validate_probe_request(existing)
        operation = validate_benchmark_v2_workflow_service_operation_ref(
            state["latest_operation_ref"]
        )
        context_projection = validate_benchmark_v2_provider_dispatch_context_projection(
            context["provider_dispatch_context_projection"]
        )
        deadline = time.monotonic() + _PROBE_DEADLINE_SECONDS
        receipt: dict[str, Any] | None = None
        while receipt is None:
            evidence = _read_committed_probe_dispatch_evidence(
                project_root=self._project_root,
                provider=context["provider_id"],
                context_projection=context_projection,
            )
            if evidence is not None:
                receipt = evidence["receipt"]
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("benchmark provider request journal was not observed")
            time.sleep(_PROBE_POLL_SECONDS)
        request_resource = _runtime_resource_ref(
            "provider_request_in_flight",
            {
                "operation_ref": operation,
                "provider_dispatch_context_projection": context_projection,
                "dispatch_receipt": receipt,
            },
        )
        event = append_benchmark_v2_attempt_event(
            journal_path=_benchmark_v2_attempt_journal_path(
                project_root=self._project_root,
                attempt_ref=context["attempt_ref"],
            ),
            attempt_ref=context["attempt_ref"],
            phase="request_in_flight",
            event_kind="provider_request_in_flight",
            provider_id=str(context["provider_id"]),
            probe_kind=str(context["probe_kind"]),
            resource_ref=request_resource,
        )
        body: dict[str, Any] = {
            "contract_version": _PROBE_REQUEST_CONTRACT,
            "attempt_ref": deepcopy(context["attempt_ref"]),
            "provider_id": context["provider_id"],
            "probe_kind": context["probe_kind"],
            "operation_ref": operation,
            "provider_dispatch_context_projection": context_projection,
            "request_state": "request_in_flight",
            "dispatch_receipt_ref": _content_ref(receipt, name="dispatch receipt"),
            "provider_runtime_attestation_ref": deepcopy(
                receipt["provider_runtime_attestation_ref"]
            ),
            "attempt_event_ref": _event_ref(event),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        body["content_sha256"] = content_sha256(body)
        request = _validate_probe_request(body)
        state["request_in_flight"] = request
        return deepcopy(request)

    def trigger_probe(
        self,
        *,
        probe_context: Mapping[str, object],
        probe_kind: str,
        request_in_flight_journal: Mapping[str, object],
    ) -> Mapping[str, object]:
        context = _validate_probe_context(probe_context)
        kind = _probe_kind(probe_kind)
        if kind != context["probe_kind"]:
            raise ValueError("benchmark probe kind differs from its prepared context")
        request = _validate_probe_request(request_in_flight_journal)
        if (
            request["attempt_ref"] != context["attempt_ref"]
            or request["provider_id"] != context["provider_id"]
            or request["probe_kind"] != context["probe_kind"]
            or request["operation_ref"] != context["operation_ref"]
            or request["provider_dispatch_context_projection"]
            != context["provider_dispatch_context_projection"]
        ):
            raise ValueError("benchmark probe request lineage is stale")
        state = self._probe_state(context)
        if state.get("request_in_flight") != request:
            raise ValueError("benchmark probe request was not observed by this runtime")
        journal_path = _benchmark_v2_attempt_journal_path(
            project_root=self._project_root, attempt_ref=context["attempt_ref"]
        )
        events = read_benchmark_v2_attempt_journal(
            journal_path=journal_path, attempt_ref=context["attempt_ref"]
        )
        persisted = _probe_trigger_from_terminal_events(
            events,
            provider_id=context["provider_id"],
            probe_kind=context["probe_kind"],
        )
        if persisted is not None:
            state["trigger_receipt"] = deepcopy(persisted)
            return persisted
        trigger_observation = _probe_trigger_observation_from_events(
            events,
            provider_id=context["provider_id"],
            probe_kind=context["probe_kind"],
            required=False,
        )
        existing_intent = _probe_trigger_intent_from_events(
            events,
            provider_id=context["provider_id"],
            probe_kind=context["probe_kind"],
        )
        if existing_intent is not None:
            if trigger_observation is None:
                raise ValueError(
                    "benchmark probe trigger observation is unavailable for prior intent"
                )
            _validate_probe_trigger_observation_lineage(
                material=trigger_observation,
                context=context,
                request=request,
            )
            recovered_context = _probe_context_from_events(
                events, trigger_intent=existing_intent, request=request
            )
            recovered_terminal = _safe_stopped_terminal_from_lookup(
                events=events,
                service=state["service"],
                context=recovered_context,
                request=request,
            )
            if recovered_terminal is None:
                raise ValueError("benchmark probe retry remains pending after prior trigger intent")
            intent_event = _one_probe_event_for_tuple(
                events,
                event_kind="probe_trigger_intent",
                provider_id=context["provider_id"],
                probe_kind=context["probe_kind"],
                required=True,
            )
            assert intent_event is not None
            _persist_recovered_probe_terminal(
                journal_path=journal_path,
                context=recovered_context,
                request=request,
                trigger_intent_event=intent_event,
                service_terminal=recovered_terminal,
            )
            state["service_terminal"] = recovered_terminal
            rebuilt = _probe_trigger_from_terminal_events(
                read_benchmark_v2_attempt_journal(
                    journal_path=journal_path, attempt_ref=context["attempt_ref"]
                ),
                provider_id=context["provider_id"],
                probe_kind=context["probe_kind"],
            )
            if rebuilt is None:
                raise ValueError("benchmark probe retry terminal rebuild is unavailable")
            state["trigger_receipt"] = deepcopy(rebuilt)
            return rebuilt
        if trigger_observation is None:
            trigger_observation = _compose_probe_trigger_observation(
                context=context,
                request=request,
                monotonic_ns=self._monotonic_ns,
                wait_hook=self._wait_hook,
            )
            append_benchmark_v2_attempt_event(
                journal_path=journal_path,
                attempt_ref=context["attempt_ref"],
                phase="request_in_flight",
                event_kind="probe_trigger_observation",
                provider_id=str(context["provider_id"]),
                probe_kind=kind,
                resource_ref=_runtime_resource_ref(
                    "probe_trigger_observation",
                    {
                        "trigger_observation": trigger_observation[
                            "trigger_observation"
                        ],
                        "deadline_expiration": trigger_observation[
                            "deadline_expiration"
                        ],
                    },
                ),
            )
        else:
            _validate_probe_trigger_observation_lineage(
                material=trigger_observation,
                context=context,
                request=request,
            )
        trigger_intent = _compose_probe_trigger_intent(
            project_root=self._project_root,
            context=context,
            request=request,
        )
        intent_event = append_benchmark_v2_attempt_event(
            journal_path=_benchmark_v2_attempt_journal_path(
                project_root=self._project_root,
                attempt_ref=context["attempt_ref"],
            ),
            attempt_ref=context["attempt_ref"],
            phase="request_in_flight",
            event_kind="probe_trigger_intent",
            provider_id=str(context["provider_id"]),
            probe_kind=kind,
            resource_ref=_runtime_resource_ref(
                "probe_trigger_intent",
                {"trigger_intent": trigger_intent},
            ),
        )
        service_terminal = state.get("service_terminal")
        if not isinstance(service_terminal, Mapping):
            service_terminal = state["service"].cancel_operation(
                operation_ref=deepcopy(state["latest_operation_ref"])
            )
            service_terminal = _validate_service_terminal(
                service_terminal,
                expected_operation=context["operation_ref"],
                expected_context_projection=context[
                    "provider_dispatch_context_projection"
                ],
                expected_request=request,
                require_safe_stop=True,
            )
            state["service_terminal"] = service_terminal
        cleanup_binding = _probe_cleanup_binding(
            context=context,
            request=request,
            service_terminal=service_terminal,
        )
        event = append_benchmark_v2_attempt_event(
            journal_path=_benchmark_v2_attempt_journal_path(
                project_root=self._project_root,
                attempt_ref=context["attempt_ref"],
            ),
            attempt_ref=context["attempt_ref"],
            phase="request_in_flight",
            event_kind="probe_triggered",
            provider_id=str(context["provider_id"]),
            probe_kind=kind,
            resource_ref=_runtime_resource_ref(
                "probe_trigger",
                {
                    "request_ref": _content_ref(request, name="probe request"),
                    "service_terminal": service_terminal,
                    "cleanup_binding_ref": cleanup_binding,
                },
            ),
        )
        absence_observations = _live_absence_observations(
            trigger_intent["process_identities"]
        )
        terminal_body: dict[str, Any] = {
            "contract_version": _PROBE_TRIGGER_TERMINAL_CONTRACT,
            "trigger_intent_ref": _event_ref(intent_event),
            "service_terminal_ref": _content_ref(service_terminal, name="workflow service terminal result"),
            "cleanup_binding_ref": cleanup_binding,
            "absence_observations": _persisted_probe_absence_observations(absence_observations),
            "outcome": "safe_stopped_exact_incarnation_absent",
            "evidence_scope": "benchmark_probe_only_non_authorizing",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        terminal_body["content_sha256"] = content_sha256(terminal_body)
        terminal = _sealed_parent(terminal_body, name="probe trigger terminal")
        terminal_event = append_benchmark_v2_attempt_event(
            journal_path=_benchmark_v2_attempt_journal_path(
                project_root=self._project_root,
                attempt_ref=context["attempt_ref"],
            ),
            attempt_ref=context["attempt_ref"],
            phase="body_complete",
            event_kind="probe_trigger_terminal",
            provider_id=str(context["provider_id"]),
            probe_kind=kind,
            resource_ref=_runtime_resource_ref(
                "probe_trigger_terminal", {"probe_trigger_terminal": terminal}
            ),
        )
        body: dict[str, Any] = {
            "contract_version": _PROBE_TRIGGER_CONTRACT,
            "attempt_ref": deepcopy(context["attempt_ref"]),
            "provider_id": context["provider_id"],
            "probe_kind": kind,
            "request_in_flight_ref": _content_ref(request, name="probe request"),
            "trigger_intent_ref": _event_ref(intent_event),
            "service_terminal_ref": _content_ref(service_terminal, name="workflow service terminal result"),
            "cleanup_binding_ref": cleanup_binding,
            "probe_trigger_terminal_ref": _event_ref(terminal_event),
            "absence_observations": absence_observations,
            "attempt_event_ref": _event_ref(event),
            "outcome": "safe_stopped_exact_incarnation_absent",
            "evidence_scope": "benchmark_probe_only_non_authorizing",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        body["content_sha256"] = content_sha256(body)
        trigger = _validate_probe_trigger(body)
        state["trigger_receipt"] = deepcopy(trigger)
        return trigger

    def finalize_probe_lifecycle_receipt(
        self,
        *,
        provider_manifest: Mapping[str, object],
        attempt_ref: Mapping[str, object],
        cleanup_receipt: Mapping[str, object],
    ) -> Mapping[str, object]:
        loaded = _loaded_manifest(provider_manifest)
        attempt = _sealed_parent(attempt_ref, name="probe receipt attempt ref")
        journal_path = _benchmark_v2_attempt_journal_path(
            project_root=self._project_root,
            attempt_ref=attempt,
        )
        events = read_benchmark_v2_attempt_journal(
            journal_path=journal_path,
            attempt_ref=attempt,
        )
        durable_cleanup = _cleanup_receipt_from_terminal(events)
        cleanup = _sealed_parent(cleanup_receipt, name="probe receipt cleanup")
        if durable_cleanup is None or cleanup != durable_cleanup:
            raise ValueError("benchmark probe cleanup differs from terminal journal")
        if (
            cleanup.get("attempt_ref") != attempt
            or cleanup.get("cleanup_status") != "stable_zero"
            or cleanup.get("resource_counts")
            != {
                "service_operations": 0,
                "windows": 0,
                "providers": 0,
                "listeners": 0,
                "leases": 0,
            }
            or cleanup.get("artifact_is_authorization") is not False
            or cleanup.get("execute_binding_enabled") is not False
        ):
            raise ValueError("benchmark probe cleanup receipt is invalid")
        tuples = _probe_terminal_tuples(events)
        if len(tuples) != 1:
            raise ValueError("benchmark probe terminal tuple is unavailable or ambiguous")
        provider_id, probe_kind = tuples[0]
        material = _probe_terminal_material(
            events,
            provider_id=provider_id,
            probe_kind=probe_kind,
        )
        if material is None:
            raise ValueError("benchmark probe terminal material is unavailable")
        context = material["context"]
        request = material["request"]
        trigger_material = material["trigger_observation"]
        trigger_observation = deepcopy(trigger_material["trigger_observation"])
        dispatch = _read_committed_probe_dispatch_evidence(
            project_root=self._project_root,
            provider=provider_id,
            context_projection=context["provider_dispatch_context_projection"],
            expected_dispatch_receipt_ref=request["dispatch_receipt_ref"],
            expected_runtime_identity_ref=request["provider_runtime_attestation_ref"],
        )
        if dispatch is None:
            raise ValueError("benchmark probe committed dispatch parent is unavailable")
        dispatch_parent = dispatch["runtime_parent"]
        process_identities = _exact_ordered_process_identities(dispatch_parent)
        if process_identities != material["intent"]["process_identities"]:
            raise ValueError("benchmark probe trigger and dispatch process identities differ")
        _live_absence_observations(process_identities)
        zero_counts = {
            "service_operations": 0,
            "windows": 0,
            "providers": 0,
            "listeners": 0,
            "leases": 0,
        }
        attempt_dir = _actual_attempt_directory_from_events(events)
        if attempt_dir is None:
            raise ValueError("benchmark probe attempt directory is unavailable")
        stable_path = (attempt_dir / "probe-stable-zero-evidence.json").resolve()
        receipt_path = (attempt_dir / "lifecycle-probe-receipt.json").resolve()
        if stable_path.parent != attempt_dir or receipt_path.parent != attempt_dir:
            raise ValueError("benchmark probe receipt path escapes attempt directory")
        if stable_path.exists() != receipt_path.exists():
            raise ValueError(
                "benchmark probe stable-zero parent is orphaned from its receipt"
            )
        terminal_evidence = _event_ref(material["terminal_event"])
        triggered_ns = _monotonic_clock_value(
            trigger_observation["triggered_monotonic_ns"]
        )
        if stable_path.exists():
            stable_zero = _read_canonical_json(
                stable_path, name="benchmark probe stable-zero evidence"
            )
            stable_zero = validate_benchmark_v2_probe_stable_zero_evidence_v1(
                stable_zero,
                attempt_ref=attempt,
                cleanup_receipt=cleanup,
            )
            body_observation = deepcopy(
                stable_zero["body_completion_observation"]
            )
            fresh_after = max(
                triggered_ns,
                stable_zero["samples"][-1]["observed_monotonic_ns"],
            )
            _collect_probe_runtime_zero_samples(
                monotonic_ns=self._monotonic_ns,
                wait_hook=self._wait_hook,
                resource_counts=self.resource_counts,
                after=fresh_after,
                expected_counts=zero_counts,
            )
        else:
            if receipt_path.exists():
                raise ValueError("benchmark probe receipt lost its stable-zero parent")
            body_observed = _next_probe_monotonic_observation(
                monotonic_ns=self._monotonic_ns,
                wait_hook=self._wait_hook,
                after=triggered_ns,
            )
            body_observation = {
                "state": "not_complete",
                "observed_monotonic_ns": body_observed,
                "evidence_ref": terminal_evidence,
            }
            samples = _collect_probe_runtime_zero_samples(
                monotonic_ns=self._monotonic_ns,
                wait_hook=self._wait_hook,
                resource_counts=self.resource_counts,
                after=body_observed,
                expected_counts=zero_counts,
            )
            stable_zero = compose_benchmark_v2_probe_stable_zero_evidence_v1(
                attempt_ref=attempt,
                cleanup_receipt=cleanup,
                body_completion_observation=body_observation,
                samples=samples,
            )
            _write_create_only_json(stable_path, stable_zero)
        if body_observation["observed_monotonic_ns"] <= triggered_ns:
            raise ValueError("benchmark probe body observation did not follow trigger")
        provider_policy = loaded.get("evaluation_projection")
        if not isinstance(provider_policy, Mapping):
            raise ValueError("benchmark provider evaluation projection is unavailable")
        policy = provider_policy.get("provider_policy")
        revisions = policy.get("provider_revisions") if isinstance(policy, Mapping) else None
        if not isinstance(revisions, Mapping):
            raise ValueError("benchmark provider revisions are unavailable")
        provider_revision = revisions.get(provider_id)
        if not isinstance(provider_revision, str) or not provider_revision:
            raise ValueError("benchmark provider revision is unavailable")
        profile = dispatch_parent.get("profile")
        if not isinstance(profile, Mapping):
            raise ValueError("benchmark dispatch runtime profile is unavailable")
        receipt = compose_benchmark_v2_lifecycle_probe_receipt_v2(
            provider_manifest=loaded,
            attempt_ref=attempt,
            provider={
                "provider_id": provider_id,
                "provider_revision": provider_revision,
                "profile_id": profile["profile_id"],
                "profile_sha256": profile["profile_sha256"],
            },
            probe_kind=probe_kind,
            operation_ref=context["operation_ref"],
            request_in_flight_ref=request,
            trigger_observation=trigger_observation,
            body_completion_observation=body_observation,
            termination_observation={
                "outcome": "same_incarnations_exited",
                "process_identities": process_identities,
                "evidence_ref": terminal_evidence,
            },
            stable_zero_evidence=stable_zero,
            cleanup_receipt=cleanup,
            dispatch_runtime_parent=dispatch_parent,
            deadline_expiration=trigger_material["deadline_expiration"],
            probe_trigger_terminal_event=terminal_evidence,
        )
        if receipt_path.exists():
            existing = _read_canonical_json(
                receipt_path, name="benchmark lifecycle probe receipt v2"
            )
            if existing != receipt:
                raise ValueError(
                    "benchmark lifecycle probe receipt has different existing bytes"
                )
            return validate_benchmark_v2_lifecycle_probe_receipt_v2(
                existing,
                stable_zero_evidence=stable_zero,
                cleanup_receipt=cleanup,
                dispatch_runtime_parent=dispatch_parent,
                deadline_expiration=trigger_material["deadline_expiration"],
                probe_trigger_terminal_event=terminal_evidence,
                provider_manifest=loaded,
            )
        _write_create_only_json(receipt_path, receipt)
        return receipt

    def cleanup_attempt(
        self, *, attempt: Mapping[str, object], reason: str
    ) -> Mapping[str, object]:
        attempt_ref = _sealed_parent(attempt, name="attempt ref")
        normalized_reason = str(reason or "").strip()
        if not normalized_reason:
            raise ValueError("benchmark cleanup reason is invalid")
        journal_path = _benchmark_v2_attempt_journal_path(
            project_root=self._project_root,
            attempt_ref=attempt_ref,
        )
        events = read_benchmark_v2_attempt_journal(
            journal_path=journal_path,
            attempt_ref=attempt_ref,
        )
        # 终态 receipt 的 replay 必须先完整重建并校验 durable probe terminal。
        completed_probe_terminals: list[Mapping[str, object]] = []
        for provider_id, probe_kind in _probe_terminal_tuples(events):
            _probe_trigger_from_terminal_events(
                events, provider_id=provider_id, probe_kind=probe_kind
            )
            material = _probe_terminal_material(
                events, provider_id=provider_id, probe_kind=probe_kind
            )
            assert material is not None
            completed_probe_terminals.append(material["service_terminal"])
        if len(completed_probe_terminals) > 1:
            raise ValueError("benchmark completed probe service terminal is ambiguous")
        terminal = _cleanup_receipt_from_terminal(events)
        if terminal is not None:
            with self._lock:
                self._attempt_states.pop(str(attempt_ref["content_sha256"]), None)
            return terminal
        prepared_cleanup = _prepared_cleanup_receipt_from_events(events)
        if prepared_cleanup is not None:
            append_benchmark_v2_attempt_event(
                journal_path=journal_path,
                attempt_ref=attempt_ref,
                phase="terminal",
                event_kind="attempt_terminal",
                resource_ref=_runtime_resource_ref(
                    "attempt_cleanup_receipt",
                    {"cleanup_receipt": prepared_cleanup},
                ),
            )
            with self._lock:
                self._attempt_states.pop(str(attempt_ref["content_sha256"]), None)
            return prepared_cleanup
        attempt_key = str(attempt_ref["content_sha256"])
        with self._lock:
            state = self._attempt_states.get(attempt_key)

        service_terminal: Mapping[str, object] | None = (
            completed_probe_terminals[0] if completed_probe_terminals else None
        )
        window_cleanup: Mapping[str, object] | None = None
        cleanup_errors: list[BaseException] = []
        actual_attestations: list[Mapping[str, object]] = []
        actual_pre_reservation_recoveries: list[Mapping[str, object]] = []
        actual_completed_hybrid_cleanups: list[Mapping[str, object]] = []
        actual_terminals: list[Mapping[str, object]] = []
        partial_actual_terminals: list[Mapping[str, object]] = []
        unresolved_actual_operations = 0
        durable_service_operation = _service_operation_from_events(events)
        actual_directory = _actual_attempt_directory_from_events(events)
        if actual_directory is not None:
            try:
                actual_intents = _read_actual_screen_group_service_intents(
                    attempt_dir=actual_directory
                )
                if actual_intents:
                    (
                        actual_terminals,
                        actual_attestations,
                        actual_pre_reservation_recoveries,
                        actual_completed_hybrid_cleanups,
                        partial_actual_terminals,
                        unresolved_actual_operations,
                    ) = _reconcile_actual_operations(
                        attempt_dir=actual_directory,
                        service=get_production_benchmark_v2_workflow_service(),
                    )
                    if actual_terminals:
                        service_terminal = actual_terminals[-1]
            except BaseException as error:
                cleanup_errors.append(error)
        if isinstance(state, dict):
            try:
                active_tuple = _probe_tuple(state["provider_id"], state["probe_kind"])
                trigger_intent = _probe_trigger_intent_from_events(
                    events, provider_id=active_tuple[0], probe_kind=active_tuple[1]
                )
                request = _probe_request_from_events(
                    events, provider_id=active_tuple[0], probe_kind=active_tuple[1]
                )
                if trigger_intent is not None:
                    if request is None:
                        raise ValueError(
                            "benchmark probe request is unavailable for prior trigger intent"
                        )
                    observation_context = state.get("probe_context")
                    if not isinstance(observation_context, Mapping):
                        observation_context = _probe_context_from_events(
                            events, trigger_intent=trigger_intent, request=request
                        )
                    trigger_observation = _probe_trigger_observation_from_events(
                        events,
                        provider_id=active_tuple[0],
                        probe_kind=active_tuple[1],
                        required=True,
                    )
                    assert trigger_observation is not None
                    _validate_probe_trigger_observation_lineage(
                        material=trigger_observation,
                        context=observation_context,
                        request=request,
                    )
                service_terminal = state.get("service_terminal")
                if not isinstance(service_terminal, Mapping):
                    operation = state.get("latest_operation_ref")
                    if not isinstance(operation, Mapping):
                        operation = _lookup_service_operation_from_intent(
                            events=events,
                            service=state["service"],
                        )
                        if isinstance(operation, Mapping):
                            state["latest_operation_ref"] = operation
                    if (
                        isinstance(operation, Mapping)
                        and durable_service_operation is None
                    ):
                        durable_service_operation = _append_service_recovered_event(
                            journal_path=journal_path,
                            attempt_ref=attempt_ref,
                            operation=operation,
                            binding=state["window_binding"],
                            screen_group=state["screen_group"],
                        )
                    if isinstance(operation, Mapping):
                        if trigger_intent is not None and request is not None:
                            recovered_context = _probe_context_from_events(
                                events, trigger_intent=trigger_intent, request=request
                            )
                            service_terminal = _safe_stopped_terminal_from_lookup(
                                events=events,
                                service=state["service"],
                                context=recovered_context,
                                request=request,
                            )
                        if service_terminal is not None:
                            state["service_terminal"] = service_terminal
                        else:
                            if trigger_intent is not None:
                                if operation != trigger_intent["operation_ref"]:
                                    raise ValueError(
                                        "benchmark probe pending recovery operation is stale"
                                    )
                                _observe_exact_process_identities_before_cancel(
                                    trigger_intent["process_identities"]
                                )
                        try:
                            if service_terminal is None:
                                service_terminal = state["service"].cancel_operation(
                                    operation_ref=deepcopy(dict(operation))
                                )
                        except ValueError:
                            consumed = state.get("continuation_in_flight")
                            if not isinstance(consumed, Mapping) or consumed != operation:
                                raise
                            recovered_step = state["service"].continue_hybrid_operation(
                                operation_ref=deepcopy(dict(consumed))
                            )
                            recovered_operation = _service_operation_from_step(
                                recovered_step,
                                name="lost-response continuation reconciliation",
                                predecessor=consumed,
                            )
                            state["latest_operation_ref"] = recovered_operation
                            state["continuation_in_flight"] = None
                            durable_service_operation = _append_service_recovered_event(
                                journal_path=journal_path,
                                attempt_ref=attempt_ref,
                                operation=recovered_operation,
                                binding=state["window_binding"],
                                screen_group=state["screen_group"],
                            )
                            service_terminal = state["service"].cancel_operation(
                                operation_ref=recovered_operation
                            )
                        service_terminal = _validate_service_terminal(service_terminal)
                        state["service_terminal"] = service_terminal
                if (
                    isinstance(service_terminal, Mapping)
                    and trigger_intent is not None
                    and request is not None
                    and _one_probe_event_for_tuple(
                        events,
                        event_kind="probe_trigger_terminal",
                        provider_id=active_tuple[0],
                        probe_kind=active_tuple[1],
                        required=False,
                    )
                    is None
                ):
                    recovered_context = _probe_context_from_events(
                        events, trigger_intent=trigger_intent, request=request
                    )
                    intent_event = _one_probe_event_for_tuple(
                        events,
                        event_kind="probe_trigger_intent",
                        provider_id=active_tuple[0],
                        probe_kind=active_tuple[1],
                        required=True,
                    )
                    assert intent_event is not None
                    service_terminal = _persist_recovered_probe_terminal(
                        journal_path=journal_path,
                        context=recovered_context,
                        request=request,
                        trigger_intent_event=intent_event,
                        service_terminal=service_terminal,
                    )
                    state["service_terminal"] = service_terminal
                    events = read_benchmark_v2_attempt_journal(
                        journal_path=journal_path,
                        attempt_ref=attempt_ref,
                    )
            except BaseException as error:
                cleanup_errors.append(error)
            try:
                window_cleanup = state.get("window_cleanup")
                if not isinstance(window_cleanup, Mapping):
                    window_cleanup = self._close_probe_window(
                        state=state,
                        reason=normalized_reason,
                    )
                    state["window_cleanup"] = window_cleanup
            except BaseException as error:
                cleanup_errors.append(error)
        else:
            try:
                recovered_tuple = _single_probe_intent_tuple(events)
                trigger_intent = (
                    _probe_trigger_intent_from_events(
                        events, provider_id=recovered_tuple[0], probe_kind=recovered_tuple[1]
                    )
                    if recovered_tuple is not None
                    else None
                )
                request = (
                    _probe_request_from_events(
                        events, provider_id=recovered_tuple[0], probe_kind=recovered_tuple[1]
                    )
                    if recovered_tuple is not None
                    else None
                )
                if trigger_intent is not None:
                    if request is None:
                        raise ValueError(
                            "benchmark probe request is unavailable for prior trigger intent"
                        )
                    observation_context = _probe_context_from_events(
                        events, trigger_intent=trigger_intent, request=request
                    )
                    trigger_observation = _probe_trigger_observation_from_events(
                        events,
                        provider_id=recovered_tuple[0],
                        probe_kind=recovered_tuple[1],
                        required=True,
                    )
                    assert trigger_observation is not None
                    _validate_probe_trigger_observation_lineage(
                        material=trigger_observation,
                        context=observation_context,
                        request=request,
                    )
                if (
                    service_terminal is None
                    and trigger_intent is not None
                    and request is not None
                ):
                    recovered_context = _probe_context_from_events(
                        events, trigger_intent=trigger_intent, request=request
                    )
                    recovered_terminal = _safe_stopped_terminal_from_lookup(
                        events=events,
                        service=get_production_benchmark_v2_workflow_service(),
                        context=recovered_context,
                        request=request,
                    )
                    if recovered_terminal is not None:
                        assert recovered_tuple is not None
                        intent_event = _one_probe_event_for_tuple(
                            events,
                            event_kind="probe_trigger_intent",
                            provider_id=recovered_tuple[0],
                            probe_kind=recovered_tuple[1],
                            required=True,
                        )
                        assert intent_event is not None
                        service_terminal = _persist_recovered_probe_terminal(
                            journal_path=journal_path,
                            context=recovered_context,
                            request=request,
                            trigger_intent_event=intent_event,
                            service_terminal=recovered_terminal,
                        )
                        events = read_benchmark_v2_attempt_journal(
                            journal_path=journal_path,
                            attempt_ref=attempt_ref,
                        )
                if service_terminal is None and recovered_tuple is not None:
                    service_terminal = _service_terminal_from_events(
                        events,
                        provider_id=recovered_tuple[0],
                        probe_kind=recovered_tuple[1],
                    )
                if (
                    isinstance(service_terminal, Mapping)
                    and trigger_intent is not None
                    and request is not None
                    and recovered_tuple is not None
                    and _one_probe_event_for_tuple(
                        events,
                        event_kind="probe_trigger_terminal",
                        provider_id=recovered_tuple[0],
                        probe_kind=recovered_tuple[1],
                        required=False,
                    )
                    is None
                ):
                    recovered_context = _probe_context_from_events(
                        events, trigger_intent=trigger_intent, request=request
                    )
                    intent_event = _one_probe_event_for_tuple(
                        events,
                        event_kind="probe_trigger_intent",
                        provider_id=recovered_tuple[0],
                        probe_kind=recovered_tuple[1],
                        required=True,
                    )
                    assert intent_event is not None
                    service_terminal = _persist_recovered_probe_terminal(
                        journal_path=journal_path,
                        context=recovered_context,
                        request=request,
                        trigger_intent_event=intent_event,
                        service_terminal=service_terminal,
                    )
                    events = read_benchmark_v2_attempt_journal(
                        journal_path=journal_path,
                        attempt_ref=attempt_ref,
                    )
                service_operation = durable_service_operation
                service: object | None = None
                intent = _service_start_intent_from_events(events)
                if service_operation is None and intent is not None:
                    service = get_production_benchmark_v2_workflow_service()
                    service_operation = _lookup_service_operation_from_intent(
                        events=events,
                        service=service,
                    )
                    if isinstance(service_operation, Mapping):
                        service_operation = _append_service_recovered_event(
                            journal_path=journal_path,
                            attempt_ref=attempt_ref,
                            operation=service_operation,
                            binding=intent["window_binding"],
                            screen_group=intent["screen_group"],
                        )
                if service_terminal is None and service_operation is not None:
                    if trigger_intent is not None:
                        if service_operation != trigger_intent["operation_ref"]:
                            raise ValueError("benchmark probe pending recovery operation is stale")
                        _observe_exact_process_identities_before_cancel(
                            trigger_intent["process_identities"]
                        )
                    if service is None:
                        service = get_production_benchmark_v2_workflow_service()
                    service_terminal = service.cancel_operation(
                        operation_ref=service_operation
                    )
                    service_terminal = _validate_service_terminal(service_terminal)
                if (
                    isinstance(service_terminal, Mapping)
                    and trigger_intent is not None
                    and request is not None
                    and recovered_tuple is not None
                    and _one_probe_event_for_tuple(
                        events,
                        event_kind="probe_trigger_terminal",
                        provider_id=recovered_tuple[0],
                        probe_kind=recovered_tuple[1],
                        required=False,
                    )
                    is None
                ):
                    recovered_context = _probe_context_from_events(
                        events, trigger_intent=trigger_intent, request=request
                    )
                    intent_event = _one_probe_event_for_tuple(
                        events,
                        event_kind="probe_trigger_intent",
                        provider_id=recovered_tuple[0],
                        probe_kind=recovered_tuple[1],
                        required=True,
                    )
                    assert intent_event is not None
                    service_terminal = _persist_recovered_probe_terminal(
                        journal_path=journal_path,
                        context=recovered_context,
                        request=request,
                        trigger_intent_event=intent_event,
                        service_terminal=service_terminal,
                    )
                    events = read_benchmark_v2_attempt_journal(
                        journal_path=journal_path,
                        attempt_ref=attempt_ref,
                    )
            except BaseException as error:
                cleanup_errors.append(error)
            try:
                with self._lock:
                    active = self._active
                    active_matches = bool(
                        isinstance(active, Mapping)
                        and active.get("attempt_ref") == attempt_ref
                    )
                    owner_token = active.get("owner_token") if active_matches else None
                if owner_token is not None:
                    window_cleanup = self._close_active(
                        owner_token=owner_token,
                        reason=normalized_reason,
                    )
                else:
                    owner_journal = _owner_journal_from_events(
                        events,
                        authority_root=self._authority_root,
                    )
                    if owner_journal is not None:
                        window_cleanup = _sealed_parent(
                            close_owned_window(
                                journal_path=owner_journal,
                                reason=normalized_reason,
                            ),
                            name="window cleanup receipt",
                        )
            except BaseException as error:
                cleanup_errors.append(error)

        if cleanup_errors:
            raise BaseExceptionGroup(
                "benchmark cleanup remains indeterminate",
                cleanup_errors,
            )

        if (
            actual_attestations
            and not actual_pre_reservation_recoveries
            and not actual_completed_hybrid_cleanups
            and not partial_actual_terminals
        ):
            if len(actual_attestations) == 1:
                service_terminal_ref = _cleanup_parent_ref(
                    actual_attestations[0],
                    parent_kind="actual_operations_stable_zero",
                    name="actual operations stable-zero attestation",
                )
            else:
                service_terminal_ref = _cleanup_parent_ref(
                    _runtime_resource_ref(
                        "actual_group_stable_zero_attestations",
                        {
                            "group_attestation_refs": [
                                _content_ref(item, name="actual group attestation")
                                for item in actual_attestations
                            ]
                        },
                    ),
                    parent_kind="actual_operations_stable_zero_aggregate",
                    name="actual operations stable-zero aggregate",
                )
        elif (
            partial_actual_terminals
            or actual_pre_reservation_recoveries
            or actual_completed_hybrid_cleanups
        ):
            if (
                not actual_attestations
                and not actual_pre_reservation_recoveries
                and not actual_completed_hybrid_cleanups
                and len(partial_actual_terminals) == 1
            ):
                service_terminal_ref = _cleanup_parent_ref(
                    partial_actual_terminals[0],
                    parent_kind="workflow_service_terminal",
                    name="partial actual workflow service terminal",
                )
            elif (
                not actual_attestations
                and not actual_pre_reservation_recoveries
                and not partial_actual_terminals
                and len(actual_completed_hybrid_cleanups) == 1
            ):
                service_terminal_ref = _cleanup_parent_ref(
                    actual_completed_hybrid_cleanups[0],
                    parent_kind="actual_completed_hybrid_cleanup",
                    name="actual completed Hybrid cleanup",
                )
            else:
                service_terminal_ref = _cleanup_parent_ref(
                    _runtime_resource_ref(
                        "actual_operations_cleanup_aggregate",
                        {
                            "full_group_attestation_refs": [
                                _content_ref(item, name="actual group attestation")
                                for item in actual_attestations
                            ],
                            "pre_reservation_recovery_refs": [
                                _content_ref(
                                    item,
                                    name="actual pre-reservation recovery",
                                )
                                for item in actual_pre_reservation_recoveries
                            ],
                            "completed_hybrid_cleanup_refs": [
                                _content_ref(
                                    item,
                                    name="actual completed Hybrid cleanup",
                                )
                                for item in actual_completed_hybrid_cleanups
                            ],
                            "partial_workflow_terminal_refs": [
                                _content_ref(
                                    item,
                                    name="partial actual workflow service terminal",
                                )
                                for item in partial_actual_terminals
                            ],
                        },
                    ),
                    parent_kind="actual_operations_cleanup_aggregate",
                    name="actual operations cleanup aggregate",
                )
        else:
            service_terminal_ref = (
                _cleanup_parent_ref(
                    service_terminal,
                    parent_kind="workflow_service_terminal",
                    name="workflow service terminal result",
                )
                if isinstance(service_terminal, Mapping)
                else None
            )
        if actual_terminals or actual_completed_hybrid_cleanups:
            provider_cleanup_refs = []
            completed_operation_shas = {
                str(item["operation_ref"]["content_sha256"])
                for item in actual_completed_hybrid_cleanups
            }
            for terminal in actual_terminals:
                cleanup = terminal["cleanup_refs"]
                if all(
                    isinstance(cleanup.get(name), Mapping)
                    for name in ("worker_cleanup_ref", "provider_cleanup_ref")
                ):
                    provider_cleanup_refs.extend(
                        _cleanup_parent_ref(
                            cleanup[name],
                            parent_kind=parent_kind,
                            name=f"actual {name}",
                        )
                        for name, parent_kind in (
                            ("worker_cleanup_ref", "worker_cleanup"),
                            ("provider_cleanup_ref", "provider_cleanup"),
                        )
                    )
                elif (
                    cleanup
                    == {"worker_cleanup_ref": None, "provider_cleanup_ref": None}
                    and str(terminal["operation_ref"]["content_sha256"])
                    in completed_operation_shas
                ):
                    continue
                else:
                    raise ValueError(
                        "actual terminal cleanup has no exact cleanup proof"
                    )
            for completed_cleanup in actual_completed_hybrid_cleanups:
                provider_cleanup_refs.extend(
                    _cleanup_parent_ref(
                        completed_cleanup[name],
                        parent_kind=parent_kind,
                        name=f"actual completed Hybrid {name}",
                    )
                    for name, parent_kind in (
                        ("worker_cleanup_ref", "worker_cleanup"),
                        ("provider_cleanup_ref", "provider_cleanup"),
                    )
                )
        else:
            provider_cleanup_refs = _provider_cleanup_refs(service_terminal)
        counts = dict(self.resource_counts())
        counts["service_operations"] += unresolved_actual_operations
        receipt = compose_benchmark_v2_attempt_cleanup_receipt(
            attempt_ref=attempt_ref,
            reason=normalized_reason,
            service_terminal_ref=service_terminal_ref,
            window_cleanup_ref=(
                _cleanup_parent_ref(
                    window_cleanup,
                    parent_kind="window_cleanup",
                    name="window cleanup receipt",
                )
                if isinstance(window_cleanup, Mapping)
                else None
            ),
            provider_cleanup_refs=provider_cleanup_refs,
            resource_counts=counts,
        )
        append_benchmark_v2_attempt_event(
            journal_path=journal_path,
            attempt_ref=attempt_ref,
            phase="body_complete",
            event_kind="attempt_cleanup_prepared",
            resource_ref=_runtime_resource_ref(
                "attempt_cleanup_receipt",
                {"cleanup_receipt": receipt},
            ),
        )
        append_benchmark_v2_attempt_event(
            journal_path=journal_path,
            attempt_ref=attempt_ref,
            phase="terminal",
            event_kind="attempt_terminal",
            resource_ref=_runtime_resource_ref(
                "attempt_cleanup_receipt",
                {"cleanup_receipt": receipt},
            ),
        )
        if isinstance(state, dict):
            with self._lock:
                self._attempt_states.pop(attempt_key, None)
        return receipt

    def resource_counts(self) -> Mapping[str, int]:
        with self._lock:
            states = list(self._attempt_states.values())
            windows = int(self._active is not None or self._pending_cleanup is not None)
        active_states = [
            state for state in states if not isinstance(state.get("window_cleanup"), Mapping)
        ]
        requests = [
            state
            for state in active_states
            if isinstance(state.get("request_in_flight"), Mapping)
            and not isinstance(state.get("service_terminal"), Mapping)
        ]
        managed = [
            state for state in requests if state.get("provider_id") in {"qwen", "vista"}
        ]
        return {
            "service_operations": len(active_states),
            "windows": windows,
            "providers": len(requests),
            "listeners": len(managed),
            "leases": len(managed),
        }

    def _probe_state(self, context: Mapping[str, object]) -> dict[str, Any]:
        attempt_key = str(context["attempt_ref"]["content_sha256"])
        with self._lock:
            state = self._attempt_states.get(attempt_key)
        if not isinstance(state, dict) or state.get("probe_context") != context:
            raise ValueError("benchmark probe context is stale or cross-attempt")
        return state

    def _close_probe_window(
        self, *, state: Mapping[str, object], reason: str
    ) -> Mapping[str, object]:
        binding = state.get("window_binding")
        if not isinstance(binding, Mapping):
            raise ValueError("benchmark probe window binding is unavailable")
        receipt = self.close_screen_group(
            window_binding=binding,
            reason=reason,
        )
        iterator = state.get("iterator")
        close = getattr(iterator, "close", None)
        if callable(close):
            close()
        return receipt

    def _prepare_one(
        self,
        *,
        loaded: _LoadedProviderManifest,
        attempt_ref: Mapping[str, object],
        attempt_dir: Path,
        partition: str,
        screen_group: str,
        cases: list[dict[str, Any]],
        case_refs: list[dict[str, object]],
        owner_token: object,
    ) -> dict[str, Any]:
        image = cases[0]["image"]
        source = _project_file(
            self._project_root,
            Path(str(image["path"])),
            name="provider screenshot source",
        )
        raw = _read_exact_file(source)
        image_sha = sha256(raw).hexdigest()
        if image_sha != image["sha256"]:
            raise ValueError("provider screenshot source SHA differs from corpus")
        destination = (
            self._project_root
            / _SCREENSHOT_ROOT
            / str(attempt_ref["content_sha256"])[:24]
            / f"{screen_group}.png"
        ).resolve()
        _create_identical(destination, raw)
        operation_digest = sha256(
            canonical_json_bytes(
                {
                    "attempt_ref": dict(attempt_ref),
                    "partition": partition,
                    "screen_group": screen_group,
                    "image_sha256": image_sha,
                }
            )
        ).hexdigest()
        operation_id = f"benchmark-v2-{operation_digest[:48]}"
        run_id = f"benchmark-v2-run-{operation_digest}"
        journal_path = self._authority_root / f"{operation_id}.owner.json"
        owner: Mapping[str, object] | None = None
        try:
            self._authority_root.mkdir(parents=True, exist_ok=True)
            append_benchmark_v2_attempt_event(
                journal_path=_benchmark_v2_attempt_journal_path(
                    project_root=self._project_root,
                    attempt_ref=attempt_ref,
                ),
                attempt_ref=attempt_ref,
                phase="prepared",
                event_kind="window_owned",
                resource_ref=_runtime_resource_ref(
                    "owned_window",
                    {
                        "attempt_dir": str(attempt_dir),
                        "owner_journal_path": str(journal_path.resolve()),
                        "operation_id": operation_id,
                        "screen_group": screen_group,
                        "ownership_state": "launch_prepared",
                    },
                ),
            )
            owner = launch_owned_window(
                image_path=destination,
                expected_sha256=image_sha,
                operation_id=operation_id,
                journal_path=journal_path,
            )
            with self._lock:
                if self._pending_cleanup is not None or self._active is not None:
                    raise RuntimeError("benchmark runtime acquired a second cleanup owner")
                self._pending_cleanup = {
                    "owner_token": owner_token,
                    "journal_path": journal_path,
                    "owner_id": owner["owner_id"],
                }
            snapshot_record = _validate_snapshot_record(
                snapshot_owned_window(owner=owner), owner=owner
            )
            uia_snapshot = snapshot_record["uia_snapshot"]
            window_binding = _capture_window_binding(owner, uia_snapshot)
            identity = seal_hybrid_capture_identity(
                project_root=self._project_root,
                image_path=destination,
                run_id=run_id,
                workflow_revision=0,
                window_binding=window_binding,
            )
            ocr_value = ocr_service.scan_image(str(destination.resolve()))
            if not hasattr(ocr_value, "to_dict"):
                raise ValueError("built-in OCR did not return its exact result contract")
            ocr_result = ocr_value.to_dict()
            if (
                ocr_result.get("image_path") != str(destination.resolve())
                or not isinstance(ocr_result.get("matches"), list)
                or not ocr_result["matches"]
                or not isinstance(ocr_result.get("metadata"), dict)
                or ocr_result["metadata"].get("match_count")
                != len(ocr_result["matches"])
            ):
                raise ValueError("built-in OCR result is empty or does not bind the exact PNG")
            ocr_ref = seal_builtin_ocr_evidence(
                project_root=self._project_root,
                image_path=destination,
                capture_id=str(identity["capture_id"]),
                captured_at=str(identity["captured_at"]),
                ocr_result=ocr_result,
                expected_image_sha256=image_sha,
                expected_image_size={
                    "width": int(image["width"]),
                    "height": int(image["height"]),
                },
                capture_lineage_ref=identity["capture_lineage_ref"],
                capture_envelope=identity.capture_envelope,
            )
            uia_ref = seal_builtin_uia_evidence(
                project_root=self._project_root,
                image_path=destination,
                capture_lineage_ref=identity["capture_lineage_ref"],
                capture_envelope=identity.capture_envelope,
                uia_snapshot=uia_snapshot,
                window_binding=window_binding,
            )
            context = {
                "capture_lineage_ref": deepcopy(identity["capture_lineage_ref"]),
                "sources": [
                    _capture_source(
                        source_kind="ocr",
                        evidence_ref=ocr_ref,
                        identity=identity,
                        run_id=run_id,
                        window_binding=window_binding,
                    ),
                    _capture_source(
                        source_kind="uia",
                        evidence_ref=uia_ref,
                        identity=identity,
                        run_id=run_id,
                        window_binding=window_binding,
                    ),
                ],
                "derived_views": [],
            }
            bundle = seal_hybrid_capture_bundle(
                project_root=self._project_root,
                image_path=destination,
                run_id=run_id,
                workflow_revision=0,
                window_binding=window_binding,
                ocr_uia_context=context,
                capture_envelope=identity.capture_envelope,
            )
            request_ref, registration_ref, manifest_ref = _seal_omni_parents(
                project_root=self._project_root,
                capture_lineage_ref=identity["capture_lineage_ref"],
                capture_id=str(identity["capture_id"]),
            )
            capture_ref = {
                "id": str(identity["capture_id"]),
                "content_sha256": image_sha,
            }
            authority = publish_server_worker_window_binding(
                publisher=get_production_server_worker_window_binding_publisher(),
                run_id=run_id,
                stage="screen_understanding",
                operation_id=operation_id,
                owner=owner,
                capture_ref=capture_ref,
            )
            workflow_window_binding = compose_benchmark_v2_workflow_window_binding(
                run_id=run_id,
                operation_id=operation_id,
                window_binding_ref=authority["window_binding_ref"],
                capture_ref=capture_ref,
                owner_journal_ref=authority["owner_journal_ref"],
                expected_uia_root_ref=owner["uia_root_identity"],
            )
            relative_capture = destination.relative_to(self._project_root).as_posix()
            screen_group_start = compose_benchmark_v2_hybrid_screen_group_start(
                attempt_ref=attempt_ref,
                partition=partition,
                screen_group=screen_group,
                provider_corpus_ref=loaded._corpus_file_ref,
                case_refs=case_refs,
                hybrid_capture_bundle_ref=bundle["bundle_ref"],
                request_ref=request_ref,
                registration_ref=registration_ref,
                manifest_ref=manifest_ref,
                capture_image_path=relative_capture,
                hybrid_config=load_hybrid_config(self._project_root),
                capture_bundle=bundle,
            )
            prepared = {
                "screen_group_start": screen_group_start,
                "workflow_window_binding": workflow_window_binding,
                "owner": deepcopy(dict(owner)),
                "journal_path": journal_path,
                "attempt_ref": deepcopy(dict(attempt_ref)),
                "attempt_dir": str(attempt_dir),
            }
            append_benchmark_v2_attempt_event(
                journal_path=_benchmark_v2_attempt_journal_path(
                    project_root=self._project_root,
                    attempt_ref=attempt_ref,
                ),
                attempt_ref=attempt_ref,
                phase="prepared",
                event_kind="window_owned",
                resource_ref=_runtime_resource_ref(
                    "owned_window",
                    {
                        "attempt_dir": str(attempt_dir),
                        "owner_journal_path": str(journal_path.resolve()),
                        "owner_id": str(owner["owner_id"]),
                        "process_identity_projection": (
                            _runtime_process_identity_projection(
                                owner["process_identity"]
                            )
                        ),
                        "workflow_window_binding": workflow_window_binding,
                        "ownership_state": "owned",
                    },
                ),
            )
            with self._lock:
                if self._active is not None:
                    raise RuntimeError("benchmark runtime acquired a second live window")
                pending = self._pending_cleanup
                if (
                    pending is None
                    or pending["owner_token"] is not owner_token
                    or pending["journal_path"] != journal_path
                ):
                    raise RuntimeError("benchmark cleanup ownership changed before publish")
                self._active = {**prepared, "owner_token": owner_token}
            return deepcopy(prepared)
        except BaseException as primary:
            if owner is not None:
                try:
                    self._close_active(
                        owner_token=owner_token,
                        reason="benchmark_v2_screen_group_prepare_failed",
                    )
                except BaseException as cleanup:
                    raise BaseExceptionGroup(
                        "benchmark screen group prepare and cleanup failed",
                        [primary, cleanup],
                    )
            raise

    def _close_active(
        self, *, owner_token: object, reason: str
    ) -> Mapping[str, object]:
        with self._lock:
            active = self._active
            pending = self._pending_cleanup
            if active is None and pending is None:
                return _sealed_parent(
                    {"content_sha256": "0" * 64}, name="empty close replay"
                )
            if pending is None or pending["owner_token"] is not owner_token:
                raise RuntimeError("benchmark cleanup owner differs")
            if active is not None and active["owner_token"] is not owner_token:
                raise RuntimeError("benchmark active owner differs")
            receipt = close_owned_window(
                journal_path=Path(str(pending["journal_path"])),
                reason=reason,
            )
            sealed = _sealed_parent(receipt, name="window cleanup receipt")
            self._active = None
            self._pending_cleanup = None
            return sealed


def _loaded_manifest(value: Mapping[str, object]) -> _LoadedProviderManifest:
    if type(value) is not _LoadedProviderManifest:
        raise ValueError("provider manifest must come from this production runtime")
    validate_provider_manifest(value)
    return value


def _partition_groups(
    loaded: _LoadedProviderManifest, *, partition: str
) -> list[tuple[str, list[dict[str, Any]], list[dict[str, object]]]]:
    ref_by_id = {str(ref["case_id"]): deepcopy(ref) for ref in loaded._case_refs}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in loaded._corpus["cases"]:
        if case["partition"] == partition:
            grouped.setdefault(str(case["screen_group"]), []).append(deepcopy(case))
    result = []
    for screen_group in sorted(grouped):
        cases = grouped[screen_group]
        if len(cases) != 5:
            raise ValueError("provider screen group no longer contains five cases")
        refs = [ref_by_id[str(case["case_id"])] for case in cases]
        result.append((screen_group, cases, refs))
    if len(result) != 12:
        raise ValueError("provider partition no longer contains twelve screen groups")
    return result


def _canonical_file(path: Path, *, name: str) -> Path:
    if not isinstance(path, Path):
        raise ValueError(f"{name} must be a server-owned Path")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{name} is not a file")
    return resolved


def _project_file(root: Path, path: Path, *, name: str) -> Path:
    try:
        candidate = (root / path).resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{name} is missing") from error
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{name} escapes project root") from error
    if not candidate.is_file():
        raise ValueError(f"{name} is missing")
    return candidate


def _read_exact_file(path: Path) -> bytes:
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (
        before.st_size != len(raw)
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise ValueError("provider screenshot changed during exact read")
    return raw


def _create_identical(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError("benchmark capture destination is already occupied")
        return
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if path.read_bytes() != raw:
        raise ValueError("benchmark capture copy is not byte-identical")


def _canonical_attempt_directory(value: Path) -> Path:
    if not isinstance(value, Path):
        raise ValueError("benchmark attempt directory must be a server-owned Path")
    directory = value if value.is_absolute() else value.resolve()
    if directory != directory.resolve():
        raise ValueError("benchmark attempt directory must be canonical")
    return directory


def _actual_screen_group_paths(
    *,
    attempt_dir: Path,
    attempt_ref: Mapping[str, object],
    screen_group: str,
) -> dict[str, Path]:
    token = sha256(
        canonical_json_bytes(
            {
                "attempt_ref": dict(attempt_ref),
                "screen_group": str(screen_group),
            }
        )
    ).hexdigest()
    root = (Path(attempt_dir) / _ACTUAL_DIRECTORY).resolve()
    if root.parent != Path(attempt_dir).resolve():
        raise ValueError("benchmark actual projection directory escapes attempt root")
    return {
        "intent": root / f"{token}.service-intent.json",
        "result": root / f"{token}.service-result.json",
        "projection": root / f"{token}.projection.json",
    }


def _actual_case_ref(
    group: Mapping[str, object], value: Mapping[str, object]
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("benchmark actual incumbent case ref is invalid")
    candidate = deepcopy(dict(value))
    matches = [item for item in group["case_refs"] if dict(item) == candidate]
    if len(matches) != 1:
        raise ValueError("benchmark actual incumbent case lineage is stale")
    return deepcopy(dict(matches[0]))


def _actual_case_for_operation(
    group: Mapping[str, object], operation: Mapping[str, object]
) -> dict[str, Any]:
    request_ref = operation["request_ref"]
    matches = [
        item
        for item in group["case_refs"]
        if {
            "id": str(item["case_id"]),
            "content_sha256": str(item["case_content_sha256"]),
        }
        == request_ref
    ]
    if len(matches) != 1:
        raise ValueError("benchmark actual incumbent operation case lineage is stale")
    return deepcopy(dict(matches[0]))


def _actual_incumbent_call_intent(
    *,
    intent_ref: Mapping[str, object],
    group: Mapping[str, object],
    binding: Mapping[str, object],
    call_kind: str,
    provider_case_ref: Mapping[str, object],
    operation_ref: Mapping[str, object] | None,
    worker_ref: Mapping[str, object] | None,
) -> dict[str, Any]:
    if call_kind not in {"start", "poll", "adopt"}:
        raise ValueError("benchmark actual incumbent call kind is invalid")
    if (call_kind == "start") != (operation_ref is None):
        raise ValueError("benchmark actual incumbent call operation input is invalid")
    if (call_kind == "adopt") != (worker_ref is not None):
        raise ValueError("benchmark actual incumbent adopt worker input is invalid")
    operation = (
        validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
        if operation_ref is not None
        else None
    )
    if operation is not None:
        _actual_case_for_operation(group, operation)
    worker = (
        _sealed_parent(worker_ref, name="benchmark actual incumbent worker ref")
        if worker_ref is not None
        else None
    )
    if worker is not None and operation is not None and worker != operation["worker_ref"]:
        raise ValueError("benchmark actual incumbent adopt worker lineage is stale")
    return _sealed_record(
        {
            "contract_version": _ACTUAL_CALL_INTENT_CONTRACT,
            "screen_group_ref": _actual_group_ref(group),
            "service_intent_ref": deepcopy(dict(intent_ref)),
            "call_kind": call_kind,
            "provider_case_ref": deepcopy(dict(provider_case_ref)),
            "window_binding_ref": deepcopy(binding["window_binding_ref"]),
            "capture_ref": deepcopy(binding["capture_ref"]),
            "stage": str(binding["stage"]),
            "operation_ref": operation,
            "worker_ref": worker,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def _actual_incumbent_call_paths(
    root: Path, *, intent: Mapping[str, object]
) -> dict[str, Path]:
    token = str(intent["content_sha256"])
    directory = Path(root).resolve()
    return {
        "intent": directory / f"{token}.intent.json",
        "result": directory / f"{token}.result.json",
    }


def _read_actual_incumbent_call_result(
    path: Path,
    *,
    intent_ref: Mapping[str, object],
    provider_case_ref: Mapping[str, object],
    binding: Mapping[str, object],
) -> dict[str, Any] | None:
    if not Path(path).exists():
        return None
    record = _sealed_parent(
        _read_canonical_json(path, name="benchmark actual incumbent call result"),
        name="benchmark actual incumbent call result",
    )
    if (
        set(record)
        != {
            "contract_version",
            "intent_ref",
            "service_step",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        or record["contract_version"] != _ACTUAL_CALL_RESULT_CONTRACT
        or record["intent_ref"] != intent_ref
        or record["artifact_is_authorization"] is not False
        or record["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark actual incumbent call result lineage is stale")
    record["service_step"] = _validate_actual_incumbent_step(
        record["service_step"],
        provider_case_ref=provider_case_ref,
        binding=binding,
        expected_operation=None,
    )
    return record


def _actual_attempt_directory_from_events(
    events: list[Mapping[str, object]],
) -> Path | None:
    directories: set[str] = set()
    for event in events:
        if event.get("event_kind") != "attempt_prepared":
            continue
        value = _runtime_resource_value(event, expected_kind="attempt_directory")
        if not isinstance(value, Mapping) or set(value) != {"attempt_dir"}:
            raise ValueError("benchmark actual attempt directory event is not closed")
        directory = _canonical_attempt_directory(Path(str(value["attempt_dir"])))
        directories.add(str(directory))
    if not directories:
        return None
    if len(directories) != 1:
        raise ValueError("benchmark actual attempt directory lineage is stale")
    return Path(next(iter(directories)))


def _read_actual_incumbent_call_intents(
    *, attempt_dir: Path,
) -> list[dict[str, Any]]:
    root = (Path(attempt_dir) / _ACTUAL_DIRECTORY / "incumbent-calls").resolve()
    if not root.exists():
        return []
    if not root.is_dir() or root.parent != (Path(attempt_dir) / _ACTUAL_DIRECTORY).resolve():
        raise ValueError("benchmark actual incumbent call directory is stale")
    intents: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.intent.json")):
        intent = _sealed_parent(
            _read_canonical_json(path, name="benchmark actual incumbent call intent"),
            name="benchmark actual incumbent call intent",
        )
        if (
            intent.get("contract_version") != _ACTUAL_CALL_INTENT_CONTRACT
            or intent.get("call_kind") not in {"start", "poll", "adopt"}
            or not isinstance(intent.get("provider_case_ref"), Mapping)
            or not isinstance(intent.get("service_intent_ref"), Mapping)
            or intent.get("artifact_is_authorization") is not False
            or intent.get("execute_binding_enabled") is not False
        ):
            raise ValueError("benchmark actual incumbent call intent is invalid")
        service_intent = _sealed_parent(
            intent["service_intent_ref"],
            name="benchmark actual screen-group service intent",
        )
        if (
            service_intent.get("contract_version") != _ACTUAL_INTENT_CONTRACT
            or not isinstance(service_intent.get("provider_group"), Mapping)
            or not isinstance(service_intent.get("window_binding"), Mapping)
        ):
            raise ValueError("benchmark actual call parent service intent is stale")
        group = validate_benchmark_v2_hybrid_screen_group_start(
            service_intent["provider_group"]
        )
        binding = validate_benchmark_v2_workflow_window_binding(
            service_intent["window_binding"]
        )
        case_ref = _actual_case_ref(group, intent["provider_case_ref"])
        if (
            intent.get("screen_group_ref") != _actual_group_ref(group)
            or intent.get("window_binding_ref") != binding["window_binding_ref"]
            or intent.get("capture_ref") != binding["capture_ref"]
            or intent.get("stage") != binding["stage"]
        ):
            raise ValueError("benchmark actual incumbent call parent lineage is stale")
        intent["provider_group"] = group
        intent["window_binding"] = binding
        intent["provider_case_ref"] = case_ref
        intents.append(intent)
    return intents


def _read_actual_screen_group_service_intents(
    *, attempt_dir: Path,
) -> list[dict[str, Any]]:
    root = (Path(attempt_dir) / _ACTUAL_DIRECTORY).resolve()
    if not root.exists():
        return []
    intents: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.service-intent.json")):
        intent = _sealed_parent(
            _read_canonical_json(path, name="benchmark actual service intent"),
            name="benchmark actual service intent",
        )
        if (
            intent.get("contract_version") != _ACTUAL_INTENT_CONTRACT
            or not isinstance(intent.get("provider_group"), Mapping)
            or not isinstance(intent.get("window_binding"), Mapping)
            or intent.get("artifact_is_authorization") is not False
            or intent.get("execute_binding_enabled") is not False
        ):
            raise ValueError("benchmark actual service intent is invalid")
        intent["provider_group"] = validate_benchmark_v2_hybrid_screen_group_start(
            intent["provider_group"]
        )
        intent["window_binding"] = validate_benchmark_v2_workflow_window_binding(
            intent["window_binding"]
        )
        intents.append(intent)
    return sorted(
        intents,
        key=lambda item: (
            str(item["provider_group"]["partition"]),
            str(item["provider_group"]["screen_group"]),
        ),
    )


def _reconcile_actual_operations(
    *, attempt_dir: Path, service: object
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    int,
]:
    intents = _read_actual_incumbent_call_intents(attempt_dir=attempt_dir)
    screen_group_intents = _read_actual_screen_group_service_intents(
        attempt_dir=attempt_dir
    )
    targets: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for intent in intents:
        case_ref = intent["provider_case_ref"]
        parent_sha = str(intent["service_intent_ref"]["content_sha256"])
        key = (
            str(case_ref["case_id"]),
            str(case_ref["case_content_sha256"]),
        )
        targets.setdefault(parent_sha, {})[key] = intent
    lookup_hybrid = getattr(service, "lookup_hybrid_operation", None)
    lookup = getattr(service, "lookup_incumbent_observe", None)
    recover_pre_reservation = getattr(
        service,
        "recover_incumbent_pre_reservation",
        None,
    )
    cancel = getattr(service, "cancel_operation", None)
    attest = getattr(service, "attest_actual_operations_stable_zero", None)
    attest_completed_hybrid = getattr(
        service,
        "attest_completed_hybrid_cleanup",
        None,
    )
    if not callable(cancel) or (
        any(targets.values()) and not callable(lookup)
    ) or (
        screen_group_intents and not callable(lookup_hybrid)
    ):
        raise RuntimeError("WorkflowService actual operation recovery is unavailable")
    terminals: list[dict[str, Any]] = []
    attestations: list[dict[str, Any]] = []
    pre_reservation_recoveries: list[dict[str, Any]] = []
    completed_hybrid_cleanups: list[dict[str, Any]] = []
    partial_terminals: list[dict[str, Any]] = []
    unresolved_operations = 0
    for intent in screen_group_intents:
        group_terminals: list[dict[str, Any]] = []
        step_value = lookup_hybrid(
            screen_group=deepcopy(intent["provider_group"]),
            window_binding=deepcopy(intent["window_binding"]),
        )
        if step_value is not None:
            step = validate_benchmark_v2_workflow_service_step(step_value)
            _validate_actual_service_step(
                step,
                group=intent["provider_group"],
                binding=intent["window_binding"],
            )
            terminal = _validate_service_terminal(
                cancel(operation_ref=deepcopy(step["operation_ref"]))
            )
            _validate_actual_terminal_successor(
                terminal=terminal["operation_ref"],
                supplied=step["operation_ref"],
            )
            confirmed = lookup_hybrid(
                screen_group=deepcopy(intent["provider_group"]),
                window_binding=deepcopy(intent["window_binding"]),
            )
            if confirmed is None or validate_benchmark_v2_workflow_service_step(
                confirmed
            )["operation_ref"] != terminal["operation_ref"]:
                raise ValueError("benchmark actual Hybrid cleanup lookup differs")
            group_terminals.append(terminal)
        else:
            unresolved_operations += 1
        parent_sha = str(intent["content_sha256"])
        for key in sorted(targets.get(parent_sha, {})):
            call_intent = targets[parent_sha][key]
            recovery_value = (
                recover_pre_reservation(
                    provider_case_ref=deepcopy(call_intent["provider_case_ref"]),
                    window_binding=deepcopy(call_intent["window_binding"]),
                )
                if callable(recover_pre_reservation)
                else None
            )
            if recovery_value is not None:
                from app.learn.workflow_service import (
                    _benchmark_v2_incumbent_child_slot,
                )

                recovery = validate_benchmark_v2_incumbent_pre_reservation_recovery(
                    recovery_value
                )
                expected_child_slot = _benchmark_v2_incumbent_child_slot(
                    provider_case_ref=call_intent["provider_case_ref"],
                    window_binding=call_intent["window_binding"],
                )
                if (
                    recovery["provider_case_ref"]
                    != call_intent["provider_case_ref"]
                    or recovery["run_id"] != expected_child_slot["run_id"]
                    or recovery["stage"]
                    != expected_child_slot["stage"]
                    or recovery["operation_id"]
                    != expected_child_slot["operation_id"]
                    or recovery["window_binding_ref"]
                    != call_intent["window_binding"]["window_binding_ref"]
                    or recovery["capture_ref"]
                    != call_intent["window_binding"]["capture_ref"]
                ):
                    raise ValueError(
                        "benchmark actual pre-reservation recovery lineage differs"
                    )
                pre_reservation_recoveries.append(recovery)
                continue
            step_value = lookup(
                provider_case_ref=deepcopy(call_intent["provider_case_ref"]),
                window_binding=deepcopy(call_intent["window_binding"]),
            )
            if step_value is None:
                unresolved_operations += 1
                continue
            step = _validate_actual_incumbent_step(
                step_value,
                provider_case_ref=call_intent["provider_case_ref"],
                binding=call_intent["window_binding"],
                expected_operation=None,
            )
            terminal = _validate_service_terminal(
                cancel(operation_ref=deepcopy(step["operation_ref"]))
            )
            _validate_actual_terminal_successor(
                terminal=terminal["operation_ref"],
                supplied=step["operation_ref"],
            )
            confirmed = lookup(
                provider_case_ref=deepcopy(call_intent["provider_case_ref"]),
                window_binding=deepcopy(call_intent["window_binding"]),
            )
            if confirmed is None or validate_benchmark_v2_workflow_service_step(
                confirmed
            )["operation_ref"] != terminal["operation_ref"]:
                raise ValueError("benchmark actual incumbent cleanup lookup differs")
            group_terminals.append(terminal)
        if len(group_terminals) == 6 and len(targets.get(parent_sha, {})) == 5:
            if not callable(attest):
                raise RuntimeError(
                    "WorkflowService actual stable-zero attestation is unavailable"
                )
            operation_refs = [
                deepcopy(item["operation_ref"]) for item in group_terminals
            ]
            attestation = validate_benchmark_v2_actual_operations_stable_zero(
                attest(operation_refs=deepcopy(operation_refs))
            )
            if attestation["operation_refs"] != operation_refs:
                raise ValueError(
                    "benchmark actual cleanup attestation operation lineage differs"
                )
            attestations.append(attestation)
        else:
            for terminal in group_terminals:
                operation = terminal["operation_ref"]
                cleanup = terminal["cleanup_refs"]
                completed_without_inline_cleanup = (
                    operation["mode"] == "hybrid_v1_1"
                    and operation["status"] == "complete"
                    and cleanup
                    == {"worker_cleanup_ref": None, "provider_cleanup_ref": None}
                )
                if completed_without_inline_cleanup:
                    if not callable(attest_completed_hybrid):
                        raise RuntimeError(
                            "WorkflowService completed Hybrid cleanup attestation is unavailable"
                        )
                    completed_cleanup = (
                        validate_benchmark_v2_actual_completed_hybrid_cleanup(
                            attest_completed_hybrid(
                                operation_ref=deepcopy(operation)
                            )
                        )
                    )
                    if completed_cleanup["operation_ref"] != operation:
                        raise ValueError(
                            "benchmark actual completed Hybrid cleanup lineage differs"
                        )
                    completed_hybrid_cleanups.append(completed_cleanup)
                    continue
                _validate_partial_actual_terminal_cleanup(terminal)
                partial_terminals.append(terminal)
        terminals.extend(group_terminals)
    return (
        terminals,
        attestations,
        pre_reservation_recoveries,
        completed_hybrid_cleanups,
        partial_terminals,
        unresolved_operations,
    )


def _validate_actual_incumbent_step(
    value: object,
    *,
    provider_case_ref: Mapping[str, object],
    binding: Mapping[str, object],
    expected_operation: Mapping[str, object] | None,
) -> dict[str, Any]:
    step = validate_benchmark_v2_workflow_service_step(value)
    operation = step["operation_ref"]
    request_ref = {
        "id": str(provider_case_ref["case_id"]),
        "content_sha256": str(provider_case_ref["case_content_sha256"]),
    }
    if (
        operation["mode"] != "incumbent_qwen_only"
        or operation["stage"] != binding["stage"]
        or operation["window_binding_ref"] != binding["window_binding_ref"]
        or operation["capture_ref"] != binding["capture_ref"]
        or operation["request_ref"] != request_ref
    ):
        raise ValueError("benchmark actual incumbent service step lineage is stale")
    if expected_operation is not None and any(
        operation[name] != expected_operation[name]
        for name in (
            "mode",
            "run_id",
            "stage",
            "operation_id",
            "request_ref",
            "window_binding_ref",
            "capture_ref",
        )
    ):
        raise ValueError("benchmark actual incumbent child operation identity is stale")
    return step


def _sealed_record(value: Mapping[str, object]) -> dict[str, Any]:
    result = deepcopy(dict(value))
    result["content_sha256"] = content_sha256(result)
    return result


def _write_create_only_json(
    path: Path, value: Mapping[str, object]
) -> dict[str, Any]:
    target = Path(path)
    if not target.is_absolute() or target != target.resolve():
        raise ValueError("benchmark actual artifact path must be canonical")
    record = _sealed_parent(value, name="benchmark actual durable record")
    raw = canonical_json_bytes(record, pretty=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(target, flags)
    except FileExistsError:
        existing = _read_canonical_json(target, name="benchmark actual durable record")
        if existing != record:
            raise ValueError("benchmark actual artifact has a different-content replay")
        with target.open("rb+") as stream:
            os.fsync(stream.fileno())
        return existing
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("benchmark actual artifact short write")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    existing = _read_canonical_json(target, name="benchmark actual durable record")
    if existing != record:
        raise ValueError("benchmark actual durable record differs after fsync")
    return existing


def _read_canonical_json(path: Path, *, name: str) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{name} is not canonical UTF-8 JSON") from error
    if not isinstance(decoded, Mapping) or canonical_json_bytes(decoded, pretty=True) != raw:
        raise ValueError(f"{name} is not canonical")
    return deepcopy(dict(decoded))


def _actual_group_ref(group: Mapping[str, object]) -> dict[str, str]:
    return {
        "id": str(group["screen_group"]),
        "content_sha256": str(group["content_sha256"]),
    }


def _read_actual_service_result(
    path: Path,
    *,
    intent_ref: Mapping[str, object],
    group: Mapping[str, object],
    binding: Mapping[str, object],
) -> dict[str, Any] | None:
    if not Path(path).exists():
        return None
    record = _sealed_parent(
        _read_canonical_json(path, name="benchmark actual service result"),
        name="benchmark actual service result",
    )
    if (
        set(record)
        != {
            "contract_version",
            "intent_ref",
            "provider_group_ref",
            "service_step",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        or record["contract_version"] != _ACTUAL_RESULT_CONTRACT
        or record["intent_ref"] != intent_ref
        or record["provider_group_ref"] != _actual_group_ref(group)
        or record["artifact_is_authorization"] is not False
        or record["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark actual service result lineage is stale")
    step = validate_benchmark_v2_workflow_service_step(record["service_step"])
    _validate_actual_service_step(step, group=group, binding=binding)
    return record


def _validate_actual_service_step(
    step: Mapping[str, object],
    *,
    group: Mapping[str, object],
    binding: Mapping[str, object],
) -> None:
    operation = validate_benchmark_v2_workflow_service_operation_ref(
        step["operation_ref"]
    )
    if operation["mode"] != "hybrid_v1_1":
        raise ValueError("benchmark actual service start mode is stale")
    _validate_probe_operation_lineage(
        operation=operation,
        binding=binding,
        request_ref=group["request_ref"],
    )


def _validate_actual_terminal_successor(
    *,
    terminal: Mapping[str, object],
    supplied: Mapping[str, object],
) -> None:
    returned = validate_benchmark_v2_workflow_service_operation_ref(terminal)
    current = validate_benchmark_v2_workflow_service_operation_ref(supplied)
    immutable = (
        "mode",
        "run_id",
        "stage",
        "operation_id",
        "request_ref",
        "window_binding_ref",
        "capture_ref",
        "worker_ref",
    )
    if any(returned[name] != current[name] for name in immutable):
        raise ValueError("benchmark actual cleanup full operation lineage is stale")
    if current["status"] in {"complete", "cancelled", "safe_stopped"}:
        if returned != current:
            raise ValueError("benchmark actual cleanup terminal replay differs")
        return
    if returned["content_sha256"] == current["content_sha256"]:
        if returned != current:
            raise ValueError("benchmark actual cleanup same-ref replay differs")
        return
    if (
        returned["predecessor_content_sha256"] != current["content_sha256"]
        or returned["workflow_state_ref"]["revision"]
        <= current["workflow_state_ref"]["revision"]
        or returned["stage_execution_ref"]["revision"]
        <= current["stage_execution_ref"]["revision"]
    ):
        raise ValueError("benchmark actual cleanup successor lineage is stale")


def _validate_partial_actual_terminal_cleanup(
    value: Mapping[str, object],
) -> dict[str, Any]:
    terminal = _validate_service_terminal(value)
    operation = validate_benchmark_v2_workflow_service_operation_ref(
        terminal["operation_ref"]
    )
    worker = operation["worker_ref"]
    cleanup = terminal["cleanup_refs"]
    worker_cleanup = cleanup.get("worker_cleanup_ref")
    provider_cleanup = cleanup.get("provider_cleanup_ref")
    if not isinstance(worker_cleanup, Mapping) or not isinstance(
        provider_cleanup, Mapping
    ):
        raise ValueError("partial actual terminal cleanup proof is unavailable")
    worker_kind, _ = _validate_cleanup_parent_semantics(
        worker_cleanup, name="partial actual worker cleanup"
    )
    provider_kind, _ = _validate_cleanup_parent_semantics(
        provider_cleanup, name="partial actual provider cleanup"
    )
    if worker_kind != "worker_cleanup" or provider_kind != "provider_cleanup":
        raise ValueError("partial actual terminal cleanup kind is stale")
    if (
        provider_cleanup.get("contract_version")
        == "benchmark_v2_hybrid_no_provider_cleanup_ref_v1"
    ):
        if (
            terminal.get("status") != "safe_stopped"
            or terminal.get("observed_task_kind")
            != "panel_learning_hybrid_review_projection"
            or operation.get("mode") != "hybrid_v1_1"
            or worker_cleanup.get("contract_version")
            != "benchmark_v2_hybrid_worker_cleanup_ref_v1"
            or provider_cleanup.get("worker_cleanup_ref")
            != {"content_sha256": worker_cleanup.get("content_sha256")}
            or provider_cleanup.get("cancellation_backend_termination")
            != worker_cleanup.get("backend_compute_termination")
            or provider_cleanup.get("cancellation_model_request_termination")
            != worker_cleanup.get("model_service_compute_termination")
        ):
            raise ValueError(
                "partial actual review no-provider cleanup lineage is stale"
            )
    operation_identity = ("run_id", "stage", "operation_id")
    worker_identity = ("worker_id", "model_request_id", "payload_sha256")
    if any(
        worker_cleanup.get(name) != operation[name]
        for name in operation_identity
    ) or any(
        provider_cleanup.get(name) != operation[name]
        for name in operation_identity
    ):
        raise ValueError("partial actual terminal cleanup operation is stale")
    if worker_cleanup.get("worker_id") != worker["worker_id"] or any(
        provider_cleanup.get(name) != worker[name] for name in worker_identity
    ):
        raise ValueError("partial actual terminal cleanup worker is stale")
    worker_contract = worker_cleanup.get("contract_version")
    if worker_contract in {
        "benchmark_v2_hybrid_worker_cleanup_ref_v1",
        "benchmark_v2_hybrid_completed_worker_cleanup_ref_v1",
    } and any(
        worker_cleanup.get(name) != worker[name] for name in worker_identity
    ):
        raise ValueError("partial actual Hybrid worker cleanup is stale")
    if (
        worker_contract == "benchmark_v2_hybrid_completed_worker_cleanup_ref_v1"
        and worker_cleanup.get("provider_cleanup_ref")
        != {"content_sha256": provider_cleanup["content_sha256"]}
    ):
        raise ValueError(
            "partial actual completed worker provider cleanup is stale"
        )
    return terminal


def _validate_actual_projection(
    value: object,
    *,
    group: Mapping[str, object],
    lifecycle_ref: Mapping[str, object],
) -> dict[str, Any]:
    projection = _sealed_parent(value, name="benchmark actual screen-group projection")
    if (
        projection.get("contract_version")
        != "benchmark_v2_actual_screen_group_projection_v1"
        or projection.get("partition") != group["partition"]
        or projection.get("screen_group") != group["screen_group"]
        or projection.get("request_ref") != group["request_ref"]
        or projection.get("lifecycle_ref") != lifecycle_ref
        or projection.get("artifact_is_authorization") is not False
        or projection.get("execute_binding_enabled") is not False
    ):
        raise ValueError("benchmark actual screen-group projection lineage is stale")
    stable = _sealed_parent(lifecycle_ref, name="benchmark actual lifecycle ref")
    if projection.get("window_close_ref") != stable.get("window_close_ref"):
        raise ValueError("benchmark actual projection cleanup lineage is stale")
    if projection.get("execution_refs") != stable.get("execution_refs"):
        raise ValueError("benchmark actual projection execution lineage is stale")
    _validate_pre_vista_evidence(
        projection.get("pre_vista_evidence"),
        group=group,
    )
    rows = projection.get("rows")
    expected_pairs = {
        (str(case["case_id"]), arm)
        for case in group["case_refs"]
        for arm in (
            "qwen_only",
            "omni_only_discovery",
            "omni_to_qwen",
            "omni_to_qwen_vista",
        )
    }
    if not isinstance(rows, list) or len(rows) != 20:
        raise ValueError("benchmark actual projection target multiset is incomplete")
    observed_pairs: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("case_ref"), Mapping):
            raise ValueError("benchmark actual projection row is invalid")
        observed_pairs.add((str(row["case_ref"].get("case_id")), str(row.get("arm_id"))))
        observation = row.get("observation")
        receipts = (
            observation.get("provider_dispatch_receipt_refs")
            if isinstance(observation, Mapping)
            else None
        )
        if not isinstance(receipts, list) or not receipts:
            raise ValueError("benchmark actual projection dispatch evidence is missing")
        for receipt in receipts:
            if (
                not isinstance(receipt, Mapping)
                or not isinstance(receipt.get("provider"), str)
                or not isinstance(receipt.get("content_sha256"), str)
                or len(str(receipt["content_sha256"])) != 64
            ):
                raise ValueError("benchmark actual projection dispatch evidence is invalid")
    if observed_pairs != expected_pairs:
        raise ValueError("benchmark actual projection target multiset is stale")
    return projection


def _validate_pre_vista_evidence(
    value: object,
    *,
    group: Mapping[str, object],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PRE_VISTA_EVIDENCE_FIELDS:
        raise ValueError("benchmark actual pre-VISTA evidence shape is invalid")
    evidence = _sealed_parent(value, name="benchmark actual pre-VISTA evidence")
    if evidence["contract_version"] != _PRE_VISTA_EVIDENCE_CONTRACT:
        raise ValueError("benchmark actual pre-VISTA evidence contract is stale")
    expected_group_ref = {
        "id": str(group["screen_group"]),
        "content_sha256": str(group["content_sha256"]),
    }
    if (
        not isinstance(evidence["provider_group_ref"], Mapping)
        or set(evidence["provider_group_ref"]) != _PRE_VISTA_REF_FIELDS
        or evidence["provider_group_ref"] != expected_group_ref
    ):
        raise ValueError("benchmark actual pre-VISTA provider group lineage is stale")
    if evidence["safety"] != _PRE_VISTA_SAFETY:
        raise ValueError("benchmark actual pre-VISTA evidence safety is invalid")

    _validate_pre_vista_envelope(
        evidence["omni_inventory_envelope"],
        name="Omni inventory",
        id_prefix="omni-inventory",
        domain=b"benchmark-v2-omni-inventory\0",
    )
    _validate_pre_vista_envelope(
        evidence["qwen_bindings_envelope"],
        name="Qwen bindings",
        id_prefix="qwen-bindings",
        domain=b"benchmark-v2-qwen-bindings\0",
    )
    fusion = _validate_pre_vista_envelope(
        evidence["fusion_result_envelope"],
        name="fusion result",
        id_prefix="fusion-result",
        domain=b"benchmark-v2-fusion-result\0",
    )
    raw_requests = evidence["submitted_vista_request_envelopes"]
    if not isinstance(raw_requests, list):
        raise ValueError("benchmark actual pre-VISTA request envelopes are invalid")
    requests = [
        _validate_pre_vista_envelope(
            item,
            name="submitted VISTA request",
            id_prefix="submitted-vista-request",
            domain=b"benchmark-v2-submitted-vista-request\0",
        )
        for item in raw_requests
    ]
    _validate_pre_vista_request_coverage(fusion=fusion, requests=requests)
    return evidence


def _validate_pre_vista_envelope(
    value: object,
    *,
    name: str,
    id_prefix: str,
    domain: bytes,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PRE_VISTA_ENVELOPE_FIELDS:
        raise ValueError(f"benchmark actual pre-VISTA {name} envelope is invalid")
    ref = value["ref"]
    encoded = value["canonical_bytes_b64"]
    if not isinstance(ref, Mapping) or set(ref) != _PRE_VISTA_REF_FIELDS:
        raise ValueError(f"benchmark actual pre-VISTA {name} ref is invalid")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError(f"benchmark actual pre-VISTA {name} bytes are invalid")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ValueError(
            f"benchmark actual pre-VISTA {name} bytes are invalid"
        ) from None
    if (
        len(raw) > int(_SAFE_LIMITS["max_json_bytes"])
        or base64.b64encode(raw).decode("ascii") != encoded
    ):
        raise ValueError(f"benchmark actual pre-VISTA {name} bytes are invalid")
    try:
        decoded = json.loads(raw.decode("utf-8"))
        if canonical_json_bytes(decoded) != raw:
            raise ValueError
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise ValueError(
            f"benchmark actual pre-VISTA {name} bytes are not compact canonical JSON"
        ) from None
    if not isinstance(decoded, dict):
        raise ValueError(f"benchmark actual pre-VISTA {name} must decode to an object")
    _validate_pathless_exact_json(decoded, name=name)
    expected_content_sha = sha256(raw).hexdigest()
    expected_ref_id = f"{id_prefix}/{sha256(domain + raw).hexdigest()}"
    if ref != {
        "id": expected_ref_id,
        "content_sha256": expected_content_sha,
    }:
        raise ValueError(f"benchmark actual pre-VISTA {name} ref is stale")
    return deepcopy(decoded)


def _validate_pathless_exact_json(value: object, *, name: str) -> None:
    if type(value) is dict:
        for key, nested in value.items():
            if type(key) is not str:
                raise ValueError(
                    f"benchmark actual pre-VISTA {name} requires JSON string keys"
                )
            _validate_pathless_exact_json(nested, name=name)
        return
    if type(value) is list:
        for nested in value:
            _validate_pathless_exact_json(nested, name=name)
        return
    if isinstance(value, str):
        lowered = value.casefold()
        if (
            Path(value).is_absolute()
            or value.startswith(("/", "\\"))
            or lowered.startswith("file:")
        ):
            raise ValueError(f"benchmark actual pre-VISTA {name} contains an absolute path")
        return
    if value is not None and type(value) not in {int, bool, float}:
        raise ValueError(f"benchmark actual pre-VISTA {name} contains a non-JSON value")


def _validate_pre_vista_request_coverage(
    *,
    fusion: Mapping[str, object],
    requests: list[Mapping[str, object]],
) -> None:
    candidates = fusion.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("benchmark actual pre-VISTA fusion candidates are missing")
    bound_ids: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("benchmark actual pre-VISTA fusion candidate is invalid")
        if candidate.get("state") == "BOUND":
            candidate_id = candidate.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise ValueError("benchmark actual pre-VISTA BOUND candidate is invalid")
            bound_ids.append(candidate_id)
    request_ids: list[str] = []
    for request in requests:
        candidate_id = request.get("candidate_id")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or request.get("submission_status") != "SUBMITTED"
        ):
            raise ValueError("benchmark actual pre-VISTA submitted request is invalid")
        request_ids.append(candidate_id)
    if (
        len(bound_ids) != len(set(bound_ids))
        or len(request_ids) != len(set(request_ids))
        or request_ids != sorted(request_ids)
        or request_ids != sorted(bound_ids)
    ):
        raise ValueError("benchmark actual pre-VISTA request coverage is stale")


def _read_actual_projection_record(
    path: Path,
    *,
    attempt: Mapping[str, object],
    group: Mapping[str, object],
) -> dict[str, Any] | None:
    if not Path(path).exists():
        return None
    record = _sealed_parent(
        _read_canonical_json(path, name="benchmark actual projection record"),
        name="benchmark actual projection record",
    )
    if (
        set(record)
        != {
            "contract_version",
            "attempt_ref",
            "provider_group_ref",
            "projection",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        or record["contract_version"] != _ACTUAL_PROJECTION_RECORD_CONTRACT
        or record["attempt_ref"] != attempt
        or record["provider_group_ref"] != _actual_group_ref(group)
        or record["artifact_is_authorization"] is not False
        or record["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark actual projection has a different-content replay")
    projection = _sealed_parent(
        record["projection"], name="benchmark actual recorded projection"
    )
    if (
        projection.get("screen_group") != group["screen_group"]
        or projection.get("partition") != group["partition"]
        or projection.get("request_ref") != group["request_ref"]
    ):
        raise ValueError("benchmark actual projection replay lineage is stale")
    return _validate_actual_projection(
        projection,
        group=group,
        lifecycle_ref=projection.get("lifecycle_ref"),
    )


def _sealed_parent(value: Mapping[str, object], *, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must be a sealed object")
    result = deepcopy(dict(value))
    digest = result.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{name} content SHA is invalid")
    if len(result) > 1 and content_sha256(result) != digest:
        raise ValueError(f"{name} content SHA differs")
    return result


def _runtime_sealed_parent(
    value: Mapping[str, object], *, name: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must be a sealed object")
    result = deepcopy(dict(value))
    digest = result.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{name} content SHA is invalid")
    if len(result) > 1 and runtime_content_sha256(result) != digest:
        raise ValueError(f"{name} content SHA differs")
    return result


def _benchmark_v2_attempt_journal_path(
    *, project_root: Path, attempt_ref: Mapping[str, object]
) -> Path:
    attempt = _sealed_parent(attempt_ref, name="attempt ref")
    return (
        Path(project_root).resolve()
        / "runtime_state"
        / "benchmark-v2-attempts"
        / f"{attempt['content_sha256']}.jsonl"
    ).resolve()


def _benchmark_v2_dispatch_journal_path_for_operation(
    *, project_root: Path, operation_ref: Mapping[str, object]
) -> Path:
    operation = validate_benchmark_v2_workflow_service_operation_ref(operation_ref)
    key = content_sha256(
        {
            "run_id": operation["run_id"],
            "stage": operation["stage"],
            "operation_id": operation["operation_id"],
        }
    )
    return (
        Path(project_root).resolve()
        / "runtime_state"
        / "benchmark-v2-provider-dispatch"
        / f"{key}.jsonl"
    ).resolve()


def _runtime_resource_ref(kind: str, value: Mapping[str, object]) -> dict[str, Any]:
    normalized_kind = str(kind or "").strip()
    if not normalized_kind or not isinstance(value, Mapping):
        raise ValueError("benchmark runtime resource is invalid")
    body: dict[str, Any] = {
        "contract_version": "benchmark_v2_runtime_resource_ref_v1",
        "resource_kind": normalized_kind,
        "value": deepcopy(dict(value)),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return body


def _runtime_process_identity_projection(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {"pid", "create_time_ns"}:
        raise ValueError("benchmark runtime process identity is invalid")
    pid = value.get("pid")
    create_time_ns = value.get("create_time_ns")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or isinstance(create_time_ns, bool)
        or not isinstance(create_time_ns, int)
        or create_time_ns <= 0
    ):
        raise ValueError("benchmark runtime process identity is invalid")
    return {
        "pid": pid,
        "create_time_ns_decimal": str(create_time_ns),
    }


def _runtime_resource_value(
    event: Mapping[str, object], *, expected_kind: str
) -> dict[str, Any] | None:
    resource = event.get("resource_ref")
    if not isinstance(resource, Mapping):
        return None
    fields = {
        "contract_version",
        "resource_kind",
        "value",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if set(resource) != fields or (
        resource.get("contract_version") != "benchmark_v2_runtime_resource_ref_v1"
        or resource.get("resource_kind") != expected_kind
        or resource.get("artifact_is_authorization") is not False
        or resource.get("execute_binding_enabled") is not False
        or resource.get("content_sha256") != content_sha256(resource)
        or not isinstance(resource.get("value"), Mapping)
    ):
        raise ValueError("benchmark runtime resource lineage is invalid")
    return deepcopy(dict(resource["value"]))


def _event_ref(event: Mapping[str, object]) -> dict[str, Any]:
    return _sealed_parent(event, name="attempt event")


def _content_ref(value: Mapping[str, object], *, name: str) -> dict[str, Any]:
    return _sealed_parent(value, name=name)


def _cleanup_parent_ref(
    value: Mapping[str, object], *, parent_kind: str, name: str
) -> dict[str, Any]:
    if parent_kind not in {
        "workflow_service_terminal",
        "window_cleanup",
        "worker_cleanup",
        "provider_cleanup",
        "actual_operations_stable_zero",
        "actual_operations_stable_zero_aggregate",
        "actual_operations_cleanup_aggregate",
        "actual_completed_hybrid_cleanup",
    }:
        raise ValueError("benchmark cleanup parent kind is invalid")
    producer = (
        _runtime_sealed_parent(value, name=name)
        if parent_kind in {"worker_cleanup", "provider_cleanup"}
        else _sealed_parent(value, name=name)
    )
    inferred_kind, producer_contract = _validate_cleanup_parent_semantics(
        producer, name=name
    )
    if inferred_kind != parent_kind:
        raise ValueError("benchmark cleanup parent kind differs from producer contract")
    return seal_immutable(
        {
            "contract_version": "benchmark_v2_cleanup_parent_ref_v1",
            "parent_kind": inferred_kind,
            "producer_contract_version": producer_contract,
            "producer_content_sha256": producer["content_sha256"],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def _validate_actual_operations_cleanup_aggregate(
    value: Mapping[str, object],
) -> None:
    legacy_fields = {
        "full_group_attestation_refs",
        "pre_reservation_recovery_refs",
        "partial_workflow_terminal_refs",
    }
    fields = legacy_fields | {"completed_hybrid_cleanup_refs"}
    if not isinstance(value, Mapping) or frozenset(value) not in {
        frozenset(legacy_fields),
        frozenset(fields),
    }:
        raise ValueError("actual operations cleanup aggregate is not closed")
    full_values = value.get("full_group_attestation_refs")
    recovery_values = value.get("pre_reservation_recovery_refs")
    completed_values = value.get("completed_hybrid_cleanup_refs", [])
    partial_values = value.get("partial_workflow_terminal_refs")
    if (
        not isinstance(full_values, list)
        or not isinstance(recovery_values, list)
        or not isinstance(completed_values, list)
        or not isinstance(partial_values, list)
    ):
        raise ValueError("actual operations cleanup aggregate refs are invalid")
    if (
        not (partial_values or completed_values)
        or len(full_values)
        + len(recovery_values)
        + len(completed_values)
        + len(partial_values)
        < 2
    ):
        raise ValueError("actual operations cleanup aggregate is incomplete")

    attestations = [
        validate_benchmark_v2_actual_operations_stable_zero(item)
        for item in full_values
    ]
    recoveries = [
        validate_benchmark_v2_incumbent_pre_reservation_recovery(item)
        for item in recovery_values
    ]
    completed_cleanups = [
        validate_benchmark_v2_actual_completed_hybrid_cleanup(item)
        for item in completed_values
    ]
    partial_terminals = [
        _validate_partial_actual_terminal_cleanup(item) for item in partial_values
    ]
    producer_shas = [
        str(item["content_sha256"])
        for item in [
            *attestations,
            *recoveries,
            *completed_cleanups,
            *partial_terminals,
        ]
    ]
    if len(set(producer_shas)) != len(producer_shas):
        raise ValueError("actual operations cleanup aggregate producer is duplicated")

    operations = [
        operation
        for attestation in attestations
        for operation in attestation["operation_refs"]
    ] + [
        {
            "run_id": recovery["run_id"],
            "stage": recovery["stage"],
            "operation_id": recovery["operation_id"],
            "content_sha256": recovery["content_sha256"],
        }
        for recovery in recoveries
    ] + [
        cleanup["operation_ref"] for cleanup in completed_cleanups
    ] + [terminal["operation_ref"] for terminal in partial_terminals]
    operation_keys = [
        (operation["run_id"], operation["stage"], operation["operation_id"])
        for operation in operations
    ]
    operation_shas = [str(operation["content_sha256"]) for operation in operations]
    if len(set(operation_keys)) != len(operation_keys) or len(
        set(operation_shas)
    ) != len(operation_shas):
        raise ValueError("actual operations cleanup aggregate operation is duplicated")

    cleanup_shas = [
        str(terminal["cleanup_refs"][name]["content_sha256"])
        for terminal in partial_terminals
        for name in ("worker_cleanup_ref", "provider_cleanup_ref")
    ] + [
        str(cleanup[name]["content_sha256"])
        for cleanup in completed_cleanups
        for name in ("worker_cleanup_ref", "provider_cleanup_ref")
    ]
    if len(set(cleanup_shas)) != len(cleanup_shas):
        raise ValueError("actual operations cleanup aggregate proof is duplicated")
    completed_bindings = {
        (
            cleanup["operation_ref"]["window_binding_ref"]["content_sha256"],
            cleanup["operation_ref"]["capture_ref"]["content_sha256"],
        )
        for cleanup in completed_cleanups
    }
    if completed_cleanups and any(
        (
            recovery["window_binding_ref"]["content_sha256"],
            recovery["capture_ref"]["content_sha256"],
        )
        not in completed_bindings
        for recovery in recoveries
    ):
        raise ValueError(
            "actual operations cleanup recovery parent binding is stale"
        )


def _validate_review_no_provider_cleanup_parent(
    producer: Mapping[str, object],
) -> None:
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
    if (
        set(producer) != fields
        or producer.get("status") != "cleanup_verified"
        or producer.get("outcome")
        != "verified_review_provider_not_applicable"
        or producer.get("authority_kind")
        != "benchmark_v2_workflow_service_review_no_provider_cleanup"
        or producer.get("task_kind")
        != "panel_learning_hybrid_review_projection"
        or producer.get("provider_role") != "review"
        or producer.get("worker_status") != "completed"
        or producer.get("runtime_attached") is not False
        or producer.get("result_available") is not True
        or producer.get("result_adopted") is not True
        or producer.get("continuation_phase") != "terminal_prepared"
        or producer.get("cancellation_backend_termination")
        not in {"not_running", "terminated"}
        or producer.get("cancellation_model_request_termination")
        not in {"request_not_active", "terminated"}
        or producer.get("artifact_is_authorization") is not False
        or producer.get("execute_binding_enabled") is not False
        or not _cleanup_identity_fields_are_nonempty(producer)
        or any(
            not _is_exact_sha_ref(producer.get(name))
            for name in (
                "service_binding_ref",
                "terminal_prepared_continuation_receipt_ref",
                "worker_cleanup_ref",
            )
        )
    ):
        raise ValueError("review no-provider cleanup receipt is invalid")
    returned_worker = producer.get("returned_worker_ref")
    worker_fields = {
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
        not isinstance(returned_worker, Mapping)
        or set(returned_worker) != worker_fields
        or returned_worker.get("contract_version")
        != "benchmark_v2_workflow_service_generic_worker_ref_v1"
        or any(
            returned_worker.get(name) != producer.get(name)
            for name in identity_fields
        )
        or returned_worker.get("content_sha256") != content_sha256(returned_worker)
    ):
        raise ValueError("review no-provider cleanup returned worker is stale")
    observation = producer.get("live_absence_observation")
    observation_fields = {
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
    if (
        not isinstance(observation, Mapping)
        or set(observation) != observation_fields
        or observation.get("contract_version")
        != "benchmark_v2_hybrid_no_provider_live_absence_observation_v1"
        or observation.get("provider_role") != "review"
        or any(
            observation.get(name) != producer.get(name) for name in identity_fields
        )
        or observation.get("current_worker_ref") != returned_worker
        or observation.get("latest_operation_worker_ref") != returned_worker
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
        or producer.get("content_sha256") != content_sha256(producer)
    ):
        raise ValueError("review no-provider cleanup absence observation is stale")


def _validate_cleanup_parent_semantics(
    producer: Mapping[str, object], *, name: str
) -> tuple[str, str]:
    if producer.get("artifact_is_authorization") is True or producer.get(
        "execute_binding_enabled"
    ) is True:
        raise ValueError(f"{name} cannot authorize execution")
    contract = producer.get("contract_version")
    if contract == benchmark_v2_window_owner.CLEANUP_CONTRACT:
        benchmark_v2_window_owner._validate_event_payload(
            "cleanup_verified", producer
        )
        return "window_cleanup", str(contract)
    if contract == "benchmark_v2_actual_operations_stable_zero_v1":
        validate_benchmark_v2_actual_operations_stable_zero(producer)
        return "actual_operations_stable_zero", str(contract)
    if contract == "benchmark_v2_actual_completed_hybrid_cleanup_v1":
        validate_benchmark_v2_actual_completed_hybrid_cleanup(producer)
        return "actual_completed_hybrid_cleanup", str(contract)
    if contract == "benchmark_v2_runtime_resource_ref_v1":
        fields = {
            "contract_version",
            "resource_kind",
            "value",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        body = producer.get("value")
        if (
            set(producer) != fields
            or producer.get("artifact_is_authorization") is not False
            or producer.get("execute_binding_enabled") is not False
            or not isinstance(body, Mapping)
        ):
            raise ValueError("actual operations cleanup aggregate is invalid")
        if producer.get("resource_kind") == "actual_group_stable_zero_attestations":
            if (
                set(body) != {"group_attestation_refs"}
                or not isinstance(body.get("group_attestation_refs"), list)
                or len(body["group_attestation_refs"]) < 2
            ):
                raise ValueError("actual operations stable-zero aggregate is invalid")
            for item in body["group_attestation_refs"]:
                validate_benchmark_v2_actual_operations_stable_zero(item)
            return "actual_operations_stable_zero_aggregate", str(contract)
        if producer.get("resource_kind") == "actual_operations_cleanup_aggregate":
            _validate_actual_operations_cleanup_aggregate(body)
            return "actual_operations_cleanup_aggregate", str(contract)
        raise ValueError("actual operations cleanup aggregate is invalid")
    if contract == "benchmark_v2_hybrid_worker_cleanup_ref_v1":
        fields = {
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
        if (
            set(producer) != fields
            or producer.get("backend_compute_termination")
            not in {"not_running", "terminated"}
            or producer.get("model_service_compute_termination")
            not in {"request_not_active", "terminated"}
            or producer.get("artifact_is_authorization") is not False
            or producer.get("execute_binding_enabled") is not False
            or not _cleanup_identity_fields_are_nonempty(producer)
            or not _is_exact_sha_ref(producer.get("cancellation_ref"))
        ):
            raise ValueError("Hybrid worker cleanup receipt is invalid")
        return "worker_cleanup", str(contract)
    if contract == "benchmark_v2_hybrid_completed_worker_cleanup_ref_v1":
        fields = {
            "contract_version",
            "run_id",
            "stage",
            "operation_id",
            "worker_id",
            "model_request_id",
            "payload_sha256",
            "worker_status",
            "runtime_attached",
            "result_available",
            "authoritative_worker_record_sha256",
            "provider_cleanup_ref",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        if (
            set(producer) != fields
            or producer.get("worker_status") != "completed"
            or producer.get("runtime_attached") is not False
            or producer.get("result_available") is not True
            or producer.get("artifact_is_authorization") is not False
            or producer.get("execute_binding_enabled") is not False
            or not _cleanup_identity_fields_are_nonempty(producer)
            or not _is_sha(producer.get("authoritative_worker_record_sha256"))
            or not _is_exact_sha_ref(producer.get("provider_cleanup_ref"))
        ):
            raise ValueError("completed Hybrid worker cleanup receipt is invalid")
        return "worker_cleanup", str(contract)
    if contract == "benchmark_worker_cleanup_receipt_v1":
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
        outcome = producer.get("outcome")
        if (
            set(producer) != fields
            or outcome not in {"verified_not_launched", "verified_exact_worker_exited"}
            or producer.get("artifact_is_authorization") is not False
            or producer.get("execute_binding_enabled") is not False
            or not all(
                isinstance(producer.get(field), str) and producer.get(field)
                for field in ("run_id", "stage", "operation_id", "worker_id")
            )
            or not _is_exact_sha_ref(producer.get("operation_anchor_ref"))
            or not _is_exact_sha_ref(producer.get("reservation_ref"))
        ):
            raise ValueError("incumbent worker cleanup receipt is invalid")
        if outcome == "verified_not_launched":
            absent_fields = (
                "supervision_ref",
                "process_identity",
                "assignment_proven_ref",
                "finalization_intent_ref",
                "exact_handle_observation_refs",
                "job_absence_observation_ref",
                "worker_absence_observation_ref",
                "supervisor_absence_observation_ref",
            )
            if any(producer.get(field) is not None for field in absent_fields) or not (
                _is_exact_sha_ref(producer.get("reservation_abort_ref"))
            ):
                raise ValueError("incumbent not-launched cleanup receipt is invalid")
        elif (
            not _is_exact_sha_ref(producer.get("supervision_ref"))
            or not isinstance(producer.get("process_identity"), Mapping)
            or not _is_exact_sha_ref(producer.get("assignment_proven_ref"))
            or not _is_exact_sha_ref(producer.get("finalization_intent_ref"))
            or not isinstance(producer.get("exact_handle_observation_refs"), Mapping)
            or not _is_exact_sha_ref(producer.get("job_absence_observation_ref"))
            or not _is_exact_sha_ref(producer.get("worker_absence_observation_ref"))
            or producer.get("reservation_abort_ref") is not None
        ):
            raise ValueError("incumbent exited worker cleanup receipt is invalid")
        return "worker_cleanup", str(contract)
    if contract == "benchmark_v2_hybrid_no_provider_cleanup_ref_v1":
        _validate_review_no_provider_cleanup_parent(producer)
        return "provider_cleanup", str(contract)
    if contract == "benchmark_provider_cleanup_ref_v1":
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
        outcome = producer.get("outcome")
        if outcome == "verified_exact_process_exited":
            evidence_ref_name = "cleanup_receipt_ref"
        elif outcome == "verified_not_acquired" and set(producer) == (
            common_fields | {"provider", "task_kind", "recovered_lease_ref"}
        ):
            evidence_ref_name = "recovered_lease_ref"
        else:
            evidence_ref_name = "cleanup_receipt_ref"
        if (
            set(producer)
            != common_fields
            | (
                {"provider", "task_kind", evidence_ref_name}
                if evidence_ref_name == "recovered_lease_ref"
                else {evidence_ref_name}
            )
            or producer.get("status") != "cleanup_verified"
            or outcome
            not in {"verified_not_acquired", "verified_exact_process_exited"}
            or not all(
                isinstance(producer.get(field), str) and producer.get(field)
                for field in (
                    "authority_kind",
                    "run_id",
                    "stage",
                    "operation_id",
                    "worker_id",
                    "model_request_id",
                    "payload_sha256",
                )
            )
            or any(
                not _is_exact_sha_ref(producer.get(field))
                for field in (
                    "reservation_ref",
                    "acquisition_owner_ref",
                    "acquisition_intent_ref",
                    "runtime_owner_ref",
                    evidence_ref_name,
                )
            )
            or (
                evidence_ref_name == "recovered_lease_ref"
                and (
                    producer.get("authority_kind")
                    != "benchmark_v2_workflow_service_dispatch_cleanup"
                    or producer.get("provider") != "vista"
                    or producer.get("task_kind")
                    != "panel_learning_calibration_sequence"
                    or producer.get("reservation_ref")
                    != producer.get("acquisition_intent_ref")
                )
            )
        ):
            raise ValueError("provider cleanup receipt is invalid")
        return "provider_cleanup", str(contract)
    if contract == BENCHMARK_V2_WORKFLOW_SERVICE_STEP_CONTRACT:
        step = validate_benchmark_v2_workflow_service_step(producer)
        _validate_service_terminal(step)
        return "workflow_service_terminal", str(contract)
    terminal_fields = {
        "status",
        "operation_ref",
        "provider_dispatch_context_projection",
        "cleanup_refs",
        "content_sha256",
    }
    if contract is None and set(producer) == terminal_fields:
        _validate_service_terminal(producer)
        return (
            "workflow_service_terminal",
            "benchmark_v2_workflow_service_terminal_result_v1",
        )
    raise ValueError(f"{name} producer contract is unsupported")


def _is_exact_sha_ref(value: object) -> bool:
    digest = value.get("content_sha256") if isinstance(value, Mapping) else None
    return (
        isinstance(value, Mapping)
        and set(value) == {"content_sha256"}
        and isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
    )


def _is_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _cleanup_identity_fields_are_nonempty(value: Mapping[str, object]) -> bool:
    return all(
        isinstance(value.get(field), str) and value.get(field)
        for field in (
            "run_id",
            "stage",
            "operation_id",
            "worker_id",
            "model_request_id",
            "payload_sha256",
        )
    )


def _service_operation_resource(
    *,
    operation: Mapping[str, object],
    binding: Mapping[str, object],
    screen_group: Mapping[str, object],
) -> dict[str, Any]:
    current = validate_benchmark_v2_workflow_service_operation_ref(operation)
    window = validate_benchmark_v2_workflow_window_binding(binding)
    group = validate_benchmark_v2_hybrid_screen_group_start(screen_group)
    _validate_probe_operation_lineage(
        operation=current,
        binding=window,
        request_ref=group["request_ref"],
    )
    return _runtime_resource_ref(
        "workflow_service_operation",
        {
            "operation_ref": current,
            "window_binding": window,
            "screen_group_ref": {
                "id": str(group["screen_group"]),
                "content_sha256": str(group["content_sha256"]),
            },
        },
    )


def _identity_ref(value: object, *, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "content_sha256"}:
        raise ValueError(f"{name} must be an exact identity ref")
    identifier = value.get("id")
    digest = value.get("content_sha256")
    if (
        not isinstance(identifier, str)
        or not identifier
        or not isinstance(digest, str)
        or len(digest) != 64
    ):
        raise ValueError(f"{name} identity is invalid")
    return {"id": identifier, "content_sha256": digest}


def _probe_provider(value: object) -> str:
    provider = str(value or "").strip().lower()
    if provider not in _PROBE_TARGET_TASKS:
        raise ValueError("benchmark probe provider must be omni, qwen, or vista")
    return provider


def _probe_kind(value: object) -> str:
    kind = str(value or "").strip().lower()
    if kind not in _PROBE_KINDS:
        raise ValueError("benchmark probe kind must be cancel or timeout")
    return kind


def _validate_probe_context(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PROBE_CONTEXT_FIELDS:
        raise ValueError("benchmark probe context is not closed")
    context = deepcopy(dict(value))
    if (
        context["contract_version"] != _PROBE_CONTEXT_CONTRACT
        or context["artifact_is_authorization"] is not False
        or context["execute_binding_enabled"] is not False
        or context["content_sha256"] != content_sha256(context)
    ):
        raise ValueError("benchmark probe context is invalid")
    context["attempt_ref"] = _sealed_parent(
        context["attempt_ref"], name="probe attempt ref"
    )
    context["provider_id"] = _probe_provider(context["provider_id"])
    context["probe_kind"] = _probe_kind(context["probe_kind"])
    context["operation_ref"] = validate_benchmark_v2_workflow_service_operation_ref(
        context["operation_ref"]
    )
    context["provider_dispatch_context_projection"] = (
        validate_benchmark_v2_provider_dispatch_context_projection(
            context["provider_dispatch_context_projection"]
        )
    )
    _validate_provider_context_against_service_operation(
        projection=context["provider_dispatch_context_projection"],
        provider=context["provider_id"],
        service_operation=context["operation_ref"],
    )
    for name in ("window_binding_ref", "capture_ref"):
        if context[name] != context["operation_ref"][name]:
            raise ValueError(f"benchmark probe {name} lineage is stale")
    context["screen_group_ref"] = _identity_ref(
        context["screen_group_ref"], name="probe screen group ref"
    )
    context["service_event_ref"] = _sealed_parent(
        context["service_event_ref"], name="probe service event ref"
    )
    return context


def _validate_probe_request(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PROBE_REQUEST_FIELDS:
        raise ValueError("benchmark probe request journal is not closed")
    request = deepcopy(dict(value))
    if (
        request["contract_version"] != _PROBE_REQUEST_CONTRACT
        or request["request_state"] != "request_in_flight"
        or request["artifact_is_authorization"] is not False
        or request["execute_binding_enabled"] is not False
        or request["content_sha256"] != content_sha256(request)
    ):
        raise ValueError("benchmark probe request journal is invalid")
    request["attempt_ref"] = _sealed_parent(
        request["attempt_ref"], name="probe request attempt ref"
    )
    request["provider_id"] = _probe_provider(request["provider_id"])
    request["probe_kind"] = _probe_kind(request["probe_kind"])
    request["operation_ref"] = validate_benchmark_v2_workflow_service_operation_ref(
        request["operation_ref"]
    )
    request["provider_dispatch_context_projection"] = (
        validate_benchmark_v2_provider_dispatch_context_projection(
            request["provider_dispatch_context_projection"]
        )
    )
    _validate_provider_context_against_service_operation(
        projection=request["provider_dispatch_context_projection"],
        provider=request["provider_id"],
        service_operation=request["operation_ref"],
    )
    for name in (
        "dispatch_receipt_ref",
        "provider_runtime_attestation_ref",
        "attempt_event_ref",
    ):
        request[name] = _sealed_parent(request[name], name=f"probe request {name}")
    return request


def _read_committed_probe_dispatch_evidence(
    *,
    project_root: Path,
    provider: str,
    context_projection: Mapping[str, object],
    expected_dispatch_receipt_ref: Mapping[str, object] | None = None,
    expected_runtime_identity_ref: Mapping[str, object] | None = None,
) -> dict[str, Any] | None:
    root = Path(project_root).resolve()
    if Path(benchmark_v2_dispatch_attestation.PROJECT_ROOT).resolve() != root:
        raise ValueError("benchmark dispatch fixed root differs from probe runtime")
    projection = validate_benchmark_v2_provider_dispatch_context_projection(
        context_projection
    )
    if projection["provider"] != provider:
        raise ValueError("benchmark probe dispatch context provider is stale")
    operation = projection["operation_ref"]
    journal_path = benchmark_v2_dispatch_attestation._fixed_dispatch_journal_path(
        operation
    )
    records = benchmark_v2_dispatch_attestation._read_committed_dispatch_records(
        journal_path
    )
    matches = [
        receipt
        for receipt in records
        if receipt["provider"] == provider and receipt["operation_ref"] == operation
    ]
    if not matches:
        return None
    if len(matches) != 1 or matches[0]["dispatch_index"] != 1:
        raise ValueError("benchmark probe did not observe one committed first dispatch")
    receipt = matches[0]
    if receipt["predecessor_content_sha256"] != projection["context_content_sha256"]:
        raise ValueError("benchmark probe first dispatch predecessor context is stale")
    if expected_dispatch_receipt_ref is not None and receipt["content_sha256"] != _sealed_parent(
        expected_dispatch_receipt_ref, name="probe trigger expected dispatch receipt"
    )["content_sha256"]:
        raise ValueError("benchmark probe dispatch receipt differs from request")
    if (
        expected_runtime_identity_ref is not None
        and receipt["provider_runtime_attestation_ref"]
        != _sealed_parent(
            expected_runtime_identity_ref,
            name="probe trigger expected runtime identity",
        )
    ):
        raise ValueError("benchmark probe runtime identity differs from request")
    parent_path = benchmark_v2_dispatch_attestation._dispatch_artifact_path(
        operation, provider, 1, "runtime-parent"
    )
    marker_path = benchmark_v2_dispatch_attestation._dispatch_artifact_path(
        operation, provider, 1, "commit-marker"
    )
    parent = benchmark_v2_dispatch_attestation._read_canonical_artifact(
        parent_path,
        benchmark_v2_dispatch_attestation._validate_dispatch_runtime_parent,
        "benchmark dispatch runtime parent",
    )
    marker = benchmark_v2_dispatch_attestation._read_canonical_artifact(
        marker_path,
        benchmark_v2_dispatch_attestation._validate_dispatch_commit_marker,
        "benchmark dispatch commit marker",
    )
    if (
        parent["provider"] != provider
        or parent["operation_ref"] != operation
        or parent["dispatch_receipt_ref"] != {"content_sha256": receipt["content_sha256"]}
        or receipt["provider_runtime_attestation_ref"]
        != {"content_sha256": parent["runtime_identity"]["content_sha256"]}
        or marker["provider"] != provider
        or marker["operation_ref"] != operation
        or marker["dispatch_receipt_ref"] != parent["dispatch_receipt_ref"]
        or marker["runtime_parent_ref"] != {"content_sha256": parent["content_sha256"]}
    ):
        raise ValueError("benchmark probe committed dispatch joins differ")
    return {"receipt": receipt, "runtime_parent": parent}


def _exact_ordered_process_identities(
    dispatch_runtime_parent: Mapping[str, object],
) -> list[dict[str, int]]:
    parent = _sealed_parent(
        dispatch_runtime_parent,
        name="probe trigger dispatch runtime parent",
    )
    runtime_identity = parent.get("runtime_identity")
    if not isinstance(runtime_identity, Mapping):
        raise ValueError("benchmark probe exact process identities are unavailable")
    identities = runtime_identity.get("process_identities")
    if not isinstance(identities, list) or not identities:
        raise ValueError("benchmark probe exact process identities are unavailable")
    normalized: list[dict[str, int]] = []
    seen: set[tuple[int, int]] = set()
    for raw in identities:
        if not isinstance(raw, Mapping) or set(raw) != {"pid", "create_time_ns"}:
            raise ValueError("benchmark probe exact process identities are invalid")
        pid = raw.get("pid")
        create_time_ns = raw.get("create_time_ns")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or isinstance(create_time_ns, bool)
            or not isinstance(create_time_ns, int)
            or create_time_ns <= 0
            or (pid, create_time_ns) in seen
        ):
            raise ValueError("benchmark probe exact process identities are invalid")
        seen.add((pid, create_time_ns))
        normalized.append({"pid": pid, "create_time_ns": create_time_ns})
    return normalized


def _monotonic_clock_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("benchmark probe monotonic clock value is invalid")
    return value


def _next_probe_monotonic_observation(
    *,
    monotonic_ns: Callable[[], int],
    wait_hook: Callable[[], None],
    after: int,
) -> int:
    previous = _monotonic_clock_value(after)
    observed = _monotonic_clock_value(monotonic_ns())
    stagnant_reads = 0
    while observed <= previous:
        if observed < previous:
            raise ValueError("benchmark probe monotonic clock regressed")
        wait_hook()
        next_value = _monotonic_clock_value(monotonic_ns())
        if next_value < observed:
            raise ValueError("benchmark probe monotonic clock regressed")
        if next_value == observed:
            stagnant_reads += 1
            if stagnant_reads >= _PROBE_MAX_STAGNANT_READS:
                raise ValueError("benchmark probe monotonic clock failed to advance")
        else:
            stagnant_reads = 0
        observed = next_value
    return observed


def _collect_probe_runtime_zero_samples(
    *,
    monotonic_ns: Callable[[], int],
    wait_hook: Callable[[], None],
    resource_counts: Callable[[], Mapping[str, int]],
    after: int,
    expected_counts: Mapping[str, int],
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    previous = _monotonic_clock_value(after)
    for _ in range(3):
        observed = _next_probe_monotonic_observation(
            monotonic_ns=monotonic_ns,
            wait_hook=wait_hook,
            after=previous,
        )
        counts = dict(resource_counts())
        if counts != dict(expected_counts):
            raise ValueError(
                "benchmark probe fresh stable-zero sample observed runtime residue"
            )
        samples.append(
            {
                "observed_monotonic_ns": observed,
                "resource_counts": counts,
            }
        )
        previous = observed
    return samples


def _deadline_content_ref(value: Mapping[str, object]) -> dict[str, str]:
    digest = value.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("benchmark probe deadline expiration ref is invalid")
    return {"content_sha256": digest}


def _validate_probe_deadline_expiration(value: object) -> dict[str, Any]:
    fields = {
        "contract_version",
        "attempt_ref",
        "operation_ref",
        "request_in_flight_ref",
        "clock",
        "owner",
        "started_monotonic_ns",
        "duration_ns",
        "deadline_monotonic_ns",
        "expired_monotonic_ns",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("benchmark probe deadline expiration parent is not closed")
    expiration = deepcopy(dict(value))
    if (
        expiration["contract_version"] != _PROBE_DEADLINE_EXPIRATION_CONTRACT
        or expiration["clock"] != "time.monotonic_ns"
        or expiration["owner"] != "BenchmarkV2Runtime"
        or expiration["duration_ns"] != _PROBE_DEADLINE_DURATION_NS
        or expiration["content_sha256"] != content_sha256(expiration)
    ):
        raise ValueError("benchmark probe deadline expiration parent is invalid")
    expiration["attempt_ref"] = _sealed_parent(
        expiration["attempt_ref"], name="probe deadline attempt ref"
    )
    expiration["operation_ref"] = validate_benchmark_v2_workflow_service_operation_ref(
        expiration["operation_ref"]
    )
    expiration["request_in_flight_ref"] = _sealed_parent(
        expiration["request_in_flight_ref"], name="probe deadline request ref"
    )
    started = _monotonic_clock_value(expiration["started_monotonic_ns"])
    deadline = _monotonic_clock_value(expiration["deadline_monotonic_ns"])
    expired = _monotonic_clock_value(expiration["expired_monotonic_ns"])
    if (
        deadline != started + _PROBE_DEADLINE_DURATION_NS
        or not started < deadline <= expired
    ):
        raise ValueError("benchmark probe monotonic deadline expiration is invalid")
    return expiration


def _validate_probe_trigger_observation_resource(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "trigger_observation",
        "deadline_expiration",
    }:
        raise ValueError("benchmark probe trigger observation resource is not closed")
    raw_observation = value.get("trigger_observation")
    if not isinstance(raw_observation, Mapping) or set(raw_observation) != {
        "kind",
        "action",
        "request_in_flight_ref",
        "triggered_monotonic_ns",
        "deadline_expiration_ref",
    }:
        raise ValueError("benchmark probe trigger observation is not closed")
    observation = deepcopy(dict(raw_observation))
    kind = _probe_kind(observation["kind"])
    observation["kind"] = kind
    observation["request_in_flight_ref"] = _sealed_parent(
        observation["request_in_flight_ref"],
        name="probe trigger observation request ref",
    )
    triggered = _monotonic_clock_value(observation["triggered_monotonic_ns"])
    expiration_value = value.get("deadline_expiration")
    if kind == "cancel":
        if (
            observation["action"] != "explicit_cancel"
            or observation["deadline_expiration_ref"] is not None
            or expiration_value is not None
        ):
            raise ValueError("benchmark cancel trigger observation has deadline evidence")
        expiration = None
    else:
        if observation["action"] != "monotonic_deadline_expired":
            raise ValueError("benchmark timeout trigger observation action is invalid")
        expiration = _validate_probe_deadline_expiration(expiration_value)
        expected_ref = _deadline_content_ref(expiration)
        if observation["deadline_expiration_ref"] != expected_ref:
            raise ValueError("benchmark timeout deadline expiration ref is stale")
        if expiration["expired_monotonic_ns"] > triggered:
            raise ValueError("benchmark timeout trigger preceded monotonic expiration")
    return {
        "trigger_observation": observation,
        "deadline_expiration": expiration,
    }


def _probe_trigger_observation_from_events(
    events: list[Mapping[str, object]],
    *,
    provider_id: object,
    probe_kind: object,
    required: bool,
) -> dict[str, Any] | None:
    event = _one_probe_event_for_tuple(
        events,
        event_kind="probe_trigger_observation",
        provider_id=provider_id,
        probe_kind=probe_kind,
        required=required,
    )
    if event is None:
        return None
    value = _runtime_resource_value(
        event, expected_kind="probe_trigger_observation"
    )
    material = _validate_probe_trigger_observation_resource(value)
    material["event"] = event
    return material


def _validate_probe_trigger_observation_lineage(
    *,
    material: Mapping[str, object],
    context: Mapping[str, object],
    request: Mapping[str, object],
) -> None:
    probe_context = _validate_probe_context(context)
    in_flight = _validate_probe_request(request)
    observation = material["trigger_observation"]
    if not isinstance(observation, Mapping):
        raise ValueError("benchmark probe trigger observation is unavailable")
    if (
        observation["kind"] != probe_context["probe_kind"]
        or observation["request_in_flight_ref"]
        != _content_ref(in_flight, name="probe trigger observation request")
    ):
        raise ValueError("benchmark probe trigger observation lineage is stale")
    expiration = material.get("deadline_expiration")
    if probe_context["probe_kind"] == "timeout":
        if not isinstance(expiration, Mapping):
            raise ValueError("benchmark timeout deadline expiration is unavailable")
        if (
            expiration["attempt_ref"] != probe_context["attempt_ref"]
            or expiration["operation_ref"] != probe_context["operation_ref"]
            or expiration["request_in_flight_ref"]
            != _content_ref(in_flight, name="probe deadline request")
        ):
            raise ValueError("benchmark timeout deadline expiration lineage is stale")
    elif expiration is not None:
        raise ValueError("benchmark cancel deadline expiration must be absent")


def _compose_probe_trigger_observation(
    *,
    context: Mapping[str, object],
    request: Mapping[str, object],
    monotonic_ns: Callable[[], int],
    wait_hook: Callable[[], None],
) -> dict[str, Any]:
    probe_context = _validate_probe_context(context)
    in_flight = _validate_probe_request(request)
    if (
        in_flight["attempt_ref"] != probe_context["attempt_ref"]
        or in_flight["provider_id"] != probe_context["provider_id"]
        or in_flight["probe_kind"] != probe_context["probe_kind"]
        or in_flight["operation_ref"] != probe_context["operation_ref"]
    ):
        raise ValueError("benchmark probe trigger observation lineage is stale")
    kind = str(probe_context["probe_kind"])
    if kind == "cancel":
        expiration = None
        action = "explicit_cancel"
        triggered = _monotonic_clock_value(monotonic_ns())
        deadline_ref = None
    else:
        started = _monotonic_clock_value(monotonic_ns())
        deadline = started + _PROBE_DEADLINE_DURATION_NS
        observed = _monotonic_clock_value(monotonic_ns())
        stagnant_reads = 0
        while observed < deadline:
            if observed < started:
                raise ValueError("benchmark probe monotonic clock regressed")
            wait_hook()
            previous = observed
            observed = _monotonic_clock_value(monotonic_ns())
            if observed < previous:
                raise ValueError("benchmark probe monotonic clock regressed")
            if observed == previous:
                stagnant_reads += 1
                if stagnant_reads >= _PROBE_MAX_STAGNANT_READS:
                    raise ValueError(
                        "benchmark probe monotonic clock failed to advance"
                    )
            else:
                stagnant_reads = 0
        expired = observed
        triggered = _monotonic_clock_value(monotonic_ns())
        if triggered < expired:
            raise ValueError("benchmark probe monotonic clock regressed")
        expiration_body: dict[str, Any] = {
            "contract_version": _PROBE_DEADLINE_EXPIRATION_CONTRACT,
            "attempt_ref": deepcopy(probe_context["attempt_ref"]),
            "operation_ref": deepcopy(probe_context["operation_ref"]),
            "request_in_flight_ref": _content_ref(
                in_flight, name="probe deadline request"
            ),
            "clock": "time.monotonic_ns",
            "owner": "BenchmarkV2Runtime",
            "started_monotonic_ns": started,
            "duration_ns": _PROBE_DEADLINE_DURATION_NS,
            "deadline_monotonic_ns": deadline,
            "expired_monotonic_ns": expired,
        }
        expiration_body["content_sha256"] = content_sha256(expiration_body)
        expiration = _validate_probe_deadline_expiration(expiration_body)
        action = "monotonic_deadline_expired"
        deadline_ref = _deadline_content_ref(expiration)
    material = {
        "trigger_observation": {
            "kind": kind,
            "action": action,
            "request_in_flight_ref": _content_ref(
                in_flight, name="probe trigger observation request"
            ),
            "triggered_monotonic_ns": triggered,
            "deadline_expiration_ref": deadline_ref,
        },
        "deadline_expiration": expiration,
    }
    validated = _validate_probe_trigger_observation_resource(material)
    _validate_probe_trigger_observation_lineage(
        material=validated, context=probe_context, request=in_flight
    )
    return validated


def _compose_probe_trigger_intent(
    *,
    project_root: Path,
    context: Mapping[str, object],
    request: Mapping[str, object],
) -> dict[str, Any]:
    probe_context = _validate_probe_context(context)
    in_flight = _validate_probe_request(request)
    if (
        in_flight["attempt_ref"] != probe_context["attempt_ref"]
        or in_flight["provider_id"] != probe_context["provider_id"]
        or in_flight["probe_kind"] != probe_context["probe_kind"]
        or in_flight["operation_ref"] != probe_context["operation_ref"]
    ):
        raise ValueError("benchmark probe trigger intent lineage is stale")
    evidence = _read_committed_probe_dispatch_evidence(
        project_root=project_root,
        provider=probe_context["provider_id"],
        context_projection=probe_context["provider_dispatch_context_projection"],
        expected_dispatch_receipt_ref=in_flight["dispatch_receipt_ref"],
        expected_runtime_identity_ref=in_flight["provider_runtime_attestation_ref"],
    )
    if evidence is None:
        raise ValueError("benchmark probe committed dispatch receipt is unavailable")
    parent = evidence["runtime_parent"]
    body: dict[str, Any] = {
        "contract_version": _PROBE_TRIGGER_INTENT_CONTRACT,
        "attempt_ref": deepcopy(probe_context["attempt_ref"]),
        "provider_id": probe_context["provider_id"],
        "probe_kind": probe_context["probe_kind"],
        "operation_ref": deepcopy(probe_context["operation_ref"]),
        "request_in_flight_ref": _content_ref(
            in_flight, name="probe trigger request"
        ),
        "dispatch_receipt_ref": deepcopy(in_flight["dispatch_receipt_ref"]),
        "dispatch_runtime_parent_ref": _sealed_parent(
            parent, name="probe trigger dispatch runtime parent"
        ),
        "process_identities": _exact_ordered_process_identities(parent),
        "evidence_scope": "benchmark_probe_only_non_authorizing",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return _validate_probe_trigger_intent(body)


def _validate_probe_trigger_intent(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PROBE_TRIGGER_INTENT_FIELDS:
        raise ValueError("benchmark probe trigger intent is not closed")
    intent = deepcopy(dict(value))
    if (
        intent["contract_version"] != _PROBE_TRIGGER_INTENT_CONTRACT
        or intent["evidence_scope"] != "benchmark_probe_only_non_authorizing"
        or intent["artifact_is_authorization"] is not False
        or intent["execute_binding_enabled"] is not False
        or intent["content_sha256"] != content_sha256(intent)
    ):
        raise ValueError("benchmark probe trigger intent is invalid")
    intent["attempt_ref"] = _sealed_parent(
        intent["attempt_ref"], name="probe trigger intent attempt ref"
    )
    intent["provider_id"] = _probe_provider(intent["provider_id"])
    intent["probe_kind"] = _probe_kind(intent["probe_kind"])
    intent["operation_ref"] = validate_benchmark_v2_workflow_service_operation_ref(
        intent["operation_ref"]
    )
    for name in (
        "request_in_flight_ref",
        "dispatch_receipt_ref",
        "dispatch_runtime_parent_ref",
    ):
        intent[name] = _sealed_parent(
            intent[name], name=f"probe trigger intent {name}"
        )
    expected = _exact_ordered_process_identities(intent["dispatch_runtime_parent_ref"])
    if intent["process_identities"] != expected:
        raise ValueError("benchmark probe exact process identities are stale")
    intent["process_identities"] = expected
    return intent


def _observe_exact_process_identities_before_cancel(process_identities: object) -> None:
    if not isinstance(process_identities, list) or not process_identities:
        raise ValueError("benchmark probe process identities are unavailable")
    for expected in process_identities:
        if not isinstance(expected, Mapping) or set(expected) != {"pid", "create_time_ns"}:
            raise ValueError("benchmark probe process identity is invalid")
        pid = expected.get("pid")
        created = expected.get("create_time_ns")
        if (
            isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
            or isinstance(created, bool) or not isinstance(created, int) or created <= 0
        ):
            raise ValueError("benchmark probe process identity is invalid")
        try:
            observed = int(round(psutil.Process(pid).create_time() * 1_000_000_000))
        except (psutil.AccessDenied, psutil.Error, OSError, ValueError, TypeError) as error:
            raise ValueError("benchmark probe pre-cancel process identity is indeterminate") from error
        if abs(observed - created) > 1000:
            raise ValueError("benchmark probe pre-cancel exact process identity is stale")


def _live_absence_observations(
    process_identities: object,
) -> list[dict[str, object]]:
    if not isinstance(process_identities, list) or not process_identities:
        raise ValueError("benchmark probe process identities are unavailable")
    observations: list[dict[str, object]] = []
    seen: set[tuple[int, int]] = set()
    for expected in process_identities:
        if not isinstance(expected, Mapping) or set(expected) != {"pid", "create_time_ns"}:
            raise ValueError("benchmark probe process identity is invalid")
        pid = expected.get("pid")
        created = expected.get("create_time_ns")
        if (
            isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid <= 0
            or isinstance(created, bool)
            or not isinstance(created, int)
            or created <= 0
            or (pid, created) in seen
        ):
            raise ValueError("benchmark probe process identity is invalid")
        seen.add((pid, created))
        try:
            observed = int(round(psutil.Process(pid).create_time() * 1_000_000_000))
        except psutil.NoSuchProcess:
            outcome = "no_such_process"
        except (psutil.AccessDenied, psutil.Error, OSError, ValueError, TypeError) as error:
            raise ValueError("benchmark probe live absence is indeterminate") from error
        else:
            if abs(observed - created) <= 1000:
                raise ValueError("benchmark probe exact incarnation remains live")
            outcome = "pid_reused"
        observation: dict[str, object] = {
            "pid": pid,
            "create_time_ns": created,
            "outcome": outcome,
        }
        if outcome == "pid_reused":
            observation["observed_create_time_ns"] = observed
        observations.append(observation)
    return observations


def _persisted_probe_absence_observations(
    observations: list[dict[str, object]],
) -> list[dict[str, object]]:
    persisted: list[dict[str, object]] = []
    for observation in _validate_probe_absence_observations(
        observations, name="benchmark probe fresh"
    ):
        item = dict(observation)
        item["create_time_ns"] = str(item["create_time_ns"])
        if item["outcome"] == "pid_reused":
            item["observed_create_time_ns"] = str(item["observed_create_time_ns"])
        persisted.append(item)
    return persisted


def _validate_probe_trigger(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PROBE_TRIGGER_FIELDS:
        raise ValueError("benchmark probe trigger receipt is not closed")
    trigger = deepcopy(dict(value))
    if (
        trigger["contract_version"] != _PROBE_TRIGGER_CONTRACT
        or trigger["outcome"] != "safe_stopped_exact_incarnation_absent"
        or trigger["evidence_scope"] != "benchmark_probe_only_non_authorizing"
        or trigger["artifact_is_authorization"] is not False
        or trigger["execute_binding_enabled"] is not False
        or trigger["content_sha256"] != content_sha256(trigger)
    ):
        raise ValueError("benchmark probe trigger receipt is invalid")
    trigger["attempt_ref"] = _sealed_parent(
        trigger["attempt_ref"], name="probe trigger attempt ref"
    )
    trigger["provider_id"] = _probe_provider(trigger["provider_id"])
    trigger["probe_kind"] = _probe_kind(trigger["probe_kind"])
    for name in (
        "request_in_flight_ref",
        "trigger_intent_ref",
        "service_terminal_ref",
        "cleanup_binding_ref",
        "probe_trigger_terminal_ref",
        "attempt_event_ref",
    ):
        trigger[name] = _sealed_parent(trigger[name], name=f"probe trigger {name}")
    trigger["absence_observations"] = _validate_probe_absence_observations(
        trigger["absence_observations"], name="benchmark probe trigger"
    )
    return trigger


def _provider_context_projection_from_step(
    *,
    step: Mapping[str, object],
    provider: str,
    service_operation: Mapping[str, object],
) -> dict[str, Any]:
    value = step.get("provider_dispatch_context_projection")
    if not isinstance(value, Mapping):
        raise ValueError("benchmark target provider context projection is unavailable")
    projection = validate_benchmark_v2_provider_dispatch_context_projection(value)
    _validate_provider_context_against_service_operation(
        projection=projection,
        provider=provider,
        service_operation=service_operation,
    )
    return projection


def _validate_provider_context_against_service_operation(
    *,
    projection: Mapping[str, object],
    provider: str,
    service_operation: Mapping[str, object],
) -> None:
    current = validate_benchmark_v2_provider_dispatch_context_projection(projection)
    service = validate_benchmark_v2_workflow_service_operation_ref(service_operation)
    operation = current["operation_ref"]
    if current["provider"] != provider:
        raise ValueError("benchmark provider context projection provider is stale")
    if any(
        operation[name] != service[name]
        for name in ("run_id", "stage", "operation_id", "window_binding_ref", "capture_ref")
    ):
        raise ValueError("benchmark provider context projection operation lineage is stale")
    if operation["revision"] > service["workflow_state_ref"]["revision"]:
        raise ValueError("benchmark provider context projection revision is from the future")


def _service_operation_from_step(
    step: object,
    *,
    name: str,
    predecessor: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    if not isinstance(step, Mapping) or not isinstance(
        step.get("operation_ref"), Mapping
    ):
        raise ValueError(f"benchmark {name} did not return an operation ref")
    operation = validate_benchmark_v2_workflow_service_operation_ref(
        step["operation_ref"]
    )
    if step.get("status") != operation["status"]:
        raise ValueError(f"benchmark {name} status differs from its operation ref")
    if predecessor is not None:
        previous = validate_benchmark_v2_workflow_service_operation_ref(predecessor)
        if operation["operation_id"] != previous["operation_id"]:
            raise ValueError("benchmark probe continuation switched operation identity")
        if operation["content_sha256"] != previous["content_sha256"]:
            if operation["predecessor_content_sha256"] != previous["content_sha256"]:
                raise ValueError("benchmark probe continuation predecessor is stale")
            if any(
                operation[field]["revision"] <= previous[field]["revision"]
                for field in ("workflow_state_ref", "stage_execution_ref")
            ):
                raise ValueError("benchmark probe continuation revision did not advance")
    return operation


def _validate_probe_operation_lineage(
    *,
    operation: Mapping[str, object],
    binding: Mapping[str, object],
    request_ref: Mapping[str, object],
) -> None:
    current = validate_benchmark_v2_workflow_service_operation_ref(operation)
    window = validate_benchmark_v2_workflow_window_binding(binding)
    if any(
        current[name] != window[name]
        for name in ("run_id", "stage", "operation_id")
    ) or any(
        current[name] != window[name]
        for name in ("window_binding_ref", "capture_ref")
    ):
        raise ValueError("benchmark probe WorkflowService window lineage is stale")
    if current["request_ref"] != request_ref:
        raise ValueError("benchmark probe WorkflowService request lineage is stale")


def _service_start_intent_from_events(
    events: list[Mapping[str, object]],
) -> dict[str, dict[str, Any]] | None:
    matches = [
        event
        for event in events
        if event.get("event_kind") == "service_start_intent"
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("benchmark service start intent is duplicated")
    value = _runtime_resource_value(
        matches[0], expected_kind="workflow_service_start_intent"
    )
    if not isinstance(value, Mapping) or set(value) != {
        "screen_group",
        "window_binding",
    }:
        raise ValueError("benchmark service start intent is not closed")
    screen_group = validate_benchmark_v2_hybrid_screen_group_start(
        value["screen_group"]
    )
    window_binding = validate_benchmark_v2_workflow_window_binding(
        value["window_binding"]
    )
    return {
        "screen_group": screen_group,
        "window_binding": window_binding,
    }


def _lookup_service_operation_from_intent(
    *,
    events: list[Mapping[str, object]],
    service: object,
) -> dict[str, Any] | None:
    intent = _service_start_intent_from_events(events)
    if intent is None:
        return None
    lookup = getattr(service, "lookup_hybrid_operation", None)
    if not callable(lookup):
        raise RuntimeError("WorkflowService lookup_hybrid_operation is unavailable")
    step = lookup(
        screen_group=deepcopy(intent["screen_group"]),
        window_binding=deepcopy(intent["window_binding"]),
    )
    if step is None:
        return None
    operation = _service_operation_from_step(
        step,
        name="hard-crash service lookup",
    )
    _validate_probe_operation_lineage(
        operation=operation,
        binding=intent["window_binding"],
        request_ref=intent["screen_group"]["request_ref"],
    )
    return operation


def _append_service_recovered_event(
    *,
    journal_path: Path,
    attempt_ref: Mapping[str, object],
    operation: Mapping[str, object],
    binding: Mapping[str, object],
    screen_group: Mapping[str, object],
) -> dict[str, Any]:
    current = validate_benchmark_v2_workflow_service_operation_ref(operation)
    append_benchmark_v2_attempt_event(
        journal_path=journal_path,
        attempt_ref=attempt_ref,
        phase="prepared",
        event_kind="service_recovered",
        resource_ref=_service_operation_resource(
            operation=current,
            binding=binding,
            screen_group=screen_group,
        ),
    )
    return current


def _service_operation_from_events(
    events: list[Mapping[str, object]],
) -> dict[str, Any] | None:
    intent = _service_start_intent_from_events(events)
    for event in reversed(events):
        if event.get("event_kind") not in {"service_started", "service_recovered"}:
            continue
        value = _runtime_resource_value(
            event, expected_kind="workflow_service_operation"
        )
        if (
            isinstance(value, Mapping)
            and set(value) == {
                "operation_ref",
                "window_binding",
                "screen_group_ref",
            }
            and isinstance(value.get("operation_ref"), Mapping)
        ):
            operation = validate_benchmark_v2_workflow_service_operation_ref(
                value["operation_ref"]
            )
            binding_value = value.get("window_binding")
            if not isinstance(binding_value, Mapping):
                raise ValueError("benchmark service event lost its window binding")
            binding = validate_benchmark_v2_workflow_window_binding(binding_value)
            if any(
                operation[name] != binding[name]
                for name in ("run_id", "stage", "operation_id")
            ) or any(
                operation[name] != binding[name]
                for name in ("window_binding_ref", "capture_ref")
            ):
                raise ValueError("benchmark service event window lineage is stale")
            group_ref = _identity_ref(
                value.get("screen_group_ref"),
                name="benchmark service event screen group ref",
            )
            if intent is None:
                raise ValueError("benchmark service event lost its start intent")
            if (
                binding != intent["window_binding"]
                or group_ref
                != {
                    "id": str(intent["screen_group"]["screen_group"]),
                    "content_sha256": str(intent["screen_group"]["content_sha256"]),
                }
            ):
                raise ValueError("benchmark service event start lineage is stale")
            _validate_probe_operation_lineage(
                operation=operation,
                binding=binding,
                request_ref=intent["screen_group"]["request_ref"],
            )
            return operation
        raise ValueError("benchmark service event is not closed")
    return None


def _validate_service_terminal(
    value: object,
    *,
    expected_operation: Mapping[str, object] | None = None,
    expected_context_projection: Mapping[str, object] | None = None,
    expected_request: Mapping[str, object] | None = None,
    require_safe_stop: bool = False,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("workflow service terminal result is unavailable")
    terminal = _sealed_parent(value, name="workflow service terminal result")
    if terminal.get("status") not in {
        "complete",
        "cancelled",
        "safe_stopped",
    }:
        raise ValueError("workflow service terminal status is not terminal")
    if require_safe_stop and terminal.get("status") not in {
        "cancelled",
        "safe_stopped",
    }:
        raise ValueError("workflow service probe terminal is not a safe-stop cancellation")
    if not isinstance(terminal.get("operation_ref"), Mapping):
        raise ValueError("workflow service terminal operation ref is unavailable")
    operation = validate_benchmark_v2_workflow_service_operation_ref(
        terminal["operation_ref"]
    )
    if operation["status"] != terminal["status"]:
        raise ValueError("workflow service terminal operation status is stale")
    cleanup = terminal.get("cleanup_refs")
    if not isinstance(cleanup, Mapping) or set(cleanup) != {
        "worker_cleanup_ref",
        "provider_cleanup_ref",
    }:
        raise ValueError("workflow service terminal cleanup lineage is unavailable")
    for name in ("worker_cleanup_ref", "provider_cleanup_ref"):
        if cleanup[name] is not None:
            cleanup[name] = _runtime_sealed_parent(
                cleanup[name], name=f"workflow service {name}"
            )
    terminal["cleanup_refs"] = cleanup
    if require_safe_stop:
        if (
            expected_operation is None
            or expected_context_projection is None
            or expected_request is None
        ):
            raise ValueError("workflow service probe terminal expected lineage is unavailable")
        expected = validate_benchmark_v2_workflow_service_operation_ref(
            expected_operation
        )
        if any(
            operation[name] != expected[name]
            for name in (
                "run_id",
                "stage",
                "operation_id",
                "request_ref",
                "window_binding_ref",
                "capture_ref",
            )
        ):
            raise ValueError("workflow service probe terminal operation lineage is stale")
        projection = terminal.get("provider_dispatch_context_projection")
        if projection != expected_context_projection:
            raise ValueError("workflow service probe terminal provider context is stale")
        _validate_provider_context_against_service_operation(
            projection=expected_context_projection,
            provider=str(expected_context_projection["provider"]),
            service_operation=expected,
        )
        worker_cleanup = cleanup.get("worker_cleanup_ref")
        if not isinstance(worker_cleanup, Mapping):
            raise ValueError("workflow service probe terminal worker cleanup is unavailable")
        backend = worker_cleanup.get("backend_compute_termination")
        model = worker_cleanup.get("model_service_compute_termination")
        safe_backend = backend in {"not_running", "terminated"}
        safe_model = model in {"request_not_active", "terminated"}
        provider = str(expected_context_projection["provider"])
        incarnation_proven = safe_backend and (
            provider == "omni" or safe_model
        )
        if not incarnation_proven:
            raise ValueError(
                "workflow service probe terminal incarnation termination is unprovable"
            )
        worker = operation.get("worker_ref")
        required_worker_identity = (
            "worker_id",
            "model_request_id",
            "payload_sha256",
        )
        if not isinstance(worker, Mapping) or any(
            not isinstance(worker.get(name), str) or not worker.get(name)
            for name in required_worker_identity
        ):
            raise ValueError(
                "workflow service probe terminal worker identity is unavailable"
            )
        if any(
            worker_cleanup.get(name) != worker[name]
            for name in required_worker_identity
        ):
            raise ValueError(
                "workflow service probe terminal worker cleanup model request is stale"
            )
        provider_cleanup = cleanup.get("provider_cleanup_ref")
        if not isinstance(provider_cleanup, Mapping):
            raise ValueError(
                "workflow service probe terminal provider cleanup is unavailable"
            )
        provider_cleanup_fields = {
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
        if (
            set(provider_cleanup) != provider_cleanup_fields
            or provider_cleanup.get("contract_version")
            != "benchmark_provider_cleanup_ref_v1"
            or provider_cleanup.get("status") != "cleanup_verified"
            or provider_cleanup.get("outcome")
            not in {"verified_not_acquired", "verified_exact_process_exited"}
            or provider_cleanup.get("authority_kind")
            != "benchmark_v2_workflow_service_dispatch_cleanup"
            or any(
                provider_cleanup.get(name) != operation[name]
                for name in ("run_id", "stage", "operation_id")
            )
            or any(
                provider_cleanup.get(name) != worker[name]
                for name in required_worker_identity
            )
        ):
            raise ValueError(
                "workflow service probe terminal provider cleanup model request is stale"
            )
        request = _validate_probe_request(expected_request)
        expected_runtime_owner = {
            "content_sha256": request["provider_runtime_attestation_ref"][
                "content_sha256"
            ]
        }
        expected_context_owner = {
            "content_sha256": expected_context_projection[
                "context_content_sha256"
            ]
        }
        for name in (
            "reservation_ref",
            "acquisition_owner_ref",
            "acquisition_intent_ref",
            "runtime_owner_ref",
            "cleanup_receipt_ref",
        ):
            _sealed_parent(
                provider_cleanup[name],
                name=f"workflow service provider cleanup {name}",
            )
        if (
            provider_cleanup["reservation_ref"] != expected_context_owner
            or provider_cleanup["acquisition_owner_ref"]
            != {
                "content_sha256": request["dispatch_receipt_ref"][
                    "content_sha256"
                ]
            }
            or provider_cleanup["acquisition_intent_ref"]
            != expected_runtime_owner
            or provider_cleanup["runtime_owner_ref"] != expected_runtime_owner
        ):
            raise ValueError(
                "workflow service probe terminal provider cleanup runtime owner "
                "incarnation is stale"
            )
        if (
            request["operation_ref"] != expected
            or request["provider_dispatch_context_projection"]
            != expected_context_projection
        ):
            raise ValueError("workflow service probe terminal request lineage is stale")
    return terminal


def _probe_cleanup_binding(
    *,
    context: Mapping[str, object],
    request: Mapping[str, object],
    service_terminal: Mapping[str, object],
) -> dict[str, Any]:
    terminal = _validate_service_terminal(
        service_terminal,
        expected_operation=context["operation_ref"],
        expected_context_projection=context[
            "provider_dispatch_context_projection"
        ],
        expected_request=request,
        require_safe_stop=True,
    )
    cleanup = terminal["cleanup_refs"]
    return _runtime_resource_ref(
        "probe_cleanup_binding",
        {
            "provider_dispatch_context_projection": deepcopy(
                context["provider_dispatch_context_projection"]
            ),
            "dispatch_receipt_ref": deepcopy(request["dispatch_receipt_ref"]),
            "provider_runtime_attestation_ref": deepcopy(
                request["provider_runtime_attestation_ref"]
            ),
            "service_terminal_operation_ref": deepcopy(terminal["operation_ref"]),
            "worker_cleanup_ref": deepcopy(cleanup["worker_cleanup_ref"]),
            "provider_cleanup_ref": deepcopy(cleanup["provider_cleanup_ref"]),
        },
    )


def _probe_tuple(provider_id: object, probe_kind: object) -> tuple[str, str]:
    return _probe_provider(provider_id), _probe_kind(probe_kind)


def _probe_terminal_tuples(events: list[Mapping[str, object]]) -> list[tuple[str, str]]:
    tuples: set[tuple[str, str]] = set()
    for event in events:
        if event.get("event_kind") == "probe_trigger_terminal":
            tuples.add(_probe_tuple(event.get("provider_id"), event.get("probe_kind")))
    return sorted(tuples)


def _single_probe_intent_tuple(events: list[Mapping[str, object]]) -> tuple[str, str] | None:
    tuples: set[tuple[str, str]] = set()
    for event in events:
        if event.get("event_kind") == "probe_trigger_intent":
            tuples.add(_probe_tuple(event.get("provider_id"), event.get("probe_kind")))
    tuples.difference_update(_probe_terminal_tuples(events))
    if not tuples:
        return None
    if len(tuples) != 1:
        raise ValueError("benchmark unfinished probe recovery tuple is ambiguous")
    return next(iter(tuples))


def _probe_events_for_tuple(
    events: list[Mapping[str, object]],
    *,
    event_kind: str,
    provider_id: object,
    probe_kind: object,
) -> list[Mapping[str, object]]:
    provider, kind = _probe_tuple(provider_id, probe_kind)
    return [
        event
        for event in events
        if event.get("event_kind") == event_kind
        and event.get("provider_id") == provider
        and event.get("probe_kind") == kind
    ]


def _one_probe_event_for_tuple(
    events: list[Mapping[str, object]],
    *,
    event_kind: str,
    provider_id: object,
    probe_kind: object,
    required: bool,
) -> Mapping[str, object] | None:
    matches = _probe_events_for_tuple(
        events,
        event_kind=event_kind,
        provider_id=provider_id,
        probe_kind=probe_kind,
    )
    if not matches:
        if required:
            raise ValueError(f"benchmark probe {event_kind} is unavailable for tuple")
        return None
    if len(matches) != 1:
        raise ValueError(f"benchmark probe {event_kind} is not unique for tuple")
    return matches[0]


def _validate_probe_absence_observations(
    value: object, *, name: str, allow_encoded_times: bool = False
) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} absence observations are invalid")
    normalized: list[dict[str, object]] = []
    seen: set[tuple[int, int]] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{name} absence observation is invalid")
        outcome = item.get("outcome")
        fields = {"pid", "create_time_ns", "outcome"}
        if outcome == "pid_reused":
            fields.add("observed_create_time_ns")
        if outcome not in {"no_such_process", "pid_reused"} or set(item) != fields:
            raise ValueError(f"{name} absence observation is invalid")
        pid = item.get("pid")
        created = item.get("create_time_ns")
        def _time_value(raw: object) -> int | str:
            if isinstance(raw, bool):
                raise ValueError(f"{name} absence observation is invalid")
            if isinstance(raw, int) and raw > 0:
                return raw
            if (
                allow_encoded_times
                and isinstance(raw, str)
                and raw.isascii()
                and raw.isdecimal()
                and raw[0] != "0"
                and int(raw) > 0
            ):
                return raw
            raise ValueError(f"{name} absence observation is invalid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError(f"{name} absence observation is invalid")
        created_value = _time_value(created)
        identity = (pid, int(created_value))
        if identity in seen:
            raise ValueError(f"{name} absence observation is invalid")
        observed: dict[str, object] = {
            "pid": pid,
            "create_time_ns": created_value,
            "outcome": outcome,
        }
        if outcome == "pid_reused":
            observed["observed_create_time_ns"] = _time_value(item.get("observed_create_time_ns"))
        seen.add(identity)
        normalized.append(observed)
    return normalized


def _validate_probe_trigger_terminal(value: object) -> dict[str, Any]:
    fields = {
        "contract_version", "trigger_intent_ref", "service_terminal_ref",
        "cleanup_binding_ref", "absence_observations", "outcome",
        "evidence_scope", "artifact_is_authorization", "execute_binding_enabled",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("benchmark probe trigger terminal is not closed")
    terminal = deepcopy(dict(value))
    if (
        terminal["contract_version"] != _PROBE_TRIGGER_TERMINAL_CONTRACT
        or terminal["outcome"] != "safe_stopped_exact_incarnation_absent"
        or terminal["evidence_scope"] != "benchmark_probe_only_non_authorizing"
        or terminal["artifact_is_authorization"] is not False
        or terminal["execute_binding_enabled"] is not False
        or terminal["content_sha256"] != content_sha256(terminal)
    ):
        raise ValueError("benchmark probe trigger terminal is invalid")
    for field in ("trigger_intent_ref", "service_terminal_ref", "cleanup_binding_ref"):
        terminal[field] = _sealed_parent(terminal[field], name=f"probe trigger terminal {field}")
    terminal["absence_observations"] = _validate_probe_absence_observations(
        terminal["absence_observations"],
        name="benchmark probe terminal",
        allow_encoded_times=True,
    )
    return terminal


def _probe_trigger_intent_from_events(
    events: list[Mapping[str, object]], *, provider_id: object, probe_kind: object
) -> dict[str, Any] | None:
    event = _one_probe_event_for_tuple(
        events,
        event_kind="probe_trigger_intent",
        provider_id=provider_id,
        probe_kind=probe_kind,
        required=False,
    )
    if event is None:
        return None
    value = _runtime_resource_value(event, expected_kind="probe_trigger_intent")
    if not isinstance(value, Mapping) or set(value) != {"trigger_intent"}:
        raise ValueError("benchmark probe trigger intent resource is not closed")
    return _validate_probe_trigger_intent(value["trigger_intent"])


def _probe_request_from_events(
    events: list[Mapping[str, object]], *, provider_id: object, probe_kind: object
) -> dict[str, Any] | None:
    event = _one_probe_event_for_tuple(
        events,
        event_kind="provider_request_in_flight",
        provider_id=provider_id,
        probe_kind=probe_kind,
        required=False,
    )
    if event is None:
        return None
    value = _runtime_resource_value(event, expected_kind="provider_request_in_flight")
    if not isinstance(value, Mapping) or set(value) != {
        "operation_ref", "provider_dispatch_context_projection", "dispatch_receipt"
    }:
        raise ValueError("benchmark probe request resource is not closed")
    receipt = _sealed_parent(value["dispatch_receipt"], name="benchmark probe dispatch receipt")
    if not isinstance(receipt.get("provider_runtime_attestation_ref"), Mapping):
        raise ValueError("benchmark probe dispatch runtime identity is unavailable")
    body: dict[str, Any] = {
        "contract_version": _PROBE_REQUEST_CONTRACT,
        "attempt_ref": deepcopy(event["attempt_ref"]),
        "provider_id": event["provider_id"],
        "probe_kind": event["probe_kind"],
        "operation_ref": deepcopy(value["operation_ref"]),
        "provider_dispatch_context_projection": deepcopy(value["provider_dispatch_context_projection"]),
        "request_state": "request_in_flight",
        "dispatch_receipt_ref": _content_ref(receipt, name="dispatch receipt"),
        "provider_runtime_attestation_ref": deepcopy(receipt["provider_runtime_attestation_ref"]),
        "attempt_event_ref": _event_ref(event),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return _validate_probe_request(body)


def _probe_context_from_events(
    events: list[Mapping[str, object]],
    *,
    trigger_intent: Mapping[str, object],
    request: Mapping[str, object],
) -> dict[str, Any]:
    intent = _validate_probe_trigger_intent(trigger_intent)
    in_flight = _validate_probe_request(request)
    if (
        in_flight["attempt_ref"] != intent["attempt_ref"]
        or in_flight["provider_id"] != intent["provider_id"]
        or in_flight["probe_kind"] != intent["probe_kind"]
        or in_flight["operation_ref"] != intent["operation_ref"]
        or intent["request_in_flight_ref"] != _content_ref(in_flight, name="probe trigger request")
        or intent["dispatch_receipt_ref"] != in_flight["dispatch_receipt_ref"]
    ):
        raise ValueError("benchmark probe recovery lineage is stale")
    parent = _sealed_parent(intent["dispatch_runtime_parent_ref"], name="probe trigger dispatch runtime parent")
    runtime_identity = _sealed_parent(
        parent.get("runtime_identity"), name="probe trigger runtime identity"
    )
    if (
        parent.get("provider") != intent["provider_id"]
        or parent.get("operation_ref")
        != in_flight["provider_dispatch_context_projection"]["operation_ref"]
        or parent.get("dispatch_receipt_ref")
        != {"content_sha256": in_flight["dispatch_receipt_ref"]["content_sha256"]}
        or in_flight["provider_runtime_attestation_ref"]
        != {"content_sha256": runtime_identity["content_sha256"]}
    ):
        raise ValueError("benchmark probe recovery runtime parent/provider lineage is stale")
    matches: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    for event in events:
        if event.get("event_kind") != "service_started":
            continue
        value = _runtime_resource_value(event, expected_kind="workflow_service_operation")
        if isinstance(value, Mapping) and value.get("operation_ref") == intent["operation_ref"]:
            matches.append((event, value))
    if len(matches) != 1:
        raise ValueError("benchmark probe service start event is unavailable for tuple")
    service_event, value = matches[0]
    if set(value) != {"operation_ref", "window_binding", "screen_group_ref"}:
        raise ValueError("benchmark probe service start resource is not closed")
    binding = validate_benchmark_v2_workflow_window_binding(value["window_binding"])
    group_ref = _identity_ref(value["screen_group_ref"], name="benchmark service start screen group ref")
    operation = intent["operation_ref"]
    if any(binding[name] != operation[name] for name in (
        "run_id", "stage", "operation_id", "window_binding_ref", "capture_ref"
    )):
        raise ValueError("benchmark probe service start window binding lineage is stale")
    start_matches: list[dict[str, dict[str, Any]]] = []
    for event in events:
        if event.get("event_kind") != "service_start_intent":
            continue
        start_value = _runtime_resource_value(
            event, expected_kind="workflow_service_start_intent"
        )
        if not isinstance(start_value, Mapping) or set(start_value) != {
            "screen_group", "window_binding"
        }:
            raise ValueError("benchmark service start intent is not closed")
        start_group = validate_benchmark_v2_hybrid_screen_group_start(
            start_value["screen_group"]
        )
        start_binding = validate_benchmark_v2_workflow_window_binding(
            start_value["window_binding"]
        )
        candidate_group_ref = {
            "id": str(start_group["screen_group"]),
            "content_sha256": str(start_group["content_sha256"]),
        }
        if start_binding == binding and candidate_group_ref == group_ref:
            start_matches.append({
                "screen_group": start_group,
                "window_binding": start_binding,
            })
    if len(start_matches) != 1:
        raise ValueError("benchmark probe exact service start intent is unavailable")
    body: dict[str, Any] = {
        "contract_version": _PROBE_CONTEXT_CONTRACT,
        "attempt_ref": deepcopy(intent["attempt_ref"]),
        "provider_id": intent["provider_id"],
        "probe_kind": intent["probe_kind"],
        "operation_ref": deepcopy(intent["operation_ref"]),
        "provider_dispatch_context_projection": deepcopy(in_flight["provider_dispatch_context_projection"]),
        "window_binding_ref": deepcopy(intent["operation_ref"]["window_binding_ref"]),
        "capture_ref": deepcopy(intent["operation_ref"]["capture_ref"]),
        "screen_group_ref": group_ref,
        "service_event_ref": _event_ref(service_event),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return _validate_probe_context(body)


def _probe_terminal_material(
    events: list[Mapping[str, object]], *, provider_id: object, probe_kind: object
) -> dict[str, Any] | None:
    provider, kind = _probe_tuple(provider_id, probe_kind)
    terminal_event = _one_probe_event_for_tuple(
        events, event_kind="probe_trigger_terminal", provider_id=provider, probe_kind=kind, required=False
    )
    if terminal_event is None:
        return None
    intent_event = _one_probe_event_for_tuple(
        events, event_kind="probe_trigger_intent", provider_id=provider, probe_kind=kind, required=True
    )
    request_event = _one_probe_event_for_tuple(
        events, event_kind="provider_request_in_flight", provider_id=provider, probe_kind=kind, required=True
    )
    triggered_event = _one_probe_event_for_tuple(
        events, event_kind="probe_triggered", provider_id=provider, probe_kind=kind, required=True
    )
    assert intent_event is not None and request_event is not None and triggered_event is not None
    terminal_value = _runtime_resource_value(terminal_event, expected_kind="probe_trigger_terminal")
    if not isinstance(terminal_value, Mapping) or set(terminal_value) != {"probe_trigger_terminal"}:
        raise ValueError("benchmark probe trigger terminal resource is not closed")
    durable_terminal = _validate_probe_trigger_terminal(terminal_value["probe_trigger_terminal"])
    intent = _probe_trigger_intent_from_events(events, provider_id=provider, probe_kind=kind)
    request = _probe_request_from_events(events, provider_id=provider, probe_kind=kind)
    if intent is None or request is None:
        raise ValueError("benchmark probe trigger terminal recovery is incomplete")
    context = _probe_context_from_events(events, trigger_intent=intent, request=request)
    trigger_observation = _probe_trigger_observation_from_events(
        events,
        provider_id=provider,
        probe_kind=kind,
        required=True,
    )
    assert trigger_observation is not None
    _validate_probe_trigger_observation_lineage(
        material=trigger_observation,
        context=context,
        request=request,
    )
    causal_events = (
        request_event,
        trigger_observation["event"],
        intent_event,
        triggered_event,
        terminal_event,
    )
    causal_sequences = [event.get("sequence") for event in causal_events]
    if any(
        isinstance(sequence, bool) or not isinstance(sequence, int)
        for sequence in causal_sequences
    ) or any(
        left >= right
        for left, right in zip(causal_sequences, causal_sequences[1:])
    ):
        raise ValueError(
            "benchmark probe causal order requires request < observation < intent < "
            "triggered < terminal"
        )
    triggered_value = _runtime_resource_value(triggered_event, expected_kind="probe_trigger")
    if not isinstance(triggered_value, Mapping) or set(triggered_value) != {
        "request_ref", "service_terminal", "cleanup_binding_ref"
    }:
        raise ValueError("benchmark probe trigger recovery resource is not closed")
    service_terminal = _validate_service_terminal(
        triggered_value["service_terminal"],
        expected_operation=context["operation_ref"],
        expected_context_projection=context["provider_dispatch_context_projection"],
        expected_request=request,
        require_safe_stop=True,
    )
    cleanup_binding = _probe_cleanup_binding(
        context=context, request=request, service_terminal=service_terminal
    )
    if (
        durable_terminal["trigger_intent_ref"] != _event_ref(intent_event)
        or durable_terminal["service_terminal_ref"] != _content_ref(service_terminal, name="workflow service terminal result")
        or durable_terminal["cleanup_binding_ref"] != cleanup_binding
        or triggered_value["request_ref"] != _content_ref(request, name="probe request")
        or triggered_value["cleanup_binding_ref"] != cleanup_binding
    ):
        raise ValueError("benchmark probe trigger terminal recovery lineage is stale")
    historical = durable_terminal["absence_observations"]
    identities = intent["process_identities"]
    if len(historical) != len(identities) or any(
        observation["pid"] != identity["pid"]
        or int(observation["create_time_ns"]) != identity["create_time_ns"]
        for observation, identity in zip(historical, identities, strict=True)
    ):
        raise ValueError("benchmark probe terminal absence identity is stale")
    return {
        "provider_id": provider,
        "probe_kind": kind,
        "terminal_event": terminal_event,
        "intent_event": intent_event,
        "request_event": request_event,
        "triggered_event": triggered_event,
        "terminal": durable_terminal,
        "intent": intent,
        "request": request,
        "context": context,
        "service_terminal": service_terminal,
        "cleanup_binding": cleanup_binding,
        "trigger_observation": trigger_observation,
    }


def _probe_trigger_from_terminal_events(
    events: list[Mapping[str, object]], *, provider_id: object, probe_kind: object
) -> dict[str, Any] | None:
    material = _probe_terminal_material(events, provider_id=provider_id, probe_kind=probe_kind)
    if material is None:
        return None
    observations = _live_absence_observations(material["intent"]["process_identities"])
    body: dict[str, Any] = {
        "contract_version": _PROBE_TRIGGER_CONTRACT,
        "attempt_ref": deepcopy(material["context"]["attempt_ref"]),
        "provider_id": material["provider_id"],
        "probe_kind": material["probe_kind"],
        "request_in_flight_ref": _content_ref(material["request"], name="probe request"),
        "trigger_intent_ref": _event_ref(material["intent_event"]),
        "service_terminal_ref": _content_ref(material["service_terminal"], name="workflow service terminal result"),
        "cleanup_binding_ref": deepcopy(material["cleanup_binding"]),
        "probe_trigger_terminal_ref": _event_ref(material["terminal_event"]),
        "absence_observations": observations,
        "attempt_event_ref": _event_ref(material["triggered_event"]),
        "outcome": "safe_stopped_exact_incarnation_absent",
        "evidence_scope": "benchmark_probe_only_non_authorizing",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return _validate_probe_trigger(body)

def _safe_stopped_terminal_from_lookup(
    *,
    events: list[Mapping[str, object]],
    service: object,
    context: Mapping[str, object],
    request: Mapping[str, object],
) -> dict[str, Any] | None:
    start = _service_start_intent_from_events(events)
    if start is None:
        raise ValueError("benchmark probe service start intent is unavailable")
    lookup = getattr(service, "lookup_hybrid_operation", None)
    if not callable(lookup):
        raise RuntimeError("WorkflowService lookup_hybrid_operation is unavailable")
    step = lookup(
        screen_group=deepcopy(start["screen_group"]),
        window_binding=deepcopy(start["window_binding"]),
    )
    if step is None:
        raise ValueError("benchmark probe exact service lookup is unavailable")
    operation = _service_operation_from_step(step, name="probe trigger intent recovery")
    if operation["status"] == "pending":
        if operation != context["operation_ref"]:
            raise ValueError("benchmark probe pending lookup operation is stale")
        return None
    if operation["status"] not in {"cancelled", "safe_stopped"}:
        raise ValueError("benchmark probe exact service lookup is not safe-stopped")
    if not isinstance(step, Mapping):
        raise ValueError("benchmark probe exact service lookup is invalid")
    cleanup = step.get("cleanup_refs")
    projection = step.get("provider_dispatch_context_projection")
    if not isinstance(cleanup, Mapping) or not isinstance(projection, Mapping):
        raise ValueError("benchmark probe exact service lookup lacks terminal lineage")
    body: dict[str, Any] = {
        "status": operation["status"],
        "operation_ref": operation,
        "provider_dispatch_context_projection": deepcopy(dict(projection)),
        "cleanup_refs": deepcopy(dict(cleanup)),
    }
    body["content_sha256"] = content_sha256(body)
    return _validate_service_terminal(
        body,
        expected_operation=context["operation_ref"],
        expected_context_projection=context["provider_dispatch_context_projection"],
        expected_request=request,
        require_safe_stop=True,
    )


def _persist_recovered_probe_terminal(
    *,
    journal_path: Path,
    context: Mapping[str, object],
    request: Mapping[str, object],
    trigger_intent_event: Mapping[str, object],
    service_terminal: Mapping[str, object],
) -> dict[str, Any]:
    context = _validate_probe_context(context)
    request = _validate_probe_request(request)
    service_terminal = _validate_service_terminal(
        service_terminal,
        expected_operation=context["operation_ref"],
        expected_context_projection=context["provider_dispatch_context_projection"],
        expected_request=request,
        require_safe_stop=True,
    )
    cleanup_binding = _probe_cleanup_binding(
        context=context,
        request=request,
        service_terminal=service_terminal,
    )
    triggered = append_benchmark_v2_attempt_event(
        journal_path=journal_path,
        attempt_ref=context["attempt_ref"],
        phase="request_in_flight",
        event_kind="probe_triggered",
        provider_id=str(context["provider_id"]),
        probe_kind=str(context["probe_kind"]),
        resource_ref=_runtime_resource_ref(
            "probe_trigger",
            {
                "request_ref": _content_ref(request, name="probe request"),
                "service_terminal": service_terminal,
                "cleanup_binding_ref": cleanup_binding,
            },
        ),
    )
    absence_observations = _live_absence_observations(
        _validate_probe_trigger_intent(
            _runtime_resource_value(
                trigger_intent_event, expected_kind="probe_trigger_intent"
            )["trigger_intent"]
        )["process_identities"]
    )
    body: dict[str, Any] = {
        "contract_version": _PROBE_TRIGGER_TERMINAL_CONTRACT,
        "trigger_intent_ref": _event_ref(trigger_intent_event),
        "service_terminal_ref": _content_ref(service_terminal, name="workflow service terminal result"),
        "cleanup_binding_ref": cleanup_binding,
        "absence_observations": _persisted_probe_absence_observations(absence_observations),
        "outcome": "safe_stopped_exact_incarnation_absent",
        "evidence_scope": "benchmark_probe_only_non_authorizing",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    terminal = _sealed_parent(body, name="probe trigger terminal")
    terminal_resource = _runtime_resource_ref(
        "probe_trigger_terminal", {"probe_trigger_terminal": terminal}
    )
    append_benchmark_v2_attempt_event(
        journal_path=journal_path,
        attempt_ref=context["attempt_ref"],
        phase="body_complete",
        event_kind="probe_trigger_terminal",
        provider_id=str(context["provider_id"]),
        probe_kind=str(context["probe_kind"]),
        resource_ref=terminal_resource,
    )
    return _validate_service_terminal(
        service_terminal,
        expected_operation=context["operation_ref"],
        expected_context_projection=context["provider_dispatch_context_projection"],
        expected_request=request,
        require_safe_stop=True,
    )


def _service_terminal_from_events(
    events: list[Mapping[str, object]], *, provider_id: object, probe_kind: object
) -> dict[str, Any] | None:
    provider, kind = _probe_tuple(provider_id, probe_kind)
    for event in reversed(events):
        if (
            event.get("event_kind") != "probe_triggered"
            or event.get("provider_id") != provider
            or event.get("probe_kind") != kind
        ):
            continue
        value = _runtime_resource_value(event, expected_kind="probe_trigger")
        if isinstance(value, Mapping) and isinstance(
            value.get("service_terminal"), Mapping
        ):
            return _validate_service_terminal(value["service_terminal"])
    return None


def _owner_journal_from_events(
    events: list[Mapping[str, object]],
    *,
    authority_root: Path,
) -> Path | None:
    root = Path(authority_root).resolve()
    for event in reversed(events):
        if event.get("event_kind") != "window_owned":
            continue
        value = _runtime_resource_value(event, expected_kind="owned_window")
        if not isinstance(value, Mapping):
            continue
        raw = value.get("owner_journal_path")
        if isinstance(raw, str):
            path = Path(raw)
            if (
                path.is_absolute()
                and path == path.resolve()
                and path.parent == root
            ):
                return path
            raise ValueError("benchmark owned-window journal escapes its authority root")
    return None


def _provider_cleanup_refs(
    service_terminal: Mapping[str, object] | None,
) -> list[dict[str, Any]]:
    if not isinstance(service_terminal, Mapping):
        return []
    cleanup = service_terminal.get("cleanup_refs")
    if not isinstance(cleanup, Mapping) or set(cleanup) != {
        "worker_cleanup_ref",
        "provider_cleanup_ref",
    }:
        raise ValueError("workflow service terminal cleanup lineage is unavailable")
    result: list[dict[str, Any]] = []
    for name, parent_kind in (
        ("worker_cleanup_ref", "worker_cleanup"),
        ("provider_cleanup_ref", "provider_cleanup"),
    ):
        value = cleanup.get(name)
        if value is not None:
            if not isinstance(value, Mapping):
                raise ValueError("workflow service terminal cleanup proof is unavailable")
            result.append(
                _cleanup_parent_ref(
                    value,
                    parent_kind=parent_kind,
                    name=name,
                )
            )
    return result


def _cleanup_receipt_from_terminal(
    events: list[Mapping[str, object]],
) -> dict[str, Any] | None:
    if not events or events[-1].get("event_kind") != "attempt_terminal":
        return None
    value = _runtime_resource_value(
        events[-1], expected_kind="attempt_cleanup_receipt"
    )
    if not isinstance(value, Mapping) or not isinstance(
        value.get("cleanup_receipt"), Mapping
    ):
        raise ValueError("benchmark terminal attempt lost its cleanup receipt")
    return _sealed_parent(value["cleanup_receipt"], name="attempt cleanup receipt")


def _prepared_cleanup_receipt_from_events(
    events: list[Mapping[str, object]],
) -> dict[str, Any] | None:
    if not events or events[-1].get("event_kind") != "attempt_cleanup_prepared":
        return None
    value = _runtime_resource_value(
        events[-1], expected_kind="attempt_cleanup_receipt"
    )
    if not isinstance(value, Mapping) or not isinstance(
        value.get("cleanup_receipt"), Mapping
    ):
        raise ValueError("benchmark prepared cleanup lost its exact receipt")
    return _sealed_parent(value["cleanup_receipt"], name="attempt cleanup receipt")


def _validate_snapshot_record(
    value: Mapping[str, object], *, owner: Mapping[str, object]
) -> dict[str, Any]:
    fields = {
        "contract_version",
        "owner_binding_ref",
        "operation_id",
        "exact_hwnd",
        "process_identity",
        "job_member_pids",
        "screenshot_sha256",
        "uia_root_identity",
        "uia_snapshot",
        "pre_raw_identity_sha256",
        "post_raw_identity_sha256",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "display_only",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("owned window snapshot record is not closed")
    record = deepcopy(dict(value))
    if (
        record["contract_version"]
        != "portfolio_hybrid_benchmark_v2_owned_window_snapshot_v1"
        or record["content_sha256"] != content_sha256(record)
        or record["owner_binding_ref"]
        != {"id": owner["owner_id"], "content_sha256": owner["content_sha256"]}
        or record["operation_id"] != owner["operation_id"]
        or record["exact_hwnd"] != owner["hwnd"]
        or record["process_identity"] != owner["process_identity"]
        or record["screenshot_sha256"] != owner["screenshot_sha256"]
        or record["uia_root_identity"] != owner["uia_root_identity"]
        or record["pre_raw_identity_sha256"]
        != record["post_raw_identity_sha256"]
        or record["artifact_is_authorization"] is not False
        or record["execute_binding_enabled"] is not False
        or record["display_only"] is not True
    ):
        raise ValueError("owned window snapshot has stale HWND or process lineage")
    return record


def _capture_window_binding(
    owner: Mapping[str, object], uia_snapshot: Mapping[str, object]
) -> dict[str, object]:
    window = uia_snapshot.get("window")
    if (
        not isinstance(window, Mapping)
        or window.get("handle") != owner["hwnd"]
        or window.get("process_id") != owner["process_identity"]["pid"]
    ):
        raise ValueError("UIA snapshot window/HWND process lineage is stale")
    rect = owner.get("window_rect")
    if not isinstance(rect, Mapping):
        raise ValueError("owned window rectangle is missing")
    return {
        "window_binding_id": str(owner["owner_id"]),
        "process_id": int(owner["process_identity"]["pid"]),
        "process_name": str(window["process_name"]),
        "rect": deepcopy(dict(rect)),
    }


def _capture_source(
    *,
    source_kind: str,
    evidence_ref: Mapping[str, object],
    identity: Mapping[str, object],
    run_id: str,
    window_binding: Mapping[str, object],
) -> dict[str, object]:
    return {
        "source_kind": source_kind,
        "capture_lineage_ref": deepcopy(identity["capture_lineage_ref"]),
        "run_id": run_id,
        "workflow_revision": 0,
        "window_binding": deepcopy(dict(window_binding)),
        "evidence_contract_version": "provider_safe_result_v1",
        "evidence_ref": deepcopy(dict(evidence_ref)),
    }


def _seal_omni_parents(
    *, project_root: Path, capture_lineage_ref: Mapping[str, object], capture_id: str
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    store = UEIObjectStore(root=project_root / "artifacts" / "uei-shadow-store")
    token = sha256((capture_id + ":omni").encode()).hexdigest()[:24]
    request_ref = store.put(seal_immutable({
        "contract_version": "screen_parse_request_v1",
        "request_id": f"request/benchmark-v2-omni/{token}",
        "capture_lineage_ref": deepcopy(dict(capture_lineage_ref)),
        "requested_profiles": [{
            "provider_id": _OMNI_PROVIDER_ID,
            "profile_id": _OMNI_PROFILE_ID,
            "mode": "Shadow",
        }],
        "privacy_policy": "restricted",
        "requester_id": "server",
    }))
    registration_ref = store.put(seal_immutable({
        "contract_version": "trusted_provider_registration_v1",
        "registration_id": "registration/benchmark-v2/omniparser/v2",
        "provider_id": _OMNI_PROVIDER_ID,
        "profile_ids": [_OMNI_PROFILE_ID],
        "enabled": True,
        "allowed_modes": ["Shadow"],
        "allowed_privacy_policies": ["restricted"],
        "egress_policy": "local_only",
        "wire_payload_policy": "restricted_store_only",
        "safe_payload_limits": deepcopy(_SAFE_LIMITS),
        "required_conformance_suite": "uei-v1-static-projection",
    }))
    manifest_ref = store.put(seal_immutable({
        "contract_version": "provider_manifest_v1",
        "manifest_id": "manifest/benchmark-v2/omniparser/v2",
        "provider_id": _OMNI_PROVIDER_ID,
        "provider_version": _OMNI_PROVIDER_VERSION,
        "profiles": [{
            "profile_id": _OMNI_PROFILE_ID,
            "operation": "screen_parse",
            "input_contract": "screen_parse_request_v1",
            "output_contract": "provider_safe_result_v1",
            "declared_output_kinds": ["element", "icon"],
            "supported_coordinate_spaces": ["capture_pixel_xyxy"],
            "supports_capture_artifact": True,
            "privacy_capabilities": ["restricted"],
            "mode_allowlist": ["Shadow"],
        }],
    }))
    return request_ref, registration_ref, manifest_ref


_PRODUCTION_RUNTIME = _BenchmarkV2ProductionRuntime(
    project_root=_PROJECT_ROOT,
    authority_root=_AUTHORITY_ROOT,
)


def get_production_benchmark_v2_runtime() -> BenchmarkV2ProductionRuntimePort:
    return _PRODUCTION_RUNTIME


__all__ = [
    "BenchmarkV2ProductionRuntimePort",
    "BenchmarkV2ScreenGroupIterator",
    "get_production_benchmark_v2_runtime",
]
