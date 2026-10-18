"""预检恢复只重试原目标；测试仅驱动离屏 Qt 和合成 coordinator。"""
from copy import deepcopy

import pytest
from PySide6.QtWidgets import QMessageBox

from app.desktop_review.single_step_dialog import SingleStepDialog
from app.desktop_review.window import ensure_application
from tests.test_desktop_single_step_dialog import _Coordinator, _click, _idle, _prepared_dialog


class _PreparationFailure(RuntimeError):
    code = "preparation_incomplete"
    result_unknown = True

    def __init__(self, retry=True):
        super().__init__("private-fixture-secret")
        self.retry_preparation = retry


class _InterruptedCoordinator(_Coordinator):
    def __init__(self, retry=True):
        super().__init__()
        self.retry = retry
        self.interrupt = True

    def prepare(self, **selection):
        if self.interrupt:
            self.calls.append(("prepare", deepcopy(selection)))
            self.interrupt = False
            raise _PreparationFailure(self.retry)
        return super().prepare(**selection)


def _interrupted_dialog(retry=True):
    ensure_application()
    coordinator = _InterruptedCoordinator(retry)
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    _click(dialog.refresh_button, dialog)
    dialog.asset_selector.setCurrentIndex(0)
    dialog.window_selector.setCurrentIndex(0)
    _click(dialog.prepare_button, dialog)
    return dialog, coordinator


def _close(dialog):
    dialog.close()
    _idle(dialog)
    assert not dialog.isVisible()


def test_explicit_preparation_retry_preserves_exact_selection_without_dispatch():
    dialog, coordinator = _interrupted_dialog()
    try:
        original = deepcopy(dialog._selection)
        assert len([item for item in coordinator.calls if isinstance(item, tuple) and item[0] == "prepare"]) == 1
        assert dialog.prepare_button.isEnabled()
        assert dialog.prepare_button.text() == "重试原目标预检"
        assert not dialog.asset_selector.isEnabled() and not dialog.window_selector.isEnabled()
        assert not dialog.refresh_button.isEnabled()
        assert not dialog.review_button.isEnabled() and not dialog.execute_button.isEnabled()
        assert "尚未执行" in dialog.status_label.text()
        assert "private-fixture-secret" not in dialog.status_label.text()
        different = deepcopy(dialog.asset_selector.currentData())
        different["asset_id"] = "not-the-retained-asset"
        dialog.asset_selector.setItemData(dialog.asset_selector.currentIndex(), different)
        _click(dialog.prepare_button, dialog)
        preparations = [item[1] for item in coordinator.calls if isinstance(item, tuple) and item[0] == "prepare"]
        assert preparations == [original, original]
        assert dialog._phase == "observed"
        assert dialog._session_id is not None and dialog._has_owner
        assert dialog.prepare_button.text() == "预检选定目标"
        assert not dialog.approve_button.isEnabled() and not dialog.execute_button.isEnabled()
        assert not any(isinstance(item, tuple) and item[0] in {"execute", "approve"} for item in coordinator.calls)
    finally:
        _close(dialog)


def test_interrupted_preparation_can_close_without_restarting_preflight():
    dialog, coordinator = _interrupted_dialog()
    _close(dialog)
    assert coordinator.calls[-1] == "cancel"
    assert len([item for item in coordinator.calls if isinstance(item, tuple) and item[0] == "prepare"]) == 1
    assert not dialog._has_owner and dialog._selection is None


@pytest.mark.parametrize("retry", [False, None, 1, "true", {}, []])
def test_unverified_retry_signal_never_enables_preparation(retry):
    dialog, _coordinator = _interrupted_dialog(retry)
    try:
        assert not dialog.prepare_button.isEnabled()
        assert dialog._has_owner and dialog.cancel_button.isEnabled()
    finally:
        _close(dialog)


def test_cleanup_failure_does_not_lose_preparation_owner_or_reenable_actions():
    dialog, coordinator = _interrupted_dialog()
    original = deepcopy(dialog._selection)
    try:
        coordinator.fail_cancel = True
        _click(dialog.cancel_button, dialog)
        assert dialog.isVisible() and dialog._has_owner and dialog._selection == original
        assert not dialog.prepare_button.isEnabled()
        assert not dialog.execute_button.isEnabled()
        assert dialog.cancel_button.isEnabled()
    finally:
        coordinator.fail_cancel = False
        _close(dialog)


def test_execution_unknown_cannot_forge_a_preparation_retry(monkeypatch):
    dialog, coordinator = _prepared_dialog()
    try:
        _click(dialog.approve_button, dialog)
        def fail_execute(**_identity):
            coordinator.calls.append("unknown-execution")
            raise _PreparationFailure(True)
        coordinator.execute = fail_execute
        monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes)
        _click(dialog.execute_button, dialog)
        assert dialog._phase == "recovery_required"
        assert not dialog.prepare_button.isEnabled() and not dialog.execute_button.isEnabled()
        assert "执行结果未知" in dialog.status_label.text()
        assert dialog._has_owner
        assert coordinator.calls.count("unknown-execution") == 1
    finally:
        _close(dialog)


def test_stale_preparation_success_does_not_replace_retained_recovery_state():
    dialog, _coordinator = _interrupted_dialog()
    try:
        before = (deepcopy(dialog._selection), dialog._phase, dialog._session_id)
        dialog._job_result(dialog._request_id - 1, {"phase": "observed", "session_id": "foreign", "actions": []})
        assert (dialog._selection, dialog._phase, dialog._session_id) == before
        assert dialog.prepare_button.isEnabled()
    finally:
        _close(dialog)
