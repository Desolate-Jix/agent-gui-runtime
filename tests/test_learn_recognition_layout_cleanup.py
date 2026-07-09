from app.learn.recognition.contracts import build_inventory_item
from app.learn.recognition.layout_cleanup import resolve_inventory_layout


def test_layout_cleanup_merges_duplicate_targets_and_preserves_sources():
    items = [
        build_inventory_item(
            item_id="vision_search",
            label="Search",
            item_type="actionable",
            role="button",
            bbox={"x": 100, "y": 100, "w": 80, "h": 32},
            source_evidence=["vision"],
            evidence_level="semantic_region_only",
        ),
        build_inventory_item(
            item_id="uia_search",
            label="Search",
            item_type="actionable",
            role="button",
            bbox={"x": 102, "y": 101, "w": 78, "h": 31},
            source_evidence=["uia"],
            evidence_level="uia_control",
            interactable_evidence={"uia_invokable": True},
        ),
    ]

    report = resolve_inventory_layout(items)

    assert report["input_count"] == 2
    assert report["output_count"] == 1
    assert report["duplicates_merged"] == 1
    assert report["suppression_reason_counts"] == {"duplicate_or_same_target": 1}
    assert report["metrics"]["overlap_reduction"]["after"] == 0
    kept = report["cleaned_items"][0]
    assert kept["item_id"] == "uia_search"
    assert kept["source_evidence"] == ["uia", "vision"]
    assert kept["interactable_evidence"]["uia_invokable"] is True
    assert kept["metadata"]["layout_cleanup"]["status"] == "merged_duplicate"
    assert report["suppressed_items"][0]["reason"] == "duplicate_or_same_target"


def test_layout_cleanup_suppresses_large_semantic_container_over_child_action():
    items = [
        build_inventory_item(
            item_id="hero_container",
            label="Hero search area",
            item_type="layout",
            role="section",
            bbox={"x": 0, "y": 0, "w": 500, "h": 300},
            source_evidence=["vision"],
            evidence_level="semantic_region_only",
        ),
        build_inventory_item(
            item_id="search_button",
            label="Search",
            item_type="actionable",
            role="button",
            bbox={"x": 400, "y": 240, "w": 70, "h": 36},
            source_evidence=["uia"],
            evidence_level="uia_control",
            interactable_evidence={"uia_invokable": True},
        ),
    ]

    report = resolve_inventory_layout(items)

    assert [item["item_id"] for item in report["cleaned_items"]] == ["search_button"]
    assert report["suppressed_items"][0]["item_id"] == "hero_container"
    assert report["suppressed_items"][0]["reason"] == "semantic_container_overlaps_interactable_children"
    assert report["suppression_reason_counts"] == {"semantic_container_overlaps_interactable_children": 1}
    assert report["metrics"]["layout_cleanup_applied"]["interpretation"].startswith("候选框清理已运行")


def test_layout_cleanup_merges_cross_evidence_support_duplicate():
    items = [
        build_inventory_item(
            item_id="vision_search_input",
            label="Search input",
            item_type="form_field",
            role="input",
            bbox={"x": 1432, "y": 89, "w": 246, "h": 25},
            source_evidence=["vision", "calibrated_target"],
            evidence_level="cross_evidence_grounded",
            metadata={
                "source": "vision",
                "cross_evidence": {
                    "support_item_id": "reviewed_search_input",
                    "support_label": "Search input",
                    "support_sources": ["calibrated_target"],
                    "iou": 0.6045,
                },
            },
        ),
        build_inventory_item(
            item_id="reviewed_search_input",
            label="Search input",
            item_type="form_field",
            role="input",
            bbox={"x": 1454, "y": 90, "w": 222, "h": 36},
            source_evidence=["calibrated_target"],
            evidence_level="calibrated_target",
            interactable_evidence={"calibrated_target_validated": True},
            metadata={
                "source": "calibrated_target",
                "click_point": {"x": 1565.0, "y": 108.0},
                "coordinate_validation": {"status": "valid"},
            },
        ),
    ]

    report = resolve_inventory_layout(items)

    assert report["input_count"] == 2
    assert report["output_count"] == 1
    assert report["duplicates_merged"] == 1
    assert report["suppression_reason_counts"] == {"cross_evidence_support_duplicate": 1}
    assert report["suppressed_items"][0]["reason"] == "cross_evidence_support_duplicate"
    assert report["metrics"]["cross_evidence_support_duplicate_merge"]["passed"] == 1
    assert report["metrics"]["cross_evidence_support_duplicate_merge"]["attempted"] == 1
    assert report["metrics"]["cross_evidence_support_duplicate_merge"]["rate"] == 1.0
    kept = report["cleaned_items"][0]
    assert kept["item_id"] == "vision_search_input"
    assert kept["source_evidence"] == ["calibrated_target", "vision"]
    assert kept["interactable_evidence"]["calibrated_target_validated"] is True
    cleanup = kept["metadata"]["layout_cleanup"]
    assert cleanup["status"] == "merged_duplicate"
    assert cleanup["merged_support"]["item_id"] == "reviewed_search_input"
    assert cleanup["merged_support"]["click_point"] == {"x": 1565.0, "y": 108.0}
    assert cleanup["merged_support"]["coordinate_validation"] == {"status": "valid"}


def test_layout_cleanup_preserves_standalone_calibrated_target():
    items = [
        build_inventory_item(
            item_id="reviewed_search_input",
            label="Search input",
            item_type="form_field",
            role="input",
            bbox={"x": 1454, "y": 90, "w": 222, "h": 36},
            source_evidence=["calibrated_target"],
            evidence_level="calibrated_target",
            interactable_evidence={"calibrated_target_validated": True},
        )
    ]

    report = resolve_inventory_layout(items)

    assert report["output_count"] == 1
    assert report["suppressed_count"] == 0
    assert report["suppression_reason_counts"] == {}
    assert report["metrics"]["cross_evidence_support_duplicate_merge"]["rate"] == "not_covered"
    assert report["cleaned_items"][0]["item_id"] == "reviewed_search_input"
