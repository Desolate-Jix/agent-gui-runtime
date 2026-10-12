"""历史点击标注只派生原图，不引入桌面动作或新的执行许可。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json

from PIL import Image
import pytest

from app.judgment.executed_click_annotation import (
    executed_click_reference, executed_click_metadata, render_executed_click_annotation,
)


IDENTITY = {"handle": 10, "process_id": 20, "process_create_time": 123.0}
FIELD = {"click_point": {"x": 120, "y": 90}, "window_identity": IDENTITY,
    "window_rect": [-200, 300, 480, 240], "bbox": {"x": 80, "y": 70, "w": 240, "h": 50}}


@pytest.fixture
def source():
    screen = {"x": -80, "y": 390}
    click = {"clicked": True, "window_point": deepcopy(FIELD["click_point"]), "screen_point": screen,
        "down": {"button": "left", "state": "down", "cursor": deepcopy(screen)},
        "up": {"button": "left", "state": "up", "cursor": deepcopy(screen)},
        "button": "left", "click_count": 1, "window_handle": 10}
    receipt = {"contract_version": "local_direct_step_v1", "operation": "execute_recognition_plan",
        "phase": "returned", "local_input_scope_closed": True, "finished_at": "2026-10-12T00:00:00Z",
        "target_identity": {"target_window_handle": 10, "process_id": 20, "process_create_time": 123.0},
        "target_window_geometry": {"coordinate_space": "screen_pixels", "rect_format": "ltrb", "rect": [-200, 300, 280, 540]},
        "response": {"success": True, "data": {"result": {"execution_path": {"action_executed": True}, "click_result": click}}}}
    image = Image.new("RGBA", (480, 240), (11, 22, 33, 177))
    image.putpixel((120, 90), (203, 101, 51, 199))
    output = BytesIO()
    image.save(output, format="PNG")
    data = output.getvalue()
    return receipt, deepcopy(FIELD), data


def metadata(source, *, role="after"):
    receipt, field, data = source
    reference = executed_click_reference(receipt, field)
    frame = {"capture_id": "fresh-" + role, "sha256": sha256(data).hexdigest(), "role": role,
        "window_identity": deepcopy(IDENTITY)}
    action = {"operation": "visual_field_check", "field_phase": "focus", "field": field,
        "executed_click": reference, "focus_receipt_sha256": reference["receipt_sha256"]}
    return executed_click_metadata(frame, (480, 240), action), frame, action


def test_reference_binds_actual_click_and_nonzero_screen_origin_without_mutation(source):
    receipt, field, _ = source
    original = deepcopy((receipt, field))
    reference = executed_click_reference(receipt, field)
    digest = sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    assert reference == {"schema": "executed_click.v1", "receipt_sha256": digest,
        "click_point": {"x": 120, "y": 90}, "screen_point": {"x": -80, "y": 390},
        "window_identity": IDENTITY, "window_rect": [-200, 300, 480, 240],
        "coordinate_space": "capture_image_pixels"}
    reference["click_point"]["x"] = 1
    assert (receipt, field) == original


def test_legacy_receipt_without_any_physical_coordinates_has_no_annotation(source):
    receipt, field, _ = source
    receipt["response"]["data"]["result"]["click_result"] = {"clicked": True}
    assert executed_click_reference(receipt, field) is None


@pytest.mark.parametrize("damage", ["partial", "screen", "down", "up", "button", "count", "handle",
    "geometry", "float_geometry", "identity", "point", "not_completed", "open_scope", "no_action", "bool_point"])
def test_partial_or_contradictory_click_facts_are_rejected(source, damage):
    receipt, field, _ = source
    click = receipt["response"]["data"]["result"]["click_result"]
    if damage == "partial": click.pop("screen_point")
    elif damage == "screen": click["screen_point"]["x"] += 1
    elif damage == "down": click["down"]["cursor"]["y"] += 1
    elif damage == "up": click["up"]["cursor"]["x"] += 1
    elif damage == "button": click["button"] = "right"
    elif damage == "count": click["click_count"] = 2
    elif damage == "handle": click["window_handle"] += 1
    elif damage == "geometry": receipt["target_window_geometry"]["rect"][2] += 1
    elif damage == "float_geometry": receipt["target_window_geometry"]["rect"] = [-200.0, 300.0, 280.0, 540.0]
    elif damage == "identity": receipt["target_identity"]["process_create_time"] += 1
    elif damage == "point": field["click_point"]["x"] += 1
    elif damage == "not_completed": receipt["phase"] = "result_unknown"
    elif damage == "open_scope": receipt["local_input_scope_closed"] = False
    elif damage == "no_action": receipt["response"]["data"]["result"]["execution_path"]["action_executed"] = False
    else: click["window_point"]["x"] = True
    with pytest.raises(ValueError):
        executed_click_reference(receipt, field)


@pytest.mark.parametrize("phase", ["focus", "value"])
@pytest.mark.parametrize("role", ["before", "after"])
def test_metadata_keeps_historical_point_even_when_current_bbox_does_not_contain_it(source, phase, role):
    _, frame, action = metadata(source, role=role)
    action["field_phase"] = phase
    action["field"]["bbox"] = {"x": 300, "y": 150, "w": 100, "h": 40}
    original = deepcopy((frame, action))
    value = executed_click_metadata(frame, [480, 240], action)
    assert value["schema"] == "decision_executed_click_annotation.v1"
    assert value["capture_id"] == "fresh-" + role and value["role"] == role
    assert value["source_sha256"] == sha256(source[2]).hexdigest()
    assert value["viewport_size"] == {"width": 480, "height": 240}
    assert value["executed_click"]["click_point"] == {"x": 120, "y": 90}
    assert (frame, action) == original


@pytest.mark.parametrize("damage", ["receipt_hash", "source_hash", "window", "screen", "point",
    "dimensions", "rect", "operation", "phase", "malformed_phase"])
def test_metadata_rejects_binding_or_geometry_mismatch(source, damage):
    _, frame, action = metadata(source)
    dimensions = (480, 240)
    if damage == "receipt_hash": action["focus_receipt_sha256"] = "0" * 64
    elif damage == "source_hash": frame["sha256"] = "not-a-hash"
    elif damage == "window": frame["window_identity"]["process_id"] += 1
    elif damage == "screen": action["executed_click"]["screen_point"]["x"] += 1
    elif damage == "point": action["field"]["click_point"]["x"] += 1
    elif damage == "dimensions": dimensions = (481, 240)
    elif damage == "rect": action["field"]["window_rect"][0] += 1
    elif damage == "operation": action["operation"] = "click"
    elif damage == "malformed_phase": action["field_phase"] = {}
    else: action["field_phase"] = "selection"
    with pytest.raises(ValueError):
        executed_click_metadata(frame, dimensions, action)


def test_render_preserves_original_bytes_size_alpha_and_center_pixel(source):
    value, _, _ = metadata(source)
    data = source[2]
    original = bytes(data)
    output = render_executed_click_annotation(data, value)
    assert data == original and output != original
    with Image.open(BytesIO(data)) as before, Image.open(BytesIO(output)) as after:
        assert before.size == after.size == (480, 240)
        assert after.getpixel((120, 90)) == before.getpixel((120, 90))
        assert after.getpixel((120, 82))[:3] == (0, 174, 207)
        assert after.getpixel((479, 239)) == before.getpixel((479, 239))
        assert after.getpixel((120, 70)) == before.getpixel((120, 70))


@pytest.mark.parametrize("damage", ["hash", "dimensions", "jpeg", "animated", "metadata"])
def test_render_rejects_changed_source_or_invalid_metadata(source, damage):
    value, _, _ = metadata(source)
    data = source[2]
    if damage == "hash": value["source_sha256"] = "0" * 64
    elif damage == "dimensions": value["viewport_size"]["width"] += 1
    elif damage in {"jpeg", "animated"}:
        output = BytesIO()
        image = Image.new("RGB", (480, 240), "red")
        if damage == "jpeg": image.save(output, format="JPEG")
        else: image.save(output, format="PNG", save_all=True, append_images=[Image.new("RGB", (480, 240), "blue")])
        data = output.getvalue()
        value["source_sha256"] = sha256(data).hexdigest()
    else: value["extra"] = True
    with pytest.raises(ValueError):
        render_executed_click_annotation(data, value)
