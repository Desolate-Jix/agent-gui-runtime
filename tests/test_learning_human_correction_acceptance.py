from __future__ import annotations

from pathlib import Path

from PIL import Image

from scripts.run_learning_human_correction_acceptance import (
    audit_human_correction_acceptance,
    bounded_bbox_adjustment,
)


def test_bounded_bbox_adjustment_changes_geometry_without_leaving_image() -> None:
    adjusted = bounded_bbox_adjustment(
        {"x": 0, "y": 0, "w": 100, "h": 40},
        image_size={"width": 320, "height": 240},
    )

    assert adjusted != {"x": 0, "y": 0, "w": 100, "h": 40}
    assert adjusted["x"] >= 0
    assert adjusted["y"] >= 0
    assert adjusted["x"] + adjusted["w"] <= 320
    assert adjusted["y"] + adjusted["h"] <= 240


def test_human_correction_acceptance_requires_reloaded_geometry_and_same_size_overlay(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (320, 240), "white").save(source)
    Image.new("RGB", (320, 240), "white").save(overlay)
    expected_bbox = {"x": 12, "y": 20, "w": 96, "h": 32}

    audit = audit_human_correction_acceptance(
        source_image_path=source,
        reviewed_overlay_path=overlay,
        target_region_id="region_1",
        expected_bbox=expected_bbox,
        save_result={
            "reviewed_template_candidate_path": "artifacts/reviewed.json",
            "pathgraph_candidate_path": "artifacts/pathgraph.json",
            "human_review_patch_revision": 1,
            "correction_memory": {"status": "candidate", "production_eligible": False},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        reloaded_review={
            "draft": {
                "regions": [{"region_id": "region_1", "bbox": expected_bbox}],
                "page_details": {"compiled_overlay_path": str(overlay)},
            },
            "pathgraph_candidate_review": {"status": "candidate"},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": True,
        },
    )

    assert audit["status"] == "passed"
    assert audit["checks"]["reloaded_bbox_matches"] is True
    assert audit["checks"]["overlay_same_size_as_source"] is True
    assert audit["checks"]["correction_memory_candidate_only"] is True
    assert audit["checks"]["read_only_safety_preserved"] is True


def test_human_correction_acceptance_exposes_overlay_or_geometry_failure(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    overlay = tmp_path / "overlay.png"
    Image.new("RGB", (320, 240), "white").save(source)
    Image.new("RGB", (160, 120), "white").save(overlay)

    audit = audit_human_correction_acceptance(
        source_image_path=source,
        reviewed_overlay_path=overlay,
        target_region_id="region_1",
        expected_bbox={"x": 12, "y": 20, "w": 96, "h": 32},
        save_result={
            "correction_memory": {"status": "active", "production_eligible": True},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        reloaded_review={
            "draft": {"regions": [{"region_id": "region_1", "bbox": {"x": 0, "y": 0, "w": 1, "h": 1}}]},
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": True,
        },
    )

    assert audit["status"] == "failed"
    assert "reloaded_bbox_mismatch" in audit["failure_categories"]
    assert "overlay_size_mismatch" in audit["failure_categories"]
    assert "correction_memory_not_candidate_only" in audit["failure_categories"]
