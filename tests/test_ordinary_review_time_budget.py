"""两层阶段预算及外层总截止；全部使用离线传输和认证账本。"""
from copy import deepcopy
import json
from pathlib import Path
from threading import RLock

import httpx
import pytest

from app.judgment import DecisionProfile, OpenAIDecisionsProvider
from app.judgment.ordinary_review import validate_review_record
from test_adaptive_decision_policy import context
from test_decision_choice import runtime
from test_decision_service import arguments
from tests.test_luna_choice_review_provider import payload, decision_body, response_body


def config(**changes):
    return {"contract_version": "decision_profile.v2", "mode": "auto", "decision_format": "choice",
        "ordinary_review": "on_reject", **changes}


def review_answer(data):
    return {"request_sha256": data["request_sha256"],
        "review_result": {"type": "choice", "name": "current_step", "choice": "condition_met"},
        "usage": {"input_tokens": 20, "output_tokens": 2, "total_tokens": 22},
        "http_elapsed_ms": 100, "server_processing_ms": 50, "provider_request_id": "req-offline-review"}


def test_optional_timeout_none_keeps_old_profile_dump_and_digest_input():
    old = DecisionProfile(**config())
    explicit_none = DecisionProfile(**config(ordinary_review_timeout_seconds=None))
    assert old.model_dump(mode="json") == explicit_none.model_dump(mode="json")
    assert "ordinary_review_timeout_seconds" not in old.model_dump()
    assert DecisionProfile(**config(ordinary_review_timeout_seconds=12)).ordinary_review_timeout_seconds == 12


@pytest.mark.parametrize("value", [0, -1, 61, True, "12", float("nan")])
def test_independent_review_timeout_is_strict_and_bounded(value):
    with pytest.raises(ValueError):
        DecisionProfile(**config(ordinary_review_timeout_seconds=value))


@pytest.mark.parametrize("changes", [{"ordinary_review": "off"}, {"decision_format": "predicate"},
    {"contract_version": "decision_profile.v1"}])
def test_independent_timeout_requires_enabled_v2_choice(changes):
    with pytest.raises(ValueError):
        DecisionProfile(**config(ordinary_review_timeout_seconds=12, **changes))


def test_maintained_examples_explicitly_allow_twelve_second_review():
    from app.judgment.profile import load_decision_profile
    for suffix in ("example", "adaptive.example", "visual-execution.example"):
        assert load_decision_profile(Path("configs") / f"decision-profile.{suffix}.json").ordinary_review_timeout_seconds == 12


def test_primary_honors_plain_request_budget_before_http(monkeypatch):
    import app.judgment.openai_decisions as module
    monkeypatch.setenv("BUDGET_TEST_KEY", "synthetic-only")
    clock = [0]
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    original = module.result_choice_question
    def slow_question(condition):
        clock[0] += 300_000_000
        return original(condition)
    monkeypatch.setattr(module, "result_choice_question", slow_question)
    data = payload()
    data["request_timeout_seconds"] = .2
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, json=decision_body()))) as client:
        with pytest.raises(TimeoutError):
            OpenAIDecisionsProvider(api_key_env="BUDGET_TEST_KEY", client=client).judge(data)
    assert calls == []


def test_review_can_exceed_primary_cap_but_carries_absolute_deadline(monkeypatch):
    monkeypatch.setenv("BUDGET_TEST_KEY", "synthetic-only")
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=response_body())
    data = payload()
    data["request_timeout_seconds"] = 12
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = OpenAIDecisionsProvider(api_key_env="BUDGET_TEST_KEY", timeout_seconds=8, client=client).review(data)
    assert result["review_result"]["choice"] == "condition_met"
    assert 11 < calls[0].extensions["timeout"]["read"] <= 12
    assert "total_deadline" in calls[0].extensions


@pytest.mark.parametrize("independent,outer,adopted", [(12, None, True), (None, None, False), (12, 10, False)])
def test_stage_budget_preserves_legacy_shared_mode_and_outer_cap(tmp_path, monkeypatch, independent, outer, adopted):
    import app.judgment.service as module
    clock = [0]
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    service, calls, client = runtime(tmp_path, monkeypatch, body=decision_body(),
        profile={"ordinary_review": "on_reject", "ordinary_review_timeout_seconds": independent})
    original = service._provider.judge
    def judge(data):
        answer = original(data)
        clock[0] = 7_000_000_000
        return answer
    reviews = []
    def review(data):
        reviews.append(deepcopy(data))
        clock[0] = 16_000_000_000
        return review_answer(data)
    monkeypatch.setattr(service._provider, "judge", judge)
    monkeypatch.setattr(service._provider, "review", review)
    args = arguments(tmp_path, review_context=context(), request_budget_seconds=outer)
    result = service.evaluate(**args)
    assert len(calls) == len(reviews) == 1
    assert reviews[0]["request_timeout_seconds"] == (12 if independent and outer is None else 3 if outer else 1)
    assert result["adopted"] is adopted
    if not adopted:
        assert result["ordinary_review"]["diagnostic"]["phase"] == "service_deadline"
        assert result["ordinary_review"]["diagnostic"]["provider_request_id"] == "req-offline-review"
        assert result["usage"]["total_tokens"] == 34
    assert service.validate_result(result, **args)
    assert service.evaluate(**args) == result and len(calls) == len(reviews) == 1
    client.close()


def test_review_admission_time_consumes_independent_stage_budget(tmp_path, monkeypatch):
    import app.judgment.service as module
    clock = [0]
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    service, calls, client = runtime(tmp_path, monkeypatch, body=decision_body(),
        profile={"ordinary_review": "on_reject", "ordinary_review_timeout_seconds": 12})
    original_connect = service._connect
    connections = [0]
    def connect():
        connections[0] += 1
        if connections[0] == 2:
            clock[0] += 4_000_000_000
        return original_connect()
    monkeypatch.setattr(service, "_connect", connect)
    def review(data):
        assert data["request_timeout_seconds"] == 8
        return review_answer(data)
    monkeypatch.setattr(service._provider, "review", review)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result["adopted"] and service.validate_result(result, **args)
    assert len(calls) == 1
    client.close()


@pytest.mark.parametrize("stage", ["queue", "http", "parse"])
def test_timeout_diagnostic_keeps_phase_and_known_response_metadata(tmp_path, monkeypatch, stage):
    import app.judgment.openai_decisions as module
    clock = [0]
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    def handle(request):
        if request.url.path.endswith("decisions"):
            return httpx.Response(200, json=decision_body())
        if stage == "http":
            raise httpx.ReadTimeout("synthetic-choice-secret", request=request)
        clock[0] = 13_000_000_000
        return httpx.Response(200, json=response_body(), headers={"x-request-id": "req-known-response"})
    service, calls, client = runtime(tmp_path, monkeypatch, handler=handle,
        profile={"ordinary_review": "on_reject", "ordinary_review_timeout_seconds": 12})
    if stage == "queue":
        def queue_timeout(data):
            raise TimeoutError("ordinary_review_provider_queue_timeout")
        monkeypatch.setattr(service._provider, "review", queue_timeout)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    record = result["ordinary_review"]
    assert record["diagnostic"]["phase"] == stage
    assert not result["adopted"] and result["disposition"] == "review_required"
    assert "synthetic-choice-secret" not in json.dumps(record)
    if stage == "parse":
        assert record["diagnostic"]["provider_request_id"] == "req-known-response"
        assert record["diagnostic"]["usage"]["total_tokens"] == 18
        assert result["usage"]["total_tokens"] == 30
    assert service.validate_result(result, **args)
    changed = deepcopy(record)
    changed["diagnostic"]["phase"] = "unknown-secret"
    with pytest.raises(ValueError):
        validate_review_record(changed, result["request_sha256"])
    assert service.evaluate(**args) == result
    client.close()


@pytest.mark.parametrize("late_at", ["settlement_lock", "persistence"])
def test_final_settlement_cannot_adopt_after_deadline(tmp_path, monkeypatch, late_at):
    import app.judgment.service as module
    clock = [0]
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    service, calls, client = runtime(tmp_path, monkeypatch,
        profile={"ordinary_review": "on_reject", "ordinary_review_timeout_seconds": 12})
    if late_at == "settlement_lock":
        class SlowLock:
            def __init__(self):
                self.lock, self.count = RLock(), 0
            def __enter__(self):
                self.lock.acquire()
                self.count += 1
                if self.count == 2:
                    clock[0] = 9_000_000_000
            def __exit__(self, *args):
                self.lock.release()
        service._provider_lock = SlowLock()
    else:
        original = module._protect
        protected = [0]
        def slow_protect(*args, **kwargs):
            if not kwargs.get("decrypt"):
                protected[0] += 1
                if protected[0] == 2:
                    clock[0] = 9_000_000_000
            return original(*args, **kwargs)
        monkeypatch.setattr(module, "_protect", slow_protect)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result["status"] == "timeout" and not result["adopted"]
    assert service.validate_result(result, **args)
    assert service.evaluate(**args) == result and len(calls) == 1
    client.close()
