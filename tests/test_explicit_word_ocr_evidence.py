"""独立实机发现：邻词或截断整行不能证明指定单词的位置。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from PIL import Image

from app.api import vision
from app.operation.recognition.schemas import LocalGroundingCandidateResult
from app.vision.schemas import ImageSize


@pytest.mark.parametrize("observed", ["VikipediaDur", "Wikipedia", "Wikipedia Dunedin"])
def test_neighbor_or_line_box_is_not_word_corroboration(tmp_path, monkeypatch, observed):
    goal = "Double click the word Dunedin inside the Google search input box"
    path = tmp_path / "frame.png"
    Image.new("RGB", (2560, 1400)).save(path)
    point = {"x": 287, "y": 128}
    candidate = vision._recognition_candidate_from_vista_direct(
        goal=goal, point=point, image_size=ImageSize(width=2560, height=1400), bbox_size=48)
    local = LocalGroundingCandidateResult(
        candidate_id=candidate.candidate_id, element_id=candidate.element_id,
        status="grounded", crop_path=None,
        crop_bbox={"x": 239, "y": 80, "width": 96, "height": 96},
        refined_click_point=point, coordinate_source="local_ocr_text_center",
        confidence=.95, matched_text=observed,
        matched_text_bbox={"x": 0, "y": 43, "width": 95, "height": 18},
        reasons=["matched_local_ocr_text", "mapped_crop_text_center_to_full_image"])
    monkeypatch.setattr(vision, "run_local_grounding", lambda request: SimpleNamespace(results=[deepcopy(local)]))
    result = vision._corroborate_vista_direct_point(
        image_path=path, goal=goal, candidate=candidate, point=point, app_name="word-test")
    assert result.status == "unverified"
    assert result.confidence == 0
    assert result.coordinate_source == "vista_point_v1_unverified"
    assert result.refined_click_point == point
    assert result.matched_text == observed
    assert "word_target_requires_exact_text_bbox" in result.reasons
    assert "vista_point_matches_local_ocr" not in result.reasons
    assert candidate.element.evidence["local_ocr_target_match"]["full_target_identity_verified"] is False


def test_exact_word_box_still_refines_point(tmp_path, monkeypatch):
    goal = "Double click the word Dunedin inside the search input"
    path = tmp_path / "frame.png"
    Image.new("RGB", (2560, 1400)).save(path)
    point = {"x": 287, "y": 128}
    candidate = vision._recognition_candidate_from_vista_direct(
        goal=goal, point=point, image_size=ImageSize(width=2560, height=1400), bbox_size=48)
    local = LocalGroundingCandidateResult(
        candidate_id=candidate.candidate_id, element_id=candidate.element_id,
        status="grounded", crop_path=None,
        crop_bbox={"x": 239, "y": 80, "width": 256, "height": 96},
        refined_click_point=point, coordinate_source="local_ocr_text_center",
        confidence=.95, matched_text="Dunedin",
        matched_text_bbox={"x": 80, "y": 43, "width": 58, "height": 18},
        reasons=["matched_local_ocr_text", "mapped_crop_text_center_to_full_image"])
    monkeypatch.setattr(vision, "run_local_grounding", lambda request: SimpleNamespace(results=[deepcopy(local)]))
    result = vision._corroborate_vista_direct_point(
        image_path=path, goal=goal, candidate=candidate, point=point, app_name="word-test")
    assert result.status == "grounded"
    assert result.coordinate_source == "local_ocr_text_center"
    assert result.refined_click_point == {"x": 348, "y": 132}
    assert candidate.refined_bbox == {"x": 319, "y": 123, "w": 58, "h": 18}


@pytest.mark.parametrize('goal', [
    'Double click the word Dunedin inside the search input',
    'Double-click the word Dunedin at the end of the second line Wikipedia Dunedin to select that word',
])
def test_word_path_uses_independent_word_boxes_in_wider_crop(tmp_path, monkeypatch, goal):
    from app.core.runtime_artifacts import pinned_runtime_output_root
    from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch
    path = tmp_path / "frame.png"
    Image.new("RGB", (2560, 1400)).save(path)
    point = {"x": 287, "y": 128}
    candidate = vision._recognition_candidate_from_vista_direct(
        goal=goal, point=point, image_size=ImageSize(width=2560, height=1400), bbox_size=48)
    calls = []
    def scan_words(crop_path):
        with Image.open(crop_path) as crop:
            calls.append(crop.size)
        return OCRResult(image_path=crop_path, matches=[
            OCRTextMatch("Wikipedia", .99, OCRBoundingBox(110, 43, 65, 18)),
            OCRTextMatch("Dunedin", .99, OCRBoundingBox(183, 43, 58, 18))],
            metadata={"granularity": "word"})
    def no_line_scan(_path):
        pytest.fail("Word localization must not request whole-line OCR")
    monkeypatch.setattr(vision.ocr_service, "scan_words", scan_words, raising=False)
    monkeypatch.setattr(vision.ocr_service, "scan_image", no_line_scan)
    with pinned_runtime_output_root(tmp_path / "output"):
        result = vision._corroborate_vista_direct_point(
            image_path=path, goal=goal, candidate=candidate, point=point, app_name="word-test")
    assert calls == [(320, 96)]
    assert result.crop_bbox == {"x": 127, "y": 80, "w": 320, "h": 96}
    assert result.matched_text == "Dunedin"
    assert result.refined_click_point == {"x": 339, "y": 132}
    assert result.coordinate_source == "local_ocr_text_center"


@pytest.mark.parametrize("matches", [["Dunedim"], ["Dunedin", "Dunedin"]])
def test_word_matching_cannot_substitute_fuzzy_or_duplicate_token(matches):
    from app.operation.recognition.local_grounding import _best_match
    from modules.ocr.contracts import OCRBoundingBox, OCRTextMatch
    rows = [OCRTextMatch(text, .99, OCRBoundingBox(i*100, 0, 50, 20))
            for i, text in enumerate(matches)]
    assert _best_match(rows, goal="Dunedin", candidate_texts=["Dunedim"], exact=True) is None


@pytest.mark.parametrize("x,width,expected", [(0, 2560, 0), (2540, 2560, 2240), (0, 200, 0)])
def test_wider_word_crop_stays_inside_original_image(x, width, expected):
    from app.operation.recognition.local_grounding import _crop_bbox
    from app.vision.schemas import BBox
    box = _crop_bbox(BBox(x=x, y=104, w=48, h=48), image_size=(width, 1400), padding=24, minimum_width=320)
    assert box == {"x": expected, "y": 80, "width": min(320, width), "height": 96}
