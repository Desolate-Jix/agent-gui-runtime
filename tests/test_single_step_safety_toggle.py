"""单步安全开关的离屏行为；不创建 Runtime，也不批准或执行动作。"""
from __future__ import annotations

from copy import deepcopy

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

from app.desktop_review.single_step_dialog import SingleStepDialog
from app.desktop_review.window import ensure_application


def _settings(enabled=True):
    return {"automatic_safety_interception": enabled,
            "scope": "automatic_risk_policy", "session_only": True}


class _Coordinator:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.calls = []
        self.read_error = False
        self.set_error = False
        self.change_before_error = False
        self.invalid_set_result = False
        self.error_code = None

    def safety_settings(self):
        self.calls.append("read")
        if self.read_error:
            raise RuntimeError("private diagnostic must not enter UI")
        return _settings(self.enabled)

    def set_automatic_safety_interception(self, enabled):
        self.calls.append(("set", enabled))
        assert type(enabled) is bool
        if self.set_error:
            if self.change_before_error:
                self.enabled = enabled
            error = RuntimeError("private diagnostic must not enter UI")
            error.code = self.error_code
            raise error
        self.enabled = enabled
        return {**_settings(enabled), "scope": "all_checks"} if self.invalid_set_result else _settings(enabled)

    def approve(self, **kwargs):
        pytest.fail("changing settings must not approve")

    def execute(self, **kwargs):
        pytest.fail("changing settings must not execute")


@pytest.fixture
def dialog_factory():
    application = ensure_application()
    dialogs = []

    def make(coordinator):
        dialog = SingleStepDialog(coordinator)
        dialog._timer.stop()
        dialogs.append(dialog)
        return dialog

    yield make
    for dialog in dialogs:
        dialog._jobs.clear()
        dialog._has_owner = False
        dialog._window_preparation = None
        dialog._phase = "idle"
        dialog._followup_timer.stop()
        dialog.close()
        dialog.deleteLater()
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_default_enabled_is_read_without_mutating_or_approving(dialog_factory):
    coordinator = _Coordinator()
    dialog = dialog_factory(coordinator)
    assert dialog.safety_checkbox.text() == "自动安全拦截"
    assert dialog.safety_checkbox.isChecked()
    assert dialog.safety_checkbox.isEnabled()
    assert dialog.safety_status_label.text() == "自动拦截已开启"
    assert coordinator.calls == ["read"]
    boundary = dialog.safety_boundary_label.text()
    assert all(text in boundary for text in ("关闭不是批准", "单步确认", "请求身份", "数据完整性", "支持动作类型"))
    assert "像素" not in boundary
    assert "旧已发布流程的调试入口仍需开启" in boundary
    assert "Agent 新学习/界面复用单步" in boundary
    assert not dialog.approve_button.isEnabled()
    assert not dialog.execute_button.isEnabled()


def test_toggle_changes_only_setting_and_shows_prominent_warning(dialog_factory):
    coordinator = _Coordinator()
    dialog = dialog_factory(coordinator)
    dialog.safety_checkbox.click()
    assert coordinator.calls == ["read", ("set", False)]
    assert dialog.safety_checkbox.isChecked() is False
    assert dialog.safety_status_label.text() == "自动拦截已关闭：本地无学习单步免一次性授权，仍检查目标与截图并记录结果。已有学习步骤保留原确认流程。"
    assert "font-weight" in dialog.safety_status_label.styleSheet()
    assert dialog._phase == "idle" and not dialog._jobs and not dialog._has_owner
    assert not dialog.approve_button.isEnabled() and not dialog.execute_button.isEnabled()
    dialog.safety_checkbox.click()
    assert coordinator.calls[-1] == ("set", True)
    assert dialog.safety_checkbox.isChecked()
    assert dialog.safety_status_label.text() == "自动拦截已开启"


def test_existing_session_setting_is_displayed_without_reset(dialog_factory):
    coordinator = _Coordinator(False)
    dialog = dialog_factory(coordinator)
    assert not dialog.safety_checkbox.isChecked()
    assert dialog.safety_status_label.text().startswith("自动拦截已关闭")
    assert coordinator.calls == ["read"]


def test_warning_and_boundary_render_inside_minimum_dialog_size(dialog_factory):
    dialog = dialog_factory(_Coordinator(False))
    dialog.resize(1000, 650)
    dialog.show()
    ensure_application().processEvents()
    assert not dialog.grab().isNull()
    for widget in (dialog.safety_checkbox, dialog.safety_status_label, dialog.safety_boundary_label):
        assert widget.isVisible()
        top_left = widget.mapTo(dialog, widget.rect().topLeft())
        bottom_right = widget.mapTo(dialog, widget.rect().bottomRight())
        assert 0 <= top_left.x() <= bottom_right.x() < dialog.width()
        assert 0 <= top_left.y() <= bottom_right.y() < dialog.height()
    for label in (dialog.safety_status_label, dialog.safety_boundary_label):
        assert label.height() >= label.heightForWidth(label.width())


@pytest.mark.parametrize("state", ["busy", "pending_review", "approved", "observed", "owner", "window_preparation"])
def test_only_selecting_state_can_change_setting(dialog_factory, state):
    coordinator = _Coordinator()
    dialog = dialog_factory(coordinator)
    if state == "busy":
        dialog._jobs.add(object())
    elif state == "owner":
        dialog._has_owner = True
    elif state == "window_preparation":
        dialog._window_preparation = {}
    else:
        dialog._phase = state
    dialog._update_controls()
    assert not dialog.safety_checkbox.isEnabled()
    dialog.safety_checkbox.click()
    dialog.safety_checkbox.setChecked(False)
    assert dialog.safety_checkbox.isChecked()
    assert coordinator.calls == ["read"]
    dialog._jobs.clear()
    dialog._has_owner = False
    dialog._window_preparation = None
    dialog._phase = "idle"
    dialog._update_controls()
    assert dialog.safety_checkbox.isEnabled()


@pytest.mark.parametrize("changed", [False, True])
def test_setter_failure_reloads_actual_setting_without_approval(dialog_factory, changed):
    coordinator = _Coordinator()
    coordinator.set_error = True
    coordinator.change_before_error = changed
    dialog = dialog_factory(coordinator)
    dialog.safety_checkbox.click()
    assert coordinator.calls == ["read", ("set", False), "read"]
    assert dialog.safety_checkbox.isChecked() is (not changed)
    assert dialog.safety_checkbox.isEnabled()
    assert "失败" in dialog.status_label.text()
    assert "private diagnostic" not in dialog.status_label.text()
    assert dialog._phase == "idle" and not dialog._has_owner
    assert not dialog.approve_button.isEnabled() and not dialog.execute_button.isEnabled()


def test_invalid_setter_result_is_error_and_reloads_actual_value(dialog_factory):
    coordinator = _Coordinator()
    coordinator.invalid_set_result = True
    dialog = dialog_factory(coordinator)
    dialog.safety_checkbox.click()
    assert coordinator.calls == ["read", ("set", False), "read"]
    assert not dialog.safety_checkbox.isChecked()
    assert "失败" in dialog.status_label.text()


def test_backend_busy_error_explains_cancel_before_switching(dialog_factory):
    coordinator = _Coordinator()
    coordinator.set_error = True
    coordinator.error_code = "safety_mode_change_unavailable"
    dialog = dialog_factory(coordinator)
    dialog.safety_checkbox.click()
    assert dialog.safety_checkbox.isChecked()
    assert "先取消当前步骤" in dialog.status_label.text()
    assert coordinator.calls == ["read", ("set", False), "read"]


@pytest.mark.parametrize("code, explanation", [
    ("safety_mode_change_unavailable", "先取消当前步骤"),
    ("safety_observation_mode_unsupported", "旧已发布流程的调试入口仍需开启"),
])
def test_operation_failure_explains_mode_boundaries(dialog_factory, code, explanation):
    dialog = dialog_factory(_Coordinator())
    dialog._operation = "prepare"
    dialog._failure(code)
    assert explanation in dialog.status_label.text()
    if code == "safety_observation_mode_unsupported":
        assert "Agent 新学习/界面复用单步" in dialog.status_label.text()
    assert dialog._phase == "idle" and not dialog._has_owner and not dialog._jobs


def test_setter_and_readback_failure_marks_state_unknown_and_disables_switch(dialog_factory):
    coordinator = _Coordinator()
    dialog = dialog_factory(coordinator)
    coordinator.set_error = True
    coordinator.read_error = True
    dialog.safety_checkbox.click()
    assert dialog.safety_checkbox.isChecked()
    assert not dialog.safety_checkbox.isEnabled()
    assert "未知" in dialog.safety_status_label.text()
    assert "失败" in dialog.status_label.text()
    assert "private diagnostic" not in dialog.status_label.text()


def test_legacy_coordinator_defaults_enabled_but_cannot_change_setting(dialog_factory):
    dialog = dialog_factory(object())
    assert dialog.safety_checkbox.isChecked()
    assert not dialog.safety_checkbox.isEnabled()
    assert dialog.safety_status_label.text() == "自动拦截已开启"


@pytest.mark.parametrize("invalid", [
    None, {**_settings(), "automatic_safety_interception": 1},
    {**_settings(), "scope": "all_checks"}, {**_settings(), "session_only": False},
    {**_settings(), "extra": True},
])
def test_invalid_read_settings_do_not_claim_verified_state(dialog_factory, invalid):
    coordinator = _Coordinator()
    coordinator.safety_settings = lambda: deepcopy(invalid)
    dialog = dialog_factory(coordinator)
    assert not dialog.safety_checkbox.isEnabled()
    assert "未知" in dialog.safety_status_label.text()
    assert "失败" in dialog.status_label.text()
