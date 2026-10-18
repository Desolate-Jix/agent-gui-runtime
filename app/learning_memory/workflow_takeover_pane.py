"""接管视图只组合现有公开请求，未决结果始终回读原 ID。"""
from app.learning_memory.workbench_i18n import ui, tr, bind_text, initialize_i18n, language_manager
from copy import deepcopy
import json
import re

from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from .workflow_control import validate_request


def _require(value):
    if not value:
        raise ValueError("workflow_takeover_ui_binding_invalid")


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class WorkflowTakeoverPane(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.rows = []
        self.source_snapshot = None
        self.preview_request = None
        self.preview_id = None
        self.preview = None
        self.commit_request = None
        self.committed = False
        self.invalid = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ui(QLabel, tr('恢复中断的任务')))
        self.label = ui(QLabel, tr('原动作结算后，请回当前 Agent 创建恢复会话，再连接它。'))
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        grid = QGridLayout()
        self.source = QComboBox()
        self.resolution = QComboBox()
        self.mode = QComboBox()
        ui(self.mode.addItem, tr('接管后运行单步'), 'single')
        ui(self.mode.addItem, tr('接管后连续运行至等待'), 'until_wait')
        grid.addWidget(ui(QLabel, tr('原任务')), 0, 0)
        grid.addWidget(self.source, 0, 1)
        grid.addWidget(ui(QLabel, tr('恢复方式')), 1, 0)
        grid.addWidget(self.resolution, 1, 1)
        grid.addWidget(ui(QLabel, tr('继续方式')), 2, 0)
        grid.addWidget(self.mode, 2, 1)
        self.preview_button = ui(QPushButton, tr('核对当前效果'))
        self.commit_button = ui(QPushButton, tr('提交接管（保持暂停）'))
        grid.addWidget(self.preview_button, 3, 0)
        grid.addWidget(self.commit_button, 3, 1)
        layout.addLayout(grid)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(150)
        ui(self.details.setPlaceholderText, tr('核对后显示保留的任务输入、上游输出和当前效果。'))
        layout.addWidget(self.details)
        self.source.currentIndexChanged.connect(self._source_changed)
        self.resolution.currentIndexChanged.connect(lambda: owner._sync())
        self.preview_button.clicked.connect(self.prepare)
        self.commit_button.clicked.connect(self.commit)
        self.set_sources([])

    @property
    def blocks_new_run(self):
        return self.invalid or (not self.committed and bool(self.rows or self.preview_request))

    def reset(self):
        self.source_snapshot = self.preview_request = self.preview_id = self.preview = self.commit_request = None
        self.committed = self.invalid = False
        self.details.clear()
        ui(self.label.setText, tr('原动作结算后，请回当前 Agent 创建恢复会话，再连接它。'))
        self.set_sources([])

    def set_sources(self, values):
        try:
            _require(isinstance(values, list))
            for value in values:
                _require(isinstance(value, dict) and all(isinstance(value.get(key), str) and value[key]
                    for key in ("admission_request_id", "source_run_id", "source_session", "workflow_id",
                                "program_id", "step_id", "step_title")))
                _require(_hash(value.get("program_sha256")) and value.get("terminal_status") in
                    {"completed", "failed", "cancelled"} and type(value.get("action_executed")) in {bool, type(None)}
                    and type(value.get("resume_unexecuted_available")) is bool
                    and value.get("current_effect_verified") is False)
                _require(not value["resume_unexecuted_available"] or
                    (value["terminal_status"] == "cancelled" and value["action_executed"] is False))
            _require(len({(row["admission_request_id"], row["source_run_id"]) for row in values}) == len(values))
        except ValueError as error:
            self.invalid = True
            ui(self.label.setText, tr('原任务来源无法核对：') + str(error))
            return
        self.invalid = False
        if values == self.rows:
            return
        selected = self.source.currentData()
        self.rows = deepcopy(values)
        self.source.blockSignals(True)
        self.source.clear()
        ui(self.source.addItem, tr('请选择要恢复的原任务'), None)
        for row in self.rows:
            terminal = {'completed': tr('已完成'), 'failed': tr('失败'), 'cancelled': tr('已取消')}.get(row['terminal_status'], row['terminal_status'])
            ui(self.source.addItem, tr('{title} · {terminal}', title=row['step_title'], terminal=terminal), row)
        if selected in self.rows:
            self.source.setCurrentIndex(self.source.findData(selected))
        self.source.blockSignals(False)
        if self.preview_request is None:
            self._source_changed()

    def _source_changed(self):
        if self.preview_request is not None:
            return
        value = self.source.currentData()
        self.resolution.blockSignals(True)
        self.resolution.clear()
        ui(self.resolution.addItem, tr('请选择恢复方式'), None)
        if isinstance(value, dict):
            ui(self.resolution.addItem, tr('确认此步骤已完成，从下一步继续'), 'adopt_success')
            if value["resume_unexecuted_available"]:
                ui(self.resolution.addItem, tr('确认此步骤未完成，重新执行原步骤'), 'resume_unexecuted')
            action = value["action_executed"]
            fact = tr('已发生') if action is True else tr('未发生') if action is False else tr('未知')
            ui(self.label.setText, tr('原步骤：') + value['step_title'] + tr('；原输入动作') + fact + tr('。当前效果尚未核对，请选择恢复方式。'))
            self.label.setToolTip(str(value.get("resume_unexecuted_reason") or ""))
        self.resolution.blockSignals(False)
        self.owner._sync()

    def _can_queue(self):
        owner = self.owner
        state = (owner._run or {}).get("runner_state") or (owner._run or {}).get("status")
        return bool(owner._client is not None and owner._host_alive and owner._connection_matches()
            and not owner.is_busy and not owner._close_requested and not owner._is_recovery_paused()
            and not owner._pending and not owner._host_pending_ids and not owner._recovery_blocked
            and state in {None, "completed", "failed", "cancelled"} and not self.invalid and not self.committed)

    def sync(self):
        live = self._can_queue()
        self.setVisible(bool(self.rows or self.preview_request or self.invalid))
        locked = self.preview_request is not None
        self.source.setEnabled(live and not locked)
        self.resolution.setEnabled(live and not locked and isinstance(self.source.currentData(), dict))
        self.mode.setEnabled(live and self.commit_request is None)
        self.preview_button.setEnabled(bool(live and not locked and self.resolution.currentData()))
        bound = self.source_snapshot in self.rows
        self.commit_button.setEnabled(bool(live and bound and self.preview is not None
            and self.commit_request is None))

    def prepare(self):
        if not self.preview_button.isEnabled():
            return
        source = self.source.currentData()
        request = {"action": "takeover_preview", "admission_request_id": source["admission_request_id"],
            "source_run_id": source["source_run_id"], "resolution": self.resolution.currentData()}
        self.owner._control(request, "takeover_preview")

    def commit(self):
        if not self.commit_button.isEnabled():
            return
        request = {"action": "takeover_commit", "preview_request_id": self.preview_id,
            "preview_sha256": self.preview["preview_sha256"], "mode": self.mode.currentData()}
        capabilities = self.owner._declared_vision_capabilities()
        if capabilities is not None:
            request["vision_capabilities"] = capabilities
        self.owner._control(request, "takeover_commit", request["mode"])

    def record_request(self, request, request_id, preview=None):
        validate_request(request)
        if request["action"] == "takeover_preview":
            matches = [row for row in self.rows if row["admission_request_id"] == request["admission_request_id"]
                and row["source_run_id"] == request["source_run_id"]]
            _require(len(matches) == 1 and self.preview_request in (None, request))
            resolution = request.get("resolution", "adopt_success")
            _require(resolution != "resume_unexecuted" or matches[0]["resume_unexecuted_available"])
            self.source_snapshot = deepcopy(matches[0])
            self.source.setCurrentIndex(self.source.findData(matches[0]))
            self.resolution.setCurrentIndex(self.resolution.findData(resolution))
            self.preview_request, self.preview_id = deepcopy(request), request_id
        else:
            if preview is not None:
                original = {"action": "takeover_preview", "admission_request_id": preview["admission_request_id"],
                    "source_run_id": preview["source_run_id"], "resolution": preview["resolution"]}
                self.record_request(original, preview["preview_request_id"])
                self.accept_preview(preview["preview_request_id"], preview)
            _require(self.preview is not None and request["preview_request_id"] == self.preview_id
                and request["preview_sha256"] == self.preview["preview_sha256"])
            self.commit_request = deepcopy(request)
            self.mode.setCurrentIndex(self.mode.findData(request["mode"]))

    def accept_preview(self, request_id, value):
        request = self.preview_request or {}
        _require(isinstance(value, dict) and value.get("status") == "preview_ready"
            and request_id == self.preview_id == value.get("preview_request_id")
            and value.get("admission_request_id") == request.get("admission_request_id")
            and value.get("source_run_id") == request.get("source_run_id")
            and value.get("resolution") == request.get("resolution", "adopt_success")
            and _hash(value.get("preview_sha256"))
            and isinstance(value.get("new_run_id"), str) and re.fullmatch(r"trial-[0-9a-f]{64}", value["new_run_id"])
            and (value.get("next_step_id") is None or isinstance(value["next_step_id"], str) and value["next_step_id"])
            and all(isinstance(value.get(key), dict) for key in ("inputs", "outputs", "effect"))
            and value.get("input_dispatched") is False and value.get("automatic_retry_allowed") is False
            and self.source_snapshot in self.rows)
        verification = value["effect"].get("verification")
        _require(isinstance(verification, dict) and verification.get("verdict") ==
            ("failure" if value["resolution"] == "resume_unexecuted" else "success"))
        _require(value["resolution"] != "resume_unexecuted" or
            (verification.get("reason") == "observed_value_conflict"
             and value["next_step_id"] == self.source_snapshot["step_id"]))
        self.preview = deepcopy(value)
        explanation = (tr('当前效果未完成；保留已验证上游，将重新执行原步骤。') if value['resolution'] == 'resume_unexecuted' else tr('当前效果已完成；将从下一步继续。'))
        ui(self.label.setText, explanation + tr('提交只接管并暂停，之后仍需点击“继续原运行”。'))
        ui(self.details.setPlainText, tr('{inputs_label}: {inputs}\n{outputs_label}: {outputs}\n{effect_label}: {effect}\n{next_label}: {next_step}',
            inputs_label=tr('任务输入'), inputs=json.dumps(value['inputs'], ensure_ascii=False, indent=2),
            outputs_label=tr('保留的上游输出'), outputs=json.dumps(value['outputs'], ensure_ascii=False, indent=2),
            effect_label=tr('当前效果'), effect=json.dumps(verification, ensure_ascii=False, indent=2),
            next_label=tr('后续步骤'), next_step=value['next_step_id']))
        ui(self.details.setToolTip, tr('原预览 ID：') + request_id + '；SHA256：' + value['preview_sha256'])

    def accept_commit(self, value):
        preview, source = self.preview or {}, self.source_snapshot or {}
        _require(isinstance(value, dict) and self.commit_request is not None
            and value.get("run_id") == preview.get("new_run_id")
            and value.get("current_step_id") == preview.get("next_step_id")
            and value.get("workflow_id") == source.get("workflow_id")
            and value.get("program_id") == source.get("program_id")
            and value.get("outputs") == preview.get("outputs"))
        if preview.get("next_step_id") is None:
            _require(value.get("runner_state") == value.get("status") == "completed")
        else:
            wait = value.get("wait")
            _require(value.get("runner_state") == "waiting" and value.get("wait_reason") == "takeover_ready"
                and isinstance(wait, dict) and wait.get("reason") == "takeover_ready"
                and isinstance(wait.get("wait_id"), str) and wait["wait_id"])
        self.committed = True
        ui(self.label.setText, tr('已接管并保持暂停；点击“继续原运行”才会执行。') if preview.get('next_step_id') else tr('已接管原已完成任务，无后续步骤。'))

    def show_run(self, value):
        marker = value.get("recovery_import") if isinstance(value, dict) else None
        if isinstance(marker, dict) and any(marker.get("source_run_id") == row["source_run_id"] for row in self.rows):
            self.committed = True
            ui(self.label.setText, tr('原任务已接管；运行状态和继续入口见上方。'))
