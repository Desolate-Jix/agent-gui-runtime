from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable

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
    screen_index = _screen_reading_index(request.screen_reading)

    for element in request.page_structure.elements:
        screen_evidence = _screen_evidence_for_element(element, screen_index)
        breakdown, reasons, eligible = _score_element(
            element,
            goal=request.goal,
            state_hint=request.state_hint,
            screen_evidence=screen_evidence,
        )
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

    ranked.sort(
        key=lambda item: (
            item.score,
            item.score_breakdown.text_similarity,
            item.score_breakdown.screen_reading_score,
            item.element.fusion_confidence,
        ),
        reverse=True,
    )
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
            "screen_reading_used": request.screen_reading is not None,
            "screen_reading_matched_count": len(
                [
                    item
                    for item in [*ranked, *rejected]
                    if item.score_breakdown.screen_reading_score > 0
                ]
            ),
        },
    )


def _score_element(
    element: PageElement,
    *,
    goal: str,
    state_hint: str | None,
    screen_evidence: dict[str, Any] | None = None,
) -> tuple[ScoreBreakdown, list[str], bool]:
    policy = element.interaction_policy
    reasons: list[str] = []
    precision_visual_match = _is_precision_visual_goal_match(element, goal)
    visual_goal = _goal_requests_visual_icon(goal)
    base_text_similarity = _best_text_similarity(goal, _element_text_values(element))
    precision_text_match = _is_precision_text_goal_match(element, goal=goal, text_similarity=base_text_similarity)
    screen_text_similarity = _best_text_similarity(goal, _screen_reading_text_values(screen_evidence))
    text_similarity = max(base_text_similarity, screen_text_similarity)
    role_score = _role_score(element)
    policy_score = _policy_score(element)
    confidence_score = _confidence_score(element)
    state_score = _state_score(element, state_hint)
    screen_reading_score, screen_reasons = _screen_reading_score(goal=goal, element=element, screen_evidence=screen_evidence)
    ad_penalty = max(0.0, min(float(policy.ad_risk), 1.0))
    blocked_penalty = 1.0 if not policy.allowed and not precision_visual_match and not precision_text_match else 0.0

    if precision_visual_match:
        text_similarity = max(text_similarity, 0.92)
        role_score = max(role_score, 1.0)
        policy_score = max(policy_score, 0.75)
        reasons.append("precision_visual_target_matches_icon_goal")
    elif precision_text_match:
        text_similarity = max(text_similarity, 0.75)
        policy_score = max(policy_score, 0.6)
        reasons.append("precision_text_target_matches_goal")
    elif visual_goal and element.role not in {"icon", "icon_button", "toolbar_button"}:
        text_similarity = min(text_similarity, 0.35)
        reasons.append("text_control_does_not_satisfy_icon_goal")

    if screen_text_similarity > base_text_similarity:
        reasons.append("screen_reading_text_match")
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
    reasons.extend(screen_reasons)

    breakdown = ScoreBreakdown(
        text_similarity=text_similarity,
        role_score=role_score,
        policy_score=policy_score,
        confidence_score=confidence_score,
        state_score=state_score,
        screen_reading_score=screen_reading_score,
        ad_penalty=ad_penalty,
        blocked_penalty=blocked_penalty,
    )
    eligible = (bool(policy.allowed) or precision_visual_match or precision_text_match) and element.interaction_type in SUPPORTED_INTERACTIONS and breakdown.total() >= 0.18
    if not eligible and "low_candidate_score" not in reasons and bool(policy.allowed):
        reasons.append("low_candidate_score")
    return breakdown, _unique(reasons), eligible


def _goal_requests_visual_icon(goal: str) -> bool:
    normalized = _normalize_text(goal)
    if any(
        hint in normalized
        for hint in (
            "\u5173\u95ed\u7a97\u53e3",
            "\u5173\u95ed\u6309\u94ae",
            "close window",
            "close button",
            "x button",
        )
    ):
        return True
    hints = ("图标", "放大镜", "箭头", "返回键", "icon", "magnifying", "arrow", "toolbar glyph")
    return any(hint in normalized for hint in hints)


def _is_precision_visual_goal_match(element: PageElement, goal: str) -> bool:
    return element.interaction_policy.zone_type == "precise_visual_target" and _goal_requests_visual_icon(goal)


def _is_precision_text_goal_match(element: PageElement, *, goal: str, text_similarity: float) -> bool:
    if element.interaction_policy.zone_type != "precise_text_target":
        return False
    if text_similarity >= 0.75:
        return True
    normalized_goal = _normalize_text(goal)
    normalized_element = " ".join(_normalize_text(value) for value in _element_text_values(element))
    named_tokens = re.findall(r"[a-z0-9]{3,}", normalized_goal)
    return any(token in normalized_element for token in named_tokens)


def _element_text_values(element: PageElement) -> list[str]:
    return [
        element.label,
        element.text,
        element.description,
        *element.possible_destinations,
        element.role,
        element.interaction_type,
    ]


def _screen_reading_text_values(screen_evidence: dict[str, Any] | None) -> list[str]:
    if not screen_evidence:
        return []
    values: list[str] = []
    ui_element = screen_evidence.get("ui_element")
    if isinstance(ui_element, dict):
        values.extend(
            [
                str(ui_element.get("label") or ""),
                str(ui_element.get("description") or ""),
                str(ui_element.get("role_guess") or ""),
                str(ui_element.get("type") or ""),
            ]
        )
        uia_match = ((ui_element.get("provider_matches") or {}).get("uia") or {})
        if isinstance(uia_match, dict):
            values.extend(
                [
                    str(uia_match.get("name") or ""),
                    str(uia_match.get("control_type") or ""),
                    str(uia_match.get("automation_id") or ""),
                ]
            )
    icon_candidate = screen_evidence.get("icon_candidate")
    if isinstance(icon_candidate, dict):
        uia_match = icon_candidate.get("uia_match") or {}
        if isinstance(uia_match, dict):
            values.append(str(uia_match.get("name") or ""))
    return values


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


def _screen_reading_score(
    *,
    goal: str,
    element: PageElement,
    screen_evidence: dict[str, Any] | None,
) -> tuple[float, list[str]]:
    if not screen_evidence:
        return 0.0, []
    score = 0.0
    reasons: list[str] = []
    ui_element = screen_evidence.get("ui_element")
    uia_match: dict[str, Any] | None = None
    if isinstance(ui_element, dict):
        raw_match = ((ui_element.get("provider_matches") or {}).get("uia") or None)
        if isinstance(raw_match, dict):
            uia_match = raw_match
    icon_candidate = screen_evidence.get("icon_candidate")
    if uia_match is None and isinstance(icon_candidate, dict):
        raw_icon_uia = icon_candidate.get("uia_match")
        if isinstance(raw_icon_uia, dict):
            uia_match = raw_icon_uia

    if uia_match is not None:
        if uia_match.get("visible") is not False and uia_match.get("enabled") is not False:
            uia_score = max(0.0, min(float(uia_match.get("score") or 0.0), 1.0))
            score += 0.62 + (uia_score * 0.18)
            reasons.append("screen_reading_uia_match")
            if _best_text_similarity(goal, [str(uia_match.get("name") or "")]) >= 0.75:
                score += 0.15
                reasons.append("screen_reading_uia_goal_name_match")
            if element.interaction_type == "click" and "Invoke" in list(uia_match.get("patterns") or []):
                score += 0.05
                reasons.append("screen_reading_uia_invoke_pattern")

    if isinstance(icon_candidate, dict) and icon_candidate.get("uia_match"):
        score += 0.08
        reasons.append("screen_reading_icon_uia_match")

    return round(max(0.0, min(score, 1.0)), 4), _unique(reasons)


def _screen_reading_index(screen_reading: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(screen_reading, dict):
        return {}
    ui_elements = screen_reading.get("ui_elements") or (screen_reading.get("ui") or {}).get("elements") or []
    icon_candidates = (screen_reading.get("ui") or {}).get("icon_candidates") or []
    indexed: dict[str, dict[str, Any]] = {}
    for item in ui_elements:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        indexed.setdefault(str(item["id"]), {})["ui_element"] = item
    for item in icon_candidates:
        if not isinstance(item, dict) or not item.get("element_id"):
            continue
        indexed.setdefault(str(item["element_id"]), {})["icon_candidate"] = item
    return indexed


def _screen_evidence_for_element(element: PageElement, screen_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    evidence = screen_index.get(element.element_id)
    return evidence if evidence else None


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
