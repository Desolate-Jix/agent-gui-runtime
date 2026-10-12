"""结果判断仅上传当前步骤证据，完整任务绑定仍由服务保存。"""
from copy import deepcopy
import json

import httpx
import pytest

from app.judgment import OpenAIDecisionsProvider
from tests.test_native_field_freshness_evidence import freshness_payload
from tests.test_native_focus_evidence import focus_payload
from tests.test_native_value_evidence import value_payload
from tests.test_openai_decisions import observation_payload, payload


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setenv("CURRENT_STEP_TEST_KEY", "offline-only")
    bodies = []

    def handle(request):
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": item["name"],
                "probability": .97 if item["name"] == "condition_met" else .01}
            for item in body["questions"]],
            "usage": {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        yield OpenAIDecisionsProvider(api_key_env="CURRENT_STEP_TEST_KEY", client=client), bodies


def scoped_payload(phase="after_action"):
    danger = "unsafe_effect" if phase == "before_action" else "visible_error"
    return {**payload(), "phase": phase, "condition": "The requested result page is open.",
        "schema_version": "decision_request.v2",
        "enabled_predicates": ["condition_met", danger, "needs_agent_review"],
        "review_context": {"goal": "HISTORICAL_GLOBAL_GOAL", "step_goal": json.dumps({
            "action": {"goal": "PRIOR_FIELD_VALUE_GOAL"}, "verification": "OLD_VERIFICATION_CONDITION"}),
            "remaining_plan": ["FUTURE_ACTION_SEQUENCE"], "allowed_states": ["FUTURE_ALLOWED_STATE"]},
        "action": {"operation": "result_check", "kind": "click", "click_point": {"x": 4, "y": 5},
            "goal": "HISTORICAL_ACTION_GOAL", "remaining_plan": ["ACTION_FUTURE_SEQUENCE"],
            "freshness_context": {"review_context": {"goal": "NESTED_HISTORICAL_GOAL"}}}}


def test_after_action_does_not_upload_plan_history_through_context_or_action(wire):
    provider, bodies = wire
    data = scoped_payload()
    original = deepcopy(data)
    result = provider.judge(data)
    sent = json.dumps(bodies[0])
    for marker in ("HISTORICAL_GLOBAL_GOAL", "PRIOR_FIELD_VALUE_GOAL", "OLD_VERIFICATION_CONDITION",
            "FUTURE_ACTION_SEQUENCE", "FUTURE_ALLOWED_STATE", "HISTORICAL_ACTION_GOAL",
            "ACTION_FUTURE_SEQUENCE", "NESTED_HISTORICAL_GOAL"):
        assert marker not in sent
    assert data["condition"] in bodies[0]["questions"][0]["instructions"]
    assert result["request_sha256"] == data["request_sha256"]
    assert data == original


def test_before_action_keeps_original_full_scoped_context_and_action(wire):
    provider, bodies = wire
    data = scoped_payload("before_action")
    provider.judge(data)
    texts = [part["text"] for part in bodies[0]["input"][0]["content"] if part["type"] == "input_text"]
    assert json.loads(next(text.split(": ", 1)[1] for text in texts
        if text.startswith("Frozen scoped task"))) == data["review_context"]
    assert json.loads(next(text.split(": ", 1)[1] for text in texts
        if text.startswith("Proposed action context"))) == data["action"]
    assert "before the specified original current action can safely proceed" in bodies[0]["questions"][2]["instructions"]


@pytest.mark.parametrize("observation", [False, True])
def test_after_review_only_asks_about_current_result_obstacles(wire, observation):
    provider, bodies = wire
    data = observation_payload() if observation else scoped_payload()
    provider.judge(data)
    questions = {item["name"]: item["instructions"] for item in bodies[0]["questions"]}
    question = questions["needs_agent_review"]
    assert "current declared condition" in question
    assert "ambiguity" in question and "occlusion" in question and "error" in question
    assert "Ordinary navigation, links and optional buttons" in question
    assert "remaining plan" not in question and "allowed_states" not in question
    assert "off-plan" not in question and "extra choice" not in question
    if observation:
        assert "observation" in question
        assert "Record loading indicator visible" in questions["still_progressing"]


@pytest.mark.parametrize("factory", [focus_payload, value_payload, freshness_payload])
def test_current_native_field_evidence_and_special_question_are_preserved(wire, factory):
    provider, bodies = wire
    data = factory()
    data["review_context"] = scoped_payload()["review_context"]
    original = deepcopy(data)
    result = provider.judge(data)
    texts = [part["text"] for part in bodies[0]["input"][0]["content"] if part["type"] == "input_text"]
    action = json.loads(next(text.split(": ", 1)[1] for text in texts
        if text.startswith("Proposed action context")))
    assert action == data["action"]
    assert "Given the bound native" in bodies[0]["questions"][0]["instructions"] or (
        "Given the two bound native reads" in bodies[0]["questions"][0]["instructions"])
    assert "HISTORICAL_GLOBAL_GOAL" not in " ".join(texts)
    assert result["predicates"]["condition_met"]["probability"] == .97
    assert data == original


def test_field_projection_drops_unrelated_nested_history_without_changing_target(wire):
    provider, bodies = wire
    data = focus_payload()
    data["action"].pop("focus_value_snapshot")
    data["action"]["field"]["review_context"] = {"goal": "FIELD_HISTORY_LEAK"}
    data["action"]["field"]["remaining_plan"] = ["FIELD_FUTURE_LEAK"]
    provider.judge(data)
    sent = json.dumps(bodies[0])
    assert "FIELD_HISTORY_LEAK" not in sent and "FIELD_FUTURE_LEAK" not in sent
    assert data["action"]["field"]["field_goal"] in sent
    assert data["action"]["field"]["expected_text"] not in sent
