from __future__ import annotations

from app.seek.final_review import build_seek_final_review_extraction
from scripts.seek_debug_step_runner import _merge_review_observations


def test_merge_review_observations_keeps_top_and_bottom_review_evidence() -> None:
    top = {
        "contract_version": "screen_observation_v1",
        "screen_inventory": {
            "page_elements": [
                {"id": "title", "text": "Review and submit", "role": "text"},
                {"id": "resume", "text": "WENQING JI.pdf", "role": "text"},
                {"id": "cover", "text": "You wrote a cover letter for this application", "role": "text"},
            ]
        },
    }
    bottom = {
        "contract_version": "screen_observation_v1",
        "screen_inventory": {
            "page_elements": [
                {"id": "questions", "text": "You answered 3 out of 3", "role": "text"},
                {"id": "submit", "text": "Submit application", "role": "text"},
            ]
        },
    }
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
    flow_state = {
        "contract_version": "seek_application_flow_state_v1",
        "current_step": "review_and_submit",
        "final_submit_visible_blocker": {"blocked": True},
    }

    merged = _merge_review_observations([top, bottom])
    extraction = build_seek_final_review_extraction(record, observation=merged, flow_state=flow_state)

    assert merged["merged_review_observation"]["source_observation_count"] == 2
    assert extraction["status"] == "pass"
    assert extraction["resume"]["matched"] is True
    assert extraction["cover_letter"]["matched"] is True
    assert extraction["submit_application_visible"] is True
