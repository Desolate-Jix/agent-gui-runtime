"""分别配置两层连接时，真实服务仍认证原回执且不重复派发。"""
from copy import deepcopy
import json

import httpx
import pytest

from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from app.judgment.openai_decisions import ENDPOINT, REVIEW_ENDPOINT
from test_adaptive_decision_policy import context
from test_decision_choice import choice_reply
from test_decision_service import arguments
from test_luna_choice_review_provider import response_body
from test_openai_decisions import reply


@pytest.fixture
def runtime(monkeypatch):
    resources = []
    monkeypatch.setenv("CONFIG_DECISION_KEY", "synthetic-primary-key")
    monkeypatch.setenv("CONFIG_REVIEW_KEY", "synthetic-secondary-key")

    def build(root, *, first="condition_not_met", second="condition_met", **patch):
        config = {"contract_version": "decision_profile.v2", "mode": "auto", "decision_format": "choice",
                  "ordinary_review": "on_reject", "api_key_env": "CONFIG_DECISION_KEY",
                  "auto_conditions": ["\u8be6\u60c5\u5df2\u6253\u5f00"], **patch}
        if config["contract_version"] == "decision_profile.v1":
            config.pop("decision_format")
            config.pop("ordinary_review")
        calls = []

        def handle(request):
            calls.append(request)
            sent = json.loads(request.content)
            body = (reply() if sent["questions"][0]["type"] == "predicate" else choice_reply(first)) \
                if "questions" in sent else response_body(second)
            body["model"] = sent["model"]
            return httpx.Response(200, json=body)

        client = httpx.Client(transport=httpx.MockTransport(handle))
        monkeypatch.setattr("app.judgment.service.OpenAIDecisionsProvider",
                            lambda **kwargs: OpenAIDecisionsProvider(client=client, **kwargs))
        service = DecisionService(root, profile=DecisionProfile.model_validate(config))
        resources.append((service, client))
        return service, calls

    yield build
    for service, client in resources:
        service.close()
        client.close()


def test_service_factory_routes_each_stage_and_authenticates_custom_model_receipt(tmp_path, runtime, monkeypatch):
    service, calls = runtime(tmp_path, endpoint="https://decision.example.invalid/v1/decisions",
        model="decision-custom", ordinary_review_endpoint="https://review.example.invalid/v1/responses",
        ordinary_review_model="review-custom", ordinary_review_api_key_env="CONFIG_REVIEW_KEY")
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result["adopted"] and result["judged_by"] == "ordinary_review"
    assert result["model"] == service.status()["model"] == "decision-custom"
    assert result["ordinary_review_model"] == service.status()["ordinary_review_model"] == "review-custom"
    assert result["source"] == "openai_decisions"
    assert [str(call.url) for call in calls] == ["https://decision.example.invalid/v1/decisions",
                                               "https://review.example.invalid/v1/responses"]
    assert [json.loads(call.content)["model"] for call in calls] == ["decision-custom", "review-custom"]
    assert [call.headers["authorization"] for call in calls] == ["Bearer synthetic-primary-key",
                                                               "Bearer synthetic-secondary-key"]
    assert result["usage"]["total_tokens"] == 30 and service.status()["used"] == 2
    assert service.validate_result(result, **args)
    tampered = deepcopy(result)
    tampered["judged_by"] = "ordinary_luna"
    assert not service.validate_result(tampered, **args)
    for name in ("CONFIG_DECISION_KEY", "CONFIG_REVIEW_KEY"):
        monkeypatch.delenv(name)
    reopened = DecisionService(tmp_path, profile=service.profile)
    monkeypatch.setattr(reopened, "_get_provider", lambda: pytest.fail("saved request dispatched again"))
    assert reopened.evaluate(**args) == result
    assert reopened.validate_result(result, **args) and len(calls) == 2
    assert "synthetic-primary-key" not in json.dumps(result)
    assert "synthetic-secondary-key" not in json.dumps(result)


def test_omitted_connection_fields_keep_default_routes_key_and_review_label(tmp_path, runtime):
    service, calls = runtime(tmp_path)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result["adopted"] and result["judged_by"] == "ordinary_luna"
    assert result["model"] == service.status()["model"] == "gpt-6-luna"
    assert "ordinary_review_model" not in result and "ordinary_review_model" not in service.status()
    assert [str(call.url) for call in calls] == [ENDPOINT, REVIEW_ENDPOINT]
    assert {call.headers["authorization"] for call in calls} == {"Bearer synthetic-primary-key"}
    assert service.validate_result(result, **args)


@pytest.mark.parametrize("first", ["condition_met", "condition_not_met"])
def test_missing_explicit_secondary_key_never_blocks_primary_or_spends_secondary(tmp_path, runtime, monkeypatch, first):
    monkeypatch.delenv("CONFIG_REVIEW_KEY")
    service, calls = runtime(tmp_path, first=first, ordinary_review_api_key_env="CONFIG_REVIEW_KEY")
    assert service.readiness() == {"ready": True, "status": "ready"}
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert len(calls) == service.status()["used"] == 1
    if first == "condition_met":
        assert result["adopted"] and "ordinary_review" not in result
    else:
        assert not result["adopted"] and result["disposition"] == "review_required"
        assert result["ordinary_review"]["reason"] == "ordinary_review_unavailable"
        monkeypatch.setenv("CONFIG_REVIEW_KEY", "new-synthetic-key")
        assert service.evaluate(**args) == result and len(calls) == 1
    assert service.validate_result(result, **args)


@pytest.mark.parametrize("patch", [
    {"endpoint": "https://different.example.invalid/v1/decisions"}, {"model": "different-decision"},
    {"api_key_env": "DIFFERENT_PRIMARY_KEY"},
    {"ordinary_review_endpoint": "https://different.example.invalid/v1/responses"},
    {"ordinary_review_model": "different-review"}, {"ordinary_review_api_key_env": "DIFFERENT_REVIEW_KEY"}])
def test_connection_configuration_changes_cannot_adopt_or_reissue_prior_request(tmp_path, runtime, patch):
    service, calls = runtime(tmp_path, first="condition_met")
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    changed = DecisionProfile.model_validate({**service.profile.model_dump(mode="json"), **patch})
    reopened = DecisionService(tmp_path, profile=changed)
    assert not reopened.validate_result(result, **args)
    conflict = reopened.evaluate(**args)
    assert conflict["status"] == "conflict" and len(calls) == 1


@pytest.mark.parametrize("patch", [{"ordinary_review_model": "review-custom"},
    {"ordinary_review_endpoint": "https://review.example.invalid/v1/responses"}])
@pytest.mark.parametrize("second", ["condition_met", "condition_not_met"])
def test_custom_review_never_claims_default_luna_for_pass_or_nonpass(tmp_path, runtime, patch, second):
    service, calls = runtime(tmp_path, second=second, **patch)
    args = arguments(tmp_path, review_context=context())
    result = service.evaluate(**args)
    assert result["judged_by"] == "ordinary_review" and len(calls) == 2
    assert result["ordinary_review_model"] == patch.get("ordinary_review_model", "gpt-6-luna")
    assert result["adopted"] is (second == "condition_met")
    assert service.validate_result(result, **args)


@pytest.mark.parametrize("patch", [
    {"endpoint": "https://different.example.invalid/v1/decisions"}, {"model": "different-decision"},
    {"api_key_env": "DIFFERENT_PRIMARY_KEY"},
    {"ordinary_review_endpoint": "https://different.example.invalid/v1/responses"},
    {"ordinary_review_model": "different-review"}, {"ordinary_review_api_key_env": "DIFFERENT_REVIEW_KEY"}])
def test_v1_explicit_connections_bind_all_effective_routes_without_replaying(tmp_path, runtime, patch):
    service, calls = runtime(tmp_path, contract_version="decision_profile.v1", model="decision-custom")
    args = arguments(tmp_path)
    result = service.evaluate(**args)
    assert result["adopted"] and service.validate_result(result, **args)
    changed = DecisionProfile.model_validate({**service.profile.model_dump(mode="json"), **patch})
    reopened = DecisionService(tmp_path, profile=changed)
    assert not reopened.validate_result(result, **args)
    assert reopened.evaluate(**args)["status"] == "conflict" and len(calls) == 1
