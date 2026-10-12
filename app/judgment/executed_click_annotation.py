"""真实历史点击的纯标注派生；不读路径、不授予输入或焦点证明。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from math import isfinite
import re

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError


_REFERENCE_FIELDS = {"schema", "receipt_sha256", "click_point", "screen_point", "window_identity",
    "window_rect", "coordinate_space"}
_METADATA_FIELDS = {"schema", "capture_id", "source_sha256", "role", "viewport_size", "executed_click", "bbox"}
_METADATA_ROI_FIELDS = _METADATA_FIELDS | {"field_roi"}
_METADATA_RESULT_FIELDS = _METADATA_FIELDS - {"bbox"}
_ROLES = {"before", "after", "observation", "sample_start", "sample_middle", "sample_end"}
_MAX_PIXELS = 40_000_000


def _invalid(reason):
    raise ValueError("decision_executed_click_" + reason)


def _coordinates(value, keys):
    if type(value) is not dict or set(value) != set(keys) or any(type(value[k]) is not int for k in keys):
        _invalid("coordinates_invalid")
    return {key: value[key] for key in keys}


def _hash(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _invalid("hash_invalid")
    return value


def _identity(value):
    if type(value) is not dict:
        _invalid("window_identity_invalid")
    handle = value.get("handle", value.get("target_window_handle"))
    pid, born = value.get("process_id"), value.get("process_create_time")
    if (type(handle) is not int or handle <= 0 or type(pid) is not int or pid <= 0
            or type(born) not in (int, float) or not isfinite(born) or born <= 0
            or "target_window_handle" in value and value["target_window_handle"] != handle):
        _invalid("window_identity_invalid")
    return {"handle": handle, "process_id": pid, "process_create_time": born}


def _rect(value):
    if (type(value) is not list or len(value) != 4 or any(type(n) is not int for n in value)
            or min(value[2:]) <= 0 or value[2] * value[3] > _MAX_PIXELS):
        _invalid("window_geometry_invalid")
    return list(value)


def _dimensions(value):
    if (type(value) not in (tuple, list) or len(value) != 2
            or any(type(n) is not int or n <= 0 for n in value) or value[0] * value[1] > _MAX_PIXELS):
        _invalid("dimensions_invalid")
    return tuple(value)


def _checked_reference(value):
    if (type(value) is not dict or set(value) != _REFERENCE_FIELDS or value.get("schema") != "executed_click.v1"
            or value.get("coordinate_space") != "capture_image_pixels"):
        _invalid("reference_invalid")
    _hash(value["receipt_sha256"])
    _identity(value["window_identity"])
    left, top, width, height = _rect(value["window_rect"])
    point = _coordinates(value["click_point"], ("x", "y"))
    screen = _coordinates(value["screen_point"], ("x", "y"))
    if (not (0 <= point["x"] < width and 0 <= point["y"] < height)
            or screen != {"x": left + point["x"], "y": top + point["y"]}):
        _invalid("point_mapping_invalid")
    return deepcopy(value)


def executed_click_reference(receipt, field) -> dict | None:
    """仅从完成的原生点击事实生成引用；旧无坐标回执不伪造实际位置。"""
    if type(receipt) is not dict or type(field) is not dict:
        _invalid("receipt_invalid")
    api = receipt.get("response")
    data = api.get("data") if type(api) is dict else None
    data = data.get("result", data) if type(data) is dict else None
    if type(data) is not dict:
        _invalid("receipt_invalid")
    path = data.get("execution_path") or {}
    click = data.get("click_result")
    if (receipt.get("contract_version") != "local_direct_step_v1"
            or receipt.get("operation") != "execute_recognition_plan" or receipt.get("phase") != "returned"
            or receipt.get("local_input_scope_closed") is not True
            or type(receipt.get("finished_at")) is not str or not receipt["finished_at"].strip()
            or api.get("success") is not True or type(path) is not dict
            or path.get("action_executed", data.get("action_executed")) is not True
            or "action_executed" in data and data["action_executed"] is not True
            or "action_executed" in receipt and receipt["action_executed"] is not True
            or type(click) is not dict or click.get("clicked") is not True):
        _invalid("original_click_not_completed")
    identity = _identity(field.get("window_identity"))
    rect = _rect(field.get("window_rect"))
    geometry = receipt.get("target_window_geometry") or {}
    if (type(geometry) is not dict or geometry.get("coordinate_space") != "screen_pixels"
            or geometry.get("rect_format") != "ltrb"
            or type(geometry.get("rect")) is not list or len(geometry["rect"]) != 4
            or any(type(n) is not int for n in geometry["rect"])
            or geometry.get("rect") != [rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3]]
            or _identity(receipt.get("target_identity")) != identity):
        _invalid("window_binding_invalid")
    point = _coordinates(field.get("click_point"), ("x", "y"))
    if ("button" in click and click["button"] != "left"
            or "click_count" in click and (type(click["click_count"]) is not int or click["click_count"] != 1)
            or "window_handle" in click and (type(click["window_handle"]) is not int or click["window_handle"] != identity["handle"])):
        _invalid("click_binding_invalid")
    if not any(key in click for key in ("window_point", "screen_point", "down", "up", "click_events")):
        return None
    actual = _coordinates(click.get("window_point"), ("x", "y"))
    screen = _coordinates(click.get("screen_point"), ("x", "y"))
    if (actual != point or click.get("button") != "left" or type(click.get("click_count")) is not int
            or click["click_count"] != 1 or type(click.get("window_handle")) is not int
            or click["window_handle"] != identity["handle"]):
        _invalid("click_binding_invalid")
    for phase in ("down", "up"):
        event = click.get(phase)
        if (type(event) is not dict or _coordinates(event.get("cursor"), ("x", "y")) != screen
                or event.get("button", "left") != "left" or event.get("state", phase) != phase):
            _invalid("click_cursor_mismatch")
    digest = sha256(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return _checked_reference({"schema": "executed_click.v1", "receipt_sha256": digest,
        "click_point": point, "screen_point": screen, "window_identity": identity, "window_rect": rect,
        "coordinate_space": "capture_image_pixels"})


def executed_click_metadata(frame, dimensions, action) -> dict:
    """校验同窗口与原回执映射；当前字段框只供标注标签布局。"""
    if type(frame) is not dict or type(action) is not dict:
        _invalid("binding_invalid")
    capture_id, role = frame.get("capture_id"), frame.get("role")
    if (type(capture_id) is not str or not capture_id.strip() or len(capture_id) > 200
            or type(role) is not str or role not in _ROLES):
        _invalid("frame_invalid")
    width, height = _dimensions(dimensions)
    reference = _checked_reference(action.get("executed_click"))
    if action.get("operation") == "step_result_check":
        if (set(action) != {"operation", "kind", "input_receipt_sha256", "executed_click"}
                or action.get("kind") != "click" or role != "after"
                or action.get("input_receipt_sha256") != reference["receipt_sha256"]
                or _identity(frame.get("window_identity")) != reference["window_identity"]
                or (width, height) != tuple(reference["window_rect"][2:])):
            _invalid("binding_mismatch")
        return {"schema": "decision_executed_click_annotation.v3", "capture_id": capture_id,
            "source_sha256": _hash(frame.get("sha256")), "role": role,
            "viewport_size": {"width": width, "height": height}, "executed_click": reference}
    field = action.get("field")
    if (action.get("operation") != "visual_field_check" or type(action.get("field_phase")) is not str
            or action["field_phase"] not in {"focus", "value"}
            or type(field) is not dict or action.get("focus_receipt_sha256") != reference["receipt_sha256"]
            or _identity(frame.get("window_identity")) != reference["window_identity"]
            or _identity(field.get("window_identity")) != reference["window_identity"]
            or _rect(field.get("window_rect")) != reference["window_rect"]
            or (width, height) != tuple(reference["window_rect"][2:])
            or _coordinates(field.get("click_point"), ("x", "y")) != reference["click_point"]):
        _invalid("binding_mismatch")
    bbox = _coordinates(field.get("bbox"), ("x", "y", "w", "h"))
    if (min(bbox["x"], bbox["y"]) < 0 or min(bbox["w"], bbox["h"]) <= 0
            or bbox["x"] + bbox["w"] > width or bbox["y"] + bbox["h"] > height):
        _invalid("label_bbox_invalid")
    result = {"schema": "decision_executed_click_annotation.v1", "capture_id": capture_id,
        "source_sha256": _hash(frame.get("sha256")), "role": role,
        "viewport_size": {"width": width, "height": height}, "executed_click": reference, "bbox": bbox}
    from .field_roi import field_roi_requested, field_roi_metadata
    if field_roi_requested(action):
        result.update(schema="decision_executed_click_annotation.v2",
            field_roi=field_roi_metadata(frame, dimensions, field, padding=action["field_image_scope"]["padding"]))
    return result


def render_executed_click_annotation(data: bytes, metadata: dict) -> bytes:
    """保持原尺寸与中心像素，仅画空心环、外刻度及历史坐标标签。"""
    if type(metadata) is not dict:
        _invalid("metadata_invalid")
    roi = metadata.get("schema") == "decision_executed_click_annotation.v2"
    generic = metadata.get("schema") == "decision_executed_click_annotation.v3"
    if (set(metadata) != (_METADATA_RESULT_FIELDS if generic else _METADATA_ROI_FIELDS if roi else _METADATA_FIELDS)
            or metadata.get("schema") != ("decision_executed_click_annotation.v3" if generic else
                "decision_executed_click_annotation.v2" if roi else "decision_executed_click_annotation.v1")):
        _invalid("metadata_invalid")
    viewport = _coordinates(metadata["viewport_size"], ("width", "height"))
    reference = _checked_reference(metadata["executed_click"])
    checked = executed_click_metadata({"capture_id": metadata["capture_id"], "sha256": metadata["source_sha256"],
        "role": metadata["role"], "window_identity": reference["window_identity"]},
        (viewport["width"], viewport["height"]),
        {"operation": "step_result_check", "kind": "click", "input_receipt_sha256": reference["receipt_sha256"],
            "executed_click": reference} if generic else
        {"operation": "visual_field_check", "field_phase": "focus",
            **({"focus_stage": "after_click", "field_image_scope": {"schema": "visual_field_roi.v1", "padding": 16}} if roi else {}),
            "executed_click": reference, "focus_receipt_sha256": reference["receipt_sha256"],
            "field": {"window_identity": reference["window_identity"], "window_rect": reference["window_rect"],
                "click_point": reference["click_point"], "bbox": metadata["bbox"]}})
    if checked != metadata:
        _invalid("metadata_binding_mismatch")
    if type(data) is not bytes or not data or len(data) > 20 * 1024 * 1024:
        _invalid("bytes_invalid")
    if sha256(data).hexdigest() != checked["source_sha256"]:
        _invalid("source_hash_mismatch")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format != "PNG" or getattr(source, "is_animated", False) or getattr(source, "n_frames", 1) != 1:
                _invalid("static_png_required")
            if source.size != (viewport["width"], viewport["height"]):
                _invalid("dimensions_mismatch")
            source.verify()
        with Image.open(BytesIO(data)) as source:
            image = source.convert("RGBA")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        _invalid("image_invalid")
    if roi:
        from .field_roi import render_field_roi
        with Image.open(BytesIO(render_field_roi(data, checked["field_roi"]))) as cropped:
            image = cropped.convert("RGBA")
    width, height = image.size
    point = checked["field_roi"]["crop_click_point"] if roi else reference["click_point"]
    x, y = (point[key] for key in ("x", "y"))
    center = image.getpixel((x, y))
    draw = ImageDraw.Draw(image)
    ink = (0, 174, 207, 255)
    draw.ellipse((x - 8, y - 8, x + 8, y + 8), outline=ink, width=2)
    for line in ((x - 13, y, x - 9, y), (x + 9, y, x + 13, y),
                 (x, y - 13, x, y - 9), (x, y + 9, x, y + 13)):
        draw.line(line, fill=ink, width=2)
    if not generic:
        font = ImageFont.load_default(size=18)
        original_point = reference["click_point"]
        label = f"CLICK 1 x={original_point['x']} y={original_point['y']}"
        bounds = draw.textbbox((0, 0), label, font=font)
        label_w, label_h = bounds[2] - bounds[0] + 16, bounds[3] - bounds[1] + 12
        box = dict(checked["bbox"])
        if roi:
            box["x"] -= checked["field_roi"]["crop_bbox"]["x"]
            box["y"] -= checked["field_roi"]["crop_bbox"]["y"]
        lx = max(0, min(width - label_w, x - label_w // 2))
        candidates = [(lx, box["y"] - label_h - 8), (lx, box["y"] + box["h"] + 8),
            (box["x"] - label_w - 8, max(0, min(height - label_h, y - label_h // 2))),
            (box["x"] + box["w"] + 8, max(0, min(height - label_h, y - label_h // 2))),
            (0, 0), (max(0, width - label_w), max(0, height - label_h))]
        for label_x, label_y in candidates:
            if (0 <= label_x and label_x + label_w <= width and 0 <= label_y and label_y + label_h <= height
                    and (not roi or label_x + label_w < box["x"] or label_x > box["x"] + box["w"]
                        or label_y + label_h < box["y"] or label_y > box["y"] + box["h"])
                    and not (label_x - 14 <= x <= label_x + label_w + 14 and label_y - 14 <= y <= label_y + label_h + 14)):
                draw.rounded_rectangle((label_x, label_y, label_x + label_w, label_y + label_h),
                    radius=5, fill=(19, 44, 52, 255))
                draw.text((label_x + 8 - bounds[0], label_y + 6 - bounds[1]), label, font=font, fill=(124, 237, 255, 255))
                break
    # 极小图或边缘标记也不得盖住实际点击中心。
    image.putpixel((x, y), center)
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=3)
    return output.getvalue()
