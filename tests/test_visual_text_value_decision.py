"""输入后只比较指定文本，焦点与其他流程不能混入本次 Choice。"""
from copy import deepcopy
import json

import httpx
import pytest

from app.judgment import OpenAIDecisionsProvider
from test_decision_choice import choice_reply
from test_visual_value_decision import visual_value_payload


TEXT_CONDITION = "The target field displays exactly the specified expected text."


@pytest.mark.parametrize("choice", ["condition_met", "condition_not_met", "evidence_insufficient"])
def test_text_only_choice_and_original_classification(monkeypatch, choice):
    monkeypatch.setenv("TEXT_VALUE_TEST_KEY", "offline-only")
    bodies = []
    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=choice_reply(choice))
    payload = visual_value_payload()
    payload.update(condition=TEXT_CONDITION, decision_format="choice", enabled_predicates=[])
    original = deepcopy(payload)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="TEXT_VALUE_TEST_KEY", client=client)
        result = provider.judge(payload)
    assert payload == original and result["choice_result"]["choice"] == choice
    assert len(bodies) == 1 and len(bodies[0]["questions"]) == 1
    question = bodies[0]["questions"][0]
    assert question["type"] == "choice"
    assert "exactly" in question["instructions"]
    assert "expected_text" in question["instructions"]
    text = json.dumps(question).lower()
    for removed in ("focus", "feasibility", "blocker", "navigation", "keyboard", "safe continuation"):
        assert removed not in text
    content = [p["text"] for p in bodies[0]["input"][0]["content"] if p["type"] == "input_text"]
    assert all("focus redirection" not in t for t in content)
    assert "comparison target" in " ".join(content)


def test_pure_visual_producer_uses_text_condition(tmp_path):
    from test_executed_click_integration import arguments
    request = arguments(tmp_path, phase="value")
    assert request["condition"] == TEXT_CONDITION
    assert request["action"]["value_verification"] == "visual"


def test_visual_example_allows_new_condition_without_rewriting_legacy():
    from pathlib import Path
    from app.judgment.profile import load_decision_profile
    from app.judgment.visual_action_conditions import VISUAL_VALUE_CONDITION
    profile = load_decision_profile(Path("configs/decision-profile.visual-execution.example.json"))
    assert TEXT_CONDITION in profile.auto_conditions
    assert VISUAL_VALUE_CONDITION in profile.auto_conditions
