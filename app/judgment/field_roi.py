"""同帧完整字段裁剪；原图坐标与裁剪坐标分开记录，不执行 OCR 或输入。"""
from hashlib import sha256
from io import BytesIO
from math import isfinite
import re

from PIL import Image, UnidentifiedImageError


_MAX_BYTES = 20 * 1024 * 1024
_MAX_PIXELS = 40_000_000
_FIELDS = {"schema", "source_capture_id", "source_sha256", "role", "window_identity", "window_rect",
    "source_size", "field_bbox", "crop_bbox", "upload_size", "click_point_original", "crop_click_point", "scale"}


def _invalid(reason):
    raise ValueError("decision_field_roi_" + reason)


def _coordinates(value, keys):
    if type(value) is not dict or set(value) != set(keys) or any(type(value[k]) is not int for k in keys):
        _invalid("coordinates_invalid")
    return dict(value)


def _identity(value):
    if (type(value) is not dict or set(value) != {"handle", "process_id", "process_create_time"}
            or any(type(value[k]) is not int or value[k] <= 0 for k in ("handle", "process_id"))
            or type(value["process_create_time"]) not in (int, float)
            or not isfinite(value["process_create_time"]) or value["process_create_time"] <= 0):
        _invalid("window_identity_invalid")
    return dict(value)


def field_roi_requested(action) -> bool:
    if type(action) is not dict or "field_image_scope" not in action:
        return False
    flag = action["field_image_scope"]
    if (type(flag) is not dict or set(flag) != {"schema", "padding"}
            or flag["schema"] != "visual_field_roi.v1" or type(flag["padding"]) is not int or flag["padding"] != 16
            or action.get("operation") != "visual_field_check" or action.get("field_phase") not in ("focus", "value")
            or action.get("focus_stage") not in (("after_click", "after_selection") if action["field_phase"] == "focus" else (None,))
            or action.get("actual_text") is not None or action.get("value_reading") is not None
            or type(action.get("executed_click")) is not dict
            or any(key in action for key in ("focus_value_snapshot", "field_freshness_context", "focus_observation"))):
        _invalid("request_invalid")
    return True


def field_roi_metadata(frame, dimensions, field, *, padding=16) -> dict:
    """完整字段加固定边缘；只有图像边界可以夹取，不缩放或只裁点击附近。"""
    if type(padding) is not int or padding != 16:
        _invalid("padding_invalid")
    if (type(dimensions) not in (tuple, list) or len(dimensions) != 2
            or any(type(n) is not int or n <= 0 for n in dimensions) or dimensions[0] * dimensions[1] > _MAX_PIXELS):
        _invalid("dimensions_invalid")
    width, height = dimensions
    if (type(frame) is not dict or type(field) is not dict or type(frame.get("capture_id")) is not str
            or not frame["capture_id"].strip() or len(frame["capture_id"]) > 200
            or frame.get("role") not in ("before", "after")
            or type(frame.get("sha256")) is not str or re.fullmatch(r"[0-9a-f]{64}", frame["sha256"]) is None):
        _invalid("source_binding_invalid")
    identity = _identity(frame.get("window_identity"))
    rect = field.get("window_rect")
    if (identity != _identity(field.get("window_identity")) or type(rect) is not list or len(rect) != 4
            or any(type(n) is not int for n in rect) or rect[2:] != [width, height]):
        _invalid("source_geometry_invalid")
    bbox = _coordinates(field.get("bbox"), ("x", "y", "w", "h"))
    x, y, w, h = (bbox[k] for k in ("x", "y", "w", "h"))
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > width or y + h > height:
        _invalid("field_bbox_invalid")
    left, top, right, bottom = max(0, x-padding), max(0, y-padding), min(width, x+w+padding), min(height, y+h+padding)
    point = _coordinates(field.get("click_point"), ("x", "y"))
    if not (left <= point["x"] < right and top <= point["y"] < bottom):
        _invalid("click_outside_crop")
    return {"schema": "decision_field_roi.v1", "source_capture_id": frame["capture_id"], "source_sha256": frame["sha256"],
        "role": frame["role"], "window_identity": identity, "window_rect": list(rect),
        "source_size": {"width": width, "height": height}, "field_bbox": bbox,
        "crop_bbox": {"x": left, "y": top, "w": right-left, "h": bottom-top},
        "upload_size": {"width": right-left, "height": bottom-top},
        "click_point_original": point, "crop_click_point": {"x": point["x"]-left, "y": point["y"]-top}, "scale": 1}


def render_field_roi(data: bytes, metadata: dict) -> bytes:
    """返回无标记原像素裁剪；OCR 与远端标注共用同一份几何。"""
    if type(metadata) is not dict or set(metadata) != _FIELDS or metadata.get("schema") != "decision_field_roi.v1":
        _invalid("metadata_invalid")
    size = _coordinates(metadata["source_size"], ("width", "height"))
    _coordinates(metadata["crop_bbox"], ("x", "y", "w", "h"))
    _coordinates(metadata["upload_size"], ("width", "height"))
    _coordinates(metadata["crop_click_point"], ("x", "y"))
    expected = field_roi_metadata({"capture_id": metadata["source_capture_id"], "sha256": metadata["source_sha256"],
        "role": metadata["role"], "window_identity": metadata["window_identity"]}, (size["width"], size["height"]),
        {"window_identity": metadata["window_identity"], "window_rect": metadata["window_rect"],
            "bbox": metadata["field_bbox"], "click_point": metadata["click_point_original"]})
    if expected != metadata or type(metadata["scale"]) is not int:
        _invalid("mapping_invalid")
    if type(data) is not bytes or not data or len(data) > _MAX_BYTES or sha256(data).hexdigest() != expected["source_sha256"]:
        _invalid("source_hash_mismatch")
    box = expected["crop_bbox"]
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format != "PNG" or getattr(source, "is_animated", False) or getattr(source, "n_frames", 1) != 1:
                _invalid("static_png_required")
            if source.size != (size["width"], size["height"]):
                _invalid("dimensions_mismatch")
            source.verify()
        with Image.open(BytesIO(data)) as source:
            crop = source.crop((box["x"], box["y"], box["x"]+box["w"], box["y"]+box["h"])).convert("RGBA")
        output = BytesIO()
        crop.save(output, format="PNG", optimize=False, compress_level=3)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        _invalid("image_invalid")
    rendered = output.getvalue()
    if len(rendered) > _MAX_BYTES:
        _invalid("bytes_invalid")
    return rendered
