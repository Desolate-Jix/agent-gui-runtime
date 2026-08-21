from __future__ import annotations

from copy import deepcopy

import pytest

from app.agent.reviewed_workflow_asset import content_sha256, validate_reviewed_workflow_asset
from app.agent.reviewed_workflow_replay import (
    resolve_current_state,
    select_verified_transition,
    verify_transition_result,
)
from app.agent.runtime_contracts import validate_agent_intent_v1, validate_agent_observation_v1
from tests.test_reviewed_workflow_asset_v2 import _asset
from tests.test_reviewed_workflow_replay_v2 import _observation, _operation


def _refs(**overrides):
    from app.agent.replay_runtime_receipt_adapter import ReplayReceiptRefsV1

    values = {
        "selection_ref": "selection:1", "candidate_ref": "candidate:1",
        "gate_decision_ref": "gate:1", "backend_receipt_ref": "backend:1",
        "verification_ref": "verification:1", "trace_refs": ("trace:1",),
    }
    values.update(overrides)
    return ReplayReceiptRefsV1(**values)


def _case(*, transition_id: str = "open_detail", failure: str | None = None):
    raw_asset = _asset()
    if transition_id == "open_apply_flow":
        # 测试 stop-boundary 成功路径；最终申请动作仍不属于 Portfolio v1。
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
    if failure == "post_capture_not_new":
        post = _observation(asset, "capture-1", "b" * 64, *target_anchors)
    elif failure == "destination_mismatch":
        post = _observation(asset, target_capture, "b" * 64, *source_anchors)
    elif failure == "post_action_failure":
        post = _observation(asset, target_capture, "b" * 64)
    else:
        post = _observation(asset, target_capture, "b" * 64, *target_anchors)
    verification = verify_transition_result(asset, selection, operation, post)
    workflow = {
        "workflow_id": "workflow-1", "asset_id": asset["asset_id"],
        "asset_content_sha256": content_sha256(asset),
        "source_workflow_sha256": asset["source_review_lineage"]["source_workflow_sha256"],
        "reviewed_revision_hash": asset["source_review_lineage"]["reviewed_revision_hash"],
    }
    action = next(item for item in asset["transitions"] if item["transition_id"] == transition_id)
    observation = validate_agent_observation_v1({
        "contract_version": "agent_observation_v1", "observation_id": "observation-1", "session_id": "session-1", "workflow": workflow,
        "application": {"identity_ref": "application:web:nz.seek.com", "kind": "web", "display_name": "nz.seek.com"},
        "state_resolution_ref": "state-resolution:1",
        "current_capture": {"capture_id": "capture-1", "screenshot_sha256": "a" * 64, "evidence_ref": "capture:1"},
        "state": {"status": "matched", "state_id": action["source_state_id"], "state_availability": "reviewed", "resolution_sha256": resolution["resolution_sha256"]},
        "semantic_facts": [], "evidence_refs": ["state-resolution:1", "capture:1"], "blockers": [],
        "available_actions": [{
            "action_id": transition_id, "semantic_action": action["semantic_action"], "description": action["display_name"], "target_state_id": action["target_state_id"],
            "expected_effect": f"Reach reviewed state: {action['target_state_id']}.", "verification_rule_refs": [f"workflow-rule:{action['post_action_verification']['semantic_success_rules'][0]['rule_id']}"],
            "risk_level": action["risk_policy"]["risk_level"], "requires_user_confirmation": action["risk_policy"]["requires_user_confirmation"],
        }, {"action_id": "runtime.safe_stop", "semantic_action": "safe_stop", "description": "Stop without dispatching another action.", "target_state_id": None, "expected_effect": "Stop without dispatching another action.", "verification_rule_refs": [], "risk_level": "low", "requires_user_confirmation": False}],
        "safe_stop": {"required": False, "reason_code": "none"}, "artifact_is_authorization": False,
    })
    intent = validate_agent_intent_v1({"contract_version": "agent_intent_v1", "intent_id": "intent-1", "session_id": "session-1", "observation_id": "observation-1", "workflow": workflow, "action_id": transition_id}, observation=observation)
    return observation, intent, selection, operation, verification


def _adapt(*, transition_id: str = "open_detail", failure: str | None = None, **overrides):
    from app.agent.replay_runtime_receipt_adapter import adapt_replay_verification_to_runtime_receipt_v1

    observation, intent, selection, operation, verification = _case(transition_id=transition_id, failure=failure)
    values = {"receipt_id": "receipt-1", "issued_at": "2026-08-22T12:00:00Z", "observation": observation, "intent": intent, "selection": selection, "operation_result": operation, "transition_verification": verification, "refs": _refs(), "next_observation_id": "observation-2"}
    values.update(overrides)
    return adapt_replay_verification_to_runtime_receipt_v1(**values)


def test_maps_existing_verified_replay_to_verified_receipt() -> None:
    receipt = _adapt()
    assert receipt.outcome == "VERIFIED"
    assert receipt.dispatch_status == "dispatched"
    assert receipt.effect_status == receipt.destination_status == "verified"


def test_maps_verified_stop_boundary_to_dispatched_safe_stop() -> None:
    receipt = _adapt(transition_id="open_apply_flow")
    assert receipt.outcome == "SAFE_STOP"
    assert receipt.reason_code == "stop_boundary"
    assert receipt.action.semantic_action == "close_modal"


@pytest.mark.parametrize("failure,reason", [
    ("post_capture_not_new", "post_capture_not_new"),
    ("destination_mismatch", "destination_mismatch"),
    ("post_action_failure", "post_action_failure"),
])
def test_maps_confirmed_post_dispatch_failures(failure: str, reason: str) -> None:
    receipt = _adapt(failure=failure)
    assert receipt.outcome == "VERIFICATION_FAILED"
    assert receipt.reason_code == reason
    assert receipt.dispatch_status == "dispatched"
    assert receipt.effect_status == "not_verified"


@pytest.mark.parametrize("field", ["selection_ref", "candidate_ref", "gate_decision_ref", "backend_receipt_ref", "verification_ref"])
def test_rejects_missing_typed_refs(field: str) -> None:
    values = {field: ""}
    with pytest.raises(ValueError):
        _adapt(refs=_refs(**values))


def test_rejects_missing_trace_ref() -> None:
    with pytest.raises(ValueError):
        _adapt(refs=_refs(trace_refs=()))


def test_rejects_selection_intent_and_operation_lineage_mismatches() -> None:
    observation, intent, selection, operation, verification = _case()
    bad_selection = deepcopy(selection)
    bad_selection["transition_id"] = "open_apply_flow"
    with pytest.raises(ValueError, match="selection"):
        _adapt(observation=observation, intent=intent, selection=bad_selection, operation_result=operation, transition_verification=verification)
    bad_intent = intent.model_copy(update={"action_id": "runtime.safe_stop"})
    with pytest.raises(ValueError, match="intent"):
        _adapt(observation=observation, intent=bad_intent, selection=selection, operation_result=operation, transition_verification=verification)
    bad_operation = deepcopy(operation)
    bad_operation["replay_context"]["selection_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="operation"):
        _adapt(observation=observation, intent=intent, selection=selection, operation_result=bad_operation, transition_verification=verification)


def test_synthetic_safe_stop_cannot_map_existing_replay_execution() -> None:
    observation, intent, selection, operation, verification = _case()
    safe_intent = intent.model_copy(update={"action_id": "runtime.safe_stop"})
    with pytest.raises(ValueError, match="intent"):
        _adapt(observation=observation, intent=safe_intent, selection=selection, operation_result=operation, transition_verification=verification)


def test_receipt_omits_geometry_and_native_operation_payload() -> None:
    receipt = _adapt()
    encoded = str(receipt.model_dump()).casefold()
    for token in ("bbox", "click_point", "viewport", "approved_plan", "operation_result"):
        assert token not in encoded
