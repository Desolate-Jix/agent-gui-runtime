"""普通点击输入框也必须给模型明确的内部聚焦任务，不能只处理填写意图。"""
import pytest

from app.api import vision


@pytest.mark.parametrize("goal", [
    "Click the Bilibili search input box at the top center of the page, left of the magnifying-glass search icon",
    "Click the main Google search input box in the center of the page",
    "Click the Quick search input box",
    "Click inside the text area",
    "Focus the search box",
])
def test_field_click_preserves_goal_and_requests_interior_focus(goal):
    prompt = vision._vista_direct_prompt(goal)
    assert goal in prompt
    assert "interior of the editable field" in prompt
    assert "away from its borders" in prompt
    assert "not the search/action button" in prompt


@pytest.mark.parametrize("goal", [
    "Double click the word Rotorua inside the search input box",
    "Click the search button next to the input box",
    "Click the icon inside the search input box",
    "Click the result link labelled 'Search input box'",
])
def test_inner_word_or_action_is_not_rewritten_as_field_focus(goal):
    assert "interior of the editable field" not in vision._vista_direct_prompt(goal)


def test_explicit_field_preserves_label_without_retargeting_button():
    goal = "Click the input labelled 'Account search'"
    target = {"contract_version": "recognition_control_target_v1", "role": "input",
              "label": "Account search", "source_binding_sha256": "a" * 64}
    prompt = vision._vista_direct_prompt(goal, target)
    assert goal in prompt and '"Account search"' in prompt
    assert "interior of the editable field" in prompt


def test_fill_field_keeps_existing_interior_focus_instruction():
    assert "interior of the editable field" in vision._vista_direct_prompt("Search", semantic_action="fill_field")
