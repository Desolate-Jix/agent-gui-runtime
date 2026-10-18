"""学习工作流编辑与原会话运行入口。"""
from __future__ import annotations
from app.learning_memory.workbench_i18n import ui, translated_dialog, tr, bind_text, join_text

from copy import deepcopy
import json
from pathlib import Path
import re
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.desktop_review.jobs import make_job
from app.desktop_review.theme import apply_review_theme
from .program_graph_widget import ProgramGraphWidget
from .workflow_rules_editor import WorkflowRulesEditor
from .workflow_target_editor import WorkflowTargetEditor
from .workflow_run_panel import WorkflowRunPanel
from .workflow_input_dialog import WorkflowInputDialog
from .workflow_definition_summary import summarize_definition


_ACTIONS = ((tr('点击'), 'click'), (tr('填写文本'), 'input_sequence'), (tr('读取文本'), 'read_text'), (tr('滚动'), 'scroll'), (tr('按键'), 'press_key'))
_TYPES = ((tr('文本'), 'text'), (tr('数字'), 'number'), (tr('是/否'), 'boolean'))
_SOURCES = ((tr('常量'), 'constant'), (tr('工作流输入'), 'input'), (tr('上游输出'), 'output'))
_OPERATORS = ((tr('存在'), 'exists'), (tr('等于'), 'eq'), (tr('不等于'), 'not_eq'), (tr('包含'), 'contains'), (tr('Agent 判断'), 'agent_assertion'))
_TRIAL_STATES = {'ready': tr('可准备下一步'), 'pending': tr('等待 Agent 执行'), 'blocked': tr('缺少输入或条件未满足'), 'completed': tr('已完成'), 'failed': tr('失败已暂停'), 'paused_uncertain': tr('结果不确定，已暂停'), 'cancel_requested': tr('取消请求已提交'), 'cancelled': tr('已取消')}
_ERRORS = {'task_program_stale_revision': tr('项目版本已变化；当前修改仍保留，请放弃后刷新并重新编辑。'), 'task_program_step_title_invalid': tr('步骤名称不能为空。'), 'task_program_goal_invalid': tr('请填写当前步骤的目标。'), 'task_program_input_action_invalid': tr('请填写字段目标和有效的输入选项。'), 'action_input_unknown': tr('文本来源引用的工作流输入不存在。'), 'action_upstream_output_unknown': tr('文本来源引用的上游输出不存在。'), 'target_input_unknown': tr('目标条件引用的工作流输入不存在，请先声明或重新选择变量。'), 'target_upstream_output_unknown': tr('目标条件引用的前序输出不可用，请修正依赖或步骤顺序。'), 'target_row_requires_text': tr('当前行规则读取的是文字，匹配值需要声明为文本。'), 'target_edit_action_control_type_mismatch': tr('动作类型与所选控件不匹配，请重新选择目标。'), 'workflow_trial_save_program_first': tr('请先保存任务步骤。'), 'workflow_learning_session_missing': tr('学习会话目录不存在，请连接已有会话。'), 'workflow_learning_library_mismatch': tr('学习会话与当前内容库不属于同一数据目录，请连接对应会话。'), 'workflow_learning_synthesis_request_missing': tr('整理请求记录缺失，请让当前 Agent 检查并恢复原记录。'), 'workflow_trial_session_has_unresolved_execution': tr('会话已有待处理请求；请先回读或处理原试运行。')}


def _choice(combo, value):
    index = combo.findData(value)
    combo.setCurrentIndex(index if index >= 0 else 0)


def _cell(table, row, column):
    widget = table.cellWidget(row, column)
    if isinstance(widget, QComboBox):
        return widget.currentData()
    item = table.item(row, column)
    return item.text().strip() if item else ""


def _error_text(error):
    raw = str(error).splitlines()[0]
    return _ERRORS.get(raw, raw)


class ConditionEditor(QWidget):
    changed = Signal()

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self._loading = False
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(ui(QLabel, tr(title)))
        self.rows = QListWidget()
        self.rows.setMaximumHeight(94)
        box.addWidget(self.rows)
        form = QHBoxLayout()
        self.source = QComboBox()
        for label, key in (("工作流输入", "input"), ("上游输出", "output"), ("当前观察", "observation")):
            ui(self.source.addItem, tr(label), key)
        self.step = QComboBox()
        self.name = QLineEdit(); ui(self.name.setPlaceholderText, tr('输入、输出或观察名称'))
        self.operator = QComboBox()
        for label, key in _OPERATORS:
            ui(self.operator.addItem, tr(label), key)
        self.value = QLineEdit(); ui(self.value.setPlaceholderText, tr('比较值'))
        for widget in (self.source, self.step, self.name, self.operator, self.value):
            form.addWidget(widget)
        box.addLayout(form)
        buttons = QHBoxLayout()
        self.add_button = ui(QPushButton, tr('添加条件'))
        self.remove_button = ui(QPushButton, tr('移除选中条件'))
        buttons.addWidget(self.add_button); buttons.addWidget(self.remove_button)
        box.addLayout(buttons)
        self.add_button.clicked.connect(self.add_condition)
        self.remove_button.clicked.connect(self.remove_condition)
        self.source.currentIndexChanged.connect(self._update_fields)
        self.operator.currentIndexChanged.connect(self._update_fields)
        self._update_fields()

    def set_steps(self, steps):
        current = self.step.currentData()
        self.step.clear()
        for item in steps:
            self.step.addItem(item["title"], item["step_id"])
        _choice(self.step, current)

    def set_conditions(self, values):
        self._loading = True
        self.rows.clear()
        for value in values:
            self._append(value)
        self._loading = False

    def conditions(self):
        return [deepcopy(self.rows.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.rows.count())]

    def _append(self, value):
        left = value["left"]
        location = (left.get("step_id", "") + ".") if left["source"] == "output" else ""
        label = f'{left["source"]}: {location}{left["name"]} · {value["operator"]}'
        if "value" in value:
            label += f' · {value["value"]}'
        row = QListWidgetItem(label)
        row.setData(Qt.ItemDataRole.UserRole, deepcopy(value))
        self.rows.addItem(row)

    def _update_fields(self):
        self.step.setVisible(self.source.currentData() == "output")
        self.value.setEnabled(self.operator.currentData() in {"eq", "not_eq", "contains"})

    def add_condition(self):
        name = self.name.text().strip()
        if not name:
            self.name.setFocus(); return
        source = self.source.currentData()
        left = {"source": source, "name": name}
        if source == "output":
            if self.step.currentData() is None:
                return
            left["step_id"] = self.step.currentData()
        value = {"left": left, "operator": self.operator.currentData()}
        if value["operator"] in {"eq", "not_eq", "contains"}:
            value["value"] = self.value.text()
        self._append(value)
        self.name.clear(); self.value.clear()
        if not self._loading:
            self.changed.emit()

    def remove_condition(self):
        row = self.rows.currentRow()
        if row >= 0:
            self.rows.takeItem(row)
            self.changed.emit()


class WorkflowStepsPane(QWidget):
    dirtyChanged = Signal(bool)
    busyChanged = Signal(bool)

    def __init__(self, facade, session_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self.facade = facade
        self.session_dir = Path(session_dir).resolve() if session_dir else None
        self.snapshot = None
        self._summary_snapshot = None
        self.definition = None
        self._selected_id = None
        self._dirty = False
        self._loading = False
        self._text_reference = None
        self._sequence = 0
        self._active_request = None
        self._jobs = {}
        self._outcomes = {}
        self._closing_reads = False
        self._run_id = None
        self._learning_result = None
        self._draft_recipes = []
        self._build_ui()
        apply_review_theme(self)
        self.refresh()

    @property
    def dirty(self):
        return self._dirty

    @property
    def is_busy(self):
        return bool(self._jobs) or self.target_editor.is_busy or self.run_panel.is_busy

    def closeEvent(self, event):
        if self.is_busy:
            self.cancel_loading()
            ui(self.status.setText, tr('后台读取仍在结束，请稍后关闭。'))
            event.ignore()
            return
        if self.dirty:
            ui(self.status.setText, tr('任务步骤有未保存修改；请先保存或放弃后再关闭。'))
            event.ignore()
            return
        self.run_panel.close_client()
        super().closeEvent(event)

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.status = ui(QLabel, tr('选择流程项目后，可逐步修改任务。准备试运行不会操作外部软件。'))
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.definition_summary = ui(QLabel, tr('尚无任务定义。'))
        self.definition_summary.setWordWrap(True)
        self.definition_summary.setProperty("role", "muted")
        ui(self.definition_summary.setToolTip, tr('摘要仅计数载入的定义；不证明本次运行的目标命中、结果成功或完整模型调用节省。运行页的已记录用量可能只覆盖部分调用，缺失计量保持未知。'))
        root.addWidget(self.definition_summary)
        learning_bar = QHBoxLayout()
        self.learning_status = ui(QLabel, tr('未连接学习会话；仍可编辑已保存的工作流。'))
        self.learning_status.setWordWrap(True)
        learning_bar.addWidget(self.learning_status, 1)
        self.learning_refresh_button = ui(QPushButton, tr('刷新最近学习'))
        self.learning_refresh_button.setEnabled(self.session_dir is not None)
        self.learning_refresh_button.clicked.connect(self.refresh_learning)
        self.open_learning_button = ui(QPushButton, tr('打开学习草稿'))
        self.open_learning_button.setEnabled(False)
        self.open_learning_button.clicked.connect(self.open_learning_draft)
        learning_bar.addWidget(self.learning_refresh_button)
        learning_bar.addWidget(self.open_learning_button)
        root.addLayout(learning_bar)
        self.learning_details = QPlainTextEdit()
        self.learning_details.setReadOnly(True)
        self.learning_details.setMaximumHeight(100)
        self.learning_details.hide()
        root.addWidget(self.learning_details)
        toolbar = QHBoxLayout()
        toolbar.addWidget(ui(QLabel, tr('项目')))
        self.projects = QComboBox(); self.projects.setMinimumWidth(230)
        toolbar.addWidget(self.projects, 1)
        self.refresh_button = ui(QPushButton, tr('刷新'))
        self.save_button = ui(QPushButton, tr('保存任务步骤'))
        self.discard_button = ui(QPushButton, tr('放弃修改'))
        self.open_run_button = ui(QPushButton, tr('运行工作流'))
        ui(self.open_run_button.setToolTip, tr('打开运行页，连接原会话后选择单步或连续运行。'))
        for widget in (self.refresh_button, self.save_button, self.discard_button, self.open_run_button):
            toolbar.addWidget(widget)
        root.addLayout(toolbar)
        self.program_title = QLineEdit(); ui(self.program_title.setPlaceholderText, tr('任务名称'))
        root.addWidget(self.program_title)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.nav_tabs = QTabWidget()
        left = QWidget(); left_box = QVBoxLayout(left)
        note = ui(QLabel, tr('列表顺序不自动建立跳转'))
        note.setProperty("role", "muted")
        left_box.addWidget(note)
        self.steps = QListWidget(); self.steps.setMinimumWidth(185)
        self.steps.setStyleSheet("QListWidget::item { min-height: 42px; padding: 6px 8px; }")
        left_box.addWidget(self.steps, 1)
        row = QGridLayout()
        self.add_button = ui(QPushButton, tr('添加'))
        self.delete_button = ui(QPushButton, tr('删除'))
        self.up_button = ui(QPushButton, tr('上移'))
        self.down_button = ui(QPushButton, tr('下移'))
        for index, button in enumerate((self.add_button, self.delete_button, self.up_button, self.down_button)):
            row.addWidget(button, index // 2, index % 2)
        left_box.addLayout(row)
        ui(self.nav_tabs.addTab, left, tr('步骤'))
        relation_page = QWidget(); relation_box = QVBoxLayout(relation_page)
        relation_note = ui(QLabel, tr('成功与失败分支来自当前任务定义；未连接处暂停。'))
        relation_note.setWordWrap(True); relation_note.setProperty("role", "muted")
        relation_box.addWidget(relation_note)
        self.relations = QTreeWidget()
        ui(self.relations.setHeaderLabels, [tr('步骤'), tr('成功后'), tr('失败后')])
        self.relations.setMinimumWidth(255)
        self.relations.header().setStretchLastSection(True)
        self.relation_views = QTabWidget()
        ui(self.relation_views.addTab, self.relations, tr('关系表'))
        graph_page = QWidget(); graph_box = QVBoxLayout(graph_page)
        graph_box.setContentsMargins(0, 0, 0, 0)
        self.program_graph_note = ui(QLabel, tr('尚无可显示的任务步骤。'))
        self.program_graph_note.setWordWrap(True)
        graph_box.addWidget(self.program_graph_note)
        self.program_graph = ProgramGraphWidget()
        graph_box.addWidget(self.program_graph, 1)
        ui(self.relation_views.addTab, graph_page, tr('程序图'))
        relation_box.addWidget(self.relation_views)
        ui(self.nav_tabs.addTab, relation_page, tr('关系'))
        split.addWidget(self.nav_tabs)
        right = QWidget(); right_box = QVBoxLayout(right)
        self.step_heading = ui(QLabel, tr('选择步骤'))
        self.step_heading.setProperty("role", "sectionTitle")
        self.step_heading.setStyleSheet("font-size: 17px; font-weight: 600;")
        self.step_summary = ui(QLabel, tr('动作、来源和审核状态将在这里显示。'))
        self.step_summary.setProperty("role", "muted")
        self.step_summary.setWordWrap(True)
        right_box.addWidget(self.step_heading)
        right_box.addWidget(self.step_summary)
        trial = ui(QGroupBox, tr('高级 · 局部试运行仅准备请求'))
        trial_box = QVBoxLayout(trial)
        self.trial_note = ui(QLabel, tr('保存步骤后，可从选中步骤准备一次待 Agent 执行的请求。'))
        self.trial_note.setWordWrap(True); trial_box.addWidget(self.trial_note)
        trial_buttons = QHBoxLayout()
        self.prepare_button = ui(QPushButton, tr('准备单步试运行'))
        self.status_button = ui(QPushButton, tr('回读试运行'))
        self.next_button = ui(QPushButton, tr('准备下一步'))
        self.next_button.setEnabled(False)
        self.cancel_button = ui(QPushButton, tr('取消试运行'))
        for button in (self.prepare_button, self.status_button, self.next_button, self.cancel_button):
            trial_buttons.addWidget(button)
        trial_box.addLayout(trial_buttons)
        self.command_preview = QPlainTextEdit(); self.command_preview.setReadOnly(True)
        self.command_preview.setMaximumHeight(90)
        ui(self.command_preview.setPlaceholderText, tr('待执行命令会在此显示；工作台不会派发输入。'))
        self.command_preview.hide()
        trial_box.addWidget(self.command_preview)
        right_box.addWidget(trial)
        self.editor_tabs = QTabWidget()
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        editor = QWidget(); edit_box = QVBoxLayout(editor)
        self.empty = ui(QLabel, tr('选择一个步骤查看和修改。'))
        edit_box.addWidget(self.empty)
        form = QFormLayout(); self._form = form
        self.step_title = QLineEdit()
        self.action_kind = QComboBox()
        for label, key in _ACTIONS:
            ui(self.action_kind.addItem, tr(label), key)
        self.click_kind = QComboBox()
        ui(self.click_kind.addItem, tr('单击'), 'single')
        ui(self.click_kind.addItem, tr('双击（现场重新识别）'), 'double')
        self.selection_intent = QComboBox()
        ui(self.selection_intent.addItem, tr('普通点击'), None)
        ui(self.selection_intent.addItem, tr('确保选中该行'), 'ensure_selected')
        ui(self.selection_intent.setToolTip, tr('仅单击的可见行名称规则可用；修改后请在目标规则页预览并应用，再保存。'))
        self._selection_intent_pending = False
        self.goal = QLineEdit(); ui(self.goal.setPlaceholderText, tr('当前界面上的目标或读取内容'))
        self.field_goal = QLineEdit(); ui(self.field_goal.setPlaceholderText, tr('要填写的字段'))
        self.text_source = QComboBox()
        for label, key in _SOURCES:
            ui(self.text_source.addItem, tr(label), key)
        self.text_value = QLineEdit(); ui(self.text_value.setPlaceholderText, tr('每次都填写的固定文字'))
        self.text_binding = QComboBox()
        self.text_binding.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.text_binding.setMinimumContentsLength(20)
        self.parameterize_button = ui(QPushButton, tr('改为每次输入'))
        ui(self.parameterize_button.setToolTip, tr('创建一个输入参数，运行时填写本次的值。'))
        self.clear_existing = ui(QCheckBox, tr('先清空原内容'))
        self.submit_search = ui(QCheckBox, tr('填写后提交搜索'))
        self.scroll_direction = QComboBox(); ui(self.scroll_direction.addItem, tr('向下'), 'down'); ui(self.scroll_direction.addItem, tr('向上'), 'up')
        self.scroll_amount = QSpinBox(); self.scroll_amount.setRange(1, 20)
        self.key = QComboBox()
        for key in ("Enter", "Escape", "Tab", "Backspace"):
            self.key.addItem(key)
        self.review = QComboBox(); ui(self.review.addItem, tr('待审核'), 'pending'); ui(self.review.addItem, tr('已审核'), 'reviewed')
        self.provenance = QLabel()
        self.success = QComboBox(); self.failure = QComboBox()
        for label, widget in (("步骤名称", self.step_title), ("动作类型", self.action_kind),
                              ("点击方式", self.click_kind),
                              ("选择意图", self.selection_intent),
                              ("目标／读取内容", self.goal), ("字段目标", self.field_goal),
                              ("文本来源", self.text_source), ("固定文字", self.text_value),
                              ("参数化", self.parameterize_button), ("选择来源", self.text_binding), ("输入选项", self.clear_existing),
                              ("搜索选项", self.submit_search), ("滚动方向", self.scroll_direction),
                              ("滚动量", self.scroll_amount), ("按键", self.key),
                              ("成功后", self.success), ("失败后", self.failure),
                              ("审核状态", self.review), ("来源", self.provenance)):
            ui(form.addRow, tr(label), widget)
        edit_box.addLayout(form)
        edit_box.addStretch()
        scroll.setWidget(editor)
        ui(self.editor_tabs.addTab, scroll, tr('动作与分支'))
        detail_scroll = QScrollArea(); detail_scroll.setWidgetResizable(True)
        detail = QWidget(); detail_box = QVBoxLayout(detail)
        self.preconditions = ConditionEditor("执行前条件")
        self.success_conditions = ConditionEditor("成功条件")
        detail_box.addWidget(self.preconditions)
        detail_box.addWidget(self.success_conditions)
        self.outputs = QTableWidget(0, 2); ui(self.outputs.setHorizontalHeaderLabels, [tr("输出名称"), tr("类型")])
        self.outputs.setMaximumHeight(140)
        detail_box.addWidget(ui(QLabel, tr('本步骤输出 · 供后续步骤引用')))
        detail_box.addWidget(self.outputs)
        output_buttons = QHBoxLayout()
        self.add_output = ui(QPushButton, tr('添加输出'))
        self.remove_output = ui(QPushButton, tr('移除输出'))
        output_buttons.addWidget(self.add_output); output_buttons.addWidget(self.remove_output)
        detail_box.addLayout(output_buttons)
        detail_box.addStretch()
        detail_scroll.setWidget(detail)
        ui(self.editor_tabs.addTab, detail_scroll, tr('条件与输出'))
        input_box = ui(QGroupBox, tr('工作流输入'))
        input_layout = QVBoxLayout(input_box)
        self.inputs = QTableWidget(0, 3); ui(self.inputs.setHorizontalHeaderLabels, [tr("名称"), tr("类型"), tr("必填：是／否")])
        self.inputs.setMaximumHeight(130); input_layout.addWidget(self.inputs)
        input_buttons = QHBoxLayout()
        self.add_input = ui(QPushButton, tr('添加输入')); self.remove_input = ui(QPushButton, tr('移除输入'))
        input_buttons.addWidget(self.add_input); input_buttons.addWidget(self.remove_input)
        input_layout.addLayout(input_buttons)
        # 输入页与其他编辑页一样可滚动，字体放大时不撑高隐藏页面。
        input_scroll = QScrollArea(); input_scroll.setWidgetResizable(True)
        input_scroll.setWidget(input_box)
        ui(self.editor_tabs.addTab, input_scroll, tr('工作流输入'))
        self.rules_editor = WorkflowRulesEditor()
        self.rules_editor.set_step(None, None, 0)
        rule_scroll = QScrollArea(); rule_scroll.setWidgetResizable(True)
        rule_scroll.setWidget(self.rules_editor)
        ui(self.editor_tabs.addTab, rule_scroll, tr('结果与读取'))
        self.target_editor = WorkflowTargetEditor(self.facade)
        self.target_editor.action_provider = self._target_action
        self.target_editor.proposalReady.connect(self._apply_target_proposal)
        self.target_editor.busyChanged.connect(lambda _busy: self.busyChanged.emit(self.is_busy))
        self.target_editor.changed.connect(self._mark_dirty)
        target_scroll = QScrollArea(); target_scroll.setWidgetResizable(True)
        target_scroll.setWidget(self.target_editor)
        ui(self.editor_tabs.addTab, target_scroll, tr('目标规则'))
        self.run_panel = WorkflowRunPanel(self.facade._artifact_root, self.session_dir, self)
        self.run_panel.inputs_provider = self._trial_inputs
        self.run_panel.sessionChanged.connect(self._run_session_connected)
        self.run_panel.busyChanged.connect(lambda _busy: self.busyChanged.emit(self.is_busy))
        ui(self.editor_tabs.addTab, self.run_panel, tr('运行'))
        self.editor_tabs.currentChanged.connect(self._target_tab_chosen)
        right_box.addWidget(self.editor_tabs, 1)
        split.addWidget(right)
        split.setStretchFactor(0, 1); split.setStretchFactor(1, 3)
        split.setSizes([300, 980])
        root.addWidget(split, 1)
        self.refresh_button.clicked.connect(self.refresh)
        self.save_button.clicked.connect(self.save)
        self.discard_button.clicked.connect(self.discard)
        self.open_run_button.clicked.connect(self._open_run_tab)
        self.projects.currentIndexChanged.connect(self._project_chosen)
        self.steps.currentItemChanged.connect(self._step_chosen)
        self.relations.itemClicked.connect(self._relation_chosen)
        self.relation_views.currentChanged.connect(self._relation_view_chosen)
        self.program_graph.nodeSelected.connect(self._graph_node_chosen)
        self.add_button.clicked.connect(self.add_step)
        self.delete_button.clicked.connect(self.delete_step)
        self.up_button.clicked.connect(lambda: self.move_step(-1))
        self.down_button.clicked.connect(lambda: self.move_step(1))
        self.add_input.clicked.connect(lambda: self._add_table_row(self.inputs, ["", "text", "是"]))
        self.remove_input.clicked.connect(lambda: self._remove_table_row(self.inputs))
        self.add_output.clicked.connect(lambda: self._add_table_row(self.outputs, ["", "text"]))
        self.remove_output.clicked.connect(lambda: self._remove_table_row(self.outputs))
        self.prepare_button.clicked.connect(self.prepare_trial)
        self.status_button.clicked.connect(self.read_trial)
        self.next_button.clicked.connect(self.prepare_next)
        self.cancel_button.clicked.connect(self.cancel_trial)
        for widget in (self.program_title, self.step_title, self.goal, self.field_goal, self.text_value):
            widget.textChanged.connect(self._mark_dirty)
        for widget in (self.action_kind, self.click_kind, self.scroll_direction,
                       self.key, self.review, self.success, self.failure):
            widget.currentIndexChanged.connect(self._mark_dirty)
        for widget in (self.clear_existing, self.submit_search):
            widget.toggled.connect(self._mark_dirty)
        self.scroll_amount.valueChanged.connect(self._mark_dirty)
        self.inputs.itemChanged.connect(self._mark_dirty)
        self.outputs.itemChanged.connect(self._mark_dirty)
        self.preconditions.changed.connect(self._mark_dirty)
        self.success_conditions.changed.connect(self._mark_dirty)
        self.rules_editor.changed.connect(self._mark_dirty)
        self.action_kind.currentIndexChanged.connect(self._update_action_fields)
        self.click_kind.currentIndexChanged.connect(self._update_action_fields)
        self.selection_intent.currentIndexChanged.connect(self._selection_intent_changed)
        self.target_editor.changed.connect(self._update_action_fields)
        self.target_editor.busyChanged.connect(self._update_action_fields)
        self.text_source.currentIndexChanged.connect(self._text_source_changed)
        self.text_binding.currentIndexChanged.connect(self._text_binding_chosen)
        self.parameterize_button.clicked.connect(self._make_text_parameter)
        self._update_action_fields()

    def _mark_dirty(self, *_args):
        if not self._loading and self.definition is not None:
            self._refresh_text_bindings()
            if not self._dirty:
                self._dirty = True; self.dirtyChanged.emit(True)
            self._update_step_summary()
            self._update_definition_summary()
            ui(self.status.setText, tr('有未保存的任务步骤修改。'))
            if self.relation_views.currentIndex() == 1:
                self._commit_selected()
            self._sync_run_context()

    def _input_declarations(self):
        return [{"name": _cell(self.inputs, row, 0), "type": _cell(self.inputs, row, 1),
                 "required": _cell(self.inputs, row, 2) in {"是", "yes", "true", "1"}}
                for row in range(self.inputs.rowCount())]

    def _text_binding_choices(self, step, source):
        if step is None or self.definition is None:
            return []
        if source == "input":
            items = self._input_declarations()
            names = [item["name"] for item in items]
            return [(item["name"], {"source": "input", "name": item["name"]})
                    for item in items if item["name"] and item["type"] == "text"
                    and names.count(item["name"]) == 1]
        if source == "output":
            choices = []
            for upstream in self.definition["steps"][:self.definition["steps"].index(step)]:
                names = [item["name"] for item in upstream["outputs"]]
                for item in upstream["outputs"]:
                    if item["name"] and item["type"] == "text" and names.count(item["name"]) == 1:
                        choices.append((f'{upstream["title"]} · {item["name"]}',
                            {"source": "output", "step_id": upstream["step_id"], "name": item["name"]}))
            return choices
        return []

    def _refresh_text_bindings(self) -> None:
        source = self.text_source.currentData()
        choices = self._text_binding_choices(self._step(), source)
        selected = self._text_reference if (self._text_reference or {}).get("source") == source else None
        was_blocked = self.text_binding.blockSignals(True)
        self.text_binding.clear()
        ui(self.text_binding.addItem, tr('请选择工作流输入') if source == 'input' else tr('请选择前面步骤的文本结果'), None)
        for label, binding in choices:
            ui(self.text_binding.addItem, tr('{label}', label=label), binding)
        index = next((i for i in range(1, self.text_binding.count())
                      if self.text_binding.itemData(i) == selected), 0)
        if selected and index == 0:
            label = selected.get("name") or "尚未选择"
            ui(self.text_binding.addItem, tr('不可用：{v0}（名称、类型或顺序已变化）', v0=label), selected)
            index = self.text_binding.count() - 1
            self.text_binding.model().item(index).setEnabled(False)
        self.text_binding.setCurrentIndex(index)
        self.text_binding.setToolTip(self.text_binding.currentText())
        self.text_binding.blockSignals(was_blocked)

    def _text_source_changed(self):
        if self._loading:
            return
        self._text_reference = None
        self._refresh_text_bindings()
        self._update_action_fields()
        self._mark_dirty()

    def _text_binding_chosen(self):
        if not self._loading:
            self._text_reference = deepcopy(self.text_binding.currentData())
            self._mark_dirty()

    def _make_text_parameter(self) -> None:
        if self._step() is None or self.action_kind.currentData() != "input_sequence" or self.text_source.currentData() != "constant":
            return
        declarations = self._input_declarations()
        if len(declarations) >= 128:
            ui(self.status.setText, tr('输入参数已达上限，请先整理工作流输入。'))
            return
        names = {item["name"] for item in declarations}
        index = next(i for i in range(1, len(names) + 2) if f"value_{i}" not in names)
        name, accepted = translated_dialog(QInputDialog.getText, self, tr('改为每次输入'), tr('参数名称（已自动生成，可修改；运行时填写本次的值）'), text=f'value_{index}')
        if not accepted:
            return
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}", name):
            ui(self.status.setText, tr('参数名称请使用字母或数字开头，可含下划线和短横线，最多 160 个字符；也可保留自动名称。'))
            return
        if name in names:
            ui(self.status.setText, tr('参数 {v0} 已存在；请在文本来源中选择已有输入，或使用新名称。', v0=name))
            return
        if not self._commit_all():
            return
        self._loading = True
        self._insert_table_row(self.inputs, [name, "text", "是"])
        self.definition["inputs"] = self._input_declarations()
        self._step()["action"]["text"] = {"source": "input", "name": name}
        self._load_selected()
        self._mark_dirty()
        ui(self.status.setText, tr('已改为每次输入：{v0}。保存后，运行时填写本次的值。', v0=name))

    def _text_binding_problem(self):
        for step in self.definition["steps"]:
            text = step["action"].get("text")
            if step["action"]["kind"] != "input_sequence" or not text or text["source"] == "constant":
                continue
            if not text.get("name"):
                return tr('{v0}：请选择要填写的工作流输入或前面步骤的文本结果。', v0=step['title'])
            if text not in [ref for _label, ref in self._text_binding_choices(step, text["source"])]:
                return tr('{v0}：文本来源 {v1} 不可用；请检查名称是否唯一、类型是否为文本，以及来源步骤是否在前面。', v0=step['title'], v1=text['name'])
        return None

    def _update_step_summary(self):
        step = self._step()
        if step is None:
            ui(self.step_heading.setText, tr('选择步骤'))
            ui(self.step_summary.setText, tr('动作、来源和审核状态将在这里显示。'))
            return
        title = self.step_title.text().strip() or step["title"]
        ui(self.step_heading.setText, tr('{title}', title=self._display_title(title)))
        action = next((label for label, value in _ACTIONS if value == self.action_kind.currentData()), self.action_kind.currentData())
        if self.action_kind.currentData() == "click":
            action = tr('单击') if self.click_kind.currentData() == 'single' else tr('双击（现场重新识别）')
            if self.selection_intent.currentData() == "ensure_selected":
                action = tr("确保选中该行")
        source = {"observed": tr("已观测"), "editorial": tr("整理或修改"), "manual": tr("人工添加")}.get(step["provenance"], step["provenance"])
        review = tr("已审核") if self.review.currentData() == "reviewed" else tr("待审核")
        ui(self.step_summary.setText, tr('{action} · {provenance} · {review}', action=action, provenance=source, review=review))

    def _set_clean(self):
        self._dirty = False; self.dirtyChanged.emit(False)
        self._update_definition_summary()
        self._sync_run_context()

    def _update_definition_summary(self):
        if self.snapshot is None:
            ui(self.definition_summary.setText, tr('尚无任务定义。'))
            return
        summary = summarize_definition(self._summary_snapshot)
        source = tr("已保存定义") if summary["saved"] else tr("草稿定义（尚未保存）")
        dirty = (tr("有未保存修改，以下为已保存版本。") if summary["saved"] else
                 tr("有未保存修改，以下为载入的草稿定义。")) if self.dirty else ""
        ui(self.definition_summary.setText, tr('{v0}{v1}：共 {v2} 步，已审核 {v3}，待审核 {v4}。\n定位规则 {v5}/{v6} 个点击或填写步骤；结果规则 {v7}/{v8} 步；仅由 Agent 判断 {v9} 步；图像核验 {v10} 步，未匹配时由 Agent 审核。\n本次定位与核验结果、已记录用量，请在运行页查看。', v0=dirty, v1=source, v2=summary['total_steps'], v3=summary['reviewed_steps'], v4=summary['pending_steps'], v5=summary['target_memory_steps'], v6=summary['target_applicable_steps'], v7=summary['verification_rule_steps'], v8=summary['total_steps'], v9=summary['agent_judgment_steps'] - summary['image_check_steps'], v10=summary['image_check_steps']))

    def _sync_run_context(self):
        if hasattr(self, "run_panel"):
            self.run_panel.set_context(self.snapshot, self._selected_id, dirty=self.dirty)
            self.open_run_button.setEnabled(self.snapshot is not None)

    def _open_run_tab(self):
        self.editor_tabs.setCurrentWidget(self.run_panel)
        if self.dirty or not (self.snapshot or {}).get("program_id"):
            ui(self.status.setText, tr('请先保存工作流，再在运行页连接原会话并运行。'))

    def _run_session_connected(self, session_dir):
        selected = Path(session_dir).resolve()
        self.learning_refresh_button.setEnabled(True)
        if self.session_dir == selected:
            return
        self.session_dir = selected
        self._active_request = None
        self._learning_result = None
        self.open_learning_button.setEnabled(False)
        self.learning_details.hide()
        ui(self.learning_status.setText, tr('已连接现有执行会话；可刷新最近学习或在运行页查看进度。'))

    def _start_read(self, kind, call):
        self._closing_reads = False
        self._sequence += 1
        request = self._sequence
        self._active_request = request
        job = make_job(request, call, self)
        self._jobs[request] = (job, kind)
        job.succeeded.connect(lambda key, value: self._outcomes.__setitem__(key, (True, value)))
        job.failed.connect(lambda key, error: self._outcomes.__setitem__(key, (False, error)))
        job.finished.connect(lambda key=request: self._read_finished(key))
        self.busyChanged.emit(True)
        job.start()

    def _read_finished(self, request):
        job, kind = self._jobs.pop(request)
        ok, value = self._outcomes.pop(request, (False, "后台读取没有返回结果"))
        job.deleteLater()
        if request == self._active_request and not self._closing_reads:
            self._active_request = None
            if self.dirty:
                self._update_definition_summary()
                self._restore_project_choice()
                ui(self.status.setText, tr('读取期间有未保存修改；已保留当前编辑。'))
                if kind == "learning":
                    ui(self.learning_status.setText, tr('已保留当前修改；保存或放弃后可刷新学习状态。'))
            elif not ok:
                if kind != "learning":
                    ui(self.definition_summary.setText, tr('任务定义读取失败；暂不显示定义摘要。'))
                self._restore_project_choice()
                label = self.learning_status if kind == "learning" else self.status
                ui(label.setText, tr('读取失败：{v0}', v0=_error_text(value)))
                label.setToolTip(str(value))
            elif kind == "list":
                self._install_projects(value)
            elif kind == "learning":
                self._show_learning(value)
            else:
                self._install(value)
                self.refresh_learning()
        self.busyChanged.emit(self.is_busy)

    def _restore_project_choice(self):
        if self.snapshot is None:
            return
        self.projects.blockSignals(True)
        _choice(self.projects, self.snapshot["workflow_id"])
        self.projects.blockSignals(False)

    def refresh(self):
        if self.dirty:
            ui(self.status.setText, tr('请先保存或放弃修改，再刷新项目。'))
            return
        ui(self.status.setText, tr('正在读取项目…'))
        ui(self.definition_summary.setText, tr('正在读取任务定义…'))
        self._start_read("list", self.facade.list_workflow_projects)

    def _install_projects(self, values):
        if not isinstance(values, list):
            ui(self.definition_summary.setText, tr('任务定义读取失败；项目列表格式无效。'))
            ui(self.status.setText, tr('项目列表格式无效。'))
            return
        selected = self.projects.currentData()
        self.projects.blockSignals(True)
        self.projects.clear()
        for value in values:
            workflow_id = value.get("logical_workflow_id")
            if isinstance(workflow_id, str):
                self.projects.addItem(value.get("title") or workflow_id, workflow_id)
        _choice(self.projects, selected)
        self.projects.blockSignals(False)
        if self.projects.count():
            self.open_project(self.projects.currentData())
        else:
            self.snapshot = None; self.definition = None
            self._update_definition_summary()
            self.steps.clear(); self.relations.clear()
            self.rules_editor.set_step(None, None, 0)
            self.target_editor.set_step(None, None)
            self.program_graph.clear_graph()
            ui(self.program_graph_note.setText, tr('尚无可显示的任务步骤。'))
            self.program_graph_note.show()
            ui(self.status.setText, tr('还没有学习流程。独立界面仍可在界面库审核。'))
            self.refresh_learning()

    def refresh_learning(self):
        if self.session_dir is None:
            return
        if self.dirty:
            ui(self.status.setText, tr('请先保存或放弃修改，再刷新学习草稿。'))
            return
        self._learning_result = None
        self.open_learning_button.setEnabled(False)
        ui(self.learning_status.setText, tr('正在读取最近学习…'))
        self.learning_details.clear()
        self.learning_details.hide()
        self._start_read("learning", lambda: self.facade.read_workflow_learning(self.session_dir))

    def _show_learning(self, value):
        if not isinstance(value, dict):
            ui(self.learning_status.setText, tr('学习状态格式无效；当前工作流保持不变。'))
            return
        self._learning_result = deepcopy(value)
        labels = {'no_learning': tr('这个会话还没有学习记录。'), 'interface_only': tr('最近学习的是独立界面，可在界面库查看。'), 'recording': tr('正在学习；结束后将整理草稿。'), 'awaiting_recording': tr('学习记录尚未完整，请先恢复缺失的回执。'), 'not_requested': tr('学习已结束，等待 Agent 发起整理。'), 'awaiting_agent': tr('等待当前 Agent 整理；完成后刷新即可审核。'), 'awaiting_user': tr('整理暂停，等待你补充；原学习记录已保留。'), 'needs_review': tr('学习内容需要补充，目前没有可审核的工作流草稿。'), 'draft_ready': tr('学习草稿可审核；打开后可修改并保存。'), 'existing_program_preserved': tr('这次学习已有已保存版本；保留现有修改。')}
        state = value.get("status")
        ui(self.learning_status.setText, labels.get(state, tr('学习状态暂不可用，请查看当前 Agent 的结果。')))
        synthesis = value.get("synthesis") or {}
        correction = synthesis.get("last_correction")
        if state in {"awaiting_agent", "awaiting_user"} and isinstance(correction, dict):
            if state == "awaiting_agent":
                ui(self.learning_status.setText, tr('整理需要补充；当前 Agent 可继续修正。'))
            events = (synthesis.get("synthesis_request") or {}).get("events", [])
            errors = correction.get("result", {}).get("errors", [])
            conversation = synthesis.get("conversation") or {}
            if state == "awaiting_user":
                lines = [tr("自动纠错已用完。请在原 Agent 对话中补充以下内容或明确要求继续，修正后刷新本页。")]
            elif conversation.get("state") == "correct_once":
                lines = [tr("当前 Agent 可自动修正一次。若连接中断，请回原 Agent 对话继续；刷新本页不会调用模型。")]
            else:
                lines = [tr("请在原 Agent 对话中继续整理，修正后刷新本页。")]
            if correction.get("ordering") == "unknown":
                lines.append(tr("这是历史待修记录，先后顺序未知。"))
            reasons = {'verification_target_invalid': tr('成功条件缺少有效的控件名称或类型'), 'learning_annotation_invalid': tr('步骤定义含有不支持或不完整的内容'), 'parameter_binding_invalid': tr('输入来源或参数声明不完整'), 'parameter_example_mismatch': tr('示例值与原操作记录不一致'), 'learning_target_semantics_mismatch': tr('目标含义与原操作证据不一致'), 'learning_compiler_unknown_event': tr('整理引用的操作不在本次学习记录中')}
            fields = {"verification": "成功条件", "read_spec": "读取规则", "outputs": "输出声明",
                      "parameter_bindings": "输入参数", "annotations": "步骤定义", "title": "步骤名称"}
            for error in errors:
                index = next((i for i, event in enumerate(events) if event.get("event_id") == error.get("event_id")), None)
                hints = (events[index].get("action_hints") or {}) if index is not None else {}
                title = hints.get("goal") or hints.get("field_goal")
                label = tr("第 {v0} 个操作", v0=index + 1) if index is not None else tr("整理内容")
                if title:
                    label += "（" + title + "）"
                field = tr(next((fields[key] for key in ("verification", "read_spec", "outputs", "parameter_bindings", "title", "annotations")
                              if key in error.get("field", "")), "步骤内容"))
                reason = reasons.get(error.get("code"), tr("该项内容需要当前 Agent 检查并修正"))
                lines.append(tr("{label} · {field}: {reason}.", label=label, field=field, reason=reason))
            ui(self.learning_details.setPlainText, join_text("\n", lines))
            self.learning_details.setToolTip(json.dumps(errors, ensure_ascii=False))
            self.learning_details.show()
            return
        self.learning_details.setToolTip("")
        draft = (value.get("synthesis") or {}).get("draft")
        if state == "draft_ready" and isinstance(draft, dict):
            steps = draft["definition"]["steps"]
            proposals = draft.get("proposed_target_recipes", [])
            lines = [tr("任务：{v0}", v0=draft['definition']['title']),
                     tr("步骤 {v0} 个 · 目标规则建议 {v1} 个 · 保存前请核对目标和成功条件。", v0=len(steps), v1=len(proposals))]
            reasons = {'proposed_target_rule_requires_review': tr('目标规则需要审核'), 'editorial_verification_unverified': tr('结果检查尚未实测'), 'editorial_read_spec_unverified': tr('读取规则尚未实测'), 'verification_rule_required': tr('缺少成功条件'), 'read_spec_required': tr('缺少读取规则'), 'agent_read_required': tr('需要 Agent 阅读'), 'target_rule_required': tr('缺少目标定位规则'), 'observed_sequence_interrupted': tr('操作顺序曾中断'), 'action_order_unverified': tr('操作先后顺序尚未确认')}
            for item in draft.get("unresolved_items", []):
                lines.append(tr("待核对：") + reasons.get(item["reason"], tr("存在未解决的学习证据或规则")))
            ui(self.learning_details.setPlainText, join_text("\n", lines))
            self.learning_details.show()
            self.open_learning_button.setEnabled(True)

    def open_learning_draft(self):
        if self.dirty:
            ui(self.status.setText, tr('请先保存或放弃当前修改，再打开学习草稿。'))
            return
        value = self._learning_result
        if not isinstance(value, dict) or value.get("status") != "draft_ready":
            return
        draft = value["synthesis"]["draft"]
        baseline = value["program"]
        if baseline.get("program_id") is not None or baseline["workflow_id"] != draft["workflow_id"]:
            ui(self.learning_status.setText, tr('已有已保存版本或来源发生变化，请刷新后查看。'))
            self.open_learning_button.setEnabled(False)
            return
        self.projects.blockSignals(True)
        if self.projects.findData(baseline["workflow_id"]) < 0:
            self.projects.addItem(draft["definition"]["title"], baseline["workflow_id"])
        _choice(self.projects, baseline["workflow_id"])
        self.projects.blockSignals(False)
        self._install({**baseline, "definition": deepcopy(draft["definition"])})
        # 保存沿用载入时的版本摘要；放弃编辑恢复原版本而不是再次装入整理结果。
        self.snapshot = deepcopy(baseline)
        self._draft_recipes = [deepcopy(row["recipe"]) for row in draft.get("proposed_target_recipes", [])
                               if "recipe" in row]
        self.target_editor.set_step(self._step(), self.definition, self._draft_recipes)
        self._mark_dirty()
        self.open_learning_button.setEnabled(False)
        ui(self.status.setText, tr('学习草稿已打开；逐步核对目标、数据来源和成功条件后保存。'))

    def _project_chosen(self, _index):
        workflow_id = self.projects.currentData()
        if workflow_id:
            self.open_project(workflow_id)

    def open_project(self, workflow_id):
        if self.dirty:
            ui(self.status.setText, tr('请先保存或放弃修改，再切换项目。'))
            if self.snapshot:
                self.projects.blockSignals(True)
                _choice(self.projects, self.snapshot["workflow_id"])
                self.projects.blockSignals(False)
            return
        ui(self.status.setText, tr('正在读取任务步骤…'))
        ui(self.definition_summary.setText, tr('正在读取任务定义…'))
        self._start_read("program", lambda: self.facade.load_workflow_program(workflow_id))

    def open_target_link(self, link):
        if self.is_busy or self.dirty or self.run_panel.is_busy:
            ui(self.status.setText, tr('请先完成读取并保存或放弃任务步骤修改，再打开学习框对应的规则。'))
            return False
        program = self.facade.load_workflow_program(link["workflow_id"])
        if program["program_id"] != link["program_id"] or program["content_sha256"] != link["program_sha256"]:
            ui(self.status.setText, tr('工作流版本已变化，请刷新独立界面中的目标列表。'))
            return False
        step = next((row for row in program["definition"]["steps"] if row["step_id"] == link["step_id"]), None)
        if step is None or step["action"].get("target_memory") != link["reference"]:
            ui(self.status.setText, tr('学习框对应的目标规则已变化，请刷新后重试。'))
            return False
        self._install(program)
        self.projects.blockSignals(True)
        _choice(self.projects, link["workflow_id"])
        self.projects.blockSignals(False)
        index = next(i for i in range(self.steps.count()) if self.steps.item(i).data(Qt.ItemDataRole.UserRole) == link["step_id"])
        self.steps.setCurrentRow(index)
        self.editor_tabs.setCurrentIndex(next(i for i in range(self.editor_tabs.count()) if self.editor_tabs.tabText(i) == "目标规则"))
        request = link.get("box_request")
        if request is not None:
            self.target_editor._pending_box = (request["strategy_index"], request["bbox"])
        self.target_editor.load_evidence()
        return True

    def _install(self, snapshot):
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("definition"), dict):
            ui(self.definition_summary.setText, tr('任务定义读取失败；内容无效。'))
            ui(self.status.setText, tr('任务步骤内容无效，保留当前编辑。'))
            return
        self._loading = True
        self.snapshot = deepcopy(snapshot)
        # 摘要描述实际载入内容，独立于保存并发与放弃恢复所用基线。
        self._summary_snapshot = deepcopy(snapshot)
        self.definition = deepcopy(snapshot["definition"])
        self._draft_recipes = []
        self.program_title.setText(self.definition["title"])
        self._set_table(self.inputs, [(x["name"], x["type"], "是" if x["required"] else "否")
                                      for x in self.definition["inputs"]])
        self._selected_id = None
        self._refresh_steps()
        self._loading = False
        self._set_clean()
        self._run_id = None
        self.command_preview.clear()
        self.command_preview.hide()
        self.next_button.setEnabled(False)
        self.prepare_button.setEnabled(True)
        ui(self.status.setText, tr('任务步骤已载入；修改后保存，试运行使用保存的确切版本。'))

    def _set_table(self, table, rows):
        table.blockSignals(True)
        table.setRowCount(0)
        for values in rows:
            self._insert_table_row(table, values)
        table.blockSignals(False)

    def _add_table_row(self, table, values):
        self._insert_table_row(table, values)
        self._mark_dirty()

    def _insert_table_row(self, table, values):
        row = table.rowCount(); table.insertRow(row)
        for column, value in enumerate(values):
            if column == 1 or (table is self.inputs and column == 2):
                combo = QComboBox()
                choices = _TYPES if column == 1 else (("是", "是"), ("否", "否"))
                for label, key in choices:
                    ui(combo.addItem, tr(label), key)
                _choice(combo, value)
                combo.currentIndexChanged.connect(self._mark_dirty)
                table.setCellWidget(row, column, combo)
            else:
                table.setItem(row, column, QTableWidgetItem(str(value)))

    def _remove_table_row(self, table):
        if table.currentRow() >= 0:
            table.removeRow(table.currentRow())
            self._mark_dirty()

    def _refresh_steps(self):
        self.steps.blockSignals(True)
        self.steps.clear(); self.relations.clear()
        chosen = None
        for step in self.definition["steps"]:
            item = ui(QListWidgetItem, self._step_list_label(step))
            item.setData(Qt.ItemDataRole.UserRole, step["step_id"])
            self.steps.addItem(item)
            if step["step_id"] == self._selected_id:
                chosen = item
            self.relations.addTopLevelItem(QTreeWidgetItem())
            self._render_relation_row(self.relations.topLevelItemCount() - 1)
        self.steps.setCurrentItem(chosen or (self.steps.item(0) if self.steps.count() else None))
        self.steps.blockSignals(False)
        self._selected_id = self.steps.currentItem().data(Qt.ItemDataRole.UserRole) if self.steps.currentItem() else None
        self._load_selected()
        self._refresh_program_graph()

    def _refresh_program_graph(self):
        if self.definition is None or not self.definition.get("steps"):
            self.program_graph.clear_graph()
            ui(self.program_graph_note.setText, tr('尚无可显示的任务步骤。'))
            self.program_graph_note.show()
            return
        try:
            self.program_graph.set_program_graph(self.definition)
        except ValueError:
            self.program_graph.clear_graph()
            ui(self.program_graph_note.setText, tr('步骤或分支尚未填写完整；当前修改仍在编辑器中，保存前请补齐。'))
            self.program_graph_note.show()
            return
        self.program_graph_note.hide()

    def _relation_view_chosen(self, index):
        if index == 1 and self.definition is not None:
            if self._commit_selected():
                self._refresh_program_graph()

    def _graph_node_chosen(self, step_id):
        for index in range(self.steps.count()):
            if self.steps.item(index).data(Qt.ItemDataRole.UserRole) == step_id:
                self.steps.setCurrentRow(index)
                return

    def _step_list_label(self, step):
        kind = next((label for label, value in _ACTIONS if value == step["action"]["kind"]), step["action"]["kind"])
        if step["action"].get("selection_intent") == "ensure_selected":
            kind = tr("确保选中该行")
        review = tr("已审核") if step["review_status"] == "reviewed" else tr("待审核")
        return tr('{title}\n{kind} · {review}', title=self._display_title(step["title"]), kind=kind, review=review)

    @staticmethod
    def _display_title(title):
        return next((label for label, value in _ACTIONS if title == value), title)

    def _relation_chosen(self, item, _column):
        index = self.relations.indexOfTopLevelItem(item)
        if index >= 0:
            self.steps.setCurrentRow(index)
            self.nav_tabs.setCurrentIndex(0)

    def _step(self, step_id=None):
        if self.definition is None:
            return None
        identity = self._selected_id if step_id is None else step_id
        return next((step for step in self.definition["steps"] if step["step_id"] == identity), None)

    def _render_relation_row(self, index):
        step = self.definition["steps"][index]
        titles = {item["step_id"]: self._display_title(item["title"]) for item in self.definition["steps"]}
        row = self.relations.topLevelItem(index)
        row.setText(0, self._display_title(step["title"]))
        ui(row.setText, 1, tr('{title}', title=titles.get(step['branches']['success'], tr('暂停'))))
        ui(row.setText, 2, tr('{title}', title=titles.get(step['branches']['failure'], tr('暂停'))))

    def _step_chosen(self, current, _previous):
        if self._loading:
            return
        if not self._commit_selected():
            old_index = next((index for index in range(self.steps.count())
                              if self.steps.item(index).data(Qt.ItemDataRole.UserRole) == self._selected_id), -1)
            self.steps.blockSignals(True)
            self.steps.setCurrentRow(old_index)
            self.steps.blockSignals(False)
            return
        self._selected_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._load_selected()

    def _load_selected(self):
        step = self._step()
        self._loading = True
        enabled = step is not None
        self._selection_intent_pending = False
        for widget in (self.step_title, self.action_kind, self.click_kind, self.selection_intent, self.goal, self.field_goal, self.text_source,
                       self.text_value, self.text_binding, self.parameterize_button, self.clear_existing, self.submit_search,
                       self.scroll_direction, self.scroll_amount, self.key, self.success, self.failure,
                       self.review, self.preconditions, self.success_conditions, self.outputs):
            widget.setEnabled(enabled)
        self.empty.setVisible(not enabled)
        if step:
            self.step_title.setText(step["title"])
            action = step["action"]
            _choice(self.action_kind, action["kind"])
            _choice(self.click_kind, action.get("click_kind", "single"))
            _choice(self.selection_intent, action.get("selection_intent"))
            self.goal.setText(action.get("goal", ""))
            self.field_goal.setText(action.get("field_goal", ""))
            text = action.get("text") or {"source": "constant", "value": ""}
            _choice(self.text_source, text["source"])
            self.text_value.setText(str(text.get("value", "")))
            self._text_reference = deepcopy(text) if text["source"] != "constant" else None
            index = self.definition["steps"].index(step)
            self.clear_existing.setChecked(action.get("clear_existing", True))
            self.submit_search.setChecked(action.get("submit_search", False))
            _choice(self.scroll_direction, action.get("direction", "down"))
            self.scroll_amount.setValue(action.get("amount", 1))
            _choice(self.key, action.get("key", "Enter"))
            self.success.clear(); self.failure.clear()
            for combo in (self.success, self.failure):
                ui(combo.addItem, tr('暂停／无跳转'), None)
                for other in self.definition["steps"]:
                    if other["step_id"] != step["step_id"]:
                        combo.addItem(other["title"], other["step_id"])
                _choice(combo, step["branches"]["success" if combo is self.success else "failure"])
            _choice(self.review, step["review_status"])
            ui(self.provenance.setText, {'observed': tr('已观测'), 'editorial': tr('整理或修改'), 'manual': tr('人工添加')}.get(step['provenance'], step['provenance']))
            self.preconditions.set_steps(self.definition["steps"][:index])
            self.success_conditions.set_steps(self.definition["steps"][:index])
            self.preconditions.set_conditions(step["preconditions"])
            self.success_conditions.set_conditions(step["success_conditions"])
            self._set_table(self.outputs, [(x["name"], x["type"]) for x in step["outputs"]])
        index = self.definition["steps"].index(step) if step else 0
        self.rules_editor.set_step(step, self.definition, index)
        image_options = []
        if step and self.snapshot and hasattr(self.facade, 'read_workflow_image_options'):
            try:
                image_options = self.facade.read_workflow_image_options(
                    self.snapshot['workflow_id'], self.snapshot['project_snapshot_id'],
                    step.get('target_node_id'))
            except (ValueError, OSError, RuntimeError, KeyError):
                image_options = []
        self.rules_editor.set_image_options(image_options)
        self.target_editor.set_step(step, self.definition, self._draft_recipes)
        self._refresh_text_bindings()
        self._update_action_fields()
        self._update_step_summary()
        self._loading = False
        self._sync_run_context()

    def _update_action_fields(self, *_args):
        kind = self.action_kind.currentData()
        self.rules_editor.set_action_kind(kind)
        def show(widget, visible):
            widget.setVisible(visible)
            label = self._form.labelForField(widget)
            if label is not None:
                label.setVisible(visible)
        show(self.goal, kind in {"click", "read_text"})
        show(self.click_kind, kind == "click")
        show(self.selection_intent, kind == "click")
        self.selection_intent.setEnabled(kind == "click" and self._step() is not None
            and self.click_kind.currentData() == "single" and self._selection_rule_available())
        for widget in (self.field_goal, self.text_source, self.clear_existing, self.submit_search):
            show(widget, kind == "input_sequence")
        constant = self.text_source.currentData() == "constant"
        show(self.text_value, kind == "input_sequence" and constant)
        show(self.parameterize_button, kind == "input_sequence" and constant)
        show(self.text_binding, kind == "input_sequence" and not constant)
        for widget in (self.scroll_direction, self.scroll_amount): show(widget, kind == "scroll")
        show(self.key, kind == "press_key")

    def _selection_rule_available(self):
        # 使用当前普通目标编辑器的规则，保留尚未应用的组合编辑。
        strategies = self.target_editor._strategies
        if len(strategies) != 1:
            return False
        rule = strategies[0]
        return (rule.get("kind") == "visible_row" and rule.get("row", {}).get("control_type") == "ListItem"
                and rule.get("action", {}).get("source") == "row_name"
                and rule.get("action", {}).get("control_type") == "Edit")

    def _selection_intent_changed(self, *_args):
        if self._loading or self._step() is None:
            return
        self._selection_intent_pending = True
        self._mark_dirty()
        self._update_step_summary()
        self.editor_tabs.setCurrentIndex(next(index for index in range(self.editor_tabs.count())
            if self.editor_tabs.tabText(index) == "目标规则"))
        ui(self.status.setText, tr('选择意图已修改；请在目标规则页预览学习截图并应用，再保存和审核。'))

    def _commit_selected(self, *, allow_target_draft=False):
        step = self._step()
        if not step:
            return True
        if self._selection_intent_pending and not allow_target_draft:
            ui(self.status.setText, tr('选择意图有未应用修改；请在目标规则页预览并应用后保存。'))
            return False
        if self.target_editor.has_unapplied_changes and not allow_target_draft:
            ui(self.status.setText, tr('目标规则有未应用修改；请先预览并应用，或放弃本次修改。'))
            return False
        previous_action = step["action"]
        kind = self.action_kind.currentData()
        verification, read_spec = self.rules_editor.rules(kind)
        if self.rules_editor.validation_error:
            ui(self.status.setText, tr('规则未保存；') + self.rules_editor.validation_error)
            return False
        step["title"] = self.step_title.text().strip()
        if kind in {"click", "read_text"}:
            action = {"kind": kind, "goal": self.goal.text().strip()}
            if kind == "click" and (self.click_kind.currentData() != "single" or "click_kind" in previous_action):
                action["click_kind"] = self.click_kind.currentData()
            if kind == "click" and self.selection_intent.currentData() is not None:
                if self.click_kind.currentData() != "single":
                    ui(self.status.setText, tr('确保选中仅支持单击；双击不能使用该选择意图。'))
                    return False
                # 重开后无需加载规则即可保存非语义修改；新意图必须来自已加载的行规则。
                if self._selection_intent_pending and not self._selection_rule_available():
                    ui(self.status.setText, tr('确保选中需要唯一的可见行名称规则（ListItem／Edit）；请先修改目标规则。'))
                    return False
                action["selection_intent"] = self.selection_intent.currentData()
        elif kind == "input_sequence":
            source = self.text_source.currentData()
            binding = ({"source": "constant", "value": self.text_value.text()} if source == "constant"
                       else deepcopy(self._text_reference) or {"source": source, "name": ""})
            if source == "output" and "step_id" not in binding:
                binding["step_id"] = ""
            action = {"kind": kind, "field_goal": self.field_goal.text().strip(), "text": binding,
                      "clear_existing": self.clear_existing.isChecked(), "submit_search": self.submit_search.isChecked()}
        elif kind == "scroll":
            action = {"kind": kind, "direction": self.scroll_direction.currentData(), "amount": self.scroll_amount.value()}
        else:
            action = {"kind": kind, "key": self.key.currentText()}
        reference = previous_action.get("target_memory")
        if reference is not None and (
                (kind == "click" and previous_action.get("kind") == kind
                 and previous_action.get("goal") == action.get("goal")
                 and previous_action.get("click_kind", "single") == action.get("click_kind", "single"))
                or (kind == "input_sequence" and previous_action.get("kind") == kind
                    and previous_action.get("field_goal") == action.get("field_goal")
                    and previous_action.get("submit_search") == action.get("submit_search"))):
            action["target_memory"] = deepcopy(reference)
        step["action"] = action
        if previous_action.get("kind") != kind:
            step.pop("source_evidence", None)
        step["branches"] = {"success": self.success.currentData(), "failure": self.failure.currentData(), "uncertain": None}
        step["review_status"] = self.review.currentData()
        step["preconditions"] = self.preconditions.conditions()
        step["success_conditions"] = self.success_conditions.conditions()
        step["outputs"] = [{"name": _cell(self.outputs, row, 0), "type": _cell(self.outputs, row, 1)}
                           for row in range(self.outputs.rowCount())]
        if verification is None:
            step.pop("verification", None)
        else:
            step["verification"] = verification
        if read_spec is None:
            step.pop("read_spec", None)
        else:
            step["read_spec"] = read_spec
        index = self.definition["steps"].index(step)
        ui(self.steps.item(index).setText, self._step_list_label(step))
        self._render_relation_row(index)
        self._refresh_program_graph()
        return True

    def _commit_all(self, *, allow_target_draft=False):
        if not self._commit_selected(allow_target_draft=allow_target_draft):
            return False
        self.definition["title"] = self.program_title.text().strip()
        self.definition["inputs"] = self._input_declarations()
        return True

    def _target_action(self):
        if not self._commit_all(allow_target_draft=True):
            return None
        step = self._step()
        return deepcopy(step["action"]) if step else None

    def _target_tab_chosen(self, index):
        if self.editor_tabs.tabText(index) == "目标规则" and self.definition is not None:
            if self._commit_all(allow_target_draft=True):
                self.target_editor.refresh_definition(self.definition)

    def _apply_target_proposal(self, value):
        step = self._step()
        if (step is None or step["step_id"] != value.get("step_id")
                or self._target_action() != value.get("original_action")):
            ui(self.status.setText, tr('当前步骤或动作已变化，请重新预览目标。'))
            return
        result = value["result"]
        if result.get("preview_scope") != "learning_capture" or result.get("preview", {}).get("status") != "matched":
            ui(self.status.setText, tr('目标尚未在学习证据中唯一匹配，修订未应用。'))
            return
        recipe = deepcopy(result["recipe"])
        self._selection_intent_pending = False
        step["action"]["target_memory"] = deepcopy(result["reference"])
        step["provenance"] = "editorial"
        step["review_status"] = "pending"
        self._draft_recipes = [row for row in self._draft_recipes if row["recipe_id"] != recipe["recipe_id"]] + [recipe]
        self._loading = True
        _choice(self.review, "pending")
        ui(self.provenance.setText, tr('整理或修改'))
        self._loading = False
        self._refresh_steps()
        self._mark_dirty()
        ui(self.status.setText, tr('目标规则已修改，保存后成为待验证的新版本；原操作证据保持可追溯。'))

    def add_step(self):
        if self.definition is None: return
        if not self._commit_all(): return
        identity = "manual-" + uuid4().hex[:12]
        self.definition["steps"].append({"step_id": identity, "title": "新步骤", "source_node_id": None,
            "target_node_id": None, "action": {"kind": "click", "goal": ""},
            "preconditions": [], "success_conditions": [],
            "branches": {"success": None, "failure": None, "uncertain": None}, "outputs": [],
            "review_status": "pending", "provenance": "manual"})
        self._selected_id = identity
        self._refresh_steps(); self._mark_dirty()

    def delete_step(self):
        if not self._selected_id: return
        if not self._commit_all(): return
        identity = self._selected_id
        refs = []
        for step in self.definition["steps"]:
            if step["step_id"] == identity: continue
            if identity in step["branches"].values(): refs.append(tr('{title}的跳转', title=step['title']))
            if step["action"].get("text", {}).get("step_id") == identity: refs.append(tr('{title}的输入', title=step['title']))
            for key in ("preconditions", "success_conditions"):
                if any(item["left"].get("step_id") == identity for item in step[key]):
                    refs.append(tr('{title}的条件', title=step['title']))
            expected = (step.get("verification") or {}).get("expected") or {}
            if expected.get("source") == "output" and expected.get("step_id") == identity:
                refs.append(tr('{title}的结果判断', title=step['title']))
        if any(item.get("step_id") == identity for item in self.definition.get("outputs", [])):
            refs.append(tr("任务输出"))
        if refs:
            ui(self.status.setText, tr('删除前请先修复引用：') + join_text(tr('、'), refs))
            return
        self.definition["steps"] = [step for step in self.definition["steps"] if step["step_id"] != identity]
        self._selected_id = None
        self._refresh_steps(); self._mark_dirty()

    def move_step(self, offset):
        if not self._selected_id: return
        if not self._commit_all(): return
        steps = self.definition["steps"]
        source = next(i for i, step in enumerate(steps) if step["step_id"] == self._selected_id)
        target = source + offset
        if 0 <= target < len(steps):
            steps[source], steps[target] = steps[target], steps[source]
            self._refresh_steps(); self._mark_dirty()

    def save(self):
        if self.snapshot is None or (not self.dirty and self.snapshot.get("program_id") is not None): return
        if not self._commit_all(): return
        problem = self._text_binding_problem()
        if problem:
            ui(self.status.setText, tr('保存失败；') + problem)
            return
        try:
            referenced = {step["action"]["target_memory"]["recipe_id"] for step in self.definition["steps"]
                          if "target_memory" in step["action"]}
            recipes = [recipe for recipe in self._draft_recipes if recipe["recipe_id"] in referenced]
            value = self.facade.save_workflow_program(self.snapshot["workflow_id"],
                self.snapshot["content_sha256"], deepcopy(self.definition), uuid4().hex,
                **({"target_recipes": recipes} if recipes else {}))
        except Exception as error:
            ui(self.status.setText, tr('保存失败；修改仍在页面中：') + _error_text(error))
            return
        self._install(value)
        self._learning_result = None
        self.open_learning_button.setEnabled(False)
        self.learning_details.hide()
        if self.session_dir is not None:
            ui(self.learning_status.setText, tr('工作流已保存；刷新最近学习可查看最新状态。'))
        ui(self.status.setText, tr('任务步骤已保存；旧版本仍可追溯。'))

    def discard(self):
        if self.snapshot is None: return
        self._install(self.snapshot)
        ui(self.status.setText, tr('已放弃未保存修改。'))

    def _trial_inputs(self):
        inputs = self.definition.get("inputs", [])
        if not inputs: return {}
        dialog = WorkflowInputDialog(inputs, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.values()

    def prepare_trial(self):
        if self.snapshot is None or self._selected_id is None: return
        if self.dirty:
            ui(self.status.setText, tr('请先保存任务步骤，再准备确切版本的试运行。'))
            return
        if self.snapshot.get("program_id") is None:
            ui(self.status.setText, tr('请先保存生成的任务步骤，再准备确切版本的试运行。'))
            return
        if self.session_dir is None:
            ui(self.status.setText, tr('未连接执行会话；请用 --session-dir 指定已有会话后再准备试运行。'))
            return
        try:
            inputs = self._trial_inputs()
            if inputs is None: return
            started = self.facade.start_workflow_trial(self.session_dir, self.snapshot["workflow_id"],
                self.snapshot["program_id"], self._selected_id, inputs, uuid4().hex)
            self._run_id = started["run_id"]
            value = self.facade.prepare_workflow_trial(self.session_dir, self._run_id, uuid4().hex)
            self._show_trial(value)
        except Exception as error:
            ui(self.status.setText, tr('准备失败；未派发输入：') + _error_text(error))

    def _show_trial(self, value):
        state = value.get("status", "未知状态")
        step = value.get("current_step_id") or (value.get("pending") or {}).get("step_id") or value.get("step_id")
        ui(self.trial_note.setText, tr('试运行 · ') + _TRIAL_STATES.get(state, state) + (tr(' · 当前步骤 {v0}', v0=step) if step else ''))
        self.trial_note.setToolTip(str(value.get("run_id", self._run_id)))
        self.next_button.setEnabled(state == "ready" and self._run_id is not None)
        self.prepare_button.setEnabled(state not in {"pending", "cancel_requested"})
        command = value.get("suggested_command") or (value.get("pending") or {}).get("suggested_command")
        if command:
            self.command_preview.setPlainText(json.dumps(command, ensure_ascii=False, indent=2))
        else:
            ui(self.command_preview.setPlainText, tr("当前没有待执行命令。请回读状态或检查缺失输入／观察。"))
        self.command_preview.setVisible(command is not None)
        ui(self.status.setText, tr('等待 Agent 执行当前确切命令并回写回执；工作台没有调用键鼠。') if state == 'pending' else tr('取消已请求；待执行请求需由 Agent 核对，工作台没有派发输入。') if state == 'cancel_requested' else tr('可准备下一步；每次只生成一个待执行请求。') if state == 'ready' else tr('试运行已回读；当前没有可派发命令。'))

    def prepare_next(self):
        if not self._run_id or not self.next_button.isEnabled():
            return
        try:
            value = self.facade.prepare_workflow_trial(self.session_dir, self._run_id, uuid4().hex)
            self._show_trial(value)
        except Exception as error:
            ui(self.status.setText, tr('准备下一步失败；未派发输入：') + _error_text(error))

    def read_trial(self):
        if not self._run_id:
            ui(self.status.setText, tr('当前没有试运行记录。'))
            return
        try:
            value = self.facade.status_workflow_trial(self.session_dir, self._run_id)
            self._show_trial(value)
        except Exception as error:
            ui(self.status.setText, tr('回读失败：') + _error_text(error))

    def cancel_trial(self):
        if not self._run_id: return
        try:
            value = self.facade.cancel_workflow_trial(self.session_dir, self._run_id, uuid4().hex)
            self._show_trial(value)
        except Exception as error:
            ui(self.status.setText, tr('取消失败：') + _error_text(error))

    def cancel_loading(self):
        self._closing_reads = True
        self._active_request = None
        self.target_editor.cancel_loading()
        self.run_panel.cancel_loading()
