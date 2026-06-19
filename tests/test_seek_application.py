from __future__ import annotations

from app.seek.application import assess_seek_application_flow_state


def test_application_flow_state_detects_final_submit_and_blocks() -> None:
    observation = {
        "trace_path": "logs/traces/vision/apply.json",
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [{"label": "Submit application"}],
            "page_elements": [{"text": "Review your application"}],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation, source_job={"job_id": "job-1", "title": "Software Engineer"})

    assert state["contract_version"] == "seek_application_flow_state_v1"
    assert state["status"] == "blocked_need_user_or_gpt_decision"
    assert state["state_type"] == "final_submit_visible"
    assert "final_submit_detected" in state["detected_states"]
    assert state["final_submit_visible"] is True
    assert state["final_submit_visible_blocker"]["contract_version"] == "final_submit_visible_blocker_v1"
    assert state["final_submit_visible_blocker"]["blocked"] is True
    assert "submit application" in state["final_submit_visible_blocker"]["matched_terms"]
    assert state["final_submission_performed"] is False
    assert state["source_job"]["title"] == "Software Engineer"


def test_application_flow_state_detects_apply_flow_without_final_submit() -> None:
    observation = {
        "trace_path": "logs/traces/vision/apply.json",
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [{"label": "Save draft"}],
            "page_elements": [{"text": "Apply with SEEK"}, {"text": "Cover letter"}],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation)

    assert state["state_type"] == "cover_letter_field_detected"
    assert state["application_flow_started"] is True
    assert state["final_submit_visible"] is False
    assert state["final_submit_visible_blocker"]["blocked"] is False
    assert state["application_form_inventory"]["cover_letter_field_detected"] is True
    assert state["stop_reason"] == "cover_letter_field_detected_stop_before_paste"


def test_application_flow_state_detects_risky_questions() -> None:
    observation = {
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [],
            "page_elements": [{"text": "What is your expected salary?"}, {"text": "Do you have the right to work in New Zealand?"}],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation)

    assert state["state_type"] == "risky_application_questions"
    assert "risky_questions_present" in state["risk_flags"]
    assert state["final_submission_performed"] is False


def test_application_flow_state_detects_review_and_submit_as_visible_blocker() -> None:
    observation = {
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [{"label": "Review and submit"}],
            "page_elements": [{"text": "Please review your application before continuing"}],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation)

    assert state["state_type"] == "final_submit_visible"
    assert state["stop_reason"] == "final_submit_visible_stop_before_submission"
    assert state["final_submit_visible_blocker"]["blocked"] is True
    assert "review and submit" in state["final_submit_visible_blocker"]["matched_terms"]


def test_application_flow_state_does_not_treat_negative_instruction_as_submit_button() -> None:
    observation = {
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [{"label": "Save draft"}],
            "page_elements": [
                {"text": "Do not click Submit during this read-only test.", "role": "instruction"},
                {"text": "Cover letter", "role": "textarea"},
            ],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation)

    assert state["state_type"] == "cover_letter_field_detected"
    assert state["final_submit_visible"] is False
    assert state["final_submit_visible_blocker"]["blocked"] is False
    assert state["final_submit_visible_blocker"]["matched_items"] == []


def test_application_flow_state_builds_read_only_form_inventory() -> None:
    observation = {
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [{"label": "Save draft"}],
            "page_elements": [
                {"text": "Screening question"},
                {"text": "Tell us why you are interested in this role", "role": "textarea"},
            ],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation)

    assert state["state_type"] == "screening_questions_detected"
    assert state["stop_reason"] == "screening_questions_stop_before_form_fill"
    assert state["application_form_inventory"]["contract_version"] == "application_form_inventory_v1"
    assert state["application_form_inventory"]["screening_questions_detected"] is True
    assert state["application_form_inventory"]["field_count"] >= 1
    assert state["final_submission_performed"] is False
