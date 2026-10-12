"""最终目标必须有冻结的可观察证明；最后一次输入成功不能替代目标完成。"""
from copy import deepcopy

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.task_plan_contract import validate_task_plan
from tests.test_task_plan_adaptive_review import OfflineAssessment, adaptive_plan, review_request
from tests.test_task_plan_contract import plan
from tests.test_task_plan_runner import complete_original, scene


def goal_plan(*, different=False, semantic=False):
    value = adaptive_plan(count=1) if semantic else plan(count=1)
    value.update(schema_version='task_plan.v3', goal='The requested detail is visible and ready.')
    rule = {'kind': 'agent_judgment', 'decision_condition': 'The final requested content is visible.'} if different else deepcopy(value['steps'][-1]['verification'])
    value['completion'] = {'step_id': value['steps'][-1]['step_id'], 'verification': rule}
    return value


@pytest.mark.parametrize('patch', ['missing_goal', 'empty_goal', 'missing_completion', 'not_final', 'no_observable_condition', 'extra_field'])
def test_v3_requires_observable_goal_completion(patch):
    value = goal_plan()
    if patch == 'missing_goal':
        value.pop('goal')
    elif patch == 'empty_goal':
        value['goal'] = ' '
    elif patch == 'missing_completion':
        value.pop('completion')
    elif patch == 'not_final':
        value['completion']['step_id'] = 'other-step'
    elif patch == 'no_observable_condition':
        value['completion']['verification'] = {'kind': 'agent_judgment'}
    else:
        value['completion']['force_complete'] = True
    with pytest.raises(ValueError):
        validate_task_plan(value)


def test_v3_contract_and_default_intervention_are_frozen(tmp_path, monkeypatch):
    source = goal_plan()
    assert validate_task_plan(source) == source
    s = scene(tmp_path, monkeypatch, source=source)
    state = s.runtime.backend.status(s.run_id)
    frozen = s.runtime.backend._source(state)
    assert state['recovery_policy'] == frozen['recovery_policy'] == 'intervention_v1'
    assert state['completion_snapshot_sha256']
    assert frozen['completion_snapshot']['goal'] == source['goal']
    assert frozen['completion_snapshot']['verification'] == source['completion']['verification']


@pytest.mark.parametrize('version', ['task_plan.v1', 'task_plan.v2'])
def test_old_plan_versions_retain_semantics(tmp_path, monkeypatch, version):
    source = plan(count=1)
    source['schema_version'] = version
    assert validate_task_plan(source) == source
    s = scene(tmp_path, monkeypatch, source=source)
    complete_original(s)
    final = s.runtime.tick(force=True)
    assert final['status'] == 'completed' and 'goal_completion' not in final['history'][0]
    assert s.runtime.backend._source(final).get('recovery_policy', 'legacy') == 'legacy'
    with pytest.raises(ValueError):
        validate_task_plan({**source, 'goal': 'Not a legacy field', 'completion': goal_plan()['completion']})


def test_same_native_final_condition_reuses_original_proof(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=goal_plan())
    original = complete_original(s)
    final = s.runtime.tick(force=True)
    assert final['status'] == final['runner_state'] == 'completed'
    assert final['history'][0]['goal_completion']['proof'] == 'final_step'
    assert final['history'][0]['execution_request_id'] == original.command_id
    assert len(list(tmp_path.glob('commands/*.json'))) == 1


def test_same_semantic_final_condition_uses_one_authenticated_decision(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition='continue')
    source = goal_plan(semantic=True)
    s = scene(tmp_path, monkeypatch, source=source, decision=service)
    complete_original(s, native=False)
    final = s.runtime.tick(force=True)
    assert final['status'] == 'completed' and len(service.calls) == 1
    assert service.calls[0]['review_context']['goal'] == source['goal']
    assert final['history'][0]['goal_completion']['proof'] == 'final_step'


def test_last_click_success_is_not_goal_success_and_main_review_is_read_only(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=goal_plan(different=True))
    original = complete_original(s)
    waiting = s.runtime.tick(force=True)
    assert waiting['status'] == 'pending' and waiting['wait_reason'] == 'verification_required'
    assert waiting['review_packet']['reason'] == 'goal_completion_required'
    assert waiting['review_packet']['completion']['verification'] == goal_plan(different=True)['completion']['verification']
    assert waiting['history'] == [] and len(list(tmp_path.glob('commands/*.json'))) == 1
    reviewed = s.runtime.control(review_request(s, waiting, original), 'goal-main-review')
    assert reviewed['status'] == 'completed' and reviewed['runner_state'] == 'waiting'
    assert reviewed['history'][0]['goal_completion']['proof'] == 'main_review'
    final = s.runtime.control({'action': 'continue', 'run_id': s.run_id,
        'wait_id': waiting['wait']['wait_id']}, 'finish-goal-review')
    assert final['runner_state'] == 'completed' and len(list(tmp_path.glob('commands/*.json'))) == 1


def test_goal_packet_and_source_snapshot_tampering_cannot_complete(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=goal_plan(different=True))
    original = complete_original(s)
    waiting = s.runtime.tick(force=True)
    forged = review_request(s, waiting, original)
    forged['review_packet_sha256'] = 'f' * 64
    with pytest.raises(ValueError):
        s.runtime.control(forged, 'forged-goal-review')
    state = s.runtime.backend.status(s.run_id)
    source = s.runtime.backend._source(state)
    source['completion_snapshot']['goal'] = 'Changed'
    write_json_snapshot(s.runtime.backend._source_path(state['plan_id']), source)
    with pytest.raises(ValueError, match='completion'):
        s.runtime.backend.status(s.run_id)
    assert len(list(tmp_path.glob('commands/*.json'))) == 1


def test_cancel_wins_over_late_goal_review(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=goal_plan(different=True))
    original = complete_original(s)
    waiting = s.runtime.tick(force=True)
    s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-goal')
    with pytest.raises(ValueError):
        s.runtime.control(review_request(s, waiting, original), 'late-goal-review')
    final = s.runtime.tick(force=True)
    assert final['status'] == final['runner_state'] == 'cancelled'
    assert final['history'][0]['action_executed'] is True
    assert len(list(tmp_path.glob('commands/*.json'))) == 1


@pytest.mark.parametrize('forge', ['missing', 'different_condition_as_final_step'])
def test_backend_rejects_final_success_without_matching_goal_proof(tmp_path, monkeypatch, forge):
    s = scene(tmp_path, monkeypatch, source=goal_plan(different=True))
    complete_original(s)
    waiting = s.runtime.tick(force=True)
    result = deepcopy(next(iter(waiting['verification_results'].values())))
    result.pop('review_packet')
    result.update(verdict='success', judged_by='native_condition', reason='declared_native_condition_met')
    if forge == 'missing':
        result.pop('goal_completion')
    else:
        result['goal_completion']['proof'] = 'final_step'
    with pytest.raises(ValueError, match='goal_completion_proof'):
        s.runtime.backend.record_verified_result(s.run_id, 'forged-final-success', result['execution_request_id'], result)
    state = s.runtime.backend.status(s.run_id)
    assert state['status'] == 'pending' and state['history'] == []
    assert len(list(tmp_path.glob('commands/*.json'))) == 1


@pytest.mark.parametrize('kind', ['click', 'input_sequence', 'read_text'])
def test_v3_action_review_is_bound_to_original_plan_and_input_attempt(tmp_path, monkeypatch, kind):
    source = goal_plan()
    if kind == 'input_sequence':
        source['steps'][0]['action'] = {'kind': kind, 'field_goal': 'The visible search field', 'text': 'safe query',
            'clear_existing': True, 'submit_search': True}
    elif kind == 'read_text':
        source['steps'].insert(0, {'step_id': 'read-first', 'action': {'kind': kind, 'goal': 'Read current text'},
            'verification': {'kind': 'agent_judgment'}})
    s = scene(tmp_path, monkeypatch, source=source)
    pending = s.runtime.backend.status(s.run_id)['pending']
    command = pending['suggested_command']
    if kind == 'input_sequence':
        assert command['field_evidence_mode'] == 'visual'
    else:
        assert 'field_evidence_mode' not in command
    if kind == 'read_text':
        assert 'action_review' not in command
    else:
        assert command['action_review'] == {'schema': 'action_review_context.v1', 'plan': source,
            'step_id': pending['step_id'], 'run_id': s.run_id,
            'attempt_id': pending['execution_request_id'], 'budget_ms': 60000}
        state = s.runtime.backend.status(s.run_id)
        state['pending']['suggested_command']['action_review']['attempt_id'] = 'old-attempt'
        write_json_snapshot(s.runtime.backend._path(s.run_id), state)
        with pytest.raises(ValueError, match='pending_command'):
            s.runtime.backend.status(s.run_id)


@pytest.mark.parametrize('version', ['task_plan.v1', 'task_plan.v2', 'task_plan.v3'])
@pytest.mark.parametrize('explicit_target', [False, True])
def test_input_field_evidence_default_preserves_version_and_explicit_target(tmp_path, monkeypatch, version, explicit_target):
    from app.instant_mcp import InstantCommand

    source = goal_plan() if version == 'task_plan.v3' else plan(count=1)
    source['schema_version'] = version
    action = {'kind': 'input_sequence', 'field_goal': 'The visible search field', 'text': 'safe query',
        'clear_existing': True, 'submit_search': True}
    if explicit_target:
        action['target'] = {'name': 'Search', 'control_type': 'Edit',
            'container': {'name': 'Search panel', 'control_type': 'Pane'}}
    source['steps'][0]['action'] = action
    s = scene(tmp_path, monkeypatch, source=source)
    pending = s.runtime.backend.status(s.run_id)['pending']
    command = pending['suggested_command']

    if version == 'task_plan.v3' and not explicit_target:
        assert command['field_evidence_mode'] == 'visual'
        assert 'target' not in command['request']
    else:
        # 省略模式仍使用维护入口原有的 legacy 默认，显式目标不能被视觉路径覆盖。
        assert 'field_evidence_mode' not in command
        assert command.get('field_evidence_mode', 'legacy') == 'legacy'
        if explicit_target:
            assert command['request']['target'] == action['target']
        else:
            assert 'target' not in command['request']
    assert ('action_review' in command) is (version == 'task_plan.v3')
    assert 'field_evidence_mode' not in command['request']
    assert InstantCommand.model_validate(command).command() == command
    assert read_json_snapshot(s.session / 'commands' / (pending['execution_request_id'] + '.json')) == command


@pytest.mark.parametrize('version', ['task_plan.v1', 'task_plan.v2', 'task_plan.v3'])
@pytest.mark.parametrize('explicit_target', [False, True])
def test_direct_input_is_admitted_for_runtime_empty_check_without_changing_legacy(tmp_path, monkeypatch, version, explicit_target):
    source = goal_plan() if version == 'task_plan.v3' else plan(count=1)
    source['schema_version'] = version
    action = {'kind': 'input_sequence', 'field_goal': 'The visible search field', 'text': 'safe query',
        'clear_existing': False, 'submit_search': True}
    if explicit_target:
        action['target'] = {'name': 'Search', 'control_type': 'Edit'}
    source['steps'][0]['action'] = action

    assert validate_task_plan(source) == source
    s = scene(tmp_path, monkeypatch, source=source)
    pending = s.runtime.backend.status(s.run_id)['pending']
    command = pending['suggested_command']
    assert command['request']['clear_existing'] is False
    if version == 'task_plan.v3' and not explicit_target:
        # 入队不是输入授权；运行时仍须用认证截图确认空框。
        assert command['field_evidence_mode'] == 'visual'
        assert command['action_review']['plan'] == source
    else:
        assert 'field_evidence_mode' not in command
    if explicit_target:
        assert command['request']['target'] == action['target']
    assert read_json_snapshot(s.session / 'commands' / (pending['execution_request_id'] + '.json')) == command


def test_v3_successor_backend_default_policy_and_idempotency_include_intervention(tmp_path, monkeypatch):
    parent = plan(count=1)
    parent['schema_version'] = 'task_plan.v2'
    s = scene(tmp_path, monkeypatch, source=parent)
    complete_original(s)
    terminal = s.runtime.tick(force=True)
    child = goal_plan()
    child['steps'][0]['action']['goal'] = 'Open a different safe detail'
    successor = {'successor_request_id': 'goal-successor', 'successor_of': s.run_id,
        'parent_plan_sha256': terminal['plan_sha256'], 'prefix_sha256': terminal['prefix_sha256'],
        'lineage_generation': 0, 'reason': 'A new remaining goal'}
    state = s.runtime.backend.start_successor(child, s.target, successor, transport_request_id='new-goal-control')
    assert state['recovery_policy'] == 'intervention_v1'
    assert s.runtime.backend.successor_lookup(child, s.target, successor) == state
    with pytest.raises(ValueError, match='idempotency_conflict'):
        s.runtime.backend.successor_lookup(child, s.target, successor, recovery_policy='legacy')
