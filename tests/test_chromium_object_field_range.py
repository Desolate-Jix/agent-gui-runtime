"""对象占位范围不等于字段正文，不能伪造文字或选区。"""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from app.agent.windows_text_field_reader import TextFieldReadError
from tests.test_windows_text_field_reader import _Wrapper, _Text, _reader, _read


def _fixture(value=''):
    wrapper = _Wrapper(value, control_type='ComboBox', value_pattern=True)
    wrapper._text = _Text('\ufffc')
    element = wrapper.element_info.element
    element.CurrentFrameworkId = 'Chrome'
    element.CurrentAriaRole = 'combobox'
    element.CurrentName = ''
    enclosing = deepcopy(element)
    enclosing.GetRuntimeId = lambda: (1,2)
    children = SimpleNamespace(Length=0)
    wrapper._text.DocumentRange.GetEnclosingElement = lambda: enclosing
    wrapper._text.DocumentRange.GetChildren = lambda: children
    wrapper._text.GetSelection = lambda: pytest.fail('object marker range has no usable text selection')
    return wrapper, enclosing, children


@pytest.mark.parametrize('value', ['', 'Auckland War Memorial Museum', '\u4e0a\u6d77\u535a\u7269\u9986'])
def test_exact_owned_object_range_reads_actual_value_twice(value):
    wrapper, _, _ = _fixture(value)
    reader, desktop = _reader(wrapper)
    snapshot = _read(reader)
    assert snapshot.value == value and snapshot.source == 'uia_value' and snapshot.selection is None
    assert len(desktop.calls) == 2


@pytest.mark.parametrize('change', ['framework','role','pid','runtime','name','children','mixed','double','unknown'])
def test_object_marker_does_not_hide_unrelated_or_unknown_ranges(change):
    wrapper, enclosing, children = _fixture('actual')
    if change == 'framework': enclosing.CurrentFrameworkId = 'Other'
    elif change == 'role': enclosing.CurrentAriaRole = 'button'
    elif change == 'pid': enclosing.CurrentProcessId += 1
    elif change == 'runtime': enclosing.GetRuntimeId = lambda: (1,3)
    elif change == 'name': enclosing.CurrentName = 'Other'
    elif change == 'children': children.Length = 1
    elif change == 'mixed': wrapper._text.DocumentRange.text = 'text\ufffc'
    elif change == 'double': wrapper._text.DocumentRange.text = '\ufffc\ufffc'
    else: del wrapper._text.DocumentRange.GetChildren
    with pytest.raises(TextFieldReadError, match='value_patterns_disagree'):
        _read(_reader(wrapper)[0])


@pytest.mark.parametrize('children_present', [True, False])
def test_marker_equal_to_name_cannot_bypass_object_range_checks(children_present):
    wrapper, enclosing, children = _fixture('actual')
    wrapper.element_info.element.CurrentName = enclosing.CurrentName = '\ufffc'
    if children_present:
        children.Length = 1
    else:
        del wrapper._text.DocumentRange.GetChildren
    with pytest.raises(TextFieldReadError, match='value_patterns_disagree'):
        _read(_reader(wrapper)[0])
