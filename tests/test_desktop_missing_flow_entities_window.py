"""遗漏步骤／关系的原生只读对照与采用；仅使用合成临时数据。"""
from copy import deepcopy
import os
from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractItemView, QMessageBox

from tests.test_desktop_relearn_adoption_window import _compared


def _flow_entity_diffs(workspace, anchor=None):
    batch = workspace["batch"]
    first, last = batch["interfaces"][0], batch["interfaces"][-1]
    step = {"step_id": "missing-step", "action_type": "observe", "target_region_id": None,
            "start_state": first["interface_id"], "arrival_state": last["interface_id"],
            "prerequisites": ["人工核验当前界面"], "expected_result": "补齐遗漏观察", "stop_condition": "等待独立审核"}
    relation = {"relationship_id": "missing-relation", "from_interface_id": first["interface_id"],
                "to_interface_id": last["interface_id"], "kind": "新增流程关联"}
    return [
        {"target_type": "step", "target_id": step["step_id"], "field": "entity",
         "baseline": None, "current": None, "proposed": {"after_step_id": anchor, "step": step}},
        {"target_type": "relationship", "target_id": relation["relationship_id"], "field": "entity",
         "baseline": None, "current": None, "proposed": relation},
    ]


@pytest.mark.parametrize("at_start", [True, False])
def test_native_missing_step_and_relation_show_all_fields_and_explicit_insertion_readonly(at_start):
    application, facade, dialog = _compared()
    before = deepcopy(dialog.workspace)
    anchor = None if at_start else dialog.workspace["batch"]["steps"][0]["step_id"]
    comparison = deepcopy(dialog.comparison)
    comparison["diffs"] = _flow_entity_diffs(dialog.workspace, anchor)
    try:
        dialog._pending = ("compare", comparison["candidate_id"])
        dialog._succeeded(dialog._request_id, comparison)
        assert dialog.diff_table.rowCount() == 13
        labels = [dialog.diff_table.item(row, 1).text() for row in range(13)]
        assert labels[:9] == ["新增步骤 · 标识", "新增步骤 · 插入位置", "新增步骤 · 操作",
                              "新增步骤 · 目标控件", "新增步骤 · 起始界面", "新增步骤 · 到达界面",
                              "新增步骤 · 前置条件", "新增步骤 · 预期结果", "新增步骤 · 停止条件"]
        assert labels[9:] == ["新增关系 · 标识", "新增关系 · 来源界面", "新增关系 · 目的界面", "新增关系 · 类别"]
        assert dialog.diff_table.item(1, 4).text() == ("流程开头" if at_start else f"步骤 {anchor} 之后")
        for row in range(13):
            assert dialog.diff_table.item(row, 2).text() == dialog.diff_table.item(row, 3).text() == "不存在"
            assert not dialog.diff_table.item(row, 4).flags() & Qt.ItemFlag.ItemIsEditable
        assert dialog.diff_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
        assert not dialog.geometry_button.isEnabled()
        assert dialog.comparison == comparison and dialog.workspace == before
        assert not facade.requests and dialog.adoption_receipt is None
    finally:
        dialog.close()
        application.processEvents()


@pytest.mark.parametrize("invalid", ["wrapper", "anchor", "step_id", "relationship_id", "authority"])
def test_malformed_flow_entity_is_not_expanded_into_plausible_fields(invalid):
    from app.desktop_review.relearn_dialog import _comparison_display_rows
    application, _, dialog = _compared()
    diffs = _flow_entity_diffs(dialog.workspace)
    diff = diffs[1] if invalid == "relationship_id" else diffs[0]
    if invalid == "wrapper":
        diff["proposed"]["unknown"] = True
    elif invalid == "anchor":
        diff["proposed"]["after_step_id"] = []
    elif invalid == "step_id":
        diff["proposed"]["step"]["step_id"] = "wrong-step"
    elif invalid == "relationship_id":
        diff["proposed"]["relationship_id"] = "wrong-relation"
    else:
        diff["proposed"]["step"]["execute_binding_enabled"] = True
    before = deepcopy(diff)
    try:
        rows = _comparison_display_rows([diff])
        assert len(rows) == 1 and "格式无效" in rows[0]["_display_label"]
        assert rows[0]["proposed"] == before["proposed"] and diff == before
    finally:
        dialog.close()
        application.processEvents()


def test_real_native_missing_flow_compare_adopt_edit_reorder_and_reopen(tmp_path):
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.desktop_review.relearn_dialog import RelearnReviewDialog
    from app.desktop_review.window import ReviewMainWindow, ensure_application
    from app.desktop_review.workspace import NativeReviewFacade
    from tests.test_desktop_flow_candidates_window import _real_flow_batch
    from tests.test_desktop_relearn_window import _wait
    from tests.test_desktop_review_window import _wait_loaded, _wait_workers

    application = ensure_application()
    batch = _real_flow_batch(application)
    missing_region = batch["interfaces"][0]["regions"].pop()
    state, root = tmp_path / "inbox.json", tmp_path / "review-data"
    token = "synthetic-missing-flow-reviewer"
    store = AgentLinkStore(state)
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {"task_id": "qa-task", "agent_name": "合成遗漏流程验收"})
    service.agent_call(grant["token"], "submit_batch", batch)
    facade = NativeReviewFacade(service, token, root)
    dialog = window = None
    output = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
    output.mkdir(parents=True, exist_ok=True)
    try:
        loaded = facade.load_batch("qa-task", "native-qa-batch")
        saved = facade.save_revision("qa-task", "native-qa-batch", 0, loaded["batch"])
        original = deepcopy(saved["batch"])
        dialog = RelearnReviewDialog(facade, saved)
        dialog.resize(1500, 1050)
        dialog.show()
        _wait(lambda: dialog.review is not None and not dialog._jobs)
        for index in range(2):
            dialog.scope_list.item(index).setCheckState(Qt.CheckState.Checked)
        dialog.message.setPlainText("补上第一步之后的详情步骤和返回关系，按钮也漏识别")
        QTest.mouseClick(dialog.request_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert not dialog.message.toPlainText(), dialog.status.text()
        issue = service.agent_call(grant["token"], "read_feedback", {"batch_id": "native-qa-batch"})["issues"][0]
        step = {**deepcopy(saved["batch"]["steps"][0]), "step_id": "missing-open-detail",
                "action_type": "open_detail", "target_region_id": missing_region["region_id"],
                "arrival_state": "file-list-checked", "expected_result": "进入已检查详情状态"}
        relation = {"relationship_id": "missing-return", "from_interface_id": "file-list-checked",
                    "to_interface_id": "file-list", "kind": "返回列表"}
        receipt = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "batch_id": "native-qa-batch", "idempotency_key": "native-missing-flow",
            "issue_id": issue["issue_id"], "baseline_revision": issue["baseline_revision"], "scope": issue["scope"],
            "review_baseline_sha256": issue["review_baseline_sha256"], "changes": [
                {"change_type": "steps_add", "after_step_id": "first", "steps": [step]},
                {"change_type": "regions_add", "interface_id": "file-list", "regions": [missing_region]},
                {"change_type": "relationships_add", "relationships": [relation]},
            ],
        })
        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        dialog.tabs.setCurrentIndex(1)
        dialog.candidate_table.selectRow(0)
        QTest.mouseClick(dialog.compare_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.comparison is not None and dialog.comparison["status"] == "current", dialog.status.text()
        assert len(dialog.comparison["diffs"]) == 3 and dialog.diff_table.rowCount() == 14
        assert dialog.diff_table.item(1, 4).text() == "步骤 first 之后"
        dialog.diff_table.setCurrentCell(1, 4)
        dialog.diff_table.scrollToItem(dialog.diff_table.item(1, 4))
        application.processEvents()
        assert dialog.diff_table.viewport().rect().intersects(dialog.diff_table.visualItemRect(dialog.diff_table.item(1, 4)))
        assert dialog.grab().save(str(output / "native-missing-flow-comparison.png"))
        answers = []

        def answer(button):
            prompt = application.activeModalWidget()
            if isinstance(prompt, QMessageBox):
                answers.append(prompt.defaultButton() == prompt.button(QMessageBox.StandardButton.Cancel)
                               and "3 项候选变更" in prompt.text())
                QTest.mouseClick(prompt.button(button), Qt.MouseButton.LeftButton)

        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Cancel))
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        assert facade.load_batch("qa-task", "native-qa-batch") == saved
        QTimer.singleShot(0, lambda: answer(QMessageBox.StandardButton.Yes))
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert answers == [True, True]
        assert dialog.adoption_receipt is not None, dialog.status.text()
        adopted = facade.load_batch("qa-task", "native-qa-batch")
        assert [item["step_id"] for item in adopted["batch"]["steps"]] == ["first", "missing-open-detail", "second", "third"]
        assert adopted["batch"]["relationships"][-1] == relation
        assert adopted["relearn_adoption"]["candidate_id"] == receipt["candidate_id"]
        assert adopted["review_status"] == "needs_human_review" and adopted["revision"] == 2
        dialog.close()
        application.processEvents()
        window = ReviewMainWindow(facade)
        window.resize(1500, 1100)
        window.show()
        application.processEvents()
        item = window.batch_tree.topLevelItem(0)
        QTest.mouseClick(window.batch_tree.viewport(), Qt.MouseButton.LeftButton,
                         pos=window.batch_tree.visualItemRect(item).center())
        _wait_loaded(window)
        _wait_workers(window)
        window.step_table.selectRow(1)
        window.step_expected.setPlainText("人工确认新步骤只打开详情")
        window.relationship_table.selectRow(1)
        window.relationship_kind.setText("人工校正返回关联")
        QTest.mouseClick(window.step_up_button, Qt.MouseButton.LeftButton)
        assert window._selected_step_id == "missing-open-detail"
        window.save_action.trigger()
        _wait_workers(window)
        assert window.workspace["revision"] == 3, window.status.currentMessage()
        assert window.workspace["batch"]["steps"][0]["step_id"] == "missing-open-detail"
        assert window.workspace["batch"]["steps"][0]["expected_result"] == "人工确认新步骤只打开详情"
        assert window.workspace["batch"]["relationships"][-1]["kind"] == "人工校正返回关联"
        assert window.grab().save(str(output / "native-missing-flow-edited.png"))
        assert facade.list_reviewed_assets() == []
        assert service.reviewer_call(token, "get_batch", {"task_id": "qa-task", "batch_id": "native-qa-batch"})["batch"] == original
        final = deepcopy(window.workspace)
    finally:
        if dialog is not None:
            _wait(lambda: not dialog._jobs)
            dialog.message.clear()
            for index in range(dialog.scope_list.count()):
                dialog.scope_list.item(index).setCheckState(Qt.CheckState.Unchecked)
            dialog.close()
        if window is not None:
            _wait_workers(window)
            window._dirty = False
            window.close()
        application.processEvents()
        facade.close()
        store.close()
    reopened_store = AgentLinkStore(state)
    reopened = NativeReviewFacade(AgentLinkService(reopened_store, token), token, root)
    try:
        assert reopened.load_batch("qa-task", "native-qa-batch") == final
    finally:
        reopened.close()
        reopened_store.close()
