from __future__ import annotations

import ctypes
from contextlib import contextmanager
from contextvars import ContextVar
from io import BytesIO
from pathlib import Path
import time
from threading import get_ident
from typing import Any, Optional

from loguru import logger

from app.core.runtime_input_authority import runtime_backend_input_is_active
from app.core.editing_keys import EDITING_KEY_CHORDS, EXTENDED_EDITING_KEYS
from app.core.window_manager import window_manager
from modules.click.geometry import resolve_window_and_screen_point

WINDOWS_INPUT_AVAILABLE = False
WINDOWS_INPUT_IMPORT_ERROR: Optional[str] = None

try:
    import win32api
    import win32con
    import win32clipboard
    import win32gui

    WINDOWS_INPUT_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on runtime platform/environment
    win32api = None  # type: ignore[assignment]
    win32con = None  # type: ignore[assignment]
    win32clipboard = None  # type: ignore[assignment]
    win32gui = None  # type: ignore[assignment]
    WINDOWS_INPUT_IMPORT_ERROR = str(exc)


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_A = 0x41
VK_RETURN = 0x0D
VK_V = 0x56
CF_DIB = 8
SM_CXSCREEN = 0
SM_CYSCREEN = 1
CLIPBOARD_PASTE_SETTLE_SECONDS = 0.15
CLIPBOARD_OPEN_RETRY_SECONDS = 0.03
CLIPBOARD_OPEN_ATTEMPTS = 8
CLIPBOARD_VERIFY_TIMEOUT_SECONDS = 0.5
CLIPBOARD_VERIFY_RETRY_SECONDS = 0.03
TASKBAR_ACTIVATION_SETTLE_SECONDS = 0.1
TASKBAR_ACTIVATION_VERIFY_INTERVAL_SECONDS = 0.05
TASKBAR_ACTIVATION_VERIFY_TIMEOUT_SECONDS = 1.0

_CLICK_RELEASE = ContextVar("current_click_mouse_release", default=None)
_KEY_RELEASE = ContextVar("current_keyboard_release", default=None)


@contextmanager
def _click_release_scope(controller, button):
    # 只在同步点击的 finally 中清理同一按钮；不能用于下一次输入。
    state = {"controller": controller, "thread": get_ident(), "down": controller._button_down_flag(button),
             "up": controller._button_up_flag(button), "attempted": False, "releasing": False,
             "used": False, "active": True}
    token = _CLICK_RELEASE.set(state)
    try:
        yield state
    finally:
        state["active"] = False
        _CLICK_RELEASE.reset(token)


def _pending_click_release(controller, flags):
    state = _CLICK_RELEASE.get()
    return (state if state is not None and state["active"] and state["controller"] is controller
            and state["thread"] == get_ident() and state["attempted"] and state["releasing"]
            and not state["used"] and flags == state["up"] else None)


class KeyboardForegroundMismatchError(RuntimeError):
    """保存校验当刻的前台差异，不事后重读或暗中切换窗口。"""

    def __init__(self, expected_handle: int, observed_handle: int) -> None:
        self.evidence = {"expected_window_handle": expected_handle,
                         "observed_foreground_handle": observed_handle,
                         "stage": "before_keyboard_dispatch"}
        super().__init__("Text target is not the foreground window before keyboard dispatch")


class TargetPointOccludedError(RuntimeError):
    """点击点被外部窗口遮挡或无法验证时，阻止输入下发。"""

    def __init__(self, evidence: dict[str, Any]) -> None:
        self.evidence = evidence
        super().__init__(str(evidence.get("reason") or "target_point_occluded"))


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]


class InputController:
    """Dispatch input actions to the currently bound window."""

    def move_mouse(self, x: int, y: int) -> dict[str, Any]:
        """Move mouse to a point relative to the bound window."""
        self._ensure_windows_input()
        bound = self._require_bound_window()
        point = self._resolve_window_and_screen_point(bound=bound, x=x, y=y)

        logger.info(
            "Moving mouse: handle={}, window_point=({}, {}), screen_point=({}, {})",
            bound.handle,
            x,
            y,
            point["screen_x"],
            point["screen_y"],
        )

        cursor_before = win32api.GetCursorPos()  # type: ignore[union-attr]
        self._focus_window(bound.handle)
        self._send_move(point["screen_x"], point["screen_y"])
        cursor_after = win32api.GetCursorPos()  # type: ignore[union-attr]
        return {
            "moved": True,
            "window_point": {"x": point["window_x"], "y": point["window_y"]},
            "screen_point": {"x": point["screen_x"], "y": point["screen_y"]},
            "cursor_before": {"x": int(cursor_before[0]), "y": int(cursor_before[1])},
            "cursor_after": {"x": int(cursor_after[0]), "y": int(cursor_after[1])},
        }

    def mouse_down(self, button: str = "left") -> dict[str, Any]:
        self._ensure_windows_input()
        dispatched = self._send_mouse_flags(self._button_down_flag(button))
        pos = win32api.GetCursorPos()  # type: ignore[union-attr]
        return {"button": button, "state": "down", "cursor": {"x": int(pos[0]), "y": int(pos[1])},
                "dispatched_monotonic_ns": dispatched}

    def mouse_up(self, button: str = "left") -> dict[str, Any]:
        flag = self._button_up_flag(button)
        if _pending_click_release(self, flag) is None:
            self._ensure_windows_input()
        self._send_mouse_flags(flag)
        pos = win32api.GetCursorPos()  # type: ignore[union-attr]
        return {"button": button, "state": "up", "cursor": {"x": int(pos[0]), "y": int(pos[1])}}

    def click_point(
        self,
        x: int,
        y: int,
        *,
        button: str = "left",
        move_before_click: bool = True,
        settle_ms: int = 100,
        hold_ms: int = 60,
        popup_guard: Any | None = None,
        target_bbox: tuple[float, float, float, float] | None = None,
        click_count: int = 1,
        expected_owned_popup_handle: int | None = None,
    ) -> dict[str, Any]:
        """Click a point relative to the bound window using a realistic pointer sequence."""
        if type(click_count) is not int or click_count not in (1, 2):
            raise ValueError("click_count must be an integer of 1 or 2")
        self._ensure_windows_input()
        bound = self._require_bound_window()
        if popup_guard is not None:
            from app.agent.popup_click_guard import PopupClickGuard

            if type(popup_guard) is not PopupClickGuard:
                raise ValueError("popup_guard must be a PopupClickGuard")
            popup_guard.validate_command(window_handle=int(bound.handle), click_point=(x, y))
            expectation = popup_guard.expectation
            rect = bound.rect
            if (
                int(bound.handle) != expectation.popup_handle
                or getattr(bound, "process_id", None) != expectation.process_id
                or (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)) != expectation.popup_rect
            ):
                raise ValueError("popup guard does not match bound popup")
        point = self._resolve_window_and_screen_point(bound=bound, x=x, y=y)

        logger.info(
            "Clicking bound window point via SendInput: handle={}, button={}, window_point=({}, {}), screen_point=({}, {}), move_first={}, settle_ms={}, hold_ms={}",
            bound.handle,
            button,
            x,
            y,
            point["screen_x"],
            point["screen_y"],
            move_before_click,
            settle_ms,
            hold_ms,
        )

        foreground_before = int(win32gui.GetForegroundWindow())  # type: ignore[union-attr]
        if popup_guard is not None:
            popup_guard.verify_current()
            set_foreground_ok = None
        else:
            set_foreground_ok = self._focus_window(bound.handle)
        cursor_before = win32api.GetCursorPos()  # type: ignore[union-attr]

        if move_before_click:
            self._send_move(point["screen_x"], point["screen_y"])
            if settle_ms > 0:
                time.sleep(settle_ms / 1000.0)
            move_cursor_after = win32api.GetCursorPos()  # type: ignore[union-attr]
            move_result = {
                "performed": True,
                "cursor_after_move": {"x": int(move_cursor_after[0]), "y": int(move_cursor_after[1])},
            }
        else:
            move_result = {"performed": False}

        point_visibility = window_manager.validate_bound_point_visibility(
            bound=bound,
            x=point["window_x"],
            y=point["window_y"],
            **({"expected_owned_popup_handle": expected_owned_popup_handle} if expected_owned_popup_handle is not None else {}),
        )
        if not point_visibility.get("allowed"):
            raise TargetPointOccludedError(point_visibility)
        if target_bbox is not None:
            region_visibility = window_manager.validate_bound_region_visibility(bound=bound, bbox=target_bbox)
            if region_visibility.get("allowed") is not True:
                raise TargetPointOccludedError({**region_visibility,
                    "point_visibility": point_visibility,
                    "region_visibility": region_visibility})
        if popup_guard is not None:
            hit_window = point_visibility.get("hit_window")
            if not isinstance(hit_window, dict) or hit_window.get("root_handle") != popup_guard.expectation.popup_handle:
                raise TargetPointOccludedError({
                    **point_visibility,
                    "allowed": False,
                    "reason": "target_point_not_owned_by_exact_popup_root",
                })

        # 按下前最后核对窗口与鼠标，拒绝等待期间发生的漂移。
        current_bound = window_manager.get_bound_window()
        if popup_guard is not None:
            popup_guard.verify_current()
        expected_foreground_handle = (
            popup_guard.expectation.parent_handle if popup_guard is not None else int(bound.handle)
        )
        if (
            current_bound is None
            or current_bound.handle != bound.handle
            or current_bound.process_id != bound.process_id
            or current_bound.rect != bound.rect
            or int(win32gui.GetForegroundWindow()) != expected_foreground_handle
        ):
            raise RuntimeError("Bound window changed immediately before mouse down")
        current_cursor = tuple(win32api.GetCursorPos())
        if current_cursor != (point["screen_x"], point["screen_y"]):
            raise RuntimeError("Mouse cursor position changed immediately before mouse down: "
                f"expected_screen=({point['screen_x']}, {point['screen_y']}), "
                f"observed_screen={current_cursor}, after_move={move_result.get('cursor_after_move')}")

        double_click_time_ms = self._double_click_time_ms() if click_count == 2 else None
        effective_hold_ms = int(max(0, hold_ms))
        inter_click_gap_ms = 0
        if double_click_time_ms is not None:
            # Keep the complete press interval within the Windows double-click window.
            effective_hold_ms = min(effective_hold_ms, double_click_time_ms)
            inter_click_gap_ms = min(50, max(0, double_click_time_ms - effective_hold_ms))

        click_events: list[dict[str, Any]] = []
        completed_clicks = 0
        input_attempted = False
        try:
            for index in range(click_count):
                if index:
                    if inter_click_gap_ms > 0:
                        time.sleep(inter_click_gap_ms / 1000.0)
                    current = window_manager.get_bound_window()
                    if popup_guard is not None:
                        popup_guard.verify_current()
                    if (
                        current is None
                        or current.handle != bound.handle
                        or current.process_id != bound.process_id
                        or current.rect != bound.rect
                        or int(win32gui.GetForegroundWindow()) != expected_foreground_handle
                    ):
                        raise RuntimeError("Bound window changed before second click")
                    if tuple(win32api.GetCursorPos()) != (point["screen_x"], point["screen_y"]):
                        raise RuntimeError("Mouse cursor position changed before second click")
                    second_visibility = window_manager.validate_bound_point_visibility(
                        bound=current, x=point["window_x"], y=point["window_y"],
                        **({"expected_owned_popup_handle": expected_owned_popup_handle} if expected_owned_popup_handle is not None else {}))
                    if not second_visibility.get("allowed"):
                        raise TargetPointOccludedError(second_visibility)

                primary_error = None
                down_result = None
                up_result = None
                with _click_release_scope(self, button) as release:
                    try:
                        input_attempted = True
                        down_result = self.mouse_down(button)
                        if effective_hold_ms > 0:
                            time.sleep(effective_hold_ms / 1000.0)
                    except BaseException as error:
                        primary_error = error
                        raise
                    finally:
                        release["releasing"] = True
                        try:
                            up_result = self.mouse_up(button)
                        except Exception as release_error:
                            if primary_error is None:
                                raise RuntimeError("Mouse button release failed; input outcome unknown") from release_error
                            primary_error.add_note("Mouse button release also failed; input outcome unknown")
                            primary_error.mouse_release_error = str(release_error)
                completed_clicks += 1
                click_events.append({
                    "index": index + 1,
                    "down": down_result,
                    "up": up_result,
                    "hold_ms": effective_hold_ms,
                    "gap_before_ms": inter_click_gap_ms if index else 0,
                })
        except BaseException as error:
            sequence = {
                "requested_click_count": click_count,
                "completed_clicks": completed_clicks,
                "input_attempted": input_attempted,
                "button": button,
            }
            # 保留原始异常类型；标准异常支持属性时附加部分输入诊断。
            try:
                error.click_sequence = sequence
                if completed_clicks:
                    error.completed_click_count = completed_clicks
                    error.add_note(f"Partial click sequence: {completed_clicks}/{click_count} click(s) dispatched")
            except Exception:
                pass
            raise

        cursor_after = win32api.GetCursorPos()  # type: ignore[union-attr]
        foreground_after = int(win32gui.GetForegroundWindow())  # type: ignore[union-attr]

        # 记录实际下发间隔；请求的 sleep 不包含身份读取和调度开销。
        dispatch_interval_ms = None
        if len(click_events) == 2:
            stamps = [event["down"].get("dispatched_monotonic_ns") for event in click_events]
            if all(type(stamp) is int for stamp in stamps):
                dispatch_interval_ms = (stamps[1] - stamps[0]) / 1_000_000

        result = {
            "clicked": True,
            "input_backend": "SendInput",
            "window_point": {"x": point["window_x"], "y": point["window_y"]},
            "screen_point": {"x": point["screen_x"], "y": point["screen_y"]},
            "window_handle": int(bound.handle),
            "window_title": bound.title,
            "button": button,
            "click_count": click_count,
            "foreground_before": foreground_before,
            "foreground_after": foreground_after,
            "set_foreground_ok": set_foreground_ok,
            "cursor_before": {"x": int(cursor_before[0]), "y": int(cursor_before[1])},
            "cursor_after": {"x": int(cursor_after[0]), "y": int(cursor_after[1])},
            "move_before_click": move_before_click,
            "settle_ms": int(settle_ms),
            "hold_ms": effective_hold_ms,
            "requested_hold_ms": int(hold_ms),
            "double_click_time_ms": double_click_time_ms,
            "double_click_gap_ms": inter_click_gap_ms,
            "double_click_dispatch_interval_ms": dispatch_interval_ms,
            "double_click_within_system_interval": (
                dispatch_interval_ms < double_click_time_ms if dispatch_interval_ms is not None else None),
            "move": move_result,
            "point_visibility": point_visibility,
            "click_events": click_events,
            # Existing callers consume these fields for a single click.
            "down": click_events[0]["down"],
            "up": click_events[0]["up"],
        }
        logger.info("Click result: {}", result)
        return result

    def activate_taskbar_item(self, *, guard: Any) -> dict[str, Any]:
        """点击已严格固定的系统任务栏按钮，不改变普通窗口前台规则。"""

        from app.agent.taskbar_activation_guard import TaskbarActivationGuard

        self._ensure_windows_input()
        if type(guard) is not TaskbarActivationGuard:
            raise ValueError("guard must be a TaskbarActivationGuard")
        expectation = guard.expectation
        guard.validate_command(
            window_handle=expectation.taskbar_handle,
            click_point=expectation.window_point,
        )
        guard.verify_current()
        cursor_before = tuple(win32api.GetCursorPos())  # type: ignore[union-attr]
        self._send_move(*expectation.screen_point)
        if TASKBAR_ACTIVATION_SETTLE_SECONDS > 0:
            time.sleep(TASKBAR_ACTIVATION_SETTLE_SECONDS)
        guard.verify_current()
        if tuple(win32api.GetCursorPos()) != expectation.screen_point:  # type: ignore[union-attr]
            raise RuntimeError("Taskbar activation cursor changed before mouse down")

        primary_error = None
        try:
            down_result = self.mouse_down("left")
        except BaseException as error:
            primary_error = error
            raise
        finally:
            try:
                up_result = self.mouse_up("left")
            except Exception as release_error:
                if primary_error is None:
                    raise RuntimeError(
                        "Mouse button release failed; taskbar activation outcome unknown"
                    ) from release_error
                primary_error.add_note(
                    "Mouse button release also failed; taskbar activation outcome unknown"
                )
                primary_error.mouse_release_error = str(release_error)

        deadline = time.monotonic() + TASKBAR_ACTIVATION_VERIFY_TIMEOUT_SECONDS
        verification_attempts = 0
        activation_verified = False
        while True:
            verification_attempts += 1
            if guard.verify_destination() is True:
                activation_verified = True
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(TASKBAR_ACTIVATION_VERIFY_INTERVAL_SECONDS, remaining))

        cursor_after = tuple(win32api.GetCursorPos())  # type: ignore[union-attr]
        return {
            "clicked": True,
            "activation_verified": activation_verified,
            "input_backend": "SendInput",
            "button": "left",
            "taskbar_handle": expectation.taskbar_handle,
            "destination_handle": expectation.destination_handle,
            "window_point": {
                "x": expectation.window_point[0], "y": expectation.window_point[1]
            },
            "screen_point": {
                "x": expectation.screen_point[0], "y": expectation.screen_point[1]
            },
            "capture_id": expectation.capture_id,
            "candidate_id": expectation.candidate_id,
            "source_sha256": expectation.source_sha256,
            "cursor_before": {"x": cursor_before[0], "y": cursor_before[1]},
            "cursor_after": {"x": cursor_after[0], "y": cursor_after[1]},
            "verification_attempts": verification_attempts,
            "down": down_result,
            "up": up_result,
        }

    def type_text(
        self,
        text: str,
        *,
        x: int | None = None,
        y: int | None = None,
        click_before_typing: bool = False,
        clear_existing: bool = False,
        submit: bool = False,
        restore_clipboard: bool = True,
        field_guard: Any | None = None,
    ) -> dict[str, Any]:
        """先保存剪贴板，再校验当前输入目标并单次粘贴；异常出口也恢复。"""
        self._ensure_windows_input()
        bound = self._require_bound_window()
        snapshot = self._text_target_snapshot(bound)
        click_result = None
        from app.core.local_keyboard_target import claim_keyboard_target
        keyboard_target = claim_keyboard_target("type_text", {"text": text, "x": x, "y": y,
            "click_before_typing": click_before_typing, "clear_existing": clear_existing, "submit": submit})
        if keyboard_target is not None and field_guard is not None:
            raise ValueError("internal keyboard scope cannot replace a reviewed text guard")
        if click_before_typing and (type(x) is not int or type(y) is not int):
            raise ValueError("integer x and y are required when click_before_typing=true")
        if field_guard is not None:
            from app.agent.text_input_guard import TextInputGuard

            if type(field_guard) is not TextInputGuard:
                raise ValueError("field_guard must be a TextInputGuard")
            if type(x) is not int or type(y) is not int:
                raise ValueError("integer x and y are required when field_guard is present")
            field_guard.validate_command(
                text=text,
                clear_existing=clear_existing,
                window_handle=int(bound.handle),
                click_point=(x, y),
            )
        with self._clipboard_text_transaction(text, restore=restore_clipboard) as clipboard:
            if self._text_target_snapshot(self._require_bound_window()) != snapshot:
                raise RuntimeError("Text target window changed before focus/click")
            if click_before_typing:
                click_result = self.click_point(x, y, move_before_click=True, settle_ms=100, hold_ms=50)
            elif keyboard_target is None:
                self._focus_window(bound.handle)
            if keyboard_target is None:
                self._verify_text_target(snapshot, x=x, y=y)
            if field_guard is not None:
                self._verify_text_region(bound, field_guard)
            clipboard.verify_current_text()
            if field_guard is not None:
                field_guard.verify_before_selection()
            if clear_existing:
                if keyboard_target is not None:
                    self._verify_text_target(snapshot, x=x, y=y, keyboard_target=keyboard_target)
                self._press_chord([VK_CONTROL, VK_A])
                time.sleep(0.03)
            # 选择文字与粘贴之间窗口或剪贴板都可能变化，不能复用前一次检查。
            if keyboard_target is None:
                self._verify_text_target(snapshot, x=x, y=y)
            if field_guard is not None:
                self._verify_text_region(bound, field_guard)
            verify_attempts = clipboard.verify_current_text()
            if field_guard is not None:
                field_guard.verify_before_paste()
            if keyboard_target is not None:
                self._verify_text_target(snapshot, x=x, y=y, keyboard_target=keyboard_target)
            self._press_chord([VK_CONTROL, VK_V])
            time.sleep(CLIPBOARD_PASTE_SETTLE_SECONDS)
            if submit:
                time.sleep(0.03)
                self._verify_text_target(snapshot, x=x, y=y)
                if field_guard is not None:
                    self._verify_text_region(bound, field_guard)
                self._press_key(VK_RETURN)

        return {
            "typed": True,
            "input_backend": "SendInput+clipboard",
            "window_handle": int(bound.handle),
            "window_title": bound.title,
            "text_length": len(text),
            "click_before_typing": bool(click_before_typing),
            "click_result": click_result,
            "clear_existing": bool(clear_existing),
            "submit": bool(submit),
            "restore_clipboard": bool(restore_clipboard),
            "clipboard_restore_status": clipboard.status,
            "clipboard_bitmap_preservation": getattr(clipboard, "bitmap_preservation", None),
            "clipboard_verified_before_paste": True,
            "clipboard_verify_attempts": verify_attempts,
            "clipboard_paste_settle_ms": int(CLIPBOARD_PASTE_SETTLE_SECONDS * 1000),
        }

    def press_key(self, key: str, *, x: int, y: int) -> dict[str, Any]:
        """向当前焦点派发编辑键；不点击坐标、不重填、不改变窗口焦点。"""
        if not isinstance(key, str) or key not in EDITING_KEY_CHORDS:
            raise ValueError(f"Unsupported editing key; supported keys: {', '.join(EDITING_KEY_CHORDS)}")
        if type(x) is not int or type(y) is not int:
            raise ValueError("press_key requires an observed window point")
        self._ensure_windows_input()
        bound = self._require_bound_window()
        from app.core.local_keyboard_target import claim_keyboard_target
        keyboard_target = claim_keyboard_target("press_key", {"key": key, "x": x, "y": y})
        self._verify_text_target(self._text_target_snapshot(bound), x=x, y=y, keyboard_target=keyboard_target)
        self._press_chord(list(EDITING_KEY_CHORDS[key]))
        return {"pressed": True, "key": key, "window_handle": bound.handle,
            "input_backend": "SendInput", "text_retyped": False}

    @staticmethod
    def _verify_text_region(bound, field_guard) -> None:
        evidence = window_manager.validate_bound_region_visibility(
            bound=bound, bbox=field_guard.expectation.before.identity.control_bbox)
        if evidence.get("allowed") is not True:
            raise TargetPointOccludedError(evidence)

    def _clipboard_text_transaction(self, text: str, *, restore: bool) -> Any:
        from app.core.clipboard_transaction import ClipboardTextTransaction

        return ClipboardTextTransaction(text, restore=restore)

    @staticmethod
    def _text_target_snapshot(bound: Any) -> tuple[Any, ...]:
        return (int(bound.handle), getattr(bound, "process_id", None),
                bound.rect.left, bound.rect.top, bound.rect.right, bound.rect.bottom)

    def _verify_text_target(self, snapshot: tuple[Any, ...], *, x: int | None, y: int | None,
                            keyboard_target=None) -> None:
        current = self._require_bound_window()
        if self._text_target_snapshot(current) != snapshot:
            raise RuntimeError("Text target window changed before keyboard dispatch")
        foreground = int(win32gui.GetForegroundWindow())
        if foreground != snapshot[0]:
            raise KeyboardForegroundMismatchError(snapshot[0], foreground)
        if keyboard_target is not None:
            from app.core.local_keyboard_target import LocalKeyboardTarget
            if type(keyboard_target) is not LocalKeyboardTarget:
                raise ValueError("invalid internal keyboard field target")
            keyboard_target.verify(window_manager)
            # COM 复读可能耗时；真正按键前仍重新确认窗口与前台。
            if self._text_target_snapshot(self._require_bound_window()) != snapshot:
                raise RuntimeError("Text target window changed before keyboard dispatch")
            foreground = int(win32gui.GetForegroundWindow())
            if foreground != snapshot[0]:
                raise KeyboardForegroundMismatchError(snapshot[0], foreground)
            return
        if x is not None and y is not None:
            evidence = window_manager.validate_bound_point_visibility(bound=current, x=x, y=y)
            if evidence.get("allowed") is not True:
                raise TargetPointOccludedError(evidence)

    def paste_image(
        self,
        image_path: str,
        *,
        focus_bound_window: bool = True,
        restore_clipboard_text: bool = False,
        settle_ms: int | None = None,
    ) -> dict[str, Any]:
        """Paste an image file into the current focused target using CF_DIB + Ctrl+V."""
        self._ensure_windows_input()
        bound = None
        if focus_bound_window:
            bound = self._require_bound_window()
            self._focus_window(bound.handle)

        image_file = Path(image_path)
        clipboard_before = self._get_clipboard_text() if restore_clipboard_text else None
        dib_bytes = self._image_path_to_cf_dib(image_file)
        self._set_clipboard_image_dib(dib_bytes)
        self._press_chord([VK_CONTROL, VK_V])
        paste_settle = CLIPBOARD_PASTE_SETTLE_SECONDS if settle_ms is None else max(0, int(settle_ms)) / 1000.0
        time.sleep(paste_settle)
        if restore_clipboard_text:
            self._set_clipboard_text(clipboard_before or "")

        return {
            "pasted": True,
            "input_backend": "SendInput+clipboard_image",
            "image_path": str(image_file),
            "image_bytes": int(image_file.stat().st_size),
            "dib_bytes": len(dib_bytes),
            "focus_bound_window": bool(focus_bound_window),
            "window_handle": int(bound.handle) if bound is not None else None,
            "window_title": bound.title if bound is not None else None,
            "restore_clipboard_text": bool(restore_clipboard_text),
            "clipboard_format": "CF_DIB",
            "clipboard_paste_settle_ms": int(paste_settle * 1000),
        }

    def scroll_window(
        self,
        *,
        direction: str = "down",
        wheel_clicks: int = 4,
        x: int | None = None,
        y: int | None = None,
        settle_ms: int = 100,
    ) -> dict[str, Any]:
        """Scroll the bound window with a real mouse wheel event."""
        self._ensure_windows_input()
        if type(wheel_clicks) is not int or not 1 <= wheel_clicks <= 20:
            raise ValueError("wheel_clicks must be an integer from 1 through 20")
        bound = self._require_bound_window()
        bound_handle = int(bound.handle)
        bound_process_id = getattr(bound, "process_id", None)
        bound_geometry = (bound.rect.left, bound.rect.top, bound.rect.right, bound.rect.bottom)
        rect_width = max(1, int(bound.rect.right) - int(bound.rect.left))
        rect_height = max(1, int(bound.rect.bottom) - int(bound.rect.top))
        window_x = int(x) if x is not None else rect_width // 2
        window_y = int(y) if y is not None else rect_height // 2
        point = self._resolve_window_and_screen_point(bound=bound, x=window_x, y=window_y)
        normalized_direction = str(direction or "down").strip().lower()
        if normalized_direction not in {"down", "up"}:
            raise ValueError(f"Unsupported scroll direction: {direction}")
        click_count = wheel_clicks
        wheel_delta = (120 * click_count) if normalized_direction == "up" else (-120 * click_count)

        foreground_before = int(win32gui.GetForegroundWindow())  # type: ignore[union-attr]
        set_foreground_ok = self._focus_window(bound.handle)
        cursor_before = win32api.GetCursorPos()  # type: ignore[union-attr]
        self._send_move(point["screen_x"], point["screen_y"])
        if settle_ms > 0:
            time.sleep(settle_ms / 1000.0)
        current = self._require_bound_window()
        current_geometry = (current.rect.left, current.rect.top, current.rect.right, current.rect.bottom)
        if int(current.handle) != bound_handle or getattr(current, "process_id", None) != bound_process_id or current_geometry != bound_geometry:
            raise RuntimeError("Scroll target window changed before wheel dispatch")
        if int(win32gui.GetForegroundWindow()) != bound_handle:  # type: ignore[union-attr]
            raise RuntimeError("Scroll target is not the foreground window before wheel dispatch")
        if tuple(win32api.GetCursorPos()) != (point["screen_x"], point["screen_y"]):  # type: ignore[union-attr]
            raise RuntimeError("Scroll pointer changed before wheel dispatch")
        point_visibility = window_manager.validate_bound_point_visibility(bound=current, x=window_x, y=window_y)
        if point_visibility.get("allowed") is not True:
            raise TargetPointOccludedError(point_visibility)
        self._send_mouse_input(dx=0, dy=0, flags=MOUSEEVENTF_WHEEL, mouse_data=wheel_delta)
        cursor_after = win32api.GetCursorPos()  # type: ignore[union-attr]
        foreground_after = int(win32gui.GetForegroundWindow())  # type: ignore[union-attr]
        return {
            "scrolled": True,
            "input_backend": "SendInput",
            "window_handle": int(bound.handle),
            "window_title": bound.title,
            "direction": normalized_direction,
            "wheel_clicks": click_count,
            "wheel_delta": wheel_delta,
            "point_visibility": point_visibility,
            "window_point": {"x": point["window_x"], "y": point["window_y"]},
            "screen_point": {"x": point["screen_x"], "y": point["screen_y"]},
            "foreground_before": foreground_before,
            "foreground_after": foreground_after,
            "set_foreground_ok": set_foreground_ok,
            "cursor_before": {"x": int(cursor_before[0]), "y": int(cursor_before[1])},
            "cursor_after": {"x": int(cursor_after[0]), "y": int(cursor_after[1])},
            "settle_ms": int(settle_ms),
        }

    def _require_bound_window(self) -> Any:
        bound = window_manager.get_bound_window()
        if bound is None:
            raise ValueError("No bound window available for click")
        return bound

    def _resolve_window_and_screen_point(self, *, bound: Any, x: int, y: int) -> dict[str, int]:
        return resolve_window_and_screen_point(bound=bound, x=x, y=y)

    def _focus_window(self, handle: int) -> bool:
        self._ensure_windows_input()
        set_foreground_ok = False
        try:
            win32gui.SetForegroundWindow(handle)  # type: ignore[union-attr]
            set_foreground_ok = True
        except Exception as exc:
            logger.warning("SetForegroundWindow failed for handle {}: {}", handle, exc)
        return set_foreground_ok

    @staticmethod
    def _double_click_time_ms() -> int:
        """Read Windows' current double-click interval without changing system settings."""
        value = int(ctypes.windll.user32.GetDoubleClickTime())
        return max(1, value)

    def _button_down_flag(self, button: str) -> int:
        if button == "left":
            return MOUSEEVENTF_LEFTDOWN
        if button == "middle":
            return MOUSEEVENTF_MIDDLEDOWN
        if button == "right":
            return MOUSEEVENTF_RIGHTDOWN
        raise ValueError(f"Unsupported mouse button: {button}")

    def _button_up_flag(self, button: str) -> int:
        if button == "left":
            return MOUSEEVENTF_LEFTUP
        if button == "middle":
            return MOUSEEVENTF_MIDDLEUP
        if button == "right":
            return MOUSEEVENTF_RIGHTUP
        raise ValueError(f"Unsupported mouse button: {button}")

    def _send_move(self, screen_x: int, screen_y: int) -> None:
        screen_width = ctypes.windll.user32.GetSystemMetrics(SM_CXSCREEN)
        screen_height = ctypes.windll.user32.GetSystemMetrics(SM_CYSCREEN)
        # 发送像素区间中心；旧公式向下取整会把靠左/上目标送到相邻像素。
        absolute_x = ((2 * screen_x + 1) * 32768) // max(1, screen_width)
        absolute_y = ((2 * screen_y + 1) * 32768) // max(1, screen_height)
        self._send_mouse_input(dx=absolute_x, dy=absolute_y, flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)

    def _send_mouse_flags(self, flags: int) -> int:
        return self._send_mouse_input(dx=0, dy=0, flags=flags)

    def _send_mouse_input(self, *, dx: int, dy: int, flags: int, mouse_data: int = 0) -> int:
        release = _pending_click_release(self, flags) if dx == 0 and dy == 0 and mouse_data == 0 else None
        if release is None:
            self._ensure_windows_input()
        else:
            release["used"] = True
        input_struct = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(
                mi=MOUSEINPUT(
                    dx=dx,
                    dy=dy,
                    mouseData=mouse_data & 0xFFFFFFFF,
                    dwFlags=flags,
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        )
        state = _CLICK_RELEASE.get()
        if (state is not None and state["active"] and state["controller"] is self
                and state["thread"] == get_ident() and flags == state["down"] and not state["releasing"]):
            # 系统可能派发后才报错，因此以尝试 SendInput 为清理边界。
            state["attempted"] = True
        dispatched = time.perf_counter_ns()
        sent = ctypes.windll.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))
        if sent != 1:
            raise RuntimeError(f"SendInput failed, sent={sent}, flags={flags}")
        return dispatched

    def _press_chord(self, keys: list[int]) -> None:
        # 释放本次已尝试按下的键属于收尾；目标关闭不应把键留在按下状态。
        state = {"controller": self, "thread": get_ident(), "pending": set(),
                 "active": True, "releasing": False}
        token = _KEY_RELEASE.set(state)
        try:
            self._press_chord_in_scope(keys, state)
        finally:
            state["active"] = False
            _KEY_RELEASE.reset(token)

    def _press_chord_in_scope(self, keys: list[int], state: dict) -> None:
        attempted: list[int] = []
        primary: BaseException | None = None
        try:
            for key in keys:
                attempted.append(key)
                self._send_key(key, key_up=False)
        except BaseException as error:
            primary = error
        release_error: BaseException | None = None
        state["releasing"] = True
        for key in reversed(attempted):
            try:
                self._send_key(key, key_up=True)
            except BaseException as error:
                if release_error is None:
                    release_error = error
        if primary is not None:
            if release_error is not None:
                primary.add_note("Keyboard release also failed; key state is unknown")
            raise primary
        if release_error is not None:
            raise release_error

    def _press_key(self, key: int) -> None:
        self._press_chord([key])

    def _send_key(self, key: int, *, key_up: bool) -> None:
        state = _KEY_RELEASE.get()
        own_scope = (state is not None and state["active"] and state["controller"] is self
                     and state["thread"] == get_ident())
        cleanup = own_scope and state["releasing"] and key_up and key in state["pending"]
        if cleanup:
            # 单次消费，不能释放其他键、跨线程复用或授权下一次按下。
            state["pending"].remove(key)
        else:
            self._ensure_windows_input()
        input_struct = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(
                ki=KEYBDINPUT(
                    wVk=int(key),
                    wScan=0,
                    dwFlags=(KEYEVENTF_KEYUP if key_up else 0) | (0x0001 if key in EXTENDED_EDITING_KEYS else 0),
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        )
        if own_scope and not key_up:
            state["pending"].add(key)
        sent = ctypes.windll.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))
        if sent != 1:
            raise RuntimeError(f"SendInput keyboard failed, sent={sent}, key={key}, key_up={key_up}")

    def _get_clipboard_text(self) -> str | None:
        if win32clipboard is None:
            return None
        opened = False
        try:
            self._open_clipboard()
            opened = True
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):  # type: ignore[union-attr]
                    return str(win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT))  # type: ignore[union-attr]
                return None
            finally:
                if opened:
                    win32clipboard.CloseClipboard()  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Reading clipboard text failed: {}", exc)
            return None

    def _set_clipboard_text(self, text: str) -> None:
        self._ensure_windows_input()
        if win32clipboard is None:
            raise RuntimeError("win32clipboard is unavailable; cannot paste text")
        opened = False
        self._open_clipboard()
        opened = True
        try:
            win32clipboard.EmptyClipboard()  # type: ignore[union-attr]
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)  # type: ignore[union-attr]
        finally:
            if opened:
                win32clipboard.CloseClipboard()  # type: ignore[union-attr]

    def _set_clipboard_image_dib(self, dib_bytes: bytes) -> None:
        self._ensure_windows_input()
        if win32clipboard is None:
            raise RuntimeError("win32clipboard is unavailable; cannot paste image")
        opened = False
        self._open_clipboard()
        opened = True
        try:
            win32clipboard.EmptyClipboard()  # type: ignore[union-attr]
            win32clipboard.SetClipboardData(CF_DIB, dib_bytes)  # type: ignore[union-attr]
        finally:
            if opened:
                win32clipboard.CloseClipboard()  # type: ignore[union-attr]

    def _image_path_to_cf_dib(self, image_path: Path) -> bytes:
        if not image_path.exists():
            raise FileNotFoundError(f"Image path does not exist: {image_path}")
        try:
            from PIL import Image
        except Exception as exc:  # pragma: no cover - depends on optional runtime imaging support
            raise RuntimeError("Pillow is required to paste image clipboard data") from exc

        with Image.open(image_path) as image:
            output = BytesIO()
            image.convert("RGB").save(output, "BMP")
        bmp_bytes = output.getvalue()
        # CF_DIB expects the BMP payload without the 14-byte BITMAPFILEHEADER.
        if len(bmp_bytes) <= 14:
            raise RuntimeError(f"Invalid BMP conversion for image: {image_path}")
        return bmp_bytes[14:]

    def _open_clipboard(self) -> None:
        if win32clipboard is None:
            raise RuntimeError("win32clipboard is unavailable; cannot open clipboard")
        last_exc: Exception | None = None
        for attempt in range(CLIPBOARD_OPEN_ATTEMPTS):
            try:
                win32clipboard.OpenClipboard(None)  # type: ignore[union-attr]
                return
            except Exception as exc:
                last_exc = exc
                if attempt < CLIPBOARD_OPEN_ATTEMPTS - 1:
                    time.sleep(CLIPBOARD_OPEN_RETRY_SECONDS)
        raise RuntimeError(
            f"Opening clipboard failed after {CLIPBOARD_OPEN_ATTEMPTS} attempt(s)"
        ) from last_exc

    def _ensure_windows_input(self) -> None:
        from app.core.local_input_policy import require_local_operator_input
        if not runtime_backend_input_is_active() and not require_local_operator_input(window_manager):
            raise PermissionError(
                "Windows input requires one-time LiveController authority via DesktopBackend"
            )
        if not WINDOWS_INPUT_AVAILABLE:
            raise RuntimeError(
                "Windows input backend is unavailable. "
                f"Import error: {WINDOWS_INPUT_IMPORT_ERROR}"
            )


input_controller = InputController()
