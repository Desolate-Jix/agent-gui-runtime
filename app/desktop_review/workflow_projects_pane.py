"""可持续编辑的流程项目；保存记忆不等于执行授权。"""
from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget,
)
from .graph_view import NativeWorkflowGraphView
from .graph_review_pane import GraphReviewPane
from .interface_pane import InterfaceReviewPane
from .interface_picker import InterfacePickerDialog
from .jobs import make_job


class WorkflowProjectsPane(QWidget):
    dirtyChanged = Signal(bool)
    busyChanged = Signal(bool)

    def __init__(self, facade, parent=None):
        super().__init__(parent)
        self.facade = facade
        self.snapshot = None
        self._edges = []
        self._edge_id = None
        self._node_id = None
        self._dirty = False
        self._loading = False
        self._loading_action_editor = False
        self._pending_action_revision = None
        self.interface_picker = None
        self._delete_after_picker = False
        self._read_sequence = 0
        self._read_jobs = {}
        self._read_outcomes = {}
        self._list_request = None
        self._project_request = None
        self._project_job = None
        self._pending_project = None
        self._wanted_project = None
        self._closing_reads = False
        self._build_ui()
        self.refresh()

    @property
    def dirty(self):
        return self._dirty or self.interface_pane.dirty or self.action_evidence_editor._dirty

    @property
    def is_busy(self):
        return bool(self._read_jobs) or self.is_edit_busy

    @property
    def is_edit_busy(self):
        return ((self.interface_picker is not None and self.interface_picker.busy)
                or self.action_evidence_editor._busy or bool(self.action_evidence_editor._jobs))

    def closeEvent(self, event):
        if self.interface_picker is not None and self.interface_picker.busy:
            self.interface_picker.reject()
            event.ignore()
            return
        if self.action_evidence_editor._busy or self.action_evidence_editor._jobs:
            self.status.setText("操作证据仍在读取或保存，请完成后再关闭项目。")
            event.ignore()
            return
        if self.dirty:
            self.status.setText("项目或操作证据有未保存修改；请先保存或放弃修改。")
            event.ignore()
            return
        self.cancel_loading()
        super().closeEvent(event)

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete and self.is_busy:
            self._delete_after_picker = True
            self.cancel_loading()
            if self.interface_picker is not None and self.interface_picker.busy:
                self.interface_picker.reject()
            else:
                QTimer.singleShot(0, self._finish_deferred_delete)
            return True
        return super().event(event)

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.status = QLabel("打开项目，选择界面或连线直接修改。保存后可继续修改，无需定稿。")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget(); sidebar = QVBoxLayout(left)
        self.project_list = QListWidget()
        self.project_list.setMinimumWidth(180)
        sidebar.addWidget(QLabel("流程项目")); sidebar.addWidget(self.project_list, 1)
        self.create_button = QPushButton("新建流程项目")
        self.refresh_button = QPushButton("刷新项目")
        sidebar.addWidget(self.create_button); sidebar.addWidget(self.refresh_button)
        split.addWidget(left)
        center = QWidget(); layout = QVBoxLayout(center)
        self.title_edit = QLineEdit(); self.title_edit.setPlaceholderText("流程项目名称")
        layout.addWidget(self.title_edit)
        self.graph_view = NativeWorkflowGraphView()
        self.graph_view.setMinimumHeight(210)
        layout.addWidget(self.graph_view, 2)
        graph_actions = QHBoxLayout()
        self.fit_button = QPushButton("查看全图")
        self.link_button = QPushButton("新增跳转关系")
        self.remove_node_button = QPushButton("移除选中界面")
        for button in (self.fit_button, self.link_button, self.remove_node_button):
            graph_actions.addWidget(button)
        layout.addLayout(graph_actions)
        membership = QHBoxLayout()
        self.attach_button = QPushButton("＋ 添加已有界面")
        membership.addWidget(self.attach_button)
        membership_note = QLabel("从界面库挑选，可搜索、多选；加入后再连接跳转关系。")
        membership_note.setWordWrap(True)
        membership.addWidget(membership_note, 1)
        layout.addLayout(membership)
        self.details = QStackedWidget()
        self.empty_detail = QLabel("点击图中的界面查看截图和识别框；点击连线修改跳转。")
        self.empty_detail.setWordWrap(True)
        self.details.addWidget(self.empty_detail)
        self.interface_pane = InterfaceReviewPane(self.facade)
        self.interface_pane.saved.connect(self._interface_saved)
        self.interface_pane.errorRaised.connect(self.status.setText)
        self.details.addWidget(self.interface_pane)
        self.action_evidence_editor = GraphReviewPane(self.facade)
        # 项目已有总图，证据编辑区只显示原图和字段，避免重复图挤压截图。
        self.action_evidence_editor.graph_box.hide()
        self.action_evidence_editor.review_graph_button.hide()
        self.action_evidence_editor.graph_relearn_button.hide()
        self.action_evidence_editor.status_label.setText(
            "这是流程中的权威动作证据节点，不是独立学习界面；保存只修改当前图草稿，不授予执行权限。")
        self.action_evidence_editor.dirtyChanged.connect(lambda _value: self.dirtyChanged.emit(self.dirty))
        self.action_evidence_editor.busyChanged.connect(self._action_busy_changed)
        self.action_evidence_editor.errorRaised.connect(self.status.setText)
        self.action_evidence_editor.revisionChanged.connect(self._action_revision_changed)
        self.details.addWidget(self.action_evidence_editor)
        self.edge_editor = QWidget(); form = QFormLayout(self.edge_editor)
        self.edge_source = QComboBox(); self.edge_target = QComboBox()
        self.edge_region = QComboBox(); self.edge_action = QComboBox()
        for label, value in (("点击", "click"), ("填写文本", "fill_field"), ("观察", "observe"),
                             ("打开详情", "open_detail"), ("继续下一步", "continue_next_step")):
            self.edge_action.addItem(label, value)
        self.edge_action.setEditable(True)
        self.edge_result = QLineEdit(); self.edge_condition = QLineEdit()
        for label, control in (("从哪个界面", self.edge_source), ("操作哪个框", self.edge_region),
                               ("操作", self.edge_action), ("到哪个界面", self.edge_target),
                               ("预期变化", self.edge_result), ("跳转条件", self.edge_condition)):
            form.addRow(label, control)
        self.edge_note = QLabel("人工修改的是流程记忆；尚未验证的关系不会被当作执行证据。")
        self.edge_note.setWordWrap(True); form.addRow(self.edge_note)
        self.remove_edge_button = QPushButton("删除这条关系")
        form.addRow(self.remove_edge_button)
        self.details.addWidget(self.edge_editor)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        detail_scroll.setWidget(self.details)
        layout.addWidget(detail_scroll, 3)
        save_row = QHBoxLayout()
        self.save_button = QPushButton("保存项目修改")
        self.discard_button = QPushButton("放弃项目修改")
        save_row.addWidget(self.save_button); save_row.addWidget(self.discard_button); save_row.addStretch()
        layout.addLayout(save_row)
        split.addWidget(center); split.setSizes([210, 1030])
        root.addWidget(split, 1)
        self.project_list.currentItemChanged.connect(self._selected)
        self.refresh_button.clicked.connect(self.refresh)
        self.create_button.clicked.connect(self.create_project)
        self.attach_button.clicked.connect(self.attach_interface)
        self.remove_node_button.clicked.connect(self.detach_interface)
        self.graph_view.nodeSelected.connect(self.node_selected)
        self.graph_view.edgeSelected.connect(self.edge_selected)
        self.fit_button.clicked.connect(self.graph_view.fit_graph)
        self.link_button.clicked.connect(self.add_edge)
        self.remove_edge_button.clicked.connect(self.remove_edge)
        self.save_button.clicked.connect(self.save_current)
        self.discard_button.clicked.connect(self.discard_changes)
        self.title_edit.textChanged.connect(self._mark_dirty)
        self.edge_source.currentIndexChanged.connect(self._source_changed)
        for control in (self.edge_target, self.edge_region, self.edge_action):
            control.currentIndexChanged.connect(self._edge_changed)
        self.edge_action.editTextChanged.connect(self._edge_changed)
        self.edge_result.textChanged.connect(self._edge_changed)
        self.edge_condition.textChanged.connect(self._edge_changed)

    def _allow_replace(self):
        if self.is_edit_busy:
            self.status.setText("界面选择器仍在读取或保存，请完成后再修改项目。")
            return False
        if self.dirty:
            self.status.setText("请先保存或放弃修改，再切换、刷新或改变项目成员。")
            return False
        return True

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.graph_view.fit_graph)

    def refresh(self):
        if not self._allow_replace(): return
        if self._list_request is not None:
            return
        self._closing_reads = False
        self._project_request = None
        self._pending_project = None
        current = self.project_list.currentItem()
        if current is not None:
            self._wanted_project = current.data(Qt.ItemDataRole.UserRole)
        elif self.snapshot is not None:
            self._wanted_project = self.snapshot['logical_workflow_id']
        self._read_sequence += 1
        self._list_request = self._read_sequence
        self.status.setText("正在读取流程项目列表…可继续切换页面或关闭窗口。")
        operation = getattr(self.facade, 'list_workflow_project_summaries', None)
        self._start_read('list', self._list_request,
                         operation if callable(operation) else self.facade.list_workflow_projects)

    def _start_read(self, kind, request_id, operation):
        job = make_job(request_id, operation, self)
        self._read_jobs[request_id] = (job, kind)
        if kind == 'project':
            self._project_job = job
        job.succeeded.connect(self._read_succeeded)
        job.failed.connect(self._read_failed)
        job.finished.connect(lambda: self._read_finished(request_id))
        self._update_loading_controls()
        self.busyChanged.emit(True)
        job.start()

    def _read_succeeded(self, request_id, value):
        self._read_outcomes[request_id] = (True, value)

    def _read_failed(self, request_id, error):
        self._read_outcomes[request_id] = (False, error)

    def _read_finished(self, request_id):
        job, kind = self._read_jobs.pop(request_id)
        outcome = self._read_outcomes.pop(request_id, (False, "后台任务没有返回结果"))
        job.deleteLater()
        if kind == 'project':
            self._project_job = None
        expected = self._list_request if kind == 'list' else self._project_request
        if request_id == expected and not self._closing_reads and not self._delete_after_picker:
            if kind == 'list':
                self._list_request = None
            else:
                self._project_request = None
            if self.dirty:
                self._restore_project_selection()
                self.status.setText("读取期间出现未保存修改，已保留编辑；请保存或放弃后再刷新。")
            elif not outcome[0]:
                self._restore_project_selection()
                self.status.setText(("读取项目失败：" if kind == 'list' else "打开项目失败：")
                                    + str(outcome[1]).splitlines()[0])
                self.status.setToolTip(str(outcome[1]))
            else:
                try:
                    if kind == 'list':
                        self._install_directory(outcome[1])
                    else:
                        self._install(outcome[1])
                except Exception as error:
                    self._restore_project_selection()
                    self.status.setText(f"项目内容无效，未替换当前编辑：{error}")
        if self._project_job is None and self._pending_project is not None:
            pending_id, workflow_id = self._pending_project
            self._pending_project = None
            if pending_id == self._project_request and not self.dirty and not self._closing_reads:
                self._start_read('project', pending_id,
                                 lambda: self.facade.load_workflow_project(workflow_id))
            elif pending_id == self._project_request:
                self._project_request = None
                self._restore_project_selection()
        self._update_loading_controls()
        self.busyChanged.emit(self.is_busy)

    def _install_directory(self, values):
        if not isinstance(values, list) or any(not isinstance(value, dict)
                or not isinstance(value.get('logical_workflow_id'), str) for value in values):
            raise ValueError("流程项目摘要无效")
        self.project_list.blockSignals(True)
        try:
            self.project_list.clear()
            target = None
            for value in values:
                item = QListWidgetItem(value.get('title') or value['logical_workflow_id'])
                item.setData(Qt.ItemDataRole.UserRole, value['logical_workflow_id'])
                self.project_list.addItem(item)
                if value['logical_workflow_id'] == self._wanted_project:
                    target = item
            if target is None and values and self._wanted_project is None:
                target = self.project_list.item(0)
            self.project_list.setCurrentItem(target)
        finally:
            self.project_list.blockSignals(False)
        if target is not None:
            self._request_project(target.data(Qt.ItemDataRole.UserRole))
        elif self._wanted_project is not None:
            self.status.setText("所属学习流程暂不可用，请刷新；未创建替代流程。")
        else:
            self.snapshot = None
            self.graph_view.clear_graph()
            self.details.setCurrentWidget(self.empty_detail)
            self.status.setText("还没有流程项目。可以新建项目，然后加入已学界面并连接关系。")

    def _request_project(self, workflow_id):
        if self._project_request is not None and self._wanted_project == workflow_id:
            return
        self._wanted_project = workflow_id
        self._read_sequence += 1
        self._project_request = self._read_sequence
        self.status.setText("正在打开流程项目…可选择其他项目或切换页面。")
        if self._project_job is not None:
            self._pending_project = (self._project_request, workflow_id)
            return
        self._start_read('project', self._project_request,
                         lambda: self.facade.load_workflow_project(workflow_id))

    def _restore_project_selection(self):
        workflow_id = self.snapshot['logical_workflow_id'] if self.snapshot else None
        self.project_list.blockSignals(True)
        try:
            selected = next((self.project_list.item(index) for index in range(self.project_list.count())
                             if self.project_list.item(index).data(Qt.ItemDataRole.UserRole) == workflow_id), None)
            self.project_list.setCurrentItem(selected)
        finally:
            self.project_list.blockSignals(False)
        self._wanted_project = workflow_id

    def _update_loading_controls(self):
        loading = self._list_request is not None or self._project_request is not None
        for widget in (self.title_edit, self.graph_view, self.details, self.save_button,
                       self.discard_button, self.create_button, self.attach_button,
                       self.link_button, self.remove_node_button):
            widget.setEnabled(not loading and not self._closing_reads)

    def cancel_loading(self):
        """停止装入结果；在途只读任务自然结束前仍由页面持有。"""
        self._closing_reads = True
        self._list_request = None
        self._project_request = None
        self._pending_project = None
        self._update_loading_controls()

    def _selected(self, current, previous):
        if not self._allow_replace():
            self.project_list.blockSignals(True); self.project_list.setCurrentItem(previous)
            self.project_list.blockSignals(False); return
        if current is None: return
        workflow_id = current.data(Qt.ItemDataRole.UserRole)
        if self._list_request is not None:
            self._wanted_project = workflow_id
            return
        self._request_project(workflow_id)

    def open_project(self, workflow_id: str) -> None:
        """选择已有学习项目，不创建副本。"""
        if not self._allow_replace():
            return
        if self._list_request is not None:
            self._wanted_project = workflow_id
            return
        for index in range(self.project_list.count()):
            item = self.project_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == workflow_id:
                self.project_list.blockSignals(True)
                self.project_list.setCurrentItem(item)
                self.project_list.blockSignals(False)
                if (self._project_request is not None or self.snapshot is None
                        or self.snapshot["logical_workflow_id"] != workflow_id):
                    self._request_project(workflow_id)
                return
        self.status.setText("所属学习流程暂不可用，请刷新；未创建替代流程。")

    def _install(self, snapshot):
        self.graph_view.set_project(snapshot)
        # 外部保存或显式装入也会使旧后台读取失效。
        self._list_request = None
        self._project_request = None
        self._pending_project = None
        self._wanted_project = snapshot['logical_workflow_id']
        self.snapshot = deepcopy(snapshot)
        self._loading = True
        self.title_edit.setText(snapshot['graph']['workflow']['goal'])
        self._edges = deepcopy(snapshot['graph']['edges'])
        self._edge_id = None; self._node_id = None
        self.details.setCurrentWidget(self.empty_detail)
        self._loading = False; self._dirty = False
        warnings = snapshot.get('warnings') or []
        from .learning_catalog import learning_project_notice
        notice = learning_project_notice(snapshot)
        self.status.setText("；".join([notice, *map(str, warnings)]) if notice or warnings else "项目可持续修改。界面按最新保存内容显示；点击节点查看内容，点击连线修改关系。")
        self.dirtyChanged.emit(False)
        self._update_loading_controls()

    def node_selected(self, node_id):
        if self._dirty:
            self.status.setText("项目关系有未保存修改。请先保存项目，再编辑界面内容。")
            return
        if self.interface_pane.dirty:
            self.status.setText("请先保存或放弃当前界面修改。")
            if self._node_id: self.graph_view.select_node(self._node_id)
            return
        node = next((n for n in self.snapshot['graph']['nodes'] if n['node_id'] == node_id), None)
        if node is None: return
        self._node_id = node_id; self._edge_id = None
        reference = node.get('interface_reference')
        if not reference:
            source = self.facade.load_graph_revision(
                self.snapshot['logical_workflow_id'], self.snapshot['source_revision'])
            if source.get('source_refs', {}).get('kind') != 'recorded_actions':
                self.empty_detail.setText("这是原学习图中的证据节点；当前项目不能直接修改。独立界面可通过“加入已有界面”添加。")
                self.details.setCurrentWidget(self.empty_detail); return
            try:
                self._loading_action_editor = True
                if not self.action_evidence_editor.set_revision(
                        source, initial_selection=("node", node_id)):
                    return
                self.details.setCurrentWidget(self.action_evidence_editor)
                self.graph_view.select_node(node_id)
            finally:
                self._loading_action_editor = False
            return
        try:
            value = self.facade.load_interface_content(reference['interface_id'], reference['version_id'])
            latest = self.facade.load_interface_content(reference['interface_id'])
            if latest['version_id'] != reference['version_id']:
                self._install(self.facade.load_workflow_project(self.snapshot['logical_workflow_id']))
                return self.node_selected(node_id)
            self.interface_pane.set_read_only(False)
            self.interface_pane.set_snapshot(value)
            self.details.setCurrentWidget(self.interface_pane)
            self.graph_view.select_node(node_id)
        except Exception as error: self.status.setText(f"打开界面失败：{error}")

    def _fill_regions(self, preferred=None):
        self.edge_region.clear(); self.edge_region.addItem("无特定框", None)
        node = next((n for n in self.snapshot['graph']['nodes'] if n['node_id'] == self.edge_source.currentData()), {})
        for region in node.get('regions', []):
            self.edge_region.addItem(str(region.get('name') or region['region_id']), region['region_id'])
        index = self.edge_region.findData(preferred)
        if preferred and index < 0:
            self.edge_region.addItem("原目标框已不存在（请选择）", preferred)
            index = self.edge_region.count()-1
        self.edge_region.setCurrentIndex(max(0, index))

    def edge_selected(self, edge_id):
        if self.interface_pane.dirty:
            self.status.setText("请先保存或放弃当前界面修改。"); return
        edge = next((e for e in self._edges if e['edge_id'] == edge_id), None)
        if edge is None: return
        self._loading = True; self._edge_id = edge_id; self._node_id = None
        for control in (self.edge_source, self.edge_target):
            control.clear()
            for node in self.snapshot['graph']['nodes']:
                control.addItem(node['display_name'], node['node_id'])
        self.edge_source.setCurrentIndex(self.edge_source.findData(edge['source_node_id']))
        self.edge_target.setCurrentIndex(self.edge_target.findData(edge['target_node_id']))
        self._fill_regions(edge.get('target_region_id'))
        index = self.edge_action.findData(edge['action_type'])
        if index < 0:
            self.edge_action.addItem(edge['action_type'], edge['action_type']); index = self.edge_action.count()-1
        self.edge_action.setCurrentIndex(index)
        self.edge_result.setText(str(edge.get('expected_result') or ''))
        self.edge_condition.setText(str(edge.get('condition') or ''))
        self.details.setCurrentWidget(self.edge_editor)
        self._loading = False

    def _source_changed(self):
        if self._loading: return
        self._loading = True; self._fill_regions(); self._loading = False
        self._edge_changed()

    def _edge_changed(self):
        if self._loading or not self._edge_id: return
        edge = next(e for e in self._edges if e['edge_id'] == self._edge_id)
        edge.clear(); edge.update({
            'edge_id': self._edge_id, 'source_node_id': self.edge_source.currentData(),
            'target_node_id': self.edge_target.currentData(), 'target_region_id': self.edge_region.currentData(),
            'action_type': self.edge_action.currentData() or self.edge_action.currentText(),
            'expected_result': self.edge_result.text(), 'condition': self.edge_condition.text(),
        })
        self._mark_dirty()
        self._show_edit_preview()

    def _mark_dirty(self):
        if self._loading or self.snapshot is None: return
        self._dirty = True; self.dirtyChanged.emit(True)
        self.status.setText("项目有未保存修改。保存即可继续使用，不需要审核或发布。")

    def add_edge(self):
        if not self.snapshot or self.interface_pane.dirty: return
        nodes = self.snapshot['graph']['nodes']
        if not nodes:
            self.status.setText("请先加入界面，再新增跳转关系。"); return
        edge = {'edge_id': 'edge-user-'+uuid4().hex, 'source_node_id': nodes[0]['node_id'],
            'target_node_id': nodes[min(1, len(nodes)-1)]['node_id'], 'action_type': 'click',
            'target_region_id': None, 'expected_result': '', 'condition': ''}
        self._edges.append(edge); self.edge_selected(edge['edge_id']); self._mark_dirty()
        self._show_edit_preview()

    def remove_edge(self):
        if self._edge_id is None: return
        self._edges = [e for e in self._edges if e['edge_id'] != self._edge_id]
        self._edge_id = None; self.details.setCurrentWidget(self.empty_detail); self._mark_dirty()
        self._show_edit_preview()

    def _show_edit_preview(self):
        from .workflow_project import _view_digest
        preview = deepcopy(self.snapshot)
        preview['snapshot_id'] = None
        preview['graph']['edges'] = deepcopy(self._edges)
        preview['graph']['workflow']['edge_ids'] = [edge['edge_id'] for edge in self._edges]
        preview['content_sha256'] = _view_digest(preview)
        try:
            self.graph_view.set_project(preview)
            if self._edge_id: self.graph_view.select_edge(self._edge_id)
        except ValueError:
            self.status.setText("关系信息尚不完整；补充后再保存，当前编辑不会丢失。")

    def save_current(self):
        if self.interface_pane.dirty:
            self.interface_pane.save_changes()
            if self.interface_pane.dirty: return
        if not self.snapshot or not self._dirty: return
        try:
            editable_edges = [{
                'edge_id': e['edge_id'], 'source_node_id': e['source_node_id'],
                'target_node_id': e['target_node_id'], 'action_type': e['action_type'],
                'target_region_id': e.get('target_region_id'),
                'expected_result': str(e.get('expected_result') or ''),
                'condition': str(e.get('condition') or e.get('stop_condition') or ''),
            } for e in self._edges]
            result = self.facade.save_workflow_project(self.snapshot['logical_workflow_id'],
                self.snapshot['content_sha256'], {'title': self.title_edit.text(), 'edges': editable_edges}, uuid4().hex)
            self._install(result)
            current = self.project_list.currentItem()
            if current: current.setText(result['graph']['workflow']['goal'])
            self.status.setText("项目修改已保存；后续仍可随时修改。")
        except Exception as error: self.status.setText(f"保存失败，修改已保留：{error}")

    def discard_changes(self):
        self.interface_pane.discard_changes()
        if self.action_evidence_editor._dirty:
            self.action_evidence_editor.revert_edits()
        self._dirty = False
        if self.snapshot:
            try: self._install(self.facade.load_workflow_project(self.snapshot['logical_workflow_id']))
            except Exception as error: self.status.setText(f"重新读取失败：{error}")

    def _interface_saved(self, value):
        if self.snapshot is None: return
        if self._dirty:
            self.status.setText("界面已保存。项目另有未保存关系，请保留编辑并核对引用后保存。")
            return
        node = self._node_id
        self._install(self.facade.load_workflow_project(self.snapshot['logical_workflow_id']))
        if node: self.node_selected(node)
        self.status.setText("界面已保存；所有引用它的项目在下次打开/刷新时读取最新内容。")

    def _action_revision_changed(self, value):
        if self._loading_action_editor or self.snapshot is None:
            return
        self._pending_action_revision = deepcopy(value)
        QTimer.singleShot(0, self._flush_action_revision)

    def _action_busy_changed(self, busy):
        if busy:
            return
        QTimer.singleShot(0, self._flush_action_revision)
        if self._delete_after_picker:
            QTimer.singleShot(0, self._finish_deferred_delete)

    def _flush_action_revision(self):
        value = self._pending_action_revision
        if self._delete_after_picker or value is None or self.snapshot is None or self.action_evidence_editor._busy:
            return
        if self._dirty or self.interface_pane.dirty or self.action_evidence_editor._dirty:
            self.status.setText("动作证据图已变化，但项目仍有未保存修改；请先保存或放弃项目修改，再刷新来源。")
            return
        node = self._node_id
        try:
            current = self.facade.load_graph_revision(self.snapshot['logical_workflow_id'])
            if (current.get('revision') != value.get('revision')
                    or current.get('content_sha256') != value.get('content_sha256')):
                self.status.setText("操作证据来源已有更新；当前编辑未被覆盖，请刷新后再继续。")
                return
            self._pending_action_revision = None
            self._install(self.facade.load_workflow_project(self.snapshot['logical_workflow_id']))
            if node: self.node_selected(node)
            self.status.setText("动作证据节点修改已保存；项目已读取新的确切图修订。")
        except Exception as error:
            self.status.setText(f"动作证据已保存，但项目刷新失败：{error}")

    def create_project(self):
        if not self._allow_replace(): return
        values = self.facade.list_interface_contents(False)
        if not values:
            self.status.setText("请先接收一个界面，项目将沿用该学习连接。无需批准界面。"); return
        title, ok = QInputDialog.getText(self, "新建流程项目", "项目名称")
        if not ok or not title.strip(): return
        tasks = sorted({v['source']['task_id'] for v in values})
        task = tasks[0]
        if len(tasks) > 1:
            task, ok = QInputDialog.getItem(self, "选择学习连接", "项目所属连接", tasks, 0, False)
            if not ok: return
        try:
            graph = self.facade.create_workflow_graph(title.strip(), task)
            self.snapshot = self.facade.load_workflow_project(graph['logical_workflow_id']); self.refresh()
        except Exception as error: self.status.setText(f"创建失败：{error}")

    def attach_interface(self):
        if not self._allow_replace() or not self.snapshot: return
        if self.interface_picker is not None and self.interface_picker.isVisible():
            self.interface_picker.raise_(); return
        if self.interface_picker is not None:
            self.interface_picker.deleteLater()
        self.interface_picker = InterfacePickerDialog(self.facade, self.snapshot, self)
        self.interface_picker.added.connect(self._interfaces_added)
        self.interface_picker.finished.connect(self._picker_finished)
        self.interface_picker.open()

    def _picker_finished(self, _):
        if self._delete_after_picker:
            QTimer.singleShot(0, self._finish_deferred_delete)

    def _finish_deferred_delete(self):
        from shiboken6 import delete, isValid
        # 原 DeferredDelete 已消费；等信号回调退出且线程结束后再销毁。
        if not isValid(self):
            return
        if self.is_busy:
            QTimer.singleShot(25, self._finish_deferred_delete)
            return
        delete(self)

    def _interfaces_added(self, source, references):
        try:
            self._install(self.facade.load_workflow_project(source['logical_workflow_id']))
            identities = {ref['interface_id'] for ref in references}
            nodes = [node for node in self.snapshot['graph']['nodes']
                     if node.get('interface_reference', {}).get('interface_id') in identities]
            self.graph_view.fit_graph()
            if nodes:
                self.node_selected(nodes[0]['node_id'])
            self.status.setText(f"已加入 {len(references)} 个界面，已打开其中一个。可继续添加，或点击“新增跳转关系”连接它们。")
        except Exception as error:
            self.status.setText(f"界面已加入，但项目显示刷新失败；请刷新项目，不要重复添加：{error}")

    def detach_interface(self):
        if not self._allow_replace() or not self.snapshot or not self._node_id: return
        if any(self._node_id in (e['source_node_id'], e['target_node_id']) for e in self._edges):
            self.status.setText("这个界面仍有跳转关系。请先删除相关连线并保存，再移除界面；界面原件不会删除。"); return
        try:
            source = self.facade.load_graph_revision(self.snapshot['logical_workflow_id'], self.snapshot['source_revision'])
            node = next(n for n in source['graph']['nodes'] if n['node_id'] == self._node_id)
            ref = node['interface_reference']
            self.facade.detach_interface_from_workflow(source['logical_workflow_id'], ref['interface_id'], ref['version_id'],
                source['revision'], source['content_sha256'], uuid4().hex)
            self._install(self.facade.load_workflow_project(source['logical_workflow_id']))
            self.status.setText("已移除项目引用；独立界面仍在界面库中。")
        except Exception as error: self.status.setText(f"移除失败：{error}")
