from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.main import app


def test_execute_observe_seek_detects_review_and_submit_danger() -> None:
    client = TestClient(app)

    response = client.post(
        "/execute/observe",
        json={
            "app_id": "seek",
            "application_flow_state": {
                "current_step": "review_and_submit",
                "state_type": "final_submit_visible",
                "application_form_inventory": {
                    "fields": [
                        {"id": "review", "text": "Review and submit", "role": "text"},
                        {"id": "submit", "text": "Submit application", "role": "button", "bbox": {"x": 10, "y": 20, "w": 120, "h": 40}},
                    ]
                },
                "evidence": {"texts": ["Review and submit", "Submit application"]},
            },
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["contract_version"] == "execute_observation_v1"
    assert data["page_state"] == "review_before_submit"
    assert data["danger_actions"][0]["text"] == "Submit application"
    assert data["safety_blockers"][0]["kind"] == "final_submit_visible"
    assert data["trace_path"]


def test_execute_verify_diff_returns_changed_bbox(tmp_path: Path) -> None:
    client = TestClient(app)
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    Image.new("RGB", (220, 140), "white").save(before)
    image = Image.new("RGB", (220, 140), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 170, 86), outline="black", fill="white")
    draw.text((52, 55), "Continue", fill="black")
    image.save(after)

    response = client.post(
        "/execute/verify_diff",
        json={
            "before_image": str(before),
            "after_image": str(after),
            "expected_change": "step_changed",
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["contract_version"] == "ui_diff_verification_v1"
    assert data["verification_status"] == "pass"
    assert data["diff_bboxes"]
    assert data["trace_path"]


def test_execute_read_region_batch_merges_ocr_lines() -> None:
    client = TestClient(app)

    response = client.post(
        "/execute/read_region_batch",
        json={
            "target_container_id": "seek:job_detail",
            "target_bbox": {"x": 10, "y": 20, "w": 300, "h": 500},
            "max_captures": 4,
            "captures": [
                {"image_path": "a.png", "ocr_result": {"items": [{"text": "Title"}, {"text": "React"}]}},
                {"image_path": "b.png", "ocr_result": {"items": [{"text": "React"}, {"text": "AI workflow"}]}},
            ],
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["contract_version"] == "read_region_batch_v1"
    assert data["merged_text_lines"] == ["Title", "React", "AI workflow"]
    assert data["unique_line_count"] == 3
    assert data["trace_path"]


def test_execute_form_inventory_seek_exposes_fields_and_danger_actions() -> None:
    client = TestClient(app)

    response = client.post(
        "/execute/form_inventory",
        json={
            "app_id": "seek",
            "application_flow_state": {
                "contract_version": "seek_application_flow_state_v1",
                "current_step": "questionnaire",
                "application_form_inventory": {
                    "fields": [
                        {"id": "cover", "text": "Cover letter", "role": "textarea", "bbox": {"x": 1, "y": 2, "w": 3, "h": 4}},
                    ],
                    "actions": [
                        {"id": "continue", "text": "Continue", "role": "button"},
                        {"id": "submit", "text": "Submit application", "role": "button"},
                    ],
                },
            },
            "employer_question_inventory": {
                "contract_version": "employer_question_inventory_v1",
                "questions": [
                    {
                        "question_id": "q_country",
                        "question_text": "Country",
                        "answer_type": "text",
                        "group_bbox": {"x": 10, "y": 20, "w": 100, "h": 50},
                    }
                ],
            },
        },
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["success"] is True
    data = payload["data"]
    assert data["contract_version"] == "form_field_inventory_v1"
    assert data["form_state"] == "questionnaire"
    assert [field["field_id"] for field in data["fields"]] == ["cover_letter", "q_country"]
    assert data["continue_action"]["text"] == "Continue"
    assert data["danger_actions"][0]["text"] == "Submit application"
    assert data["trace_path"]
