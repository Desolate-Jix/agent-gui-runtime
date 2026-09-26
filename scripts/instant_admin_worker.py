"""管理员 MCP 固定子进程与字节桥；不接受任意可执行命令。"""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

MAX_FRAME = 16 * 1024 * 1024


def _cancel_thread_io(thread):
    if not thread.is_alive():
        return
    import ctypes
    import win32api
    import pywintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    cancel = kernel.CancelSynchronousIo
    cancel.argtypes = [ctypes.c_void_p]
    cancel.restype = ctypes.c_int
    try:
        handle = win32api.OpenThread(0x0001, False, thread.native_id)
    except pywintypes.error:
        if not thread.is_alive():
            return
        raise
    try:
        if not cancel(int(handle)) and ctypes.get_last_error() != 1168:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        handle.Close()


class _InputPump:
    def __init__(self, stream):
        self.stream = stream
        self.pending = queue.Queue(maxsize=4)
        self.finishing = threading.Event()
        self.stopping = threading.Event()
        self.failure = None
        self.thread = threading.Thread(target=self._write, daemon=True, name="instant-admin-stdin")
        self.thread.start()

    def submit(self, data):
        if self.finishing.is_set():
            raise ValueError("input_after_close")
        try:
            self.pending.put_nowait(data)
        except queue.Full as error:
            raise BufferError("admin_input_backpressure_limit") from error

    def _write(self):
        try:
            while not self.stopping.is_set():
                try:
                    data = self.pending.get(timeout=0.05)
                except queue.Empty:
                    if self.finishing.is_set():
                        break
                    continue
                remaining = memoryview(data)
                while remaining and not self.stopping.is_set():
                    written = self.stream.write(remaining)
                    if not written:
                        raise BrokenPipeError("child_stdin_write_failed")
                    remaining = remaining[written:]
                self.stream.flush()
        except (OSError, ValueError) as error:
            self.failure = error
        finally:
            self.stream.close()

    def finish(self):
        self.finishing.set()

    def shutdown(self):
        self.finish()
        self.thread.join(timeout=0.1)
        if self.thread.is_alive():
            # 仅取消本桥写线程的同步 I/O，不终止线程、子进程或用户程序。
            self.stopping.set()
            _cancel_thread_io(self.thread)
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise TimeoutError("admin_input_writer_cleanup_unverified")


def identity():
    import win32api
    import win32con
    import win32security
    import win32ts
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        elevated = bool(win32security.GetTokenInformation(token, win32security.TokenElevation))
        return win32security.ConvertSidToStringSid(sid), win32ts.ProcessIdToSessionId(os.getpid()), elevated
    finally:
        token.Close()


def private_security(sid_text):
    import pywintypes
    import win32security
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        "D:P(A;OICI;GA;;;" + sid_text + ")", win32security.SDDL_REVISION_1)
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    return attributes


def load_ticket(path):
    import win32security
    path = Path(path).resolve(strict=True)
    sid, session_id, elevated = identity()
    if not elevated:
        raise RuntimeError("administrator_token_required")
    descriptor = win32security.GetFileSecurity(str(path), win32security.OWNER_SECURITY_INFORMATION)
    if win32security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()) != sid:
        raise RuntimeError("ticket_owner_mismatch")
    ticket = json.loads(path.read_text(encoding="utf-8"))
    if set(ticket) != {"pipe", "auth", "sid", "session", "expires", "data", "model", "source",
                       "delegate_profile", "allow_input"}:
        raise ValueError("invalid_ticket_fields")
    if ticket["sid"] != sid or ticket["session"] != session_id:
        raise RuntimeError("same_user_and_session_required")
    if time.time() > ticket["expires"]:
        raise RuntimeError("admin_connection_ticket_expired")
    if not isinstance(ticket["pipe"], str) or not ticket["pipe"].startswith("\\\\.\\pipe\\agent-review-instant-admin-"):
        raise ValueError("local_pipe_required")
    auth = bytes.fromhex(ticket["auth"])
    if len(auth) != 32 or type(ticket["allow_input"]) is not bool:
        raise ValueError("invalid_ticket")
    if not isinstance(ticket["data"], str) or not Path(ticket["data"]).is_absolute():
        raise ValueError("absolute_directories_required")
    from pydantic import ValidationError
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.vision.recognition_source import RecognitionSourceConfig
    try:
        config = RecognitionSourceConfig.model_validate({"source": ticket["source"],
            "delegate_profile": ticket["delegate_profile"]})
    except ValidationError:
        raise ValueError("invalid_recognition_configuration") from None
    if config.source == "external_api":
        raise ValueError("external_api_not_implemented")
    if config.source == "local" and (not isinstance(ticket["model"], str)
                                     or not Path(ticket["model"]).is_absolute()):
        raise ValueError("absolute_model_directory_required")
    if config.source != "local" and ticket["model"] is not None:
        raise ValueError("agent_source_must_not_use_model_directory")
    return ticket, auth


def server_command(ticket):
    script = Path(__file__).resolve().with_name("start_instant_mcp.py")
    command = [sys.executable, "-I", str(script), "--data-dir", ticket["data"],
               "--recognition-source", ticket["source"]]
    if ticket["model"] is not None:
        command.extend(["--model-directory", ticket["model"]])
    if ticket["delegate_profile"] is not None:
        command.extend(["--delegate-profile", ticket["delegate_profile"]])
    if ticket["allow_input"]:
        command.append("--allow-local-input")
    return command


def child_elevation(pid):
    import win32api
    import win32con
    import win32security
    process = win32api.OpenProcess(0x1000, False, pid)
    try:
        token = win32security.OpenProcessToken(process, win32con.TOKEN_QUERY)
        try:
            return bool(win32security.GetTokenInformation(token, win32security.TokenElevation))
        finally:
            token.Close()
    finally:
        process.Close()


def run_child(connection, command, *, popen=subprocess.Popen, cleanup_timeout=180):
    # 数据通道只传字节，不反序列化来自普通权限端的 Python 对象。
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    environment.pop("PYTHONPATH", None)
    child = popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                  bufsize=0, env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        return _bridge_child(connection, child, cleanup_timeout)
    finally:
        # 身份读取、证据发送或线程初始化失败也必须关闭输入并等待清理。
        if not child.stdin.closed:
            child.stdin.close()
        if child.poll() is None:
            try:
                child.wait(timeout=cleanup_timeout)
            except subprocess.TimeoutExpired:
                print("admin_worker: cleanup unverified; no process was forcibly terminated", file=sys.stderr)
        for stream in (child.stdout, child.stderr):
            stream.close()


def _bridge_child(connection, child, cleanup_timeout):
    connection.send_bytes(b"A" + json.dumps({"worker_pid": os.getpid(), "worker_elevated": identity()[2],
                                             "server_pid": child.pid,
                                             "server_elevated": child_elevation(child.pid)}).encode("utf-8"))
    pump = _InputPump(child.stdin)
    try:
        return _bridge_with_pump(connection, child, cleanup_timeout, pump)
    finally:
        pump.shutdown()


def _bridge_with_pump(connection, child, cleanup_timeout, pump):
    write_lock = threading.Lock()
    disconnected = threading.Event()

    def emit(tag, stream):
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                with write_lock:
                    connection.send_bytes(tag + chunk)
        except (EOFError, BrokenPipeError, OSError):
            disconnected.set()

    streams = [threading.Thread(target=emit, args=(tag, stream), daemon=True)
               for tag, stream in ((b"O", child.stdout), (b"E", child.stderr))]
    input_closed = False
    deadline = None
    try:
        for thread in streams:
            thread.start()
        while child.poll() is None:
            if disconnected.is_set() and not input_closed:
                pump.finish()
                input_closed = True
                deadline = time.monotonic() + cleanup_timeout
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("MCP cleanup timeout; child not forcibly terminated")
            if pump.failure is not None:
                raise RuntimeError("admin_input_writer_failed") from pump.failure
            if input_closed:
                time.sleep(0.05)
                continue
            try:
                if not connection.poll(0.1):
                    continue
                packet = connection.recv_bytes(MAX_FRAME)
                if packet == b"C":
                    pump.finish()
                    input_closed = True
                    deadline = time.monotonic() + cleanup_timeout
                elif packet.startswith(b"I") and len(packet) > 1:
                    pump.submit(packet[1:])
                else:
                    raise ValueError("invalid_admin_input_frame")
            except (EOFError, BrokenPipeError, OSError):
                disconnected.set()
        for thread in streams:
            thread.join(timeout=5)
        code = child.wait()
        if not disconnected.is_set():
            with write_lock:
                connection.send_bytes(b"X" + str(code).encode("ascii"))
        return code
    finally:
        if not input_closed:
            pump.finish()
        # 读线程也可能等待拒绝退出的子进程；先取消本桥读取再关闭流。
        for thread in streams:
            if thread.ident is not None:
                _cancel_thread_io(thread)
                thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticket", type=Path, required=True)
    args = parser.parse_args()
    try:
        from multiprocessing.connection import Client
        ticket, auth = load_ticket(args.ticket)
        connection = Client(ticket["pipe"], family="AF_PIPE", authkey=auth)
        try:
            return run_child(connection, server_command(ticket))
        finally:
            connection.close()
    except Exception as error:
        # 只记录类型，避免路径、票据或凭据从异常信息泄漏。
        print("admin_worker_failed: " + type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
