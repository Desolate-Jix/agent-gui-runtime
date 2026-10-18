import os
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6
from PySide6.QtCore import QByteArray, QBuffer, QCoreApplication, QEvent, QIODevice, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.desktop_review.interface_pane import InterfaceReviewPane


def _app():
    return QApplication.instance() or QApplication([])


def _png_bytes():
    image = QImage(10, 10, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFF)
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(encoded)


class _LegacyUnownedPane(InterfaceReviewPane):
    """隔离旧的无所有权调度方式，作为实际异常的负对照。"""

    def _schedule_fit_image(self):
        QTimer.singleShot(0, self.canvas.fit_image)


def test_legacy_unowned_fit_reproduces_deleted_canvas_runtime_error():
    app = _app()
    pane = _LegacyUnownedPane(object())
    pane.canvas.set_image(_png_bytes(), [], ("legacy",))
    errors = []
    previous_hook = sys.excepthook
    sys.excepthook = lambda kind, value, traceback: errors.append(value)
    try:
        pane.show()
        canvas = pane.canvas
        pane.close()
        pane.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(canvas)
        app.processEvents()
    finally:
        sys.excepthook = previous_hook
    assert any(isinstance(error, RuntimeError) and "already deleted" in str(error) for error in errors)


def test_deferred_fit_does_not_outlive_editor_disposal():
    app = _app()
    pane = InterfaceReviewPane(object())
    pane.canvas.set_image(_png_bytes(), [], ("owned",))
    pane.show()
    timer = pane._fit_timer
    assert timer.parent() is pane.canvas
    assert timer.isActive()

    errors = []
    previous_hook = sys.excepthook
    sys.excepthook = lambda kind, value, traceback: errors.append(value)
    try:
        canvas = pane.canvas
        pane.close()
        pane.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        assert not shiboken6.isValid(timer)
        assert not shiboken6.isValid(canvas)
    finally:
        sys.excepthook = previous_hook
    assert errors == []


def test_deferred_fit_timer_runs_for_live_canvas():
    app = _app()
    pane = InterfaceReviewPane(object())
    pane.canvas.set_image(_png_bytes(), [], ("test",))
    calls = []
    pane.canvas.zoomChanged.connect(calls.append)
    pane._schedule_fit_image()
    app.processEvents()
    assert not pane._fit_timer.isActive()
    assert calls
    pane.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
