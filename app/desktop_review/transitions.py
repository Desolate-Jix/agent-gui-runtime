"""不会延迟审核状态或截图替换的轻量过渡。"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QEasingCurve, QVariantAnimation
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget


class SubtleFadeTransition(QVariantAnimation):
    """只渐变文字颜色，不创建 Qt 图形合成效果；关闭时立即复原。"""

    def __init__(self, widget: QWidget, duration_ms: int = 140) -> None:
        super().__init__(widget)
        self._enabled = True
        self._widget = widget
        self._original_style = widget.styleSheet()
        widget.installEventFilter(self)
        self.setDuration(duration_ms)
        self.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.valueChanged.connect(self._apply_color)
        self.finished.connect(self._restore_style)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self._finish_immediately()

    def _finish_immediately(self) -> None:
        self.stop()
        self._restore_style()

    def _restore_style(self) -> None:
        self._widget.setStyleSheet(self._original_style)

    def _apply_color(self, color: QColor) -> None:
        self._widget.setStyleSheet(self._original_style + f"\ncolor: {color.name()};")

    def eventFilter(self, watched, event) -> bool:
        # 隐藏或销毁前停止文字更新，保留下一次显示时的动画偏好。
        if event.type() in (QEvent.Type.Hide, QEvent.Type.Close, QEvent.Type.DeferredDelete):
            self._finish_immediately()
        return super().eventFilter(watched, event)

    def play(self) -> None:
        self._finish_immediately()
        if not self._enabled or not self._widget.isVisible():
            return
        end = self._widget.palette().color(QPalette.ColorRole.WindowText)
        start = QColor(*(round(value * 0.72 + 255 * 0.28) for value in (end.red(), end.green(), end.blue())))
        self.setStartValue(start)
        self.setEndValue(end)
        self.start()
