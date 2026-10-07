"""滚动预检明确未输入，普通失败仍保留未知；全部使用隔离边界。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.api import action
from app.api.models.request import ScrollRequest
from app.desktop_review import local_direct_step as direct
from tests.test_local_step_timings import timed_scene, saved_report


REQUEST = {'scroll_scope': 'container', 'target_pane': 'unknown',
    'container_bbox': {'x': 345, 'y': 550, 'width': 1009, 'height': 300},
    'coordinate_window_size': {'width': 1380, 'height': 900},
    'target_point_policy': 'explicit_point', 'direction': 'up', 'wheel_clicks': 6,
    'x': 1290, 'y': 595, 'reason': 'Inspect synthetic Run pane', 'enable_verification': True}


@pytest.fixture(autouse=True)
def receipt_geometry(timed_scene, monkeypatch):
    co, _, _, _ = timed_scene
    bound = co._windows().bind_window_by_handle(321)
    bound.rect.right, bound.rect.bottom = 1380, 900
    capture_type = direct.ScreenshotService
    class Capture(capture_type):
        def capture_window(self, **kwargs):
            return {**super().capture_window(**kwargs), 'image_width': 1380, 'image_height': 900}
    monkeypatch.setattr(direct, 'ScreenshotService', Capture)


@pytest.fixture
def scroll_route(monkeypatch):
    events = []
    bound = SimpleNamespace(handle=321, process_id=12, title='Native synthetic workbench',
        rect=SimpleNamespace(left=0, top=0, right=1380, bottom=900))
    monkeypatch.setattr(action, 'window_manager', SimpleNamespace(get_bound_window=lambda: bound))
    def forbidden(name):
        def call(*args, **kwargs):
            events.append(name)
            raise AssertionError('unexpected side effect: ' + name)
        return call
    monkeypatch.setattr(action, 'input_controller', SimpleNamespace(scroll_window=forbidden('scroll_backend')))
    monkeypatch.setattr(action, 'verifier', SimpleNamespace(capture_pre_action_state=forbidden('route_capture')))
    return events


def test_missing_native_container_rejects_before_capture_or_any_input(scroll_route):
    response = action.scroll(ScrollRequest(**REQUEST)).model_dump()
    assert response['success'] is False
    assert response['error']['code'] == 'scroll_precondition_rejected'
    data = response['data']
    assert data['target_container'] is None
    assert data['precondition_decision']['reject_reasons'] == ['target_container_missing']
    assert data['operation_trace_link']['result_status'] == 'blocked'
    assert scroll_route == []
    assert data.get('dispatch_status') == 'not_dispatched'
    assert data['scrolled'] is False and data['input_started'] is False
    assert data['automatic_retry_allowed'] is False


@pytest.mark.parametrize('missing_observation', [False, True])
def test_real_precondition_route_preserved_as_no_dispatch(timed_scene, scroll_route, monkeypatch, missing_observation):
    co, _, _, _ = timed_scene
    monkeypatch.setattr(direct, '_post_action', lambda operation, request, manager:
        action.scroll(ScrollRequest(**request)).model_dump())
    if missing_observation:
        def unavailable(*args): raise ValueError('synthetic observation unavailable')
        monkeypatch.setattr(direct, '_capture_observation', unavailable)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='scroll', request=deepcopy(REQUEST), include_observation=True, observation_wait_ms=0)
    assert result['phase'] == 'not_dispatched'
    assert result['automatic_retry_allowed'] is False
    assert result['observation']['status'] == ('unavailable' if missing_observation else 'captured')
    assert result == saved_report(co)
    assert scroll_route == []


def explicit_rejection():
    return {'success': False, 'error': {'code': 'scroll_precondition_rejected'},
        'data': {'dispatch_status': 'not_dispatched', 'scrolled': False, 'input_started': False,
                 'precondition_decision': {'decision': 'REJECT'},
                 'operation_trace_link': {'result_status': 'blocked'},
                 'execution_path': {'action_executed': False}}}


def test_real_scroll_producer_owner_receipt_reaches_terminal_inspector(timed_scene, scroll_route, monkeypatch, tmp_path):
    from tests.test_session_input_terminal import save, inspect
    co, _, _, _ = timed_scene
    monkeypatch.setattr(direct, '_post_action', lambda operation, request, manager:
        action.scroll(ScrollRequest(**request)).model_dump())
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='scroll', request=deepcopy(REQUEST), include_observation=True, observation_wait_ms=0)
    assert result == saved_report(co)
    root = tmp_path / 'terminal-session'
    command = {'kind': 'step', 'operation': 'scroll', 'request': deepcopy(REQUEST)}
    save(root, 'commands', 'original-scroll', command)
    save(root, 'responses', 'original-scroll', {'command': command, 'status': 'returned', 'result': result})
    before = {str(p): p.read_bytes() for p in root.rglob('*.json')}
    terminal = inspect(root)['commands']['original-scroll']
    assert terminal['terminal_status'] == 'not_dispatched'
    assert terminal['action_executed'] is False
    assert scroll_route == []
    assert before == {str(p): p.read_bytes() for p in root.rglob('*.json')}


@pytest.mark.parametrize('damage', ['dispatch_missing', 'scrolled_missing', 'input_missing',
    'scrolled_true', 'input_true', 'scrolled_zero', 'input_zero', 'error_missing', 'wrong_error',
    'decision_missing', 'decision_allow', 'success_true', 'wrong_operation'])
def test_unproven_or_different_failure_does_not_claim_no_dispatch(timed_scene, monkeypatch, damage):
    co, _, _, _ = timed_scene
    response = explicit_rejection()
    if damage == 'dispatch_missing': response['data'].pop('dispatch_status')
    if damage == 'scrolled_missing': response['data'].pop('scrolled')
    if damage == 'input_missing': response['data'].pop('input_started')
    if damage == 'scrolled_true': response['data']['scrolled'] = True
    if damage == 'input_true': response['data']['input_started'] = True
    if damage == 'scrolled_zero': response['data']['scrolled'] = 0
    if damage == 'input_zero': response['data']['input_started'] = 0
    if damage == 'error_missing': response.pop('error')
    if damage == 'wrong_error': response['error']['code'] = 'scroll_failed'
    if damage == 'decision_missing': response['data'].pop('precondition_decision')
    if damage == 'decision_allow': response['data']['precondition_decision']['decision'] = 'ALLOW'
    if damage == 'success_true': response['success'] = True
    monkeypatch.setattr(direct, '_post_action', lambda *args: response)
    operation = 'press_key' if damage == 'wrong_operation' else 'scroll'
    request = {'key': 'Home', 'x': 70, 'y': 80} if damage == 'wrong_operation' else deepcopy(REQUEST)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation=operation, request=request)
    assert result['phase'] == ('returned' if damage == 'success_true' else 'result_unknown')
    assert result['automatic_retry_allowed'] is False


@pytest.mark.parametrize('effect', ['focus_move', 'wheel_then_verification'])
def test_backend_partial_effect_failure_stays_unknown(timed_scene, monkeypatch, effect):
    co, _, _, _ = timed_scene
    events = []
    def route(*args):
        events.append(effect)
        return {'success': False, 'error': {'code': 'scroll_failed'}, 'data': {
            'execution_path': {'action_executed': effect == 'wheel_then_verification'},
            'operation_trace_link': {'result_status': 'blocked'}}}
    monkeypatch.setattr(direct, '_post_action', route)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='scroll', request=deepcopy(REQUEST))
    assert events == [effect]
    assert result['phase'] == 'result_unknown'
    assert result['automatic_retry_allowed'] is False
