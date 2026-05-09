from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

from app.vision.region_standard import build_layout_key, build_match_key, diagonal_from_bbox, normalized_diagonal_from_bbox
from app.vision.schemas import BBox, VisionAnalyzeResponse, VisionRegion
from modules.ocr.contracts import OCRResult, OCRTextMatch


@dataclass
class OCRRegionRefineOptions:
    enabled: bool = False
    min_text_score: float = 0.58
    padding: int = 16


@dataclass
class _Candidate:
    match: OCRTextMatch
    text_score: float
    total_score: float


def parse_ocr_region_refine_options(metadata: dict[str, Any] | None) -> OCRRegionRefineOptions:
    raw = dict(metadata or {}).get("ocr_region_refine")
    if raw in (None, False):
        return OCRRegionRefineOptions(enabled=False)
    if raw is True:
        return OCRRegionRefineOptions(enabled=True)
    if isinstance(raw, dict):
        if not raw.get("enabled", True):
            return OCRRegionRefineOptions(enabled=False)
        min_text_score = _clamp_float(raw.get("min_text_score"), default=0.58, minimum=0.2, maximum=0.95)
        padding = _clamp_int(raw.get("padding"), default=16, minimum=4, maximum=64)
        return OCRRegionRefineOptions(enabled=True, min_text_score=min_text_score, padding=padding)
    return OCRRegionRefineOptions(enabled=True)


def refine_vision_regions_with_ocr(
    vision: VisionAnalyzeResponse,
    ocr: OCRResult,
    *,
    options: OCRRegionRefineOptions,
) -> VisionAnalyzeResponse:
    if not options.enabled or vision.image_size is None or not vision.regions:
        return vision

    refined_regions: list[VisionRegion] = []
    adjustment_report: list[dict[str, Any]] = []
    adjusted_count = 0
    matched_count = 0

    for region in vision.regions:
        report, refined = _refine_region(region, ocr.matches, image_size=vision.image_size.to_dict(), options=options)
        if report.get("matched_candidate_count", 0) > 0:
            matched_count += 1
        if report.get("status") == "adjusted":
            adjusted_count += 1
        adjustment_report.append(report)
        refined_regions.append(refined)

    refined = VisionAnalyzeResponse(
        provider=vision.provider,
        contract_version=vision.contract_version,
        image_size=vision.image_size,
        screen_summary=vision.screen_summary,
        state_guess=vision.state_guess,
        regions=refined_regions,
        targets=list(vision.targets),
        observers=list(vision.observers),
        notes=[
            *list(vision.notes),
            f"ocr_region_refine=adjusted:{adjusted_count}/{len(vision.regions)} matched:{matched_count}/{len(vision.regions)}",
        ],
        artifacts={
            **dict(vision.artifacts),
            "ocr_region_refine": {
                "profile": "ocr_region_refine_v1",
                "enabled": True,
                "adjusted_region_count": adjusted_count,
                "matched_region_count": matched_count,
                "unchanged_region_count": len(vision.regions) - adjusted_count,
                "options": {
                    "min_text_score": options.min_text_score,
                    "padding": options.padding,
                },
                "regions": adjustment_report,
            },
        },
        raw_text=vision.raw_text,
        raw_response=vision.raw_response,
    )
    return refined


def _refine_region(
    region: VisionRegion,
    matches: list[OCRTextMatch],
    *,
    image_size: dict[str, int],
    options: OCRRegionRefineOptions,
) -> tuple[dict[str, Any], VisionRegion]:
    phrases = _region_phrases(region)
    candidates = _matching_candidates(region, matches, min_text_score=options.min_text_score)
    inside_matches = [item for item in candidates if _contains_center(region.bbox, _bbox_from_match(item.match))]
    report: dict[str, Any] = {
        "region_id": region.region_id,
        "label": region.label,
        "before_bbox": region.bbox.to_dict(),
        "after_bbox": region.bbox.to_dict(),
        "status": "unchanged",
        "matched_candidate_count": len(candidates),
        "inside_candidate_count": len(inside_matches),
        "phrases": phrases[:4],
        "matched_ocr_texts": [item.match.text for item in candidates[:4]],
        "selected_ocr_texts": [],
        "move": {"dx": 0, "dy": 0},
        "reason": "no_matching_ocr_candidate",
    }
    if inside_matches:
        report["reason"] = "matching_ocr_already_inside_region"
        return report, region
    if not candidates:
        return report, region

    selected = _select_anchor_group(region, candidates)
    anchor_bbox = _union_bbox([_bbox_from_match(item.match) for item in selected])
    shifted_bbox = _shift_bbox_to_cover_anchor(region.bbox, anchor_bbox, image_size=image_size, padding=options.padding)

    if shifted_bbox.to_dict() == region.bbox.to_dict():
        report["reason"] = "anchor_found_but_shift_not_needed"
        report["selected_ocr_texts"] = [item.match.text for item in selected[:4]]
        return report, region

    refined = _with_updated_bbox(region, shifted_bbox, image_size=image_size)
    report["after_bbox"] = shifted_bbox.to_dict()
    report["status"] = "adjusted"
    report["selected_ocr_texts"] = [item.match.text for item in selected[:4]]
    report["move"] = {
        "dx": shifted_bbox.x - region.bbox.x,
        "dy": shifted_bbox.y - region.bbox.y,
    }
    report["reason"] = "shifted_to_include_matching_ocr_anchor"
    return report, refined


def _matching_candidates(region: VisionRegion, matches: list[OCRTextMatch], *, min_text_score: float) -> list[_Candidate]:
    phrases = _region_phrases(region)
    candidates: list[_Candidate] = []
    for match in matches:
        text_score = max((_text_similarity(match.text, phrase) for phrase in phrases), default=0.0)
        if text_score < min_text_score:
            continue
        proximity = _proximity_score(region.bbox, _bbox_from_match(match))
        total = round((text_score * 0.75) + (proximity * 0.25), 4)
        candidates.append(_Candidate(match=match, text_score=round(text_score, 4), total_score=total))
    candidates.sort(key=lambda item: (item.total_score, item.text_score, item.match.score), reverse=True)
    return candidates


def _select_anchor_group(region: VisionRegion, candidates: list[_Candidate]) -> list[_Candidate]:
    seed = candidates[0]
    seed_bbox = _bbox_from_match(seed.match)
    selected = [seed]
    for candidate in candidates[1:]:
        if candidate.text_score < max(0.6, seed.text_score - 0.12):
            continue
        bbox = _bbox_from_match(candidate.match)
        if abs(_center_x(bbox) - _center_x(seed_bbox)) <= max(region.bbox.w, 80) and abs(_center_y(bbox) - _center_y(seed_bbox)) <= max(region.bbox.h, 80):
            selected.append(candidate)
    selected.sort(key=lambda item: (item.match.bbox.y, item.match.bbox.x))
    return selected


def _shift_bbox_to_cover_anchor(
    bbox: BBox,
    anchor_bbox: BBox,
    *,
    image_size: dict[str, int],
    padding: int,
) -> BBox:
    width = bbox.w
    height = bbox.h
    x1 = bbox.x
    y1 = bbox.y
    x2 = bbox.x + bbox.w
    y2 = bbox.y + bbox.h
    ax1 = anchor_bbox.x
    ay1 = anchor_bbox.y
    ax2 = anchor_bbox.x + anchor_bbox.w
    ay2 = anchor_bbox.y + anchor_bbox.h

    if anchor_bbox.w + (padding * 2) >= width:
        new_x = int(round(_center_x(anchor_bbox) - (width / 2.0)))
    elif ax1 < x1 + padding:
        new_x = ax1 - padding
    elif ax2 > x2 - padding:
        new_x = ax2 + padding - width
    else:
        new_x = x1

    if anchor_bbox.h + (padding * 2) >= height:
        new_y = int(round(_center_y(anchor_bbox) - (height / 2.0)))
    elif ay1 < y1 + padding:
        new_y = ay1 - padding
    elif ay2 > y2 - padding:
        new_y = ay2 + padding - height
    else:
        new_y = y1

    max_x = max(0, int(image_size.get("width", 0)) - width)
    max_y = max(0, int(image_size.get("height", 0)) - height)
    clamped_x = min(max(0, new_x), max_x)
    clamped_y = min(max(0, new_y), max_y)
    return BBox(x=int(clamped_x), y=int(clamped_y), w=width, h=height)


def _with_updated_bbox(region: VisionRegion, bbox: BBox, *, image_size: dict[str, int]) -> VisionRegion:
    diagonal = diagonal_from_bbox(bbox)
    normalized = normalized_diagonal_from_bbox(
        bbox,
        width=int(image_size.get("width", 0)),
        height=int(image_size.get("height", 0)),
    )
    layout_key = build_layout_key(region.role, normalized)
    return VisionRegion(
        region_id=region.region_id,
        label=region.label,
        role=region.role,
        bbox=bbox,
        diagonal=diagonal,
        normalized_diagonal=normalized,
        description=region.description,
        ocr_text=region.ocr_text,
        text_lines=list(region.text_lines),
        possible_destinations=list(region.possible_destinations),
        confidence=region.confidence,
        layout_key=layout_key,
        content_key=region.content_key,
        match_key=build_match_key(layout_key, region.content_key),
    )


def _region_phrases(region: VisionRegion) -> list[str]:
    values = [
        region.label,
        region.ocr_text,
        *region.text_lines,
        region.description,
    ]
    phrases: list[str] = []
    for value in values:
        normalized = _normalize_text(value)
        if normalized and normalized not in phrases:
            phrases.append(normalized)
    return phrases


def _text_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    if normalized_left in normalized_right or normalized_right in normalized_left:
        return 0.9
    sequence_score = SequenceMatcher(None, normalized_left, normalized_right).ratio()
    left_tokens = set(normalized_left.split())
    right_tokens = set(normalized_right.split())
    token_score = 0.0
    if left_tokens and right_tokens:
        token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return max(sequence_score, token_score)


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _bbox_from_match(match: OCRTextMatch) -> BBox:
    return BBox(x=int(match.bbox.x), y=int(match.bbox.y), w=int(match.bbox.width), h=int(match.bbox.height))


def _union_bbox(boxes: Iterable[BBox]) -> BBox:
    materialized = list(boxes)
    x1 = min(item.x for item in materialized)
    y1 = min(item.y for item in materialized)
    x2 = max(item.x + item.w for item in materialized)
    y2 = max(item.y + item.h for item in materialized)
    return BBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1)


def _contains_center(container: BBox, child: BBox) -> bool:
    center_x = _center_x(child)
    center_y = _center_y(child)
    return container.x <= center_x <= container.x + container.w and container.y <= center_y <= container.y + container.h


def _proximity_score(region_bbox: BBox, text_bbox: BBox) -> float:
    distance = ((float(_center_x(region_bbox)) - float(_center_x(text_bbox))) ** 2 + (float(_center_y(region_bbox)) - float(_center_y(text_bbox))) ** 2) ** 0.5
    diag = max(1.0, (float(region_bbox.w**2 + region_bbox.h**2)) ** 0.5)
    return max(0.0, 1.0 - min(distance / (diag * 1.25), 1.0))


def _center_x(bbox: BBox) -> int:
    return int(round(bbox.x + bbox.w / 2.0))


def _center_y(bbox: BBox) -> int:
    return int(round(bbox.y + bbox.h / 2.0))


def _clamp_int(raw: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except Exception:
        return default
    return max(minimum, min(maximum, value))


def _clamp_float(raw: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(raw)
    except Exception:
        return default
    return max(minimum, min(maximum, value))
