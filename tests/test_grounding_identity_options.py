"""定位同次补充身份备选；旧合同省略兼容且不产生期望身份或答案。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import httpx
from PIL import Image
import pytest

from app.vision.external_grounding_api import (ApiGroundingError, ApiGroundingProfile,
    ChatCompletionsGrounder, load_api_grounding_profile)
from app.vision.grounding_contract import validate_grounding_result
from tests.test_external_grounding_api import capture, profile, reply, result


def validate(value):
    return validate_grounding_result(value, request_id="request-1", capture_id="capture-1", image_size=(100, 80))


def test_legacy_omission_is_preserved_in_all_dump_modes_and_roundtrip():
    original = result()
    parsed = validate(original)
    assert parsed.identity_options is None
    assert "identity_options" not in parsed.model_dump()
    assert "identity_options" not in parsed.model_dump(mode="json")
    assert "identity_options" not in json.loads(parsed.model_dump_json())
    assert validate(parsed.model_dump()).model_dump() == parsed.model_dump()


def test_concrete_options_preserve_utf8_order_and_are_independent():
    raw = {**result(), "identity_options": ["\u6d4f\u89c8\u5668\u5730\u5740\u680f", "Page search field"]}
    original = deepcopy(raw)
    parsed = validate(raw)
    assert parsed.identity_options == raw["identity_options"]
    raw["identity_options"][0] = "changed"
    assert parsed.identity_options == original["identity_options"]
    assert json.loads(parsed.model_dump_json())["identity_options"] == original["identity_options"]


@pytest.mark.parametrize("options", [[], ["x"] * 8, [""], ["  "], [1], [True], "Close tab", {"value": "Close tab"},
    ["x" * 4001], ["Close tab", " close TAB "], ["Save button", "savebutton"],
    ["expected"], ["correct"], ["wrong"], ["YES"], ["no"], ["\u6b63\u786e"], ["\u9519\u8bef"],
    ["condition_met"], ["unknown"], ["other"]])
def test_invalid_options_rejected_in_lightweight_contract(options):
    with pytest.raises(ValueError, match="identity_options"):
        validate({**result(), "identity_options": options})


@pytest.mark.parametrize("count", [1, 7])
def test_option_count_boundaries(count):
    raw = {**result(), "identity_options": [f"Concrete control {i}" for i in range(count)]}
    assert validate(raw).identity_options == raw["identity_options"]


@pytest.mark.parametrize("status", ["absent", "unsupported", "error", "ambiguous"])
def test_nonfound_status_cannot_attach_identity_options(status):
    raw = result()
    raw.update(status=status, selected_candidate_id=None, candidates=[])
    if status == "ambiguous":
        candidate = result()["candidates"][0]
        raw["candidates"] = [{**deepcopy(candidate), "id": f"c{i}"} for i in range(2)]
    assert validate(raw).identity_options is None
    assert validate({**raw, "identity_options": None}).identity_options is None
    with pytest.raises(ValueError, match="identity_options"):
        validate({**raw, "identity_options": ["Other search input"]})


def test_legacy_options_profile_remains_explicit_opt_in_and_strict():
    assert profile().identity_options is False
    assert profile(identity_options=True).identity_options is True
    for value in (1, "true", None):
        with pytest.raises(ValueError):
            profile(identity_options=value)
    configured = load_api_grounding_profile(Path("configs/vision-api-openai-luna.example.json"))
    assert configured.model == "gpt-6-luna" and configured.identity_options is False


@pytest.mark.parametrize("enabled", [False, True])
def test_same_single_call_delivers_options_and_trace_without_identity_answer(capture, monkeypatch, enabled):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-secret")
    raw = result()
    if enabled:
        raw["identity_options"] = ["Browser address bar", "\u641c\u7d22\u7ed3\u679c\u94fe\u63a5"]
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(raw))
    with ChatCompletionsGrounder(profile(identity_options=enabled), transport=httpx.MockTransport(handle),
            capture_trace=True) as grounder:
        output = grounder.ground(request_id="request-1", capture=capture, goal="Page search field")
    assert len(calls) == 1 and output["provider"]["attempts"] == 1
    assert output["provider"]["automatic_retry_allowed"] is False and output["action_executed"] is False
    body = json.loads(calls[0].content)
    context = json.loads(body["messages"][1]["content"][0]["text"])
    schema = context["required_output_schema"]
    assert ("identity_options" in schema["properties"]) is enabled
    if enabled:
        assert output["result"]["identity_options"] == raw["identity_options"]
        instructions = body["messages"][0]["content"]
        assert all(term in instructions for term in ("1-7", "alternative", "unchanged goal", "expected ID", "Candidate.label"))
        assert "identity_options" in json.dumps(schema.get("allOf"))
    else:
        assert "identity_options" not in output["result"]
        assert "identity_options" not in body["messages"][0]["content"]
    trace = output["trace"]
    assert trace["raw_model_text"] == json.dumps(raw, ensure_ascii=False)
    assert trace["parsed_model_json"] == raw and trace["parse_error"] is None
    assert "expected" not in output["result"] and "identity_answer" not in output["result"]


@pytest.mark.parametrize("options", ["missing", None, [], ["Page search field"], [" page SEARCHfield "]])
def test_enabled_found_requires_nonempty_alternatives_excluding_the_goal(capture, monkeypatch, options):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-secret")
    raw = result()
    if options != "missing":
        raw["identity_options"] = options
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(raw))
    with ChatCompletionsGrounder(profile(identity_options=True), transport=httpx.MockTransport(handle),
            capture_trace=True) as grounder:
        with pytest.raises(ApiGroundingError, match="api_grounding_invalid") as failed:
            grounder.ground(request_id="request-1", capture=capture, goal="Page search field")
    assert len(calls) == 1 and failed.value.attempt["status"] == "failure"
    assert failed.value.trace["raw_model_text"] == json.dumps(raw, ensure_ascii=False)
    assert failed.value.trace["parsed_model_json"] == raw
    assert "identity_options" in failed.value.trace["parse_error"]


def test_enabled_absent_has_no_invented_alternatives(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-secret")
    raw = {**result(), "status": "absent", "candidates": [], "selected_candidate_id": None}
    with ChatCompletionsGrounder(profile(identity_options=True), transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=reply(raw)))) as grounder:
        output = grounder.ground(request_id="request-1", capture=capture, goal="Page search field")
    assert output["result"]["status"] == "absent" and "identity_options" not in output["result"]


def test_resize_preserves_options_and_original_trace(capture, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-secret")
    path = Path(capture["image_path"])
    Image.new("RGB", (400, 300), "white").save(path)
    original = path.read_bytes()
    capture.update(sha256=sha256(original).hexdigest(), image_size={"width": 400, "height": 300})
    raw = {**result(), "image_size": {"width": 200, "height": 150},
        "identity_options": ["Browser address bar", "Search results link"]}
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=reply(raw))
    with ChatCompletionsGrounder(profile(identity_options=True, max_image_edge=200),
            transport=httpx.MockTransport(handle), capture_trace=True) as grounder:
        output = grounder.ground(request_id="request-1", capture=capture, goal="Page search field")
    assert len(calls) == 1 and path.read_bytes() == original
    assert output["result"]["image_size"] == capture["image_size"]
    assert output["result"]["identity_options"] == raw["identity_options"]
    assert output["result"]["candidates"][0]["click_point"] == {"x": 60, "y": 40}
    assert output["trace"]["parsed_model_json"] == raw
    assert output["trace"]["raw_model_text"] == json.dumps(raw, ensure_ascii=False)
