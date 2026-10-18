"""Chromium 名称型 TextRange 与真实 Value 分开，不猜测插入选区。"""
from types import SimpleNamespace

import pytest

from tests.test_windows_text_field_reader import _Wrapper, _Text, _reader, _read
from app.agent.windows_text_field_reader import TextFieldReadError


def _named_combo(value=''):
    wrapper = _Wrapper(value, control_type='ComboBox', value_pattern=True)
    element = wrapper.element_info.element
    element.CurrentFrameworkId = 'Chrome'
    element.CurrentAriaRole = 'combobox'
    element.CurrentName = 'Accessible field label'
    wrapper._text = _Text(element.CurrentName)
    wrapper._text.DocumentRange.GetEnclosingElement = lambda: SimpleNamespace(
        GetRuntimeId=lambda: (1, 2), CurrentProcessId=8, CurrentName=element.CurrentName,
        CurrentFrameworkId='Chrome', CurrentAriaRole='combobox')
    return wrapper


@pytest.mark.parametrize('value', ['', 'OpenStreetMap', '中文 😀'])
def test_name_range_is_not_value_or_selection(value):
    reader, desktop = _reader(_named_combo(value))
    result = _read(reader)
    assert result.value == value
    assert result.source == 'uia_value'
    assert result.selection is None
    assert len(desktop.calls) == 2
    from app.agent.text_field_evidence import prepare_text_field_expectation
    from app.agent.text_parameters import ReviewedTextParameters, ReviewedTextSource, resolve_text_parameters
    def parameters(clear):
        return resolve_text_parameters(ReviewedTextParameters('field', ReviewedTextSource('literal', 'new'), clear, False), {})
    assert prepare_text_field_expectation(result, parameters(True)).before.value == value
    with pytest.raises(ValueError, match='selection'):
        prepare_text_field_expectation(result, parameters(False))


@pytest.mark.parametrize('case', ['framework', 'role', 'name', 'empty_name', 'enclosing_runtime',
                                'enclosing_process', 'enclosing_name', 'enclosing_framework',
                                'no_range_owner', 'readonly', 'password', 'edit_not_combo'])
def test_name_range_exception_requires_all_verified_provider_facts(case):
    wrapper = _named_combo()
    element = wrapper.element_info.element
    if case == 'framework': element.CurrentFrameworkId = 'Other'
    elif case == 'role': element.CurrentAriaRole = 'listbox'
    elif case == 'name': element.CurrentName = 'Other label'
    elif case == 'empty_name': element.CurrentName = ''; wrapper._text.DocumentRange.text = ''
    elif case.startswith('enclosing_'):
        owner = wrapper._text.DocumentRange.GetEnclosingElement()
        if case == 'enclosing_runtime': owner.GetRuntimeId = lambda: (4, 5)
        elif case == 'enclosing_process': owner.CurrentProcessId = 9
        elif case == 'enclosing_name': owner.CurrentName = 'Other field'
        else: owner.CurrentFrameworkId = 'Other'
        wrapper._text.DocumentRange.GetEnclosingElement = lambda: owner
    elif case == 'no_range_owner': wrapper._text.DocumentRange.GetEnclosingElement = lambda: None
    elif case == 'readonly': wrapper._value.CurrentIsReadOnly = True
    elif case == 'password': element.CurrentIsPassword = True
    elif case == 'edit_not_combo': wrapper.element_info.control_type = 'Edit'
    # 空名称且两模式均为空不构成冲突；此处保持非空真实值触发待验证的分支。
    if case == 'empty_name': wrapper._value.CurrentValue = 'content'
    reader, _ = _reader(wrapper)
    with pytest.raises(TextFieldReadError):
        _read(reader)


def test_changing_value_or_name_between_reads_is_rejected():
    for changed in ('value', 'name'):
        wrapper = _named_combo('before')
        reader, desktop = _reader(wrapper)
        original = desktop.from_point
        def changing(*args):
            if desktop.calls:
                if changed == 'value': wrapper._value.CurrentValue = 'after'
                else:
                    wrapper.element_info.element.CurrentName = 'Changed label'
                    wrapper._text.DocumentRange.text = 'Changed label'
            return original(*args)
        desktop.from_point = changing
        with pytest.raises(TextFieldReadError):
            _read(reader)


@pytest.mark.parametrize('selection', [(0, 0), (1, 4), (0, 22)])
def test_value_equal_to_name_never_turns_name_range_into_content_selection(selection):
    wrapper = _named_combo('Accessible field label')
    wrapper._text.start, wrapper._text.end = selection
    reader, _ = _reader(wrapper)
    result = _read(reader)
    assert result.value == wrapper.element_info.element.CurrentName
    assert result.source == 'uia_value'
    assert result.selection is None

    from dataclasses import replace
    from app.agent.text_field_evidence import prepare_text_field_expectation
    from app.agent.text_input_guard import TextInputGuard
    from app.agent.text_parameters import ReviewedTextParameters, ReviewedTextSource, resolve_text_parameters
    parameters = resolve_text_parameters(
        ReviewedTextParameters('field', ReviewedTextSource('literal', 'new'), True, False), {})
    expectation = prepare_text_field_expectation(result, parameters)
    latest = replace(result, read_id=result.read_id + '-latest', observed_at_ns=result.observed_at_ns + 1)
    guard = TextInputGuard(expectation=expectation, read_current=lambda **kwargs: latest)
    with pytest.raises(ValueError, match='precondition'):
        guard.verify_before_paste()
