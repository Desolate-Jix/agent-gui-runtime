from __future__ import annotations

from app.operation.page_structure.schemas import InteractionPolicy, PageElement, PageStructure, PageText, VerificationHints
from app.operation.recognition import CandidateRankRequest, rank_candidates
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


def test_rank_candidates_does_not_promote_negated_button_labels_over_requested_radio() -> None:
    structure = _structure(
        [
            _element("element_continue", "Continue", priority="high"),
            _element("element_review", "Review and submit", priority="high"),
            _element("element_yes", "Yes", role="radio", priority="high"),
        ]
    )

    result = rank_candidates(
        CandidateRankRequest(
            goal=(
                'Click Yes for the question "Do you have at least 1-2 years of experience in web application development?" '
                "Do not click Continue, Back, Review and submit, Submit, Send application, or Complete application."
            ),
            page_structure=structure,
            top_k=3,
        )
    )

    assert result.candidates[0].element_id == "element_yes"
    assert "goal_explicitly_mentions_candidate_label" in result.candidates[0].reasons
    continue_candidate = next(item for item in result.candidates if item.element_id == "element_continue")
    assert "goal_negates_candidate_label" in continue_candidate.reasons
    assert continue_candidate.score < result.candidates[0].score


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


def test_rank_candidates_uses_screen_reading_uia_name_to_promote_candidate() -> None:
    structure = _structure(
        [
            _element("element_generic", "Generic button", priority="medium"),
            _element("element_uia_target", "Unknown control", priority="medium"),
        ]
    )
    screen_reading = {
        "contract_version": "screen_reading_v1",
        "ui_elements": [
            {
                "id": "element_uia_target",
                "label": "Unknown control",
                "description": "Control with accessibility name",
                "role_guess": "button",
                "type": "button",
                "provider_matches": {
                    "uia": {
                        "name": "点击此处测试",
                        "control_type": "Button",
                        "automation_id": None,
                        "enabled": True,
                        "visible": True,
                        "patterns": ["Invoke"],
                        "score": 0.91,
                    }
                },
            }
        ],
        "ui": {"icon_candidates": []},
    }

    result = rank_candidates(
        CandidateRankRequest(
            goal="点击此处测试",
            page_structure=structure,
            top_k=2,
            screen_reading=screen_reading,
        )
    )

    candidate = result.candidates[0]
    assert candidate.element_id == "element_uia_target"
    assert candidate.score_breakdown.screen_reading_score > 0
    assert "screen_reading_text_match" in candidate.reasons
    assert "screen_reading_uia_goal_name_match" in candidate.reasons
    assert result.summary["screen_reading_used"] is True
    assert result.summary["screen_reading_matched_count"] == 1


def test_rank_candidates_adds_screen_inventory_uia_input_candidate() -> None:
    structure = _structure([])
    screen_reading = {
        "contract_version": "screen_reading_v1",
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [
                {
                    "id": "action_uia_35_dear-alicia",
                    "label": "Dear Alicia, I am writing to apply for the Junior Java Developer position.",
                    "role": "input",
                    "action_type": "input_text",
                    "bbox": {"x": 838, "y": 1201, "w": 625, "h": 172},
                    "click_point": {"x": 1150, "y": 1287},
                    "confidence": 0.82,
                    "coordinate_confidence": "high",
                    "source": "windows_uia.controls",
                    "source_id": "uia_cover_letter",
                    "metadata": {"control_type": "Edit", "patterns": ["Value"]},
                }
            ],
            "page_elements": [],
            "cards": [],
        },
    }

    result = rank_candidates(
        CandidateRankRequest(
            goal="existing cover letter text box containing Dear Alicia",
            page_structure=structure,
            top_k=1,
            screen_reading=screen_reading,
        )
    )

    candidate = result.candidates[0]
    assert candidate.element_id == "screen_inventory_action_uia_35_dear-alicia"
    assert candidate.role == "input"
    assert candidate.element.interaction_type == "focus"
    assert candidate.element.click_point == {"x": 1150, "y": 1287}
    assert "screen_inventory_action_candidate" in candidate.reasons
    assert "screen_inventory_action_match" in candidate.reasons
    assert candidate.score_breakdown.screen_reading_score > 0
    assert result.summary["element_count"] == 0
    assert result.summary["ranked_element_count"] == 1
    assert result.summary["screen_inventory_virtual_element_count"] == 1


def test_rank_candidates_prefers_typeable_input_over_matching_field_label() -> None:
    structure = _structure([])
    screen_reading = {
        "contract_version": "screen_reading_v1",
        "screen_inventory": {
            "contract_version": "screen_inventory_v1",
            "available_actions": [
                {
                    "id": "action_uia_1_cover-letter",
                    "label": "Cover letter",
                    "role": "text",
                    "action_type": "click",
                    "bbox": {"x": 802, "y": 1023, "w": 661, "h": 20},
                    "click_point": {"x": 1132, "y": 1033},
                    "confidence": 0.82,
                    "coordinate_confidence": "high",
                    "source": "windows_uia.controls",
                    "source_id": "uia_cover_label",
                    "metadata": {"control_type": "Text", "patterns": ["Text"]},
                },
                {
                    "id": "action_uia_2_dear-alicia",
                    "label": "Dear Alicia, I am writing to apply for the Junior Java Developer position.",
                    "role": "input",
                    "action_type": "input_text",
                    "bbox": {"x": 838, "y": 1201, "w": 625, "h": 172},
                    "click_point": {"x": 1150, "y": 1287},
                    "confidence": 0.82,
                    "coordinate_confidence": "high",
                    "source": "windows_uia.controls",
                    "source_id": "uia_cover_input",
                    "metadata": {"control_type": "Edit", "patterns": ["Value"]},
                },
            ],
            "page_elements": [],
            "cards": [],
        },
    }

    result = rank_candidates(
        CandidateRankRequest(
            goal="Click the existing cover letter text box containing Dear Alicia field",
            page_structure=structure,
            top_k=2,
            screen_reading=screen_reading,
        )
    )

    assert result.candidates[0].element_id == "screen_inventory_action_uia_2_dear-alicia"
    assert result.candidates[0].role == "input"
    assert "text_entry_target_matches_field_goal" in result.candidates[0].reasons
    assert "non_typeable_label_does_not_satisfy_field_goal" in result.candidates[1].reasons


def test_rank_candidates_keeps_blocked_screen_reading_match_rejected() -> None:
    structure = _structure(
        [
            _element(
                "element_blocked",
                "Unknown control",
                allowed=False,
                zone_type="ad_candidate",
                priority="blocked",
            )
        ]
    )
    screen_reading = {
        "contract_version": "screen_reading_v1",
        "ui_elements": [
            {
                "id": "element_blocked",
                "label": "Unknown control",
                "role_guess": "button",
                "type": "button",
                "provider_matches": {
                    "uia": {
                        "name": "点击此处测试",
                        "control_type": "Button",
                        "enabled": True,
                        "visible": True,
                        "patterns": ["Invoke"],
                        "score": 0.95,
                    }
                },
            }
        ],
        "ui": {"icon_candidates": []},
    }

    result = rank_candidates(
        CandidateRankRequest(
            goal="点击此处测试",
            page_structure=structure,
            top_k=1,
            screen_reading=screen_reading,
        )
    )

    assert result.candidates == []
    assert result.rejected[0].element_id == "element_blocked"
    assert result.rejected[0].score_breakdown.screen_reading_score > 0
    assert "blocked_by_interaction_policy" in result.rejected[0].reasons


def test_rank_candidates_prefers_precise_visual_icon_over_nearby_text_for_icon_goal() -> None:
    structure = _structure(
        [
            _element(
                "element_search_icon",
                "Search Icon",
                role="icon",
                allowed=False,
                zone_type="precise_visual_target",
                priority="review",
                coordinate_confidence="medium",
            ),
            _element("element_search_text", "搜索游戏", role="input"),
        ]
    )

    result = rank_candidates(CandidateRankRequest(goal="定位搜索游戏左侧的放大镜图标", page_structure=structure, top_k=2))

    assert result.candidates[0].element_id == "element_search_icon"
    assert result.candidates[0].eligible is True
    assert "precision_visual_target_matches_icon_goal" in result.candidates[0].reasons
    assert "text_control_does_not_satisfy_icon_goal" in result.candidates[1].reasons


def test_rank_candidates_returns_precise_visual_close_button_for_chinese_close_goal() -> None:
    structure = _structure(
        [
            _element(
                "element_close",
                "close window button",
                role="button",
                allowed=False,
                zone_type="precise_visual_target",
                priority="review",
                coordinate_confidence="medium",
            )
        ]
    )

    result = rank_candidates(CandidateRankRequest(goal="\u5173\u95ed\u7a97\u53e3", page_structure=structure, top_k=1))

    assert result.candidates[0].element_id == "element_close"
    assert result.candidates[0].eligible is True
    assert "precision_visual_target_matches_icon_goal" in result.candidates[0].reasons


def test_rank_candidates_returns_matching_precise_text_card_for_review() -> None:
    structure = _structure(
        [
            _element(
                "element_serato",
                "Junior Software Engineer C++ Serato Limited",
                role="card",
                allowed=False,
                zone_type="precise_text_target",
                priority="review",
                coordinate_confidence="high",
            )
        ]
    )

    result = rank_candidates(
        CandidateRankRequest(goal="\u6253\u5f00serato\u7684\u804c\u4e1a\u754c\u9762", page_structure=structure, top_k=1)
    )

    assert result.candidates[0].element_id == "element_serato"
    assert result.candidates[0].eligible is True
    assert "precision_text_target_matches_goal" in result.candidates[0].reasons


def test_rank_candidates_rejects_unmatched_precise_text_card() -> None:
    structure = _structure(
        [
            _element(
                "element_serato",
                "Junior Software Engineer C++ Serato Limited",
                role="card",
                allowed=False,
                zone_type="precise_text_target",
                priority="review",
            )
        ]
    )

    result = rank_candidates(CandidateRankRequest(goal="open blackpepper role", page_structure=structure, top_k=1))

    assert result.candidates == []
    assert result.rejected[0].element_id == "element_serato"
