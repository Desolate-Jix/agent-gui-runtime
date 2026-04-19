from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from app.vision_protocol.schemas import BBox, VisionAction, VisionResponse, VisionState, VisionTarget, VisionValidator


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception as exc:
            logger.warning("Failed to parse JSON string for vision response: {}", exc)
    return {}


def _parse_bbox(raw: Any, *, field_name: str) -> BBox | None:
    data = _as_dict(raw)
    try:
        x = int(data.get("x"))
        y = int(data.get("y"))
        w = int(data.get("w", data.get("width")))
        h = int(data.get("h", data.get("height")))
    except Exception:
        logger.warning("Invalid or missing bbox for {}: {}", field_name, raw)
        return None
    if w <= 0 or h <= 0:
        logger.warning("Non-positive bbox for {}: {}", field_name, raw)
        return None
    return BBox(x=x, y=y, w=w, h=h)


def _clamp_confidence(value: Any, *, action_id: str) -> float:
    try:
        confidence = float(value)
    except Exception:
        logger.warning("Invalid confidence for action {}: {}", action_id, value)
        return 0.0
    if confidence < 0.0 or confidence > 1.0:
        logger.warning("Confidence out of range for action {}: {}", action_id, confidence)
        confidence = min(1.0, max(0.0, confidence))
    return confidence


def parse_vision_response(raw_json: dict | str) -> VisionResponse:
    raw = _as_dict(raw_json)
    state_raw = _as_dict(raw.get("state"))
    state = VisionState(
        state_id=str(state_raw.get("state_id") or "unknown"),
        screen_summary=str(state_raw.get("screen_summary") or ""),
    )

    actions: list[VisionAction] = []
    for index, item in enumerate(raw.get("actions") or []):
        action_raw = _as_dict(item)
        action_id = str(action_raw.get("action_id") or f"action_{index}")
        target_raw = _as_dict(action_raw.get("target"))
        validator_raw = _as_dict(action_raw.get("validator"))

        target_bbox = _parse_bbox(target_raw.get("bbox"), field_name=f"actions[{index}].target.bbox")
        validator_roi = _parse_bbox(validator_raw.get("roi"), field_name=f"actions[{index}].validator.roi")
        if target_bbox is None or validator_roi is None:
            logger.warning("Skipping action {} due to invalid bbox/roi", action_id)
            continue

        target = VisionTarget(
            target_id=str(target_raw.get("target_id") or f"target_{index}"),
            label=str(target_raw.get("label") or target_raw.get("target_id") or f"target_{index}"),
            bbox=target_bbox,
            point_strategy=str(target_raw.get("point_strategy") or "grid"),
            priority=int(target_raw.get("priority") or 0),
        )
        validator = VisionValidator(
            type=str(validator_raw.get("type") or "roi_change"),
            observer_id=str(validator_raw.get("observer_id") or f"observer_{index}"),
            roi=validator_roi,
            expected_change=str(validator_raw.get("expected_change") or "change"),
            threshold=float(validator_raw.get("threshold") or 0.1),
        )
        actions.append(
            VisionAction(
                action_id=action_id,
                action_type=str(action_raw.get("action_type") or "click"),
                target=target,
                validator=validator,
                expected_effect=str(action_raw.get("expected_effect") or ""),
                confidence=_clamp_confidence(action_raw.get("confidence"), action_id=action_id),
            )
        )

    response = VisionResponse(
        state=state,
        actions=actions,
        observers=list(raw.get("observers") or []),
        meta=dict(raw.get("meta") or {}),
    )
    logger.info("Parsed vision response: state_id={}, action_count={}", response.state.state_id, len(response.actions))
    return response
