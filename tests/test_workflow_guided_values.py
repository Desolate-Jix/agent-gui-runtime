"""通过选择器绑定本次输入与上游输出，缺失引用不能被悄悄替换。"""
from copy import deepcopy

import pytest
from PySide6.QtWidgets import QInputDialog

from tests.test_workflow_steps_ui import generated, qt_app, _pane


def _choose(combo, value):
    index = next((i for i in range(combo.count()) if combo.itemData(i) == value), -1)
    assert index >= 0, value
    combo.setCurrentIndex(index)


def _choices(combo):
    return [combo.itemData(i) for i in range(combo.count())
            if combo.itemData(i) is not None and combo.model().item(i).isEnabled()]


@pytest.fixture
def pane(qt_app, generated):
    widget = _pane(qt_app, generated)
    try:
        yield widget
    finally:
        widget.discard()
        widget.close()


def test_text_binding_choices_track_current_declarations(pane):
    original = {"source": "input", "name": "place"}
    assert pane.text_binding.currentData() == original
    pane._add_table_row(pane.inputs, ["other", "text", "是"])
    pane._add_table_row(pane.inputs, ["count", "number", "否"])
    assert _choices(pane.text_binding) == [original, {"source": "input", "name": "other"}]
    pane.inputs.cellWidget(0, 1).setCurrentIndex(1)
    assert pane.text_binding.currentData() == original
    assert "不可用" in pane.text_binding.currentText()
    pane.save_button.click()
    assert pane.dirty and pane.snapshot["program_id"] is None
    assert "place" in pane.status.text() and "文本" in pane.status.text()
    pane.inputs.cellWidget(0, 1).setCurrentIndex(0)
    assert pane.text_binding.currentData() == original
    assert "不可用" not in pane.text_binding.currentText()
    pane.inputs.selectRow(0)
    pane.remove_input.click()
    assert pane.text_binding.currentData() == original
    assert "不可用" in pane.text_binding.currentText()
    _choose(pane.text_binding, {"source": "input", "name": "other"})
    pane.save_button.click()
    assert not pane.dirty
    assert pane.snapshot["definition"]["steps"][0]["action"]["text"] == {
        "source": "input", "name": "other"}


def test_source_switch_requires_explicit_choice_and_retains_literal(pane):
    _choose(pane.text_source, "constant")
    pane.text_value.setText(" 本次固定文字 ")
    _choose(pane.text_source, "input")
    assert pane.text_binding.currentData() is None
    pane.save_button.click()
    assert pane.dirty and "选择" in pane.status.text()
    _choose(pane.text_source, "constant")
    pane.save_button.click()
    assert not pane.dirty
    assert pane.snapshot["definition"]["steps"][0]["action"]["text"] == {
        "source": "constant", "value": " 本次固定文字 "}


def test_output_choices_exclude_current_future_and_nontext_and_keep_broken_reference(pane):
    first = pane.definition["steps"][0]
    first["outputs"] = [{"name": "status", "type": "text"}, {"name": "matched", "type": "boolean"}]
    second = deepcopy(first)
    second.update(step_id="fill-status", title="填写当前状态", outputs=[{"name": "own", "type": "text"}])
    second["action"] = {"kind": "input_sequence", "field_goal": "状态字段",
        "text": {"source": "output", "step_id": first["step_id"], "name": "status"},
        "clear_existing": True, "submit_search": False}
    third = deepcopy(first)
    third.update(step_id="future-read", title="后续读取", outputs=[{"name": "future", "type": "text"}])
    pane.definition["steps"].extend([second, third])
    pane._selected_id = second["step_id"]
    pane._refresh_steps()
    expected = {"source": "output", "step_id": first["step_id"], "name": "status"}
    assert _choices(pane.text_binding) == [expected]
    assert pane.text_binding.currentData() == expected
    pane.up_button.click()
    assert pane.definition["steps"][0]["step_id"] == second["step_id"]
    assert pane.text_binding.currentData() == expected and "不可用" in pane.text_binding.currentText()
    pane.steps.setCurrentRow(1)
    assert pane._selected_id == first["step_id"], "缺失引用不能锁死修正来源的导航"
    pane.steps.setCurrentRow(0)
    pane.down_button.click()
    assert _choices(pane.text_binding) == [expected]


def test_constant_to_input_updates_declaration_and_binding_together(pane, monkeypatch):
    _choose(pane.text_source, "constant")
    pane.text_value.setText("教学编号")
    pane._add_table_row(pane.inputs, ["value_1", "text", "否"])
    suggested = []
    def answer(*args, **kwargs):
        suggested.append(kwargs["text"])
        return kwargs["text"], True
    monkeypatch.setattr(QInputDialog, "getText", answer)
    pane.parameterize_button.click()
    assert suggested == ["value_2"]
    assert pane.definition["steps"][0]["action"]["text"] == {"source": "input", "name": "value_2"}
    assert pane.definition["inputs"][-1] == {"name": "value_2", "type": "text", "required": True}
    assert pane.definition["inputs"][-2] == {"name": "value_1", "type": "text", "required": False}
    assert pane.dirty
    pane.save_button.click()
    assert not pane.dirty
    saved = pane.snapshot["program_id"]
    pane._install(pane.facade.load_workflow_program(pane.snapshot["workflow_id"]))
    assert pane.snapshot["program_id"] == saved
    assert pane.text_binding.currentData() == {"source": "input", "name": "value_2"}


@pytest.mark.parametrize("answer,accepted", [("place", False), ("place", True), ("中文名称", True)])
def test_parameter_creation_cancel_or_invalid_name_preserves_draft(pane, monkeypatch, answer, accepted):
    _choose(pane.text_source, "constant")
    pane.text_value.setText("示例")
    pane._commit_all()
    before = deepcopy(pane.definition)
    count = pane.inputs.rowCount()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **kw: (answer, accepted))
    pane.parameterize_button.click()
    assert pane.definition == before
    assert pane.inputs.rowCount() == count
    assert pane.text_source.currentData() == "constant"


def test_duplicate_input_name_is_unavailable_not_a_silent_alias(pane):
    pane._add_table_row(pane.inputs, ["place", "text", "是"])
    assert "不可用" in pane.text_binding.currentText()
    assert _choices(pane.text_binding) == []
    pane.save_button.click()
    assert pane.dirty and pane.snapshot["program_id"] is None


def test_normal_run_entry_opens_panel_without_dispatch_and_graph_preserves_binding(pane):
    pane.open_run_button.click()
    assert pane.editor_tabs.currentWidget() is pane.run_panel
    assert not pane.run_panel.run_button.isEnabled()
    assert pane._run_id is None
    pane.nav_tabs.setCurrentIndex(1)
    pane.relation_views.setCurrentIndex(1)
    pane._add_table_row(pane.inputs, ["current_id", "text", "是"])
    _choose(pane.text_binding, {"source": "input", "name": "current_id"})
    assert pane.definition["steps"][0]["action"]["text"] == {"source": "input", "name": "current_id"}
    pane.inputs.cellWidget(1, 1).setCurrentIndex(1)
    pane.save_button.click()
    assert pane.dirty and "current_id" in pane.status.text()
    assert pane.definition["steps"][0]["action"]["text"]["name"] == "current_id"


def test_trial_input_dialog_is_disposed_after_accept_or_cancel(pane, qt_app):
    from PySide6.QtCore import QCoreApplication, QEvent
    from app.learning_memory.workflow_input_dialog import WorkflowInputDialog
    from tests.test_workflow_guided_journey import _drive_dialog
    values = []
    for accepted in (True, False):
        def respond(dialog):
            dialog.editors["place"].setText("本次地点")
            dialog.accept() if accepted else dialog.reject()
        _drive_dialog(WorkflowInputDialog, lambda: values.append(pane._trial_inputs()), respond)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not pane.findChildren(WorkflowInputDialog)
    assert values == [{"place": "本次地点"}, None]
