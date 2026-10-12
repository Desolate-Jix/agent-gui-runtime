"""键盘派发的同步只读事实；不读文字，不授予输入或焦点权限。"""
import ctypes
from ctypes import wintypes
from functools import lru_cache
import json
from time import perf_counter_ns

from loguru import logger


class _GUIThreadInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT)]


@lru_cache(maxsize=1)
def _user32():
    # 延迟初始化并声明句柄宽度；导入模块本身不访问桌面。
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.GetForegroundWindow.argtypes, api.GetForegroundWindow.restype = [], wintypes.HWND
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    api.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUIThreadInfo)]
    api.GetGUIThreadInfo.restype = wintypes.BOOL
    api.GetAsyncKeyState.argtypes, api.GetAsyncKeyState.restype = [ctypes.c_int], wintypes.SHORT
    return api


def capture_keyboard_dispatch_state():
    """各项独立读取；失败只留下 unavailable，不影响原输入。"""
    started = perf_counter_ns()
    result = {"status": "unavailable", "foreground_hwnd": None,
        "gui_thread": {"active_hwnd": None, "focus_hwnd": None, "caret_hwnd": None, "flags": None},
        "modifiers": {"ctrl": None, "alt": None, "shift": None, "win": None}, "unavailable": []}
    try:
        api = _user32()
    except Exception:
        result["unavailable"].append("user32")
    else:
        def read(label, operation):
            try:
                return operation()
            except Exception:
                # 不记录异常正文，避免原生接口或日志实现夹带无关资料。
                result["unavailable"].append(label)
                return None

        result["foreground_hwnd"] = read("foreground_hwnd", lambda: int(api.GetForegroundWindow() or 0))

        def gui_thread():
            handle = result["foreground_hwnd"]
            thread = api.GetWindowThreadProcessId(handle, None) if handle else 0
            info = _GUIThreadInfo()
            info.cbSize = ctypes.sizeof(info)
            if not thread or not api.GetGUIThreadInfo(thread, ctypes.byref(info)):
                raise OSError("GUI thread unavailable")
            return {"active_hwnd": int(info.hwndActive or 0), "focus_hwnd": int(info.hwndFocus or 0),
                "caret_hwnd": int(info.hwndCaret or 0), "flags": int(info.flags)}

        gui = read("gui_thread", gui_thread)
        if gui is not None:
            result["gui_thread"] = gui
        for name, keys in (("ctrl", (0x11,)), ("alt", (0x12,)), ("shift", (0x10,)), ("win", (0x5B, 0x5C))):
            result["modifiers"][name] = read("modifiers." + name,
                lambda keys=keys: bool(sum(int(api.GetAsyncKeyState(key)) & 0x8000 for key in keys)))
        result["status"] = ("observed" if not result["unavailable"] else
            "unavailable" if len(result["unavailable"]) == 6 else "partial")
    result["elapsed_ms"] = round((perf_counter_ns() - started) / 1_000_000, 6)
    return result


def emit_keyboard_dispatch_event(event):
    """成功或失败的原 SendInput 都留日志；日志故障不能改变原异常。"""
    try:
        logger.bind(keyboard_dispatch_diagnostics=event).info("keyboard_dispatch_diagnostics {}",
            json.dumps(event, ensure_ascii=False, separators=(",", ":")))
    except Exception:
        # 原生派发与释放的成败仍完全由原调用决定。
        return


def keyboard_dispatch_reference(events):
    return {"schema": "keyboard_dispatch_diagnostics.v1", "events": events or [],
        "status": "recorded" if events else "unavailable",
        "diagnostic_elapsed_ms": round(sum(event["diagnostic_elapsed_ms"] for event in events or []), 6),
        "timing_scope": "readonly_state_sampling", "artifact_is_authorization": False}
