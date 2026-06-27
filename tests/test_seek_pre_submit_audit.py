from __future__ import annotations

from app.seek.pre_submit_audit import build_seek_final_submit_decision


def test_seek_final_submit_decision_blocks_unreviewed_non_auckland_contract_with_unsupported_yes() -> None:
    decision = build_seek_final_submit_decision(
        job={
            "title": "Software Engineer (Business Systems)",
            "company": "Sourced",
            "location": "Christchurch Central, Canterbury",
            "work_type": "6 month fixed term contract",
        },
        match_decision={"decision": "maybe_apply", "score": 0.58},
        application_answers=[
            {
                "question": "Are you comfortable with Java, AngularJS, React, Vue and MySQL?",
                "answer": "Yes",
                "supported_by_profile": False,
            }
        ],
        user_preferences={"preferred_locations": ["Auckland"], "accept_other_nz_locations": True},
        gpt_review={"decision": "maybe_apply_pending_user_review"},
        user_reviewed_current_job=False,
    )

    assert decision["contract_version"] == "final_submit_decision_v1"
    assert decision["allow_final_submit"] is False
    assert decision["submit_gate"] == "block"
    assert "match_decision_not_strong_apply" in decision["block_reasons"]
    assert "non_auckland_location_not_reviewed" in decision["block_reasons"]
    assert "contract_duration_not_reviewed" in decision["block_reasons"]
    assert decision["unsupported_yes_answers"] is True


def test_seek_final_submit_decision_allows_reviewed_strong_apply_with_supported_answers() -> None:
    decision = build_seek_final_submit_decision(
        job={
            "title": "Frontend Software Engineer",
            "company": "Example Co",
            "location": "Auckland CBD, Auckland",
            "work_type": "Full time",
        },
        match_decision={"decision": "strong_apply", "score": 0.82},
        application_answers=[
            {
                "question": "Do you have React and SQL experience?",
                "answer": "Yes",
                "supported_by_profile": True,
            }
        ],
        user_preferences={"preferred_locations": ["Auckland"]},
        gpt_review={"decision": "submit"},
        user_reviewed_current_job=True,
    )

    assert decision["allow_final_submit"] is True
    assert decision["submit_gate"] == "allow"
    assert decision["block_reasons"] == []
    assert decision["unsupported_yes_answers"] is False

