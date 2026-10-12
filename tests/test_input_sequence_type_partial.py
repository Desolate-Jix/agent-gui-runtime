"""已点击但真实键入路由尚未派发时，结算原票据且保留点击事实。"""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from app.core.input_sequence_partial import original_input_status
from tests.test_local_step_timings import timed_scene
from tests.test_type_text_no_dispatch import route, _POST_ACTION
from tests.test_recognition_dispatch_boundary import route as recognition_route


REQUEST = {'field_goal': 'Focus the fresh field', 'text': 'fresh text',
    'clear_existing': True, 'submit_search': True}
TARGET = {'handle': 321, 'process_id': 12, 'process_create_time': 123.5}


@pytest.fixture
def focus_response(recognition_route):
    return recognition_route.run('success')


@pytest.fixture
def closed(focus_response, route, monkeypatch):
    from app.execution import local_direct_step as direct
    monkeypatch.setattr(direct, '_post_action', lambda *a: deepcopy(focus_response))
    focus = route.coordinator.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='execute_recognition_plan', request={'goal': REQUEST['field_goal']})
    monkeypatch.setattr(direct, '_post_action', _POST_ACTION)
    typed = route.run()
    assert typed.get('type_text_no_dispatch')
    result = {'contract_version': 'input_sequence_v1', 'sequence_id': 'synthetic-type-sequence',
        'status': 'interrupted', 'phase': 'type', 'interrupted_at': 'type', 'action_executed': True,
        'completed_steps': ['focus'], 'automatic_retry_allowed': False, 'task_effect_verified': None,
        'target': {'handle': 321, 'process_id': 12}, 'input_check': {'status': 'not_checked'},
        'text_length': len(REQUEST['text']), 'text_sha256': sha256(REQUEST['text'].encode()).hexdigest(),
        'submit_search': True, 'error': {'type': 'InputSequenceInterrupted', 'code': 'type_input_not_confirmed'},
        'steps': [{'name': name, 'operation': operation, 'status': receipt['phase'],
            'action_executed': executed, 'receipt': receipt} for name, operation, executed, receipt in [
                ('focus', 'execute_recognition_plan', True, focus), ('type', 'type_text', False, typed)]]}
    return json.loads(json.dumps({'status': 'failed',
        'command': {'kind': 'input_sequence', 'request': deepcopy(REQUEST)}, 'result': result}))


def test_focus_completed_and_authenticated_zero_type_is_known_partial_failure(closed):
    assert original_input_status(closed, closed['command'], succeeded=False,
        action_executed=True, target_identity=TARGET) == 'failed'
    assert closed['result']['action_executed'] is True
    assert closed['result']['steps'][0]['action_executed'] is True


@pytest.mark.parametrize('damage', ['proof', 'started', 'scope', 'identity', 'request',
    'clear_existing', 'click_before_typing', 'focus', 'extra_row', 'input_check'])
def test_incomplete_type_boundary_remains_unknown(closed, damage):
    result = closed['result']
    typed = result['steps'][1]['receipt']
    if damage == 'proof': typed.pop('type_text_no_dispatch')
    elif damage == 'started': typed['response']['data']['typing_dispatch']['selection_dispatch'] = 'started'
    elif damage == 'scope': typed['local_input_scope_closed'] = False
    elif damage == 'identity': typed['target_identity']['process_create_time'] += 1
    elif damage == 'request': closed['command']['request']['text'] = 'other'
    elif damage == 'clear_existing': closed['command']['request']['clear_existing'] = False
    elif damage == 'click_before_typing': typed['request']['click_before_typing'] = True
    elif damage == 'focus': result['steps'][0]['receipt']['response'] = []
    elif damage == 'extra_row': result['steps'].append(deepcopy(result['steps'][-1]))
    else: result['input_check']['status'] = 'matched'
    assert original_input_status(closed, closed['command'], succeeded=False,
        action_executed=True, target_identity=TARGET) == 'unknown'


@pytest.mark.parametrize('known', [True, False])
def test_cancel_settles_only_authenticated_zero_type(closed, tmp_path, monkeypatch, known):
    from tests import test_input_sequence_focus_partial as queue
    monkeypatch.setattr(queue, 'REQUEST', deepcopy(REQUEST))
    if not known:
        closed['result']['steps'][1]['receipt'].pop('type_text_no_dispatch')
    s, pending, path, calls = queue.queued(tmp_path, monkeypatch, closed['result'])
    original = queue.persist_original(s, pending, path, closed['result'], async_terminal=True)
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
