"""Hybrid provider 的 Windows Job Object 所有权边界。"""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Sequence

import psutil


PROCESS_SCOPE_CONTRACT_VERSION = "hybrid_windows_process_scope_v1"
_PROVIDERS = {"omni", "qwen", "vista"}

try:  # pragma: no cover - 非 Windows 只用于 readiness fail-closed
    import win32api
    import win32con
    import win32event
    import win32job
    import win32process
except ImportError:  # pragma: no cover
    win32api = win32con = win32event = win32job = win32process = None


class HybridProcessScopeError(RuntimeError):
    pass


def windows_process_scope_available() -> bool:
    return os.name == "nt" and all(
        module is not None
        for module in (win32api, win32con, win32event, win32job, win32process)
    )


def process_scope_name(lineage: Mapping[str, Any], provider: str) -> str:
    normalized = str(provider or "").strip().casefold()
    if normalized not in _PROVIDERS:
        raise ValueError("Hybrid process scope provider is invalid")
    required = ("run_id", "workflow_revision", "operation_id", "stage", "stage_execution_id")
    if any(field not in lineage for field in required):
        raise ValueError("Hybrid process scope lineage is incomplete")
    material = "\0".join(str(lineage[field]) for field in required)
    digest = sha256(f"{material}\0{normalized}".encode("utf-8")).hexdigest()
    return f"Local\\AgentGuiHybrid-{normalized}-{digest}"


class WindowsProcessScope:
    def __init__(self, name: str, *, create: bool) -> None:
        if not windows_process_scope_available():
            raise HybridProcessScopeError("Windows Job Object authority is unavailable")
        self.name = _scope_name(name)
        if create:
            self._handle = win32job.CreateJobObject(None, self.name)
            if int(win32api.GetLastError()) == 183:
                win32api.CloseHandle(self._handle)
                raise HybridProcessScopeError(
                    "Hybrid process scope identity already exists"
                )
            information = win32job.QueryInformationJobObject(
                self._handle, win32job.JobObjectExtendedLimitInformation
            )
            basic = dict(information.get("BasicLimitInformation") or {})
            breakaway_flags = int(win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK) | int(
                win32job.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
            )
            basic["LimitFlags"] = (
                int(basic.get("LimitFlags") or 0) & ~breakaway_flags
            ) | int(win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
            information["BasicLimitInformation"] = basic
            win32job.SetInformationJobObject(
                self._handle,
                win32job.JobObjectExtendedLimitInformation,
                information,
            )
        else:
            access = (
                win32job.JOB_OBJECT_QUERY
                | win32job.JOB_OBJECT_TERMINATE
                | win32job.JOB_OBJECT_ASSIGN_PROCESS
            )
            self._handle = win32job.OpenJobObject(access, False, self.name)
        self._closed = False

    def pids(self) -> list[int]:
        self._require_open()
        value = win32job.QueryInformationJobObject(
            self._handle, win32job.JobObjectBasicProcessIdList
        )
        raw_pids = value.get("ProcessIdList", []) if isinstance(value, dict) else value
        return sorted({int(pid) for pid in raw_pids if int(pid) > 0})

    def assign(self, process_handle: Any) -> None:
        self._require_open()
        win32job.AssignProcessToJobObject(self._handle, process_handle)

    def terminate(self, exit_code: int = 197) -> None:
        self._require_open()
        win32job.TerminateJobObject(self._handle, int(exit_code))

    def close(self) -> None:
        if not self._closed:
            win32api.CloseHandle(self._handle)
            self._closed = True

    def _require_open(self) -> None:
        if self._closed:
            raise HybridProcessScopeError("Hybrid process scope handle is closed")


class ScopedProcess:
    """仅覆盖现有 provider 调用需要的 Popen 子集。"""

    def __init__(
        self,
        process_handle: Any,
        pid: int,
        process_identity: dict[str, int],
    ) -> None:
        self._handle = process_handle
        self.pid = int(pid)
        self.process_identity = dict(process_identity)
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        code = int(win32process.GetExitCodeProcess(self._handle))
        if code == int(win32con.STILL_ACTIVE):
            return None
        self.returncode = code
        return code

    def wait(self, timeout: float | None = None) -> int:
        milliseconds = win32event.INFINITE if timeout is None else max(0, int(timeout * 1000))
        status = win32event.WaitForSingleObject(self._handle, milliseconds)
        if status == win32event.WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(["scoped-process"], timeout)
        code = self.poll()
        assert code is not None
        return code

    def communicate(self, timeout: float | None = None) -> tuple[None, None]:
        self.wait(timeout)
        return None, None

    def kill(self) -> None:
        if self.poll() is None:
            win32process.TerminateProcess(self._handle, 1)
            self.wait(5.0)

    terminate = kill


def spawn_process_in_scope(
    command: Sequence[str],
    *,
    scope_name: str,
    cwd: str | Path,
    env: Mapping[str, str] | None = None,
    stdin: Any = subprocess.DEVNULL,
    stdout: Any = subprocess.DEVNULL,
    stderr: Any = subprocess.DEVNULL,
    creationflags: int = 0,
) -> ScopedProcess:
    """挂起创建、加入 Job，再恢复；provider 无未纳管的 spawn 窗口。"""
    scope = WindowsProcessScope(scope_name, create=False)
    opened: list[Any] = []
    process_handle = thread_handle = None
    try:
        startup = win32process.STARTUPINFO()
        startup.dwFlags |= int(win32process.STARTF_USESTDHANDLES)
        startup.hStdInput = _stdio_handle(stdin, readable=True, opened=opened)
        startup.hStdOutput = _stdio_handle(stdout, readable=False, opened=opened)
        startup.hStdError = (
            startup.hStdOutput
            if stderr == subprocess.STDOUT
            else _stdio_handle(stderr, readable=False, opened=opened)
        )
        flags = int(creationflags) | int(win32con.CREATE_SUSPENDED)
        process_handle, thread_handle, pid, _ = win32process.CreateProcess(
            None,
            subprocess.list2cmdline([str(item) for item in command]),
            None,
            None,
            True,
            flags,
            dict(env) if env is not None else None,
            str(cwd),
            startup,
        )
        scope.assign(process_handle)
        process = psutil.Process(int(pid))
        process_identity = {
            "pid": int(pid),
            "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
        }
        win32process.ResumeThread(thread_handle)
        return ScopedProcess(process_handle, pid, process_identity)
    except BaseException:
        if process_handle is not None:
            try:
                win32process.TerminateProcess(process_handle, 198)
            except BaseException:
                pass
            win32api.CloseHandle(process_handle)
        raise
    finally:
        if thread_handle is not None:
            win32api.CloseHandle(thread_handle)
        for handle in opened:
            handle.close()
        scope.close()


def observe_process_scope_cleanup(
    scope_name: str,
    *,
    terminate: bool,
    listener_ports: Sequence[int] = (),
    pid_file: str | Path | None = None,
    remove_owned_pid_file: bool = False,
    stable_zero_observations: int = 3,
    interval_seconds: float = 0.02,
) -> dict[str, Any]:
    if stable_zero_observations < 2:
        raise ValueError("Hybrid process scope requires multiple stable-zero observations")
    observed_before: list[int] = []
    scope_absent = False
    try:
        scope = WindowsProcessScope(scope_name, create=False)
    except BaseException as error:
        if _job_not_found(error):
            scope = None
            scope_absent = True
        else:
            return _indeterminate_scope(scope_name, error)
    try:
        if scope is not None:
            observed_before = scope.pids()
            if terminate and observed_before:
                scope.terminate()
        observed_identities_before = _identities_for_pids(observed_before)
        zero_rounds = 0
        samples: list[dict[str, Any]] = []
        final_pids: list[int] = []
        final_listeners: list[dict[str, int]] = []
        for _ in range(max(stable_zero_observations * 3, 6)):
            try:
                final_pids = [] if scope is None else scope.pids()
                final_identities = _identities_for_pids(final_pids)
                final_listeners = _listeners(listener_ports)
            except BaseException as error:
                return _indeterminate_scope(scope_name, error)
            samples.append({
                "pids": final_pids,
                "process_identities": final_identities,
                "listeners": final_listeners,
            })
            if not final_pids and not final_listeners:
                zero_rounds += 1
                if zero_rounds >= stable_zero_observations:
                    break
            else:
                zero_rounds = 0
            time.sleep(interval_seconds)
        pid_path = Path(pid_file).resolve() if pid_file else None
        if remove_owned_pid_file and pid_path and pid_path.exists():
            try:
                pid_value = int(pid_path.read_text(encoding="utf-8").strip())
            except (OSError, UnicodeError, ValueError):
                pid_value = 0
            if pid_value in observed_before or (pid_value > 0 and not psutil.pid_exists(pid_value)):
                try:
                    pid_path.unlink()
                except OSError:
                    pass
        pid_file_remaining = bool(pid_path and pid_path.exists())
        verified = (
            zero_rounds >= stable_zero_observations
            and not final_pids
            and not final_listeners
            and not pid_file_remaining
        )
        return {
            "contract_version": PROCESS_SCOPE_CONTRACT_VERSION,
            "scope_name": scope_name,
            "authority": "windows_job_object",
            "scope_absent_after_owner_close": scope_absent,
            "cleanup_status": "verified" if verified else "indeterminate",
            "observed_member_pids_before": observed_before,
            "observed_member_identities_before": observed_identities_before,
            "member_pids_after": final_pids,
            "member_identities_after": final_identities,
            "active_listeners_after": final_listeners,
            "pid_file_after": str(pid_path) if pid_file_remaining else None,
            "stable_zero_observations": zero_rounds,
            "samples": samples,
        }
    finally:
        if scope is not None:
            scope.close()


def _stdio_handle(value: Any, *, readable: bool, opened: list[Any]) -> Any:
    import msvcrt

    if value == subprocess.PIPE:
        raise ValueError("Hybrid scoped provider does not support PIPE stdio")
    if value == subprocess.DEVNULL or value is None:
        handle = open(os.devnull, "rb" if readable else "ab", buffering=0)
        opened.append(handle)
        os.set_handle_inheritable(msvcrt.get_osfhandle(handle.fileno()), True)
        return msvcrt.get_osfhandle(handle.fileno())
    os_handle = msvcrt.get_osfhandle(value.fileno())
    os.set_handle_inheritable(os_handle, True)
    return os_handle


def _listeners(ports: Sequence[int]) -> list[dict[str, int]]:
    expected = {int(port) for port in ports if int(port) > 0}
    if not expected:
        return []
    result: list[dict[str, int]] = []
    for connection in psutil.net_connections(kind="tcp"):
        address = connection.laddr
        if (
            connection.status == psutil.CONN_LISTEN
            and address
            and int(address.port) in expected
        ):
            result.append({"port": int(address.port), "pid": int(connection.pid or 0)})
    return sorted(result, key=lambda item: (item["port"], item["pid"]))


def _identities_for_pids(pids: Sequence[int]) -> list[dict[str, int]]:
    identities: list[dict[str, int]] = []
    for pid in pids:
        try:
            process = psutil.Process(int(pid))
            identities.append({
                "pid": int(process.pid),
                "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
            })
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, OSError) as error:
            raise HybridProcessScopeError(
                "Hybrid process scope member identity is unobservable"
            ) from error
    return sorted(identities, key=lambda item: (item["pid"], item["create_time_ns"]))


def _scope_name(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized.startswith("Local\\AgentGuiHybrid-") or len(normalized) > 240:
        raise ValueError("Hybrid process scope name is invalid")
    return normalized


def _job_not_found(error: BaseException) -> bool:
    return getattr(error, "winerror", None) in {2, 6} or getattr(error, "args", [None])[0] in {2, 6}


def _indeterminate_scope(scope_name: str, error: BaseException) -> dict[str, Any]:
    return {
        "contract_version": PROCESS_SCOPE_CONTRACT_VERSION,
        "scope_name": scope_name,
        "authority": "windows_job_object",
        "scope_absent_after_owner_close": False,
        "cleanup_status": "indeterminate",
        "observed_member_pids_before": [],
        "observed_member_identities_before": [],
        "member_pids_after": [],
        "member_identities_after": [],
        "active_listeners_after": [],
        "pid_file_after": None,
        "stable_zero_observations": 0,
        "samples": [],
        "error_type": type(error).__name__,
        "details": str(error),
    }


__all__ = [
    "HybridProcessScopeError",
    "ScopedProcess",
    "WindowsProcessScope",
    "observe_process_scope_cleanup",
    "process_scope_name",
    "spawn_process_in_scope",
    "windows_process_scope_available",
]
