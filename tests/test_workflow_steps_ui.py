"""任务步骤页离屏交互：保存的定义决定待执行请求，页面不派发输入。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time

import pytest

from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.graph_source import logical_id
from app.learning_memory.editor_client import MemoryEditorClient
from test_learning_memory_v1 import record_search


def _wait(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("UI 后台读取未按时完成")


@pytest.fixture
def generated(tmp_path):
    session = tmp_path / "session"
    (session / "responses").mkdir(parents=True)
    store = LearningEventStore(session)
    store.control("learning_start", {"scope": "workflow", "title": "地图搜索", "project_id": "maps-ui"}, "start")
    record_search(store, "search-one")
    store.control("learning_stop", {}, "stop")
    return session, tmp_path / "memory-library", logical_id("maps-ui")


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    assert font_id >= 0
    app.setFont(QFont("Microsoft YaHei UI", 10))
    return app


def _pane(qt_app, generated, session=True):
    from app.learning_memory.workflow_steps_pane import WorkflowStepsPane
    session_dir, root, workflow_id = generated
    pane = WorkflowStepsPane(MemoryEditorClient(root), session_dir if session else None)
    pane.resize(1280, 800)
    pane.show()
    _wait(qt_app, lambda: pane.snapshot is not None and not pane.is_busy)
    assert pane.snapshot["workflow_id"] == workflow_id
    return pane


def test_agent_judgment_edit_drops_previous_automatic_output(qt_app, generated):
    pane = _pane(qt_app, generated)
    pane._insert_table_row(pane.outputs, ("matched", "boolean"))
    rules = pane.rules_editor
    rules.verification_kind.setCurrentIndex(rules.verification_kind.findData("target_present"))
    rules.target_type.setText("Button")
    rules.target_name.setText("打开详情")
    rules.verification_output.setCurrentText("matched")
    pane.save_button.click()
    assert not pane.dirty
    old_version = pane.snapshot["program_id"]
    rules.verification_kind.setCurrentIndex(rules.verification_kind.findData("agent_judgment"))
    pane.save_button.click()
    assert not pane.dirty and pane.snapshot["program_id"] != old_version
    assert pane.snapshot["definition"]["steps"][0]["verification"] == {"kind": "agent_judgment"}
    pane.close()


def test_generated_step_edit_save_reopen_changes_pending_command(qt_app, generated, monkeypatch):
    session, root, _workflow_id = generated
    pane = _pane(qt_app, generated)
    assert pane.steps.count() == 1
    assert pane.relations.topLevelItemCount() == 1
    assert pane.nav_tabs.count() == 2
    pane.nav_tabs.setCurrentIndex(1)
    assert pane.relations.isVisible()
    assert pane.relation_views.count() == 2
    pane.nav_tabs.setCurrentIndex(0)
    assert pane.prepare_button.isVisible()
    assert pane.prepare_button.mapTo(pane, pane.prepare_button.rect().bottomRight()).y() < pane.height()
    assert pane.action_kind.currentData() == "input_sequence"
    pane.text_source.setCurrentIndex(pane.text_source.findData("constant"))
    pane.text_value.setText("新搜索词")
    assert pane.dirty
    pane.save_button.click()
    assert not pane.dirty
    assert pane.snapshot["program_id"] is not None
    pane.close()

    reopened = _pane(qt_app, generated)
    assert reopened.text_value.text() == "新搜索词"
    before = list((session / "responses").glob("*.json"))
    monkeypatch.setattr(reopened, "_trial_inputs", lambda: {"place": "另一地点"})
    reopened.prepare_button.click()
    assert reopened._run_id is not None
    command = json.loads(reopened.command_preview.toPlainText())
    assert command["request"]["text"] == "新搜索词"
    assert list((session / "responses").glob("*.json")) == before
    trial = reopened.facade.status_workflow_trial(session, reopened._run_id)
    assert trial["status"] == "pending"
    assert trial["pending"]["suggested_command"] == command
    assert trial["history"] == []
    reopened.status_button.click()
    assert "等待 Agent" in reopened.status.text()
    assert not reopened.next_button.isEnabled()
    reopened.cancel_button.click()
    assert reopened.facade.status_workflow_trial(session, reopened._run_id)["status"] == "cancel_requested"
    capture = os.environ.get("WORKFLOW_STEPS_CAPTURE")
    if capture:
        qt_app.processEvents()
        assert reopened.grab().save(capture)
    relation_capture = os.environ.get("WORKFLOW_RELATIONS_CAPTURE")
    if relation_capture:
        reopened.nav_tabs.setCurrentIndex(1)
        qt_app.processEvents()
        assert reopened.grab().save(relation_capture)
    reopened.close()


def test_dirty_switch_and_prepare_without_session_are_blocked(qt_app, generated):
    pane = _pane(qt_app, generated, session=False)
    pane.step_title.setText("新名称")
    assert pane.dirty
    pane.close()
    assert pane.isVisible()
    assert "未保存修改" in pane.status.text()
    pane.refresh_button.click()
    assert "保存或放弃" in pane.status.text()
    pane.prepare_button.click()
    assert "先保存" in pane.status.text()
    pane.discard_button.click()
    assert not pane.dirty
    pane.save_button.click()
    pane.prepare_button.click()
    assert "未连接执行会话" in pane.status.text()
    assert pane._run_id is None
    pane.close()


def test_delete_referenced_step_requires_explicit_branch_repair(qt_app, generated):
    pane = _pane(qt_app, generated)
    pane.add_button.click()
    assert pane.steps.count() == 2
    new_id = pane._selected_id
    pane.steps.setCurrentRow(0)
    pane.success.setCurrentIndex(pane.success.findData(new_id))
    pane.steps.setCurrentRow(1)
    pane.delete_button.click()
    assert pane.steps.count() == 2
    assert "修复引用" in pane.status.text()
    pane.steps.setCurrentRow(0)
    pane.success.setCurrentIndex(0)
    pane.steps.setCurrentRow(1)
    pane.delete_button.click()
    assert pane.steps.count() == 1
    pane.discard_button.click()
    pane.close()


def test_delete_step_referenced_by_verification_output_requires_repair(qt_app, generated):
    pane = _pane(qt_app, generated)
    first_id = pane._selected_id
    pane._insert_table_row(pane.outputs, ("record_status", "text"))
    pane.add_button.click()
    second_id = pane._selected_id
    pane.goal.setText("核对状态")
    rules = pane.rules_editor
    rules.verification_kind.setCurrentIndex(rules.verification_kind.findData("text_equals"))
    rules.target_type.setText("Text")
    rules.target_name.setText("状态")
    rules.expected_source.setCurrentIndex(rules.expected_source.findData("output"))
    rules.expected_step.setCurrentIndex(rules.expected_step.findData(first_id))
    rules.expected_name.setCurrentText("record_status")
    pane.save_button.click()
    assert not pane.dirty
    saved_id = pane.snapshot["program_id"]
    pane.steps.setCurrentRow(0)
    pane.delete_button.click()
    assert pane.steps.count() == 2
    assert pane.snapshot["program_id"] == saved_id
    assert "结果" in pane.status.text() or "验证" in pane.status.text()
    pane.steps.setCurrentRow(1)
    assert pane._selected_id == second_id
    assert pane.rules_editor.rules("click")[0]["expected"] == {
        "source": "output", "step_id": first_id, "name": "record_status"}
    pane.rules_editor.expected_source.setCurrentIndex(pane.rules_editor.expected_source.findData("constant"))
    pane.rules_editor.expected_value.setText("已完成")
    pane.steps.setCurrentRow(0)
    pane.delete_button.click()
    assert pane.steps.count() == 1
    pane.discard_button.click()
    pane.close()


def test_delete_step_referenced_by_program_output_requires_repair(qt_app, generated):
    pane = _pane(qt_app, generated)
    first_id = pane._selected_id
    pane._insert_table_row(pane.outputs, ("record_status", "text"))
    pane._commit_all()
    pane.definition["outputs"].append({"name": "final_status", "type": "text",
                                       "step_id": first_id})
    pane.delete_button.click()
    assert pane.steps.count() == 1
    assert "任务输出" in pane.status.text()
    assert pane.definition["outputs"][0]["step_id"] == first_id
    pane.discard_button.click()
    pane.close()


def test_condition_output_and_review_edit_without_json(qt_app, generated):
    pane = _pane(qt_app, generated)
    pane.editor_tabs.setCurrentIndex(1)
    pane.preconditions.name.setText("place")
    pane.preconditions.add_button.click()
    pane.add_output.click()
    pane.outputs.item(0, 0).setText("found_text")
    pane.editor_tabs.setCurrentIndex(0)
    pane.review.setCurrentIndex(pane.review.findData("reviewed"))
    pane.save_button.click()
    assert not pane.dirty
    saved = pane.facade.load_workflow_program(pane.snapshot["workflow_id"])
    step = saved["definition"]["steps"][0]
    assert step["preconditions"] == [{"left": {"source": "input", "name": "place"}, "operator": "exists"}]
    assert step["outputs"] == [{"name": "found_text", "type": "text"}]
    assert step["review_status"] == "pending"
    assert pane.review.currentData() == "pending"
    first_program_id = saved["program_id"]
    pane.review.setCurrentIndex(pane.review.findData("reviewed"))
    pane.save_button.click()
    assert not pane.dirty
    saved = pane.facade.load_workflow_program(pane.snapshot["workflow_id"])
    assert saved["program_id"] != first_program_id
    step = saved["definition"]["steps"][0]
    assert step["review_status"] == "reviewed"
    assert pane.review.currentData() == "reviewed"
    pane.close()


def test_new_manual_step_requires_defined_goal_before_save(qt_app, generated):
    pane = _pane(qt_app, generated)
    pane.add_button.click()
    pane.save_button.click()
    assert pane.dirty
    assert "请填写当前步骤的目标" in pane.status.text()
    pane.goal.setText("打开帮助菜单")
    pane.save_button.click()
    assert not pane.dirty
    saved = pane.facade.load_workflow_program(pane.snapshot["workflow_id"])
    assert saved["definition"]["steps"][-1]["action"]["goal"] == "打开帮助菜单"
    pane.close()


def test_program_graph_shows_only_explicit_branches_and_selects_editor(qt_app, generated):
    pane = _pane(qt_app, generated)
    first_id = pane._selected_id
    pane.add_button.click()
    second_id = pane._selected_id
    pane.steps.setCurrentRow(0)
    pane.success.setCurrentIndex(pane.success.findData(second_id))
    pane.relation_views.setCurrentIndex(1)
    pane.nav_tabs.setCurrentIndex(1)
    qt_app.processEvents()
    graph = pane.program_graph
    assert len(graph._node_items) == 2
    assert set(graph._edge_items) == {first_id + ":success"}
    graph._node_items[second_id].setSelected(True)
    qt_app.processEvents()
    assert pane._selected_id == second_id
    assert pane.step_title.text() == "新步骤"
    assert pane.nav_tabs.currentIndex() == 1
    pane.step_title.clear()
    pane.relation_views.setCurrentIndex(0)
    pane.relation_views.setCurrentIndex(1)
    assert pane._selected_id == second_id
    assert pane.dirty
    assert pane.program_graph_note.isVisible()
    pane.discard_button.click()
    pane.close()


def test_commit_preserves_target_memory_and_verification_for_unrelated_edits(qt_app, generated):
    pane = _pane(qt_app, generated)
    reference = {"recipe_id": "target-recipe-" + "a" * 64, "interface_key": "search", "state_key": "home"}
    step = pane.definition["steps"][0]
    step["action"]["target_memory"] = reference
    step["verification"] = {"kind": "agent_judgment"}
    pane._load_selected()
    pane.step_title.setText("新标题")
    pane.text_value.setText("另一个本次值")
    pane._commit_all()
    assert step["action"]["target_memory"] == reference
    assert step["verification"] == {"kind": "agent_judgment"}
    assert "read_spec" not in step
    pane.save_button.click()
    assert pane.dirty
    assert "保存失败" in pane.status.text()
    pane.submit_search.setChecked(not pane.submit_search.isChecked())
    pane._commit_all()
    assert "target_memory" not in step["action"]
    pane.discard_button.click()
    pane.close()


def test_read_source_reference_survives_text_edit_but_detaches_on_action_change(qt_app, generated):
    pane = _pane(qt_app, generated)
    step = pane.definition["steps"][0]
    step["action"] = {"kind": "read_text", "goal": "读取本页"}
    reference = {"learning_id": "learning-" + "a" * 32, "event_id": "read-one",
                 "event_sha256": "b" * 64, "review_sha256": "c" * 64}
    step["source_evidence"] = reference
    pane._load_selected()
    pane.goal.setText("读取当前标题")
    assert pane._commit_selected()
    assert step["source_evidence"] == reference
    pane.action_kind.setCurrentIndex(pane.action_kind.findData("click"))
    pane.goal.setText("打开详情")
    assert pane._commit_selected()
    assert "source_evidence" not in step
    pane.discard_button.click()
    pane.close()


@pytest.mark.parametrize("changed", ["field_goal", "kind", "goal"])
def test_semantic_target_edits_drop_stale_target_reference(qt_app, generated, changed):
    pane = _pane(qt_app, generated)
    reference = {"recipe_id": "target-recipe-" + "a" * 64, "interface_key": "search", "state_key": "home"}
    step = pane.definition["steps"][0]
    if changed == "goal":
        step["action"] = {"kind": "click", "goal": "旧目标", "target_memory": reference}
        pane._load_selected()
        pane.goal.setText("新目标")
    else:
        step["action"]["target_memory"] = reference
        if changed == "field_goal":
            pane.field_goal.setText("新字段")
        else:
            pane.action_kind.setCurrentIndex(pane.action_kind.findData("read_text"))
    pane._commit_all()
    assert "target_memory" not in step["action"]
    pane.discard_button.click()
    pane.close()


def test_empty_workbench_step_pane_keeps_program_graph_empty(qt_app, tmp_path):
    from app.learning_memory.workflow_steps_pane import WorkflowStepsPane
    pane = WorkflowStepsPane(MemoryEditorClient(tmp_path / "new-library"))
    pane.show()
    _wait(qt_app, lambda: not pane.is_busy)
    pane.nav_tabs.setCurrentIndex(1)
    pane.relation_views.setCurrentIndex(1)
    assert pane.snapshot is None
    assert not pane.program_graph._node_items
    assert pane.program_graph_note.isVisible()
    pane.close()


def test_verification_rule_edits_save_reopen_and_invalid_rule_keeps_draft(qt_app, generated):
    pane = _pane(qt_app, generated)
    pane.editor_tabs.setCurrentIndex(3)
    rules = pane.rules_editor
    rules.verification_kind.setCurrentIndex(rules.verification_kind.findData("text_equals"))
    rules.target_type.setText("Text")
    rules.target_name.setText("当前状态")
    rules.expected_source.setCurrentIndex(rules.expected_source.findData("input"))
    rules.expected_name.setCurrentText("place")
    pane.save_button.click()
    assert not pane.dirty
    saved_id = pane.snapshot["program_id"]
    assert pane.definition["steps"][0]["verification"]["expected"] == {"source": "input", "name": "place"}
    pane.close()
    pane = _pane(qt_app, generated)
    rules = pane.rules_editor
    assert rules.expected_name.currentText() == "place"
    assert rules.target_name.text() == "当前状态"
    rules.expected_source.setCurrentIndex(rules.expected_source.findData("constant"))
    rules.expected_value.setText("已完成")
    pane.save_button.click()
    assert not pane.dirty
    assert pane.definition["steps"][0]["verification"]["expected"] == {"source": "constant", "value": "已完成"}
    saved_id = pane.snapshot["program_id"]
    rules.verification_output.setCurrentText("missing_output")
    pane.save_button.click()
    assert pane.dirty
    assert pane.snapshot["program_id"] == saved_id
    assert "保存失败" in pane.status.text()
    pane.discard_button.click()
    rules.target_name.clear()
    pane.save_button.click()
    assert pane.dirty
    assert pane.snapshot["program_id"] == saved_id
    assert "保存失败" in pane.status.text()
    pane.discard_button.click()
    rules.verification_kind.setCurrentIndex(0)
    pane.save_button.click()
    assert "verification" not in pane.definition["steps"][0]
    pane.close()


def test_rule_stays_with_source_step_when_switching_list_and_graph(qt_app, generated):
    pane = _pane(qt_app, generated)
    first_id = pane._selected_id
    rules = pane.rules_editor
    rules.verification_kind.setCurrentIndex(rules.verification_kind.findData("target_present"))
    rules.target_type.setText("Text")
    rules.target_name.setText("结果")
    pane.add_button.click()
    second_id = pane._selected_id
    assert pane.definition["steps"][0]["verification"]["target"]["name"] == "结果"
    assert "verification" not in pane.definition["steps"][1]
    pane.relation_views.setCurrentIndex(1)
    pane.nav_tabs.setCurrentIndex(1)
    pane.program_graph._node_items[first_id].setSelected(True)
    qt_app.processEvents()
    assert pane._selected_id == first_id
    assert pane.rules_editor.target_name.text() == "结果"
    pane.program_graph.scene().clearSelection()
    pane.program_graph._node_items[second_id].setSelected(True)
    qt_app.processEvents()
    assert pane._selected_id == second_id
    assert pane.rules_editor.verification_kind.currentData() is None
    pane.discard_button.click()
    pane.close()


@pytest.mark.parametrize("constant_type,value,expected_error", [
    ("number", "oops", "数字"), ("boolean", "perhaps", "是／否")])
def test_invalid_typed_rule_keeps_selected_step_and_saved_revision(qt_app, generated,
                                                                    constant_type, value, expected_error):
    pane = _pane(qt_app, generated)
    pane.add_button.click()
    second_id = pane._selected_id
    pane.goal.setText("打开详情")
    pane.steps.setCurrentRow(0)
    first_id = pane._selected_id
    rules = pane.rules_editor
    rules.verification_kind.setCurrentIndex(rules.verification_kind.findData("field_equals"))
    rules.target_type.setText("Text")
    rules.target_name.setText("数量")
    rules.expected_type.setCurrentIndex(rules.expected_type.findData(constant_type))
    rules.expected_value.setText(value)
    saved_id = pane.snapshot["program_id"]
    pane.steps.setCurrentRow(1)
    assert pane._selected_id == first_id
    assert pane.rules_editor.expected_value.text() == value
    assert pane.dirty
    pane.save_button.click()
    assert pane.snapshot["program_id"] == saved_id
    assert expected_error in pane.status.text()
    rules.expected_value.setText("12" if constant_type == "number" else "true")
    pane.steps.setCurrentRow(1)
    assert pane._selected_id == second_id
    pane.discard_button.click()
    pane.close()


def test_read_spec_only_on_read_text_saves_reopens_and_survives_title_edit(qt_app, generated):
    pane = _pane(qt_app, generated)
    pane.action_kind.setCurrentIndex(pane.action_kind.findData("read_text"))
    pane.goal.setText("读取状态")
    pane.add_output.click()
    pane.outputs.item(0, 0).setText("status")
    rules = pane.rules_editor
    assert rules.read_method.isEnabled()
    rules.read_method.setCurrentIndex(rules.read_method.findData("visible_text"))
    rules.target_type.setText("Text")
    rules.target_name.setText("状态")
    rules.read_output.setCurrentText("status")
    pane.save_button.click()
    assert not pane.dirty
    saved = pane.definition["steps"][0]["read_spec"]
    assert saved == {"method": "visible_text", "target": {"control_type": "Text", "name": "状态"}, "output_name": "status"}
    pane.close()
    pane = _pane(qt_app, generated)
    assert pane.rules_editor.read_method.currentData() == "visible_text"
    pane.step_title.setText("状态读取")
    pane.save_button.click()
    assert pane.definition["steps"][0]["read_spec"] == saved
    saved_id = pane.snapshot["program_id"]
    pane.rules_editor.read_output.setCurrentText("missing_output")
    pane.save_button.click()
    assert pane.dirty
    assert pane.snapshot["program_id"] == saved_id
    pane.discard_button.click()
    pane.action_kind.setCurrentIndex(pane.action_kind.findData("click"))
    assert not pane.rules_editor.read_method.isEnabled()
    pane.discard_button.click()
    pane.close()
