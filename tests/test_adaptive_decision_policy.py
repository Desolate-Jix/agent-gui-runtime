"""主动审核合同的离线回归；本轮先编写，待用户授权后执行。"""
from copy import deepcopy
from hashlib import sha256
import json

import httpx
import pytest

from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from test_decision_service import arguments
from test_openai_decisions import reply


def context(**patch):
    return {"goal": "Open record then inspect its details", "step_goal": "Open record",
            "remaining_plan": ["Read the displayed record details"], "allowed_states": ["Record details page"],
            "source_id": "plan-1", "source_sha256": "b" * 64, **patch}


def service(root, monkeypatch, *, met=0.97, danger=0.01, review=0.01, progress=0.97, profile=None, mutate=None):
    monkeypatch.setenv("ADAPTIVE_DECISION_TEST_KEY", "synthetic-adaptive-secret")
    requests = []
    def handle(request):
        requests.append(request)
        body = reply(met, danger)
        questions = json.loads(request.content)["questions"]
        body["answers"][1]["name"] = questions[1]["name"]
        if any(question["name"] == "needs_agent_review" for question in questions):
            body["answers"].append({"type": "predicate", "name": "needs_agent_review", "probability": review})
        if any(question["name"] == "still_progressing" for question in questions):
            body["answers"].append({"type": "predicate", "name": "still_progressing", "probability": progress})
        if mutate:
            mutate(body)
        return httpx.Response(200, json=body)
    client = httpx.Client(transport=httpx.MockTransport(handle))
    config = {"contract_version": "decision_profile.v2", "mode": "auto", "api_key_env": "ADAPTIVE_DECISION_TEST_KEY",
              "auto_conditions": ["\u8be6\u60c5\u5df2\u6253\u5f00"], **(profile or {})}
    runtime = DecisionService(root, profile=DecisionProfile.model_validate(config),
        provider=OpenAIDecisionsProvider(api_key_env="ADAPTIVE_DECISION_TEST_KEY", client=client))
    return runtime, requests, client


@pytest.mark.parametrize("review,code", [(0.96, "off_plan_intervention_high"), (0.4, "off_plan_intervention_gray")])
def test_success_can_require_review_without_adopting_or_repeating_request(tmp_path, monkeypatch, review, code):
    runtime, requests, client = service(tmp_path, monkeypatch, review=review)
    args = arguments(tmp_path, review_context=context())
    result = runtime.evaluate(**args)
    assert result["verdict"] == "success" and result["disposition"] == "review_required"
    assert result["review_scope"] == "remaining_plan" and code in result["reason_codes"]
    assert result["adopted"] is False and result["authorizes_action"] is False
    assert runtime.validate_result(result, **args)
    assert result["profile_sha256"] == runtime.status()["profile_sha256"]
    assert result["budget"] == {"scope": "host_session", "request_cap": 20, "used": 1,
                                "remaining": 19, "snapshot_phase": "dispatch_admission"}
    assert runtime.evaluate(**args) == result and len(requests) == 1
    assert [q["name"] for q in json.loads(requests[0].content)["questions"]] == [
        "condition_met", "visible_error", "needs_agent_review"]
    client.close()


@pytest.mark.parametrize("met,danger,review,verdict,code", [
    (0.98, 0.97, 0.96, "uncertain", "decision_predicate_conflict"),
    (0.05, 0.01, 0.01, "failure", "condition_not_met"),
    (0.5, 0.01, 0.01, "uncertain", "condition_gray"),
    (0.5, 0.97, 0.01, "failure", "visible_error_high"),
    (0.98, 0.4, 0.01, "uncertain", "visible_error_gray"),
])
def test_outcome_is_derived_before_review_routing(tmp_path, monkeypatch, met, danger, review, verdict, code):
    runtime, _, client = service(tmp_path, monkeypatch, met=met, danger=danger, review=review)
    result = runtime.evaluate(**arguments(tmp_path, review_context=context()))
    assert result["verdict"] == verdict and result["disposition"] == "review_required"
    assert result["adopted"] is False and code in result["reason_codes"]
    client.close()


def test_explicitly_disabled_review_is_not_a_probability_and_complete_success_continues(tmp_path, monkeypatch):
    runtime, requests, client = service(tmp_path, monkeypatch, profile={"proactive_review": False})
    args = arguments(tmp_path, review_context=context())
    result = runtime.evaluate(**args)
    assert result["verdict"] == "success" and result["disposition"] == "continue" and result["adopted"]
    assert result["predicates"]["needs_agent_review"] == {"type": "not_requested", "probability": None}
    assert result["probabilities"]["needs_agent_review"] is None
    assert "needs_agent_review" not in result["enabled_predicates"]
    assert result["predicates"]["still_progressing"] == {"type": "not_requested", "probability": None}
    assert len(json.loads(requests[0].content)["questions"]) == 2
    assert runtime.validate_result(result, **args)
    client.close()


@pytest.mark.parametrize("mutate", [
    lambda body: body["answers"].pop(),
    lambda body: body["answers"][-1].update(probability=True),
    lambda body: body["answers"][-1].update(type="not_requested", probability=None),
    lambda body: body["answers"][-1].update(name="still_progressing"),
])
def test_missing_or_invalid_requested_review_never_becomes_negative_answer(tmp_path, monkeypatch, mutate):
    runtime, requests, client = service(tmp_path, monkeypatch, mutate=mutate)
    args = arguments(tmp_path, review_context=context())
    result = runtime.evaluate(**args)
    assert result["status"] == "error" and result["verdict"] == "uncertain"
    assert result["disposition"] == "review_required" and not result["adopted"]
    assert runtime.evaluate(**args) == result and len(requests) == 1
    client.close()


@pytest.mark.parametrize("profile,ctx,reason", [
    ({"review_policy": "always_main"}, context(), "decision_always_main"),
    ({}, context(review_policy="always_main"), "decision_always_main"),
    ({"review_policy": "always_main"}, context(review_policy="adaptive"), "decision_always_main"),
    ({"auto_conditions": []}, context(), "decision_condition_not_allowlisted"),
])
def test_policy_preflight_is_zero_request_and_returns_authenticated_bound_wait(tmp_path, monkeypatch, profile, ctx, reason):
    runtime, requests, client = service(tmp_path, monkeypatch, profile=profile)
    args = arguments(tmp_path, review_context=ctx)
    result = runtime.evaluate(**args)
    assert result["status"] == "skipped" and result["disposition"] == "review_required"
    assert result["reason"] == reason and requests == [] and result["adopted"] is False
    assert runtime.validate_result(result, **args)
    assert runtime.status()["used"] == 0 and runtime.status()["remaining"] == 20
    client.close()


def test_shadow_only_records_suggested_route_without_authorizing_continuation(tmp_path, monkeypatch):
    runtime, requests, client = service(tmp_path, monkeypatch, profile={"mode": "shadow", "auto_conditions": []})
    result = runtime.evaluate(**arguments(tmp_path, review_context=context()))
    assert result["verdict"] == "success" and result["suggested_disposition"] == "continue"
    assert result["disposition"] == "review_required" and not result["adopted"]
    assert "decision_shadow_advice_only" in result["reason_codes"] and len(requests) == 1
    client.close()


def test_off_profile_keeps_zero_disk_and_request_work(tmp_path, monkeypatch):
    runtime, requests, client = service(tmp_path / "missing", monkeypatch, profile={"mode": "off"})
    result = runtime.evaluate(request_id="off", execution_request_id="off", condition="", frames=[])
    assert result["status"] == "disabled" and result["disposition"] == "review_required"
    assert requests == [] and not (tmp_path / "missing").exists()
    assert runtime.status()["used"] == 0 and not (tmp_path / "missing").exists()
    client.close()


def test_missing_context_for_proactive_review_is_authenticated_zero_request_wait(tmp_path, monkeypatch):
    runtime, requests, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    result = runtime.evaluate(**args)
    assert result["status"] == "skipped" and result["reason"] == "decision_review_context_missing"
    assert result["disposition"] == "review_required" and not result["adopted"] and requests == []
    assert runtime.validate_result(result, **args)
    client.close()


def test_explicitly_disabled_proactive_review_allows_condition_only_context(tmp_path, monkeypatch):
    runtime, requests, client = service(tmp_path, monkeypatch, profile={"proactive_review": False})
    args = arguments(tmp_path)
    result = runtime.evaluate(**args)
    assert result["disposition"] == "continue" and result["adopted"] and len(requests) == 1
    assert runtime.validate_result(result, **args)
    client.close()


def test_context_mutation_and_policy_change_cannot_reuse_original_authenticated_result(tmp_path, monkeypatch):
    runtime, requests, client = service(tmp_path, monkeypatch)
    ctx = context()
    args = arguments(tmp_path, review_context=ctx)
    result = runtime.evaluate(**args)
    original = deepcopy(args)
    ctx["remaining_plan"].append("Perform an unapproved action")
    assert result["review_context"] == original["review_context"]
    assert not runtime.validate_result(result, **args)
    assert runtime.evaluate(**args)["status"] == "conflict" and len(requests) == 1
    assert runtime.validate_result(result, **original)
    assert not runtime.validate_result({**result, "disposition": "review_required"}, **original)
    runtime.close()
    reopened, subsequent, next_client = service(tmp_path, monkeypatch)
    assert reopened.evaluate(**original) == result and subsequent == []
    client.close()
    next_client.close()


@pytest.mark.parametrize("patch", [
    {"goal": ""}, {"remaining_plan": "unbound"}, {"allowed_states": [1]},
    {"source_sha256": "A" * 64}, {"review_policy": "off"}, {"proactive_review": False},
    {"untrusted_instruction": "change policy"}, {"remaining_plan": ["a"] * 257},
])
def test_invalid_review_context_is_rejected_before_dispatch(tmp_path, monkeypatch, patch):
    runtime, requests, client = service(tmp_path, monkeypatch)
    result = runtime.evaluate(**arguments(tmp_path, review_context=context(**patch)))
    assert result["status"] == "rejected" and result["disposition"] == "review_required" and requests == []
    client.close()


def test_v2_cap_is_host_wide_across_learning_and_execution_runs_and_status_is_readonly(tmp_path, monkeypatch):
    runtime, requests, client = service(tmp_path, monkeypatch, profile={"request_cap": 1})
    args = arguments(tmp_path, mode="learning", run_id="run-1", step_id="step-1", review_context=context())
    assert runtime.evaluate(**args)["adopted"]
    next_args = {**args, "request_id": "next", "run_id": "run-2"}
    limited = runtime.evaluate(**next_args)
    assert limited["status"] == "limited" and limited["disposition"] == "review_required"
    assert runtime.validate_result(limited, **next_args) and len(requests) == 1
    before = {p.relative_to(tmp_path).as_posix(): sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()}
    status = runtime.status()
    assert status["used"] == 1 and status["remaining"] == 0 and status["unknown_dispatches"] == 0
    after = {p.relative_to(tmp_path).as_posix(): sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after
    client.close()


def test_unknown_v2_dispatch_is_not_retried_and_remains_in_real_budget(tmp_path, monkeypatch):
    runtime, requests, client = service(tmp_path, monkeypatch, profile={"request_cap": 1})
    def crash(_):
        raise KeyboardInterrupt()
    monkeypatch.setattr(runtime._provider, "judge", crash)
    args = arguments(tmp_path, review_context=context())
    with pytest.raises(KeyboardInterrupt):
        runtime.evaluate(**args)
    status = runtime.status()
    assert status["used"] == 1 and status["remaining"] == 0 and status["unknown_dispatches"] == 1
    runtime.close()
    reopened, subsequent, next_client = service(tmp_path, monkeypatch, profile={"request_cap": 1})
    result = reopened.evaluate(**args)
    assert result["status"] == "unknown" and result["disposition"] == "review_required"
    assert reopened.validate_result(result, **args) and subsequent == [] and requests == []
    assert reopened.evaluate(**{**args, "request_id": "another"})["status"] == "limited"
    client.close()
    next_client.close()


def test_v2_authenticated_result_does_not_validate_after_policy_change(tmp_path, monkeypatch):
    runtime, requests, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path, review_context=context())
    result = runtime.evaluate(**args)
    changed, subsequent, next_client = service(tmp_path, monkeypatch, profile={"proactive_review": False})
    assert changed.validate_result(result, **args) is False
    assert changed.evaluate(**args)["status"] == "conflict"
    assert len(requests) == 1 and subsequent == []
    client.close()
    next_client.close()


def test_v1_serialization_and_request_digest_remain_legacy_and_saved_result_reopens(tmp_path, monkeypatch):
    from test_decision_service import setup_service
    runtime, requests, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=["\u8be6\u60c5\u5df2\u6253\u5f00"])
    args = arguments(tmp_path)
    result = runtime.evaluate(**args)
    binding = {**args, "mode": "execution", "phase": "after_action", "run_id": None, "step_id": None, "action": None}
    policy = {"mode": "auto", "pass_threshold": 0.9, "fail_threshold": 0.1, "auto_conditions": [args["condition"]]}
    legacy_digest = sha256(json.dumps({"binding": binding, "policy": policy}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    assert result["request_sha256"] == legacy_digest and "disposition" not in result
    assert "proactive_review" not in runtime.profile.model_dump() and "review_policy" not in runtime.profile.model_dump()
    reopened, subsequent, next_client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=[args["condition"]])
    assert reopened.evaluate(**args) == result and reopened.validate_result(result, **args)
    assert len(requests) == 1 and subsequent == []
    client.close()
    next_client.close()


def test_v1_does_not_silently_accept_v2_policy_fields():
    with pytest.raises(ValueError):
        DecisionProfile.model_validate({"contract_version": "decision_profile.v1", "proactive_review": True})


@pytest.mark.parametrize("patch", [{"proactive_review": 1}, {"review_policy": "sometimes"}, {"still_progressing": True}])
def test_v2_policy_requires_explicit_finite_configuration(patch):
    with pytest.raises(ValueError):
        DecisionProfile.model_validate({"contract_version": "decision_profile.v2", **patch})


def waiting_context(**patch):
    return context(wait_policy={"loading_condition": "A visible record loading indicator is present",
                                "completion_excludes_loading": True}, **patch)


def round_context(**patch):
    return {"assessment_round": 0, "original_receipt_sha256": "c" * 64,
            "evidence_set_sha256": "d" * 64, "elapsed_ms": 500, "timeout_seconds": 3, **patch}


@pytest.mark.parametrize("met,danger,review,progress,exclusive,expected,verdict", [
    (0.01, 0.01, 0.01, 0.97, True, "observe", "uncertain"),
    (0.4, 0.01, 0.01, 0.97, True, "review_required", "uncertain"),
    (0.01, 0.4, 0.01, 0.97, True, "review_required", "failure"),
    (0.01, 0.01, 0.4, 0.97, True, "review_required", "failure"),
    (0.01, 0.01, 0.01, 0.4, True, "review_required", "failure"),
    (0.97, 0.01, 0.01, 0.97, True, "review_required", "uncertain"),
    (0.97, 0.01, 0.01, 0.97, False, "continue", "success"),
    (0.01, 0.97, 0.01, 0.97, True, "review_required", "failure"),
])
def test_declared_progress_routes_only_safe_incomplete_target(tmp_path, monkeypatch, met, danger, review,
                                                           progress, exclusive, expected, verdict):
    runtime, calls, client = service(tmp_path, monkeypatch, met=met, danger=danger, review=review, progress=progress)
    ctx = waiting_context()
    ctx["wait_policy"]["completion_excludes_loading"] = exclusive
    args = arguments(tmp_path, review_context=ctx, assessment_context=round_context())
    result = runtime.evaluate(**args)
    assert result["status"] == "completed" and result["disposition"] == expected
    assert result["verdict"] == verdict and result["adopted"] is (expected == "continue")
    assert result["enabled_predicates"][-1] == "still_progressing" and len(calls) == 1
    assert runtime.validate_result(result, **args)
    assert runtime.evaluate(**args) == result and len(calls) == 1
    client.close()


@pytest.mark.parametrize("profile,actual,suggested", [
    ({"proactive_review": False}, "observe", "observe"),
    ({"mode": "shadow", "auto_conditions": []}, "review_required", "observe"),
])
def test_progress_observation_never_adopts_and_shadow_only_suggests(tmp_path, monkeypatch, profile, actual, suggested):
    runtime, calls, client = service(tmp_path, monkeypatch, met=0.01, profile=profile)
    result = runtime.evaluate(**arguments(tmp_path, review_context=waiting_context()))
    assert result["disposition"] == actual and result["suggested_disposition"] == suggested
    assert result["verdict"] == "uncertain" and not result["adopted"] and len(calls) == 1
    client.close()


@pytest.mark.parametrize("patch", [
    {"loading_condition": ""}, {"loading_condition": "x" * 4001},
    {"completion_excludes_loading": 1}, {"extra": True},
])
def test_invalid_wait_declaration_rejected_without_dispatch(tmp_path, monkeypatch, patch):
    runtime, calls, client = service(tmp_path, monkeypatch)
    ctx = waiting_context()
    ctx["wait_policy"].update(patch)
    result = runtime.evaluate(**arguments(tmp_path, review_context=ctx))
    assert result["status"] == "rejected" and calls == []
    client.close()


@pytest.mark.parametrize("patch", [
    {"assessment_round": True}, {"assessment_round": 3}, {"assessment_round": 1.0},
    {"elapsed_ms": True}, {"elapsed_ms": -1}, {"elapsed_ms": float("nan")},
    {"elapsed_ms": 12000}, {"timeout_seconds": True}, {"timeout_seconds": 0},
    {"timeout_seconds": 13}, {"timeout_seconds": float("inf")},
    {"elapsed_ms": 10 ** 400}, {"timeout_seconds": 10 ** 400},
    {"elapsed_ms": 11500, "timeout_seconds": 1}, {"original_receipt_sha256": "C" * 64},
    {"evidence_set_sha256": "not-a-sha"}, {"extra": "unsupported"},
])
def test_invalid_assessment_context_is_zero_dispatch(tmp_path, monkeypatch, patch):
    runtime, calls, client = service(tmp_path, monkeypatch)
    result = runtime.evaluate(**arguments(tmp_path, review_context=context(), assessment_context=round_context(**patch)))
    assert result["status"] == "rejected" and calls == []
    client.close()


@pytest.mark.parametrize("round_number", [1, 2])
def test_new_round_binds_original_after_and_independent_latest_observation(tmp_path, monkeypatch, round_number):
    from test_decision_service import frame
    runtime, calls, client = service(tmp_path, monkeypatch)
    frames = [frame(tmp_path, "after", "original-after"), frame(tmp_path, "observation", "fresh-1")]
    args = arguments(tmp_path, frames=frames, review_context=waiting_context(),
                     assessment_context=round_context(assessment_round=round_number))
    result = runtime.evaluate(**args)
    assert result["status"] == "completed" and result["assessment_context"] == args["assessment_context"]
    assert runtime.validate_result(result, **args) and runtime.validate_result(result)
    for key, value in (("assessment_round", 0), ("original_receipt_sha256", "e" * 64),
                       ("evidence_set_sha256", "f" * 64), ("elapsed_ms", 501), ("timeout_seconds", 2)):
        changed = deepcopy(args)
        changed["assessment_context"][key] = value
        assert not runtime.validate_result(result, **changed)
    assert not runtime.validate_result({**result, "disposition": "observe"}, **args)
    assert len(calls) == 1
    client.close()


@pytest.mark.parametrize("violation", ["missing", "reversed", "duplicate_id", "reused_path", "different_birth",
                                     "different_handle", "different_pid", "round_zero_pair"])
def test_observation_roles_and_window_birth_cannot_be_fabricated(tmp_path, monkeypatch, violation):
    from test_decision_service import frame
    runtime, calls, client = service(tmp_path, monkeypatch)
    frames = [frame(tmp_path, "after", "after"), frame(tmp_path, "observation", "fresh")]
    round_number = 1
    if violation == "missing":
        frames.pop()
    elif violation == "reversed":
        frames.reverse()
    elif violation == "duplicate_id":
        frames[1]["capture_id"] = frames[0]["capture_id"]
    elif violation == "reused_path":
        frames[1]["image_path"] = frames[0]["image_path"]
    elif violation == "different_birth":
        frames[1]["window_identity"]["process_create_time"] += 1
    elif violation == "different_handle":
        frames[1]["window_identity"]["handle"] += 1
    elif violation == "different_pid":
        frames[1]["window_identity"]["process_id"] += 1
    else:
        round_number = 0
    result = runtime.evaluate(**arguments(tmp_path, frames=frames, review_context=context(),
        assessment_context=round_context(assessment_round=round_number)))
    assert result["status"] == "rejected" and calls == []
    client.close()


def test_round_context_cannot_extend_v1_or_before_action(tmp_path, monkeypatch):
    from test_decision_service import setup_service, frame
    runtime, calls, client = setup_service(tmp_path, monkeypatch)
    assert runtime.evaluate(**arguments(tmp_path, assessment_context=round_context()))["status"] == "rejected"
    assert calls == []
    client.close()
    runtime, calls, client = service(tmp_path, monkeypatch)
    result = runtime.evaluate(**arguments(tmp_path, phase="before_action", frames=[frame(tmp_path, "before")],
        review_context=context(), assessment_context=round_context()))
    assert result["status"] == "rejected" and calls == []
    client.close()


def test_omitted_assessment_context_keeps_existing_v2_digest_and_disabled_progress(tmp_path, monkeypatch):
    runtime, calls, client = service(tmp_path, monkeypatch)
    args = arguments(tmp_path, review_context=context())
    result = runtime.evaluate(**args)
    binding = {**args, "mode": "execution", "phase": "after_action", "run_id": None, "step_id": None, "action": None}
    policy = {"profile": runtime.profile.model_dump(mode="json"),
              "enabled_predicates": ["condition_met", "visible_error", "needs_agent_review"],
              "review_policy": "adaptive", "prompt_version": "decision_prompt.v2"}
    digest = sha256(json.dumps({"binding": binding, "policy": policy}, ensure_ascii=False,
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    assert result["request_sha256"] == digest and "assessment_context" not in result
    assert result["predicates"]["still_progressing"] == {"type": "not_requested", "probability": None}
    assert runtime.validate_result(result, **args) and len(calls) == 1
    client.close()


def test_wait_declaration_cannot_enable_progress_before_action(tmp_path, monkeypatch):
    from test_decision_service import frame
    runtime, calls, client = service(tmp_path, monkeypatch)
    result = runtime.evaluate(**arguments(tmp_path, phase="before_action", frames=[frame(tmp_path, "before")],
        review_context=waiting_context()))
    assert result["status"] == "completed" and result["disposition"] == "continue"
    assert result["predicates"]["still_progressing"] == {"type": "not_requested", "probability": None}
    assert len(json.loads(calls[0].content)["questions"]) == 3
    client.close()


def test_loading_refusal_is_not_observe_or_a_fabricated_low_probability(tmp_path, monkeypatch):
    def refuse(body):
        body["answers"][-1] = {"type": "refusal", "name": "still_progressing"}
    runtime, calls, client = service(tmp_path, monkeypatch, met=0.01, mutate=refuse)
    result = runtime.evaluate(**arguments(tmp_path, review_context=waiting_context()))
    assert result["status"] == "refused" and result["disposition"] == "review_required" and not result["adopted"]
    assert result["predicates"]["still_progressing"] == {"type": "refusal", "probability": None}
    assert len(calls) == 1
    client.close()


def test_expired_service_preparation_budget_never_reaches_provider_and_authenticates_timeout(tmp_path, monkeypatch):
    import app.judgment.service as module
    runtime, calls, client = service(tmp_path, monkeypatch)
    clock, original = [0], runtime._prepare
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    def delayed(kwargs, **options):
        prepared = original(kwargs, **options)
        clock[0] += 1_000_000_000
        return prepared
    monkeypatch.setattr(runtime, "_prepare", delayed)
    args = arguments(tmp_path, review_context=waiting_context(), assessment_context=round_context(timeout_seconds=0.5))
    result = runtime.evaluate(**args)
    assert result["status"] == "timeout" and result["disposition"] == "review_required"
    assert not result["adopted"] and calls == [] and runtime.validate_result(result, **args)
    assert runtime.evaluate(**args) == result and calls == []
    client.close()


@pytest.mark.parametrize("profile,reason", [
    ({"review_policy": "always_main"}, "decision_always_main"),
    ({"auto_conditions": []}, "decision_condition_not_allowlisted"),
])
def test_declared_loading_does_not_bypass_zero_request_policy(tmp_path, monkeypatch, profile, reason):
    runtime, calls, client = service(tmp_path, monkeypatch, met=0.01, profile=profile)
    args = arguments(tmp_path, review_context=waiting_context(), assessment_context=round_context())
    result = runtime.evaluate(**args)
    assert result["status"] == "skipped" and result["reason"] == reason
    assert result["disposition"] == "review_required" and not result["adopted"] and calls == []
    assert runtime.validate_result(result, **args) and runtime.status()["used"] == 0
    client.close()


def test_provider_getter_wait_consumes_budget_before_any_http_dispatch(tmp_path, monkeypatch):
    import app.judgment.service as module
    runtime, calls, client = service(tmp_path, monkeypatch)
    clock, getter_calls, original = [0], [], runtime._get_provider
    monkeypatch.setattr(module, "perf_counter_ns", lambda: clock[0])
    def delayed_getter():
        getter_calls.append(True)
        provider = original()
        clock[0] += 1_000_000_000
        return provider
    monkeypatch.setattr(runtime, "_get_provider", delayed_getter)
    args = arguments(tmp_path, review_context=waiting_context(), assessment_context=round_context(timeout_seconds=0.5))
    result = runtime.evaluate(**args)
    assert calls == []
    assert result["status"] == "timeout" and result["disposition"] == "review_required" and not result["adopted"]
    assert runtime.validate_result(result, **args) and runtime.status()["used"] == 1
    assert runtime.evaluate(**args) == result and getter_calls == [True] and calls == []
    client.close()
