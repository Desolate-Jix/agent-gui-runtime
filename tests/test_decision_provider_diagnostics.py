"""服务只保留适配器白名单错误码；诊断不改变失败状态、权限或原请求派发次数。"""
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from test_decision_service import arguments


PRIVATE = "synthetic-private-key https://private.invalid/account?api_key=private-value"
CONDITION = "Inspect the synthetic error state"


def service(root, monkeypatch, *, version="v2", handler=None, provider=None):
    monkeypatch.setenv("PROVIDER_DIAGNOSTIC_TEST_KEY", "synthetic-private-key")
    calls = []

    def handle(request):
        calls.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(handle))
    configuration = {"contract_version": "decision_profile." + version, "mode": "auto",
        "api_key_env": "PROVIDER_DIAGNOSTIC_TEST_KEY", "auto_conditions": [CONDITION]}
    if version == "v2":
        configuration["proactive_review"] = False
    runtime = DecisionService(root, profile=DecisionProfile.model_validate(configuration), provider=provider or
        OpenAIDecisionsProvider(api_key_env="PROVIDER_DIAGNOSTIC_TEST_KEY", client=client))
    return runtime, arguments(root, condition=CONDITION), calls, client


def assert_unchanged_failure(result, version):
    assert result["status"] == "error" and result["verdict"] == "uncertain"
    assert result["reason"] == "decision_provider_or_contract_error"
    assert result["adopted"] is False and result["authorizes_action"] is False
    assert result["automatic_retry_allowed"] is False
    if version == "v2":
        assert result["disposition"] == "review_required"
        assert "decision_provider_or_contract_error" in result["reason_codes"]


@pytest.mark.parametrize("version", ["v1", "v2"])
@pytest.mark.parametrize("fault,code", [
    ("transport", "decision_transport_error"), (401, "decision_http_status_401"),
    (429, "decision_http_status_429"), (503, "decision_http_status_503"),
    ("protocol", "decision_protocol_error"), ("large", "decision_response_too_large"),
    ("closed", "decision_provider_closed")])
def test_real_adapter_failure_exposes_only_exact_code_and_does_not_retry(tmp_path, monkeypatch, version, fault, code):
    def handle(request):
        if fault == "transport":
            raise httpx.ConnectError(PRIVATE, request=request)
        if type(fault) is int:
            return httpx.Response(fault, text=PRIVATE)
        if fault == "large":
            return httpx.Response(200, content=b"x" * 65537 + PRIVATE.encode("utf-8"))
        return httpx.Response(200, text=PRIVATE)

    runtime, args, calls, client = service(tmp_path, monkeypatch, version=version, handler=handle)
    if fault == "closed":
        runtime._provider.close()
    try:
        result = runtime.evaluate(**args)
        assert_unchanged_failure(result, version)
        assert result.get("provider_error_code") == code
        assert "synthetic-private-key" not in json.dumps(result) and "private.invalid" not in json.dumps(result)
        assert runtime.validate_result(result, **args)
        assert runtime.evaluate(**args) == result
        assert len(calls) == (0 if fault == "closed" else 1)
        forged = deepcopy(result)
        forged["provider_error_code"] = "decision_http_status_502"
        assert runtime.validate_result(forged, **args) is False
    finally:
        runtime.close()
        client.close()


@pytest.mark.parametrize("failure", [
    OSError(PRIVATE), ValueError("decision_transport_error " + PRIVATE),
    OSError("prefix_decision_transport_error"), OSError("decision_transport_error\n"),
    OSError("decision_http_status_99"), OSError("decision_http_status_600"),
    OSError("decision_http_status_0401"), OSError("decision_http_status_\u0664\u0660\u0661"),
    OSError("decision_http_status_401 " + PRIVATE), OSError("decision_http_status_401\n"),
    ValueError("decision_usage_invalid"), OSError(5, "decision_transport_error"),
    ValueError({"provider_error_code": "decision_protocol_error", "secret": PRIVATE})])
def test_unapproved_exception_payloads_do_not_escape_as_provider_codes(tmp_path, monkeypatch, failure):
    calls = []

    def judge(payload):
        calls.append(payload)
        raise failure

    runtime, args, _, client = service(tmp_path, monkeypatch, provider=SimpleNamespace(judge=judge))
    try:
        result = runtime.evaluate(**args)
        assert_unchanged_failure(result, "v2")
        assert "provider_error_code" not in result
        assert "synthetic-private-key" not in json.dumps(result) and "private.invalid" not in json.dumps(result)
        assert runtime.validate_result(result, **args)
        assert runtime.evaluate(**args) == result and len(calls) == 1
    finally:
        runtime.close()
        client.close()


def test_provider_code_survives_reopen_without_dispatching_again(tmp_path, monkeypatch):
    runtime, args, calls, client = service(tmp_path, monkeypatch, handler=lambda request: httpx.Response(429, text=PRIVATE))
    result = runtime.evaluate(**args)
    runtime.close()
    client.close()
    reopened, _, next_calls, next_client = service(tmp_path, monkeypatch,
        handler=lambda request: pytest.fail("saved error cannot dispatch again"))
    try:
        assert result.get("provider_error_code") == "decision_http_status_429"
        assert reopened.evaluate(**args) == result and reopened.validate_result(result, **args)
        assert len(calls) == 1 and next_calls == []
    finally:
        reopened.close()
        next_client.close()
