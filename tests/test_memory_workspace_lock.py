"""记忆库短事务与另一进程的工作区锁竞争。"""
import errno
import multiprocessing
import os
import time

import pytest

from app.learning_memory.workspace import MemoryWorkspace


def _hold_workspace(root, acquired, release):
    with MemoryWorkspace(root):
        acquired.set()
        release.wait(5)


def _holder(root):
    context = multiprocessing.get_context("spawn")
    acquired, release = context.Event(), context.Event()
    process = context.Process(target=_hold_workspace, args=(root, acquired, release))
    process.start()
    assert acquired.wait(5), "holder did not acquire the workspace lock"
    return process, release


def _finish_holder(process, release):
    release.set()
    process.join(5)
    if process.is_alive():
        process.terminate()
        process.join(5)
    assert process.exitcode == 0


def test_memory_workspace_waits_for_other_short_transaction(tmp_path, monkeypatch):
    monkeypatch.setattr("app.learning_memory.workspace._LOCK_WAIT_SECONDS", 1.0, raising=False)
    process, release = _holder(tmp_path)
    try:
        from threading import Timer
        timer = Timer(0.15, release.set)
        timer.start()
        try:
            with MemoryWorkspace(tmp_path) as library:
                assert library._workspace_root.is_dir()
        finally:
            timer.join(1)
    finally:
        _finish_holder(process, release)


def test_memory_workspace_times_out_without_entering_transaction(tmp_path, monkeypatch):
    monkeypatch.setattr("app.learning_memory.workspace._LOCK_WAIT_SECONDS", 0.1, raising=False)
    process, release = _holder(tmp_path)
    entered = False
    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="已占用该工作区"):
            with MemoryWorkspace(tmp_path):
                entered = True
        assert time.monotonic() - started >= 0.08
        assert entered is False
    finally:
        _finish_holder(process, release)
    with MemoryWorkspace(tmp_path):
        pass


@pytest.mark.skipif(os.name != "nt", reason="Windows msvcrt lock error contract")
def test_memory_workspace_unrelated_lock_error_is_immediate(tmp_path, monkeypatch):
    import msvcrt
    attempts = []
    def invalid_lock(*args):
        attempts.append(args)
        raise OSError(errno.EINVAL, "invalid lock")
    monkeypatch.setattr(msvcrt, "locking", invalid_lock)
    monkeypatch.setattr("app.learning_memory.workspace.sleep",
                        lambda *_: pytest.fail("unrelated error must not retry"))
    with pytest.raises(OSError) as caught:
        MemoryWorkspace(tmp_path)
    assert caught.value.errno == errno.EINVAL
    assert len(attempts) == 1
