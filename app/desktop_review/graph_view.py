"""原生只读流程图视图。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
import re
from typing import Any

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF, QTransform
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOGICAL_ID = re.compile(r"workflow-[0-9a-f]{64}\Z")
# 卡片留出更宽的中文标题和更大的点选面，仍只改变视图几何。
_NODE_WIDTH = 204.0
_NODE_HEIGHT = 82.0
_COLUMN_GAP = 72.0
_ROW_GAP = 72.0
_SURFACE = "#ffffff"
_BACKGROUND = "#f4f7fb"
_ACCENT = "#2563eb"
_TEXT = "#172b4d"
_MUTED = "#52627a"
_BORDER = "#dbe3ef"
_KNOWN_ACTION_LABELS = {
    "click": "点击",
    "observe": "观察",
    "open_detail": "打开详情",
    "back": "返回",
    "go_back": "返回",
    "open_apply_flow": "打开申请流程",
    "fill_field": "填写字段",
    "continue_next_step": "继续下一步",
    "final_submit": "最终提交",
}


def friendly_action_label(action: str) -> str:
    return _KNOWN_ACTION_LABELS.get(action, "动作待核对")


def _elide(text: str, font: QFont, width: float) -> str:
    return QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, int(width))


class _NodeItem(QGraphicsRectItem):
    def __init__(self, node_id: str, label: str) -> None:
        super().__init__(0.0, 0.0, _NODE_WIDTH, _NODE_HEIGHT)
        self.node_id = node_id
        self.label = label
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setZValue(2)
        self.setToolTip(label)
        self._set_pen(False)
        self._type_text = QGraphicsSimpleTextItem("界面", self)
        type_font = QFont(self._type_text.font())
        type_font.setPointSizeF(9.0)
        self._type_text.setFont(type_font)
        self._type_text.setBrush(QColor(_MUTED))
        self._type_text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._type_text.setPos(14.0, 11.0)
        self._title_text = QGraphicsSimpleTextItem(self)
        title_font = QFont(self._title_text.font())
        title_font.setPointSizeF(11.0)
        title_font.setBold(True)
        self._title_text.setFont(title_font)
        self._title_text.setText(_elide(label, title_font, _NODE_WIDTH - 28.0))
        self._title_text.setToolTip(label)
        self._title_text.setBrush(QColor(_TEXT))
        self._title_text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._title_text.setPos(14.0, 33.0)

    def _set_pen(self, selected: bool) -> None:
        self.setBrush(QColor("#eff6ff") if selected else QColor(_SURFACE))
        pen = QPen(QColor(_ACCENT) if selected else QColor(_BORDER), 2.5 if selected else 1.5)
        pen.setCosmetic(True)
        self.setPen(pen)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRoundedRect(self.rect(), 10.0, 10.0)

    def itemChange(self, change: QGraphicsRectItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsRectItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._set_pen(bool(value) or self.hasFocus())
        return super().itemChange(change, value)

    def focusInEvent(self, event: Any) -> None:
        super().focusInEvent(event)
        self._set_pen(True)

    def focusOutEvent(self, event: Any) -> None:
        super().focusOutEvent(event)
        self._set_pen(self.isSelected())


class _EdgeItem(QGraphicsPathItem):
    def __init__(self, edge_id: str, label: str, path: QPainterPath, label_position: QPointF, display_label: str | None = None) -> None:
        super().__init__(path)
        self.edge_id = edge_id
        self.label = label
        self.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setZValue(1)
        self.setToolTip(label)
        self._set_pen(False)
        self._label_text = QGraphicsSimpleTextItem(self)
        label_font = QFont(self._label_text.font())
        label_font.setPointSizeF(10.0)
        self._label_text.setFont(label_font)
        self.display_label = display_label or label
        self._label_text.setText(_elide(self.display_label, label_font, 176.0))
        self._label_text.setToolTip(label)
        self._label_text.setBrush(QColor(_MUTED))
        self._label_text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        bounds = self._label_text.boundingRect()
        self._label_background = QGraphicsRectItem(
            QRectF(-4.0, -2.0, bounds.width() + 8.0, bounds.height() + 4.0), self,
        )
        self._label_background.setBrush(QColor(_SURFACE))
        self._label_background.setPen(QPen(Qt.PenStyle.NoPen))
        self._label_background.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._label_background.setZValue(0.0)
        self._label_background.setPos(label_position.x() - bounds.width() / 2, label_position.y() - bounds.height() / 2)
        self._label_text.setZValue(1.0)
        self._label_text.setPos(label_position.x() - bounds.width() / 2, label_position.y() - bounds.height() / 2)

    def _set_pen(self, selected: bool) -> None:
        pen = QPen(QColor(_ACCENT) if selected else QColor(_MUTED), 3.5 if selected else 2.25)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        self.setPen(pen)

    def shape(self) -> QPainterPath:
        """让连线有稳定的宽点击带，但不改变绘制的箭头和关系。"""
        stroker = QPainterPathStroker()
        stroker.setWidth(12.0)
        return stroker.createStroke(self.path())

    def itemChange(self, change: QGraphicsPathItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsPathItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._set_pen(bool(value))
        return super().itemChange(change, value)


class _SequenceLinkItem(QGraphicsPathItem):
    """仅显示动作顺序缺口，不参与选择、边集合或执行语义。"""

    def __init__(self, path: QPainterPath, label: str, label_position: QPointF) -> None:
        super().__init__(path)
        pen = QPen(QColor("#9aa7b5"), 1.8, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setZValue(-1)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        text = QGraphicsSimpleTextItem(label, self)
        text.setBrush(QColor("#7b8794"))
        text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        bounds = text.boundingRect()
        text.setPos(label_position.x() - bounds.width() / 2, label_position.y() - bounds.height() / 2)


class NativeWorkflowGraphView(QGraphicsView):
    """显示一个不可执行的正式图修订，并只输出稳定 ID 选择。"""

    nodeSelected = Signal(str)
    edgeSelected = Signal(str)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._scene = self._empty_scene()
        self.setScene(self._scene)
        self._revision: dict[str, Any] | None = None
        self._node_items: dict[str, _NodeItem] = {}
        self._edge_items: dict[str, _EdgeItem] = {}
        self._updating_selection = False
        self._last_selection: tuple[str, str] | None = None
        self._pan_last: QPoint | None = None
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor(_BACKGROUND))

    def _empty_scene(self) -> QGraphicsScene:
        scene = QGraphicsScene(self)
        scene.setBackgroundBrush(QColor(_BACKGROUND))
        scene.selectionChanged.connect(self._on_selection_changed)
        return scene

    def set_revision(self, snapshot: dict[str, Any]) -> None:
        checked = _validate_revision(snapshot)
        self._install_checked(checked)

    def set_project(self, snapshot: dict[str, Any]) -> None:
        from .workflow_project import validate_project_view
        self._install_checked(validate_project_view(snapshot))

    def _install_checked(self, checked: dict[str, Any]) -> None:
        scene, nodes, edges = self._build_scene(checked["graph"])
        old_scene = self._scene
        self._scene = scene
        self._node_items = nodes
        self._edge_items = edges
        self._revision = checked
        self._last_selection = None
        self.setScene(scene)
        old_scene.deleteLater()
        self.fit_graph()

    def clear_graph(self) -> None:
        scene = self._empty_scene()
        old_scene = self._scene
        self._scene = scene
        self._revision = None
        self._node_items = {}
        self._edge_items = {}
        self._last_selection = None
        self.setScene(scene)
        old_scene.deleteLater()
        self.resetTransform()

    def select_node(self, node_id: str) -> None:
        item = self._node_items.get(node_id)
        if item is None:
            raise ValueError("unknown node id")
        self._select_silently(item, ("node", node_id))

    def select_edge(self, edge_id: str) -> None:
        item = self._edge_items.get(edge_id)
        if item is None:
            raise ValueError("unknown edge id")
        self._select_silently(item, ("edge", edge_id))

    def fit_graph(self) -> None:
        if not self._node_items:
            return
        bounds = self._scene.itemsBoundingRect().adjusted(-36.0, -36.0, 36.0, 36.0)
        self._scene.setSceneRect(bounds)
        self.resetTransform()
        self.fitInView(bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def readable_zoom(self) -> None:
        """显式放大至清晰字号；小窗口可平移，完整概览仍由适合窗口负责。"""
        self.fit_graph()
        if not self._node_items:
            return
        current = self.transform().m11()
        if current < 0.9:
            self.scale(0.9 / current, 0.9 / current)
        if self._last_selection is not None:
            kind, identity = self._last_selection
            item = (self._node_items if kind == "node" else self._edge_items).get(identity)
            if item is not None:
                self.centerOn(item)

    def set_zoom_percent(self, value: float) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 10 <= value <= 800:
            raise ValueError("zoom must be between 10 and 800 percent")
        center = self.mapToScene(self.viewport().rect().center())
        self.setTransform(QTransform.fromScale(float(value) / 100.0, float(value) / 100.0))
        self.centerOn(center)

    def wheelEvent(self, event: Any) -> None:
        if not self._node_items:
            return super().wheelEvent(event)
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        current = self.transform().m11()
        if 0.1 <= current * factor <= 8.0:
            self.scale(factor, factor)
        event.accept()

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

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
            self._pan_last = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _select_silently(self, item: QGraphicsRectItem | QGraphicsPathItem, identity: tuple[str, str]) -> None:
        self._updating_selection = True
        try:
            self._scene.clearSelection()
            item.setSelected(True)
            self.centerOn(item)
            self._last_selection = identity
        finally:
            self._updating_selection = False

    def _on_selection_changed(self) -> None:
        if self._updating_selection:
            return
        selected = self._scene.selectedItems()
        identity: tuple[str, str] | None = None
        if len(selected) == 1 and isinstance(selected[0], _NodeItem):
            identity = ("node", selected[0].node_id)
        elif len(selected) == 1 and isinstance(selected[0], _EdgeItem):
            identity = ("edge", selected[0].edge_id)
        if identity is None:
            self._last_selection = None
            return
        if identity == self._last_selection:
            return
        self._last_selection = identity
        if identity[0] == "node":
            self.nodeSelected.emit(identity[1])
        else:
            self.edgeSelected.emit(identity[1])

    def _build_scene(self, graph: dict[str, Any]) -> tuple[QGraphicsScene, dict[str, _NodeItem], dict[str, _EdgeItem]]:
        scene = self._empty_scene()
        nodes: dict[str, _NodeItem] = {}
        ordered_nodes = _ordered_graph_nodes(graph)
        columns = len(ordered_nodes) if len(ordered_nodes) <= 4 else max(1, math.ceil(math.sqrt(len(ordered_nodes))))
        for index, source in enumerate(ordered_nodes):
            item = _NodeItem(source["node_id"], source["display_name"])
            item.setPos((index % columns) * (_NODE_WIDTH + _COLUMN_GAP),
                        (index // columns) * (_NODE_HEIGHT + _ROW_GAP))
            scene.addItem(item)
            nodes[item.node_id] = item

        # 顺序线只消费权威 action_sequence；无完整事件 pair 时不画，避免猜测节点。
        sequence = graph.get("action_sequence")
        if isinstance(sequence, list):
            pairs = {
                edge.get("external_step_id"): (edge.get("source_node_id"), edge.get("target_node_id"))
                for edge in graph["edges"]
                if isinstance(edge, dict) and isinstance(edge.get("external_step_id"), str)
            }
            previous_pair = None
            for item in sorted(
                (value for value in sequence if isinstance(value, dict)),
                key=lambda value: value.get("sequence_index", 0),
            ):
                pair = pairs.get(item.get("event_id"))
                if pair is None or pair[0] not in nodes or pair[1] not in nodes:
                    previous_pair = None
                    continue
                if previous_pair is not None and item.get("previous_event_id") == previous_pair[0]:
                    source_node, target_node = nodes[previous_pair[1]], nodes[pair[0]]
                    path = QPainterPath(source_node.sceneBoundingRect().center())
                    end = target_node.sceneBoundingRect().center()
                    mid_x = (path.currentPosition().x() + end.x()) / 2
                    path.cubicTo(mid_x, path.currentPosition().y(), mid_x, end.y(), end.x(), end.y())
                    scene.addItem(_SequenceLinkItem(path, "下一次操作 · 衔接未核验", path.pointAtPercent(0.5)))
                previous_pair = (item.get("event_id"), pair[1])

        edges: dict[str, _EdgeItem] = {}
        directional: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for edge in graph["edges"]:
            directional.setdefault((edge["source_node_id"], edge["target_node_id"]), []).append(edge)
        for group in directional.values():
            group.sort(key=lambda item: item["edge_id"])
        for key in sorted(directional):
            source_id, target_id = key
            group = directional[key]
            reverse_exists = source_id != target_id and (target_id, source_id) in directional
            for index, source in enumerate(group):
                path, label_position = _edge_path(
                    nodes[source_id], nodes[target_id], index, len(group), reverse_exists,
                )
                label = source.get("label") or source["action_type"]
                action_type = source.get("action_type")
                display_label = label
                if not source.get("label"):
                    display_label = friendly_action_label(action_type)
                item = _EdgeItem(source["edge_id"], label, path, label_position, display_label)
                scene.addItem(item)
                edges[item.edge_id] = item
        return scene, nodes, edges


def _ordered_graph_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    # 独立关系组连续排布，避免无关节点挡住另一组的连线。
    nodes = {node['node_id']: node for node in graph['nodes']}
    incoming = dict.fromkeys(nodes, 0)
    outgoing = {identity: [] for identity in nodes}
    adjacent = {identity: set() for identity in nodes}
    for edge in graph['edges']:
        source, target = edge['source_node_id'], edge['target_node_id']
        if source != target:
            incoming[target] += 1; outgoing[source].append(target)
            adjacent[source].add(target)
            adjacent[target].add(source)
    ordered = []
    remaining = set(nodes)
    while remaining:
        component = set()
        pending = [min(remaining)]
        while pending:
            identity = pending.pop()
            if identity in component:
                continue
            component.add(identity)
            pending.extend(adjacent[identity] - component)
        remaining.difference_update(component)
        ready = sorted(identity for identity in component if incoming[identity] == 0)
        group = []
        while ready:
            identity = ready.pop(0)
            group.append(identity)
            for target in sorted(outgoing[identity]):
                incoming[target] -= 1
                if incoming[target] == 0:
                    ready.append(target)
        # 循环节点仍按稳定身份排布，不修改真实跳转关系。
        ordered.extend(group)
        ordered.extend(sorted(component - set(group)))
    return [nodes[identity] for identity in ordered]


def _validate_revision(value: Any) -> dict[str, Any]:
    fields = {"contract_version", "logical_workflow_id", "revision", "content_sha256", "parent_sha256", "source_refs", "graph", "change"}
    if not isinstance(value, dict) or set(value) != fields or value.get("contract_version") != "formal_graph_revision_v1":
        raise ValueError("invalid formal graph revision")
    logical_id = value.get("logical_workflow_id")
    revision = value.get("revision")
    digest = value.get("content_sha256")
    parent = value.get("parent_sha256")
    if (not isinstance(logical_id, str) or not _LOGICAL_ID.fullmatch(logical_id) or
            isinstance(revision, bool) or not isinstance(revision, int) or revision < 1 or
            not isinstance(digest, str) or not _SHA256.fullmatch(digest) or
            (parent is not None and (not isinstance(parent, str) or not _SHA256.fullmatch(parent))) or
            not isinstance(value.get("source_refs"), dict) or not isinstance(value.get("change"), dict)):
        raise ValueError("invalid formal graph revision identity")
    if (revision == 1 and parent is not None) or (revision > 1 and parent is None):
        raise ValueError("invalid formal graph revision parent")
    content = deepcopy(value)
    content.pop("content_sha256")
    try:
        calculated = hashlib.sha256(json.dumps(
            content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest()
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise ValueError("formal graph revision is not canonical JSON") from error
    if calculated != digest:
        raise ValueError("formal graph revision digest mismatch")
    graph = value.get("graph")
    if (not isinstance(graph, dict) or graph.get("display_only") is not True or
            graph.get("artifact_is_authorization") is not False or
            graph.get("execute_binding_enabled") is not False or
            not isinstance(graph.get("nodes"), list) or not isinstance(graph.get("edges"), list)):
        raise ValueError("invalid display-only graph")
    node_ids: set[str] = set()
    for node in graph["nodes"]:
        if not isinstance(node, dict):
            raise ValueError("invalid graph node")
        node_id, label = node.get("node_id"), node.get("display_name")
        if (not isinstance(node_id, str) or not node_id or len(node_id) > 512 or node_id in node_ids or
                not isinstance(label, str) or not label.strip() or len(label) > 4000):
            raise ValueError("invalid or duplicate graph node id")
        node_ids.add(node_id)
    edge_ids: set[str] = set()
    for edge in graph["edges"]:
        if not isinstance(edge, dict):
            raise ValueError("invalid graph edge")
        edge_id = edge.get("edge_id")
        source_id, target_id = edge.get("source_node_id"), edge.get("target_node_id")
        label = edge.get("label") or edge.get("action_type")
        if (not isinstance(edge_id, str) or not edge_id or len(edge_id) > 512 or edge_id in edge_ids or
                not isinstance(source_id, str) or not isinstance(target_id, str) or
                source_id not in node_ids or target_id not in node_ids or
                not isinstance(label, str) or not label.strip() or len(label) > 4000):
            raise ValueError("invalid, duplicate, or dangling graph edge")
        edge_ids.add(edge_id)
    return deepcopy(value)


def _edge_path(source: _NodeItem, target: _NodeItem, index: int, count: int, reverse_exists: bool) -> tuple[QPainterPath, QPointF]:
    if source is target:
        rect = source.sceneBoundingRect()
        start = QPointF(rect.right() - 28.0, rect.top() + 5.0)
        end = QPointF(rect.left() + 28.0, rect.top() + 5.0)
        lift = 58.0 + index * 30.0
        first = QPointF(rect.right() + 46.0 + index * 18.0, rect.top() - lift)
        second = QPointF(rect.left() - 46.0 - index * 18.0, rect.top() - lift)
        path = QPainterPath(start)
        path.cubicTo(first, second, end)
        label_position = QPointF(rect.center().x(), rect.top() - lift - 7.0)
        tangent_from = second
    else:
        source_center, target_center = source.sceneBoundingRect().center(), target.sceneBoundingRect().center()
        start = _rectangle_boundary(source.sceneBoundingRect(), target_center)
        end = _rectangle_boundary(target.sceneBoundingRect(), source_center)
        dx, dy = end.x() - start.x(), end.y() - start.y()
        length = max(1.0, math.hypot(dx, dy))
        if count == 1 and not reverse_exists:
            curve = 0.0
        else:
            curve = 28.0 * (index + 1)
        control = QPointF((start.x() + end.x()) / 2 - dy / length * curve,
                          (start.y() + end.y()) / 2 + dx / length * curve)
        path = QPainterPath(start)
        path.quadTo(control, end)
        label_position = QPointF(
            0.25 * start.x() + 0.5 * control.x() + 0.25 * end.x(),
            0.25 * start.y() + 0.5 * control.y() + 0.25 * end.y(),
        )
        tangent_from = control
    _append_arrow(path, tangent_from, end)
    return path, label_position


def _rectangle_boundary(rect: QRectF, toward: QPointF) -> QPointF:
    center = rect.center()
    dx, dy = toward.x() - center.x(), toward.y() - center.y()
    if dx == 0 and dy == 0:
        return QPointF(rect.right(), center.y())
    scale = 1.0 / max(abs(dx) / (rect.width() / 2), abs(dy) / (rect.height() / 2))
    return QPointF(center.x() + dx * scale, center.y() + dy * scale)


def _append_arrow(path: QPainterPath, tangent_from: QPointF, end: QPointF) -> None:
    dx, dy = end.x() - tangent_from.x(), end.y() - tangent_from.y()
    length = max(1.0, math.hypot(dx, dy))
    ux, uy = dx / length, dy / length
    left = QPointF(end.x() - ux * 13.0 - uy * 6.0, end.y() - uy * 13.0 + ux * 6.0)
    right = QPointF(end.x() - ux * 13.0 + uy * 6.0, end.y() - uy * 13.0 - ux * 6.0)
    path.addPolygon(QPolygonF([end, left, right, end]))


__all__ = ["NativeWorkflowGraphView"]
