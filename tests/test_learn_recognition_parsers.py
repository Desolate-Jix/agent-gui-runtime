from app.learn.recognition.parsers import parse_existing_evidence_to_inventory
from app.learn.recognition.classifier import classify_inventory_items


def test_ocr_parser_outputs_readable_non_click_items():
    bundle = {
        "sources": {
            "ocr": {
                "texts": [
                    {
                        "id": "t1",
                        "text": "Latest News",
                        "bbox": {"x": 1, "y": 2, "w": 80, "h": 20},
                    }
                ]
            }
        }
    }

    items = parse_existing_evidence_to_inventory(bundle)

    assert items[0]["item_type"] == "readable"
    assert items[0]["click_candidate"] is False
    assert items[0]["artifact_is_authorization"] is False
    assert items[0]["evidence_level"] == "ocr_text_only"


def test_uia_parser_preserves_invokable_evidence_without_authorizing_click():
    bundle = {
        "screen_size": {"width": 1000, "height": 800},
        "capture_id": "capture-cross",
        "source_run_id": "cross-run",
        "screenshot_sha256": "e" * 64,
        "sources": {
            "uia": {
                "controls": [
                    {
                        "id": "u1",
                        "name": "Search",
                        "control_type": "Button",
                        "bbox": {"x": 1, "y": 2, "w": 80, "h": 30},
                        "patterns": ["Invoke"],
                    }
                ]
            }
        }
    }

    items = parse_existing_evidence_to_inventory(bundle)

    assert items[0]["item_type"] == "actionable"
    assert items[0]["interactable_evidence"]["uia_invokable"] is True
    assert items[0]["click_candidate"] is False
    assert items[0]["artifact_is_authorization"] is False


def test_vision_parser_converts_model_diagonal_to_bbox():
    bundle = {
        "screenshot_sha256": "a" * 64,
        "capture_id": "capture-parser-1",
        "source_run_id": "parser_run_1",
        "coordinate_space": "image",
        "screen_size": {"width": 1400, "height": 900},
        "sources": {
            "vision": {
                "regions": [
                    {
                        "region_id": "c2",
                        "label": "Search button",
                        "role": "button",
                        "diagonal": {"x1": 1322, "y1": 244, "x2": 1379, "y2": 290},
                    }
                ]
            }
        }
    }

    items = parse_existing_evidence_to_inventory(bundle)

    assert items[0]["label"] == "Search button"
    assert items[0]["bbox"] == {"x": 1322, "y": 244, "w": 57, "h": 46}
    assert items[0]["source_evidence"] == ["vision"]
    assert items[0]["evidence_level"] == "semantic_region_only"
    assert items[0]["parser_candidate"]["schema_version"] == "parser_candidate_v1"
    assert items[0]["parser_candidate"]["source_type"] == "qwen_vlm"
    assert items[0]["parser_candidate"]["source_run_id"] == "parser_run_1"
    assert items[0]["parser_candidate"]["screenshot_sha256"] == "a" * 64
    assert items[0]["parser_candidate"]["coordinate_space"] == "image"
    assert items[0]["parser_candidate"]["evidence_kind"] == "semantic_region"
    assert items[0]["parser_candidate"]["review_only"] is True
    assert items[0]["parser_candidate"]["grounding_eligible"] is False
    assert items[0]["parser_candidate"]["grounding_block_reason"] == "semantic_region_only_without_interactable_evidence"
    assert items[0]["parser_candidate"]["artifact_is_authorization"] is False
    assert items[0]["parser_candidate"]["execute_binding_enabled"] is False


def test_vision_parser_preserves_locator_descriptions_for_task_cards():
    bundle = {
        "screen_size": {"width": 1400, "height": 900},
        "sources": {
            "vision": {
                "regions": [
                    {
                        "region_id": "job_card_1",
                        "label": "Job listing card",
                        "role": "card",
                        "description": "card containing Software Engineer title, AIA New Zealand company, and Auckland location",
                        "text_lines": [
                            "Software Engineer Specialist - Integration",
                            "AIA New Zealand",
                            "Takapuna, Auckland",
                        ],
                        "boundary_definition": "single white card from title row to featured footer, excluding next card below",
                        "clickable_area_hint": "safe interior around the title and company text",
                        "bbox": {"x": 300, "y": 400, "w": 420, "h": 260},
                    }
                ]
            }
        },
    }

    items = parse_existing_evidence_to_inventory(bundle)

    assert items[0]["metadata"]["description"] == (
        "card containing Software Engineer title, AIA New Zealand company, and Auckland location"
    )
    assert items[0]["metadata"]["text_lines"] == [
        "Software Engineer Specialist - Integration",
        "AIA New Zealand",
        "Takapuna, Auckland",
    ]
    assert items[0]["metadata"]["boundary_definition"] == (
        "single white card from title row to featured footer, excluding next card below"
    )
    assert items[0]["metadata"]["clickable_area_hint"] == "safe interior around the title and company text"


def test_vision_region_with_uia_overlap_becomes_cross_evidence_grounded():
    bundle = {
        "screen_size": {"width": 1000, "height": 800},
        "capture_id": "capture-cross",
        "source_run_id": "cross-run",
        "screenshot_sha256": "e" * 64,
        "sources": {
            "uia": {
                "controls": [
                    {
                        "id": "u1",
                        "name": "Search",
                        "control_type": "Button",
                        "bbox": {"x": 100, "y": 100, "w": 80, "h": 32},
                        "patterns": ["Invoke"],
                    }
                ]
            },
            "vision": {
                "regions": [
                    {
                        "region_id": "v1",
                        "label": "Search",
                        "role": "button",
                        "bbox": {"x": 96, "y": 96, "w": 88, "h": 40},
                    }
                ]
            },
        }
    }

    items = parse_existing_evidence_to_inventory(bundle)
    vision_item = next(item for item in items if item["item_id"] == "v1")
    classification = classify_inventory_items(items)

    assert vision_item["item_type"] == "actionable"
    assert vision_item["role"] == "button"
    assert vision_item["evidence_level"] == "cross_evidence_grounded"
    assert vision_item["source_evidence"] == ["vision", "uia"]
    assert vision_item["interactable_evidence"]["uia_invokable"] is True
    assert vision_item["interactable_evidence"]["cross_evidence_overlap"] is True
    assert vision_item["metadata"]["cross_evidence"]["support_item_id"] == "u1"
    assert vision_item["parser_candidate"]["source_type"] == "mixed"
    assert vision_item["parser_candidate"]["evidence_kind"] == "cross_evidence_interactable"
    assert vision_item["parser_candidate"]["is_interactable_evidence"] is True
    assert vision_item["parser_candidate"]["grounding_eligible"] is True
    assert vision_item["parser_candidate"]["review_only"] is False
    assert "Search" in {item["label"] for item in classification["accepted_for_grounding"]}


def test_large_semantic_container_over_small_button_stays_review_only():
    bundle = {
        "screen_size": {"width": 1000, "height": 800},
        "sources": {
            "uia": {
                "controls": [
                    {
                        "id": "u1",
                        "name": "Search",
                        "control_type": "Button",
                        "bbox": {"x": 100, "y": 100, "w": 80, "h": 32},
                        "patterns": ["Invoke"],
                    }
                ]
            },
            "vision": {
                "regions": [
                    {
                        "region_id": "hero",
                        "label": "Hero search area",
                        "role": "section",
                        "bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                    }
                ]
            },
        },
    }

    items = parse_existing_evidence_to_inventory(bundle)
    hero = next(item for item in items if item["item_id"] == "hero")
    classification = classify_inventory_items(items)

    assert hero["evidence_level"] == "semantic_region_only"
    assert hero["interactable_evidence"]["cross_evidence_overlap"] is False
    assert "Hero search area" in {item["label"] for item in classification["rejected_non_actionable"]}


def test_omniparser_parser_converts_normalized_bbox_and_interactivity():
    bundle = {
        "screen_size": {"width": 1000, "height": 800},
        "capture_id": "capture-omni-search",
        "source_run_id": "omni-run-search",
        "screenshot_sha256": "c" * 64,
        "sources": {
            "omniparser": {
                "provider": "omniparser",
                "model_revision": "v.2.0.1",
                "capture_id": "capture-omni-search",
                "source_run_id": "omni-run-search",
                "screenshot_sha256": "c" * 64,
                "image_size": {"width": 1000, "height": 800},
                "coordinate_space": "image_normalized_xyxy",
                "parsed_content_list": [
                    {
                        "type": "icon",
                        "content": "Search",
                        "bbox": [0.1, 0.2, 0.2, 0.25],
                        "interactivity": True,
                        "source": "box_yolo_content_yolo",
                    }
                ]
            }
        },
    }

    items = parse_existing_evidence_to_inventory(bundle)

    assert items[0]["label"] == "Search"
    assert items[0]["item_type"] == "actionable"
    assert items[0]["role"] == "icon_button"
    assert items[0]["bbox"] == {"x": 100, "y": 160, "w": 100, "h": 40}
    assert items[0]["source_evidence"] == ["omniparser"]
    assert items[0]["interactable_evidence"]["omniparser_interactable"] is True
    assert items[0]["parser_candidate"]["source_type"] == "omniparser"
    assert items[0]["parser_candidate"]["evidence_kind"] == "omniparser_interactable"
    assert items[0]["parser_candidate"]["grounding_eligible"] is True
    assert items[0]["artifact_is_authorization"] is False


def test_omniparser_parser_treats_textarea_as_form_field():
    bundle = {
        "screen_size": {"width": 1000, "height": 800},
        "capture_id": "capture-omni-textarea",
        "source_run_id": "omni-run-textarea",
        "screenshot_sha256": "d" * 64,
        "sources": {
            "omniparser": {
                "provider": "omniparser",
                "model_revision": "v.2.0.1",
                "capture_id": "capture-omni-textarea",
                "source_run_id": "omni-run-textarea",
                "screenshot_sha256": "d" * 64,
                "image_size": {"width": 1000, "height": 800},
                "coordinate_space": "image_normalized_xyxy",
                "parsed_content_list": [
                    {
                        "type": "textarea",
                        "content": "Cover letter",
                        "bbox": [0.1, 0.2, 0.7, 0.6],
                        "interactivity": True,
                        "source": "box_yolo_content_yolo",
                    }
                ]
            }
        },
    }

    items = parse_existing_evidence_to_inventory(bundle)
    classification = classify_inventory_items(items)

    assert items[0]["label"] == "Cover letter"
    assert items[0]["item_type"] == "form_field"
    assert items[0]["role"] == "input"
    assert items[0]["interactable_evidence"]["omniparser_interactable"] is True
    assert classification["accepted_for_grounding"][0]["label"] == "Cover letter"


def test_calibrated_target_parser_accepts_only_validated_grounding_evidence():
    bundle = {
        "screen_size": {"width": 1400, "height": 900},
        "capture_id": "capture-calibrated",
        "source_run_id": "calibrated-run",
        "screenshot_sha256": "f" * 64,
        "sources": {
            "calibrated_targets": {
                "source_trace_path": "logs/traces/vision/deep.json",
                "source_overlay_path": "artifacts/review-overlays/overlay.png",
                "targets": [
                    {
                        "candidate_id": "element_search_button",
                        "label": "Search button",
                        "role": "button",
                        "bbox": {"x": 1322, "y": 244, "w": 57, "h": 46},
                        "click_point": {"x": 1350, "y": 267},
                        "coordinate_validation": {
                            "status": "valid",
                            "bbox_present": True,
                            "click_point_present": True,
                            "bbox_inside_image": True,
                            "click_point_inside_image": True,
                            "click_point_inside_bbox": True,
                        },
                    },
                    {
                        "candidate_id": "element_unchecked",
                        "label": "Unchecked button",
                        "role": "button",
                        "bbox": {"x": 1, "y": 2, "w": 30, "h": 20},
                        "coordinate_validation": {
                            "status": "invalid",
                            "bbox_present": True,
                            "click_point_present": False,
                        },
                    },
                ],
            }
        }
    }

    items = parse_existing_evidence_to_inventory(bundle)
    classification = classify_inventory_items(items)

    assert items[0]["source_evidence"] == ["calibrated_target"]
    assert items[0]["interactable_evidence"]["calibrated_target_validated"] is True
    assert items[0]["metadata"]["source_trace_path"] == "logs/traces/vision/deep.json"
    assert classification["accepted_for_grounding"][0]["label"] == "Search button"
    assert classification["needs_human_review"][0]["label"] == "Unchecked button"


def test_execute_candidate_result_parser_is_learn_only_interactable_evidence():
    bundle = {
        "screen_size": {"width": 800, "height": 600},
        "capture_id": "capture-execute",
        "source_run_id": "execute-run",
        "screenshot_sha256": "g" * 64,
        "sources": {
            "execute_candidate_result": {
                "source_trace_path": "logs/traces/vision/recognition-plan.json",
                "candidates": [
                    {
                        "candidate_id": "path_graph_home",
                        "rank": 1,
                        "score": 0.92,
                        "eligible": True,
                        "reasons": ["path_graph_recall", "vista_point_inside_candidate_bbox"],
                        "element": {
                            "element_id": "path_graph_home",
                            "label": "Home",
                            "role": "nav text action",
                            "interaction_type": "click",
                            "bbox": {"x": 30, "y": 120, "w": 80, "h": 60},
                            "click_point": {"x": 56, "y": 150},
                        },
                    }
                ],
            }
        }
    }

    items = parse_existing_evidence_to_inventory(bundle)
    classification = classify_inventory_items(items)

    assert items[0]["label"] == "Home"
    assert items[0]["source_evidence"] == ["execute_candidate_result"]
    assert items[0]["interactable_evidence"]["execute_candidate_ranked"] is True
    assert items[0]["click_candidate"] is False
    assert items[0]["artifact_is_authorization"] is False
    assert classification["accepted_for_grounding"][0]["label"] == "Home"


def test_omniparser_parser_requires_fresh_current_screenshot_identity() -> None:
    matching_bundle = {
        "screen_size": {"width": 1000, "height": 800},
        "capture_id": "capture-17",
        "screenshot_sha256": "a" * 64,
        "sources": {
            "omniparser": {
                "contract_version": "screen_parser_result_v1",
                "provider": "omniparser",
                "model_revision": "v.2.0.1",
                "capture_id": "capture-17",
                "source_run_id": "omni-run-17",
                "screenshot_sha256": "a" * 64,
                "image_size": {"width": 1000, "height": 800},
                "coordinate_space": "image_normalized_xyxy",
                "elements": [
                    {
                        "element_id": "omni_search",
                        "type": "icon",
                        "content": "Search",
                        "bbox": [0.1, 0.2, 0.2, 0.25],
                        "interactivity": True,
                    }
                ],
            }
        },
    }

    matching_item = parse_existing_evidence_to_inventory(matching_bundle)[0]
    matching_classification = classify_inventory_items([matching_item])

    assert matching_item["parser_candidate"]["provider"] == "omniparser"
    assert matching_item["parser_candidate"]["model_revision"] == "v.2.0.1"
    assert matching_item["parser_candidate"]["capture_id"] == "capture-17"
    assert matching_item["parser_candidate"]["freshness"] == {
        "same_screenshot": True,
        "capture_time": "",
        "stale": False,
    }
    assert matching_classification["accepted_for_grounding"][0]["label"] == "Search"

    stale_bundle = {
        **matching_bundle,
        "sources": {
            "omniparser": {
                **matching_bundle["sources"]["omniparser"],
                "screenshot_sha256": "b" * 64,
                "stale": True,
            }
        },
    }
    stale_item = parse_existing_evidence_to_inventory(stale_bundle)[0]
    stale_classification = classify_inventory_items([stale_item])

    assert stale_item["parser_candidate"]["freshness"]["same_screenshot"] is False
    assert stale_item["parser_candidate"]["freshness"]["stale"] is True
    assert stale_classification["needs_human_review"][0]["grounding_eligible"] is False
    assert stale_classification["needs_human_review"][0]["grounding_block_reason"] == "parser_candidate_stale"


def test_freshness_gate_does_not_change_legacy_item_without_parser_candidate() -> None:
    legacy_item = {
        "item_id": "legacy_uia",
        "label": "Search",
        "item_type": "actionable",
        "role": "button",
        "source_evidence": ["uia"],
        "interactable_evidence": {"uia_invokable": True},
    }

    classification = classify_inventory_items([legacy_item])

    assert classification["accepted_for_grounding"][0]["label"] == "Search"
