from __future__ import annotations

import copy
import re
from difflib import SequenceMatcher
from typing import Any

from app.vision.schemas import ImageSize
from modules.ocr.contracts import OCRResult


def build_ocr_anchor_payload(
    ocr: OCRResult,
    *,
    image_size: ImageSize,
    goal: str | None = None,
    max_anchors: int | None = None,
    min_score: float = 0.0,
) -> dict[str, Any]:
    anchors: list[dict[str, Any]] = []
    normalized_goal = _normalize_text(goal or "")
    for index, match in enumerate(ocr.matches, start=1):
        text = str(match.text or "").strip()
        confidence = _clamp01(match.score)
        if not text or confidence < min_score:
            continue
        bbox = {
            "x": int(match.bbox.x),
            "y": int(match.bbox.y),
            "w": int(match.bbox.width),
            "h": int(match.bbox.height),
        }
        goal_similarity = _text_similarity(normalized_goal, _normalize_text(text)) if normalized_goal else 0.0
        anchors.append(
            {
                "anchor_id": f"ocr_anchor_{index}",
                "text": text,
                "bbox": bbox,
                "center": _center(bbox),
                "confidence": round(confidence, 4),
                "goal_similarity": round(goal_similarity, 4),
            }
        )

    anchors.sort(key=lambda item: (item["goal_similarity"], item["confidence"], len(item["text"])), reverse=True)
    selected = anchors if max_anchors is None or int(max_anchors) <= 0 else anchors[: int(max_anchors)]
    return {
        "contract_version": "ocr_anchors_v1",
        "coordinate_space": "original_image",
        "image_size": image_size.to_dict(),
        "source_engine": str((ocr.metadata or {}).get("engine") or "ocr"),
        "total_detected_count": len(anchors),
        "anchor_count": len(selected),
        "anchors": selected,
    }


def scale_ocr_anchor_payload(
    payload: dict[str, Any] | None,
    *,
    from_size: ImageSize,
    to_size: ImageSize,
    coordinate_space: str = "inference_image",
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    scaled = copy.deepcopy(payload)
    scaled["coordinate_space"] = coordinate_space
    scaled["image_size"] = to_size.to_dict()
    scale_x = float(to_size.width) / float(max(1, from_size.width))
    scale_y = float(to_size.height) / float(max(1, from_size.height))
    for anchor in scaled.get("anchors") or []:
        if not isinstance(anchor, dict) or not isinstance(anchor.get("bbox"), dict):
            continue
        bbox = anchor["bbox"]
        new_bbox = {
            "x": _scale_int(bbox.get("x"), scale_x),
            "y": _scale_int(bbox.get("y"), scale_y),
            "w": max(1, _scale_int(bbox.get("w"), scale_x)),
            "h": max(1, _scale_int(bbox.get("h"), scale_y)),
        }
        new_bbox["x"] = max(0, min(int(to_size.width), new_bbox["x"]))
        new_bbox["y"] = max(0, min(int(to_size.height), new_bbox["y"]))
        if new_bbox["x"] + new_bbox["w"] > to_size.width:
            new_bbox["w"] = max(1, int(to_size.width) - new_bbox["x"])
        if new_bbox["y"] + new_bbox["h"] > to_size.height:
            new_bbox["h"] = max(1, int(to_size.height) - new_bbox["y"])
        anchor["bbox"] = new_bbox
        anchor["center"] = _center(new_bbox)
    return scaled


def _center(bbox: dict[str, int]) -> dict[str, int]:
    return {
        "x": int(round(int(bbox["x"]) + int(bbox["w"]) / 2.0)),
        "y": int(round(int(bbox["y"]) + int(bbox["h"]) / 2.0)),
    }


def _scale_int(value: Any, scale: float) -> int:
    try:
        return int(round(float(value) * scale))
    except Exception:
        return 0


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except Exception:
        return 0.0


def _normalize_text(value: str) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", normalized)
    return " ".join(normalized.split())


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.9
    return SequenceMatcher(None, left, right).ratio()
