"""仅合成 PNG 的坐标标注合同；不调用桌面或模型。"""
from copy import deepcopy
from hashlib import sha256
from importlib import import_module
from io import BytesIO

from PIL import Image
import pytest


def png_bytes(size=(119, 61), *, mode="RGB"):
    image = Image.new(mode, size)
    image.putdata([(x % 251, y % 251, (x + y) % 251, 127) if mode == "RGBA"
        else (x % 251, y % 251, (x + y) % 251) for y in range(size[1]) for x in range(size[0])])
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def scene():
    data = png_bytes()
    return import_module("app.judgment.candidate_annotation"), data, {
        "capture_id": "fresh-capture", "sha256": sha256(data).hexdigest(), "role": "before"}, {
        "candidate_id": "address-bar", "capture_id": "fresh-capture",
        "bbox": {"x": 23, "y": 13, "w": 60, "h": 31}, "click_point": {"x": 53, "y": 28}}


def test_metadata_is_pure_bound_and_copies_coordinates(scene, monkeypatch):
    module, data, frame, candidate = scene
    before = deepcopy((frame, candidate))
    monkeypatch.setattr(Image, "open", lambda *a, **k: pytest.fail("metadata must not decode images"))
    monkeypatch.setattr(Image.Image, "save", lambda *a, **k: pytest.fail("metadata must not encode images"))
    metadata = module.candidate_annotation_metadata(frame, (119, 61), candidate)
    assert metadata == {"schema": "decision_candidate_annotation.v1", "capture_id": "fresh-capture",
        "source_sha256": sha256(data).hexdigest(), "role": "before", "viewport_size": {"width": 119, "height": 61},
        "bbox": {"x": 23, "y": 13, "w": 60, "h": 31}, "click_point": {"x": 53, "y": 28}, "candidate_id": "address-bar"}
    assert (frame, candidate) == before
    candidate["bbox"]["x"] = 24
    candidate["click_point"]["x"] = 54
    assert metadata["bbox"]["x"] == 23 and metadata["click_point"]["x"] == 53


@pytest.mark.parametrize("fault", ["stale", "negative_x", "negative_y", "zero_width", "zero_height",
    "right_overflow", "bottom_overflow", "point_viewport_x", "point_viewport_y", "point_before_box",
    "point_box_right", "bool_bbox", "float_point", "bool_dimensions", "zero_dimensions", "bbox_extra",
    "point_extra", "bad_hash", "missing_role", "empty_candidate_id"])
def test_metadata_rejects_invalid_binding_or_coordinates_without_repair(scene, fault):
    module, _, frame, candidate = scene
    dimensions = (119, 61)
    if fault == "stale": candidate["capture_id"] = "old-capture"
    elif fault == "negative_x": candidate["bbox"]["x"] = -1
    elif fault == "negative_y": candidate["bbox"]["y"] = -1
    elif fault == "zero_width": candidate["bbox"]["w"] = 0
    elif fault == "zero_height": candidate["bbox"]["h"] = 0
    elif fault == "right_overflow": candidate["bbox"]["w"] = 119
    elif fault == "bottom_overflow": candidate["bbox"]["h"] = 61
    elif fault == "point_viewport_x": candidate["click_point"]["x"] = 119
    elif fault == "point_viewport_y": candidate["click_point"]["y"] = 61
    elif fault == "point_before_box": candidate["click_point"]["x"] = 22
    elif fault == "point_box_right": candidate["click_point"]["x"] = 83
    elif fault == "bool_bbox": candidate["bbox"]["h"] = True
    elif fault == "float_point": candidate["click_point"]["x"] = 53.0
    elif fault == "bool_dimensions": dimensions = (True, 61)
    elif fault == "zero_dimensions": dimensions = (119, 0)
    elif fault == "bbox_extra": candidate["bbox"]["width"] = 60
    elif fault == "point_extra": candidate["click_point"]["coordinate_space"] = "screen"
    elif fault == "bad_hash": frame["sha256"] = "not-a-hash"
    elif fault == "missing_role": frame.pop("role")
    elif fault == "empty_candidate_id": candidate["candidate_id"] = ""
    before = deepcopy((frame, dimensions, candidate))
    with pytest.raises(ValueError, match="decision_candidate_annotation"):
        module.candidate_annotation_metadata(frame, dimensions, candidate)
    assert (frame, dimensions, candidate) == before


@pytest.mark.parametrize("point", [{"x": 0, "y": 0}, {"x": 118, "y": 60}])
def test_exact_viewport_boundaries_are_valid_and_keep_original_size(scene, point):
    module, data, frame, candidate = scene
    candidate.update(bbox={"x": 0, "y": 0, "w": 119, "h": 61}, click_point=point)
    metadata = module.candidate_annotation_metadata(frame, [119, 61], candidate)
    rendered = module.render_candidate_annotation(data, metadata)
    with Image.open(BytesIO(rendered)) as image:
        assert image.size == (119, 61) and image.format == "PNG"
        assert image.convert("RGBA").getpixel((point["x"], point["y"])) == (0, 255, 255, 255)


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_render_is_deterministic_precise_hollow_and_preserves_unmarked_pixels(scene, mode):
    module, _, frame, candidate = scene
    data = png_bytes(mode=mode)
    original_hash = sha256(data).hexdigest()
    frame["sha256"] = original_hash
    metadata = module.candidate_annotation_metadata(frame, (119, 61), candidate)
    before_metadata = deepcopy(metadata)
    result = module.render_candidate_annotation(data, metadata)
    assert result == module.render_candidate_annotation(data, metadata)
    assert sha256(data).hexdigest() == original_hash and metadata == before_metadata
    with Image.open(BytesIO(data)) as source, Image.open(BytesIO(result)) as marked:
        assert marked.size == source.size == (119, 61) and marked.format == "PNG"
        original, pixels = source.convert("RGBA"), marked.convert("RGBA")
        for point in [(23, 13), (82, 13), (23, 43), (82, 43)]:
            assert pixels.getpixel(point) == original.getpixel(point)
        for point in [(53, 28), (44, 28), (62, 28), (53, 19), (53, 37), (58, 31)]:
            assert pixels.getpixel(point) == (0, 255, 255, 255)
        for y in range(61):
            for x in range(119):
                near_click = abs(x - 53) <= 9 and abs(y - 28) <= 9
                if not near_click:
                    assert pixels.getpixel((x, y)) == original.getpixel((x, y))
        assert pixels.getpixel((26, 20)) == original.getpixel((26, 20))
        assert pixels.getpixel((63, 28)) == original.getpixel((63, 28))


@pytest.mark.parametrize("fault", ["hash", "dimensions", "extra_metadata", "metadata_float_point", "schema"])
def test_render_revalidates_hash_dimensions_and_closed_metadata(scene, fault):
    module, data, frame, candidate = scene
    metadata = module.candidate_annotation_metadata(frame, (119, 61), candidate)
    if fault == "hash": metadata["source_sha256"] = "b" * 64
    elif fault == "dimensions": metadata["viewport_size"]["width"] = 120
    elif fault == "extra_metadata": metadata["trusted"] = True
    elif fault == "metadata_float_point": metadata["click_point"]["x"] = 53.0
    elif fault == "schema": metadata["schema"] = "decision_candidate_annotation.v2"
    with pytest.raises(ValueError, match="decision_candidate_annotation"):
        module.render_candidate_annotation(data, metadata)


@pytest.mark.parametrize("kind", ["jpeg", "animated_png", "corrupt_png"])
def test_renderer_accepts_only_valid_static_png_bytes(scene, kind):
    module, _, frame, candidate = scene
    stream = BytesIO()
    if kind == "jpeg": Image.new("RGB", (119, 61), "white").save(stream, format="JPEG")
    elif kind == "animated_png":
        Image.new("RGB", (119, 61), "white").save(stream, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (119, 61), "black")], duration=100, loop=0)
    else: stream.write(b"\x89PNG\r\n\x1a\ninvalid")
    data = stream.getvalue()
    frame["sha256"] = sha256(data).hexdigest()
    metadata = module.candidate_annotation_metadata(frame, (119, 61), candidate)
    with pytest.raises(ValueError, match="decision_candidate_annotation"):
        module.render_candidate_annotation(data, metadata)


def test_large_original_viewport_marks_only_click_point_without_rescaling(scene):
    module, _, frame, candidate = scene
    stream = BytesIO()
    Image.new("RGB", (2560, 1400), (7, 11, 13)).save(stream, format="PNG")
    data = stream.getvalue()
    frame["sha256"] = sha256(data).hexdigest()
    candidate.update(bbox={"x": 62, "y": 36, "w": 1890, "h": 27}, click_point={"x": 1007, "y": 49})
    metadata = module.candidate_annotation_metadata(frame, (2560, 1400), candidate)
    with Image.open(BytesIO(module.render_candidate_annotation(data, metadata))) as marked:
        assert marked.size == (2560, 1400)
        pixels = marked.convert("RGBA")
        for point in [(62, 36), (63, 37), (1950, 61), (1951, 62)]:
            assert pixels.getpixel(point) == (7, 11, 13, 255)
        for point in [(1007, 49), (989, 49), (1025, 49), (1007, 31), (1007, 67)]:
            assert pixels.getpixel(point) == (0, 255, 255, 255)
        for point in [(64, 38), (1026, 49), (100, 50), (10, 10)]:
            assert pixels.getpixel(point) == (7, 11, 13, 255)


def test_box_geometry_does_not_change_rendered_click_marker(scene):
    module, data, frame, candidate = scene
    first = module.candidate_annotation_metadata(frame, (119, 61), candidate)
    candidate["bbox"] = {"x": 0, "y": 0, "w": 119, "h": 61}
    second = module.candidate_annotation_metadata(frame, (119, 61), candidate)
    assert first["bbox"] != second["bbox"]
    assert module.render_candidate_annotation(data, first) == module.render_candidate_annotation(data, second)
