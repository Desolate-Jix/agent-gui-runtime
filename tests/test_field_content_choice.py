"""纯视觉空框判断共用首次焦点请求；离线传输与认证恢复。"""
from copy import deepcopy
from hashlib import sha256
import json
import sqlite3

import httpx
from PIL import Image
import pytest

from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from test_adaptive_decision_policy import context
from test_decision_choice import choice_reply, runtime
from test_native_focus_evidence import focus_payload


CONTENT_OPTIONS = ("empty", "nonempty", "uncertain")


def content_answer(choice="empty"):
    return {"type": "choice", "name": "field_content", "choice": choice, "confidence": .15,
        "probabilities": [{"value": name, "probability": value}
            for name, value in zip(CONTENT_OPTIONS, (.2, .35, .45))]}


def response(main="condition_met", content="empty"):
    value = choice_reply(main)
    value["answers"].append(content_answer(content))
    return value


def payload(clear_existing=True, *, flagged=True):
    data = focus_payload()
    data.update(decision_format="choice", enabled_predicates=[])
    data["action"].pop("focus_value_snapshot")
    if flagged:
        data["action"]["field_content_check"] = {
            "schema": "visual_field_content.v1", "clear_existing": clear_existing}
    return data


def arguments(root, clear_existing=True, *, flagged=True):
    data = payload(clear_existing, flagged=flagged)
    path = root / "captures" / "focus.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (180, 90), "white").save(path)
    return {"request_id": "content-focus", "execution_request_id": "original-input",
        "phase": data["phase"], "condition": data["condition"], "action": data["action"],
        "review_context": context(), "frames": [{"capture_id": "after-click", "role": "after",
            "sha256": sha256(path.read_bytes()).hexdigest(), "image_path": str(path),
            "window_identity": data["action"]["field"]["window_identity"]}]}


def test_provider_adds_content_question_to_same_http_without_changing_focus_choice(monkeypatch):
    monkeypatch.setenv("CONTENT_TEST_KEY", "offline-only")
    bodies = []
    def handle(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=response())
    original = payload(False)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="CONTENT_TEST_KEY", client=client)
        result = provider.judge(original)
    assert len(bodies) == 1
    assert [item["name"] for item in bodies[0]["questions"]] == ["current_step", "field_content"]
    assert [item["value"] for item in bodies[0]["questions"][1]["choices"]] == list(CONTENT_OPTIONS)
    assert "placeholder" in bodies[0]["questions"][1]["instructions"].lower()
    assert "visible keyboard-focus evidence" in bodies[0]["questions"][0]["instructions"]
    assert result["choice_result"] == response()["answers"][0]
    assert result["field_content_result"] == content_answer()
    assert original == payload(False)


@pytest.mark.parametrize("main,content,clear_existing,verdict,adopted", [
    ("condition_met", "empty", False, "success", True),
    ("condition_met", "empty", True, "success", True),
    ("condition_met", "nonempty", True, "success", True),
    ("condition_met", "nonempty", False, "failure", False),
    ("condition_met", "uncertain", True, "uncertain", False),
    ("condition_met", "uncertain", False, "uncertain", False),
    ("condition_not_met", "empty", False, "failure", False),
    ("evidence_insufficient", "empty", False, "uncertain", False),
])
def test_authenticated_content_route_reopens_without_another_dispatch(tmp_path, monkeypatch,
        main, content, clear_existing, verdict, adopted):
    args = arguments(tmp_path, clear_existing)
    profile = {"auto_conditions": [args["condition"]], "pass_threshold": 1.0}
    service, calls, client = runtime(tmp_path, monkeypatch, body=response(main, content), profile=profile)
    result = service.evaluate(**args)
    assert result["status"] == "completed" and result["verdict"] == verdict
    assert result["adopted"] is adopted
    assert result["disposition"] == ("continue" if adopted else "review_required")
    assert result["choice_result"] == response(main, content)["answers"][0]
    assert result["field_content_result"] == content_answer(content)
    assert not result["authorizes_action"] and not result["automatic_retry_allowed"]
    assert service.validate_result(result, **args)
    reopened, later, next_client = runtime(tmp_path, monkeypatch, profile=profile)
    assert reopened.evaluate(**args) == result and reopened.validate_result(result, **args)
    assert len(calls) == 1 and later == []
    for key, value in (("choice", "uncertain" if content != "uncertain" else "empty"), ("confidence", .99)):
        changed = deepcopy(result)
        changed["field_content_result"][key] = value
        assert not reopened.validate_result(changed, **args)
    changed_args = deepcopy(args)
    changed_args["action"]["field_content_check"]["clear_existing"] = not clear_existing
    assert not reopened.validate_result(result, **changed_args)
    client.close()
    next_client.close()


@pytest.mark.parametrize("profile,expected_calls", [({"mode": "shadow"}, 1),
    ({"review_policy": "always_main"}, 0), ({"auto_conditions": []}, 0)])
def test_content_cannot_bypass_shadow_policy_or_allowlist(tmp_path, monkeypatch, profile, expected_calls):
    args = arguments(tmp_path, False)
    service, calls, client = runtime(tmp_path, monkeypatch, body=response(),
        profile={"auto_conditions": [args["condition"]], **profile})
    result = service.evaluate(**args)
    assert not result["adopted"] and result["disposition"] == "review_required"
    assert len(calls) == expected_calls and service.validate_result(result, **args)
    client.close()


@pytest.mark.parametrize("fault", ["missing", "extra", "reversed", "wrong_name", "invalid_choice",
    "bool_confidence", "nan_confidence", "bad_sum", "duplicate_probability", "extra_key", "refusal"])
def test_bad_content_reply_never_continues_and_is_cached(tmp_path, monkeypatch, fault):
    body = response()
    item = body["answers"][1]
    if fault == "missing": body["answers"].pop()
    elif fault == "extra": body["answers"].append(deepcopy(item))
    elif fault == "reversed": body["answers"].reverse()
    elif fault == "wrong_name": item["name"] = "current_step"
    elif fault == "invalid_choice": item["choice"] = "probably_empty"
    elif fault == "bool_confidence": item["confidence"] = True
    elif fault == "nan_confidence": item["confidence"] = float("nan")
    elif fault == "bad_sum": item["probabilities"][0]["probability"] = .9
    elif fault == "duplicate_probability": item["probabilities"][0]["value"] = "uncertain"
    elif fault == "extra_key": item["approved"] = True
    else: body["answers"][1] = {"type": "refusal", "name": "field_content"}
    args = arguments(tmp_path)
    service, calls, client = runtime(tmp_path, monkeypatch, body=body,
        profile={"auto_conditions": [args["condition"]]})
    result = service.evaluate(**args)
    assert result["status"] == ("refused" if fault == "refusal" else "error")
    assert not result["adopted"] and result["disposition"] == "review_required"
    assert service.validate_result(result, **args)
    assert service.evaluate(**args) == result and len(calls) == 1
    client.close()


@pytest.mark.parametrize("fault", ["schema", "clear_existing", "extra_flag", "null_flag", "before_action",
    "operation", "field_phase", "focus_stage", "native_snapshot", "predicate"])
def test_illegal_content_scope_rejects_before_http(tmp_path, monkeypatch, fault):
    args = arguments(tmp_path)
    action = args["action"]
    if fault == "schema": action["field_content_check"]["schema"] = "other"
    elif fault == "clear_existing": action["field_content_check"]["clear_existing"] = 1
    elif fault == "extra_flag": action["field_content_check"]["trust"] = True
    elif fault == "null_flag": action["field_content_check"] = None
    elif fault == "before_action":
        args["phase"] = "before_action"
        args["frames"][0]["role"] = "before"
    elif fault == "native_snapshot": action["focus_value_snapshot"] = None
    elif fault != "predicate": action[fault] = "other"
    service, calls, client = runtime(tmp_path, monkeypatch,
        profile={"auto_conditions": [args["condition"]], **({"decision_format": "predicate"} if fault == "predicate" else {})})
    result = service.evaluate(**args)
    assert result["status"] == "rejected" and not result["adopted"] and calls == []
    client.close()


def test_old_request_has_one_question_and_forbids_unrequested_content_result(tmp_path, monkeypatch):
    args = arguments(tmp_path, flagged=False)
    service, calls, client = runtime(tmp_path, monkeypatch, profile={"auto_conditions": [args["condition"]]})
    result = service.evaluate(**args)
    assert result["adopted"] and "field_content_result" not in result
    assert len(json.loads(calls[0].content)["questions"]) == 1
    assert service.validate_result(result, **args)
    client.close()
    second = {**args, "request_id": "unexpected-content"}
    service, calls, client = runtime(tmp_path, monkeypatch, profile={"auto_conditions": [args["condition"]]})
    judge = service._provider.judge
    def unexpected(data):
        return {**judge(data), "field_content_result": content_answer()}
    monkeypatch.setattr(service._provider, "judge", unexpected)
    result = service.evaluate(**second)
    assert result["status"] == "error" and not result["adopted"]
    client.close()


def test_saved_content_route_is_recomputed_not_trusted(tmp_path, monkeypatch):
    from app.judgment.service import _canonical, _protect
    args = arguments(tmp_path, False)
    service, calls, client = runtime(tmp_path, monkeypatch, body=response(content="nonempty"),
        profile={"auto_conditions": [args["condition"]]})
    result = service.evaluate(**args)
    assert not result["adopted"]
    changed = {**result, "verdict": "success", "disposition": "continue", "suggested_disposition": "continue",
        "adopted": True, "reason_codes": ["decision_choice_condition_met"]}
    with sqlite3.connect(tmp_path / "judgments" / "decisions.sqlite3") as db:
        db.execute("UPDATE dispatches SET result_blob=? WHERE request_id=?",
            (_protect(_canonical(changed), service._entropy(args["request_id"])), args["request_id"]))
    assert not service.validate_result(changed, **args)
    saved = service.evaluate(**args)
    assert saved["status"] == "error" and saved["reason"] == "decision_saved_result_invalid"
    assert len(calls) == 1
    client.close()


def test_content_helper_accepts_binding_without_decision_format_and_rejects_bad_flag():
    from app.judgment.field_content_choice import (field_content_assessment, field_content_requested,
        validate_field_content_result)
    data = payload(False)
    data.pop("decision_format")
    assert field_content_requested(data)
    assert not field_content_requested({"action": None})
    data["action"]["field_content_check"]["clear_existing"] = "false"
    with pytest.raises(ValueError):
        field_content_requested(data)
    profile = DecisionProfile(contract_version="decision_profile.v2", mode="auto", decision_format="choice")
    decision = field_content_assessment(profile, "condition_met", content_answer("nonempty"), clear_existing=False)
    assert decision["verdict"] == "failure" and decision["disposition"] == "review_required" and not decision["adopted"]
    with pytest.raises(ValueError):
        validate_field_content_result({**content_answer(), "confidence": float("inf")})
