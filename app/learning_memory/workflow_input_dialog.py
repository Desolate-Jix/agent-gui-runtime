from __future__ import annotations
from app.learning_memory.workbench_i18n import ui, tr, bind_text, initialize_i18n, language_manager

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QScrollArea, QVBoxLayout, QWidget,
)


class WorkflowInputDialog(QDialog):
    def __init__(self, inputs: list[dict], parent=None):
        super().__init__(parent)
        ui(self.setWindowTitle, tr('本次运行参数'))
        self.resize(520, min(620, 180 + 48 * len(inputs)))
        self.setMinimumSize(420, 260)
        self._inputs = list(inputs)
        self._values: dict = {}
        self.editors: dict[str, QWidget] = {}

        root = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        form_widget = QWidget(scroll)
        form = QFormLayout(form_widget)
        for item in self._inputs:
            name = item["name"]
            kind = item["type"]
            if kind == "boolean":
                editor = QComboBox(form_widget)
                ui(editor.addItem, tr('未填写'), None)
                ui(editor.addItem, tr('是'), True)
                ui(editor.addItem, tr('否'), False)
            elif kind in {"text", "number"}:
                editor = QLineEdit(form_widget)
                ui(editor.setPlaceholderText, tr('必填') if item['required'] else tr('选填'))
            else:
                raise ValueError(f"unsupported workflow input type: {kind!r}")
            self.editors[name] = editor
            description = {'text': tr('文本'), 'number': tr('数字'), 'boolean': tr('是／否')}[kind]
            description += tr(" · 必填") if item["required"] else tr(" · 选填")
            label = ui(QLabel, tr("{name}\n{description}", name=name, description=description), form_widget)
            label.setWordWrap(True)
            label.setMaximumWidth(180)
            label.setBuddy(editor)
            ui(editor.setAccessibleName, tr("{name}, {description}", name=name, description=description))
            form.addRow(label, editor)
        scroll.setWidget(form_widget)
        root.addWidget(scroll, 1)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b42318;")
        root.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        ui(self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText, tr('确定'))
        ui(self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText, tr('取消'))
        root.addWidget(self.buttons)

    def values(self) -> dict:
        return dict(self._values) if self.result() == QDialog.DialogCode.Accepted else {}

    def accept(self):
        values = {}
        for item in self._inputs:
            name = item["name"]
            editor = self.editors[name]
            if item["type"] == "boolean":
                value = editor.currentData()
                if value is None:
                    if item["required"]:
                        self._reject_field(name, editor, tr("请选择是或否"))
                        return
                    continue
                values[name] = value
                continue

            raw = editor.text()
            if not raw.strip():
                if item["required"]:
                    self._reject_field(name, editor, tr("为必填项"))
                    return
                continue
            if item["type"] == "text":
                values[name] = raw
                continue
            try:
                number = float(raw)
            except ValueError:
                self._reject_field(name, editor, tr("必须为有限数字"))
                return
            if not math.isfinite(number):
                self._reject_field(name, editor, tr("必须为有限数字"))
                return
            values[name] = number

        self._values = values
        self.error_label.clear()
        super().accept()

    def _reject_field(self, name: str, editor: QWidget, reason: str):
        self._values = {}
        ui(self.error_label.setText, tr("{name} {reason}", name=name, reason=reason))
        editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def reject(self):
        self._values = {}
        super().reject()
