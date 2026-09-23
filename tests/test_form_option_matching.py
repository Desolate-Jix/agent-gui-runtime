"""真实 Gender 选项大小写差异与整批容量回归。"""
import pytest

from app.desktop_review.form_fill import run_form_fill, FormFillRequest
from test_form_fill import Coordinator, control, option, reader, TARGET, CHECK


@pytest.mark.parametrize("requested", ["Prefer not to say", " Prefer  Not To Say "])
def test_observed_gender_option_resolves_unique_case_space_variant(monkeypatch, requested):
    before = control(kind="dropdown", label="Gender", value="Select..")
    visible = option("Prefer Not To Say")
    reader(monkeypatch, before, {**before, "expanded": True, "options": [visible]},
        {**before, "value": "Prefer Not To Say"})
    co = Coordinator()
    result = run_form_fill(co, TARGET, {"fields": [{"kind": "dropdown", "label": "Gender", "option": requested}]})
    assert result["status"] == "completed", result
    assert len(co.calls) == 2
    assert '"Prefer Not To Say"' in co.calls[1]["request"]["goal"]
    assert result["fields"][0]["option_match"]["resolved"] == "Prefer Not To Say"


def test_casefold_collision_is_ambiguous_not_first_match(monkeypatch):
    before = control(kind="dropdown", label="Gender", value="Select..", expanded=True,
        options=[option("Prefer Not To Say"), {**option("PREFER NOT TO SAY"), "runtime_id": [2]}])
    reader(monkeypatch, before)
    co = Coordinator()
    result = run_form_fill(co, TARGET, {"fields": [{"kind": "dropdown", "label": "Gender", "option": "prefer not to say"}]})
    assert result["error"]["code"] == "form_option_ambiguous"
    assert not co.calls


def test_whole_form_32_fields_allowed_and_33_rejected_before_dispatch():
    assert len(FormFillRequest.model_validate({"fields": [CHECK]*32}).fields) == 32
    with pytest.raises(ValueError):
        FormFillRequest.model_validate({"fields": [CHECK]*33})


def test_large_batch_returns_one_summary_and_partial_failure_indexes(monkeypatch):
    from app.instant_receipt import compact_receipt
    from test_form_fill import ReadError
    reader(monkeypatch, *([control(checked=True)] * 20), ReadError("form_control_not_found"))
    result = run_form_fill(Coordinator(), TARGET, {"fields": [CHECK]*28})
    receipt = compact_receipt({"request_id": "whole-form", "result": result})["form"]
    assert receipt["requested_fields"] == 28
    assert receipt["completed_fields"] == list(range(20))
    assert receipt["remaining_fields"] == list(range(20,28))
    assert receipt["interrupted_at"] == 20
    assert len(receipt["fields"]) == 21
