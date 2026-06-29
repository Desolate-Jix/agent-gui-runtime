from __future__ import annotations

from app.operation.page_structure import build_page_structure
from app.operation.screen_reading import build_screen_reading
from app.operation.screen_reading.uia_provider import _patterns
from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def test_uia_pattern_probe_ignores_descriptor_errors() -> None:
    class Wrapper:
        @property
        def invoke(self) -> object:
            raise RuntimeError("pattern unavailable")

        def get_value(self) -> str:
            return "value"

    assert _patterns(Wrapper()) == ("Value",)


def test_screen_reading_exposes_ui_layer_with_reserved_icon_and_learning_slots() -> None:
    vision = VisionAnalyzeResponse(
        provider="dummy",
        screen_summary="Browser page with toolbar and a Start button.",
        state_guess="demo",
        image_size=ImageSize(width=420, height=220),
        regions=[
            VisionRegion(
                region_id="region_start",
                label="Start",
                role="button",
                bbox=BBox(x=80, y=120, w=140, h=80),
                diagonal=Diagonal(x1=80, y1=120, x2=220, y2=200),
                normalized_diagonal=NormalizedDiagonal(nx1=0.19, ny1=0.54, nx2=0.52, ny2=0.9),
                description="Start button",
                ocr_text="Start",
                text_lines=["Start"],
                confidence=0.9,
                layout_key="start_layout",
                content_key="start_content",
                match_key="start_layout:start_content",
            ),
            VisionRegion(
                region_id="region_back",
                label="Back arrow",
                role="icon_button",
                bbox=BBox(x=12, y=50, w=34, h=34),
                diagonal=Diagonal(x1=12, y1=50, x2=46, y2=84),
                normalized_diagonal=NormalizedDiagonal(nx1=0.02, ny1=0.22, nx2=0.1, ny2=0.38),
                description="Left arrow icon in the browser toolbar.",
                confidence=0.82,
                layout_key="browser_toolbar_left",
                content_key="back_arrow",
                match_key="browser_toolbar_left:back_arrow",
            ),
        ],
    )
    ocr = OCRResult(
        image_path="demo.png",
        metadata={"engine": "test_ocr"},
        matches=[OCRTextMatch(text="Start", score=0.99, bbox=OCRBoundingBox(x=112, y=150, width=44, height=18))],
    )
    page_structure = build_page_structure(vision, ocr)
    uia_snapshot = {
        "provider": "windows_uia",
        "provider_version": "windows_uia_provider_v1",
        "status": "ok",
        "control_count": 1,
        "controls": [
            {
                "provider": "windows_uia",
                "control_id": "uia_1_back",
                "name": "Back",
                "control_type": "Button",
                "automation_id": "Back",
                "class_name": "Button",
                "bbox": {"x": 12, "y": 50, "w": 34, "h": 34},
                "screen_bbox": {"x": 112, "y": 150, "w": 34, "h": 34},
                "enabled": True,
                "visible": True,
                "patterns": ["Invoke"],
            }
        ],
    }

    result = build_screen_reading(
        image_path="demo.png",
        vision=vision,
        ocr=ocr,
        page_structure=page_structure,
        app_name="demo",
        uia_snapshot=uia_snapshot,
    )

    assert result["contract_version"] == "screen_reading_v1"
    assert result["ui"]["summary"]["element_count"] == 2
    assert result["ui"]["summary"]["icon_candidate_count"] == 1
    assert "icon_library" not in result["ui"]["provider_slots"]
    assert result["ui"]["provider_slots"]["uia"]["status"] == "connected"
    assert result["ui"]["provider_slots"]["uia"]["last_scan_status"] == "ok"
    assert result["ui"]["provider_slots"]["learned_ui_memory"]["status"] == "reserved"

    start = next(item for item in result["ui_elements"] if item["label"] == "Start")
    assert start["evidence_level"] == "ocr_text_and_semantic_region"
    assert start["locator_hints"]["future_providers"]["uia"]["status"] == "connected"
    assert "icon_library" not in start["locator_hints"]["future_providers"]

    back = next(item for item in result["ui_elements"] if item["role_guess"] == "icon_button")
    assert back["type"] == "icon_button"
    assert back["evidence_level"] == "visual_region_only"
    assert back["id"] in result["execution_relevance"]["risky_candidates"]
    back_icon = next(item for item in result["ui"]["icon_candidates"] if item["element_id"] == back["id"])
    assert back_icon["visual_recognition_status"] == "reserved_for_grounding"
    assert "icon_library_match" not in back_icon
    assert back_icon["uia_match"]["name"] == "Back"
    assert back_icon["uia_match"]["control_type"] == "Button"
    assert "Invoke" in back_icon["uia_match"]["patterns"]
    assert back["provider_matches"]["uia"]["control_id"] == "uia_1_back"
    assert any(item["code"] == "visual_only_ui_requires_grounding" for item in result["uncertainties"])
    assert result["source_layers"]["windows_uia"]["status"] == "ok"
    assert result["source_layers"]["windows_uia"]["controls"][0]["name"] == "Back"
    assert result["screen_inventory"]["contract_version"] == "screen_inventory_v1"
    assert result["screen_inventory"]["summary"]["available_action_count"] >= 1
