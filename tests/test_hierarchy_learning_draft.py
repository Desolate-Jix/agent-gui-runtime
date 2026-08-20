from __future__ import annotations

import json
from pathlib import Path

from app.learn.draft_review import load_learning_draft_review
from app.learn.hierarchy_draft import build_hierarchy_learning_draft


def _hierarchy() -> dict:
    return {
        "contract_version": "ui_hierarchy_graph_v1",
        "root_node_id": "uih:screen",
        "nodes": [
            {
                "node_id": "uih:screen",
                "level": "screen",
                "component_type": "screen",
                "label": "Screen",
                "bbox": {"x": 0, "y": 0, "w": 800, "h": 600},
                "parent_id": "",
                "children": ["uih:structure:main"],
                "source_ref": "screen",
                "review_status": "review_only",
            },
            {
                "node_id": "uih:structure:main",
                "level": "structure_region",
                "component_type": "main_content",
                "label": "Main content",
                "bbox": {"x": 0, "y": 80, "w": 800, "h": 520},
                "parent_id": "uih:screen",
                "children": ["uih:group:news"],
                "source_ref": "main",
                "review_status": "review_only",
            },
            {
                "node_id": "uih:group:news",
                "level": "section",
                "component_type": "section_parent",
                "label": "Latest news",
                "bbox": {"x": 80, "y": 140, "w": 640, "h": 300},
                "parent_id": "uih:structure:main",
                "children": ["uih:item:title"],
                "source_ref": "news",
                "review_status": "review_only",
            },
            {
                "node_id": "uih:item:title",
                "level": "content",
                "component_type": "text",
                "label": "Release title",
                "bbox": {"x": 100, "y": 180, "w": 220, "h": 24},
                "parent_id": "uih:group:news",
                "children": [],
                "source_ref": "title",
                "review_status": "review_only",
            },
        ],
        "edges": [],
        "summary": {"node_count": 4, "structure_region_count": 1},
        "validation": {
            "passed": True,
            "orphan_node_count": 0,
            "child_outside_parent_count": 0,
            "duplicate_primary_owner_count": 0,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "runtime_pathgraph_promotion": False,
    }


def test_build_hierarchy_learning_draft_preserves_parentage_and_page_details() -> None:
    draft = build_hierarchy_learning_draft(
        ui_hierarchy=_hierarchy(),
        source_image_path="artifacts/screenshots/example.png",
        compiled_overlay_path="artifacts/review-overlays/example.png",
    )

    assert draft["contract_version"] == "learning_template_draft_v1"
    assert draft["learning_source"] == "ui_hierarchy_graph_v1"
    assert len(draft["states"]) == 1
    assert draft["action_templates"] == []
    by_id = {region["region_id"]: region for region in draft["regions"]}
    assert by_id["uih:group:news"]["parent_region_id"] == "uih:structure:main"
    assert by_id["uih:item:title"]["parent_region_id"] == "uih:group:news"
    assert draft["page_details"]["ui_hierarchy"]["contract_version"] == "ui_hierarchy_graph_v1"
    assert draft["page_details"]["inventory_summary"]["content_count"] == 1
    assert draft["safety"]["runtime_pathgraph_promotion"] is False


def test_learning_draft_review_preserves_ui_hierarchy(tmp_path: Path) -> None:
    draft = build_hierarchy_learning_draft(
        ui_hierarchy=_hierarchy(),
        source_image_path="artifacts/screenshots/example.png",
        compiled_overlay_path="artifacts/review-overlays/example.png",
    )
    source = tmp_path / "logs" / "two_stage_with_draft.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps({"contract_version": "learn_two_stage_screen_understanding_v1", "learning_draft": draft}),
        encoding="utf-8",
    )

    review = load_learning_draft_review(source, project_root=tmp_path)

    assert review["draft"]["ui_hierarchy"]["contract_version"] == "ui_hierarchy_graph_v1"
    assert review["draft"]["page_details"]["ui_hierarchy"]["validation"]["passed"] is True
    assert review["screen_understanding_preview"]["source_status"] == "available"
    assert (
        review["screen_understanding_preview"]["compiled_overlay_path"]
        == "artifacts/review-overlays/example.png"
    )
    assert (
        review["screen_understanding_preview"]["source_image_path"]
        == "artifacts/screenshots/example.png"
    )
    assert review["execute_binding_enabled"] is False
