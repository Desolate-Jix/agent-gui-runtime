from app.learn.recognition.validator import validate_grounding_candidate


def test_rejects_point_outside_bbox():
    result = validate_grounding_candidate(
        item={"item_id": "search", "item_type": "actionable", "bbox": {"x": 10, "y": 10, "w": 100, "h": 30}},
        grounding={"screen_point": {"x": 200, "y": 20}, "screen_bbox": {"x": 10, "y": 10, "w": 100, "h": 30}},
        evidence={"screenshot_freshness": True, "coordinate_transform_replay": True},
    )

    assert result["contract_version"] == "learning_grounding_validation_v1"
    assert result["status"] == "rejected"
    assert result["failure_category"] == "point_outside_bbox"


def test_rejects_missing_grounding_point_even_when_bbox_contains_origin():
    result = validate_grounding_candidate(
        item={"item_id": "top_left", "item_type": "actionable", "bbox": {"x": 0, "y": 0, "w": 68, "h": 46}},
        grounding={"screen_bbox": {"x": 0, "y": 0, "w": 68, "h": 46}},
        evidence={"screenshot_freshness": True, "coordinate_transform_replay": True},
    )

    assert result["status"] == "rejected"
    assert result["failure_category"] == "missing_grounding_point"
    assert result["checks"]["point_present"] is False


def test_danger_zone_never_becomes_valid_action():
    result = validate_grounding_candidate(
        item={
            "item_id": "submit",
            "item_type": "danger_zone",
            "label": "Submit application",
            "bbox": {"x": 1, "y": 1, "w": 120, "h": 40},
        },
        grounding={"screen_point": {"x": 50, "y": 20}, "screen_bbox": {"x": 1, "y": 1, "w": 120, "h": 40}},
        evidence={"screenshot_freshness": True, "coordinate_transform_replay": True},
    )

    assert result["status"] == "rejected"
    assert result["failure_category"] == "danger_zone"
    assert result["checks"]["not_danger_zone"] is False


def test_rejects_stale_screenshot_and_missing_transform_replay():
    result = validate_grounding_candidate(
        item={"item_id": "continue", "item_type": "actionable", "bbox": {"x": 10, "y": 10, "w": 100, "h": 30}},
        grounding={"screen_point": {"x": 50, "y": 20}, "screen_bbox": {"x": 10, "y": 10, "w": 100, "h": 30}},
        evidence={"screenshot_freshness": False, "coordinate_transform_replay": False},
    )

    assert result["status"] == "rejected"
    assert result["failure_category"] == "stale_or_unreplayable_evidence"
    assert result["checks"]["screenshot_freshness"] is False
    assert result["checks"]["coordinate_transform_replay"] is False


def test_valid_actionable_grounding_candidate_passes():
    result = validate_grounding_candidate(
        item={
            "item_id": "search",
            "item_type": "actionable",
            "label": "Search",
            "bbox": {"x": 10, "y": 10, "w": 100, "h": 30},
        },
        grounding={"screen_point": {"x": 50, "y": 20}, "screen_bbox": {"x": 10, "y": 10, "w": 100, "h": 30}},
        evidence={
            "screenshot_freshness": True,
            "coordinate_transform_replay": True,
            "uia_or_dom_or_parser_overlap": True,
        },
    )

    assert result["status"] == "valid_candidate"
    assert result["failure_category"] is None
    assert result["checks"]["point_inside_bbox"] is True


def test_cross_evidence_job_card_grounding_candidate_passes_for_open_detail_review():
    result = validate_grounding_candidate(
        item={
            "item_id": "c4",
            "item_type": "actionable",
            "role": "card",
            "label": "Job listing card",
            "bbox": {"x": 656, "y": 518, "w": 470, "h": 378},
            "source_evidence": ["vision", "calibrated_target"],
            "evidence_level": "cross_evidence_grounded",
            "interactable_evidence": {"calibrated_target_validated": True, "cross_evidence_overlap": True},
            "metadata": {
                "description": "Job card for Software Engineer Specialist - Integration at AIA New Zealand",
                "text_lines": ["Software Engineer Specialist - Integration", "AIA New Zealand"],
            },
        },
        grounding={"screen_point": {"x": 723, "y": 584}, "screen_bbox": {"x": 656, "y": 518, "w": 470, "h": 378}},
        evidence={
            "screenshot_freshness": True,
            "coordinate_transform_replay": True,
            "uia_or_dom_or_parser_overlap": True,
        },
    )

    assert result["status"] == "valid_candidate"
    assert result["failure_category"] is None
    assert result["checks"]["not_non_actionable_content"] is True
    assert result["execute_binding_enabled"] is False
