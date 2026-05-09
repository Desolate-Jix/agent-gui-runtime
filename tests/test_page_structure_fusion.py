from __future__ import annotations

from app.page_structure import build_page_structure
from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def _region(region_id: str, label: str, role: str, x: int, y: int, w: int, h: int) -> VisionRegion:
    return VisionRegion(
        region_id=region_id,
        label=label,
        role=role,
        bbox=BBox(x=x, y=y, w=w, h=h),
        diagonal=Diagonal(x1=x, y1=y, x2=x + w, y2=y + h),
        normalized_diagonal=NormalizedDiagonal(nx1=0.1, ny1=0.1, nx2=0.2, ny2=0.2),
        description=f"{label} {role}",
        ocr_text=label,
        text_lines=[label],
        possible_destinations=[f"{label.casefold()}_page"],
        confidence=0.92,
        layout_key=f"layout_{region_id}",
        content_key=f"content_{region_id}",
        match_key=f"layout_{region_id}:content_{region_id}",
    )


def test_build_page_structure_binds_ocr_text_to_supported_regions() -> None:
    vision = VisionAnalyzeResponse(
        provider="local",
        image_size=ImageSize(width=420, height=220),
        screen_summary="main menu",
        state_guess="home",
        regions=[
            _region("region_start", "Start button", "button", 80, 120, 140, 100),
            _region("region_settings", "Settings tab", "tab", 280, 120, 140, 100),
            _region("region_panel", "Main content", "content", 0, 0, 420, 220),
        ],
    )
    ocr = OCRResult(
        image_path="screen.png",
        metadata={"engine": "rapidocr_onnxruntime"},
        matches=[
            OCRTextMatch(text="Start", score=0.99, bbox=OCRBoundingBox(x=77, y=68, width=24, height=13)),
            OCRTextMatch(text="Settings", score=0.98, bbox=OCRBoundingBox(x=256, y=67, width=41, height=16)),
        ],
    )

    structure = build_page_structure(vision, ocr)
    result = structure.to_dict()

    assert result["contract_version"] == "page_structure_v1"
    assert result["image_size"] == {"width": 420, "height": 220}
    assert len(result["texts"]) == 2
    assert len(result["elements"]) == 2
    assert len(result["raw_vision_regions"]) == 3

    start = next(item for item in result["elements"] if item["text"] == "Start")
    assert start["role"] == "button"
    assert start["interaction_type"] == "click"
    assert start["click_strategy"] == "ocr_text_center"
    assert start["click_point"] == {"x": 89, "y": 74}
    assert start["coordinate_confidence"] == "high"
    assert start["verification_hints"] == {
        "expected_changes": ["state_change", "new_region", "content_change"],
        "target_scope": "page",
    }
    assert start["interaction_policy"]["allowed"] is True
    assert start["interaction_policy"]["zone_type"] == "general_action"
    assert "role:button" in start["memory_key"]
    assert start["source_region_ids"] == ["region_start"]
    assert start["source_text_ids"] == ["text_1"]

    settings = next(item for item in result["elements"] if item["text"] == "Settings")
    assert settings["role"] == "tab"
    assert settings["verification_hints"]["expected_changes"] == ["selection_change", "content_change"]
    assert settings["interaction_policy"]["allowed"] is True

    bound_links = [item for item in result["links"] if item["relation"] == "semantic_text_binding"]
    assert len(bound_links) == 2
    assert bound_links[0]["text_ids"]
    assert result["learning_summary"]["allowed_element_count"] == 2
    assert result["learning_summary"]["blocked_element_count"] == 0


def test_build_page_structure_marks_ad_like_action_as_blocked() -> None:
    vision = VisionAnalyzeResponse(
        provider="local",
        image_size=ImageSize(width=420, height=220),
        screen_summary="download area",
        state_guess="tool_recommendations",
        regions=[_region("region_download", "CPU-Z 涓嬭浇", "button", 80, 40, 180, 90)],
    )
    ocr = OCRResult(
        image_path="screen.png",
        metadata={"engine": "rapidocr_onnxruntime"},
        matches=[OCRTextMatch(text="绔嬪嵆璁块棶 CPU-Z", score=0.99, bbox=OCRBoundingBox(x=90, y=60, width=96, height=18))],
    )

    structure = build_page_structure(vision, ocr)
    result = structure.to_dict()

    assert len(result["elements"]) == 1
    download = result["elements"][0]
    assert download["interaction_policy"]["allowed"] is False
    assert download["interaction_policy"]["zone_type"] == "ad_candidate"
    assert download["interaction_policy"]["priority"] == "blocked"
    assert result["learning_summary"]["blocked_element_count"] == 1
    assert result["learning_summary"]["ad_like_element_ids"] == [download["element_id"]]


def test_build_page_structure_does_not_bind_far_duplicate_short_texts() -> None:
    vision = VisionAnalyzeResponse(
        provider="local",
        image_size=ImageSize(width=1500, height=900),
        screen_summary="mouse tester",
        state_guess="test_page",
        regions=[_region("region_double_click", "C E Click here", "button", 980, 500, 120, 90)],
    )
    ocr = OCRResult(
        image_path="screen.png",
        metadata={"engine": "rapidocr_onnxruntime"},
        matches=[
            OCRTextMatch(text="C", score=0.93, bbox=OCRBoundingBox(x=56, y=52, width=18, height=16)),
            OCRTextMatch(text="E", score=0.81, bbox=OCRBoundingBox(x=1282, y=104, width=46, height=25)),
            OCRTextMatch(text="Click here", score=0.99, bbox=OCRBoundingBox(x=1008, y=532, width=70, height=17)),
        ],
    )

    structure = build_page_structure(vision, ocr)
    result = structure.to_dict()

    element = result["elements"][0]
    assert element["text"] == "Click here"
    assert element["source_text_ids"] == ["text_3"]
    assert element["bbox"] == {"x": 1008, "y": 532, "w": 70, "h": 17}


def test_build_page_structure_rejects_far_ambiguous_short_text_binding() -> None:
    vision = VisionAnalyzeResponse(
        provider="local",
        image_size=ImageSize(width=1500, height=900),
        screen_summary="mouse tester",
        state_guess="test_page",
        regions=[_region("region_icon", "C E", "button", 980, 500, 120, 90)],
    )
    ocr = OCRResult(
        image_path="screen.png",
        metadata={"engine": "rapidocr_onnxruntime"},
        matches=[OCRTextMatch(text="C", score=0.93, bbox=OCRBoundingBox(x=56, y=52, width=18, height=16))],
    )

    structure = build_page_structure(vision, ocr)
    result = structure.to_dict()

    element = result["elements"][0]
    assert element["text"] == "C E"
    assert element["source_text_ids"] == []
    assert element["bbox"] == {"x": 980, "y": 500, "w": 120, "h": 90}
    assert result["links"][0]["relation"] == "semantic_only"
