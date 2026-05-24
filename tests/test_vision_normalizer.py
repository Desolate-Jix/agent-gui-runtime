from __future__ import annotations

from app.vision.normalizer import VisionResultNormalizer, normalizer
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
                "anchor_relations": [
                    {
                        "anchor_id": "ocr_anchor_1",
                        "text": "Orders",
                        "relation": "inside",
                        "axis": "both",
                        "target_edge": "center_x",
                        "anchor_edge": "center_x",
                        "gap_px": {"x": 0, "y": 0},
                        "overlap_ratio": {"x": 0.9, "y": 0.8},
                        "confidence": 0.91,
                        "evidence": "The region surrounds the Orders text.",
                    }
                ],
                "grounding_constraints": {
                    "reference_frame": {
                        "type": "nav",
                        "anchor_ids": ["ocr_anchor_1"],
                        "evidence": "Orders is inside the nav rail.",
                    },
                    "edge_constraints": {
                        "left": {"source": "visual_edge", "confidence": 0.8},
                        "right": {"source": "anchor", "anchor_id": "ocr_anchor_1", "relation": "contains_anchor"},
                    },
                    "center_constraints": {
                        "x": {"anchor_ids": ["ocr_anchor_1"], "alignment": "aligned_to", "confidence": 0.9}
                    },
                    "size_constraints": {"expected_aspect_ratio": "wide nav item"},
                    "negative_constraints": [{"anchor_id": "ocr_anchor_2", "rule": "must_not_include_text_anchor"}],
                    "final_bbox_reason": "Visual nav item encloses the text anchor with horizontal padding.",
                },
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
    assert region.anchor_relations == [
        {
            "anchor_id": "ocr_anchor_1",
            "text": "Orders",
            "relation": "inside",
            "axis": "both",
            "target_edge": "center_x",
            "anchor_edge": "center_x",
            "gap_px": {"x": 0, "y": 0},
            "overlap_ratio": {"x": 0.9, "y": 0.8},
            "confidence": 0.91,
            "evidence": "The region surrounds the Orders text.",
        }
    ]
    assert region.to_dict()["anchor_relations"][0]["relation"] == "inside"
    assert region.to_dict()["anchor_relations"][0]["gap_px"] == {"x": 0, "y": 0}
    assert region.grounding_constraints["edge_constraints"]["right"]["anchor_id"] == "ocr_anchor_1"
    assert region.to_dict()["grounding_constraints"]["final_bbox_reason"].startswith("Visual nav item")


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


def test_normalizer_scales_unit_1000_diagonal_when_model_ignores_small_image_size() -> None:
    raw = {
        "provider": "local",
        "contract_version": "vision_regions_v1",
        "image_size": {"width": 420, "height": 220},
        "screen_summary": "Single button",
        "state_guess": "idle",
        "regions": [
            {
                "region_id": "r1",
                "label": "Start Button",
                "role": "button",
                "diagonal": {"x1": 283, "y1": 363, "x2": 717, "y2": 637},
                "description": "Start button",
                "ocr_text": "Start",
                "confidence": 0.9,
            }
        ],
    }

    result = normalizer.normalize(raw, "local")

    assert len(result.regions) == 1
    assert result.regions[0].bbox.to_dict() == {"x": 119, "y": 80, "w": 182, "h": 60}


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
    assert 'contract_version must be "vision_regions_v1"' in prompt
    assert "possible_destinations" in prompt
    assert "anchor_relations" in prompt
    assert "grounding_constraints" in prompt
    assert "before finalizing a region diagonal" in prompt
    assert "edge_constraints" in prompt
    assert "negative_constraints" in prompt
    assert "text_anchor_frame" in prompt
    assert "text_inclusion_policy" in prompt
    assert "relative_frame_position" in prompt
    assert 'Case A, visual icon/object has no text inside it' in prompt
    assert 'Case B, the target visually includes text' in prompt


def test_prompt_builder_strengthens_grid_coordinate_guidance() -> None:
    prompt = build_region_analysis_prompt(
        VisionAnalyzeRequest(
            image_path="demo.png",
            app_name="DemoApp",
            goal="segment modules precisely",
            state_hint="dashboard",
        ),
        ImageSize(width=1440, height=900),
        grid_overlay_spacing=100,
    )

    assert "major grid spacing is 100 pixels" in prompt
    assert "first estimate each bbox edge against the nearest visible grid lines" in prompt
    assert "prefer tight boxes around the visible module itself" in prompt


def test_prompt_builder_includes_ocr_anchor_guidance() -> None:
    prompt = build_region_analysis_prompt(
        VisionAnalyzeRequest(
            image_path="demo.png",
            app_name="DemoApp",
            goal="click search",
            metadata={
                "ocr_anchors": {
                    "contract_version": "ocr_anchors_v1",
                    "coordinate_space": "inference_image",
                    "image_size": {"width": 400, "height": 200},
                    "anchor_count": 1,
                    "anchors": [
                        {
                            "anchor_id": "ocr_anchor_1",
                            "text": "Search",
                            "bbox": {"x": 120, "y": 20, "w": 50, "h": 18},
                            "center": {"x": 145, "y": 29},
                            "confidence": 0.97,
                            "goal_similarity": 0.9,
                        }
                    ],
                }
            },
        ),
        ImageSize(width=400, height=200),
    )

    assert "OCR anchor hints" in prompt
    assert "use them as spatial anchors for nearby icons" in prompt
    assert "id=anchor_id, t=text, b=[x,y,w,h]" in prompt
    assert "first choose the relevant anchor_ids" in prompt
    assert "write grounding_constraints" in prompt
    assert "reference_frame" in prompt
    assert "edge_constraints" in prompt
    assert "negative_constraints" in prompt
    assert "nearest OCR text boxes as boundary-line rulers" in prompt
    assert 'text_inclusion_policy="exclude_text"' in prompt
    assert 'text_inclusion_policy="include_referenced_text"' in prompt
    assert "use the label anchors as bottom negative/edge constraints" in prompt
    assert '"t":"Search"' in prompt
    assert '"b":[120,20,50,18]' in prompt
    assert '"coordinate_space":"inference_image"' in prompt


def test_prompt_builder_includes_all_ocr_anchors_without_truncation() -> None:
    anchors = [
        {
            "anchor_id": f"ocr_anchor_{index}",
            "text": f"Text {index}",
            "bbox": {"x": index, "y": index + 1, "w": 10, "h": 6},
            "center": {"x": index + 5, "y": index + 4},
            "confidence": 0.9,
            "goal_similarity": 0.1,
        }
        for index in range(30)
    ]

    prompt = build_region_analysis_prompt(
        VisionAnalyzeRequest(
            image_path="demo.png",
            app_name="DemoApp",
            goal="use all text anchors",
            metadata={
                "ocr_anchors": {
                    "contract_version": "ocr_anchors_v1",
                    "coordinate_space": "inference_image",
                    "image_size": {"width": 400, "height": 200},
                    "total_detected_count": 30,
                    "anchor_count": 30,
                    "anchors": anchors,
                }
            },
        ),
        ImageSize(width=400, height=200),
    )

    assert '"anchor_count":30' in prompt
    assert '"t":"Text 0"' in prompt
    assert '"t":"Text 29"' in prompt


def test_prompt_builder_includes_custom_prompt_rules() -> None:
    prompt = build_region_analysis_prompt(
        VisionAnalyzeRequest(
            image_path="screen.png",
            task="click_target",
            goal="find home icon",
            metadata={"prompt_overrides": {"additional_rules": "Prefer the leftmost logo mark in the navigation bar."}},
        ),
        ImageSize(width=800, height=600),
    )

    assert "Additional user-configured grounding rules" in prompt
    assert "Prefer the leftmost logo mark in the navigation bar." in prompt


def test_normalizer_skips_non_object_region_target_and_observer_items() -> None:
    normalizer = VisionResultNormalizer()

    result = normalizer.normalize(
        {
            "provider": "internvl",
            "image_size": {"width": 420, "height": 220},
            "screen_summary": "synthetic ui",
            "regions": [
                "bad region",
                {
                    "region_id": "region_start",
                    "label": "Start",
                    "role": "button",
                    "bbox": {"x": 120, "y": 82, "w": 180, "h": 60},
                    "confidence": 0.8,
                },
            ],
            "targets": ["bad target"],
            "observers": ["bad observer"],
        },
        "local",
    )

    assert [region.region_id for region in result.regions] == ["region_start"]
    assert result.targets == []
    assert result.observers == []
