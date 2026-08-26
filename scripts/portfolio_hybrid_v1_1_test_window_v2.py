"""Benchmark-v2 专用、无交互的 bitmap HWND helper。"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import site
import struct
import sys
import time


_ROOT = Path(__file__).resolve().parents[1]
site.addsitedir(str(_ROOT / ".venv" / "Lib" / "site-packages"))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _content_sha256(value: dict[str, object]) -> str:
    return hashlib.sha256(
        _canonical_bytes({key: item for key, item in value.items() if key != "content_sha256"})
    ).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    raw = _canonical_bytes(value)
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _rect(user32: object, hwnd: int) -> tuple[dict[str, int], dict[str, int], int]:
    user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    user32.ClientToScreen.restype = wintypes.BOOL
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
        raise ValueError("test-owned window DPI is unavailable")
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


def _parse_bmp(raw: bytes) -> dict[str, int | str]:
    if len(raw) < 54 or raw[:2] != b"BM":
        raise ValueError("screenshot is not a sealed BMP")
    file_size = struct.unpack_from("<I", raw, 2)[0]
    pixel_offset = struct.unpack_from("<I", raw, 10)[0]
    header_size, width, signed_height, planes, bit_count, compression, size_image = (
        struct.unpack_from("<IiiHHII", raw, 14)
    )
    height = abs(signed_height)
    stride = ((width * bit_count + 31) // 32) * 4 if width > 0 else 0
    pixel_bytes = stride * height
    if (
        file_size != len(raw)
        or header_size != 40
        or width <= 0
        or signed_height == 0
        or planes != 1
        or bit_count not in {24, 32}
        or compression != 0
        or pixel_offset < 54
        or size_image not in {0, pixel_bytes}
        or pixel_offset + pixel_bytes != len(raw)
    ):
        raise ValueError("screenshot BMP layout is invalid")
    return {
        "width": width,
        "height": height,
        "signed_height": signed_height,
        "bit_count": bit_count,
        "pixel_offset": pixel_offset,
        "pixel_bytes": pixel_bytes,
        "bitmap_pixel_sha256": hashlib.sha256(
            raw[pixel_offset : pixel_offset + pixel_bytes]
        ).hexdigest(),
    }


def _read_sealed_bmp(kernel32: object, path: Path) -> tuple[int, bytes]:
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileSizeEx.argtypes = (wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong))
    kernel32.GetFileSizeEx.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = (
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateFileW(str(path), 0x80000000, 0x00000001, None, 3, 0x80, None)
    if not handle or int(handle) == int(ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = ctypes.c_longlong()
        if not kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        if size.value < 54 or size.value > 64 * 1024 * 1024:
            raise ValueError("sealed BMP file length is invalid")
        buffer = ctypes.create_string_buffer(size.value)
        offset = 0
        while offset < size.value:
            count = wintypes.DWORD()
            remaining = size.value - offset
            if not kernel32.ReadFile(
                handle,
                ctypes.byref(buffer, offset),
                remaining,
                ctypes.byref(count),
                None,
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if count.value == 0:
                raise ValueError("sealed BMP read ended early")
            offset += int(count.value)
        return int(handle), bytes(buffer.raw[: size.value])
    except BaseException:
        kernel32.CloseHandle(handle)
        raise


def _serve_bitmap(args: argparse.Namespace) -> int:
    image = Path(args.image).resolve()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    if not user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
        raise ctypes.WinError(ctypes.get_last_error())

    file_handle, raw = _read_sealed_bmp(kernel32, image)
    if hashlib.sha256(raw).hexdigest() != args.sha256:
        kernel32.CloseHandle(file_handle)
        raise ValueError("screenshot SHA-256 mismatch")
    bmp = _parse_bmp(raw)
    if bmp["bitmap_pixel_sha256"] != args.pixel_sha256:
        kernel32.CloseHandle(file_handle)
        raise ValueError("screenshot pixel digest mismatch")
    if args.read_ready:
        Path(args.read_ready).write_text("sealed", encoding="utf-8")
        deadline = time.monotonic() + 20
        while not Path(args.read_release).exists():
            if time.monotonic() >= deadline:
                kernel32.CloseHandle(file_handle)
                raise TimeoutError("sealed BMP read barrier timed out")
            time.sleep(0.01)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class RGBQUAD(ctypes.Structure):
        _fields_ = [("rgbBlue", wintypes.BYTE), ("rgbGreen", wintypes.BYTE),
                    ("rgbRed", wintypes.BYTE), ("rgbReserved", wintypes.BYTE)]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", RGBQUAD * 1)]

    info = BITMAPINFO()
    ctypes.memmove(ctypes.byref(info.bmiHeader), raw[14:54], 40)
    bits = ctypes.c_void_p()
    gdi32.CreateDIBSection.argtypes = (
        wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    )
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SetDIBits.argtypes = (
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
    )
    gdi32.SetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HANDLE)
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.BitBlt.argtypes = (
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
    )
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = (wintypes.HDC,)
    gdi32.DeleteDC.restype = wintypes.BOOL
    bitmap = gdi32.CreateDIBSection(None, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    if not bitmap or not bits:
        kernel32.CloseHandle(file_handle)
        raise ctypes.WinError(ctypes.get_last_error())
    transfer_dc = gdi32.CreateCompatibleDC(None)
    try:
        source = ctypes.create_string_buffer(raw)
        copied = gdi32.SetDIBits(
            transfer_dc, bitmap, 0, int(bmp["height"]),
            ctypes.c_void_p(ctypes.addressof(source) + int(bmp["pixel_offset"])),
            ctypes.byref(info), 0,
        )
        if copied != int(bmp["height"]):
            raise ctypes.WinError(ctypes.get_last_error())
        actual_pixel_sha256 = hashlib.sha256(
            ctypes.string_at(bits, int(bmp["pixel_bytes"]))
        ).hexdigest()
        if actual_pixel_sha256 != args.pixel_sha256:
            raise ValueError("created DIB pixel digest differs")
    finally:
        if transfer_dc:
            gdi32.DeleteDC(transfer_dc)
        if not kernel32.CloseHandle(file_handle):
            raise ctypes.WinError(ctypes.get_last_error())
    width, height = int(bmp["width"]), int(bmp["height"])

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [
            ("hdc", wintypes.HDC),
            ("fErase", wintypes.BOOL),
            ("rcPaint", wintypes.RECT),
            ("fRestore", wintypes.BOOL),
            ("fIncUpdate", wintypes.BOOL),
            ("rgbReserved", wintypes.BYTE * 32),
        ]

    user32.BeginPaint.argtypes = (wintypes.HWND, ctypes.POINTER(PAINTSTRUCT))
    user32.BeginPaint.restype = wintypes.HDC
    user32.EndPaint.argtypes = (wintypes.HWND, ctypes.POINTER(PAINTSTRUCT))
    user32.EndPaint.restype = wintypes.BOOL
    user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.AdjustWindowRectEx.argtypes = (
        ctypes.POINTER(wintypes.RECT), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
    )
    user32.AdjustWindowRectEx.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = (
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    )
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
    user32.ShowWindow.restype = wintypes.BOOL
    user32.UpdateWindow.argtypes = (wintypes.HWND,)
    user32.UpdateWindow.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = (wintypes.HWND,)
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.PostQuitMessage.argtypes = (ctypes.c_int,)
    user32.PostQuitMessage.restype = None
    user32.DefWindowProcW.argtypes = (
        wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t
    )
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.IsWindow.argtypes = (wintypes.HWND,)
    user32.IsWindow.restype = wintypes.BOOL
    user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
    user32.UnregisterClassW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = (
        ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT,
        wintypes.UINT,
    )
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.MsgWaitForMultipleObjects.argtypes = (
        wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL,
        wintypes.DWORD, wintypes.DWORD,
    )
    user32.MsgWaitForMultipleObjects.restype = wintypes.DWORD

    WM_PAINT, WM_CLOSE, WM_DESTROY = 0x000F, 0x0010, 0x0002
    SRCCOPY = 0x00CC0020

    @WNDPROC
    def window_proc(hwnd, message, wparam, lparam):
        if message == WM_PAINT:
            paint = PAINTSTRUCT()
            dc = user32.BeginPaint(hwnd, ctypes.byref(paint))
            memory = gdi32.CreateCompatibleDC(dc)
            previous = gdi32.SelectObject(memory, bitmap)
            gdi32.BitBlt(dc, 0, 0, width, height, memory, 0, 0, SRCCOPY)
            gdi32.SelectObject(memory, previous)
            gdi32.DeleteDC(memory)
            user32.EndPaint(hwnd, ctypes.byref(paint))
            return 0
        if message == WM_CLOSE:
            # 通用关闭消息不具备 owner 身份；仅命名事件可以结束窗口。
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    instance = kernel32.GetModuleHandleW(None)
    window_class = WNDCLASSW(
        0,
        window_proc,
        0,
        0,
        instance,
        None,
        None,
        ctypes.c_void_p(5),
        None,
        args.window_class,
    )
    atom = user32.RegisterClassW(ctypes.byref(window_class))
    if not atom:
        gdi32.DeleteObject(bitmap)
        raise ctypes.WinError(ctypes.get_last_error())

    WS_OVERLAPPED = 0x00000000
    WS_CAPTION = 0x00C00000
    WS_SYSMENU = 0x00080000
    WS_VISIBLE = 0x10000000
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    SW_SHOWNOACTIVATE = 4
    style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_VISIBLE
    ex_style = WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    user32.CreateWindowExW.argtypes = (
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    )
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.GetDpiForWindow.argtypes = (wintypes.HWND,)
    user32.GetDpiForWindow.restype = wintypes.UINT
    adjusted = wintypes.RECT(0, 0, width, height)
    if not user32.AdjustWindowRectEx(ctypes.byref(adjusted), style, False, ex_style):
        raise ctypes.WinError(ctypes.get_last_error())

    hwnds: list[int] = []
    count = 2 if args.duplicate_window else 1
    try:
        for index in range(count):
            hwnd = user32.CreateWindowExW(
                ex_style,
                args.window_class,
                args.title,
                style,
                20 + index * 30,
                20 + index * 30,
                int(adjusted.right - adjusted.left),
                int(adjusted.bottom - adjusted.top),
                None,
                None,
                instance,
                None,
            )
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            hwnds.append(int(hwnd))
            current_client = wintypes.RECT()
            current_window = wintypes.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(current_client)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not user32.GetWindowRect(hwnd, ctypes.byref(current_window)):
                raise ctypes.WinError(ctypes.get_last_error())
            client_width = int(current_client.right - current_client.left)
            client_height = int(current_client.bottom - current_client.top)
            if client_width != width or client_height != height:
                if not user32.SetWindowPos(
                    hwnd,
                    None,
                    0,
                    0,
                    int(current_window.right - current_window.left) + width - client_width,
                    int(current_window.bottom - current_window.top) + height - client_height,
                    0x0002 | 0x0004 | 0x0010,
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            user32.UpdateWindow(hwnd)
        window_rect, client_rect, dpi = _rect(user32, hwnds[0])
        import psutil

        identity = {
            "pid": os.getpid(),
            "create_time_ns": int(round(psutil.Process().create_time() * 1_000_000_000)),
        }
        permit_path = Path(args.publication_permit)
        deadline = time.monotonic() + 20
        while not permit_path.exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("HWND publication permit timed out")
            time.sleep(0.01)
        permit = json.loads(permit_path.read_text(encoding="utf-8"))
        if (
            not isinstance(permit, dict)
            or permit.get("contract_version")
            != "portfolio_hybrid_benchmark_v2_hwnd_publication_permit_v1"
            or permit.get("owner_id") != args.owner_id
            or permit.get("content_sha256") != _content_sha256(permit)
        ):
            raise ValueError("HWND publication permit is invalid")
        publication: dict[str, object] = {
                "contract_version": "portfolio_hybrid_benchmark_v2_hwnd_publication_v1",
                "owner_id": args.owner_id,
                "screenshot_sha256": args.sha256,
                "raw_file_sha256": args.sha256,
                "bitmap_pixel_sha256": actual_pixel_sha256,
                "shutdown_nonce_sha256": hashlib.sha256(
                    args.shutdown_nonce.encode("utf-8")
                ).hexdigest(),
                "process_identity": identity,
                "hwnd": hwnds[0],
                "hwnds": hwnds,
                "window_class": args.window_class,
                "window_title": args.title,
                "window_rect": window_rect,
                "client_rect": client_rect,
                "dpi": dpi,
                "image_dimensions": {"width": width, "height": height},
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "journal_root_sha256": permit["journal_root_sha256"],
                "expected_predecessor_sha256": permit[
                    "expected_predecessor_sha256"
                ],
                "permit_content_sha256": permit["content_sha256"],
        }
        publication["content_sha256"] = _content_sha256(publication)
        _atomic_json(Path(args.publication), publication)
        kernel32.OpenEventW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.OpenEventW.restype = wintypes.HANDLE
        shutdown = kernel32.OpenEventW(0x00100000, False, args.shutdown_event_name)
        if not shutdown:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            handles = (wintypes.HANDLE * 1)(shutdown)
            message = wintypes.MSG()
            while True:
                status = int(
                    user32.MsgWaitForMultipleObjects(1, handles, False, 0xFFFFFFFF, 0x04FF)
                )
                if status == 0:
                    for hwnd in list(hwnds):
                        if user32.IsWindow(hwnd):
                            user32.DestroyWindow(hwnd)
                    break
                if status != 1:
                    raise OSError(status, "shutdown event/message wait failed")
                while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0x0001):
                    if message.message == 0x0012:
                        return 0
                    user32.TranslateMessage(ctypes.byref(message))
                    user32.DispatchMessageW(ctypes.byref(message))
        finally:
            kernel32.CloseHandle(shutdown)
        return 0
    finally:
        for hwnd in hwnds:
            if user32.IsWindow(hwnd):
                user32.DestroyWindow(hwnd)
        user32.UnregisterClassW(args.window_class, instance)
        gdi32.DeleteObject(bitmap)


def _probe_uia(args: argparse.Namespace) -> int:
    request = json.loads(Path(args.request).read_text(encoding="utf-8"))
    if (
        not isinstance(request, dict)
        or request.get("contract_version")
        != "portfolio_hybrid_benchmark_v2_uia_probe_request_v1"
        or request.get("content_sha256") != _content_sha256(request)
        or request.get("binding_bytes_sha256")
        != hashlib.sha256(_canonical_bytes(request.get("owner"))).hexdigest()
    ):
        raise ValueError("UIA probe request seal is invalid")
    owner = request["owner"]
    from app.core.window_manager import window_manager
    from app.learn.hybrid.benchmark_v2_window_owner import _raw_hwnd_attestation
    from app.operation.screen_reading.uia_provider import uia_provider

    pre = _raw_hwnd_attestation(owner)
    bound = window_manager.bind_window_by_handle(int(owner["hwnd"]))
    snapshot = uia_provider.snapshot_bound_window()
    post = _raw_hwnd_attestation(owner)
    result: dict[str, object] = {
            "contract_version": "portfolio_hybrid_benchmark_v2_uia_probe_v1",
            "owner_id": owner["owner_id"],
            "probe_nonce": request["probe_nonce"],
            "binding_bytes_sha256": request["binding_bytes_sha256"],
            "pre": pre,
            "post": post,
            "bound": {
                "handle": int(bound.handle),
                "process_id": int(bound.process_id),
                "title": bound.title,
            },
            "snapshot": snapshot,
    }
    result["content_sha256"] = _content_sha256(result)
    _atomic_json(Path(args.result), result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    serve = subparsers.add_parser("serve-bitmap")
    serve.add_argument("--image", required=True)
    serve.add_argument("--sha256", required=True)
    serve.add_argument("--pixel-sha256", required=True)
    serve.add_argument("--owner-id", required=True)
    serve.add_argument("--window-class", required=True)
    serve.add_argument("--title", required=True)
    serve.add_argument("--publication", required=True)
    serve.add_argument("--publication-permit", required=True)
    serve.add_argument("--shutdown-event-name", required=True)
    serve.add_argument("--shutdown-nonce", required=True)
    serve.add_argument("--read-ready")
    serve.add_argument("--read-release")
    serve.add_argument("--duplicate-window", action="store_true")
    probe = subparsers.add_parser("probe-uia")
    probe.add_argument("--request", required=True)
    probe.add_argument("--result", required=True)
    args = parser.parse_args(argv)
    if args.mode == "serve-bitmap":
        return _serve_bitmap(args)
    return _probe_uia(args)


if __name__ == "__main__":
    raise SystemExit(main())
