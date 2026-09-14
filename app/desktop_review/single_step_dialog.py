"""单次人工审核、批准和执行窗口；绝不自动执行下一步。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLayout,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from .grounded_preview_widget import GroundedPreviewWidget, validate_review_view
from .jobs import make_job
from .single_step import NativeSingleStepError, validate_single_step_response
from app.agent.action_semantics import REVIEWED_SINGLE_STEP_ACTIONS
from app.agent.text_parameters import ReviewedTextParameters
from .text_input_dialog import TextInputDialog


@dataclass(frozen=True)
class _JobFailure:
    code: str
    result_unknown: bool
    retry_preparation: bool = False
    computation_stopped: bool = False


def _safe_operation(operation):
    try:
        return operation()
    except Exception as error:  # 仅传播稳定分类，不把内部异常或凭据放进 Qt traceback。
        code = getattr(error, "code", "single_step_failed")
        if not isinstance(code, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code) is None:
            code = "single_step_failed"
        return _JobFailure(
            code, getattr(error, "result_unknown", False) is True,
            getattr(error, "retry_preparation", False) is True,
            getattr(error, "computation_stopped", False) is True,
        )


class SingleStepDialog(QDialog):
    _finished_job = Signal(object)

    def __init__(self, coordinator, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        self._jobs = set()
        self._request_id = 0
        self._operation = None
        self._phase = "idle"
        self._selection = None
        self._session_id = None
        self._selected_action = None
        self._has_owner = False
        self._retry_preparation = False
        self._close_requested = False
        self._closing_verified = False
        self._pending_text_parameters = None
        self._text_input_dialog = None
        self._window_preparation = None
        self._queued_followup = None
        self._agent_review_source_kind = None
        self._automatic_safety_interception = True
        self._safety_settings_known = True
        self._safety_settings_available = False
        self._keep_models_loaded = False
        self._resident_model_count = 0
        self._model_residency_known = False
        self._model_residency_available = False
        self._model_residency_supported = False
        self._requested_model_residency = None
        self._model_close_cleanup_verified = False
        self._finished_job.connect(self._job_finished)
        self._followup_timer = QTimer(self)
        self._followup_timer.setSingleShot(True)
        self._followup_timer.timeout.connect(self._start_queued_followup)
        self.setWindowTitle("单步验证 · 人工审核后执行")
        self.resize(1360, 820)
        self.setMinimumSize(1000, 650)
        self._build_ui()
        self._load_safety_settings()
        self._load_model_residency_settings()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._update_controls()

    def _label(self, text):
        label = QLabel(text, self)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        return label

    def _button(self, text, handler):
        button = QPushButton(text, self)
        button.setAutoDefault(False)
        button.clicked.connect(handler)
        return button

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        heading = self._label("1 读取 Agent 动作（或选择调试流程）   →   2 检查定位   →   3 批准   →   4 只执行一步")
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)
        self.status_label = self._label("尚未预检。请先刷新并明确选择流程和窗口。")
        self.status_label.setAccessibleName("单步验证状态与切窗指引")
        self.status_label.setStyleSheet("QLabel { background: #eaf2ff; color: #173e75; border: 1px solid #8bb5ed; border-radius: 6px; padding: 10px; font-weight: 600; }")
        layout.addWidget(self.status_label)
        layout.addWidget(self._label("首次学习也可先选择窗口，点击“恢复/聚焦选定窗口…”并确认，再让 Agent 截图。预检可能启动模型；只读截图不会抢前台，窗口准备不会执行下一步。"))
        safety_row = QHBoxLayout()
        self.safety_checkbox = QCheckBox("自动安全拦截", self)
        self.safety_checkbox.setAccessibleName("自动安全拦截，仅本次会话")
        self.safety_checkbox.toggled.connect(self._change_safety_setting)
        safety_row.addWidget(self.safety_checkbox)
        self.safety_status_label = self._label("自动拦截已开启")
        self.safety_status_label.setAccessibleName("自动安全拦截当前状态")
        safety_row.addWidget(self.safety_status_label, 1)
        layout.addLayout(safety_row)
        self.safety_boundary_label = self._label(
            "仅本次会话生效。关闭后，本地无学习单步免一次性授权；请求身份、数据完整性和支持动作类型仍检查。"
            "对 Agent 新学习/界面复用单步，关闭不是批准，仍需单步确认；旧已发布流程的调试入口仍需开启。"
        )
        layout.addWidget(self.safety_boundary_label)
        residency_row = QHBoxLayout()
        self.model_residency_checkbox = QCheckBox("保持模型驻留（允许多模型）", self)
        self.model_residency_checkbox.setAccessibleName("保持模型驻留，允许多模型，仅本次会话")
        self.model_residency_checkbox.toggled.connect(self._change_model_residency)
        residency_row.addWidget(self.model_residency_checkbox)
        self.model_residency_status_label = self._label("模型驻留状态尚未读取")
        self.model_residency_status_label.setAccessibleName("模型驻留状态与数量")
        residency_row.addWidget(self.model_residency_status_label, 1)
        self.release_models_button = self._button("释放驻留模型", self._release_resident_models)
        residency_row.addWidget(self.release_models_button)
        layout.addLayout(residency_row)
        self.model_residency_warning_label = self._label(
            "默认关闭，仅本次会话生效。开启不会立即启动模型；多个模型会持续占用内存/显存。"
            "关闭本窗口会释放本协调器驻留模型，不关闭外部服务。"
        )
        layout.addWidget(self.model_residency_warning_label)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        choices = QGroupBox("本次验证目标", self)
        choices.setMinimumWidth(235)
        choice_layout = QVBoxLayout(choices)
        choice_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.asset_selector = QComboBox(self)
        self.window_selector = QComboBox(self)
        self.action_selector = QComboBox(self)
        for selector, name in ((self.asset_selector, "已发布流程"), (self.window_selector, "目标窗口（HWND / PID）"), (self.action_selector, "服务器提供的动作")):
            selector.setPlaceholderText("请明确选择")
            selector.setMinimumContentsLength(20)
            selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            selector.setAccessibleName(name)
            selector.currentIndexChanged.connect(self._update_controls)
            form.addRow(name, selector)
        choice_layout.addLayout(form)
        self.refresh_button = self._button("刷新流程与窗口", self._refresh)
        self.history_button = self._button("执行历史与恢复…", self._open_history)
        self.environment_button = self._button("检查运行环境", self._check_environment)
        self.prepare_button = self._button("预检选定目标", self._prepare)
        self.launch_window_button = self._button("启动流程对应程序…", self._preview_launch_window)
        self.focus_window_button = self._button("恢复/聚焦选定窗口…", self._preview_focus_window)
        self.review_button = self._button("生成定位预览", self._request_review)
        self.fresh_review_button = self._button("读取 Agent 待确认动作", self._read_fresh_review)
        self.fresh_review_button.setToolTip("只读取当前本地 owner 已持久化的 Agent 待审预览；不会批准或执行。")
        for button in (self.refresh_button, self.history_button, self.environment_button, self.launch_window_button, self.focus_window_button, self.prepare_button, self.review_button, self.fresh_review_button):
            choice_layout.addWidget(button)
        choice_layout.addWidget(self._label("调试入口使用已发布版本；Agent 首次学习不需要已有流程。\n\n青色框：识别范围\n橙色十字：计划点击点\n拖动平移，Ctrl+滚轮缩放。"))
        choice_layout.addStretch()
        choices_scroll = QScrollArea(self)
        choices_scroll.setWidgetResizable(True)
        choices_scroll.setWidget(choices)
        choices_scroll.setMinimumWidth(255)
        splitter.addWidget(choices_scroll)
        self.preview_widget = GroundedPreviewWidget(self)
        splitter.addWidget(self.preview_widget)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([245, 1085])
        layout.addWidget(splitter, 3)
        self.receipt_text = QPlainTextEdit(self)
        self.receipt_text.setReadOnly(True)
        self.receipt_text.setMaximumHeight(140)
        self.receipt_text.setPlaceholderText("执行回执会显示在这里；回执不是下一步的授权。")
        self.receipt_text.setAccessibleName("单步执行回执，只读")
        layout.addWidget(self.receipt_text, 1)
        self.environment_report = QPlainTextEdit(self)
        self.environment_report.setReadOnly(True)
        self.environment_report.setMaximumHeight(140)
        self.environment_report.setPlaceholderText("运行环境元数据报告会显示在这里；它不构成 Runtime、模型或窗口已就绪的证明。")
        self.environment_report.setAccessibleName("运行环境元数据报告，只读")
        layout.addWidget(self.environment_report, 1)
        buttons = QHBoxLayout()
        self.stop_wait_button = self._button("停止等待/识别请求", self._stop_wait)
        self.stop_wait_button.setToolTip("取消前台或模型就绪等待，以及受管本地模型的识别请求；服务端计算未确认停止，不能撤销已经开始的执行。")
        self.cancel_button = self._button("取消本次 / 释放目标", self._cancel)
        self.approve_button = self._button("批准本次预检", self._approve)
        self.deny_button = self._button("拒绝 Agent 动作", self._deny)
        self.execute_button = self._button("执行这一步…", self._execute)
        self.close_button = self._button("关闭", self.close)
        for button in (self.stop_wait_button, self.cancel_button):
            buttons.addWidget(button)
        buttons.addStretch()
        for button in (self.approve_button, self.deny_button, self.execute_button, self.close_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def _is_selecting(self):
        return (not self._jobs and self._phase == "idle" and not self._has_owner
                and self._window_preparation is None
                and not (self._text_input_dialog is not None and self._text_input_dialog.isVisible()))

    @staticmethod
    def _checked_safety_settings(value):
        if (not isinstance(value, dict)
                or set(value) != {"automatic_safety_interception", "scope", "session_only"}
                or type(value["automatic_safety_interception"]) is not bool
                or value["scope"] != "automatic_risk_policy" or value["session_only"] is not True):
            raise ValueError("invalid automatic safety settings")
        return value["automatic_safety_interception"]

    def _render_safety_settings(self):
        blocked = self.safety_checkbox.blockSignals(True)
        try:
            self.safety_checkbox.setChecked(self._automatic_safety_interception)
        finally:
            self.safety_checkbox.blockSignals(blocked)
        if not self._safety_settings_known:
            self.safety_status_label.setText("自动安全拦截状态未知：读取失败；未批准或执行动作。")
        elif self._automatic_safety_interception:
            self.safety_status_label.setText("自动拦截已开启")
        else:
            self.safety_status_label.setText(
                "自动拦截已关闭：本地无学习单步免一次性授权，仍检查目标与截图并记录结果。已有学习步骤保留原确认流程。"
            )
        self.safety_status_label.setStyleSheet(
            "QLabel { color: #8f1d17; background: #fff1ed; border: 1px solid #c85a4f; "
            "border-radius: 6px; padding: 7px; font-weight: 700; }"
            if not self._safety_settings_known or not self._automatic_safety_interception
            else "QLabel { color: #173e75; font-weight: 600; padding: 7px; }"
        )

    def _load_safety_settings(self):
        getter = getattr(self.coordinator, "safety_settings", None)
        setter = getattr(self.coordinator, "set_automatic_safety_interception", None)
        self._safety_settings_available = callable(getter) and callable(setter)
        if not self._safety_settings_available:
            self._automatic_safety_interception = True
            self._safety_settings_known = True
            self.safety_checkbox.setToolTip("当前连接不支持修改此设置，保持默认开启。")
        else:
            self.safety_checkbox.setToolTip("仅在尚未持有目标、审核或执行的选择阶段可修改。")
            try:
                self._automatic_safety_interception = self._checked_safety_settings(getter())
                self._safety_settings_known = True
            except Exception:  # 读取失败明确呈现未知状态，不把私有诊断写入界面。
                self._safety_settings_known = False
                self._safety_settings_available = False
                self.status_label.setText("读取自动安全拦截设置失败，当前状态未知；未批准或执行动作。")
        self._render_safety_settings()
        self._update_controls()

    def _change_safety_setting(self, enabled):
        if not self._safety_settings_available or not self._is_selecting():
            self._render_safety_settings()
            self._update_controls()
            return
        try:
            result = self.coordinator.set_automatic_safety_interception(enabled)
            actual = self._checked_safety_settings(result)
            if actual is not enabled:
                raise ValueError("automatic safety setting did not take effect")
            self._automatic_safety_interception = actual
            self._safety_settings_known = True
        except Exception as error:  # setter 可能在改变后失败，必须回读真实设置而非盲目取反。
            self._load_safety_settings()
            detail = "已重新读取当前设置。" if self._safety_settings_known else "当前设置读取也失败，状态未知。"
            if getattr(error, "code", None) == "safety_mode_change_unavailable":
                detail = "请先取消当前步骤，再切换自动安全拦截。" + detail
            self.status_label.setText("修改自动安全拦截失败；" + detail + "未批准或执行动作。")
            return
        self._render_safety_settings()
        self._update_controls()
        self.status_label.setText("自动安全拦截设置已更新，仅本次会话生效；未批准或执行动作。")

    @staticmethod
    def _checked_model_residency_settings(value):
        if (not isinstance(value, dict)
                or set(value) != {"keep_models_loaded", "allow_multiple_models", "resident_model_count", "session_only"}
                or type(value["keep_models_loaded"]) is not bool
                or type(value["allow_multiple_models"]) is not bool
                or value["allow_multiple_models"] is not value["keep_models_loaded"]
                or type(value["resident_model_count"]) is not int or value["resident_model_count"] < 0
                or value["session_only"] is not True):
            raise ValueError("invalid model residency settings")
        return value["keep_models_loaded"], value["resident_model_count"]

    def _render_model_residency_settings(self):
        blocked = self.model_residency_checkbox.blockSignals(True)
        try:
            self.model_residency_checkbox.setChecked(self._keep_models_loaded)
        finally:
            self.model_residency_checkbox.blockSignals(blocked)
        if not self._model_residency_supported:
            text = "当前连接不支持模型驻留选项；未更改模型生命周期。"
        elif not self._model_residency_known:
            text = "模型驻留状态未知：读取失败，不能修改或确认释放。"
        else:
            mode = "已开启" if self._keep_models_loaded else "已关闭"
            text = f"模型驻留{mode} · 当前驻留 {self._resident_model_count} 个"
            if not self._model_residency_available:
                text += "；当前连接不支持修改或释放。"
        self.model_residency_status_label.setText(text)
        self.model_residency_status_label.setStyleSheet(
            "QLabel { color: #8f4b13; font-weight: 600; }"
            if self._keep_models_loaded or (self._model_residency_supported and not self._model_residency_known)
            else "QLabel { color: #173e75; }"
        )

    def _load_model_residency_settings(self):
        getter = getattr(self.coordinator, "model_residency_settings", None)
        setter = getattr(self.coordinator, "set_keep_models_loaded", None)
        releaser = getattr(self.coordinator, "release_resident_models", None)
        self._model_residency_supported = any(callable(method) for method in (getter, setter, releaser))
        self._model_residency_available = all(callable(method) for method in (getter, setter, releaser))
        if not self._model_residency_supported:
            self._keep_models_loaded = False
            self._resident_model_count = 0
            self._model_residency_known = False
        else:
            try:
                self._keep_models_loaded, self._resident_model_count = self._checked_model_residency_settings(getter())
                self._model_residency_known = True
            except Exception:  # 只读取内存快照；私有诊断不进入界面。
                self._model_residency_known = False
                self._model_residency_available = False
        self.model_residency_checkbox.setToolTip(
            "仅在未持有目标、没有后台任务或待审核动作时可修改；关闭后后台释放模型。"
            if self._model_residency_available else "当前连接不支持此设置或状态未知，不能更改。"
        )
        self._render_model_residency_settings()

    def _change_model_residency(self, enabled):
        if not self._model_residency_available or not self._is_selecting():
            self._render_model_residency_settings()
            self._update_controls()
            return
        self._requested_model_residency = enabled
        self._render_model_residency_settings()
        self._launch("model_residency_set", lambda: self.coordinator.set_keep_models_loaded(enabled))

    def _release_resident_models(self):
        if self.release_models_button.isEnabled() and self._is_selecting():
            self._launch("model_residency_release", self.coordinator.release_resident_models)

    def _load_model_residency_result(self, result):
        enabled, count = self._checked_model_residency_settings(result)
        if self._operation == "model_residency_set":
            if enabled is not self._requested_model_residency or (not enabled and count != 0):
                raise ValueError("model residency setting did not take effect")
        elif (count != 0 or (self._model_residency_known and enabled is not self._keep_models_loaded)):
            raise ValueError("model service cleanup or preference is not verified")
        self._keep_models_loaded, self._resident_model_count = enabled, count
        self._model_residency_known = True
        self._requested_model_residency = None
        self._render_model_residency_settings()
        if self._operation == "model_residency_close":
            self._model_close_cleanup_verified = True
            self.status_label.setText("本窗口拥有的驻留模型已核验释放；外部服务未关闭。")
        elif self._operation == "model_residency_release":
            self.status_label.setText("驻留模型已核验释放；驻留偏好未更改，下次使用时按需启动。")
        else:
            self.status_label.setText("模型驻留设置已更新，仅本次会话生效；未启动新模型或执行动作。")

    def _model_residency_failure(self, code):
        self._requested_model_residency = None
        self._close_requested = False
        self._model_close_cleanup_verified = False
        self._load_model_residency_settings()
        detail = "已回读当前设置与驻留数量。" if self._model_residency_known else "读取当前状态失败，状态未知。"
        if code == "model_residency_change_unavailable":
            detail = "请先取消当前步骤并等待后台任务结束，再修改或释放。" + detail
        elif code == "model_service_cleanup_pending":
            detail = "模型释放尚未核验，保留窗口与清理记录，可重试释放或关闭。" + detail
        self.status_label.setText(f"模型驻留操作失败（{code}）。{detail}未批准或执行动作。")

    def _update_controls(self, *_args):
        if not hasattr(self, "preview_widget"):
            return
        busy = bool(self._jobs) or (self._text_input_dialog is not None and self._text_input_dialog.isVisible())
        selecting = self._is_selecting()
        self.safety_checkbox.setEnabled(selecting and self._safety_settings_available)
        self.model_residency_checkbox.setEnabled(selecting and self._model_residency_available)
        self.release_models_button.setEnabled(
            selecting and self._model_residency_available and self._resident_model_count > 0
        )
        self.asset_selector.setEnabled(selecting)
        self.window_selector.setEnabled(selecting)
        self.refresh_button.setEnabled(selecting)
        self.history_button.setEnabled(selecting)
        self.environment_button.setEnabled(selecting)
        retrying = self._phase == "prepare_recovery_required" and self._retry_preparation
        self.prepare_button.setText("重试原目标预检" if retrying else "预检选定目标")
        self.prepare_button.setEnabled((not busy and retrying) or (selecting and self.asset_selector.currentData() is not None and self.window_selector.currentData() is not None))
        self.launch_window_button.setEnabled(selecting and self.asset_selector.currentData() is not None)
        fresh_window_preparation = callable(getattr(self.coordinator, "preview_selected_window_preparation", None))
        self.focus_window_button.setEnabled(selecting and self.window_selector.currentData() is not None
            and (self.asset_selector.currentData() is not None or fresh_window_preparation))
        self.action_selector.setEnabled(not busy and self._phase == "observed")
        self.review_button.setEnabled(not busy and self._phase == "observed" and self.action_selector.currentData() is not None)
        self.fresh_review_button.setEnabled(not busy and self._phase == "idle" and not self._has_owner)
        current = self.preview_widget.review is not None and not self.preview_widget.expired
        review = self.preview_widget.review if current else None
        self.approve_button.setEnabled(not busy and self._phase == "pending_review" and current)
        source_kind = review.get("source_kind") if isinstance(review, dict) else None
        self.deny_button.setEnabled(
            not busy and self._phase == "pending_review" and current
            and (source_kind == "fresh_learning"
                 or self._agent_review_source_kind in {"fresh_learning", "reviewed_learning"})
        )
        semantic_action = _review_semantic_action(review) if current else None
        executable = current and semantic_action in REVIEWED_SINGLE_STEP_ACTIONS
        if executable and semantic_action == "fill_field":
            executable = (
                "text_field_expectation_ref" in review["preview"]
                and "text_field_local" in review
            )
        self.execute_button.setEnabled(not busy and self._phase == "approved" and executable)
        self.cancel_button.setEnabled(not busy and self._has_owner)
        self.close_button.setEnabled(not busy)
        self.stop_wait_button.setEnabled(busy and self._operation in {"prepare", "review", "approve", "execute", "window_confirm"})
        self.approve_button.setText("批准校验中…" if busy and self._operation == "approve" else "批准本次预检")
        self.execute_button.setText("执行准备中…" if busy and self._operation == "execute" else "执行这一步…")

    def _tick(self):
        if not self._jobs:
            self._load_model_residency_settings()
        if self.preview_widget.review is not None and self._phase in {"pending_review", "approved"} and self.preview_widget.expired and not self._jobs:
            self.status_label.setText("本次预检已过期。请取消并重新预检；不能批准或执行旧截图。")
        self._update_controls()

    def _launch(self, operation, callback):
        if self._jobs:
            return
        self._operation = operation
        self._request_id += 1
        job = make_job(self._request_id, lambda: _safe_operation(callback), self)
        self._jobs.add(job)
        job.succeeded.connect(self._job_result)
        job.failed.connect(self._job_failed)
        job.finished.connect(lambda: self._finished_job.emit(job))
        job.finished.connect(job.deleteLater)
        if operation in {"prepare", "review", "approve", "execute"}:
            self.status_label.setText(self._handoff_message(operation))
        else:
            if operation == "inventory":
                self.status_label.setText("正在刷新…")
            elif operation == "environment":
                self.status_label.setText("正在检查运行环境元数据；不会创建 Runtime、检查窗口或执行动作。")
            elif operation == "model_residency_set":
                self.status_label.setText("正在更新模型驻留设置；关闭时会后台释放模型，不会启动新模型或执行动作。")
            elif operation in {"model_residency_release", "model_residency_close"}:
                self.status_label.setText("正在后台核验并释放驻留模型；完成前保留窗口，不关闭外部服务。")
            else:
                self.status_label.setText("正在核验并释放本次 Runtime；失败时会保留目标。")
        self._update_controls()
        job.start()

    def _handoff_message(self, operation):
        """使用已校验的目标身份提示切窗，不触发聚焦或增加执行权限。"""
        review = self.preview_widget.review
        window = self.window_selector.currentData()
        target = "已选定的目标窗口"
        if review is not None:
            handle, process_id = _review_target_identity(review)
            target = f"HWND {handle} / PID {process_id}"
            if (isinstance(window, dict) and window.get("handle") == handle
                    and window.get("process_id") == process_id):
                target = f"{window['title']}（{target}）"
            elif review.get("source_kind") == "fresh_learning":
                application = review["preview"]["observation_evidence"]["application"]
                name = (application["executable_path"].replace("\\", "/").rsplit("/", 1)[-1]
                        if application.get("kind") == "native" else application.get("canonical_origin", ""))
                if name:
                    target = f"{name}（{target}）"
        elif isinstance(window, dict):
            target = f"{window['title']}（HWND {window['handle']} / PID {window['process_id']}）"
        phase = {"prepare": "预检准备中", "review": "定位校验中",
                 "approve": "批准校验中：还未完成批准，不会点击", "execute": "执行准备中：尚无执行回执"}[operation]
        next_step = ("校验完成后，请返回此窗口再点“执行这一步…”；确认后还需再次切回目标。"
                     if operation == "approve" else "请保持目标在前台，等待本次结果；不要重复点执行，不会自动继续下一步。")
        return f"{phase}\n请按 Alt+Tab 切到：{target}。不要点击目标内容。\n{next_step} 可点“停止等待/识别请求”取消等待。"

    def _refresh(self):
        if self.refresh_button.isEnabled():
            self._clear_window_preparation()
            self._launch("inventory", self.coordinator.inventory)

    def _open_history(self):
        if self.history_button.isEnabled():
            from .grounded_history_dialog import GroundedHistoryDialog

            self._history_dialog = GroundedHistoryDialog(self.coordinator, self)
            self._history_dialog.exec()

    def _check_environment(self):
        if self.environment_button.isEnabled():
            self._launch("environment", self.coordinator.environment)

    def _prepare(self):
        if not self.prepare_button.isEnabled():
            return
        if not (self._phase == "prepare_recovery_required" and self._retry_preparation):
            asset, window = self.asset_selector.currentData(), self.window_selector.currentData()
            self._selection = {"asset_id": asset["asset_id"], "asset_content_sha256": asset["content_sha256"],
                               "target_window_handle": window["handle"], "target_process_id": window["process_id"]}
        selection = deepcopy(self._selection)
        self._clear_window_preparation()
        self._retry_preparation = False
        self._has_owner = True
        self._launch("prepare", lambda: self.coordinator.prepare(**selection))

    def _preview_launch_window(self):
        self._preview_window_preparation("launch")

    def _preview_focus_window(self):
        self._preview_window_preparation("focus")

    def _preview_window_preparation(self, mode):
        asset = self.asset_selector.currentData()
        window = self.window_selector.currentData()
        if mode == "focus" and not isinstance(asset, dict) and isinstance(window, dict):
            preview = getattr(self.coordinator, "preview_selected_window_preparation", None)
            if callable(preview):
                kwargs = {"target_window_handle": window["handle"], "target_process_id": window["process_id"]}
                self._launch("window_preview", lambda: preview(**kwargs))
            return
        if not isinstance(asset, dict) or (mode == "focus" and not isinstance(window, dict)):
            return
        kwargs = {"mode": mode, "asset_id": asset["asset_id"], "asset_content_sha256": asset["content_sha256"]}
        if mode == "focus":
            kwargs.update(target_window_handle=window["handle"], target_process_id=window["process_id"])
        self._launch("window_preview", lambda: self.coordinator.preview_window_preparation(**kwargs))

    def _clear_window_preparation(self):
        self._queued_followup = None
        self._window_preparation = None
        clear = getattr(self.coordinator, "clear_window_preparation", None)
        if callable(clear):
            clear()

    def _request_review(self):
        if self.review_button.isEnabled():
            self._selected_action = deepcopy(self.action_selector.currentData())
            if self._selected_action["semantic_action"] == "fill_field":
                self._launch("text_requirements", lambda: self.coordinator.text_input_requirements(action_id=self._selected_action["action_id"]))
            else:
                self._launch("review", lambda: self.coordinator.request_review(action_id=self._selected_action["action_id"]))

    def _read_fresh_review(self):
        if self.fresh_review_button.isEnabled():
            self._has_owner = True
            self._launch("agent_review", self.coordinator.current_agent_review)

    def _open_text_input(self):
        parameters = self._pending_text_parameters
        self._pending_text_parameters = None
        if parameters is None or self._phase != "observed":
            return
        editor = TextInputDialog(parameters, self)
        self._text_input_dialog = editor
        editor.accepted.connect(lambda: self._submit_text_input(editor))
        editor.finished.connect(self._text_input_closed)
        editor.open()
        self._update_controls()

    def _submit_text_input(self, editor):
        if self._phase != "observed" or self._jobs:
            return
        values = editor.text_values
        action_id = self._selected_action["action_id"]
        self._launch("review", lambda: self.coordinator.request_review(action_id=action_id, text_values=values))

    def _text_input_closed(self, _result):
        editor = self._text_input_dialog
        self._text_input_dialog = None
        if editor is not None:
            editor.deleteLater()
        self._update_controls()

    def _approve(self):
        if self.approve_button.isEnabled() and not self.preview_widget.expired:
            view = self.preview_widget.review
            if view.get("source_kind") == "fresh_learning":
                self._launch("approve", lambda: self.coordinator.approve(
                    confirmation_id=view["confirmation_id"], preview_sha256=view["preview"]["preview_sha256"]))
            else:
                self._launch("approve", lambda: self.coordinator.approve(
                    confirmation_id=view["confirmation_id"], preview_content_sha256=view["preview"]["content_sha256"]))

    def _deny(self):
        if self.deny_button.isEnabled() and not self.preview_widget.expired:
            view = self.preview_widget.review
            if view.get("source_kind") == "fresh_learning":
                self._launch("deny", lambda: self.coordinator.deny(
                    confirmation_id=view["confirmation_id"], preview_sha256=view["preview"]["preview_sha256"]))
            else:
                self._launch("deny", lambda: self.coordinator.deny(
                    confirmation_id=view["confirmation_id"],
                    preview_content_sha256=view["preview"]["content_sha256"]))

    def _execute(self):
        if not self.execute_button.isEnabled() or self.preview_widget.expired:
            return
        view = self.preview_widget.review
        preview = view["preview"]
        target_window_handle, target_process_id = _review_target_identity(view)
        semantic_action = _review_semantic_action(view)
        answer = QMessageBox.question(
            self, "确认执行这一步", f"将对 HWND {target_window_handle} / PID {target_process_id} 执行："
            f"{semantic_action}。\n\n确认后请手动切换到该窗口。仍须通过新截图、Gate 和执行后验证；不会自动执行下一步。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes and not self.preview_widget.expired:
            self._launch("execute", lambda: self.coordinator.execute(confirmation_id=view["confirmation_id"]))

    def _cancel(self):
        if not self._jobs and self._has_owner:
            self._launch("cancel", self.coordinator.cancel)

    def _stop_wait(self):
        if self.stop_wait_button.isEnabled():
            result = _safe_operation(self.coordinator.cancel_waiting)
            if isinstance(result, _JobFailure):
                self.status_label.setText("取消等待请求失败；请等待当前操作返回，窗口仍保留。")
            else:
                self.status_label.setText("已请求停止当前等待。若程序已启动，不会自动关闭或撤销该效果；请等待窗口准备调用返回。")

    def _job_result(self, request_id, result):
        if request_id != self._request_id:
            return
        if isinstance(result, _JobFailure):
            self._failure(result.code, result.result_unknown, result.retry_preparation, result.computation_stopped)
            return
        try:
            operation = self._operation
            if operation == "inventory":
                self._load_inventory(result)
            elif operation in {"model_residency_set", "model_residency_release", "model_residency_close"}:
                self._load_model_residency_result(result)
            elif operation == "environment":
                self._load_environment(result)
            elif operation == "prepare":
                self._load_observed(result)
            elif operation == "window_preview":
                if not isinstance(result, dict) or result.get("contract_version") != "native_window_preparation_v1":
                    raise ValueError("invalid window preparation")
                self._window_preparation = deepcopy(result)
                answer = self._confirm_window_preparation_dialog(result)
                if answer == QMessageBox.StandardButton.Yes:
                    preparation_id = result["preparation_id"]
                    self._queued_followup = ("window_confirm", lambda: self.coordinator.confirm_window_preparation(preparation_id))
                else:
                    self._clear_window_preparation()
                    self.status_label.setText("已取消窗口准备；未启动或聚焦目标。")
            elif operation == "window_confirm":
                if not isinstance(result, dict) or result.get("status") not in {"focused", "launched_window_ready", "launched_window_unavailable"}:
                    raise ValueError("invalid window preparation outcome")
                self.receipt_text.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
                if result["status"] == "launched_window_unavailable":
                    self._clear_window_preparation()
                    self.status_label.setText("程序启动结果未能核验窗口就绪；未开始模型、审核或输入。请查看回执中的原因和进程号。")
                elif self._window_preparation.get("source") == "selected_window":
                    self._clear_window_preparation()
                    self.status_label.setText("选定窗口已恢复/聚焦，不需要已有流程。现在可让 Agent 重新截图学习；仍会检查窗口身份与遮挡，未启动模型或执行动作。")
                else:
                    self._clear_window_preparation()
                    self.status_label.setText("窗口准备已核验。请刷新并明确选择窗口后，再执行预检；不会自动启动模型或审核。")
                    self._queued_followup = ("inventory", self.coordinator.inventory)
            elif operation == "text_requirements":
                if type(result) is not ReviewedTextParameters:
                    raise ValueError("invalid local text declaration")
                self._pending_text_parameters = result
            elif operation == "agent_review":
                self._load_agent_review(result)
            elif operation in {"review", "approve"}:
                if isinstance(result, dict) and result.get("source_kind") == "fresh_learning":
                    self._load_fresh_review(result)
                else:
                    self._load_review(result, approved=operation == "approve")
            elif operation == "deny":
                if not isinstance(result, dict) or result.get("phase") != "denied":
                    raise ValueError("fresh denial was not recorded")
                self._phase = "observed"
                self.status_label.setText("已拒绝 Agent 动作，未执行。请释放本次目标后再开始新的预检。")
            elif operation == "execute":
                view = self.preview_widget.review
                checked = validate_single_step_response(result, confirmation_id=view["confirmation_id"])
                self.receipt_text.setPlainText(json.dumps(checked, ensure_ascii=False, indent=2))
                self._phase = "completed" if checked["kind"] == "receipt" or checked["payload"]["status"] == "REJECTED" else "recovery_required"
                self.status_label.setText("本次请求已返回，未自动继续。请查看回执；继续前需释放本次目标并重新预检。")
            elif operation == "cancel":
                if (not isinstance(result, dict)
                        or set(result) not in ({"phase", "cleanup_verified"}, {"phase", "cleanup_verified", "model_residency"})
                        or result["phase"] != "idle" or result["cleanup_verified"] is not True):
                    raise ValueError("cleanup unverified")
                if "model_residency" in result:
                    enabled, count = self._checked_model_residency_settings(result["model_residency"])
                    self._keep_models_loaded, self._resident_model_count = enabled, count
                    self._model_residency_known = True
                    self._render_model_residency_settings()
                self._phase = "idle"
                self._has_owner = False
                self._agent_review_source_kind = None
                self._retry_preparation = False
                self._selection = self._session_id = self._selected_action = None
                self.preview_widget.clear()
                self.action_selector.clear()
                self.status_label.setText("本次目标已核验释放。下一次仍需重新选择和预检。")
                if "model_residency" in result and self._resident_model_count:
                    self.status_label.setText(
                        f"本次目标已核验释放，模型仍驻留 {self._resident_model_count} 个；"
                        "可继续复用或释放模型，下一次仍需重新选择和预检。"
                    )
                self.asset_selector.setCurrentIndex(-1)
                self.window_selector.setCurrentIndex(-1)
            else:
                raise ValueError("unexpected operation")
        except (KeyError, TypeError, ValueError, RecursionError, AttributeError, NativeSingleStepError):
            if self._operation in {"model_residency_set", "model_residency_release", "model_residency_close"}:
                code = "invalid_native_model_residency_response"
            else:
                code = "invalid_native_environment_response" if self._operation == "environment" else "invalid_native_review_response"
            self._failure(code, self._operation == "execute")

    def _load_inventory(self, result):
        if not isinstance(result, dict) or set(result) != {"assets", "windows"} or not all(isinstance(result[key], list) for key in result):
            raise ValueError("invalid inventory")
        assets, windows = deepcopy(result["assets"]), deepcopy(result["windows"])
        asset_ids, window_ids = set(), set()
        for asset in assets:
            if (not isinstance(asset, dict) or set(asset) != {"asset_id", "content_sha256", "application", "display_name"}
                    or not all(isinstance(asset[key], str) and asset[key] for key in ("asset_id", "content_sha256", "display_name"))
                    or re.fullmatch("[0-9a-f]{64}", asset["content_sha256"]) is None or asset["asset_id"] in asset_ids):
                raise ValueError("invalid asset")
            asset_ids.add(asset["asset_id"])
        for window in windows:
            if (not isinstance(window, dict) or set(window) != {"handle", "process_id", "title", "process_name"}
                    or not all(type(window[key]) is int and window[key] > 0 for key in ("handle", "process_id"))
                    or not all(isinstance(window[key], str) for key in ("title", "process_name")) or window["handle"] in window_ids):
                raise ValueError("invalid window")
            window_ids.add(window["handle"])
        self.asset_selector.clear()
        self.window_selector.clear()
        for asset in assets:
            self.asset_selector.addItem(asset["display_name"], asset)
        for window in windows:
            self.window_selector.addItem(f"{window['title']} · {window['handle']} / {window['process_id']}", window)
        self.asset_selector.setCurrentIndex(-1)
        self.window_selector.setCurrentIndex(-1)
        self.status_label.setText(f"发现 {len(assets)} 个已发布流程、{len(windows)} 个窗口。请明确选择目标。")

    def _load_environment(self, result):
        required = {
            "contract_version", "profile", "status", "missing_modules", "probe_errors", "checks",
            "missing_distributions", "required_python", "limitations",
            "runtime_verified", "imports_exercised", "model_assets_checked", "artifact_is_authorization",
            "interpreter", "python_version", "platform", "python_supported", "platform_supported",
        }
        if (
            not isinstance(result, dict) or set(result) not in (required, required | {"vision_configuration"})
            or result["contract_version"] != "native_environment_metadata_v1"
            or result["profile"] != "all"
            or result["status"] not in {"blocked", "metadata_present_unverified"}
            or not all(isinstance(result[key], list) for key in ("missing_modules", "missing_distributions", "probe_errors", "checks", "limitations"))
            or not all(isinstance(item, str) for item in result["missing_modules"])
            or not all(isinstance(item, str) for item in result["missing_distributions"])
            or not all(isinstance(item, str) for item in result["limitations"])
            or not all(isinstance(item, dict) for key in ("probe_errors", "checks") for item in result[key])
            or not all(result[key] is False for key in ("runtime_verified", "imports_exercised", "model_assets_checked", "artifact_is_authorization"))
            or not all(isinstance(result[key], str) for key in ("interpreter", "python_version", "platform", "required_python"))
            or not all(type(result[key]) is bool for key in ("python_supported", "platform_supported"))
        ):
            raise ValueError("invalid environment")
        if "vision_configuration" in result:
            configuration = result["vision_configuration"]
            common = {"config_path", "status", "runtime_verified", "model_assets_checked", "service_contacted"}
            if (not isinstance(configuration, dict)
                    or configuration.get("status") not in {"configured_unverified", "blocked"}
                    or set(configuration) != common | ({"mode"} if configuration.get("status") == "configured_unverified" else {"reason_code"})
                    or not isinstance(configuration.get("config_path"), str)
                    or not configuration["config_path"]
                    or not all(configuration.get(key) is False for key in ("runtime_verified", "model_assets_checked", "service_contacted"))
                    or (configuration["status"] == "configured_unverified" and configuration["mode"] not in {"local", "local_understanding", "local_grounding"})
                    or (configuration["status"] == "blocked" and configuration["reason_code"] not in {
                        "vision_config_missing", "vision_config_invalid", "vision_provider_not_configured",
                        "vision_provider_unimplemented", "vision_provider_unsupported"})):
                raise ValueError("invalid vision configuration report")
        report = deepcopy(result)
        self.environment_report.setPlainText(
            "运行环境与模型配置报告（只读）\n"
            "结论：仅检查安装元数据与配置，不证明真实 Runtime、模型资源、服务或窗口已就绪；不构成授权。\n\n"
            + json.dumps(report, ensure_ascii=False, indent=2)
        )
        status = "缺少元数据依赖" if result["status"] == "blocked" else "元数据存在，尚未验证"
        self.status_label.setText(f"运行环境检查完成：{status}。未创建 Runtime、未枚举窗口、未改变本次目标。")

    def _load_observed(self, result):
        required = {"phase", "session_id", "actions"}
        if (not isinstance(result, dict) or set(result) not in (required, required | {"diagnostic"}) or result["phase"] != "observed"
                or not isinstance(result["session_id"], str) or not result["session_id"] or not isinstance(result["actions"], list)):
            raise ValueError("invalid observation")
        diagnostic = result.get("diagnostic")
        seen = set()
        for action in result["actions"]:
            if (not isinstance(action, dict) or set(action) != {"action_id", "semantic_action", "target"}
                    or not all(isinstance(value, str) and value for value in action.values()) or action["action_id"] in seen):
                raise ValueError("invalid action")
            seen.add(action["action_id"])
        self._session_id = result["session_id"]
        self.action_selector.clear()
        for action in result["actions"]:
            self.action_selector.addItem(f"{action['semantic_action']} → {action['target']}", deepcopy(action))
        self.action_selector.setCurrentIndex(-1)
        self._phase = "observed"
        self._retry_preparation = False
        if seen:
            self.status_label.setText("已预检，请选择服务器提供的动作并生成定位预览。")
            return
        diagnostic = _normalize_preflight_diagnostic(diagnostic)
        self.receipt_text.setPlainText("预检诊断（只读，不构成执行授权）\n" + json.dumps(diagnostic, ensure_ascii=False, indent=2))
        if diagnostic["status"] == "available":
            reason_code = diagnostic["safe_stop_reason_code"]
            detail = _safe_stop_reason_text(reason_code)
            state = diagnostic["state_status"]
            state_id = diagnostic["state_id"] or "无"
            self.status_label.setText(f"当前没有可执行动作：{detail}（{reason_code}）。状态：{state} / {state_id}。请释放目标，检查流程资产或界面状态。")
        else:
            reason_code = diagnostic["unavailable_reason_code"]
            self.status_label.setText(f"当前没有可执行动作，预检诊断不可用（{reason_code}）。请释放目标，检查流程资产或界面状态。")

    def _load_fresh_review(self, result):
        checked, _image = validate_review_view(result)
        if checked.get("source_kind") != "fresh_learning":
            raise ValueError("not a fresh review")
        self.preview_widget.set_review(checked)
        self._phase = checked["phase"]
        self._session_id = checked["preview"]["session_id"]
        self._has_owner = True
        self._agent_review_source_kind = "fresh_learning"
        self.status_label.setText(
            "请核对 Agent 提议的原图、动作和窗口身份；批准后仍须独立确认才会执行。"
            if self._phase == "pending_review" else "Agent 动作已批准，尚未执行；点击“执行这一步”仍需独立确认。"
        )
        self._tick()

    def _load_agent_review(self, result):
        if isinstance(result, dict) and result.get("source_kind") == "fresh_learning":
            self._load_fresh_review(result)
            return
        if not isinstance(result, dict) or result.get("source_kind") != "reviewed_learning":
            raise ValueError("unsupported Agent review source")
        self._agent_review_source_kind = "reviewed_learning"
        reviewed = deepcopy(result)
        reviewed.pop("source_kind")
        checked, _image = validate_review_view(reviewed)
        preview = checked["preview"]
        grounding = preview["grounding_preview"]
        self._selection = {
            "asset_id": preview["workflow"]["asset_id"],
            "asset_content_sha256": preview["workflow"]["asset_content_sha256"],
            "target_window_handle": preview["target_window_handle"],
            "target_process_id": preview["target_process_id"],
        }
        self._selected_action = {
            "action_id": grounding["transition_id"],
            "semantic_action": grounding["semantic_action"],
        }
        self._session_id = preview["session_id"]
        if checked["phase"] == "approved":
            pending = deepcopy(checked)
            pending["phase"] = "pending_review"
            self.preview_widget.set_review(pending)
        self._load_review(checked, approved=checked["phase"] == "approved")
        self._has_owner = True
        self._tick()

    def _load_review(self, result, *, approved):
        checked, _image = validate_review_view(result)
        preview = checked["preview"]
        ground = preview["grounding_preview"]
        if (checked["phase"] != ("approved" if approved else "pending_review") or preview["session_id"] != self._session_id
                or any(preview[key] != self._selection[key] for key in ("target_window_handle", "target_process_id"))
                or any(preview["workflow"][key] != self._selection[key] for key in ("asset_id", "asset_content_sha256"))
                or ground["transition_id"] != self._selected_action["action_id"]
                or ground["semantic_action"] != self._selected_action["semantic_action"]):
            raise ValueError("review selection mismatch")
        previous = self.preview_widget.review
        if approved and (previous is None or {**checked, "phase": "pending_review"} != previous):
            raise ValueError("approval binding mismatch")
        self.preview_widget.set_review(checked)
        self._phase = checked["phase"]
        self.status_label.setText("本次预检已批准，尚未执行。点击“执行这一步”仍需独立确认。" if approved else "请检查截图、识别框、点击点、动作与窗口身份；确认正确后才批准。")
        if ground["semantic_action"] == "fill_field":
            self.status_label.setText(
                "本次填写已批准，尚未执行。请核对目标字段、原值、预计最终内容和写入方式；"
                "点击“执行这一步”仍需独立确认。"
                if approved
                else "请核对目标字段、原值、预计最终内容及写入方式；批准后仍须独立确认才会执行这一步。"
            )
        self._tick()

    def _failure(self, code, unknown=False, retry_preparation=False, computation_stopped=False):
        if self._operation in {"model_residency_set", "model_residency_release", "model_residency_close"}:
            self._model_residency_failure(code)
            return
        if self._operation == "window_confirm":
            self._clear_window_preparation()
        self._pending_text_parameters = None
        self._retry_preparation = (
            retry_preparation is True and self._operation == "prepare"
            and self._has_owner and self._selection is not None and self._session_id is None
        )
        self._phase = "prepare_recovery_required" if self._retry_preparation else ("recovery_required" if self._has_owner else "idle")
        self._close_requested = False
        if code == "runtime_dependencies_missing":
            detail = "运行环境依赖元数据缺失或不兼容。请在受支持的 Python/平台环境中安装或修复所需依赖；不会据此释放当前目标。"
        elif code == "safety_mode_change_unavailable":
            detail = "当前步骤尚未结束，请先取消当前步骤，再切换自动安全拦截。未批准或执行动作。"
        elif code == "safety_observation_mode_unsupported":
            detail = "旧已发布流程的调试入口仍需开启自动安全拦截；关闭模式请使用 Agent 新学习/界面复用单步。未启动模型或执行动作。"
        elif code in {"vision_config_missing", "vision_config_invalid", "vision_provider_not_configured",
                      "vision_provider_unimplemented", "vision_provider_unsupported"}:
            detail = "模型配置不可用或所选提供器尚未实现。请核验释放后，在运行环境报告中查看配置路径并修正配置；不会创建占位文件或自动切换模型。"
        elif self._operation == "prepare":
            detail = "预检未完成，尚未执行动作。" + ("可明确重试原目标预检，或取消并核验释放；不会自动重试。" if self._retry_preparation else "保留当前目标，请先核验释放。")
        elif unknown and self._operation == "execute":
            detail = "执行结果未知，禁止自动重试；保留当前 owner 等待核验。"
        else:
            detail = "未自动继续；如已持有目标，请先核验释放。"
        if code == "model_request_cancelled":
            detail = ("识别请求已取消，已确认本次请求不再活动。" if computation_stopped is True
                      else "识别请求已取消，服务端计算未确认停止。") + detail
        self.status_label.setText(f"操作失败（{code}）。" + detail)

    def _job_failed(self, request_id, _private_traceback):
        if request_id == self._request_id:
            self._failure("native_worker_failed", self._operation == "execute")

    def _job_finished(self, job):
        self._jobs.discard(job)
        if not self._jobs:
            self._operation = None
            self._tick()
            if self._pending_text_parameters is not None:
                self._open_text_input()
            if self._close_requested and not self._has_owner:
                if self._model_close_cleanup_verified or not self._model_residency_supported:
                    self._closing_verified = True
                    self.accept()
                else:
                    self.close()
            if self._queued_followup is not None:
                self._followup_timer.start(0)

    def _start_queued_followup(self):
        if self._jobs or self._queued_followup is None or self._close_requested:
            return
        operation, callback = self._queued_followup
        self._queued_followup = None
        self._launch(operation, callback)

    def _confirm_window_preparation_dialog(self, result):
        identity = result.get("identity") if isinstance(result.get("identity"), dict) else {}
        source = (f"首次学习 / 独立窗口：{result.get('title', '')}\n不需要已有流程。\n"
                  if result.get("source") == "selected_window" else
                  f"流程：{result.get('asset_id')}\n版本：{result.get('asset_content_sha256')}\n")
        details = (
            f"模式：{result.get('mode')}\n{source}"
            f"程序：{result.get('executable_path')}\nHWND：{identity.get('target_window_handle', '无')}\n"
            f"PID：{identity.get('process_id', '无')}\n创建时间：{identity.get('process_create_time', '无')}\n\n"
            "确认后只执行本次窗口准备，不会启动模型、审核、输入或执行流程动作。"
            "之后的截图仍须重新检查窗口身份与遮挡；聚焦成功不代表页面已加载。"
        )
        box = QMessageBox(QMessageBox.Icon.Question, "确认窗口准备", details,
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return QMessageBox.StandardButton(box.exec())

    def closeEvent(self, event):
        self._followup_timer.stop()
        self._queued_followup = None
        if self._jobs:
            self.status_label.setText("后台操作尚未结束，窗口和 Runtime owner 会保留。可请求停止等待或受管本地识别请求，完成前不会释放拥有者。")
            event.ignore()
        elif self._has_owner:
            self._close_requested = True
            self._cancel()
            event.ignore()
        elif not self._model_close_cleanup_verified and self._model_residency_supported:
            releaser = getattr(self.coordinator, "release_resident_models", None)
            if callable(releaser):
                self._close_requested = True
                self._launch("model_residency_close", releaser)
            else:
                self.status_label.setText("当前连接不支持释放驻留模型，无法核验关闭清理；窗口仍保留。")
            event.ignore()
        else:
            self._closing_verified = True
            event.accept()

    def reject(self):
        if self._closing_verified or (not self._jobs and not self._has_owner and not self._model_residency_supported):
            super().reject()
        else:
            self.close()

    def done(self, result):
        if self._closing_verified or (not self._jobs and not self._has_owner and not self._model_residency_supported):
            super().done(result)
        else:
            self.close()


def _review_semantic_action(review):
    preview = review["preview"]
    if review.get("source_kind") == "fresh_learning":
        return preview["intent"]["semantic_action"]
    return preview["grounding_preview"]["semantic_action"]


def _review_target_identity(review):
    preview = review["preview"]
    if review.get("source_kind") == "fresh_learning":
        target = preview["observation_evidence"]["target"]
        return target["window_handle"], target["process_id"]
    return preview["target_window_handle"], preview["target_process_id"]


def _normalize_preflight_diagnostic(value):
    unavailable = {
        "contract_version": "native_preflight_diagnostic_v1",
        "status": "unavailable",
        "unavailable_reason_code": "observation_diagnostic_fields_unavailable",
        "artifact_is_authorization": False,
    }
    if value is None:
        return unavailable
    if not isinstance(value, dict) or value.get("contract_version") != unavailable["contract_version"] or value.get("artifact_is_authorization") is not False:
        raise ValueError("invalid preflight diagnostic")
    if value.get("status") == "unavailable" and value == unavailable:
        return unavailable
    available = {"contract_version", "status", "safe_stop_reason_code", "state_status", "state_id", "capture_id", "blockers", "artifact_is_authorization"}
    if (
        set(value) != available
        or value.get("status") != "available"
        or not all(isinstance(value.get(key), str) and value[key] for key in ("safe_stop_reason_code", "state_status", "capture_id"))
        or not (isinstance(value.get("state_id"), str) or value.get("state_id") is None)
        or not isinstance(value.get("blockers"), list)
    ):
        raise ValueError("invalid preflight diagnostic")
    for blocker in value["blockers"]:
        if (not isinstance(blocker, dict) or set(blocker) != {"reason_code", "description"}
                or not all(isinstance(blocker.get(key), str) and blocker[key] for key in blocker)):
            raise ValueError("invalid preflight diagnostic")
    return deepcopy(value)


def _safe_stop_reason_text(reason_code):
    return {
        "state_ambiguous": "当前界面状态存在歧义",
        "state_unknown": "无法确认当前界面状态",
        "stop_boundary": "已到达审核流程的停止边界",
        "no_available_action": "当前状态没有审核通过的可用动作",
        "policy_blocked": "当前动作被安全策略阻止",
        "human_review_required": "当前状态需要人工审核",
    }.get(reason_code, "Runtime 要求安全停止")
