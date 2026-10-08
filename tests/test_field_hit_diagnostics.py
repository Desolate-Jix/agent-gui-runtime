"""字段拒绝诊断保留定位证据，不触碰私有字段内容。"""
import json
from types import SimpleNamespace

import pytest

from app.agent import windows_text_field_reader as reader


class _Info:
    control_type = "Document"
    runtime_id = [42, 10, 7]
    rectangle = SimpleNamespace(left=320, top=160, right=920, bottom=560)

    @property
    def name(self):
        raise AssertionError("diagnostics must not read names")

    @property
    def value(self):
        raise AssertionError("diagnostics must not read field values")


class _Raw:
    element_info = _Info()

    def parent(self):
        raise AssertionError("diagnostics must not traverse again")


def _provenance(monkeypatch, dpi=2):
    context = lambda: 1
    awareness = lambda _: dpi
    monkeypatch.setattr(reader.ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(
        GetThreadDpiAwarenessContext=context, GetAwarenessFromDpiAwarenessContext=awareness)), raising=False)
    return reader._focus_probe_failure_diagnostic(_Raw(), [_Info(), _Info()],
        (300, 100, 800, 600), (50, 70), 10, 20, {"process_create_time": 100.5},
        {"check": "text_readonly", "attribute_class": "mixed"})


def test_document_mixed_rejection_keeps_raw_hit_and_nonzero_origin(monkeypatch):
    result = reader.TextFieldReadError("text_field_target_not_writable", diagnostic={
        "hit_provenance": _provenance(monkeypatch)}).to_reference()
    assert result["reason_code"] == "text_field_target_not_writable"
    hit = result["diagnostic"]["hit_provenance"]
    assert hit["readonly_attribute_class"] == "mixed"
    assert hit["screen_point"] == [350, 170]
    assert hit["raw_hit"]["screen_bbox"] == [320, 160, 600, 400]
    assert hit["raw_hit"]["capture_bbox"] == [20, 60, 600, 400]
    assert hit["window_identity"] == {"window_handle": 10, "process_id": 20, "process_create_time": 100.5}
    assert hit["capture_identity_status"] == "unavailable_at_focus_probe"


@pytest.mark.parametrize("dpi,expected", [(0, 0), (1, 1), (2, 2), (-1, "unavailable")])
def test_dpi_context_is_reported_without_inference(monkeypatch, dpi, expected):
    assert _provenance(monkeypatch, dpi)["thread_dpi_awareness"] == expected


def test_diagnostic_omits_private_or_forged_fields(monkeypatch):
    value = _provenance(monkeypatch)
    value.update(field_value="private-value", name="private-name", capture_id="forged", sha256="forged")
    value["raw_hit"].update(name="private-name", value="private-value")
    value["window_identity"]["secret"] = "private-value"
    result = reader.TextFieldReadError("text_field_target_not_writable", diagnostic={
        "field_value": "private-value", "hit_provenance": value}).to_reference()
    encoded = json.dumps(result)
    assert "private" not in encoded and "forged" not in encoded
    assert "raw_hit" in encoded


def test_unbounded_or_invalid_provenance_never_enters_receipt(monkeypatch):
    value = _provenance(monkeypatch)
    value["ancestors"] *= 8
    value["raw_hit"]["runtime_id"] = [1] * 65
    value["window_identity"]["process_create_time"] = float("nan")
    value["screen_point"] = [2**40, 1]
    result = reader._safe_focus_hit_diagnostic(value)
    assert "ancestors" not in result
    assert "runtime_id" not in result["raw_hit"]
    assert "process_create_time" not in result["window_identity"]
    assert "screen_point" not in result
