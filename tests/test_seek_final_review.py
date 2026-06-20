from __future__ import annotations

from app.seek.final_review import build_seek_final_review_extraction


def _record() -> dict:
    return {
        "contract_version": "seek_application_fill_record_v1",
        "job_id": "seek_job_92822270",
        "job_title": "Software Engineer (Business Systems)",
        "stage": "review_before_submit",
        "submit_clicks": 0,
        "final_submissions": 0,
        "filled_content": {
            "resume": "WENQING JI.pdf (SEEK default/selected resume)",
            "cover_letter": (
                "Dear Hiring Team,\n\n"
                "I am interested in the Software Engineer role because it aligns with collaboration and innovation. "
                "My relevant background includes React, SQL, AI, Frontend, Prompt Engineering, and careful testing.\n\n"
                "Kind regards,\nWenqing Ji"
            ),
            "employer_questions": [
                {
                    "question": "Which of the following statements best describes your right to work in New Zealand?",
                    "answer": "I have a graduate temporary work visa (e.g. post study work visa - open)",
                },
                {
                    "question": "Do you have at least 1-2 years of experience in web application development?",
                    "answer": "Yes",
                },
                {
                    "question": "Are you comfortable reading, altering and designing solutions with Java, React, Vue, MySQL?",
                    "answer": "Yes",
                },
                {
                    "question": "Can you start immediately or within 1-2 weeks?",
                    "answer": "Yes, I can start immediately or within 1-2 weeks.",
                },
            ],
            "seek_profile_mutation": "none",
        },
        "filled_fields": [
            {"step": "choose_documents", "field": "resume", "value": "WENQING JI.pdf", "policy": "unchanged"},
            {
                "step": "choose_documents",
                "field": "cover_letter",
                "value": "Dear Hiring Team...",
                "policy": "replaced_existing_cover_letter",
            },
            {
                "step": "update_seek_profile",
                "field": "resume_role_suggestions",
                "value": "Selected Don't include",
                "policy": "do_not_mutate_profile_without_explicit_user_approval",
            },
        ],
    }


def _observation(extra_text: list[str] | None = None) -> dict:
    texts = [
        "Review and submit",
        "WENQING JI.pdf",
        "I am interested in the Software Engineer role because it aligns with collaboration and innovation.",
        "My relevant background includes React, SQL, AI, Frontend, Prompt Engineering, and careful testing.",
        "Which of the following statements best describes your right to work in New Zealand?",
        "I have a graduate temporary work visa (e.g. post study work visa - open)",
        "Do you have at least 1-2 years of experience in web application development?",
        "Yes",
        "Are you comfortable reading, altering and designing solutions with Java, React, Vue, MySQL?",
        "Yes",
        "Can you start immediately or within 1-2 weeks?",
        "Yes, I can start immediately or within 1-2 weeks.",
        "Submit application",
    ]
    if extra_text:
        texts.extend(extra_text)
    return {
        "contract_version": "screen_observation_v1",
        "trace_path": "logs/traces/vision/review.json",
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [{"label": "Submit application"}],
            "page_elements": [{"text": text} for text in texts],
        },
    }


def _flow_state() -> dict:
    return {
        "contract_version": "seek_application_flow_state_v1",
        "current_step": "review_and_submit",
        "state_type": "final_submit_visible",
        "final_submit_visible_blocker": {"blocked": True, "matched_terms": ["Submit application"]},
    }


def test_final_review_extraction_requires_submit_visible_but_not_clicked() -> None:
    extraction = build_seek_final_review_extraction(_record(), observation=_observation(), flow_state=_flow_state())

    assert extraction["contract_version"] == "seek_final_review_extraction_v1"
    assert extraction["status"] == "pass"
    assert extraction["submit_application_visible"] is True
    assert extraction["submit_clicks"] == 0
    assert extraction["final_submissions"] == 0
    assert extraction["review_reconciliation"]["safety_decision"] == "stop_before_final_submit"


def test_final_review_matches_cover_letter_latest_hash() -> None:
    extraction = build_seek_final_review_extraction(_record(), observation=_observation(), flow_state=_flow_state())

    cover = extraction["cover_letter"]
    assert cover["matched"] is True
    assert cover["sha256"]
    assert cover["length"] > 120
    assert extraction["review_reconciliation"]["checks"]["cover_letter_latest_hash"] == cover["sha256"]


def test_final_review_matches_4_of_4_employer_questions() -> None:
    extraction = build_seek_final_review_extraction(_record(), observation=_observation(), flow_state=_flow_state())

    assert extraction["employer_questions"]["expected_count"] == 4
    assert extraction["employer_questions"]["matched_count"] == 4
    assert extraction["review_reconciliation"]["checks"]["employer_questions_matched"] == 4


def test_final_review_fails_if_expected_answer_missing() -> None:
    observation = _observation()
    observation["screen_inventory"]["page_elements"] = [
        item
        for item in observation["screen_inventory"]["page_elements"]
        if item["text"] != "Yes, I can start immediately or within 1-2 weeks."
    ]

    extraction = build_seek_final_review_extraction(_record(), observation=observation, flow_state=_flow_state())

    assert extraction["status"] == "needs_review"
    assert extraction["employer_questions"]["matched_count"] == 3
    assert "Can you start immediately or within 1-2 weeks?" in extraction["review_reconciliation"]["missing"]


def test_final_review_extraction_never_clicks_submit_application() -> None:
    record = _record()
    record["submit_clicks"] = 1

    extraction = build_seek_final_review_extraction(record, observation=_observation(), flow_state=_flow_state())

    assert extraction["status"] == "needs_review"
    assert extraction["submit_clicks"] == 1
    assert extraction["final_submissions"] == 0
    assert extraction["review_reconciliation"]["safety_decision"] == "unsafe_final_submit_counter_seen"
