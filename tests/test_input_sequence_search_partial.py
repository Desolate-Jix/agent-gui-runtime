"""已完成填写加可信零按键后缀可终结；真实未知派发仍保留原票据。"""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from app.core.input_sequence_partial import original_input_status
from tests.test_key_no_dispatch import key_route
from tests.test_local_step_timings import timed_scene
from tests.test_type_text_no_dispatch import route, _POST_ACTION
from tests.test_recognition_dispatch_boundary import route as recognition_route


REQUEST = {'field_goal': 'Focus the fresh field', 'text': 'fresh text', 'clear_existing': True, 'submit_search': True}
TARGET = {'handle': 321, 'process_id': 12, 'process_create_time': 123.5}


@pytest.fixture
def closed(key_route, recognition_route, monkeypatch):
    from app.api import action
    from app.desktop_review import local_direct_step as direct
    co = key_route.route.coordinator
    response = recognition_route.run('success')
    monkeypatch.setattr(direct, '_post_action', lambda *a: deepcopy(response))
    focus = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='execute_recognition_plan', request={'goal': REQUEST['field_goal']},
        include_observation=True, observation_wait_ms=0)
    monkeypatch.setattr(action, 'window_manager', co._windows())
    monkeypatch.setattr(action, 'input_controller', key_route.controller)
    monkeypatch.setattr(direct, '_post_action', _POST_ACTION)
    key_route.state.failure = 'none'
    typed = key_route.route.run(x=184, y=516)
    key_route.state.failure = 'before'
    search = key_route.run(x=184, y=516)
    assert focus['response']['success'] is True and typed['response']['success'] is True
    assert search['phase'] == 'not_dispatched'
    digest = sha256(REQUEST['text'].encode('utf-8')).hexdigest()
    result = {'contract_version': 'input_sequence_v1', 'sequence_id': 'synthetic-search-sequence',
        'status': 'interrupted', 'phase': 'search', 'interrupted_at': 'search', 'action_executed': True,
        'completed_steps': ['focus', 'type', 'check_input'], 'automatic_retry_allowed': False,
        'task_effect_verified': None, 'target': {'handle': 321, 'process_id': 12},
        'text_sha256': digest, 'text_length': len(REQUEST['text']), 'submit_search': True,
        'input_check': {'status': 'matched', 'value_sha256': digest},
        'error': {'type': 'InputSequenceInterrupted', 'code': 'search_input_not_confirmed'},
        'steps': [{'name': name, 'operation': operation, 'status': receipt['phase'],
            'action_executed': executed, 'receipt': receipt} for name, operation, executed, receipt in [
                ('focus', 'execute_recognition_plan', True, focus), ('type', 'type_text', True, typed),
                ('search', 'press_key', False, search)]]}
    command = {'kind': 'input_sequence', 'request': deepcopy(REQUEST)}
    return json.loads(json.dumps({'status': 'returned', 'command': command, 'result': result}))


def test_completed_prefix_and_proven_zero_enter_is_known_failed_input(closed):
    assert original_input_status(closed, closed['command'], succeeded=False,
        action_executed=True, target_identity=TARGET) == 'failed'
    assert closed['result']['action_executed'] is True


@pytest.mark.parametrize('damage', ['key_proof', 'key_unknown', 'key_started', 'type_unknown', 'type_partial',
    'type_text', 'type_identity', 'scope_open', 'extra_row', 'completed_steps', 'input_check', 'request', 'command',
    'type_response', 'type_path', 'type_events', 'focus_response', 'focus_path', 'focus_clicked',
    'type_native', 'type_executable'])
def test_incomplete_prefix_or_unknown_key_remains_unknown(closed, damage):
    result, command = closed['result'], deepcopy(closed['command'])
    typed, search = result['steps'][1], result['steps'][2]
    if damage == 'key_proof': search['receipt'].pop('key_no_dispatch')
    elif damage == 'key_unknown': search['status'] = search['receipt']['phase'] = 'result_unknown'
    elif damage == 'key_started': search['receipt']['response']['data']['key_dispatch']['dispatch'] = 'started'
    elif damage == 'type_unknown': typed['status'] = typed['receipt']['phase'] = 'result_unknown'
    elif damage == 'type_partial': typed['receipt']['response']['data']['result']['type_result']['typing_dispatch']['text_dispatch'] = 'started'
    elif damage == 'type_text': typed['receipt']['request']['text_sha256'] = 'f' * 64
    elif damage == 'type_identity': typed['receipt']['target_identity']['process_create_time'] += 1
    elif damage == 'scope_open': typed['receipt']['local_input_scope_closed'] = False
    elif damage == 'extra_row': result['steps'].append(deepcopy(search))
    elif damage == 'completed_steps': result['completed_steps'].append('search')
    elif damage == 'input_check': result['input_check']['status'] = 'unavailable'
    elif damage == 'request': command['request']['text'] = 'other text'
    elif damage == 'type_response': typed['receipt']['response'] = []
    elif damage == 'type_path': typed['receipt']['response']['data']['result']['execution_path'] = 'unknown'
    elif damage == 'type_events': typed['receipt']['response']['data']['result']['type_result']['typing_dispatch']['events'] = []
    elif damage == 'type_native': typed['receipt']['target_identity']['status'] = 'unavailable'
    elif damage == 'type_executable': typed['receipt']['target_identity']['executable_path'] = 'C:/other.exe'
    elif damage == 'focus_response': result['steps'][0]['receipt']['response'] = []
    elif damage == 'focus_path': result['steps'][0]['receipt']['response']['data']['result']['execution_path'] = 'unknown'
    elif damage == 'focus_clicked': result['steps'][0]['receipt']['response']['data']['result']['click_result']['clicked'] = False
    else: closed['command']['kind'] = 'press_key'
    assert original_input_status(closed, command, succeeded=False, action_executed=True,
        target_identity=TARGET) == 'unknown'


@pytest.mark.parametrize('known', [True, False])
@pytest.mark.parametrize('async_terminal', [False, True])
def test_cancel_settles_only_closed_prefix_with_proven_zero_search(closed, tmp_path, monkeypatch, known, async_terminal):
    from tests import test_input_sequence_focus_partial as queue
    monkeypatch.setattr(queue, 'REQUEST', deepcopy(REQUEST))
    if not known:
        closed['result']['steps'][-1]['receipt'].pop('key_no_dispatch')
    s, pending, path, calls = queue.queued(tmp_path, monkeypatch, closed['result'])
    original = queue.persist_original(s, pending, path, closed['result'], async_terminal=async_terminal)
    terminal_path = s.session / 'agent-commands' / (pending['execution_request_id'] + '.json')
    terminal_bytes = terminal_path.read_bytes() if async_terminal else None
    if async_terminal:
        from app.learning_memory.receipt_adapter import resolve_execution_receipt
        effective, terminal = resolve_execution_receipt(json.loads(original), path, pending['execution_request_id'])
        assert effective['status'] == 'failed' and terminal['status'] == 'failed'
        assert original_input_status(effective, pending['suggested_command'], succeeded=False,
            action_executed=True, target_identity=TARGET) == ('failed' if known else 'unknown')
    s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-original')
    final = s.runtime.tick(force=True)
    if known:
        assert final['status'] == 'cancelled' and final['pending'] is None
        assert final['history'][0]['original_input_status'] == 'failed'
        assert final['history'][0]['action_executed'] is True
        s.runtime.admit('owned-close', {'kind': 'close_launched_window', 'request': {}})
    else:
        assert final['status'] == 'cancel_requested' and final['pending'] == pending
        assert final['history'] == [] and final['wait_reason'] == 'verification_required'
    assert path.read_bytes() == original and calls == []
    if async_terminal:
        assert terminal_path.read_bytes() == terminal_bytes
    assert len(list(s.session.glob('commands/trial-exec-*.json'))) == 1
