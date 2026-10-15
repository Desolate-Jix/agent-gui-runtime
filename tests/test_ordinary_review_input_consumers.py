"""两层判断必须被输入前缀及历史策略读取；认证或原始绑定不能省略。"""
from copy import deepcopy

import httpx
import pytest

from app.core.input_sequence_partial import original_input_status, _click_before_enter_verified, _request
from app.core.visual_typing_strategy import validated_effective_typing_request
from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from tests.test_luna_choice_review_provider import decision_body, response_body
from tests.test_visual_empty_input import scene
from tests.test_visual_empty_partial import sequence_command
from tests.test_visual_enter_preparation_partial import historical_stopped_enter, stopped_enter, receipt_for
from tests.test_visual_empty_input import visual_sequence
from tests.test_visual_field_proof import IDENTITY


def reviewing_service(previous):
    profile = DecisionProfile.model_validate({**previous.profile.model_dump(mode="json"), "ordinary_review": "on_reject"})
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=decision_body() if request.url.path == "/v1/decisions" else response_body())
    client = httpx.Client(transport=httpx.MockTransport(handle))
    service = DecisionService(previous.session_dir, profile=profile,
        provider=OpenAIDecisionsProvider(api_key_env="VISUAL_FIELD_TEST_KEY", client=client))
    return service, client, calls


@pytest.fixture
def reviewed_prefix(historical_stopped_enter):
    v, original, previous, _ = historical_stopped_enter
    service, client, calls = reviewing_service(previous)
    profile = service.profile
    result = deepcopy(original)
    evidences = [result["visual_click_evidence"], result["enter_preparation_failure"]["evidence"]]
    for index, evidence in enumerate(evidences):
        request = evidence["request"]
        request["request_id"] += "-ordinary-consumer"
        evidence["profile"] = profile.model_dump(mode="json", exclude_unset=True)
        evidence["assessment"] = service.evaluate(**request)
        answer = evidence["assessment"]
        assert answer["choice_result"]["choice"] == "condition_not_met"
        assert answer["ordinary_review"]["review_result"]["choice"] == "condition_met"
        assert answer["adopted"] is True and service.validate_result(answer, **request)
        result["field_proofs"][index]["request_sha256"] = answer["request_sha256"]
    result["enter_preparation_failure"]["value_request_sha256"] = evidences[1]["assessment"]["request_sha256"]
    try:
        yield v, result, service, calls
    finally:
        service.close()
        client.close()


def test_current_compound_prefix_uses_authenticated_second_opinion(stopped_enter):
    v, original, previous, _ = stopped_enter
    service, client, calls = reviewing_service(previous)
    result = deepcopy(original)
    evidence = result["enter_preparation_failure"]["evidence"]
    request = evidence["request"]
    request["request_id"] += "-ordinary-consumer"
    evidence["profile"] = service.profile.model_dump(mode="json", exclude_unset=True)
    evidence["assessment"] = service.evaluate(**request)
    answer = evidence["assessment"]
    assert answer["adopted"] is True and service.validate_result(answer, **request)
    result["field_proofs"][0]["request_sha256"] = answer["request_sha256"]
    result["enter_preparation_failure"]["value_request_sha256"] = answer["request_sha256"]
    receipt = receipt_for(result)
    before, events = deepcopy(receipt), deepcopy(v.events)
    try:
        assert original_input_status(receipt, receipt["command"], succeeded=False,
            action_executed=True, target_identity=IDENTITY) == "failed"
        assert receipt == before and v.events == events and len(calls) == 2
    finally:
        service.close()
        client.close()


def test_authenticated_second_opinion_settles_known_enter_prefix_without_new_input(reviewed_prefix):
    v, result, service, calls = reviewed_prefix
    receipt = receipt_for(result)
    before = deepcopy(receipt)
    before_calls, before_events = len(calls), deepcopy(v.events)
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "failed"
    assert receipt == before and len(calls) == before_calls and v.events == before_events


def test_authenticated_second_opinion_is_final_choice_for_recorded_click(reviewed_prefix):
    _, result, service, calls = reviewed_prefix
    before = deepcopy(result)
    assert _click_before_enter_verified(service, result["visual_click_evidence"], result,
        _request(sequence_command()["request"]), IDENTITY) is True
    assert result == before and len(calls) == 4


@pytest.mark.parametrize("damage", ["click_auth", "value_auth", "value_request", "click_reference"])
def test_second_opinion_never_bypasses_authentication_or_original_binding(reviewed_prefix, damage):
    _, result, _, calls = reviewed_prefix
    receipt = receipt_for(deepcopy(result))
    forged = receipt["result"]
    if damage == "click_auth":
        forged["visual_click_evidence"]["assessment"]["ordinary_review"]["provider_request_id"] = "forged"
    elif damage == "value_auth":
        forged["enter_preparation_failure"]["evidence"]["assessment"]["ordinary_review"]["provider_request_id"] = "forged"
    elif damage == "value_request":
        forged["enter_preparation_failure"]["evidence"]["request"]["execution_request_id"] += "-wrong"
    else:
        forged["field_proofs"][0]["request_sha256"] = "0" * 64
    before = deepcopy(receipt)
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "unknown"
    assert receipt == before and len(calls) == 4


def legacy_ocr_strategy(result, service):
    from app.execution.field_content_ocr import read_field_content
    result = deepcopy(result)
    evidence = result.pop("visual_click_evidence")
    request = evidence["request"]
    request["request_id"] += "-ocr"
    request["condition"] = "The marked click is inside the intended visible text input and the field is usable for typing now."
    request["action"]["field_content_ocr"] = {"schema": "visual_field_content_ocr.v1", "clear_existing": True,
        "reading": read_field_content(frame=request["frames"][0], field=request["action"]["field"],
            session_dir=service.session_dir)}
    evidence["assessment"] = service.evaluate(**request)
    assert service.validate_result(evidence["assessment"], **request) and evidence["assessment"]["adopted"]
    digest = evidence["assessment"]["request_sha256"]
    result["typing_strategy_evidence"] = evidence
    result["typing_strategy"] = {"schema": "visual_typing_strategy.v2", "requested_clear_existing": True,
        "effective_clear_existing": True, "reason": "replace_existing", "focus_request_sha256": digest}
    result["field_proofs"][0]["request_sha256"] = digest
    result["field_proofs"][0]["field_content_ocr"] = deepcopy(request["action"]["field_content_ocr"])
    return result


def test_historical_ocr_strategy_uses_authenticated_final_choice(reviewed_prefix):
    v, prefix, service, calls = reviewed_prefix
    result = legacy_ocr_strategy(prefix, service)
    request = sequence_command()["request"]
    before, events = deepcopy(result), deepcopy(v.events)
    assert validated_effective_typing_request(result, request) == request
    assert result == before and v.events == events and len(calls) == 6
    receipt = receipt_for(result)
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "failed"


def test_historical_ocr_strategy_rejects_tampered_second_opinion(reviewed_prefix):
    _, prefix, service, calls = reviewed_prefix
    result = legacy_ocr_strategy(prefix, service)
    result["typing_strategy_evidence"]["assessment"]["ordinary_review"]["provider_request_id"] = "forged"
    with pytest.raises(ValueError, match="^visual_typing_strategy_invalid$"):
        validated_effective_typing_request(result, sequence_command()["request"])
    assert len(calls) == 6
