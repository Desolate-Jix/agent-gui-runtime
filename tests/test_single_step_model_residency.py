"""模型驻留选项的离屏契约；仅使用内存替身，不启动模型或控制桌面。"""
from __future__ import annotations

from copy import deepcopy
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QCloseEvent

from app.desktop_review.single_step_dialog import SingleStepDialog
from app.desktop_review.window import ensure_application
from tests.test_native_model_service import _coordinator, _prepare, backend


def _settings(enabled=False, count=0):
    return {"keep_models_loaded": enabled, "allow_multiple_models": enabled,
            "resident_model_count": count, "session_only": True}


def _error(code):
    error = RuntimeError("private model diagnostic must not enter UI")
    error.code = code
    return error


class _Coordinator:
    def __init__(self, enabled=False, count=0):
        self.enabled = enabled
        self.count = count
        self.calls = []
        self.worker_threads = []
        self.read_error = False
        self.set_error = None
        self.release_error = None
        self.change_before_error = False
        self.invalid_set_result = None
        self.invalid_release_result = None
        self.hold = None
        self.entered = threading.Event()

    def model_residency_settings(self):
        self.calls.append("read")
        if self.read_error:
            raise _error("model_residency_read_failed")
        return _settings(self.enabled, self.count)

    def _worker_started(self):
        self.worker_threads.append(threading.get_ident())
        self.entered.set()
        if self.hold is not None:
            assert self.hold.wait(5)

    def set_keep_models_loaded(self, enabled):
        self.calls.append(("set", enabled))
        self._worker_started()
        if self.set_error:
            if self.change_before_error:
                self.enabled = enabled
            raise _error(self.set_error)
        self.enabled = enabled
        if not enabled:
            self.count = 0
        return self.invalid_set_result or _settings(self.enabled, self.count)

    def release_resident_models(self):
        self.calls.append("release")
        self._worker_started()
        if self.release_error:
            raise _error(self.release_error)
        self.count = 0
        return self.invalid_release_result or _settings(self.enabled, self.count)

    def cancel(self):
        self.calls.append("cancel")
        self.count += 1
        return {"phase": "idle", "cleanup_verified": True}

    def approve(self, **kwargs):
        pytest.fail("model residency must not approve")

    def execute(self, **kwargs):
        pytest.fail("model residency must not execute")


def _wait(predicate):
    application = ensure_application()
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.002)
    assert predicate()


def _drain(dialog):
    _wait(lambda: not dialog._jobs and not dialog._followup_timer.isActive())


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
        hold = getattr(dialog.coordinator, "hold", None)
        if hold is not None:
            hold.set()
        if dialog._jobs:
            _drain(dialog)
        dialog._followup_timer.stop()
        dialog._closing_verified = True
        dialog.done(0)
        dialog.deleteLater()
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_default_off_reads_only_local_snapshot_and_keeps_safety_default(dialog_factory):
    coordinator = _Coordinator()
    dialog = dialog_factory(coordinator)
    assert coordinator.calls == ["read"]
    assert dialog.model_residency_checkbox.text() == "保持模型驻留（允许多模型）"
    assert not dialog.model_residency_checkbox.isChecked()
    assert dialog.model_residency_checkbox.isEnabled()
    assert "当前驻留 0 个" in dialog.model_residency_status_label.text()
    assert not dialog.release_models_button.isEnabled()
    assert dialog.safety_checkbox.isChecked()
    warning = dialog.model_residency_warning_label.text()
    assert all(value in warning for value in ("默认关闭", "仅本次会话", "不会立即启动", "内存/显存", "不关闭外部服务"))
    assert not dialog._jobs and not dialog._has_owner
    assert not dialog.approve_button.isEnabled() and not dialog.execute_button.isEnabled()


def test_enable_and_disable_are_background_jobs_and_do_not_launch_models(dialog_factory):
    coordinator = _Coordinator()
    dialog = dialog_factory(coordinator)
    main_thread = threading.get_ident()
    dialog.model_residency_checkbox.click()
    assert dialog._jobs and not dialog.model_residency_checkbox.isEnabled()
    _drain(dialog)
    assert coordinator.enabled and dialog.model_residency_checkbox.isChecked()
    assert coordinator.count == 0
    coordinator.count = 2
    dialog._tick()
    assert "当前驻留 2 个" in dialog.model_residency_status_label.text()
    assert dialog.release_models_button.isEnabled()
    dialog.model_residency_checkbox.click()
    _drain(dialog)
    assert not coordinator.enabled and coordinator.count == 0
    assert not dialog.model_residency_checkbox.isChecked()
    assert not dialog.release_models_button.isEnabled()
    assert coordinator.worker_threads and all(worker != main_thread for worker in coordinator.worker_threads)
    assert [call for call in coordinator.calls if call != "read"] == [("set", True), ("set", False)]
    assert dialog.safety_checkbox.isChecked()


def test_slow_disable_keeps_qt_responsive_and_blocks_other_actions(dialog_factory):
    coordinator = _Coordinator(True, 2)
    coordinator.hold = threading.Event()
    dialog = dialog_factory(coordinator)
    dialog.model_residency_checkbox.click()
    _wait(coordinator.entered.is_set)
    assert dialog._jobs
    assert dialog.model_residency_checkbox.isChecked()
    assert not dialog.model_residency_checkbox.isEnabled()
    assert not dialog.release_models_button.isEnabled()
    assert not dialog.safety_checkbox.isEnabled()
    assert not dialog.prepare_button.isEnabled()
    assert not dialog.close_button.isEnabled()
    event = QCloseEvent()
    dialog.closeEvent(event)
    assert not event.isAccepted() and not dialog._close_requested
    coordinator.hold.set()
    _drain(dialog)
    assert not dialog.model_residency_checkbox.isChecked()


@pytest.mark.parametrize("state", ["busy", "pending_review", "approved", "observed", "owner", "window_preparation"])
def test_setting_and_release_are_only_available_in_idle_selection(dialog_factory, state):
    coordinator = _Coordinator(True, 2)
    dialog = dialog_factory(coordinator)
    marker = object()
    if state == "busy":
        dialog._jobs.add(marker)
    elif state == "owner":
        dialog._has_owner = True
    elif state == "window_preparation":
        dialog._window_preparation = {}
    else:
        dialog._phase = state
    dialog._update_controls()
    assert not dialog.model_residency_checkbox.isEnabled()
    assert not dialog.release_models_button.isEnabled()
    dialog.model_residency_checkbox.setChecked(False)
    dialog._release_resident_models()
    assert dialog.model_residency_checkbox.isChecked()
    assert coordinator.calls == ["read"]
    dialog._jobs.discard(marker)


@pytest.mark.parametrize("changed", [False, True])
def test_setter_failure_reads_actual_value_and_does_not_toggle_back_blindly(dialog_factory, changed):
    coordinator = _Coordinator()
    coordinator.set_error = "model_residency_change_unavailable"
    coordinator.change_before_error = changed
    dialog = dialog_factory(coordinator)
    dialog.model_residency_checkbox.click()
    _drain(dialog)
    assert dialog.model_residency_checkbox.isChecked() is changed
    assert dialog.model_residency_checkbox.isEnabled()
    assert "先取消当前步骤" in dialog.status_label.text()
    assert "已回读" in dialog.status_label.text()
    assert "private model" not in dialog.status_label.text()
    assert dialog._phase == "idle" and not dialog._has_owner


def test_invalid_setter_response_is_not_reported_as_success(dialog_factory):
    coordinator = _Coordinator()
    coordinator.invalid_set_result = _settings(False, 0)
    dialog = dialog_factory(coordinator)
    dialog.model_residency_checkbox.click()
    _drain(dialog)
    assert dialog.model_residency_checkbox.isChecked()
    assert "invalid_native_model_residency_response" in dialog.status_label.text()
    assert "失败" in dialog.status_label.text()


def test_failed_setter_and_readback_mark_unknown_and_disable_mutations(dialog_factory):
    coordinator = _Coordinator()
    dialog = dialog_factory(coordinator)
    coordinator.set_error = "model_service_cleanup_pending"
    coordinator.read_error = True
    dialog.model_residency_checkbox.click()
    _drain(dialog)
    assert not dialog.model_residency_checkbox.isEnabled()
    assert not dialog.release_models_button.isEnabled()
    assert "未知" in dialog.model_residency_status_label.text()
    assert "失败" in dialog.status_label.text()
    assert "private model" not in dialog.status_label.text()


def test_release_preserves_preference_and_refreshes_count(dialog_factory):
    coordinator = _Coordinator(True, 3)
    dialog = dialog_factory(coordinator)
    dialog.release_models_button.click()
    assert dialog._jobs
    _drain(dialog)
    assert coordinator.enabled and dialog.model_residency_checkbox.isChecked()
    assert coordinator.count == 0 and "当前驻留 0 个" in dialog.model_residency_status_label.text()
    assert "偏好未更改" in dialog.status_label.text()
    assert not dialog.release_models_button.isEnabled()


def test_failed_release_retains_count_and_can_retry(dialog_factory):
    coordinator = _Coordinator(True, 2)
    coordinator.release_error = "model_service_cleanup_pending"
    dialog = dialog_factory(coordinator)
    dialog.release_models_button.click()
    _drain(dialog)
    assert "当前驻留 2 个" in dialog.model_residency_status_label.text()
    assert "可重试" in dialog.status_label.text()
    assert dialog.release_models_button.isEnabled()
    assert not dialog._closing_verified
    coordinator.release_error = None
    dialog.release_models_button.click()
    _drain(dialog)
    assert coordinator.count == 0


def test_backend_busy_release_does_not_clear_count(dialog_factory):
    coordinator = _Coordinator(True, 1)
    coordinator.release_error = "model_residency_change_unavailable"
    dialog = dialog_factory(coordinator)
    dialog.release_models_button.click()
    _drain(dialog)
    assert coordinator.count == 1
    assert dialog.release_models_button.isEnabled()
    assert "先取消当前步骤" in dialog.status_label.text()


@pytest.mark.parametrize("response", [_settings(True, 1), _settings(False, 0)])
def test_release_result_must_confirm_zero_without_changing_preference(dialog_factory, response):
    coordinator = _Coordinator(True, 2)
    coordinator.invalid_release_result = response
    dialog = dialog_factory(coordinator)
    dialog.release_models_button.click()
    _drain(dialog)
    assert "invalid_native_model_residency_response" in dialog.status_label.text()
    assert dialog.model_residency_checkbox.isChecked()


@pytest.mark.parametrize("entry", ["close", "reject", "done"])
def test_each_close_entry_releases_residents_in_background_before_finishing(dialog_factory, entry):
    coordinator = _Coordinator(True, 2)
    coordinator.hold = threading.Event()
    dialog = dialog_factory(coordinator)
    if entry == "done":
        dialog.done(0)
    else:
        getattr(dialog, entry)()
    _wait(coordinator.entered.is_set)
    assert dialog._jobs and not dialog._closing_verified
    assert coordinator.count == 2
    coordinator.hold.set()
    _drain(dialog)
    assert dialog._closing_verified and dialog._model_close_cleanup_verified
    assert coordinator.count == 0 and coordinator.enabled


def test_close_cancels_active_owner_then_releases_retained_models(dialog_factory):
    coordinator = _Coordinator(True, 1)
    dialog = dialog_factory(coordinator)
    dialog._has_owner = True
    dialog._phase = "observed"
    dialog.close()
    _drain(dialog)
    assert [call for call in coordinator.calls if call != "read"] == ["cancel", "release"]
    assert coordinator.count == 0 and dialog._closing_verified


def test_close_failure_retains_window_until_successful_retry(dialog_factory):
    coordinator = _Coordinator(True, 2)
    coordinator.release_error = "model_service_cleanup_pending"
    dialog = dialog_factory(coordinator)
    dialog.close()
    _drain(dialog)
    assert not dialog._closing_verified and not dialog._close_requested
    assert coordinator.count == 2 and "可重试" in dialog.status_label.text()
    coordinator.release_error = None
    dialog.close()
    _drain(dialog)
    assert dialog._closing_verified and coordinator.count == 0


def test_legacy_coordinator_has_explicit_unsupported_state_and_keeps_close_behavior(dialog_factory):
    dialog = dialog_factory(object())
    assert not dialog.model_residency_checkbox.isChecked()
    assert not dialog.model_residency_checkbox.isEnabled()
    assert not dialog.release_models_button.isEnabled()
    assert "不支持" in dialog.model_residency_status_label.text()
    assert dialog.safety_checkbox.isChecked()
    event = QCloseEvent()
    dialog.closeEvent(event)
    assert event.isAccepted() and dialog._closing_verified


@pytest.mark.parametrize("invalid", [
    None, {**_settings(), "keep_models_loaded": 1},
    {**_settings(), "allow_multiple_models": True},
    {**_settings(), "resident_model_count": -1},
    {**_settings(), "resident_model_count": True},
    {**_settings(), "session_only": False}, {**_settings(), "extra": True},
])
def test_invalid_read_settings_never_claim_a_verified_count(dialog_factory, invalid):
    coordinator = _Coordinator()
    coordinator.model_residency_settings = lambda: deepcopy(invalid)
    dialog = dialog_factory(coordinator)
    assert "未知" in dialog.model_residency_status_label.text()
    assert not dialog.model_residency_checkbox.isEnabled()
    assert not dialog.release_models_button.isEnabled()


def test_timer_refreshes_only_local_snapshot_without_creating_jobs(dialog_factory):
    coordinator = _Coordinator(True, 1)
    dialog = dialog_factory(coordinator)
    coordinator.count = 3
    for _ in range(3):
        dialog._tick()
    assert coordinator.calls == ["read"] * 4
    assert not dialog._jobs and coordinator.worker_threads == []
    assert "当前驻留 3 个" in dialog.model_residency_status_label.text()


def test_residency_controls_render_inside_minimum_size_without_showing_a_window(dialog_factory):
    dialog = dialog_factory(_Coordinator(True, 2))
    dialog.resize(1000, 650)
    dialog.ensurePolished()
    dialog.layout().activate()
    assert not dialog.grab().isNull()
    assert not dialog.isVisible()
    for widget in (dialog.model_residency_checkbox, dialog.model_residency_status_label,
                   dialog.release_models_button, dialog.model_residency_warning_label):
        top_left = widget.mapTo(dialog, widget.rect().topLeft())
        bottom_right = widget.mapTo(dialog, widget.rect().bottomRight())
        assert 0 <= top_left.x() <= bottom_right.x() < dialog.width()
        assert 0 <= top_left.y() <= bottom_right.y() < dialog.height()
    for label in (dialog.model_residency_status_label, dialog.model_residency_warning_label):
        assert label.height() >= label.heightForWidth(label.width())


def test_partial_interface_cannot_claim_close_cleanup_is_available(dialog_factory):
    class PartialCoordinator:
        def model_residency_settings(self):
            return _settings(True, 1)

    dialog = dialog_factory(PartialCoordinator())
    assert "不支持修改或释放" in dialog.model_residency_status_label.text()
    assert not dialog.model_residency_checkbox.isEnabled()
    event = QCloseEvent()
    dialog.closeEvent(event)
    assert not event.isAccepted() and not dialog._closing_verified
    assert "无法核验关闭清理" in dialog.status_label.text()


@pytest.mark.parametrize("proof", [
    {"phase": "idle", "cleanup_verified": 1},
    {"phase": "idle", "cleanup_verified": True, "unknown": True},
    {"phase": "idle", "cleanup_verified": True, "model_residency": None},
    {"phase": "idle", "cleanup_verified": True, "model_residency": {**_settings(), "resident_model_count": -1}},
    {"phase": "idle", "cleanup_verified": True, "model_residency": _settings(), "unknown": True},
])
def test_invalid_cancel_proof_retains_owner_and_does_not_release_models(dialog_factory, proof):
    coordinator = _Coordinator(True, 1)
    coordinator.cancel = lambda: deepcopy(proof)
    dialog = dialog_factory(coordinator)
    dialog._has_owner = True
    dialog._phase = "observed"
    dialog.close()
    _drain(dialog)
    assert dialog._has_owner and not dialog._closing_verified
    assert "失败" in dialog.status_label.text()
    assert "release" not in coordinator.calls


def test_real_coordinator_cancel_retains_model_and_close_releases_it_offline(
        dialog_factory, tmp_path, monkeypatch, backend):
    coordinator, _, _ = _coordinator(tmp_path, monkeypatch)
    dialog = dialog_factory(coordinator)
    try:
        dialog.model_residency_checkbox.click()
        _drain(dialog)
        assert coordinator.model_residency_settings() == _settings(True, 0)
        assert not backend.starts
        dialog._has_owner = True
        dialog._launch("prepare", lambda: _prepare(coordinator))
        _drain(dialog)
        assert dialog._phase == "observed" and len(backend.starts) == 1
        dialog.cancel_button.click()
        _drain(dialog)
        assert dialog._phase == "idle" and not dialog._has_owner
        assert coordinator.model_residency_settings() == _settings(True, 1)
        assert "当前驻留 1 个" in dialog.model_residency_status_label.text()
        assert "模型仍驻留 1 个" in dialog.status_label.text()
        assert dialog.release_models_button.isEnabled()
        assert backend.cleanups == [] and not backend.scopes[0].closed
        dialog.close()
        _drain(dialog)
        assert dialog._closing_verified
        assert coordinator.model_residency_settings() == _settings(True, 0)
        assert len(backend.cleanups) == 1 and backend.scopes[0].closed
    finally:
        if dialog._jobs:
            _drain(dialog)
        coordinator.shutdown()
