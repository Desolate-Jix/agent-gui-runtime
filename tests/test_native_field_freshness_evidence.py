"""双帧字段检查必须解释已绑定原生事实，坏绑定不能进入 HTTP。"""
from copy import deepcopy
from hashlib import sha256
import json

import httpx
import pytest

from app.execution.visual_field_proof import VISUAL_FIELD_FRESHNESS_CONDITION
from app.judgment import OpenAIDecisionsProvider
from tests.test_native_focus_evidence import focus_payload, wire


def freshness_payload():
    payload = focus_payload()
    before = payload["action"].pop("focus_value_snapshot")
    current = deepcopy(before)
    current.update(capture_id="current", read_id="read-two", observed_at_ns=200)
    payload["frames"] = [dict(payload["frames"][0], role="before"),
        dict(payload["frames"][0], role="after", capture_id="current")]
    payload["condition"] = VISUAL_FIELD_FRESHNESS_CONDITION
    payload["action"].update(focus_stage="before_keyboard_freshness", field_freshness_context={
        "schema": "visual_field_freshness.v1", "changed_region": {"x": 40, "y": 22, "w": 1, "h": 16},
        "original_condition": "original", "prior_request_sha256": "b" * 64,
        "prior_assessment_sha256": "c" * 64,
        "native_before_snapshot": before, "native_current_snapshot": current})
    return payload


def test_bound_pair_explains_native_facts_without_overriding_condition(wire):
    provider, bodies = wire
    payload = freshness_payload()
    provider.judge(payload)
    intro = bodies[0]["input"][0]["content"][0]["text"]
    assert "native_before_snapshot" in intro and "native_current_snapshot" in intro
    assert "not permission" in intro
    assert payload["condition"] in bodies[0]["questions"][0]["instructions"]
    assert "Refuse if the condition needs temporal evidence" not in bodies[0]["questions"][0]["instructions"]
    action_text = next(part["text"] for part in bodies[0]["input"][0]["content"]
        if part.get("text", "").startswith("Proposed action context"))
    assert json.loads(action_text.split(": ", 1)[1]) == payload["action"]


@pytest.mark.parametrize("phase", ["focus", "value"])
def test_only_bound_freshness_uses_native_continuity_question(wire, phase):
    provider, bodies = wire
    payload = freshness_payload()
    action = payload["action"]
    action["field_phase"] = phase
    if phase == "value":
        text = action["field"]["expected_text"]
        for key in ("native_before_snapshot", "native_current_snapshot"):
            action["field_freshness_context"][key].update(
                value_sha256=sha256(text.encode("utf-8")).hexdigest(), value_length=len(text))
    provider.judge(payload)
    question = bodies[0]["questions"][0]["instructions"]
    assert "native identity, value and selection" in question
    assert "do not repeat character-by-character OCR" in question
    assert "changed_region" in question and "keyboard effect" in question
    assert "Refuse if the supplied evidence is insufficient" in question
    assert payload["condition"] in question
    assert question.endswith(action["field_freshness_context"]["original_condition"])


def test_native_freshness_does_not_raise_model_probability(monkeypatch):
    monkeypatch.setenv("NATIVE_FRESHNESS_TEST_KEY", "offline-only")
    def handle(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": q["name"], "probability": .76 if q["name"] == "condition_met" else 0.0}
            for q in body["questions"]], "usage": {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="NATIVE_FRESHNESS_TEST_KEY", client=client)
        result = provider.judge(freshness_payload())
    assert result["predicates"]["condition_met"] == {"type": "predicate", "probability": .76}


@pytest.mark.parametrize("fault", ["identity", "capture", "time", "read", "value", "selection", "region", "condition"])
def test_invalid_pair_refuses_before_http(wire, fault):
    provider, bodies = wire
    payload = freshness_payload()
    context = payload["action"]["field_freshness_context"]
    current = context["native_current_snapshot"]
    if fault == "identity": current["identity"]["runtime_id"] = [42, 2]
    elif fault == "capture": current["capture_id"] = "wrong"
    elif fault == "time": current["observed_at_ns"] = 100
    elif fault == "read": current["read_id"] = "read-one"
    elif fault == "value": current["value_sha256"] = "0" * 64
    elif fault == "selection": current["selection"] = [0, 3]
    elif fault == "region": context["changed_region"]["x"] = 160
    else: payload["condition"] = "Anything is allowed"
    with pytest.raises(ValueError, match="decision_native_field_freshness_invalid"):
        provider.judge(payload)
    assert bodies == []
