"""导航目标不能因同名输入值而被裁成填写字段的局部图。"""

import pytest

from tests.test_current_uia_primary_grounding import _control, _recognize


def _search_results(field_type):
    return [
        _control(control_id="query-field", name="Atlas Maps", control_type=field_type),
        _control(control_id="official-link", name="Atlas Maps official site https://maps.example.test",
            control_type="Hyperlink", automation_id="official-link", class_name="",
            patterns=["Invoke"], bbox={"x": 100, "y": 330, "w": 300, "h": 40},
            screen_bbox={"x": 100, "y": 330, "w": 300, "h": 40}),
    ]


@pytest.mark.parametrize("semantic_action", [None, "open_detail"])
@pytest.mark.parametrize("field_type", ["ComboBox", "Edit"])
def test_navigation_or_unspecified_goal_does_not_crop_to_same_name_field(
    tmp_path, monkeypatch, semantic_action, field_type,
):
    result, calls = _recognize(tmp_path, monkeypatch, controls=_search_results(field_type),
        goal="Atlas Maps", semantic_action=semantic_action, raw="[500, 850]")

    summary = result["candidate_result"]["summary"]
    assert summary["current_uia_primary_candidate_used"] is False
    assert summary["vista_direct_point_grounding_attempted"] is True
    assert summary["vista_roi_source"] != "current_uia_candidate_v1"
    assert calls
    assert result["model_io"]["attempts"][0]["image_preprocess"]["roi_policy"] == "vista_direct_full_screen_fallback"


@pytest.mark.parametrize("field_type", ["ComboBox", "Edit"])
def test_explicit_fill_keeps_current_field_shortcut_with_same_name_navigation_target(
    tmp_path, monkeypatch, field_type,
):
    result, calls = _recognize(tmp_path, monkeypatch, controls=_search_results(field_type),
        goal="Atlas Maps", semantic_action="fill_field")

    summary = result["candidate_result"]["summary"]
    assert summary["current_uia_primary_candidate_used"] is True
    assert summary["vista_roi_source"] == "current_uia_candidate_v1"
    assert result["pre_click_decision"]["allowed"] is True
    assert len(calls) == 1
