"""独立界面内容审核器；不创建流程图，也不执行动作。"""
from __future__ import annotations
from app.learning_memory.workbench_i18n import ui, tr, bind_text, user_text

from copy import deepcopy
import json
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QPlainTextEdit, QScrollArea, QSplitter, QVBoxLayout, QWidget
from .canvas import ReviewCanvas
from .friendly_controls import DetailsSection
from .interface_content import SUPPORTED_REGION_KINDS
from .jobs import make_job


_REGION_KIND_HELP = tr("支持类型：") + ", ".join(SUPPORTED_REGION_KINDS)


class InterfaceReviewPane(QWidget):
    saved = Signal(object)
    reviewed = Signal(object)
    errorRaised = Signal(str)
    targetRuleRequested = Signal(object)
    loaded = Signal(object)

    def __init__(self, facade: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._snapshot: dict[str, Any] | None = None
        self._regions: list[dict[str, Any]] = []
        self._dirty = False
        self._loading = False
        self._read_only = False
        self._selected_region_id: str | None = None
        self._target_link = None
        self._load_job = None
        self._load_sequence = 0
        self._pending_snapshot = None
        self._load_outcome = None
        self._display_evidence = None
        self._load_failed = False
        self._delete_after_load = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.title = ui(QLabel, tr('独立界面编辑'))
        self.title.setWordWrap(True)
        self.status = ui(QLabel, tr('尚未加载界面内容'))
        self.status.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.status)
        target_row = QHBoxLayout()
        self.target_choice = QComboBox()
        self.target_choice.setObjectName("interfaceLearnedTargetChoice")
        self.target_choice.currentIndexChanged.connect(self._target_view_changed)
        self.edit_target_button = ui(QPushButton, tr('修改此步骤的定位规则'))
        self.edit_target_button.clicked.connect(self._open_target_rule)
        target_row.addWidget(self.target_choice, 1)
        target_row.addWidget(self.edit_target_button)
        layout.addLayout(target_row)
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
        actual = ui(QPushButton, tr('原始像素 100%'))
        fit = ui(QPushButton, tr('适应窗口'))
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
        self.selection_label = ui(QLabel, tr('界面信息 · 点击截图中的框可编辑该框'))
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
        ui(self.regions_edit.setPlaceholderText, tr('每个区域一行 JSON bbox：[x, y, width, height]'))
        self.regions_edit.hide()
        self.region_name_edit = QLineEdit(); self.region_kind_edit = QLineEdit()
        self.region_text_edit = QLineEdit(); self.region_meaning_edit = QLineEdit()
        ui(self.region_kind_edit.setPlaceholderText, _REGION_KIND_HELP)
        ui(self.region_kind_edit.setToolTip, _REGION_KIND_HELP)
        ui(form.addRow, tr('框名称'), self.region_name_edit)
        ui(form.addRow, tr('框类型'), self.region_kind_edit)
        ui(form.addRow, tr('框识别文字'), self.region_text_edit)
        ui(form.addRow, tr('框含义'), self.region_meaning_edit)
        self.bbox_spins = []
        coordinates = QHBoxLayout()
        for label in ("X", "Y", "宽", "高"):
            column = QVBoxLayout(); column.addWidget(ui(QLabel, tr(label)))
            spin = QDoubleSpinBox(); spin.setRange(0, 100000); spin.setDecimals(1)
            column.addWidget(spin); coordinates.addLayout(column); self.bbox_spins.append(spin)
            spin.valueChanged.connect(self._bbox_edited)
        ui(form.addRow, tr('位置与大小（原图像素）'), coordinates)
        inspector_layout.addWidget(self.region_properties)
        interface_form = QFormLayout()
        interface_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        ui(interface_form.addRow, tr('界面含义'), self.meaning_edit)
        ui(interface_form.addRow, tr('整页识别文字'), self.recognition_text_edit)
        self.binding_kind = QComboBox()
        ui(self.binding_kind.addItem, tr('本机应用'), 'native')
        ui(self.binding_kind.addItem, tr('网页来源'), 'web')
        self.binding_name = QLineEdit()
        self.binding_identity = QLineEdit()
        ui(self.binding_identity.setPlaceholderText, tr('可执行文件路径或网页来源'))
        inspector_layout.addLayout(interface_form)
        binding_body = QWidget()
        binding_form = QFormLayout(binding_body)
        ui(binding_form.addRow, tr('应用类型'), self.binding_kind)
        ui(binding_form.addRow, tr('应用名称'), self.binding_name)
        ui(binding_form.addRow, tr('应用标识'), self.binding_identity)
        self.binding_section = DetailsSection("应用信息（可选）", binding_body)
        inspector_layout.addWidget(self.binding_section)
        inspector_layout.addStretch(1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(inspector)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.editor_splitter.addWidget(scroll)
        self.editor_splitter.setSizes([650, 310])
        layout.addWidget(self.editor_splitter, 1)
        buttons = QHBoxLayout()
        self.save_button = ui(QPushButton, tr('保存修改'))
        self.save_button.setProperty("primary", True)
        self.review_button = ui(QPushButton, tr('审核界面'))
        self.review_button.hide()
        self.compose_button = ui(QPushButton, tr('加入流程项目'))
        self.relearn_button = ui(QPushButton, tr('交给 Agent 修正'))
        self.discard_button = ui(QPushButton, tr('放弃修改'))
        self.add_region_button = ui(QPushButton, tr('新增框'))
        self.remove_region_button = ui(QPushButton, tr('删除选中框'))
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
        ui(self.selection_label.setText, tr('点击学习框查看目标规则。') if self._target_link else tr('界面信息 · 点击截图中的框可编辑该框') if self._regions else tr('当前界面没有标注框；可新增框，或选择上方已学步骤目标。'))
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
        if self._loading or self._load_failed or self._read_only or self._snapshot is None or self._target_link is not None:
            return
        self._dirty = True
        ui(self.status.setText, tr('有未保存修改：请保存后再加入项目或切换界面。'))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        loaded = self._snapshot is not None and not self._loading and not self._load_failed
        target_view = self._target_link is not None
        self.save_button.setEnabled(loaded and not self._read_only and not target_view)
        self.review_button.setEnabled(loaded and not self._dirty and not self._read_only)
        self.compose_button.setEnabled(loaded and not self._dirty)
        self.relearn_button.setEnabled(loaded and not self._dirty and not self._read_only and callable(getattr(self.facade, "request_interface_relearning", None)))
        self.discard_button.setEnabled(self._dirty and not self._read_only)
        self.add_region_button.setEnabled(loaded and not self._read_only and not target_view)
        self.remove_region_button.setEnabled(loaded and not self._read_only and not target_view and self._selected_region_id is not None)
        self.region_properties.setEnabled(loaded and not self._read_only and not target_view)
        self.target_choice.setEnabled(loaded and not self._dirty)
        self.edit_target_button.setEnabled(loaded and target_view and not self._read_only and not self._dirty)
        for widget in (self.meaning_edit, self.recognition_text_edit, self.binding_name, self.binding_identity):
            widget.setReadOnly(not loaded or self._read_only or target_view)
        self.binding_kind.setEnabled(loaded and not self._read_only and not target_view)
        self.canvas.setInteractive(loaded and not self._read_only)

    @property
    def is_busy(self):
        return self._load_job is not None or self._pending_snapshot is not None

    def cancel_loading(self):
        self._load_sequence += 1
        self._pending_snapshot = None
        self._loading = False
        self._load_failed = True
        self._display_evidence = None
        self.canvas.clear_canvas()
        self._target_link = None
        self.target_choice.clear()
        self._sync_buttons()

    def closeEvent(self, event):
        if self.is_busy:
            self.cancel_loading()
            event.ignore()
            return
        super().closeEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete and self.is_busy:
            self._delete_after_load = True
            self.cancel_loading()
            return True
        return super().event(event)

    def _read_display_evidence(self, snapshot):
        key, version = snapshot['interface_id'], snapshot.get('version_id')
        latest = self.facade.load_interface_content(key)
        loader = getattr(self.facade, 'load_interface_content_evidence', None)
        image = None
        if callable(loader):
            evidence = loader(key, version)
            image = self.facade._artifact_file(evidence['image_path'], '独立界面截图').read_bytes()
            if evidence.get('sha256') and hashlib.sha256(image).hexdigest() != evidence['sha256']:
                raise ValueError('interface_evidence_hash_mismatch')
        regions = deepcopy(snapshot['content'].get('regions') or [])
        recover = getattr(self.facade, 'read_learned_target_regions', None)
        if not regions and (snapshot.get('source') or {}).get('kind') == 'execution_memory_v1' and callable(recover):
            regions = deepcopy(recover(key, version)['regions'])
        links = getattr(self.facade, 'read_interface_target_links', None)
        targets = links(key, version)['targets'] if callable(links) else []
        frames = {}
        for target in targets:
            frame = target['frame']
            data = Path(frame['image_path']).read_bytes()
            if hashlib.sha256(data).hexdigest() != frame['sha256']:
                raise ValueError('target_evidence_hash_mismatch')
            frames[(frame['image_path'], frame['sha256'])] = data
        return {'image': image, 'regions': regions, 'targets': targets, 'frames': frames,
                'latest_version_id': latest['version_id']}

    def _start_display_read(self, sequence, snapshot):
        job = make_job(sequence, lambda: self._read_display_evidence(snapshot), self)
        self._load_job = job
        self._load_outcome = None
        job.succeeded.connect(self._display_read_succeeded)
        job.failed.connect(self._display_read_failed)
        job.finished.connect(self._display_read_finished)
        job.start()

    def _display_read_succeeded(self, sequence, result):
        self._load_outcome = (sequence, True, result)

    def _display_read_failed(self, sequence, error):
        self._load_outcome = (sequence, False, error)

    def _display_read_finished(self):
        job = self._load_job
        self._load_job = None
        job.deleteLater()
        outcome = self._load_outcome
        self._load_outcome = None
        if outcome and outcome[0] == self._load_sequence:
            if outcome[1]:
                try:
                    self._display_evidence = outcome[2]
                    self._install_snapshot(self._snapshot)
                    self.loaded.emit({'snapshot': self.snapshot, 'latest_version_id': outcome[2]['latest_version_id']})
                except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
                    self._display_install_failed(str(error))
            else:
                self._display_install_failed(str(outcome[2]))
        if self._pending_snapshot is not None:
            sequence, snapshot = self._pending_snapshot
            self._pending_snapshot = None
            self._start_display_read(sequence, snapshot)
        elif self._delete_after_load:
            self.deleteLater()

    def _display_install_failed(self, error):
        self._loading = False
        self._load_failed = True
        self._display_evidence = None
        self._target_link = None
        self.target_choice.clear()
        self.canvas.clear_canvas()
        ui(self.status.setText, tr('界面证据读取失败：') + error.splitlines()[0])
        self._sync_buttons()
        self.errorRaised.emit(error)

    def discard_changes(self) -> None:
        if self._snapshot is not None:
            self.set_snapshot(self._snapshot)

    def clear_content(self) -> None:
        if self._dirty: return
        self.cancel_loading()
        self._loading = True
        self._snapshot = None; self._regions = []
        self._target_link = None; self.target_choice.clear()
        self.canvas.clear_canvas(); self._blank_selected()
        self.meaning_edit.clear(); self.recognition_text_edit.clear()
        self.binding_name.clear(); self.binding_identity.clear()
        ui(self.title.setText, tr('选择一个界面'))
        ui(self.status.setText, tr('点击左侧已学内容开始查看或修改。'))
        self._loading = False; self._sync_buttons()

    def set_snapshot(self, snapshot: dict[str, Any]) -> None:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("content"), dict):
            raise ValueError("invalid interface content snapshot")
        if getattr(self.facade, 'background_interface_loading', False):
            self._load_sequence += 1
            self._snapshot = deepcopy(snapshot)
            self._loading = True
            self._load_failed = False
            self._dirty = False
            self._regions = []
            self._target_link = None
            self._display_evidence = None
            self.target_choice.clear()
            self.canvas.clear_canvas()
            self._blank_selected()
            user_text(self.title.setText, str(snapshot['content'].get('meaning') or snapshot['interface_id']))
            self.meaning_edit.setText(str(snapshot['content'].get('meaning') or ''))
            self.recognition_text_edit.setText(str(snapshot['content'].get('recognition_text') or ''))
            binding = snapshot.get('application_binding') or {}
            self.binding_kind.setCurrentIndex(max(0, self.binding_kind.findData(binding.get('kind', 'native'))))
            self.binding_name.setText(str(binding.get('display_name') or ''))
            self.binding_identity.setText(str(binding.get('executable_identity') or binding.get('canonical_origin') or ''))
            ui(self.status.setText, tr('正在读取界面证据…'))
            self._sync_buttons()
            if self._load_job is None:
                self._start_display_read(self._load_sequence, deepcopy(snapshot))
            else:
                self._pending_snapshot = (self._load_sequence, deepcopy(snapshot))
            return
        self._install_snapshot(snapshot)

    def _install_snapshot(self, snapshot):
        self._load_failed = False
        content = snapshot["content"]
        self._loading = True
        self._target_link = None
        loader = getattr(self.facade, "load_interface_content_evidence", None)
        if self._display_evidence is not None:
            pass
        elif callable(loader):
            evidence = loader(snapshot["interface_id"], snapshot.get("version_id"))
            image_file = self.facade._artifact_file(evidence["image_path"], "独立界面截图")
            self.canvas.set_image(image_file.read_bytes(), content.get("regions") or [],
                (snapshot["interface_id"], snapshot.get("version_id", ""), snapshot.get("content_sha256", "")))
        else:
            self.canvas.clear_canvas()
        self._loading = True
        self._snapshot = deepcopy(snapshot)
        self._blank_selected()
        ui(self.title.setText, str(content.get('meaning') or snapshot.get('interface_id') or tr('独立界面')))
        self.meaning_edit.setText(str(content.get("meaning") or ""))
        self.recognition_text_edit.setText(str(content.get("recognition_text") or ""))
        self._regions = deepcopy(self._display_evidence['regions'] if self._display_evidence is not None else content.get("regions") or [])
        recover = getattr(self.facade, "read_learned_target_regions", None)
        if self._display_evidence is None and not self._regions and snapshot["source"].get("kind") == "execution_memory_v1" and callable(recover):
            recovered = recover(snapshot["interface_id"], snapshot.get("version_id"))
            self._regions = deepcopy(recovered["regions"])
        self.regions_edit.setPlainText(json.dumps(self._regions, ensure_ascii=False))
        self.binding_kind.setCurrentIndex(max(0, self.binding_kind.findData((snapshot.get("application_binding") or {}).get("kind", "native"))))
        binding = snapshot.get("application_binding") or {}
        self.binding_name.setText(str(binding.get("display_name") or ""))
        self.binding_identity.setText(str(binding.get("executable_identity") or binding.get("canonical_origin") or ""))
        self._original_binding_fields = self._binding()
        self._dirty = False
        self.target_choice.clear()
        ui(self.target_choice.addItem, tr('界面标注（保存为独立界面版本）'), None)
        links = getattr(self.facade, "read_interface_target_links", None)
        if callable(links):
            result = {'targets': self._display_evidence['targets']} if self._display_evidence is not None else links(snapshot["interface_id"], snapshot.get("version_id"))
            for target in result["targets"]:
                ui(self.target_choice.addItem, tr('已学目标 · {v0} · {v1}', v0=target['step_title'], v1=target['workflow_title']), target)
        self.target_choice.setVisible(callable(links))
        self.edit_target_button.setVisible(callable(links))
        if self.target_choice.count() > 1:
            self.target_choice.setCurrentIndex(1)
        self._loading = False
        state = tr("新学内容") if snapshot.get("origin_status") == "new" else tr("有修改")
        ui(self.status.setText, tr('独立界面 · 修订 {v0} · {v1} · 保存即完成 · 不执行外部动作', v0=snapshot.get('revision'), v1=state))
        self._target_view_changed()
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
        if self._read_only or self._loading or self._load_failed:
            return
        if self._target_link is not None:
            target = deepcopy(self._target_link)
            target["box_request"] = {"strategy_index": int(region_id.removeprefix("strategy-")), "bbox": list(bbox)}
            self._target_view_changed()
            self.targetRuleRequested.emit(target)
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
        regions = self._target_link["target_boxes"] if self._target_link is not None else self._regions
        region = next((item for item in regions if item.get("region_id") == region_id), None)
        if region is None: return
        self._loading = True
        try:
            for edit, key in ((self.region_name_edit,"name"),(self.region_kind_edit,"kind"),(self.region_text_edit,"recognition_text"),(self.region_meaning_edit,"meaning")):
                value = str(region.get(key) or "")
                if self._target_link is not None:
                    labels = {"uia": "固定控件", "visible_row": "动态列表动作", "learning_target": "学习时定位的目标控件",
                        "learning_example": "学习时所选行的动作示例；运行时按本次输入重新选行"}
                    if key == 'kind' and value in labels:
                        ui(edit.setText, tr(labels[value]))
                        continue
                user_text(edit.setText, value)
            for spin, value in zip(self.bbox_spins, region['bbox']): spin.setValue(value)
        finally:
            self._loading = False
        self.region_properties.show()
        ui(self.selection_label.setText, tr('学习目标框 · 点击上方按钮修改对应步骤规则；拖动框可选择另一控件。') if self._target_link else tr('正在编辑识别框 · 拖动框或角点调整位置大小'))
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
        if self._loading or self._read_only or self._selected_region_id is None or self._target_link is not None: return
        region = next((item for item in self._regions if item.get("region_id") == self._selected_region_id), None)
        if region is None: return
        for edit, key in ((self.region_name_edit,"name"),(self.region_kind_edit,"kind"),(self.region_text_edit,"recognition_text"),(self.region_meaning_edit,"meaning")):
            value = edit.text().strip()
            region[key] = value
        self._mark_dirty()

    def add_region(self) -> None:
        if self._read_only or self._snapshot is None or self._loading or self._load_failed: return
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
        if self._snapshot is None or self._read_only or self._target_link is not None or self._loading or self._load_failed:
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
                message = tr("框类型不支持。") + _REGION_KIND_HELP
            self.errorRaised.emit(message)

    def _target_view_changed(self, *_args):
        if self._loading or self._snapshot is None or self._load_failed:
            return
        self._target_link = deepcopy(self.target_choice.currentData())
        if self._target_link is not None:
            frame = self._target_link["frame"]
            data = self._display_evidence['frames'][(frame['image_path'], frame['sha256'])] if self._display_evidence is not None else Path(frame["image_path"]).read_bytes()
            self.canvas.set_image(data, self._target_link["target_boxes"],
                (self._target_link["program_id"], self._target_link["step_id"], frame["sha256"]))
            suffix = tr("；工作流仍引用它固定的界面版本") if not self._target_link["selected_version_matches"] else ""
            ui(self.status.setText, tr('学习动作截图 · 框绑定具体步骤规则 · 修改后须保存并重新审核') + suffix)
        else:
            loader = getattr(self.facade, "load_interface_content_evidence", None)
            if self._display_evidence is not None:
                data = self._display_evidence['image']
                if data is not None:
                    self.canvas.set_image(data, self._regions, (self._snapshot['interface_id'], self._snapshot.get('version_id', '')))
                else:
                    self.canvas.clear_canvas()
            elif callable(loader):
                evidence = loader(self._snapshot["interface_id"], self._snapshot.get("version_id"))
                self.canvas.set_image(self.facade._artifact_file(evidence["image_path"], "独立界面截图").read_bytes(),
                    self._regions, (self._snapshot["interface_id"], self._snapshot.get("version_id", "")))
            else:
                self.canvas.clear_canvas()
            ui(self.status.setText, tr('独立界面标注 · 保存生成新界面版本；工作流目标通过上方已学步骤入口修改。'))
        self._blank_selected()
        self._sync_buttons()

    def _open_target_rule(self):
        if self._target_link is not None and not self._dirty and not self._read_only and not self._loading and not self._load_failed:
            self.targetRuleRequested.emit(deepcopy(self._target_link))

    def review(self, application_binding: dict[str, Any] | None = None) -> None:
        if self._snapshot is None or self._read_only or self._loading or self._load_failed:
            return
        if self._dirty:
            self.errorRaised.emit(tr("请先保存界面修改，不能审核屏幕上尚未保存的内容。"))
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
        if self._snapshot is None or self._loading or self._load_failed:
            return
        if self._dirty:
            self.errorRaised.emit(tr("请先保存界面修改，再加入流程。"))
            return
        from .content_library import WorkflowCompositionDialog
        dialog = WorkflowCompositionDialog(self.facade, self._snapshot, self)
        dialog.exec()

    def open_relearning(self) -> None:
        if self._snapshot is None or self._dirty or self._read_only or self._loading or self._load_failed:
            return
        from .interface_relearning_dialog import InterfaceRelearningDialog
        dialog = InterfaceRelearningDialog(self.facade, self._snapshot,
                                            self._selected_region_id, self)
        dialog.adopted.connect(self._relearning_adopted)
        dialog.errorRaised.connect(self.errorRaised)
        dialog.exec()

    def _relearning_adopted(self, snapshot: dict[str, Any]) -> None:
        if self._dirty:
            self.errorRaised.emit(tr("界面已有未保存修改，未覆盖当前草稿；请先保存或放弃后再采用 Agent 修正。"))
            return
        self.set_snapshot(snapshot)
        self.saved.emit(deepcopy(snapshot))


__all__ = ["InterfaceReviewPane"]
