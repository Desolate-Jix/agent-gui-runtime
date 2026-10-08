"""真实传输适配器的离线协议回归；不读取用户凭据。"""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest


def reply(probability=0.97, danger=0.01):
    return {"model": "gpt-6-luna", "answers": [
        {"type": "predicate", "name": "condition_met", "probability": probability},
        {"type": "predicate", "name": "visible_error", "probability": danger}],
        "usage": {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12,
                  "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                  "output_tokens_details": {"reasoning_tokens": 0}}}


def payload():
    return {"condition": "详情已打开", "phase": "after_action", "frames": [
        {"role": "after", "capture_id": "c1", "data_url": "data:image/png;base64,aGVsbG8="}],
        "request_sha256": "a" * 64, "action": None}


def test_provider_batches_shared_images_and_preserves_real_usage_and_timings(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    captured = []
    def handle(request):
        captured.append(request)
        return httpx.Response(200, json=reply(), headers={"openai-processing-ms": "564", "x-request-id": "req-123"})
    client = httpx.Client(transport=httpx.MockTransport(handle))
    provider = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client, timeout_seconds=3)
    result = provider.judge(payload())
    body = json.loads(captured[0].content)
    assert str(captured[0].url) == "https://api.openai.com/v1/decisions"
    assert captured[0].method == "POST" and len(captured) == 1
    assert body["model"] == "gpt-6-luna"
    assert [item["name"] for item in body["questions"]] == ["condition_met", "visible_error"]
    assert len([part for part in body["input"][0]["content"] if part["type"] == "input_image"]) == 1
    assert "详情已打开" in body["questions"][0]["instructions"]
    assert result["predicates"]["condition_met"] == {"type": "predicate", "probability": 0.97}
    assert result["usage"]["total_tokens"] == 12 and result["server_processing_ms"] == 564
    assert result["http_elapsed_ms"] >= 0 and result["provider_request_id"] == "req-123"
    assert captured[0].extensions["timeout"]["read"] == 3
    provider.close()
    assert not client.is_closed
    client.close()


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(model="other"),
    lambda r: r["answers"][0].update(probability=True),
    lambda r: r["answers"][0].update(probability="0.99"),
    lambda r: r["answers"][0].update(probability=float("nan")),
    lambda r: r["answers"][0].update(probability=1.1),
    lambda r: r["answers"][0].update(name="unrequested"),
    lambda r: r["answers"].append(r["answers"][0]),
    lambda r: r["answers"][0].update(click_point=[1, 2]),
    lambda r: r["usage"].update(input_tokens=True),
    lambda r: r["usage"].update(total_tokens=1),
])
def test_provider_rejects_malformed_contract_without_retry(monkeypatch, mutation):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    body = reply()
    mutation(body)
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, content=json.dumps(body).encode("utf-8"))
    client = httpx.Client(transport=httpx.MockTransport(handle))
    with pytest.raises(ValueError):
        OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge(payload())
    assert len(calls) == 1
    client.close()


def test_refusal_remains_distinct_without_inventing_probability(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    body = reply()
    body["answers"][0] = {"type": "refusal", "name": "condition_met"}
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        result = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge(payload())
    assert result["predicates"]["condition_met"] == {"type": "refusal", "probability": None}


def test_server_diagnostics_cannot_echo_the_credential(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=reply(),
        headers={"x-request-id": "synthetic-secret", "openai-processing-ms": "synthetic-secret"}))) as client:
        result = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client).judge(payload())
    assert result["provider_request_id"] is None and result["server_processing_ms"] is None
    assert "synthetic-secret" not in json.dumps(result)


def test_owned_client_is_created_lazily_reused_and_closed(monkeypatch):
    import app.judgment.openai_decisions as module
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    created, requests = [], []
    original_client = httpx.Client
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=reply())
    def create_client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        client = original_client(**kwargs)
        created.append(client)
        return client
    def transport(*, retries):
        assert retries == 0
        return httpx.MockTransport(handle)
    monkeypatch.setattr(module.httpx, "Client", create_client)
    monkeypatch.setattr(module.httpx, "HTTPTransport", transport)
    provider = module.OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY")
    assert not created
    assert provider.judge(payload())["usage"]["input_tokens"] == 12
    assert provider.judge(payload())["usage"]["input_tokens"] == 12
    assert len(created) == 1 and len(requests) == 2
    provider.close()
    assert created[0].is_closed


def test_queued_request_times_out_without_second_dispatch(monkeypatch):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    entered, release = Event(), Event()
    requests = []
    def handle(request):
        requests.append(request)
        entered.set()
        assert release.wait(2)
        return httpx.Response(200, json=reply())
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client, timeout_seconds=0.02)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(provider.judge, payload())
            assert entered.wait(1)
            try:
                with pytest.raises(TimeoutError):
                    provider.judge(payload())
            finally:
                release.set()
            assert pending.result(timeout=1)["usage"]["input_tokens"] == 12
    assert len(requests) == 1


@pytest.mark.parametrize("kind", ["timeout", "redirect", "http_error", "json_error"])
def test_transport_failures_are_bounded_no_retry_and_do_not_expose_secret(monkeypatch, kind):
    from app.judgment import OpenAIDecisionsProvider
    monkeypatch.setenv("DECISION_TEST_KEY", "synthetic-secret")
    calls = []
    def handle(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("synthetic-secret", request=request)
        if kind == "redirect":
            return httpx.Response(307, headers={"location": "https://evil.invalid"})
        if kind == "json_error":
            return httpx.Response(200, text="synthetic-secret")
        return httpx.Response(401, text="synthetic-secret")
    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        provider = OpenAIDecisionsProvider(api_key_env="DECISION_TEST_KEY", client=client)
        with pytest.raises((TimeoutError, OSError, ValueError)) as error:
            provider.judge(payload())
    assert len(calls) == 1 and "synthetic-secret" not in str(error.value)
