from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, UnidentifiedImageError

from app.agent.native_identity import validate_native_identity_fact


SCROLL_SPATIAL_CONTRACT = "scroll_spatial_evidence_v1"
SCROLL_CAPTURE_CONTRACT = "scroll_capture_snapshot_v1"
PIXEL_DELTA_THRESHOLD = 25
SIGNIFICANT_PIXEL_COUNT = 80


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _valid_size(value: object) -> bool:
    return isinstance(value, dict) and all(_positive_int(value.get(key)) for key in ("width", "height"))


def _valid_bbox(value: object, size: dict[str, int]) -> bool:
    return (
        isinstance(value, dict) and _valid_size(value)
        and all(type(value.get(key)) is int and value[key] >= 0 for key in ("x", "y"))
        and value["x"] + value["width"] <= size["width"]
        and value["y"] + value["height"] <= size["height"]
    )


def measure_scroll_spatial_evidence(
    *, before: object, after: object, target_bbox: object, target_container_id: str | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "contract_version": SCROLL_SPATIAL_CONTRACT, "available": False, "status": "unknown",
        "target_container_id": target_container_id, "target_bbox": target_bbox,
        "target_changed": None, "non_target_changed": None, "non_target_stable": None,
        "wrong_scope_detected": None, "scroll_movement_verified": None,
        "direction_verified": None, "boundary_reached": None, "should_retry": False,
        "policy": {"pixel_delta_threshold": PIXEL_DELTA_THRESHOLD, "significant_pixel_count": SIGNIFICANT_PIXEL_COUNT, "ignored_regions": []},
    }

    def unknown(reason: str) -> dict[str, Any]:
        return {**result, "reason": reason}

    frames = (before, after)
    if not all(isinstance(frame, dict) for frame in frames):
        return unknown("capture_missing")
    identities = []
    for frame in frames:
        if frame.get("contract_version") != SCROLL_CAPTURE_CONTRACT or frame.get("captured") is not True or frame.get("capture_status") != "observed":
            return unknown("capture_unavailable")
        if not all(isinstance(frame.get(key), str) and frame[key].strip() for key in ("capture_id", "capture_clock_id")):
            return unknown("capture_id_missing")
        if not all(_positive_int(frame.get(key)) for key in ("capture_started_ns", "captured_at_ns")) or frame["captured_at_ns"] < frame["capture_started_ns"]:
            return unknown("capture_interval_invalid")
        if frame.get("roi") is not None:
            return unknown("full_window_capture_required")
        if not _valid_size(frame.get("viewport_size")):
            return unknown("viewport_invalid")
        identity = validate_native_identity_fact(frame.get("native_identity"), target_window_handle=frame.get("window_handle"))
        if identity is None:
            return unknown("native_identity_invalid")
        identities.append(identity)
    if before["capture_id"] == after["capture_id"]:
        return unknown("capture_reused")
    if before["capture_clock_id"] != after["capture_clock_id"]:
        return unknown("capture_clock_mismatch")
    if after["capture_started_ns"] <= before["captured_at_ns"]:
        return unknown("capture_order_invalid")
    if identities[0] != identities[1]:
        return unknown("native_identity_mismatch")
    size = before["viewport_size"]
    if size != after["viewport_size"]:
        return unknown("viewport_mismatch")
    for frame in frames:
        rect = frame.get("window_rect")
        if not isinstance(rect, dict) or not all(type(rect.get(key)) is int for key in ("x", "y")) or any(rect.get(key) != size[key] for key in ("width", "height")):
            return unknown("window_geometry_invalid")
    if before["window_rect"] != after["window_rect"]:
        return unknown("window_geometry_mismatch")
    if not _valid_bbox(target_bbox, size):
        return unknown("target_bbox_invalid")

    images = []
    for frame in frames:
        try:
            path = frame.get("image_path")
            if not isinstance(path, str) or not path:
                return unknown("image_path_missing")
            raw = Path(path).read_bytes()
            if sha256(raw).hexdigest() != frame.get("image_sha256"):
                return unknown("image_hash_mismatch")
            with Image.open(BytesIO(raw)) as image:
                if image.format != "PNG":
                    return unknown("png_capture_required")
                if image.size != (size["width"], size["height"]):
                    return unknown("image_dimensions_mismatch")
                images.append(image.convert("RGB"))
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            return {**unknown("image_read_failed"), "error_type": type(error).__name__}

    bands = ImageChops.difference(images[0], images[1]).split()
    delta = ImageChops.lighter(ImageChops.lighter(bands[0], bands[1]), bands[2])
    mask = delta.point(lambda value: 255 if value > PIXEL_DELTA_THRESHOLD else 0)
    x, y, width, height = (target_bbox[key] for key in ("x", "y", "width", "height"))
    target_pixels = width * height
    target_count = mask.crop((x, y, x + width, y + height)).histogram()[255]
    outside_pixels = size["width"] * size["height"] - target_pixels
    outside_count = mask.histogram()[255] - target_count

    def metrics(count: int, pixels: int) -> dict[str, Any]:
        return {"pixel_count": pixels, "changed_pixel_count": count, "changed_ratio": count / pixels if pixels else 0.0}

    # 微小变化无法归因为噪声或滚动，不能把它静默视为稳定。
    def changed(count: int) -> bool | None:
        return False if count == 0 else (True if count >= SIGNIFICANT_PIXEL_COUNT else None)

    target_changed, outside_changed = changed(target_count), changed(outside_count)
    status = "unknown"
    if outside_changed is True:
        status = "non_target_visual_change"
    elif outside_changed is False and target_changed is not None:
        status = "target_visual_change" if target_changed else "no_visual_change"
    result.update({
        "available": True, "status": status, "reason": status,
        "target_changed": target_changed, "non_target_changed": outside_changed,
        "non_target_stable": None if outside_changed is None else not outside_changed,
        "wrong_scope_detected": outside_changed,
        "non_target_change_cause": "unknown" if outside_changed is not False else None,
        "target_metrics": metrics(target_count, target_pixels),
        "non_target_metrics": metrics(outside_count, outside_pixels),
        "lineage": {
            label: {key: frame[key] for key in ("capture_id", "capture_clock_id", "capture_started_ns", "captured_at_ns", "image_path", "image_sha256", "viewport_size", "window_rect", "native_identity")}
            for label, frame in zip(("before", "after"), frames)
        },
    })
    return result
