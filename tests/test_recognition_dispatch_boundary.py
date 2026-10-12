"""只替换模型与桌面边界，贯通真实识别、owner、序列与持久队列。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

from PIL import Image
import pytest

from app.desktop_review import local_direct_step as direct
from tests.test_local_step_timings import timed_scene


@pytest.fixture
def route(tmp_path, monkeypatch):
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.api.models.response import APIResponse
    from app.agent.windows_text_field_reader import TextFieldReadError
    from app.core.local_input_policy import _local_operator_input_scope
    from app.core import local_text_focus
    from tests.test_local_recognition_policy import plan_fixture

    identity = {'contract_version': 'windows_native_identity_observation_v1', 'provider': 'windows_native_identity',
        'status': 'observed', 'target_window_handle': 321, 'process_id': 12, 'process_create_time': 123.5,
        'executable_path': 'c:\\fixture\\editor.exe'}
    bound = SimpleNamespace(handle=321, process_id=12, title='Fresh synthetic editor', process_name='editor.exe',
        rect=SimpleNamespace(left=100, top=200, right=1100, bottom=890))
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    monkeypatch.setattr(action, 'window_manager', manager)
    capture_index = []
    def fresh_capture(**kwargs):
        capture_index.append(1)
        path = tmp_path / ('dispatch-capture-' + str(len(capture_index)) + '.png')
        Image.new('RGB', (1000, 690), 'white').save(path)
        return {'capture_id': str(path), 'image_path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest(),
            'image_size': {'width': 1000, 'height': 690}, 'window_size': {'width': 1000, 'height': 690},
            'window_identity': {'handle': 321, 'process_id': 12, 'process_create_time': 123.5}, 'roi': None}
    monkeypatch.setattr(action.screenshot_service, 'capture_window', fresh_capture)
    monkeypatch.setattr(action, 'prepare_browser_content', lambda *args: None)
    monkeypatch.setattr(action, '_run_recognition_plan_for_execution', lambda request:
        APIResponse(success=True, message='synthetic model evidence', data={'result': deepcopy(plan_fixture(request.image_path))}))
    monkeypatch.setattr(action, '_render_recognition_plan_overlay_for_execution', lambda plan: None)
    monkeypatch.setattr(action, 'write_trace', lambda **kw: str(tmp_path / 'trace.json'))
    monkeypatch.setattr(action, '_rewrite_execute_trace_result', lambda **kw: None)
    monkeypatch.setattr(action, '_capture_pre_action_state_with_foreground_retry', lambda **kw: ({}, 0))
    events = []

    def run(failure='pre_field'):
        events.clear()
        def probe(*args, **kwargs):
            events.append('readonly_probe')
            if failure == 'pre_field':
                raise TextFieldReadError('text_field_target_not_writable', diagnostic={
                    'hit_provenance': {'raw_hit': {'control_type': 'ToolBar'}}})
            return {'control_type': 'Edit', 'runtime_id': [42, 1]}
        monkeypatch.setattr(local_text_focus, 'probe_local_focus_target', probe)
        def click(x, y, **kwargs):
            events.append('click_point')
            if failure == 'click_control_error':
                from app.core.local_control_target import LocalControlTargetError
                raise LocalControlTargetError('local_control_target_state_changed')
            if failure in {'click_unknown', 'click_partial', 'click_occluded'}:
                error = (action.TargetPointOccludedError({'reason': 'target_point_occluded'})
                    if failure == 'click_occluded' else RuntimeError('synthetic dispatch interruption'))
                if failure == 'click_partial':
                    error.click_sequence = {'requested_click_count': 1, 'completed_clicks': 0,
                        'input_attempted': True, 'button': 'left'}
                raise error
            if failure == 'missing_click_result':
                return {}
            return {'clicked': True, 'window_point': {'x': x, 'y': y}}
        monkeypatch.setattr(action.input_controller, 'click_point', click)
        def verify(*args, **kwargs):
            events.append('post_click_verifier')
            if failure == 'post_verify_control':
                from app.core.local_control_target import LocalControlTargetError
                raise LocalControlTargetError('local_control_target_state_changed')
            raise RuntimeError('synthetic verifier unavailable after dispatch')
        monkeypatch.setattr(action.verifier, 'verify_action', verify)
        request = ExecuteRecognitionPlanRequest(goal='Focus the fresh field',
            enable_post_click_verification=failure in {'post_verify', 'post_verify_control'}, max_execution_attempts=1,
            auto_observe_learning_artifacts=False,
            write_policy={'path_graph': False, 'element_memory': False, 'trace': False})
        with _local_operator_input_scope(manager=manager,
                identity_reader=SimpleNamespace(read_identity=lambda handle: deepcopy(identity)), identity=identity,
                window_rect=(100, 200, 1100, 890), enabled=lambda: True), local_text_focus.local_text_focus_scope(
                    local_text_focus.LocalTextFocusTarget(321, 12)):
            return action.execute_recognition_plan(request).model_dump()
    return SimpleNamespace(run=run, events=events)


def owner(timed_scene, monkeypatch, response):
    co = timed_scene[0]
    monkeypatch.setattr(direct, '_post_action', lambda *args: deepcopy(response))
    return co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='execute_recognition_plan', request={'goal': 'Focus the fresh field'},
        include_observation=True, observation_wait_ms=0)


def sequence(timed_scene, monkeypatch, response):
    from app.desktop_review.input_sequence import run_input_sequence
    monkeypatch.setattr(direct, '_post_action', lambda *args: deepcopy(response))
    return run_input_sequence(timed_scene[0], {'handle': 321, 'process_id': 12},
        {'field_goal': 'Focus the fresh field', 'text': 'fresh synthetic text', 'submit_search': False})


def test_real_readonly_focus_rejection_produces_strict_stage_proof(route):
    response = route.run()
    data = response['data']
    assert route.events == ['readonly_probe']
    assert response['error']['code'] == 'recognition_plan_click_failed'
    assert data.get('dispatch_status') == 'not_dispatched'
    assert data.get('dispatch_stage') == 'pre_click_validation'
    assert data.get('input_started') is False
    proof = data.get('pre_click_input_rejection')
    assert proof == {'contract_version': 'recognition_pre_click_rejection.v1', 'validator': 'text_focus',
        'reason_code': 'text_field_target_not_writable', 'click_dispatch_started': False}
    assert data['execution_path']['action_executed'] is False
    assert data['selected_click_point'] == {'x': 184, 'y': 516}


@pytest.mark.parametrize('failure,expected', [('click_unknown', None), ('click_partial', None),
    ('click_occluded', None), ('click_control_error', None), ('missing_click_result', None),
    ('post_verify', True), ('post_verify_control', True)])
def test_dispatch_entry_and_confirmed_click_are_never_downgraded_by_empty_attempts(route, failure, expected):
    response = route.run(failure)
    assert response['success'] is False
    data = response['data']
    assert data['execution_path']['action_executed'] is expected
    assert data['agent_step_result']['action_executed'] is expected
    assert data.get('dispatch_status') != 'not_dispatched'
    assert data.get('pre_click_input_rejection') is None
    assert 'click_point' in route.events


def test_successful_precise_field_still_dispatches_once(route):
    response = route.run('success')
    assert response['success'] is True
    assert route.events == ['readonly_probe', 'click_point']
    assert response['data']['result']['execution_path']['action_executed'] is True


def test_post_click_failure_preserves_input_through_owner_sequence_and_shared_learning(
        route, timed_scene, monkeypatch):
    from app.learning_memory.workflow_trial import _actual_action_executed
    response = route.run('post_verify')
    result = sequence(timed_scene, monkeypatch, response)
    assert result['status'] == 'interrupted' and result['action_executed'] is True
    assert result['steps'][0]['status'] == 'result_unknown'
    assert _actual_action_executed(result) is True
    assert result['completed_steps'] == []


def test_owner_sequence_and_terminal_share_pre_click_proof(route, timed_scene, monkeypatch, tmp_path):
    from tests.test_session_input_terminal import save, inspect
    response = route.run()
    local = owner(timed_scene, monkeypatch, response)
    assert local['phase'] == 'not_dispatched' and local.get('action_executed') is False
    result = sequence(timed_scene, monkeypatch, response)
    assert result['status'] == 'interrupted' and result['action_executed'] is False
    assert result['steps'][0]['status'] == 'not_dispatched'
    assert result['completed_steps'] == [] and result['error']['code'] == 'focus_input_not_confirmed'
    root = tmp_path / 'terminal'
    command = {'kind': 'input_sequence', 'request': {'field_goal': 'Focus the fresh field',
        'text': 'fresh synthetic text', 'submit_search': False}}
    save(root, 'commands', 'original', command)
    save(root, 'responses', 'original', {'status': 'returned', 'command': command, 'result': result})
    checked = inspect(root)['commands']['original']
    assert checked['action_executed'] is False and checked['terminal_status'] == 'interrupted'


@pytest.mark.parametrize('damage', ['no_stage', 'started', 'reason', 'validator', 'true', 'attempt', 'unknown_phase'])
def test_incomplete_or_conflicting_zero_proof_remains_unknown_in_owner_and_shared_trial(
        route, timed_scene, monkeypatch, damage):
    from app.learning_memory.workflow_trial import _actual_action_executed
    response = route.run()
    data = response['data']
    if damage == 'no_stage': data.pop('dispatch_stage', None)
    elif damage == 'started': data['input_started'] = True
    elif damage == 'reason': data.setdefault('pre_click_input_rejection', {})['reason_code'] = 'other'
    elif damage == 'validator': data.setdefault('pre_click_input_rejection', {})['validator'] = 'other'
    elif damage == 'true': data['execution_path']['action_executed'] = True
    elif damage == 'attempt': data['attempts'] = [{'click_result': {'clicked': True}}]
    local = owner(timed_scene, monkeypatch, response)
    if damage == 'unknown_phase':
        local.update(phase='result_unknown', action_executed=False)
    assert local['phase'] == 'result_unknown'
    expected = True if damage == 'true' else None
    assert _actual_action_executed(local) is expected


@pytest.mark.parametrize('cancel', [False, True])
def test_real_producer_owner_sequence_queue_terminal_unlocks_only_proved_zero(
        route, timed_scene, monkeypatch, tmp_path, cancel):
    from app.core.json_snapshot import write_json_snapshot
    from tests.test_task_plan_contract import plan
    from tests.test_task_plan_runner import scene
    response = route.run()
    result = sequence(timed_scene, monkeypatch, response)
    source = plan(verification={'kind': 'agent_judgment'})
    source['schema_version'] = 'task_plan.v2'
    source['steps'][0]['action'] = {'kind': 'input_sequence', 'field_goal': 'Focus the fresh field',
        'text': 'fresh synthetic text', 'clear_existing': True, 'submit_search': False}
    def forbidden(*args, **kwargs): pytest.fail('failed input cannot call Decision')
    (tmp_path / 'queue').mkdir()
    s = scene(tmp_path / 'queue', monkeypatch, source=source, decision=SimpleNamespace(evaluate=forbidden))
    pending = s.runtime.backend.status(s.run_id)['pending']
    path = s.session / 'responses' / (pending['execution_request_id'] + '.json')
    write_json_snapshot(path, {'status': 'returned', 'command': deepcopy(pending['suggested_command']), 'result': result})
    original = path.read_bytes()
    if cancel: s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-original')
    final = s.runtime.tick(force=True)
    assert final['status'] == ('cancelled' if cancel else 'failed') and final['pending'] is None
    assert final['history'][0]['original_input_status'] == 'failed'
    assert final['history'][0]['action_executed'] is False
    s.runtime.admit('owned-close', {'kind': 'close_launched_window', 'request': {}})
    for i in range(2):
        s.runtime.control({'action': 'status', 'run_id': s.run_id}, 'status-' + str(i))
        assert s.runtime.tick(force=True) is None
    assert len(list(s.session.glob('commands/*.json'))) == 1 and path.read_bytes() == original


def test_unknown_focus_row_is_not_settled_by_outer_false_in_shared_learning_or_plan(
        route, timed_scene, monkeypatch, tmp_path):
    from app.core.json_snapshot import write_json_snapshot
    from app.learning_memory.workflow_trial import _actual_action_executed
    from tests.test_task_plan_contract import plan
    from tests.test_task_plan_runner import scene
    result = sequence(timed_scene, monkeypatch, route.run('click_unknown'))
    result['action_executed'] = False
    result['steps'][0]['action_executed'] = False
    result['steps'][0]['receipt']['response']['data']['execution_path']['action_executed'] = False
    assert _actual_action_executed(result) is None
    source = plan(verification={'kind': 'agent_judgment'})
    source['schema_version'] = 'task_plan.v2'
    source['steps'][0]['action'] = {'kind': 'input_sequence', 'field_goal': 'Focus the fresh field',
        'text': 'fresh synthetic text', 'clear_existing': True, 'submit_search': False}
    (tmp_path / 'queue').mkdir()
    s = scene(tmp_path / 'queue', monkeypatch, source=source)
    pending = s.runtime.backend.status(s.run_id)['pending']
    write_json_snapshot(s.session / 'responses' / (pending['execution_request_id'] + '.json'),
        {'status': 'returned', 'command': deepcopy(pending['suggested_command']), 'result': result})
    final = s.runtime.tick(force=True)
    assert final['wait_reason'] == 'verification_required' and final['pending'] is not None
    assert final['runner_state'] == 'waiting' and final['status'] == 'pending'
    assert final['pending'] == pending and final['wait']['reason'] == 'verification_required'
    assert final['history'] == []
    with pytest.raises(ValueError, match='task_plan_run_active'):
        s.runtime.admit('owned-close', {'kind': 'close_launched_window', 'request': {}})
    assert len(list(s.session.glob('commands/*.json'))) == 1
    for i in range(2):
        unchanged = s.runtime.control({'action': 'status', 'run_id': s.run_id}, 'unknown-status-' + str(i))
        assert unchanged['pending'] == pending and unchanged['history'] == []
    cancelled = s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-unknown')
    assert cancelled['status'] == 'cancel_requested'
    waiting = s.runtime.tick(force=True)
    assert waiting['status'] == 'cancel_requested' and waiting['pending'] == pending and waiting['history'] == []
    assert waiting['wait_reason'] == 'verification_required'
    assert len(list(s.session.glob('commands/*.json'))) == 1


@pytest.mark.parametrize('damage', ['missing', 'started', 'conflicting_action', 'conflicting_reason'])
def test_terminal_cannot_accept_forged_not_dispatched_row(route, timed_scene, monkeypatch, tmp_path, damage):
    from tests.test_session_input_terminal import save, inspect
    from app.learning_memory.workflow_trial import _actual_action_executed
    result = sequence(timed_scene, monkeypatch, route.run())
    row = result['steps'][0]
    data = row['receipt']['response']['data']
    if damage == 'missing': data.pop('pre_click_input_rejection')
    elif damage == 'started': data['input_started'] = True
    elif damage == 'conflicting_action': data['execution_path']['action_executed'] = True
    else: data['pre_click_input_rejection']['reason_code'] = 'other'
    assert _actual_action_executed(result) is None
    root = tmp_path / 'terminal'
    command = {'kind': 'input_sequence', 'request': {}}
    save(root, 'commands', 'original', command)
    save(root, 'responses', 'original', {'status': 'returned', 'command': command, 'result': result})
    with pytest.raises(ValueError, match='session_input_batch_unknown'):
        inspect(root)
