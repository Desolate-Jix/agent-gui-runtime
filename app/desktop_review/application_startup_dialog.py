"""人工确认 Agent 软件启动请求；面板不暴露 MCP 凭据或自动确认。"""
from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .jobs import FacadeJob, make_job
from app.core.launch_text import launch_display_json, launch_display_text


class ApplicationStartupDialog(QDialog):
    def __init__(self, provider: Any, parent=None, *, auto_refresh: bool = True) -> None:
        super().__init__(parent)
        if any(not callable(getattr(provider, name, None)) for name in ("list_requests", "preview", "confirm")):
            raise TypeError("application startup dialog requires the local startup provider")
        self.provider = provider
        self._jobs: set[FacadeJob] = set()
        self._request_id = 0
        self._operation: str | None = None
        self._preview: dict[str, Any] | None = None
        self.setWindowTitle("Agent 软件启动请求 · 人工确认")
        self.resize(960, 700)
        self.setMinimumSize(760, 520)
        self._build_ui()
        if auto_refresh:
            self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        heading = QLabel("Agent 只能暂存目录应用启动请求。请检查完整命令后，独立确认一次。", self)
        heading.setWordWrap(True)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(heading)
        self.status = QLabel("正在读取本地人工确认队列…", self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.requests = QTableWidget(0, 5, self)
        self.requests.setHorizontalHeaderLabels(["请求", "任务", "应用", "URL", "状态"])
        self.requests.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.requests.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.requests.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.requests.itemSelectionChanged.connect(self._selection_changed)
        self.requests.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.requests, 2)
        self.preview_text = QPlainTextEdit(self)
        self.preview_text.setReadOnly(True)
        self.preview_text.setPlaceholderText("选择请求后读取确切启动预览；不会启动程序。")
        self.preview_text.setAccessibleName("应用启动确切预览")
        layout.addWidget(self.preview_text, 2)
        self.receipt_text = QPlainTextEdit(self)
        self.receipt_text.setReadOnly(True)
        self.receipt_text.setMaximumHeight(130)
        self.receipt_text.setPlaceholderText("人工确认后的窗口准备回执会显示在这里。")
        layout.addWidget(self.receipt_text)
        controls = QHBoxLayout()
        self.refresh_button = QPushButton("刷新请求", self)
        self.preview_button = QPushButton("获取确切预览", self)
        self.confirm_button = QPushButton("确认启动…", self)
        self.close_button = QPushButton("关闭", self)
        self.refresh_button.clicked.connect(self.refresh)
        self.preview_button.clicked.connect(self.preview)
        self.confirm_button.clicked.connect(self.confirm)
        self.close_button.clicked.connect(self.reject)
        for button in (self.refresh_button, self.preview_button, self.confirm_button):
            button.setAutoDefault(False)
            controls.addWidget(button)
        controls.addStretch()
        controls.addWidget(self.close_button)
        layout.addLayout(controls)
        self._controls()

    def refresh(self) -> None:
        if not self.refresh_button.isEnabled():
            return
        self._preview = None
        self.preview_text.clear()
        self._start("refresh", self.provider.list_requests)

    def preview(self) -> None:
        request_id = self._selected_request_id()
        if request_id is None or not self.preview_button.isEnabled():
            return
        self._preview = None
        self.preview_text.clear()
        self._start("preview", lambda: self.provider.preview(request_id))

    def confirm(self) -> None:
        request_id = self._selected_request_id()
        preview = self._preview
        if request_id is None or preview is None or not self.confirm_button.isEnabled():
            return
        if preview.get("request_id") not in {None, request_id}:
            self.status.setText("预览与当前请求不一致；未确认。")
            self._preview = None
            self._controls()
            return
        details = (
            f"应用：{launch_display_text(preview['name'])}\n程序：{launch_display_text(preview['executable_path'])}\n"
            f"完整参数：{launch_display_json(preview['command'])}\n"
            f"URL：{launch_display_text(preview.get('url') or '无')}\n\n"
            "确认后仅调用一次窗口准备启动；不会启动模型、学习、点击或输入。"
        )
        box = QMessageBox(QMessageBox.Icon.Question, "确认软件启动", details,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if QMessageBox.StandardButton(box.exec()) != QMessageBox.StandardButton.Yes:
            return
        self._start("confirm", lambda: self.provider.confirm(request_id, preview["preview_sha256"]))

    def _start(self, operation: str, callback) -> None:
        if self._jobs:
            return
        self._operation = operation
        self._request_id += 1
        request_id = self._request_id
        job = make_job(request_id, callback, self)
        job.succeeded.connect(self._succeeded)
        job.failed.connect(self._failed)
        job.finished.connect(lambda: self._finished(job))
        job.finished.connect(job.deleteLater)
        self._jobs.add(job)
        self.status.setText("正在读取请求…" if operation == "refresh" else ("正在生成确切预览；未启动程序。" if operation == "preview" else "正在确认窗口准备；不会重复发送启动。"))
        self._controls()
        job.start()

    def _succeeded(self, request_id: int, result: Any) -> None:
        if request_id != self._request_id:
            return
        if self._operation == "refresh":
            if not isinstance(result, list) or any(not _request(item) for item in result):
                self.status.setText("本地请求队列回执无效；未显示为可确认项。")
                self.requests.setRowCount(0)
                return
            self._render(result)
            self.status.setText("已读取本地请求；尚未启动任何程序。")
        elif self._operation == "preview":
            if not _preview(result):
                self.status.setText("确切预览无效；未允许确认。")
                self._preview = None
                return
            self._preview = copy.deepcopy(result)
            self.preview_text.setPlainText(launch_display_json(result, indent=2))
            self.status.setText("已显示确切应用、程序路径、完整参数和 URL；尚未启动。")
        elif self._operation == "confirm":
            if not _outcome(result):
                self.status.setText("启动回执无效；不将其显示为已完成。")
                return
            self.receipt_text.setPlainText(launch_display_json(result, indent=2))
            self._preview = None
            self.status.setText("窗口准备已返回回执；请仅在窗口已就绪时继续既有观察入口，未自动开始学习。")

    def _failed(self, request_id: int, _message: str) -> None:
        if request_id != self._request_id:
            return
        self._preview = None if self._operation != "refresh" else self._preview
        self.status.setText("本地启动请求操作失败或结果未知；未自动重试，也未把结果显示为已启动。")

    def _finished(self, job: FacadeJob) -> None:
        # QThread 的 finished 信号可能先于析构安全点；显式等候避免关闭对话框时丢弃仍在退出的任务。
        job.wait(1000)
        self._jobs.discard(job)
        if not self._jobs:
            operation = self._operation
            self._operation = None
            self._controls()
            if operation == "confirm":
                self.refresh()

    def _render(self, records: list[dict[str, Any]]) -> None:
        selected = self._selected_request_id()
        self.requests.setRowCount(0)
        for record in records:
            row = self.requests.rowCount()
            self.requests.insertRow(row)
            values = (record["request_id"], record["task_id"], record["app_id"], record["url"] or "—", record["status"])
            for column, value in enumerate(values):
                item = QTableWidgetItem(launch_display_text(str(value)))
                item.setToolTip(launch_display_text(str(value)))
                self.requests.setItem(row, column, item)
            self.requests.item(row, 0).setData(Qt.ItemDataRole.UserRole, copy.deepcopy(record))
            if record["request_id"] == selected:
                self.requests.selectRow(row)

    def _selected_request_id(self) -> str | None:
        rows = self.requests.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.requests.item(rows[0].row(), 0)
        record = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        return record.get("request_id") if isinstance(record, dict) and isinstance(record.get("request_id"), str) else None

    def _selection_changed(self) -> None:
        self._preview = None
        self.preview_text.clear()
        self._controls()

    def reject(self) -> None:
        if self._jobs:
            self.status.setText("确认请求仍在运行；请等待回执，窗口不会销毁后台任务或重复启动。")
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._jobs:
            self.status.setText("确认请求仍在运行；请等待回执，窗口不会销毁后台任务或重复启动。")
            event.ignore()
            return
        event.accept()

    def _controls(self) -> None:
        idle = not self._jobs
        selected = self._selected_request_id() is not None
        self.requests.setEnabled(idle)
        self.refresh_button.setEnabled(idle)
        self.preview_button.setEnabled(idle and selected)
        self.confirm_button.setEnabled(idle and selected and self._preview is not None)
        self.close_button.setEnabled(idle)


def _request(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"request_id", "task_id", "app_id", "url", "created_at", "status"} and all(isinstance(value.get(key), str) and value[key] for key in ("request_id", "task_id", "app_id", "status")) and (value.get("url") is None or isinstance(value.get("url"), str)) and type(value.get("created_at")) is int


def _preview(value: Any) -> bool:
    keys = {"contract_version", "preparation_id", "mode", "identity", "source", "app_id", "name", "url", "command", "executable_path", "catalog_entry_sha256", "executable_sha256", "expires_in_seconds", "preview_sha256"}
    return isinstance(value, dict) and set(value) == keys and value.get("contract_version") == "native_window_preparation_v1" and value.get("mode") == "launch" and value.get("identity") is None and value.get("source") == "app_catalog" and all(isinstance(value.get(key), str) and value[key] for key in ("preparation_id", "app_id", "name", "executable_path")) and (value.get("url") is None or isinstance(value.get("url"), str)) and isinstance(value.get("command"), list) and value["command"] and all(isinstance(item, str) and item for item in value["command"]) and value["command"][0] == value["executable_path"] and type(value.get("expires_in_seconds")) is int and value["expires_in_seconds"] > 0


def _outcome(value: Any) -> bool:
    return isinstance(value, dict) and value.get("status") in {"launched_window_ready", "launched_window_unavailable"}
