"""持久执行历史与仅后验恢复窗口；不提供批准或重放输入。"""

from copy import deepcopy
import json
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .jobs import make_job
from .single_step_dialog import _JobFailure, _safe_operation


_OPERATIONS = {
    "grounded_confirmation_pending": "close_unexecuted",
    "grounded_confirmation_approved": "close_unexecuted",
    "grounded_confirmation_denied": "view_history",
    "grounded_confirmation_closed": "view_history",
    "grounded_confirmation_consume_started": "indeterminate",
    "dispatch_started": "indeterminate",
    "verification_pending": "verify_postcheck",
    "terminal": "view_history",
}
_LABELS = {
    "close_unexecuted": "旧批准不可恢复 · 可使其失效",
    "view_history": "历史记录 · 不执行",
    "indeterminate": "执行结果未知 · 禁止重试",
    "verify_postcheck": "动作已派发 · 等待后验核验",
}


def _item(value):
    if not isinstance(value, dict) or value.get("phase") not in _OPERATIONS:
        raise ValueError("invalid history phase")
    if value.get("operation") != _OPERATIONS[value["phase"]]:
        raise ValueError("invalid history operation")
    if not all(isinstance(value.get(key), str) and value[key] for key in (
        "confirmation_id", "session_id", "observation_id", "action_id", "requested_at",
    )):
        raise ValueError("invalid history identity")
    if re.fullmatch(r"grounded-confirmation\.[0-9a-f]{64}", value["confirmation_id"]) is None:
        raise ValueError("invalid confirmation identity")
    if not all(isinstance(value.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", value[key]) for key in ("claim_sha256", "request_sha256")):
        raise ValueError("invalid history evidence")
    selection = value.get("selection")
    if (not isinstance(selection, dict) or not all(type(selection.get(key)) is int and selection[key] > 0
                                                   for key in ("target_window_handle", "target_process_id"))):
        raise ValueError("invalid history selection")
    if selection.get("source_kind") == "fresh_learning":
        if (set(selection) != {"source_kind", "source_sha256", "target_window_handle", "target_process_id"}
                or not isinstance(selection.get("source_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", selection["source_sha256"]) is None
                or value["phase"] not in {"grounded_confirmation_pending", "grounded_confirmation_approved",
                                          "grounded_confirmation_denied", "grounded_confirmation_closed",
                                          "grounded_confirmation_consume_started", "dispatch_started", "terminal"}):
            raise ValueError("invalid fresh history selection")
        if value["phase"] == "terminal":
            from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt

            try:
                receipt = RuntimeFreshResultReceipt.from_dict(value.get("receipt"))
            except ValueError as error:
                raise ValueError("invalid fresh history receipt") from error
            if (receipt.session_id != value["session_id"]
                    or receipt.observation_id != value["observation_id"]
                    or receipt.action.action_id != value["action_id"]
                    or receipt.source_sha256 != selection["source_sha256"]
                    or receipt.evidence.source_sha256 != selection["source_sha256"]
                    or receipt.evidence.confirmation_id != value["confirmation_id"]):
                raise ValueError("invalid fresh history receipt")
        elif value.get("receipt") is not None:
            raise ValueError("invalid fresh history receipt")
    elif (not isinstance(selection.get("asset_id"), str) or not selection["asset_id"]
            or not isinstance(selection.get("asset_content_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", selection["asset_content_sha256"]) is None):
        raise ValueError("invalid history selection")
    if value.get("receipt") is not None and not isinstance(value["receipt"], dict):
        raise ValueError("invalid history receipt")
    return deepcopy(value)


class GroundedHistoryDialog(QDialog):
    def __init__(self, coordinator, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        self._jobs = set()
        self._items = []
        self._retained = None
        self._request_id = 0
        self._operation = None
        self._recover_id = None
        self.setWindowTitle("执行历史与恢复 · 不重放操作")
        self.resize(1180, 780)
        self.setMinimumSize(850, 600)
        layout = QVBoxLayout(self)
        heading = QLabel("重启不恢复旧批准。仅查看历史、使未执行批准失效，或继续已执行动作的后验核验。", self)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["动作", "原始状态", "目标 HWND / PID", "记录时间"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selected)
        self.table.setAccessibleName("已核验的持久单步历史")
        layout.addWidget(self.table, 2)
        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setAccessibleName("原始身份、证据摘要和回执，只读")
        layout.addWidget(self.details, 3)
        self.status = QLabel("正在读取持久记录，不启动识别模型或操作目标窗口。", self)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("刷新历史", self)
        self.refresh_button.clicked.connect(self._refresh)
        self.recover_button = QPushButton("继续核验（不重放操作）…", self)
        self.recover_button.clicked.connect(self._recover)
        self.stop_button = QPushButton("停止前台等待", self)
        self.stop_button.clicked.connect(coordinator.cancel_waiting)
        self.close_button = QPushButton("关闭", self)
        self.close_button.clicked.connect(self.close)
        for button in (self.refresh_button, self.recover_button, self.stop_button, self.close_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self._controls()
        self._refresh()

    @property
    def owner_retained(self):
        return self._retained is not None

    def _current(self):
        row = self.table.currentRow()
        return self._items[row] if 0 <= row < len(self._items) else None

    def _selected(self):
        item = self._current()
        self.details.setPlainText(json.dumps(item, ensure_ascii=False, indent=2) if item else "")
        if item:
            self.status.setText(_LABELS[item["operation"]] + "。terminal 只表示记录结束，不等于操作成功，请查看原始回执。")
        self._controls()

    def _controls(self):
        busy = bool(self._jobs)
        item = self._current()
        eligible = item is not None and (
            item["confirmation_id"] == self._retained if self.owner_retained
            else item["operation"] in {"close_unexecuted", "verify_postcheck"}
        )
        self.table.setEnabled(not busy and not self.owner_retained)
        self.refresh_button.setEnabled(not busy)
        self.recover_button.setEnabled(not busy and eligible)
        close_old = item is not None and item["operation"] == "close_unexecuted" and not self.owner_retained
        self.recover_button.setText("使旧批准失效…" if close_old else "继续核验 / 清理（不重放操作）…")
        self.stop_button.setEnabled(busy and self._operation == "recover")
        self.close_button.setEnabled(not busy and not self.owner_retained)

    def _launch(self, operation, callback):
        if self._jobs:
            return
        self._operation = operation
        self._request_id += 1
        job = make_job(self._request_id, lambda: _safe_operation(callback), self)
        self._jobs.add(job)
        job.succeeded.connect(self._result)
        job.failed.connect(lambda request_id, _private: self._result(request_id, _JobFailure("history_worker_failed", operation == "recover")))
        job.finished.connect(lambda: self._finished(job))
        job.finished.connect(job.deleteLater)
        self._controls()
        job.start()

    def _refresh(self):
        self._launch("history", self.coordinator.history)

    def _recover(self):
        item = self._current()
        if item is None or not self.recover_button.isEnabled():
            return
        close_old = item["operation"] == "close_unexecuted" and not self.owner_retained
        detail = "将此旧批准标记为失效，不执行动作。" if close_old else "仅恢复后验核验或清理；可能启动已配置识别模型并截图，请手动切换到原目标窗口。不会重放点击。"
        answer = QMessageBox.question(self, "确认本条历史处理", detail + "\n\n" + item["confirmation_id"],
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._recover_id = item["confirmation_id"]
        self.status.setText(detail)
        self._launch("recover", lambda: self.coordinator.recover_history(confirmation_id=self._recover_id))

    def _result(self, request_id, result):
        if request_id != self._request_id:
            return
        if isinstance(result, _JobFailure):
            if result.result_unknown and self._operation == "recover":
                self._retained = self._recover_id
            self.status.setText(f"读取或核验未完成（{result.code}）。未重放操作；已取得的恢复 owner 会保留。")
            return
        try:
            if not isinstance(result, dict) or result.get("artifact_is_authorization") is not False:
                raise ValueError("invalid history envelope")
            if self._operation == "history":
                if result.get("contract_version") != "native_grounded_history_v1" or not isinstance(result.get("items"), list):
                    raise ValueError("invalid history response")
                items = [_item(item) for item in result["items"]]
                ids = [item["confirmation_id"] for item in items]
                retained = result.get("retained_confirmation_id")
                if len(ids) != len(set(ids)) or retained is not None and retained not in ids or self._retained is not None and retained != self._retained:
                    raise ValueError("invalid retained history identity")
                self._items, self._retained = items, retained
                self.table.setRowCount(len(items))
                for row, item in enumerate(items):
                    target = item["selection"]
                    columns = [item["action_id"], item["phase"], f"{target['target_window_handle']} / {target['target_process_id']}", item["requested_at"]]
                    for col, value in enumerate(columns):
                        self.table.setItem(row, col, QTableWidgetItem(value))
                self.table.clearSelection()
                self.table.setCurrentCell(-1, -1)
                self.details.clear()
                if retained is not None:
                    self.table.selectRow(ids.index(retained))
                else:
                    self.status.setText(f"已核验 {len(items)} 条持久历史。请选择一条查看，未自动恢复任何批准或动作。")
            else:
                if result.get("contract_version") != "native_grounded_recovery_v1" or type(result.get("owner_retained")) is not bool:
                    raise ValueError("invalid recovery response")
                item = _item(result.get("item"))
                if item["confirmation_id"] != self._recover_id:
                    raise ValueError("recovery identity mismatch")
                self._retained = self._recover_id if result["owner_retained"] else None
                row = self.table.currentRow()
                self._items[row] = item
                self.table.setItem(row, 1, QTableWidgetItem(item["phase"]))
                self.details.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
                self.status.setText("后验或清理仍未完成，请继续处理同一条记录。" if self.owner_retained else "记录已核验；未重放操作，也未自动继续下一步。")
        except (KeyError, TypeError, ValueError, AttributeError):
            if self._operation == "recover":
                self._retained = self._recover_id
            self.status.setText("历史响应无法验证；禁止恢复或切换目标，保留已取得的 owner。")

    def _finished(self, job):
        self._jobs.discard(job)
        if not self._jobs:
            self._operation = None
            self._controls()

    def closeEvent(self, event):
        if self._jobs or self.owner_retained:
            self.status.setText("恢复尚未完成，窗口与原 owner 会保留；请完成同一条记录的后验核验或清理。")
            event.ignore()
        else:
            event.accept()

    def reject(self):
        if self._jobs or self.owner_retained:
            self.close()
        else:
            super().reject()

    def done(self, result):
        if self._jobs or self.owner_retained:
            self.close()
        else:
            super().done(result)
