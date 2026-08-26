"""Benchmark-v2 test-owned bitmap window 的精确所有权边界。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import RLock
import time
from typing import Any, Mapping

import psutil

from app.learn.hybrid.benchmark_v2_contracts import (
    canonical_json_bytes,
    content_sha256,
    require_sha256,
)
from app.learn.hybrid.windows_process_scope import (
    ScopedProcess,
    WindowsProcessScope,
    observe_process_scope_cleanup,
    spawn_process_in_scope,
)


OWNER_JOURNAL_CONTRACT = "portfolio_hybrid_benchmark_v2_window_owner_journal_v1"
OWNER_BINDING_CONTRACT = "portfolio_hybrid_benchmark_v2_window_binding_v1"
ATTESTATION_CONTRACT = "portfolio_hybrid_benchmark_v2_window_attestation_v1"
CLEANUP_CONTRACT = "portfolio_hybrid_benchmark_v2_window_cleanup_v1"
EVENT_CONTRACT = "portfolio_hybrid_benchmark_v2_window_owner_event_v1"
_OPERATION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_LIVE_LOCK = RLock()
_WINDOWS = os.name == "nt"


@dataclass
class _LiveOwner:
    scope: WindowsProcessScope
    process: ScopedProcess


_LIVE_OWNERS: dict[str, _LiveOwner] = {}


@contextmanager
def _reconcile_mutex(owner_id: str):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel.ReleaseMutex.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    name = "Local\\AgentGuiBenchmarkV2-window-reconcile-" + _sha(
        owner_id.encode("utf-8")
    )
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    acquired = False
    try:
        status = int(kernel.WaitForSingleObject(handle, 0xFFFFFFFF))
        if status not in {0, 0x80}:
            raise OSError(status, "window reconcile mutex wait failed")
        acquired = True
        yield
    finally:
        errors: list[BaseException] = []
        if acquired and not kernel.ReleaseMutex(handle):
            errors.append(ctypes.WinError(ctypes.get_last_error()))
        if not kernel.CloseHandle(handle):
            errors.append(ctypes.WinError(ctypes.get_last_error()))
        if errors:
            raise BaseExceptionGroup("window reconcile mutex cleanup failed", errors)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _helper_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "portfolio_hybrid_v1_1_test_window_v2.py"
    ).resolve()


def _identity(operation_id: str, screenshot_sha256: str) -> dict[str, str]:
    if _OPERATION.fullmatch(operation_id) is None:
        raise ValueError("window operation_id is invalid")
    require_sha256(screenshot_sha256, "screenshot_sha256")
    digest = _sha(
        canonical_json_bytes(
            {
                "contract_version": OWNER_JOURNAL_CONTRACT,
                "operation_id": operation_id,
                "screenshot_sha256": screenshot_sha256,
            }
        )
    )
    return {
        "owner_id": f"window-owner-{digest}",
        "scope_name": f"Local\\AgentGuiHybrid-vista-{digest}",
        "window_class": f"AgentGuiBenchmarkV2_{digest[:32]}",
        "window_title": f"AgentGui Benchmark v2 {digest[:24]}",
    }


def _bmp_dimensions(raw: bytes) -> dict[str, int]:
    if len(raw) < 26 or raw[:2] != b"BM":
        raise ValueError("benchmark screenshot must be an exact BMP fixture")
    width = int.from_bytes(raw[18:22], "little", signed=True)
    height = abs(int.from_bytes(raw[22:26], "little", signed=True))
    if width <= 0 or height <= 0:
        raise ValueError("benchmark screenshot dimensions are invalid")
    return {"width": width, "height": height}


def _atomic_create_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_json_bytes(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(canonical_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _events_path(journal_path: Path) -> Path:
    return journal_path.with_name(journal_path.name + ".events.jsonl")


def _publication_path(journal_path: Path) -> Path:
    return journal_path.with_name(journal_path.name + ".publication.json")


def _publication_permit_path(journal_path: Path) -> Path:
    return journal_path.with_name(journal_path.name + ".publication-permit.json")


def _helper_stderr_path(journal_path: Path) -> Path:
    return journal_path.with_name(journal_path.name + ".helper-stderr.txt")


def _event_lock_path(journal_path: Path) -> Path:
    return journal_path.with_name(journal_path.name + ".events.lock")


class _EventLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._stream = None

    def __enter__(self) -> "_EventLock":
        import msvcrt

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self._path.open("a+b")
        if self._stream.seek(0, os.SEEK_END) == 0:
            self._stream.write(b"\0")
            self._stream.flush()
        self._stream.seek(0)
        msvcrt.locking(self._stream.fileno(), msvcrt.LK_LOCK, 1)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        import msvcrt

        assert self._stream is not None
        self._stream.seek(0)
        msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
        self._stream.close()


def _load_events(journal_path: Path, *, owner_id: str) -> list[dict[str, object]]:
    path = _events_path(journal_path)
    if not path.exists():
        return []
    try:
        lines = path.read_bytes().splitlines()
        events = [json.loads(line.decode("utf-8")) for line in lines if line]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("window owner journal event bytes are invalid") from error
    previous = "0" * 64
    for sequence, event in enumerate(events):
        required = {
            "contract_version",
            "sequence",
            "event_type",
            "owner_id",
            "previous_event_sha256",
            "payload",
            "content_sha256",
        }
        if not isinstance(event, dict) or set(event) != required:
            raise ValueError("window owner journal event schema is invalid")
        if (
            event["contract_version"] != EVENT_CONTRACT
            or event["sequence"] != sequence
            or event["owner_id"] != owner_id
            or event["previous_event_sha256"] != previous
            or event["content_sha256"] != content_sha256(event)
        ):
            raise ValueError("window owner journal event chain is invalid")
        previous = str(event["content_sha256"])
    return events


def _append_event(
    journal_path: Path,
    *,
    owner_id: str,
    event_type: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    with _EventLock(_event_lock_path(journal_path)):
        events = _load_events(journal_path, owner_id=owner_id)
        previous = str(events[-1]["content_sha256"]) if events else "0" * 64
        event: dict[str, object] = {
            "contract_version": EVENT_CONTRACT,
            "sequence": len(events),
            "event_type": event_type,
            "owner_id": owner_id,
            "previous_event_sha256": previous,
            "payload": dict(payload),
        }
        event["content_sha256"] = content_sha256(event)
        with _events_path(journal_path).open("ab") as stream:
            stream.write(canonical_json_bytes(event) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        verified = _load_events(journal_path, owner_id=owner_id)
        if verified[-1] != event:
            raise ValueError("window owner journal append postcondition failed")
        return event


def _load_root(journal_path: Path) -> dict[str, object]:
    path = Path(journal_path)
    if not path.is_absolute() or str(path) != str(path.resolve()):
        raise ValueError("window owner journal path must be canonical and absolute")
    try:
        root = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("window owner journal is unreadable") from error
    fields = {
        "contract_version",
        "owner_id",
        "operation_id",
        "screenshot_path",
        "screenshot_sha256",
        "image_dimensions",
        "scope_name",
        "window_class",
        "window_title",
        "journal_path",
        "events_path",
        "publication_path",
        "publication_permit_path",
        "helper_path",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "display_only",
        "content_sha256",
    }
    if not isinstance(root, dict) or set(root) != fields:
        raise ValueError("window owner journal schema is invalid")
    if root["contract_version"] != OWNER_JOURNAL_CONTRACT:
        raise ValueError("window owner journal contract is invalid")
    if root["content_sha256"] != content_sha256(root):
        raise ValueError("window owner journal content hash is invalid")
    identity = _identity(str(root["operation_id"]), str(root["screenshot_sha256"]))
    if any(root[key] != value for key, value in identity.items()):
        raise ValueError("window owner journal derived identity is invalid")
    expected_paths = {
        "journal_path": str(path),
        "events_path": str(_events_path(path)),
        "publication_path": str(_publication_path(path)),
        "publication_permit_path": str(_publication_permit_path(path)),
        "helper_path": str(_helper_path()),
    }
    if any(root[key] != value for key, value in expected_paths.items()):
        raise ValueError("window owner journal paths are invalid")
    image = Path(str(root["screenshot_path"]))
    if not image.is_absolute() or str(image) != str(image.resolve()):
        raise ValueError("window owner screenshot path is invalid")
    if (
        root["artifact_is_authorization"] is not False
        or root["execute_binding_enabled"] is not False
        or root["display_only"] is not True
    ):
        raise ValueError("window owner journal safety fields are invalid")
    _load_events(path, owner_id=str(root["owner_id"]))
    return root


def _enum_matching_windows(pid: int, window_class: str, title: str) -> list[int]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int

    @callback_type
    def callback(hwnd, _lparam):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if int(process_id.value) != int(pid):
            return True
        class_buffer = ctypes.create_unicode_buffer(256)
        title_buffer = ctypes.create_unicode_buffer(512)
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        if class_buffer.value == window_class and title_buffer.value == title:
            found.append(int(hwnd))
        return True

    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    if not user32.EnumWindows(callback, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return sorted(found)


def _window_geometry(hwnd: int) -> tuple[dict[str, int], dict[str, int], int]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetDpiForWindow.argtypes = (wintypes.HWND,)
    user32.GetDpiForWindow.restype = wintypes.UINT
    window = wintypes.RECT()
    client = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(window)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not user32.GetClientRect(hwnd, ctypes.byref(client)):
        raise ctypes.WinError(ctypes.get_last_error())
    top_left = wintypes.POINT(client.left, client.top)
    bottom_right = wintypes.POINT(client.right, client.bottom)
    if not user32.ClientToScreen(hwnd, ctypes.byref(top_left)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not user32.ClientToScreen(hwnd, ctypes.byref(bottom_right)):
        raise ctypes.WinError(ctypes.get_last_error())
    dpi = int(user32.GetDpiForWindow(hwnd))
    if dpi <= 0:
        raise ValueError("window binding DPI is unavailable")
    return (
        {
            "left": int(window.left),
            "top": int(window.top),
            "right": int(window.right),
            "bottom": int(window.bottom),
        },
        {
            "left": int(top_left.x),
            "top": int(top_left.y),
            "right": int(bottom_right.x),
            "bottom": int(bottom_right.y),
            "width": int(bottom_right.x - top_left.x),
            "height": int(bottom_right.y - top_left.y),
        },
        dpi,
    )


def _raw_hwnd_attestation(owner: Mapping[str, object]) -> dict[str, object]:
    try:
        process_identity = dict(owner["process_identity"])
        pid = int(process_identity["pid"])
        create_time_ns = int(process_identity["create_time_ns"])
        hwnd = int(owner["hwnd"])
        scope_name = str(owner["scope_name"])
        window_class = str(owner["window_class"])
        title = str(owner["window_title"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("window binding identity is incomplete") from error
    try:
        observed_create_time = int(
            round(psutil.Process(pid).create_time() * 1_000_000_000)
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as error:
        raise ValueError("window binding process is missing") from error
    if observed_create_time != create_time_ns:
        raise ValueError("window binding process incarnation is stale")
    try:
        scope = WindowsProcessScope(scope_name, create=False)
    except BaseException as error:
        raise ValueError("window binding Job is missing") from error
    try:
        members = scope.pids()
    finally:
        scope.close()
    if members != [pid]:
        member_details = []
        for member in members:
            try:
                process = psutil.Process(member)
                member_details.append(
                    {"pid": member, "exe": process.exe(), "cmdline": process.cmdline()}
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                member_details.append({"pid": member, "unobservable": True})
        raise ValueError(
            "window binding Job membership is ambiguous: "
            f"members={member_details}, expected={[pid]}"
        )
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = (wintypes.HWND,)
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    )
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    if not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        raise ValueError("window binding HWND is missing")
    if int(user32.GetAncestor(hwnd, 2)) != hwnd:
        raise ValueError("window binding HWND is not a top-level root")
    hwnd_pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(hwnd_pid))
    if int(hwnd_pid.value) != pid:
        raise ValueError("window binding HWND owner PID differs")
    matching = _enum_matching_windows(pid, window_class, title)
    if len(matching) != 1:
        raise ValueError("window binding has multiple or missing exact HWNDs")
    if matching[0] != hwnd:
        raise ValueError("window binding exact HWND differs")
    window_rect, client_rect, dpi = _window_geometry(hwnd)
    expected = {
        "window_rect": dict(owner["window_rect"]),
        "client_rect": dict(owner["client_rect"]),
        "dpi": int(owner["dpi"]),
    }
    if (
        window_rect != expected["window_rect"]
        or client_rect != expected["client_rect"]
        or dpi != expected["dpi"]
    ):
        raise ValueError("window binding geometry or DPI drifted")
    dimensions = dict(owner["image_dimensions"])
    if client_rect["width"] != dimensions["width"] or client_rect["height"] != dimensions["height"]:
        raise ValueError("window binding client area differs from screenshot")
    result: dict[str, object] = {
        "process_identity": {"pid": pid, "create_time_ns": create_time_ns},
        "job_member_pids": members,
        "hwnd": hwnd,
        "window_class": window_class,
        "window_title": title,
        "window_rect": window_rect,
        "client_rect": client_rect,
        "dpi": dpi,
        "screenshot_sha256": owner["screenshot_sha256"],
    }
    result["identity_sha256"] = _sha(canonical_json_bytes(result))
    return result


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    root = Path(__file__).resolve().parents[3]
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root / ".venv" / "Lib" / "site-packages"), str(root)]
    )
    return env


def _run_uia_probe(owner: Mapping[str, object]) -> dict[str, object]:
    journal_path = Path(str(owner["journal_path"]))
    token = _sha(canonical_json_bytes({"owner_id": owner["owner_id"], "probe": time.time_ns()}))
    request = journal_path.with_name(f".{journal_path.name}.{token}.probe-request.json")
    result = journal_path.with_name(f".{journal_path.name}.{token}.probe-result.json")
    stderr_path = journal_path.with_name(f".{journal_path.name}.{token}.probe-stderr.txt")
    probe_scope_name = f"Local\\AgentGuiHybrid-vista-{token}"
    scope = WindowsProcessScope(probe_scope_name, create=True)
    process = None
    try:
        binding_bytes_sha256 = _sha(canonical_json_bytes(dict(owner)))
        request_value: dict[str, object] = {
            "contract_version": "portfolio_hybrid_benchmark_v2_uia_probe_request_v1",
            "probe_nonce": token,
            "binding_bytes_sha256": binding_bytes_sha256,
            "owner": dict(owner),
        }
        request_value["content_sha256"] = content_sha256(request_value)
        _atomic_json(request, request_value)
        with stderr_path.open("wb") as stderr_stream:
            process = spawn_process_in_scope(
                [
                    sys._base_executable,
                    str(_helper_path()),
                    "probe-uia",
                    "--request",
                    str(request),
                    "--result",
                    str(result),
                ],
                scope_name=probe_scope_name,
                cwd=Path(__file__).resolve().parents[3],
                env=_child_env(),
                stderr=stderr_stream,
                creationflags=0x08000008,
            )
        code = process.wait(30)
        if code != 0 or not result.exists():
            details = stderr_path.read_text(encoding="utf-8", errors="replace")
            raise ValueError(
                f"window binding isolated UIA probe failed: exit={code}: {details}"
            )
        probe = json.loads(result.read_text(encoding="utf-8"))
        if (
            not isinstance(probe, dict)
            or probe.get("content_sha256") != content_sha256(probe)
            or probe.get("probe_nonce") != token
            or probe.get("binding_bytes_sha256") != binding_bytes_sha256
        ):
            raise ValueError("window binding UIA probe result is invalid")
        return probe
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
            finally:
                process.close()
        scope.close()
        cleanup = observe_process_scope_cleanup(
            probe_scope_name, terminate=True, stable_zero_observations=3
        )
        for path in (request, result, stderr_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        if cleanup["cleanup_status"] != "verified":
            raise RuntimeError("window binding UIA probe cleanup is indeterminate")


def _uia_identity(probe: Mapping[str, object], owner: Mapping[str, object]) -> dict[str, object]:
    if probe.get("contract_version") != "portfolio_hybrid_benchmark_v2_uia_probe_v1":
        raise ValueError("window binding UIA probe contract is invalid")
    if probe.get("owner_id") != owner["owner_id"]:
        raise ValueError("window binding UIA probe lineage differs")
    pre = dict(probe["pre"])
    post = dict(probe["post"])
    if pre != post:
        raise ValueError("window binding changed during UIA probe")
    bound = dict(probe["bound"])
    snapshot = dict(probe["snapshot"])
    window = dict(snapshot.get("window") or {})
    controls = snapshot.get("controls")
    if (
        snapshot.get("status") != "ok"
        or bound.get("handle") != owner["hwnd"]
        or bound.get("process_id") != owner["process_identity"]["pid"]
        or window.get("handle") != owner["hwnd"]
        or window.get("process_id") != owner["process_identity"]["pid"]
        or not isinstance(controls, list)
        or not controls
        or not isinstance(controls[0], dict)
    ):
        raise ValueError("window binding UIA root is not exact")
    root = controls[0]
    identity = {
        "provider": snapshot["provider"],
        "provider_version": snapshot["provider_version"],
        "window_handle": window["handle"],
        "window_process_id": window["process_id"],
        "window_title": window["title"],
        "root_control": {
            key: root.get(key)
            for key in (
                "control_id",
                "name",
                "control_type",
                "automation_id",
                "class_name",
                "screen_bbox",
            )
        },
    }
    identity["content_sha256"] = content_sha256(identity)
    return identity


def _binding_from_publication(
    root: Mapping[str, object], publication: Mapping[str, object]
) -> dict[str, object]:
    binding: dict[str, object] = {
        "contract_version": OWNER_BINDING_CONTRACT,
        "owner_id": root["owner_id"],
        "operation_id": root["operation_id"],
        "screenshot_path": root["screenshot_path"],
        "screenshot_sha256": root["screenshot_sha256"],
        "scope_name": root["scope_name"],
        "process_identity": publication["process_identity"],
        "job_member_pids": [publication["process_identity"]["pid"]],
        "hwnd": publication["hwnd"],
        "window_class": root["window_class"],
        "window_title": root["window_title"],
        "window_rect": publication["window_rect"],
        "client_rect": publication["client_rect"],
        "dpi": publication["dpi"],
        "image_dimensions": root["image_dimensions"],
        "journal_path": root["journal_path"],
        "journal_root_sha256": root["content_sha256"],
        "journal_root": dict(root),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "display_only": True,
    }
    return binding


def _validate_publication(
    root: Mapping[str, object],
    publication: Mapping[str, object],
    process: ScopedProcess,
    *,
    expected_predecessor_sha256: str,
    permit_content_sha256: str,
) -> None:
    required = {
        "contract_version",
        "owner_id",
        "screenshot_sha256",
        "process_identity",
        "hwnd",
        "hwnds",
        "window_class",
        "window_title",
        "window_rect",
        "client_rect",
        "dpi",
        "image_dimensions",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "journal_root_sha256",
        "expected_predecessor_sha256",
        "permit_content_sha256",
        "content_sha256",
    }
    if not isinstance(publication, Mapping) or set(publication) != required:
        raise ValueError("window binding publication schema is invalid")
    if (
        publication["contract_version"]
        != "portfolio_hybrid_benchmark_v2_hwnd_publication_v1"
        or publication["owner_id"] != root["owner_id"]
        or publication["screenshot_sha256"] != root["screenshot_sha256"]
        or publication["window_class"] != root["window_class"]
        or publication["window_title"] != root["window_title"]
        or publication["image_dimensions"] != root["image_dimensions"]
        or publication["process_identity"] != process.process_identity
        or publication["artifact_is_authorization"] is not False
        or publication["execute_binding_enabled"] is not False
        or publication["journal_root_sha256"] != root["content_sha256"]
        or publication["expected_predecessor_sha256"]
        != expected_predecessor_sha256
        or publication["permit_content_sha256"] != permit_content_sha256
        or publication["content_sha256"] != content_sha256(publication)
    ):
        raise ValueError("window binding publication lineage differs")


def launch_owned_window(
    *,
    image_path: Path,
    expected_sha256: str,
    operation_id: str,
    journal_path: Path,
) -> dict[str, object]:
    if not _WINDOWS:
        raise RuntimeError("Windows exact HWND ownership is unavailable")
    return _launch_owned_window(
        image_path=image_path,
        expected_sha256=expected_sha256,
        operation_id=operation_id,
        journal_path=journal_path,
        duplicate_window=False,
    )


def _launch_owned_window_for_test(
    *,
    image_path: Path,
    expected_sha256: str,
    operation_id: str,
    journal_path: Path,
    duplicate_window: bool,
    fail_after_job_created: bool = False,
    pause_after_process_created: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return _launch_owned_window(
        image_path=image_path,
        expected_sha256=expected_sha256,
        operation_id=operation_id,
        journal_path=journal_path,
        duplicate_window=duplicate_window,
        fail_after_job_created=fail_after_job_created,
        pause_after_process_created=pause_after_process_created,
    )


def _launch_owned_window(
    *,
    image_path: Path,
    expected_sha256: str,
    operation_id: str,
    journal_path: Path,
    duplicate_window: bool,
    fail_after_job_created: bool = False,
    pause_after_process_created: Mapping[str, object] | None = None,
) -> dict[str, object]:
    image = Path(image_path)
    journal = Path(journal_path)
    if not image.is_absolute():
        image = image.resolve()
    if not journal.is_absolute():
        journal = journal.resolve()
    if str(image) != str(image.resolve()) or str(journal) != str(journal.resolve()):
        raise ValueError("window owner paths must be canonical")
    raw = image.read_bytes()
    digest = _sha(raw)
    if digest != require_sha256(expected_sha256, "expected_sha256"):
        raise ValueError("window screenshot SHA-256 differs")
    dimensions = _bmp_dimensions(raw)
    derived = _identity(operation_id, digest)
    root: dict[str, object] = {
        "contract_version": OWNER_JOURNAL_CONTRACT,
        **derived,
        "operation_id": operation_id,
        "screenshot_path": str(image),
        "screenshot_sha256": digest,
        "image_dimensions": dimensions,
        "journal_path": str(journal),
        "events_path": str(_events_path(journal)),
        "publication_path": str(_publication_path(journal)),
        "publication_permit_path": str(_publication_permit_path(journal)),
        "helper_path": str(_helper_path()),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "display_only": True,
    }
    root["content_sha256"] = content_sha256(root)
    _atomic_create_json(journal, root)
    _append_event(
        journal,
        owner_id=str(root["owner_id"]),
        event_type="launch_intent",
        payload={"journal_root_sha256": root["content_sha256"]},
    )
    lifecycle = ExitStack()
    lifecycle.enter_context(_reconcile_mutex(str(root["owner_id"])))
    scope = None
    process = None
    scope_transferred = False
    try:
        current_events = _load_events(journal, owner_id=str(root["owner_id"]))
        if any(
            event["event_type"] in {"finalization_intent", "cleanup_verified"}
            for event in current_events
        ):
            raise ValueError("window launch was already finalized")
        scope = WindowsProcessScope(str(root["scope_name"]), create=True)
        with _LIVE_LOCK:
            if str(journal) in _LIVE_OWNERS:
                scope.close()
                raise ValueError("window owner journal is already live")
        _append_event(
            journal,
            owner_id=str(root["owner_id"]),
            event_type="job_created",
            payload={"scope_name": root["scope_name"]},
        )
        if fail_after_job_created:
            raise RuntimeError("injected pre-transfer launch failure")
        command = [
            sys._base_executable,
            str(_helper_path()),
            "serve-bitmap",
            "--image",
            str(image),
            "--sha256",
            digest,
            "--owner-id",
            str(root["owner_id"]),
            "--window-class",
            str(root["window_class"]),
            "--title",
            str(root["window_title"]),
            "--publication",
            str(_publication_path(journal)),
            "--publication-permit",
            str(_publication_permit_path(journal)),
        ]
        if duplicate_window:
            command.append("--duplicate-window")
        with _helper_stderr_path(journal).open("wb") as stderr_stream:
            process = spawn_process_in_scope(
                command,
                scope_name=str(root["scope_name"]),
                cwd=Path(__file__).resolve().parents[3],
                env=_child_env(),
                stderr=stderr_stream,
                creationflags=0x08000008,
            )
        with _LIVE_LOCK:
            _LIVE_OWNERS[str(journal)] = _LiveOwner(scope=scope, process=process)
            scope_transferred = True
        process_event = _append_event(
            journal,
            owner_id=str(root["owner_id"]),
            event_type="process_created",
            payload={"process_identity": process.process_identity},
        )
        if pause_after_process_created is not None:
            ready_path = Path(str(pause_after_process_created["ready_path"]))
            release_path = Path(str(pause_after_process_created["release_path"]))
            ready_path.write_text("paused", encoding="utf-8")
            deadline = time.monotonic() + 20
            while not release_path.exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("window launch pause timed out")
                time.sleep(0.01)
        permit: dict[str, object] = {
            "contract_version": "portfolio_hybrid_benchmark_v2_hwnd_publication_permit_v1",
            "owner_id": root["owner_id"],
            "journal_root_sha256": root["content_sha256"],
            "expected_predecessor_sha256": process_event["content_sha256"],
        }
        permit["content_sha256"] = content_sha256(permit)
        _atomic_json(_publication_permit_path(journal), permit)
        deadline = time.monotonic() + 20
        publication_path = _publication_path(journal)
        while not publication_path.exists():
            code = process.poll()
            if code is not None:
                details = _helper_stderr_path(journal).read_text(
                    encoding="utf-8", errors="replace"
                )
                raise RuntimeError(
                    f"window helper exited before publication: {code}: {details}"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError("window helper publication timed out")
            time.sleep(0.02)
        publication = json.loads(publication_path.read_text(encoding="utf-8"))
        _validate_publication(
            root,
            publication,
            process,
            expected_predecessor_sha256=str(process_event["content_sha256"]),
            permit_content_sha256=str(permit["content_sha256"]),
        )
        publication_event = _append_event(
            journal,
            owner_id=str(root["owner_id"]),
            event_type="hwnd_published",
            payload={"publication": publication},
        )
        if publication_event["previous_event_sha256"] != publication[
            "expected_predecessor_sha256"
        ]:
            raise ValueError("window binding publication predecessor differs")
        binding = _binding_from_publication(root, publication)
        pre = _raw_hwnd_attestation(binding)
        probe = _run_uia_probe(binding)
        uia_identity = _uia_identity(probe, binding)
        post = _raw_hwnd_attestation(binding)
        if pre != post:
            raise ValueError("window binding changed around UIA probe")
        binding["uia_root_identity"] = uia_identity
        binding["content_sha256"] = content_sha256(binding)
        _append_event(
            journal,
            owner_id=str(root["owner_id"]),
            event_type="ready",
            payload={
                "binding": binding,
                "pre_raw_identity_sha256": pre["identity_sha256"],
                "post_raw_identity_sha256": post["identity_sha256"],
            },
        )
        return binding
    except BaseException as primary:
        local_cleanup: list[BaseException] = []
        if not scope_transferred:
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                except BaseException as error:
                    local_cleanup.append(error)
                try:
                    process.close()
                except BaseException as error:
                    local_cleanup.append(error)
            if scope is not None:
                try:
                    scope.close()
                except BaseException as error:
                    local_cleanup.append(error)
        try:
            close_owned_window(journal_path=journal, reason="launch_failure")
        except BaseException as cleanup:
            local_cleanup.append(cleanup)
        if local_cleanup:
            raise BaseExceptionGroup(
                "window launch and cleanup failed", [primary, *local_cleanup]
            )
        raise
    finally:
        lifecycle.close()


def _validate_binding(owner: Mapping[str, object]) -> dict[str, object]:
    binding = dict(owner)
    if binding.get("contract_version") != OWNER_BINDING_CONTRACT:
        raise ValueError("window binding contract is invalid")
    if binding.get("content_sha256") != content_sha256(binding):
        raise ValueError("window binding content hash is invalid")
    root = _load_root(Path(str(binding.get("journal_path"))))
    try:
        screenshot_bytes = Path(str(root["screenshot_path"])).read_bytes()
    except OSError as error:
        raise ValueError("window binding screenshot is missing") from error
    if (
        _sha(screenshot_bytes) != root["screenshot_sha256"]
        or _bmp_dimensions(screenshot_bytes) != root["image_dimensions"]
    ):
        raise ValueError("window binding screenshot bytes are stale")
    if (
        binding.get("owner_id") != root["owner_id"]
        or binding.get("operation_id") != root["operation_id"]
        or binding.get("screenshot_sha256") != root["screenshot_sha256"]
        or binding.get("screenshot_path") != root["screenshot_path"]
        or binding.get("scope_name") != root["scope_name"]
        or binding.get("window_class") != root["window_class"]
        or binding.get("window_title") != root["window_title"]
        or binding.get("journal_root_sha256") != root["content_sha256"]
        or binding.get("journal_root") != root
        or binding.get("artifact_is_authorization") is not False
        or binding.get("execute_binding_enabled") is not False
        or binding.get("display_only") is not True
    ):
        raise ValueError("window binding lineage differs from journal")
    events = _load_events(Path(str(root["journal_path"])), owner_id=str(root["owner_id"]))
    ready = [event for event in events if event["event_type"] == "ready"]
    if len(ready) != 1 or ready[0]["payload"].get("binding") != binding:
        raise ValueError("window binding ready receipt is missing or ambiguous")
    return root


def attest_bound_window(*, owner: Mapping[str, object]) -> dict[str, object]:
    if not _WINDOWS:
        raise RuntimeError("Windows exact HWND attestation is unavailable")
    _validate_binding(owner)
    pre = _raw_hwnd_attestation(owner)
    probe = _run_uia_probe(owner)
    uia_identity = _uia_identity(probe, owner)
    post = _raw_hwnd_attestation(owner)
    if pre != post or uia_identity != owner["uia_root_identity"]:
        raise ValueError("window binding pre/post or UIA identity differs")
    return {
        "contract_version": ATTESTATION_CONTRACT,
        "binding_content_sha256": owner["content_sha256"],
        "owner_id": owner["owner_id"],
        "operation_id": owner["operation_id"],
        "exact_hwnd": owner["hwnd"],
        "process_identity": owner["process_identity"],
        "job_member_pids": pre["job_member_pids"],
        "screenshot_sha256": owner["screenshot_sha256"],
        "uia_root_identity": uia_identity,
        "pre_raw_identity_sha256": pre["identity_sha256"],
        "post_raw_identity_sha256": post["identity_sha256"],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _owner_for_cleanup(root: Mapping[str, object], events: list[dict[str, object]]) -> dict[str, object] | None:
    ready = [event for event in events if event["event_type"] == "ready"]
    if ready:
        binding = ready[-1]["payload"].get("binding")
        return dict(binding) if isinstance(binding, Mapping) else None
    publication_path = Path(str(root["publication_path"]))
    if publication_path.exists():
        publication = json.loads(publication_path.read_text(encoding="utf-8"))
        if isinstance(publication, Mapping):
            return _binding_from_publication(root, publication)
    return None


def close_owned_window(*, journal_path: Path, reason: str) -> dict[str, object]:
    if not _WINDOWS:
        raise RuntimeError("Windows exact HWND cleanup is unavailable")
    journal = Path(journal_path)
    if not journal.is_absolute():
        journal = journal.resolve()
    root = _load_root(journal)
    with _reconcile_mutex(str(root["owner_id"])):
        return _close_owned_window_locked(journal=journal, root=root, reason=reason)


def _close_owned_window_locked(
    *, journal: Path, root: Mapping[str, object], reason: str
) -> dict[str, object]:
    events = _load_events(journal, owner_id=str(root["owner_id"]))
    terminal = [event for event in events if event["event_type"] == "cleanup_verified"]
    if terminal:
        return dict(terminal[-1]["payload"])
    if not isinstance(reason, str) or not reason or len(reason) > 128:
        raise ValueError("window cleanup reason is invalid")
    _append_event(
        journal,
        owner_id=str(root["owner_id"]),
        event_type="finalization_intent",
        payload={"reason": reason},
    )
    events = _load_events(journal, owner_id=str(root["owner_id"]))
    owner = _owner_for_cleanup(root, events)
    live = None
    with _LIVE_LOCK:
        live = _LIVE_OWNERS.pop(str(journal), None)
    exact_hwnd = int(owner["hwnd"]) if owner is not None else 0
    pid = int(owner["process_identity"]["pid"]) if owner is not None else 0
    matching_before: list[int] = []
    wm_close_queued = False
    wm_close_error_code = 0
    if owner is not None:
        try:
            _raw_hwnd_attestation(owner)
            matching_before = _enum_matching_windows(
                pid, str(owner["window_class"]), str(owner["window_title"])
            )
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostMessageW.argtypes = (
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            user32.PostMessageW.restype = wintypes.BOOL
            wm_close_queued = bool(user32.PostMessageW(exact_hwnd, 0x0010, 0, 0))
            if not wm_close_queued:
                wm_close_error_code = ctypes.get_last_error()
        except (ValueError, OSError):
            matching_before = []
    deadline = time.monotonic() + 1.0
    while live is not None and live.process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    first_cleanup = observe_process_scope_cleanup(
        str(root["scope_name"]), terminate=True, stable_zero_observations=3
    )
    process_handle_closed = live is None
    job_handle_closed = live is None
    if live is not None:
        try:
            if live.process.poll() is None:
                live.process.kill()
            else:
                live.process.wait(5)
        finally:
            live.process.close()
            process_handle_closed = True
        live.scope.close()
        job_handle_closed = True
    final_cleanup = observe_process_scope_cleanup(
        str(root["scope_name"]), terminate=True, stable_zero_observations=3
    )
    matching_after = (
        _enum_matching_windows(pid, str(root["window_class"]), str(root["window_title"]))
        if pid
        else []
    )
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.IsWindow.argtypes = (wintypes.HWND,)
    user32.IsWindow.restype = wintypes.BOOL
    hwnd_absent = exact_hwnd == 0 or not bool(user32.IsWindow(exact_hwnd))
    verified = (
        first_cleanup["cleanup_status"] == "verified"
        and final_cleanup["cleanup_status"] == "verified"
        and final_cleanup["scope_absent_after_owner_close"] is True
        and not final_cleanup["member_pids_after"]
        and not final_cleanup["active_listeners_after"]
        and not matching_after
        and hwnd_absent
        and process_handle_closed
        and job_handle_closed
    )
    receipt: dict[str, object] = {
        "contract_version": CLEANUP_CONTRACT,
        "owner_id": root["owner_id"],
        "reason": reason,
        "cleanup_status": "verified" if verified else "indeterminate",
        "wm_close_exact_hwnd_attempted": bool(matching_before),
        "wm_close_exact_hwnd_queued": wm_close_queued,
        "wm_close_error_code": wm_close_error_code,
        "enum_windows_exact_hwnd_absent": hwnd_absent,
        "matching_owned_windows_after": matching_after,
        "member_pids_after": final_cleanup["member_pids_after"],
        "stable_zero_observations": final_cleanup["stable_zero_observations"],
        "scope_absent_after_owner_close": final_cleanup[
            "scope_absent_after_owner_close"
        ],
        "process_handle_closed": process_handle_closed,
        "job_handle_closed": job_handle_closed,
        "active_listeners_after": final_cleanup["active_listeners_after"],
        "listener_or_lease_residue": [],
        "outer_owner_python_finally_observed": live is not None,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    receipt["content_sha256"] = content_sha256(receipt)
    if not verified:
        raise RuntimeError(f"window cleanup is indeterminate: {receipt}")
    _append_event(
        journal,
        owner_id=str(root["owner_id"]),
        event_type="cleanup_verified",
        payload=receipt,
    )
    for path in (
        _publication_path(journal),
        _publication_permit_path(journal),
        _event_lock_path(journal),
        _helper_stderr_path(journal),
    ):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return receipt


__all__ = ["launch_owned_window", "attest_bound_window", "close_owned_window"]
