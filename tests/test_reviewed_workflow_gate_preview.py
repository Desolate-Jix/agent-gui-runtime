from copy import deepcopy

import pytest

from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.reviewed_workflow_replay import (
    resolve_current_state, select_transition_for_review, validate_current_grounding,
    validate_review_grounding_preview,
)
from tests.test_reviewed_workflow_asset_v2 import _asset
from tests.test_reviewed_workflow_gate_w4 import _recognition_inputs
from tests.test_reviewed_workflow_replay_v2 import _observation, _grounding, _selection


def _inputs(requires_confirmation=False):
    asset = _asset()
    transition = next(item for item in asset["transitions"] if item["transition_id"] == "open_detail")
    transition["risk_policy"]["requires_user_confirmation"] = requires_confirmation
    if requires_confirmation:
        transition["risk_policy"]["automatic_execution_allowed"] = False
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")
    selection = select_transition_for_review(asset, resolve_current_state(asset, observation),
        transition_id="open_detail", current_observation=observation)
    candidates, local = _recognition_inputs()
    return asset, dict(selection=selection, grounding=_grounding(asset), candidates=candidates, local_grounding=local)


@pytest.mark.parametrize("requires_confirmation", [False, True])
def test_production_gate_has_distinct_review_path_without_execution_authority(requires_confirmation):
    asset, inputs = _inputs(requires_confirmation)
    adapter = ReviewedWorkflowGateAdapter()
    decision = adapter.evaluate_review(**inputs)
    assert decision["allowed"] is True
    assert decision["selection_sha256"] == inputs["selection"]["review_selection_sha256"]
    preview = validate_review_grounding_preview(asset, inputs["selection"], inputs["grounding"], decision,
        policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
    assert preview["status"] == "validated"
    assert adapter.evaluate(**inputs)["allowed"] is False
    assert validate_current_grounding(asset, inputs["selection"], inputs["grounding"], decision,
        policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})["status"] != "validated"


@pytest.mark.parametrize("field,value", [
    ("contract_version", "verified_transition_selection_v1"), ("review_only", False),
    ("grants_action_authority", True), ("execute_binding_enabled", True),
    ("artifact_is_authorization", True), ("selection_sha256", "0" * 64),
    ("review_selection_sha256", "1" * 64), ("target_state_id", "different"),
])
def test_review_gate_rejects_forged_review_contract(field, value):
    _, inputs = _inputs()
    inputs["selection"][field] = value
    assert ReviewedWorkflowGateAdapter().evaluate_review(**inputs)["allowed"] is False


def test_review_gate_does_not_accept_execution_selection():
    _, inputs = _inputs()
    inputs["selection"] = _selection()
    assert ReviewedWorkflowGateAdapter().evaluate_review(**inputs)["allowed"] is False


@pytest.mark.parametrize("field,value", [
    ("capture_id", "wrong-capture"), ("candidate_id", "wrong-candidate"),
    ("bbox", {"x": 101, "y": 200, "w": 300, "h": 80}),
    ("click_point", {"x": 221, "y": 240}),
])
def test_review_gate_keeps_real_local_evidence_binding(field, value):
    _, inputs = _inputs()
    inputs["grounding"][field] = value
    assert ReviewedWorkflowGateAdapter().evaluate_review(**inputs)["allowed"] is False


def test_review_gate_preserves_policy_rejection():
    _, inputs = _inputs()
    inputs["candidates"], inputs["local_grounding"] = _recognition_inputs(policy_allowed=False)
    assert ReviewedWorkflowGateAdapter().evaluate_review(**inputs)["allowed"] is False


@pytest.mark.parametrize("requires_confirmation", [False, True])
def test_review_preflight_uses_real_evidence_adapter_and_gate_with_synthetic_capture(tmp_path, requires_confirmation):
    from hashlib import sha256
    from tests.test_live_runtime_composition_w3b import _adapter

    asset = _asset()
    transition = next(item for item in asset["transitions"] if item["transition_id"] == "open_detail")
    transition["risk_policy"]["requires_user_confirmation"] = requires_confirmation
    if requires_confirmation:
        transition["risk_policy"]["automatic_execution_allowed"] = False
    adapter, _, screenshot, _, _ = _adapter(tmp_path, asset)
    current = adapter.capture_current(session_id="session.review-adapter", asset=asset, target_window_handle=4242)
    assert current["screenshot_sha256"] == sha256(screenshot.paths[0].read_bytes()).hexdigest()
    selection = select_transition_for_review(asset, resolve_current_state(asset, current),
        transition_id="open_detail", current_observation=current)
    resolved = adapter.resolve(session_id="session.review-adapter", selection=selection, current_observation=current)
    assert resolved["status"] == "resolved"
    gate = ReviewedWorkflowGateAdapter().evaluate_review(selection=selection,
        grounding=resolved["grounding"], **resolved["gate_context"])
    preview = validate_review_grounding_preview(asset, selection, resolved["grounding"], gate,
        policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
    assert preview["status"] == "validated", preview
    assert preview["candidate_id"] == resolved["grounding"]["candidate_id"]
    assert preview["bbox"] == resolved["grounding"]["bbox"]
    assert preview["click_point"] == resolved["grounding"]["click_point"]
