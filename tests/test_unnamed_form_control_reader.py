import pytest
from types import SimpleNamespace as NS

from app.agent import windows_form_control_reader as reader
from tests.test_windows_form_control_reader import Node, TARGET, rect, setup


def _node(name, kind, rid, x, y, w, h):
    node = Node(name, kind, rid)
    node.element_info.rectangle = rect(x, y, w, h)
    return node


def test_unnamed_dropdown_binds_unique_visible_sibling_label(setup):
    label = _node("Eligibility to work", "Text", (2,), 451, 837, 180, 18)
    combo = _node("", "ComboBox", (3,), 451, 857, 433, 30)
    other = _node("", "ComboBox", (4,), 451, 1006, 433, 31)
    parent = Node("", "Group", (1,), children=[label, combo, other])
    bounds = [NS(handle=10, process_id=20, rect=rect(100, 200, 1200, 1300))] * 2
    result = reader.read_form_control(setup(parent, bounds=bounds), TARGET, "Eligibility to work", "dropdown")
    assert result["runtime_id"] == [3]
    assert result["label"] == "Eligibility to work"
    assert result["bbox"] == {"x": 351, "y": 657, "w": 433, "h": 30}


def test_unnamed_dropdown_with_adjacent_competing_control_is_not_found(setup):
    label = _node("Desired Salary (optional)", "Text", (2,), 451, 986, 200, 18)
    first = _node("", "ComboBox", (3,), 451, 1006, 433, 31)
    second = _node("", "ComboBox", (4,), 451, 1036, 433, 30)
    parent = Node("", "Group", (1,), children=[label, first, second])
    with pytest.raises(reader.FormControlReadError, match="form_control_not_found"):
        bounds = [NS(handle=10, process_id=20, rect=rect(100, 200, 1200, 1300))] * 2
        reader.read_form_control(setup(parent, bounds=bounds), TARGET, "Desired Salary (optional)", "dropdown")
