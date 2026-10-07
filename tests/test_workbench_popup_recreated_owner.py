"""离屏 QWindow 事件与模拟 HWND 验证重建归属，不调用 Win32。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPlatformSurfaceEvent
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QComboBox, QWidget
from app.learning_memory import workbench_popup_ownership as ownership


@pytest.mark.parametrize('notification', ['surface', 'show', 'visible'])
@pytest.mark.parametrize('bad_readback', [False, True])
def test_recreated_native_handle_rebinds_with_unchanged_transient_parent(monkeypatch, notification, bad_readback, caplog):
    app = QApplication.instance() or QApplication([])
    main = QWidget()
    combo = QComboBox(main)
    popup = QWidget(combo, Qt.WindowType.Popup)
    main.winId()
    popup.winId()
    handle = popup.windowHandle()
    hwnd = [101]
    writes = []
    owners = {10: 0, 101: 0, 202: 0}
    def set_owner(window, owner):
        writes.append((owner, window))
        if not (bad_readback and window == 202):
            owners[window] = owner
    backend = SimpleNamespace(valid=lambda window: window in owners, identity=lambda window: (17, 29),
        style=lambda window: 0, owner=lambda window: owners[window],
        root_owner=lambda window: owners[window] or window, set_owner=set_owner)
    bind_native = ownership.bind_native_popup
    monkeypatch.setattr(main, 'winId', lambda: 10)
    monkeypatch.setattr(main.windowHandle(), 'winId', lambda: 10)
    monkeypatch.setattr(popup, 'winId', lambda: 101)
    monkeypatch.setattr(handle, 'winId', lambda: hwnd[0])
    monkeypatch.setattr(ownership.QGuiApplication, 'platformName', lambda: 'windows')
    monkeypatch.setattr(ownership, 'bind_native_popup',
        lambda owner, window: bind_native(owner, window, backend=backend))
    try:
        assert ownership.associate_owned_popup(main, popup)
        assert handle.transientParent() is main.windowHandle()
        writes.clear()
        hook = handle._workbench_lifecycle_hook
        assert ownership.associate_owned_popup(main, popup)
        assert handle._workbench_lifecycle_hook is hook
        writes.clear()
        handle.visibleChanged.emit(False)
        assert writes == []
        hwnd[0] = 202
        if notification == 'surface':
            hook = getattr(handle, '_workbench_lifecycle_hook', None)
            assert hook is not None, 'native surface recreation has no ownership hook'
            hook.eventFilter(handle, SimpleNamespace(type=lambda: QEvent.Type.PlatformSurface,
                surfaceEventType=lambda: QPlatformSurfaceEvent.SurfaceEventType.SurfaceCreated))
        elif notification == 'show':
            app.sendEvent(handle, QEvent(QEvent.Type.Show))
        else:
            handle.visibleChanged.emit(True)
        assert writes and all(pair == (10, 202) for pair in writes)
        assert owners[202] == (0 if bad_readback else 10)
        if bad_readback:
            assert 'native owner readback mismatch' in caplog.text
        assert handle.transientParent() is main.windowHandle()
        writes.clear()
        popup.setParent(None, Qt.WindowType.Popup)
        handle.visibleChanged.emit(True)
        assert writes == []
    finally:
        popup.deleteLater()
        main.deleteLater()
        app.processEvents()


def test_surface_destruction_callbacks_do_not_read_or_recreate_native_id(monkeypatch):
    app = QApplication.instance() or QApplication([])
    main = QWidget()
    popup = QWidget(main, Qt.WindowType.Popup)
    main.winId()
    popup.winId()
    handle = popup.windowHandle()
    assert ownership.associate_owned_popup(main, popup)
    hook = handle._workbench_lifecycle_hook
    hook.eventFilter(handle, SimpleNamespace(type=lambda: QEvent.Type.PlatformSurface,
        surfaceEventType=lambda: QPlatformSurfaceEvent.SurfaceEventType.SurfaceAboutToBeDestroyed))
    reads = []
    monkeypatch.setattr(popup, 'winId', lambda: reads.append('widget') or 101)
    monkeypatch.setattr(handle, 'winId', lambda: reads.append('qwindow') or 202)
    monkeypatch.setattr(ownership.QGuiApplication, 'platformName', lambda: 'windows')
    monkeypatch.setattr(ownership, 'bind_native_popup', lambda *args: reads.append('bind') or True)
    try:
        hook.recheck()
        assert not ownership.associate_owned_popup(main, popup)
        assert reads == []
    finally:
        popup.deleteLater()
        main.deleteLater()
        app.processEvents()
