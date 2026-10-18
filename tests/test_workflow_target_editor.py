"""目标编辑只读取固定证据、预览并交付草稿。"""
from copy import deepcopy
import time

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.learning_memory.workflow_target_editor import WorkflowTargetEditor


REF = {"recipe_id": "target-recipe-" + "a" * 64, "interface_key": "search", "state_key": "home"}
STEP = {"step_id": "second", "action": {"kind": "click", "goal": "Open", "target_memory": REF}}
DEFINITION = {"inputs": [{"name": "wanted", "type": "text"}], "steps": [
    {"step_id": "first", "title": "Read", "outputs": [{"name": "found", "type": "text"}]},
    STEP]}
_APP = None


def _control(cid, name, kind, chain=(), aid=None):
    return {"control_id": cid, "name": name, "control_type": kind, "automation_id": aid,
            "ancestor_control_ids": list(chain), "visible": True, "enabled": True,
            "bbox": {"x": 5, "y": 5, "w": 20, "h": 12}}


def _context(path, strategies=None, tree=True):
    controls = [_control("list", "Results", "List", aid="results"),
                _control("row", "A", "ListItem", ["list"]),
                _control("text", "A-1", "Text", ["row", "list"], "recordId"),
                _control("open", "Open", "Button", ["row", "list"], "openDetail")]
    return {"recipe": {"recipe_id": REF["recipe_id"], "contract_version": "target_recipe.v2",
                       "strategies": strategies or [{"kind": "uia", "name": "Open", "control_type": "Button",
                                                      "automation_id": "openDetail"}]},
            "frame": {"image_path": str(path)}, "controls": controls,
            "uia": {"snapshot": {"provider_tree_valid": tree}}}


class FakeFacade:
    def __init__(self, context):
        self.context = context
        self.reads = []
        self.proposals = []

    def read_target_edit_context(self, reference, proposed_recipe=None):
        self.reads.append((reference, proposed_recipe))
        return deepcopy(self.context)

    def propose_target_edit(self, reference, action, strategies, proposed_recipe=None,
                            preview_inputs=None, preview_outputs=None):
        self.proposals.append((reference, action, strategies, proposed_recipe, preview_inputs, preview_outputs))
        return {"recipe": {"recipe_id": "new"}, "reference": {"recipe_id": "new"},
                "preview": {"status": "matched", "reason": "unique", "candidate": {
                    "bbox": {"x": 5, "y": 5, "w": 20, "h": 12}}},
                "preview_scope": "learning_capture", "validation": "unverified"}


def _wait(app, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("异步控件未结束")


def _editor(tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    app = _APP
    path = tmp_path / "evidence.png"
    assert QImage(80, 50, QImage.Format.Format_RGB32).save(str(path))
    facade = FakeFacade(_context(path))
    editor = WorkflowTargetEditor(facade)
    return app, facade, editor


def test_no_automatic_io_preview_and_fresh_action(tmp_path):
    app, facade, editor = _editor(tmp_path)
    editor.set_step(STEP, DEFINITION)
    assert not facade.reads and not facade.proposals
    editor.load_button.click()
    _wait(app, lambda: len(facade.reads) == 1 and not editor.is_busy)
    assert editor.preview_button.isEnabled()
    current = deepcopy(STEP["action"])
    editor.action_provider = lambda: deepcopy(current)
    captured = []
    editor.proposalReady.connect(captured.append)
    editor.preview_button.click()
    _wait(app, lambda: len(facade.proposals) == 1 and not editor.is_busy)
    editor.apply_button.click()
    assert captured[0]["step_id"] == "second"
    assert captured[0]["original_action"] == STEP["action"]
    assert captured[0]["result"]["validation"] == "unverified"
    current["goal"] = "Changed"
    editor.apply_button.click()
    assert len(captured) == 1
    assert "重新预览" in editor.status.text()
    editor.close()


def test_row_strategy_only_from_ancestor_tree_and_declared_binding(tmp_path):
    app, facade, editor = _editor(tmp_path)
    editor.set_step(STEP, DEFINITION)
    editor._install_context(deepcopy(facade.context))
    editor.mode.setCurrentIndex(1)
    editor.row_type.setCurrentIndex(editor.row_type.findData("ListItem"))
    editor.value_source.setCurrentIndex(1)
    assert editor.property_control.count() == 1
    assert editor.row_action.count() == 1
    assert editor.binding.count() == 1
    strategy = editor._strategy()
    assert strategy["container"] == {"name": "Results", "control_type": "List", "automation_id": "results"}
    assert strategy["properties"] == [{"property": "target_value", "control_type": "Text",
                                        "automation_id": "recordId", "read": "name"}]
    assert strategy["constraints"][0]["value"] == {"source": "input", "name": "wanted"}
    editor.value_source.setCurrentIndex(2)
    editor.sample.setText("B-2")
    assert editor._request_key()[3] == {"first.found": {"run_id": "target-edit-preview", "value": "B-2"}}
    editor.value_source.setCurrentIndex(1)
    editor.sample.clear()
    assert strategy["action"]["automation_id"] == "openDetail"
    assert not editor.preview_button.isEnabled()
    editor.sample.setText("A-1")
    assert editor.preview_button.isEnabled()
    assert editor._request_key()[2] == {"wanted": "A-1"}
    assert strategy["constraints"][0]["value"] == {"source": "input", "name": "wanted"}
    editor.close()


def test_complex_recipe_preserves_rules_and_missing_tree_blocks_row(tmp_path):
    app, facade, editor = _editor(tmp_path)
    editor.set_step(STEP, DEFINITION)
    complex_context = deepcopy(facade.context)
    complex_context["recipe"]["strategies"] = [
        {"kind": "uia", "name": "Open", "control_type": "Button", "automation_id": "openDetail"},
        {"kind": "uia", "name": "A", "control_type": "ListItem"}]
    editor._install_context(complex_context)
    assert editor.strategy_choice.count() == 2
    editor.strategy_down.click()
    assert editor.has_unapplied_changes
    editor.preview_button.click()
    _wait(app, lambda: len(facade.proposals) == 1 and not editor.is_busy)
    assert facade.proposals[0][2] == [complex_context["recipe"]["strategies"][1],
                                      complex_context["recipe"]["strategies"][0]]
    editor.strategy_delete.click()
    assert editor.strategy_choice.count() == 1
    editor.preview_button.click()
    _wait(app, lambda: len(facade.proposals) == 2 and not editor.is_busy)
    assert facade.proposals[1][2] == [complex_context["recipe"]["strategies"][1]]
    editor.set_step(STEP, DEFINITION)
    editor._install_context(_context(tmp_path / "evidence.png", tree=False))
    editor.mode.setCurrentIndex(1)
    assert not editor.apply_button.isEnabled()
    assert "完整控件层级证据" in editor.status.text()
    editor.close()


def test_multiple_row_conditions_and_samples_are_separate(tmp_path):
    app, facade, editor = _editor(tmp_path)
    recipe = {"kind": "visible_row", "container": {"name": "Results", "control_type": "List", "automation_id": "results"},
        "row": {"control_type": "ListItem"},
        "properties": [{"property": "title", "control_type": "Text", "automation_id": "recordId", "read": "name"}],
        "constraints": [{"property": "title", "operator": "eq", "value": {"source": "input", "name": "wanted"}}],
        "action": {"name": "Open", "control_type": "Button", "automation_id": "openDetail"}}
    editor.set_step(STEP, DEFINITION)
    editor._install_context(_context(tmp_path / "evidence.png", [recipe]))
    editor.sample.setText("A-1")
    editor.condition_add.click()
    assert editor.condition_choice.count() == 2
    editor.value_source.setCurrentIndex(editor.value_source.findData("constant"))
    editor.constant.setText("B-2")
    editor.preview_button.click()
    _wait(app, lambda: len(facade.proposals) == 1 and not editor.is_busy)
    strategy = facade.proposals[0][2][0]
    assert len(strategy["constraints"]) == 2
    assert strategy["constraints"][0] == recipe["constraints"][0]
    assert facade.proposals[0][4] == {"wanted": "A-1"}
    assert all("A-1" not in str(rule) for rule in strategy["constraints"])
    editor.close()


def test_existing_complex_row_round_trips_without_truncation(tmp_path):
    app, facade, editor = _editor(tmp_path)
    rule = {"kind": "visible_row", "container": {"name": "Results", "control_type": "List", "automation_id": "results"},
        "row": {"control_type": "ListItem"},
        "properties": [{"property": "title", "control_type": "Text", "automation_id": "recordId", "read": "name"},
                       {"property": "number", "control_type": "Text", "automation_id": "recordId", "read": "name"}],
        "constraints": [{"property": "title", "operator": "eq", "value": {"source": "input", "name": "wanted"}},
                        {"property": "number", "operator": "contains", "value": {"source": "constant", "value": "1"}}],
        "action": {"name": "Open", "control_type": "Button", "automation_id": "openDetail"}}
    editor.set_step(STEP, DEFINITION)
    editor._install_context(_context(tmp_path / "evidence.png", [rule]))
    assert editor.condition_choice.count() == 2
    editor.sample.setText("A-1")
    editor.condition_choice.setCurrentIndex(1)
    editor.condition_choice.setCurrentIndex(0)
    editor.preview_button.click()
    _wait(app, lambda: len(facade.proposals) == 1 and not editor.is_busy)
    assert facade.proposals[0][2] == [rule]
    assert not editor.has_unapplied_changes
    editor.close()


def test_stale_load_does_not_install_after_step_change(tmp_path):
    app, facade, editor = _editor(tmp_path)
    from threading import Event
    entered, release = Event(), Event()
    original = facade.read_target_edit_context

    def delayed(*args, **kwargs):
        entered.set()
        release.wait(2)
        return original(*args, **kwargs)

    facade.read_target_edit_context = delayed
    editor.set_step(STEP, DEFINITION)
    editor.load_evidence()
    assert entered.wait(1)
    editor.set_step({"step_id": "none", "action": {"kind": "click", "goal": "Other"}}, DEFINITION)
    release.set()
    _wait(app, lambda: not editor.is_busy)
    assert editor._context is None
    assert not editor.apply_button.isEnabled()
    editor.close()


def test_changed_tracks_rules_but_not_preview_sample(tmp_path):
    app, facade, editor = _editor(tmp_path)
    editor.set_step(STEP, DEFINITION)
    changes = []
    editor.changed.connect(lambda: changes.append(True))
    editor._install_context(deepcopy(facade.context))
    assert not editor.has_unapplied_changes and not changes
    editor.sample.setText("preview only")
    assert not editor.has_unapplied_changes and not changes
    editor.mode.setCurrentIndex(1)
    assert editor.has_unapplied_changes and changes
    editor.set_step(STEP, DEFINITION)
    assert not editor.has_unapplied_changes
    editor.close()


def test_refresh_definition_preserves_selection_and_rejects_removed_variable(tmp_path):
    app, facade, editor = _editor(tmp_path)
    editor.set_step(STEP, DEFINITION)
    editor._install_context(deepcopy(facade.context))
    editor.mode.setCurrentIndex(1)
    editor.row_type.setCurrentIndex(editor.row_type.findData("ListItem"))
    editor.value_source.setCurrentIndex(1)
    editor.sample.setText("A-1")
    editor.refresh_definition({**DEFINITION, "inputs": [
        {"name": "wanted", "type": "text"}, {"name": "new", "type": "text"}]})
    assert editor.binding.currentData() == (None, "wanted")
    assert editor.preview_button.isEnabled()
    editor.refresh_definition({**DEFINITION, "inputs": [{"name": "new", "type": "text"}]})
    assert editor.binding.currentData() is None
    assert editor.binding.currentText().startswith("原变量已不在")
    assert not editor.preview_button.isEnabled()
    assert "所选变量已不在" in editor.status.text()
    editor.refresh_definition({**DEFINITION, "inputs": [
        {"name": "new", "type": "text"}, {"name": "wanted", "type": "text"}]})
    assert editor.binding.currentData() == (None, "wanted")
    assert "变量已恢复" in editor.status.text()
    editor.refresh_definition({**DEFINITION, "inputs": [
        {"name": "new", "type": "text"}, {"name": "wanted", "type": "number"}]})
    assert editor.binding.currentData() is None
    assert not editor.preview_button.isEnabled()
    editor.close()
