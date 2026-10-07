"""工作台独立外框，保留 Qt 系统移动、缩放和关闭保护。"""
from app.learning_memory.workbench_i18n import ui, tr, bind_text, initialize_i18n, language_manager
from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QMainWindow, QMenuBar, QToolButton, QWidget


def _window_icon(kind):
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#525252'), 1.4))
    if kind == 'minimize':
        painter.drawLine(5, 13, 15, 13)
    elif kind == 'close':
        painter.drawLine(5, 5, 15, 15)
        painter.drawLine(15, 5, 5, 15)
    elif kind == 'restore':
        painter.drawRect(5, 8, 8, 8)
        painter.drawLine(8, 5, 16, 5)
        painter.drawLine(16, 5, 16, 13)
    else:
        painter.drawRect(5, 5, 10, 10)
    painter.end()
    return QIcon(pixmap)


class _ChromeHeader(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setObjectName('workbenchChrome')
        self.setMinimumHeight(44)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 4, 4)
        layout.setSpacing(8)
        self.brand = QLabel('Agent Review', self)
        self.brand.setObjectName('workbenchChromeBrand')
        self.brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.brand)
        self.subtitle = ui(QLabel, tr('学习工作台'), self)
        self.subtitle.setProperty('role', 'muted')
        self.subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.subtitle)
        window.chrome_menu = QMenuBar(self)
        window.chrome_menu.setNativeMenuBar(False)
        layout.addWidget(window.chrome_menu)
        layout.addStretch()
        for kind, text, slot in (
            ('minimize', '最小化', window.showMinimized),
            ('maximize', '最大化', window.toggle_maximized),
            ('close', '关闭', window.close),
        ):
            button = QToolButton(self)
            button.setObjectName('chrome' + kind.title())
            button.setIcon(_window_icon(kind))
            button.setFixedSize(36, 32)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            bind_text(button, 'setAccessibleName', text)
            bind_text(button, 'setToolTip', text)
            button.clicked.connect(slot)
            setattr(window, 'chrome_' + kind + '_button', button)
            layout.addWidget(button)
        self.setStyleSheet('''
            QWidget#workbenchChrome { background: transparent; }
            QLabel#workbenchChromeBrand { font-weight: 600; }
            QMenuBar { background: transparent; spacing: 3px; }
            QMenuBar::item { padding: 6px 8px; background: transparent; border-radius: 7px; }
            QMenuBar::item:selected { background: #eaeaea; }
            QToolButton { background: transparent; border: 1px solid transparent; border-radius: 7px; }
            QToolButton:hover { background: #e7e7e7; }
            QToolButton:pressed { background: #dedede; }
            QToolButton:focus { border-color: #2563eb; }
            QToolButton#chromeClose:hover { background: #fee2e2; }
        ''')

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.owner.windowHandle()
            if handle and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.owner.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class WorkbenchWindow(QMainWindow):
    """可直接作为工作台基类；菜单使用 chrome_menu.addMenu。"""
    FRAME_WIDTH = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('memoryWindow')
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.chrome_header = _ChromeHeader(self)
        self.setMenuWidget(self.chrome_header)
        self._sync_frame()
        QApplication.instance().installEventFilter(self)

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _sync_frame(self):
        margin = 0 if self.isMaximized() or self.isFullScreen() else self.FRAME_WIDTH
        self.setContentsMargins(margin, margin, margin, margin)
        restored = self.isMaximized()
        self.chrome_maximize_button.setIcon(_window_icon('restore' if restored else 'maximize'))
        text = '还原' if restored else '最大化'
        bind_text(self.chrome_maximize_button, 'setAccessibleName', text)
        bind_text(self.chrome_maximize_button, 'setToolTip', text)
        self.update()

    def resize_edges(self, point):
        """按窗口逻辑坐标计算边角；最大化不提供缩放。"""
        edges = Qt.Edge(0)
        if self.isMaximized() or self.isFullScreen():
            return edges
        if point.x() < self.FRAME_WIDTH:
            edges |= Qt.Edge.LeftEdge
        elif point.x() >= self.width() - self.FRAME_WIDTH:
            edges |= Qt.Edge.RightEdge
        if point.y() < self.FRAME_WIDTH:
            edges |= Qt.Edge.TopEdge
        elif point.y() >= self.height() - self.FRAME_WIDTH:
            edges |= Qt.Edge.BottomEdge
        return edges

    def eventFilter(self, watched, event):
        if isinstance(watched, QComboBox) and event.type() in (QEvent.Type.Polish, QEvent.Type.Show):
            from .workbench_popup_ownership import prepare_owned_combo_popup
            prepare_owned_combo_popup(self, watched)
        if event.type() == QEvent.Type.Polish:
            from .workbench_popup_ownership import prepare_owned_popup
            prepare_owned_popup(self, watched)
        if event.type() in (QEvent.Type.Show, QEvent.Type.WinIdChange):
            from .workbench_popup_ownership import associate_owned_popup
            associate_owned_popup(self, watched)
        if isinstance(watched, QWidget) and watched.window() is self:
            if event.type() == QEvent.Type.Show:
                watched.setMouseTracking(True)
            elif event.type() == QEvent.Type.Leave and watched is self:
                self.unsetCursor()
            if event.type() in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
                point = self.mapFromGlobal(event.globalPosition().toPoint())
                edges = self.resize_edges(point)
                if event.type() == QEvent.Type.MouseMove:
                    horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
                    vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
                    cursor = Qt.CursorShape.ArrowCursor
                    if horizontal and vertical:
                        same = bool(edges & Qt.Edge.LeftEdge) == bool(edges & Qt.Edge.TopEdge)
                        cursor = Qt.CursorShape.SizeFDiagCursor if same else Qt.CursorShape.SizeBDiagCursor
                    elif horizontal:
                        cursor = Qt.CursorShape.SizeHorCursor
                    elif vertical:
                        cursor = Qt.CursorShape.SizeVerCursor
                    if edges:
                        self.setCursor(cursor)
                    else:
                        self.unsetCursor()
                elif edges and event.button() == Qt.MouseButton.LeftButton:
                    handle = self.windowHandle()
                    if handle and handle.startSystemResize(edges):
                        event.accept()
                        return True
        return super().eventFilter(watched, event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_frame()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor('#f6f6f6'))
        painter.setPen(QPen(QColor('#dedede'), 1))
        radius = 0 if self.isMaximized() or self.isFullScreen() else 12
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), radius, radius)
