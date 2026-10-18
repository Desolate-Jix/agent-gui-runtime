"""本地拒绝候选的原生确认与回执测试。"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from app.desktop_review import relearn_dialog as module
from test_desktop_relearn_adoption_window import _compared
from test_desktop_relearn_window import _wait


def _receipt(dialog):
    compared = dialog.comparison
    return {
        "contract_version": "desktop_candidate_rejection_receipt_v1",
        **{key: compared[key] for key in ("task_id", "batch_id", "source_ref", "candidate_id", "candidate_sha256", "review_baseline_sha256")},
        "workspace_revision": 1, "decision_revision": 1,
        "current_revision": 1, "current_decision_revision": 1,
        "reason": "框的位置不正确，请重新学习", "record_sha256": "d" * 64,
        "staging_only": True,
    }


def _prompt(monkeypatch, accepted=True):
    class Prompt:
        def __init__(self, comparison, reason, parent):
            self.reason = reason or "框的位置不正确，请重新学习"
        def exec(self):
            return QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
        def deleteLater(self):
            pass
    monkeypatch.setattr(module, "RejectionReasonDialog", Prompt)


def test_rejection_requires_explicit_reason_and_cancel_has_no_side_effect(monkeypatch):
    application, facade, dialog = _compared()
    calls = []
    facade.reject_relearn_candidate = lambda *args: calls.append(args)
    _prompt(monkeypatch, accepted=False)
    try:
        QTest.mouseClick(dialog.reject_candidate_button, Qt.MouseButton.LeftButton)
        assert calls == []
        assert not dialog.requires_workspace_reload
    finally:
        dialog.close(); application.processEvents()


def test_valid_rejection_receipt_updates_local_decision_without_workspace_edit(monkeypatch):
    application, facade, dialog = _compared()
    receipt, calls = _receipt(dialog), []
    facade.reject_relearn_candidate = lambda *args: (calls.append(args), copy.deepcopy(receipt))[1]
    _prompt(monkeypatch)
    try:
        QTest.mouseClick(dialog.reject_candidate_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert calls[0][:8] == ("task", "batch", 1, "candidate-1", "b" * 64, "c" * 64, 0, receipt["reason"])
        assert dialog.rejection_receipt == receipt
        assert dialog.workspace["revision"] == 1
        assert dialog.comparison is None
        assert not dialog.adopt_button.isEnabled()
        assert "已拒绝" in dialog.candidate_table.item(0, 3).text()
        assert not dialog.requires_workspace_reload
    finally:
        dialog.close(); application.processEvents()


@pytest.mark.parametrize("mutation", ["reason", "candidate_id", "decision_revision", "record_sha256", "workspace_revision"])
def test_invalid_rejection_receipt_keeps_reason_and_retries_same_request(monkeypatch, mutation):
    application, facade, dialog = _compared()
    valid, calls = _receipt(dialog), []
    bad = copy.deepcopy(valid)
    bad[mutation] = True if mutation.endswith("revision") else "invalid"
    facade.reject_relearn_candidate = lambda *args: (calls.append(args), copy.deepcopy(bad))[1]
    _prompt(monkeypatch)
    try:
        QTest.mouseClick(dialog.reject_candidate_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.rejection_receipt is None
        assert dialog.comparison is not None
        assert dialog._rejection_reason == valid["reason"]
        facade.reject_relearn_candidate = lambda *args: (calls.append(args), copy.deepcopy(valid))[1]
        QTest.mouseClick(dialog.reject_candidate_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert calls[0] == calls[1]
        assert dialog.rejection_receipt == valid
    finally:
        dialog.close(); application.processEvents()


def test_rejection_disabled_with_unsent_feedback_or_rejected_candidate():
    application, _, dialog = _compared()
    try:
        dialog.message.setPlainText("还有未提交的问题")
        assert not dialog.reject_candidate_button.isEnabled()
        dialog.message.clear()
        dialog.comparison["blocked_reasons"].append("locally_rejected")
        dialog._controls()
        assert not dialog.reject_candidate_button.isEnabled()
    finally:
        dialog.message.clear(); dialog.close(); application.processEvents()


def test_withdrawn_candidate_does_not_offer_local_rejection():
    application, _, dialog = _compared()
    try:
        dialog.comparison["status"] = "withdrawn"
        dialog._controls()
        assert not dialog.reject_candidate_button.isEnabled()
    finally:
        dialog.close(); application.processEvents()


def test_rejection_reason_native_dialog_defaults_to_cancel():
    from app.desktop_review.candidate_rejection_dialog import RejectionReasonDialog
    from app.desktop_review.window import ensure_application
    application = ensure_application()
    dialog = RejectionReasonDialog({"candidate_id": "candidate-1", "workspace_revision": 1}, "", None)
    dialog.show(); application.processEvents()
    try:
        assert dialog.cancel_button.isDefault()
        assert not dialog.confirm_button.isEnabled()
        dialog.reason_edit.setPlainText("识别框遮住了相邻按钮")
        assert dialog.confirm_button.isEnabled()
        QTest.mouseClick(dialog.cancel_button, Qt.MouseButton.LeftButton)
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert dialog.reason == "识别框遮住了相邻按钮"
    finally:
        dialog.close(); application.processEvents()


def test_native_geometry_entry_opens_actual_readonly_widget_without_writes():
    from app.desktop_review.geometry_comparison import GeometryComparisonWidget
    application, _, dialog = _compared()
    original = copy.deepcopy(dialog.workspace)
    bbox = original["batch"]["interfaces"][0]["regions"][0]["bbox"]
    dialog.comparison["diffs"] = [{"target_type": "region", "target_id": "open", "field": "bbox", "baseline": bbox, "current": bbox, "proposed": [bbox[0] + 1, *bbox[1:]]}]
    seen = []
    def inspect():
        modal = application.activeModalWidget()
        if isinstance(modal, QDialog):
            widget = modal.findChild(GeometryComparisonWidget)
            seen.append(widget.region_selector.count() if widget else -1)
            modal.close()
    try:
        dialog._controls()
        assert dialog.geometry_button.isEnabled()
        QTimer.singleShot(0, inspect)
        QTest.mouseClick(dialog.geometry_button, Qt.MouseButton.LeftButton)
        assert seen == [1]
        assert dialog.workspace == original
    finally:
        dialog.close(); application.processEvents()


def test_local_decision_view_from_other_task_is_rejected_without_replacing_state():
    application, facade, dialog = _compared()
    previous = copy.deepcopy(dialog.review)
    bad = copy.deepcopy(facade.view)
    decision = _receipt(dialog)
    decision["task_id"] = "another-task"
    bad.update(decision_revision=1, candidate_decisions=[decision])
    facade.load_relearn_review = lambda *_: bad
    try:
        dialog.refresh()
        _wait(lambda: not dialog._jobs)
        assert dialog.review == previous
    finally:
        dialog.close(); application.processEvents()


def test_known_local_rejection_blocks_adoption_even_if_comparison_says_current():
    application, _, dialog = _compared()
    try:
        dialog.review["candidate_decisions"] = [_receipt(dialog)]
        dialog._controls()
        assert not dialog.adopt_button.isEnabled()
    finally:
        dialog.close(); application.processEvents()


def test_real_native_geometry_and_rejection_persist_without_changing_workspace(tmp_path):
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.desktop_review.candidate_rejection_dialog import RejectionReasonDialog
    from app.desktop_review.geometry_comparison import GeometryComparisonWidget
    from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
    from app.desktop_review.window import ensure_application
    from test_desktop_review_integration import _synthetic_batch

    application = ensure_application()
    token = "synthetic-native-candidate-decisions"
    state_path, root = tmp_path / "inbox.json", tmp_path / "review-data"
    store = AgentLinkStore(state_path)
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "qa-task", "agent_name": "合成拒绝与框对照验收"})
    service.agent_call(grant["token"], "submit_batch", _synthetic_batch(application))
    facade = NativeReviewFacade(service, token, root)
    dialog = None
    try:
        loaded = facade.load_batch("qa-task", "native-qa-batch")
        saved = facade.save_revision("qa-task", "native-qa-batch", 0, loaded["batch"])
        interface = saved["batch"]["interfaces"][0]
        region = interface["regions"][0]
        bbox = region["bbox"]
        proposed = [bbox[0] + 1, bbox[1], bbox[2] - 1, bbox[3]]
        feedback = facade.request_relearn("qa-task", "native-qa-batch", 1, 0, {"interface_ids": [interface["interface_id"]], "relationship_ids": []}, "复核详情按钮识别框", "native-rejection-question")
        issue = feedback["issues"][0]
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "batch_id": "native-qa-batch",
            "idempotency_key": "native-rejection-candidate", "issue_id": issue["issue_id"],
            "baseline_revision": feedback["feedback_revision"], "scope": issue["scope"],
            "review_baseline_sha256": issue["review_baseline_sha256"],
            "changes": [{"change_type": "geometry", "region_id": region["region_id"], "bbox": proposed}],
        })
        before = service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})
        dialog = module.RelearnReviewDialog(facade, saved)
        dialog.resize(1200, 880); dialog.show()
        _wait(lambda: dialog.review is not None and not dialog._jobs)
        QTest.mouseClick(dialog.tabs.tabBar(), Qt.MouseButton.LeftButton, pos=dialog.tabs.tabBar().tabRect(1).center())
        application.processEvents()
        item = dialog.candidate_table.item(0, 0)
        QTest.mouseClick(dialog.candidate_table.viewport(), Qt.MouseButton.LeftButton, pos=dialog.candidate_table.visualItemRect(item).center())
        QTest.mouseClick(dialog.compare_button, Qt.MouseButton.LeftButton)
        _wait(lambda: dialog.comparison is not None and not dialog._jobs)
        comparison = copy.deepcopy(dialog.comparison)
        out = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
        out.mkdir(parents=True, exist_ok=True)
        geometry_seen = []
        def inspect_geometry():
            modal = application.activeModalWidget()
            if isinstance(modal, QDialog):
                widget = modal.findChild(GeometryComparisonWidget)
                geometry_seen.append((widget.region_selector.currentData(), modal.grab().save(str(out / "native-candidate-geometry.png"))) if widget else None)
                modal.close()
        QTimer.singleShot(0, inspect_geometry)
        QTest.mouseClick(dialog.geometry_button, Qt.MouseButton.LeftButton)
        assert geometry_seen == [(region["region_id"], True)]
        confirmations = []
        reason = "候选框漏掉按钮左缘，请重新核对"
        def answer_rejection(accept):
            prompt = application.activeModalWidget()
            if isinstance(prompt, RejectionReasonDialog):
                confirmations.append(prompt.cancel_button.isDefault())
                prompt.reason_edit.setPlainText(reason)
                QTest.mouseClick(prompt.confirm_button if accept else prompt.cancel_button, Qt.MouseButton.LeftButton)
        QTimer.singleShot(0, lambda: answer_rejection(False))
        QTest.mouseClick(dialog.reject_candidate_button, Qt.MouseButton.LeftButton)
        assert facade.load_relearn_review("qa-task", "native-qa-batch", 1)["decision_revision"] == 0
        QTimer.singleShot(0, lambda: answer_rejection(True))
        QTest.mouseClick(dialog.reject_candidate_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert confirmations == [True, True]
        assert dialog.rejection_receipt is not None, dialog.status.text()
        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.review["decision_revision"] == 1, dialog.status.text()
        assert "已拒绝" in dialog.candidate_table.item(0, 3).text()
        assert facade.load_batch("qa-task", "native-qa-batch") == saved
        assert service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"}) == before
        blocked = facade.compare_relearn_candidate("qa-task", "native-qa-batch", 1, candidate["candidate_id"])
        assert blocked["status"] == "blocked" and "locally_rejected" in blocked["blocked_reasons"]
        with pytest.raises(DesktopReviewError):
            facade.adopt_relearn_candidate("qa-task", "native-qa-batch", 1, candidate["candidate_id"], comparison["candidate_sha256"], comparison["review_baseline_sha256"], "reject-then-adopt")
        assert dialog.grab().save(str(out / "native-candidate-rejected.png"))
        assert facade.list_reviewed_assets() == []
    finally:
        if dialog is not None:
            _wait(lambda: not dialog._jobs)
            dialog.close(); application.processEvents()
        facade.close(); store.close()
    reopened_store = AgentLinkStore(state_path)
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, token), token, root)
    restored_dialog = None
    try:
        assert reopened.load_batch("qa-task", "native-qa-batch") == saved
        restored_dialog = module.RelearnReviewDialog(reopened, saved)
        restored_dialog.show()
        _wait(lambda: restored_dialog.review is not None and not restored_dialog._jobs)
        assert restored_dialog.review["decision_revision"] == 1
        assert "已拒绝" in restored_dialog.candidate_table.item(0, 3).text()
    finally:
        if restored_dialog is not None:
            _wait(lambda: not restored_dialog._jobs)
            restored_dialog.close(); application.processEvents()
        reopened.close(); reopened_store.close()
