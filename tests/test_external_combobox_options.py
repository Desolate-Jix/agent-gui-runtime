"""外置列表仅通过 UIA ControllerFor 明确关系进入组合框选项。"""
from types import SimpleNamespace as NS

import pytest

from app.agent import windows_form_control_reader as reader
from tests.test_windows_form_control_reader import Array, Node, TARGET, rect, setup


@pytest.fixture(autouse=True)
def compare_elements_boundary(monkeypatch):
    monkeypatch.setattr(reader, "_same_element", lambda left, right: left is right)


def scene(setup, *, controls=True, duplicate=False, wrong_pid=False, bad_edge=False):
    apple = Node("Apple", "ListItem", (4, 4), pid=21 if wrong_pid else 20)
    apple.element_info.rectangle = rect(120, 310, 100, 25)
    apple.iface_selection_item = NS(CurrentIsSelected=0)
    outside = Node("Banana", "ListItem", (4, 5))
    outside.element_info.rectangle = rect(120, 720, 100, 25)
    foreign = Node("Unrelated", "ListItem", (8, 8))
    listbox = Node("choices", "List", (4, 3), children=[apple, outside])
    combo = Node("Choice", "ComboBox", (4, 2))
    combo.iface_expand_collapse = NS(CurrentExpandCollapseState=1)
    combo.iface_value = NS(CurrentValue="old")
    if controls:
        combo.CurrentControllerFor = Array(listbox, foreign) if duplicate else Array(listbox)
    elif bad_edge:
        combo.CurrentControllerFor = Array(foreign)
    return setup(combo, listbox, foreign), listbox


def test_unique_controller_for_external_list_reads_only_in_capture_items(setup):
    coordinator, _ = scene(setup)
    result = reader.read_form_control(coordinator, TARGET, "Choice", "dropdown")
    assert result["expanded"] is True
    assert [item["label"] for item in result["options"]] == ["Apple"]
    assert result["options"][0]["bbox"] == {"x": 20, "y": 110, "w": 100, "h": 25}
    assert result["options"][0]["runtime_id"] == [4, 4]


@pytest.mark.parametrize("fault", ["missing", "duplicate", "non_list", "wrong_pid"])
def test_unowned_or_ambiguous_external_lists_never_supply_options(setup, fault):
    coordinator, _ = scene(setup, controls=fault not in {"missing", "non_list"},
        duplicate=fault == "duplicate", wrong_pid=fault == "wrong_pid",
        bad_edge=fault == "non_list")
    if fault == "missing":
        result = reader.read_form_control(coordinator, TARGET, "Choice", "dropdown")
        assert result["options"] == []
    else:
        with pytest.raises(reader.FormControlReadError):
            reader.read_form_control(coordinator, TARGET, "Choice", "dropdown")


def test_external_visible_item_requires_valid_geometry(setup):
    coordinator, listbox = scene(setup)
    listbox.nodes[0].element_info.rectangle = rect(120, 310, 0, 25)
    with pytest.raises(reader.FormControlReadError, match="geometry_unavailable"):
        reader.read_form_control(coordinator, TARGET, "Choice", "dropdown")
