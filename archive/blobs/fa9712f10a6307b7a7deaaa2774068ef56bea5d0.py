from __future__ import annotations

from dataclasses import dataclass
import ctypes

import pytest

from app.core.clipboard_transaction import (
    CF_DIB,
    CF_BITMAP,
    CF_HDROP,
    CF_LOCALE,
    CF_TEXT,
    CF_UNICODETEXT,
    ClipboardEntry,
    ClipboardSnapshot,
    ClipboardTextTransaction,
    ClipboardTransactionError,
    WindowsClipboardBackend,
)


@dataclass
class FakeClipboardBackend:
    snapshot: ClipboardSnapshot
    unsupported_formats: set[int] | None = None
    fail_restore: bool = False

    def __post_init__(self) -> None:
        self.sequence = 100
        self.owner = "external-owner"
        self.current = self.snapshot
        self.events: list[str] = []
        self.restore_calls = 0

    def capture(self) -> ClipboardSnapshot:
        self.events.append("capture")
        unsupported = self.unsupported_formats or set()
        for entry in self.current.entries:
            if entry.format in unsupported:
                raise ClipboardTransactionError("unsupported_format")
        return ClipboardSnapshot(tuple(self.current.entries), sequence=self.sequence)

    def replace_with_text(self, text: str, expected_sequence: int | None, *, snapshot: ClipboardSnapshot):
        self.events.append("replace")
        if expected_sequence != self.sequence:
            raise ClipboardTransactionError("ownership_conflict")
        self.sequence += 1
        self.owner = "transaction-owner"
        self.current = ClipboardSnapshot((ClipboardEntry(CF_UNICODETEXT, text.encode("utf-16-le") + b"\x00\x00"),))
        return self.sequence

    def verify_owned_text(self, sequence: int, text: str) -> int:
        self.events.append("verify")
        expected = text.encode("utf-16-le") + b"\x00\x00"
        if self.owner != "transaction-owner" or self.sequence != sequence or self.current.entries != (ClipboardEntry(CF_UNICODETEXT, expected),):
            raise ClipboardTransactionError("ownership_conflict")
        return 1

    def restore_if_owned(self, snapshot: ClipboardSnapshot, sequence: int) -> str:
        self.restore_calls += 1
        self.events.append("restore")
        if self.owner != "transaction-owner" or self.sequence != sequence:
            return "conflict"
        if self.fail_restore:
            raise OSError("backend error includes no clipboard contents")
        self.current = ClipboardSnapshot(tuple(snapshot.entries))
        self.sequence += 1
        self.owner = "transaction-owner"
        return "restored"

    def external_copy(self, text: str) -> None:
        self.sequence += 1
        self.owner = "another-owner"
        self.current = ClipboardSnapshot((ClipboardEntry(CF_UNICODETEXT, text.encode("utf-16-le") + b"\x00\x00"),))


def _snapshot(*entries: ClipboardEntry) -> ClipboardSnapshot:
    return ClipboardSnapshot(entries)


def test_multiformat_clipboard_is_restored_after_verified_transaction() -> None:
    original = _snapshot(
        ClipboardEntry(CF_UNICODETEXT, b"o\x00l\x00d\x00\x00\x00"),
        ClipboardEntry(CF_TEXT, b"old\x00"),
        ClipboardEntry(CF_LOCALE, b"\x09\x04\x00\x00"),
        ClipboardEntry(CF_DIB, b"dib-bytes"),
        ClipboardEntry(CF_HDROP, b"drop-files"),
        ClipboardEntry(0xC001, b"{\\rtf1\\ansi old}"),
    )
    backend = FakeClipboardBackend(original)

    with ClipboardTextTransaction("temporary", backend=backend) as transaction:
        assert transaction.verify_current_text() == 1

    assert transaction.status == "restored"
    assert backend.current == original
    assert backend.events == ["capture", "replace", "verify", "restore"]


def test_empty_clipboard_is_restored_as_genuinely_empty() -> None:
    backend = FakeClipboardBackend(_snapshot())

    with ClipboardTextTransaction("temporary", backend=backend) as transaction:
        transaction.verify_current_text()

    assert transaction.status == "restored"
    assert backend.current.entries == ()


def test_primary_body_exception_is_preserved_after_successful_cleanup() -> None:
    backend = FakeClipboardBackend(_snapshot(ClipboardEntry(CF_UNICODETEXT, b"o\x00l\x00d\x00\x00\x00")))
    primary = RuntimeError("body failure")

    with pytest.raises(RuntimeError) as captured:
        with ClipboardTextTransaction("temporary", backend=backend) as transaction:
            raise primary

    assert captured.value is primary
    assert getattr(primary, "clipboard_restore_status") == "restored"
    assert transaction.status == "restored"
    assert backend.current.entries[0].data == b"o\x00l\x00d\x00\x00\x00"


def test_unsupported_format_fails_before_clipboard_overwrite() -> None:
    backend = FakeClipboardBackend(
        _snapshot(ClipboardEntry(14, b"metafile-handle")),
        unsupported_formats={14},
    )

    with pytest.raises(ClipboardTransactionError) as captured:
        with ClipboardTextTransaction("temporary", backend=backend):
            raise AssertionError("body must not run")

    assert captured.value.code == "unsupported_format"
    assert backend.events == ["capture"]
    assert backend.current.entries == (ClipboardEntry(14, b"metafile-handle"),)


def test_restore_failure_raises_sanitized_error_without_clipboard_text() -> None:
    backend = FakeClipboardBackend(
        _snapshot(ClipboardEntry(CF_UNICODETEXT, b"s\x00e\x00c\x00r\x00e\x00t\x00\x00\x00")),
        fail_restore=True,
    )

    with pytest.raises(ClipboardTransactionError) as captured:
        with ClipboardTextTransaction("temporary", backend=backend) as transaction:
            transaction.verify_current_text()

    assert captured.value.code == "restore_failed"
    assert captured.value.restore_status == "restore_failed"
    assert "secret" not in str(captured.value)
    assert "temporary" not in repr(captured.value)
    assert transaction.status == "restore_failed"


def test_primary_exception_survives_conflicting_concurrent_copy() -> None:
    backend = FakeClipboardBackend(_snapshot(ClipboardEntry(CF_UNICODETEXT, b"o\x00l\x00d\x00\x00\x00")))
    primary = ValueError("primary failure")

    with pytest.raises(ValueError) as captured:
        with ClipboardTextTransaction("temporary", backend=backend) as transaction:
            backend.external_copy("newer")
            raise primary

    assert captured.value is primary
    assert getattr(primary, "clipboard_restore_status") == "conflict"
    assert transaction.status == "conflict"
    assert backend.current.entries == (ClipboardEntry(CF_UNICODETEXT, b"n\x00e\x00w\x00e\x00r\x00\x00\x00"),)
    assert backend.restore_calls == 1


def test_conflicting_concurrent_copy_raises_and_never_overwrites_newer_contents() -> None:
    backend = FakeClipboardBackend(_snapshot(ClipboardEntry(CF_UNICODETEXT, b"o\x00l\x00d\x00\x00\x00")))

    with pytest.raises(ClipboardTransactionError) as captured:
        with ClipboardTextTransaction("temporary", backend=backend) as transaction:
            backend.external_copy("newer")

    assert captured.value.code == "ownership_conflict"
    assert captured.value.restore_status == "conflict"
    assert backend.current.entries == (ClipboardEntry(CF_UNICODETEXT, b"n\x00e\x00w\x00e\x00r\x00\x00\x00"),)
    assert transaction.status == "conflict"


def test_restore_opt_out_leaves_temporary_clipboard_and_reports_not_requested() -> None:
    backend = FakeClipboardBackend(_snapshot(ClipboardEntry(CF_UNICODETEXT, b"o\x00l\x00d\x00\x00\x00")))

    with ClipboardTextTransaction("temporary", restore=False, backend=backend) as transaction:
        transaction.verify_current_text()

    assert transaction.status == "not_requested"
    assert backend.restore_calls == 0


def test_invalid_text_is_rejected_before_capture() -> None:
    backend = FakeClipboardBackend(_snapshot(ClipboardEntry(CF_UNICODETEXT, b"o\x00l\x00d\x00\x00\x00")))

    with pytest.raises(ClipboardTransactionError) as captured:
        ClipboardTextTransaction("temporary\x00text", backend=backend)

    assert captured.value.code == "invalid_text"
    assert backend.events == []


class FakeWin32Api:
    """只在 Python 内存模拟 Win32 所有权；绝不调用真实剪贴板或窗口。"""

    def __init__(self, formats, *, sequence=100, owner=900):
        self.user32 = self.kernel32 = self.gdi32 = self
        self.sequence, self.owner = sequence, owner
        self.events = []
        self.formats = {}
        self.buffers = {}
        self.bitmap_data = {}
        self.live_hglobals = set()
        self.live_bitmaps = set()
        self.created_windows = set()
        self.deleted_bitmaps = []
        self.opened = False
        self.open_owner = 0
        self.last_error = 0
        self.next_handle = 1000
        self.open_calls = self.set_calls = 0
        self.close_calls = 0
        self.fail_open_calls = set()
        self.fail_set_calls = set()
        self.fail_close_calls = set()
        self.fail_enum = False
        self.fail_destroy = False
        self.fail_delete = False
        for format_id, data in formats.items():
            self.formats[format_id] = self._seed(format_id, data)

    def _handle(self):
        self.next_handle += 1
        return self.next_handle

    def _seed(self, format_id, data):
        if format_id == CF_BITMAP:
            handle = self._handle()
            self.live_bitmaps.add(handle)
            self.bitmap_data[handle] = data
        else:
            handle = self.GlobalAlloc(2, len(data))
            if data:
                ctypes.memmove(self.GlobalLock(handle), data, len(data))
        return handle

    def current_bytes(self, format_id):
        handle = self.formats.get(format_id)
        if handle is None:
            return None
        if format_id == CF_BITMAP:
            return self.bitmap_data[handle]
        return bytes(self.buffers[handle])

    def external_copy(self, text):
        self._empty_data()
        self.formats[CF_UNICODETEXT] = self._seed(CF_UNICODETEXT, text.encode("utf-16-le") + b"\x00\x00")
        self.owner = 900
        self.sequence += 1
        self.events.append("external-copy")

    def GlobalAlloc(self, flags, size):
        handle = self._handle()
        capacity = (size + 7) // 8 * 8
        buffer = ctypes.create_string_buffer(capacity)
        if capacity and not flags & 0x40:
            ctypes.memset(ctypes.addressof(buffer), 0xA5, capacity)
        self.buffers[handle] = buffer
        self.live_hglobals.add(handle)
        self.events.append("allocate")
        return handle

    def GlobalSize(self, handle):
        return len(self.buffers[handle]) if handle in self.live_hglobals else 0

    def GlobalLock(self, handle):
        return ctypes.addressof(self.buffers[handle]) if handle in self.live_hglobals and self.GlobalSize(handle) else 0

    def GlobalUnlock(self, handle):
        return True

    def GlobalFree(self, handle):
        if handle not in self.live_hglobals:
            return handle
        self.live_hglobals.remove(handle)
        self.events.append("free")
        return 0

    def GetModuleHandleW(self, _):
        return 1

    def CreateWindowExW(self, *args):
        assert args[3] == 0 and args[8] == -3
        handle = self._handle()
        self.created_windows.add(handle)
        return handle

    def DestroyWindow(self, handle):
        if self.fail_destroy:
            return False
        assert handle in self.created_windows
        self.created_windows.remove(handle)
        if self.owner == handle:
            self.owner = 0
        self.events.append("destroy-window")
        return True

    def OpenClipboard(self, handle):
        self.open_calls += 1
        if self.open_calls in self.fail_open_calls:
            return False
        assert handle in self.created_windows and not self.opened
        self.opened, self.open_owner = True, handle
        self.events.append("open")
        return True

    def CloseClipboard(self):
        assert self.opened
        self.close_calls += 1
        if self.close_calls in self.fail_close_calls:
            return False
        self.opened = False
        self.events.append("close")
        return True

    def _empty_data(self):
        for format_id, handle in self.formats.items():
            if format_id == CF_BITMAP:
                assert self.DeleteObject(handle)
            else:
                assert self.GlobalFree(handle) == 0
        self.formats.clear()

    def EmptyClipboard(self):
        assert self.opened
        self._empty_data()
        self.owner = self.open_owner
        self.sequence += 1
        self.events.append("empty")
        return True

    def SetClipboardData(self, format_id, handle):
        assert self.opened
        self.set_calls += 1
        if self.set_calls in self.fail_set_calls:
            return 0
        self.formats[format_id] = handle
        self.sequence += 1
        self.events.append("set")
        return handle

    def GetClipboardData(self, format_id):
        assert self.opened
        return self.formats.get(format_id, 0)

    def GetClipboardSequenceNumber(self):
        return self.sequence

    def GetClipboardOwner(self):
        return self.owner

    def EnumClipboardFormats(self, current):
        assert self.opened
        if self.fail_enum:
            self.last_error = 5
            return 0
        keys = list(self.formats)
        index = keys.index(current) + 1 if current else 0
        return keys[index] if index < len(keys) else 0

    def get_last_error(self):
        return self.last_error

    def set_last_error(self, value):
        self.last_error = value

    def GetClipboardFormatNameW(self, format_id, buffer, capacity):
        name = {0xC001: "Rich Text Format", 0xC002: "HTML Format", 0xC003: "PNG"}.get(format_id, "unknown")
        buffer.value = name
        return len(name)

    def CopyImage(self, handle, *args):
        assert handle in self.live_bitmaps
        return self._seed(CF_BITMAP, self.bitmap_data[handle])

    def DeleteObject(self, handle):
        self.deleted_bitmaps.append(handle)
        if self.fail_delete or handle not in self.live_bitmaps:
            return False
        self.live_bitmaps.remove(handle)
        return True


def build_windows_backend(api):
    backend = WindowsClipboardBackend(open_attempts=1, retry_seconds=0)
    backend._api = api
    return backend


def test_windows_text_verification_ignores_allocator_padding_and_closes_owner():
    api = FakeWin32Api({CF_UNICODETEXT: b"o\x00\x00\x00", CF_DIB: b"dib"})
    original = {key: api.current_bytes(key) for key in api.formats}
    with ClipboardTextTransaction("x", backend=build_windows_backend(api)) as transaction:
        assert transaction.verify_current_text() == 1
    assert transaction.status == "restored"
    assert {key: api.current_bytes(key) for key in api.formats} == original
    assert not api.created_windows
    assert api.live_hglobals == set(api.formats.values())


@pytest.mark.parametrize("name", ["Chromium internal source RFH token", "Chromium internal source URL"])
def test_windows_chromium_provenance_is_restored_as_opaque_bytes(name):
    class ProvenanceApi(FakeWin32Api):
        def GetClipboardFormatNameW(self, format_id, buffer, capacity):
            if format_id == 0xC100:
                buffer.value = name
                return len(name)
            return super().GetClipboardFormatNameW(format_id, buffer, capacity)

    api = ProvenanceApi({CF_UNICODETEXT: b"o\x00\x00\x00", 0xC002: b"html", 0xC100: b"\x00\xffopaque\x00metadata"})
    original = {key: api.current_bytes(key) for key in api.formats}
    with ClipboardTextTransaction("temporary", backend=build_windows_backend(api)) as transaction:
        assert transaction.verify_current_text() == 1
    assert transaction.status == "restored"
    assert {key: api.current_bytes(key) for key in api.formats} == original
    assert not api.created_windows
    assert api.live_hglobals == set(api.formats.values())


def test_windows_unknown_registered_format_still_blocks_without_modifying_clipboard():
    api = FakeWin32Api({CF_UNICODETEXT: b"o\x00\x00\x00", 0xC100: b"unknown"})
    original = {key: api.current_bytes(key) for key in api.formats}
    with pytest.raises(ClipboardTransactionError, match="unsupported_format"):
        with ClipboardTextTransaction("temporary", backend=build_windows_backend(api)):
            pytest.fail("unknown formats must not reach input")
    assert "empty" not in api.events
    assert {key: api.current_bytes(key) for key in api.formats} == original
    assert not api.created_windows


class CloseSequenceApi(FakeWin32Api):
    def OpenClipboard(self, handle):
        result = super().OpenClipboard(handle)
        if result:
            self.sequence_at_open = self.sequence
        return result

    def CloseClipboard(self):
        changed = self.sequence != self.sequence_at_open
        result = super().CloseClipboard()
        if result and changed:
            self.sequence += 3
        return result


def test_windows_sequence_is_committed_after_close_without_losing_original_formats():
    api = CloseSequenceApi({CF_UNICODETEXT: b"o\x00\x00\x00", 0xC002: b"html"})
    original = {key: api.current_bytes(key) for key in api.formats}
    with ClipboardTextTransaction("temporary", backend=build_windows_backend(api)) as transaction:
        assert transaction.verify_current_text() == 1
    assert transaction.status == "restored"
    assert {key: api.current_bytes(key) for key in api.formats} == original
    assert not api.created_windows


@pytest.mark.parametrize("same_owner", [False, True])
def test_windows_external_same_text_copy_during_install_close_is_not_adopted(same_owner):
    class ConcurrentCopyApi(CloseSequenceApi):
        def CloseClipboard(self):
            replace = self.set_calls == 1 and not getattr(self, "copied", False)
            result = super().CloseClipboard()
            if result and replace:
                self.copied = True
                owner = self.owner
                self.external_copy("temporary")
                if same_owner:
                    self.owner = owner
            return result

    api = ConcurrentCopyApi({CF_UNICODETEXT: b"o\x00\x00\x00"})
    with pytest.raises(ClipboardTransactionError):
        with ClipboardTextTransaction("temporary", backend=build_windows_backend(api)):
            pytest.fail("a new clipboard object must not become our transaction")
    assert api.current_bytes(CF_UNICODETEXT).startswith("temporary".encode("utf-16-le"))
    assert api.events.count("empty") == 1
    assert not api.created_windows


def test_windows_bitmap_conflict_releases_clone_exactly_once():
    api = FakeWin32Api({CF_BITMAP: b"bitmap"})
    with pytest.raises(ClipboardTransactionError, match="ownership_conflict"):
        with ClipboardTextTransaction("x", backend=build_windows_backend(api)):
            api.external_copy("new")
    assert len(api.deleted_bitmaps) == len(set(api.deleted_bitmaps))
    assert not api.live_bitmaps
    assert not api.created_windows


def test_windows_open_failure_after_capture_frees_temporary_allocation():
    api = FakeWin32Api({CF_UNICODETEXT: b"o\x00\x00\x00"})
    api.fail_open_calls = {2}
    original = set(api.live_hglobals)
    with pytest.raises(ClipboardTransactionError):
        with ClipboardTextTransaction("x", backend=build_windows_backend(api)):
            pytest.fail("body must not run")
    assert api.live_hglobals == original
    assert "empty" not in api.events
    assert not api.created_windows


def test_windows_enumeration_failure_stops_before_overwrite():
    api = FakeWin32Api({CF_UNICODETEXT: b"o\x00\x00\x00"})
    api.fail_enum = True
    with pytest.raises(ClipboardTransactionError, match="clipboard_capture_failed"):
        with ClipboardTextTransaction("x", backend=build_windows_backend(api)):
            pytest.fail("body must not run")
    assert "empty" not in api.events
    assert not api.created_windows


def test_windows_zero_size_handle_stops_before_overwrite():
    api = FakeWin32Api({CF_DIB: b""})
    with pytest.raises(ClipboardTransactionError, match="clipboard_data_unavailable"):
        with ClipboardTextTransaction("x", backend=build_windows_backend(api)):
            pytest.fail("body must not run")
    assert "empty" not in api.events
    assert not api.created_windows


def test_clipboard_snapshot_repr_excludes_source_data():
    entry = ClipboardEntry(CF_TEXT, b"private-clipboard-content")
    assert "private-clipboard-content" not in repr(entry)
    assert "private-clipboard-content" not in repr(ClipboardSnapshot((entry,)))


def test_windows_partial_install_failure_restores_original_and_cleans_resources():
    api = FakeWin32Api({CF_DIB: b"original-dib"})
    original = api.current_bytes(CF_DIB)
    api.fail_set_calls = {1}
    with pytest.raises(ClipboardTransactionError, match="temporary_write_failed"):
        with ClipboardTextTransaction("x", backend=build_windows_backend(api)):
            pytest.fail("body must not run")
    assert api.current_bytes(CF_DIB) == original
    assert api.live_hglobals == set(api.formats.values())
    assert not api.created_windows


def test_windows_snapshot_release_failure_is_not_silently_restored():
    api = FakeWin32Api({CF_BITMAP: b"bitmap"})
    with pytest.raises(ClipboardTransactionError):
        with ClipboardTextTransaction("x", restore=False, backend=build_windows_backend(api)):
            api.fail_delete = True


def test_windows_owner_release_failure_is_not_silently_restored():
    api = FakeWin32Api({CF_DIB: b"dib"})
    with pytest.raises(ClipboardTransactionError):
        with ClipboardTextTransaction("x", backend=build_windows_backend(api)):
            api.fail_destroy = True


@pytest.mark.parametrize("failed_close", [1, 2])
def test_windows_close_failure_stops_body_and_preserves_original(failed_close):
    api = FakeWin32Api({CF_DIB: b"original-dib"})
    original = api.current_bytes(CF_DIB)
    api.fail_close_calls = {failed_close}
    with pytest.raises(ClipboardTransactionError):
        with ClipboardTextTransaction("x", backend=build_windows_backend(api)):
            pytest.fail("body must not run after failed clipboard close")
    assert api.current_bytes(CF_DIB) == original
    assert not api.opened
    assert not api.created_windows
    assert api.live_hglobals == set(api.formats.values())


@pytest.mark.parametrize("formats", [{}, {
    CF_UNICODETEXT: b"o\x00\x00\x00", CF_TEXT: b"old\x00", 7: b"oem\x00",
    CF_LOCALE: b"\x09\x04\x00\x00", CF_DIB: b"dib", 17: b"dibv5",
    CF_HDROP: b"file-drop", 0xC001: b"{\\rtf1 old}", 0xC002: b"html",
    0xC003: b"png-bytes", CF_BITMAP: b"bitmap-bytes",
}])
def test_windows_multiformat_or_empty_snapshot_restores_all_owned_data(formats):
    api = FakeWin32Api(formats)
    original = {key: api.current_bytes(key) for key in api.formats}
    with ClipboardTextTransaction("next", backend=build_windows_backend(api)) as transaction:
        transaction.verify_current_text()
    assert transaction.status == "restored"
    assert {key: api.current_bytes(key) for key in api.formats} == original
    assert not api.created_windows
    assert api.live_hglobals | api.live_bitmaps == set(api.formats.values())


def test_windows_capture_error_is_not_replaced_by_secondary_close_error():
    api = FakeWin32Api({14: b"uncopyable-format"})
    api.fail_close_calls = {1}
    with pytest.raises(ClipboardTransactionError) as captured:
        with ClipboardTextTransaction("next", backend=build_windows_backend(api)):
            pytest.fail("body must not run")
    assert captured.value.code == "unsupported_format"
    assert "clipboard_close_failed" in " ".join(captured.value.__notes__)
    assert not api.created_windows
    assert not api.opened


@pytest.mark.parametrize("failed_query", [3, 4])
def test_windows_missing_sequence_after_mutation_restores_before_unlock(failed_query):
    api = FakeWin32Api({CF_BITMAP: b"bitmap", CF_DIB: b"original-dib"})
    original = {key: api.current_bytes(key) for key in api.formats}
    calls = 0

    def sequence():
        nonlocal calls
        calls += 1
        return 0 if calls == failed_query else api.sequence

    api.GetClipboardSequenceNumber = sequence
    with pytest.raises(ClipboardTransactionError) as captured:
        with ClipboardTextTransaction("private-value", backend=build_windows_backend(api)):
            pytest.fail("body must not run")
    assert captured.value.code == "temporary_write_failed"
    assert captured.value.restore_status == "restored"
    assert {key: api.current_bytes(key) for key in api.formats} == original
    assert api.open_calls == 2
    assert not api.created_windows and not api.opened
    assert api.live_hglobals | api.live_bitmaps == set(api.formats.values())
    assert len(api.deleted_bitmaps) == len(set(api.deleted_bitmaps))
    assert "private-value" not in str(captured.value) + repr(captured.value.__notes__)


def test_windows_body_failure_retains_conflict_and_owner_cleanup_failure():
    api = FakeWin32Api({CF_DIB: b"original"})
    primary = RuntimeError("input failed")
    with pytest.raises(RuntimeError) as captured:
        with ClipboardTextTransaction("private-value", backend=build_windows_backend(api)) as transaction:
            api.external_copy("newer")
            api.fail_destroy = True
            raise primary
    assert captured.value is primary
    assert transaction.status == "restore_failed"
    assert "ownership_conflict" in transaction.cleanup_errors
    assert "owner_release_failed" in transaction.cleanup_errors
    notes = " ".join(primary.__notes__)
    assert "ownership_conflict" in notes and "owner_release_failed" in notes
    assert api.current_bytes(CF_UNICODETEXT).startswith(b"n\x00e\x00w\x00e\x00r\x00\x00\x00")


def test_windows_enter_failure_retains_cleanup_failure_without_raw_content():
    api = FakeWin32Api({14: b"private-original"})
    api.fail_destroy = True
    with pytest.raises(ClipboardTransactionError) as captured:
        with ClipboardTextTransaction("private-value", backend=build_windows_backend(api)):
            pytest.fail("body must not run")
    assert captured.value.code == "unsupported_format"
    assert captured.value.restore_status == "restore_failed"
    notes = " ".join(getattr(captured.value, "__notes__", ()))
    assert "owner_release_failed" in notes
    assert "private-original" not in str(captured.value) + notes
    assert "private-value" not in str(captured.value) + notes


@pytest.mark.parametrize("failed_set,failed_close,want_code", [
    (2, None, "restore_failed"),
    (3, None, "restore_failed"),
    (None, 2, "clipboard_close_failed"),
])
def test_windows_locked_rollback_failure_is_explicit_and_never_reuses_handles(failed_set, failed_close, want_code):
    api = FakeWin32Api({CF_BITMAP: b"bitmap", CF_DIB: b"original"})
    api.fail_set_calls = {failed_set}
    api.fail_close_calls = {failed_close}
    calls = 0

    def sequence():
        nonlocal calls
        calls += 1
        return 0 if calls == 4 else api.sequence

    api.GetClipboardSequenceNumber = sequence
    with pytest.raises(ClipboardTransactionError) as captured:
        with ClipboardTextTransaction("private-value", backend=build_windows_backend(api)):
            pytest.fail("body must not run")
    assert captured.value.code == "temporary_write_failed"
    assert captured.value.restore_status == "restore_failed"
    assert want_code in captured.value.cleanup_errors
    assert api.open_calls == 2
    assert api.live_hglobals | api.live_bitmaps == set(api.formats.values())
    assert not api.created_windows and not api.opened
    assert len(api.deleted_bitmaps) == len(set(api.deleted_bitmaps))


def test_windows_conflict_survives_failed_close_during_restore():
    api = FakeWin32Api({CF_DIB: b"original"})
    primary = RuntimeError("input failed")
    with pytest.raises(RuntimeError) as captured:
        with ClipboardTextTransaction("next", backend=build_windows_backend(api)) as transaction:
            api.fail_close_calls = {api.close_calls + 1}
            api.external_copy("newer")
            raise primary
    assert captured.value is primary
    assert "ownership_conflict" in transaction.cleanup_errors
    assert "clipboard_close_failed" in transaction.cleanup_errors
    assert api.current_bytes(CF_UNICODETEXT).startswith(b"n\x00e\x00w\x00e\x00r\x00\x00\x00")
    assert not api.created_windows and not api.opened


def test_windows_capture_failure_survives_failed_bitmap_release():
    api = FakeWin32Api({CF_BITMAP: b"bitmap", 14: b"unsupported"})
    api.fail_delete = True
    with pytest.raises(ClipboardTransactionError) as captured:
        with ClipboardTextTransaction("next", backend=build_windows_backend(api)):
            pytest.fail("body must not run")
    assert captured.value.code == "unsupported_format"
    assert "snapshot_release_failed" in captured.value.cleanup_errors
    assert "empty" not in api.events
    assert not api.created_windows and not api.opened
