"""原候选的全窗与细节双视图；仅派生显示，不改变认证或输入权限。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import math

from PIL import Image, ImageDraw, UnidentifiedImageError

from .candidate_annotation import candidate_annotation_metadata


_FIELDS = {"schema", "capture_id", "source_sha256", "role", "viewport_size", "bbox", "click_point", "candidate_id"}


def _invalid(reason):
    raise ValueError("decision_candidate_view_" + reason)


def _checked_metadata(metadata):
    if (type(metadata) is not dict or set(metadata) != _FIELDS
            or metadata.get("schema") != "decision_candidate_annotation.v1"):
        _invalid("metadata_invalid")
    viewport = metadata["viewport_size"]
    if type(viewport) is not dict or set(viewport) != {"width", "height"}:
        _invalid("viewport_invalid")
    checked = candidate_annotation_metadata(
        {"capture_id": metadata["capture_id"], "sha256": metadata["source_sha256"], "role": metadata["role"]},
        (viewport["width"], viewport["height"]),
        {"capture_id": metadata["capture_id"], "candidate_id": metadata["candidate_id"],
            "bbox": metadata["bbox"], "click_point": metadata["click_point"]})
    if checked != metadata:
        _invalid("metadata_binding_mismatch")
    return checked


def _source_image(data, checked):
    if type(data) is not bytes or not data or len(data) > 20 * 1024 * 1024:
        _invalid("bytes_invalid")
    if sha256(data).hexdigest() != checked["source_sha256"]:
        _invalid("source_hash_mismatch")
    dimensions = (checked["viewport_size"]["width"], checked["viewport_size"]["height"])
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format != "PNG" or getattr(source, "is_animated", False) or getattr(source, "n_frames", 1) != 1:
                _invalid("static_png_required")
            if source.size != dimensions:
                _invalid("dimensions_mismatch")
            source.verify()
        with Image.open(BytesIO(data)) as source:
            return source.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        _invalid("image_invalid")


def _detail_crop(size, bbox):
    width, height = size
    x, y, w, h = (bbox[key] for key in ("x", "y", "w", "h"))
    # 尽可能保留四周 48 像素及最小上下文，极端视口以完整候选框为先。
    cw, ch = max(320, w + 96), max(160, h + 96)
    ch = max(ch, math.ceil(cw * 160 / 768))
    cw = max(cw, math.ceil(ch * 320 / 768))
    cw, ch = min(width, cw), min(height, ch)
    left = max(0, min(width - cw, math.floor(x + w / 2 - cw / 2)))
    top = max(0, min(height - ch, math.floor(y + h / 2 - ch / 2)))
    return left, top, left + cw, top + ch


def render_candidate_view(data: bytes, metadata: dict) -> tuple[bytes, dict]:
    """验证原图和闭合 v1 绑定，返回确定性 PNG 及精确坐标映射。"""
    checked = _checked_metadata(metadata)
    source = _source_image(data, checked)
    width, height = source.size
    bbox, point = checked["bbox"], checked["click_point"]
    crop = _detail_crop(source.size, bbox)
    views = []
    for name, rect, edge in (("overview", (0, 0, width, height), 640), ("detail", crop, 768)):
        # 每块视图独立从未标注原图裁剪，缩放后再画环，不能放大旧标记。
        view = source.crop(rect)
        ratio = min(2 if name == "detail" else 1, edge / max(view.size))
        size = tuple(max(1, round(value * ratio)) for value in view.size)
        view = view.resize(size, Image.Resampling.LANCZOS)
        sx, sy = size[0] / (rect[2] - rect[0]), size[1] / (rect[3] - rect[1])
        mapped = ((point["x"] - rect[0] + .5) * sx - .5,
                  (point["y"] - rect[1] + .5) * sy - .5)
        center = tuple(math.floor(value + .5) for value in mapped)
        px, py = center
        protected = (max(0, px - 6), max(0, py - 6), min(size[0], px + 7), min(size[1], py + 7))
        original_center = view.crop(protected)
        draw = ImageDraw.Draw(view)
        draw.ellipse((px - 11, py - 11, px + 11, py + 11), outline=(0, 255, 255), width=2)
        for a, b in (((px - 19, py), (px - 15, py)), ((px + 15, py), (px + 19, py)),
                     ((px, py - 19), (px, py - 15)), ((px, py + 15), (px, py + 19))):
            draw.line((a, b), fill=(0, 255, 255), width=2)
        # 极小图与边界也保留中心正负六像素，标记不成为目标内容的替代证据。
        view.paste(original_center, protected[:2])
        item = {"name": name, "source_crop_ltrb": list(rect), "size": list(size),
            "scale_xy": [sx, sy], "point_in_view_exact": list(mapped), "marker_center_in_view": list(center)}
        if name == "detail":
            item.update(crop_edges_are_ui_boundaries=False,
                source_frame_edges={"left": rect[0] == 0, "top": rect[1] == 0,
                    "right": rect[2] == width, "bottom": rect[3] == height})
        views.append((view, item))
    canvas_width = max(view.width for view, _ in views)
    canvas = Image.new("RGB", (canvas_width, sum(view.height for view, _ in views) + 48), "white")
    cursor, panels = 0, []
    for view, item in views:
        ImageDraw.Draw(canvas).text((4, cursor + 3), item["name"].title(), fill="black")
        origin = ((canvas_width - view.width) // 2, cursor + 20)
        canvas.paste(view, origin)
        item["image_origin_in_composite"] = list(origin)
        item["point_in_composite_exact"] = [origin[i] + item["point_in_view_exact"][i] for i in (0, 1)]
        item["marker_center_in_composite"] = [origin[i] + item["marker_center_in_view"][i] for i in (0, 1)]
        panels.append(item)
        cursor += view.height + 24
    mapping = {"schema": "decision_candidate_view.v1", "recipe": "overview_detail_zoom2.v1",
        "capture_id": checked["capture_id"], "candidate_id": checked["candidate_id"], "role": checked["role"],
        "source_size": [width, height], "source_sha256": checked["source_sha256"],
        "source_point": deepcopy(point), "source_bbox": deepcopy(bbox), "composite_size": list(canvas.size),
        "views": panels, "center_protected_radius_pixels": 6, "marker_radius_pixels": 11,
        "marker_width_pixels": 2, "marker_outer_tick_radii_pixels": [15, 19],
        "detail_padding_requested_pixels": 48, "detail_minimum_requested_size": [320, 160],
        "detail_minimum_met": views[1][0].width >= 320 and views[1][0].height >= 160,
        "detail_includes_complete_bbox": True, "overview_includes_complete_frame": True}
    output = BytesIO()
    canvas.save(output, format="PNG", optimize=False, compress_level=3)
    return output.getvalue(), mapping
