from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger

WINDOWS_BACKEND_AVAILABLE = False
WINDOWS_BACKEND_IMPORT_ERROR: Optional[str] = None

try:
    from pywinauto import Desktop
    from pywinauto.controls.hwndwrapper import HwndWrapper
    import win32gui
    import win32process

    WINDOWS_BACKEND_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on runtime platform/environment
    Desktop = None  # type: ignore[assignment]
    HwndWrapper = object  # type: ignore[assignment]
    win32gui = None  # type: ignore[assignment]
    win32process = None  # type: ignore[assignment]
    WINDOWS_BACKEND_IMPORT_ERROR = str(exc)


@dataclass
class WindowRect:
    """Represents a window rectangle in screen coordinates."""

    left: int
    top: int
    right: int
    bottom: int


@dataclass
class BoundWindow:
    """Represents the currently bound target window."""

    handle: int
    title: Optional[str]
    process_id: Optional[int]
    process_name: Optional[str]
    rect: WindowRect
    is_active: bool


class WindowManager:
    """Manage the single in-memory bound window session for the MVP.

    This manager is intentionally simple:
    - one bound window only
    - in-memory state only
    - title/process matching over visible top-level windows
    """

    def __init__(self) -> None:
        self._bound_window: Optional[BoundWindow] = None

    def bind_window(self, process_name: Optional[str], title: Optional[str]) -> BoundWindow:
        """Find and bind a top-level visible window by process name and/or title."""
        self._ensure_windows_backend()
        logger.info("Binding window: process_name={}, title={}", process_name, title)
        wrapper = self._find_window(process_name=process_name, title=title)
        bound = self._build_bound_window(wrapper)
        self._bound_window = bound
        return bound

    def get_bound_window(self) -> Optional[BoundWindow]:
        """Return the currently bound window, if any."""
        if self._bound_window is None:
            return None

        if not WINDOWS_BACKEND_AVAILABLE:
            return self._bound_window

        try:
            wrapper = HwndWrapper(self._bound_window.handle)  # type: ignore[operator]
            self._bound_window = self._build_bound_window(wrapper)
        except Exception as exc:  # pragma: no cover - defensive refresh path
            logger.warning("Failed to refresh bound window state: {}", exc)

        return self._bound_window

    def focus_bound_window(self) -> BoundWindow:
        """Bring the currently bound window to the foreground and refresh its state."""
        self._ensure_windows_backend()
        bound = self.get_bound_window()
        if bound is None:
            raise ValueError("No bound window available to focus")

        logger.info("Focusing bound window: handle={}, title={}", bound.handle, bound.title)
        try:
            win32gui.ShowWindow(bound.handle, 9)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("ShowWindow failed for handle {}: {}", bound.handle, exc)

        try:
            win32gui.SetForegroundWindow(bound.handle)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("SetForegroundWindow failed for handle {}: {}", bound.handle, exc)

        time.sleep(0.25)
        refreshed = self.get_bound_window()
        if refreshed is None:
            raise ValueError("Bound window disappeared after focus attempt")
        return refreshed

    def list_visible_windows(self) -> list[dict[str, Optional[int | str]]]:
        """Return visible top-level candidate windows for debugging and matching."""
        self._ensure_windows_backend()
        candidates: list[dict[str, Optional[int | str]]] = []

        for wrapper in Desktop(backend="win32").windows():  # type: ignore[operator]
            if not self._is_candidate_window(wrapper):
                continue

            window_title = wrapper.window_text() or ""
            process_id = self._get_process_id(wrapper.handle)
            process_name = self._get_process_name(process_id)
            candidates.append(
                {
                    "handle": int(wrapper.handle),
                    "title": window_title or None,
                    "process_id": process_id,
                    "process_name": process_name,
                }
            )

        logger.info("Enumerated {} visible top-level windows", len(candidates))
        return candidates

    def _find_window(self, process_name: Optional[str], title: Optional[str]) -> HwndWrapper:
        """Locate a visible top-level window matching the provided filters."""
        self._ensure_windows_backend()
        title_query = title.strip().lower() if title else None
        process_query = process_name.strip().lower() if process_name else None

        candidates: list[tuple[HwndWrapper, str, Optional[int], Optional[str]]] = []
        for wrapper in Desktop(backend="win32").windows():  # type: ignore[operator]
            if not self._is_candidate_window(wrapper):
                continue

            window_title = wrapper.window_text() or ""
            pid = self._get_process_id(wrapper.handle)
            current_process_name = self._get_process_name(pid)
            candidates.append((wrapper, window_title, pid, current_process_name))

        logger.info(
            "Window match request: process_name={}, title={}, candidate_count={}",
            process_name,
            title,
            len(candidates),
        )
        for wrapper, window_title, pid, current_process_name in candidates:
            logger.info(
                "Window candidate: handle={}, title={}, process_id={}, process_name={}",
                wrapper.handle,
                window_title,
                pid,
                current_process_name,
            )

        if not title_query and not process_query:
            raise ValueError("No matching criteria provided")

        for wrapper, window_title, pid, current_process_name in candidates:
            title_match = True
            process_match = True

            if title_query:
                title_match = title_query in window_title.lower()
            if process_query:
                process_match = current_process_name is not None and current_process_name.lower() == process_query

            if title_match and process_match:
                logger.info(
                    "Matched window: handle={}, title={}, process_id={}, process_name={}",
                    wrapper.handle,
                    window_title,
                    pid,
                    current_process_name,
                )
                return wrapper

        raise ValueError("No matching visible top-level window found")

    def _is_candidate_window(self, wrapper: HwndWrapper) -> bool:
        """Return whether a window is a usable top-level candidate."""
        if not WINDOWS_BACKEND_AVAILABLE:
            return False

        try:
            handle = wrapper.handle
            if not win32gui.IsWindowVisible(handle):  # type: ignore[union-attr]
                return False
            if win32gui.GetParent(handle) != 0:  # type: ignore[union-attr]
                return False
            if not wrapper.window_text().strip():
                return False
            return True
        except Exception:
            return False

    def _build_bound_window(self, wrapper: HwndWrapper) -> BoundWindow:
        """Build a serializable bound-window snapshot from a wrapper."""
        self._ensure_windows_backend()
        left, top, right, bottom = win32gui.GetWindowRect(wrapper.handle)  # type: ignore[union-attr]
        process_id = self._get_process_id(wrapper.handle)
        process_name = self._get_process_name(process_id)
        active_handle = win32gui.GetForegroundWindow()  # type: ignore[union-attr]

        return BoundWindow(
            handle=int(wrapper.handle),
            title=wrapper.window_text() or None,
            process_id=process_id,
            process_name=process_name,
            rect=WindowRect(left=left, top=top, right=right, bottom=bottom),
            is_active=active_handle == wrapper.handle,
        )

    def _get_process_id(self, handle: int) -> Optional[int]:
        """Return the process id for a window handle."""
        if not WINDOWS_BACKEND_AVAILABLE:
            return None

        try:
            _, process_id = win32process.GetWindowThreadProcessId(handle)  # type: ignore[union-attr]
            return int(process_id)
        except Exception:
            return None

    def _get_process_name(self, process_id: Optional[int]) -> Optional[str]:
        """Return the executable name for a process id, if available."""
        if process_id is None:
            return None

        try:
            import psutil

            return psutil.Process(process_id).name()
        except Exception:
            return None

    def _ensure_windows_backend(self) -> None:
        """Ensure Windows-only automation dependencies are available."""
        if not WINDOWS_BACKEND_AVAILABLE:
            raise RuntimeError(
                "Windows automation backend is unavailable. "
                f"Import error: {WINDOWS_BACKEND_IMPORT_ERROR}"
            )


window_manager = WindowManager()
