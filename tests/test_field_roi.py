"""完整字段 ROI 保留原像素与坐标绑定，供 OCR 和标注图共同使用。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO

from PIL import Image
import pytest

from test_executed_click_annotation import source, metadata


def roi(source):
    from app.judgment.field_roi import field_roi_metadata
    _, frame, action = metadata(source)
    return field_roi_metadata(frame, (480, 240), action["field"])


def test_unmarked_roi_contains_entire_field_and_maps_nonzero_screen_origin(source):
    from app.judgment.field_roi import render_field_roi
    value = roi(source)
    original = deepcopy(source)
    assert value["crop_bbox"] == {"x": 64, "y": 54, "w": 272, "h": 82}
    assert value["upload_size"] == {"width": 272, "height": 82}
    assert value["click_point_original"] == {"x": 120, "y": 90}
    assert value["crop_click_point"] == {"x": 56, "y": 36}
    assert value["window_rect"] == [-200, 300, 480, 240]
    assert value["scale"] == 1 and value["source_sha256"] == sha256(source[2]).hexdigest()
    cropped = render_field_roi(source[2], value)
    with Image.open(BytesIO(source[2])) as full, Image.open(BytesIO(cropped)) as image:
        assert image.size == (272, 82)
        assert image.tobytes() == full.crop((64, 54, 336, 136)).tobytes()
        assert image.getpixel((56, 36)) == full.getpixel((120, 90))
    assert source == original


@pytest.mark.parametrize("bbox,want", [
    ({"x": 0, "y": 0, "w": 125, "h": 95}, {"x": 0, "y": 0, "w": 141, "h": 111}),
    ({"x": 100, "y": 80, "w": 380, "h": 160}, {"x": 84, "y": 64, "w": 396, "h": 176}),
])
def test_roi_padding_clamps_only_at_source_image_boundary(source, bbox, want):
    from app.judgment.field_roi import field_roi_metadata
    _, frame, action = metadata(source)
    action["field"]["bbox"] = bbox
    assert field_roi_metadata(frame, (480, 240), action["field"])["crop_bbox"] == want


@pytest.mark.parametrize("fault", ["negative", "outside", "point", "identity", "dimensions", "padding", "bool_bbox"])
def test_roi_rejects_invalid_source_geometry_or_point_mapping(source, fault):
    from app.judgment.field_roi import field_roi_metadata
    _, frame, action = metadata(source)
    field, dimensions, padding = action["field"], (480, 240), 16
    if fault == "negative": field["bbox"]["x"] = -1
    elif fault == "outside": field["bbox"]["w"] = 481
    elif fault == "point": field["bbox"] = {"x": 300, "y": 150, "w": 100, "h": 40}
    elif fault == "identity": frame["window_identity"]["handle"] += 1
    elif fault == "dimensions": dimensions = (481, 240)
    elif fault == "padding": padding = True
    else: field["bbox"]["x"] = True
    with pytest.raises(ValueError):
        field_roi_metadata(frame, dimensions, field, padding=padding)


@pytest.mark.parametrize("fault", ["source_hash", "mapping", "crop", "size", "scale", "extra", "jpeg", "animated"])
def test_roi_renderer_rejects_forged_mapping_or_changed_source(source, fault):
    from app.judgment.field_roi import render_field_roi
    value, data = roi(source), source[2]
    if fault == "source_hash": value["source_sha256"] = "0" * 64
    elif fault == "mapping": value["crop_click_point"]["x"] += 1
    elif fault == "crop": value["crop_bbox"]["w"] -= 1
    elif fault == "size": value["upload_size"]["width"] -= 1
    elif fault == "scale": value["scale"] = .5
    elif fault == "extra": value["unexpected"] = True
    else:
        output = BytesIO()
        image = Image.new("RGB", (480, 240), "white")
        if fault == "jpeg": image.save(output, format="JPEG")
        else: image.save(output, format="PNG", save_all=True, append_images=[Image.new("RGB", (480, 240), "gray")])
        data = output.getvalue()
        value["source_sha256"] = sha256(data).hexdigest()
    with pytest.raises(ValueError):
        render_field_roi(data, value)


def test_wide_field_is_not_resized_or_partially_cut_to_detail_limit():
    from app.judgment.field_roi import field_roi_metadata, render_field_roi
    output = BytesIO()
    Image.new("RGBA", (5000, 40), "white").save(output, format="PNG")
    data = output.getvalue()
    identity = {"handle": 10, "process_id": 20, "process_create_time": 100.0}
    frame = {"capture_id": "wide", "sha256": sha256(data).hexdigest(), "role": "after", "window_identity": identity}
    field = {"window_identity": identity, "window_rect": [100, 200, 5000, 40],
        "bbox": {"x": 1, "y": 1, "w": 4998, "h": 38}, "click_point": {"x": 10, "y": 10}}
    value = field_roi_metadata(frame, (5000, 40), field)
    with Image.open(BytesIO(render_field_roi(data, value))) as image:
        assert image.size == (5000, 40)


@pytest.mark.parametrize("phase,stage", [("focus", "after_click"), ("focus", "after_selection"), ("value", None)])
def test_roi_flag_is_explicit_and_limited_to_visual_field_checks(source, phase, stage):
    from app.judgment.field_roi import field_roi_requested
    _, _, action = metadata(source)
    assert not field_roi_requested(action)
    action.update(field_phase=phase, focus_stage=stage, actual_text=None, value_reading=None,
        field_image_scope={"schema": "visual_field_roi.v1", "padding": 16})
    assert field_roi_requested(action)


@pytest.mark.parametrize("fault", ["extra", "padding", "operation", "phase", "stage", "missing_click",
    "native_snapshot", "native_reading", "actual_value", "temporal_stage"])
def test_invalid_roi_request_flag_rejects_instead_of_falling_back(source, fault):
    from app.judgment.field_roi import field_roi_requested
    _, _, action = metadata(source)
    action.update(focus_stage="after_click", field_image_scope={"schema": "visual_field_roi.v1", "padding": 16})
    if fault == "extra": action["field_image_scope"]["extra"] = True
    elif fault == "padding": action["field_image_scope"]["padding"] = True
    elif fault == "operation": action["operation"] = "click"
    elif fault == "phase": action["field_phase"] = []
    elif fault == "stage": action["focus_stage"] = []
    elif fault == "missing_click": action.pop("executed_click")
    elif fault == "native_snapshot": action["focus_value_snapshot"] = {}
    elif fault == "native_reading": action["value_reading"] = {"source": "uia"}
    elif fault == "actual_value": action["actual_text"] = "observed"
    else: action["focus_observation"] = {}
    with pytest.raises(ValueError, match="decision_field_roi_request_invalid"):
        field_roi_requested(action)


def test_roi_mapping_requires_integer_crop_coordinates(source):
    from app.judgment.field_roi import render_field_roi
    value = roi(source)
    value["crop_click_point"]["x"] = float(value["crop_click_point"]["x"])
    with pytest.raises(ValueError):
        render_field_roi(source[2], value)


def test_roi_annotation_preserves_center_and_field_pixels_outside_small_ring(source):
    from app.judgment.executed_click_annotation import executed_click_metadata, render_executed_click_annotation
    _, frame, action = metadata(source)
    action.update(focus_stage="after_click", field_image_scope={"schema": "visual_field_roi.v1", "padding": 16})
    value = executed_click_metadata(frame, (480, 240), action)
    with Image.open(BytesIO(source[2])) as full, Image.open(BytesIO(render_executed_click_annotation(source[2], value))) as marked:
        assert marked.size == (272, 82)
        assert marked.getpixel((56, 36)) == full.getpixel((120, 90))
        # 标签只能放字段外；除点击环与外刻度外，所有字段像素必须保持原样。
        for y in range(70, 120):
            for x in range(80, 320):
                if abs(x-120) <= 14 and abs(y-90) <= 14:
                    continue
                assert marked.getpixel((x-64, y-54)) == full.getpixel((x, y))
