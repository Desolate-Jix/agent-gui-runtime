"""有限结果与读取规则的结构化编辑控件。"""

from __future__ import annotations
from app.learning_memory.workbench_i18n import ui, tr, bind_text, initialize_i18n, language_manager

from copy import deepcopy
import math
import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget
from .workflow_image_check_editor import WorkflowImageCheckEditor


_VERIFY_KINDS = ((tr('无结果规则'), None), (tr('字段等于'), 'field_equals'), (tr('文本等于'), 'text_equals'), (tr('文本包含'), 'text_contains'), (tr('目标存在'), 'target_present'), (tr('目标不存在'), 'target_absent'), (tr('Agent 判断'), 'agent_judgment'))
_READ_METHODS = ((tr('无读取规则'), None), (tr('控件值'), 'uia_value'), (tr('可见文字'), 'visible_text'), (tr('Agent 读取'), 'agent_read'))
_SOURCES = ((tr('常量'), 'constant'), (tr('工作流输入'), 'input'), (tr('本次上游输出'), 'output'))
_TYPES = ((tr('文本'), 'text'), (tr('数字'), 'number'), (tr('是／否'), 'boolean'))


def _choice(combo, value):
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


def _target(control_type, name, automation_id):
    value = {"control_type": control_type.strip()}
    if name.strip():
        value["name"] = name.strip()
    if automation_id.strip():
        value["automation_id"] = automation_id.strip()
    return value


class WorkflowRulesEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._modified = False
        self._original_verification = None
        self._original_read = None
        self.validation_error = None
        self._input_names = []
        self._outputs_by_step = {}
        self._action_kind = None
        self._image_step_eligible = True
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(ui(QLabel, tr('结果判断与当次读取只使用当前运行的证据。')))
        form = QFormLayout()
        self.verification_kind = QComboBox()
        for label, value in _VERIFY_KINDS:
            ui(self.verification_kind.addItem, tr(label), value)
        self.target_type = QLineEdit(); ui(self.target_type.setPlaceholderText, tr('例如 Text'))
        self.target_name = QLineEdit(); ui(self.target_name.setPlaceholderText, tr('可见控件名称'))
        self.target_automation_id = QLineEdit(); ui(self.target_automation_id.setPlaceholderText, tr('可选的 AutomationId'))
        self.expected_source = QComboBox()
        for label, value in _SOURCES:
            ui(self.expected_source.addItem, tr(label), value)
        self.expected_type = QComboBox()
        for label, value in _TYPES:
            ui(self.expected_type.addItem, tr(label), value)
        self.expected_value = QLineEdit()
        self.expected_name = QComboBox(); self.expected_name.setEditable(True)
        self.expected_step = QComboBox(); self.expected_step.setEditable(True)
        self.verification_output = QComboBox(); self.verification_output.setEditable(True)
        self.read_method = QComboBox()
        for label, value in _READ_METHODS:
            ui(self.read_method.addItem, tr(label), value)
        self.read_output = QComboBox(); self.read_output.setEditable(True)
        for label, widget in (("结果规则", self.verification_kind), ("控件类型", self.target_type),
                              ("控件名称", self.target_name), ("AutomationId", self.target_automation_id),
                              ("预期值来源", self.expected_source), ("常量类型", self.expected_type),
                              ("常量值", self.expected_value), ("输入／输出名称", self.expected_name),
                              ("上游步骤", self.expected_step), ("结果写入输出", self.verification_output),
                              ("读取方式（仅读取文本步骤）", self.read_method),
                              ("读取写入输出", self.read_output)):
            ui(form.addRow, tr(label), widget)
        root.addLayout(form)
        self.image_check_editor = WorkflowImageCheckEditor()
        form.insertRow(1, self.image_check_editor)
        self.image_check_editor.changed.connect(self._mark_modified)
        root.addStretch()
        for widget in (self.verification_kind, self.expected_source, self.expected_type, self.read_method):
            widget.currentIndexChanged.connect(self._mark_modified)
        for widget in (self.target_type, self.target_name, self.target_automation_id, self.expected_value):
            widget.textChanged.connect(self._mark_modified)
        for widget in (self.expected_name, self.expected_step, self.verification_output, self.read_output):
            widget.currentTextChanged.connect(self._mark_modified)
        self.verification_kind.currentIndexChanged.connect(self._update_fields)
        self.expected_source.currentIndexChanged.connect(self._update_fields)
        self.expected_source.currentIndexChanged.connect(self._refresh_expected_names)
        self.expected_step.currentIndexChanged.connect(self._refresh_expected_names)
        self.expected_step.currentTextChanged.connect(self._refresh_expected_names)
        self.read_method.currentIndexChanged.connect(self._update_fields)
        self._update_fields()

    def _mark_modified(self, *_args):
        if not self._loading:
            self._modified = True
            self.changed.emit()

    def _update_fields(self, *_args):
        kind = self.verification_kind.currentData()
        expected = kind in {"field_equals", "text_equals", "text_contains"}
        source = self.expected_source.currentData()
        target_enabled = kind not in {None, "agent_judgment"} or (
            self._action_kind == "read_text" and self.read_method.currentData() is not None)
        for widget in (self.target_type, self.target_name, self.target_automation_id):
            widget.setEnabled(target_enabled)
        self.expected_source.setEnabled(expected)
        self.expected_type.setEnabled(expected and source == "constant")
        self.expected_value.setEnabled(expected and source == "constant")
        self.expected_name.setEnabled(expected and source in {"input", "output"})
        self.expected_step.setEnabled(expected and source == "output")
        self.verification_output.setEnabled(kind not in {None, "agent_judgment"})

    def set_action_kind(self, kind):
        self._action_kind = kind
        self.read_method.setEnabled(kind == "read_text")
        self.read_output.setEnabled(kind == "read_text")
        self._update_fields()
        self.image_check_editor.set_eligible(self._image_step_eligible and kind != 'read_text')

    def set_image_options(self, options):
        self.image_check_editor.set_options(options)

    def _selected_step_id(self):
        index = self.expected_step.currentIndex()
        typed = self.expected_step.currentText().strip()
        return self.expected_step.itemData(index) if index >= 0 and typed == self.expected_step.itemText(index) else typed

    def _refresh_expected_names(self, *_args):
        if self._loading:
            return
        old = self.expected_name.currentText()
        source = self.expected_source.currentData()
        names = self._input_names if source == "input" else self._outputs_by_step.get(self._selected_step_id(), []) if source == "output" else []
        self.expected_name.blockSignals(True)
        self.expected_name.clear()
        for name in names:
            self.expected_name.addItem(name)
        self.expected_name.setCurrentText(old)
        self.expected_name.blockSignals(False)

    def set_step(self, step, definition, index):
        self._loading = True
        self._original_verification = deepcopy(step.get("verification")) if step else None
        self._original_read = deepcopy(step.get("read_spec")) if step else None
        self.validation_error = None
        verification = self._original_verification or {}
        self._image_step_eligible = not bool((step or {}).get('outputs') or (step or {}).get('read_spec'))
        self.image_check_editor.set_config(verification.get('image_check'),
            self._image_step_eligible and (step or {}).get('action', {}).get('kind') != 'read_text')
        read_spec = self._original_read or {}
        _choice(self.verification_kind, verification.get("kind"))
        target = verification.get("target") or read_spec.get("target") or {}
        self.target_type.setText(target.get("control_type", ""))
        self.target_name.setText(target.get("name", ""))
        self.target_automation_id.setText(target.get("automation_id", ""))
        expected = verification.get("expected") or {"source": "constant", "value": ""}
        _choice(self.expected_source, expected.get("source"))
        value = expected.get("value", "")
        _choice(self.expected_type, "boolean" if type(value) is bool else "number" if type(value) in (int, float) else "text")
        self.expected_value.setText(str(value).lower() if type(value) is bool else str(value))
        self.expected_name.clear(); self.expected_step.clear()
        self.verification_output.clear(); self.read_output.clear()
        self._input_names = []
        self._outputs_by_step = {}
        if definition is not None and step is not None:
            for item in definition.get("inputs", []):
                self._input_names.append(item["name"])
            for prior in definition.get("steps", [])[:index]:
                self.expected_step.addItem(prior["title"], prior["step_id"])
                self._outputs_by_step[prior["step_id"]] = [item["name"] for item in prior.get("outputs", [])]
            for item in step.get("outputs", []):
                self.verification_output.addItem(item["name"])
                self.read_output.addItem(item["name"])
        previous_step = expected.get("step_id")
        if previous_step is not None:
            selected_index = self.expected_step.findData(previous_step)
            if selected_index >= 0:
                self.expected_step.setCurrentIndex(selected_index)
            else:
                self.expected_step.setCurrentText(previous_step)
        source = self.expected_source.currentData()
        names = self._input_names if source == "input" else self._outputs_by_step.get(self._selected_step_id(), []) if source == "output" else []
        for name in names:
            self.expected_name.addItem(name)
        self.expected_name.setCurrentText(expected.get("name", ""))
        self.verification_output.setCurrentText(verification.get("output_name", ""))
        self.read_output.setCurrentText(read_spec.get("output_name", ""))
        _choice(self.read_method, read_spec.get("method"))
        self.set_action_kind((step or {}).get("action", {}).get("kind"))
        self._update_fields()
        self._modified = False
        self._loading = False
        self.setEnabled(step is not None)

    def rules(self, action_kind):
        self.validation_error = None
        self.image_check_editor.set_eligible(self._image_step_eligible and action_kind != 'read_text')
        _image_value, image_error = self.image_check_editor.value()
        if image_error:
            self.validation_error = image_error
        if not self._modified:
            return deepcopy(self._original_verification), deepcopy(self._original_read) if action_kind == "read_text" else None
        kind = self.verification_kind.currentData()
        target = _target(self.target_type.text(), self.target_name.text(), self.target_automation_id.text())
        verification = None
        if kind is not None:
            verification = {"kind": kind}
            if kind != "agent_judgment":
                verification["target"] = deepcopy(target)
            if kind in {"field_equals", "text_equals", "text_contains"}:
                source = self.expected_source.currentData()
                if source == "constant":
                    raw = self.expected_value.text()
                    typ = self.expected_type.currentData()
                    if typ == "boolean":
                        if raw.lower() not in {"true", "false", "是", "否", "1", "0"}:
                            self.validation_error = tr("是／否常量只能填 是、否、true、false、1 或 0。")
                            value = raw
                        else:
                            value = raw.lower() in {"true", "是", "1"}
                    elif typ == "number":
                        try:
                            value = int(raw) if re.fullmatch(r"[+-]?\d+", raw.strip()) else float(raw)
                            if not math.isfinite(value):
                                raise ValueError("nonfinite")
                        except ValueError:
                            self.validation_error = tr("数字常量必须是有限的有效数字。")
                            value = raw
                    else:
                        value = raw
                    verification["expected"] = {"source": "constant", "value": value}
                elif source == "input":
                    verification["expected"] = {"source": "input", "name": self.expected_name.currentText().strip()}
                else:
                    verification["expected"] = {"source": "output", "step_id": self._selected_step_id(),
                                                "name": self.expected_name.currentText().strip()}
            output = self.verification_output.currentText().strip()
            if output and kind != "agent_judgment":
                verification["output_name"] = output
        method = self.read_method.currentData() if action_kind == "read_text" else None
        read_spec = {"method": method, "target": deepcopy(target),
                     "output_name": self.read_output.currentText().strip()} if method else None
        image_check, image_error = self.image_check_editor.value()
        if image_error:
            self.validation_error = image_error
        elif image_check is not None:
            if kind not in {None, 'agent_judgment'}:
                self.validation_error = tr('图像核验必须使用 Agent 判断结果规则。')
            else:
                verification = {'kind': 'agent_judgment', 'image_check': image_check}
        if (verification is not None and verification.get("kind") == "agent_judgment"
                and "decision_condition" in (self._original_verification or {})):
            # 修改图像规则不应静默丢弃已声明的语义核验条件。
            verification["decision_condition"] = self._original_verification["decision_condition"]
        return verification, read_spec


__all__ = ["WorkflowRulesEditor"]
