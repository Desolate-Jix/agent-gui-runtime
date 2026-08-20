from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Optional

from app.core.ocr_service import ocr_service


def should_verify_mouse_tester_semantics(*, request: Any, plan: dict[str, Any]) -> bool:
    values = [
        getattr(request, "app_name", "") or "",
        getattr(request, "state_hint", "") or "",
        plan.get("goal") or "",
        (plan.get("parse_result") or {}).get("vision_regions", {}).get("screen_summary") or "",
    ]
    normalized = " ".join(str(value).casefold() for value in values)
    return "mousetester" in normalized or "mouse tester" in normalized or "鼠标" in normalized


def verify_mouse_tester_post_click_semantics(
    *,
    request: Any,
    plan: dict[str, Any],
    generic_verification: dict[str, Any],
) -> dict[str, Any]:
    before_path = (generic_verification.get("before") or {}).get("image_path")
    after_path = (generic_verification.get("after") or {}).get("image_path")
    recommended = plan.get("recommended_target") or {}
    target_bbox = target_bbox_from_recommended(recommended)
    if not before_path or not after_path or target_bbox is None:
        return {
            "applicable": True,
            "verified": False,
            "reason": "missing_before_after_or_target_bbox",
            "before_path": before_path,
            "after_path": after_path,
            "target_bbox": target_bbox,
        }

    image_size = image_size_from_plan(plan)
    verification_bbox = expand_bbox(target_bbox, pad_x=90, pad_y=55, image_size=image_size)
    before_texts = ocr_texts_in_bbox(str(before_path), verification_bbox)
    after_texts = ocr_texts_in_bbox(str(after_path), verification_bbox)
    expected_values = [
        getattr(request, "goal", ""),
        str(recommended.get("label") or ""),
        str(recommended.get("text") or ""),
    ]
    before_target_present = texts_contain_expected(before_texts, expected_values)
    after_target_present = texts_contain_expected(after_texts, expected_values)
    localized_text_changed = text_signature(before_texts) != text_signature(after_texts)
    diff_overlaps_target = diff_overlaps_bbox(generic_verification.get("diff") or {}, verification_bbox)
    target_text_replaced = bool(before_target_present and not after_target_present)
    verified = bool(diff_overlaps_target and localized_text_changed and (target_text_replaced or before_target_present))

    return {
        "applicable": True,
        "verified": verified,
        "profile": "mousetester_target_text_change_v1",
        "target_bbox": target_bbox,
        "verification_bbox": verification_bbox,
        "before_path": before_path,
        "after_path": after_path,
        "before_texts": before_texts,
        "after_texts": after_texts,
        "before_target_present": before_target_present,
        "after_target_present": after_target_present,
        "target_text_replaced": target_text_replaced,
        "localized_text_changed": localized_text_changed,
        "diff_overlaps_target": diff_overlaps_target,
        "reasons": semantic_verification_reasons(
            before_target_present=before_target_present,
            after_target_present=after_target_present,
            target_text_replaced=target_text_replaced,
            localized_text_changed=localized_text_changed,
            diff_overlaps_target=diff_overlaps_target,
        ),
    }


def target_bbox_from_recommended(recommended: dict[str, Any]) -> Optional[dict[str, int]]:
    source = recommended.get("refined_bbox") or (recommended.get("element") or {}).get("bbox")
    if not source:
        return None
    return {
        "x": int(source.get("x", 0)),
        "y": int(source.get("y", 0)),
        "width": int(source.get("width", source.get("w", 0))),
        "height": int(source.get("height", source.get("h", 0))),
    }


def image_size_from_plan(plan: dict[str, Any]) -> Optional[dict[str, int]]:
    image_size = (((plan.get("parse_result") or {}).get("vision_regions") or {}).get("image_size") or {})
    width = image_size.get("width")
    height = image_size.get("height")
    if width and height:
        return {"width": int(width), "height": int(height)}
    return None


def expand_bbox(
    bbox: dict[str, int],
    *,
    pad_x: int,
    pad_y: int,
    image_size: Optional[dict[str, int]] = None,
) -> dict[str, int]:
    x1 = int(bbox["x"]) - int(pad_x)
    y1 = int(bbox["y"]) - int(pad_y)
    x2 = int(bbox["x"]) + int(bbox["width"]) + int(pad_x)
    y2 = int(bbox["y"]) + int(bbox["height"]) + int(pad_y)
    x1 = max(0, x1)
    y1 = max(0, y1)
    if image_size:
        x2 = min(int(image_size["width"]), x2)
        y2 = min(int(image_size["height"]), y2)
    return {"x": x1, "y": y1, "width": max(1, x2 - x1), "height": max(1, y2 - y1)}


def ocr_texts_in_bbox(image_path: str, bbox: dict[str, int]) -> list[dict[str, Any]]:
    result = ocr_service.scan_image(image_path)
    texts: list[dict[str, Any]] = []
    for match in result.matches:
        match_bbox = match.bbox.to_dict()
        center = {
            "x": int(match_bbox["x"] + match_bbox["width"] / 2),
            "y": int(match_bbox["y"] + match_bbox["height"] / 2),
        }
        if point_in_rect(center, bbox):
            texts.append({"text": match.text, "score": float(match.score), "bbox": match_bbox})
    texts.sort(key=lambda item: (item["bbox"]["y"], item["bbox"]["x"]))
    return texts


def texts_contain_expected(texts: list[dict[str, Any]], expected_values: list[str]) -> bool:
    expected = [normalize_semantic_text(value) for value in expected_values if normalize_semantic_text(value)]
    for item in texts:
        normalized_text = normalize_semantic_text(str(item.get("text") or ""))
        if any(semantic_text_similarity(normalized_text, value) >= 0.75 for value in expected):
            return True
    return False


def text_signature(texts: list[dict[str, Any]]) -> list[str]:
    return [normalize_semantic_text(str(item.get("text") or "")) for item in texts]


def diff_overlaps_bbox(diff: dict[str, Any], bbox: dict[str, int]) -> bool:
    for region in diff.get("regions") or []:
        region_bbox = {
            "x": int(region.get("x", 0)),
            "y": int(region.get("y", 0)),
            "width": int(region.get("width", region.get("w", 0))),
            "height": int(region.get("height", region.get("h", 0))),
        }
        if rects_intersect(region_bbox, bbox):
            return True
    return False


def semantic_verification_reasons(
    *,
    before_target_present: bool,
    after_target_present: bool,
    target_text_replaced: bool,
    localized_text_changed: bool,
    diff_overlaps_target: bool,
) -> list[str]:
    reasons: list[str] = []
    reasons.append("before_target_present" if before_target_present else "before_target_missing")
    reasons.append("after_target_still_present" if after_target_present else "after_target_absent")
    if target_text_replaced:
        reasons.append("target_text_replaced")
    if localized_text_changed:
        reasons.append("localized_text_changed")
    if diff_overlaps_target:
        reasons.append("diff_overlaps_target")
    else:
        reasons.append("diff_did_not_overlap_target")
    return reasons


def point_in_rect(point: dict[str, int], rect: dict[str, int]) -> bool:
    return (
        int(rect["x"]) <= int(point["x"]) <= int(rect["x"]) + int(rect["width"])
        and int(rect["y"]) <= int(point["y"]) <= int(rect["y"]) + int(rect["height"])
    )


def rects_intersect(left: dict[str, int], right: dict[str, int]) -> bool:
    left_x2 = int(left["x"]) + int(left["width"])
    left_y2 = int(left["y"]) + int(left["height"])
    right_x2 = int(right["x"]) + int(right["width"])
    right_y2 = int(right["y"]) + int(right["height"])
    return not (
        left_x2 < int(right["x"])
        or right_x2 < int(left["x"])
        or left_y2 < int(right["y"])
        or right_y2 < int(left["y"])
    )


def semantic_text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if min(len(left), len(right)) >= 3 and (left in right or right in left):
        return 0.9
    return SequenceMatcher(None, left, right).ratio()


def normalize_semantic_text(value: str) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", normalized)
    return " ".join(normalized.split())
