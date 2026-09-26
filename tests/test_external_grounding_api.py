"""外部视觉协议的错误、原图与候选契约；不调用付费服务或派发输入。"""
import base64
import hashlib
import json

import httpx
from PIL import Image
import pytest

from app.vision.external_grounding_api import ApiGroundingError, ApiGroundingProfile, ChatCompletionsGrounder


@pytest.fixture
def capture(tmp_path):
    path = tmp_path / "frame.png"
    Image.new("RGB", (100, 80), "white").save(path)
    return {"image_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "capture_id": "capture-1", "image_size": {"width": 100, "height": 80}}


def result():
    return {"schema_version": "grounding.v1", "request_id": "request-1", "capture_id": "capture-1",
        "status": "found", "coordinate_space": "capture_image_pixels",
        "image_size": {"width": 100, "height": 80}, "selected_candidate_id": "search",
        "candidates": [{"id": "search", "label": "搜索", "bbox": {"x": 10, "y": 10, "width": 60, "height": 30},
            "click_point": {"x": 30, "y": 20}, "evidence_source": "api_visual"}]}


def profile(**changes):
    return ApiGroundingProfile(endpoint="https://vision.example/v1/chat/completions",
        model="configured-model", api_key_env="TEST_VISION_KEY", **changes)


def reply(payload=None, **changes):
    return {"model": "provider-model", "usage": {"prompt_tokens": 30, "completion_tokens": 20,
        "total_tokens": 50}, "choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps(result() if payload is None else payload, ensure_ascii=False)}}], **changes}


def test_exact_png_utf8_and_model_provenance(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    seen = []
    def handler(request):
        seen.append(request)
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer secret-value"
        assert body["model"] == "configured-model"
        assert body["response_format"] == {"type": "json_object"}
        parts = body["messages"][1]["content"]
        assert "搜索" in parts[0]["text"]
        from pathlib import Path
        assert base64.b64decode(parts[1]["image_url"]["url"].split(",", 1)[1]) == Path(capture["image_path"]).read_bytes()
        assert "tools" not in body
        return httpx.Response(200, json=reply())
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(handler)) as provider:
        value = provider.ground(request_id="request-1", capture=capture, goal="搜索")
    assert len(seen) == 1
    assert value["result"]["candidates"][0]["label"] == "搜索"
    assert value["provider"]["requested_model"] == "configured-model"
    assert value["provider"]["returned_model"] == "provider-model"
    assert value["provider"]["usage"]["total_tokens"] == 50
    assert value["provider"]["elapsed_ms"] >= 0
    assert value["action_executed"] is False
    assert "secret-value" not in json.dumps(value)


@pytest.mark.parametrize("status,code", [(401,"api_authentication_failed"),(403,"api_access_denied"),
    (429,"api_rate_limited"),(500,"api_server_error"),(302,"api_redirect_rejected"),(400,"api_request_rejected")])
def test_http_errors_are_distinct_redacted_and_not_retried(capture, monkeypatch, status, code):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="secret-value echoed by provider", headers={"Retry-After": "7"})
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(handler)) as provider:
        with pytest.raises(ApiGroundingError) as failure:
            provider.ground(request_id="request-1", capture=capture, goal="Search")
    assert failure.value.code == code
    assert "secret-value" not in str(failure.value)
    assert len(calls) == 1


@pytest.mark.parametrize("mutation,code", [
    (lambda x: x.update(capture_id="wrong"), "api_grounding_invalid"),
    (lambda x: x["candidates"][0].update(evidence_source="agent_visual"), "api_source_mismatch"),
    (lambda x: x["candidates"][0]["click_point"].update(x=999), "api_grounding_invalid")])
def test_bad_candidates_cannot_become_ready(capture, monkeypatch, mutation, code):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    payload = result()
    mutation(payload)
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(lambda _: httpx.Response(200,json=reply(payload)))) as provider:
        with pytest.raises(ApiGroundingError, match=code):
            provider.ground(request_id="request-1",capture=capture,goal="Search")


def test_missing_key_and_changed_frame_fail_before_network(capture, monkeypatch):
    monkeypatch.delenv("TEST_VISION_KEY", raising=False)
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(lambda _: pytest.fail("network"))) as provider:
        with pytest.raises(ApiGroundingError, match="api_key_missing"):
            provider.ground(request_id="request-1",capture=capture,goal="Search")
        monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
        capture["sha256"] = "wrong"
        with pytest.raises(ApiGroundingError, match="api_capture_changed"):
            provider.ground(request_id="request-1",capture=capture,goal="Search")


@pytest.mark.parametrize("value,code", [
    ({"choices": []}, "api_response_invalid"),
    ({"choices": [{"finish_reason":"length", "message":{"content":"{}"}}]}, "api_output_truncated"),
    ({"choices": [{"finish_reason":"stop", "message":{"refusal":"no", "content":None}}]}, "api_model_refused"),
    ({"choices": [{"finish_reason":"stop", "message":{"content":"not JSON"}}]}, "api_grounding_invalid")])
def test_protocol_failures_are_not_vision_unsupported(capture, monkeypatch, value, code):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(lambda _: httpx.Response(200,json=value))) as provider:
        with pytest.raises(ApiGroundingError, match=code):
            provider.ground(request_id="request-1",capture=capture,goal="Search")


def test_timeout_and_response_bound(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    def timeout(request):
        raise httpx.ReadTimeout("secret-value", request=request)
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(timeout)) as provider:
        with pytest.raises(ApiGroundingError, match="api_timeout"):
            provider.ground(request_id="request-1",capture=capture,goal="Search")
    with ChatCompletionsGrounder(profile(max_response_bytes=1024), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x"*1025))) as provider:
        with pytest.raises(ApiGroundingError, match="api_response_too_large"):
            provider.ground(request_id="request-1",capture=capture,goal="Search")


@pytest.mark.parametrize("endpoint", ["http://remote.example/v1/chat/completions", "https://user:secret@host/api", "https://host/api?key=secret", "https://host:bad/api", "https://host:99999/api"])
def test_credentials_are_referenced_not_embedded(endpoint):
    with pytest.raises(ValueError):
        ApiGroundingProfile(endpoint=endpoint,model="model",api_key_env="TEST_VISION_KEY")


@pytest.mark.parametrize("mode", ["nul_path", "corrupt_crc"])
def test_invalid_capture_has_structured_error(capture, monkeypatch, mode):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    if mode == "nul_path":
        capture["image_path"] = "invalid\x00file"
    else:
        from pathlib import Path
        path = Path(capture["image_path"])
        data = bytearray(path.read_bytes())
        offset = data.index(b"IDAT")
        length = int.from_bytes(data[offset-4:offset], "big")
        data[offset + 4 + length] ^= 1
        path.write_bytes(data)
        capture["sha256"] = hashlib.sha256(data).hexdigest()
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(lambda _: pytest.fail("network"))) as provider:
        with pytest.raises(ApiGroundingError, match="api_capture_invalid"):
            provider.ground(request_id="request-1",capture=capture,goal="Search")


def test_slot_released_after_error_and_explicit_busy(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(lambda _: httpx.Response(200,json=reply()))) as provider:
        assert provider._slots.acquire(blocking=False)
        with pytest.raises(ApiGroundingError, match="api_busy"):
            provider.ground(request_id="request-1",capture=capture,goal="Search")
        provider._slots.release()
        assert provider.ground(request_id="request-1",capture=capture,goal="Search")["result"]["status"] == "found"
