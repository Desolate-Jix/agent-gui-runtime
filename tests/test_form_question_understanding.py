from __future__ import annotations

import pytest

from app.agent.form_question_understanding import normalize_form_question_intent


def _question(label: str, *, field_type: str = "radio", question_id: str = "q1") -> dict:
    return {
        "contract_version": "form_question_contract_v1",
        "question_id": question_id,
        "label": label,
        "field_type": field_type,
        "required": True,
        "disabled": False,
        "risk": "ordinary_field",
        "options": [
            {"option_id": "yes", "label": "Yes", "disabled": False},
            {"option_id": "no", "label": "No", "disabled": False},
        ],
        "source_capture_id": "capture-current",
    }


@pytest.mark.parametrize(
    "label",
    [
        "Do you have the right to work in New Zealand?",
        "Are you legally authorized to work in New Zealand?",
        "Can you work in New Zealand without employer sponsorship?",
    ],
)
def test_work_authorization_positive_polarity_is_normalized(label: str) -> None:
    result = normalize_form_question_intent(_question(label))

    assert result["contract_version"] == "normalized_question_intent_v1"
    assert result["intent"] == "authorized_to_work_without_sponsorship"
    assert result["polarity"] == "affirmative_means_intent_true"
    assert result["risk"] == "controlled_review"
    assert result["recommended_policy"] == "needs_user_review"
    assert result["confidence"] >= 0.9
    assert result["evidence"]
    assert result["artifact_is_authorization"] is False


@pytest.mark.parametrize(
    "label",
    [
        "Do you require employer sponsorship to work in New Zealand?",
        "Will you now or in the future require visa sponsorship?",
        "Do you need sponsorship for this role?",
    ],
)
def test_sponsorship_requirement_uses_inverse_polarity(label: str) -> None:
    result = normalize_form_question_intent(_question(label))

    assert result["intent"] == "authorized_to_work_without_sponsorship"
    assert result["polarity"] == "affirmative_means_intent_false"
    assert result["recommended_policy"] == "needs_user_review"
    assert result["confidence"] >= 0.9


@pytest.mark.parametrize(
    "label",
    [
        "Do you not require employer sponsorship to work in New Zealand?",
        "I confirm that I do not need visa sponsorship.",
    ],
)
def test_negated_sponsorship_requirement_restores_positive_polarity(label: str) -> None:
    result = normalize_form_question_intent(_question(label))

    assert result["intent"] == "authorized_to_work_without_sponsorship"
    assert result["polarity"] == "affirmative_means_intent_true"
    assert result["recommended_policy"] == "needs_user_review"
    assert result["confidence"] >= 0.9


def test_temporally_conflicting_sponsorship_statement_fails_closed() -> None:
    result = normalize_form_question_intent(
        _question("I do not require sponsorship now but will require sponsorship in the future.")
    )

    assert result["intent"] == "authorized_to_work_without_sponsorship"
    assert result["polarity"] == "ambiguous"
    assert result["confidence"] == 0.0
    assert result["blockers"] == ["conflicting_polarity_evidence"]


def test_conflicting_work_authorization_polarity_fails_closed() -> None:
    result = normalize_form_question_intent(
        _question("Do you have the right to work and require sponsorship?")
    )

    assert result["intent"] == "authorized_to_work_without_sponsorship"
    assert result["polarity"] == "ambiguous"
    assert result["confidence"] == 0.0
    assert result["recommended_policy"] == "needs_user_review"
    assert result["blockers"] == ["conflicting_polarity_evidence"]


@pytest.mark.parametrize(
    ("label", "intent", "risk", "policy"),
    [
        ("What are your salary expectations?", "salary_expectation", "negotiable", "needs_user_review"),
        ("Are you willing to relocate?", "relocation_willingness", "consequential", "needs_user_review"),
        ("Please disclose your criminal history", "criminal_history", "sensitive", "blocked_sensitive"),
        ("Do you have a health or medical condition?", "health_information", "sensitive", "blocked_sensitive"),
    ],
)
def test_nonordinary_question_intents_keep_strict_policy(
    label: str,
    intent: str,
    risk: str,
    policy: str,
) -> None:
    result = normalize_form_question_intent(_question(label, field_type="textarea"))

    assert result["intent"] == intent
    assert result["polarity"] == "neutral"
    assert result["risk"] == risk
    assert result["recommended_policy"] == policy


def test_unknown_open_question_is_not_guessed() -> None:
    result = normalize_form_question_intent(
        _question("Tell us what makes you different", field_type="textarea")
    )

    assert result["intent"] == "unknown_open_text"
    assert result["polarity"] == "unknown"
    assert result["risk"] == "unknown"
    assert result["confidence"] <= 0.25
    assert result["recommended_policy"] == "needs_user_review"
    assert result["blockers"] == ["unrecognized_question_intent"]


def test_plain_visa_status_is_complex_without_boolean_polarity() -> None:
    result = normalize_form_question_intent(
        _question("Describe your current visa status", field_type="textarea")
    )

    assert result["intent"] == "visa_status"
    assert result["polarity"] == "neutral"
    assert result["risk"] == "complex"
    assert result["recommended_policy"] == "needs_user_review"
