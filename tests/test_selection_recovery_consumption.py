"""恢复消费者保留真实输入事实并闭合原选择证明图片。"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from test_selection_trial_consumption import selection_trial


def scene(tmp_path, *, dispatched=False, condition=True):
    trials, state, receipt, observations = selection_trial(tmp_path, dispatched=dispatched, condition=condition)
    program = trials.programs.load()
    program.update(program_id=state['program_id'], workflow_id=state['workflow_id'],
                   project_snapshot_id='snapshot', content_sha256='a' * 64)
    state.update(start_step_id='step', project_snapshot_id='snapshot')
    trials.programs.library = tmp_path / 'library'
    trials.programs.load = lambda *_: deepcopy(program)
    trials._path(state['run_id']).write_text(json.dumps(state), encoding='utf-8')
    return trials, state, receipt, observations, program


@pytest.mark.parametrize('dispatched', [False, True])
@pytest.mark.parametrize('condition', [False, True])
def test_original_selection_history_recovers_true_input_fact(tmp_path, monkeypatch, dispatched, condition):
    from app.learning_memory import workflow_recovery_history as module
    from app.execution.session_input_terminal import _catalog
    trials, state, _, observations, program = scene(tmp_path, dispatched=dispatched, condition=condition)
    result = trials.review(state['run_id'], 'review', 'exec', 'success', observations, {})
    monkeypatch.setattr(module, 'WorkflowProgramService', lambda _: trials.programs)
    raw = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    hashes = {ref: sha256(data).hexdigest() for ref, data in _catalog(tmp_path).items()}
    restored = module.verify_recovery_history(trials.programs.library, tmp_path, result, program, file_hashes=hashes)
    assert restored['history'] == result['history']
    assert restored['history'][0]['action_executed'] is dispatched
    assert restored['history'][0]['input_route_succeeded'] is dispatched
    assert all(Path(name).read_bytes() == data for name, data in raw.items())


def test_catalog_includes_both_original_selection_frames(tmp_path):
    from app.execution.session_input_terminal import _catalog
    _, _, receipt, _, _ = scene(tmp_path)
    proof = receipt['result']['row_selection_proof']
    catalog = _catalog(tmp_path)
    for stage in ['before', 'after']:
        frame = proof[stage]['frame']
        path = Path(frame['image_path'])
        assert catalog[path.relative_to(tmp_path).as_posix()] == path.read_bytes()


@pytest.mark.parametrize('reviewed', [False, True])
def test_model_call_binding_accepts_selection_without_input(tmp_path, monkeypatch, reviewed):
    from app.learning_memory import caller_model_calls as module
    from app.learning_memory import workflow_trial
    trials, state, _, observations, _ = scene(tmp_path)
    if reviewed:
        trials.review(state['run_id'], 'review', 'exec', 'success', observations, {})
    monkeypatch.setattr(workflow_trial, 'TrialService', lambda *_: trials)
    result = module._binding(trials.programs.library, tmp_path, {'kind': 'workflow',
        'run_id': state['run_id'], 'step_id': 'step', 'execution_request_id': 'exec'})
    assert result['evidence_ref'] == 'responses/exec.json'


@pytest.mark.parametrize('dispatched', [False, True])
@pytest.mark.parametrize('status', ['completed', 'failed', 'cancelled'])
def test_terminal_recovery_preserves_original_selection_input_fact(tmp_path, dispatched, status):
    from app.learning_memory.workflow_terminal_recovery import WorkflowTerminalRecovery
    from app.learning_memory.workflow_program import _digest
    trials, state, receipt, _, _ = scene(tmp_path, dispatched=dispatched)
    recovery = WorkflowTerminalRecovery.__new__(WorkflowTerminalRecovery)
    recovery.trials, recovery.session = trials, tmp_path
    recovery.runner_root = tmp_path / 'workflow-runners'
    recovery.runner_root.mkdir()
    recovery._inactive = lambda *_: []
    pending = state['pending']
    ticket = {**pending, 'command_sha256': _digest(receipt['command'])}
    runner = {'schema': 'workflow_runner.v1', 'run_id': state['run_id'], 'ticket': ticket,
              'current_step_id': 'step', 'runner_state': 'waiting'}
    (recovery.runner_root / (state['run_id'] + '.json')).write_text(json.dumps(runner), encoding='utf-8')
    (recovery.runner_root / 'active.json').write_text(json.dumps({'schema': 'workflow_runner.v1', 'run_id': state['run_id']}), encoding='utf-8')
    worker = {'contract_version': 'agent_command.v1', 'command_id': 'exec', 'status': status,
              'action_executed': dispatched, 'result': receipt['result'], 'dispatch_attempts': []}
    (tmp_path / 'agent-commands').mkdir()
    (tmp_path / 'agent-commands/exec.json').write_text(json.dumps(worker), encoding='utf-8')
    acceptance = {**receipt, 'result': {'contract_version': 'agent_command.v1', 'command_id': 'exec', 'status': 'running', 'action_executed': False}}
    (tmp_path / 'responses/exec.json').write_text(json.dumps(acceptance), encoding='utf-8')
    preview = recovery._inspect(state['run_id'])
    assert preview['action_executed'] is dispatched
    assert preview['input_route_succeeded'] is (dispatched and status == 'completed')
    assert preview['command_succeeded'] is (status == 'completed')


def test_failed_selection_history_keeps_false_input_fact(tmp_path, monkeypatch):
    from app.learning_memory import workflow_recovery_history as module
    from app.execution.session_input_terminal import _catalog
    trials, state, receipt, observations, program = scene(tmp_path)
    receipt['status'] = 'failed'
    (tmp_path / 'responses/exec.json').write_text(json.dumps(receipt), encoding='utf-8')
    result = trials.review(state['run_id'], 'review', 'exec', 'failure', observations, {})
    monkeypatch.setattr(module, 'WorkflowProgramService', lambda _: trials.programs)
    hashes = {ref: sha256(data).hexdigest() for ref, data in _catalog(tmp_path).items()}
    restored = module.verify_recovery_history(trials.programs.library, tmp_path, result, program, file_hashes=hashes)
    entry = restored['history'][0]
    assert entry['command_succeeded'] is False and entry['action_executed'] is False
    assert entry['input_route_succeeded'] is False
    assert 'selection_proof_sha256' not in entry


@pytest.mark.parametrize('change', ['missing_image', 'changed_image', 'outside_image'])
def test_catalog_rejects_unavailable_or_foreign_proof_image(tmp_path, change):
    from app.execution.session_input_terminal import _catalog
    _, _, receipt, _, _ = scene(tmp_path)
    image = Path(receipt['result']['row_selection_proof']['after']['frame']['image_path'])
    if change == 'missing_image':
        # 移到本测试目录，保留原字节而让原引用缺失。
        image.rename(tmp_path / 'retained.png')
    elif change == 'changed_image':
        image.write_bytes(b'changed')
    else:
        receipt['result']['row_selection_proof']['after']['frame']['image_path'] = str(tmp_path.parent / 'outside.png')
        (tmp_path / 'responses/exec.json').write_text(json.dumps(receipt), encoding='utf-8')
    with pytest.raises((ValueError, OSError)):
        _catalog(tmp_path)


def test_history_input_fact_cannot_be_relabelled(tmp_path, monkeypatch):
    from app.learning_memory import workflow_recovery_history as module
    from app.execution.session_input_terminal import _catalog
    trials, state, _, observations, program = scene(tmp_path)
    result = trials.review(state['run_id'], 'review', 'exec', 'success', observations, {})
    result['history'][0]['action_executed'] = True
    trials._path(state['run_id']).write_text(json.dumps(result), encoding='utf-8')
    monkeypatch.setattr(module, 'WorkflowProgramService', lambda _: trials.programs)
    hashes = {ref: sha256(data).hexdigest() for ref, data in _catalog(tmp_path).items()}
    with pytest.raises(ValueError, match='selection_input_fact_mismatch'):
        module.verify_recovery_history(trials.programs.library, tmp_path, result, program, file_hashes=hashes)
