"""归档回放保留零输入事实，不依赖原会话仍在磁盘。"""
from copy import deepcopy
from hashlib import sha256
import base64
import json
from pathlib import Path

import pytest

from app.learning_memory.benchmark_provenance import inspect_coverage
from app.learning_memory.workflow_verification import verify_step
from test_benchmark_provenance import evidence, frozen
from test_selection_trial_consumption import normalized_selection


def archived_selection(tmp_path, *, ready=True):
    trials, state, step, normalized, observation, frame = normalized_selection(tmp_path)
    observation['values']['ready'] = ready
    step['review_status'] = 'reviewed'
    receipt_path = tmp_path / 'responses' / 'exec.json'
    response = json.loads(receipt_path.read_text(encoding='utf-8'))
    response['result']['memory_resolution'] = deepcopy(response['result']['row_selection_proof']['before'])
    receipt_path.write_text(json.dumps(response), encoding='utf-8')
    envelope = {'contract_version': 'workflow_observation.v1', 'receipt': normalized, 'observation': observation,
                'frame': frame, 'source_receipt_sha256': sha256(receipt_path.read_bytes()).hexdigest(),
                'terminal_receipt': None}
    path = tmp_path / 'workflow-observations' / 'verify.json'
    path.parent.mkdir()
    path.write_text(json.dumps(envelope), encoding='utf-8')
    result = verify_step(step, inputs=state['inputs'], outputs={}, receipt=normalized, observation=observation)
    trial = trials.record_verified_result(state['run_id'], 'verify', 'exec', result)
    binding, program = frozen([step])
    trial.update({key: binding[key] for key in ('workflow_id', 'program_id', 'project_snapshot_id', 'start_step_id')})
    trial['execution_strategy'] = 'learned'
    files = []
    for path in (tmp_path / 'commands' / 'exec.json', receipt_path, tmp_path / 'workflow-observations' / 'verify.json'):
        raw = path.read_bytes()
        files.append({'ref': path.relative_to(tmp_path).as_posix(), 'text': raw.decode('utf-8'), 'sha256': sha256(raw).hexdigest()})
    path = tmp_path / 'runtime-output' / 'fresh.png'
    raw = path.read_bytes()
    files.append({'ref': path.relative_to(tmp_path).as_posix(), 'data_base64': base64.b64encode(raw).decode('ascii'),
                  'sha256': sha256(raw).hexdigest()})
    return binding, program, trial, files


def test_archived_satisfaction_is_not_a_fabricated_click_or_benefit(tmp_path, monkeypatch):
    args = archived_selection(tmp_path)
    def no_disk(*_, **__):
        raise AssertionError('archive replay read original files')
    monkeypatch.setattr(Path, 'read_bytes', no_disk)
    result = inspect_coverage(*args)
    assert result['errors'] == [] and result['status'] == 'complete'
    row = result['steps'][0]
    assert row['target_memory'] == 'memory_selection_satisfied'
    assert row['action_executed'] is False and row['verification'] == 'rule_verified'
    assert result['eligible_for_full_rule_comparison'] is False


def test_archive_retains_real_business_failure_after_selection_satisfaction(tmp_path):
    args = archived_selection(tmp_path, ready=False)
    assert args[2]['status'] == 'failed'
    assert args[2]['history'][0]['verdict'] == 'failure'
    result = inspect_coverage(*args)
    assert result['status'] == 'complete' and result['errors'] == []
    assert result['eligible_for_full_rule_comparison'] is False


@pytest.mark.parametrize('mutation', ['missing_image', 'image_bytes', 'run', 'normalized', 'input_fact', 'business_condition'])
def test_archive_requires_original_image_context_and_actual_input_fact(tmp_path, mutation):
    binding, program, trial, files = archived_selection(tmp_path)
    if mutation == 'missing_image':
        files.pop()
    elif mutation == 'image_bytes':
        raw = b'not original image'
        files[-1].update(data_base64=base64.b64encode(raw).decode('ascii'), sha256=sha256(raw).hexdigest())
    elif mutation == 'run':
        trial['run_id'] = 'trial-' + 'f' * 64
    elif mutation == 'input_fact':
        trial['history'][0]['action_executed'] = True
    elif mutation == 'business_condition':
        envelope = json.loads(files[2]['text'])
        envelope['observation']['values']['ready'] = False
        entry = trial['history'][0]
        entry['verification']['observations'] = deepcopy(envelope['observation'])
        entry['observations']['ready'] = False
        files[2] = evidence(files[2]['ref'], envelope)
    else:
        envelope = json.loads(files[2]['text'])
        envelope['receipt']['row_selection_proof']['before']['frame']['sha256'] = 'f' * 64
        files[2] = evidence(files[2]['ref'], envelope)
    result = inspect_coverage(binding, program, trial, files)
    assert result['errors'] and result['status'] == 'partial'
    assert not result['eligible_for_full_rule_comparison']
