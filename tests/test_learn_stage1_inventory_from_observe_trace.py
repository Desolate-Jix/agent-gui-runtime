from app.learn.recognition.two_stage import _merge_overlapping_same_family_structure_regions
from pathlib import Path

from scripts.run_learn_stage1_region_localization import (
    _observe_bundle_from_trace_result,
    _stage1_inventory_from_trace_result,
)


def test_stage1_inventory_reads_observe_screen_inventory() -> None:
    result = {
        "image_size": {"width": 800, "height": 600},
        "screen_inventory": {
            "available_actions": [
                {
                    "id": "action_home",
                    "label": "Home",
                    "role": "button",
                    "bbox": {"x": 10, "y": 12, "w": 40, "h": 32},
                }
            ],
            "page_elements": [
                {
                    "id": "text_title",
                    "text": "Welcome",
                    "role": "text",
                    "bbox": {"x": 80, "y": 20, "w": 120, "h": 28},
                }
            ],
            "cards": [
                {
                    "id": "card_feature",
                    "label": "Feature card",
                    "role": "card",
                    "bbox": {"x": 80, "y": 100, "w": 180, "h": 140},
                }
            ],
        },
    }

    items = _stage1_inventory_from_trace_result(result)

    assert [item["item_id"] for item in items] == ["action_home", "text_title", "card_feature"]
    assert {tuple(item["source_evidence"]) for item in items} == {
        ("screen_inventory_available_action",),
        ("screen_inventory_page_element",),
        ("screen_inventory_card",),
    }
    assert all(item["review_only"] is True for item in items)
    assert all(item["grounding_eligible"] is False for item in items)


def test_stage1_inventory_preserves_action_grounding_evidence_from_observe_trace() -> None:
    result = {
        "image_size": {"width": 800, "height": 600},
        "screen_inventory": {
            "available_actions": [
                {
                    "id": "action_up",
                    "label": "向上",
                    "role": "button",
                    "bbox": {"x": 451, "y": 257, "w": 32, "h": 33},
                    "source": "screen_reading.ui_elements",
                    "metadata": {
                        "evidence_level": "semantic_region_only",
                        "uia_match": None,
                        "interaction_type": "click",
                    },
                }
            ]
        },
    }

    items = _stage1_inventory_from_trace_result(result)

    assert len(items) == 1
    assert items[0]["source"] == "screen_reading.ui_elements"
    assert items[0]["evidence_level"] == "semantic_region_only"
    assert items[0]["metadata"]["evidence_level"] == "semantic_region_only"
    assert items[0]["metadata"]["uia_match"] is None
    assert items[0]["metadata"]["interaction_type"] == "click"


def test_stage1_inventory_reads_parser_screen_inventory_list() -> None:
    result = {
        "observe_bundle": {
            "image_size": {"width": 2521, "height": 1300},
            "screenshot_path": "artifacts/learning-runs/new_site_python_org_20260702/python_org_home.png",
        },
        "screen_inventory": [
            {
                "item_id": "c1",
                "label": "Search input",
                "item_type": "layout",
                "role": "input",
                "bbox": {"x": 1134, "y": 140, "w": 178, "h": 39},
                "source_evidence": ["vision"],
                "evidence_level": "semantic_region_only",
            },
            {
                "item_id": "bad_no_box",
                "label": "Ignored",
                "bbox": {},
            },
        ],
    }

    bundle = _observe_bundle_from_trace_result(result, trace_path=Path("parser_output.json"))
    items = _stage1_inventory_from_trace_result(result)

    assert bundle["image_path"] == "artifacts/learning-runs/new_site_python_org_20260702/python_org_home.png"
    assert bundle["screen_size"] == {"width": 2521, "height": 1300}
    assert len(items) == 1
    assert items[0]["item_id"] == "c1"
    assert items[0]["label"] == "Search input"
    assert items[0]["source_evidence"] == ["vision"]
    assert items[0]["metadata"]["source"] == "screen_inventory.list"
    assert items[0]["review_only"] is True
    assert items[0]["grounding_eligible"] is False


def test_stage1_inventory_does_not_promote_single_edge_ocr_text_to_sidebar() -> None:
    result = {
        "image_size": {"width": 1200, "height": 900},
        "texts": [
            {
                "id": "edge_title",
                "text": "页面标题",
                "bbox": {"x": 18, "y": 10, "w": 42, "h": 22},
                "confidence": 0.96,
            }
        ],
    }

    items = _stage1_inventory_from_trace_result(result)

    assert len(items) == 1
    assert items[0]["metadata"]["surface_zone"] == "top_bar"
    assert items[0]["metadata"]["zone_evidence"] == "geometry_hint_only"


def test_stage1_localization_merges_same_family_duplicate_structure_regions() -> None:
    regions = [
        {
            "region_id": "structure_region_browser_chrome",
            "zone_id": "browser_chrome",
            "label": "Browser chrome",
            "bbox": {"x": 0, "y": 0, "w": 1000, "h": 90},
            "rough_bbox": {"x": 0, "y": 0, "w": 1000, "h": 90},
            "item_ids": ["top_1"],
        },
        {
            "region_id": "structure_region_top_bar",
            "zone_id": "top_bar",
            "label": "Top bar",
            "bbox": {"x": 0, "y": 0, "w": 1000, "h": 90},
            "rough_bbox": {"x": 0, "y": 0, "w": 1000, "h": 90},
            "item_ids": ["top_2"],
        },
        {
            "region_id": "structure_region_main_content",
            "zone_id": "main_content",
            "label": "Main content",
            "bbox": {"x": 90, "y": 90, "w": 910, "h": 710},
            "rough_bbox": {"x": 90, "y": 90, "w": 910, "h": 710},
            "item_ids": ["main_1"],
        },
        {
            "region_id": "structure_region_primary_area",
            "zone_id": "primary_area",
            "label": "Primary area",
            "bbox": {"x": 90, "y": 90, "w": 910, "h": 710},
            "rough_bbox": {"x": 90, "y": 90, "w": 910, "h": 710},
            "item_ids": ["main_2"],
        },
    ]

    merged, events = _merge_overlapping_same_family_structure_regions(regions)

    assert len(merged) == 2
    assert len(events) == 2
    assert {event["family"] for event in events} == {"top_bar", "main_content"}
    top = next(region for region in merged if "top_1" in region["item_ids"])
    main = next(region for region in merged if "main_1" in region["item_ids"])
    assert top["item_ids"] == ["top_1", "top_2"]
    assert main["item_ids"] == ["main_1", "main_2"]
    assert top["merge_policy"] == "same_family_high_overlap_before_stage1_gate"
    assert main["merged_zone_ids"] == ["main_content", "primary_area"]
