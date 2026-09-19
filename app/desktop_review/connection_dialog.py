"""原生连接授权管理；不推断 Agent 在线，不启动外部产品。"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QDialog, QDialogButtonBox,
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app.agent_link.codex_config import render_codex_config
from app.desktop_review.launch_paths import agent_bridge_command

from .jobs import make_job


class ConnectionManagerDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.snapshot = None
        self._busy = False
        self._jobs = set()
        self._request_id = 0
        self._pending = None
        self._secret = None
        self._creation_uncertain = False
        self._recovery_refreshed = False
        self._refresh_after_job = False
        self._revoke_keys = {}
        self._artifact_refs = None
        self.setWindowTitle("Agent 连接与授权")
        self.resize(1080, 760)
        layout = QVBoxLayout(self)
        self.host_label = QLabel("正在读取本机接收服务；真实 Agent 产品和会话未验证。")
        self.host_label.setWordWrap(True)
        layout.addWidget(self.host_label)
        note = QLabel("连接用于学习、读取审核反馈及已授权的流程记忆、提交动作意图；实际可用工具以服务端能力为准，不授予人工批准、发布或执行。未撤销不代表在线，模型账号仍留在 Agent 中。")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.task_id = QLineEdit()
        self.task_id.setMaxLength(4000)
        self.task_id.setPlaceholderText("这条授权接收哪个任务的学习结果")
        self.agent_name = QLineEdit()
        self.agent_name.setMaxLength(4000)
        self.agent_name.setPlaceholderText("仅显示名称，不是已验证的产品身份")
        form.addRow("任务标识", self.task_id)
        form.addRow("连接名称", self.agent_name)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.create_button = QPushButton("创建本任务的 Agent 授权")
        self.refresh_button = QPushButton("刷新接收服务与授权")
        self.revoke_button = QPushButton("撤销所选授权…")
        for button in (self.create_button, self.refresh_button, self.revoke_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.recovery_checked = QCheckBox("已刷新并检查、处理可能创建的现有授权，明确允许另建一条")
        self.recovery_checked.setVisible(False)
        layout.addWidget(self.recovery_checked)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["连接 ID", "连接名称", "任务", "授权状态（不是在线状态）"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 2)
        layout.addWidget(QLabel("新授权密钥仅在本次窗口内保留；默认隐藏，不会保存到审核文件。"))
        self.token = QLineEdit()
        self.token.setReadOnly(True)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.token)
        layout.addWidget(QLabel("以下仅为配置格式预览；未验证在线连接、产品身份或实际会话。"))
        approval_note = QLabel("Codex 中需由用户自行配置并批准所需工具；名单不等于自动授权，截图与动作意图也不等于允许点击。此预览不会修改自动批准设置。")
        approval_note.setWordWrap(True)
        layout.addWidget(approval_note)
        self.config_format = QComboBox()
        self.config_format.addItems(["Codex (TOML)", "通用 STDIO MCP (JSON)"])
        layout.addWidget(self.config_format)
        self.config_preview = QPlainTextEdit()
        self.config_preview.setReadOnly(True)
        self.config_preview.setPlaceholderText("这里显示所选配置字段（密钥隐藏）；未验证任意产品是否可导入。")
        layout.addWidget(self.config_preview, 1)
        credentials = QHBoxLayout()
        self.copy_config_button = QPushButton("复制配置字段（含本连接密钥）")
        self.clear_secret_button = QPushButton("已保存，丢弃本次密钥显示")
        credentials.addWidget(self.copy_config_button)
        credentials.addWidget(self.clear_secret_button)
        layout.addLayout(credentials)
        artifacts = QHBoxLayout()
        self.register_artifacts_button = QPushButton("选择并登记 PNG 截图包…")
        self.copy_artifact_refs_button = QPushButton("复制图片引用")
        self.detach_artifacts_button = QPushButton("从此配置分离截图包")
        for button in (self.register_artifacts_button, self.copy_artifact_refs_button, self.detach_artifacts_button):
            artifacts.addWidget(button)
        layout.addLayout(artifacts)
        self.status = QLabel("未创建或修改任何授权。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)
        layout.addWidget(close_buttons)
        self.task_id.textChanged.connect(self._controls)
        self.agent_name.textChanged.connect(self._controls)
        self.recovery_checked.toggled.connect(self._controls)
        self.table.itemSelectionChanged.connect(self._controls)
        self.create_button.clicked.connect(self.create_connection)
        self.refresh_button.clicked.connect(self.refresh)
        self.revoke_button.clicked.connect(self.revoke_connection)
        self.copy_config_button.clicked.connect(self.copy_config)
        self.clear_secret_button.clicked.connect(self.clear_secret)
        self.register_artifacts_button.clicked.connect(self.register_artifact_bundle)
        self.copy_artifact_refs_button.clicked.connect(self.copy_image_references)
        self.detach_artifacts_button.clicked.connect(self.detach_artifact_bundle)
        self.config_format.currentIndexChanged.connect(self._render_config_preview)
        self._controls()
        self.refresh()

    def _view(self):
        return {"host": self.controller.host_status(), "connections": self.controller.list_connections()}

    def refresh(self):
        self._start("refresh", None, self._view)

    def create_connection(self):
        if not self.create_button.isEnabled():
            return
        task, name = self.task_id.text().strip(), self.agent_name.text().strip()
        binding = {"task_id": task, "agent_name": name, **self.snapshot["host"]}
        self._start("create", binding, lambda: self.controller.create_connection(task, name))

    def revoke_connection(self):
        selected = self._selected()
        if not self.revoke_button.isEnabled() or selected is None:
            return
        identifier = selected["connection_id"]
        if QMessageBox.question(self, "撤销 Agent 授权", "仅撤销所选授权；保留历史学习结果。这不会停止外部 Agent 进程。是否撤销？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        key = self._revoke_keys.setdefault(identifier, "native-revoke-" + uuid4().hex)
        self._start("revoke", identifier, lambda: self.controller.revoke_connection(identifier, key))

    def _start(self, kind, binding, operation):
        if self._busy or self._jobs:
            return
        self._busy = True
        self._request_id += 1
        self._pending = (kind, binding)
        self._controls()
        job = make_job(self._request_id, operation, self)
        job.succeeded.connect(self._succeeded)
        job.failed.connect(self._failed)
        job.finished.connect(lambda: self._finished(job))
        job.finished.connect(job.deleteLater)
        self._jobs.add(job)
        job.start()

    def _succeeded(self, request_id, result):
        if request_id != self._request_id or self._pending is None:
            return
        kind, binding = self._pending
        if kind == "refresh":
            if not self._valid_view(result):
                self.status.setText("授权列表或宿主回执无效；未将其显示为可信状态。")
                self._invalidate_view()
                return
            self.snapshot = copy.deepcopy(result)
            host = result["host"]
            ready = host["phase"] == "ready"
            self.host_label.setText(f"本机接收服务：{'就绪' if ready else host['phase']}；{host['base_url'] or '不接收'}。真实 Agent 产品、版本、会话和能力仍未验证。")
            self._render_connections(result["connections"])
            if self._creation_uncertain:
                self._recovery_refreshed = True
                self.status.setText("已刷新。先检查并处理可能创建的授权，确认后才能另建；未自动重试。")
            else:
                self.status.setText("授权状态已刷新；不代表 Agent 正在运行。")
            if self._secret and (
                not ready
                or host["host_id"] != self._secret["host_id"]
                or host["base_url"] != self._secret["base_url"]
                or not any(
                    item["connection_id"] == self._secret["connection_id"]
                    and item["task_id"] == self._secret["task_id"]
                    and not item["revoked"]
                    for item in result["connections"]
                )
            ):
                self.clear_secret()
        elif kind == "create":
            if not self._valid_created(result, binding):
                self._uncertain_creation()
                return
            self._secret = {**copy.deepcopy(result), "host_id": binding["host_id"], "base_url": binding["base_url"]}
            self.token.setText(result["token"])
            self._render_config_preview()
            self.task_id.clear()
            self.agent_name.clear()
            self._creation_uncertain = False
            self._recovery_refreshed = False
            self.recovery_checked.setChecked(False)
            self.status.setText("已创建授权；请按所选产品格式配置 MCP。尚未验证产品连接或会话。")
            self._refresh_after_job = True
        elif kind == "revoke":
            if not isinstance(result, dict) or set(result) != {"contract_version", "connection_id", "status", "staging_only"} or result != {"contract_version": "agent_link_v1", "connection_id": binding, "status": "revoked", "staging_only": True}:
                self.status.setText("撤销回执不匹配；请刷新核验，重试沿用原请求。")
                return
            if self._secret and self._secret["connection_id"] == binding:
                self.clear_secret()
            self.status.setText("所选授权已撤销；未删除历史或停止外部进程。")
            self._refresh_after_job = True
        elif kind == "prepare_artifacts":
            images, output = binding["images"], binding["output"]
            if not self._current_artifact_binding(binding["binding"]):
                self.status.setText("截图包回执已过期，当前授权或接收服务已变化；未更新配置。文件若已写入请手动检查。")
                return
            if not self._valid_artifact_refs(result, binding["binding"], images, output):
                self.status.setText("截图包回执无效或与当前授权不匹配；未更新配置。文件若已写入请手动检查，未自动重试。")
                return
            self._artifact_refs = {"binding": copy.deepcopy(binding["binding"]), "refs": copy.deepcopy(result)}
            self._render_config_preview()
            self.status.setText("截图包已登记到本次连接配置。请重启 MCP 后生效；仍需在 Codex 中单独附上真实 PNG。")

    def _failed(self, request_id, message):
        if request_id != self._request_id or self._pending is None:
            return
        if self._pending[0] == "create":
            self._uncertain_creation()
        elif self._pending[0] == "prepare_artifacts":
            self.status.setText("截图包操作失败；配置未更新。写入结果未知时文件可能已存在，请手动检查；未自动重试。")
        else:
            if self._pending[0] == "refresh":
                self._invalidate_view()
            self.status.setText("连接操作失败，输入保留；请刷新状态或重试。未显示可能含凭据的底层错误。")

    def _invalidate_view(self):
        # 刷新失败不能继续把历史就绪快照当成当前状态。
        self.snapshot = None
        self.host_label.setText("接收服务及授权状态尚未确认；请刷新核验，不使用历史状态。")
        self.table.setRowCount(0)
        self._recovery_refreshed = False
        self.recovery_checked.setChecked(False)

    def _uncertain_creation(self):
        self._creation_uncertain = True
        self._recovery_refreshed = False
        self.recovery_checked.setChecked(False)
        self.status.setText("创建结果不确定，输入保留且未自动重试。先刷新检查并处理可能创建的授权，再明确允许另建。")

    def _finished(self, job):
        self._jobs.discard(job)
        self._busy = False
        self._pending = None
        self._controls()
        if self._refresh_after_job:
            self._refresh_after_job = False
            self.refresh()

    def _render_connections(self, records):
        identifier = (self._selected() or {}).get("connection_id")
        self.table.setRowCount(0)
        for record in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [record["connection_id"], record["agent_name"], record["task_id"], "已撤销" if record["revoked"] else "未撤销（不代表在线）"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, column, item)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, copy.deepcopy(record))
            if record["connection_id"] == identifier:
                self.table.selectRow(row)

    def _selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _controls(self, *_):
        idle = not self._busy and not self._jobs
        ready = self.snapshot is not None and self.snapshot["host"]["phase"] == "ready"
        recovered = not self._creation_uncertain or self._recovery_refreshed and self.recovery_checked.isChecked()
        self.task_id.setEnabled(idle and self._secret is None)
        self.agent_name.setEnabled(idle and self._secret is None)
        self.refresh_button.setEnabled(idle)
        self.table.setEnabled(idle)
        self.create_button.setEnabled(idle and ready and self._secret is None and recovered and bool(self.task_id.text().strip()) and bool(self.agent_name.text().strip()))
        selected = self._selected()
        self.revoke_button.setEnabled(idle and ready and bool(selected and not selected["revoked"]))
        self.recovery_checked.setVisible(self._creation_uncertain)
        self.recovery_checked.setEnabled(idle and self._creation_uncertain and self._recovery_refreshed)
        self.copy_config_button.setEnabled(idle and ready and self._secret is not None)
        self.clear_secret_button.setEnabled(idle and self._secret is not None)
        self.register_artifacts_button.setEnabled(idle and ready and self._secret is not None)
        self.copy_artifact_refs_button.setEnabled(idle and ready and self._artifact_refs is not None)
        self.detach_artifacts_button.setEnabled(idle and self._artifact_refs is not None)

    def _config(self, *, masked):
        env = {"AGENT_LINK_BASE_URL": self._secret["base_url"], "AGENT_LINK_TOKEN": "<本连接密钥已隐藏>" if masked else self._secret["token"]}
        if self._artifact_refs is not None:
            env["AGENT_LINK_ARTIFACT_BUNDLE"] = self._artifact_refs["refs"]["bundle_path"]
        return {**agent_bridge_command(), "env": env}

    def _render_config_preview(self, *_):
        if self._secret is None:
            self.config_preview.clear()
            return
        configuration = self._config(masked=True)
        if self.config_format.currentIndex() == 0:
            self.config_preview.setPlainText(render_codex_config(configuration))
        else:
            self.config_preview.setPlainText(json.dumps(configuration, ensure_ascii=False, indent=2))

    def copy_config(self):
        if self.copy_config_button.isEnabled():
            configuration = self._config(masked=False)
            value = render_codex_config(configuration) if self.config_format.currentIndex() == 0 else json.dumps(configuration, ensure_ascii=False, indent=2)
            QApplication.clipboard().setText(value)
            self.status.setText("已明确复制含Agent密钥的所选配置。请只粘贴到可信Agent配置，使用后自行清除剪贴板；未修改任何产品配置。")

    def clear_secret(self):
        self._secret = None
        self._artifact_refs = None
        self.token.clear()
        self.config_preview.clear()
        self._controls()

    def register_artifact_bundle(self):
        if not self.register_artifacts_button.isEnabled() or self._secret is None:
            return
        frozen = self._frozen_artifact_binding()
        if frozen is None:
            return
        names, _ = QFileDialog.getOpenFileNames(self, "选择 1–32 张 PNG 截图", "", "PNG 图片 (*.png)")
        if not names:
            return
        paths = [Path(name).resolve() for name in names]
        if not 1 <= len(paths) <= 32 or any(path.suffix.lower() != ".png" for path in paths) or len(set(paths)) != len(paths):
            self.status.setText("请选择 1–32 个互不重复的 PNG 文件；未修改配置。")
            return
        output_name, _ = QFileDialog.getSaveFileName(self, "保存新的截图包 JSON", "", "JSON 文件 (*.json)")
        if not output_name:
            return
        output = Path(output_name).resolve()
        if output.suffix.lower() != ".json" or output.exists():
            self.status.setText("截图包输出必须是不存在的 JSON 文件；未修改配置。")
            return
        summary = "\n".join(str(path) for path in paths)
        if QMessageBox.question(self, "登记截图包", f"将登记 {len(paths)} 张 PNG：\n{summary}\n\n输出：{output}\n\n继续吗？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        if not self._current_artifact_binding(frozen):
            self.status.setText("选择文件期间授权或接收服务已变化；未创建截图包。")
            self._controls()
            return
        images = {f"image-{index:03d}": path for index, path in enumerate(paths, 1)}
        payload = {"binding": frozen, "images": images, "output": output}
        self._start("prepare_artifacts", payload, lambda: self.controller.prepare_artifact_bundle(frozen, images, output))

    def copy_image_references(self):
        if not self.copy_artifact_refs_button.isEnabled() or self._artifact_refs is None:
            return
        refs = self._artifact_refs["refs"]
        value = {key: copy.deepcopy(refs[key]) for key in ("connection_id", "task_id", "screenshots")}
        QApplication.clipboard().setText(json.dumps(value, ensure_ascii=False, indent=2))
        self.status.setText("已复制图片引用。请单独附上真实 PNG，并在配置变更后重启 MCP。")

    def detach_artifact_bundle(self):
        if not self.detach_artifacts_button.isEnabled():
            return
        self._artifact_refs = None
        self._render_config_preview()
        self._controls()
        self.status.setText("已从此配置分离截图包；未删除已生成的文件。")

    def _frozen_artifact_binding(self):
        if self._secret is None:
            return None
        return {key: self._secret[key] for key in ("connection_id", "task_id", "host_id", "base_url")}

    def _current_artifact_binding(self, binding):
        if self._secret is None or self.snapshot is None:
            return False
        host = self.snapshot.get("host") if isinstance(self.snapshot, dict) else None
        return (
            isinstance(host, dict)
            and host.get("phase") == "ready"
            and host.get("host_id") == binding["host_id"]
            and host.get("base_url") == binding["base_url"]
            and all(self._secret.get(key) == binding[key] for key in binding)
        )

    @staticmethod
    def _valid_artifact_refs(result, binding, images, output):
        expected = {"contract_version", "connection_id", "task_id", "bundle_path", "bundle_sha256", "screenshots"}
        if not isinstance(result, dict) or set(result) != expected:
            return False
        if result["contract_version"] != "agent_link_artifact_references_v1" or result["connection_id"] != binding["connection_id"] or result["task_id"] != binding["task_id"]:
            return False
        try:
            if Path(result["bundle_path"]).resolve() != output.resolve():
                return False
        except (TypeError, ValueError, OSError):
            return False
        if not isinstance(result["bundle_sha256"], str) or len(result["bundle_sha256"]) != 64 or any(char not in "0123456789abcdef" for char in result["bundle_sha256"]):
            return False
        screenshots = result["screenshots"]
        if not isinstance(screenshots, list) or len(screenshots) != len(images):
            return False
        ids = list(images)
        if [item.get("screenshot_id") if isinstance(item, dict) else None for item in screenshots] != ids:
            return False
        for item in screenshots:
            if set(item) != {"screenshot_id", "artifact_id", "sha256"} or item["artifact_id"] != item["screenshot_id"]:
                return False
            if not isinstance(item["sha256"], str) or len(item["sha256"]) != 64 or any(char not in "0123456789abcdef" for char in item["sha256"]):
                return False
        return True

    @staticmethod
    def _valid_created(result, binding):
        if not isinstance(result, dict) or set(result) != {"contract_version", "connection_id", "task_id", "agent_name", "token", "staging_only"}:
            return False
        token = result["token"]
        return (result["contract_version"] == "agent_link_v1" and result["staging_only"] is True
                and result["task_id"] == binding["task_id"] and result["agent_name"] == binding["agent_name"]
                and isinstance(result["connection_id"], str) and bool(result["connection_id"])
                and isinstance(token, str) and 16 <= len(token) <= 512 and token.isascii() and "\r" not in token and "\n" not in token)

    @staticmethod
    def _valid_view(value):
        if not isinstance(value, dict) or set(value) != {"host", "connections"}:
            return False
        host, records = value["host"], value["connections"]
        if not isinstance(host, dict):
            return False
        version = host.get("contract_version")
        if version == "native_review_host_v1":
            if (
                set(host) != {"contract_version", "host_id", "phase", "base_url", "staging_only"}
                or host.get("staging_only") is not True
            ):
                return False
        elif version == "native_review_host_v2":
            if (
                set(host) != {
                    "contract_version", "host_id", "phase", "base_url", "staging_only",
                    "agent_link_staging_only", "reviewed_single_step_enabled",
                    "automatic_execution_enabled",
                }
                or host.get("staging_only") is not False
                or host.get("agent_link_staging_only") is not True
                or host.get("reviewed_single_step_enabled") is not True
                or host.get("automatic_execution_enabled") is not False
            ):
                return False
        else:
            return False
        if not isinstance(host["host_id"], str) or not host["host_id"] or host["phase"] not in {"created", "starting", "ready", "stopping", "stopped", "failed"}:
            return False
        if host["phase"] == "ready":
            try:
                url = urlsplit(host["base_url"])
                if url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port or url.username or url.password or url.path or url.query or url.fragment:
                    return False
            except (ValueError, TypeError, AttributeError):
                return False
        elif host["base_url"] is not None:
            return False
        if not isinstance(records, list):
            return False
        identifiers = set()
        for record in records:
            if not isinstance(record, dict) or set(record) != {"connection_id", "task_id", "agent_name", "revoked", "created_at"}:
                return False
            if any(not isinstance(record[key], str) or not record[key] or len(record[key]) > 4000 for key in ("connection_id", "task_id", "agent_name")) or type(record["revoked"]) is not bool or type(record["created_at"]) is not int or record["created_at"] <= 0 or record["connection_id"] in identifiers:
                return False
            identifiers.add(record["connection_id"])
        return True

    def _can_close(self):
        if self._busy or self._jobs:
            self.status.setText("连接操作仍在进行，请等待回执；不会销毁后台作业或重复创建授权。")
            return False
        if self._secret is not None and QMessageBox.question(self, "丢弃本次密钥显示", "关闭后不能再次查看本次密钥；授权仍然有效。已保存配置或准备撤销重建，仍要关闭吗？", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return False
        self.clear_secret()
        return True

    def reject(self):
        if self._can_close():
            super().reject()

    def closeEvent(self, event):
        event.accept() if self._can_close() else event.ignore()
