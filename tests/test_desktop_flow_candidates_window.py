"""完整流程候选与原生步骤顺序的控件回归。"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from app.desktop_review.window import ReviewMainWindow, ensure_application
from test_desktop_review_window import _Facade, _batch, _wait_loaded, _wait_workers


def _ordered_window():
    application = ensure_application()
    batch = _batch()
    original = batch["steps"][0]
    batch["steps"] = [{**copy.deepcopy(original), "step_id": f"step-{index}"} for index in (1, 2, 3)]
    facade = _Facade([batch])
    window = ReviewMainWindow(facade)
    window.show()
    window.load_batch("task-1", "batch-1")
    _wait_loaded(window); _wait_workers(window)
    window.step_table.selectRow(0)
    application.processEvents()
    return application, facade, window


def _close(application, window):
    _wait_workers(window)
    window._dirty = False
    window.close(); application.processEvents()


def _ids(window):
    return [step["step_id"] for step in window.workspace["batch"]["steps"]]


def test_native_step_order_buttons_preserve_selected_identity_and_pending_fields():
    application, facade, window = _ordered_window()
    try:
        window.step_expected.setPlainText("顺序变更前刚输入的预期结果")
        QTest.mouseClick(window.step_down_button, Qt.MouseButton.LeftButton)
        assert _ids(window) == ["step-2", "step-1", "step-3"]
        assert window._selected_step_id == "step-1"
        assert window.step_table.currentRow() == 1
        assert window.workspace["batch"]["steps"][1]["expected_result"] == "顺序变更前刚输入的预期结果"
        assert window._dirty
        assert facade.saved == []
        QTest.mouseClick(window.step_up_button, Qt.MouseButton.LeftButton)
        assert _ids(window) == ["step-1", "step-2", "step-3"]
        assert window._selected_step_id == "step-1"
    finally:
        _close(application, window)


def test_native_step_order_buttons_disable_at_boundaries_and_during_busy():
    application, _, window = _ordered_window()
    try:
        assert not window.step_up_button.isEnabled()
        assert window.step_down_button.isEnabled()
        window.step_table.selectRow(2)
        assert window.step_up_button.isEnabled()
        assert not window.step_down_button.isEnabled()
        original = _ids(window)
        window._operation = "saving"
        window._set_busy(True)
        assert not window.step_up_button.isEnabled()
        window.move_selected_step(-1)
        assert _ids(window) == original
    finally:
        window._operation = "idle"
        _close(application, window)


@pytest.mark.parametrize("field", ["step_start", "step_arrival", "step_action"])
def test_invalid_flow_draft_blocks_reorder_and_preserves_input(field):
    application, _, window = _ordered_window()
    try:
        edit = getattr(window, field)
        edit.setText("" if field == "step_action" else "missing-interface")
        assert not window.step_down_button.isEnabled()
        window.move_selected_step(1)
        assert _ids(window) == ["step-1", "step-2", "step-3"]
        assert edit.text() == ("" if field == "step_action" else "missing-interface")
    finally:
        _close(application, window)


def _flow_comparison_dialog():
    from test_desktop_relearn_adoption_window import _compared
    application, facade, dialog = _compared()
    batch = dialog.workspace["batch"]
    first, last = batch["interfaces"][0], batch["interfaces"][-1]
    template = {
        "action_type": "open_detail", "target_region_id": first["regions"][0]["region_id"],
        "start_state": first["interface_id"], "arrival_state": first["interface_id"],
        "prerequisites": [], "expected_result": "原预期", "stop_condition": "原停止条件",
    }
    batch["steps"] = [{"step_id": name, **copy.deepcopy(template)} for name in ("alpha", "beta", "gamma")]
    relation = {"relationship_id": "relation", "from_interface_id": first["interface_id"],
                "to_interface_id": last["interface_id"], "kind": "原关联"}
    batch["relationships"] = [relation]
    changed = {"action_type": "safe_stop", "target_region_id": None,
               "start_state": last["interface_id"], "arrival_state": last["interface_id"],
               "prerequisites": ["当前界面已经审核"], "expected_result": "只观察停止边界", "stop_condition": "不再执行下一步"}
    diffs = [{"target_type": "step", "target_id": "alpha", "field": field,
              "baseline": template[field], "current": template[field], "proposed": value}
             for field, value in changed.items()]
    diffs.extend({"target_type": "relationship", "target_id": "relation", "field": field,
                  "baseline": relation[field], "current": relation[field], "proposed": value}
                 for field, value in {"from_interface_id": last["interface_id"], "to_interface_id": first["interface_id"], "kind": "返回关联"}.items())
    diffs.append({"target_type": "batch", "target_id": batch["batch_id"], "field": "step_order",
                  "baseline": ["alpha", "beta", "gamma"], "current": ["alpha", "beta", "gamma"], "proposed": ["gamma", "beta", "alpha"]})
    dialog.comparison["diffs"] = diffs
    return application, facade, dialog


def test_native_flow_comparison_projects_all_fields_and_full_order_without_writes():
    application, _, dialog = _flow_comparison_dialog()
    original = copy.deepcopy(dialog.workspace)
    try:
        projected = dialog._project_comparison(dialog.comparison)
        assert projected is not None
        assert [step["step_id"] for step in projected["steps"]] == ["gamma", "beta", "alpha"]
        assert projected["steps"][-1]["target_region_id"] is None
        assert projected["steps"][-1]["prerequisites"] == ["当前界面已经审核"]
        assert projected["relationships"][0]["kind"] == "返回关联"
        assert dialog.workspace == original
    finally:
        dialog.close(); application.processEvents()


@pytest.mark.parametrize("order", [["alpha", "alpha", "gamma"], ["alpha"], ["alpha", "beta", "other"], [True, "beta", "gamma"]])
def test_native_flow_projection_rejects_changed_stable_step_identity(order):
    application, _, dialog = _flow_comparison_dialog()
    try:
        dialog.comparison["diffs"][-1]["proposed"] = order
        assert dialog._project_comparison(dialog.comparison) is None
    finally:
        dialog.close(); application.processEvents()


def _real_flow_batch(application):
    from test_desktop_review_integration import _synthetic_batch
    batch = _synthetic_batch(application)
    other = copy.deepcopy(batch["interfaces"][0])
    other.update(interface_id="file-list-checked", meaning="同一列表的另一合成审核状态")
    other["regions"][0]["region_id"] = "checked-details-button"
    batch["interfaces"].append(other)
    batch["relationships"] = [{"relationship_id": "list-checked", "from_interface_id": "file-list",
                               "to_interface_id": "file-list-checked", "kind": "人工复核前后"}]
    template = batch["steps"][0]
    batch["steps"] = [{**copy.deepcopy(template), "step_id": identifier} for identifier in ("first", "second", "third")]
    return batch


def test_real_native_flow_edit_reorder_save_and_reopen(tmp_path):
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.desktop_review.workspace import NativeReviewFacade
    application = ensure_application()
    token = "synthetic-flow-direct-reviewer"
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "qa-task", "agent_name": "合成流程编辑验收"})
    service.agent_call(grant["token"], "submit_batch", _real_flow_batch(application))
    before = service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})
    facade = NativeReviewFacade(service, token, tmp_path / "review-data")
    window = ReviewMainWindow(facade)
    window.resize(1500, 1100); window.show()
    window.load_batch("qa-task", "native-qa-batch")
    try:
        _wait_loaded(window); _wait_workers(window)
        window.step_table.selectRow(0)
        window.step_arrival.setText("file-list-checked")
        window.step_prerequisites.setPlainText("界面可见\n当前文件已核对")
        window.relationship_table.selectRow(0)
        window.relationship_from.setText("file-list-checked")
        window.relationship_to.setText("file-list")
        window.relationship_kind.setText("返回原审核状态")
        QTest.mouseClick(window.step_down_button, Qt.MouseButton.LeftButton)
        assert _ids(window) == ["second", "first", "third"]
        window.save_current(); _wait_workers(window)
        assert window.workspace["revision"] == 1, window.status.currentMessage()
        saved = facade.load_batch("qa-task", "native-qa-batch")
        assert saved == window.workspace
        assert saved["batch"]["steps"][1]["arrival_state"] == "file-list-checked"
        assert saved["batch"]["steps"][1]["prerequisites"] == ["界面可见", "当前文件已核对"]
        assert saved["batch"]["relationships"][0]["from_interface_id"] == "file-list-checked"
        assert saved["batch"]["relationships"][0]["to_interface_id"] == "file-list"
        assert service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"}) == before
        assert facade.list_reviewed_assets() == []
        out = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
        out.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(out / "native-flow-direct-edited.png"))
    finally:
        _close(application, window); store.close()
    reopened_store = AgentLinkStore(tmp_path / "inbox.json")
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, token), token, tmp_path / "review-data")
    try:
        assert reopened.load_batch("qa-task", "native-qa-batch") == saved
    finally:
        reopened.close(); reopened_store.close()


def test_real_native_full_flow_candidate_compare_adopt_and_restart(tmp_path):
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.desktop_review.relearn_dialog import RelearnReviewDialog
    from app.desktop_review.workspace import NativeReviewFacade
    from test_desktop_relearn_window import _wait
    application = ensure_application()
    token = "synthetic-full-flow-reviewer"
    state, root = tmp_path / "inbox.json", tmp_path / "review-data"
    store = AgentLinkStore(state)
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "qa-task", "agent_name": "合成完整流程候选"})
    service.agent_call(grant["token"], "submit_batch", _real_flow_batch(application))
    facade = NativeReviewFacade(service, token, root)
    dialog = None
    try:
        loaded = facade.load_batch("qa-task", "native-qa-batch")
        saved = facade.save_revision("qa-task", "native-qa-batch", 0, loaded["batch"])
        dialog = RelearnReviewDialog(facade, saved)
        dialog.resize(1400, 950); dialog.show()
        _wait(lambda: dialog.review is not None and not dialog._jobs)
        for index in range(dialog.scope_list.count()):
            dialog.scope_list.item(index).setCheckState(Qt.CheckState.Checked)
        dialog.message.setPlainText("复核整个流程的起点、到达状态、前置条件、停止边界与审核顺序")
        QTest.mouseClick(dialog.request_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert not dialog.message.toPlainText(), dialog.status.text()
        feedback = service.agent_call(grant["token"], "read_feedback", {"batch_id": "native-qa-batch"})
        issue = feedback["issues"][0]
        flow = {"change_type": "step_flow", "step_id": "first", "action_type": "safe_stop", "target_region_id": None,
                "start_state": "file-list-checked", "arrival_state": "file-list", "prerequisites": ["两个状态均已核对"],
                "expected_result": "只检查返回关系并停止", "stop_condition": "不继续执行任何外部步骤"}
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "batch_id": "native-qa-batch", "idempotency_key": "native-full-flow",
            "issue_id": issue["issue_id"], "baseline_revision": issue["baseline_revision"], "scope": issue["scope"],
            "review_baseline_sha256": issue["review_baseline_sha256"], "changes": [flow,
                {"change_type": "relationship_flow", "relationship_id": "list-checked", "from_interface_id": "file-list-checked", "to_interface_id": "file-list", "kind": "返回原审核状态"},
                {"change_type": "step_order", "step_ids": ["third", "second", "first"]}],
        })
        inbox_before = service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})
        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        QTest.mouseClick(dialog.tabs.tabBar(), Qt.MouseButton.LeftButton, pos=dialog.tabs.tabBar().tabRect(1).center())
        application.processEvents()
        row = dialog.candidate_table.item(0, 0)
        QTest.mouseClick(dialog.candidate_table.viewport(), Qt.MouseButton.LeftButton, pos=dialog.candidate_table.visualItemRect(row).center())
        assert dialog.compare_button.isEnabled(), dialog.status.text()
        QTest.mouseClick(dialog.compare_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.comparison is not None, dialog.status.text()
        assert dialog.comparison["status"] == "current", dialog.status.text()
        assert dialog.diff_table.rowCount() == 11
        labels = {dialog.diff_table.item(index, 1).text() for index in range(11)}
        assert {"起始界面", "到达界面", "前置条件", "停止条件", "步骤审核顺序"} <= labels
        expected = dialog._project_comparison(dialog.comparison)
        out = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
        out.mkdir(parents=True, exist_ok=True)
        application.processEvents()
        assert dialog.grab().save(str(out / "native-full-flow-comparison.png"))
        dialog.diff_table.setFocus()
        dialog.diff_table.setCurrentCell(0, 4)
        QTest.keyClick(dialog.diff_table, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
        application.processEvents()
        assert dialog.diff_table.currentRow() == 10
        order_item = dialog.diff_table.item(10, 4)
        assert dialog.diff_table.viewport().rect().contains(dialog.diff_table.visualItemRect(order_item).center())
        assert order_item.text() == '["third", "second", "first"]'
        assert dialog.grab().save(str(out / "native-full-flow-order.png"))
        confirmations = []
        def accept():
            prompt = application.activeModalWidget()
            if isinstance(prompt, QMessageBox):
                confirmations.append(prompt.defaultButton() == prompt.button(QMessageBox.StandardButton.Cancel))
                QTest.mouseClick(prompt.button(QMessageBox.StandardButton.Yes), Qt.MouseButton.LeftButton)
        QTimer.singleShot(0, accept)
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert confirmations == [True]
        assert dialog.requires_workspace_reload
        adopted = facade.load_batch("qa-task", "native-qa-batch")
        assert adopted["revision"] == 2 and adopted["batch"] == expected, dialog.status.text()
        assert adopted["review_status"] == "needs_human_review"
        assert [step["step_id"] for step in adopted["batch"]["steps"]] == ["third", "second", "first"]
        assert adopted["batch"]["steps"][-1]["start_state"] == flow["start_state"]
        assert service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"}) == inbox_before
        assert facade.list_reviewed_assets() == []
        origin = adopted["relearn_adoption"]
        assert origin["candidate_id"] == candidate["candidate_id"]
    finally:
        if dialog is not None:
            _wait(lambda: not dialog._jobs)
            dialog.message.clear()
            for index in range(dialog.scope_list.count()):
                dialog.scope_list.item(index).setCheckState(Qt.CheckState.Unchecked)
            dialog.close(); application.processEvents()
        facade.close(); store.close()
    reopened_store = AgentLinkStore(state)
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, token), token, root)
    try:
        assert reopened.load_batch("qa-task", "native-qa-batch") == adopted
        assert reopened.load_relearn_review("qa-task", "native-qa-batch", 2)["candidates"][0]["candidate_id"] == candidate["candidate_id"]
    finally:
        reopened.close(); reopened_store.close()
