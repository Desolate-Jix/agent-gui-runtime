"""定位外观描述与原目标分离；同次返回且不生成类别或正确答案。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import httpx
from PIL import Image
import pytest

from app.vision.external_grounding_api import (ApiGroundingError, ChatCompletionsGrounder,
    load_api_grounding_profile)
from app.vision.grounding_contract import validate_grounding_result
from tests.test_external_grounding_api import capture, profile, reply, result


def description(**changes):
    return {"kind": "input_field", "appearance": "Long rounded editable box", "container": "Browser toolbar", **changes}


def validate(value):
    return validate_grounding_result(value, request_id="request-1", capture_id="capture-1", image_size=(100, 80))


def test_legacy_description_omission_preserves_dump_and_profile_digest_shape():
    parsed = validate(result())
    assert parsed.target_description is None
    for dumped in (parsed.model_dump(), parsed.model_dump(mode="json"), json.loads(parsed.model_dump_json())):
        assert "target_description" not in dumped and "identity_options" not in dumped
    assert validate(parsed.model_dump()).model_dump() == parsed.model_dump()
    for dumped in (profile().model_dump(), profile().model_dump(mode="json"), json.loads(profile().model_dump_json())):
        assert "target_description" not in dumped and "identity_options" not in dumped


@pytest.mark.parametrize("kind", ["graphic", "input_field"])
def test_target_description_is_strict_independent_and_preserves_utf8(kind):
    raw = {**result(), "target_description": description(kind=kind, appearance="\u5706\u89d2\u8f93\u5165\u6846")}
    original = deepcopy(raw)
    parsed = validate(raw)
    assert parsed.model_dump()["target_description"] == original["target_description"]
    raw["target_description"]["appearance"] = "changed"
    assert json.loads(parsed.model_dump_json())["target_description"] == original["target_description"]


@pytest.mark.parametrize("value", ["input_field", [], {},
    description(kind="button"), description(kind=True),
    description(appearance=""), description(appearance=" \n\t"), description(appearance=1),
    description(appearance=None), description(appearance="x" * 1001),
    description(container=""), description(container=" \n\t"), description(container=True),
    description(container=None), description(container="x" * 1001),
    description(expected="a"), description(choices=["a", "b"]), description(answer="correct")])
def test_invalid_target_description_is_rejected(value):
    with pytest.raises(ValueError, match="target_description"):
        validate({**result(), "target_description": value})


def test_description_text_boundaries_do_not_rewrite_values():
    raw = description(appearance="x" * 1000, container=" y ")
    assert validate({**result(), "target_description": raw}).model_dump()["target_description"] == raw


@pytest.mark.parametrize("status", ["absent", "ambiguous", "unsupported", "error"])
def test_nonfound_status_cannot_attach_target_description(status):
    raw = {**result(), "status": status, "candidates": [], "selected_candidate_id": None}
    if status == "ambiguous":
        candidate = result()["candidates"][0]
        raw["candidates"] = [{**deepcopy(candidate), "id": f"c{i}"} for i in range(2)]
    assert validate(raw).target_description is None
    assert validate({**raw, "target_description": None}).target_description is None
    with pytest.raises(ValueError, match="target_description"):
        validate({**raw, "target_description": description()})


def test_profile_is_strict_opt_in_and_mutually_exclusive_with_legacy_options():
    assert profile().target_description is False
    assert profile(target_description=True).target_description is True
    assert profile(identity_options=True).target_description is False
    for value in (1, "true", None):
        with pytest.raises(ValueError):
            profile(target_description=value)
    with pytest.raises(ValueError, match="identity_options.*target_description|target_description.*identity_options"):
        profile(identity_options=True, target_description=True)


def test_luna_example_requests_description_without_identity_options():
    configured = load_api_grounding_profile(Path("configs/vision-api-openai-luna.example.json"))
    assert configured.model == "gpt-6-luna"
    assert configured.target_description is True and configured.identity_options is False
    assert "identity_options" not in configured.model_dump()


@pytest.mark.parametrize("enabled", [False, True])
def test_same_single_call_carries_unverified_description_and_unchanged_goal(capture, monkeypatch, enabled):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-secret")
    raw = result()
    if enabled:
        raw["target_description"] = description()
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(raw))
    with ChatCompletionsGrounder(profile(target_description=enabled), transport=httpx.MockTransport(handle),
            capture_trace=True) as grounder:
        output = grounder.ground(request_id="request-1", capture=capture, goal="Original exact target")
    assert len(calls) == 1 and output["provider"]["attempts"] == 1
    assert output["provider"]["automatic_retry_allowed"] is False and output["action_executed"] is False
    body = json.loads(calls[0].content)
    context = json.loads(body["messages"][1]["content"][0]["text"])
    assert context["goal"] == "Original exact target" and "tools" not in body
    schema = context["required_output_schema"]
    assert ("target_description" in schema["properties"]) is enabled
    assert ("TargetDescription" in schema.get("$defs", {})) is enabled
    assert "identity_options" not in schema["properties"]
    prompt = body["messages"][0]["content"]
    if enabled:
        assert output["result"]["target_description"] == raw["target_description"]
        assert all(term in prompt for term in ("appearance", "container", "input_field", "graphic", "unverified"))
        assert "target_description" in json.dumps(schema.get("allOf"))
    else:
        assert "target_description" not in output["result"] and "target_description" not in prompt
    assert "identity_options" not in prompt and "alternative" not in prompt
    trace = output["trace"]
    assert trace["raw_model_text"] == json.dumps(raw, ensure_ascii=False)
    assert trace["parsed_model_json"] == raw and trace["parse_error"] is None


@pytest.mark.parametrize("value", ["missing", None, {}, description(kind="invalid"), description(expected="a")])
def test_enabled_found_requires_valid_description_without_retry(capture, monkeypatch, value):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-secret")
    raw = result()
    if value != "missing":
        raw["target_description"] = value
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(raw))
    with ChatCompletionsGrounder(profile(target_description=True), transport=httpx.MockTransport(handle),
            capture_trace=True) as grounder:
        with pytest.raises(ApiGroundingError, match="api_grounding_invalid") as failure:
            grounder.ground(request_id="request-1", capture=capture, goal="Original target")
    assert len(calls) == 1 and failure.value.attempt["status"] == "failure"
    assert failure.value.trace["parsed_model_json"] == raw
    assert failure.value.trace["raw_model_text"] == json.dumps(raw, ensure_ascii=False)
    assert "target_description" in failure.value.trace["parse_error"]


def test_enabled_absent_does_not_invent_description(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-secret")
    raw = {**result(), "status": "absent", "candidates": [], "selected_candidate_id": None}
    with ChatCompletionsGrounder(profile(target_description=True), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=reply(raw)))) as grounder:
        output = grounder.ground(request_id="request-1", capture=capture, goal="Original target")
    assert output["result"]["status"] == "absent" and "target_description" not in output["result"]


@pytest.mark.parametrize("options", [None, ["Tab strip search button"]])
def test_description_request_rejects_unrequested_legacy_options(capture, monkeypatch, options):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-secret")
    raw = {**result(), "target_description": description(), "identity_options": options}
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(raw))
    with ChatCompletionsGrounder(profile(target_description=True), transport=httpx.MockTransport(handle),
            capture_trace=True) as grounder:
        with pytest.raises(ApiGroundingError, match="api_grounding_invalid") as failure:
            grounder.ground(request_id="request-1", capture=capture, goal="Original target")
    assert len(calls) == 1 and failure.value.attempt["status"] == "failure"
    assert failure.value.trace["parsed_model_json"] == raw
    assert "identity_options" in failure.value.trace["parse_error"]


def test_resize_keeps_target_description_original_trace_and_capture(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-secret")
    path = Path(capture["image_path"])
    Image.new("RGB", (400, 300), "white").save(path)
    original = path.read_bytes()
    capture.update(sha256=sha256(original).hexdigest(), image_size={"width": 400, "height": 300})
    raw = {**result(), "image_size": {"width": 200, "height": 150}, "target_description": description()}
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(raw))
    with ChatCompletionsGrounder(profile(target_description=True, max_image_edge=200),
            transport=httpx.MockTransport(handle), capture_trace=True) as grounder:
        output = grounder.ground(request_id="request-1", capture=capture, goal="Original target")
    assert len(calls) == 1 and path.read_bytes() == original
    assert output["result"]["image_size"] == capture["image_size"]
    assert output["result"]["target_description"] == raw["target_description"]
    assert output["result"]["candidates"][0]["click_point"] == {"x": 60, "y": 40}
    assert output["trace"]["parsed_model_json"] == raw
