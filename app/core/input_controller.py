from __future__ import annotations

import ctypes
import time
from typing import Any, Optional

from loguru import logger

from app.core.window_manager import window_manager
from modules.click.geometry import resolve_window_and_screen_point

WINDOWS_INPUT_AVAILABLE = False
WINDOWS_INPUT_IMPORT_ERROR: Optional[str] = None

try:
    import win32api
    import win32con
    import win32gui

    WINDOWS_INPUT_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on runtime platform/environment
    win32api = None  # type: ignore[assignment]
    win32con = None  # type: ignore[assignment]
    win32gui = None  # type: ignore[assignment]
    WINDOWS_INPUT_IMPORT_ERROR = str(exc)


INPUT_MOUSE = 0
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
SM_CXSCREEN = 0
SM_CYSCREEN = 1


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


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
        self._send_mouse_flags(self._button_down_flag(button))
        pos = win32api.GetCursorPos()  # type: ignore[union-attr]
        return {"button": button, "state": "down", "cursor": {"x": int(pos[0]), "y": int(pos[1])}}

    def mouse_up(self, button: str = "left") -> dict[str, Any]:
        self._ensure_windows_input()
        self._send_mouse_flags(self._button_up_flag(button))
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
    ) -> dict[str, Any]:
        """Click a point relative to the bound window using a realistic pointer sequence."""
        self._ensure_windows_input()
        bound = self._require_bound_window()
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

        down_result = self.mouse_down(button)
        if hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
        up_result = self.mouse_up(button)

        cursor_after = win32api.GetCursorPos()  # type: ignore[union-attr]
        foreground_after = int(win32gui.GetForegroundWindow())  # type: ignore[union-attr]

        result = {
            "clicked": True,
            "input_backend": "SendInput",
            "window_point": {"x": point["window_x"], "y": point["window_y"]},
            "screen_point": {"x": point["screen_x"], "y": point["screen_y"]},
            "window_handle": int(bound.handle),
            "window_title": bound.title,
            "button": button,
            "foreground_before": foreground_before,
            "foreground_after": foreground_after,
            "set_foreground_ok": set_foreground_ok,
            "cursor_before": {"x": int(cursor_before[0]), "y": int(cursor_before[1])},
            "cursor_after": {"x": int(cursor_after[0]), "y": int(cursor_after[1])},
            "move_before_click": move_before_click,
            "settle_ms": int(settle_ms),
            "hold_ms": int(hold_ms),
            "move": move_result,
            "down": down_result,
            "up": up_result,
        }
        logger.info("Click result: {}", result)
        return result

    def _require_bound_window(self) -> Any:
        bound = window_manager.get_bound_window()
        if bound is None:
            raise ValueError("No bound window available for click")
        return bound

    def _resolve_window_and_screen_point(self, *, bound: Any, x: int, y: int) -> dict[str, int]:
        return resolve_window_and_screen_point(bound=bound, x=x, y=y)

    def _focus_window(self, handle: int) -> bool:
        set_foreground_ok = False
        try:
            win32gui.SetForegroundWindow(handle)  # type: ignore[union-attr]
            set_foreground_ok = True
        except Exception as exc:
            logger.warning("SetForegroundWindow failed for handle {}: {}", handle, exc)
        return set_foreground_ok

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
        absolute_x = int(screen_x * 65535 / max(1, screen_width - 1))
        absolute_y = int(screen_y * 65535 / max(1, screen_height - 1))
        self._send_mouse_input(dx=absolute_x, dy=absolute_y, flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)

    def _send_mouse_flags(self, flags: int) -> None:
        self._send_mouse_input(dx=0, dy=0, flags=flags)

    def _send_mouse_input(self, *, dx: int, dy: int, flags: int) -> None:
        input_struct = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(
                mi=MOUSEINPUT(
                    dx=dx,
                    dy=dy,
                    mouseData=0,
                    dwFlags=flags,
                    time=0,
                    dwExtraInfo=None,
                )
            ),
        )
        sent = ctypes.windll.user32.SendInput(1, ctypes.byref(input_struct), ctypes.sizeof(INPUT))
        if sent != 1:
            raise RuntimeError(f"SendInput failed, sent={sent}, flags={flags}")

    def _ensure_windows_input(self) -> None:
        if not WINDOWS_INPUT_AVAILABLE:
            raise RuntimeError(
                "Windows input backend is unavailable. "
                f"Import error: {WINDOWS_INPUT_IMPORT_ERROR}"
            )


input_controller = InputController()
