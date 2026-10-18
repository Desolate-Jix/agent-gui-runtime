"""当前派发后无观察与明确未派发回执仍须严格证明。"""
from copy import deepcopy
import pytest
from tests.test_session_input_terminal import save, inspect


def fixture(root, kind):
    if kind == 'grounding':
        command = {'kind': 'grounding_execute', 'request': {'grounding_request_id': 'ground'}}
        result = {'contract_version': 'local_direct_step_v1', 'operation': 'execute_recognition_plan',
                  'phase': 'returned_observation_unavailable', 'response': {'data': {'action_executed': True}}}
        state = {'contract_version': 'grounding_handoff.v1', 'request_id': 'ground', 'execution_id': 'input',
                 'phase': 'completed', 'execution_result': deepcopy(result), 'input_attempted': True, 'input_dispatched': None}
        save(root, 'grounding', 'ground', state)
    else:
        command = {'kind': 'step', 'operation': 'scroll'}
        result = {'contract_version': 'local_direct_step_v1', 'operation': 'scroll', 'phase': 'not_dispatched',
                  'response': {'success': False, 'error': {'code': 'scroll_precondition_rejected'},
                    'data': {'dispatch_status': 'not_dispatched', 'scrolled': False, 'input_started': False,
                             'precondition_decision': {'decision': 'REJECT'}}}}
    save(root, 'commands', 'input', command)
    save(root, 'responses', 'input', {'command': command, 'status': 'returned', 'result': result})
    return result


@pytest.mark.parametrize('kind', ['grounding', 'scroll'])
def test_current_receipt_terminal_readonly(tmp_path, kind):
    root = tmp_path / 'session'
    fixture(root, kind)
    before = {str(p): p.read_bytes() for p in root.rglob('*.json')}
    item = inspect(root)['commands']['input']
    assert item['action_executed'] is (kind == 'grounding')
    assert item['terminal_status'] == ('completed' if kind == 'grounding' else 'not_dispatched')
    assert before == {str(p): p.read_bytes() for p in root.rglob('*.json')}


@pytest.mark.parametrize('field', ['dispatch_status', 'scrolled', 'input_started', 'success', 'error', 'decision', 'phase', 'schema'])
def test_incomplete_scroll_proof_rejected(tmp_path, field):
    root = tmp_path / 'session'
    result = fixture(root, 'scroll')
    response = result['response']
    if field in ('dispatch_status', 'scrolled', 'input_started'): response['data'].pop(field)
    elif field == 'decision': response['data']['precondition_decision']['decision'] = 'ALLOW'
    elif field == 'phase': result['phase'] = 'result_unknown'
    elif field == 'schema': result['contract_version'] = 'foreign'
    else: response.pop(field)
    save(root, 'responses', 'input', {'command': {'kind': 'step', 'operation': 'scroll'}, 'status': 'returned', 'result': result})
    with pytest.raises(ValueError, match='session_input_'): inspect(root)


@pytest.mark.parametrize('field', ['schema', 'operation', 'phase', 'action', 'binding', 'orphan'])
def test_observation_unavailable_uncertain_or_foreign_rejected(tmp_path, field):
    root = tmp_path / 'session'
    result = fixture(root, 'grounding')
    if field == 'schema': result['contract_version'] = 'foreign'
    elif field == 'operation': result['operation'] = 'scroll'
    elif field == 'phase': result['phase'] = 'result_unknown'
    elif field == 'action': result['response']['data']['action_executed'] = None
    if field in ('schema', 'operation', 'phase', 'action'):
        import json
        state = json.loads((root / 'grounding' / 'ground.json').read_text(encoding='utf-8'))
        state['execution_result'] = deepcopy(result)
        save(root, 'grounding', 'ground', state)
    command = {'kind': 'grounding_execute', 'request': {'grounding_request_id': 'ground'}}
    if field == 'binding': command['request']['grounding_request_id'] = 'other'
    if field == 'orphan':
        save(root, 'grounding', 'orphan', {'execution_id': 'foreign'})
    save(root, 'responses', 'input', {'command': command, 'status': 'returned', 'result': result})
    with pytest.raises(ValueError, match='session_input_'): inspect(root)
