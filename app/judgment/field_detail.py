"""从已绑定同帧 PNG 派生无标记局部图，不读取路径或增加时刻。"""
import base64
from hashlib import sha256
from io import BytesIO

from PIL import Image, UnidentifiedImageError


_PREFIX = "data:image/png;base64,"
_MAX_BYTES = 20 * 1024 * 1024
_MAX_PIXELS = 40_000_000
_MAX_DETAIL_EDGE = 1024
FIELD_DETAIL_INTRO = (
    "Any field detail image is an unmarked, unscaled crop of the immediately preceding original image, "
    "not an additional time frame. Its metadata gives the source capture, role and original-image crop coordinates. "
    "Use these same-frame details to inspect small differences; still inspect the full original images for target "
    "meaning and actual UI clipping. An artificial crop edge is not UI text clipping. "
    "Judge actual UI clipping from the full original images. Inspect those originals for target "
    "meaning, focus redirection, obstructions and the exact supplied condition. A crop is not independent evidence "
    "or permission, and native value equality alone does not establish safety.")


def build_field_detail(frame, field, changed_region, *, padding=64, max_detail_edge=_MAX_DETAIL_EDGE):
    """限定字节、尺寸及原坐标；超大变化保留完整原图，不截去部分变化。"""
    if (type(padding) is not int or not 0 <= padding <= 64
            or type(max_detail_edge) is not int or not 1 <= max_detail_edge <= 4096):
        raise ValueError("decision_field_detail_limits_invalid")
    window = field.get("window_rect") if type(field) is dict else None
    if (type(window) is not list or len(window) != 4 or any(type(n) is not int for n in window)
            or min(window[2:]) <= 0 or window[2] * window[3] > _MAX_PIXELS):
        raise ValueError("decision_field_detail_dimensions_invalid")
    width, height = window[2:]
    if (type(frame) is not dict or type(frame.get("capture_id")) is not str
            or not frame["capture_id"].strip() or len(frame["capture_id"]) > 200
            or frame.get("role") not in {"before", "after"}):
        raise ValueError("decision_field_detail_binding_invalid")
    if (type(changed_region) is not dict or set(changed_region) != {"x", "y", "w", "h"}
            or any(type(n) is not int for n in changed_region.values())):
        raise ValueError("decision_field_detail_region_invalid")
    x, y, w, h = (changed_region[key] for key in ("x", "y", "w", "h"))
    if min(x, y) < 0 or min(w, h) <= 0 or x + w > width or y + h > height:
        raise ValueError("decision_field_detail_region_invalid")
    url = frame.get("data_url")
    if type(url) is not str or not url.startswith(_PREFIX):
        raise ValueError("decision_field_detail_inline_png_required")
    encoded = url[len(_PREFIX):]
    if len(encoded) > 4 * ((_MAX_BYTES + 2) // 3):
        raise ValueError("decision_field_detail_bytes_invalid")
    try:
        data = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ValueError("decision_field_detail_encoding_invalid") from None
    if not data or len(data) > _MAX_BYTES:
        raise ValueError("decision_field_detail_bytes_invalid")
    left, top, right, bottom = max(0, x - padding), max(0, y - padding), min(width, x + w + padding), min(height, y + h + padding)
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format != "PNG" or getattr(source, "is_animated", False) or getattr(source, "n_frames", 1) != 1:
                raise ValueError("decision_field_detail_static_png_required")
            if source.size != (width, height):
                raise ValueError("decision_field_detail_dimensions_mismatch")
            source.verify()
        if max(right - left, bottom - top) > max_detail_edge:
            return None
        with Image.open(BytesIO(data)) as source:
            crop = source.crop((left, top, right, bottom)).convert("RGBA")
        output = BytesIO()
        crop.save(output, format="PNG", optimize=False, compress_level=3)
        cropped = output.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise ValueError("decision_field_detail_image_invalid") from None
    if len(cropped) > _MAX_BYTES:
        raise ValueError("decision_field_detail_bytes_invalid")
    return {"metadata": {"schema": "decision_field_detail.v1", "source_capture_id": frame["capture_id"],
        "role": frame["role"], "source_sha256": sha256(data).hexdigest(),
        "source_size": {"width": width, "height": height},
        "crop_bbox": {"x": left, "y": top, "w": right - left, "h": bottom - top}},
        "data_url": _PREFIX + base64.b64encode(cropped).decode("ascii")}
