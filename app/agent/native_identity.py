from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from pathlib import PureWindowsPath
from typing import Any


NATIVE_IDENTITY_CONTRACT_VERSION = "windows_native_identity_observation_v1"
NATIVE_IDENTITY_PROVIDER = "windows_native_identity"


def normalize_windows_executable_path(value: object) -> str | None:
    text = str(value or "").strip().replace("/", "\\")
    if not text:
        return None
    path = PureWindowsPath(text)
    if not path.is_absolute() or not path.drive:
        return None
    return str(path).casefold()


def asset_application_identity_key(application: Mapping[str, Any]) -> str:
    kind = application.get("kind")
    if kind == "web":
        domain = str(application.get("canonical_domain") or "").strip()
        if domain:
            return f"web:{domain}"
    elif kind == "native":
        executable = PureWindowsPath(
            str(application.get("executable") or "").strip().replace("/", "\\")
        ).name.casefold()
        product = str(application.get("product_identity") or "").strip().casefold()
        parts = [part for part in (executable, product) if part]
        if parts:
            return f"native:{':'.join(parts)}"
    raise ValueError("reviewed asset application identity is unsupported")


def require_reviewed_native_executable_path(application: Mapping[str, Any]) -> str:
    if application.get("kind") != "native":
        raise ValueError("reviewed application must be native")
    path = normalize_windows_executable_path(application.get("executable_path"))
    if path is None:
        raise ValueError("reviewed native application requires an absolute executable path")
    return path


def validate_native_identity_fact(
    fact: object,
    *,
    target_window_handle: int,
    expected_process_id: int | None = None,
    expected_executable_path: str | None = None,
) -> dict[str, object] | None:
    if not isinstance(fact, Mapping) or set(fact) != {
        "contract_version",
        "provider",
        "status",
        "target_window_handle",
        "process_id",
        "process_create_time",
        "executable_path",
    }:
        return None
    if (
        type(target_window_handle) is not int
        or target_window_handle <= 0
        or fact.get("contract_version") != NATIVE_IDENTITY_CONTRACT_VERSION
        or fact.get("provider") != NATIVE_IDENTITY_PROVIDER
        or fact.get("status") != "observed"
        or type(fact.get("target_window_handle")) is not int
        or fact.get("target_window_handle") != target_window_handle
        or type(fact.get("process_id")) is not int
        or int(fact["process_id"]) <= 0
        or not isinstance(fact.get("process_create_time"), (int, float))
        or isinstance(fact.get("process_create_time"), bool)
        or not math.isfinite(float(fact["process_create_time"]))
        or float(fact["process_create_time"]) <= 0
    ):
        return None
    executable_path = normalize_windows_executable_path(fact.get("executable_path"))
    if executable_path is None:
        return None
    if expected_process_id is not None and fact["process_id"] != expected_process_id:
        return None
    if expected_executable_path is not None and executable_path != expected_executable_path:
        return None
    return {
        "contract_version": NATIVE_IDENTITY_CONTRACT_VERSION,
        "provider": NATIVE_IDENTITY_PROVIDER,
        "status": "observed",
        "target_window_handle": target_window_handle,
        "process_id": int(fact["process_id"]),
        "process_create_time": float(fact["process_create_time"]),
        "executable_path": executable_path,
    }


class WindowsNativeIdentityReader:
    def __init__(
        self,
        *,
        window_manager: Any | None = None,
        process_factory: Callable[[int], Any] | None = None,
    ) -> None:
        if window_manager is None:
            from app.core.window_manager import window_manager as active_window_manager

            window_manager = active_window_manager
        if process_factory is None:
            import psutil

            process_factory = psutil.Process
        self._window_manager = window_manager
        self._process_factory = process_factory

    @staticmethod
    def require_reviewed_executable_path(application: Mapping[str, Any]) -> str:
        return require_reviewed_native_executable_path(application)

    def read_identity(self, target_window_handle: int) -> dict[str, object]:
        handle = int(target_window_handle)
        stage = "binding_read"
        try:
            before = self._window_manager.get_bound_window()
            process_id = _bound_process_id(before, handle)
            stage = "process_identity_read"
            process = self._process_factory(process_id)
            executable_path = normalize_windows_executable_path(process.exe())
            created = process.create_time()
            if executable_path is None:
                raise ValueError("native process executable path is not absolute")
            if not isinstance(created, (int, float)) or isinstance(created, bool) or not math.isfinite(float(created)) or float(created) <= 0:
                raise ValueError("native process create time is invalid")
            stage = "binding_recheck"
            after = self._window_manager.get_bound_window()
            if _bound_process_id(after, handle) != process_id:
                raise ValueError("bound native process changed during identity read")
        except Exception as error:
            return {
                "contract_version": NATIVE_IDENTITY_CONTRACT_VERSION,
                "provider": NATIVE_IDENTITY_PROVIDER,
                "status": "unavailable",
                "target_window_handle": handle,
                "process_id": None,
                "process_create_time": None,
                "executable_path": None,
                "reason": f"{stage}_failed",
                "error_type": type(error).__name__,
            }
        return {
            "contract_version": NATIVE_IDENTITY_CONTRACT_VERSION,
            "provider": NATIVE_IDENTITY_PROVIDER,
            "status": "observed",
            "target_window_handle": handle,
            "process_id": process_id,
            "process_create_time": float(created),
            "executable_path": executable_path,
        }


def _bound_process_id(bound: object, target_window_handle: int) -> int:
    if bound is None or int(getattr(bound, "handle", 0)) != target_window_handle:
        raise ValueError("bound native window does not match target handle")
    process_id = getattr(bound, "process_id", None)
    if type(process_id) is not int or process_id <= 0:
        raise ValueError("bound native process identity is unavailable")
    return process_id


__all__ = [
    "NATIVE_IDENTITY_CONTRACT_VERSION",
    "NATIVE_IDENTITY_PROVIDER",
    "WindowsNativeIdentityReader",
    "asset_application_identity_key",
    "normalize_windows_executable_path",
    "require_reviewed_native_executable_path",
    "validate_native_identity_fact",
]
