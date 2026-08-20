from __future__ import annotations

from app.agent.form_answer_planner import plan_form_answer
from app.gate.form_policy import evaluate_form_action_policy


def _question(label: str, *, field_type: str = "text", risk: str = "ordinary_field", disabled: bool = False) -> dict:
    return {
        "contract_version": "form_question_contract_v1",
        "question_id": "q1",
        "label": label,
        "field_type": field_type,
        "required": True,
        "disabled": disabled,
        "risk": risk,
        "options": [],
        "source_capture_id": "capture-current",
    }


def _evidence(value: str = "PrivateFirst") -> list[dict]:
    return [
        {
            "contract_version": "form_answer_evidence_v1",
            "evidence_id": "profile:first_name",
            "field_key": "first_name",
            "source": "reviewed_candidate_profile",
            "reviewed": True,
            "value": value,
        }
    ]


def test_auto_fill_policy_passes_policy_gate_but_does_not_authorize_execution() -> None:
    question = _question("First name")
    decision = plan_form_answer(question=question, evidence=_evidence())

    gate = evaluate_form_action_policy(question=question, decision=decision)

    assert gate["contract_version"] == "form_action_gate_decision_v1"
    assert gate["policy_allowed"] is True
    assert gate["execution_authorized"] is False
    assert gate["requires_current_grounding"] is True
    assert gate["requires_action_gate"] is True
    assert gate["fill_attempted"] is False
    assert gate["submit_attempted"] is False


def test_missing_evidence_blocks_nominal_auto_fill_decision() -> None:
    question = _question("First name")
    decision = {
        "contract_version": "form_answer_decision_v1",
        "question_id": "q1",
        "policy": "auto_fill",
        "evidence_refs": [],
        "value_reference": None,
        "value_hash": None,
        "value_length": 0,
    }

    gate = evaluate_form_action_policy(question=question, decision=decision)

    assert gate["policy_allowed"] is False
    assert gate["reason"] == "answer_evidence_missing"


def test_disabled_field_is_not_allowed() -> None:
    question = _question("First name", disabled=True)
    decision = plan_form_answer(question=question, evidence=_evidence())

    gate = evaluate_form_action_policy(question=question, decision=decision)

    assert gate["policy_allowed"] is False
    assert gate["reason"] == "field_disabled"


def test_sensitive_and_final_actions_are_safe_stops() -> None:
    sensitive_question = _question("Disability status")
    sensitive = evaluate_form_action_policy(
        question=sensitive_question,
        decision=plan_form_answer(question=sensitive_question, evidence=[]),
    )
    final_question = _question("Submit application", field_type="action", risk="final_submit")
    final = evaluate_form_action_policy(
        question=final_question,
        decision=plan_form_answer(question=final_question, evidence=[]),
    )

    assert sensitive["policy_allowed"] is False
    assert sensitive["unsafe_prevented"] is True
    assert final["policy_allowed"] is False
    assert final["unsafe_prevented"] is True
    assert final["submit_attempted"] is False
