from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter


CONTRACT_VERSION = "ui_diff_verification_v1"


def build_ui_diff_verification(
    before_image: str | Path | None,
    after_image: str | Path | None,
    *,
    expected_change: str | None = None,
    target_bbox: dict[str, Any] | None = None,
    threshold: int = 28,
    min_changed_ratio: float = 0.00002,
) -> dict[str, Any]:
    """Build a lightweight screenshot-diff verifier without invoking a model."""

    result: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "expected_change": expected_change or "unknown",
        "before_screenshot": str(before_image) if before_image else None,
        "after_screenshot": str(after_image) if after_image else None,
        "diff_bboxes": [],
        "changed_regions": [],
        "verification_status": "needs_review",
        "evidence": [],
        "safety": {
            "submit_clicked": False,
            "unexpected_navigation": False,
        },
    }
    if not before_image or not after_image:
        result["verification_status"] = "fail"
        result["failure_reason"] = "missing_before_or_after_image"
        return result

    try:
        before = Image.open(before_image).convert("RGB")
        after = Image.open(after_image).convert("RGB")
    except OSError as exc:
        result["verification_status"] = "fail"
        result["failure_reason"] = f"image_open_failed: {exc}"
        return result

    if before.size != after.size:
        after = after.resize(before.size)
        result["evidence"].append({"type": "resize_after_to_before", "size": before.size})

    diff = ImageChops.difference(before, after).convert("L")
    mask = diff.point(lambda value: 255 if value >= threshold else 0)
    mask = mask.filter(ImageFilter.MaxFilter(7))
    union_bbox = mask.getbbox()
    total_pixels = max(1, before.size[0] * before.size[1])
    changed_pixels = _count_mask_pixels(mask)
    changed_ratio = changed_pixels / total_pixels

    result["changed_pixel_ratio"] = round(changed_ratio, 8)
    result["threshold"] = threshold
    result["image_size"] = {"width": before.size[0], "height": before.size[1]}

    if not union_bbox or changed_ratio < min_changed_ratio:
        result["verification_status"] = "fail"
        result["failure_reason"] = "no_meaningful_visual_change"
        return result

    bbox = _tuple_to_bbox(union_bbox)
    result["diff_bboxes"] = [bbox]
    result["changed_regions"] = [
        {
            "bbox": bbox,
            "area": bbox["w"] * bbox["h"],
            "source": "thresholded_absdiff_union",
        }
    ]

    target = _bbox(target_bbox)
    if target:
        result["target_bbox"] = target
        result["target_intersects_diff"] = _intersects(target, bbox)

    status = "pass"
    evidence: list[dict[str, Any]] = []
    if expected_change == "field_value_changed":
        if target and not _intersects(target, bbox):
            status = "needs_review"
            evidence.append({"type": "field_target_not_in_diff", "reason": "diff did not intersect expected field bbox"})
        else:
            evidence.append({"type": "field_target_changed", "reason": "diff intersects expected field bbox" if target else "visual diff exists"})
    elif expected_change in {"step_changed", "detail_opened", "scroll_progress"}:
        evidence.append({"type": expected_change, "reason": "meaningful visual diff detected"})
    else:
        evidence.append({"type": "visual_diff_detected", "reason": "meaningful visual diff detected"})

    result["verification_status"] = status
    result["evidence"].extend(evidence)
    return result


def _count_mask_pixels(mask: Image.Image) -> int:
    histogram = mask.histogram()
    if len(histogram) < 256:
        return 0
    return sum(histogram[1:])


def _tuple_to_bbox(value: tuple[int, int, int, int]) -> dict[str, int]:
    left, top, right, bottom = value
    return {"x": left, "y": top, "w": max(0, right - left), "h": max(0, bottom - top)}


def _bbox(value: dict[str, Any] | None) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(value.get("x") or 0)
        y = int(value.get("y") or 0)
        w = int(value.get("w") if value.get("w") is not None else value.get("width"))
        h = int(value.get("h") if value.get("h") is not None else value.get("height"))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _intersects(a: dict[str, int], b: dict[str, int]) -> bool:
    return not (
        a["x"] + a["w"] <= b["x"]
        or b["x"] + b["w"] <= a["x"]
        or a["y"] + a["h"] <= b["y"]
        or b["y"] + b["h"] <= a["y"]
    )
