"""不存在命令的只读查询失败不能污染终态，也不能掩盖真实未知输入。"""
from threading import Condition

import pytest

from app.vision.agent_command_jobs import AgentCommandJobs, AgentCommandError
from scripts.run_local_step_session import dispatch_agent_command, run_read_text_command
from tests.test_session_input_terminal import inspect, save, job, step


def arrange(root, reference='missing', kind='agent_command_status'):
    command = {'kind': kind, 'request': {'command_id': reference}}
    if kind == 'agent_command_continue':
        command['request']['grounding_request_id'] = 'ground'
    response = {'command': command, 'status': 'failed', 'error_type': 'AgentCommandError',
                'error': 'command_unknown', 'automatic_retry_allowed': False}
    save(root, 'commands', 'query', command)
    save(root, 'responses', 'query', response)
    return command, response


def test_unknown_status_is_readonly_and_does_not_block_terminal_proof(tmp_path):
    root = tmp_path / 'session'
    # 通过实际 get 方法产生不存在状态查询的原异常，不创建工作线程。
    manager = AgentCommandJobs.__new__(AgentCommandJobs)
    manager._root = root / 'agent-commands'
    manager._condition = Condition()
    manager._snapshots = {}
    command, response = arrange(root)
    with pytest.raises(AgentCommandError, match='^command_unknown$') as caught:
        dispatch_agent_command(manager, 'query', command, None)
    response.update(error_type=type(caught.value).__name__, error=str(caught.value))
    save(root, 'responses', 'query', response)
    before = {str(p): p.read_bytes() for p in root.rglob('*.json')}
    proof = inspect(root)
    assert proof['input_terminal_settlement_verified'] is True
    assert before == {str(p): p.read_bytes() for p in root.rglob('*.json')}


@pytest.mark.parametrize('change', ['continue', 'cancel', 'self_id', 'empty_id', 'invalid_id', 'id_type',
    'extra_request', 'response_command', 'error_type', 'error', 'returned', 'result', 'action', 'orphan_worker'])
def test_only_exact_valid_unknown_status_failure_is_closed(tmp_path, change):
    root = tmp_path / 'session'
    command, response = arrange(root)
    if change == 'continue': command['kind'] = 'agent_command_continue'; command['request']['grounding_request_id'] = 'ground'
    if change == 'cancel': command['kind'] = 'agent_command_cancel'
    if change == 'self_id': command['request']['command_id'] = 'query'
    if change == 'empty_id': command['request']['command_id'] = ''
    if change == 'invalid_id': command['request']['command_id'] = '../outside'
    if change == 'id_type': command['request']['command_id'] = 123
    if change == 'extra_request': command['request']['action_executed'] = False
    if change == 'response_command': response['command'] = {}
    if change == 'error_type': response['error_type'] = 'ValueError'
    if change == 'error': response['error'] = 'execution_result_unknown'
    if change == 'returned': response['status'] = 'returned'
    if change == 'result': response['result'] = {'action_executed': True}
    if change == 'action': response['action_executed'] = True
    if change == 'orphan_worker': save(root, 'agent-commands', 'missing', {'command_id': 'missing'})
    save(root, 'commands', 'query', command)
    save(root, 'responses', 'query', response)
    with pytest.raises(ValueError, match='session_input_'):
        inspect(root)


@pytest.mark.parametrize('same_reference', [False, True])
def test_status_failure_does_not_mask_existing_unknown_input(tmp_path, same_reference):
    root = tmp_path / 'session'
    _, worker = job(root)
    worker['dispatch_attempts'][0]['status'] = 'unknown'
    worker['dispatch_attempts'][0]['action_executed'] = None
    worker['action_executed'] = None
    save(root, 'agent-commands', 'input', worker)
    arrange(root, reference='input' if same_reference else 'missing')
    with pytest.raises(ValueError, match='session_input_'):
        inspect(root)


def test_unknown_status_claim_cannot_reference_an_existing_completed_input(tmp_path):
    root = tmp_path / 'session'
    job(root)
    arrange(root, reference='input')
    with pytest.raises(ValueError, match='session_input_'):
        inspect(root)


@pytest.mark.parametrize('kind', ['read_text', 'step'])
def test_unknown_worker_query_preserves_existing_synchronous_terminal(tmp_path, kind):
    root = tmp_path / 'session'
    if kind == 'read_text':
        command = {'kind': kind, 'max_chars': 10000}
        result, _ = run_read_text_command(lambda: {}, command, recognition_source='agent_current')
    else:
        command = {'kind': kind, 'operation': 'type_text', 'request': {'text': 'fresh'}}
        result = step()
    save(root, 'commands', 'input', command)
    save(root, 'responses', 'input', {'command': command, 'status': 'returned', 'result': result})
    query, response = arrange(root, reference='input')
    manager = AgentCommandJobs.__new__(AgentCommandJobs)
    manager._root = root / 'agent-commands'
    manager._condition = Condition()
    manager._snapshots = {}
    with pytest.raises(AgentCommandError, match='^command_unknown$') as caught:
        dispatch_agent_command(manager, 'query', query, None)
    response.update(error_type=type(caught.value).__name__, error=str(caught.value))
    save(root, 'responses', 'query', response)
    before = {str(p): p.read_bytes() for p in root.rglob('*.json')}
    proof = inspect(root)
    assert proof['input_terminal_settlement_verified'] is True
    assert proof['commands']['input']['action_executed'] is (None if kind == 'read_text' else True)
    assert proof['commands']['query']['action_executed'] is None
    assert proof['commands']['query']['referenced_command_id'] == 'input'
    assert before == {str(p): p.read_bytes() for p in root.rglob('*.json')}


@pytest.mark.parametrize('damage', ['missing', 'unknown', 'worker', 'control', 'deferred'])
def test_unknown_worker_query_cannot_close_unproven_existing_command(tmp_path, damage):
    root = tmp_path / 'session'
    command = {'kind': 'step', 'operation': 'type_text', 'request': {'text': 'fresh'}}
    if damage == 'control':
        command = {'kind': 'agent_command_status', 'request': {'command_id': 'query'}}
    if damage == 'deferred':
        command = {'kind': 'learning_workflow', 'request': {'action': 'run', 'run_id': 'trial-fresh', 'mode': 'single'}}
    save(root, 'commands', 'input', command)
    if damage not in {'missing', 'deferred'}:
        save(root, 'responses', 'input', {'command': command, 'status': 'returned',
             'result': {} if damage == 'unknown' else step()})
    if damage == 'worker':
        save(root, 'agent-commands', 'input', {'command_id': 'input'})
    arrange(root, reference='input')
    with pytest.raises(ValueError, match='session_input_'):
        inspect(root)
