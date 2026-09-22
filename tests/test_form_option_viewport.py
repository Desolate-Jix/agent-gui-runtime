"""展开组合框的可选项须完整落在已验证视口内，树遍历仍必须完整。"""
from types import SimpleNamespace as NS

import pytest

from app.agent import windows_form_control_reader as reader
from tests.test_windows_form_control_reader import Node, TARGET, rect, setup


POPUP = {"handle": 90, "process_id": 20, "owner_handle": 10, "root_owner_handle": 10,
         "class_name": "ChoicePopup", "rect": [120, 260, 400, 361]}


def option(index, y, *, visible=True):
    item = Node(str(index), "ListItem", (2, index), visible=visible)
    item.element_info.rectangle = rect(120, y, 100, 25)
    item.iface_selection_item = NS(CurrentIsSelected=0)
    return item


def observe(setup, monkeypatch, items, *, expanded=True, popups=None):
    combo = Node("Choice", "ComboBox", children=items)
    combo.iface_value = NS(CurrentValue="old")
    combo.iface_expand_collapse = NS(CurrentExpandCollapseState=int(expanded))
    coordinator = setup(combo)
    monkeypatch.setattr(reader, "_native_owned_popups", lambda *args: [POPUP] if popups is None else popups)
    return reader.read_form_control(coordinator, TARGET, "Choice", "dropdown")


def test_off_viewport_options_do_not_abort_or_truncate_complete_scan(setup, monkeypatch):
    items = [option(1, 260), option(2, 350), option(3, 720), option(4, 300)]
    result = observe(setup, monkeypatch, items)
    assert [o["label"] for o in result["options"]] == ["1", "4"]
    assert all(o["native_popup"]["handle"] == 90 for o in result["options"])
    scan = result["diagnostics"]["option_scan"]
    assert scan["edge_count"] == 4 and scan["graph_scan_complete"] is True
    assert scan["viewport_excluded_count"] == 2
    assert scan["viewport_source"] == "native_owned_popup"


@pytest.mark.parametrize("geometry", [None, rect(120, 300, 0, 25), rect(120, 300, 100, -1)])
def test_visible_option_missing_or_invalid_geometry_still_rejects(setup, monkeypatch, geometry):
    broken = option(2, 300)
    broken.element_info.rectangle = geometry
    with pytest.raises(reader.FormControlReadError, match="geometry_unavailable"):
        observe(setup, monkeypatch, [option(1, 260), broken])


def test_explicit_offscreen_missing_geometry_is_not_a_click_candidate(setup, monkeypatch):
    hidden = option(2, 0, visible=False)
    hidden.element_info.rectangle = None
    result = observe(setup, monkeypatch, [option(1, 260), hidden, option(3, 300)])
    assert [o["label"] for o in result["options"]] == ["1", "3"]


@pytest.mark.parametrize("expanded,popups", [
    (False, [POPUP]), (True, []),
    (True, [{**POPUP, "rect": [500, 500, 600, 600]}]),
])
def test_unexpanded_and_inline_options_keep_existing_geometry_contract(setup, monkeypatch, expanded, popups):
    result = observe(setup, monkeypatch, [option(1, 260), option(2, 350)], expanded=expanded, popups=popups)
    assert [o["label"] for o in result["options"]] == ["1", "2"]
    assert all("native_popup" not in o for o in result["options"])


@pytest.mark.parametrize("expanded,popups", [(False, [POPUP]), (True, [])])
def test_without_verified_viewport_outside_capture_geometry_is_not_accepted(setup, monkeypatch, expanded, popups):
    with pytest.raises(reader.FormControlReadError, match="geometry_unavailable"):
        observe(setup, monkeypatch, [option(1, 260), option(2, 720)], expanded=expanded, popups=popups)


def test_two_option_corresponding_popups_remain_ambiguous(setup, monkeypatch):
    other = {**POPUP, "handle": 91, "rect": [120, 450, 400, 500]}
    with pytest.raises(reader.FormControlReadError, match="popup_ambiguous"):
        observe(setup, monkeypatch, [option(1, 260), option(2, 450)], popups=[POPUP, other])


def test_off_viewport_option_cannot_bypass_window_identity(setup, monkeypatch):
    outside = option(2, 720)
    outside.top_handle = 99
    with pytest.raises(reader.FormControlReadError, match="tree_scope_changed"):
        observe(setup, monkeypatch, [option(1, 260), outside])


def test_nonmaximized_live_geometry_replay_keeps_twenty_rows_and_full_graph(setup, monkeypatch):
    items = [option(index, 520 + (index - 1) * 24, visible=index <= 30)
             for index in range(1, 43)]
    for item in items:
        item.element_info.rectangle.left = 1117
        item.element_info.rectangle.right = 1330
        item.element_info.rectangle.bottom = item.element_info.rectangle.top + 24
    combo = Node("Choice", "ComboBox", children=items)
    combo.element_info.rectangle = rect(1116, 496, 285, 19)
    combo.iface_value = NS(CurrentValue="old")
    combo.iface_expand_collapse = NS(CurrentExpandCollapseState=1)
    coordinator = setup(combo, bounds=[NS(handle=10, process_id=20, rect=rect(879, 80, 800, 1155))] * 2)
    monkeypatch.setattr(reader, "_native_owned_popups", lambda *args:
        [{**POPUP, "rect": [1116, 519, 1401, 1001]}])
    result = reader.read_form_control(coordinator, TARGET, "Choice", "dropdown")
    assert len(result["options"]) == 20
    assert result["options"][1]["bbox"] == {"x": 238, "y": 464, "w": 213, "h": 24}
    assert result["options"][-1]["label"] == "20"
    scan = result["diagnostics"]["option_scan"]
    assert scan["edge_count"] == 42 and scan["graph_scan_complete"] is True
    assert scan["viewport_excluded_count"] == 10
