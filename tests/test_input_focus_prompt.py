"""普通点击输入框也必须给模型明确的内部聚焦任务，不能只处理填写意图。"""
import pytest

from app.api import vision
from app.core import local_text_focus


DESCRIPTIVE_FIELD_GOAL = (
    "The long folder path address input directly below the toolbar, on the left side inside "
    "its white text area just after the folder icon, above the file list. "
    "Enter the specified fresh test directory path here.")


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


def test_internal_sequence_focus_preserves_descriptive_goal_and_interior_instruction():
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        prompt = vision._vista_direct_prompt(DESCRIPTIVE_FIELD_GOAL)
    assert DESCRIPTIVE_FIELD_GOAL in prompt
    assert "interior of the editable field" in prompt
    assert "away from its borders" in prompt


@pytest.mark.parametrize("target", [None, {
    "contract_version": "recognition_control_target_v1", "role": "button",
    "label": "Search", "source_binding_sha256": "a" * 64}])
def test_internal_focus_keeps_explicit_word_and_noninput_target_exclusions(target):
    goal = "Double click the word Rotorua inside the search input box" if target is None else "Search"
    original = vision._vista_direct_prompt(goal, target)
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        assert vision._vista_direct_prompt(goal, target) == original
    assert "interior of the editable field" not in original


def test_internal_focus_does_not_change_strict_fill_prompt():
    original = vision._vista_direct_prompt("Search", semantic_action="fill_field")
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        assert vision._vista_direct_prompt("Search", semantic_action="fill_field") == original


def test_claimed_and_exited_focus_scopes_do_not_change_prompt(monkeypatch):
    original = vision._vista_direct_prompt(DESCRIPTIVE_FIELD_GOAL)
    monkeypatch.setattr(local_text_focus, "require_local_operator_input", lambda manager: True)
    monkeypatch.setattr(local_text_focus, "probe_local_focus_target", lambda *args, **kwargs:
        {"control_type": "Edit", "runtime_id": [42, 1]})
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        local_text_focus.check_local_text_focus({"x": 90, "y": 87}, object())
        assert vision._vista_direct_prompt(DESCRIPTIVE_FIELD_GOAL) == original
    assert vision._vista_direct_prompt(DESCRIPTIVE_FIELD_GOAL) == original


def test_copied_focus_scope_in_another_thread_does_not_change_prompt():
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    original = vision._vista_direct_prompt(DESCRIPTIVE_FIELD_GOAL)
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        copied = copy_context()
        with ThreadPoolExecutor(max_workers=1) as worker:
            prompt = worker.submit(copied.run, vision._vista_direct_prompt, DESCRIPTIVE_FIELD_GOAL).result()
    assert prompt == original
