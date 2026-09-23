"""同帧文本字段中心仅来自唯一、完整、绑定的 UIA 控件。"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.operation.recognition.current_text_target import current_text_primary_point
from app.operation.recognition.text_match import explicit_target_label


SIZE = {"width": 800, "height": 600}
BOX = {"x": 100, "y": 120, "w": 200, "h": 40}


def fixture(*, control_type="Edit", name="Notice period", label="Notice period"):
    control = {"control_id": "field-1", "runtime_id": [42, 3], "control_type": control_type,
               "name": name, "patterns": ["Value", "Text"], "bbox": dict(BOX),
               "visible": True, "enabled": True}
    if not name:
        control["form_label_binding"] = {"source": "visible_label_geometry", "control_id": "field-1",
                                         "runtime_id": [42, 3], "bbox": dict(BOX), "label": label}
    uia = {"status": "ok", "scan_complete": True, "truncated": False,
           "scan_scope": "bound_window", "controls": [control]}
    fast = {"status": "ready", "uia_scan_complete": True, "uia_scan_truncated": False,
            "raw_uia_snapshot": uia,
            "screen_reading": {"image_path": "frame.png", "image_size": dict(SIZE),
                               "source_layers": {"windows_uia": deepcopy(uia)}}}
    action = {"source": "windows_uia.controls", "source_id": "field-1", "bbox": dict(BOX)}
    candidate = SimpleNamespace(role="input", eligible=True,
        element=SimpleNamespace(bbox=SimpleNamespace(to_dict=lambda: dict(BOX)),
            interaction_policy=SimpleNamespace(allowed=True),
            evidence={"screen_inventory_action": action}))
    return fast, candidate


def locate(fast, candidate, *, label="Notice period", image_path="frame.png", image_size=None):
    return current_text_primary_point(fast, candidate=candidate, image_path=image_path,
                                      image_size=image_size or SIZE, literal_label=label)


def test_named_edit_uses_current_control_center_without_mutation():
    fast, candidate = fixture()
    before = deepcopy(fast)
    assert locate(fast, candidate) == {"point": {"x": 200, "y": 140}, "bbox": BOX,
        "control_id": "field-1", "runtime_id": [42, 3],
        "coordinate_source": "current_uia_named_text_center"}
    assert fast == before


def test_json_quoted_label_does_not_select_truncated_name_field():
    label = 'Say "yes"'
    literal = explicit_target_label(f"Click the input labelled {json.dumps(label)}")
    fast, candidate = fixture(name=label)
    other = deepcopy(fast["raw_uia_snapshot"]["controls"][0])
    other.update(control_id="truncated-field", runtime_id=[42, 4], name="Say \\",
                 bbox={**BOX, "y": 220})
    fast["raw_uia_snapshot"]["controls"].append(other)
    fast["screen_reading"]["source_layers"]["windows_uia"]["controls"].append(deepcopy(other))
    assert locate(fast, candidate, label=literal)["control_id"] == "field-1"
    candidate.element.evidence["screen_inventory_action"].update(
        source_id="truncated-field", bbox=dict(other["bbox"]))
    candidate.element.bbox.to_dict = lambda: dict(other["bbox"])
    assert locate(fast, candidate, label=literal) is None


def test_unnamed_editable_combobox_uses_bound_form_label():
    fast, candidate = fixture(control_type="ComboBox", name="", label="Eligibility to work")
    candidate.role = "combobox"
    assert locate(fast, candidate, label="Eligibility to work")["point"] == {"x": 200, "y": 140}


def test_filtered_layer_keeps_exact_selected_control_from_full_raw_tree():
    fast, candidate = fixture()
    fast["raw_uia_snapshot"]["controls"].extend([
        {"control_id": "pane", "control_type": "Pane", "name": "container"},
        {"control_id": "text", "control_type": "Text", "name": "Notice period"},
    ])
    # 原始树用于同名字段消歧；快速层只保留可用控件。
    assert locate(fast, candidate)["control_id"] == "field-1"


def test_missing_raw_scope_defaults_to_bound_window_as_provider_does():
    fast, candidate = fixture()
    fast["raw_uia_snapshot"].pop("scan_scope")
    assert locate(fast, candidate)["control_id"] == "field-1"


@pytest.mark.parametrize("fault", ["stale_path", "stale_size", "not_ready", "raw_incomplete",
    "layer_incomplete", "raw_truncated", "layer_truncated", "wrong_scope", "layer_mismatch",
    "layer_rewritten", "layer_duplicate",
    "duplicate_label", "duplicate_disabled", "candidate_bbox", "candidate_source", "candidate_id",
    "candidate_role", "candidate_ineligible", "candidate_policy", "disabled", "hidden", "button",
    "missing_patterns", "missing_rid", "outside", "readonly", "password", "stale_binding"])
def test_rejects_unbound_or_ambiguous_text_coordinate(fault):
    fast, candidate = fixture()
    uia = fast["raw_uia_snapshot"]
    control = uia["controls"][0]
    if fault == "stale_path": fast["screen_reading"]["image_path"] = "old.png"
    elif fault == "stale_size": fast["screen_reading"]["image_size"]["width"] = 799
    elif fault == "not_ready": fast["status"] = "partial"
    elif fault == "raw_incomplete": uia["scan_complete"] = False
    elif fault == "layer_incomplete": fast["screen_reading"]["source_layers"]["windows_uia"]["scan_complete"] = False
    elif fault == "raw_truncated": uia["truncated"] = True
    elif fault == "layer_truncated": fast["screen_reading"]["source_layers"]["windows_uia"]["truncated"] = True
    elif fault == "wrong_scope": uia["scan_scope"] = "menu_subtree"
    elif fault == "layer_mismatch": fast["screen_reading"]["source_layers"]["windows_uia"]["controls"] = []
    elif fault == "layer_rewritten": fast["screen_reading"]["source_layers"]["windows_uia"]["controls"][0]["bbox"]["y"] += 1
    elif fault == "layer_duplicate": fast["screen_reading"]["source_layers"]["windows_uia"]["controls"].append(deepcopy(control))
    elif fault in {"duplicate_label", "duplicate_disabled"}:
        other = deepcopy(control)
        other["control_id"] = "field-2"
        other["runtime_id"] = [42, 4]
        other["bbox"]["y"] += 50
        if fault == "duplicate_disabled": other["enabled"] = False
        uia["controls"].append(other)
        fast["screen_reading"]["source_layers"]["windows_uia"]["controls"].append(deepcopy(other))
    elif fault == "candidate_bbox": candidate.element.evidence["screen_inventory_action"]["bbox"]["y"] += 1
    elif fault == "candidate_source": candidate.element.evidence["screen_inventory_action"]["source"] = "seeded"
    elif fault == "candidate_id": candidate.element.evidence["screen_inventory_action"]["source_id"] = "other"
    elif fault == "candidate_role": candidate.role = "button"
    elif fault == "candidate_ineligible": candidate.eligible = False
    elif fault == "candidate_policy": candidate.element.interaction_policy.allowed = False
    elif fault == "disabled": control["enabled"] = False
    elif fault == "hidden": control["visible"] = False
    elif fault == "button": control["control_type"] = "Button"
    elif fault == "missing_patterns": control["patterns"] = ["Scroll"]
    elif fault == "missing_rid": control["runtime_id"] = []
    elif fault == "outside": control["bbox"]["x"] = 750
    elif fault == "readonly": control["is_read_only"] = True
    elif fault == "password": control["is_password"] = True
    elif fault == "stale_binding":
        control["name"] = ""
        control["form_label_binding"] = {"source": "visible_label_geometry", "control_id": "field-1",
            "runtime_id": [42, 3], "bbox": {**BOX, "y": 121}, "label": "Notice period"}
    assert locate(fast, candidate) is None


def test_same_label_button_and_static_text_do_not_make_field_ambiguous():
    fast, candidate = fixture()
    for kind in ("Button", "Text"):
        extra = {"control_id": kind, "runtime_id": [55, len(kind)], "control_type": kind,
            "name": "Notice period", "patterns": ["Invoke"] if kind == "Button" else [],
            "bbox": {"x": 400, "y": 120, "w": 100, "h": 30}, "visible": True, "enabled": True}
        fast["raw_uia_snapshot"]["controls"].append(extra)
        fast["screen_reading"]["source_layers"]["windows_uia"]["controls"].append(deepcopy(extra))
    assert locate(fast, candidate)["control_id"] == "field-1"
