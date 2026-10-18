"""原生明确采用的合成控件测试，不操作外部软件。"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from test_desktop_relearn_window import _Facade, _ready, _wait
from app.desktop_review.external_mapping import canonical_json_bytes, normalize_agent_link_batch


def _compared():
    facade = _Facade()
    facade.view["candidates"] = [{"candidate_id": "candidate-1", "issue_id": "issue-1", "status": "pending_review_proposal"}]
    application, facade, dialog = _ready(facade)
    dialog.workspace["contract_version"] = "desktop_review_workspace_v1"
    dialog.workspace["review_status"] = "needs_human_review"
    dialog.workspace["batch"] = normalize_agent_link_batch(dialog.workspace["batch"])
    original_compare = facade.compare_relearn_candidate
    def compare(*args):
        result = original_compare(*args)
        value = dialog.workspace["batch"]["interfaces"][0]["regions"][0]["meaning"]
        result["diffs"][0].update(current=value, baseline=value)
        return result
    facade.compare_relearn_candidate = compare
    dialog.tabs.setCurrentIndex(1)
    dialog.candidate_table.selectRow(0)
    QTest.mouseClick(dialog.compare_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.comparison is not None and not dialog._jobs)
    return application, facade, dialog


def _receipt(dialog):
    snapshot = copy.deepcopy(dialog.workspace)
    snapshot["contract_version"] = "desktop_review_workspace_v2"
    snapshot["revision"] = 2
    snapshot["review_status"] = "needs_human_review"
    snapshot["workflow_review_path"] = "synthetic-new-review.json"
    snapshot["batch"]["interfaces"][0]["regions"][0]["meaning"] = "只读查看文件详情"
    snapshot["parent_revision"] = {"revision": 1, "workspace_path": "desktop-review/workspaces/synthetic/workspace.json", "workspace_sha256": hashlib.sha256(canonical_json_bytes(dialog.workspace) + b"\n").hexdigest(), "workflow_review_sha256": "e" * 64}
    snapshot["relearn_adoption"] = {
        "contract_version": "desktop_relearn_adoption_origin_v1",
        "idempotency_key_sha256": "f" * 64, "request_sha256": "d" * 64,
        "candidate_id": "candidate-1", "candidate_sha256": "b" * 64,
        "issue_id": "issue-1", "review_baseline_sha256": "c" * 64,
        "scope": {"interface_ids": ["one"], "relationship_ids": []},
        "candidate": {}, "issue": {}, "comparison": copy.deepcopy(dialog.comparison),
    }
    return {
        "contract_version": "desktop_relearn_adoption_receipt_v1", "task_id": "task",
        "batch_id": "batch", "source_ref": "a" * 64, "candidate_id": "candidate-1",
        "candidate_sha256": "b" * 64, "review_baseline_sha256": "c" * 64,
        "previous_revision": 1, "adopted_revision": 2, "current_revision": 2,
        "is_current": True, "snapshot": snapshot, "staging_only": True,
    }


def test_native_adoption_cancel_is_default_and_does_not_call_facade(monkeypatch):
    application, facade, dialog = _compared()
    calls, defaults = [], []
    facade.adopt_relearn_candidate = lambda *args: calls.append(args)
    def cancel(*args):
        defaults.append(args[-1])
        return QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(QMessageBox, "question", cancel)
    try:
        assert dialog.adopt_button.isEnabled()
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        assert defaults == [QMessageBox.StandardButton.Cancel]
        assert calls == []
        assert not dialog.requires_workspace_reload
    finally:
        dialog.close(); application.processEvents()


def test_native_adoption_freezes_exact_binding_and_returns_to_review(monkeypatch):
    application, facade, dialog = _compared()
    calls = []
    receipt = _receipt(dialog)
    facade.adopt_relearn_candidate = lambda *args: (calls.append(args), copy.deepcopy(receipt))[1]
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    try:
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert calls[0][:6] == ("task", "batch", 1, "candidate-1", "b" * 64, "c" * 64)
        assert dialog.adoption_receipt == receipt
        assert dialog.workspace["revision"] == 1
        assert dialog.requires_workspace_reload
        assert "待审" in dialog.status.text() and "执行" in dialog.status.text()
        assert not dialog.adopt_button.isEnabled()
        assert not dialog.request_button.isEnabled()
    finally:
        dialog.close(); application.processEvents()


@pytest.mark.parametrize("change", [
    {"status": "stale"}, {"status": "withdrawn"}, {"blocked_reasons": ["dangerous_action"]},
    {"candidate_sha256": "not-a-hash"}, {"review_baseline_sha256": None},
])
def test_invalid_comparison_cannot_enable_adoption(change):
    application, _, dialog = _compared()
    try:
        dialog.comparison.update(change)
        dialog._controls()
        assert not dialog.adopt_button.isEnabled()
    finally:
        dialog.close(); application.processEvents()


def test_candidate_selection_or_new_question_disables_adoption():
    application, _, dialog = _compared()
    try:
        dialog.message.setPlainText("尚未提交的新问题")
        assert not dialog.adopt_button.isEnabled()
        dialog.message.clear()
        dialog.candidate_table.clearSelection()
        assert not dialog.adopt_button.isEnabled()
    finally:
        dialog.close(); application.processEvents()


@pytest.mark.parametrize("mutation", ["current", "baseline", "duplicate", "unknown_target", "unknown_field"])
def test_adoption_requires_diffs_bound_to_actual_saved_fields(mutation):
    application, _, dialog = _compared()
    try:
        diff = dialog.comparison["diffs"][0]
        if mutation in {"current", "baseline"}:
            diff[mutation] = "与固定版本不同的伪值"
        elif mutation == "duplicate":
            dialog.comparison["diffs"].append(copy.deepcopy(diff))
        elif mutation == "unknown_target":
            diff["target_id"] = "missing-region"
        else:
            diff["field"] = "authority"
        dialog._controls()
        assert not dialog.adopt_button.isEnabled()
    finally:
        dialog.close(); application.processEvents()


@pytest.mark.parametrize("mutation", ["wrong_candidate", "unexpected_edit", "approved", "bool_revision", "missing_parent", "missing_origin", "wrong_parent", "wrong_origin", "legacy_child"])
def test_invalid_adoption_receipt_preserves_comparison_and_retry_key(monkeypatch, mutation):
    application, facade, dialog = _compared()
    valid, calls = _receipt(dialog), []
    malformed = copy.deepcopy(valid)
    if mutation == "wrong_candidate":
        malformed["candidate_sha256"] = "d" * 64
    elif mutation == "unexpected_edit":
        malformed["snapshot"]["batch"]["title"] = "未授权的更改"
    elif mutation == "approved":
        malformed["snapshot"]["review_status"] = "approved"
    elif mutation == "bool_revision":
        malformed["previous_revision"] = True
    elif mutation == "missing_parent":
        malformed["snapshot"].pop("parent_revision")
    elif mutation == "missing_origin":
        malformed["snapshot"].pop("relearn_adoption")
    elif mutation == "wrong_parent":
        malformed["snapshot"]["parent_revision"]["workspace_sha256"] = "0" * 64
    elif mutation == "wrong_origin":
        malformed["snapshot"]["relearn_adoption"]["comparison"]["candidate_sha256"] = "0" * 64
    else:
        malformed["snapshot"]["contract_version"] = "desktop_review_workspace_v1"
        malformed["snapshot"].pop("parent_revision")
        malformed["snapshot"].pop("relearn_adoption")
    facade.adopt_relearn_candidate = lambda *args: (calls.append(args), copy.deepcopy(malformed))[1]
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    try:
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.adoption_receipt is None
        assert dialog.comparison is not None
        assert dialog.requires_workspace_reload
        assert not dialog.refresh_button.isEnabled()
        facade.adopt_relearn_candidate = lambda *args: (calls.append(args), copy.deepcopy(valid))[1]
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert calls[0] == calls[1]
        assert dialog.adoption_receipt == valid
    finally:
        dialog.close(); application.processEvents()


def test_recovered_historical_receipt_never_replaces_later_workspace(monkeypatch):
    application, facade, dialog = _compared()
    receipt = {**_receipt(dialog), "current_revision": 3, "is_current": False}
    facade.adopt_relearn_candidate = lambda *_: receipt
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    try:
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.adoption_receipt == receipt
        assert dialog.workspace["revision"] == 1
        assert "后续" in dialog.status.text()
        assert dialog.requires_workspace_reload
    finally:
        dialog.close(); application.processEvents()


def test_legacy_workspace_can_receive_versioned_adoption_receipt(monkeypatch):
    application, facade, dialog = _compared()
    receipt = _receipt(dialog)
    receipt["snapshot"]["contract_version"] = "desktop_review_workspace_v2"
    facade.adopt_relearn_candidate = lambda *_: receipt
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    try:
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.adoption_receipt == receipt
    finally:
        dialog.close(); application.processEvents()


def test_main_window_reloads_current_after_any_adoption_attempt(monkeypatch):
    from app.desktop_review import window as module
    from test_desktop_exact_review_window import _workspace
    from test_desktop_review_window import _Facade as WindowFacade
    application = module.ensure_application()
    window = module.ReviewMainWindow(WindowFacade())
    _wait(lambda: not window._jobs)
    loaded = []
    class Dialog:
        requires_workspace_reload = True
        def __init__(self, *args):
            pass
        def setObjectName(self, name):
            pass
        def exec(self):
            return 0
    monkeypatch.setattr(module, "RelearnReviewDialog", Dialog)
    monkeypatch.setattr(module.ReviewMainWindow, "load_batch", lambda self, *args: loaded.append(args))
    try:
        window._workspace = _workspace()
        window.open_relearn_review()
        assert loaded == [("task", "batch")]
    finally:
        window.close(); application.processEvents()


def test_real_native_candidate_adoption_creates_pending_revision_and_reloads(tmp_path):
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.desktop_review.relearn_dialog import RelearnReviewDialog
    from app.desktop_review.window import ReviewMainWindow, ensure_application
    from app.desktop_review.workspace import NativeReviewFacade
    from test_desktop_review_integration import _synthetic_batch

    application = ensure_application()
    token = "synthetic-native-adoption-reviewer"
    state_path, root = tmp_path / "inbox.json", tmp_path / "review-data"
    store = AgentLinkStore(state_path)
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "qa-task", "agent_name": "合成候选验收"})
    service.agent_call(grant["token"], "submit_batch", _synthetic_batch(application))
    facade = NativeReviewFacade(service, token, root)
    dialog = window = None
    try:
        loaded = facade.load_batch("qa-task", "native-qa-batch")
        saved = facade.save_revision("qa-task", "native-qa-batch", 0, loaded["batch"])
        feedback = facade.request_relearn("qa-task", "native-qa-batch", 1, 0, {"interface_ids": [saved["batch"]["interfaces"][0]["interface_id"]], "relationship_ids": []}, "复核详情按钮含义", "native-adoption-question")
        issue = feedback["issues"][0]
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "batch_id": "native-qa-batch",
            "idempotency_key": "native-adoption-candidate", "issue_id": issue["issue_id"],
            "baseline_revision": feedback["feedback_revision"], "scope": issue["scope"],
            "review_baseline_sha256": issue["review_baseline_sha256"],
            "changes": [{"change_type": "semantic", "target_type": "region", "target_id": "details-button", "meaning": "候选修订：只读打开文件详情"}],
        })
        before = service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})
        dialog = RelearnReviewDialog(facade, saved)
        dialog.resize(1200, 880); dialog.show()
        _wait(lambda: dialog.review is not None and not dialog._jobs)
        QTest.mouseClick(dialog.tabs.tabBar(), Qt.MouseButton.LeftButton, pos=dialog.tabs.tabBar().tabRect(1).center())
        application.processEvents()
        item = dialog.candidate_table.item(0, 0)
        QTest.mouseClick(dialog.candidate_table.viewport(), Qt.MouseButton.LeftButton, pos=dialog.candidate_table.visualItemRect(item).center())
        QTest.mouseClick(dialog.compare_button, Qt.MouseButton.LeftButton)
        _wait(lambda: dialog.comparison is not None and not dialog._jobs)
        confirmations = []
        def confirm_native():
            box = application.activeModalWidget()
            if isinstance(box, QMessageBox):
                confirmations.append(box.defaultButton() == box.button(QMessageBox.StandardButton.Cancel))
                QTest.mouseClick(box.button(QMessageBox.StandardButton.Yes), Qt.MouseButton.LeftButton)
        QTimer.singleShot(0, confirm_native)
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert confirmations == [True]
        assert dialog.adoption_receipt is not None, dialog.status.text()
        assert dialog.adoption_receipt["candidate_id"] == candidate["candidate_id"]
        adopted = facade.load_batch("qa-task", "native-qa-batch")
        assert adopted["revision"] == 2 and adopted["review_status"] == "needs_human_review"
        assert adopted["batch"]["interfaces"][0]["regions"][0]["meaning"] == "候选修订：只读打开文件详情"
        assert service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"}) == before
        assert facade.list_reviewed_assets() == []
        out = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
        out.mkdir(parents=True, exist_ok=True)
        assert dialog.grab().save(str(out / "native-relearn-adopted.png"))
        dialog.close(); application.processEvents()
        window = ReviewMainWindow(facade)
        _wait(lambda: not window._jobs)
        window.load_batch("qa-task", "native-qa-batch")
        _wait(lambda: window._workspace is not None and not window._jobs)
        assert window._workspace == adopted
    finally:
        for widget in (dialog, window):
            if widget is not None:
                _wait(lambda: not widget._jobs)
                widget.close(); application.processEvents()
        facade.close(); store.close()
    reopened_store = AgentLinkStore(state_path)
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, token), token, root)
    try:
        assert reopened.load_batch("qa-task", "native-qa-batch") == adopted
    finally:
        reopened.close(); reopened_store.close()
