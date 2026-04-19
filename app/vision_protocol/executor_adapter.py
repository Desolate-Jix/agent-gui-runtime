from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

from app.core.window_manager import window_manager
from app.schemas.validator_profile import ValidatorProfile
from app.vision_protocol.parser import parse_vision_response
from app.vision_protocol.schemas import BBox, VisionAction, VisionResponse


MIN_BOX_SIZE = 20


def _window_rect(bound: Any) -> dict[str, int]:
    return {
        "left": int(bound.rect.left),
        "top": int(bound.rect.top),
        "width": int(bound.rect.right - bound.rect.left),
        "height": int(bound.rect.bottom - bound.rect.top),
    }


def _bbox_to_zone(bbox: BBox) -> dict[str, int]:
    return {"x": int(bbox.x), "y": int(bbox.y), "width": int(bbox.w), "height": int(bbox.h), "source": "vision_protocol"}


def _make_points(bbox: BBox, point_strategy: str) -> list[dict[str, Any]]:
    zone = _bbox_to_zone(bbox)
    left = zone["x"]
    top = zone["y"]
    right = zone["x"] + zone["width"]
    bottom = zone["y"] + zone["height"]
    cx = int(round((left + right) / 2))
    cy = int(round((top + bottom) / 2))

    if point_strategy == "center":
        return [{"x": cx, "y": cy, "label": "center"}]

    if point_strategy == "grid":
        xs = [int(round(left + zone["width"] * ratio)) for ratio in (0.2, 0.5, 0.8)]
        ys = [int(round(top + zone["height"] * ratio)) for ratio in (0.2, 0.5, 0.8)]
        labels = ["top_left", "top_center", "top_right", "center_left", "center", "center_right", "bottom_left", "bottom_center", "bottom_right"]
        points: list[dict[str, Any]] = []
        idx = 0
        for y in ys:
            for x in xs:
                points.append({"x": x, "y": y, "label": labels[idx]})
                idx += 1
        return points

    return [{"x": cx, "y": cy, "label": "center_fallback"}]


def _validator_callable(vision_action: VisionAction, verification_sink: dict[str, Any]):
    def _validator(before_numeric_texts: list[str], after_numeric_texts: list[str]) -> dict[str, Any]:
        _ = before_numeric_texts, after_numeric_texts
        verification = verification_sink.get("verification") or {}
        diff = verification.get("diff") or {}
        roi_diff_score = float(diff.get("count") or 0.0)
        changed = bool(diff.get("changed"))
        threshold = float(vision_action.validator.threshold)
        strict_success = False
        weak_success = False
        if vision_action.validator.type == "roi_change":
            strict_success = changed and roi_diff_score >= threshold
            weak_success = changed
        else:
            strict_success = changed and roi_diff_score >= threshold
            weak_success = changed
        result = {
            "observer_id": vision_action.validator.observer_id,
            "validator_type": vision_action.validator.type,
            "expected_change": vision_action.validator.expected_change,
            "roi_diff_score": roi_diff_score,
            "strict_success": strict_success,
            "weak_success": weak_success,
            "threshold": threshold,
        }
        logger.info("vision validator result: {}", result)
        return result

    return _validator


def execute_vision_action(vision_action: VisionAction) -> dict[str, Any]:
    bound = window_manager.get_bound_window()
    if bound is None:
        return {"success": False, "status": "skip", "reason": "no_bound_window"}

    rect = _window_rect(bound)
    bbox = vision_action.target.bbox
    roi = vision_action.validator.roi

    if vision_action.confidence < 0.5:
        return {"success": False, "status": "skip", "reason": "low_confidence", "confidence": vision_action.confidence}
    if bbox.w < MIN_BOX_SIZE or bbox.h < MIN_BOX_SIZE:
        return {"success": False, "status": "skip", "reason": "bbox_too_small", "bbox": bbox.to_dict()}
    if roi.w <= 0 or roi.h <= 0:
        return {"success": False, "status": "skip", "reason": "invalid_roi", "roi": roi.to_dict()}
    if bbox.x < 0 or bbox.y < 0 or bbox.x + bbox.w > rect["width"] or bbox.y + bbox.h > rect["height"]:
        return {"success": False, "status": "skip", "reason": "bbox_out_of_bounds", "bbox": bbox.to_dict(), "window_rect": rect}
    if roi.x < 0 or roi.y < 0 or roi.x + roi.w > rect["width"] or roi.y + roi.h > rect["height"]:
        return {"success": False, "status": "skip", "reason": "roi_out_of_bounds", "roi": roi.to_dict(), "window_rect": rect}

    generated_points = _make_points(bbox, vision_action.target.point_strategy)
    logger.info("selected action_id={}, bbox={}, generated_points={}", vision_action.action_id, bbox.to_dict(), generated_points)

    verification_sink: dict[str, Any] = {}

    def panel_locator(_: Any) -> dict[str, Any]:
        return {"x": 0, "y": 0, "width": rect["width"], "height": rect["height"], "source": "window_full"}

    def zone_resolver(_: dict[str, Any]) -> dict[str, Any]:
        return _bbox_to_zone(bbox)

    def point_strategy(_: dict[str, Any], preferred_norm_point: Optional[dict[str, float]] = None) -> list[dict[str, Any]]:
        _ = preferred_norm_point
        return generated_points

    validator_profile = ValidatorProfile(
        validator_profile_id=f"vision_{vision_action.action_id}",
        name=f"Vision Validator {vision_action.action_id}",
        ocr_roi=None,
        roi_diff_threshold=float(vision_action.validator.threshold),
        strict_rule={"type": vision_action.validator.type, "observer_id": vision_action.validator.observer_id},
        weak_rule={"type": vision_action.validator.type},
        version=1,
    )

    from app.api.action import _run_region_click

    result = _run_region_click(
        case_name=vision_action.action_id,
        bound=bound,
        panel_locator=panel_locator,
        zone_resolver=zone_resolver,
        point_strategy=point_strategy,
        validator=_validator_callable(vision_action, verification_sink),
        validator_profile=validator_profile,
        max_retries=1,
    )
    if result.get("retries"):
        verification_sink["verification"] = ((result.get("retries") or [{}])[-1]).get("verification") or result.get("verification") or {}
        validator_result = _validator_callable(vision_action, verification_sink)([], [])
    else:
        validator_result = {}
    result["vision_action_id"] = vision_action.action_id
    result["generated_points"] = generated_points
    result["validator_result"] = validator_result
    logger.info("vision execution result: action_id={}, success={}, validator_result={}", vision_action.action_id, result.get("success"), validator_result)
    return result


def run_vision_response(raw_json: dict | str) -> dict[str, Any]:
    response: VisionResponse = parse_vision_response(raw_json)
    if not response.actions:
        return {"success": False, "status": "skip", "reason": "no_actions", "state": response.state.to_dict()}
    selected = sorted(response.actions, key=lambda item: (-int(item.target.priority), -float(item.confidence), item.action_id))[0]
    logger.info("run_vision_response selected action_id={}", selected.action_id)
    result = execute_vision_action(selected)
    return {
        "success": bool(result.get("success")),
        "status": result.get("status", "success" if result.get("success") else "fail"),
        "selected_action_id": selected.action_id,
        "state": response.state.to_dict(),
        "result": result,
    }
