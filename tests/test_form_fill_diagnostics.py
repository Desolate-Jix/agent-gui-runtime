"""表单只读失败回执透传安全结构诊断，不触发输入或重试。"""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.agent import windows_form_control_reader as reader
from app.desktop_review.form_fill import run_form_fill


@pytest.mark.parametrize("counts", [{}, {"Pane": 1, "ToolBar": 1}, {"Document": 1, "CheckBox": 1}])
def test_form_read_failure_preserves_safe_scan_diagnostics(monkeypatch, counts):
    diagnostic = {"scope": "window_control_view", "window_handle": 10, "process_id": 20,
        "node_count": sum(counts.values()), "control_type_counts": counts,
        "document_count": counts.get("Document", 0), "match_count": 0,
        "scan_started": True, "scan_complete": True}
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise reader.FormControlReadError("form_control_not_found", diagnostics=diagnostic)

    monkeypatch.setattr(reader, "read_form_control", fail)
    progress = []
    result = run_form_fill(SimpleNamespace(), {"handle": 10, "process_id": 20},
        {"fields": [{"kind": "checkbox", "label": "Show Source", "checked": True}]},
        persist=lambda data: progress.append(deepcopy(data)))
    assert result["status"] == "interrupted"
    assert result["fields"][0]["check"]["diagnostics"] == diagnostic
    assert result["observation"]["diagnostics"] == diagnostic
    assert result["action_executed"] is False
    assert result["automatic_retry_allowed"] is False
    assert result["fields"][0]["steps"] == []
    assert len(calls) == 1
    assert progress[-1]["fields"][0]["check"]["diagnostics"] == diagnostic


def test_arbitrary_provider_diagnostics_do_not_leak_through_form_receipt(monkeypatch):
    def fail(*args, **kwargs):
        error = ValueError("private provider text")
        error.diagnostics = {"value": "private provider text"}
        raise error

    monkeypatch.setattr(reader, "read_form_control", fail)
    result = run_form_fill(SimpleNamespace(), {"handle": 10, "process_id": 20},
        {"fields": [{"kind": "checkbox", "label": "Show Source", "checked": True}]})
    assert "diagnostics" not in result["fields"][0]["check"]
    assert "diagnostics" not in result["observation"]
    assert "private" not in json.dumps(result)
