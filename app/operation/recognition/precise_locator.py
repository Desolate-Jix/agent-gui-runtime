from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from math import hypot
import re
from typing import Any


_GENERIC_LABELS = {
    "button",
    "control",
    "icon",
    "item",
    "link",
    "nav",
    "text",
    "unknown",
}


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        result = {key: int(round(float(value.get(key)))) for key in ("x", "y", "w", "h")}
    except (TypeError, ValueError):
        return None
    if result["w"] <= 0 or result["h"] <= 0:
        return None
    return result


def _point(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        return {"x": int(round(float(value.get("x")))), "y": int(round(float(value.get("y"))))}
    except (TypeError, ValueError):
        return None


def _inside(point: dict[str, int] | None, bbox: dict[str, int] | None) -> bool:
    if point is None or bbox is None:
        return False
    return (
        bbox["x"] <= point["x"] <= bbox["x"] + bbox["w"]
        and bbox["y"] <= point["y"] <= bbox["y"] + bbox["h"]
    )


def _bbox_inside(inner: dict[str, int] | None, outer: dict[str, int] | None) -> bool:
    if inner is None or outer is None:
        return False
    return (
        outer["x"] <= inner["x"]
        and outer["y"] <= inner["y"]
        and inner["x"] + inner["w"] <= outer["x"] + outer["w"]
        and inner["y"] + inner["h"] <= outer["y"] + outer["h"]
    )


def _iou(left: dict[str, int], right: dict[str, int]) -> float:
    x1 = max(left["x"], right["x"])
    y1 = max(left["y"], right["y"])
    x2 = min(left["x"] + left["w"], right["x"] + right["w"])
    y2 = min(left["y"] + left["h"], right["y"] + right["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = left["w"] * left["h"] + right["w"] * right["h"] - intersection
    return intersection / union if union > 0 else 0.0


def _compact(value: Any) -> str:
    return " ".join(str(value or "").split())


def _normalized_text(value: Any) -> str:
    return "".join(character for character in _compact(value).casefold() if character.isalnum())


def _generated_generic_label(value: Any) -> bool:
    text = _compact(value).casefold()
    if _normalized_text(text) in _GENERIC_LABELS:
        return True
    return re.fullmatch(
        r"(?:control|button|icon|item|card|nav|text|region|group|slot|element)[\s_#.-]*\d+",
        text,
    ) is not None


def _similarity(left: Any, right: Any) -> float:
    left_text = _normalized_text(left)
    right_text = _normalized_text(right)
    if not left_text or not right_text:
        return 0.0
    if left_text in right_text or right_text in left_text:
        return min(len(left_text), len(right_text)) / max(len(left_text), len(right_text))
    return SequenceMatcher(None, left_text, right_text).ratio()


def _center_distance_score(point: dict[str, int] | None, bbox: dict[str, int]) -> float:
    if point is None:
        return 0.0
    center_x = bbox["x"] + bbox["w"] / 2
    center_y = bbox["y"] + bbox["h"] / 2
    diagonal = max(1.0, hypot(bbox["w"], bbox["h"]))
    distance = hypot(point["x"] - center_x, point["y"] - center_y)
    return max(0.0, 1.0 - distance / diagonal)


def _source_name(candidate: dict[str, Any]) -> str:
    return _compact(candidate.get("source")) or "unknown"


def _normalize_candidate(candidate: dict[str, Any], *, index: int) -> dict[str, Any] | None:
    candidate_bbox = _bbox(candidate.get("bbox"))
    if candidate_bbox is None:
        return None
    sources = [_compact(item) for item in candidate.get("sources", []) if _compact(item)]
    source = _source_name(candidate)
    if source not in sources:
        sources.append(source)
    return {
        "candidate_id": _compact(candidate.get("candidate_id")) or f"candidate-{index}",
        "label": _compact(candidate.get("label")),
        "role": _compact(candidate.get("role")) or "unknown",
        "bbox": candidate_bbox,
        "click_point": _point(candidate.get("click_point")),
        "confidence": max(0.0, min(1.0, float(candidate.get("confidence") or 0.0))),
        "freshness": _compact(candidate.get("freshness")) or "unknown",
        "sources": sorted(set(sources)),
        "evidence": dict(candidate.get("evidence")) if isinstance(candidate.get("evidence"), dict) else {},
    }


def _merge_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for candidate in candidates:
        match = next(
            (
                existing
                for existing in merged
                if _iou(existing["bbox"], candidate["bbox"]) >= 0.72
                and _similarity(existing.get("label"), candidate.get("label")) >= 0.72
            ),
            None,
        )
        if match is None:
            merged.append(candidate)
            continue
        match["sources"] = sorted(set([*match["sources"], *candidate["sources"]]))
        if candidate["confidence"] > match["confidence"]:
            match["confidence"] = candidate["confidence"]
            match["candidate_id"] = candidate["candidate_id"]
            match["bbox"] = candidate["bbox"]
            match["click_point"] = candidate["click_point"]
            match["freshness"] = candidate["freshness"]
        match["evidence"] = {**match.get("evidence", {}), **candidate.get("evidence", {})}
    return merged


def _source_bbox_quality(
    *,
    source_candidate: dict[str, Any] | None,
    target_label: str,
    parent_bbox: dict[str, int] | None,
    vista_point: dict[str, int] | None,
) -> dict[str, Any]:
    if source_candidate is None or _bbox(source_candidate.get("bbox")) is None:
        return {"classification": "candidate_bbox_missing", "reasons": ["source_bbox_missing"]}
    source_bbox = _bbox(source_candidate.get("bbox"))
    freshness = _compact(source_candidate.get("freshness"))
    if freshness not in {"current_capture", "current", "verified_current"}:
        return {"classification": "candidate_bbox_stale", "reasons": ["source_candidate_not_current"]}
    if not _bbox_inside(source_bbox, parent_bbox):
        return {"classification": "candidate_outside_parent", "reasons": ["source_bbox_outside_parent_region"]}
    if _generated_generic_label(target_label):
        return {"classification": "candidate_label_too_generic", "reasons": ["target_label_too_generic"]}
    if vista_point is not None and not _inside(vista_point, source_bbox):
        return {"classification": "candidate_bbox_misaligned", "reasons": ["vista_point_outside_source_bbox"]}
    return {"classification": "candidate_bbox_ok", "reasons": []}


def build_precise_locator_evidence(
    *,
    capture_id: str,
    image_size: dict[str, int],
    goal: str,
    target: dict[str, Any],
    source_candidate: dict[str, Any] | None,
    evidence_candidates: list[dict[str, Any]],
    vista_point: dict[str, Any] | None,
    mode: str = "learn",
    numbered_overlay_used: bool = False,
) -> dict[str, Any]:
    parent_bbox = _bbox(target.get("parent_region_bbox"))
    target_label = _compact(target.get("label"))
    target_role = _compact(target.get("role")) or "unknown"
    normalized_point = _point(vista_point)

    raw_candidates = [item for item in [source_candidate, *evidence_candidates] if isinstance(item, dict)]
    source_counts = Counter(_source_name(item) for item in raw_candidates)
    normalized_candidates = [
        candidate
        for index, item in enumerate(raw_candidates)
        if (candidate := _normalize_candidate(item, index=index)) is not None
        and _bbox_inside(candidate["bbox"], parent_bbox)
    ]
    candidates = _merge_candidates(normalized_candidates)

    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        label_score = _similarity(target_label, candidate["label"])
        role_score = 1.0 if candidate["role"] == target_role else (0.5 if candidate["role"] in {"unknown", "text"} else 0.0)
        vista_inside = _inside(normalized_point, candidate["bbox"])
        vista_score = 1.0 if vista_inside else 0.0
        source_diversity_score = min(1.0, len(candidate["sources"]) / 3.0)
        center_score = _center_distance_score(normalized_point, candidate["bbox"]) if vista_inside else 0.0
        score_breakdown = {
            "semantic_label": round(label_score, 4),
            "role_match": round(role_score, 4),
            "vista_point_inside": round(vista_score, 4),
            "source_diversity": round(source_diversity_score, 4),
            "confidence": round(candidate["confidence"], 4),
            "center_proximity": round(center_score, 4),
            "source_origin_bonus": 0.0,
        }
        score = (
            label_score * 0.30
            + role_score * 0.10
            + vista_score * 0.30
            + source_diversity_score * 0.15
            + candidate["confidence"] * 0.10
            + center_score * 0.05
        )
        scored.append(
            {
                **candidate,
                "vista_point_inside_bbox": vista_inside,
                "score": round(score, 4),
                "score_breakdown": score_breakdown,
            }
        )
    scored.sort(key=lambda item: (-float(item["score"]), item["candidate_id"]))
    selected = scored[0] if scored else None
    margin = round(float(scored[0]["score"]) - float(scored[1]["score"]), 4) if len(scored) > 1 else None
    bbox_quality = _source_bbox_quality(
        source_candidate=source_candidate,
        target_label=target_label,
        parent_bbox=parent_bbox,
        vista_point=normalized_point,
    )

    gate_reasons: list[str] = []
    if selected is None:
        gate_reasons.append("no_valid_candidate_inside_parent")
        gate_status = "locate_review_failed"
    else:
        source_candidate_id = _compact((source_candidate or {}).get("candidate_id"))
        if _generated_generic_label(target_label):
            gate_reasons.append("target_label_too_generic_for_precise_location")
            if selected["candidate_id"] != source_candidate_id:
                gate_reasons.append("generated_label_cannot_disambiguate_sibling")
        if not selected["vista_point_inside_bbox"]:
            gate_reasons.append("vista_point_outside_selected_bbox")
        if selected["score_breakdown"]["semantic_label"] < 0.45:
            gate_reasons.append("semantic_evidence_too_weak")
        if selected["score"] < 0.62:
            gate_reasons.append("candidate_score_below_threshold")
        if margin is not None and margin < 0.08:
            gate_reasons.append("candidate_margin_too_small")
        if selected["freshness"] not in {"current_capture", "current", "verified_current"}:
            gate_reasons.append("selected_candidate_not_current")
        gate_status = "locate_review_pass" if not gate_reasons else "needs_human_review"

    return {
        "contract_version": "precise_locator_evidence_v1",
        "mode": mode,
        "capture_id": _compact(capture_id),
        "image_size": {"width": int(image_size.get("width") or 0), "height": int(image_size.get("height") or 0)},
        "goal": _compact(goal),
        "target": {
            "target_id": _compact(target.get("target_id")),
            "label": target_label,
            "role": target_role,
            "parent_region_id": _compact(target.get("parent_region_id")),
            "parent_region_bbox": parent_bbox,
        },
        "source_bbox_quality": bbox_quality,
        "candidate_source_counts": dict(sorted(source_counts.items())),
        "candidates": scored,
        "selected_candidate": selected,
        "margin_to_second": margin,
        "vista_point": normalized_point,
        "numbered_overlay_used": bool(numbered_overlay_used),
        "overlay_used_as_model_input": bool(numbered_overlay_used),
        "dry_run_gate": {
            "contract_version": "precise_locator_dry_run_gate_v1",
            "status": gate_status,
            "allowed_for_review": gate_status == "locate_review_pass",
            "click_authorized": False,
            "reasons": gate_reasons,
        },
        "execute_binding_enabled": False,
        "click_performed": False,
    }
