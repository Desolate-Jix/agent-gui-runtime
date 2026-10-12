"""候选双视图的纯图像合同；仅使用合成静态 PNG，不访问桌面或模型。"""
from copy import deepcopy
from hashlib import sha256
from importlib import import_module
from io import BytesIO
import json

from PIL import Image, ImageChops, ImageDraw
import pytest

from app.judgment.candidate_annotation import candidate_annotation_metadata


def png_bytes(size=(1000, 500), mode="RGB"):
    image = Image.new(mode, size, (18, 31, 47, 127) if mode == "RGBA" else (18, 31, 47))
    draw = ImageDraw.Draw(image)
    for x in range(0, size[0], 31):
        color = (x % 251, (x * 3) % 251, (x * 7) % 251)
        draw.line((x, 0, x, size[1] - 1), fill=(*color, 91) if mode == "RGBA" else color)
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def metadata(data, size, bbox, point):
    return candidate_annotation_metadata(
        {"capture_id": "fresh-candidate-frame", "sha256": sha256(data).hexdigest(), "role": "before"}, size,
        {"candidate_id": "visible-target", "capture_id": "fresh-candidate-frame", "bbox": bbox, "click_point": point})


def render(data, bound):
    return import_module("app.judgment.candidate_view").render_candidate_view(data, bound)


@pytest.fixture
def scene():
    data = png_bytes()
    return data, metadata(data, (1000, 500), {"x": 490, "y": 240, "w": 20, "h": 20}, {"x": 500, "y": 250})


def test_full_overview_and_zoomed_detail_have_exact_half_pixel_point_mapping(scene):
    data, bound = scene
    result, mapping = render(data, bound)
    assert mapping["schema"] == "decision_candidate_view.v1"
    assert mapping["recipe"] == "overview_detail_zoom2.v1"
    assert mapping["source_size"] == [1000, 500] and mapping["composite_size"] == [640, 688]
    overview, detail = mapping["views"]
    assert overview["source_crop_ltrb"] == [0, 0, 1000, 500]
    assert overview["size"] == [640, 320] and overview["scale_xy"] == [0.64, 0.64]
    assert overview["point_in_view_exact"] == pytest.approx([319.82, 159.82])
    assert overview["marker_center_in_view"] == [320, 160]
    assert overview["image_origin_in_composite"] == [0, 20]
    assert detail["source_crop_ltrb"] == [340, 170, 660, 330]
    assert detail["size"] == [640, 320] and detail["scale_xy"] == [2.0, 2.0]
    assert detail["point_in_view_exact"] == [320.5, 160.5]
    assert detail["marker_center_in_view"] == [321, 161]
    assert detail["image_origin_in_composite"] == [0, 364]
    assert detail["point_in_composite_exact"] == [320.5, 524.5]
    assert detail["marker_center_in_composite"] == [321, 525]
    assert mapping["overview_includes_complete_frame"] is True
    assert mapping["detail_includes_complete_bbox"] is True
    with Image.open(BytesIO(result)) as image:
        assert image.format == "PNG" and image.size == (640, 688)


@pytest.mark.parametrize("size,bbox,point,crop,detail_size", [
    ((800, 600), (0, 0, 20, 20), (0, 0), [0, 0, 320, 160], [640, 320]),
    ((800, 600), (780, 580, 20, 20), (799, 599), [480, 440, 800, 600], [640, 320]),
    ((119, 61), (10, 10, 60, 31), (40, 30), [0, 0, 119, 61], [238, 122]),
    ((1, 1), (0, 0, 1, 1), (0, 0), [0, 0, 1, 1], [2, 2]),
    ((4000, 100), (1000, 40, 2000, 20), (2000, 50), [952, 0, 3048, 100], [768, 37]),
    ((100, 4000), (40, 1000, 20, 2000), (50, 2000), [0, 952, 100, 3048], [37, 768]),
    ((1280, 720), (75, 43, 904, 34), (500, 60), [27, 0, 1027, 209], [768, 161]),
    ((1280, 720), (0, 0, 1280, 720), (500, 60), [0, 0, 1280, 720], [768, 432]),
    ((1249, 1032), (839, 587, 62, 18), (868, 596), [710, 516, 1030, 676], [640, 320]),
])
def test_near_edges_small_viewports_extreme_aspect_and_wide_fields_keep_complete_evidence(size, bbox, point, crop, detail_size):
    data = png_bytes(size)
    box = dict(zip(("x", "y", "w", "h"), bbox))
    bound = metadata(data, size, box, dict(zip(("x", "y"), point)))
    result, mapping = render(data, bound)
    overview, detail = mapping["views"]
    assert overview["source_crop_ltrb"] == [0, 0, *size]
    assert max(overview["size"]) <= 640 and all(a <= b for a, b in zip(overview["size"], size))
    assert detail["source_crop_ltrb"] == crop and detail["size"] == detail_size
    assert max(detail["size"]) <= 768 and max(detail["scale_xy"]) <= 2
    assert crop[0] <= bbox[0] and crop[1] <= bbox[1]
    assert crop[2] >= bbox[0] + bbox[2] and crop[3] >= bbox[1] + bbox[3]
    assert detail["crop_edges_are_ui_boundaries"] is False
    assert detail["source_frame_edges"] == {"left": crop[0] == 0, "top": crop[1] == 0,
        "right": crop[2] == size[0], "bottom": crop[3] == size[1]}
    assert mapping["detail_minimum_met"] == (detail_size[0] >= 320 and detail_size[1] >= 160)
    with Image.open(BytesIO(result)) as image:
        assert image.size == tuple(mapping["composite_size"])
        for view in mapping["views"]:
            assert all(0 <= view["marker_center_in_view"][i] < view["size"][i] for i in (0, 1))


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_only_hollow_ring_and_external_ticks_change_pixels_and_center_six_pixels_stay_original(mode):
    data = png_bytes(mode=mode)
    bound = metadata(data, (1000, 500), {"x": 490, "y": 240, "w": 20, "h": 20}, {"x": 500, "y": 250})
    result, mapping = render(data, bound)
    with Image.open(BytesIO(data)) as source, Image.open(BytesIO(result)) as output:
        original = source.convert("RGB")
        for view in mapping["views"]:
            expected = original.crop(view["source_crop_ltrb"]).resize(view["size"], Image.Resampling.LANCZOS)
            ox, oy = view["image_origin_in_composite"]
            actual = output.crop((ox, oy, ox + view["size"][0], oy + view["size"][1]))
            px, py = view["marker_center_in_view"]
            center = (max(0, px - 6), max(0, py - 6), min(actual.width, px + 7), min(actual.height, py + 7))
            assert actual.crop(center).tobytes() == expected.crop(center).tobytes()
            assert actual.getpixel((px + 11, py)) == (0, 255, 255)
            assert actual.getpixel((px + 19, py)) == (0, 255, 255)
            assert actual.getpixel((px + 14, py)) == expected.getpixel((px + 14, py))
            delta = ImageChops.difference(actual, expected)
            ImageDraw.Draw(delta).rectangle((px - 20, py - 20, px + 20, py + 20), fill="black")
            assert delta.getbbox() is None


def test_output_mapping_and_source_are_deterministic_and_independent(scene):
    data, bound = scene
    before = deepcopy(bound)
    original_hash = sha256(data).hexdigest()
    first, mapping = render(data, bound)
    second, again = render(data, bound)
    assert first == second and mapping == again
    assert bound == before and sha256(data).hexdigest() == original_hash
    assert mapping["source_sha256"] == original_hash
    assert mapping["capture_id"] == bound["capture_id"] and mapping["candidate_id"] == bound["candidate_id"]
    assert mapping["source_bbox"] == bound["bbox"] and mapping["source_point"] == bound["click_point"]
    json.dumps(mapping, ensure_ascii=False, allow_nan=False)
    mapping["source_bbox"]["x"] = -1
    mapping["source_point"]["x"] = -1
    assert bound == before and again["source_bbox"]["x"] == 490 and again["source_point"]["x"] == 500


@pytest.mark.parametrize("fault", ["hash", "dimensions", "extra", "schema", "point_float", "point_outside",
    "bbox_overflow", "bbox_bool", "viewport_extra", "viewport_bool", "capture_empty", "candidate_empty", "role", "oversized"])
def test_closed_metadata_binding_rejects_tampering_without_repair(scene, fault):
    data, bound = scene
    if fault == "hash": bound["source_sha256"] = "f" * 64
    elif fault == "dimensions": bound["viewport_size"]["width"] = 1001
    elif fault == "extra": bound["trusted"] = True
    elif fault == "schema": bound["schema"] = "decision_candidate_annotation.v2"
    elif fault == "point_float": bound["click_point"]["x"] = 500.0
    elif fault == "point_outside": bound["click_point"]["x"] = 900
    elif fault == "bbox_overflow": bound["bbox"]["w"] = 1000
    elif fault == "bbox_bool": bound["bbox"]["h"] = True
    elif fault == "viewport_extra": bound["viewport_size"]["dpi"] = 1
    elif fault == "viewport_bool": bound["viewport_size"]["width"] = True
    elif fault == "capture_empty": bound["capture_id"] = ""
    elif fault == "candidate_empty": bound["candidate_id"] = ""
    elif fault == "role": bound["role"] = "unbound"
    elif fault == "oversized": bound["viewport_size"] = {"width": 40_000_000, "height": 2}
    before = deepcopy(bound)
    with pytest.raises(ValueError, match="decision_candidate"):
        render(data, bound)
    assert bound == before


@pytest.mark.parametrize("kind", ["jpeg", "animated_png", "corrupt_png", "truncated_png"])
def test_requires_decodable_static_png_even_when_hash_matches(kind):
    stream = BytesIO()
    if kind == "jpeg": Image.new("RGB", (1000, 500), "white").save(stream, format="JPEG")
    elif kind == "animated_png":
        Image.new("RGB", (1000, 500), "white").save(stream, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (1000, 500), "black")], duration=100, loop=0)
    elif kind == "truncated_png": stream.write(png_bytes()[:100])
    else: stream.write(b"\x89PNG\r\n\x1a\ninvalid")
    data = stream.getvalue()
    bound = metadata(data, (1000, 500), {"x": 490, "y": 240, "w": 20, "h": 20}, {"x": 500, "y": 250})
    with pytest.raises(ValueError, match="decision_candidate_view"):
        render(data, bound)


@pytest.mark.parametrize("data", [b"", "not-bytes", bytearray(b"PNG")])
def test_bytes_contract_rejects_empty_or_mutable_data(scene, data):
    _, bound = scene
    with pytest.raises(ValueError, match="decision_candidate_view"):
        render(data, bound)
