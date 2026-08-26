from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest

from app.learn.hybrid.windows_process_scope import (
    HybridProcessScopeError,
    WindowsProcessScope,
    assign_exact_process_identity_to_scope,
    benchmark_worker_controller_mutex_name_v1,
    benchmark_worker_scope_name_v1,
    observe_process_scope_cleanup,
    process_scope_name,
    spawn_process_in_scope,
    windows_process_scope_available,
)


pytestmark = pytest.mark.skipif(
    not windows_process_scope_available(),
    reason="Windows Job Object authority is unavailable",
)


def _lineage(index: int) -> dict:
    return {
        "run_id": f"run-job-{index}",
        "workflow_revision": index,
        "operation_id": f"operation-job-{index}",
        "stage": "screen_understanding",
        "stage_execution_id": f"execution-job-{index}",
    }


def test_exact_process_identity_to_scope_assigns_exact_singleton() -> None:
    scope_name = benchmark_worker_scope_name_v1(
        authority_kind="test_only",
        run_id="run-exact",
        stage="screen_understanding",
        operation_id="operation-exact",
        worker_id="worker-exact",
        payload_sha256="a" * 64,
        execution_nonce="b" * 32,
    )
    scope = WindowsProcessScope(scope_name, create=True)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0),
    )
    identity = {
        "pid": child.pid,
        "create_time_ns": int(
            round(psutil.Process(child.pid).create_time() * 1_000_000_000)
        ),
    }
    try:
        observation = assign_exact_process_identity_to_scope(
            scope_name=scope_name,
            process_identity=identity,
        )
        assert set(observation) == {
            "contract_version",
            "scope_name",
            "process_identity",
            "observed_member_identities",
            "job_policy",
            "temporary_process_handle_close",
            "temporary_job_handle_close",
            "content_sha256",
        }
        assert observation["process_identity"] == identity
        assert observation["observed_member_identities"] == [identity]
        assert observation["job_policy"] == {
            "kill_on_job_close": True,
            "breakaway_ok": False,
            "silent_breakaway_ok": False,
            "owner_handle_authority": "registry_parent",
        }
    finally:
        try:
            scope.terminate()
        finally:
            scope.close()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def test_exact_process_identity_to_scope_rejects_wrong_incarnation() -> None:
    scope_name = benchmark_worker_scope_name_v1(
        authority_kind="test_only",
        run_id="run-exact-wrong",
        stage="screen_understanding",
        operation_id="operation-exact-wrong",
        worker_id="worker-exact-wrong",
        payload_sha256="c" * 64,
        execution_nonce="d" * 32,
    )
    scope = WindowsProcessScope(scope_name, create=True)
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0),
    )
    try:
        wrong = {
            "pid": child.pid,
            "create_time_ns": int(
                round(psutil.Process(child.pid).create_time() * 1_000_000_000)
            )
            + 1,
        }
        with pytest.raises(HybridProcessScopeError, match="incarnation"):
            assign_exact_process_identity_to_scope(
                scope_name=scope_name,
                process_identity=wrong,
            )
        assert scope.pids() == []
    finally:
        child.terminate()
        child.wait(timeout=5)
        scope.close()


def test_exact_process_identity_to_scope_namespaces_are_disjoint_and_canonical() -> None:
    production = benchmark_worker_scope_name_v1(
        authority_kind="production_workflow_service",
        run_id="run-name",
        stage="screen_understanding",
        operation_id="operation-name",
        worker_id="worker-name",
        payload_sha256="e" * 64,
        execution_nonce="f" * 32,
    )
    test = benchmark_worker_scope_name_v1(
        authority_kind="test_only",
        run_id="run-name",
        stage="screen_understanding",
        operation_id="operation-name",
        worker_id="worker-name",
        payload_sha256="e" * 64,
        execution_nonce="f" * 32,
    )
    mutex = benchmark_worker_controller_mutex_name_v1(
        authority_kind="test_only",
        run_id="run-name",
        stage="screen_understanding",
        operation_id="operation-name",
    )
    assert production.startswith("Local\\AgentGuiBenchmarkWorker-")
    assert test.startswith("Local\\AgentGuiBenchmarkWorkerTest-")
    assert mutex.startswith("Local\\AgentGuiBenchmarkWorkerControllerTest-")
    assert len({production, test, mutex}) == 3


def _spawn_reparenting_helper(tmp_path: Path, index: int):
    scope_name = process_scope_name(_lineage(index), "vista")
    scope = WindowsProcessScope(scope_name, create=True)
    child_pid_path = tmp_path / f"child-{index}.json"
    root_code = (
        "import json,subprocess,sys;"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
        f"open({str(child_pid_path)!r},'w',encoding='utf-8').write(json.dumps({{'pid':p.pid}}))"
    )
    root = spawn_process_in_scope(
        [sys.executable, "-c", root_code],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    root.wait(10)
    root.close()
    deadline = time.monotonic() + 5
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert child_pid_path.exists()
    child_pid = int(json.loads(child_pid_path.read_text(encoding="utf-8"))["pid"])
    return scope, scope_name, child_pid


def test_job_scope_observes_and_kills_child_after_root_exit(tmp_path: Path) -> None:
    scope, scope_name, child_pid = _spawn_reparenting_helper(tmp_path, 1)
    try:
        assert child_pid in scope.pids()
        assert psutil.pid_exists(child_pid)

        cleanup = observe_process_scope_cleanup(
            scope_name,
            terminate=True,
            stable_zero_observations=3,
            interval_seconds=0.01,
        )

        assert cleanup["cleanup_status"] == "verified"
        assert child_pid in cleanup["observed_member_pids_before"]
        assert cleanup["member_pids_after"] == []
        assert cleanup["stable_zero_observations"] >= 3
        assert not psutil.pid_exists(child_pid)
    finally:
        try:
            scope.terminate()
        finally:
            scope.close()


def test_job_scope_repeated_runs_have_zero_membership_leak(tmp_path: Path) -> None:
    for index in range(5):
        scope, scope_name, child_pid = _spawn_reparenting_helper(tmp_path, index + 10)
        try:
            cleanup = observe_process_scope_cleanup(
                scope_name,
                terminate=True,
                stable_zero_observations=3,
                interval_seconds=0.01,
            )
            assert cleanup["cleanup_status"] == "verified"
            assert cleanup["member_pids_after"] == []
            assert not psutil.pid_exists(child_pid)
        finally:
            try:
                scope.terminate()
            finally:
                scope.close()


def test_closing_last_job_handle_kills_owned_helper(tmp_path: Path) -> None:
    scope, scope_name, child_pid = _spawn_reparenting_helper(tmp_path, 99)
    assert child_pid in scope.pids()
    scope.close()
    deadline = time.monotonic() + 5
    while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not psutil.pid_exists(child_pid)
    cleanup = observe_process_scope_cleanup(
        scope_name,
        terminate=False,
        stable_zero_observations=3,
        interval_seconds=0.01,
    )
    assert cleanup["cleanup_status"] == "verified"
    assert cleanup["scope_absent_after_owner_close"] is True


def test_job_scope_rejects_replayed_live_owner_identity() -> None:
    scope_name = process_scope_name(_lineage(101), "qwen")
    scope = WindowsProcessScope(scope_name, create=True)
    try:
        with pytest.raises(HybridProcessScopeError, match="already exists"):
            WindowsProcessScope(scope_name, create=True)
    finally:
        scope.close()


def test_assignment_failure_never_executes_uncontained_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_name = process_scope_name(_lineage(102), "omni")
    marker = tmp_path / "must-not-exist.txt"
    scope = WindowsProcessScope(scope_name, create=True)
    monkeypatch.setattr(
        WindowsProcessScope,
        "assign",
        lambda self, handle: (_ for _ in ()).throw(
            RuntimeError("controlled assignment failure")
        ),
    )
    try:
        with pytest.raises(RuntimeError, match="assignment failure"):
            spawn_process_in_scope(
                [
                    sys.executable,
                    "-c",
                    f"open({str(marker)!r},'w').write('unsafe')",
                ],
                scope_name=scope_name,
                cwd=tmp_path,
            )
    finally:
        scope.close()
    assert marker.exists() is False


def test_scope_name_rejects_noncanonical_provider_or_digest() -> None:
    from app.learn.hybrid.windows_process_scope import validate_process_scope_name

    valid = process_scope_name(_lineage(103), "omni")
    assert validate_process_scope_name(valid) == valid
    for invalid in (
        "Local\\AgentGuiHybrid-other-" + "a" * 64,
        "Local\\AgentGuiHybrid-omni-" + "A" * 64,
        "Local\\AgentGuiHybrid-omni-" + "a" * 63,
        valid + "x",
    ):
        with pytest.raises(ValueError, match="scope name is invalid"):
            validate_process_scope_name(invalid)


def test_scoped_launch_does_not_inherit_unlisted_handle(tmp_path: Path) -> None:
    import msvcrt
    import win32api
    import win32event

    scope_name = process_scope_name(_lineage(104), "omni")
    scope = WindowsProcessScope(scope_name, create=True)
    sentinel = win32event.CreateEvent(None, True, False, None)
    marker = tmp_path / "inherited.txt"
    win32api.SetHandleInformation(
        sentinel,
        1,
        1,
    )
    code = (
        "import ctypes,sys;"
        "k=ctypes.WinDLL('kernel32',use_last_error=True);"
        "ok=k.GetHandleInformation(int(sys.argv[1]),ctypes.byref(ctypes.c_ulong()));"
        "open(sys.argv[2],'w').write('inherited') if ok else None"
    )
    try:
        with spawn_process_in_scope(
            [sys.executable, "-c", code, str(int(sentinel)), str(marker)],
            scope_name=scope_name,
            cwd=tmp_path,
        ) as child:
            assert child.wait(10) == 0
        assert marker.exists() is False
    finally:
        win32api.CloseHandle(sentinel)
        scope.close()


def test_scoped_launch_preserves_stdio_inheritability_and_closes_handle(
    tmp_path: Path,
) -> None:
    import msvcrt

    scope_name = process_scope_name(_lineage(105), "qwen")
    scope = WindowsProcessScope(scope_name, create=True)
    output_path = tmp_path / "stdio.txt"
    with output_path.open("wb", buffering=0) as output:
        handle = msvcrt.get_osfhandle(output.fileno())
        before = os.get_handle_inheritable(handle)
        child = spawn_process_in_scope(
            [sys.executable, "-c", "print('ok')"],
            scope_name=scope_name,
            cwd=tmp_path,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        assert child.wait(10) == 0
        assert os.get_handle_inheritable(handle) is before
        child.close()
        child.close()
        with pytest.raises(HybridProcessScopeError, match="process handle is closed"):
            child.poll()
    scope.close()
