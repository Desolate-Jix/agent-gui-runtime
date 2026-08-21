"""Maps recomputed reviewed-replay evidence to the public runtime receipt."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any

from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset
from app.agent.reviewed_workflow_replay import verify_transition_result
from app.agent.runtime_contracts import (
    AgentIntentV1,
    AgentObservationV1,
    RuntimeResultReceiptV1,
    validate_agent_intent_v1,
    validate_runtime_result_receipt_v1,
)

_REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")


@dataclass(frozen=True)
class ReplayReceiptRefsV1:
    candidate_ref: str
    gate_decision_ref: str
    backend_receipt_ref: str
    trace_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (self.candidate_ref, self.gate_decision_ref, self.backend_receipt_ref, *self.trace_refs)
        if not self.trace_refs or any(not isinstance(value, str) or not _REF_PATTERN.fullmatch(value) for value in values):
            raise ValueError("typed replay receipt refs must be non-empty opaque refs")
        if len(self.trace_refs) != len(set(self.trace_refs)):
            raise ValueError("trace refs must be unique")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _derived_ref(prefix: str, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()}"


def _require_operation_refs(operation: Mapping[str, Any], refs: ReplayReceiptRefsV1) -> None:
    evidence = operation.get("evidence_refs")
    _require(isinstance(evidence, list), "operation evidence refs must be a list")
    actual_refs = {value for value in evidence if isinstance(value, str)}
    expected_refs = {refs.candidate_ref, refs.gate_decision_ref, refs.backend_receipt_ref, *refs.trace_refs}
    _require(expected_refs.issubset(actual_refs), "receipt refs must be members of operation evidence")


def _require_reviewed_asset_application(
    asset: Mapping[str, Any],
    observation: AgentObservationV1,
) -> tuple[str, str | None]:
    application = _mapping(asset.get("application"), "reviewed asset application")
    kind = application.get("kind")
    _require(kind in {"web", "native"}, "reviewed asset application kind is invalid")
    if kind == "web":
        identity = application.get("canonical_domain")
        origin = application.get("canonical_origin")
        _require(isinstance(identity, str) and identity, "reviewed asset application identity is invalid")
        _require(isinstance(origin, str) and origin, "reviewed asset application origin is invalid")
    else:
        identity = application.get("product_identity") or application.get("executable")
        origin = None
        _require(isinstance(identity, str) and identity, "reviewed asset application identity is invalid")
    _require(observation.application.kind == kind, "reviewed asset application kind mismatch")
    _require(
        observation.application.identity_ref == f"application:{kind}:{identity}",
        "reviewed asset application identity mismatch",
    )
    return kind, origin


def _require_selection_observation_lineage(selection: Mapping[str, Any], observation: AgentObservationV1) -> None:
    workflow = observation.workflow
    for key, value in (
        ("asset_id", workflow.asset_id),
        ("asset_content_sha256", workflow.asset_content_sha256),
        ("source_workflow_sha256", workflow.source_workflow_sha256),
        ("reviewed_revision_hash", workflow.reviewed_revision_hash),
    ):
        _require(selection.get(key) == value, "selection workflow lineage mismatch")
    capture = _mapping(selection.get("capture_lineage"), "selection capture lineage")
    _require(capture.get("capture_id") == observation.current_capture.capture_id, "selection capture lineage mismatch")
    _require(capture.get("screenshot_sha256") == observation.current_capture.screenshot_sha256, "selection capture lineage mismatch")


def _require_next_observation(
    next_observation: AgentObservationV1 | None,
    *,
    observation: AgentObservationV1,
    verification: Mapping[str, Any],
    expected_application_kind: str,
) -> AgentObservationV1:
    _require(isinstance(next_observation, AgentObservationV1), "verified replay requires an AgentObservationV1 next observation")
    post_resolution = _mapping(verification.get("post_state_resolution"), "verification post state")
    post_capture = _mapping(verification.get("post_capture_lineage"), "verification post capture")
    availability = post_resolution.get("state_availability")
    expected_status = "matched" if availability == "reviewed" else "stop_boundary"
    _require(availability in {"reviewed", "stop_boundary"}, "verification target availability is invalid")
    _require(next_observation.session_id == observation.session_id, "next observation session mismatch")
    _require(next_observation.workflow == observation.workflow, "next observation workflow mismatch")
    _require(next_observation.application == observation.application, "next observation application mismatch")
    _require(next_observation.application.kind == expected_application_kind, "next observation reviewed asset application mismatch")
    _require(next_observation.state.status == expected_status, "next observation status mismatch")
    _require(next_observation.state.state_id == post_resolution.get("state_id"), "next observation destination mismatch")
    _require(next_observation.state.state_availability == availability, "next observation availability mismatch")
    _require(next_observation.state.resolution_sha256 == post_resolution.get("resolution_sha256"), "next observation state resolution mismatch")
    _require(next_observation.current_capture.capture_id == post_capture.get("capture_id"), "next observation capture mismatch")
    _require(next_observation.current_capture.screenshot_sha256 == post_capture.get("screenshot_sha256"), "next observation screenshot mismatch")
    return next_observation


def adapt_replay_verification_to_runtime_receipt_v1(
    *,
    receipt_id: str,
    issued_at: str,
    observation: AgentObservationV1,
    intent: AgentIntentV1,
    reviewed_asset: Mapping[str, Any],
    selection: Mapping[str, Any],
    operation_result: Mapping[str, Any],
    post_observation: Mapping[str, Any],
    refs: ReplayReceiptRefsV1,
    next_observation: AgentObservationV1 | None,
) -> RuntimeResultReceiptV1:
    """Recompute replay verification and map only its fail-closed outcomes."""
    validate_agent_intent_v1(intent.model_dump(), observation=observation)
    _require(observation.state.status == "matched" and not observation.safe_stop.required, "replay receipt requires matched actionable observation")
    selected_action = next((item for item in observation.available_actions if item.action_id == intent.action_id), None)
    _require(selected_action is not None and selected_action.semantic_action != "safe_stop", "intent cannot select synthetic safe_stop")

    asset = validate_reviewed_workflow_asset(_mapping(reviewed_asset, "reviewed asset"))
    application_kind, expected_origin = _require_reviewed_asset_application(asset, observation)
    selection = _mapping(selection, "selection")
    operation = _mapping(operation_result, "operation")
    post = _mapping(post_observation, "post observation")
    _require_operation_refs(operation, refs)
    verification = verify_transition_result(asset, selection, operation, post)
    _require(verification.get("contract_version") == "transition_verification_v1", "recomputed verification contract mismatch")
    _require_selection_observation_lineage(selection, observation)

    if verification.get("status") == "verified":
        _require(verification.get("selection_sha256") == selection.get("selection_sha256"), "recomputed verification selection mismatch")
        _require(verification.get("transition_id") == intent.action_id, "recomputed verification transition mismatch")
        _require(verification.get("source_state_id") == observation.state.state_id, "recomputed verification source mismatch")
        _require(verification.get("target_state_id") == selected_action.target_state_id, "recomputed verification destination mismatch")
        _require(verification.get("state_advanced") is True, "recomputed verification must advance state")
        next_value = _require_next_observation(
            next_observation,
            observation=observation,
            verification=verification,
            expected_application_kind=application_kind,
        )
        post_resolution = _mapping(verification.get("post_state_resolution"), "verification post state")
        if expected_origin is not None:
            _require(post_resolution.get("observed_origin") == expected_origin, "recomputed post origin mismatch")
        availability = post_resolution.get("state_availability")
        outcome = "SAFE_STOP" if availability == "stop_boundary" else "VERIFIED"
        reason = "stop_boundary" if outcome == "SAFE_STOP" else "none"
        effect, destination, safe_required = "verified", "verified", outcome == "SAFE_STOP"
        next_id = next_value.observation_id
    else:
        failure = verification.get("failure_code")
        _require(verification.get("status") == "blocked" and verification.get("state_advanced") is False, "recomputed verification outcome is uncertain")
        _require(failure in {"post_capture_not_new", "destination_mismatch", "post_action_failure"}, "recomputed verification outcome cannot be mapped safely")
        _require(next_observation is None, "verification failure cannot advance next observation")
        if failure == "post_action_failure":
            gate = _mapping(operation.get("gate_result"), "operation gate result")
            _require(
                operation.get("action_executed") is True and gate.get("allowed") is True,
                "unproven dispatch cannot map to verification failure",
            )
        outcome, reason, next_id, safe_required = "VERIFICATION_FAILED", failure, None, True
        effect = "not_verified"
        destination = "not_evaluated" if failure == "post_capture_not_new" else "not_verified"

    selection_ref = _derived_ref("selection", selection)
    verification_ref = _derived_ref("verification", verification)
    payload = {
        "contract_version": "runtime_result_receipt_v1", "receipt_id": receipt_id, "issued_at": issued_at,
        "session_id": observation.session_id, "observation_id": observation.observation_id, "intent_id": intent.intent_id,
        "workflow": observation.workflow.model_dump(), "action": {"action_id": intent.action_id, "semantic_action": selected_action.semantic_action},
        "outcome": outcome, "reason_code": reason, "attempt_count": 1, "gate_status": "allowed", "dispatch_status": "dispatched",
        "effect_status": effect, "destination_status": destination,
        "evidence": {"state_resolution_ref": observation.state_resolution_ref, "selection_ref": selection_ref, "candidate_ref": refs.candidate_ref, "gate_decision_ref": refs.gate_decision_ref, "backend_receipt_ref": refs.backend_receipt_ref, "verification_ref": verification_ref, "trace_refs": list(refs.trace_refs)},
        "next_observation_id": next_id, "safe_stop": {"required": safe_required, "reason_code": reason}, "artifact_is_authorization": False,
    }
    return validate_runtime_result_receipt_v1(payload, observation=observation, intent=intent)


__all__ = ["ReplayReceiptRefsV1", "adapt_replay_verification_to_runtime_receipt_v1"]
