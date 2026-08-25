from __future__ import annotations

import json
from pathlib import Path
import sys
import time

import psutil
import pytest

from app.learn.hybrid.windows_process_scope import (
    HybridProcessScopeError,
    WindowsProcessScope,
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
