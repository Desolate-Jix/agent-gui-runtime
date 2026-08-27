"""Hybrid provider 的 Windows Job Object 所有权边界。"""

from __future__ import annotations

from hashlib import sha256
import ctypes
from ctypes import wintypes
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
from threading import Lock
import time
from typing import Any, Callable, Mapping, Sequence

import psutil


PROCESS_SCOPE_CONTRACT_VERSION = "hybrid_windows_process_scope_v1"
_PROVIDERS = {"omni", "qwen", "vista"}
_SCOPE_NAME_RE = re.compile(
    r"\ALocal\\AgentGuiHybrid-(omni|qwen|vista)-[0-9a-f]{64}\Z"
)
_BENCHMARK_SCOPE_NAME_RE = re.compile(
    r"\ALocal\\AgentGuiBenchmarkWorker(?:Test)?-[0-9a-f]{64}\Z"
)
_BENCHMARK_CONTROLLER_NAME_RE = re.compile(
    r"\ALocal\\AgentGuiBenchmarkWorkerController(?:Test)?-[0-9a-f]{64}\Z"
)
_PROCESS_LAUNCH_LOCK = Lock()

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


def scoped_process_launch_ready() -> bool:
    return windows_process_scope_available()


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


def benchmark_worker_scope_name_v1(
    *,
    authority_kind: str,
    run_id: str,
    stage: str,
    operation_id: str,
    worker_id: str,
    payload_sha256: str,
    execution_nonce: str,
) -> str:
    material = _benchmark_name_material(
        contract_version="benchmark_worker_scope_name_v1",
        authority_kind=authority_kind,
        fields={
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "worker_id": worker_id,
            "payload_sha256": _require_lower_hex(payload_sha256, 64, "payload_sha256"),
            "execution_nonce": _require_lower_hex(
                execution_nonce, 32, "execution_nonce"
            ),
        },
    )
    prefix = (
        "Local\\AgentGuiBenchmarkWorker-"
        if authority_kind == "production_workflow_service"
        else "Local\\AgentGuiBenchmarkWorkerTest-"
    )
    return prefix + _canonical_sha256(material)


def benchmark_worker_controller_mutex_name_v1(
    *,
    authority_kind: str,
    run_id: str,
    stage: str,
    operation_id: str,
) -> str:
    material = _benchmark_name_material(
        contract_version="benchmark_worker_controller_mutex_name_v1",
        authority_kind=authority_kind,
        fields={
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
        },
    )
    prefix = (
        "Local\\AgentGuiBenchmarkWorkerController-"
        if authority_kind == "production_workflow_service"
        else "Local\\AgentGuiBenchmarkWorkerControllerTest-"
    )
    return prefix + _canonical_sha256(material)


class WindowsProcessScope:
    def __init__(self, name: str, *, create: bool) -> None:
        if not windows_process_scope_available():
            raise HybridProcessScopeError("Windows Job Object authority is unavailable")
        self.name = _owned_scope_name(name)
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

    def job_policy(self) -> dict[str, object]:
        self._require_open()
        information = win32job.QueryInformationJobObject(
            self._handle, win32job.JobObjectExtendedLimitInformation
        )
        basic = dict(information.get("BasicLimitInformation") or {})
        flags = int(basic.get("LimitFlags") or 0)
        return {
            "kill_on_job_close": bool(
                flags & int(win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
            ),
            "breakaway_ok": bool(
                flags & int(win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK)
            ),
            "silent_breakaway_ok": bool(
                flags & int(win32job.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK)
            ),
            "owner_handle_authority": "registry_parent",
        }

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


def assign_exact_process_identity_to_scope(
    *,
    scope_name: str,
    process_identity: Mapping[str, int],
) -> dict[str, Any]:
    normalized_scope_name = _benchmark_scope_name(scope_name)
    expected = _validated_process_identity(process_identity)
    before = _identity_for_pid(expected["pid"])
    if before != expected:
        raise HybridProcessScopeError(
            "benchmark worker process incarnation changed before OpenProcess"
        )

    process_handle = None
    scope = None
    observation: dict[str, Any] | None = None
    primary_error: BaseException | None = None
    process_close: dict[str, object] | None = None
    job_close: dict[str, object] | None = None
    try:
        access = (
            int(win32con.PROCESS_QUERY_INFORMATION)
            | int(win32con.PROCESS_SET_QUOTA)
            | int(win32con.PROCESS_TERMINATE)
        )
        process_handle = win32api.OpenProcess(access, False, expected["pid"])
        after_open = _identity_from_handle(process_handle, expected["pid"])
        if not _same_process_incarnation(after_open, expected):
            raise HybridProcessScopeError(
                "benchmark worker process incarnation changed after OpenProcess"
            )
        scope = WindowsProcessScope(normalized_scope_name, create=False)
        if scope.pids():
            raise HybridProcessScopeError(
                "benchmark worker Job must be empty before exact assignment"
            )
        scope.assign(process_handle)
        after_assignment = _identity_from_handle(process_handle, expected["pid"])
        observed = _identities_for_pids(scope.pids())
        if not _same_process_incarnation(after_assignment, expected) or observed != [expected]:
            raise HybridProcessScopeError(
                "benchmark worker Job membership does not match exact incarnation"
            )
        policy = scope.job_policy()
        if policy != _benchmark_job_policy():
            raise HybridProcessScopeError("benchmark worker Job policy is invalid")
        observation = {
            "contract_version": "benchmark_worker_scope_assignment_v1",
            "scope_name": normalized_scope_name,
            "process_identity": expected,
            "observed_member_identities": observed,
            "job_policy": policy,
        }
    except BaseException as error:
        primary_error = error
    finally:
        if process_handle is not None:
            try:
                win32api.CloseHandle(process_handle)
                process_close = {"handle_kind": "temporary_process", "status": "closed"}
            except BaseException as error:
                process_close = {
                    "handle_kind": "temporary_process",
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
                if primary_error is None:
                    primary_error = error
        if scope is not None:
            try:
                scope.close()
                job_close = {"handle_kind": "temporary_job", "status": "closed"}
            except BaseException as error:
                job_close = {
                    "handle_kind": "temporary_job",
                    "status": "error",
                    "error_type": type(error).__name__,
                    "message": str(error),
                }
                if primary_error is None:
                    primary_error = error
    if primary_error is not None:
        if isinstance(primary_error, HybridProcessScopeError):
            raise primary_error
        raise HybridProcessScopeError(
            "benchmark worker exact Job assignment failed"
        ) from primary_error
    assert observation is not None and process_close is not None and job_close is not None
    observation["temporary_process_handle_close"] = process_close
    observation["temporary_job_handle_close"] = job_close
    return _seal_observation(observation)


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
        self._closed = False

    def _require_open(self) -> None:
        if self._closed:
            raise HybridProcessScopeError("Hybrid process handle is closed")

    def poll(self) -> int | None:
        self._require_open()
        if self.returncode is not None:
            return self.returncode
        code = int(win32process.GetExitCodeProcess(self._handle))
        if code == int(win32con.STILL_ACTIVE):
            return None
        self.returncode = code
        return code

    def wait(self, timeout: float | None = None) -> int:
        self._require_open()
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
        self._require_open()
        if self.poll() is None:
            win32process.TerminateProcess(self._handle, 1)
            self.wait(5.0)

    terminate = kill

    def close(self) -> None:
        if not self._closed:
            win32api.CloseHandle(self._handle)
            self._closed = True

    def __enter__(self) -> "ScopedProcess":
        self._require_open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


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
    before_resume: Callable[[Mapping[str, object]], None] | None = None,
) -> ScopedProcess:
    """挂起创建、加入 Job，再恢复；provider 无未纳管的 spawn 窗口。"""
    scope = WindowsProcessScope(scope_name, create=False)
    opened: list[Any] = []
    process_handle = thread_handle = None
    duplicates: list[int] = []
    try:
        with _PROCESS_LAUNCH_LOCK:
            source_input = _stdio_source(stdin, readable=True, opened=opened)
            source_output = _stdio_source(stdout, readable=False, opened=opened)
            source_error = (
                source_output
                if stderr == subprocess.STDOUT
                else _stdio_source(stderr, readable=False, opened=opened)
            )
            duplicate_by_source: dict[int, int] = {}
            for source in (source_input, source_output, source_error):
                if source not in duplicate_by_source:
                    duplicate_by_source[source] = _duplicate_inheritable_handle(source)
                    duplicates.append(duplicate_by_source[source])
            process_handle, thread_handle, pid = _create_suspended_process_with_handles(
                command,
                cwd=Path(cwd),
                env=env,
                creationflags=creationflags,
                stdin_handle=duplicate_by_source[source_input],
                stdout_handle=duplicate_by_source[source_output],
                stderr_handle=duplicate_by_source[source_error],
                inherited_handles=duplicates,
            )
        scope.assign(process_handle)
        process = psutil.Process(int(pid))
        process_identity = {
            "pid": int(pid),
            "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
        }
        if before_resume is not None:
            before_resume(deepcopy(process_identity))
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
        for handle in duplicates:
            win32api.CloseHandle(handle)
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


def _stdio_source(value: Any, *, readable: bool, opened: list[Any]) -> int:
    import msvcrt

    if value == subprocess.PIPE:
        raise ValueError("Hybrid scoped provider does not support PIPE stdio")
    if value == subprocess.DEVNULL or value is None:
        handle = open(os.devnull, "rb" if readable else "ab", buffering=0)
        opened.append(handle)
        return int(msvcrt.get_osfhandle(handle.fileno()))
    return int(msvcrt.get_osfhandle(value.fileno()))


def _duplicate_inheritable_handle(source: int) -> int:
    current = win32api.GetCurrentProcess()
    duplicated = win32api.DuplicateHandle(
        current,
        int(source),
        current,
        0,
        True,
        int(win32con.DUPLICATE_SAME_ACCESS),
    )
    return int(duplicated.Detach())


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(wintypes.BYTE)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


def _create_suspended_process_with_handles(
    command: Sequence[str], *, cwd: Path, env: Mapping[str, str] | None,
    creationflags: int, stdin_handle: int, stdout_handle: int,
    stderr_handle: int, inherited_handles: Sequence[int],
) -> tuple[int, int, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    size = ctypes.c_size_t()
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    attributes = ctypes.create_string_buffer(size.value)
    if not kernel32.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    handle_array = (wintypes.HANDLE * len(inherited_handles))(
        *(wintypes.HANDLE(handle) for handle in inherited_handles)
    )
    try:
        if not kernel32.UpdateProcThreadAttribute(
            attributes, 0, ctypes.c_size_t(0x00020002),
            ctypes.byref(handle_array), ctypes.sizeof(handle_array), None, None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        startup = _STARTUPINFOEXW()
        startup.StartupInfo.cb = ctypes.sizeof(startup)
        startup.StartupInfo.dwFlags = int(win32process.STARTF_USESTDHANDLES)
        startup.StartupInfo.hStdInput = wintypes.HANDLE(stdin_handle)
        startup.StartupInfo.hStdOutput = wintypes.HANDLE(stdout_handle)
        startup.StartupInfo.hStdError = wintypes.HANDLE(stderr_handle)
        startup.lpAttributeList = ctypes.cast(attributes, ctypes.c_void_p)
        information = _PROCESS_INFORMATION()
        command_line = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([str(item) for item in command])
        )
        environment = None
        flags = (
            int(creationflags)
            | int(win32con.CREATE_SUSPENDED)
            | 0x00080000
        )
        if env is not None:
            environment = ctypes.create_unicode_buffer(
                "\0".join(f"{key}={value}" for key, value in sorted(env.items())) + "\0\0"
            )
            flags |= 0x00000400
        if not kernel32.CreateProcessW(
            None, command_line, None, None, True, flags,
            environment, str(cwd), ctypes.byref(startup), ctypes.byref(information),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(information.hProcess), int(information.hThread), int(information.dwProcessId)
    finally:
        kernel32.DeleteProcThreadAttributeList(attributes)


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


def _identity_for_pid(pid: int) -> dict[str, int]:
    try:
        process = psutil.Process(int(pid))
        return {
            "pid": int(process.pid),
            "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
        }
    except psutil.NoSuchProcess as error:
        raise HybridProcessScopeError(
            "benchmark worker process incarnation is absent"
        ) from error
    except (psutil.AccessDenied, OSError) as error:
        raise HybridProcessScopeError(
            "benchmark worker process incarnation is unobservable"
        ) from error


def _identity_from_handle(handle: Any, pid: int) -> dict[str, int]:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        )
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        if not kernel32.GetProcessTimes(
            wintypes.HANDLE(int(handle)),
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        filetime = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        return {
            "pid": int(pid),
            "create_time_ns": (filetime - 116_444_736_000_000_000) * 100,
        }
    except BaseException as error:
        raise HybridProcessScopeError(
            "benchmark worker process handle incarnation is unobservable"
        ) from error


def _same_process_incarnation(
    handle_identity: Mapping[str, int],
    expected: Mapping[str, int],
) -> bool:
    return (
        handle_identity.get("pid") == expected.get("pid")
        and abs(
            int(handle_identity.get("create_time_ns") or 0)
            - int(expected.get("create_time_ns") or 0)
        )
        < 1_000
    )


def _validated_process_identity(value: Mapping[str, int]) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != {"pid", "create_time_ns"}:
        raise HybridProcessScopeError("benchmark worker process identity must be closed")
    pid = value.get("pid")
    created = value.get("create_time_ns")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or isinstance(created, bool)
        or not isinstance(created, int)
        or created <= 0
    ):
        raise HybridProcessScopeError("benchmark worker process identity is invalid")
    return {"pid": pid, "create_time_ns": created}


def _benchmark_job_policy() -> dict[str, object]:
    return {
        "kill_on_job_close": True,
        "breakaway_ok": False,
        "silent_breakaway_ok": False,
        "owner_handle_authority": "registry_parent",
    }


def _benchmark_name_material(
    *,
    contract_version: str,
    authority_kind: str,
    fields: Mapping[str, object],
) -> dict[str, object]:
    if authority_kind not in {"production_workflow_service", "test_only"}:
        raise ValueError("benchmark worker authority_kind is invalid")
    normalized: dict[str, object] = {
        "contract_version": contract_version,
        "authority_kind": authority_kind,
    }
    for key, value in fields.items():
        if key not in {"payload_sha256", "execution_nonce"}:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"benchmark worker {key} is required")
        normalized[key] = value
    return normalized


def _require_lower_hex(value: object, length: int, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"benchmark worker {field} is invalid")
    return value


def _canonical_sha256(value: Mapping[str, object]) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _seal_observation(value: Mapping[str, object]) -> dict[str, Any]:
    sealed = dict(value)
    sealed["content_sha256"] = _canonical_sha256(sealed)
    return sealed


def _scope_name(value: str) -> str:
    normalized = str(value or "").strip()
    if _SCOPE_NAME_RE.fullmatch(normalized) is None:
        raise ValueError("Hybrid process scope name is invalid")
    return normalized


def _benchmark_scope_name(value: str) -> str:
    normalized = str(value or "").strip()
    if _BENCHMARK_SCOPE_NAME_RE.fullmatch(normalized) is None:
        raise ValueError("benchmark worker scope name is invalid")
    return normalized


def _owned_scope_name(value: str) -> str:
    normalized = str(value or "").strip()
    if (
        _SCOPE_NAME_RE.fullmatch(normalized) is None
        and _BENCHMARK_SCOPE_NAME_RE.fullmatch(normalized) is None
    ):
        raise ValueError("Hybrid process scope name is invalid")
    return normalized


def validate_process_scope_name(value: str) -> str:
    return _scope_name(value)


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
    "assign_exact_process_identity_to_scope",
    "benchmark_worker_controller_mutex_name_v1",
    "benchmark_worker_scope_name_v1",
    "observe_process_scope_cleanup",
    "process_scope_name",
    "validate_process_scope_name",
    "spawn_process_in_scope",
    "scoped_process_launch_ready",
    "windows_process_scope_available",
]
