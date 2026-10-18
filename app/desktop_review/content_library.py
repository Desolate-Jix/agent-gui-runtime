"""独立界面内容库的审核、复用与逻辑删除入口。"""
from __future__ import annotations
from app.learning_memory.workbench_i18n import ui, translated_dialog, tr, bind_text, join_text

from copy import deepcopy
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QEvent, QTimer, Qt, QSignalBlocker, Signal
from PySide6.QtWidgets import QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QLineEdit, QMessageBox, QPushButton, QSplitter, QVBoxLayout

from .interface_pane import InterfaceReviewPane


class InterfaceContentLibrary(QDialog):
    """只展示 façade 返回的界面快照；不会创建图或执行动作。"""

    openLearningFlow = Signal(str)

    def __init__(self, facade: Any, parent=None, *, reviewed_only: bool = False, task_id: str | None = None, pending_batch: dict[str, Any] | None = None, embedded: bool = False) -> None:
        super().__init__(parent)
        self.facade = facade
        self.reviewed_only = reviewed_only
        self.task_id = task_id
        self.pending_batch = pending_batch
        self.embedded = bool(embedded)
        if self.embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        ui(self.setWindowTitle, tr('界面库 · 新学内容与修改'))
        self.resize(1240, 820)
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        ui(self.search.setPlaceholderText, tr('搜索界面含义或识别文字'))
        self.filter = QComboBox()
        ui(self.filter.addItems, [tr('全部界面'), tr('新学内容'), tr('有修改'), tr('原始观察（调试）')])
        self.filter.setCurrentIndex(0)
        refresh = ui(QPushButton, tr('接收新内容 / 刷新'))
        self.latest_button = ui(QPushButton, tr('打开并继续修改'))
        self.latest_button.setEnabled(False)
        self.latest_button.clicked.connect(self._open_latest)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.filter)
        filters.addWidget(refresh)
        filters.addWidget(self.latest_button)
        layout.addLayout(filters)
        actions = QHBoxLayout()
        self.selection_label = ui(QLabel, tr('已选 0 个界面 · 按 Ctrl / Shift 可多选'))
        self.delete_button = ui(QPushButton, tr('删除界面'))
        self.delete_button.setObjectName("deleteInterfaceButton")
        self.batch_delete_button = ui(QPushButton, tr('批量删除'))
        self.batch_delete_button.setObjectName("batchDeleteInterfacesButton")
        self.learning_flow_button = ui(QPushButton, tr('查看所属学习流程'))
        self.learning_flow_button.hide()
        actions.addWidget(self.selection_label, 1)
        actions.addWidget(self.learning_flow_button)
        actions.addWidget(self.delete_button)
        actions.addWidget(self.batch_delete_button)
        layout.addLayout(actions)
        self.delete_button.clicked.connect(lambda: self._delete_selected(batch=False))
        self.batch_delete_button.clicked.connect(lambda: self._delete_selected(batch=True))
        self.learning_flow_button.clicked.connect(self._open_learning_flow)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.items = QListWidget()
        self.items.setObjectName("interfaceContentList")
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.items.setMinimumWidth(210)
        splitter.addWidget(self.items)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.pane = InterfaceReviewPane(facade, self)
        self.pane.loaded.connect(self._interface_loaded)
        self.pane.saved.connect(self._saved)
        self.pane.reviewed.connect(self._saved)
        self.pane.errorRaised.connect(self.error.setText)
        splitter.addWidget(self.pane)
        splitter.setSizes([290, 900])
        layout.addWidget(splitter, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        ui(close.button(QDialogButtonBox.StandardButton.Close).setText, tr('关闭'))
        close.rejected.connect(self.reject)
        self.close_button = close.button(QDialogButtonBox.StandardButton.Close)
        if self.embedded:
            self.close_button.hide()
        layout.addWidget(close)
        self.items.currentItemChanged.connect(self._selected)
        self.items.itemSelectionChanged.connect(self._selection_changed)
        refresh.clicked.connect(self.refresh)
        self.filter.currentIndexChanged.connect(self.refresh)
        self.search.textChanged.connect(self._filter_items)
        self.refresh()

    @property
    def dirty(self) -> bool:
        return self.pane.dirty

    def refresh(self, *_args) -> None:
        if self.pane.dirty:
            ui(self.error.setText, tr('请先保存或放弃当前修改，再刷新内容。'))
            return
        selected = self.pane.snapshot
        self.error.clear()
        try:
            values = self._load_values()
        except Exception as error:
            ui(self.error.setText, tr('独立界面读取失败：{v0}；保留当前列表。', v0=error))
            return
        self.items.clear()
        target = None
        for value in values:
            state = "原始观察" if value.get("learning_status") == "observation_only" else ("新学内容" if value.get("origin_status") == "new" else "有修改")
            item = ui(QListWidgetItem, tr('{v0}\n{v1} · 修订 {v2}', v0=value['content']['meaning'], v1=state, v2=value['revision']))
            item.setData(256, deepcopy(value))
            self.items.addItem(item)
            if selected and selected["interface_id"] == value["interface_id"]:
                target = item
        self._filter_items()
        if target is None:
            target = next((self.items.item(i) for i in range(self.items.count()) if not self.items.item(i).isHidden()), None)
        if target is not None:
            self.items.setCurrentItem(target)
        if not values:
            ui(self.error.setText, tr('尚未收到符合条件的界面。请让 Agent 提交学习内容，再点击刷新。'))
        self._selection_changed()

    def _load_values(self) -> list[dict]:
        if self.reviewed_only:
            values = self.facade.list_interface_contents(True, self.task_id)
        elif self.pending_batch is not None:
            source = self.pending_batch
            task_id, batch_id = source.get("task_id"), source.get("batch_id")
            values = []
            for item in (source.get("batch") or {}).get("interfaces", []):
                try:
                    values.append(self.facade.import_interface_content(task_id, batch_id, item.get("external_interface_id", item.get("interface_id"))))
                except Exception as error:
                    if str(error).startswith("interface_content_deleted:"):
                        continue
                    ui(self.error.setText, tr('独立界面导入失败：{v0}；未替换已有内容。', v0=error))
        else:
            values = self._scan_incoming_interfaces()
        if self.filter.currentIndex() == 3:
            return [value for value in values if value.get("learning_status") == "observation_only"]
        values = [value for value in values if value.get("learning_status") != "observation_only"]
        if self.filter.currentIndex() == 1:
            values = [value for value in values if value.get("origin_status") == "new"]
        elif self.filter.currentIndex() == 2:
            values = [value for value in values if value.get("origin_status") == "modified"]
        return values

    def _filter_items(self, *_args) -> None:
        query = self.search.text().casefold().strip()
        for index in range(self.items.count()):
            item = self.items.item(index)
            value = item.data(256)
            haystack = str(value.get("content", {})).casefold()
            item.setHidden(bool(query) and query not in haystack)
            if item.isHidden():
                item.setSelected(False)
        self._selection_changed()

    def _scan_incoming_interfaces(self) -> list[dict[str, Any]]:
        """扫描待审核批次并幂等导入界面，不创建流程图。"""
        if not callable(getattr(self.facade, "list_batches", None)):
            return self.facade.list_interface_contents(self.reviewed_only, self.task_id)
        if self.reviewed_only:
            return self.facade.list_interface_contents(True, self.task_id)
        result: list[dict[str, Any]] = []
        for summary in self.facade.list_batches():
            if not isinstance(summary, dict):
                continue
            task_id, batch_id = summary.get("task_id"), summary.get("batch_id")
            if not isinstance(task_id, str) or not isinstance(batch_id, str):
                continue
            if self.task_id is not None and task_id != self.task_id:
                continue
            workspace = self.facade.load_batch(task_id, batch_id)
            for interface in (workspace.get("batch") or {}).get("interfaces", []) if isinstance(workspace, dict) else []:
                external_id = interface.get("external_interface_id", interface.get("interface_id"))
                try:
                    result.append(self.facade.import_interface_content(task_id, batch_id, external_id))
                except Exception as error:
                    if str(error).startswith("interface_content_deleted:"):
                        continue
                    ui(self.error.setText, tr('独立界面导入失败：{v0}；未替换已有内容。', v0=error))
        return self.facade.list_interface_contents(False, self.task_id)

    def _selection_changed(self) -> None:
        count = sum(not item.isHidden() for item in self.items.selectedItems())
        ui(self.selection_label.setText, tr('已选 {v0} 个界面 · 按 Ctrl / Shift 可多选', v0=count))
        available = callable(getattr(self.facade, "delete_interface_contents", None))
        self.delete_button.setEnabled(available and count == 1)
        self.batch_delete_button.setEnabled(available and count > 0)

    def _delete_selected(self, *, batch: bool) -> None:
        if self.pane.dirty:
            ui(self.error.setText, tr('仍有未保存修改。请先保存或放弃当前修改，再删除界面。'))
            return
        selected = [item.data(256) for item in self.items.selectedItems() if not item.isHidden()]
        if not selected or (not batch and len(selected) != 1):
            ui(self.error.setText, tr('请先选择一个界面；多选后请使用“批量删除”。'))
            return
        requests = [{"interface_id": item["interface_id"], "expected_revision": item["revision"],
                     "expected_sha256": item["content_sha256"]} for item in selected]
        try:
            preview = self.facade.preview_interface_content_deletion(requests)
        except Exception as error:
            ui(self.error.setText, tr('删除检查失败：{v0}；整批未删除，当前内容保留。', v0=error))
            return
        details = []
        for item in preview["items"]:
            references = [ref["title"] for ref in item["references"]]
            detail = tr('• {title}', title=item['meaning'])
            detail += tr('（引用项目：{references}）', references=join_text(tr('、'), references)) if references else tr('（无流程引用）')
            details.append(detail)
        answer = translated_dialog(QMessageBox.question, self, tr('确认批量删除') if batch else tr('确认删除界面'), tr('将从界面库删除 {v0} 个界面：\n', v0=len(selected)) + join_text('\n', details) + tr('\n\n仅删除库入口；流程引用、所有历史版本及截图仍保留。刷新或重开不会重新导入。') + tr('\n本入口不提供恢复操作。是否继续？'), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            ui(self.error.setText, tr('已取消删除；所有界面及当前选择保留。'))
            return
        try:
            result = self.facade.delete_interface_contents(requests)
        except Exception as error:
            ui(self.error.setText, tr('删除失败：{v0}；请刷新核对，未清空当前选择。', v0=error))
            return
        self.refresh()
        ui(self.error.setText, tr('已删除 {v0} 个界面，另有 {v1} 个此前已删除。流程引用、历史版本和截图保留。', v0=result['deleted_count'], v1=result['already_deleted_count']))

    def _sync_learning_flow(self) -> None:
        flow = (self.pane.snapshot or {}).get("learning_flow") or {}
        available = bool(flow.get("logical_workflow_id"))
        self.learning_flow_button.setVisible(available)
        self.learning_flow_button.setEnabled(available)

    def _open_learning_flow(self) -> None:
        if self.pane.dirty:
            ui(self.error.setText, tr('请先保存或放弃当前修改，再查看所属学习流程。'))
            return
        flow = (self.pane.snapshot or {}).get("learning_flow") or {}
        if flow.get("logical_workflow_id"):
            self.openLearningFlow.emit(flow["logical_workflow_id"])

    def _selected(self, current, previous) -> None:
        if self.pane.dirty:
            blocker = QSignalBlocker(self.items)
            self.items.setCurrentItem(previous)
            del blocker
            ui(self.error.setText, tr('请先保存或放弃当前修改，再切换界面。'))
            return
        if current is None:
            self.pane.clear_content()
            self.latest_button.setEnabled(False)
            self._sync_learning_flow()
            return
        if current is not None and isinstance(current.data(256), dict):
            try:
                self.pane.set_snapshot(current.data(256))
                self._opened_latest_version = None
                if getattr(self.facade, 'background_interface_loading', False):
                    self.latest_button.setEnabled(False)
                    self._sync_learning_flow()
                    self.error.clear()
                    return
                latest = self.facade.load_interface_content(current.data(256)["interface_id"])
                older = latest["version_id"] != current.data(256)["version_id"]
                self.pane.set_read_only(older)
                self.latest_button.setEnabled(older)
                self._sync_learning_flow()
                self.error.clear()
                if older:
                    ui(self.error.setText, tr('正在查看历史版本（只读）。需要修改时，请打开最新版本。'))
            except Exception as error:
                blocker = QSignalBlocker(self.items)
                self.items.setCurrentItem(previous)
                del blocker
                ui(self.error.setText, tr('界面证据读取失败：{v0}；当前选择未成功加载。', v0=error))

    def _interface_loaded(self, result):
        snapshot = result['snapshot']
        older = result['latest_version_id'] != snapshot['version_id']
        self.pane.set_read_only(older)
        self.latest_button.setEnabled(older)
        self._sync_learning_flow()
        ui(self.error.setText, tr('正在查看历史版本（只读）。需要修改时，请打开最新版本。') if older else tr('正在修改最新版本；流程项目中的固定版本不会自动更新，请在项目中明确更新引用。') if getattr(self, '_opened_latest_version', None) == snapshot['version_id'] else '')

    def _open_latest(self) -> None:
        if self.pane.dirty or self.pane.snapshot is None:
            return
        try:
            latest = self.facade.load_interface_content(self.pane.snapshot["interface_id"])
            self._opened_latest_version = latest['version_id']
            self.pane.set_snapshot(latest)
            self.pane.set_read_only(False)
            self.latest_button.setEnabled(False)
            self._saved(latest)
            ui(self.error.setText, tr('正在修改最新版本；流程项目中的固定版本不会自动更新，请在项目中明确更新引用。'))
        except Exception as error:
            ui(self.error.setText, tr('读取最新界面失败：{v0}', v0=error))

    def _saved(self, snapshot: object) -> None:
        current = self.items.currentItem()
        if current is not None and isinstance(snapshot, dict):
            current.setData(256, deepcopy(snapshot))
            state = "原始观察" if snapshot.get("learning_status") == "observation_only" else ("新学内容" if snapshot.get("origin_status") == "new" else "有修改")
            ui(current.setText, tr('{v0}\n{v1} · 修订 {v2}', v0=snapshot['content']['meaning'], v1=state, v2=snapshot['revision']))
            self._sync_learning_flow()
            self.error.clear()

    def reject(self) -> None:
        if self.pane.is_busy:
            self.pane.cancel_loading()
            ui(self.error.setText, tr('正在结束界面证据读取，请稍后再关闭。'))
            return
        if self.pane.dirty:
            ui(self.error.setText, tr('仍有未保存修改。请先保存或点“放弃未保存修改”。'))
            return
        super().reject()

    def event(self, event):
        if event.type() == QEvent.Type.DeferredDelete and hasattr(self, 'pane') and self.pane.is_busy:
            self.pane.cancel_loading()
            QTimer.singleShot(20, self._delete_when_idle)
            return True
        return super().event(event)

    def _delete_when_idle(self):
        if self.pane.is_busy:
            QTimer.singleShot(20, self._delete_when_idle)
        else:
            self.deleteLater()

    def closeEvent(self, event) -> None:
        if self.pane.is_busy:
            self.pane.cancel_loading()
            event.ignore()
            return
        if self.pane.dirty:
            ui(self.error.setText, tr('仍有未保存修改。请先保存或点“放弃未保存修改”。'))
            event.ignore()
            return
        super().closeEvent(event)


__all__ = ["InterfaceContentLibrary"]


class WorkflowCompositionDialog(QDialog):
    """将选中的独立界面加入已有图或明确新建图；加入不创建连线。"""
    def __init__(self, facade: Any, interface_snapshot: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.facade, self.interface_snapshot = facade, deepcopy(interface_snapshot)
        self._created_graph: dict[str, Any] | None = None
        self._mutation_keys: dict[tuple[str, str], str] = {}
        ui(self.setWindowTitle, tr('加入流程项目'))
        layout = QVBoxLayout(self)
        layout.addWidget(ui(QLabel, tr('选择已有项目，或输入名称新建；加入后可在“流程项目”连接和修改跳转。')))
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.graphs = QListWidget()
        layout.addWidget(self.graphs)
        self.title_edit = QLineEdit()
        ui(self.title_edit.setPlaceholderText, tr('新流程项目名称（可选）'))
        layout.addWidget(self.title_edit)
        row = QHBoxLayout()
        self.attach = ui(QPushButton, tr('加入选中项目'))
        self.create = ui(QPushButton, tr('新建并加入'))
        self.detach = ui(QPushButton, tr('从选中流程移除'))
        self.close_button = ui(QPushButton, tr('关闭'))
        row.addWidget(self.attach); row.addWidget(self.create); row.addWidget(self.detach); row.addWidget(self.close_button)
        self.detach.hide()
        layout.addLayout(row)
        self.attach.clicked.connect(self._attach)
        self.create.clicked.connect(self._create)
        self.detach.clicked.connect(self._detach)
        self.close_button.clicked.connect(self.reject)
        self._load()

    def _load(self) -> None:
        try:
            loader = getattr(self.facade, "list_workflow_projects", self.facade.list_workflow_graphs)
            graphs = loader()
        except Exception as error:
            ui(self.status.setText, tr('流程图库读取失败：{v0}', v0=error))
            return
        for graph in graphs:
            if graph.get("task_id") != self.interface_snapshot.get("source", {}).get("task_id"):
                continue
            item = QListWidgetItem(str(graph.get("title") or graph.get("logical_workflow_id", "")))
            item.setData(256, deepcopy(graph)); self.graphs.addItem(item)

    def _attach(self) -> None:
        item = self.graphs.currentItem()
        if item is None:
            ui(self.status.setText, tr('请先选择一个同一 task 的流程图。'))
            return
        graph = item.data(256)
        try:
            existing = self.facade.load_graph_revision(graph['logical_workflow_id'])
            if any(node.get('interface_reference', {}).get('interface_id') == self.interface_snapshot['interface_id'] for node in existing['graph']['nodes']):
                ui(self.status.setText, tr('该界面已在这个项目中，不需要重复加入。固定版本不会自动更新，请在项目中明确更新引用。'))
                return
            result = self.facade.attach_interface_to_workflow(workflow_id=graph["logical_workflow_id"], interface_id=self.interface_snapshot["interface_id"], version_id=self.interface_snapshot["version_id"], expected_revision=graph["revision"], expected_sha256=graph["content_sha256"], idempotency_key=self._key("attach", graph))
            self._record_graph(result)
            ui(self.status.setText, tr('已加入流程图；未创建跳转边。'))
        except Exception as error:
            ui(self.status.setText, tr('加入流程图失败：{v0}；当前图和界面草稿未覆盖，可重试。', v0=error))

    def _create(self) -> None:
        title = self.title_edit.text().strip()
        if not title:
            ui(self.status.setText, tr('请输入新流程图名称。'))
            return
        try:
            if self._created_graph is None:
                self._created_graph = self.facade.create_workflow_graph(title=title, task_id=self.interface_snapshot["source"]["task_id"])
                self.title_edit.setReadOnly(True)
            graph = self._created_graph
            result = self.facade.attach_interface_to_workflow(workflow_id=graph["logical_workflow_id"], interface_id=self.interface_snapshot["interface_id"], version_id=self.interface_snapshot["version_id"], expected_revision=graph["revision"], expected_sha256=graph["content_sha256"], idempotency_key=self._key("create-attach", graph))
            self._record_graph(result)
            self.create.setEnabled(False)
            ui(self.status.setText, tr('已新建并加入流程图；未创建跳转边。'))
        except Exception as error:
            ui(self.status.setText, tr('新建或加入失败：{v0}；已保留本次新建图，可重试加入。', v0=error))

    def _detach(self) -> None:
        item = self.graphs.currentItem()
        if item is None:
            ui(self.status.setText, tr('请先选择要移除的流程图。'))
            return
        graph = item.data(256)
        try:
            result = self.facade.detach_interface_from_workflow(workflow_id=graph["logical_workflow_id"], interface_id=self.interface_snapshot["interface_id"], version_id=self.interface_snapshot["version_id"], expected_revision=graph["revision"], expected_sha256=graph["content_sha256"], idempotency_key=self._key("detach", graph))
            self._record_graph(result)
            ui(self.status.setText, tr('已移除引用及关联边；源界面和其他流程保留。'))
        except Exception as error:
            ui(self.status.setText, tr('移除流程图成员失败：{v0}；未覆盖当前图。', v0=error))

    def _key(self, operation: str, graph: dict) -> str:
        identity = (operation, graph["logical_workflow_id"], graph["content_sha256"])
        if identity not in self._mutation_keys:
            self._mutation_keys[identity] = uuid4().hex
        return self._mutation_keys[identity]

    def _record_graph(self, snapshot: dict) -> None:
        summary = {key: snapshot[key] for key in ("logical_workflow_id", "revision", "content_sha256")}
        summary.update(title=snapshot["graph"]["workflow"]["goal"], task_id=snapshot["source_refs"]["task_id"],
                       node_count=len(snapshot["graph"]["nodes"]))
        item = next((self.graphs.item(index) for index in range(self.graphs.count())
            if self.graphs.item(index).data(256)["logical_workflow_id"] == summary["logical_workflow_id"]), None)
        if item is None:
            item = QListWidgetItem()
            self.graphs.addItem(item)
        ui(item.setText, tr('{v0} · 修订 {v1}', v0=summary['title'], v1=summary['revision']))
        item.setData(256, summary)
        self.graphs.setCurrentItem(item)


__all__.append("WorkflowCompositionDialog")
