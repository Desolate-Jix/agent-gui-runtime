"""真实动作路由的离线合并审核；桌面和供应商仅在边界替换。"""
from copy import deepcopy
from time import perf_counter_ns

import pytest
from PIL import ImageDraw

from tests.test_agent_grounding_target import scene
from tests.test_execution_decision_check import run_route
from tests.test_action_review_contract import Provider
from app.execution import action_review as review
from app.judgment.profile import DecisionProfile
from app.judgment.service import DecisionService


def context():
    return {"schema": "action_review_context.v1", "run_id": "task-1", "attempt_id": "attempt-1",
        "step_id": "search", "budget_ms": 5000, "plan": {"schema_version": "task_plan.v2",
        "title": "Search Java documentation", "inputs": {}, "steps": [{"step_id": "search",
        "action": {"kind": "click", "goal": "Search"}, "verification": {"kind": "agent_judgment"}}]}}


def route(scene, monkeypatch, *, mutate=None, deny=False, cancelled=None):
    monkeypatch.setattr("app.judgment.service._protect", lambda data, entropy, decrypt=False: data)
    provider = Provider()
    original = provider.judge
    def judge(payload):
        result = original(payload)
        if deny:
            result["predicates"]["needs_agent_review"]["probability"] = .99
        if mutate:
            mutate()
        return result
    provider.judge = judge
    service = DecisionService(scene[3], provider=provider,
        profile=DecisionProfile(contract_version="decision_profile.v2", mode="auto",
            auto_conditions=[review.CANDIDATE_CONDITION, review.FRESHNESS_CONDITION], request_cap=3))
    with review.action_review_scope(service, context=context(), cancelled=cancelled,
            deadline_ns=perf_counter_ns()+5_000_000_000):
        result = run_route(scene, monkeypatch, service, condition=review.CANDIDATE_CONDITION)
    return result, provider


def test_dom_overlay_enters_same_candidate_review(scene, monkeypatch):
    result, provider = route(scene, monkeypatch)
    receipt, clicks = result[:2]
    assert receipt.success, receipt
    assert clicks == [(65, 55)]
    assert len(provider.calls) == 1
    assert provider.calls[0]["review_context"]["goal"] == "Search Java documentation"
    assert receipt.data["result"]["action_assessment"]["scope"] == "candidate"


def test_combined_review_denial_has_zero_dispatch(scene, monkeypatch):
    result, provider = route(scene, monkeypatch, deny=True)
    receipt, clicks = result[:2]
    assert not receipt.success and clicks == []
    assert receipt.data["dispatch_status"] == "not_dispatched"
    assert len(provider.calls) == 1


def test_cancelled_model_result_does_not_click(scene, monkeypatch):
    cancelled = [False]
    result, _ = route(scene, monkeypatch, mutate=lambda: cancelled.__setitem__(0, True),
        cancelled=lambda: cancelled[0])
    assert not result[0].success and result[1] == []


def test_mutated_reviewed_source_file_does_not_click(scene, monkeypatch):
    def change():
        ImageDraw.Draw(scene[2]).rectangle((30, 40, 100, 70), fill="red")
        scene[2].save(scene[3] / "current.png")
    result, _ = route(scene, monkeypatch, mutate=change)
    assert not result[0].success and result[1] == []


@pytest.mark.parametrize("attribute", ["handle", "process_id"])
def test_dispatch_validator_freezes_mutable_window_identity(tmp_path, monkeypatch, attribute):
    from types import SimpleNamespace
    from tests.test_action_review_contract import _review
    from app.execution.action_review_dispatch import review_original_action
    from app.execution.decision_check import DecisionCheckRejected
    mod, service, _, args = _review(tmp_path, monkeypatch)
    bound = SimpleNamespace(handle=10, process_id=20,
        rect=SimpleNamespace(left=0, top=0, right=200, bottom=150))
    ctx = {"schema": "action_review_context.v1", "run_id": "run-1",
        "attempt_id": "attempt-1", "step_id": "open", "budget_ms": 5000, "plan": args["plan"]}
    with mod.action_review_scope(service, context=ctx, deadline_ns=args["deadline_ns"]):
        reviewed = review_original_action(capture=args["capture"], identity=args["identity"],
            candidate=args["candidate"], point=args["candidate"]["click_point"],
            goal="Address bar", click_kind="single", manager=SimpleNamespace(get_bound_window=lambda: bound),
            validate_binding=lambda: (args["identity"], args["candidate"]))
        setattr(bound, attribute, getattr(bound, attribute) + 1)
        with pytest.raises(DecisionCheckRejected, match="action_review_window_changed"):
            reviewed["validate"]()
