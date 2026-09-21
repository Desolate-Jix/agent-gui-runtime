from copy import deepcopy
import importlib.util

import pytest


BOX = {"x": 0, "y": 0, "w": 2560, "h": 1335}
FULL_BOX = {"x": 0, "y": 0, "width": 2560, "height": 1335}
POINT = {"x": 1264, "y": 681}
GOAL = "Right click inside the text area of the document"


def plan_fixture():
    # 复现本轮回执的数据形状与几何；不读取历史内容或通知文字。
    control = {"provider": "windows_uia", "control_id": "uia_1_15",
               "control_type": "Edit", "bbox": dict(BOX), "enabled": True,
               "visible": True, "patterns": ["Value", "Scroll"]}
    action = {"source": "windows_uia.controls", "source_id": "uia_1_15",
              "role": "input", "bbox": dict(BOX)}
    return {"image_path": "fresh-capture.png", "recommended_target": {
        "element": {"bbox": dict(BOX), "role": "input", "evidence": {
            "screen_inventory_action": action}}}, "parse_result": {"screen_reading": {
                "image_path": "fresh-capture.png", "image_size": {"width": 2560, "height": 1357},
                "source_layers": {"windows_uia": {"provider": "windows_uia", "status": "ok",
                    "scan_complete": True, "truncated": False, "scan_scope": "bound_window",
                    "controls": [control]}}}}}


def classify(plan=None, point=None, **kwargs):
    assert importlib.util.find_spec("app.operation.recognition.click_visibility") is not None, "visibility classifier is not implemented"
    from app.operation.recognition.click_visibility import recognition_click_visibility
    return recognition_click_visibility(plan if plan is not None else plan_fixture(),
        point if point is not None else POINT,
        **{"goal": GOAL, "click_kind": "right", "local_operator": True, **kwargs})


def test_current_editable_container_right_click_uses_actual_input_footprint():
    plan = plan_fixture()
    before = deepcopy(plan)
    result = classify(plan)
    assert result["scope"] == "editable_container_point"
    assert result["target_bbox"] == {"x": 1264, "y": 681, "width": 1, "height": 1}
    assert result["candidate_bbox"] == FULL_BOX
    assert result["control_id"] == "uia_1_15"
    assert plan == before


@pytest.mark.parametrize("kwargs", [
    {"local_operator": False}, {"local_operator": 1}, {"click_kind": "left"},
    {"click_kind": "double"}, {"goal": 'Right click the word "probe" in the text area'},
    {"goal": "Right click the button inside the text area"},
    {"goal": "Right click the menu item inside the text area"},
    {"goal": 'Right click the "Search" text field'},
])
def test_other_actions_preserve_full_candidate_bbox(kwargs):
    result = classify(**kwargs)
    assert result["scope"] == "candidate_bbox"
    assert result["target_bbox"] == FULL_BOX


@pytest.mark.parametrize("mutation", [
    "partial", "truncated", "missing_complete", "missing_truncated", "bad_status", "menu_scope",
    "missing_image", "missing_reading_image", "different_image", "missing_size", "small_size",
    "duplicate", "duplicate_other_id", "duplicate_id_elsewhere", "duplicate_outside_image", "wrong_role", "wrong_pattern",
    "hidden", "disabled", "wrong_id", "wrong_source", "action_bbox", "control_bbox", "refined_bbox",
    "missing_control_id", "nan_control", "negative_control", "wrong_control_provider",
])
def test_incomplete_or_mismatched_evidence_does_not_shrink_bbox(mutation):
    plan = plan_fixture()
    reading = plan["parse_result"]["screen_reading"]
    layer = reading["source_layers"]["windows_uia"]
    control = layer["controls"][0]
    action = plan["recommended_target"]["element"]["evidence"]["screen_inventory_action"]
    if mutation == "partial": layer["scan_complete"] = False
    elif mutation == "truncated": layer["truncated"] = True
    elif mutation == "missing_complete": layer.pop("scan_complete")
    elif mutation == "missing_truncated": layer.pop("truncated")
    elif mutation == "bad_status": layer["status"] = "error"
    elif mutation == "menu_scope": layer["scan_scope"] = "menu_subtree"
    elif mutation == "missing_image": plan.pop("image_path")
    elif mutation == "missing_reading_image": reading.pop("image_path")
    elif mutation == "different_image": reading["image_path"] = "stale.png"
    elif mutation == "missing_size": reading.pop("image_size")
    elif mutation == "small_size": reading["image_size"]["width"] = 1000
    elif mutation.startswith("duplicate"):
        extra = deepcopy(control)
        if mutation == "duplicate_other_id": extra["control_id"] = "other"
        if mutation == "duplicate_id_elsewhere": extra["bbox"] = {"x": 1, "y": 1, "w": 10, "h": 10}
        if mutation == "duplicate_outside_image": extra.update(control_id="other", bbox={"x": 0, "y": 0, "w": 3000, "h": 1335})
        layer["controls"].append(extra)
    elif mutation == "wrong_role": control["control_type"] = "Pane"
    elif mutation == "wrong_pattern": control["patterns"] = ["Scroll"]
    elif mutation == "hidden": control["visible"] = False
    elif mutation == "disabled": control["enabled"] = False
    elif mutation == "wrong_id": action["source_id"] = "stale"
    elif mutation == "wrong_source": action["source"] = "vision"
    elif mutation == "action_bbox": action["bbox"]["w"] = 2000
    elif mutation == "control_bbox": control["bbox"]["w"] = 2000
    elif mutation == "refined_bbox": plan["recommended_target"]["refined_bbox"] = {"x": 1000, "y": 600, "w": 500, "h": 200}
    elif mutation == "missing_control_id": control.pop("control_id")
    elif mutation == "nan_control": control["bbox"]["x"] = float("nan")
    elif mutation == "negative_control": control["bbox"]["x"] = -1
    elif mutation == "wrong_control_provider": control["provider"] = "vision"
    result = classify(plan)
    assert result["scope"] == "candidate_bbox"
    assert result["target_bbox"] == ({"x": 1000, "y": 600, "width": 500, "height": 200} if mutation == "refined_bbox" else FULL_BOX)


@pytest.mark.parametrize("point", [{"x": 2560, "y": 681}, {"x": 1264, "y": 1335},
    {"x": -1, "y": 681}, {"x": 1264.0, "y": 681}, {"x": True, "y": 681},
    {"x": float("inf"), "y": 681}, {"y": 681}])
def test_invalid_or_outside_point_preserves_region_requirement(point):
    result = classify(point=point)
    assert result["scope"] == "candidate_bbox"
    assert result["target_bbox"] == FULL_BOX


@pytest.mark.parametrize("kind,patterns", [("Textbox", ["Text"]), ("Edit", ["Value"])])
def test_editable_role_and_pattern_variants(kind, patterns):
    plan = plan_fixture()
    control = plan["parse_result"]["screen_reading"]["source_layers"]["windows_uia"]["controls"][0]
    control.update(control_type=kind, patterns=patterns)
    assert classify(plan)["scope"] == "editable_container_point"


def test_absent_candidate_bbox_keeps_existing_absent_bbox_semantics():
    plan = plan_fixture()
    plan["recommended_target"] = {}
    assert classify(plan)["target_bbox"] is None
