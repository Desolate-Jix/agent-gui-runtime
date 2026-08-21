from __future__ import annotations

from copy import deepcopy

import pytest

from app.agent.reviewed_workflow_asset import content_sha256, validate_reviewed_workflow_asset
from app.agent.reviewed_workflow_replay import (
    resolve_current_state,
    select_verified_transition,
)
from app.agent.runtime_contracts import validate_agent_intent_v1, validate_agent_observation_v1
from tests.test_reviewed_workflow_asset_v2 import _asset
from tests.test_reviewed_workflow_replay_v2 import _observation, _operation


def _refs(**overrides):
    from app.agent.replay_runtime_receipt_adapter import ReplayReceiptRefsV1

    values = {
        "candidate_ref": "candidate:1",
        "gate_decision_ref": "gate:1",
        "backend_receipt_ref": "backend:1",
        "trace_refs": ("trace:1",),
    }
    values.update(overrides)
    return ReplayReceiptRefsV1(**values)


def _workflow(asset: dict) -> dict:
    return {
        "workflow_id": "workflow-1",
        "asset_id": asset["asset_id"],
        "asset_content_sha256": content_sha256(asset),
        "source_workflow_sha256": asset["source_review_lineage"]["source_workflow_sha256"],
        "reviewed_revision_hash": asset["source_review_lineage"]["reviewed_revision_hash"],
    }


def _state_payload(asset: dict, state_id: str, availability: str, resolution_sha256: str) -> dict:
    state = next(item for item in asset["states"] if item["state_id"] == state_id)
    return {
        "status": "matched" if availability == "reviewed" else "stop_boundary",
        "state_id": state_id,
        "state_availability": availability,
        "resolution_sha256": resolution_sha256,
        "source_interface_id": state["source_node_id"],
        "display_name": state["display_name"],
        "surface_type": state["state_type"],
        "responsibility": "Reviewed replay state identity.",
    }


def _runtime_observation(
    *,
    asset: dict,
    workflow: dict,
    observation_id: str,
    capture_id: str,
    screenshot_sha256: str,
    state_id: str,
    availability: str,
    resolution_sha256: str,
    available_transition: dict | None = None,
) -> object:
    is_stop = availability == "stop_boundary"
    anchor_ref = f"evidence:{capture_id}:identity"
    evidence_refs = ["state-resolution:2", f"capture:{capture_id}", anchor_ref]
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
    if not is_stop:
        if available_transition is None:
            raise ValueError("reviewed observation requires an available transition")
        actions = [{
            "action_id": available_transition["transition_id"],
            "semantic_action": available_transition["semantic_action"],
            "description": available_transition["display_name"],
            "target_state_id": available_transition["target_state_id"],
            "expected_effect": f"Reach reviewed state: {available_transition['target_state_id']}.",
            "verification_rule_refs": [f"workflow-rule:{available_transition['post_action_verification']['semantic_success_rules'][0]['rule_id']}"],
            "risk_level": "medium" if available_transition["semantic_action"] == "open_apply_flow" else available_transition["risk_policy"]["risk_level"],
            "requires_user_confirmation": available_transition["semantic_action"] == "open_apply_flow" or available_transition["risk_policy"]["requires_user_confirmation"],
        }, safe_action]
    else:
        actions = [safe_action]
    payload = {
        "contract_version": "agent_observation_v1",
        "observation_id": observation_id,
        "session_id": "session-1",
        "workflow": workflow,
        "application": {
            "identity_ref": "application:web:nz.seek.com",
            "kind": "web",
            "display_name": "nz.seek.com",
        },
        "state_resolution_ref": "state-resolution:2",
        "current_capture": {
            "capture_id": capture_id,
            "screenshot_sha256": screenshot_sha256,
            "evidence_ref": f"capture:{capture_id}",
        },
        "state": _state_payload(asset, state_id, availability, resolution_sha256),
        "semantic_facts": [{
            "fact_id": "identity-target",
            "fact_type": "identity_anchor",
            "label": "Current reviewed state identity",
            "value": state_id,
            "observation_status": "current",
            "capture_id": capture_id,
            "value_sha256": None,
            "evidence_refs": [anchor_ref],
        }],
        "evidence_refs": evidence_refs,
        "blockers": ([{
            "blocker_id": "reviewed-stop-boundary",
            "blocker_type": "policy",
            "description": "Synthetic reviewed stop-boundary fixture; no live/open-apply proof.",
            "safe_stop_required": True,
            "evidence_refs": ["state-resolution:2"],
        }] if is_stop else []),
        "available_actions": actions,
        "safe_stop": {"required": is_stop, "reason_code": "stop_boundary" if is_stop else "none"},
        "artifact_is_authorization": False,
    }
    return validate_agent_observation_v1(payload)


def _case(*, transition_id: str = "open_detail", failure: str | None = None):
    raw_asset = _asset()
    if transition_id == "open_apply_flow":
        raw_asset["transitions"][1]["semantic_action"] = "close_modal"
    asset = validate_reviewed_workflow_asset(raw_asset)
    if transition_id == "open_detail":
        source_anchors, target_anchors, target_capture = ("anchor_homepage", "job_card"), ("anchor_detail", "quick_apply"), "capture-2"
    else:
        source_anchors, target_anchors, target_capture = ("anchor_detail", "quick_apply"), ("anchor_apply_entry",), "capture-2"
    current = _observation(asset, "capture-1", "a" * 64, *source_anchors)
    resolution = resolve_current_state(asset, current)
    selection = select_verified_transition(asset, resolution, transition_id=transition_id, current_observation=current)
    operation = _operation(selection)
    operation["evidence_refs"] = ["candidate:1", "gate:1", "backend:1", "trace:1"]
    if failure == "post_capture_not_new":
        post = _observation(asset, "capture-1", "b" * 64, *target_anchors)
    elif failure == "destination_mismatch":
        post = _observation(asset, target_capture, "b" * 64, *source_anchors)
    elif failure == "post_action_failure":
        post = _observation(asset, target_capture, "b" * 64)
    else:
        post = _observation(asset, target_capture, "b" * 64, *target_anchors)
    workflow = _workflow(asset)
    action = next(item for item in asset["transitions"] if item["transition_id"] == transition_id)
    observation = _runtime_observation(
        asset=asset,
        workflow=workflow,
        observation_id="observation-1",
        capture_id="capture-1",
        screenshot_sha256="a" * 64,
        state_id=action["source_state_id"],
        availability="reviewed",
        resolution_sha256=resolution["resolution_sha256"],
        available_transition=action,
    )
    intent = validate_agent_intent_v1({
        "contract_version": "agent_intent_v1",
        "intent_id": "intent-1",
        "session_id": "session-1",
        "observation_id": "observation-1",
        "workflow": workflow,
        "action_id": transition_id,
    }, observation=observation)
    post_resolution = resolve_current_state(asset, post)
    next_observation = None
    if post_resolution.get("status") == "resolved":
        next_transition = next(
            (item for item in asset["transitions"] if item["source_state_id"] == post_resolution["state_id"]),
            None,
        )
        next_observation = _runtime_observation(
            asset=asset,
            workflow=workflow,
            observation_id="observation-2",
            capture_id=post["capture_id"],
            screenshot_sha256=post["screenshot_sha256"],
            state_id=post_resolution["state_id"],
            availability=post_resolution["state_availability"],
            resolution_sha256=post_resolution["resolution_sha256"],
            available_transition=next_transition,
        )
    return asset, observation, intent, selection, operation, post, next_observation


def _adapt(*, transition_id: str = "open_detail", failure: str | None = None, **overrides):
    from app.agent.replay_runtime_receipt_adapter import adapt_replay_verification_to_runtime_receipt_v1

    asset, observation, intent, selection, operation, post, next_observation = _case(transition_id=transition_id, failure=failure)
    values = {
        "receipt_id": "receipt-1",
        "issued_at": "2026-08-22T12:00:00Z",
        "observation": observation,
        "intent": intent,
        "reviewed_asset": asset,
        "selection": selection,
        "operation_result": operation,
        "post_observation": post,
        "refs": _refs(),
        "next_observation": next_observation,
    }
    values.update(overrides)
    return adapt_replay_verification_to_runtime_receipt_v1(**values)


def test_recomputes_verified_reviewed_target_and_binds_next_observation() -> None:
    receipt = _adapt()
    assert receipt.outcome == "VERIFIED"
    assert receipt.dispatch_status == "dispatched"
    assert receipt.effect_status == receipt.destination_status == "verified"
    assert receipt.next_observation_id == "observation-2"
    assert receipt.evidence.selection_ref.startswith("selection:")
    assert receipt.evidence.verification_ref.startswith("verification:")


def test_recomputes_stop_boundary_as_dispatched_safe_stop_with_honest_fixture() -> None:
    receipt = _adapt(transition_id="open_apply_flow")
    assert receipt.outcome == "SAFE_STOP"
    assert receipt.reason_code == "stop_boundary"
    assert receipt.action.semantic_action == "close_modal"
    assert receipt.next_observation_id == "observation-2"


def test_hand_forged_transition_verification_parameter_is_not_accepted() -> None:
    asset, observation, intent, selection, operation, post, next_observation = _case()
    forged = {"contract_version": "transition_verification_v1", "status": "verified", "state_advanced": True}
    with pytest.raises(TypeError, match="transition_verification"):
        _adapt(
            reviewed_asset=asset,
            observation=observation,
            intent=intent,
            selection=selection,
            operation_result=operation,
            post_observation=post,
            next_observation=next_observation,
            transition_verification=forged,
        )


@pytest.mark.parametrize("tamper", ["selection", "asset", "operation", "post"])
def test_tampered_replay_inputs_cannot_produce_verified_receipt(tamper: str) -> None:
    asset, observation, intent, selection, operation, post, next_observation = _case()
    if tamper == "selection":
        selection = deepcopy(selection)
        selection["selection_sha256"] = "c" * 64
    elif tamper == "asset":
        asset = deepcopy(asset)
        asset["states"][1]["display_name"] = "Forged Detail"
    elif tamper == "operation":
        operation = deepcopy(operation)
        operation["replay_context"]["selection_sha256"] = "c" * 64
    else:
        post = deepcopy(post)
        post["screenshot_sha256"] = "c" * 64
    with pytest.raises(ValueError):
        _adapt(
            reviewed_asset=asset,
            observation=observation,
            intent=intent,
            selection=selection,
            operation_result=operation,
            post_observation=post,
            next_observation=next_observation,
        )


@pytest.mark.parametrize("failure", ["post_capture_not_new", "destination_mismatch", "post_action_failure"])
def test_post_dispatch_verification_failure_has_no_next_observation(failure: str) -> None:
    receipt = _adapt(failure=failure, next_observation=None)
    assert receipt.outcome == "VERIFICATION_FAILED"
    assert receipt.dispatch_status == "dispatched"
    assert receipt.effect_status == "not_verified"
    assert receipt.destination_status != "verified"
    assert receipt.next_observation_id is None


def test_rejects_next_observation_with_tampered_destination_or_lineage() -> None:
    asset, observation, intent, selection, operation, post, next_observation = _case()
    assert next_observation is not None
    bad_destination = next_observation.model_copy(update={"state": next_observation.state.model_copy(update={"state_id": "homepage"})})
    with pytest.raises(ValueError, match="next observation"):
        _adapt(reviewed_asset=asset, observation=observation, intent=intent, selection=selection, operation_result=operation, post_observation=post, next_observation=bad_destination)
    bad_capture = next_observation.model_copy(update={"current_capture": next_observation.current_capture.model_copy(update={"screenshot_sha256": "c" * 64})})
    with pytest.raises(ValueError, match="next observation"):
        _adapt(reviewed_asset=asset, observation=observation, intent=intent, selection=selection, operation_result=operation, post_observation=post, next_observation=bad_capture)
    bad_resolution = next_observation.model_copy(update={"state": next_observation.state.model_copy(update={"resolution_sha256": "c" * 64})})
    with pytest.raises(ValueError, match="next observation"):
        _adapt(reviewed_asset=asset, observation=observation, intent=intent, selection=selection, operation_result=operation, post_observation=post, next_observation=bad_resolution)


def test_rejects_arbitrary_refs_absent_from_operation_evidence() -> None:
    with pytest.raises(ValueError, match="operation evidence"):
        _adapt(refs=_refs(candidate_ref="candidate:unrelated"))


def test_synthetic_safe_stop_and_geometry_or_native_payloads_remain_rejected_or_omitted() -> None:
    asset, observation, intent, selection, operation, post, next_observation = _case()
    safe_intent = intent.model_copy(update={"action_id": "runtime.safe_stop"})
    with pytest.raises(ValueError, match="intent"):
        _adapt(reviewed_asset=asset, observation=observation, intent=safe_intent, selection=selection, operation_result=operation, post_observation=post, next_observation=next_observation)
    receipt = _adapt()
    encoded = str(receipt.model_dump()).casefold()
    for token in ("bbox", "click_point", "viewport", "approved_plan", "operation_result"):
        assert token not in encoded
