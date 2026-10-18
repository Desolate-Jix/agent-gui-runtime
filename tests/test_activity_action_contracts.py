"""启停活动的语义必须如实传递，且不能因可逆而绕过独立确认。"""
from types import SimpleNamespace

import pytest

from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset
from app.agent.reviewed_workflow_replay import (
    resolve_current_state, select_transition_for_review, select_verified_transition,
)
from app.agent.runtime_contracts import AgentAvailableActionV1
from app.desktop_review.single_step_coordinator import _actions
from tests.test_reviewed_workflow_asset_v2 import _asset
from tests.test_reviewed_workflow_replay_v2 import _observation


def _action(semantic):
    return {"action_id": "activity.transition", "semantic_action": semantic,
            "description": "Change the reviewed activity state.", "target_state_id": "detail",
            "expected_effect": "The reviewed destination state is visible.",
            "verification_rule_refs": ["rule:destination"], "risk_level": "medium",
            "requires_user_confirmation": True}


def _activity_asset(semantic):
    asset = _asset()
    transition = asset["transitions"][0]
    transition["semantic_action"] = semantic
    transition["risk_policy"].update(risk_level="medium", requires_user_confirmation=True,
                                     automatic_execution_allowed=False)
    return asset


@pytest.mark.parametrize("semantic", ["start_activity", "stop_activity"])
def test_activity_action_keeps_truthful_semantics(semantic):
    result = AgentAvailableActionV1.model_validate(_action(semantic))
    assert result.semantic_action == semantic
    assert result.requires_user_confirmation is True


@pytest.mark.parametrize("semantic", ["start_activity", "stop_activity"])
@pytest.mark.parametrize("change", [{"risk_level": "low"}, {"requires_user_confirmation": False}])
def test_activity_action_rejects_lowered_confirmation_policy(semantic, change):
    payload = _action(semantic) | change
    with pytest.raises(ValueError, match="requires user confirmation|risk must be medium or high"):
        AgentAvailableActionV1.model_validate(payload)


@pytest.mark.parametrize("semantic", ["start_activity", "stop_activity"])
def test_reviewed_activity_allows_preview_but_no_execution_without_confirmation(semantic):
    asset = validate_reviewed_workflow_asset(_activity_asset(semantic))
    current = _observation(asset, "capture-activity", "c" * 64, "anchor_homepage", "job_card")
    resolution = resolve_current_state(asset, current)
    preview = select_transition_for_review(asset, resolution, transition_id="open_detail", current_observation=current)
    assert preview["status"] == "selected"
    assert preview["semantic_action"] == semantic
    assert preview["requires_user_confirmation"] is True
    assert preview["grants_action_authority"] is False
    selected = select_verified_transition(asset, resolution, transition_id="open_detail", current_observation=current)
    assert selected["status"] == "blocked"
    assert selected["failure_code"] == "human_review_required"


@pytest.mark.parametrize("semantic", ["start_activity", "stop_activity"])
@pytest.mark.parametrize("change", [{"risk_level": "low"}, {"requires_user_confirmation": False}])
def test_reviewed_activity_rejects_lowered_confirmation_policy(semantic, change):
    asset = _activity_asset(semantic)
    asset["transitions"][0]["risk_policy"].update(change)
    with pytest.raises(ValueError, match="activity.*confirmation|activity.*medium"):
        validate_reviewed_workflow_asset(asset)


def test_desktop_single_step_lists_reviewed_activity_not_runtime_safe_stop_or_final_actions():
    raw = [SimpleNamespace(**_action(semantic), marker=semantic) for semantic in (
        "start_activity", "stop_activity", "safe_stop", "final_submit", "send", "payment")]
    for index, item in enumerate(raw):
        item.action_id = f"action-{index}"
    actual = _actions(raw)
    assert [item["semantic_action"] for item in actual] == ["start_activity", "stop_activity"]
