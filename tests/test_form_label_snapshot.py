from copy import deepcopy

import pytest

from app.operation.recognition.control_target import uia_action_identity_matches
from app.operation.screen_reading.uia_provider import _annotate_form_labels


def snapshot():
    return dict(status="ok", scan_complete=True, truncated=False, controls=[
        dict(control_id="label", runtime_id=[1, 1], name="Email", control_type="Text",
             bbox=dict(x=10, y=10, w=70, h=20), visible=True, ancestor_control_ids=["form"]),
        dict(control_id="field", runtime_id=[1, 2], name="Email address", control_type="Edit",
             bbox=dict(x=10, y=35, w=300, h=30), visible=True, enabled=True,
             patterns=["Value", "Text"], ancestor_control_ids=["form"])])


def test_visible_label_alias_preserves_name_and_matches_named_field():
    value = snapshot()
    _annotate_form_labels(value)
    field = value["controls"][1]
    assert field["name"] == "Email address"
    assert uia_action_identity_matches(field, goal="Click the Email input field")
    assert uia_action_identity_matches(field, goal="Click the Email address input field")
    assert not uia_action_identity_matches(field, goal="Click the Mobile input field")
    assert uia_action_identity_matches(field, goal='Click the input field labelled "Email"')


def test_dropdown_current_label_alias_is_not_an_input_or_button():
    value = snapshot()
    value["controls"][1].update(control_type="ComboBox", name=None, patterns=["ExpandCollapse", "Selection"])
    _annotate_form_labels(value)
    field = value["controls"][1]
    assert uia_action_identity_matches(field, goal='Click the dropdown labelled "Email"')
    assert not uia_action_identity_matches(field, goal='Click the input field labelled "Email"')
    assert not uia_action_identity_matches(field, goal='Click the button labelled "Email"')


def test_current_file_control_label_does_not_rename_or_confuse_buttons():
    value = snapshot()
    value["controls"][0]["name"] = "Cover Letter"
    value["controls"][1].update(control_type="Button", name="Choose file: No file chosen", patterns=["Invoke", "Value"])
    _annotate_form_labels(value)
    field = value["controls"][1]
    assert field["name"] == "Choose file: No file chosen"
    assert uia_action_identity_matches(field, goal='Click the button labelled "Cover Letter"')
    assert not uia_action_identity_matches(field, goal='Click the button labelled "Resume"')


@pytest.mark.parametrize("fault", ["incomplete", "truncated", "runtime_id", "bbox", "duplicate"])
def test_visible_label_does_not_outlive_or_broaden_current_binding(fault):
    value = snapshot()
    if fault == "incomplete":
        value["scan_complete"] = False
    if fault == "truncated":
        value["truncated"] = True
    if fault == "duplicate":
        value["controls"].append({**deepcopy(value["controls"][1]), "control_id":"other", "runtime_id":[1,3]})
    _annotate_form_labels(value)
    field = value["controls"][1]
    if fault == "runtime_id":
        field["runtime_id"] = [99]
    if fault == "bbox":
        field["bbox"]["y"] += 20
    assert not uia_action_identity_matches(field, goal="Click the Email input field")


def test_tall_file_control_does_not_prevent_literal_edit_roi(tmp_path, monkeypatch):
    from PIL import Image
    from app.api import vision
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult

    image = tmp_path / "form.png"
    Image.new("RGB", (2560, 1400), "white").save(image)
    goal = 'Click the input field labelled "Preferred Name"'
    label = dict(control_id="preferred-label", runtime_id=[42, 879],
        name="Preferred Name", control_type="Text", bbox={"x": 1047, "y": 443, "w": 91, "h": 15},
        visible=True, enabled=True, patterns=["Text"], ancestor_control_ids=["form"])
    edit = dict(control_id="preferred-edit", runtime_id=[42, 15],
        name="\ufffc", control_type="Edit", bbox={"x": 1047, "y": 465, "w": 451, "h": 31},
        visible=True, enabled=True, patterns=["Value", "Text"], ancestor_control_ids=["form"])
    upload = dict(control_id="upload", runtime_id=[42, 8], name="Choose file", control_type="Button",
        bbox={"x": 1030, "y": 270, "w": 190, "h": 1378}, visible=True, enabled=True,
        patterns=["Invoke", "Value"], ancestor_control_ids=["form"])
    snap = {"status": "ok", "scan_complete": True, "truncated": False,
        "controls": [upload, label, edit]}
    _annotate_form_labels(snap)
    assert edit["form_label_binding"]["label"] == "Preferred Name"
    calls = []
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: calls.append(kw) or {
        "point": {"x": 1264, "y": 480}, "provider": "isolated-model-boundary"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snap), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=2560, height=1400), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    result = response.data["result"]
    assert calls[0]["vista_stage"] == "pathgraph_candidate_roi_refine"
    assert result["candidate_result"]["summary"]["current_uia_literal_identity"]["match_count"] == 1
    assert result["recommended_target"]["element"]["bbox"] == edit["bbox"]
    assert result["recommended_target"]["element"]["evidence"]["screen_inventory_action"]["source_id"] == "preferred-edit"
