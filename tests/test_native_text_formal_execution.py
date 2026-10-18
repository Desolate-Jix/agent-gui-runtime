from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from app.agent.reviewed_workflow_asset import content_sha256
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from app.desktop_review.single_step_dialog import SingleStepDialog
from app.desktop_review.window import ensure_application
from tests.test_desktop_single_step_dialog import _click, _idle, _wait
from tests.test_text_formal_execution import assert_restored, formal_text


def test_dialog_keeps_legacy_fill_preview_without_local_field_expectation_nonexecutable():
    ensure_application()
    dialog = SingleStepDialog(SimpleNamespace())
    try:
        dialog._phase = "approved"
        dialog.preview_widget._review = {
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat(),
            "preview": {"grounding_preview": {"semantic_action": "fill_field"}},
        }
        dialog._update_controls()
        assert not dialog.execute_button.isEnabled()
    finally:
        dialog.close()


@pytest.mark.parametrize(("variable", "clear"), [(False, True), (True, False)])
def test_native_dialog_executes_one_formal_text_step_after_independent_confirmation(formal_text, monkeypatch, tmp_path, variable, clear):
    ensure_application()
    f = formal_text(variable=variable, clear=clear, start=False)
    host = DesktopReviewHost(tmp_path / "host.sqlite", tmp_path / "review", "native-formal-text-token", port=0)
    host.start(timeout=15.0)
    factory = lambda **_kwargs: f.service
    factory.window_manager = f.windows
    coordinator = NativeSingleStepCoordinator(
        f.root,
        SimpleNamespace(list_reviewed_assets=f.facade.list_reviewed_assets),
        host,
        runtime_factory=factory,
        thread_initializer=lambda: None,
        thread_finalizer=lambda: None,
        foreground_timeout=0.1,
    )
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    confirmations = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: confirmations.append(args) or QMessageBox.StandardButton.Yes)
    try:
        _click(dialog.refresh_button, dialog)
        dialog.asset_selector.setCurrentIndex(0)
        dialog.window_selector.setCurrentIndex(0)
        _click(dialog.prepare_button, dialog)
        dialog.action_selector.setCurrentIndex(0)
        _click(dialog.review_button, dialog)
        _wait(lambda: dialog._text_input_dialog is not None)
        editor = dialog._text_input_dialog
        approved_text = f.expected_text if not variable else f.expected_text.replace("\r\n", "\n")
        if variable:
            editor.text_editor.setPlainText(f.expected_text)
        else:
            assert editor.text_editor.isReadOnly()
            assert editor.text_editor.toPlainText() == f.expected_text.replace("\r\n", "\n")
        QTest.mouseClick(editor.continue_button, Qt.MouseButton.LeftButton)
        _idle(dialog)
        expected_final = approved_text if clear else "A" + approved_text + "D"
        assert dialog.preview_widget.review["text_field_local"].before.value == "ABCD"
        assert dialog.preview_widget.text_before_editor.toPlainText() == "ABCD"
        assert dialog.preview_widget.text_expected_editor.toPlainText() == expected_final.replace("\r\n", "\n")
        assert f.state.pasted == []
        _click(dialog.approve_button, dialog)
        assert f.state.pasted == []
        assert "独立确认" in dialog.status_label.text()
        assert dialog.execute_button.isEnabled()
        _click(dialog.execute_button, dialog)
        assert len(confirmations) == 1
        assert confirmations[0][-1] == QMessageBox.StandardButton.Cancel
        assert f.state.pasted == [approved_text]
        assert "VERIFIED" in dialog.receipt_text.toPlainText()
        assert not dialog.execute_button.isEnabled()
        dialog._execute()
        assert f.state.pasted == [approved_text]
        assert_restored(f.api, f.original)
        confirmation_id = dialog.preview_widget.review["confirmation_id"]
        terminal = f.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        assert terminal.phase == "terminal"
        preview = dialog.preview_widget.review["preview"]
        persisted = f.claims.load_terminal_receipt(
            session_id=preview["session_id"], observation_id=preview["observation_id"],
        )
        assert persisted.outcome == "VERIFIED"
        _click(dialog.cancel_button, dialog)
    finally:
        dialog.close()
        _idle(dialog)
        coordinator.shutdown()
        host.close()
