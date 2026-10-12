"""原图坐标的纯标注派生；元数据不读取图片，也不授予输入权限。"""
from hashlib import sha256
from io import BytesIO
import re

from PIL import Image, ImageDraw, UnidentifiedImageError


_SCHEMA = "decision_candidate_annotation.v1"
_FIELDS = {"schema", "capture_id", "source_sha256", "role", "viewport_size", "bbox", "click_point", "candidate_id"}
_ROLES = {"before", "after", "observation", "sample_start", "sample_middle", "sample_end"}


def _text(value, name):
    if type(value) is not str or not value.strip() or len(value) > 200:
        raise ValueError("decision_candidate_annotation_" + name + "_invalid")
    return value


def _coordinates(value, keys):
    if type(value) is not dict or set(value) != set(keys) or any(type(value[k]) is not int for k in keys):
        raise ValueError("decision_candidate_annotation_coordinates_invalid")
    return {k: value[k] for k in keys}


def candidate_annotation_metadata(frame, dimensions, candidate) -> dict:
    """仅验证已知尺寸与原候选绑定，返回可重算的闭合认证元数据。"""
    if type(frame) is not dict or type(candidate) is not dict:
        raise ValueError("decision_candidate_annotation_binding_invalid")
    capture_id = _text(frame.get("capture_id"), "capture_id")
    if candidate.get("capture_id") != capture_id:
        raise ValueError("decision_candidate_annotation_capture_mismatch")
    source_sha256 = frame.get("sha256")
    if type(source_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", source_sha256) is None:
        raise ValueError("decision_candidate_annotation_source_hash_invalid")
    role = frame.get("role")
    if type(role) is not str or role not in _ROLES:
        raise ValueError("decision_candidate_annotation_role_invalid")
    if (type(dimensions) not in (tuple, list) or len(dimensions) != 2
            or any(type(v) is not int or v <= 0 for v in dimensions)
            or dimensions[0] * dimensions[1] > 40_000_000):
        raise ValueError("decision_candidate_annotation_dimensions_invalid")
    width, height = dimensions
    bbox = _coordinates(candidate.get("bbox"), ("x", "y", "w", "h"))
    point = _coordinates(candidate.get("click_point"), ("x", "y"))
    if (min(bbox["x"], bbox["y"]) < 0 or min(bbox["w"], bbox["h"]) <= 0
            or bbox["x"] + bbox["w"] > width or bbox["y"] + bbox["h"] > height
            or not (0 <= point["x"] < width and 0 <= point["y"] < height)
            or not (bbox["x"] <= point["x"] < bbox["x"] + bbox["w"]
                and bbox["y"] <= point["y"] < bbox["y"] + bbox["h"])):
        raise ValueError("decision_candidate_annotation_coordinates_outside")
    return {"schema": _SCHEMA, "capture_id": capture_id, "source_sha256": source_sha256, "role": role,
        "viewport_size": {"width": width, "height": height}, "bbox": bbox, "click_point": point,
        "candidate_id": _text(candidate.get("candidate_id"), "candidate_id")}


def render_candidate_annotation(data: bytes, metadata: dict) -> bytes:
    """保持原尺寸，只画点击环和十字，不画候选框；原字节不变。"""
    if type(metadata) is not dict or set(metadata) != _FIELDS or metadata.get("schema") != _SCHEMA:
        raise ValueError("decision_candidate_annotation_metadata_invalid")
    viewport = _coordinates(metadata["viewport_size"], ("width", "height"))
    checked = candidate_annotation_metadata(
        {"capture_id": metadata["capture_id"], "sha256": metadata["source_sha256"], "role": metadata["role"]},
        (viewport["width"], viewport["height"]),
        {"capture_id": metadata["capture_id"], "candidate_id": metadata["candidate_id"],
            "bbox": metadata["bbox"], "click_point": metadata["click_point"]})
    if type(data) is not bytes or not data or len(data) > 20 * 1024 * 1024:
        raise ValueError("decision_candidate_annotation_bytes_invalid")
    if sha256(data).hexdigest() != checked["source_sha256"]:
        raise ValueError("decision_candidate_annotation_source_hash_mismatch")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format != "PNG" or getattr(source, "is_animated", False) or getattr(source, "n_frames", 1) != 1:
                raise ValueError("decision_candidate_annotation_static_png_required")
            if source.size != (viewport["width"], viewport["height"]):
                raise ValueError("decision_candidate_annotation_dimensions_mismatch")
            source.verify()
        with Image.open(BytesIO(data)) as source:
            image = source.convert("RGBA")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise ValueError("decision_candidate_annotation_image_invalid") from None
    draw = ImageDraw.Draw(image)
    point = checked["click_point"]
    stroke = 2 if max(viewport.values()) >= 1920 else 1
    x, y = point["x"], point["y"]
    cyan = (0, 255, 255, 255)
    radius, reach = 6 * stroke, 9 * stroke
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=cyan, width=stroke)
    draw.line((x - reach, y, x + reach, y), fill=cyan, width=stroke)
    draw.line((x, y - reach, x, y + reach), fill=cyan, width=stroke)
    output = BytesIO()
    image.save(output, format="PNG", optimize=False, compress_level=3)
    return output.getvalue()
