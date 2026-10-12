"""字段值显示仅放大完整已认证裁剪，保持原图和历史点击映射。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO

from PIL import Image
import pytest

from app.judgment.executed_click_annotation import executed_click_metadata, render_executed_click_annotation
from app.judgment.field_roi import render_field_roi


def source(size=(480, 240), bbox=None, point=None):
    width, height = size
    bbox = bbox or {"x": 80, "y": 70, "w": 240, "h": 50}
    point = point or {"x": 120, "y": 90}
    image = Image.new("RGBA", size, (11, 22, 33, 177))
    image.putpixel((0, 0), (203, 101, 51, 199))
    image.putpixel((width - 1, height - 1), (72, 156, 44, 255))
    image.putpixel((point["x"], point["y"]), (51, 93, 141, 211))
    output = BytesIO()
    image.save(output, format="PNG")
    data = output.getvalue()
    identity = {"handle": 10, "process_id": 20, "process_create_time": 123.0}
    rect = [-200, 300, width, height]
    reference = {"schema": "executed_click.v1", "receipt_sha256": "a" * 64,
        "click_point": point, "screen_point": {"x": point["x"] - 200, "y": point["y"] + 300},
        "window_identity": identity, "window_rect": rect, "coordinate_space": "capture_image_pixels"}
    frame = {"capture_id": "fresh-after", "sha256": sha256(data).hexdigest(), "role": "after",
        "window_identity": identity}
    action = {"operation": "visual_field_check", "field_phase": "value", "focus_stage": None,
        "actual_text": None, "value_reading": None,
        "field_image_scope": {"schema": "visual_field_roi.v1", "padding": 16},
        "executed_click": reference, "focus_receipt_sha256": reference["receipt_sha256"],
        "field": {"window_identity": identity, "window_rect": rect, "click_point": point, "bbox": bbox}}
    return data, executed_click_metadata(frame, size, action)


def test_complete_rgba_roi_doubles_without_internal_marker_and_keeps_exact_margin_mapping():
    from app.judgment.field_value_view import render_field_value_view
    data, metadata = source()
    before_data, before_metadata = bytes(data), deepcopy(metadata)
    rendered, mapping = render_field_value_view(data, metadata)
    assert mapping == {"schema": "decision_field_value_view.v2", "annotation_layout": "margin_ticks",
        "image_offset": {"x": 8, "y": 8},
        "source_roi_size": {"width": 272, "height": 82},
        "upload_size": {"width": 560, "height": 180},
        "scale_xy": [2, 2], "marker_center_exact": {"x": 120.5, "y": 80.5}}
    with Image.open(BytesIO(render_field_roi(data, metadata["field_roi"]))) as raw:
        expected = raw.convert("RGBA").resize((544, 164), Image.Resampling.LANCZOS)
    with Image.open(BytesIO(render_executed_click_annotation(data, metadata))) as old:
        old_marked = old.convert("RGBA").resize((544, 164), Image.Resampling.LANCZOS)
    with Image.open(BytesIO(rendered)) as image:
        assert image.format == "PNG" and image.mode == "RGBA" and image.size == (560, 180)
        inside = image.crop((8, 8, 552, 172))
        assert inside.tobytes() == expected.tobytes()
        assert inside.tobytes() != old_marked.tobytes()
        for pixel in ((0, 0), (559, 0), (0, 179), (559, 179)):
            assert image.getpixel(pixel) == (255, 255, 255, 255)
        for pixel in ((121, 1), (121, 7), (1, 81), (7, 81)):
            assert image.getpixel(pixel) == (0, 194, 207, 255)
    assert data == before_data and metadata == before_metadata
    assert render_field_value_view(data, metadata) == (rendered, mapping)


@pytest.mark.parametrize("point,want", [
    ({"x": 0, "y": 0}, {"x": 8.5, "y": 8.5}),
    ({"x": 39, "y": 0}, {"x": 86.5, "y": 8.5}),
    ({"x": 0, "y": 19}, {"x": 8.5, "y": 46.5}),
    ({"x": 39, "y": 19}, {"x": 86.5, "y": 46.5}),
])
def test_edge_point_keeps_complete_crop_and_exact_half_pixel_center(point, want):
    from app.judgment.field_value_view import render_field_value_view
    data, metadata = source((40, 20), {"x": 0, "y": 0, "w": 40, "h": 20}, point)
    rendered, mapping = render_field_value_view(data, metadata)
    assert mapping["source_roi_size"] == {"width": 40, "height": 20}
    assert mapping["upload_size"] == {"width": 96, "height": 56}
    assert mapping["annotation_layout"] == "margin_ticks"
    assert mapping["marker_center_exact"] == want
    with Image.open(BytesIO(rendered)) as image:
        assert image.size == (96, 56)
        x, y = point["x"] * 2 + 9, point["y"] * 2 + 9
        assert image.getpixel((x, 1)) == image.getpixel((1, y)) == (0, 194, 207, 255)


@pytest.mark.parametrize("size,want_scale,want_size", [
    ((2040, 20), 2, (4096, 56)),
    ((2041, 20), 1, (2041, 20)),
    ((2048, 20), 1, (2048, 20)),
    ((2049, 20), 1, (2049, 20)),
    ((992, 992), 2, (2000, 2000)),
    ((993, 993), 1, (993, 993)),
    ((1000, 1000), 1, (1000, 1000)),
    ((1000, 1001), 1, (1000, 1001)),
    ((5000, 20), 1, (5000, 20)),
])
def test_limits_preserve_complete_original_resolution_instead_of_cropping_or_downscaling(size, want_scale, want_size):
    from app.judgment.field_value_view import render_field_value_view
    data, metadata = source(size, {"x": 0, "y": 0, "w": size[0], "h": size[1]}, {"x": 0, "y": 0})
    rendered, mapping = render_field_value_view(data, metadata)
    assert mapping["source_roi_size"] == {"width": size[0], "height": size[1]}
    assert mapping["upload_size"] == {"width": want_size[0], "height": want_size[1]}
    assert mapping["scale_xy"] == [want_scale, want_scale]
    with Image.open(BytesIO(rendered)) as image:
        assert image.size == want_size
    if want_scale == 1:
        assert mapping["schema"] == "decision_field_value_view.v1"
        assert "annotation_layout" not in mapping and "image_offset" not in mapping
        assert rendered == render_executed_click_annotation(data, metadata)
    else:
        assert mapping["schema"] == "decision_field_value_view.v2"
        assert mapping["annotation_layout"] == "margin_ticks"


@pytest.mark.parametrize("fault", ["source_hash", "field_hash", "changed_bytes", "crop_point", "crop_bbox", "field_bbox", "upload_size",
    "scale", "window", "screen_point", "dimensions", "bbox", "extra", "missing_roi", "v1", "v3", "not_dict", "invalid_png"])
def test_invalid_source_or_metadata_never_produces_a_view(fault):
    from app.judgment.field_value_view import render_field_value_view
    data, metadata = source()
    if fault == "source_hash": metadata["source_sha256"] = "0" * 64
    elif fault == "field_hash": metadata["field_roi"]["source_sha256"] = "0" * 64
    elif fault == "changed_bytes": data += b"changed"
    elif fault == "crop_point": metadata["field_roi"]["crop_click_point"]["x"] += 1
    elif fault == "crop_bbox": metadata["field_roi"]["crop_bbox"]["w"] -= 1
    elif fault == "field_bbox": metadata["field_roi"]["field_bbox"]["w"] -= 1
    elif fault == "upload_size": metadata["field_roi"]["upload_size"]["height"] += 1
    elif fault == "scale": metadata["field_roi"]["scale"] = 2
    elif fault == "window": metadata["field_roi"]["window_identity"]["process_id"] += 1
    elif fault == "screen_point": metadata["executed_click"]["screen_point"]["x"] += 1
    elif fault == "dimensions": metadata["viewport_size"]["width"] += 1
    elif fault == "bbox": metadata["bbox"]["w"] -= 1
    elif fault == "extra": metadata["expected_text"] = "must not create pixels"
    elif fault == "missing_roi": metadata.pop("field_roi")
    elif fault == "v1":
        metadata["schema"] = "decision_executed_click_annotation.v1"
        metadata.pop("field_roi")
    elif fault == "v3":
        metadata["schema"] = "decision_executed_click_annotation.v3"
        metadata.pop("field_roi")
        metadata.pop("bbox")
    elif fault == "not_dict": metadata = None
    else:
        data = b"not a PNG"
        metadata["source_sha256"] = metadata["field_roi"]["source_sha256"] = sha256(data).hexdigest()
    with pytest.raises(ValueError):
        render_field_value_view(data, metadata)
