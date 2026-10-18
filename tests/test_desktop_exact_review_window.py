from __future__ import annotations

import base64
import copy
import os
import threading
import time
from io import BytesIO
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QDialog, QMessageBox

from app.desktop_review.exact_dialog import ExactReviewDialog
from app.desktop_review.library_dialog import WorkflowLibraryDialog
from app.desktop_review.window import ensure_application


def _batch() -> dict:
    image = Image.new("RGB", (80, 60), "white")
    output = BytesIO(); image.save(output, "PNG")
    return {
        "contract_version": "agent_link_v1", "idempotency_key": "exact-ui", "batch_id": "batch", "title": "审核草稿", "learning_outcome": "completed", "outcome_reason": None,
        "screenshots": [{"screenshot_id": "shot", "png_base64": base64.b64encode(output.getvalue()).decode("ascii"), "width": 80, "height": 60}],
        "interfaces": [{"interface_id": "one", "screenshot_id": "shot", "meaning": "界面一", "regions": [{"region_id": "open", "bbox": [2.0, 3.0, 20.0, 12.0], "name": "打开", "meaning": "查看详情"}]}],
        "relationships": [], "steps": [{"step_id": "open", "action_type": "open_detail", "target_region_id": "open", "start_state": "one", "arrival_state": "one", "prerequisites": [], "expected_result": "详情可见", "stop_condition": "停止"}], "issues": [],
    }


class _ExactFacade:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.subjects = [
            {"subject_id": "application", "kind": "application", "label": "Notepad", "content": "native notepad.exe", "confirmed": False},
            {"subject_id": "step-open", "kind": "step", "label": "打开", "content": "完整步骤内容", "confirmed": False},
        ]

    def prepare_exact_review(self, *args) -> dict:
        self.calls.append("prepare")
        return self._review(0, "prepared")

    def record_review_decisions(self, review_ref: str, revision: int, confirmed: list[str]) -> dict:
        self.calls.append("record")
        for subject in self.subjects:
            subject["confirmed"] = subject["subject_id"] in confirmed
        return self._review(revision + 1, "reviewed")

    def compile_exact_review(self, review_ref: str, revision: int) -> dict:
        self.calls.append("compile")
        complete = all(item["confirmed"] for item in self.subjects)
        result = self._review(revision, "compiled" if complete else "blocked")
        result["compile_receipt_id"] = "receipt-1" if complete else None
        return result

    def publish_exact_review(self, receipt: str) -> dict:
        self.calls.append("publish")
        return {"status": "published", "receipt": receipt}

    def list_reviewed_assets(self) -> list[dict]:
        return [{"asset_id": "asset-1", "application": "native:notepad.exe", "display_name": "Notepad", "content_sha256": "a" * 64}]

    def _review(self, revision: int, status: str) -> dict:
        return {"contract_version": "desktop_exact_review_v1", "review_ref": "review-1", "task_id": "task", "batch_id": "batch", "source_ref": "a" * 64, "workspace_revision": 1, "approval_revision": revision, "application_identity": {"kind": "native"}, "subjects": copy.deepcopy(self.subjects), "blocked_reasons": [], "status": status, "compile_receipt_id": None}


def _workspace() -> dict:
    return {"task_id": "task", "batch_id": "batch", "revision": 1, "source": "untrusted_external", "source_ref": "a" * 64, "workflow_review_path": "saved-review.json", "batch": _batch()}


def _wait(predicate) -> None:
    deadline = time.monotonic() + 8
    application = ensure_application()
    while time.monotonic() < deadline:
        time.sleep(0.01)
        application.processEvents()
        if predicate():
            return
    raise AssertionError("native background response was not rendered")


def test_exact_dialog_roundtrips_partial_decisions_then_compile_publish() -> None:
    application = ensure_application()
    facade = _ExactFacade()
    dialog = ExactReviewDialog(facade, _workspace())
    dialog.show()
    dialog.application_display_name.setText("Notepad")
    dialog.application_identity.setText("notepad.exe")
    QTest.mouseClick(dialog.prepare_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.review is not None)
    assert dialog.subject_table.rowCount() == 2
    assert not dialog.subject_table.cellWidget(0, 0).isChecked()
    dialog.subject_table.selectRow(1)
    QTest.qWait(10)
    assert "完整步骤内容" in dialog.subject_detail.toPlainText()
    dialog.subject_table.cellWidget(0, 0).setChecked(True)
    QTest.mouseClick(dialog.record_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.review is not None and dialog.review["approval_revision"] == 1)
    QTest.mouseClick(dialog.compile_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.review is not None and dialog.review["status"] == "blocked")
    dialog.subject_table.cellWidget(1, 0).setChecked(True)
    QTest.mouseClick(dialog.record_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.review is not None and dialog.review["approval_revision"] == 2)
    QTest.mouseClick(dialog.compile_button, Qt.MouseButton.LeftButton)
    _wait(lambda: bool(dialog.review and dialog.review.get("compile_receipt_id")))
    QTest.mouseClick(dialog.publish_button, Qt.MouseButton.LeftButton)
    _wait(lambda: "入库回执" in dialog.status_label.text())
    assert facade.calls == ["prepare", "record", "compile", "record", "compile", "publish"]
    _wait(lambda: not dialog._jobs)
    dialog.close(); application.processEvents()
    library = WorkflowLibraryDialog(facade)
    library.show()
    _wait(lambda: library.asset_table.rowCount() == 1)
    assert library.asset_table.item(0, 2).text() == "a" * 64
    library.asset_table.selectRow(0)
    QTest.qWait(10)
    assert "content_sha256" in library.asset_detail.toPlainText()
    _wait(lambda: not library._jobs)
    library.close(); application.processEvents()


def test_real_facade_prepare_and_library_are_native(tmp_path: Path) -> None:
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.desktop_review.workspace import NativeReviewFacade

    application = ensure_application()
    store = AgentLinkStore(tmp_path / "inbox.json")
    token = "exact-native-reviewer-token"
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "task", "agent_name": "fixture"})
    proposed = _batch()
    for screenshot in proposed["screenshots"]:
        screenshot.pop("width"); screenshot.pop("height")
    service.agent_call(grant["token"], "submit_batch", proposed)
    facade = NativeReviewFacade(service, token, tmp_path / "root")
    try:
        workspace = facade.save_revision("task", "batch", 0, facade.load_batch("task", "batch")["batch"])
        facade.prepare_exact_review("task", "batch", workspace["revision"], {"kind": "native", "display_name": "Notepad", "executable_identity": "notepad.exe"}, {"open": []}, [])
        dialog = ExactReviewDialog(facade, workspace)
        dialog.show()
        dialog.application_display_name.setText("Notepad")
        dialog.application_identity.setText("notepad.exe")
        QTest.mouseClick(dialog.prepare_button, Qt.MouseButton.LeftButton)
        _wait(lambda: dialog.review is not None)
        assert dialog.review and dialog.review["review_ref"]
        assert dialog.subject_table.rowCount() > 0
        _wait(lambda: not dialog._jobs)
        dialog.close(); application.processEvents()
        library = WorkflowLibraryDialog(facade)
        library.show()
        _wait(lambda: "已读取" in library.status.text())
        assert library.asset_table.rowCount() == 0
        _wait(lambda: not library._jobs)
        library.close(); application.processEvents()
    finally:
        facade.close(); store.close()


def test_exact_dialog_preserves_stop_choice_and_disables_stale_compile_publish(monkeypatch) -> None:
    application = ensure_application()
    facade = _ExactFacade()
    workspace = _workspace()
    workspace["batch"]["interfaces"].append({"interface_id": "stop", "screenshot_id": "shot", "meaning": "停止界面", "regions": []})
    dialog = ExactReviewDialog(facade, workspace)
    dialog.show()
    stop = dialog.findChildren(QCheckBox, "exactStopInterface")[1]
    stop.setChecked(True)
    dialog.application_display_name.setText("Notepad")
    dialog.application_identity.setText("notepad.exe")
    QTest.mouseClick(dialog.prepare_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.review is not None)
    selected = [box.property("interface_id") for box in dialog.findChildren(QCheckBox, "exactStopInterface") if box.isChecked()]
    assert selected == ["stop"]
    dialog.review["compile_receipt_id"] = "receipt-1"
    dialog._set_controls()
    dialog.subject_table.cellWidget(0, 0).setChecked(True)
    assert dialog._decision_dirty
    assert not dialog.prepare_button.isEnabled()
    assert not dialog.compile_button.isEnabled()
    assert not dialog.publish_button.isEnabled()
    review_ref = dialog.review["review_ref"]
    dialog.prepare()
    assert dialog.review["review_ref"] == review_ref
    assert dialog.subject_table.cellWidget(0, 0).isChecked()
    assert dialog._decision_dirty
    _wait(lambda: not dialog._jobs)
    monkeypatch.setattr("app.desktop_review.exact_dialog.QMessageBox.question", lambda *args: QMessageBox.StandardButton.Discard)
    dialog.close(); application.processEvents()


class _DelayedExactFacade(_ExactFacade):
    def __init__(self, malformed: bool = False, non_dict: bool = False) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.malformed = malformed
        self.non_dict = non_dict

    def prepare_exact_review(self, *args) -> object:
        self.started.set()
        self.release.wait(3)
        if self.non_dict:
            return ["不是审核响应"]
        result = super().prepare_exact_review(*args)
        if self.malformed:
            result["task_id"] = "wrong-task"
        return result


class _WrongRevisionRecordFacade(_ExactFacade):
    def record_review_decisions(self, review_ref: str, revision: int, confirmed: list[str]) -> dict:
        result = super().record_review_decisions(review_ref, revision, confirmed)
        result["approval_revision"] = revision + 2
        return result


def test_exact_dialog_worker_close_guard_and_malformed_response(monkeypatch) -> None:
    application = ensure_application()
    monkeypatch.setattr("app.desktop_review.exact_dialog.QMessageBox.information", lambda *args: None)
    facade = _DelayedExactFacade()
    dialog = ExactReviewDialog(facade, _workspace())
    dialog.show()
    dialog.application_display_name.setText("Notepad")
    dialog.application_identity.setText("notepad.exe")
    QTest.mouseClick(dialog.prepare_button, Qt.MouseButton.LeftButton)
    assert facade.started.wait(1)
    dialog.reject()
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    dialog.close()
    assert dialog.isVisible() and dialog._jobs
    facade.release.set()
    _wait(lambda: not dialog._jobs)
    dialog.close(); application.processEvents()

    malformed = _DelayedExactFacade(malformed=True)
    malformed.release.set()
    response_dialog = ExactReviewDialog(malformed, _workspace())
    response_dialog.show()
    response_dialog.application_display_name.setText("Notepad")
    response_dialog.application_identity.setText("notepad.exe")
    QTest.mouseClick(response_dialog.prepare_button, Qt.MouseButton.LeftButton)
    _wait(lambda: not response_dialog._busy)
    assert response_dialog.review is None
    assert response_dialog.prepare_button.isEnabled()
    assert "身份不匹配" in response_dialog.status_label.text()
    _wait(lambda: not response_dialog._jobs)
    response_dialog.close(); application.processEvents()

    non_dict = _DelayedExactFacade(non_dict=True)
    non_dict.release.set()
    malformed_type_dialog = ExactReviewDialog(non_dict, _workspace())
    malformed_type_dialog.show()
    malformed_type_dialog.application_display_name.setText("Notepad")
    malformed_type_dialog.application_identity.setText("notepad.exe")
    QTest.mouseClick(malformed_type_dialog.prepare_button, Qt.MouseButton.LeftButton)
    _wait(lambda: not malformed_type_dialog._busy)
    assert malformed_type_dialog.review is None
    assert malformed_type_dialog.prepare_button.isEnabled()
    assert "返回格式无效" in malformed_type_dialog.status_label.text()
    _wait(lambda: not malformed_type_dialog._jobs)
    malformed_type_dialog.close(); application.processEvents()


def test_exact_dialog_rejects_wrong_record_revision_without_replacing_draft(monkeypatch) -> None:
    application = ensure_application()
    facade = _WrongRevisionRecordFacade()
    dialog = ExactReviewDialog(facade, _workspace())
    dialog.show()
    dialog.application_display_name.setText("Notepad")
    dialog.application_identity.setText("notepad.exe")
    QTest.mouseClick(dialog.prepare_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.review is not None)
    dialog.subject_table.cellWidget(0, 0).setChecked(True)
    QTest.mouseClick(dialog.record_button, Qt.MouseButton.LeftButton)
    _wait(lambda: not dialog._busy)
    assert dialog.review is not None and dialog.review["approval_revision"] == 0
    assert dialog.subject_table.cellWidget(0, 0).isChecked()
    assert dialog._decision_dirty
    assert "修订不匹配" in dialog.status_label.text()
    _wait(lambda: not dialog._jobs)
    monkeypatch.setattr("app.desktop_review.exact_dialog.QMessageBox.question", lambda *args: QMessageBox.StandardButton.Discard)
    dialog.close(); application.processEvents()


def test_exact_dialog_keeps_unsaved_withdrawal_on_every_close_path(monkeypatch) -> None:
    application = ensure_application()
    facade = _ExactFacade()
    dialog = ExactReviewDialog(facade, _workspace())
    dialog.show()
    dialog.application_display_name.setText("Notepad")
    dialog.application_identity.setText("notepad.exe")
    QTest.mouseClick(dialog.prepare_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.review is not None)
    dialog.subject_table.cellWidget(0, 0).setChecked(True)
    QTest.mouseClick(dialog.record_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.review is not None and dialog.review["approval_revision"] == 1)
    dialog.review["compile_receipt_id"] = "receipt-1"
    dialog.subject_table.cellWidget(0, 0).setChecked(False)
    assert dialog._decision_dirty
    _wait(lambda: not dialog._jobs)
    defaults = []
    def cancel_default(*args):
        defaults.append(args[-1])
        return QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(
        "app.desktop_review.exact_dialog.QMessageBox.question",
        cancel_default,
    )
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert dialog.isVisible()
    dialog.reject()
    assert dialog.isVisible()
    dialog.done(QDialog.DialogCode.Rejected)
    assert dialog.isVisible()
    dialog.close()
    assert dialog.isVisible()
    assert defaults == [QMessageBox.StandardButton.Cancel] * 4
    monkeypatch.setattr(
        "app.desktop_review.exact_dialog.QMessageBox.question",
        lambda *args: QMessageBox.StandardButton.Discard,
    )
    dialog.close()
    assert not dialog.isVisible()
    application.processEvents()


def test_exact_dialog_window_close_exits_native_modal_loop():
    from PySide6.QtCore import QTimer
    application = ensure_application()
    dialog = ExactReviewDialog(_ExactFacade(), _workspace())
    guard_used = []
    guard = QTimer(dialog)
    guard.setSingleShot(True)
    guard.timeout.connect(lambda: (guard_used.append(True), dialog.reject()))
    guard.start(1000)
    QTimer.singleShot(0, dialog.close)
    assert dialog.exec() == QDialog.DialogCode.Rejected
    assert not guard_used
    guard.stop()
    application.processEvents()


def test_exact_relationship_keyboard_navigation_reaches_prepare_without_decisions():
    application = ensure_application()
    facade = _ExactFacade()
    dialog = ExactReviewDialog(facade, _workspace())
    dialog.show()
    try:
        dialog.application_product_name.setFocus()
        application.processEvents()
        QTest.keyClick(dialog.application_product_name, Qt.Key.Key_Tab)
        application.processEvents()
        assert application.focusWidget() is dialog.step_relationship_table
        QTest.keyClick(dialog.step_relationship_table, Qt.Key.Key_End)
        application.processEvents()
        assert application.focusWidget() is dialog.step_relationship_table.cellWidget(0, 3)
        forward = []
        for _ in range(6):
            QTest.keyClick(application.focusWidget(), Qt.Key.Key_Tab)
            application.processEvents()
            forward.append(application.focusWidget().objectName())
            if application.focusWidget() is dialog.prepare_button:
                break
        assert application.focusWidget() is dialog.prepare_button, forward
        backward = []
        for _ in range(6):
            QTest.keyClick(application.focusWidget(), Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
            application.processEvents()
            backward.append(application.focusWidget().objectName())
            if application.focusWidget() is dialog.application_product_name:
                break
        assert application.focusWidget() is dialog.application_product_name, backward
        assert dialog._step_relationships() == {"open": []}
        assert not dialog._stop_interface_ids()
        assert dialog.review is None
        assert not facade.calls
    finally:
        dialog.close()
        application.processEvents()
