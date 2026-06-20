from __future__ import annotations

from app.seek.application import (
    assess_seek_application_flow_state,
    build_seek_application_final_review_audit,
    build_seek_apply_flow_decision,
)


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


def test_application_flow_state_ignores_generic_generated_submit_button_label() -> None:
    observation = {
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [
                {"id": "action_screen_2_submit-button", "label": "Submit button", "role": "button"},
                {"id": "action_uia_continue", "text": "Continue", "role": "button"},
            ],
            "page_elements": [{"text": "Cover letter"}, {"text": "Write a cover letter"}],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation)

    assert state["state_type"] == "cover_letter_field_detected"
    assert state["final_submit_visible"] is False
    assert state["final_submit_visible_blocker"]["matched_items"] == []


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


def test_application_flow_state_ignores_progress_steps_on_choose_documents() -> None:
    observation = {
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [
                {"label": "Answer employer questions", "role": "button"},
                {"label": "Review and submit", "role": "button"},
                {"label": "Continue", "role": "button"},
            ],
            "page_elements": [
                {"text": "Choose documents"},
                {"text": "Answer employer questions"},
                {"text": "Review and submit"},
                {"text": "Upload a resume"},
                {"text": "13/5/26-WENQING JI.pdf"},
                {"text": "Resume attached"},
                {"text": "Upload a cover letter"},
                {"text": "Write a cover letter"},
                {"text": "Cover letter"},
                {"text": "Explore salaries"},
            ],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation)

    assert state["state_type"] == "cover_letter_field_detected"
    assert state["final_submit_visible"] is False
    assert state["application_form_inventory"]["screening_questions_detected"] is False
    assert "risky_questions_present" not in state["risk_flags"]


def test_application_flow_state_reads_degraded_observation_texts() -> None:
    observation = {
        "contract_version": "screen_observation_v1",
        "status": "degraded",
        "texts": [
            {"id": "ocr_0", "text": "Choose documents", "bbox": {"x": 804, "y": 422, "w": 169, "h": 26}},
            {"id": "ocr_1", "text": "Answer employer questions", "bbox": {"x": 1065, "y": 422, "w": 255, "h": 26}},
            {"id": "ocr_2", "text": "Review and submit", "bbox": {"x": 1591, "y": 422, "w": 196, "h": 26}},
            {"id": "ocr_3", "text": "Cover letter", "bbox": {"x": 803, "y": 1018, "w": 135, "h": 34}},
            {"id": "ocr_4", "text": "Write a cover letter", "bbox": {"x": 837, "y": 1118, "w": 190, "h": 25}},
            {
                "id": "ocr_5",
                "text": "Dear Alicia, I am writing to apply for the Junior Java Developer contract role.",
                "bbox": {"x": 855, "y": 1266, "w": 492, "h": 28},
            },
            {
                "id": "ocr_6",
                "text": "Technology and hold a valid open work visa for New Zealand.",
                "bbox": {"x": 855, "y": 1312, "w": 530, "h": 26},
            },
            {"id": "ocr_7", "text": "Continue", "bbox": {"x": 821, "y": 1332, "w": 110, "h": 36}},
        ],
    }

    state = assess_seek_application_flow_state(observation)

    assert state["state_type"] == "cover_letter_field_detected"
    assert state["application_form_inventory"]["cover_letter_field_detected"] is True
    assert state["evidence"]["text_count"] == len(observation["texts"])
    assert "risky_questions_present" not in state["risk_flags"]
    fields = state["application_form_inventory"]["fields"]
    assert any(item["text"] == "Cover letter body" and item["role"] == "textarea" for item in fields)


def test_application_flow_state_ignores_risky_terms_inside_existing_cover_letter_body() -> None:
    observation = {
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [
                {
                    "label": "Cover letter",
                    "role": "group",
                    "bbox": {"x": 802, "y": 1074, "w": 661, "h": 339},
                },
                {
                    "label": (
                        "Dear Alicia, I hold a valid open work visa for New Zealand and I am writing "
                        "to apply for this role because my automation experience matches the team."
                    ),
                    "role": "input",
                    "bbox": {"x": 838, "y": 1201, "w": 625, "h": 172},
                }
            ],
            "page_elements": [
                {"text": "Cover letter"},
                {"text": "Write a cover letter"},
                {
                    "text": "Technology and hold a valid open work visa for New Zealand. I am",
                    "role": "text",
                    "bbox": {"x": 853, "y": 1312, "w": 530, "h": 26},
                },
                {"text": "Continue"},
            ],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation)

    assert state["state_type"] == "cover_letter_field_detected"
    assert "risky_questions_present" not in state["risk_flags"]


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


def test_application_flow_state_detects_review_and_submit_as_review_step_not_final_submit() -> None:
    observation = {
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [{"label": "Review and submit"}],
            "page_elements": [{"text": "Please review your application before continuing"}],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation)

    assert state["state_type"] == "review_step_detected"
    assert state["stop_reason"] == "review_step_stop_before_final_submit"
    assert state["final_submit_visible_blocker"]["blocked"] is False
    assert "review and submit" not in state["final_submit_visible_blocker"]["matched_terms"]


def test_application_flow_state_does_not_treat_progress_review_label_as_current_step() -> None:
    observation = {
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [
                {
                    "label": "https://nz.seek.com/job/92566124/apply/profile?sol=abc",
                    "role": "input",
                },
                {"label": "Review and submit", "role": "button"},
                {"label": "Continue", "role": "button"},
            ],
            "page_elements": [
                {"text": "Update SEEK Profile | SEEK"},
                {"text": "Choose documents"},
                {"text": "Answer employer questions"},
                {"text": "Update SEEK Profile"},
                {"text": "Review and submit"},
                {"text": "Your SEEK Profile is part of your application."},
            ],
            "cards": [],
        },
    }

    state = assess_seek_application_flow_state(observation)

    assert state["current_step"] == "update_seek_profile"
    assert state["state_type"] != "review_step_detected"
    assert state["stop_reason"] != "review_step_stop_before_final_submit"
    assert state["final_submit_visible"] is False


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


def test_apply_flow_decision_defers_third_party_ats() -> None:
    state = assess_seek_application_flow_state(
        {
            "trace_path": "logs/traces/vision/workday.json",
            "screen_inventory": {
                "contract_version": "screen_inventory_v1",
                "available_actions": [{"label": "Apply"}],
                "page_elements": [{"text": "Workday"}, {"text": "Fiserv careers"}],
                "cards": [],
            },
        }
    )

    decision = build_seek_apply_flow_decision(state)

    assert decision["contract_version"] == "seek_apply_flow_decision_v1"
    assert decision["source_state_type"] == "third_party_ats"
    assert decision["state_type"] == "third_party_ats_deferred"
    assert decision["decision"] == "stop"
    assert decision["blocked_downstream"] == {
        "cover_letter_draft": True,
        "answer_plan": True,
        "safe_fill": True,
        "submit": True,
    }
    assert decision["allowed_next_steps"] == ["capture", "back_to_seek", "match"]
    assert decision["safety_counters"]["forms_filled"] == 0


def test_apply_flow_decision_allows_seek_internal_read_only_plan() -> None:
    state = assess_seek_application_flow_state(
        {
            "screen_inventory": {
                "contract_version": "screen_inventory_v1",
                "available_actions": [{"label": "Save draft"}],
                "page_elements": [{"text": "Apply with SEEK"}, {"text": "Cover letter"}],
                "cards": [],
            },
        }
    )

    decision = build_seek_apply_flow_decision(state)

    assert decision["state_type"] == "seek_internal_cover_letter_field_detected"
    assert decision["decision"] == "continue_read_only"
    assert decision["blocked_downstream"]["cover_letter_draft"] is False
    assert decision["blocked_downstream"]["answer_plan"] is False
    assert decision["blocked_downstream"]["submit"] is True


def test_final_review_audit_passes_station_internal_fill_before_submit(tmp_path) -> None:
    review = tmp_path / "review.png"
    trace = tmp_path / "type-text.json"
    review.write_bytes(b"png")
    trace.write_text("{}", encoding="utf-8")
    record = {
        "job_id": "92822270",
        "job_title": "Software Engineer (Business Systems)",
        "apply_url": "https://nz.seek.com/job/92822270/apply",
        "stage": "review_before_submit",
        "filled_fields": [
            {"step": "choose_documents", "field": "resume", "value": "WENQING JI.pdf", "policy": "unchanged"},
            {"step": "choose_documents", "field": "cover_letter", "value": "Dear Alicia...", "policy": "replaced_existing_cover_letter"},
            {"step": "answer_employer_questions", "field": "right_to_work_nz", "value": "Post-study open work visa"},
            {"step": "answer_employer_questions", "field": "web_experience", "value": "Yes"},
            {"step": "answer_employer_questions", "field": "stack_comfort", "value": "Yes"},
            {"step": "answer_employer_questions", "field": "availability", "value": "Within 1-2 weeks"},
            {
                "step": "update_seek_profile",
                "field": "resume_role_suggestions",
                "value": "Selected Don't include for suggested profile additions.",
                "policy": "do_not_mutate_profile_without_explicit_user_approval",
            },
        ],
        "evidence": {
            "review_before_submit_screenshot": str(review),
            "clipboard_fix_type_text_trace": str(trace),
            "final_submit_clicked": False,
        },
    }

    audit = build_seek_application_final_review_audit(record, base_dir=tmp_path, created_at="2026-06-20T00:00:00Z")

    assert audit["contract_version"] == "seek_application_final_review_audit_v1"
    assert audit["decision"] == "pass_stopped_before_final_submit"
    assert audit["checks"]["final_submissions"] == 0
    assert audit["checks"]["submit_clicks"] == 0
    assert audit["checks"]["cover_letter_filled"] is True
    assert audit["checks"]["employer_questions_answered"] == "4/4"
    assert audit["checks"]["persistent_profile_updates"] == 0
    assert audit["checks"]["seek_profile_suggestions_choice"] == "Don't include"
    assert audit["checks"]["final_review_screenshot_exists"] is True


def test_final_review_audit_passes_when_seek_profile_suggestions_not_shown(tmp_path) -> None:
    review = tmp_path / "review.png"
    trace = tmp_path / "type-text.json"
    review.write_bytes(b"png")
    trace.write_text("{}", encoding="utf-8")
    record = {
        "job_id": "92566124",
        "job_title": "Intermediate Engineer - AI Automation & Integration",
        "apply_url": "https://nz.seek.com/job/92566124/apply/review",
        "stage": "review_before_submit",
        "employer_question_total": 2,
        "filled_fields": [
            {"step": "choose_documents", "field": "resume", "value": "WENQING JI.pdf", "policy": "unchanged"},
            {"step": "choose_documents", "field": "cover_letter", "value": "Dear Hiring Team...", "policy": "replaced_existing_cover_letter"},
            {"step": "answer_employer_questions", "field": "right_to_work_nz", "value": "Post-study open work visa"},
            {"step": "answer_employer_questions", "field": "notice_period", "value": "None, I'm ready to go now"},
        ],
        "evidence": {
            "review_before_submit_screenshot": str(review),
            "cover_letter_type_text_trace": str(trace),
            "final_submit_clicked": False,
        },
    }

    audit = build_seek_application_final_review_audit(record, base_dir=tmp_path, created_at="2026-06-20T00:00:00Z")

    assert audit["decision"] == "pass_stopped_before_final_submit"
    assert audit["checks"]["seek_profile_suggestions_choice"] == "not_shown"
    assert audit["checks"]["persistent_profile_updates"] == 0


def test_final_review_audit_passes_when_no_employer_questions_were_shown(tmp_path) -> None:
    review = tmp_path / "review.png"
    trace = tmp_path / "type-text.json"
    review.write_bytes(b"png")
    trace.write_text("{}", encoding="utf-8")
    record = {
        "job_id": "92763500",
        "job_title": "Software Engineers",
        "apply_url": "https://nz.seek.com/job/92763500/apply/review",
        "stage": "review_before_submit",
        "employer_question_total": 0,
        "filled_fields": [
            {"step": "choose_documents", "field": "resume", "value": "WENQING JI.pdf", "policy": "unchanged"},
            {
                "step": "choose_documents",
                "field": "cover_letter",
                "value": "Dear Hiring Team...",
                "policy": "replaced_existing_cover_letter",
            },
        ],
        "evidence": {
            "review_before_submit_screenshot": str(review),
            "cover_letter_type_text_trace": str(trace),
            "final_submit_clicked": False,
        },
    }

    audit = build_seek_application_final_review_audit(record, base_dir=tmp_path, created_at="2026-06-20T00:00:00Z")

    assert audit["decision"] == "pass_stopped_before_final_submit"
    assert audit["checks"]["employer_questions_answered"] == "0/0"
    assert audit["checks"]["cover_letter_filled"] is True
    assert audit["checks"]["resume_kept"] is True


def test_final_review_audit_fails_when_submit_was_clicked(tmp_path) -> None:
    review = tmp_path / "review.png"
    trace = tmp_path / "type-text.json"
    review.write_bytes(b"png")
    trace.write_text("{}", encoding="utf-8")
    record = {
        "stage": "review_before_submit",
        "final_submissions": 1,
        "submit_clicks": 1,
        "filled_fields": [
            {"step": "choose_documents", "field": "resume", "value": "WENQING JI.pdf"},
            {"step": "choose_documents", "field": "cover_letter", "value": "Cover letter"},
            {"step": "answer_employer_questions", "field": "availability", "value": "Within 1-2 weeks"},
            {
                "step": "update_seek_profile",
                "field": "resume_role_suggestions",
                "value": "Selected Don't include",
                "policy": "do_not_mutate_profile_without_explicit_user_approval",
            },
        ],
        "evidence": {
            "review_before_submit_screenshot": str(review),
            "clipboard_fix_type_text_trace": str(trace),
        },
    }

    audit = build_seek_application_final_review_audit(record, base_dir=tmp_path)

    assert audit["decision"] == "needs_review"
    assert audit["checks"]["final_submissions"] == 1
    assert audit["checks"]["submit_clicks"] == 1
