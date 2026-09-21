from __future__ import annotations

import pytest

from app.core.clipboard_transaction import (
    CF_BITMAP, CF_DIB, CF_DIBV5, CF_UNICODETEXT,
    ClipboardTextTransaction, ClipboardTransactionError,
)
from test_clipboard_transaction import FakeWin32Api, build_windows_backend


class UncopyableBitmapApi(FakeWin32Api):
    def CopyImage(self, handle, *args):
        self.last_error = 6
        return 0


@pytest.mark.parametrize('dib_format', [CF_DIB, CF_DIBV5])
def test_uncopyable_bitmap_preserves_opaque_dib_and_all_other_formats(dib_format):
    # 位图句柄失效不应阻止可无损保存的同一图片数据和文本恢复。
    original_dib = b'\x28\x00\x00\x00' + bytes(range(80))
    api = UncopyableBitmapApi({CF_BITMAP: b'bitmap', dib_format: original_dib,
                              CF_UNICODETEXT: b'o\x00\x00\x00'})
    original_dib = api.current_bytes(dib_format)
    original_text = api.current_bytes(CF_UNICODETEXT)
    with ClipboardTextTransaction('next', backend=build_windows_backend(api)) as transaction:
        assert transaction.verify_current_text() == 1
    assert transaction.status == 'restored'
    assert api.current_bytes(dib_format) == original_dib
    assert api.current_bytes(CF_UNICODETEXT) == original_text
    assert transaction.bitmap_preservation == {
        'mode': 'dib_system_synthesis', 'source_formats': [dib_format],
        'copy_error': {'code': 'bitmap_copy_failed', 'win32_function': 'CopyImage', 'winerror': 6},
    }
    assert not api.created_windows and not api.live_bitmaps
    assert api.live_hglobals == set(api.formats.values())


def test_uncopyable_bitmap_without_dib_has_native_error_and_no_clipboard_write():
    api = UncopyableBitmapApi({CF_BITMAP: b'bitmap'})
    with pytest.raises(ClipboardTransactionError) as caught:
        with ClipboardTextTransaction('next', backend=build_windows_backend(api)):
            pytest.fail('input must not start')
    assert caught.value.code == 'bitmap_copy_failed'
    assert caught.value.native_error == {'win32_function': 'CopyImage', 'winerror': 6}
    assert 'empty' not in api.events
    assert api.current_bytes(CF_BITMAP) == b'bitmap'
    assert not api.created_windows


def test_uncopyable_bitmap_does_not_allow_unknown_format_to_be_lost():
    api = UncopyableBitmapApi({CF_BITMAP: b'bitmap', CF_DIB: b'dib', 0xC100: b'private'})
    original = api.current_bytes(0xC100)
    with pytest.raises(ClipboardTransactionError, match='unsupported_format'):
        with ClipboardTextTransaction('next', backend=build_windows_backend(api)):
            pytest.fail('input must not start')
    assert 'empty' not in api.events
    assert api.current_bytes(0xC100) == original


def test_uncopyable_bitmap_with_unreadable_dib_never_installs_text():
    class MissingDibApi(UncopyableBitmapApi):
        def GetClipboardData(self, format_id):
            return 0 if format_id == CF_DIB else super().GetClipboardData(format_id)
    api = MissingDibApi({CF_BITMAP: b'bitmap', CF_DIB: b'dib'})
    with pytest.raises(ClipboardTransactionError, match='clipboard_data_unavailable'):
        with ClipboardTextTransaction('next', backend=build_windows_backend(api)):
            pytest.fail('input must not start')
    assert 'empty' not in api.events


def test_uncopyable_bitmap_recovery_keeps_external_clipboard_changes():
    api = UncopyableBitmapApi({CF_BITMAP: b'bitmap', CF_DIB: b'dib'})
    with pytest.raises(ClipboardTransactionError, match='ownership_conflict'):
        with ClipboardTextTransaction('next', backend=build_windows_backend(api)):
            api.external_copy('user-new')
    assert api.current_bytes(CF_UNICODETEXT).startswith('user-new\x00'.encode('utf-16-le'))
    assert CF_DIB not in api.formats
