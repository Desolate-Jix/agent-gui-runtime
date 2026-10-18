"""动作类别相同不是明确目标身份；保留原始排序分差与重复目标拒绝。"""

from copy import deepcopy

import pytest

from app.operation.page_structure.schemas import PageStructure
from app.operation.recognition.candidate_ranker import rank_candidates
from app.operation.recognition.decision import decide_pre_click
from app.operation.recognition.schemas import CandidateRankRequest, LocalGroundingCandidateResult, LocalGroundingResult
from app.operation.screen_inventory.builder import build_screen_inventory
from app.vision.schemas import ImageSize


def _request(goal, controls, *, top_k=10, target=None):
    uia_controls = [{"control_id": f"control-{index}", "name": label,
        "control_type": {"button": "Button", "link": "Hyperlink", "input": "Edit"}[role],
        "bbox": {"x": 40, "y": 40 + index * 60, "w": 200, "h": 36},
        "enabled": True, "visible": True, "patterns": ["Value"] if role == "input" else ["Invoke"]}
        for index, (label, role) in enumerate(controls)]
    screen = {"contract_version": "screen_reading_v1", "image_size": {"width": 600, "height": 800},
        "source_layers": {"windows_uia": {"status": "ok", "controls": uia_controls}},
        "texts": [], "ui_elements": []}
    screen["screen_inventory"] = build_screen_inventory(screen, goal=goal)
    return CandidateRankRequest(goal=goal, top_k=top_k, control_target=target, screen_reading=screen,
        page_structure=PageStructure(image_size=ImageSize(width=600, height=800),
            screen_summary="synthetic current actions", state_guess=None, elements=[], texts=[]))


@pytest.mark.parametrize("goal,decoys", [
    ("Atlas Search", [("How Search works", "link"), ("地址和搜索栏", "input"), ("搜索标签页", "button")]),
    ("Save draft", [("Saved searches", "button"), ("How to save", "link"), ("Autosave status", "link")]),
    ("Continue setup", [("Next chapter", "link"), ("Continue reading", "button"), ("Next update notes", "link")]),
    ("Apply changes", [("How to apply filters", "link"), ("Apply coupon", "button")]),
    ("Send feedback", [("Confirm payment", "button"), ("Submit report", "button")]),
    ("地图 搜索", [("搜索标签页", "button"), ("地址和搜索栏", "input")]),
])
def test_related_action_terms_cannot_promote_unrelated_labels_to_exact_identity(goal, decoys):
    request = _request(goal, [(goal, "button"), *decoys])
    original_screen = deepcopy(request.screen_reading)
    ranked = rank_candidates(request)
    selected = next(candidate for candidate in ranked.candidates if candidate.label == goal)
    assert "explicit_action_target_match" in selected.reasons
    assert selected.score_breakdown.text_similarity == 1.0
    for candidate in ranked.candidates:
        if candidate is selected:
            continue
        assert "explicit_action_target_match" not in candidate.reasons
        assert candidate.score_breakdown.text_similarity < 0.95
    assert request.screen_reading == original_screen


def _ground_selected(ranked):
    candidate = ranked.candidates[0]
    box = candidate.element.bbox.to_dict()
    return LocalGroundingResult(goal=ranked.goal, recommended_candidate_id=candidate.candidate_id,
        results=[LocalGroundingCandidateResult(candidate_id=candidate.candidate_id, element_id=candidate.element_id,
            status="grounded", confidence=0.82, crop_bbox=box, crop_path="synthetic-current-crop.png",
            matched_text=candidate.label, matched_text_bbox=box,
            refined_click_point=dict(candidate.element.click_point),
            coordinate_source="vista_point_v1_corroborated_by_local_ocr", reasons=["matched_local_ocr_text"])])


def test_exact_search_identity_gets_real_margin_without_overriding_gate():
    ranked = rank_candidates(_request("Atlas Search", [("Atlas Search", "button"),
        ("How Search works", "link"), ("地址和搜索栏", "input"), ("搜索标签页", "button")]))
    decision = decide_pre_click(goal=ranked.goal, candidates=ranked, grounding=_ground_selected(ranked))
    assert decision.allowed is True
    assert ranked.margin_to_second >= 0.06
    assert "top_candidate_margin_reviewed_override" not in decision.reasons
    assert decision.selected_click_point == ranked.candidates[0].element.click_point


@pytest.mark.parametrize("goal", ["Open Settings", "View details", "查看详情"])
def test_non_action_keyword_goals_keep_exact_identity_and_order(goal):
    ranked = rank_candidates(_request(goal, [("Search history", "link"), (goal, "button"), ("Send report", "button")]))
    assert ranked.candidates[0].label == goal
    assert ranked.candidates[0].score_breakdown.text_similarity == 1.0
    assert "explicit_action_target_match" not in ranked.candidates[0].reasons


@pytest.mark.parametrize("goal,label", [("Click the Search button", "Search"),
    ("Open the Apply for this job button", "Apply for this job"), ("选择 保存 按钮", "保存")])
def test_explicit_actual_labels_keep_action_promotion(goal, label):
    ranked = rank_candidates(_request(goal, [(label, "button"), ("Other settings", "button")]))
    assert ranked.candidates[0].label == label
    assert "explicit_action_target_match" in ranked.candidates[0].reasons
    assert ranked.candidates[0].score_breakdown.text_similarity >= 0.95


@pytest.mark.parametrize("source", ["description", "possible_destinations"])
def test_action_word_only_in_auxiliary_metadata_is_not_explicit_target(source):
    request = _request("Atlas Search", [("Atlas Search", "button"), ("Help", "button")])
    initial = rank_candidates(request)
    elements = [candidate.element for candidate in initial.candidates]
    help_element = next(element for element in elements if element.label == "Help")
    if source == "description":
        help_element.description = "Describes search preferences"
    else:
        help_element.possible_destinations = ["search options"]
    ranked = rank_candidates(CandidateRankRequest(goal=request.goal,
        page_structure=PageStructure(image_size=ImageSize(width=600, height=800),
            screen_summary="synthetic metadata", state_guess=None, elements=elements, texts=[])))
    help_candidate = next(candidate for candidate in ranked.candidates if candidate.label == "Help")
    assert "explicit_action_target_match" not in help_candidate.reasons
    assert help_candidate.score_breakdown.text_similarity < 0.95


def test_negated_label_cannot_be_repromoted_by_shared_action_category():
    ranked = rank_candidates(_request("Click Atlas Search; do not click Search", [("Atlas Search", "button"), ("Search", "button")]))
    negated = next(candidate for candidate in ranked.candidates if candidate.label == "Search")
    assert "goal_negates_candidate_label" in negated.reasons
    assert "explicit_action_target_match" not in negated.reasons
    assert negated.score_breakdown.text_similarity <= 0.2


def test_true_same_name_actions_remain_ambiguous_with_original_margin_gate():
    ranked = rank_candidates(_request("Atlas Search", [("Atlas Search", "button"), ("Atlas Search", "button")]))
    assert len(ranked.candidates) == 2 and ranked.margin_to_second == 0.0
    decision = decide_pre_click(goal=ranked.goal, candidates=ranked, grounding=_ground_selected(ranked))
    assert decision.allowed is False
    assert "top_candidate_margin_too_small" in decision.reasons


def test_explicit_control_target_duplicate_rejection_still_precedes_top_k():
    target = {"contract_version": "recognition_control_target_v1", "label": "Atlas Search",
              "role": "button", "source_binding_sha256": "a" * 64}
    ranked = rank_candidates(_request("Atlas Search", [("Atlas Search", "button"), ("Atlas Search", "button")],
                                      top_k=1, target=target))
    assert not ranked.candidates and len(ranked.rejected) == 2
    assert all("control_target_ambiguous_before_top_k" in candidate.reasons for candidate in ranked.rejected)
