"""外部视觉协议的错误、原图与候选契约；不调用付费服务或派发输入。"""
import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image
import pytest

from app.vision.external_grounding_api import ApiGroundingError, ApiGroundingProfile, ChatCompletionsGrounder
from app.vision import external_grounding_api as api


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
    attempt = value["provider"]["attempt"]
    assert attempt["status"] == "success"
    assert attempt["started_ns"] <= attempt["ended_ns"]
    assert attempt["usage"] == {"input_tokens": 30, "output_tokens": 20, "total_tokens": 50}
    assert set(attempt) == {"started_ns", "ended_ns", "status", "usage"}
    assert value["action_executed"] is False
    assert "secret-value" not in json.dumps(value)


def test_default_transport_reuses_one_deadline_pool_and_keeps_provider_reasoning(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    pools, calls = [], []
    def factory(**options):
        pools.append(options)
        def handler(request):
            calls.append(request)
            assert "reasoning_effort" not in json.loads(request.content)
            assert request.headers["Accept-Encoding"] == "identity"
            assert request.extensions["total_deadline"] > api.time.monotonic()
            assert 0 < request.extensions["timeout"]["read"] <= 45.0
            return httpx.Response(200, json=reply())
        return httpx.MockTransport(handler)
    monkeypatch.setattr(api, "DeadlineHTTPTransport", factory)
    with ChatCompletionsGrounder(profile()) as provider:
        client = provider._client
        provider.ground(request_id="request-1", capture=capture, goal="Search")
        provider.ground(request_id="request-1", capture=capture, goal="Search")
        assert provider._client is client
    assert len(pools) == 1
    assert {key: value for key, value in pools[0].items() if key != "limits"} == {
        "max_response_bytes": 262144, "error_prefix": "api", "thread_name": "vision-api-http"}
    limits = pools[0]["limits"]
    assert limits.max_connections == limits.max_keepalive_connections == 1
    assert limits.keepalive_expiry == 60.0
    assert len(calls) == 2


def test_reasoning_none_is_explicit_only_and_does_not_change_other_wire_content(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "synthetic-secret")
    calls, outputs = [], []
    usage = {"prompt_tokens": 30, "completion_tokens": 20, "total_tokens": 50,
        "completion_tokens_details": {"reasoning_tokens": 7}}
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(usage=usage))
    for changes in ({}, {"reasoning_effort": None}, {"reasoning_effort": "none"}):
        with ChatCompletionsGrounder(profile(**changes), transport=httpx.MockTransport(handle)) as grounder:
            outputs.append(grounder.ground(request_id="request-1", capture=capture, goal="Search"))
    assert calls[0].content == calls[1].content
    original = json.loads(calls[0].content)
    explicit = json.loads(calls[2].content)
    assert "reasoning_effort" not in original and explicit.pop("reasoning_effort") == "none"
    assert explicit == original
    assert [output["provider"]["requested_reasoning_effort"] for output in outputs] == [None, None, "none"]
    assert all(output["provider"]["usage"] == usage for output in outputs)
    assert all(output["result"] == outputs[0]["result"] for output in outputs)
    assert all(output["provider"]["attempts"] == 1 for output in outputs)


def test_reasoning_none_and_omission_preserve_profile_serialization():
    omitted = profile()
    explicit_null = profile(reasoning_effort=None)
    assert omitted.reasoning_effort is None
    assert omitted.model_dump() == explicit_null.model_dump()
    assert omitted.model_dump_json() == explicit_null.model_dump_json()
    assert "reasoning_effort" not in omitted.model_dump()
    assert profile(reasoning_effort="none").model_dump()["reasoning_effort"] == "none"


@pytest.mark.parametrize("value", [True, 0, "", "NONE", "low", {"effort": "none"}, ["none"]])
def test_reasoning_configuration_rejects_unimplemented_values(value):
    with pytest.raises(ValueError):
        profile(reasoning_effort=value)


@pytest.mark.parametrize("protocol", ["responses_json", "decisions"])
def test_reasoning_configuration_never_ignores_an_unsupported_protocol(tmp_path, protocol):
    path = tmp_path / "unsupported-protocol.json"
    path.write_text(json.dumps({**profile().model_dump(), "protocol": protocol, "reasoning_effort": "none"}), encoding="utf-8")
    with pytest.raises(api.ApiGroundingError, match="api_profile_invalid"):
        api.load_api_grounding_profile(path)


def test_reasoning_rejection_is_not_retried_without_parameter(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "synthetic-secret")
    calls = []
    def handle(request):
        calls.append(request)
        assert json.loads(request.content)["reasoning_effort"] == "none"
        return httpx.Response(400, text="unsupported reasoning_effort synthetic-secret")
    with ChatCompletionsGrounder(profile(reasoning_effort="none"), transport=httpx.MockTransport(handle)) as grounder:
        with pytest.raises(api.ApiGroundingError, match="api_request_rejected") as failure:
            grounder.ground(request_id="request-1", capture=capture, goal="Search")
    assert len(calls) == 1 and failure.value.attempt["status"] == "failure"
    assert "synthetic-secret" not in str(failure.value)


def test_reasoning_experiment_example_is_separate_from_maintained_default():
    root = Path(__file__).resolve().parents[1] / "configs"
    default = api.load_api_grounding_profile(root / "vision-api-openai-luna.example.json")
    experiment = api.load_api_grounding_profile(root / "vision-api-openai-luna.no-reasoning.example.json")
    assert default.reasoning_effort is None and experiment.reasoning_effort == "none"
    configured = experiment.model_dump()
    assert configured.pop("reasoning_effort") == "none" and configured == default.model_dump()


def test_explicit_resize_maps_geometry_back_to_original_capture(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    path = Path(capture["image_path"])
    Image.new("RGB", (400, 300), "white").save(path)
    original = path.read_bytes()
    capture.update(sha256=hashlib.sha256(original).hexdigest(), image_size={"width": 400, "height": 300})
    calls = []
    def handler(request):
        calls.append(request)
        parts = json.loads(request.content)["messages"][1]["content"]
        context = json.loads(parts[0]["text"])
        assert context["capture_id"] == "capture-1"
        assert context["image_size"] == {"width": 200, "height": 150}
        with Image.open(BytesIO(base64.b64decode(parts[1]["image_url"]["url"].split(",", 1)[1]))) as image:
            assert image.size == (200, 150)
        payload = result()
        payload["image_size"] = context["image_size"]
        return httpx.Response(200, json=reply(payload))
    with ChatCompletionsGrounder(profile(max_image_edge=200), transport=httpx.MockTransport(handler)) as provider:
        value = provider.ground(request_id="request-1", capture=capture, goal="Search")
    assert len(calls) == 1
    assert path.read_bytes() == original
    assert value["result"]["image_size"] == capture["image_size"]
    candidate = value["result"]["candidates"][0]
    assert candidate["bbox"] == {"x": 20, "y": 20, "width": 120, "height": 60}
    assert candidate["click_point"] == {"x": 60, "y": 40}
    assert value["provider"]["image_preprocess"]["original_sha256"] == capture["sha256"]
    assert value["provider"]["image_preprocess"]["inference_size"] == {"width": 200, "height": 150}


def test_resized_model_geometry_is_validated_before_mapping(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    payload = result()
    payload["image_size"] = {"width": 50, "height": 40}
    payload["candidates"][0].update(bbox={"x": 10, "y": 10, "width": 40, "height": 20},
                                    click_point={"x": 60, "y": 20})
    with ChatCompletionsGrounder(profile(max_image_edge=50), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=reply(payload)))) as provider:
        with pytest.raises(ApiGroundingError, match="api_grounding_invalid") as failure:
            provider.ground(request_id="request-1", capture=capture, goal="Search")
    assert failure.value.attempt["status"] == "failure"


def test_resize_maps_rounded_axes_and_edge_box_without_clamping(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    path = Path(capture["image_path"])
    Image.new("RGB", (101, 81), "white").save(path)
    capture.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), image_size={"width": 101, "height": 81})
    payload = result()
    payload["image_size"] = {"width": 50, "height": 40}
    payload["candidates"][0].update(bbox={"x": 49, "y": 39, "width": 1, "height": 1},
                                    click_point={"x": 49, "y": 39})
    with ChatCompletionsGrounder(profile(max_image_edge=50), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=reply(payload)))) as provider:
        value = provider.ground(request_id="request-1", capture=capture, goal="Search")
    candidate = value["result"]["candidates"][0]
    assert candidate["bbox"] == {"x": 98, "y": 78, "width": 3, "height": 3}
    assert candidate["click_point"] == {"x": 98, "y": 78}


@pytest.mark.parametrize("max_edge", [None, 1280])
def test_pixel_bound_rejects_compressed_large_image_before_decode(capture, monkeypatch, max_edge):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    capture["image_size"] = {"width": 40001, "height": 1000}
    class HeaderOnlyImage:
        width, height, size, format = 40001, 1000, (40001, 1000), "PNG"
        def __enter__(self):
            return self
        def __exit__(self, *_):
            pass
        def verify(self):
            pytest.fail("pixel bound must precede image verification/decode")
        def convert(self, *_):
            pytest.fail("oversized compressed image must not decode")
    monkeypatch.setattr(api.Image, "open", lambda _: HeaderOnlyImage())
    with ChatCompletionsGrounder(profile(max_image_edge=max_edge), transport=httpx.MockTransport(
            lambda _: pytest.fail("network"))) as provider:
        with pytest.raises(ApiGroundingError, match="api_image_too_many_pixels") as failure:
            provider.ground(request_id="request-1", capture=capture, goal="Search")
    assert failure.value.attempt is None


def test_total_deadline_consumed_before_dispatch_does_not_call_provider(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    clock = {"now": 10.0}
    monkeypatch.setattr(api.time, "monotonic", lambda: clock["now"])
    original_prepare = api._prepare_api_image
    def prepare(*args, **kwargs):
        value = original_prepare(*args, **kwargs)
        clock["now"] += 46.0
        return value
    monkeypatch.setattr(api, "_prepare_api_image", prepare)
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(lambda _: pytest.fail("network"))) as provider:
        with pytest.raises(ApiGroundingError, match="api_timeout") as failure:
            provider.ground(request_id="request-1", capture=capture, goal="Search")
    assert failure.value.attempt is None


def test_total_deadline_rejects_late_parsed_result_without_retry(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    clock, calls = {"now": 10.0}, []
    monkeypatch.setattr(api.time, "monotonic", lambda: clock["now"])
    original_validate = api.validate_grounding_result
    def validate(*args, **kwargs):
        value = original_validate(*args, **kwargs)
        clock["now"] += 46.0
        return value
    monkeypatch.setattr(api, "validate_grounding_result", validate)
    transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200, json=reply()))
    with ChatCompletionsGrounder(profile(), transport=transport) as provider:
        with pytest.raises(ApiGroundingError, match="api_timeout") as failure:
            provider.ground(request_id="request-1", capture=capture, goal="Search")
    assert len(calls) == 1
    assert failure.value.attempt["status"] == "timeout"
    assert failure.value.attempt["usage"]["total_tokens"] == 50


@pytest.mark.parametrize("error,code", [
    (TimeoutError("api_provider_timeout"), "api_timeout"),
    (ValueError("api_response_too_large"), "api_response_too_large"),
    (ValueError("api_content_encoding_unsupported"), "api_content_encoding_unsupported")])
def test_shared_transport_errors_remain_structured_and_single_attempt(capture, monkeypatch, error, code):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    calls = []
    def handler(request):
        calls.append(request)
        raise error
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(handler)) as provider:
        with pytest.raises(ApiGroundingError, match=code) as failure:
            provider.ground(request_id="request-1", capture=capture, goal="Search")
    assert len(calls) == 1
    assert failure.value.attempt["status"] == ("timeout" if code == "api_timeout" else "failure")


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
    assert failure.value.attempt["status"] == "failure"
    assert failure.value.attempt["usage"] is None
    assert set(failure.value.attempt) == {"started_ns", "ended_ns", "status", "usage"}
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
        with pytest.raises(ApiGroundingError, match=code) as failure:
            provider.ground(request_id="request-1",capture=capture,goal="Search")
    assert failure.value.attempt["status"] == "failure"
    assert failure.value.attempt["usage"] == {"input_tokens": 30, "output_tokens": 20, "total_tokens": 50}


def test_missing_key_and_changed_frame_fail_before_network(capture, monkeypatch):
    monkeypatch.delenv("TEST_VISION_KEY", raising=False)
    calls = []
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(lambda request: calls.append(request) or pytest.fail("network"))) as provider:
        with pytest.raises(ApiGroundingError, match="api_key_missing") as missing_key:
            provider.ground(request_id="request-1",capture=capture,goal="Search")
        assert missing_key.value.attempt is None
        monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
        capture["sha256"] = "wrong"
        with pytest.raises(ApiGroundingError, match="api_capture_changed") as changed_capture:
            provider.ground(request_id="request-1",capture=capture,goal="Search")
        assert changed_capture.value.attempt is None
    assert calls == []


@pytest.mark.parametrize("value,code", [
    ({"choices": []}, "api_response_invalid"),
    ({"choices": [{"finish_reason":"length", "message":{"content":"{}"}}]}, "api_output_truncated"),
    ({"choices": [{"finish_reason":"stop", "message":{"refusal":"no", "content":None}}]}, "api_model_refused"),
    ({"choices": [{"finish_reason":"stop", "message":{"content":"not JSON"}}]}, "api_grounding_invalid")])
def test_protocol_failures_are_not_vision_unsupported(capture, monkeypatch, value, code):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(lambda _: httpx.Response(200,json=value))) as provider:
        with pytest.raises(ApiGroundingError, match=code) as failure:
            provider.ground(request_id="request-1",capture=capture,goal="Search")
    assert failure.value.attempt["status"] == "failure"


def test_timeout_and_response_bound(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    def timeout(request):
        raise httpx.ReadTimeout("secret-value", request=request)
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(timeout)) as provider:
        with pytest.raises(ApiGroundingError, match="api_timeout") as timed_out:
            provider.ground(request_id="request-1",capture=capture,goal="Search")
        assert timed_out.value.attempt["status"] == "timeout"
        assert timed_out.value.attempt["usage"] is None
    with ChatCompletionsGrounder(profile(max_response_bytes=1024), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x"*1025))) as provider:
        with pytest.raises(ApiGroundingError, match="api_response_too_large") as too_large:
            provider.ground(request_id="request-1",capture=capture,goal="Search")
    assert too_large.value.attempt["status"] == "failure"


def test_unknown_provider_usage_stays_unknown(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=reply(usage=None)))) as provider:
        value = provider.ground(request_id="request-1", capture=capture, goal="Search")
    assert value["provider"]["attempt"]["usage"] is None


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
        with pytest.raises(ApiGroundingError, match="api_busy") as busy:
            provider.ground(request_id="request-1",capture=capture,goal="Search")
        assert busy.value.attempt is None
        provider._slots.release()
        assert provider.ground(request_id="request-1",capture=capture,goal="Search")["result"]["status"] == "found"


def test_provider_timing_and_usage_survive_invalid_grounding(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    payload = reply()
    payload["usage"]["completion_tokens_details"] = {"reasoning_tokens": 12, "unknown": "secret-value"}
    payload["usage"]["prompt_tokens_details"] = {"cached_tokens": 5}
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload,
        headers={"openai-processing-ms": "23.5", "x-request-id": "req_vision_1"}))
    with ChatCompletionsGrounder(profile(), transport=transport) as provider:
        value = provider.ground(request_id="request-1", capture=capture, goal="Search")
        with pytest.raises(ApiGroundingError, match="api_grounding_invalid") as invalid:
            provider.ground(request_id="different-request", capture=capture, goal="Search")
    for metadata in (value["provider"], invalid.value.provider):
        assert metadata["server_processing_ms"] == 23.5
        assert metadata["provider_request_id"] == "req_vision_1"
        assert metadata["http_elapsed_ms"] >= 0
        assert metadata["requested_reasoning_effort"] is None
        assert metadata["usage"]["completion_tokens_details"] == {"reasoning_tokens": 12}
        assert metadata["usage"]["prompt_tokens_details"] == {"cached_tokens": 5}
        assert "secret-value" not in json.dumps(metadata)


@pytest.mark.parametrize("server_ms", ["NaN", "-1", "Infinity", "secret-value", "3600001"])
def test_untrusted_provider_metadata_does_not_leak_or_invent_time(capture, monkeypatch, server_ms):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=reply(model="secret-value"),
        headers={"openai-processing-ms": server_ms, "x-request-id": "secret-value"}))
    with ChatCompletionsGrounder(profile(), transport=transport) as provider:
        value = provider.ground(request_id="request-1", capture=capture, goal="Search")
    assert value["provider"]["server_processing_ms"] is None
    assert value["provider"]["provider_request_id"] is None
    assert value["provider"]["returned_model"] is None
    assert "secret-value" not in json.dumps(value)


def test_opt_in_trace_preserves_utf8_model_text_and_parse_error(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    replies = [reply(), reply(choices=[{"finish_reason": "stop", "message": {
        "content": '{"label":"搜索 secret-value", invalid JSON}'}}])]
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=replies.pop(0)))
    with ChatCompletionsGrounder(profile(), transport=transport, capture_trace=True) as provider:
        value = provider.ground(request_id="request-1", capture=capture, goal="搜索")
        with pytest.raises(ApiGroundingError, match="api_grounding_invalid") as invalid:
            provider.ground(request_id="request-1", capture=capture, goal="搜索")
    assert value["trace"]["prompt"]["goal"] == "搜索"
    assert "搜索" in value["trace"]["raw_model_text"]
    assert value["trace"]["parsed_model_json"]["candidates"][0]["label"] == "搜索"
    assert "搜索" in invalid.value.trace["raw_model_text"]
    assert invalid.value.trace["parse_error"].startswith("grounding JSON invalid")
    assert "secret-value" not in json.dumps(invalid.value.trace)
    assert "secret-value" not in json.dumps(value["trace"])


def benchmark_manifest(capture, **changes):
    return {"schema_version": "external_vision_benchmark.v1", "suite_id": "fresh-unit-suite",
        "truth_source": "independent test geometry", "cases": [{"case_id": "found", "goal": "Search",
            "capture": {**capture, "captured_at_utc": "2026-10-08T00:00:00Z"},
            "truth": {"status": "found", "bboxes": [{"x": 10, "y": 10, "width": 60, "height": 30}]}}],
        **changes}


def test_benchmark_reports_explicit_reasoning_setting(capture, monkeypatch, tmp_path):
    from scripts.benchmark_external_vision import BenchmarkManifest, preflight, run_benchmark
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    configured = profile(reasoning_effort="none")
    manifest = BenchmarkManifest.model_validate(benchmark_manifest(capture))
    assert preflight(manifest, configured)["requested_reasoning_effort"] == "none"
    def handle(request):
        body = json.loads(request.content)
        assert body["reasoning_effort"] == "none"
        context = json.loads(body["messages"][1]["content"][0]["text"])
        payload = result()
        payload["request_id"] = context["request_id"]
        return httpx.Response(200, json=reply(payload))
    report = run_benchmark(manifest, configured, output_path=tmp_path / "reasoning.json",
        transport=httpx.MockTransport(handle))
    assert report["profile"]["requested_reasoning_effort"] == "none"


def test_benchmark_keeps_first_failure_and_truth_out_of_model_request(capture, monkeypatch, tmp_path):
    from scripts.benchmark_external_vision import BenchmarkManifest, run_benchmark
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    document = benchmark_manifest(capture)
    first = document["cases"][0]
    good = {**first, "case_id": "found-good"}
    absent = {**first, "case_id": "absent", "goal": "Missing target",
              "truth": {"status": "absent", "bboxes": []}}
    ambiguous = {**first, "case_id": "ambiguous", "goal": "Duplicate target",
        "truth": {"status": "ambiguous", "bboxes": [
            {"x": 10, "y": 10, "width": 20, "height": 20},
            {"x": 50, "y": 10, "width": 20, "height": 20}]}}
    document["cases"] = [first, good, absent, ambiguous]
    calls = []
    def handler(request):
        context = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        assert "truth" not in context and "bboxes" not in context
        calls.append(context)
        if len(calls) == 1:
            return httpx.Response(500, text="secret-value")
        payload = result()
        payload["request_id"] = context["request_id"]
        if len(calls) == 3:
            payload.update(status="absent", candidates=[], selected_candidate_id=None)
        if len(calls) == 4:
            payload.update(status="ambiguous", selected_candidate_id=None, candidates=[
                {"id": "right", "label": "Search", "evidence_source": "api_visual",
                 "bbox": {"x": 50, "y": 10, "width": 20, "height": 20}, "click_point": {"x": 55, "y": 15}},
                {"id": "left", "label": "Search", "evidence_source": "api_visual",
                 "bbox": {"x": 10, "y": 10, "width": 20, "height": 20}, "click_point": {"x": 15, "y": 15}}])
        return httpx.Response(200, json=reply(payload), headers={"openai-processing-ms": "2"})
    output = tmp_path / "benchmark.json"
    report = run_benchmark(BenchmarkManifest.model_validate(document), profile(), output_path=output,
                           max_calls=4, transport=httpx.MockTransport(handler))
    assert len(calls) == 4
    assert report["cases"][0]["error"]["code"] == "api_server_error"
    assert report["cases"][0]["first_attempt"] is True
    assert report["cases"][0]["accuracy"]["passed"] is False
    assert report["cases"][1]["accuracy"]["bbox_iou"] == 1.0
    assert report["cases"][1]["accuracy"]["click_in_truth"] is True
    assert report["cases"][3]["accuracy"]["ambiguous_boxes_correct"] is True
    assert report["summary"]["cases"] == 4
    assert report["summary"]["passed"] == 3
    assert report["summary"]["failures"] == 1
    assert report["summary"]["found_click_accuracy"] == 0.5
    assert report["summary"]["classification_accuracy"] == 0.75
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert "secret-value" not in output.read_text(encoding="utf-8")


def test_benchmark_distinguishes_bbox_quality_from_click_hit(capture, monkeypatch, tmp_path):
    from scripts.benchmark_external_vision import BenchmarkManifest, run_benchmark
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    def handler(request):
        context = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        payload = result()
        payload["request_id"] = context["request_id"]
        payload["candidates"][0].update(bbox={"x": 30, "y": 10, "width": 10, "height": 10},
                                          click_point={"x": 35, "y": 15})
        return httpx.Response(200, json=reply(payload))
    report = run_benchmark(BenchmarkManifest.model_validate(benchmark_manifest(capture)), profile(),
        output_path=tmp_path / "score.json", max_calls=1, transport=httpx.MockTransport(handler))
    accuracy = report["cases"][0]["accuracy"]
    assert accuracy["bbox_iou"] == pytest.approx(1 / 18, abs=0.000001)
    assert accuracy["bbox_correct"] is False
    assert accuracy["click_in_truth"] is True
    assert accuracy["passed"] is False


def test_benchmark_preflight_rejects_changed_capture_and_call_cap(capture, monkeypatch, tmp_path):
    from scripts.benchmark_external_vision import BenchmarkManifest, run_benchmark
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    document = benchmark_manifest(capture)
    document["cases"][0]["capture"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="benchmark_capture_changed"):
        run_benchmark(BenchmarkManifest.model_validate(document), profile(), output_path=tmp_path / "bad.json",
            max_calls=1, transport=httpx.MockTransport(lambda _: pytest.fail("network")))
    document = benchmark_manifest(capture)
    document["cases"].append({**document["cases"][0], "case_id": "second"})
    with pytest.raises(ValueError, match="benchmark_call_cap_exceeded"):
        run_benchmark(BenchmarkManifest.model_validate(document), profile(), output_path=tmp_path / "cap.json",
            max_calls=1, transport=httpx.MockTransport(lambda _: pytest.fail("network")))


@pytest.mark.parametrize("truth", [
    {"status": "found", "bboxes": []},
    {"status": "absent", "bboxes": [{"x": 0, "y": 0, "width": 1, "height": 1}]},
    {"status": "ambiguous", "bboxes": [{"x": 0, "y": 0, "width": 1, "height": 1}]},
    {"status": "found", "bboxes": [{"x": 90, "y": 0, "width": 20, "height": 1}]}])
def test_benchmark_truth_contract_is_validated_before_any_call(capture, truth):
    from scripts.benchmark_external_vision import BenchmarkManifest
    document = benchmark_manifest(capture)
    document["cases"][0]["truth"] = truth
    with pytest.raises(ValueError):
        BenchmarkManifest.model_validate(document)


def test_benchmark_dry_run_needs_no_key_or_network(capture, monkeypatch, tmp_path, capsys):
    from scripts.benchmark_external_vision import main
    monkeypatch.delenv("TEST_VISION_KEY", raising=False)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(benchmark_manifest(capture), ensure_ascii=False), encoding="utf-8")
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(profile().model_dump_json(), encoding="utf-8")
    assert main(["--manifest", str(manifest_path), "--profile", str(profile_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["network_called"] is False
    assert report["truth_sent_to_provider"] is False
    assert not (tmp_path / "result.json").exists()


def test_benchmark_refuses_to_overwrite_first_results_before_network(capture, monkeypatch, tmp_path):
    from scripts.benchmark_external_vision import BenchmarkManifest, run_benchmark
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    output = tmp_path / "first.json"
    output.write_text('{"first_failure":"preserved"}\n', encoding="utf-8")
    with pytest.raises(FileExistsError):
        run_benchmark(BenchmarkManifest.model_validate(benchmark_manifest(capture)), profile(),
            output_path=output, transport=httpx.MockTransport(lambda _: pytest.fail("network")))
    assert output.read_text(encoding="utf-8") == '{"first_failure":"preserved"}\n'


@pytest.mark.parametrize("expected", ["absent", "ambiguous"])
def test_benchmark_found_target_cannot_pass_absence_or_ambiguity_truth(capture, monkeypatch, tmp_path, expected):
    from scripts.benchmark_external_vision import BenchmarkManifest, run_benchmark
    monkeypatch.setenv("TEST_VISION_KEY", "secret-value")
    document = benchmark_manifest(capture)
    document["cases"][0]["truth"] = {"status": expected, "bboxes": [] if expected == "absent" else [
        {"x": 10, "y": 10, "width": 20, "height": 20},
        {"x": 50, "y": 10, "width": 20, "height": 20}]}
    def handler(request):
        context = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        payload = result()
        payload["request_id"] = context["request_id"]
        return httpx.Response(200, json=reply(payload))
    report = run_benchmark(BenchmarkManifest.model_validate(document), profile(),
        output_path=tmp_path / "false-positive.json", transport=httpx.MockTransport(handler))
    assert report["cases"][0]["accuracy"]["status_correct"] is False
    assert report["cases"][0]["accuracy"]["passed"] is False
    assert report["summary"]["classification_accuracy"] == 0.0


@pytest.mark.parametrize("original_size", [(2560, 1400), (1400, 2560), (2400, 2400), (1001, 777)])
def test_luna_default_bounds_submitted_image_and_restores_original_coordinates(tmp_path, monkeypatch, original_size):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    path = tmp_path / "luna-frame.png"
    Image.new("RGB", original_size, "white").save(path)
    source_bytes = path.read_bytes()
    capture = {"image_path": str(path), "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "capture_id": "capture-1", "image_size": {"width": original_size[0], "height": original_size[1]}}
    configured = api.load_api_grounding_profile(
        Path(__file__).resolve().parents[1] / "configs/vision-api-openai-luna.example.json")
    assert configured.response_binding == "runtime"
    seen = []
    def handler(request):
        parts = json.loads(request.content)["messages"][1]["content"]
        context = json.loads(parts[0]["text"])
        with Image.open(BytesIO(base64.b64decode(parts[1]["image_url"]["url"].split(",", 1)[1]))) as image:
            actual = image.size
        assert max(actual) <= 1600
        assert actual[0] <= original_size[0] and actual[1] <= original_size[1]
        assert context["image_size"] == {"width": actual[0], "height": actual[1]}
        assert "request_id" not in context and "capture_id" not in context
        payload = result()
        del payload["request_id"], payload["capture_id"]
        payload["target_description"] = {"kind": "input_field", "appearance": "Long rounded box", "container": "Browser toolbar"}
        payload["image_size"] = context["image_size"]
        if original_size == (2560, 1400):
            assert actual == (1600, 875)
            payload["candidates"][0].update(
                bbox={"x": 47, "y": 27, "width": 1437, "height": 22},
                click_point={"x": 765, "y": 38})
        else:
            payload["candidates"][0].update(
                bbox={"x": actual[0]-1, "y": actual[1]-1, "width": 1, "height": 1},
                click_point={"x": actual[0]-1, "y": actual[1]-1})
        seen.append(actual)
        return httpx.Response(200, json=reply(payload))
    with ChatCompletionsGrounder(configured, transport=httpx.MockTransport(handler)) as provider:
        value = provider.ground(request_id="request-1", capture=capture, goal="Browser address bar")
    assert len(seen) == 1
    assert path.read_bytes() == source_bytes
    assert value["result"]["image_size"] == capture["image_size"]
    assert value["result"]["request_id"] == "request-1"
    assert value["result"]["capture_id"] == "capture-1"
    candidate = value["result"]["candidates"][0]
    if original_size == (2560, 1400):
        assert candidate["click_point"] == {"x": 1224, "y": 60}
        assert candidate["bbox"] == {"x": 75, "y": 43, "width": 2300, "height": 36}
    else:
        width, height = original_size
        box = candidate["bbox"]
        assert box["x"] + box["width"] == width
        assert box["y"] + box["height"] == height
        assert candidate["click_point"] == {"x": (seen[0][0]-1)*width//seen[0][0],
            "y": (seen[0][1]-1)*height//seen[0][1]}
    assert value["provider"]["image_preprocess"]["original_sha256"] == capture["sha256"]
    assert value["action_executed"] is False
