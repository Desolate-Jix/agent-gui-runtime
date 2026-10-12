"""主动审核保留原学习票据与已固定修订。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_workflow_decision_verification import CONDITION, DecisionDouble, scene
from tests.test_workflow_trial import services, WORKFLOW


class AdaptiveDecisionDouble(DecisionDouble):
    profile = SimpleNamespace(contract_version="decision_profile.v2", mode="auto", review_policy="adaptive",
                              proactive_review=True, auto_conditions=(CONDITION,))

    def __init__(self, *, disposition="review_required", adopted=False):
        super().__init__(adopted=adopted)
        self.disposition = disposition

    def evaluate(self, **kwargs):
        result = super().evaluate(**kwargs)
        result.update(schema_version="decision_assessment.v2", disposition=self.disposition, review_scope="remaining_plan",
                      reason_codes=["off_plan_obstacle"], enabled_predicates=["condition_met", "visible_error", "needs_agent_review"])
        self.saved[kwargs["request_id"]] = deepcopy(result)
        return result


@pytest.mark.parametrize("adopted", [False, True])
def test_success_requesting_main_review_keeps_original_ticket_pending(services, monkeypatch, adopted):
    service = AdaptiveDecisionDouble(adopted=adopted)
    s = scene(services, monkeypatch, service=service)
    result = s.verify()
    assert result["status"] == "verification_required"
    assert result["reason"] == "workflow_decision_review_required"
    assert result["decision_advice"]["verdict"] == "success"
    pending = s.trials.status(s.run["run_id"])
    assert pending["pending"]["execution_request_id"] == s.ticket["execution_request_id"]
    assert pending["history"] == [] and pending["outputs"] == {}
    assert s.verify("another-verification") == result
    assert len(service.calls) == 1


@pytest.mark.parametrize("disposition", [None, [], {}, "unknown"])
def test_invalid_adaptive_disposition_cannot_settle_original_input(services, monkeypatch, disposition):
    service = AdaptiveDecisionDouble(disposition=disposition, adopted=True)
    s = scene(services, monkeypatch, service=service)
    result = s.verify()
    assert result["status"] == "verification_required" and result["reason"] == "workflow_decision_result_untrusted"
    assert s.trials.status(s.run["run_id"])["history"] == []


def test_v2_dispatch_freezes_program_step_and_suffix_context(services, monkeypatch):
    service = AdaptiveDecisionDouble(disposition="continue", adopted=True)
    s = scene(services, monkeypatch, service=service)
    assert s.verify()["status"] == "completed"
    context = service.calls[0]["review_context"]
    assert context["source_id"] == s.saved["program_id"]
    assert context["source_sha256"] == s.saved["content_sha256"]
    assert context["step_goal"] == s.saved["definition"]["steps"][0]["title"]
    assert context["goal"] == s.saved["definition"]["title"]
    assert context["remaining_plan"] == []


def test_policy_edit_creates_pending_revision_and_preserves_pinned_run(services, monkeypatch):
    service = AdaptiveDecisionDouble(disposition="continue", adopted=True)
    s = scene(services, monkeypatch, service=service)
    definition = deepcopy(s.saved["definition"])
    definition["steps"][0]["verification"]["review_policy"] = "always_main"
    newer = s.programs.save(WORKFLOW, s.saved["content_sha256"], definition, "edit-review-policy")
    assert newer["program_id"] != s.saved["program_id"]
    assert newer["definition"]["steps"][0]["review_status"] == "pending"
    assert "review_policy" not in s.programs.load(WORKFLOW, s.saved["program_id"])["definition"]["steps"][0]["verification"]
    assert s.verify()["status"] == "completed"
    assert "review_policy" not in service.calls[0]["review_context"]


@pytest.mark.parametrize("value", ["unknown", 1, None])
def test_review_options_are_strictly_validated(value):
    from app.learning_memory.workflow_program import _step_rules
    step = {"action": {"kind": "click"}, "outputs": [],
            "verification": {"kind": "agent_judgment", "decision_condition": CONDITION, "review_policy": value}}
    with pytest.raises(ValueError, match="decision_review"):
        _step_rules(step, {}, {}, {})


def test_always_main_policy_skips_capture_and_api(services, monkeypatch):
    service = AdaptiveDecisionDouble()
    service.profile = SimpleNamespace(**{**vars(service.profile), "review_policy": "always_main"})
    s = scene(services, monkeypatch, service=service)
    result = s.verify()
    assert result["status"] == "verification_required" and result["reason"] == "workflow_decision_always_main"
    assert service.calls == s.captures == []


@pytest.mark.parametrize("host,step", [("adaptive", "always_main"), ("always_main", "adaptive")])
def test_step_policy_only_tightens_host_review_policy(services, monkeypatch, host, step):
    service = AdaptiveDecisionDouble()
    service.profile = SimpleNamespace(**{**vars(service.profile), "review_policy": host})
    s = scene(services, monkeypatch, service=service, review_policy=step)
    result = s.verify()
    assert result["status"] == "verification_required" and result["reason"] == "workflow_decision_always_main"
    assert service.calls == s.captures == []


@pytest.mark.parametrize("policy", ["adaptive", "always_main"])
@pytest.mark.parametrize("mode", ["auto", "shadow", "off"])
def test_complete_local_image_respects_main_policy_without_api(services, tmp_path, monkeypatch, policy, mode):
    from tests.test_image_verification import sample
    from tests.test_image_wait_early_exit import Clock
    check, raw, _, _ = sample(tmp_path)
    service = AdaptiveDecisionDouble()
    service.profile = SimpleNamespace(**{**vars(service.profile), "review_policy": policy, "mode": mode})
    service.enabled = mode != "off"
    s = scene(services, monkeypatch, service=service, image=(tmp_path, check, raw))
    clock = Clock()
    monkeypatch.setattr("app.learning_memory.image_verification.monotonic", clock.monotonic)
    monkeypatch.setattr("app.learning_memory.image_verification.sleep", clock.wait)
    result = s.verify()
    review = policy == "always_main" and mode != "off"
    assert result["status"] == ("verification_required" if review else "completed")
    assert service.calls == [] and len(s.captures) == 1
    if review:
        assert s.trials.status(s.run["run_id"])["history"] == []


def test_unapproved_auto_condition_is_zero_capture_and_api(services, monkeypatch):
    service = AdaptiveDecisionDouble()
    service.profile = SimpleNamespace(**{**vars(service.profile), "auto_conditions": ()})
    s = scene(services, monkeypatch, service=service)
    assert s.verify()["status"] == "verification_required"
    assert service.calls == s.captures == []


def test_unproven_extra_condition_requires_main_before_paid_adoption(services, monkeypatch):
    service = AdaptiveDecisionDouble(disposition="continue", adopted=True)
    s = scene(services, monkeypatch, service=service, success_conditions=[
        {"left": {"source": "observation", "name": "independent_check"}, "operator": "agent_assertion"}])
    result = s.verify()
    assert result["status"] == "verification_required"
    assert result["reason"] == "workflow_decision_success_conditions_require_agent"
    assert service.calls == [] and len(s.captures) == 1
    assert s.trials.status(s.run["run_id"])["history"] == []


@pytest.mark.parametrize("mutation", ["source_id", "source_sha256", "step_goal", "remaining_plan"])
def test_tampered_frozen_context_cannot_dispatch_or_settle_again(services, monkeypatch, mutation):
    import json
    service = AdaptiveDecisionDouble()
    s = scene(services, monkeypatch, service=service)
    assert s.verify()["status"] == "verification_required"
    path = s.session / "workflow-observations/decision-verify.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["decision_review_context"][mutation] = ["Different next action."] if mutation == "remaining_plan" else "changed"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="review_context_mismatch"):
        s.verify("another-verification")
    assert len(service.calls) == len(s.captures) == 1
    assert s.trials.status(s.run["run_id"])["history"] == []


@pytest.mark.parametrize("mutation", ["outputs", "read_spec", "read_text"])
def test_review_policy_preserves_dynamic_read_forbidden_contract(mutation):
    from app.learning_memory.workflow_program import _step_rules
    step = {"action": {"kind": "click"}, "outputs": [],
            "verification": {"kind": "agent_judgment", "review_policy": "always_main"}}
    if mutation == "read_text":
        step["action"]["kind"] = "read_text"
    else:
        step[mutation] = [{"name": "value", "type": "text"}] if mutation == "outputs" else {}
    with pytest.raises(ValueError, match="decision_review_dynamic_read_forbidden"):
        _step_rules(step, {}, {}, {})


def test_context_byte_budget_is_rejected_before_model_dispatch():
    from app.learning_memory.decision_verification import decision_review_context
    step = {"step_id": "current", "title": "Current", "action": {"kind": "click"},
            "branches": {"success": "s0", "failure": None, "uncertain": None}}
    suffix = [{"step_id": "s" + str(index), "title": "x" * 1900, "action": {"kind": "click"},
               "branches": {"success": "s" + str(index + 1) if index < 99 else None,
                            "failure": None, "uncertain": None}}
              for index in range(100)]
    program = {"program_id": "task-program-" + "a" * 64, "content_sha256": "a" * 64,
               "definition": {"title": "Long workflow", "steps": [step, *suffix]}}
    with pytest.raises(ValueError, match="review_context_too_large"):
        decision_review_context(program, step)


def test_context_preflight_failure_is_zero_capture_and_api(services, monkeypatch):
    service = AdaptiveDecisionDouble()
    s = scene(services, monkeypatch, service=service)
    def oversized(*args):
        raise ValueError("decision_review_context_too_large")
    monkeypatch.setattr("app.learning_memory.decision_verification.decision_review_context", oversized)
    result = s.verify()
    assert result["status"] == "verification_required" and result["reason"] == "workflow_decision_review_context_invalid"
    assert service.calls == s.captures == []


def test_complete_image_proof_does_not_need_semantic_context_budget(services, tmp_path, monkeypatch):
    from tests.test_image_verification import sample
    from tests.test_image_wait_early_exit import Clock
    check, raw, _, _ = sample(tmp_path)
    service = AdaptiveDecisionDouble()
    s = scene(services, monkeypatch, service=service, image=(tmp_path, check, raw))
    def oversized(*args):
        raise ValueError("decision_review_context_too_large")
    monkeypatch.setattr("app.learning_memory.decision_verification.decision_review_context", oversized)
    clock = Clock()
    monkeypatch.setattr("app.learning_memory.image_verification.monotonic", clock.monotonic)
    monkeypatch.setattr("app.learning_memory.image_verification.sleep", clock.wait)
    assert s.verify()["status"] == "completed"
    assert service.calls == [] and len(s.captures) == 1


def test_unexpected_service_error_is_persisted_wait_without_second_attempt(services, monkeypatch):
    service = AdaptiveDecisionDouble()
    s = scene(services, monkeypatch, service=service)
    def failed():
        raise RuntimeError("Private diagnostic must never be exposed.")
    service.on_evaluate = failed
    result = s.verify()
    assert result["status"] == "verification_required" and result["reason"] == "workflow_decision_evaluation_failed"
    assert result["error_type"] == "RuntimeError" and "Private" not in repr(result)
    assert s.verify("another-verification") == result
    assert len(service.calls) == len(s.captures) == 1
    assert s.trials.status(s.run["run_id"])["history"] == []


@pytest.mark.parametrize("fail_on", [1, 2, 3])
def test_authentication_error_is_structured_wait_without_exposing_details(services, monkeypatch, fail_on):
    service = AdaptiveDecisionDouble(disposition="continue", adopted=True)
    s = scene(services, monkeypatch, service=service)
    validate = service.validate_result
    calls = []
    def failed(result, **binding):
        calls.append(True)
        if len(calls) == fail_on:
            raise ValueError("Private diagnostic must never be exposed.")
        return validate(result, **binding)
    service.validate_result = failed
    result = s.verify()
    assert result["status"] == "verification_required" and result["reason"] == "workflow_decision_authentication_failed"
    assert result["error_type"] == "ValueError" and "Private" not in repr(result)
    assert len(service.calls) == len(s.captures) == 1
    assert s.trials.status(s.run["run_id"])["history"] == []
