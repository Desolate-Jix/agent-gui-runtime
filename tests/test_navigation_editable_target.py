import pytest

from app.gate.fresh_action_risk import classify_fresh_action_risk
from tests.test_fresh_action_risk import _candidate, _control, _local, _uia


def _risk(role, *, semantic="open_detail", label="Atlas", controls=()):
    candidate = _candidate(label, role=role)
    return classify_fresh_action_risk(
        proposed_semantic_action=semantic, goal=label, candidate=candidate,
        local=_local(candidate), capture_id="capture.navigation", uia_snapshot=_uia(*controls),
    )


@pytest.mark.parametrize("semantic", ["open_detail", "back", "close_modal"])
@pytest.mark.parametrize("role", ["input", "Edit", "textbox", "ComboBox", "combo box"])
@pytest.mark.parametrize("label", ["Atlas", "Search", "\u5730\u56fe"])
def test_editable_value_is_not_navigation_target(semantic, role, label):
    risk = _risk(role, semantic=semantic, label=label)
    assert risk["hard_blocked"] is True
    assert risk["risk_class"] == "unsupported"
    assert risk["reasons"] == ["navigation_target_is_editable_field"]


@pytest.mark.parametrize("control_type", ["Edit", "ComboBox"])
def test_current_uia_field_geometry_overrides_navigation_label(control_type):
    control = _control("field", "Atlas", {"x": 100, "y": 80, "w": 160, "h": 50}, control_type=control_type)
    control.update(patterns=["Value", "Text"])
    risk = _risk("button", controls=[control])
    assert risk["hard_blocked"] is True
    assert risk["reasons"] == ["navigation_target_is_editable_field"]


@pytest.mark.parametrize("role", ["button", "link", "menu_item", "tab"])
def test_real_navigation_control_is_not_rejected_by_unrelated_field(role):
    control = _control("other-field", "Atlas", {"x": 500, "y": 400, "w": 200, "h": 50}, control_type="ComboBox")
    control.update(patterns=["Value", "Text"])
    assert _risk(role, controls=[control])["hard_blocked"] is False


def test_search_button_inside_larger_combo_is_not_the_editable_field():
    control = _control("field", "Atlas", {"x": 80, "y": 60, "w": 300, "h": 90}, control_type="ComboBox")
    control.update(patterns=["Value", "Text"])
    assert _risk("button", controls=[control])["hard_blocked"] is False


@pytest.mark.parametrize("role,control_type", [("input", "Edit"), ("combobox", "ComboBox")])
def test_explicit_fill_still_accepts_current_editable_field(role, control_type):
    control = _control("field", "Atlas", {"x": 100, "y": 80, "w": 160, "h": 50}, control_type=control_type)
    control.update(patterns=["Value", "Text"])
    risk = _risk(role, semantic="fill_field", controls=[control])
    assert risk["hard_blocked"] is False
    assert risk["risk_class"] == "low_risk_text_input"
