"""条件模板编辑只修改绑定或新修订，不改旧模板和运行输入。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy

import pytest
from PySide6.QtWidgets import QApplication

from app.judgment.condition_templates import make_record_id_template, resolve_condition_binding
from app.learning_memory.condition_template_editor import ConditionTemplateEditor
from app.learning_memory.workflow_rules_editor import WorkflowRulesEditor
from tests.test_workflow_trial import services, WORKFLOW


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def binding():
    return {"schema": "condition_binding.v1", "template": make_record_id_template(),
        "typed_parameters": {"record_id": {"source": "input", "name": "query"}}}


INPUTS = [{"name": "query", "type": "text", "required": True},
    {"name": "count", "type": "number", "required": True}]


def test_existing_binding_is_lossless_and_parameter_change_keeps_template_revision(app):
    editor = ConditionTemplateEditor()
    original = binding()
    editor.set_binding(original, INPUTS)
    assert editor.value() == (original, None)
    assert [editor.input_name.itemText(i) for i in range(editor.input_name.count())] == ["query"]
    editor.parameter_source.setCurrentIndex(editor.parameter_source.findData("literal"))
    editor.literal_value.setText('记录号-"甲"')
    value, error = editor.value()
    assert error is None and value["template"] == original["template"]
    assert resolve_condition_binding(value, {})["typed_parameters"] == {"record_id": '记录号-"甲"'}
    assert original == binding()
    assert editor.preview.isReadOnly()
    editor.close()


def test_semantic_edit_produces_one_new_revision_and_restoring_content_restores_identity(app):
    editor = ConditionTemplateEditor()
    original = binding()
    editor.set_binding(original, INPUTS)
    editor.template_text.setPlainText("The record number shown in the detail is {record_id}.")
    first, error = editor.value()
    assert error is None
    assert first["template"]["revision"] == 2
    assert first["template"]["template_sha256"] != original["template"]["template_sha256"]
    assert editor.value()[0] == first
    editor.template_text.setPlainText(original["template"]["text_template"])
    assert editor.value()[0] == original
    editor.close()


@pytest.mark.parametrize("invalid", ["placeholder", "length", "input", "state"])
def test_invalid_template_edit_blocks_value(app, invalid):
    editor = ConditionTemplateEditor()
    editor.set_binding(binding(), INPUTS)
    if invalid == "placeholder":
        editor.template_text.setPlainText("Always pass.")
    elif invalid == "length":
        editor.minimum.setValue(200)
        editor.maximum.setValue(100)
    elif invalid == "input":
        editor.input_name.setCurrentIndex(-1)
    else:
        editor.allowed_states.setPlainText("ready\nready")
    value, error = editor.value()
    assert value is None and error
    editor.close()


def test_rules_editor_uses_exclusive_template_and_keeps_unmodified_legacy_rule(app):
    editor = WorkflowRulesEditor()
    step = {"step_id": "first", "action": {"kind": "click"}, "outputs": [],
        "verification": {"kind": "agent_judgment", "decision_condition": "A detail is open."}}
    definition = {"inputs": INPUTS, "steps": [step]}
    editor.set_step(step, definition, 0)
    assert editor.rules("click")[0] == step["verification"]
    editor.condition_template.enabled.setChecked(True)
    editor.condition_template.parameter_source.setCurrentIndex(editor.condition_template.parameter_source.findData("input"))
    rule, _ = editor.rules("click")
    assert editor.validation_error is None
    assert "condition_binding" in rule and "decision_condition" not in rule
    assert not editor.decision_condition.isEnabled()
    new_step = {**step, "verification": deepcopy(rule)}
    editor.set_step(new_step, definition, 0)
    assert editor.rules("click")[0] == rule
    editor.condition_template.template_text.setPlainText("No parameter")
    editor.rules("click")
    assert editor.validation_error
    editor.close()


def test_reading_or_output_steps_cannot_enable_semantic_templates(app):
    editor = WorkflowRulesEditor()
    editor.set_step({"step_id": "read", "action": {"kind": "read_text"}, "outputs": []},
        {"inputs": INPUTS, "steps": []}, 0)
    assert not editor.condition_template.isEnabled()
    editor.close()


def test_language_switch_keeps_binding_and_edit_signals_unchanged(app, tmp_path):
    from app.learning_memory.workbench_i18n import initialize_i18n
    manager = initialize_i18n(app, tmp_path / "preferences.json", "en_US")
    editor = ConditionTemplateEditor()
    editor.set_binding(binding(), INPUTS)
    events = []
    editor.changed.connect(lambda: events.append(True))
    original = editor.value()[0]
    assert editor.enabled.text() == "Use a record ID condition template"
    assert "Use the actual value" in editor.preview.toPlainText()
    manager.set_language("zh-CN", persist=False)
    assert editor.enabled.text() == "使用记录号条件模板"
    assert "运行时取输入" in editor.preview.toPlainText()
    manager.set_language("en-US", persist=False)
    assert editor.value()[0] == original and events == []
    editor.close()
    manager.set_language("zh-CN", persist=False)


def test_parameter_edit_preserves_multiline_state_and_original_text_bytes(app):
    original = binding()
    original["template"] = make_record_id_template(text_template="Record:\r\n{record_id}", allowed_states=["detail\nready"])
    editor = ConditionTemplateEditor()
    editor.set_binding(original, INPUTS)
    editor.parameter_source.setCurrentIndex(editor.parameter_source.findData("literal"))
    editor.literal_value.setText("R-001")
    value, error = editor.value()
    assert error is None and value["template"] == original["template"]
    editor.close()


@pytest.mark.parametrize("declarations", [[{"name": "replacement", "type": "text", "required": True}],
    [{"name": "query", "type": "number", "required": True}, {"name": "replacement", "type": "text", "required": True}]])
def test_changed_input_declaration_remains_editable_and_requires_rebinding(app, declarations):
    editor = WorkflowRulesEditor()
    step = {"step_id": "first", "action": {"kind": "click"}, "outputs": [],
        "verification": {"kind": "agent_judgment", "condition_binding": binding()}}
    editor.set_step(step, {"inputs": declarations, "steps": [step]}, 0)
    original, _ = editor.rules("click")
    assert original == step["verification"] and editor.validation_error and not editor._loading
    combo = editor.condition_template.input_name
    combo.setCurrentIndex(combo.findData("replacement"))
    rule, _ = editor.rules("click")
    assert editor.validation_error is None
    assert rule["condition_binding"]["typed_parameters"]["record_id"] == {"source": "input", "name": "replacement"}
    assert rule["condition_binding"]["template"] == step["verification"]["condition_binding"]["template"]
    editor.close()


def test_switching_template_step_to_read_text_blocks_save_without_dropping_binding(app):
    editor = WorkflowRulesEditor()
    step = {"step_id": "first", "action": {"kind": "click"}, "outputs": [],
        "verification": {"kind": "agent_judgment", "condition_binding": binding()}}
    editor.set_step(step, {"inputs": INPUTS, "steps": [step]}, 0)
    editor.set_action_kind("read_text")
    rule, _ = editor.rules("read_text")
    assert editor.validation_error and rule == step["verification"]
    assert editor.condition_template.enabled.isEnabled()
    assert not editor.condition_template.body.isEnabled()
    editor.condition_template.enabled.setChecked(False)
    rule, _ = editor.rules("read_text")
    assert editor.validation_error is None and "condition_binding" not in rule
    editor.close()


def test_editor_program_save_review_reopen_and_run_parameter_binding(app, services):
    programs, trials, original, _ = services
    definition = deepcopy(original["definition"])
    definition["steps"] = definition["steps"][:1]
    step = definition["steps"][0]
    step.update(outputs=[], success_conditions=[], branches={"success": None, "failure": None, "uncertain": None},
        verification={"kind": "agent_judgment"})
    editor = WorkflowRulesEditor()
    editor.set_step(step, definition, 0)
    editor.condition_template.enabled.setChecked(True)
    rule, _ = editor.rules(step["action"]["kind"])
    assert editor.validation_error is None
    step["verification"] = rule
    saved = programs.save(WORKFLOW, original["content_sha256"], definition, "template-ui-save")
    assert saved["definition"]["steps"][0]["review_status"] == "pending"
    reviewed = deepcopy(saved["definition"])
    reviewed["steps"][0]["review_status"] = "reviewed"
    approved = programs.save(WORKFLOW, saved["content_sha256"], reviewed, "template-ui-review")
    editor.close()
    reopened = WorkflowRulesEditor()
    pinned = programs.load(WORKFLOW, approved["program_id"])
    reopened.set_step(pinned["definition"]["steps"][0], pinned["definition"], 0)
    assert reopened.rules("input_sequence")[0] == rule
    first = trials.start(WORKFLOW, approved["program_id"], step["step_id"], {"query": "R-001"}, "template-ui-run-a")
    second = trials.start(WORKFLOW, approved["program_id"], step["step_id"], {"query": "R-002"}, "template-ui-run-b")
    assert first["condition_snapshots"][step["step_id"]]["typed_parameters"] == {"record_id": "R-001"}
    assert second["condition_snapshots"][step["step_id"]]["typed_parameters"] == {"record_id": "R-002"}
    reopened.condition_template.template_text.setPlainText("The selected record number is {record_id}.")
    edited_rule, _ = reopened.rules("input_sequence")
    assert edited_rule["condition_binding"]["template"]["revision"] == 2
    changed = deepcopy(pinned["definition"])
    changed["steps"][0]["verification"] = edited_rule
    new = programs.save(WORKFLOW, approved["content_sha256"], changed, "template-ui-save-revision")
    assert new["definition"]["steps"][0]["review_status"] == "pending"
    assert programs.load(WORKFLOW, approved["program_id"]) == pinned
    reopened.close()
