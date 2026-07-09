from app.learn.recognition.stage1_audit import audit_stage1_region_selection


def test_stage1_region_selection_audit_passes_complete_bars():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_top_bar",
                "label": "Top bar",
                "bbox": {"x": 90, "y": 0, "w": 910, "h": 80},
            },
            {
                "region_id": "structure_region_left_sidebar",
                "label": "Left sidebar",
                "bbox": {"x": 0, "y": 0, "w": 90, "h": 800},
            },
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 90, "y": 80, "w": 910, "h": 720},
            },
        ],
        screen_size={"width": 1000, "height": 800},
        overlay_path="overlay.png",
    )

    assert audit["passed"] is True
    assert audit["failure_categories"] == []
    assert audit["overlay_path"] == "overlay.png"


def test_stage1_region_selection_audit_flags_icon_only_sidebar():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_left_sidebar",
                "label": "Left sidebar",
                "bbox": {"x": 0, "y": 0, "w": 32, "h": 800},
            }
        ],
        screen_size={"width": 1000, "height": 800},
    )

    assert audit["passed"] is False
    assert "sidebar_bbox_too_narrow" in audit["failure_categories"]
    assert audit["regions"][0]["status"] == "failed"


def test_stage1_region_selection_audit_flags_overlapping_topbar_and_main_content():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_top_bar",
                "label": "Top bar",
                "bbox": {"x": 0, "y": 0, "w": 1000, "h": 160},
            },
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 80, "y": 90, "w": 920, "h": 710},
            },
        ],
        screen_size={"width": 1000, "height": 800},
    )

    assert audit["passed"] is False
    assert "structure_region_overlap" in audit["failure_categories"]
    assert {region["status"] for region in audit["regions"]} == {"failed"}


def test_stage1_region_selection_audit_requires_adjacent_partition_covering_empty_space():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_left_sidebar",
                "label": "Left navigation",
                "bbox": {"x": 0, "y": 0, "w": 90, "h": 800},
            },
            {
                "region_id": "structure_region_top_bar",
                "label": "Top bar",
                "bbox": {"x": 90, "y": 0, "w": 910, "h": 120},
            },
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 160, "y": 260, "w": 640, "h": 300},
            },
        ],
        screen_size={"width": 1000, "height": 800},
    )

    assert audit["passed"] is False
    assert "main_content_not_adjacent_to_left_boundary" in audit["failure_categories"]
    assert "main_content_not_adjacent_to_top_boundary" in audit["failure_categories"]
    assert "main_content_does_not_cover_right_empty_area" in audit["failure_categories"]
    assert "main_content_does_not_cover_lower_empty_area" in audit["failure_categories"]
