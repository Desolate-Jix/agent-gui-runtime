from __future__ import annotations

from app.learn.ui_hierarchy import build_ui_hierarchy_graph
from app.learn.recognition.two_stage import build_two_stage_screen_understanding


def _structure(region_id: str, bbox: dict[str, int]) -> dict:
    return {
        "region_id": region_id,
        "label": region_id,
        "bbox": bbox,
        "coordinate_validation": {"status": "passed", "evidence": "fixture"},
    }


def test_ui_hierarchy_builds_unique_nested_parents() -> None:
    structure_regions = [_structure("main", {"x": 0, "y": 80, "w": 800, "h": 520})]
    numbered_regions = [
        {
            "region_id": "main",
            "bbox": {"x": 0, "y": 80, "w": 800, "h": 520},
            "subregion_groups": [
                {
                    "group_id": "news_section",
                    "role": "section_parent",
                    "bbox": {"x": 80, "y": 120, "w": 640, "h": 360},
                    "child_group_ids": ["news_list"],
                    "member_item_ids": ["date_1", "title_1"],
                    "source": "fixture_section",
                },
                {
                    "group_id": "news_list",
                    "role": "list_group",
                    "bbox": {"x": 100, "y": 180, "w": 600, "h": 220},
                    "child_group_ids": ["news_row_1"],
                    "member_item_ids": ["date_1", "title_1"],
                    "source": "fixture_list",
                },
                {
                    "group_id": "news_row_1",
                    "role": "list_row",
                    "bbox": {"x": 100, "y": 180, "w": 520, "h": 28},
                    "member_item_ids": ["date_1", "title_1"],
                    "source": "fixture_row",
                },
            ],
            "numbered_items": [
                {
                    "item_id": "date_1",
                    "number": "1.1",
                    "label": "2026-07-12",
                    "role": "text",
                    "bbox": {"x": 100, "y": 180, "w": 90, "h": 22},
                    "source": "ocr",
                },
                {
                    "item_id": "title_1",
                    "number": "1.2",
                    "label": "Release note",
                    "role": "text",
                    "bbox": {"x": 210, "y": 180, "w": 180, "h": 22},
                    "source": "ocr",
                },
            ],
        }
    ]

    graph = build_ui_hierarchy_graph(
        structure_regions=structure_regions,
        numbered_regions=numbered_regions,
        screen_size={"width": 800, "height": 600},
    )

    by_source = {node.get("source_ref"): node for node in graph["nodes"] if node.get("source_ref")}
    assert by_source["news_section"]["level"] == "section"
    assert by_source["news_list"]["parent_id"] == by_source["news_section"]["node_id"]
    assert by_source["news_row_1"]["parent_id"] == by_source["news_list"]["node_id"]
    assert by_source["date_1"]["parent_id"] == by_source["news_row_1"]["node_id"]
    assert by_source["title_1"]["parent_id"] == by_source["news_row_1"]["node_id"]
    assert graph["validation"]["orphan_node_count"] == 0
    assert all(node["parent_id"] for node in graph["nodes"] if node["level"] != "screen")


def test_ui_hierarchy_attaches_stage1_5_numbered_regions_to_structure_parent() -> None:
    graph = build_ui_hierarchy_graph(
        structure_regions=[_structure("main", {"x": 0, "y": 0, "w": 900, "h": 600})],
        numbered_regions=[
            {
                "region_id": "main__stage1_5__conversation_list",
                "bbox": {"x": 0, "y": 0, "w": 340, "h": 600},
                "input_stage1_5_subregion": {
                    "subregion_id": "main__stage1_5__conversation_list",
                    "parent_region_id": "main",
                    "role": "conversation_list",
                },
                "subregion_groups": [
                    {
                        "group_id": "conversation_row_1",
                        "role": "conversation_row",
                        "bbox": {"x": 20, "y": 120, "w": 300, "h": 64},
                        "member_item_ids": ["conversation_title_1"],
                        "source": "fixture_stage1_5_row",
                    }
                ],
                "numbered_items": [
                    {
                        "item_id": "conversation_title_1",
                        "number": "1.1",
                        "label": "Example chat",
                        "role": "text",
                        "bbox": {"x": 90, "y": 130, "w": 140, "h": 22},
                        "source": "ocr",
                    }
                ],
            },
            {
                "region_id": "main__stage1_5__message_thread",
                "bbox": {"x": 340, "y": 0, "w": 560, "h": 600},
                "input_stage1_5_subregion": {
                    "subregion_id": "main__stage1_5__message_thread",
                    "parent_region_id": "main",
                    "role": "message_thread",
                },
                "subregion_groups": [],
                "numbered_items": [],
            },
        ],
        screen_size={"width": 900, "height": 600},
    )

    by_source = {node.get("source_ref"): node for node in graph["nodes"] if node.get("source_ref")}
    assert by_source["conversation_row_1"]["component_type"] == "conversation_row"
    assert by_source["conversation_title_1"]["parent_id"] == by_source["conversation_row_1"]["node_id"]
    assert by_source["conversation_row_1"]["parent_id"] == by_source["main"]["node_id"]
    assert graph["validation"]["passed"] is True


def test_ui_hierarchy_prefers_atomic_control_parent_over_semantic_group_for_factual_children() -> None:
    graph = build_ui_hierarchy_graph(
        structure_regions=[_structure("main", {"x": 0, "y": 0, "w": 640, "h": 420})],
        numbered_regions=[
            {
                "region_id": "main",
                "bbox": {"x": 0, "y": 0, "w": 640, "h": 420},
                "subregion_groups": [
                    {
                        "group_id": "conversation_list",
                        "role": "conversation_group",
                        "bbox": {"x": 30, "y": 40, "w": 280, "h": 330},
                        "member_item_ids": ["avatar_1", "title_1"],
                        "source": "semantic_interpretation",
                    }
                ],
                "control_parents": [
                    {
                        "object_id": "control_parent_row_1",
                        "label": "Conversation row",
                        "role": "atomic_control_parent",
                        "bbox": {"x": 48, "y": 82, "w": 220, "h": 46},
                        "member_object_ids": ["avatar_1", "title_1"],
                        "source": "repeated_visual_anchor_with_row_evidence",
                    }
                ],
                "numbered_items": [
                    {
                        "item_id": "avatar_1",
                        "label": "Avatar",
                        "role": "icon",
                        "bbox": {"x": 48, "y": 82, "w": 42, "h": 42},
                        "source": "visual",
                    },
                    {
                        "item_id": "title_1",
                        "label": "Chat title",
                        "role": "text",
                        "bbox": {"x": 100, "y": 90, "w": 120, "h": 20},
                        "source": "ocr",
                    },
                ],
            }
        ],
        screen_size={"width": 640, "height": 420},
    )

    by_source = {node.get("source_ref"): node for node in graph["nodes"] if node.get("source_ref")}
    control_parent = by_source["control_parent_row_1"]
    assert control_parent["level"] == "component"
    assert control_parent["component_type"] == "atomic_control_parent"
    assert control_parent["parent_id"] == "uih:structure:main"
    assert by_source["avatar_1"]["parent_id"] == control_parent["node_id"]
    assert by_source["title_1"]["parent_id"] == control_parent["node_id"]
    assert by_source["conversation_list"]["node_id"] != control_parent["node_id"]
    assert graph["summary"]["control_parent_count"] == 1
    assert graph["validation"]["duplicate_primary_owner_count"] == 0


def test_ui_hierarchy_keeps_empty_structure_region_and_clips_children() -> None:
    structure_regions = [
        _structure("top_bar", {"x": 0, "y": 0, "w": 500, "h": 80}),
        _structure("main", {"x": 0, "y": 80, "w": 500, "h": 320}),
    ]
    numbered_regions = [
        {
            "region_id": "main",
            "bbox": {"x": 0, "y": 80, "w": 500, "h": 320},
            "subregion_groups": [],
            "numbered_items": [
                {
                    "item_id": "overflowing_label",
                    "label": "Overflowing label",
                    "role": "text",
                    "bbox": {"x": 460, "y": 360, "w": 100, "h": 80},
                    "source": "fixture",
                }
            ],
        }
    ]

    graph = build_ui_hierarchy_graph(
        structure_regions=structure_regions,
        numbered_regions=numbered_regions,
        screen_size={"width": 500, "height": 400},
    )

    structure_nodes = [node for node in graph["nodes"] if node["level"] == "structure_region"]
    assert {node["source_ref"] for node in structure_nodes} == {"top_bar", "main"}
    top_node = next(node for node in structure_nodes if node["source_ref"] == "top_bar")
    assert top_node["children"] == []
    label = next(node for node in graph["nodes"] if node.get("source_ref") == "overflowing_label")
    assert label["bbox"] == {"x": 460, "y": 360, "w": 40, "h": 40}
    assert label["review_status"] == "needs_review"
    assert graph["validation"]["child_outside_parent_count"] == 0
    assert graph["validation"]["clipped_node_count"] == 1
    assert graph["validation"]["passed"] is False
    assert graph["validation"]["status"] == "needs_review"


def test_ui_hierarchy_does_not_restore_rejected_geometry_only_owner() -> None:
    structure_regions = [_structure("main", {"x": 0, "y": 0, "w": 600, "h": 400})]
    numbered_regions = [
        {
            "region_id": "main",
            "bbox": {"x": 0, "y": 0, "w": 600, "h": 400},
            "subregion_groups": [
                {
                    "group_id": "accepted_row",
                    "role": "list_row",
                    "bbox": {"x": 80, "y": 100, "w": 420, "h": 30},
                    "member_item_ids": ["title"],
                    "source": "fixture_explicit_owner",
                },
                {
                    "group_id": "rejected_tile",
                    "role": "tile_card_parent",
                    "bbox": {"x": 60, "y": 80, "w": 480, "h": 100},
                    "member_item_ids": [],
                    "source": "fixture_rejected_geometry_owner",
                },
            ],
            "numbered_items": [
                {
                    "item_id": "title",
                    "label": "Title",
                    "role": "text",
                    "bbox": {"x": 100, "y": 104, "w": 180, "h": 22},
                    "source": "ocr",
                }
            ],
        }
    ]

    graph = build_ui_hierarchy_graph(
        structure_regions=structure_regions,
        numbered_regions=numbered_regions,
        screen_size={"width": 600, "height": 400},
    )

    title = next(node for node in graph["nodes"] if node.get("source_ref") == "title")
    assert title["parent_id"].endswith(":accepted_row")
    assert title["competing_owner_ids"] == []
    assert graph["validation"]["duplicate_primary_owner_count"] == 0


def test_ui_hierarchy_does_not_assign_geometry_owner_when_item_exceeds_group() -> None:
    graph = build_ui_hierarchy_graph(
        structure_regions=[_structure("main", {"x": 0, "y": 0, "w": 500, "h": 300})],
        numbered_regions=[
            {
                "region_id": "main",
                "bbox": {"x": 0, "y": 0, "w": 500, "h": 300},
                "subregion_groups": [
                    {
                        "group_id": "nearby_row",
                        "role": "list_row",
                        "bbox": {"x": 100, "y": 80, "w": 100, "h": 40},
                        "member_item_ids": [],
                    }
                ],
                "numbered_items": [
                    {
                        "item_id": "wider_item",
                        "label": "Wider item",
                        "role": "text",
                        "bbox": {"x": 100, "y": 80, "w": 101, "h": 40},
                    }
                ],
            }
        ],
        screen_size={"width": 500, "height": 300},
    )

    item = next(node for node in graph["nodes"] if node.get("source_ref") == "wider_item")
    assert item["parent_id"] == "uih:structure:main"
    assert item["bbox"] == {"x": 100, "y": 80, "w": 101, "h": 40}
    assert graph["validation"]["clipped_node_count"] == 0


def test_ui_hierarchy_summarizes_ownership_resolution_audit() -> None:
    graph = build_ui_hierarchy_graph(
        structure_regions=[_structure("main", {"x": 0, "y": 0, "w": 400, "h": 300})],
        numbered_regions=[
            {
                "region_id": "main",
                "bbox": {"x": 0, "y": 0, "w": 400, "h": 300},
                "subregion_groups": [],
                "numbered_items": [],
                "ownership_resolution": {
                    "conflict_count": 7,
                    "ambiguous_tie_count": 1,
                    "needs_human_review": True,
                },
            }
        ],
        screen_size={"width": 400, "height": 300},
    )

    assert graph["summary"]["resolved_ownership_conflict_count"] == 7
    assert graph["summary"]["ambiguous_ownership_tie_count"] == 1
    assert graph["summary"]["ownership_review_required"] is True


def test_ui_hierarchy_rejects_cycles_and_nodes_unreachable_from_screen() -> None:
    graph = build_ui_hierarchy_graph(
        structure_regions=[_structure("main", {"x": 0, "y": 0, "w": 400, "h": 300})],
        numbered_regions=[
            {
                "region_id": "main",
                "bbox": {"x": 0, "y": 0, "w": 400, "h": 300},
                "subregion_groups": [
                    {
                        "group_id": "a",
                        "role": "component_group",
                        "bbox": {"x": 50, "y": 50, "w": 200, "h": 150},
                        "parent_group_id": "b",
                        "member_item_ids": [],
                    },
                    {
                        "group_id": "b",
                        "role": "component_group",
                        "bbox": {"x": 50, "y": 50, "w": 200, "h": 150},
                        "parent_group_id": "a",
                        "member_item_ids": [],
                    },
                ],
                "numbered_items": [],
            }
        ],
        screen_size={"width": 400, "height": 300},
    )

    assert graph["validation"]["passed"] is False
    assert graph["validation"]["cycle_node_count"] == 2
    assert graph["validation"]["unreachable_from_root_count"] == 2


def test_ui_hierarchy_is_deterministic_and_display_only() -> None:
    structure_regions = [_structure("main", {"x": 0, "y": 0, "w": 300, "h": 200})]
    numbered_regions = [{"region_id": "main", "bbox": {"x": 0, "y": 0, "w": 300, "h": 200}, "subregion_groups": [], "numbered_items": []}]

    first = build_ui_hierarchy_graph(
        structure_regions=structure_regions,
        numbered_regions=numbered_regions,
        screen_size={"width": 300, "height": 200},
    )
    second = build_ui_hierarchy_graph(
        structure_regions=structure_regions,
        numbered_regions=numbered_regions,
        screen_size={"width": 300, "height": 200},
    )

    assert first == second
    assert first["contract_version"] == "ui_hierarchy_graph_v1"
    assert first["root_node_id"] == "uih:screen"
    assert first["display_only"] is True
    assert first["execute_binding_enabled"] is False
    assert first["artifact_is_authorization"] is False
    assert first["runtime_pathgraph_promotion"] is False


def test_ui_hierarchy_does_not_restore_suppressed_fusion_group() -> None:
    graph = build_ui_hierarchy_graph(
        structure_regions=[_structure("main", {"x": 0, "y": 0, "w": 300, "h": 200})],
        numbered_regions=[
            {
                "region_id": "main",
                "bbox": {"x": 0, "y": 0, "w": 300, "h": 200},
                "subregion_groups": [
                    {
                        "group_id": "suppressed_group",
                        "role": "media_card_group",
                        "bbox": {"x": 20, "y": 20, "w": 120, "h": 80},
                        "member_item_ids": ["shared_item"],
                        "render_in_main_overlay": False,
                        "candidate_only": True,
                    },
                    {
                        "group_id": "active_group",
                        "role": "section_parent",
                        "bbox": {"x": 100, "y": 20, "w": 160, "h": 100},
                        "member_item_ids": ["shared_item"],
                    },
                ],
                "numbered_items": [
                    {
                        "item_id": "shared_item",
                        "role": "text",
                        "bbox": {"x": 110, "y": 40, "w": 60, "h": 20},
                    }
                ],
            }
        ],
        screen_size={"width": 300, "height": 200},
    )

    by_source = {node.get("source_ref"): node for node in graph["nodes"]}
    assert "suppressed_group" not in by_source
    assert by_source["shared_item"]["parent_id"] == by_source["active_group"]["node_id"]


def test_two_stage_output_attaches_ui_hierarchy() -> None:
    inventory = [
        {
            "item_id": "main_surface",
            "label": "Main surface",
            "role": "content_area",
            "item_type": "section",
            "bbox": {"x": 0, "y": 0, "w": 400, "h": 300},
            "review_only": True,
        }
    ]
    layout_graph = {
        "contract_version": "learn_layout_graph_v1",
        "zones": {"main_content": {"item_ids": ["main_surface"]}},
        "nodes": {"main_surface": inventory[0]},
    }

    result = build_two_stage_screen_understanding(
        bundle={"screen_size": {"width": 400, "height": 300}},
        screen_inventory=inventory,
        layout_graph=layout_graph,
    )

    hierarchy = result["ui_hierarchy"]
    assert hierarchy["contract_version"] == "ui_hierarchy_graph_v1"
    assert hierarchy["summary"]["structure_region_count"] == 1
    assert hierarchy["display_only"] is True
    assert hierarchy["runtime_pathgraph_promotion"] is False
    assert result["learning_draft"]["learning_source"] == "ui_hierarchy_graph_v1"
    assert result["learning_draft"]["page_details"]["ui_hierarchy"] == hierarchy
    assert result["page_details"]["contract_version"] == "learning_draft_page_details_v1"
