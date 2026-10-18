"""活动命令前置拒绝在共享终态合同中保持原证明。"""
from copy import deepcopy
import json

import pytest

from app.core.session_input_terminal import inspect_session_input_terminal
from scripts.run_local_step_session import AgentCommandAdmissionError, preserve_input_admission_rejection


def recorded_rejection(tmp_path):
    root = tmp_path / 'session-busy'
    command = {'kind': 'capture'}
    error = AgentCommandAdmissionError()
    receipt = {'command': deepcopy(command), 'status': 'failed',
               'error_type': type(error).__name__, 'error': str(error)}
    preserve_input_admission_rejection(receipt, error, 'rejected')
    for folder, value in [('commands', command), ('responses', receipt)]:
        path = root / folder / 'rejected.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return root, command, receipt


def test_real_busy_rejection_remains_inspectable_after_contract_module_move(tmp_path):
    root, _, _ = recorded_rejection(tmp_path)
    before = {path: path.read_bytes() for path in root.rglob('*.json')}
    proof = inspect_session_input_terminal(root, root.parent / 'memory-library')
    assert proof['commands']['rejected'] == {
        'kind': 'capture', 'terminal_status': 'failed', 'action_executed': False}
    assert proof['input_terminal_settlement_verified'] is True
    assert before == {path: path.read_bytes() for path in root.rglob('*.json')}


@pytest.mark.parametrize('change', ['input', 'action', 'safe_control', 'wrong_id', 'legacy'])
def test_unproven_busy_rejection_still_refuses(tmp_path, change):
    root, command, receipt = recorded_rejection(tmp_path)
    if change == 'input':
        receipt['result']['input_attempted'] = True
    elif change == 'action':
        receipt['result']['action_executed'] = True
    elif change == 'wrong_id':
        receipt['result']['command_id'] = 'another'
    elif change == 'legacy':
        receipt.pop('result')
    else:
        command['kind'] = 'agent_command_status'
        command['request'] = {'command_id': 'original'}
        receipt['command'] = deepcopy(command)
        (root / 'commands/rejected.json').write_text(json.dumps(command), encoding='utf-8')
    (root / 'responses/rejected.json').write_text(json.dumps(receipt), encoding='utf-8')
    with pytest.raises(ValueError, match='session_input_admission_rejection_unproven'):
        inspect_session_input_terminal(root, root.parent / 'memory-library')
