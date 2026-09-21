"""条件等待只读状态，不能用静止旧页或输入派发冒充条件成立。"""
from types import SimpleNamespace
import pytest


def module():
    from app.desktop_review import conditional_observation
    return conditional_observation


class Clock:
    def __init__(self):
        self.seconds = 0
        self.cancelled = False

    def now(self):
        return self.seconds

    def wait(self, seconds):
        self.seconds += seconds
        return self.cancelled


def match(token=1):
    return {'status': 'matched', 'runtime_id': [token], 'bbox': [10, 20, 50, 15]}


def exercise(answers, baseline=None, *, clock=None, after_capture=None):
    m = module()
    clock = clock or Clock()
    values = iter(answers)
    last = {'status': 'absent'}
    frames = []
    def probe():
        nonlocal last
        last = next(values, last)
        return last
    def capture():
        frames.append({'sha256': str(len(frames)), 'image_path': 'after.png'})
        if after_capture:
            after_capture()
        return frames[-1]
    result = m.observe_until_condition(probe, capture, baseline or {'status': 'absent'},
        timeout_ms=2000, cancel=clock, clock=clock.now)
    return result, clock, frames


def test_new_stable_target_returns_early_and_binds_final_frame():
    (frame, status), clock, frames = exercise([match(), match(), match()])
    assert status['status'] == 'condition_met'
    assert 0.1 <= clock.seconds < 2
    assert status['after_sha256'] == frame['sha256']
    assert status['after_capture_rechecked'] is True
    assert status['task_effect_verified'] is None and len(frames) == 1


@pytest.mark.parametrize('baseline', [match(), {'status': 'unavailable'}, {'status': 'ambiguous'}])
def test_preexisting_or_unknown_baseline_cannot_finish_early(baseline):
    (_, status), clock, _ = exercise([match()], baseline)
    assert status['status'] == 'timed_out'
    assert clock.seconds >= 2


def test_old_target_must_disappear_before_reappearing():
    (_, status), clock, _ = exercise([{'status': 'absent'}, match(), match(), match()], match())
    assert status['status'] == 'condition_met' and clock.seconds < 2


@pytest.mark.parametrize('middle', [{'status': 'absent'}, {'status': 'ambiguous'}, {'status': 'unavailable'}, match(2)])
def test_unstable_target_requires_new_consecutive_pair(middle):
    (_, status), clock, _ = exercise([match(), middle, match(), match(), match()])
    assert status['status'] == 'condition_met' and clock.seconds >= .3


def test_disappeared_target_after_capture_does_not_reuse_that_frame():
    (_, status), clock, frames = exercise([match(), match(), {'status': 'absent'}])
    assert status['status'] == 'timed_out' and clock.seconds >= 2
    assert len(frames) == 2 and status['after_sha256'] == frames[-1]['sha256']


def test_missing_target_times_out_with_current_image_not_success():
    (_, status), clock, frames = exercise([{'status': 'absent'}])
    assert status['status'] == 'timed_out' and clock.seconds >= 2
    assert len(frames) == 1 and status['task_effect_verified'] is None


def test_timeout_cannot_promote_a_single_last_sample():
    clock = Clock()
    (_, status), _, _ = exercise([{'status': 'absent'}] * 20 + [match()], clock=clock)
    assert status['status'] == 'timed_out'


def test_cancel_stops_wait_without_final_capture():
    clock = Clock()
    clock.cancelled = True
    with pytest.raises(ValueError, match='cancelled'):
        exercise([{'status': 'absent'}], clock=clock)


@pytest.mark.parametrize('condition', [
    {'text': ' '}, {'text': 'target', 'control_type': 'Edit'},
    {'text': 'target', 'unknown': 1}, {'text': 2},
])
def test_invalid_condition_rejected_before_queue(condition):
    from app.instant_mcp import InstantCommand
    with pytest.raises(ValueError):
        InstantCommand(kind='step', operation='press_key', request={'key': 'Enter', 'x': 10, 'y': 10},
            observation_condition=condition).command()


def test_valid_condition_reaches_command_and_cannot_attach_to_capture():
    from app.instant_mcp import InstantCommand
    condition = {'text': 'Wellington Museum', 'control_type': 'Hyperlink'}
    value = InstantCommand(kind='step', operation='press_key', request={'key': 'Enter', 'x': 10, 'y': 10},
        observation_condition=condition).command()
    assert value['observation_condition'] == condition
    with pytest.raises(ValueError):
        InstantCommand(kind='capture', observation_condition=condition).command()


def test_condition_with_zero_wait_is_rejected_before_queue():
    from app.instant_mcp import InstantCommand
    with pytest.raises(ValueError):
        InstantCommand(kind='step', operation='press_key', request={'key': 'Enter', 'x': 10, 'y': 10},
            observation_condition={'text': 'target', 'control_type': 'Text'}, observation_wait_ms=0).command()


def test_sequence_routes_condition_only_to_final_search(monkeypatch):
    from tests.test_input_sequence import Coordinator, snapshots
    from app.desktop_review.input_sequence import run_input_sequence
    co = Coordinator()
    snapshots(monkeypatch, ['', 'maps'])
    condition = {'text': 'Google Maps', 'control_type': 'Hyperlink'}
    result = run_input_sequence(co, {'handle': 1, 'process_id': 2},
        {'field_goal': 'Search', 'text': 'maps', 'submit_search': True}, observation_condition=condition)
    assert result['status'] == 'completed'
    assert all('observation_condition' not in c for c in co.calls[:2])
    assert co.calls[-1]['observation_condition'] == condition


def test_condition_is_preserved_in_compact_sequence_and_step_receipts():
    from app.instant_receipt import compact_receipt
    for contract in ['local_direct_step_v1', 'input_sequence_v1']:
        condition = {'status': 'timed_out', 'elapsed_ms': 2000, 'after_sha256': 'abc'}
        result = compact_receipt({'request_id': 'one', 'result': {
            'contract_version': contract, 'observation': {'status': 'captured', 'condition': condition}}})
        assert result['observation']['condition'] == {**condition, 'sample_count': 0}


from tests.test_local_step_timings import timed_scene, saved_report


def test_direct_path_observes_condition_after_exactly_one_dispatch(timed_scene, monkeypatch):
    from app.desktop_review import local_direct_step as direct
    co, state, clock, _ = timed_scene
    reads = iter([{'status': 'absent'}, match(), match(), match()])
    monkeypatch.setattr(direct, 'UIATextConditionProbe', lambda *args: lambda: next(reads))
    monkeypatch.setattr(co._cancel_wait, 'wait', lambda seconds: clock.advance(seconds * 1000) or False)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='press_key', request={'key': 'Enter', 'x': 30, 'y': 20},
        include_observation=True, observation_condition={'text': 'target', 'control_type': 'Text'})
    assert state.events.count('route') == 1 and state.events.count('capture') == 2
    condition = result['observation']['condition']
    assert condition['status'] == 'condition_met'
    assert condition['after_sha256'] == result['observation']['capture']['sha256']
    assert result['observation']['readiness'] == 'condition_met'
    assert result['effect_verified'] is False and result == saved_report(co)


@pytest.mark.parametrize('baseline', ['unavailable', 'ambiguous', 'matched'])
def test_direct_timeout_preserves_input_and_returns_image(timed_scene, monkeypatch, baseline):
    from app.desktop_review import local_direct_step as direct
    co, state, clock, _ = timed_scene
    monkeypatch.setattr(direct, 'UIATextConditionProbe', lambda *args: lambda: {'status': baseline})
    monkeypatch.setattr(co._cancel_wait, 'wait', lambda seconds: clock.advance(seconds * 1000) or False)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='press_key', request={'key': 'Enter', 'x': 30, 'y': 20},
        include_observation=True, observation_condition={'text': 'target', 'control_type': 'Text'})
    assert result['observation']['condition']['status'] == 'timed_out'
    assert result['observation']['capture']['sha256']
    assert result['phase'] == 'returned' and state.events.count('route') == 1
    assert result['automatic_retry_allowed'] is False


def test_condition_without_observation_is_rejected_before_dispatch(timed_scene):
    co, state, _, _ = timed_scene
    with pytest.raises(ValueError):
        co.execute_local_step(target_window_handle=321, target_process_id=12,
            operation='press_key', request={'key': 'Enter', 'x': 30, 'y': 20},
            observation_condition={'text': 'target', 'control_type': 'Text'})
    assert 'route' not in state.events


def native_scene(monkeypatch, *, nodes=None):
    from pywinauto import uia_defines
    m = module()
    identity = {'contract_version': 'windows_native_identity_observation_v1',
        'provider': 'windows_native_identity', 'status': 'observed', 'target_window_handle': 1,
        'process_id': 2, 'process_create_time': 3.0, 'executable_path': 'c:\\fixture.exe'}
    rect = SimpleNamespace(left=100, top=100, right=900, bottom=700)
    bound = SimpleNamespace(handle=1, process_id=2, rect=rect)
    node = SimpleNamespace(CurrentName='目标', CurrentControlType=20, CurrentIsOffscreen=False,
        CurrentBoundingRectangle=SimpleNamespace(left=110, top=120, right=160, bottom=135),
        GetRuntimeId=lambda: [1, 2, 3])
    items = nodes if nodes is not None else [node]
    array = SimpleNamespace(Length=len(items), GetElement=lambda n: items[n])
    native = SimpleNamespace(CreatePropertyCondition=lambda *args: args,
        CreateAndCondition=lambda *args: args,
        ElementFromHandle=lambda h: SimpleNamespace(FindAll=lambda *args: array))
    api = SimpleNamespace(iuia=native, UIA_dll=SimpleNamespace(UIA_NamePropertyId=1, UIA_ControlTypePropertyId=2),
        known_control_types={'Text': 20}, tree_scope={'descendants': 4})
    monkeypatch.setattr(uia_defines, 'IUIA', lambda: api)
    probe = m.UIATextConditionProbe({'text': '目标', 'control_type': 'Text'},
        SimpleNamespace(bind_window_by_handle=lambda h: bound),
        SimpleNamespace(read_identity=lambda h: dict(identity)), identity)
    return probe, node, bound


def test_native_probe_uses_window_relative_bbox_and_original_unicode(monkeypatch):
    probe, _, _ = native_scene(monkeypatch)
    result = probe()
    assert result['status'] == 'matched' and result['bbox'] == [10, 20, 50, 15]
    assert result['target_window_handle'] == 1 and result['process_id'] == 2


@pytest.mark.parametrize('field,value', [('CurrentName', '目标 '), ('CurrentControlType', 99),
    ('CurrentIsOffscreen', True)])
def test_native_probe_rechecks_exact_visible_control(monkeypatch, field, value):
    probe, node, _ = native_scene(monkeypatch)
    setattr(node, field, value)
    assert probe()['status'] == 'absent'


def test_native_probe_rejects_duplicate_visible_labels(monkeypatch):
    _, node, _ = native_scene(monkeypatch)
    probe, _, _ = native_scene(monkeypatch, nodes=[node, node])
    assert probe()['status'] == 'ambiguous'


def test_native_probe_does_not_use_other_window_identity(monkeypatch):
    probe, _, bound = native_scene(monkeypatch)
    bound.handle = 22
    with pytest.raises(ValueError, match='identity_changed'):
        probe()


def test_native_probe_reports_read_failure_without_private_exception(monkeypatch):
    probe, _, _ = native_scene(monkeypatch)
    def fail(rect):
        raise OSError('private title')
    probe._find = fail
    result = probe()
    assert result['status'] == 'unavailable' and result['error_type'] == 'OSError'
    assert 'private title' not in str(result)


def test_slow_capture_reports_budget_overrun_not_condition_success():
    clock = Clock()
    (_, status), _, _ = exercise([match(), match(), match()], clock=clock,
        after_capture=lambda: setattr(clock, 'seconds', clock.seconds + 3))
    assert status['status'] == 'timed_out'
    assert status['deadline_exceeded'] is True
    assert status['capture_elapsed_ms'] >= 3000
    assert status['deadline_scope'] == 'polling_budget_not_io_timeout'


def test_cancel_has_actionable_reason_without_claiming_zero_input(timed_scene, monkeypatch):
    from app.desktop_review import local_direct_step as direct
    co, state, _, _ = timed_scene
    monkeypatch.setattr(direct, 'UIATextConditionProbe', lambda *args: lambda: {'status': 'absent'})
    monkeypatch.setattr(co._cancel_wait, 'wait', lambda seconds: True)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='press_key', request={'key': 'Enter', 'x': 30, 'y': 20}, include_observation=True,
        observation_condition={'text': 'target', 'control_type': 'Text'})
    assert result['observation']['error_code'] == 'observation_condition_cancelled'
    assert state.events.count('route') == 1 and result['response']['success'] is True
