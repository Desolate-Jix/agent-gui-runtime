from __future__ import annotations

import json

from app.seek.answer_plan import build_application_answer_plan


def _flow_state() -> dict:
    return {
        "contract_version": "seek_application_flow_state_v1",
        "final_submit_visible_blocker": {
            "contract_version": "final_submit_visible_blocker_v1",
            "blocked": False,
            "matched_items": [],
        },
        "application_form_inventory": {
            "contract_version": "application_form_inventory_v1",
            "fields": [
                {"id": "name", "text": "Full name", "role": "text_input"},
                {"id": "cover", "text": "Cover letter", "role": "textarea"},
                {"id": "salary", "text": "Expected salary", "role": "text_input"},
                {"id": "upload", "text": "Upload resume", "role": "button"},
            ],
            "actions": [{"id": "save", "text": "Save draft", "role": "button"}],
        },
    }


def test_answer_plan_classifies_fields_without_filling() -> None:
    plan = build_application_answer_plan(
        profile={
            "contract_version": "candidate_profile_v1",
            "candidate_name": "Alex Chen",
            "work_rights_summary": "Eligible to work in New Zealand",
        },
        application_flow_state=_flow_state(),
        cover_letter_draft={
            "contract_version": "cover_letter_draft_v1",
            "status": "draft_only_not_pasted",
            "draft": "Dear Hiring Team, ...",
        },
    )

    assert plan["contract_version"] == "application_answer_plan_v1"
    assert plan["status"] == "planned_only_not_filled"
    assert plan["filled"] is False
    assert plan["counts"]["auto_safe_known"] == 2
    assert plan["counts"]["blocked_sensitive"] == 1
    assert plan["counts"]["unsupported"] == 1
    assert any(item["answer_source"] == "cover_letter_draft_v1.draft" for item in plan["planned_answers"])


def test_answer_plan_blocks_when_final_submit_visible() -> None:
    flow = _flow_state()
    flow["final_submit_visible_blocker"] = {
        "contract_version": "final_submit_visible_blocker_v1",
        "blocked": True,
        "matched_items": [{"id": "submit", "text": "Submit application", "role": "button"}],
    }

    plan = build_application_answer_plan(
        profile={"contract_version": "candidate_profile_v1"},
        application_flow_state=flow,
    )

    assert plan["status"] == "blocked_final_submit_visible"
    assert plan["counts"]["danger_final_submit"] == 1
    assert plan["stop_reason"] == "final_submit_visible_stop_before_answering"


def test_answer_plan_recognizes_common_safe_text_fields_only_with_profile_values() -> None:
    flow = {
        "contract_version": "seek_application_flow_state_v1",
        "final_submit_visible_blocker": {"blocked": False, "matched_items": []},
        "application_form_inventory": {
            "contract_version": "application_form_inventory_v1",
            "fields": [
                {"id": "first", "text": "First name", "role": "text_input"},
                {"id": "last", "text": "Last name", "role": "text_input"},
                {"id": "email", "text": "Email address", "role": "email_input"},
                {"id": "github", "text": "GitHub profile", "role": "url_input"},
                {"id": "phone", "text": "Phone", "role": "text_input"},
                {"id": "salary", "text": "Expected salary", "role": "text_input"},
                {"id": "start", "text": "Available to start", "role": "text_input"},
                {"id": "crime", "text": "Criminal conviction", "role": "text_input"},
                {"id": "health", "text": "Health declaration", "role": "text_input"},
                {"id": "visa", "text": "Visa status details", "role": "select"},
            ],
            "actions": [],
        },
    }

    plan = build_application_answer_plan(
        profile={
            "contract_version": "candidate_profile_v1",
            "first_name": "Alex",
            "last_name": "Chen",
            "email": "alex@example.com",
            "github_url": "https://github.com/alex",
        },
        application_flow_state=flow,
    )

    by_label = {item["label"]: item for item in plan["planned_answers"]}
    assert by_label["First name"]["category"] == "auto_safe_known"
    assert by_label["Last name"]["category"] == "auto_safe_known"
    assert by_label["Email address"]["category"] == "auto_safe_known"
    assert by_label["GitHub profile"]["category"] == "auto_safe_known"
    assert by_label["Email address"]["value_preview"] == "<redacted:email:len=16>"
    assert by_label["Email address"]["value_length"] == len("alex@example.com")
    assert len(by_label["Email address"]["value_hash"]) == 64
    assert by_label["First name"]["value_preview"] == "<redacted:name:len=4>"
    assert by_label["Phone"]["category"] == "needs_user_review"
    assert by_label["Expected salary"]["category"] == "blocked_sensitive"
    assert by_label["Available to start"]["category"] == "blocked_sensitive"
    assert by_label["Criminal conviction"]["category"] == "blocked_sensitive"
    assert by_label["Health declaration"]["category"] == "blocked_sensitive"
    assert by_label["Visa status details"]["category"] == "blocked_sensitive"


def test_answer_plan_output_does_not_echo_raw_email_or_phone() -> None:
    flow = {
        "contract_version": "seek_application_flow_state_v1",
        "final_submit_visible_blocker": {"blocked": False, "matched_items": []},
        "application_form_inventory": {
            "contract_version": "application_form_inventory_v1",
            "fields": [
                {"id": "email", "text": "Email address", "role": "email_input"},
                {"id": "phone", "text": "Phone", "role": "tel"},
            ],
            "actions": [],
        },
    }

    plan = build_application_answer_plan(
        profile={
            "contract_version": "candidate_profile_v1",
            "email": "alex@example.com",
            "phone": "+64 21 555 0123",
        },
        application_flow_state=flow,
    )

    payload_text = json.dumps(plan, ensure_ascii=False)
    assert "alex@example.com" not in payload_text
    assert "+64 21 555 0123" not in payload_text
    assert "<redacted:email:len=16>" in payload_text
    assert "<redacted:phone:len=15>" in payload_text


def test_answer_plan_does_not_autofill_buttons_or_dropdowns_with_profile_values() -> None:
    flow = {
        "contract_version": "seek_application_flow_state_v1",
        "final_submit_visible_blocker": {"blocked": False, "matched_items": []},
        "application_form_inventory": {
            "contract_version": "application_form_inventory_v1",
            "fields": [
                {"id": "email_dropdown", "text": "Email", "role": "select"},
                {"id": "phone_radio", "text": "Phone", "role": "radio"},
            ],
            "actions": [{"id": "email_button", "text": "Email", "role": "button"}],
        },
    }

    plan = build_application_answer_plan(
        profile={
            "contract_version": "candidate_profile_v1",
            "email": "alex@example.com",
            "phone": "0210000000",
        },
        application_flow_state=flow,
    )

    assert all(item["category"] == "needs_user_review" for item in plan["planned_answers"])
