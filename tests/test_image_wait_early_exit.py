"""图像等待仅在已审核复用策略早退；虚拟时钟限定只读预算。"""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from tests.test_image_verification import sample
from tests.test_workflow_trial import services, WORKFLOW


class Clock:
    def __init__(self):
        self.now = 0.0
        self.waits = []
        self.cancelled = False
    def monotonic(self):
        return self.now
    def is_set(self):
        return self.cancelled
    def wait(self, seconds):
        self.waits.append(seconds)
        self.now = round(self.now + seconds, 9)
        return self.cancelled


def observe_setup(tmp_path, monkeypatch, *, success_at=None, capture_duration=0):
    import app.learning_memory.image_verification as module
    check, raw, _, frame = sample(tmp_path)
    clock = Clock(); captures = []
    def capture(*args, **kwargs):
        assert kwargs == {'recipe': None}
        captures.append(clock.now)
        clock.now += capture_duration
        return deepcopy(frame), {}
    def match(*args):
        matched = success_at is not None and clock.now >= success_at
        return {'matched': matched, 'reason': 'image_matched' if matched else 'image_not_matched'}
    monkeypatch.setattr(module, 'monotonic', clock.monotonic, raising=False)
    monkeypatch.setattr(module, 'sleep', clock.wait)
    monkeypatch.setattr(module, 'match_image_check', match)
    monkeypatch.setattr('app.learning_memory.memory_observation.capture_memory_observation', capture)
    co = SimpleNamespace(_cancel_wait=clock)
    run = lambda: module.observe_image_check(co, target={'handle': 1, 'process_id': 2},
        identity=frame['window_identity'], check=check, reference_raw=raw)
    return run, clock, captures, frame


def test_first_success_has_no_wait(tmp_path, monkeypatch):
    run, clock, captures, _ = observe_setup(tmp_path, monkeypatch, success_at=0)
    assert run()['complete']
    assert captures == [0] and clock.waits == []


def test_delayed_render_after_200ms_succeeds_before_budget(tmp_path, monkeypatch):
    run, clock, captures, _ = observe_setup(tmp_path, monkeypatch, success_at=.6)
    assert run()['complete']
    assert captures[-1] == .6 and clock.now == .6


def test_persistent_miss_does_not_capture_at_or_after_deadline(tmp_path, monkeypatch):
    run, clock, captures, _ = observe_setup(tmp_path, monkeypatch)
    assert not run()['complete']
    assert clock.now == 2 and all(at < 2 for at in captures)
    assert len(captures) == 20


def test_slow_capture_consumes_budget_and_cannot_add_extra_capture(tmp_path, monkeypatch):
    run, clock, captures, _ = observe_setup(tmp_path, monkeypatch, capture_duration=.8)
    assert not run()['complete']
    assert captures == [0, .9, 1.8] and clock.now == pytest.approx(2.6)


@pytest.mark.parametrize('stage', ['before', 'during_wait'])
def test_cancel_stops_polling_without_extra_capture(tmp_path, monkeypatch, stage):
    run, clock, captures, _ = observe_setup(tmp_path, monkeypatch)
    if stage == 'before':
        clock.cancelled = True
    else:
        def cancel_wait(seconds):
            clock.cancelled = True
            return True
        clock.wait = cancel_wait
    result = run()
    assert not result['complete'] and result['reason'] == 'workflow_image_observation_cancelled'
    assert len(captures) == (0 if stage == 'before' else 1)


@pytest.mark.parametrize('reason', ['image_ambiguous', 'workflow_image_reference_sha256_changed', 'unknown'])
def test_non_mismatch_is_not_polled(tmp_path, monkeypatch, reason):
    run, clock, captures, _ = observe_setup(tmp_path, monkeypatch)
    monkeypatch.setattr('app.learning_memory.image_verification.match_image_check',
        lambda *args: {'matched': False, 'reason': reason})
    assert run()['reason'] == reason
    assert captures == [0] and clock.waits == []


@pytest.mark.parametrize('failure', ['identity', 'sha', 'read', 'cancel_during_capture'])
def test_invalid_capture_never_succeeds_or_retries(tmp_path, monkeypatch, failure):
    run, clock, captures, frame = observe_setup(tmp_path, monkeypatch, success_at=0)
    def capture(*args, **kwargs):
        captures.append(clock.now)
        if failure == 'read':
            raise OSError('unreadable current PNG')
        if failure == 'cancel_during_capture':
            clock.cancelled = True
        if failure == 'identity':
            frame['window_identity'] = {'handle': 99}
        return deepcopy(frame), {}
    monkeypatch.setattr('app.learning_memory.memory_observation.capture_memory_observation', capture)
    if failure == 'sha':
        def invalid_match(*args):
            raise ValueError('workflow_image_capture_sha256_changed')
        monkeypatch.setattr('app.learning_memory.image_verification.match_image_check', invalid_match)
    result = run()
    assert not result['complete'] and result['values'] == {}
    assert len(captures) == 1 and clock.waits == []


@pytest.mark.parametrize('kind', ['click', 'input_sequence', 'scroll'])
@pytest.mark.parametrize('strategy,reviewed,image,override', [
    ('learned', True, True, True), ('learned', False, True, False),
    ('steps_only', True, True, False), ('learned', True, False, False)])
def test_prepare_zero_wait_only_for_reviewed_image_learned_strategy(services, tmp_path, kind, strategy, reviewed, image, override):
    programs, trials, saved, _ = services
    programs.library._artifact_root = tmp_path
    check, _, _, _ = sample(tmp_path)
    definition = deepcopy(saved['definition'])
    definition['steps'] = definition['steps'][:1]
    step = definition['steps'][0]
    step.update(outputs=[], success_conditions=[], branches={'success': None, 'failure': None, 'uncertain': None},
        verification={'kind': 'agent_judgment'})
    if kind == 'click':
        step['action'] = {'kind': 'click', 'goal': 'Open detail'}
    elif kind == 'scroll':
        step['action'] = {'kind': 'scroll', 'direction': 'down', 'amount': 1}
    if image:
        step['verification']['image_check'] = check
    saved = programs.save(WORKFLOW, saved['content_sha256'], definition, 'wait-config')
    if reviewed:
        definition = deepcopy(saved['definition']); definition['steps'][0]['review_status'] = 'reviewed'
        saved = programs.save(WORKFLOW, saved['content_sha256'], definition, 'wait-review')
    run = trials.start(WORKFLOW, saved['program_id'], 'search', {'query': 'new'}, 'wait-start', execution_strategy=strategy)
    before = deepcopy(saved)
    ticket = trials.prepare(run['run_id'], 'wait-prepare')
    command = ticket['suggested_command']
    assert ('observation_wait_ms' in command) is override
    if override:
        assert command['observation_wait_ms'] == 0
    from app.instant_mcp import InstantCommand
    assert InstantCommand.model_validate(command).command() == command
    assert programs.load(WORKFLOW, saved['program_id']) == before
    assert trials.prepare(run['run_id'], 'wait-prepare-again')['execution_request_id'] == ticket['execution_request_id']
