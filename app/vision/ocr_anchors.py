from __future__ import annotations

import copy
import re
from difflib import SequenceMatcher
from typing import Any

from app.vision.schemas import ImageSize
from modules.ocr.contracts import OCRResult

DEFAULT_PROMPT_ANCHOR_LIMIT = 48
DEFAULT_PROMPT_TEXT_MATCH_THRESHOLD = 0.55
DEFAULT_PROMPT_FOCUS_NEIGHBOR_LIMIT = 12


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


def build_prompt_anchor_projection(
    payload: dict[str, Any] | None,
    *,
    max_anchors: int = DEFAULT_PROMPT_ANCHOR_LIMIT,
    text_match_threshold: float = DEFAULT_PROMPT_TEXT_MATCH_THRESHOLD,
    focus_neighbor_limit: int = DEFAULT_PROMPT_FOCUS_NEIGHBOR_LIMIT,
) -> dict[str, Any] | None:
    """Project full OCR evidence into a bounded text-coordinate relation matrix."""
    if not isinstance(payload, dict):
        return None
    anchors = [item for item in (payload.get("anchors") or []) if isinstance(item, dict)]
    if not anchors:
        return None
    limit = max(1, int(max_anchors))
    focus_limit = max(0, int(focus_neighbor_limit))
    selected = _select_prompt_anchors(
        anchors,
        image_size=payload.get("image_size"),
        limit=limit,
        text_match_threshold=text_match_threshold,
        focus_neighbor_limit=focus_limit,
    )
    rows: list[list[Any]] = []
    goal_match_count = 0
    for anchor in selected:
        is_goal_match = int(_confidence_value(anchor.get("goal_similarity")) >= text_match_threshold)
        rows.append([_anchor_number(anchor), str(anchor.get("text") or ""), *_bbox_array(anchor), is_goal_match])
        goal_match_count += is_goal_match
    result = {
        "contract_version": "ocr_prompt_matrix_v1",
        "profile": "relation_matrix_compact",
        "coordinate_space": payload.get("coordinate_space") or "current_image",
        "source_anchor_count": len(anchors),
        "anchor_count": len(rows),
        "text_anchor_count": len(rows),
        "goal_match_count": goal_match_count,
        "columns": ["i", "t", "x", "y", "w", "h", "m"],
        "rows": rows,
        "relation_policy_columns": ["target_kind", "text_bbox_policy", "allowed_anchor_relation"],
        "relation_policy_rows": [
            ["visual_icon", "exclude_text", "boundary|alignment|exclusion"],
            ["text_control", "include_referenced_text", "inside|contains|edge"],
        ],
    }
    focus_relations = _focus_relation_rows(
        anchors,
        selected=selected,
        text_match_threshold=text_match_threshold,
        limit=focus_limit,
    )
    if focus_relations:
        result.update(
            {
                "focus_relation_columns": ["f", "n", "r", "g"],
                "focus_relation_codes": {
                    "L": "n left of f on same row",
                    "R": "n right of f on same row",
                    "A": "n above f in same column",
                    "B": "n below f in same column",
                },
                "focus_relation_rows": focus_relations,
            }
        )
    result["focus_relation_count"] = len(focus_relations)
    return result


def _select_prompt_anchors(
    anchors: list[dict[str, Any]],
    *,
    image_size: Any,
    limit: int,
    text_match_threshold: float,
    focus_neighbor_limit: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(anchor: dict[str, Any]) -> None:
        key = str(anchor.get("anchor_id") or anchor.get("id") or "")
        if key and key not in seen and len(selected) < limit:
            selected.append(anchor)
            seen.add(key)

    matched = sorted(
        (item for item in anchors if _confidence_value(item.get("goal_similarity")) >= text_match_threshold),
        key=lambda item: (_confidence_value(item.get("goal_similarity")), _confidence_value(item.get("confidence"))),
        reverse=True,
    )
    for anchor in matched:
        add(anchor)

    if focus_neighbor_limit > 0:
        focus_neighbors_added = 0
        for _, neighbor, _, _ in _focus_relation_candidates(matched, anchors):
            previous_count = len(selected)
            add(neighbor)
            if len(selected) > previous_count:
                focus_neighbors_added += 1
            if focus_neighbors_added >= focus_neighbor_limit:
                break

    width, height = _payload_dimensions(image_size)
    if width > 0 and height > 0:
        title_bar_bottom = max(48, int(round(height * 0.06)))
        title_bar = sorted(
            (item for item in anchors if _bbox_array(item)[1] <= title_bar_bottom),
            key=lambda item: _bbox_array(item)[0],
        )
        for anchor in title_bar:
            add(anchor)

        cell_best: dict[tuple[int, int], dict[str, Any]] = {}
        for anchor in anchors:
            x, y, w, h = _bbox_array(anchor)
            center_x = x + (w / 2.0)
            center_y = y + (h / 2.0)
            cell = (min(4, int(center_x * 5 / max(1, width))), min(4, int(center_y * 5 / max(1, height))))
            existing = cell_best.get(cell)
            if existing is None or _confidence_value(anchor.get("confidence")) > _confidence_value(existing.get("confidence")):
                cell_best[cell] = anchor
        for cell in sorted(cell_best):
            add(cell_best[cell])

    for anchor in anchors:
        add(anchor)
    return selected


def _focus_relation_rows(
    anchors: list[dict[str, Any]],
    *,
    selected: list[dict[str, Any]],
    text_match_threshold: float,
    limit: int,
) -> list[list[Any]]:
    if limit <= 0:
        return []
    selected_ids = {str(item.get("anchor_id") or item.get("id") or "") for item in selected}
    matched = [item for item in anchors if _confidence_value(item.get("goal_similarity")) >= text_match_threshold]
    rows: list[list[Any]] = []
    seen: set[tuple[str, str]] = set()
    for focus, neighbor, relation, gap in _focus_relation_candidates(matched, anchors):
        focus_id = str(focus.get("anchor_id") or focus.get("id") or "")
        neighbor_id = str(neighbor.get("anchor_id") or neighbor.get("id") or "")
        key = (focus_id, neighbor_id)
        if focus_id not in selected_ids or neighbor_id not in selected_ids or key in seen:
            continue
        rows.append([_anchor_number(focus), _anchor_number(neighbor), relation, gap])
        seen.add(key)
        if len(rows) >= limit:
            break
    return rows


def _focus_relation_candidates(
    matched: list[dict[str, Any]],
    anchors: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any], str, int]]:
    candidates: list[tuple[float, float, float, dict[str, Any], dict[str, Any], str, int]] = []
    for focus in matched:
        fx, fy, fw, fh = _bbox_array(focus)
        for neighbor in anchors:
            if neighbor is focus:
                continue
            nx, ny, nw, nh = _bbox_array(neighbor)
            x_overlap = max(0, min(fx + fw, nx + nw) - max(fx, nx))
            y_overlap = max(0, min(fy + fh, ny + nh) - max(fy, ny))
            x_overlap_ratio = x_overlap / max(1, min(fw, nw))
            y_overlap_ratio = y_overlap / max(1, min(fh, nh))
            horizontal_gap = max(0, max(fx - (nx + nw), nx - (fx + fw)))
            vertical_gap = max(0, max(fy - (ny + nh), ny - (fy + fh)))
            relation = ""
            priority = 0.0
            gap = 0
            if y_overlap_ratio >= 0.5 and horizontal_gap <= max(80, min(180, fw * 2)):
                relation = "L" if nx + nw <= fx else "R"
                priority = 0.0
                gap = horizontal_gap
            elif x_overlap_ratio >= 0.4 and vertical_gap <= max(80, fh * 4):
                relation = "A" if ny + nh <= fy else "B"
                priority = 1.0
                gap = vertical_gap
            if relation:
                candidates.append(
                    (
                        priority,
                        float(gap),
                        -_confidence_value(neighbor.get("confidence")),
                        focus,
                        neighbor,
                        relation,
                        gap,
                    )
                )
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return [(focus, neighbor, relation, gap) for _, _, _, focus, neighbor, relation, gap in candidates]


def _payload_dimensions(image_size: Any) -> tuple[int, int]:
    if not isinstance(image_size, dict):
        return 0, 0
    try:
        return int(image_size.get("width") or 0), int(image_size.get("height") or 0)
    except (TypeError, ValueError):
        return 0, 0


def _bbox_array(anchor: dict[str, Any]) -> list[int]:
    bbox = anchor.get("bbox") if isinstance(anchor.get("bbox"), dict) else {}
    return [
        int(bbox.get("x") or 0),
        int(bbox.get("y") or 0),
        int(bbox.get("w") or bbox.get("width") or 0),
        int(bbox.get("h") or bbox.get("height") or 0),
    ]


def _anchor_number(anchor: dict[str, Any]) -> int | str:
    anchor_id = str(anchor.get("anchor_id") or anchor.get("id") or "")
    match = re.search(r"(\d+)$", anchor_id)
    return int(match.group(1)) if match else anchor_id


def _confidence_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
    if (left in right or right in left) and min(len(left), len(right)) >= 2:
        return 0.9
    return SequenceMatcher(None, left, right).ratio()
