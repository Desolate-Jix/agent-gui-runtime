from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from app.page_structure.schemas import InteractionPolicy, PageElement, PageLink, PageStructure, PageText, VerificationHints
from app.vision.schemas import BBox, VisionAnalyzeResponse, VisionRegion
from modules.ocr.contracts import OCRBoundingBox, OCRResult

SUPPORTED_ROLES = {"button", "input", "tab", "menu_item"}
ROLE_ALIASES = {
    "nav": "menu_item",
    "navigation": "menu_item",
    "menu": "menu_item",
    "link": "menu_item",
}
AD_KEYWORDS = {
    "cpu-z",
    "gpu-z",
    "aida64",
    "furmark",
    "hwinfo",
    "download",
    "涓嬭浇",
    "璁块棶",
    "璇︽儏",
    "绮鹃€?",
    "纭欢",
    "鏍″噯",
    "淇",
    "绔嬪嵆浣撻獙",
    "绔嬪嵆璁块棶",
    "绔嬪嵆鏍″噯",
}
TEST_KEYWORDS = {
    "娴嬭瘯",
    "妫€娴?",
    "鐐瑰嚮寮€濮?",
    "鐐瑰嚮姝ゅ",
    "鍙屽嚮",
    "cps",
    "鍥炴姤鐜?",
    "杞鐜?",
    "骞虫粦搴?",
    "鍏夋爣",
    "榧犳爣",
    "寰姩",
}
NAV_KEYWORDS = {
    "鍓嶈繘",
    "杩斿洖",
    "back",
    "next",
    "涓婁竴椤?",
    "涓嬩竴椤?",
}


@dataclass
class _Candidate:
    text: PageText
    score: float
    text_score: float
    geometry_score: float
    reasons: list[str]


def build_page_structure(vision: VisionAnalyzeResponse, ocr: OCRResult) -> PageStructure:
    texts = _build_texts(ocr)
    elements: list[PageElement] = []
    links: list[PageLink] = []
    used_text_ids: set[str] = set()
    raw_regions = [region.to_dict() for region in vision.regions]

    for region in vision.regions:
        role = _normalize_role(region.role)
        if _is_precise_visual_icon_region(region, role=role):
            element = _element_from_precise_visual_icon(region, role)
            elements.append(element)
            links.append(
                PageLink(
                    link_id=f"link_{element.element_id}",
                    relation="precise_visual_grounding",
                    region_id=region.region_id,
                    element_id=element.element_id,
                    text_ids=[],
                    score=round(float(region.confidence), 4),
                    reasons=["icon_only_bbox_from_precise_vision_grounding", "requires_pre_click_confirmation"],
                )
            )
            continue
        if _is_precise_clickable_text_card_region(region, role=role):
            candidates = _rank_text_candidates(region, texts)
            bound = [item for item in candidates if _candidate_is_bindable(item)]
            if not bound:
                continue
            selected_texts = _select_bound_texts(bound, region=region)
            used_text_ids.update(item.text.text_id for item in selected_texts)
            element = _element_from_precise_text_card(region, selected_texts, texts)
            elements.append(element)
            link_reasons = ["clickable_card_with_ocr_text_proof", "requires_pre_click_confirmation"]
            if element.evidence.get("above_exclusion_boundary"):
                link_reasons.append("above_exclusion_boundary_applied")
            if element.evidence.get("semantic_bbox_violations"):
                link_reasons.append("semantic_bbox_crossed_above_exclusion_boundary")
            links.append(
                PageLink(
                    link_id=f"link_{element.element_id}",
                    relation="precise_text_grounding",
                    region_id=region.region_id,
                    element_id=element.element_id,
                    text_ids=[item.text.text_id for item in selected_texts],
                    score=round(max(item.score for item in selected_texts), 4),
                    reasons=link_reasons,
                )
            )
            continue
        if role not in SUPPORTED_ROLES:
            continue

        candidates = _rank_text_candidates(region, texts)
        bound = [item for item in candidates if _candidate_is_bindable(item)]
        if bound:
            selected_texts = _select_bound_texts(bound, region=region)
            used_text_ids.update(item.text.text_id for item in selected_texts)
            element = _element_from_region_and_texts(region, role, selected_texts)
            _apply_above_exclusion_boundary(element, region=region, selected_texts=selected_texts, texts=texts)
            elements.append(element)
            link_reasons = _merge_reasons(item.reasons for item in selected_texts)
            if element.evidence.get("above_exclusion_boundary"):
                link_reasons.append("above_exclusion_boundary_applied")
            if element.evidence.get("semantic_bbox_violations"):
                link_reasons.append("semantic_bbox_crossed_above_exclusion_boundary")
            links.append(
                PageLink(
                    link_id=f"link_{element.element_id}",
                    relation="semantic_text_binding",
                    region_id=region.region_id,
                    element_id=element.element_id,
                    text_ids=[item.text.text_id for item in selected_texts],
                    score=round(max(item.score for item in selected_texts), 4),
                    reasons=_unique(link_reasons),
                )
            )
            continue

        element = _element_from_semantic_region(region, role)
        elements.append(element)
        links.append(
            PageLink(
                link_id=f"link_{element.element_id}",
                relation="semantic_only",
                region_id=region.region_id,
                element_id=element.element_id,
                text_ids=[],
                score=round(float(region.confidence), 4),
                reasons=["supported_role_without_ocr_text"],
            )
        )

    for text in texts:
        if text.text_id in used_text_ids:
            continue
        links.append(
            PageLink(
                link_id=f"link_unbound_{text.text_id}",
                relation="unbound_text",
                region_id=None,
                element_id=None,
                text_ids=[text.text_id],
                score=round(float(text.score), 4),
                reasons=["ocr_text_not_bound_to_supported_semantic_region"],
            )
        )

    learning_summary = _learning_summary(elements, texts, vision)

    return PageStructure(
        image_size=vision.image_size,
        screen_summary=vision.screen_summary,
        state_guess=vision.state_guess,
        regions=raw_regions,
        elements=elements,
        texts=texts,
        links=links,
        learning_summary=learning_summary,
        raw_ocr=ocr.to_dict(),
        raw_vision_regions=raw_regions,
    )


def _build_texts(ocr: OCRResult) -> list[PageText]:
    source = str(ocr.metadata.get("engine") or "ocr")
    texts: list[PageText] = []
    for index, match in enumerate(ocr.matches, start=1):
        texts.append(
            PageText(
                text_id=f"text_{index}",
                text=match.text,
                bbox=_bbox_from_ocr(match.bbox),
                score=float(match.score),
                source=source,
                source_index=index - 1,
            )
        )
    return texts


def _rank_text_candidates(region: VisionRegion, texts: list[PageText]) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for text in texts:
        text_score = _best_text_score(text.text, _region_text_values(region))
        geometry_score = _geometry_score(region.bbox, text.bbox)
        role_score = 1.0 if _normalize_role(region.role) in SUPPORTED_ROLES else 0.0
        ocr_score = max(0.0, min(float(text.score), 1.0))
        qwen_score = max(0.0, min(float(region.confidence), 1.0))
        score = (text_score * 0.65) + (geometry_score * 0.15) + (role_score * 0.08) + (ocr_score * 0.07) + (qwen_score * 0.05)
        reasons: list[str] = []
        if text_score >= 0.85:
            reasons.append("strong_text_match")
        elif text_score >= 0.55:
            reasons.append("partial_text_match")
        if geometry_score >= 0.75:
            reasons.append("strong_geometry_match")
        elif geometry_score >= 0.35:
            reasons.append("nearby_geometry_match")
        if ocr_score >= 0.8:
            reasons.append("high_ocr_confidence")
        if qwen_score >= 0.7:
            reasons.append("high_semantic_confidence")
        candidates.append(
            _Candidate(
                text=text,
                score=round(score, 4),
                text_score=round(text_score, 4),
                geometry_score=round(geometry_score, 4),
                reasons=reasons,
            )
        )
    candidates.sort(key=lambda item: (item.score, item.text_score, item.text.score), reverse=True)
    return candidates


def _select_bound_texts(candidates: list[_Candidate], *, region: VisionRegion) -> list[_Candidate]:
    best = candidates[0]
    selected = [best]
    for candidate in candidates[1:]:
        if (
            candidate.text_score >= 0.85
            and candidate.score >= best.score - 0.12
            and _same_text_cluster(best.text.bbox, candidate.text.bbox, region.bbox)
        ):
            selected.append(candidate)
    selected.sort(key=lambda item: (item.text.bbox.y, item.text.bbox.x))
    return selected


def _same_text_cluster(anchor: BBox, candidate: BBox, region_bbox: BBox) -> bool:
    anchor_center = _bbox_center(anchor)
    candidate_center = _bbox_center(candidate)
    dx = abs(anchor_center["x"] - candidate_center["x"])
    dy = abs(anchor_center["y"] - candidate_center["y"])
    same_line = dy <= max(anchor.h, candidate.h, 18) * 1.8
    nearby_line = dy <= max(region_bbox.h, anchor.h, candidate.h, 40) * 1.2
    max_dx = max(120, min(max(region_bbox.w, anchor.w, candidate.w) * 1.6, 360))
    if same_line and dx <= max_dx:
        return True
    return nearby_line and dx <= max(80, min(max(region_bbox.w, anchor.w, candidate.w) * 0.75, 220))


def _candidate_is_bindable(candidate: _Candidate) -> bool:
    if candidate.score < 0.45:
        return False
    normalized = _normalize_text(candidate.text.text)
    compact_length = len(normalized.replace(" ", ""))
    if candidate.geometry_score < 0.05 and candidate.text_score < 0.92:
        return False
    if compact_length <= 2 and candidate.geometry_score < 0.35 and candidate.text_score < 0.98:
        return False
    return True


def _element_from_region_and_texts(region: VisionRegion, role: str, candidates: list[_Candidate]) -> PageElement:
    text_values = [item.text.text for item in candidates]
    text = " ".join(value for value in text_values if value).strip()
    bbox = _union_bbox([item.text.bbox for item in candidates])
    best = max(candidates, key=lambda item: item.score)
    interaction_type = _interaction_type(role)
    click_point = _bbox_center(bbox)
    click_strategy = "ocr_text_center_focus" if role == "input" else "ocr_text_center"
    label = _best_label(region, text)
    fusion_confidence = round(min(1.0, max(best.score, float(region.confidence) * 0.7, float(best.text.score) * 0.7)), 4)
    coordinate_confidence = "high" if best.text_score >= 0.75 and best.text.score >= 0.7 else "medium"
    memory_key = _memory_key(role=role, label=label, text=text, layout_key=region.layout_key)
    text_ids = [item.text.text_id for item in candidates]
    policy = _interaction_policy(role=role, label=label, text=text, description=region.description, possible_destinations=region.possible_destinations)
    return PageElement(
        element_id=_element_id(role, label, region.region_id),
        label=label,
        role=role,
        interaction_type=interaction_type,
        description=region.description,
        text=text,
        bbox=bbox,
        semantic_bbox=region.bbox,
        click_point=click_point,
        click_strategy=click_strategy,
        possible_destinations=list(region.possible_destinations),
        verification_hints=_verification_hints(role),
        interaction_policy=policy,
        fusion_confidence=fusion_confidence,
        coordinate_confidence=coordinate_confidence,
        memory_key=memory_key,
        sources=_unique(["qwen3_vl", *[item.text.source for item in candidates]]),
        source_region_ids=[region.region_id],
        source_text_ids=text_ids,
        evidence={
            "binding_scores": [
                {
                    "text_id": item.text.text_id,
                    "score": item.score,
                    "text_score": item.text_score,
                    "geometry_score": item.geometry_score,
                    "reasons": list(item.reasons),
                }
                for item in candidates
            ],
            "semantic_match_key": region.match_key,
        },
    )


def _element_from_semantic_region(region: VisionRegion, role: str) -> PageElement:
    label = _best_label(region, region.ocr_text)
    bbox = region.bbox
    policy = _interaction_policy(
        role=role,
        label=label,
        text=region.ocr_text,
        description=region.description,
        possible_destinations=region.possible_destinations,
    )
    return PageElement(
        element_id=_element_id(role, label, region.region_id),
        label=label,
        role=role,
        interaction_type=_interaction_type(role),
        description=region.description,
        text=region.ocr_text,
        bbox=bbox,
        semantic_bbox=region.bbox,
        click_point=_bbox_center(bbox),
        click_strategy="semantic_bbox_center",
        possible_destinations=list(region.possible_destinations),
        verification_hints=_verification_hints(role),
        interaction_policy=policy,
        fusion_confidence=round(max(0.0, min(float(region.confidence) * 0.65, 1.0)), 4),
        coordinate_confidence="medium" if float(region.confidence) >= 0.75 else "low",
        memory_key=_memory_key(role=role, label=label, text=region.ocr_text, layout_key=region.layout_key),
        sources=["qwen3_vl"],
        source_region_ids=[region.region_id],
        source_text_ids=[],
        evidence={
            "semantic_match_key": region.match_key,
            "reason": "no_ocr_text_bound",
        },
    )


def _element_from_precise_visual_icon(region: VisionRegion, role: str) -> PageElement:
    label = _best_label(region, "")
    bbox = region.bbox
    policy = InteractionPolicy(
        allowed=False,
        zone_type="precise_visual_target",
        priority="review",
        ad_risk=0.0,
        reasons=["precision_visual_grounding_requires_confirmation"],
    )
    return PageElement(
        element_id=_element_id(role, label, region.region_id),
        label=label,
        role=role,
        interaction_type="click",
        description=region.description,
        text="",
        bbox=bbox,
        semantic_bbox=bbox,
        click_point=_bbox_center(bbox),
        click_strategy="vision_grounded_icon_center",
        possible_destinations=list(region.possible_destinations),
        verification_hints=_verification_hints(role),
        interaction_policy=policy,
        fusion_confidence=round(max(0.0, min(float(region.confidence), 1.0)), 4),
        coordinate_confidence="medium",
        memory_key=_memory_key(role=role, label=label, text="", layout_key=region.layout_key),
        sources=["qwen3_vl", "ocr_anchor_guided_visual_grounding"],
        source_region_ids=[region.region_id],
        source_text_ids=[],
        evidence={
            "semantic_match_key": region.match_key,
            "reason": "precise_visual_icon_grounding",
            "text_inclusion_policy": "exclude_text",
            "grounding_constraints": dict(region.grounding_constraints),
            "anchor_relations": list(region.anchor_relations),
        },
    )


def _element_from_precise_text_card(region: VisionRegion, candidates: list[_Candidate], texts: list[PageText]) -> PageElement:
    element = _element_from_region_and_texts(region, "card", candidates)
    if element.interaction_policy.zone_type != "ad_candidate":
        element.interaction_policy = InteractionPolicy(
            allowed=False,
            zone_type="precise_text_target",
            priority="review",
            ad_risk=element.interaction_policy.ad_risk,
            reasons=["precision_text_grounding_requires_confirmation"],
        )
    element.click_strategy = "ocr_text_center_review"
    element.verification_hints = VerificationHints(
        expected_changes=["state_change", "new_region", "content_change"],
        target_scope="page",
    )
    element.evidence.update(
        {
            "reason": "precise_clickable_card_grounded_from_ocr_text",
            "text_inclusion_policy": "include_referenced_text",
            "grounding_constraints": dict(region.grounding_constraints),
            "anchor_relations": list(region.anchor_relations),
        }
    )
    _apply_above_exclusion_boundary(element, region=region, selected_texts=candidates, texts=texts)
    return element


def _apply_above_exclusion_boundary(
    element: PageElement,
    *,
    region: VisionRegion,
    selected_texts: list[_Candidate],
    texts: list[PageText],
) -> None:
    if not _uses_referenced_text_grounding(region):
        return
    selected_ids = {item.text.text_id for item in selected_texts}
    target_bbox = _union_bbox([item.text.bbox for item in selected_texts])
    boundary = _nearest_above_text_boundary(target_bbox, texts=texts, excluded_ids=selected_ids)
    if boundary is None:
        return
    visual_crosses_boundary = _intersects(region.bbox, boundary.bbox)
    candidate_crosses_boundary = _intersects(element.bbox, boundary.bbox)
    element.evidence["above_exclusion_boundary"] = {
        "text_id": boundary.text_id,
        "text": boundary.text,
        "bbox": boundary.bbox.to_dict(),
        "relation": "above_target_text",
        "vertical_gap_px": target_bbox.y - (boundary.bbox.y + boundary.bbox.h),
        "semantic_bbox_crosses_boundary": visual_crosses_boundary,
        "candidate_bbox_crosses_boundary": candidate_crosses_boundary,
        "enforcement": "candidate_bbox_uses_target_ocr_text_only",
    }
    if visual_crosses_boundary:
        element.evidence["semantic_bbox_violations"] = ["crosses_above_exclusion_boundary"]
        if element.interaction_policy.zone_type != "ad_candidate":
            element.interaction_policy = InteractionPolicy(
                allowed=False,
                zone_type="precise_text_target",
                priority="review",
                ad_risk=element.interaction_policy.ad_risk,
                reasons=["semantic_bbox_crosses_above_exclusion_boundary", "precision_text_grounding_requires_confirmation"],
            )
            element.click_strategy = "ocr_text_center_review"


def _nearest_above_text_boundary(target_bbox: BBox, *, texts: list[PageText], excluded_ids: set[str]) -> PageText | None:
    max_vertical_gap = max(180, target_bbox.h * 4)
    max_left_offset = max(80, target_bbox.w // 2)
    boundaries: list[tuple[int, PageText]] = []
    for text in texts:
        if text.text_id in excluded_ids:
            continue
        bottom = text.bbox.y + text.bbox.h
        vertical_gap = target_bbox.y - bottom
        if vertical_gap < 0 or vertical_gap > max_vertical_gap:
            continue
        horizontally_related = _horizontal_overlap(target_bbox, text.bbox) > 0 or abs(text.bbox.x - target_bbox.x) <= max_left_offset
        if horizontally_related:
            boundaries.append((vertical_gap, text))
    if not boundaries:
        return None
    boundaries.sort(key=lambda item: (item[0], abs(item[1].bbox.x - target_bbox.x), -item[1].score))
    return boundaries[0][1]


def _uses_referenced_text_grounding(region: VisionRegion) -> bool:
    constraints = region.grounding_constraints or {}
    policy = str(constraints.get("text_inclusion_policy") or "").strip().lower().replace("-", "_").replace(" ", "_")
    return policy == "include_referenced_text"


def _horizontal_overlap(left: BBox, right: BBox) -> int:
    return max(0, min(left.x + left.w, right.x + right.w) - max(left.x, right.x))


def _intersects(left: BBox, right: BBox) -> bool:
    return bool(
        left.x < right.x + right.w
        and left.x + left.w > right.x
        and left.y < right.y + right.h
        and left.y + left.h > right.y
    )


def _is_precise_visual_icon_region(region: VisionRegion, *, role: str) -> bool:
    if role not in {"icon", "icon_button", "toolbar_button", "button"}:
        return False
    constraints = region.grounding_constraints or {}
    policy = str(constraints.get("text_inclusion_policy") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if policy != "exclude_text" or float(region.confidence) < 0.7:
        return False
    edges = constraints.get("edge_constraints")
    return bool(
        isinstance(edges, dict)
        and all(edges.get(edge) for edge in ("top", "bottom", "left", "right"))
        and constraints.get("final_bbox_reason")
    )


def _is_precise_clickable_text_card_region(region: VisionRegion, *, role: str) -> bool:
    if role != "card" or float(region.confidence) < 0.7:
        return False
    constraints = region.grounding_constraints or {}
    edges = constraints.get("edge_constraints")
    has_target_text = bool(region.ocr_text.strip() or any(item.strip() for item in region.text_lines))
    return bool(
        _uses_referenced_text_grounding(region)
        and has_target_text
        and region.possible_destinations
        and isinstance(edges, dict)
        and all(edges.get(edge) for edge in ("top", "bottom", "left", "right"))
        and constraints.get("final_bbox_reason")
    )


def _region_text_values(region: VisionRegion) -> list[str]:
    return [region.label, region.ocr_text, *region.text_lines]


def _best_text_score(text: str, candidates: Iterable[str]) -> float:
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return 0.0
    return max((_text_similarity(normalized_text, _normalize_text(item)) for item in candidates), default=0.0)


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.86
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    return overlap / len(left_tokens | right_tokens)


def _geometry_score(region_bbox: BBox, text_bbox: BBox) -> float:
    if _contains_center(region_bbox, text_bbox):
        return 1.0
    overlap = _iou(region_bbox, text_bbox)
    distance = _center_distance(region_bbox, text_bbox)
    region_diag = max(1.0, ((region_bbox.w**2 + region_bbox.h**2) ** 0.5))
    distance_score = max(0.0, 1.0 - min(distance / (region_diag * 1.5), 1.0))
    return max(overlap, distance_score * 0.6)


def _contains_center(container: BBox, child: BBox) -> bool:
    center = _bbox_center(child)
    return container.x <= center["x"] <= container.x + container.w and container.y <= center["y"] <= container.y + container.h


def _iou(left: BBox, right: BBox) -> float:
    x1 = max(left.x, right.x)
    y1 = max(left.y, right.y)
    x2 = min(left.x + left.w, right.x + right.w)
    y2 = min(left.y + left.h, right.y + right.h)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    intersection = (x2 - x1) * (y2 - y1)
    union = (left.w * left.h) + (right.w * right.h) - intersection
    return intersection / max(1, union)


def _center_distance(left: BBox, right: BBox) -> float:
    left_center = _bbox_center(left)
    right_center = _bbox_center(right)
    return ((left_center["x"] - right_center["x"]) ** 2 + (left_center["y"] - right_center["y"]) ** 2) ** 0.5


def _bbox_from_ocr(bbox: OCRBoundingBox) -> BBox:
    return BBox(x=int(bbox.x), y=int(bbox.y), w=int(bbox.width), h=int(bbox.height))


def _union_bbox(boxes: list[BBox]) -> BBox:
    x1 = min(box.x for box in boxes)
    y1 = min(box.y for box in boxes)
    x2 = max(box.x + box.w for box in boxes)
    y2 = max(box.y + box.h for box in boxes)
    return BBox(x=x1, y=y1, w=x2 - x1, h=y2 - y1)


def _bbox_center(bbox: BBox) -> dict[str, int]:
    return {
        "x": int(round(bbox.x + bbox.w / 2.0)),
        "y": int(round(bbox.y + bbox.h / 2.0)),
    }


def _normalize_role(role: str) -> str:
    normalized = _normalize_text(role).replace(" ", "_")
    return ROLE_ALIASES.get(normalized, normalized)


def _interaction_type(role: str) -> str:
    if role == "input":
        return "focus"
    return "click"


def _verification_hints(role: str) -> VerificationHints:
    if role in {"button", "menu_item"}:
        return VerificationHints(expected_changes=["state_change", "new_region", "content_change"], target_scope="page")
    if role == "tab":
        return VerificationHints(expected_changes=["selection_change", "content_change"], target_scope="local")
    if role == "input":
        return VerificationHints(expected_changes=["focus_change", "caret_visible"], target_scope="local")
    return VerificationHints(expected_changes=["unknown_change"], target_scope="local")


def _interaction_policy(
    *,
    role: str,
    label: str,
    text: str,
    description: str,
    possible_destinations: list[str],
) -> InteractionPolicy:
    combined = " ".join(value for value in [role, label, text, description, *possible_destinations] if value)
    normalized = _normalize_text(combined)
    reasons: list[str] = []
    ad_risk = 0.0
    trusted_score = 0.0
    nav_score = 0.0

    if any(keyword in normalized for keyword in AD_KEYWORDS):
        ad_risk += 0.75
        reasons.append("ad_like_keyword")
    if any(keyword in normalized for keyword in TEST_KEYWORDS):
        trusted_score += 0.7
        reasons.append("test_like_keyword")
    if any(keyword in normalized for keyword in NAV_KEYWORDS):
        nav_score += 0.8
        reasons.append("navigation_keyword")
    if role == "tab":
        nav_score = max(nav_score, 0.65)
        reasons.append("tab_role")
    if role == "input":
        trusted_score += 0.2
        reasons.append("input_focusable")
    if "鐐瑰嚮" in normalized:
        trusted_score += 0.2
        reasons.append("explicit_click_instruction")
    if "绔嬪嵆" in normalized and trusted_score < 0.7:
        ad_risk += 0.2
        reasons.append("cta_without_test_context")

    ad_risk = round(min(ad_risk, 1.0), 4)
    if ad_risk >= 0.6:
        return InteractionPolicy(
            allowed=False,
            zone_type="ad_candidate",
            priority="blocked",
            ad_risk=ad_risk,
            reasons=_unique(reasons or ["ad_candidate"]),
        )
    if trusted_score >= 0.7:
        return InteractionPolicy(
            allowed=True,
            zone_type="test_module",
            priority="high",
            ad_risk=ad_risk,
            reasons=_unique(reasons or ["test_module"]),
        )
    if nav_score >= 0.65:
        return InteractionPolicy(
            allowed=True,
            zone_type="nav_control",
            priority="medium",
            ad_risk=ad_risk,
            reasons=_unique(reasons or ["nav_control"]),
        )
    if role in {"button", "menu_item", "input", "tab"}:
        return InteractionPolicy(
            allowed=True,
            zone_type="general_action",
            priority="low",
            ad_risk=ad_risk,
            reasons=_unique(reasons or ["generic_action"]),
        )
    return InteractionPolicy(
        allowed=False,
        zone_type="unknown",
        priority="blocked",
        ad_risk=ad_risk,
        reasons=_unique(reasons or ["unsupported_action"]),
    )


def _learning_summary(elements: list[PageElement], texts: list[PageText], vision: VisionAnalyzeResponse) -> dict[str, object]:
    safe_elements = [item.element_id for item in elements if item.interaction_policy.allowed]
    blocked_elements = [item.element_id for item in elements if not item.interaction_policy.allowed]
    ad_like_elements = [item.element_id for item in elements if item.interaction_policy.zone_type == "ad_candidate"]
    return {
        "profile": "rule_based_interaction_learning_v1",
        "screen_type": _normalize_text(vision.state_guess or vision.screen_summary or "unknown"),
        "safe_element_ids": safe_elements,
        "blocked_element_ids": blocked_elements,
        "ad_like_element_ids": ad_like_elements,
        "allowed_element_count": len(safe_elements),
        "blocked_element_count": len(blocked_elements),
        "test_module_count": len([item for item in elements if item.interaction_policy.zone_type == "test_module"]),
        "nav_control_count": len([item for item in elements if item.interaction_policy.zone_type == "nav_control"]),
        "ocr_text_count": len(texts),
    }


def _best_label(region: VisionRegion, text: str) -> str:
    if text.strip():
        return text.strip()
    if region.label.strip():
        return region.label.strip()
    return _normalize_role(region.role)


def _memory_key(*, role: str, label: str, text: str, layout_key: str) -> str:
    return "|".join(
        [
            f"role:{_normalize_text(role)}",
            f"label:{_normalize_text(label)}",
            f"text:{_normalize_text(text)}",
            f"layout:{layout_key or 'none'}",
        ]
    )


def _element_id(role: str, label: str, region_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _normalize_text(label)).strip("_") or "element"
    source = f"{role}|{slug}|{region_id}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:8]
    return f"element_{slug}_{digest}"


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _merge_reasons(groups: Iterable[list[str]]) -> list[str]:
    result: list[str] = []
    for group in groups:
        for item in group:
            if item not in result:
                result.append(item)
    return result
