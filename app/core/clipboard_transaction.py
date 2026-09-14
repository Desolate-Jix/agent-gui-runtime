from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import ctypes
from ctypes import wintypes
import os
import threading
import time
from typing import Any, Protocol

CF_TEXT = 1
CF_BITMAP = 2
CF_OEMTEXT = 7
CF_DIB = 8
CF_HDROP = 15
CF_LOCALE = 16
CF_DIBV5 = 17
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
HWND_MESSAGE = -3
IMAGE_BITMAP = 0
LR_CREATEDIBSECTION = 0x00002000

_HGLOBAL_FORMATS = {
    CF_TEXT,
    CF_OEMTEXT,
    CF_DIB,
    CF_HDROP,
    CF_LOCALE,
    CF_DIBV5,
    CF_UNICODETEXT,
}
_REGISTERED_HGLOBAL_FORMATS = {
    "HTML Format",
    "Rich Text Format",
    "PNG",
    "ExcludeClipboardContentFromMonitorProcessing",
    "CanIncludeInClipboardHistory",
    "CanUploadToCloudClipboard",
    # Chromium 使用 HGLOBAL 保存来源信息；按原始字节保留，不解析或记录内容。
    "Chromium internal source RFH token",
    "Chromium internal source URL",
}


class ClipboardTransactionError(RuntimeError):
    """不含剪贴板内容的事务失败。"""

    def __init__(self, code: str, restore_status: str | None = None) -> None:
        self.code = code
        self.restore_status = restore_status
        self.cleanup_errors: tuple[str, ...] = ()
        message = code if restore_status is None else f"{code}:{restore_status}"
        super().__init__(message)


class _InstallFailure(ClipboardTransactionError):
    def __init__(self, sequence: int, *, rollback_attempted: bool = False) -> None:
        self.sequence = sequence
        self.rollback_attempted = rollback_attempted
        self.rolled_back = False
        super().__init__("temporary_write_failed")


@dataclass(frozen=True)
class ClipboardEntry:
    format: int
    data: bytes = field(repr=False)
    name: str | None = None
    _bitmap_handle: int | None = field(default=None, repr=False, compare=False)


@dataclass
class ClipboardSnapshot:
    entries: tuple[ClipboardEntry, ...] = field(repr=False)
    sequence: int | None = field(default=None, compare=False)
    _bitmap_handles: set[int] = field(default_factory=set, repr=False, compare=False)


class ClipboardBackend(Protocol):
    def capture(self) -> ClipboardSnapshot: ...

    def replace_with_text(self, text: str, expected_sequence: int | None, *, snapshot: ClipboardSnapshot) -> int: ...

    def verify_owned_text(self, sequence: int, text: str) -> int: ...

    def restore_if_owned(self, snapshot: ClipboardSnapshot, sequence: int) -> str: ...


class ClipboardTextTransaction:
    """临时替换文本并在未发生竞争时无损恢复剪贴板。"""

    def __init__(self, text: str, *, restore: bool = True, backend: ClipboardBackend | None = None) -> None:
        self._validate_text(text)
        self._text = text
        self._restore_requested = bool(restore)
        self._backend: ClipboardBackend = backend if backend is not None else WindowsClipboardBackend()
        self._snapshot: ClipboardSnapshot | None = None
        self._sequence: int | None = None
        self._temporary_installed = False
        self.cleanup_errors: tuple[str, ...] = ()
        self.status = "not_started"

    def __repr__(self) -> str:
        return f"ClipboardTextTransaction(restore={self._restore_requested!r}, status={self.status!r})"

    def __enter__(self) -> ClipboardTextTransaction:
        try:
            self._snapshot = self._backend.capture()
            self._sequence = self._snapshot.sequence
            self._sequence = self._backend.replace_with_text(
                self._text, self._snapshot.sequence, snapshot=self._snapshot,
            )
            self._temporary_installed = True
        except _InstallFailure as exc:
            self._temporary_installed = not exc.rollback_attempted
            self._sequence = exc.sequence
            self.cleanup_errors = exc.cleanup_errors
            if exc.rollback_attempted:
                self.status = "restored" if exc.rolled_back else "restore_failed"
            self._finish_failed_enter()
            primary = ClipboardTransactionError("temporary_write_failed", self.status)
            self._attach_cleanup_status(primary)
            raise primary from None
        except ClipboardTransactionError as error:
            self.cleanup_errors = error.cleanup_errors
            self.status = error.restore_status or self.status
            self._finish_failed_enter()
            primary = ClipboardTransactionError(error.code, self.status)
            self._attach_cleanup_status(primary)
            raise primary from None
        except Exception:
            self._finish_failed_enter()
            primary = ClipboardTransactionError("temporary_write_failed", self.status)
            self._attach_cleanup_status(primary)
            raise primary from None
        self.status = "pending_restore" if self._restore_requested else "not_requested"
        return self

    def verify_current_text(self) -> int:
        if not self._temporary_installed or self._sequence is None:
            raise ClipboardTransactionError("transaction_not_started", self.status)
        try:
            attempts = self._backend.verify_owned_text(self._sequence, self._text)
        except ClipboardTransactionError:
            raise
        except Exception:
            raise ClipboardTransactionError("clipboard_verification_failed", self.status) from None
        if type(attempts) is not int or attempts < 1:
            raise ClipboardTransactionError("clipboard_verification_failed", self.status)
        return attempts

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        cleanup_error = self._cleanup()
        if exc is not None:
            self._attach_cleanup_status(exc)
            return False
        if cleanup_error is not None:
            raise cleanup_error
        return False

    def _finish_failed_enter(self) -> None:
        cleanup_error = self._cleanup(force_restore=True)
        if cleanup_error is not None:
            self.status = cleanup_error.restore_status or self.status

    def _cleanup(self, *, force_restore: bool = False) -> ClipboardTransactionError | None:
        error = None
        failures = list(self.cleanup_errors)
        if self._temporary_installed:
            self._temporary_installed = False
            if not self._restore_requested and not force_restore:
                self.status = "not_requested"
            else:
                outcome = "restore_failed"
                try:
                    if self._snapshot is not None and self._sequence is not None:
                        outcome = self._backend.restore_if_owned(self._snapshot, self._sequence)
                except ClipboardTransactionError as failure:
                    failures.extend((failure.code, *failure.cleanup_errors))
                    if failure.code == "ownership_conflict":
                        outcome = "conflict"
                except Exception:
                    outcome = "restore_failed"
                self.status = outcome if outcome in {"restored", "conflict"} else "restore_failed"
                if self.status != "restored":
                    code = "ownership_conflict" if self.status == "conflict" else "restore_failed"
                    error = ClipboardTransactionError(code, self.status)
                    failures.append(code)
        release_failed = False
        try:
            self._release_snapshot()
        except Exception:
            release_failed = True
            failures.append("snapshot_release_failed")
        close = getattr(self._backend, "close", None)
        if callable(close):
            try:
                close()
            except Exception as failure:
                release_failed = True
                failures.append("owner_release_failed")
                if isinstance(failure, ClipboardTransactionError):
                    failures.extend((failure.code, *failure.cleanup_errors))
        self.cleanup_errors = tuple(dict.fromkeys(failures))
        if release_failed:
            self.status = "restore_failed"
            error = ClipboardTransactionError("clipboard_cleanup_failed", self.status)
        if error is not None:
            self._attach_cleanup_status(error)
        return error

    def _release_snapshot(self) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            return
        release = getattr(self._backend, "release_snapshot", None)
        if callable(release):
            release(snapshot)
        self._snapshot = None

    def _attach_cleanup_status(self, primary: BaseException) -> None:
        try:
            setattr(primary, "clipboard_restore_status", self.status)
            setattr(primary, "cleanup_errors", self.cleanup_errors)
        except Exception:
            pass
        add_note = getattr(primary, "add_note", None)
        if callable(add_note):
            try:
                add_note(f"clipboard_restore_status={self.status}")
                if self.cleanup_errors:
                    add_note("clipboard_cleanup_errors=" + ",".join(self.cleanup_errors))
            except Exception:
                pass

    @staticmethod
    def _validate_text(text: str) -> None:
        if not isinstance(text, str):
            raise ClipboardTransactionError("invalid_text")
        if "\x00" in text or any(0xD800 <= ord(char) <= 0xDFFF for char in text):
            raise ClipboardTransactionError("invalid_text")


class WindowsClipboardBackend:
    """使用隐藏消息窗口和 Win32 原语实现的主剪贴板后端。"""

    def __init__(self, *, open_attempts: int = 8, retry_seconds: float = 0.03) -> None:
        self._open_attempts = max(1, int(open_attempts))
        self._retry_seconds = max(0.0, float(retry_seconds))
        self._api: _Win32ClipboardApi | None = None
        self._owner_hwnd: int | None = None
        self._owner_thread_id: int | None = None
        self._clipboard_open = False

    def capture(self) -> ClipboardSnapshot:
        api = self._require_api()
        entries: list[ClipboardEntry] = []
        snapshot = ClipboardSnapshot(())
        try:
            with self._clipboard_lock(api):
                format_id = 0
                while True:
                    api.set_last_error(0)
                    format_id = int(api.user32.EnumClipboardFormats(format_id))
                    if format_id == 0:
                        if api.get_last_error() != 0:
                            raise ClipboardTransactionError("clipboard_capture_failed")
                        break
                    entry = self._capture_entry(api, format_id)
                    entries.append(entry)
                    if entry._bitmap_handle is not None:
                        snapshot._bitmap_handles.add(entry._bitmap_handle)
                snapshot.entries = tuple(entries)
                snapshot.sequence = self._require_sequence(api)
            return snapshot
        except Exception as cause:
            failure = cause if isinstance(cause, ClipboardTransactionError) else ClipboardTransactionError("clipboard_capture_failed")
            try:
                self.release_snapshot(snapshot)
            except Exception:
                failure.restore_status = "restore_failed"
                failure.cleanup_errors += ("snapshot_release_failed",)
            raise failure from None

    def replace_with_text(self, text: str, expected_sequence: int | None, *, snapshot: ClipboardSnapshot) -> int:
        api = self._require_api()
        if not expected_sequence:
            raise ClipboardTransactionError("clipboard_sequence_unavailable")
        hglobal = self._allocate_hglobal(api, text.encode("utf-16-le") + b"\x00\x00")
        transferred = False
        mutated = False
        sequence = 0
        failure = None
        try:
            with self._clipboard_lock(api):
                if self._require_sequence(api) != expected_sequence:
                    raise ClipboardTransactionError("ownership_conflict")
                if not api.user32.EmptyClipboard():
                    raise ClipboardTransactionError("temporary_write_failed")
                mutated = True
                try:
                    sequence = self._require_sequence(api)
                    if not api.user32.SetClipboardData(CF_UNICODETEXT, hglobal):
                        raise ClipboardTransactionError("temporary_write_failed")
                    transferred = True
                    sequence = self._require_sequence(api)
                except Exception as cause:
                    failure = _InstallFailure(sequence, rollback_attempted=True)
                    if isinstance(cause, ClipboardTransactionError):
                        failure.cleanup_errors = (cause.code, *cause.cleanup_errors)
                    # 同一把锁尚未释放，外部无法改写；序号不可读时只能在此回滚。
                    try:
                        self._restore_snapshot_locked(api, snapshot)
                        failure.rolled_back = True
                    except Exception as rollback_error:
                        failure.cleanup_errors += ("restore_failed",)
                        if isinstance(rollback_error, ClipboardTransactionError):
                            failure.cleanup_errors += (rollback_error.code, *rollback_error.cleanup_errors)
            if failure is None:
                # Windows 在关闭写入锁时仍会增加序号，不能把锁内序号当作已提交版本。
                with self._clipboard_lock(api):
                    owner = int(api.user32.GetClipboardOwner() or 0)
                    current_handle = int(api.user32.GetClipboardData(CF_UNICODETEXT) or 0)
                    expected = text.encode("utf-16-le") + b"\x00\x00"
                    if (
                        owner != self._owner(api)
                        or current_handle != hglobal
                        or self._read_hglobal(api, current_handle)[:len(expected)] != expected
                    ):
                        raise ClipboardTransactionError("ownership_conflict")
                    # 只在初次安装且原始内存对象仍归本事务时取提交序号；后续检查不重认领。
                    sequence = self._require_sequence(api)
        except ClipboardTransactionError as cause:
            if not mutated:
                raise
            failure = failure or _InstallFailure(sequence)
            failure.rolled_back = False
            failure.cleanup_errors += (cause.code, *cause.cleanup_errors)
        except Exception:
            if not mutated:
                raise ClipboardTransactionError("temporary_write_failed") from None
            failure = failure or _InstallFailure(sequence)
            failure.rolled_back = False
            failure.cleanup_errors += ("clipboard_operation_failed",)
        finally:
            if not transferred:
                api.kernel32.GlobalFree(hglobal)
        if failure is not None:
            raise failure from None
        return sequence

    def verify_owned_text(self, sequence: int, text: str) -> int:
        api = self._require_api()
        with self._clipboard_lock(api):
            if self._require_sequence(api) != sequence or int(api.user32.GetClipboardOwner() or 0) != self._owner(api):
                raise ClipboardTransactionError("ownership_conflict")
            handle = int(api.user32.GetClipboardData(CF_UNICODETEXT) or 0)
            expected = text.encode("utf-16-le") + b"\x00\x00"
            # GlobalSize 是容量，不是文本长度；只比较完整正文及其终止符。
            if not handle or self._read_hglobal(api, handle)[:len(expected)] != expected:
                raise ClipboardTransactionError("ownership_conflict")
            return 1

    def restore_if_owned(self, snapshot: ClipboardSnapshot, sequence: int) -> str:
        api = self._require_api()
        with self._clipboard_lock(api):
            if self._require_sequence(api) != sequence or int(api.user32.GetClipboardOwner() or 0) != self._owner(api):
                raise ClipboardTransactionError("ownership_conflict")
            self._restore_snapshot_locked(api, snapshot)
            return "restored"

    def _restore_snapshot_locked(self, api: _Win32ClipboardApi, snapshot: ClipboardSnapshot) -> None:
        prepared: list[tuple[ClipboardEntry, int]] = []
        transferred: set[int] = set()
        try:
            for entry in snapshot.entries:
                if entry._bitmap_handle is None:
                    prepared.append((entry, self._allocate_hglobal(api, entry.data)))
                else:
                    prepared.append((entry, entry._bitmap_handle))
            if not api.user32.EmptyClipboard():
                raise ClipboardTransactionError("restore_failed")
            for entry, handle in prepared:
                if not api.user32.SetClipboardData(entry.format, handle):
                    raise ClipboardTransactionError("restore_failed")
                transferred.add(handle)
                if entry._bitmap_handle is not None:
                    snapshot._bitmap_handles.discard(handle)
        finally:
            for entry, handle in prepared:
                if handle not in transferred:
                    if entry._bitmap_handle is None:
                        api.kernel32.GlobalFree(handle)
                    # 未转移的 bitmap 仍归 snapshot，统一在 release_snapshot 释放。

    def release_snapshot(self, snapshot: ClipboardSnapshot) -> None:
        api = self._api
        if api is None:
            return
        failed = False
        for handle in tuple(snapshot._bitmap_handles):
            if api.gdi32.DeleteObject(handle):
                snapshot._bitmap_handles.remove(handle)
            else:
                failed = True
        if failed:
            raise ClipboardTransactionError("snapshot_release_failed")

    def close(self) -> None:
        if self._owner_hwnd is None:
            return
        if self._owner_thread_id != threading.get_ident():
            raise ClipboardTransactionError("clipboard_owner_thread_changed")
        if self._clipboard_open:
            self._close_clipboard(self._require_api())
        # 数据已立即交给系统，不依赖延迟渲染；销毁窗口不清空剪贴板。
        if not self._require_api().user32.DestroyWindow(self._owner_hwnd):
            raise ClipboardTransactionError("clipboard_owner_release_failed")
        self._owner_hwnd = None
        self._owner_thread_id = None

    def _capture_entry(self, api: _Win32ClipboardApi, format_id: int) -> ClipboardEntry:
        if format_id == CF_BITMAP:
            bitmap = int(api.user32.GetClipboardData(format_id) or 0)
            if not bitmap:
                raise ClipboardTransactionError("clipboard_data_unavailable")
            copy = int(api.user32.CopyImage(bitmap, IMAGE_BITMAP, 0, 0, LR_CREATEDIBSECTION) or 0)
            if not copy:
                raise ClipboardTransactionError("unsupported_format")
            return ClipboardEntry(format_id, b"", _bitmap_handle=copy)
        name = self._format_name(api, format_id) if format_id >= 0xC000 else None
        if format_id not in _HGLOBAL_FORMATS and name not in _REGISTERED_HGLOBAL_FORMATS:
            raise ClipboardTransactionError("unsupported_format")
        handle = int(api.user32.GetClipboardData(format_id) or 0)
        if not handle:
            raise ClipboardTransactionError("clipboard_data_unavailable")
        return ClipboardEntry(format_id, self._read_hglobal(api, handle), name=name)

    def _open(self, api: _Win32ClipboardApi) -> None:
        hwnd = self._owner(api)
        if self._clipboard_open:
            # 仅清理由本实例已打开、但上一次关闭失败的锁；不操作外部所有者。
            self._close_clipboard(api)
        for attempt in range(self._open_attempts):
            if api.user32.OpenClipboard(hwnd):
                self._clipboard_open = True
                return
            if attempt + 1 < self._open_attempts:
                time.sleep(self._retry_seconds)
        raise ClipboardTransactionError("clipboard_open_failed")

    def _close_clipboard(self, api: _Win32ClipboardApi) -> None:
        if not api.user32.CloseClipboard():
            raise ClipboardTransactionError("clipboard_close_failed")
        self._clipboard_open = False

    @contextmanager
    def _clipboard_lock(self, api: _Win32ClipboardApi):
        self._open(api)
        primary = None
        try:
            yield
        except BaseException as failure:
            primary = failure
            raise
        finally:
            try:
                self._close_clipboard(api)
            except ClipboardTransactionError as failure:
                if primary is None:
                    raise
                # 关闭失败是次要错误，不能覆盖捕获或写入的原始失败。
                if isinstance(primary, ClipboardTransactionError):
                    primary.cleanup_errors += (failure.code,)
                primary.add_note("clipboard_cleanup_errors=" + failure.code)

    def _owner(self, api: _Win32ClipboardApi) -> int:
        if self._owner_hwnd:
            if self._owner_thread_id != threading.get_ident():
                raise ClipboardTransactionError("clipboard_owner_thread_changed")
            return self._owner_hwnd
        hwnd = int(
                api.user32.CreateWindowExW(
                    0,
                    "STATIC",
                    "clipboard-transaction-owner",
                    0,
                    0,
                    0,
                    0,
                    0,
                    HWND_MESSAGE,
                    None,
                    api.kernel32.GetModuleHandleW(None),
                    None,
                )
                or 0
        )
        if not hwnd:
            raise ClipboardTransactionError("clipboard_owner_unavailable")
        self._owner_hwnd = hwnd
        self._owner_thread_id = threading.get_ident()
        return hwnd

    def _require_sequence(self, api: _Win32ClipboardApi) -> int:
        sequence = int(api.user32.GetClipboardSequenceNumber())
        if sequence == 0:
            raise ClipboardTransactionError("clipboard_sequence_unavailable")
        return sequence

    @staticmethod
    def _read_hglobal(api: _Win32ClipboardApi, handle: int) -> bytes:
        size = int(api.kernel32.GlobalSize(handle))
        if size <= 0:
            raise ClipboardTransactionError("clipboard_data_unavailable")
        pointer = api.kernel32.GlobalLock(handle)
        if not pointer and size:
            raise ClipboardTransactionError("clipboard_data_unavailable")
        try:
            return ctypes.string_at(pointer, size) if size else b""
        finally:
            if pointer:
                api.kernel32.GlobalUnlock(handle)

    @staticmethod
    def _allocate_hglobal(api: _Win32ClipboardApi, data: bytes) -> int:
        handle = int(api.kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, max(1, len(data))) or 0)
        if not handle:
            raise ClipboardTransactionError("clipboard_memory_allocation_failed")
        pointer = api.kernel32.GlobalLock(handle)
        if not pointer:
            api.kernel32.GlobalFree(handle)
            raise ClipboardTransactionError("clipboard_memory_allocation_failed")
        try:
            if data:
                ctypes.memmove(pointer, data, len(data))
        finally:
            api.kernel32.GlobalUnlock(handle)
        return handle

    @staticmethod
    def _format_name(api: _Win32ClipboardApi, format_id: int) -> str | None:
        buffer = ctypes.create_unicode_buffer(256)
        length = int(api.user32.GetClipboardFormatNameW(format_id, buffer, len(buffer)))
        return buffer.value[:length] if length else None

    def _require_api(self) -> _Win32ClipboardApi:
        if self._api is None:
            if os.name != "nt":
                raise ClipboardTransactionError("clipboard_backend_unavailable")
            self._api = _Win32ClipboardApi()
        return self._api


class _Win32ClipboardApi:
    @staticmethod
    def get_last_error():
        return ctypes.get_last_error()

    @staticmethod
    def set_last_error(value):
        ctypes.set_last_error(value)

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.user32.OpenClipboard.argtypes = [wintypes.HWND]
        self.user32.OpenClipboard.restype = wintypes.BOOL
        self.user32.CloseClipboard.argtypes = []
        self.user32.CloseClipboard.restype = wintypes.BOOL
        self.user32.EmptyClipboard.argtypes = []
        self.user32.EmptyClipboard.restype = wintypes.BOOL
        self.user32.GetClipboardData.argtypes = [wintypes.UINT]
        self.user32.GetClipboardData.restype = wintypes.HANDLE
        self.user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        self.user32.SetClipboardData.restype = wintypes.HANDLE
        self.user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
        self.user32.EnumClipboardFormats.restype = wintypes.UINT
        self.user32.GetClipboardSequenceNumber.argtypes = []
        self.user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
        self.user32.GetClipboardOwner.argtypes = []
        self.user32.GetClipboardOwner.restype = wintypes.HWND
        self.user32.GetClipboardFormatNameW.argtypes = [wintypes.UINT, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetClipboardFormatNameW.restype = ctypes.c_int
        self.user32.CreateWindowExW.argtypes = [
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
            wintypes.LPVOID,
        ]
        self.user32.CreateWindowExW.restype = wintypes.HWND
        self.user32.DestroyWindow.argtypes = [wintypes.HWND]
        self.user32.DestroyWindow.restype = wintypes.BOOL
        self.user32.CopyImage.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.user32.CopyImage.restype = wintypes.HANDLE
        self.kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        self.kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        self.kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalFree.restype = wintypes.HGLOBAL
        self.kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalLock.restype = wintypes.LPVOID
        self.kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalUnlock.restype = wintypes.BOOL
        self.kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
        self.kernel32.GlobalSize.restype = ctypes.c_size_t
        self.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self.gdi32.DeleteObject.restype = wintypes.BOOL
