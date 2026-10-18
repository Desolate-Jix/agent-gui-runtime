"""现场命中只证明控件身份，不读值、不授予输入权限。"""
import json

import pytest

from app.agent.windows_text_field_reader import TextFieldReadError
from tests.test_text_field_hit_readiness import _setup, _placeholder
from tests.test_windows_text_field_reader import _Wrapper


def _observe(reader, **updates):
    args = dict(target_field_id='field', capture_id='capture', target_window_handle=7,
        target_process_id=8, process_create_time=2.0, window_rect=(100, 200, 400, 300),
        target_bbox=(0, 0, 200, 40), click_point=(10, 10),
        expected_runtime_id=(1, 2), expected_control_type='Edit')
    args.update(updates)
    return reader.observe_field_hit(**args)


@pytest.mark.parametrize('kind', ['Edit', 'ComboBox', 'Document'])
def test_hit_returns_only_rechecked_identity_not_field_contents(kind):
    field = _Wrapper('PRIVATE_VALUE', control_type=kind, value_pattern=kind != 'Document')
    reader, state, _ = _setup([_placeholder(), field, field])
    reader._read_text = lambda *_: pytest.fail('hit observation must not read field value')
    result = _observe(reader, expected_control_type=kind)
    assert result['runtime_id'] == [1, 2]
    assert result['point'] == {'x': 10, 'y': 10}
    assert result['bbox'] == {'x': 0, 'y': 0, 'w': 200, 'h': 40}
    assert result['action_executed'] is False and result['artifact_is_authorization'] is False
    assert result['capture_id'] == 'capture'
    assert result['target']['process_create_time'] == 2.0
    assert state['hits'] == 3 and len(state['waits']) == 1
    assert 'PRIVATE_VALUE' not in json.dumps(result)


@pytest.mark.parametrize('change', ['runtime', 'bbox', 'window', 'process', 'password', 'unknown_password',
    'readonly', 'unknown_readonly', 'disabled', 'invisible', 'missing_pattern'])
def test_invalid_or_drifted_hit_is_not_observed(change):
    field = _Wrapper()
    if change == 'runtime': field.element_info.runtime_id = (3, 4)
    elif change == 'bbox': field.element_info.rectangle.right = 301
    elif change == 'window': field.element_info.handle = 99
    elif change == 'process': field.element_info.process_id = 99
    elif change == 'password': field.element_info.element.CurrentIsPassword = True
    elif change == 'unknown_password': field.element_info.element.CurrentIsPassword = None
    elif change == 'readonly': field._value.CurrentIsReadOnly = True
    elif change == 'unknown_readonly': field._value.CurrentIsReadOnly = None
    elif change == 'disabled': field._enabled = False
    elif change == 'invisible': field._visible = False
    elif change == 'missing_pattern': field._value = field._text = None
    reader, _, _ = _setup([field])
    with pytest.raises(TextFieldReadError):
        _observe(reader)


def test_second_hit_cannot_settle_or_reuse_first_field():
    reader, state, _ = _setup([_Wrapper(), _placeholder(), _Wrapper()])
    with pytest.raises(TextFieldReadError):
        _observe(reader)
    assert state['hits'] == 2 and not state['waits']


def test_expected_identity_is_mandatory_before_provider_access():
    reader, state, _ = _setup([_Wrapper()])
    with pytest.raises(TextFieldReadError):
        _observe(reader, expected_runtime_id=None, expected_control_type=None)
    assert state['hits'] == 0


def test_provider_exception_does_not_expose_contents():
    reader, _, _ = _setup([RuntimeError('PRIVATE_PROVIDER_VALUE')])
    with pytest.raises(TextFieldReadError) as caught:
        _observe(reader)
    assert 'PRIVATE_PROVIDER_VALUE' not in str(caught.value)


def test_hit_does_not_access_value_text_or_selection_interfaces():
    class ValueFlagsOnly:
        CurrentIsReadOnly = False
        @property
        def CurrentValue(self):
            pytest.fail('hit read CurrentValue')
    class RangeFlagsOnly:
        def GetAttributeValue(self, _):
            return False
        def GetText(self, _):
            pytest.fail('hit read GetText')
    class TextFlagsOnly:
        DocumentRange = RangeFlagsOnly()
        def GetSelection(self):
            pytest.fail('hit read selection')
    field = _Wrapper(control_type='ComboBox', value_pattern=True)
    field._value, field._text = ValueFlagsOnly(), TextFlagsOnly()
    reader, state, _ = _setup([field])
    assert _observe(reader, expected_control_type='ComboBox')['sample_count'] == 2
    assert state['hits'] == 2


@pytest.mark.parametrize('kind', ['Button', 'CheckBox', 'Hyperlink', 'ListItem'])
def test_interactive_child_hit_cannot_be_promoted_to_editable_parent(kind):
    field = _Wrapper()
    child = _Wrapper(control_type=kind)
    child.element_info.runtime_id = (7, 8)
    child.parent = lambda: field
    child.top_level_parent = lambda: field
    reader, state, _ = _setup([child, field])
    with pytest.raises(TextFieldReadError):
        _observe(reader)
    assert state['hits'] == 1 and not state['waits']
