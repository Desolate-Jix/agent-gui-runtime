"""首请求分段计时使用离线传输和回环 HTTP，不读取真实凭据。"""
import asyncio
import json

import httpx
import pytest

from app.judgment import OpenAIDecisionsProvider
from tests.test_decision_connection_reuse import _loopback_server, loopback_network_only, payload as choice_payload
from tests.test_decision_service import arguments, setup_service
from tests.test_openai_decisions import payload, reply


def test_first_owned_client_records_connection_but_reused_connection_does_not(monkeypatch):
    monkeypatch.setenv("FIRST_TIMING_TEST_KEY", "synthetic-loopback-only")
    with _loopback_server() as (url, state):
        provider = OpenAIDecisionsProvider(api_key_env="FIRST_TIMING_TEST_KEY", endpoint=url + "/v1/decisions")
        try:
            first = provider.judge(choice_payload())["provider_timings"]
            second = provider.judge(choice_payload())["provider_timings"]
        finally:
            provider.close()
    assert first["client_created"] is True and second["client_created"] is False
    assert [item["connection"] for item in state.requests] == [1, 1]
    assert state.requests[0]["body"] == state.requests[1]["body"]
    assert any(item["name"] == "connection.connect_tcp" and item["status"] == "complete"
        for item in first["transport_spans"])
    assert not any(item["name"] == "connection.connect_tcp" for item in second["transport_spans"])
    for timing in (first, second):
        assert timing["schema"] == "decision_provider_timings.v1"
        assert any(item["name"] == "http11.receive_response_headers" for item in timing["transport_spans"])
        assert all(timing[name] >= 0 for name in
            ("preparation_ms", "queue_wait_ms", "client_setup_ms", "http_ms", "parse_ms", "total_ms"))
        assert sum(timing[name] for name in
            ("preparation_ms", "queue_wait_ms", "client_setup_ms", "http_ms", "parse_ms")) <= timing["total_ms"]


def test_service_separates_local_stages_and_authenticates_them(tmp_path, monkeypatch):
    import app.judgment.service as service_module
    import app.judgment.openai_decisions as provider_module
    clock = [0]
    monkeypatch.setattr(service_module, "perf_counter_ns", lambda: clock[0])
    monkeypatch.setattr(provider_module, "perf_counter_ns", lambda: clock[0])

    def handle(request):
        clock[0] += 41_000_000
        return httpx.Response(200, json=reply())

    runtime, calls, client = setup_service(tmp_path, monkeypatch, handler=handle)
    for name, elapsed in (("_prepare", 11), ("_connect", 13), ("_get_provider", 17)):
        original = getattr(runtime, name)

        def measured(*args, _original=original, _elapsed=elapsed, **kwargs):
            value = _original(*args, **kwargs)
            clock[0] += _elapsed * 1_000_000
            return value

        monkeypatch.setattr(runtime, name, measured)
    args = arguments(tmp_path)
    try:
        result = runtime.evaluate(**args)
        timing = result["stage_timings"]
        assert timing["schema"] == "decision_stage_timings.v1"
        assert timing["service"] == {"evidence_prepare_ms": 11, "admission_ms": 13,
            "provider_lookup_ms": 17, "provider_call_ms": 41, "result_assessment_ms": 0}
        assert timing["provider"]["http_ms"] == result["http_elapsed_ms"] == 41
        assert result["elapsed_ms"] == 82
        assert result["status"] == "completed" and result["automatic_retry_allowed"] is False
        assert runtime.validate_result(result, **args)
        assert runtime.evaluate(**args) == result and len(calls) == 1
    finally:
        runtime.close()
        client.close()


@pytest.mark.parametrize("fault,expected_status", [
    ("transport", "error"), ("protocol", "error"), (503, "error"), ("timeout", "timeout")])
def test_failed_call_keeps_numeric_trace_without_private_details_or_redispatch(
        tmp_path, monkeypatch, fault, expected_status):
    secret = "synthetic-private-host-key-and-body"

    def handle(request):
        async def emit():
            trace = request.extensions["trace"]
            await trace("connection.connect_tcp.started", {"host": secret, "port": 443})
            await trace("connection.connect_tcp.complete", {"return_value": secret})
            await trace("connection.start_tls.started", {"ssl_context": secret, "server_hostname": secret})
            await trace("connection.start_tls.failed", {"exception": RuntimeError(secret)})
            await trace("unrecognized.private.started", {"secret": secret})

        asyncio.run(emit())
        if fault == "transport":
            raise httpx.ConnectError(secret, request=request)
        if fault == "timeout":
            raise httpx.ReadTimeout(secret, request=request)
        return httpx.Response(fault if type(fault) is int else 200, text=secret)

    runtime, calls, client = setup_service(tmp_path, monkeypatch, handler=handle)
    args = arguments(tmp_path)
    try:
        result = runtime.evaluate(**args)
        assert result["status"] == expected_status and result["adopted"] is False
        assert result["automatic_retry_allowed"] is False and result["authorizes_action"] is False
        timing = result["stage_timings"]["provider"]
        assert timing["http_ms"] >= 0 and timing["total_ms"] >= timing["http_ms"]
        assert [{"name": item["name"], "status": item["status"]} for item in timing["transport_spans"]] == [
            {"name": "connection.connect_tcp", "status": "complete"},
            {"name": "connection.start_tls", "status": "failed"}]
        assert all(set(item) == {"name", "status", "elapsed_ms"} for item in timing["transport_spans"])
        assert secret not in json.dumps(result)
        assert runtime.validate_result(result, **args)
        assert runtime.evaluate(**args) == result and len(calls) == 1
    finally:
        runtime.close()
        client.close()


def test_ordinary_review_does_not_change_its_strict_reply_contract(monkeypatch):
    from tests.test_luna_choice_review_provider import response_body
    monkeypatch.setenv("FIRST_TIMING_TEST_KEY", "synthetic-mock-only")
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response_body()))) as client:
        provider = OpenAIDecisionsProvider(api_key_env="FIRST_TIMING_TEST_KEY", client=client)
        result = provider.review(choice_payload())
    assert set(result) == {"request_sha256", "review_result", "usage", "http_elapsed_ms",
        "server_processing_ms", "provider_request_id"}
