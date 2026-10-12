"""输入字段完整框与空白子区点击分开绑定；只使用合成像素及离线 HTTP。"""
import base64
from hashlib import sha256
from io import BytesIO
import json

import httpx
from PIL import Image, ImageDraw
import pytest

from app.judgment.field_roi import field_roi_metadata, render_field_roi
from app.vision.external_grounding_api import ApiGroundingProfile, ChatCompletionsGrounder


def profile(**options):
    return ApiGroundingProfile(endpoint="https://vision.example/v1/chat/completions",
        model="configured-model", api_key_env="TEST_VISION_KEY", **options)


def response(context, bbox, point):
    result = {"schema_version": "grounding.v1", "request_id": context["request_id"],
        "capture_id": context["capture_id"], "status": "found", "coordinate_space": "capture_image_pixels",
        "image_size": context["image_size"], "selected_candidate_id": "target",
        "candidates": [{"id": "target", "label": "Visible target", "bbox": bbox,
            "click_point": point, "evidence_source": "api_visual"}]}
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}


def capture(tmp_path):
    image = Image.new("RGB", (1000, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 40, 859, 89), outline=(80, 80, 80), fill=(245, 245, 245))
    draw.rectangle((130, 52, 514, 68), fill=(20, 70, 130))
    draw.text((132, 54), "CURRENT DIRECTORY PATH", fill="white")
    path = tmp_path / "fresh-field.png"
    image.save(path)
    data = path.read_bytes()
    return {"capture_id": "fresh-capture", "image_path": str(path), "sha256": sha256(data).hexdigest(),
        "image_size": {"width": 1000, "height": 300}}, data


def test_official_wire_requires_full_input_field_bbox_independently_of_blank_click(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-test-key")
    frame, _ = capture(tmp_path)
    seen = []
    goal = "The blank editable region to the right of the current text in the directory address field."
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        context = json.loads(body["messages"][1]["content"][0]["text"])
        return httpx.Response(200, json=response(context,
            {"x": 100, "y": 40, "width": 760, "height": 50}, {"x": 800, "y": 60}))
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(handler)) as grounder:
        value = grounder.ground(request_id="field-request", capture=frame, goal=goal)
    assert len(seen) == 1
    prompt = seen[0]["messages"][0]["content"]
    assert "For an input field" in prompt
    assert "entire visible input field" in prompt and "existing text" in prompt
    assert "even when the goal requests a blank or other clickable subregion" in prompt
    assert "click_point independently" in prompt and "not necessarily the bbox center" in prompt
    context = json.loads(seen[0]["messages"][1]["content"][0]["text"])
    assert context["goal"] == goal
    fields = context["required_output_schema"]["$defs"]["GroundingCandidate"]["properties"]
    assert set(fields) == {"id", "label", "bbox", "click_point", "evidence_source", "confidence"}
    assert "entire visible input field" in fields["bbox"]["description"]
    assert "existing text" in fields["bbox"]["description"]
    assert "not necessarily" in fields["click_point"]["description"]
    assert value["result"]["schema_version"] == "grounding.v1"
    assert value["result"]["candidates"][0]["click_point"] == {"x": 800, "y": 60}
    assert value["provider"]["attempts"] == 1 and value["provider"]["automatic_retry_allowed"] is False


@pytest.mark.parametrize("max_edge", [None, 500])
def test_full_input_bbox_mapping_keeps_left_text_pixels_and_independent_edge_click(tmp_path, monkeypatch, max_edge):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-test-key")
    source, data = capture(tmp_path)
    calls = []
    def handler(request):
        parts = json.loads(request.content)["messages"][1]["content"]
        context = json.loads(parts[0]["text"])
        with Image.open(BytesIO(base64.b64decode(parts[1]["image_url"]["url"].split(",", 1)[1]))) as image:
            assert image.size == ((500, 150) if max_edge else (1000, 300))
        scale = 2 if max_edge else 1
        calls.append(context)
        return httpx.Response(200, json=response(context,
            {"x": 100 // scale, "y": 40 // scale, "width": 760 // scale, "height": 50 // scale},
            {"x": 800 // scale, "y": 60 // scale}))
    with ChatCompletionsGrounder(profile(max_image_edge=max_edge), transport=httpx.MockTransport(handler)) as grounder:
        value = grounder.ground(request_id="field-request", capture=source,
            goal="Click the blank area to the right of existing text in the input field.")
    assert len(calls) == 1
    candidate = value["result"]["candidates"][0]
    assert candidate["bbox"] == {"x": 100, "y": 40, "width": 760, "height": 50}
    assert candidate["click_point"] == {"x": 800, "y": 60}
    assert candidate["click_point"]["x"] != candidate["bbox"]["x"] + candidate["bbox"]["width"] // 2
    identity = {"handle": 10, "process_id": 20, "process_create_time": 30.0}
    box = candidate["bbox"]
    metadata = field_roi_metadata({**source, "role": "after", "window_identity": identity}, (1000, 300),
        {"window_identity": identity, "window_rect": [-150, 200, 1000, 300],
            "bbox": {"x": box["x"], "y": box["y"], "w": box["width"], "h": box["height"]},
            "click_point": candidate["click_point"]})
    assert metadata["crop_bbox"] == {"x": 84, "y": 24, "w": 792, "h": 82}
    assert metadata["click_point_original"] == {"x": 800, "y": 60}
    assert metadata["crop_click_point"] == {"x": 716, "y": 36}
    with Image.open(BytesIO(data)) as original, Image.open(BytesIO(render_field_roi(data, metadata))) as cropped:
        assert cropped.tobytes() == original.convert("RGBA").crop((84, 24, 876, 106)).tobytes()
        assert cropped.crop((46, 28, 431, 45)).tobytes() == original.convert("RGBA").crop((130, 52, 515, 69)).tobytes()
        assert cropped.getpixel((716, 36)) == original.convert("RGBA").getpixel((800, 60))
    assert value["provider"]["attempts"] == 1 and value["provider"]["automatic_retry_allowed"] is False
    assert value["action_executed"] is False


def test_non_field_target_keeps_its_own_box_and_off_center_point(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_VISION_KEY", "offline-test-key")
    source, _ = capture(tmp_path)
    calls = []
    def handler(request):
        context = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
        calls.append(context)
        return httpx.Response(200, json=response(context,
            {"x": 120, "y": 140, "width": 80, "height": 30}, {"x": 125, "y": 145}))
    with ChatCompletionsGrounder(profile(), transport=httpx.MockTransport(handler)) as grounder:
        value = grounder.ground(request_id="button-request", capture=source, goal="The ordinary toolbar Open button.")
    assert len(calls) == 1
    assert value["result"]["candidates"][0]["bbox"] == {"x": 120, "y": 140, "width": 80, "height": 30}
    assert value["result"]["candidates"][0]["click_point"] == {"x": 125, "y": 145}
