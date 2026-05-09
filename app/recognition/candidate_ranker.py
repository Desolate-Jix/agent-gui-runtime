from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Iterable

from app.page_structure.schemas import PageElement
from app.recognition.schemas import CandidateRankRequest, CandidateRankResult, RecognitionCandidate, ScoreBreakdown


SUPPORTED_INTERACTIONS = {"click", "focus"}
HIGH_PRIORITY_ZONES = {"test_module", "nav_control", "general_action"}


def rank_candidates(request: CandidateRankRequest) -> CandidateRankResult:
    top_k = max(1, int(request.top_k or 5))
    ranked: list[RecognitionCandidate] = []
    rejected: list[RecognitionCandidate] = []

    for element in request.page_structure.elements:
        breakdown, reasons, eligible = _score_element(element, goal=request.goal, state_hint=request.state_hint)
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


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
