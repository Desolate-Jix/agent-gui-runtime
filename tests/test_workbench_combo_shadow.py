"""迟接入工作台的 combo 必须在私有 Popup 原生创建前准备阴影。"""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox
from app.learning_memory.workbench_window import WorkbenchWindow
from app.learning_memory import workbench_popup_ownership as ownership


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def test_unparented_polished_combo_prepared_on_first_main_show(qt_app):
    main = WorkbenchWindow()
    combo = QComboBox()
    combo.addItems(['pending', 'reviewed'])
    combo.ensurePolished()
    popup = combo.view().window()
    assert popup.windowHandle() is None
    assert not popup.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
    combo.setParent(main)
    try:
        main.show()
        qt_app.processEvents()
        assert popup.windowHandle() is None
        assert not popup.isVisible()
        assert popup.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
    finally:
        main.close()
        main.deleteLater()
        qt_app.processEvents()


@pytest.mark.parametrize('parent_kind', ['none', 'foreign'])
def test_unproven_combo_does_not_even_create_or_read_view(qt_app, monkeypatch, parent_kind):
    main, foreign = WorkbenchWindow(), WorkbenchWindow()
    combo = QComboBox(foreign if parent_kind == 'foreign' else None)
    calls = []
    monkeypatch.setattr(combo, 'view', lambda: calls.append('view'))
    try:
        assert hasattr(ownership, 'prepare_owned_combo_popup')
        assert not ownership.prepare_owned_combo_popup(main, combo)
        assert calls == []
    finally:
        combo.deleteLater()
        main.deleteLater()
        foreign.deleteLater()
        qt_app.processEvents()


def test_owned_combo_helper_prepares_without_creating_native_handle(qt_app):
    main = WorkbenchWindow()
    combo = QComboBox(main)
    try:
        assert hasattr(ownership, 'prepare_owned_combo_popup')
        assert ownership.prepare_owned_combo_popup(main, combo)
        popup = combo.view().window()
        assert ownership._proven_popup(main, popup)
        assert popup.windowHandle() is None
        assert popup.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
    finally:
        main.deleteLater()
        qt_app.processEvents()


def test_existing_popup_handle_is_not_hidden_recreated_or_reflagged(qt_app):
    main = WorkbenchWindow()
    combo = QComboBox()
    combo.ensurePolished()
    popup = combo.view().window()
    popup.winId()
    old_handle, old_flags = popup.windowHandle(), popup.windowFlags()
    combo.setParent(main)
    try:
        assert hasattr(ownership, 'prepare_owned_combo_popup')
        assert not ownership.prepare_owned_combo_popup(main, combo)
        assert popup.windowHandle() is old_handle
        assert popup.windowFlags() == old_flags
        assert not popup.isVisible()
    finally:
        main.deleteLater()
        qt_app.processEvents()
