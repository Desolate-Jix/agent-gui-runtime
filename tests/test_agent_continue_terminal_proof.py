"""真实 continue 派发的 grounding 只能凭完整原终态互证。"""
from copy import deepcopy
import pytest
from tests.test_session_input_terminal import inspect, save, job, step


def arrange(root):
    _, worker = job(root)
    command = {'kind': 'agent_command_continue', 'request': {'command_id': 'input', 'grounding_request_id': 'ground'}}
    response = {'command': command, 'status': 'returned', 'result': {'contract_version': 'agent_command.v1', 'command_id': 'input', 'status': 'running'}}
    grounding = {'contract_version': 'grounding_handoff.v1', 'request_id': 'ground', 'execution_id': 'continue',
                 'phase': 'completed', 'input_attempted': True, 'input_dispatched': None, 'execution_result': step()}
    save(root, 'commands', 'continue', command)
    save(root, 'responses', 'continue', response)
    save(root, 'grounding', 'ground', grounding)
    return command, response, grounding, worker


def test_real_continue_terminal_binding_is_readonly(tmp_path):
    root = tmp_path / 'session'
    arrange(root)
    before = {str(p): p.read_bytes() for p in root.rglob('*.json')}
    assert inspect(root)['commands']['input']['terminal_status'] == 'completed'
    assert before == {str(p): p.read_bytes() for p in root.rglob('*.json')}


@pytest.mark.parametrize('change', ['ground_id', 'worker_id', 'response_command', 'response_status', 'missing_response',
    'missing_acceptance', 'running', 'unknown_dispatch', 'receipt', 'action', 'phase', 'attempted', 'multiple', 'ground_schema'])
def test_unproven_continue_grounding_remains_rejected(tmp_path, change):
    root = tmp_path / 'session'
    command, response, grounding, worker = arrange(root)
    if change == 'ground_id': command['request']['grounding_request_id'] = 'other'
    if change == 'worker_id': command['request']['command_id'] = 'other'
    if change == 'response_command': response['command'] = {}
    if change == 'response_status': response['status'] = 'failed'
    if change == 'running': worker['status'] = 'running'
    if change == 'unknown_dispatch': worker['dispatch_in_progress'] = True
    if change == 'receipt': grounding['execution_result']['extra'] = 'changed'
    if change == 'action': grounding['execution_result']['response']['data']['action_executed'] = False
    if change == 'phase': grounding['phase'] = 'executing'
    if change == 'attempted': grounding['input_attempted'] = None
    if change == 'ground_schema': grounding['contract_version'] = 'other'
    if change == 'multiple':
        worker['dispatch_attempts'].append({**deepcopy(worker['dispatch_attempts'][0]), 'index': 2})
        worker['last_execution']['attempt_index'] = 2
    save(root, 'commands', 'continue', command)
    save(root, 'responses', 'continue', response)
    save(root, 'grounding', 'ground', grounding)
    save(root, 'agent-commands', 'input', worker)
    if change == 'missing_response': (root / 'responses/continue.json').unlink()
    if change == 'missing_acceptance': (root / 'responses/input.json').unlink()
    with pytest.raises(ValueError, match='session_input_'):
        inspect(root)


def arrange_batch(root, kind='input_sequence'):
    command, response, grounding, worker = arrange(root)
    original = {'kind': kind, 'request': {'field_goal': 'Search', 'text': 'current', 'submit_search': False}}
    focus = deepcopy(grounding['execution_result'])
    focus['step_id'] = 'focus-native-step'
    focus['operation'] = 'execute_recognition_plan'
    focus['contract_version'] = 'local_direct_step_v1'
    typed = step()
    typed['step_id'] = 'type-native-step'
    typed['operation'] = 'type_text'
    typed['contract_version'] = 'local_direct_step_v1'
    grounding['execution_result'] = focus
    rows = [{'operation': 'execute_recognition_plan', 'status': 'returned', 'action_executed': True, 'receipt': focus},
            {'operation': 'type_text', 'status': 'returned', 'action_executed': True, 'receipt': typed}]
    worker['dispatch_attempts'] = [
        {'index': i + 1, 'operation': row['operation'], 'status': 'returned', 'action_executed': True}
        for i, row in enumerate(rows)]
    worker['last_execution'] = {'attempt_index': 2, 'operation': 'type_text', 'receipt': deepcopy(typed)}
    worker['result'] = {'contract_version': 'input_sequence_v1' if kind == 'input_sequence' else 'form_fill_v1',
                        'status': 'completed', 'action_executed': True}
    if kind == 'input_sequence': worker['result']['steps'] = rows
    else: worker['result']['fields'] = [{'steps': rows}]
    save(root, 'commands', 'input', original)
    save(root, 'responses', 'input', {'command': original, 'status': 'returned', 'result': {
        'contract_version': 'agent_command.v1', 'command_id': 'input', 'status': 'running', 'action_executed': False}})
    save(root, 'grounding', 'ground', grounding)
    save(root, 'agent-commands', 'input', worker)
    return worker, rows


@pytest.mark.parametrize('kind', ['input_sequence', 'form_fill'])
def test_completed_batch_preserves_earlier_grounding_receipt_for_recovery(tmp_path, kind):
    root = tmp_path / 'session'
    arrange_batch(root, kind)
    before = {str(p): p.read_bytes() for p in root.rglob('*.json')}
    proof = inspect(root)
    assert proof['commands']['input']['terminal_status'] == 'completed'
    assert proof['commands']['input']['action_executed'] is True
    assert before == {str(p): p.read_bytes() for p in root.rglob('*.json')}


@pytest.mark.parametrize('change', ['missing_earlier', 'reordered', 'missing_step', 'action_conflict',
    'duplicate_receipt', 'duplicate_native_id', 'receipt_operation', 'last_mismatch', 'wrong_batch_kind', 'unknown_batch', 'extra_attempt'])
def test_batch_continue_requires_every_ordered_original_dispatch_receipt(tmp_path, change):
    root = tmp_path / 'session'
    worker, rows = arrange_batch(root)
    if change == 'missing_earlier': rows[0].pop('receipt')
    if change == 'reordered': rows.reverse()
    if change == 'missing_step': rows.pop(0)
    if change == 'action_conflict': rows[0]['action_executed'] = False
    if change == 'duplicate_receipt': rows[1]['receipt'] = deepcopy(rows[0]['receipt']); worker['last_execution']['receipt'] = rows[1]['receipt']
    if change == 'duplicate_native_id': rows[1]['receipt']['step_id'] = rows[0]['receipt']['step_id']; worker['last_execution']['receipt'] = deepcopy(rows[1]['receipt'])
    if change == 'receipt_operation':
        rows[0]['receipt']['operation'] = 'type_text'
        import json
        ground = json.loads((root / 'grounding/ground.json').read_text(encoding='utf-8'))
        ground['execution_result'] = deepcopy(rows[0]['receipt'])
        save(root, 'grounding', 'ground', ground)
    if change == 'last_mismatch': worker['last_execution']['receipt']['extra'] = 'other'
    if change == 'wrong_batch_kind': worker['result']['contract_version'] = 'form_fill_v1'
    if change == 'unknown_batch': worker['result']['status'] = 'running'
    if change == 'extra_attempt': worker['dispatch_attempts'].append({**worker['dispatch_attempts'][-1], 'index': 3}); worker['last_execution']['attempt_index'] = 3
    save(root, 'agent-commands', 'input', worker)
    with pytest.raises(ValueError, match='session_input_'):
        inspect(root)


def test_one_batch_dispatch_cannot_belong_to_two_grounding_executions(tmp_path):
    root = tmp_path / 'session'
    arrange_batch(root)
    import json
    ground = json.loads((root / 'grounding/ground.json').read_text(encoding='utf-8'))
    command = {'kind': 'agent_command_continue', 'request': {'command_id': 'input', 'grounding_request_id': 'ground2'}}
    ground.update(request_id='ground2', execution_id='continue2')
    save(root, 'grounding', 'ground2', ground)
    save(root, 'commands', 'continue2', command)
    save(root, 'responses', 'continue2', {'command': command, 'status': 'returned', 'result': {
        'contract_version': 'agent_command.v1', 'command_id': 'input', 'status': 'running'}})
    with pytest.raises(ValueError, match='session_input_'):
        inspect(root)
