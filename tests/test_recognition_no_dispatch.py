"""识别前置拒绝保留零输入事实，取消与清理门禁不猜测嵌套默认值。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.desktop_review import local_direct_step as direct
from tests.test_local_step_timings import timed_scene, saved_report
from tests.test_task_plan_target import current_frame


GOAL = 'Open the reports folder in the current file list'


@pytest.fixture
def rejected_route(current_frame, monkeypatch):
    from app.api import action, vision
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.core.local_input_policy import _local_operator_input_scope
    capture, _ = current_frame
    identity = {'contract_version': 'windows_native_identity_observation_v1',
        'provider': 'windows_native_identity', 'status': 'observed', 'target_window_handle': 11,
        'process_id': 22, 'process_create_time': 33.0, 'executable_path': 'c:\\fixture\\file-manager.exe'}
    bound = SimpleNamespace(handle=11, process_id=22, title='Fresh synthetic application',
        process_name='file-manager.exe', rect=SimpleNamespace(left=100, top=200, right=1000, bottom=800))
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    monkeypatch.setattr(action, 'window_manager', manager)
    monkeypatch.setattr(action.screenshot_service, 'capture_window', lambda **kw:
        {'image_path': capture['image_path'], 'window_size': capture['image_size'], 'roi': None})
    monkeypatch.setattr(action, 'prepare_browser_content', lambda *args: None)
    monkeypatch.setattr(vision.VisionProviderFactory, 'load_config', lambda: {'vision': {'mode': 'local_grounding'}})
    monkeypatch.setattr(vision.VisionProviderFactory, 'create', lambda **kw: object())
    monkeypatch.setattr(vision, '_selected_local_vision_config', lambda *args: {'model_name': 'isolated'})
    monkeypatch.setattr(vision, '_uses_vista_point_grounding', lambda config: True)
    events = []
    def forbidden(*args, **kwargs):
        events.append('input_or_model')
        pytest.fail('recognition rejection must precede input and model dispatch')
    monkeypatch.setattr(vision, '_call_vista_point_prompt', forbidden)
    monkeypatch.setattr(action.input_controller, 'click_point', forbidden)
    request = ExecuteRecognitionPlanRequest(goal=GOAL,
        click_kind='double', max_execution_attempts=1, enable_post_click_verification=False,
        auto_observe_learning_artifacts=False,
        # 普通执行先校验视觉缩放参数；不依赖已移出的原生字段拦截规则。
        metadata={'task_plan_target': {'name': 'reports', 'control_type': 'Edit'},
            'vista_direct_grounding': {'max_edge': -1}},
        write_policy={'path_graph': False, 'element_memory': False, 'trace': False})
    with _local_operator_input_scope(manager=manager,
            identity_reader=SimpleNamespace(read_identity=lambda handle: deepcopy(identity)),
            identity=identity, window_rect=(100, 200, 1000, 800), enabled=lambda: True):
        response = action.execute_recognition_plan(request).model_dump()
    assert response['success'] is False
    assert response['error']['details']['details'] == 'direct_visual_max_edge_invalid'
    assert response['data']['agent_step_result']['action_executed'] is False
    assert response['data']['fallback_plan']['attempt_count'] == 0
    assert events == []
    return response


def owner_receipt(timed_scene, monkeypatch, response):
    co, _, _, _ = timed_scene
    monkeypatch.setattr(direct, '_post_action', lambda *args: deepcopy(response))
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='execute_recognition_plan', request={'goal': GOAL, 'click_kind': 'double',
            'metadata': {'task_plan_target': {'name': 'reports', 'control_type': 'Edit'}}},
        include_observation=True, observation_wait_ms=0)
    assert result == saved_report(co)
    return result


def test_real_pre_recognition_rejection_has_explicit_no_dispatch_proof(rejected_route):
    data = rejected_route['data']
    assert data.get('dispatch_status') == 'not_dispatched'
    assert data.get('dispatch_stage') == 'recognition_plan'
    assert data.get('input_started') is False
    assert data.get('execution_path', {}).get('action_executed') is False


def test_owner_receipt_and_terminal_inspector_preserve_real_pre_recognition_rejection(
        rejected_route, timed_scene, monkeypatch, tmp_path):
    from tests.test_session_input_terminal import save, inspect
    result = owner_receipt(timed_scene, monkeypatch, rejected_route)
    assert result['phase'] == 'not_dispatched'
    assert result.get('action_executed') is False
    root = tmp_path / 'terminal-session'
    command = {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': {'goal': GOAL}}
    save(root, 'commands', 'original-input', command)
    save(root, 'responses', 'original-input', {'command': command, 'status': 'returned', 'result': result})
    before = {str(path): path.read_bytes() for path in root.rglob('*.json')}
    terminal = inspect(root)['commands']['original-input']
    assert terminal['terminal_status'] == 'not_dispatched' and terminal['action_executed'] is False
    assert before == {str(path): path.read_bytes() for path in root.rglob('*.json')}


@pytest.mark.parametrize('cancel', [False, True])
def test_real_producer_zero_input_terminal_settles_original_ticket_and_unlocks_close(
        rejected_route, timed_scene, monkeypatch, tmp_path, cancel):
    from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
    from tests.test_task_plan_runner import scene
    from tests.test_task_plan_contract import plan

    result = owner_receipt(timed_scene, monkeypatch, rejected_route)
    root = tmp_path / 'runner'
    root.mkdir()
    source = plan(verification={'kind': 'agent_judgment'})
    source['schema_version'] = 'task_plan.v2'
    source['steps'][0]['action'].update(goal=GOAL, click_kind='double',
        target={'name': 'reports', 'control_type': 'Edit'})
    def forbidden(*args, **kwargs): pytest.fail('known zero-input failure must not call Decision')
    s = scene(root, monkeypatch, source=source, decision=SimpleNamespace(evaluate=forbidden))
    pending = s.runtime.backend.status(s.run_id)['pending']
    command_id = pending['execution_request_id']
    path = s.session / 'responses' / (command_id + '.json')
    write_json_snapshot(path, {'command': deepcopy(pending['suggested_command']), 'status': 'returned', 'result': result})
    original = path.read_bytes()
    if cancel:
        assert s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-original')['status'] == 'cancel_requested'
    terminal = s.runtime.tick(force=True)
    assert terminal['status'] == ('cancelled' if cancel else 'failed')
    assert terminal['runner_state'] == ('cancelled' if cancel else 'failed')
    assert terminal['pending'] is None and len(terminal['history']) == 1
    assert terminal['history'][0]['execution_request_id'] == command_id
    assert terminal['history'][0]['action_executed'] is False
    assert terminal['history'][0]['original_input_status'] == 'failed'
    assert len(list(s.session.glob('commands/*.json'))) == 1
    s.runtime.admit('owned-close', {'kind': 'close_launched_window', 'request': {}})
    for index in range(2):
        assert s.runtime.control({'action': 'status', 'run_id': s.run_id}, 'status-' + str(index))['status'] == terminal['status']
        assert s.runtime.tick(force=True) is None
    assert path.read_bytes() == original
    assert read_json_snapshot(path)['result'] == result


@pytest.mark.parametrize('damage', ['missing_proof', 'input_started', 'input_zero', 'action_conflict',
    'action_zero', 'path_conflict', 'attempt', 'attempt_bool', 'wrong_stage', 'late_failure'])
def test_nested_default_false_or_incomplete_proof_does_not_downgrade_unknown(
        rejected_route, timed_scene, monkeypatch, damage):
    response = deepcopy(rejected_route)
    data = response['data']
    if damage == 'missing_proof':
        for key in ('dispatch_status', 'dispatch_stage', 'input_started', 'execution_path'):
            data.pop(key, None)
    elif damage == 'input_started': data['input_started'] = True
    elif damage == 'input_zero': data['input_started'] = 0
    elif damage == 'action_conflict': data['agent_step_result']['action_executed'] = True
    elif damage == 'action_zero': data['action_executed'] = 0
    elif damage == 'path_conflict': data['execution_path']['action_executed'] = True
    elif damage == 'attempt': data['fallback_plan']['attempt_count'] = 1
    elif damage == 'attempt_bool': data['fallback_plan']['attempt_count'] = False
    elif damage == 'wrong_stage': data['dispatch_stage'] = 'after_input'
    else:
        response['error']['code'] = 'post_click_verification_failed'
        data.pop('recognition_plan_response')
        data['execution_path'] = {'action_executed': True}
    result = owner_receipt(timed_scene, monkeypatch, response)
    assert result['phase'] == 'result_unknown'
    assert result.get('action_executed') is not False
    assert result['automatic_retry_allowed'] is False


def test_legacy_nested_zero_does_not_reclassify_persisted_unknown(
        rejected_route, timed_scene, monkeypatch, tmp_path):
    from tests.test_session_input_terminal import save, inspect
    response = deepcopy(rejected_route)
    for key in ('dispatch_status', 'dispatch_stage', 'input_started', 'execution_path'):
        response['data'].pop(key)
    result = owner_receipt(timed_scene, monkeypatch, response)
    assert result['phase'] == 'result_unknown'
    root = tmp_path / 'legacy-shape-session'
    command = {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': {'goal': GOAL}}
    save(root, 'commands', 'original-input', command)
    save(root, 'responses', 'original-input', {'command': command, 'status': 'returned', 'result': result})
    before = {str(path): path.read_bytes() for path in root.rglob('*.json')}
    with pytest.raises(ValueError, match='session_input_synchronous_unknown'):
        inspect(root)
    assert before == {str(path): path.read_bytes() for path in root.rglob('*.json')}
