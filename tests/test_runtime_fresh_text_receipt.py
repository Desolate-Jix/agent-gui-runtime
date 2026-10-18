from copy import deepcopy
from hashlib import sha256

import pytest

from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt, RuntimeFreshReceiptError
from app.agent.text_field_evidence import (
    TextFieldIdentity, TextFieldSnapshot, prepare_text_field_expectation,
    verify_text_field_result_reference,
)
from app.agent.text_parameters import ReviewedTextParameters, resolve_text_parameters, text_parameter_reference


def _text_parts(*, variable=False):
    reviewed = ReviewedTextParameters.from_payload({
        "contract_version": "reviewed_text_parameters_v1", "target_field_id": "query",
        "content": ({"kind": "variable", "name": "value"} if variable else {"kind": "literal", "text": "new"}), "clear_existing": True,
        "sensitive": False, "submit": False, "clipboard_policy": "restore_previous",
    })
    resolved = resolve_text_parameters(reviewed, {"value": "new"})
    identity = TextFieldIdentity("query", 42, 7, 1.0, (1, 2), (0, 0, 20, 20), (2, 3, 10, 10))
    before = TextFieldSnapshot(identity, "capture", "read-before", 1, "uia_value", "old", (0, 0))
    expectation = prepare_text_field_expectation(before, resolved)
    actual = TextFieldSnapshot(identity, "after-capture", "read-after", 2, "uia_value", "new", (0, 0))
    verification = verify_text_field_result_reference(expectation.to_reference(), actual, declaration_reference=text_parameter_reference(reviewed))
    return text_parameter_reference(reviewed), verification


def _receipt(*, semantic="fill_field", effect="verified", outcome="ACTION_RECORDED", verification=None):
    declaration, valid_verification = _text_parts()
    evidence = {
        "source_sha256": "a" * 64, "approved_preview_sha256": "b" * 64,
        "fresh_preview_sha256": "c" * 64, "consume_content_sha256": "d" * 64,
        "confirmation_id": "confirmation", "capture_id": "capture",
        "candidate_ref": "candidate", "gate_decision_ref": "gate",
    }
    if semantic == "fill_field":
        evidence.update(text_parameters_ref=declaration, text_field_verification=verification or valid_verification)
    return {
        "contract_version": "runtime_fresh_result_receipt_v1", "receipt_id": "receipt",
        "issued_at": "2026-09-12T00:00:00Z", "session_id": "session",
        "observation_id": "observation", "intent_id": "intent", "source_sha256": "a" * 64,
        "action": {"action_id": "action", "semantic_action": semantic}, "outcome": outcome,
        "reason_code": "backend_dispatched" if outcome == "ACTION_RECORDED" else "backend_not_started",
        "attempt_count": 1, "gate_status": "allowed", "dispatch_status": "dispatched" if outcome == "ACTION_RECORDED" else "not_started",
        "effect_status": effect, "destination_status": "not_evaluated", "evidence": evidence,
        "next_observation_id": "next-observation" if outcome == "ACTION_RECORDED" else None,
        "artifact_is_authorization": False,
    }


def test_fill_receipt_roundtrips_private_text_evidence_without_exposing_mutable_state():
    checked = RuntimeFreshResultReceipt.from_dict(_receipt())
    dumped = checked.model_dump(mode="json")
    assert dumped["evidence"]["text_parameters_ref"]["target_field_id"] == "query"
    assert dumped["evidence"]["text_field_verification"]["status"] == "verified"
    dumped["evidence"]["text_parameters_ref"]["target_field_id"] = "changed"
    assert checked.evidence.text_parameters_ref["target_field_id"] == "query"


def test_fill_receipt_accepts_variable_text_declaration():
    declaration, verification = _text_parts(variable=True)
    value = _receipt()
    value["evidence"]["text_parameters_ref"] = declaration
    value["evidence"]["text_field_verification"] = verification
    checked = RuntimeFreshResultReceipt.from_dict(value)
    assert checked.evidence.text_parameters_ref["source_kind"] == "variable"
    assert checked.evidence.text_parameters_ref["variable_name"] == "value"


@pytest.mark.parametrize("mutate", [
    lambda value: value["action"].update(semantic_action="open_detail"),
    lambda value: value["evidence"].pop("text_parameters_ref"),
    lambda value: value["evidence"].pop("text_field_verification"),
    lambda value: value["evidence"]["text_field_verification"]["expected"]["before"].update(capture_id="other"),
    lambda value: value.update(effect_status="not_verified"),
])
def test_fill_receipt_rejects_invalid_text_evidence(mutate):
    value = deepcopy(_receipt())
    mutate(value)
    with pytest.raises(RuntimeFreshReceiptError):
        RuntimeFreshResultReceipt.from_dict(value)


def test_navigation_receipt_rejects_text_extensions():
    value = _receipt(semantic="open_detail")
    value["evidence"]["text_parameters_ref"] = {}
    with pytest.raises(RuntimeFreshReceiptError):
        RuntimeFreshResultReceipt.from_dict(value)


def test_non_recorded_fill_receipt_requires_no_actual_verification():
    value = _receipt(outcome="EXECUTION_FAILED", effect="not_verified")
    with pytest.raises(RuntimeFreshReceiptError):
        RuntimeFreshResultReceipt.from_dict(value)
