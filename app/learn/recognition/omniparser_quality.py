from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
from typing import Any


DEFAULT_MINIMUM_CAPTURE_SIDE_PX = 10
_DUPLICATE_IOU_THRESHOLD = 0.95


def filter_omniparser_candidates(
    items: list[dict[str, Any]],
    *,
    image_size: dict[str, Any],
    minimum_capture_side_px: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """删除不可审阅的微小框，并只合并语义等价的近重复框。"""

    width = _positive_int(image_size.get("width"))
    height = _positive_int(image_size.get("height"))
    if not isinstance(items, list):
        raise ValueError("omniparser_candidate_invalid")
    if minimum_capture_side_px is None:
        minimum_capture_side_px = min(
            DEFAULT_MINIMUM_CAPTURE_SIDE_PX,
            max(1, round(min(width, height) * 0.0125)),
        )
    if not isinstance(minimum_capture_side_px, int) or minimum_capture_side_px < 1:
        raise ValueError("omniparser_candidate_invalid")

    selected: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    tiny_count = 0
    duplicate_count = 0
    for input_index, raw_item in enumerate(items):
        item = _validated_item(raw_item)
        bbox = item["bbox"]
        if min((bbox[2] - bbox[0]) * width, (bbox[3] - bbox[1]) * height) < minimum_capture_side_px:
            tiny_count += 1
            removed.append(_removed_record(item, input_index=input_index, reason="below_minimum_capture_side"))
            continue

        duplicate_index = _equivalent_duplicate_index(item, selected)
        if duplicate_index is None:
            selected.append(item)
            continue

        duplicate_count += 1
        incumbent = selected[duplicate_index]
        if _fingerprint(item) < _fingerprint(incumbent):
            removed.append(_removed_record(incumbent, input_index=input_index, reason="equivalent_duplicate"))
            selected[duplicate_index] = item
        else:
            removed.append(_removed_record(item, input_index=input_index, reason="equivalent_duplicate"))

    return selected, {
        "input_count": len(items),
        "output_count": len(selected),
        "removed_tiny_count": tiny_count,
        "removed_duplicate_count": duplicate_count,
        "minimum_capture_side_px": minimum_capture_side_px,
        "removed_candidates": removed,
    }


def _validated_item(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("omniparser_candidate_invalid")
    bbox = value.get("bbox")
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or not all(isinstance(edge, (int, float)) and not isinstance(edge, bool) and math.isfinite(float(edge)) for edge in bbox)
    ):
        raise ValueError("omniparser_candidate_invalid")
    normalized = [float(edge) for edge in bbox]
    if not (0 <= normalized[0] < normalized[2] <= 1 and 0 <= normalized[1] < normalized[3] <= 1):
        raise ValueError("omniparser_candidate_invalid")
    item = deepcopy(value)
    item["bbox"] = normalized
    return item


def _positive_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("omniparser_candidate_invalid")
    return value


def _equivalent_duplicate_index(item: dict[str, Any], selected: list[dict[str, Any]]) -> int | None:
    key = _semantic_key(item)
    for index, candidate in enumerate(selected):
        if _semantic_key(candidate) == key and _iou(item["bbox"], candidate["bbox"]) >= _DUPLICATE_IOU_THRESHOLD:
            return index
    return None


def _semantic_key(item: dict[str, Any]) -> tuple[str, str, str, bool]:
    return (
        str(item.get("type") or "element").strip().casefold(),
        str(item.get("content") or "").strip().casefold(),
        str(item.get("source") or "official_omniparser").strip().casefold(),
        bool(item.get("interactivity")),
    )


def _iou(first: list[float], second: list[float]) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0


def _fingerprint(item: dict[str, Any]) -> str:
    payload = {
        "bbox": item["bbox"],
        "content": str(item.get("content") or "").strip(),
        "interactivity": bool(item.get("interactivity")),
        "source": str(item.get("source") or "official_omniparser"),
        "type": str(item.get("type") or "element"),
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _removed_record(item: dict[str, Any], *, input_index: int, reason: str) -> dict[str, Any]:
    return {
        "input_index": input_index,
        "candidate_fingerprint": _fingerprint(item),
        "reason": reason,
    }
