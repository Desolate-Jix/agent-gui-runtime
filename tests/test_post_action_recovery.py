"""输入结果与观察中断独立；窗口提示只读且不冒充后继身份。"""
from types import SimpleNamespace

import pytest

from app.desktop_review import local_direct_step as direct
from tests.test_local_step_timings import timed_scene, saved_report


def test_successful_dispatch_survives_missing_after_and_persists_recovery(timed_scene, monkeypatch):
    co, state, _, _ = timed_scene
    def missing(*args):
        raise ValueError('old modal disappeared')
    recovery = {'status': 'candidates_available', 'candidates': [{'handle': 322, 'process_id': 12}],
                'authorizes_input': False, 'successor_identity_verified': False}
    monkeypatch.setattr(direct, '_capture_observation', missing)
    monkeypatch.setattr(direct, 'observe_recovery_windows', lambda manager, identity: recovery, raising=False)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='press_key', request={'key': 'Enter', 'x': 30, 'y': 20},
        include_observation=True, observation_wait_ms=0)
    assert result['phase'] == 'returned_observation_unavailable'
    assert result['response']['success'] is True
    assert result['observation']['recovery'] == recovery
    assert result['observation']['next_action'] == 'inspect_recovery_windows_then_select_and_capture'
    assert result['automatic_retry_allowed'] is False
    assert state.events.count('route') == 1
    assert result == saved_report(co)


@pytest.mark.parametrize('route_ok', [False, None])
def test_unknown_or_failed_dispatch_is_not_promoted_by_observation_failure(timed_scene, monkeypatch, route_ok):
    co, state, _, _ = timed_scene
    def route(*args):
        state.events.append('route')
        return {'success': route_ok}
    def missing(*args):
        raise ValueError('no frame')
    monkeypatch.setattr(direct, '_post_action', route)
    monkeypatch.setattr(direct, '_capture_observation', missing)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='press_key', request={'key': 'Enter', 'x': 30, 'y': 20},
        include_observation=True, observation_wait_ms=0)
    assert result['phase'] == 'result_unknown'
    assert state.events.count('route') == 1


def recovery_scene():
    identity = {'target_window_handle': 11, 'process_id': 20, 'process_create_time': 123.5,
                'executable_path': 'c:\\fixture\\editor.exe'}
    process = SimpleNamespace(create_time=lambda: 123.5, exe=lambda: 'C:\\fixture\\editor.exe')
    manager = SimpleNamespace(list_visible_windows=lambda: [
        {'handle': 12, 'process_id': 20, 'title': '另存为', 'process_name': 'editor.exe'},
        {'handle': 13, 'process_id': 21, 'title': 'Unrelated'},
        {'handle': 14, 'process_id': 20, 'title': 'Other editor window'}])
    return identity, process, manager


def test_recovery_lists_only_same_process_without_guessing_unique_successor():
    from app.desktop_review.post_action_recovery import observe_recovery_windows
    identity, process, manager = recovery_scene()
    result = observe_recovery_windows(manager, identity, process_factory=lambda pid: process)
    assert result['status'] == 'candidates_available'
    assert [row['handle'] for row in result['candidates']] == [12, 14]
    assert result['target_in_candidates'] is False
    assert result['successor_identity_verified'] is False
    assert result['authorizes_input'] is False
    assert result['candidates'][0]['title'] == '另存为'


@pytest.mark.parametrize('when', ['before', 'after'])
def test_reused_process_never_supplies_recovery_candidates(when):
    from app.desktop_review.post_action_recovery import observe_recovery_windows
    identity, process, manager = recovery_scene()
    count = 0
    def created():
        nonlocal count
        count += 1
        return 999 if when == 'before' or count > 1 else 123.5
    process.create_time = created
    result = observe_recovery_windows(manager, identity, process_factory=lambda pid: process)
    assert result['status'] == 'unavailable'
    assert result['candidates'] == []
    assert result['error_code'] == 'recovery_process_identity_changed'


def test_recovery_failure_does_not_leak_exception_message():
    from app.desktop_review.post_action_recovery import observe_recovery_windows
    identity, _, manager = recovery_scene()
    def gone(pid):
        raise RuntimeError('private process details')
    result = observe_recovery_windows(manager, identity, process_factory=gone)
    assert result['status'] == 'unavailable' and result['error_type'] == 'RuntimeError'
    assert 'private' not in str(result)


def test_recovery_reopens_process_identity_after_enumeration():
    from app.desktop_review.post_action_recovery import observe_recovery_windows
    identity, process, manager = recovery_scene()
    changed = SimpleNamespace(create_time=lambda: 999, exe=process.exe)
    instances = iter([process, changed])
    result = observe_recovery_windows(manager, identity, process_factory=lambda pid: next(instances))
    assert result['status'] == 'unavailable'
    assert result['error_code'] == 'recovery_process_identity_changed'
    assert result['candidates'] == []


def test_no_same_process_windows_does_not_claim_target_closed():
    from app.desktop_review.post_action_recovery import observe_recovery_windows
    identity, process, manager = recovery_scene()
    manager.list_visible_windows = lambda: [{'handle': 14, 'process_id': 30, 'title': 'Unrelated'}]
    result = observe_recovery_windows(manager, identity, process_factory=lambda pid: process)
    assert result['status'] == 'no_visible_candidates'
    assert result['candidates'] == [] and result['target_in_candidates'] is False
    assert result['successor_identity_verified'] is False


@pytest.mark.parametrize('when', ['before', 'after'])
def test_exited_process_is_an_observation_not_a_probe_failure(when):
    from psutil import NoSuchProcess
    from app.desktop_review.post_action_recovery import observe_recovery_windows
    identity, process, manager = recovery_scene()
    calls = 0
    def observed(pid):
        nonlocal calls
        calls += 1
        if when == 'before' or calls > 1:
            raise NoSuchProcess(pid)
        return process
    result = observe_recovery_windows(manager, identity, process_factory=observed)
    assert result['status'] == 'process_not_running'
    assert result['source'] == 'process_identity'
    assert result['candidates'] == []
    assert result['automatic_retry_allowed'] is False
    assert result['authorizes_input'] is False
    assert 'error_code' not in result
    assert result['target_in_candidates'] is None


def test_enumeration_no_such_process_is_not_target_exit():
    from psutil import NoSuchProcess
    from app.desktop_review.post_action_recovery import observe_recovery_windows
    identity, process, manager = recovery_scene()
    def enumerate_windows():
        raise NoSuchProcess(999)
    manager.list_visible_windows = enumerate_windows
    result = observe_recovery_windows(manager, identity, process_factory=lambda pid: process)
    assert result['status'] == 'unavailable'
    assert result['error_code'] == 'recovery_observation_failed'


def test_permission_failure_is_not_target_exit():
    from psutil import AccessDenied
    from app.desktop_review.post_action_recovery import observe_recovery_windows
    identity, _, manager = recovery_scene()
    def denied(pid):
        raise AccessDenied(pid)
    result = observe_recovery_windows(manager, identity, process_factory=denied)
    assert result['status'] == 'unavailable'
    assert result['error_type'] == 'AccessDenied'


@pytest.mark.parametrize('route_ok', [True, False, None])
def test_dispatched_input_then_process_exit_requires_agent_effect_review(timed_scene, monkeypatch, route_ok):
    co, state, _, _ = timed_scene
    def missing(*args):
        raise ValueError('old target disappeared')
    monkeypatch.setattr(direct, '_capture_observation', missing)
    original_route = direct._post_action
    def route(*args):
        response = original_route(*args)
        return {**response, 'success': route_ok}
    monkeypatch.setattr(direct, '_post_action', route)
    monkeypatch.setattr(direct, 'observe_recovery_windows', lambda manager, identity: {
        'status': 'process_not_running', 'source': 'process_identity', 'candidates': [],
        'automatic_retry_allowed': False, 'authorizes_input': False})
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='press_key', request={'key': 'Enter', 'x': 30, 'y': 20},
        include_observation=True, observation_wait_ms=0)
    assert result['response']['success'] is route_ok
    assert result['phase'] == ('returned_observation_unavailable' if route_ok is True else 'result_unknown')
    assert result['observation']['error_code'] == 'target_process_not_running'
    assert result['observation']['next_action'] == 'review_task_effect_without_replaying_input'
    assert result['effect_verified'] is False
    assert result['automatic_retry_allowed'] is False
    assert state.events.count('route') == 1
    assert result == saved_report(co)
