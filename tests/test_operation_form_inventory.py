from __future__ import annotations

from app.operation.form_inventory import build_form_question_inventory


def _bbox(x: int, y: int, w: int, h: int) -> dict[str, int]:
    return {"x": x, "y": y, "w": w, "h": h}


def test_form_inventory_normalizes_field_types_and_final_action() -> None:
    fields = [
        {"id": "first", "label": "First name", "role": "textbox", "bbox": _bbox(20, 40, 220, 36), "capture_id": "cap-1"},
        {"id": "email", "label": "Email", "input_type": "email", "bbox": _bbox(20, 90, 220, 36), "capture_id": "cap-1"},
        {"id": "phone", "label": "Mobile", "input_type": "tel", "bbox": _bbox(20, 140, 220, 36), "capture_id": "cap-1"},
        {"id": "cover", "label": "Cover letter", "role": "textarea", "bbox": _bbox(20, 190, 420, 120), "capture_id": "cap-1"},
        {"id": "visa", "label": "Visa status", "role": "radio", "bbox": _bbox(20, 330, 20, 20), "capture_id": "cap-1"},
        {"id": "relocate", "label": "Relocate", "role": "checkbox", "bbox": _bbox(20, 370, 20, 20), "capture_id": "cap-1"},
        {"id": "city", "label": "City", "role": "combobox", "bbox": _bbox(20, 410, 220, 36), "capture_id": "cap-1"},
        {"id": "resume", "label": "Resume", "input_type": "file", "bbox": _bbox(20, 460, 220, 36), "capture_id": "cap-1"},
        {"id": "locked", "label": "Verified email", "role": "textbox", "disabled": True, "bbox": _bbox(20, 510, 220, 36), "capture_id": "cap-1"},
    ]
    actions = [
        {"id": "continue", "text": "Continue", "role": "button", "bbox": _bbox(20, 570, 120, 40), "capture_id": "cap-1"},
        {"id": "submit", "text": "Submit application", "role": "button", "bbox": _bbox(160, 570, 180, 40), "capture_id": "cap-1"},
    ]

    result = build_form_question_inventory(
        form_state="application_form",
        current_capture_id="cap-1",
        active_scope_bbox=_bbox(0, 0, 600, 700),
        fields=fields,
        actions=actions,
    )

    assert result["contract_version"] == "form_question_inventory_v1"
    assert [field["field_type"] for field in result["fields"]] == [
        "text",
        "email",
        "phone",
        "textarea",
        "radio",
        "checkbox",
        "select",
        "file_upload",
        "text",
    ]
    assert result["fields"][-1]["disabled"] is True
    assert result["fields"][7]["risk_class"] == "unsupported_file_upload"
    assert result["continue_action"]["text"] == "Continue"
    assert result["danger_actions"][0]["action_type"] == "final_action"
    assert result["danger_actions"][0]["risk_class"] == "final_submit"
    assert result["artifact_is_authorization"] is False


def test_form_inventory_assigns_repeated_options_to_their_question() -> None:
    questions = [
        {
            "question_id": "q_visa",
            "question_text": "Do you have a valid visa?",
            "question_group_bbox": _bbox(10, 10, 500, 100),
            "capture_id": "cap-2",
            "control_candidates": [
                {"id": "visa_yes", "label": "Yes", "role": "radio", "bbox": _bbox(30, 60, 60, 24), "capture_id": "cap-2"},
                {"id": "visa_no", "label": "No", "role": "radio", "bbox": _bbox(120, 60, 60, 24), "capture_id": "cap-2"},
                {"id": "relocate_yes", "label": "Yes", "role": "radio", "bbox": _bbox(30, 180, 60, 24), "capture_id": "cap-2"},
            ],
        },
        {
            "question_id": "q_relocate",
            "question_text": "Can you relocate?",
            "question_group_bbox": _bbox(10, 130, 500, 100),
            "capture_id": "cap-2",
            "control_candidates": [
                {"id": "visa_no", "label": "No", "role": "radio", "bbox": _bbox(120, 60, 60, 24), "capture_id": "cap-2"},
                {"id": "relocate_yes", "label": "Yes", "role": "radio", "bbox": _bbox(30, 180, 60, 24), "capture_id": "cap-2"},
                {"id": "relocate_no", "label": "No", "role": "radio", "bbox": _bbox(120, 180, 60, 24), "capture_id": "cap-2"},
            ],
        },
    ]

    result = build_form_question_inventory(
        form_state="screening_questions",
        current_capture_id="cap-2",
        active_scope_bbox=_bbox(0, 0, 600, 300),
        questions=questions,
    )

    by_id = {question["field_id"]: question for question in result["questions"]}
    assert [option["control_id"] for option in by_id["q_visa"]["options"]] == ["visa_yes", "visa_no"]
    assert [option["control_id"] for option in by_id["q_relocate"]["options"]] == ["relocate_yes", "relocate_no"]


def test_form_inventory_excludes_outside_scope_and_invalidates_stale_evidence() -> None:
    result = build_form_question_inventory(
        form_state="modal_form",
        current_capture_id="cap-current",
        active_scope_bbox=_bbox(100, 100, 400, 400),
        fields=[
            {"id": "inside", "label": "City", "role": "textbox", "bbox": _bbox(120, 140, 200, 36), "capture_id": "cap-current"},
            {"id": "outside", "label": "Global search", "role": "textbox", "bbox": _bbox(10, 10, 200, 36), "capture_id": "cap-current"},
            {"id": "stale", "label": "Phone", "role": "textbox", "bbox": _bbox(120, 200, 200, 36), "capture_id": "cap-old"},
            {"id": "missing", "label": "Email", "role": "textbox", "bbox": _bbox(120, 260, 200, 36)},
        ],
        actions=[
            {"id": "global_submit_search", "text": "Submit search", "role": "button", "bbox": _bbox(10, 10, 160, 36), "capture_id": "cap-current"},
        ],
    )

    assert [field["field_id"] for field in result["fields"]] == ["inside"]
    assert result["excluded_outside_scope_count"] == 2
    assert result["danger_actions"] == []
    assert result["continue_action"] is None
    assert {item["field_id"]: item["invalid_reason"] for item in result["invalid_fields"]} == {
        "stale": "stale_capture",
        "missing": "missing_capture_id",
    }
