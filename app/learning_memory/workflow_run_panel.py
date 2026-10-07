"""在已连接的原宿主会话中显式启动并观察固定版本工作流。"""
from __future__ import annotations
from app.learning_memory.workbench_i18n import ui, tr, bind_text, bound_text, join_text

from copy import deepcopy
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget)

from app.desktop_review.jobs import make_job
from .workflow_run_history import WorkflowRunHistory
from .workflow_takeover_pane import WorkflowTakeoverPane


_TERMINAL = {"completed", "failed", "cancelled"}
_STATE_LABELS = {'ready': tr('待运行'), 'running': tr('运行中'), 'dispatching': tr('正在执行'), 'waiting': tr('等待处理'), 'blocked': tr('已暂停'), 'single_complete': tr('单步完成'), 'completed': tr('已完成'), 'failed': tr('失败'), 'cancelled': tr('已取消'), 'cancel_requested': tr('取消处理中')}
_METRIC_LABELS = {'steps_completed': tr('已完成步骤'), 'steps_total': tr('总步骤'), 'elapsed_ms': tr('耗时（毫秒）'), 'input_actions': tr('输入动作'), 'model_calls': tr('模型调用')}
_ACTION_TITLES = {'click': tr('点击'), 'input_sequence': tr('填写文本'), 'read_text': tr('读取文本'), 'scroll': tr('滚动'), 'press_key': tr('按键')}
_WAIT_LABELS = {'execution_pending': tr('正在等待原动作回执'), 'queue_busy': tr('原命令队列忙'), 'grounding_required': tr('需 Agent 在原会话完成图像定位'), 'verification_required': tr('需 Agent 在原会话核验执行结果'), 'recovery_paused': tr('原动作已结算，恢复暂停；业务结果仍待核验'), 'takeover_ready': tr('接管已就绪，等待明确继续'), 'input_required': tr('需补充任务输入或前序输出'), 'result_unknown': tr('结果未知；只能回读原请求，不可重发'), 'uncertain': tr('结果不确定，需人工检查'), 'single_step_complete': tr('单步已完成，等待明确继续'), 'failed': tr('步骤失败，需检查原回执')}


class WorkflowRunPanel(QWidget):
    sessionChanged = Signal(object)
    busyChanged = Signal(bool)

    def __init__(self, library_root, session_dir=None, parent=None, *, client_factory=None, execution_root=None):
        super().__init__(parent)
        self.library_root = Path(library_root)
        self._client_factory = client_factory
        self.inputs_provider = None
        self._client = None
        self._connected_path = None
        self._client_session_path = None
        self._client_execution_root = None
        self._host_alive = False
        self._host_pending_ids = []
        self._context = None
        self._step_id = None
        self._dirty = False
        self._run = None
        self._run_program_identity = None
        self._run_step_titles = {}
        self._prepared_run = False
        self._recovery_blocked = False
        self._recovered_ids = set()
        self._pending = None
        self._jobs = {}
        self._outcomes = {}
        self._sequence = 0
        self._generation = 0
        self._close_requested = False
        self._recognition_source = None
        self._start_vision_capabilities = None
        self._terminal_preview = None
        self._terminal_recovery_id = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)
        # 隐藏的运行页不能把整个工作台撑高，小屏下保留所有操作的滚动入口。
        layout = QVBoxLayout(content)
        execution_row = QHBoxLayout()
        execution_row.addWidget(ui(QLabel, tr('执行模式安装目录')))
        self.execution_path = QLineEdit(str(execution_root) if execution_root is not None else "")
        ui(self.execution_path.setPlaceholderText, tr('采集或运行时选择兼容的执行模式安装目录'))
        self.execution_browse_button = ui(QPushButton, tr('选择执行安装'))
        self.execution_browse_button.clicked.connect(self.browse_execution)
        execution_row.addWidget(self.execution_path, 1)
        execution_row.addWidget(self.execution_browse_button)
        layout.addLayout(execution_row)
        offline_note = ui(QLabel, tr('未连接时仍可审核、修改和保存学习库；采集教学和运行工作流需要连接执行模式。'))
        offline_note.setWordWrap(True)
        layout.addWidget(offline_note)
        row = QHBoxLayout()
        self.session_path = QLineEdit(str(session_dir) if session_dir is not None else "")
        ui(self.session_path.setPlaceholderText, tr('默认连接当前 Agent 的执行会话；也可选择已有会话'))
        self.browse_button = ui(QPushButton, tr('选择文件夹'))
        self.browse_button.clicked.connect(self.browse_session)
        self.connect_button = ui(QPushButton, tr('连接会话'))
        self.connect_button.clicked.connect(self.connect_session)
        row.addWidget(self.session_path, 1)
        row.addWidget(self.browse_button)
        row.addWidget(self.connect_button)
        self.latest_button = ui(QPushButton, tr('连接当前 Agent 会话'))
        self.latest_button.clicked.connect(self.connect_latest)
        row.addWidget(self.latest_button)
        layout.addLayout(row)
        self.status_label = ui(QLabel, tr('尚未连接执行会话。'))
        self.status_label.setWordWrap(True)
        self.status = self.status_label
        layout.addWidget(self.status_label)
        self.step_label = ui(QLabel, tr('当前步骤：尚未运行'))
        self.step_label.setWordWrap(True)
        layout.addWidget(self.step_label)
        self.target_label = ui(QLabel, tr('当前目标：未连接'))
        self.target_label.setWordWrap(True)
        layout.addWidget(self.target_label)
        self.vision_checkbox = QCheckBox()
        ui(self.vision_checkbox.setToolTip, tr('仅声明本会话的识图能力，不是输入授权；未勾选表示能力未知。'))
        layout.addWidget(self.vision_checkbox)
        buttons = QGridLayout()
        self.single_button = ui(QPushButton, tr('运行单步'))
        self.single_button.clicked.connect(self.start_single)
        self.run_button = ui(QPushButton, tr('连续运行至等待'))
        self.run_button.clicked.connect(self.start_continuous)
        self.refresh_button = ui(QPushButton, tr('刷新状态'))
        self.refresh_button.clicked.connect(self.refresh)
        self.continue_button = ui(QPushButton, tr('继续原运行'))
        self.continue_button.clicked.connect(self.continue_run)
        self.cancel_button = ui(QPushButton, tr('取消原运行'))
        self.cancel_button.clicked.connect(self.cancel_run)
        for index, button in enumerate((self.single_button, self.run_button, self.refresh_button,
                                        self.continue_button, self.cancel_button)):
            buttons.addWidget(button, index // 3, index % 3)
        layout.addLayout(buttons)
        self.recovery_button = ui(QPushButton, tr('核对已保存结果'))
        self.recovery_button.clicked.connect(self.recover_saved_terminal)
        layout.addWidget(self.recovery_button)
        self.recovery_label = QLabel("")
        self.recovery_label.setWordWrap(True)
        layout.addWidget(self.recovery_label)
        self.takeover = WorkflowTakeoverPane(self)
        self.takeover_source = self.takeover.source
        self.takeover_resolution = self.takeover.resolution
        self.takeover_preview_button = self.takeover.preview_button
        self.takeover_commit_button = self.takeover.commit_button
        self.takeover_label = self.takeover.label
        layout.addWidget(self.takeover)
        self.wait_label = ui(QLabel, tr('等待原因：无'))
        self.wait_label.setWordWrap(True)
        layout.addWidget(self.wait_label)
        self.metrics_label = ui(QLabel, tr('统计：暂无'))
        self.metrics_label.setWordWrap(True)
        layout.addWidget(self.metrics_label)
        layout.addWidget(ui(QLabel, tr('本次步骤结果（时长和调用仅含已观测部分）')))
        self.history_table = WorkflowRunHistory(self)
        layout.addWidget(self.history_table, 1)
        self.outputs = QPlainTextEdit()
        self.outputs.setReadOnly(True)
        ui(self.outputs.setPlaceholderText, tr('当前运行输出将在这里显示'))
        layout.addWidget(self.outputs, 1)
        self._timer = QTimer(self)
        self._timer.setInterval(900)
        self._timer.timeout.connect(self._poll_visible)
        self.session_path.textChanged.connect(self._session_path_edited)
        self.execution_path.textChanged.connect(self._session_path_edited)
        self._sync()

    @property
    def is_busy(self):
        return bool(self._jobs)

    def set_context(self, snapshot, step_id, *, dirty=False):
        """更新可启动版本；原运行账本保持独立。"""
        self._context = deepcopy(snapshot) if isinstance(snapshot, dict) else None
        self._step_id = step_id
        self._dirty = bool(dirty)
        self._sync()

    def _connection_matches(self):
        text = self.session_path.text().strip()
        return bool(text and self._connected_path is not None
                    and Path(text).resolve() == self._connected_path
                    and self._selected_execution_root() == self._client_execution_root)

    def _selected_execution_root(self):
        text = self.execution_path.text().strip()
        return Path(text).resolve() if text else None

    def _session_path_edited(self):
        if self._connected_path is not None and not self._connection_matches():
            self._reset_vision_declaration()
            ui(self.status_label.setText, tr('执行安装或会话选择已更改，请先连接；不会向原会话派发新请求。'))
        self._sync()

    def browse_execution(self):
        if not self.execution_browse_button.isEnabled():
            return
        selected = QFileDialog.getExistingDirectory(self, tr('选择兼容的执行模式安装目录'), self.execution_path.text())
        if selected:
            self.execution_path.setText(selected)

    def browse_session(self):
        if not self.browse_button.isEnabled():
            return
        selected = QFileDialog.getExistingDirectory(self, tr("选择已有执行会话"), self.session_path.text())
        if selected:
            self.session_path.setText(selected)

    def _factory(self):
        if self._client_factory is not None:
            return self._client_factory
        from .workflow_run_client import WorkflowRunClient
        return WorkflowRunClient

    def connect_latest(self):
        if not self.latest_button.isEnabled():
            return
        self.session_path.clear()
        self.connect_session()

    def connect_session(self):
        if self.is_busy:
            ui(self.status_label.setText, tr('后台读取尚未完成，不能切换会话。'))
            return
        if self._close_requested:
            return
        try:
            execution_root = self._selected_execution_root()
        except (OSError, ValueError) as error:
            self._show_error('执行模式安装目录无效：', error)
            return
        if getattr(sys, 'frozen', False) and execution_root is None:
            ui(self.status_label.setText, tr('请选择兼容的执行模式安装目录；未连接时仍可管理学习库。'))
            return
        if not self.session_path.text().strip():
            try:
                from app.core.json_snapshot import read_json_snapshot
                root = self.library_root.resolve().parent
                pointer = read_json_snapshot(root / "latest-session.json")
                name = pointer.get("name") if isinstance(pointer, dict) else None
                if not isinstance(name, str) or re.fullmatch(r"session-[0-9a-f]{32}", name) is None:
                    raise ValueError("workflow_run_session_pointer_mismatch")
                self.session_path.setText(str(root / name))
            except (OSError, ValueError) as error:
                self._show_error("尚无可连接的执行会话，请先回原 Agent 对话建立连接：", error)
                return
        path = Path(self.session_path.text()).resolve()
        if not path.is_dir():
            ui(self.status_label.setText, tr('请选择已有的会话文件夹。'))
            return
        same_target = (self._client is not None and path == self._client_session_path
                       and execution_root == self._client_execution_root)
        if self._client is not None and (self._pending or self._host_pending_ids) and not same_target:
            ui(self.status_label.setText, tr('原请求尚未结算，不能切换执行安装或会话；请先回读原请求。'))
            return
        if same_target:
            self._start_job("connect", self._client.connect)
            return
        try:
            if execution_root is None:
                client = self._factory()(path, self.library_root)
            else:
                client = self._factory()(path, self.library_root, execution_root=execution_root)
        except (OSError, ValueError, RuntimeError) as error:
            self._show_error('无法连接，请检查执行安装、会话与学习库：', error)
            return
        if self._client is not None:
            self._client.close()
        self._client = client
        self._client_session_path = path
        self._client_execution_root = execution_root
        self._reset_vision_declaration()
        self._connected_path = None
        self._host_alive = False
        self._host_pending_ids = []
        self._run = None
        self._terminal_preview = None
        self._terminal_recovery_id = None
        self.recovery_label.clear()
        self.takeover.reset()
        self._prepared_run = False
        self._recovery_blocked = False
        self._recovered_ids.clear()
        self._pending = None
        self._run_program_identity = None
        self._run_step_titles = {}
        ui(self.step_label.setText, tr('当前步骤：尚未运行'))
        self.step_label.setToolTip("")
        ui(self.target_label.setText, tr('当前目标：未连接'))
        ui(self.wait_label.setText, tr('等待原因：无'))
        self.wait_label.setToolTip("")
        ui(self.metrics_label.setText, tr('统计：暂无'))
        self.metrics_label.setToolTip("")
        self.history_table.setRowCount(0)
        self.outputs.clear()
        self.outputs.setToolTip("")
        ui(self.status_label.setText, tr('正在连接所选会话。'))
        self.status_label.setToolTip("")
        self._close_requested = False
        self._generation += 1
        self._start_job("connect", self._client.connect)

    def _start_job(self, kind, operation, *, request_id=None, mode=None):
        if self.is_busy or self._client is None or self._close_requested:
            return
        self._sequence += 1
        number = self._sequence
        job = make_job(number, operation, self)
        self._jobs[number] = (job, self._generation, kind, request_id, mode)
        job.succeeded.connect(self._succeeded)
        job.failed.connect(self._failed)
        job.finished.connect(self._job_finished)
        job.start()
        self.busyChanged.emit(True)
        self._sync()

    @Slot(int, object)
    def _succeeded(self, number, value):
        self._outcomes[number] = (True, value)

    @Slot(int, str)
    def _failed(self, number, error):
        self._outcomes[number] = (False, error)

    @Slot()
    def _job_finished(self):
        number = self.sender().request_id
        job, generation, kind, request_id, mode = self._jobs.pop(number)
        ok, value = self._outcomes.pop(number, (False, "后台操作未返回结果"))
        job.succeeded.disconnect(self._succeeded)
        job.failed.disconnect(self._failed)
        job.finished.disconnect(self._job_finished)
        job.deleteLater()
        if generation == self._generation and not self._close_requested:
            if ok:
                if kind == "terminal_preview":
                    self._accept_terminal_preview(value)
                elif kind in {"connect", "status", "terminal_settle"}:
                    self._accept_status(value)
                else:
                    self._accept_receipt(kind, request_id, mode, value)
            elif kind == "control":
                # 提交时异常也可能发生在派发后；原 ID 必须先回读。
                self._pending = {"request_id": request_id, "action": mode[0], "mode": mode[1]}
                self._show_error("请求状态未知，请回读原请求 ID：", value)
            else:
                if kind in {"connect", "status"}:
                    self._host_alive = False
                self._show_error("读取失败：", value)
        if self._close_requested and not self._jobs:
            self._finish_close()
        self.busyChanged.emit(self.is_busy)
        self._sync()

    def _show_error(self, prefix, error):
        raw = str(error)
        ui(self.status_label.setText, tr(prefix) + raw.splitlines()[0])
        self.status_label.setToolTip(raw)

    def _accept_status(self, value):
        if not isinstance(value, dict):
            self._host_alive = False
            ui(self.status_label.setText, tr('会话状态格式无效。'))
            return
        selected = Path(self.session_path.text()).resolve()
        actual = value.get("session_directory")
        if not actual or Path(actual).resolve() != selected:
            self._host_alive = False
            ui(self.status_label.setText, tr('会话目录与宿主报告不一致。'))
            return
        self._connected_path = selected
        source = value.get("recognition_source")
        if source != self._recognition_source:
            self._reset_vision_declaration()
            self._recognition_source = source
        ui(self.vision_checkbox.setText, {'agent_current': tr('此会话的 Agent 能接收并识别截图'), 'agent_delegate': tr('此会话的客户端能指定视觉子 Agent、传递截图并获得识图结果')}.get(source, ''))
        ui(self.vision_checkbox.setToolTip, tr('声明客户端能委派、选择视觉子模型、传递截图且子 Agent 能识图；不是输入授权。') if source == 'agent_delegate' else tr('仅声明本会话的识图能力，不是输入授权；未勾选表示能力未知。'))
        self._host_alive = value.get("host_alive") is True
        self.takeover.set_sources(value.get("takeover_sources", []))
        self._host_pending_ids = value.get("pending_ids") if isinstance(value.get("pending_ids"), list) else []
        target = value.get("target")
        ui(self.target_label.setText, tr('当前目标：') + (str(target.get('title') or target) if isinstance(target, dict) else str(target or tr('未报告'))))
        reported = value.get("workflow_run")
        preserve_prepared = self._prepared_run and self._run and isinstance(reported, dict) and reported.get("run_id") != self._run.get("run_id")
        if isinstance(reported, dict) and reported.get("run_id") and not preserve_prepared:
            if self._run and self._run.get("run_id") != reported.get("run_id"):
                self._terminal_preview = None
                self._terminal_recovery_id = None
                self.recovery_label.clear()
            self._show_run(reported)
            settlement = reported.get("recovery_settlement")
            if isinstance(settlement, dict):
                self._show_terminal_facts(settlement, settled=True)
                self._terminal_preview = None
        runtime_error = value.get("workflow_runtime_error")
        if runtime_error:
            ui(self.status_label.setText, tr('运行时报告错误；请在原会话检查。'))
            self.status_label.setToolTip(str(runtime_error))
        elif not isinstance(reported, dict) or not reported.get("run_id"):
            ui(self.status_label.setText, tr('已连接原会话。') if self._host_alive else tr('宿主未运行；只能回读已保存状态。'))
        if self._host_pending_ids:
            ui(self.status_label.setText, bound_text(self.status_label) + (tr(' 有旧请求未完成；请在原会话核对其 ID 与阶段，本面板不会猜测或重发。') if self._pending is None else tr(' 原请求尚未完成。')))
            self.status_label.setToolTip(str(self._host_pending_ids))
        self._recover_controls(value.get("recoverable_controls", []))
        if self._connected_path is not None:
            self.sessionChanged.emit(self._connected_path)
        self._timer.start()

    def _recover_controls(self, controls):
        if self._pending is not None:
            return
        if not isinstance(controls, list):
            self._recovery_blocked = True
            ui(self.status_label.setText, tr('原控制记录格式无效，请回原会话核对。'))
            return
        remaining = [item for item in controls if not isinstance(item, dict)
                     or item.get("request_id") not in self._recovered_ids]
        self._recovery_blocked = len(remaining) > 1
        if self._recovery_blocked:
            ui(self.status_label.setText, tr('发现多个未解决的原控制请求，请在原会话核对；不会猜测或新建运行。'))
            return
        if not remaining:
            return
        item = remaining[0]
        if (not isinstance(item, dict) or not isinstance(item.get("request_id"), str)
                or not isinstance(item.get("request"), dict) or item.get("action") not in
                {"start", "run", "continue", "status", "cancel", "verify", "takeover_preview", "takeover_commit"}):
            self._recovery_blocked = True
            ui(self.status_label.setText, tr('原控制记录不完整，请回原会话核对。'))
            return
        if item["action"] in {"takeover_preview", "takeover_commit"}:
            try:
                self.takeover.record_request(item["request"], item["request_id"], item.get("takeover_preview"))
            except (ValueError, KeyError, TypeError) as error:
                self._recovery_blocked = True
                self._show_error("原接管记录无法恢复：", error)
                return
        self._recovered_ids.add(item["request_id"])
        # 重开后恢复开始请求只读取原结果，不延续上次窗口的自动派发意图。
        self._accept_receipt("recovery", item["request_id"], (item["action"], None), item.get("receipt"))

    def _accept_receipt(self, kind, request_id, mode, receipt):
        if not isinstance(receipt, dict) or receipt.get("request_id") != request_id:
            self._pending = {"request_id": request_id, "action": mode[0], "mode": mode[1]}
            ui(self.status_label.setText, tr('回执 ID 不符；只能回读原请求。'))
            return
        state = receipt.get("status")
        if state == "pending":
            self._pending = {"request_id": request_id, "action": mode[0], "mode": mode[1]}
            ui(self.status_label.setText, tr('原请求仍在执行；刷新将回读同一 ID。'))
            return
        if state in {"result_unknown", "not_found"}:
            self._pending = {"request_id": request_id, "action": mode[0], "mode": mode[1]}
            ui(self.status_label.setText, tr('结果未知；保留原请求 ID，禁止重发。'))
            return
        if mode[0] in {"takeover_preview", "takeover_commit"} and state != "returned":
            self._pending = {"request_id": request_id, "action": mode[0], "mode": mode[1]}
            ui(self.status_label.setText, tr('原接管请求未成功；保留原 ID 回读，不会重发。'))
            self.status_label.setToolTip(str(receipt))
            return
        if state == "not_submitted":
            self._pending = None
            reason = receipt.get("reason")
            ids = receipt.get("pending_ids")
            if isinstance(ids, list):
                self._host_pending_ids = ids
            if reason == "host_not_ready":
                self._host_alive = False
            ui(self.status_label.setText, tr('请求未入队；请先处理原队列或检查连接。不会自动重发。'))
            self.status_label.setToolTip(str(receipt))
            return
        if state != "returned":
            self._pending = None
            ui(self.status_label.setText, tr('原请求失败；请检查原会话回执。'))
            self.status_label.setToolTip(str(receipt.get("result", receipt)))
            return
        result = receipt.get("result")
        if (mode[0] not in {"takeover_preview", "takeover_commit"}
                and (not isinstance(result, dict) or not isinstance(result.get("run_id"), str))):
            self._pending = {"request_id": request_id, "action": mode[0], "mode": mode[1]}
            ui(self.status_label.setText, tr('返回数据缺少运行 ID；禁止重发，需检查原回执。'))
            return
        if mode[0] in {"takeover_preview", "takeover_commit"}:
            try:
                if receipt.get("operation_succeeded") is False:
                    raise ValueError("原接管请求未成功")
                if mode[0] == "takeover_preview":
                    self.takeover.accept_preview(request_id, result)
                else:
                    self.takeover.accept_commit(result)
            except (ValueError, KeyError, TypeError) as error:
                self._pending = {"request_id": request_id, "action": mode[0], "mode": mode[1]}
                self._show_error("原接管结果需核对，禁止重发：", error)
                return
            self._pending = None
            self._host_pending_ids = [value for value in self._host_pending_ids if value != request_id]
            if mode[0] == "takeover_commit":
                self._show_run(result)
            else:
                ui(self.status_label.setText, tr('当前效果预览已返回；请查看后明确提交接管。'))
            return
        self._pending = None
        self._host_pending_ids = [value for value in self._host_pending_ids if value != request_id]
        self._show_run(result)
        if mode[0] == "start":
            if result.get("status") != "ready" or receipt.get("operation_succeeded") is False:
                ui(self.status_label.setText, tr('启动请求已返回，但运行尚未就绪；请检查原回执。'))
                return
            run_id = result["run_id"]
            self._prepared_run = True
            if mode[1] is None:
                ui(self.status_label.setText, tr('已找回原来的准备结果；请选择运行单步或连续运行，不会重新创建任务。'))
                return
            self._control(self._run_request(run_id, mode[1], self._start_vision_capabilities), "run", mode[1])

    def _show_run(self, snapshot):
        self._run = deepcopy(snapshot)
        identity = (snapshot.get("workflow_id"), snapshot.get("program_id"))
        if identity != self._run_program_identity:
            self._run_program_identity = identity
            self._run_step_titles = {}
        context = self._context or {}
        if identity[1] and identity == (context.get("workflow_id"), context.get("program_id")):
            self._run_step_titles = {step["step_id"]: _ACTION_TITLES.get(step["title"], step["title"])
                for step in context.get("definition", {}).get("steps", [])}
        step_id = snapshot.get("current_step_id")
        ui(self.step_label.setText, tr('当前步骤：') + self._run_step_titles.get(step_id, tr('全部步骤已结束') if snapshot.get('status') == 'completed' else tr('运行版本中的步骤')))
        self.step_label.setToolTip(str(step_id or ""))
        if snapshot.get("runner_state"):
            self._prepared_run = False
        state = snapshot.get("runner_state") or snapshot.get("status") or "未知"
        ui(self.status_label.setText, tr('当前运行：') + _STATE_LABELS.get(state, tr('状态待核对')))
        ui(self.status_label.setToolTip, tr('运行 ID：') + str(snapshot.get('run_id')) + tr('；步骤 ID：') + str(snapshot.get('current_step_id')))
        reason = snapshot.get("wait_reason") or (snapshot.get("wait") or {}).get("reason")
        wait_text = _WAIT_LABELS.get(reason, str(reason)) if reason else tr("无")
        detail = str(snapshot.get("reason") or "")
        if reason == "input_required" and detail.startswith("workflow_trial_upstream_output_missing:"):
            reference = detail.partition(":")[2]
            source_step, _, name = reference.partition(".")
            source_title = self._run_step_titles.get(source_step, source_step)
            wait_text += tr("；缺少“{v0}”的本次输出“{v1}”。请从来源步骤运行，或将填写来源改为本次输入后保存新版本。", v0=source_title, v1=name)
        ui(self.wait_label.setText, tr('等待原因：') + wait_text)
        self.wait_label.setToolTip(detail)
        metrics = snapshot.get("metrics")
        if isinstance(metrics, dict) and metrics:
            parts = [
                tr("{label} {value}", label=_METRIC_LABELS.get(key, key), value=value) for key, value in metrics.items()
                if key in _METRIC_LABELS and isinstance(value, (str, int, float, bool))]
            if "total_model_calls" in metrics:
                total = metrics["total_model_calls"]
                parts.append(tr("模型调用总量未知") if total is None else tr("模型调用总量 {v0}", v0=total))
            if "total_usage" in metrics:
                usage = metrics["total_usage"]
                parts.append(tr("token 总量未知") if usage is None else tr("token 用量见详细记录"))
            ui(self.metrics_label.setText, tr('统计：') + join_text('; ', parts or [tr('部分计量可用，完整数据见详细记录')]))
            self.metrics_label.setToolTip(json.dumps(metrics, ensure_ascii=False, sort_keys=True))
        else:
            ui(self.metrics_label.setText, tr('统计：暂无'))
            self.metrics_label.setToolTip("")
        self.history_table.show_snapshot(snapshot, self._run_step_titles)
        self.takeover.show_run(snapshot)
        outputs = snapshot.get("outputs")
        if isinstance(outputs, dict) and outputs:
            self.outputs.setPlainText("\n".join(
                f"{name}：{value.get('value') if isinstance(value, dict) and 'value' in value else value}"
                for name, value in outputs.items()))
            self.outputs.setToolTip(json.dumps(outputs, ensure_ascii=False, indent=2))
        else:
            ui(self.outputs.setPlainText, tr("当前没有输出。"))
            self.outputs.setToolTip("")
        if reason in {"grounding_required", "verification_required"}:
            ui(self.status_label.setText, bound_text(self.status_label) + tr('；需 Agent 在原会话判断并补充证据。'))

    def _control(self, request, action, mode=None):
        if (self._client is None or self._pending is not None or self.is_busy
                or not self._host_alive or not self._connection_matches() or self._is_recovery_paused()):
            return
        request_id = "workflow-ui-" + uuid4().hex
        if action in {"takeover_preview", "takeover_commit"}:
            if not self.takeover._can_queue():
                return
            try:
                self.takeover.record_request(request, request_id)
            except (ValueError, KeyError, TypeError) as error:
                self._show_error("接管请求无法准备：", error)
                return
        client = self._client
        self._pending = {"request_id": request_id, "action": action, "mode": mode}
        self._start_job("control", lambda: client.control(deepcopy(request), request_id),
                        request_id=request_id, mode=(action, mode))

    def _start(self, mode):
        if not self._can_start():
            return
        if self._prepared_run:
            self._control(self._run_request(self._run["run_id"], mode, self._declared_vision_capabilities()), "run", mode)
            return
        if not callable(self.inputs_provider):
            ui(self.status_label.setText, tr('当前没有任务输入提供入口。'))
            return
        try:
            inputs = self.inputs_provider()
        except Exception as error:
            self._show_error("任务输入无效：", error)
            return
        if inputs is None:
            return
        if not isinstance(inputs, dict):
            ui(self.status_label.setText, tr('任务输入须为已声明字段。'))
            return
        # 明确启动时冻结声明，异步准备回执不能读取后来改变的控件。
        self._start_vision_capabilities = self._declared_vision_capabilities()
        self._control({"action": "start", "workflow_id": self._context["workflow_id"],
                       "program_id": self._context["program_id"], "start_step_id": self._step_id,
                       "inputs": deepcopy(inputs)}, "start", mode)

    def _reset_vision_declaration(self):
        self.vision_checkbox.setChecked(False)
        self.vision_checkbox.setText("")
        self._recognition_source = None
        self._start_vision_capabilities = None

    def _declared_vision_capabilities(self):
        if not self.vision_checkbox.isChecked():
            return None
        required = {
            "agent_current": ("image_transport", "current_vision"),
            "agent_delegate": ("image_transport", "delegation", "model_selection", "delegate_vision"),
        }.get(self._recognition_source, ())
        return {name: "supported" for name in required} if required else None

    def _run_request(self, run_id, mode, capabilities=None):
        request = {"action": "run", "run_id": run_id, "mode": mode}
        if capabilities is not None:
            request["vision_capabilities"] = deepcopy(capabilities)
        return request

    def start_single(self):
        self._start("single")

    def start_continuous(self):
        self._start("until_wait")

    def refresh(self):
        if self._client is None or self.is_busy or self._close_requested:
            return
        client = self._client
        if not self._host_alive:
            self._start_job("status", client.connect)
            return
        if self._pending is not None:
            pending = deepcopy(self._pending)
            self._start_job("result", lambda: client.result(pending["request_id"]),
                            request_id=pending["request_id"], mode=(pending["action"], pending["mode"]))
        else:
            self._start_job("status", client.connect)

    def continue_run(self):
        if not self.continue_button.isEnabled():
            return
        wait = self._run["wait"]
        self._control({"action": "continue", "run_id": self._run["run_id"],
                       "wait_id": wait["wait_id"]}, "continue")

    def cancel_run(self):
        if not self.cancel_button.isEnabled():
            return
        self._control({"action": "cancel", "run_id": self._run["run_id"]}, "cancel")

    def _can_start(self):
        context = self._context or {}
        state = (self._run or {}).get("runner_state") or (self._run or {}).get("status")
        ready_pinned = (self._prepared_run and state == "ready"
                        and self._run.get("program_id") == context.get("program_id")
                        and self._run.get("workflow_id") == context.get("workflow_id")
                        and self._run.get("start_step_id") == self._step_id)
        return bool(self._host_alive and not self._is_recovery_paused() and not self.takeover.blocks_new_run
                    and self._connection_matches() and not self._dirty
                    and isinstance(context.get("workflow_id"), str) and context.get("program_id")
                    and isinstance(self._step_id, str) and self._step_id and
                    (self._run is None or state in _TERMINAL or ready_pinned) and not self._host_pending_ids
                    and not self._recovery_blocked
                    and self._pending is None and not self.is_busy)

    def _sync(self):
        active = self._client is not None and self._connected_path is not None and not self._close_requested
        can_select = not self.is_busy and not self._close_requested and not self._pending and not self._host_pending_ids
        self.connect_button.setEnabled(not self.is_busy and not self._close_requested)
        self.latest_button.setEnabled(bool(can_select))
        self.browse_button.setEnabled(bool(can_select))
        self.session_path.setEnabled(bool(can_select))
        self.execution_browse_button.setEnabled(bool(can_select))
        self.execution_path.setEnabled(bool(can_select))
        self.single_button.setEnabled(self._can_start())
        self.run_button.setEnabled(self._can_start())
        self.refresh_button.setEnabled(active and not self.is_busy)
        wait = (self._run or {}).get("wait") or {}
        reason = (self._run or {}).get("wait_reason") or wait.get("reason")
        can_act = active and self._connection_matches() and self._host_alive and not self._is_recovery_paused() and not self.is_busy and self._pending is None and bool(self._run)
        recoverable = bool(active and self._connection_matches() and not self._host_alive
            and self._run and self._run.get("run_id") and not self._is_recovery_paused()
            and ((self._run.get("active_command_id") or self._run.get("pending") or self._host_pending_ids)
                 or self._terminal_preview))
        self.recovery_button.setVisible(recoverable or self._is_recovery_paused())
        self.recovery_button.setEnabled(recoverable and not self.is_busy)
        ui(self.recovery_button.setText, tr('结算已保存结果') if self._terminal_preview else tr('核对已保存结果'))
        self.continue_button.setEnabled(bool(can_act and wait.get("wait_id") and reason not in
                                             {"execution_pending", "queue_busy", "result_unknown", "grounding_required"}))
        state = (self._run or {}).get("runner_state") or (self._run or {}).get("status")
        if active and not self._host_alive and tr("宿主未运行；以下为已保存状态。") not in self.status_label.text():
            note = tr("宿主未运行；以下为已保存状态。")
            if state not in _TERMINAL and (self._run or self._pending or self._host_pending_ids):
                note += tr("未决输入可能已发生；请核对原请求，不能重发。")
            ui(self.status_label.setText, note + " " + bound_text(self.status_label))
        self.vision_checkbox.setVisible(self._recognition_source in {"agent_current", "agent_delegate"})
        self.vision_checkbox.setEnabled(bool(active and self._connection_matches() and self._host_alive
            and not self.is_busy and self._pending is None and not self._host_pending_ids
            and not self._recovery_blocked and (self._run is None or state in _TERMINAL
                                                or self._prepared_run and state == "ready")))
        self.cancel_button.setEnabled(bool(can_act and state not in _TERMINAL))
        self.takeover.sync()

    def _is_recovery_paused(self):
        run = self._run or {}
        return bool(run.get("runner_state") == "recovery_paused" or run.get("recovery_settlement"))

    def _show_terminal_facts(self, value, *, settled=False):
        fact = value.get("action_executed")
        action = tr("已发生") if fact is True else tr("未发生") if fact is False else tr("未知")
        ui(self.recovery_label.setText, tr('{v0}原步骤 {v1}：原动作终态 {v2}；输入动作{v3}；业务结果仍未核验。', v0=tr('已结算') if settled else tr('已核对'), v1=value.get('step_id', tr('未知')), v2=value.get('terminal_status', tr('未知')), v3=action) + (tr('恢复已暂停，不能继续或启动输入。') if settled else tr('请明确结算此原动作。')))

    def _accept_terminal_preview(self, value):
        run = self._run or {}
        if (not isinstance(value, dict)
                or value.get("contract_version") != "workflow_terminal_recovery_preview.v1"
                or value.get("run_id") != run.get("run_id")
                or not value.get("step_id") or not value.get("execution_request_id")
                or (run.get("current_step_id") and value.get("step_id") != run["current_step_id"])
                or (run.get("active_command_id") and value.get("execution_request_id") != run["active_command_id"])
                or value.get("terminal_status") not in _TERMINAL
                or type(value.get("action_executed")) not in {bool, type(None)}
                or value.get("task_effect_verified") is not None):
            self._show_error("已保存结果无法核对：", "原终态预览格式或运行绑定无效")
            return
        self._terminal_preview = deepcopy(value)
        self._terminal_recovery_id = "workflow-recovery-ui-" + uuid4().hex
        self._show_terminal_facts(value)

    def recover_saved_terminal(self):
        if not self.recovery_button.isEnabled():
            return
        client = self._client
        if self._terminal_preview is None:
            run_id = self._run["run_id"]
            self._start_job("terminal_preview", lambda: client.preview_recovery(run_id))
        else:
            # 失败后的重读沿用原预览和原恢复请求，不创建输入命令。
            preview = deepcopy(self._terminal_preview)
            request_id = self._terminal_recovery_id
            self._start_job("terminal_settle", lambda: client.settle_recovery(preview, request_id=request_id))

    def _poll_visible(self):
        run = self._run or {}
        state = run.get("runner_state") or run.get("status")
        reason = run.get("wait_reason") or (run.get("wait") or {}).get("reason")
        # 等待明确操作和终态保持静止，只有未决原请求及运行过渡需要自动回读。
        unsettled = (self._pending or self._host_pending_ids
            or state in {"running", "dispatching", "cancel_requested"}
            or run.get("runner_state") == "ready" and not self._prepared_run
            or reason in {"execution_pending", "queue_busy", "result_unknown"})
        if (self.isVisible() and self._client is not None and not self.is_busy
                and not self._close_requested and unsettled):
            self.refresh()

    def cancel_loading(self):
        self._generation += 1
        self._timer.stop()

    def close_client(self):
        self.cancel_loading()
        self._close_requested = True
        if not self._jobs:
            self._finish_close()
        self._sync()

    def _finish_close(self):
        if self._client is not None:
            self._client.close()
        self._client = None
        self._reset_vision_declaration()
        self._connected_path = None
        self._client_session_path = None
        self._client_execution_root = None
        self._host_alive = False
        self._host_pending_ids = []
        self._pending = None
        self._close_requested = False

    def closeEvent(self, event):
        self.close_client()
        super().closeEvent(event)


__all__ = ["WorkflowRunPanel"]
