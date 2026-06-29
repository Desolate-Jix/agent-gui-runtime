from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.runtime_artifacts import build_review_overlay_path


ALLOW_COLOR = (0, 150, 80)
REJECT_COLOR = (215, 40, 40)
CANDIDATE_COLOR = (230, 170, 0)
REFINED_BBOX_COLOR = (0, 170, 210)
POINT_COLOR = (0, 100, 255)
FALLBACK_POINT_COLOR = (125, 70, 200)


def render_recognition_plan_overlay(
    *,
    trace_path: str | Path,
    include_rejected: bool = True,
    include_points: bool = True,
    label_candidates: bool = True,
    label_reasons: bool = True,
) -> dict[str, Any]:
    trace_file = Path(trace_path)
    trace_payload = json.loads(trace_file.read_text(encoding="utf-8"))
    result = _extract_result(trace_payload)
    if result.get("contract_version") != "recognition_plan_v1":
        raise ValueError("trace does not contain recognition_plan_v1 result")

    image_path = Path(str(result.get("image_path") or ""))
    if not image_path.exists():
        raise FileNotFoundError(f"image referenced by trace does not exist: {image_path}")

    candidates = list(((result.get("candidate_result") or {}).get("candidates")) or [])
    rejected = list(((result.get("candidate_result") or {}).get("rejected")) or [])
    if include_rejected:
        candidates = [*candidates, *rejected]

    narrow_by_id = {
        str(item.get("candidate_id")): item
        for item in ((result.get("narrow_search_result") or {}).get("results") or [])
    }
    decision_by_id = {
        str(item.get("candidate_id")): item
        for item in ((result.get("pre_click_decision") or {}).get("candidate_decisions") or [])
    }
    selected_id = (result.get("pre_click_decision") or {}).get("selected_candidate_id")
    output_path = build_review_overlay_path(name_hint=trace_file.stem, suffix="recognition-plan-overlay")

    with Image.open(image_path) as image:
        annotated = image.convert("RGB")
        draw = ImageDraw.Draw(annotated)
        font = ImageFont.load_default()

        for candidate in candidates:
            candidate_id = str(candidate.get("candidate_id") or "")
            decision = decision_by_id.get(candidate_id)
            narrow = narrow_by_id.get(candidate_id)
            color = _candidate_color(candidate, decision, selected_id=selected_id)
            bbox = ((candidate.get("element") or {}).get("bbox")) or {}
            rect = _bbox_rect(bbox)
            if rect is None:
                continue
            draw.rectangle(rect, outline=color, width=4)
            refined_rect = _bbox_rect(candidate.get("refined_bbox") or {})
            if refined_rect is not None:
                draw.rectangle(refined_rect, outline=REFINED_BBOX_COLOR, width=2)
            if label_candidates:
                label = _candidate_label(candidate, decision, narrow, selected_id=selected_id, label_reasons=label_reasons)
                _draw_label(draw, rect[0], rect[1], label, font=font, color=color)
            if include_points:
                _draw_candidate_point(draw, narrow, decision)

        annotated.save(output_path)

    return {
        "trace_path": str(trace_file.resolve()),
        "image_path": str(image_path.resolve()),
        "output_path": str(output_path.resolve()),
        "candidate_count": len(candidates),
        "decision_count": len(decision_by_id),
        "narrow_result_count": len(narrow_by_id),
        "selected_candidate_id": selected_id,
        "include_rejected": bool(include_rejected),
        "include_points": bool(include_points),
        "label_candidates": bool(label_candidates),
        "label_reasons": bool(label_reasons),
    }


def _extract_result(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("result"), dict):
        return payload["result"]
    data = payload.get("data") or {}
    if isinstance(data.get("result"), dict):
        return data["result"]
    return {}


def _candidate_color(candidate: dict[str, Any], decision: dict[str, Any] | None, *, selected_id: Any) -> tuple[int, int, int]:
    if decision is not None:
        if bool(decision.get("allowed")):
            return ALLOW_COLOR
        return REJECT_COLOR
    if candidate.get("eligible") is False:
        return REJECT_COLOR
    if selected_id and candidate.get("candidate_id") == selected_id:
        return ALLOW_COLOR
    return CANDIDATE_COLOR


def _bbox_rect(bbox: dict[str, Any]) -> tuple[int, int, int, int] | None:
    if not bbox:
        return None
    x = int(bbox.get("x", 0))
    y = int(bbox.get("y", 0))
    w = int(bbox.get("w", bbox.get("width", 0)))
    h = int(bbox.get("h", bbox.get("height", 0)))
    if w <= 0 or h <= 0:
        return None
    return (x, y, x + w, y + h)


def _candidate_label(
    candidate: dict[str, Any],
    decision: dict[str, Any] | None,
    narrow: dict[str, Any] | None,
    *,
    selected_id: Any,
    label_reasons: bool,
) -> str:
    rank = candidate.get("rank", "?")
    score = float(candidate.get("score") or 0.0)
    label = str(candidate.get("label") or candidate.get("text") or candidate.get("element_id") or "candidate")
    state = "SEL" if selected_id and candidate.get("candidate_id") == selected_id else "CAND"
    if decision is not None:
        state = "ALLOW" if decision.get("allowed") else "REJECT"
    text = f"#{rank} {state} {score:.2f} {label[:28]}"
    if narrow and narrow.get("matched_text"):
        text += f" | ocr:{str(narrow.get('matched_text'))[:20]}"
    if candidate.get("refined_bbox") and candidate.get("bbox_refine_reason"):
        text += f" | rb:{str(candidate.get('bbox_refine_reason'))[:18]}"
    if label_reasons and decision:
        reasons = [str(item) for item in decision.get("reasons") or []]
        if reasons:
            text += f" | {', '.join(reasons[:2])[:42]}"
    return text


def _draw_candidate_point(draw: ImageDraw.ImageDraw, narrow: dict[str, Any] | None, decision: dict[str, Any] | None) -> None:
    point = None
    color = POINT_COLOR
    if narrow and narrow.get("refined_click_point"):
        point = narrow.get("refined_click_point")
        if narrow.get("coordinate_source") == "candidate_element_click_point":
            color = FALLBACK_POINT_COLOR
    elif decision and decision.get("click_point"):
        point = decision.get("click_point")
        color = FALLBACK_POINT_COLOR
    if not point:
        return
    x = int(point.get("x", 0))
    y = int(point.get("y", 0))
    radius = 7
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color, outline=(255, 255, 255), width=2)
    draw.line((x - 12, y, x + 12, y), fill=color, width=2)
    draw.line((x, y - 12, x, y + 12), fill=color, width=2)


def _draw_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    *,
    font: ImageFont.ImageFont,
    color: tuple[int, int, int],
) -> None:
    try:
        left, top, right, bottom = draw.textbbox((x, y), label, font=font)
        text_w = right - left
        text_h = bottom - top
    except Exception:
        text_w = max(48, len(label) * 7)
        text_h = 14
    text_y = max(0, y - text_h - 6)
    draw.rectangle((x, text_y, x + text_w + 8, text_y + text_h + 6), fill=color)
    draw.text((x + 4, text_y + 3), label, fill=(255, 255, 255), font=font)
