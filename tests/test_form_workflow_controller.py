from __future__ import annotations

import pytest

from app.agent.continuous_task_session import (
    bind_form_step_context,
    create_continuous_task_session,
    observe_interface,
    record_action_result,
    record_form_workflow_turn,
)
from app.agent.form_workflow_controller import plan_form_workflow_turn


def _evidence(capture_id: str) -> dict[str, str]:
    return {
        "capture_id": capture_id,
        "screenshot_sha256": f"sha256:{capture_id}",
        "trace_path": f"logs/{capture_id}.json",
    }


def _question(
    question_id: str,
    *,
    field_type: str = "text",
    label: str | None = None,
) -> dict:
    return {
        "field_id": question_id,
        "question_id": question_id,
        "label": label or question_id.replace("_", " ").title(),
        "field_type": field_type,
        "required": True,
        "disabled": False,
        "capture_id": "capture-page-1",
    }


def _decision(
    question_id: str,
    *,
    field_type: str = "text",
    policy: str = "auto_fill",
) -> dict:
    return {
        "contract_version": "form_answer_decision_v1",
        "question_id": question_id,
        "field_type": field_type,
        "policy": policy,
        "reason": "reviewed evidence",
        "value_reference": (
            f"reviewed:{question_id}"
            if policy in {"auto_fill", "reviewed_file_upload"}
            else None
        ),
        "value_hash": "sha256:redacted" if policy == "auto_fill" else None,
        "value_length": 8 if policy == "auto_fill" else 0,
        "pii_redacted": True,
        "artifact_is_authorization": False,
    }


def _inventory(
    *,
    capture_id: str = "capture-page-1",
    questions: list[dict] | None = None,
    continue_visible: bool = True,
    danger_visible: bool = False,
    danger_text: str = "Submit application",
) -> dict:
    action = {
        "action_id": "continue",
        "text": "Continue",
        "action_type": "continue_action",
        "risk_class": "low_risk_navigation",
        "capture_id": capture_id,
    }
    return {
        "contract_version": "form_question_inventory_v1",
        "form_state": "application_form_step",
        "capture_id": capture_id,
        "questions": questions or [],
        "fields": questions or [],
        "continue_action": action if continue_visible else None,
        "danger_actions": (
            [
                {
                    "action_id": "submit",
                    "text": danger_text,
                    "action_type": "final_action",
                    "risk_class": "final_submit",
                    "capture_id": capture_id,
                }
            ]
            if danger_visible
            else []
        ),
        "artifact_is_authorization": False,
    }


def _answer_plan(*, capture_id: str, decisions: list[dict]) -> dict:
    return {
        "contract_version": "form_answer_plan_v1",
        "capture_id": capture_id,
        "decisions": decisions,
        "pii_redacted": True,
        "fill_attempted": False,
        "submit_attempted": False,
        "artifact_is_authorization": False,
    }


def test_two_page_form_produces_exactly_one_action_and_invalidates_after_continue() -> None:
    page_one_questions = [
        _question("first_name"),
        _question("country", field_type="select"),
    ]
    inventory = _inventory(questions=page_one_questions)
    answer_plan = _answer_plan(
        capture_id="capture-page-1",
        decisions=[
            _decision("first_name"),
            _decision("country", field_type="select"),
        ],
    )

    first_turn = plan_form_workflow_turn(
        interface_id="application:page-1",
        surface_status="ready",
        observation_evidence=_evidence("capture-page-1"),
        inventory=inventory,
        answer_plan=answer_plan,
        completed_question_ids=[],
    )
    second_turn = plan_form_workflow_turn(
        interface_id="application:page-1",
        surface_status="ready",
        observation_evidence=_evidence("capture-page-1"),
        inventory=inventory,
        answer_plan=answer_plan,
        completed_question_ids=["first_name"],
    )
    continue_turn = plan_form_workflow_turn(
        interface_id="application:page-1",
        surface_status="ready",
        observation_evidence=_evidence("capture-page-1"),
        inventory=inventory,
        answer_plan=answer_plan,
        completed_question_ids=["first_name", "country"],
    )

    assert first_turn["action_type"] == "fill_field"
    assert first_turn["question_id"] == "first_name"
    assert second_turn["action_type"] == "select_option"
    assert second_turn["question_id"] == "country"
    assert continue_turn["action_type"] == "continue_next_step"
    assert continue_turn["operation_count"] == 1
    assert continue_turn["invalidates_after_success"] == [
        "capture",
        "form_inventory",
        "grounding",
    ]
    assert continue_turn["artifact_is_authorization"] is False

    session = create_continuous_task_session(
        session_id="multi-page-form",
        workflow_id="generic-application",
    )
    session = observe_interface(
        session,
        interface_id="application:page-1",
        surface_type="application_form_step",
        memory_object_sha256="reviewed-form-memory",
        evidence=_evidence("capture-page-1"),
    )
    session = bind_form_step_context(
        session,
        capture_id="capture-page-1",
        inventory_fingerprint="inventory-page-1",
        grounding_fingerprint="grounding-page-1",
    )
    session = record_form_workflow_turn(session, decision=continue_turn)
    session = record_action_result(
        session,
        action_type="continue_next_step",
        action_executed=True,
        post_action_verified=True,
        evidence=_evidence("capture-page-1-transition"),
    )

    assert session["status"] == "waiting_for_destination_observation"
    assert session["current_observation_evidence"] is None
    assert session["current_form_step_context"] == {
        "capture_id": None,
        "inventory_fingerprint": None,
        "grounding_fingerprint": None,
        "valid": False,
        "invalidated_by": "continue_next_step",
    }
    with pytest.raises(ValueError, match="not ready for a form workflow turn"):
        record_form_workflow_turn(session, decision=continue_turn)

    session = observe_interface(
        session,
        interface_id="application:page-2",
        surface_type="application_form_step",
        memory_object_sha256="reviewed-form-memory-page-2",
        evidence=_evidence("capture-page-2"),
    )
    session = bind_form_step_context(
        session,
        capture_id="capture-page-2",
        inventory_fingerprint="inventory-page-2",
        grounding_fingerprint="grounding-page-2",
    )

    assert session["status"] == "ready_for_agent_decision"
    assert session["current_form_step_context"]["capture_id"] == "capture-page-2"
    assert session["current_form_step_context"]["valid"] is True


def test_unknown_or_sensitive_question_pauses_before_later_fields() -> None:
    inventory = _inventory(
        questions=[
            _question("visa_status", field_type="radio"),
            _question("email", field_type="email"),
        ]
    )
    turn = plan_form_workflow_turn(
        interface_id="application:questions",
        surface_status="ready",
        observation_evidence=_evidence("capture-page-1"),
        inventory=inventory,
        answer_plan=_answer_plan(
            capture_id="capture-page-1",
            decisions=[
                _decision("visa_status", field_type="radio", policy="needs_user_review"),
                _decision("email", field_type="email"),
            ],
        ),
        completed_question_ids=[],
    )

    assert turn["action_type"] == "request_user_review"
    assert turn["question_id"] == "visa_status"
    assert turn["operation"] is None
    assert turn["operation_count"] == 0


def test_reviewed_file_upload_becomes_one_gated_operation() -> None:
    upload = _question("resume_upload", field_type="file_upload")
    turn = plan_form_workflow_turn(
        interface_id="application:questions",
        surface_status="ready",
        observation_evidence=_evidence("capture-page-1"),
        inventory=_inventory(questions=[upload], continue_visible=False),
        answer_plan=_answer_plan(
            capture_id="capture-page-1",
            decisions=[
                _decision(
                    "resume_upload",
                    field_type="file_upload",
                    policy="reviewed_file_upload",
                )
            ],
        ),
        completed_question_ids=[],
    )

    assert turn["action_type"] == "upload_file"
    assert turn["question_id"] == "resume_upload"
    assert turn["operation_count"] == 1
    assert turn["requires_gate"] is True
    assert turn["operation"]["value_reference"] == "reviewed:resume_upload"
    assert turn["invalidates_after_success"] == ["capture", "grounding"]

    session = create_continuous_task_session(
        session_id="reviewed-file-upload",
        workflow_id="generic-application",
    )
    session = observe_interface(
        session,
        interface_id="application:questions",
        surface_type="application_form_step",
        memory_object_sha256="reviewed-form-memory",
        evidence=_evidence("capture-page-1"),
    )
    session = bind_form_step_context(
        session,
        capture_id="capture-page-1",
        inventory_fingerprint="inventory-page-1",
        grounding_fingerprint="grounding-page-1",
    )
    session = record_form_workflow_turn(session, decision=turn)
    session = record_action_result(
        session,
        action_type="upload_file",
        action_executed=True,
        post_action_verified=True,
        evidence=_evidence("capture-uploaded"),
    )

    assert session["status"] == "waiting_for_destination_observation"
    assert session["current_form_step_context"]["valid"] is False
    assert session["current_form_step_context"]["invalidated_by"] == "upload_file"


def test_login_blocker_wrong_surface_and_verification_failure_safe_stop() -> None:
    inventory = _inventory(questions=[_question("first_name")])
    answer_plan = _answer_plan(
        capture_id="capture-page-1",
        decisions=[_decision("first_name")],
    )

    login = plan_form_workflow_turn(
        interface_id="application:login",
        surface_status="login_required",
        observation_evidence=_evidence("capture-page-1"),
        inventory=inventory,
        answer_plan=answer_plan,
        completed_question_ids=[],
    )
    wrong_surface = plan_form_workflow_turn(
        interface_id="browser:search",
        surface_status="wrong_surface",
        observation_evidence=_evidence("capture-page-1"),
        inventory=inventory,
        answer_plan=answer_plan,
        completed_question_ids=[],
    )
    verification_failed = plan_form_workflow_turn(
        interface_id="application:page-1",
        surface_status="ready",
        observation_evidence=_evidence("capture-page-1"),
        inventory=inventory,
        answer_plan=answer_plan,
        completed_question_ids=[],
        previous_verification={"verified": False, "status": "verification_failed"},
    )

    assert login["action_type"] == "safe_stop"
    assert login["reason"] == "login_required"
    assert wrong_surface["action_type"] == "safe_stop"
    assert wrong_surface["reason"] == "wrong_surface"
    assert verification_failed["action_type"] == "safe_stop"
    assert verification_failed["reason"] == "previous_action_verification_failed"
    assert login["operation_count"] == 0
    assert wrong_surface["operation_count"] == 0
    assert verification_failed["operation_count"] == 0


@pytest.mark.parametrize(
    "danger_text",
    ["Review and submit", "Submit application", "Send", "Complete"],
)
def test_final_submit_visible_safe_stops_and_never_becomes_continue(
    danger_text: str,
) -> None:
    dispatch_counts = {"real_clicks": 0, "submit_clicks": 0}
    turn = plan_form_workflow_turn(
        interface_id="application:review",
        surface_status="ready",
        observation_evidence=_evidence("capture-page-1"),
        inventory=_inventory(
            questions=[],
            danger_visible=True,
            danger_text=danger_text,
        ),
        answer_plan=_answer_plan(capture_id="capture-page-1", decisions=[]),
        completed_question_ids=[],
    )

    assert turn["action_type"] == "safe_stop"
    assert turn["reason"] == "final_submit_visible"
    assert turn["operation"] is None
    assert turn["unsafe_prevented"] is True
    assert dispatch_counts == {"real_clicks": 0, "submit_clicks": 0}


def test_stale_inventory_or_answer_plan_is_rejected_without_operation() -> None:
    turn = plan_form_workflow_turn(
        interface_id="application:page-1",
        surface_status="ready",
        observation_evidence=_evidence("capture-page-1"),
        inventory=_inventory(capture_id="capture-stale", questions=[]),
        answer_plan=_answer_plan(capture_id="capture-stale", decisions=[]),
        completed_question_ids=[],
    )

    assert turn["action_type"] == "safe_stop"
    assert turn["reason"] == "stale_form_step_evidence"
    assert turn["operation_count"] == 0
