from __future__ import annotations

import json
import base64
import os
import socket
import subprocess
import sys
import urllib.error
from urllib.parse import urlsplit
from copy import deepcopy
from threading import Event, Thread
import time

import pytest


_HYBRID_LINEAGE = {
    "run_id": "run-hybrid-release",
    "workflow_revision": 7,
    "operation_id": "operation-hybrid-release",
    "stage": "panel_learning_calibration_sequence",
    "stage_execution_id": "stage-execution-hybrid-release",
}
_PREDECESSOR_SHA256 = "a" * 64
_PROVIDER_RESULT_SHA256 = "b" * 64


def _cleanup_lease() -> dict:
    process = {"pid": 4123, "create_time": 100.5, "executable": "qwen-server.exe"}
    return {"contract_version":"qwen_model_server_lease_v1", "lease_id":"lease-cleanup",
        "owner_request_id":"owner-cleanup", "profile_id":"qwen", "incarnation_id":"inc-cleanup",
        "server_base_url":"http://127.0.0.1:12345", "server_model_id":"qwen", "profile_sha256":"1"*64,
        "server_process_identity":process}


def test_qwen_cleanup_receipt_requires_exact_terminal_lifecycle_evidence() -> None:
    from app.core.model_server import build_qwen_cleanup_receipt, validate_qwen_cleanup_receipt
    lease = _cleanup_lease()
    result = {"status":"released", "lease":lease, "shared_server_retained":False,
        "server_termination":"verified_exact_process_exited",
        "release":{"status":"proven_absent", "identity":lease["server_process_identity"]},
        "process_identity":lease["server_process_identity"]}
    receipt = build_qwen_cleanup_receipt(release_result=result, model_lease=lease)
    assert validate_qwen_cleanup_receipt(receipt) == receipt


@pytest.mark.parametrize("mutation", ["shared", "provider", "process", "indeterminate"])
def test_qwen_cleanup_receipt_fails_closed_for_non_exact_evidence(mutation: str) -> None:
    from app.core.model_server import build_qwen_cleanup_receipt
    lease = _cleanup_lease()
    result = {"status":"released", "lease":lease, "shared_server_retained":False,
        "server_termination":"verified_exact_process_exited",
        "release":{"status":"proven_absent", "identity":lease["server_process_identity"]},
        "process_identity":lease["server_process_identity"]}
    if mutation == "shared": result["shared_server_retained"] = True
    elif mutation == "provider": result["lease"] = {**lease, "server_model_id":"not-qwen"}
    elif mutation == "process": result["process_identity"] = {"pid":999}
    else: result["release"] = {"status":"unobservable"}
    with pytest.raises(ValueError):
        build_qwen_cleanup_receipt(release_result=result, model_lease=lease)


def test_hybrid_vista_release_builds_inventory_from_observed_cleanup(
    tmp_path, monkeypatch
) -> None:
    from app.core import model_server
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    profile = {
        "profile_id": "vista-test",
        "role": ["locate"],
        "provider_mode": "local_grounding",
        "port": 13240,
        "pid_file": str(tmp_path / "vista.pid"),
    }
    scope_name = process_scope_name(_HYBRID_LINEAGE, "vista")
    scope = WindowsProcessScope(scope_name, create=True)
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    process = __import__("psutil").Process(helper.pid)
    identities = [{
        "pid": helper.pid,
        "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
    }]
    lease = {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": "vista-incarnation",
        "profile": profile,
        "process_identities": identities,
        "process_scope_name": scope_name,
        "process_scope_acquisition": {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": scope_name,
            "member_pids": [identity["pid"] for identity in identities],
            "process_identities": identities,
        },
    }
    monkeypatch.setattr(
        model_server,
        "stop_model_server",
        lambda selected: {
            "stopped": True,
            "after": {"status": "unreachable"},
        },
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda identity: {"status": "proven_absent", "identity": identity},
    )
    monkeypatch.setattr(
        model_server, "_descendant_identities_for_parents", lambda parents: ([], True)
    )
    monkeypatch.setattr(model_server, "_listening_pids_for_port", lambda port: [])

    try:
        inventory = model_server.release_hybrid_vista_model_lease(
            lease,
            lineage=_HYBRID_LINEAGE,
            predecessor_sha256=_PREDECESSOR_SHA256,
            provider_result_sha256=_PROVIDER_RESULT_SHA256,
        )
    finally:
        scope.close()

    assert inventory["release_status"] == "verified"
    assert inventory["provider_processes_after"] == []
    assert inventory["active_listeners_after"] == []
    assert inventory["lease_files_after"] == []
    helper.close()


def test_hybrid_vista_release_fails_closed_on_listener_or_failed_stop(
    tmp_path, monkeypatch
) -> None:
    from app.core import model_server
    from app.learn.hybrid.gpu_lifecycle import release_hybrid_provider
    from app.learn.hybrid.windows_process_scope import process_scope_name

    pid_path = tmp_path / "vista.pid"
    pid_path.write_text("4123", encoding="utf-8")
    identity = {"pid": 4123, "create_time_ns": 100_000_000_000}
    lease = {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": "vista-incarnation",
        "profile": {
            "profile_id": "vista-test",
            "role": ["locate"],
            "provider_mode": "local_grounding",
            "port": 13240,
            "pid_file": str(pid_path),
        },
        "process_identities": [identity],
        "process_scope_name": process_scope_name(_HYBRID_LINEAGE, "vista"),
        "process_scope_acquisition": {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": process_scope_name(_HYBRID_LINEAGE, "vista"),
            "member_pids": [identity["pid"]],
            "process_identities": [identity],
        },
    }
    monkeypatch.setattr(
        model_server,
        "stop_model_server",
        lambda selected: {"stopped": False, "after": {"status": "running"}},
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda observed: {"status": "exact_live", "identity": observed},
    )
    monkeypatch.setattr(
        model_server, "_descendant_identities_for_parents", lambda parents: ([], True)
    )
    from app.learn.hybrid import windows_process_scope

    monkeypatch.setattr(
        windows_process_scope,
        "observe_process_scope_cleanup",
        lambda name, **kwargs: {
            "contract_version": "hybrid_windows_process_scope_v1",
            "scope_name": name,
            "cleanup_status": "indeterminate",
            "member_pids_after": [4123],
            "active_listeners_after": [{"port": 13240, "pid": 4123}],
        },
    )

    inventory = model_server.release_hybrid_vista_model_lease(
        lease,
        lineage=_HYBRID_LINEAGE,
        predecessor_sha256=_PREDECESSOR_SHA256,
        provider_result_sha256=_PROVIDER_RESULT_SHA256,
    )

    assert inventory["release_status"] == "failed"
    assert inventory["provider_processes_after"] == [identity]
    assert inventory["active_listeners_after"] == [{"port": 13240, "pid": 4123}]
    with pytest.raises(RuntimeError, match="cleanup is not verified"):
        release_hybrid_provider("vista", process_inventory=lambda provider: inventory)


def test_hybrid_vista_lease_rejects_missing_or_ambiguous_process_identity() -> None:
    from app.core.model_server import build_hybrid_vista_model_lease

    profile = {"profile_id": "vista-test", "provider_mode": "local_grounding"}
    os.environ["AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME"] = (
        "Local\\AgentGuiHybrid-vista-" + "1" * 64
    )

    try:
        with pytest.raises(ValueError, match="no exact process identity"):
            build_hybrid_vista_model_lease(
                profile,
                {"before": {"status": "unreachable"}, "after": {"status": "ready"}},
            )
    finally:
        os.environ.pop("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", None)


def test_hybrid_vista_lease_binds_exact_nonempty_job_membership(
    tmp_path,
    monkeypatch,
) -> None:
    from app.core.model_server import build_hybrid_vista_model_lease
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    scope_name = process_scope_name(_HYBRID_LINEAGE, "vista")
    scope = WindowsProcessScope(scope_name, create=True)
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    process = __import__("psutil").Process(helper.pid)
    identity = {
        "pid": helper.pid,
        "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
    }
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    try:
        lease = build_hybrid_vista_model_lease(
            {"profile_id": "vista-job-test"},
            {"start": {"pid": helper.pid}},
        )
        with pytest.raises(ValueError, match="outside its exact scope"):
            build_hybrid_vista_model_lease(
                {"profile_id": "vista-job-test"},
                {"start": {"pid": os.getpid()}},
            )
    finally:
        scope.close()

    assert lease["process_identities"] == [identity]
    assert helper.pid in lease["process_scope_acquisition"]["member_pids"]
    assert helper.poll() is not None
    helper.close()


def test_hybrid_vista_release_detects_descendant_appearing_after_stop(
    tmp_path,
    monkeypatch,
) -> None:
    from app.core import model_server
    from app.learn.hybrid.windows_process_scope import process_scope_name

    parent = {"pid": 4123, "create_time_ns": 100_000_000_000}
    raced_child = {"pid": 4999, "create_time_ns": 200_000_000_000}
    lease = {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": "vista-race-incarnation",
        "profile": {
            "profile_id": "vista-test",
            "provider_mode": "local_grounding",
            "port": 13240,
            "pid_file": str(tmp_path / "vista.pid"),
        },
        "process_identities": [parent],
        "process_scope_name": process_scope_name(_HYBRID_LINEAGE, "vista"),
        "process_scope_acquisition": {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": process_scope_name(_HYBRID_LINEAGE, "vista"),
            "member_pids": [parent["pid"]],
            "process_identities": [parent],
        },
    }
    from app.learn.hybrid import windows_process_scope
    monkeypatch.setattr(
        windows_process_scope,
        "observe_process_scope_cleanup",
        lambda name, **kwargs: {
            "contract_version": "hybrid_windows_process_scope_v1",
            "scope_name": name,
            "cleanup_status": "indeterminate",
            "member_pids_after": [raced_child["pid"]],
            "member_identities_after": [raced_child],
            "active_listeners_after": [],
        },
    )
    monkeypatch.setattr(
        model_server,
        "stop_model_server",
        lambda profile: {"stopped": True, "after": {"status": "unreachable"}},
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda identity: {
            "status": "exact_live" if identity == raced_child else "proven_absent",
            "identity": identity,
        },
    )
    monkeypatch.setattr(model_server, "_listening_pids_for_port", lambda port: [])

    inventory = model_server.release_hybrid_vista_model_lease(
        lease,
        lineage=_HYBRID_LINEAGE,
        predecessor_sha256=_PREDECESSOR_SHA256,
        provider_result_sha256=_PROVIDER_RESULT_SHA256,
    )

    assert inventory["release_status"] == "failed"
    assert inventory["orphan_descendant_pids"] == [raced_child["pid"]]
    assert inventory["helper_processes_after"] == [raced_child]


def test_hybrid_qwen_observer_rejects_synthetic_receipt_without_lifecycle_tombstone(
    monkeypatch,
) -> None:
    from app.core import model_server

    lease = _cleanup_lease()
    release_result = {
        "status": "released",
        "lease": lease,
        "shared_server_retained": False,
        "server_termination": "verified_exact_process_exited",
        "release": {"status": "proven_absent", "identity": lease["server_process_identity"]},
        "process_identity": lease["server_process_identity"],
    }
    receipt = model_server.build_qwen_cleanup_receipt(
        release_result=release_result,
        model_lease=lease,
    )
    monkeypatch.setattr(model_server, "_load_qwen_owner_tombstone", lambda owner: None)
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda identity: {"status": "proven_absent", "identity": identity},
    )
    monkeypatch.setattr(model_server, "_listening_pids_for_port", lambda port: [])
    monkeypatch.setattr(model_server, "qwen_model_lease_is_active", lambda value: False)

    inventory = model_server.observe_hybrid_qwen_cleanup(
        receipt,
        lineage=_HYBRID_LINEAGE,
        predecessor_sha256=_PREDECESSOR_SHA256,
        provider_result_sha256=_PROVIDER_RESULT_SHA256,
    )

    assert inventory["release_status"] == "failed"
    assert inventory["source_cleanup_evidence"]["lifecycle_verified"] is False


def test_hybrid_qwen_observer_requires_exact_server_owned_lifecycle_tombstone(
    monkeypatch,
) -> None:
    from app.core import model_server
    from app.learn.hybrid.windows_process_scope import process_scope_name

    lease = _cleanup_lease()
    scope_name = process_scope_name(_HYBRID_LINEAGE, "qwen")
    release_result = {
        "status": "released",
        "lease": lease,
        "shared_server_retained": False,
        "server_termination": "verified_exact_process_exited",
        "release": {"status": "proven_absent", "identity": lease["server_process_identity"]},
        "process_identity": lease["server_process_identity"],
        "hybrid_descendant_cleanup": {
            "status": "verified",
            "descendant_identities": [
                {"pid": 8124, "create_time_ns": 812_400_000_000}
            ],
            "probes": [
                {
                    "status": "proven_absent",
                    "identity": {"pid": 8124, "create_time_ns": 812_400_000_000},
                }
            ],
        },
        "hybrid_process_scope_name": scope_name,
        "hybrid_process_scope_acquisition": {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": scope_name,
            "member_pids": [lease["server_process_identity"]["pid"]],
            "server_process_identity": lease["server_process_identity"],
        },
        "hybrid_process_scope_cleanup": {
            "contract_version": "hybrid_windows_process_scope_v1",
            "scope_name": scope_name,
            "cleanup_status": "verified",
        },
    }
    receipt = model_server.build_qwen_cleanup_receipt(
        release_result=release_result,
        model_lease=lease,
    )
    tombstone = {
        "contract_version": "qwen_model_request_owner_receipt_v1",
        "status": "finalized",
        "owner_request_id": lease["owner_request_id"],
        "profile_id": lease["profile_id"],
        "lease_id": lease["lease_id"],
        "incarnation_id": lease["incarnation_id"],
        "server_termination": release_result["server_termination"],
        "release_result": release_result,
        "finalization_token": None,
    }
    monkeypatch.setattr(
        model_server, "_load_qwen_owner_tombstone", lambda owner: tombstone
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda identity: {"status": "proven_absent", "identity": identity},
    )
    monkeypatch.setattr(model_server, "_listening_pids_for_port", lambda port: [])
    monkeypatch.setattr(model_server, "qwen_model_lease_is_active", lambda value: False)

    inventory = model_server.observe_hybrid_qwen_cleanup(
        receipt,
        lineage=_HYBRID_LINEAGE,
        predecessor_sha256=_PREDECESSOR_SHA256,
        provider_result_sha256=_PROVIDER_RESULT_SHA256,
    )

    assert inventory["release_status"] == "verified"
    assert inventory["source_cleanup_evidence"]["lifecycle_verified"] is True


def test_hybrid_qwen_release_uses_nonempty_exact_job_membership(
    tmp_path,
    monkeypatch,
) -> None:
    from app.core import model_server
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    scope_name = process_scope_name(_HYBRID_LINEAGE, "qwen")
    scope = WindowsProcessScope(scope_name, create=True)
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    process = __import__("psutil").Process(helper.pid)
    identity = {
        "pid": helper.pid,
        "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
    }
    profile = {
        "profile_id": "qwen-job-test",
        "endpoint": "http://127.0.0.1:54321/v1/chat/completions",
        "pid_file": str(tmp_path / "qwen-job-test.pid"),
    }
    readiness = _server_readiness(
        started=True,
        pid=identity["pid"],
        created_ns=identity["create_time_ns"],
        base_url="http://127.0.0.1:54321/v1",
    )
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    try:
        lease = model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id="qwen-job-owner",
            readiness=readiness,
        )
        released = model_server._release_exact_qwen_lease(
            lease,
            reason="controlled-job-release",
        )
        receipt = model_server.build_qwen_cleanup_receipt(
            release_result=released,
            model_lease=lease,
        )
        inventory = model_server.observe_hybrid_qwen_cleanup(
            receipt,
            lineage=_HYBRID_LINEAGE,
            predecessor_sha256=_PREDECESSOR_SHA256,
            provider_result_sha256=_PROVIDER_RESULT_SHA256,
        )
    finally:
        scope.close()

    assert released["hybrid_process_scope_name"] == scope_name
    cleanup = released["hybrid_process_scope_cleanup"]
    assert cleanup["cleanup_status"] == "verified"
    assert helper.pid in released["hybrid_process_scope_acquisition"]["member_pids"]
    assert helper.poll() is not None
    assert inventory["release_status"] == "verified"
    helper.close()


def test_abnormal_qwen_owner_reconciliation_finalizes_exact_lease_and_tombstone(
    tmp_path,
    monkeypatch,
) -> None:
    from app.core import model_server
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    scope_name = process_scope_name(_HYBRID_LINEAGE, "qwen")
    scope = WindowsProcessScope(scope_name, create=True)
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    runtime_path = tmp_path / "qwen-runtime.json"
    profile = {
        "profile_id": "qwen-abnormal-test",
        "endpoint": "http://127.0.0.1:54322/v1/chat/completions",
        "pid_file": str(tmp_path / "qwen-abnormal.pid"),
    }
    readiness = _server_readiness(
        started=True,
        pid=helper.process_identity["pid"],
        created_ns=helper.process_identity["create_time_ns"],
        base_url="http://127.0.0.1:54322/v1",
    )
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("AGENT_GUI_HYBRID_LINEAGE_JSON", json.dumps(_HYBRID_LINEAGE))
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    try:
        lease = model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id="qwen-abnormal-owner",
            readiness=readiness,
        )
        evidence = model_server.reconcile_hybrid_qwen_owner(
            runtime_path,
            expected_lineage=_HYBRID_LINEAGE,
            expected_scope_name=scope_name,
        )
        assert evidence["status"] == "verified"
        assert evidence["owner_tombstone"]["content_sha256"] == (
            model_server.content_sha256(evidence["owner_tombstone"])
        )
        assert model_server.qwen_model_lease_is_active(lease) is False
        assert model_server._load_qwen_owner_tombstone(
            "qwen-abnormal-owner"
        )["lease_id"] == lease["lease_id"]
        assert helper.poll() is not None
        assert json.loads(runtime_path.read_text(encoding="utf-8"))["state"] == "released"
    finally:
        helper.close()
        scope.close()


def test_qwen_recovery_resolves_exact_lease_from_prelaunch_acquiring_owner(
    tmp_path,
    monkeypatch,
) -> None:
    from app.core import model_server
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    scope_name = process_scope_name(_HYBRID_LINEAGE, "qwen")
    scope = WindowsProcessScope(scope_name, create=True)
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    runtime_path = tmp_path / "qwen-acquiring.json"
    request_id = "qwen-acquiring-owner"
    runtime_path.write_text(
        json.dumps(
            seal_immutable({
                "contract_version": "hybrid_supervised_provider_runtime_v1",
                "state": "acquiring",
                "worker_id": "worker-acquiring",
                "model_request_id": request_id,
                "provider": "qwen",
                "lineage": _HYBRID_LINEAGE,
                "process_scope_name": scope_name,
                "provider_identity": None,
                "cleanup_observation": None,
            })
        ),
        encoding="utf-8",
    )
    profile = {
        "profile_id": "qwen-acquiring-test",
        "endpoint": "http://127.0.0.1:54324/v1/chat/completions",
        "pid_file": str(tmp_path / "qwen-acquiring.pid"),
    }
    readiness = _server_readiness(
        started=True,
        pid=helper.process_identity["pid"],
        created_ns=helper.process_identity["create_time_ns"],
        base_url="http://127.0.0.1:54324/v1",
    )
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    try:
        lease = model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id=request_id,
            readiness=readiness,
        )
        evidence = model_server.reconcile_hybrid_qwen_owner(
            runtime_path,
            expected_lineage=_HYBRID_LINEAGE,
            expected_scope_name=scope_name,
        )
        assert evidence["status"] == "verified"
        assert model_server.qwen_model_lease_is_active(lease) is False
        assert helper.poll() is not None
    finally:
        helper.close()
        scope.close()


def test_qwen_started_without_durable_lease_aborts_exact_job_and_restarts(
    tmp_path,
    monkeypatch,
) -> None:
    from pathlib import Path

    from app.core import model_server
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    lineage = {**_HYBRID_LINEAGE, "operation_id": "operation-qwen-no-lease"}
    scope_name = process_scope_name(lineage, "qwen")
    scope = WindowsProcessScope(scope_name, create=True)
    helper_holder = []
    request_id = "qwen-started-no-lease"
    runtime_path = tmp_path / "qwen-no-lease.json"
    runtime_path.write_text(
        json.dumps(seal_immutable({
            "contract_version": "hybrid_supervised_provider_runtime_v1",
            "state": "acquiring",
            "worker_id": "worker-no-lease",
            "model_request_id": request_id,
            "provider": "qwen",
            "lineage": lineage,
            "process_scope_name": scope_name,
            "provider_identity": None,
            "cleanup_observation": None,
        })),
        encoding="utf-8",
    )
    profile = {
        "profile_id": "qwen-no-lease",
        "endpoint": "http://127.0.0.1:54325/v1/chat/completions",
        "pid_file": str(tmp_path / "qwen-no-lease.pid"),
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen-leases")
    monkeypatch.setattr(model_server, "profile_for_stage", lambda *args: profile)
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("AGENT_GUI_HYBRID_LINEAGE_JSON", json.dumps(lineage))

    def start_then_lose_outer_worker(**kwargs):
        del kwargs
        helper = spawn_process_in_scope(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            scope_name=scope_name,
            cwd=tmp_path,
        )
        helper_holder.append(helper)
        Path(profile["pid_file"]).write_text(str(helper.pid), encoding="utf-8")
        raise RuntimeError("simulated-outer-worker-death-before-lease")

    monkeypatch.setattr(
        model_server, "_ensure_model_server_for_profile", start_then_lose_outer_worker
    )
    try:
        with pytest.raises(
            RuntimeError, match="simulated-outer-worker-death-before-lease"
        ):
            model_server.ensure_and_acquire_qwen_model_lease(
                stage="screen_understanding",
                profile_id=profile["profile_id"],
                request_id=request_id,
                wait_seconds=0,
            )
        helper = helper_holder[0]
        original_write = model_server._write_hybrid_qwen_runtime
        injected = False

        def crash_after_tombstone(path, document):
            nonlocal injected
            original_write(path, document)
            if (
                not injected
                and document.get("contract_version")
                == "hybrid_qwen_aborted_acquisition_tombstone_v1"
            ):
                injected = True
                raise RuntimeError("injected-after-qwen-abort-tombstone")

        monkeypatch.setattr(
            model_server, "_write_hybrid_qwen_runtime", crash_after_tombstone
        )
        with pytest.raises(RuntimeError, match="injected-after-qwen-abort-tombstone"):
            model_server.reconcile_hybrid_qwen_owner(
                runtime_path,
                expected_lineage=lineage,
                expected_scope_name=scope_name,
            )
        monkeypatch.setattr(
            model_server, "_write_hybrid_qwen_runtime", original_write
        )
        first = model_server.reconcile_hybrid_qwen_owner(
            runtime_path,
            expected_lineage=lineage,
            expected_scope_name=scope_name,
        )
        second = model_server.reconcile_hybrid_qwen_owner(
            runtime_path,
            expected_lineage=lineage,
            expected_scope_name=scope_name,
        )
        assert first["status"] == second["status"] == "verified"
        assert first["aborted_acquisition_tombstone"]["model_request_id"] == request_id
        assert first["aborted_acquisition_tombstone"] == second[
            "aborted_acquisition_tombstone"
        ]
        assert helper.poll() is not None
        assert Path(profile["pid_file"]).exists() is False
    finally:
        if helper_holder:
            helper_holder[0].close()
        scope.close()


@pytest.mark.parametrize("failure_stage", ["poll", "pid_write", "readiness", "sync"])
def test_scoped_model_start_failure_closes_process_log_and_job_membership(
    tmp_path,
    monkeypatch,
    failure_stage: str,
) -> None:
    from pathlib import Path

    import psutil
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope

    lineage = {**_HYBRID_LINEAGE, "operation_id": f"operation-start-{failure_stage}"}
    scope_name = windows_process_scope.process_scope_name(lineage, "qwen")
    scope = windows_process_scope.WindowsProcessScope(scope_name, create=True)
    real_spawn = windows_process_scope.spawn_process_in_scope
    spawned = []

    def controlled_spawn(command, **kwargs):
        child = real_spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            scope_name=kwargs["scope_name"],
            cwd=tmp_path,
            stdout=kwargs["stdout"],
            stderr=kwargs["stderr"],
        )
        spawned.append(child)
        if failure_stage == "poll":
            child.poll = lambda: (_ for _ in ()).throw(RuntimeError("injected-poll"))
        return child

    monkeypatch.setattr(windows_process_scope, "spawn_process_in_scope", controlled_spawn)
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    profile = {
        "profile_id": f"start-failure-{failure_stage}",
        "runtime": "transformers" if failure_stage in {"readiness", "sync"} else "llama",
        "port": 54326,
        "pid_file": str(tmp_path / f"{failure_stage}.pid"),
        "startup_exit_check_seconds": 0,
    }
    if failure_stage == "pid_write":
        monkeypatch.setattr(
            model_server,
            "_write_model_profile_pid",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("injected-pid-write")
            ),
        )
    elif failure_stage == "readiness":
        monkeypatch.setattr(
            model_server,
            "check_model_server",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("injected-readiness")
            ),
        )
    elif failure_stage == "sync":
        monkeypatch.setattr(
            model_server,
            "check_model_server",
            lambda *args, **kwargs: {"status": "running", "health": {"pid": 1}},
        )
        monkeypatch.setattr(
            model_server,
            "_sync_pid_file_from_health",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("injected-sync")
            ),
        )
    log_path = tmp_path / f"{failure_stage}.log"
    try:
        with pytest.raises(RuntimeError, match=f"injected-{failure_stage.replace('_', '-')}"):
            model_server._launch_model_server_process(
                profile=profile,
                log_path=log_path,
                command=["controlled-no-wrapper"],
            )
        assert len(spawned) == 1
        assert spawned[0]._closed is True
        assert psutil.pid_exists(spawned[0].pid) is False
        assert scope.pids() == []
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("closed")
    finally:
        for child in spawned:
            if not child._closed:
                child.close()
        scope.close()


def test_scoped_model_start_process_close_failure_still_closes_log_and_surfaces_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    from pathlib import Path

    from app.core import model_server
    from app.learn.hybrid import windows_process_scope

    lineage = {**_HYBRID_LINEAGE, "operation_id": "operation-start-close-failure"}
    scope_name = windows_process_scope.process_scope_name(lineage, "qwen")
    scope = windows_process_scope.WindowsProcessScope(scope_name, create=True)
    real_spawn = windows_process_scope.spawn_process_in_scope
    spawned = []

    def controlled_spawn(command, **kwargs):
        child = real_spawn(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            scope_name=kwargs["scope_name"],
            cwd=tmp_path,
            stdout=kwargs["stdout"],
            stderr=kwargs["stderr"],
        )
        spawned.append(child)
        child.poll = lambda: (_ for _ in ()).throw(RuntimeError("injected-poll"))
        real_close = child.close

        def close_then_throw():
            real_close()
            raise RuntimeError("injected-process-handle-close")

        child.close = close_then_throw
        return child

    log_path = tmp_path / "close-failure.log"
    real_path_open = Path.open
    tracking = {}

    class TrackingLog:
        def __init__(self, handle) -> None:
            self.handle = handle
            self.close_called = False

        def fileno(self):
            return self.handle.fileno()

        def close(self):
            self.close_called = True
            self.handle.close()

        def __getattr__(self, name):
            return getattr(self.handle, name)

    def tracked_open(path, *args, **kwargs):
        handle = real_path_open(path, *args, **kwargs)
        if Path(path) == log_path:
            wrapper = TrackingLog(handle)
            tracking["log"] = wrapper
            return wrapper
        return handle

    monkeypatch.setattr(windows_process_scope, "spawn_process_in_scope", controlled_spawn)
    monkeypatch.setattr(Path, "open", tracked_open)
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    profile = {
        "profile_id": "start-close-failure",
        "runtime": "llama",
        "port": 54327,
        "pid_file": str(tmp_path / "close-failure.pid"),
        "startup_exit_check_seconds": 0,
    }
    try:
        with pytest.raises(
            model_server.HybridModelLaunchCleanupError,
            match="Hybrid model launch handle cleanup is indeterminate",
        ) as captured:
            model_server._launch_model_server_process(
                profile=profile,
                log_path=log_path,
                command=["controlled-no-wrapper"],
            )
        evidence = captured.value.cleanup_evidence
        assert evidence["process_handle_close"] == "failed"
        assert evidence["log_handle_close"] == "closed"
        assert evidence["scope_cleanup_evidence"]["cleanup_status"] == "verified"
        assert tracking["log"].close_called is True
        assert spawned[0]._closed is True
    finally:
        if spawned and not spawned[0]._closed:
            spawned[0].close()
        if not scope._closed:
            scope.close()


def test_stop_model_server_honors_real_wrapper_test_sentinel(monkeypatch) -> None:
    from app.core import model_server

    monkeypatch.setenv("AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER", "1")
    with pytest.raises(RuntimeError, match="wrapper disabled"):
        model_server.stop_model_server({"profile_id": "must-not-run"})
import psutil

from app.core import model_server
from app.learn.recognition.uei.canonical import seal_immutable

_PRODUCTION_QWEN_SOCKET_ATTESTER = model_server._attest_exact_qwen_socket_owner


@pytest.fixture(autouse=True)
def _use_controlled_qwen_socket_attestation(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER", "1")
    production_observer = model_server._observe_qwen_server_binding

    def observe(profile, readiness):
        observed = (
            readiness.get("after")
            if isinstance(readiness.get("after"), dict)
            else readiness.get("before")
        )
        observed = observed if isinstance(observed, dict) else {}
        identity = observed.get("server_process_identity")
        server_socket = observed.get("server_socket")
        resolved = model_server._resolved_qwen_endpoint_addresses(profile, observed)
        if (
            model_server._valid_process_identity(identity)
            and model_server._valid_qwen_server_socket(server_socket)
            and (str(server_socket["host"]), int(server_socket["port"])) in resolved
        ):
            return {
                "server_process_identity": deepcopy(identity),
                "server_socket": deepcopy(server_socket),
            }
        return production_observer(profile, readiness)

    monkeypatch.setattr(model_server, "_observe_qwen_server_binding", observe)
    monkeypatch.setattr(
        model_server,
        "_attest_exact_qwen_socket_owner",
        lambda server_socket, process_identity: (
            model_server._current_process_identity(process_identity["pid"])
            == process_identity
        ),
        raising=False,
    )


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        raw = json.dumps(self._payload).encode("utf-8")
        return raw if size < 0 else raw[:size]


def _server_readiness(
    *,
    started: bool,
    pid: int = 9101,
    created_ns: int = 123456789,
    model_id: str = "qwen",
    base_url: str = "http://127.0.0.1:13240/v1",
) -> dict:
    parsed_base_url = urlsplit(base_url)
    observation = {
        "status": "running",
        "base_url": base_url,
        "model_id": model_id,
        "server_process_identity": {
            "pid": pid,
            "create_time_ns": created_ns,
        },
        "server_socket": {
            "host": "127.0.0.1" if parsed_base_url.hostname == "localhost" else parsed_base_url.hostname,
            "port": parsed_base_url.port,
        },
    }
    return {"started": started, "after" if started else "before": observation}


def _valid_binding_artifacts() -> tuple[dict, dict]:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from test_learn_hybrid_contracts import inventory_fixture

    inventory = seal_immutable(inventory_fixture())
    candidate_id = inventory["candidates"][0]["candidate_id"]
    parsed = parse_qwen_candidate_bindings(
        {
            "bindings": [{
                "candidate_id": candidate_id,
                "role": "button",
                "label": "申请职位",
                "description": "打开申请流程",
                "semantic_confidence": 0.94,
                "task_relevance": 0.88,
                "relation": "primary_action",
                "ambiguity": None,
            }],
            "ambiguity_sets": [],
            "orphan_semantics": [],
        },
        inventory,
        context_ref={"id": "hybrid-context/test", "content_sha256": "56" * 32},
    )
    return inventory, seal_immutable(parsed)


def _current_process_readiness(*, model_id: str) -> dict:
    process = psutil.Process(os.getpid())
    return _server_readiness(
        started=False,
        pid=process.pid,
        created_ns=int(round(process.create_time() * 1_000_000_000)),
        model_id=model_id,
    )


def test_cancel_model_request_verifies_vista_request_termination(monkeypatch) -> None:
    requested: list[dict] = []
    profile = {
        "profile_id": "vista",
        "role": ["grounding", "locate"],
        "endpoint": "http://127.0.0.1:13244/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13244/v1/cancel",
    }
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [profile])

    def fake_urlopen(request, timeout):
        requested.append(
            {
                "url": request.full_url,
                "body": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return _FakeResponse(
            {
                "contract_version": "model_request_cancel_response_v1",
                "status": "cancellation_acknowledged",
                "request_id": "learn-worker-123",
            }
        )

    monkeypatch.setattr(model_server.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda profile, timeout=1.0: {
            "status": "running",
            "health": {"status": "ok", "active_request": None},
        },
    )

    result = model_server.cancel_model_request(
        request_id="learn-worker-123",
        task_kind="vision_locate_target",
        payload={"provider_mode": "local_grounding"},
    )

    assert requested == [
        {
            "url": "http://127.0.0.1:13244/v1/cancel",
            "body": {"request_id": "learn-worker-123"},
            "timeout": 1.0,
        }
    ]
    assert result["status"] == "terminated"
    assert result["model_service_compute_termination"] == "terminated"
    assert result["provider_results"][0]["profile_id"] == "vista"


def test_cancel_model_request_reports_unsupported_without_guessing(monkeypatch) -> None:
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [])

    result = model_server.cancel_model_request(
        request_id="learn-worker-456",
        task_kind="unknown_model_task",
        payload={},
    )

    assert result["status"] == "not_supported"
    assert result["model_service_compute_termination"] == "not_supported"
    assert result["provider_results"] == []


@pytest.mark.parametrize(
    "task_kind",
    [
        "panel_learning_recognition_trial",
        "panel_learning_two_stage_understanding",
        "panel_learning_model_review_repair",
        "panel_learning_hybrid_qwen_binding",
        "vision_observe_screen",
    ],
)
def test_managed_qwen_cancel_before_lease_publication_is_request_not_active(
    tmp_path,
    monkeypatch,
    task_kind,
) -> None:
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    monkeypatch.setattr(
        model_server,
        "_request_cancel_profiles",
        lambda **kwargs: pytest.fail("managed Qwen cancellation guessed a profile before ownership publication"),
    )

    result = model_server.cancel_model_request(
        request_id=f"pre-publish-{task_kind}",
        task_kind=task_kind,
        payload={},
    )

    assert result["status"] == "request_not_active"
    assert result["model_service_compute_termination"] == "request_not_active"


def test_calibration_sequence_cancellation_uses_nested_locate_payload(
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "vista",
        "role": ["grounding", "locate"],
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13244/v1/cancel",
    }
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [profile])

    profiles = model_server._request_cancel_profiles(
        task_kind="panel_learning_calibration_sequence",
        payload={
            "contract_version": "learning_calibration_sequence_request_v1",
            "locate_payload": {"provider_mode": "local_grounding"},
        },
    )

    assert profiles == [profile]


def test_qwen_cancellation_uses_exact_request_endpoint_and_retains_other_operation(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "role": ["understanding", "learning"],
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13240/v1/cancel",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease_a = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="learn-qwen-a",
        readiness=_server_readiness(started=True),
    )
    lease_b = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="learn-qwen-b",
        readiness=_server_readiness(started=False),
    )
    changed_profile = {**profile, "request_cancel_endpoint": "http://127.0.0.1:13240/v1/should-not-use"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage, profile_id=None: changed_profile)
    requested: list[dict] = []

    def fake_urlopen(request, timeout):
        requested.append({"url": request.full_url, "body": json.loads(request.data), "timeout": timeout})
        return _FakeResponse({
            "contract_version": "model_request_cancel_response_v1",
            "status": "cancellation_acknowledged",
            "request_id": "learn-qwen-a",
        })

    monkeypatch.setattr(model_server.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {
        "status": "running",
        "base_url": "http://127.0.0.1:13240/v1",
        "model_id": "qwen",
        "health": {"status": "ok", "active_request": {"request_id": "learn-qwen-b"}},
    })
    monkeypatch.setattr(model_server, "stop_model_server", lambda selected: pytest.fail("shared server stopped"))

    result = model_server.cancel_model_request(
        request_id="learn-qwen-a",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )

    assert result["status"] == "terminated"
    assert requested == [{
        "url": profile["request_cancel_endpoint"],
        "body": {"request_id": "learn-qwen-a"},
        "timeout": 1.0,
    }]
    assert result["provider_results"][0]["lease"]["lease_id"] == lease_a["lease_id"]
    assert result["provider_results"][0]["shared_server_retained"] is True
    assert model_server.qwen_model_lease_is_active(lease_b) is True
    assert model_server.qwen_model_lease_is_active(lease_a) is False


@pytest.mark.parametrize(
    "second_profile,second_readiness",
    [
        (
            {"profile_id": "qwen", "endpoint": "http://127.0.0.1:14000/v1/chat/completions"},
            _server_readiness(started=False, base_url="http://127.0.0.1:14000/v1"),
        ),
        (
            {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions", "model_name": "other"},
            _server_readiness(started=False, model_id="other"),
        ),
        (
            {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"},
            _server_readiness(started=False, pid=9202, created_ns=987654321),
        ),
    ],
)
def test_same_profile_id_rejects_incompatible_server_incarnation(
    tmp_path,
    monkeypatch,
    second_profile,
    second_readiness,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True),
    )

    with pytest.raises(ValueError, match="server incarnation mismatch"):
        model_server.acquire_qwen_model_lease(
            profile=second_profile,
            request_id="request-b",
            readiness=second_readiness,
        )


def test_different_profile_id_cannot_partition_same_qwen_listener_process(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    first = {
        "profile_id": "qwen-before-rename",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    renamed = {
        **first,
        "profile_id": "qwen-after-rename",
        "endpoint": "http://localhost:13240/v1/chat/completions",
    }
    first_readiness = _server_readiness(
        started=True,
        pid=9101,
        created_ns=111,
        base_url="http://127.0.0.1:13240/v1",
    )
    renamed_readiness = _server_readiness(
        started=False,
        pid=9101,
        created_ns=111,
        base_url="http://localhost:13240/v1",
    )
    first_lease = model_server.acquire_qwen_model_lease(
        profile=first,
        request_id="request-a",
        readiness=first_readiness,
    )
    second_lease = model_server.acquire_qwen_model_lease(
        profile=renamed,
        request_id="request-b",
        readiness=renamed_readiness,
    )

    assert second_lease["incarnation_id"] == first_lease["incarnation_id"]
    with model_server._qwen_lease_lock():
        states = model_server._load_all_qwen_lease_states()
    assert len(states) == 1
    assert {item["owner_request_id"] for item in states[0]["leases"]} == {
        "request-a",
        "request-b",
    }


def test_qwen_process_observation_binds_service_pid_to_resolved_endpoint_socket(
    monkeypatch,
) -> None:
    class Address:
        def __init__(self, ip: str, port: int) -> None:
            self.ip = ip
            self.port = port

    class Connection:
        def __init__(self, ip: str, port: int, pid: int) -> None:
            self.laddr = Address(ip, port)
            self.status = psutil.CONN_LISTEN
            self.pid = pid

    monkeypatch.setattr(
        model_server.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 13240))
        ],
    )
    monkeypatch.setattr(
        model_server.psutil,
        "net_connections",
        lambda kind: [
            Connection("0.0.0.0", 13240, 7001),
            Connection("127.0.0.1", 13240, 7002),
        ],
    )
    monkeypatch.setattr(
        model_server,
        "_current_process_identity",
        lambda pid: {"pid": int(pid), "create_time_ns": int(pid) * 1000},
    )

    observed = model_server._observe_qwen_server_process(
        {
            "profile_id": "qwen",
            "endpoint": "http://localhost:13240/v1/chat/completions",
        },
        {"start": {"service_pid": 7002, "pid": 7001}},
    )

    assert observed == {"pid": 7002, "create_time_ns": 7002000}


def test_qwen_process_observation_fails_closed_for_ambiguous_endpoint_owners(
    monkeypatch,
) -> None:
    class Address:
        ip = "127.0.0.1"
        port = 13240

    class Connection:
        def __init__(self, pid: int) -> None:
            self.laddr = Address()
            self.status = psutil.CONN_LISTEN
            self.pid = pid

    monkeypatch.setattr(
        model_server.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 13240))
        ],
    )
    monkeypatch.setattr(
        model_server.psutil,
        "net_connections",
        lambda kind: [Connection(7001), Connection(7002)],
    )
    monkeypatch.setattr(
        model_server,
        "_current_process_identity",
        lambda pid: {"pid": int(pid), "create_time_ns": int(pid) * 1000},
    )

    assert model_server._observe_qwen_server_process(
        {
            "profile_id": "qwen",
            "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        },
        {},
    ) is None


def test_qwen_process_observation_rejects_readiness_pid_not_owning_socket(
    monkeypatch,
) -> None:
    class Address:
        ip = "127.0.0.1"
        port = 13240

    class Connection:
        laddr = Address()
        status = psutil.CONN_LISTEN
        pid = 7002

    monkeypatch.setattr(
        model_server.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 13240))
        ],
    )
    monkeypatch.setattr(
        model_server.psutil,
        "net_connections",
        lambda kind: [Connection()],
    )
    monkeypatch.setattr(
        model_server,
        "_current_process_identity",
        lambda pid: {"pid": int(pid), "create_time_ns": int(pid) * 1000},
    )

    assert model_server._observe_qwen_server_process(
        {
            "profile_id": "qwen",
            "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        },
        {
            "before": {
                "status": "running",
                "base_url": "http://127.0.0.1:13240/v1",
                "server_process_identity": {"pid": 7001, "create_time_ns": 7001000},
            }
        },
    ) is None


def test_qwen_cancellation_finds_lease_by_owner_when_current_profile_id_changes(
    tmp_path,
    monkeypatch,
) -> None:
    acquired = {
        "profile_id": "qwen-acquired",
        "role": ["understanding"],
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13240/v1/cancel",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=acquired,
        request_id="owner-request",
        readiness=_server_readiness(started=False),
    )
    monkeypatch.setattr(model_server, "profile_for_stage", lambda *args, **kwargs: {
        **acquired,
        "profile_id": "qwen-current-other",
        "request_cancel_endpoint": "http://127.0.0.1:13240/v1/wrong",
    })
    requested: list[str] = []
    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda request, timeout: requested.append(request.full_url) or _FakeResponse({
        "status": "request_not_active",
        "request_id": "owner-request",
    }))

    result = model_server.cancel_model_request(
        request_id="owner-request",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )

    assert requested == [acquired["request_cancel_endpoint"]]
    assert result["provider_results"][0]["profile_id"] == "qwen-acquired"
    assert model_server.qwen_model_lease_is_active(lease) is False


def test_no_endpoint_shared_cancel_stays_owned_pending(
    tmp_path,
    monkeypatch,
) -> None:
    profile = deepcopy(model_server.profile_for_stage("understanding"))
    assert profile["profile_id"] == "qwen3_vl_8b_q4_k_m"
    assert not profile.get("request_cancel_endpoint")
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease_a = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True, model_id=profile["model_name"]),
    )
    lease_b = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-b",
        readiness=_server_readiness(started=False, model_id=profile["model_name"]),
    )
    model_server._mark_qwen_model_request_in_flight(lease_a)
    monkeypatch.setattr(model_server, "stop_model_server", lambda selected: pytest.fail("shared server stopped"))

    result = model_server.cancel_model_request(
        request_id="request-a",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )

    assert result["status"] == "cancellation_acknowledged_pending"
    assert result["model_service_compute_termination"] == "cancellation_acknowledged_pending"
    provider = result["provider_results"][0]
    assert provider["pending_reason"] == "request_cancel_endpoint_unavailable"
    assert provider["capability_blocker"] == "request_cancel_endpoint_unavailable"
    assert provider["reconciliation_trigger"] == "worker_http_completion_or_explicit_retry"
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease_a["incarnation_id"])
        exact = model_server._find_exact_lease(state, lease_a)
    assert exact["pending_reason"] == "request_cancel_endpoint_unavailable"
    assert exact["capability_blocker"] == "request_cancel_endpoint_unavailable"
    assert exact["reconciliation_trigger"] == "worker_http_completion_or_explicit_retry"
    assert model_server.qwen_model_lease_is_active(lease_a) is True
    assert model_server.qwen_model_lease_is_active(lease_b) is True


def test_qwen_finalization_token_is_single_owner_during_release_cancel_race(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="release-cancel-owner",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    entered = Event()
    finish = Event()
    terminations: list[dict] = []

    def terminate(expected):
        terminations.append(expected)
        entered.set()
        finish.wait(timeout=2.0)
        return {"status": "proven_absent", "method": "terminate_wait"}

    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(model_server, "_terminate_exact_qwen_server_process", terminate)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    released: dict[str, object] = {}
    worker = Thread(
        target=lambda: released.update(
            model_server.release_qwen_model_server(
                sealed_artifact=artifact,
                omni_inventory=inventory,
                model_lease=lease,
            )
        )
    )
    worker.start()
    assert entered.wait(timeout=1.0) is True

    concurrent = model_server.cancel_model_request(
        request_id="release-cancel-owner",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert concurrent["status"] == "cancellation_acknowledged_pending"
    assert concurrent["provider_results"][0]["server_termination"] == "finalization_pending"
    assert len(terminations) == 1

    finish.set()
    worker.join(timeout=2.0)
    assert worker.is_alive() is False
    assert released["server_termination"] == "verified_exact_process_exited"
    assert len(terminations) == 1
    retry = model_server.cancel_model_request(
        request_id="release-cancel-owner",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert retry["status"] == "request_not_active"
    assert retry["provider_results"][0]["owner_receipt"]["status"] == "finalized"


def test_existing_qwen_finalization_token_is_immutable_and_never_stops_twice(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="existing-token-owner",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        state["revision"] += 1
        state["finalization"] = {
            "token": "immutable-token",
            "revision": state["revision"],
            "lease_id": lease["lease_id"],
            "phase": "stop_pending",
            "reason": "completed",
        }
        model_server._write_qwen_lease_state(state)
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: pytest.fail("second finalizer attempted exact termination"),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )

    pending = model_server._release_exact_qwen_lease(lease, reason="cancelled")

    assert pending["status"] == "cancellation_acknowledged_pending"
    assert pending["finalization"]["token"] == "immutable-token"
    with model_server._qwen_lease_lock():
        persisted = model_server._load_qwen_lease_state(lease["incarnation_id"])
    assert persisted["finalization"]["token"] == "immutable-token"


def test_qwen_failure_reconciliation_persists_timeout_pending_and_removes_completed_parser_lease(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    timeout_lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="timeout-request",
        readiness=_server_readiness(started=True),
    )
    parser_lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="parser-request",
        readiness=_server_readiness(started=False),
    )
    model_server._mark_qwen_model_request_in_flight(timeout_lease)

    pending = model_server.reconcile_qwen_model_lease_failure(
        model_lease=timeout_lease,
        compute_completed=False,
        reason="timeout",
    )
    assert pending["status"] == "cancellation_acknowledged_pending"
    assert model_server.qwen_model_lease_is_active(timeout_lease) is True

    completed = model_server.reconcile_qwen_model_lease_failure(
        model_lease=parser_lease,
        compute_completed=True,
        reason="parser_rejection",
    )
    assert completed["status"] == "released"
    assert completed["shared_server_retained"] is True
    assert model_server.qwen_model_lease_is_active(parser_lease) is False
    assert model_server.qwen_model_lease_is_active(timeout_lease) is True


def test_qwen_pending_cancel_then_real_finalizer_retry_uses_owner_tombstone(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    pending_lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="pending-owner",
        readiness=_server_readiness(started=True),
    )
    retained = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="retained-owner",
        readiness=_server_readiness(started=False),
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: pytest.fail("shared process must not be terminated"),
    )
    model_server._mark_qwen_model_request_in_flight(pending_lease)

    first = model_server.cancel_model_request(
        request_id="pending-owner",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert first["status"] == "cancellation_acknowledged_pending"

    model_server._mark_qwen_model_compute_complete(pending_lease)

    retry = model_server.cancel_model_request(
        request_id="pending-owner",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert retry["status"] == "request_not_active"
    assert retry["model_service_compute_termination"] == "request_not_active"
    assert retry["provider_results"][0]["owner_receipt"]["status"] == "finalized"
    assert model_server.qwen_model_lease_is_active(pending_lease) is False
    assert model_server.qwen_model_lease_is_active(retained) is True


def test_qwen_timeout_finalizer_stops_only_sole_exact_owned_incarnation(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="timeout-request",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: {"status": "proven_absent", "identity": None},
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {"status": "unreachable"})

    reconciled = model_server.reconcile_qwen_model_lease_failure(
        model_lease=lease,
        compute_completed=False,
        reason="timeout",
    )
    assert reconciled["server_termination"] == "verified_exact_process_exited"
    assert model_server.qwen_model_lease_is_active(lease) is False


def test_invalid_http_json_marks_compute_complete_before_failure_reconciliation(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    failed = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="invalid-json-request",
        readiness=_server_readiness(started=True),
    )
    active = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="active-request",
        readiness=_server_readiness(started=False),
    )
    monkeypatch.setattr(model_server, "_current_process_identity", lambda pid: {
        "pid": 9101,
        "create_time_ns": 123456789,
    })

    class InvalidResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size=-1):
            return b"not-json"

    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda *args, **kwargs: InvalidResponse())
    with pytest.raises(ValueError):
        model_server.run_qwen_binding_model(
            request={"candidates": []},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            model_lease=failed,
        )

    reconciled = model_server.reconcile_qwen_model_lease_failure(
        model_lease=failed,
        compute_completed=False,
        reason="invalid_json",
    )
    assert reconciled["status"] == "released"
    assert model_server.qwen_model_lease_is_active(failed) is False
    assert model_server.qwen_model_lease_is_active(active) is True


def test_qwen_release_refcounts_and_stops_only_after_last_runtime_owned_lease(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    stopped: list[dict] = []
    profile = {"profile_id": "qwen3_vl_8b_q4_k_m", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease_a = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True),
    )
    lease_b = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-b",
        readiness=_server_readiness(started=False),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: stopped.append(expected)
        or {"status": "proven_absent", "reason": "terminate_wait"},
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {"status": "unreachable"})

    first = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=lease_a,
    )
    assert first["status"] == "released"
    assert first["shared_server_retained"] is True
    assert stopped == []
    assert model_server.qwen_model_lease_is_active(lease_b) is True

    second = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=lease_b,
    )
    assert second["status"] == "released"
    assert second["server_termination"] == "verified_exact_process_exited"
    assert stopped == [lease_b["server_process_identity"]]


def test_qwen_last_request_cancel_stops_owned_server_then_new_external_lease_is_retained(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "role": ["understanding"],
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13240/v1/cancel",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage, profile_id=None: profile)
    first = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="owned-request",
        readiness=_server_readiness(started=True),
    )
    stopped: list[dict] = []
    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda request, timeout: _FakeResponse({
        "status": "cancellation_acknowledged",
        "request_id": "owned-request",
    }))
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: stopped.append(expected)
        or {"status": "proven_absent", "reason": "terminate_wait"},
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {
        "status": "unreachable",
        "health": {"active_request": None},
    })

    cancelled = model_server.cancel_model_request(
        request_id="owned-request",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert cancelled["status"] == "terminated"
    assert cancelled["provider_results"][0]["server_termination"] == "verified_exact_process_exited"
    assert stopped == [first["server_process_identity"]]
    assert model_server.qwen_model_lease_is_active(first) is False

    external = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="external-request",
        readiness=_server_readiness(started=False),
    )
    stopped.clear()
    released = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=external,
    )
    assert released["server_termination"] == "not_owned"
    assert stopped == []


def test_qwen_release_rejects_forged_or_wrong_capture_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen3_vl_8b_q4_k_m", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=False),
    )

    with pytest.raises(ValueError, match="sealed Qwen binding"):
        model_server.release_qwen_model_server(
            sealed_artifact=seal_immutable({"contract_version": "hybrid_qwen_bindings_v1"}),
            omni_inventory=inventory,
            model_lease=lease,
        )

    with pytest.raises(ValueError, match="exact Qwen model lease"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=inventory,
            model_lease={
                "lease_id": lease["lease_id"],
                "incarnation_id": lease["incarnation_id"],
            },
        )

    omitted = seal_immutable({
        **{key: deepcopy(value) for key, value in artifact.items() if key != "content_sha256"},
        "bindings": [],
    })
    with pytest.raises(ValueError, match="coverage|sealed Qwen binding"):
        model_server.release_qwen_model_server(
            sealed_artifact=omitted,
            omni_inventory=inventory,
            model_lease=lease,
        )

    wrong_inventory = seal_immutable({
        **{key: value for key, value in inventory.items() if key != "content_sha256"},
        "capture_identity": {**inventory["capture_identity"], "screenshot_sha256": "0" * 64},
    })
    with pytest.raises(ValueError, match="capture|screenshot|sealed Qwen binding"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=wrong_inventory,
            model_lease=lease,
        )


def test_qwen_stop_script_success_but_server_running_is_not_released(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen3_vl_8b_q4_k_m", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {"status": "running", "model_id": "qwen"})

    with pytest.raises(RuntimeError, match="still running"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=inventory,
            model_lease=lease,
        )
    assert model_server.qwen_model_lease_is_active(lease) is True


def test_qwen_release_never_stops_replacement_process(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {
            "status": "proven_absent",
            "identity": {"pid": 9101, "create_time_ns": 222},
            "reason": "pid_reused",
        },
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: pytest.fail("replacement stopped"),
    )

    with pytest.raises(RuntimeError, match="server incarnation ownership changed"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=inventory,
            model_lease=lease,
        )
    assert model_server.qwen_model_lease_is_active(lease) is True


def test_qwen_post_stop_access_denied_remains_owned_pending(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="access-denied-owner",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )

    class AccessDeniedProcess:
        pid = 9101

        def is_running(self):
            return True

        def status(self):
            return "running"

        def create_time(self):
            return 111 / 1_000_000_000

        def children(self, recursive=True):
            del recursive
            return []

        def terminate(self):
            return None

        def wait(self, timeout):
            del timeout
            raise psutil.AccessDenied(pid=9101)

    monkeypatch.setattr(model_server.psutil, "Process", lambda pid: AccessDeniedProcess())

    with pytest.raises(RuntimeError, match="process exit is unobservable"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=inventory,
            model_lease=lease,
        )
    assert model_server.qwen_model_lease_is_active(lease) is True
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
    assert state["finalization"]["phase"] == "owned_pending"
    assert state["finalization"]["failure_reason"] == "process_exit_unobservable"


def test_exact_qwen_termination_never_kills_pid_replacement(monkeypatch) -> None:
    expected = {"pid": 9101, "create_time_ns": 111}
    killed: list[int] = []

    class OriginalProcess:
        pid = 9101

        def is_running(self):
            return True

        def status(self):
            return "running"

        def create_time(self):
            return 111 / 1_000_000_000

        def terminate(self):
            return None

        def wait(self, timeout):
            del timeout
            raise psutil.TimeoutExpired(seconds=0.1, pid=9101)

        def kill(self):
            killed.append(self.pid)

    probes = iter([
        {"status": "exact_live", "identity": expected},
        {
            "status": "proven_absent",
            "identity": {"pid": 9101, "create_time_ns": 222},
            "reason": "pid_reused",
        },
    ])
    monkeypatch.setattr(model_server.psutil, "Process", lambda pid: OriginalProcess())
    monkeypatch.setattr(model_server, "_probe_exact_qwen_process", lambda identity: next(probes))

    result = model_server._terminate_exact_qwen_server_process(expected)

    assert result["status"] == "proven_absent"
    assert result["reason"] == "pid_reused"
    assert killed == []


def test_qwen_global_acquisition_transaction_serializes_first_start_and_publication(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    first_started = Event()
    release_first = Event()
    active_calls = 0
    max_active_calls = 0
    call_lock = __import__("threading").Lock()
    ensure_calls = 0

    def ensure(**kwargs):
        nonlocal active_calls, max_active_calls, ensure_calls
        del kwargs
        with call_lock:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            ensure_calls += 1
            call_number = ensure_calls
        if call_number == 1:
            first_started.set()
            release_first.wait(timeout=2.0)
        with call_lock:
            active_calls -= 1
        return {
            **_server_readiness(
                started=call_number == 1,
                pid=9101,
                created_ns=111,
            ),
            "profile": model_server._public_profile(profile),
        }

    monkeypatch.setattr(model_server, "profile_for_stage", lambda *args, **kwargs: deepcopy(profile))
    monkeypatch.setattr(model_server, "_ensure_model_server_for_profile", ensure)
    leases: list[dict] = []

    def acquire(owner):
        leases.append(model_server.ensure_and_acquire_qwen_model_lease(
            stage="understanding",
            profile_id=None,
            request_id=owner,
            wait_seconds=1.0,
        ))

    one = Thread(target=acquire, args=("owner-a",))
    two = Thread(target=acquire, args=("owner-b",))
    one.start()
    assert first_started.wait(timeout=1.0) is True
    two.start()
    time.sleep(0.05)
    assert ensure_calls == 1
    release_first.set()
    one.join(timeout=2.0)
    two.join(timeout=2.0)

    assert max_active_calls == 1
    assert len(leases) == 2
    assert leases[0]["incarnation_id"] == leases[1]["incarnation_id"]


def test_qwen_acquisition_loads_one_profile_snapshot_inside_global_transaction(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    loaded = []
    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "model_name": "qwen",
    }

    def load_profile(stage, profile_id=None):
        loaded.append((stage, profile_id))
        return deepcopy(profile)

    def ensure_snapshot(*, profile, stage, wait_until_ready, wait_seconds):
        assert profile == {
            "profile_id": "qwen",
            "provider_mode": "local_understanding",
            "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
            "model_name": "qwen",
        }
        assert stage == "understanding"
        assert wait_until_ready is True
        assert wait_seconds == 3.0
        return {
            **_server_readiness(started=False, model_id="qwen"),
            "profile": model_server._public_profile(profile),
        }

    monkeypatch.setattr(model_server, "profile_for_stage", load_profile)
    monkeypatch.setattr(model_server, "_ensure_model_server_for_profile", ensure_snapshot)

    lease = model_server.ensure_and_acquire_qwen_model_lease(
        stage="understanding",
        profile_id=None,
        request_id="atomic-profile-owner",
        wait_seconds=3.0,
    )

    assert loaded == [("understanding", None)]
    assert lease["profile_sha256"] == model_server.content_sha256(
        model_server._public_profile(profile)
    )


@pytest.mark.parametrize(
    "profile,readiness",
    [
        (
            {
                "profile_id": "qwen",
                "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
                "model_name": "qwen-expected",
            },
            _server_readiness(started=False, model_id="qwen-other"),
        ),
        (
            {
                "profile_id": "qwen",
                "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
                "model_name": "qwen",
            },
            _server_readiness(
                started=False,
                model_id="qwen",
                base_url="http://127.0.0.1:14000/v1",
            ),
        ),
    ],
)
def test_qwen_acquisition_rejects_readiness_model_or_endpoint_mismatch(
    tmp_path,
    monkeypatch,
    profile,
    readiness,
) -> None:
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="readiness .* does not match"):
        model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id="mismatched-readiness",
            readiness=readiness,
        )


@pytest.mark.parametrize("failure_stage", ["tombstone", "delete"])
def test_qwen_termination_receipt_cleanup_is_retryable_without_second_stop(
    tmp_path,
    monkeypatch,
    failure_stage,
) -> None:
    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id=f"recover-{failure_stage}",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    stop_calls = []
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )

    def terminate(expected):
        stop_calls.append(deepcopy(expected))
        return {"status": "proven_absent", "identity": None, "reason": "terminated"}

    monkeypatch.setattr(model_server, "_terminate_exact_qwen_server_process", terminate)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected: {"status": "unreachable"},
    )
    target_name = (
        "_write_qwen_owner_tombstone"
        if failure_stage == "tombstone"
        else "_delete_qwen_lease_state"
    )
    original = getattr(model_server, target_name)
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError(f"injected {failure_stage} failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(model_server, target_name, fail_once)

    with pytest.raises(OSError, match=f"injected {failure_stage} failure"):
        model_server._release_exact_qwen_lease(lease, reason="completed")

    with model_server._qwen_lease_lock():
        persisted = model_server._load_qwen_lease_state(lease["incarnation_id"])
    assert persisted["finalization"]["phase"] == "termination_proven"

    retried = model_server._release_exact_qwen_lease(lease, reason="completed")

    assert retried["status"] == "released"
    assert stop_calls == [{"pid": 9101, "create_time_ns": 111}]
    assert model_server.qwen_model_lease_is_active(lease) is False


def test_managed_local_provider_timeout_preserves_request_in_flight(
    tmp_path,
    monkeypatch,
) -> None:
    from PIL import Image
    from app.vision import local_provider

    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "model_name": "qwen-controlled",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="managed-timeout-owner",
        readiness=_current_process_readiness(model_id="qwen-controlled"),
    )
    model_server._mark_qwen_model_request_in_flight(lease)
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    monkeypatch.setattr(
        local_provider,
        "urlopen",
        lambda request, timeout: (_ for _ in ()).throw(TimeoutError("controlled timeout")),
    )
    provider = local_provider.LocalVisionProvider(
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="mutable-wrong-model",
        timeout_seconds=0.01,
        managed_model_lease=lease,
    )

    with pytest.raises(TimeoutError, match="controlled timeout"):
        provider._call_openai_compatible_endpoint(image_path, "controlled")

    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        exact = model_server._find_exact_lease(state, lease)
    assert exact["lifecycle_state"] == "request_in_flight"
    assert exact["request_attempt"] >= 2
    assert "completed_request_attempt" not in exact
    pending = model_server.reconcile_qwen_model_lease_failure(
        model_lease=lease,
        compute_completed=False,
        reason="managed_consumer_completed",
    )
    assert pending["status"] == "cancellation_acknowledged_pending"
    assert model_server.qwen_model_lease_is_active(lease) is True


def test_managed_local_provider_release_race_waits_for_exact_response_body(
    tmp_path,
    monkeypatch,
) -> None:
    from PIL import Image
    from app.vision import local_provider

    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "model_name": "qwen-controlled",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="managed-race-owner",
        readiness=_current_process_readiness(model_id="qwen-controlled"),
    )
    model_server._mark_qwen_model_request_in_flight(lease)
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    read_entered = Event()
    release_read = Event()
    requested_urls: list[str] = []

    class BlockingResponse(_FakeResponse):
        def read(self, size: int = -1) -> bytes:
            read_entered.set()
            assert release_read.wait(timeout=2.0)
            return super().read(size)

    def controlled_urlopen(request, timeout):
        del timeout
        requested_urls.append(request.full_url)
        return BlockingResponse({"choices": []})

    monkeypatch.setattr(local_provider, "urlopen", controlled_urlopen)
    provider = local_provider.LocalVisionProvider(
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="mutable-wrong-model",
        managed_model_lease=lease,
    )
    result: dict[str, object] = {}
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            result.update(provider._call_openai_compatible_endpoint(image_path, "controlled"))
        except BaseException as exc:
            errors.append(exc)

    worker = Thread(target=invoke)
    worker.start()
    assert read_entered.wait(timeout=1.0) is True
    pending = model_server.release_managed_qwen_model_lease(
        lease,
        "managed_consumer_completed",
    )
    assert pending["status"] == "cancellation_acknowledged_pending"
    assert model_server.qwen_model_lease_is_active(lease) is True

    release_read.set()
    worker.join(timeout=2.0)
    assert worker.is_alive() is False
    assert errors == []
    assert result == {"choices": []}
    assert requested_urls == [profile["endpoint"]]
    finalized = model_server.reconcile_qwen_model_lease_failure(
        model_lease=lease,
        compute_completed=False,
        reason="response_body_completed",
    )
    assert finalized["status"] == "released"
    assert model_server.qwen_model_lease_is_active(lease) is False


def test_managed_local_provider_parse_retry_then_timeout_reopens_request_lifecycle(
    tmp_path,
    monkeypatch,
) -> None:
    from PIL import Image
    from app.vision import local_provider
    from app.vision.schemas import VisionAnalyzeRequest

    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "model_name": "qwen-controlled",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="managed-parse-retry-timeout",
        readiness=_current_process_readiness(model_id="qwen-controlled"),
    )
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    dispatch_count = 0

    def controlled_urlopen(request, timeout):
        nonlocal dispatch_count
        del request, timeout
        dispatch_count += 1
        if dispatch_count == 1:
            return _FakeResponse(
                {"choices": [{"message": {"content": "not-json"}}]}
            )
        raise TimeoutError("controlled retry timeout")

    monkeypatch.setattr(local_provider, "urlopen", controlled_urlopen)
    provider = local_provider.LocalVisionProvider(
        endpoint="http://127.0.0.1:1/v1/chat/completions",
        model_name="mutable-wrong-model",
        timeout_seconds=0.01,
        managed_model_lease=lease,
    )

    with pytest.raises(RuntimeError, match="controlled retry timeout"):
        provider.analyze(VisionAnalyzeRequest(image_path=str(image_path)))

    assert dispatch_count >= 2
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        exact = model_server._find_exact_lease(state, lease)
    assert exact["lifecycle_state"] == "request_in_flight"
    assert exact["request_attempt"] >= 2
    assert "completed_request_attempt" not in exact
    pending = model_server.reconcile_qwen_model_lease_failure(
        model_lease=lease,
        compute_completed=False,
        reason="parse_retry_timeout",
    )
    assert pending["status"] == "cancellation_acknowledged_pending"


def test_managed_factory_stub_endpoint_uses_lease_and_blocks_release_until_body(
    tmp_path,
    monkeypatch,
) -> None:
    from PIL import Image
    from app.vision import local_provider
    from app.vision.factory import VisionProviderFactory
    from app.vision.schemas import VisionAnalyzeRequest

    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "model_name": "qwen-controlled",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="managed-factory-stub-owner",
        readiness=_current_process_readiness(model_id="qwen-controlled"),
    )
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    read_entered = Event()
    release_read = Event()
    requested_urls: list[str] = []

    class BlockingResponse(_FakeResponse):
        def read(self, size: int = -1) -> bytes:
            read_entered.set()
            assert release_read.wait(timeout=2.0)
            return super().read(size)

    def controlled_urlopen(request, timeout):
        del timeout
        requested_urls.append(request.full_url)
        return BlockingResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "screen_summary": "leased response",
                                    "state_guess": "leased",
                                    "regions": [],
                                    "targets": [],
                                    "observers": [],
                                    "notes": [],
                                }
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(local_provider, "urlopen", controlled_urlopen)
    provider = VisionProviderFactory.create(config=deepcopy(VisionProviderFactory.load_config(tmp_path / "missing.json")))
    assert provider.endpoint is None
    provider.bind_managed_model_lease(lease)
    result: dict[str, object] = {}
    errors: list[BaseException] = []

    def invoke() -> None:
        try:
            result["response"] = provider.analyze(
                VisionAnalyzeRequest(image_path=str(image_path))
            )
        except BaseException as exc:
            errors.append(exc)

    worker = Thread(target=invoke)
    worker.start()
    assert read_entered.wait(timeout=1.0) is True
    pending = model_server.release_managed_qwen_model_lease(
        lease,
        "concurrent_release",
    )
    assert pending["status"] == "cancellation_acknowledged_pending"
    release_read.set()
    worker.join(timeout=2.0)

    assert worker.is_alive() is False
    assert errors == []
    assert requested_urls == [profile["endpoint"]]
    response = result["response"]
    assert response.screen_summary == "leased response"
    assert response.raw_response["endpoint_response"]
    finalized = model_server.reconcile_qwen_model_lease_failure(
        model_lease=lease,
        compute_completed=False,
        reason="response_body_completed",
    )
    assert finalized["status"] == "released"
    assert model_server.qwen_model_lease_is_active(lease) is False


def test_model_review_http_attempt_reopens_completed_lease_before_later_timeout(
    tmp_path,
    monkeypatch,
) -> None:
    from PIL import Image
    from scripts import run_learning_overlay_model_review_probe as review_probe

    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "model_name": "qwen-controlled",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="managed-model-review-owner",
        readiness=_current_process_readiness(model_id="qwen-controlled"),
    )
    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", "managed-model-review-owner")
    image_path = tmp_path / "review.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    drifted_profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13241/v1/chat/completions",
        "model_name": "qwen-drifted",
    }
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [drifted_profile])
    dispatch_count = 0
    dispatched_requests: list[dict[str, object]] = []

    def controlled_urlopen(request, timeout):
        nonlocal dispatch_count
        dispatch_count += 1
        dispatched_requests.append(
            {
                "url": request.full_url,
                "body": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        if dispatch_count == 1:
            return _FakeResponse({"choices": [{"message": {"content": "{}"}}]})
        raise TimeoutError("controlled model-review timeout")

    monkeypatch.setattr(review_probe, "urlopen", controlled_urlopen)
    first = review_probe._call_model(
        endpoint=drifted_profile["endpoint"],
        model_name=drifted_profile["model_name"],
        image_path=image_path,
        prompt="first",
        timeout_seconds=0.01,
        managed_model_lease=lease,
    )
    assert first["choices"]
    with model_server._qwen_lease_lock():
        completed_state = model_server._load_qwen_lease_state(
            lease["incarnation_id"]
        )
        completed_exact = model_server._find_exact_lease(completed_state, lease)
    assert completed_exact["lifecycle_state"] == "compute_complete"
    assert completed_exact["completed_request_attempt"] == 1

    with pytest.raises(TimeoutError, match="controlled model-review timeout"):
        review_probe._call_model(
            endpoint=drifted_profile["endpoint"],
            model_name=drifted_profile["model_name"],
            image_path=image_path,
            prompt="retry",
            timeout_seconds=0.01,
            managed_model_lease=lease,
        )

    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        exact = model_server._find_exact_lease(state, lease)
    assert exact["lifecycle_state"] == "request_in_flight"
    assert exact["request_attempt"] == 2
    assert "completed_request_attempt" not in exact
    assert [item["url"] for item in dispatched_requests] == [
        profile["endpoint"],
        profile["endpoint"],
    ]
    assert [item["body"]["model"] for item in dispatched_requests] == [
        profile["model_name"],
        profile["model_name"],
    ]


def test_unbound_model_review_response_cannot_complete_ambient_managed_lease(
    tmp_path,
    monkeypatch,
) -> None:
    from PIL import Image
    from scripts import run_learning_overlay_model_review_probe as review_probe

    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "model_name": "qwen-controlled",
    }
    drifted_endpoint = "http://127.0.0.1:13241/v1/chat/completions"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="managed-model-review-owner",
        readiness=_current_process_readiness(model_id="qwen-controlled"),
    )
    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", "managed-model-review-owner")
    image_path = tmp_path / "review.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    requested_urls: list[str] = []

    def controlled_urlopen(request, timeout):
        del timeout
        requested_urls.append(request.full_url)
        return _FakeResponse({"choices": [{"message": {"content": "{}"}}]})

    monkeypatch.setattr(review_probe, "urlopen", controlled_urlopen)
    response = review_probe._call_model(
        endpoint=drifted_endpoint,
        model_name="qwen-drifted",
        image_path=image_path,
        prompt="unbound",
        timeout_seconds=0.01,
    )

    assert response["choices"]
    assert requested_urls == [drifted_endpoint]
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        exact = model_server._find_exact_lease(state, lease)
    assert exact["lifecycle_state"] == "not_started"
    assert "request_attempt" not in exact


def test_managed_model_review_fails_closed_when_exact_attempt_cannot_open(
    tmp_path,
    monkeypatch,
) -> None:
    from PIL import Image
    from scripts import run_learning_overlay_model_review_probe as review_probe

    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "model_name": "qwen-controlled",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="managed-model-review-owner",
        readiness=_current_process_readiness(model_id="qwen-controlled"),
    )
    image_path = tmp_path / "review.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    monkeypatch.setattr(
        model_server,
        "mark_qwen_model_request_in_flight",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        review_probe,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("inactive exact lease reached HTTP dispatch"),
    )

    with pytest.raises(RuntimeError, match="exact request attempt"):
        review_probe._call_model(
            endpoint=profile["endpoint"],
            model_name=profile["model_name"],
            image_path=image_path,
            prompt="closed lease",
            timeout_seconds=0.01,
            managed_model_lease=lease,
        )


def test_managed_model_review_reattests_exact_socket_after_attempt_open(
    tmp_path,
    monkeypatch,
) -> None:
    from PIL import Image
    from scripts import run_learning_overlay_model_review_probe as review_probe

    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "model_name": "qwen-controlled",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "leases")
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="managed-model-review-owner",
        readiness=_current_process_readiness(model_id="qwen-controlled"),
    )
    image_path = tmp_path / "review.png"
    Image.new("RGB", (8, 8), "white").save(image_path)
    production_mark = model_server.mark_qwen_model_request_in_flight

    def open_attempt_then_drift(**kwargs):
        attempt = production_mark(**kwargs)
        monkeypatch.setattr(
            model_server,
            "_attest_exact_qwen_socket_owner",
            lambda server_socket, process_identity: False,
        )
        return attempt

    monkeypatch.setattr(
        model_server,
        "mark_qwen_model_request_in_flight",
        open_attempt_then_drift,
    )
    monkeypatch.setattr(
        review_probe,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("drifted socket reached HTTP dispatch"),
    )

    with pytest.raises(RuntimeError, match="socket ownership changed"):
        review_probe._call_model(
            endpoint=profile["endpoint"],
            model_name=profile["model_name"],
            image_path=image_path,
            prompt="drift after attempt open",
            timeout_seconds=0.01,
            managed_model_lease=lease,
        )

    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        exact = model_server._find_exact_lease(state, lease)
    assert exact["lifecycle_state"] == "request_in_flight"


def test_qwen_finalizer_crash_after_stop_recovers_from_proven_absence_without_second_stop(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="recover-terminal-state-write",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    proofs = iter(
        [
            {"status": "exact_live", "identity": {"pid": 9101, "create_time_ns": 111}},
            {"status": "proven_absent", "identity": None, "reason": "no_such_process"},
        ]
    )
    monkeypatch.setattr(model_server, "_probe_exact_qwen_process", lambda expected: next(proofs))
    stops = []

    def terminate(expected):
        stops.append(deepcopy(expected))
        return {"status": "proven_absent", "identity": None, "reason": "terminated"}

    monkeypatch.setattr(model_server, "_terminate_exact_qwen_server_process", terminate)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected: {"status": "unreachable"},
    )
    original_write = model_server._write_qwen_lease_state
    failed = False

    def fail_terminal_write(state):
        nonlocal failed
        finalization = state.get("finalization")
        if (
            not failed
            and isinstance(finalization, dict)
            and finalization.get("phase") == "termination_proven"
        ):
            failed = True
            raise OSError("injected terminal state write failure")
        return original_write(state)

    monkeypatch.setattr(model_server, "_write_qwen_lease_state", fail_terminal_write)

    with pytest.raises(OSError, match="terminal state write failure"):
        model_server._release_exact_qwen_lease(lease, reason="completed")

    recovered = model_server._release_exact_qwen_lease(lease, reason="completed")

    assert recovered["status"] == "released"
    assert recovered["server_termination"] == "verified_exact_process_proven_absent_on_retry"
    assert stops == [{"pid": 9101, "create_time_ns": 111}]


def test_qwen_final_stop_runs_outside_os_state_lock_and_proves_exact_pid_exit(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "exact_live", "identity": expected},
    )
    stop_observed_lock = Event()

    def stop(expected):
        with model_server._qwen_lease_lock():
            stop_observed_lock.set()
        return {"status": "proven_absent", "identity": None, "expected": expected}

    monkeypatch.setattr(model_server, "_terminate_exact_qwen_server_process", stop)
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {"status": "unreachable"})

    released = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=lease,
    )
    assert stop_observed_lock.is_set() is True
    assert released["server_termination"] == "verified_exact_process_exited"


def test_qwen_os_lock_is_not_stolen_from_live_owner(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    owner_entered = Event()
    release_owner = Event()
    waiter_entered = Event()

    def owner():
        with model_server._qwen_lease_lock():
            lock_path = tmp_path / ".lease-state.lock"
            old = time.time() - 31.0
            os.utime(lock_path, (old, old))
            owner_entered.set()
            release_owner.wait(timeout=2.0)

    def waiter():
        owner_entered.wait(timeout=2.0)
        with model_server._qwen_lease_lock():
            waiter_entered.set()

    first = Thread(target=owner)
    second = Thread(target=waiter)
    first.start()
    second.start()
    assert owner_entered.wait(timeout=1.0) is True
    time.sleep(0.05)
    assert waiter_entered.is_set() is False
    release_owner.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)
    assert waiter_entered.is_set() is True


@pytest.mark.parametrize("candidate_count", [0, 1, 15])
def test_qwen_binding_response_schema_closes_each_supplied_candidate_id(
    candidate_count,
) -> None:
    candidate_ids = [
        "candidate/" + f"{index:064x}" for index in range(candidate_count)
    ]

    schema = model_server._qwen_binding_response_schema(
        {"candidates": [{"candidate_id": candidate_id} for candidate_id in candidate_ids]}
    )

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "bindings",
        "ambiguity_sets",
        "orphan_semantics",
    }
    bindings_schema = schema["properties"]["bindings"]
    assert set(bindings_schema) == {
        "type",
        "prefixItems",
        "minItems",
        "maxItems",
    }
    assert bindings_schema["minItems"] == candidate_count
    assert bindings_schema["maxItems"] == candidate_count
    assert [
        item["properties"]["candidate_id"]["const"]
        for item in bindings_schema["prefixItems"]
    ] == candidate_ids
    binding_fields = {
        "candidate_id",
        "role",
        "label",
        "description",
        "semantic_confidence",
        "task_relevance",
        "relation",
        "ambiguity",
    }
    assert all(
        set(item["properties"]) == binding_fields
        and set(item["required"]) == binding_fields
        and item["additionalProperties"] is False
        for item in bindings_schema["prefixItems"]
    )
    ambiguity_item_schema = schema["properties"]["ambiguity_sets"]["items"]
    assert ambiguity_item_schema == {
        "type": "object",
        "properties": {
            "contract_version": {"const": "hybrid_semantic_ambiguity_set_v1"},
            "candidate_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "uniqueItems": True,
            },
        },
        "required": ["contract_version", "candidate_ids"],
        "additionalProperties": False,
    }
    orphan_semantics_schema = schema["properties"]["orphan_semantics"]
    assert orphan_semantics_schema["maxItems"] == 64
    assert orphan_semantics_schema["items"] == {
        "type": "object",
        "properties": {
            "semantic_id": {"type": "string", "pattern": "^semantic/.*$"},
            "role": {"type": "string"},
            "label": {"type": "string"},
            "description": {"type": "string"},
            "reason": {"const": "ORPHAN_SEMANTIC"},
        },
        "required": ["semantic_id", "role", "label", "description", "reason"],
        "additionalProperties": False,
    }


def test_qwen_binding_response_schema_rejects_missing_candidate_inventory() -> None:
    with pytest.raises(ValueError, match="Qwen binding request candidates"):
        model_server._qwen_binding_response_schema({})


@pytest.mark.parametrize(
    "candidates",
    [
        None,
        {},
        [{"candidate_id": 7}],
        [{"candidate_id": "candidate/duplicate"}, {"candidate_id": "candidate/duplicate"}],
    ],
)
def test_qwen_binding_response_schema_rejects_invalid_candidate_inventory(
    candidates,
) -> None:
    with pytest.raises(ValueError, match="Qwen binding request candidates"):
        model_server._qwen_binding_response_schema({"candidates": candidates})


def test_qwen_binding_runner_reuses_understanding_endpoint_and_request_id(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "model_name": "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    seen: dict = {}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="learn-qwen-request",
        readiness=_server_readiness(started=False, model_id=profile["model_name"]),
    )
    changed_profile = {**profile, "endpoint": "http://127.0.0.1:13240/v1/should-not-use"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: changed_profile)
    monkeypatch.setattr(model_server, "_current_process_identity", lambda pid: {
        "pid": 9101,
        "create_time_ns": 123456789,
    })
    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", "learn-qwen-request")
    screenshot_bytes = b"controlled-task2-image-bytes"
    candidate_ids = ["candidate/" + "a" * 64, "candidate/" + "b" * 64]
    model_request = {
        "contract_version": "hybrid_qwen_binding_request_v1",
        "label": "申请职位",
        "candidates": [{"candidate_id": candidate_id} for candidate_id in candidate_ids],
    }
    model_response = {
        "bindings": [
            {
                "candidate_id": candidate_id,
                "role": "button",
                "label": f"candidate {index}",
                "description": "",
                "semantic_confidence": 0.5,
                "task_relevance": 0.5,
                "relation": "visible",
                "ambiguity": None,
            }
            for index, candidate_id in enumerate(candidate_ids)
        ],
        "ambiguity_sets": [],
        "orphan_semantics": [],
    }

    def fake_urlopen(request, timeout):
        seen.update(
            url=request.full_url,
            headers=dict(request.headers),
            body=json.loads(request.data.decode("utf-8")),
            timeout=timeout,
        )
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(model_response, ensure_ascii=False)
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(model_server.urllib.request, "urlopen", fake_urlopen)
    result = model_server.run_qwen_binding_model(
        request=model_request,
        screenshot_bytes=screenshot_bytes,
        screenshot_media_type="image/png",
        screenshot_sha256=__import__("hashlib").sha256(screenshot_bytes).hexdigest(),
        model_lease=lease,
        timeout_seconds=3.0,
    )

    assert result == model_response
    assert seen["url"] == profile["endpoint"]
    assert seen["timeout"] == 3.0
    assert seen["body"]["request_id"] == "learn-qwen-request"
    assert seen["body"]["model"] == profile["model_name"]
    response_format = seen["body"]["response_format"]
    assert response_format["type"] == "json_object"
    schema = response_format["schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["bindings", "ambiguity_sets", "orphan_semantics"]
    bindings_schema = schema["properties"]["bindings"]
    assert "items" not in bindings_schema
    assert bindings_schema["minItems"] == len(candidate_ids)
    assert bindings_schema["maxItems"] == len(candidate_ids)
    assert [
        item["properties"]["candidate_id"]["const"]
        for item in bindings_schema["prefixItems"]
    ] == candidate_ids
    assert all(
        item["additionalProperties"] is False
        and set(item["required"])
        == {
            "candidate_id",
            "role",
            "label",
            "description",
            "semantic_confidence",
            "task_relevance",
            "relation",
            "ambiguity",
        }
        for item in bindings_schema["prefixItems"]
    )
    prompt = seen["body"]["messages"][1]["content"][0]["text"]
    assert "申请职位" in prompt
    assert "three top-level fields bindings, ambiguity_sets, and orphan_semantics" in prompt
    image_url = seen["body"]["messages"][1]["content"][1]["image_url"]["url"]
    assert base64.b64decode(image_url.split(",", 1)[1]) == screenshot_bytes


def test_qwen_binding_runner_preserves_hash_bound_parse_failure_diagnostics(
    monkeypatch,
) -> None:
    from app.learn.recognition.uei.canonical import content_sha256
    from app.learn.workflow_worker import _hybrid_managed_failure_result

    profile = {
        "profile_id": "qwen-trace",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "model_name": "qwen-trace-model",
    }
    screenshot_bytes = b"diagnostic-image"
    screenshot_sha256 = __import__("hashlib").sha256(screenshot_bytes).hexdigest()
    raw_content = '{"bindings":[{"label":"快速申请"}'
    usage = {
        "prompt_tokens": 5644,
        "completion_tokens": 4096,
        "total_tokens": 9740,
    }
    response_payload = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {"content": raw_content},
            }
        ],
        "usage": usage,
    }
    response_bytes = json.dumps(response_payload).encode("utf-8")
    seen: dict = {}

    def fake_urlopen(request, timeout):
        seen["request"] = json.loads(request.data.decode("utf-8"))
        seen["timeout"] = timeout
        return _FakeResponse(response_payload)

    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", "request-qwen-trace")
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)
    monkeypatch.setattr(
        model_server.urllib.request,
        "urlopen",
        fake_urlopen,
    )

    with pytest.raises(
        ValueError,
        match="Qwen binding response is not a closed JSON object",
    ) as failure:
        model_server.run_qwen_binding_model(
            request={"candidates": []},
            screenshot_bytes=screenshot_bytes,
            screenshot_media_type="image/png",
            screenshot_sha256=screenshot_sha256,
        )

    diagnostics = getattr(failure.value, "diagnostics", None)
    assert isinstance(diagnostics, dict)
    assert diagnostics["contract_version"] == "qwen_binding_response_failure_trace_v1"
    assert diagnostics["artifact_is_authorization"] is False
    assert diagnostics["execute_binding_enabled"] is False
    assert diagnostics["evidence_use"] == "benchmark_non_authorizing_diagnostic"
    assert diagnostics["request_lineage"] == {
        "model_request_id": "request-qwen-trace",
        "request_content_sha256": content_sha256({"candidates": []}),
        "screenshot_sha256": screenshot_sha256,
        "profile_id": "qwen-trace",
        "model_id": "qwen-trace-model",
    }
    assert diagnostics["http_response"] == {
        "response_body_bytes": len(response_bytes),
        "response_body_sha256": __import__("hashlib")
        .sha256(response_bytes)
        .hexdigest(),
        "raw_message_content": raw_content,
        "raw_message_content_utf8_bytes": len(raw_content.encode("utf-8")),
        "raw_message_content_sha256": __import__("hashlib")
        .sha256(raw_content.encode("utf-8"))
        .hexdigest(),
        "finish_reason": "length",
        "usage": usage,
    }
    assert diagnostics["parse_error"]["type"] == "JSONDecodeError"
    assert diagnostics["parse_error"]["line"] == 1
    assert diagnostics["parse_error"]["column"] == len(raw_content) + 1
    assert diagnostics["parse_error"]["position"] == len(raw_content)
    assert diagnostics["content_sha256"] == content_sha256(diagnostics)
    assert seen["request"]["max_tokens"] == 4096
    assert seen["request"]["temperature"] == 0.0
    assert seen["request"]["response_format"]["type"] == "json_object"

    projected = _hybrid_managed_failure_result(
        task_kind="panel_learning_hybrid_qwen_binding",
        error=failure.value,
        orchestration={},
        lifecycle_evidence={"status": "verified"},
    )
    assert projected["result"]["diagnostics"] == diagnostics


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("direct timeout"),
        socket.timeout("socket timeout"),
        urllib.error.URLError(socket.timeout("wrapped timeout")),
    ],
)
def test_qwen_binding_runner_normalizes_timeout_types(monkeypatch, error) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)
    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(error))

    with pytest.raises(model_server.QwenModelRequestTimeout):
        model_server.run_qwen_binding_model(
            request={"candidates": []},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            timeout_seconds=0.1,
        )


def test_qwen_binding_runner_rejects_oversized_http_body(monkeypatch) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)

    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size=-1):
            return b"x" * size

    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda *args, **kwargs: OversizedResponse())
    with pytest.raises(ValueError, match="response byte limit"):
        model_server.run_qwen_binding_model(
            request={"candidates": []},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
        )


def test_qwen_http_event_set_and_cancelled_transport_use_typed_cancellation(monkeypatch) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)
    cancellation = Event()
    cancellation.set()
    with pytest.raises(model_server.QwenModelRequestCancelled):
        model_server.run_qwen_binding_model(
            request={"candidates": []},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            cancellation_event=cancellation,
        )

    cancellation.clear()

    def cancelled_transport(*args, **kwargs):
        del args, kwargs
        cancellation.set()
        raise urllib.error.URLError("cancelled transport")

    monkeypatch.setattr(model_server.urllib.request, "urlopen", cancelled_transport)
    with pytest.raises(model_server.QwenModelRequestCancelled):
        model_server.run_qwen_binding_model(
            request={"candidates": []},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            cancellation_event=cancellation,
        )


def test_qwen_runner_rejects_replaced_server_incarnation_before_http(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness=_server_readiness(started=False, pid=9101, created_ns=111),
    )
    monkeypatch.setattr(model_server, "_current_process_identity", lambda pid: {
        "pid": 9101,
        "create_time_ns": 222,
    })
    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda *args, **kwargs: pytest.fail("replacement received request"))

    with pytest.raises(RuntimeError, match="server incarnation ownership changed"):
        model_server.run_qwen_binding_model(
            request={"candidates": []},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            model_lease=lease,
        )


def test_qwen_runner_rejects_replaced_endpoint_socket_owner_before_http(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-socket-drift",
        readiness=_server_readiness(started=False, pid=9101, created_ns=111),
    )
    monkeypatch.setattr(model_server, "_current_process_identity", lambda pid: {
        "pid": 9101,
        "create_time_ns": 111,
    })
    observed = []

    def reject_socket(server_socket, process_identity):
        observed.append((deepcopy(server_socket), deepcopy(process_identity)))
        return False

    monkeypatch.setattr(
        model_server,
        "_attest_exact_qwen_socket_owner",
        reject_socket,
        raising=False,
    )
    monkeypatch.setattr(
        model_server.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("replacement socket owner received request"),
    )

    with pytest.raises(RuntimeError, match="endpoint socket ownership changed"):
        model_server.run_qwen_binding_model(
            request={"candidates": []},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            model_lease=lease,
        )

    assert observed == [
        (
            {"host": "127.0.0.1", "port": 13240},
            {"pid": 9101, "create_time_ns": 111},
        )
    ]


def test_exact_qwen_socket_attester_requires_one_sealed_pid_and_create_time(
    monkeypatch,
) -> None:
    class Address:
        ip = "127.0.0.1"
        port = 13240

    class Connection:
        status = psutil.CONN_LISTEN
        laddr = Address()

        def __init__(self, pid):
            self.pid = pid

    identity = {"pid": 9101, "create_time_ns": 111}
    monkeypatch.setattr(model_server, "_current_process_identity", lambda pid: deepcopy(identity))
    monkeypatch.setattr(model_server.psutil, "net_connections", lambda kind: [Connection(9101)])

    assert _PRODUCTION_QWEN_SOCKET_ATTESTER(
        {"host": "127.0.0.1", "port": 13240}, identity
    ) is True

    monkeypatch.setattr(
        model_server.psutil,
        "net_connections",
        lambda kind: [Connection(9101), Connection(9202)],
    )
    assert _PRODUCTION_QWEN_SOCKET_ATTESTER(
        {"host": "127.0.0.1", "port": 13240}, identity
    ) is False

    monkeypatch.setattr(
        model_server,
        "_current_process_identity",
        lambda pid: {"pid": 9101, "create_time_ns": 222},
    )
    assert _PRODUCTION_QWEN_SOCKET_ATTESTER(
        {"host": "127.0.0.1", "port": 13240}, identity
    ) is False


def test_legacy_v2_missing_lifecycle_is_unknown_in_flight_and_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="legacy-owner",
        readiness=_server_readiness(started=False, pid=9101, created_ns=111),
    )
    retained = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="retained-owner",
        readiness=_server_readiness(started=False, pid=9101, created_ns=111),
    )
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        state["contract_version"] = "qwen_model_server_lease_state_v2"
        for stored in state["leases"]:
            stored.pop("lifecycle_state", None)
        model_server._write_qwen_lease_state(state)

    result = model_server.cancel_model_request(
        request_id="legacy-owner",
        task_kind="panel_learning_recognition_trial",
        payload={},
    )

    assert result["status"] == "cancellation_acknowledged_pending"
    assert model_server.qwen_model_lease_is_active(lease) is True
    assert model_server.qwen_model_lease_is_active(retained) is True
    with model_server._qwen_lease_lock():
        migrated = model_server._load_qwen_lease_state(lease["incarnation_id"])
    assert migrated["leases"][0]["lifecycle_state"] == "unknown_in_flight"


def test_qwen_v3_state_rejects_open_lifecycle_values(tmp_path, monkeypatch) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="invalid-lifecycle",
        readiness=_server_readiness(started=False, pid=9101, created_ns=111),
    )
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        state["leases"][0]["lifecycle_state"] = "assume_safe"
        model_server._write_qwen_lease_state(state)

    with pytest.raises(RuntimeError, match="lease lifecycle is invalid"):
        model_server._load_qwen_lease_state(lease["incarnation_id"])


def test_legacy_finalization_without_finalizer_pid_recovers_from_exact_absence(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="legacy-finalizer",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        state["contract_version"] = "qwen_model_server_lease_state_v2"
        state["revision"] += 1
        state["finalization"] = {
            "token": "legacy-token",
            "revision": state["revision"],
            "lease_id": lease["lease_id"],
            "phase": "stop_pending",
            "reason": "legacy-retry",
        }
        model_server._write_qwen_lease_state(state)
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda expected: {"status": "proven_absent", "identity": None, "reason": "no_such_process"},
    )
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: pytest.fail("legacy recovery must not terminate again"),
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda profile: {"status": "unreachable"})

    result = model_server._release_exact_qwen_lease(lease, reason="legacy-retry")

    assert result["status"] == "released"
    assert result["server_termination"] == "verified_exact_process_proven_absent_on_retry"
    assert model_server.qwen_model_lease_is_active(lease) is False


def test_qwen_terminal_proof_is_phase_cas_and_tombstone_recovery_is_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="proof-race",
        readiness=_server_readiness(started=True, pid=9101, created_ns=111),
    )
    with model_server._qwen_lease_lock():
        state = model_server._load_qwen_lease_state(lease["incarnation_id"])
        state["revision"] += 1
        revision = state["revision"]
        state["finalization"] = {
            "token": "proof-token",
            "revision": revision,
            "lease_id": lease["lease_id"],
            "phase": "stop_pending",
            "reason": "race",
            "finalizer_pid": os.getpid(),
        }
        model_server._write_qwen_lease_state(state)
    first_result = {"status": "released", "server_termination": "proof-a", "lease": lease}
    second_result = {"status": "released", "server_termination": "proof-b", "lease": lease}
    outputs = []
    gate = Event()

    def persist(candidate):
        gate.wait(timeout=1.0)
        outputs.append(
            model_server._persist_qwen_termination_proof(
                state,
                token="proof-token",
                revision=revision,
                result=candidate,
            )
        )

    threads = [Thread(target=persist, args=(candidate,)) for candidate in (first_result, second_result)]
    for thread in threads:
        thread.start()
    gate.set()
    for thread in threads:
        thread.join(timeout=1.0)

    assert len(outputs) == 2
    assert outputs[0] == outputs[1]
    assert outputs[0]["server_termination"] in {"proof-a", "proof-b"}
    cleaned = model_server._finish_qwen_finalization_cleanup(
        lease["incarnation_id"],
        token="proof-token",
        revision=revision,
        model_lease=lease,
    )
    recovered = model_server._finish_qwen_finalization_cleanup(
        lease["incarnation_id"],
        token="proof-token",
        revision=revision,
        model_lease=lease,
    )
    assert recovered == cleaned == outputs[0]


def test_spawned_python_inherits_hard_deny_before_real_wrapper_boundary() -> None:
    code = """
import sys
from app.core import model_server
model_server.subprocess.Popen = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('REAL_WRAPPER_REACHED'))
try:
    model_server.start_model_server({'profile_id': 'deny-test', 'start_script': 'scripts/model_servers/start_llama_vision_server.ps1'})
except RuntimeError as error:
    text = str(error)
    print(text)
    raise SystemExit(0 if 'disabled by inherited test safety sentinel' in text else 7)
raise SystemExit(8)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=model_server.ROOT_DIR,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "disabled by inherited test safety sentinel" in completed.stdout
    assert "REAL_WRAPPER_REACHED" not in completed.stdout + completed.stderr


def _benchmark_qwen_runtime_owner(request_id: str) -> dict:
    return seal_immutable(
        {
            "contract_version": "benchmark_provider_runtime_owner_v1",
            "authority_kind": "test",
            "run_id": "run-b2-ledger",
            "stage": "panel_learning_calibration_sequence",
            "operation_id": f"operation-{request_id}",
            "worker_id": f"worker-{request_id}",
            "model_request_id": request_id,
            "reservation_ref": {"content_sha256": "1" * 64},
            "payload_sha256": "2" * 64,
        }
    )


def _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id: str) -> dict:
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen-leases")
    return model_server.prepare_qwen_model_request_acquisition_owner(
        request_id,
        runtime_owner_ref=_benchmark_qwen_runtime_owner(request_id),
    )


def _install_benchmark_qwen_abort_primitive(
    tmp_path,
    monkeypatch,
    request_id: str,
) -> Path:
    from app.learn.hybrid.windows_process_scope import process_scope_name

    lineage = {**_HYBRID_LINEAGE, "operation_id": f"operation-{request_id}"}
    scope_name = process_scope_name(lineage, "qwen")
    runtime_path = tmp_path / f"{request_id}-qwen-runtime.json"
    profile = {
        "profile_id": f"profile-{request_id}",
        "endpoint": "http://127.0.0.1:54990/v1/chat/completions",
        "pid_file": str(tmp_path / f"{request_id}.pid"),
    }
    model_server._write_hybrid_qwen_runtime(
        runtime_path,
        seal_immutable(
            {
                "contract_version": "hybrid_qwen_acquisition_intent_v1",
                "state": "starting",
                "worker_id": f"worker-{request_id}",
                "model_request_id": request_id,
                "provider": "qwen",
                "lineage": lineage,
                "process_scope_name": scope_name,
                "profile": profile,
                "profile_sha256": model_server.content_sha256(
                    model_server._public_profile(profile)
                ),
                "listener_port": 54990,
                "pid_file": profile["pid_file"],
                "aborted_tombstone_sha256": None,
            }
        ),
    )
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setenv(
        "AGENT_GUI_HYBRID_LINEAGE_JSON",
        json.dumps(lineage, sort_keys=True, separators=(",", ":")),
    )
    return runtime_path


def test_materialization_ledger_prepare_is_deterministic_and_has_zero_provider_side_effect(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-prepare-zero-provider"
    forbidden = []

    def reject(name):
        def fail(*args, **kwargs):
            forbidden.append((name, args, kwargs))
            raise AssertionError(f"prepare reached provider side effect: {name}")

        return fail

    for name in (
        "profile_for_stage",
        "_ensure_model_server_for_profile",
        "acquire_qwen_model_lease",
        "start_model_server",
    ):
        monkeypatch.setattr(model_server, name, reject(name))

    first = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    second = model_server.prepare_qwen_model_request_acquisition_owner(
        request_id,
        runtime_owner_ref=_benchmark_qwen_runtime_owner(request_id),
    )
    ledger = model_server._load_qwen_model_request_materialization_ledger(request_id)

    assert first == second
    assert set(first) == {
        "contract_version",
        "model_request_id",
        "runtime_owner_ref",
        "acquisition_intent_ref",
        "owner_state",
        "content_sha256",
    }
    assert first["contract_version"] == "benchmark_provider_acquisition_owner_v1"
    assert first["owner_state"] == "acquisition_prepared"
    assert ledger == seal_immutable(
        {
            "contract_version": "qwen_model_request_materialization_ledger_v1",
            "model_request_id": request_id,
            "acquisition_intent_ref": first["acquisition_intent_ref"],
            "runtime_owner_ref": first["runtime_owner_ref"],
            "state": "prepared_never_materialized",
            "revision": 0,
            "transition": "prepare",
            "predecessor_content_sha256": None,
        }
    )
    assert forbidden == []
    assert list((tmp_path / "qwen-leases").glob("*.json")) == []


def test_qwen_cleanup_sidecar_abort_replays_byte_identically_and_blocks_launch(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-abort-replay"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    arguments = {
        "acquisition_intent_ref": owner["acquisition_intent_ref"],
        "runtime_owner_ref": owner["runtime_owner_ref"],
        "reason": "cancelled",
    }

    first_abort = model_server.abort_qwen_model_request_acquisition(request_id, **arguments)
    tombstone_path = model_server._qwen_acquisition_artifact_paths(request_id)[
        "aborted_tombstone"
    ]
    tombstone_bytes = tombstone_path.read_bytes()
    first_receipt = model_server.observe_qwen_model_request_cleanup(request_id)
    second_abort = model_server.abort_qwen_model_request_acquisition(request_id, **arguments)
    second_receipt = model_server.observe_qwen_model_request_cleanup(request_id)

    assert first_abort == second_abort
    assert tombstone_path.read_bytes() == tombstone_bytes
    assert json.loads(tombstone_bytes)["contract_version"] == (
        "benchmark_provider_aborted_acquisition_tombstone_v1"
    )
    assert first_receipt == second_receipt
    assert first_receipt["contract_version"] == "qwen_model_request_cleanup_receipt_v1"
    assert first_receipt["outcome"] == "verified_not_acquired"
    assert set(first_receipt) == model_server._QWEN_CLEANUP_RECEIPT_FIELDS
    assert first_receipt["lease_ref"] is None
    assert first_receipt["server_process_identity"] is None
    assert first_receipt["scope_stable_zero_ref"] is None
    assert first_receipt["listener_stable_zero_ref"] is None
    assert first_receipt["no_active_lease_observation_ref"] is not None
    assert first_receipt["no_owned_runtime_observation_ref"] is not None
    with pytest.raises(RuntimeError, match="conflicts|aborted"):
        model_server._transition_qwen_model_request_materialization(
            request_id, transition="launch"
        )


def test_qwen_cleanup_sidecar_abort_without_runtime_uses_materialization_ledger(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-abort-without-provider-runtime"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    arguments = {
        "acquisition_intent_ref": owner["acquisition_intent_ref"],
        "runtime_owner_ref": owner["runtime_owner_ref"],
        "reason": "exact_worker_exited_before_provider_start",
    }

    first_abort = model_server.abort_qwen_model_request_acquisition(
        request_id, **arguments
    )
    first_receipt = model_server.observe_qwen_model_request_cleanup(request_id)
    second_abort = model_server.abort_qwen_model_request_acquisition(
        request_id, **arguments
    )
    second_receipt = model_server.observe_qwen_model_request_cleanup(request_id)
    paths = model_server._qwen_acquisition_artifact_paths(request_id)
    tombstone = json.loads(paths["aborted_tombstone"].read_text(encoding="utf-8"))

    assert first_abort == second_abort
    assert first_abort["owner_tombstone_ref"] == {
        "content_sha256": tombstone["content_sha256"]
    }
    assert first_receipt == second_receipt
    assert first_receipt["outcome"] == "verified_not_acquired"
    assert first_receipt["owner_tombstone_ref"] == first_abort[
        "owner_tombstone_ref"
    ]
    assert first_receipt["scope_stable_zero_ref"] is None
    assert first_receipt["listener_stable_zero_ref"] is None
    assert first_receipt["no_owned_runtime_observation_ref"] == first_abort[
        "owner_tombstone_ref"
    ]


@pytest.mark.parametrize("first_transition", ["abort", "launch"])
def test_materialization_ledger_cancel_launch_race_has_one_durable_winner_in_both_orders(
    tmp_path,
    monkeypatch,
    first_transition,
) -> None:
    request_id = f"benchmark-linearization-{first_transition}"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)

    if first_transition == "abort":
        model_server.abort_qwen_model_request_acquisition(
            request_id,
            acquisition_intent_ref=owner["acquisition_intent_ref"],
            runtime_owner_ref=owner["runtime_owner_ref"],
            reason="cancelled",
        )
        with pytest.raises(RuntimeError, match="conflicts|aborted"):
            model_server._transition_qwen_model_request_materialization(
                request_id, transition="launch"
            )
        expected_state = "aborted_never_materialized"
    else:
        first = model_server._transition_qwen_model_request_materialization(
            request_id, transition="launch"
        )
        assert model_server._transition_qwen_model_request_materialization(
            request_id, transition="launch"
        ) == first
        with pytest.raises(RuntimeError, match="conflicts|materialization"):
            model_server.abort_qwen_model_request_acquisition(
                request_id,
                acquisition_intent_ref=owner["acquisition_intent_ref"],
                runtime_owner_ref=owner["runtime_owner_ref"],
                reason="cancelled",
            )
        expected_state = "materialization_possible"

    ledger = model_server._load_qwen_model_request_materialization_ledger(request_id)
    assert ledger["state"] == expected_state
    assert ledger["revision"] == 1
    assert ledger["predecessor_content_sha256"] is not None


def test_materialization_ledger_concurrent_cancel_launch_race_persists_one_head(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-concurrent-linearization"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    gate = Event()
    results = []

    def abort():
        gate.wait(timeout=1.0)
        try:
            results.append(("abort", model_server.abort_qwen_model_request_acquisition(
                request_id,
                acquisition_intent_ref=owner["acquisition_intent_ref"],
                runtime_owner_ref=owner["runtime_owner_ref"],
                reason="cancelled",
            )))
        except RuntimeError as error:
            results.append(("abort_error", str(error)))

    def launch():
        gate.wait(timeout=1.0)
        try:
            results.append(("launch", model_server._transition_qwen_model_request_materialization(
                request_id, transition="launch"
            )))
        except RuntimeError as error:
            results.append(("launch_error", str(error)))

    threads = [Thread(target=abort), Thread(target=launch)]
    for thread in threads:
        thread.start()
    gate.set()
    for thread in threads:
        thread.join(timeout=2.0)

    ledger = model_server._load_qwen_model_request_materialization_ledger(request_id)
    assert len(results) == 2
    assert ledger["revision"] == 1
    assert ledger["state"] in {"aborted_never_materialized", "materialization_possible"}
    assert len([name for name, _ in results if not name.endswith("_error")]) == 1


@pytest.mark.parametrize("lifetime_seconds", [0.05, 5.0])
def test_benchmark_provider_cleanup_process_before_lease_remains_pending(
    tmp_path,
    monkeypatch,
    lifetime_seconds,
) -> None:
    request_id = f"benchmark-process-before-lease-{lifetime_seconds}"
    _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    model_server._transition_qwen_model_request_materialization(
        request_id, transition="launch"
    )
    with subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({lifetime_seconds})"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as process:
        try:
            if lifetime_seconds < 1:
                process.wait(timeout=2.0)
            observation = model_server.observe_qwen_model_request_cleanup(request_id)
            assert observation["status"] == "cleanup_pending"
            assert observation["outcome"] == "indeterminate"
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2.0)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "missing_intent",
        "legacy",
        "edited",
        "wrong_owner",
        "wrong_predecessor",
        "revision_gap",
        "extra_field",
        "stale_rollback",
        "missing_winner",
    ],
)
def test_materialization_ledger_invalid_evidence_remains_pending(
    tmp_path,
    monkeypatch,
    mutation,
) -> None:
    request_id = f"benchmark-invalid-ledger-{mutation}"
    _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    path = model_server._qwen_materialization_ledger_path(request_id)
    if mutation in {"stale_rollback", "missing_winner"}:
        model_server._transition_qwen_model_request_materialization(
            request_id, transition="launch"
        )
    if mutation == "missing":
        path.unlink()
    elif mutation == "missing_intent":
        model_server._qwen_acquisition_artifact_paths(request_id)["intent"].unlink()
    elif mutation == "legacy":
        path.write_text(
            json.dumps({"contract_version": "qwen_model_request_materialization_ledger_v0"}),
            encoding="utf-8",
        )
    elif mutation == "stale_rollback":
        revision_zero = model_server._qwen_acquisition_artifact_paths(request_id)[
            "ledger_revision_zero"
        ]
        path.write_bytes(revision_zero.read_bytes())
    elif mutation == "missing_winner":
        model_server._qwen_acquisition_artifact_paths(request_id)["ledger_winner"].unlink()
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.pop("content_sha256")
        if mutation == "edited":
            payload["revision"] = 7
        elif mutation == "wrong_owner":
            payload["runtime_owner_ref"] = {"content_sha256": "f" * 64}
        elif mutation == "wrong_predecessor":
            payload.update(
                revision=1,
                transition="launch",
                state="materialization_possible",
                predecessor_content_sha256="e" * 64,
            )
        elif mutation == "revision_gap":
            payload["revision"] = 2
        else:
            payload["observed_at"] = "forbidden"
        path.write_text(json.dumps(seal_immutable(payload)), encoding="utf-8")

    observation = model_server.observe_qwen_model_request_cleanup(request_id)
    assert observation["status"] == "cleanup_pending"
    assert observation["outcome"] == "indeterminate"


def test_materialization_ledger_launch_dominates_profile_lookup_and_process_creation(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-launch-dominates-provider"
    _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)

    def inspect_then_stop(stage, profile_id=None):
        del stage, profile_id
        ledger = model_server._load_qwen_model_request_materialization_ledger(request_id)
        assert ledger["state"] == "materialization_possible"
        raise RuntimeError("profile-lookup-sentinel")

    monkeypatch.setattr(model_server, "profile_for_stage", inspect_then_stop)
    with pytest.raises(RuntimeError, match="profile-lookup-sentinel"):
        model_server.ensure_and_acquire_qwen_model_lease(
            stage="understanding",
            profile_id=None,
            request_id=request_id,
            wait_seconds=0.1,
        )
    assert model_server.observe_qwen_model_request_cleanup(request_id)["status"] == "cleanup_pending"


def test_materialization_ledger_missing_head_rejects_launch_before_profile_lookup(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-missing-ledger-before-launch"
    _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    model_server._qwen_materialization_ledger_path(request_id).unlink()
    profile_calls = []
    monkeypatch.setattr(
        model_server,
        "profile_for_stage",
        lambda *args, **kwargs: profile_calls.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="artifact|ledger"):
        model_server.ensure_and_acquire_qwen_model_lease(
            stage="understanding",
            profile_id=None,
            request_id=request_id,
            wait_seconds=0.1,
        )
    assert profile_calls == []


def test_qwen_cleanup_sidecar_observer_uses_acquisition_then_lease_lock_order(
    tmp_path,
    monkeypatch,
) -> None:
    from contextlib import contextmanager

    request_id = "benchmark-observer-lock-order"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    _install_benchmark_qwen_abort_primitive(tmp_path, monkeypatch, request_id)
    model_server.abort_qwen_model_request_acquisition(
        request_id,
        acquisition_intent_ref=owner["acquisition_intent_ref"],
        runtime_owner_ref=owner["runtime_owner_ref"],
        reason="cancelled",
    )
    events = []
    acquisition_lock = model_server._qwen_acquisition_lock
    lease_lock = model_server._qwen_lease_lock

    @contextmanager
    def observed_acquisition_lock():
        events.append("acquisition_enter")
        with acquisition_lock():
            yield
        events.append("acquisition_exit")

    @contextmanager
    def observed_lease_lock():
        assert events[-1] == "acquisition_enter"
        events.append("lease_enter")
        with lease_lock():
            yield
        events.append("lease_exit")

    monkeypatch.setattr(model_server, "_qwen_acquisition_lock", observed_acquisition_lock)
    monkeypatch.setattr(model_server, "_qwen_lease_lock", observed_lease_lock)
    receipt = model_server.observe_qwen_model_request_cleanup(request_id)

    assert receipt["outcome"] == "verified_not_acquired"
    assert events == [
        "acquisition_enter",
        "lease_enter",
        "lease_exit",
        "acquisition_exit",
    ]


def test_qwen_cleanup_sidecar_acquired_release_yields_only_exact_process_exited(
    tmp_path,
    monkeypatch,
) -> None:
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    request_id = "benchmark-acquired-release"
    _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    scope_name = process_scope_name(
        {**_HYBRID_LINEAGE, "operation_id": "operation-benchmark-acquired"},
        "qwen",
    )
    scope = WindowsProcessScope(scope_name, create=True)
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    profile = {
        "profile_id": "qwen-benchmark-acquired",
        "endpoint": "http://127.0.0.1:54329/v1/chat/completions",
        "pid_file": str(tmp_path / "qwen-benchmark-acquired.pid"),
    }
    readiness = _server_readiness(
        started=True,
        pid=helper.process_identity["pid"],
        created_ns=helper.process_identity["create_time_ns"],
        base_url="http://127.0.0.1:54329/v1",
    )
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    try:
        lease = model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id=request_id,
            readiness=readiness,
        )
        released = model_server._release_exact_qwen_lease(
            lease,
            reason="controlled-benchmark-release",
        )
        receipt = model_server.observe_qwen_model_request_cleanup(request_id)
        replay = model_server.observe_qwen_model_request_cleanup(request_id)
        assert released["server_termination"] == "verified_exact_process_exited"
        assert receipt == replay
        assert receipt["outcome"] == "verified_exact_process_exited"
        assert receipt["server_process_identity"] == lease["server_process_identity"]
        assert receipt["release_reason"] == "controlled-benchmark-release"
        assert receipt["no_owned_runtime_observation_ref"] is None
        assert set(receipt) == model_server._QWEN_CLEANUP_RECEIPT_FIELDS
    finally:
        helper.close()
        scope.close()


def test_qwen_cleanup_sidecar_edited_receipt_fails_closed_to_pending(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-edited-cleanup-sidecar"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    _install_benchmark_qwen_abort_primitive(tmp_path, monkeypatch, request_id)
    model_server.abort_qwen_model_request_acquisition(
        request_id,
        acquisition_intent_ref=owner["acquisition_intent_ref"],
        runtime_owner_ref=owner["runtime_owner_ref"],
        reason="cancelled",
    )
    receipt = model_server.observe_qwen_model_request_cleanup(request_id)
    assert receipt["outcome"] == "verified_not_acquired"
    path = model_server._qwen_acquisition_artifact_paths(request_id)["cleanup_receipt"]
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["outcome"] = "verified_exact_process_exited"
    path.write_text(json.dumps(edited), encoding="utf-8")

    assert model_server.observe_qwen_model_request_cleanup(request_id) == {
        "contract_version": "qwen_model_request_cleanup_observation_v1",
        "status": "cleanup_pending",
        "outcome": "indeterminate",
        "model_request_id": request_id,
    }


def _released_benchmark_qwen_owner(tmp_path, monkeypatch, request_id: str):
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    scope_name = process_scope_name(
        {**_HYBRID_LINEAGE, "operation_id": f"operation-{request_id}"},
        "qwen",
    )
    scope = WindowsProcessScope(scope_name, create=True)
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    profile = {
        "profile_id": f"profile-{request_id}",
        "endpoint": "http://127.0.0.1:54330/v1/chat/completions",
        "pid_file": str(tmp_path / f"{request_id}.pid"),
    }
    readiness = _server_readiness(
        started=True,
        pid=helper.process_identity["pid"],
        created_ns=helper.process_identity["create_time_ns"],
        base_url="http://127.0.0.1:54330/v1",
    )
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    try:
        lease = model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id=request_id,
            readiness=readiness,
        )
        model_server._release_exact_qwen_lease(
            lease,
            reason="review-fix-release",
        )
        return lease, helper, scope
    except BaseException:
        helper.close()
        scope.close()
        raise


def test_materialization_ledger_prepare_rejects_reused_finalized_request_id(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-reused-finalized-owner"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen-leases")
    old_lease = {
        **_cleanup_lease(),
        "owner_request_id": request_id,
        "contract_version": "qwen_model_server_lease_v2",
        "server_process_identity": {"pid": 987654, "create_time_ns": 123456789},
    }
    old_result = {
        "status": "released",
        "lease": old_lease,
        "shared_server_retained": False,
        "server_termination": "verified_exact_process_exited",
        "release": {"status": "proven_absent", "identity": None},
        "process_identity": old_lease["server_process_identity"],
    }
    model_server._write_qwen_owner_tombstone(
        old_lease,
        result=old_result,
        finalization_token="old-finalization",
    )

    with pytest.raises(RuntimeError, match="finalized|ownership|request"):
        model_server.prepare_qwen_model_request_acquisition_owner(
            request_id,
            runtime_owner_ref=_benchmark_qwen_runtime_owner(request_id),
        )


def test_qwen_cleanup_sidecar_old_finalized_owner_cannot_terminalize_new_launch_cut(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-old-owner-new-launch-cut"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen-leases")
    owner = _benchmark_qwen_runtime_owner(request_id)
    prepared = model_server.prepare_qwen_model_request_acquisition_owner(
        request_id,
        runtime_owner_ref=owner,
    )
    model_server._transition_qwen_model_request_materialization(
        request_id, transition="launch"
    )
    old_lease = {
        **_cleanup_lease(),
        "owner_request_id": request_id,
        "contract_version": "qwen_model_server_lease_v2",
        "server_process_identity": {"pid": 987655, "create_time_ns": 123456790},
    }
    old_result = {
        "status": "released",
        "lease": old_lease,
        "shared_server_retained": False,
        "server_termination": "verified_exact_process_exited",
        "release": {"status": "proven_absent", "identity": None},
        "process_identity": old_lease["server_process_identity"],
        "hybrid_process_scope_acquisition": {
            "scope_name": "old-scope",
            "member_pids": [old_lease["server_process_identity"]["pid"]],
        },
        "hybrid_process_scope_cleanup": {
            "scope_name": "old-scope",
            "authority": "windows_job_object",
            "cleanup_status": "verified",
            "member_pids_after": [],
            "member_identities_after": [],
            "active_listeners_after": [],
            "pid_file_after": None,
            "stable_zero_observations": 3,
        },
    }
    model_server._write_qwen_owner_tombstone(
        old_lease,
        result=old_result,
        finalization_token="old-finalization",
    )
    release_observation = seal_immutable(
        {
            "contract_version": "qwen_model_request_exact_release_observation_v1",
            "model_request_id": request_id,
            "lease_ref": model_server._qwen_content_ref(old_lease),
            "finalization_token": "old-finalization",
            "release_reason": "old-release",
            "release_result_ref": model_server._qwen_content_ref(
                seal_immutable(old_result)
            ),
        }
    )
    model_server._write_qwen_acquisition_artifact(
        model_server._qwen_acquisition_artifact_paths(request_id)["release_observation"],
        release_observation,
    )

    observation = model_server.observe_qwen_model_request_cleanup(request_id)
    assert prepared["runtime_owner_ref"] == owner
    assert observation["status"] == "cleanup_pending"
    assert observation["outcome"] == "indeterminate"


def test_qwen_cleanup_sidecar_not_acquired_ignores_unrelated_hybrid_context(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-abort-unrelated-hybrid-context"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    monkeypatch.setenv(
        "AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH",
        str(tmp_path / "missing-runtime.json"),
    )
    monkeypatch.delenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", raising=False)
    monkeypatch.delenv("AGENT_GUI_HYBRID_LINEAGE_JSON", raising=False)
    model_server.abort_qwen_model_request_acquisition(
        request_id,
        acquisition_intent_ref=owner["acquisition_intent_ref"],
        runtime_owner_ref=owner["runtime_owner_ref"],
        reason="cancelled",
    )

    ledger = model_server._load_qwen_model_request_materialization_ledger(request_id)
    observation = model_server.observe_qwen_model_request_cleanup(request_id)
    assert ledger["state"] == "aborted_never_materialized"
    assert ledger["revision"] == 1
    assert observation["outcome"] == "verified_not_acquired"
    assert observation["scope_stable_zero_ref"] is None
    assert observation["listener_stable_zero_ref"] is None


@pytest.mark.parametrize("completed_writes", [1, 2, 3, 4])
def test_materialization_ledger_prepare_recovers_exact_deterministic_write_prefix(
    tmp_path,
    monkeypatch,
    completed_writes,
) -> None:
    request_id = f"benchmark-prepare-write-cut-{completed_writes}"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen-leases")
    runtime_owner = _benchmark_qwen_runtime_owner(request_id)
    original_write = model_server._write_qwen_acquisition_artifact
    writes = []

    def fail_after_write(path, document):
        original_write(path, document)
        writes.append((path.name, path.read_bytes()))
        if len(writes) == completed_writes:
            raise OSError(f"injected-after-write-{completed_writes}")

    monkeypatch.setattr(
        model_server,
        "_write_qwen_acquisition_artifact",
        fail_after_write,
    )
    with pytest.raises(OSError, match=f"injected-after-write-{completed_writes}"):
        model_server.prepare_qwen_model_request_acquisition_owner(
            request_id,
            runtime_owner_ref=runtime_owner,
        )
    persisted_prefix = {name: raw for name, raw in writes}
    monkeypatch.setattr(
        model_server,
        "_write_qwen_acquisition_artifact",
        original_write,
    )

    code = (
        "import json,sys; from pathlib import Path; "
        "from app.core import model_server; "
        "model_server.MODEL_SERVER_LEASE_DIR=Path(sys.argv[1]); "
        "owner=json.loads(sys.argv[2]); "
        "model_server.prepare_qwen_model_request_acquisition_owner("
        "sys.argv[3],runtime_owner_ref=owner)"
    )
    arguments = [
        sys.executable,
        "-c",
        code,
        str(tmp_path / "qwen-leases"),
        json.dumps(runtime_owner, sort_keys=True, separators=(",", ":")),
        request_id,
    ]
    recovered = subprocess.run(
        arguments,
        cwd=model_server.ROOT_DIR,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    paths = model_server._qwen_acquisition_artifact_paths(request_id)
    assert all(paths[key].exists() for key in ("intent", "owner", "ledger_revision_zero", "ledger"))
    for name, raw in persisted_prefix.items():
        matching = [path for path in paths.values() if path.name == name]
        assert len(matching) == 1
        assert matching[0].read_bytes() == raw
    first_snapshot = {
        path.relative_to(tmp_path / "qwen-leases").as_posix(): path.read_bytes()
        for path in (tmp_path / "qwen-leases").rglob("*")
        if path.is_file() and not path.name.endswith(".lock")
    }
    replay = subprocess.run(
        arguments,
        cwd=model_server.ROOT_DIR,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert replay.returncode == 0, replay.stdout + replay.stderr
    second_snapshot = {
        path.relative_to(tmp_path / "qwen-leases").as_posix(): path.read_bytes()
        for path in (tmp_path / "qwen-leases").rglob("*")
        if path.is_file() and not path.name.endswith(".lock")
    }
    assert second_snapshot == first_snapshot


def test_materialization_ledger_direct_acquire_dominates_materialization_probe(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-direct-acquire-dominance"
    _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)

    def inspect_then_stop(profile, readiness):
        del profile, readiness
        ledger = model_server._load_qwen_model_request_materialization_ledger(
            request_id
        )
        assert ledger["state"] == "materialization_possible"
        raise RuntimeError("direct-materialization-sentinel")

    monkeypatch.setattr(model_server, "_qwen_server_incarnation", inspect_then_stop)
    with pytest.raises(RuntimeError, match="direct-materialization-sentinel"):
        model_server.acquire_qwen_model_lease(
            profile={"profile_id": "direct-profile"},
            request_id=request_id,
            readiness={},
        )


def test_qwen_cleanup_sidecar_missing_release_observation_remains_pending(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-missing-release-observation"
    _, helper, scope = _released_benchmark_qwen_owner(
        tmp_path, monkeypatch, request_id
    )
    try:
        model_server._qwen_acquisition_artifact_paths(request_id)[
            "release_observation"
        ].unlink()
        observation = model_server.observe_qwen_model_request_cleanup(request_id)
        assert observation["status"] == "cleanup_pending"
        assert observation["outcome"] == "indeterminate"
    finally:
        helper.close()
        scope.close()


def test_qwen_cleanup_sidecar_pid_reuse_observation_remains_pending(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-pid-reuse-observation"
    lease, helper, scope = _released_benchmark_qwen_owner(
        tmp_path, monkeypatch, request_id
    )
    try:
        monkeypatch.setattr(
            model_server,
            "_probe_exact_qwen_process",
            lambda identity: {
                "status": "proven_absent",
                "identity": {
                    "pid": identity["pid"],
                    "create_time_ns": lease["server_process_identity"]["create_time_ns"]
                    + 1,
                },
                "reason": "pid_reused",
            },
        )
        observation = model_server.observe_qwen_model_request_cleanup(request_id)
        assert observation["status"] == "cleanup_pending"
        assert observation["outcome"] == "indeterminate"
    finally:
        helper.close()
        scope.close()


def test_qwen_cleanup_sidecar_real_scope_listener_cleanup_without_lease_stays_pending(
    tmp_path,
    monkeypatch,
) -> None:
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        observe_process_scope_cleanup,
        process_scope_name,
        spawn_process_in_scope,
    )

    request_id = "benchmark-real-scope-listener-no-lease"
    _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    model_server._transition_qwen_model_request_materialization(
        request_id, transition="launch"
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = int(reservation.getsockname()[1])
    lineage = {**_HYBRID_LINEAGE, "operation_id": f"operation-{request_id}"}
    scope_name = process_scope_name(lineage, "qwen")
    scope = WindowsProcessScope(scope_name, create=True)
    script = (
        "import socket,time; s=socket.socket(); "
        f"s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(30)"
    )
    helper = spawn_process_in_scope(
        [sys.executable, "-c", script],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    try:
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if model_server._listening_pids_for_port(port):
                break
            time.sleep(0.02)
        assert model_server._listening_pids_for_port(port)
        cleanup = observe_process_scope_cleanup(
            scope_name,
            terminate=True,
            listener_ports=[port],
            stable_zero_observations=3,
        )
        assert cleanup["cleanup_status"] == "verified"
        observation = model_server.observe_qwen_model_request_cleanup(request_id)
        assert observation["status"] == "cleanup_pending"
        assert observation["outcome"] == "indeterminate"
    finally:
        helper.close()
        scope.close()


def test_qwen_cleanup_sidecar_requires_current_acquisition_lease_binding(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-missing-current-lease-binding"
    lease, helper, scope = _released_benchmark_qwen_owner(
        tmp_path, monkeypatch, request_id
    )
    try:
        binding_path = (
            model_server._qwen_acquisition_artifact_directory(request_id)
            / "acquisition-lease-binding.json"
        )
        binding_path.unlink(missing_ok=True)
        observation = model_server.observe_qwen_model_request_cleanup(request_id)
        assert lease["owner_request_id"] == request_id
        assert observation["status"] == "cleanup_pending"
        assert observation["outcome"] == "indeterminate"
    finally:
        helper.close()
        scope.close()


def test_qwen_acquire_recovers_lease_state_to_binding_write_cut_without_duplication(
    tmp_path,
    monkeypatch,
) -> None:
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    request_id = "benchmark-binding-write-cut"
    _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    scope_name = process_scope_name(
        {**_HYBRID_LINEAGE, "operation_id": f"operation-{request_id}"},
        "qwen",
    )
    scope = WindowsProcessScope(scope_name, create=True)
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    profile = {
        "profile_id": "profile-binding-write-cut",
        "endpoint": "http://127.0.0.1:54333/v1/chat/completions",
        "pid_file": str(tmp_path / "binding-write-cut.pid"),
    }
    readiness = _server_readiness(
        started=True,
        pid=helper.process_identity["pid"],
        created_ns=helper.process_identity["create_time_ns"],
        base_url="http://127.0.0.1:54333/v1",
    )
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    original_binding_write = model_server._write_qwen_acquisition_lease_binding_locked
    monkeypatch.setattr(
        model_server,
        "_write_qwen_acquisition_lease_binding_locked",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("injected-binding-write-cut")
        ),
    )
    try:
        with pytest.raises(OSError, match="injected-binding-write-cut"):
            model_server.acquire_qwen_model_lease(
                profile=profile,
                request_id=request_id,
                readiness=readiness,
            )
        active = model_server._find_qwen_lease_by_owner(request_id)
        assert active is not None
        first_lease = active[1]
        monkeypatch.setattr(
            model_server,
            "_write_qwen_acquisition_lease_binding_locked",
            original_binding_write,
        )
        recovered = model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id=request_id,
            readiness=readiness,
        )
        assert recovered == first_lease
        with model_server._qwen_lease_lock():
            assert len(model_server._find_qwen_owner_leases_locked(request_id)) == 1
        model_server._release_exact_qwen_lease(
            recovered,
            reason="binding-write-cut-recovered",
        )
        receipt = model_server.observe_qwen_model_request_cleanup(request_id)
        assert receipt["outcome"] == "verified_exact_process_exited"
    finally:
        helper.close()
        scope.close()


@pytest.mark.parametrize(
    "mutation",
    ["outer_profile", "embedded_profile", "incarnation", "socket", "job", "process"],
)
def test_qwen_cleanup_sidecar_resealed_parent_tamper_remains_pending(
    tmp_path,
    monkeypatch,
    mutation,
) -> None:
    request_id = f"benchmark-resealed-parent-{mutation}"
    lease, helper, scope = _released_benchmark_qwen_owner(
        tmp_path, monkeypatch, request_id
    )
    try:
        tombstone_path = model_server._qwen_owner_tombstone_path(request_id)
        tombstone = json.loads(tombstone_path.read_text(encoding="utf-8"))
        tombstone.pop("content_sha256")
        release_result = tombstone["release_result"]
        embedded_lease = release_result["lease"]
        if mutation == "outer_profile":
            tombstone["profile_id"] = "wrong-profile"
        elif mutation == "embedded_profile":
            embedded_lease["profile_id"] = "wrong-profile"
            embedded_lease["profile_sha256"] = "d" * 64
            tombstone["profile_id"] = "wrong-profile"
        elif mutation == "incarnation":
            embedded_lease["incarnation_id"] = "wrong-incarnation"
            tombstone["incarnation_id"] = "wrong-incarnation"
        elif mutation == "socket":
            embedded_lease["server_base_url"] = "http://127.0.0.1:54331/v1"
        elif mutation == "job":
            release_result["hybrid_process_scope_acquisition"]["scope_name"] = "wrong-job"
            release_result["hybrid_process_scope_cleanup"]["scope_name"] = "wrong-job"
        else:
            replacement = {"pid": 987656, "create_time_ns": 123456791}
            embedded_lease["server_process_identity"] = replacement
            release_result["process_identity"] = replacement
            release_result["hybrid_process_scope_acquisition"]["member_pids"] = [
                replacement["pid"]
            ]
        tombstone_path.write_text(
            json.dumps(seal_immutable(tombstone), sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        release_path = model_server._qwen_acquisition_artifact_paths(request_id)[
            "release_observation"
        ]
        release_observation = json.loads(release_path.read_text(encoding="utf-8"))
        release_observation.pop("content_sha256")
        release_observation["lease_ref"] = model_server._qwen_content_ref(
            embedded_lease
        )
        release_observation["release_result_ref"] = model_server._qwen_content_ref(
            seal_immutable(release_result)
        )
        release_path.write_text(
            json.dumps(
                seal_immutable(release_observation),
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

        observation = model_server.observe_qwen_model_request_cleanup(request_id)
        assert lease["owner_request_id"] == request_id
        assert observation["status"] == "cleanup_pending"
        assert observation["outcome"] == "indeterminate"
    finally:
        helper.close()
        scope.close()


@pytest.mark.parametrize("mutation", ["lease_state_ref", "nested_release"])
def test_qwen_cleanup_sidecar_adversarial_parent_substitution_remains_pending(
    tmp_path,
    monkeypatch,
    mutation,
) -> None:
    request_id = f"benchmark-adversarial-parent-{mutation}"
    _, helper, scope = _released_benchmark_qwen_owner(
        tmp_path, monkeypatch, request_id
    )
    try:
        paths = model_server._qwen_acquisition_artifact_paths(request_id)
        if mutation == "lease_state_ref":
            binding = json.loads(paths["lease_binding"].read_text(encoding="utf-8"))
            binding.pop("content_sha256")
            binding["lease_state_ref"] = {"content_sha256": "e" * 64}
            paths["lease_binding"].write_text(
                json.dumps(
                    seal_immutable(binding),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        else:
            tombstone_path = model_server._qwen_owner_tombstone_path(request_id)
            tombstone = json.loads(tombstone_path.read_text(encoding="utf-8"))
            tombstone.pop("content_sha256")
            tombstone["release_result"]["release"]["forged_parent"] = True
            tombstone_path.write_text(
                json.dumps(
                    seal_immutable(tombstone),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            release_observation = json.loads(
                paths["release_observation"].read_text(encoding="utf-8")
            )
            release_observation.pop("content_sha256")
            release_observation["release_result_ref"] = model_server._qwen_content_ref(
                seal_immutable(tombstone["release_result"])
            )
            paths["release_observation"].write_text(
                json.dumps(
                    seal_immutable(release_observation),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )

        observation = model_server.observe_qwen_model_request_cleanup(request_id)
        assert observation["status"] == "cleanup_pending"
        assert observation["outcome"] == "indeterminate"
        assert not paths["cleanup_receipt"].exists()
    finally:
        helper.close()
        scope.close()


def test_qwen_cleanup_observer_concurrent_mixed_acquisition_lease_snapshot_is_pending(
    tmp_path,
    monkeypatch,
) -> None:
    current_id = "benchmark-concurrent-snapshot-current"
    other_id = "benchmark-concurrent-snapshot-other"
    _, current_helper, current_scope = _released_benchmark_qwen_owner(
        tmp_path, monkeypatch, current_id
    )
    _, other_helper, other_scope = _released_benchmark_qwen_owner(
        tmp_path, monkeypatch, other_id
    )
    gate = Event()
    proceed = Event()
    observations = []
    original_load = model_server._load_qwen_acquisition_lease_binding

    def gated_load(request_id, *, owner):
        if request_id == current_id:
            gate.set()
            assert proceed.wait(timeout=2.0)
        return original_load(request_id, owner=owner)

    monkeypatch.setattr(
        model_server,
        "_load_qwen_acquisition_lease_binding",
        gated_load,
    )
    observer = Thread(
        target=lambda: observations.append(
            model_server.observe_qwen_model_request_cleanup(current_id)
        )
    )
    try:
        observer.start()
        assert gate.wait(timeout=2.0)
        current_paths = model_server._qwen_acquisition_artifact_paths(current_id)
        other_paths = model_server._qwen_acquisition_artifact_paths(other_id)
        current_binding = json.loads(
            current_paths["lease_binding"].read_text(encoding="utf-8")
        )
        other_binding = json.loads(
            other_paths["lease_binding"].read_text(encoding="utf-8")
        )
        current_binding.pop("content_sha256")
        current_binding["lease_state_ref"] = other_binding["lease_state_ref"]
        current_paths["lease_binding"].write_text(
            json.dumps(
                seal_immutable(current_binding),
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        proceed.set()
        observer.join(timeout=3.0)
        assert not observer.is_alive()
        assert observations == [
            {
                "contract_version": "qwen_model_request_cleanup_observation_v1",
                "status": "cleanup_pending",
                "outcome": "indeterminate",
                "model_request_id": current_id,
            }
        ]
        assert not current_paths["cleanup_receipt"].exists()
    finally:
        proceed.set()
        observer.join(timeout=3.0)
        current_helper.close()
        current_scope.close()
        other_helper.close()
        other_scope.close()


def test_generic_qwen_duplicate_owner_preserves_prior_value_error(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "generic-duplicate-owner"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen-leases")
    monkeypatch.delenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", raising=False)
    helper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    identity = model_server._current_process_identity(helper.pid)
    assert identity is not None
    profile = {
        "profile_id": "generic-duplicate-profile",
        "endpoint": "http://127.0.0.1:54334/v1/chat/completions",
    }
    readiness = _server_readiness(
        started=True,
        pid=identity["pid"],
        created_ns=identity["create_time_ns"],
        base_url="http://127.0.0.1:54334/v1",
    )
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    lease = None
    try:
        lease = model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id=request_id,
            readiness=readiness,
        )
        with pytest.raises(
            ValueError,
            match="^Qwen request already owns a server lease$",
        ):
            model_server.acquire_qwen_model_lease(
                profile=profile,
                request_id=request_id,
                readiness=readiness,
            )
    finally:
        if lease is not None and model_server.qwen_model_lease_is_active(lease):
            model_server._release_exact_qwen_lease(
                lease,
                reason="generic-duplicate-test-cleanup",
            )
        if helper.poll() is None:
            helper.terminate()
            helper.wait(timeout=3.0)


def test_qwen_acquisition_observation_prepared_snapshot_has_exact_refs(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-acquisition-observation-prepared"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    observation = model_server.observe_qwen_model_request_acquisition(
        request_id,
        acquisition_intent_ref=owner["acquisition_intent_ref"],
        runtime_owner_ref=owner["runtime_owner_ref"],
    )
    ledger = model_server._load_qwen_model_request_materialization_ledger(request_id)
    prepared = model_server._load_optional_qwen_sealed_artifact(
        model_server._qwen_acquisition_artifact_paths(request_id)[
            "ledger_revision_zero"
        ]
    )
    assert prepared is not None

    assert observation == seal_immutable(
        {
            "contract_version": "qwen_model_request_acquisition_observation_v1",
            "model_request_id": request_id,
            "acquisition_owner_ref": model_server._qwen_content_ref(owner),
            "acquisition_intent_ref": owner["acquisition_intent_ref"],
            "runtime_owner_ref": owner["runtime_owner_ref"],
            "prepared_materialization_ledger_ref": model_server._qwen_content_ref(
                prepared
            ),
            "materialization_ledger_ref": model_server._qwen_content_ref(ledger),
            "materialization_state": "prepared_never_materialized",
            "materialization_revision": 0,
        }
    )
    assert set(observation) == {
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


def test_qwen_acquisition_observation_is_byte_identical_after_fresh_process_reload(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-acquisition-observation-reload"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    expected = model_server.observe_qwen_model_request_acquisition(
        request_id,
        acquisition_intent_ref=owner["acquisition_intent_ref"],
        runtime_owner_ref=owner["runtime_owner_ref"],
    )
    code = (
        "import json,sys; from pathlib import Path; "
        "from app.core import model_server; "
        "model_server.MODEL_SERVER_LEASE_DIR=Path(sys.argv[1]); "
        "intent=json.loads(sys.argv[3]); owner=json.loads(sys.argv[4]); "
        "value=model_server.observe_qwen_model_request_acquisition("
        "sys.argv[2],acquisition_intent_ref=intent,runtime_owner_ref=owner); "
        "sys.stdout.write(json.dumps(value,sort_keys=True,separators=(',',':')))"
    )
    arguments = [
        sys.executable,
        "-c",
        code,
        str(tmp_path / "qwen-leases"),
        request_id,
        json.dumps(owner["acquisition_intent_ref"], separators=(",", ":")),
        json.dumps(owner["runtime_owner_ref"], separators=(",", ":")),
    ]
    first = subprocess.run(
        arguments,
        cwd=model_server.ROOT_DIR,
        env=os.environ.copy(),
        capture_output=True,
        timeout=15,
    )
    second = subprocess.run(
        arguments,
        cwd=model_server.ROOT_DIR,
        env=os.environ.copy(),
        capture_output=True,
        timeout=15,
    )
    expected_bytes = json.dumps(
        expected,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    assert first.stdout == second.stdout == expected_bytes


@pytest.mark.parametrize(
    ("transition", "expected_state"),
    [
        ("launch", "materialization_possible"),
        ("abort", "aborted_never_materialized"),
    ],
)
def test_qwen_acquisition_observation_tracks_exact_current_transition(
    tmp_path,
    monkeypatch,
    transition,
    expected_state,
) -> None:
    request_id = f"benchmark-acquisition-observation-{transition}"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    before = model_server.observe_qwen_model_request_acquisition(
        request_id,
        acquisition_intent_ref=owner["acquisition_intent_ref"],
        runtime_owner_ref=owner["runtime_owner_ref"],
    )
    head = model_server._transition_qwen_model_request_materialization(
        request_id,
        transition=transition,
    )
    after = model_server.observe_qwen_model_request_acquisition(
        request_id,
        acquisition_intent_ref=owner["acquisition_intent_ref"],
        runtime_owner_ref=owner["runtime_owner_ref"],
    )

    assert head is not None
    assert after["materialization_state"] == expected_state
    assert after["materialization_revision"] == 1
    assert after["materialization_ledger_ref"] == model_server._qwen_content_ref(head)
    assert after["materialization_ledger_ref"] != before["materialization_ledger_ref"]
    assert (
        before["prepared_materialization_ledger_ref"]
        == before["materialization_ledger_ref"]
    )
    assert (
        after["prepared_materialization_ledger_ref"]
        == before["prepared_materialization_ledger_ref"]
    )
    assert (
        after["prepared_materialization_ledger_ref"]
        != after["materialization_ledger_ref"]
    )
    assert after["acquisition_owner_ref"] == before["acquisition_owner_ref"]
    assert after["acquisition_intent_ref"] == before["acquisition_intent_ref"]
    assert after["runtime_owner_ref"] == before["runtime_owner_ref"]


@pytest.mark.parametrize(
    "substitution",
    ["request", "intent", "owner"],
)
def test_qwen_acquisition_observation_rejects_identity_substitution(
    tmp_path,
    monkeypatch,
    substitution,
) -> None:
    request_id = f"benchmark-acquisition-substitution-{substitution}"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    observed_request_id = request_id
    intent_ref = owner["acquisition_intent_ref"]
    runtime_owner = owner["runtime_owner_ref"]
    if substitution == "request":
        observed_request_id = f"{request_id}-other"
    elif substitution == "intent":
        intent_ref = {"content_sha256": "f" * 64}
    else:
        changed_owner = deepcopy(runtime_owner)
        changed_owner.pop("content_sha256")
        changed_owner["worker_id"] = f"worker-{request_id}-substituted"
        runtime_owner = seal_immutable(changed_owner)

    with pytest.raises((RuntimeError, ValueError)):
        model_server.observe_qwen_model_request_acquisition(
            observed_request_id,
            acquisition_intent_ref=intent_ref,
            runtime_owner_ref=runtime_owner,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_intent",
        "legacy_owner",
        "missing_history",
        "corrupt_history",
        "wrong_history",
        "wrong_predecessor",
        "mixed_head",
    ],
)
def test_qwen_acquisition_observation_rejects_incoherent_persisted_lineage(
    tmp_path,
    monkeypatch,
    mutation,
) -> None:
    request_id = f"benchmark-acquisition-lineage-{mutation}"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    paths = model_server._qwen_acquisition_artifact_paths(request_id)
    if mutation == "missing_intent":
        paths["intent"].unlink()
    elif mutation == "legacy_owner":
        persisted_owner = json.loads(paths["owner"].read_text(encoding="utf-8"))
        persisted_owner.pop("content_sha256")
        persisted_owner["contract_version"] = "benchmark_provider_acquisition_owner_v0"
        paths["owner"].write_text(
            json.dumps(seal_immutable(persisted_owner)),
            encoding="utf-8",
        )
    elif mutation == "missing_history":
        paths["ledger_revision_zero"].unlink()
    elif mutation == "corrupt_history":
        paths["ledger_revision_zero"].write_bytes(b"{corrupt")
    elif mutation == "wrong_history":
        history = json.loads(
            paths["ledger_revision_zero"].read_text(encoding="utf-8")
        )
        history.pop("content_sha256")
        changed_runtime_owner = deepcopy(owner["runtime_owner_ref"])
        changed_runtime_owner.pop("content_sha256")
        changed_runtime_owner["worker_id"] = f"worker-{request_id}-drifted"
        history["runtime_owner_ref"] = seal_immutable(changed_runtime_owner)
        paths["ledger_revision_zero"].write_text(
            json.dumps(seal_immutable(history)),
            encoding="utf-8",
        )
    else:
        model_server._transition_qwen_model_request_materialization(
            request_id,
            transition="launch",
        )
        if mutation == "wrong_predecessor":
            head = json.loads(paths["ledger"].read_text(encoding="utf-8"))
            head.pop("content_sha256")
            head["predecessor_content_sha256"] = "e" * 64
            head = seal_immutable(head)
            paths["ledger"].write_text(json.dumps(head), encoding="utf-8")
            paths["ledger_winner"].write_text(json.dumps(head), encoding="utf-8")
        else:
            paths["ledger"].write_bytes(paths["ledger_revision_zero"].read_bytes())

    with pytest.raises((RuntimeError, ValueError)):
        model_server.observe_qwen_model_request_acquisition(
            request_id,
            acquisition_intent_ref=owner["acquisition_intent_ref"],
            runtime_owner_ref=owner["runtime_owner_ref"],
        )


def test_qwen_acquisition_observation_has_zero_provider_or_resource_side_effect(
    tmp_path,
    monkeypatch,
) -> None:
    request_id = "benchmark-acquisition-observation-zero-side-effect"
    owner = _prepare_benchmark_qwen_owner(tmp_path, monkeypatch, request_id)
    root = tmp_path / "qwen-leases"
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    forbidden = []

    def reject(name):
        def fail(*args, **kwargs):
            forbidden.append((name, args, kwargs))
            raise AssertionError(f"observation reached side effect: {name}")

        return fail

    for name in (
        "profile_for_stage",
        "_ensure_model_server_for_profile",
        "_qwen_server_incarnation",
        "_write_qwen_acquisition_artifact",
        "_qwen_lease_lock",
    ):
        monkeypatch.setattr(model_server, name, reject(name))

    observation = model_server.observe_qwen_model_request_acquisition(
        request_id,
        acquisition_intent_ref=owner["acquisition_intent_ref"],
        runtime_owner_ref=owner["runtime_owner_ref"],
    )
    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert observation["materialization_state"] == "prepared_never_materialized"
    assert before == after
    assert forbidden == []
