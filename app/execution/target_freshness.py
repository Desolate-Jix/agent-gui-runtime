"""认证原图完整性并严格比较目标及锚点；不签发输入权限或猜测无关区域。"""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from app.judgment.evidence import _prepare_frame


def _size(value):
    if (type(value) is not dict or set(value) != {"width", "height"}
            or any(type(value[key]) is not int or value[key] <= 0 for key in value)):
        raise ValueError("viewport_metadata_invalid")
    return value["width"], value["height"]


def _bbox(value, size):
    if (type(value) is not dict or set(value) != {"x", "y", "w", "h"}
            or any(type(value[key]) is not int for key in value)):
        raise ValueError("region_geometry_invalid")
    x, y, w, h = (value[key] for key in ("x", "y", "w", "h"))
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > size[0] or y + h > size[1]:
        raise ValueError("region_geometry_invalid")
    return x, y, x + w, y + h


def _visibility(capture, size):
    value = capture.get("capture_visibility")
    if value is None:
        return ()
    if (type(value) is not dict or value.get("allowed") is not True
            or value.get("coordinate_space") != "window"
            or type(value.get("occluded_regions")) is not list
            or len(value["occluded_regions"]) > 64):
        raise ValueError("capture_visibility_unknown")
    regions = []
    for region in value["occluded_regions"]:
        if type(region) is not dict or set(region) != {"x", "y", "width", "height"}:
            raise ValueError("capture_visibility_unknown")
        regions.append(_bbox({"x": region["x"], "y": region["y"],
            "w": region["width"], "h": region["height"]}, size))
    if value.get("masked") is True and not regions:
        raise ValueError("capture_visibility_unknown")
    return tuple(sorted(set(regions)))


def _frame(capture):
    if type(capture) is not dict:
        raise ValueError("capture_metadata_invalid")
    fields = {key: capture[key] for key in ("capture_id", "image_path", "sha256", "window_identity", "role")}
    if fields["role"] not in {"before", "observation"}:
        raise ValueError("capture_role_invalid")
    if type(fields["image_path"]) is not str or not Path(fields["image_path"]).is_absolute():
        raise ValueError("capture_path_invalid")
    # 会话归属由调用边界先认证；复用纯证据 helper 校验本次读取的完整原图字节。
    normalized, data, _, actual_size = _prepare_frame(
        Path(fields["image_path"]).parent.resolve(strict=True), fields, static_png=True)
    size = _size(capture.get("image_size"))
    rect = capture.get("window_rect")
    if (type(rect) not in (tuple, list) or len(rect) != 4
            or any(type(value) is not int for value in rect)
            or rect[2] <= rect[0] or rect[3] <= rect[1]
            or (rect[2] - rect[0], rect[3] - rect[1]) != size
            or actual_size != size or capture.get("roi") is not None):
        raise ValueError("capture_geometry_invalid")
    visibility = _visibility(capture, size)
    with Image.open(BytesIO(data)) as image:
        pixels = image.convert("RGBA")
    return normalized, pixels, size, tuple(rect), visibility


def _overlap(first, second):
    return (max(first[0], second[0]) < min(first[2], second[2])
        and max(first[1], second[1]) < min(first[3], second[3]))


def _box_dict(box):
    return {"x": box[0], "y": box[1], "w": box[2] - box[0], "h": box[3] - box[1]}


def check_target_freshness(*, before: dict, current: dict, candidate: dict,
                           context_regions: list[dict]) -> dict:
    """消费宿主认证过的 capture；未解释的变化返回 unknown，任何结果均不是输入许可。"""
    result = {"schema": "target_freshness.v1", "status": "unknown", "reason": "evidence_invalid",
        "authorizes_action": False, "before_capture_id": None, "current_capture_id": None,
        "source_sha256": None, "current_sha256": None, "protected_regions": [],
        "uncovered_change_bbox": None}
    try:
        original, original_pixels, size, rect, original_masks = _frame(before)
        observed, current_pixels, current_size, current_rect, current_masks = _frame(current)
        result.update(before_capture_id=original["capture_id"], current_capture_id=observed["capture_id"],
            source_sha256=original["sha256"], current_sha256=observed["sha256"])
        if type(candidate) is not dict or candidate.get("capture_id") != original["capture_id"]:
            raise ValueError("candidate_capture_mismatch")
        if _size(candidate.get("viewport_size")) != size:
            raise ValueError("candidate_viewport_mismatch")
        target = _bbox(candidate.get("bbox"), size)
        point = candidate.get("click_point")
        if (type(point) is not dict or set(point) != {"x", "y"}
                or any(type(point[key]) is not int for key in point)
                or not (target[0] <= point["x"] < target[2] and target[1] <= point["y"] < target[3])):
            raise ValueError("candidate_point_invalid")
        if type(context_regions) is not list or not 1 <= len(context_regions) <= 32:
            raise ValueError("context_regions_missing_or_invalid")
        protected = [("target", target)]
        for region in context_regions:
            if (type(region) is not dict or set(region) != {"kind", "bbox"}
                    or region.get("kind") != "anchor"):
                raise ValueError("untrusted_context_region")
            protected.append(("anchor", _bbox(region["bbox"], size)))
        result["protected_regions"] = [{"kind": kind, "bbox": _box_dict(box)} for kind, box in protected]
        if original["window_identity"] != observed["window_identity"]:
            return {**result, "status": "changed", "reason": "window_identity_changed"}
        if current_size != size or current_rect != rect:
            return {**result, "status": "changed", "reason": "viewport_or_window_geometry_changed"}
        if any(_overlap(mask, box) for mask in current_masks for _, box in protected):
            return {**result, "status": "changed", "reason": "protected_region_occluded"}
        if any(_overlap(mask, box) for mask in original_masks for _, box in protected):
            return {**result, "reason": "original_protected_region_occluded"}
        # 四个通道均逐像素比较，不能漏掉仅 alpha 改变的遮挡或微小文字变化。
        channels = ImageChops.difference(original_pixels, current_pixels).split()
        changes = channels[0]
        for channel in channels[1:]:
            changes = ImageChops.lighter(changes, channel)
        for kind, box in protected:
            if changes.crop(box).getbbox() is not None:
                return {**result, "status": "changed", "reason": kind + "_pixels_changed",
                    "changed_region_bbox": _box_dict(changes.getbbox())}
        outside_occlusion_changed = original_masks != current_masks
        if outside_occlusion_changed:
            # 比较实际遮挡覆盖，不能因联合外接矩形穿过目标就认定目标被遮挡。
            coverage = []
            for masks in (original_masks, current_masks):
                mask_pixels = Image.new("L", size, 0)
                mask_drawing = ImageDraw.Draw(mask_pixels)
                for box in masks:
                    mask_drawing.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=255)
                coverage.append(mask_pixels)
            occlusion_changes = ImageChops.difference(*coverage)
            if occlusion_changes.getbbox() is None:
                occlusion_changes = ImageChops.lighter(*coverage)
            changes = ImageChops.lighter(changes, occlusion_changes)
        uncovered = changes.copy()
        drawing = ImageDraw.Draw(uncovered)
        for _, box in protected:
            drawing.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=0)
        remaining = uncovered.getbbox()
        if remaining is not None:
            reason = "unexplained_outside_occlusion_change" if outside_occlusion_changed else "unexplained_outside_change"
            return {**result, "reason": reason, "uncovered_change_bbox": _box_dict(remaining)}
        return {**result, "status": "valid", "reason": "protected_regions_unchanged"}
    except (ValueError, TypeError, KeyError, OSError) as error:
        return {**result, "reason": "evidence_invalid", "error_type": type(error).__name__}
