"""字段值的完整裁剪显示派生；复用原标注认证，不读取或生成目标文字。"""
from io import BytesIO

from PIL import Image, ImageDraw

from .executed_click_annotation import render_executed_click_annotation
from .field_roi import render_field_roi


def render_field_value_view(data: bytes, metadata: dict) -> tuple[bytes, dict]:
    """只接受 v2 字段 ROI；安全尺寸内放大原像素并在外沿标记点击位置。"""
    if type(metadata) is not dict or metadata.get("schema") != "decision_executed_click_annotation.v2":
        raise ValueError("decision_field_value_view_metadata_invalid")
    # 原 renderer 完整重验哈希、静态 PNG、身份与裁剪映射后才返回已标图。
    marked = render_executed_click_annotation(data, metadata)
    with Image.open(BytesIO(marked)) as image:
        width, height = image.size
    doubled_size = (width * 2 + 16, height * 2 + 16)
    doubled = max(width, height) * 2 <= 4096 and width * height * 4 <= 4_000_000
    margin_fits = doubled and max(doubled_size) <= 4096 and doubled_size[0] * doubled_size[1] <= 4_000_000
    point = metadata["field_roi"]["crop_click_point"]
    if margin_fits:
        with Image.open(BytesIO(render_field_roi(data, metadata["field_roi"]))) as image:
            roi = image.convert("RGBA")
        enlarged = roi.resize((width * 2, height * 2), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", doubled_size, (255, 255, 255, 255))
        canvas.paste(enlarged, (8, 8))
        x, y = point["x"] * 2 + 9, point["y"] * 2 + 9
        draw = ImageDraw.Draw(canvas)
        ink = (0, 194, 207, 255)
        draw.polygon([(x - 4, 1), (x + 4, 1), (x, 7)], fill=ink)
        draw.polygon([(1, y - 4), (1, y + 4), (7, y)], fill=ink)
        output = BytesIO()
        canvas.save(output, format="PNG", optimize=False, compress_level=3)
        marked = output.getvalue()
        mapping = {
            "schema": "decision_field_value_view.v2",
            "annotation_layout": "margin_ticks",
            "image_offset": {"x": 8, "y": 8},
            "source_roi_size": {"width": width, "height": height},
            "upload_size": {"width": doubled_size[0], "height": doubled_size[1]},
            "scale_xy": [2, 2],
            "marker_center_exact": {key: (point[key] + .5) * 2 - .5 + 8 for key in ("x", "y")},
        }
    else:
        mapping = {
            "schema": "decision_field_value_view.v1",
            "source_roi_size": {"width": width, "height": height},
            "upload_size": {"width": width, "height": height},
            "scale_xy": [1, 1],
            "marker_center_exact": {key: (point[key] + .5) - .5 for key in ("x", "y")},
        }
    return marked, mapping
