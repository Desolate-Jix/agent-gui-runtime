"""即时切页的轻量导航指示动画。"""
from __future__ import annotations
from app.learning_memory.workbench_i18n import ui, tr, bind_text, initialize_i18n, language_manager

import os

from PySide6.QtCore import QEasingCurve, QRectF, QVariantAnimation
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QTabBar


def system_motion_enabled() -> bool:
    if os.environ.get('AGENT_REVIEW_REDUCED_MOTION', '').lower() in {'1', 'true', 'yes'}:
        return False
    if os.name == 'nt':
        import ctypes
        enabled = ctypes.c_int()
        # 只读取 Windows 客户区动画偏好，不修改系统配置。
        if not ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            return False
        return bool(enabled.value)
    return True


class WorkbenchTabBar(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._motion_enabled = system_motion_enabled()
        self._indicator = QRectF()
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(160)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._paint_indicator)
        self.currentChanged.connect(self._selection_changed)
        self.setExpanding(False)
        self.setDrawBase(False)
        ui(self.setAccessibleName, tr('工作台页面导航'))

    @property
    def is_animating(self):
        return self._animation.state() == QVariantAnimation.State.Running

    @property
    def indicator_rect(self):
        return QRectF(self._indicator)

    def set_motion_enabled(self, enabled):
        self._motion_enabled = bool(enabled)
        if not self._motion_enabled:
            self._settle()

    def _destination(self):
        if self.currentIndex() < 0:
            return QRectF()
        tab = QRectF(self.tabRect(self.currentIndex()))
        return QRectF(tab.left() + 16, tab.bottom() - 4, max(0, tab.width() - 32), 3)

    def _paint_indicator(self, value):
        self._indicator = QRectF(value)
        self.update()

    def _settle(self):
        self._animation.stop()
        self._paint_indicator(self._destination())

    def _selection_changed(self, _index):
        self._animation.stop()
        end = self._destination()
        if not self._motion_enabled or not self.isVisible() or self._indicator.isEmpty():
            self._paint_indicator(end)
            return
        # 页面已经由 QTabWidget 切换，动画不接管页面、焦点或输入。
        self._animation.setStartValue(QRectF(self._indicator))
        self._animation.setEndValue(end)
        self._animation.start()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(0, 0, 0, 0))
        painter.setBrush(QColor('#2563eb'))
        painter.drawRoundedRect(self._indicator, 1.5, 1.5)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._settle()

    def showEvent(self, event):
        super().showEvent(event)
        self._settle()

    def hideEvent(self, event):
        self._settle()
        super().hideEvent(event)
