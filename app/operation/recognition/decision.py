from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.operation.recognition.schemas import (
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
    allow_low_margin_when_grounded: bool = False,
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

    precision_review_top_blocked = bool(
        decisions
        and candidates.candidates[0].element.interaction_policy.zone_type in {"precise_visual_target", "precise_text_target"}
        and not decisions[0].allowed
    )
    if precision_review_top_blocked:
        review_zone = candidates.candidates[0].element.interaction_policy.zone_type
        blocked_reason = (
            "higher_ranked_precision_visual_target_requires_confirmation"
            if review_zone == "precise_visual_target"
            else "higher_ranked_precision_text_target_requires_confirmation"
        )
        for decision in decisions[1:]:
            if decision.allowed:
                decision.allowed = False
                decision.reasons = [item for item in decision.reasons if item != "pre_click_checks_passed"]
                decision.reasons.append(blocked_reason)

    top_margin_ok = _top_margin_ok(candidates, min_margin=min_margin)
    if not top_margin_ok:
        for index, decision in enumerate(decisions):
            if allow_low_margin_when_grounded and index == 0 and decision.allowed and "pre_click_checks_passed" in decision.reasons:
                decision.reasons.append("top_candidate_margin_reviewed_override")
                continue
            decision.allowed = False
            decision.reasons = [item for item in decision.reasons if item != "pre_click_checks_passed"]
            decision.reasons.append("top_candidate_margin_too_small")

    allowed = [item for item in decisions if item.allowed]
    selected = allowed[0] if allowed else None
    reasons = ["pre_click_candidate_allowed"] if selected is not None else ["no_candidate_passed_pre_click_checks"]
    if not top_margin_ok:
        reasons.append("top_candidate_margin_reviewed_override" if selected is not None else "top_candidate_margin_too_small")

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
            "low_margin_reviewed_override_used": bool(selected is not None and not top_margin_ok and allow_low_margin_when_grounded),
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
    goal_mentions_candidate_label = _goal_explicitly_requests_candidate_label(goal, candidate)
    if candidate.score_breakdown.text_similarity < min_local_text_similarity and not goal_mentions_candidate_label:
        allowed = False
        reasons.append("candidate_goal_text_mismatch")
    elif goal_mentions_candidate_label:
        reasons.append("goal_explicitly_mentions_candidate_label")
    policy = candidate.element.interaction_policy
    if not policy.allowed:
        allowed = False
        reasons.append("interaction_policy_blocked")
    if policy.zone_type == "precise_visual_target":
        allowed = False
        reasons.append("precision_visual_target_requires_confirmation")
    if policy.zone_type == "precise_text_target":
        allowed = False
        reasons.append("precision_text_target_requires_confirmation")
    if policy.zone_type == "ad_candidate" or policy.ad_risk >= 0.6:
        allowed = False
        reasons.append("ad_like_candidate")

    click_point = dict(candidate.element.click_point)
    resolved_click_point: dict[str, object] | None = None
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
            bbox = _candidate_decision_bbox(candidate)
            raw_point = dict(local.refined_click_point)
            click_point, resolved_click_point = _resolve_click_point(candidate=candidate, bbox=bbox, raw_point=raw_point)
            if resolved_click_point.get("chosen_point_source") == "bbox_safe_center":
                reasons.append("bbox_safe_center_used")
            if not resolved_click_point.get("raw_inside_bbox"):
                allowed = False
                reasons.append("refined_point_outside_candidate_bbox")
            elif not _point_inside_bbox(click_point, bbox, padding=8):
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

    if _verified_precision_text_candidate(
        goal=goal,
        candidate=candidate,
        local=local,
        min_local_text_similarity=min_local_text_similarity,
    ):
        reasons = [
            reason
            for reason in reasons
            if reason not in {"interaction_policy_blocked", "precision_text_target_requires_confirmation"}
        ]
        hard_blockers = {
            "candidate_not_eligible",
            "candidate_score_too_low",
            "candidate_goal_text_mismatch",
            "ad_like_candidate",
            "missing_narrow_search_result",
            "missing_refined_click_point",
            "refined_point_outside_candidate_bbox",
            "local_ocr_text_mismatch",
            "missing_local_ocr_text",
        }
        if not any(reason in hard_blockers or reason.startswith("narrow_search_status:") for reason in reasons):
            allowed = True
            reasons.append("precision_text_target_verified_by_local_ocr")

    if allowed:
        reasons.append("pre_click_checks_passed")
    return PreClickCandidateDecision(
        candidate_id=candidate.candidate_id,
        element_id=candidate.element_id,
        allowed=allowed,
        score=candidate.score,
        click_point=click_point if click_point else None,
        reasons=_unique(reasons),
        resolved_click_point=resolved_click_point,
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


def _resolve_click_point(
    *,
    candidate: RecognitionCandidate,
    bbox: BBox,
    raw_point: dict[str, int],
) -> tuple[dict[str, int], dict[str, object]]:
    role = str(candidate.role or candidate.element.role or "").casefold()
    raw = {"x": int(raw_point.get("x", 0)), "y": int(raw_point.get("y", 0))}
    safe_center = _bbox_safe_center(bbox)
    edge_margin = _point_edge_margin(raw, bbox)
    min_margin = _safe_edge_margin(bbox)
    bbox_payload = {"x": int(bbox.x), "y": int(bbox.y), "w": int(bbox.w), "h": int(bbox.h)}
    raw_inside_bbox = _point_inside_bbox(raw, bbox)
    should_use_center = _safe_center_role(role) and raw_inside_bbox and edge_margin < min_margin and _valid_bbox(bbox)
    chosen = safe_center if should_use_center else raw
    source = "bbox_safe_center" if should_use_center else "raw_grounding_point"
    reason = "raw_model_point_near_edge" if should_use_center else "raw_grounding_point_within_safe_margin"
    return chosen, {
        "contract_version": "resolved_click_point_v1",
        "target_text": candidate.text or candidate.label,
        "target_role": role or None,
        "bbox": bbox_payload,
        "bbox_source": "candidate_refined_bbox" if candidate.refined_bbox else "candidate_element_bbox",
        "raw_model_point": raw,
        "chosen_point": chosen,
        "chosen_point_source": source,
        "adjustment_reason": reason,
        "inside_bbox": _point_inside_bbox(chosen, bbox),
        "raw_inside_bbox": raw_inside_bbox,
        "edge_margin_px": int(edge_margin),
        "min_edge_margin_px": int(min_margin),
    }


def _safe_center_role(role: str) -> bool:
    return role in {"button", "menuitem", "checkbox", "radio", "tab", "toggle", "switch"}


def _valid_bbox(bbox: BBox) -> bool:
    return int(bbox.w) > 0 and int(bbox.h) > 0


def _bbox_safe_center(bbox: BBox) -> dict[str, int]:
    return {"x": int(round(bbox.x + bbox.w / 2)), "y": int(round(bbox.y + bbox.h / 2))}


def _safe_edge_margin(bbox: BBox) -> int:
    short_side = max(1, min(int(bbox.w), int(bbox.h)))
    return max(4, min(10, int(round(short_side * 0.15))))


def _point_edge_margin(point: dict[str, int], bbox: BBox) -> int:
    x = int(point.get("x", 0))
    y = int(point.get("y", 0))
    return min(
        abs(x - int(bbox.x)),
        abs(int(bbox.x + bbox.w) - x),
        abs(y - int(bbox.y)),
        abs(int(bbox.y + bbox.h) - y),
    )


def _verified_precision_text_candidate(
    *,
    goal: str,
    candidate: RecognitionCandidate,
    local: LocalGroundingCandidateResult | None,
    min_local_text_similarity: float,
) -> bool:
    policy = candidate.element.interaction_policy
    if policy.zone_type != "precise_text_target" or policy.ad_risk >= 0.6:
        return False
    required_reasons = {"precision_text_target_matches_goal", "strong_goal_text_match", "supported_interaction"}
    if not required_reasons.issubset(set(candidate.reasons)):
        return False
    if not candidate.eligible or local is None or local.status != "grounded":
        return False
    if local.refined_click_point is None or not local.matched_text:
        return False
    if not _point_inside_bbox(dict(local.refined_click_point), _candidate_decision_bbox(candidate), padding=8):
        return False
    similarity = _best_similarity(goal, local.matched_text, [candidate.label, candidate.text, candidate.element.description])
    return similarity >= min_local_text_similarity


def _best_similarity(goal: str, matched_text: str, values: list[str]) -> float:
    targets = [_normalize_text(goal), *[_normalize_text(value) for value in values]]
    text = _normalize_text(matched_text)
    return max((_text_similarity(text, target) for target in targets if target), default=0.0)


def _goal_explicitly_requests_candidate_label(goal: str, candidate: RecognitionCandidate) -> bool:
    goal_text = _normalize_text(goal)
    labels = _candidate_label_values(candidate)
    for label in labels:
        label_text = _normalize_text(label)
        if len(label_text) < 3:
            continue
        for match in re.finditer(rf"(?<!\w){re.escape(label_text)}(?!\w)", goal_text):
            before = goal_text[max(0, match.start() - 40) : match.start()].strip()
            if _negates_next_click_target(before):
                continue
            return True
    return False


def _candidate_label_values(candidate: RecognitionCandidate) -> list[str]:
    return _unique(
        [
            str(candidate.label or ""),
            str(candidate.text or ""),
            str(candidate.element.label or ""),
            str(candidate.element.text or ""),
        ]
    )


def _negates_next_click_target(preceding_text: str) -> bool:
    words = preceding_text.split()
    tail = " ".join(words[-5:])
    return bool(
        re.search(
            r"\b(do not|don t|dont|never|not|avoid|exclude|excluding|forbid|forbidden)\b",
            tail,
        )
    )


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
