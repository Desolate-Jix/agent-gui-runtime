import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QWidget

from app.learning_memory.workbench_popup_ownership import associate_owned_popup
from app.learning_memory.workbench_window import WorkbenchWindow
from app.learning_memory import workbench_popup_ownership as ownership


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def test_only_proven_widget_ancestry_can_bind_popup(qt_app):
    first, second = WorkbenchWindow(), WorkbenchWindow()
    first.show()
    second.show()
    combo = QComboBox(first)
    popup = QWidget(combo, Qt.WindowType.Popup)
    foreign = QWidget(second, Qt.WindowType.Popup)
    dialog = QDialog(first)
    try:
        popup.winId()
        foreign.winId()
        dialog.winId()
        popup.windowHandle().setTransientParent(None)
        foreign.windowHandle().setTransientParent(None)
        foreign_parent = foreign.windowHandle().transientParent()
        assert not associate_owned_popup(first, foreign)
        assert foreign.windowHandle().transientParent() is foreign_parent
        assert not associate_owned_popup(first, dialog)
        assert associate_owned_popup(first, popup)
        assert popup.windowHandle().transientParent() is first.windowHandle()
        assert associate_owned_popup(second, foreign)
        assert foreign.windowHandle().transientParent() is second.windowHandle()
    finally:
        for widget in (popup, foreign, dialog, first, second):
            widget.close()
            widget.deleteLater()
        qt_app.processEvents()


def test_real_combo_show_and_reopen_bind_to_owner(qt_app):
    window = WorkbenchWindow()
    combo = QComboBox(window)
    combo.addItems(['one', 'two'])
    window.show()
    try:
        for _ in range(2):
            combo.showPopup()
            qt_app.processEvents()
            popup = combo.view().window()
            assert popup.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
            assert popup.windowHandle().transientParent() is window.windowHandle()
            combo.hidePopup()
            qt_app.processEvents()
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_menu_and_language_prepared_before_first_native_handle(qt_app):
    window = WorkbenchWindow()
    menu = window.chrome_menu.addMenu('settings')
    language = menu.addMenu('language')
    foreign_owner = WorkbenchWindow()
    foreign = foreign_owner.chrome_menu.addMenu('foreign')
    try:
        assert hasattr(ownership, 'prepare_owned_popup'), 'Popup shadow must be disabled before native creation'
        assert menu.windowHandle() is None
        assert ownership.prepare_owned_popup(window, menu)
        assert ownership.prepare_owned_popup(window, language)
        assert not ownership.prepare_owned_popup(window, foreign)
        for popup in (menu, language):
            assert popup.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
            for _ in range(2):
                popup.show()
                qt_app.processEvents()
                assert popup.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
                assert popup.windowHandle().transientParent() is window.windowHandle()
                popup.hide()
    finally:
        window.close()
        foreign_owner.close()


def test_late_shadow_preparation_never_changes_flags_or_visibility(qt_app):
    window = WorkbenchWindow()
    popup = QWidget(window, Qt.WindowType.Popup)
    popup.winId()
    flags = popup.windowFlags()
    assert hasattr(ownership, 'prepare_owned_popup')
    assert not ownership.prepare_owned_popup(window, popup)
    assert popup.windowFlags() == flags
    assert not popup.isVisible()


def test_native_rejection_precedes_qt_transient_write(qt_app, monkeypatch):
    from types import SimpleNamespace
    owner = QWidget()
    popup = QWidget(owner, Qt.WindowType.Popup)
    owner.winId()
    popup.winId()
    popup.windowHandle().setTransientParent(None)
    calls = []
    monkeypatch.setattr(ownership, 'QGuiApplication', SimpleNamespace(platformName=lambda: 'windows'))
    monkeypatch.setattr(ownership, 'bind_native_popup', lambda *args: calls.append(args) or False)
    assert not associate_owned_popup(owner, popup)
    assert popup.windowHandle().transientParent() is None
    assert len(calls) == 1
