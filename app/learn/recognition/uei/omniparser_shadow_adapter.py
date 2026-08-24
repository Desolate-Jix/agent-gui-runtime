"""Trusted local OmniParser worker adapter for UEI Shadow execution."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from threading import Event
from typing import Callable, Protocol
from uuid import uuid4

from app.learn.recognition.uei.provider_adapters import (
    AdapterFailure,
    NormalizedProviderItem,
    NormalizedScreenParseOutput,
    ProviderRunBudget,
    RestrictedCaptureLease,
)


ROOT = Path(__file__).resolve().parents[4]
PROFILE_PATH = ROOT / "configs" / "model_profiles" / "learn_mode_omniparser_v2.json"
WORKER_PATH = ROOT / "scripts" / "run_uei_omniparser_shadow_worker.py"
PROVIDER_ID = "local.runtime/omniparser"
PROFILE_ID = "local.runtime/omniparser/shadow-v2"
PROVIDER_VERSION = "v2.0.1"
_SECRET_MARKERS = ("authorization:", "bearer ", "api_key", "password=", "secret=", "sk-")


class OmniParserShadowAdapterError(AdapterFailure):
    """Non-sensitive local-worker failure safe for the generic runtime path."""

    def __init__(self, code: str) -> None:
        outcomes = {
            "runtime_resource_rejected": ("rejected", "resource_rejected", True, "not_required"),
            "runtime_pinned_runtime_unavailable": ("rejected", "runtime_unavailable", True, "not_required"),
            "runtime_invalid_input": ("rejected", "policy_rejected", False, "not_required"),
            "runtime_timeout": ("failed", "runtime_timeout", True, "clean"),
            "runtime_worker_invalid": ("failed", "runtime_worker_invalid", False, "clean"),
            "runtime_output_limit": ("failed", "runtime_worker_invalid", False, "clean"),
            "runtime_worker_failed": ("failed", "runtime_worker_failed", True, "clean"),
            "runtime_cleanup_failed": ("failed", "runtime_cleanup_failed", False, "failed"),
            "runtime_capture_hash_mismatch": ("rejected", "policy_rejected", False, "not_required"),
            "runtime_cancelled": ("failed", "runtime_provider_failed", True, "clean"),
            "runtime_configuration_unavailable": ("failed", "runtime_provider_failed", True, "not_required"),
        }
        disposition, reason, retryable, cleanup = outcomes.get(code, ("failed", "runtime_provider_failed", False, "failed"))
        super().__init__(disposition=disposition, reason_class=reason, retryable=retryable, cleanup_status=cleanup)
        self.code = code
        if code == "runtime_cancelled":
            self.args = (code,)


class ResourceLease(Protocol):
    def release(self) -> None: ...


@dataclass(frozen=True)
class TrustedOmniParserConfiguration:
    interpreter: Path
    worker_script: Path
    code_path: Path
    weights_path: Path
    cache_path: Path
    minimum_free_gpu_gib: int = 8
    is_available: bool = True

    @classmethod
    def load_default(cls) -> "TrustedOmniParserConfiguration":
        try:
            profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            expected = profile["expected_paths"]
            runtime_path = ROOT / str(expected["runtime_path"])
            return cls(
                interpreter=runtime_path / "Scripts" / "python.exe",
                worker_script=WORKER_PATH,
                code_path=ROOT / str(expected["code_path"]),
                weights_path=ROOT / str(expected["weights_path"]),
                cache_path=Path(str(expected["huggingface_cache_path"])).expanduser(),
                minimum_free_gpu_gib=int(profile["runtime_probe"]["minimum_free_gpu_gib"]),
                is_available=profile.get("launchable") is True and profile.get("download_status") == "downloaded",
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise OmniParserShadowAdapterError("runtime_configuration_unavailable") from error


class _ExclusiveLease:
    def __init__(self, owner: "InMemoryResourceLeaseManager", group: str) -> None:
        self._owner = owner
        self._group = group
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._owner._release(self._group)
            self._released = True


class InMemoryResourceLeaseManager:
    """仅测试用的进程内租约管理器。"""

    def __init__(self) -> None:
        from threading import Lock

        self._lock = Lock()
        self._held: set[str] = set()

    def __call__(self, group: str) -> ResourceLease | None:
        with self._lock:
            if group in self._held:
                return None
            self._held.add(group)
        return _ExclusiveLease(self, group)

    def _release(self, group: str) -> None:
        with self._lock:
            self._held.discard(group)


class _FileLease:
    def __init__(self, path: Path, token: str) -> None:
        self._path, self._token, self._released = path, token, False

    def release(self) -> None:
        if self._released:
            return
        try:
            if self._path.read_text(encoding="utf-8") != self._token:
                raise OmniParserShadowAdapterError("runtime_cleanup_failed")
            self._path.unlink()
            if self._path.exists():
                raise OmniParserShadowAdapterError("runtime_cleanup_failed")
        except OSError as error:
            raise OmniParserShadowAdapterError("runtime_cleanup_failed") from error
        self._released = True


class ProcessResourceLeaseManager:
    """使用原子本地锁，遗留或无效锁一律 fail closed。"""

    def __init__(self, *, root: Path | None = None) -> None:
        self._root = root or (Path(tempfile.gettempdir()) / "agent-gui-runtime-uei-leases")

    def __call__(self, group: str) -> ResourceLease | None:
        if not isinstance(group, str) or not group or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in group):
            return None
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            if self._root.is_symlink() or not self._root.is_dir():
                return None
            path = self._root / f"{group}.lock"
            if path.parent != self._root or path.is_symlink():
                return None
            token = uuid4().hex
            descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            return _FileLease(path, token)
        except OSError:
            return None


class OmniParserShadowAdapter:
    """Use a fixed offline worker without exposing paths or commands to callers."""

    provider_id = PROVIDER_ID
    profile_id = PROFILE_ID
    provider_version = PROVIDER_VERSION

    def __init__(
        self, *, configuration: TrustedOmniParserConfiguration | None = None,
        resource_lease_manager: Callable[[str], ResourceLease | None] | None = None,
        gpu_free_gib: Callable[[], float] | None = None,
        benchmark_mode: bool = False,
    ) -> None:
        self._configuration = configuration or TrustedOmniParserConfiguration.load_default()
        self._lease_manager = resource_lease_manager or ProcessResourceLeaseManager()
        self._gpu_free_gib = gpu_free_gib or _free_gpu_gib
        self._benchmark_mode = benchmark_mode is True
        self.provider_version = (
            f"{PROVIDER_VERSION}+benchmark-cold1-warm3" if self._benchmark_mode else PROVIDER_VERSION
        )
        self.last_benchmark: dict[str, object] | None = None

    def invoke(
        self, *, capture: RestrictedCaptureLease, budget: ProviderRunBudget,
        invocation_id: str, cancellation_event: Event | None = None,
    ) -> NormalizedScreenParseOutput:
        self._validate_preflight(capture=capture, budget=budget, invocation_id=invocation_id)
        if cancellation_event is not None and cancellation_event.is_set():
            raise OmniParserShadowAdapterError("runtime_cancelled")
        if self._gpu_free_gib() < self._configuration.minimum_free_gpu_gib:
            raise OmniParserShadowAdapterError("runtime_resource_rejected")
        lease_allowed, resource_lease = _cancellable_transition(
            cancellation_event,
            "before_lease",
            lambda: self._lease_manager(budget.resource_group),
        )
        if not lease_allowed:
            raise OmniParserShadowAdapterError("runtime_cancelled")
        if resource_lease is None:
            raise OmniParserShadowAdapterError("runtime_resource_rejected")
        try:
            if cancellation_event is not None and cancellation_event.is_set():
                raise OmniParserShadowAdapterError("runtime_cancelled")
            return self._invoke_worker(
                capture=capture,
                budget=budget,
                cancellation_event=cancellation_event,
            )
        finally:
            resource_lease.release()

    def _validate_preflight(
        self, *, capture: RestrictedCaptureLease, budget: ProviderRunBudget, invocation_id: str,
    ) -> None:
        config = self._configuration
        if (not isinstance(invocation_id, str) or not invocation_id
                or not isinstance(capture, RestrictedCaptureLease)
                or not isinstance(budget, ProviderRunBudget)):
            raise OmniParserShadowAdapterError("runtime_invalid_input")
        if (not config.is_available
                or not all((config.interpreter.is_file(), config.worker_script.is_file(), config.code_path.is_dir(),
                    config.weights_path.is_dir(), config.cache_path.is_dir(), capture.local_path.is_file()))):
            raise OmniParserShadowAdapterError("runtime_pinned_runtime_unavailable")
        if _sha256_file(capture.local_path) != capture.artifact_sha256:
            raise OmniParserShadowAdapterError("runtime_capture_hash_mismatch")

    def _invoke_worker(self, *, capture: RestrictedCaptureLease, budget: ProviderRunBudget,
                       cancellation_event: Event | None) -> NormalizedScreenParseOutput:
        with tempfile.TemporaryDirectory(prefix="uei-omniparser-shadow-") as directory:
            exchange = Path(directory)
            input_path = exchange / "input.json"
            output_path = exchange / "output.json"
            input_path.write_text(json.dumps({
                "input_path": str(capture.local_path), "image_size": capture.image_size,
            }, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
            process = None
            try:
                spawn_options: dict[str, object] = {
                    "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                    "env": _offline_environment(self._configuration.cache_path), "cwd": str(ROOT),
                    "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                }
                if os.name != "nt":
                    spawn_options["start_new_session"] = True
                spawn_allowed, spawned_process = _cancellable_transition(
                    cancellation_event,
                    "before_popen",
                    lambda: subprocess.Popen(
                        [str(self._configuration.interpreter), str(self._configuration.worker_script),
                         "--input-json", str(input_path), "--output-json", str(output_path)]
                        + (["--benchmark"] if self._benchmark_mode else []),
                        **spawn_options,
                    ),
                )
                if not spawn_allowed:
                    raise OmniParserShadowAdapterError("runtime_cancelled")
                process = spawned_process
                deadline = time.monotonic() + budget.timeout_ms / 1000
                while process.poll() is None:
                    if cancellation_event is not None and cancellation_event.is_set():
                        self._terminate_tree(process)
                        raise OmniParserShadowAdapterError("runtime_cancelled")
                    if output_path.exists() and output_path.stat().st_size > budget.max_output_bytes:
                        self._terminate_tree(process)
                        raise OmniParserShadowAdapterError("runtime_output_limit")
                    if time.monotonic() >= deadline:
                        self._terminate_tree(process)
                        raise OmniParserShadowAdapterError("runtime_timeout")
                    time.sleep(0.01)
                if process.returncode != 0:
                    raise OmniParserShadowAdapterError("runtime_worker_failed")
                raw = _read_bounded(output_path, budget.max_output_bytes)
                benchmark = _benchmark_metrics(raw) if self._benchmark_mode else None
                output = _normalize_worker_output(raw=raw, capture=capture, budget=budget,
                                                  allow_benchmark=self._benchmark_mode)
                self.last_benchmark = benchmark
                return output
            finally:
                if process is not None and process.returncode is None:
                    self._terminate_tree(process)

    @staticmethod
    def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
        tree_failed = False
        if os.name == "nt" and not getattr(process, "_uei_fake_process", False):
            tracked_pids: set[int] = {process.pid}
            verification_available = False
            try:
                verification_available = _windows_pid_is_active(process.pid)
                tracked_pids.update(_windows_descendant_pids(process.pid))
            except OSError:
                tree_failed = True
            try:
                completed = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if completed.returncode != 0 and not verification_available:
                    tree_failed = True
            except (OSError, subprocess.TimeoutExpired):
                tree_failed = True
            if verification_available:
                for descendant_pid in tracked_pids - {process.pid}:
                    try:
                        if _windows_pid_is_active(descendant_pid):
                            _windows_terminate_pid(descendant_pid)
                    except OSError:
                        tree_failed = True
        elif os.name != "nt" and not getattr(process, "_uei_fake_process", False):
            try:
                os.killpg(os.getpgid(process.pid), 9)
            except OSError:
                tree_failed = True
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired as error:
            raise OmniParserShadowAdapterError("runtime_cleanup_failed") from error
        if os.name == "nt" and not getattr(process, "_uei_fake_process", False) and verification_available:
            deadline = time.monotonic() + 5
            remaining = set(tracked_pids)
            while remaining and time.monotonic() < deadline:
                try:
                    remaining = {pid for pid in remaining if _windows_pid_is_active(pid)}
                except OSError:
                    tree_failed = True
                    break
                if remaining:
                    time.sleep(0.02)
            if remaining:
                tree_failed = True
        if tree_failed:
            raise OmniParserShadowAdapterError("runtime_cleanup_failed")


def _offline_environment(cache_path: Path) -> dict[str, str]:
    environment = {
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_CACHE": str(cache_path),
        "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1",
    }
    for name in ("SystemRoot", "WINDIR", "PATH"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _cancellable_transition(
    cancellation_event: Event | None,
    stage: str,
    action: Callable[[], object],
) -> tuple[bool, object | None]:
    transition = getattr(cancellation_event, "run_if_not_cancelled", None)
    if callable(transition):
        allowed, result = transition(stage, action)
        return bool(allowed), result
    if cancellation_event is not None and cancellation_event.is_set():
        return False, None
    return True, action()


def _windows_descendant_pids(root_pid: int) -> set[int]:
    """通过 Toolhelp 快照记录终止前的完整 Windows 子进程树。"""
    if os.name != "nt":
        return set()
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "process_snapshot_failed")
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise OSError(ctypes.get_last_error(), "process_snapshot_failed")
        children: dict[int, set[int]] = {}
        while True:
            children.setdefault(int(entry.th32ParentProcessID), set()).add(int(entry.th32ProcessID))
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    descendants: set[int] = set()
    pending = list(children.get(root_pid, set()))
    while pending:
        pid = pending.pop()
        if pid in descendants:
            continue
        descendants.add(pid)
        pending.extend(children.get(pid, set()))
    return descendants


def _windows_pid_is_active(pid: int) -> bool:
    """仅在能查询到明确退出码时判断 Windows PID 是否仍存活。"""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in {87, 1168}:
            return False
        raise OSError(error, "process_query_failed")
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise OSError(ctypes.get_last_error(), "process_query_failed")
        return exit_code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def _windows_terminate_pid(pid: int) -> None:
    """以固定 Win32 调用终止已记录的 worker 后代进程。"""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x0001, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error in {87, 1168}:
            return
        raise OSError(error, "process_terminate_failed")
    try:
        if not kernel32.TerminateProcess(handle, 1):
            raise OSError(ctypes.get_last_error(), "process_terminate_failed")
    finally:
        kernel32.CloseHandle(handle)


def _free_gpu_gib() -> float:
    """读取 device 0 的系统级可用 GPU 内存；探测失败时保守地视为零。"""
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            check=False, capture_output=True, text=True, timeout=2,
        )
        if completed.returncode != 0:
            return 0.0
        first = completed.stdout.splitlines()[0].strip().split()[0]
        return max(0.0, float(first) / 1024.0)
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        pass
    return 0.0


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_bounded(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as error:
        raise OmniParserShadowAdapterError("runtime_worker_invalid") from error
    if len(data) > limit:
        raise OmniParserShadowAdapterError("runtime_output_limit")
    return data


def _normalize_worker_output(
    *, raw: bytes, capture: RestrictedCaptureLease, budget: ProviderRunBudget, allow_benchmark: bool = False,
) -> NormalizedScreenParseOutput:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OmniParserShadowAdapterError("runtime_worker_invalid") from error
    expected = {"items", "duration_ms", "resource_units"}
    if allow_benchmark:
        expected.add("benchmark")
    if not isinstance(value, dict) or set(value) != expected:
        raise OmniParserShadowAdapterError("runtime_worker_invalid")
    items = value.get("items")
    if not isinstance(items, list) or len(items) > budget.max_element_count:
        raise OmniParserShadowAdapterError("runtime_output_limit")
    duration_ms, resource_units = value.get("duration_ms"), value.get("resource_units")
    if (not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or not 0 <= duration_ms <= 86400000
            or not isinstance(resource_units, int) or isinstance(resource_units, bool) or not 0 <= resource_units <= 1048576):
        raise OmniParserShadowAdapterError("runtime_worker_invalid")
    normalized = tuple(_normalize_item(item=item, capture=capture, budget=budget) for item in items)
    return NormalizedScreenParseOutput(items=normalized, duration_ms=duration_ms, resource_units=resource_units)


def _benchmark_metrics(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"))
        metrics = value.get("benchmark") if isinstance(value, dict) else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        metrics = None
    required = {"cold_ms", "warm_ms", "warm_p50_ms", "warm_p95_ms", "item_counts", "invalid_item_counts", "peak_mib"}
    if (not isinstance(metrics, dict) or set(metrics) != required or not isinstance(metrics["cold_ms"], int)
            or not isinstance(metrics["warm_ms"], list) or len(metrics["warm_ms"]) != 3
            or not all(isinstance(item, int) and item >= 0 for item in metrics["warm_ms"])
            or not isinstance(metrics["item_counts"], list) or len(metrics["item_counts"]) != 4
            or not isinstance(metrics["invalid_item_counts"], list) or len(metrics["invalid_item_counts"]) != 4
            or not all(isinstance(item, int) and item >= 0 for item in metrics["item_counts"] + metrics["invalid_item_counts"])
            or not all(isinstance(metrics[name], (int, float)) and metrics[name] >= 0 for name in ("warm_p50_ms", "warm_p95_ms", "peak_mib"))):
        raise OmniParserShadowAdapterError("runtime_worker_invalid")
    return metrics


def _normalize_item(
    *, item: object, capture: RestrictedCaptureLease, budget: ProviderRunBudget,
) -> NormalizedProviderItem:
    required = {"source_item_id", "kind", "safe_text", "source_bbox", "source_coordinate_space", "provider_confidence"}
    optional = {"safe_role", "safe_states"}
    if not isinstance(item, dict) or not required.issubset(item) or not set(item).issubset(required | optional):
        raise OmniParserShadowAdapterError("runtime_worker_invalid")
    source_item_id, kind, safe_text = item.get("source_item_id"), item.get("kind"), item.get("safe_text")
    coordinate_space, bbox, confidence = item.get("source_coordinate_space"), item.get("source_bbox"), item.get("provider_confidence")
    safe_role = item.get("safe_role")
    safe_states = item.get("safe_states", [])
    if (not isinstance(source_item_id, str) or not source_item_id or len(source_item_id) > 512
            or kind not in {"element", "text", "role", "state", "icon", "structure"}
            or not isinstance(safe_text, str) or len(safe_text) > budget.max_string_length
            or _contains_secret(safe_text)
            or safe_role is not None and (not isinstance(safe_role, str) or len(safe_role) > budget.max_string_length or _contains_secret(safe_role))
            or not isinstance(safe_states, list)
            or any(state != "interactable" for state in safe_states)
            or len(safe_states) != len(set(safe_states))):
        raise OmniParserShadowAdapterError("runtime_worker_invalid")
    if (coordinate_space != "capture_pixel_xyxy" or not isinstance(bbox, list) or len(bbox) != 4
            or not all(isinstance(edge, int) and not isinstance(edge, bool) for edge in bbox)
            or not (0 <= bbox[0] < bbox[2] <= capture.image_size["width"]
                    and 0 <= bbox[1] < bbox[3] <= capture.image_size["height"])):
        raise OmniParserShadowAdapterError("runtime_worker_invalid")
    if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1):
        raise OmniParserShadowAdapterError("runtime_worker_invalid")
    return NormalizedProviderItem(
        source_item_id=source_item_id, kind=kind, safe_text=safe_text, source_bbox=tuple(bbox),
        source_coordinate_space=coordinate_space, provider_confidence=None if confidence is None else float(confidence),
        safe_role=safe_role, safe_states=tuple(safe_states),
    )


def _contains_secret(value: str) -> bool:
    return any(marker in value.casefold() for marker in _SECRET_MARKERS)
