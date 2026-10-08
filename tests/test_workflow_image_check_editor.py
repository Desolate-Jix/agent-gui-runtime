import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
from hashlib import sha256
import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from app.learning_memory.workflow_rules_editor import WorkflowRulesEditor


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def option(tmp_path):
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill(0xffabcdef)
    path = tmp_path / "learned.png"
    assert image.save(str(path))
    return {"reference_sha256": sha256(path.read_bytes()).hexdigest(),
            "reference_size": [200, 100], "image_path": str(path), "label": "已学结果"}


def step(**kwargs):
    return {"step_id": "open", "action": {"kind": "click"}, "outputs": [],
            "verification": {"kind": "agent_judgment"}, **kwargs}


def load(editor, value, options):
    editor.set_step(value, {"inputs": [], "steps": [value]}, 0)
    editor.set_image_options(options)


def test_default_disabled_requires_explicit_stable_boxes_and_can_turn_off(app, option):
    editor = WorkflowRulesEditor()
    load(editor, step(), [option])
    image = editor.image_check_editor
    assert not image.enabled.isChecked()
    assert editor.rules("click") == ({"kind": "agent_judgment"}, None)
    image.enabled.setChecked(True)
    editor.rules("click")
    assert editor.validation_error
    image.source.setCurrentIndex(1)
    image.set_box("template_bbox", [10, 10, 30, 20])
    image.set_box("search_roi", [0, 0, 100, 60])
    result = editor.rules("click")[0]
    assert result["image_check"]["template_bbox"] == [10, 10, 30, 20]
    assert result["image_check"]["reference_sha256"] == option["reference_sha256"]
    image.enabled.setChecked(False)
    assert editor.rules("click") == ({"kind": "agent_judgment"}, None)
    editor.close()


@pytest.mark.parametrize("decision", [False, True])
def test_roundtrip_missing_source_preserves_config_and_disable_only_removes_image_check(app, option, decision):
    config = {"contract_version": "workflow_image_check.v1", "reference_sha256": option["reference_sha256"],
              "reference_size": [200, 100], "template_bbox": [10, 10, 30, 20],
              "search_roi": [0, 0, 100, 60], "threshold": 0.95}
    value = step(verification={"kind": "agent_judgment", "image_check": config})
    if decision:
        value["verification"]["decision_condition"] = "The reviewed detail is open."
    original = deepcopy(value)
    editor = WorkflowRulesEditor()
    load(editor, value, [])
    assert editor.rules("click")[0] == value["verification"]
    assert "不可用" in editor.image_check_editor.status.text()
    editor.image_check_editor.threshold.setValue(0.9)
    assert editor.rules("click")[0]["image_check"]["reference_sha256"] == config["reference_sha256"]
    assert editor.rules("click")[0].get("decision_condition") == value["verification"].get("decision_condition")
    assert value == original
    editor.image_check_editor.enabled.setChecked(False)
    assert editor.rules("click")[0] == {key: item for key, item in value["verification"].items() if key != "image_check"}
    load(editor, original, [option])
    assert editor.rules("click")[0] == original["verification"]
    editor.close()


@pytest.mark.parametrize("value", [step(outputs=[{"name": "detail", "type": "text"}]),
    step(action={"kind": "read_text"}), step(read_spec={"method": "agent_read"})])
def test_dynamic_output_and_reading_steps_cannot_enable_image_check(app, option, value):
    editor = WorkflowRulesEditor()
    load(editor, value, [option])
    assert not editor.image_check_editor.enabled.isEnabled()
    editor.close()


def test_canvas_geometry_and_out_of_bounds_are_not_silently_accepted(app, option):
    editor = WorkflowRulesEditor()
    load(editor, step(), [option])
    image = editor.image_check_editor
    image.enabled.setChecked(True)
    image.source.setCurrentIndex(1)
    image.set_box("template_bbox", [10, 10, 30, 20])
    image.set_box("search_roi", [0, 0, 100, 60])
    image.canvas.regionGeometryChanged.emit("template_bbox", [12, 12, 25, 18])
    assert editor.rules("click")[0]["image_check"]["template_bbox"] == [12, 12, 25, 18]
    image.set_box("template_bbox", [195, 10, 30, 20])
    editor.rules("click")
    assert editor.validation_error
    editor.close()


def test_changing_action_to_read_cannot_retain_enabled_image_check(app, option):
    config = {'contract_version': 'workflow_image_check.v1',
        'reference_sha256': option['reference_sha256'], 'reference_size': [200, 100],
        'template_bbox': [10, 10, 30, 20], 'search_roi': [0, 0, 100, 60], 'threshold': .95}
    editor = WorkflowRulesEditor()
    load(editor, step(verification={'kind': 'agent_judgment', 'image_check': config}), [option])
    editor.set_action_kind('read_text')
    editor.rules('read_text')
    assert editor.validation_error
    editor.close()
