"""主动审核不能被成功概率或旧采用字段绕过。"""
import json

import httpx
from PIL import Image
import pytest

from app.execution.decision_check import evaluate_post_action
from tests.test_agent_grounding_target import scene
from tests.test_execution_decision_check import Decisions, run_route


class AdaptiveDecisions(Decisions):
    def __init__(self, *, disposition="review_required", adopted=False, authenticated=True, **kwargs):
        super().__init__(**kwargs)
        self.profile.contract_version = "decision_profile.v2"
        self.profile.proactive_review = True
        self.profile.review_policy = "adaptive"
        self.disposition = disposition
        self.adopted = adopted
        self.authenticated = authenticated
        self.authentication_requests = []

    def evaluate(self, **request):
        result = super().evaluate(**request)
        result.update(schema_version="decision_assessment.v2", disposition=self.disposition,
            review_scope="remaining_plan", reason_codes=["off_plan_intervention_high"],
            adopted=self.adopted)
        return result

    def validate_result(self, result, **request):
        self.authentication_requests.append(request)
        return self.authenticated


def completed_receipt(tmp_path):
    image = tmp_path / "after.png"
    Image.new("RGB", (120, 80), "white").save(image)
    return {"phase": "returned", "step_id": "open-detail", "goal": "Open record detail",
        "response": {"success": True},
        "target_identity": {"handle": 10, "process_id": 20, "process_create_time": 30.0},
        "observation": {"status": "captured", "capture": {
            "capture_id": "after-detail", "image_path": str(image)}}}


def post(service, tmp_path):
    return evaluate_post_action(service, request_id="judge-1", execution_request_id="exec-1",
        decision_check={"phase": "after_action", "condition": "Record detail is visible"},
        receipt=completed_receipt(tmp_path))


def test_completed_review_advice_is_authenticated_and_carries_only_standalone_context(tmp_path):
    service = AdaptiveDecisions()
    result = post(service, tmp_path)
    assert result["verdict"] == "success"
    assert result["task_effect"] == "awaiting_agent_review"
    assert result["input_status"] == "returned" and result["effect_verified"] is None
    assert result["authorizes_action"] is False and result["automatic_retry_allowed"] is False
    assert len(service.authentication_requests) == 1
    request = service.authentication_requests[0]
    assert request["review_context"] == {
        "goal": "Open record detail", "step_goal": "Record detail is visible",
        "remaining_plan": [], "allowed_states": [], "source_id": "exec-1"}
    assert request == service.calls[0]


def test_untrusted_review_result_cannot_be_presented_as_authenticated_outcome(tmp_path):
    result = post(AdaptiveDecisions(authenticated=False), tmp_path)
    assert result["status"] == "invalid"
    assert result["reason"] == "decision_result_authentication_invalid"
    assert result["task_effect"] == "awaiting_agent_review"
    assert result["effect_verified"] is None and result["verdict"] == "uncertain"


@pytest.mark.parametrize("authenticated", [True, False])
def test_policy_skip_is_authenticated_without_losing_valid_reason(tmp_path, authenticated):
    service = AdaptiveDecisions(authenticated=authenticated)
    original_evaluate = service.evaluate

    def evaluate(**request):
        return {**original_evaluate(**request), "status": "skipped", "verdict": "uncertain",
            "reason": "decision_always_main"}

    service.evaluate = evaluate
    result = post(service, tmp_path)
    assert len(service.authentication_requests) == 1
    assert result["reason"] == ("decision_always_main" if authenticated else "decision_result_authentication_invalid")
    assert result["effect_verified"] is None and result["task_effect"] == "awaiting_agent_review"


@pytest.mark.parametrize("disposition", ["review_required", "observe", "stop", None, [], {}])
def test_adopted_success_without_continue_disposition_never_verifies_effect(tmp_path, disposition):
    result = post(AdaptiveDecisions(disposition=disposition, adopted=True), tmp_path)
    assert result["task_effect"] == "awaiting_agent_review"
    assert result["effect_verified"] is None and result["adopted"] is False


def test_authenticated_continue_can_verify_original_effect(tmp_path):
    result = post(AdaptiveDecisions(disposition="continue", adopted=True), tmp_path)
    assert result["effect_verified"] is True and result["task_effect"] == "success"


@pytest.mark.parametrize("status", ["unknown", "timeout", "error"])
def test_noncompleted_v2_result_cannot_promote_input_to_success(tmp_path, status):
    service = AdaptiveDecisions(disposition="continue", adopted=True)
    original_evaluate = service.evaluate

    def evaluate(**request):
        return {**original_evaluate(**request), "status": status}

    service.evaluate = evaluate
    result = post(service, tmp_path)
    assert result["status"] == "invalid" and result["adopted"] is False
    assert result["effect_verified"] is None and result["task_effect"] == "awaiting_agent_review"


def test_proactive_pre_action_review_stops_input_and_preserves_candidate_boundary(scene, monkeypatch):
    service = AdaptiveDecisions()
    receipt, clicks, _, target, _, _, _ = run_route(scene, monkeypatch, service)
    assert not receipt.success and clicks == [] and target.input_claimed is False
    assert receipt.error.code == "decision_check_rejected"
    assert service.calls[0]["review_context"]["remaining_plan"] == []
    assert service.calls[0]["review_context"]["step_goal"] == "Search is safe"


def test_v2_unallowlisted_pre_check_requires_main_instead_of_silently_dispatching(scene, monkeypatch):
    service = AdaptiveDecisions()
    receipt, clicks, _, target, _, _, _ = run_route(scene, monkeypatch, service,
        condition="An unapproved task condition")
    assert not receipt.success and clicks == [] and target.input_claimed is False


def test_v1_no_context_is_added_to_existing_service_request(tmp_path):
    service = Decisions()
    post(service, tmp_path)
    assert "review_context" not in service.calls[0]


def test_real_v2_service_preserves_proactive_review_through_receipt_and_reopen(tmp_path, monkeypatch):
    from app.judgment import DecisionProfile, DecisionService
    from app.judgment.openai_decisions import OpenAIDecisionsProvider
    from tests.test_openai_decisions import reply

    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert [question["name"] for question in body["questions"]] == [
            "condition_met", "visible_error", "needs_agent_review"]
        response = reply(0.98)
        response["answers"].append({"type": "predicate", "name": "needs_agent_review", "probability": 0.97})
        return httpx.Response(200, json=response)

    monkeypatch.setenv("ADAPTIVE_EXECUTION_TEST_KEY", "synthetic-test-key")
    profile = DecisionProfile(contract_version="decision_profile.v2", mode="auto",
        api_key_env="ADAPTIVE_EXECUTION_TEST_KEY", auto_conditions=["Record detail is visible"])
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        service = DecisionService(tmp_path, profile=profile,
            provider=OpenAIDecisionsProvider(api_key_env=profile.api_key_env, client=client))
        try:
            result = post(service, tmp_path)
            assert result["verdict"] == "success" and result["disposition"] == "review_required"
            assert result["effect_verified"] is None and result["task_effect"] == "awaiting_agent_review"
            assert result["input_status"] == "returned" and result["adopted"] is False
            assert service.validate_result(result["judgment_result"])
            assert len(calls) == 1
        finally:
            service.close()
    monkeypatch.delenv("ADAPTIVE_EXECUTION_TEST_KEY")
    reopened = DecisionService(tmp_path, profile=profile)
    try:
        assert post(reopened, tmp_path) == result
        assert len(calls) == 1
    finally:
        reopened.close()
