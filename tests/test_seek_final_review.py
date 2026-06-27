from __future__ import annotations

from app.seek.final_review import build_seek_final_review_extraction


def test_final_review_accepts_seek_answered_count_summary_for_employer_questions() -> None:
    record = {
        "contract_version": "seek_application_fill_record_v1",
        "stage": "review_before_submit",
        "submit_clicks": 0,
        "final_submissions": 0,
        "filled_content": {
            "resume": "WENQING JI.pdf (SEEK default/selected resume)",
            "cover_letter": "Dear Hiring Team,\nI am interested in this role because it matches my software engineering skills.",
            "employer_questions": [
                {"question": "Gender", "answer": "Do not wish to disclose"},
                {
                    "question": "Do you have an existing right to work in New Zealand without the need for employer sponsorship?",
                    "answer": "Yes",
                },
                {
                    "question": "Which of the following statements best describes your right to work in New Zealand?",
                    "answer": "I have a graduate temporary work visa (e.g. post study work visa - open)",
                },
            ],
        },
    }
    observation = {
        "contract_version": "screen_observation_v1",
        "screen_inventory": {
            "page_elements": [
                {"text": "Review and submit"},
                {"text": "WENQING JI.pdf"},
                {"text": "You wrote a cover letter for this application"},
                {"text": "Employer questions"},
                {"text": "You answered 3 out of 3"},
                {"text": "Submit application"},
            ]
        },
    }
    flow_state = {
        "contract_version": "seek_application_flow_state_v1",
        "current_step": "review_and_submit",
        "final_submit_visible_blocker": {"blocked": True},
    }

    extraction = build_seek_final_review_extraction(record, observation=observation, flow_state=flow_state)

    assert extraction["status"] == "pass"
    assert extraction["submit_application_visible"] is True
    assert extraction["employer_questions"]["verification_depth"] == "summary_count"
    assert extraction["review_reconciliation"]["checks"]["employer_questions_matched"] == 3
    assert extraction["review_reconciliation"]["checks"]["final_submissions"] == 0


def test_final_review_accepts_filename_scoped_ocr_confusion_for_resume() -> None:
    record = {
        "contract_version": "seek_application_fill_record_v1",
        "stage": "review_before_submit",
        "submit_clicks": 0,
        "final_submissions": 0,
        "filled_content": {
            "resume": "WENQING JI.pdf (SEEK default/selected resume)",
            "cover_letter": "Dear Hiring Team,\nI am interested in this role because it matches my software engineering skills.",
            "employer_questions": [],
        },
    }
    observation = {
        "contract_version": "screen_observation_v1",
        "screen_inventory": {
            "page_elements": [
                {"text": "Review and submit"},
                {"text": "WENQING JIl.pdf"},
                {"text": "You wrote a cover letter for this application"},
                {"text": "Submit application"},
            ]
        },
    }
    flow_state = {
        "contract_version": "seek_application_flow_state_v1",
        "current_step": "review_and_submit",
        "final_submit_visible_blocker": {"blocked": True},
    }

    extraction = build_seek_final_review_extraction(record, observation=observation, flow_state=flow_state)

    assert extraction["status"] == "pass"
    assert extraction["resume"]["reason"] == "filename_ocr_canonicalized_match"
    assert extraction["resume"]["normalization_scope"] == "filename_short_token_ocr"
