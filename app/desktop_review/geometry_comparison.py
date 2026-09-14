"""已保存审核截图上的只读几何框三方对照。"""
from __future__ import annotations

import base64
import binascii
from copy import deepcopy
import hashlib
import math
from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


_COMPARISON_CONTRACT = "desktop_relearn_comparison_v1"
_SHA256_LENGTH = 64


class _ReadonlyGraphicsView(QGraphicsView):
    """只允许缩放、适配和拖动画面，绝不移动审核框。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setInteractive(False)
        self.setBackgroundBrush(QColor("#f2f4f7"))

    def zoom_in(self) -> None:
        self.scale(1.15, 1.15)

    def zoom_out(self) -> None:
        self.scale(1 / 1.15, 1 / 1.15)

    def fit_image(self) -> None:
        rect = self.scene().sceneRect()
        if not rect.isEmpty():
            self.resetTransform()
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self.fit_image()

    def wheelEvent(self, event: Any) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            (self.zoom_in if event.angleDelta().y() > 0 else self.zoom_out)()
            event.accept()
            return
        super().wheelEvent(event)


class GeometryComparisonWidget(QWidget):
    """显示同一已保存截图上的重学基线、人工框和 Agent 候选框。"""

    def __init__(self, workspace: dict, comparison: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("截图框三方对照（只读）")
        self._workspace = _validate_workspace(workspace)
        self._comparison = _validate_comparison(comparison, self._workspace)
        self._targets = _geometry_targets(self._workspace, self._comparison)

        layout = QVBoxLayout(self)
        self.comparison_title = QLabel("截图框三方对照（只读）", self)
        self.comparison_title.setObjectName("geometryComparisonTitle")
        layout.addWidget(self.comparison_title)
        self.region_selector = QComboBox(self)
        self.region_selector.setObjectName("geometryComparisonRegionSelector")
        self.region_selector.setToolTip("选择要查看的区域；图片与框均来自已保存工作区。")
        layout.addWidget(self.region_selector)
        self.metadata_label = QLabel(self)
        self.metadata_label.setWordWrap(True)
        layout.addWidget(self.metadata_label)
        self.empty_label = QLabel(self)
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        controls = QHBoxLayout()
        self.zoom_out_button = QPushButton("缩小", self)
        self.zoom_in_button = QPushButton("放大", self)
        self.fit_button = QPushButton("适配", self)
        for button in (self.zoom_out_button, self.zoom_in_button, self.fit_button):
            button.setToolTip("三栏同时操作；Ctrl+滚轮缩放，拖动画面平移。")
            controls.addWidget(button)
        controls.addStretch(1)
        layout.addLayout(controls)

        columns = QHBoxLayout()
        self.baseline_view, self.baseline_bbox_label = self._column(columns, "重学基线")
        self.current_view, self.current_bbox_label = self._column(columns, "当前人工")
        self.proposed_view, self.proposed_bbox_label = self._column(columns, "Agent 候选")
        layout.addLayout(columns, 1)
        self.region_selector.currentIndexChanged.connect(self._show_target)
        self.zoom_out_button.clicked.connect(lambda: self._all_views("zoom_out"))
        self.zoom_in_button.clicked.connect(lambda: self._all_views("zoom_in"))
        self.fit_button.clicked.connect(lambda: self._all_views("fit_image"))

        for target in self._targets:
            self.region_selector.addItem(target["selector_text"], target["region_id"])
        if self._targets:
            self.empty_label.hide()
            self._show_target(0)
        else:
            self.metadata_label.hide()
            self.empty_label.setText("没有可显示的几何框差异；未绘制或伪造任何框。")

    def _column(self, columns: QHBoxLayout, title: str) -> tuple[_ReadonlyGraphicsView, QLabel]:
        box = QVBoxLayout()
        label = QLabel(title, self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(label)
        view = _ReadonlyGraphicsView(self)
        view.setMinimumSize(180, 140)
        box.addWidget(view, 1)
        bbox_label = QLabel("原像素框：—", self)
        bbox_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(bbox_label)
        columns.addLayout(box, 1)
        return view, bbox_label

    def _all_views(self, method: str) -> None:
        for view in (self.baseline_view, self.current_view, self.proposed_view):
            getattr(view, method)()

    def _show_target(self, index: int) -> None:
        if not 0 <= index < len(self._targets):
            return
        target = self._targets[index]
        self.metadata_label.setText(
            f"区域：{target['region_name']}（{target['region_id']}） · 所属界面："
            f"{target['interface_name']}（{target['interface_id']}） · 截图："
            f"{target['width']} × {target['height']} px · 原像素框：{_bbox_text(target['current'])}"
        )
        self._draw(self.baseline_view, target, target["baseline"], QColor("#7b2cbf"))
        self._draw(self.current_view, target, target["current"], QColor("#247ba0"))
        self._draw(self.proposed_view, target, target["proposed"], QColor("#d1495b"))
        self.baseline_bbox_label.setText("原像素框：" + _bbox_text(target["baseline"]))
        self.current_bbox_label.setText("原像素框：" + _bbox_text(target["current"]))
        self.proposed_bbox_label.setText("原像素框：" + _bbox_text(target["proposed"]))

    @staticmethod
    def _draw(view: _ReadonlyGraphicsView, target: dict[str, Any], bbox: list[float] | None, color: QColor) -> None:
        scene = view.scene()
        scene.clear()
        pixmap = QPixmap.fromImage(target["image"])
        scene.addItem(QGraphicsPixmapItem(pixmap))
        if bbox is not None:
            rect = QGraphicsRectItem(0.0, 0.0, bbox[2], bbox[3])
            rect.setPos(bbox[0], bbox[1])
            rect.setPen(QPen(color, 2.0))
            rect.setBrush(QColor(color.red(), color.green(), color.blue(), 24))
            rect.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
            rect.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
            rect.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            rect.setZValue(2)
            scene.addItem(rect)
        scene.setSceneRect(QRectF(0, 0, target["width"], target["height"]))
        view.fit_image()


def _validate_workspace(workspace: Any) -> dict[str, Any]:
    if not isinstance(workspace, dict):
        raise ValueError("workspace 必须是已保存的对象")
    required = ("task_id", "batch_id", "source_ref", "revision", "batch")
    if any(key not in workspace for key in required):
        raise ValueError("workspace 缺少固定身份字段")
    if not all(isinstance(workspace[key], str) and workspace[key] for key in ("task_id", "batch_id")):
        raise ValueError("workspace task_id 或 batch_id 无效")
    if not _is_sha(workspace["source_ref"]) or type(workspace["revision"]) is not int or workspace["revision"] < 1:
        raise ValueError("workspace source_ref 或 revision 无效")
    batch = workspace["batch"]
    if not isinstance(batch, dict) or not isinstance(batch.get("screenshots"), list) or not isinstance(batch.get("interfaces"), list):
        raise ValueError("workspace batch 缺少 screenshots 或 interfaces")
    screenshots: dict[str, dict[str, Any]] = {}
    for screenshot in batch["screenshots"]:
        if not isinstance(screenshot, dict) or not isinstance(screenshot.get("screenshot_id"), str) or not screenshot["screenshot_id"]:
            raise ValueError("保存截图身份无效")
        sid = screenshot["screenshot_id"]
        if sid in screenshots:
            raise ValueError("保存截图身份重复")
        image = _validated_png(screenshot)
        screenshots[sid] = {**screenshot, "image": image}
    interfaces: dict[str, dict[str, Any]] = {}
    regions: dict[str, dict[str, Any]] = {}
    for interface in batch["interfaces"]:
        if not isinstance(interface, dict) or not isinstance(interface.get("interface_id"), str) or not interface["interface_id"]:
            raise ValueError("保存界面身份无效")
        iid = interface["interface_id"]
        if iid in interfaces or interface.get("screenshot_id") not in screenshots or not isinstance(interface.get("regions"), list):
            raise ValueError("保存界面或截图绑定无效")
        interfaces[iid] = interface
        for region in interface["regions"]:
            if not isinstance(region, dict) or not isinstance(region.get("region_id"), str) or not region["region_id"]:
                raise ValueError("保存区域身份无效")
            rid = region["region_id"]
            if rid in regions:
                raise ValueError("保存区域身份重复")
            regions[rid] = {"region": region, "interface": interface, "screenshot": screenshots[interface["screenshot_id"]]}
            _bbox(region.get("bbox"), screenshots[interface["screenshot_id"]]["width"], screenshots[interface["screenshot_id"]]["height"], "保存区域 bbox")
    return {"raw": deepcopy(workspace), "screenshots": screenshots, "interfaces": interfaces, "regions": regions}


def _validate_comparison(comparison: Any, workspace: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(comparison, dict) or comparison.get("contract_version") != _COMPARISON_CONTRACT:
        raise ValueError("comparison contract_version 无效")
    raw = workspace["raw"]
    for key in ("task_id", "batch_id", "source_ref", "workspace_revision"):
        expected = raw["revision"] if key == "workspace_revision" else raw[key]
        if (key == "workspace_revision" and type(comparison.get(key)) is not int) or comparison.get(key) != expected:
            raise ValueError(f"comparison {key} 不匹配已保存工作区")
    if not isinstance(comparison.get("candidate_id"), str) or not comparison["candidate_id"]:
        raise ValueError("comparison candidate_id 无效")
    for key in ("candidate_sha256", "review_baseline_sha256"):
        if not _is_sha(comparison.get(key)):
            raise ValueError(f"comparison {key} 无效")
    if comparison.get("status") not in {"current", "stale", "withdrawn", "legacy_unbound", "blocked"}:
        raise ValueError("comparison status 无效")
    if not isinstance(comparison.get("diffs"), list):
        raise ValueError("comparison diffs 必须是数组")
    return deepcopy(comparison)


def _geometry_targets(workspace: dict[str, Any], comparison: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    added_counts: dict[str, int] = {}
    for diff in comparison["diffs"]:
        if not isinstance(diff, dict):
            raise ValueError("comparison diff 必须是对象")
        if diff.get("target_type") == "region" and diff.get("field") == "entity":
            target = _added_geometry_target(workspace, diff, seen, added_counts)
            targets.append(target)
            seen.add(target["region_id"])
            continue
        is_geometry = diff.get("target_type") == "region" and diff.get("field") == "bbox"
        if not is_geometry:
            continue
        region_id = diff.get("target_id")
        if not isinstance(region_id, str) or region_id in seen or region_id not in workspace["regions"]:
            raise ValueError("geometry diff 的区域目标必须唯一且存在")
        seen.add(region_id)
        binding = workspace["regions"][region_id]
        screenshot = binding["screenshot"]
        width, height = screenshot["width"], screenshot["height"]
        baseline = _bbox(diff.get("baseline"), width, height, "geometry baseline")
        current = _bbox(diff.get("current"), width, height, "geometry current")
        proposed = _bbox(diff.get("proposed"), width, height, "geometry proposed")
        saved = _bbox(binding["region"].get("bbox"), width, height, "保存区域 bbox")
        if current != saved:
            raise ValueError("geometry current 必须等于已保存 workspace 区域 bbox")
        if comparison["status"] == "current" and baseline != current:
            raise ValueError("current comparison 的 geometry baseline 必须等于 current")
        interface = binding["interface"]
        targets.append({
            "region_id": region_id,
            "region_name": _display_name(binding["region"]), "interface_id": interface["interface_id"],
            "interface_name": _display_name(interface), "width": width, "height": height,
            "image": screenshot["image"], "baseline": baseline, "current": current, "proposed": proposed,
            "selector_text": f"{_display_name(binding['region'])} · {_display_name(interface)}",
        })
    return targets


def _added_geometry_target(workspace: dict[str, Any], diff: dict[str, Any], seen: set[str], counts: dict[str, int]) -> dict[str, Any]:
    from app.agent_link.contracts import AgentLinkError, RegionInput, parse

    if set(diff) != {"target_type", "target_id", "field", "baseline", "current", "proposed"}:
        raise ValueError("新增区域 diff 字段无效")
    region_id = diff["target_id"]
    if not isinstance(region_id, str) or not region_id or region_id in seen or region_id in workspace["regions"]:
        raise ValueError("新增区域必须具有当前不存在的唯一身份")
    if diff["baseline"] is not None or diff["current"] is not None:
        raise ValueError("新增区域的 baseline/current 必须明确不存在")
    proposed = diff["proposed"]
    if not isinstance(proposed, dict) or set(proposed) != {"interface_id", "region"}:
        raise ValueError("新增区域的父绑定字段无效")
    interface_id = proposed["interface_id"]
    if not isinstance(interface_id, str) or interface_id not in workspace["interfaces"]:
        raise ValueError("新增区域必须属于已保存界面")
    try:
        region = parse(RegionInput, proposed["region"], "新增区域")
    except AgentLinkError as error:
        raise ValueError("新增区域契约无效") from error
    if region["region_id"] != region_id:
        raise ValueError("新增区域内容身份与 diff 不一致")
    interface = workspace["interfaces"][interface_id]
    counts[interface_id] = counts.get(interface_id, 0) + 1
    if len(interface["regions"]) + counts[interface_id] > 128:
        raise ValueError("新增区域超过界面数量上限")
    screenshot = workspace["screenshots"][interface["screenshot_id"]]
    width, height = screenshot["width"], screenshot["height"]
    bbox = _bbox(region["bbox"], width, height, "新增区域 bbox")
    return {
        "region_id": region_id, "region_name": _display_name(region),
        "interface_id": interface_id, "interface_name": _display_name(interface),
        "width": width, "height": height, "image": screenshot["image"],
        "baseline": None, "current": None, "proposed": bbox,
        "selector_text": f"新增 · {_display_name(region)} · {_display_name(interface)}",
    }


def _validated_png(screenshot: dict[str, Any]) -> QImage:
    if not isinstance(screenshot.get("png_base64"), str) or not _is_sha(screenshot.get("sha256")):
        raise ValueError("保存截图 PNG 或 SHA-256 无效")
    if type(screenshot.get("width")) is not int or type(screenshot.get("height")) is not int or screenshot["width"] < 1 or screenshot["height"] < 1:
        raise ValueError("保存截图尺寸无效")
    try:
        raw = base64.b64decode(screenshot["png_base64"], validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("保存截图不是有效 base64 PNG") from error
    if hashlib.sha256(raw).hexdigest() != screenshot["sha256"]:
        raise ValueError("保存截图 PNG SHA-256 不匹配")
    image = QImage.fromData(raw, "PNG")
    if image.isNull() or image.width() != screenshot["width"] or image.height() != screenshot["height"]:
        raise ValueError("保存截图 PNG 实际尺寸不匹配")
    return image


def _bbox(value: Any, width: int, height: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(f"{label} 必须是四个像素数值")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{label} 必须是有限且非布尔数值")
        try:
            numeric = float(item)
        except OverflowError as error:
            raise ValueError(f"{label} 必须是有限且非布尔数值") from error
        if not math.isfinite(numeric):
            raise ValueError(f"{label} 必须是有限且非布尔数值")
        result.append(numeric)
    x, y, box_width, box_height = result
    if x < 0 or y < 0 or box_width <= 0 or box_height <= 0 or x + box_width > width or y + box_height > height:
        raise ValueError(f"{label} 越出截图边界，拒绝裁剪")
    return result


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == _SHA256_LENGTH and all(char in "0123456789abcdef" for char in value)


def _display_name(value: dict[str, Any]) -> str:
    for key in ("meaning", "name", "label"):
        if isinstance(value.get(key), str) and value[key].strip():
            return value[key].strip()
    return "未命名"


def _bbox_text(bbox: list[float] | None) -> str:
    if bbox is None:
        return "不存在（新增控件）"
    return "[" + ", ".join(f"{value:g}" for value in bbox) + "]"
