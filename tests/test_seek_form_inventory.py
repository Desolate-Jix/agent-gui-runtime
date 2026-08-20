from __future__ import annotations

from app.seek.form_inventory import build_seek_form_field_inventory


def test_seek_form_inventory_exports_cover_letter_and_question_fields() -> None:
    flow = {
        "capture_id": "seek-cap-1",
        "current_step": "answer_employer_questions",
        "application_form_inventory": {
            "fields": [
                {
                    "collection": "available_actions",
                    "id": "cover",
                    "text": "Cover letter body",
                    "role": "textarea",
                    "bbox": {"x": 10, "y": 20, "w": 300, "h": 200},
                    "capture_id": "seek-cap-1",
                },
                {"id": "continue", "text": "Continue", "role": "button", "bbox": {"x": 400, "y": 500, "w": 120, "h": 50}, "capture_id": "seek-cap-1"},
                {"id": "submit", "text": "Submit application", "role": "button", "bbox": {"x": 540, "y": 500, "w": 180, "h": 50}, "capture_id": "seek-cap-1"},
            ]
        },
    }
    question_inventory = {
        "contract_version": "employer_question_inventory_v1",
        "questions": [
            {
                "question_id": "q1",
                "question_text": "Country",
                "answer_type": "text_input",
                "question_bbox": {"x": 10, "y": 260, "w": 100, "h": 24},
                "question_group_bbox": {"x": 10, "y": 250, "w": 500, "h": 100},
                "capture_id": "seek-cap-1",
                "control_candidates": [],
            }
        ],
    }

    result = build_seek_form_field_inventory(flow, employer_question_inventory=question_inventory)

    assert result["contract_version"] == "form_question_inventory_v1"
    assert result["form_state"] == "answer_employer_questions"
    assert any(field["field_id"] == "cover_letter" for field in result["fields"])
    assert any(field["field_id"] == "q1" and field["field_type"] == "text" for field in result["fields"])
    assert result["continue_action"]["text"] == "Continue"
    assert result["danger_actions"][0]["text"] == "Submit application"
    assert result["artifact_is_authorization"] is False
