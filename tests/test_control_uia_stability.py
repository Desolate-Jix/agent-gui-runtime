"""导航上下文的纯合成回归；不读取桌面、不产生输入权限。"""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.control_uia_stability import ControlContextIdentity, compare_navigation_uia_context


def _fixture(*, context_type="Document", role="Hyperlink", label="Open library", patterns=None):
    identity = ControlContextIdentity(123, 456, 1000.5, (42, 4), (100, 50, 1000, 700), (150, 220, 300, 40))

    def control(cid, kind, box, ancestors, number, name=None):
        bbox = dict(zip(("x", "y", "w", "h"), box))
        return {"provider": "windows_uia", "control_id": cid, "name": name,
            "control_type": kind, "automation_id": cid, "class_name": "SyntheticControl",
            "bbox": bbox, "screen_bbox": {**bbox, "x": bbox["x"]+100, "y": bbox["y"]+50},
            "enabled": True, "visible": True, "patterns": [],
            "runtime_id": [42, number], "ancestor_control_ids": ancestors}

    controls = [
        control("root", "Window", (0, 0, 1000, 700), [], 1),
        control("toolbar", "ToolBar", (0, 0, 1000, 60), ["root"], 2),
        control("badge", "Button", (800, 10, 40, 30), ["toolbar", "root"], 3, "Notifications 24"),
        control("context", context_type, (100, 150, 700, 450), ["root"], 5),
        control("target", role, identity.control_bbox, ["context", "root"], 4, label),
        control("label", "Text", (150, 180, 120, 20), ["context", "root"], 6, label),
    ]
    controls[4]["patterns"] = ["Invoke"] if patterns is None else patterns
    uia = {"provider": "windows_uia", "provider_version": "windows_uia_provider_v1", "status": "ok",
        "scan_budget": 1000, "scan_visited_count": 6, "scan_complete": True, "truncated": False,
        "truncation_reason": None, "window": {"handle": 123, "process_id": 456, "process_name": "synthetic.exe",
            "title": "Synthetic", "bbox": {"x": 0, "y": 0, "w": 1000, "h": 700}},
        "control_count": len(controls), "controls": controls}
    evidence = {"target": {"window_handle": 123, "process_id": 456,
        "rect": dict(zip(("x", "y", "width", "height"), identity.window_rect))},
        "application": {"kind": "web" if context_type == "Document" else "native",
            "executable_path": "C:/Synthetic/synthetic.exe", "process_create_time": 1000.5},
        "capture": {"viewport_size": {"width": 1000, "height": 700}}}
    if context_type == "Document":
        evidence["application"]["canonical_origin"] = "https://library.invalid"
    args = dict(control_identity=identity, original_evidence=evidence, original_uia=uia,
        current_evidence=deepcopy(evidence), current_uia=deepcopy(uia))
    args["current_uia"]["controls"][2]["name"] = "Notifications 25"
    _bind(args)
    return args


def _bind(args):
    for prefix in ("original", "current"):
        uia = args[prefix+"_uia"]
        args[prefix+"_evidence"]["uia"] = {key: uia[key] for key in ("provider", "provider_version", "status", "control_count")}
        args[prefix+"_evidence"]["uia"]["snapshot_sha256"] = payload_sha256(uia)


@pytest.mark.parametrize("context_type,role,label,patterns", [
    ("Document", "Hyperlink", "Open library", ["Invoke", "Value"]),
    ("Group", "Button", "Show details", ["Invoke"]),
    ("Dialog", "Button", "打开详情", ["InvokePattern"]),
    ("Document", "Hyperlink", "Bibliothèque", ["Value", "Invoke"]),
])
def test_remote_toolbar_name_has_recomputable_navigation_reference(context_type, role, label, patterns):
    args = _fixture(context_type=context_type, role=role, label=label, patterns=patterns)
    before = deepcopy(args)
    result = compare_navigation_uia_context(**args)
    protected = [args["original_uia"]["controls"][index] for index in (0, 3, 4, 5)]
    assert result == {
        "contract_version": "navigation_uia_stability_reference_v1", "policy": "navigation_uia_context_v1",
        "before_uia_sha256": payload_sha256(args["original_uia"]),
        "after_uia_sha256": payload_sha256(args["current_uia"]),
        "control_identity_sha256": payload_sha256(args["control_identity"].to_reference()),
        "context_root_id": "context", "context_sha256": payload_sha256({"controls": protected}),
        "changes": [{"index": 2, "control_id": "badge",
            "before_name_sha256": sha256(b"Notifications 24").hexdigest(),
            "after_name_sha256": sha256(b"Notifications 25").hexdigest()}],
    }
    assert result == compare_navigation_uia_context(**deepcopy(args))
    assert args == before
    assert "Notifications" not in repr(result)
    assert "target_field_id" not in args["control_identity"].to_reference()


@pytest.mark.parametrize("legacy", [False, True])
def test_equal_trees_keep_the_exact_path(legacy):
    args = _fixture()
    if legacy:
        for key in ("scan_budget", "scan_visited_count", "scan_complete", "truncated", "truncation_reason"):
            args["original_uia"].pop(key)
        for control in args["original_uia"]["controls"]:
            control.pop("ancestor_control_ids")
    args["current_uia"] = deepcopy(args["original_uia"])
    _bind(args)
    assert compare_navigation_uia_context(**args) is None


@pytest.mark.parametrize("role,patterns,enabled,visible", [
    ("Edit", ["Invoke", "Value"], True, True),
    ("Document", ["Invoke"], True, True),
    ("Text", ["Invoke"], True, True),
    ("Hyperlink", ["Value"], True, True),
    ("Button", [], True, True),
    ("Button", ["Invoke"], False, True),
    ("Button", ["Invoke"], True, False),
    ("Button", ["Invoke"], None, True),
    ("Button", ["Invoke"], True, None),
])
@pytest.mark.parametrize("equal", [False, True])
def test_navigation_requires_a_verified_action_identity_even_on_equal_trees(role, patterns, enabled, visible, equal):
    args = _fixture(role=role, patterns=patterns)
    for prefix in ("original", "current"):
        args[prefix+"_uia"]["controls"][4].update(enabled=enabled, visible=visible)
    if equal:
        args["current_uia"] = deepcopy(args["original_uia"])
    _bind(args)
    with pytest.raises(ValueError):
        compare_navigation_uia_context(**args)


@pytest.mark.parametrize("fault", [
    "target_name", "target_runtime", "target_geometry", "target_pattern", "target_enabled", "target_visible",
    "context_name", "context_label", "ancestor_name", "toolbar_name", "badge_geometry", "badge_pattern",
    "badge_role", "badge_runtime", "non_toolbar", "non_leaf", "same_context", "near_target", "missing_context",
    "missing_scan", "truncated", "scan_count", "unknown_field", "added", "removed", "reordered",
    "duplicate_runtime", "duplicate_id", "inconsistent_ancestor", "digest", "process", "origin", "viewport",
])
def test_navigation_rejects_changes_beyond_remote_leaf_name(fault):
    args = _fixture()
    uia = args["current_uia"]
    root, toolbar, badge, context, target, label = uia["controls"]
    if fault == "target_name": target["name"] = "Buy now"
    elif fault == "target_runtime": target["runtime_id"] = [42, 999]
    elif fault == "target_geometry": target["bbox"]["x"] += 1
    elif fault == "target_pattern": target["patterns"].append("Toggle")
    elif fault == "target_enabled": target["enabled"] = False
    elif fault == "target_visible": target["visible"] = None
    elif fault == "context_name": context["name"] = "Payment form"
    elif fault == "context_label": label["name"] = "Purchase"
    elif fault == "ancestor_name": root["name"] = "Another account"
    elif fault == "toolbar_name": toolbar["name"] = "Other toolbar"
    elif fault == "badge_geometry": badge["bbox"]["x"] += 1
    elif fault == "badge_pattern": badge["patterns"] = ["Toggle"]
    elif fault == "badge_role": badge["control_type"] = "Edit"
    elif fault == "badge_runtime": badge["runtime_id"] = [42, 111]
    elif fault == "non_toolbar": toolbar["control_type"] = "Pane"
    elif fault == "non_leaf": label["ancestor_control_ids"] = ["badge", "toolbar", "root"]
    elif fault == "same_context":
        toolbar["ancestor_control_ids"] = ["context", "root"]
        badge["ancestor_control_ids"] = ["toolbar", "context", "root"]
    elif fault == "near_target":
        toolbar["bbox"].update(y=170); toolbar["screen_bbox"].update(y=220)
        badge["bbox"].update(x=400, y=190); badge["screen_bbox"].update(x=500, y=240)
    elif fault == "missing_context": context["control_type"] = "Pane"
    elif fault == "missing_scan": uia.pop("scan_complete")
    elif fault == "truncated": uia["truncated"] = True
    elif fault == "scan_count": uia["scan_visited_count"] = 1000
    elif fault == "unknown_field": badge["new_permission"] = True
    elif fault == "added": uia["controls"].append(deepcopy(label)); uia["control_count"] += 1
    elif fault == "removed": uia["controls"].pop(); uia["control_count"] -= 1
    elif fault == "reordered": uia["controls"][2], uia["controls"][5] = label, badge
    elif fault == "duplicate_runtime": badge["runtime_id"] = target["runtime_id"][:]
    elif fault == "duplicate_id": badge["control_id"] = "target"
    elif fault == "inconsistent_ancestor": target["ancestor_control_ids"] = ["root", "context"]
    elif fault == "process": args["current_evidence"]["application"]["process_create_time"] += 1
    elif fault == "origin": args["current_evidence"]["application"]["canonical_origin"] = "https://other.invalid"
    elif fault == "viewport": args["current_evidence"]["capture"]["viewport_size"]["width"] -= 1
    if fault in {"non_toolbar", "non_leaf", "same_context", "near_target", "missing_context", "missing_scan",
                 "truncated", "scan_count", "unknown_field", "duplicate_runtime", "duplicate_id", "inconsistent_ancestor"}:
        args["original_uia"] = deepcopy(uia)
        args["original_uia"]["controls"][2]["name"] = "Notifications 24"
    _bind(args)
    if fault == "digest": args["current_evidence"]["uia"]["snapshot_sha256"] = "f"*64
    before = deepcopy(args)
    with pytest.raises(ValueError):
        compare_navigation_uia_context(**args)
    assert args == before


@pytest.mark.parametrize("outer_type", ["Document", "Group", "Dialog"])
def test_nested_group_cannot_hide_a_shared_outer_context(outer_type):
    args = _fixture(context_type="Group")
    for prefix in ("original", "current"):
        uia = args[prefix+"_uia"]
        outer = deepcopy(uia["controls"][3])
        outer.update(control_id="outer", control_type=outer_type, runtime_id=[42, 99])
        outer["bbox"].update(x=0, y=0, w=1000, h=650)
        outer["screen_bbox"].update(x=100, y=50, w=1000, h=650)
        uia["controls"].append(outer)
        for index in range(1, 6):
            uia["controls"][index]["ancestor_control_ids"].insert(-1, "outer")
        uia["control_count"] = uia["scan_visited_count"] = 7
    _bind(args)
    with pytest.raises(ValueError, match="context"):
        compare_navigation_uia_context(**args)


@pytest.mark.parametrize("key,value", [
    ("window_handle", True), ("process_id", 0), ("process_create_time", float("nan")),
    ("runtime_id", (True, 4)), ("runtime_id", []), ("window_rect", (0, 0, 0, 700)),
    ("control_bbox", (-1, 10, 20, 20)), ("control_bbox", (999, 10, 20, 20)),
])
def test_navigation_identity_validates_its_constructor(key, value):
    old = _fixture()["control_identity"]
    values = {name: getattr(old, name) for name in old.to_reference()}
    values[key] = value
    with pytest.raises(ValueError):
        ControlContextIdentity(**values)


def test_navigation_identity_is_typed_immutable_and_revalidated():
    args = _fixture()
    identity = args["control_identity"]
    with pytest.raises(FrozenInstanceError):
        identity.process_id = 999
    args["control_identity"] = identity.to_reference()
    with pytest.raises(TypeError):
        compare_navigation_uia_context(**args)
    args["control_identity"] = identity
    object.__setattr__(identity, "runtime_id", (True, 4))
    with pytest.raises(ValueError):
        compare_navigation_uia_context(**args)


def test_navigation_does_not_accept_a_fabricated_text_field_identity():
    from app.agent.text_field_evidence import TextFieldIdentity

    args = _fixture()
    identity = args["control_identity"]
    args["control_identity"] = TextFieldIdentity("logical-field", identity.window_handle,
        identity.process_id, identity.process_create_time, identity.runtime_id,
        identity.window_rect, identity.control_bbox)
    with pytest.raises(TypeError):
        compare_navigation_uia_context(**args)


@pytest.mark.parametrize("equal", [False, True])
def test_fill_wrapper_preserves_the_complete_existing_reference(equal):
    from app.agent.text_field_evidence import TextFieldIdentity
    from app.agent.text_uia_stability import compare_fill_uia_context

    args = _fixture(role="Edit", patterns=["Value"])
    control = args.pop("control_identity")
    field = TextFieldIdentity("logical-field", control.window_handle, control.process_id,
        control.process_create_time, control.runtime_id, control.window_rect, control.control_bbox)
    args["field_identity"] = field
    if equal:
        args["current_uia"] = deepcopy(args["original_uia"])
        _bind(args)
    before = deepcopy(args)
    result = compare_fill_uia_context(**args)
    assert args == before
    if equal:
        assert result is None
        return
    assert result == {
        "contract_version": "text_uia_stability_reference_v1", "policy": "fill_field_uia_context_v1",
        "before_uia_sha256": payload_sha256(args["original_uia"]),
        "after_uia_sha256": payload_sha256(args["current_uia"]),
        "field_identity_sha256": payload_sha256(field.to_reference()), "context_root_id": "context",
        "context_sha256": payload_sha256({"controls": [args["original_uia"]["controls"][i] for i in (0, 3, 4, 5)]}),
        "changes": [{"index": 2, "control_id": "badge",
            "before_name_sha256": sha256(b"Notifications 24").hexdigest(),
            "after_name_sha256": sha256(b"Notifications 25").hexdigest()}],
    }
