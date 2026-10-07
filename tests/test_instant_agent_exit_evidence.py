"""宿主退出后原接收回执不能把可能发生的输入投影为未执行。"""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from app.instant_mcp import InstantSession
from tests.test_workflow_run_client import _live, _write


def _dead_session(tmp_path):
    session, library, pointer, report = _live(tmp_path)
    pointer['host_identity']['created'] += 1
    _write(tmp_path / 'latest-session.json', pointer)
    instant = InstantSession(tmp_path, tmp_path, recognition_source='agent_current')
    instant.session = session
    instant.host_identity = pointer['host_identity']
    command = {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': {'goal': 'Open'}}
    worker = {'contract_version': 'agent_command.v1', 'command_id': 'original-step',
              'status': 'running', 'action_executed': False, 'dispatch_in_progress': False}
    _write(session / 'commands/original-step.json', command)
    _write(session / 'responses/original-step.json', {'command': command, 'status': 'returned', 'result': worker})
    (session / 'agent-commands').mkdir()
    return instant, session, worker


@pytest.mark.parametrize('stage', ['missing', 'started', 'returned', 'legacy'])
def test_dead_async_acceptance_exposes_current_evidence_without_no_input_claim(tmp_path, stage):
    instant, session, initial = _dead_session(tmp_path)
    if stage != 'missing':
        current = {**deepcopy(initial), 'dispatch_in_progress': stage == 'started',
                   'action_executed': True if stage == 'returned' else None if stage == 'started' else False}
        if stage != 'legacy':
            current['dispatch_attempts'] = [{'index': 1, 'operation': 'execute_recognition_plan',
                'status': stage, 'previous_action_executed': False, 'action_executed': current['action_executed']}]
        _write(session / 'agent-commands/original-step.json', current)
    before = {p: p.read_bytes() for p in session.rglob('*.json')}
    receipt = instant.result('original-step')
    assert receipt['result'] == initial
    assert receipt['action_executed'] is (True if stage == 'returned' else None)
    assert receipt['worker_status'] == 'result_unknown'
    assert receipt['operation_succeeded'] is None
    assert receipt['automatic_retry_allowed'] is False
    assert receipt['next_action'] == 'inspect_original_worker_evidence_no_replay'
    evidence = receipt['persisted_worker_evidence']
    assert evidence['scope'] == 'saved_worker_diagnostic_not_execution_receipt'
    assert evidence['command_id'] == 'original-step'
    if stage == 'missing':
        assert evidence['status'] == 'unavailable' and evidence['sha256'] is None
    else:
        path = session / 'agent-commands/original-step.json'
        assert evidence['sha256'] == sha256(path.read_bytes()).hexdigest()
        assert evidence['status'] == 'running'
        assert evidence['action_executed'] == current['action_executed']
    assert {p: p.read_bytes() for p in session.rglob('*.json')} == before
    assert 'next' not in receipt


@pytest.mark.parametrize('value', [
    {'contract_version': 'agent_command.v1', 'command_id': 'other', 'status': 'running'},
    {'contract_version': 'other', 'command_id': 'original-step', 'status': 'running'},
    {'contract_version': 'agent_command.v1', 'command_id': 'original-step', 'status': 'bogus'},
    {'contract_version': 'agent_command.v1', 'command_id': 'original-step', 'status': 'running', 'action_executed': 'False'},
])
def test_dead_worker_evidence_rejects_malformed_identity_without_replay(tmp_path, value):
    instant, session, _ = _dead_session(tmp_path)
    _write(session / 'agent-commands/original-step.json', value)
    before = {p: p.read_bytes() for p in session.rglob('*.json')}
    with pytest.raises(ValueError, match='instant_agent_worker_evidence_invalid'):
        instant.result('original-step')
    assert {p: p.read_bytes() for p in session.rglob('*.json')} == before


def test_live_async_acceptance_keeps_original_polling_contract(tmp_path):
    instant, session, initial = _dead_session(tmp_path)
    instant.host_identity['created'] -= 1
    receipt = instant.result('original-step')
    assert receipt['action_executed'] is False
    assert receipt['result'] == initial
    assert receipt['next']['arguments']['command']['kind'] == 'agent_command_status'
    assert 'persisted_worker_evidence' not in receipt


@pytest.mark.parametrize('current', [None, False])
def test_dead_projection_preserves_previously_recorded_true(tmp_path, current):
    instant, session, initial = _dead_session(tmp_path)
    original = json.loads((session / 'responses/original-step.json').read_text(encoding='utf-8'))
    original['result']['action_executed'] = True
    _write(session / 'responses/original-step.json', original)
    if current is not None:
        _write(session / 'agent-commands/original-step.json', {**initial, 'action_executed': current})
    assert instant.result('original-step')['action_executed'] is True


def test_dead_poll_receipt_reads_referenced_original_worker_without_control(tmp_path):
    instant, session, initial = _dead_session(tmp_path)
    command = {'kind': 'agent_command_status', 'request': {'command_id': 'original-step'}}
    _write(session / 'commands/original-poll.json', command)
    _write(session / 'responses/original-poll.json', {'command': command, 'status': 'returned', 'result': initial})
    terminal = {**initial, 'status': 'completed', 'action_executed': True}
    _write(session / 'agent-commands/original-step.json', terminal)
    before = {p: p.read_bytes() for p in session.rglob('*.json')}
    receipt = instant.result('original-poll')
    assert receipt['worker_status'] == 'terminal_available'
    assert receipt['persisted_worker_evidence']['command_id'] == 'original-step'
    assert receipt['result'] == initial and receipt['operation_succeeded'] is None
    assert receipt['action_executed'] is True
    assert {p: p.read_bytes() for p in session.rglob('*.json')} == before


@pytest.mark.parametrize('conflict', ['command', 'acceptance_identity', 'acceptance_contract'])
def test_dead_poll_rejects_conflicting_original_job_binding(tmp_path, conflict):
    instant, session, initial = _dead_session(tmp_path)
    command = {'kind': 'agent_command_status', 'request': {'command_id': 'original-step'}}
    _write(session / 'commands/original-poll.json', command)
    _write(session / 'responses/original-poll.json', {'command': command, 'status': 'returned', 'result': initial})
    _write(session / 'agent-commands/original-step.json', {**initial, 'status': 'completed', 'action_executed': True})
    if conflict == 'command':
        _write(session / 'commands/original-step.json', {'kind': 'read_text', 'max_chars': 100})
    else:
        original = json.loads((session / 'responses/original-step.json').read_text(encoding='utf-8'))
        original['result']['command_id' if conflict == 'acceptance_identity' else 'contract_version'] = 'other'
        _write(session / 'responses/original-step.json', original)
    before = {p: p.read_bytes() for p in session.rglob('*.json')}
    with pytest.raises(ValueError, match='instant_agent_worker_evidence_invalid'):
        instant.result('original-poll')
    assert {p: p.read_bytes() for p in session.rglob('*.json')} == before
