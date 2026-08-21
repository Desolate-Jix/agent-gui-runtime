from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.agent.runtime_contracts import (
    AgentIntentV1,
    AgentObservationV1,
    RuntimeResultReceiptV1,
    validate_agent_intent_v1,
    validate_agent_observation_v1,
    validate_runtime_result_receipt_v1,
)


ROOT = Path(__file__).resolve().parents[1]
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


def _observation_payload() -> dict[str, object]:
    return {
        "contract_version": "agent_observation_v1",
        "observation_id": "observation-1",
        "session_id": "session-1",
        "workflow": _workflow(),
        "application": {
            "identity_ref": "application:web:nz.seek.com",
            "kind": "web",
            "display_name": "nz.seek.com",
        },
        "state_resolution_ref": "state-resolution:1",
        "current_capture": {
            "capture_id": "capture-1",
            "screenshot_sha256": SHA_A,
            "evidence_ref": "capture:1",
        },
        "state": {
            "status": "matched",
            "state_id": "job-detail",
            "state_availability": "reviewed",
            "resolution_sha256": SHA_B,
        },
        "semantic_facts": [
            {
                "fact_id": "fact.current-job-title",
                "fact_type": "current_content",
                "label": "Current job title",
                "value": "Software Engineer",
                "observation_status": "current",
                "evidence_refs": ["evidence:job-title"],
            }
        ],
        "evidence_refs": [
            "state-resolution:1",
            "capture:1",
            "evidence:job-title",
        ],
        "blockers": [],
        "available_actions": [
            {
                "action_id": "transition.open-detail",
                "semantic_action": "open_detail",
                "description": "Open the reviewed job detail.",
                "target_state_id": "job-detail-2",
                "expected_effect": "Reach the reviewed job detail state.",
                "verification_rule_refs": ["workflow-rule:detail-visible"],
                "risk_level": "low",
                "requires_user_confirmation": False,
            },
            {
                "action_id": "transition.open-apply",
                "semantic_action": "open_apply_flow",
                "description": "Open the reviewed application entry.",
                "target_state_id": "apply-entry",
                "expected_effect": "Reach the reviewed application entry state.",
                "verification_rule_refs": ["workflow-rule:apply-entry-visible"],
                "risk_level": "medium",
                "requires_user_confirmation": True,
            },
            {
                "action_id": "runtime.safe_stop",
                "semantic_action": "safe_stop",
                "description": "Stop without dispatching another action.",
                "target_state_id": None,
                "expected_effect": "Stop without dispatching another action.",
                "verification_rule_refs": [],
                "risk_level": "low",
                "requires_user_confirmation": False,
            },
        ],
        "safe_stop": {"required": False, "reason_code": "none"},
        "artifact_is_authorization": False,
    }


def _intent_payload(action_id: str = "transition.open-detail") -> dict[str, object]:
    return {
        "contract_version": "agent_intent_v1",
        "intent_id": f"intent.{action_id}",
        "session_id": "session-1",
        "observation_id": "observation-1",
        "workflow": _workflow(),
        "action_id": action_id,
    }


def _receipt_evidence() -> dict[str, object]:
    return {
        "state_resolution_ref": "state-resolution:1",
        "selection_ref": "selection:1",
        "candidate_ref": "candidate:1",
        "gate_decision_ref": "gate:1",
        "backend_receipt_ref": "backend-receipt:1",
        "verification_ref": "verification:1",
        "trace_refs": ["trace:1"],
    }


def _receipt_payload(
    *,
    action_id: str = "transition.open-detail",
    semantic_action: str = "open_detail",
) -> dict[str, object]:
    return {
        "contract_version": "runtime_result_receipt_v1",
        "receipt_id": "receipt-1",
        "issued_at": "2026-08-22T01:02:03Z",
        "session_id": "session-1",
        "observation_id": "observation-1",
        "intent_id": f"intent.{action_id}",
        "workflow": _workflow(),
        "action": {"action_id": action_id, "semantic_action": semantic_action},
        "outcome": "VERIFIED",
        "reason_code": "none",
        "attempt_count": 1,
        "gate_status": "allowed",
        "dispatch_status": "dispatched",
        "effect_status": "verified",
        "destination_status": "verified",
        "evidence": _receipt_evidence(),
        "next_observation_id": "observation-2",
        "safe_stop": {"required": False, "reason_code": "none"},
        "artifact_is_authorization": False,
    }


def _validated_pair(action_id: str = "transition.open-detail"):
    observation = validate_agent_observation_v1(_observation_payload())
    intent = validate_agent_intent_v1(
        _intent_payload(action_id),
        observation=observation,
    )
    return observation, intent


def test_valid_observation_and_intent_are_geometry_free_and_bound() -> None:
    observation, intent = _validated_pair()
    assert observation.contract_version == "agent_observation_v1"
    assert intent.action_id == "transition.open-detail"
    assert observation.artifact_is_authorization is False
    assert {item.semantic_action for item in observation.available_actions} == {
        "open_detail",
        "open_apply_flow",
        "safe_stop",
    }


@pytest.mark.parametrize("status,reason", [
    ("ambiguous", "state_ambiguous"),
    ("unknown", "state_unknown"),
    ("stop_boundary", "stop_boundary"),
])
def test_non_actionable_state_exposes_only_safe_stop(status: str, reason: str) -> None:
    payload = _observation_payload()
    payload["state"] = {
        "status": status,
        "state_id": "apply-entry" if status == "stop_boundary" else None,
        "state_availability": "stop_boundary" if status == "stop_boundary" else None,
        "resolution_sha256": SHA_B if status == "stop_boundary" else None,
    }
    payload["available_actions"] = [deepcopy(payload["available_actions"][-1])]
    payload["safe_stop"] = {"required": True, "reason_code": reason}
    payload["semantic_facts"] = []
    payload["blockers"] = [
        {
            "blocker_id": f"blocker.{reason}",
            "blocker_type": "state",
            "description": f"Runtime requires safe stop: {reason}.",
            "safe_stop_required": True,
            "evidence_refs": ["state-resolution:1"],
        }
    ]
    observation = validate_agent_observation_v1(payload)
    assert [item.action_id for item in observation.available_actions] == ["runtime.safe_stop"]


def test_observation_exposes_application_facts_blockers_and_action_contracts() -> None:
    observation = validate_agent_observation_v1(_observation_payload())
    assert observation.application.identity_ref == "application:web:nz.seek.com"
    assert observation.semantic_facts[0].observation_status == "current"
    assert observation.semantic_facts[0].evidence_refs == ["evidence:job-title"]
    action = observation.available_actions[0]
    assert action.expected_effect == "Reach the reviewed job detail state."
    assert action.verification_rule_refs == ["workflow-rule:detail-visible"]


def test_observation_requires_current_fact_and_capture_lineage_to_be_declared() -> None:
    payload = _observation_payload()
    payload["evidence_refs"].remove("evidence:job-title")
    with pytest.raises(ValueError, match="semantic fact evidence"):
        validate_agent_observation_v1(payload)

    payload = _observation_payload()
    payload["evidence_refs"].remove("capture:1")
    with pytest.raises(ValueError, match="capture evidence"):
        validate_agent_observation_v1(payload)


def test_safe_stop_boundary_requires_a_safe_stop_blocker() -> None:
    payload = _observation_payload()
    payload["state"] = {
        "status": "unknown",
        "state_id": None,
        "state_availability": None,
        "resolution_sha256": None,
    }
    payload["semantic_facts"] = []
    payload["available_actions"] = [deepcopy(payload["available_actions"][-1])]
    payload["safe_stop"] = {"required": True, "reason_code": "state_unknown"}
    with pytest.raises(ValueError, match="safe-stop blocker"):
        validate_agent_observation_v1(payload)


def test_safe_stop_blocker_cannot_coexist_with_semantic_actions() -> None:
    payload = _observation_payload()
    payload["blockers"] = [
        {
            "blocker_id": "blocker.policy",
            "blocker_type": "policy",
            "description": "Policy requires a safe stop.",
            "safe_stop_required": True,
            "evidence_refs": ["state-resolution:1"],
        }
    ]
    with pytest.raises(ValueError, match="safe-stop blocker requires safe stop"):
        validate_agent_observation_v1(payload)


def test_non_safe_action_requires_effect_and_verification_information() -> None:
    payload = _observation_payload()
    payload["available_actions"][0]["verification_rule_refs"] = []
    with pytest.raises(ValueError, match="verification rule"):
        validate_agent_observation_v1(payload)

    payload = _observation_payload()
    payload["available_actions"][0]["expected_effect"] = ""
    with pytest.raises(ValueError):
        validate_agent_observation_v1(payload)


def test_duplicate_action_ids_are_rejected() -> None:
    payload = _observation_payload()
    payload["available_actions"].append(deepcopy(payload["available_actions"][0]))
    with pytest.raises(ValueError, match="unique"):
        validate_agent_observation_v1(payload)


def test_open_apply_flow_must_require_confirmation() -> None:
    payload = _observation_payload()
    payload["available_actions"][1]["requires_user_confirmation"] = False
    with pytest.raises(ValueError, match="confirmation"):
        validate_agent_observation_v1(payload)


@pytest.mark.parametrize(
    "container,key,value",
    [
        (("available_actions", 0), "bbox", {"x": 1}),
        (("workflow",), "click_point", {"x": 1, "y": 2}),
        (("current_capture",), "skip_gate", True),
        (("safe_stop",), "parameters", {}),
        (("state",), "human_confirmation", True),
    ],
)
def test_observation_rejects_nested_authority_or_geometry_injection(container, key, value) -> None:
    payload = _observation_payload()
    target = payload
    for part in container:
        target = target[part]
    target[key] = value
    with pytest.raises(ValueError):
        validate_agent_observation_v1(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("bbox", {"x": 1}),
        ("click_point", {"x": 1, "y": 2}),
        ("skip_gate", True),
        ("parameters", {}),
        ("confirmation", True),
        ("human_confirmation", True),
        ("approved", True),
        ("provider_native_candidate", {"id": "candidate-1"}),
        ("historical_target", "target-1"),
        ("direct_dispatch", {"type": "click"}),
    ],
)
def test_intent_rejects_authority_or_geometry_injection(field: str, value: object) -> None:
    observation = validate_agent_observation_v1(_observation_payload())
    payload = _intent_payload()
    payload[field] = value
    with pytest.raises(ValueError):
        validate_agent_intent_v1(payload, observation=observation)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(action_id="transition.unknown"),
        lambda value: value.update(observation_id="observation-wrong"),
        lambda value: value.update(session_id="session-wrong"),
        lambda value: value["workflow"].update(workflow_id="workflow.wrong"),
        lambda value: value["workflow"].update(reviewed_revision_hash=SHA_A),
    ],
)
def test_intent_rejects_unknown_action_or_wrong_binding(mutation) -> None:
    observation = validate_agent_observation_v1(_observation_payload())
    payload = _intent_payload()
    mutation(payload)
    with pytest.raises(ValueError):
        validate_agent_intent_v1(payload, observation=observation)


def _valid_outcome_case(outcome: str):
    if outcome == "VERIFIED":
        return _validated_pair(), _receipt_payload()
    if outcome == "BLOCKED":
        pair = _validated_pair()
        payload = _receipt_payload()
        payload.update(
            outcome="BLOCKED",
            reason_code="pre_click_rejected",
            attempt_count=0,
            gate_status="blocked",
            dispatch_status="not_started",
            effect_status="not_evaluated",
            destination_status="not_evaluated",
            next_observation_id=None,
            safe_stop={"required": True, "reason_code": "pre_click_rejected"},
        )
        payload["evidence"]["backend_receipt_ref"] = None
        payload["evidence"]["verification_ref"] = None
        return pair, payload
    if outcome == "SAFE_STOP":
        pair = _validated_pair("runtime.safe_stop")
        payload = _receipt_payload(action_id="runtime.safe_stop", semantic_action="safe_stop")
        payload.update(
            outcome="SAFE_STOP",
            reason_code="safe_stop_boundary",
            attempt_count=0,
            gate_status="not_evaluated",
            dispatch_status="not_started",
            effect_status="not_evaluated",
            destination_status="not_evaluated",
            next_observation_id=None,
            safe_stop={"required": True, "reason_code": "safe_stop_boundary"},
        )
        for field in ("selection_ref", "candidate_ref", "gate_decision_ref", "backend_receipt_ref", "verification_ref"):
            payload["evidence"][field] = None
        return pair, payload
    if outcome == "NEEDS_REVIEW":
        pair = _validated_pair("transition.open-apply")
        payload = _receipt_payload(action_id="transition.open-apply", semantic_action="open_apply_flow")
        payload.update(
            outcome="NEEDS_REVIEW",
            reason_code="human_confirmation_required",
            attempt_count=0,
            gate_status="not_evaluated",
            dispatch_status="not_started",
            effect_status="not_evaluated",
            destination_status="not_evaluated",
            next_observation_id=None,
            safe_stop={"required": True, "reason_code": "human_confirmation_required"},
        )
        for field in ("candidate_ref", "gate_decision_ref", "backend_receipt_ref", "verification_ref"):
            payload["evidence"][field] = None
        return pair, payload
    if outcome == "EXECUTION_FAILED":
        pair = _validated_pair()
        payload = _receipt_payload()
        payload.update(
            outcome="EXECUTION_FAILED",
            reason_code="backend_failed",
            dispatch_status="not_started",
            effect_status="not_evaluated",
            destination_status="not_evaluated",
            next_observation_id=None,
            safe_stop={"required": True, "reason_code": "backend_failed"},
        )
        payload["evidence"]["verification_ref"] = None
        return pair, payload
    if outcome == "VERIFICATION_FAILED":
        pair = _validated_pair()
        payload = _receipt_payload()
        payload.update(
            outcome="VERIFICATION_FAILED",
            reason_code="destination_mismatch",
            effect_status="verified",
            destination_status="not_verified",
            next_observation_id=None,
            safe_stop={"required": True, "reason_code": "destination_mismatch"},
        )
        return pair, payload
    if outcome == "INDETERMINATE":
        pair = _validated_pair()
        payload = _receipt_payload()
        payload.update(
            outcome="INDETERMINATE",
            reason_code="backend_result_lost",
            dispatch_status="indeterminate",
            effect_status="indeterminate",
            destination_status="indeterminate",
            next_observation_id=None,
            safe_stop={"required": True, "reason_code": "backend_result_lost"},
        )
        payload["evidence"]["verification_ref"] = None
        return pair, payload
    raise AssertionError(outcome)


@pytest.mark.parametrize("outcome", [
    "VERIFIED",
    "BLOCKED",
    "SAFE_STOP",
    "NEEDS_REVIEW",
    "EXECUTION_FAILED",
    "VERIFICATION_FAILED",
    "INDETERMINATE",
])
def test_each_receipt_outcome_has_one_valid_fail_closed_shape(outcome: str) -> None:
    (observation, intent), payload = _valid_outcome_case(outcome)
    receipt = validate_runtime_result_receipt_v1(
        payload,
        observation=observation,
        intent=intent,
    )
    assert receipt.outcome == outcome


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(effect_status="not_evaluated"),
        lambda value: value["evidence"].update(candidate_ref=None),
        lambda value: value.update(intent_id="intent.wrong"),
        lambda value: value["workflow"].update(reviewed_revision_hash=SHA_A),
        lambda value: value["evidence"].update(bbox={"x": 1}),
        lambda value: value["action"].update(click_point={"x": 1, "y": 2}),
    ],
)
def test_verified_receipt_rejects_invalid_matrix_lineage_or_geometry(mutation) -> None:
    observation, intent = _validated_pair()
    payload = _receipt_payload()
    mutation(payload)
    with pytest.raises(ValueError):
        validate_runtime_result_receipt_v1(
            payload,
            observation=observation,
            intent=intent,
        )


def test_indeterminate_receipt_cannot_advance_or_omit_backend_receipt() -> None:
    (observation, intent), payload = _valid_outcome_case("INDETERMINATE")
    payload["next_observation_id"] = "observation-2"
    payload["evidence"]["backend_receipt_ref"] = None
    with pytest.raises(ValueError):
        validate_runtime_result_receipt_v1(payload, observation=observation, intent=intent)


def test_blocked_rejects_post_dispatch_destination_reason() -> None:
    (observation, intent), payload = _valid_outcome_case("BLOCKED")
    payload["reason_code"] = "destination_mismatch"
    payload["safe_stop"]["reason_code"] = "destination_mismatch"
    with pytest.raises(ValueError, match="BLOCKED reason"):
        validate_runtime_result_receipt_v1(payload, observation=observation, intent=intent)


def test_non_dispatch_safe_stop_rejects_destination_mismatch_reason() -> None:
    (observation, intent), payload = _valid_outcome_case("SAFE_STOP")
    payload["reason_code"] = "destination_mismatch"
    payload["safe_stop"]["reason_code"] = "destination_mismatch"
    with pytest.raises(ValueError, match="SAFE_STOP reason"):
        validate_runtime_result_receipt_v1(payload, observation=observation, intent=intent)


def test_synthetic_safe_stop_can_never_be_dispatched() -> None:
    (observation, intent), payload = _valid_outcome_case("SAFE_STOP")
    payload.update(
        attempt_count=1,
        gate_status="allowed",
        dispatch_status="dispatched",
        effect_status="verified",
        destination_status="verified",
        next_observation_id="observation-2",
    )
    payload["evidence"].update(
        selection_ref="selection:1",
        candidate_ref="candidate:1",
        gate_decision_ref="gate:1",
        backend_receipt_ref="backend-receipt:1",
        verification_ref="verification:1",
    )
    with pytest.raises(ValueError, match="synthetic safe_stop"):
        validate_runtime_result_receipt_v1(payload, observation=observation, intent=intent)


@pytest.mark.parametrize(
    "outcome,mutation,match",
    [
        (
            "NEEDS_REVIEW",
            lambda value: value.update(dispatch_status="dispatched"),
            "NEEDS_REVIEW cannot dispatch",
        ),
        (
            "EXECUTION_FAILED",
            lambda value: value.update(dispatch_status="dispatched"),
            "EXECUTION_FAILED must confirm no dispatch",
        ),
        (
            "VERIFICATION_FAILED",
            lambda value: value.update(dispatch_status="not_started"),
            "VERIFICATION_FAILED requires dispatch",
        ),
    ],
)
def test_receipt_outcome_matrix_rejects_wrong_dispatch_state(outcome, mutation, match) -> None:
    (observation, intent), payload = _valid_outcome_case(outcome)
    mutation(payload)
    with pytest.raises(ValueError, match=match):
        validate_runtime_result_receipt_v1(payload, observation=observation, intent=intent)


def test_receipt_safe_stop_reason_must_match_outcome_reason() -> None:
    (observation, intent), payload = _valid_outcome_case("EXECUTION_FAILED")
    payload["safe_stop"]["reason_code"] = "policy_blocked"
    with pytest.raises(ValueError, match="safe-stop reason"):
        validate_runtime_result_receipt_v1(payload, observation=observation, intent=intent)


def test_contract_models_reject_authorization_and_non_utc_timestamp() -> None:
    observation_payload = _observation_payload()
    observation_payload["artifact_is_authorization"] = True
    with pytest.raises(ValueError):
        validate_agent_observation_v1(observation_payload)

    observation, intent = _validated_pair()
    receipt_payload = _receipt_payload()
    receipt_payload["issued_at"] = "2026-08-22T01:02:03+00:00"
    with pytest.raises(ValueError):
        validate_runtime_result_receipt_v1(
            receipt_payload,
            observation=observation,
            intent=intent,
        )


def test_static_public_schemas_are_frozen_against_models_and_geometry_free() -> None:
    cases = [
        (AgentObservationV1, "agent_observation_v1.schema.json"),
        (AgentIntentV1, "agent_intent_v1.schema.json"),
        (RuntimeResultReceiptV1, "runtime_result_receipt_v1.schema.json"),
    ]
    forbidden = {"bbox", "click_point", "clickpoint", "coordinates", "point", "viewport_size", "skip_gate"}
    for model, filename in cases:
        path = ROOT / "schemas" / "agent_runtime" / "v1" / filename
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload == model.model_json_schema()
        assert "Pydantic validators are authoritative for cross-field semantics" in payload["$comment"]
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        assert not any(f'"{field}"' in serialized for field in forbidden)
    receipt_schema = RuntimeResultReceiptV1.model_json_schema()
    assert receipt_schema["properties"]["issued_at"]["pattern"].endswith("Z$")
