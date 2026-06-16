from __future__ import annotations

from app.screen_inventory import build_screen_inventory


def test_screen_inventory_splits_actions_text_and_cards() -> None:
    screen_reading = {
        "contract_version": "screen_reading_v1",
        "texts": [
            {"id": "text_pay", "text": "Pay", "bbox": {"x": 40, "y": 250, "w": 42, "h": 20}, "confidence": 0.97},
            {"id": "text_date", "text": "Date", "bbox": {"x": 520, "y": 250, "w": 50, "h": 20}, "confidence": 0.96},
            {"id": "text_posted", "text": "Posted 3 days ago", "bbox": {"x": 380, "y": 430, "w": 150, "h": 18}, "confidence": 0.94},
            {"id": "text_salary", "text": "$120k - $140k", "bbox": {"x": 380, "y": 455, "w": 140, "h": 18}, "confidence": 0.92},
        ],
        "ui_elements": [
            {
                "id": "filter_pay",
                "type": "button",
                "role_guess": "button",
                "label": "Pay",
                "bbox": {"x": 32, "y": 238, "w": 92, "h": 44},
                "click_point": {"x": 78, "y": 260},
                "confidence": 0.78,
                "coordinate_confidence": "medium",
                "interaction_type": "click",
                "evidence": {"interaction_policy": {"allowed": True}},
            },
            {
                "id": "filter_date",
                "type": "button",
                "role_guess": "button",
                "label": "Date",
                "bbox": {"x": 510, "y": 238, "w": 108, "h": 44},
                "click_point": {"x": 564, "y": 260},
                "confidence": 0.77,
                "coordinate_confidence": "medium",
                "interaction_type": "click",
                "evidence": {"interaction_policy": {"allowed": True}},
            },
            {
                "id": "job_card_1",
                "type": "card",
                "role_guess": "card",
                "label": "Senior Product Designer",
                "bbox": {"x": 340, "y": 360, "w": 520, "h": 160},
                "click_point": {"x": 600, "y": 430},
                "confidence": 0.74,
                "coordinate_confidence": "medium",
                "interaction_type": "click",
                "evidence": {"interaction_policy": {"allowed": True}},
            },
        ],
        "source_layers": {
            "windows_uia": {
                "status": "ok",
                "control_count": 2,
                "controls": [
                    {
                        "control_id": "uia_apply",
                        "name": "Apply",
                        "control_type": "Button",
                        "bbox": {"x": 760, "y": 468, "w": 80, "h": 32},
                        "enabled": True,
                        "visible": True,
                        "patterns": ["Invoke"],
                    },
                    {
                        "control_id": "uia_save",
                        "name": "Save",
                        "control_type": "Button",
                        "bbox": {"x": 660, "y": 468, "w": 80, "h": 32},
                        "enabled": True,
                        "visible": True,
                        "patterns": ["Invoke"],
                    },
                ],
            }
        },
    }

    inventory = build_screen_inventory(screen_reading, goal="click Apply")

    labels = {item["label"] for item in inventory["available_actions"]}
    assert {"Pay", "Date", "Senior Product Designer", "Apply", "Save"} <= labels
    assert any(item["metadata"]["semantic_hint"] == "posted" for item in inventory["page_elements"])
    assert any(item["metadata"]["semantic_hint"] == "salary" for item in inventory["page_elements"])
    assert inventory["summary"]["card_count"] == 1
    card = inventory["cards"][0]
    assert card["label"] == "Senior Product Designer"
    assert len(card["child_action_ids"]) == 2
    assert len(card["child_page_element_ids"]) == 2
    assert inventory["quality"]["coordinate_coverage"] == 1.0
