from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

from app.page_structure.schemas import PageElement, PageText
from app.recognition.schemas import CandidateRankRequest, CandidateRankResult, RecognitionCandidate, ScoreBreakdown
from app.vision.schemas import ImageSize


SUPPORTED_INTERACTIONS = {"click", "focus"}
HIGH_PRIORITY_ZONES = {"test_module", "nav_control", "general_action"}


def rank_candidates(request: CandidateRankRequest) -> CandidateRankResult:
    top_k = max(1, int(request.top_k or 5))
    ranked: list[RecognitionCandidate] = []
    rejected: list[RecognitionCandidate] = []
    texts_by_id = {text.text_id: text for text in request.page_structure.texts}

    for element in request.page_structure.elements:
        breakdown, reasons, eligible = _score_element(element, goal=request.goal, state_hint=request.state_hint)
        refined_bbox, bbox_refine_reason = _refined_bbox_from_source_texts(
            element,
            goal=request.goal,
            texts_by_id=texts_by_id,
            image_size=request.page_structure.image_size,
        )
        if refined_bbox is not None:
            reasons.append("bbox_refined_from_source_text")
        candidate = RecognitionCandidate(
            candidate_id=_candidate_id(element),
            rank=0,
            element_id=element.element_id,
            label=element.label,
            role=element.role,
            text=element.text,
            score=breakdown.total(),
            eligible=eligible,
            reasons=reasons,
            score_breakdown=breakdown,
            element=element,
            refined_bbox=refined_bbox,
            bbox_refine_reason=bbox_refine_reason,
        )
        if eligible:
            ranked.append(candidate)
        else:
            rejected.append(candidate)

    ranked.sort(key=lambda item: (item.score, item.score_breakdown.text_similarity, item.element.fusion_confidence), reverse=True)
    rejected.sort(key=lambda item: (item.score, item.score_breakdown.text_similarity), reverse=True)
    for index, candidate in enumerate(ranked, start=1):
        candidate.rank = index
    for index, candidate in enumerate(rejected, start=1):
        candidate.rank = index

    selected = ranked[:top_k]
    margin = None
    if len(selected) >= 2:
        margin = round(selected[0].score - selected[1].score, 4)
    elif selected:
        margin = selected[0].score

    return CandidateRankResult(
        goal=request.goal,
        top_k=top_k,
        candidates=selected,
        rejected=rejected,
        recommended_candidate_id=selected[0].candidate_id if selected else None,
        margin_to_second=margin,
        summary={
            "element_count": len(request.page_structure.elements),
            "eligible_count": len(ranked),
            "rejected_count": len(rejected),
            "returned_count": len(selected),
            "has_recommendation": bool(selected),
        },
    )


def _score_element(element: PageElement, *, goal: str, state_hint: str | None) -> tuple[ScoreBreakdown, list[str], bool]:
    policy = element.interaction_policy
    reasons: list[str] = []
    text_similarity = _best_text_similarity(goal, _element_text_values(element))
    role_score = _role_score(element)
    policy_score = _policy_score(element)
    confidence_score = _confidence_score(element)
    state_score = _state_score(element, state_hint)
    ad_penalty = max(0.0, min(float(policy.ad_risk), 1.0))
    blocked_penalty = 1.0 if not policy.allowed else 0.0

    if text_similarity >= 0.75:
        reasons.append("strong_goal_text_match")
    elif text_similarity >= 0.45:
        reasons.append("partial_goal_text_match")
    if role_score >= 0.8:
        reasons.append("supported_interaction")
    if policy.zone_type in HIGH_PRIORITY_ZONES:
        reasons.append(f"trusted_zone:{policy.zone_type}")
    if ad_penalty >= 0.6:
        reasons.append("ad_risk_penalty")
    if blocked_penalty:
        reasons.append("blocked_by_interaction_policy")
    if state_score > 0.0:
        reasons.append("state_hint_match")

    breakdown = ScoreBreakdown(
        text_similarity=text_similarity,
        role_score=role_score,
        policy_score=policy_score,
        confidence_score=confidence_score,
        state_score=state_score,
        ad_penalty=ad_penalty,
        blocked_penalty=blocked_penalty,
    )
    eligible = bool(policy.allowed) and element.interaction_type in SUPPORTED_INTERACTIONS and breakdown.total() >= 0.18
    if not eligible and "low_candidate_score" not in reasons and bool(policy.allowed):
        reasons.append("low_candidate_score")
    return breakdown, _unique(reasons), eligible


def _element_text_values(element: PageElement) -> list[str]:
    return [
        element.label,
        element.text,
        element.description,
        *element.possible_destinations,
        element.role,
        element.interaction_type,
    ]


def _best_text_similarity(goal: str, candidates: Iterable[str]) -> float:
    normalized_goal = _normalize_text(goal)
    if not normalized_goal:
        return 0.0
    return round(max((_text_similarity(normalized_goal, _normalize_text(item)) for item in candidates), default=0.0), 4)


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.9
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    token_score = 0.0
    if left_tokens and right_tokens:
        token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence_score = SequenceMatcher(None, left, right).ratio()
    return max(token_score, sequence_score)


def _role_score(element: PageElement) -> float:
    if element.interaction_type not in SUPPORTED_INTERACTIONS:
        return 0.0
    if element.role in {"button", "input", "tab", "menu_item"}:
        return 1.0
    return 0.55


def _policy_score(element: PageElement) -> float:
    policy = element.interaction_policy
    if not policy.allowed:
        return 0.0
    if policy.priority == "high":
        return 1.0
    if policy.priority == "medium":
        return 0.75
    if policy.zone_type in HIGH_PRIORITY_ZONES:
        return 0.65
    return 0.45


def _confidence_score(element: PageElement) -> float:
    coordinate_score = {
        "high": 1.0,
        "medium": 0.65,
        "low": 0.3,
    }.get(element.coordinate_confidence, 0.4)
    fusion = max(0.0, min(float(element.fusion_confidence), 1.0))
    return round((fusion * 0.65) + (coordinate_score * 0.35), 4)


def _state_score(element: PageElement, state_hint: str | None) -> float:
    normalized_state = _normalize_text(state_hint or "")
    if not normalized_state:
        return 0.0
    return round(max(_text_similarity(normalized_state, _normalize_text(value)) for value in _element_text_values(element)), 4)


def _normalize_text(value: str) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", normalized)
    return " ".join(normalized.split())


def _candidate_id(element: PageElement) -> str:
    slug = re.sub(r"[^0-9a-z]+", "_", element.element_id.casefold()).strip("_")
    return f"candidate_{slug or 'element'}"


def _refined_bbox_from_source_texts(
    element: PageElement,
    *,
    goal: str,
    texts_by_id: dict[str, PageText],
    image_size: ImageSize | None,
    padding: int = 12,
) -> tuple[dict[str, int] | None, str | None]:
    if not element.source_text_ids:
        return None, "no_source_text_ids"

    source_texts = [texts_by_id[text_id] for text_id in element.source_text_ids if text_id in texts_by_id]
    if not source_texts:
        return None, "source_text_ids_not_found"
    selected_texts, selected_reason = _select_refine_texts(source_texts, goal=goal)
    boxes = [text.bbox for text in selected_texts]

    x1 = min(int(box.x) for box in boxes) - int(padding)
    y1 = min(int(box.y) for box in boxes) - int(padding)
    x2 = max(int(box.x + box.w) for box in boxes) + int(padding)
    y2 = max(int(box.y + box.h) for box in boxes) + int(padding)

    x1 = max(0, x1)
    y1 = max(0, y1)
    if image_size is not None:
        x2 = min(int(image_size.width), x2)
        y2 = min(int(image_size.height), y2)

    original_x1 = int(element.bbox.x)
    original_y1 = int(element.bbox.y)
    original_x2 = int(element.bbox.x + element.bbox.w)
    original_y2 = int(element.bbox.y + element.bbox.h)
    x1 = max(x1, original_x1)
    y1 = max(y1, original_y1)
    x2 = min(x2, original_x2)
    y2 = min(y2, original_y2)

    if x2 <= x1 or y2 <= y1:
        return None, "source_text_bbox_outside_element"
    original_area = max(1, (original_x2 - original_x1) * (original_y2 - original_y1))
    refined_area = max(1, (x2 - x1) * (y2 - y1))
    if refined_area >= original_area * 0.95:
        return None, "source_text_bbox_not_tighter"
    return {
        "x": x1,
        "y": y1,
        "w": max(1, x2 - x1),
        "h": max(1, y2 - y1),
    }, f"{selected_reason}:{len(boxes)}"


def _select_refine_texts(texts: list[PageText], *, goal: str) -> tuple[list[PageText], str]:
    normalized_goal = _normalize_text(goal)
    if normalized_goal:
        scored = [
            (_text_similarity(normalized_goal, _normalize_text(text.text)), text)
            for text in texts
        ]
        goal_matches = [text for score, text in scored if score >= 0.65]
        if goal_matches:
            return goal_matches, "goal_text_ids_union"
    return texts, "source_text_ids_union"


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
