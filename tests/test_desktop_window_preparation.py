from __future__ import annotations

import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from app.desktop_review.single_step_dialog import SingleStepDialog
from app.desktop_review.window import ensure_application


class _Coordinator:
    def __init__(self):
        self.calls = []

    def inventory(self):
        return {"assets": [], "windows": []}

    def clear_window_preparation(self):
        self.calls.append("clear")
        return None

    def preview_window_preparation(self, **kwargs):
        self.calls.append(("preview", kwargs))
        return {"contract_version": "native_window_preparation_v1", "preparation_id": "intent-1", "mode": kwargs["mode"],
                "asset_id": kwargs["asset_id"], "asset_content_sha256": kwargs["asset_content_sha256"],
                "executable_path": r"C:\fixture\app.exe", "identity": None, "expires_in_seconds": 60}

    def confirm_window_preparation(self, preparation_id):
        self.calls.append(("confirm", preparation_id))
        return {"status": "launched_window_unavailable", "process_id": 77, "window": None, "reason": "launched_window_timeout"}


def _wait(predicate, timeout=3):
    app = ensure_application()
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline
        QTest.qWait(10)
        app.processEvents()


def _configured_dialog(coordinator=None):
    ensure_application()
    dialog = SingleStepDialog(coordinator or _Coordinator())
    dialog.asset_selector.addItem("资产", {"asset_id": "asset-1", "content_sha256": "a" * 64})
    dialog.asset_selector.setCurrentIndex(0)
    return dialog


def test_single_step_dialog_exposes_separate_window_preparation_controls() -> None:
    ensure_application()
    dialog = SingleStepDialog(_Coordinator())
    try:
        assert dialog.launch_window_button.text() == "启动流程对应程序…"
        assert dialog.focus_window_button.text() == "恢复/聚焦选定窗口…"
        assert not dialog.launch_window_button.isEnabled()
        assert not dialog.focus_window_button.isEnabled()
    finally:
        dialog.close()


def test_busy_window_preparation_blocks_preflight_and_preparation_controls() -> None:
    dialog = _configured_dialog()
    marker = object()
    try:
        dialog._jobs.add(marker)
        dialog._update_controls()
        assert not dialog.prepare_button.isEnabled()
        assert not dialog.launch_window_button.isEnabled()
        assert not dialog.focus_window_button.isEnabled()
    finally:
        dialog._jobs.discard(marker)
        dialog._update_controls()
        dialog.close()


def test_launch_preparation_default_cancel_has_no_confirm_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    dialog = _configured_dialog()
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.StandardButton.Cancel)
    try:
        QTest.mouseClick(dialog.launch_window_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert [call for call in dialog.coordinator.calls if isinstance(call, tuple) and call[0] == "confirm"] == []
    finally:
        dialog.close()


def test_launch_preparation_yes_queues_one_confirm_and_nonready_does_not_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    dialog = _configured_dialog()
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.StandardButton.Yes)
    try:
        QTest.mouseClick(dialog.launch_window_button, Qt.MouseButton.LeftButton)
        _wait(lambda: (
            [("confirm", "intent-1")] == [call for call in dialog.coordinator.calls if isinstance(call, tuple) and call[0] == "confirm"]
            and not dialog._jobs
            and "launched_window_timeout" in dialog.receipt_text.toPlainText()
        ))
        assert "未能核验窗口就绪" in dialog.status_label.text()
        assert "未开始模型、审核或输入" in dialog.status_label.text()
    finally:
        _wait(lambda: not dialog._jobs)
        dialog.close()
        QTest.qWait(20)


def test_window_confirmation_failure_clears_pending_intent_without_claiming_undo() -> None:
    dialog = _configured_dialog()
    try:
        dialog._window_preparation = {"preparation_id": "intent-1"}
        dialog._operation = "window_confirm"
        dialog._failure("window_preparation_identity_changed", unknown=True)
        assert dialog._window_preparation is None
        assert "未自动继续" in dialog.status_label.text()
    finally:
        dialog.close()
