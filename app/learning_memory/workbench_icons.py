"""学习工作台的轻量线性图标。"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


_PATHS = {
    "steps": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="m3 6 1 1 2-2m-3 7 1 1 2-2m-3 7 1 1 2-2"/>',
    "graph": '<rect x="9" y="2" width="6" height="5" rx="1"/><rect x="2" y="17" width="6" height="5" rx="1"/><rect x="16" y="17" width="6" height="5" rx="1"/><path d="M12 7v5M5 17v-5h14v5"/>',
    "library": '<rect x="3" y="4" width="4" height="16" rx="1"/><rect x="9" y="4" width="4" height="16" rx="1"/><path d="m16 4 4 1 1 15-4 1z"/>',
    "refresh": '<path d="M20 8a8 8 0 1 0 0 8M20 3v5h-5"/>',
    "save": '<path d="M4 3h13l4 4v14H3V3z"/><path d="M7 3v6h10V3M7 21v-8h10v8"/>',
    "play": '<path d="m7 3 14 9-14 9z"/>',
    "plus": '<path d="M12 4v16M4 12h16"/>',
    "trash": '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    "undo": '<path d="m8 4-5 5 5 5M3 9h10a7 7 0 0 1 0 14"/>',
    "edit": '<path d="m4 16 12-12 4 4L8 20l-5 1zM13 7l4 4"/>',
    "crop": '<path d="M6 2v16h16M2 6h16v16"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8" cy="8" r="1.5"/><path d="m3 18 6-6 4 4 4-5 4 5"/>',
    "arrow-up": '<path d="M12 20V4m-7 7 7-7 7 7"/>',
    "arrow-down": '<path d="M12 4v16m-7-7 7 7 7-7"/>',
    "settings": '<path d="m10 3 4 0 1 3 3 1 3 3-2 3v4l-3 2-3-1-3 3-4-1-1-3-3-2 1-4-2-3 3-3 3 1z"/><circle cx="12" cy="12" r="3"/>',
    "check": '<path d="m4 12 5 5L20 6"/>',
    "search": '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
    "zoom": '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6M6 10h8M10 6v8"/>',
    "link": '<path d="m10 7 3-3a5 5 0 0 1 7 7l-3 3M14 17l-3 3a5 5 0 0 1-7-7l3-3M8 16l8-8"/>',
}


def workbench_icon(name: str, color: str = "#525252") -> QIcon:
    """返回支持高分屏的透明线性图标；未知名称返回空图标。"""
    paths = _PATHS.get(name)
    if paths is None:
        return QIcon()
    stroke = QColor(color).name()
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{stroke}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>'
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    result = QIcon()
    for size in (16, 20, 24, 32, 40, 48):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        result.addPixmap(pixmap)
    return result


icon = workbench_icon
