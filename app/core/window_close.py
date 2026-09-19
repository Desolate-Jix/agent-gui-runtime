"""受身份核验约束的原生窗口关闭请求。"""

from __future__ import annotations

import ctypes
import os


WM_CLOSE = 0x0010


def window_handle_exists(handle: int) -> bool:
    """检查 HWND 是否仍存在；可见性或最小化状态不影响结果。"""
    if os.name != "nt":
        raise OSError("window existence requires Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    is_window = user32.IsWindow
    is_window.argtypes = [ctypes.c_void_p]
    is_window.restype = ctypes.c_bool
    return bool(is_window(ctypes.c_void_p(handle)))


def post_window_close(handle: int) -> None:
    """向已核验的窗口发送正常 WM_CLOSE，不终止所属进程。"""
    if os.name != "nt":
        raise OSError("window close requires Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    post = user32.PostMessageW
    post.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    post.restype = ctypes.c_bool
    if not post(ctypes.c_void_p(handle), WM_CLOSE, 0, 0):
        error = ctypes.get_last_error()
        raise OSError(error or "PostMessageW(WM_CLOSE) failed")
