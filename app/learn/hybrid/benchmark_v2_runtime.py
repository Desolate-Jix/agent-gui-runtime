"""Benchmark-v2 真实屏幕组准备边界；不授予任何桌面动作权限。"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import RLock
import time
from typing import Any, Callable, Iterator, Mapping, Protocol

from app.core.ocr_service import ocr_service
from app.learn.hybrid.benchmark_v2_contracts import (
    canonical_json_bytes,
    content_sha256,
)
from app.learn.hybrid.benchmark_v2_incumbent_operation import (
    compose_benchmark_v2_hybrid_screen_group_start,
    compose_benchmark_v2_workflow_window_binding,
    get_production_benchmark_v2_workflow_service,
    validate_benchmark_v2_hybrid_screen_group_start,
    validate_benchmark_v2_provider_dispatch_context_projection,
    validate_benchmark_v2_workflow_window_binding,
    validate_benchmark_v2_workflow_service_operation_ref,
)
from app.learn.hybrid.benchmark_v2_lifecycle import (
    append_benchmark_v2_attempt_event,
    compose_benchmark_v2_attempt_cleanup_receipt,
    read_benchmark_v2_attempt_journal,
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
_PROBE_MAX_CONTINUES = 4096
_PROBE_CONTEXT_CONTRACT = "benchmark_v2_probe_context_v1"
_PROBE_REQUEST_CONTRACT = "benchmark_v2_probe_request_in_flight_v1"
_PROBE_TRIGGER_CONTRACT = "benchmark_v2_probe_trigger_receipt_v1"
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
_PROBE_TRIGGER_FIELDS = {
    "contract_version",
    "attempt_ref",
    "provider_id",
    "probe_kind",
    "request_in_flight_ref",
    "service_terminal_ref",
    "cleanup_binding_ref",
    "attempt_event_ref",
    "outcome",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
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


class _BenchmarkV2ProductionRuntime:
    __slots__ = (
        "_project_root",
        "_authority_root",
        "_lock",
        "_active",
        "_pending_cleanup",
        "_preparing",
        "_attempt_states",
    )

    def __init__(self, *, project_root: Path, authority_root: Path) -> None:
        self._project_root = Path(project_root).resolve()
        self._authority_root = Path(authority_root).resolve()
        self._lock = RLock()
        self._active: dict[str, Any] | None = None
        self._pending_cleanup: dict[str, object] | None = None
        self._preparing = False
        self._attempt_states: dict[str, dict[str, Any]] = {}

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
        if (
            corpus_file_ref.get("file_sha256") != ref["file_sha256"]
            or corpus_file_ref.get("source_parent_ref") != ref["source_parent_ref"]
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
        journal_path = _benchmark_v2_dispatch_journal_path_for_operation(
            project_root=self._project_root,
            operation_ref=operation,
        )
        deadline = time.monotonic() + _PROBE_DEADLINE_SECONDS
        receipt: dict[str, Any] | None = None
        while receipt is None:
            receipt = _read_exact_dispatch_receipt(
                journal_path=journal_path,
                provider=context["provider_id"],
                context_projection=context_projection,
            )
            if receipt is not None:
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
        existing = state.get("trigger_receipt")
        if isinstance(existing, Mapping):
            return _validate_probe_trigger(existing)
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
        body: dict[str, Any] = {
            "contract_version": _PROBE_TRIGGER_CONTRACT,
            "attempt_ref": deepcopy(context["attempt_ref"]),
            "provider_id": context["provider_id"],
            "probe_kind": kind,
            "request_in_flight_ref": _content_ref(request, name="probe request"),
            "service_terminal_ref": _content_ref(
                service_terminal, name="workflow service terminal result"
            ),
            "cleanup_binding_ref": cleanup_binding,
            "attempt_event_ref": _event_ref(event),
            "outcome": "safe_stopped",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        body["content_sha256"] = content_sha256(body)
        trigger = _validate_probe_trigger(body)
        state["trigger_receipt"] = deepcopy(trigger)
        return trigger

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

        service_terminal: Mapping[str, object] | None = None
        window_cleanup: Mapping[str, object] | None = None
        cleanup_errors: list[BaseException] = []
        durable_service_operation = _service_operation_from_events(events)
        if isinstance(state, dict):
            try:
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
                        try:
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
                service_terminal = _service_terminal_from_events(events)
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
                    if service is None:
                        service = get_production_benchmark_v2_workflow_service()
                    service_terminal = service.cancel_operation(
                        operation_ref=service_operation
                    )
                    service_terminal = _validate_service_terminal(service_terminal)
            except BaseException as error:
                cleanup_errors.append(error)
            try:
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

        provider_cleanup_refs = _provider_cleanup_refs(service_terminal)
        counts = self.resource_counts()
        receipt = compose_benchmark_v2_attempt_cleanup_receipt(
            attempt_ref=attempt_ref,
            reason=normalized_reason,
            service_terminal_ref=(
                _content_ref(service_terminal, name="workflow service terminal result")
                if isinstance(service_terminal, Mapping)
                else None
            ),
            window_cleanup_ref=(
                _content_ref(window_cleanup, name="window cleanup receipt")
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
                "content_sha256": str(identity["capture_lineage_ref"]["content_sha256"]),
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
                        "process_identity": deepcopy(owner["process_identity"]),
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


def _validate_probe_trigger(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PROBE_TRIGGER_FIELDS:
        raise ValueError("benchmark probe trigger receipt is not closed")
    trigger = deepcopy(dict(value))
    if (
        trigger["contract_version"] != _PROBE_TRIGGER_CONTRACT
        or trigger["outcome"] != "safe_stopped"
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
        "service_terminal_ref",
        "cleanup_binding_ref",
        "attempt_event_ref",
    ):
        trigger[name] = _sealed_parent(trigger[name], name=f"probe trigger {name}")
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


def _read_exact_dispatch_receipt(
    *,
    journal_path: Path,
    provider: str,
    context_projection: Mapping[str, object],
) -> dict[str, Any] | None:
    if not journal_path.exists():
        return None
    raw = journal_path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("benchmark dispatch journal is incomplete")
    projection = validate_benchmark_v2_provider_dispatch_context_projection(
        context_projection
    )
    if projection["provider"] != provider:
        raise ValueError("benchmark probe dispatch context provider is stale")
    expected_operation = projection["operation_ref"]
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    provider_rows = 0
    for raw_line in raw.splitlines():
        try:
            decoded = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("benchmark dispatch journal is corrupt") from error
        if canonical_json_bytes(decoded) != raw_line or not isinstance(decoded, Mapping):
            raise ValueError("benchmark dispatch journal is not canonical")
        receipt = deepcopy(dict(decoded))
        required = {
            "contract_version",
            "provider",
            "dispatch_index",
            "operation_ref",
            "window_attestation_ref",
            "provider_runtime_attestation_ref",
            "predecessor_content_sha256",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        if set(receipt) != required or (
            receipt["contract_version"]
            != "benchmark_v2_provider_dispatch_receipt_v1"
            or receipt["artifact_is_authorization"] is not False
            or receipt["execute_binding_enabled"] is not False
            or receipt["content_sha256"] != content_sha256(receipt)
        ):
            raise ValueError("benchmark dispatch receipt is invalid")
        index = receipt["dispatch_index"]
        predecessor = receipt["predecessor_content_sha256"]
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 1
            or not isinstance(predecessor, str)
            or len(predecessor) != 64
        ):
            raise ValueError("benchmark dispatch receipt sequence is invalid")
        receipt["window_attestation_ref"] = _sealed_parent(
            receipt["window_attestation_ref"], name="dispatch window attestation"
        )
        receipt["provider_runtime_attestation_ref"] = _sealed_parent(
            receipt["provider_runtime_attestation_ref"],
            name="dispatch provider runtime attestation",
        )
        digest = str(receipt["content_sha256"])
        if digest in seen:
            raise ValueError("benchmark dispatch journal contains duplicate receipts")
        seen.add(digest)
        if receipt["provider"] == provider:
            provider_rows += 1
            if receipt["operation_ref"] != expected_operation:
                raise ValueError(
                    "benchmark probe dispatch receipt operation lineage is stale"
                )
            matches.append(receipt)
    if not matches:
        if provider_rows:
            raise ValueError("benchmark probe provider receipt was not usable")
        return None
    if len(matches) != 1:
        raise ValueError("benchmark probe provider already dispatched more than once")
    if matches[0]["dispatch_index"] != 1:
        raise ValueError("benchmark probe did not observe the first provider dispatch")
    if (
        matches[0]["predecessor_content_sha256"]
        != projection["context_content_sha256"]
    ):
        raise ValueError("benchmark probe first dispatch predecessor context is stale")
    return matches[0]


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
            cleanup[name] = _sealed_parent(
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


def _service_terminal_from_events(
    events: list[Mapping[str, object]],
) -> dict[str, Any] | None:
    for event in reversed(events):
        if event.get("event_kind") != "probe_triggered":
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
    for name in ("worker_cleanup_ref", "provider_cleanup_ref"):
        value = cleanup.get(name)
        if value is not None:
            if not isinstance(value, Mapping):
                raise ValueError("workflow service terminal cleanup proof is unavailable")
            result.append(_sealed_parent(value, name=name))
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
