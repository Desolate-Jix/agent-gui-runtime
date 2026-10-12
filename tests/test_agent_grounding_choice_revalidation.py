"""像素变化交给同一次候选 Choice；真实认证和派发绑定仍不可省略。"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
from time import perf_counter_ns, time
from types import SimpleNamespace

import pytest
from PIL import ImageDraw

from app.core.agent_grounding_target import AgentGroundingTarget, agent_grounding_scope
from app.execution import action_review as review
from app.execution.action_review_dispatch import review_original_action
from tests.test_action_review_route import context
from tests.test_agent_grounding_target import scene
from tests.test_decision_choice import choice_reply, runtime
from tests.test_execution_decision_check import run_route


def changed_text(scene):
    ImageDraw.Draw(scene[2]).text((31, 42), "New URL / documentation", fill="white")
    current = scene[3] / "current.png"
    scene[2].save(current)
    return current


@contextmanager
def choice_service(scene, monkeypatch, *, choice="condition_met", profile=None):
    monkeypatch.setattr("app.judgment.service._protect", lambda data, entropy, decrypt=False: data)
    service, calls, client = runtime(scene[3], monkeypatch, body=choice_reply(choice),
        profile={"auto_conditions": [review.CANDIDATE_CONDITION], "request_cap": 3, **(profile or {})})
    try:
        yield service, calls
    finally:
        service.close()
        client.close()


def reviewed_route(scene, monkeypatch, service, *, cancelled=None):
    with review.action_review_scope(service, context=context(), cancelled=cancelled,
            deadline_ns=perf_counter_ns() + 5_000_000_000):
        return run_route(scene, monkeypatch, service, condition=review.CANDIDATE_CONDITION)


def test_changed_text_reaches_one_choice_and_dispatches_original_point(scene, monkeypatch):
    changed_text(scene)
    with choice_service(scene, monkeypatch) as (service, calls):
        receipt, clicks, captures, target, *_ = reviewed_route(scene, monkeypatch, service)
        assert receipt.success, receipt
        assert clicks == [(65, 55)] and target.input_claimed
        assert len(calls) == 1
        assert len(captures) == 2
        plan = receipt.data["result"]["recognition_plan"]
        assert plan["grounding_evidence"]["region_changed_fraction"] > .02
        assert plan["recommended_target"]["freshness"]["status"] == "pending_semantic_review"
        assert receipt.data["result"]["action_assessment"]["disposition"] == "pass"


@pytest.mark.parametrize("choice", ["condition_not_met", "evidence_insufficient"])
def test_changed_text_rejected_choice_has_one_request_and_zero_dispatch(scene, monkeypatch, choice):
    changed_text(scene)
    with choice_service(scene, monkeypatch, choice=choice) as (service, calls):
        receipt, clicks, _, target, *_ = reviewed_route(scene, monkeypatch, service)
        assert not receipt.success and clicks == [] and not target.input_claimed
        assert len(calls) == 1
        assert receipt.data["dispatch_status"] == "not_dispatched"


@pytest.mark.parametrize("legacy", ["no_scope", "no_service", "shadow", "off", "predicate", "unavailable", "wrong_goal", "cancelled", "deadline"])
def test_changed_text_keeps_pixel_rejection_without_eligible_choice(scene, monkeypatch, legacy):
    current = changed_text(scene)
    profile = {"mode": legacy} if legacy in {"shadow", "off"} else {}
    if legacy == "predicate":
        profile["decision_format"] = "predicate"
    with choice_service(scene, monkeypatch, profile=profile) as (service, calls):
        if legacy == "unavailable":
            monkeypatch.setattr(service, "readiness", lambda: {"ready": False})
        target = AgentGroundingTarget(scene[0])
        ctx = context()
        if legacy == "wrong_goal":
            ctx["plan"]["steps"][0]["action"]["goal"] = "Other target"
        def plan():
            with agent_grounding_scope(target):
                with pytest.raises(ValueError, match="agent_grounding_target_region_changed"):
                    target.plan(image_path=str(current), goal="Search", identity=scene[1])
        if legacy == "no_scope":
            plan()
        else:
            with review.action_review_scope(None if legacy == "no_service" else service, context=ctx,
                    cancelled=lambda: legacy == "cancelled",
                    deadline_ns=perf_counter_ns() + (-1 if legacy == "deadline" else 5_000_000_000)):
                plan()
        assert not target.input_claimed and calls == []


@contextmanager
def prepared(scene, monkeypatch, *, mutate_before_review=None):
    current = changed_text(scene)
    target = AgentGroundingTarget(scene[0])
    cancelled = [False]
    with choice_service(scene, monkeypatch) as (service, calls), agent_grounding_scope(target), \
            review.action_review_scope(service, context=context(), cancelled=lambda: cancelled[0],
                deadline_ns=perf_counter_ns() + 5_000_000_000) as scope:
        plan = target.plan(image_path=str(current), goal="Search", identity=scene[1])
        capture = {"image_path": str(current), "capture_id": "current-capture",
            "sha256": sha256(current.read_bytes()).hexdigest()}
        candidate = deepcopy(plan["recommended_target"])
        if mutate_before_review:
            mutate_before_review(capture, candidate)
        bound = SimpleNamespace(handle=10, process_id=20,
            rect=SimpleNamespace(left=100, top=200, right=300, bottom=350))
        reviewed = review_original_action(capture=capture, identity=scene[1], candidate=candidate,
            point=candidate["click_point"], goal="Search", click_kind="single",
            manager=SimpleNamespace(get_bound_window=lambda: bound),
            validate_binding=lambda: (scene[1], candidate))
        assert review.validate_assessment(service, reviewed["assessment"], envelope=scope["envelope"])
        assert len(calls) == 1
        yield target, plan, scope, cancelled, calls


@pytest.mark.parametrize("mutation", ["untrusted_result", "context", "goal", "source_hash", "current_hash", "identity", "cancelled", "deadline", "expired", "candidate"])
def test_before_dispatch_reauthenticates_pending_review(scene, monkeypatch, mutation):
    with prepared(scene, monkeypatch) as (target, plan, scope, cancelled, calls):
        identity = deepcopy(scene[1])
        if mutation == "untrusted_result":
            scope["assessment"]["judgment"]["judgment_result"]["request_sha256"] = "f" * 64
        elif mutation == "context":
            scope["context"]["attempt_id"] = "different-attempt"
        elif mutation == "goal":
            target._state["goal"] = "Other target"
        elif mutation in {"source_hash", "current_hash"}:
            path = scene[0]["capture"]["image_path"] if mutation == "source_hash" else plan["image_path"]
            scene[2].save(path)
            if mutation == "current_hash":
                ImageDraw.Draw(scene[2]).line((1, 1, 10, 1), fill="red")
                scene[2].save(path)
        elif mutation == "identity":
            identity["process_create_time"] += 1
        elif mutation == "cancelled":
            cancelled[0] = True
        elif mutation == "deadline":
            monkeypatch.setattr(review, "perf_counter_ns", lambda: scope["deadline_ns"])
        elif mutation == "expired":
            monkeypatch.setattr("app.core.agent_grounding_target.time", SimpleNamespace(time=lambda: target._state["expires_at"]))
        else:
            target._candidate.bbox.x += 1
        with pytest.raises(ValueError):
            target.before_dispatch({"x": 65, "y": 55}, identity)
        assert not target.input_claimed and len(calls) == 1


@pytest.mark.parametrize("mutation", ["bbox", "point", "source", "capture", "frame"])
def test_authenticated_different_candidate_or_frame_cannot_claim_original(scene, monkeypatch, mutation):
    def alter(capture, candidate):
        if mutation == "frame":
            another = scene[3] / "other-current.png"
            another.write_bytes((scene[3] / "current.png").read_bytes())
            capture["image_path"] = str(another)
        elif mutation == "bbox":
            candidate["bbox"]["w"] += 1
        elif mutation == "point":
            candidate["click_point"]["x"] += 1
        elif mutation == "source":
            candidate["source"] = "api_visual"
        else:
            candidate["capture_id"] = "other-original-capture"
    with prepared(scene, monkeypatch, mutate_before_review=alter) as (target, _, _, _, calls):
        with pytest.raises(ValueError):
            target.before_dispatch({"x": 65, "y": 55}, scene[1])
        assert not target.input_claimed and len(calls) == 1


def test_pending_review_cannot_outlive_its_original_scope(scene, monkeypatch):
    with prepared(scene, monkeypatch) as (target, _, scope, _, calls):
        service = scope["service"]
    with agent_grounding_scope(target), review.action_review_scope(service, context=context(),
            deadline_ns=perf_counter_ns() + 5_000_000_000):
        with pytest.raises(ValueError):
            target.before_dispatch({"x": 65, "y": 55}, scene[1])
    assert not target.input_claimed and len(calls) == 1


def test_pending_review_without_assessment_or_agent_scope_cannot_claim(scene, monkeypatch):
    current = changed_text(scene)
    target = AgentGroundingTarget(scene[0])
    with choice_service(scene, monkeypatch) as (service, calls), review.action_review_scope(service,
            context=context(), deadline_ns=perf_counter_ns() + 5_000_000_000):
        with agent_grounding_scope(target):
            target.plan(image_path=str(current), goal="Search", identity=scene[1])
            with pytest.raises(ValueError):
                target.before_dispatch({"x": 65, "y": 55}, scene[1])
        with pytest.raises(ValueError):
            target.before_dispatch({"x": 65, "y": 55}, scene[1])
        assert not target.input_claimed and calls == []


@pytest.mark.parametrize("stop", ["cancelled", "deadline", "expired"])
def test_authentication_cannot_cross_cancellation_or_deadline_and_claim(scene, monkeypatch, stop):
    with prepared(scene, monkeypatch) as (target, _, scope, cancelled, calls):
        service = scope["service"]
        original = service.validate_result
        def slow_authentication(*args, **kwargs):
            authenticated = original(*args, **kwargs)
            if stop == "cancelled":
                cancelled[0] = True
            else:
                monkeypatch.setattr("app.core.agent_grounding_target.time", SimpleNamespace(
                    time=(lambda: target._state["expires_at"]) if stop == "expired" else time,
                    perf_counter_ns=(lambda: scope["deadline_ns"]) if stop == "deadline" else perf_counter_ns))
            return authenticated
        monkeypatch.setattr(service, "validate_result", slow_authentication)
        with pytest.raises(ValueError):
            target.before_dispatch({"x": 65, "y": 55}, scene[1])
        assert not target.input_claimed and len(calls) == 1


def test_pending_review_cannot_replace_original_cancellation_callback(scene, monkeypatch):
    with prepared(scene, monkeypatch) as (target, _, scope, cancelled, calls):
        cancelled[0] = True
        scope["cancelled"] = lambda: False
        with pytest.raises(ValueError):
            target.before_dispatch({"x": 65, "y": 55}, scene[1])
        assert not target.input_claimed and len(calls) == 1
