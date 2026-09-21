"""原生审核工作区使用的 Qt 截图画布。"""
from __future__ import annotations

import base64
import hashlib
import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView


class _ResizeHandle(QGraphicsRectItem):
    """固定屏幕尺寸的拖动柄，拖动结果仍使用原图坐标。"""

    def __init__(self, owner: "RegionRectItem", horizontal: int, vertical: int) -> None:
        super().__init__(-4, -4, 8, 8, owner)
        self.owner = owner
        self.horizontal, self.vertical = horizontal, vertical
        self._start: list[float] | None = None
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.setBrush(QColor("#fff8df"))
        self.setPen(QPen(QColor("#a96d00"), 1))
        self.setZValue(3)
        cursor = (Qt.CursorShape.SizeHorCursor if vertical == 0 else
                  Qt.CursorShape.SizeVerCursor if horizontal == 0 else
                  Qt.CursorShape.SizeFDiagCursor if horizontal == vertical else
                  Qt.CursorShape.SizeBDiagCursor)
        self.setCursor(cursor)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setVisible(False)

    def mousePressEvent(self, event: Any) -> None:
        self._start = self.owner.bbox()
        event.accept()

    def mouseMoveEvent(self, event: Any) -> None:
        if self._start is None:
            return
        x, y, width, height = self._start
        right, bottom = x + width, y + height
        point, bounds = event.scenePos(), self.owner._bounds
        if self.horizontal < 0:
            x = max(bounds.left(), min(point.x(), right - 1))
        elif self.horizontal > 0:
            right = min(bounds.right(), max(point.x(), x + 1))
        if self.vertical < 0:
            y = max(bounds.top(), min(point.y(), bottom - 1))
        elif self.vertical > 0:
            bottom = min(bounds.bottom(), max(point.y(), y + 1))
        self.owner.set_bbox([x, y, right - x, bottom - y])
        event.accept()

    def mouseReleaseEvent(self, event: Any) -> None:
        self.mouseMoveEvent(event)
        self._start = None
        event.accept()


class RegionRectItem(QGraphicsRectItem):
    """原始截图坐标中可移动、可缩放且受边界限制的区域框。"""

    def __init__(self, region_id: str, bbox: list[float], bounds: QRectF) -> None:
        super().__init__(0.0, 0.0, float(bbox[2]), float(bbox[3]))
        self.region_id = region_id
        self._bounds = QRectF(bounds)
        self._handles: list[_ResizeHandle] = []
        self.setPos(float(bbox[0]), float(bbox[1]))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self._set_pen(False)
        self._handles = [_ResizeHandle(self, horizontal, vertical)
                         for horizontal, vertical in ((-1, -1), (0, -1), (1, -1),
                                                      (-1, 0), (1, 0),
                                                      (-1, 1), (0, 1), (1, 1))]
        self._position_handles()

    def _set_pen(self, selected: bool) -> None:
        pen = QPen(QColor("#f4b942") if selected else QColor("#247ba0"), 2.0)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QColor(36, 123, 160, 28))
        for handle in self._handles:
            handle.setVisible(selected)

    def _position_handles(self) -> None:
        for handle in self._handles:
            handle.setPos((handle.horizontal + 1) * self.rect().width() / 2,
                          (handle.vertical + 1) * self.rect().height() / 2)

    def set_bbox(self, bbox: list[float]) -> None:
        if (not isinstance(bbox, list) or len(bbox) != 4 or
                any(isinstance(value, bool) or not isinstance(value, (int, float)) or
                    not math.isfinite(value) for value in bbox)):
            raise ValueError("bbox must contain four finite coordinates")
        x, y, width, height = bbox
        if (x < self._bounds.left() or y < self._bounds.top() or width < 1 or height < 1 or
                x + width > self._bounds.right() or y + height > self._bounds.bottom()):
            raise ValueError("bbox must be a positive rectangle inside the original image")
        self.setRect(0, 0, width, height)
        self.setPos(x, y)
        self._position_handles()

    def itemChange(self, change: QGraphicsRectItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionChange:
            point = QPointF(value)
            rect = self.rect()
            point.setX(max(self._bounds.left(), min(point.x(), self._bounds.right() - rect.width())))
            point.setY(max(self._bounds.top(), min(point.y(), self._bounds.bottom() - rect.height())))
            return point
        if change == QGraphicsRectItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._set_pen(bool(value))
        return super().itemChange(change, value)

    def bbox(self) -> list[float]:
        rect = self.rect()
        return [round(self.pos().x(), 3), round(self.pos().y(), 3), round(rect.width(), 3), round(rect.height(), 3)]


class ReviewCanvas(QGraphicsView):
    """可缩放画布；只修改内存中的人工审核草稿。"""

    regionSelected = Signal(str)
    regionGeometryChanged = Signal(str, list)
    blankSelected = Signal()
    zoomChanged = Signal(float)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#f2f4f7"))
        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._regions: dict[str, RegionRectItem] = {}
        self._updating = False
        self._image_identity: tuple | None = None
        self._press_geometry: tuple[str, list[float]] | None = None
        self._pan_last = None
        self._scene.selectionChanged.connect(self._on_selection_changed)

    def clear_canvas(self) -> None:
        self._updating = True
        self._scene.clear()
        self._regions.clear()
        self._pixmap_item = None
        self._image_identity = None
        self._press_geometry = None
        self._updating = False

    def set_interface(self, batch: dict[str, Any], interface_id: str) -> None:
        interface = next((item for item in batch.get("interfaces", []) if item.get("interface_id") == interface_id), None)
        if interface is None:
            self.clear_canvas()
            return
        screenshot = next((item for item in batch.get("screenshots", []) if item.get("screenshot_id") == interface.get("screenshot_id")), None)
        if screenshot is None:
            self.clear_canvas()
            return
        raw = base64.b64decode(screenshot["png_base64"])
        image = QImage.fromData(raw, "PNG")
        if image.isNull():
            self.clear_canvas()
            return
        regions = [region for region in interface.get("regions", [])
                   if isinstance(region.get("bbox"), list) and len(region["bbox"]) == 4]
        self._display_image(raw, image, regions,
                            (batch.get("batch_id"), interface_id, screenshot.get("screenshot_id")))

    def set_image(self, png_bytes: bytes, regions: list[dict[str, Any]], identity: tuple) -> None:
        """从图证据直接显示原图与区域，不重建或写入旧批次。"""
        if not isinstance(png_bytes, bytes) or not isinstance(identity, tuple):
            raise ValueError("image evidence requires PNG bytes and a stable identity tuple")
        image = QImage.fromData(png_bytes, "PNG")
        if image.isNull():
            raise ValueError("image evidence is not a readable PNG")
        self._display_image(png_bytes, image, regions, identity)

    def _display_image(self, raw: bytes, image: QImage, regions: list[dict[str, Any]], identity: tuple) -> None:
        bounds = QRectF(0, 0, image.width(), image.height())
        if not isinstance(regions, list):
            raise ValueError("image regions must be a list")
        items: dict[str, RegionRectItem] = {}
        for region in regions:
            region_id = region.get("region_id") if isinstance(region, dict) else None
            if not isinstance(region_id, str) or not region_id or region_id in items:
                raise ValueError("image region identity is invalid or duplicated")
            item = RegionRectItem(region_id, [0, 0, 1, 1], bounds)
            item.set_bbox(region.get("bbox"))
            items[region_id] = item
        identity = (*identity, hashlib.sha256(raw).hexdigest())
        keep_view = identity == self._image_identity
        transform = self.transform()
        center = self.mapToScene(self.viewport().rect().center())
        self.clear_canvas()
        self._image_identity = identity
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(1)
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(bounds)
        for item in items.values():
            self._scene.addItem(item)
            self._regions[item.region_id] = item
        if keep_view:
            self.setTransform(transform)
            self.centerOn(center)
        else:
            self.fit_image()

    def select_region(self, region_id: str | None) -> None:
        self._updating = True
        for item_id, item in self._regions.items():
            item.setSelected(item_id == region_id)
        self._updating = False

    def set_region_bbox(self, region_id: str, bbox: list[float]) -> None:
        item = self._regions.get(region_id)
        if item is None:
            return
        self._updating = True
        try:
            item.set_bbox(bbox)
        finally:
            self._updating = False

    def add_region(self, region_id: str, bbox: list[float]) -> None:
        if self._pixmap_item is None or region_id in self._regions:
            return
        item = RegionRectItem(region_id, bbox, self._scene.sceneRect())
        self._scene.addItem(item); self._regions[region_id] = item
        self.select_region(region_id)

    def remove_region(self, region_id: str) -> None:
        item = self._regions.pop(region_id, None)
        if item is not None:
            self._scene.removeItem(item); del item

    def zoom_percent(self) -> float:
        return self.transform().m11() * self.devicePixelRatioF() * 100

    def set_zoom_percent(self, value: float) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 10 <= value <= 800:
            raise ValueError("zoom must be between 10 and 800 percent")
        center = self.mapToScene(self.viewport().rect().center())
        factor = value / 100 / self.devicePixelRatioF()
        self.setTransform(QTransform.fromScale(factor, factor))
        self.centerOn(center)
        self.zoomChanged.emit(self.zoom_percent())

    def show_actual_size(self) -> None:
        self.set_zoom_percent(100)

    def fit_image(self) -> None:
        if self._pixmap_item is not None:
            self.resetTransform()
            self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.zoomChanged.emit(self.zoom_percent())

    def wheelEvent(self, event: Any) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            requested = self.zoom_percent() * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15)
            self.set_zoom_percent(max(10, min(800, requested)))
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)
        selected = self._scene.selectedItems()
        self._press_geometry = None
        if not selected:
            self.blankSelected.emit()
        if selected and isinstance(selected[0], RegionRectItem):
            self._press_geometry = (selected[0].region_id, selected[0].bbox())

    def mouseMoveEvent(self, event: Any) -> None:
        if self._pan_last is not None:
            point = event.position().toPoint()
            delta = point - self._pan_last
            self._pan_last = point
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._pan_last is not None:
            self.mouseMoveEvent(event)
            self._pan_last = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        previous, self._press_geometry = self._press_geometry, None
        if previous is not None:
            region = self._regions.get(previous[0])
            if region is not None and region.bbox() != previous[1]:
                self.regionGeometryChanged.emit(region.region_id, region.bbox())

    def _on_selection_changed(self) -> None:
        if self._updating:
            return
        selected = self._scene.selectedItems()
        if selected and isinstance(selected[0], RegionRectItem):
            self.regionSelected.emit(selected[0].region_id)
