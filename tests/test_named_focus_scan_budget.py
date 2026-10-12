"""字段名称检查覆盖维护采集能处理的大页面，并在上限处明确拒绝。"""
import pytest

from app.agent import windows_form_control_reader as forms
from app.agent import windows_text_field_reader as reader
from app.operation.screen_reading.uia_provider import HARD_UIA_MAX_CONTROLS
from tests.test_named_text_focus import desktop
from tests.test_windows_form_control_reader import Node


@pytest.mark.parametrize("duplicate", [False, True])
def test_named_field_scans_past_old_limit_and_checks_late_duplicate(desktop, duplicate):
    hit = Node("Search", "Edit", (1, 1))
    padding = [Node("", "Group", (2, index)) for index in range(1400)]
    tail = [Node("Search", "Edit", (3, 1))] if duplicate else []
    desktop(hit, *padding, *tail)
    if duplicate:
        with pytest.raises(reader.TextFieldReadError, match="text_field_label_ambiguous"):
            reader._verify_named_focus_hit(hit, 10, 20, (100, 200, 600, 500), "Search")
    else:
        reader._verify_named_focus_hit(hit, 10, 20, (100, 200, 600, 500), "Search")


def test_named_field_budget_remains_bounded_and_reports_exact_reason(desktop):
    hit = Node("Search", "Edit", (1, 1))
    desktop(hit, *[Node("", "Group", (2, index)) for index in range(HARD_UIA_MAX_CONTROLS)])
    with pytest.raises(reader.TextFieldReadError, match="text_field_label_scan_limit"):
        reader._verify_named_focus_hit(hit, 10, 20, (100, 200, 600, 500), "Search")


def test_unrelated_provider_failure_stays_redacted(desktop, monkeypatch):
    hit = Node("Search", "Edit", (1, 1))
    desktop(hit)

    def fail(*args, **kwargs):
        raise RuntimeError("private provider detail")

    monkeypatch.setattr(forms, "_scan_controls", fail)
    with pytest.raises(reader.TextFieldReadError) as error:
        reader._verify_named_focus_hit(hit, 10, 20, (100, 200, 600, 500), "Search")
    assert str(error.value) == "text_field_label_unavailable"
