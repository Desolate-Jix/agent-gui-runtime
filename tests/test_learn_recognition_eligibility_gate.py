from app.learn.recognition.eligibility import (
    apply_grounding_eligibility_gate,
    summarize_grounding_eligibility,
)


def test_eligibility_gate_blocks_semantic_and_ocr_only_items_from_grounding():
    gated = apply_grounding_eligibility_gate(
        [
            {
                "item_id": "hero",
                "label": "Hero search area",
                "item_type": "layout",
                "role": "section",
                "source_evidence": ["vision"],
                "evidence_level": "semantic_region_only",
                "interactable_evidence": {},
            },
            {
                "item_id": "title",
                "label": "Latest News",
                "item_type": "readable",
                "role": "text",
                "source_evidence": ["ocr"],
                "evidence_level": "ocr_text_only",
                "interactable_evidence": {},
            },
        ]
    )

    assert [item["grounding_eligible"] for item in gated] == [False, False]
    assert [item["review_only"] for item in gated] == [True, True]
    assert [item["eligible_for"] for item in gated] == [[], []]
    assert gated[0]["evidence_strength"] == "semantic_only"
    assert gated[0]["grounding_block_reason"] == "semantic_region_only_without_interactable_evidence"
    assert gated[1]["evidence_strength"] == "ocr_text_anchor_only"
    assert gated[1]["grounding_block_reason"] == "ocr_text_only_without_interactable_evidence"


def test_eligibility_gate_allows_interactable_actions_but_not_as_authorization():
    gated = apply_grounding_eligibility_gate(
        [
            {
                "item_id": "search",
                "label": "Search",
                "item_type": "actionable",
                "role": "button",
                "source_evidence": ["uia"],
                "evidence_level": "uia_control",
                "interactable_evidence": {"uia_invokable": True},
            },
            {
                "item_id": "cover_letter",
                "label": "Cover letter",
                "item_type": "form_field",
                "role": "input",
                "source_evidence": ["omniparser"],
                "evidence_level": "omniparser_element",
                "interactable_evidence": {"omniparser_interactable": True},
            },
        ]
    )

    assert [item["grounding_eligible"] for item in gated] == [True, True]
    assert [item["review_only"] for item in gated] == [False, False]
    assert gated[0]["evidence_strength"] == "single_interactable_source"
    assert gated[0]["eligible_for"] == ["roi_grounding"]
    assert gated[0]["artifact_is_authorization"] is False
    assert gated[0]["execute_binding_enabled"] is False
    assert gated[0]["real_action_requires_gate"] is True
    assert gated[1]["evidence_strength"] == "single_interactable_source"


def test_eligibility_gate_marks_multi_source_and_calibrated_strength():
    gated = apply_grounding_eligibility_gate(
        [
            {
                "item_id": "search_input",
                "label": "Search keyword field",
                "item_type": "form_field",
                "role": "input",
                "source_evidence": ["vision", "uia"],
                "evidence_level": "cross_evidence_grounded",
                "interactable_evidence": {"uia_value_pattern": True, "cross_evidence_overlap": True},
            },
            {
                "item_id": "download",
                "label": "Download",
                "item_type": "actionable",
                "role": "button",
                "source_evidence": ["calibrated_target"],
                "evidence_level": "calibrated_target",
                "interactable_evidence": {"calibrated_target_validated": True},
            },
        ]
    )

    assert gated[0]["evidence_strength"] == "multi_source_interactable"
    assert gated[0]["grounding_eligible"] is True
    assert gated[1]["evidence_strength"] == "human_calibrated_interactable"
    assert gated[1]["grounding_eligible"] is True


def test_eligibility_gate_allows_cross_evidence_job_card_for_open_detail_review():
    gated = apply_grounding_eligibility_gate(
        [
            {
                "item_id": "c4",
                "label": "Job listing card",
                "item_type": "layout",
                "role": "card",
                "source_evidence": ["vision", "calibrated_target"],
                "evidence_level": "cross_evidence_grounded",
                "interactable_evidence": {
                    "calibrated_target_validated": True,
                    "cross_evidence_overlap": True,
                },
                "metadata": {
                    "description": "Job card for Software Engineer Specialist - Integration at AIA New Zealand",
                    "text_lines": ["Software Engineer Specialist - Integration", "AIA New Zealand"],
                },
            }
        ]
    )

    item = gated[0]
    assert item["grounding_eligible"] is True
    assert item["review_only"] is False
    assert item["eligible_for"] == ["roi_grounding"]
    assert item["evidence_strength"] == "human_calibrated_interactable"
    assert item["execute_binding_enabled"] is False
    summary = summarize_grounding_eligibility(gated)
    assert summary["non_actionable_leaked_to_grounding"]["leaked_count"] == 0


def test_eligibility_gate_blocks_calibrated_text_and_group_without_direct_action_evidence():
    gated = apply_grounding_eligibility_gate(
        [
            {
                "item_id": "page_title",
                "label": "WhatsApp",
                "item_type": "actionable",
                "role": "text",
                "source_evidence": ["vision", "calibrated_target"],
                "evidence_level": "cross_evidence_grounded",
                "interactable_evidence": {
                    "calibrated_target_validated": True,
                    "cross_evidence_overlap": True,
                },
            },
            {
                "item_id": "container_group",
                "label": "group",
                "item_type": "actionable",
                "role": "group",
                "source_evidence": ["calibrated_target"],
                "evidence_level": "calibrated_target",
                "interactable_evidence": {
                    "calibrated_target_validated": True,
                },
            },
        ]
    )

    assert [item["grounding_eligible"] for item in gated] == [False, False]
    assert [item["review_only"] for item in gated] == [True, True]
    assert {item["grounding_block_reason"] for item in gated} == {
        "non_actionable_role_without_direct_interactable_evidence"
    }
    summary = summarize_grounding_eligibility(gated)
    assert summary["non_actionable_leaked_to_grounding"]["leaked_count"] == 0


def test_eligibility_gate_allows_directly_invokable_text_without_reporting_a_leak():
    gated = apply_grounding_eligibility_gate(
        [
            {
                "item_id": "direct_text_control",
                "label": "Chat",
                "item_type": "actionable",
                "role": "text",
                "source_evidence": ["uia"],
                "evidence_level": "uia_control",
                "interactable_evidence": {"uia_invokable": True},
            }
        ]
    )

    assert gated[0]["grounding_eligible"] is True
    summary = summarize_grounding_eligibility(gated)
    assert summary["non_actionable_leaked_to_grounding"]["leaked_count"] == 0


def test_eligibility_summary_reports_non_actionable_leakage_metrics():
    gated = apply_grounding_eligibility_gate(
        [
            {
                "item_id": "body_text",
                "label": "Python lets you work quickly",
                "item_type": "readable",
                "role": "text",
                "source_evidence": ["ocr"],
                "evidence_level": "ocr_text_only",
            },
            {
                "item_id": "search",
                "label": "Search",
                "item_type": "actionable",
                "role": "button",
                "source_evidence": ["uia"],
                "interactable_evidence": {"uia_invokable": True},
            },
        ]
    )

    summary = summarize_grounding_eligibility(gated)

    assert summary["evaluation_scope"] == "learn_mode_grounding_eligibility_gate"
    assert summary["execution_scope"] == "no_action_no_execute_no_live_click"
    assert summary["not_accuracy"] is True
    assert summary["not_e2e_success"] is True
    assert summary["not_execute_mode_default"] is True
    assert summary["grounding_eligibility"] == {"attempted": 2, "eligible": 1, "blocked": 1}
    assert summary["ocr_only_rejection"] == {"passed": 1, "attempted": 1, "rate": 1.0}
    assert summary["non_actionable_leaked_to_grounding"]["leaked_count"] == 0
    assert summary["non_actionable_leaked_to_grounding"]["passed"] == 1
    assert summary["grounding_eligible_breakdown"]["uia_interactable"] == 1


def test_eligibility_gate_blocks_browser_chrome_controls_from_page_grounding():
    gated = apply_grounding_eligibility_gate(
        [
            {
                "item_id": "address_bar",
                "label": "Address and search bar",
                "item_type": "form_field",
                "role": "address_bar",
                "bbox": {"x": 92, "y": 48, "w": 700, "h": 34},
                "source_evidence": ["uia"],
                "evidence_level": "uia_control",
                "interactable_evidence": {"uia_value_pattern": True},
                "metadata": {"surface_zone": "browser_chrome"},
            }
        ]
    )

    item = gated[0]
    assert item["grounding_eligible"] is False
    assert item["review_only"] is True
    assert item["surface_zone"] == "browser_chrome"
    assert item["grounding_block_reason"] == "browser_chrome_not_page_surface"
    assert item["eligible_for"] == []


def test_eligibility_gate_marks_overlapping_distinct_targets_as_split_roi_required():
    gated = apply_grounding_eligibility_gate(
        [
            {
                "item_id": "get_started",
                "label": "Get Started",
                "item_type": "actionable",
                "role": "button",
                "bbox": {"x": 100, "y": 200, "w": 180, "h": 64},
                "source_evidence": ["uia"],
                "interactable_evidence": {"uia_invokable": True},
            },
            {
                "item_id": "download",
                "label": "Download",
                "item_type": "actionable",
                "role": "button",
                "bbox": {"x": 150, "y": 200, "w": 180, "h": 64},
                "source_evidence": ["uia"],
                "interactable_evidence": {"uia_invokable": True},
            },
        ]
    )

    assert [item["grounding_eligible"] for item in gated] == [True, True]
    assert all(item["roi_diagnostic"]["split_roi_required"] is True for item in gated)
    assert {item["roi_diagnostic"]["split_roi_reason"] for item in gated} == {"overlapping_distinct_grounding_targets"}
    summary = summarize_grounding_eligibility(gated)
    assert summary["split_roi_required"]["attempted"] == 2
    assert summary["split_roi_required"]["count"] == 2
