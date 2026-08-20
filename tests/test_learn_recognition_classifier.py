from app.learn.recognition.classifier import classify_inventory_items


def test_rejects_code_block_and_readonly_card():
    report = classify_inventory_items(
        [
            {
                "item_id": "code",
                "label": ">>> print('Hello')",
                "item_type": "readable",
                "role": "text",
                "source_evidence": ["ocr"],
                "evidence_level": "ocr_text_only",
            },
            {
                "item_id": "card",
                "label": "Looking for work",
                "item_type": "readable",
                "role": "card",
                "source_evidence": ["vision"],
                "evidence_level": "semantic_region_only",
            },
        ]
    )

    assert {item["item_id"] for item in report["rejected_non_actionable"]} == {"code", "card"}
    assert report["accepted_for_grounding"] == []


def test_accepts_multi_source_button_for_grounding():
    report = classify_inventory_items(
        [
            {
                "item_id": "search",
                "label": "Search",
                "item_type": "actionable",
                "role": "button",
                "source_evidence": ["ocr", "uia"],
                "interactable_evidence": {"uia_invokable": True},
                "evidence_level": "multi_source_grounded",
            }
        ]
    )

    assert report["accepted_for_grounding"][0]["item_id"] == "search"
    assert report["accepted_for_grounding"][0]["grounding_eligible"] is True
    assert report["accepted_for_grounding"][0]["review_only"] is False


def test_accepts_cross_evidence_job_card_for_open_detail_grounding():
    report = classify_inventory_items(
        [
            {
                "item_id": "c4",
                "label": "Job listing card",
                "item_type": "layout",
                "role": "card",
                "bbox": {"x": 656, "y": 518, "w": 470, "h": 378},
                "source_evidence": ["vision", "calibrated_target"],
                "evidence_level": "cross_evidence_grounded",
                "interactable_evidence": {
                    "calibrated_target_validated": True,
                    "cross_evidence_overlap": True,
                },
                "metadata": {
                    "description": "Job card for Software Engineer Specialist - Integration at AIA New Zealand",
                    "text_lines": [
                        "Software Engineer Specialist - Integration",
                        "AIA New Zealand",
                        "Takapuna, Auckland",
                    ],
                },
            }
        ]
    )

    accepted = report["accepted_for_grounding"][0]
    assert accepted["item_id"] == "c4"
    assert accepted["grounding_eligible"] is True
    assert accepted["classification_decision"]["reason"] == "open_detail_card_with_grounding_evidence"
    assert report["rejected_non_actionable"] == []


def test_rejects_tiny_validated_calibrated_target_as_noise():
    report = classify_inventory_items(
        [
            {
                "item_id": "tiny_validated",
                "label": "Learn More",
                "item_type": "actionable",
                "role": "menu_item",
                "bbox": {"x": 1, "y": 1, "w": 1, "h": 1},
                "source_evidence": ["calibrated_target"],
                "evidence_level": "calibrated_target",
                "interactable_evidence": {"calibrated_target_validated": True},
            }
        ]
    )

    assert report["accepted_for_grounding"] == []
    rejected = report["rejected_non_actionable"][0]
    assert rejected["item_id"] == "tiny_validated"
    assert rejected["grounding_block_reason"] == "tiny_noise_bbox"
    assert rejected["review_only"] is True


def test_semantic_only_region_is_review_only_and_not_grounding_eligible():
    report = classify_inventory_items(
        [
            {
                "item_id": "vision_search",
                "label": "Search",
                "item_type": "layout",
                "role": "input",
                "source_evidence": ["vision"],
                "evidence_level": "semantic_region_only",
                "interactable_evidence": {},
            }
        ]
    )

    rejected = report["rejected_non_actionable"][0]
    assert rejected["label"] == "Search"
    assert rejected["grounding_eligible"] is False
    assert rejected["review_only"] is True
    assert rejected["grounding_block_reason"] == "semantic_region_only_without_interactable_evidence"
    assert report["accepted_for_grounding"] == []
