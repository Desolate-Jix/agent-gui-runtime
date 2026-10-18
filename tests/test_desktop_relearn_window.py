"""合成 Qt 重学审核测试，不连接真实 Agent 或执行外部操作。"""
from __future__ import annotations

import copy
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QMessageBox

from app.desktop_review.relearn_dialog import RelearnReviewDialog
from app.desktop_review.window import ReviewMainWindow, ensure_application
from test_desktop_exact_review_window import _workspace
from test_desktop_review_window import _Facade as _WindowFacade


def _wait(predicate):
    application = ensure_application()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        time.sleep(0.01)
        application.processEvents()
        if predicate():
            return
    raise AssertionError("native relearn response not rendered")


class _Facade:
    def __init__(self):
        self.view = {
            "contract_version": "desktop_relearn_review_v1", "task_id": "task",
            "batch_id": "batch", "source_ref": "a" * 64, "workspace_revision": 1,
            "feedback_revision": 0, "issues": [], "candidates": [], "staging_only": True,
        }
        self.requests = []
        self.fail = False

    def load_relearn_review(self, *args):
        return copy.deepcopy(self.view)

    def request_relearn(self, *args):
        self.requests.append(copy.deepcopy(args))
        if self.fail:
            raise ValueError("合成保存故障")
        self.view["feedback_revision"] = 1
        self.view["issues"] = [{"issue_id": "issue-1", "scope": args[4], "message": args[5], "status": "open", "baseline_revision": 1}]
        return copy.deepcopy(self.view)

    def withdraw_relearn(self, *args):
        self.view["feedback_revision"] += 1
        self.view["issues"][0]["status"] = "withdrawn"
        return copy.deepcopy(self.view)

    def compare_relearn_candidate(self, *args):
        return {
            **{key: self.view[key] for key in ("task_id", "batch_id", "source_ref", "workspace_revision")},
            "contract_version": "desktop_relearn_comparison_v1", "candidate_id": args[3],
            "candidate_sha256": "b" * 64, "issue_id": "issue-1",
            "review_baseline_sha256": "c" * 64, "baseline_workspace_revision": 1,
            "status": "current", "blocked_reasons": [],
            "diffs": [{"target_type": "region", "target_id": "open", "field": "meaning", "baseline": "查看详情", "current": "人工检查详情", "proposed": "只读查看文件详情"}],
        }


def _ready(facade=None):
    application = ensure_application()
    facade = facade or _Facade()
    dialog = RelearnReviewDialog(facade, _workspace())
    dialog.show()
    _wait(lambda: dialog.review is not None and not dialog._jobs)
    return application, facade, dialog


def _draft(dialog):
    dialog.scope_list.item(0).setCheckState(Qt.CheckState.Checked)
    dialog.message.setPlainText("请复核这个界面的识别框与步骤含义")


def test_native_issue_submission_and_candidate_comparison_are_explicit_readonly():
    application, facade, dialog = _ready()
    assert dialog.scope_list.item(0).checkState() == Qt.CheckState.Unchecked
    assert not dialog.request_button.isEnabled()
    _draft(dialog)
    QTest.mouseClick(dialog.request_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.review["feedback_revision"] == 1 and not dialog._jobs)
    assert facade.requests[0][0:4] == ("task", "batch", 1, 0)
    assert facade.requests[0][4] == {"interface_ids": ["one"], "relationship_ids": []}
    assert not dialog.message.toPlainText()
    assert dialog.issue_table.rowCount() == 1
    facade.view["candidates"] = [{"candidate_id": "candidate-1", "issue_id": "issue-1", "status": "pending_review_proposal"}]
    QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.candidate_table.rowCount() == 1 and not dialog._jobs)
    dialog.candidate_table.selectRow(0)
    QTest.mouseClick(dialog.compare_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.comparison is not None and not dialog._jobs)
    assert dialog.diff_table.item(0, 2).text() == "查看详情"
    assert dialog.diff_table.item(0, 3).text() == "人工检查详情"
    assert dialog.diff_table.item(0, 4).text() == "只读查看文件详情"
    assert "candidate_sha256" in dialog.detail.toPlainText()
    assert "只读" in dialog.status.text()
    dialog.close(); application.processEvents()


def test_failed_request_keeps_draft_and_reuses_same_idempotency_key():
    application, facade, dialog = _ready()
    _draft(dialog)
    facade.fail = True
    QTest.mouseClick(dialog.request_button, Qt.MouseButton.LeftButton)
    _wait(lambda: len(facade.requests) == 1 and not dialog._jobs)
    assert "合成保存故障" in dialog.status.text()
    assert dialog.message.toPlainText().startswith("请复核")
    facade.fail = False
    QTest.mouseClick(dialog.request_button, Qt.MouseButton.LeftButton)
    _wait(lambda: dialog.review["feedback_revision"] == 1 and not dialog._jobs)
    assert facade.requests[0] == facade.requests[1]
    dialog.close(); application.processEvents()


def test_current_malformed_response_unlocks_without_discarding_draft():
    application, facade, dialog = _ready()
    _draft(dialog)
    facade.load_relearn_review = lambda *_: None
    QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
    _wait(lambda: not dialog._jobs)
    assert not dialog._busy
    assert dialog.message.toPlainText().startswith("请复核")
    assert "格式" in dialog.status.text() or "身份" in dialog.status.text()
    dialog.message.clear(); dialog.scope_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    dialog.close(); application.processEvents()


def test_wrong_comparison_identity_is_rejected_without_showing_proposal():
    application, facade, dialog = _ready()
    facade.view["candidates"] = [{"candidate_id": "candidate-1", "issue_id": "issue-1", "status": "pending_review_proposal"}]
    dialog.refresh()
    _wait(lambda: dialog.candidate_table.rowCount() == 1 and not dialog._jobs)
    original = facade.compare_relearn_candidate
    facade.compare_relearn_candidate = lambda *args: {**original(*args), "candidate_id": "other"}
    dialog.candidate_table.selectRow(0); dialog.compare_candidate()
    _wait(lambda: not dialog._jobs)
    assert dialog.comparison is None
    assert dialog.diff_table.rowCount() == 0
    assert "身份" in dialog.status.text()
    dialog.close(); application.processEvents()


def test_dirty_close_paths_default_to_cancel_and_busy_never_closes(monkeypatch):
    application, facade, dialog = _ready()
    _draft(dialog)
    defaults = []
    def cancel(*args):
        defaults.append(args[-1])
        return QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(QMessageBox, "question", cancel)
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    dialog.reject(); dialog.done(QDialog.DialogCode.Rejected); dialog.close()
    assert dialog.isVisible()
    assert defaults == [QMessageBox.StandardButton.Cancel] * 4
    started, release = threading.Event(), threading.Event()
    def delayed(*_):
        started.set()
        release.wait(5)
        return copy.deepcopy(facade.view)
    facade.load_relearn_review = delayed
    dialog.refresh()
    _wait(started.is_set)
    try:
        dialog.close(); dialog.reject(); dialog.done(QDialog.DialogCode.Rejected)
        assert dialog.isVisible()
    finally:
        release.set()
    _wait(lambda: not dialog._jobs)
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Discard)
    dialog.close(); application.processEvents()
    assert not dialog.isVisible()


def test_main_window_relearn_entry_requires_clean_saved_revision(monkeypatch):
    from app.desktop_review import window as module
    application = ensure_application()
    window = ReviewMainWindow(_WindowFacade())
    opened = []
    class Dialog:
        def __init__(self, facade, workspace, parent):
            opened.append(copy.deepcopy(workspace))
        def setObjectName(self, value):
            pass
        def exec(self):
            return 0
    monkeypatch.setattr(module, "RelearnReviewDialog", Dialog)
    _wait(lambda: not window._jobs)
    window.open_relearn_review()
    assert not opened
    window._workspace = _workspace()
    window._dirty = True
    window.open_relearn_review()
    assert not opened
    window._dirty = False
    window.open_relearn_review()
    assert len(opened) == 1
    window.close(); application.processEvents()


def test_feedback_response_without_recorded_question_does_not_clear_draft():
    application, facade, dialog = _ready()
    _draft(dialog)
    facade.request_relearn = lambda *_: {**facade.view, "feedback_revision": 1}
    dialog.request_relearn()
    _wait(lambda: not dialog._jobs)
    assert dialog.message.toPlainText().startswith("请复核")
    assert dialog.review["feedback_revision"] == 0
    dialog.message.clear(); dialog.scope_list.item(0).setCheckState(Qt.CheckState.Unchecked)
    dialog.close(); application.processEvents()


def test_withdrawal_needs_separate_confirmation_and_modal_close_exits(monkeypatch):
    application, facade, dialog = _ready()
    _draft(dialog); dialog.request_relearn()
    _wait(lambda: dialog.review["feedback_revision"] == 1 and not dialog._jobs)
    dialog.issue_table.selectRow(0)
    defaults = []
    def cancel(*args):
        defaults.append(args[-1])
        return QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(QMessageBox, "question", cancel)
    dialog.withdraw_issue()
    assert facade.view["feedback_revision"] == 1
    assert defaults == [QMessageBox.StandardButton.Cancel]
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.StandardButton.Yes)
    dialog.withdraw_issue()
    _wait(lambda: dialog.review["feedback_revision"] == 2 and not dialog._jobs)
    assert dialog.issue_table.item(0, 1).text() == "withdrawn"
    emergency = []
    timer = QTimer(dialog)
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (emergency.append(True), dialog.done(QDialog.DialogCode.Rejected)))
    timer.start(1000)
    QTimer.singleShot(0, dialog.close)
    assert dialog.exec() == QDialog.DialogCode.Rejected
    timer.stop()
    assert not emergency


def test_real_native_relearn_roundtrip_compares_without_mutating_saved_revision(tmp_path):
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.agent_link.contracts import canonical_hash
    from app.desktop_review.workspace import NativeReviewFacade
    from test_desktop_review_integration import _synthetic_batch

    application = ensure_application()
    token = "synthetic-native-relearn-reviewer"
    state_path, root = tmp_path / "inbox.json", tmp_path / "review-data"
    store = AgentLinkStore(state_path)
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "qa-task", "agent_name": "合成协议验收，不是真实 Agent"})
    service.agent_call(grant["token"], "submit_batch", _synthetic_batch(application))
    facade = NativeReviewFacade(service, token, root)
    dialog = None
    try:
        original = copy.deepcopy(service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})["batch"])
        loaded = facade.load_batch("qa-task", "native-qa-batch")
        edited = copy.deepcopy(loaded["batch"])
        edited["interfaces"][0]["regions"][0]["meaning"] = "人工基线：只查看所选文件详情"
        saved = facade.save_revision("qa-task", "native-qa-batch", 0, edited)
        dialog = RelearnReviewDialog(facade, saved)
        dialog.resize(1200, 880)
        dialog.show()
        _wait(lambda: dialog.review is not None and not dialog._jobs)
        dialog.scope_list.item(0).setCheckState(Qt.CheckState.Checked)
        dialog.message.setPlainText("复核详情按钮的含义，保留我已保存的其他修改")
        QTest.mouseClick(dialog.request_button, Qt.MouseButton.LeftButton)
        _wait(lambda: dialog.review["feedback_revision"] == 1 and not dialog._jobs)
        feedback = service.agent_call(grant["token"], "read_feedback", {"batch_id": "native-qa-batch"})
        issue = feedback["issues"][0]
        baseline = issue["review_baseline"]
        assert baseline["workspace_revision"] == 1
        assert baseline["batch"]["interfaces"][0]["regions"][0]["meaning"] == "人工基线：只查看所选文件详情"
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "batch_id": "native-qa-batch",
            "idempotency_key": "synthetic-relearn-candidate", "issue_id": issue["issue_id"],
            "baseline_revision": feedback["revision"], "scope": issue["scope"],
            "review_baseline_sha256": canonical_hash(baseline),
            "changes": [{"change_type": "semantic", "target_type": "region", "target_id": "details-button", "meaning": "Agent 候选：打开详情抽屉，不修改文件"}],
        })
        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        _wait(lambda: dialog.candidate_table.rowCount() == 1 and not dialog._jobs)
        QTest.mouseClick(dialog.tabs.tabBar(), Qt.MouseButton.LeftButton, pos=dialog.tabs.tabBar().tabRect(1).center())
        application.processEvents()
        item = dialog.candidate_table.item(0, 0)
        QTest.mouseClick(dialog.candidate_table.viewport(), Qt.MouseButton.LeftButton, pos=dialog.candidate_table.visualItemRect(item).center())
        QTest.mouseClick(dialog.compare_button, Qt.MouseButton.LeftButton)
        _wait(lambda: dialog.comparison is not None and not dialog._jobs)
        comparison = copy.deepcopy(dialog.comparison)
        assert comparison["candidate_id"] == candidate["candidate_id"]
        assert comparison["status"] == "current"
        assert dialog.diff_table.item(0, 2).text() == "人工基线：只查看所选文件详情"
        assert dialog.diff_table.item(0, 3).text() == "人工基线：只查看所选文件详情"
        assert dialog.diff_table.item(0, 4).text() == "Agent 候选：打开详情抽屉，不修改文件"
        assert facade.load_batch("qa-task", "native-qa-batch") == saved
        assert service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})["batch"] == original
        assert facade.list_reviewed_assets() == []
        out = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
        out.mkdir(parents=True, exist_ok=True)
        assert dialog.grab().save(str(out / "native-relearn-comparison.png"))
    finally:
        if dialog is not None:
            _wait(lambda: not dialog._jobs)
            dialog.message.clear()
            for index in range(dialog.scope_list.count()):
                dialog.scope_list.item(index).setCheckState(Qt.CheckState.Unchecked)
            dialog.close(); application.processEvents()
        facade.close(); store.close()
    reloaded_store = AgentLinkStore(state_path)
    reloaded_service = AgentLinkService(reloaded_store, token)
    reloaded = NativeReviewFacade(reloaded_service, token, root)
    try:
        assert reloaded.compare_relearn_candidate("qa-task", "native-qa-batch", 1, candidate["candidate_id"]) == comparison
        assert reloaded.load_batch("qa-task", "native-qa-batch") == saved
    finally:
        reloaded.close(); reloaded_store.close()
