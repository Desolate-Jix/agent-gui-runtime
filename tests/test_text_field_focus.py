"""输入前必须由真实字段而不是父窗口持有键盘焦点。"""
import pytest

from app.agent.windows_text_field_reader import TextFieldReadError
from tests.test_windows_text_field_reader import _Wrapper, _reader


@pytest.mark.parametrize('focused', [False, True, 0, 1, None])
def test_input_read_requires_exact_field_keyboard_focus(focused):
    field = _Wrapper('value')
    field.element_info.element.CurrentHasKeyboardFocus = focused
    reader, _ = _reader(field)
    kwargs = dict(target_field_id='field', capture_id='capture', target_window_handle=7,
        target_process_id=8, process_create_time=2.0, window_rect=(100, 200, 400, 300),
        target_bbox=(0, 0, 200, 40), click_point=(10, 10), require_keyboard_focus=True)
    if focused:
        assert reader.read_field(**kwargs).value == 'value'
    else:
        with pytest.raises(TextFieldReadError, match='focus'):
            reader.read_field(**kwargs)
