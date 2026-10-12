"""候选审核使用真实判断服务与临时图像，供应商仅在内存中应答。"""
from copy import deepcopy
from hashlib import sha256
import importlib
from time import perf_counter_ns

from PIL import Image
import pytest


def api():
    assert importlib.util.find_spec("app.execution.action_review") is not None, "action review is not implemented"
    return importlib.import_module("app.execution.action_review")


class Provider:
    ready = True

    def __init__(self):
        self.calls = []
        self.during = None

    def judge(self, payload):
        self.calls.append(deepcopy(payload))
        if self.during:
            self.during()
        return {"request_sha256": payload["request_sha256"],
            "predicates": {name: {"type": "predicate", "probability": 0.99 if name == "condition_met" else 0.01}
                           for name in payload["enabled_predicates"]},
            "usage": {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15},
            "http_elapsed_ms": 1.0, "server_processing_ms": None, "provider_request_id": "offline-1"}


def _review(tmp_path, monkeypatch):
    mod = api()
    from app.judgment.profile import DecisionProfile
    from app.judgment.service import DecisionService, decision_profile_sha256
    monkeypatch.setattr("app.judgment.service._protect", lambda data, entropy, decrypt=False: data)
    profile = DecisionProfile(contract_version="decision_profile.v2", mode="auto",
        auto_conditions=[mod.CANDIDATE_CONDITION, mod.SCENE_CONDITION], request_cap=2)
    provider = Provider()
    service = DecisionService(tmp_path, profile=profile, provider=provider)
    path = tmp_path / "frame.png"
    Image.new("RGB", (200, 150), "white").save(path)
    identity = {"handle": 10, "process_id": 20, "process_create_time": 30.0}
    capture = {"image_path": str(path), "capture_id": "frame-1", "sha256": sha256(path.read_bytes()).hexdigest(),
        "window_identity": identity, "window_size": {"width": 200, "height": 150}}
    step = {"step_id": "open", "action": {"kind": "click", "goal": "Address bar"},
        "verification": {"kind": "agent_judgment"}}
    plan = {"schema_version": "task_plan.v2", "title": "Search Java documentation",
        "inputs": {}, "steps": [step, {"step_id": "search", "action": {"kind": "click", "goal": "First result"},
        "verification": {"kind": "agent_judgment"}}]}
    args = dict(scope="candidate", plan=plan, step=step, run_id="run-1", attempt_id="attempt-1", capture=capture,
        identity=identity, candidate={"candidate_id": "c1", "capture_id": "frame-1", "source": "external_api",
            "bbox": {"x": 10, "y": 10, "w": 100, "h": 20}, "click_point": {"x": 20, "y": 20}},
        action={"operation": "execute_recognition_plan", "goal": "Address bar", "click_kind": "single"},
        profile_sha256=decision_profile_sha256(profile), deadline_ns=perf_counter_ns()+5_000_000_000)
    return mod, service, provider, args


@pytest.fixture
def review(tmp_path, monkeypatch):
    return lambda: _review(tmp_path, monkeypatch)


def test_candidate_binds_full_task_and_remaining_plan(review):
    mod, service, provider, args = review()
    envelope = mod.build_action_review(**args)
    args["plan"]["title"] = "Changed after freeze"
    result = mod.assess_candidate(service, envelope=envelope)
    assert result["disposition"] == "pass", result
    assert result["authorizes_action"] is False
    assert len(provider.calls) == 1
    assert provider.calls[0]["review_context"]["goal"] == "Search Java documentation"
    assert "First result" in str(provider.calls[0]["review_context"]["remaining_plan"])
    assert 0 < provider.calls[0]["request_timeout_seconds"] <= 5
    assert mod.validate_assessment(service, result, envelope=envelope)


def test_scene_cannot_be_adopted_as_candidate(review):
    mod, service, provider, args = review()
    args.update(scope="scene", candidate=None)
    envelope = mod.build_action_review(**args)
    result = mod.assess_scene(service, envelope=envelope)
    assert result["disposition"] == "pass"
    with pytest.raises(ValueError, match="scope"):
        mod.assess_candidate(service, envelope=envelope)
    candidate_args = deepcopy(args)
    candidate_args.update(scope="candidate", candidate={"candidate_id": "c1", "capture_id": "frame-1",
        "source": "external_api", "bbox": {"x": 10, "y": 10, "w": 100, "h": 20},
        "click_point": {"x": 20, "y": 20}})
    assert not mod.validate_assessment(service, result, envelope=mod.build_action_review(**candidate_args))


@pytest.mark.parametrize("change", ["capture", "point", "profile", "payload"])
def test_mismatched_or_mutated_binding_is_rejected(review, change):
    mod, service, provider, args = review()
    if change == "capture":
        args["candidate"]["capture_id"] = "old"
    elif change == "point":
        args["candidate"]["click_point"]["x"] = 180
    if change in {"capture", "point"}:
        with pytest.raises(ValueError):
            mod.build_action_review(**args)
        return
    envelope = mod.build_action_review(**args)
    if change == "profile":
        envelope["profile_sha256"] = "f" * 64
    else:
        envelope["action"]["goal"] = "Different target"
    with pytest.raises(ValueError):
        mod.assess_candidate(service, envelope=envelope)
    assert provider.calls == []


def test_preflight_reports_allowlist_and_host_budget(review):
    mod, service, provider, args = review()
    status = mod.review_preflight(service, condition="not approved")
    assert status["reason"] == "decision_condition_not_allowlisted"
    assert status["ready"] is False
    assert provider.calls == []
    assert mod.review_preflight(service, condition=mod.CANDIDATE_CONDITION)["ready"] is True
    for i in range(2):
        args["attempt_id"] = "attempt-"+str(i)
        assert mod.assess_candidate(service, envelope=mod.build_action_review(**args))["disposition"] == "pass"
    assert mod.review_preflight(service, condition=mod.CANDIDATE_CONDITION)["reason"] == "decision_scope_request_cap"


def test_expired_budget_never_dispatches(review, monkeypatch):
    mod, service, provider, args = review()
    envelope = mod.build_action_review(**args)
    monkeypatch.setattr(mod, "perf_counter_ns", lambda: args["deadline_ns"] + 1)
    result = mod.assess_candidate(service, envelope=envelope)
    assert result["disposition"] == "unavailable"
    assert result["reason"] == "action_review_deadline_expired"
    assert provider.calls == []


def test_late_result_is_not_adopted(review, monkeypatch):
    mod, service, provider, args = review()
    envelope = mod.build_action_review(**args)
    provider.during = lambda: monkeypatch.setattr(mod, "perf_counter_ns", lambda: args["deadline_ns"] + 1)
    result = mod.assess_candidate(service, envelope=envelope)
    assert result["disposition"] == "unavailable"
    assert not mod.validate_assessment(service, result, envelope=envelope)


def test_cancelled_result_is_not_adopted(review):
    mod, service, provider, args = review()
    envelope = mod.build_action_review(**args)
    result = mod.assess_candidate(service, envelope=envelope)
    assert not mod.validate_assessment(service, result, envelope=envelope, cancelled=lambda: True)
