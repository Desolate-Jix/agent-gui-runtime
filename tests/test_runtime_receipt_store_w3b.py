from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from threading import Barrier, Thread

import pytest

from app.agent.desktop_backend import BackendDispatchReceipt
from app.agent.runtime_contracts import AgentObservationV1, RuntimeResultReceiptV1


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _workflow() -> dict[str, object]:
    return {
        "workflow_id": "workflow.seek.portfolio",
        "asset_id": "asset.seek.portfolio",
        "asset_content_sha256": SHA_A,
        "source_workflow_sha256": SHA_B,
        "reviewed_revision_hash": SHA_C,
    }


def _receipt_payload(outcome: str = "DISPATCHED") -> dict[str, object]:
    payload: dict[str, object] = {
        "contract_version": "runtime_result_receipt_v1",
        "receipt_id": "receipt:runtime:1",
        "issued_at": "2026-08-22T01:02:03Z",
        "session_id": "session-1",
        "observation_id": "observation-1",
        "intent_id": "intent.open-detail",
        "workflow": _workflow(),
        "action": {
            "action_id": "transition.open-detail",
            "semantic_action": "open_detail",
        },
        "outcome": "DISPATCHED",
        "reason_code": "verification_pending",
        "attempt_count": 1,
        "gate_status": "allowed",
        "dispatch_status": "dispatched",
        "effect_status": "not_evaluated",
        "destination_status": "not_evaluated",
        "evidence": {
            "state_resolution_ref": "state-resolution:1",
            "selection_ref": "selection:1",
            "candidate_ref": "candidate:1",
            "gate_decision_ref": "gate:1",
            "backend_receipt_ref": "backend-receipt:1",
            "verification_ref": None,
            "trace_refs": ["trace:1"],
        },
        "next_observation_id": None,
        "safe_stop": {
            "required": True,
            "reason_code": "verification_pending",
        },
        "artifact_is_authorization": False,
    }
    if outcome == "BLOCKED":
        payload.update(
            outcome="BLOCKED",
            reason_code="pre_click_rejected",
            attempt_count=0,
            gate_status="blocked",
            dispatch_status="not_started",
        )
        payload["evidence"]["backend_receipt_ref"] = None
        payload["safe_stop"] = {
            "required": True,
            "reason_code": "pre_click_rejected",
        }
    elif outcome == "EXECUTION_FAILED":
        payload.update(
            outcome="EXECUTION_FAILED",
            reason_code="backend_failed",
            dispatch_status="not_started",
        )
        payload["safe_stop"] = {
            "required": True,
            "reason_code": "backend_failed",
        }
    elif outcome == "INDETERMINATE":
        payload.update(
            outcome="INDETERMINATE",
            reason_code="backend_result_lost",
            dispatch_status="indeterminate",
            effect_status="indeterminate",
            destination_status="indeterminate",
        )
        payload["safe_stop"] = {
            "required": True,
            "reason_code": "backend_result_lost",
        }
    return payload


def _receipt(outcome: str = "DISPATCHED") -> RuntimeResultReceiptV1:
    return RuntimeResultReceiptV1.model_validate(_receipt_payload(outcome))


def _backend(
    status: str = "dispatched",
    reason_code: str = "none",
) -> BackendDispatchReceipt:
    return BackendDispatchReceipt(
        receipt_ref="backend-receipt:1",
        status=status,
        reason_code=reason_code,
    )


def _next_observation(*, stop_boundary: bool = False) -> AgentObservationV1:
    state_id = "state-stop" if stop_boundary else "state-detail"
    capture_id = "capture-next"
    capture_ref = "capture:next"
    state_ref = "state-resolution:next"
    fact_ref = "fact:next"
    safe_action = {
        "action_id": "runtime.safe_stop",
        "semantic_action": "safe_stop",
        "description": "Stop without dispatching another action.",
        "target_state_id": None,
        "expected_effect": "Stop without dispatching another action.",
        "verification_rule_refs": [],
        "risk_level": "low",
        "requires_user_confirmation": False,
    }
    actions = [safe_action]
    blockers: list[dict[str, object]] = []
    if stop_boundary:
        blockers = [
            {
                "blocker_id": "stop-boundary",
                "blocker_type": "state",
                "description": "The reviewed workflow reached its stop boundary.",
                "safe_stop_required": True,
                "evidence_refs": [state_ref],
            }
        ]
    else:
        actions.insert(
            0,
            {
                "action_id": "transition.close-detail",
                "semantic_action": "close_modal",
                "description": "Close the current detail view.",
                "target_state_id": "state-list",
                "expected_effect": "Return to the reviewed results state.",
                "verification_rule_refs": ["rule:close-detail"],
                "risk_level": "low",
                "requires_user_confirmation": False,
            },
        )
    return AgentObservationV1.model_validate(
        {
            "contract_version": "agent_observation_v1",
            "observation_id": "observation-next",
            "session_id": "session-1",
            "workflow": _workflow(),
            "application": {
                "identity_ref": "application:web:nz.seek.com",
                "kind": "web",
                "display_name": "nz.seek.com",
            },
            "state_resolution_ref": state_ref,
            "current_capture": {
                "capture_id": capture_id,
                "screenshot_sha256": SHA_C,
                "evidence_ref": capture_ref,
            },
            "state": {
                "status": "stop_boundary" if stop_boundary else "matched",
                "state_id": state_id,
                "state_availability": "stop_boundary" if stop_boundary else "reviewed",
                "resolution_sha256": SHA_B,
                "source_interface_id": "interface.detail",
                "display_name": "Reviewed detail state",
                "surface_type": "detail",
                "responsibility": "Expose the recomputed post-transition state.",
            },
            "semantic_facts": [
                {
                    "fact_id": "fact-next",
                    "fact_type": "identity_anchor",
                    "label": "Current reviewed state identity",
                    "value": state_id,
                    "observation_status": "current",
                    "capture_id": capture_id,
                    "value_sha256": None,
                    "evidence_refs": [fact_ref],
                }
            ],
            "evidence_refs": [state_ref, capture_ref, fact_ref],
            "blockers": blockers,
            "available_actions": actions,
            "safe_stop": {
                "required": stop_boundary,
                "reason_code": "stop_boundary" if stop_boundary else "none",
            },
            "artifact_is_authorization": False,
        }
    )


def _verification(next_observation: AgentObservationV1) -> dict[str, object]:
    return {
        "contract_version": "transition_verification_v1",
        "status": "verified",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "state_advanced": True,
        "asset_content_sha256": SHA_A,
        "selection_sha256": "d" * 64,
        "transition_id": "transition.open-detail",
        "source_state_id": "state-list",
        "target_state_id": next_observation.state.state_id,
        "post_capture_lineage": {
            "capture_id": next_observation.current_capture.capture_id,
            "screenshot_sha256": next_observation.current_capture.screenshot_sha256,
            "viewport_size": {"width": 1280, "height": 720},
        },
        "post_state_resolution": {
            "contract_version": "current_state_resolution_v1",
            "status": "resolved",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "asset_id": "asset.seek.portfolio",
            "asset_content_sha256": SHA_A,
            "source_workflow_sha256": SHA_B,
            "reviewed_revision_hash": SHA_C,
            "canonical_origin": "https://nz.seek.com",
            "state_id": next_observation.state.state_id,
            "state_availability": next_observation.state.state_availability,
            "score": 1.0,
            "capture_lineage": {
                "capture_id": next_observation.current_capture.capture_id,
                "screenshot_sha256": next_observation.current_capture.screenshot_sha256,
                "viewport_size": {"width": 1280, "height": 720},
            },
            "resolution_sha256": next_observation.state.resolution_sha256,
            "observed_origin": "https://nz.seek.com",
            "matched_anchor_ids": ["anchor-detail"],
            "evidence_refs": ["post-state:1"],
        },
        "evidence_refs": [
            "backend-receipt:1",
            "candidate:1",
            "gate:1",
            "post-state:1",
            "trace:1",
        ],
    }


def _semantic_success_receipt(
    verification: dict[str, object],
    next_observation: AgentObservationV1,
    *,
    safe_stop: bool = False,
) -> RuntimeResultReceiptV1:
    payload = _receipt_payload()
    verification_bytes = json.dumps(
        verification,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    payload.update(
        outcome="SAFE_STOP" if safe_stop else "VERIFIED",
        reason_code="stop_boundary" if safe_stop else "none",
        effect_status="verified",
        destination_status="verified",
        next_observation_id=next_observation.observation_id,
    )
    payload["evidence"]["verification_ref"] = (
        f"verification:{hashlib.sha256(verification_bytes).hexdigest()}"
    )
    payload["safe_stop"] = {
        "required": safe_stop,
        "reason_code": "stop_boundary" if safe_stop else "none",
    }
    return RuntimeResultReceiptV1.model_validate(payload)


def _blocked_verification(failure_code: str) -> dict[str, object]:
    verification: dict[str, object] = {
        "contract_version": "transition_verification_v1",
        "status": "blocked",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "failure_code": failure_code,
        "state_advanced": False,
    }
    if failure_code == "destination_mismatch":
        verification["post_state_resolution"] = _verification(
            _next_observation()
        )["post_state_resolution"]
    elif failure_code == "post_action_failure":
        verification["post_state_resolution"] = {
            "contract_version": "current_state_resolution_v1",
            "status": "blocked",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "failure_code": "current_state_unresolved",
            "asset_id": "asset.seek.portfolio",
            "asset_content_sha256": SHA_A,
            "source_workflow_sha256": SHA_B,
            "reviewed_revision_hash": SHA_C,
            "canonical_origin": "https://nz.seek.com",
            "capture_lineage": {
                "capture_id": "capture-next",
                "screenshot_sha256": SHA_C,
                "viewport_size": {"width": 1280, "height": 720},
            },
            "evidence_refs": [],
        }
    return verification


def _verification_failed_receipt(
    verification: dict[str, object],
    *,
    reason_code: str | None = None,
) -> RuntimeResultReceiptV1:
    failure_code = str(verification["failure_code"])
    public_reason = reason_code or failure_code
    payload = _receipt_payload()
    verification_bytes = json.dumps(
        verification,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    payload.update(
        outcome="VERIFICATION_FAILED",
        reason_code=public_reason,
        effect_status="not_verified",
        destination_status=(
            "not_evaluated"
            if public_reason == "post_capture_not_new"
            else "not_verified"
        ),
    )
    payload["evidence"]["verification_ref"] = (
        f"verification:{hashlib.sha256(verification_bytes).hexdigest()}"
    )
    payload["safe_stop"] = {
        "required": True,
        "reason_code": public_reason,
    }
    return RuntimeResultReceiptV1.model_validate(payload)


@pytest.mark.parametrize(
    "failure_code,public_reason",
    [
        ("post_capture_not_new", "post_capture_not_new"),
        ("destination_mismatch", "destination_mismatch"),
        ("post_action_failure", "post_action_failure"),
    ],
)
def test_verification_failed_v2_resolves_exact_blocked_evidence_after_restart(
    tmp_path: Path,
    failure_code: str,
    public_reason: str,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    verification = _blocked_verification(failure_code)
    receipt = _verification_failed_receipt(
        verification,
        reason_code=public_reason,
    )
    first = RuntimeReceiptStore(project_root=tmp_path)
    ref = first.put(
        receipt,
        backend_receipt=_backend(),
        verification_evidence=verification,
    )

    restarted = RuntimeReceiptStore(project_root=tmp_path)
    record = restarted.get(ref)

    assert record.verification_evidence == verification
    assert record.next_observation is None
    assert restarted.resolve_verification_evidence(ref) == verification
    assert restarted.resolve_verification_evidence(receipt.receipt_id) == verification
    with pytest.raises(RuntimeReceiptStoreError, match="no persisted next observation"):
        restarted.resolve_next_observation(receipt.receipt_id)
    object_path = restarted.objects_root / f'{ref["content_sha256"]}.json'
    envelope = json.loads(object_path.read_text(encoding="utf-8"))
    assert envelope["store_contract_version"] == "runtime_receipt_record_v2"
    assert envelope["next_observation"] is None
    assert envelope["application"] is None


@pytest.mark.parametrize(
    "failure_code,public_reason",
    [
        ("post_action_failure", "destination_mismatch"),
        ("capture_lineage_mismatch", "post_action_failure"),
        ("unexpected_origin", "post_action_failure"),
        ("asset_lineage_mismatch", "post_action_failure"),
        ("invalid_observation_contract", "post_action_failure"),
        ("operation_evidence_missing", "post_action_failure"),
        ("post_capture_missing", "post_action_failure"),
        ("capture_missing", "post_action_failure"),
        ("invalid_anchor_evidence", "post_action_failure"),
    ],
)
def test_verification_failed_rejects_reason_or_internal_failure_mismatch(
    tmp_path: Path,
    failure_code: str,
    public_reason: str,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    verification = _blocked_verification(failure_code)
    receipt = _verification_failed_receipt(
        verification,
        reason_code=public_reason,
    )

    with pytest.raises(RuntimeReceiptStoreError, match="verification failure"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
        )


def test_verification_failed_requires_evidence_and_forbids_next_observation(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    verification = _blocked_verification("destination_mismatch")
    receipt = _verification_failed_receipt(verification)

    with pytest.raises(RuntimeReceiptStoreError, match="requires verification evidence"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
        )
    with pytest.raises(RuntimeReceiptStoreError, match="forbids a next observation"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
            next_observation=_next_observation(),
        )


@pytest.mark.parametrize("target", ["object", "pointer"])
def test_verification_failed_v2_rejects_object_or_index_tamper(
    tmp_path: Path,
    target: str,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    verification = _blocked_verification("destination_mismatch")
    receipt = _verification_failed_receipt(verification)
    store = RuntimeReceiptStore(project_root=tmp_path)
    ref = store.put(
        receipt,
        backend_receipt=_backend(),
        verification_evidence=verification,
    )
    if target == "object":
        path = store.objects_root / f'{ref["content_sha256"]}.json'
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path = store._pointer_path(receipt.receipt_id)
        pointer = json.loads(path.read_text(encoding="utf-8"))
        pointer["content_sha256"] = "f" * 64
        path.write_text(
            json.dumps(pointer, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    with pytest.raises(RuntimeReceiptStoreError):
        RuntimeReceiptStore(project_root=tmp_path).resolve_verification_evidence(
            receipt.receipt_id
        )


@pytest.mark.parametrize("safe_stop", [False, True])
def test_semantic_success_v2_resolves_exact_evidence_after_restart(
    tmp_path: Path,
    safe_stop: bool,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    next_observation = _next_observation(stop_boundary=safe_stop)
    verification = _verification(next_observation)
    receipt = _semantic_success_receipt(
        verification,
        next_observation,
        safe_stop=safe_stop,
    )
    first = RuntimeReceiptStore(project_root=tmp_path)
    ref = first.put(
        receipt,
        backend_receipt=_backend(),
        verification_evidence=verification,
        next_observation=next_observation,
    )

    restarted = RuntimeReceiptStore(project_root=tmp_path)
    record = restarted.get(ref)

    assert record.verification_evidence == verification
    assert record.next_observation == next_observation
    assert restarted.resolve_verification_evidence(ref) == verification
    assert restarted.resolve_verification_evidence(receipt.receipt_id) == verification
    assert restarted.resolve_next_observation(ref) == next_observation
    assert restarted.resolve_next_observation(receipt.receipt_id) == next_observation
    object_path = restarted.objects_root / f'{ref["content_sha256"]}.json'
    envelope = json.loads(object_path.read_text(encoding="utf-8"))
    assert envelope["store_contract_version"] == "runtime_receipt_record_v2"
    assert hashlib.sha256(object_path.read_bytes()).hexdigest() == ref["content_sha256"]


def test_semantic_success_rejects_verification_ref_mismatch(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    next_observation = _next_observation()
    verification = _verification(next_observation)
    payload = _semantic_success_receipt(verification, next_observation).model_dump(mode="json")
    payload["evidence"]["verification_ref"] = f"verification:{'f' * 64}"
    receipt = RuntimeResultReceiptV1.model_validate(payload)

    with pytest.raises(RuntimeReceiptStoreError, match="verification reference mismatch"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
            next_observation=next_observation,
        )


def test_semantic_success_requires_a_new_next_observation_id(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    next_payload = _next_observation().model_dump(mode="json")
    next_payload["observation_id"] = "observation-1"
    next_observation = AgentObservationV1.model_validate(next_payload)
    verification = _verification(next_observation)
    receipt = _semantic_success_receipt(verification, next_observation)

    with pytest.raises(RuntimeReceiptStoreError, match="must be new"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
            next_observation=next_observation,
        )


def test_semantic_success_wraps_malformed_observed_origin(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    next_observation = _next_observation()
    verification = _verification(next_observation)
    verification["post_state_resolution"]["observed_origin"] = "http://[::1"
    receipt = _semantic_success_receipt(verification, next_observation)

    with pytest.raises(RuntimeReceiptStoreError, match="application mismatch"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
            next_observation=next_observation,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "top_authority_key",
        "authorization_flag",
        "capture_extra_key",
        "resolution_authority_key",
        "missing_receipt_evidence",
    ],
)
def test_semantic_success_rejects_noncanonical_or_authority_smuggling_artifact(
    tmp_path: Path,
    mutation: str,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    next_observation = _next_observation()
    verification = _verification(next_observation)
    if mutation == "top_authority_key":
        verification["approved_to_click"] = True
    elif mutation == "authorization_flag":
        verification["artifact_is_authorization"] = True
    elif mutation == "capture_extra_key":
        verification["post_capture_lineage"]["command"] = "click"
    elif mutation == "resolution_authority_key":
        verification["post_state_resolution"]["approved"] = True
    else:
        verification["evidence_refs"].remove("candidate:1")
    receipt = _semantic_success_receipt(verification, next_observation)

    with pytest.raises(RuntimeReceiptStoreError):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
            next_observation=next_observation,
        )


def test_verification_failed_rejects_noncanonical_blocked_artifact(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    verification = _blocked_verification("post_capture_not_new")
    verification["approved_to_click"] = True
    receipt = _verification_failed_receipt(verification)

    with pytest.raises(RuntimeReceiptStoreError):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
        )


@pytest.mark.parametrize(
    "origin",
    [
        "javascript://nz.seek.com",
        "https://user@nz.seek.com",
        "https://nz.seek.com/path",
        "https://nz.seek.com?query=1",
        "https://nz.seek.com#fragment",
        "https://nz.seek.com:443",
        "https://nz.seek.com/",
    ],
)
def test_semantic_success_rejects_non_normalized_web_origin(
    tmp_path: Path,
    origin: str,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    next_observation = _next_observation()
    verification = _verification(next_observation)
    verification["post_state_resolution"]["observed_origin"] = origin
    receipt = _semantic_success_receipt(verification, next_observation)

    with pytest.raises(RuntimeReceiptStoreError, match="application mismatch"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
            next_observation=next_observation,
        )


def test_semantic_success_rejects_web_evidence_paired_to_native_application(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    payload = _next_observation().model_dump(mode="json")
    payload["application"] = {
        "identity_ref": "application:native:seek.exe",
        "kind": "native",
        "display_name": "SEEK",
    }
    next_observation = AgentObservationV1.model_validate(payload)
    verification = _verification(next_observation)
    receipt = _semantic_success_receipt(verification, next_observation)

    with pytest.raises(RuntimeReceiptStoreError, match="native application"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
            next_observation=next_observation,
        )


@pytest.mark.parametrize(
    "mismatch",
    ["observation_id", "session", "workflow", "application"],
)
def test_semantic_success_rejects_next_observation_lineage_mismatch(
    tmp_path: Path,
    mismatch: str,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    next_observation = _next_observation()
    verification = _verification(next_observation)
    receipt = _semantic_success_receipt(verification, next_observation)
    payload = next_observation.model_dump(mode="json")
    if mismatch == "observation_id":
        payload["observation_id"] = "observation-other"
    elif mismatch == "session":
        payload["session_id"] = "session-other"
    elif mismatch == "workflow":
        payload["workflow"]["workflow_id"] = "workflow.other"
    else:
        payload["application"]["identity_ref"] = "application:web:example.com"

    with pytest.raises(RuntimeReceiptStoreError, match="next observation .*mismatch"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
            next_observation=payload,
        )


@pytest.mark.parametrize("outcome", ["DISPATCHED", "BLOCKED", "EXECUTION_FAILED"])
def test_non_semantic_outcome_rejects_embedded_verification_or_next_observation(
    tmp_path: Path,
    outcome: str,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    next_observation = _next_observation()
    verification = _verification(next_observation)
    backend = None if outcome == "BLOCKED" else (
        _backend("not_started", "backend_failed")
        if outcome == "EXECUTION_FAILED"
        else _backend()
    )

    with pytest.raises(RuntimeReceiptStoreError, match="semantic-success"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            _receipt(outcome),
            backend_receipt=backend,
            verification_evidence=verification,
            next_observation=next_observation,
        )


def test_semantic_success_requires_both_embedded_artifacts(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    next_observation = _next_observation()
    verification = _verification(next_observation)
    receipt = _semantic_success_receipt(verification, next_observation)

    with pytest.raises(RuntimeReceiptStoreError, match="requires verification evidence"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
        )
    with pytest.raises(RuntimeReceiptStoreError, match="requires verification evidence"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            receipt,
            backend_receipt=_backend(),
            verification_evidence=verification,
        )


def test_existing_semantic_success_v1_record_remains_reloadable(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    next_observation = _next_observation()
    verification = _verification(next_observation)
    receipt = _semantic_success_receipt(verification, next_observation)
    backend = _backend()
    envelope = {
        "store_contract_version": "runtime_receipt_record_v1",
        "runtime_receipt": receipt.model_dump(mode="json"),
        "backend_receipt": {
            "receipt_ref": backend.receipt_ref,
            "status": backend.status,
            "reason_code": backend.reason_code,
        },
    }
    object_bytes = json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(object_bytes).hexdigest()
    store = RuntimeReceiptStore(project_root=tmp_path)
    store._publish_bytes(store._object_path(digest), object_bytes)
    store._publish_bytes(
        store._pointer_path(receipt.receipt_id),
        json.dumps(
            {
                "store_contract_version": "runtime_receipt_pointer_v1",
                "receipt_id": receipt.receipt_id,
                "content_sha256": digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    )
    store._publish_bytes(
        store._intent_pointer_path(
            session_id=receipt.session_id,
            observation_id=receipt.observation_id,
            intent_id=receipt.intent_id,
        ),
        json.dumps(
            {
                "store_contract_version": "runtime_receipt_intent_pointer_v1",
                "session_id": receipt.session_id,
                "observation_id": receipt.observation_id,
                "intent_id": receipt.intent_id,
                "receipt_id": receipt.receipt_id,
                "content_sha256": digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    )

    restarted = RuntimeReceiptStore(project_root=tmp_path)
    record = restarted.load_by_receipt_id(receipt.receipt_id)

    assert record.runtime_receipt == receipt
    assert record.backend_receipt == backend
    assert record.verification_evidence is None
    assert record.next_observation is None
    with pytest.raises(RuntimeReceiptStoreError, match="no persisted verification"):
        restarted.resolve_verification_evidence(receipt.receipt_id)


@pytest.mark.parametrize("target", ["object", "pointer"])
def test_semantic_success_v2_rejects_object_or_index_tamper(
    tmp_path: Path,
    target: str,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    next_observation = _next_observation()
    verification = _verification(next_observation)
    receipt = _semantic_success_receipt(verification, next_observation)
    store = RuntimeReceiptStore(project_root=tmp_path)
    ref = store.put(
        receipt,
        backend_receipt=_backend(),
        verification_evidence=verification,
        next_observation=next_observation,
    )
    if target == "object":
        path = store.objects_root / f'{ref["content_sha256"]}.json'
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path = store._pointer_path(receipt.receipt_id)
        pointer = json.loads(path.read_text(encoding="utf-8"))
        pointer["content_sha256"] = "f" * 64
        path.write_text(
            json.dumps(pointer, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    restarted = RuntimeReceiptStore(project_root=tmp_path)
    with pytest.raises(RuntimeReceiptStoreError):
        restarted.resolve_verification_evidence(receipt.receipt_id)
    with pytest.raises(RuntimeReceiptStoreError):
        restarted.resolve_next_observation(receipt.receipt_id)


@pytest.mark.parametrize(
    "outcome,backend",
    [
        ("BLOCKED", None),
        ("DISPATCHED", _backend()),
    ],
)
def test_store_reloads_validated_receipt_after_restart(
    tmp_path: Path,
    outcome: str,
    backend: BackendDispatchReceipt | None,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    first = RuntimeReceiptStore(project_root=tmp_path)
    ref = first.put(_receipt(outcome), backend_receipt=backend)

    restarted = RuntimeReceiptStore(project_root=tmp_path)
    record = restarted.get(ref)
    by_id = restarted.load_by_receipt_id(_receipt(outcome).receipt_id)

    assert record.runtime_receipt == _receipt(outcome)
    assert by_id == record
    assert record.backend_receipt == backend
    assert ref == {
        "receipt_id": _receipt(outcome).receipt_id,
        "content_sha256": record.content_sha256,
    }
    pointer_name = hashlib.sha256(_receipt(outcome).receipt_id.encode("utf-8")).hexdigest()
    assert (restarted.root / "receipt-ids" / f"{pointer_name}.json").is_file()
    assert not (restarted.root / "receipt-ids" / "receipt:runtime:1.json").exists()
    assert restarted.find_for_intent(
        session_id=_receipt(outcome).session_id,
        observation_id=_receipt(outcome).observation_id,
        intent_id=_receipt(outcome).intent_id,
    ) == record


@pytest.mark.parametrize(
    "outcome,backend,match",
    [
        ("DISPATCHED", None, "backend receipt is required"),
        ("BLOCKED", _backend(), "cannot have a backend receipt"),
        (
            "DISPATCHED",
            BackendDispatchReceipt(
                receipt_ref="backend-receipt:wrong",
                status="dispatched",
                reason_code="none",
            ),
            "reference mismatch",
        ),
        ("DISPATCHED", _backend("not_started", "backend_failed"), "status mismatch"),
        ("DISPATCHED", _backend("dispatched", "backend_failed"), "reason mismatch"),
        ("EXECUTION_FAILED", _backend(), "status mismatch"),
        ("EXECUTION_FAILED", _backend("not_started", "none"), "reason mismatch"),
        ("INDETERMINATE", _backend(), "status mismatch"),
    ],
)
def test_store_rejects_missing_or_mismatched_backend_receipt(
    tmp_path: Path,
    outcome: str,
    backend: BackendDispatchReceipt | None,
    match: str,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    with pytest.raises(RuntimeReceiptStoreError, match=match):
        RuntimeReceiptStore(project_root=tmp_path).put(
            _receipt(outcome),
            backend_receipt=backend,
        )


@pytest.mark.parametrize(
    "outcome,backend",
    [
        ("EXECUTION_FAILED", _backend("not_started", "backend_failed")),
        ("INDETERMINATE", _backend("indeterminate", "backend_result_lost")),
    ],
)
def test_store_accepts_backend_failure_and_indeterminate_pairings(
    tmp_path: Path,
    outcome: str,
    backend: BackendDispatchReceipt,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeReceiptStore(project_root=tmp_path)
    record = store.get(store.put(_receipt(outcome), backend_receipt=backend))

    assert record.backend_receipt == backend


def test_execution_failed_backend_not_started_reason_remains_reloadable(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    payload = _receipt_payload("EXECUTION_FAILED")
    payload["reason_code"] = "backend_not_started"
    payload["safe_stop"] = {
        "required": True,
        "reason_code": "backend_not_started",
    }
    receipt = RuntimeResultReceiptV1.model_validate(payload)
    backend = _backend("not_started", "backend_failed")
    store = RuntimeReceiptStore(project_root=tmp_path)

    record = store.get(store.put(receipt, backend_receipt=backend))

    assert record.runtime_receipt.reason_code == "backend_not_started"
    assert record.backend_receipt == backend


def test_store_rejects_non_backend_receipt_object_with_structured_error(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    with pytest.raises(RuntimeReceiptStoreError, match="invalid backend receipt"):
        RuntimeReceiptStore(project_root=tmp_path).put(
            _receipt(),
            backend_receipt={"receipt_ref": "backend-receipt:1"},  # type: ignore[arg-type]
        )


def test_same_receipt_is_idempotent_but_conflicting_identity_never_overwrites(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    first = store.put(_receipt(), backend_receipt=_backend())
    assert store.put(_receipt(), backend_receipt=_backend()) == first
    pointer_path = store.root / "receipt-ids" / (
        hashlib.sha256(_receipt().receipt_id.encode("utf-8")).hexdigest() + ".json"
    )
    committed_pointer = pointer_path.read_bytes()

    changed = _receipt_payload()
    changed["issued_at"] = "2026-08-22T01:02:04Z"
    with pytest.raises(RuntimeReceiptStoreError, match="receipt identity conflict"):
        store.put(RuntimeResultReceiptV1.model_validate(changed), backend_receipt=_backend())

    assert pointer_path.read_bytes() == committed_pointer
    assert store.get(first).runtime_receipt.issued_at == "2026-08-22T01:02:03Z"


def test_same_intent_cannot_bind_a_second_receipt_identity(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    first = store.put(_receipt(), backend_receipt=_backend())
    second_payload = _receipt_payload()
    second_payload["receipt_id"] = "receipt:runtime:2"
    second_payload["issued_at"] = "2026-08-22T01:02:04Z"
    second = RuntimeResultReceiptV1.model_validate(second_payload)

    with pytest.raises(RuntimeReceiptStoreError, match="intent identity conflict"):
        store.put(second, backend_receipt=_backend())

    assert store.find_for_intent(
        session_id=second.session_id,
        observation_id=second.observation_id,
        intent_id=second.intent_id,
    ) == store.get(first)
    second_objects = [
        path
        for path in store.objects_root.glob("*.json")
        if path.stem != first["content_sha256"]
    ]
    assert len(second_objects) == 1
    with pytest.raises(RuntimeReceiptStoreError, match="intent|authority"):
        store.get(
            {
                "receipt_id": second.receipt_id,
                "content_sha256": second_objects[0].stem,
            }
        )


@pytest.mark.parametrize("target", ["object", "pointer"])
def test_store_rejects_tampered_object_or_pointer(tmp_path: Path, target: str) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    ref = store.put(_receipt(), backend_receipt=_backend())
    if target == "object":
        path = store.root / "objects" / f'{ref["content_sha256"]}.json'
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        pointer_name = hashlib.sha256(ref["receipt_id"].encode("utf-8")).hexdigest()
        path = store.root / "receipt-ids" / f"{pointer_name}.json"
        pointer = json.loads(path.read_text(encoding="utf-8"))
        pointer["content_sha256"] = "f" * 64
        path.write_text(json.dumps(pointer), encoding="utf-8")

    with pytest.raises(RuntimeReceiptStoreError):
        store.load_by_receipt_id(ref["receipt_id"])


def test_exact_get_requires_matching_canonical_receipt_identity_pointer(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    ref = store.put(_receipt(), backend_receipt=_backend())
    pointer_path = store._pointer_path(ref["receipt_id"])
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["content_sha256"] = "f" * 64
    pointer_path.write_text(
        json.dumps(
            pointer,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeReceiptStoreError, match="pointer|identity"):
        store.get(ref)


def test_exact_get_rejects_tampered_intent_identity_pointer(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    receipt = _receipt()
    ref = store.put(receipt, backend_receipt=_backend())
    intent_path = store._intent_pointer_path(
        session_id=receipt.session_id,
        observation_id=receipt.observation_id,
        intent_id=receipt.intent_id,
    )
    pointer = json.loads(intent_path.read_text(encoding="utf-8"))
    pointer["receipt_id"] = "receipt:runtime:other"
    intent_path.write_text(
        json.dumps(
            pointer,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeReceiptStoreError, match="intent|authority"):
        store.get(ref)


def test_find_for_intent_rejects_canonical_pointer_cross_linked_to_other_intent(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    first = _receipt()
    first_ref = store.put(first, backend_receipt=_backend())
    second_payload = _receipt_payload()
    second_payload.update(
        receipt_id="receipt:runtime:other",
        issued_at="2026-08-22T01:02:04Z",
        session_id="session-other",
        observation_id="observation-other",
        intent_id="intent.other",
    )
    second = RuntimeResultReceiptV1.model_validate(second_payload)
    second_ref = store.put(second, backend_receipt=_backend())

    first_intent_path = store._intent_pointer_path(
        session_id=first.session_id,
        observation_id=first.observation_id,
        intent_id=first.intent_id,
    )
    cross_link = {
        "store_contract_version": "runtime_receipt_intent_pointer_v1",
        "session_id": first.session_id,
        "observation_id": first.observation_id,
        "intent_id": first.intent_id,
        "receipt_id": second_ref["receipt_id"],
        "content_sha256": second_ref["content_sha256"],
    }
    first_intent_path.write_text(
        json.dumps(
            cross_link,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeReceiptStoreError, match="intent|identity"):
        store.find_for_intent(
            session_id=first.session_id,
            observation_id=first.observation_id,
            intent_id=first.intent_id,
        )
    assert store.get(second_ref).runtime_receipt == second
    with pytest.raises(RuntimeReceiptStoreError):
        store.get(first_ref)


def test_failed_partial_object_write_is_cleaned_and_retry_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)

    def fail_after_partial_write(path: Path, contents: bytes) -> None:
        path.write_bytes(contents[:1])
        raise OSError("injected partial write")

    monkeypatch.setattr(store, "_write_temp", fail_after_partial_write)
    with pytest.raises(RuntimeReceiptStoreError, match="write failed"):
        store.put(_receipt(), backend_receipt=_backend())
    assert list(store.root.rglob("*.tmp")) == []
    assert list((store.root / "receipt-ids").glob("*.json")) == []

    monkeypatch.undo()
    ref = store.put(_receipt(), backend_receipt=_backend())
    assert store.get(ref).runtime_receipt.receipt_id == _receipt().receipt_id


def test_orphan_object_after_pointer_failure_is_reused_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    original_publish = store._publish_temp
    publish_count = 0

    def fail_pointer_publish(temporary: Path, target: Path, contents: bytes) -> bool:
        nonlocal publish_count
        publish_count += 1
        if target.parent.name == "receipt-ids":
            raise OSError("injected pointer failure")
        return original_publish(temporary, target, contents)

    monkeypatch.setattr(store, "_publish_temp", fail_pointer_publish)
    with pytest.raises(RuntimeReceiptStoreError, match="write failed"):
        store.put(_receipt(), backend_receipt=_backend())
    assert len(list((store.root / "objects").glob("*.json"))) == 1
    assert list((store.root / "receipt-ids").glob("*.json")) == []

    monkeypatch.undo()
    ref = store.put(_receipt(), backend_receipt=_backend())
    assert store.get(ref).backend_receipt == _backend()
    assert publish_count == 2


def test_durable_publish_failure_before_identity_commit_keeps_orphan_nonauthoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    original_publish = store._durable_publish_no_replace

    def fail_identity_commit(temporary: Path, target: Path) -> None:
        if target.parent == store.receipt_ids_root:
            raise OSError("injected durable identity commit failure")
        original_publish(temporary, target)

    monkeypatch.setattr(store, "_durable_publish_no_replace", fail_identity_commit)
    with pytest.raises(RuntimeReceiptStoreError, match="write failed"):
        store.put(_receipt(), backend_receipt=_backend())

    objects = list(store.objects_root.glob("*.json"))
    assert len(objects) == 1
    assert list(store.receipt_ids_root.glob("*.json")) == []
    with pytest.raises(RuntimeReceiptStoreError):
        store.load_by_receipt_id(_receipt().receipt_id)
    exact_ref = {
        "receipt_id": _receipt().receipt_id,
        "content_sha256": objects[0].stem,
    }
    with pytest.raises(RuntimeReceiptStoreError, match="pointer|identity"):
        store.get(exact_ref)

    monkeypatch.undo()
    committed_ref = store.put(_receipt(), backend_receipt=_backend())
    assert committed_ref == exact_ref
    assert store.get(committed_ref).runtime_receipt == _receipt()


def test_intent_pointer_failure_keeps_receipt_nonauthoritative_until_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    original_publish = store._durable_publish_no_replace

    def fail_intent_commit(temporary: Path, target: Path) -> None:
        if target.parent == store.intent_ids_root:
            raise OSError("injected durable intent commit failure")
        original_publish(temporary, target)

    monkeypatch.setattr(store, "_durable_publish_no_replace", fail_intent_commit)
    with pytest.raises(RuntimeReceiptStoreError, match="write failed"):
        store.put(_receipt(), backend_receipt=_backend())

    objects = list(store.objects_root.glob("*.json"))
    receipt_pointers = list(store.receipt_ids_root.glob("*.json"))
    assert len(objects) == len(receipt_pointers) == 1
    assert list(store.intent_ids_root.glob("*.json")) == []
    incomplete_ref = {
        "receipt_id": _receipt().receipt_id,
        "content_sha256": objects[0].stem,
    }
    with pytest.raises(RuntimeReceiptStoreError, match="intent|authority"):
        store.get(incomplete_ref)
    assert store.find_for_intent(
        session_id=_receipt().session_id,
        observation_id=_receipt().observation_id,
        intent_id=_receipt().intent_id,
    ) is None

    monkeypatch.undo()
    assert store.put(_receipt(), backend_receipt=_backend()) == incomplete_ref
    assert store.get(incomplete_ref).runtime_receipt == _receipt()


@pytest.mark.parametrize(
    "use_windows,expected_helper",
    [
        (True, "windows"),
        (False, "posix"),
    ],
)
def test_durable_publish_selects_platform_specific_no_replace_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    use_windows: bool,
    expected_helper: str,
) -> None:
    import app.agent.runtime_receipt_store as receipt_store_module
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeReceiptStore(project_root=tmp_path)
    calls: list[str] = []

    def publish(label: str, temporary: Path, target: Path) -> None:
        calls.append(label)
        # 测试替身仍使用 no-replace hard link，保留并发冲突语义。
        os.link(temporary, target)

    monkeypatch.setattr(receipt_store_module, "_IS_WINDOWS", use_windows)
    monkeypatch.setattr(
        receipt_store_module,
        "_publish_windows_no_replace_write_through",
        lambda temporary, target: publish("windows", temporary, target),
        raising=False,
    )
    monkeypatch.setattr(
        receipt_store_module,
        "_publish_posix_no_replace_durable",
        lambda temporary, target: publish("posix", temporary, target),
        raising=False,
    )

    store.put(_receipt(), backend_receipt=_backend())

    assert calls == [expected_helper, expected_helper, expected_helper]


def test_concurrent_identical_puts_converge(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeReceiptStore(project_root=tmp_path)
    barrier = Barrier(4)
    results: list[dict[str, str]] = []
    failures: list[BaseException] = []

    def put() -> None:
        try:
            barrier.wait()
            results.append(store.put(_receipt(), backend_receipt=_backend()))
        except BaseException as exc:
            failures.append(exc)

    threads = [Thread(target=put) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert len(results) == 4
    assert all(result == results[0] for result in results)
    assert len(list((store.root / "objects").glob("*.json"))) == 1
    assert len(list((store.root / "receipt-ids").glob("*.json"))) == 1


def test_concurrent_conflicting_receipt_id_has_one_winner(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    store = RuntimeReceiptStore(project_root=tmp_path)
    barrier = Barrier(2)
    results: list[dict[str, str]] = []
    failures: list[BaseException] = []
    payloads = [_receipt_payload(), deepcopy(_receipt_payload())]
    payloads[1]["issued_at"] = "2026-08-22T01:02:04Z"

    def put(payload: dict[str, object]) -> None:
        try:
            barrier.wait()
            results.append(
                store.put(
                    RuntimeResultReceiptV1.model_validate(payload),
                    backend_receipt=_backend(),
                )
            )
        except BaseException as exc:
            failures.append(exc)

    threads = [Thread(target=put, args=(payload,)) for payload in payloads]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], RuntimeReceiptStoreError)
    assert "receipt identity conflict" in str(failures[0])
    assert store.get(results[0]).runtime_receipt.issued_at in {
        "2026-08-22T01:02:03Z",
        "2026-08-22T01:02:04Z",
    }


def test_store_rejects_symlink_redirection_outside_fixed_root(tmp_path: Path) -> None:
    from app.agent.runtime_receipt_store import RuntimeReceiptStore, RuntimeReceiptStoreError

    external = tmp_path / "external"
    external.mkdir()
    runtime_state = tmp_path / "runtime_state"
    runtime_state.mkdir()
    root = runtime_state / "runtime-receipts-v1"
    try:
        root.symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    with pytest.raises(RuntimeReceiptStoreError, match="redirection|reparse"):
        RuntimeReceiptStore(project_root=tmp_path)
