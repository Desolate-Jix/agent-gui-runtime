from __future__ import annotations

import json

import pytest

from app.agent.form_answer_planner import build_form_answer_plan, plan_form_answer
from app.operation.form_inventory import build_form_question_inventory


def _question(label: str, *, question_id: str = "q1", field_type: str = "text", risk: str = "ordinary_field") -> dict:
    return {
        "contract_version": "form_question_contract_v1",
        "question_id": question_id,
        "label": label,
        "field_type": field_type,
        "required": True,
        "disabled": False,
        "risk": risk,
        "options": [],
        "source_capture_id": "capture-current",
    }


def _reviewed_evidence(field_key: str, value: str, *, evidence_id: str | None = None) -> dict:
    return {
        "contract_version": "form_answer_evidence_v1",
        "evidence_id": evidence_id or f"profile:{field_key}",
        "field_key": field_key,
        "source": "reviewed_candidate_profile",
        "reviewed": True,
        "value": value,
    }


@pytest.mark.parametrize(
    ("label", "field_type", "field_key"),
    [
        ("First name", "text", "first_name"),
        ("Last name", "text", "last_name"),
        ("Preferred name", "text", "preferred_name"),
        ("Email address", "email", "email"),
        ("Mobile phone", "phone", "phone"),
    ],
)
def test_reviewed_profile_fields_are_auto_fill_without_raw_pii(
    label: str,
    field_type: str,
    field_key: str,
) -> None:
    raw_value = {
        "first_name": "PrivateFirst",
        "last_name": "PrivateLast",
        "preferred_name": "PrivatePreferred",
        "email": "private@example.invalid",
        "phone": "+64 00 000 0000",
    }[field_key]

    decision = plan_form_answer(
        question=_question(label, field_type=field_type),
        evidence=[_reviewed_evidence(field_key, raw_value)],
    )

    assert decision["policy"] == "auto_fill"
    assert decision["proposed_value"] is None
    assert decision["value_reference"] == f"profile:{field_key}"
    assert decision["value_length"] == len(raw_value)
    assert decision["value_hash"]
    assert raw_value not in json.dumps(decision, ensure_ascii=False)


@pytest.mark.parametrize(
    "label",
    [
        "Salary expectation",
        "Are you willing to relocate?",
        "Describe your visa or sponsorship requirements",
    ],
)
def test_complex_or_negotiable_questions_require_user_review(label: str) -> None:
    decision = plan_form_answer(question=_question(label), evidence=[])

    assert decision["policy"] == "needs_user_review"
    assert decision["proposed_value"] is None


@pytest.mark.parametrize(
    "label",
    [
        "Ethnicity",
        "Gender identity",
        "Disability status",
        "Health or medical condition",
        "Criminal history",
    ],
)
def test_sensitive_questions_are_blocked(label: str) -> None:
    decision = plan_form_answer(question=_question(label), evidence=[])

    assert decision["policy"] == "blocked_sensitive"
    assert decision["proposed_value"] is None


def test_file_upload_is_unsupported() -> None:
    decision = plan_form_answer(
        question=_question("Upload your CV", field_type="file_upload", risk="unsupported_file_upload"),
        evidence=[],
    )

    assert decision["policy"] == "unsupported"


def test_human_reviewed_single_use_file_is_planned_without_leaking_path() -> None:
    raw_path = r"D:\private\reviewed-resume.pdf"
    decision = plan_form_answer(
        question=_question(
            "Upload your CV",
            question_id="resume_upload",
            field_type="file_upload",
            risk="unsupported_file_upload",
        ),
        evidence=[
            {
                "contract_version": "reviewed_file_evidence_v1",
                "evidence_id": "reviewed-file:resume:v1",
                "kind": "reviewed_file",
                "question_id": "resume_upload",
                "reviewed": True,
                "human_approved": True,
                "single_use": True,
                "absolute_path": raw_path,
            }
        ],
    )

    assert decision["policy"] == "reviewed_file_upload"
    assert decision["value_reference"] == "reviewed-file:resume:v1"
    assert decision["proposed_value"] is None
    assert raw_path not in json.dumps(decision, ensure_ascii=False)


def test_unapproved_or_wrong_question_file_stays_unsupported() -> None:
    question = _question(
        "Upload your CV",
        question_id="resume_upload",
        field_type="file_upload",
        risk="unsupported_file_upload",
    )
    base = {
        "contract_version": "reviewed_file_evidence_v1",
        "evidence_id": "reviewed-file:resume:v1",
        "kind": "reviewed_file",
        "reviewed": True,
        "human_approved": True,
        "single_use": True,
    }

    unapproved = plan_form_answer(
        question=question,
        evidence=[{**base, "human_approved": False, "question_id": "resume_upload"}],
    )
    mismatched = plan_form_answer(
        question=question,
        evidence=[{**base, "question_id": "different_upload"}],
    )

    assert unapproved["policy"] == "unsupported"
    assert mismatched["policy"] == "unsupported"


def test_final_action_is_never_an_answerable_field() -> None:
    decision = plan_form_answer(
        question=_question("Submit application", field_type="action", risk="final_submit"),
        evidence=[],
    )

    assert decision["policy"] == "final_submit"
    assert decision["proposed_value"] is None


def test_unknown_question_never_gets_default_answer() -> None:
    decision = plan_form_answer(question=_question("Tell us something else"), evidence=[])

    assert decision["policy"] == "needs_user_review"
    assert decision["question_understanding"]["intent"] == "unknown_open_text"
    assert decision["question_understanding"]["recommended_policy"] == "needs_user_review"
    assert decision["proposed_value"] is None
    assert decision["value_reference"] is None


@pytest.mark.parametrize(
    ("label", "polarity"),
    [
        ("Do you have the right to work in New Zealand?", "affirmative_means_intent_true"),
        ("Do you require sponsorship to work in New Zealand?", "affirmative_means_intent_false"),
    ],
)
def test_answer_plan_exposes_work_authorization_polarity_without_guessing(
    label: str,
    polarity: str,
) -> None:
    decision = plan_form_answer(question=_question(label, field_type="radio"), evidence=[])

    assert decision["policy"] == "needs_user_review"
    assert decision["question_understanding"]["intent"] == "authorized_to_work_without_sponsorship"
    assert decision["question_understanding"]["polarity"] == polarity
    assert decision["proposed_value"] is None
    assert decision["value_reference"] is None


def test_exact_reviewed_derived_answer_requires_question_linkage() -> None:
    decision = plan_form_answer(
        question=_question("Why are you interested in this role?", question_id="motivation"),
        evidence=[
            {
                "contract_version": "form_answer_evidence_v1",
                "evidence_id": "derived:motivation:v1",
                "question_id": "motivation",
                "kind": "derived_answer",
                "source": "reviewed_answer_draft",
                "reviewed": True,
                "value": "A private reviewed response",
            }
        ],
    )

    assert decision["policy"] == "derived_with_evidence"
    assert decision["value_reference"] == "derived:motivation:v1"
    assert "A private reviewed response" not in json.dumps(decision, ensure_ascii=False)


def test_plan_report_redacts_all_pii_and_keeps_policy_counts(capsys: pytest.CaptureFixture[str]) -> None:
    raw_name = "PrivateFirst"
    raw_email = "private@example.invalid"
    report = build_form_answer_plan(
        inventory={
            "contract_version": "form_question_inventory_v1",
            "capture_id": "capture-current",
            "questions": [
                _question("First name", question_id="first_name"),
                _question("Email address", question_id="email", field_type="email"),
                _question("Ethnicity", question_id="ethnicity"),
            ],
        },
        evidence=[
            _reviewed_evidence("first_name", raw_name),
            _reviewed_evidence("email", raw_email),
        ],
    )

    serialized = json.dumps(report, ensure_ascii=False)
    audit_payload = json.dumps(
        {
            "report": report,
            "trace": {"decision": report},
            "expected": report,
            "actual": report,
        },
        ensure_ascii=False,
    )
    print(audit_payload)
    stdout = capsys.readouterr().out
    assert report["contract_version"] == "form_answer_plan_v1"
    assert report["policy_counts"] == {"auto_fill": 2, "blocked_sensitive": 1}
    assert report["pii_redacted"] is True
    assert report["fill_attempted"] is False
    assert report["submit_attempted"] is False
    assert raw_name not in serialized
    assert raw_email not in serialized
    assert raw_name not in audit_payload
    assert raw_email not in audit_payload
    assert raw_name not in stdout
    assert raw_email not in stdout


def test_plan_consumes_fields_questions_and_final_actions_from_common_inventory() -> None:
    inventory = build_form_question_inventory(
        form_state="questionnaire",
        current_capture_id="capture-current",
        active_scope_bbox={"x": 0, "y": 0, "w": 800, "h": 800},
        fields=[
            {
                "id": "first_name",
                "label": "First name",
                "role": "textbox",
                "bbox": {"x": 20, "y": 20, "w": 200, "h": 30},
                "capture_id": "capture-current",
            },
            {
                "id": "cv",
                "label": "Upload your CV",
                "input_type": "file",
                "bbox": {"x": 20, "y": 70, "w": 200, "h": 30},
                "capture_id": "capture-current",
            },
        ],
        questions=[
            {
                "question_id": "work_rights",
                "question_text": "Describe your visa or sponsorship requirements",
                "answer_type": "textarea",
                "question_group_bbox": {"x": 20, "y": 120, "w": 400, "h": 100},
                "capture_id": "capture-current",
            }
        ],
        actions=[
            {
                "id": "submit",
                "text": "Submit application",
                "role": "button",
                "bbox": {"x": 20, "y": 250, "w": 180, "h": 40},
                "capture_id": "capture-current",
            }
        ],
    )

    report = build_form_answer_plan(
        inventory=inventory,
        evidence=[_reviewed_evidence("first_name", "PrivateFirst")],
    )

    assert len(report["decisions"]) == 4
    assert report["policy_counts"] == {
        "auto_fill": 1,
        "unsupported": 1,
        "needs_user_review": 1,
        "final_submit": 1,
    }
