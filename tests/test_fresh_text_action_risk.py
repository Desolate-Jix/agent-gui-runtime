from tests.test_fresh_action_risk import _candidate, _local, _uia
from app.gate.fresh_action_risk import classify_fresh_action_risk
import pytest


def _edit(control_id="field", *, bbox=None, **extra):
    value = {
        "provider": "windows_uia",
        "control_id": control_id,
        "name": "Name",
        "control_type": "Edit",
        "automation_id": control_id,
        "class_name": "Edit",
        "bbox": bbox or {"x": 100, "y": 80, "w": 160, "h": 50},
        "screen_bbox": bbox or {"x": 100, "y": 80, "w": 160, "h": 50},
        "enabled": True,
        "visible": True,
        "patterns": ["Value"],
    }
    value.update(extra)
    return value


def _classify(controls):
    candidate = _candidate("Name", role="edit")
    return classify_fresh_action_risk(
        proposed_semantic_action="fill_field",
        goal="Fill Name",
        candidate=candidate,
        local=_local(candidate),
        capture_id="fresh-capture.0123456789abcdef",
        uia_snapshot=_uia(*controls),
    )


def test_fill_field_accepts_one_enabled_visible_editable_uia_control():
    result = _classify([_edit()])

    assert result["hard_blocked"] is False
    assert result["risk_class"] == "low_risk_text_input"
    assert "observed_editable_text_field" in result["reasons"]


def test_edit_exposing_invoke_is_not_a_distinct_overlapping_control():
    result = _classify([_edit(patterns=["Invoke", "Value", "Text"])])
    assert result["hard_blocked"] is False
    assert result["risk_class"] == "low_risk_text_input"


@pytest.mark.parametrize("case", ["button", "same_id_button", "second_edit", "missing_id", "dangerous_edit"])
def test_edit_invoke_does_not_hide_other_overlap_or_danger(case):
    field = _edit(patterns=["Invoke", "Value", "Text"])
    controls = [field]
    if case in {"button", "same_id_button"}:
        controls.append(_edit("field" if case == "same_id_button" else "other",
            control_type="Button", patterns=["Invoke"]))
    elif case == "second_edit":
        controls.append(_edit("other"))
    elif case == "missing_id":
        field["control_id"] = ""
    else:
        field["name"] = "Send"
    assert _classify(controls)["hard_blocked"] is True


def test_fill_field_rejects_missing_or_ambiguous_editable_control():
    no_field = _classify([])
    two_fields = _classify([_edit("one"), _edit("two")])

    assert no_field["hard_blocked"] is True
    assert "editable_text_field_unresolved" in no_field["reasons"]
    assert two_fields["hard_blocked"] is True
    assert "multiple_editable_text_fields" in two_fields["reasons"]


def test_fill_field_rejects_readonly_password_and_overlapping_actionable_control():
    readonly = _classify([_edit(is_read_only=True)])
    password = _classify([_edit(is_password=True)])
    dangerous = {
        "provider": "windows_uia",
        "control_id": "send",
        "name": "Send",
        "control_type": "Button",
        "bbox": {"x": 120, "y": 90, "w": 60, "h": 30},
        "enabled": True,
        "visible": True,
        "patterns": ["Invoke"],
    }
    overlap = _classify([_edit(), dangerous])

    assert readonly["hard_blocked"] is True
    assert "text_field_readonly_or_password" in readonly["reasons"]
    assert password["hard_blocked"] is True
    assert "text_field_readonly_or_password" in password["reasons"]
    assert overlap["hard_blocked"] is True
    assert "final_submit_target" in overlap["reasons"]


@pytest.mark.parametrize("name,reason", [("Pay now", "payment_or_purchase_target"), ("Send", "final_submit_target"), ("Delete account", "destructive_delete_target")])
def test_fill_field_editable_control_text_is_in_danger_evidence(name, reason):
    result = _classify([_edit(name=name)])

    assert result["hard_blocked"] is True
    assert reason in result["reasons"]



def _combo(control_id="field", *, bbox=None, **extra):
    value = _edit(
        control_id,
        bbox=bbox,
        control_type="ComboBox",
        class_name="ComboBox",
        patterns=["Value", "Text", "ExpandCollapse"],
    )
    value.update(extra)
    return value


def _group(control_id="page", *, bbox=None, **extra):
    value = {
        "provider": "windows_uia",
        "control_id": control_id,
        "name": "Search page",
        "control_type": "Group",
        "automation_id": control_id,
        "class_name": "Group",
        "bbox": bbox or {"x": 0, "y": 0, "w": 600, "h": 400},
        "screen_bbox": bbox or {"x": 0, "y": 0, "w": 600, "h": 400},
        "enabled": True,
        "visible": True,
        "patterns": ["Invoke"],
        "ancestor_control_ids": [],
    }
    value.update(extra)
    return value


def test_fill_field_accepts_enabled_visible_combobox_with_value_and_text_patterns():
    result = _classify([_combo()])

    assert result["hard_blocked"] is False
    assert result["risk_class"] == "low_risk_text_input"


@pytest.mark.parametrize(
    "extra",
    [
        {"patterns": ["Selection", "ExpandCollapse"]},
        {"patterns": ["Value", "ExpandCollapse"]},
        {"patterns": ["Text", "ExpandCollapse"]},
        {"enabled": False},
        {"visible": False},
        {"is_read_only": True},
        {"is_password": True},
    ],
)
def test_fill_field_rejects_noneditable_or_unsafe_combobox(extra):
    result = _classify([_combo(**extra)])

    assert result["hard_blocked"] is True


def test_fill_field_ignores_only_strictly_containing_confirmed_group_ancestor():
    field = _combo(ancestor_control_ids=["page"])
    page = _group()

    result = _classify([page, field])

    assert result["hard_blocked"] is False
    assert result["risk_class"] == "low_risk_text_input"


@pytest.mark.parametrize(
    "field_extra,page_extra",
    [
        ({}, {}),  # 同级 Group 不是祖先。
        ({"ancestor_control_ids": ["missing"]}, {}),  # 未知祖先。
        ({"ancestor_control_ids": ["page"]}, {"control_id": "page", "ancestor_control_ids": ["field"]}),  # 循环。
        ({"ancestor_control_ids": ["page"]}, {"control_id": "page", "bbox": {"x": 100, "y": 80, "w": 160, "h": 50}}),  # 非严格包含。
    ],
)
def test_fill_field_rejects_unconfirmed_or_corrupt_group_overlap(field_extra, page_extra):
    field = _combo(**field_extra)
    page = _group(**page_extra)
    result = _classify([page, field])

    assert result["hard_blocked"] is True
    assert "editable_text_field_overlaps_actionable_control" in result["reasons"]


def test_fill_field_rejects_group_overlap_when_control_ids_are_duplicated():
    field = _combo(ancestor_control_ids=["page"])
    duplicate = _edit("page", bbox={"x": 500, "y": 300, "w": 20, "h": 20})
    result = _classify([_group(), duplicate, field])

    assert result["hard_blocked"] is True
    assert "editable_text_field_overlaps_actionable_control" in result["reasons"]


def test_fill_field_keeps_danger_text_check_for_confirmed_group_ancestor():
    field = _combo(ancestor_control_ids=["page"])
    page = _group(name="Delete account")

    result = _classify([page, field])

    assert result["hard_blocked"] is True
    assert "destructive_delete_target" in result["reasons"]
