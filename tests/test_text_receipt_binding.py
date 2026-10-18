from __future__ import annotations

from copy import deepcopy
import json

import pytest

from app.agent.runtime_contracts import RuntimeResultReceiptV1
from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError
from app.agent.text_field_evidence import (
    TextFieldIdentity,
    TextFieldSnapshot,
    prepare_text_field_expectation,
    verify_text_field_result_reference,
)
from app.agent.text_parameters import (
    ReviewedTextParameters,
    ReviewedTextSource,
    ResolvedTextParameters,
    text_parameter_reference,
)
from tests.test_runtime_receipt_store_w3b import (
    _backend,
    _blocked_verification,
    _next_observation,
    _semantic_success_receipt,
    _verification,
    _verification_failed_receipt,
)


def _parameters() -> ResolvedTextParameters:
    reviewed = ReviewedTextParameters(
        target_field_id="field-1",
        content=ReviewedTextSource("literal", "secret-new"),
        clear_existing=False,
        sensitive=False,
    )
    return ResolvedTextParameters(reviewed=reviewed, text="secret-new")


def _expected_and_proof(*, actual_value: str) -> tuple[dict, dict]:
    identity = TextFieldIdentity(
        target_field_id="field-1",
        window_handle=4242,
        process_id=9001,
        process_create_time=1.0,
        runtime_id=(1,),
        window_rect=(0, 0, 320, 200),
        control_bbox=(40, 50, 120, 40),
    )
    before = TextFieldSnapshot(
        identity=identity,
        capture_id="capture-before",
        read_id="read-before",
        observed_at_ns=10,
        source="uia_value",
        value="secret-old",
        selection=(10, 10),
    )
    expectation = prepare_text_field_expectation(before, _parameters())
    actual = TextFieldSnapshot(
        identity=identity,
        capture_id="capture-after",
        read_id="read-after",
        observed_at_ns=11,
        source="uia_value",
        value=actual_value,
        selection=(len(actual_value), len(actual_value)),
    )
    declaration = text_parameter_reference(_parameters().reviewed)
    return expectation.to_reference(), verify_text_field_result_reference(
        expectation.to_reference(), actual, declaration_reference=declaration
    )


def _fill_receipt(verification: dict, next_observation) -> RuntimeResultReceiptV1:
    payload = _semantic_success_receipt(verification, next_observation).model_dump(mode="json")
    payload["action"] = {
        "action_id": "transition.open-detail",
        "semantic_action": "fill_field",
        "text_parameters_ref": text_parameter_reference(_parameters().reviewed),
    }
    return RuntimeResultReceiptV1.model_validate(payload)


def _failed_fill_receipt(verification: dict) -> RuntimeResultReceiptV1:
    payload = _verification_failed_receipt(verification).model_dump(mode="json")
    payload["action"] = {
        "action_id": "transition.open-detail",
        "semantic_action": "fill_field",
        "text_parameters_ref": text_parameter_reference(_parameters().reviewed),
    }
    return RuntimeResultReceiptV1.model_validate(payload)


def test_fill_receipt_persists_and_reloads_reference_only_text_verification(tmp_path) -> None:
    expected, proof = _expected_and_proof(actual_value="secret-oldsecret-new")
    next_observation = _next_observation()
    verification = _verification(next_observation)
    verification["text_field_verification"] = proof
    receipt = _fill_receipt(verification, next_observation)
    store = RuntimeReceiptStore(project_root=tmp_path)

    reference = store.put(
        receipt,
        backend_receipt=_backend(),
        verification_evidence=verification,
        next_observation=next_observation,
    )
    reloaded = RuntimeReceiptStore(project_root=tmp_path).get(reference)

    assert reloaded.verification_evidence == verification
    assert reloaded.verification_evidence["text_field_verification"]["expected"] == expected
    serialized = "".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "secret-old" not in serialized
    assert "secret-new" not in serialized


@pytest.mark.parametrize("mutation", ["identity", "value_hash", "status"])
def test_fill_receipt_rejects_tampered_text_verification(mutation: str, tmp_path) -> None:
    _, proof = _expected_and_proof(actual_value="secret-oldsecret-new")
    next_observation = _next_observation()
    verification = _verification(next_observation)
    proof = deepcopy(proof)
    if mutation == "identity":
        proof["actual"]["identity"]["target_field_id"] = "other-field"
    elif mutation == "value_hash":
        proof["actual"]["value_sha256"] = "f" * 64
    else:
        proof["status"] = "not_verified"
    verification["text_field_verification"] = proof

    with pytest.raises(RuntimeReceiptStoreError, match="text field"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            _fill_receipt(verification, next_observation),
            backend_receipt=_backend(),
            verification_evidence=verification,
            next_observation=next_observation,
        )


def test_fill_verification_failure_requires_matching_text_reason(tmp_path) -> None:
    _, proof = _expected_and_proof(actual_value="different")
    assert proof["status"] == "not_verified"
    verification = _blocked_verification(proof["reason_code"])
    verification["semantic_verification"] = _verification(_next_observation())
    verification["text_field_verification"] = proof
    receipt = _failed_fill_receipt(verification)

    reference = RuntimeReceiptStore(project_root=tmp_path).put(
        receipt,
        backend_receipt=_backend(),
        verification_evidence=verification,
    )
    assert RuntimeReceiptStore(project_root=tmp_path).get(reference).verification_evidence == verification

    changed = deepcopy(verification)
    changed["failure_code"] = "text_field_read_not_new"
    with pytest.raises(RuntimeReceiptStoreError, match="reason"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            _failed_fill_receipt(changed),
            backend_receipt=_backend(),
            verification_evidence=changed,
        )
