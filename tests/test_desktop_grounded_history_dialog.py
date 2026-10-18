from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path
import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from app.desktop_review.window import ensure_application
from tests.test_desktop_single_step_dialog import _wait, _Coordinator


def _item(phase="verification_pending", operation="verify_postcheck"):
    return {"confirmation_id": "grounded-confirmation." + "a" * 64,
            "session_id": "synthetic-session", "observation_id": "synthetic-observation",
            "action_id": "open_detail", "phase": phase, "operation": operation,
            "selection": {"asset_id": "合成审核流程", "asset_content_sha256": "b" * 64,
                          "target_window_handle": 88401, "target_process_id": 9301},
            "claim_sha256": "c" * 64, "request_sha256": "d" * 64,
            "requested_at": "2026-09-07T12:00:00Z", "reason_code": None, "receipt": None}


class History:
    def __init__(self):
        self.item = _item()
        self.calls = []
        self.retain = False
        self.failure = False

    def history(self):
        self.calls.append("history")
        return {"contract_version": "native_grounded_history_v1", "items": [deepcopy(self.item)],
                "retained_confirmation_id": self.item["confirmation_id"] if self.retain else None,
                "artifact_is_authorization": False}

    def recover_history(self, *, confirmation_id):
        self.calls.append(("recover", confirmation_id))
        if self.failure:
            from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError
            raise NativeSingleStepCoordinatorError("synthetic_cleanup_pending", "private-trace-do-not-display", result_unknown=True)
        self.item["phase"] = "terminal"
        self.item["operation"] = "view_history"
        return {"contract_version": "native_grounded_recovery_v1", "item": deepcopy(self.item),
                "owner_retained": self.retain, "reason_code": "cleanup_pending" if self.retain else None,
                "artifact_is_authorization": False}

    def cancel_waiting(self):
        self.calls.append("stop_wait")


def _dialog():
    from app.desktop_review.grounded_history_dialog import GroundedHistoryDialog
    ensure_application()
    co = History()
    dialog = GroundedHistoryDialog(co)
    dialog.show()
    _wait(lambda: not dialog._jobs)
    return co, dialog


def test_history_dialog_has_no_auto_selection_approval_or_execution(monkeypatch):
    co, dialog = _dialog()
    try:
        assert co.calls == ["history"]
        assert not dialog.recover_button.isEnabled()
        dialog.table.selectRow(0)
        assert dialog.recover_button.isEnabled()
        assert dialog.details.isReadOnly()
        defaults = []

        def cancel(*args):
            defaults.append(args[-1])
            return QMessageBox.StandardButton.Cancel

        monkeypatch.setattr(QMessageBox, "question", cancel)
        dialog.recover_button.click()
        assert defaults == [QMessageBox.StandardButton.Cancel]
        assert co.calls == ["history"]
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        dialog.recover_button.click()
        _wait(lambda: not dialog._jobs)
        assert co.calls[-1] == ("recover", co.item["confirmation_id"])
        assert not dialog.recover_button.isEnabled()
        assert not dialog.owner_retained
        assert "terminal" in dialog.details.toPlainText()
    finally:
        dialog.close()


def test_history_failure_retains_owner_and_never_exposes_private_trace(monkeypatch):
    co, dialog = _dialog()
    try:
        co.failure = True
        dialog.table.selectRow(0)
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        dialog.recover_button.click()
        _wait(lambda: not dialog._jobs)
        dialog.close()
        assert dialog.isVisible()
        assert dialog.owner_retained
        assert "private-trace" not in dialog.status.text()
        assert dialog.recover_button.isEnabled()
        co.failure = False
        dialog.recover_button.click()
        _wait(lambda: not dialog._jobs)
        assert not dialog.owner_retained
    finally:
        dialog.close()


@pytest.mark.parametrize("phase,operation", [("dispatch_started", "indeterminate"), ("grounded_confirmation_consume_started", "indeterminate"), ("grounded_confirmation_closed", "view_history")])
def test_history_unknown_and_closed_records_have_no_retry(phase, operation):
    co, dialog = _dialog()
    try:
        co.item = _item(phase, operation)
        dialog.refresh_button.click()
        _wait(lambda: not dialog._jobs)
        dialog.table.selectRow(0)
        assert not dialog.recover_button.isEnabled()
        assert not dialog.owner_retained
    finally:
        dialog.close()


def test_single_step_exposes_history_only_when_no_live_owner():
    from app.desktop_review.single_step_dialog import SingleStepDialog
    ensure_application()
    dialog = SingleStepDialog(_Coordinator())
    try:
        assert dialog.history_button.isEnabled()
        dialog._has_owner = True
        dialog._phase = "approved"
        dialog._update_controls()
        assert not dialog.history_button.isEnabled()
    finally:
        dialog._has_owner = False
        dialog.close()


def test_old_approval_can_only_be_invalidated_not_approved(monkeypatch):
    co, dialog = _dialog()
    try:
        co.item = _item("grounded_confirmation_approved", "close_unexecuted")
        dialog.refresh_button.click()
        _wait(lambda: not dialog._jobs)
        dialog.table.selectRow(0)
        assert dialog.recover_button.text() == "使旧批准失效…"
        assert dialog.recover_button.isEnabled()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
        dialog.recover_button.click()
        assert all(not isinstance(call, tuple) for call in co.calls)
    finally:
        dialog.close()


def test_terminal_cleanup_keeps_recovery_enabled_and_exact_row(monkeypatch):
    co, dialog = _dialog()
    try:
        co.retain = True
        dialog.table.selectRow(0)
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        dialog.recover_button.click()
        _wait(lambda: not dialog._jobs)
        assert dialog.owner_retained
        assert dialog.recover_button.isEnabled()
        assert not dialog.table.isEnabled()
        dialog.refresh_button.click()
        _wait(lambda: not dialog._jobs)
        assert dialog.table.currentRow() == 0
        assert dialog.recover_button.isEnabled()
        co.retain = False
        dialog.recover_button.click()
        _wait(lambda: not dialog._jobs)
        assert not dialog.owner_retained
    finally:
        dialog.close()


def test_actual_qt_store_history_invalidation_and_reopen(tmp_path, monkeypatch):
    from app.desktop_review.grounded_history_dialog import GroundedHistoryDialog
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    from tests.test_runtime_grounded_confirmation_store import _prepared_claim
    from tests.test_native_single_step_coordinator import _Facade, _Host

    ensure_application()
    controller, store, session, preview, backend = _prepared_claim(tmp_path)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id, observation_id=session.current_observation.observation_id, preview=preview,
    )
    cid = pending.grounded_confirmation.confirmation_id

    def forbidden_factory(**kwargs):
        pytest.fail("history must not construct a runtime")

    co = NativeSingleStepCoordinator(tmp_path, _Facade(), _Host(), runtime_factory=forbidden_factory,
                                   thread_initializer=lambda: None, thread_finalizer=lambda: None)
    dialog = GroundedHistoryDialog(co)
    dialog.show()
    target = Path(os.environ.get("R6B7_QA_DIR", str(tmp_path / "qa")))
    target.mkdir(parents=True, exist_ok=True)
    try:
        _wait(lambda: not dialog._jobs)
        assert dialog.table.rowCount() == 1
        dialog.table.selectRow(0)
        assert cid in dialog.details.toPlainText()
        ensure_application().processEvents()
        assert dialog.grab().save(str(target / "native-grounded-history.png"))
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        dialog.recover_button.click()
        _wait(lambda: not dialog._jobs)
        assert not dialog.owner_retained
        closed = store.get_for_grounded_confirmation(confirmation_id=cid)
        assert closed.phase == "grounded_confirmation_closed"
        assert closed.grounded_confirmation.closed_reason_code == "grounded_confirmation_restarted"
        assert backend.attempt_count == 0
        assert "grounded_confirmation_restarted" in dialog.details.toPlainText()
        assert dialog.grab().save(str(target / "native-grounded-history-closed.png"))
        dialog.close()
        reopened = GroundedHistoryDialog(co)
        reopened.show()
        _wait(lambda: not reopened._jobs)
        reopened.table.selectRow(0)
        assert not reopened.recover_button.isEnabled()
        reopened.close()
        co.shutdown()
    finally:
        dialog.close()
        co._owner.close()
        for owned in controller._sessions.values():
            controller._release_window_lease(owned.window_lease)
