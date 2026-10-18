from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QPushButton, QMessageBox
import pytest

from app.desktop_review.window import ReviewMainWindow, ensure_application
from test_formal_graph_source_ownership import _facade


def test_native_window_exposes_actual_size_fit_and_live_percentage(tmp_path, monkeypatch):
    application = ensure_application()
    facade, store, _, _ = _facade(tmp_path)
    window = ReviewMainWindow(facade)
    try:
        window.show()
        window.load_batch("graph-source-ownership-task", "graph-source-ownership-batch")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            application.processEvents()
            if window.workspace is not None and not window._jobs:
                break
            QTest.qWait(10)
        assert window.workspace is not None, "\n".join(label.text() for label in window.findChildren(QLabel))
        window._show_interface("interface-a")
        actual = window.findChild(QPushButton, "canvasActualSizeButton")
        fit = window.findChild(QPushButton, "canvasFitButton")
        label = window.findChild(QLabel, "canvasZoomLabel")
        assert actual is not None and fit is not None and label is not None
        QTest.mouseClick(actual, Qt.MouseButton.LeftButton)
        assert window.canvas.zoom_percent() == pytest.approx(100)
        assert label.text() == "100%"
        QTest.mouseClick(fit, Qt.MouseButton.LeftButton)
        assert label.text() == f"{window.canvas.zoom_percent():.0f}%"
        assert window._dirty is False
        window._select_region("region-a")
        window.canvas.set_zoom_percent(400)
        canvas = window.canvas
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         canvas.mapFromScene(QPointF(22, 15)))
        QTest.mouseMove(canvas.viewport(), canvas.mapFromScene(QPointF(30, 20)), 10)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           canvas.mapFromScene(QPointF(30, 20)))
        expected = canvas._regions["region-a"].bbox()
        assert expected == pytest.approx([2, 3, 28, 17], abs=1)
        assert window._dirty is True
        assert [spin.value() for spin in window.bbox_spins] == pytest.approx(expected, abs=.01)
        window.save_current()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and (window._jobs or window._dirty):
            application.processEvents()
            time.sleep(.01)
            QTest.qWait(10)
        assert window._dirty is False and not window._jobs, (window._operation, window.status.currentMessage(), window._pending_invalid)
        saved = facade.load_batch("graph-source-ownership-task", "graph-source-ownership-batch")
        assert saved["batch"]["interfaces"][0]["regions"][0]["bbox"] == expected
    finally:
        deadline = time.monotonic() + 8
        while window._jobs and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(.01)
            QTest.qWait(10)
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Discard)
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
        window.close()
        application.processEvents()
        facade.close()
        store.close()
