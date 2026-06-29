from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.operation.page_structure.schemas import InteractionPolicy, PageElement, VerificationHints
from app.operation.recognition import LocalGroundingRequest, RecognitionCandidate, ScoreBreakdown, run_local_grounding
from app.vision.schemas import BBox
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def _candidate(*, refined_bbox: dict[str, int] | None = None) -> RecognitionCandidate:
    element = PageElement(
        element_id="element_start",
        label="Start detection",
        role="button",
        interaction_type="click",
        description="Start detection button",
        text="Start detection",
        bbox=BBox(x=100, y=80, w=120, h=60),
        semantic_bbox=BBox(x=100, y=80, w=120, h=60),
        click_point={"x": 160, "y": 110},
        click_strategy="semantic_bbox_center",
        possible_destinations=[],
        verification_hints=VerificationHints(expected_changes=["content_change"], target_scope="local"),
        interaction_policy=InteractionPolicy(allowed=True, zone_type="test_module", priority="high"),
        fusion_confidence=0.9,
        coordinate_confidence="medium",
        memory_key="memory:start",
        sources=["test"],
    )
    return RecognitionCandidate(
        candidate_id="candidate_element_start",
        rank=1,
        element_id=element.element_id,
        label=element.label,
        role=element.role,
        text=element.text,
        score=0.85,
        eligible=True,
        reasons=["test"],
        score_breakdown=ScoreBreakdown(text_similarity=1.0),
        element=element,
        refined_bbox=refined_bbox,
        bbox_refine_reason="test_refined_bbox" if refined_bbox else None,
    )


def test_local_grounding_crops_candidate_and_maps_local_ocr_to_global_point(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (400, 260), color=(255, 255, 255)).save(image_path)

    def fake_ocr(path: str) -> OCRResult:
        assert Path(path).exists()
        return OCRResult(
            image_path=path,
            matches=[OCRTextMatch(text="Start detection", score=0.98, bbox=OCRBoundingBox(x=38, y=26, width=92, height=16))],
        )

    result = run_local_grounding(
        LocalGroundingRequest(
            image_path=str(image_path),
            goal="click start detection",
            candidates=[_candidate()],
            ocr_scan=fake_ocr,
            app_name="demo",
            crop_padding=20,
        )
    )

    grounded = result.results[0]
    assert result.contract_version == "narrow_search_v1"
    assert grounded.status == "grounded"
    assert grounded.crop_bbox == {"x": 80, "y": 60, "width": 160, "height": 100}
    assert grounded.refined_click_point == {"x": 164, "y": 94}
    assert grounded.coordinate_source == "local_ocr_text_center"
    assert grounded.matched_text == "Start detection"
    assert Path(grounded.crop_path or "").exists()


def test_local_grounding_falls_back_to_candidate_click_point_without_match(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (400, 260), color=(255, 255, 255)).save(image_path)

    def fake_ocr(path: str) -> OCRResult:
        return OCRResult(image_path=path, matches=[])

    result = run_local_grounding(
        LocalGroundingRequest(
            image_path=str(image_path),
            goal="click start detection",
            candidates=[_candidate()],
            ocr_scan=fake_ocr,
            app_name="demo",
        )
    )

    grounded = result.results[0]
    assert grounded.status == "fallback"
    assert grounded.refined_click_point == {"x": 160, "y": 110}
    assert grounded.coordinate_source == "candidate_element_click_point"
    assert "no_matching_local_ocr_text" in grounded.reasons


def test_local_grounding_prefers_candidate_refined_bbox_for_crop(tmp_path) -> None:
    image_path = tmp_path / "screen.png"
    Image.new("RGB", (400, 260), color=(255, 255, 255)).save(image_path)

    def fake_ocr(path: str) -> OCRResult:
        return OCRResult(
            image_path=path,
            matches=[OCRTextMatch(text="Start detection", score=0.98, bbox=OCRBoundingBox(x=10, y=8, width=90, height=16))],
        )

    result = run_local_grounding(
        LocalGroundingRequest(
            image_path=str(image_path),
            goal="click start detection",
            candidates=[_candidate(refined_bbox={"x": 130, "y": 94, "w": 80, "h": 24})],
            ocr_scan=fake_ocr,
            app_name="demo",
            crop_padding=10,
        )
    )

    grounded = result.results[0]
    assert grounded.crop_bbox == {"x": 120, "y": 84, "width": 100, "height": 44}
    assert grounded.refined_click_point == {"x": 175, "y": 100}
