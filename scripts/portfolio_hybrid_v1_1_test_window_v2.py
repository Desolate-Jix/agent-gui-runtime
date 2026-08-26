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


def _serve_bitmap(args: argparse.Namespace) -> int:
    image = Path(args.image).resolve()
    raw = image.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.sha256:
        raise ValueError("screenshot SHA-256 mismatch")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    user32.SetProcessDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
    user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
    if not user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
        raise ctypes.WinError(ctypes.get_last_error())

    IMAGE_BITMAP = 0
    LR_LOADFROMFILE = 0x10
    LR_CREATEDIBSECTION = 0x2000
    user32.LoadImageW.argtypes = (
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    )
    user32.LoadImageW.restype = wintypes.HANDLE
    bitmap = user32.LoadImageW(
        None, str(image), IMAGE_BITMAP, 0, 0, LR_LOADFROMFILE | LR_CREATEDIBSECTION
    )
    if not bitmap:
        raise ctypes.WinError(ctypes.get_last_error())

    class BITMAP(ctypes.Structure):
        _fields_ = [
            ("bmType", wintypes.LONG),
            ("bmWidth", wintypes.LONG),
            ("bmHeight", wintypes.LONG),
            ("bmWidthBytes", wintypes.LONG),
            ("bmPlanes", wintypes.WORD),
            ("bmBitsPixel", wintypes.WORD),
            ("bmBits", ctypes.c_void_p),
        ]

    gdi32.GetObjectW.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p)
    gdi32.GetObjectW.restype = ctypes.c_int
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
    bitmap_info = BITMAP()
    if not gdi32.GetObjectW(bitmap, ctypes.sizeof(bitmap_info), ctypes.byref(bitmap_info)):
        gdi32.DeleteObject(bitmap)
        raise ctypes.WinError(ctypes.get_last_error())
    width, height = int(bitmap_info.bmWidth), int(bitmap_info.bmHeight)

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
            user32.DestroyWindow(hwnd)
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
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
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
    serve.add_argument("--owner-id", required=True)
    serve.add_argument("--window-class", required=True)
    serve.add_argument("--title", required=True)
    serve.add_argument("--publication", required=True)
    serve.add_argument("--publication-permit", required=True)
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
