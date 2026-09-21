"""从流程项目直接挑选已有界面；只修改记忆引用，不执行操作。"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from uuid import uuid4

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from .jobs import make_job


class InterfacePickerDialog(QDialog):
    added = Signal(object, object)

    def __init__(self, facade, project_snapshot, parent=None):
        super().__init__(parent)
        self.facade = facade
        self.project = deepcopy(project_snapshot)
        self._job = None
        self._operation = None
        self._outcome = None
        self._closing = False
        self._loading = False
        self._request = None
        self._selected_before_reload = []
        self.setWindowTitle("添加已有界面")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(880, 680)
        self.setMinimumSize(620, 460)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        self.heading = QLabel()
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        self.heading.setWordWrap(True)
        self.heading.setStyleSheet("font-size: 20px; font-weight: 600;")
        root.addWidget(self.heading)
        note = QLabel("勾选界面，一次加入项目。已有审核记录的界面也在这里，无需再次审核。")
        note.setWordWrap(True)
        root.addWidget(note)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索界面名称、识别文字或应用名称")
        self.search.setClearButtonEnabled(True)
        self.refresh_button = QPushButton("刷新界面库")
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.refresh_button)
        root.addLayout(search_row)
        self.items = QListWidget()
        self.items.setIconSize(QSize(160, 96))
        self.items.setSpacing(6)
        self.items.setWordWrap(True)
        self.items.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.items.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.items.setStyleSheet("QListWidget {border: 1px solid #d8e1ec; border-radius: 8px;}"
                                 "QListWidget::item {padding: 10px; border-bottom: 1px solid #edf1f6;}"
                                 "QListWidget::item:hover {background: #eef5ff;}")
        self.items.setAccessibleName("已有界面，多选加入项目")
        root.addWidget(self.items, 1)
        self.selection_note = QLabel()
        self.selection_note.setWordWrap(True)
        root.addWidget(self.selection_note)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        actions = QHBoxLayout()
        self.select_visible_button = QPushButton("勾选当前可加入项")
        self.clear_button = QPushButton("清空选择")
        self.cancel_button = QPushButton("取消")
        self.add_button = QPushButton("加入选中的界面")
        self.add_button.setStyleSheet("QPushButton {padding: 9px 18px;}"
                                      "QPushButton:enabled {background: #2563eb; color: white; border-radius: 6px;}")
        for button in (self.select_visible_button, self.clear_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.add_button)
        root.addLayout(actions)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.search.textChanged.connect(self._filter)
        self.items.itemChanged.connect(self._selection_changed)
        self.refresh_button.clicked.connect(self.reload)
        self.select_visible_button.clicked.connect(self.select_visible)
        self.clear_button.clicked.connect(self.clear_selection)
        self.cancel_button.clicked.connect(self.reject)
        self.add_button.clicked.connect(self.add_selected)
        self.reload()

    @property
    def busy(self):
        return self._job is not None

    def _run(self, operation, callback):
        self._operation = operation
        self._outcome = None
        job = make_job(1, callback, self)
        self._job = job
        job.succeeded.connect(lambda _, result: self._received(True, result))
        job.failed.connect(lambda _, error: self._received(False, error))
        job.finished.connect(lambda: self._finished(job))
        self._selection_changed()
        job.start()

    def _received(self, success, value):
        self._outcome = (success, value)

    def _finished(self, job):
        operation, outcome = self._operation, self._outcome
        self._job = None
        job.deleteLater()
        if self._closing:
            super().reject()
            return
        self._selection_changed()
        if not outcome or not outcome[0]:
            message = str(outcome[1]) if outcome else "后台任务没有返回结果"
            self.status.setText(("加入失败，选择已保留。请刷新后检查并重试：" if operation == "add"
                                 else "读取界面库失败，请刷新重试：") + message.splitlines()[0])
            self.status.setToolTip(message)
            return
        if operation == "load":
            self._install(outcome[1])
        else:
            self.added.emit(outcome[1], deepcopy(self._request[1]))
            super().accept()

    def reload(self):
        if self.busy:
            return
        self._selected_before_reload = self.selected_references()
        self.status.setText("正在读取界面库和截图…")
        self._run("load", self._load_candidates)

    def _load_candidates(self):
        project = self.facade.load_workflow_project(self.project['logical_workflow_id'])
        source = self.facade.load_graph_revision(project['logical_workflow_id'], project['source_revision'])
        task_id = source['source_refs']['task_id']
        present = {node.get('interface_reference', {}).get('interface_id') for node in project['graph']['nodes']}
        records = []
        for value in self.facade.list_interface_contents(False):
            if value.get("learning_status") == "observation_only":
                continue
            reason = ""
            if value['interface_id'] in present:
                reason = "已在项目中 · 无需重复加入"
            elif value['source']['task_id'] != task_id:
                reason = "来自其他学习连接 · 当前项目暂不支持跨连接加入"
            thumbnail = QImage()
            try:
                evidence = self.facade.load_interface_content_evidence(value['interface_id'], value['version_id'])
                path = self.facade._artifact_file(evidence['image_path'], "界面缩略图")
                raw = path.read_bytes()
                if sha256(raw).hexdigest() != evidence['sha256']:
                    raise ValueError("截图内容已变化，请检查原件")
                thumbnail = QImage.fromData(raw)
                if thumbnail.isNull():
                    raise ValueError("截图不能解码")
                thumbnail = thumbnail.scaled(160, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation)
            except (ValueError, OSError, RuntimeError) as error:
                reason = (reason + "；" if reason else "") + f"截图读取失败：{error}"
            records.append({'value': value, 'reason': reason, 'thumbnail': thumbnail})
        records.sort(key=lambda item: (bool(item['reason']), item['value']['content']['meaning'].casefold(),
                                      item['value']['interface_id']))
        return {'project': project, 'records': records}

    def _install(self, result):
        self.project = result['project']
        self.heading.setText("添加到：" + self.project['graph']['workflow']['goal'])
        self._loading = True
        self.items.clear()
        retained = 0
        for record in result['records']:
            value = record['value']
            ref = {key: value[key] for key in ('interface_id', 'version_id', 'content_sha256')}
            binding = value.get('application_binding') or {}
            title = value['content']['meaning']
            context = binding.get('display_name') or "未命名应用"
            reason = record['reason'] or "可加入"
            item = QListWidgetItem(f"{title}\n{context} · 已保存版本 {value['revision']}\n{reason}")
            item.setSizeHint(QSize(0, 120))
            item.setToolTip(f"{title}\n{reason}\n学习连接：{value['source']['task_id']}\n界面：{value['interface_id']}")
            item.setData(Qt.ItemDataRole.UserRole, ref)
            item.setData(Qt.ItemDataRole.UserRole + 1, " ".join((title, str(value['content'].get('recognition_text', '')),
                         context, value['source']['task_id'])).casefold())
            item.setIcon(QIcon(QPixmap.fromImage(record['thumbnail'])))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            if not record['reason']:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                checked = ref in self._selected_before_reload
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                retained += int(checked)
            else:
                item.setForeground(QBrush(QColor('#64748b')))
            self.items.addItem(item)
        self._loading = False
        removed = len(self._selected_before_reload) - retained
        self._filter()
        self.status.setToolTip("")
        if removed:
            self.status.setText(f"有 {removed} 个原选项已更新或不能加入，已取消勾选；请检查后重新勾选。")
        elif not self.items.count():
            self.status.setText("当前数据目录还没有已保存界面。请先让 Agent 学习并保存界面，再刷新这里。")
        else:
            self.status.setText("只添加引用，不复制界面、不自动连线，也不执行点击。灰色说明会解释不能加入的原因。")

    def selected_references(self):
        return [deepcopy(item.data(Qt.ItemDataRole.UserRole)) for item in self._items()
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.checkState() == Qt.CheckState.Checked]

    def _items(self):
        return [self.items.item(index) for index in range(self.items.count())]

    def _filter(self):
        query = self.search.text().strip().casefold()
        for item in self._items():
            item.setHidden(query not in item.data(Qt.ItemDataRole.UserRole + 1))
        self._selection_changed()

    def _selection_changed(self, *_):
        if self._loading:
            return
        selected = self.selected_references()
        hidden_selected = sum(item.isHidden() and item.checkState() == Qt.CheckState.Checked for item in self._items())
        visible = [item for item in self._items() if not item.isHidden()]
        available = [item for item in visible if item.flags() & Qt.ItemFlag.ItemIsUserCheckable]
        existing = sum('interface_reference' in node for node in self.project['graph']['nodes'])
        remaining = max(0, 256 - existing)
        self.selection_note.setText(f"当前显示 {len(visible)} 个 · 可加入 {len(available)} 个 · 已选 {len(selected)} 个"
                                   + (f"（其中 {hidden_selected} 个被搜索隐藏，仍会一起加入）" if hidden_selected else ""))
        if len(selected) > remaining:
            self.selection_note.setText(self.selection_note.text() + f"；此项目最多还能加入 {remaining} 个，请减少勾选。")
        self.add_button.setText(f"加入选中的 {len(selected)} 个界面")
        self.add_button.setEnabled(bool(selected) and len(selected) <= remaining and not self.busy)
        for widget in (self.items, self.search, self.refresh_button):
            widget.setEnabled(not self.busy)
        self.select_visible_button.setEnabled(bool(available) and not self.busy)
        self.clear_button.setEnabled(bool(selected) and not self.busy)
        self.cancel_button.setEnabled(not self.busy or self._operation == "load")

    def select_visible(self):
        if self.busy:
            return
        for item in self._items():
            if not item.isHidden() and item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Checked)

    def clear_selection(self):
        if self.busy:
            return
        for item in self._items():
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Unchecked)

    def add_selected(self):
        refs = self.selected_references()
        if self.busy or not refs:
            return
        fingerprint = (self.project['source_sha256'], refs)
        if self._request is None or self._request[:2] != fingerprint:
            self._request = (*fingerprint, uuid4().hex)
        project, key = deepcopy(self.project), self._request[2]
        self.status.setText(f"正在将 {len(refs)} 个界面一起加入项目…")
        self._run("add", lambda: self.facade.attach_interfaces_to_workflow(
            project['logical_workflow_id'], refs, project['source_revision'], project['source_sha256'], key))

    def reject(self):
        if self.busy:
            if self._operation == "load":
                self._closing = True
                self.status.setText("正在结束读取，不会修改项目…")
            else:
                self.status.setText("正在保存加入结果，请稍候；完成后会自动返回项目。")
            return
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
