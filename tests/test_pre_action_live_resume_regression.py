"""Regression for the live external-API, multi-step graphic review wait."""
from time import sleep
from threading import Event, Thread

import pytest

from app.core.json_snapshot import write_json_snapshot
from app.core.instant_command_queue import command_queue_lock
from tests.test_pre_action_main_review import scene, timed_scene, live_job, wait


@pytest.fixture
def initial_queue_contention(monkeypatch):
    from types import SimpleNamespace
    from app.vision.pre_action_review_wait import PreActionReviewWait
    original = PreActionReviewWait._pre_action_bound
    state = SimpleNamespace(threads=[], observed=[], automatic_deadline=None)
    def bound(jobs, job):
        if not state.threads and job.pre_action_review_state is None:
            entered = Event()
            state.automatic_deadline = job.action_review_deadline_ns
            def hold():
                with command_queue_lock(jobs.store.session_root):
                    entered.set()
                    sleep(.15)
                    state.observed.append((job.pre_action_review_state, job.action_review_deadline_ns))
            thread = Thread(target=hold)
            state.threads.append(thread)
            thread.start()
            assert entered.wait(timeout=1)
        return original(jobs, job)
    monkeypatch.setattr(PreActionReviewWait, '_pre_action_bound', bound)
    yield state
    for thread in state.threads:
        thread.join(timeout=2)


@pytest.fixture
def initially_contended_job(initial_queue_contention, request):
    return request.getfixturevalue('live_job'), initial_queue_contention


def test_initial_offer_waits_for_queue_without_starting_main_deadline_early(initially_contended_job):
    s, contention = initially_contended_job
    assert contention.observed == [(None, contention.automatic_deadline)]
    assert s.jobs._jobs[s.command_id].action_review_deadline_ns == contention.automatic_deadline
    assert s.jobs.get(s.command_id)['status'] == 'awaiting_pre_action_review'
    assert s.clicks == [] and len(s.calls) == 2


@pytest.mark.parametrize('live_job', [{'source': 'external_api', 'steps': 4, 'double': True}], indirect=True)
def test_external_api_multistep_double_click_resumes_original_job_via_native_queue(live_job):
    s = live_job
    review = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Original graphic row checked.'}
    write_json_snapshot(s.root/'commands'/'queued-review.json', {'kind': 'task_plan', 'request': review})
    sleep(.25)
    reviewed = s.runtime.control(review, 'queued-review')
    write_json_snapshot(s.root/'responses'/'queued-review.json', {'status': 'returned', 'result': reviewed})
    request = reviewed['caller_controls']['continue']['request']
    write_json_snapshot(s.root/'commands'/'queued-continue.json', {'kind': 'task_plan', 'request': request})
    sleep(.25)
    continued = s.runtime.control(request, 'queued-continue')
    write_json_snapshot(s.root/'responses'/'queued-continue.json', {'status': 'returned', 'result': continued})
    done = wait(s, 'completed')
    assert done['result']['main_pre_action_review']['source'] == 'main_agent'
    assert len(s.calls) == 2 and len(s.targets) == 2 and s.targets[0] is s.targets[1]
    assert s.clicks == [(65,55)]


@pytest.mark.parametrize('live_job', [{'source': 'external_api', 'steps': 4, 'double': True}], indirect=True)
def test_runner_reconcile_while_resumed_worker_has_not_entered_second_local_call(live_job, monkeypatch):
    import app.vision.pre_action_review_wait as module
    s = live_job
    entered, release = Event(), Event()
    original = module._issue_main_pre_action_approval
    def parked(**kwargs):
        entered.set()
        if not release.wait(timeout=3):
            raise RuntimeError('offline resume barrier expired')
        return original(**kwargs)
    monkeypatch.setattr(module, '_issue_main_pre_action_approval', parked)
    review = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Original graphic row checked.'}
    reviewed = s.runtime.control(review, 'review-before-barrier')
    request = reviewed['caller_controls']['continue']['request']
    write_json_snapshot(s.root/'commands'/'continue-before-barrier.json', {'kind': 'task_plan', 'request': request})
    try:
        continued = s.runtime.control(request, 'continue-before-barrier')
        assert entered.wait(timeout=1)
        assert s.jobs.get(s.command_id)['status'] == 'running'
        assert len(s.targets) == len(s.jobs.get(s.command_id)['local_invocations']) == 1
        assert continued['runner_state'] == 'waiting' and continued['wait_reason'] == 'execution_pending'
        assert s.runtime.runner.advance(s.run_id)['wait_reason'] == 'execution_pending'
        assert s.runtime.runner.status(s.run_id)['status'] == 'pending'
        assert s.runtime._pre_action_plan_matches(s.command_id, s.jobs._jobs[s.command_id].action_review)
    finally:
        release.set()
    wait(s, 'completed')
    assert s.clicks == [(65,55)]


def test_continue_admission_queue_lock_does_not_revoke_waiting_original_job(live_job, monkeypatch):
    """The host's own admit runs under the same nonblocking cancellation-queue lock."""
    s = live_job
    review = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Original bound image checked.'}
    reviewed = s.runtime.control(review, 'review-before-admit')
    request = reviewed['caller_controls']['continue']['request']
    command = {'kind': 'task_plan', 'request': request}
    write_json_snapshot(s.root/'commands'/'continue-held-in-admit.json', command)
    entered, release = Event(), Event()
    original = s.runtime.reviewed_runtime._admit_input
    failures = []
    def parked(*args):
        entered.set()
        if not release.wait(timeout=3):
            raise RuntimeError('offline queue barrier expired')
        return original(*args)
    monkeypatch.setattr(s.runtime.reviewed_runtime, '_admit_input', parked)
    def admit():
        try:
            s.runtime.admit('continue-held-in-admit', command)
        except Exception as error:
            failures.append(error)
    thread = Thread(target=admit)
    thread.start()
    try:
        assert entered.wait(timeout=1)
        sleep(.25)
        snapshot = s.jobs.get(s.command_id)
        assert snapshot['status'] == 'awaiting_pre_action_review', snapshot.get('pre_action_resolution')
        assert s.clicks == [] and len(snapshot['local_invocations']) == 1
    finally:
        release.set()
        thread.join(timeout=2)
    assert not thread.is_alive() and failures == []
    continued = s.runtime.control(request, 'continue-held-in-admit')
    write_json_snapshot(s.root/'responses'/'continue-held-in-admit.json', {'status': 'returned', 'result': continued})
    wait(s, 'completed')
    assert s.clicks == [(65,55)] and len(s.calls) == 2 and len(s.targets) == 2


@pytest.mark.parametrize('damage', ['queued_cancel', 'foreign_input', 'closing', 'expired', 'cancel'])
def test_queue_contention_rechecks_invalidations_without_authorizing_or_extending_wait(live_job, damage):
    from time import perf_counter_ns
    from app.instant_mcp import InstantCommand
    s = live_job
    record = s.jobs._jobs[s.command_id].pre_action_review_state
    deadline = record['deadline_ns']
    with command_queue_lock(s.root):
        with s.jobs._condition:
            s.jobs._condition.notify_all()
        sleep(.15)
        assert s.jobs.get(s.command_id)['status'] == 'awaiting_pre_action_review'
        assert record['deadline_ns'] == deadline and s.clicks == []
        if damage in {'queued_cancel', 'foreign_input'}:
            command = ({'kind': 'task_plan', 'request': {'action': 'cancel', 'run_id': s.run_id}}
                if damage == 'queued_cancel' else {'kind': 'step', 'operation': 'execute_recognition_plan',
                    'request': {'goal': 'Unrelated input'}})
            write_json_snapshot(s.root/'commands'/'new-competing-input.json', InstantCommand.model_validate(command).command())
        elif damage == 'closing':
            write_json_snapshot(s.root/'closing.json', {'closing': True})
        elif damage == 'expired':
            record['deadline_ns'] = perf_counter_ns()-1
        else:
            s.jobs.cancel(s.command_id)
        if damage in {'expired', 'closing', 'cancel'}:
            done = wait(s, 'cancelled' if damage == 'cancel' else 'failed')
            assert done['action_executed'] is False
    done = wait(s, 'cancelled' if damage == 'cancel' else 'failed')
    assert done['action_executed'] is False and len(done['local_invocations']) == 1
    assert s.clicks == [] and len(s.targets) == 1 and len(s.calls) == 2
    assert not record['continued'] and s.targets[0]._main_pre_action is None
    if damage == 'queued_cancel':
        assert 'TaskPlanCancelPending' in done['pre_action_resolution']['reason']
    elif damage == 'foreign_input':
        assert 'queued_command_not_bound:new-competing-input' in done['pre_action_resolution']['reason']


def test_continued_queue_contention_does_not_renew_two_second_capture_lease(live_job, monkeypatch):
    from app.core.agent_grounding_target import AgentGroundingTarget
    from time import monotonic
    s = live_job
    review = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Original bound image checked.'}
    reviewed = s.runtime.control(review, 'review-before-fresh-lock')
    entered, release = Event(), Event()
    holder = []
    recorded = []
    original = AgentGroundingTarget.plan
    def plan(target, **kwargs):
        result = original(target, **kwargs)
        if target._main_fresh is not None:
            recorded.append(target._main_fresh['checked_ns'])
            def hold():
                with command_queue_lock(s.root):
                    entered.set()
                    release.wait(timeout=2.15)
            thread = Thread(target=hold)
            holder.append(thread)
            thread.start()
            assert entered.wait(timeout=1)
        return result
    monkeypatch.setattr(AgentGroundingTarget, 'plan', plan)
    started = monotonic()
    try:
        s.runtime.control(reviewed['caller_controls']['continue']['request'], 'continue-fresh-lock')
        done = wait(s, 'failed')
    finally:
        release.set()
        for thread in holder:
            thread.join(timeout=2)
    assert monotonic()-started >= 2
    assert len(recorded) == 1 and s.targets[0]._main_fresh['checked_ns'] == recorded[0]
    assert s.clicks == [] and done['action_executed'] is False and len(s.calls) == 2
    assert not s.targets[0].input_claimed
