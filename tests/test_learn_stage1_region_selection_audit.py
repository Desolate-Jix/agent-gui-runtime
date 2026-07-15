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


def test_stage1_region_selection_audit_allows_sidebar_ending_at_adjacent_full_width_bottom_panel():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_top_bar",
                "label": "Top bar",
                "bbox": {"x": 0, "y": 0, "w": 800, "h": 109},
            },
            {
                "region_id": "structure_region_left_sidebar",
                "label": "Left sidebar",
                "bbox": {"x": 12, "y": 117, "w": 252, "h": 736},
            },
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 264, "y": 109, "w": 536, "h": 744},
            },
            {
                "region_id": "structure_region_conversation_bottom_panel",
                "label": "Conversation bottom panel",
                "bbox": {"x": 0, "y": 853, "w": 800, "h": 147},
            },
        ],
        screen_size={"width": 800, "height": 1000},
    )

    assert audit["passed"] is True
    assert "sidebar_bbox_too_short" not in audit["failure_categories"]
    sidebar = next(region for region in audit["regions"] if region["region_type"] == "left_sidebar")
    assert "vertical_lane_completed_by_adjacent_bottom_bar" in sidebar["notes"]


def test_stage1_region_selection_audit_still_blocks_short_sidebar_without_bottom_coverage():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_left_sidebar",
                "label": "Left sidebar",
                "bbox": {"x": 0, "y": 100, "w": 120, "h": 650},
            },
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 120, "y": 100, "w": 880, "h": 900},
            },
        ],
        screen_size={"width": 1000, "height": 1000},
    )

    assert audit["passed"] is False
    assert "sidebar_bbox_too_short" in audit["failure_categories"]


def test_stage1_region_selection_audit_blocks_topbar_that_leaves_unassigned_top_gap():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_top_bar",
                "label": "Top bar",
                "bbox": {"x": 0, "y": 122, "w": 1200, "h": 88},
            },
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 0, "y": 210, "w": 1200, "h": 590},
            },
        ],
        screen_size={"width": 1200, "height": 800},
    )

    assert audit["passed"] is False
    assert "top_structure_does_not_cover_screen_origin" in audit["failure_categories"]


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


def test_stage1_region_selection_audit_allows_small_lower_system_border_slack():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_left_sidebar",
                "label": "Left navigation",
                "bbox": {"x": 0, "y": 0, "w": 92, "h": 1005},
            },
            {
                "region_id": "structure_region_top_bar",
                "label": "Top bar",
                "bbox": {"x": 92, "y": 0, "w": 1062, "h": 90},
            },
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 92, "y": 90, "w": 1062, "h": 887},
            },
        ],
        screen_size={"width": 1154, "height": 1005},
    )

    assert audit["passed"] is True
    assert "main_content_does_not_cover_lower_empty_area" not in audit["failure_categories"]
    main_region = next(region for region in audit["regions"] if region["region_type"] == "main_content")
    assert "main_content_lower_edge_within_system_border_tolerance" in main_region["notes"]


def test_stage1_region_selection_audit_passes_applemusic_adjacent_columns_after_repair():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_browser_chrome",
                "label": "Browser chrome",
                "bbox": {"x": 0, "y": 0, "w": 1154, "h": 73},
            },
            {
                "region_id": "structure_region_left_navigation",
                "label": "Left navigation",
                "bbox": {"x": 0, "y": 73, "w": 92, "h": 932},
            },
            {
                "region_id": "structure_region_top_header_area",
                "label": "Top/header area",
                "bbox": {"x": 92, "y": 73, "w": 1062, "h": 119},
            },
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 92, "y": 192, "w": 1062, "h": 813},
            },
        ],
        screen_size={"width": 1154, "height": 1005},
    )

    assert audit["passed"] is True
    assert audit["failure_categories"] == []


def test_stage1_region_selection_audit_blocks_applemusic_old_overlap_and_shrunken_main():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_browser_chrome",
                "label": "Browser chrome",
                "bbox": {"x": 0, "y": 0, "w": 1154, "h": 142},
            },
            {
                "region_id": "structure_region_left_navigation",
                "label": "Left navigation",
                "bbox": {"x": 0, "y": 0, "w": 92, "h": 1005},
            },
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 92, "y": 420, "w": 912, "h": 432},
            },
        ],
        screen_size={"width": 1154, "height": 1005},
    )

    assert audit["passed"] is False
    assert "structure_region_overlap" in audit["failure_categories"]
    assert "main_content_not_adjacent_to_top_boundary" in audit["failure_categories"]
    assert "main_content_does_not_cover_right_empty_area" in audit["failure_categories"]
    assert "main_content_does_not_cover_lower_empty_area" in audit["failure_categories"]


def test_stage1_region_selection_audit_allows_full_main_with_centered_content_column():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 0, "y": 0, "w": 2521, "h": 1300},
                "rough_bbox": {"x": 567, "y": 140, "w": 820, "h": 906},
            }
        ],
        screen_size={"width": 2521, "height": 1300},
    )

    assert audit["passed"] is True
    assert "main_region_too_small" not in audit["failure_categories"]
    main_region = audit["regions"][0]
    assert "main_content_has_centered_rough_content_column" in main_region["notes"]


def test_stage1_region_selection_audit_blocks_full_main_backfilled_from_top_only_items():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 0, "y": 0, "w": 2521, "h": 1300},
                "rough_bbox": {"x": 528, "y": 134, "w": 910, "h": 187},
            }
        ],
        screen_size={"width": 2521, "height": 1300},
    )

    assert audit["passed"] is False
    assert "single_region_undersegmented" in audit["failure_categories"]


def test_stage1_region_selection_audit_still_blocks_small_localized_main_region():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_main_content",
                "label": "Main content",
                "bbox": {"x": 567, "y": 140, "w": 820, "h": 260},
                "rough_bbox": {"x": 567, "y": 140, "w": 820, "h": 260},
            }
        ],
        screen_size={"width": 2521, "height": 1300},
    )

    assert audit["passed"] is False
    assert "main_region_too_small" in audit["failure_categories"]


def test_stage1_region_selection_audit_blocks_unknown_only_structure():
    audit = audit_stage1_region_selection(
        localized_regions=[
            {
                "region_id": "structure_region_unknown",
                "label": "Unknown",
                "bbox": {"x": 560, "y": 140, "w": 820, "h": 900},
                "item_count": 12,
            }
        ],
        screen_size={"width": 2520, "height": 1300},
    )

    assert audit["passed"] is False
    assert "unknown_only_structure" in audit["failure_categories"]
    assert audit["structure_family_coverage"]["recognized_region_count"] == 0
    assert audit["structure_family_coverage"]["status"] == "not_covered"
