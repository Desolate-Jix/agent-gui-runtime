"""可信零输入可显式恢复；原票据、已完成动作和取消仍受保护。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.task_plan_admission import TaskPlanRuntime
from app.learning_memory.workflow_runtime import WorkflowRuntime
from tests.test_point_visibility_no_dispatch import visibility_route
from tests.test_task_plan_contract import plan
from tests.test_local_step_timings import timed_scene


TARGET = {'handle': 321, 'process_id': 12, 'process_create_time': 123.5}


@pytest.fixture
def intervention(tmp_path, monkeypatch, visibility_route):
    def create(*, policy='intervention_v1', version='task_plan.v2', count=1, verification='agent', kind='click'):
        for name in ('commands', 'responses', 'agent-commands'):
            (tmp_path / name).mkdir(exist_ok=True)
        co = SimpleNamespace(_decision_service=None, _memory_library_root=tmp_path / 'absent-learning')
        reviewed = WorkflowRuntime(tmp_path, co)
        target = deepcopy(TARGET)
        runtime = TaskPlanRuntime(tmp_path, co, owner_id='owner', target_identity=lambda: deepcopy(target),
            reviewed_runtime=reviewed)
        source = plan(count=count, verification={'kind': 'agent_judgment'} if verification == 'agent' else None)
        source['schema_version'] = version
        source['steps'][0]['action']['goal'] = 'Focus the fresh field'
        if kind == 'input_sequence':
            source['steps'][0]['action'] = {'kind': kind, 'field_goal': 'Focus the fresh field',
                'text': 'fresh synthetic text', 'clear_existing': True, 'submit_search': False}
        if version == 'task_plan.v3':
            source.update(goal='The requested field is focused', completion={'step_id': source['steps'][-1]['step_id'],
                'verification': {'kind': 'agent_judgment', 'decision_condition': 'The requested field is visibly focused.'}})
        request = {'action': 'start', 'plan': source}
        if policy is not None:
            request['recovery_policy'] = policy
        first = runtime.control(request, 'start-original')
        return SimpleNamespace(runtime=runtime, session=tmp_path, run_id=first['run_id'], target=target,
            source=source, first=first, start_request=request)
    return SimpleNamespace(create=create, route=visibility_route)


def reject(s, fixture, *, kind='zero'):
    pending = s.runtime.backend.status(s.run_id)['pending']
    response = fixture.route.run()
    data = response['data']
    path = data['image_path']
    capture = {'image_path': path, 'sha256': sha256(__import__('pathlib').Path(path).read_bytes()).hexdigest(),
        'capture_id': 'fresh-zero-frame', 'window_identity': deepcopy(TARGET)}
    result = {'contract_version': 'local_direct_step_v1', 'operation': 'execute_recognition_plan', 'phase': 'not_dispatched', 'action_executed': False,
        'target_identity': {'target_window_handle': 321, 'process_id': 12, 'process_create_time': 123.5},
        'local_input_scope_closed': True, 'capture': capture, 'response': response, 'automatic_retry_allowed': False}
    if kind != 'zero':
        result['phase'] = 'result_unknown'
        result['action_executed'] = True if kind == 'partial' else None
        data['execution_path']['action_executed'] = result['action_executed']
        data.pop('point_visibility_no_dispatch', None)
    receipt = {'status': 'returned', 'command': deepcopy(pending['suggested_command']), 'result': result}
    path = s.session / 'responses' / (pending['execution_request_id'] + '.json')
    write_json_snapshot(path, receipt)
    return pending, path, path.read_bytes()


def binding(waiting):
    packet = waiting['review_packet']
    return {key: packet[key] for key in ('run_id', 'wait_id', 'step_id', 'execution_request_id',
        'evidence_set_sha256', 'assessment_round')} | {'review_packet_sha256': packet['packet_sha256']}


def resume(s, waiting, request_id='resume-original'):
    return s.runtime.control({'action': 'resume_pre_dispatch', **binding(waiting), 'reason': 'Main checked the obstruction'}, request_id)


def recover(s, waiting, request_id='recover-control', recovery_id='recovery-click'):
    command = {'kind': 'step', 'operation': 'execute_recognition_plan',
        'request': {'goal': 'Dismiss the harmless synthetic popup', 'click_kind': 'single'}}
    result = s.runtime.control({'action': 'recover', **binding(waiting),
        'recovery_request_id': recovery_id, 'command': command}, request_id)
    return result, read_json_snapshot(s.session / 'commands' / (recovery_id + '.json'))


@pytest.mark.parametrize('version', ['task_plan.v1', 'task_plan.v2'])
def test_omitted_recovery_policy_keeps_legacy_terminal_failure(intervention, version):
    s = intervention.create(policy=None, version=version)
    reject(s, intervention)
    result = s.runtime.tick(force=True)
    assert result['status'] == result['runner_state'] == 'failed' and result['pending'] is None


def test_zero_dispatch_block_is_resumable_and_old_rejection_is_immutable(intervention):
    s = intervention.create()
    old, path, before = reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    assert waiting['wait_reason'] == 'verification_required' and waiting['status'] == 'pending'
    assert waiting['review_packet']['reason'] == 'blocked_before_dispatch'
    assert 'caller_controls' not in waiting
    assert waiting['review_packet']['action_executed'] is False and waiting['history'] == []
    fresh = resume(s, waiting)
    assert fresh['pending']['step_id'] == old['step_id']
    assert fresh['pending']['execution_request_id'] != old['execution_request_id']
    assert path.read_bytes() == before and len(list(s.session.glob('commands/*.json'))) == 2
    assert resume(s, waiting) == fresh
    with pytest.raises(ValueError, match='wait|stale|resume'):
        resume(s, waiting, 'another-resume')
    assert len(list(s.session.glob('commands/*.json'))) == 2


@pytest.mark.parametrize('kind', ['partial', 'unknown'])
def test_partial_and_unknown_never_enter_zero_dispatch_resume(intervention, kind):
    s = intervention.create()
    reject(s, intervention, kind=kind)
    waiting = s.runtime.tick(force=True)
    assert waiting['pending'] is not None and waiting['history'] == []
    assert waiting.get('review_packet', {}).get('reason') != 'blocked_before_dispatch'
    with pytest.raises(ValueError):
        s.runtime.backend.resume_pre_dispatch(s.run_id, 'forged', 'fake-wait', {})
    assert len(list(s.session.glob('commands/*.json'))) == 1


def test_recovery_admission_only_accepts_exact_once_bound_click(intervention):
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    result, command = recover(s, waiting)
    assert result['pending']['execution_request_id'] == waiting['pending']['execution_request_id']
    assert len(list(s.session.glob('commands/*.json'))) == 2
    same, _ = recover(s, waiting)
    assert same == result and len(list(s.session.glob('commands/*.json'))) == 2
    with pytest.raises(ValueError, match='active|recovery'):
        s.runtime.admit('other-request', command)
    with pytest.raises(ValueError, match='recovery|pending|unsettled'):
        resume(s, waiting)
    receipt = {'status': 'returned', 'command': command, 'result': {'contract_version': 'local_direct_step_v1',
        'phase': 'returned', 'target_identity': {'target_window_handle': 321, 'process_id': 12,
            'process_create_time': 123.5}, 'response': {'success': True, 'data': {'result': {
                'execution_path': {'action_executed': True}}}}}}
    write_json_snapshot(s.session / 'responses' / 'recovery-click.json', receipt)
    fresh = resume(s, waiting)
    assert fresh['pending']['execution_request_id'] != waiting['pending']['execution_request_id']
    assert len(list(s.session.glob('commands/*.json'))) == 3
    settlement = fresh['intervention_resumes']['resume-original']['recovery_settlement']
    assert settlement['recovery_request_id'] == 'recovery-click' and settlement['action_executed'] is True
    assert {ref['path'] for ref in settlement['evidence_refs']} == {
        'commands/recovery-click.json', 'responses/recovery-click.json'}
    receipt['result']['phase'] = 'result_unknown'
    write_json_snapshot(s.session / 'responses' / 'recovery-click.json', receipt)
    with pytest.raises(ValueError, match='recovery'):
        s.runtime.backend.status(s.run_id)


def test_cancel_wins_over_late_resume_and_recovery(intervention):
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-original')
    for action in (lambda: resume(s, waiting), lambda: recover(s, waiting)):
        with pytest.raises(ValueError, match='cancel|terminal|wait|intervention'):
            action()
    terminal = s.runtime.tick(force=True)
    assert terminal['status'] == terminal['runner_state'] == 'cancelled'
    assert len(list(s.session.glob('commands/*.json'))) == 1


def test_policy_is_in_start_idempotency_and_immutable_source(intervention):
    s = intervention.create()
    assert s.runtime.control(s.start_request, 'start-original')['run_id'] == s.run_id
    changed = {**s.start_request, 'recovery_policy': 'legacy'}
    with pytest.raises(ValueError, match='idempotency|policy'):
        s.runtime.control(changed, 'start-original')
    state = s.runtime.backend.status(s.run_id)
    source = s.runtime.backend._source(state)
    assert source['recovery_policy'] == state['recovery_policy'] == 'intervention_v1'


def test_second_obstruction_after_one_resume_stops_recovery_loop(intervention):
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    resume(s, waiting)
    reject(s, intervention)
    repeated = s.runtime.tick(force=True)
    assert repeated['review_packet']['reason'] == 'repeated_obstruction'
    with pytest.raises(ValueError, match='repeated|limit'):
        resume(s, repeated, 'second-resume')
    assert len(list(s.session.glob('commands/*.json'))) == 2


@pytest.mark.parametrize('field', ['wait_id', 'step_id', 'execution_request_id', 'review_packet_sha256', 'evidence_set_sha256', 'assessment_round'])
def test_resume_requires_exact_original_review_packet(intervention, field):
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    request = {'action': 'resume_pre_dispatch', **binding(waiting), 'reason': 'Checked'}
    request[field] = 1 if field == 'assessment_round' else 'f' * 64
    with pytest.raises(ValueError):
        s.runtime.control(request, 'wrong-binding')
    assert len(list(s.session.glob('commands/*.json'))) == 1


@pytest.mark.parametrize('action', ['resume', 'recover'])
def test_window_change_revokes_recovery(intervention, action):
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    s.target['process_create_time'] += 1
    with pytest.raises(ValueError, match='target_changed'):
        (resume if action == 'resume' else recover)(s, waiting)
    assert len(list(s.session.glob('commands/*.json'))) == 1


@pytest.mark.parametrize('action', ['resume', 'recover'])
def test_queued_cancel_wins_before_intervention(intervention, action):
    from tests.test_task_plan_queued_cancel import queue_cancel
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    queue_cancel(s)
    with pytest.raises(ValueError, match='cancel_pending'):
        (resume if action == 'resume' else recover)(s, waiting)
    assert len(list(s.session.glob('commands/*.json'))) == 2


def test_recovery_permit_is_single_use_and_exact_action(intervention):
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    _, command = recover(s, waiting)
    changed = deepcopy(command)
    changed['request']['goal'] = 'A different action'
    with pytest.raises(ValueError, match='active'):
        s.runtime.admit('recovery-click', changed)
    s.runtime.admit('recovery-click', command)
    with pytest.raises(ValueError, match='consumed'):
        s.runtime.admit('recovery-click', command)
    assert len(list(s.session.glob('commands/*.json'))) == 2


@pytest.mark.parametrize('phase,actual', [('result_unknown', None), ('failed', True)])
def test_unknown_or_partial_recovery_never_releases_business_or_cancel(intervention, phase, actual):
    s = intervention.create()
    original, _, _ = reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    _, command = recover(s, waiting)
    receipt = {'status': 'returned', 'command': command, 'result': {'phase': phase, 'action_executed': actual,
        'target_identity': {'target_window_handle': 321, 'process_id': 12, 'process_create_time': 123.5}}}
    write_json_snapshot(s.session / 'responses' / 'recovery-click.json', receipt)
    with pytest.raises(ValueError, match='recovery.*unknown|recovery.*unsettled'):
        resume(s, waiting)
    s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-recovery')
    cancelling = s.runtime.tick(force=True)
    assert cancelling['status'] == 'cancel_requested' and cancelling['runner_state'] == 'waiting'
    assert cancelling['pending']['execution_request_id'] == original['execution_request_id']
    assert cancelling['history'] == [] and len(list(s.session.glob('commands/*.json'))) == 2


def test_crash_after_backend_resume_can_finish_same_request_without_replay(intervention, monkeypatch):
    s = intervention.create()
    original, _, _ = reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    save = s.runtime.runner._save
    def fail_after_backend(state):
        if state.get('intervention_resume_requests'):
            raise OSError('synthetic runner save failure')
        save(state)
    monkeypatch.setattr(s.runtime.runner, '_save', fail_after_backend)
    with pytest.raises(OSError):
        resume(s, waiting)
    assert len(list(s.session.glob('commands/*.json'))) == 1
    monkeypatch.setattr(s.runtime.runner, '_save', save)
    fresh = resume(s, waiting)
    assert fresh['pending']['execution_request_id'] != original['execution_request_id']
    assert len(list(s.session.glob('commands/*.json'))) == 2


def test_completed_prefix_is_preserved_and_new_attempt_finishes_plan(intervention, monkeypatch):
    from tests import test_task_plan_runner as helpers
    monkeypatch.setattr(helpers, 'TARGET', deepcopy(TARGET))
    s = intervention.create(count=2, verification='native')
    (s.session / 'captures').mkdir(exist_ok=True)
    first = helpers.complete_original(s, identity=TARGET)
    second = s.runtime.tick(force=True)
    assert second['pending']['step_id'] == 'step-1' and len(second['history']) == 1
    prefix = deepcopy(second['history'])
    rejected, path, raw = reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    fresh = resume(s, waiting)
    assert fresh['history'] == prefix
    last = helpers.complete_original(s, identity=TARGET)
    final = s.runtime.tick(force=True)
    assert final['status'] == final['runner_state'] == 'completed'
    assert [row['execution_request_id'] for row in final['history']] == [first.command_id, last.command_id]
    assert last.command_id != rejected['execution_request_id'] and path.read_bytes() == raw
    assert len(list(s.session.glob('commands/*.json'))) == 3
    replayed = resume(s, waiting)
    assert replayed['status'] == 'completed' and len(list(s.session.glob('commands/*.json'))) == 3


@pytest.mark.parametrize('request_id', ['start-original', 'continue-before-recover'])
def test_recovery_control_cannot_reuse_other_control_request_id(intervention, request_id):
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    if request_id.startswith('continue'):
        waiting = s.runtime.control({'action': 'continue', 'run_id': s.run_id,
            'wait_id': waiting['wait']['wait_id']}, request_id)
    with pytest.raises(ValueError, match='conflict'):
        recover(s, waiting, request_id=request_id)
    assert len(list(s.session.glob('commands/*.json'))) == 1


def test_recovery_execution_id_cannot_equal_its_transport_request_id(intervention):
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    with pytest.raises(ValueError, match='request_id'):
        recover(s, waiting, request_id='same-id', recovery_id='same-id')
    assert len(list(s.session.glob('commands/*.json'))) == 1


def test_changed_resume_request_replay_is_rejected(intervention):
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    resume(s, waiting)
    changed = {'action': 'resume_pre_dispatch', **binding(waiting), 'reason': 'Different review'}
    with pytest.raises(ValueError, match='conflict'):
        s.runtime.control(changed, 'resume-original')
    assert len(list(s.session.glob('commands/*.json'))) == 2


def test_v3_default_intervention_rebinds_action_review_to_new_attempt(intervention):
    s = intervention.create(policy=None, version='task_plan.v3')
    old, _, _ = reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    fresh = resume(s, waiting)
    pending = fresh['pending']
    assert fresh['recovery_policy'] == 'intervention_v1'
    assert pending['execution_request_id'] != old['execution_request_id']
    assert pending['suggested_command']['action_review']['attempt_id'] == pending['execution_request_id']
    assert old['suggested_command']['action_review']['attempt_id'] == old['execution_request_id']
    assert len(list(s.session.glob('commands/*.json'))) == 2


@pytest.mark.parametrize('kind', ['click', 'input_sequence'])
@pytest.mark.parametrize('asynchronous', [False, True])
def test_real_owner_sequence_and_async_terminal_zero_bind_fresh_attempt(
        intervention, timed_scene, monkeypatch, kind, asynchronous):
    from tests.test_recognition_dispatch_boundary import owner, sequence
    s = intervention.create(kind=kind)
    old = s.runtime.backend.status(s.run_id)['pending']
    response = intervention.route.run()
    local = (sequence if kind == 'input_sequence' else owner)(timed_scene, monkeypatch, response)
    receipt = {'status': 'returned', 'command': deepcopy(old['suggested_command']), 'result': local}
    terminal_path = s.session / 'agent-commands' / (old['execution_request_id'] + '.json')
    if asynchronous:
        write_json_snapshot(terminal_path, {'contract_version': 'agent_command.v1',
            'command_id': old['execution_request_id'], 'status': 'failed', 'result': local, 'action_executed': False})
        receipt['result'] = {'contract_version': 'agent_command.v1', 'command_id': old['execution_request_id'], 'status': 'running'}
    path = s.session / 'responses' / (old['execution_request_id'] + '.json')
    write_json_snapshot(path, receipt)
    before = path.read_bytes()
    terminal_before = terminal_path.read_bytes() if asynchronous else None
    waiting = s.runtime.tick(force=True)
    assert waiting['review_packet']['reason'] == 'blocked_before_dispatch'
    fresh = resume(s, waiting)
    assert fresh['pending']['execution_request_id'] != old['execution_request_id']
    assert path.read_bytes() == before and len(list(s.session.glob('commands/*.json'))) == 2
    if asynchronous:
        assert terminal_path.read_bytes() == terminal_before
        assert any(ref['path'].startswith('agent-commands/') for ref in waiting['review_packet']['evidence_refs'])


def test_async_recovery_terminal_is_bound_in_independent_settlement(intervention):
    s = intervention.create()
    reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    _, command = recover(s, waiting)
    write_json_snapshot(s.session / 'responses' / 'recovery-click.json', {'status': 'returned', 'command': command,
        'result': {'contract_version': 'agent_command.v1', 'command_id': 'recovery-click', 'status': 'running'}})
    local = {'contract_version': 'local_direct_step_v1', 'operation': 'execute_recognition_plan',
        'phase': 'returned', 'status': 'completed', 'action_executed': True,
        'target_identity': {'target_window_handle': 321, 'process_id': 12, 'process_create_time': 123.5},
        'response': {'success': True, 'data': {'result': {'execution_path': {'action_executed': True}}}}}
    terminal_path = s.session / 'agent-commands' / 'recovery-click.json'
    terminal = {'contract_version': 'agent_command.v1', 'command_id': 'recovery-click',
        'status': 'completed', 'result': local, 'action_executed': True}
    write_json_snapshot(terminal_path, terminal)
    fresh = resume(s, waiting)
    settlement = fresh['intervention_resumes']['resume-original']['recovery_settlement']
    assert {ref['path'] for ref in settlement['evidence_refs']} == {
        'commands/recovery-click.json', 'responses/recovery-click.json', 'agent-commands/recovery-click.json'}
    terminal['result']['action_executed'] = None
    write_json_snapshot(terminal_path, terminal)
    with pytest.raises(ValueError, match='recovery'):
        s.runtime.backend.status(s.run_id)


def test_known_zero_recovery_can_settle_cancel_without_claiming_recovery_success(intervention):
    s = intervention.create()
    original, original_path, _ = reject(s, intervention)
    waiting = s.runtime.tick(force=True)
    _, command = recover(s, waiting)
    local = read_json_snapshot(original_path)['result']
    write_json_snapshot(s.session / 'responses' / 'recovery-click.json',
        {'status': 'returned', 'command': command, 'result': local})
    s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-zero-recovery')
    cancelled = s.runtime.tick(force=True)
    assert cancelled['status'] == cancelled['runner_state'] == 'cancelled'
    assert cancelled['history'][0]['execution_request_id'] == original['execution_request_id']
    assert cancelled['intervention_recovery']['settlement']['action_executed'] is False
    assert len(list(s.session.glob('commands/*.json'))) == 2
