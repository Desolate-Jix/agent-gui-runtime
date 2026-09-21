"""独立界面内容审核器；不创建流程图，也不执行动作。"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QPlainTextEdit, QScrollArea, QSplitter, QVBoxLayout, QWidget
from .canvas import ReviewCanvas
from .friendly_controls import DetailsSection
from .interface_content import SUPPORTED_REGION_KINDS


_REGION_KIND_HELP = "支持类型：" + "、".join(SUPPORTED_REGION_KINDS)


class InterfaceReviewPane(QWidget):
    saved = Signal(object)
    reviewed = Signal(object)
    errorRaised = Signal(str)

    def __init__(self, facade: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._snapshot: dict[str, Any] | None = None
        self._regions: list[dict[str, Any]] = []
        self._dirty = False
        self._loading = False
        self._read_only = False
        self._selected_region_id: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.title = QLabel("独立界面编辑")
        self.title.setWordWrap(True)
        self.status = QLabel("尚未加载界面内容")
        self.status.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.status)
        self.editor_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.editor_splitter.setChildrenCollapsible(False)
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = ReviewCanvas()
        self.canvas.setObjectName("interfaceEvidenceCanvas")
        self.canvas.setMinimumHeight(220)
        # 定时器归画布所有；画布销毁时会自动取消尚未执行的适应窗口回调。
        self._fit_timer = QTimer(self.canvas)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self.canvas.fit_image)
        self.canvas.regionGeometryChanged.connect(self._region_geometry_changed)
        self.canvas.blankSelected.connect(self._blank_selected)
        self.canvas.regionSelected.connect(self._region_selected)
        canvas_layout.addWidget(self.canvas, 1)
        zoom = QHBoxLayout()
        actual = QPushButton("原始像素 100%")
        fit = QPushButton("适应窗口")
        actual.clicked.connect(self.canvas.show_actual_size)
        fit.clicked.connect(self.canvas.fit_image)
        zoom.addWidget(actual)
        zoom.addWidget(fit)
        zoom.addStretch()
        canvas_layout.addLayout(zoom)
        self.editor_splitter.addWidget(canvas_container)
        inspector = QWidget()
        inspector.setMinimumWidth(240)
        inspector_layout = QVBoxLayout(inspector)
        self.selection_label = QLabel("界面信息 · 点击截图中的框可编辑该框")
        self.selection_label.setWordWrap(True)
        inspector_layout.addWidget(self.selection_label)
        self.region_properties = QWidget()
        form = QFormLayout(self.region_properties)
        form.setContentsMargins(0, 0, 0, 0)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.meaning_edit = QLineEdit()
        self.meaning_edit.setObjectName("interfaceMeaningEdit")
        self.recognition_text_edit = QLineEdit()
        self.recognition_text_edit.setObjectName("interfaceRecognitionTextEdit")
        self.regions_edit = QPlainTextEdit()
        self.regions_edit.setObjectName("interfaceRegionsEdit")
        self.regions_edit.setPlaceholderText("每个区域一行 JSON bbox：[x, y, width, height]")
        self.regions_edit.hide()
        self.region_name_edit = QLineEdit(); self.region_kind_edit = QLineEdit()
        self.region_text_edit = QLineEdit(); self.region_meaning_edit = QLineEdit()
        self.region_kind_edit.setPlaceholderText(_REGION_KIND_HELP)
        self.region_kind_edit.setToolTip(_REGION_KIND_HELP)
        form.addRow("框名称", self.region_name_edit)
        form.addRow("框类型", self.region_kind_edit)
        form.addRow("框识别文字", self.region_text_edit)
        form.addRow("框含义", self.region_meaning_edit)
        self.bbox_spins = []
        coordinates = QHBoxLayout()
        for label in ("X", "Y", "宽", "高"):
            column = QVBoxLayout(); column.addWidget(QLabel(label))
            spin = QDoubleSpinBox(); spin.setRange(0, 100000); spin.setDecimals(1)
            column.addWidget(spin); coordinates.addLayout(column); self.bbox_spins.append(spin)
            spin.valueChanged.connect(self._bbox_edited)
        form.addRow("位置与大小（原图像素）", coordinates)
        inspector_layout.addWidget(self.region_properties)
        interface_form = QFormLayout()
        interface_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        interface_form.addRow("界面含义", self.meaning_edit)
        interface_form.addRow("整页识别文字", self.recognition_text_edit)
        self.binding_kind = QComboBox()
        self.binding_kind.addItem("本机应用", "native")
        self.binding_kind.addItem("网页来源", "web")
        self.binding_name = QLineEdit()
        self.binding_identity = QLineEdit()
        self.binding_identity.setPlaceholderText("可执行文件路径或网页来源")
        inspector_layout.addLayout(interface_form)
        binding_body = QWidget()
        binding_form = QFormLayout(binding_body)
        binding_form.addRow("应用类型", self.binding_kind)
        binding_form.addRow("应用名称", self.binding_name)
        binding_form.addRow("应用标识", self.binding_identity)
        self.binding_section = DetailsSection("应用信息（可选）", binding_body)
        inspector_layout.addWidget(self.binding_section)
        inspector_layout.addStretch(1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(inspector)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.editor_splitter.addWidget(scroll)
        self.editor_splitter.setSizes([650, 310])
        layout.addWidget(self.editor_splitter, 1)
        buttons = QHBoxLayout()
        self.save_button = QPushButton("保存修改")
        self.save_button.setProperty("primary", True)
        self.review_button = QPushButton("审核界面")
        self.review_button.hide()
        self.compose_button = QPushButton("加入流程项目")
        self.relearn_button = QPushButton("交给 Agent 修正")
        self.discard_button = QPushButton("放弃修改")
        self.add_region_button = QPushButton("新增框")
        self.remove_region_button = QPushButton("删除选中框")
        self.add_region_button.clicked.connect(self.add_region)
        self.remove_region_button.clicked.connect(self.remove_selected_region)
        self.discard_button.clicked.connect(self.discard_changes)
        self.save_button.clicked.connect(self.save_changes)
        self.review_button.clicked.connect(lambda: self.review())
        self.compose_button.clicked.connect(self.open_composition)
        self.relearn_button.clicked.connect(self.open_relearning)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.review_button)
        buttons.addWidget(self.compose_button)
        buttons.addWidget(self.relearn_button)
        buttons.addWidget(self.discard_button)
        zoom.insertWidget(0, self.remove_region_button)
        zoom.insertWidget(0, self.add_region_button)
        layout.addLayout(buttons)
        self.meaning_edit.textChanged.connect(self._mark_dirty)
        self.recognition_text_edit.textChanged.connect(self._mark_dirty)
        self.binding_kind.currentIndexChanged.connect(self._mark_dirty)
        self.binding_name.textChanged.connect(self._mark_dirty)
        self.binding_identity.textChanged.connect(self._mark_dirty)
        for edit in (self.region_name_edit, self.region_kind_edit, self.region_text_edit, self.region_meaning_edit):
            edit.textChanged.connect(self._sync_selected_region_fields)
        self._sync_buttons()

    def _blank_selected(self) -> None:
        self._selected_region_id = None
        for edit in (self.region_name_edit, self.region_kind_edit, self.region_text_edit, self.region_meaning_edit):
            edit.clear()
        self.region_properties.hide()
        self.selection_label.setText("界面信息 · 点击截图中的框可编辑该框")
        self._sync_buttons()

    @property
    def snapshot(self) -> dict[str, Any] | None:
        return deepcopy(self._snapshot)

    @property
    def dirty(self) -> bool:
        return self._dirty

    def set_read_only(self, value: bool) -> None:
        self._read_only = bool(value)
        for widget in (self.meaning_edit, self.recognition_text_edit, self.binding_name, self.binding_identity):
            widget.setReadOnly(self._read_only)
        self.binding_kind.setEnabled(not self._read_only)
        self.canvas.setInteractive(not self._read_only)
        self._sync_buttons()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_fit_image()

    def _schedule_fit_image(self) -> None:
        self._fit_timer.start(0)

    def _mark_dirty(self, *_args) -> None:
        if self._loading or self._read_only or self._snapshot is None:
            return
        self._dirty = True
        self.status.setText("有未保存修改：请保存后再加入项目或切换界面。")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        loaded = self._snapshot is not None
        self.save_button.setEnabled(loaded and not self._read_only)
        self.review_button.setEnabled(loaded and not self._dirty and not self._read_only)
        self.compose_button.setEnabled(loaded and not self._dirty)
        self.relearn_button.setEnabled(loaded and not self._dirty and not self._read_only and callable(getattr(self.facade, "request_interface_relearning", None)))
        self.discard_button.setEnabled(self._dirty and not self._read_only)
        self.add_region_button.setEnabled(loaded and not self._read_only)
        self.remove_region_button.setEnabled(loaded and not self._read_only and self._selected_region_id is not None)
        self.region_properties.setEnabled(loaded and not self._read_only)

    def discard_changes(self) -> None:
        if self._snapshot is not None:
            self.set_snapshot(self._snapshot)

    def clear_content(self) -> None:
        if self._dirty: return
        self._loading = True
        self._snapshot = None; self._regions = []
        self.canvas.clear_canvas(); self._blank_selected()
        self.meaning_edit.clear(); self.recognition_text_edit.clear()
        self.binding_name.clear(); self.binding_identity.clear()
        self.title.setText("选择一个界面")
        self.status.setText("点击左侧已学内容开始查看或修改。")
        self._loading = False; self._sync_buttons()

    def set_snapshot(self, snapshot: dict[str, Any]) -> None:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("content"), dict):
            raise ValueError("invalid interface content snapshot")
        content = snapshot["content"]
        loader = getattr(self.facade, "load_interface_content_evidence", None)
        if callable(loader):
            evidence = loader(snapshot["interface_id"], snapshot.get("version_id"))
            image_file = self.facade._artifact_file(evidence["image_path"], "独立界面截图")
            self.canvas.set_image(image_file.read_bytes(), content.get("regions") or [],
                (snapshot["interface_id"], snapshot.get("version_id", ""), snapshot.get("content_sha256", "")))
        else:
            self.canvas.clear_canvas()
        self._loading = True
        self._snapshot = deepcopy(snapshot)
        self._blank_selected()
        self.title.setText(str(content.get("meaning") or snapshot.get("interface_id") or "独立界面"))
        self.meaning_edit.setText(str(content.get("meaning") or ""))
        self.recognition_text_edit.setText(str(content.get("recognition_text") or ""))
        self._regions = deepcopy(content.get("regions") or [])
        self.regions_edit.setPlainText(json.dumps(self._regions, ensure_ascii=False))
        self.binding_kind.setCurrentIndex(max(0, self.binding_kind.findData((snapshot.get("application_binding") or {}).get("kind", "native"))))
        binding = snapshot.get("application_binding") or {}
        self.binding_name.setText(str(binding.get("display_name") or ""))
        self.binding_identity.setText(str(binding.get("executable_identity") or binding.get("canonical_origin") or ""))
        self._original_binding_fields = self._binding()
        self._dirty = False
        self._loading = False
        state = "新学内容" if snapshot.get("origin_status") == "new" else "有修改"
        self.status.setText(f"独立界面 · 修订 {snapshot.get('revision')} · {state} · 保存即完成 · 不执行外部动作")
        self._sync_buttons()
        if self.isVisible():
            self._schedule_fit_image()

    def _changes(self) -> dict[str, Any]:
        if self._snapshot is None:
            raise ValueError("interface content is not loaded")
        changes = {"meaning": self.meaning_edit.text().strip(), "regions": deepcopy(self._regions)}
        recognition = self.recognition_text_edit.text().strip()
        if recognition or "recognition_text" in self._snapshot["content"]:
            changes["recognition_text"] = recognition
        current_binding = self._binding()
        if current_binding != self._original_binding_fields:
            changes["application_binding"] = current_binding if self.binding_name.text().strip() or self.binding_identity.text().strip() else None
        return changes

    def _region_geometry_changed(self, region_id: str, bbox: list[float]) -> None:
        if self._read_only or self._loading:
            return
        for region in self._regions:
            if region.get("region_id") == region_id:
                region["bbox"] = list(bbox)
                if region_id == self._selected_region_id:
                    self._loading = True
                    for spin, value in zip(self.bbox_spins, bbox): spin.setValue(value)
                    self._loading = False
                self._mark_dirty()
                return

    def _region_selected(self, region_id: str) -> None:
        self._selected_region_id = region_id
        region = next((item for item in self._regions if item.get("region_id") == region_id), None)
        if region is None: return
        self._loading = True
        try:
            for edit, key in ((self.region_name_edit,"name"),(self.region_kind_edit,"kind"),(self.region_text_edit,"recognition_text"),(self.region_meaning_edit,"meaning")):
                edit.setText(str(region.get(key) or ""))
            for spin, value in zip(self.bbox_spins, region['bbox']): spin.setValue(value)
        finally:
            self._loading = False
        self.region_properties.show()
        self.selection_label.setText("正在编辑识别框 · 拖动框或角点调整位置大小")
        self._sync_buttons()

    def _bbox_edited(self):
        if self._loading or self._read_only or self._selected_region_id is None: return
        rect = self.canvas.scene().sceneRect()
        bounds = (rect.width(), rect.height())
        if bounds[0] <= 0 or bounds[1] <= 0: return
        x, y, width, height = [spin.value() for spin in self.bbox_spins]
        width, height = max(1, min(width, bounds[0])), max(1, min(height, bounds[1]))
        x, y = min(x, bounds[0]-width), min(y, bounds[1]-height)
        bbox = [x, y, width, height]
        self.canvas.set_region_bbox(self._selected_region_id, bbox)
        self._region_geometry_changed(self._selected_region_id, bbox)

    def _sync_selected_region_fields(self, *_args) -> None:
        if self._loading or self._read_only or self._selected_region_id is None: return
        region = next((item for item in self._regions if item.get("region_id") == self._selected_region_id), None)
        if region is None: return
        for edit, key in ((self.region_name_edit,"name"),(self.region_kind_edit,"kind"),(self.region_text_edit,"recognition_text"),(self.region_meaning_edit,"meaning")):
            value = edit.text().strip()
            region[key] = value
        self._mark_dirty()

    def add_region(self) -> None:
        if self._read_only or self._snapshot is None: return
        region_id = "region-user-" + str(uuid4())
        bounds = self.canvas.scene().sceneRect()
        width, height = min(40.0, max(1.0, bounds.width() / 4)), min(30.0, max(1.0, bounds.height() / 4))
        x = min(max(bounds.left(), bounds.left() + 8.0), max(bounds.left(), bounds.right() - width))
        y = min(max(bounds.top(), bounds.top() + 8.0), max(bounds.top(), bounds.bottom() - height))
        bbox = [x, y, width, height]
        self._regions.append({"region_id": region_id, "bbox": bbox, "name": "新区域", "kind": "unknown", "meaning": "新区域", "recognition_text": ""})
        self.canvas.add_region(region_id, bbox)
        self._region_selected(region_id); self._mark_dirty()

    def remove_selected_region(self) -> None:
        if self._read_only or self._selected_region_id is None: return
        self._regions = [item for item in self._regions if item.get("region_id") != self._selected_region_id]
        self.canvas.remove_region(self._selected_region_id); self._blank_selected(); self._mark_dirty()

    def save_changes(self) -> None:
        if self._snapshot is None or self._read_only:
            return
        try:
            result = self.facade.save_interface_content(
                self._snapshot["interface_id"], self._snapshot["revision"], self._snapshot["content_sha256"],
                self._changes(), uuid4().hex,
            )
            self.set_snapshot(result)
            self._dirty = False
            self.saved.emit(deepcopy(result))
        except Exception as error:
            message = str(error)
            if message == "interface_content_region_kind_invalid":
                message = "框类型不支持。" + _REGION_KIND_HELP
            self.errorRaised.emit(message)

    def review(self, application_binding: dict[str, Any] | None = None) -> None:
        if self._snapshot is None or self._read_only:
            return
        if self._dirty:
            self.errorRaised.emit("请先保存界面修改，不能审核屏幕上尚未保存的内容。")
            return
        try:
            binding = application_binding or self._binding()
            result = self.facade.review_interface_content(
                self._snapshot["interface_id"], self._snapshot["revision"], self._snapshot["content_sha256"],
                deepcopy(binding),
            )
            self.set_snapshot(result)
            self.reviewed.emit(deepcopy(result))
        except Exception as error:
            self.errorRaised.emit(str(error))

    def _binding(self) -> dict[str, Any]:
        kind = self.binding_kind.currentData()
        binding: dict[str, Any] = {"kind": kind, "display_name": self.binding_name.text().strip()}
        binding["executable_identity" if kind == "native" else "canonical_origin"] = self.binding_identity.text().strip()
        return binding

    def open_composition(self) -> None:
        if self._snapshot is None:
            return
        if self._dirty:
            self.errorRaised.emit("请先保存界面修改，再加入流程。")
            return
        from .content_library import WorkflowCompositionDialog
        dialog = WorkflowCompositionDialog(self.facade, self._snapshot, self)
        dialog.exec()

    def open_relearning(self) -> None:
        if self._snapshot is None or self._dirty or self._read_only:
            return
        from .interface_relearning_dialog import InterfaceRelearningDialog
        dialog = InterfaceRelearningDialog(self.facade, self._snapshot,
                                            self._selected_region_id, self)
        dialog.adopted.connect(self._relearning_adopted)
        dialog.errorRaised.connect(self.errorRaised)
        dialog.exec()

    def _relearning_adopted(self, snapshot: dict[str, Any]) -> None:
        if self._dirty:
            self.errorRaised.emit("界面已有未保存修改，未覆盖当前草稿；请先保存或放弃后再采用 Agent 修正。")
            return
        self.set_snapshot(snapshot)
        self.saved.emit(deepcopy(snapshot))


__all__ = ["InterfaceReviewPane"]
