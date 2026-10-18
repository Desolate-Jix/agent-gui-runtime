"""从固定学习证据编辑有限目标规则；预览和采用均不派发真实输入。"""
from __future__ import annotations
from app.learning_memory.workbench_i18n import ui, tr, bind_text, initialize_i18n, language_manager

from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout, QWidget)

from app.desktop_review.jobs import make_job
from app.desktop_review.canvas import ReviewCanvas


_ROW_TYPES = {"Group", "Pane", "ListItem", "DataItem"}
_CLICK_TYPES = {"Button", "Hyperlink", "MenuItem", "ListItem", "DataItem", "CheckBox", "RadioButton", "TabItem"}
_INPUT_TYPES = {"Edit", "ComboBox"}


def _selector(control, *, include_id=True):
    result = {"control_type": control["control_type"]}
    if control.get("source") in {"row", "row_name"}:
        return {"source": control["source"], **result}
    if control.get("name"):
        result["name"] = control["name"]
    if include_id and control.get("automation_id"):
        result["automation_id"] = control["automation_id"]
    return result


def _label(control):
    return tr('{name} · {kind}{identity}', name=control.get('name') or tr('（无名称）'),
              kind=control.get('control_type', '?'),
              identity=f" · {control['automation_id']}" if control.get("automation_id") else "")


class WorkflowTargetEditor(QWidget):
    proposalReady = Signal(object)
    busyChanged = Signal(bool)
    changed = Signal()

    def __init__(self, facade, parent=None):
        super().__init__(parent)
        self.facade = facade
        self.action_provider = None
        self._step = None
        self._definition = None
        self._reference = None
        self._proposed_recipe = None
        self._context = None
        self._jobs = {}
        self._outcomes = {}
        self._sequence = 0
        self._active_request = None
        self._closing = False
        self._preview_key = None
        self._preview_result = None
        self._updating = False
        self._has_unapplied_changes = False
        self._missing_binding_value = None
        self._strategies = []
        self._samples = []
        self._active_strategy = 0
        self._active_condition = 0
        self._form_rule_dirty = False
        self._pending_box = None

        layout = QVBoxLayout(self)
        self.note = ui(QLabel, tr('学习截图匹配，不代表当前实机已验证。'))
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.load_button = ui(QPushButton, tr('读取学习证据'))
        self.load_button.clicked.connect(self.load_evidence)
        layout.addWidget(self.load_button)
        self.canvas = ReviewCanvas()
        self.canvas.setObjectName("workflowTargetCanvas")
        self.canvas.setMinimumSize(320, 190)
        self.canvas.setMaximumHeight(280)
        self.canvas.regionSelected.connect(self._box_selected)
        self.canvas.regionGeometryChanged.connect(self._box_moved)
        layout.addWidget(self.canvas, 1)
        self.box_help = ui(QLabel, tr('点击学习框选择规则；移动框选择另一明确控件，框将贴合该控件边界。'))
        self.box_help.setWordWrap(True)
        layout.addWidget(self.box_help)

        form = QFormLayout()
        self._form = form
        self.strategy_choice = QComboBox()
        ui(form.addRow, tr('策略顺序'), self.strategy_choice)
        strategy_buttons = QHBoxLayout()
        self.strategy_add = ui(QPushButton, tr('新增策略'))
        self.strategy_up = ui(QPushButton, tr('上移'))
        self.strategy_down = ui(QPushButton, tr('下移'))
        self.strategy_delete = ui(QPushButton, tr('删除策略'))
        for button in (self.strategy_add, self.strategy_up, self.strategy_down, self.strategy_delete):
            strategy_buttons.addWidget(button)
        layout.addLayout(strategy_buttons)
        self.mode = QComboBox()
        ui(self.mode.addItem, tr('固定控件'), 'uia')
        ui(self.mode.addItem, tr('当前可见唯一行'), 'visible_row')
        ui(form.addRow, tr('定位方式'), self.mode)
        self.fixed_control = QComboBox()
        ui(form.addRow, tr('目标控件'), self.fixed_control)
        self.container = QComboBox()
        ui(form.addRow, tr('列表容器'), self.container)
        self.row_type = QComboBox()
        for kind in sorted(_ROW_TYPES):
            self.row_type.addItem(kind, kind)
        ui(form.addRow, tr('行类型'), self.row_type)
        self.property_control = QComboBox()
        self.property_source = QComboBox()
        ui(self.property_source.addItem, tr('行内文字控件'), 'descendant')
        ui(self.property_source.addItem, tr('行自身名称'), 'row')
        ui(form.addRow, tr('属性读取位置'), self.property_source)
        ui(form.addRow, tr('属性控件'), self.property_control)
        self.property_id_required = ui(QCheckBox, tr('限定所选属性的固定 ID'))
        self.property_id_required.setChecked(True)
        ui(self.property_id_required.setToolTip, tr('记录不同导致 ID 改变时可取消；每行仍必须恰有一个文字属性，否则拒绝。'))
        form.addRow(self.property_id_required)
        self.condition_choice = QComboBox()
        ui(form.addRow, tr('行匹配条件'), self.condition_choice)
        condition_buttons = QHBoxLayout()
        self.condition_add = ui(QPushButton, tr('新增条件'))
        self.condition_delete = ui(QPushButton, tr('删除条件'))
        condition_buttons.addWidget(self.condition_add)
        condition_buttons.addWidget(self.condition_delete)
        layout.addLayout(condition_buttons)
        self.row_action = QComboBox()
        self.action_source = QComboBox()
        ui(self.action_source.addItem, tr('行内动作控件'), 'descendant')
        ui(self.action_source.addItem, tr('整行中心（须实机核验）'), 'row')
        ui(self.action_source.addItem, tr('行名称控件'), 'row_name')
        ui(form.addRow, tr('动作位置'), self.action_source)
        ui(form.addRow, tr('行内动作控件'), self.row_action)
        self.action_id_required = ui(QCheckBox, tr('限定所选动作的固定 ID'))
        self.action_id_required.setChecked(True)
        ui(self.action_id_required.setToolTip, tr('取消后按每行内的名称和类型匹配；动作必须唯一，否则拒绝。'))
        form.addRow(self.action_id_required)
        self.operator = QComboBox()
        ui(self.operator.addItem, tr('等于'), 'eq')
        ui(self.operator.addItem, tr('包含'), 'contains')
        ui(form.addRow, tr('匹配条件'), self.operator)
        self.value_source = QComboBox()
        ui(self.value_source.addItem, tr('固定值'), 'constant')
        ui(self.value_source.addItem, tr('任务输入'), 'input')
        ui(self.value_source.addItem, tr('前序输出'), 'output')
        ui(form.addRow, tr('值来源'), self.value_source)
        self.constant = QLineEdit()
        ui(form.addRow, tr('固定值'), self.constant)
        self.binding = QComboBox()
        ui(form.addRow, tr('已声明变量'), self.binding)
        self.sample = QLineEdit()
        ui(self.sample.setPlaceholderText, tr('仅供本次预览，不保存为参数值'))
        ui(form.addRow, tr('预览样例值'), self.sample)
        layout.addLayout(form)

        buttons = QHBoxLayout()
        self.preview_button = ui(QPushButton, tr('预览学习截图匹配'))
        self.apply_button = ui(QPushButton, tr('应用目标修订'))
        self.preview_button.clicked.connect(self.preview)
        self.apply_button.clicked.connect(self.apply)
        buttons.addWidget(self.preview_button)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)
        self.status = ui(QLabel, tr('选择带目标记忆的步骤后读取学习证据。'))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        for widget in (self.mode, self.fixed_control, self.container, self.row_type,
                       self.property_control, self.row_action, self.property_source, self.action_source, self.operator, self.value_source,
                       self.binding):
            widget.currentIndexChanged.connect(self._changed)
        for widget in (self.constant, self.sample):
            widget.textChanged.connect(self._changed)
        for widget in (self.property_id_required, self.action_id_required):
            widget.toggled.connect(self._changed)
        self.strategy_choice.currentIndexChanged.connect(self._switch_strategy)
        self.condition_choice.currentIndexChanged.connect(self._switch_condition)
        self.strategy_add.clicked.connect(self._add_strategy)
        self.strategy_up.clicked.connect(lambda: self._move_strategy(-1))
        self.strategy_down.clicked.connect(lambda: self._move_strategy(1))
        self.strategy_delete.clicked.connect(self._delete_strategy)
        self.condition_add.clicked.connect(self._add_condition)
        self.condition_delete.clicked.connect(self._delete_condition)
        self._sync()

    @property
    def is_busy(self):
        return bool(self._jobs)

    @property
    def has_unapplied_changes(self):
        return self._has_unapplied_changes

    def set_step(self, step, definition, proposed_recipes=None):
        self.cancel_loading()
        self._closing = False
        self._step = deepcopy(step) if isinstance(step, dict) else None
        self._definition = deepcopy(definition) if isinstance(definition, dict) else None
        action = self._step.get("action", {}) if self._step else {}
        self._reference = deepcopy(action.get("target_memory"))
        self._proposed_recipe = None
        for row in proposed_recipes or []:
            recipe = row.get("recipe", row) if isinstance(row, dict) else None
            if isinstance(recipe, dict) and isinstance(self._reference, dict) and recipe.get("recipe_id") == self._reference.get("recipe_id"):
                self._proposed_recipe = deepcopy(recipe)
                break
        self._context = None
        self._strategies = []
        self._samples = []
        self._active_strategy = 0
        self._active_condition = 0
        self._form_rule_dirty = False
        self._pending_box = None
        self._has_unapplied_changes = False
        self._missing_binding_value = None
        self._updating = True
        try:
            self.strategy_choice.clear()
            self.condition_choice.clear()
            self.property_id_required.setChecked(True)
            self.action_id_required.setChecked(True)
        finally:
            self._updating = False
        self._invalidate_preview()
        self.canvas.clear_canvas()
        ui(self.status.setText, tr('可读取学习证据。') if self._reference else tr('当前步骤没有目标记忆。'))
        self._sync()

    def refresh_definition(self, definition):
        """刷新变量声明，保留当前目标编辑和已选变量。"""
        self._definition = deepcopy(definition) if isinstance(definition, dict) else None
        if not self._context:
            return
        was_missing = self._missing_binding_value is not None
        self._updating = True
        try:
            self._populate_bindings()
        finally:
            self._updating = False
        self._invalidate_preview()
        if self._missing_binding_value is not None or self._any_missing_binding():
            ui(self.status.setText, tr('所选变量已不在工作流声明中，请重新选择。'))
            if not self._has_unapplied_changes:
                self._has_unapplied_changes = True
                self.changed.emit()
        elif was_missing:
            ui(self.status.setText, tr('变量已恢复；请重新预览学习截图匹配。'))
        self._sync()

    def cancel_loading(self):
        self._active_request = None
        self._sequence += 1
        self._closing = True
        self._sync()

    def closeEvent(self, event):
        self.cancel_loading()
        super().closeEvent(event)

    def _start(self, operation, call, key=None):
        if self.is_busy:
            return
        self._sequence += 1
        request = self._sequence
        self._active_request = request
        job = make_job(request, call, self)
        self._jobs[request] = (job, operation, key)
        job.succeeded.connect(self._succeeded)
        job.failed.connect(self._failed)
        job.finished.connect(self._job_finished)
        ui(self.status.setText, tr('正在读取学习证据…') if operation == 'load' else tr('正在匹配归档截图…'))
        self._sync()
        self.busyChanged.emit(True)
        job.start()

    @Slot(int, object)
    def _succeeded(self, request, value):
        self._outcomes[request] = (True, value)

    @Slot(int, str)
    def _failed(self, request, error):
        self._outcomes[request] = (False, error)

    @Slot()
    def _job_finished(self):
        request = self.sender().request_id
        job, operation, key = self._jobs.pop(request)
        ok, value = self._outcomes.pop(request, (False, "后台任务未返回结果"))
        job.succeeded.disconnect(self._succeeded)
        job.failed.disconnect(self._failed)
        job.finished.disconnect(self._job_finished)
        job.deleteLater()
        if request == self._active_request and not self._closing:
            self._active_request = None
            if not ok:
                if operation == "box":
                    self._paint(None)
                self._show_status("读取失败：" if operation == "load" else "匹配失败：", value)
            elif operation == "load":
                self._install_context(value)
            elif operation == "box":
                try:
                    current = self._request_key()
                except ValueError:
                    current = None
                if key == current:
                    self._install_box_proposal(value)
                else:
                    self._paint(None)
                    ui(self.status.setText, tr('编辑内容已变化，请重新选择目标框。'))
            else:
                try:
                    current = self._request_key()
                except ValueError:
                    current = None
                if key == current:
                    self._preview_result = deepcopy(value)
                    self._preview_key = key
                    self._show_preview(value)
                else:
                    ui(self.status.setText, tr('编辑内容已变化，请重新预览。'))
        self._sync()
        self.busyChanged.emit(self.is_busy)
        if operation == "load" and self._pending_box is not None and self._context is not None:
            index, bbox = self._pending_box
            self._pending_box = None
            self.request_box_edit(index, bbox)

    def _show_status(self, prefix, reason):
        raw = str(reason).splitlines()[0]
        messages = {
            "target_edit_action_observation_unsupported": "旧版规则缺少动作控件证据，无法编辑。",
            "target_edit_control_missing": "学习证据中未找到目标控件。",
            "target_edit_control_ambiguous": "目标控件匹配不唯一。",
            "target_edit_control_geometry_invalid": "目标控件的位置超出学习截图。",
            "target_edit_control_not_executable": "所选控件不支持此动作。",
            "target_edit_container_missing": "学习证据中未找到列表容器。",
            "target_edit_container_ambiguous": "列表容器匹配不唯一。",
            "target_edit_container_geometry_invalid": "列表容器的位置超出学习截图。",
            "target_edit_row_missing": "学习证据中未找到匹配的行。",
            "target_edit_row_geometry_invalid": "行的位置超出列表容器。",
            "target_edit_property_missing": "行内 Text 属性缺失。",
            "target_edit_property_ambiguous": "行内 Text 属性匹配不唯一。",
            "target_edit_row_action_missing": "行内动作控件缺失。",
            "target_edit_row_action_ambiguous": "行内动作控件匹配不唯一。",
            "target_edit_anchor_is_target": "目标与界面锚点重叠，请选择其他控件。",
            "target_edit_single_strategy_required": "仅支持 1–8 条固定控件或可见行策略。",
            "target_edit_preview_bindings_invalid": "预览样例值无效。",
            "target_box_control_missing": "框内没有可执行控件，请框选完整目标控件。",
            "target_box_control_ambiguous": "框选目标不唯一，请缩小范围或选择具体控件。",
            "target_box_ambiguous": "框选目标不唯一，请缩小范围或选择具体控件。",
            "target_box_not_inside_control": "请在目标控件边界内框选；位置将随当前控件重新定位。",
            "target_box_outside_frame": "框的位置必须在这张学习截图内。",
            "target_box_row_control_not_unique": "新目标必须是当前列表行中唯一的动作控件。",
            "target_box_geometry_invalid": "框的位置必须在这张学习截图内。",
            "target_box_preview_not_matched": "修改后的规则未能唯一匹配，请检查目标与预览输入。",
        }
        label = tr(messages[raw]) if raw in messages else tr("缺少完整控件层级证据。") if "provider_tree" in raw else raw
        ui(self.status.setText, tr(prefix) + label)
        self.status.setToolTip(str(reason))

    def load_evidence(self):
        if self._has_unapplied_changes:
            ui(self.status.setText, tr('有未应用目标修改；请先应用并保存，或在任务步骤中放弃修改。'))
            return
        if self.is_busy or not self._reference:
            return
        reference, proposed = deepcopy(self._reference), deepcopy(self._proposed_recipe)
        self._start("load", lambda: self.facade.read_target_edit_context(reference, proposed_recipe=proposed))

    def _install_context(self, context):
        self._context = context
        recipe = context["recipe"]
        self._updating = True
        try:
            controls = [row for row in context.get("controls", []) if isinstance(row, dict)
                        and row.get("visible") is True and row.get("enabled") is True]
            action_kind = self._step["action"].get("kind")
            allowed = _CLICK_TYPES if action_kind == "click" else _INPUT_TYPES if action_kind == "input_sequence" else set()
            self._fill(self.fixed_control, [(row, _label(row)) for row in controls
                                            if row.get("control_type") in allowed and row.get("name")])
            self._fill(self.container, [(row, _label(row)) for row in controls
                                        if row.get("control_type") in {"List", "Table", "DataGrid", "Pane", "Group"}
                                        and (row.get("name") or row.get("automation_id"))])
            self._fill(self.binding, [])
            self._strategies = deepcopy(recipe.get("strategies", []))
            self._samples = [["" for _ in rule.get("constraints", [])] for rule in self._strategies]
            self._active_strategy = 0
            self._active_condition = 0
            self._editable = (1 <= len(self._strategies) <= 8 and all(
                rule.get("kind") in {"uia", "visible_row"} and
                (rule.get("kind") != "visible_row" or bool(rule.get("properties")) and bool(rule.get("constraints")) and
                 all(any(prop.get("property") == constraint.get("property") for prop in rule["properties"])
                     for constraint in rule["constraints"])) for rule in self._strategies))
            self._refresh_strategy_choice()
            if self._editable:
                self._load_strategy(0)
            self._invalidate_preview()
            self._paint(None)
            if not self._editable:
                ui(self.status.setText, tr('原规则含本编辑器不支持的策略结构；原规则已保留。'))
            elif recipe.get("contract_version") == "target_recipe.v1":
                ui(self.status.setText, tr('旧版规则没有动作 UIA 证据；当前编辑不受支持。'))
            elif self._missing_binding_value is not None:
                ui(self.status.setText, tr('所选变量已不在工作流声明中，请重新选择。'))
            else:
                ui(self.status.setText, tr('证据已读取；先预览归档截图匹配。'))
        finally:
            self._updating = False
        self._sync()

    def _box_selected(self, region_id):
        if self._updating or not region_id.startswith("strategy-"):
            return
        index = int(region_id.removeprefix("strategy-"))
        if 0 <= index < self.strategy_choice.count():
            self.strategy_choice.setCurrentIndex(index)

    def _box_moved(self, region_id, bbox):
        if self._updating or not region_id.startswith("strategy-"):
            return
        self.request_box_edit(int(region_id.removeprefix("strategy-")), bbox)

    def request_box_edit(self, index, bbox):
        if not self._context or not self._editable or self.is_busy:
            self._paint(None)
            return
        try:
            key = self._request_key()
        except ValueError as error:
            self._paint(None)
            self._show_status("无法修改目标框：", error)
            return
        reference, proposed = deepcopy(self._reference), deepcopy(self._proposed_recipe)
        action, strategies, inputs, outputs = key
        self._start("box", lambda: self.facade.propose_target_box_edit(reference, action, strategies,
            index, list(bbox), proposed_recipe=proposed, preview_inputs=inputs, preview_outputs=outputs), key)

    def _install_box_proposal(self, value):
        self._updating = True
        try:
            self._strategies = deepcopy(value["recipe"]["strategies"])
            self._load_strategy(self._active_strategy)
            self._refresh_strategy_choice()
        finally:
            self._updating = False
        self._preview_result = deepcopy(value)
        self._preview_key = self._request_key()
        self._has_unapplied_changes = True
        self.changed.emit()
        self._show_preview(value)

    @staticmethod
    def _fill(combo, rows):
        combo.clear()
        for value, label in rows:
            ui(combo.addItem, tr('{label}', label=label), deepcopy(value))

    @staticmethod
    def _choose(combo, value):
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return True
        return False

    @staticmethod
    def _choose_selector(combo, selector, *, per_row=False):
        matches = []
        for index in range(combo.count()):
            value = combo.itemData(index)
            if value and value.get("source") == selector.get("source") and all(value.get(key) == val for key, val in selector.items() if key in {"name", "control_type", "automation_id"}):
                matches.append(index)
        # 行内通用规则只展示一份控件样例；预览及运行仍逐行验证唯一性。
        accepted = len(matches) == 1 or bool(matches) and per_row and "automation_id" not in selector
        if accepted:
            combo.setCurrentIndex(matches[0])
        return accepted

    def _refresh_strategy_choice(self):
        self.strategy_choice.clear()
        for index, rule in enumerate(self._strategies):
            kind = tr("固定控件") if rule.get("kind") == "uia" else tr("可见行")
            ui(self.strategy_choice.addItem, tr("{index}. {kind}", index=index + 1, kind=kind), index)
        self.strategy_choice.setCurrentIndex(self._active_strategy)

    def _refresh_condition_choice(self):
        self.condition_choice.clear()
        rule = self._strategies[self._active_strategy]
        for index, condition in enumerate(rule.get("constraints", [])):
            self.condition_choice.addItem(f"{index + 1}. {condition['property']}", index)
        self.condition_choice.setCurrentIndex(self._active_condition)

    def _load_strategy(self, index):
        self._active_strategy = index
        self._active_condition = 0
        rule = self._strategies[index]
        self._selector_missing = False
        self.mode.setCurrentIndex(0 if rule["kind"] == "uia" else 1)
        if rule["kind"] == "uia":
            self._selector_missing = not self._choose_selector(self.fixed_control, rule)
            self.condition_choice.clear()
        else:
            self._selector_missing = not self._choose_selector(self.container, rule["container"])
            self._choose(self.row_type, rule["row"]["control_type"])
            self._choose(self.action_source, rule["action"].get("source", "descendant"))
            self._choose(self.property_source, rule["properties"][0].get("source", "descendant"))
            self._populate_row_controls()
            self.action_id_required.setChecked("automation_id" in rule["action"])
            self._selector_missing |= not self._choose_selector(self.row_action, rule["action"], per_row=True)
            self._refresh_condition_choice()
            self._load_condition(0)
        self.strategy_choice.setCurrentIndex(index)
        self._form_rule_dirty = False

    def _load_condition(self, index):
        rule = self._strategies[self._active_strategy]
        self._active_condition = index
        self._selector_missing = (not self._choose_selector(self.container, rule["container"])
                                  or not self._choose_selector(self.row_action, rule["action"], per_row=True))
        condition = rule["constraints"][index]
        prop = next(row for row in rule["properties"] if row["property"] == condition["property"])
        self._choose(self.property_source, prop.get("source", "descendant"))
        self._populate_row_controls()
        self._selector_missing |= not self._choose_selector(self.row_action, rule["action"], per_row=True)
        self.property_id_required.setChecked("automation_id" in prop)
        self._selector_missing |= not self._choose_selector(self.property_control, prop, per_row=True)
        self._choose(self.operator, condition["operator"])
        value = condition["value"]
        self._choose(self.value_source, value["source"])
        self._missing_binding_value = None
        self._populate_bindings(preserve=False)
        self.constant.setText(str(value.get("value", "")))
        if value["source"] != "constant":
            selected = (value.get("step_id"), value["name"])
            if not self._choose(self.binding, selected):
                self._missing_binding_value = selected
                self._populate_bindings()
        self.sample.setText(self._samples[self._active_strategy][index])
        self.condition_choice.setCurrentIndex(index)
        self._form_rule_dirty = False

    def _store_active(self):
        if not self._context or not self._editable or self._selector_missing:
            return
        old = self._strategies[self._active_strategy]
        if old.get("kind") == "visible_row" and self._active_condition < len(old["constraints"]):
            self._samples[self._active_strategy][self._active_condition] = self.sample.text()
        if not self._form_rule_dirty:
            return
        if self.mode.currentData() == "uia":
            control = self.fixed_control.currentData()
            if control:
                self._strategies[self._active_strategy] = {"kind": "uia", **_selector(control)}
                self._form_rule_dirty = False
            return
        container, prop, action = self.container.currentData(), self.property_control.currentData(), self.row_action.currentData()
        if not all((container, prop, action)):
            return
        if old.get("kind") != "visible_row":
            old = {"kind": "visible_row", "container": _selector(container), "row": {"control_type": self.row_type.currentData()},
                   "properties": [{"property": "target_value", "control_type": "Text", "read": "name"}],
                   "constraints": [{"property": "target_value", "operator": "eq", "value": {"source": "constant", "value": ""}}],
                   "action": _selector(action)}
            self._samples[self._active_strategy] = [""]
            self._active_condition = 0
        old["container"] = _selector(container)
        old["row"] = {"control_type": self.row_type.currentData()}
        old["action"] = _selector(action, include_id=self.action_id_required.isChecked())
        condition = old["constraints"][self._active_condition]
        property_spec = next(item for item in old["properties"] if item["property"] == condition["property"])
        property_spec.clear()
        property_spec.update(property=condition["property"], control_type=prop["control_type"], read="name")
        if prop.get("source") == "row":
            property_spec["source"] = "row"
        if self.property_id_required.isChecked() and prop.get("automation_id"):
            property_spec["automation_id"] = prop["automation_id"]
        condition["operator"] = self.operator.currentData()
        source = self.value_source.currentData()
        if source == "constant":
            condition["value"] = {"source": "constant", "value": self.constant.text()}
        elif self.binding.currentData() is not None:
            step_id, name = self.binding.currentData()
            condition["value"] = {"source": source, "name": name}
            if source == "output":
                condition["value"]["step_id"] = step_id
        self._strategies[self._active_strategy] = old
        self._form_rule_dirty = False

    def _mark_rule_changed(self):
        self._invalidate_preview()
        self._has_unapplied_changes = True
        self.changed.emit()
        self._sync()

    def _switch_strategy(self, index):
        if self._updating or index < 0 or not self._context or not self._editable:
            return
        self._store_active()
        self._updating = True
        try:
            self._load_strategy(index)
        finally:
            self._updating = False
        self._sync()

    def _switch_condition(self, index):
        if self._updating or index < 0 or not self._context or not self._editable:
            return
        self._store_active()
        self._updating = True
        try:
            self._load_condition(index)
        finally:
            self._updating = False
        self._sync()

    def _add_strategy(self):
        if not self._editable or len(self._strategies) >= 8:
            return
        self._store_active()
        self._strategies.append(deepcopy(self._strategies[self._active_strategy]))
        self._samples.append(deepcopy(self._samples[self._active_strategy]))
        self._updating = True
        try:
            self._refresh_strategy_choice()
            self._load_strategy(len(self._strategies) - 1)
        finally:
            self._updating = False
        self._mark_rule_changed()

    def _move_strategy(self, delta):
        destination = self._active_strategy + delta
        if not self._editable or not 0 <= destination < len(self._strategies):
            return
        self._store_active()
        self._strategies[self._active_strategy], self._strategies[destination] = self._strategies[destination], self._strategies[self._active_strategy]
        self._samples[self._active_strategy], self._samples[destination] = self._samples[destination], self._samples[self._active_strategy]
        self._updating = True
        try:
            self._refresh_strategy_choice()
            self._load_strategy(destination)
        finally:
            self._updating = False
        self._mark_rule_changed()

    def _delete_strategy(self):
        if not self._editable or len(self._strategies) <= 1:
            return
        self._strategies.pop(self._active_strategy)
        self._samples.pop(self._active_strategy)
        self._updating = True
        try:
            self._active_strategy = min(self._active_strategy, len(self._strategies) - 1)
            self._refresh_strategy_choice()
            self._load_strategy(self._active_strategy)
        finally:
            self._updating = False
        self._mark_rule_changed()

    def _add_condition(self):
        if not self._editable or self.mode.currentData() != "visible_row":
            return
        self._store_active()
        rule = self._strategies[self._active_strategy]
        if len(rule["constraints"]) >= 16:
            return
        used = {item["property"] for item in rule["properties"]}
        suffix = 2
        while f"target_value_{suffix}" in used:
            suffix += 1
        name = f"target_value_{suffix}"
        prop = deepcopy(rule["properties"][0])
        prop["property"] = name
        rule["properties"].append(prop)
        rule["constraints"].append({"property": name, "operator": "eq", "value": {"source": "constant", "value": ""}})
        self._samples[self._active_strategy].append("")
        self._updating = True
        try:
            self._active_condition = len(rule["constraints"]) - 1
            self._refresh_condition_choice()
            self._load_condition(self._active_condition)
        finally:
            self._updating = False
        self._mark_rule_changed()

    def _delete_condition(self):
        if not self._editable or self.mode.currentData() != "visible_row":
            return
        self._store_active()
        rule = self._strategies[self._active_strategy]
        if len(rule["constraints"]) <= 1:
            return
        condition = rule["constraints"].pop(self._active_condition)
        if not any(item["property"] == condition["property"] for item in rule["constraints"]):
            rule["properties"] = [item for item in rule["properties"] if item["property"] != condition["property"]]
        self._samples[self._active_strategy].pop(self._active_condition)
        self._updating = True
        try:
            self._active_condition = min(self._active_condition, len(rule["constraints"]) - 1)
            self._refresh_condition_choice()
            self._load_condition(self._active_condition)
        finally:
            self._updating = False
        self._mark_rule_changed()

    def _tree_available(self):
        if not self._context:
            return False
        controls = self._context.get("controls", [])
        frame = self._context.get("frame", {})
        uia = self._context.get("uia") or {}
        snapshot = uia.get("snapshot") or {}
        return (snapshot.get("provider_tree_valid") is True
                and all(isinstance(row.get("control_id"), str)
                        and isinstance(row.get("ancestor_control_ids"), list) for row in controls))

    def _populate_row_controls(self):
        self.property_control.clear()
        self.row_action.clear()
        if not self._tree_available():
            return
        container = self.container.currentData()
        if not container:
            return
        cid = container["control_id"]
        controls = self._context["controls"]
        row_ids = {row["control_id"] for row in controls
                   if row.get("control_type") == self.row_type.currentData()
                   and cid in row.get("ancestor_control_ids", [])}
        descendants = [row for row in controls if row.get("visible") is True and row.get("enabled") is True
                       and cid in row.get("ancestor_control_ids", [])
                       and any(rid in row.get("ancestor_control_ids", []) for rid in row_ids)]
        def unique(kind):
            found = {}
            for row in descendants:
                if kind(row) and row.get("name"):
                    found[tuple(sorted(_selector(row).items()))] = row
            return [(row, _label(row)) for row in found.values()]
        self._fill(self.property_control, unique(lambda row: row.get("control_type") == "Text"))
        allowed = _CLICK_TYPES if self._step["action"].get("kind") == "click" else _INPUT_TYPES
        self._fill(self.row_action, unique(lambda row: row.get("control_type") in allowed))
        if row_ids and self.property_source.currentData() == "row":
            self._fill(self.property_control, [({"source": "row", "control_type": self.row_type.currentData()}, "行自身名称")])
        if row_ids and self.action_source.currentData() == "row":
            self._fill(self.row_action, [({"source": "row", "control_type": self.row_type.currentData()}, "行自身动作")]
                       if self.row_type.currentData() in allowed else [])
        if self.action_source.currentData() == "row_name":
            by_id = {row["control_id"]: row for row in controls if row["control_id"] in row_ids}
            types = sorted({child["control_type"] for child in descendants
                            if child["control_type"] in (_CLICK_TYPES | {"Edit"})
                            and len(row_ids.intersection(child["ancestor_control_ids"])) == 1
                            and child.get("name") and any(child["name"] == by_id[rid].get("name")
                                for rid in row_ids.intersection(child["ancestor_control_ids"]))})
            self._fill(self.row_action, [({"source": "row_name", "control_type": kind}, tr('当前行同名子控件 · {kind}', kind=kind))
                                         for kind in types] if self._step["action"].get("kind") == "click" else [])

    def _populate_bindings(self, *, preserve=True):
        source = self.value_source.currentData()
        definition = self._definition or {}
        if source == "input":
            rows = [((None, item["name"]), item["name"]) for item in definition.get("inputs", []) if item.get("type") == "text"]
        elif source == "output":
            steps = definition.get("steps", [])
            selected = next((i for i, row in enumerate(steps) if row.get("step_id") == self._step.get("step_id")), len(steps))
            rows = [((row["step_id"], item["name"]), f"{row.get('title', row['step_id'])} · {item['name']}")
                    for row in steps[:selected] for item in row.get("outputs", []) if item.get("type") == "text"]
        else:
            rows = []
        old = self.binding.currentData() if preserve else None
        if old is None and preserve:
            old = self._missing_binding_value
        self._fill(self.binding, rows)
        if old is not None and not self._choose(self.binding, old):
            self._missing_binding_value = old
            ui(self.binding.insertItem, 0, tr("原变量已不在声明中，请重新选择"), None)
            self.binding.setCurrentIndex(0)
        else:
            self._missing_binding_value = None

    def _changed(self, *_):
        if self._updating:
            return
        sender = self.sender()
        if sender in (self.mode, self.container, self.row_type, self.property_source, self.action_source):
            self._populate_row_controls()
        if sender is self.value_source:
            self._missing_binding_value = None
            self._updating = True
            try:
                self._populate_bindings(preserve=False)
            finally:
                self._updating = False
        elif sender is self.binding and self.binding.currentData() is not None:
            self._missing_binding_value = None
        if sender is not self.sample:
            self._selector_missing = False
            self._form_rule_dirty = True
        self._store_active()
        if self._strategies and self._active_strategy < self.strategy_choice.count():
            kind = tr("固定控件") if self.mode.currentData() == "uia" else tr("可见行")
            ui(self.strategy_choice.setItemText, self._active_strategy, tr("{index}. {kind}", index=self._active_strategy + 1, kind=kind))
        self._invalidate_preview()
        if sender is not self.sample:
            self._has_unapplied_changes = True
            self.changed.emit()
        self._sync()

    def _invalidate_preview(self):
        self._preview_key = None
        self._preview_result = None
        if self._context:
            self._paint(None)

    def _sync(self):
        loaded = self._context is not None
        editable = loaded and getattr(self, "_editable", False) and self._context["recipe"].get("contract_version") != "target_recipe.v1"
        row = self.mode.currentData() == "visible_row"
        for widget, visible in ((self.fixed_control, not row), (self.container, row),
                                (self.property_source, row), (self.action_source, row),
                                (self.row_type, row), (self.property_control, row),
                                (self.property_id_required, row and self.property_source.currentData() != "row"),
                                (self.action_id_required, row and self.action_source.currentData() not in {"row", "row_name"}),
                                (self.row_action, row), (self.operator, row), (self.value_source, row),
                                (self.constant, row and self.value_source.currentData() == "constant"),
                                (self.binding, row and self.value_source.currentData() != "constant"),
                                (self.sample, row and self.value_source.currentData() != "constant")):
            self._form.setRowVisible(widget, visible)
        self.load_button.setEnabled(bool(self._reference) and not self.is_busy and not self._has_unapplied_changes)
        self.canvas.setInteractive(bool(editable and not self.is_busy))
        self.strategy_choice.setEnabled(editable and not self.is_busy)
        self.strategy_add.setEnabled(editable and not self.is_busy and len(self._strategies) < 8)
        self.strategy_up.setEnabled(editable and not self.is_busy and self._active_strategy > 0)
        self.strategy_down.setEnabled(editable and not self.is_busy and self._active_strategy + 1 < len(self._strategies))
        self.strategy_delete.setEnabled(editable and not self.is_busy and len(self._strategies) > 1)
        self.condition_choice.setEnabled(editable and row and not self.is_busy)
        self.condition_add.setEnabled(editable and row and not self.is_busy and bool(self._strategies) and
                                      len(self._strategies[self._active_strategy].get("constraints", [])) < 16)
        self.condition_delete.setEnabled(editable and row and not self.is_busy and bool(self._strategies) and
                                         len(self._strategies[self._active_strategy].get("constraints", [])) > 1)
        self.mode.setEnabled(editable and not self.is_busy)
        self.fixed_control.setEnabled(editable and not row and not self.is_busy)
        row_ok = self._tree_available() if any(rule.get("kind") == "visible_row" for rule in self._strategies) or row else True
        for widget in (self.container, self.row_type, self.property_control, self.row_action, self.property_source, self.action_source,
                       self.operator, self.value_source, self.property_id_required, self.action_id_required):
            widget.setEnabled(editable and row and row_ok and not self.is_busy)
        self.constant.setEnabled(editable and row and row_ok and self.value_source.currentData() == "constant" and not self.is_busy)
        self.binding.setEnabled(editable and row and row_ok and self.value_source.currentData() != "constant" and not self.is_busy)
        self.sample.setEnabled(editable and row and row_ok and self.value_source.currentData() != "constant" and not self.is_busy)
        ready = editable and not self.is_busy and row_ok and not getattr(self, "_selector_missing", False) and (
            self.fixed_control.currentData() is not None if not row else
            self.container.currentData() is not None and self.property_control.currentData() is not None
            and self.row_action.currentData() is not None and
            (self.value_source.currentData() == "constant" and bool(self.constant.text()) or
              self.binding.currentData() is not None and bool(self.sample.text())))
        if ready:
            for index, rule in enumerate(self._strategies):
                if rule["kind"] != "visible_row":
                    continue
                for position, constraint in enumerate(rule["constraints"]):
                    value = constraint["value"]
                    if value["source"] != "constant" and (not self._binding_declared(value) or
                            not self._samples[index][position]):
                        ready = False
                        break
        self.preview_button.setEnabled(bool(ready))
        self.apply_button.setEnabled(bool(ready))
        if editable and not row_ok:
            ui(self.status.setText, tr('缺少完整控件层级证据，无法编辑可见行。'))

    def _binding_declared(self, value):
        if value["source"] == "constant":
            return True
        definition = self._definition or {}
        if value["source"] == "input":
            return any(item.get("name") == value["name"] and item.get("type") == "text"
                       for item in definition.get("inputs", []))
        steps = definition.get("steps", [])
        selected = next((i for i, row in enumerate(steps) if row.get("step_id") == self._step.get("step_id")), len(steps))
        return any(row.get("step_id") == value.get("step_id") and
                   any(item.get("name") == value["name"] and item.get("type") == "text"
                       for item in row.get("outputs", [])) for row in steps[:selected])

    def _any_missing_binding(self):
        return any(not self._binding_declared(condition["value"])
                   for rule in self._strategies if rule.get("kind") == "visible_row"
                   for condition in rule["constraints"])

    def _strategy(self):
        self._store_active()
        return deepcopy(self._strategies[self._active_strategy])

    def _request_key(self):
        action = self.action_provider() if callable(self.action_provider) else deepcopy(self._step["action"])
        if not isinstance(action, dict):
            raise ValueError("当前动作未能提交")
        self._store_active()
        strategies = deepcopy(self._strategies)
        inputs, outputs = {}, {}
        for index, strategy in enumerate(strategies):
            if strategy["kind"] != "visible_row":
                continue
            for position, constraint in enumerate(strategy["constraints"]):
                value = constraint["value"]
                if value["source"] == "constant":
                    continue
                if not self._binding_declared(value):
                    raise ValueError("所选变量已不在工作流声明中")
                sample = self._samples[index][position]
                if not sample:
                    raise ValueError("请提供本次预览样例值")
                if value["source"] == "input":
                    key = value["name"]
                    if key in inputs and inputs[key] != sample:
                        raise ValueError("同一变量的预览样例值不一致")
                    inputs[key] = sample
                else:
                    key = value["step_id"] + "." + value["name"]
                    item = {"run_id": "target-edit-preview", "value": sample}
                    if key in outputs and outputs[key] != item:
                        raise ValueError("同一变量的预览样例值不一致")
                    outputs[key] = item
        return action, strategies, inputs or None, outputs or None

    def preview(self):
        if not self.preview_button.isEnabled():
            return
        try:
            key = self._request_key()
        except ValueError as error:
            self._show_status("无法预览：", error)
            return
        reference, proposed = deepcopy(self._reference), deepcopy(self._proposed_recipe)
        facade = self.facade
        action, strategies, inputs, outputs = key
        self._start("preview", lambda: facade.propose_target_edit(reference, action, strategies,
                     proposed_recipe=proposed, preview_inputs=inputs, preview_outputs=outputs), key)

    def _show_preview(self, value):
        preview = value.get("preview", {})
        status = preview.get("status")
        reason = preview.get("reason", "")
        self._paint(preview.get("candidate", {}).get("bbox") if status == "matched" else None)
        label = {"matched": "已在学习截图中唯一匹配，可应用未验证修订。",
                 "miss": "学习截图未匹配到目标。", "ambiguous": "学习截图匹配不唯一。",
                 "unsupported": "此证据不支持预览。", "invalid": "目标或证据无效。"}.get(status, "预览结果未知。")
        ui(self.status.setText, tr(label) + tr(' 学习截图匹配，不代表当前实机已验证。'))
        self.status.setToolTip(str(reason))

    def _paint(self, bbox):
        if not self._context:
            return
        path = self._context.get("frame", {}).get("image_path")
        if not path:
            self.canvas.clear_canvas()
            return
        regions = deepcopy(self._context.get("target_boxes", []))
        for index, rule in enumerate(self._strategies):
            if rule.get("kind") != "uia":
                continue
            matches = [control for control in self._context.get("controls", [])
                if control.get("visible") is True and control.get("enabled") is True and
                all(control.get(key) == val for key, val in rule.items() if key != "kind")]
            if len(matches) == 1 and isinstance(matches[0].get("bbox"), dict):
                box = matches[0]["bbox"]
                item = {"region_id": f"strategy-{index}", "bbox": [box[k] for k in ("x", "y", "w", "h")],
                    "name": matches[0].get("name", ""), "kind": "unknown"}
                regions = [row for row in regions if row["region_id"] != item["region_id"]] + [item]
        if isinstance(bbox, dict):
            region_id = f"strategy-{self._active_strategy}"
            regions = [row for row in regions if row["region_id"] != region_id] + [
                {"region_id": region_id, "bbox": [bbox[k] for k in ("x", "y", "w", "h")]}]
        frame = self._context["frame"]
        self.canvas.set_image(Path(path).read_bytes(), regions,
            (self._reference["recipe_id"], frame.get("capture_id"), frame.get("sha256")))
        self.canvas.select_region(f"strategy-{self._active_strategy}")

    def apply(self):
        if not self.apply_button.isEnabled():
            return
        try:
            key = self._request_key()
        except ValueError as error:
            self._show_status("无法应用：", error)
            return
        if self._preview_key != key or not self._preview_result:
            ui(self.status.setText, tr('动作或条件已变化，请重新预览学习截图。'))
            return
        if self._preview_result.get("preview", {}).get("status") != "matched":
            ui(self.status.setText, tr('仅唯一匹配的预览可应用。'))
            return
        self.proposalReady.emit({"step_id": self._step["step_id"], "original_action": deepcopy(key[0]),
                                 "result": deepcopy(self._preview_result)})
        ui(self.status.setText, tr('修订已交给步骤编辑区；学习截图匹配，不代表当前实机已验证。'))


__all__ = ["WorkflowTargetEditor"]
