from app.learn.recognition.contracts import (
    build_inventory_item,
    build_learning_template_draft_from_validated_items,
)


def test_inventory_item_defaults_to_non_click_authorization():
    item = build_inventory_item(
        item_id="text_1",
        label="Latest News",
        item_type="readable",
        bbox={"x": 10, "y": 10, "w": 100, "h": 20},
        source_evidence=["ocr"],
        evidence_level="ocr_text_only",
    )

    assert item["contract_version"] == "screen_inventory_item_v2"
    assert item["click_candidate"] is False
    assert item["artifact_is_authorization"] is False
    assert item["source_evidence"] == ["ocr"]


def test_learning_draft_safety_flags_are_non_executable():
    draft = build_learning_template_draft_from_validated_items(
        state_guess="homepage",
        summary="home screen",
        valid_items=[],
        evidence_refs={"screen_inventory_path": "artifacts/x.json"},
    )

    assert draft["contract_version"] == "learning_template_draft_v1"
    assert draft["learning_source"] == "learn_recognition_pipeline_v2"
    assert draft["safety"]["artifact_is_authorization"] is False
    assert draft["safety"]["execute_binding_enabled"] is False
    assert draft["safety"]["final_submit_forbidden"] is True
    assert draft["safety"]["real_action_requires_gate"] is True


def test_learning_draft_marks_job_card_as_open_detail_review_candidate():
    draft = build_learning_template_draft_from_validated_items(
        state_guess="seek_results",
        summary="SEEK result list",
        valid_items=[
            build_inventory_item(
                item_id="c4",
                label="Job listing card: Software Engineer Specialist - Integration",
                item_type="card",
                role="card",
                bbox={"x": 656, "y": 518, "w": 470, "h": 378},
                source_evidence=["vision", "calibrated_target"],
                evidence_level="cross_evidence_grounded",
                metadata={
                    "description": "Job card for Software Engineer Specialist - Integration at AIA New Zealand",
                    "text_lines": [
                        "Software Engineer Specialist - Integration",
                        "AIA New Zealand",
                        "Takapuna, Auckland",
                    ],
                },
            )
        ],
    )

    action = draft["action_templates"][0]
    assert action["semantic_action"] == "open_detail"
    assert action["action_kind"] == "open_detail"
    assert action["low_level_action_type"] == "click"
    assert action["requires_gate"] is True
    assert action["execute_binding_enabled"] is False
    assert action["transition_hint"] == {
        "contract_version": "learn_open_detail_transition_hint_v1",
        "transition_type": "open_detail",
        "source_region_id": "region_1",
        "expected_next_state_role": "detail_view",
        "target_surface": "detail_pane_or_detail_page",
        "requires_post_action_observe": True,
        "candidate_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
