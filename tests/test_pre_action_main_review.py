"""Offline public task-plan controls, original native owner/job and real refusal authentication."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep, perf_counter_ns
from types import SimpleNamespace

import httpx
from PIL import ImageDraw
import pytest

from app.core.json_snapshot import write_json_snapshot
from app.core.agent_grounding_target import AgentGroundingTarget
from app.execution import action_review
from app.execution.task_plan_admission import TaskPlanRuntime
from app.execution.single_step_runtime_owner import SerialRuntimeOwner
from app.execution.local_direct_step import _post_action as REAL_POST_ACTION
from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from app.learning_memory.workflow_runtime import WorkflowRuntime
from app.vision.agent_command_jobs import AgentCommandJobs
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig
from tests.test_agent_grounding_target import scene
from tests.test_local_step_timings import timed_scene
from tests.test_luna_choice_review_provider import decision_body, response_body


def wait(s, status):
    end = monotonic()+4
    while monotonic() < end:
        value = s.jobs.get(s.command_id)
        if value['status'] == status:
            return value
        if value['status'] in {'failed', 'cancelled', 'completed'}:
            result = value.get('result') or {}
            pytest.fail(str({'status': value['status'], 'error': value.get('error'), 'phase': result.get('phase'),
                'response_error': (result.get('response') or {}).get('error'),
                'assessment_reason': (result.get('action_assessment') or {}).get('reason')}))
        sleep(.005)
    pytest.fail(f"did not reach {status}: {value['status']}, {value.get('error')}")


@pytest.fixture
def live_job(scene, timed_scene, monkeypatch, request):
    from app.api import action
    from app.core.local_input_policy import _local_operator_input_scope
    from app.execution import local_direct_step as direct
    options = getattr(request, 'param', 'step')
    kind = options.get('kind', 'step') if isinstance(options, dict) else options
    reply = options.get('reply') if isinstance(options, dict) else None
    external = isinstance(options, dict) and options.get('source') == 'external_api'
    step_count = options.get('steps', 1) if isinstance(options, dict) else 1
    double = isinstance(options, dict) and options.get('double') is True
    state, identity, im, root = scene
    co = timed_scene[0]
    owner = SerialRuntimeOwner(initializer=lambda: None, finalizer=lambda: None)
    request.addfinalizer(owner.close)
    co._owner = owner
    co._memory_library_root = root / 'unused-learning'
    native_identity = {'contract_version': 'windows_native_identity_observation_v1',
        'provider': 'windows_native_identity', 'status': 'observed', **identity,
        'executable_path': 'c:/offline/editor.exe'}
    bound = SimpleNamespace(handle=10, process_id=20, title='Fixture', process_name='editor.exe',
        rect=SimpleNamespace(left=0, top=0, right=200, bottom=150))
    manager = SimpleNamespace(get_bound_window=lambda: bound, bind_window_by_handle=lambda handle: bound)
    co._windows = lambda: manager
    reader = SimpleNamespace(read_identity=lambda handle: deepcopy(native_identity))
    monkeypatch.setattr(direct, 'WindowsNativeIdentityReader', lambda **kwargs: reader)
    monkeypatch.setattr(direct, '_local_operator_input_scope', _local_operator_input_scope)
    monkeypatch.setattr(direct, '_post_action', REAL_POST_ACTION)
    monkeypatch.setattr(direct, 'resolve_render_grace_ms', lambda *args: 0)
    monkeypatch.setattr(action, 'window_manager', manager)
    monkeypatch.setattr(action, 'prepare_browser_content', lambda *args: None)
    monkeypatch.setattr(action, '_render_recognition_plan_overlay_for_execution', lambda *args: None)
    monkeypatch.setattr(action, 'write_trace', lambda **kwargs: str(root/'trace.json'))
    monkeypatch.setattr(action, '_rewrite_execute_trace_result', lambda **kwargs: None)
    s = SimpleNamespace(co=co, root=root, bound=bound, identity=native_identity, im=im, clicks=[],
        calls=[], captures=[], targets=[], damage=None)
    def capture(**kwargs):
        name = 'fresh-'+str(len(s.captures))+'.png'
        path = root/name
        s.im.save(path)
        result = {'image_path': str(path), 'image_width': 200, 'image_height': 150,
            'window_size': {'width': 200, 'height': 150}, 'image_size': {'width': 200, 'height': 150},
            'window_rect': [0, 0, 200, 150], 'roi': None,
            'capture_visibility': {'contract_version': 'bound_capture_visibility_v2', 'allowed': True,
                'coordinate_space': 'window', 'bound_window_handle': 10, 'masked': False, 'occluded_regions': []},
            'sha256': sha256(path.read_bytes()).hexdigest(), 'window_identity': state['capture']['window_identity']}
        s.captures.append(result)
        return result
    monkeypatch.setattr(action.screenshot_service, 'capture_window', capture)
    monkeypatch.setattr(direct, 'ScreenshotService', lambda **kwargs: SimpleNamespace(capture_window=capture))
    monkeypatch.setattr(action.input_controller, 'click_point', lambda x, y, **kwargs:
        s.clicks.append((x,y)) or {'clicked': True, 'window_handle': 10, 'window_point': {'x': x, 'y': y},
            'screen_point': {'x': x, 'y': y}, 'button': 'left', 'click_count': 1,
            'down': {'cursor': {'x': x, 'y': y}}, 'up': {'cursor': {'x': x, 'y': y}}})
    if kind == 'input_sequence':
        import app.core.input_controller as native
        controller = native.InputController()
        s.keys = []
        class Clipboard:
            status = 'not_started'
            def __enter__(self):
                return self
            def verify_current_text(self):
                return 1
            def __exit__(self, *args):
                self.status = 'restored'
        monkeypatch.setattr(controller, '_ensure_windows_input', lambda: None)
        monkeypatch.setattr(controller, '_require_bound_window', lambda: bound)
        monkeypatch.setattr(controller, '_focus_window', lambda *args: pytest.fail('unexpected focus input'))
        monkeypatch.setattr(controller, '_clipboard_text_transaction', lambda *args, **kwargs: Clipboard())
        monkeypatch.setattr(controller, '_press_chord', lambda keys: s.keys.append(tuple(keys)))
        monkeypatch.setattr(controller, 'click_point', action.input_controller.click_point)
        monkeypatch.setattr(native, 'window_manager', manager)
        monkeypatch.setattr(native.win32gui, 'GetForegroundWindow', lambda: 10)
        monkeypatch.setattr(action, 'input_controller', controller)
    monkeypatch.setenv('PRE_ACTION_TEST_KEY', 'offline-only-synthetic-key')
    def handle(request):
        s.calls.append(request)
        if reply == 'primary_auth':
            return httpx.Response(401, json={'error': {'code': 'invalid_api_key'}})
        if reply == 'primary_protocol' or reply == 'ordinary_protocol' and 'responses' in request.url.path:
            return httpx.Response(200, json={'unexpected': 'offline invalid protocol'})
        if reply == 'ordinary_unavailable' and 'responses' in request.url.path:
            return httpx.Response(503, json={'error': {'code': 'unavailable'}})
        body = decision_body() if 'decisions' in request.url.path else response_body('condition_not_met')
        if kind == 'input_sequence' and len(s.calls) > 2:
            answer = body['answers'][0]
            answer.update(choice='condition_met', confidence=.8)
            for row, probability in zip(answer['probabilities'], (.9,.05,.05)):
                row['probability'] = probability
        return httpx.Response(200, json=body)
    client = httpx.Client(transport=httpx.MockTransport(handle))
    from app.execution.visual_field_proof import VISUAL_TEXT_VALUE_CONDITION
    service = DecisionService(root, profile=DecisionProfile.model_validate({
        'contract_version': 'decision_profile.v2', 'mode': 'auto', 'decision_format': 'choice',
        'ordinary_review': 'off' if reply == 'ordinary_off' else 'on_reject', 'api_key_env': 'PRE_ACTION_TEST_KEY', 'request_cap': 20,
        'auto_conditions': [action_review.CANDIDATE_CONDITION, action_review.FRESHNESS_CONDITION,
                action_review.SCENE_CONDITION, VISUAL_TEXT_VALUE_CONDITION]}), provider=OpenAIDecisionsProvider(api_key_env='PRE_ACTION_TEST_KEY', client=client))
    co._decision_service = service
    request.addfinalizer(service.close)
    request.addfinalizer(client.close)
    store = GroundingHandoffStore(root, owner_id='original-owner')
    class Grounder:
        def ground(self, *, request_id, capture, goal, **kwargs):
            result = deepcopy(state['result'])
            result.update(request_id=request_id, capture_id=capture['capture_id'])
            for candidate in result['candidates']:
                candidate['evidence_source'] = 'api_visual'
            return {'result': result}
    jobs = AgentCommandJobs(co, store, capture, RecognitionSourceConfig(source='external_api', api_profile='fixture')
        if external else RecognitionSourceConfig(source='agent_current'), api_grounder=Grounder() if external else None)
    request.addfinalizer(lambda: jobs.close(timeout=2))
    s.jobs, s.store, s.service = jobs, store, service
    original_execute = co.execute_local_step
    def execute(**kwargs):
        s.targets.append(kwargs.get('grounding_target'))
        if external and double:
            # Isolate pre-input adoption from the unrelated double-click
            # diagnostic observer; the native action/review/claim path is real.
            kwargs['include_observation'] = False
        if len(s.targets) == 2 and s.damage:
            s.damage(s, kwargs)
        return original_execute(**kwargs)
    co.execute_local_step = execute
    for name in ('commands', 'responses'):
        (root/name).mkdir(exist_ok=True)
    reviewed = WorkflowRuntime(root, co)
    runtime = TaskPlanRuntime(root, co, owner_id='original-owner',
        target_identity=lambda: owner.call(lambda: {'handle': native_identity['target_window_handle'],
            'process_id': native_identity['process_id'], 'process_create_time': native_identity['process_create_time']}),
        reviewed_runtime=reviewed, agent_jobs=jobs, requires_client_vision=not external)
    s.runtime = runtime
    verification = {'kind': 'agent_judgment', 'decision_condition': 'Search is open.'}
    operation = ({'kind': 'input_sequence', 'field_goal': 'Search', 'text': 'confirmed offline text',
        'clear_existing': True, 'submit_search': False} if kind == 'input_sequence' else {'kind': 'click', 'goal': 'Search'})
    if double:
        operation['click_kind'] = 'double'
    plan = {'schema_version': 'task_plan.v3', 'title': 'Original click', 'goal': 'Open Search', 'inputs': {},
        'steps': [{'step_id': 'open', 'action': operation, 'verification': verification}],
        'completion': {'step_id': 'open', 'verification': verification}}
    for index in range(1, step_count):
        plan['steps'].append({'step_id': 'later-'+str(index), 'action': {'kind': 'click', 'goal': 'Later '+str(index)},
            'verification': deepcopy(verification)})
    plan['completion']['step_id'] = plan['steps'][-1]['step_id']
    first = runtime.control({'action': 'start', 'plan': plan,
        **({'vision_capabilities': {'image_transport': 'supported', 'current_vision': 'supported'}} if not external else {})}, 'start-plan')
    s.run_id = first['run_id']
    pending = first['pending']
    s.command_id = pending['execution_request_id']
    command = pending['suggested_command']
    accepted = jobs.start(s.command_id, command, {'handle': 10, 'process_id': 20}, command.get('vision_capabilities') or {})
    write_json_snapshot(root/'responses'/(s.command_id+'.json'), {'status': 'returned', 'command': command, 'result': accepted})
    if not external:
        grounding = wait(s, 'awaiting_grounding')['pending_grounding']
        result = deepcopy(state['result'])
        result.update(request_id=grounding['request_id'], capture_id=grounding['capture']['capture_id'])
        store.resolve(grounding['request_id'], result)
        jobs.resume(s.command_id, grounding['request_id'], 'original-grounding-execution')
    s.paused = wait(s, 'failed' if reply else 'awaiting_pre_action_review')
    s.waiting = runtime.tick(force=True) if not reply else None
    yield s


def approve(s, verdict='success'):
    request = {**s.waiting['caller_controls']['review']['request'], 'verdict': verdict, 'reason': 'Original bound image checked.'}
    return s.runtime.control(request, 'original-main-review')


def test_public_original_job_review_then_continue_dispatches_one_click(live_job):
    s = live_job
    packet = s.waiting['review_packet']
    assert packet['schema'] == 'pre_action_review_packet.v1'
    assert packet['before']['sha256'] == s.paused['pending_pre_action_review']['before']['sha256']
    assert s.waiting['wait_reason'] == 'verification_required' and s.waiting['history'] == []
    assert s.clicks == [] and len(s.calls) == 2
    assert s.paused['dispatch_in_progress'] is False and s.paused['action_executed'] is False
    reviewed = approve(s)
    assert s.clicks == [] and 'continue' in reviewed['caller_controls']
    assert s.co._owner.call(lambda: 'owner available') == 'owner available'
    s.jobs._jobs[s.command_id].action_review_deadline_ns = perf_counter_ns()-1
    s.runtime.control(reviewed['caller_controls']['continue']['request'], 'original-main-continue')
    done = wait(s, 'completed')
    assert s.clicks == [(65,55)] and len(s.calls) == 2
    assert s.targets[0] is s.targets[1]
    assert len(done['dispatch_attempts']) == 1 and done['dispatch_attempts'][0]['status'] == 'returned'
    assert len(done['local_invocations']) == 2
    assert done['result']['action_assessment'] == packet['assessment']
    assert done['result']['action_assessment']['disposition'] == 'review'
    assert done['result']['main_pre_action_review']['source'] == 'main_agent'
    assert done['pre_action_review']['review']['verdict'] == 'success'
    assert s.store.get(s.targets[0]._state['request_id'])['input_attempted'] is True


def test_main_rejection_stops_original_plan_without_new_attempt(live_job):
    s = live_job
    approve(s, 'failure')
    done = wait(s, 'failed')
    assert s.clicks == [] and len(s.calls) == 2 and done['action_executed'] is False
    final = s.runtime.tick(force=True)
    assert final['runner_state'] == 'failed' and final['pending'] is None
    assert len(list((s.root/'commands').glob('*.json'))) == 1
    for i in range(3):
        assert s.runtime.control({'action': 'status', 'run_id': s.run_id}, 'read-stop-'+str(i))['runner_state'] == 'failed'
    assert len(s.targets) == 1 and len(s.calls) == 2


@pytest.mark.parametrize('field', ['run_id', 'step_id', 'execution_request_id', 'evidence_sha256',
    'review_packet_sha256', 'evidence_set_sha256', 'assessment_round'])
def test_wrong_review_binding_does_not_authorize_or_wake_original(live_job, field):
    s = live_job
    review = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Bound image checked.'}
    review[field] = 1 if field == 'assessment_round' else ('0'*64 if 'sha256' in field else 'different')
    with pytest.raises(ValueError):
        s.runtime.control(review, 'wrong-binding')
    assert s.jobs.get(s.command_id)['status'] == 'awaiting_pre_action_review'
    assert s.clicks == [] and len(s.calls) == 2


def test_duplicate_review_and_continue_do_not_repeat_native_input(live_job):
    s = live_job
    reviewed = approve(s)
    request = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Original bound image checked.'}
    assert s.jobs.review_pre_action(s.command_id, 'original-main-review', request)['review'] == request
    with pytest.raises(ValueError, match='conflict'):
        s.jobs.review_pre_action(s.command_id, 'original-main-review', {**request, 'verdict': 'failure'})
    continuation = reviewed['caller_controls']['continue']['request']
    s.runtime.control(continuation, 'once-continue')
    wait(s, 'completed')
    s.runtime.control(continuation, 'once-continue')
    s.jobs.continue_pre_action(s.command_id, 'once-continue')
    assert s.clicks == [(65,55)] and len(s.targets) == 2 and len(s.calls) == 2


@pytest.mark.parametrize('damage', ['cancel', 'closing', 'expired', 'image', 'packet', 'dirty_queue', 'queued_cancel'])
def test_wait_invalidations_are_known_zero_and_do_not_retry(live_job, damage):
    s = live_job
    record = s.jobs._jobs[s.command_id].pre_action_review_state
    if damage == 'cancel':
        s.jobs.cancel(s.command_id)
    elif damage == 'closing':
        write_json_snapshot(s.root/'closing.json', {'closing': True})
    elif damage == 'expired':
        record['deadline_ns'] = perf_counter_ns()-1
    elif damage == 'image':
        Path(record['packet']['before']['image_path']).write_bytes(b'changed bound image')
    elif damage == 'packet':
        record['packet']['candidate']['click_point']['x'] += 1
    else:
        from app.instant_mcp import InstantCommand
        request = ({'kind': 'task_plan', 'request': {'action': 'cancel', 'run_id': s.run_id}}
            if damage == 'queued_cancel' else {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': {'goal': 'Other'}})
        write_json_snapshot(s.root/'commands'/'competing.json', InstantCommand.model_validate(request).command())
    with s.jobs._condition:
        s.jobs._condition.notify_all()
    done = wait(s, 'cancelled' if damage == 'cancel' else 'failed')
    assert done['action_executed'] is False and done['dispatch_in_progress'] is False
    assert len(done['local_invocations']) == 1
    assert s.clicks == [] and len(s.targets) == 1 and len(s.calls) == 2
    assert s.store.get(s.targets[0]._state['request_id'])['input_attempted'] is False


@pytest.mark.parametrize('damage', ['region', 'geometry', 'identity', 'viewport', 'popup', 'late_capture'])
def test_main_success_still_requires_fresh_native_binding(live_job, monkeypatch, damage):
    s = live_job
    reviewed = approve(s)
    def mutate(current, kwargs):
        if damage == 'region':
            ImageDraw.Draw(current.im).rectangle((30,40,100,70), fill='red')
        elif damage == 'geometry':
            current.bound.rect.right += 1
        elif damage == 'identity':
            current.identity['process_create_time'] += 1
        elif damage == 'viewport':
            current.im = current.im.resize((100,75))
        elif damage == 'popup':
            current.co._windows().read_owned_foreground_popup = lambda bound: {'handle': 99}
        else:
            original = AgentGroundingTarget.plan
            def delayed(target, **options):
                if options.get('main_capture_completed_ns') is not None:
                    sleep(2.05)
                return original(target, **options)
            monkeypatch.setattr(AgentGroundingTarget, 'plan', delayed)
    s.damage = mutate
    s.runtime.control(reviewed['caller_controls']['continue']['request'], 'continue-with-change')
    done = wait(s, 'failed')
    assert s.clicks == [] and done['action_executed'] is False and len(s.calls) == 2
    assert s.store.get(s.targets[0]._state['request_id'])['input_attempted'] is False


@pytest.mark.parametrize('live_job', ['input_sequence'], indirect=True)
def test_compound_focus_main_wait_renews_only_authenticated_suffix(live_job, monkeypatch):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    from app.execution import visual_field_proof
    from app.core import visual_compound_input, agent_grounding_target
    s = live_job
    old = s.jobs._jobs[s.command_id].action_review_deadline_ns
    # The frozen original automatic deadline and grounding expiry are over;
    # Main's separate continuation budget must cover compound typing/value proof.
    monkeypatch.setattr(visual_field_proof, 'perf_counter_ns', lambda: old+1)
    monkeypatch.setattr(visual_compound_input, 'perf_counter_ns', lambda: old+1)
    monkeypatch.setattr(agent_grounding_target, 'time', SimpleNamespace(
        time=lambda: s.targets[0]._state['expires_at']+1, perf_counter_ns=perf_counter_ns))
    reviewed = approve(s)
    s.runtime.control(reviewed['caller_controls']['continue']['request'], 'compound-continue')
    done = wait(s, 'completed')
    assert s.keys.count((VK_CONTROL,VK_A)) == s.keys.count((VK_CONTROL,VK_V)) == 1
    assert s.clicks == [(65,55)] and len(s.calls) == 3
    assert done['result']['input_check']['status'] == 'verified'
    assert done['result']['steps'][0]['receipt']['action_assessment']['disposition'] == 'review'
    assert done['result']['steps'][0]['receipt']['main_pre_action_review']['source'] == 'main_agent'


@pytest.mark.parametrize('live_job', [{'reply': value} for value in (
    'primary_auth', 'primary_protocol', 'ordinary_protocol', 'ordinary_unavailable', 'ordinary_off')], indirect=True)
def test_provider_or_protocol_errors_and_missing_second_refusal_cannot_create_main_capability(live_job):
    s = live_job
    assert s.paused['status'] == 'failed' and s.paused['action_executed'] is False
    assert s.paused['pending_pre_action_review'] is None
    assert s.jobs._jobs[s.command_id].pre_action_review_state is None
    assert s.targets[0]._pre_action_source is None
    assert s.clicks == [] and len(s.targets) == 1


def test_formal_queued_own_controls_survive_response_write_gap_only_while_unchanged(live_job):
    s = live_job
    review = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Original bound image checked.'}
    def queued(request, request_id):
        write_json_snapshot(s.root/'commands'/(request_id+'.json'), {'kind': 'task_plan', 'request': request})
        result = s.runtime.control(request, request_id)
        assert s.runtime._control_id is None
        assert not (s.root/'responses'/(request_id+'.json')).exists()
        return result
    reviewed = queued(review, 'held-review-response')
    sleep(.25)
    assert s.jobs.get(s.command_id)['status'] == 'awaiting_pre_action_review'
    queued(reviewed['caller_controls']['continue']['request'], 'held-continue-response')
    done = wait(s, 'completed')
    assert s.clicks == [(65,55)] and len(s.targets) == 2 and len(done['local_invocations']) == 2


def test_accepted_control_file_cannot_be_changed_to_another_request(live_job):
    s = live_job
    review = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Original bound image checked.'}
    path = s.root/'commands'/'held-review.json'
    write_json_snapshot(path, {'kind': 'task_plan', 'request': review})
    s.runtime.control(review, 'held-review')
    write_json_snapshot(path, {'kind': 'task_plan', 'request': {**review, 'reason': 'changed'}})
    done = wait(s, 'failed')
    assert s.clicks == [] and done['action_executed'] is False and len(done['local_invocations']) == 1


def test_exact_controls_can_wait_in_queue_before_host_reads_them_without_authorizing_input(live_job):
    s = live_job
    review = {**s.waiting['caller_controls']['review']['request'], 'verdict': 'success', 'reason': 'Original bound image checked.'}
    write_json_snapshot(s.root/'commands'/'queued-review.json', {'kind': 'task_plan', 'request': review})
    sleep(.25)
    assert s.jobs.get(s.command_id)['status'] == 'awaiting_pre_action_review' and s.clicks == []
    assert s.jobs._jobs[s.command_id].pre_action_review_state['review'] is None
    reviewed = s.runtime.control(review, 'queued-review')
    continuation = reviewed['caller_controls']['continue']['request']
    write_json_snapshot(s.root/'commands'/'queued-continue.json', {'kind': 'task_plan', 'request': continuation})
    sleep(.25)
    assert s.jobs.get(s.command_id)['status'] == 'awaiting_pre_action_review' and s.clicks == []
    assert s.jobs._jobs[s.command_id].pre_action_review_state['continued'] is False
    s.runtime.control(continuation, 'queued-continue')
    wait(s, 'completed')
    assert s.clicks == [(65,55)] and len(s.calls) == 2


def test_public_mcp_status_compact_and_before_image_preserve_main_instructions(live_job, monkeypatch):
    import asyncio
    import base64
    import json
    from app.instant_mcp import InstantSession, build_server
    s = live_job
    session = InstantSession(Path('D:/agent-gui-runtime'), s.root, recognition_source='agent_current')
    session.session = s.root
    monkeypatch.setattr(session, '_host_alive', lambda: True)
    write_json_snapshot(s.root/'report.json', {'task_plan_run': s.waiting})
    command = {'kind': 'agent_command_status', 'request': {'command_id': s.command_id}}
    write_json_snapshot(s.root/'commands'/'new-status-id.json', command)
    write_json_snapshot(s.root/'responses'/'new-status-id.json',
        {'command': command, 'status': 'returned', 'result': s.paused})
    server = build_server(session)
    result = asyncio.run(server.call_tool('instant_image', {'request_id': 'new-status-id', 'view': 'before'}))
    assert not result.is_error
    pixels = base64.b64decode(result.content[0].data)
    assert sha256(pixels).hexdigest() == s.waiting['review_packet']['before']['sha256']
    status = asyncio.run(server.call_tool('instant_status', {}))
    value = json.loads(status.content[0].text)
    assert list(value)[:2] == ['pre_action_review', 'caller_controls']
    assert value['caller_controls']['review']['request'] == s.waiting['caller_controls']['review']['request']
    compact = asyncio.run(server.call_tool('instant_result', {'request_id': 'new-status-id', 'detail': 'compact'}))
    value = json.loads(compact.content[0].text)
    assert list(value)[0] == 'pre_action_review'
    assert value['pre_action_review']['image']['view'] == 'before'
    assert value['pre_action_review']['original_refusal']['adopted'] is False
    assert s.clicks == [] and len(s.calls) == 2


def test_public_shared_client_returns_pre_action_packet_without_poll_or_file_reads(live_job):
    import asyncio
    from tests.test_task_plan_client import Session, client, COMMAND
    s = live_job
    session = Session([s.waiting])
    value = asyncio.run(client(s.root, session).run_plan('start-plan', COMMAND, total_timeout=1))
    assert value['client_state'] == 'review_required'
    assert value['result']['review_packet'] == s.waiting['review_packet']
    assert value['result']['caller_controls'] == s.waiting['caller_controls']
    assert len(session.calls) == 1 and s.clicks == []
