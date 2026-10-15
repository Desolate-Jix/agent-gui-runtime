"""离线核对先观察后匹配的三选一边界，不替代模型识图验收。"""
import pytest

from app.judgment.choice_contract import (
    CHOICE_NAME,
    CHOICES,
    candidate_choice_question,
    input_clicked_choice_question,
)


def assert_choice_contract(question):
    assert set(question) == {"type", "name", "instructions", "choices"}
    assert question["type"] == "choice" and question["name"] == CHOICE_NAME == "current_step"
    assert [item["value"] for item in question["choices"]] == list(CHOICES)
    assert all(set(item) == {"value", "description"} for item in question["choices"])


@pytest.mark.parametrize("options", [{}, {"input_sequence": True}, {"submit_search": True}])
def test_candidate_observes_marked_graphic_before_matching_target(options):
    question = candidate_choice_question(**options)
    assert_choice_contract(question)
    text = question["instructions"]
    assert text.index("Inspect Detail first") < text.index("Compare")
    assert "graphic, visible text or control" in text
    assert "center of the cyan click marker" in text
    assert "annotation, not the target's icon" in text
    assert "Overview only when needed" in text
    assert "Current target and action.target" in text
    assert "lookalike" in text and "visible shape" in text
    assert "Classify this target match once" in text


def test_candidate_choices_keep_visible_mismatch_local_block_and_missing_evidence_distinct():
    question = candidate_choice_question()
    choices = {item["value"]: item["description"] for item in question["choices"]}
    assert "matches" in choices["condition_met"] and "usable" in choices["condition_met"]
    assert all(item in choices["condition_not_met"] for item in ("different", "disabled", "directly blocked"))
    assert all(item in choices["evidence_insufficient"] for item in ("occluded", "missing", "ambiguous"))
    text = question["instructions"]
    assert "target-local obstruction" in text and "unrelated popup" in text
    assert "Artificial crop edges are not UI occlusion" in text
    assert all(item not in text for item in ("permitted action", "permitted class", "final-submit", "post-click focus"))


@pytest.mark.parametrize("options", [{"input_sequence": True}, {"submit_search": True}])
def test_candidate_input_variants_stay_on_current_marked_control(options):
    text = candidate_choice_question(**options)["instructions"]
    assert "marked text input itself" in text
    assert "Enter" not in text and "already verified" not in text


def test_recorded_click_observes_input_without_requiring_focus_or_empty_value():
    question = input_clicked_choice_question()
    assert_choice_contract(question)
    text = question["instructions"]
    assert text.index("Inspect Detail first") < text.index("Match")
    assert "center of the cyan recorded-click marker" in text
    assert "annotation" in text and "action.field.field_goal" in text
    assert "recorded-click location only" in text
    assert "Keyboard focus and the field's value are outside this check" in text
    assert "empty" not in text and "can text be entered" not in text


def test_prompt_has_no_site_specific_or_binary_symbol_rule():
    for question in (candidate_choice_question(), input_clicked_choice_question()):
        text = question["instructions"].lower()
        assert all(item not in text for item in ("browser", "chrome", "google", "plus sign", "plus symbol"))
        assert "output an explanation" not in text
