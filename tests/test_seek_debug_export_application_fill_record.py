from __future__ import annotations

from scripts.seek_debug_export_application_fill_record import _dedupe_employer_questions


def test_dedupe_employer_questions_filters_seek_error_summary_duplicate() -> None:
    questions = [
        {
            "question": "Which of the following statements best describes your right to work in New Zealand?-Please make a selection",
            "answer": "I have a graduate temporary work visa (e.g. post study work visa - open)",
            "evidence": "error summary",
        },
        {
            "question": "Gender",
            "answer": "Do not wish to disclose",
            "evidence": "safe default",
        },
        {
            "question": "Do you have an existing right to work in New Zealand without the need for employer sponsorship?",
            "answer": "Yes",
            "evidence": "work rights",
        },
        {
            "question": "Which of the following statements best describes yourright to work in New Zealand?",
            "answer": "I have a graduate temporary work visa (e.g. post study work visa - open)",
            "evidence": "visible selected option",
        },
    ]

    deduped = _dedupe_employer_questions(questions)

    assert [item["question"] for item in deduped] == [
        "Gender",
        "Do you have an existing right to work in New Zealand without the need for employer sponsorship?",
        "Which of the following statements best describes yourright to work in New Zealand?",
    ]
