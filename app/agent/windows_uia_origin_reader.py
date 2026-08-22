from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit


ORIGIN_OBSERVATION_CONTRACT_VERSION = "windows_uia_origin_observation_v1"
ORIGIN_OBSERVATION_PROVIDER = "windows_uia"


class WindowsUIAOriginReader:
    """从绑定浏览器窗口读取地址栏事实，不授予任何执行权限。"""

    def __init__(
        self,
        *,
        window_manager: Any | None = None,
        desktop_factory: Callable[..., Any] | None = None,
    ) -> None:
        if window_manager is None:
            from app.core.window_manager import window_manager as active_window_manager

            window_manager = active_window_manager
        self._window_manager = window_manager
        self._desktop_factory = desktop_factory

    def read_origin(self, target_window_handle: int) -> Mapping[str, object]:
        target_handle = int(target_window_handle)
        try:
            before = self._window_manager.get_bound_window()
        except Exception as exc:
            return self._unavailable(
                target_handle,
                reason="binding_read_failed",
                message="The current server-owned window binding could not be read.",
                error=exc,
            )
        if before is None:
            return self._unavailable(
                target_handle,
                reason="no_bound_window",
                message="No server-owned target window is currently bound.",
            )
        if int(before.handle) != target_handle:
            return self._unavailable(
                target_handle,
                reason="bound_window_mismatch",
                message="The requested window does not match the server-owned binding.",
            )
        process_id = self._valid_process_id(getattr(before, "process_id", None))
        if process_id is None:
            return self._unavailable(
                target_handle,
                reason="bound_process_unavailable",
                message="The bound window has no verifiable process identity.",
            )

        try:
            desktop = self._create_desktop()
        except (ImportError, ModuleNotFoundError) as exc:
            return self._unavailable(
                target_handle,
                process_id=process_id,
                reason="uia_dependency_unavailable",
                message="The Windows UIA dependency is unavailable.",
                error=exc,
            )
        except Exception as exc:
            return self._unavailable(
                target_handle,
                process_id=process_id,
                reason="uia_initialization_failed",
                message="The Windows UIA desktop could not be initialized.",
                error=exc,
            )

        controls: list[Any] = []
        origin: str | None = None
        source: str | None = None
        scan_error: Exception | None = None
        try:
            root = desktop.window(handle=target_handle)
            controls = list(root.descendants(control_type="Edit"))
            for control in controls:
                origin, source = self._origin_from_control(control)
                if origin is not None:
                    break
        except Exception as exc:
            scan_error = exc

        try:
            after = self._window_manager.get_bound_window()
        except Exception as exc:
            return self._unavailable(
                target_handle,
                process_id=process_id,
                edit_control_count=len(controls),
                reason="post_read_binding_failed",
                message="The server-owned window binding could not be revalidated after UIA inspection.",
                error=exc,
            )
        after_process_id = (
            self._valid_process_id(getattr(after, "process_id", None))
            if after is not None
            else None
        )
        if (
            after is None
            or int(after.handle) != target_handle
            or after_process_id != process_id
        ):
            return self._unavailable(
                target_handle,
                process_id=process_id,
                edit_control_count=len(controls),
                reason="bound_window_drift",
                message="The bound window or process changed during UIA inspection.",
            )
        if scan_error is not None:
            return self._unavailable(
                target_handle,
                process_id=process_id,
                edit_control_count=len(controls),
                reason="uia_read_failed",
                message="The exact bound window could not be inspected through Windows UIA.",
                error=scan_error,
            )
        if origin is None or source is None:
            return self._unavailable(
                target_handle,
                process_id=process_id,
                edit_control_count=len(controls),
                reason="no_http_origin",
                message="No valid HTTP or HTTPS origin was observed in bound-window Edit controls.",
            )
        return {
            "contract_version": ORIGIN_OBSERVATION_CONTRACT_VERSION,
            "provider": ORIGIN_OBSERVATION_PROVIDER,
            "status": "observed",
            "target_window_handle": target_handle,
            "bound_process_id": process_id,
            "origin": origin,
            "source": source,
            "edit_control_count": len(controls),
        }

    def _create_desktop(self) -> Any:
        if self._desktop_factory is not None:
            return self._desktop_factory(backend="uia")
        from pywinauto import Desktop

        return Desktop(backend="uia")

    def _origin_from_control(self, control: Any) -> tuple[str | None, str | None]:
        value = self._safe_control_text(control, "get_value")
        origin = self._normalize_origin(value)
        if origin is not None:
            return origin, "uia_edit_value"
        fallback = self._safe_control_text(control, "window_text")
        origin = self._normalize_origin(fallback)
        if origin is not None:
            return origin, "uia_edit_window_text"
        return None, None

    @staticmethod
    def _safe_control_text(control: Any, attribute: str) -> str | None:
        try:
            value = getattr(control, attribute, None)
            value = value() if callable(value) else value
        except Exception:
            return None
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    @staticmethod
    def _normalize_origin(value: str | None) -> str | None:
        if value is None or any(character.isspace() for character in value):
            return None
        if "\\" in value:
            return None
        try:
            parsed = urlsplit(value)
            scheme = parsed.scheme.lower()
            if scheme not in {"http", "https"} or not parsed.netloc:
                return None
            if parsed.username is not None or parsed.password is not None:
                return None
            raw_host = parsed.hostname
            port = parsed.port
        except (UnicodeError, ValueError):
            return None
        if not raw_host:
            return None
        if parsed.netloc.endswith(":") or (port is not None and port <= 0):
            return None
        host = WindowsUIAOriginReader._normalize_host(raw_host)
        if host is None:
            return None
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            port = None
        authority = f"[{host}]" if ":" in host else host
        if port is not None:
            authority = f"{authority}:{port}"
        return f"{scheme}://{authority}"

    @staticmethod
    def _normalize_host(value: str) -> str | None:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            try:
                host = value.rstrip(".").encode("idna").decode("ascii").lower()
            except UnicodeError:
                return None
            if not host or len(host) > 253:
                return None
            labels = host.split(".")
            if any(
                not label
                or len(label) > 63
                or label.startswith("-")
                or label.endswith("-")
                or re.fullmatch(r"[a-z0-9-]+", label) is None
                for label in labels
            ):
                return None
            return host
        return address.compressed.lower()

    @staticmethod
    def _valid_process_id(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    @staticmethod
    def _unavailable(
        target_window_handle: int,
        *,
        reason: str,
        message: str,
        process_id: int | None = None,
        edit_control_count: int = 0,
        error: Exception | None = None,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "contract_version": ORIGIN_OBSERVATION_CONTRACT_VERSION,
            "provider": ORIGIN_OBSERVATION_PROVIDER,
            "status": "unavailable",
            "target_window_handle": target_window_handle,
            "bound_process_id": process_id,
            "origin": None,
            "source": None,
            "edit_control_count": edit_control_count,
            "reason": reason,
            "message": message,
        }
        if error is not None:
            result["error_type"] = type(error).__name__
        return result
