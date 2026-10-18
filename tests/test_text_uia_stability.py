"""填写 UIA 稳定性的合成网页/原生树回归，不读取桌面或运行模型。"""
from copy import deepcopy
from hashlib import sha256

import pytest

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.text_field_evidence import TextFieldIdentity
from app.agent.text_uia_stability import compare_fill_uia_context


def _fixture(*, context_type="Document", label="Search", names=("Status 1", "Status 2")):
    identity = TextFieldIdentity("field", 123, 456, 1000.5, (42, 4), (100, 50, 1000, 700), (150, 220, 300, 40))
    def control(cid, kind, box, ancestors, number, name=None):
        bbox = dict(zip(("x", "y", "w", "h"), box))
        return {"provider": "windows_uia", "control_id": cid, "name": name,
            "control_type": kind, "automation_id": cid, "class_name": "SyntheticControl",
            "bbox": bbox, "screen_bbox": {**bbox, "x": bbox["x"]+100, "y": bbox["y"]+50},
            "enabled": True, "visible": True, "patterns": ["Value"] if kind == "Edit" else ["Invoke"] if kind == "Button" else [],
            "runtime_id": [42, number], "ancestor_control_ids": ancestors}
    controls = [
        control("root", "Window", (0, 0, 1000, 700), [], 1),
        control("toolbar", "ToolBar", (0, 0, 1000, 60), ["root"], 2),
        control("badge", "Button", (800, 10, 40, 30), ["toolbar", "root"], 3, names[0]),
        control("context", context_type, (100, 150, 700, 450), ["root"], 5),
        control("field", "Edit", identity.control_bbox, ["context", "root"], 4, label),
        control("label", "Text", (150, 180, 120, 20), ["context", "root"], 6, label),
    ]
    original_uia = {"provider": "windows_uia", "provider_version": "windows_uia_provider_v1", "status": "ok",
        "scan_budget": 1000, "scan_visited_count": 6, "scan_complete": True, "truncated": False,
        "truncation_reason": None, "window": {"handle": 123, "process_id": 456, "process_name": "synthetic.exe",
            "title": "Synthetic", "bbox": {"x": 0, "y": 0, "w": 1000, "h": 700}},
        "control_count": len(controls), "controls": controls}
    current_uia = deepcopy(original_uia)
    current_uia["controls"][2]["name"] = names[1]
    original_evidence = {"target": {"window_handle": 123, "process_id": 456,
        "rect": dict(zip(("x", "y", "width", "height"), identity.window_rect))},
        "application": {"kind": "web" if context_type == "Document" else "native",
            "executable_path": "C:/Synthetic/synthetic.exe", "process_create_time": 1000.5},
        "capture": {"viewport_size": {"width": 1000, "height": 700}}}
    if context_type == "Document": original_evidence["application"]["canonical_origin"] = "https://synthetic.invalid"
    arguments = dict(field_identity=identity, original_evidence=original_evidence,
        original_uia=original_uia, current_evidence=deepcopy(original_evidence), current_uia=current_uia)
    _bind(arguments)
    return arguments


def _bind(arguments):
    for prefix in ("original", "current"):
        uia = arguments[prefix+"_uia"]
        arguments[prefix+"_evidence"]["uia"] = {key: uia[key] for key in ("provider", "provider_version", "status", "control_count")}
        arguments[prefix+"_evidence"]["uia"]["snapshot_sha256"] = payload_sha256(uia)


@pytest.mark.parametrize("context_type,label,names", [
    ("Document", "Search", ("Status 1", "Status 2")),
    ("Group", "Find item", ("Alerts 3", "Alerts 4")),
    ("Dialog", "查找", ("消息 1", "消息 2")),
    ("Document", "Rechercher", ("Notifications 8", "Notifications 9")),
])
def test_only_remote_toolbar_leaf_name_changes_have_a_recomputable_reference(context_type, label, names):
    arguments = _fixture(context_type=context_type, label=label, names=names)
    before = deepcopy(arguments)
    result = compare_fill_uia_context(**arguments)
    assert result == compare_fill_uia_context(**deepcopy(arguments))
    assert arguments == before
    assert result["contract_version"] == "text_uia_stability_reference_v1"
    assert result["policy"] == "fill_field_uia_context_v1"
    assert result["before_uia_sha256"] == payload_sha256(arguments["original_uia"])
    assert result["after_uia_sha256"] == payload_sha256(arguments["current_uia"])
    assert result["field_identity_sha256"] == payload_sha256(arguments["field_identity"].to_reference())
    assert result["context_root_id"] == "context"
    assert result["changes"] == [{"index": 2, "control_id": "badge",
        "before_name_sha256": sha256(names[0].encode("utf-8")).hexdigest(),
        "after_name_sha256": sha256(names[1].encode("utf-8")).hexdigest()}]
    assert names[0] not in repr(result) and names[1] not in repr(result)


@pytest.mark.parametrize("legacy", [False, True])
def test_exact_trees_return_none_without_requiring_a_new_context_contract(legacy):
    arguments = _fixture()
    if legacy:
        for key in ("scan_budget", "scan_visited_count", "scan_complete", "truncated", "truncation_reason"):
            arguments["original_uia"].pop(key)
        for control in arguments["original_uia"]["controls"]:
            control.pop("ancestor_control_ids")
    arguments["current_uia"] = deepcopy(arguments["original_uia"])
    _bind(arguments)
    assert compare_fill_uia_context(**arguments) is None


@pytest.mark.parametrize("equal", [False, True])
def test_logical_reviewed_field_id_is_not_mistaken_for_a_uia_control_id(equal):
    arguments = _fixture()
    old = arguments["field_identity"]
    arguments["field_identity"] = TextFieldIdentity("reviewed.logical.field", old.window_handle,
        old.process_id, old.process_create_time, old.runtime_id, old.window_rect, old.control_bbox)
    if equal:
        arguments["current_uia"] = deepcopy(arguments["original_uia"])
        _bind(arguments)
    result = compare_fill_uia_context(**arguments)
    if equal:
        assert result is None
    else:
        assert result["context_root_id"] == "context"
        assert result["field_identity_sha256"] == payload_sha256(arguments["field_identity"].to_reference())


@pytest.mark.parametrize("screen_origin", [False, True])
def test_both_supported_uia_window_coordinate_conventions_bind(screen_origin):
    arguments = _fixture()
    if screen_origin:
        for prefix in ("original", "current"):
            arguments[prefix+"_uia"]["window"]["bbox"].update(x=100, y=50)
        _bind(arguments)
    assert compare_fill_uia_context(**arguments)["changes"][0]["control_id"] == "badge"


def test_multiple_independent_toolbar_leaf_changes_are_reported_in_original_index_order():
    arguments = _fixture()
    for prefix, name in (("original", "消息 1"), ("current", "消息 2")):
        uia = arguments[prefix+"_uia"]
        extra = deepcopy(uia["controls"][2])
        extra.update(control_id="other-badge", runtime_id=[42, 77], name=name)
        extra["bbox"]["x"] = 860
        extra["screen_bbox"]["x"] = 960
        uia["controls"].append(extra)
        uia["control_count"] = uia["scan_visited_count"] = 7
    _bind(arguments)
    result = compare_fill_uia_context(**arguments)
    assert [(item["index"], item["control_id"]) for item in result["changes"]] == [(2, "badge"), (6, "other-badge")]


@pytest.mark.parametrize("distance", [63, 64])
def test_changed_toolbar_leaf_must_be_at_least_64_pixels_from_the_protected_field(distance):
    arguments = _fixture()
    for prefix in ("original", "current"):
        toolbar, badge = arguments[prefix+"_uia"]["controls"][1:3]
        toolbar["bbox"].update(y=90, h=100)
        toolbar["screen_bbox"].update(y=140, h=100)
        badge["bbox"].update(x=150, y=212-distance-20, h=20)
        badge["screen_bbox"].update(x=250, y=262-distance-20, h=20)
    _bind(arguments)
    if distance == 63:
        with pytest.raises(ValueError):
            compare_fill_uia_context(**arguments)
    else:
        assert compare_fill_uia_context(**arguments)["changes"]


@pytest.mark.parametrize("outer_type", ["Document", "Group", "Dialog"])
@pytest.mark.parametrize("shared_outer", [False, True])
def test_nested_field_group_does_not_hide_a_shared_outer_semantic_context(outer_type, shared_outer):
    arguments = _fixture(context_type="Group")
    for prefix in ("original", "current"):
        uia = arguments[prefix+"_uia"]
        outer = deepcopy(uia["controls"][3])
        outer.update(control_id="outer-context", control_type=outer_type, runtime_id=[42, 99])
        outer["bbox"].update(x=0, y=0, w=1000, h=650)
        outer["screen_bbox"].update(x=100, y=50, w=1000, h=650)
        uia["controls"].append(outer)
        for index in (3, 4, 5):
            uia["controls"][index]["ancestor_control_ids"].insert(-1, "outer-context")
        if shared_outer:
            for index in (1, 2):
                uia["controls"][index]["ancestor_control_ids"].insert(-1, "outer-context")
        uia["control_count"] = uia["scan_visited_count"] = 7
    _bind(arguments)
    if shared_outer:
        with pytest.raises(ValueError, match="context"):
            compare_fill_uia_context(**arguments)
    else:
        result = compare_fill_uia_context(**arguments)
        assert result["context_root_id"] == "context"
        assert result["changes"][0]["control_id"] == "badge"


@pytest.mark.parametrize("equal", [False, True])
@pytest.mark.parametrize("fault", ["before_hash", "after_hash", "window", "process", "window_rect", "viewport", "application", "field_identity"])
def test_each_snapshot_is_bound_even_on_the_exact_path(equal, fault):
    arguments = _fixture()
    if equal: arguments["current_uia"] = deepcopy(arguments["original_uia"])
    _bind(arguments)
    if fault == "before_hash": arguments["original_evidence"]["uia"]["snapshot_sha256"] = "f"*64
    elif fault == "after_hash": arguments["current_evidence"]["uia"]["snapshot_sha256"] = "f"*64
    elif fault == "window": arguments["current_evidence"]["target"]["window_handle"] += 1
    elif fault == "process": arguments["current_uia"]["window"]["process_id"] += 1; _bind(arguments)
    elif fault == "window_rect": arguments["current_evidence"]["target"]["rect"]["x"] += 1
    elif fault == "viewport": arguments["current_evidence"]["capture"]["viewport_size"]["width"] += 1
    elif fault == "application": arguments["current_evidence"]["application"]["process_create_time"] += 1
    elif fault == "field_identity": arguments["field_identity"] = arguments["field_identity"].to_reference()
    with pytest.raises((ValueError, TypeError)):
        compare_fill_uia_context(**arguments)


@pytest.mark.parametrize("fault", [
    "field_name", "field_runtime", "field_bbox", "field_enabled", "field_visible", "field_pattern", "field_role",
    "ancestor_name", "context_label", "toolbar_name", "non_toolbar", "non_leaf", "same_container", "near_field",
    "missing_context", "missing_ancestor", "unknown_ancestor", "duplicate_ancestor", "cycle", "inconsistent_chain",
    "duplicate_control_id", "duplicate_runtime", "missing_runtime", "bad_runtime_type", "unknown_control_field",
    "unknown_snapshot_field", "unknown_window_field", "added_control", "removed_control", "reordered_controls",
    "changed_geometry", "changed_screen_bbox", "changed_pattern", "changed_enabled", "changed_role",
    "incomplete", "truncated", "invalid_scan_count", "missing_scan", "null_name",
])
def test_context_structure_identity_and_unknown_deltas_remain_rejected(fault):
    arguments = _fixture()
    uia = arguments["current_uia"]
    root, toolbar, badge, context, field, label = uia["controls"]
    if fault == "field_name": field["name"] = "Other field"
    elif fault == "field_runtime": field["runtime_id"][-1] += 100
    elif fault == "field_bbox": field["bbox"]["x"] += 1
    elif fault == "field_enabled": field["enabled"] = False
    elif fault == "field_visible": field["visible"] = False
    elif fault == "field_pattern": field["patterns"] = ["Invoke"]
    elif fault == "field_role": field["control_type"] = "Button"
    elif fault == "ancestor_name": root["name"] = "Different account"
    elif fault == "context_label": label["name"] = "Other purpose"
    elif fault == "toolbar_name": toolbar["name"] = "New toolbar"
    elif fault == "non_toolbar": toolbar["control_type"] = "Pane"
    elif fault == "non_leaf": label["ancestor_control_ids"] = ["badge", "toolbar", "root"]
    elif fault == "same_container":
        toolbar["ancestor_control_ids"] = ["context", "root"]
        badge["ancestor_control_ids"] = ["toolbar", "context", "root"]
    elif fault == "near_field":
        toolbar["bbox"].update(y=170); toolbar["screen_bbox"].update(y=220)
        badge["bbox"].update(x=400, y=190); badge["screen_bbox"].update(x=500, y=240)
    elif fault == "missing_context": context["control_type"] = "Pane"
    elif fault == "missing_ancestor": field.pop("ancestor_control_ids")
    elif fault == "unknown_ancestor": field["ancestor_control_ids"][0] = "missing"
    elif fault == "duplicate_ancestor": field["ancestor_control_ids"].append("root")
    elif fault == "cycle": root["ancestor_control_ids"] = ["field"]
    elif fault == "inconsistent_chain": field["ancestor_control_ids"] = ["root", "context"]
    elif fault == "duplicate_control_id": badge["control_id"] = "field"
    elif fault == "duplicate_runtime": badge["runtime_id"] = list(field["runtime_id"])
    elif fault == "missing_runtime": badge["runtime_id"] = None
    elif fault == "bad_runtime_type": badge["runtime_id"] = [True, 3]
    elif fault == "unknown_control_field": badge["future_action"] = True
    elif fault == "unknown_snapshot_field": uia["future_permission"] = True
    elif fault == "unknown_window_field": uia["window"]["future_owner"] = "x"
    elif fault == "added_control": uia["controls"].append(deepcopy(label)); uia["control_count"] += 1
    elif fault == "removed_control": uia["controls"].pop(); uia["control_count"] -= 1
    elif fault == "reordered_controls": uia["controls"][2], uia["controls"][5] = uia["controls"][5], uia["controls"][2]
    elif fault == "changed_geometry": badge["bbox"]["x"] += 1
    elif fault == "changed_screen_bbox": badge["screen_bbox"]["x"] += 1
    elif fault == "changed_pattern": badge["patterns"] = ["Toggle"]
    elif fault == "changed_enabled": badge["enabled"] = False
    elif fault == "changed_role": badge["control_type"] = "Edit"
    elif fault == "incomplete": uia["scan_complete"] = False
    elif fault == "truncated": uia["truncated"] = True
    elif fault == "invalid_scan_count": uia["scan_visited_count"] = 2
    elif fault == "missing_scan": uia.pop("scan_complete")
    elif fault == "null_name": badge["name"] = None
    # 部分拒绝条件同时放进两帧，排除仅靠前后不等而偶然拒绝的假绿。
    shared_faults = {"non_toolbar", "non_leaf", "same_container", "near_field", "missing_context", "missing_ancestor",
        "unknown_ancestor", "duplicate_ancestor", "cycle", "inconsistent_chain", "duplicate_control_id", "duplicate_runtime",
        "missing_runtime", "bad_runtime_type", "unknown_control_field", "unknown_snapshot_field", "unknown_window_field",
        "incomplete", "truncated", "invalid_scan_count", "missing_scan"}
    if fault in shared_faults:
        arguments["original_uia"] = deepcopy(uia)
        arguments["original_uia"]["controls"][2]["name"] = "Status 1"
    _bind(arguments)
    before = deepcopy(arguments)
    with pytest.raises(ValueError):
        compare_fill_uia_context(**arguments)
    assert arguments == before


@pytest.mark.parametrize("fault", ["duplicate_control_id", "duplicate_runtime", "missing_ancestor_reference"])
def test_equal_trees_still_reject_available_identity_or_ancestor_corruption(fault):
    arguments = _fixture()
    uia = arguments["original_uia"]
    if fault == "duplicate_control_id": uia["controls"][2]["control_id"] = "field"
    elif fault == "duplicate_runtime": uia["controls"][2]["runtime_id"] = list(uia["controls"][4]["runtime_id"])
    else: uia["controls"][4]["ancestor_control_ids"] = ["unavailable"]
    arguments["current_uia"] = deepcopy(uia)
    _bind(arguments)
    with pytest.raises(ValueError):
        compare_fill_uia_context(**arguments)
