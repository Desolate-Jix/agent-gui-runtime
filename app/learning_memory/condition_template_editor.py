"""编辑已固定模板的参数；语义变化生成待审新修订，不修改原版本。"""
from copy import deepcopy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QToolButton, QVBoxLayout, QWidget

from app.judgment.condition_templates import make_record_id_template, resolve_condition_binding, validate_condition_binding
from .workbench_i18n import bind_text, tr, ui


class ConditionTemplateEditor(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._original = None
        self._inputs = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.enabled = ui(QCheckBox, tr("使用记录号条件模板"))
        layout.addWidget(self.enabled)
        self.body = QWidget()
        form = QFormLayout(self.body)
        form.setContentsMargins(0, 0, 0, 0)
        self.identity = QLabel()
        self.identity.setWordWrap(True)
        self.template_text = QPlainTextEdit()
        self.template_text.setMaximumHeight(76)
        self.minimum, self.maximum = QSpinBox(), QSpinBox()
        self.minimum.setRange(1, 4000)
        self.maximum.setRange(1, 4000)
        self.parameter_source = QComboBox()
        ui(self.parameter_source.addItem, tr("工作流输入"), "input")
        ui(self.parameter_source.addItem, tr("常量"), "literal")
        self.input_name = QComboBox()
        self.literal_value = QLineEdit()
        self.allowed_states = QPlainTextEdit()
        self.allowed_states.setMaximumHeight(64)
        ui(self.allowed_states.setPlaceholderText, tr("每行一个允许状态；留空表示不增加状态范围。"))
        self.review_policy = QComboBox()
        ui(self.review_policy.addItem, tr("自适应（不弱化宿主策略）"), "adaptive")
        ui(self.review_policy.addItem, tr("每步交主 Agent 审核（包括本地成功）"), "always_main")
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(92)
        for label, widget in (("模板版本", self.identity), ("记录号来源", self.parameter_source),
                ("输入名称", self.input_name), ("记录号常量", self.literal_value), ("条件预览", self.preview)):
            ui(form.addRow, tr(label), widget)
            ui(widget.setAccessibleName, tr(label))
        self.edit_rule = ui(QToolButton)
        ui(self.edit_rule.setText, tr("编辑模板规则（生成新版本）"))
        self.edit_rule.setCheckable(True)
        form.addRow(self.edit_rule)
        self.advanced = QWidget()
        advanced_form = QFormLayout(self.advanced)
        advanced_form.setContentsMargins(0, 0, 0, 0)
        for label, widget in (("模板规则（保留 {record_id}）", self.template_text),
                ("记录号最少字符", self.minimum), ("记录号最多字符", self.maximum),
                ("模板允许状态", self.allowed_states), ("模板审核策略", self.review_policy)):
            ui(advanced_form.addRow, tr(label), widget)
            ui(widget.setAccessibleName, tr(label))
        form.addRow(self.advanced)
        self.edit_rule.toggled.connect(self.advanced.setVisible)
        self.advanced.hide()
        note = ui(QLabel, tr("规则、范围或策略变化将生成新模板版本，保存后需重新审核并加入配置允许列表。"))
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(self.body)
        self.enabled.toggled.connect(self._change)
        for widget in (self.parameter_source, self.input_name, self.review_policy):
            widget.currentIndexChanged.connect(self._change)
        for widget in (self.template_text, self.allowed_states):
            widget.textChanged.connect(self._change)
        for widget in (self.minimum, self.maximum):
            widget.valueChanged.connect(self._change)
        self.literal_value.textChanged.connect(self._change)
        self.set_binding(None, [])

    def set_binding(self, binding, inputs):
        self._loading = True
        try:
            self._inputs = {item["name"]: "string" if item["type"] == "text" else item["type"] for item in inputs}
            display_inputs = dict(self._inputs)
            reference = (binding or {}).get("typed_parameters", {}).get("record_id", {})
            # 原绑定仍须展示供修订；实际声明的有效性由 value 阻止保存。
            if reference.get("source") == "input" and isinstance(reference.get("name"), str):
                display_inputs[reference["name"]] = "string"
            checked = validate_condition_binding(binding, input_types=display_inputs) if binding is not None else None
            self._original = deepcopy(checked)
            self.edit_rule.setChecked(False)
            template = checked["template"] if checked else make_record_id_template()
            self.enabled.setChecked(checked is not None)
            self.template_text.setPlainText(template["text_template"])
            self.minimum.setValue(template["parameters"]["record_id"]["min_length"])
            self.maximum.setValue(template["parameters"]["record_id"]["max_length"])
            self.allowed_states.setPlainText("\n".join(template["allowed_states"]))
            self.review_policy.setCurrentIndex(self.review_policy.findData(template["review_policy"]))
            self.input_name.clear()
            for name, kind in self._inputs.items():
                if kind == "string":
                    self.input_name.addItem(name, name)
            ref = checked["typed_parameters"]["record_id"] if checked else {"source": "input" if self.input_name.count() else "literal"}
            self.parameter_source.setCurrentIndex(self.parameter_source.findData(ref["source"]))
            if ref["source"] == "input" and "name" in ref:
                if self.input_name.findData(ref["name"]) < 0:
                    ui(self.input_name.addItem, tr("{name}（输入已缺失或类型不符）", name=ref["name"]), ref["name"])
                self.input_name.setCurrentIndex(self.input_name.findData(ref["name"]))
            self.literal_value.setText(ref.get("value", ""))
            self._loaded_text = self.template_text.toPlainText()
            self._loaded_states = self.allowed_states.toPlainText()
        finally:
            self._loading = False
        self._refresh()

    def value(self):
        if not self.enabled.isChecked():
            return None, None
        old = self._original["template"] if self._original else make_record_id_template()
        try:
            text, states = self.template_text.toPlainText(), self.allowed_states.toPlainText()
            args = {"condition_template_id": old["condition_template_id"], "revision": old["revision"],
                "text_template": old["text_template"] if self._original and text == self._loaded_text else text,
                "min_length": self.minimum.value(), "max_length": self.maximum.value(),
                "allowed_states": old["allowed_states"] if self._original and states == self._loaded_states else states.splitlines(),
                "review_policy": self.review_policy.currentData()}
            template = make_record_id_template(**args)
            if self._original and template != old:
                template = make_record_id_template(**{**args, "revision": old["revision"] + 1})
            reference = ({"source": "input", "name": self.input_name.currentData()}
                if self.parameter_source.currentData() == "input" else {"source": "literal", "value": self.literal_value.text()})
            binding = validate_condition_binding({"schema": "condition_binding.v1", "template": template,
                "typed_parameters": {"record_id": reference}}, input_types=self._inputs)
            if reference["source"] == "literal":
                resolve_condition_binding(binding, {})
            return binding, None
        except ValueError:
            return None, tr("请检查模板占位符、字符范围、允许状态和记录号来源。")

    def _refresh(self):
        self.body.setVisible(self.enabled.isChecked())
        input_source = self.parameter_source.currentData() == "input"
        self.input_name.setEnabled(input_source)
        self.literal_value.setEnabled(not input_source)
        value, error = self.value()
        if error:
            bind_text(self.preview, "setPlainText", error)
            bind_text(self.identity, "setText", tr("模板尚未通过校验"))
        elif value is not None:
            template = value["template"]
            bind_text(self.identity, "setText", tr("{name} · 修订 {revision} · {digest}", name=template["condition_template_id"],
                revision=template["revision"], digest=template["template_sha256"][:12] + "…"))
            self.identity.setToolTip(template["template_sha256"])
            if input_source:
                bind_text(self.preview, "setPlainText", tr("运行时取输入 {name} 的实际值：\n{rule}",
                    name=value["typed_parameters"]["record_id"]["name"], rule=template["text_template"]))
            else:
                self.preview.setPlainText(resolve_condition_binding(value, {})["condition"])
        else:
            self.preview.clear()
            self.identity.clear()

    def _change(self, *_args):
        if not self._loading:
            self._refresh()
            self.changed.emit()
