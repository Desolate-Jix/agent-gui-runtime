"""保存固定控件的局部模板；此面板不截图、不定位当前桌面、不点击。"""
from app.learning_memory.workbench_i18n import ui, tr, bind_text, initialize_i18n, language_manager
import hashlib
import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QVBoxLayout, QWidget)


def _local_error(error):
    raw = str(error)
    return tr(raw) if raw in {"模板图片在读取期间发生变化", "模板 PNG 无法显示"} else raw


class ControlTemplateDialog(QDialog):
    def __init__(self, facade, snapshot, selected_region_id=None, parent=None):
        super().__init__(parent)
        self.facade, self.snapshot = facade, snapshot
        ui(self.setWindowTitle, tr('局部截图模板 · 固定界面版本'))
        self.resize(900, 650)
        layout = QVBoxLayout(self)
        help_text = ui(QLabel, tr('选择已保存的识别框，将框和少量周边像素保存为定位模板。\n只读取学习原图，不采集当前桌面。执行时仍须匹配新截图；找不到或重复目标会明确返回。'))
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        form = QFormLayout()
        self.region = QComboBox()
        for row in snapshot["content"]["regions"]:
            self.region.addItem(row["name"] + " · " + row["region_id"], row["region_id"])
        index = self.region.findData(selected_region_id)
        if index >= 0:
            self.region.setCurrentIndex(index)
        self.padding = QSpinBox(); self.padding.setRange(0, 32); self.padding.setValue(6)
        self.radius = QSpinBox(); self.radius.setRange(0, 512); self.radius.setValue(80)
        bind_text(self.padding, 'setSuffix', " 像素"); bind_text(self.radius, 'setSuffix', " 像素")
        ui(form.addRow, tr('保存哪个框'), self.region)
        ui(form.addRow, tr('周边留白'), self.padding)
        ui(form.addRow, tr('原位置附近搜索半径'), self.radius)
        layout.addLayout(form)
        controls = QHBoxLayout()
        save = ui(QPushButton, tr('保存局部模板'))
        save.setEnabled(self.region.count() > 0)
        save.clicked.connect(self.save)
        refresh = ui(QPushButton, tr('刷新此版本模板'))
        refresh.clicked.connect(self.refresh)
        controls.addWidget(save); controls.addWidget(refresh); controls.addStretch()
        layout.addLayout(controls)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.items = QListWidget()
        self.items.currentItemChanged.connect(self.preview)
        split.addWidget(self.items)
        preview = QWidget(); preview_layout = QVBoxLayout(preview)
        self.image = ui(QLabel, tr('选择模板查看原始像素'))
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll = QScrollArea(); scroll.setWidget(self.image); scroll.setWidgetResizable(True)
        preview_layout.addWidget(scroll, 1)
        self.details = QPlainTextEdit(); self.details.setReadOnly(True)
        self.details.setMaximumHeight(190)
        preview_layout.addWidget(self.details)
        split.addWidget(preview); split.setSizes([290, 580])
        layout.addWidget(split, 1)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.refresh()

    def refresh(self, select_id=None):
        self.items.clear()
        try:
            rows = self.facade.list_control_templates(self.snapshot["interface_id"], self.snapshot["version_id"])["templates"]
            ui(self.status.setText, tr('当前固定版本共有 {v0} 个模板；修改界面产生新版本后需明确另存模板。', v0=len(rows)))
            for row in rows:
                item = QListWidgetItem(row["label"] + " · " + row["template_id"][-8:])
                item.setData(Qt.ItemDataRole.UserRole, row["template_id"])
                self.items.addItem(item)
                if row["template_id"] == select_id:
                    self.items.setCurrentItem(item)
        except Exception as error:
            ui(self.status.setText, tr('读取失败：') + str(error))

    def save(self):
        try:
            value = self.facade.save_control_template({"action": "save",
                "interface_id": self.snapshot["interface_id"], "version_id": self.snapshot["version_id"],
                "region_id": self.region.currentData(), "padding": self.padding.value(), "radius": self.radius.value()})
            self.refresh(value["template_id"])
        except Exception as error:
            ui(self.status.setText, tr('保存失败：') + str(error))

    def preview(self, current, previous=None):
        self.image.clear(); self.image.setMinimumSize(0, 0); self.details.clear()
        if current is None:
            return
        try:
            value = self.facade.load_control_template_evidence(current.data(Qt.ItemDataRole.UserRole))
            raw = self.facade._artifact_file(value["image_path"], "局部模板").read_bytes()
            if hashlib.sha256(raw).hexdigest() != value["png_sha256"]:
                raise ValueError("模板图片在读取期间发生变化")
            image = QPixmap()
            if not image.loadFromData(raw, "PNG"):
                raise ValueError("模板 PNG 无法显示")
            self.image.setPixmap(image)
            self.image.setMinimumSize(image.size())
            fields = {key: value[key] for key in ("template_id", "interface_id", "version_id",
                "region_id", "interface_key", "state_key", "crop_bbox", "radius", "png_sha256")}
            self.details.setPlainText(json.dumps(fields, ensure_ascii=False, indent=2))
        except Exception as error:
            ui(self.status.setText, tr('预览失败：') + _local_error(error))
