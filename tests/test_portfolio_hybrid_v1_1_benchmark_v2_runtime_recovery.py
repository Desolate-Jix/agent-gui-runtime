from __future__ import annotations

from copy import deepcopy
import inspect
import json
from pathlib import Path
from typing import Mapping

import pytest

from app.learn.hybrid.benchmark_v2_contracts import content_sha256


def _sealed(value: dict[str, object]) -> dict[str, object]:
    result = deepcopy(value)
    result["content_sha256"] = content_sha256(result)
    return result


def _native_window_cleanup_with_large_create_time() -> dict[str, object]:
    return _sealed(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_window_cleanup_v1",
            "owner_id": "benchmark-v2-owner-regression",
            "reason": "benchmark_v2_cleanup",
            "exact_hwnd": 18745282,
            "process_identity": {
                "pid": 61844,
                "create_time_ns": 1788061836336039424,
            },
            "cleanup_subject_kind": "ready_window",
            "finalization_intent_sha256": "1" * 64,
            "process_event_sha256": "2" * 64,
            "ready_event_sha256": "3" * 64,
            "publication_content_sha256": "4" * 64,
            "cleanup_status": "verified",
            "shutdown_event_name": "benchmark-v2-shutdown-regression",
            "shutdown_event_signaled": True,
            "shutdown_event_error_code": 0,
            "shutdown_event_handle_closed": True,
            "enum_windows_exact_hwnd_absent": True,
            "matching_owned_windows_after": [],
            "member_pids_after": [],
            "stable_zero_observations": 3,
            "scope_absent_after_owner_close": True,
            "process_handle_closed": True,
            "job_handle_closed": True,
            "active_listeners_after": [],
            "listener_or_lease_residue": [],
            "outer_owner_python_finally_observed": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def _actual_stable_zero_from_existing_service_helper(
    *, suffix: str
) -> tuple[dict[str, object], list[dict[str, object]]]:
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import (
        _ActualService,
        _actual_operation,
    )

    binding = {
        "stage": "screen_understanding",
        "window_binding_ref": {
            "id": f"window-{suffix}",
            "content_sha256": "a" * 64,
        },
        "capture_ref": {
            "id": f"capture-{suffix}",
            "content_sha256": "b" * 64,
        },
    }
    operations = []
    for index in range(6):
        operation_id = (
            f"hybrid-{suffix}" if index == 0 else f"incumbent-{suffix}-{index}"
        )
        operations.append(
            _actual_operation(
                mode="hybrid_v1_1" if index == 0 else "incumbent_qwen_only",
                operation_id=operation_id,
                request_ref={
                    "id": f"case-{suffix}-{index}",
                    "content_sha256": f"{index + 1:x}" * 64,
                },
                binding={
                    **binding,
                    "run_id": f"run-actual-parent-{suffix}-{index}",
                },
                revision=index + 1,
            )
        )
    service = _ActualService([])
    terminals = [
        service.cancel_operation(operation_ref=operation) for operation in operations
    ]
    attestation = service.attest_actual_operations_stable_zero(
        operation_refs=[terminal["operation_ref"] for terminal in terminals]
    )
    return attestation, terminals


@pytest.fixture(autouse=True)
def _use_producer_complete_window_cleanup_receipts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _Windows

    original_close = _Windows.close

    def close(
        windows: object, *, journal_path: Path, reason: str
    ) -> dict[str, object]:
        original_close(windows, journal_path=journal_path, reason=reason)
        receipt = _native_window_cleanup_with_large_create_time()
        receipt["reason"] = reason
        receipt["content_sha256"] = content_sha256(receipt)
        return receipt

    monkeypatch.setattr(_Windows, "close", close)


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
                "run_id": operation["run_id"],
                "stage": operation["stage"],
                "operation_id": operation["operation_id"],
                "worker_id": worker["worker_id"],
                "model_request_id": worker["model_request_id"],
                "payload_sha256": worker["payload_sha256"],
                "backend_compute_termination": "terminated",
                "model_service_compute_termination": "terminated",
                "cancellation_ref": {"content_sha256": "9" * 64},
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
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
    process_identities: list[dict[str, int]] | None = None,
) -> dict[str, object]:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as dispatch

    del runtime_module
    monkeypatch.setattr(dispatch, "PROJECT_ROOT", project_root.resolve())
    projection = context["provider_dispatch_context_projection"]
    dispatch_operation = deepcopy(projection["operation_ref"])
    identity = {"pid": pid, "create_time_ns": 5000}
    identities = deepcopy(process_identities or [identity])
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
            process_identities=identities,
            process_scope={
                "scope_name": f"scope-omni-{pid}",
                "member_pids": [item["pid"] for item in identities],
                "process_identities": identities,
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
                "process_identities": identities,
            },
            process_identities=identities,
            process_scope={
                "scope_name": f"scope-qwen-{pid}",
                "member_pids": [item["pid"] for item in identities],
                "process_identities": identities,
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
                "process_identities": identities,
            },
            process_identities=identities,
            process_scope={
                "scope_name": f"scope-vista-{pid}",
                "member_pids": [item["pid"] for item in identities],
                "process_identities": identities,
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


def _prepare_probe_for_absence_control(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempt_id: str,
    pid: int,
):
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed({"attempt_id": attempt_id, "partition": "regression"})
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / attempt_id).resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=pid,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)
    return runtime_module, runtime, service, windows, attempt, context, request


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
    for event_kind in (
        "provider_request_in_flight",
        "probe_trigger_observation",
    ):
        append_benchmark_v2_attempt_event(
            journal_path=journal,
            attempt_ref=attempt,
            phase="request_in_flight",
            event_kind=event_kind,
            provider_id="omni",
            probe_kind="cancel",
            resource_ref=_sealed({"event": event_kind}),
        )
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
        provider_id="qwen",
        probe_kind="cancel",
        resource_ref=_sealed({"request": "other-tuple"}),
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
        "provider_request_in_flight",
        "probe_trigger_observation",
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
    for event_kind in (
        "provider_request_in_flight",
        "probe_trigger_observation",
        "probe_trigger_intent",
    ):
        append_benchmark_v2_attempt_event(
            journal_path=journal,
            attempt_ref=attempt,
            phase="request_in_flight",
            event_kind=event_kind,
            provider_id="omni",
            probe_kind="cancel",
            resource_ref=_sealed({"event": event_kind}),
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
    ) == 4


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


def test_cleanup_projects_native_window_receipt_and_replays_terminal_once(
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
        {"attempt_id": "attempt-native-window-cleanup", "partition": "regression"}
    )
    runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-native-window-cleanup").resolve(),
    )
    native_cleanup = _native_window_cleanup_with_large_create_time()
    original_close = windows.close

    def close_with_native_receipt(
        *, journal_path: Path, reason: str
    ) -> dict[str, object]:
        original_close(journal_path=journal_path, reason=reason)
        return deepcopy(native_cleanup)

    monkeypatch.setattr(runtime_module, "close_owned_window", close_with_native_receipt)

    first = runtime.cleanup_attempt(attempt=attempt, reason="native_window_cleanup")
    second = runtime.cleanup_attempt(attempt=attempt, reason="native_window_cleanup")

    assert first == second
    assert first["cleanup_status"] == "stable_zero"
    assert first["window_cleanup_ref"] == {
        "contract_version": "benchmark_v2_cleanup_parent_ref_v1",
        "parent_kind": "window_cleanup",
        "producer_contract_version": (
            "portfolio_hybrid_benchmark_v2_window_cleanup_v1"
        ),
        "producer_content_sha256": native_cleanup["content_sha256"],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "content_sha256": first["window_cleanup_ref"]["content_sha256"],
    }
    assert "create_time_ns" not in json.dumps(first, sort_keys=True)
    assert first["service_terminal_ref"]["parent_kind"] == (
        "workflow_service_terminal"
    )
    assert [
        parent["parent_kind"] for parent in first["provider_cleanup_refs"]
    ] == ["worker_cleanup"]
    assert windows.close_calls == 1
    assert service.cancel_calls == 1
    assert runtime.resource_counts() == {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }
    events = read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert [event["event_kind"] for event in events].count("attempt_terminal") == 1


def test_cleanup_rejects_tampered_native_window_receipt_before_projection() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    tampered = _native_window_cleanup_with_large_create_time()
    tampered["reason"] = "tampered"

    with pytest.raises(ValueError, match="window cleanup receipt content SHA differs"):
        runtime_module._cleanup_parent_ref(
            tampered,
            parent_kind="window_cleanup",
            name="window cleanup receipt",
        )


def test_cleanup_parent_projection_rejects_wrong_contract_and_cross_kind() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    wrong_contract = _sealed(
        {
            "contract_version": "benchmark_v2_wrong_cleanup_v1",
            "cleanup_status": "verified",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    with pytest.raises(ValueError, match="contract|unsupported"):
        runtime_module._cleanup_parent_ref(
            wrong_contract,
            parent_kind="window_cleanup",
            name="wrong cleanup receipt",
        )

    window_cleanup = _native_window_cleanup_with_large_create_time()
    with pytest.raises(ValueError, match="kind"):
        runtime_module._cleanup_parent_ref(
            window_cleanup,
            parent_kind="provider_cleanup",
            name="cross-kind cleanup receipt",
        )


def test_cleanup_parent_projection_rejects_authorizing_producer() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    authorizing = _native_window_cleanup_with_large_create_time()
    authorizing["artifact_is_authorization"] = True
    authorizing["content_sha256"] = content_sha256(authorizing)

    with pytest.raises(ValueError, match="authorization|authorize"):
        runtime_module._cleanup_parent_ref(
            authorizing,
            parent_kind="window_cleanup",
            name="authorizing window cleanup receipt",
        )


def test_cleanup_parent_projection_accepts_production_actual_provider_and_aggregate() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    first_attestation, first_terminals = (
        _actual_stable_zero_from_existing_service_helper(suffix="first")
    )
    second_attestation, _ = _actual_stable_zero_from_existing_service_helper(
        suffix="second"
    )

    actual_parent = runtime_module._cleanup_parent_ref(
        first_attestation,
        parent_kind="actual_operations_stable_zero",
        name="actual operations stable-zero attestation",
    )
    provider_parent = runtime_module._cleanup_parent_ref(
        first_terminals[0]["cleanup_refs"]["provider_cleanup_ref"],
        parent_kind="provider_cleanup",
        name="actual provider cleanup",
    )
    aggregate = runtime_module._runtime_resource_ref(
        "actual_group_stable_zero_attestations",
        {
            "group_attestation_refs": [
                first_attestation,
                second_attestation,
            ]
        },
    )
    aggregate_parent = runtime_module._cleanup_parent_ref(
        aggregate,
        parent_kind="actual_operations_stable_zero_aggregate",
        name="actual operations stable-zero aggregate",
    )

    assert actual_parent["producer_contract_version"] == (
        "benchmark_v2_actual_operations_stable_zero_v1"
    )
    assert provider_parent["producer_contract_version"] == (
        "benchmark_provider_cleanup_ref_v1"
    )
    assert aggregate_parent["parent_kind"] == (
        "actual_operations_stable_zero_aggregate"
    )
    assert all(
        parent["artifact_is_authorization"] is False
        and parent["execute_binding_enabled"] is False
        for parent in (actual_parent, provider_parent, aggregate_parent)
    )


def test_cleanup_parent_projection_accepts_each_production_worker_contract() -> None:
    from app.learn import workflow_worker
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    _, terminals = _actual_stable_zero_from_existing_service_helper(
        suffix="workers"
    )
    cancelled = terminals[0]["cleanup_refs"]["worker_cleanup_ref"]
    provider_cleanup = terminals[0]["cleanup_refs"]["provider_cleanup_ref"]
    completed = _sealed(
        {
            "contract_version": (
                "benchmark_v2_hybrid_completed_worker_cleanup_ref_v1"
            ),
            "run_id": "run-completed",
            "stage": "screen_understanding",
            "operation_id": "operation-completed",
            "worker_id": "worker-completed",
            "model_request_id": "request-completed",
            "payload_sha256": "1" * 64,
            "worker_status": "completed",
            "runtime_attached": False,
            "result_available": True,
            "authoritative_worker_record_sha256": "2" * 64,
            "provider_cleanup_ref": {
                "content_sha256": provider_cleanup["content_sha256"]
            },
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    cancelled_reservation = _sealed(
        {
            "run_id": "run-incumbent",
            "stage": "screen_understanding",
            "operation_id": "operation-incumbent",
            "worker_id": "worker-incumbent",
        }
    )
    incumbent = workflow_worker._compose_benchmark_not_launched_receipt(
        cancelled_reservation=cancelled_reservation,
        operation_anchor={"anchor_identity_sha256": "3" * 64},
        observation={"content_sha256": "4" * 64},
    )

    parents = [
        runtime_module._cleanup_parent_ref(
            producer,
            parent_kind="worker_cleanup",
            name=name,
        )
        for producer, name in (
            (cancelled, "cancelled Hybrid worker cleanup"),
            (completed, "completed Hybrid worker cleanup"),
            (incumbent, "incumbent worker cleanup"),
        )
    ]

    assert [parent["producer_contract_version"] for parent in parents] == [
        "benchmark_v2_hybrid_worker_cleanup_ref_v1",
        "benchmark_v2_hybrid_completed_worker_cleanup_ref_v1",
        "benchmark_worker_cleanup_receipt_v1",
    ]
    assert all(parent["parent_kind"] == "worker_cleanup" for parent in parents)


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
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal
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
    assert triggered["outcome"] == "safe_stopped_exact_incarnation_absent"
    events = read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
    )
    assert "probe_trigger_terminal" in [event["event_kind"] for event in events]
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

    assert trigger["outcome"] == "safe_stopped_exact_incarnation_absent"
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
    observations = 0
    class _ExactPendingIdentity:
        def create_time(self) -> float:
            return 5000 / 1_000_000_000
    def pending_then_absent(pid: int):
        nonlocal observations
        observations += 1
        if observations == 1:
            return _ExactPendingIdentity()
        raise runtime_module.psutil.NoSuchProcess(pid)
    monkeypatch.setattr(runtime_module.psutil, "Process", pending_then_absent)
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
    receipt = recovered_runtime.cleanup_attempt(
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
    assert receipt["cleanup_status"] == "stable_zero"
    assert receipt["service_terminal_ref"]["parent_kind"] == (
        "actual_operations_cleanup_aggregate"
    )
    assert len(receipt["provider_cleanup_refs"]) == 4
    events = runtime_module.read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert [event["event_kind"] for event in events].count("attempt_terminal") == 1
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
    receipt = recovered_runtime.cleanup_attempt(
        attempt=attempt,
        reason="second_group_crash",
    )

    assert delegate.stable_zero_operation_counts == [6]
    assert delegate.cancel_calls == 8
    assert windows.active == 0
    assert receipt["cleanup_status"] == "stable_zero"
    assert receipt["service_terminal_ref"]["parent_kind"] == (
        "actual_operations_cleanup_aggregate"
    )
    assert len(receipt["provider_cleanup_refs"]) == 16
    events = runtime_module.read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    assert [event["event_kind"] for event in events].count("attempt_terminal") == 1
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

    clock = _DeterministicDeadlineClock()
    _, runtime, manifest, _, windows, _ = _runtime(
        monkeypatch,
        tmp_path,
        runtime_options={
            "monotonic_ns": clock.monotonic_ns,
            "wait_hook": clock.wait,
        },
    )
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


def test_intent_only_restart_uses_read_only_safe_stop_lookup_without_recancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已落盘 intent 且服务已安全停止时，恢复只能读取并证明，绝不再次 cancel。"""
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
        {"attempt_id": "attempt-intent-only-safe-stop", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-intent-only-safe-stop").resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4861,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)
    original_cancel = service.cancel_operation
    terminal: dict[str, object] | None = None

    def lose_terminal_response(**kwargs: object) -> dict[str, object]:
        nonlocal terminal
        terminal = original_cancel(**kwargs)
        raise ConnectionError("terminal response lost after service safe stop")

    monkeypatch.setattr(service, "cancel_operation", lose_terminal_response)
    with pytest.raises(ConnectionError, match="terminal response lost"):
        runtime.trigger_probe(
            probe_context=context,
            probe_kind="cancel",
            request_in_flight_journal=request,
        )
    assert service.cancel_calls == 1
    assert terminal is not None

    def lookup_safe_stopped(**kwargs: object) -> dict[str, object]:
        service.lookup_calls += 1
        assert kwargs["screen_group"] == service.started_screen_group
        assert kwargs["window_binding"] == service.started_window_binding
        assert terminal is not None
        return {
            "operation_ref": deepcopy(terminal["operation_ref"]),
            "status": "cancelled",
            "terminal_receipt": None,
            "cleanup_refs": deepcopy(terminal["cleanup_refs"]),
            "provider_dispatch_context_projection": deepcopy(
                terminal["provider_dispatch_context_projection"]
            ),
        }

    monkeypatch.setattr(service, "lookup_hybrid_operation", lookup_safe_stopped)
    runtime._active = None
    runtime._pending_cleanup = None
    runtime._attempt_states.clear()
    recovered = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )

    receipt = recovered.cleanup_attempt(attempt=attempt, reason="intent_only_restart")

    assert receipt["cleanup_status"] == "stable_zero"
    assert service.lookup_calls == 1
    assert service.cancel_calls == 1
    assert windows.active == 0


def test_same_runtime_response_loss_uses_one_read_only_lookup_without_recancel(
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
        {"attempt_id": "attempt-same-runtime-response-loss", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-same-runtime-response-loss").resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4950,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)
    original_cancel = service.cancel_operation
    terminal: dict[str, object] | None = None

    def lose_terminal_response(**kwargs: object) -> dict[str, object]:
        nonlocal terminal
        terminal = original_cancel(**kwargs)
        raise ConnectionError("same-runtime cancel response lost")

    def lookup_terminal(**kwargs: object) -> dict[str, object]:
        service.lookup_calls += 1
        assert kwargs["screen_group"] == service.started_screen_group
        assert kwargs["window_binding"] == service.started_window_binding
        assert terminal is not None
        return {
            "operation_ref": deepcopy(terminal["operation_ref"]),
            "status": "cancelled",
            "terminal_receipt": None,
            "cleanup_refs": deepcopy(terminal["cleanup_refs"]),
            "provider_dispatch_context_projection": deepcopy(
                terminal["provider_dispatch_context_projection"]
            ),
        }

    monkeypatch.setattr(service, "cancel_operation", lose_terminal_response)
    monkeypatch.setattr(service, "lookup_hybrid_operation", lookup_terminal)
    with pytest.raises(ConnectionError, match="response lost"):
        runtime.trigger_probe(
            probe_context=context,
            probe_kind="cancel",
            request_in_flight_journal=request,
        )

    trigger = runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=request,
    )
    assert trigger["outcome"] == "safe_stopped_exact_incarnation_absent"
    receipt = runtime.cleanup_attempt(attempt=attempt, reason="same_runtime_loss")

    assert receipt["cleanup_status"] == "stable_zero"
    assert service.lookup_calls == 1
    assert service.cancel_calls == 1
    assert windows.active == 0


def test_terminal_receipt_replay_requires_fresh_exact_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """终态收据只能证明历史；每次消费都必须重新确认同一进程实例已离场。"""
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
        {"attempt_id": "attempt-terminal-fresh-absence", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-terminal-fresh-absence").resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4862,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)
    runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=request,
    )
    assert runtime.cleanup_attempt(attempt=attempt, reason="initial") ["cleanup_status"] == "stable_zero"

    class _StillSameIncarnation:
        def create_time(self) -> float:
            return 5000 / 1_000_000_000

    monkeypatch.setattr(
        runtime_module.psutil,
        "Process",
        lambda pid: _StillSameIncarnation(),
    )
    with pytest.raises(ValueError, match="remains live"):
        runtime.cleanup_attempt(attempt=attempt, reason="replay")
    assert service.cancel_calls == 1


def test_probe_trigger_terminal_is_unique_per_tuple(
    tmp_path: Path,
) -> None:
    """同一 attempt/provider/probe tuple 只允许一个持久化 terminal。"""
    from app.learn.hybrid.benchmark_v2_lifecycle import append_benchmark_v2_attempt_event

    attempt = _sealed({"attempt_id": "attempt-trigger-terminal-unique"})
    journal = (tmp_path / "attempt.jsonl").resolve()
    append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="prepared",
        event_kind="attempt_prepared",
        resource_ref=_sealed({"attempt_dir": str(tmp_path.resolve())}),
    )
    for event_kind in (
        "provider_request_in_flight",
        "probe_trigger_observation",
        "probe_trigger_intent",
        "probe_triggered",
    ):
        append_benchmark_v2_attempt_event(
            journal_path=journal,
            attempt_ref=attempt,
            phase="request_in_flight",
            event_kind=event_kind,
            provider_id="omni",
            probe_kind="cancel",
            resource_ref=_sealed({"event": event_kind}),
        )
    first = append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="body_complete",
        event_kind="probe_trigger_terminal",
        provider_id="omni",
        probe_kind="cancel",
        resource_ref=_sealed({"terminal": "first"}),
    )
    assert append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="body_complete",
        event_kind="probe_trigger_terminal",
        provider_id="omni",
        probe_kind="cancel",
        resource_ref=_sealed({"terminal": "first"}),
    ) == first
    with pytest.raises(ValueError, match="trigger terminal"):
        append_benchmark_v2_attempt_event(
            journal_path=journal,
            attempt_ref=attempt,
            phase="body_complete",
            event_kind="probe_trigger_terminal",
            provider_id="omni",
            probe_kind="cancel",
            resource_ref=_sealed({"terminal": "different"}),
        )


def test_probe_terminal_selector_validates_exact_tuple_and_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Selector rebuilds one sealed tuple and rejects a same-tuple conflict."""
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed({"attempt_id": "attempt-terminal-tuple-scope", "partition": "regression"})
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-terminal-tuple-scope").resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4961,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)
    receipt = runtime.trigger_probe(
        probe_context=context, probe_kind="cancel", request_in_flight_journal=request
    )
    events = read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
    )
    assert runtime_module._probe_trigger_from_terminal_events(
        events, provider_id="omni", probe_kind="cancel"
    ) == receipt
    assert runtime.cleanup_attempt(
        attempt=attempt, reason="tuple_scope_cleanup"
    )["cleanup_status"] == "stable_zero"

    conflict = deepcopy(next(event for event in events if event["event_kind"] == "probe_trigger_terminal"))
    conflict["resource_ref"] = _sealed({"different": "same-tuple-terminal"})
    with pytest.raises(ValueError, match="probe_trigger_terminal.*unique"):
        runtime_module._probe_trigger_from_terminal_events(
            [*events, conflict], provider_id="omni", probe_kind="cancel"
        )


def test_probe_recovery_selects_only_unfinished_tuple() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    events = [
        {"event_kind": "probe_trigger_intent", "provider_id": "omni", "probe_kind": "cancel"},
        {"event_kind": "probe_trigger_terminal", "provider_id": "omni", "probe_kind": "cancel"},
        {"event_kind": "probe_trigger_intent", "provider_id": "qwen", "probe_kind": "timeout"},
    ]

    assert runtime_module._single_probe_intent_tuple(events) == ("qwen", "timeout")
    assert runtime_module._single_probe_intent_tuple(events[:2]) is None


def test_probe_recovery_rejects_multiple_unfinished_tuples() -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    with pytest.raises(ValueError, match="unfinished.*ambiguous"):
        runtime_module._single_probe_intent_tuple([
            {"event_kind": "probe_trigger_intent", "provider_id": "omni", "probe_kind": "cancel"},
            {"event_kind": "probe_trigger_intent", "provider_id": "qwen", "probe_kind": "timeout"},
        ])


def test_probe_context_rejects_runtime_parent_provider_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal

    module, runtime, _, _, attempt, context, request = _prepare_probe_for_absence_control(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id="attempt-runtime-parent-provider-tamper",
        pid=4962,
    )
    intent = module._compose_probe_trigger_intent(
        project_root=tmp_path, context=context, request=request
    )
    parent = deepcopy(intent["dispatch_runtime_parent_ref"])
    parent["provider"] = "qwen"
    parent["content_sha256"] = content_sha256(parent)
    intent["dispatch_runtime_parent_ref"] = parent
    intent["content_sha256"] = content_sha256(intent)
    events = read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
    )

    with pytest.raises(ValueError, match="runtime parent|provider"):
        module._probe_context_from_events(
            events, trigger_intent=intent, request=request
        )
    runtime.cleanup_attempt(attempt=attempt, reason="runtime_parent_tamper_cleanup")


def test_probe_context_rejects_service_started_binding_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal

    module, runtime, _, _, attempt, context, request = _prepare_probe_for_absence_control(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id="attempt-service-start-binding-tamper",
        pid=4963,
    )
    intent = module._compose_probe_trigger_intent(
        project_root=tmp_path, context=context, request=request
    )
    events = read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
    )
    service_event = next(event for event in events if event["event_kind"] == "service_started")
    value = deepcopy(service_event["resource_ref"]["value"])
    binding = deepcopy(value["window_binding"])
    binding["operation_id"] = f"{binding['operation_id']}-tampered"
    binding["content_sha256"] = content_sha256(binding)
    value["window_binding"] = binding
    tampered_resource = module._runtime_resource_ref(
        "workflow_service_operation", value
    )
    tampered_event = deepcopy(service_event)
    tampered_event["resource_ref"] = tampered_resource
    tampered_event["content_sha256"] = content_sha256(tampered_event)
    tampered_events = [
        tampered_event if event is service_event else event for event in events
    ]

    with pytest.raises(ValueError, match="service start.*lineage|window"):
        module._probe_context_from_events(
            tampered_events, trigger_intent=intent, request=request
        )
    runtime.cleanup_attempt(attempt=attempt, reason="service_start_tamper_cleanup")


def test_probe_terminal_rejects_absence_identity_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal

    module, runtime, _, _, attempt, context, request = _prepare_probe_for_absence_control(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id="attempt-terminal-absence-tamper",
        pid=4964,
    )
    runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=request,
    )
    events = read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
    )
    terminal_event = next(
        event for event in events if event["event_kind"] == "probe_trigger_terminal"
    )
    terminal = deepcopy(
        terminal_event["resource_ref"]["value"]["probe_trigger_terminal"]
    )
    terminal["absence_observations"][0]["pid"] += 1
    terminal["content_sha256"] = content_sha256(terminal)
    tampered_event = deepcopy(terminal_event)
    tampered_event["resource_ref"] = module._runtime_resource_ref(
        "probe_trigger_terminal", {"probe_trigger_terminal": terminal}
    )
    tampered_event["content_sha256"] = content_sha256(tampered_event)
    tampered_events = [
        tampered_event if event is terminal_event else event for event in events
    ]

    with pytest.raises(ValueError, match="absence.*identity|process identities"):
        module._probe_trigger_from_terminal_events(
            tampered_events, provider_id="omni", probe_kind="cancel"
        )
    runtime.cleanup_attempt(attempt=attempt, reason="absence_tamper_cleanup")



def test_intent_only_pending_restart_cancels_exact_operation_once_then_persists_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅有 intent 且 worker 尚在时，恢复只取消该 exact operation 一次并补全 terminal。"""
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {"attempt_id": "attempt-intent-only-pending", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-intent-only-pending").resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4863,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)
    original_cancel = service.cancel_operation

    def fail_before_cancel(**kwargs: object) -> dict[str, object]:
        del kwargs
        raise ConnectionError("cancel response unavailable before dispatch")

    monkeypatch.setattr(service, "cancel_operation", fail_before_cancel)
    with pytest.raises(ConnectionError, match="before dispatch"):
        runtime.trigger_probe(
            probe_context=context,
            probe_kind="cancel",
            request_in_flight_journal=request,
        )
    assert service.cancel_calls == 0
    monkeypatch.setattr(service, "cancel_operation", original_cancel)
    runtime._active = None
    runtime._pending_cleanup = None
    runtime._attempt_states.clear()
    recovered = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )
    observations = 0

    class _LiveThenAbsent:
        def create_time(self) -> float:
            return 5000 / 1_000_000_000

    def process_for_pending_recovery(pid: int):
        nonlocal observations
        observations += 1
        if observations == 1:
            return _LiveThenAbsent()
        raise runtime_module.psutil.NoSuchProcess(pid)

    monkeypatch.setattr(runtime_module.psutil, "Process", process_for_pending_recovery)
    assert recovered.cleanup_attempt(
        attempt=attempt, reason="intent_only_pending"
    )["cleanup_status"] == "stable_zero"
    events = read_benchmark_v2_attempt_journal(
        journal_path=runtime_module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
    )
    assert [event["event_kind"] for event in events].count("probe_trigger_terminal") == 1
    assert service.cancel_calls == 1
    assert windows.active == 0


def test_trigger_terminal_replay_returns_same_receipt_without_recancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """terminal 已 fsync 但响应丢失时，重试只 fresh re-attest 并返回同一 receipt。"""
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
        {"attempt_id": "attempt-trigger-terminal-replay", "partition": "regression"}
    )
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / "attempt-trigger-terminal-replay").resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4864,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)
    first = runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=request,
    )
    runtime._probe_state(context).pop("trigger_receipt", None)

    replay = runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=request,
    )

    assert replay == first
    assert service.cancel_calls == 1
    runtime._active = None
    runtime._pending_cleanup = None
    runtime._attempt_states.clear()
    restarted = runtime_module._BenchmarkV2ProductionRuntime(
        project_root=tmp_path,
        authority_root=tmp_path / "runtime_state" / "binding-authority",
    )
    assert restarted.cleanup_attempt(
        attempt=attempt, reason="terminal_replay_test_cleanup"
    )["cleanup_status"] == "stable_zero"
    assert service.cancel_calls == 1


def test_probe_access_denied_fails_closed_without_terminal_or_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal

    module, runtime, service, _, attempt, context, request = _prepare_probe_for_absence_control(
        tmp_path=tmp_path, monkeypatch=monkeypatch, attempt_id="attempt-access-denied", pid=4865
    )
    original_process = module.psutil.Process
    monkeypatch.setattr(
        module.psutil, "Process", lambda pid: (_ for _ in ()).throw(module.psutil.AccessDenied(pid))
    )
    with pytest.raises(ValueError, match="live absence is indeterminate"):
        runtime.trigger_probe(
            probe_context=context, probe_kind="cancel", request_in_flight_journal=request
        )
    events = read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(project_root=tmp_path, attempt_ref=attempt),
        attempt_ref=attempt,
    )
    assert "probe_trigger_terminal" not in [event["event_kind"] for event in events]
    assert "attempt_terminal" not in [event["event_kind"] for event in events]
    with pytest.raises(ValueError, match="remains pending"):
        runtime.trigger_probe(
            probe_context=context, probe_kind="cancel", request_in_flight_journal=request
        )
    assert service.cancel_calls == 1
    monkeypatch.setattr(module.psutil, "Process", original_process)
    assert runtime.cleanup_attempt(attempt=attempt, reason="access_denied_test_cleanup")["cleanup_status"] == "stable_zero"


def test_probe_psutil_api_failure_fails_closed_without_terminal_or_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal

    module, runtime, service, _, attempt, context, request = _prepare_probe_for_absence_control(
        tmp_path=tmp_path, monkeypatch=monkeypatch, attempt_id="attempt-psutil-api-failure", pid=4866
    )
    original_process = module.psutil.Process
    monkeypatch.setattr(
        module.psutil, "Process", lambda pid: (_ for _ in ()).throw(OSError("psutil api unavailable"))
    )
    with pytest.raises(ValueError, match="live absence is indeterminate"):
        runtime.trigger_probe(
            probe_context=context, probe_kind="cancel", request_in_flight_journal=request
        )
    events = read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(project_root=tmp_path, attempt_ref=attempt),
        attempt_ref=attempt,
    )
    assert "probe_trigger_terminal" not in [event["event_kind"] for event in events]
    assert "attempt_terminal" not in [event["event_kind"] for event in events]
    with pytest.raises(ValueError, match="remains pending"):
        runtime.trigger_probe(
            probe_context=context, probe_kind="cancel", request_in_flight_journal=request
        )
    assert service.cancel_calls == 1
    monkeypatch.setattr(module.psutil, "Process", original_process)
    assert runtime.cleanup_attempt(attempt=attempt, reason="api_failure_test_cleanup")["cleanup_status"] == "stable_zero"


def test_probe_malformed_identity_fails_closed_without_terminal_or_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal

    module, runtime, service, _, attempt, context, request = _prepare_probe_for_absence_control(
        tmp_path=tmp_path, monkeypatch=monkeypatch, attempt_id="attempt-malformed-identity", pid=4867
    )
    original_absence = module._live_absence_observations
    monkeypatch.setattr(
        module,
        "_live_absence_observations",
        lambda identities: original_absence([{"pid": 4867}]),
    )
    with pytest.raises(ValueError, match="process identity is invalid"):
        runtime.trigger_probe(
            probe_context=context, probe_kind="cancel", request_in_flight_journal=request
        )
    events = read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(project_root=tmp_path, attempt_ref=attempt),
        attempt_ref=attempt,
    )
    assert "probe_trigger_terminal" not in [event["event_kind"] for event in events]
    assert "attempt_terminal" not in [event["event_kind"] for event in events]
    with pytest.raises(ValueError, match="remains pending"):
        runtime.trigger_probe(
            probe_context=context, probe_kind="cancel", request_in_flight_journal=request
        )
    assert service.cancel_calls == 1
    with pytest.raises(BaseExceptionGroup, match="indeterminate"):
        runtime.cleanup_attempt(attempt=attempt, reason="malformed_identity_test_cleanup")


def test_pid_reuse_records_observed_identity_as_exact_incarnation_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module

    class _ReusedPid:
        def create_time(self) -> float:
            return 9000 / 1_000_000_000

    monkeypatch.setattr(runtime_module.psutil, "Process", lambda pid: _ReusedPid())
    observations = runtime_module._live_absence_observations(
        [{"pid": 4868, "create_time_ns": 5000}]
    )
    assert observations == [{
        "pid": 4868,
        "create_time_ns": 5000,
        "observed_create_time_ns": 9000,
        "outcome": "pid_reused",
    }]


def test_in_memory_trigger_replay_requires_fresh_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, runtime, service, _, attempt, context, request = _prepare_probe_for_absence_control(
        tmp_path=tmp_path, monkeypatch=monkeypatch, attempt_id="attempt-memory-replay", pid=4870
    )
    original_process = module.psutil.Process
    runtime.trigger_probe(
        probe_context=context, probe_kind="cancel", request_in_flight_journal=request
    )

    class _Same:
        def create_time(self) -> float:
            return 5000 / 1_000_000_000

    monkeypatch.setattr(module.psutil, "Process", lambda pid: _Same())
    with pytest.raises(ValueError, match="remains live"):
        runtime.trigger_probe(
            probe_context=context, probe_kind="cancel", request_in_flight_journal=request
        )
    assert service.cancel_calls == 1
    monkeypatch.setattr(module.psutil, "Process", original_process)
    assert runtime.cleanup_attempt(attempt=attempt, reason="memory_replay_cleanup")["cleanup_status"] == "stable_zero"


def test_active_cleanup_after_absence_failure_never_terminalizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal

    module, runtime, service, _, attempt, context, request = _prepare_probe_for_absence_control(
        tmp_path=tmp_path, monkeypatch=monkeypatch, attempt_id="attempt-active-cleanup-denied", pid=4871
    )
    monkeypatch.setattr(
        module.psutil, "Process", lambda pid: (_ for _ in ()).throw(module.psutil.AccessDenied(pid))
    )
    with pytest.raises(ValueError, match="indeterminate"):
        runtime.trigger_probe(
            probe_context=context, probe_kind="cancel", request_in_flight_journal=request
        )
    with pytest.raises(BaseExceptionGroup, match="indeterminate"):
        runtime.cleanup_attempt(attempt=attempt, reason="active_absence_failure")
    events = read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(project_root=tmp_path, attempt_ref=attempt),
        attempt_ref=attempt,
    )
    assert "attempt_terminal" not in [event["event_kind"] for event in events]
    assert service.cancel_calls == 1


class _DeterministicDeadlineClock:
    def __init__(self, values: list[int] | None = None) -> None:
        self.now = 100
        self.values = list(values or [])
        self.reads = 0
        self.waits = 0
        self.before_wait = None

    def monotonic_ns(self) -> int:
        self.reads += 1
        if self.values:
            return self.values.pop(0)
        return self.now

    def wait(self) -> None:
        if self.before_wait is not None:
            self.before_wait()
        self.waits += 1
        self.now += 40_000_000_000


def _prepare_deadline_probe(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempt_id: str,
    probe_kind: str,
    clock: _DeterministicDeadlineClock,
):
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    _, runtime, manifest, _, windows, _ = _runtime(
        monkeypatch,
        tmp_path,
        runtime_options={
            "monotonic_ns": clock.monotonic_ns,
            "wait_hook": clock.wait,
        },
    )
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed({"attempt_id": attempt_id, "partition": "regression"})
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind=probe_kind,
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / attempt_id).resolve(),
    )
    _write_dispatch_journal(
        runtime_module=runtime_module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4980,
        service=service,
    )
    request = runtime.read_server_journal(probe_context=context)
    return runtime_module, runtime, service, windows, attempt, context, request


def test_timeout_monotonic_deadline_waits_before_cancel_and_persists_expiration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal

    clock = _DeterministicDeadlineClock()
    module, runtime, service, _, attempt, context, request = _prepare_deadline_probe(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id="attempt-timeout-monotonic-deadline",
        probe_kind="timeout",
        clock=clock,
    )
    clock.before_wait = lambda: service.cancel_calls == 0 or pytest.fail(
        "timeout cancelled before monotonic expiry"
    )
    original_cancel = service.cancel_operation

    def cancel_after_durable_observation(**kwargs: object) -> dict[str, object]:
        events = read_benchmark_v2_attempt_journal(
            journal_path=module._benchmark_v2_attempt_journal_path(
                project_root=tmp_path, attempt_ref=attempt
            ),
            attempt_ref=attempt,
        )
        assert [event["event_kind"] for event in events].count(
            "probe_trigger_observation"
        ) == 1
        return original_cancel(**kwargs)

    monkeypatch.setattr(
        service, "cancel_operation", cancel_after_durable_observation
    )

    runtime.trigger_probe(
        probe_context=context,
        probe_kind="timeout",
        request_in_flight_journal=request,
    )

    assert clock.waits == 3
    assert service.cancel_calls == 1
    events = read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
    )
    matches = [
        event for event in events if event["event_kind"] == "probe_trigger_observation"
    ]
    assert len(matches) == 1
    value = matches[0]["resource_ref"]["value"]
    observation = value["trigger_observation"]
    expiration = value["deadline_expiration"]
    assert observation == {
        "kind": "timeout",
        "action": "monotonic_deadline_expired",
        "request_in_flight_ref": request,
        "triggered_monotonic_ns": 120_000_000_100,
        "deadline_expiration_ref": {
            "content_sha256": expiration["content_sha256"]
        },
    }
    assert expiration["contract_version"] == (
        "benchmark_v2_probe_monotonic_deadline_expiration_v1"
    )
    assert expiration["clock"] == "time.monotonic_ns"
    assert expiration["owner"] == "BenchmarkV2Runtime"
    assert expiration["duration_ns"] == 120_000_000_000
    assert (
        expiration["started_monotonic_ns"]
        < expiration["deadline_monotonic_ns"]
        <= expiration["expired_monotonic_ns"]
        <= observation["triggered_monotonic_ns"]
    )
    assert runtime.cleanup_attempt(
        attempt=attempt, reason="timeout_deadline_test_cleanup"
    )["cleanup_status"] == "stable_zero"


def test_cancel_has_no_deadline_expiration_ref_and_does_not_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal

    clock = _DeterministicDeadlineClock()
    module, runtime, service, _, attempt, context, request = _prepare_deadline_probe(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id="attempt-cancel-no-deadline-expiration",
        probe_kind="cancel",
        clock=clock,
    )
    clock.before_wait = lambda: pytest.fail("explicit cancel invoked deadline wait")

    runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=request,
    )

    assert clock.waits == 0
    assert service.cancel_calls == 1
    events = read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
    )
    value = next(
        event["resource_ref"]["value"]
        for event in events
        if event["event_kind"] == "probe_trigger_observation"
    )
    assert value["trigger_observation"]["action"] == "explicit_cancel"
    assert value["trigger_observation"]["deadline_expiration_ref"] is None
    assert value["deadline_expiration"] is None
    assert runtime.cleanup_attempt(
        attempt=attempt, reason="cancel_observation_test_cleanup"
    )["cleanup_status"] == "stable_zero"


@pytest.mark.parametrize(
    "values, message",
    [
        ([True], "monotonic clock"),
        ([100, 99], "regressed"),
    ],
)
def test_timeout_monotonic_deadline_rejects_invalid_or_backward_clock_before_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    values: list[int],
    message: str,
) -> None:
    clock = _DeterministicDeadlineClock(values)
    _, runtime, service, _, _, context, request = _prepare_deadline_probe(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id=f"attempt-timeout-clock-{message}",
        probe_kind="timeout",
        clock=clock,
    )

    with pytest.raises(ValueError, match=message):
        runtime.trigger_probe(
            probe_context=context,
            probe_kind="timeout",
            request_in_flight_journal=request,
        )
    assert service.cancel_calls == 0
    assert runtime.cleanup_attempt(
        attempt=context["attempt_ref"], reason="invalid_clock_test_cleanup"
    )["cleanup_status"] == "stable_zero"


@pytest.mark.parametrize("mutation", ["owner", "clock", "duration", "cross_attempt"])
def test_timeout_monotonic_deadline_parent_conflicts_fail_closed_before_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import append_benchmark_v2_attempt_event

    clock = _DeterministicDeadlineClock()
    module, runtime, service, _, attempt, context, request = _prepare_deadline_probe(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id=f"attempt-timeout-parent-{mutation}",
        probe_kind="timeout",
        clock=clock,
    )
    expiration = _sealed(
        {
            "contract_version": "benchmark_v2_probe_monotonic_deadline_expiration_v1",
            "attempt_ref": attempt,
            "operation_ref": context["operation_ref"],
            "request_in_flight_ref": request,
            "clock": "time.monotonic_ns",
            "owner": "BenchmarkV2Runtime",
            "started_monotonic_ns": 100,
            "duration_ns": 120_000_000_000,
            "deadline_monotonic_ns": 120_000_000_100,
            "expired_monotonic_ns": 120_000_000_100,
        }
    )
    if mutation == "owner":
        expiration["owner"] = "runner"
    elif mutation == "clock":
        expiration["clock"] = "time.time_ns"
    elif mutation == "duration":
        expiration["duration_ns"] = 1
    else:
        expiration["attempt_ref"] = _sealed(
            {"attempt_id": "another-attempt", "partition": "regression"}
        )
    expiration["content_sha256"] = content_sha256(expiration)
    observation = {
        "kind": "timeout",
        "action": "monotonic_deadline_expired",
        "request_in_flight_ref": request,
        "triggered_monotonic_ns": 120_000_000_100,
        "deadline_expiration_ref": {
            "content_sha256": expiration["content_sha256"]
        },
    }
    append_benchmark_v2_attempt_event(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
        phase="request_in_flight",
        event_kind="probe_trigger_observation",
        provider_id="omni",
        probe_kind="timeout",
        resource_ref=module._runtime_resource_ref(
            "probe_trigger_observation",
            {
                "trigger_observation": observation,
                "deadline_expiration": expiration,
            },
        ),
    )
    intent = module._compose_probe_trigger_intent(
        project_root=tmp_path, context=context, request=request
    )
    append_benchmark_v2_attempt_event(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
        phase="request_in_flight",
        event_kind="probe_trigger_intent",
        provider_id="omni",
        probe_kind="timeout",
        resource_ref=module._runtime_resource_ref(
            "probe_trigger_intent", {"trigger_intent": intent}
        ),
    )

    with pytest.raises(ValueError, match="deadline|owner|clock|duration|attempt"):
        runtime.trigger_probe(
            probe_context=context,
            probe_kind="timeout",
            request_in_flight_journal=request,
        )
    assert service.cancel_calls == 0
    state = runtime._probe_state(context)
    service.cancel_operation(operation_ref=state["latest_operation_ref"])
    runtime._close_probe_window(
        state=state, reason="deadline_conflict_test_fixture_cleanup"
    )
    runtime._attempt_states.clear()


def test_probe_trigger_intent_without_trigger_observation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import append_benchmark_v2_attempt_event

    clock = _DeterministicDeadlineClock()
    module, runtime, service, _, attempt, context, request = _prepare_deadline_probe(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id="attempt-intent-missing-observation",
        probe_kind="cancel",
        clock=clock,
    )
    intent = module._compose_probe_trigger_intent(
        project_root=tmp_path, context=context, request=request
    )
    with pytest.raises(ValueError, match="causal.*observation.*intent"):
        append_benchmark_v2_attempt_event(
            journal_path=module._benchmark_v2_attempt_journal_path(
                project_root=tmp_path, attempt_ref=attempt
            ),
            attempt_ref=attempt,
            phase="request_in_flight",
            event_kind="probe_trigger_intent",
            provider_id="omni",
            probe_kind="cancel",
            resource_ref=module._runtime_resource_ref(
                "probe_trigger_intent", {"trigger_intent": intent}
            ),
        )
    assert service.cancel_calls == 0
    assert runtime.cleanup_attempt(
        attempt=attempt, reason="missing_observation_test_cleanup"
    )["cleanup_status"] == "stable_zero"


def test_timeout_monotonic_deadline_lost_response_retry_reuses_observation_without_recancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import read_benchmark_v2_attempt_journal

    clock = _DeterministicDeadlineClock()
    module, runtime, service, _, attempt, context, request = _prepare_deadline_probe(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id="attempt-timeout-observation-response-loss",
        probe_kind="timeout",
        clock=clock,
    )
    original_cancel = service.cancel_operation
    terminal = None

    def lose_cancel_response(**kwargs: object) -> dict[str, object]:
        nonlocal terminal
        terminal = original_cancel(**kwargs)
        raise ConnectionError("timeout cancel response lost")

    def lookup_terminal(**_kwargs: object) -> dict[str, object]:
        assert terminal is not None
        return {
            "operation_ref": deepcopy(terminal["operation_ref"]),
            "status": "cancelled",
            "terminal_receipt": None,
            "cleanup_refs": deepcopy(terminal["cleanup_refs"]),
            "provider_dispatch_context_projection": deepcopy(
                terminal["provider_dispatch_context_projection"]
            ),
        }

    monkeypatch.setattr(service, "cancel_operation", lose_cancel_response)
    monkeypatch.setattr(service, "lookup_hybrid_operation", lookup_terminal)
    with pytest.raises(ConnectionError, match="response lost"):
        runtime.trigger_probe(
            probe_context=context,
            probe_kind="timeout",
            request_in_flight_journal=request,
        )
    reads_after_loss = clock.reads
    waits_after_loss = clock.waits

    trigger = runtime.trigger_probe(
        probe_context=context,
        probe_kind="timeout",
        request_in_flight_journal=request,
    )

    assert trigger["outcome"] == "safe_stopped_exact_incarnation_absent"
    assert service.cancel_calls == 1
    assert clock.reads == reads_after_loss
    assert clock.waits == waits_after_loss
    events = read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path, attempt_ref=attempt
        ),
        attempt_ref=attempt,
    )
    assert [event["event_kind"] for event in events].count(
        "probe_trigger_observation"
    ) == 1
    assert runtime.cleanup_attempt(
        attempt=attempt, reason="response_loss_test_cleanup"
    )["cleanup_status"] == "stable_zero"


def test_probe_trigger_causal_replay_rejects_observation_after_intent(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle

    attempt = _sealed({"attempt_id": "attempt-retroactive-observation"})
    journal = (tmp_path / "retroactive-observation.jsonl").resolve()
    for event_kind in (
        "attempt_prepared",
        "provider_request_in_flight",
        "probe_trigger_observation",
        "probe_trigger_intent",
    ):
        lifecycle.append_benchmark_v2_attempt_event(
            journal_path=journal,
            attempt_ref=attempt,
            phase=(
                "prepared"
                if event_kind == "attempt_prepared"
                else "request_in_flight"
            ),
            event_kind=event_kind,
            provider_id=None if event_kind == "attempt_prepared" else "omni",
            probe_kind=None if event_kind == "attempt_prepared" else "cancel",
            resource_ref=_sealed({"event": event_kind}),
        )
    events = lifecycle.read_benchmark_v2_attempt_journal(
        journal_path=journal, attempt_ref=attempt
    )
    prepared, request, observation, intent = events
    retroactive_observation = deepcopy(observation)
    reordered = [prepared, request, observation, intent, retroactive_observation]
    predecessor = None
    for sequence, event in enumerate(reordered, 1):
        event["sequence"] = sequence
        event["predecessor_content_sha256"] = predecessor
        event["content_sha256"] = content_sha256(event)
        predecessor = event["content_sha256"]
    journal.write_bytes(
        b"".join(
            lifecycle.canonical_json_bytes(event) + b"\n" for event in reordered
        )
    )

    with pytest.raises(ValueError, match="causal|observation.*intent"):
        lifecycle.read_benchmark_v2_attempt_journal(
            journal_path=journal, attempt_ref=attempt
        )


def test_probe_trigger_causal_order_requires_triggered_before_terminal(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle

    attempt = _sealed({"attempt_id": "attempt-terminal-before-triggered"})
    journal = (tmp_path / "terminal-before-triggered.jsonl").resolve()
    lifecycle.append_benchmark_v2_attempt_event(
        journal_path=journal,
        attempt_ref=attempt,
        phase="prepared",
        event_kind="attempt_prepared",
        resource_ref=_sealed({"event": "prepared"}),
    )
    for event_kind in (
        "provider_request_in_flight",
        "probe_trigger_observation",
        "probe_trigger_intent",
    ):
        lifecycle.append_benchmark_v2_attempt_event(
            journal_path=journal,
            attempt_ref=attempt,
            phase="request_in_flight",
            event_kind=event_kind,
            provider_id="omni",
            probe_kind="cancel",
            resource_ref=_sealed({"event": event_kind}),
        )

    with pytest.raises(ValueError, match="causal|triggered.*terminal"):
        lifecycle.append_benchmark_v2_attempt_event(
            journal_path=journal,
            attempt_ref=attempt,
            phase="body_complete",
            event_kind="probe_trigger_terminal",
            provider_id="omni",
            probe_kind="cancel",
            resource_ref=_sealed({"event": "terminal"}),
        )


def test_timeout_monotonic_deadline_nonadvancing_clock_fails_closed_before_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wait_calls = 0

    def no_progress_wait() -> None:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls > 4100:
            raise AssertionError("deadline wait was not bounded")

    clock = _DeterministicDeadlineClock()
    module, runtime, service, _, attempt, context, request = _prepare_deadline_probe(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id="attempt-timeout-nonadvancing-clock",
        probe_kind="timeout",
        clock=clock,
    )
    runtime._wait_hook = no_progress_wait

    with pytest.raises(ValueError, match="monotonic clock failed to advance"):
        runtime.trigger_probe(
            probe_context=context,
            probe_kind="timeout",
            request_in_flight_journal=request,
        )

    assert wait_calls <= 4096
    assert service.cancel_calls == 0
    assert runtime.cleanup_attempt(
        attempt=attempt, reason="nonadvancing_clock_test_cleanup"
    )["cleanup_status"] == "stable_zero"


def _materialize_lifecycle_probe_receipt_v2(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempt_id: str,
    probe_kind: str,
):
    clock = _DeterministicDeadlineClock()
    module, runtime, _, _, attempt, context, request = _prepare_deadline_probe(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id=attempt_id,
        probe_kind=probe_kind,
        clock=clock,
    )
    runtime.trigger_probe(
        probe_context=context,
        probe_kind=probe_kind,
        request_in_flight_journal=request,
    )
    cleanup = runtime.cleanup_attempt(
        attempt=attempt,
        reason=f"{probe_kind}_receipt_v2_cleanup",
    )
    manifest_path = tmp_path / "provider" / "provider-manifest.v2.json"
    manifest = runtime.load_provider_manifest(path=manifest_path)
    receipt = runtime.finalize_probe_lifecycle_receipt(
        provider_manifest=manifest,
        attempt_ref=attempt,
        cleanup_receipt=cleanup,
    )
    return module, runtime, manifest, attempt, cleanup, context, request, receipt


@pytest.mark.parametrize("probe_kind", ["cancel", "timeout"])
def test_lifecycle_probe_receipt_v2_materializes_exact_non_authorizing_runtime_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probe_kind: str,
) -> None:
    from app.learn.hybrid.benchmark_v2_contracts import BENCHMARK_RELEASE_ID

    module, runtime, manifest, attempt, cleanup, context, request, receipt = (
        _materialize_lifecycle_probe_receipt_v2(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            attempt_id=f"attempt-lifecycle-receipt-v2-{probe_kind}",
            probe_kind=probe_kind,
        )
    )
    attempt_dir = (tmp_path / f"attempt-lifecycle-receipt-v2-{probe_kind}").resolve()
    stable_path = attempt_dir / "probe-stable-zero-evidence.json"
    receipt_path = attempt_dir / "lifecycle-probe-receipt.json"
    stable = json.loads(stable_path.read_text(encoding="utf-8"))
    events = module.read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    trigger_parent = next(
        event["resource_ref"]["value"]
        for event in events
        if event["event_kind"] == "probe_trigger_observation"
    )

    assert set(receipt) == {
        "contract_version",
        "benchmark_release_id",
        "partition",
        "probe_id",
        "attempt_ref",
        "provider",
        "probe_kind",
        "operation_ref",
        "request_in_flight_ref",
        "trigger_observation",
        "body_completion_observation",
        "termination_observation",
        "stable_zero_observation",
        "cleanup_receipt_ref",
        "observer_identity",
        "status",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    assert receipt["contract_version"] == "benchmark_v2_lifecycle_probe_receipt_v2"
    assert receipt["benchmark_release_id"] == BENCHMARK_RELEASE_ID
    assert receipt["partition"] == "regression"
    assert receipt["probe_id"] == (
        f"probe/omni/{probe_kind}/{attempt['content_sha256']}"
    )
    assert receipt["attempt_ref"] == attempt
    assert receipt["probe_kind"] == probe_kind
    assert receipt["operation_ref"] == context["operation_ref"]
    assert receipt["request_in_flight_ref"] == request
    assert receipt["trigger_observation"] == trigger_parent["trigger_observation"]
    assert receipt["body_completion_observation"]["state"] == "not_complete"
    assert (
        receipt["body_completion_observation"]["observed_monotonic_ns"]
        > receipt["trigger_observation"]["triggered_monotonic_ns"]
    )
    assert receipt["termination_observation"]["outcome"] == (
        "same_incarnations_exited"
    )
    assert receipt["termination_observation"]["process_identities"] == [
        {"pid": 4980, "create_time_ns": 5000}
    ]
    assert receipt["stable_zero_observation"] == {
        "job_members": [],
        "active_listeners": [],
        "active_leases": [],
        "stable_zero_observations": 3,
        "evidence_ref": {"content_sha256": stable["content_sha256"]},
    }
    assert receipt["cleanup_receipt_ref"] == {
        "content_sha256": cleanup["content_sha256"]
    }
    assert receipt["provider"]["provider_id"] == "omni"
    assert receipt["provider"]["provider_revision"] == manifest[
        "evaluation_projection"
    ]["provider_policy"]["provider_revisions"]["omni"]
    assert receipt["provider"]["profile_id"] == "omni-test-profile"
    assert receipt["observer_identity"]["kind"] == "production_runtime"
    assert Path(receipt["observer_identity"]["module_ref"]["canonical_path"]) == Path(
        module.__file__
    ).resolve()
    assert receipt["status"] == "PASS"
    assert receipt["artifact_is_authorization"] is False
    assert receipt["execute_binding_enabled"] is False
    if probe_kind == "cancel":
        assert receipt["trigger_observation"]["deadline_expiration_ref"] is None
        assert trigger_parent["deadline_expiration"] is None
    else:
        assert receipt["trigger_observation"]["deadline_expiration_ref"] == {
            "content_sha256": trigger_parent["deadline_expiration"]["content_sha256"]
        }
    assert receipt_path.read_bytes() == module.canonical_json_bytes(receipt, pretty=True)
    assert stable_path.read_bytes() == module.canonical_json_bytes(stable, pretty=True)
    observed = [sample["observed_monotonic_ns"] for sample in stable["samples"]]
    assert len(observed) == len(set(observed)) == 3
    assert observed == sorted(observed)
    assert all(
        sample["resource_counts"]
        == {
            "service_operations": 0,
            "windows": 0,
            "providers": 0,
            "listeners": 0,
            "leases": 0,
        }
        for sample in stable["samples"]
    )
    assert runtime.finalize_probe_lifecycle_receipt(
        provider_manifest=manifest,
        attempt_ref=attempt,
        cleanup_receipt=cleanup,
    ) == receipt


def test_lifecycle_probe_receipt_v2_public_port_accepts_no_runner_authored_facts() -> None:
    from app.learn.hybrid.benchmark_v2_runtime import BenchmarkV2ProductionRuntimePort

    assert list(
        inspect.signature(
            BenchmarkV2ProductionRuntimePort.finalize_probe_lifecycle_receipt
        ).parameters
    ) == ["self", "provider_manifest", "attempt_ref", "cleanup_receipt"]


def test_lifecycle_probe_receipt_v2_replay_rejects_different_bytes_and_live_ambiguity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, runtime, manifest, attempt, cleanup, _, _, receipt = (
        _materialize_lifecycle_probe_receipt_v2(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            attempt_id="attempt-lifecycle-receipt-v2-replay",
            probe_kind="cancel",
        )
    )
    receipt_path = (
        tmp_path
        / "attempt-lifecycle-receipt-v2-replay"
        / "lifecycle-probe-receipt.json"
    ).resolve()
    original_bytes = receipt_path.read_bytes()
    assert runtime.finalize_probe_lifecycle_receipt(
        provider_manifest=manifest,
        attempt_ref=attempt,
        cleanup_receipt=cleanup,
    ) == receipt
    assert receipt_path.read_bytes() == original_bytes

    receipt_path.write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="canonical|receipt"):
        runtime.finalize_probe_lifecycle_receipt(
            provider_manifest=manifest,
            attempt_ref=attempt,
            cleanup_receipt=cleanup,
        )
    receipt_path.write_bytes(original_bytes)
    monkeypatch.setattr(
        module.psutil,
        "Process",
        lambda pid: (_ for _ in ()).throw(module.psutil.AccessDenied(pid)),
    )
    with pytest.raises(ValueError, match="absence.*indeterminate"):
        runtime.finalize_probe_lifecycle_receipt(
            provider_manifest=manifest,
            attempt_ref=attempt,
            cleanup_receipt=cleanup,
        )


@pytest.mark.parametrize("mutation", ["attempt", "cleanup"])
def test_lifecycle_probe_receipt_v2_rejects_cross_attempt_or_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _, runtime, manifest, attempt, cleanup, _, _, _ = (
        _materialize_lifecycle_probe_receipt_v2(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            attempt_id=f"attempt-lifecycle-receipt-v2-{mutation}",
            probe_kind="timeout",
        )
    )
    if mutation == "attempt":
        attempt = _sealed({"attempt_id": "cross-attempt", "partition": "regression"})
    else:
        cleanup = deepcopy(cleanup)
        cleanup["reason"] = "cross-cleanup"
        cleanup["content_sha256"] = content_sha256(cleanup)
    with pytest.raises(ValueError):
        runtime.finalize_probe_lifecycle_receipt(
            provider_manifest=manifest,
            attempt_ref=attempt,
            cleanup_receipt=cleanup,
        )


def _lifecycle_probe_receipt_v2_validator_material(
    *,
    module: object,
    runtime: object,
    manifest: Mapping[str, object],
    attempt: Mapping[str, object],
    cleanup: Mapping[str, object],
    receipt: Mapping[str, object],
) -> dict[str, object]:
    events = module.read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=runtime._project_root,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    provider_id = receipt["provider"]["provider_id"]
    probe_kind = receipt["probe_kind"]
    material = module._probe_terminal_material(
        events,
        provider_id=provider_id,
        probe_kind=probe_kind,
    )
    dispatch = module._read_committed_probe_dispatch_evidence(
        project_root=runtime._project_root,
        provider=provider_id,
        context_projection=material["context"][
            "provider_dispatch_context_projection"
        ],
        expected_dispatch_receipt_ref=material["request"]["dispatch_receipt_ref"],
        expected_runtime_identity_ref=material["request"][
            "provider_runtime_attestation_ref"
        ],
    )
    attempt_dir = module._actual_attempt_directory_from_events(events)
    stable = json.loads(
        (attempt_dir / "probe-stable-zero-evidence.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        "stable_zero_evidence": stable,
        "cleanup_receipt": cleanup,
        "dispatch_runtime_parent": dispatch["runtime_parent"],
        "deadline_expiration": material["trigger_observation"][
            "deadline_expiration"
        ],
        "probe_trigger_terminal_event": material["terminal_event"],
        "provider_manifest": manifest,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "attempt",
        "operation",
        "request",
        "provider",
        "profile",
        "revision",
        "cleanup",
        "timeout_missing_deadline",
        "body_complete",
        "body_not_post_trigger",
    ],
)
def test_lifecycle_probe_receipt_v2_validator_rejects_join_or_semantic_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        validate_benchmark_v2_lifecycle_probe_receipt_v2,
    )

    module, runtime, manifest, attempt, cleanup, _, _, receipt = (
        _materialize_lifecycle_probe_receipt_v2(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            attempt_id=f"attempt-lifecycle-receipt-v2-validator-{mutation}",
            probe_kind="timeout",
        )
    )
    parents = _lifecycle_probe_receipt_v2_validator_material(
        module=module,
        runtime=runtime,
        manifest=manifest,
        attempt=attempt,
        cleanup=cleanup,
        receipt=receipt,
    )
    drifted = deepcopy(receipt)
    if mutation == "attempt":
        drifted["attempt_ref"] = _sealed(
            {"attempt_id": "cross-attempt", "partition": "regression"}
        )
    elif mutation == "operation":
        drifted["operation_ref"]["operation_id"] = "cross-operation"
        drifted["operation_ref"]["content_sha256"] = content_sha256(
            drifted["operation_ref"]
        )
    elif mutation == "request":
        drifted["request_in_flight_ref"]["provider_id"] = "qwen"
        drifted["request_in_flight_ref"]["content_sha256"] = content_sha256(
            drifted["request_in_flight_ref"]
        )
    elif mutation == "provider":
        drifted["provider"]["provider_id"] = "qwen"
        drifted["probe_id"] = "probe/qwen/timeout"
    elif mutation == "profile":
        drifted["provider"]["profile_id"] = "sealed-runtime-role-is-not-authority"
    elif mutation == "revision":
        drifted["provider"]["provider_revision"] = "STALE_REVISION"
    elif mutation == "cleanup":
        drifted["cleanup_receipt_ref"] = {"content_sha256": "f" * 64}
    elif mutation == "timeout_missing_deadline":
        drifted["trigger_observation"]["deadline_expiration_ref"] = None
    elif mutation == "body_complete":
        drifted["body_completion_observation"]["state"] = "complete"
    else:
        drifted["body_completion_observation"]["observed_monotonic_ns"] = drifted[
            "trigger_observation"
        ]["triggered_monotonic_ns"]
    drifted["content_sha256"] = content_sha256(drifted)
    with pytest.raises(ValueError):
        validate_benchmark_v2_lifecycle_probe_receipt_v2(drifted, **parents)


def test_lifecycle_probe_receipt_v2_cancel_rejects_extra_deadline_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        validate_benchmark_v2_lifecycle_probe_receipt_v2,
    )

    module, runtime, manifest, attempt, cleanup, _, _, receipt = (
        _materialize_lifecycle_probe_receipt_v2(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            attempt_id="attempt-lifecycle-receipt-v2-cancel-extra-deadline",
            probe_kind="cancel",
        )
    )
    parents = _lifecycle_probe_receipt_v2_validator_material(
        module=module,
        runtime=runtime,
        manifest=manifest,
        attempt=attempt,
        cleanup=cleanup,
        receipt=receipt,
    )
    drifted = deepcopy(receipt)
    drifted["trigger_observation"]["deadline_expiration_ref"] = {
        "content_sha256": "e" * 64
    }
    drifted["content_sha256"] = content_sha256(drifted)
    parents["deadline_expiration"] = _sealed({"kind": "runner-authored-expiry"})
    with pytest.raises(ValueError, match="cancel.*deadline"):
        validate_benchmark_v2_lifecycle_probe_receipt_v2(drifted, **parents)


@pytest.mark.parametrize("mutation", ["fewer", "repeated", "nonzero"])
def test_lifecycle_probe_receipt_v2_rejects_insufficient_or_nonzero_stable_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        validate_benchmark_v2_lifecycle_probe_receipt_v2,
    )

    module, runtime, manifest, attempt, cleanup, _, _, receipt = (
        _materialize_lifecycle_probe_receipt_v2(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            attempt_id=f"attempt-lifecycle-receipt-v2-stable-{mutation}",
            probe_kind="cancel",
        )
    )
    parents = _lifecycle_probe_receipt_v2_validator_material(
        module=module,
        runtime=runtime,
        manifest=manifest,
        attempt=attempt,
        cleanup=cleanup,
        receipt=receipt,
    )
    stable = deepcopy(parents["stable_zero_evidence"])
    if mutation == "fewer":
        stable["samples"] = stable["samples"][:2]
    elif mutation == "repeated":
        stable["samples"][1]["observed_monotonic_ns"] = stable["samples"][0][
            "observed_monotonic_ns"
        ]
    else:
        stable["samples"][1]["resource_counts"]["listeners"] = 1
    stable["content_sha256"] = content_sha256(stable)
    parents["stable_zero_evidence"] = stable
    with pytest.raises(ValueError, match="stable-zero"):
        validate_benchmark_v2_lifecycle_probe_receipt_v2(receipt, **parents)


def test_lifecycle_probe_receipt_v2_preserves_exact_ordered_multi_process_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        validate_benchmark_v2_lifecycle_probe_receipt_v2,
    )
    from app.learn.hybrid import benchmark_v2_runtime as runtime_module
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import _runtime

    module, runtime, manifest, _, _, _ = _runtime(monkeypatch, tmp_path)
    service = _ProbeService()
    monkeypatch.setattr(
        runtime_module,
        "get_production_benchmark_v2_workflow_service",
        lambda: service,
    )
    attempt = _sealed(
        {
            "attempt_id": "attempt-lifecycle-receipt-v2-multi-process",
            "partition": "regression",
        }
    )
    identities = [
        {"pid": 4980, "create_time_ns": 5000},
        {"pid": 4981, "create_time_ns": 5001},
    ]
    context = runtime.begin_probe(
        provider_id="omni",
        probe_kind="cancel",
        provider_manifest=manifest,
        attempt_ref=attempt,
        attempt_dir=(tmp_path / attempt["attempt_id"]).resolve(),
    )
    _write_dispatch_journal(
        runtime_module=module,
        project_root=tmp_path,
        monkeypatch=monkeypatch,
        context=context,
        provider="omni",
        pid=4980,
        service=service,
        process_identities=identities,
    )
    request = runtime.read_server_journal(probe_context=context)
    runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=request,
    )
    cleanup = runtime.cleanup_attempt(attempt=attempt, reason="multi_process_cleanup")
    receipt = runtime.finalize_probe_lifecycle_receipt(
        provider_manifest=manifest,
        attempt_ref=attempt,
        cleanup_receipt=cleanup,
    )
    assert receipt["termination_observation"]["process_identities"] == identities
    parents = _lifecycle_probe_receipt_v2_validator_material(
        module=module,
        runtime=runtime,
        manifest=manifest,
        attempt=attempt,
        cleanup=cleanup,
        receipt=receipt,
    )
    reversed_receipt = deepcopy(receipt)
    reversed_receipt["termination_observation"]["process_identities"] = list(
        reversed(identities)
    )
    reversed_receipt["content_sha256"] = content_sha256(reversed_receipt)
    with pytest.raises(ValueError, match="process identities"):
        validate_benchmark_v2_lifecycle_probe_receipt_v2(
            reversed_receipt, **parents
        )


def test_lifecycle_probe_receipt_v2_replay_rejects_forged_preexisting_zero_parent_without_three_fresh_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        compose_benchmark_v2_probe_stable_zero_evidence_v1,
    )

    clock = _DeterministicDeadlineClock()
    module, runtime, _, _, attempt, context, request = _prepare_deadline_probe(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id="attempt-lifecycle-receipt-v2-forged-zero-parent",
        probe_kind="cancel",
        clock=clock,
    )
    runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=request,
    )
    cleanup = runtime.cleanup_attempt(
        attempt=attempt,
        reason="forged_zero_parent_cleanup",
    )
    manifest = runtime.load_provider_manifest(
        path=tmp_path / "provider" / "provider-manifest.v2.json"
    )
    events = module.read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    terminal = next(
        event for event in events if event["event_kind"] == "probe_trigger_terminal"
    )
    zero = {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }
    forged = compose_benchmark_v2_probe_stable_zero_evidence_v1(
        attempt_ref=attempt,
        cleanup_receipt=cleanup,
        body_completion_observation={
            "state": "not_complete",
            "observed_monotonic_ns": 1_000,
            "evidence_ref": terminal,
        },
        samples=[
            {"observed_monotonic_ns": value, "resource_counts": zero}
            for value in (2_000, 3_000, 4_000)
        ],
    )
    attempt_dir = (tmp_path / "attempt-lifecycle-receipt-v2-forged-zero-parent").resolve()
    attempt_dir.mkdir(parents=True, exist_ok=True)
    (attempt_dir / "probe-stable-zero-evidence.json").write_bytes(
        module.canonical_json_bytes(forged, pretty=True)
    )
    calls = 0

    def fresh_counts(self: object) -> Mapping[str, int]:
        nonlocal calls
        calls += 1
        result = dict(zero)
        if calls == 3:
            result["leases"] = 1
        return result

    monkeypatch.setattr(type(runtime), "resource_counts", fresh_counts)
    clock.now = 5_000
    with pytest.raises(ValueError, match="sample|residue|stable-zero"):
        runtime.finalize_probe_lifecycle_receipt(
            provider_manifest=manifest,
            attempt_ref=attempt,
            cleanup_receipt=cleanup,
        )
    assert calls == 0


@pytest.mark.parametrize(
    "mutation",
    ["release", "deadline_extra", "cleanup_extra", "dispatch_extra", "observer_forged", "terminal_ref"],
)
def test_lifecycle_probe_receipt_v2_rejects_open_or_caller_circular_parents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        validate_benchmark_v2_lifecycle_probe_receipt_v2,
    )

    probe_kind = "timeout" if mutation == "deadline_extra" else "cancel"
    module, runtime, manifest, attempt, cleanup, _, _, receipt = (
        _materialize_lifecycle_probe_receipt_v2(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            attempt_id=f"attempt-lifecycle-receipt-v2-closed-{mutation}",
            probe_kind=probe_kind,
        )
    )
    parents = _lifecycle_probe_receipt_v2_validator_material(
        module=module,
        runtime=runtime,
        manifest=manifest,
        attempt=attempt,
        cleanup=cleanup,
        receipt=receipt,
    )
    drifted = deepcopy(receipt)
    if mutation == "release":
        drifted["benchmark_release_id"] = "FORGED_RELEASE"
    elif mutation == "deadline_extra":
        expiration = deepcopy(parents["deadline_expiration"])
        expiration["runner_authored_expired"] = True
        expiration["content_sha256"] = content_sha256(expiration)
        parents["deadline_expiration"] = expiration
        drifted["trigger_observation"]["deadline_expiration_ref"] = {
            "content_sha256": expiration["content_sha256"]
        }
    elif mutation == "cleanup_extra":
        parent = deepcopy(parents["cleanup_receipt"])
        parent["runner_note"] = "not-closed"
        parent["content_sha256"] = content_sha256(parent)
        parents["cleanup_receipt"] = parent
        stable = deepcopy(parents["stable_zero_evidence"])
        stable["cleanup_receipt_ref"] = {
            "content_sha256": parent["content_sha256"]
        }
        stable["content_sha256"] = content_sha256(stable)
        parents["stable_zero_evidence"] = stable
        drifted["cleanup_receipt_ref"] = {
            "content_sha256": parent["content_sha256"]
        }
        drifted["stable_zero_observation"]["evidence_ref"] = {
            "content_sha256": stable["content_sha256"]
        }
    elif mutation == "dispatch_extra":
        parent = deepcopy(parents["dispatch_runtime_parent"])
        parent["runner_profile_claim"] = "not-closed"
        parent["content_sha256"] = content_sha256(parent)
        parents["dispatch_runtime_parent"] = parent
    elif mutation == "observer_forged":
        observer = _sealed(
            {
                "kind": "production_runtime",
                "module_ref": {
                    "canonical_path": str((tmp_path / "forged-runtime.py").resolve()),
                    "file_sha256": "f" * 64,
                },
            }
        )
        drifted["observer_identity"] = observer
    else:
        forged_event = _sealed({"kind": "not-the-p0c-terminal"})
        drifted["body_completion_observation"]["evidence_ref"] = forged_event
        drifted["termination_observation"]["evidence_ref"] = forged_event
        stable = deepcopy(parents["stable_zero_evidence"])
        stable["body_completion_observation"]["evidence_ref"] = forged_event
        stable["content_sha256"] = content_sha256(stable)
        parents["stable_zero_evidence"] = stable
        drifted["stable_zero_observation"]["evidence_ref"] = {
            "content_sha256": stable["content_sha256"]
        }
    drifted["content_sha256"] = content_sha256(drifted)
    with pytest.raises(ValueError):
        validate_benchmark_v2_lifecycle_probe_receipt_v2(drifted, **parents)


def test_lifecycle_probe_receipt_v2_probe_id_is_unique_per_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _materialize_lifecycle_probe_receipt_v2(
        tmp_path=tmp_path / "first",
        monkeypatch=monkeypatch,
        attempt_id="attempt-lifecycle-receipt-v2-unique-first",
        probe_kind="cancel",
    )[-1]
    second = _materialize_lifecycle_probe_receipt_v2(
        tmp_path=tmp_path / "second",
        monkeypatch=monkeypatch,
        attempt_id="attempt-lifecycle-receipt-v2-unique-second",
        probe_kind="cancel",
    )[-1]
    assert first["probe_id"] != second["probe_id"]
    assert first["probe_id"].endswith(first["attempt_ref"]["content_sha256"])
    assert second["probe_id"].endswith(second["attempt_ref"]["content_sha256"])


def test_lifecycle_probe_receipt_v2_rejects_orphan_stable_parent_even_after_three_fresh_zero_samples(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        compose_benchmark_v2_probe_stable_zero_evidence_v1,
    )

    clock = _DeterministicDeadlineClock()
    module, runtime, _, _, attempt, context, request = _prepare_deadline_probe(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
        attempt_id="attempt-lifecycle-receipt-v2-orphan-zero-parent",
        probe_kind="cancel",
        clock=clock,
    )
    runtime.trigger_probe(
        probe_context=context,
        probe_kind="cancel",
        request_in_flight_journal=request,
    )
    cleanup = runtime.cleanup_attempt(attempt=attempt, reason="orphan_zero_cleanup")
    manifest = runtime.load_provider_manifest(
        path=tmp_path / "provider" / "provider-manifest.v2.json"
    )
    events = module.read_benchmark_v2_attempt_journal(
        journal_path=module._benchmark_v2_attempt_journal_path(
            project_root=tmp_path,
            attempt_ref=attempt,
        ),
        attempt_ref=attempt,
    )
    terminal = next(
        event for event in events if event["event_kind"] == "probe_trigger_terminal"
    )
    zero = {
        "service_operations": 0,
        "windows": 0,
        "providers": 0,
        "listeners": 0,
        "leases": 0,
    }
    orphan = compose_benchmark_v2_probe_stable_zero_evidence_v1(
        attempt_ref=attempt,
        cleanup_receipt=cleanup,
        body_completion_observation={
            "state": "not_complete",
            "observed_monotonic_ns": 1_000,
            "evidence_ref": terminal,
        },
        samples=[
            {"observed_monotonic_ns": value, "resource_counts": zero}
            for value in (2_000, 3_000, 4_000)
        ],
    )
    attempt_dir = (tmp_path / "attempt-lifecycle-receipt-v2-orphan-zero-parent").resolve()
    attempt_dir.mkdir(parents=True, exist_ok=True)
    stable_path = attempt_dir / "probe-stable-zero-evidence.json"
    receipt_path = attempt_dir / "lifecycle-probe-receipt.json"
    stable_path.write_bytes(module.canonical_json_bytes(orphan, pretty=True))
    clock.now = 5_000
    calls = 0

    def fresh_zero(self: object) -> Mapping[str, int]:
        nonlocal calls
        calls += 1
        return dict(zero)

    monkeypatch.setattr(type(runtime), "resource_counts", fresh_zero)
    with pytest.raises(ValueError, match="orphan|receipt|producer"):
        runtime.finalize_probe_lifecycle_receipt(
            provider_manifest=manifest,
            attempt_ref=attempt,
            cleanup_receipt=cleanup,
        )
    assert calls in {0, 3}
    assert not receipt_path.exists()


@pytest.mark.parametrize("mutation", ["request_extra", "operation_extra", "terminal_absence"])
def test_lifecycle_probe_receipt_v2_rejects_rehashed_open_request_operation_or_terminal_absence_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from app.learn.hybrid.benchmark_v2_lifecycle import (
        validate_benchmark_v2_lifecycle_probe_receipt_v2,
    )

    module, runtime, manifest, attempt, cleanup, _, _, receipt = (
        _materialize_lifecycle_probe_receipt_v2(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
            attempt_id=f"attempt-lifecycle-receipt-v2-open-{mutation}",
            probe_kind="cancel",
        )
    )
    parents = _lifecycle_probe_receipt_v2_validator_material(
        module=module,
        runtime=runtime,
        manifest=manifest,
        attempt=attempt,
        cleanup=cleanup,
        receipt=receipt,
    )
    drifted = deepcopy(receipt)
    if mutation == "request_extra":
        request = drifted["request_in_flight_ref"]
        request["runner_note"] = "open-request"
        request["content_sha256"] = content_sha256(request)
        drifted["trigger_observation"]["request_in_flight_ref"] = deepcopy(request)
    elif mutation == "operation_extra":
        operation = drifted["operation_ref"]
        operation["runner_note"] = "open-operation"
        operation["content_sha256"] = content_sha256(operation)
        drifted["request_in_flight_ref"]["operation_ref"] = deepcopy(operation)
        drifted["request_in_flight_ref"]["content_sha256"] = content_sha256(
            drifted["request_in_flight_ref"]
        )
        drifted["trigger_observation"]["request_in_flight_ref"] = deepcopy(
            drifted["request_in_flight_ref"]
        )
    else:
        event = deepcopy(parents["probe_trigger_terminal_event"])
        terminal = event["resource_ref"]["value"]["probe_trigger_terminal"]
        terminal["absence_observations"][0]["pid"] += 100
        terminal["content_sha256"] = content_sha256(terminal)
        event["resource_ref"]["content_sha256"] = content_sha256(
            event["resource_ref"]
        )
        event["content_sha256"] = content_sha256(event)
        parents["probe_trigger_terminal_event"] = event
        drifted["body_completion_observation"]["evidence_ref"] = event
        drifted["termination_observation"]["evidence_ref"] = event
        stable = deepcopy(parents["stable_zero_evidence"])
        stable["body_completion_observation"]["evidence_ref"] = event
        stable["content_sha256"] = content_sha256(stable)
        parents["stable_zero_evidence"] = stable
        drifted["stable_zero_observation"]["evidence_ref"] = {
            "content_sha256": stable["content_sha256"]
        }
    drifted["content_sha256"] = content_sha256(drifted)
    with pytest.raises(ValueError):
        validate_benchmark_v2_lifecycle_probe_receipt_v2(drifted, **parents)
