from __future__ import annotations

import json
from pathlib import Path

from app.learn.draft_review import load_learning_draft_review
from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review
from app.learn.recognition import build_learning_recognition_trial
from app.learn.recognition import two_stage
from app.learn.recognition.two_stage import (
    _render_message_context_review_overlay,
    _render_two_stage_overlay,
    _stage1_5_overlay_style,
    build_stage1_region_localization_report,
    build_two_stage_screen_understanding,
)
from scripts.run_learn_stage1_region_localization import _observe_bundle_from_trace_result


def _stage2_region_with_item(
    result: dict,
    item_id: str,
    *,
    region_prefix: str = "structure_region_primary_area",
) -> dict:
    regions = result["stage2_numbering"]["regions"]
    for region in regions:
        region_id = str(region.get("region_id") or "")
        if not region_id.startswith(region_prefix):
            continue
        if any(item.get("item_id") == item_id for item in region.get("numbered_items", [])):
            return region
    return next(item for item in regions if item["region_id"] == region_prefix)


def test_observe_bundle_from_trace_preserves_screen_reading_texts(tmp_path):
    trace_path = tmp_path / "observe_trace.json"
    result = {
        "image_path": "screen.png",
        "image_size": {"width": 1000, "height": 760},
        "screen_reading": {
            "texts": [
                {
                    "text": "Ad astra",
                    "bbox": {"x": 772, "y": 420, "w": 64, "h": 20},
                    "source": "ocr_fallback",
                }
            ]
        },
    }

    bundle = _observe_bundle_from_trace_result(result, trace_path=trace_path)

    assert bundle["screen_reading"]["texts"][0]["text"] == "Ad astra"
    assert bundle["screen_reading"]["texts"][0]["bbox"] == {"x": 772, "y": 420, "w": 64, "h": 20}


def test_two_stage_screen_understanding_splits_structure_then_numbers_items(tmp_path):
    image_path = tmp_path / "apple_music.png"
    image_path.write_bytes(b"not a real image")
    inventory = [
        {
            "item_id": "nav_home",
            "label": "Home icon",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 16, "y": 140, "w": 24, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "card_1",
            "label": "Energy album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 240, "w": 260, "h": 190},
            "review_only": True,
            "metadata": {
                "text_lines": [
                    {"label": "能量充电", "bbox": {"x": 170, "y": 330, "w": 140, "h": 30}},
                    {"label": "ATLUS Sound Team", "bbox": {"x": 170, "y": 370, "w": 160, "h": 20}},
                ]
            },
        },
        {
            "item_id": "misassigned_left_icon",
            "label": "Playlist icon",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 18, "y": 210, "w": 24, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["nav_home"]},
            "main_content": {"item_ids": ["card_1", "misassigned_left_icon"]},
        },
        "nodes": {
            "nav_home": inventory[0],
            "card_1": inventory[1],
            "misassigned_left_icon": inventory[2],
        },
    }

    result = build_two_stage_screen_understanding(
        bundle={
            "image_path": str(image_path),
            "screen_size": {"width": 900, "height": 650},
        },
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert result["contract_version"] == "learn_two_stage_screen_understanding_v1"
    assert result["pipeline_contract"]["contract_version"] == "learn_mode_two_pass_pipeline_contract_v1"
    assert result["pipeline_contract"]["center_policy"] == "subdivide_main_content_before_item_numbering"
    assert result["flow_compliance"]["stage1_region_split_present"] is True
    assert result["flow_compliance"]["single_screenshot_patch_strategy_used"] is False


    assert result["stage1_structure"]["region_count"] == 2
    assert result["stage1_region_localization"]["localized_region_count"] == 2
    assert [item["region_id"] for item in result["stage1_structure"]["structure_regions"]] == [
        "structure_region_left_nav",
        "structure_region_main_content",
    ]
    left_region = next(
        item for item in result["stage1_structure"]["structure_regions"] if item["region_id"] == "structure_region_left_nav"
    )
    main_region = next(
        item for item in result["stage1_structure"]["structure_regions"] if item["region_id"] == "structure_region_main_content"
    )
    assert "misassigned_left_icon" in left_region["item_ids"]
    assert "misassigned_left_icon" not in main_region["item_ids"]
    assert main_region["bbox"]["x"] > 96
    localized_left = next(
        item for item in result["stage1_region_localization"]["regions"] if item["region_id"] == "structure_region_left_nav"
    )
    assert localized_left["precise_bbox"]["w"] >= 72
    localized_main = next(
        item for item in result["stage1_region_localization"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    assert localized_main["locator_task"]["target_scope"] == "whole_structure_region"
    assert localized_main["rough_bbox"] == main_region["bbox"]
    assert localized_main["precise_bbox"]["x"] < main_region["bbox"]["x"]
    assert localized_main["precise_bbox"]["w"] > main_region["bbox"]["w"]
    assert localized_main["coordinate_validation"]["status"] == "heuristic_calibrated_from_region_content"
    assert result["stage2_numbering"]["regions"][1]["input_region_bbox"] == localized_main["precise_bbox"]
    assert result["stage2_numbering"]["region_count"] == 2
    left_numbered_region = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_left_nav"
    )
    assert left_numbered_region["region_processing_contract"]["mode"] == "direct_numbering_within_precise_region"
    assert left_numbered_region["bar_numbering"]["applied"] is True
    assert (
        left_numbered_region["bar_numbering"]["spacing_policy"]
        == "spacing_may_split_control_groups_but_must_not_shrink_region_bbox"
    )
    main_numbered_region = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    assert main_numbered_region["region_processing_contract"]["mode"] == "subdivide_then_number"
    assert main_numbered_region["main_content_subdivision"]["subdivision_required"] is True
    assert main_numbered_region["bar_numbering"]["applied"] is False
    assert main_numbered_region["numbered_items"][0]["number"] == "2.1"
    assert main_numbered_region["numbered_items"][0]["children"][0]["label"] == "能量充电"
    assert result["fusion"]["fused_review_box_count"] >= 4
    assert result["model_call_plan"]["recommended_model_calls"] == 2


def test_two_stage_global_no_partition_numbers_items_on_full_screen_canvas(tmp_path):
    image_path = tmp_path / "apple_music.png"
    image_path.write_bytes(b"not a real image")
    inventory = [
        {
            "item_id": "top_play",
            "label": "Play",
            "role": "control",
            "item_type": "review_only",
            "bbox": {"x": 160, "y": 24, "w": 28, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "left_home",
            "label": "Home",
            "role": "nav_item",
            "item_type": "review_only",
            "bbox": {"x": 18, "y": 110, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "card_1",
            "label": "Energy album card",
            "role": "media_card",
            "item_type": "card",
            "bbox": {"x": 180, "y": 220, "w": 180, "h": 240},
            "review_only": True,
        },
    ]
    layout_graph = {
        "zones": {
            "top_bar": {"item_ids": ["top_play"]},
            "left_nav": {"item_ids": ["left_home"]},
            "main_content": {"item_ids": ["card_1"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 650}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        stage2_region_strategy="global_no_partition",
    )

    assert result["stage2_input_policy"]["stage2_region_strategy"] == "global_no_partition"
    assert result["stage2_input_policy"]["input_region_count"] == 1
    region = result["stage2_numbering"]["regions"][0]
    assert region["region_id"] == "global_no_partition"
    assert region["input_region_bbox"] == {"x": 0, "y": 0, "w": 900, "h": 650}
    assert {item["item_id"] for item in region["numbered_items"]} >= {"top_play", "left_home", "card_1"}


def test_fusion_marks_group_child_text_as_child_evidence_not_main_overlay() -> None:
    structure_regions = [
        {
            "region_no": 1,
            "label": "Primary",
            "bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
        }
    ]
    numbered_regions = [
        {
            "region_id": "structure_region_primary_area",
            "subregion_groups": [
                {
                    "group_id": "hero_panel_1",
                    "label": "hero panel",
                    "role": "hero_panel",
                    "bbox": {"x": 20, "y": 20, "w": 460, "h": 160},
                    "member_item_ids": ["hero_title", "hero_cta"],
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                }
            ],
            "numbered_items": [
                {
                    "item_id": "hero_title",
                    "number": "1.1",
                    "label": "Quick and Easy",
                    "role": "text",
                    "bbox": {"x": 40, "y": 40, "w": 200, "h": 28},
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                },
                {
                    "item_id": "hero_card",
                    "number": "1.2",
                    "label": "Download card",
                    "role": "news_card",
                    "bbox": {"x": 40, "y": 220, "w": 200, "h": 140},
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                },
                {
                    "item_id": "hero_extra",
                    "number": "1.3",
                    "label": "Extra hero copy",
                    "role": "text",
                    "bbox": {"x": 70, "y": 90, "w": 220, "h": 26},
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                },
            ],
        }
    ]

    fusion = two_stage._fusion_boxes(structure_regions, numbered_regions)

    boxes = {item["number"]: item for item in fusion["fused_review_boxes"] if item.get("box_type") == "numbered_item"}
    assert boxes["1.1"]["parent_group_ids"] == ["hero_panel_1"]
    assert boxes["1.1"]["display_hierarchy"]["display_layer"] == "child_evidence"
    assert boxes["1.1"]["render_in_main_overlay"] is False
    assert boxes["1.2"]["display_hierarchy"]["display_layer"] == "primary_region"
    assert boxes["1.2"]["render_in_main_overlay"] is True
    assert boxes["1.3"]["parent_group_ids"] == ["hero_panel_1"]
    assert boxes["1.3"]["display_hierarchy"]["display_layer"] == "child_evidence"
    assert boxes["1.3"]["render_in_main_overlay"] is False


def test_fusion_demotes_model_text_cards_inside_parent_groups_but_keeps_visual_cards() -> None:
    structure_regions = [
        {
            "region_no": 1,
            "region_id": "structure_region_primary_area",
            "label": "Primary",
            "bbox": {"x": 0, "y": 0, "w": 900, "h": 600},
        }
    ]
    numbered_regions = [
        {
            "region_id": "structure_region_primary_area",
            "subregion_groups": [
                {
                    "group_id": "latest_news_section",
                    "label": "Latest News",
                    "role": "section_parent",
                    "bbox": {"x": 40, "y": 40, "w": 360, "h": 220},
                    "member_item_ids": ["model_news_card"],
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 600},
                },
                {
                    "group_id": "media_row",
                    "label": "Media row",
                    "role": "media_card_group",
                    "bbox": {"x": 460, "y": 40, "w": 360, "h": 260},
                    "member_item_ids": ["visual_media_card"],
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 600},
                },
            ],
            "numbered_items": [
                {
                    "item_id": "model_news_card",
                    "number": "1.1",
                    "label": "Thinking about running for the board?",
                    "role": "news_card",
                    "source": "structure_region_item",
                    "bbox": {"x": 56, "y": 96, "w": 300, "h": 96},
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 600},
                },
                {
                    "item_id": "visual_media_card",
                    "number": "1.2",
                    "label": "Album card",
                    "role": "media_card",
                    "source": "visual_card_segmenter",
                    "bbox": {"x": 500, "y": 88, "w": 180, "h": 220},
                    "parent_region_id": "structure_region_primary_area",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 600},
                },
            ],
        }
    ]

    fusion = two_stage._fusion_boxes(structure_regions, numbered_regions)

    boxes = {item["number"]: item for item in fusion["fused_review_boxes"] if item.get("box_type") == "numbered_item"}
    assert boxes["1.1"]["display_hierarchy"]["display_layer"] == "child_evidence"
    assert boxes["1.1"]["display_hierarchy"]["demotion_reason"] == "model_card_like_text_evidence_inside_parent_group"
    assert boxes["1.1"]["render_in_main_overlay"] is False
    assert boxes["1.2"]["display_hierarchy"]["display_layer"] == "primary_region"
    assert boxes["1.2"]["render_in_main_overlay"] is True


def test_fusion_demotes_structural_container_groups_with_child_groups_from_main_overlay() -> None:
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_primary_area",
                "label": "Primary",
                "bbox": {"x": 0, "y": 0, "w": 600, "h": 420},
            }
        ],
        [
            {
                "region_id": "structure_region_primary_area",
                "subregion_groups": [
                    {
                        "group_id": "hero_panel_1",
                        "label": "Hero panel",
                        "role": "hero_panel",
                        "bbox": {"x": 40, "y": 40, "w": 520, "h": 180},
                        "child_group_ids": ["hero_text_panel_1", "hero_code_panel_1"],
                        "child_group_roles": ["hero_text_panel", "hero_code_panel"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 600, "h": 420},
                    },
                    {
                        "group_id": "hero_text_panel_1",
                        "label": "Hero text",
                        "role": "hero_text_panel",
                        "bbox": {"x": 320, "y": 60, "w": 220, "h": 130},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 600, "h": 420},
                    },
                ],
                "numbered_items": [],
            }
        ],
    )

    groups = {item["number"]: item for item in result["fused_review_boxes"] if item.get("box_type") == "subregion_group"}
    assert groups["hero_panel_1"]["group_display_hierarchy"]["display_layer"] == "structural_container"
    assert groups["hero_panel_1"]["render_in_main_overlay"] is False
    assert groups["hero_text_panel_1"]["render_in_main_overlay"] is True


def test_fusion_keeps_ungrouped_review_region_detail_only() -> None:
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_primary_area",
                "label": "Primary",
                "bbox": {"x": 0, "y": 0, "w": 700, "h": 500},
            }
        ],
        [
            {
                "region_id": "structure_region_primary_area",
                "subregion_groups": [
                    {
                        "group_id": "ungrouped_review_region_1",
                        "label": "ungrouped review region",
                        "role": "ungrouped_review_region",
                        "bbox": {"x": 80, "y": 80, "w": 480, "h": 220},
                        "member_item_ids": ["review_text"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 700, "h": 500},
                    }
                ],
                "numbered_items": [
                    {
                        "item_id": "review_text",
                        "number": "1.1",
                        "label": "fallback text evidence",
                        "role": "text",
                        "bbox": {"x": 110, "y": 110, "w": 240, "h": 24},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 700, "h": 500},
                    }
                ],
            }
        ],
    )

    group = next(item for item in result["fused_review_boxes"] if item.get("box_type") == "subregion_group")
    child = next(item for item in result["fused_review_boxes"] if item.get("box_type") == "numbered_item")
    assert group["group_display_hierarchy"]["display_layer"] == "detail_only_review_region"
    assert group["render_in_main_overlay"] is False
    assert child["display_hierarchy"]["display_layer"] == "child_evidence"
    assert child["display_hierarchy"]["demotion_reason"] == "ungrouped_review_region_detail_only"
    assert child["render_in_main_overlay"] is False


def test_fusion_demotes_media_group_without_visual_card_evidence() -> None:
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_primary_area",
                "label": "Primary",
                "bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
            }
        ],
        [
            {
                "region_id": "structure_region_primary_area",
                "subregion_groups": [
                    {
                        "group_id": "text_card_row",
                        "label": "visual media card row",
                        "role": "media_card_group",
                        "bbox": {"x": 80, "y": 420, "w": 700, "h": 170},
                        "member_item_ids": ["news_card_a", "news_card_b", "more_link"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                    {
                        "group_id": "visual_card_row",
                        "label": "visual media card row",
                        "role": "media_card_group",
                        "bbox": {"x": 80, "y": 80, "w": 700, "h": 260},
                        "member_item_ids": ["album_card_a", "album_card_b"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                ],
                "numbered_items": [
                    {
                        "item_id": "news_card_a",
                        "number": "1.1",
                        "label": "Python 3.15 beta is here",
                        "role": "news_card",
                        "source": "structure_region_item",
                        "bbox": {"x": 90, "y": 430, "w": 300, "h": 120},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                    {
                        "item_id": "news_card_b",
                        "number": "1.2",
                        "label": "Use Python for...",
                        "role": "news_card",
                        "source": "structure_region_item",
                        "bbox": {"x": 470, "y": 430, "w": 260, "h": 120},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                    {
                        "item_id": "more_link",
                        "number": "1.3",
                        "label": "More",
                        "role": "button",
                        "source": "structure_region_item",
                        "bbox": {"x": 740, "y": 430, "w": 60, "h": 24},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                    {
                        "item_id": "album_card_a",
                        "number": "1.4",
                        "label": "Album A",
                        "role": "media_card",
                        "source": "visual_card_segmenter",
                        "bbox": {"x": 100, "y": 100, "w": 180, "h": 220},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                    {
                        "item_id": "album_card_b",
                        "number": "1.5",
                        "label": "Album B",
                        "role": "media_card",
                        "source": "visual_card_segmenter",
                        "bbox": {"x": 320, "y": 100, "w": 180, "h": 220},
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 700},
                    },
                ],
            }
        ],
    )

    groups = {item["number"]: item for item in result["fused_review_boxes"] if item.get("box_type") == "subregion_group"}
    assert groups["text_card_row"]["group_display_hierarchy"]["display_layer"] == "detail_only_text_card_group"
    assert groups["text_card_row"]["render_in_main_overlay"] is False
    assert groups["visual_card_row"]["render_in_main_overlay"] is True


def test_stage1_localization_suppresses_tiny_contained_duplicate_main_region(tmp_path):
    from PIL import Image

    image_path = tmp_path / "generic_app.png"
    Image.new("RGB", (1000, 700), "white").save(image_path)
    inventory = [
        {
            "item_id": "primary_area",
            "label": "Primary work area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 100, "y": 100, "w": 800, "h": 500},
            "review_only": True,
        },
        {
            "item_id": "tiny_duplicate",
            "label": "Tiny duplicate content hint",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 140, "y": 140, "w": 50, "h": 30},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "primary_area": {"item_ids": ["primary_area"]},
            "main_content": {"item_ids": ["tiny_duplicate"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 700}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    localization = report["stage1_region_localization"]
    assert localization["suppressed_duplicate_region_count"] == 1
    assert localization["localized_region_count"] == 1
    assert localization["suppressed_duplicate_regions"][0]["region_id"] == "structure_region_main_content"
    assert localization["suppressed_duplicate_regions"][0]["contained_by_region_id"] == "structure_region_primary_area"
    kept_region_ids = [item["region_id"] for item in localization["regions"]]
    assert kept_region_ids == ["structure_region_primary_area"]
    assert report["region_selection_audit"]["passed"] is True
    assert "main_region_too_small" not in report["region_selection_audit"]["failure_categories"]


def test_stage1_splits_right_side_information_panel_without_splitting_card_grid(tmp_path):
    from PIL import Image

    image_path = tmp_path / "right_panel.png"
    Image.new("RGB", (1000, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "chat_body",
            "label": "Conversation content",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 120, "y": 120, "w": 860, "h": 560},
            "review_only": True,
        },
        {
            "item_id": "right_notice",
            "label": "Group announcement",
            "role": "recommendation_item",
            "item_type": "card",
            "bbox": {"x": 760, "y": 120, "w": 220, "h": 230},
            "review_only": True,
        },
        {
            "item_id": "right_members",
            "label": "Member list",
            "role": "recommendation_item",
            "item_type": "card",
            "bbox": {"x": 760, "y": 370, "w": 220, "h": 310},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    region_ids = {item["region_id"] for item in result["stage1_region_localization"]["regions"]}
    assert "structure_region_right_sidebar" in region_ids
    right_region = next(
        item for item in result["stage1_region_localization"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    primary_region = next(
        item for item in result["stage1_region_localization"]["regions"] if item["region_id"] == "structure_region_primary_area"
    )
    assert set(right_region["item_ids"]) == {"right_notice", "right_members"}
    assert "right_notice" not in primary_region["item_ids"]
    assert right_region["precise_bbox"]["x"] >= 720
    assert primary_region["precise_bbox"]["x"] + primary_region["precise_bbox"]["w"] <= right_region["precise_bbox"]["x"]
    assert result["region_selection_audit"]["passed"] is True

    card_grid_inventory = [
        {
            "item_id": "card_left",
            "label": "Left album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 190, "w": 220, "h": 260},
            "review_only": True,
        },
        {
            "item_id": "card_middle",
            "label": "Middle album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 390, "y": 190, "w": 220, "h": 260},
            "review_only": True,
        },
        {
            "item_id": "card_right",
            "label": "Right album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 660, "y": 190, "w": 220, "h": 260},
            "review_only": True,
        },
    ]
    card_grid_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in card_grid_inventory]}},
        "nodes": {item["item_id"]: item for item in card_grid_inventory},
    }
    card_grid_result = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=card_grid_inventory,
        layout_graph=card_grid_graph,
    )
    card_grid_region_ids = {item["region_id"] for item in card_grid_result["stage1_region_localization"]["regions"]}
    assert "structure_region_right_sidebar" not in card_grid_region_ids


def test_stage1_does_not_create_sidebar_from_single_top_corner_ocr_title(tmp_path):
    from PIL import Image

    image_path = tmp_path / "single_top_corner_title.png"
    Image.new("RGB", (1154, 900), "white").save(image_path)
    inventory = [
        {
            "item_id": "window_title",
            "label": "Settings",
            "role": "button",
            "item_type": "text",
            "bbox": {"x": 18, "y": 8, "w": 54, "h": 20},
            "review_only": True,
            "source": "ocr_fallback",
            "metadata": {
                "source": "screen_reading.texts",
                "surface_zone": "left_nav",
                "zone_evidence": "geometry_hint_only",
            },
        },
        {
            "item_id": "top_account_area",
            "label": "Account summary",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 0, "y": 0, "w": 1200, "h": 180},
            "review_only": True,
        },
        {
            "item_id": "main_settings_grid",
            "label": "Settings categories",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 0, "y": 180, "w": 1200, "h": 720},
            "review_only": True,
        },
        *[
            {
                "item_id": f"category_icon_{index}",
                "label": f"Category icon {index}",
                "role": "icon_button",
                "item_type": "button",
                "bbox": {"x": 88, "y": y, "w": 34, "h": 34},
                "review_only": True,
            }
            for index, y in enumerate((300, 430, 560), start=1)
        ],
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["window_title"]},
            "top_bar": {"item_ids": ["top_account_area"]},
            "primary_area": {
                "item_ids": ["main_settings_grid", "category_icon_1", "category_icon_2", "category_icon_3"]
            },
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 900}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = result["stage1_region_localization"]["regions"]
    assert "structure_region_left_nav" not in {region["region_id"] for region in regions}
    top_region = next(region for region in regions if region["region_id"] == "structure_region_top_bar")
    assert "window_title" in top_region["item_ids"]


def test_stage1_discovers_left_navigation_from_tall_rail_with_multiple_child_controls(tmp_path):
    from PIL import Image

    image_path = tmp_path / "unlabelled_left_navigation_rail.png"
    Image.new("RGB", (1200, 900), "white").save(image_path)
    inventory = [
        {
            "item_id": "rail_container",
            "label": "PaneRoot",
            "role": "pane",
            "item_type": "layout",
            "bbox": {"x": 8, "y": 2, "w": 48, "h": 896},
            "review_only": True,
        },
        *[
            {
                "item_id": f"rail_control_{index}",
                "label": f"Control {index}",
                "role": "listitem" if index > 2 else "button",
                "item_type": "actionable",
                "bbox": {"x": 12, "y": y, "w": 42, "h": 36},
                "review_only": True,
            }
            for index, y in enumerate((48, 88, 136, 176, 216, 256), start=1)
        ],
        {
            "item_id": "main_workspace",
            "label": "Primary workspace",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 56, "y": 90, "w": 1098, "h": 810},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["rail_container", "rail_control_1", "rail_control_2"]},
            "main_content": {
                "item_ids": [
                    "rail_control_3",
                    "rail_control_4",
                    "rail_control_5",
                    "rail_control_6",
                    "main_workspace",
                ]
            },
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1154, "height": 900}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = result["stage1_region_localization"]["regions"]
    left_nav = next(region for region in regions if region["region_id"] == "structure_region_left_nav")
    assert set(left_nav["item_ids"]) >= {
        "rail_container",
        "rail_control_1",
        "rail_control_2",
        "rail_control_3",
        "rail_control_4",
        "rail_control_5",
        "rail_control_6",
    }
    assert 52 <= left_nav["bbox"]["w"] <= 120
    assert left_nav["bbox"]["h"] >= 700
    assert left_nav["coordinate_validation"]["calibration_strategy"] == "left_nav_icon_column_full_height"


def test_stage1_calibrates_left_navigation_from_list_items_after_top_controls_are_partitioned(tmp_path):
    from PIL import Image

    image_path = tmp_path / "left_navigation_list_items.png"
    Image.new("RGB", (1154, 900), "white").save(image_path)
    inventory = [
        {
            "item_id": "rail_container",
            "label": "Navigation pane",
            "role": "pane",
            "item_type": "layout",
            "bbox": {"x": 8, "y": 90, "w": 48, "h": 810},
            "review_only": True,
        },
        *[
            {
                "item_id": f"rail_item_{index}",
                "label": f"Item {index}",
                "role": "listitem",
                "item_type": "actionable",
                "bbox": {"x": 11, "y": y, "w": 44, "h": 36},
                "review_only": True,
            }
            for index, y in enumerate((134, 174, 214, 254, 294), start=1)
        ],
        {
            "item_id": "main_workspace",
            "label": "Primary workspace",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 56, "y": 90, "w": 1098, "h": 810},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1154, "height": 900}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    left_nav = next(
        region
        for region in result["stage1_region_localization"]["regions"]
        if region["region_id"] == "structure_region_left_nav"
    )
    assert left_nav["bbox"]["w"] >= 52
    assert left_nav["coordinate_validation"]["calibration_strategy"] == "left_nav_icon_column_full_height"


def test_stage1_repartitions_unknown_only_items_by_vertical_structure(tmp_path):
    from PIL import Image

    image_path = tmp_path / "unknown_only_vertical_structure.png"
    Image.new("RGB", (1400, 900), "white").save(image_path)
    inventory = [
        {
            "item_id": "header_search",
            "label": "Search",
            "role": "input",
            "item_type": "input",
            "bbox": {"x": 760, "y": 90, "w": 280, "h": 40},
            "review_only": True,
        },
        {
            "item_id": "header_nav",
            "label": "Navigation",
            "role": "link",
            "item_type": "link",
            "bbox": {"x": 420, "y": 190, "w": 560, "h": 44},
            "review_only": True,
        },
        {
            "item_id": "main_action",
            "label": "Learn more",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 610, "y": 500, "w": 180, "h": 44},
            "review_only": True,
        },
        {
            "item_id": "lower_content",
            "label": "Documentation card",
            "role": "link",
            "item_type": "link",
            "bbox": {"x": 350, "y": 690, "w": 260, "h": 80},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"unknown": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1400, "height": 900}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = result["stage1_region_localization"]["regions"]
    region_ids = {region["region_id"] for region in regions}
    assert region_ids == {"structure_region_page_header", "structure_region_main_content"}
    assert result["region_selection_audit"]["failure_categories"] == []
    assert result["region_selection_audit"]["passed"] is True, result["region_selection_audit"]
    header = next(region for region in regions if region["region_id"] == "structure_region_page_header")
    main = next(region for region in regions if region["region_id"] == "structure_region_main_content")
    assert header["bbox"]["y"] == 0
    assert main["bbox"]["y"] == header["bbox"]["y"] + header["bbox"]["h"]


def test_stage1_recovers_adjacent_header_and_main_from_shallow_fullscreen_backfill(tmp_path):
    from PIL import Image

    image_path = tmp_path / "shallow_fullscreen_backfill.png"
    Image.new("RGB", (1000, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "top_control_row",
            "label": "Top controls",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 180, "y": 60, "w": 640, "h": 100},
            "review_only": True,
        },
        {
            "item_id": "top_navigation_row",
            "label": "Navigation row",
            "role": "navigation",
            "item_type": "layout",
            "bbox": {"x": 220, "y": 180, "w": 560, "h": 60},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = result["stage1_region_localization"]["regions"]
    assert [(region["zone_id"], region["bbox"]) for region in regions] == [
        ("page_header", {"x": 0, "y": 0, "w": 1000, "h": 240}),
        ("main_content", {"x": 0, "y": 240, "w": 1000, "h": 560}),
    ]
    assert result["region_selection_audit"]["passed"] is True


def test_two_stage_uses_ocr_content_recovery_when_existing_items_cover_only_top(tmp_path, monkeypatch):
    from PIL import Image

    from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

    image_path = tmp_path / "undercovered_main.png"
    Image.new("RGB", (1000, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "top_navigation",
            "label": "Navigation",
            "role": "navigation",
            "item_type": "layout",
            "bbox": {"x": 100, "y": 40, "w": 800, "h": 120},
            "review_only": True,
        }
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": ["top_navigation"]}},
        "nodes": {"top_navigation": inventory[0]},
    }
    ocr_result = OCRResult(
        image_path=str(image_path),
        matches=[
            OCRTextMatch("Body section", 0.95, OCRBoundingBox(120, 420, 180, 28)),
            OCRTextMatch("Lower content", 0.93, OCRBoundingBox(120, 690, 200, 28)),
        ],
        metadata={"engine": "test_ocr"},
    )
    monkeypatch.setattr("app.learn.recognition.two_stage.ocr_service.scan_image", lambda _path: ocr_result)

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        enable_ocr_content_recovery=True,
    )

    recovery = result["content_recovery"]
    assert recovery["status"] == "applied"
    assert recovery["ocr_match_count"] == 2
    assert recovery["added_item_count"] == 2
    labels = {
        item["label"]
        for region in result["stage2_numbering"]["regions"]
        for item in region.get("numbered_items", [])
    }
    assert {"Body section", "Lower content"} <= labels


def test_stage1_keeps_incomplete_semantic_card_columns_in_main_grid(tmp_path):
    from PIL import Image

    image_path = tmp_path / "incomplete_semantic_card_grid.png"
    Image.new("RGB", (1000, 760), "white").save(image_path)
    inventory = []
    for row, y in enumerate((160, 430), start=1):
        inventory.extend(
            [
                {
                    "item_id": f"row_{row}_left_card",
                    "label": f"Row {row} left card",
                    "role": "media_card",
                    "item_type": "card",
                    "bbox": {"x": 80, "y": y, "w": 240, "h": 230},
                    "review_only": True,
                },
                {
                    "item_id": f"row_{row}_middle_item",
                    "label": f"Row {row} middle item",
                    "role": "listitem",
                    "item_type": "layout",
                    "bbox": {"x": 340, "y": y, "w": 240, "h": 230},
                    "review_only": True,
                },
                {
                    "item_id": f"row_{row}_right_card",
                    "label": f"Row {row} right card",
                    "role": "recommendation_item",
                    "item_type": "card",
                    "bbox": {"x": 700, "y": y, "w": 240, "h": 230},
                    "review_only": True,
                },
            ]
        )
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 760}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    region_ids = {region["region_id"] for region in result["stage1_region_localization"]["regions"]}
    assert "structure_region_right_sidebar" not in region_ids


def test_stage1_merges_narrow_bottom_like_content_back_into_primary_area(tmp_path):
    from PIL import Image

    image_path = tmp_path / "web_content_not_bottom_bar.png"
    Image.new("RGB", (1400, 900), "white").save(image_path)
    inventory = [
        {
            "item_id": "top_nav",
            "label": "Top navigation",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 1400, "h": 120},
            "review_only": True,
        },
        {
            "item_id": "primary_page",
            "label": "Primary web content",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 150, "w": 820, "h": 620},
            "review_only": True,
        },
        {
            "item_id": "latest_news",
            "label": "Latest News",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 380, "y": 650, "w": 460, "h": 120},
            "review_only": True,
        },
        {
            "item_id": "upcoming_events",
            "label": "Upcoming Events",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 850, "y": 650, "w": 250, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "top_bar": {"item_ids": ["top_nav"]},
            "primary_area": {"item_ids": ["primary_page"]},
            "bottom_bar": {"item_ids": ["latest_news", "upcoming_events"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1400, "height": 900}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = report["stage1_region_localization"]["regions"]
    region_ids = {item["region_id"] for item in regions}
    assert "structure_region_bottom_bar" not in region_ids
    correction = report["stage1_structure"]["zone_corrections"][0]
    assert correction["correction"] == "bottom_bar_content_merged_into_primary_region"
    assert correction["target_zone"] == "primary_area"
    assert correction["item_ids"] == ["latest_news", "upcoming_events"]
    assert report["stage1_structure"]["zone_correction_status"] == "passed_with_correction"
    primary = next(item for item in regions if item["region_id"] == "structure_region_primary_area")
    assert set(primary["item_ids"]) == {"primary_page", "latest_news", "upcoming_events"}
    assert primary["precise_bbox"]["y"] <= 150
    assert primary["precise_bbox"]["y"] + primary["precise_bbox"]["h"] >= 770
    assert report["region_selection_audit"]["passed"] is True


def test_stage1_keeps_true_full_width_bottom_bar_separate(tmp_path):
    from PIL import Image

    image_path = tmp_path / "true_bottom_bar.png"
    Image.new("RGB", (1000, 700), "white").save(image_path)
    inventory = [
        {
            "item_id": "top_nav",
            "label": "Top navigation",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 1000, "h": 80},
            "review_only": True,
        },
        {
            "item_id": "primary_page",
            "label": "Primary content",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 100, "y": 110, "w": 800, "h": 460},
            "review_only": True,
        },
        {
            "item_id": "true_bottom_toolbar",
            "label": "Playback controls",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 620, "w": 1000, "h": 72},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "top_bar": {"item_ids": ["top_nav"]},
            "primary_area": {"item_ids": ["primary_page"]},
            "bottom_bar": {"item_ids": ["true_bottom_toolbar"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 700}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = report["stage1_region_localization"]["regions"]
    bottom = next(item for item in regions if item["region_id"] == "structure_region_bottom_bar")
    primary = next(item for item in regions if item["region_id"] == "structure_region_primary_area")
    assert bottom["item_ids"] == ["true_bottom_toolbar"]
    assert "true_bottom_toolbar" not in primary["item_ids"]
    assert report["stage1_structure"]["zone_corrections"] == []
    assert report["stage1_structure"]["zone_correction_status"] == "clean"
    assert report["region_selection_audit"]["passed"] is True


def test_stage1_primary_area_expands_full_width_without_sidebar(tmp_path):
    from PIL import Image

    image_path = tmp_path / "centered_web_page.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "browser_back",
            "label": "Back",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 18, "y": 20, "w": 32, "h": 28},
            "review_only": True,
            "metadata": {"surface_zone": "browser_chrome"},
        },
        {
            "item_id": "page_header",
            "label": "Header",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 1200, "h": 100},
            "review_only": True,
        },
        {
            "item_id": "centered_hero",
            "label": "Centered hero",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 330, "y": 160, "w": 540, "h": 260},
            "review_only": True,
        },
        {
            "item_id": "centered_card",
            "label": "Centered card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 360, "y": 460, "w": 260, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["browser_back"]},
            "top_bar": {"item_ids": ["page_header"]},
            "primary_area": {"item_ids": ["centered_hero", "centered_card"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item
        for item in report["stage1_region_localization"]["regions"]
        if item["region_id"] == "structure_region_primary_area"
    )
    assert primary["precise_bbox"]["x"] == 0
    assert primary["precise_bbox"]["w"] == 1200
    assert primary["coordinate_validation"]["calibration_strategy"] == "main_content_full_width_when_no_sidebars"


def test_stage1_main_boundary_ignores_readable_duplicate_of_explicit_top_candidate(tmp_path):
    from PIL import Image

    image_path = tmp_path / "top_summary_with_duplicate_readable_evidence.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "top_shell",
            "label": "Top summary",
            "role": "navigation",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 1200, "h": 150},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "top_bar"},
        },
        {
            "item_id": "summary_readable",
            "label": "Account summary",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 220, "y": 108, "w": 150, "h": 24},
            "review_only": True,
            "metadata": {"source": "screen_reading.texts", "surface_zone": "primary_area"},
        },
        {
            "item_id": "summary_top_candidate",
            "label": "Account summary",
            "role": "nav_text_action",
            "item_type": "review_only",
            "bbox": {"x": 220, "y": 108, "w": 150, "h": 24},
            "review_only": True,
            "metadata": {"source": "screen_map.candidates", "surface_zone": "top_bar"},
        },
        {
            "item_id": "summary_peer_readable",
            "label": "Secondary summary",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 220, "y": 126, "w": 150, "h": 22},
            "review_only": True,
            "metadata": {"source": "screen_reading.texts", "surface_zone": "primary_area"},
        },
        *[
            {
                "item_id": f"top_peer_{index}",
                "label": f"Top peer {index}",
                "role": "nav_text_action",
                "item_type": "review_only",
                "bbox": {"x": x, "y": 112, "w": 70, "h": 22},
                "review_only": True,
                "metadata": {"source": "screen_map.candidates", "surface_zone": "top_bar"},
            }
            for index, x in enumerate((500, 700, 900), start=1)
        ],
        {
            "item_id": "search_field",
            "label": "Search",
            "role": "input",
            "item_type": "actionable",
            "bbox": {"x": 450, "y": 170, "w": 300, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "main_grid",
            "label": "Settings grid",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 0, "y": 150, "w": 1200, "h": 650},
            "review_only": True,
        },
        {
            "item_id": "first_tile",
            "label": "Category",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 80, "y": 230, "w": 240, "h": 90},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "top_bar": {
                "item_ids": ["top_shell", "summary_top_candidate", "top_peer_1", "top_peer_2", "top_peer_3"]
            },
            "primary_area": {
                "item_ids": [
                    "summary_readable",
                    "summary_peer_readable",
                    "search_field",
                    "main_grid",
                    "first_tile",
                ]
            },
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = report["stage1_region_localization"]["regions"]
    top = next(item for item in regions if item["region_id"] == "structure_region_top_bar")
    primary = next(item for item in regions if item["region_id"] == "structure_region_primary_area")
    assert primary["bbox"]["y"] >= 140
    assert top["bbox"]["y"] + top["bbox"]["h"] == primary["bbox"]["y"]


def test_stage1_primary_area_with_left_nav_preserves_visible_media_grid_right_edge(tmp_path):
    from PIL import Image

    image_path = tmp_path / "media_grid_with_left_nav.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "nav_home",
            "label": "Home",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 24, "y": 140, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_toolbar",
            "label": "Player controls",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 96, "y": 0, "w": 1104, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "media_grid_shell",
            "label": "Recently played media grid",
            "role": "media_grid",
            "item_type": "section",
            "bbox": {"x": 96, "y": 110, "w": 1104, "h": 620},
            "metadata": {"source": "screen_map.sections"},
            "review_only": True,
        },
        {
            "item_id": "visible_card_1",
            "label": "Energy album",
            "role": "media_card",
            "item_type": "card",
            "bbox": {"x": 128, "y": 170, "w": 220, "h": 210},
            "review_only": True,
        },
        {
            "item_id": "visible_card_2_text",
            "label": "Second card text only",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 520, "y": 360, "w": 210, "h": 30},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["nav_home"]},
            "top_bar": {"item_ids": ["top_toolbar"]},
            "primary_area": {"item_ids": ["media_grid_shell", "visible_card_1", "visible_card_2_text"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item
        for item in report["stage1_region_localization"]["regions"]
        if item["region_id"] == "structure_region_primary_area"
    )

    assert primary["precise_bbox"]["x"] >= 90
    assert primary["precise_bbox"]["x"] + primary["precise_bbox"]["w"] == 1200
    assert primary["coordinate_validation"]["right_edge_preservation"]["status"] == (
        "main_content_right_edge_preserved_from_visual_region_hint"
    )


def test_stage1_primary_area_right_edge_preservation_reports_sidebar_clamp(tmp_path):
    from PIL import Image

    image_path = tmp_path / "media_grid_with_right_sidebar.png"
    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "nav_home",
            "label": "Home",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 24, "y": 140, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "media_grid_shell",
            "label": "Recently played media grid",
            "role": "media_grid",
            "item_type": "section",
            "bbox": {"x": 96, "y": 110, "w": 1104, "h": 620},
            "metadata": {"source": "screen_map.sections"},
            "review_only": True,
        },
        {
            "item_id": "visible_card",
            "label": "Energy album",
            "role": "media_card",
            "item_type": "card",
            "bbox": {"x": 128, "y": 170, "w": 220, "h": 210},
            "review_only": True,
        },
        {
            "item_id": "right_detail",
            "label": "Detail panel",
            "role": "right_sidebar",
            "item_type": "section",
            "bbox": {"x": 900, "y": 110, "w": 300, "h": 620},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["nav_home"]},
            "primary_area": {"item_ids": ["media_grid_shell", "visible_card"]},
            "right_sidebar": {"item_ids": ["right_detail"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item
        for item in report["stage1_region_localization"]["regions"]
        if item["region_id"] == "structure_region_primary_area"
    )

    assert primary["precise_bbox"]["x"] + primary["precise_bbox"]["w"] == 900
    preservation = primary["coordinate_validation"]["right_edge_preservation"]
    assert preservation["status"] == "main_content_right_edge_preserved_then_clamped_to_sibling_region"
    assert preservation["preserved_right"] == 1200
    assert preservation["final_right"] == 900


def test_stage1_topbar_preserves_full_width_and_sidebars_start_below_it(tmp_path):
    from PIL import Image

    image_path = tmp_path / "app_with_left_nav_and_topbar.png"
    Image.new("RGB", (1000, 700), "white").save(image_path)
    inventory = [
        {
            "item_id": "nav_home",
            "label": "Home",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 24, "y": 140, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_toolbar",
            "label": "Toolbar",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 100, "y": 0, "w": 880, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "primary_grid",
            "label": "Primary content",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 120, "y": 120, "w": 820, "h": 520},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["nav_home"]},
            "top_bar": {"item_ids": ["top_toolbar"]},
            "primary_area": {"item_ids": ["primary_grid"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 700}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = report["stage1_region_localization"]["regions"]
    left_nav = next(region for region in regions if region["region_id"] == "structure_region_left_nav")
    top_bar = next(region for region in regions if region["region_id"] == "structure_region_top_bar")
    assert top_bar["bbox"]["x"] == 0
    assert top_bar["bbox"]["x"] + top_bar["bbox"]["w"] == 1000
    assert left_nav["bbox"]["y"] == top_bar["bbox"]["y"] + top_bar["bbox"]["h"]
    assert top_bar["coordinate_validation"]["sibling_lane"]["reason"] == (
        "horizontal_bar_full_bbox_preserved_non_sidebar_lane_recorded"
    )
    assert left_nav["coordinate_validation"]["sibling_partition"]["reason"] == (
        "sidebar_must_use_non_horizontal_bar_lane"
    )
    assert report["region_selection_audit"]["passed"] is True


def test_stage2_does_not_number_structure_section_hints_as_primary_cards(tmp_path):
    from PIL import Image

    image_path = tmp_path / "section_hint.png"
    Image.new("RGB", (900, 650), "white").save(image_path)
    inventory = [
        {
            "item_id": "primary_section_hint",
            "label": "Primary area",
            "role": "content",
            "item_type": "layout",
            "bbox": {"x": 90, "y": 90, "w": 760, "h": 520},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "primary_area"},
        },
        {
            "item_id": "card_1",
            "label": "Album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 180, "w": 220, "h": 260},
            "review_only": True,
        },
        {
            "item_id": "card_2",
            "label": "Second album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 370, "y": 180, "w": 220, "h": 260},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 650}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "image_message")
    labels = [item["label"] for item in primary["numbered_items"]]
    assert "Primary area" not in labels
    assert "Album card" in labels
    assert "Second album card" in labels


def test_stage2_filters_items_to_current_region_bbox_after_sidebar_split(tmp_path):
    from PIL import Image

    image_path = tmp_path / "split_regions.png"
    Image.new("RGB", (1000, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "chat_text",
            "label": "Central chat message",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 300, "y": 300, "w": 220, "h": 40},
            "review_only": True,
        },
        {
            "item_id": "right_notice",
            "label": "Right notice",
            "role": "recommendation_item",
            "item_type": "card",
            "bbox": {"x": 760, "y": 120, "w": 220, "h": 230},
            "review_only": True,
        },
        {
            "item_id": "right_member",
            "label": "Right member",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 780, "y": 410, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "right_members_panel",
            "label": "Right members panel",
            "role": "recommendation_item",
            "item_type": "card",
            "bbox": {"x": 760, "y": 370, "w": 220, "h": 310},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    primary_labels = {item["label"] for item in primary["numbered_items"]}
    right_labels = {item["label"] for item in right["numbered_items"]}
    assert "Central chat message" in primary_labels
    assert "Right member" not in primary_labels
    assert "Right member" in right_labels


def test_two_stage_reconstructs_notice_parent_in_direct_sidebar(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "notice_sidebar.png"
    image = Image.new("RGB", (1000, 720), "white")
    draw = ImageDraw.Draw(image)
    for y in (124, 160, 194):
        draw.rectangle((774, y, 925, y + 10), fill="black")
    image.save(image_path)
    inventory = [
        {
            "item_id": "main_chat",
            "label": "Central conversation",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 120, "y": 90, "w": 610, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "notice_title",
            "label": "Group announcement",
            "role": "nav_item",
            "item_type": "heading",
            "bbox": {"x": 770, "y": 118, "w": 160, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "notice_body_a",
            "label": "Maintenance tonight",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 772, "y": 154, "w": 170, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "notice_body_b",
            "label": "Pinned note",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 772, "y": 188, "w": 120, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "primary_area": {"item_ids": ["main_chat"]},
            "right_sidebar": {"item_ids": ["notice_title", "notice_body_a", "notice_body_b"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    notice_groups = [group for group in right["subregion_groups"] if group["role"] == "notice_region"]
    assert notice_groups
    notice = notice_groups[0]
    assert notice["parent_child_policy"] == "notice_heading_binds_to_nearby_body_lines"
    assert set(notice["member_item_ids"]) == {"notice_title", "notice_body_a", "notice_body_b"}
    assert notice["bbox"]["x"] <= 770
    assert notice["bbox"]["h"] >= 90
    notice_items = [
        item for item in right["numbered_items"] if item["item_id"] in {"notice_title", "notice_body_a", "notice_body_b"}
    ]
    assert notice_items
    assert {item["role"] for item in notice_items} == {"notice_item"}
    assert all(item["execute_binding_enabled"] is False for item in notice_items)
    fused_notices = [
        item for item in result["fusion"]["fused_review_boxes"] if item.get("role") == "notice_region"
    ]
    assert fused_notices


def test_two_stage_downgrades_nav_item_crossing_notice_member_boundary(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "mixed_notice_member_nav_item.png"
    image = Image.new("RGB", (1000, 720), "white")
    draw = ImageDraw.Draw(image)
    for y in (124, 160, 194):
        draw.rectangle((774, y, 925, y + 10), fill="black")
    draw.rectangle((774, 224, 925, 236), fill="black")
    draw.rectangle((774, 312, 925, 326), fill="black")
    image.save(image_path)
    inventory = [
        {
            "item_id": "main_chat",
            "label": "Central conversation",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 120, "y": 90, "w": 610, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "notice_title",
            "label": "Group announcement",
            "role": "nav_item",
            "item_type": "heading",
            "bbox": {"x": 770, "y": 118, "w": 160, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "notice_body_a",
            "label": "Maintenance tonight",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 772, "y": 154, "w": 170, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "notice_body_b",
            "label": "Pinned note",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 772, "y": 188, "w": 120, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "mixed_notice_member",
            "label": "Pinned note / Group members 1263",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 768, "y": 170, "w": 190, "h": 118},
            "review_only": True,
        },
        {
            "item_id": "member_row",
            "label": "Cateek / owner",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 770, "y": 306, "w": 170, "h": 42},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "primary_area": {"item_ids": ["main_chat"]},
            "right_sidebar": {
                "item_ids": [
                    "notice_title",
                    "notice_body_a",
                    "notice_body_b",
                    "mixed_notice_member",
                    "member_row",
                ]
            },
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    mixed = next(item for item in right["numbered_items"] if item["item_id"] == "mixed_notice_member")
    assert mixed["role"] == "boundary_review_region"
    assert mixed["original_role"] == "nav_item"
    assert mixed["action_candidate"] is False
    assert mixed["execute_binding_enabled"] is False
    assert mixed["bbox_policy"] == "cross_parent_boundary_nav_item_needs_review"
    assert mixed["boundary_violation"]["category"] == "notice_member_boundary_leak"
    member = next(item for item in right["numbered_items"] if item["item_id"] == "member_row")
    assert member["role"] == "nav_item"


def test_two_stage_reconstructs_message_item_parent_in_primary_content(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_parent.png"
    Image.new("RGB", (900, 640), "white").save(image_path)
    inventory = [
        {
            "item_id": "sender_avatar",
            "label": "Sender avatar",
            "role": "avatar",
            "item_type": "image",
            "bbox": {"x": 130, "y": 220, "w": 44, "h": 44},
            "review_only": True,
        },
        {
            "item_id": "sender_name",
            "label": "Alex",
            "role": "sender_label",
            "item_type": "text",
            "bbox": {"x": 190, "y": 214, "w": 60, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "message_text",
            "label": "Can you check the draft?",
            "role": "message_text",
            "item_type": "text",
            "bbox": {"x": 190, "y": 244, "w": 230, "h": 30},
            "review_only": True,
        },
        {
            "item_id": "image_message",
            "label": "Shared screenshot",
            "role": "image_message",
            "item_type": "image",
            "bbox": {"x": 190, "y": 286, "w": 180, "h": 110},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 640}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "image_message")
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    assert message_groups
    message = message_groups[0]
    assert message["parent_child_policy"] == "message_core_absorbs_nearby_context_fragments"
    assert set(message["member_item_ids"]) == {"sender_avatar", "sender_name", "message_text", "image_message"}
    assert set(message["child_item_ids"]) == {"message_text", "image_message"}
    assert set(message["context_item_ids"]) == {"sender_avatar", "sender_name"}
    assert set(message["core_item_ids"]) == {"message_text", "image_message"}
    assert message["message_child_breakdown"]["core_item_count"] == 2
    assert message["message_child_breakdown"]["context_item_count"] == 2
    assert "image_message" in message["child_group_roles"]
    assert message["bbox"]["x"] <= 130
    assert message["bbox"]["h"] >= 170
    fused_messages = [
        item for item in result["fusion"]["fused_review_boxes"] if item.get("role") == "message_item"
    ]
    assert fused_messages


def test_two_stage_reconstructs_chat_image_and_text_bubble_parents(tmp_path):
    from PIL import Image

    image_path = tmp_path / "chat_fragments.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 80, "w": 520, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 130, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "sticker_image",
            "label": "Shared sticker image",
            "role": "image",
            "item_type": "image",
            "bbox": {"x": 360, "y": 180, "w": 150, "h": 120},
            "review_only": True,
        },
        {
            "item_id": "message_time",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 320, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "This is a longer message bubble that spans a visible chat row",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 370, "w": 310, "h": 64},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    roles_by_id = {item["item_id"]: item["role"] for item in primary["numbered_items"]}
    assert roles_by_id["sticker_image"] == "image_message"
    assert roles_by_id["long_text_bubble"] == "message_bubble"
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    assert len(message_groups) >= 2
    grouped_ids = {item_id for group in message_groups for item_id in group["member_item_ids"]}
    assert {"sticker_image", "long_text_bubble"}.issubset(grouped_ids)


def test_two_stage_recovers_visual_chat_image_message_without_inventory_item(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "visual_chat_image.png"
    image = Image.new("RGB", (980, 720), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((380, 190, 520, 330), radius=24, fill=(66, 190, 88))
    image.save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 90, "w": 560, "h": 590},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 130, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "message_time",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 350, "w": 44, "h": 18},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "row_one_title")
    image_messages = [item for item in primary["numbered_items"] if item["role"] == "image_message"]
    assert image_messages
    assert image_messages[0]["source"] == "chat_visual_image_message_synthesis"
    assert image_messages[0]["bbox"]["w"] >= 120
    assert image_messages[0]["bbox"]["h"] >= 120
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    grouped_ids = {item_id for group in message_groups for item_id in group["member_item_ids"]}
    assert image_messages[0]["item_id"] in grouped_ids


def test_two_stage_expands_text_only_send_button_hit_area(tmp_path):
    from PIL import Image

    image_path = tmp_path / "send_text_button.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 90, "w": 560, "h": 590},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 120, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "send_text",
            "label": "Send",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 820, "y": 660, "w": 38, "h": 18},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "row_one_title")
    send = next(item for item in primary["numbered_items"] if item["item_id"] == "send_text")
    assert send["role"] == "text_button"
    assert send["bbox"]["w"] >= 72
    assert send["bbox"]["h"] >= 34
    assert send["execute_binding_enabled"] is False
    assert send["bbox_policy"] == "text_only_button_hit_area_normalized"


def test_two_stage_message_item_absorbs_nearby_sender_and_timestamp(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_context.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 80, "w": 520, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 100, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "timestamp",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 150, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "sender_name",
            "label": "Alex LV75",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 185, "w": 90, "h": 20},
            "review_only": True,
        },
        {
            "item_id": "image_message",
            "label": "Shared sticker image",
            "role": "image_message",
            "item_type": "image",
            "bbox": {"x": 360, "y": 215, "w": 140, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "image_message")
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    assert message_groups
    message = next(group for group in message_groups if "image_message" in group["member_item_ids"])
    assert {"timestamp", "sender_name", "image_message"}.issubset(set(message["member_item_ids"]))
    assert message["bbox"]["y"] <= 150
    assert message["parent_child_policy"] == "message_core_absorbs_nearby_context_fragments"


def test_two_stage_message_bubble_absorbs_timestamp_context(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_bubble_context.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 100, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "timestamp",
            "label": "15:10",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 280, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "This is a visible text bubble that needs one message parent",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 330, "w": 310, "h": 56},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    assert message_groups
    message = next(group for group in message_groups if "long_text_bubble" in group["member_item_ids"])
    assert {"timestamp", "long_text_bubble"}.issubset(set(message["member_item_ids"]))
    assert message["bbox_policy"] == "message_item_core_display_bbox_context_externalized"
    assert message["bbox"]["y"] > 280


def test_two_stage_text_only_message_parent_expands_to_bubble_background(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_bubble_background.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 80, "w": 520, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 100, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "timestamp",
            "label": "15:10",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 250, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "This text is a message bubble but OCR only saw one text line",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 305, "w": 210, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    message = next(
        group for group in primary["subregion_groups"]
        if group["role"] == "message_item" and "long_text_bubble" in group["member_item_ids"]
    )
    assert message["bbox"]["x"] < message["raw_bbox_before_policy"]["x"]
    assert {"timestamp", "long_text_bubble"}.issubset(set(message["member_item_ids"]))
    assert message["bbox"]["w"] >= 250
    assert message["bbox"]["h"] < message["raw_bbox_before_policy"]["h"]
    assert message["bbox_policy"] == "message_item_core_display_bbox_context_externalized"
    assert message["display_only"] is True
    assert message["execute_binding_enabled"] is False


def test_message_parent_externalizes_context_gap_when_bubble_child_is_already_expanded():
    timestamp = {
        "item_id": "timestamp",
        "label": "15:10",
        "role": "text",
        "bbox": {"x": 420, "y": 250, "w": 44, "h": 18},
    }
    bubble = {
        "item_id": "bubble",
        "label": "message text",
        "role": "message_bubble",
        "bbox": {"x": 348, "y": 295, "w": 274, "h": 76},
        "bbox_policy": "message_bubble_background_expanded_needs_review",
    }

    bbox, policy = two_stage._message_parent_display_bbox(
        [timestamp, bubble],
        region_bbox={"x": 300, "y": 80, "w": 520, "h": 600},
    )

    assert policy == "message_item_core_display_bbox_context_externalized"
    assert bbox["y"] > timestamp["bbox"]["y"]
    assert bbox["y"] <= bubble["bbox"]["y"]
    assert bbox["h"] < 100


def test_two_stage_text_only_message_bubble_child_expands_to_review_background(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_bubble_child_background.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 80, "w": 520, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "timestamp",
            "label": "15:10",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 250, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "This text is a message bubble but OCR only saw one text line",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 305, "w": 210, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    bubble = next(item for item in primary["numbered_items"] if item["item_id"] == "long_text_bubble")
    assert bubble["role"] == "message_bubble"
    assert bubble["bbox"]["x"] < bubble["raw_bbox_before_policy"]["x"]
    assert bubble["bbox"]["w"] >= 250
    assert bubble["bbox"]["h"] > bubble["raw_bbox_before_policy"]["h"]
    assert bubble["bbox"]["h"] < 72
    assert bubble["bbox_policy"] == "message_bubble_background_expanded_needs_review"
    assert bubble["review_required"] is True
    assert bubble["display_only"] is True
    assert bubble["execute_binding_enabled"] is False


def test_message_bubble_review_background_uses_conservative_padding():
    raw = {"x": 302, "y": 609, "w": 249, "h": 24}
    expanded = two_stage._message_bubble_review_background_bbox(
        raw,
        parent_bbox={"x": 250, "y": 90, "w": 380, "h": 760},
    )

    assert expanded["x"] < raw["x"]
    assert expanded["w"] > raw["w"]
    assert expanded["w"] <= raw["w"] + 48
    assert expanded["h"] <= raw["h"] + 44


def test_two_stage_system_new_messages_notice_is_not_message_bubble(tmp_path):
    from PIL import Image

    image_path = tmp_path / "new_messages_notice.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "new_messages_notice",
            "label": "87条新消息",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 520, "y": 104, "w": 90, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "This text is a message bubble but OCR only saw one text line",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 305, "w": 210, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "new_messages_notice")
    notice = next(item for item in primary["numbered_items"] if item["item_id"] == "new_messages_notice")
    assert notice["role"] == "text"
    assert notice["bbox"] == {"x": 520, "y": 104, "w": 90, "h": 28}
    assert notice["bbox_policy"] == "numbered_region_candidate_hint_only"
    assert "raw_bbox_before_policy" not in notice


def test_two_stage_message_card_child_text_is_not_expanded_as_bubble(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_card_child_text.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "forwarded_message_card",
            "label": "Forwarded message card with image preview",
            "role": "message_card",
            "item_type": "card",
            "bbox": {"x": 300, "y": 360, "w": 270, "h": 116},
            "review_only": True,
        },
        {
            "item_id": "inner_forward_text",
            "label": "查看2条转发消息",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 315, "y": 438, "w": 96, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "inner_forward_title",
            "label": "Forwarded card title",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 315, "y": 405, "w": 140, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "regular_text_bubble",
            "label": "This text is a message bubble but OCR only saw one text line",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 560, "w": 210, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "inner_forward_text")
    inner = next(item for item in primary["numbered_items"] if item["item_id"] == "inner_forward_text")
    assert inner["role"] == "message_card_content"
    assert inner["bbox"] == {"x": 315, "y": 438, "w": 96, "h": 18}
    assert inner["bbox_policy"] == "message_card_child_content_not_message_bubble"
    assert "raw_bbox_before_policy" not in inner
    inner_title = next(item for item in primary["numbered_items"] if item["item_id"] == "inner_forward_title")
    assert inner_title["role"] == "message_card_content"
    media_groups = [group for group in primary["subregion_groups"] if group["role"] == "media_card_group"]
    assert all("inner_forward_text" not in group["member_item_ids"] for group in media_groups)
    assert all("inner_forward_title" not in group["member_item_ids"] for group in media_groups)
    bubble = next(item for item in primary["numbered_items"] if item["item_id"] == "regular_text_bubble")
    assert bubble["role"] == "message_bubble"
    assert bubble["bbox_policy"] == "message_bubble_background_expanded_needs_review"


def test_two_stage_image_message_parent_expands_to_review_slot(tmp_path):
    from PIL import Image

    image_path = tmp_path / "image_message_review_slot.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "standalone_image_message",
            "label": "image_message shared sticker",
            "role": "image_message",
            "item_type": "image",
            "bbox": {"x": 380, "y": 240, "w": 140, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "standalone_image_message")
    message = next(
        group for group in primary["subregion_groups"]
        if group["role"] == "message_item" and "standalone_image_message" in group["member_item_ids"]
    )
    assert message["bbox"]["x"] < message["raw_bbox_before_policy"]["x"]
    assert message["raw_bbox_before_policy"]["x"] - message["bbox"]["x"] >= 48
    assert message["bbox"]["w"] > message["raw_bbox_before_policy"]["w"]
    assert message["bbox"]["h"] > message["raw_bbox_before_policy"]["h"]
    assert message["bbox_policy"] == "message_item_image_background_expanded_needs_review"
    assert message["review_required"] is True
    assert message["display_only"] is True
    assert message["execute_binding_enabled"] is False


def test_two_stage_timestamp_above_sender_attaches_to_following_bubble(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_timestamp_sender_gap.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "previous_message_card",
            "label": "Previous forwarded message card",
            "role": "message_card",
            "item_type": "card",
            "bbox": {"x": 300, "y": 360, "w": 270, "h": 116},
            "review_only": True,
        },
        {
            "item_id": "timestamp",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 423, "y": 496, "w": 36, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "sender_name",
            "label": "Forever LV75钻石",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 303, "y": 525, "w": 102, "h": 20},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "这是一条很长的聊天消息内容用于测试父框归属",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 302, "y": 609, "w": 249, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    previous = next(group for group in primary["subregion_groups"] if "previous_message_card" in group["member_item_ids"])
    following = next(group for group in primary["subregion_groups"] if "long_text_bubble" in group["member_item_ids"])
    assert "timestamp" not in previous["member_item_ids"]
    assert {"timestamp", "sender_name", "long_text_bubble"}.issubset(set(following["member_item_ids"]))
    timestamp = next(item for item in primary["numbered_items"] if item["item_id"] == "timestamp")
    sender = next(item for item in primary["numbered_items"] if item["item_id"] == "sender_name")
    bubble = next(item for item in primary["numbered_items"] if item["item_id"] == "long_text_bubble")
    assert timestamp["semantic_parent_group_id"] == following["group_id"]
    assert timestamp["message_context_role"] == "timestamp"
    assert sender["semantic_parent_group_id"] == following["group_id"]
    assert sender["message_context_role"] == "sender_or_level"
    assert bubble["semantic_parent_group_id"] == following["group_id"]


def test_message_parent_bbox_map_reads_subregion_group_parents():
    parent_map = two_stage._message_parent_bbox_map(
        [
            {
                "subregion_groups": [
                    {
                        "group_id": "message_item_3",
                        "role": "message_item",
                        "bbox": {"x": 38, "y": 70, "w": 160, "h": 90},
                    }
                ],
                "numbered_items": [
                    {
                        "number": "3.34",
                        "role": "text",
                        "bbox": {"x": 50, "y": 42, "w": 48, "h": 18},
                        "message_context_role": "timestamp",
                        "semantic_parent_group_id": "message_item_3",
                    }
                ],
            }
        ]
    )

    assert parent_map["message_item_3"] == {"x": 38, "y": 70, "w": 160, "h": 90}


def test_two_stage_overlay_renders_message_context_children_with_distinct_style(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_context_overlay.png"
    Image.new("RGB", (220, 160), (255, 255, 255)).save(image_path)

    overlay_path = _render_two_stage_overlay(
        image_path=str(image_path),
        structure_regions=[],
        numbered_regions=[
            {
                "numbered_items": [
                    {
                        "number": "3.34",
                        "role": "text",
                        "bbox": {"x": 20, "y": 30, "w": 50, "h": 18},
                        "message_context_role": "timestamp",
                        "semantic_parent_group_id": "message_item_3",
                    },
                    {
                        "number": "3.35",
                        "role": "message_bubble",
                        "bbox": {"x": 80, "y": 60, "w": 90, "h": 42},
                        "semantic_parent_group_id": "message_item_3",
                    },
                ]
            }
        ],
    )

    assert overlay_path
    with Image.open(overlay_path) as overlay:
        assert overlay.getpixel((20, 30)) == (0, 150, 170)


def test_two_stage_writes_message_context_review_overlay_and_zoom(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_context_review.png"
    Image.new("RGB", (260, 220), (255, 255, 255)).save(image_path)

    result = _render_message_context_review_overlay(
        image_path=str(image_path),
        numbered_regions=[
            {
                "numbered_items": [
                    {
                        "number": "3.34",
                        "role": "text",
                        "bbox": {"x": 50, "y": 42, "w": 48, "h": 18},
                        "message_context_role": "timestamp",
                        "semantic_parent_group_id": "message_item_3",
                    },
                    {
                        "group_id": "message_item_3",
                        "role": "message_item",
                        "bbox": {"x": 38, "y": 70, "w": 160, "h": 90},
                    },
                    {
                        "number": "3.35",
                        "role": "message_bubble",
                        "bbox": {"x": 62, "y": 96, "w": 120, "h": 42},
                    },
                ]
            }
        ],
    )

    assert result["contract_version"] == "learn_message_context_review_overlay_v1"
    assert result["display_only"] is True
    assert result["execute_binding_enabled"] is False
    assert result["message_parent_count"] == 1
    assert result["message_context_count"] == 1
    assert Path(result["overlay_path"]).exists()
    assert Path(result["zoom_path"]).exists()


def test_two_stage_context_only_short_message_gets_review_parent(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_context_only_short.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "previous_message_card",
            "label": "Previous forwarded message card",
            "role": "message_card",
            "item_type": "card",
            "bbox": {"x": 300, "y": 360, "w": 270, "h": 116},
            "review_only": True,
        },
        {
            "item_id": "short_timestamp",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 423, "y": 496, "w": 36, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "short_sender",
            "label": "Forever LV75钻石",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 303, "y": 525, "w": 102, "h": 20},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "short_timestamp")
    short_parent = next(
        group for group in primary["subregion_groups"] if {"short_timestamp", "short_sender"}.issubset(group["member_item_ids"])
    )
    assert short_parent["role"] == "message_item"
    assert short_parent["parent_child_policy"] == "message_context_only_short_message_parent"
    assert short_parent["bbox_policy"] == "message_context_only_short_message_needs_review"
    assert short_parent["review_required"] is True
    assert short_parent["execute_binding_enabled"] is False
    assert "previous_message_card" not in short_parent["member_item_ids"]


def test_two_stage_message_parent_does_not_cross_multiple_timestamps(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_multiple_timestamps.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "main_chat_area",
            "label": "Main chat area",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 260, "y": 80, "w": 560, "h": 600},
            "review_only": True,
        },
        {
            "item_id": "old_timestamp",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 423, "y": 496, "w": 36, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "old_sender_name",
            "label": "Forever LV75钻石",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 303, "y": 525, "w": 102, "h": 20},
            "review_only": True,
        },
        {
            "item_id": "new_timestamp",
            "label": "15:10",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 407, "y": 554, "w": 37, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "long_text_bubble",
            "label": "这是一条很长的聊天消息内容用于测试父框归属",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 302, "y": 609, "w": 249, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "long_text_bubble")
    following = next(group for group in primary["subregion_groups"] if "long_text_bubble" in group["member_item_ids"])
    assert {"new_timestamp", "long_text_bubble"}.issubset(set(following["member_item_ids"]))
    assert "old_timestamp" not in following["member_item_ids"]
    assert "old_sender_name" not in following["member_item_ids"]


def test_two_stage_message_context_does_not_absorb_left_conversation_list(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_context_boundary.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_row_title",
            "label": "Project group",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 170, "y": 170, "w": 120, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 100, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "image_message",
            "label": "Shared sticker image",
            "role": "image_message",
            "item_type": "image",
            "bbox": {"x": 360, "y": 190, "w": 140, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "image_message")
    message = next(group for group in primary["subregion_groups"] if group["role"] == "message_item")
    assert "image_message" in message["member_item_ids"]
    assert "left_row_title" not in message["member_item_ids"]


def test_two_stage_splits_message_parent_at_new_timestamp_anchor(tmp_path):
    from PIL import Image

    image_path = tmp_path / "message_parent_split.png"
    Image.new("RGB", (980, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "chat_history_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 320, "y": 90, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "first_sender",
            "label": "Alex LV75",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 320, "y": 288, "w": 90, "h": 20},
            "review_only": True,
        },
        {
            "item_id": "first_message_card",
            "label": "message shared card with image",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 320, "y": 320, "w": 220, "h": 260},
            "review_only": True,
        },
        {
            "item_id": "second_timestamp",
            "label": "17:31",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 420, "y": 452, "w": 44, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "second_message_bubble",
            "label": "Second message bubble should start a separate parent",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 320, "y": 486, "w": 300, "h": 60},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "second_message_bubble")
    message_groups = [group for group in primary["subregion_groups"] if group["role"] == "message_item"]
    assert len(message_groups) >= 2
    first_group = next(group for group in message_groups if "first_message_card" in group["member_item_ids"])
    second_group = next(group for group in message_groups if "second_message_bubble" in group["member_item_ids"])
    first_card = next(item for item in primary["numbered_items"] if item["item_id"] == "first_message_card")
    assert first_group["group_id"] != second_group["group_id"]
    assert "second_message_bubble" not in first_group["member_item_ids"]
    assert "first_message_card" not in second_group["member_item_ids"]
    assert "second_timestamp" in second_group["member_item_ids"]
    assert "second_timestamp" not in first_group["member_item_ids"]
    assert first_card["bbox"]["y"] + first_card["bbox"]["h"] < 452
    assert first_card["bbox_policy"] == "message_card_clipped_before_following_start_anchor"


def test_two_stage_reconstructs_member_list_region_in_sidebar(tmp_path):
    from PIL import Image

    image_path = tmp_path / "member_list.png"
    Image.new("RGB", (1000, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "member_header",
            "label": "Group members 1263",
            "role": "text",
            "item_type": "heading",
            "bbox": {"x": 760, "y": 270, "w": 160, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "member_owner",
            "label": "Cateek / owner",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 320, "w": 190, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "member_admin",
            "label": "Alex / admin",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 360, "w": 190, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "member_user",
            "label": "Blue cat / member",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 400, "w": 190, "h": 34},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"right_sidebar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    member_groups = [group for group in right["subregion_groups"] if group["role"] == "member_list_region"]
    assert member_groups
    assert set(member_groups[0]["member_item_ids"]) == {
        "member_header",
        "member_owner",
        "member_admin",
        "member_user",
    }
    assert member_groups[0]["bbox"]["h"] >= 160


def test_two_stage_adds_same_column_ocr_member_continuation_rows_from_bundle(tmp_path):
    from PIL import Image

    image_path = tmp_path / "member_list_ocr_continuation.png"
    Image.new("RGB", (1000, 760), "white").save(image_path)
    inventory = [
        {
            "item_id": "right_sidebar_panel",
            "label": "Right sidebar panel",
            "role": "boundary_review_region",
            "item_type": "panel",
            "bbox": {"x": 740, "y": 100, "w": 230, "h": 610},
            "review_only": True,
        },
        {
            "item_id": "member_header",
            "label": "Group members 1263",
            "role": "member_list_header",
            "item_type": "heading",
            "bbox": {"x": 760, "y": 270, "w": 160, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "member_owner",
            "label": "Cateek / owner",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 320, "w": 190, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "member_admin",
            "label": "Alex / admin",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 360, "w": 190, "h": 34},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"right_sidebar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={
            "image_path": str(image_path),
            "screen_size": {"width": 1000, "height": 760},
            "screen_reading": {
                "texts": [
                    {
                        "text": "Ad astra",
                        "bbox": {"x": 772, "y": 420, "w": 64, "h": 20},
                        "source": "ocr_fallback",
                    },
                    {
                        "text": "ADaChi",
                        "bbox": {"x": 772, "y": 456, "w": 58, "h": 20},
                        "source": "ocr_fallback",
                    },
                    {
                        "text": "Central chat text",
                        "bbox": {"x": 400, "y": 456, "w": 120, "h": 20},
                        "source": "ocr_fallback",
                    },
                ]
            },
        },
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    labels = {item["label"] for item in right["numbered_items"]}
    assert "Ad astra" in labels
    assert "ADaChi" in labels
    assert "Central chat text" not in labels
    member_group = next(
        group
        for group in right["subregion_groups"]
        if group["role"] == "member_list_region"
        and {"ocr_bundle_text_1", "ocr_bundle_text_2"}.issubset(set(group["member_item_ids"]))
    )
    assert {"ocr_bundle_text_1", "ocr_bundle_text_2"}.issubset(set(member_group["member_item_ids"]))
    assert member_group["bbox"]["y"] + member_group["bbox"]["h"] >= 476


def test_two_stage_uses_child_member_header_inside_oversized_sidebar_boundary(tmp_path):
    from PIL import Image

    image_path = tmp_path / "member_header_child_proxy.png"
    Image.new("RGB", (1000, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "notice_title",
            "label": "Group announcement",
            "role": "nav_item",
            "item_type": "heading",
            "bbox": {"x": 760, "y": 118, "w": 160, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "notice_body",
            "label": "Pinned note for members",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 154, "w": 170, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "mixed_notice_member",
            "label": "Pinned note / Group members 1263",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 748, "y": 142, "w": 212, "h": 190},
            "children": [
                {
                    "child_id": "member_header_text",
                    "label": "Group members 1263",
                    "role": "text",
                    "bbox": {"x": 762, "y": 270, "w": 158, "h": 24},
                }
            ],
            "review_only": True,
        },
        {
            "item_id": "member_owner",
            "label": "Cateek / owner",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 320, "w": 190, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "member_admin",
            "label": "Alex / admin",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 360, "w": 190, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "member_user",
            "label": "Blue cat / member",
            "role": "nav_item",
            "item_type": "readable",
            "bbox": {"x": 760, "y": 400, "w": 190, "h": 34},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"right_sidebar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    right = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_right_sidebar"
    )
    member_group = next(group for group in right["subregion_groups"] if group["role"] == "member_list_region")
    assert member_group["bbox"]["y"] <= 320
    assert {"member_owner", "member_admin", "member_user"}.issubset(set(member_group["member_item_ids"]))
    merged = next(item for item in right["numbered_items"] if item["item_id"].startswith("merged_"))
    assert merged["role"] == "sidebar_review_region"
    assert merged["execute_binding_enabled"] is False


def test_member_list_parent_groups_extracts_header_child_from_boundary_container():
    groups = two_stage._member_list_parent_groups(
        region={"region_id": "structure_region_right_sidebar"},
        numbered_items=[
            {
                "number": "4.2",
                "item_id": "mixed_notice_member",
                "label": "Pinned note / Group members 1263",
                "role": "nav_item",
                "bbox": {"x": 748, "y": 142, "w": 212, "h": 190},
                "children": [
                    {
                        "child_id": "member_header_text",
                        "label": "Group members 1263",
                        "role": "text",
                        "bbox": {"x": 762, "y": 270, "w": 158, "h": 24},
                    }
                ],
            },
            {
                "number": "4.8",
                "item_id": "member_owner",
                "label": "Cateek / owner",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 320, "w": 190, "h": 34},
            },
            {
                "number": "4.9",
                "item_id": "member_admin",
                "label": "Alex / admin",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 360, "w": 190, "h": 34},
            },
            {
                "number": "4.10",
                "item_id": "member_user",
                "label": "Blue cat / member",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 400, "w": 190, "h": 34},
            },
        ],
    )

    assert groups
    member_group = groups[0]
    assert member_group["bbox"]["y"] == 270
    assert "member_header_text" in member_group["member_item_ids"]
    assert member_group["label"] == "Group members 1263"


def test_member_list_parent_groups_keep_plain_continuation_rows_after_header():
    groups = two_stage._member_list_parent_groups(
        region={"region_id": "structure_region_right_sidebar"},
        numbered_items=[
            {
                "number": "4.1",
                "item_id": "notice_title",
                "label": "Group announcement",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 120, "w": 190, "h": 30},
            },
            {
                "number": "4.2",
                "item_id": "member_header",
                "label": "Group members 1263",
                "role": "member_list_header",
                "bbox": {"x": 760, "y": 270, "w": 190, "h": 28},
            },
            {
                "number": "4.3",
                "item_id": "member_admin",
                "label": "Alex / admin",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 320, "w": 190, "h": 34},
            },
            {
                "number": "4.4",
                "item_id": "plain_member_one",
                "label": "AAA谢尔曼批发",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 360, "w": 190, "h": 34},
            },
            {
                "number": "4.5",
                "item_id": "plain_member_two",
                "label": "AAA煤炭批发小王",
                "role": "nav_item",
                "bbox": {"x": 760, "y": 400, "w": 190, "h": 34},
            },
        ],
    )

    assert groups
    member_group = groups[0]
    assert "notice_title" not in member_group["member_item_ids"]
    assert {"member_header", "member_admin", "plain_member_one", "plain_member_two"}.issubset(
        set(member_group["member_item_ids"])
    )
    assert member_group["bbox"]["y"] == 270
    assert member_group["bbox"]["h"] >= 164


def test_two_stage_reconstructs_conversation_rows_in_primary_list_column(tmp_path):
    from PIL import Image

    image_path = tmp_path / "conversation_rows.png"
    Image.new("RGB", (1000, 720), "white").save(image_path)
    inventory = [
        {
            "item_id": "row_one_title",
            "label": "Project group",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 120, "y": 140, "w": 110, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "row_one_preview",
            "label": "Latest message preview",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 120, "y": 166, "w": 180, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "row_one_time",
            "label": "18:55",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 270, "y": 140, "w": 42, "h": 18},
            "review_only": True,
        },
        {
            "item_id": "row_two_title",
            "label": "Design chat",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 120, "y": 220, "w": 110, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "row_two_preview",
            "label": "Another message preview",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 120, "y": 246, "w": 180, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "chat_heading",
            "label": "Chat history",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 430, "y": 180, "w": 120, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1000, "height": 720}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = _stage2_region_with_item(result, "row_one_title")
    conversation_groups = [group for group in primary["subregion_groups"] if group["role"] == "conversation_row"]
    assert len(conversation_groups) >= 2
    assert {"row_one_title", "row_one_preview", "row_one_time"}.issubset(
        set(conversation_groups[0]["member_item_ids"])
    )


def test_two_stage_stage2_refines_sparse_top_bar_without_rewriting_left_nav(tmp_path):
    image_path = tmp_path / "toolbar.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (520, 240), "white")
    draw = ImageDraw.Draw(image)
    for x in (242, 292, 342, 442):
        draw.rectangle((x, 24, x + 14, 38), fill="black")
    for y in (82, 132, 182):
        draw.rectangle((16, y, 38, y + 22), outline="black", width=3)
    image.save(image_path)

    inventory = [
        {
            "item_id": "top_1",
            "label": "Top control 1",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 120, "y": 10, "w": 20, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "top_2",
            "label": "Top control 2",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 140, "y": 10, "w": 20, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "top_3",
            "label": "Top control 3",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 160, "y": 10, "w": 20, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "top_4",
            "label": "Top control 4",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 180, "y": 10, "w": 20, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "nav_1",
            "label": "Nav 1",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 10, "y": 72, "w": 43, "h": 43},
            "review_only": True,
        },
        {
            "item_id": "nav_2",
            "label": "Nav 2",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 10, "y": 122, "w": 43, "h": 43},
            "review_only": True,
        },
        {
            "item_id": "nav_3",
            "label": "Nav 3",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 10, "y": 172, "w": 43, "h": 43},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "page_header": {"item_ids": ["top_1", "top_2", "top_3", "top_4"]},
            "left_nav": {"item_ids": ["nav_1", "nav_2", "nav_3"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 520, "height": 240}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    header = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_page_header"
    )
    left_nav = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_left_nav"
    )

    assert header["grouping_strategy"] == "direct_region_numbering_without_subgrouping"
    assert header["visual_small_control_refinement"]["applied"] is True
    assert header["visual_small_control_refinement"]["refined_count"] == 4
    assert header["numbered_items"][0]["bbox"]["x"] >= 230
    assert header["numbered_items"][0]["bbox_refinement"]["source"] == "visual_small_control_segmenter"

    assert left_nav["grouping_strategy"] == "direct_region_numbering_without_subgrouping"
    assert left_nav["visual_small_control_refinement"]["applied"] is False, left_nav[
        "visual_small_control_refinement"
    ]
    assert left_nav["visual_small_control_refinement"]["reason"] in {
        "model_boxes_already_overlap_visual_candidates",
        "insufficient_visual_candidates",
    }
    assert [item["bbox"] for item in left_nav["numbered_items"]] == [
        {"x": 10, "y": 72, "w": 43, "h": 43},
        {"x": 10, "y": 122, "w": 43, "h": 43},
        {"x": 10, "y": 172, "w": 43, "h": 43},
    ]


def test_two_stage_synthesizes_top_controls_when_text_inventory_is_sparse(tmp_path):
    image_path = tmp_path / "sparse_top_controls.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (620, 260), "white")
    draw = ImageDraw.Draw(image)
    for x in (124, 164, 204, 244, 384, 504):
        draw.rectangle((x, 22, x + 16, 38), fill="black")
    for y in (94, 144):
        draw.rectangle((16, y, 38, y + 22), outline="black", width=3)
    image.save(image_path)

    inventory = [
        {
            "item_id": "title_text",
            "label": "x",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 600, "y": 8, "w": 12, "h": 14},
            "review_only": True,
        },
        {
            "item_id": "nav_1",
            "label": "Nav 1",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 10, "y": 92, "w": 43, "h": 43},
            "review_only": True,
        },
        {
            "item_id": "nav_2",
            "label": "Nav 2",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 10, "y": 142, "w": 43, "h": 43},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["title_text"]},
            "left_nav": {"item_ids": ["nav_1", "nav_2"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 620, "height": 260}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_browser_chrome"
    )
    assert top["input_region_bbox"]["x"] == 0
    assert top["input_region_bbox"]["w"] == 620
    assert top["visual_small_control_refinement"]["reason"] == "visual_candidates_replace_sparse_text_inventory"
    assert top["numbered_item_count"] >= 6
    assert {item["role"] for item in top["numbered_items"]} == {"control"}
    assert all(item["bbox"]["w"] >= 36 for item in top["numbered_items"])
    assert all(item["bbox"]["h"] >= 30 for item in top["numbered_items"])


def test_two_stage_creates_topbar_control_strip_parent_group(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "topbar_parent.png"
    image = Image.new("RGB", (720, 280), "white")
    draw = ImageDraw.Draw(image)
    for x in (120, 164, 208, 328, 520, 604, 652):
        draw.rectangle((x, 22, x + 16, 38), fill="black")
    image.save(image_path)

    inventory = [
        {
            "item_id": f"top_control_{index}",
            "label": f"Top control {index}",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": x, "y": 18, "w": 28, "h": 28},
            "review_only": True,
        }
        for index, x in enumerate((118, 162, 206, 326, 518, 602, 650), start=1)
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"page_header": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 280}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_page_header"
    )
    strip_groups = [group for group in top["subregion_groups"] if group["role"] == "topbar_control_strip"]
    assert strip_groups
    strip = strip_groups[0]
    assert strip["display_only"] is True
    assert strip["execute_binding_enabled"] is False
    assert strip["artifact_is_authorization"] is False
    assert strip["bbox"]["x"] <= 118
    assert strip["bbox"]["w"] >= 560
    assert strip["bbox"]["h"] >= 48
    assert set(strip["member_item_ids"]) == {item["item_id"] for item in top["numbered_items"]}


def test_two_stage_splits_topbar_controls_into_display_only_clusters(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "topbar_clusters.png"
    image = Image.new("RGB", (720, 280), "white")
    draw = ImageDraw.Draw(image)
    for x in (120, 164, 208, 328, 520, 604, 652):
        draw.rectangle((x, 22, x + 16, 38), fill="black")
    image.save(image_path)

    inventory = [
        {
            "item_id": f"top_control_{index}",
            "label": f"Top control {index}",
            "role": "button",
            "item_type": "button",
            "bbox": {"x": x, "y": 18, "w": 28, "h": 28},
            "review_only": True,
        }
        for index, x in enumerate((118, 162, 206, 326, 518, 602, 650), start=1)
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"page_header": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 280}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_page_header"
    )
    strip = next(group for group in top["subregion_groups"] if group["role"] == "topbar_control_strip")
    clusters = [group for group in top["subregion_groups"] if group["role"] == "topbar_control_cluster"]
    assert len(clusters) >= 3
    assert all(group["display_only"] is True for group in clusters)
    assert all(group["execute_binding_enabled"] is False for group in clusters)
    assert all(group["artifact_is_authorization"] is False for group in clusters)
    assert all(group["bbox"]["w"] < strip["bbox"]["w"] * 0.65 for group in clusters)

    clustered_item_ids = [item_id for group in clusters for item_id in group["member_item_ids"]]
    assert set(clustered_item_ids) == {item["item_id"] for item in top["numbered_items"]}
    assert len(clustered_item_ids) == len(set(clustered_item_ids))


def test_two_stage_adds_sparse_center_topbar_semantic_parent(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "topbar_sparse_status_parent.png"
    image = Image.new("RGB", (1154, 260), "white")
    draw = ImageDraw.Draw(image)
    for x in (112, 151, 193, 232, 273, 371, 575, 830, 877, 923, 1012, 1058, 1104):
        draw.rectangle((x + 14, 20, x + 26, 32), fill="black")
    draw.rounded_rectangle((330, 12, 710, 62), radius=6, outline="#dddddd", width=2)
    image.save(image_path)

    inventory = [
        {
            "item_id": f"top_control_{index}",
            "label": f"Top control {index}",
            "role": "icon_button",
            "item_type": "button",
            "bbox": {"x": x + 16, "y": 20, "w": 12, "h": 12},
            "review_only": True,
        }
        for index, x in enumerate((112, 151, 193, 232, 273, 371, 575, 830, 877, 923, 1012, 1058, 1104), start=1)
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"top_bar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1154, "height": 260}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_top_bar"
    )
    semantic_groups = [group for group in top["subregion_groups"] if group["role"] == "topbar_semantic_group"]
    assert semantic_groups
    group = semantic_groups[0]
    assert group["display_only"] is True
    assert group["execute_binding_enabled"] is False
    assert group["artifact_is_authorization"] is False
    assert group["parent_child_policy"] == "sparse_center_topbar_controls_share_display_only_semantic_parent"
    assert group["bbox_policy"] == "topbar_sparse_aligned_controls_expand_to_status_parent"
    assert group["bbox"]["x"] <= 342
    assert group["bbox"]["x"] + group["bbox"]["w"] >= 700
    assert set(group["member_item_ids"]) == {"top_control_6", "top_control_7"}
    assert not any({"top_control_8", "top_control_9"} & set(group["member_item_ids"]) for group in semantic_groups)


def test_two_stage_does_not_add_sparse_semantic_parent_for_text_nav_bar(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "topbar_text_nav.png"
    image = Image.new("RGB", (1200, 260), "white")
    draw = ImageDraw.Draw(image)
    for x, text in (
        (120, "Python"),
        (360, "About"),
        (520, "Downloads"),
        (710, "Documentation"),
        (920, "Community"),
        (1080, "Success Stories"),
    ):
        draw.text((x, 30), text, fill="black")
    image.save(image_path)

    inventory = [
        {
            "item_id": f"nav_{index}",
            "label": label,
            "role": "text_action",
            "item_type": "text_action",
            "bbox": {"x": x, "y": 28, "w": w, "h": 24},
            "review_only": True,
        }
        for index, (label, x, w) in enumerate(
            (
                ("Python", 120, 72),
                ("About", 360, 62),
                ("Downloads", 520, 112),
                ("Documentation", 710, 156),
                ("Community", 920, 124),
                ("Success Stories", 1080, 148),
            ),
            start=1,
        )
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"top_bar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 260}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_top_bar"
    )
    semantic_groups = [group for group in top["subregion_groups"] if group["role"] == "topbar_semantic_group"]
    assert semantic_groups == []


def test_two_stage_splits_browser_chrome_from_page_top_navigation(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "browser_chrome_and_page_nav.png"
    image = Image.new("RGB", (1200, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1199, 70), fill="#f7f7f7")
    draw.rectangle((0, 74, 1199, 118), fill="#1f4b6d")
    draw.text((110, 8), "Welcome to Python.org", fill="black")
    draw.text((150, 42), "https://www.python.org", fill="black")
    for x, text in ((360, "Python"), (520, "PSF"), (700, "Docs"), (880, "PyPI")):
        draw.text((x, 88), text, fill="white")
    image.save(image_path)

    inventory = [
        {
            "item_id": "browser_title",
            "label": "Welcome to Python.org",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 110, "y": 4, "w": 170, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "browser_url",
            "label": "https://www.python.org",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 150, "y": 38, "w": 230, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "browser_right_tool",
            "label": "Chat",
            "role": "text_action",
            "item_type": "text_action",
            "bbox": {"x": 1080, "y": 38, "w": 56, "h": 24},
            "review_only": True,
        },
        *[
            {
                "item_id": f"site_nav_{index}",
                "label": label,
                "role": "nav_text_action",
                "item_type": "text_action",
                "bbox": {"x": x, "y": 84, "w": w, "h": 20},
                "review_only": True,
            }
            for index, (label, x, w) in enumerate(
                (("Python", 360, 72), ("PSF", 520, 48), ("Docs", 700, 58), ("PyPI", 880, 56)),
                start=1,
            )
        ],
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"top_bar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 320}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = result["stage2_numbering"]["regions"]
    browser = next(region for region in regions if region["region_id"] == "structure_region_browser_chrome")
    top = next(region for region in regions if region["region_id"] == "structure_region_top_bar")
    assert browser["label"] == "Browser chrome"
    assert browser["bbox"]["y"] == 0
    assert browser["bbox"]["y"] + browser["bbox"]["h"] <= 78
    assert {item["item_id"] for item in browser["numbered_items"]} == {
        "browser_title",
        "browser_url",
        "browser_right_tool",
    }
    assert top["bbox"]["y"] >= 70
    assert {item["item_id"] for item in top["numbered_items"]} == {
        "site_nav_1",
        "site_nav_2",
        "site_nav_3",
        "site_nav_4",
    }


def test_two_stage_browser_chrome_ignores_large_python_org_surface_containers(tmp_path):
    from PIL import Image, ImageDraw
    from app.learn.recognition.layout_graph import build_inventory_layout_graph

    image_path = tmp_path / "python_org_with_uia_containers.png"
    image = Image.new("RGB", (1200, 640), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1199, 70), fill="#f7f7f7")
    draw.rectangle((0, 74, 1199, 118), fill="#1f4b6d")
    draw.rectangle((0, 119, 1199, 360), fill="#234f73")
    draw.text((110, 8), "Welcome to Python.org", fill="black")
    draw.text((150, 42), "https://www.python.org", fill="black")
    for x, text in ((360, "Python"), (520, "PSF"), (700, "Docs"), (880, "PyPI")):
        draw.text((x, 88), text, fill="white")
    image.save(image_path)

    inventory = [
        {
            "item_id": "uia_window",
            "label": "Welcome to Python.org - Microsoft Edge",
            "role": "window",
            "item_type": "actionable",
            "bbox": {"x": 0, "y": 0, "w": 1200, "h": 640},
            "review_only": True,
        },
        {
            "item_id": "uia_pane",
            "label": "Welcome to Python.org - Microsoft Edge",
            "role": "pane",
            "item_type": "actionable",
            "bbox": {"x": 4, "y": 0, "w": 1192, "h": 636},
            "review_only": True,
        },
        {
            "item_id": "uia_document",
            "label": "Welcome to Python.org",
            "role": "document",
            "item_type": "layout",
            "bbox": {"x": 4, "y": 80, "w": 1192, "h": 550},
            "review_only": True,
        },
        {
            "item_id": "browser_title",
            "label": "Welcome to Python.org",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 110, "y": 4, "w": 170, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "browser_url",
            "label": "https://www.python.org",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 150, "y": 38, "w": 230, "h": 24},
            "review_only": True,
        },
        *[
            {
                "item_id": f"site_nav_{index}",
                "label": label,
                "role": "link",
                "item_type": "actionable",
                "bbox": {"x": x, "y": 84, "w": w, "h": 20},
                "review_only": True,
            }
            for index, (label, x, w) in enumerate(
                (("Python", 360, 72), ("PSF", 520, 48), ("Docs", 700, 58), ("PyPI", 880, 56)),
                start=1,
            )
        ],
        {
            "item_id": "hero_text",
            "label": "Python is a programming language that lets you work quickly",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 300, "w": 520, "h": 36},
            "review_only": True,
        },
    ]
    screen_size = {"width": 1200, "height": 640}
    layout_graph = build_inventory_layout_graph(inventory, screen_size=screen_size)

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": screen_size},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert result["stage1_gate"]["status"] == "passed"
    browser = next(
        region
        for region in result["stage1_region_localization"]["regions"]
        if region["region_id"] == "structure_region_browser_chrome"
    )
    following = next(
        region
        for region in result["stage1_region_localization"]["regions"]
        if region["region_id"] == "structure_region_main_content"
    )
    assert browser["bbox"]["y"] == 0
    assert browser["bbox"]["h"] < 96
    assert browser["bbox"]["y"] + browser["bbox"]["h"] <= following["bbox"]["y"]
    assert set(browser["item_ids"]) >= {"browser_title", "browser_url"}


def test_two_stage_overlay_uses_localized_structure_regions(tmp_path, monkeypatch):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "browser_chrome_overlay_regions.png"
    image = Image.new("RGB", (1200, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1199, 70), fill="#f7f7f7")
    draw.rectangle((0, 74, 1199, 118), fill="#1f4b6d")
    draw.text((120, 38), "https://www.python.org", fill="black")
    draw.text((360, 88), "Python", fill="white")
    image.save(image_path)

    inventory = [
        {
            "item_id": "browser_url",
            "label": "https://www.python.org",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 38, "w": 230, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "site_nav_1",
            "label": "Python",
            "role": "nav_text_action",
            "item_type": "text_action",
            "bbox": {"x": 360, "y": 84, "w": 72, "h": 20},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"top_bar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }
    captured: dict[str, list[dict]] = {}

    def fake_overlay(*, image_path, structure_regions, numbered_regions):
        captured["structure_regions"] = structure_regions
        return ""

    monkeypatch.setattr(two_stage, "_render_two_stage_overlay", fake_overlay)

    build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 320}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    rendered_top = next(
        region for region in captured["structure_regions"] if region["region_id"] == "structure_region_top_bar"
    )
    rendered_browser = next(
        region
        for region in captured["structure_regions"]
        if region["region_id"] == "structure_region_browser_chrome"
    )
    assert rendered_browser["bbox"]["y"] == 0
    assert rendered_browser["bbox"]["y"] + rendered_browser["bbox"]["h"] <= rendered_top["bbox"]["y"]
    assert rendered_top["bbox"]["y"] >= 70


def test_two_stage_exposes_stage1_and_fusion_overlay_paths_from_same_run(tmp_path, monkeypatch):
    from PIL import Image

    image_path = tmp_path / "triad_source.png"
    Image.new("RGB", (800, 500), "white").save(image_path)
    inventory = [
        {
            "item_id": "main",
            "label": "Main content",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 0, "y": 0, "w": 800, "h": 500},
            "review_only": True,
        }
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": ["main"]}},
        "nodes": {"main": inventory[0]},
    }
    monkeypatch.setattr(two_stage, "_render_stage1_region_localization_overlay", lambda **kwargs: "stage1.png")
    monkeypatch.setattr(two_stage, "_render_two_stage_overlay", lambda **kwargs: "fusion.png")

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 800, "height": 500}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert result["source_image_path"] == str(image_path)
    assert result["stage1_region_localization"]["overlay_path"] == "stage1.png"
    assert result["fusion"]["stage1_structure_overlay_path"] == "stage1.png"
    assert result["fusion"]["compiled_overlay_path"] == "fusion.png"


def test_stage1_clamps_topbar_before_overlapping_main_content(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "topbar_main_overlap.png"
    image = Image.new("RGB", (900, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 899, 68), fill="#f7f7f7")
    draw.text((120, 22), "top controls", fill="black")
    draw.text((100, 100), "Home", fill="black")
    draw.rectangle((100, 150, 300, 320), fill="#db3030")
    image.save(image_path)

    inventory = [
        {
            "item_id": "top_bar_hint",
            "label": "Top bar coarse hint",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 900, "h": 150},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "top_bar"},
        },
        {
            "item_id": "top_controls",
            "label": "top controls",
            "role": "text_action",
            "item_type": "text_action",
            "bbox": {"x": 120, "y": 22, "w": 120, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "misassigned_main_title",
            "label": "Home",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 100, "y": 100, "w": 70, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "primary_area",
            "label": "Primary area",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 90, "y": 92, "w": 720, "h": 380},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "top_bar": {"item_ids": ["top_bar_hint", "top_controls", "misassigned_main_title"]},
            "primary_area": {"item_ids": ["primary_area"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    top = next(
        region
        for region in result["stage1_region_localization"]["regions"]
        if region["region_id"] == "structure_region_top_bar"
    )
    primary = next(
        region
        for region in result["stage1_region_localization"]["regions"]
        if region["region_id"] == "structure_region_primary_area"
    )
    assert top["bbox"]["y"] + top["bbox"]["h"] <= primary["bbox"]["y"]
    assert top["coordinate_validation"]["sibling_clamp"]["reason"] == "top_bar_must_not_overlap_main_content"


def test_two_stage_required_stage1_gate_blocks_item_numbering_when_stage1_fails(tmp_path):
    from PIL import Image

    image_path = tmp_path / "stage1_gate_main_too_small.png"
    Image.new("RGB", (900, 520), "white").save(image_path)
    inventory = [
        {
            "item_id": "top_bar_hint",
            "label": "Top bar",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 900, "h": 72},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "top_bar"},
        },
        {
            "item_id": "primary_area",
            "label": "Primary area",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 80, "y": 100, "w": 120, "h": 120},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "top_bar": {"item_ids": ["top_bar_hint"]},
            "primary_area": {"item_ids": ["primary_area"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
    )

    assert result["stage1_gate"]["required"] is True
    assert result["stage1_gate"]["allow_stage2_numbering"] is False
    assert result["stage1_gate"]["status"] == "blocked_before_stage2_numbering"
    assert "main_region_too_small" in result["stage1_gate"]["failure_categories"]
    assert result["stage2_numbering_skipped"] is True
    assert result["stage2_numbering"]["numbered_item_count"] == 0
    assert result["fusion"]["region_content_boundary_summary"]["boundary_contract_status"] == "not_evaluated_stage2_skipped"
    assert result["fusion"]["region_content_boundary_summary"]["pathgraph_promotion_allowed"] is False
    assert "stage2_numbering_skipped" in result["fusion"]["region_content_boundary_summary"]["promotion_blockers"]


def test_two_stage_does_not_promote_browser_chrome_left_icon_to_left_nav(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "browser_left_icon_not_left_nav.png"
    image = Image.new("RGB", (1200, 320), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1199, 70), fill="#f7f7f7")
    draw.rectangle((0, 74, 1199, 118), fill="#1f4b6d")
    draw.text((56, 42), "C", fill="black")
    draw.text((150, 42), "https://www.python.org", fill="black")
    draw.text((360, 88), "Python", fill="white")
    image.save(image_path)

    inventory = [
        {
            "item_id": "browser_left_icon",
            "label": "C",
            "role": "nav_item",
            "item_type": "text",
            "bbox": {"x": 56, "y": 42, "w": 18, "h": 16},
            "review_only": True,
        },
        {
            "item_id": "browser_url",
            "label": "https://www.python.org",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 150, "y": 38, "w": 230, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "site_nav_1",
            "label": "Python",
            "role": "nav_text_action",
            "item_type": "text_action",
            "bbox": {"x": 360, "y": 84, "w": 72, "h": 20},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["browser_left_icon"]},
            "top_bar": {"item_ids": ["browser_url", "site_nav_1"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 320}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    region_ids = {region["region_id"] for region in result["stage2_numbering"]["regions"]}
    browser = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if region["region_id"] == "structure_region_browser_chrome"
    )
    assert "structure_region_left_nav" not in region_ids
    assert {item["item_id"] for item in browser["numbered_items"]} == {
        "browser_left_icon",
        "browser_url",
    }


def test_two_stage_overlay_suppresses_browser_chrome_child_item_labels(tmp_path, monkeypatch):
    from PIL import Image

    image_path = tmp_path / "browser_chrome_overlay_suppression.png"
    Image.new("RGB", (600, 180), "white").save(image_path)
    drawn_labels: list[str] = []

    def fake_draw_box(draw, bbox, label, *, color, font, width=1):
        drawn_labels.append(str(label))

    monkeypatch.setattr(two_stage, "_draw_box", fake_draw_box)

    _render_two_stage_overlay(
        image_path=str(image_path),
        structure_regions=[
            {
                "region_no": 1,
                "region_id": "structure_region_browser_chrome",
                "label": "Browser chrome",
                "bbox": {"x": 0, "y": 0, "w": 600, "h": 64},
            },
            {
                "region_no": 2,
                "region_id": "structure_region_top_bar",
                "label": "Top/header area",
                "bbox": {"x": 0, "y": 72, "w": 600, "h": 60},
            },
        ],
        numbered_regions=[
            {
                "region_id": "structure_region_browser_chrome",
                "numbered_items": [
                    {
                        "number": "1.0",
                        "label": "https://example.test",
                        "role": "address_bar",
                        "bbox": {"x": 120, "y": 20, "w": 260, "h": 24},
                    },
                    {
                        "number": "1.1",
                        "role": "control",
                        "bbox": {"x": 20, "y": 20, "w": 80, "h": 24},
                    }
                ],
            },
            {
                "region_id": "structure_region_top_bar",
                "numbered_items": [
                    {
                        "number": "2.1",
                        "role": "nav_item",
                        "bbox": {"x": 120, "y": 84, "w": 72, "h": 20},
                    }
                ],
            },
        ],
    )

    assert "S1: Browser chrome" in drawn_labels
    assert "1.1 control" not in drawn_labels
    assert "2.1 nav_item" in drawn_labels


def test_two_stage_overlay_and_fusion_keep_native_toolbar_children(tmp_path, monkeypatch):
    from PIL import Image

    image_path = tmp_path / "native_toolbar_overlay.png"
    Image.new("RGB", (600, 180), "white").save(image_path)
    drawn_labels: list[str] = []

    def fake_draw_box(draw, bbox, label, *, color, font, width=1):
        drawn_labels.append(str(label))

    monkeypatch.setattr(two_stage, "_draw_box", fake_draw_box)
    structure_regions = [
        {
            "region_no": 1,
            "region_id": "structure_region_browser_chrome",
            "label": "Legacy top toolbar",
            "bbox": {"x": 0, "y": 0, "w": 600, "h": 64},
        }
    ]
    numbered_regions = [
        {
            "region_id": "structure_region_browser_chrome",
            "bbox": {"x": 0, "y": 0, "w": 600, "h": 64},
            "numbered_items": [
                {
                    "item_id": "play_control",
                    "number": "1.1",
                    "label": "Play",
                    "role": "button",
                    "bbox": {"x": 180, "y": 18, "w": 36, "h": 28},
                    "parent_region_id": "structure_region_browser_chrome",
                    "parent_region_bbox": {"x": 0, "y": 0, "w": 600, "h": 64},
                }
            ],
            "subregion_groups": [],
        }
    ]

    _render_two_stage_overlay(
        image_path=str(image_path),
        structure_regions=structure_regions,
        numbered_regions=numbered_regions,
    )
    fusion = two_stage._fusion_boxes(structure_regions, numbered_regions)

    assert "1.1 button" in drawn_labels
    assert any(
        box.get("box_type") == "numbered_item" and box.get("number") == "1.1"
        for box in fusion["fused_review_boxes"]
    )


def test_two_stage_synthesizes_web_list_row_parents_for_date_title_rows(tmp_path):
    image_path = tmp_path / "date_title_rows.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (900, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.text((90, 96), "Latest News", fill="black")
    for y, date, title in (
        (140, "2026-07-02", "Thinking about running for the PSF Board? Let's talk!"),
        (178, "2026-06-29", "Python Packaging Council Inaugural Election Dates"),
    ):
        draw.text((90, y), date, fill="black")
        draw.text((200, y), title, fill="black")
    image.save(image_path)

    inventory = [
        {
            "item_id": "section_latest_news",
            "label": "Latest News",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 90, "y": 96, "w": 140, "h": 24},
            "review_only": True,
        },
        *[
            {
                "item_id": f"date_{index}",
                "label": date,
                "role": "text",
                "item_type": "text",
                "bbox": {"x": 90, "y": y, "w": 86, "h": 20},
                "review_only": True,
            }
            for index, (y, date) in enumerate(
                ((140, "2026-07-02"), (178, "2026-06-29")),
                start=1,
            )
        ],
        *[
            {
                "item_id": f"title_{index}",
                "label": title,
                "role": "text",
                "item_type": "text",
                "bbox": {"x": 200, "y": y, "w": w, "h": 20},
                "review_only": True,
            }
            for index, (y, title, w) in enumerate(
                (
                    (140, "Thinking about running for the PSF Board? Let's talk!", 360),
                    (178, "Python Packaging Council Inaugural Election Dates", 330),
                ),
                start=1,
            )
        ],
        {
            "item_id": "below_list_content",
            "label": "Below list content",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 90, "y": 360, "w": 160, "h": 20},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if region["grouping_strategy"] == "primary_region_homogeneous_grouping_with_visual_card_segmenter"
    )
    list_rows = [group for group in primary["subregion_groups"] if group["role"] == "list_row"]
    list_groups = [group for group in primary["subregion_groups"] if group["role"] == "list_group"]
    section_parents = [group for group in primary["subregion_groups"] if group["role"] == "section_parent"]

    assert len(list_rows) == 2
    assert len(list_groups) == 1
    assert list_groups[0]["child_group_roles"] == ["list_row", "list_row"]
    assert section_parents
    assert "list_group" in section_parents[0]["child_group_roles"]


def test_list_groups_take_precedence_over_inferred_text_tile_cards() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "label": "Main content",
        "bbox": {"x": 0, "y": 0, "w": 900, "h": 520},
    }
    items: list[dict] = []
    for index, y in enumerate((140, 178, 216), start=1):
        items.extend(
            [
                {
                    "number": f"1.{index * 2 - 1}",
                    "item_id": f"metadata_{index}",
                    "label": f"2026-07-{index:02d}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": 90, "y": y, "w": 86, "h": 20},
                },
                {
                    "number": f"1.{index * 2}",
                    "item_id": f"title_{index}",
                    "label": f"Entry title {index}",
                    "role": "text",
                    "item_type": "text",
                    "bbox": {"x": 200, "y": y, "w": 150, "h": 20},
                },
            ]
        )

    groups = two_stage._semantic_parent_groups(region=region, numbered_items=items)

    list_groups = [group for group in groups if group.get("role") == "list_group"]
    assert len(list_groups) == 1
    list_member_ids = set(list_groups[0]["member_item_ids"])
    conflicting_text_tiles = [
        group
        for group in groups
        if group.get("source") == "stage2_primary_text_tile_card_parent_grouping"
        and list_member_ids.intersection(group.get("member_item_ids", []))
    ]
    assert conflicting_text_tiles == []


def test_two_stage_synthesizes_hero_code_and_text_panels(tmp_path):
    image_path = tmp_path / "hero_code_text_panels.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1100, 620), "#1f4b6d")
    draw = ImageDraw.Draw(image)
    for y, text in (
        (180, ">>> name = input('What is your name?')"),
        (214, ">>> print('Hi ' + name + '.')"),
        (248, "Hi Python."),
    ):
        draw.text((180, y), text, fill="white")
    draw.text((610, 178), "Quick & Easy to Learn", fill="yellow")
    draw.text((610, 218), "Experienced programmers in any other language can pick up Python quickly.", fill="white")
    draw.text((610, 258), "Learn More", fill="yellow")
    draw.text((180, 460), "Below hero content", fill="white")
    image.save(image_path)

    inventory = [
        *[
            {
                "item_id": f"code_{index}",
                "label": label,
                "role": "text",
                "item_type": "text",
                "bbox": {"x": 180, "y": y, "w": w, "h": 24},
                "review_only": True,
            }
            for index, (y, label, w) in enumerate(
                (
                    (180, ">>> name = input('What is your name?')", 330),
                    (214, ">>> print('Hi ' + name + '.')", 260),
                    (248, "Hi Python.", 86),
                ),
                start=1,
            )
        ],
        {
            "item_id": "hero_heading",
            "label": "Quick & Easy to Learn",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 610, "y": 178, "w": 210, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "hero_paragraph",
            "label": "Experienced programmers in any other language can pick up Python quickly.",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 610, "y": 218, "w": 430, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "hero_cta",
            "label": "Learn More",
            "role": "text_action",
            "item_type": "text_action",
            "bbox": {"x": 610, "y": 258, "w": 110, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "below_hero",
            "label": "Below hero content",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 180, "y": 460, "w": 160, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1100, "height": 620}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if region["grouping_strategy"] == "primary_region_homogeneous_grouping_with_visual_card_segmenter"
    )
    roles = {group["role"]: group for group in primary["subregion_groups"]}
    assert roles["hero_code_panel"]["member_item_ids"] == ["code_1", "code_2", "code_3"]
    assert roles["hero_text_panel"]["member_item_ids"] == ["hero_heading", "hero_paragraph", "hero_cta"]
    assert roles["hero_panel"]["child_group_roles"] == ["hero_code_panel", "hero_text_panel"]


def test_two_stage_expands_sparse_sidebar_visual_fragments_to_hit_area_items(tmp_path):
    image_path = tmp_path / "sparse_sidebar_controls.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (360, 420), "white")
    draw = ImageDraw.Draw(image)
    for y in (42, 92, 142, 192, 242, 292):
        draw.rectangle((18, y, 32, y + 14), fill="black")
    image.save(image_path)

    inventory = [
        {
            "item_id": "left_nav_region_hint",
            "label": "Left nav",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 72, "h": 360},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "left_nav"},
        },
        {
            "item_id": "left_nav_sparse_text",
            "label": "Nav",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 14, "y": 8, "w": 22, "h": 16},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"left_nav": {"item_ids": ["left_nav_region_hint", "left_nav_sparse_text"]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 360, "height": 420}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    left_nav = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_left_nav"
    )

    assert left_nav["visual_small_control_refinement"]["applied"] is True
    assert left_nav["visual_small_control_refinement"]["sidebar_item_grouping"]["applied"] is True
    assert left_nav["numbered_item_count"] >= 6
    assert {item["role"] for item in left_nav["numbered_items"]} == {"nav_item"}
    assert all(item["bbox"]["w"] >= left_nav["bbox"]["w"] * 0.55 for item in left_nav["numbered_items"])
    assert all(
        item.get("bbox_refinement", {}).get("source") == "sidebar_item_hit_area_normalizer"
        for item in left_nav["numbered_items"]
    )


def test_two_stage_sidebar_blank_fragments_do_not_promote_to_nav_items(tmp_path):
    image_path = tmp_path / "blank_sidebar.png"
    from PIL import Image

    Image.new("RGB", (280, 320), (246, 246, 246)).save(image_path)
    inventory = [
        {
            "item_id": "left_nav_region_hint",
            "label": "Left nav",
            "role": "layout",
            "item_type": "layout",
            "bbox": {"x": 0, "y": 0, "w": 80, "h": 300},
            "review_only": True,
            "metadata": {"source": "screen_map.sections", "surface_zone": "left_nav"},
        },
        {
            "item_id": "blank_fragment",
            "label": "Maybe button",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 16, "y": 150, "w": 22, "h": 23},
            "review_only": True,
        },
        {
            "item_id": "blank_fragment_2",
            "label": "Maybe button 2",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 16, "y": 210, "w": 22, "h": 23},
            "review_only": True,
        },
        {
            "item_id": "blank_fragment_3",
            "label": "Maybe button 3",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 16, "y": 260, "w": 22, "h": 23},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"left_nav": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 280, "height": 320}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    left_nav = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_left_nav"
    )

    roles = {item["role"] for item in left_nav["numbered_items"]}
    assert roles == {"sidebar_review_region"}
    assert left_nav["numbered_item_count"] == 1
    assert left_nav["visual_small_control_refinement"]["sidebar_item_grouping"]["merged_review_region_count"] == 2
    assert left_nav["numbered_items"][0]["bbox"]["w"] < left_nav["bbox"]["w"] * 0.55
    assert left_nav["numbered_items"][0]["overlay_style"] == {
        "tone": "background_review_region",
        "label_policy": "review_only_badge",
        "stroke": "muted_dashed",
        "display_layer": "review_background",
        "number_policy": "hide_stage_number",
        "action_candidate_visual_weight": "low",
    }
    assert left_nav["numbered_items"][0].get("bbox_refinement", {}).get("reason") == (
        "merge_consecutive_sidebar_review_regions_without_visual_evidence"
    )
    fused = [
        item
        for item in result["fusion"]["fused_review_boxes"]
        if item.get("role") == "sidebar_review_region"
    ]
    assert fused
    assert fused[0]["overlay_style"]["tone"] == "background_review_region"
    assert fused[0]["overlay_style"]["display_layer"] == "review_background"
    assert fused[0]["overlay_style"]["number_policy"] == "hide_stage_number"


def test_two_stage_synthesizes_primary_media_card_parents_from_visual_rows(tmp_path):
    image_path = tmp_path / "media_cards.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (520, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 220, 240), fill=(220, 30, 30))
    draw.rectangle((250, 100, 370, 240), fill=(20, 140, 220))
    image.save(image_path)

    inventory = [
        {
            "item_id": "main_area",
            "label": "Main area",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 90, "y": 90, "w": 300, "h": 210},
            "review_only": True,
        },
        {
            "item_id": "card_1_text",
            "label": "Card One",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 108, "y": 248, "w": 90, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "card_2_text",
            "label": "Card Two",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 258, "y": 248, "w": 90, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 520, "height": 360}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    main = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    assert main["visual_small_control_refinement"]["media_card_synthesis"]["applied"] is True
    cards = [item for item in main["numbered_items"] if item["role"] == "media_card"]
    assert len(cards) == 2
    assert all(card["children"] for card in cards)


def test_two_stage_groups_each_primary_tile_card_with_internal_text(tmp_path):
    image_path = tmp_path / "settings_tiles.png"
    from PIL import Image

    Image.new("RGB", (760, 420), "white").save(image_path)
    inventory = [
        {
            "item_id": "tile_a",
            "label": "System tile",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 120, "w": 220, "h": 88},
            "review_only": True,
        },
        {
            "item_id": "tile_a_title",
            "label": "System",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 154, "y": 138, "w": 70, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "tile_a_subtitle",
            "label": "Display, sound, notifications",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 154, "y": 166, "w": 170, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "tile_b",
            "label": "Network tile",
            "role": "recommendation_item",
            "item_type": "card",
            "bbox": {"x": 380, "y": 120, "w": 220, "h": 88},
            "review_only": True,
        },
        {
            "item_id": "tile_b_title",
            "label": "Network",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 414, "y": 138, "w": 82, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "tile_b_subtitle",
            "label": "Wi-Fi, airplane mode, VPN",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 414, "y": 166, "w": 164, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 760, "height": 420}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_primary_area"
    )
    tile_groups = [group for group in primary["subregion_groups"] if group["role"] == "tile_card_parent"]
    assert len(tile_groups) == 2
    by_card = {next(item_id for item_id in group["member_item_ids"] if item_id.startswith("tile_") and item_id in {"tile_a", "tile_b"}): group for group in tile_groups}
    assert set(by_card["tile_a"]["member_item_ids"]) == {"tile_a", "tile_a_title", "tile_a_subtitle"}
    assert set(by_card["tile_b"]["member_item_ids"]) == {"tile_b", "tile_b_title", "tile_b_subtitle"}
    assert by_card["tile_a"]["bbox"] == {"x": 120, "y": 120, "w": 220, "h": 88}
    assert by_card["tile_b"]["bbox"] == {"x": 380, "y": 120, "w": 220, "h": 88}
    assert by_card["tile_a"]["bbox"]["x"] + by_card["tile_a"]["bbox"]["w"] < by_card["tile_b"]["bbox"]["x"]
    assert all(group["execute_binding_enabled"] is False for group in tile_groups)


def test_two_stage_groups_text_only_settings_tiles_without_visible_card_bbox(tmp_path):
    inventory = [
        {
            "number": "3.1",
            "item_id": "device_title",
            "label": "设备",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 411, "y": 313, "w": 33, "h": 19},
            "review_only": True,
        },
        {
            "number": "3.2",
            "item_id": "device_icon",
            "label": "device icon",
            "role": "icon",
            "item_type": "review_only",
            "bbox": {"x": 370, "y": 314, "w": 24, "h": 24},
            "review_only": True,
        },
        {
            "number": "3.3",
            "item_id": "device_subtitle",
            "label": "蓝牙、打印机、鼠标",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 409, "y": 330, "w": 116, "h": 22},
            "review_only": True,
        },
        {
            "number": "3.4",
            "item_id": "apps_title",
            "label": "应用",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 411, "y": 418, "w": 33, "h": 19},
            "review_only": True,
        },
        {
            "number": "3.5",
            "item_id": "apps_icon",
            "label": "apps icon",
            "role": "icon",
            "item_type": "review_only",
            "bbox": {"x": 370, "y": 419, "w": 24, "h": 24},
            "review_only": True,
        },
        {
            "number": "3.6",
            "item_id": "apps_subtitle",
            "label": "卸载、默认值",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 409, "y": 434, "w": 79, "h": 24},
            "review_only": True,
        },
        {
            "number": "3.7",
            "item_id": "settings_search",
            "label": "查找设置",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 452, "y": 222, "w": 57, "h": 18},
            "review_only": True,
        },
    ]
    groups = two_stage._tile_card_parent_groups(
        region={"region_id": "structure_region_primary_area", "label": "Primary Area", "bbox": {"x": 0, "y": 0, "w": 760, "h": 520}},
        numbered_items=inventory,
    )
    tile_groups = [
        group
        for group in groups
        if group["role"] == "tile_card_parent" and group["source"] == "stage2_primary_text_tile_card_parent_grouping"
    ]

    assert len(tile_groups) == 2
    by_title = {group["member_item_ids"][0]: group for group in tile_groups}
    assert by_title["device_title"]["member_item_ids"] == ["device_title", "device_subtitle"]
    assert by_title["apps_title"]["member_item_ids"] == ["apps_title", "apps_subtitle"]
    assert by_title["device_title"]["bbox"]["x"] <= 393
    assert by_title["device_title"]["bbox"]["w"] >= 150
    assert by_title["device_title"]["bbox"]["h"] >= 64
    assert all(group["execute_binding_enabled"] is False for group in tile_groups)
    assert all(group["artifact_is_authorization"] is False for group in tile_groups)


def test_two_stage_binds_section_title_to_following_card_group(tmp_path):
    image_path = tmp_path / "section_cards.png"
    from PIL import Image

    Image.new("RGB", (720, 520), "white").save(image_path)
    inventory = [
        {
            "item_id": "section_title",
            "label": "Recommended for you",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 120, "w": 180, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "card_a",
            "label": "First card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 170, "w": 180, "h": 180},
            "review_only": True,
        },
        {
            "item_id": "card_b",
            "label": "Second card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 330, "y": 170, "w": 180, "h": 180},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_primary_area"
    )
    groups_by_role = {group["role"]: group for group in primary["subregion_groups"]}
    assert "media_card_group" in groups_by_role
    assert "section_parent" in groups_by_role
    section = groups_by_role["section_parent"]
    assert section["title_item_id"] == "section_title"
    assert section["child_group_ids"] == [groups_by_role["media_card_group"]["group_id"]]
    assert section["parent_child_policy"] == "section_title_binds_to_following_card_or_list_group"
    assert section["bbox"]["y"] <= inventory[0]["bbox"]["y"]
    assert section["bbox"]["h"] > groups_by_role["media_card_group"]["bbox"]["h"]
    fused_sections = [
        item
        for item in result["fusion"]["fused_review_boxes"]
        if item.get("role") == "section_parent"
    ]
    assert fused_sections


def test_two_stage_marks_incomplete_visual_card_parent_as_needs_review(tmp_path):
    image_path = tmp_path / "incomplete_card_parent.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (760, 430), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((100, 150, 260, 310), radius=8, fill=(40, 90, 180))
    draw.rounded_rectangle((300, 150, 460, 310), radius=8, fill=(180, 80, 40))
    draw.rounded_rectangle((500, 150, 680, 310), radius=8, fill=(232, 232, 232), outline=(214, 214, 214))
    draw.polygon([(590, 178), (612, 224), (664, 232), (626, 264), (636, 310), (590, 284), (544, 310), (554, 264), (516, 232), (568, 224)], fill=(240, 36, 48))
    image.save(image_path)
    inventory = [
        {
            "item_id": "section_title",
            "label": "Recent cards",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 100, "y": 110, "w": 150, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "card_1_text",
            "label": "Card One",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 108, "y": 322, "w": 90, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "card_2_text",
            "label": "Card Two",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 308, "y": 322, "w": 90, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "incomplete_title",
            "label": "Favorite songs",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 508, "y": 322, "w": 130, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 760, "height": 430}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_primary_area"
    )
    incomplete = next(item for item in primary["numbered_items"] if item["label"] == "Favorite songs")
    assert incomplete["role"] == "card_parent_incomplete"
    assert incomplete["needs_review"] is True
    assert incomplete["review_required"] is True
    assert incomplete["action_candidate"] is False
    assert incomplete["incomplete_reason"] == "missing_card_slot_or_click_area"
    assert incomplete["overlay_style"]["tone"] == "needs_review_incomplete_card"
    assert incomplete["bbox_policy"] == "incomplete_visual_card_parent_needs_review"
    assert incomplete["execute_binding_enabled"] is False


def test_two_stage_infers_dense_row_slot_for_placeholder_media_card(tmp_path):
    image_path = tmp_path / "placeholder_dense_row_card.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1120, 520), "white")
    draw = ImageDraw.Draw(image)
    slots = [
        (100, 150, 260, 310, (40, 90, 180)),
        (300, 150, 460, 310, (248, 248, 248)),
        (500, 150, 660, 310, (180, 80, 40)),
        (700, 150, 860, 310, (40, 160, 100)),
        (900, 150, 1060, 310, (180, 40, 140)),
    ]
    for index, (x1, y1, x2, y2, color) in enumerate(slots):
        outline = None if index == 1 else (214, 214, 214)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=8, fill=color, outline=outline)
        if index == 1:
            draw.polygon(
                [
                    (380, 190),
                    (398, 224),
                    (436, 230),
                    (408, 254),
                    (416, 288),
                    (380, 268),
                    (344, 288),
                    (352, 254),
                    (324, 230),
                    (362, 224),
                ],
                fill=(240, 36, 48),
            )
    image.save(image_path)
    inventory = [
        {
            "item_id": "main_gallery",
            "label": "Main gallery",
            "role": "content_card",
            "item_type": "card",
            "bbox": {"x": 90, "y": 120, "w": 990, "h": 250},
            "review_only": True,
        },
        *[
        {
            "item_id": f"card_{index}_text",
            "label": label,
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": x, "y": 322, "w": w, "h": 24},
            "review_only": True,
        }
        for index, (label, x, w) in enumerate(
            [
                ("Card One", 108, 90),
                ("Favorite songs", 308, 130),
                ("Card Three", 508, 110),
                ("Card Four", 708, 100),
                ("Card Five", 908, 100),
            ],
            start=1,
        )
        ],
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1120, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item
        for item in result["stage2_numbering"]["regions"]
        if item["region_id"] == "structure_region_primary_area"
        or item["region_id"].endswith("__stage1_5__message_thread")
    )
    favorite = next(item for item in primary["numbered_items"] if item["label"] == "Favorite songs")
    assert favorite["role"] == "media_card"
    assert favorite["bbox"]["x"] <= 308
    assert favorite["bbox"]["w"] >= 150
    assert favorite["card_parent_validation"]["complete"] is True
    assert favorite["card_parent_validation"]["slot_inference"]["applied"] is True
    assert favorite["card_parent_validation"]["slot_inference"]["reason"] == "dense_row_placeholder_visual_slot_inferred"
    assert favorite["bbox_policy"] == "visual_media_card_parent_with_inferred_dense_row_slot"
    assert favorite["execute_binding_enabled"] is False


def test_two_stage_media_card_children_do_not_cross_next_section_heading(tmp_path):
    image_path = tmp_path / "card_section_boundary.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (760, 560), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((100, 110, 260, 270), radius=8, fill=(40, 90, 180))
    draw.rounded_rectangle((300, 110, 460, 270), radius=8, fill=(180, 80, 40))
    draw.rectangle((100, 510, 260, 559), fill=(40, 160, 100))
    draw.rectangle((300, 510, 460, 559), fill=(180, 40, 140))
    image.save(image_path)
    inventory = [
        {
            "item_id": "first_section",
            "label": "Recently played",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 100, "y": 72, "w": 150, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "first_card_title",
            "label": "Station One",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 106, "y": 286, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "next_section",
            "label": "Game music",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 100, "y": 334, "w": 130, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "next_card_title",
            "label": "Eorzean Symphony",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 106, "y": 512, "w": 160, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 760, "height": 560}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_primary_area"
    )
    first_card = next(item for item in primary["numbered_items"] if item["label"] == "Station One")
    first_child_ids = {child["item_id"] for child in first_card["children"]}
    assert "next_section" not in first_child_ids
    assert "next_card_title" not in first_child_ids
    assert first_card["bbox"]["y"] + first_card["bbox"]["h"] <= inventory[2]["bbox"]["y"]


def test_two_stage_groups_bottom_edge_text_fragments_as_partial_visible_cards(tmp_path):
    image_path = tmp_path / "partial_cards.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (720, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((112, 450, 286, 519), fill=(40, 80, 180))
    draw.rectangle((340, 450, 480, 519), fill=(180, 80, 40))
    draw.rectangle((560, 450, 690, 519), fill=(40, 160, 100))
    image.save(image_path)
    inventory = [
        {
            "item_id": "section_title",
            "label": "More music",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 360, "w": 110, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "partial_left_a",
            "label": "Eorzean",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 480, "w": 72, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "partial_left_b",
            "label": "Symphony",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 190, "y": 482, "w": 82, "h": 20},
            "review_only": True,
        },
        {
            "item_id": "partial_right",
            "label": "Expedition",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 360, "y": 478, "w": 100, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_primary_area"
    )
    synthesis = primary["visual_small_control_refinement"]["partial_visible_card_synthesis"]
    assert synthesis["applied"] is True
    partial_cards = [item for item in primary["numbered_items"] if item["role"] == "partial_visible_card"]
    assert len(partial_cards) == 3
    assert any(item["item_id"] == "section_title" and item["role"] == "text" for item in primary["numbered_items"])
    assert all(item["partial_visible"] is True for item in partial_cards)
    child_label_sets = [{child["label"] for child in item["children"]} for item in partial_cards]
    assert {"Eorzean", "Symphony"} in child_label_sets
    assert {"Expedition"} in child_label_sets
    assert any(not item["children"] for item in partial_cards)
    assert {item["item_id"] for item in partial_cards} == {
        "partial_visible_card_1",
        "partial_visible_card_2",
        "partial_visible_card_3",
    }
    assert "partial_left_a" not in {item["item_id"] for item in primary["numbered_items"]}
    partial_group = next(group for group in primary["subregion_groups"] if group["role"] == "partial_visible_card_group")
    assert len(partial_group["member_numbers"]) == 3
    section_parent = next(group for group in primary["subregion_groups"] if group["role"] == "section_parent")
    assert section_parent["child_group_ids"] == [partial_group["group_id"]]


def test_partial_card_reconciliation_merges_fragments_using_peer_card_width() -> None:
    def fragment(item_id: str, label: str, x: int, y: int, w: int) -> dict:
        return {
            "number": item_id,
            "item_id": item_id,
            "label": label,
            "role": "text",
            "bbox": {"x": x, "y": y, "w": w, "h": 22},
        }

    left_title = fragment("1.1", "First panel", 110, 472, 96)
    left_action = fragment("1.2", "More", 302, 476, 46)
    right_title = fragment("1.3", "Second panel", 390, 472, 112)
    right_action = fragment("1.4", "More", 592, 476, 46)

    entries = two_stage._merge_partial_text_clusters_with_visual_boxes(
        [[left_title], [left_action], [right_title], [right_action]],
        [{"x": 100, "y": 450, "w": 250, "h": 70}],
    )

    assert len(entries) == 2
    assert [{item["item_id"] for item in entry["items"]} for entry in entries] == [
        {"1.1", "1.2"},
        {"1.3", "1.4"},
    ]
    assert entries[0]["visual_bbox"] == {"x": 100, "y": 450, "w": 250, "h": 70}
    assert entries[1]["visual_bbox"]["y"] == 450
    assert entries[1]["visual_bbox"]["h"] == 70
    assert entries[1]["visual_bbox"]["w"] >= 248


def test_partial_visible_synthesis_suppresses_duplicates_over_existing_structured_cards(tmp_path):
    image_path = tmp_path / "partial_cards_with_existing_card.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (720, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((112, 450, 286, 519), fill=(40, 80, 180))
    image.save(image_path)
    inventory = [
        {
            "item_id": "section_title",
            "label": "More music",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 360, "w": 110, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "existing_bottom_card",
            "label": "Eorzean Symphony",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 112, "y": 448, "w": 176, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "partial_left_a",
            "label": "Eorzean",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 120, "y": 480, "w": 72, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "partial_left_b",
            "label": "Symphony",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 190, "y": 482, "w": 82, "h": 20},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_primary_area"
    )
    numbered_items = [
        item
        for region in result["stage2_numbering"]["regions"]
        for item in region.get("numbered_items", [])
    ]
    partial_cards = [item for item in numbered_items if item["role"] == "partial_visible_card"]
    assert not partial_cards
    assert any(item["item_id"] == "existing_bottom_card" and item["role"] == "news_card" for item in primary["numbered_items"])
    synthesis = primary["visual_small_control_refinement"]["partial_visible_card_synthesis"]
    assert synthesis["suppressed_duplicate_partial_card_count"] >= 1


def test_two_stage_does_not_turn_bottom_toolbar_text_into_partial_cards(tmp_path):
    image_path = tmp_path / "chat_toolbar.png"
    from PIL import Image

    Image.new("RGB", (720, 520), "white").save(image_path)
    inventory = [
        {
            "item_id": "chat_message",
            "label": "hello there",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 220, "y": 300, "w": 160, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "toolbar_icon",
            "label": "?",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 260, "y": 460, "w": 24, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "send_text",
            "label": "发送",
            "role": "text",
            "item_type": "text",
            "bbox": {"x": 560, "y": 480, "w": 42, "h": 20},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"primary_area": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 720, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = result["stage2_numbering"]["regions"]
    assert not [
        item
        for region in regions
        for item in region.get("numbered_items", [])
        if item["role"] == "partial_visible_card"
    ]
    toolbar_groups = [
        group
        for region in regions
        for group in region.get("subregion_groups", [])
        if group["role"] == "input_toolbar_region"
    ]
    for toolbar_group in toolbar_groups:
        assert toolbar_group["parent_child_policy"] == "bottom_toolbar_controls_and_send_button_form_display_only_input_area"
        assert toolbar_group["display_only"] is True
        assert toolbar_group["execute_binding_enabled"] is False
        assert toolbar_group["artifact_is_authorization"] is False


def test_two_stage_merges_caption_when_visual_artwork_bbox_is_narrow(tmp_path):
    image_path = tmp_path / "narrow_artwork_card.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (520, 360), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((92, 92, 220, 220), fill=(215, 40, 40))
    draw.rectangle((310, 92, 438, 220), fill=(245, 245, 245), outline=(225, 225, 225), width=2)
    draw.polygon([(374, 118), (392, 154), (438, 154), (400, 178), (414, 216), (374, 194), (334, 216), (348, 178), (310, 154), (356, 154)], fill=(235, 30, 48))
    image.save(image_path)

    inventory = [
        {
            "item_id": "main_area",
            "label": "Main content area",
            "role": "content_area",
            "item_type": "card",
            "bbox": {"x": 90, "y": 90, "w": 360, "h": 210},
            "review_only": True,
        },
        {
            "item_id": "red_title",
            "label": "Red card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 102, "y": 230, "w": 80, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "star_title",
            "label": "Star card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 302, "y": 230, "w": 80, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 520, "height": 360}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    main = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    star_card = next(
        item
        for item in main["numbered_items"]
        if item["role"] == "media_card" and any(child["label"] == "Star card" for child in item["children"])
    )
    assert any(child["label"] == "Star card" for child in star_card["children"])
    assert star_card["bbox"]["x"] <= 302
    assert star_card["bbox"]["w"] < 180


def test_two_stage_does_not_expand_one_media_card_to_oversized_row_container(tmp_path):
    image_path = tmp_path / "media_cards_with_oversized_row_container.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (980, 440), "white")
    draw = ImageDraw.Draw(image)
    card_boxes = [
        (60, 90, 250, 320),
        (280, 90, 470, 320),
        (500, 90, 690, 320),
        (720, 90, 910, 320),
    ]
    for box, color in zip(card_boxes, ((210, 40, 40), (40, 110, 210), (40, 170, 90), (170, 50, 170))):
        draw.rounded_rectangle(box, radius=8, fill=color)
    image.save(image_path)

    inventory = [
        {
            "item_id": "whole_card_row",
            "label": "Card row",
            "role": "listitem",
            "item_type": "layout",
            "bbox": {"x": 40, "y": 70, "w": 900, "h": 290},
            "review_only": True,
        },
        *[
            {
                "item_id": f"card_title_{index}",
                "label": f"Card {index}",
                "role": "text",
                "item_type": "readable",
                "bbox": {"x": x + 10, "y": 330, "w": 100, "h": 22},
                "review_only": True,
            }
            for index, (x, _y1, _x2, _y2) in enumerate(card_boxes, start=1)
        ],
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 980, "height": 440}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    main = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    cards = [item for item in main["numbered_items"] if item["role"] == "media_card"]
    assert len(cards) == 4
    assert all(card["bbox"]["w"] < 260 for card in cards)
    assert all(child["item_id"] != "whole_card_row" for card in cards for child in card["children"])


def test_two_stage_keeps_inter_row_section_heading_outside_media_card(tmp_path):
    image_path = tmp_path / "section_heading_between_card_rows.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (520, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 220, 220), fill=(220, 30, 30))
    draw.rectangle((250, 100, 370, 220), fill=(20, 140, 220))
    draw.rectangle((100, 340, 220, 460), fill=(60, 60, 120))
    draw.rectangle((250, 340, 370, 460), fill=(70, 130, 60))
    image.save(image_path)

    inventory = [
        {
            "item_id": "main_area",
            "label": "Main content area",
            "role": "content_area",
            "item_type": "card",
            "bbox": {"x": 90, "y": 90, "w": 300, "h": 390},
            "review_only": True,
        },
        {
            "item_id": "top_card_title",
            "label": "Top Card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 108, "y": 230, "w": 90, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "next_section_title",
            "label": "Next Section",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 100, "y": 286, "w": 120, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "lower_card_title",
            "label": "Lower Card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 108, "y": 468, "w": 96, "h": 22},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 520, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    main = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    cards = [item for item in main["numbered_items"] if item["role"] == "media_card"]
    assert cards
    assert all("Next Section" not in [child["label"] for child in card["children"]] for card in cards)
    assert any(item["label"] == "Next Section" and item["role"] == "text" for item in main["numbered_items"])
    top_card = next(card for card in cards if any(child["label"] == "Top Card" for child in card["children"]))
    assert top_card["bbox"]["y"] + top_card["bbox"]["h"] < 286


def test_two_stage_keeps_following_section_heading_outside_single_row_media_card(tmp_path):
    image_path = tmp_path / "single_row_following_section.png"
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (520, 520), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 260, 260), fill=(220, 30, 30))
    draw.rectangle((300, 100, 460, 260), fill=(20, 140, 220))
    image.save(image_path)

    inventory = [
        {
            "item_id": "main_area",
            "label": "Main content area",
            "role": "content_area",
            "item_type": "card",
            "bbox": {"x": 90, "y": 90, "w": 390, "h": 380},
            "review_only": True,
        },
        {
            "item_id": "first_card_title",
            "label": "First card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 108, "y": 272, "w": 90, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "second_card_title",
            "label": "Second card",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 308, "y": 272, "w": 110, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "next_section_title",
            "label": "Next Section",
            "role": "heading",
            "item_type": "heading",
            "bbox": {"x": 100, "y": 330, "w": 140, "h": 24},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 520, "height": 520}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    main = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_main_content"
    )
    cards = [item for item in main["numbered_items"] if item["role"] == "media_card"]
    assert cards
    assert all("Next Section" not in [child["label"] for child in card["children"]] for card in cards)
    assert any(item["label"] == "Next Section" and item["role"] == "heading" for item in main["numbered_items"])
    assert all(card["bbox"]["y"] + card["bbox"]["h"] < 330 for card in cards)


def test_stage1_region_localization_report_skips_numbering_and_exposes_calibration_prompt(tmp_path):
    image_path = tmp_path / "apple_music.png"
    from PIL import Image

    Image.new("RGB", (900, 650), "white").save(image_path)
    inventory = [
        {
            "item_id": "nav_home",
            "label": "Home icon",
            "role": "nav_rail_icon_review_only",
            "item_type": "review_only",
            "bbox": {"x": 16, "y": 140, "w": 24, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "card_1",
            "label": "Energy album card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 120, "y": 240, "w": 260, "h": 190},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["nav_home"]},
            "main_content": {"item_ids": ["card_1"]},
        },
        "nodes": {
            "nav_home": inventory[0],
            "card_1": inventory[1],
        },
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 900, "height": 650}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert report["contract_version"] == "learn_stage1_region_localization_report_v1"
    assert report["scope"] == "stage1_region_localization_only"
    assert report["stage2_numbering_skipped"] is True
    assert report["pathgraph_generation_skipped"] is True
    assert "stage2_numbering" not in report
    assert report["model_call_plan"]["semantic_model"] == "qwen3_vl_8b_q4_k_m"
    assert report["model_call_plan"]["coordinate_model"] == "vista_4b_transformers"
    prompt = report["model_call_plan"]["prompt"]
    assert "Do not number inner buttons" in prompt
    assert "replace it completely" in prompt
    assert "full screenshot coordinates" in prompt
    assert report["stage1_region_localization"]["localized_region_count"] == 2
    assert report["calibration_diagnostics"]["geometry_only_region_count"] == 0
    assert report["calibration_diagnostics"]["needs_prompt_or_model_calibration"] is False
    assert {
        item["risk"] for item in report["calibration_diagnostics"]["diagnostics"]
    } == {"heuristic_calibrated_needs_visual_review"}
    assert report["display_readiness"]["stage1_overlay_available"] is True
    assert Path(report["overlay_path"]).exists()


def test_stage1_web_surface_splits_right_edge_floating_controls_from_primary(tmp_path):
    image_path = tmp_path / "web_surface_floating_controls.png"
    from PIL import Image

    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "browser_address",
            "label": "https://example.org",
            "role": "address_bar",
            "item_type": "browser_chrome",
            "bbox": {"x": 70, "y": 16, "w": 860, "h": 34},
            "review_only": True,
        },
        {
            "item_id": "site_nav",
            "label": "Docs Community Jobs",
            "role": "nav_item",
            "item_type": "section",
            "bbox": {"x": 0, "y": 80, "w": 1200, "h": 58},
            "review_only": True,
        },
        {
            "item_id": "hero_content_column",
            "label": "Centered web content column",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 170, "w": 600, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "floating_translate",
            "label": "translate",
            "role": "floating_button",
            "item_type": "button",
            "bbox": {"x": 1160, "y": 470, "w": 32, "h": 32},
            "review_only": True,
        },
        {
            "item_id": "floating_tools",
            "label": "tools",
            "role": "floating_button",
            "item_type": "button",
            "bbox": {"x": 1160, "y": 525, "w": 32, "h": 32},
            "review_only": True,
        },
        {
            "item_id": "vertical_scrollbar",
            "label": "scrollbar",
            "role": "scrollbar",
            "item_type": "control",
            "bbox": {"x": 1192, "y": 70, "w": 8, "h": 700},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["browser_address"]},
            "top_bar": {"item_ids": ["site_nav"]},
            "primary_area": {"item_ids": [item["item_id"] for item in inventory[2:]]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    regions = {region["zone_id"]: region for region in report["stage1_region_localization"]["regions"]}
    assert "floating_controls" in regions
    assert regions["floating_controls"]["bbox"]["x"] >= 1150
    assert regions["primary_area"]["bbox"]["x"] == 0
    assert regions["primary_area"]["bbox"]["w"] == 1200
    assert "floating_translate" not in regions["primary_area"]["item_ids"]
    assert "vertical_scrollbar" not in regions["primary_area"]["item_ids"]
    assert {
        "floating_translate",
        "floating_tools",
        "vertical_scrollbar",
    }.issubset(set(regions["floating_controls"]["item_ids"]))
    granularity = report["stage1_granularity_review"]
    assert granularity["status"] == "stage1_geometry_passed_needs_granularity_review"
    assert granularity["recommended_next_step"] == "stage1_5_subpane_partition"
    assert any(
        issue["issue"] == "browser_primary_scope_ambiguous_full_page_vs_content_column"
        for issue in granularity["issues"]
    )


def test_stage1_granularity_review_flags_chat_primary_as_stage1_5_candidate(tmp_path):
    image_path = tmp_path / "chat_surface.png"
    from PIL import Image

    Image.new("RGB", (1200, 780), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_nav",
            "label": "Chats",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 20, "y": 120, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_bar",
            "label": "Search and title",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 80, "y": 0, "w": 900, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "conversation_list",
            "label": "Conversation list",
            "role": "conversation_list",
            "item_type": "list_pane",
            "bbox": {"x": 80, "y": 96, "w": 260, "h": 620},
            "review_only": True,
        },
        {
            "item_id": "message_thread",
            "label": "Chat thread messages",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 350, "y": 96, "w": 560, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "composer",
            "label": "Message input area Send",
            "role": "composer",
            "item_type": "input_area",
            "bbox": {"x": 350, "y": 630, "w": 560, "h": 84},
            "review_only": True,
        },
        {
            "item_id": "bottom_bar",
            "label": "Bottom input shell",
            "role": "layout",
            "item_type": "section",
            "bbox": {"x": 80, "y": 600, "w": 830, "h": 116},
            "metadata": {"surface_zone": "bottom_bar"},
            "review_only": True,
        },
        {
            "item_id": "bottom_tool_row",
            "label": "Attach emoji voice send tools",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 360, "y": 610, "w": 520, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "bottom_icon_glyphs",
            "label": ">□>",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 604, "w": 82, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "right_detail",
            "label": "Members",
            "role": "right_sidebar",
            "item_type": "side_panel",
            "bbox": {"x": 930, "y": 96, "w": 250, "h": 620},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["left_nav"]},
            "top_bar": {"item_ids": ["top_bar"]},
            "primary_area": {
                "item_ids": [
                    "conversation_list",
                    "message_thread",
                    "composer",
                    "bottom_bar",
                    "bottom_tool_row",
                    "bottom_icon_glyphs",
                ]
            },
            "right_sidebar": {"item_ids": ["right_detail"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 780}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert report["region_selection_audit"]["passed"] is True
    granularity = report["stage1_granularity_review"]
    assert granularity["status"] == "stage1_geometry_passed_needs_granularity_review"
    assert any(issue["issue"] == "primary_contains_multiple_work_panes" for issue in granularity["issues"])
    evidence = {
        item
        for issue in granularity["issues"]
        if issue["issue"] == "primary_contains_multiple_work_panes"
        for item in issue["evidence"]
    }
    assert {
        "conversation_or_list_pane_signal",
        "message_thread_signal",
        "bottom_composer_signal",
    }.issubset(evidence)


def test_stage1_5_partition_suggests_web_content_column_without_shrinking_stage1(tmp_path):
    image_path = tmp_path / "web_surface.png"
    from PIL import Image

    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "browser_address",
            "label": "https://python.org",
            "role": "browser_address_bar",
            "item_type": "browser_chrome",
            "bbox": {"x": 80, "y": 8, "w": 900, "h": 40},
            "review_only": True,
        },
        {
            "item_id": "site_nav",
            "label": "Docs Community Jobs",
            "role": "nav_item",
            "item_type": "section",
            "bbox": {"x": 0, "y": 80, "w": 1200, "h": 58},
            "review_only": True,
        },
        {
            "item_id": "hero_content_column",
            "label": "Centered web content column",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 170, "w": 600, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "floating_translate",
            "label": "translate",
            "role": "floating_button",
            "item_type": "button",
            "bbox": {"x": 1160, "y": 470, "w": 32, "h": 32},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["browser_address"]},
            "top_bar": {"item_ids": ["site_nav"]},
            "primary_area": {"item_ids": ["hero_content_column", "floating_translate"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    primary = next(region for region in report["stage1_region_localization"]["regions"] if region["zone_id"] == "primary_area")
    assert primary["bbox"]["x"] == 0
    assert primary["bbox"]["w"] == 1200
    partition = report["stage1_5_partition"]
    assert partition["status"] == "stage1_5_suggested"
    assert partition["stage1_regions_unchanged"] is True
    assert partition["pathgraph_generation_skipped"] is True
    content_columns = [item for item in partition["subregions"] if item["role"] == "content_column"]
    assert len(content_columns) == 1
    assert content_columns[0]["parent_region_id"] == primary["region_id"]
    assert content_columns[0]["bbox"]["x"] == 300
    assert content_columns[0]["bbox"]["w"] == 600
    assert "hero_content_column" in content_columns[0]["item_ids"]
    assert report["stage1_5_overlay_path"]


def test_two_stage_numbers_stage1_5_web_content_column_instead_of_broad_primary(tmp_path):
    image_path = tmp_path / "web_surface_two_stage.png"
    from PIL import Image

    Image.new("RGB", (1200, 800), "white").save(image_path)
    inventory = [
        {
            "item_id": "browser_address",
            "label": "https://python.org",
            "role": "browser_address_bar",
            "item_type": "browser_chrome",
            "bbox": {"x": 80, "y": 8, "w": 900, "h": 40},
            "review_only": True,
        },
        {
            "item_id": "site_nav",
            "label": "Docs Community Jobs",
            "role": "nav_item",
            "item_type": "section",
            "bbox": {"x": 0, "y": 80, "w": 1200, "h": 58},
            "review_only": True,
        },
        {
            "item_id": "hero_content_column",
            "label": "Centered web content column",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 300, "y": 170, "w": 600, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "hero_card",
            "label": "Hero card",
            "role": "news_card",
            "item_type": "card",
            "bbox": {"x": 340, "y": 250, "w": 220, "h": 120},
            "review_only": True,
        },
        {
            "item_id": "floating_translate",
            "label": "translate",
            "role": "floating_button",
            "item_type": "button",
            "bbox": {"x": 1160, "y": 470, "w": 32, "h": 32},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "browser_chrome": {"item_ids": ["browser_address"]},
            "top_bar": {"item_ids": ["site_nav"]},
            "primary_area": {"item_ids": ["hero_content_column", "hero_card", "floating_translate"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 800}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
    )

    assert result["stage1_5_partition"]["status"] == "stage1_5_suggested"
    region_ids = {region["region_id"] for region in result["stage2_numbering"]["regions"]}
    assert "structure_region_primary_area" not in region_ids
    assert "structure_region_primary_area__stage1_5__content_column" in region_ids
    content_column = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if region["region_id"] == "structure_region_primary_area__stage1_5__content_column"
    )
    assert content_column["input_stage1_5_subregion"]["role"] == "content_column"
    assert content_column["bbox"]["x"] == 300
    assert content_column["bbox"]["w"] == 600
    labels = {item["label"] for item in content_column["numbered_items"]}
    assert "Hero card" in labels
    assert "translate" not in labels


def test_stage1_5_stage2_selection_only_accepts_contained_main_content_subregions():
    localized_regions = [
        {
            "region_id": "structure_region_top_bar",
            "label": "Top bar",
            "bbox": {"x": 80, "y": 0, "w": 920, "h": 70},
        },
        {
            "region_id": "structure_region_primary_area",
            "label": "Primary",
            "bbox": {"x": 80, "y": 70, "w": 920, "h": 650},
        },
    ]
    subregions = [
        {
            "subregion_id": "top_controls",
            "parent_region_id": "structure_region_top_bar",
            "role": "top_controls",
            "bbox": {"x": 120, "y": 8, "w": 180, "h": 42},
        },
        {
            "subregion_id": "content_column",
            "parent_region_id": "structure_region_primary_area",
            "role": "content_column",
            "bbox": {"x": 180, "y": 120, "w": 620, "h": 520},
        },
    ]

    annotated, report = two_stage._stage1_5_stage2_selection_report(
        subregions=subregions,
        localized_regions=localized_regions,
    )

    by_id = {item["subregion_id"]: item for item in annotated}
    assert by_id["top_controls"]["stage2_numbering_eligible"] is False
    assert by_id["top_controls"]["stage2_numbering_selection_reason"] == "stage1_5_only_main_content_may_replace_stage2_input"
    assert by_id["content_column"]["stage2_numbering_eligible"] is True
    assert report["eligible_count"] == 1
    assert report["rejected_count"] == 1


def test_stage2_input_ignores_unstable_stage1_5_partition_for_structure_bars():
    localized_regions = [
        {
            "region_no": 1,
            "region_id": "structure_region_top_bar",
            "label": "Top bar",
            "bbox": {"x": 80, "y": 0, "w": 920, "h": 70},
            "item_ids": ["play"],
        },
        {
            "region_no": 2,
            "region_id": "structure_region_primary_area",
            "label": "Primary",
            "bbox": {"x": 80, "y": 70, "w": 920, "h": 650},
            "item_ids": ["card"],
        },
    ]
    unstable_partition = {
        "subregions": [
            {
                "subregion_id": "bad_top_split",
                "parent_region_id": "structure_region_top_bar",
                "role": "top_controls",
                "bbox": {"x": 120, "y": 8, "w": 180, "h": 42},
                "item_ids": ["play"],
                "stage2_numbering_eligible": False,
            }
        ]
    }

    regions = two_stage._stage2_input_regions(
        localized_regions=localized_regions,
        stage1_5_partition=unstable_partition,
        items_by_id={
            "play": {"item_id": "play", "bbox": {"x": 140, "y": 20, "w": 24, "h": 24}},
            "card": {"item_id": "card", "bbox": {"x": 120, "y": 120, "w": 240, "h": 260}},
        },
    )

    assert [region["region_id"] for region in regions] == [
        "structure_region_top_bar",
        "structure_region_primary_area",
    ]
    assert all(region.get("stage") != "stage1_5_subregion_for_stage2_numbering" for region in regions)


def test_stage1_5_partition_suggests_chat_subpanes_inside_primary(tmp_path):
    image_path = tmp_path / "chat_surface.png"
    from PIL import Image

    Image.new("RGB", (1200, 780), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_nav",
            "label": "Chats",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 20, "y": 120, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_bar",
            "label": "Search and title",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 80, "y": 0, "w": 900, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "conversation_list",
            "label": "Conversation list",
            "role": "conversation_list",
            "item_type": "list_pane",
            "bbox": {"x": 80, "y": 96, "w": 260, "h": 620},
            "review_only": True,
        },
        {
            "item_id": "message_thread",
            "label": "Chat thread messages",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 350, "y": 96, "w": 560, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "composer",
            "label": "Message input area Send",
            "role": "composer",
            "item_type": "input_area",
            "bbox": {"x": 350, "y": 630, "w": 560, "h": 84},
            "review_only": True,
        },
        {
            "item_id": "bottom_bar",
            "label": "Bottom input shell",
            "role": "layout",
            "item_type": "section",
            "bbox": {"x": 80, "y": 600, "w": 830, "h": 116},
            "metadata": {"surface_zone": "bottom_bar"},
            "review_only": True,
        },
        {
            "item_id": "bottom_tool_row",
            "label": "Attach emoji voice send tools",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 360, "y": 610, "w": 520, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "bottom_icon_glyphs",
            "label": ">□>",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 604, "w": 82, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "right_detail",
            "label": "Members",
            "role": "right_sidebar",
            "item_type": "side_panel",
            "bbox": {"x": 930, "y": 96, "w": 250, "h": 620},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["left_nav"]},
            "top_bar": {"item_ids": ["top_bar"]},
            "primary_area": {
                "item_ids": [
                    "conversation_list",
                    "message_thread",
                    "composer",
                    "bottom_bar",
                    "bottom_tool_row",
                    "bottom_icon_glyphs",
                ]
            },
            "right_sidebar": {"item_ids": ["right_detail"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 780}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    partition = report["stage1_5_partition"]
    roles = {item["role"] for item in partition["subregions"]}
    assert partition["status"] == "stage1_5_suggested"
    assert {"conversation_list", "message_thread", "bottom_composer"}.issubset(roles)
    message_thread = next(item for item in partition["subregions"] if item["role"] == "message_thread")
    conversation_list = next(item for item in partition["subregions"] if item["role"] == "conversation_list")
    bottom_composer = next(item for item in partition["subregions"] if item["role"] == "bottom_composer")
    assert message_thread["bbox"]["y"] + message_thread["bbox"]["h"] == bottom_composer["bbox"]["y"]
    assert conversation_list["bbox"]["y"] + conversation_list["bbox"]["h"] == bottom_composer["bbox"]["y"]
    assert conversation_list["bbox"]["x"] == conversation_list["parent_region_bbox"]["x"]
    assert conversation_list["bbox"]["x"] + conversation_list["bbox"]["w"] == message_thread["bbox"]["x"]
    assert bottom_composer["bbox"]["x"] == message_thread["bbox"]["x"]
    assert bottom_composer["bbox"]["w"] == message_thread["bbox"]["w"]
    assert bottom_composer["stage1_5_boundary_review"]["status"] == "composer_bbox_constrained_to_message_channel"
    assert bottom_composer["stage1_5_boundary_review"]["previous_bbox"]["x"] == conversation_list["parent_region_bbox"]["x"]
    assert "bottom_tool_row" in bottom_composer["item_ids"]
    assert "bottom_tool_row" not in message_thread["item_ids"]
    assert "bottom_icon_glyphs" in bottom_composer["item_ids"]
    assert "bottom_icon_glyphs" not in message_thread["item_ids"]
    assert bottom_composer["bbox"]["y"] <= 604
    assert all(item["display_only"] is True for item in partition["subregions"])
    assert all(item["execute_binding_enabled"] is False for item in partition["subregions"])


def test_two_stage_numbers_stage1_5_chat_subpanes_instead_of_broad_primary(tmp_path):
    image_path = tmp_path / "chat_surface_two_stage.png"
    from PIL import Image

    Image.new("RGB", (1200, 780), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_nav",
            "label": "Chats",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 20, "y": 120, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_bar",
            "label": "Search and title",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 80, "y": 0, "w": 900, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "conversation_list",
            "label": "Conversation list",
            "role": "conversation_list",
            "item_type": "list_pane",
            "bbox": {"x": 80, "y": 96, "w": 260, "h": 620},
            "review_only": True,
        },
        {
            "item_id": "message_thread",
            "label": "Chat thread messages",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 350, "y": 96, "w": 560, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "composer",
            "label": "Message input area Send",
            "role": "composer",
            "item_type": "input_area",
            "bbox": {"x": 350, "y": 630, "w": 560, "h": 84},
            "review_only": True,
        },
        {
            "item_id": "bottom_bar",
            "label": "Bottom input shell",
            "role": "layout",
            "item_type": "section",
            "bbox": {"x": 80, "y": 600, "w": 830, "h": 116},
            "metadata": {"surface_zone": "bottom_bar"},
            "review_only": True,
        },
        {
            "item_id": "bottom_tool_row",
            "label": "Attach emoji voice send tools",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 360, "y": 610, "w": 520, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "bottom_icon_glyphs",
            "label": ">□>",
            "role": "text",
            "item_type": "readable",
            "bbox": {"x": 360, "y": 604, "w": 82, "h": 24},
            "review_only": True,
        },
        {
            "item_id": "right_detail",
            "label": "Members",
            "role": "right_sidebar",
            "item_type": "side_panel",
            "bbox": {"x": 930, "y": 96, "w": 250, "h": 620},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["left_nav"]},
            "top_bar": {"item_ids": ["top_bar"]},
            "primary_area": {
                "item_ids": [
                    "conversation_list",
                    "message_thread",
                    "composer",
                    "bottom_bar",
                    "bottom_tool_row",
                    "bottom_icon_glyphs",
                ]
            },
            "right_sidebar": {"item_ids": ["right_detail"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 780}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
    )

    assert result["stage1_5_partition"]["status"] == "stage1_5_suggested"
    region_ids = {region["region_id"] for region in result["stage2_numbering"]["regions"]}
    assert "structure_region_primary_area" not in region_ids
    assert {
        "structure_region_primary_area__stage1_5__conversation_list",
        "structure_region_primary_area__stage1_5__message_thread",
        "structure_region_primary_area__stage1_5__bottom_composer",
    }.issubset(region_ids)
    bottom_composer = next(
        region
        for region in result["stage2_numbering"]["regions"]
        if region["region_id"] == "structure_region_primary_area__stage1_5__bottom_composer"
    )
    assert bottom_composer["input_stage1_5_subregion"]["role"] == "bottom_composer"
    labels = {item["label"] for item in bottom_composer["numbered_items"]}
    assert "Attach emoji voice send tools" in labels
    assert ">□>" in labels


def test_stage1_5_bottom_composer_constrains_tall_shell_to_vertical_evidence(tmp_path):
    image_path = tmp_path / "chat_surface_tall_composer_shell.png"
    from PIL import Image

    Image.new("RGB", (1200, 780), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_nav",
            "label": "Chats",
            "role": "nav_rail_icon_review_only",
            "item_type": "button",
            "bbox": {"x": 20, "y": 120, "w": 28, "h": 28},
            "review_only": True,
        },
        {
            "item_id": "top_bar",
            "label": "Search and title",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 80, "y": 0, "w": 900, "h": 72},
            "review_only": True,
        },
        {
            "item_id": "conversation_list",
            "label": "Conversation list",
            "role": "conversation_list",
            "item_type": "list_pane",
            "bbox": {"x": 80, "y": 96, "w": 260, "h": 620},
            "review_only": True,
        },
        {
            "item_id": "message_thread",
            "label": "Chat thread messages",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 350, "y": 96, "w": 560, "h": 520},
            "review_only": True,
        },
        {
            "item_id": "composer_input",
            "label": "Message input area Send",
            "role": "composer",
            "item_type": "input_area",
            "bbox": {"x": 350, "y": 630, "w": 560, "h": 84},
            "review_only": True,
        },
        {
            "item_id": "bottom_bar",
            "label": "Bottom input shell",
            "role": "layout",
            "item_type": "section",
            "bbox": {"x": 80, "y": 540, "w": 830, "h": 176},
            "metadata": {"surface_zone": "bottom_bar"},
            "review_only": True,
        },
        {
            "item_id": "bottom_tool_row",
            "label": "Attach emoji voice send tools",
            "role": "message_thread",
            "item_type": "detail_pane",
            "bbox": {"x": 360, "y": 604, "w": 520, "h": 22},
            "review_only": True,
        },
        {
            "item_id": "right_detail",
            "label": "Members",
            "role": "right_sidebar",
            "item_type": "side_panel",
            "bbox": {"x": 930, "y": 96, "w": 250, "h": 620},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["left_nav"]},
            "top_bar": {"item_ids": ["top_bar"]},
            "primary_area": {
                "item_ids": [
                    "conversation_list",
                    "message_thread",
                    "composer_input",
                    "bottom_bar",
                    "bottom_tool_row",
                ]
            },
            "right_sidebar": {"item_ids": ["right_detail"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 780}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    bottom_composer = next(
        item for item in report["stage1_5_partition"]["subregions"] if item["role"] == "bottom_composer"
    )
    message_thread = next(
        item for item in report["stage1_5_partition"]["subregions"] if item["role"] == "message_thread"
    )
    conversation_list = next(
        item for item in report["stage1_5_partition"]["subregions"] if item["role"] == "conversation_list"
    )
    assert bottom_composer["bbox"]["y"] == 604
    assert bottom_composer["bbox"]["h"] == 110
    assert message_thread["bbox"]["y"] + message_thread["bbox"]["h"] == bottom_composer["bbox"]["y"]
    assert conversation_list["bbox"]["y"] + conversation_list["bbox"]["h"] == bottom_composer["bbox"]["y"]
    vertical_review = bottom_composer["stage1_5_vertical_review"]
    assert vertical_review["status"] == "composer_bbox_constrained_to_evidence_vertical_span"
    assert vertical_review["previous_bbox"]["y"] == 540
    assert vertical_review["evidence_bbox"]["y"] == 604
    assert "bottom_bar" in vertical_review["excluded_shell_item_ids"]


def test_stage1_5_overlay_styles_distinguish_adjacent_chat_panes():
    styles = {
        role: _stage1_5_overlay_style(role, index=index)
        for index, role in enumerate(("conversation_list", "message_thread", "bottom_composer"), start=1)
    }

    colors = {role: style["color"] for role, style in styles.items()}

    assert len(set(colors.values())) == 3
    assert colors["conversation_list"] != colors["bottom_composer"]
    assert all(style["width"] >= 4 for style in styles.values())


def test_stage1_5_partition_does_not_split_stage1_ready_media_surface(tmp_path):
    image_path = tmp_path / "apple_music_like.png"
    from PIL import Image

    Image.new("RGB", (1200, 760), "white").save(image_path)
    inventory = [
        {
            "item_id": "left_nav",
            "label": "Home Browse Radio",
            "role": "left_nav",
            "item_type": "nav",
            "bbox": {"x": 0, "y": 70, "w": 96, "h": 690},
            "review_only": True,
        },
        {
            "item_id": "top_bar",
            "label": "player controls",
            "role": "toolbar",
            "item_type": "layout",
            "bbox": {"x": 96, "y": 0, "w": 1104, "h": 70},
            "review_only": True,
        },
        {
            "item_id": "media_grid",
            "label": "Recently played music cards",
            "role": "media_grid",
            "item_type": "section",
            "bbox": {"x": 120, "y": 120, "w": 980, "h": 520},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {
            "left_nav": {"item_ids": ["left_nav"]},
            "top_bar": {"item_ids": ["top_bar"]},
            "primary_area": {"item_ids": ["media_grid"]},
        },
        "nodes": {item["item_id"]: item for item in inventory},
    }

    report = build_stage1_region_localization_report(
        bundle={"image_path": str(image_path), "screen_size": {"width": 1200, "height": 760}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    assert report["stage1_granularity_review"]["status"] == "stage1_geometry_ready"
    assert report["stage1_5_partition"]["status"] == "not_needed_stage1_geometry_ready"
    assert report["stage1_5_partition"]["subregion_count"] == 0
    assert report["stage1_5_overlay_path"] == ""


def test_two_stage_expands_topbar_icon_fragments_to_review_hit_areas(tmp_path):
    image_path = tmp_path / "topbar_controls.png"
    from PIL import Image

    Image.new("RGB", (640, 240), "white").save(image_path)
    inventory = [
        {
            "item_id": "prev_icon",
            "label": "previous",
            "role": "icon_button",
            "item_type": "button",
            "bbox": {"x": 122, "y": 18, "w": 12, "h": 14},
            "review_only": True,
        },
        {
            "item_id": "play_icon",
            "label": "play",
            "role": "icon_button",
            "item_type": "button",
            "bbox": {"x": 164, "y": 17, "w": 14, "h": 16},
            "review_only": True,
        },
        {
            "item_id": "next_icon",
            "label": "next",
            "role": "icon_button",
            "item_type": "button",
            "bbox": {"x": 206, "y": 18, "w": 12, "h": 14},
            "review_only": True,
        },
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"top_bar": {"item_ids": [item["item_id"] for item in inventory]}},
        "nodes": {item["item_id"]: item for item in inventory},
    }

    result = build_two_stage_screen_understanding(
        bundle={"image_path": str(image_path), "screen_size": {"width": 640, "height": 240}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    topbar = next(
        item for item in result["stage2_numbering"]["regions"] if item["region_id"] == "structure_region_top_bar"
    )
    assert topbar["visual_small_control_refinement"]["topbar_item_grouping"]["applied"] is True
    assert topbar["visual_small_control_refinement"]["topbar_item_grouping"]["bbox_policy"] == (
        "topbar_controls_must_not_remain_icon_or_ocr_fragments"
    )
    controls = topbar["numbered_items"]
    assert len(controls) == 3
    assert all(item["display_only"] is True for item in controls)
    assert all(item["execute_binding_enabled"] is False for item in controls)
    assert all(item["bbox"]["w"] >= 48 for item in controls)
    assert all(item["bbox"]["h"] >= 36 for item in controls)
    assert all(item["bbox_policy"] == "topbar_control_hit_area_from_visual_or_text_fragments" for item in controls)
    assert controls[0]["bbox"]["x"] < inventory[0]["bbox"]["x"]


def test_two_stage_keeps_multirow_topbar_controls_in_separate_full_height_rows() -> None:
    region = {
        "region_no": 1,
        "region_id": "structure_region_page_header",
        "label": "Top/header area",
        "bbox": {"x": 0, "y": 0, "w": 900, "h": 220},
        "item_ids": [f"row_{row}_control_{column}" for row in range(1, 4) for column in range(1, 4)],
    }
    items_by_id = {
        item_id: {
            "item_id": item_id,
            "label": item_id,
            "role": "button",
            "item_type": "button",
            "bbox": {"x": 120 + (column - 1) * 140, "y": y, "w": 52, "h": 24},
            "review_only": True,
        }
        for row, y in ((1, 12), (2, 88), (3, 166))
        for column in range(1, 4)
        for item_id in [f"row_{row}_control_{column}"]
    }

    result = two_stage._stage2_numbering([region], items_by_id=items_by_id)

    topbar = result["regions"][0]
    assert all(item["bbox"]["h"] >= 30 for item in topbar["numbered_items"])
    assert all(item["bbox"]["y"] + item["bbox"]["h"] <= 220 for item in topbar["numbered_items"])
    strips = [group for group in topbar["subregion_groups"] if group["role"] == "topbar_control_strip"]
    assert len(strips) == 3
    assert [len(group["member_item_ids"]) for group in strips] == [3, 3, 3]
    assert [group["bbox"]["y"] for group in strips] == sorted(group["bbox"]["y"] for group in strips)


def test_stage2_clips_numbered_items_to_parent_region_bbox():
    result = two_stage._stage2_numbering(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 0, "y": 0, "w": 100, "h": 60},
                "item_ids": ["overflowing_control"],
            }
        ],
        items_by_id={
            "overflowing_control": {
                "item_id": "overflowing_control",
                "label": "Overflowing control",
                "role": "icon_button",
                "item_type": "button",
                "bbox": {"x": 70, "y": 12, "w": 50, "h": 28},
                "review_only": True,
            }
        },
    )

    topbar = result["regions"][0]
    control = topbar["numbered_items"][0]
    assert control["bbox"] == {"x": 70, "y": 12, "w": 30, "h": 28}
    assert control["bbox_boundary_clip"]["reason"] == "numbered_item_must_not_extend_outside_parent_region"
    assert control["parent_region_id"] == "structure_region_main_content"
    assert control["parent_region_bbox"] == {"x": 0, "y": 0, "w": 100, "h": 60}
    assert control["parent_boundary_relation"]["relation"] == "child_of_structure_region"
    assert (
        control["parent_boundary_relation"]["child_bbox_policy"]
        == "must_be_inside_parent_region_after_boundary_enforcement"
    )
    assert control["parent_boundary_relation"]["execute_binding_enabled"] is False
    assert topbar["region_content_boundary"]["clipped_numbered_item_count"] == 1
    assert topbar["region_content_boundary"]["parent_region_id"] == "structure_region_main_content"
    assert topbar["region_content_boundary"]["annotated_numbered_item_count"] == 1


def test_stage2_clips_subregion_groups_to_parent_region_bbox():
    _items, groups, boundary = two_stage._enforce_region_content_boundary(
        [],
        [
            {
                "group_id": "media_row",
                "label": "Media row",
                "bbox": {"x": -20, "y": 8, "w": 150, "h": 44},
                "display_only": True,
            }
        ],
        region_bbox={"x": 0, "y": 0, "w": 100, "h": 60},
        region_id="structure_region_primary_area",
        region_label="Primary area",
    )

    assert groups[0]["bbox"] == {"x": 0, "y": 8, "w": 100, "h": 44}
    assert groups[0]["bbox_boundary_clip"]["reason"] == "subregion_group_must_not_extend_outside_parent_region"
    assert groups[0]["parent_region_id"] == "structure_region_primary_area"
    assert groups[0]["parent_region_label"] == "Primary area"
    assert groups[0]["parent_boundary_relation"]["relation"] == "child_group_of_structure_region"
    assert (
        groups[0]["parent_boundary_relation"]["sibling_overlap_policy"]
        == "non_parent_overlap_requires_boundary_review"
    )
    assert boundary["clipped_subregion_group_count"] == 1
    assert boundary["annotated_subregion_group_count"] == 1


def test_stage2_rejects_child_content_without_parent_overlap():
    items, groups, boundary = two_stage._enforce_region_content_boundary(
        [
            {
                "number": "1.1",
                "item_id": "sibling_button",
                "label": "Sibling button",
                "role": "button",
                "bbox": {"x": 160, "y": 20, "w": 40, "h": 24},
                "display_only": True,
            }
        ],
        [
            {
                "group_id": "sibling_group",
                "label": "Sibling group",
                "bbox": {"x": 150, "y": 8, "w": 80, "h": 44},
                "display_only": True,
            }
        ],
        region_bbox={"x": 0, "y": 0, "w": 100, "h": 60},
        region_id="structure_region_left_nav",
        region_label="Left nav",
    )

    assert items[0]["bbox"] == {}
    assert items[0]["raw_bbox_before_boundary"] == {"x": 160, "y": 20, "w": 40, "h": 24}
    assert items[0]["bbox_boundary_reject"]["reason"] == "numbered_item_outside_parent_region"
    assert items[0]["parent_boundary_relation"]["child_scope"] == "outside_parent_rejected"
    assert items[0]["parent_boundary_relation"]["inside_parent_after_enforcement"] is False
    assert items[0]["review_required"] is True
    assert items[0]["candidate_only"] is True
    assert groups[0]["bbox"] == {}
    assert groups[0]["bbox_boundary_reject"]["reason"] == "subregion_group_outside_parent_region"
    assert boundary["rejected_numbered_item_count"] == 1
    assert boundary["rejected_subregion_group_count"] == 1
    assert boundary["child_scope_policy"] == (
        "children_may_only_overlap_when_the_parent_region_contains_them_after_enforcement"
    )


def test_primary_content_orphan_items_get_internal_review_region():
    groups = two_stage._ensure_primary_items_have_subregion_parent(
        region={
            "region_id": "structure_region_primary_area",
            "bbox": {"x": 0, "y": 0, "w": 420, "h": 320},
        },
        numbered_items=[
            {
                "number": "1.1",
                "item_id": "contained_title",
                "label": "Contained title",
                "role": "text",
                "bbox": {"x": 40, "y": 32, "w": 140, "h": 24},
            },
            {
                "number": "1.2",
                "item_id": "orphan_button",
                "label": "Floating button",
                "role": "button",
                "bbox": {"x": 260, "y": 210, "w": 96, "h": 32},
            },
            {
                "number": "1.3",
                "item_id": "orphan_text_1",
                "label": "Floating text 1",
                "role": "text",
                "bbox": {"x": 260, "y": 248, "w": 120, "h": 22},
            },
            {
                "number": "1.4",
                "item_id": "orphan_text_2",
                "label": "Floating text 2",
                "role": "text",
                "bbox": {"x": 260, "y": 276, "w": 120, "h": 22},
            },
            {
                "number": "1.5",
                "item_id": "orphan_text_3",
                "label": "Floating text 3",
                "role": "text",
                "bbox": {"x": 260, "y": 304, "w": 120, "h": 22},
            },
        ],
        groups=[
            {
                "group_id": "section_parent_1",
                "label": "Section",
                "role": "section_parent",
                "bbox": {"x": 20, "y": 20, "w": 200, "h": 80},
                "member_item_ids": [],
                "member_numbers": [],
                "display_only": True,
            }
        ],
    )

    section = next(group for group in groups if group["group_id"] == "section_parent_1")
    assert "contained_title" in section["member_item_ids"]
    assert section["membership_repairs"][0]["reason"] == "item_bbox_inside_group_bbox_but_missing_member_link"
    orphan_group = next(group for group in groups if group["role"] == "ungrouped_review_region")
    assert orphan_group["member_item_ids"] == ["orphan_button", "orphan_text_1", "orphan_text_2", "orphan_text_3"]
    assert orphan_group["review_only"] is True
    assert orphan_group["candidate_only"] is True
    assert orphan_group["execute_binding_enabled"] is False
    assert orphan_group["bbox"]["x"] <= 260
    assert orphan_group["bbox"]["x"] + orphan_group["bbox"]["w"] >= 356


def test_fusion_boxes_enforce_parent_region_boundary_at_display_layer():
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_top_bar",
                "label": "Top bar",
                "bbox": {"x": 0, "y": 0, "w": 120, "h": 40},
            }
        ],
        [
            {
                "region_id": "structure_region_top_bar",
                "subregion_groups": [
                    {
                        "group_id": "toolbar_group_1",
                        "label": "Toolbar",
                        "role": "toolbar_group",
                        "bbox": {"x": 90, "y": 4, "w": 60, "h": 36},
                        "parent_region_id": "structure_region_top_bar",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 120, "h": 40},
                    }
                ],
                "numbered_items": [
                    {
                        "number": "1.1",
                        "label": "Overflow button",
                        "role": "control",
                        "bbox": {"x": 100, "y": 8, "w": 48, "h": 24},
                        "parent_region_id": "structure_region_top_bar",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 120, "h": 40},
                    }
                ],
            }
        ],
    )

    group = next(item for item in result["fused_review_boxes"] if item["box_type"] == "subregion_group")
    control = next(item for item in result["fused_review_boxes"] if item["box_type"] == "numbered_item")
    assert group["bbox"] == {"x": 90, "y": 4, "w": 30, "h": 36}
    assert control["bbox"] == {"x": 100, "y": 8, "w": 20, "h": 24}
    assert group["parent_region_id"] == "structure_region_top_bar"
    assert control["parent_region_id"] == "structure_region_top_bar"
    assert group["fusion_boundary_clip"]["reason"] == "fused_child_box_must_not_extend_outside_parent_region"
    assert control["fusion_boundary_clip"]["reason"] == "fused_child_box_must_not_extend_outside_parent_region"
    assert group["review_required"] is True
    assert control["review_required"] is True
    assert result["region_content_boundary_summary"]["clipped_fused_child_count"] == 2
    assert result["region_content_boundary_summary"]["missing_parent_child_count"] == 0
    assert result["region_content_boundary_summary"]["outside_parent_after_clip_count"] == 0
    assert result["region_content_boundary_summary"]["boundary_contract_status"] == "needs_human_review"
    assert result["region_content_boundary_summary"]["pathgraph_promotion_allowed"] is False
    assert result["region_content_boundary_summary"]["promotion_blockers"] == ["clipped_fused_child_count"]


def test_fusion_boxes_do_not_render_child_without_parent_overlap():
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_left_nav",
                "label": "Left nav",
                "bbox": {"x": 0, "y": 0, "w": 80, "h": 300},
            }
        ],
        [
            {
                "region_id": "structure_region_left_nav",
                "subregion_groups": [],
                "numbered_items": [
                    {
                        "number": "1.1",
                        "label": "Wrong column item",
                        "role": "button",
                        "bbox": {"x": 180, "y": 20, "w": 60, "h": 32},
                        "parent_region_id": "structure_region_left_nav",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 80, "h": 300},
                    }
                ],
            }
        ],
    )

    child = next(item for item in result["fused_review_boxes"] if item["box_type"] == "numbered_item")
    assert child["bbox"] == {}
    assert child["fusion_boundary_review"]["reason"] == "fused_child_box_outside_parent_region"
    assert two_stage._parent_bounded_display_bbox(child) is None
    assert result["region_content_boundary_summary"]["outside_parent_after_clip_count"] == 1
    assert result["region_content_boundary_summary"]["pathgraph_promotion_allowed"] is False
    assert result["region_content_boundary_summary"]["promotion_blockers"] == ["outside_parent_after_clip_count"]


def test_fusion_boxes_suppress_non_parent_sibling_group_overlap():
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_primary_area",
                "label": "Primary area",
                "bbox": {"x": 0, "y": 0, "w": 520, "h": 420},
            }
        ],
        [
            {
                "region_id": "structure_region_primary_area",
                "subregion_groups": [
                    {
                        "group_id": "latest_news_section",
                        "label": "Latest News",
                        "role": "section_parent",
                        "bbox": {"x": 80, "y": 120, "w": 250, "h": 190},
                        "member_item_ids": ["news_title"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 520, "h": 420},
                    },
                    {
                        "group_id": "wide_media_row",
                        "label": "Wide media row",
                        "role": "media_card_group",
                        "bbox": {"x": 240, "y": 190, "w": 250, "h": 190},
                        "member_item_ids": ["media_card"],
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 520, "h": 420},
                    },
                ],
                "numbered_items": [],
            }
        ],
    )

    media_row = next(item for item in result["fused_review_boxes"] if item["number"] == "wide_media_row")
    assert media_row["render_in_main_overlay"] is False
    assert media_row["candidate_only"] is True
    assert media_row["sibling_overlap_review"]["reason"] == "non_parent_sibling_group_overlap"
    assert result["region_content_boundary_summary"]["sibling_non_parent_overlap_count"] == 1
    assert "sibling_non_parent_overlap_count" in result["region_content_boundary_summary"]["promotion_blockers"]


def test_fusion_boxes_missing_parent_region_blocks_promotion():
    result = two_stage._fusion_boxes(
        [
            {
                "region_no": 1,
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 0, "y": 0, "w": 200, "h": 120},
            }
        ],
        [
            {
                "region_id": "structure_region_main_content",
                "subregion_groups": [],
                "numbered_items": [
                    {
                        "number": "1.1",
                        "label": "Orphan child",
                        "role": "text",
                        "bbox": {"x": 20, "y": 20, "w": 80, "h": 24},
                    }
                ],
            }
        ],
    )

    child = next(item for item in result["fused_review_boxes"] if item["box_type"] == "numbered_item")
    assert child["review_required"] is True
    assert child["candidate_only"] is True
    assert child["fusion_boundary_review"]["reason"] == "fused_child_box_missing_parent_region"
    assert result["region_content_boundary_summary"]["missing_parent_child_count"] == 1
    assert result["region_content_boundary_summary"]["boundary_contract_status"] == "needs_human_review"
    assert result["region_content_boundary_summary"]["pathgraph_promotion_allowed"] is False
    assert result["region_content_boundary_summary"]["promotion_blockers"] == ["missing_parent_child_count"]


def test_overlay_label_layout_keeps_long_labels_inside_bbox_width():
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (180, 80), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    bbox = {"x": 40, "y": 24, "w": 56, "h": 24}

    layout = two_stage._overlay_label_layout(
        draw,
        bbox,
        "3.17 timestamp -> msg_2",
        font=font,
        max_width=bbox["w"],
    )

    assert layout is not None
    assert layout["rect"][0] >= bbox["x"]
    assert layout["rect"][2] <= bbox["x"] + bbox["w"]
    assert "timestamp" not in layout["text"]


def test_overlay_label_layout_keeps_label_rect_inside_bbox():
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (240, 160), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    bbox = {"x": 60, "y": 80, "w": 72, "h": 28}

    layout = two_stage._overlay_label_layout(
        draw,
        bbox,
        "3.84 button",
        font=font,
        max_width=bbox["w"],
    )

    assert layout is not None
    assert layout["rect"][0] >= bbox["x"]
    assert layout["rect"][1] >= bbox["y"]
    assert layout["rect"][2] <= bbox["x"] + bbox["w"]
    assert layout["rect"][3] <= bbox["y"] + bbox["h"]


def test_overlay_label_layout_keeps_labels_inside_canvas_right_edge():
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (100, 60), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    bbox = {"x": 84, "y": 18, "w": 12, "h": 20}

    layout = two_stage._overlay_label_layout(
        draw,
        bbox,
        "2.13 control",
        font=font,
        max_width=48,
    )

    assert layout is not None
    assert layout["rect"][2] <= image.width


def test_learning_recognition_pipeline_exposes_two_stage_overlay_in_page_details(tmp_path):
    image_path = tmp_path / "learning_screen.png"
    from PIL import Image

    Image.new("RGB", (640, 420), "white").save(image_path)
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "image_path": str(image_path),
        "screen_size": {"width": 640, "height": 420},
        "sources": {
            "vision": {
                "regions": [
                    {
                        "candidate_id": "left_nav_home",
                        "label": "Home icon",
                        "role": "nav_rail_icon_review_only",
                        "bbox": {"x": 20, "y": 120, "w": 24, "h": 24},
                    },
                    {
                        "candidate_id": "music_card",
                        "label": "Energy album card",
                        "role": "news_card",
                        "bbox": {"x": 120, "y": 170, "w": 240, "h": 160},
                        "metadata": {
                            "text_lines": [
                                {"label": "能量充电", "bbox": {"x": 160, "y": 250, "w": 120, "h": 28}},
                            ]
                        },
                    },
                ]
            }
        },
    }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="apple_music_home",
        summary="Apple Music home screen.",
        grounding_adapter=None,
    )

    page_details = result["learning_draft"]["page_details"]
    two_stage = page_details["two_stage_understanding"]
    assert two_stage["stage1_structure"]["region_count"] >= 1
    assert two_stage["stage1_region_localization"]["localized_region_count"] >= 1
    assert two_stage["stage2_numbering"]["numbered_item_count"] >= 2
    fusion_status = page_details["pipeline_audit"]["precise_understanding_fusion_status"]
    assert fusion_status["contract_version"] == "learn_precise_understanding_fusion_status_report_v1"
    assert fusion_status["compiled_overlay_path"]
    assert Path(fusion_status["compiled_overlay_path"]).exists()
    assert fusion_status["summary"]["structure_region_count"] == two_stage["stage1_structure"]["region_count"]
    assert fusion_status["summary"]["stage1_localized_region_count"] == two_stage["stage1_region_localization"]["localized_region_count"]
    assert fusion_status["summary"]["numbered_item_count"] == two_stage["stage2_numbering"]["numbered_item_count"]


def test_learning_recognition_pipeline_outputs_reviewable_draft(tmp_path):
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "screen_size": {"width": 1280, "height": 720},
        "sources": {
            "ocr": {
                "texts": [
                    {
                        "text": "Latest News",
                        "bbox": {"x": 80, "y": 540, "w": 260, "h": 48},
                    }
                ]
            },
            "uia": {
                "controls": [
                    {
                        "name": "Search",
                        "control_type": "Button",
                        "bbox": {"x": 980, "y": 140, "w": 92, "h": 36},
                        "patterns": ["Invoke"],
                    }
                ]
            },
        },
    }

    def fake_grounding_adapter(*, item, roi_crop):
        assert item["label"] == "Search"
        return {
            "screen_point": {"x": 1024, "y": 158},
            "screen_bbox": item["bbox"],
            "evidence": {
                "coordinate_transform_replay": True,
                "screenshot_freshness": True,
                "uia_or_dom_or_parser_overlap": True,
            },
            "debug": {"roi_contract": roi_crop["contract_version"]},
        }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="python_homepage",
        summary="Python homepage search and content regions.",
        grounding_adapter=fake_grounding_adapter,
    )

    assert result["contract_version"] == "learn_recognition_pipeline_result_v1"
    assert result["status"] == "draft_ready"
    assert result["layout_graph"]["contract_version"] == "learn_layout_graph_v1"
    assert result["layout_graph"]["node_count"] == 2
    assert result["layout_graph"]["zones"]["page_header"]["item_ids"] == ["uia_control_1"]
    assert result["layout_graph"]["zones"]["main_content"]["item_ids"] == ["ocr_text_1"]
    assert result["locator_task_cards"]["contract_version"] == "learn_locator_task_cards_v1"
    assert result["locator_task_cards"]["display_only"] is True
    assert result["locator_task_cards"]["execute_binding_enabled"] is False
    search_card = next(
        item for item in result["locator_task_cards"]["cards"] if item["source_item_id"] == "uia_control_1"
    )
    assert search_card["target_visible_text"] == "Search"
    assert search_card["target_role"] == "button"
    assert search_card["evidence_level"] == "uia_control"
    assert search_card["uia_control_type"] == "Button"
    assert search_card["rough_bbox_policy"] == "hint_only_can_be_replaced"
    assert search_card["interaction_target"].startswith("click the visible button body")
    assert "boundary_definition" in search_card
    assert "clickable_area_hint" in search_card
    assert "final submit" in search_card["must_not_click"]
    assert search_card["expected_precise_output"] == "tight visible target bbox and safe interior point in full screenshot coordinates"
    assert result["classification"]["summary"]["accepted_for_grounding_count"] == 1
    assert result["classification"]["summary"]["rejected_non_actionable_count"] == 1
    assert result["learning_draft"]["contract_version"] == "learning_template_draft_v1"
    assert result["learning_draft"]["execute_binding_enabled"] is False
    assert result["learning_draft"]["artifact_is_authorization"] is False
    assert result["learning_draft"]["final_submit_forbidden"] is True
    assert result["learning_draft"]["blockers"][0]["blocker_id"] == "final_submit_guard"
    assert result["learning_draft"]["verification_rules"][0]["rule_id"] == "target_region_still_visible"
    assert result["learning_draft"]["page_details"]["contract_version"] == "learning_draft_page_details_v1"
    assert result["learning_draft"]["page_details"]["inventory_summary"]["screen_inventory_count"] == 2
    assert result["learning_draft"]["page_details"]["layout_graph"]["contract_version"] == "learn_layout_graph_v1"
    assert result["learning_draft"]["page_details"]["layout_graph"]["zone_count"] >= 2
    assert result["learning_draft"]["page_details"]["locator_task_cards"]["contract_version"] == "learn_locator_task_cards_v1"
    assert result["learning_draft"]["page_details"]["locator_task_cards"]["cards"][0]["source_item_id"]
    audit = result["learning_draft"]["page_details"]["pipeline_audit"]
    assert audit["contract_version"] == "learning_draft_pipeline_audit_v1"
    assert audit["display_only"] is True
    assert audit["execute_binding_enabled"] is False
    assert audit["layout_cleanup"]["input_count"] == 2
    assert audit["layout_cleanup"]["output_count"] == 2
    assert audit["layout_cleanup"]["suppression_reason_counts"] == {}
    assert audit["grounding_eligibility_gate"]["attempted"] == 2
    assert audit["grounding_eligibility_gate"]["eligible"] == 1
    assert audit["grounding_eligibility_gate"]["blocked"] == 1
    assert audit["grounding_eligibility_gate"]["not_accuracy"] is True
    assert audit["roi_grounding"]["validation_count"] == 1
    assert audit["roi_grounding"]["valid_candidate_count"] == 1
    assert [item["label"] for item in result["learning_draft"]["page_details"]["review_only_regions"]] == ["Latest News"]
    assert [item["label"] for item in result["learning_draft"]["page_details"]["grounding_candidates"]] == ["Search"]
    assert "click_target" in result["learning_draft"]["operation_skills"]
    assert "observe_screen" in result["learning_draft"]["operation_skills"]
    assert result["learning_draft"]["gate_contracts"][0]["contract_id"] == "pre_click_decision_v1"
    assert result["learning_draft"]["action_templates"][0]["target_region_id"] == "region_1"
    assert result["learning_draft"]["action_templates"][0]["requires_gate"] is True
    assert result["learning_draft"]["action_templates"][0]["execute_binding_enabled"] is False

    draft_path = tmp_path / "artifacts" / "learning-recognition" / "draft.json"
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text(json.dumps(result["learning_draft"], ensure_ascii=False), encoding="utf-8")

    review = load_learning_draft_review(draft_path, project_root=tmp_path)

    assert review["draft_only"] is True
    assert review["execute_binding_enabled"] is False
    assert review["final_submit_forbidden"] is True
    assert review["draft"]["state_guess"] == "python_homepage"
    assert [item["label"] for item in review["draft"]["regions"]] == ["Search", "Latest News"]
    assert review["draft"]["regions"][1]["candidate_only"] is True
    assert review["draft"]["regions"][1]["execute_binding_enabled"] is False
    assert review["draft"]["action_templates"][0]["click_point"] == {"x": 1024, "y": 158}
    assert review["draft"]["blockers"][0]["blocker_id"] == "final_submit_guard"
    assert review["draft"]["verification_rules"][0]["rule_id"] == "target_region_still_visible"
    assert review["draft"]["gate_contracts"][0]["contract_id"] == "pre_click_decision_v1"
    assert review["draft"]["page_details"]["review_only_regions"][0]["label"] == "Latest News"
    assert review["draft"]["page_details"]["pipeline_audit"]["layout_cleanup"]["input_count"] == 2


def test_learning_recognition_pipeline_keeps_observe_only_regions_visible_without_actions():
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "screen_size": {"width": 1280, "height": 720},
        "sources": {
            "vision": {
                "regions": [
                    {
                        "candidate_id": "apple_music_album_card_1",
                        "label": "Apple Music album card",
                        "role": "content_card",
                        "bbox": {"x": 120, "y": 260, "w": 240, "h": 180},
                    }
                ]
            }
        },
    }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="apple_music_home",
        summary="Apple Music home screen.",
        grounding_adapter=None,
    )

    draft = result["learning_draft"]
    assert result["status"] == "needs_human_review"
    assert result["raw_screen_inventory"]
    assert [item["label"] for item in draft["page_details"]["review_only_regions"]] == ["Apple Music album card"]
    assert [item["label"] for item in draft["regions"]] == ["Apple Music album card"]
    assert draft["regions"][0]["candidate_only"] is True
    assert draft["regions"][0]["requires_human_review"] is True
    assert draft["regions"][0]["execute_binding_enabled"] is False
    assert draft["regions"][0]["artifact_is_authorization"] is False
    assert draft["regions"][0]["grounding_status"] == "review_only"
    assert draft["action_templates"] == []


def test_learning_recognition_pipeline_restores_local_grounding_into_draft():
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "screen_size": {"width": 1200, "height": 800},
        "sources": {
            "omniparser": {
                "parsed_content_list": [
                    {
                        "type": "icon",
                        "content": "Search",
                        "bbox": [500, 300, 600, 340],
                        "interactivity": True,
                    }
                ]
            }
        },
    }

    def fake_grounding_adapter(*, item, roi_crop):
        assert roi_crop["grounding_request"]["contract_version"] == "learn_grounding_request_v1"
        return {
            "coordinate_space": "uground_0_999",
            "raw_output": "(500, 500)",
            "screen_bbox": item["bbox"],
            "evidence": {
                "screenshot_freshness": True,
                "uia_or_dom_or_parser_overlap": True,
            },
        }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="python_homepage",
        summary="Search is available.",
        grounding_adapter=fake_grounding_adapter,
    )

    assert result["status"] == "draft_ready"
    assert result["grounding_validations"][0]["checks"]["coordinate_transform_replay"] is True
    assert result["grounding_validations"][0]["screen_point"] == {"x": 550, "y": 320}
    assert result["learning_draft"]["action_templates"][0]["click_point"] == {"x": 550, "y": 320}
    assert result["learning_draft"]["action_templates"][0]["low_level_action_type"] == "click"
    assert result["learning_draft"]["verification_rules"]


def test_learning_recognition_pipeline_marks_form_fields_as_draft_fill_actions():
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "screen_size": {"width": 1000, "height": 700},
        "sources": {
            "ocr": {
                "texts": [
                    {
                        "text": "Search the docs before downloading.",
                        "bbox": {"x": 80, "y": 220, "w": 360, "h": 32},
                    }
                ]
            },
            "uia": {
                "controls": [
                    {
                        "name": "Email",
                        "control_type": "Edit",
                        "bbox": {"x": 100, "y": 220, "w": 360, "h": 40},
                        "patterns": ["Value"],
                    }
                ]
            }
        },
    }

    def fake_grounding_adapter(*, item, roi_crop):
        return {
            "screen_point": {"x": 280, "y": 240},
            "screen_bbox": item["bbox"],
            "evidence": {
                "coordinate_transform_replay": True,
                "screenshot_freshness": True,
                "uia_or_dom_or_parser_overlap": True,
            },
        }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="simple_form",
        summary="A form with one email input.",
        grounding_adapter=fake_grounding_adapter,
    )

    action = result["learning_draft"]["action_templates"][0]
    assert action["semantic_action"] == "fill_field"
    assert action["low_level_action_type"] == "input"
    assert "type_text" in result["learning_draft"]["operation_skills"]
    assert action["requires_gate"] is True
    assert action["execute_binding_enabled"] is False
    assert result["learning_draft"]["safety"]["execute_binding_enabled"] is False


def test_learning_recognition_pipeline_draft_can_generate_non_executable_pathgraph_candidate(tmp_path):
    observe_bundle = {
        "contract_version": "learn_observe_bundle_v1",
        "screen_size": {"width": 1000, "height": 700},
        "sources": {
            "ocr": {
                "texts": [
                    {
                        "text": "Search the docs before downloading.",
                        "bbox": {"x": 80, "y": 220, "w": 360, "h": 32},
                    }
                ]
            },
            "uia": {
                "controls": [
                    {
                        "name": "Search",
                        "control_type": "Button",
                        "bbox": {"x": 500, "y": 120, "w": 96, "h": 36},
                        "patterns": ["Invoke"],
                    }
                ]
            }
        },
    }

    def fake_grounding_adapter(*, item, roi_crop):
        return {
            "screen_point": {"x": 548, "y": 138},
            "screen_bbox": item["bbox"],
            "evidence": {
                "coordinate_transform_replay": True,
                "screenshot_freshness": True,
                "uia_or_dom_or_parser_overlap": True,
            },
        }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="search_page",
        summary="A search page with one validated action.",
        grounding_adapter=fake_grounding_adapter,
    )
    draft_path = tmp_path / "artifacts" / "learning-recognition" / "draft.json"
    draft_path.parent.mkdir(parents=True)
    draft_path.write_text(json.dumps(result["learning_draft"], ensure_ascii=False), encoding="utf-8")

    candidate = build_pathgraph_candidate_from_review(draft_path, {}, project_root=tmp_path)

    assert candidate["validation_status"] == "passed_candidate"
    assert candidate["artifact_is_authorization"] is False
    assert candidate["execute_binding_enabled"] is False
    assert candidate["final_submit_forbidden"] is True
    assert candidate["summary"]["blocker_count"] >= 1
    assert candidate["summary"]["verification_rule_count"] >= 1
    wrapper = json.loads((tmp_path / candidate["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    assert wrapper["validation_status"] == "passed_candidate"
    assert wrapper["execute_binding_enabled"] is False
    graph = json.loads((tmp_path / candidate["runtime_path_graph_candidate_path"]).read_text(encoding="utf-8"))
    interface_map = json.loads((tmp_path / candidate["interface_map_candidate_path"]).read_text(encoding="utf-8"))
    for artifact in (graph, interface_map):
        assert artifact["page_details"]["contract_version"] == "learning_draft_page_details_v1"
        assert artifact["page_details"]["display_only"] is True
        assert artifact["page_details"]["candidate_only"] is True
        assert artifact["page_details"]["execute_binding_enabled"] is False
        assert artifact["page_details"]["inventory_summary"]["screen_inventory_count"] == 2
        assert artifact["page_details"]["review_only_regions"][0]["label"] == "Search the docs before downloading."
        assert artifact["page_details"]["grounding_candidates"][0]["label"] == "Search"
        assert artifact["page_details"]["pipeline_audit"]["contract_version"] == "learning_draft_pipeline_audit_v1"
        assert artifact["page_details"]["pipeline_audit"]["grounding_eligibility_gate"]["eligible"] == 1


def test_learning_recognition_pipeline_without_grounding_adapter_needs_review():
    observe_bundle = {
        "screen_size": {"width": 800, "height": 600},
        "sources": {
            "uia": {
                "controls": [
                    {
                        "name": "Search",
                        "control_type": "Button",
                        "bbox": {"x": 100, "y": 100, "w": 80, "h": 32},
                        "patterns": ["Invoke"],
                    }
                ]
            }
        },
    }

    result = build_learning_recognition_trial(
        observe_bundle=observe_bundle,
        state_guess="search_page",
        summary="Search page.",
    )

    assert result["status"] == "needs_grounding_adapter"
    assert result["learning_draft"]["regions"] == []
    assert result["grounding_validations"] == []
    assert result["learning_draft"]["blockers"][0]["blocker_id"] == "final_submit_guard"
    assert result["learning_draft"]["verification_rules"][0]["rule_id"] == "target_region_still_visible"
    assert result["safety"]["execute_binding_enabled"] is False


def test_two_stage_groups_repeated_text_columns_into_complete_parent_modules() -> None:
    region = {
        "region_id": "structure_region_primary_area",
        "bbox": {"x": 0, "y": 200, "w": 1200, "h": 700},
    }
    items = []
    for column, x in enumerate((100, 350, 600, 850), start=1):
        for line, (y, width, label) in enumerate(
            (
                (300, 100, f"Heading {column}"),
                (340, 180, f"Body {column} first line"),
                (370, 190, f"Body {column} second line"),
                (410, 150, f"Action {column}"),
            ),
            start=1,
        ):
            items.append(
                {
                    "number": f"1.{column}.{line}",
                    "item_id": f"column_{column}_line_{line}",
                    "label": label,
                    "role": "heading" if line == 1 else "text",
                    "bbox": {"x": x, "y": y, "w": width, "h": 24},
                }
            )

    groups = two_stage._tile_card_parent_groups(region=region, numbered_items=items)

    columns = [group for group in groups if group.get("source") == "stage2_repeated_text_column_parent_grouping"]
    assert len(columns) == 4
    assert all(len(group["member_item_ids"]) == 4 for group in columns)
    assert all(group["bbox"]["y"] <= 282 for group in columns)
    assert all(group["bbox"]["h"] >= 170 for group in columns)


def test_two_stage_normalizes_parallel_list_parent_width_from_complete_sibling_column() -> None:
    region = {
        "region_id": "structure_region_primary_area",
        "bbox": {"x": 0, "y": 200, "w": 1200, "h": 700},
    }
    items = [
        {"number": "1.1", "item_id": "date_a1", "label": "2026-07-01", "role": "text", "bbox": {"x": 100, "y": 400, "w": 80, "h": 20}},
        {"number": "1.2", "item_id": "title_a1", "label": "A deliberately long first list title", "role": "text", "bbox": {"x": 200, "y": 400, "w": 300, "h": 20}},
        {"number": "1.3", "item_id": "date_a2", "label": "2026-07-02", "role": "text", "bbox": {"x": 100, "y": 440, "w": 80, "h": 20}},
        {"number": "1.4", "item_id": "title_a2", "label": "A second complete title", "role": "text", "bbox": {"x": 200, "y": 440, "w": 250, "h": 20}},
        {"number": "1.5", "item_id": "date_b1", "label": "2026-07-03", "role": "text", "bbox": {"x": 650, "y": 400, "w": 80, "h": 20}},
        {"number": "1.6", "item_id": "title_b1", "label": "Short event title", "role": "text", "bbox": {"x": 750, "y": 400, "w": 140, "h": 20}},
        {"number": "1.7", "item_id": "date_b2", "label": "2026-07-04", "role": "text", "bbox": {"x": 650, "y": 440, "w": 80, "h": 20}},
        {"number": "1.8", "item_id": "title_b2", "label": "Another event title", "role": "text", "bbox": {"x": 750, "y": 440, "w": 150, "h": 20}},
    ]

    groups = two_stage._list_row_parent_groups(region=region, numbered_items=items)

    list_groups = sorted((group for group in groups if group.get("role") == "list_group"), key=lambda group: group["bbox"]["x"])
    assert len(list_groups) == 2
    assert list_groups[0]["bbox"]["w"] == list_groups[1]["bbox"]["w"]
    assert list_groups[1]["bbox"]["w"] >= 400


def test_stage1_shallow_fullscreen_partition_uses_reliable_horizontal_control_row_boundary() -> None:
    region = {
        "region_id": "structure_region_main_content",
        "zone_id": "main_content",
        "bbox": {"x": 0, "y": 0, "w": 2500, "h": 1300},
        "rough_bbox": {"x": 520, "y": 134, "w": 920, "h": 187},
    }
    navigation_row = [
        {
            "item_id": f"nav_{index}",
            "label": f"Section {index}",
            "role": "text",
            "bbox": {"x": 650 + index * 120, "y": 180, "w": 72, "h": 24},
            "source": "conditional_ocr_content_recovery",
        }
        for index in range(7)
    ]
    body_evidence = [
        {
            "item_id": "hero_heading",
            "label": "Feature heading",
            "role": "text",
            "bbox": {"x": 760, "y": 245, "w": 240, "h": 30},
            "source": "conditional_ocr_content_recovery",
        },
        {
            "item_id": "hero_body",
            "label": "Feature body text",
            "role": "text",
            "bbox": {"x": 1260, "y": 245, "w": 260, "h": 30},
            "source": "conditional_ocr_content_recovery",
        },
    ]

    recovered = two_stage._recover_shallow_fullscreen_main_partition(
        [region],
        screen_size={"width": 2500, "height": 1300},
        boundary_evidence_items=[*navigation_row, *body_evidence],
    )

    assert recovered[0]["bbox"] == {"x": 0, "y": 0, "w": 2500, "h": 214}
    assert recovered[1]["bbox"] == {"x": 0, "y": 214, "w": 2500, "h": 1086}
    assert recovered[0]["boundary_recovery"]["source"] == "repeated_horizontal_control_row"
