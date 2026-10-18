"""短时文件占用不能丢失最终回执；重试范围仅为读取或发布。"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import threading
import time
import pytest
from app.core.json_snapshot import read_json_snapshot, write_json_snapshot


@contextmanager
def exclusive_windows_file(path):
    if os.name != 'nt':
        pytest.skip('Windows sharing violation contract')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    closed = False
    def release():
        nonlocal closed
        if not closed:
            assert kernel.CloseHandle(handle)
            closed = True
    try:
        yield release
    finally:
        release()


def test_real_windows_sharing_error_metadata(tmp_path):
    path = tmp_path / 'locked.json'
    write_json_snapshot(path, {'version': 1})
    with exclusive_windows_file(path):
        with pytest.raises(PermissionError) as caught:
            path.read_bytes()
    error = caught.value
    print('real Windows read error:', type(error).__name__, 'errno=', error.errno,
          'winerror=', getattr(error, 'winerror', None))
    assert error.errno == 13 or getattr(error, 'winerror', None) in {5, 32, 33}


def test_transient_windows_sharing_violation_reads_current_snapshot(tmp_path):
    path = tmp_path / 'locked.json'
    write_json_snapshot(path, {'version': 2})
    with exclusive_windows_file(path) as release:
        timer = threading.Timer(.06, release)
        timer.start()
        try:
            assert read_json_snapshot(path) == {'version': 2}
        finally:
            timer.join()


def test_persistent_windows_sharing_violation_is_bounded(tmp_path):
    path = tmp_path / 'locked.json'
    write_json_snapshot(path, {'version': 2})
    with exclusive_windows_file(path):
        started = time.monotonic()
        with pytest.raises(PermissionError) as caught:
            read_json_snapshot(path)
        elapsed = time.monotonic() - started
    assert .45 <= elapsed < 1.5
    assert caught.value.errno == 13


@pytest.mark.parametrize('raw,error', [(b'{', ValueError), (b'\xff', UnicodeError), (None, FileNotFoundError)])
def test_parse_encoding_and_missing_file_are_not_retried(tmp_path, monkeypatch, raw, error):
    path = tmp_path / 'invalid.json'
    if raw is not None:
        path.write_bytes(raw)
    original = Path.read_bytes
    calls = []
    def read(self):
        calls.append(self)
        return original(self)
    monkeypatch.setattr(Path, 'read_bytes', read)
    with pytest.raises(error):
        read_json_snapshot(path)
    assert calls == [path]


def test_unrelated_read_io_failure_is_not_retried(tmp_path, monkeypatch):
    calls = []
    def read(self):
        calls.append(self)
        raise OSError(5, 'unrelated disk failure')
    monkeypatch.setattr(Path, 'read_bytes', read)
    with pytest.raises(OSError, match='unrelated disk failure'):
        read_json_snapshot(tmp_path / 'read.json')
    assert len(calls) == 1


def test_non_windows_permission_error_is_not_retried(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from app.core import json_snapshot
    calls = []
    error = PermissionError(13, 'not a Windows sharing violation')
    def read(self):
        calls.append(self)
        raise error
    monkeypatch.setattr(Path, 'read_bytes', read)
    monkeypatch.setattr(json_snapshot, 'os', SimpleNamespace(name='posix'))
    with pytest.raises(PermissionError) as caught:
        read_json_snapshot(tmp_path / 'read.json')
    assert caught.value is error and len(calls) == 1


def test_original_async_learning_ticket_survives_transient_terminal_file_lock(tmp_path):
    from app.learning_memory.event_store import LearningEventStore
    from scripts.run_local_step_session import flush_learning_receipts
    session = tmp_path / 'new-session'
    (session / 'responses').mkdir(parents=True)
    (session / 'agent-commands').mkdir()
    store = LearningEventStore(session)
    store.control('learning_start', {'scope': 'interface', 'title': 'New synthetic interface'}, 'start')
    for index in (1, 2):
        identity = 'action-' + str(index)
        command = {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': {'goal': 'Open'}}
        ticket = store.prepare(identity, command, None)
        store.reserve(ticket)
        write_json_snapshot(session / 'responses' / (identity + '.json'), {'command': command,
            'learning_binding': ticket, 'result': {'contract_version': 'agent_command.v1', 'command_id': identity,
                                                  'status': 'running'}})
        terminal = session / 'agent-commands' / (identity + '.json')
        write_json_snapshot(terminal, {'contract_version': 'agent_command.v1', 'command_id': identity,
            'status': 'completed', 'result': {'phase': 'returned', 'response': {'success': True,
                'data': {'result': {'execution_path': {'action_executed': True}}}}}})
        pending = {identity: ticket}
        if index == 2:
            with exclusive_windows_file(terminal) as release:
                timer = threading.Timer(.06, release)
                timer.start()
                try:
                    flush_learning_receipts(store, pending)
                finally:
                    timer.join()
        else:
            flush_learning_receipts(store, pending)
        assert not pending
        event = store.control('learning_event', {'event_id': identity}, 'read-' + str(index))['event']
        assert event['action_executed'] is True
        assert event['terminal_receipt']['status'] == 'completed'
    assert store.status()['event_count'] == 2 and store.status()['pending_count'] == 0


def test_reader_does_not_block_atomic_publication(tmp_path):
    path = tmp_path / "report.json"
    write_json_snapshot(path, {"version": 1})
    with ThreadPoolExecutor() as pool:
        with path.open("rb") as reader:
            future = pool.submit(write_json_snapshot, path, {"version": 2})
            time.sleep(.06)
            assert b'"version": 1' in reader.read()
        future.result(timeout=2)
    assert read_json_snapshot(path) == {"version": 2}
    assert list(tmp_path.glob("*.tmp")) == []


def test_unrelated_write_failure_is_not_retried(tmp_path, monkeypatch):
    from pathlib import Path
    calls = []
    def fail(self, target):
        calls.append(1)
        raise OSError("disk failure")
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        write_json_snapshot(tmp_path / "report.json", {"version": 1})
    assert len(calls) == 1
