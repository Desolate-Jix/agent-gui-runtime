"""日期文本字段契约：显式显示格式，实际字段读回后才确认完成。"""
from datetime import date

import pytest

from test_form_fill import Coordinator, TARGET, text_reader

from app.desktop_review.form_fill import FormFillRequest, run_form_fill


DATE = {"kind": "date", "field_goal": "Date of birth", "value": "2024-02-29",
    "format": "YYYY-MM-DD"}


@pytest.mark.parametrize("value", ["2023-02-29", "2024-02-30", "2024-13-01",
    "2024-00-01", "2024-01-00", "2024-1-02", "24-01-02", "2024/01/02",
    "2024-01-02T00:00:00", "", 20240102, None, True])
def test_invalid_iso_dates_rejected_before_any_input(value):
    co = Coordinator()
    with pytest.raises(ValueError):
        run_form_fill(co, TARGET, {"fields": [{**DATE, "value": value}]})
    assert co.calls == []


@pytest.mark.parametrize("field", [
    {key: value for key, value in DATE.items() if key != "format"},
    {**DATE, "format": "localized"},
    {**DATE, "format": None},
    {**DATE, "field_goal": 123},
    {**DATE, "field_goal": "  "},
    {**DATE, "submit_search": True},
    {**DATE, "clear_existing": False},
    {**DATE, "text": "2024-02-29"},
])
def test_date_request_rejects_missing_format_extra_keys_and_wrong_types_before_input(field):
    co = Coordinator()
    with pytest.raises(ValueError):
        run_form_fill(co, TARGET, {"fields": [field]})
    assert co.calls == []


@pytest.mark.parametrize("display_format,display_text", [
    ("YYYY-MM-DD", "2024-02-29"),
    ("DD/MM/YYYY", "29/02/2024"),
    ("MM/DD/YYYY", "02/29/2024"),
])
def test_date_formats_text_via_verified_input_sequence(monkeypatch, display_format, display_text):
    co = Coordinator()
    text_reader(monkeypatch, "old", display_text)
    result = run_form_fill(co, TARGET, {"fields": [{**DATE, "format": display_format}]})
    row = result["fields"][0]
    assert result["status"] == "completed"
    assert row["kind"] == "date" and row["status"] == "completed"
    assert row["check"]["status"] == "matched"
    assert row["check"]["value"] == "2024-02-29"
    assert row["check"]["display_format"] == display_format
    assert row["check"]["display_text"] == display_text
    assert [call["operation"] for call in co.calls] == ["execute_recognition_plan", "type_text"]
    assert co.calls[1]["request"]["text"] == display_text
    assert co.calls[1]["request"]["clear_existing"] is True
    assert all(call["operation"] != "press_key" for call in co.calls)
    assert row["input_sequence"]["submit_search"] is False


def test_date_readback_mismatch_interrupts_without_date_success_or_later_field(monkeypatch):
    co = Coordinator()
    text_reader(monkeypatch, "", "29/02/2025")
    result = run_form_fill(co, TARGET, {"fields": [
        {**DATE, "format": "DD/MM/YYYY"},
        {"kind": "text", "field_goal": "Name", "text": "Ada"},
    ]})
    assert result["status"] == "interrupted" and result["interrupted_at"] == 0
    assert result["completed_fields"] == [] and len(result["fields"]) == 1
    row = result["fields"][0]
    assert row["kind"] == "date" and row["check"]["status"] == "mismatch"
    assert "value" not in row["check"] and "display_format" not in row["check"]
    assert [call["operation"] for call in co.calls] == ["execute_recognition_plan", "type_text"]
    assert result["automatic_retry_allowed"] is False


def test_date_dispatch_interruption_preserves_partial_receipts_without_final_submit(monkeypatch):
    co = Coordinator(fail_at=2)
    text_reader(monkeypatch, "")
    result = run_form_fill(co, TARGET, {"fields": [DATE]})
    assert result["status"] == "interrupted" and result["completed_fields"] == []
    assert result["fields"][0]["check"]["status"] != "matched"
    assert result["fields"][0]["steps"][-1]["status"] == "result_unknown"
    assert result["action_executed"] is True
    assert [call["operation"] for call in co.calls] == ["execute_recognition_plan", "type_text"]
    assert result["automatic_retry_allowed"] is False


def test_leap_date_is_valid_in_contract():
    spec = FormFillRequest.model_validate({"fields": [DATE]})
    assert spec.fields[0].value == date(2024, 2, 29).isoformat()
