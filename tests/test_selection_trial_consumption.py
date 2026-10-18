"""状态满足不伪造输入；原回执和当前试运行必须一致。"""
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from app.desktop_review.external_mapping import canonical_json_bytes
from app.learning_memory.selection_satisfaction import selection_proof
from app.learning_memory.workflow_trial import TrialService, _command
from test_workflow_ensure_selected import action, satisfied_receipt


def selection_trial(tmp_path, *, dispatched=False, condition=True):
    command, bindings, report = satisfied_receipt(tmp_path)
    run_id = 'trial-' + 'a' * 64
    step = {'step_id': 'step', 'action': action(), 'outputs': [],
            'success_conditions': [{'left': {'source': 'observation', 'name': 'ready'},
                                    'operator': 'agent_assertion'}],
            'branches': {'success': None, 'failure': None, 'uncertain': None}}
    command = _command(step, {}, {})
    state = {'run_id': run_id, 'workflow_id': 'workflow', 'program_id': 'program',
             'status': 'pending', 'current_step_id': 'step', 'inputs': {'row': 'Fresh row'},
             'outputs': {}, 'history': [], 'requests': {},
             'pending': {'step_id': 'step', 'execution_request_id': 'exec',
                         'suggested_command': command, 'preview': {'action': action()}}}
    bindings.update(run_id=run_id, inputs=state['inputs'],
                    command_sha256=sha256(canonical_json_bytes(command)).hexdigest())
    before = deepcopy(report['row_selection_proof']['before'])
    after = deepcopy(report['row_selection_proof']['after'])
    before['row_selection']['selected'] = not dispatched
    proof = selection_proof(command['request'], bindings, before, after, action_executed=dispatched)
    report.update(action_executed=dispatched, row_selection_proof=proof)
    report['response']['data']['result'].update(row_selection_proof=deepcopy(proof),
        execution_path={'action_executed': dispatched})
    receipt = {'status': 'returned', 'command': command, 'result': report}
    for directory, name, value in [('commands', 'exec', command), ('responses', 'exec', receipt),
                                    ('workflow-trials', run_id, state)]:
        path = tmp_path / directory / (name + '.json')
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    trials = TrialService.__new__(TrialService)
    trials.session, trials.root = tmp_path, tmp_path / 'workflow-trials'
    trials.programs = SimpleNamespace(load=lambda *_: {'definition': {'steps': [step]}})
    return trials, state, receipt, {'ready': condition}


@pytest.mark.parametrize('dispatched', [False, True])
def test_selection_completion_preserves_original_input_fact(tmp_path, dispatched):
    trials, state, _, observations = selection_trial(tmp_path, dispatched=dispatched)
    result = trials.review(state['run_id'], 'review', 'exec', 'success', observations, {})
    assert result['status'] == 'completed' and result['pending'] is None
    history = result['history'][0]
    assert history['command_succeeded'] is True
    assert history['action_executed'] is dispatched
    assert history['input_route_succeeded'] is dispatched
    assert trials.review(state['run_id'], 'review', 'exec', 'success', observations, {}) == result


def test_selected_state_does_not_override_business_condition(tmp_path):
    trials, state, _, observations = selection_trial(tmp_path, condition=False)
    result = trials.review(state['run_id'], 'review', 'exec', 'success', observations, {})
    assert result['status'] == 'failed'
    assert result['history'][0]['command_succeeded'] is True
    assert result['history'][0]['action_executed'] is False


@pytest.mark.parametrize('field', ['run_id', 'step_id', 'execution_request_id', 'inputs', 'outputs', 'action'])
def test_original_proof_cannot_complete_a_different_trial_context(tmp_path, field):
    trials, state, receipt, observations = selection_trial(tmp_path)
    report = receipt['result']
    proof = report['row_selection_proof']
    proof['binding'][field] = {'different': 'value'} if field in {'inputs', 'outputs', 'action'} else 'different'
    proof['sha256'] = sha256(canonical_json_bytes({key: value for key, value in proof.items()
                                               if key != 'sha256'})).hexdigest()
    report['response']['data']['result']['row_selection_proof'] = deepcopy(proof)
    (tmp_path / 'responses' / 'exec.json').write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError, match='selection'):
        trials.review(state['run_id'], 'review', 'exec', 'success', observations, {})
    assert trials.status(state['run_id'])['pending'] is not None


def test_unknown_input_cannot_be_rewritten_as_no_input_success(tmp_path):
    trials, state, receipt, observations = selection_trial(tmp_path)
    receipt['result']['action_executed'] = None
    (tmp_path / 'responses' / 'exec.json').write_text(json.dumps(receipt), encoding='utf-8')
    with pytest.raises(ValueError, match='selection'):
        trials.review(state['run_id'], 'review', 'exec', 'success', observations, {})


def test_ordinary_click_keeps_its_input_requirement(tmp_path):
    from app.learning_memory.workflow_trial import _receipt_state
    _, _, receipt, _ = selection_trial(tmp_path)
    command = receipt['command']
    command['request'].pop('selection_intent')
    (tmp_path / 'commands' / 'exec.json').write_text(json.dumps(command), encoding='utf-8')
    path = tmp_path / 'responses' / 'exec.json'
    path.write_text(json.dumps(receipt), encoding='utf-8')
    assert _receipt_state(receipt, path, 'exec', command)[0] is False


def normalized_selection(tmp_path):
    trials, state, receipt, _ = selection_trial(tmp_path)
    step = trials.programs.load()['definition']['steps'][0]
    step['verification'] = {'kind': 'target_present', 'target': {'control_type': 'ListItem', 'name': 'Fresh row'}}
    report = receipt['result']
    frame = deepcopy(report['row_selection_proof']['after']['frame'])
    frame['capture_id'] = 'verify-fresh-3'
    ids = {'run_id': state['run_id'], 'step_id': 'step', 'execution_request_id': 'exec', 'request_id': 'verify'}
    normalized = {**ids, 'status': 'completed', 'action_executed': False,
        'pre_capture_id': 'fresh-1', 'post_capture_id': frame['capture_id'], 'post_capture_sha256': frame['sha256'],
        'scope_id': 'row', 'window_identity': frame['window_identity'], 'evidence_ref': 'responses/exec.json',
        'row_selection_proof': deepcopy(report['row_selection_proof'])}
    observation = {**ids, 'capture_id': frame['capture_id'], 'capture_sha256': frame['sha256'],
        'scope_id': 'row', 'window_identity': frame['window_identity'], 'complete': True, 'source': 'presence',
        'values': {'target_present': True, 'ready': True}, 'reason': None,
        'evidence_ref': 'workflow-observations/verify.json'}
    return trials, state, step, normalized, observation, frame


def test_no_input_selection_still_requires_current_business_rule(tmp_path):
    from app.learning_memory.workflow_verification import verify_step
    _, state, step, receipt, observation, _ = normalized_selection(tmp_path)
    assert verify_step(step, inputs=state['inputs'], outputs={}, receipt=receipt,
                       observation=observation)['verdict'] == 'success'
    observation['values']['target_present'] = False
    assert verify_step(step, inputs=state['inputs'], outputs={}, receipt=receipt,
                       observation=observation)['verdict'] == 'failure'
    observation['complete'] = False
    assert verify_step(step, inputs=state['inputs'], outputs={}, receipt=receipt,
                       observation=observation)['verdict'] == 'uncertain'


@pytest.mark.parametrize('mutation', ['missing', 'hash', 'run', 'editing', 'actual', 'target'])
def test_normalized_selection_cannot_use_a_boolean_or_mismatched_proof(tmp_path, mutation):
    from app.learning_memory.workflow_verification import verify_step
    _, state, step, receipt, observation, _ = normalized_selection(tmp_path)
    proof = receipt['row_selection_proof']
    if mutation == 'missing':
        receipt.pop('row_selection_proof')
        receipt['selection_satisfied'] = True
    elif mutation == 'hash':
        proof['sha256'] = '0' * 64
    elif mutation == 'run':
        proof['binding']['run_id'] = 'another-run'
    elif mutation == 'editing':
        proof['after']['row_selection']['editing'] = True
    elif mutation == 'actual':
        receipt['action_executed'] = True
    else:
        proof['reference']['recipe_id'] = 'target-recipe-' + 'f' * 64
    assert verify_step(step, inputs=state['inputs'], outputs={}, receipt=receipt,
                       observation=observation)['verdict'] != 'success'


@pytest.mark.parametrize('tampered', [False, True])
def test_verified_result_rechecks_original_selection_proof(tmp_path, tampered):
    from app.learning_memory.workflow_verification import verify_step
    trials, state, step, normalized, observation, frame = normalized_selection(tmp_path)
    if tampered:
        proof = normalized['row_selection_proof']
        proof['before']['frame']['sha256'] = 'f' * 64
        proof['sha256'] = sha256(canonical_json_bytes({key: value for key, value in proof.items()
                                                   if key != 'sha256'})).hexdigest()
    envelope = {'contract_version': 'workflow_observation.v1', 'receipt': normalized,
                'observation': observation, 'frame': frame, 'terminal_receipt': None,
                'source_receipt_sha256': sha256((tmp_path / 'responses' / 'exec.json').read_bytes()).hexdigest()}
    path = tmp_path / 'workflow-observations' / 'verify.json'
    path.parent.mkdir()
    path.write_text(json.dumps(envelope), encoding='utf-8')
    result = verify_step(step, inputs=state['inputs'], outputs={}, receipt=normalized, observation=observation)
    if tampered:
        with pytest.raises(ValueError, match='binding_mismatch'):
            trials.record_verified_result(state['run_id'], 'verify', 'exec', result)
    else:
        assert result['verdict'] == 'success'
        completed = trials.record_verified_result(state['run_id'], 'verify', 'exec', result)
        assert completed['status'] == 'completed'
        assert completed['history'][0]['action_executed'] is False
        assert completed['history'][0]['judged_by'] == 'rule'


def test_runtime_verification_preserves_no_input_and_reads_outside_library_lock(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from app.learning_memory.runtime_verification import verify_trial_step
    trials, state, step, _, observation, frame = normalized_selection(tmp_path)
    held, calls = [], []
    @contextmanager
    def workspace(_):
        held.append(True)
        try:
            yield object()
        finally:
            held.pop()
    def load(*_):
        assert held
        return {'definition': {'steps': [step]}}
    trials.programs.load = load
    monkeypatch.setattr('app.learning_memory.workspace.MemoryWorkspace', workspace)
    monkeypatch.setattr('app.learning_memory.runtime_verification.TrialService', lambda *_: trials)
    def observe(*_, **kwargs):
        assert not held
        calls.append(kwargs)
        return {'frame': deepcopy(frame), 'scope_id': 'row', 'source': 'presence', 'complete': True,
                'values': deepcopy(observation['values']), 'reason': None, 'evidence': {}}
    monkeypatch.setattr('app.learning_memory.verification_observation.read_step_observation', observe)
    def no_input(**_):
        raise AssertionError('verification dispatched input')
    coordinator = SimpleNamespace(_memory_library_root=tmp_path,
        _owner=SimpleNamespace(call=lambda f: f()), execute_local_step=no_input)
    request = {'action': 'verify', 'run_id': state['run_id'], 'execution_request_id': 'exec'}
    result = verify_trial_step(coordinator, session_dir=tmp_path, request=request, request_id='verify')
    assert result['status'] == 'completed' and len(calls) == 1
    assert result['history'][0]['command_succeeded'] is True
    assert result['history'][0]['action_executed'] is False
    envelope = json.loads((tmp_path / 'workflow-observations' / 'verify.json').read_text(encoding='utf-8'))
    assert envelope['receipt']['action_executed'] is False
    assert envelope['receipt']['row_selection_proof']['status'] == 'already_satisfied'
    assert verify_trial_step(coordinator, session_dir=tmp_path, request=request, request_id='verify') == result
    assert len(calls) == 1
