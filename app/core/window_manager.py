from __future__ import annotations

import time
import math
import unicodedata
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from app.core.runtime_input_authority import runtime_backend_input_is_active

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
        self._ensure_window_mutation_authority(preparation_handle=getattr(self._bound_window, "handle", None))
        self._ensure_windows_backend()
        bound = self.get_bound_window()
        if bound is None:
            raise ValueError("No bound window available to focus")

        logger.info("Focusing bound window: handle={}, title={}", bound.handle, bound.title)
        activation_error = self._activate_window(bound.handle)

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
        ) from activation_error

    def prepare_bound_window(self, permit: object) -> BoundWindow:
        """消费本地人工确认许可，只恢复和聚焦同一进程窗口。"""
        from app.core.window_preparation import _window_preparation_scope

        with _window_preparation_scope(permit, self):
            return self.focus_bound_window()

    def prepare_maximized_bound_window(self, permit: object) -> BoundWindow:
        """消费本地人工确认许可，只最大化并聚焦同一进程窗口。"""
        from app.core.window_preparation import _window_preparation_scope

        with _window_preparation_scope(permit, self, operation="maximize"):
            return self.maximize_bound_window(focus=True)

    def validate_bound_capture_visibility(self, *, bound: BoundWindow, rect: dict[str, int],
                                          allow_partial: bool = False) -> dict[str, object]:
        """截图可排除局部遮挡；目标区域核验默认仍要求完全可见。"""
        base = {"contract_version": "bound_capture_visibility_v2", "allowed": False,
                "reason": "capture_visibility_unavailable", "bound_window_handle": bound.handle}
        try:
            self._ensure_windows_backend()
            if not win32gui.IsWindow(bound.handle) or not win32gui.IsWindowVisible(bound.handle):
                return {**base, "reason": "capture_window_unavailable"}
            if win32gui.IsIconic(bound.handle):
                return {**base, "reason": "capture_window_minimized"}
            expected = (bound.rect.left, bound.rect.top, bound.rect.right, bound.rect.bottom)
            if (self._capture_surface_rect(bound.handle) != expected
                    or self._get_process_id(bound.handle) != bound.process_id):
                return {**base, "reason": "capture_binding_changed"}
            if (set(rect) != {"left", "top", "width", "height"}
                    or any(type(value) is not int for value in rect.values())
                    or rect["width"] <= 0 or rect["height"] <= 0):
                return {**base, "reason": "capture_rectangle_invalid"}
            left, top = rect["left"], rect["top"]
            right, bottom = left + rect["width"], top + rect["height"]
            if not (expected[0] <= left < right <= expected[2]
                    and expected[1] <= top < bottom <= expected[3]):
                return {**base, "reason": "capture_rectangle_invalid"}
            current = int(win32gui.GetTopWindow(None) or 0)
            seen = set()
            regions = set()
            while current and current not in seen and len(seen) < 4096:
                if current == bound.handle:
                    if not regions:
                        return {**base, "allowed": True, "reason": "capture_window_visible"}
                    area = self._occluded_union_area(regions)
                    visible = 1.0 - area / (rect["width"] * rect["height"])
                    return {**base, "allowed": visible > 0,
                            "reason": "capture_window_partially_visible" if visible > 0 else "capture_window_occluded",
                            "visible_fraction": visible,
                            "occluded_regions": [
                                {"x": x1 - expected[0], "y": y1 - expected[1], "width": x2 - x1, "height": y2 - y1}
                                for x1, y1, x2, y2 in sorted(regions)]}
                seen.add(current)
                if win32gui.IsWindowVisible(current) and not win32gui.IsIconic(current):
                    # 绑定窗口拥有的原生弹出菜单属于同一可见表面，不应被截图遮罩。
                    # 无法验证 owner 链时保持原处理，避免把不明窗口误判为内部内容。
                    if current != bound.handle and self._is_owned_popup(current, bound.handle, include_shadow=True):
                        current = int(win32gui.GetWindow(current, win32con.GW_HWNDNEXT) or 0)
                        continue
                    other_left, other_top, other_right, other_bottom = win32gui.GetWindowRect(current)
                    if (max(left, other_left) < min(right, other_right)
                            and max(top, other_top) < min(bottom, other_bottom)):
                        if not allow_partial:
                            return {**base, "reason": "capture_window_occluded", "occluding_window_handle": current}
                        regions.add((max(left, other_left), max(top, other_top),
                                     min(right, other_right), min(bottom, other_bottom)))
                        if len(regions) > 256:
                            return base
                current = int(win32gui.GetWindow(current, win32con.GW_HWNDNEXT) or 0)
            return base
        except Exception as error:
            return {**base, "error_type": type(error).__name__}

    def _is_owned_popup(self, candidate_handle: int, bound_handle: int, *, include_shadow: bool = False) -> bool:
        """标准菜单可能没有 owner 链，此时核验活动 GUI 线程的菜单归属。"""
        try:
            get_ancestor = getattr(win32gui, "GetAncestor")
            root_owner_flag = getattr(win32con, "GA_ROOTOWNER", 3)
            root_owner = int(get_ancestor(candidate_handle, root_owner_flag) or candidate_handle)
            if root_owner == int(bound_handle):
                return True
            classes = {"#32768", "SysShadow"} if include_shadow else {"#32768"}
            if win32gui.GetClassName(candidate_handle) not in classes:
                return False
            thread, process = win32process.GetWindowThreadProcessId(bound_handle)
            if not thread or not process or tuple(win32process.GetWindowThreadProcessId(candidate_handle)) != (thread, process):
                return False
            state = self._read_gui_menu_state(thread)
            owner = state["menu_owner"]
            return bool(state["flags"] & 0x10 and state["active"] == bound_handle
                        and win32gui.GetForegroundWindow() == bound_handle and owner
                        and tuple(win32process.GetWindowThreadProcessId(owner)) == (thread, process)
                        and int(get_ancestor(owner, win32con.GA_ROOT) or owner) == bound_handle)
        except Exception:
            return False

    @staticmethod
    def _read_gui_menu_state(thread: int) -> dict[str, int]:
        """只读查询系统菜单所属窗口；不发送消息或更改前台。"""
        import ctypes
        from ctypes import wintypes

        class GUIThreadInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        *[(name, wintypes.HWND) for name in ("active", "focus", "capture", "menu_owner", "move_size", "caret")],
                        ("caret_rect", wintypes.RECT)]

        state = GUIThreadInfo()
        state.cbSize = ctypes.sizeof(state)
        query = ctypes.WinDLL("user32", use_last_error=True).GetGUIThreadInfo
        query.argtypes = [wintypes.DWORD, ctypes.POINTER(GUIThreadInfo)]
        query.restype = wintypes.BOOL
        if not query(thread, ctypes.byref(state)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {name: int(getattr(state, name) or 0) for name in ("flags", "active", "menu_owner")}

    @staticmethod
    def _occluded_union_area(regions: set[tuple[int, int, int, int]]) -> int:
        """按横向条带计算并集，重叠浮窗不重复扣减可见面积。"""
        edges = sorted({x for left, _, right, _ in regions for x in (left, right)})
        area = 0
        for left, right in zip(edges, edges[1:]):
            intervals = sorted((top, bottom) for x1, top, x2, bottom in regions if x1 < right and x2 > left)
            end = None
            height = 0
            for top, bottom in intervals:
                height += max(0, bottom - max(top, end if end is not None else top))
                end = max(bottom, end if end is not None else bottom)
            area += (right - left) * height
        return area

    def validate_bound_point_visibility(
        self,
        *,
        bound: BoundWindow,
        x: int,
        y: int,
        expected_owned_popup_handle: int | None = None,
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
        )
        # 原生菜单是 owned 顶层窗而非 child；同进程且根 owner 匹配才属于当前目标。
        owned_popup = bool(type(expected_owned_popup_handle) is int and expected_owned_popup_handle > 0
                           and hit_root == expected_owned_popup_handle and self._is_owned_popup(hit_root, int(bound.handle))
                           and bound.process_id and process_id == bound.process_id)
        if expected_owned_popup_handle is not None:
            return {**base, "allowed": owned_popup,
                    "reason": "target_point_owned_by_bound_popup" if owned_popup else "expected_popup_target_changed",
                    "expected_owned_popup_handle": expected_owned_popup_handle, "hit_window": hit_window}
        return {
            **base,
            "allowed": owned or owned_popup,
            "reason": ("target_point_owned_by_bound_window" if owned else
                       "target_point_owned_by_bound_popup" if owned_popup else "target_point_occluded"),
            "hit_window": hit_window,
        }

    def validate_bound_region_visibility(self, *, bound: BoundWindow,
                                         bbox: tuple[float, float, float, float]) -> dict[str, object]:
        """目标框按窗口坐标向外取整，不能用未遮挡的中心点替代完整目标。"""
        invalid = {"allowed": False, "reason": "target_region_invalid"}
        if (not isinstance(bbox, (tuple, list)) or len(bbox) != 4
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in bbox)):
            return invalid
        x, y, width, height = bbox
        if (x < 0 or y < 0 or width <= 0 or height <= 0
                or x + width > bound.rect.right - bound.rect.left
                or y + height > bound.rect.bottom - bound.rect.top):
            return invalid
        left, top = math.floor(x), math.floor(y)
        evidence = self.validate_bound_capture_visibility(bound=bound, rect={
            "left": bound.rect.left + left, "top": bound.rect.top + top,
            "width": math.ceil(x + width) - left, "height": math.ceil(y + height) - top})
        return {**evidence, "reason": "target_region_visible" if evidence.get("allowed") is True
                else "target_region_occluded" if evidence.get("reason") == "capture_window_occluded"
                else evidence.get("reason", "capture_visibility_unavailable")}

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
        self._ensure_window_mutation_authority()
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
        self._ensure_window_mutation_authority(
            preparation_handle=getattr(self._bound_window, "handle", None),
            preparation_operation="maximize",
        )
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

        def rejected(reason: str, **details) -> bool:
            # 只记录当前绑定的失败，不输出标题内容，也不刷屏记录枚举中的无关窗口。
            if self._bound_window is not None and wrapper.handle == self._bound_window.handle:
                logger.warning("Bound window candidate rejected: handle={} reason={} details={}",
                               wrapper.handle, reason, details)
            return False

        try:
            handle = wrapper.handle
            if not win32gui.IsWindowVisible(handle):  # type: ignore[union-attr]
                return rejected("not_visible")
            # GetParent 也返回弹窗 owner；只沿父子链判断，保留独立弹窗身份。
            if win32gui.GetAncestor(handle, win32con.GA_ROOT) != handle:  # type: ignore[union-attr]
                return rejected("not_top_level")
            if not wrapper.window_text().strip():
                return rejected("empty_title")
            return True
        except Exception as error:
            return rejected("candidate_query_failed", error_type=type(error).__name__,
                            winerror=getattr(error, "winerror", None))

    def _is_bound_handle_valid(self, handle: int) -> bool:
        """Return whether the bound handle still points to a visible top-level window."""
        if not WINDOWS_BACKEND_AVAILABLE:
            return False

        try:
            if hasattr(win32gui, "IsWindow") and not win32gui.IsWindow(handle):  # type: ignore[union-attr]
                return False
            if not win32gui.IsWindowVisible(handle):  # type: ignore[union-attr]
                return False
            # 绑定必须仍是原顶层窗口，不能把 owner 当作父控件。
            if win32gui.GetAncestor(handle, win32con.GA_ROOT) != handle:  # type: ignore[union-attr]
                return False
            return True
        except Exception:
            return False

    def _normalize_match_text(self, value: str) -> str:
        return "".join(char for char in value.strip().lower() if unicodedata.category(char) != "Cf")

    def _build_bound_window(self, wrapper: HwndWrapper) -> BoundWindow:
        """截图、UIA 投影和输入共用客户区原点；标题继续作为窗口元数据。"""
        self._ensure_windows_backend()
        left, top, right, bottom = self._capture_surface_rect(wrapper.handle)
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

    @staticmethod
    def _capture_surface_rect(handle: int, *, gui=None) -> tuple[int, int, int, int]:
        """排除非客户区透明边框；不可把其他窗口像素归属于当前应用。"""
        gui = win32gui if gui is None else gui
        left, top, right, bottom = gui.GetClientRect(handle)
        if right <= left or bottom <= top:
            raise ValueError("native_capture_client_area_unavailable")
        screen_left, screen_top = gui.ClientToScreen(handle, (left, top))
        screen_right, screen_bottom = gui.ClientToScreen(handle, (right, bottom))
        if screen_right <= screen_left or screen_bottom <= screen_top:
            raise ValueError("native_capture_client_area_invalid")
        return screen_left, screen_top, screen_right, screen_bottom

    def _activate_window(self, handle: int) -> Optional[Exception]:
        """Best-effort lightweight foreground activation for screen-coordinate capture."""
        self._ensure_window_mutation_authority(preparation_handle=handle)
        activation_error = None
        try:
            if hasattr(win32gui, "IsIconic") and win32gui.IsIconic(handle):  # type: ignore[union-attr]
                win32gui.ShowWindow(handle, win32con.SW_RESTORE)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Window restore check failed for handle {}: {}", handle, exc)
            activation_error = exc

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
            activation_error = exc
            from app.core.window_preparation import _window_preparation_is_active

            # 准备窗口不拥有键鼠权限，也不尝试合成按键回退。
            if not _window_preparation_is_active():
                if not self._retry_foreground_activation_with_alt_unlock(handle):
                    self._cycle_past_shell_notification_foreground(handle)
        finally:
            for thread_id in reversed(attached_threads):
                try:
                    win32process.AttachThreadInput(current_thread, thread_id, False)  # type: ignore[union-attr]
                except Exception as exc:
                    logger.warning("Input-thread detach failed for handle {}: {}", handle, exc)
        # 保留失败原因到前台核验；成功恢复不因中间警告被误判失败。
        return activation_error

    def _retry_foreground_activation_with_alt_unlock(self, handle: int) -> bool:
        """Retry foreground activation after a bounded synthetic Alt press."""
        if not runtime_backend_input_is_active():
            logger.warning(
                "Skipping synthetic Alt foreground retry without LiveController authority: {}",
                handle,
            )
            return False
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
        if not runtime_backend_input_is_active():
            logger.warning(
                "Skipping synthetic Alt-Tab foreground cycle without LiveController authority: {}",
                handle,
            )
            return False
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

    def _ensure_window_mutation_authority(
        self, *, preparation_handle: int | None = None, preparation_operation: str = "focus",
    ) -> None:
        """严格模式保留单次授权，本地关闭模式仅额外允许当前确切窗口聚焦。"""
        from app.core.window_preparation import _window_preparation_allowed

        if _window_preparation_allowed(self, preparation_handle, preparation_operation):
            return
        from app.core.local_input_policy import local_operator_input_is_allowed
        if preparation_operation == "focus" and preparation_handle is not None and local_operator_input_is_allowed(self):
            bound = self.get_bound_window()
            if bound is not None and preparation_handle == bound.handle:
                return
        if not runtime_backend_input_is_active():
            raise PermissionError(
                "Window mutation requires one-time LiveController authority via DesktopBackend"
            )


window_manager = WindowManager()
