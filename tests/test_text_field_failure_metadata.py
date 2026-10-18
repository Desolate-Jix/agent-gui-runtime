"""只读标志诊断保留故障状态而不泄漏控件内容。"""
import logging

import pytest

from app.agent.windows_text_field_reader import _log_readonly_rejection


@pytest.mark.parametrize("value,expected", [(False, "False"), (True, "True"), (0, "0"), (1, "1")])
def test_readonly_diagnostic_known_flags(caplog, value, expected):
    with caplog.at_level(logging.WARNING):
        _log_readonly_rejection("ComboBox", "text", value)
    assert "ComboBox" in caplog.text
    assert "'readonly': " + expected in caplog.text


@pytest.mark.parametrize("value", ["PRIVATE_FIELD_VALUE", 9911223344, object()])
def test_readonly_diagnostic_unknown_values_are_not_logged(caplog, value):
    with caplog.at_level(logging.WARNING):
        _log_readonly_rejection("PRIVATE_CONTROL_NAME", "PRIVATE_PATTERN", value)
    assert "PRIVATE" not in caplog.text
    assert "9911223344" not in caplog.text
    assert "object at" not in caplog.text
    assert "'readonly': None" in caplog.text


def test_failed_field_logs_geometry_without_text(caplog):
    from app.agent.windows_text_field_reader import TextFieldReadError
    from tests.test_windows_text_field_reader import _Wrapper, _reader, _read

    wrapper = _Wrapper(value="PRIVATE_FAILED_FIELD", text_readonly=True)
    reader, _ = _reader(wrapper)
    with caplog.at_level(logging.WARNING), pytest.raises(TextFieldReadError):
        _read(reader)
    assert "text_field_hit_geometry" in caplog.text
    assert "expected_bbox" in caplog.text and "hit_bbox" in caplog.text
    assert "PRIVATE_FAILED_FIELD" not in caplog.text
