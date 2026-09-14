"""经用户 UAC 确认启动管理员 MCP，保留 Agent 的普通 STDIO 连接。"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from instant_admin_worker import MAX_FRAME, identity, private_security


class LocalPipe:
    def __init__(self, name, sid):
        import win32file
        import win32pipe
        self.handle = win32pipe.CreateNamedPipe(
            name, win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED | 0x00080000,
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | 0x00000008,
            1, 65536, 65536, 0, private_security(sid))

    def accept(self, auth, process, timeout):
        import pywintypes
        import win32event
        import win32file
        import win32pipe
        from multiprocessing.connection import PipeConnection, answer_challenge, deliver_challenge
        overlapped = pywintypes.OVERLAPPED()
        event = win32event.CreateEvent(None, True, False, None)
        overlapped.hEvent = event
        try:
            try:
                result = win32pipe.ConnectNamedPipe(self.handle, overlapped)
                if result == 535:
                    win32event.SetEvent(event)
            except pywintypes.error as error:
                if error.winerror == 535:
                    win32event.SetEvent(event)
                elif error.winerror != 997:
                    raise
            deadline = time.monotonic() + timeout
            while win32event.WaitForSingleObject(event, 100) == win32event.WAIT_TIMEOUT:
                if win32event.WaitForSingleObject(process, 0) == win32event.WAIT_OBJECT_0:
                    raise RuntimeError("administrator_worker_exited_before_connection")
                if time.monotonic() >= deadline:
                    raise TimeoutError("administrator_connection_timeout")
            connection = PipeConnection(self.handle.Detach())
            self.handle = None
            failures = []

            def authenticate():
                try:
                    deliver_challenge(connection, auth)
                    answer_challenge(connection, auth)
                except Exception as error:
                    failures.append(error)

            task = threading.Thread(target=authenticate, daemon=True)
            task.start()
            task.join(timeout=max(0.1, deadline - time.monotonic()))
            if task.is_alive() or failures:
                connection.close()
                raise RuntimeError("administrator_pipe_authentication_failed")
            return connection
        finally:
            if self.handle is not None:
                try:
                    win32file.CancelIo(self.handle)
                    win32event.WaitForSingleObject(event, 5000)
                except pywintypes.error as error:
                    if error.winerror != 1168:
                        raise
            event.Close()

    def close(self):
        if self.handle is not None:
            self.handle.Close()
            self.handle = None


def make_ticket(args, sid, session):
    import win32file
    folder = Path(tempfile.gettempdir()) / ("agent-review-admin-" + secrets.token_hex(16))
    win32file.CreateDirectory(str(folder), private_security(sid))
    path = folder / "connection.json"
    payload = {"pipe": "\\\\.\\pipe\\agent-review-instant-admin-" + secrets.token_hex(24),
               "auth": secrets.token_hex(32), "sid": sid, "session": session,
               "expires": time.time() + args.connect_timeout + 120,
               "data": str(args.data_dir.resolve()), "model": str(args.model_directory.resolve()),
               "allow_input": args.allow_local_input}
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
        return path, payload
    except BaseException:
        path.unlink(missing_ok=True)
        folder.rmdir()
        raise


def elevate(ticket):
    import win32con
    from win32com.shell import shell, shellcon
    worker = Path(__file__).resolve().with_name("instant_admin_worker.py")
    result = shell.ShellExecuteEx(fMask=shellcon.SEE_MASK_NOCLOSEPROCESS | 0x00000100,
                                 lpVerb="runas", lpFile=sys.executable,
                                 lpParameters=subprocess.list2cmdline(["-I", str(worker), "--ticket", str(ticket)]),
                                 nShow=win32con.SW_HIDE)
    return result["hProcess"]


def relay(connection, stdin, stdout, stderr, report=None):
    stopped = threading.Event()

    def forward_input():
        try:
            read = getattr(stdin, "read1", stdin.read)
            while not stopped.is_set():
                chunk = read(65536)
                if not chunk:
                    connection.send_bytes(b"C")
                    return
                connection.send_bytes(b"I" + chunk)
        except (EOFError, BrokenPipeError, OSError):
            stopped.set()

    thread = threading.Thread(target=forward_input, daemon=True)
    thread.start()
    try:
        while True:
            packet = connection.recv_bytes(MAX_FRAME)
            if packet.startswith(b"O"):
                stdout.write(packet[1:])
                stdout.flush()
            elif packet.startswith(b"E"):
                stderr.write(packet[1:])
                stderr.flush()
            elif packet.startswith(b"X"):
                return int(packet[1:].decode("ascii"))
            elif packet.startswith(b"A"):
                info = json.loads(packet[1:].decode("utf-8"))
                if set(info) != {"worker_pid", "worker_elevated", "server_pid", "server_elevated"}:
                    raise ValueError("invalid_admin_process_evidence")
                if report is not None:
                    report.update(info)
            else:
                raise ValueError("invalid_admin_output_frame")
    finally:
        stopped.set()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--allow-local-input", action="store_true")
    parser.add_argument("--connect-timeout", "--uac-timeout", type=int, default=90,
                        help="Pipe connection timeout AFTER UAC confirmation; --uac-timeout is a legacy alias. "
                             "The synchronous Windows UAC dialog is not automatically timed out or cancelled.")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Windows administrator relay only")
    if not 5 <= args.connect_timeout <= 300 or not args.model_directory.is_dir():
        parser.error("valid model directory and connect timeout 5..300 required")
    ticket = pipe = process = connection = None
    report = {"mode": "administrator_stdio_relay", "connected": False,
              "relay_cleanup_verified": False, "host_cleanup_verified": None,
              "connect_timeout_seconds": args.connect_timeout,
              "timeout_scope": "pipe_connection_after_uac_confirmation",
              "uac_dialog_automatically_cancelled": False}
    try:
        sid, session, _ = identity()
        ticket, payload = make_ticket(args, sid, session)
        pipe = LocalPipe(payload["pipe"], sid)
        print("Administrator MCP requested: approve the Windows UAC prompt; no normal-permission fallback.", file=sys.stderr)
        process = elevate(ticket)
        connection = pipe.accept(bytes.fromhex(payload["auth"]), process, args.connect_timeout)
        report["connected"] = True
        ticket.unlink()
        code = relay(connection, sys.stdin.buffer, sys.stdout.buffer, sys.stderr.buffer, report)
        report["server_exit_code"] = code
        return code
    except Exception as error:
        code = getattr(error, "winerror", None)
        reason = "UAC cancelled" if code == 1223 else type(error).__name__
        report["error"] = reason
        print("administrator_mcp_failed: " + reason + "; no lower-privilege fallback", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()
        if pipe is not None:
            pipe.close()
        if process is not None:
            import win32event
            import win32process
            report["worker_exited"] = win32event.WaitForSingleObject(process, 5000) == win32event.WAIT_OBJECT_0
            if report["worker_exited"]:
                report["worker_exit_code"] = win32process.GetExitCodeProcess(process)
            report["relay_cleanup_verified"] = (report.get("server_exit_code") == 0
                                                 and report.get("worker_exit_code") == 0)
            process.Close()
        if ticket is not None:
            ticket.unlink(missing_ok=True)
            ticket.parent.rmdir()
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
