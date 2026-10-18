import importlib.util
import io
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import instant_admin_worker as worker
import start_instant_mcp_admin as admin

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows AF_PIPE transport")


def test_fixed_server_command_does_not_accept_command_in_ticket(tmp_path):
    ticket = {"data": str(tmp_path / "data"), "model": str(tmp_path / "model"), "allow_input": False,
              "command": "powershell.exe"}
    command = worker.server_command(ticket)
    assert command[:2] == [sys.executable, "-I"]
    assert Path(command[2]) == ROOT / "scripts" / "start_instant_mcp.py"
    assert "powershell.exe" not in command
    assert "--allow-local-input" not in command
    ticket["allow_input"] = True
    assert worker.server_command(ticket)[-1] == "--allow-local-input"


def test_ticket_private_acl_and_same_user_session(tmp_path, monkeypatch):
    import win32security
    sid, session, _ = worker.identity()
    args = types.SimpleNamespace(data_dir=tmp_path / "data", model_directory=tmp_path,
                                 allow_local_input=False, connect_timeout=5)
    path, payload = admin.make_ticket(args, sid, session)
    try:
        descriptor = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
        acl = descriptor.GetSecurityDescriptorDacl()
        assert acl.GetAceCount() == 1
        assert win32security.ConvertSidToStringSid(acl.GetAce(0)[2]) == sid
        monkeypatch.setattr(worker, "identity", lambda: (sid, session, True))
        ticket, auth = worker.load_ticket(path)
        assert len(auth) == 32 and ticket["data"] == str(args.data_dir.resolve())
        monkeypatch.setattr(worker, "identity", lambda: (sid, session + 1, True))
        with pytest.raises(RuntimeError, match="same_user_and_session"):
            worker.load_ticket(path)
        monkeypatch.setattr(worker, "identity", lambda: (sid, session, False))
        with pytest.raises(RuntimeError, match="administrator_token"):
            worker.load_ticket(path)
    finally:
        path.unlink()
        path.parent.rmdir()


def test_ticket_rejects_expired_or_extra_fields(tmp_path, monkeypatch):
    sid, session, _ = worker.identity()
    args = types.SimpleNamespace(data_dir=tmp_path / "data", model_directory=tmp_path,
                                 allow_local_input=True, connect_timeout=5)
    path, payload = admin.make_ticket(args, sid, session)
    monkeypatch.setattr(worker, "identity", lambda: (sid, session, True))
    try:
        payload["expires"] = 0
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(RuntimeError, match="expired"):
            worker.load_ticket(path)
        payload["command"] = "cmd.exe"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="fields"):
            worker.load_ticket(path)
    finally:
        path.unlink()
        path.parent.rmdir()


def test_named_pipe_authenticated_raw_bytes_without_elevation():
    import win32api
    import win32con
    from multiprocessing.connection import Client
    sid, _, _ = worker.identity()
    name = "\\\\.\\pipe\\agent-review-instant-admin-test-" + secrets.token_hex(16)
    secret = secrets.token_bytes(32)
    pipe = admin.LocalPipe(name, sid)
    process = win32api.OpenProcess(win32con.SYNCHRONIZE, False, os.getpid())
    received = []
    failures = []

    def client():
        try:
            with Client(name, family="AF_PIPE", authkey=secret) as connection:
                connection.send_bytes(b"\x00\xffraw-protocol\n")
                received.append(connection.recv_bytes())
        except Exception as error:
            failures.append(error)

    thread = threading.Thread(target=client, daemon=True)
    thread.start()
    try:
        connection = pipe.accept(secret, process, 5)
        assert connection.recv_bytes() == b"\x00\xffraw-protocol\n"
        connection.send_bytes(b"reply\n")
        thread.join(timeout=5)
        assert not thread.is_alive() and not failures
        assert received == [b"reply\n"]
        connection.close()
    finally:
        process.Close()
        pipe.close()


def test_relay_child_bytes_stderr_separation_and_graceful_eof():
    from multiprocessing import Pipe
    outer, inner = Pipe(duplex=True)
    code = "import sys; data=sys.stdin.buffer.read();sys.stderr.buffer.write(b'diagnostic\\n');sys.stdout.buffer.write(data)"
    results = []
    failures = []

    def run():
        try:
            results.append(worker.run_child(inner, [sys.executable, "-c", code], cleanup_timeout=5))
        except Exception as error:
            failures.append(error)
        finally:
            inner.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    payload = '{"jsonrpc":"2.0","result":"\u4e2d\u6587"}\n'.encode("utf-8") + b"\x00\xff"
    stdout, stderr, report = io.BytesIO(), io.BytesIO(), {}
    try:
        assert admin.relay(outer, io.BytesIO(payload), stdout, stderr, report) == 0
        thread.join(timeout=5)
        assert not thread.is_alive() and not failures and results == [0]
        assert stdout.getvalue() == payload
        assert stderr.getvalue() == b"diagnostic\n"
        assert set(report) == {"worker_pid", "worker_elevated", "server_pid", "server_elevated"}
        assert report["server_pid"] != os.getpid()
    finally:
        outer.close()


def test_worker_disconnect_closes_stdin_without_killing():
    from multiprocessing import Pipe
    outer, inner = Pipe(duplex=True)
    results, failures = [], []

    def run():
        try:
            results.append(worker.run_child(inner, [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"], cleanup_timeout=5))
        except Exception as error:
            failures.append(error)
        finally:
            inner.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert outer.recv_bytes().startswith(b"A")
    outer.close()
    thread.join(timeout=10)
    assert not thread.is_alive() and not failures and results == [0]


def test_uac_arguments_fixed_and_hidden(monkeypatch, tmp_path):
    from win32com.shell import shell
    import win32con
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return {"hProcess": "handle"}

    monkeypatch.setattr(shell, "ShellExecuteEx", fake)
    assert admin.elevate(tmp_path / "space path" / "connection.json") == "handle"
    assert captured["lpVerb"] == "runas" and captured["lpFile"] == sys.executable
    assert captured["nShow"] == win32con.SW_HIDE
    assert "instant_admin_worker.py" in captured["lpParameters"]
    assert "--ticket" in captured["lpParameters"]
    assert "auth" not in captured["lpParameters"]


def test_unknown_cli_options_fail_without_uac():
    import subprocess
    result = subprocess.run([sys.executable, str(ROOT / "scripts/start_instant_mcp_admin.py"),
                             "--command", "cmd.exe"], capture_output=True, timeout=10)
    assert result.returncode == 2
    assert result.stdout == b""


def test_uac_cancelled_has_no_stdout_no_secret_and_no_fallback(tmp_path, monkeypatch, capsys):
    import pywintypes
    report = tmp_path / "admin-report.json"
    monkeypatch.setattr(sys, "argv", ["start_instant_mcp_admin.py", "--data-dir", str(tmp_path / "data"),
                                    "--model-directory", str(tmp_path), "--report", str(report)])
    tickets = []
    original = admin.make_ticket

    def record(*args):
        result = original(*args)
        tickets.append(result)
        return result

    def cancelled(ticket):
        raise pywintypes.error(1223, "ShellExecuteEx", "cancelled")

    monkeypatch.setattr(admin, "make_ticket", record)
    monkeypatch.setattr(admin, "elevate", cancelled)
    assert admin.main() == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "UAC cancelled" in captured.err
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["connected"] is False and payload["relay_cleanup_verified"] is False
    path, ticket = tickets[0]
    assert not path.exists() and not path.parent.exists()
    assert ticket["auth"] not in captured.err + report.read_text(encoding="utf-8")


def test_named_pipe_timeout_is_bounded_without_uac():
    import win32api
    import win32con
    import time
    sid, _, _ = worker.identity()
    pipe = admin.LocalPipe("\\\\.\\pipe\\agent-review-instant-admin-timeout-" + secrets.token_hex(16), sid)
    process = win32api.OpenProcess(win32con.SYNCHRONIZE, False, os.getpid())
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="administrator_connection_timeout"):
            pipe.accept(secrets.token_bytes(32), process, 0.1)
        assert time.monotonic() - started < 2
    finally:
        pipe.close()
        process.Close()


@pytest.mark.parametrize("failing_stage", ["identity", "child_elevation", "send_bytes", "thread_start"])
def test_early_evidence_or_thread_failure_still_closes_child_stdin_and_waits(monkeypatch, failing_stage):
    import subprocess
    children = []

    def record_popen(*args, **kwargs):
        child = subprocess.Popen(*args, **kwargs)
        children.append(child)
        return child

    def fail(*args, **kwargs):
        raise ValueError("synthetic_early_failure")

    connection = types.SimpleNamespace(send_bytes=lambda data: None)
    if failing_stage == "send_bytes":
        connection.send_bytes = fail
    elif failing_stage == "thread_start":
        monkeypatch.setattr(worker.threading.Thread, "start", fail)
    else:
        monkeypatch.setattr(worker, failing_stage, fail)
    with pytest.raises(ValueError, match="synthetic_early_failure"):
        worker.run_child(connection, [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"],
                         popen=record_popen, cleanup_timeout=5)
    assert len(children) == 1
    child = children[0]
    assert child.stdin.closed and child.stdout.closed and child.stderr.closed
    assert child.poll() == 0


def test_timeout_help_does_not_claim_uac_dialog_timeout():
    import subprocess
    # 子解释器不继承父进程的 -X utf8；中文帮助输出与读取端必须使用同一编码。
    result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/start_instant_mcp_admin.py"), "--help"],
                            capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0
    assert "AFTER UAC confirmation" in result.stdout
    assert "not automatically timed out or cancelled" in result.stdout


def test_refusing_stdin_cannot_block_disconnect_cleanup(monkeypatch):
    import subprocess
    import time
    from multiprocessing import Pipe
    outer, inner = Pipe(duplex=True)
    children, failures = [], []

    def record_popen(*args, **kwargs):
        child = subprocess.Popen(*args, **kwargs)
        children.append(child)
        return child

    def run():
        try:
            worker.run_child(inner, [sys.executable, "-c", "import time; time.sleep(3)"],
                             popen=record_popen, cleanup_timeout=0.2)
        except Exception as error:
            failures.append(error)
        finally:
            inner.close()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        assert outer.recv_bytes().startswith(b"A")
        outer.send_bytes(b"I" + b"x" * 65536)
        time.sleep(0.1)
        outer.close()
        thread.join(timeout=2)
        assert not thread.is_alive()
        assert len(failures) == 1 and isinstance(failures[0], TimeoutError)
        assert children[0].stdin.closed
        assert children[0].poll() is None
        assert not any(t.name == "instant-admin-stdin" and t.is_alive() for t in threading.enumerate())
    finally:
        outer.close()
        for child in children:
            child.wait(timeout=5)


def test_input_queue_is_bounded_and_rejects_after_eof(monkeypatch):
    monkeypatch.setattr(worker.threading.Thread, "start", lambda self: None)
    pump = worker._InputPump(io.BytesIO())
    for _ in range(4):
        pump.submit(b"bounded")
    with pytest.raises(BufferError, match="backpressure"):
        pump.submit(b"too many")
    pump.finish()
    with pytest.raises(ValueError, match="after_close"):
        pump.submit(b"late")
