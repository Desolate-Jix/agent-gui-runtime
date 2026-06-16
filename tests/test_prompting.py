from __future__ import annotations

from app.vision.prompting import build_region_analysis_prompt
from app.vision.schemas import ImageSize, VisionAnalyzeRequest


def test_precise_target_prompt_pairs_adjacent_text_and_icon_without_overlap() -> None:
    prompt = build_region_analysis_prompt(
        VisionAnalyzeRequest(
            image_path="capture.png",
            task="click_target",
            goal="add friend icon next to Add Friend",
            app_name="demo",
        ),
        ImageSize(width=640, height=480),
    )

    assert "paired reference" in prompt
    assert "final icon bbox must not overlap the text bbox" in prompt
    assert "use the text bbox only as an anchor, boundary, and negative constraint" in prompt


def test_learn_deep_review_prompt_requests_path_graph_delta_actions() -> None:
    prompt = build_region_analysis_prompt(
        VisionAnalyzeRequest(
            image_path="capture.png",
            task="learn_deep_review",
            app_name="demo",
            metadata={
                "learn_deep_review_context": {
                    "state_id": "state_demo",
                    "candidates": [{"candidate_id": "save", "label": "Save"}],
                }
            },
        ),
        ImageSize(width=640, height=480),
    )

    assert "Learn Deep semantic review stage" in prompt
    assert "learn_deep_model_review_v1" in prompt
    assert "keep|remove|update|add" in prompt
    assert "execution still requires Locate/RecognitionPlan and pre_click_decision_v1" in prompt
    assert "state_demo" in prompt


def test_observe_prompt_includes_strict_json_validity_rules() -> None:
    prompt = build_region_analysis_prompt(
        VisionAnalyzeRequest(
            image_path="capture.png",
            task="observe_screen",
            app_name="demo",
        ),
        ImageSize(width=640, height=480),
    )

    assert "parseable JSON" in prompt
    assert "comma separator" in prompt
    assert "no trailing commas" in prompt
