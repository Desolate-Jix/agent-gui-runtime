from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.recognition.schemas import (
    CandidateRankResult,
    LocalGroundingCandidateResult,
    LocalGroundingResult,
    PreClickCandidateDecision,
    PreClickDecisionResult,
    RecognitionCandidate,
)
from app.vision.schemas import BBox


def decide_pre_click(
    *,
    goal: str,
    candidates: CandidateRankResult,
    grounding: LocalGroundingResult,
    min_candidate_score: float = 0.45,
    min_margin: float = 0.06,
    min_local_text_similarity: float = 0.45,
) -> PreClickDecisionResult:
    grounding_by_id = {item.candidate_id: item for item in grounding.results}
    decisions: list[PreClickCandidateDecision] = []

    for candidate in candidates.candidates:
        local = grounding_by_id.get(candidate.candidate_id)
        decisions.append(
            _candidate_decision(
                goal=goal,
                candidate=candidate,
                local=local,
                min_candidate_score=min_candidate_score,
                min_local_text_similarity=min_local_text_similarity,
            )
        )

    top_margin_ok = _top_margin_ok(candidates, min_margin=min_margin)
    if not top_margin_ok:
        for decision in decisions:
            decision.allowed = False
            decision.reasons = [item for item in decision.reasons if item != "pre_click_checks_passed"]
            decision.reasons.append("top_candidate_margin_too_small")

    allowed = [item for item in decisions if item.allowed]
    selected = allowed[0] if allowed else None
    reasons = ["pre_click_candidate_allowed"] if selected is not None else ["no_candidate_passed_pre_click_checks"]
    if not top_margin_ok:
        reasons.append("top_candidate_margin_too_small")

    return PreClickDecisionResult(
        allowed=selected is not None,
        selected_candidate_id=selected.candidate_id if selected else None,
        selected_element_id=selected.element_id if selected else None,
        selected_click_point=selected.click_point if selected else None,
        reasons=reasons,
        candidate_decisions=decisions,
        summary={
            "candidate_count": len(candidates.candidates),
            "allowed_candidate_count": len(allowed),
            "top_margin_ok": top_margin_ok,
            "margin_to_second": candidates.margin_to_second,
        },
    )


def _candidate_decision(
    *,
    goal: str,
    candidate: RecognitionCandidate,
    local: LocalGroundingCandidateResult | None,
    min_candidate_score: float,
    min_local_text_similarity: float,
) -> PreClickCandidateDecision:
    allowed = True
    reasons: list[str] = []

    if not candidate.eligible:
        allowed = False
        reasons.append("candidate_not_eligible")
    if candidate.score < min_candidate_score:
        allowed = False
        reasons.append("candidate_score_too_low")
    if candidate.score_breakdown.text_similarity < min_local_text_similarity:
        allowed = False
        reasons.append("candidate_goal_text_mismatch")
    policy = candidate.element.interaction_policy
    if not policy.allowed:
        allowed = False
        reasons.append("interaction_policy_blocked")
    if policy.zone_type == "ad_candidate" or policy.ad_risk >= 0.6:
        allowed = False
        reasons.append("ad_like_candidate")

    click_point = dict(candidate.element.click_point)
    if local is None:
        allowed = False
        reasons.append("missing_narrow_search_result")
    else:
        if local.status != "grounded":
            allowed = False
            reasons.append(f"narrow_search_status:{local.status}")
        if local.refined_click_point is None:
            allowed = False
            reasons.append("missing_refined_click_point")
        else:
            click_point = dict(local.refined_click_point)
            if not _point_inside_bbox(click_point, _candidate_decision_bbox(candidate), padding=8):
                allowed = False
                reasons.append("refined_point_outside_candidate_bbox")
        if local.matched_text:
            similarity = _best_similarity(goal, local.matched_text, [candidate.label, candidate.text, candidate.element.description])
            if similarity < min_local_text_similarity:
                allowed = False
                reasons.append("local_ocr_text_mismatch")
            else:
                reasons.append("local_ocr_text_match")
        else:
            allowed = False
            reasons.append("missing_local_ocr_text")

    if allowed:
        reasons.append("pre_click_checks_passed")
    return PreClickCandidateDecision(
        candidate_id=candidate.candidate_id,
        element_id=candidate.element_id,
        allowed=allowed,
        score=candidate.score,
        click_point=click_point if click_point else None,
        reasons=_unique(reasons),
    )


def _top_margin_ok(candidates: CandidateRankResult, *, min_margin: float) -> bool:
    if not candidates.candidates:
        return False
    if len(candidates.candidates) == 1:
        return True
    if candidates.margin_to_second is None:
        return False
    return float(candidates.margin_to_second) >= min_margin


def _point_inside_bbox(point: dict[str, int], bbox: BBox, *, padding: int = 0) -> bool:
    x = int(point.get("x", -1))
    y = int(point.get("y", -1))
    return (
        bbox.x - padding <= x <= bbox.x + bbox.w + padding
        and bbox.y - padding <= y <= bbox.y + bbox.h + padding
    )


def _candidate_decision_bbox(candidate: RecognitionCandidate) -> BBox:
    bbox = candidate.refined_bbox
    if not bbox:
        return candidate.element.bbox
    return BBox(
        x=int(bbox.get("x", 0)),
        y=int(bbox.get("y", 0)),
        w=int(bbox.get("w", bbox.get("width", 0))),
        h=int(bbox.get("h", bbox.get("height", 0))),
    )


def _best_similarity(goal: str, matched_text: str, values: list[str]) -> float:
    targets = [_normalize_text(goal), *[_normalize_text(value) for value in values]]
    text = _normalize_text(matched_text)
    return max((_text_similarity(text, target) for target in targets if target), default=0.0)


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if min(len(left), len(right)) >= 3 and (left in right or right in left):
        return 0.9
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    token_score = 0.0
    if left_tokens and right_tokens:
        token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    return max(token_score, SequenceMatcher(None, left, right).ratio())


def _normalize_text(value: str) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", normalized)
    return " ".join(normalized.split())


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
