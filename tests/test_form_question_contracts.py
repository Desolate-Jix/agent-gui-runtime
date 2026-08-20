from __future__ import annotations

from app.agent.form_question_contracts import build_form_question_contract
from app.operation.form_inventory import build_form_question_inventory


def test_question_contract_keeps_semantics_without_historical_geometry() -> None:
    contract = build_form_question_contract(
        {
            "question_id": "contact_email",
            "label": "Email address",
            "field_type": "email",
            "required": True,
            "disabled": False,
            "risk": "ordinary_field",
            "bbox": {"x": 20, "y": 30, "width": 200, "height": 32},
            "capture_id": "capture-current",
            "options": [],
        }
    )

    assert contract == {
        "contract_version": "form_question_contract_v1",
        "question_id": "contact_email",
        "label": "Email address",
        "field_type": "email",
        "required": True,
        "disabled": False,
        "risk": "ordinary_field",
        "options": [],
        "source_capture_id": "capture-current",
    }
    assert "bbox" not in contract


def test_question_contract_normalizes_options_without_coordinates() -> None:
    contract = build_form_question_contract(
        {
            "id": "work_rights",
            "text": "Do you have the right to work in New Zealand?",
            "type": "radio",
            "options": [
                {"id": "yes", "label": "Yes", "bbox": {"x": 1, "y": 2, "width": 3, "height": 4}},
                {"id": "no", "text": "No", "disabled": True},
            ],
        }
    )

    assert contract["question_id"] == "work_rights"
    assert contract["field_type"] == "radio"
    assert contract["options"] == [
        {"option_id": "yes", "label": "Yes", "disabled": False},
        {"option_id": "no", "label": "No", "disabled": True},
    ]
    assert all("bbox" not in option for option in contract["options"])


def test_question_contract_consumes_common_operation_inventory_shape() -> None:
    inventory = build_form_question_inventory(
        form_state="questionnaire",
        current_capture_id="capture-current",
        active_scope_bbox={"x": 0, "y": 0, "w": 500, "h": 500},
        questions=[
            {
                "question_id": "work_rights",
                "question_text": "Do you have the right to work in New Zealand?",
                "answer_type": "radio",
                "question_group_bbox": {"x": 20, "y": 20, "w": 300, "h": 120},
                "capture_id": "capture-current",
                "control_candidates": [
                    {
                        "id": "yes",
                        "text": "Yes",
                        "role": "radio",
                        "bbox": {"x": 30, "y": 80, "w": 40, "h": 20},
                        "capture_id": "capture-current",
                    }
                ],
            }
        ],
    )

    contract = build_form_question_contract(inventory["questions"][0])

    assert contract["question_id"] == "work_rights"
    assert contract["risk"] == "ordinary_question"
    assert contract["source_capture_id"] == "capture-current"
    assert contract["options"] == [
        {"option_id": "yes", "label": "Yes", "disabled": False}
    ]
