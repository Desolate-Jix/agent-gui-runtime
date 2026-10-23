"""Shared client handoff and final pre-input failure boundaries (all offline)."""
import asyncio
from copy import deepcopy
from time import sleep, perf_counter_ns

import pytest

from app.core.json_snapshot import write_json_snapshot
from app.execution.main_pre_action_approval import MainPreActionApproval, _issue_main_pre_action_approval
from tests.test_learning_benchmark_client import FakeSDK, client
from tests.test_pre_action_main_review import scene, timed_scene, live_job, wait, approve


@pytest.mark.parametrize('initial', ['running', 'awaiting_pre_action_review'])
def test_shared_agent_client_returns_new_wait_without_polling_forever(live_job, initial):
    s = live_job
    class SDK(FakeSDK):
        @staticmethod
        def agent_receipt(request_id, command_id, state):
            value = FakeSDK.agent_receipt(request_id, command_id, state)
            if state == 'awaiting_pre_action_review':
                value['result']['pending_pre_action_review'] = deepcopy(s.paused['pending_pre_action_review'])
            return value
    sdk = SDK()
    sdk.agent_initial = initial
    sdk.agent_statuses = ['awaiting_pre_action_review']
    async def run():
        async with client(s.root, sdk, allow_actions=True) as opened:
            return await opened.run(s.command_id, {'kind': 'step', 'operation': 'execute_recognition_plan',
                'request': {'goal': 'Search'}}, total_timeout=1)
    result = asyncio.run(run())
    assert result['client_state'] == 'review_required' and result['command_id'] == s.command_id
    assert result['result']['pending_pre_action_review'] == s.paused['pending_pre_action_review']
    assert len([name for name, _ in sdk.calls if name == 'instant_run']) == (2 if initial == 'running' else 1)
    assert s.clicks == []


@pytest.mark.parametrize('field', ['run_id', 'review_packet_sha256', 'evidence_sha256', 'verdict'])
def test_wrong_queued_recipe_stops_without_becoming_accepted_control(live_job, field):
    s = live_job
    request = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Image checked.'}
    request[field] = 'invalid' if field == 'verdict' else ('0'*64 if 'sha256' in field else 'another-run')
    write_json_snapshot(s.root/'commands'/'wrong-queued-review.json', {'kind': 'task_plan', 'request': request})
    done = wait(s, 'failed')
    assert done['action_executed'] is False and s.clicks == []
    assert s.jobs._jobs[s.command_id].pre_action_review_state['accepted_controls'] == {}


def test_possible_native_input_after_claim_is_never_restored_to_original_zero(live_job, monkeypatch):
    from app.api import action
    s = live_job
    reviewed = approve(s)
    def unknown(*args, **kwargs):
        raise RuntimeError('offline input boundary unknown')
    monkeypatch.setattr(action.input_controller, 'click_point', unknown)
    s.runtime.control(reviewed['caller_controls']['continue']['request'], 'unknown-native-continue')
    done = wait(s, 'failed')
    assert s.targets[0].input_claimed is True
    assert done['action_executed'] is None
    assert done['result']['phase'] == 'result_unknown'
    assert s.store.get(s.targets[0]._state['request_id'])['input_attempted'] is True


def test_prior_unknown_input_response_keeps_queue_dirty(live_job):
    s = live_job
    command = {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': {'goal': 'Other'}}
    write_json_snapshot(s.root/'commands'/'prior-unknown.json', command)
    write_json_snapshot(s.root/'responses'/'prior-unknown.json', {'status': 'failed', 'command': command,
        'result': {'phase': 'result_unknown'}})
    done = wait(s, 'failed')
    assert done['action_executed'] is False and s.clicks == []


@pytest.mark.parametrize('fault', ['json', 'unbounded', 'wrong_image'])
def test_saved_json_or_unbound_main_review_cannot_mint_capability(live_job, fault):
    s = live_job
    source = s.targets[0]._pre_action_source
    packet = s.waiting['review_packet']
    review = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Image checked.'}
    if fault == 'json':
        with pytest.raises(ValueError, match='issuer'):
            MainPreActionApproval(None, source=source, packet=packet, review=review,
                validator=lambda: True, deadline_ns=perf_counter_ns()+60_000_000_000)
    else:
        if fault == 'wrong_image':
            review['evidence_sha256'] = '0'*64
        deadline = perf_counter_ns()+(61_000_000_000 if fault == 'unbounded' else 5_000_000_000)
        with pytest.raises(ValueError, match='binding'):
            _issue_main_pre_action_approval(source=source, packet=packet, review=review,
                validator=lambda: True, deadline_ns=deadline)
    assert s.clicks == [] and s.jobs.get(s.command_id)['status'] == 'awaiting_pre_action_review'
