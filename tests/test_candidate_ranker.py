from __future__ import annotations

from app.page_structure.schemas import InteractionPolicy, PageElement, PageStructure, VerificationHints
from app.recognition import CandidateRankRequest, rank_candidates
from app.vision.schemas import BBox, ImageSize


def _element(
    element_id: str,
    label: str,
    *,
    text: str = "",
    role: str = "button",
    allowed: bool = True,
    zone_type: str = "general_action",
    priority: str = "low",
    ad_risk: float = 0.0,
    fusion_confidence: float = 0.8,
    coordinate_confidence: str = "high",
) -> PageElement:
    return PageElement(
        element_id=element_id,
        label=label,
        role=role,
        interaction_type="click",
        description=f"{label} control",
        text=text or label,
        bbox=BBox(x=10, y=10, w=80, h=32),
        semantic_bbox=BBox(x=10, y=10, w=80, h=32),
        click_point={"x": 50, "y": 26},
        click_strategy="ocr_text_center",
        possible_destinations=[],
        verification_hints=VerificationHints(expected_changes=["content_change"], target_scope="local"),
        interaction_policy=InteractionPolicy(
            allowed=allowed,
            zone_type=zone_type,
            priority=priority,
            ad_risk=ad_risk,
            reasons=[],
        ),
        fusion_confidence=fusion_confidence,
        coordinate_confidence=coordinate_confidence,
        memory_key=f"memory:{element_id}",
        sources=["test"],
    )


def _structure(elements: list[PageElement]) -> PageStructure:
    return PageStructure(
        image_size=ImageSize(width=420, height=220),
        screen_summary="candidate test",
        state_guess="test_page",
        elements=elements,
    )


def test_rank_candidates_puts_best_text_match_first() -> None:
    structure = _structure(
        [
            _element("element_settings", "Settings", priority="medium", zone_type="nav_control"),
            _element("element_start", "Start detection", text="Click start detection", priority="high", zone_type="test_module"),
        ]
    )

    result = rank_candidates(CandidateRankRequest(goal="click start detection", page_structure=structure, top_k=3))

    assert result.contract_version == "candidate_rank_v1"
    assert result.recommended_candidate_id == "candidate_element_start"
    assert result.candidates[0].element_id == "element_start"
    assert result.candidates[0].eligible is True
    assert "strong_goal_text_match" in result.candidates[0].reasons
    assert result.summary["eligible_count"] == 2


def test_rank_candidates_rejects_blocked_ad_like_element() -> None:
    structure = _structure(
        [
            _element(
                "element_ad",
                "Download CPU-Z",
                allowed=False,
                zone_type="ad_candidate",
                priority="blocked",
                ad_risk=0.9,
            ),
            _element("element_start", "Start detection", text="Click start detection", priority="high", zone_type="test_module"),
        ]
    )

    result = rank_candidates(CandidateRankRequest(goal="download cpu-z", page_structure=structure, top_k=5))

    assert result.candidates[0].element_id == "element_start"
    assert result.rejected[0].element_id == "element_ad"
    assert result.rejected[0].eligible is False
    assert "blocked_by_interaction_policy" in result.rejected[0].reasons
    assert result.summary["rejected_count"] == 1


def test_rank_candidates_respects_top_k_and_reports_margin() -> None:
    structure = _structure(
        [
            _element("element_one", "Start detection", text="Start detection", priority="high", zone_type="test_module"),
            _element("element_two", "Start", text="Start", priority="medium", zone_type="test_module"),
            _element("element_three", "Help", priority="low", zone_type="general_action"),
        ]
    )

    result = rank_candidates(CandidateRankRequest(goal="start detection", page_structure=structure, top_k=2))

    assert len(result.candidates) == 2
    assert result.summary["returned_count"] == 2
    assert result.margin_to_second is not None
    assert result.margin_to_second >= 0.0
    assert result.to_dict()["candidates"][0]["score_breakdown"]["total"] == result.candidates[0].score
