"""字段审核保留同一个待执行票据；审核与继续不得合并成输入。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from tests.test_task_plan_adaptive_review import adaptive_plan
from tests.test_task_plan_runner import scene, complete_original


def field_scene(tmp_path, monkeypatch):
    s = scene(tmp_path, monkeypatch, source=adaptive_plan())
    original = complete_original(s, async_receipt=True)
    path = tmp_path / 'agent-commands' / (original.command_id + '.json')
    state = read_json_snapshot(path)
    state['status'] = 'awaiting_field_review'
    write_json_snapshot(path, state)
    packet = {'schema': 'field_review_packet.v1', 'run_id': s.run_id,
        'step_id': 'step-0', 'execution_request_id': original.command_id,
        'plan_sha256': s.first['plan_sha256'], 'after': original.capture,
        'packet_sha256': 'a' * 64, 'evidence_set_sha256': 'b' * 64, 'assessment_round': 0}
    box = {'packet': packet, 'review': None, 'continued': False}
    calls = []
    def review(command_id, request_id, request):
        assert command_id == original.command_id
        calls.append(('review', request_id))
        box['review'] = deepcopy(request)
        return deepcopy(box)
    def resume(command_id, request_id):
        assert command_id == original.command_id
        calls.append(('continue', request_id))
        box['continued'] = True
        state['status'] = 'running'
        write_json_snapshot(path, state)
        return deepcopy(state)
    s.runtime.agent_jobs = SimpleNamespace(
        get_field_review=lambda command_id: deepcopy(box) if command_id == original.command_id else None,
        review_field=review, continue_field=resume, cancel=lambda command_id: calls.append(('cancel', command_id)))
    return s, original, box, calls


def test_field_review_preserves_pending_and_only_continue_resumes_original_job(tmp_path, monkeypatch):
    s, original, box, calls = field_scene(tmp_path, monkeypatch)
    waiting = s.runtime.tick(force=True)
    assert waiting['wait_reason'] == 'verification_required'
    assert waiting['pending']['execution_request_id'] == original.command_id
    assert waiting['history'] == []
    assert waiting['review_packet'] == box['packet']
    controls = waiting['caller_controls']
    assert 'continue' not in controls
    request = {**controls['review']['request'], 'verdict': 'success', 'reason': 'Original text is correct'}
    reviewed = s.runtime.control(request, 'main-field-review')
    assert calls == [('review', 'main-field-review')]
    assert reviewed['history'] == [] and reviewed['pending'] == waiting['pending']
    for index in range(3):
        s.runtime.control({'action': 'status', 'run_id': s.run_id}, 'read-' + str(index))
        assert s.runtime.tick(force=True) is None
    assert len(list(tmp_path.glob('commands/*.json'))) == 1
    continued = s.runtime.control(reviewed['caller_controls']['continue']['request'], 'resume-field')
    assert calls[-1] == ('continue', 'resume-field')
    assert continued['wait_reason'] == 'execution_pending'
    assert continued['pending']['execution_request_id'] == original.command_id
    s.runtime.control(reviewed['caller_controls']['continue']['request'], 'resume-field')
    assert calls.count(('continue', 'resume-field')) == 1
    assert len(list(tmp_path.glob('commands/*.json'))) == 1


@pytest.mark.parametrize('mutation', ['run_id', 'step_id', 'execution_request_id', 'plan_sha256'])
def test_field_review_projection_rejects_cross_bound_packet(tmp_path, monkeypatch, mutation):
    s, _, box, calls = field_scene(tmp_path, monkeypatch)
    box['packet'][mutation] = 'wrong'
    with pytest.raises(ValueError, match='field_review_binding'):
        s.runtime.tick(force=True)
    assert calls == []


def test_field_continue_without_review_or_after_target_change_cannot_wake_job(tmp_path, monkeypatch):
    s, _, box, calls = field_scene(tmp_path, monkeypatch)
    waiting = s.runtime.tick(force=True)
    continuation = {'action': 'continue', 'run_id': s.run_id, 'wait_id': waiting['wait']['wait_id']}
    with pytest.raises(ValueError, match='field_review_required'):
        s.runtime.control(continuation, 'premature')
    request = {**waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Text matches'}
    s.runtime.control(request, 'field-reviewed')
    s.target['handle'] += 1
    with pytest.raises(ValueError, match='target_changed'):
        s.runtime.control(continuation, 'wrong-target')
    assert calls == [('review', 'field-reviewed')]


def test_cancelled_field_wait_has_no_review_or_continue_controls(tmp_path, monkeypatch):
    s, _, _, calls = field_scene(tmp_path, monkeypatch)
    s.runtime.tick(force=True)
    cancelled = s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-field')
    assert 'caller_controls' not in cancelled
    assert calls[0][0] == 'cancel'


def test_only_original_pending_plan_can_authorize_a_field_wait(tmp_path, monkeypatch):
    source = adaptive_plan()
    source.update(schema_version='task_plan.v3', goal='Open the requested detail',
        completion={'step_id': source['steps'][-1]['step_id'],
            'verification': deepcopy(source['steps'][-1]['verification'])})
    s = scene(tmp_path, monkeypatch, source=source)
    pending = s.first['pending']
    command_id = pending['execution_request_id']
    context = pending['suggested_command']['action_review']
    assert s.runtime._field_review_plan_matches(command_id, context)
    assert not s.runtime._field_review_plan_matches('unrelated-command', context)
    changed = deepcopy(context)
    changed['step_id'] = 'unrelated-step'
    assert not s.runtime._field_review_plan_matches(command_id, changed)
    s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-original')
    assert not s.runtime._field_review_plan_matches(command_id, context)


def test_cancel_keeps_polling_while_original_field_worker_is_exiting(tmp_path, monkeypatch):
    s, original, _, calls = field_scene(tmp_path, monkeypatch)
    s.runtime.tick(force=True)
    s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-before-worker-exit')
    waiting = s.runtime.tick(force=True)
    assert waiting['wait_reason'] == 'execution_pending'
    assert s.runtime._enabled_run == s.run_id
    assert 'caller_controls' not in waiting and waiting['pending'] is not None
    complete_original(s, async_receipt=True)
    settled = s.runtime.tick(force=True)
    assert settled['runner_state'] == 'cancelled' and settled['pending'] is None
    assert len(calls) == 1 and calls[0][0] == 'cancel'
    assert len(list(tmp_path.glob('commands/*.json'))) == 1
