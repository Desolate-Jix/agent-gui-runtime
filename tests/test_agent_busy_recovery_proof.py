"""前派发拒绝需要原结构化事实，不能把普通失败猜成零输入。"""
from types import SimpleNamespace
import pytest
from tests.test_session_input_terminal import inspect, save
from scripts.run_local_step_session import check_agent_command_admission


def test_busy_admission_can_be_settled_without_an_input_worker(tmp_path):
    root = tmp_path / 'session'
    command = {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': {'goal': 'Find'}}
    with pytest.raises(ValueError) as caught:
        check_agent_command_admission(SimpleNamespace(active=True), command['kind'], command)
    error = caught.value
    assert hasattr(error, 'before_dispatch_result'), 'busy rejection must preserve zero-dispatch facts at its producer'
    response = {'command': command, 'status': 'failed', 'error_type': type(error).__name__,
                'error': str(error), 'result': error.before_dispatch_result('rejected')}
    save(root, 'commands', 'rejected', command)
    save(root, 'responses', 'rejected', response)
    before = {str(p): p.read_bytes() for p in root.rglob('*.json')}
    result = inspect(root)
    assert result['commands']['rejected']['terminal_status'] == 'failed'
    assert result['commands']['rejected']['action_executed'] is False
    assert before == {str(p): p.read_bytes() for p in root.rglob('*.json')}


@pytest.mark.parametrize('change', ['legacy', 'command_id', 'input_attempted', 'action', 'error_type', 'returned', 'worker'])
def test_unproven_busy_failure_still_blocks_recovery(tmp_path, change):
    root = tmp_path / 'session'
    command = {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': {'goal': 'Find'}}
    result = {'contract_version': 'input_admission_rejection.v1', 'command_id': 'rejected',
              'status': 'rejected_before_dispatch', 'reason': 'agent_command_in_progress',
              'input_attempted': False, 'action_executed': False}
    response = {'command': command, 'status': 'failed', 'error_type': 'AgentCommandAdmissionError',
                'error': 'agent_command_in_progress: continue, inspect or cancel the original command', 'result': result}
    if change == 'legacy': response['result'] = {}
    if change == 'command_id': result['command_id'] = 'other'
    if change == 'input_attempted': result['input_attempted'] = None
    if change == 'action': result['action_executed'] = True
    if change == 'error_type': response['error_type'] = 'ValueError'
    if change == 'returned': response['status'] = 'returned'
    if change == 'worker': save(root, 'agent-commands', 'rejected', {'command_id': 'rejected'})
    save(root, 'commands', 'rejected', command)
    save(root, 'responses', 'rejected', response)
    with pytest.raises(ValueError, match='session_input_'):
        inspect(root)
