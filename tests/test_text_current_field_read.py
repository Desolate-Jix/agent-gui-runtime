"""当前截图与审核锚点限定局部字段读取，不向公共观察加入原文。"""
from copy import deepcopy
from dataclasses import replace
import json
import time
from types import SimpleNamespace

import pytest

from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
from tests.test_text_formal_review_flow import text_preview_inputs
from tests.test_live_runtime_composition_w3b import _bound


class FieldReader:
    def __init__(self):
        self.calls = []
        self.change = lambda value: value

    def read_field(self, **kwargs):
        self.calls.append(kwargs)
        identity = TextFieldIdentity(kwargs['target_field_id'], kwargs['target_window_handle'],
            kwargs['target_process_id'], kwargs['process_create_time'], (42, 5),
            kwargs['window_rect'], kwargs['target_bbox'])
        return self.change(TextFieldSnapshot(identity, kwargs['capture_id'], f'read-{len(self.calls)}',
            time.perf_counter_ns(), 'uia_value', '字段原值\r\n中文', (1, 3)))


def inputs(tmp_path):
    asset, adapter, _, current, _, selection, resolved, _ = text_preview_inputs(tmp_path)
    reader = FieldReader()
    adapter._text_field_reader = reader
    return asset, adapter, current, selection, resolved['grounding'], reader


def read(adapter, current, selection, grounding):
    return adapter.read_text_field(session_id='text-review', current_observation=current,
        selection=selection, grounding=grounding)


def test_actual_field_read_is_bound_to_reviewed_anchor_and_capture(tmp_path):
    _, adapter, current, selection, grounding, reader = inputs(tmp_path)
    frozen_current = deepcopy(current)
    actual = read(adapter, current, selection, grounding)
    assert actual.value == '字段原值\r\n中文'
    assert actual.identity.target_field_id == 'job_card'
    assert actual.identity.window_rect == (10, 20, 320, 200)
    assert actual.identity.process_create_time == 1000.5
    assert len(reader.calls) == 1
    assert current == frozen_current
    assert '字段原值' not in json.dumps(current, ensure_ascii=False)


@pytest.mark.parametrize('change', ['capture', 'field', 'point', 'image'])
def test_bad_lineage_never_reaches_field_reader(tmp_path, change):
    _, adapter, current, selection, grounding, reader = inputs(tmp_path)
    if change == 'capture':
        current['capture_id'] = 'not-current'
    elif change == 'field':
        selection['text_parameters_ref']['target_field_id'] = 'another'
    elif change == 'point':
        grounding['click_point']['x'] += 1
    else:
        adapter._screenshot_service.paths[0].write_bytes(b'not-the-capture')
    with pytest.raises(ValueError):
        read(adapter, current, selection, grounding)
    assert reader.calls == []


@pytest.mark.parametrize('change', ['capture', 'process', 'field', 'clock'])
def test_reader_result_must_match_capture_and_identity(tmp_path, change):
    _, adapter, current, selection, grounding, reader = inputs(tmp_path)
    transforms = {
        'capture': lambda s: replace(s, capture_id='other'),
        'process': lambda s: replace(s, identity=replace(s.identity, process_create_time=2000.5)),
        'field': lambda s: replace(s, identity=replace(s.identity, target_field_id='other')),
        'clock': lambda s: replace(s, observed_at_ns=1),
    }
    reader.change = transforms[change]
    with pytest.raises(ValueError, match='field'):
        read(adapter, current, selection, grounding)


def test_text_capture_detects_origin_move_without_size_change(tmp_path):
    asset, adapter, *_ = inputs(tmp_path)
    bound = _bound()
    adapter._window_manager = SimpleNamespace(get_bound_window=lambda: bound)
    original = adapter._screenshot_service.capture_window

    def moved(**kwargs):
        result = original(**kwargs)
        bound.rect.left += 10
        bound.rect.right += 10
        return result

    adapter._screenshot_service.capture_window = moved
    with pytest.raises(ValueError, match='text capture window binding changed'):
        adapter.capture_current(session_id='moved', asset=asset, target_window_handle=4242)


@pytest.mark.parametrize('clear', [True, False])
def test_com_shaped_reader_through_actual_adapter_and_exact_value_verification(tmp_path, monkeypatch, clear):
    from app.agent.windows_text_field_reader import WindowsTextFieldReader
    from app.agent.text_parameters import ReviewedTextParameters, resolve_text_parameters
    from app.agent.text_field_evidence import prepare_text_field_expectation, validate_text_field_precondition, verify_text_field_result
    from app.agent.reviewed_workflow_replay import resolve_current_state, select_transition_for_review
    from tests.test_windows_text_field_reader import _Wrapper, _Desktop, _Text
    import tests.test_text_formal_review_flow as flow

    parameters = deepcopy(flow.PARAMETERS)
    parameters['clear_existing'] = clear
    parameters['content'] = {'kind': 'variable', 'name': 'query'}
    monkeypatch.setattr(flow, 'PARAMETERS', parameters)
    asset, adapter, current, selection, grounding, _ = inputs(tmp_path)
    windows = SimpleNamespace(get_bound_window=lambda: _bound())
    adapter._window_manager = windows
    wrapper = _Wrapper('甲🙂乙丙', handle=4242, pid=9001)
    x, y, width, height = (grounding['bbox'][key] for key in ('x', 'y', 'w', 'h'))
    wrapper.element_info.rectangle = SimpleNamespace(left=x+10, top=y+20, right=x+width+10, bottom=y+height+20)
    wrapper._text = _Text('甲🙂乙丙', 1, 3)
    desktop = _Desktop(wrapper)
    adapter._text_field_reader = WindowsTextFieldReader(window_manager=windows,
        native_identity_reader=adapter._native_identity_reader, desktop_factory=lambda **_: desktop)
    before = read(adapter, current, selection, grounding)
    expected = prepare_text_field_expectation(before,
        resolve_text_parameters(ReviewedTextParameters.from_payload(parameters), {'query': '新\r\n值'}))
    assert expected.expected_value == ('新\r\n值' if clear else '甲新\r\n值丙')
    wrapper._text.start, wrapper._text.end = 2, 2
    changed_selection = read(adapter, current, selection, grounding)
    if clear:
        validate_text_field_precondition(expected, changed_selection)
    else:
        with pytest.raises(ValueError, match='precondition'):
            validate_text_field_precondition(expected, changed_selection)

    # 只改变合成控件的值，不派发任何真实输入；随后走真正的新采集和字段回读。
    wrapper._value.CurrentValue = expected.expected_value
    wrapper._text = _Text(expected.expected_value, 0, 0)
    fresh = adapter.capture_current(session_id='text-review', asset=asset, target_window_handle=4242)
    fresh_selection = select_transition_for_review(asset, resolve_current_state(asset, fresh),
        transition_id=selection['transition_id'], current_observation=fresh)
    fresh_grounding = adapter.resolve(session_id='text-review', selection=fresh_selection, current_observation=fresh)['grounding']
    after = read(adapter, fresh, fresh_selection, fresh_grounding)
    assert verify_text_field_result(expected, after)['status'] == 'verified'
    wrapper._value.CurrentValue = 'A' + expected.expected_value
    wrapper._text = _Text(wrapper._value.CurrentValue, 0, 0)
    wrong = read(adapter, fresh, fresh_selection, fresh_grounding)
    assert verify_text_field_result(expected, wrong)['reason_code'] == 'text_value_mismatch'
