from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.learn.draft_review import load_learning_draft_review
from app.main import app
from scripts.build_learn_page_detail_candidate import build_learn_page_detail_candidate
from scripts.render_learn_page_detail_candidate_preview import render_page_detail_candidate_preview


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_page_detail_candidate_preserves_panel_trial_overlay_and_screenshot(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "artifacts" / "learning-runs" / "panel_trial" / "trial_result.json",
        {
            "contract_version": "panel_learning_recognition_trial_run_v1",
            "observe_bundle": {
                "source_image_path": "artifacts/screenshots/apple_music.png",
                "sources": {
                    "calibrated_targets": {
                        "targets": [],
                        "source_overlay_path": "artifacts/review-overlays/apple_music_numbered.png",
                    }
                },
                "panel_observation_evidence": {
                    "evidence_quality": "review_boxes_available_no_executable_targets",
                    "coordinate_overlay_path": "artifacts/review-overlays/apple_music_numbered.png",
                    "review_box_count": 40,
                },
            },
            "learning_draft": {
                "contract_version": "learning_template_draft_v1",
                "regions": [
                    {
                        "region_id": "review_region_card_1",
                        "label": "推荐卡片",
                        "role": "review_only",
                        "bbox": {"x": 100, "y": 200, "w": 240, "h": 180},
                        "possible_operation": {"kind": "read_only", "readiness": "review_required"},
                    }
                ],
                "page_details": {},
            },
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    assert result["screenshot_path"] == "artifacts/screenshots/apple_music.png"
    assert result["compiled_overlay_path"] == "artifacts/review-overlays/apple_music_numbered.png"
    assert result["full_screen_understanding_overlay_path"] == "artifacts/review-overlays/apple_music_numbered.png"
    assert result["summary"]["region_count"] == 1


def test_page_detail_candidate_arranges_regions_by_source_layout(tmp_path: Path) -> None:
    precise = _write_json(
        tmp_path / "artifacts" / "candidate" / "learn_precise_understanding_candidate.json",
        {
            "contract_version": "learn_precise_understanding_candidate_v1",
            "readiness_status": "needs_pending_calibration",
            "screenshot_path": "artifacts/screen.png",
            "summary": {
                "pending_calibration_count": 1,
                "review_blocked_count": 1,
                "pathgraph_candidate_review_ready_count": 1,
            },
            "items": [
                {
                    "region_no": 1,
                    "source_item_id": "c1",
                    "label": "Job search bar",
                    "role": "input",
                    "rough_bbox_hint": {"x": 100, "y": 20, "w": 300, "h": 40},
                    "candidate_point": {"x": 150, "y": 38},
                    "calibration_state": "pending_execute_dry_run_calibration",
                    "pathgraph_candidate_review_state": "blocked_pending_execute_dry_run_calibration",
                },
                {
                    "region_no": 4,
                    "source_item_id": "c4",
                    "label": "Job listing card",
                    "role": "card",
                    "rough_bbox_hint": {"x": 90, "y": 180, "w": 360, "h": 180},
                    "candidate_point": {"x": 140, "y": 220},
                    "calibration_state": "calibrated_review_only",
                    "pathgraph_candidate_review_state": "candidate_for_human_pathgraph_review",
                },
                {
                    "region_no": 7,
                    "source_item_id": "c7",
                    "label": "Job details placeholder",
                    "role": "region",
                    "rough_bbox_hint": {"x": 500, "y": 180, "w": 420, "h": 220},
                    "candidate_point": {"x": 540, "y": 220},
                    "calibration_state": "review_before_calibration",
                    "pathgraph_candidate_review_state": "blocked_manual_review_before_calibration",
                },
            ],
            "safety": {"execute_binding_enabled": False, "runtime_pathgraph_promotion": False},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = build_learn_page_detail_candidate(source_path=precise, out_dir=precise.parent, project_root=tmp_path)

    assert result["contract_version"] == "learn_page_detail_candidate_v1"
    assert result["readiness_status"] == "needs_pending_calibration"
    assert result["summary"]["region_count"] == 3
    assert result["summary"]["section_count"] == 3
    assert result["summary"]["possible_operation_count"] == 3
    assert result["summary"]["runtime_pathgraph_promotion"] is False
    sections = {item["section_id"]: item for item in result["layout"]["sections"]}
    assert sections["top_search_and_filters"]["region_numbers"] == [1]
    assert sections["left_results_list"]["region_numbers"] == [4]
    assert sections["right_detail_panel"]["region_numbers"] == [7]
    assert sections["top_search_and_filters"]["bbox"] == {"x": 100, "y": 20, "w": 300, "h": 40}
    assert sections["left_results_list"]["operation_summary"]["kind_counts"] == {"open_detail": 1}
    assert sections["right_detail_panel"]["operation_summary"]["readiness_counts"] == {"blocked_manual_review": 1}
    assert sections["left_results_list"]["operation_links"] == [
        {
            "region_no": 4,
            "region_id": "learn_region_4",
            "label": "Job listing card",
            "operation_kind": "open_detail",
            "operation_label": "Open job detail",
            "readiness": "ready_for_human_pathgraph_review",
            "candidate_point": {"x": 140, "y": 220},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    ]
    by_region = {item["region_no"]: item for item in result["layout"]["regions"]}
    assert by_region[1]["possible_operation"]["kind"] == "fill_field"
    assert by_region[4]["possible_operation"]["kind"] == "open_detail"
    assert by_region[7]["possible_operation"]["readiness"] == "blocked_manual_review"
    assert result["safety"]["model_started"] is False
    assert result["safety"]["runtime_pathgraph_promotion"] is False
    assert Path(result["report_path"]).exists()


def test_page_detail_candidate_can_use_actual_parser_page_details(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "actual_parser_output_v1.json",
        {
            "contract_version": "actual_parser_output_v1",
            "actual_model_call_in_this_run": True,
            "screenshot_path": "artifacts/screen.png",
            "learning_draft": {
                "contract_version": "learning_template_draft_v1",
                "page_details": {
                    "contract_version": "learning_draft_page_details_v1",
                    "screen": {
                        "summary": "Search results page",
                        "image_path": "artifacts/screen.png",
                    },
                    "review_only_regions": [
                        {
                            "item_id": "c1",
                            "label": "Job search bar",
                            "role": "input",
                            "bbox": {"x": 100, "y": 20, "w": 300, "h": 40},
                            "decision": {"review_only": True},
                        },
                        {
                            "item_id": "c2",
                            "label": "Job listing card",
                            "role": "card",
                            "bbox": {"x": 90, "y": 180, "w": 360, "h": 180},
                            "decision": {"review_only": True},
                        },
                    ],
                    "inventory_summary": {
                        "pending_calibration_count": 2,
                        "review_blocked_count": 0,
                    },
                },
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    assert result["contract_version"] == "learn_page_detail_candidate_v1"
    assert result["source_detail_shape"] == "learning_draft_page_details_v1"
    assert result["readiness_status"] == "needs_page_detail_review"
    assert result["summary"]["region_count"] == 2
    assert result["summary"]["section_count"] == 2
    assert result["summary"]["possible_operation_count"] == 2
    assert result["screenshot_path"] == "artifacts/screen.png"
    sections = {item["section_id"]: item for item in result["layout"]["sections"]}
    assert sections["top_search_and_filters"]["region_numbers"] == [1]
    assert sections["left_results_list"]["region_numbers"] == [2]
    by_region = {item["source_item_id"]: item for item in result["layout"]["regions"]}
    assert by_region["c1"]["possible_operation"]["kind"] == "fill_field"
    assert by_region["c2"]["possible_operation"]["kind"] == "open_detail"
    assert by_region["c1"]["execute_binding_enabled"] is False
    assert result["safety"]["live_clicks"] == 0


def test_page_detail_candidate_can_use_learning_draft_regions_and_actions(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "actual_parser_output_v1.json",
        {
            "contract_version": "actual_parser_output_v1",
            "actual_model_call_in_this_run": True,
            "screenshot_path": "artifacts/screen.png",
            "learning_draft": {
                "contract_version": "learning_template_draft_v1",
                "regions": [
                    {
                        "region_id": "search_input",
                        "label": "Search input",
                        "role": "input",
                        "bbox": {"x": 20, "y": 20, "width": 220, "height": 40},
                    },
                    {
                        "region_id": "job_card",
                        "label": "Job card",
                        "role": "card",
                        "bbox": {"x": 40, "y": 220, "width": 360, "height": 180},
                    },
                ],
                "action_templates": [
                    {
                        "action_template_id": "fill_search",
                        "label": "Fill search input",
                        "semantic_action": "fill_field",
                        "target_entity": "search_input",
                    },
                    {
                        "action_template_id": "open_card",
                        "label": "Open job card",
                        "semantic_action": "open_detail",
                        "target_entity": "job_card",
                    },
                ],
            },
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    assert result["source_detail_shape"] == "learning_template_draft_v1"
    assert result["summary"]["region_count"] == 2
    assert result["summary"]["section_count"] >= 1
    by_region = {item["region_id"]: item for item in result["layout"]["regions"]}
    assert by_region["search_input"]["possible_operation"]["kind"] == "fill_field"
    assert by_region["job_card"]["possible_operation"]["kind"] == "open_detail"


def test_page_detail_candidate_uses_two_stage_parent_groups_as_template_sections(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "logs" / "trace.json",
        {
            "contract_version": "vision_trace_v1",
            "input": {"screenshot_path": "artifacts/screenshots/source.png"},
        },
    )
    source = _write_json(
        tmp_path / "logs" / "two_stage_python_like.json",
        {
            "contract_version": "learn_two_stage_screen_understanding_v1",
            "display_only": True,
            "stage2_numbering": {
                "contract_version": "learn_stage2_numbering_v1",
                "regions": [
                    {
                        "region_id": "structure_region_primary_area__stage1_5__content_column",
                        "label": "Stage1.5 content column",
                        "bbox": {"x": 500, "y": 200, "w": 900, "h": 800},
                        "subregion_groups": [
                            {
                                "group_id": "hero_panel_1",
                                "label": "hero panel",
                                "role": "hero_panel",
                                "bbox": {"x": 520, "y": 220, "w": 860, "h": 260},
                                "member_item_ids": ["hero_title", "hero_button"],
                                "source": "stage2_hero_panel_synthesis",
                            },
                            {
                                "group_id": "list_row_1",
                                "label": "2026-07-02 Release note",
                                "role": "list_row",
                                "bbox": {"x": 540, "y": 540, "w": 420, "h": 36},
                                "member_item_ids": ["date_1", "title_1"],
                                "source": "stage2_list_row_synthesis",
                            },
                        ],
                        "numbered_items": [
                            {
                                "item_id": "hero_title",
                                "number": "4.1",
                                "label": "Quick and Easy to Learn",
                                "role": "text",
                                "bbox": {"x": 560, "y": 240, "w": 300, "h": 30},
                            },
                                {
                                    "item_id": "hero_button",
                                    "number": "4.2",
                                    "label": "Learn More",
                                    "role": "button",
                                    "bbox": {"x": 560, "y": 430, "w": 120, "h": 34},
                                },
                                {
                                    "item_id": "hero_extra",
                                    "number": "4.2b",
                                    "label": "Extra hero copy",
                                    "role": "text",
                                    "bbox": {"x": 700, "y": 300, "w": 220, "h": 28},
                                },
                            {
                                "item_id": "date_1",
                                "number": "4.3",
                                "label": "2026-07-02",
                                "role": "text",
                                "bbox": {"x": 540, "y": 540, "w": 100, "h": 22},
                            },
                            {
                                "item_id": "title_1",
                                "number": "4.4",
                                "label": "Release note",
                                "role": "text",
                                "bbox": {"x": 660, "y": 540, "w": 200, "h": 22},
                            },
                            {
                                "item_id": "standalone_card",
                                "number": "4.5",
                                "label": "Download card",
                                "role": "news_card",
                                "bbox": {"x": 540, "y": 620, "w": 240, "h": 180},
                            },
                        ],
                    }
                ],
            },
            "fusion": {"contract_version": "learn_two_stage_fused_review_boxes_v1"},
            "fusion_status": {
                "compiled_overlay_path": "artifacts/review-overlays/compiled.png",
                "full_screen_understanding_overlay_path": "artifacts/review-overlays/full.png",
            },
            "source_trace_path": "logs/trace.json",
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    assert result["source_detail_shape"] == "learn_two_stage_screen_understanding_v1"
    assert result["screenshot_path"] == "artifacts/screenshots/source.png"
    assert result["compiled_overlay_path"] == "artifacts/review-overlays/compiled.png"
    assert result["full_screen_understanding_overlay_path"] == "artifacts/review-overlays/full.png"
    by_id = {item["region_id"]: item for item in result["layout"]["regions"]}
    assert "hero_panel_1" in by_id
    assert "list_row_1" in by_id
    assert "hero_title" not in by_id
    assert "date_1" not in by_id
    assert by_id["hero_panel_1"]["child_evidence_count"] == 3
    assert [item["source_item_id"] for item in by_id["hero_panel_1"]["child_evidence"]] == [
        "hero_title",
        "hero_button",
        "hero_extra",
    ]
    assert by_id["list_row_1"]["child_evidence_count"] == 2
    assert by_id["standalone_card"]["display_layer"] == "standalone_region"
    sections = {item["section_id"]: item for item in result["layout"]["sections"]}
    section = sections["structure_region_primary_area__stage1_5__content_column"]
    assert section["section_source"] == "stage2_parent_region"
    assert section["bbox"] == {"x": 500, "y": 200, "w": 900, "h": 800}
    assert section["region_count"] == 3
    assert section["region_numbers"] == [1, 2, 3]
    assert section["layout_zone"] == "middle_controls"
    assert by_id["hero_panel_1"]["source_section_id"] == section["section_id"]
    assert by_id["standalone_card"]["source_section_id"] == section["section_id"]
    assert by_id["standalone_card"]["inside_source_section"] is True


def test_page_detail_candidate_prefers_fused_main_overlay_boxes(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "two_stage_with_fusion.json",
        {
            "contract_version": "learn_two_stage_screen_understanding_v1",
            "stage2_numbering": {
                "regions": [
                    {
                        "region_id": "structure_region_primary_area",
                        "label": "Primary Area",
                        "bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                        "subregion_groups": [],
                        "numbered_items": [
                            {
                                "item_id": "raw_only_should_not_return",
                                "number": "1.9",
                                "label": "Raw only",
                                "role": "news_card",
                                "bbox": {"x": 20, "y": 20, "w": 100, "h": 80},
                            }
                        ],
                    }
                ]
            },
            "fusion": {
                "contract_version": "learn_two_stage_fused_review_boxes_v1",
                "fused_review_boxes": [
                    {
                        "box_type": "structure_region",
                        "number": "1",
                        "label": "Primary Area",
                        "bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "1.1",
                        "label": "Visible card",
                        "role": "news_card",
                        "bbox": {"x": 40, "y": 60, "w": 160, "h": 100},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_label": "Primary Area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                        "display_hierarchy": {"display_layer": "primary_region"},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "1.2",
                        "label": "Demoted text",
                        "role": "text",
                        "bbox": {"x": 44, "y": 70, "w": 120, "h": 20},
                        "render_in_main_overlay": False,
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_label": "Primary Area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 500, "h": 400},
                        "display_hierarchy": {"display_layer": "child_evidence"},
                    },
                ],
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    by_id = {item["region_id"]: item for item in result["layout"]["regions"]}
    assert list(by_id) == ["1_1"]
    assert by_id["1_1"]["page_detail_source"] == "two_stage_fused_review_box"
    assert by_id["1_1"]["display_layer"] == "primary_region"
    assert by_id["1_1"]["source_section_id"] == "structure_region_primary_area"
    assert result["layout"]["sections"][0]["section_id"] == "structure_region_primary_area"
    assert result["layout"]["sections"][0]["region_numbers"] == [1]


def test_page_detail_candidate_marks_background_review_boxes_low_emphasis(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "two_stage_with_background_review.json",
        {
            "contract_version": "learn_two_stage_screen_understanding_v1",
            "stage2_numbering": {
                "regions": [
                    {
                        "region_id": "structure_region_sidebar",
                        "label": "Sidebar",
                        "bbox": {"x": 0, "y": 0, "w": 80, "h": 400},
                        "subregion_groups": [],
                        "numbered_items": [],
                    }
                ]
            },
            "fusion": {
                "contract_version": "learn_two_stage_fused_review_boxes_v1",
                "fused_review_boxes": [
                    {
                        "box_type": "numbered_item",
                        "number": "2.8",
                        "label": "sidebar background / empty review region",
                        "role": "background_region",
                        "bbox": {"x": 4, "y": 40, "w": 60, "h": 330},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_sidebar",
                        "parent_region_label": "Sidebar",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 80, "h": 400},
                        "display_hierarchy": {
                            "display_layer": "review_region",
                            "reason": "semantic_region_only_without_grounding_evidence",
                        },
                    }
                ],
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    region = result["layout"]["regions"][0]
    assert region["visual_emphasis"] == "low_review"
    assert region["page_detail_review_category"] == "background_or_empty_review"
    assert region["possible_operation"]["kind"] == "read_only"
    assert region["pathgraph_candidate_review_state"] == "blocked_page_detail_review_only"
    assert region["execute_binding_enabled"] is False


def test_page_detail_candidate_groups_list_rows_for_display_parentage(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "two_stage_with_list_rows.json",
        {
            "contract_version": "learn_two_stage_screen_understanding_v1",
            "stage2_numbering": {
                "regions": [
                    {
                        "region_id": "structure_region_primary_area__stage1_5__content_column",
                        "label": "Stage1.5 content column",
                        "bbox": {"x": 100, "y": 100, "w": 900, "h": 700},
                        "subregion_groups": [],
                        "numbered_items": [],
                    }
                ]
            },
            "fusion": {
                "contract_version": "learn_two_stage_fused_review_boxes_v1",
                "fused_review_boxes": [
                    {
                        "box_type": "subregion_group",
                        "number": "list_row_1",
                        "label": "2026-07-02 Release note",
                        "role": "list_row",
                        "bbox": {"x": 140, "y": 420, "w": 300, "h": 28},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_primary_area__stage1_5__content_column",
                        "parent_region_label": "Stage1.5 content column",
                        "parent_region_bbox": {"x": 100, "y": 100, "w": 900, "h": 700},
                    },
                    {
                        "box_type": "subregion_group",
                        "number": "list_row_2",
                        "label": "2026-07-03 Second release note",
                        "role": "list_row",
                        "bbox": {"x": 140, "y": 462, "w": 330, "h": 28},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_primary_area__stage1_5__content_column",
                        "parent_region_label": "Stage1.5 content column",
                        "parent_region_bbox": {"x": 100, "y": 100, "w": 900, "h": 700},
                    },
                    {
                        "box_type": "subregion_group",
                        "number": "list_row_3",
                        "label": "2026-07-14 Event row",
                        "role": "list_row",
                        "bbox": {"x": 610, "y": 420, "w": 250, "h": 28},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_primary_area__stage1_5__content_column",
                        "parent_region_label": "Stage1.5 content column",
                        "parent_region_bbox": {"x": 100, "y": 100, "w": 900, "h": 700},
                    },
                    {
                        "box_type": "subregion_group",
                        "number": "list_row_4",
                        "label": "2026-07-15 Event row",
                        "role": "list_row",
                        "bbox": {"x": 610, "y": 463, "w": 250, "h": 28},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_primary_area__stage1_5__content_column",
                        "parent_region_label": "Stage1.5 content column",
                        "parent_region_bbox": {"x": 100, "y": 100, "w": 900, "h": 700},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "more_link",
                        "label": ">> More",
                        "role": "partial_visible_card",
                        "bbox": {"x": 960, "y": 570, "w": 72, "h": 24},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_primary_area__stage1_5__content_column",
                        "parent_region_label": "Stage1.5 content column",
                        "parent_region_bbox": {"x": 100, "y": 100, "w": 900, "h": 700},
                    },
                ],
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    display_groups = result["layout"]["display_groups"]
    assert result["summary"]["display_group_count"] == 2
    assert result["summary"]["list_group_count"] == 2
    assert [group["role"] for group in display_groups] == ["list_group", "list_group"]
    assert display_groups[0]["member_region_numbers"] == [1, 2]
    assert display_groups[1]["member_region_numbers"] == [3, 4]
    assert display_groups[1]["footer_region_numbers"] == [5]
    assert display_groups[1]["footer_region_ids"] == ["more_link"]
    assert display_groups[1]["bbox"]["y"] <= 410
    assert display_groups[1]["bbox"]["x"] + display_groups[1]["bbox"]["w"] < 960
    assert display_groups[1]["footer_bbox_policy"] == "semantic_attachment_no_bbox_expand"
    assert display_groups[1]["footer_connectors"] == [
        {
            "contract_version": "learn_page_detail_footer_connector_v1",
            "connector_role": "review_only_semantic_attachment",
            "footer_region_no": 5,
            "footer_region_id": "more_link",
            "from_point": {"x": 870, "y": 455},
            "to_point": {"x": 960, "y": 582},
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    ]
    assert all(group["execute_binding_enabled"] is False for group in display_groups)
    by_no = {item["region_no"]: item for item in result["layout"]["regions"]}
    assert by_no[1]["parent_display_group_id"] == display_groups[0]["group_id"]
    assert by_no[4]["parent_display_group_id"] == display_groups[1]["group_id"]
    assert by_no[5]["parent_display_group_id"] == display_groups[1]["group_id"]
    assert by_no[5]["parent_display_group_role"] == "list_group_footer"
    assert by_no[5]["page_detail_review_category"] == "list_group_footer"
    assert by_no[5]["evidence"]["list_group_footer_attachment"]["bbox_expanded"] is False


def test_page_detail_candidate_suppresses_overlapping_vertical_row_shells(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "two_stage_with_overlapping_member_row_shell.json",
        {
            "contract_version": "learn_two_stage_screen_understanding_v1",
            "stage2_numbering": {
                "regions": [
                    {
                        "region_id": "structure_region_right_sidebar",
                        "label": "Right sidebar/detail area",
                        "bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                        "subregion_groups": [],
                        "numbered_items": [],
                    }
                ]
            },
            "fusion": {
                "contract_version": "learn_two_stage_fused_review_boxes_v1",
                "fused_review_boxes": [
                    {
                        "box_type": "subregion_group",
                        "number": "member_list_region_1",
                        "label": "Group members",
                        "role": "member_list_region",
                        "bbox": {"x": 600, "y": 160, "w": 220, "h": 620},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "4.1",
                        "label": "Alice / Bob / Carol",
                        "role": "nav_item",
                        "bbox": {"x": 600, "y": 200, "w": 220, "h": 220},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "4.2",
                        "label": "Bob",
                        "role": "nav_item",
                        "bbox": {"x": 600, "y": 232, "w": 220, "h": 32},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "4.3",
                        "label": "Carol",
                        "role": "nav_item",
                        "bbox": {"x": 600, "y": 268, "w": 220, "h": 32},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "4.4",
                        "label": "Dana",
                        "role": "nav_item",
                        "bbox": {"x": 600, "y": 304, "w": 220, "h": 32},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                ],
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    by_label = {item["label"]: item for item in result["layout"]["regions"]}
    shell = by_label["Alice / Bob / Carol"]
    assert shell["visual_emphasis"] == "low_review"
    assert shell["page_detail_review_category"] == "overlapping_row_shell_review"
    assert shell["render_in_spatial_preview"] is False
    assert shell["evidence"]["page_detail_overlap_resolution"]["status"] == "suppressed_overlapping_row_shell"
    assert shell["evidence"]["page_detail_overlap_resolution"]["overlapped_sibling_count"] == 3
    assert all(by_label[name]["render_in_spatial_preview"] is True for name in ["Bob", "Carol", "Dana"])


def test_page_detail_candidate_downgrades_topbar_and_hero_shells(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "two_stage_with_semantic_shells.json",
        {
            "contract_version": "learn_two_stage_screen_understanding_v1",
            "stage2_numbering": {
                "regions": [
                    {
                        "region_id": "structure_region_top_bar",
                        "label": "Top/header area",
                        "bbox": {"x": 0, "y": 0, "w": 900, "h": 160},
                        "subregion_groups": [],
                        "numbered_items": [],
                    },
                    {
                        "region_id": "structure_region_primary_area",
                        "label": "Primary Area",
                        "bbox": {"x": 0, "y": 160, "w": 900, "h": 600},
                        "subregion_groups": [],
                        "numbered_items": [],
                    },
                ]
            },
            "fusion": {
                "contract_version": "learn_two_stage_fused_review_boxes_v1",
                "fused_review_boxes": [
                    {
                        "box_type": "subregion_group",
                        "number": "topbar_control_strip_1",
                        "label": "top/header control strip",
                        "role": "topbar_control_strip",
                        "bbox": {"x": 80, "y": 20, "w": 620, "h": 120},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_top_bar",
                        "parent_region_label": "Top/header area",
                        "parent_region_bbox": {"x": 0, "y": 0, "w": 900, "h": 160},
                    },
                    {
                        "box_type": "subregion_group",
                        "number": "hero_text_panel_1",
                        "label": "hero text panel",
                        "role": "hero_text_panel",
                        "bbox": {"x": 460, "y": 220, "w": 320, "h": 220},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_primary_area",
                        "parent_region_label": "Primary Area",
                        "parent_region_bbox": {"x": 0, "y": 160, "w": 900, "h": 600},
                    },
                ],
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    by_role = {item["role"]: item for item in result["layout"]["regions"]}
    assert by_role["topbar_control_strip"]["page_detail_review_category"] == "container_shell_review"
    assert by_role["topbar_control_strip"]["visual_emphasis"] == "low_review"
    assert by_role["hero_text_panel"]["page_detail_review_category"] == "semantic_panel_review"
    assert by_role["hero_text_panel"]["visual_emphasis"] == "review_candidate"
    assert by_role["hero_text_panel"]["render_in_spatial_preview"] is True


def test_page_detail_candidate_adds_container_display_groups_for_notice_and_members(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "two_stage_with_sidebar_containers.json",
        {
            "contract_version": "learn_two_stage_screen_understanding_v1",
            "stage2_numbering": {
                "regions": [
                    {
                        "region_id": "structure_region_right_sidebar",
                        "label": "Right sidebar/detail area",
                        "bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                        "subregion_groups": [],
                        "numbered_items": [],
                    }
                ]
            },
            "fusion": {
                "contract_version": "learn_two_stage_fused_review_boxes_v1",
                "fused_review_boxes": [
                    {
                        "box_type": "subregion_group",
                        "number": "notice_region_1",
                        "label": "Notice",
                        "role": "notice_region",
                        "bbox": {"x": 600, "y": 100, "w": 220, "h": 120},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                    {
                        "box_type": "subregion_group",
                        "number": "member_list_region_1",
                        "label": "Members",
                        "role": "member_list_region",
                        "bbox": {"x": 600, "y": 260, "w": 220, "h": 420},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "4.1",
                        "label": "Notice title",
                        "role": "notice_item",
                        "bbox": {"x": 610, "y": 108, "w": 180, "h": 28},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "4.2",
                        "label": "Notice body",
                        "role": "notice_item",
                        "bbox": {"x": 610, "y": 142, "w": 180, "h": 34},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "4.3",
                        "label": "Alice",
                        "role": "nav_item",
                        "bbox": {"x": 610, "y": 280, "w": 180, "h": 32},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "4.4",
                        "label": "Bob",
                        "role": "nav_item",
                        "bbox": {"x": 610, "y": 316, "w": 180, "h": 32},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_right_sidebar",
                        "parent_region_label": "Right sidebar/detail area",
                        "parent_region_bbox": {"x": 600, "y": 80, "w": 220, "h": 720},
                    },
                ],
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    groups = {item["role"]: item for item in result["layout"]["display_groups"]}
    assert groups["notice_region"]["member_region_ids"] == ["4_1", "4_2"]
    assert groups["member_list_region"]["member_region_ids"] == ["4_3", "4_4"]
    assert groups["notice_region"]["group_source"] == "page_detail_container_with_contained_children"
    assert groups["member_list_region"]["execute_binding_enabled"] is False
    by_id = {item["region_id"]: item for item in result["layout"]["regions"]}
    assert by_id["4_3"]["parent_display_group_id"] == groups["member_list_region"]["group_id"]
    assert by_id["4_3"]["parent_display_group_role"] == "member_list_region"


def test_page_detail_candidate_clips_overlapping_sibling_display_panels(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "two_stage_overlapping_hero_panels.json",
        {
            "contract_version": "learn_two_stage_screen_understanding_v1",
            "stage2_numbering": {
                "regions": [
                    {
                        "region_id": "structure_region_primary_area__stage1_5__content_column",
                        "label": "Stage1.5 content column",
                        "bbox": {"x": 500, "y": 200, "w": 900, "h": 800},
                        "subregion_groups": [],
                        "numbered_items": [],
                    }
                ]
            },
            "fusion": {
                "contract_version": "learn_two_stage_fused_review_boxes_v1",
                "fused_review_boxes": [
                    {
                        "box_type": "structure_region",
                        "number": "4",
                        "label": "Stage1.5 content column",
                        "bbox": {"x": 500, "y": 200, "w": 900, "h": 800},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "4.1",
                        "label": "Hero code panel",
                        "role": "hero_code_panel",
                        "bbox": {"x": 520, "y": 240, "w": 360, "h": 220},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_primary_area__stage1_5__content_column",
                        "parent_region_label": "Stage1.5 content column",
                        "parent_region_bbox": {"x": 500, "y": 200, "w": 900, "h": 800},
                        "display_hierarchy": {"display_layer": "review_region"},
                    },
                    {
                        "box_type": "numbered_item",
                        "number": "4.2",
                        "label": "Hero text panel",
                        "role": "hero_text_panel",
                        "bbox": {"x": 700, "y": 220, "w": 620, "h": 260},
                        "render_in_main_overlay": True,
                        "parent_region_id": "structure_region_primary_area__stage1_5__content_column",
                        "parent_region_label": "Stage1.5 content column",
                        "parent_region_bbox": {"x": 500, "y": 200, "w": 900, "h": 800},
                        "display_hierarchy": {"display_layer": "review_region"},
                    },
                ],
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = build_learn_page_detail_candidate(source_path=source, out_dir=source.parent, project_root=tmp_path)

    by_id = {item["region_id"]: item for item in result["layout"]["regions"]}
    code_bbox = by_id["4_1"]["bbox"]
    text_bbox = by_id["4_2"]["bbox"]
    assert code_bbox["x"] + code_bbox["w"] <= text_bbox["x"]
    assert text_bbox["w"] >= 120
    assert by_id["4_2"]["evidence"]["page_detail_collision_resolution"]["status"] == "clipped_sibling_overlap"
    section = result["layout"]["sections"][0]
    assert sorted(section["region_numbers"]) == [1, 2]
    assert any(item["bbox"] == text_bbox for item in section["regions"])


def test_page_detail_candidate_endpoint_is_no_execute(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    precise = _write_json(
        tmp_path / "artifacts" / "candidate" / "learn_precise_understanding_candidate.json",
        {
            "contract_version": "learn_precise_understanding_candidate_v1",
            "readiness_status": "needs_pending_calibration",
            "summary": {"pending_calibration_count": 1, "review_blocked_count": 0, "pathgraph_candidate_review_ready_count": 0},
            "items": [
                {
                    "region_no": 1,
                    "label": "Search button",
                    "role": "button",
                    "rough_bbox_hint": {"x": 20, "y": 20, "w": 100, "h": 40},
                    "calibration_state": "pending_execute_dry_run_calibration",
                    "pathgraph_candidate_review_state": "blocked_pending_execute_dry_run_calibration",
                }
            ],
            "safety": {"execute_binding_enabled": False, "runtime_pathgraph_promotion": False},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/create_page_detail_candidate",
        json={"source_path": str(precise.relative_to(tmp_path))},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["contract_version"] == "learn_page_detail_candidate_v1"
    assert data["summary"]["region_count"] == 1
    assert data["safety"]["model_started"] is False
    assert data["safety"]["live_clicks"] == 0
    assert data["safety"]["execute_binding_enabled"] is False
    assert data["safety"]["runtime_pathgraph_promotion"] is False
    assert data["trace_path"]


def test_page_detail_candidate_sidecar_loads_with_pathgraph_review(tmp_path: Path) -> None:
    reviewed = _write_json(
        tmp_path / "artifacts" / "candidate" / "reviewed_template_candidate.json",
        {
            "contract_version": "reviewed_template_candidate_v1",
            "draft": {"contract_version": "learning_template_draft_v1", "screen_summary": "Demo", "state_guess": "demo"},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    validation = _write_json(
        tmp_path / "artifacts" / "candidate" / "promotion_validation_report.json",
        {"contract_version": "pathgraph_candidate_validation_report_v1", "validation_status": "blocked_pending_calibration"},
    )
    candidate = _write_json(
        tmp_path / "artifacts" / "candidate" / "pathgraph_candidate.json",
        {
            "contract_version": "pathgraph_candidate_v1",
            "reviewed_template_candidate_path": str(reviewed.relative_to(tmp_path)),
            "validation_report_path": str(validation.relative_to(tmp_path)),
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    _write_json(
        tmp_path / "artifacts" / "candidate" / "learn_page_detail_candidate.json",
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "readiness_status": "needs_pending_calibration",
            "summary": {"region_count": 1, "section_count": 1, "runtime_pathgraph_promotion": False},
            "layout": {"bounds": {"x": 0, "y": 0, "w": 100, "h": 100}, "regions": [], "sections": []},
            "safety": {"model_started": False, "runtime_pathgraph_promotion": False},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    review = load_learning_draft_review(candidate.relative_to(tmp_path), project_root=tmp_path)

    sidecar = review["pathgraph_candidate_review"]["page_detail_candidate"]
    summary_sidecar = review["pathgraph_candidate_review"]["pathgraph_readiness_summary"]["page_detail_candidate"]
    assert sidecar["contract_version"] == "learn_page_detail_candidate_v1"
    assert sidecar["readiness_status"] == "needs_pending_calibration"
    assert summary_sidecar["summary"]["region_count"] == 1


def test_page_detail_candidate_preview_renderer_outputs_display_only_png(tmp_path: Path) -> None:
    candidate = _write_json(
        tmp_path / "artifacts" / "candidate" / "learn_page_detail_candidate.json",
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "layout_mode": "stage_parent_sections_spatial_bbox_order",
            "layout": {
                "bounds": {"x": 0, "y": 0, "w": 500, "h": 300},
                "sections": [
                    {
                        "section_id": "main",
                        "label": "Main",
                        "bbox": {"x": 0, "y": 0, "w": 500, "h": 300},
                        "section_source": "stage2_parent_region",
                        "region_count": 1,
                    }
                ],
                "regions": [
                    {
                        "region_no": 1,
                        "region_id": "card",
                        "label": "Card",
                        "bbox": {"x": 40, "y": 50, "w": 160, "h": 90},
                    }
                ],
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = render_page_detail_candidate_preview(source_path=candidate, project_root=tmp_path)

    output = tmp_path / result["output_path"]
    assert result["contract_version"] == "learn_page_detail_candidate_preview_v1"
    assert result["section_count"] == 1
    assert result["region_count"] == 1
    assert result["display_only"] is True
    assert result["execute_binding_enabled"] is False
    assert output.exists()
    assert output.read_bytes().startswith(b"\x89PNG")


def test_page_detail_candidate_preview_reports_low_emphasis_regions(tmp_path: Path) -> None:
    candidate = _write_json(
        tmp_path / "artifacts" / "candidate" / "learn_page_detail_candidate.json",
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "layout_mode": "stage_parent_sections_spatial_bbox_order",
            "layout": {
                "bounds": {"x": 0, "y": 0, "w": 500, "h": 300},
                "sections": [],
                "display_groups": [
                    {
                        "group_id": "list_group_1",
                        "label": "List group 1",
                        "role": "list_group",
                        "bbox": {"x": 130, "y": 30, "w": 210, "h": 160},
                    }
                ],
                "regions": [
                    {
                        "region_no": 1,
                        "region_id": "background",
                        "label": "sidebar background",
                        "bbox": {"x": 20, "y": 20, "w": 80, "h": 240},
                        "visual_emphasis": "low_review",
                    },
                    {
                        "region_no": 3,
                        "region_id": "suppressed_shell",
                        "label": "overlapping row shell",
                        "bbox": {"x": 20, "y": 20, "w": 300, "h": 220},
                        "visual_emphasis": "low_review",
                        "render_in_spatial_preview": False,
                    },
                    {
                        "region_no": 2,
                        "region_id": "card",
                        "label": "content card",
                        "bbox": {"x": 140, "y": 40, "w": 180, "h": 120},
                        "visual_emphasis": "primary_content",
                    },
                ],
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = render_page_detail_candidate_preview(source_path=candidate, project_root=tmp_path)

    assert result["region_count"] == 3
    assert result["spatial_region_count"] == 2
    assert result["spatial_preview_suppressed_region_count"] == 1
    assert result["display_group_count"] == 1
    assert result["low_emphasis_region_count"] == 2
    assert result["primary_region_count"] == 1
