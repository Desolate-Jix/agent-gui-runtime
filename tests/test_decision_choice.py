"""三选一采用合同；只用离线传输与真实认证账本。"""
from copy import deepcopy
import json

import httpx
import pytest

from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from test_adaptive_decision_policy import context
from test_decision_service import arguments


OPTIONS = ("condition_met", "condition_not_met", "evidence_insufficient")


def choice_reply(choice="condition_met", confidence=0.2):
    return {"model": "gpt-6-luna", "answers": [{"type": "choice", "name": "current_step",
        "choice": choice, "confidence": confidence,
        "probabilities": [{"value": value, "probability": p} for value, p in zip(OPTIONS, (0.2, 0.35, 0.45))]}],
        "usage": {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12}}


def runtime(root, monkeypatch, *, body=None, profile=None, handler=None):
    monkeypatch.setenv("CHOICE_TEST_KEY", "synthetic-choice-secret")
    calls = []
    def handle(request):
        calls.append(request)
        return handler(request) if handler else httpx.Response(200, json=body or choice_reply())
    client = httpx.Client(transport=httpx.MockTransport(handle))
    config = {"contract_version": "decision_profile.v2", "mode": "auto", "decision_format": "choice",
        "api_key_env": "CHOICE_TEST_KEY", "auto_conditions": ["\u8be6\u60c5\u5df2\u6253\u5f00"], **(profile or {})}
    service = DecisionService(root, profile=DecisionProfile.model_validate(config),
        provider=OpenAIDecisionsProvider(api_key_env="CHOICE_TEST_KEY", client=client))
    return service, calls, client


def test_choice_profile_omission_keeps_legacy_serialization_and_v1_rejects_new_field():
    old = DecisionProfile(contract_version="decision_profile.v2")
    assert old.decision_format == "predicate"
    assert "decision_format" not in old.model_dump(mode="json")
    assert DecisionProfile(contract_version="decision_profile.v2", decision_format="predicate").model_dump()["decision_format"] == "predicate"
    with pytest.raises(ValueError):
        DecisionProfile(decision_format="choice")


@pytest.mark.parametrize("choice,verdict,adopted", [
    ("condition_met", "success", True), ("condition_not_met", "failure", False),
    ("evidence_insufficient", "uncertain", False)])
def test_single_choice_drives_outcome_without_probability_threshold_or_observation(tmp_path, monkeypatch, choice, verdict, adopted):
    service, calls, client = runtime(tmp_path, monkeypatch, body=choice_reply(choice),
        profile={"pass_threshold": 1.0, "after_action_review_threshold": 0.01})
    args = arguments(tmp_path, review_context=context(wait_policy={"loading_condition": "Loading visible", "completion_excludes_loading": True}))
    result = service.evaluate(**args)
    assert result["status"] == "completed" and result["verdict"] == verdict
    assert result["adopted"] is adopted
    assert result["disposition"] == ("continue" if adopted else "review_required")
    assert result["decision_format"] == "choice"
    assert result["choice_result"] == choice_reply(choice)["answers"][0]
    assert result["enabled_predicates"] == [] and result["predicates"] == {} and result["probabilities"] == {}
    assert not result["authorizes_action"] and not result["automatic_retry_allowed"]
    assert service.validate_result(result, **args)
    assert service.evaluate(**args) == result and len(calls) == 1
    body = json.loads(calls[0].content)
    assert len(body["questions"]) == 1 and body["questions"][0]["type"] == "choice"
    instructions = body["questions"][0]["instructions"]
    assert args["condition"] in instructions and "current" in instructions and "obstacle" in instructions
    assert "needs_agent_review" not in json.dumps(body["questions"])
    changed = deepcopy(result)
    changed["choice_result"]["choice"] = "condition_not_met" if choice != "condition_not_met" else "condition_met"
    assert not service.validate_result(changed, **args)
    client.close()


@pytest.mark.parametrize("mutation", [
    lambda r: r["answers"][0].update(name="unbound"),
    lambda r: r["answers"][0].update(choice="maybe"),
    lambda r: r["answers"][0].update(confidence=True),
    lambda r: r["answers"][0].update(confidence=float("nan")),
    lambda r: r["answers"][0].update(probabilities={"condition_met": 1}),
    lambda r: r["answers"][0]["probabilities"][0].update(probability=0.9),
    lambda r: r["answers"][0]["probabilities"][0].update(probability=-0.1),
    lambda r: r["answers"].append(deepcopy(r["answers"][0])),
    lambda r: r["answers"][0].update(probability=1.0),
])
def test_malformed_choice_is_review_only_and_never_falls_back(tmp_path, monkeypatch, mutation):
    body = choice_reply()
    mutation(body)
    service, calls, client = runtime(tmp_path, monkeypatch, body=body)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result["status"] == "error" and result["disposition"] == "review_required"
    assert not result["adopted"] and result["verdict"] == "uncertain"
    assert service.evaluate(**args) == result and len(calls) == 1
    client.close()


@pytest.mark.parametrize("profile,expected_calls", [({"mode": "shadow"}, 1),
    ({"review_policy": "always_main"}, 0), ({"auto_conditions": []}, 0)])
def test_choice_keeps_shadow_always_main_and_local_allowlist(tmp_path, monkeypatch, profile, expected_calls):
    service, calls, client = runtime(tmp_path, monkeypatch, profile=profile)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert not result["adopted"] and result["disposition"] == "review_required"
    assert len(calls) == expected_calls and service.validate_result(result, **args)
    client.close()


@pytest.mark.parametrize("kind", ["refusal", "timeout", "transport", "binding"])
def test_choice_refusal_error_and_timeout_hand_off_once(tmp_path, monkeypatch, kind):
    body = choice_reply()
    if kind == "refusal":
        body["answers"] = [{"type": "refusal", "name": "current_step"}]
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("offline", request=request)
        if kind == "transport":
            raise httpx.ConnectError("offline", request=request)
        return httpx.Response(200, json=body)
    service, calls, client = runtime(tmp_path, monkeypatch, handler=handler)
    if kind == "binding":
        original = service._provider.judge
        def wrong_binding(payload):
            result = original(payload)
            result["request_sha256"] = "0" * 64
            return result
        monkeypatch.setattr(service._provider, "judge", wrong_binding)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result["status"] == {"refusal": "refused", "timeout": "timeout"}.get(kind, "error")
    assert result["verdict"] == "uncertain" and not result["adopted"] and result["disposition"] == "review_required"
    assert service.validate_result(result, **args)
    assert service.evaluate(**args) == result and len(calls) == 1
    client.close()


def test_choice_reopens_authenticated_result_and_cannot_reinterpret_predicate_receipt(tmp_path, monkeypatch):
    from test_adaptive_decision_policy import service as predicate_runtime
    old, old_calls, old_client = predicate_runtime(tmp_path, monkeypatch)
    args = arguments(tmp_path, review_context=context())
    old_result = old.evaluate(**args)
    service, calls, client = runtime(tmp_path, monkeypatch)
    assert not service.validate_result(old_result, **args)
    assert service.evaluate(**args)["status"] == "conflict" and not calls
    fresh = {**args, "request_id": "new-choice"}
    result = service.evaluate(**fresh)
    reopened, subsequent, next_client = runtime(tmp_path, monkeypatch)
    assert reopened.evaluate(**fresh) == result and reopened.validate_result(result, **fresh)
    assert len(calls) == 1 and not subsequent and len(old_calls) == 1
    old_client.close()
    client.close()
    next_client.close()


@pytest.mark.parametrize("bad", ["image_hash", "missing_context", "expired_budget"])
def test_choice_still_requires_local_evidence_context_and_deadline_before_dispatch(tmp_path, monkeypatch, bad):
    service, calls, client = runtime(tmp_path, monkeypatch)
    args = arguments(tmp_path, review_context=context())
    if bad == "image_hash":
        args["frames"][0]["sha256"] = "0" * 64
    elif bad == "missing_context":
        args.pop("review_context")
    else:
        args["request_budget_seconds"] = 0
    result = service.evaluate(**args)
    assert result["disposition"] == "review_required" and not result["adopted"] and not calls
    client.close()


@pytest.mark.parametrize("stage", ["after_click", "after_selection", "value", "before_action"])
def test_choice_reuses_current_field_and_candidate_semantics_without_auxiliary_questions(monkeypatch, stage):
    from tests.test_native_focus_evidence import focus_payload
    from tests.test_visual_value_decision import visual_value_payload
    from tests.test_decision_current_step_scope import scoped_payload
    from app.execution.visual_field_proof import VISUAL_SELECTION_CONDITION
    monkeypatch.setenv("CHOICE_TEST_KEY", "synthetic-choice-secret")
    if stage == "value":
        data = visual_value_payload()
    elif stage == "before_action":
        data = scoped_payload("before_action")
    else:
        data = focus_payload()
        data["action"].pop("focus_value_snapshot")
        data["action"]["focus_stage"] = stage
        if stage == "after_selection":
            data["condition"] = VISUAL_SELECTION_CONDITION
    data.update(decision_format="choice", enabled_predicates=[])
    original = deepcopy(data)
    bodies = []
    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=choice_reply())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="CHOICE_TEST_KEY", client=client)
        assert provider.judge(data)["choice_result"]["choice"] == "condition_met"
    assert data == original and len(bodies) == 1 and len(bodies[0]["questions"]) == 1
    question = bodies[0]["questions"][0]
    assert question["name"] == "current_step" and [item["value"] for item in question["choices"]] == list(OPTIONS)
    text = question["instructions"]
    expected = {"after_click": "visible keyboard-focus evidence", "after_selection": "no selection highlight is required",
        "value": "comparison target, not an observed value", "before_action": "do not require its effects or later plan results"}
    assert expected[stage] in text
    assert "Current related blocker" in text
