"""零面积结构祖先只用于已遍历拓扑证明，不能变成操作候选。"""
from copy import deepcopy

import pytest

from tests.test_uia_provider_pinned_snapshot import _TreeWrapper, _tree_snapshot


def _tree(kinds=("Group",)):
    root = _TreeWrapper((1,), "Window", "root", (10, 20, 810, 620))
    page = _TreeWrapper((2,), "Group", "page", (10, 20, 810, 620), root)
    descendants = [page]
    parent = page
    for index, kind in enumerate(kinds, start=3):
        parent = _TreeWrapper((index,), kind, f"structural-{index}", (0, 0, 0, 0), parent)
        descendants.append(parent)
    field = _TreeWrapper((100,), "ComboBox", "field", (110, 100, 270, 150), parent)
    field.iface_value = object()
    field.iface_text = object()
    descendants.append(field)
    return root, descendants, field


@pytest.mark.parametrize("kinds", [("Group",), ("Pane",), ("Group", "Pane", "Group")])
def test_traversed_zero_area_structural_parents_preserve_emitted_ancestry(monkeypatch, kinds):
    root, descendants, field = _tree(kinds)
    snapshot = _tree_snapshot(monkeypatch, root, descendants)
    controls = {control["name"]: control for control in snapshot["controls"]}
    assert snapshot["scan_complete"] is True and snapshot["truncated"] is False
    assert snapshot["scan_visited_count"] == len(descendants) + 1
    assert snapshot["control_count"] == 3 and set(controls) == {"root", "page", "field"}
    assert controls["field"]["ancestor_control_ids"] == ["uia_1_page", "uia_0_root"]
    assert controls["page"]["ancestor_control_ids"] == ["uia_0_root"]
    assert controls["root"]["ancestor_control_ids"] == []
    assert controls["field"]["runtime_id"] == [100]
    assert controls["field"]["bbox"] == {"x": 100, "y": 80, "w": 160, "h": 50}
    assert controls["field"]["screen_bbox"] == {"x": 110, "y": 100, "w": 160, "h": 50}
    assert controls["field"]["control_id"] == f"uia_{len(descendants)}_field"


@pytest.mark.parametrize("kind", ["Button", "Edit", "ComboBox", "Document", "Custom", None])
def test_nonstructural_zero_area_parent_cannot_bridge(monkeypatch, kind):
    root, descendants, _ = _tree((kind,))
    snapshot = _tree_snapshot(monkeypatch, root, descendants)
    field = next(c for c in snapshot["controls"] if c["name"] == "field")
    assert field["ancestor_control_ids"] == []


@pytest.mark.parametrize("case", ["untraversed", "duplicate_hidden", "duplicate_visible", "missing_runtime",
    "rectangle_error", "parent_error", "negative_rectangle", "cycle", "cycle_via_field"])
def test_unproven_or_ambiguous_structural_parent_does_not_bridge(monkeypatch, case):
    root, descendants, field = _tree()
    middle = descendants[1]
    if case == "untraversed": descendants.remove(middle)
    elif case.startswith("duplicate"):
        rect = (0, 0, 0, 0) if case == "duplicate_hidden" else (20, 30, 800, 610)
        descendants.insert(1, _TreeWrapper((3,), "Group", "duplicate", rect, descendants[0]))
    elif case == "missing_runtime": middle.element_info.runtime_id = None
    elif case == "rectangle_error":
        def fail(): raise RuntimeError("synthetic rectangle failure")
        middle.rectangle = fail
    elif case == "parent_error":
        def fail(): raise RuntimeError("synthetic parent failure")
        middle.parent = fail
    elif case == "negative_rectangle": middle._rect.right = -1
    elif case == "cycle": middle._parent = middle
    elif case == "cycle_via_field": middle._parent = field
    snapshot = _tree_snapshot(monkeypatch, root, descendants)
    actual = next(c for c in snapshot["controls"] if c["name"] == "field")
    assert actual["ancestor_control_ids"] == []


def test_rectangle_error_cannot_be_reclassified_from_a_later_zero_read(monkeypatch):
    root, descendants, _ = _tree()
    middle = descendants[1]
    original = middle.rectangle
    calls = []
    def unstable():
        calls.append(1)
        if len(calls) == 1: raise RuntimeError("first rectangle unavailable")
        return original()
    middle.rectangle = unstable
    snapshot = _tree_snapshot(monkeypatch, root, descendants)
    assert next(c for c in snapshot["controls"] if c["name"] == "field")["ancestor_control_ids"] == []
    assert len(calls) == 1


def test_zero_area_projection_does_not_change_other_fields_or_coordinates(monkeypatch):
    root, descendants, field = _tree()
    snapshot = _tree_snapshot(monkeypatch, root, descendants)
    with_bridge = deepcopy(snapshot["controls"])
    field._parent = descendants[0]
    direct = _tree_snapshot(monkeypatch, root, descendants)
    assert with_bridge == direct["controls"]


def test_missing_parent_after_verified_bridge_keeps_only_confirmed_prefix(monkeypatch):
    root, descendants, _ = _tree()
    outside = _TreeWrapper((200,), "Pane", "untraversed", (0, 0, 0, 0), root)
    descendants[0]._parent = outside
    snapshot = _tree_snapshot(monkeypatch, root, descendants)
    controls = {c["name"]: c for c in snapshot["controls"]}
    assert controls["field"]["ancestor_control_ids"] == ["uia_1_page"]
    assert controls["page"]["ancestor_control_ids"] == []
