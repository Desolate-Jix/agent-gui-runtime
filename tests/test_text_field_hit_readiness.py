"""字段命中就绪必须绑定当前身份，不能读取近似容器或重试输入。"""
from types import SimpleNamespace

import pytest

from app.agent.windows_text_field_reader import TextFieldReadError, WindowsTextFieldReader
from tests.test_windows_text_field_reader import _Native, _Wrapper


def _setup(sequence):
    bound = SimpleNamespace(handle=7, process_id=8,
        rect=SimpleNamespace(left=100, top=200, right=500, bottom=500))
    state = {'hits':0, 'time':0.0, 'waits':[]}

    def hit(x, y):
        assert (x, y) == (110, 210)
        item = sequence[min(state['hits'], len(sequence)-1)]
        state['hits'] += 1
        if isinstance(item, Exception):
            raise item
        return item

    def wait(seconds):
        state['waits'].append(seconds)
        state['time'] += seconds

    reader = WindowsTextFieldReader(
        window_manager=SimpleNamespace(get_bound_window=lambda: bound),
        native_identity_reader=_Native(), desktop_factory=lambda **_: SimpleNamespace(from_point=hit),
        clock_ns=lambda: 9, read_id_factory=lambda:'read',
        readiness_clock=lambda: state['time'], readiness_wait=wait)
    return reader, state, bound


def _read(reader, **overrides):
    args = dict(target_field_id='field', capture_id='capture', target_window_handle=7,
        target_process_id=8, process_create_time=2.0, window_rect=(100,200,400,300),
        target_bbox=(0,0,200,40), click_point=(10,10),
        expected_runtime_id=(1,2), expected_control_type='Edit')
    args.update(overrides)
    return reader.read_field(**args)


def _coarse(kind='Document'):
    wrapper = _Wrapper('MUST_NOT_READ_CONTAINER_TEXT', control_type=kind)
    wrapper.element_info.runtime_id = (9,9)
    wrapper.element_info.rectangle = SimpleNamespace(left=100,top=200,right=500,bottom=500)
    return wrapper


@pytest.mark.parametrize('kind', ['Document','Group','Pane'])
@pytest.mark.parametrize('field_type', ['Edit','ComboBox','Document'])
@pytest.mark.parametrize('value', ['Auckland','上海', 'Mixed 地点'])
def test_coarse_hit_settles_to_exact_identity_without_reading_container(kind,field_type,value):
    coarse = _coarse(kind)
    field = _Wrapper(value,control_type=field_type,value_pattern=field_type!='Document')
    reader, state, _ = _setup([coarse,field,field])
    original = reader._read_text
    reads = []

    def read(wrapper,control_type):
        assert wrapper is field
        reads.append(wrapper)
        return original(wrapper,control_type)

    reader._read_text = read
    result = _read(reader,expected_control_type=field_type)
    assert result.value == value and result.identity.runtime_id == (1,2)
    assert state['hits'] == 3 and len(state['waits']) == 1 and len(reads) == 2


def test_ready_hit_has_no_delay():
    reader,state,_ = _setup([_Wrapper()])
    _read(reader)
    assert state['hits'] == 2 and state['waits'] == []


def _placeholder():
    wrapper = _coarse('Text')
    wrapper.element_info.rectangle = SimpleNamespace(left=100, top=202, right=180, bottom=220)
    return wrapper


def test_placeholder_hit_may_settle_but_is_never_used_as_field_identity():
    placeholder, field = _placeholder(), _Wrapper()
    reader, state, _ = _setup([placeholder, field, field])
    original = reader._read_text
    def read(wrapper, kind):
        assert wrapper is field
        return original(wrapper, kind)
    reader._read_text = read
    assert _read(reader).identity.runtime_id == (1, 2)
    assert state['hits'] == 3 and len(state['waits']) == 1


@pytest.mark.parametrize('change', ['outside', 'misses_point', 'disabled', 'invisible', 'other_window'])
def test_unbound_placeholder_cannot_create_readiness_permission(change):
    placeholder = _placeholder()
    if change == 'outside':
        placeholder.element_info.rectangle = SimpleNamespace(left=99, top=202, right=180, bottom=220)
    elif change == 'misses_point':
        placeholder.element_info.rectangle = SimpleNamespace(left=130, top=202, right=180, bottom=220)
    elif change == 'disabled':
        placeholder.is_enabled = lambda: False
    elif change == 'invisible':
        placeholder.is_visible = lambda: False
    else:
        placeholder.element_info.handle = 99
    reader, state, _ = _setup([placeholder, _Wrapper()])
    with pytest.raises(TextFieldReadError):
        _read(reader)
    assert state['hits'] == 1 and not state['waits']


def test_persistent_placeholder_is_bounded_and_never_read_as_value():
    reader, state, _ = _setup([_placeholder()])
    reader._read_text = lambda *_: pytest.fail('placeholder was read as value')
    with pytest.raises(TextFieldReadError, match='hit_not_ready'):
        _read(reader)
    assert state['hits'] <= 11 and sum(state['waits']) <= .251


def test_placeholder_after_value_read_still_fails_without_retry():
    reader, state, _ = _setup([_Wrapper(), _placeholder(), _Wrapper()])
    with pytest.raises(TextFieldReadError):
        _read(reader)
    assert state['hits'] == 2 and not state['waits']


def test_coarse_hit_timeout_is_bounded_and_does_not_read_text():
    reader,state,_ = _setup([_coarse()])
    reader._read_text = lambda *_: pytest.fail('unbound text was read')
    with pytest.raises(TextFieldReadError,match='hit_not_ready'):
        _read(reader)
    assert state['hits'] <= 11 and sum(state['waits']) <= .251


@pytest.mark.parametrize('change', ['runtime','bbox','type','process','window','password','readonly'])
def test_wrong_or_unwritable_exact_hit_never_waits(change):
    field = _Wrapper()
    if change == 'runtime': field.element_info.runtime_id = (3,4)
    if change == 'bbox': field.element_info.rectangle = SimpleNamespace(left=100,top=200,right=301,bottom=240)
    if change == 'type': field.element_info.control_type = 'ComboBox'
    if change == 'process': field.element_info.process_id = 99
    if change == 'window': field.element_info.handle = 99
    if change == 'password': field.element_info.element.CurrentIsPassword = True
    if change == 'readonly': field._value.CurrentIsReadOnly = True
    reader,state,_ = _setup([field])
    with pytest.raises(TextFieldReadError):
        _read(reader)
    assert state['waits'] == [] and state['hits'] == 1


@pytest.mark.parametrize('change', ['different_window','different_process','same_size','not_containing','provider_error'])
def test_only_current_coarse_enclosing_hits_are_eligible(change):
    coarse = _coarse()
    if change == 'different_window': coarse.element_info.handle = 99
    if change == 'different_process': coarse.element_info.process_id = 99
    if change == 'same_size': coarse.element_info.rectangle = _Wrapper().element_info.rectangle
    if change == 'not_containing': coarse.element_info.rectangle = SimpleNamespace(left=101,top=201,right=500,bottom=500)
    if change == 'provider_error': coarse = RuntimeError('PRIVATE_PROVIDER_TEXT')
    reader,state,_ = _setup([coarse])
    with pytest.raises(TextFieldReadError) as error:
        _read(reader)
    assert state['waits'] == [] and state['hits'] == 1
    assert 'PRIVATE_PROVIDER_TEXT' not in str(error.value)


def test_binding_drift_during_wait_is_rejected_before_second_hit():
    reader,state,bound = _setup([_coarse(),_Wrapper()])
    def wait(_): bound.rect.left += 1
    reader._readiness_wait = wait
    with pytest.raises(TextFieldReadError,match='window_binding_changed'):
        _read(reader)
    assert state['hits'] == 1


def test_post_read_identity_drift_is_not_hidden_by_readiness_retry():
    reader,state,_ = _setup([_Wrapper(),_coarse(),_Wrapper()])
    with pytest.raises(TextFieldReadError,match='identity_changed'):
        _read(reader)
    assert state['hits'] == 2 and state['waits'] == []


def test_missing_expected_identity_keeps_legacy_no_retry():
    reader,state,_ = _setup([_coarse(),_Wrapper()])
    with pytest.raises(TextFieldReadError):
        _read(reader,expected_runtime_id=None,expected_control_type=None)
    assert not state['waits']


@pytest.mark.parametrize('runtime', [(), [True], '1,2', [1]*65])
def test_bad_expected_identity_fails_before_hit(runtime):
    reader,state,_ = _setup([_Wrapper()])
    with pytest.raises(TextFieldReadError,match='expected_identity_invalid'):
        _read(reader,expected_runtime_id=runtime)
    assert state['hits'] == 0


@pytest.mark.parametrize('overrides', [
    {'expected_runtime_id':None}, {'expected_control_type':None},
    {'expected_control_type':'Button'}, {'expected_control_type':True},
])
def test_expected_identity_pair_cannot_be_inferred_from_hit(overrides):
    reader,state,_ = _setup([_Wrapper()])
    with pytest.raises(TextFieldReadError,match='expected_identity_invalid'):
        _read(reader,**overrides)
    assert state['hits'] == 0


def test_resolved_other_field_is_not_retried_as_raw_group():
    group = _coarse('Group')
    other = _Wrapper()
    other.element_info.runtime_id = (8,8)
    group.parent = lambda: other
    group.top_level_parent = lambda: other
    reader,state,_ = _setup([group,_Wrapper()])
    with pytest.raises(TextFieldReadError,match='identity_changed'):
        _read(reader)
    assert state['hits'] == 1 and not state['waits']


def test_exact_result_after_elapsed_budget_is_not_accepted():
    reader,state,_ = _setup([_coarse(),_Wrapper()])
    original = reader._from_point
    def slow_hit(*args):
        wrapper = original(*args)
        if state['hits'] == 2:
            state['time'] += 1
        return wrapper
    reader._from_point = slow_hit
    reader._read_text = lambda *_: pytest.fail('late text was read')
    with pytest.raises(TextFieldReadError,match='hit_not_ready'):
        _read(reader)
    assert state['hits'] == 2
