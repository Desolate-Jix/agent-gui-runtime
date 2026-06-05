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
