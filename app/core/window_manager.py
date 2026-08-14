from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass
from typing import Optional

from loguru import logger

WINDOWS_BACKEND_AVAILABLE = False
WINDOWS_BACKEND_IMPORT_ERROR: Optional[str] = None

try:
    from pywinauto import Desktop
    from pywinauto.controls.hwndwrapper import HwndWrapper
    import win32api
    import win32con
    import win32gui
    import win32process

    WINDOWS_BACKEND_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on runtime platform/environment
    Desktop = None  # type: ignore[assignment]
    HwndWrapper = object  # type: ignore[assignment]
    win32api = None  # type: ignore[assignment]
    win32con = None  # type: ignore[assignment]
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

    def bind_window_by_handle(self, handle: int) -> BoundWindow:
        """Bind a specific visible top-level window handle."""
        self._ensure_windows_backend()
        if not self._is_bound_handle_valid(handle):
            raise ValueError(f"Window handle is not valid: {handle}")
        wrapper = HwndWrapper(handle)  # type: ignore[operator]
        if not self._is_candidate_window(wrapper):
            raise ValueError(f"Window handle is not a visible top-level titled window: {handle}")
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
            if not self._is_bound_handle_valid(self._bound_window.handle):
                logger.warning("Bound window handle is no longer valid: {}", self._bound_window.handle)
                self._bound_window = None
                return None

            wrapper = HwndWrapper(self._bound_window.handle)  # type: ignore[operator]
            if not self._is_candidate_window(wrapper):
                logger.warning("Bound window is no longer a visible top-level titled window: {}", self._bound_window.handle)
                self._bound_window = None
                return None

            self._bound_window = self._build_bound_window(wrapper)
        except Exception as exc:  # pragma: no cover - defensive refresh path
            logger.warning("Failed to refresh bound window state; clearing stale binding: {}", exc)
            self._bound_window = None

        return self._bound_window

    def focus_bound_window(self) -> BoundWindow:
        """Bring the currently bound window to the foreground and refresh its state."""
        self._ensure_windows_backend()
        bound = self.get_bound_window()
        if bound is None:
            raise ValueError("No bound window available to focus")

        logger.info("Focusing bound window: handle={}, title={}", bound.handle, bound.title)
        self._activate_window(bound.handle)

        refreshed: Optional[BoundWindow] = None
        active_handle = 0
        for _attempt in range(5):
            time.sleep(0.1)
            refreshed = self.get_bound_window()
            if refreshed is None:
                raise ValueError("Bound window disappeared after focus attempt")
            active_handle = int(win32gui.GetForegroundWindow() or 0)  # type: ignore[union-attr]
            active_root = active_handle
            if active_handle and hasattr(win32gui, "GetAncestor"):
                try:
                    active_root = int(win32gui.GetAncestor(active_handle, win32con.GA_ROOT) or active_handle)  # type: ignore[union-attr]
                except Exception:
                    active_root = active_handle
            if active_handle == refreshed.handle or active_root == refreshed.handle:
                return refreshed

        raise RuntimeError(
            "Bound window foreground verification failed: "
            f"expected_handle={bound.handle}, actual_foreground_handle={active_handle}"
        )

    def validate_bound_point_visibility(
        self,
        *,
        bound: BoundWindow,
        x: int,
        y: int,
    ) -> dict[str, object]:
        """验证窗口坐标点当前是否仍由绑定窗口拥有。"""
        self._ensure_windows_backend()
        screen_x = int(bound.rect.left) + int(x)
        screen_y = int(bound.rect.top) + int(y)
        base = {
            "contract_version": "bound_point_visibility_v1",
            "window_point": {"x": int(x), "y": int(y)},
            "screen_point": {"x": screen_x, "y": screen_y},
            "bound_window": {
                "handle": int(bound.handle),
                "title": bound.title,
                "process_id": bound.process_id,
                "process_name": bound.process_name,
            },
        }
        if not (
            int(bound.rect.left) <= screen_x < int(bound.rect.right)
            and int(bound.rect.top) <= screen_y < int(bound.rect.bottom)
        ):
            return {**base, "allowed": False, "reason": "target_point_outside_bound_window"}

        try:
            hit_handle = int(win32gui.WindowFromPoint((screen_x, screen_y)) or 0)  # type: ignore[union-attr]
            hit_root = int(win32gui.GetAncestor(hit_handle, win32con.GA_ROOT) or hit_handle)  # type: ignore[union-attr]
            hit_root_owner = int(win32gui.GetAncestor(hit_handle, win32con.GA_ROOTOWNER) or hit_root)  # type: ignore[union-attr]
            is_child = bool(win32gui.IsChild(int(bound.handle), hit_handle))  # type: ignore[union-attr]
            title = str(win32gui.GetWindowText(hit_root) or "")  # type: ignore[union-attr]
            process_id = self._get_process_id(hit_root)
            process_name = self._get_process_name(process_id)
        except Exception as exc:
            return {
                **base,
                "allowed": False,
                "reason": "target_point_visibility_unavailable",
                "error": str(exc),
            }

        hit_window = {
            "handle": hit_handle,
            "root_handle": hit_root,
            "root_owner_handle": hit_root_owner,
            "title": title or None,
            "process_id": process_id,
            "process_name": process_name,
        }
        owned = bool(
            hit_handle == int(bound.handle)
            or is_child
            or hit_root == int(bound.handle)
            or hit_root_owner == int(bound.handle)
        )
        return {
            **base,
            "allowed": owned,
            "reason": "target_point_owned_by_bound_window" if owned else "target_point_occluded",
            "hit_window": hit_window,
        }

    def resize_bound_window(
        self,
        *,
        width: int,
        height: int,
        left: Optional[int] = None,
        top: Optional[int] = None,
        focus: bool = True,
    ) -> BoundWindow:
        """Resize the currently bound window and refresh its bound-window snapshot."""
        self._ensure_windows_backend()
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")

        bound = self.get_bound_window()
        if bound is None:
            raise ValueError("No bound window available to resize")

        x = int(bound.rect.left if left is None else left)
        y = int(bound.rect.top if top is None else top)
        logger.info(
            "Resizing bound window: handle={}, title={}, x={}, y={}, width={}, height={}",
            bound.handle,
            bound.title,
            x,
            y,
            width,
            height,
        )
        try:
            win32gui.ShowWindow(bound.handle, win32con.SW_RESTORE)  # type: ignore[union-attr]
            win32gui.SetWindowPos(  # type: ignore[union-attr]
                bound.handle,
                win32con.HWND_NOTOPMOST,  # type: ignore[union-attr]
                x,
                y,
                int(width),
                int(height),
                win32con.SWP_SHOWWINDOW,  # type: ignore[union-attr]
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to resize bound window: {exc}") from exc

        time.sleep(0.2)
        if focus:
            return self.focus_bound_window()
        refreshed = self.get_bound_window()
        if refreshed is None:
            raise ValueError("Bound window disappeared after resize")
        return refreshed

    def maximize_bound_window(self, *, focus: bool = True) -> BoundWindow:
        """Maximize the currently bound window and refresh its bound-window snapshot."""
        self._ensure_windows_backend()
        bound = self.get_bound_window()
        if bound is None:
            raise ValueError("No bound window available to maximize")

        logger.info("Maximizing bound window: handle={}, title={}", bound.handle, bound.title)
        try:
            win32gui.ShowWindow(bound.handle, win32con.SW_MAXIMIZE)  # type: ignore[union-attr]
        except Exception as exc:
            raise RuntimeError(f"Failed to maximize bound window: {exc}") from exc

        time.sleep(0.2)
        if focus:
            return self.focus_bound_window()
        refreshed = self.get_bound_window()
        if refreshed is None:
            raise ValueError("Bound window disappeared after maximize")
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
        title_query = self._normalize_match_text(title) if title else None
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
                title_match = title_query in self._normalize_match_text(window_title)
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

    def _is_bound_handle_valid(self, handle: int) -> bool:
        """Return whether the bound handle still points to a visible top-level window."""
        if not WINDOWS_BACKEND_AVAILABLE:
            return False

        try:
            if hasattr(win32gui, "IsWindow") and not win32gui.IsWindow(handle):  # type: ignore[union-attr]
                return False
            if not win32gui.IsWindowVisible(handle):  # type: ignore[union-attr]
                return False
            if win32gui.GetParent(handle) != 0:  # type: ignore[union-attr]
                return False
            return True
        except Exception:
            return False

    def _normalize_match_text(self, value: str) -> str:
        return "".join(char for char in value.strip().lower() if unicodedata.category(char) != "Cf")

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

    def _activate_window(self, handle: int) -> None:
        """Best-effort lightweight foreground activation for screen-coordinate capture."""
        try:
            if hasattr(win32gui, "IsIconic") and win32gui.IsIconic(handle):  # type: ignore[union-attr]
                win32gui.ShowWindow(handle, win32con.SW_RESTORE)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Window restore check failed for handle {}: {}", handle, exc)

        attached_threads: list[int] = []
        current_thread = 0
        thread_ids: tuple[int, int] = (0, 0)
        try:
            current_thread = int(win32api.GetCurrentThreadId())  # type: ignore[union-attr]
            foreground_handle = int(win32gui.GetForegroundWindow() or 0)  # type: ignore[union-attr]
            foreground_thread = (
                int(win32process.GetWindowThreadProcessId(foreground_handle)[0])  # type: ignore[union-attr]
                if foreground_handle
                else 0
            )
            target_thread = int(win32process.GetWindowThreadProcessId(handle)[0])  # type: ignore[union-attr]
            thread_ids = (foreground_thread, target_thread)
        except Exception as exc:
            logger.warning("Input-thread discovery failed for handle {}: {}", handle, exc)

        for thread_id in thread_ids:
            if not thread_id or thread_id == current_thread or thread_id in attached_threads:
                continue
            try:
                win32process.AttachThreadInput(current_thread, thread_id, True)  # type: ignore[union-attr]
            except Exception as exc:
                logger.warning(
                    "Input-thread attachment failed for handle {}, target_thread={}: {}",
                    handle,
                    thread_id,
                    exc,
                )
                continue
            attached_threads.append(thread_id)

        try:
            win32gui.BringWindowToTop(handle)  # type: ignore[union-attr]
            win32gui.SetWindowPos(  # type: ignore[union-attr]
                handle,
                win32con.HWND_TOPMOST,  # type: ignore[union-attr]
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,  # type: ignore[union-attr]
            )
            win32gui.SetWindowPos(  # type: ignore[union-attr]
                handle,
                win32con.HWND_NOTOPMOST,  # type: ignore[union-attr]
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,  # type: ignore[union-attr]
            )
            win32gui.SetForegroundWindow(handle)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Foreground activation failed for handle {}: {}", handle, exc)
            if not self._retry_foreground_activation_with_alt_unlock(handle):
                self._cycle_past_shell_notification_foreground(handle)
        finally:
            for thread_id in reversed(attached_threads):
                try:
                    win32process.AttachThreadInput(current_thread, thread_id, False)  # type: ignore[union-attr]
                except Exception as exc:
                    logger.warning("Input-thread detach failed for handle {}: {}", handle, exc)

    def _retry_foreground_activation_with_alt_unlock(self, handle: int) -> bool:
        """Retry foreground activation after a bounded synthetic Alt press."""
        alt_pressed = False
        activated = False
        try:
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)  # type: ignore[union-attr]
            alt_pressed = True
            win32gui.SetForegroundWindow(handle)  # type: ignore[union-attr]
            activated = True
        except Exception as exc:
            logger.warning("Alt-unlock foreground retry failed for handle {}: {}", handle, exc)
        finally:
            if alt_pressed:
                try:
                    win32api.keybd_event(  # type: ignore[union-attr]
                        win32con.VK_MENU,
                        0,
                        win32con.KEYEVENTF_KEYUP,
                        0,
                    )
                except Exception as exc:
                    logger.warning("Alt-unlock key release failed for handle {}: {}", handle, exc)
        return activated

    def _cycle_past_shell_notification_foreground(self, handle: int) -> bool:
        """Cycle away from an OS notification overlay and verify the bound target wins foreground."""
        foreground_handle = int(win32gui.GetForegroundWindow() or 0)  # type: ignore[union-attr]
        if not foreground_handle or foreground_handle == handle:
            return foreground_handle == handle

        process_name = (self._get_process_name(self._get_process_id(foreground_handle)) or "").lower()
        if process_name not in {"shellexperiencehost.exe", "startmenuexperiencehost.exe"}:
            return False

        alt_pressed = False
        tab_pressed = False
        try:
            win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)  # type: ignore[union-attr]
            alt_pressed = True
            win32api.keybd_event(win32con.VK_TAB, 0, 0, 0)  # type: ignore[union-attr]
            tab_pressed = True
        except Exception as exc:
            logger.warning("Shell-notification foreground cycle failed for handle {}: {}", handle, exc)
        finally:
            if tab_pressed:
                try:
                    win32api.keybd_event(  # type: ignore[union-attr]
                        win32con.VK_TAB,
                        0,
                        win32con.KEYEVENTF_KEYUP,
                        0,
                    )
                except Exception as exc:
                    logger.warning("Shell-notification Tab release failed for handle {}: {}", handle, exc)
            if alt_pressed:
                try:
                    win32api.keybd_event(  # type: ignore[union-attr]
                        win32con.VK_MENU,
                        0,
                        win32con.KEYEVENTF_KEYUP,
                        0,
                    )
                except Exception as exc:
                    logger.warning("Shell-notification Alt release failed for handle {}: {}", handle, exc)

        time.sleep(0.1)
        return int(win32gui.GetForegroundWindow() or 0) == handle  # type: ignore[union-attr]

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
