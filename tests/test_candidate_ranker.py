from __future__ import annotations

from app.page_structure.schemas import InteractionPolicy, PageElement, PageStructure, PageText, VerificationHints
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
    source_text_ids: list[str] | None = None,
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
        source_text_ids=source_text_ids or [],
    )


def _structure(elements: list[PageElement], *, texts: list[PageText] | None = None) -> PageStructure:
    return PageStructure(
        image_size=ImageSize(width=420, height=220),
        screen_summary="candidate test",
        state_guess="test_page",
        elements=elements,
        texts=texts or [],
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


def test_rank_candidates_adds_refined_bbox_from_source_text_union() -> None:
    text = PageText(
        text_id="text_start",
        text="Start detection",
        bbox=BBox(x=35, y=18, w=24, h=6),
        score=0.97,
        source="ocr",
        source_index=0,
    )
    structure = _structure(
        [_element("element_start", "Start detection", priority="high", zone_type="test_module", source_text_ids=["text_start"])],
        texts=[text],
    )

    result = rank_candidates(CandidateRankRequest(goal="click start detection", page_structure=structure, top_k=1))

    candidate = result.candidates[0]
    assert candidate.refined_bbox == {"x": 23, "y": 10, "w": 48, "h": 26}
    assert candidate.bbox_refine_reason == "goal_text_ids_union:1"
    assert "bbox_refined_from_source_text" in candidate.reasons
    assert result.to_dict()["candidates"][0]["refined_bbox"] == {"x": 23, "y": 10, "w": 48, "h": 26}


def test_rank_candidates_skips_refined_bbox_when_text_union_is_not_tighter() -> None:
    text = PageText(
        text_id="text_large",
        text="Large region",
        bbox=BBox(x=12, y=12, w=76, h=28),
        score=0.97,
        source="ocr",
        source_index=0,
    )
    structure = _structure(
        [_element("element_large", "Large region", priority="high", zone_type="test_module", source_text_ids=["text_large"])],
        texts=[text],
    )

    result = rank_candidates(CandidateRankRequest(goal="large region", page_structure=structure, top_k=1))

    candidate = result.candidates[0]
    assert candidate.refined_bbox is None
    assert candidate.bbox_refine_reason == "source_text_bbox_not_tighter"


def test_rank_candidates_refines_bbox_from_goal_matching_source_text_subset() -> None:
    structure = _structure(
        [
            _element(
                "element_double_click",
                "Double click Click here Success count",
                text="Double click Click here Success count",
                priority="high",
                zone_type="test_module",
                source_text_ids=["text_title", "text_target", "text_count"],
            )
        ],
        texts=[
            PageText(
                text_id="text_title",
                text="Double click",
                bbox=BBox(x=12, y=12, w=42, h=6),
                score=0.97,
                source="ocr",
                source_index=0,
            ),
            PageText(
                text_id="text_target",
                text="Click here",
                bbox=BBox(x=35, y=22, w=24, h=6),
                score=0.98,
                source="ocr",
                source_index=1,
            ),
            PageText(
                text_id="text_count",
                text="Success count",
                bbox=BBox(x=12, y=34, w=46, h=6),
                score=0.96,
                source="ocr",
                source_index=2,
            ),
        ],
    )

    result = rank_candidates(CandidateRankRequest(goal="click here", page_structure=structure, top_k=1))

    candidate = result.candidates[0]
    assert candidate.refined_bbox == {"x": 23, "y": 10, "w": 48, "h": 30}
    assert candidate.bbox_refine_reason == "goal_text_ids_union:1"
