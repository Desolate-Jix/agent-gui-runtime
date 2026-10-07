import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from app.learning_memory.workflow_rules_editor import WorkflowRulesEditor


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def context():
    return {"inputs": [{"name": "record_id", "type": "text", "required": True}],
            "steps": [{"step_id": "lookup", "title": "查找", "outputs": [{"name": "found", "type": "text"}]},
                      {"step_id": "read", "title": "读取", "outputs": [{"name": "status", "type": "text"}]}]}


def test_existing_rules_roundtrip_and_typed_expected_edit(app):
    editor = WorkflowRulesEditor()
    step = {"step_id": "read", "action": {"kind": "read_text"},
            "verification": {"kind": "text_equals", "target": {"control_type": "Text", "name": "状态", "automation_id": "status"},
                             "expected": {"source": "input", "name": "record_id"}, "output_name": "status"},
            "read_spec": {"method": "visible_text", "target": {"control_type": "Text", "name": "状态", "automation_id": "status"},
                          "output_name": "status"}}
    editor.set_step(step, context(), 1)
    assert editor.rules("read_text") == (step["verification"], step["read_spec"])
    editor.expected_source.setCurrentIndex(editor.expected_source.findData("constant"))
    editor.expected_type.setCurrentIndex(editor.expected_type.findData("number"))
    editor.expected_value.setText("42.5")
    verification, read_spec = editor.rules("read_text")
    assert verification["expected"] == {"source": "constant", "value": 42.5}
    assert read_spec == step["read_spec"]
    editor.close()


def test_rule_clear_and_read_only_action_gate(app):
    editor = WorkflowRulesEditor()
    editor.set_step({"step_id": "read", "action": {"kind": "click"}}, context(), 1)
    assert not editor.read_method.isEnabled()
    editor.verification_kind.setCurrentIndex(editor.verification_kind.findData("target_absent"))
    editor.target_type.setText("Text")
    editor.target_name.setText("没有结果")
    assert editor.rules("click")[0] == {"kind": "target_absent", "target": {"control_type": "Text", "name": "没有结果"}}
    editor.verification_kind.setCurrentIndex(0)
    assert editor.rules("click") == (None, None)
    editor.close()


def test_invalid_typed_constant_reports_error_and_integer_stays_integer(app):
    editor = WorkflowRulesEditor()
    step = {"step_id": "read", "action": {"kind": "click"},
            "verification": {"kind": "field_equals", "target": {"control_type": "Text", "name": "数量"},
                             "expected": {"source": "constant", "value": 42}}}
    editor.set_step(step, context(), 1)
    editor.target_name.setText("另一个数量")
    assert editor.rules("click")[0]["expected"]["value"] == 42
    assert type(editor.rules("click")[0]["expected"]["value"]) is int
    editor.expected_value.setText("not-a-number")
    editor.rules("click")
    assert "数字" in editor.validation_error
    editor.expected_value.setText("inf")
    editor.rules("click")
    assert "数字" in editor.validation_error
    editor.expected_type.setCurrentIndex(editor.expected_type.findData("boolean"))
    editor.expected_value.setText("perhaps")
    editor.rules("click")
    assert "是／否" in editor.validation_error
    editor.expected_value.setText("true")
    assert editor.rules("click")[0]["expected"]["value"] is True
    assert editor.validation_error is None
    editor.close()


def test_agent_judgment_drops_target_and_sources_filter_declared_names(app):
    editor = WorkflowRulesEditor()
    step = {"step_id": "read", "action": {"kind": "click"},
            "verification": {"kind": "text_equals", "target": {"control_type": "Text", "name": "旧目标"},
                             "expected": {"source": "input", "name": "record_id"}}}
    editor.set_step(step, context(), 1)
    editor.verification_kind.setCurrentIndex(editor.verification_kind.findData("agent_judgment"))
    assert editor.rules("click")[0] == {"kind": "agent_judgment"}
    assert not editor.target_name.isEnabled()
    editor.verification_kind.setCurrentIndex(editor.verification_kind.findData("field_equals"))
    editor.expected_source.setCurrentIndex(editor.expected_source.findData("input"))
    assert [editor.expected_name.itemText(i) for i in range(editor.expected_name.count())] == ["record_id"]
    editor.expected_source.setCurrentIndex(editor.expected_source.findData("output"))
    editor.expected_step.setCurrentIndex(0)
    assert [editor.expected_name.itemText(i) for i in range(editor.expected_name.count())] == ["found"]
    editor.expected_step.setCurrentText("missing-step")
    assert editor.rules("click")[0]["expected"]["step_id"] == "missing-step"
    editor.close()
