from __future__ import annotations

from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch
from modules.ocr.matching import bbox_center, find_text_matches, select_best_text_match


def _result() -> OCRResult:
    return OCRResult(
        image_path="capture.png",
        matches=[
            OCRTextMatch(text="Start", score=0.81, bbox=OCRBoundingBox(x=10, y=20, width=50, height=20)),
            OCRTextMatch(text="Start Game", score=0.95, bbox=OCRBoundingBox(x=80, y=40, width=120, height=30)),
            OCRTextMatch(text="Settings", score=0.99, bbox=OCRBoundingBox(x=20, y=80, width=80, height=20)),
        ],
    )


def test_find_text_matches_prefers_exact_match_over_partial() -> None:
    matches = find_text_matches(_result(), "Start", partial_match=True)
    assert [match.text for match in matches] == ["Start", "Start Game"]


def test_select_best_text_match_returns_highest_ranked_match() -> None:
    selected = select_best_text_match(_result(), "start game", partial_match=False)
    assert selected is not None
    assert selected.text == "Start Game"


def test_bbox_center_returns_middle_of_box() -> None:
    center = bbox_center(OCRBoundingBox(x=10, y=20, width=11, height=21))
    assert center == {"x": 16, "y": 30}
