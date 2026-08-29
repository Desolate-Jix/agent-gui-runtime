from __future__ import annotations

from copy import deepcopy
import inspect
from pathlib import Path
from typing import Mapping

import pytest

from app.learn.hybrid.benchmark_v2_contracts import content_sha256


def _sealed(value: dict[str, object]) -> dict[str, object]:
    result = deepcopy(value)
    result["content_sha256"] = content_sha256(result)
    return result


def _identity(identifier: str, digit: str) -> dict[str, str]:
    return {"id": identifier, "content_sha256": digit * 64}


def _operation_ref(
    *,
    revision: int,
    task_index: int,
    predecessor: dict[str, object] | None,
    binding: dict[str, object],
    request_ref: dict[str, object],
) -> dict[str, object]:
    from app.learn.hybrid.benchmark_v2_incumbent_operation import (
        compose_benchmark_v2_workflow_service_operation_ref,
    )

    return compose_benchmark_v2_workflow_service_operation_ref(
        mode="hybrid_v1_1",
        run_id=str(binding["run_id"]),
        stage=str(binding["stage"]),
        operation_id=str(binding["operation_id"]),
        workflow_state_ref={
            "run_id": str(binding["run_id"]),
            "revision": revision,
            "content_sha256": f"{task_index + 1:x}" * 64,
        },
        stage_execution_ref={
            "run_id": str(binding["run_id"]),
            "stage": str(binding["stage"]),
            "operation_id": str(binding["operation_id"]),
            "revision": revision,
            "content_sha256": f"{task_index + 6:x}" * 64,
        },
        request_ref=request_ref,
        window_binding_ref=binding["window_binding_ref"],
        capture_ref=binding["capture_ref"],
        worker_ref=_sealed(
            {
                "worker_id": f"worker-{task_index}",
                "model_request_id": f"request-{task_index}",
                "payload_sha256": f"{task_index + 1:x}" * 64,
            }
        ),
        status="pending",
        predecessor_operation_ref=predecessor,
    )


class _ProbeService:
    tasks = [
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
        "panel_learning_calibration_sequence",
        "panel_learning_hybrid_review_projection",
    ]

    def __init__(self) -> None:
        self.index = 0
        self.refs: list[dict[str, object]] = []
        self.start_calls = 0
        self.continue_calls = 0
        self.cancel_calls = 0
        self.lookup_calls = 0
        self.started_screen_group: dict[str, object] | None = None
        self.started_window_binding: dict[str, object] | None = None
        self.dispatch_receipt: dict[str, object] | None = None

    def _cleanup_refs(self, operation: Mapping[str, object]) -> dict[str, object]:
        worker = operation["worker_ref"]
        worker_cleanup = _sealed(
            {
                "contract_version": "benchmark_v2_hybrid_worker_cleanup_ref_v1",
                "status": "closed",
                "worker_id": worker["worker_id"],
                "model_request_id": worker["model_request_id"],
                "payload_sha256": worker["payload_sha256"],
                "backend_compute_termination": "terminated",
                "model_service_compute_termination": "terminated",
            }
        )
        receipt = self.dispatch_receipt
        if receipt is None:
            provider_cleanup = None
        else:
            runtime_owner_ref = {
                "content_sha256": receipt["provider_runtime_attestation_ref"][
                    "content_sha256"
                ]
            }
            cleanup_receipt = _sealed(
                {
                    "contract_version": (
                        "benchmark_v2_hybrid_provider_cleanup_receipt_v1"
                    ),
                    "worker_id": worker["worker_id"],
                    "model_request_id": worker["model_request_id"],
                    "payload_sha256": worker["payload_sha256"],
                    "dispatch_receipt_ref": {
                        "content_sha256": receipt["content_sha256"]
                    },
                    "runtime_owner_ref": runtime_owner_ref,
                    "outcome": "verified_exact_process_exited",
                }
            )
            provider_cleanup = _sealed(
                {
                    "contract_version": "benchmark_provider_cleanup_ref_v1",
                    "status": "cleanup_verified",
                    "outcome": "verified_exact_process_exited",
                    "authority_kind": (
                        "benchmark_v2_workflow_service_dispatch_cleanup"
                    ),
                    "run_id": operation["run_id"],
                    "stage": operation["stage"],
                    "operation_id": operation["operation_id"],
                    "worker_id": worker["worker_id"],
                    "model_request_id": worker["model_request_id"],
                    "payload_sha256": worker["payload_sha256"],
                    "reservation_ref": {
                        "content_sha256": receipt["predecessor_content_sha256"]
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
        return {
            "worker_cleanup_ref": worker_cleanup,
            "provider_cleanup_ref": provider_cleanup,
        }

    def _step(self) -> dict[str, object]:
        from app.learn.hybrid.benchmark_v2_incumbent_operation import (
            compose_benchmark_v2_provider_dispatch_context_projection,
        )

        task = self.tasks[self.index]
        provider = {
            "panel_learning_hybrid_omni_discovery": "omni",
            "panel_learning_hybrid_qwen_binding": "qwen",
            "panel_learning_calibration_sequence": "vista",
        }.get(task)
        projection = None
        if provider is not None:
            service_operation = self.refs[self.index]
            issued_operation = {
                "run_id": service_operation["run_id"],
                "stage": service_operation["stage"],
                "operation_id": service_operation["operation_id"],
                "revision": service_operation["workflow_state_ref"]["revision"] - 1,
                "window_binding_ref": deepcopy(
                    service_operation["window_binding_ref"]
                ),
                "capture_ref": deepcopy(service_operation["capture_ref"]),
            }
            issued_operation["content_sha256"] = content_sha256(issued_operation)
            projection = compose_benchmark_v2_provider_dispatch_context_projection(
                provider=provider,
                context_content_sha256=content_sha256(
                    {
                        "provider": provider,
                        "operation_ref": issued_operation,
                    }
                ),
                operation_ref=issued_operation,
            )
        return {
            "operation_ref": deepcopy(self.refs[self.index]),
            "observed_task_kind": task,
            "provider_dispatch_context_projection": projection,
            "status": "pending",
        }

    def start_hybrid_operation(self, **kwargs: object) -> dict[str, object]:
        self.start_calls += 1
        self.started_screen_group = deepcopy(kwargs["screen_group"])
        self.started_window_binding = deepcopy(kwargs["window_binding"])
        if not self.refs:
            binding = deepcopy(kwargs["window_binding"])
            screen_group = kwargs["screen_group"]
            request_ref = deepcopy(screen_group["request_ref"])
            predecessor = None
            for index in range(len(self.tasks)):
                current = _operation_ref(
                    revision=7 + index,
                    task_index=index,
                    predecessor=predecessor,
                    binding=binding,
                    request_ref=request_ref,
                )
                self.refs.append(current)
                predecessor = current
        return self._step()

    def lookup_hybrid_operation(self, **kwargs: object) -> dict[str, object] | None:
        self.lookup_calls += 1
        if not self.refs:
            return None
        if (
            kwargs.get("screen_group") != self.started_screen_group
            or kwargs.get("window_binding") != self.started_window_binding
        ):
            raise ValueError("benchmark lookup binding is stale")
        return self._step()

    def continue_hybrid_operation(self, **_kwargs: object) -> dict[str, object]:
        self.continue_calls += 1
        self.index += 1
        return self._step()

    def cancel_operation(self, **_kwargs: object) -> dict[str, object]:
        self.cancel_calls += 1
        terminal_operation = deepcopy(self.refs[self.index])
        terminal_operation["status"] = "cancelled"
        terminal_operation["content_sha256"] = content_sha256(terminal_operation)
        return _sealed(
            {
                "status": "cancelled",
                "operation_ref": terminal_operation,
                "provider_dispatch_context_projection": self._step()[
                    "provider_dispatch_context_projection"
                ],
                "cleanup_refs": self._cleanup_refs(terminal_operation),
            }
        )


class _LostContinueService(_ProbeService):
    def __init__(self) -> None:
        super().__init__()
        self.lost = True
        self.consumed: dict[str, object] | None = None
        self.producer_advances = 0

    def continue_hybrid_operation(self, **kwargs: object) -> dict[str, object]:
        self.continue_calls += 1
        operation_ref = kwargs.get("operation_ref")
        if self.lost:
            self.lost = False
            self.consumed = deepcopy(operation_ref)
            self.index += 1
            self.producer_advances += 1
            raise ConnectionError("continuation response lost")
        if operation_ref != self.consumed:
            raise ValueError("continuation replay ref is stale")
        return self._step()

    def cancel_operation(self, **kwargs: object) -> dict[str, object]:
        self.cancel_calls += 1
        if kwargs.get("operation_ref") != self.refs[self.index]:
            raise ValueError("cancel operation ref is stale")
        terminal_operation = deepcopy(self.refs[self.index])
        terminal_operation["status"] = "cancelled"
        terminal_operation["content_sha256"] = content_sha256(terminal_operation)
        return _sealed(
            {
                "status": "cancelled",
                "operation_ref": terminal_operation,
                "provider_dispatch_context_projection": self._step()[
                    "provider_dispatch_context_projection"
                ],
                "cleanup_refs": self._cleanup_refs(terminal_operation),
            }
        )


class _CrashBeforeCancelService(_ProbeService):
    def __init__(self) -> None:
        super().__init__()
        self.cancel_attempts = 0

    def cancel_operation(self, **kwargs: object) -> dict[str, object]:
        self.cancel_attempts += 1
        if self.cancel_attempts == 1:
            raise ConnectionError("crash after recovered checkpoint")
        return super().cancel_operation(**kwargs)


class _InvalidTerminalOnceService(_ProbeService):
    def __init__(self, mutation: str) -> None:
        super().__init__()
        self.mutation = mutation
        self.invalid_returned = False

    def cancel_operation(self, **kwargs: object) -> dict[str, object]:
        if self.invalid_returned:
            return super().cancel_operation(**kwargs)
        self.cancel_calls += 1
        self.invalid_returned = True
        terminal = super().cancel_operation(**kwargs)
        self.cancel_calls -= 1
        if self.mutation == "complete":
            terminal["status"] = "complete"
            terminal["operation_ref"]["status"] = "complete"
        elif self.mutation == "cross_operation":
            terminal["operation_ref"]["operation_id"] = "other-operation"
        elif self.mutation == "unprovable_incarnation":
            cleanup = terminal["cleanup_refs"]["worker_cleanup_ref"]
            cleanup["backend_compute_termination"] = "not_covered"
            cleanup["model_service_compute_termination"] = "not_covered"
            cleanup["content_sha256"] = content_sha256(cleanup)
        elif self.mutation == "worker_model_request":
            cleanup = terminal["cleanup_refs"]["worker_cleanup_ref"]
            cleanup["model_request_id"] = "request-from-another-incarnation"
            cleanup["content_sha256"] = content_sha256(cleanup)
        elif self.mutation == "provider_model_request":
            cleanup = terminal["cleanup_refs"]["provider_cleanup_ref"]
            cleanup["model_request_id"] = "request-from-another-incarnation"
            cleanup["content_sha256"] = content_sha256(cleanup)
        elif self.mutation == "provider_runtime_owner":
            cleanup = terminal["cleanup_refs"]["provider_cleanup_ref"]
            cleanup["runtime_owner_ref"] = {"content_sha256": "f" * 64}
            cleanup["content_sha256"] = content_sha256(cleanup)
        else:  # pragma: no cover - test helper guard
            raise AssertionError(self.mutation)
        terminal["operation_ref"]["content_sha256"] = content_sha256(
            terminal["operation_ref"]
        )
        terminal["content_sha256"] = content_sha256(terminal)
        return terminal


class _FailCancelOnceService(_ProbeService):
    def __init__(self) -> None:
        super().__init__()
        self.cancel_attempts = 0

    def cancel_operation(self, **kwargs: object) -> dict[str, object]:
        self.cancel_attempts += 1
        if self.cancel_attempts == 1:
            raise ConnectionError("service cancel unavailable")
        return super().cancel_operation(**kwargs)


def _write_dispatch_journal(
    *,
    runtime_module: object,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    context: dict[str, object],
    provider: str,
    pid: int,
    service: _ProbeService | None = None,
) -> dict[str, object]:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as dispatch

    del runtime_module
    monkeypatch.setattr(dispatch, "PROJECT_ROOT", project_root.resolve())
    projection = context["provider_dispatch_context_projection"]
    dispatch_operation = deepcopy(projection["operation_ref"])
    identity = {"pid": pid, "create_time_ns": 5000}
    if provider == "omni":
        snapshot = _sealed(
            {
                "contract_version": "omniparser_installed_configuration_snapshot_v1",
                "profile_id": "omni-test-profile",
                "interpreter_path": str((project_root / "omni-python.exe").resolve()),
                "worker_script_path": str((project_root / "omni-worker.py").resolve()),
                "code_path": str((project_root / "omni-code").resolve()),
                "weights_path": str((project_root / "omni-weights").resolve()),
                "cache_path": str((project_root / "omni-cache").resolve()),
                "minimum_free_gpu_gib": 0,
                "is_available": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        runtime_identity = dispatch.compose_benchmark_provider_runtime_identity(
            provider="omni",
            lease_identity=None,
            profile_ref=None,
            listener_owner=None,
            process_identities=[identity],
            process_scope={
                "scope_name": f"scope-omni-{pid}",
                "member_pids": [pid],
                "process_identities": [identity],
            },
        )
        runtime_attestation = {
            "runtime_identity": runtime_identity,
            "profile": {
                "profile_id": snapshot["profile_id"],
                "profile_sha256": snapshot["content_sha256"],
                "profile_payload_sha256": snapshot["content_sha256"],
            },
            "installed_configuration_snapshot": snapshot,
        }
    elif provider == "qwen":
        profile_sha = "c" * 64
        runtime_identity = dispatch.compose_benchmark_provider_runtime_identity(
            provider="qwen",
            lease_identity={
                "lease_id": f"qwen-lease-{pid}",
                "incarnation_id": f"qwen-incarnation-{pid}",
                "owner_request_id": f"qwen-request-{pid}",
            },
            profile_ref={"content_sha256": profile_sha},
            listener_owner={
                "host": "127.0.0.1",
                "port": 18000 + (pid % 1000),
                "process_identities": [identity],
            },
            process_identities=[identity],
            process_scope={
                "scope_name": f"scope-qwen-{pid}",
                "member_pids": [pid],
                "process_identities": [identity],
            },
        )
        runtime_attestation = {
            "runtime_identity": runtime_identity,
            "profile": {
                "profile_id": "qwen-test-profile",
                "profile_sha256": profile_sha,
                "profile_payload_sha256": profile_sha,
            },
            "installed_configuration_snapshot": None,
        }
    else:
        profile_sha = "e" * 64
        runtime_identity = dispatch.compose_benchmark_provider_runtime_identity(
            provider="vista",
            lease_identity={
                "incarnation_id": f"vista-incarnation-{pid}",
                "lease_content_sha256": "f" * 64,
            },
            profile_ref={"content_sha256": profile_sha},
            listener_owner={
                "host": "127.0.0.1",
                "port": 19000 + (pid % 1000),
                "process_identities": [identity],
            },
            process_identities=[identity],
            process_scope={
                "scope_name": f"scope-vista-{pid}",
                "member_pids": [pid],
                "process_identities": [identity],
            },
        )
        runtime_attestation = {
            "runtime_identity": runtime_identity,
            "profile": {
                "profile_id": "vista-test-profile",
                "profile_sha256": profile_sha,
                "profile_payload_sha256": profile_sha,
            },
            "installed_configuration_snapshot": None,
        }
    receipt = _sealed(
        {
            "contract_version": "benchmark_v2_provider_dispatch_receipt_v1",
            "provider": provider,
            "dispatch_index": 1,
            "operation_ref": dispatch_operation,
            "window_attestation_ref": {"content_sha256": "a" * 64},
            "provider_runtime_attestation_ref": {
                "content_sha256": runtime_identity["content_sha256"]
            },
            "predecessor_content_sha256": projection["context_content_sha256"],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    parent = dispatch._compose_dispatch_runtime_parent(
        provider=provider,
        operation_ref=dispatch_operation,
        receipt=receipt,
        runtime_attestation=runtime_attestation,
    )
    dispatch._commit_dispatch_transaction(
        journal_path=dispatch._fixed_dispatch_journal_path(dispatch_operation),
        receipt=receipt,
        runtime_parent=parent,
    )
    if service is not None:
        service.dispatch_receipt = deepcopy(receipt)
    return receipt


def _prepare_service_start_intent(
    *,
    runtime_module: object,
    runtime: object,
    manifest: Mapping[str, object],
    attempt: dict[str, object],
    attempt_dir: Path,
) -> tuple[object, dict[str, object], dict[str, object]]:
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt,
        attempt_dir=attempt_dir,
    )
    screen_group = deepcopy(next(iterator))
    window_binding = deepcopy(runtime.open_screen_group(provider_group=screen_group))
    runtime_module.append_benchmark_v2_attempt_event(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=runtime._project_root,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
        phase="prepared",
        event_kind="service_start_intent",
        resource_ref=runtime_module._runtime_resource_ref(
            "workflow_service_start_intent",
            {
                "screen_group": screen_group,
                "window_binding": window_binding,
            },
        ),
    )
    return iterator, screen_group, window_binding


def test_u2_runtime_public_probe_surface_is_exact() -> None:
    from app.learn.hybrid.benchmark_v2_runtime import (
        BenchmarkV2ProductionRuntimePort,
    )

    expected = {
        "begin_probe": [
            "self",
            "provider_id",
            "probe_kind",
            "provider_manifest",
            "attempt_ref",
            "attempt_dir",
        ],
        "read_server_journal": ["self", "probe_context"],
        "trigger_probe": [
            "self",
            "probe_context",
            "probe_kind",
            "request_in_flight_journal",
        ],
        "cleanup_attempt": ["self", "attempt", "reason"],
        "resource_counts": ["self"],
    }
    for name, parameters in expected.items():
        assert list(
            inspect.signature(getattr(BenchmarkV2ProductionRuntimePort, name)).parameters
        ) == parameters


def test_prepared_attempt_without_window_cleans_to_stable_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    attempt = _sealed({"attempt_id": "attempt-prepared-only"})
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-prepared-only").resolve(),
    )
    receipt = runtime.cleanup_attempt(attempt=attempt, reason="crash_before_window")
    assert receipt["cleanup_status"] == "stable_zero"
    assert windows.active == 0
    with pytest.raises(ValueError, match="terminal"):
        next(iterator)
    iterator.close()


def test_attempt_resource_journal_is_closed_durable_and_idempotent(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        append_benchmark_v2_attempt_event,
        read_benchmark_v2_attempt_journal,
    )

    attempt = _sealed({"attempt_id": "attempt-u2"})
    journal = (tmp_path / "attempt.jsonl").resolve()
    prepared_resource = _sealed(
        {"attempt_dir": str((tmp_path / "attempt").resolve())}
    )
    prepared = append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="prepared",
        event_kind="attempt_prepared",
        resource_ref=prepared_resource,
    )
    replay = append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="prepared",
        event_kind="attempt_prepared",
        resource_ref=prepared_resource,
    )
    request = append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="request_in_flight",
        event_kind="provider_request_in_flight",
        provider_id="qwen",
        probe_kind="cancel",
        resource_ref=_sealed({"dispatch_receipt_ref": _sealed({"provider": "qwen"})}),
    )

    assert replay == prepared
    assert request["sequence"] == 2
    assert request["predecessor_content_sha256"] == prepared["content_sha256"]
    assert read_benchmark_v2_attempt_journal(
        journal_path=journal,
        attempt_ref=attempt,
    ) == [prepared, request]

    stale_attempt = _sealed({"attempt_id": "attempt-other"})
    with pytest.raises(ValueError, match="attempt"):
        read_benchmark_v2_attempt_journal(
            journal_path=journal,
            attempt_ref=stale_attempt,
        )


def test_probe_trigger_intent_replay_is_journal_wide_idempotent(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        append_benchmark_v2_attempt_event,
        read_benchmark_v2_attempt_journal,
    )

    attempt = _sealed({"attempt_id": "attempt-trigger-intent-replay"})
    journal = (tmp_path / "attempt.jsonl").resolve()
    append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="prepared",
        event_kind="attempt_prepared",
        resource_ref=_sealed({"attempt_dir": str(tmp_path.resolve())}),
    )
    intent_resource = _sealed({"intent": "first"})
    intent = append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="request_in_flight",
        event_kind="probe_trigger_intent",
        provider_id="omni",
        probe_kind="cancel",
        resource_ref=intent_resource,
    )
    append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="request_in_flight",
        event_kind="provider_request_in_flight",
        provider_id="omni",
        probe_kind="cancel",
        resource_ref=_sealed({"request": "in-flight"}),
    )

    replay = append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="request_in_flight",
        event_kind="probe_trigger_intent",
        provider_id="omni",
        probe_kind="cancel",
        resource_ref=intent_resource,
    )
    events = read_benchmark_v2_attempt_journal(
        journal_path=journal,
        attempt_ref=attempt,
    )

    assert replay == intent
    assert [event["event_kind"] for event in events] == [
        "attempt_prepared",
        "probe_trigger_intent",
        "provider_request_in_flight",
    ]


def test_probe_trigger_intent_rejects_different_journal_wide_replay(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        append_benchmark_v2_attempt_event,
        read_benchmark_v2_attempt_journal,
    )

    attempt = _sealed({"attempt_id": "attempt-trigger-intent-conflict"})
    journal = (tmp_path / "attempt.jsonl").resolve()
    append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="prepared",
        event_kind="attempt_prepared",
        resource_ref=_sealed({"attempt_dir": str(tmp_path.resolve())}),
    )
    append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="request_in_flight",
        event_kind="probe_trigger_intent",
        provider_id="omni",
        probe_kind="cancel",
        resource_ref=_sealed({"intent": "first"}),
    )
    append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="request_in_flight",
        event_kind="provider_request_in_flight",
        provider_id="omni",
        probe_kind="cancel",
        resource_ref=_sealed({"request": "in-flight"}),
    )

    with pytest.raises(ValueError, match="trigger intent"):
        append_benchmark_v2_attempt_event(
            journal_path=journal,
            attempt_ref=attempt,
            phase="request_in_flight",
            event_kind="probe_trigger_intent",
            provider_id="omni",
            probe_kind="cancel",
            resource_ref=_sealed({"intent": "different"}),
        )

    assert len(
        read_benchmark_v2_attempt_journal(
            journal_path=journal,
            attempt_ref=attempt,
        )
    ) == 3


def test_attempt_journal_rejects_phase_regression_and_short_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle

    attempt = _sealed({"attempt_id": "attempt-u2-short"})
    journal = (tmp_path / "attempt.jsonl").resolve()
    lifecycle.append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="prepared",
        event_kind="attempt_prepared",
        resource_ref=_sealed({"attempt_dir": str(tmp_path.resolve())}),
    )
    lifecycle.append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="request_in_flight",
        event_kind="provider_request_in_flight",
        provider_id="omni",
        probe_kind="timeout",
        resource_ref=_sealed({"dispatch_receipt_ref": _sealed({"provider": "omni"})}),
    )
    with pytest.raises(ValueError, match="phase"):
        lifecycle.append_benchmark_v2_attempt_event(
            journal_path=journal,
            attempt_ref=attempt,
            phase="prepared",
            event_kind="service_started",
            resource_ref=_sealed({"operation_ref": _sealed({"operation_id": "op"})}),
        )

    fresh = (tmp_path / "short.jsonl").resolve()

    class _ShortStream:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def write(self, raw: bytes) -> int:
            return len(raw) - 1

        def fileno(self) -> int:
            return 1

    monkeypatch.setattr(Path, "open", lambda self, *args, **kwargs: _ShortStream())
    fsync_calls: list[int] = []
    monkeypatch.setattr(lifecycle.os, "fsync", lambda value: fsync_calls.append(value))
    with pytest.raises(OSError, match="short"):
        lifecycle.append_benchmark_v2_attempt_event(
            journal_path=fresh,
            attempt_ref=attempt,
            phase="prepared",
            event_kind="attempt_prepared",
            resource_ref=_sealed({"attempt_dir": str(tmp_path.resolve())}),
        )
    assert fsync_calls == []


def test_cleanup_receipt_requires_exact_stable_zero_counts() -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        compose_benchmark_v2_attempt_cleanup_receipt,
    )

    attempt = _sealed({"attempt_id": "attempt-u2-clean"})
    receipt = compose_benchmark_v2_attempt_cleanup_receipt(
        attempt_ref=attempt,
        reason="probe_cancelled",
        service_terminal_ref=_sealed({"status": "cancelled"}),
        window_cleanup_ref=_sealed({"cleanup_status": "verified"}),
        provider_cleanup_refs=[_sealed({"provider": "qwen", "status": "closed"})],
        resource_counts={
            "service_operations": 0,
            "windows": 0,
            "providers": 0,
            "listeners": 0,
            "leases": 0,
        },
    )
    assert receipt["cleanup_status"] == "stable_zero"
    assert receipt["lost_response_policy"] == (
        "fresh_reconcile_safe_stop_no_blind_retry"
    )
    assert receipt["artifact_is_authorization"] is False

    stale = deepcopy(receipt["resource_counts"])
    stale["leases"] = 1
    with pytest.raises(ValueError, match="stable.zero|resource"):
        compose_benchmark_v2_attempt_cleanup_receipt(
            attempt_ref=attempt,
            reason="probe_cancelled",
            service_terminal_ref=receipt["service_terminal_ref"],
            window_cleanup_ref=receipt["window_cleanup_ref"],
            provider_cleanup_refs=receipt["provider_cleanup_refs"],
            resource_counts=stale,
        )


@pytest.mark.parametrize(
    ("provider", "expected_continues"),
    [("omni", 0), ("qwen", 1), ("vista", 3)],
)
def test_probe_uses_public_workflow_cascade_and_idempotent_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    expected_continues: int,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as dispatch_module
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
        raising=False,
    )
    attempt = _sealed(
        {"attempt_id": f"attempt-{provider}", "partition": "regression"}
    )

    context = runtime.begin_probe(
        provider_id=provider,
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / f"attempt-{provider}").resolve(),
    )

    assert context["provider_id"] == provider
    assert service.start_calls == 1
    assert service.continue_calls == expected_continues
    assert windows.active == 1
    assert runtime.resource_counts() == {
        "service_operations": 1,
        "windows": 1,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }

    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider=provider,
        pid=4000 + expected_continues,
        service=service,
    )

    in_flight = runtime.read_server_journal(probe_context=context)
    assert in_flight["request_state"] == "request_in_flight"
    triggered = runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=in_flight,
    )
    assert triggered["outcome"] == "safe_stopped"
    first = runtime.cleanup_attempt(attempt=attempt, reason="probe_cancelled")
    second = runtime.cleanup_attempt(attempt=attempt, reason="probe_cancelled")

    assert first == second
    assert first["cleanup_status"] == "stable_zero"
    assert service.cancel_calls == 1
    assert windows.active == 0
    assert runtime.resource_counts() == {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }


def test_probe_persists_exact_non_authorizing_trigger_intent_before_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as dispatch_module
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        read_benchmark_v2_attempt_journal,
    )
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-trigger-intent", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-trigger-intent").resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4512,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)
    journal_path = runtime_module._benchmark_v2_attempt_journal_path(
        project_root=tmp_path,
        attempt_ref=attempt,
    )
    dispatch_parent_path = dispatch_module._dispatch_artifact_path(
        context["provider_dispatch_context_projection"]["operation_ref"],
        "omni",
        1,
        "runtime-parent",
    )
    dispatch_parent = dispatch_module._read_canonical_artifact(
        dispatch_parent_path,
        dispatch_module._validate_dispatch_runtime_parent,
        "benchmark dispatch runtime parent",
    )
    original_cancel = service.cancel_operation

    def require_durable_intent(**kwargs: object) -> dict[str, object]:
        del kwargs
        events = read_benchmark_v2_attempt_journal(
            journal_path=journal_path, attempt_ref=attempt
        )
        intent_event = next(
            event
            for event in events
            if event["event_kind"] == "probe_trigger_intent"
        )
        intent = intent_event["resource_ref"]["value"]["trigger_intent"]
        assert intent["attempt_ref"] == attempt
        assert intent["provider_id"] == "omni"
        assert intent["probe_kind"] == "cancel"
        assert intent["operation_ref"] == context["operation_ref"]
        assert intent["request_in_flight_ref"] == request
        assert intent["dispatch_receipt_ref"] == request["dispatch_receipt_ref"]
        assert intent["dispatch_runtime_parent_ref"] == dispatch_parent
        assert intent["process_identities"] == dispatch_parent["runtime_identity"][
            "process_identities"
        ]
        assert intent["evidence_scope"] == "benchmark_probe_only_non_authorizing"
        assert intent["artifact_is_authorization"] is False
        assert intent["execute_binding_enabled"] is False
        return original_cancel(operation_ref=context["operation_ref"])

    monkeypatch.setattr(service, "cancel_operation", require_durable_intent)
    trigger = runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=request,
    )

    assert trigger["outcome"] == "safe_stopped"
    assert service.cancel_calls == 1
    assert runtime.cleanup_attempt(
        attempt=attempt, reason="trigger_intent_test"
    )["cleanup_status"] == "stable_zero"


def test_probe_read_rejects_uncommitted_dispatch_before_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as dispatch_module
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-uncommitted-dispatch", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-uncommitted-dispatch").resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4513,
        service=service,
    )
    marker_path = dispatch_module._dispatch_artifact_path(
        context["provider_dispatch_context_projection"]["operation_ref"],
        "omni",
        1,
        "commit-marker",
    )
    marker_path.unlink()

    with pytest.raises(ValueError, match="uncommitted|commit marker"):
        runtime.read_server_journal(probe_context=context)

    assert service.cancel_calls == 0
    assert runtime.cleanup_attempt(
        attempt=attempt, reason="uncommitted_dispatch_test"
    )["cleanup_status"] == "stable_zero"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("complete", "safe.stop|cancel"),
        ("cross_operation", "operation|lineage"),
        ("unprovable_incarnation", "incarnation|termination|cleanup"),
        ("worker_model_request", "model.request|worker cleanup|stale"),
        ("provider_model_request", "model.request|provider cleanup|stale"),
        ("provider_runtime_owner", "runtime.owner|incarnation|provider cleanup"),
    ],
)
def test_probe_trigger_rejects_non_safe_or_unbound_terminal_before_success_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        read_benchmark_v2_attempt_journal,
    )
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _InvalidTerminalOnceService(mutation)
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": f"attempt-invalid-trigger-{mutation}", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / f"attempt-invalid-trigger-{mutation}").resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4660,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)

    with pytest.raises(ValueError, match=message):
        runtime.trigger_probe(
            probe_context=context,
            probe_kind="cancel",
            request_in_flight_journal=request,
        )

    events = read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert "probe_triggered" not in [event["event_kind"] for event in events]
    repaired = runtime.cleanup_attempt(attempt=attempt, reason="invalid_trigger")
    assert repaired["cleanup_status"] == "stable_zero"
    assert windows.active == 0


@pytest.mark.parametrize(
    ("provider", "expected_continues", "mutation"),
    [
        ("omni", 0, "create_time"),
        ("qwen", 1, "lease"),
        ("vista", 3, "incarnation"),
    ],
)
def test_probe_read_rejects_tampered_committed_dispatch_before_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    expected_continues: int,
    mutation: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as dispatch_module
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        read_benchmark_v2_attempt_journal,
    )
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {
            "attempt_id": f"attempt-tampered-dispatch-{provider}",
            "partition": "regression",
        }
    )
    context = runtime.begin_probe(
        provider_id=provider,
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / f"attempt-tampered-dispatch-{provider}").resolve(),
    )
    assert service.continue_calls == expected_continues
    receipt = _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider=provider,
        pid=4900 + expected_continues,
        service=service,
    )
    receipt["provider_runtime_attestation_ref"] = {
        "content_sha256": {"create_time": "1", "lease": "2", "incarnation": "3"}[mutation]
        * 64
    }
    receipt["content_sha256"] = content_sha256(receipt)
    journal = dispatch_module._fixed_dispatch_journal_path(
        context["provider_dispatch_context_projection"]["operation_ref"]
    )
    journal.write_bytes(runtime_module.canonical_json_bytes(receipt) + b"\n")

    with pytest.raises(ValueError, match="corrupt|join differs|uncommitted"):
        runtime.read_server_journal(probe_context=context)

    events = read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert "probe_triggered" not in [event["event_kind"] for event in events]
    assert service.cancel_calls == 0
    repaired = runtime.cleanup_attempt(attempt=attempt, reason="tampered_dispatch")
    assert repaired["cleanup_status"] == "stable_zero"
    assert windows.active == 0


def test_cleanup_attempt_closes_exact_window_even_when_service_cancel_fails_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        read_benchmark_v2_attempt_journal,
    )
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _FailCancelOnceService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-best-effort-cleanup", "partition": "regression"}
    )
    runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-best-effort-cleanup").resolve(),
    )

    with pytest.raises(BaseExceptionGroup, match="indeterminate"):
        runtime.cleanup_attempt(attempt=attempt, reason="first_cleanup")

    assert windows.active == 0
    assert windows.close_calls == 1
    events = read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert events[-1]["event_kind"] != "attempt_terminal"
    recovered = runtime.cleanup_attempt(attempt=attempt, reason="second_cleanup")
    assert recovered["cleanup_status"] == "stable_zero"
    assert service.cancel_attempts == 2
    assert windows.close_calls == 1


@pytest.mark.parametrize("revision_delta", [-1, 1])
def test_probe_receipt_rejects_stale_or_returned_service_revision_instead_of_issued(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    revision_delta: int,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as dispatch_module
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": f"attempt-revision-{revision_delta}", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="qwen",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / f"attempt-revision-{revision_delta}").resolve(),
    )
    receipt = _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="qwen",
        pid=4770,
        service=service,
    )
    receipt["operation_ref"]["revision"] += revision_delta
    receipt["operation_ref"]["content_sha256"] = content_sha256(
        receipt["operation_ref"]
    )
    receipt["content_sha256"] = content_sha256(receipt)
    journal = dispatch_module._fixed_dispatch_journal_path(
        context["provider_dispatch_context_projection"]["operation_ref"]
    )
    journal.write_bytes(runtime_module.canonical_json_bytes(receipt) + b"\n")

    with pytest.raises(ValueError, match="operation|parent|marker"):
        runtime.read_server_journal(probe_context=context)

    cleaned = runtime.cleanup_attempt(attempt=attempt, reason="stale_revision")
    assert cleaned["cleanup_status"] == "stable_zero"
    assert windows.active == 0


def test_probe_rejects_resealed_context_projection_before_journal_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-resealed-context", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="timeout",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-resealed-context").resolve(),
    )
    mutated = deepcopy(context)
    projection = mutated["provider_dispatch_context_projection"]
    projection["operation_ref"]["revision"] -= 1
    projection["operation_ref"]["content_sha256"] = content_sha256(
        projection["operation_ref"]
    )
    projection["content_sha256"] = content_sha256(projection)
    mutated["content_sha256"] = content_sha256(mutated)

    with pytest.raises(ValueError, match="stale|cross-attempt"):
        runtime.read_server_journal(probe_context=mutated)

    cleaned = runtime.cleanup_attempt(attempt=attempt, reason="resealed_context")
    assert cleaned["cleanup_status"] == "stable_zero"
    assert windows.active == 0


def test_probe_rejects_holdout_stale_attempt_and_pid_reuse_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
        raising=False,
    )
    with pytest.raises(ValueError, match="holdout"):
        runtime.begin_probe(
            provider_id="omni",
            probe_kind="cancel",
            provider_manifest=manifest,
            attempt_ref=_sealed(
                {"attempt_id": "attempt-holdout", "partition": "holdout"}
            ),
            attempt_dir=(tmp_path / "attempt-holdout").resolve(),
        )
    with pytest.raises(ValueError, match="attempt|journal"):
        runtime.cleanup_attempt(
            attempt=_sealed({"attempt_id": "attempt-stale"}),
            reason="stale",
        )

    attempt = _sealed(
        {"attempt_id": "attempt-pid-reuse", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="timeout",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-pid-reuse").resolve(),
    )
    del context
    real_close = runtime_module.close_owned_window
    monkeypatch.setattr(
        runtime_module,
        "close_owned_window",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("PID reuse detected")),
    )
    with pytest.raises(BaseExceptionGroup, match="indeterminate") as raised:
        runtime.cleanup_attempt(attempt=attempt, reason="probe_timeout")
    assert "PID reuse" in str(raised.value.exceptions[0])
    assert windows.active == 1
    monkeypatch.setattr(runtime_module, "close_owned_window", real_close)
    recovered = runtime.cleanup_attempt(attempt=attempt, reason="probe_timeout")
    assert recovered["cleanup_status"] == "stable_zero"
    assert windows.active == 0


def test_probe_service_start_failure_reconciles_exact_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    original_append = runtime_module.append_benchmark_v2_attempt_event
    failed = False

    def fail_after_service_start(**kwargs: object):
        nonlocal failed
        if kwargs.get("event_kind") == "service_started" and not failed:
            failed = True
            raise RuntimeError("service start response checkpoint failed")
        return original_append(**kwargs)

    monkeypatch.setattr(
        runtime_module,
        "append_benchmark_v2_attempt_event",
        fail_after_service_start,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-start-failure", "partition": "regression"}
    )
    with pytest.raises(RuntimeError, match="response checkpoint"):
        runtime.begin_probe(
            provider_id="omni",
            probe_kind="cancel",
            provider_manifest=manifest,
            attempt_ref=attempt,
            attempt_dir=(tmp_path / "attempt-start-failure").resolve(),
        )

    assert service.start_calls == 1
    assert service.cancel_calls == 1
    assert windows.active == 0
    assert runtime.resource_counts() == {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }
    replay = runtime.cleanup_attempt(attempt=attempt, reason="replay")
    assert replay["cleanup_status"] == "stable_zero"
    assert service.cancel_calls == 1


def test_fresh_runtime_recovers_service_started_before_response_fsync_without_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        read_benchmark_v2_attempt_journal,
    )
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-hard-crash-after-start", "partition": "regression"}
    )
    iterator, screen_group, window_binding = _prepare_service_start_intent(
        runtime_module=runtime_module,
        runtime=runtime,
        manifest=manifest,
        attempt=attempt,
        attempt_dir=(tmp_path / "attempt-hard-crash-after-start").resolve(),
    )
    service.start_hybrid_operation(
        screen_group=screen_group,
        window_binding=window_binding,
    )

    runtime._active = None
    runtime._pending_cleanup = None
    runtime._attempt_states.clear()
    recovered_runtime = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )
    receipt = recovered_runtime.cleanup_attempt(
        attempt=attempt,
        reason="hard_crash_after_service_start",
    )

    assert receipt["cleanup_status"] == "stable_zero"
    assert service.start_calls == 1
    assert service.lookup_calls == 1
    assert service.cancel_calls == 1
    assert windows.close_calls == 1
    assert windows.active == 0
    events = read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert "service_started" not in [event["event_kind"] for event in events]
    assert [event["event_kind"] for event in events].count("service_recovered") == 1
    assert events[-1]["event_kind"] == "attempt_terminal"
    del iterator


def test_fresh_runtime_cleanup_recovers_exact_incumbent_from_durable_call_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import (
        _DurableIncumbentService,
        _runtime,
    )

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    delegate = _DurableIncumbentService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: delegate,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-incumbent-hard-crash", "partition": "regression"}
    )
    attempt_dir = (tmp_path / "attempt-incumbent-hard-crash").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt,
        attempt_dir=attempt_dir,
    )
    group = deepcopy(next(iterator))
    binding = deepcopy(runtime.open_screen_group(provider_group=group))
    paths = runtime_module._actual_screen_group_paths(
        attempt_dir=attempt_dir,
        attempt_ref=attempt,
        screen_group=str(group["screen_group"]),
    )
    intent = runtime_module._sealed_record(
        {
            "contract_version": runtime_module._ACTUAL_INTENT_CONTRACT,
            "attempt_ref": attempt,
            "provider_group": group,
            "window_binding": binding,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    intent_ref = runtime_module._write_create_only_json(paths["intent"], intent)
    service = runtime_module._ActualScreenGroupService(
        delegate=delegate,
        group=group,
        binding=binding,
        intent_ref=intent_ref,
        result_path=paths["result"],
    )
    hybrid_started = service.start_hybrid_operation(
        screen_group=group,
        window_binding=binding,
    )
    incumbent_started = service.start_incumbent_observe(
        provider_case_ref=group["case_refs"][0],
        window_binding=binding,
    )

    runtime._active = None
    runtime._pending_cleanup = None
    recovered_runtime = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )
    with pytest.raises(BaseExceptionGroup, match="indeterminate|stable-zero"):
        recovered_runtime.cleanup_attempt(
            attempt=attempt,
            reason="hard_crash_during_incumbent",
        )

    assert delegate.incumbent_start_calls == 1
    assert delegate.start_calls == 1
    assert delegate.cancel_calls == 2
    assert {
        operation["mode"] for operation in delegate.cancelled_operation_refs
    } == {"hybrid_v1_1", "incumbent_qwen_only"}
    assert {
        operation["content_sha256"] for operation in delegate.cancelled_operation_refs
    } == {
        hybrid_started["operation_ref"]["content_sha256"],
        incumbent_started["operation_ref"]["content_sha256"],
    }
    assert delegate.incumbent_lookup_calls >= 2
    assert windows.active == 0
    events = runtime_module.read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert "attempt_terminal" not in [event["event_kind"] for event in events]
    del iterator


def test_fresh_actual_cleanup_attests_each_screen_group_without_cross_group_merge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import (
        _DurableIncumbentService,
        _runtime,
    )

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    delegate = _DurableIncumbentService([])
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: delegate,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-multi-group-crash", "partition": "regression"}
    )
    attempt_dir = (tmp_path / "attempt-multi-group-crash").resolve()
    iterator = runtime.prepare_screen_groups(
        provider_manifest=manifest,
        partition="regression",
        attempt_ref=attempt,
        attempt_dir=attempt_dir,
    )

    def service_for(group: Mapping[str, object], binding: Mapping[str, object]):
        paths = runtime_module._actual_screen_group_paths(
            attempt_dir=attempt_dir,
            attempt_ref=attempt,
            screen_group=str(group["screen_group"]),
        )
        intent = runtime_module._sealed_record(
            {
                "contract_version": runtime_module._ACTUAL_INTENT_CONTRACT,
                "attempt_ref": attempt,
                "provider_group": group,
                "window_binding": binding,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        intent_ref = runtime_module._write_create_only_json(paths["intent"], intent)
        return runtime_module._ActualScreenGroupService(
            delegate=delegate,
            group=group,
            binding=binding,
            intent_ref=intent_ref,
            result_path=paths["result"],
        )

    first_group = deepcopy(next(iterator))
    first_binding = deepcopy(runtime.open_screen_group(provider_group=first_group))
    first_service = service_for(first_group, first_binding)
    first_service.start_hybrid_operation(
        screen_group=first_group,
        window_binding=first_binding,
    )
    for case_ref in first_group["case_refs"]:
        first_service.start_incumbent_observe(
            provider_case_ref=case_ref,
            window_binding=first_binding,
        )
    runtime.close_screen_group(
        window_binding=first_binding,
        reason="first_group_complete",
    )

    second_group = deepcopy(next(iterator))
    second_binding = deepcopy(runtime.open_screen_group(provider_group=second_group))
    second_service = service_for(second_group, second_binding)
    second_service.start_hybrid_operation(
        screen_group=second_group,
        window_binding=second_binding,
    )
    second_service.start_incumbent_observe(
        provider_case_ref=second_group["case_refs"][0],
        window_binding=second_binding,
    )

    runtime._active = None
    runtime._pending_cleanup = None
    recovered_runtime = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )
    with pytest.raises(BaseExceptionGroup, match="indeterminate|stable-zero"):
        recovered_runtime.cleanup_attempt(
            attempt=attempt,
            reason="second_group_crash",
        )

    assert delegate.stable_zero_operation_counts == [6, 2]
    assert delegate.cancel_calls == 8
    assert windows.active == 0
    events = runtime_module.read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert "attempt_terminal" not in [event["event_kind"] for event in events]
    del iterator


def test_service_recovered_checkpoint_retries_cancel_without_lookup_or_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        read_benchmark_v2_attempt_journal,
    )
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _CrashBeforeCancelService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-crash-after-recovered", "partition": "regression"}
    )
    iterator, screen_group, window_binding = _prepare_service_start_intent(
        runtime_module=runtime_module,
        runtime=runtime,
        manifest=manifest,
        attempt=attempt,
        attempt_dir=(tmp_path / "attempt-crash-after-recovered").resolve(),
    )
    service.start_hybrid_operation(
        screen_group=screen_group,
        window_binding=window_binding,
    )
    runtime._active = None
    runtime._pending_cleanup = None
    runtime._attempt_states.clear()
    recovered_runtime = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )

    with pytest.raises(BaseExceptionGroup, match="indeterminate") as raised:
        recovered_runtime.cleanup_attempt(
            attempt=attempt,
            reason="first_recovery",
        )
    assert "recovered checkpoint" in str(raised.value.exceptions[0])
    after_crash = read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert after_crash[-1]["event_kind"] == "service_recovered"
    assert service.lookup_calls == 1
    assert service.start_calls == 1
    assert windows.active == 0

    receipt = recovered_runtime.cleanup_attempt(
        attempt=attempt,
        reason="second_recovery",
    )
    assert receipt["cleanup_status"] == "stable_zero"
    assert service.lookup_calls == 1
    assert service.start_calls == 1
    assert service.cancel_attempts == 2
    assert service.cancel_calls == 1
    assert windows.active == 0
    del iterator


def test_service_start_intent_without_durable_binding_never_restarts_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-crash-before-start", "partition": "regression"}
    )
    iterator, _screen_group, _window_binding = _prepare_service_start_intent(
        runtime_module=runtime_module,
        runtime=runtime,
        manifest=manifest,
        attempt=attempt,
        attempt_dir=(tmp_path / "attempt-crash-before-start").resolve(),
    )
    runtime._active = None
    runtime._pending_cleanup = None
    recovered_runtime = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )

    receipt = recovered_runtime.cleanup_attempt(
        attempt=attempt,
        reason="hard_crash_before_service_start",
    )
    assert receipt["cleanup_status"] == "stable_zero"
    assert service.lookup_calls == 1
    assert service.start_calls == 0
    assert service.cancel_calls == 0
    assert windows.active == 0
    del iterator


def test_stale_service_start_intent_is_indeterminate_and_never_terminalized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        read_benchmark_v2_attempt_journal,
    )
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()

    def reject_stale_lookup(**_kwargs: object) -> None:
        service.lookup_calls += 1
        raise ValueError("benchmark lookup binding is stale")

    service.lookup_hybrid_operation = reject_stale_lookup  # type: ignore[method-assign]
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-stale-start-intent", "partition": "regression"}
    )
    iterator, _screen_group, _window_binding = _prepare_service_start_intent(
        runtime_module=runtime_module,
        runtime=runtime,
        manifest=manifest,
        attempt=attempt,
        attempt_dir=(tmp_path / "attempt-stale-start-intent").resolve(),
    )
    runtime._active = None
    runtime._pending_cleanup = None
    recovered_runtime = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )

    with pytest.raises(BaseExceptionGroup, match="indeterminate") as raised:
        recovered_runtime.cleanup_attempt(
            attempt=attempt,
            reason="stale_start_intent",
        )
    assert "stale" in str(raised.value.exceptions[0])
    events = read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert events[-1]["event_kind"] == "service_start_intent"
    assert service.start_calls == 0
    assert service.cancel_calls == 0
    assert windows.active == 0
    service.lookup_hybrid_operation = _ProbeService.lookup_hybrid_operation.__get__(
        service,
        _ProbeService,
    )
    repaired = recovered_runtime.cleanup_attempt(
        attempt=attempt,
        reason="operator_repaired_stale_intent",
    )
    assert repaired["cleanup_status"] == "stable_zero"
    assert windows.active == 0
    del iterator


def test_window_launch_checkpoint_failure_closes_exact_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    original_append = runtime_module.append_benchmark_v2_attempt_event
    failed = False

    def fail_after_owned_window(**kwargs: object):
        nonlocal failed
        result = original_append(**kwargs)
        resource = kwargs.get("resource_ref")
        value = resource.get("value") if isinstance(resource, dict) else None
        if (
            kwargs.get("event_kind") == "window_owned"
            and isinstance(value, dict)
            and value.get("ownership_state") == "owned"
            and not failed
        ):
            failed = True
            raise RuntimeError("window ownership response checkpoint failed")
        return result

    monkeypatch.setattr(
        runtime_module,
        "append_benchmark_v2_attempt_event",
        fail_after_owned_window,
    )
    with pytest.raises(RuntimeError, match="ownership response checkpoint"):
        next(
            runtime.prepare_screen_groups(
                provider_manifest=manifest,
                partition="regression",
                attempt_ref=_sealed({"attempt_id": "attempt-window-checkpoint"}),
                attempt_dir=(tmp_path / "attempt-window-checkpoint").resolve(),
            )
        )
    assert windows.active == 0
    assert windows.close_calls == 1


def test_lost_continuation_response_reconciles_before_cancel_without_new_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _LostContinueService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-lost-continuation", "partition": "regression"}
    )
    with pytest.raises(ConnectionError, match="continuation response lost"):
        runtime.begin_probe(
            provider_id="qwen",
            probe_kind="cancel",
            provider_manifest=manifest,
            attempt_ref=attempt,
            attempt_dir=(tmp_path / "attempt-lost-continuation").resolve(),
        )

    assert service.start_calls == 1
    assert service.continue_calls == 2
    assert service.producer_advances == 1
    assert service.cancel_calls == 2
    assert windows.active == 0
    assert runtime.resource_counts() == {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }


def test_terminal_journal_failure_replays_prepared_cleanup_without_side_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-terminal-replay", "partition": "regression"}
    )
    runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-terminal-replay").resolve(),
    )
    original_append = runtime_module.append_benchmark_v2_attempt_event
    failed = False

    def fail_terminal_once(**kwargs: object):
        nonlocal failed
        if kwargs.get("event_kind") == "attempt_terminal" and not failed:
            failed = True
            raise OSError("terminal fsync unavailable")
        return original_append(**kwargs)

    monkeypatch.setattr(
        runtime_module,
        "append_benchmark_v2_attempt_event",
        fail_terminal_once,
    )
    with pytest.raises(OSError, match="fsync"):
        runtime.cleanup_attempt(attempt=attempt, reason="first_cleanup")
    assert service.cancel_calls == 1
    assert windows.close_calls == 1
    recovered = runtime.cleanup_attempt(attempt=attempt, reason="second_cleanup")
    assert recovered["cleanup_status"] == "stable_zero"
    assert service.cancel_calls == 1
    assert windows.close_calls == 1
    assert runtime.resource_counts() == {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }
    assert windows.active == 0
    replay = runtime.cleanup_attempt(attempt=attempt, reason="replay")
    assert replay["cleanup_status"] == "stable_zero"
    assert service.cancel_calls == 1


def test_probe_lost_trigger_response_uses_durable_reconciliation_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-lost-response", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="qwen",
        probe_kind="timeout",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-lost-response").resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="qwen",
        pid=4555,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)
    original_append = runtime_module.append_benchmark_v2_attempt_event
    lost = False

    def lose_after_durable_trigger(**kwargs: object):
        nonlocal lost
        result = original_append(**kwargs)
        if kwargs.get("event_kind") == "probe_triggered" and not lost:
            lost = True
            raise ConnectionError("trigger response lost")
        return result

    monkeypatch.setattr(
        runtime_module,
        "append_benchmark_v2_attempt_event",
        lose_after_durable_trigger,
    )
    with pytest.raises(ConnectionError, match="response lost"):
        runtime.trigger_probe(
            probe_context=context,
            probe_kind="timeout",
            request_in_flight_journal=request,
        )

    assert service.cancel_calls == 1
    runtime._active = None
    runtime._pending_cleanup = None
    runtime._attempt_states.clear()
    recovered_runtime = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )
    receipt = recovered_runtime.cleanup_attempt(
        attempt=attempt,
        reason="lost_response",
    )
    assert receipt["cleanup_status"] == "stable_zero"
    assert receipt["lost_response_policy"] == (
        "fresh_reconcile_safe_stop_no_blind_retry"
    )
    assert service.cancel_calls == 1
    assert windows.active == 0
    assert recovered_runtime.resource_counts() == {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }
