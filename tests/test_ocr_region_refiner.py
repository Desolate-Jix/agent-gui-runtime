from __future__ import annotations

from app.vision.ocr_region_refiner import OCRRegionRefineOptions, refine_vision_regions_with_ocr
from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def _region(*, x: int, y: int, w: int, h: int, label: str = "Start button") -> VisionRegion:
    return VisionRegion(
        region_id="region_start",
        label=label,
        role="button",
        bbox=BBox(x=x, y=y, w=w, h=h),
        diagonal=Diagonal(x1=x, y1=y, x2=x + w, y2=y + h),
        normalized_diagonal=NormalizedDiagonal(nx1=0.1, ny1=0.1, nx2=0.2, ny2=0.2),
        description=label,
        ocr_text="Start",
        text_lines=["Start"],
        possible_destinations=["main"],
        confidence=0.9,
        layout_key="layout_start",
        content_key="content_start",
        match_key="layout_start:content_start",
    )


def test_refiner_shifts_region_when_matching_ocr_text_is_outside_bbox() -> None:
    vision = VisionAnalyzeResponse(
        provider="dummy",
        screen_summary="demo",
        state_guess="idle",
        image_size=ImageSize(width=420, height=220),
        regions=[_region(x=80, y=120, w=140, h=100)],
    )
    ocr = OCRResult(
        image_path="screen.png",
        matches=[OCRTextMatch(text="Start", score=0.99, bbox=OCRBoundingBox(x=77, y=68, width=24, height=13))],
    )

    refined = refine_vision_regions_with_ocr(vision, ocr, options=OCRRegionRefineOptions(enabled=True))

    assert refined.regions[0].bbox.to_dict() == {"x": 61, "y": 52, "w": 140, "h": 100}
    report = refined.artifacts["ocr_region_refine"]["regions"][0]
    assert report["status"] == "adjusted"
    assert report["selected_ocr_texts"] == ["Start"]
    assert report["move"] == {"dx": -19, "dy": -68}


def test_refiner_leaves_region_unchanged_when_matching_ocr_text_is_inside_bbox() -> None:
    vision = VisionAnalyzeResponse(
        provider="dummy",
        screen_summary="demo",
        state_guess="idle",
        image_size=ImageSize(width=420, height=220),
        regions=[_region(x=40, y=40, w=140, h=100)],
    )
    ocr = OCRResult(
        image_path="screen.png",
        matches=[OCRTextMatch(text="Start", score=0.99, bbox=OCRBoundingBox(x=77, y=68, width=24, height=13))],
    )

    refined = refine_vision_regions_with_ocr(vision, ocr, options=OCRRegionRefineOptions(enabled=True))

    assert refined.regions[0].bbox.to_dict() == {"x": 40, "y": 40, "w": 140, "h": 100}
    report = refined.artifacts["ocr_region_refine"]["regions"][0]
    assert report["status"] == "unchanged"
    assert report["reason"] == "matching_ocr_already_inside_region"
