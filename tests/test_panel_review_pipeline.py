from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.learn.recognition.panel_review_pipeline import _final_stage2_report


def test_final_stage2_report_rebuilds_readonly_outputs_from_reviewed_control_parents(tmp_path: Path) -> None:
    screenshot = tmp_path / "reviewed-screen.png"
    Image.new("RGB", (640, 420), "white").save(screenshot)
    structure_region = {
        "region_no": 1,
        "region_id": "main",
        "label": "Main",
        "bbox": {"x": 0, "y": 0, "w": 640, "h": 420},
        "coordinate_validation": {"status": "passed", "evidence": "fixture"},
    }
    source_report = {
        "stage1_region_localization": {"regions": [structure_region]},
        "stage2_numbering": {"regions": []},
        "fusion": {"compiled_overlay_path": "stale-before-review.png"},
        "ui_hierarchy": {"contract_version": "stale_hierarchy"},
        "learning_draft": {"contract_version": "stale_draft"},
        "page_details": {"contract_version": "stale_page_details"},
    }
    finalized_stage2 = {
        "contract_version": "learning_review_final_numbering_v1",
        "regions": [
            {
                "region_id": "main",
                "label": "Main",
                "bbox": {"x": 0, "y": 0, "w": 640, "h": 420},
                "subregion_groups": [],
                "control_parents": [
                    {
                        "object_id": "control_parent_row_1",
                        "label": "Conversation row",
                        "role": "atomic_control_parent",
                        "bbox": {"x": 60, "y": 90, "w": 220, "h": 48},
                        "member_object_ids": ["title_1"],
                        "source": "repeated_visual_anchor_with_row_evidence",
                        "review_only": True,
                    }
                ],
                "numbered_items": [
                    {
                        "item_id": "title_1",
                        "label": "Chat title",
                        "role": "text",
                        "bbox": {"x": 112, "y": 100, "w": 120, "h": 20},
                        "source": "ocr",
                    }
                ],
            }
        ],
    }

    report = _final_stage2_report(
        source_report=source_report,
        finalized_stage2=finalized_stage2,
        screenshot_path=screenshot,
        final_overlay_path="final-reviewed-overlay.png",
        finalization={
            "source_graph_revision": "source-revision",
            "reviewed_graph_revision": "reviewed-revision",
            "final_numbering_revision": "final-revision",
            "integrity_gate": {"passed": True},
            "calibration_permission": True,
        },
        model_review_report_path=tmp_path / "model-review.json",
        closure_report_path=tmp_path / "closure.json",
    )

    by_source = {
        node.get("source_ref"): node
        for node in report["ui_hierarchy"]["nodes"]
        if node.get("source_ref")
    }
    assert by_source["title_1"]["parent_id"] == by_source["control_parent_row_1"]["node_id"]
    assert report["learning_draft"]["contract_version"] == "learning_template_draft_v1"
    assert any(
        region.get("source_ref") == "control_parent_row_1"
        for region in report["learning_draft"]["regions"]
    )
    assert report["page_details"] == report["learning_draft"]["page_details"]
    assert report["page_details"]["screen"]["compiled_overlay_path"] == "final-reviewed-overlay.png"
    assert any(
        box.get("box_type") == "control_parent"
        for box in report["fusion"]["fused_review_boxes"]
    )
