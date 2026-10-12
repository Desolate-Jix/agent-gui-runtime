"""新配置默认主动审核；无 API 时保留本地核验与原会话交接。"""
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from app.core.decision_configuration import create_session_decision_service
from app.judgment import OpenAIDecisionsProvider
from tests.test_openai_decisions import reply
from tests.test_task_plan_adaptive_review import CONDITION, adaptive_plan, review_request
from tests.test_task_plan_contract import plan
from tests.test_task_plan_runner import complete_original, scene


def configured_scene(tmp_path, monkeypatch, *, profile=None, review=0.01, native=False, key=True):
    requests = []

    def respond(request):
        requests.append(request)
        body = reply(0.97, 0.01)
        questions = json.loads(request.content)["questions"]
        if questions[0]["type"] == "choice":
            selected = "evidence_insufficient" if review > .7 else "condition_met"
            body["answers"] = [{"type": "choice", "name": "current_step", "choice": selected,
                "confidence": .19, "probabilities": [
                    {"value": label, "probability": .34 if label == selected else .33}
                    for label in ("condition_met", "condition_not_met", "evidence_insufficient")]}]
            return httpx.Response(200, json=body)
        body["answers"][1]["name"] = questions[1]["name"]
        if any(item["name"] == "needs_agent_review" for item in questions):
            body["answers"].append({"type": "predicate", "name": "needs_agent_review", "probability": review})
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    monkeypatch.setattr("app.judgment.service.OpenAIDecisionsProvider",
        lambda **kwargs: OpenAIDecisionsProvider(client=client, **kwargs))
    monkeypatch.delenv("AGENT_GUI_DECISION_PROFILE", raising=False)
    monkeypatch.delenv("DEFAULT_ROUTING_TEST_KEY", raising=False)
    if key:
        monkeypatch.setenv("DEFAULT_ROUTING_TEST_KEY", "synthetic-test-key")
    profile_path = None
    if profile is not None:
        payload = {**deepcopy(profile), "api_key_env": "DEFAULT_ROUTING_TEST_KEY"}
        profile_path = tmp_path / "profile.json"
        profile_path.write_text(json.dumps(payload), encoding="utf-8")
    root = tmp_path / "session"
    root.mkdir()
    service = create_session_decision_service(root, profile_path=profile_path)
    source = plan() if native else adaptive_plan()
    source["schema_version"] = "task_plan.v2"
    state = scene(root, monkeypatch, source=source, decision=service)
    return state, service, requests, client


@pytest.mark.parametrize("source", ["minimal-v2", "decision-profile.example.json", "decision-profile.adaptive.example.json", "decision-profile.visual-execution.example.json"])
@pytest.mark.parametrize("needs_review", [False, True])
def test_new_profile_routes_real_plan_without_shadow_or_per_step_main_default(tmp_path, monkeypatch, source, needs_review):
    payload = {"contract_version": "decision_profile.v2"} if source == "minimal-v2" else json.loads(
        (Path(__file__).resolve().parents[1] / "configs" / source).read_text(encoding="utf-8"))
    payload["auto_conditions"] = [CONDITION]
    s, service, requests, client = configured_scene(tmp_path, monkeypatch,
        profile=payload, review=0.97 if needs_review else 0.01)
    try:
        original = complete_original(s, native=False)
        current = s.runtime.tick(force=True)
        assert len(requests) == 1
        choice = payload.get("decision_format") == "choice"
        assert [question["name"] for question in json.loads(requests[0].content)["questions"]] == (
            ["current_step"] if choice else ["condition_met", "visible_error", "needs_agent_review"])
        if needs_review:
            assert current["wait_reason"] == "verification_required"
            assert current["review_packet"]["suggested_verdict"] == ("uncertain" if choice else "success")
            assert current["review_packet"]["execution_request_id"] == original.command_id
            assert len(list(s.session.glob("commands/*.json"))) == 1
            s.runtime.control(review_request(s, current, original), "main-review")
            s.runtime.control({"action": "continue", "run_id": s.run_id,
                "wait_id": current["wait"]["wait_id"]}, "continue-original")
            current = s.runtime.tick(force=True)
        assert current["wait_reason"] == "execution_pending"
        assert current["pending"]["step_id"] == "step-1"
        assert len(list(s.session.glob("commands/*.json"))) == 2
        assert len(requests) == 1
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("profile", [None, {"contract_version": "decision_profile.v2", "mode": "off"}])
@pytest.mark.parametrize("native", [False, True])
def test_no_api_keeps_local_continuation_or_bound_main_wait(tmp_path, monkeypatch, profile, native):
    s, service, requests, client = configured_scene(tmp_path, monkeypatch, profile=profile, native=native, key=False)
    try:
        original = complete_original(s, native=native)
        current = s.runtime.tick(force=True)
        if native:
            assert current["wait_reason"] == "execution_pending"
            assert current["pending"]["step_id"] == "step-1"
        else:
            assert current["wait_reason"] == "verification_required"
            assert current["review_packet"]["execution_request_id"] == original.command_id
            assert len(list(s.session.glob("commands/*.json"))) == 1
            s.runtime.control(review_request(s, current, original), "main-review")
            s.runtime.control({"action": "continue", "run_id": s.run_id,
                "wait_id": current["wait"]["wait_id"]}, "continue-original")
            assert s.runtime.tick(force=True)["pending"]["step_id"] == "step-1"
        assert requests == []
        assert not (s.session / "judgments").exists()
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("patch", [{"mode": "shadow"}, {"review_policy": "always_main"},
    {"auto_conditions": []}, {"contract_version": "decision_profile.v1"}])
def test_explicit_or_legacy_review_policy_is_not_upgraded(tmp_path, monkeypatch, patch):
    payload = {"contract_version": "decision_profile.v2", "auto_conditions": [CONDITION], **patch}
    s, service, requests, client = configured_scene(tmp_path, monkeypatch, profile=payload)
    try:
        original = complete_original(s, native=False)
        current = s.runtime.tick(force=True)
        assert current["wait_reason"] == "verification_required"
        assert current["review_packet"]["execution_request_id"] == original.command_id
        assert len(list(s.session.glob("commands/*.json"))) == 1
        if patch.get("review_policy") == "always_main" or patch.get("auto_conditions") == []:
            assert requests == []
        if patch.get("contract_version") == "decision_profile.v1":
            assert service.profile.mode == "shadow"
    finally:
        service.close()
        client.close()


def test_missing_key_keeps_original_wait_without_dispatch_or_input_replay(tmp_path, monkeypatch):
    s, service, requests, client = configured_scene(tmp_path, monkeypatch,
        profile={"contract_version": "decision_profile.v2", "auto_conditions": [CONDITION]}, key=False)
    try:
        original = complete_original(s, native=False)
        current = s.runtime.tick(force=True)
        assert current["wait_reason"] == "verification_required"
        assert current["review_packet"]["execution_request_id"] == original.command_id
        assert requests == []
        assert len(list(s.session.glob("commands/*.json"))) == 1
        used = service.status()["used"]
        assert s.runtime.tick(force=True) is None
        assert service.status()["used"] == used
        assert service.readiness() == {"ready": False, "status": "not_connected"}
    finally:
        service.close()
        client.close()
