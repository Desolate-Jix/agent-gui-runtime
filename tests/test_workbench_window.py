"""工作台外框的关闭保护、键盘和边角契约。"""
from types import SimpleNamespace
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QToolBar
from tests.test_workflow_steps_ui import qt_app
from app.learning_memory.workbench_window import WorkbenchWindow


def test_shell_preserves_mainwindow_content_and_close_guard(qt_app):
    class Guarded(WorkbenchWindow):
        def closeEvent(self, event):
            event.ignore()
    window = Guarded()
    window.setCentralWidget(QLabel('Content'))
    window.addToolBar(QToolBar('Toolbar'))
    window.chrome_menu.addMenu('Menu')
    window.resize(600, 400)
    window.show()
    qt_app.processEvents()
    try:
        assert window.contentsMargins().left() == 6
        assert window.centralWidget().isVisible()
        assert window.chrome_menu.actions()
        for button in (window.chrome_minimize_button, window.chrome_maximize_button, window.chrome_close_button):
            assert button.accessibleName()
            assert button.toolTip()
            assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus
        window.chrome_minimize_button.setFocus()
        QTest.keyClick(window.chrome_minimize_button, Qt.Key.Key_Tab)
        assert window.chrome_maximize_button.hasFocus()
        window.chrome_minimize_button.setFocus()
        QTest.keyClick(window.chrome_minimize_button, Qt.Key.Key_Tab)
        assert window.chrome_maximize_button.hasFocus()
        QTest.keyClick(window.chrome_maximize_button, Qt.Key.Key_Tab)
        assert window.chrome_close_button.hasFocus()
        window.chrome_close_button.setFocus()
        QTest.keyClick(window.chrome_close_button, Qt.Key.Key_Space)
        assert window.isVisible()
        window.chrome_maximize_button.click()
        qt_app.processEvents()
        assert window.isMaximized()
        assert window.contentsMargins().left() == 0
        assert window.chrome_maximize_button.accessibleName() == '\u8fd8\u539f'
        window.chrome_maximize_button.click()
        qt_app.processEvents()
        assert not window.isMaximized()
        assert window.contentsMargins().left() == 6
        window.chrome_minimize_button.click()
        qt_app.processEvents()
        assert window.isMinimized()
    finally:
        window.hide()
        window.deleteLater()
        qt_app.processEvents()


def test_resize_edges_are_scoped_and_disabled_when_maximized(qt_app):
    window = WorkbenchWindow()
    window.resize(600, 400)
    assert window.resize_edges(QPoint(0, 0)) == (Qt.Edge.TopEdge | Qt.Edge.LeftEdge)
    assert window.resize_edges(QPoint(599, 399)) == (Qt.Edge.BottomEdge | Qt.Edge.RightEdge)
    assert window.resize_edges(QPoint(300, 200)) == Qt.Edge(0)
    window.showMaximized()
    qt_app.processEvents()
    assert window.resize_edges(QPoint(0, 0)) == Qt.Edge(0)
    window.close()
    window.deleteLater()
    qt_app.processEvents()


def test_title_and_edges_delegate_only_to_own_window_handle(qt_app, monkeypatch):
    window = WorkbenchWindow()
    window.resize(600, 400)
    window.show()
    qt_app.processEvents()
    calls = []
    handle = SimpleNamespace(
        startSystemMove=lambda: calls.append(('move',)) or True,
        startSystemResize=lambda edges: calls.append(('resize', edges)) or True)
    monkeypatch.setattr(window, 'windowHandle', lambda: handle)
    try:
        QTest.mouseClick(window.chrome_header, Qt.MouseButton.LeftButton, pos=QPoint(300, 20))
        assert calls == [('move',)]
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=QPoint(2, 200))
        assert calls[-1] == ('resize', Qt.Edge.LeftEdge)
        QTest.mouseDClick(window.chrome_header, Qt.MouseButton.LeftButton, pos=QPoint(300, 20))
        qt_app.processEvents()
        assert window.isMaximized()
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()
