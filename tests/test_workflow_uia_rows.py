from copy import deepcopy

import pytest

from app.learning_memory.uia_rows import resolve_uia_row, validate_visible_row_strategy


def scene():
    identity = {"handle": 91, "process_id": 42, "process_create_time": 17.5}
    capture = {"capture_id": "cap-2", "window_identity": identity,
               "image_size": {"width": 800, "height": 600}, "run_id": "run-2"}
    def control(cid, name, kind, box, ancestors, automation_id=None):
        return {"control_id": cid, "name": name, "control_type": kind, "automation_id": automation_id,
                "bbox": box, "ancestor_control_ids": ancestors, "visible": True, "enabled": True}
    box = lambda x, y, w, h: {"x": x, "y": y, "w": w, "h": h}
    controls = [control("list", "Results", "List", box(10, 40, 490, 360), [] , "results"),
                control("a", "Same title", "ListItem", box(20, 50, 430, 40), ["list"]),
                control("aid", "A-1", "Text", box(30, 53, 100, 30), ["a", "list"], "recordId"),
                control("ab", "Open detail", "Button", box(350, 55, 90, 30), ["a", "list"], "openDetail"),
                control("b", "Same title", "ListItem", box(20, 110, 430, 40), ["list"]),
                control("bid", "B-2", "Text", box(30, 113, 100, 30), ["b", "list"], "recordId"),
                control("bb", "Open detail", "Button", box(350, 115, 90, 30), ["b", "list"], "openDetail")]
    snapshot = {"provider": "windows_uia", "status": "ok", "scan_scope": "bound_window", "scan_complete": True,
                "truncated": False, "provider_tree_valid": True, "capture_id": "cap-2", "window_identity": identity,
                "window": {"handle": 91, "process_id": 42}, "controls": controls}
    strategy = {"kind": "visible_row", "container": {"name": "Results", "control_type": "List", "automation_id": "results"},
                "row": {"control_type": "ListItem"},
                "properties": [{"property": "record_id", "control_type": "Text", "automation_id": "recordId", "read": "name"}],
                "constraints": [{"property": "record_id", "operator": "eq", "value": {"source": "input", "name": "wanted_id"}}],
                "action": {"name": "Open detail", "control_type": "Button", "automation_id": "openDetail"}}
    bindings = {"run_id": "run-2", "inputs": {"wanted_id": "B-2"}, "outputs": {}}
    return snapshot, strategy, capture, bindings


def test_reorder_and_same_title_select_current_id_and_row_local_action():
    snapshot, strategy, capture, bindings = scene()
    result = resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)
    assert result["candidate"]["row_id"] == "b"
    assert result["candidate"]["action_id"] == "bb"
    assert result["candidate"]["click_point"] == {"x": 395, "y": 130}
    snapshot["controls"] = list(reversed(snapshot["controls"]))
    assert resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)["candidate"]["action_id"] == "bb"


def test_inserted_row_and_duplicate_current_id_are_handled_explicitly():
    snapshot, strategy, capture, bindings = scene()
    by_id = {item["control_id"]: item for item in snapshot["controls"]}
    inserted = [deepcopy(by_id[key]) for key in ("a", "aid", "ab")]
    for item in inserted:
        item["control_id"] = "new-" + item["control_id"]
        item["ancestor_control_ids"] = ["new-" + value if value == "a" else value for value in item["ancestor_control_ids"]]
        item["bbox"]["y"] += 120
    inserted[1]["name"] = "C-3"
    snapshot["controls"][1:1] = inserted
    assert resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)["candidate"]["action_id"] == "bb"
    inserted[1]["name"] = "B-2"
    with pytest.raises(ValueError, match="visible_row_ambiguous"):
        resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)


def test_other_row_button_and_missing_property_are_not_guessed():
    snapshot, strategy, capture, bindings = scene()
    snapshot["controls"] = [item for item in snapshot["controls"] if item["control_id"] != "bb"]
    with pytest.raises(ValueError, match="row_action_missing"):
        resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)
    snapshot, strategy, capture, bindings = scene()
    snapshot["controls"] = [item for item in snapshot["controls"] if item["control_id"] != "aid"]
    with pytest.raises(ValueError, match="property_missing"):
        resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)


def test_incomplete_or_empty_tree_and_stale_binding_rejected():
    snapshot, strategy, capture, bindings = scene()
    for changed in (dict(snapshot, scan_complete=False), dict(snapshot, provider_tree_valid=False), dict(snapshot, controls=[]), dict(snapshot, capture_id="old")):
        with pytest.raises(ValueError):
            resolve_uia_row(changed, strategy, capture=capture, bindings=bindings)


def test_nested_row_ancestry_and_out_of_bounds_action_rejected():
    snapshot, strategy, capture, bindings = scene()
    next(item for item in snapshot["controls"] if item["control_id"] == "bb")["ancestor_control_ids"] = ["b", "a", "list"]
    with pytest.raises(ValueError, match="multiple_row"):
        resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)
    snapshot, strategy, capture, bindings = scene()
    next(item for item in snapshot["controls"] if item["control_id"] == "bb")["bbox"]["x"] = 480
    with pytest.raises(ValueError, match="bbox"):
        resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)


def test_output_reference_requires_current_run_and_dynamic_text():
    snapshot, strategy, capture, bindings = scene()
    strategy["constraints"][0]["value"] = {"source": "output", "step_id": "read", "name": "wanted_id"}
    bindings["outputs"] = {"read.wanted_id": {"run_id": "old-run", "value": "B-2"}}
    with pytest.raises(ValueError, match="stale_output"):
        resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)
    bindings["outputs"]["read.wanted_id"]["run_id"] = "run-2"
    assert resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)["candidate"]["action_id"] == "bb"


def test_closed_strategy_rejects_unknown_or_unbounded_fields():
    _, strategy, _, _ = scene()
    assert validate_visible_row_strategy(strategy) == strategy
    invalid = deepcopy(strategy)
    invalid["row"]["name"] = "Same title"
    with pytest.raises(ValueError, match="strategy"):
        validate_visible_row_strategy(invalid)
    invalid = deepcopy(strategy)
    invalid["properties"] *= 17
    with pytest.raises(ValueError, match="strategy"):
        validate_visible_row_strategy(invalid)
