"""已核验输入后的点击和 Enter 必须分别保留派发事实。"""
from copy import deepcopy

import pytest

from app.core.input_sequence_partial import _digest
from app.core.key_dispatch import create_key_dispatch
from tests.test_visual_compound_settlement import compound, native_closed, payload, classify
from tests.test_input_sequence_search_partial import TARGET
from tests.test_key_no_dispatch import key_route
from tests.test_type_text_no_dispatch import route
from tests.test_recognition_dispatch_boundary import route as recognition_route
from tests.test_local_step_timings import timed_scene


@pytest.fixture
def submitted(compound):
    value = deepcopy(compound)
    result = value['result']
    request = value['command']['request']
    request['submit_search'] = result['submit_search'] = True
    local, original = payload(value)
    point = deepcopy(original['point'])
    proof = {'schema': 'visual_field_proof.v1', 'phase': 'value', 'request_sha256': 'b'*64,
        'input_receipt_sha256': _digest(local), 'focus_receipt_sha256': _digest(local),
        'field': {'field_goal': request['field_goal'], 'expected_text': request['text'],
            'click_point': point, 'window_identity': deepcopy(TARGET)}}
    result['field_proofs'] = [proof]
    search = deepcopy(local)
    search.update(step_id='current-field-submit', operation='execute_recognition_plan', phase='returned')
    search['request'] = {'goal': request['field_goal'], 'click_kind': 'single'}
    data = search['response']['data']
    data = data.get('result', data)
    data.pop('visual_compound_input')
    dispatch = create_key_dispatch('Enter', **point)
    dispatch.record('started')
    dispatch.record('completed')
    key = {'pressed': True, 'key': 'Enter', 'window_handle': TARGET['handle'],
        'text_retyped': False, 'key_dispatch': dispatch.reference()}
    data['visual_submit'] = {'schema': 'visual_submit.v1', 'point': point,
        'field_goal': request['field_goal'], 'value_request_sha256': proof['request_sha256'],
        'input_receipt_sha256': proof['input_receipt_sha256'],
        'window_identity': deepcopy(TARGET), 'window_rect': deepcopy(original['window_rect']),
        'execution_request_id': original['execution_request_id'],
        'click_result_sha256': _digest(data['click_result']), 'key_result': key,
        'key_dispatch': dispatch.reference()}
    result['steps'].append({'name': 'search', 'operation': 'execute_recognition_plan',
        'status': 'returned', 'action_executed': True, 'receipt': search})
    result.update(status='completed', phase='returned', completed_steps=['focus_type','check_input','search'],
        input_check={'status':'verified','source':'decision_visual','evidence_kind':'visual'})
    result.pop('error', None)
    result.pop('interrupted_at', None)
    return value


def suffix(value):
    row = value['result']['steps'][-1]
    data = row['receipt']['response']['data']
    return row, data.get('result', data)


def test_closed_click_and_enter_are_completed(submitted):
    assert classify(submitted, succeeded=True) == 'completed'


@pytest.mark.parametrize('state', ['not_started','started','missing'])
def test_click_alone_does_not_prove_enter(submitted, state):
    row, data = suffix(submitted)
    fact = data['visual_submit']
    dispatch = create_key_dispatch('Enter', **fact['point'])
    if state == 'started':
        dispatch.record('started')
    fact['key_dispatch'] = None if state == 'missing' else dispatch.reference()
    fact.pop('key_result')
    row['status'] = row['receipt']['phase'] = 'result_unknown'
    row['receipt']['response']['success'] = False
    submitted['result'].update(status='interrupted',phase='search',interrupted_at='search',
        completed_steps=['focus_type','check_input'],
        error={'type':'InputSequenceInterrupted','code':'search_input_not_confirmed'})
    assert classify(submitted) == ('failed' if state == 'not_started' else 'unknown')


@pytest.mark.parametrize('damage', ['value','input','identity','point','click','key','events','scope','request','execution'])
def test_forged_or_incomplete_submit_never_closes_success(submitted, damage):
    row, data = suffix(submitted)
    fact = data['visual_submit']
    if damage == 'value': fact['value_request_sha256'] = 'f'*64
    elif damage == 'input': fact['input_receipt_sha256'] = 'f'*64
    elif damage == 'identity': fact['window_identity']['process_id'] += 1
    elif damage == 'point': fact['point']['x'] += 1
    elif damage == 'click': fact['click_result_sha256'] = 'f'*64
    elif damage == 'key': fact['key_result']['key'] = 'Tab'
    elif damage == 'events': fact['key_dispatch']['events'] = []
    elif damage == 'scope': row['receipt']['local_input_scope_closed'] = False
    elif damage == 'request': row['receipt']['request']['goal'] += ' changed'
    else: fact['execution_request_id'] += '-other'
    assert classify(submitted, succeeded=True) == 'unknown'
