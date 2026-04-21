from __future__ import annotations

from app.vision.normalizer import normalizer
from app.vision.prompting import build_region_analysis_prompt
from app.vision.schemas import ImageSize, VisionAnalyzeRequest


def test_normalizer_builds_region_from_diagonal_and_generates_match_keys() -> None:
    raw = {
        "provider": "local",
        "contract_version": "vision_regions_v1",
        "image_size": {"width": 1000, "height": 500},
        "screen_summary": "Sample page",
        "state_guess": "dashboard",
        "regions": [
            {
                "region_id": "region_nav_orders",
                "label": "Orders",
                "role": "nav",
                "diagonal": {"x1": 100, "y1": 50, "x2": 400, "y2": 250},
                "description": "Orders navigation item that likely opens the orders page.",
                "ocr_text": "Orders",
                "text_lines": ["Orders"],
                "possible_destinations": ["orders_page"],
                "confidence": 0.92,
            }
        ],
    }

    result = normalizer.normalize(raw, "local")

    assert result.contract_version == "vision_regions_v1"
    assert result.image_size is not None
    assert result.image_size.to_dict() == {"width": 1000, "height": 500}
    assert len(result.regions) == 1

    region = result.regions[0]
    assert region.bbox.to_dict() == {"x": 100, "y": 50, "w": 300, "h": 200}
    assert region.diagonal.to_dict() == {"x1": 100, "y1": 50, "x2": 400, "y2": 250}
    assert region.normalized_diagonal.to_dict() == {"nx1": 0.1, "ny1": 0.1, "nx2": 0.4, "ny2": 0.5}
    assert region.layout_key
    assert region.content_key
    assert region.match_key == f"{region.layout_key}:{region.content_key}"


def test_normalizer_derives_regions_from_targets_for_backward_compatibility() -> None:
    raw = {
        "provider": "api",
        "screen_summary": "Simple page",
        "state_guess": "list",
        "image_size": {"width": 800, "height": 600},
        "targets": [
            {
                "target_id": "target_submit",
                "label": "Submit",
                "bbox": {"x": 200, "y": 300, "w": 120, "h": 40},
                "kind": "button",
                "clickable_confidence": 0.88,
                "expected_effect": "submit_dialog",
            }
        ],
    }

    result = normalizer.normalize(raw, "api")

    assert len(result.targets) == 1
    assert len(result.regions) == 1
    region = result.regions[0]
    assert region.region_id == "target_submit"
    assert region.role == "button"
    assert region.possible_destinations == ["submit_dialog"]


def test_prompt_builder_includes_resolution_and_required_schema() -> None:
    prompt = build_region_analysis_prompt(
        VisionAnalyzeRequest(
            image_path="demo.png",
            app_name="DemoApp",
            goal="understand navigation",
            state_hint="home",
        ),
        ImageSize(width=1440, height=900),
    )

    assert "image width = 1440" in prompt
    assert "image height = 900" in prompt
    assert '"contract_version": "vision_regions_v1"' in prompt
    assert '"possible_destinations"' in prompt
