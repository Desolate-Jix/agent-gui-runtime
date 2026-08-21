"""Maps verified reviewed-replay evidence to the public runtime receipt."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

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
    selection_ref: str
    candidate_ref: str
    gate_decision_ref: str
    backend_receipt_ref: str
    verification_ref: str
    trace_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        values = (self.selection_ref, self.candidate_ref, self.gate_decision_ref, self.backend_receipt_ref, self.verification_ref, *self.trace_refs)
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


def adapt_replay_verification_to_runtime_receipt_v1(
    *,
    receipt_id: str,
    issued_at: str,
    observation: AgentObservationV1,
    intent: AgentIntentV1,
    selection: Mapping[str, Any],
    operation_result: Mapping[str, Any],
    transition_verification: Mapping[str, Any],
    refs: ReplayReceiptRefsV1,
    next_observation_id: str | None,
) -> RuntimeResultReceiptV1:
    """Accept only proven reviewed-replay outcomes; never infer dispatch results."""
    validate_agent_intent_v1(intent.model_dump(), observation=observation)
    _require(observation.state.status == "matched" and not observation.safe_stop.required, "replay receipt requires matched actionable observation")
    selected_action = next((item for item in observation.available_actions if item.action_id == intent.action_id), None)
    _require(selected_action is not None and selected_action.semantic_action != "safe_stop", "intent cannot select synthetic safe_stop")

    selection = _mapping(selection, "selection")
    workflow = observation.workflow
    _require(selection.get("contract_version") == "verified_transition_selection_v1" and selection.get("status") == "selected", "selection is not selected")
    for key, value in (("asset_id", workflow.asset_id), ("asset_content_sha256", workflow.asset_content_sha256), ("source_workflow_sha256", workflow.source_workflow_sha256), ("reviewed_revision_hash", workflow.reviewed_revision_hash)):
        _require(selection.get(key) == value, "selection workflow lineage mismatch")
    _require(selection.get("transition_id") == intent.action_id and selection.get("semantic_action") == selected_action.semantic_action, "selection action mismatch")
    _require(selection.get("source_state_id") == observation.state.state_id and selection.get("target_state_id") == selected_action.target_state_id, "selection state mismatch")
    selection_hash = selection.get("selection_sha256")
    _require(isinstance(selection_hash, str) and re.fullmatch(r"[0-9a-f]{64}", selection_hash) is not None, "selection hash is invalid")
    selection_lineage = _mapping(selection.get("capture_lineage"), "selection capture lineage")
    _require(selection_lineage.get("capture_id") == observation.current_capture.capture_id and selection_lineage.get("screenshot_sha256") == observation.current_capture.screenshot_sha256, "selection capture lineage mismatch")

    operation = _mapping(operation_result, "operation")
    _require(operation.get("contract_version") == "navigation_reading_operation_result_v1", "operation contract mismatch")
    _require(operation.get("action_type") == selected_action.semantic_action, "operation action mismatch")
    replay_context = _mapping(operation.get("replay_context"), "operation replay context")
    _require(replay_context == {"contract_version": "reviewed_workflow_replay_execution_context_v1", "asset_content_sha256": workflow.asset_content_sha256, "transition_id": intent.action_id, "selection_sha256": selection_hash}, "operation replay lineage mismatch")
    freshness = _mapping(operation.get("source_freshness"), "operation source freshness")
    _require(freshness.get("capture_id") == observation.current_capture.capture_id and freshness.get("screenshot_sha256") == observation.current_capture.screenshot_sha256, "operation capture lineage mismatch")
    _require(operation.get("action_executed") is True and operation.get("post_action_verified") is True, "operation dispatch is not confirmed")
    gate = _mapping(operation.get("gate_result"), "operation gate result")
    _require(gate.get("allowed") is True, "operation gate is not allowed")

    verification = _mapping(transition_verification, "transition verification")
    _require(verification.get("contract_version") == "transition_verification_v1", "transition verification contract mismatch")
    _require(verification.get("asset_content_sha256", workflow.asset_content_sha256) == workflow.asset_content_sha256, "verification workflow lineage mismatch")
    if verification.get("status") == "verified":
        _require(verification.get("selection_sha256") == selection_hash and verification.get("transition_id") == intent.action_id, "verification selection mismatch")
        _require(verification.get("source_state_id") == observation.state.state_id and verification.get("target_state_id") == selected_action.target_state_id, "verification state mismatch")
        _require(verification.get("state_advanced") is True, "verification must advance state")
        post_resolution = _mapping(verification.get("post_state_resolution"), "verification post state")
        _require(post_resolution.get("state_id") == selected_action.target_state_id, "verification destination mismatch")
        availability = post_resolution.get("state_availability")
        _require(availability in {"reviewed", "stop_boundary"}, "verification target availability is invalid")
        outcome = "SAFE_STOP" if availability == "stop_boundary" else "VERIFIED"
        reason = "stop_boundary" if outcome == "SAFE_STOP" else "none"
        effect, destination = "verified", "verified"
        next_id = next_observation_id
        safe_required = outcome == "SAFE_STOP"
    else:
        failure = verification.get("failure_code")
        _require(verification.get("status") == "blocked" and verification.get("state_advanced") is False, "verification outcome is uncertain")
        _require(failure in {"post_capture_not_new", "destination_mismatch", "post_action_failure"}, "verification outcome cannot be mapped safely")
        outcome, reason, next_id, safe_required = "VERIFICATION_FAILED", failure, None, True
        if failure == "destination_mismatch":
            effect, destination = "not_verified", "not_verified"
        elif failure == "post_capture_not_new":
            effect, destination = "not_verified", "not_evaluated"
        else:
            effect, destination = "not_verified", "not_verified"

    payload = {
        "contract_version": "runtime_result_receipt_v1", "receipt_id": receipt_id, "issued_at": issued_at,
        "session_id": observation.session_id, "observation_id": observation.observation_id, "intent_id": intent.intent_id,
        "workflow": workflow.model_dump(), "action": {"action_id": intent.action_id, "semantic_action": selected_action.semantic_action},
        "outcome": outcome, "reason_code": reason, "attempt_count": 1, "gate_status": "allowed", "dispatch_status": "dispatched",
        "effect_status": effect, "destination_status": destination,
        "evidence": {"state_resolution_ref": observation.state_resolution_ref, "selection_ref": refs.selection_ref, "candidate_ref": refs.candidate_ref, "gate_decision_ref": refs.gate_decision_ref, "backend_receipt_ref": refs.backend_receipt_ref, "verification_ref": refs.verification_ref, "trace_refs": list(refs.trace_refs)},
        "next_observation_id": next_id, "safe_stop": {"required": safe_required, "reason_code": reason}, "artifact_is_authorization": False,
    }
    return validate_runtime_result_receipt_v1(payload, observation=observation, intent=intent)


__all__ = ["ReplayReceiptRefsV1", "adapt_replay_verification_to_runtime_receipt_v1"]
