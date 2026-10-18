"""可选的已学结果原图与稳定区域编辑器。"""
from copy import deepcopy
import hashlib
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QCheckBox,
    QComboBox, QLabel, QDoubleSpinBox, QSpinBox, QHBoxLayout, QPushButton)
from app.desktop_review.canvas import ReviewCanvas
from .workbench_i18n import ui, tr


class WorkflowImageCheckEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._config = None
        self._eligible = True
        self._options = []
        root = QVBoxLayout(self)
        self.enabled = QCheckBox(); ui(self.enabled.setText, tr('本地图像核验（可选）'))
        root.addWidget(self.enabled)
        root.addWidget(ui(QLabel, tr('不匹配时由 Agent 审核')))
        self.source = QComboBox(); root.addWidget(self.source)
        self.status = QLabel(); self.status.setWordWrap(True); root.addWidget(self.status)
        self.canvas = ReviewCanvas(); self.canvas.setMinimumHeight(180); root.addWidget(self.canvas)
        form = QFormLayout(); self.boxes = {}; self._region_buttons = []
        for key, label in (('template_bbox', '稳定模板区域'), ('search_roi', '搜索区域')):
            row = QWidget(); layout = QHBoxLayout(row); layout.setContentsMargins(0, 0, 0, 0)
            fields = []
            for axis in ('x', 'y', 'w', 'h'):
                spin = QSpinBox(); spin.setRange(0, 100000); spin.setPrefix(axis + ': ')
                layout.addWidget(spin); fields.append(spin)
                spin.valueChanged.connect(lambda _value, key=key: self._box_changed(key))
            button = QPushButton(); ui(button.setText, tr('在原图中调整'))
            self._region_buttons.append(button)
            button.clicked.connect(lambda _checked=False, key=key: self._select_box(key))
            layout.addWidget(button); self.boxes[key] = fields
            ui(form.addRow, tr(label), row)
        self.threshold = QDoubleSpinBox(); self.threshold.setRange(.5, 1); self.threshold.setDecimals(3)
        self.threshold.setSingleStep(.01); self.threshold.setValue(.95)
        ui(form.addRow, tr('匹配阈值'), self.threshold); root.addLayout(form)
        self.enabled.toggled.connect(self._changed)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.threshold.valueChanged.connect(self._changed)
        self.canvas.regionGeometryChanged.connect(self._geometry_changed)
        self.set_config(None, True)

    def _changed(self, *_args):
        self.source.setEnabled(self.enabled.isChecked() and self._eligible)
        self.canvas.setEnabled(self.enabled.isChecked() and self._eligible)
        self.threshold.setEnabled(self.enabled.isChecked() and self._eligible)
        for button in self._region_buttons:
            button.setEnabled(self.enabled.isChecked() and self._eligible)
        for fields in self.boxes.values():
            for field in fields:
                field.setEnabled(self.enabled.isChecked() and self._eligible)
        if not self._loading:
            self.changed.emit()

    def set_config(self, config, eligible):
        self._loading = True
        self._config = deepcopy(config)
        self._eligible = eligible
        self.enabled.setChecked(config is not None)
        self.enabled.setEnabled(eligible)
        self.threshold.setValue((config or {}).get('threshold', .95))
        for key in self.boxes:
            self.set_box(key, (config or {}).get(key, [0, 0, 0, 0]))
        self.set_options([])
        self._loading = False
        self._changed()

    def set_eligible(self, eligible):
        self._eligible = eligible
        self.enabled.setEnabled(eligible)
        self.source.setEnabled(self.enabled.isChecked() and eligible)
        self.canvas.setEnabled(self.enabled.isChecked() and eligible)
        self.threshold.setEnabled(self.enabled.isChecked() and eligible)
        for button in self._region_buttons:
            button.setEnabled(self.enabled.isChecked() and eligible)
        for fields in self.boxes.values():
            for field in fields:
                field.setEnabled(self.enabled.isChecked() and eligible)

    def set_options(self, options):
        loading = self._loading; self._loading = True
        self._options = deepcopy(options)
        self.source.clear(); ui(self.source.addItem, tr('请选择已学结果原图'), None)
        for option in options:
            self.source.addItem(option['label'], option)
        match = next((i + 1 for i, option in enumerate(options)
                      if self._config and option['reference_sha256'] == self._config.get('reference_sha256')), 0)
        self.source.setCurrentIndex(match)
        self._preview()
        self._loading = loading

    def _source_changed(self, *_args):
        if not self._loading:
            option = self.source.currentData()
            if option:
                self._config = {'contract_version': 'workflow_image_check.v1',
                    'reference_sha256': option['reference_sha256'], 'reference_size': option['reference_size']}
                for key in self.boxes:
                    self.set_box(key, [0, 0, 0, 0])
            self._preview(); self._changed()

    def _preview(self):
        self.canvas.clear_canvas()
        option = self.source.currentData()
        if not option:
            ui(self.status.setText, tr('原图不可用；已有配置保留，运行时由 Agent 审核。') if self._config else tr('请选择原图并指定稳定区域。'))
            return
        try:
            raw = Path(option['image_path']).read_bytes()
            image = QImage.fromData(raw, 'PNG')
            if image.isNull() or hashlib.sha256(raw).hexdigest() != option['reference_sha256'] or [image.width(), image.height()] != option['reference_size']:
                raise ValueError('image evidence mismatch')
            regions = [{'region_id': key, 'bbox': self.box(key)} for key in self.boxes if self._valid_box(self.box(key), option['reference_size'])]
            self.canvas.set_image(raw, regions, (option['reference_sha256'],))
            ui(self.status.setText, tr('拖动区域或调整 x、y、w、h；避开变化内容。'))
        except (OSError, ValueError):
            ui(self.status.setText, tr('原图不可用；已有配置保留，运行时由 Agent 审核。'))

    def box(self, key):
        return [field.value() for field in self.boxes[key]]

    def set_box(self, key, value):
        for field, number in zip(self.boxes[key], value):
            field.blockSignals(True); field.setValue(int(number)); field.blockSignals(False)
        self._box_changed(key)

    def _box_changed(self, key):
        box = self.box(key)
        if self._config and self._valid_box(box, self._config['reference_size']):
            self.canvas.add_region(key, box); self.canvas.set_region_bbox(key, box)
        self._changed()

    def _geometry_changed(self, key, box):
        if key in self.boxes:
            self.set_box(key, box)

    def _select_box(self, key):
        if self._config and self.source.currentData():
            if not self._valid_box(self.box(key), self._config['reference_size']):
                width, height = self._config['reference_size']
                self.set_box(key, [width // 4, height // 4, max(1, width // 4), max(1, height // 4)])
            self.canvas.select_region(key)

    @staticmethod
    def _valid_box(box, size):
        x, y, width, height = box
        return width > 0 and height > 0 and x >= 0 and y >= 0 and x + width <= size[0] and y + height <= size[1]

    def value(self):
        if not self.enabled.isChecked():
            return None, None
        if not self._eligible:
            return None, tr('读取或输出步骤不能启用图像核验。')
        if not self._config:
            return None, tr('请选择原图并指定稳定区域。')
        value = deepcopy(self._config)
        for key in self.boxes:
            value[key] = self.box(key)
            if not self._valid_box(value[key], value['reference_size']):
                return None, tr('模板与搜索区域必须在原图内且具有有效大小。')
        value['threshold'] = self.threshold.value()
        if any(value['template_bbox'][i] > value['search_roi'][i] for i in (2, 3)):
            return None, tr('模板与搜索区域必须在原图内且具有有效大小。')
        return value, None
