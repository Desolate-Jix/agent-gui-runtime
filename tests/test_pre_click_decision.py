from __future__ import annotations

from app.operation.page_structure.schemas import InteractionPolicy, PageElement, VerificationHints
from app.operation.recognition import (
    CandidateRankResult,
    LocalGroundingCandidateResult,
    LocalGroundingResult,
    RecognitionCandidate,
    ScoreBreakdown,
    decide_pre_click,
)
from app.vision.schemas import BBox


def _candidate(
    *,
    candidate_id: str = "candidate_element_start",
    label: str = "Start detection",
    score: float = 0.8,
    text_similarity: float = 1.0,
    allowed: bool = True,
    ad_risk: float = 0.0,
    zone_type: str = "test_module",
    eligible: bool | None = None,
    refined_bbox: dict[str, int] | None = None,
) -> RecognitionCandidate:
    element = PageElement(
        element_id="element_start",
        label=label,
        role="button",
        interaction_type="click",
        description=f"{label} button",
        text=label,
        bbox=BBox(x=100, y=80, w=140, h=80),
        semantic_bbox=BBox(x=100, y=80, w=140, h=80),
        click_point={"x": 170, "y": 120},
        click_strategy="semantic_bbox_center",
        possible_destinations=[],
        verification_hints=VerificationHints(expected_changes=["content_change"], target_scope="local"),
        interaction_policy=InteractionPolicy(allowed=allowed, zone_type=zone_type, priority="high", ad_risk=ad_risk),
        fusion_confidence=0.9,
        coordinate_confidence="high",
        memory_key="memory:start",
        sources=["test"],
    )
    return RecognitionCandidate(
        candidate_id=candidate_id,
        rank=1,
        element_id=element.element_id,
        label=element.label,
        role=element.role,
        text=element.text,
        score=score,
        eligible=allowed if eligible is None else eligible,
        reasons=[],
        score_breakdown=ScoreBreakdown(text_similarity=text_similarity),
        element=element,
        refined_bbox=refined_bbox,
        bbox_refine_reason="test_refined_bbox" if refined_bbox else None,
    )


def _rank_result(candidate: RecognitionCandidate, *, margin: float | None = 0.2) -> CandidateRankResult:
    return CandidateRankResult(
        goal="click start detection",
        candidates=[candidate],
        recommended_candidate_id=candidate.candidate_id,
        margin_to_second=margin,
    )


def _grounding(
    *,
    candidate_id: str = "candidate_element_start",
    matched_text: str = "Start detection",
    point: dict[str, int] | None = None,
    status: str = "grounded",
) -> LocalGroundingResult:
    return LocalGroundingResult(
        goal="click start detection",
        results=[
            LocalGroundingCandidateResult(
                candidate_id=candidate_id,
                element_id="element_start",
                status=status,
                crop_path="crop.png",
                crop_bbox={"x": 80, "y": 60, "width": 180, "height": 120},
                refined_click_point=point or {"x": 170, "y": 120},
                coordinate_source="local_ocr_text_center",
                confidence=0.9,
                matched_text=matched_text,
                matched_text_bbox={"x": 40, "y": 40, "width": 80, "height": 16},
            )
        ],
    )


def test_pre_click_decision_allows_grounded_matching_candidate() -> None:
    candidate = _candidate()

    result = decide_pre_click(
        goal="click start detection",
        candidates=_rank_result(candidate),
        grounding=_grounding(),
    )

    assert result.contract_version == "pre_click_decision_v1"
    assert result.allowed is True
    assert result.selected_candidate_id == "candidate_element_start"
    assert result.selected_click_point == {"x": 170, "y": 120}
    assert "pre_click_candidate_allowed" in result.reasons


def test_pre_click_decision_rejects_local_ocr_text_mismatch() -> None:
    candidate = _candidate()

    result = decide_pre_click(
        goal="click start detection",
        candidates=_rank_result(candidate),
        grounding=_grounding(matched_text="A☆"),
    )

    assert result.allowed is False
    assert "local_ocr_text_mismatch" in result.candidate_decisions[0].reasons


def test_pre_click_decision_rejects_candidate_that_matches_local_ocr_but_not_goal() -> None:
    candidate = _candidate(text_similarity=0.4)

    result = decide_pre_click(
        goal="click settings",
        candidates=_rank_result(candidate),
        grounding=_grounding(matched_text="Start detection"),
    )

    assert result.allowed is False
    assert "candidate_goal_text_mismatch" in result.candidate_decisions[0].reasons


def test_pre_click_decision_allows_short_label_when_goal_mentions_it_in_long_instruction() -> None:
    candidate = _candidate(label="Continue", text_similarity=0.35)

    result = decide_pre_click(
        goal=(
            "Click only the visible SEEK application form Continue or Save and continue button to move to the next "
            "application step. Do not click Review and submit, Submit, Send application, or Complete application."
        ),
        candidates=_rank_result(candidate),
        grounding=_grounding(matched_text="Continue"),
    )

    assert result.allowed is True
    assert "goal_explicitly_mentions_candidate_label" in result.candidate_decisions[0].reasons
    assert "candidate_goal_text_mismatch" not in result.candidate_decisions[0].reasons


def test_pre_click_decision_does_not_treat_negated_label_as_positive_goal_match() -> None:
    candidate = _candidate(label="Submit", text_similarity=0.35)

    result = decide_pre_click(
        goal="Click Continue to move to the next step. Do not click Submit.",
        candidates=_rank_result(candidate),
        grounding=_grounding(matched_text="Submit"),
    )

    assert result.allowed is False
    assert "candidate_goal_text_mismatch" in result.candidate_decisions[0].reasons
    assert "goal_explicitly_mentions_candidate_label" not in result.candidate_decisions[0].reasons


def test_pre_click_decision_rejects_refined_point_outside_candidate_bbox() -> None:
    candidate = _candidate()

    result = decide_pre_click(
        goal="click start detection",
        candidates=_rank_result(candidate),
        grounding=_grounding(point={"x": 20, "y": 20}),
    )

    assert result.allowed is False
    assert "refined_point_outside_candidate_bbox" in result.candidate_decisions[0].reasons


def test_pre_click_decision_uses_button_bbox_safe_center_when_grounding_point_near_edge() -> None:
    candidate = _candidate()

    result = decide_pre_click(
        goal="click start detection",
        candidates=_rank_result(candidate),
        grounding=_grounding(point={"x": 101, "y": 81}),
    )

    decision = result.candidate_decisions[0]
    assert result.allowed is True
    assert result.selected_click_point == {"x": 170, "y": 120}
    assert decision.click_point == {"x": 170, "y": 120}
    assert "bbox_safe_center_used" in decision.reasons
    assert decision.resolved_click_point["contract_version"] == "resolved_click_point_v1"
    assert decision.resolved_click_point["raw_model_point"] == {"x": 101, "y": 81}
    assert decision.resolved_click_point["chosen_point"] == {"x": 170, "y": 120}
    assert decision.resolved_click_point["chosen_point_source"] == "bbox_safe_center"
    assert decision.resolved_click_point["adjustment_reason"] == "raw_model_point_near_edge"


def test_pre_click_decision_does_not_safe_center_grounding_point_outside_bbox() -> None:
    candidate = _candidate()

    result = decide_pre_click(
        goal="click start detection",
        candidates=_rank_result(candidate),
        grounding=_grounding(point={"x": 98, "y": 81}),
    )

    decision = result.candidate_decisions[0]
    assert result.allowed is False
    assert decision.click_point == {"x": 98, "y": 81}
    assert "bbox_safe_center_used" not in decision.reasons
    assert "refined_point_outside_candidate_bbox" in decision.reasons
    assert decision.resolved_click_point["chosen_point_source"] == "raw_grounding_point"
    assert decision.resolved_click_point["raw_inside_bbox"] is False


def test_pre_click_decision_keeps_non_button_grounding_point_when_near_edge() -> None:
    candidate = _candidate()
    candidate.role = "link"
    candidate.element.role = "link"

    result = decide_pre_click(
        goal="click start detection",
        candidates=_rank_result(candidate),
        grounding=_grounding(point={"x": 101, "y": 81}),
    )

    decision = result.candidate_decisions[0]
    assert result.allowed is True
    assert result.selected_click_point == {"x": 101, "y": 81}
    assert "bbox_safe_center_used" not in decision.reasons
    assert decision.resolved_click_point["chosen_point_source"] == "raw_grounding_point"


def test_pre_click_decision_uses_refined_bbox_when_available() -> None:
    candidate = _candidate(refined_bbox={"x": 130, "y": 94, "w": 60, "h": 24})

    result = decide_pre_click(
        goal="click start detection",
        candidates=_rank_result(candidate),
        grounding=_grounding(point={"x": 230, "y": 150}),
    )

    assert result.allowed is False
    assert "refined_point_outside_candidate_bbox" in result.candidate_decisions[0].reasons


def test_pre_click_decision_rejects_ad_like_candidate() -> None:
    candidate = _candidate(allowed=False, ad_risk=0.9, zone_type="ad_candidate")

    result = decide_pre_click(
        goal="download cpu-z",
        candidates=_rank_result(candidate),
        grounding=_grounding(matched_text="Download CPU-Z"),
    )

    assert result.allowed is False
    assert "ad_like_candidate" in result.candidate_decisions[0].reasons


def test_pre_click_decision_removes_passed_reason_when_margin_later_rejects() -> None:
    top = _candidate(candidate_id="candidate_top", score=0.8)
    second = _candidate(candidate_id="candidate_second", score=0.79)
    rank_result = CandidateRankResult(
        goal="click start detection",
        candidates=[top, second],
        recommended_candidate_id=top.candidate_id,
        margin_to_second=0.01,
    )
    grounding = LocalGroundingResult(
        goal="click start detection",
        results=[
            _grounding(candidate_id="candidate_top").results[0],
            _grounding(candidate_id="candidate_second").results[0],
        ],
    )

    result = decide_pre_click(
        goal="click start detection",
        candidates=rank_result,
        grounding=grounding,
    )

    assert result.allowed is False
    assert "top_candidate_margin_too_small" in result.candidate_decisions[0].reasons
    assert "pre_click_checks_passed" not in result.candidate_decisions[0].reasons


def test_pre_click_decision_can_allow_reviewed_low_margin_grounded_candidate() -> None:
    top = _candidate(candidate_id="candidate_top", score=0.8)
    second = _candidate(candidate_id="candidate_second", score=0.79)
    rank_result = CandidateRankResult(
        goal="click start detection",
        candidates=[top, second],
        recommended_candidate_id=top.candidate_id,
        margin_to_second=0.01,
    )
    grounding = LocalGroundingResult(
        goal="click start detection",
        results=[
            _grounding(candidate_id="candidate_top").results[0],
            _grounding(candidate_id="candidate_second").results[0],
        ],
    )

    result = decide_pre_click(
        goal="click start detection",
        candidates=rank_result,
        grounding=grounding,
        allow_low_margin_when_grounded=True,
    )

    assert result.allowed is True
    assert result.selected_candidate_id == "candidate_top"
    assert "top_candidate_margin_reviewed_override" in result.reasons
    assert "top_candidate_margin_reviewed_override" in result.candidate_decisions[0].reasons
    assert result.summary["low_margin_reviewed_override_used"] is True


def test_pre_click_decision_reviewed_low_margin_does_not_allow_hard_blocker() -> None:
    top = _candidate(candidate_id="candidate_top", score=0.8)
    second = _candidate(candidate_id="candidate_second", score=0.79)
    rank_result = CandidateRankResult(
        goal="click start detection",
        candidates=[top, second],
        recommended_candidate_id=top.candidate_id,
        margin_to_second=0.01,
    )
    grounding = LocalGroundingResult(
        goal="click start detection",
        results=[
            _grounding(candidate_id="candidate_top", matched_text="Cancel").results[0],
            _grounding(candidate_id="candidate_second").results[0],
        ],
    )

    result = decide_pre_click(
        goal="click start detection",
        candidates=rank_result,
        grounding=grounding,
        allow_low_margin_when_grounded=True,
    )

    assert result.allowed is False
    assert "local_ocr_text_mismatch" in result.candidate_decisions[0].reasons
    assert "top_candidate_margin_too_small" in result.candidate_decisions[0].reasons


def test_pre_click_decision_does_not_fall_back_from_precise_icon_to_nearby_text() -> None:
    icon = _candidate(
        candidate_id="candidate_icon",
        score=0.93,
        allowed=False,
        eligible=True,
        zone_type="precise_visual_target",
    )
    text_control = _candidate(candidate_id="candidate_text", score=0.75)
    rank_result = CandidateRankResult(
        goal="定位搜索游戏左侧的放大镜图标",
        candidates=[icon, text_control],
        recommended_candidate_id=icon.candidate_id,
        margin_to_second=0.18,
    )
    grounding = LocalGroundingResult(
        goal=rank_result.goal,
        results=[
            _grounding(candidate_id="candidate_icon").results[0],
            _grounding(candidate_id="candidate_text").results[0],
        ],
    )

    result = decide_pre_click(goal=rank_result.goal, candidates=rank_result, grounding=grounding)

    assert result.allowed is False
    assert result.selected_click_point is None
    assert "precision_visual_target_requires_confirmation" in result.candidate_decisions[0].reasons
    assert "higher_ranked_precision_visual_target_requires_confirmation" in result.candidate_decisions[1].reasons


def test_pre_click_decision_requires_confirmation_for_precise_text_card() -> None:
    card = _candidate(
        candidate_id="candidate_serato",
        score=0.9,
        text_similarity=0.9,
        allowed=False,
        eligible=True,
        zone_type="precise_text_target",
    )

    result = decide_pre_click(
        goal="\u6253\u5f00serato\u7684\u804c\u4e1a\u754c\u9762",
        candidates=_rank_result(card),
        grounding=_grounding(candidate_id="candidate_serato", matched_text="serato"),
    )

    assert result.allowed is False
    assert result.selected_click_point is None
    assert "precision_text_target_requires_confirmation" in result.candidate_decisions[0].reasons


def test_pre_click_decision_allows_ranker_verified_precise_text_button() -> None:
    button = _candidate(
        candidate_id="candidate_more",
        score=0.82,
        text_similarity=0.9,
        allowed=False,
        eligible=True,
        zone_type="precise_text_target",
    )
    button.reasons = ["precision_text_target_matches_goal", "strong_goal_text_match", "supported_interaction"]
    button.label = "See more headlines and perspectives"
    button.text = button.label
    button.element.label = button.label
    button.element.text = button.label
    button.element.description = button.label

    result = decide_pre_click(
        goal="See more headlines and perspectives",
        candidates=_rank_result(button),
        grounding=_grounding(candidate_id="candidate_more", matched_text="See more headlines and perspectives"),
    )

    assert result.allowed is True
    assert result.selected_candidate_id == "candidate_more"
    assert "precision_text_target_verified_by_local_ocr" in result.candidate_decisions[0].reasons
