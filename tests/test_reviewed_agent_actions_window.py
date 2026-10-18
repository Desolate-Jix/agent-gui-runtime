"""原生待审按钮读取已审核准备，不把它当作首次学习。"""

from __future__ import annotations

from copy import deepcopy
import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app.desktop_review.single_step_dialog import SingleStepDialog
from app.desktop_review.window import ensure_application
from tests.test_desktop_single_step_dialog import _review


class _ReviewedCoordinator:
    def __init__(self) -> None:
        self.view = _review()
        self.view["source_kind"] = "reviewed_learning"
        self.calls = []

    def current_agent_review(self):
        self.calls.append(("current_agent_review", {}))
        return deepcopy(self.view)

    def approve(self, **identity):
        self.calls.append(("approve", identity))
        result = deepcopy(self.view)
        result["phase"] = "approved"
        return result

    def deny(self, **identity):
        self.calls.append(("deny", identity))
        return {"phase": "denied", "confirmation_id": identity["confirmation_id"],
                "artifact_is_authorization": False}

    def cancel(self):
        self.calls.append(("cancel", {}))
        return {"phase": "idle", "cleanup_verified": True}


def _wait(dialog: SingleStepDialog) -> None:
    app = ensure_application()
    deadline = time.monotonic() + 10
    while dialog._jobs:
        assert time.monotonic() < deadline
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()


def test_pending_agent_button_loads_reviewed_preview_and_uses_reviewed_hash():
    ensure_application()
    coordinator = _ReviewedCoordinator()
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    try:
        assert dialog.fresh_review_button.isEnabled()
        QTest.mouseClick(dialog.fresh_review_button, Qt.MouseButton.LeftButton)
        _wait(dialog)
        expected = deepcopy(coordinator.view)
        expected.pop("source_kind")
        assert dialog.preview_widget.review == expected, dialog.status_label.text()
        assert dialog.approve_button.isEnabled()
        QTest.mouseClick(dialog.approve_button, Qt.MouseButton.LeftButton)
        _wait(dialog)
        approve = next(item for item in coordinator.calls if item[0] == "approve")
        assert approve[1] == {
            "confirmation_id": coordinator.view["confirmation_id"],
            "preview_content_sha256": coordinator.view["preview"]["content_sha256"],
        }
    finally:
        dialog._has_owner = False
        dialog.close()


def test_reviewed_pending_denial_never_uses_fresh_preview_keyword():
    ensure_application()
    coordinator = _ReviewedCoordinator()
    dialog = SingleStepDialog(coordinator)
    dialog.show()
    try:
        QTest.mouseClick(dialog.fresh_review_button, Qt.MouseButton.LeftButton)
        _wait(dialog)
        assert dialog.deny_button.isEnabled(), dialog.status_label.text()
        QTest.mouseClick(dialog.deny_button, Qt.MouseButton.LeftButton)
        _wait(dialog)
        deny = next(item for item in coordinator.calls if item[0] == "deny")
        assert deny[1] == {
            "confirmation_id": coordinator.view["confirmation_id"],
            "preview_content_sha256": coordinator.view["preview"]["content_sha256"],
        }
    finally:
        dialog._has_owner = False
        dialog.close()
