"""同帧局部图只改善字段差异可读性，保留完整原图和原判断条件。"""
import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json

from PIL import Image
import pytest

from tests.test_native_field_freshness_evidence import freshness_payload
from tests.test_native_focus_evidence import focus_payload, wire


def png_url(image, *, format="PNG", **options):
    stream = BytesIO()
    image.save(stream, format=format, **options)
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def detail_payload(region=None):
    payload = freshness_payload()
    field = payload["action"]["field"]
    field.update(window_rect=[0, 0, 2412, 1040], bbox={"x": 0, "y": 0, "w": 2412, "h": 1040},
        click_point={"x": 281, "y": 49})
    context = payload["action"]["field_freshness_context"]
    context["changed_region"] = region or {"x": 281, "y": 49, "w": 1, "h": 20}
    for key in ("native_before_snapshot", "native_current_snapshot"):
        context[key]["identity"].update(window_rect=[0, 0, 2412, 1040], control_bbox=[0, 0, 2412, 1040])
    before = Image.new("RGB", (2412, 1040), "white")
    before.putpixel((217, 0), (30, 60, 90))
    after = before.copy()
    for y in range(49, 69):
        after.putpixel((281, y), (0, 0, 0))
    for frame, image in zip(payload["frames"], (before, after)):
        frame["data_url"] = png_url(image)
    return payload


def decode(url):
    return Image.open(BytesIO(base64.b64decode(url.split(",", 1)[1], validate=True)))


def details(body):
    content = body["input"][0]["content"]
    return [json.loads(part["text"].split(": ", 1)[1]) for part in content
        if part.get("text", "").startswith("Same-frame field detail: ")]


def test_caret_pair_adds_exact_unmarked_crops_without_replacing_originals(wire):
    provider, bodies = wire
    payload = detail_payload()
    original = deepcopy(payload)
    provider.judge(payload)
    content = bodies[0]["input"][0]["content"]
    images = [part["image_url"] for part in content if part["type"] == "input_image"]
    assert len(images) == 4
    assert images[0] == payload["frames"][0]["data_url"]
    assert images[2] == payload["frames"][1]["data_url"]
    for frame, detail, image_url in zip(payload["frames"], details(bodies[0]), images[1::2]):
        assert detail == {"schema": "decision_field_detail.v1", "source_capture_id": frame["capture_id"],
            "role": frame["role"], "source_sha256": sha256(base64.b64decode(frame["data_url"].split(",", 1)[1])).hexdigest(),
            "source_size": {"width": 2412, "height": 1040}, "crop_bbox": {"x": 217, "y": 0, "w": 129, "h": 133}}
        crop = decode(image_url)
        assert crop.format == "PNG" and crop.size == (129, 133)
        assert crop.convert("RGBA").tobytes() == decode(frame["data_url"]).crop((217, 0, 346, 133)).convert("RGBA").tobytes()
    assert decode(images[1]).getpixel((64, 49)) != decode(images[3]).getpixel((64, 49))
    assert payload == original
    assert payload["condition"] in bodies[0]["questions"][0]["instructions"]
    instruction = " ".join(part.get("text", "") for part in content)
    assert "not an additional time frame" in instruction and "full original images" in instruction
    assert "artificial crop edge is not UI text clipping" in instruction
    assert "Judge actual UI clipping from the full original images" in instruction
    provider.judge(payload)
    assert bodies[1]["input"] == bodies[0]["input"]


@pytest.mark.parametrize("region,want", [
    ({"x": 0, "y": 0, "w": 1, "h": 1}, {"x": 0, "y": 0, "w": 65, "h": 65}),
    ({"x": 2411, "y": 1039, "w": 1, "h": 1}, {"x": 2347, "y": 975, "w": 65, "h": 65}),
])
def test_detail_padding_clamps_to_original_image_edges(wire, region, want):
    provider, bodies = wire
    provider.judge(detail_payload(region))
    assert [item["crop_bbox"] for item in details(bodies[0])] == [want, want]


@pytest.mark.parametrize("fault", ["dimensions", "non_png", "base64", "corrupt", "animated"])
def test_invalid_original_detail_image_refuses_before_http(wire, fault):
    provider, bodies = wire
    payload = detail_payload()
    if fault == "dimensions": url = png_url(Image.new("RGB", (2411, 1040)))
    elif fault == "non_png": url = png_url(Image.new("RGB", (2412, 1040)), format="JPEG")
    elif fault == "base64": url = "data:image/png;base64,not!base64"
    elif fault == "corrupt": url = "data:image/png;base64," + base64.b64encode(b"not a PNG").decode("ascii")
    else:
        url = png_url(Image.new("RGB", (2412, 1040)), save_all=True,
            append_images=[Image.new("RGB", (2412, 1040), "red")], duration=20, loop=0)
    payload["frames"][1]["data_url"] = url
    with pytest.raises(ValueError, match="decision_field_detail_"):
        provider.judge(payload)
    assert bodies == []


def test_unrelated_native_focus_does_not_gain_detail_images(wire):
    provider, bodies = wire
    payload = focus_payload()
    provider.judge(payload)
    images = [p for p in bodies[0]["input"][0]["content"] if p["type"] == "input_image"]
    assert len(images) == 1 and details(bodies[0]) == []


def test_large_change_keeps_full_images_without_cropping_away_changed_pixels(wire):
    provider, bodies = wire
    payload = detail_payload({"x": 100, "y": 100, "w": 1200, "h": 100})
    provider.judge(payload)
    images = [p["image_url"] for p in bodies[0]["input"][0]["content"] if p["type"] == "input_image"]
    assert images == [frame["data_url"] for frame in payload["frames"]]
    assert details(bodies[0]) == []


@pytest.mark.parametrize("fault", ["encoded_bytes", "decoded_bytes", "pixels"])
def test_detail_resource_limits_reject_before_decoding_large_images(monkeypatch, fault):
    from app.judgment import field_detail
    payload = detail_payload()
    frame = payload["frames"][0]
    field = payload["action"]["field"]
    if fault == "pixels":
        field["window_rect"] = [0, 0, 10000, 10000]
    else:
        monkeypatch.setattr(field_detail, "_MAX_BYTES", 20)
        if fault == "decoded_bytes":
            frame["data_url"] = "data:image/png;base64," + base64.b64encode(b"x" * 21).decode("ascii")
    with pytest.raises(ValueError, match="decision_field_detail_(bytes|dimensions)_invalid"):
        field_detail.build_field_detail(frame, field, payload["action"]["field_freshness_context"]["changed_region"])


def test_detail_uses_inline_bytes_without_following_a_file_path(monkeypatch):
    from app.judgment.field_detail import build_field_detail
    payload = detail_payload()
    frame = payload["frames"][0]
    frame["image_path"] = "C:/untrusted/not-a-screenshot.png"
    monkeypatch.setattr("builtins.open", lambda *a, **kw: pytest.fail("detail must only decode inline bytes"))
    result = build_field_detail(frame, payload["action"]["field"],
        payload["action"]["field_freshness_context"]["changed_region"])
    assert result["metadata"]["crop_bbox"] == {"x": 217, "y": 0, "w": 129, "h": 133}
