from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest


def _sealed_ref(identifier: str, digit: str) -> dict[str, str]:
    return {"id": identifier, "content_sha256": digit * 64}


def _context(
    tmp_path: Path,
    *,
    provider: str = "qwen",
    revision: int = 7,
) -> dict[str, object]:
    from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
        compose_benchmark_dispatch_context,
    )

    operation_ref = {
        "run_id": "run-1",
        "stage": "screen_understanding",
        "operation_id": "operation-1",
        "revision": revision,
        "window_binding_ref": _sealed_ref("window-1", "a"),
        "capture_ref": _sealed_ref("capture-1", "b"),
    }
    window_binding = {
        "contract_version": "test_window_binding_v1",
        "exact_hwnd": 101,
        "process_identity": {"pid": 202, "create_time_ns": 303},
        "job_name": "job-1",
        "payload_sha256": "c" * 64,
    }
    return compose_benchmark_dispatch_context(
        provider=provider,
        operation_ref=operation_ref,
        window_binding=window_binding,
        receipt_journal_path=(tmp_path / "dispatch.jsonl").resolve(),
    )


def test_provider_dispatch_context_ref_preserves_exact_server_issued_revision(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    omni = _context(tmp_path, provider="omni", revision=7)
    qwen = _context(tmp_path, provider="qwen", revision=8)

    omni_ref = module.compose_benchmark_dispatch_context_ref(context=omni)
    qwen_ref = module.compose_benchmark_dispatch_context_ref(context=qwen)

    assert module.validate_benchmark_dispatch_context_ref(omni_ref) == omni_ref
    assert module.validate_benchmark_dispatch_context_ref(qwen_ref) == qwen_ref
    assert omni_ref["dispatch_context"]["operation_ref"]["revision"] == 7
    assert qwen_ref["dispatch_context"]["operation_ref"]["revision"] == 8
    assert omni_ref["dispatch_context"]["content_sha256"] == omni["content_sha256"]
    assert qwen_ref["dispatch_context"]["content_sha256"] == qwen["content_sha256"]

    stale = deepcopy(qwen_ref)
    stale["dispatch_context"]["operation_ref"]["revision"] = 9
    stale["content_sha256"] = module.content_sha256(stale)
    with pytest.raises(ValueError, match="operation|context"):
        module.validate_benchmark_dispatch_context_ref(stale)


def test_attestation_is_fsynced_after_fresh_window_and_runtime_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    context = _context(tmp_path)
    events: list[str] = []
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: events.append("window") or {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_provider_runtime",
        lambda provider, value: events.append(f"runtime:{provider}")
        or {"content_sha256": "e" * 64},
    )
    real_fsync = module.os.fsync
    monkeypatch.setattr(
        module.os,
        "fsync",
        lambda descriptor: events.append("fsync") or real_fsync(descriptor),
    )

    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        receipt = module.attest_benchmark_provider_dispatch(
            provider="qwen",
            operation_ref=deepcopy(context["operation_ref"]),
            window_binding=deepcopy(context["window_binding"]),
            provider_runtime={"contract_version": "test_qwen_runtime_v1"},
        )
        events.append("dispatch")
        refs = module.current_benchmark_dispatch_receipt_refs()

    assert events == ["window", "runtime:qwen", "fsync", "dispatch"]
    assert refs == [
        {"provider": "qwen", "content_sha256": receipt["content_sha256"]}
    ]
    journal = Path(str(context["receipt_journal_path"]))
    assert json.loads(journal.read_text(encoding="utf-8").splitlines()[0]) == receipt
    assert module.read_latest_benchmark_dispatch_receipt(
        dispatch_context=context
    ) == receipt
    assert receipt["artifact_is_authorization"] is False
    assert receipt["execute_binding_enabled"] is False


def test_common_runtime_identity_distinguishes_exact_provider_ownership() -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    process = {"pid": 101, "create_time_ns": 202}
    scope = {
        "scope_name": "Local\\AgentGuiHybrid-qwen-" + "a" * 64,
        "member_pids": [101],
        "process_identities": [process],
    }
    common = {
        "profile_ref": {"content_sha256": "b" * 64},
        "listener_owner": {
            "host": "127.0.0.1",
            "port": 8080,
            "process_identities": [process],
        },
        "process_identities": [process],
        "process_scope": scope,
    }
    qwen_a = module.compose_benchmark_provider_runtime_identity(
        provider="qwen",
        lease_identity={
            "lease_id": "lease-a",
            "incarnation_id": "incarnation-a",
            "owner_request_id": "request-a",
        },
        **common,
    )
    qwen_b = module.compose_benchmark_provider_runtime_identity(
        provider="qwen",
        lease_identity={
            "lease_id": "lease-b",
            "incarnation_id": "incarnation-b",
            "owner_request_id": "request-a",
        },
        **common,
    )
    qwen_c = module.compose_benchmark_provider_runtime_identity(
        provider="qwen",
        lease_identity={
            "lease_id": "lease-a",
            "incarnation_id": "incarnation-a",
            "owner_request_id": "request-a",
        },
        profile_ref=common["profile_ref"],
        listener_owner={
            **common["listener_owner"],
            "process_identities": [{"pid": 303, "create_time_ns": 404}],
        },
        process_identities=[{"pid": 303, "create_time_ns": 404}],
        process_scope={
            **scope,
            "member_pids": [303],
            "process_identities": [{"pid": 303, "create_time_ns": 404}],
        },
    )
    vista_a = module.compose_benchmark_provider_runtime_identity(
        provider="vista",
        lease_identity={
            "incarnation_id": "vista-a",
            "lease_content_sha256": "c" * 64,
        },
        **{
            **common,
            "process_scope": {
                **scope,
                "scope_name": "Local\\AgentGuiHybrid-vista-" + "d" * 64,
            },
        },
    )
    vista_b = module.compose_benchmark_provider_runtime_identity(
        provider="vista",
        lease_identity={
            "incarnation_id": "vista-b",
            "lease_content_sha256": "e" * 64,
        },
        **{
            **common,
            "process_scope": {
                **scope,
                "scope_name": "Local\\AgentGuiHybrid-vista-" + "d" * 64,
            },
        },
    )
    omni_a = module.compose_benchmark_provider_runtime_identity(
        provider="omni",
        lease_identity=None,
        profile_ref=None,
        listener_owner=None,
        process_identities=[process],
        process_scope={
            **scope,
            "scope_name": "Local\\AgentGuiHybrid-omni-" + "f" * 64,
        },
    )
    omni_b = module.compose_benchmark_provider_runtime_identity(
        provider="omni",
        lease_identity=None,
        profile_ref=None,
        listener_owner=None,
        process_identities=[process],
        process_scope={
            **scope,
            "scope_name": "Local\\AgentGuiHybrid-omni-" + "9" * 64,
        },
    )

    assert qwen_a["content_sha256"] != qwen_b["content_sha256"]
    assert qwen_a["content_sha256"] != qwen_c["content_sha256"]
    assert vista_a["content_sha256"] != vista_b["content_sha256"]
    assert omni_a["content_sha256"] != omni_b["content_sha256"]
    assert qwen_a["artifact_is_authorization"] is False
    assert qwen_a["execute_binding_enabled"] is False


def test_registry_rejects_aggregate_only_hybrid_provider_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module
    from app.learn.workflow_worker import LearningStageWorkerRegistry

    context = _context(tmp_path, provider="qwen")
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_provider_runtime",
        lambda provider, value: {"content_sha256": "e" * 64},
    )
    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        receipt = module.attest_benchmark_provider_dispatch(
            provider="qwen",
            operation_ref=deepcopy(context["operation_ref"]),
            window_binding=deepcopy(context["window_binding"]),
            provider_runtime={"contract_version": "test_runtime_v1"},
        )

    root = (tmp_path / "workers").resolve()
    registry = LearningStageWorkerRegistry(result_root=root)
    record = {
        "contract_version": "learning_stage_worker_v1",
        "worker_id": "worker-hybrid-cleanup",
        "run_id": "run-1",
        "stage": "screen_understanding",
        "operation_id": "operation-1",
        "task_kind": "panel_learning_hybrid_qwen_binding",
        "model_request_id": "request-hybrid-cleanup",
        "payload_sha256": "f" * 64,
        "status": "cancelled",
        "started_at": "2026-08-28T00:00:00+00:00",
        "finished_at": "2026-08-28T00:00:01+00:00",
        "result_path": str(root / "worker-hybrid-cleanup.result.json"),
        "journal_path": str(root / "worker-hybrid-cleanup.worker.json"),
        "payload": {"_benchmark_v2_dispatch_context": deepcopy(context)},
        "process": None,
    }
    projection = registry._compose_hybrid_benchmark_provider_cleanup(
        record=record,
        worker_termination={
            "worker_id": record["worker_id"],
            "model_request_id": record["model_request_id"],
            "backend_compute_termination": "terminated",
            "model_service_compute_termination": "request_not_active",
            "model_request_cancellation": {
                "status": "request_not_active",
                "request_id": record["model_request_id"],
            },
        },
    )
    assert receipt["provider_runtime_attestation_ref"] == {
        "content_sha256": "e" * 64
    }
    assert projection is None


def test_registry_persists_exact_owner_cleanup_and_replays_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module
    from app.learn.recognition.uei import omniparser_shadow_adapter as omni
    from app.learn.workflow_worker import LearningStageWorkerRegistry

    context = _context(tmp_path, provider="omni")
    process = {"pid": 41, "create_time_ns": 42}
    scope_name = "Local\\AgentGuiHybrid-omni-" + "a" * 64
    runtime_identity = module.compose_benchmark_provider_runtime_identity(
        provider="omni",
        lease_identity=None,
        profile_ref=None,
        listener_owner=None,
        process_identities=[process],
        process_scope={
            "scope_name": scope_name,
            "member_pids": [41],
            "process_identities": [process],
        },
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_provider_runtime",
        lambda provider, value: {
            "content_sha256": runtime_identity["content_sha256"]
        },
    )
    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        dispatch_receipt = module.attest_benchmark_provider_dispatch(
            provider="omni",
            operation_ref=deepcopy(context["operation_ref"]),
            window_binding=deepcopy(context["window_binding"]),
            provider_runtime={"provider": "omni"},
        )

    observation = {
        "contract_version": "omniparser_invocation_cleanup_observation_v1",
        "provider_invocation_id": "invocation/exact",
        "process_identity": process,
        "descendant_identities": [],
        "provider_processes_after": [],
        "orphan_descendant_identities": [],
        "active_listeners_after": [],
        "pid_file_paths": [],
        "lease_path": None,
        "lease_files_after": [],
        "inventory_observable": True,
        "cleanup_status": "verified",
        "process_scope_name": scope_name,
        "process_scope_cleanup": {
            "scope_name": scope_name,
            "cleanup_status": "verified",
        },
        "process_scope_acquisition": {
            "scope_name": scope_name,
            "member_pids": [41],
        },
        "cleanup_reason": "outer_worker_terminated",
        "lineage": {"run_id": "run-1"},
        "resource_lease_identity": {"lease_id": "omni-lease"},
    }
    observation["content_sha256"] = module.content_sha256(observation)
    monkeypatch.setattr(
        omni,
        "load_omniparser_invocation_cleanup_observation",
        lambda invocation_id: deepcopy(observation),
    )
    provider_receipt_ref = _sealed_ref("receipt/exact", "1")
    provider_error_ref = _sealed_ref("error/exact", "2")
    provider_result_ref = _sealed_ref("result/exact", "3")
    root = (tmp_path / "workers").resolve()
    registry = LearningStageWorkerRegistry(result_root=root)
    record = {
        "contract_version": "learning_stage_worker_v1",
        "worker_id": "worker-exact-omni-cleanup",
        "run_id": "run-1",
        "stage": "screen_understanding",
        "operation_id": "operation-1",
        "task_kind": "panel_learning_hybrid_omni_discovery",
        "model_request_id": "request-exact-omni-cleanup",
        "payload_sha256": "f" * 64,
        "status": "cancelled",
        "started_at": "2026-08-28T00:00:00+00:00",
        "finished_at": "2026-08-28T00:00:01+00:00",
        "result_path": str(root / "worker-exact-omni-cleanup.result.json"),
        "journal_path": str(root / "worker-exact-omni-cleanup.worker.json"),
        "payload": {"_benchmark_v2_dispatch_context": deepcopy(context)},
        "worker_result": {
            "status": "completed",
            "response": {
                "contract_version": "hybrid_omni_discovery_result_v1",
                "outcome": "failed",
                "provider_invocation_id": "invocation/exact",
                "provider_receipt_ref": provider_receipt_ref,
                "provider_error_ref": provider_error_ref,
                "provider_result_ref": provider_result_ref,
            },
        },
        "process": None,
    }
    termination = {
        "worker_id": record["worker_id"],
        "model_request_id": record["model_request_id"],
        "backend_compute_termination": "terminated",
        "model_service_compute_termination": "not_covered",
        "cooperative_cleanup": {
            "contract_version": "hybrid_omni_cooperative_cleanup_v1",
            "provider_invocation_id": "invocation/exact",
            "provider_claim_status": "complete",
            "provider_result_ref": provider_result_ref,
            "provider_error_ref": provider_error_ref,
            "provider_receipt_ref": provider_receipt_ref,
            "provider_reason_class": "runtime_provider_failed",
            "failure_reason": "runtime_cancelled",
            "cleanup_status": "clean",
        },
    }
    projection = registry._compose_hybrid_benchmark_provider_cleanup(
        record=record,
        worker_termination=termination,
    )
    assert projection is not None
    assert projection["runtime_owner_ref"] == dispatch_receipt[
        "provider_runtime_attestation_ref"
    ]
    binding_path = root / (
        "worker-exact-omni-cleanup.benchmark-v2-hybrid-provider-cleanup.json"
    )
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    assert binding["predecessor_content_sha256"] == dispatch_receipt["content_sha256"]
    assert binding["authoritative_cleanup_ref"] == {
        "content_sha256": observation["content_sha256"]
    }

    recovered_projection = registry._compose_hybrid_benchmark_provider_cleanup(
        record=record,
        worker_termination={
            "worker_id": record["worker_id"],
            "model_request_id": record["model_request_id"],
            "backend_compute_termination": "not_running",
            "model_service_compute_termination": "request_not_active",
        },
    )
    assert recovered_projection == projection

    record["benchmark_provider_cleanup_ref"] = deepcopy(projection)
    registry._persist_record_journal(record)
    restarted = LearningStageWorkerRegistry(result_root=root)
    attachment = restarted.attachment_by_operation(
        run_id="run-1",
        stage="screen_understanding",
        operation_id="operation-1",
    )
    assert attachment is not None
    assert attachment["benchmark_provider_cleanup_ref"] == projection


@pytest.mark.parametrize("mutation", ["provider", "operation", "window"])
def test_stale_or_cross_provider_inputs_fail_before_attestation_or_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    context = _context(tmp_path)
    operation = deepcopy(context["operation_ref"])
    window = deepcopy(context["window_binding"])
    provider = "qwen"
    if mutation == "provider":
        provider = "vista"
    elif mutation == "operation":
        operation["revision"] = 6
    else:
        window["exact_hwnd"] = 999
    calls: list[str] = []
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: calls.append("window") or {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_provider_runtime",
        lambda provider, value: calls.append("runtime")
        or {"content_sha256": "e" * 64},
    )

    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        with pytest.raises(ValueError, match="stale|provider"):
            module.attest_benchmark_provider_dispatch(
                provider=provider,
                operation_ref=operation,
                window_binding=window,
                provider_runtime={"contract_version": "test_runtime_v1"},
            )

    assert calls == []
    assert not Path(str(context["receipt_journal_path"])).exists()


def test_receipt_fsync_failure_prevents_provider_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    context = _context(tmp_path)
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_provider_runtime",
        lambda provider, value: {"content_sha256": "e" * 64},
    )
    monkeypatch.setattr(module.os, "fsync", lambda descriptor: (_ for _ in ()).throw(OSError("disk")))
    dispatches = 0

    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        with pytest.raises(OSError, match="disk"):
            module.attest_benchmark_provider_dispatch(
                provider="qwen",
                operation_ref=deepcopy(context["operation_ref"]),
                window_binding=deepcopy(context["window_binding"]),
                provider_runtime={"contract_version": "test_runtime_v1"},
            )
        dispatches += 0

    assert dispatches == 0
    assert module.current_benchmark_dispatch_receipt_refs() == []


def test_spawn_scope_callback_runs_after_assignment_and_identity_before_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import windows_process_scope as module

    events: list[object] = []

    class _Scope:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def assign(self, _handle: object) -> None:
            events.append("assign")

        def close(self) -> None:
            events.append("scope-close")

    class _PsutilProcess:
        def __init__(self, pid: int) -> None:
            assert pid == 44

        def create_time(self) -> float:
            return 1.25

    monkeypatch.setattr(module, "WindowsProcessScope", _Scope)
    monkeypatch.setattr(module, "_stdio_source", lambda *args, **kwargs: 10)
    monkeypatch.setattr(module, "_duplicate_inheritable_handle", lambda value: 11)
    monkeypatch.setattr(
        module,
        "_create_suspended_process_with_handles",
        lambda *args, **kwargs: ("process", "thread", 44),
    )
    monkeypatch.setattr(module.psutil, "Process", _PsutilProcess)
    monkeypatch.setattr(
        module.win32process,
        "ResumeThread",
        lambda handle: events.append("resume"),
    )
    monkeypatch.setattr(module.win32api, "CloseHandle", lambda handle: None)

    process = module.spawn_process_in_scope(
        ["worker.exe"],
        scope_name="scope-1",
        cwd=Path.cwd(),
        before_resume=lambda identity: events.append(("attest", identity)),
    )

    assert process.process_identity == {"pid": 44, "create_time_ns": 1_250_000_000}
    assert events[:3] == [
        "assign",
        ("attest", {"pid": 44, "create_time_ns": 1_250_000_000}),
        "resume",
    ]


def test_spawn_scope_callback_failure_terminates_suspended_child_without_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import windows_process_scope as module

    events: list[str] = []

    class _Scope:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def assign(self, _handle: object) -> None:
            events.append("assign")

        def close(self) -> None:
            pass

    class _PsutilProcess:
        def __init__(self, _pid: int) -> None:
            pass

        def create_time(self) -> float:
            return 1.0

    monkeypatch.setattr(module, "WindowsProcessScope", _Scope)
    monkeypatch.setattr(module, "_stdio_source", lambda *args, **kwargs: 10)
    monkeypatch.setattr(module, "_duplicate_inheritable_handle", lambda value: 11)
    monkeypatch.setattr(
        module,
        "_create_suspended_process_with_handles",
        lambda *args, **kwargs: ("process", "thread", 44),
    )
    monkeypatch.setattr(module.psutil, "Process", _PsutilProcess)
    monkeypatch.setattr(module.win32process, "ResumeThread", lambda handle: events.append("resume"))
    monkeypatch.setattr(module.win32process, "TerminateProcess", lambda *args: events.append("terminate"), raising=False)
    monkeypatch.setattr(module.win32api, "TerminateProcess", lambda *args: events.append("terminate"))
    monkeypatch.setattr(module.win32api, "CloseHandle", lambda handle: None)

    with pytest.raises(RuntimeError, match="attestation failed"):
        module.spawn_process_in_scope(
            ["worker.exe"],
            scope_name="scope-1",
            cwd=Path.cwd(),
            before_resume=lambda identity: (_ for _ in ()).throw(
                RuntimeError("attestation failed")
            ),
        )

    assert events == ["assign", "terminate"]


def test_qwen_http_boundary_attests_inside_the_cancellation_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    events: list[str] = []
    lease = {"lease_id": "exact-qwen"}
    context = {"provider": "qwen"}

    class _Cancellation:
        def is_set(self) -> bool:
            return False

        def run_if_not_cancelled(self, stage: str, action: object):
            events.append(f"fence:{stage}")
            return True, action()

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            return json.dumps(
                {"choices": [{"message": {"content": "{}"}}]}
            ).encode("utf-8")

    monkeypatch.setattr(
        model_server,
        "_profile_for_qwen_model_lease",
        lambda value: {
            "endpoint": "http://127.0.0.1:1/chat/completions",
            "model_name": "qwen",
        },
    )
    monkeypatch.setattr(
        model_server,
        "_mark_qwen_model_request_in_flight",
        lambda value: events.append("request-in-flight") or 1,
    )
    monkeypatch.setattr(
        model_server,
        "_mark_qwen_model_compute_complete",
        lambda *args, **kwargs: events.append("compute-complete"),
    )
    monkeypatch.setattr(
        attestation,
        "current_benchmark_dispatch_context",
        lambda: deepcopy(context),
    )
    monkeypatch.setattr(
        attestation,
        "attest_managed_model_dispatch",
        lambda **kwargs: events.append("attest") or {"content_sha256": "a" * 64},
    )
    monkeypatch.setattr(
        model_server.urllib.request,
        "urlopen",
        lambda *args, **kwargs: events.append("dispatch") or _Response(),
    )

    model_server.run_qwen_binding_model(
        request={"candidate_ids": []},
        screenshot_bytes=b"png",
        screenshot_media_type="image/png",
        screenshot_sha256=__import__("hashlib").sha256(b"png").hexdigest(),
        cancellation_event=_Cancellation(),
        model_lease=lease,
    )

    assert events[:4] == [
        "fence:qwen_provider_dispatch",
        "attest",
        "request-in-flight",
        "dispatch",
    ]


def test_vista_attests_once_before_each_locate_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import calibration_sequence
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from tests.test_learning_calibration_sequence import (
        _locate_response,
        _normal_preflight,
        _sequence_payload,
    )

    events: list[str] = []
    responses = [
        _locate_response(
            completed_ids=["candidate-1"], remaining_count=1, resumable=True
        ),
        _locate_response(
            completed_ids=["candidate-1", "candidate-2"],
            remaining_count=0,
            resumable=False,
        ),
    ]
    monkeypatch.setattr(
        attestation,
        "current_benchmark_dispatch_context",
        lambda: {"provider": "vista"},
    )
    monkeypatch.setattr(
        attestation,
        "attest_managed_model_dispatch",
        lambda **kwargs: events.append("attest") or {"content_sha256": "b" * 64},
    )

    calibration_sequence.run_learning_calibration_sequence(
        _sequence_payload(),
        locate_runner=lambda payload: events.append("dispatch") or responses.pop(0),
        profile_loader=lambda *_args: {"profile_id": "vista"},
        resource_preflight_builder=_normal_preflight,
        model_lease={"lease_id": "vista-exact"},
    )

    assert events == ["attest", "dispatch", "attest", "dispatch"]


def test_incumbent_qwen_attests_immediately_before_provider_analyze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from app.operation.observe import screen_reader
    from app.operation.observe.contracts import ObserveScreenReadRequest

    image = tmp_path / "screen.png"
    image.write_bytes(b"not-decoded-before-provider")
    events: list[str] = []

    class _Provider:
        def bind_managed_model_lease(self, lease: object) -> None:
            events.append("bind")

        def analyze(self, request: object) -> object:
            events.append("dispatch")
            raise RuntimeError("stop-after-dispatch")

    class _Factory:
        @staticmethod
        def load_config() -> dict[str, object]:
            return {}

        @staticmethod
        def create(**_kwargs: object) -> _Provider:
            return _Provider()

    monkeypatch.setattr(
        attestation,
        "current_benchmark_dispatch_context",
        lambda: {"provider": "qwen"},
    )
    monkeypatch.setattr(
        attestation,
        "attest_managed_model_dispatch",
        lambda **kwargs: events.append("attest") or {"content_sha256": "c" * 64},
    )
    request = ObserveScreenReadRequest.model_validate(
        {
            "image_path": str(image),
            "task": "observe",
            "goal": "read",
            "provider_mode": "local_qwen",
        }
    )

    result = screen_reader.read_screen(
        request,
        provider_factory=_Factory,
        managed_model_lease={"lease_id": "qwen-exact"},
    )

    assert result.success is False
    assert events == ["bind", "attest", "dispatch"]


def test_omni_suspended_child_attests_before_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from app.learn.hybrid import windows_process_scope
    from app.learn.recognition.uei import omniparser_shadow_adapter as omni
    from tests.test_uei_v1_omniparser_shadow_adapter import (
        FakeProcess,
        _budget,
        _capture,
        _config,
    )

    events: list[str] = []
    process = FakeProcess(payload={"items": [], "duration_ms": 1, "resource_units": 1})
    process.process_identity = {"pid": process.pid, "create_time_ns": 7}

    def _spawn(command: list[str], **kwargs: object) -> FakeProcess:
        before_resume = kwargs.get("before_resume")
        assert callable(before_resume)
        before_resume(deepcopy(process.process_identity))
        events.append("resume")
        output = Path(command[command.index("--output-json") + 1])
        output.write_text(json.dumps(process.payload), encoding="utf-8")
        return process

    class _Scope:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def pids(self) -> list[int]:
            return [process.pid]

        def close(self) -> None:
            pass

    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", "omni-scope")
    monkeypatch.setattr(windows_process_scope, "spawn_process_in_scope", _spawn)
    monkeypatch.setattr(windows_process_scope, "WindowsProcessScope", _Scope)
    monkeypatch.setattr(
        attestation,
        "current_benchmark_dispatch_context",
        lambda: {"provider": "omni", "operation_ref": {}, "window_binding": {}},
    )
    monkeypatch.setattr(
        attestation,
        "attest_benchmark_provider_dispatch",
        lambda **kwargs: events.append("attest") or {"content_sha256": "d" * 64},
    )
    adapter = omni.OmniParserShadowAdapter(configuration=_config(tmp_path))
    adapter._cleanup_observation = {
        "process_identity": None,
        "descendant_identities": [],
        "inventory_observable": True,
    }
    monkeypatch.setattr(adapter, "_capture_cleanup_process_tree", lambda value: None)

    adapter._invoke_worker(
        capture=_capture(tmp_path), budget=_budget(), cancellation_event=None
    )

    assert events == ["attest", "resume"]


@pytest.mark.parametrize("reason", ["lease", "profile", "socket"])
def test_qwen_stale_lease_profile_or_socket_fails_before_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
) -> None:
    from app.core import model_server
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    context = _context(tmp_path)
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        model_server,
        "_profile_for_qwen_model_lease",
        lambda value: (_ for _ in ()).throw(RuntimeError(f"stale {reason}")),
    )

    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        with pytest.raises(RuntimeError, match=reason):
            module.attest_managed_model_dispatch(
                model_lease={"lease_id": "stale"},
                dispatch_context=context,
            )

    assert not Path(str(context["receipt_journal_path"])).exists()


@pytest.mark.parametrize("fact", ["HWND", "PID", "create-time", "Job"])
def test_fresh_window_fact_failure_prevents_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fact: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    context = _context(tmp_path)
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: (_ for _ in ()).throw(ValueError(f"stale {fact}")),
    )
    runtime_calls = 0

    def _runtime(*_args: object) -> dict[str, str]:
        nonlocal runtime_calls
        runtime_calls += 1
        return {"content_sha256": "e" * 64}

    monkeypatch.setattr(module, "_attest_exact_provider_runtime", _runtime)
    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        with pytest.raises(ValueError, match=fact):
            module.attest_benchmark_provider_dispatch(
                provider="qwen",
                operation_ref=context["operation_ref"],
                window_binding=context["window_binding"],
                provider_runtime={"lease_id": "exact"},
            )

    assert runtime_calls == 0
    assert not Path(str(context["receipt_journal_path"])).exists()


def test_vista_lease_binds_incarnation_profile_job_and_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    identity = {"pid": 202, "create_time_ns": 303}
    profile = {"profile_id": "vista-exact", "port": 7860}
    lease = {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": module.content_sha256(
            {"profile_id": profile["profile_id"], "process_identities": [identity]}
        ),
        "profile": profile,
        "process_identities": [identity],
        "process_scope_name": "scope-vista",
        "process_scope_acquisition": {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": "scope-vista",
            "member_pids": [202],
            "process_identities": [identity],
        },
    }

    class _Scope:
        def __init__(self, name: str, *, create: bool) -> None:
            assert (name, create) == ("scope-vista", False)

        def pids(self) -> list[int]:
            return [202]

        def close(self) -> None:
            return None

    monkeypatch.setattr(model_server, "_current_process_identity", lambda pid: identity)
    monkeypatch.setattr(
        "app.learn.hybrid.windows_process_scope.WindowsProcessScope", _Scope
    )
    monkeypatch.setattr(model_server, "_listening_pids_for_port", lambda port: [202])

    assert module._attest_exact_provider_runtime("vista", lease)["content_sha256"]

    stale = deepcopy(lease)
    stale["incarnation_id"] = "f" * 64
    with pytest.raises(ValueError, match="incarnation"):
        module._attest_exact_provider_runtime("vista", stale)

    monkeypatch.setattr(model_server, "_listening_pids_for_port", lambda port: [999])
    with pytest.raises(ValueError, match="socket|listener"):
        module._attest_exact_provider_runtime("vista", lease)


def test_receipt_validator_reconstructs_exact_durable_multiset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    context = _context(tmp_path)
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_provider_runtime",
        lambda provider, value: {"content_sha256": "e" * 64},
    )
    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        module.attest_benchmark_provider_dispatch(
            provider="qwen",
            operation_ref=context["operation_ref"],
            window_binding=context["window_binding"],
            provider_runtime={"lease_id": "exact"},
        )
        refs = module.current_benchmark_dispatch_receipt_refs()

    operation = context["operation_ref"]
    identity = {
        name: deepcopy(operation[name])
        for name in (
            "run_id",
            "stage",
            "operation_id",
            "window_binding_ref",
            "capture_ref",
        )
    }
    assert module.validate_benchmark_dispatch_receipt_refs(
        receipt_journal_path=Path(str(context["receipt_journal_path"])),
        receipt_refs=refs,
        operation_identity=identity,
        expected_provider_counts={"qwen": 1},
        expected_dispatch_contexts={"qwen": context},
    ) == refs

    stale_refs = deepcopy(refs)
    stale_refs[0]["provider"] = "vista"
    with pytest.raises(ValueError, match="provider"):
        module.validate_benchmark_dispatch_receipt_refs(
            receipt_journal_path=Path(str(context["receipt_journal_path"])),
            receipt_refs=stale_refs,
            operation_identity=identity,
            expected_provider_counts={"qwen": 1},
            expected_dispatch_contexts={"qwen": context},
        )


def test_receipt_validator_enforces_each_worker_context_chain_and_ref_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    contexts = {
        provider: _context(tmp_path, provider=provider)
        for provider in ("omni", "qwen", "vista")
    }
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_provider_runtime",
        lambda provider, value: {
            "content_sha256": {"omni": "1", "qwen": "2", "vista": "3"}[
                provider
            ]
            * 64
        },
    )
    refs: list[dict[str, str]] = []
    for provider, count in (("omni", 1), ("qwen", 1), ("vista", 2)):
        context = contexts[provider]
        with module.install_benchmark_dispatch_attestor(dispatch_context=context):
            for _ in range(count):
                module.attest_benchmark_provider_dispatch(
                    provider=provider,
                    operation_ref=context["operation_ref"],
                    window_binding=context["window_binding"],
                    provider_runtime={"provider": provider},
                )
            refs.extend(module.current_benchmark_dispatch_receipt_refs())
    operation = contexts["omni"]["operation_ref"]
    identity = {
        name: deepcopy(operation[name])
        for name in (
            "run_id",
            "stage",
            "operation_id",
            "window_binding_ref",
            "capture_ref",
        )
    }
    journal = Path(str(contexts["omni"]["receipt_journal_path"]))
    kwargs = {
        "receipt_journal_path": journal,
        "operation_identity": identity,
        "expected_provider_counts": {"omni": 1, "qwen": 1, "vista": 2},
        "expected_dispatch_contexts": contexts,
    }
    assert module.validate_benchmark_dispatch_receipt_refs(
        receipt_refs=refs, **kwargs
    ) == refs

    wrong_order = deepcopy(refs)
    wrong_order[0], wrong_order[1] = wrong_order[1], wrong_order[0]
    with pytest.raises(ValueError, match="order"):
        module.validate_benchmark_dispatch_receipt_refs(
            receipt_refs=wrong_order, **kwargs
        )

    stale_qwen = module.compose_benchmark_dispatch_context(
        provider="qwen",
        operation_ref={
            **{
                name: deepcopy(value)
                for name, value in contexts["qwen"]["operation_ref"].items()
                if name != "content_sha256"
            },
            "revision": 8,
        },
        window_binding=contexts["qwen"]["window_binding"],
        receipt_journal_path=journal,
    )
    with pytest.raises(ValueError, match="revision|context|operation"):
        module.validate_benchmark_dispatch_receipt_refs(
            receipt_refs=refs,
            **{**kwargs, "expected_dispatch_contexts": {**contexts, "qwen": stale_qwen}},
        )

    original = journal.read_bytes()
    journal.write_bytes(original + original.splitlines(keepends=True)[0])
    with pytest.raises(ValueError, match="duplicate"):
        module.validate_benchmark_dispatch_receipt_refs(
            receipt_refs=refs, **kwargs
        )


def test_hybrid_adoption_rejects_resealed_stale_projected_provider_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    context = _context(tmp_path, provider="qwen", revision=8)
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_provider_runtime",
        lambda provider, value: {"content_sha256": "e" * 64},
    )
    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        module.attest_benchmark_provider_dispatch(
            provider="qwen",
            operation_ref=context["operation_ref"],
            window_binding=context["window_binding"],
            provider_runtime={"provider": "qwen"},
        )
        receipt_refs = module.current_benchmark_dispatch_receipt_refs()
    context_ref = module.compose_benchmark_dispatch_context_ref(context=context)
    response = {
        "orchestration": {
            "benchmark_v2_provider_dispatch_receipt_refs": receipt_refs,
            "benchmark_v2_provider_dispatch_context_refs": {"qwen": context_ref},
        }
    }
    composition = type(
        "Composition",
        (),
        {
            "composition_kind": "test",
            "benchmark_v2_worker_binding_resolver": object(),
            "project_root": tmp_path,
        },
    )()
    window_binding = {
        name: deepcopy(context["operation_ref"][name])
        for name in (
            "run_id",
            "stage",
            "operation_id",
            "window_binding_ref",
            "capture_ref",
        )
    }
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_dispatch_journal_path",
        lambda **_kwargs: Path(str(context["receipt_journal_path"])),
    )

    assert workflow_service._validate_benchmark_v2_dispatch_response(
        composition=composition,
        response=response,
        window_binding=window_binding,
        expected_provider_counts={"qwen": 1},
        hybrid=True,
        dispatch_revision=None,
        provider_dispatch_context_refs={"qwen": context_ref},
    )["orchestration"]["benchmark_v2_provider_dispatch_receipt_refs"] == receipt_refs

    stale = deepcopy(context_ref)
    stale_context = stale["dispatch_context"]
    stale_context["operation_ref"]["revision"] = 9
    stale_context["operation_ref"].pop("content_sha256")
    stale_context["operation_ref"]["content_sha256"] = module.content_sha256(
        stale_context["operation_ref"]
    )
    stale_context["content_sha256"] = module.content_sha256(stale_context)
    stale["content_sha256"] = module.content_sha256(stale)
    stale_response = deepcopy(response)
    stale_response["orchestration"][
        "benchmark_v2_provider_dispatch_context_refs"
    ]["qwen"] = stale
    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="stale",
    ):
        workflow_service._validate_benchmark_v2_dispatch_response(
            composition=composition,
            response=stale_response,
            window_binding=window_binding,
            expected_provider_counts={"qwen": 1},
            hybrid=True,
            dispatch_revision=None,
            provider_dispatch_context_refs={"qwen": context_ref},
        )


@pytest.mark.parametrize("field", ["dispatch_index", "predecessor_content_sha256"])
def test_receipt_validator_rejects_resealed_skipped_chain_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    context = _context(tmp_path, provider="vista")
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_provider_runtime",
        lambda provider, value: {"content_sha256": "e" * 64},
    )
    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        for _ in range(2):
            module.attest_benchmark_provider_dispatch(
                provider="vista",
                operation_ref=context["operation_ref"],
                window_binding=context["window_binding"],
                provider_runtime={"provider": "vista"},
            )
        refs = module.current_benchmark_dispatch_receipt_refs()
    journal = Path(str(context["receipt_journal_path"]))
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    target = rows[1]
    if field == "dispatch_index":
        target[field] = 3
    else:
        target[field] = "f" * 64
    target["content_sha256"] = module.content_sha256(target)
    refs[1]["content_sha256"] = target["content_sha256"]
    journal.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    operation = context["operation_ref"]
    identity = {
        name: deepcopy(operation[name])
        for name in (
            "run_id",
            "stage",
            "operation_id",
            "window_binding_ref",
            "capture_ref",
        )
    }
    with pytest.raises(ValueError, match="index|predecessor|chain"):
        module.validate_benchmark_dispatch_receipt_refs(
            receipt_journal_path=journal,
            receipt_refs=refs,
            operation_identity=identity,
            expected_provider_counts={"vista": 2},
            expected_dispatch_contexts={"vista": context},
        )


def test_short_receipt_write_prevents_fsync_and_dispatch_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as module

    context = _context(tmp_path)
    monkeypatch.setattr(
        module,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        module,
        "_attest_exact_provider_runtime",
        lambda provider, value: {"content_sha256": "e" * 64},
    )
    fsync_calls: list[int] = []

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
    monkeypatch.setattr(module.os, "fsync", lambda value: fsync_calls.append(value))
    with module.install_benchmark_dispatch_attestor(dispatch_context=context):
        with pytest.raises(OSError, match="short"):
            module.attest_benchmark_provider_dispatch(
                provider="qwen",
                operation_ref=context["operation_ref"],
                window_binding=context["window_binding"],
                provider_runtime={"provider": "qwen"},
            )
        assert module.current_benchmark_dispatch_receipt_refs() == []
    assert fsync_calls == []


def test_vista_receipt_count_is_exactly_bound_to_calibration_batch_count() -> None:
    from app.learn import workflow_service

    response = {
        "orchestration": {"benchmark_v2_vista_batch_count": 2},
        "result": {
            "success": True,
            "data": {
                "result": {
                    "calibration_sequence": {
                        "contract_version": "learning_calibration_sequence_result_v1",
                        "status": "completed",
                        "batch_count": 2,
                    }
                }
            },
        },
    }
    assert workflow_service._benchmark_v2_expected_dispatch_counts(
        task_kind="panel_learning_calibration_sequence", response=response
    ) == {"omni": 1, "qwen": 1, "vista": 2}

    stale = deepcopy(response)
    stale["orchestration"]["benchmark_v2_vista_batch_count"] = 1
    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="batch_count",
    ):
        workflow_service._benchmark_v2_expected_dispatch_counts(
            task_kind="panel_learning_calibration_sequence", response=stale
        )


def test_registry_validates_dispatch_response_before_adoption_receipt_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import RLock

    from app.learn.workflow_worker import LearningStageWorkerRegistry

    registry = object.__new__(LearningStageWorkerRegistry)
    registry._lock = RLock()
    record = {
        "worker_id": "worker-1",
        "run_id": "run-1",
        "stage": "screen_understanding",
        "operation_id": "operation-1",
        "task_kind": "vision_observe_screen",
        "model_request_id": "request-1",
        "payload_sha256": "a" * 64,
        "status": "completed",
        "worker_result": {
            "status": "completed",
            "response": {"provider_dispatch_receipt_refs": []},
        },
    }
    registry._records = {"worker-1": record}
    monkeypatch.setattr(registry, "_refresh_record", lambda value: None)
    persisted: list[str] = []
    monkeypatch.setattr(
        registry,
        "_persist_record_journal",
        lambda value: persisted.append("persist"),
    )

    with pytest.raises(ValueError, match="stale dispatch"):
        registry.adopt_result(
            worker_id="worker-1",
            run_id="run-1",
            stage="screen_understanding",
            operation_id="operation-1",
            result_validator=lambda response: (_ for _ in ()).throw(
                ValueError("stale dispatch")
            ),
        )

    assert "result_adoption" not in record
    assert persisted == []


def test_cancelled_qwen_fence_has_zero_attestation_and_http_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    calls: list[str] = []

    class _Cancellation:
        def is_set(self) -> bool:
            return False

        def run_if_not_cancelled(self, stage: str, action: object):
            calls.append(stage)
            return False, None

    monkeypatch.setattr(
        attestation, "current_benchmark_dispatch_context", lambda: {"provider": "qwen"}
    )
    monkeypatch.setattr(
        attestation,
        "attest_managed_model_dispatch",
        lambda **kwargs: calls.append("attest"),
    )
    monkeypatch.setattr(
        model_server,
        "_profile_for_qwen_model_lease",
        lambda value: {
            "endpoint": "http://127.0.0.1:1/chat/completions",
            "model_name": "qwen",
        },
    )
    monkeypatch.setattr(
        model_server.urllib.request,
        "urlopen",
        lambda *args, **kwargs: calls.append("dispatch"),
    )

    with pytest.raises(RuntimeError, match="cancelled"):
        model_server.run_qwen_binding_model(
            request={"candidate_ids": []},
            screenshot_bytes=b"png",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"png").hexdigest(),
            cancellation_event=_Cancellation(),
            model_lease={"lease_id": "qwen"},
        )

    assert calls == ["qwen_provider_dispatch"]


def test_cancelled_vista_fence_has_zero_attestation_and_locate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import calibration_sequence
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from tests.test_learning_calibration_sequence import _normal_preflight, _sequence_payload

    calls: list[str] = []

    class _Cancellation:
        def run_if_not_cancelled(self, stage: str, action: object):
            calls.append(stage)
            return False, None

    monkeypatch.setattr(
        attestation, "current_benchmark_dispatch_context", lambda: {"provider": "vista"}
    )
    monkeypatch.setattr(
        attestation,
        "attest_managed_model_dispatch",
        lambda **kwargs: calls.append("attest"),
    )
    response = calibration_sequence.run_learning_calibration_sequence(
        _sequence_payload(),
        locate_runner=lambda payload: calls.append("dispatch"),
        profile_loader=lambda *_args: {"profile_id": "vista"},
        resource_preflight_builder=_normal_preflight,
        model_lease={"lease_id": "vista"},
        cancellation_event=_Cancellation(),
    )

    assert response["success"] is False
    assert calls == ["vista_batch_acquisition"]


def test_cancelled_incumbent_fence_has_zero_attestation_and_analyze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from app.operation.observe import screen_reader
    from app.operation.observe.contracts import ObserveScreenReadRequest

    image = tmp_path / "screen.png"
    image.write_bytes(b"png")
    calls: list[str] = []

    class _Provider:
        def bind_managed_model_lease(self, lease: object) -> None:
            return None

        def analyze(self, request: object) -> object:
            calls.append("dispatch")

    class _Factory:
        @staticmethod
        def load_config() -> dict[str, object]:
            return {}

        @staticmethod
        def create(**_kwargs: object) -> _Provider:
            return _Provider()

    class _Cancellation:
        def run_if_not_cancelled(self, stage: str, action: object):
            calls.append(stage)
            return False, None

    monkeypatch.setattr(
        attestation, "current_benchmark_dispatch_context", lambda: {"provider": "qwen"}
    )
    monkeypatch.setattr(
        attestation,
        "attest_managed_model_dispatch",
        lambda **kwargs: calls.append("attest"),
    )
    request = ObserveScreenReadRequest.model_validate(
        {
            "image_path": str(image),
            "task": "observe",
            "goal": "read",
            "provider_mode": "local_qwen",
        }
    )

    result = screen_reader.read_screen(
        request,
        provider_factory=_Factory,
        managed_model_lease={"lease_id": "qwen"},
        cancellation_event=_Cancellation(),
    )

    assert result.success is False
    assert calls == ["incumbent_qwen_provider_dispatch"]


def test_fusion_and_review_never_receive_provider_dispatch_context() -> None:
    from app.learn import workflow_service

    composition = type(
        "Composition",
        (),
        {"benchmark_v2_worker_binding_resolver": object(), "composition_kind": "test"},
    )()
    binding = {
        "run_id": "run-1",
        "stage": "screen_understanding",
        "operation_id": "operation-1",
        "window_binding_ref": _sealed_ref("window-1", "a"),
        "capture_ref": _sealed_ref("capture-1", "b"),
    }
    for task_kind in (
        "panel_learning_hybrid_fusion",
        "panel_learning_hybrid_review_projection",
    ):
        assert workflow_service._benchmark_v2_dispatch_context_for_worker(
            composition=composition,
            window_binding=binding,
            task_kind=task_kind,
            revision=1,
        ) is None


def test_qwen_benchmark_context_without_exact_lease_has_zero_http_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    dispatches: list[str] = []
    monkeypatch.setattr(
        attestation, "current_benchmark_dispatch_context", lambda: {"provider": "qwen"}
    )
    monkeypatch.setattr(
        model_server.urllib.request,
        "urlopen",
        lambda *args, **kwargs: dispatches.append("dispatch"),
    )

    with pytest.raises(ValueError, match="exact managed lease"):
        model_server.run_qwen_binding_model(
            request={"candidate_ids": []},
            screenshot_bytes=b"png",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"png").hexdigest(),
            model_lease=None,
        )

    assert dispatches == []


def test_incumbent_benchmark_context_without_exact_lease_has_zero_analyze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from app.operation.observe import screen_reader
    from app.operation.observe.contracts import ObserveScreenReadRequest

    image = tmp_path / "screen.png"
    image.write_bytes(b"png")
    dispatches: list[str] = []

    class _Provider:
        def analyze(self, request: object) -> object:
            dispatches.append("dispatch")

    class _Factory:
        @staticmethod
        def load_config() -> dict[str, object]:
            return {}

        @staticmethod
        def create(**_kwargs: object) -> _Provider:
            return _Provider()

    monkeypatch.setattr(
        attestation, "current_benchmark_dispatch_context", lambda: {"provider": "qwen"}
    )
    request = ObserveScreenReadRequest.model_validate(
        {
            "image_path": str(image),
            "task": "observe",
            "goal": "read",
            "provider_mode": "local_qwen",
        }
    )

    result = screen_reader.read_screen(request, provider_factory=_Factory)

    assert result.success is False
    assert "exact managed lease" in str(result.error)
    assert dispatches == []


def test_omni_benchmark_context_without_exact_job_has_zero_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from app.learn.recognition.uei import omniparser_shadow_adapter as omni
    from tests.test_uei_v1_omniparser_shadow_adapter import _budget, _capture, _config

    spawns: list[str] = []
    monkeypatch.delenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", raising=False)
    monkeypatch.setattr(
        attestation, "current_benchmark_dispatch_context", lambda: {"provider": "omni"}
    )
    monkeypatch.setattr(
        omni.subprocess,
        "Popen",
        lambda *args, **kwargs: spawns.append("spawn"),
    )
    adapter = omni.OmniParserShadowAdapter(configuration=_config(tmp_path))

    with pytest.raises(omni.OmniParserShadowAdapterError) as captured:
        adapter._invoke_worker(
            capture=_capture(tmp_path), budget=_budget(), cancellation_event=None
        )

    assert captured.value.code == "runtime_benchmark_process_scope_required"
    assert spawns == []
