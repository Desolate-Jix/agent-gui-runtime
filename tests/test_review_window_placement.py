"""首次窗口布局使用逻辑工作区，不覆盖任务栏或负坐标副屏。"""
from types import SimpleNamespace
import pytest

@pytest.mark.parametrize("area,size,position", [
    ((0, 0, 1930, 832), (1380, 900), (80, 0)),
    ((-1920, 40, 1280, 720), (1120, 760), (-1800, 0)),
    ((0, 0, 1920, 1040), (800, 600), (100, 120)),
])
def test_initial_window_fits_available_logical_screen(monkeypatch, area, size, position):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication, QDialog
    import app.desktop_review.window_placement as placement
    app = QApplication.instance() or QApplication([])
    window = QDialog()
    window.resize(*size)
    window.move(*position)
    window.show()
    app.processEvents()
    available = QRect(*area)
    monkeypatch.setattr(window, "screen", lambda: SimpleNamespace(availableGeometry=lambda: available))
    old_size = window.size()
    try:
        placement.fit_initial_window(window)
        app.processEvents()
        assert available.contains(window.frameGeometry())
        assert window.width() <= old_size.width()
        assert window.height() <= old_size.height()
        if size == (800, 600):
            assert window.size() == old_size
    finally:
        window.close()
