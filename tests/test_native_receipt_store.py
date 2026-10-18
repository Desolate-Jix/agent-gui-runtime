from pathlib import Path

import pytest

from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError
from tests.test_runtime_receipt_store_w3b import (
    _backend, _blocked_verification, _next_observation, _semantic_success_receipt,
    _verification, _verification_failed_receipt,
)


def _native_next_and_verification():
    observation = _next_observation()
    application = observation.application.model_copy(update={
        "kind": "native", "identity_ref": "application:native:lonlife_acc.exe:lonlife",
        "display_name": "Lonlife",
    })
    observation = observation.model_copy(update={"application": application})
    verification = _verification(observation)
    state = verification["post_state_resolution"]
    state.update(canonical_origin="", observed_origin="")
    identity_ref = "native-identity:" + "a" * 64
    state["evidence_refs"] = sorted([*state["evidence_refs"], identity_ref])
    verification["evidence_refs"] = sorted([*verification["evidence_refs"], identity_ref])
    return observation, verification


def test_native_semantic_receipt_persists_and_reloads_with_identity_lineage(tmp_path: Path) -> None:
    observation, verification = _native_next_and_verification()
    receipt = _semantic_success_receipt(verification, observation)
    RuntimeReceiptStore(project_root=tmp_path).put(
        receipt, backend_receipt=_backend(), verification_evidence=verification,
        next_observation=observation,
    )
    reopened = RuntimeReceiptStore(project_root=tmp_path)
    assert reopened.resolve_next_observation(receipt.receipt_id) == observation


@pytest.mark.parametrize("mutation", ["missing_identity", "malformed_identity", "web_observation"])
def test_empty_origin_cannot_alone_establish_native_semantic_success(tmp_path: Path, mutation: str) -> None:
    observation, verification = _native_next_and_verification()
    if mutation == "web_observation":
        observation = _next_observation()
    else:
        refs = verification["post_state_resolution"]["evidence_refs"]
        refs[:] = [ref for ref in refs if not ref.startswith("native-identity:")]
        if mutation == "malformed_identity":
            refs.append("native-identity:invalid")
            refs.sort()
    receipt = _semantic_success_receipt(verification, observation)
    with pytest.raises(RuntimeReceiptStoreError):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt, backend_receipt=_backend(), verification_evidence=verification,
            next_observation=observation,
        )


@pytest.mark.parametrize("failure", ["post_action_failure", "destination_mismatch"])
def test_native_failure_receipt_is_retained_without_advancing_state(tmp_path: Path, failure: str) -> None:
    verification = _blocked_verification(failure)
    if failure == "destination_mismatch":
        _, success = _native_next_and_verification()
        verification["post_state_resolution"] = success["post_state_resolution"]
    else:
        verification["post_state_resolution"]["canonical_origin"] = ""
    receipt = _verification_failed_receipt(verification)
    RuntimeReceiptStore(project_root=tmp_path).put(
        receipt, backend_receipt=_backend(), verification_evidence=verification,
    )
    assert receipt.outcome == "VERIFICATION_FAILED"
    assert receipt.next_observation_id is None
    assert receipt.safe_stop.required is True
