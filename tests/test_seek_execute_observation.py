from __future__ import annotations

from app.seek.execute_observation import build_seek_execute_observation


def test_seek_execute_observation_detects_review_submit_danger() -> None:
    flow = {
        "contract_version": "seek_application_flow_state_v1",
        "current_step": "review_and_submit",
        "state_type": "final_submit_visible",
        "application_form_inventory": {
            "fields": [
                {"id": "heading", "text": "Review and submit", "role": "text"},
                {"id": "submit", "text": "Submit application", "role": "button", "bbox": {"x": 1, "y": 2, "w": 3, "h": 4}},
            ],
            "actions": [],
        },
        "evidence": {"texts": ["Review and submit", "Submit application"]},
    }

    result = build_seek_execute_observation(application_flow_state=flow)

    assert result["contract_version"] == "execute_observation_v1"
    assert result["page_state"] == "review_before_submit"
    assert result["danger_actions"][0]["text"] == "Submit application"
    assert result["safety_blockers"][0]["kind"] == "final_submit_visible"


def test_seek_execute_observation_detects_profile_mutation_prompt() -> None:
    flow = {
        "current_step": "update_seek_profile",
        "application_form_inventory": {
            "fields": [
                {"id": "heading", "text": "Update SEEK Profile", "role": "text"},
                {"id": "add", "text": "Add skills", "role": "button"},
                {"id": "continue", "text": "Continue", "role": "button"},
            ],
        },
    }

    result = build_seek_execute_observation(application_flow_state=flow)

    assert result["page_state"] == "profile_prompt"
    assert result["primary_actions"][0]["text"] == "Continue"
    assert result["profile_mutation_actions"][0]["text"] == "Add skills"
    assert result["safety_blockers"][0]["kind"] == "profile_mutation_actions_visible"
