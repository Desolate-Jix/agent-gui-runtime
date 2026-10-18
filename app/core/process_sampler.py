"""轻量、只读的受绑定进程采样器。

采样器只访问 psutil 的进程身份和运行时计数，不读取命令行、环境变量或凭据。
进程实例始终由 ``(pid, created_at_unix)`` 绑定；发现阶段使用一次进程表枚举构造
父子关系，避免对重叠根节点重复递归 ``children``。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
import threading
import time
from typing import Any

import psutil


class ProcessSampler:
    """按固定时间间隔记录一个或多个进程树的轻量只读快照。

    ``snapshot()`` 返回与旧运行器兼容的 ``at``/``processes`` 字段，并额外返回
    ``collection`` 计时和错误。默认采样间隔为 3 秒；后台采样约束在 2--5 秒。
    """

    def __init__(
        self,
        root_pid: int,
        extra_root_getter: Any | None = None,
        sample_interval: float = 3,
        discovery_interval: float = 10,
    ) -> None:
        if isinstance(root_pid, bool) or not isinstance(root_pid, int) or root_pid <= 0:
            raise ValueError("root_pid must be a positive process id")
        if not 2 <= float(sample_interval) <= 5:
            raise ValueError("sample_interval must be between 2 and 5 seconds")
        if float(discovery_interval) < float(sample_interval):
            raise ValueError("discovery_interval must not be shorter than sample_interval")
        self.root_pid = int(root_pid)
        self.extra_root_getter = extra_root_getter
        self.sample_interval = float(sample_interval)
        self.discovery_interval = float(discovery_interval)
        self._lock = threading.RLock()
        self._bindings: dict[int, tuple[float, psutil.Process]] = {}
        # 采样会话内永远记住 PID 的第一份身份；PID 消失后重新出现也必须经过
        # 这份历史校验，不能把新实例静默收养为旧实例。
        self._identity_history: dict[int, float] = {}
        self._rejected_identities: dict[int, tuple[float, float]] = {}
        self._static_cache: dict[tuple[int, float], dict[str, Any]] = {}
        self._last_discovery_monotonic: float | None = None
        self._last_snapshot_monotonic: float | None = None
        self._last_result: dict[str, Any] | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pending_errors: list[dict[str, str]] = []
        self._error_ledger: list[dict[str, str]] = []

    @property
    def running(self) -> bool:
        """返回后台采样线程是否仍在运行。"""
        return self._thread is not None and self._thread.is_alive()

    @property
    def error_ledger(self) -> list[dict[str, str]]:
        """返回后台异常账本副本；进程级错误仍随对应快照返回。"""
        with self._lock:
            return list(self._error_ledger)

    def start(self) -> dict[str, Any]:
        """先做一次完整发现，再启动后台轻量采样线程。"""
        with self._lock:
            if self.running:
                return self._last_result or self.snapshot(lightweight=True)
            initial = self.snapshot(lightweight=False)
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="read-only-process-sampler", daemon=True
            )
            self._thread.start()
            return initial

    def stop(self, timeout: float = 5) -> dict[str, Any] | None:
        """停止后台采样；不会控制或终止任何被观察进程。"""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout)))
        if thread is None or not thread.is_alive():
            self._thread = None
        with self._lock:
            return self._last_result

    def snapshot(
        self,
        lightweight: bool | str = True,
        *,
        discover: bool | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """读取一次快照。

        ``lightweight=True`` 只更新已绑定 PID 的动态字段；首次调用或超过发现
        周期时会做一次发现。传入 ``False``、``"full"`` 会立即做低频发现。
        ``"lightweight"`` 与 ``True`` 等价。``discover``/``force`` 可供手动轮询
        显式控制是否进行本次低频发现；不传时按 ``discovery_interval`` 自动判断。
        """
        if isinstance(lightweight, str):
            mode = lightweight.lower()
            if mode not in {"lightweight", "full"}:
                raise ValueError("lightweight must be True/False, 'lightweight', or 'full'")
            force_discovery = mode == "full"
        elif isinstance(lightweight, bool):
            force_discovery = not lightweight
        else:
            raise TypeError("lightweight must be a bool or 'lightweight'/'full'")

        started = time.perf_counter()
        errors: list[dict[str, str]] = []
        with self._lock:
            now = time.monotonic()
            if force:
                should_discover = True
            elif discover is not None:
                should_discover = bool(discover)
            else:
                should_discover = (
                    force_discovery
                    or self._last_discovery_monotonic is None
                    or now - self._last_discovery_monotonic >= self.discovery_interval
                )
            discovery_duration_ms = 0.0
            errors.extend(self._pending_errors)
            self._pending_errors.clear()
            if should_discover:
                discovery_started = time.perf_counter()
                errors.extend(self._discover())
                self._last_discovery_monotonic = time.monotonic()
                discovery_duration_ms = round((time.perf_counter() - discovery_started) * 1000, 3)
            rows: list[dict[str, Any]] = []
            for pid in sorted(self._bindings):
                row, row_error, row_errors = self._sample_bound(pid)
                if row is not None:
                    rows.append(row)
                errors.extend(row_errors)
                if row_error is not None:
                    rows.append(row_error)
                    errors.append(
                        {"operation": "sample", "pid": str(pid), "error": row_error["observation_error"]}
                    )
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            result = {
                "at": datetime.now(timezone.utc).isoformat(),
                "processes": rows,
                "collection": {
                    "duration_ms": duration_ms,
                    "discovery": should_discover,
                    "discovery_duration_ms": discovery_duration_ms,
                    "errors": errors,
                },
                # 顶层别名便于旧 JSONL 消费者在不理解 collection 时记录诊断。
                "collection_ms": duration_ms,
                "collection_errors": errors,
            }
            self._last_snapshot_monotonic = time.monotonic()
            self._last_result = result
            return result

    def _run(self) -> None:
        while not self._stop_event.wait(self.sample_interval):
            try:
                self.snapshot(lightweight=True)
            except Exception as error:
                # 后台异常也必须留在可读错误账本中，不能静默跳过一个 tick。
                entry = self._error("background_snapshot", error)
                with self._lock:
                    self._error_ledger.append(entry)
                    self._pending_errors.append(entry)
                    self._last_result = self._failed_result(entry)

    def _discover(self) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        roots = {self.root_pid}
        if self.extra_root_getter is not None:
            try:
                roots.update(self._root_pids(self.extra_root_getter()))
            except Exception as error:  # getter 是外部扩展点，错误必须可见但不可杀采样线程
                errors.append(self._error("extra_root_getter", error))

        # 这是本次发现唯一一次进程表枚举。使用父 PID 图计算闭包，不递归调用
        # root.children()，因此重叠根节点不会重复扫描浏览器子树。
        process_rows: list[tuple[int, int | None]] = []
        try:
            for process in psutil.process_iter(["pid", "ppid"]):
                info = getattr(process, "info", {}) or {}
                pid = self._as_pid(info.get("pid", getattr(process, "pid", None)))
                if pid is None:
                    continue
                ppid = self._as_pid(info.get("ppid"))
                process_rows.append((pid, ppid))
        except Exception as error:
            errors.append(self._error("process_table_enumeration", error))
            process_rows = []

        parent_map: dict[int, set[int]] = {}
        for pid, ppid in process_rows:
            if ppid is not None:
                parent_map.setdefault(ppid, set()).add(pid)
        discovered = set(roots)
        pending = list(roots)
        while pending:
            parent = pending.pop()
            for child in parent_map.get(parent, ()):
                if child not in discovered:
                    discovered.add(child)
                    pending.append(child)

        for pid in sorted(discovered):
            error = self._bind_pid(pid)
            if error is not None:
                errors.append(error)
        return errors

    def _bind_pid(self, pid: int) -> dict[str, str] | None:
        try:
            process = psutil.Process(pid)
            created = float(process.create_time())
        except Exception as error:
            return self._error("bind", error, pid=pid)
        old = self._bindings.get(pid)
        known = self._identity_history.get(pid)
        if pid in self._rejected_identities:
            expected, observed = self._rejected_identities[pid]
            return {
                "operation": "bind",
                "pid": str(pid),
                "error": "pid_reused_rejected",
                "expected_created_at_unix": str(expected),
                "observed_created_at_unix": str(observed),
            }
        if known is not None and known != created:
            # 旧实例已经退出，不能把新实例静默纳入旧记录。
            self._bindings.pop(pid, None)
            self._rejected_identities[pid] = (known, created)
            return {
                "operation": "bind",
                "pid": str(pid),
                "error": "pid_reused_rejected",
                "expected_created_at_unix": str(known),
                "observed_created_at_unix": str(created),
            }
        if old is not None and old[0] != created:
            self._bindings.pop(pid, None)
            self._rejected_identities[pid] = (old[0], created)
            return {"operation": "bind", "pid": str(pid), "error": "pid_reused_rejected"}
        self._identity_history.setdefault(pid, created)
        self._bindings[pid] = (created, process)
        self._static_cache.setdefault(
            (pid, created),
            {
                "pid": pid,
                "created_at_unix": created,
                "name": None,
                "exe": None,
                "_name_read": False,
                "_exe_read": False,
            },
        )
        return None

    def _sample_bound(
        self, pid: int
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[dict[str, str]]]:
        expected_created, _ = self._bindings[pid]
        try:
            process = psutil.Process(pid)
            observed_created = float(process.create_time())
            if observed_created != expected_created:
                self._bindings.pop(pid, None)
                self._rejected_identities[pid] = (expected_created, observed_created)
                return (
                    None,
                    {"pid": pid, "observation_error": "pid_reused_rejected"},
                    [],
                )
            cache = self._static_cache[(pid, expected_created)]
            static_errors = self._fill_static(cache, process)
            with process.oneshot():
                cpu = process.cpu_times()
                row = {
                    "pid": pid,
                    "ppid": process.ppid(),
                    "name": cache["name"],
                    "exe": cache["exe"],
                    "created_at_unix": expected_created,
                    "threads": process.num_threads(),
                    "rss_bytes": process.memory_info().rss,
                    "cpu_user_seconds": cpu.user,
                    "cpu_system_seconds": cpu.system,
                    "status": process.status(),
                }
            self._bindings[pid] = (expected_created, process)
            return row, None, static_errors
        except Exception as error:
            # 缺失进程不是活跃进程；下次低频发现可重新绑定，不伪造动态值。
            if isinstance(error, (psutil.NoSuchProcess, psutil.ZombieProcess)):
                self._bindings.pop(pid, None)
            return None, {"pid": pid, "observation_error": type(error).__name__}, []

    @staticmethod
    def _fill_static(cache: dict[str, Any], process: psutil.Process) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        if not cache["_name_read"]:
            cache["_name_read"] = True
            try:
                cache["name"] = process.name()
            except Exception as error:
                errors.append(
                    {
                        "operation": "static_field",
                        "pid": str(cache["pid"]),
                        "field": "name",
                        "error": type(error).__name__,
                    }
                )
        if not cache["_exe_read"]:
            cache["_exe_read"] = True
            try:
                cache["exe"] = process.exe()
            except Exception as error:
                errors.append(
                    {
                        "operation": "static_field",
                        "pid": str(cache["pid"]),
                        "field": "exe",
                        "error": type(error).__name__,
                    }
                )
        return errors

    @staticmethod
    def _failed_result(error: dict[str, str]) -> dict[str, Any]:
        """为后台异常提供一个可读的、没有伪造进程数据的快照。"""
        return {
            "at": datetime.now(timezone.utc).isoformat(),
            "processes": [],
            "collection": {
                "duration_ms": 0.0,
                "discovery": False,
                "discovery_duration_ms": 0.0,
                "errors": [error],
            },
            "collection_ms": 0.0,
            "collection_errors": [error],
        }

    @staticmethod
    def _root_pids(value: Any) -> set[int]:
        if value is None:
            return set()
        if isinstance(value, Mapping):
            value = value.get("pid", value.get("process_id"))
        if isinstance(value, (str, bytes)):
            return {int(value)}
        if isinstance(value, int) and not isinstance(value, bool):
            return {value} if value > 0 else set()
        if hasattr(value, "pid"):
            return {int(value.pid)}
        if isinstance(value, Iterable):
            result: set[int] = set()
            for item in value:
                result.update(ProcessSampler._root_pids(item))
            return result
        return set()

    @staticmethod
    def _as_pid(value: Any) -> int | None:
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def _error(operation: str, error: Exception, pid: int | None = None) -> dict[str, str]:
        result = {"operation": operation, "error": f"{type(error).__name__}: {error}"}
        if pid is not None:
            result["pid"] = str(pid)
        return result


__all__ = ["ProcessSampler"]
