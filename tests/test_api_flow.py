"""真实回环 HTTP 到公共动作路由；仅系统窗口、截图和物理输入边界隔离。"""
from copy import deepcopy
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from app.vision.agent_command_jobs import AgentCommandJobs
from app.vision.external_grounding_api import ApiGroundingProfile, ChatCompletionsGrounder
from app.vision.grounding_handoff import GroundingHandoffStore
from app.vision.recognition_source import RecognitionSourceConfig
from scripts.run_local_step_session import dispatch_agent_command


@pytest.fixture
def api_server(monkeypatch):
    state = SimpleNamespace(requests=[], status=200, mode='found', entered=Event(), release=Event())
    state.release.set()
    monkeypatch.setenv('FLOW_TEST_KEY', 'local-test-key-not-a-credential')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            context = json.loads(body['messages'][1]['content'][0]['text'])
            png = base64.b64decode(body['messages'][1]['content'][1]['image_url']['url'].split(',', 1)[1])
            state.requests.append({'context': context, 'png': png})
            state.entered.set()
            state.release.wait(5)
            result = {'schema_version': 'grounding.v1', 'request_id': context['request_id'],
                'capture_id': context['capture_id'], 'status': state.mode,
                'coordinate_space': 'capture_image_pixels', 'image_size': context['image_size'],
                'candidates': [], 'selected_candidate_id': None}
            if state.mode == 'found':
                result.update(candidates=[{'id': 'button', 'label': 'Search',
                    'bbox': {'x': 30, 'y': 40, 'width': 71, 'height': 31},
                    'click_point': {'x': 65, 'y': 55}, 'evidence_source': 'api_visual'}],
                    selected_candidate_id='button')
            if state.mode == 'malformed':
                result = {'not_a_candidate': True}
            encoded = json.dumps({'model': 'loopback-fixture', 'usage': {'total_tokens': 12},
                'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]}).encode()
            self.send_response(state.status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.profile = ApiGroundingProfile(endpoint=f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
        model='loopback-fixture', api_key_env='FLOW_TEST_KEY')
    yield state
    state.release.set()
    server.shutdown()
    server.server_close()
    thread.join(3)


@pytest.fixture
def flow(tmp_path, monkeypatch, api_server):
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.core.agent_grounding_target import agent_grounding_scope
    from app.core.local_input_policy import _local_operator_input_scope
    from app.desktop_review.local_action_contract import _validated_request
    from app.learning_memory.learning_observation_capture import learning_capture_scope
    from app.instant_mcp import InstantCommand

    image = Image.new('RGB', (200, 150), 'white')
    ImageDraw.Draw(image).rectangle((30, 40, 100, 70), fill='blue')
    identity = {'contract_version': 'windows_native_identity_observation_v1',
        'provider': 'windows_native_identity', 'status': 'observed', 'target_window_handle': 10,
        'process_id': 20, 'process_create_time': 30.0, 'executable_path': 'c:\\fixture\\editor.exe'}
    bound = SimpleNamespace(handle=10, process_id=20, title='Fixture', process_name='editor.exe',
        rect=SimpleNamespace(left=100, top=200, right=300, bottom=350))
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    reader = SimpleNamespace(read_identity=lambda _: deepcopy(identity))
    frames, clicks = [], []

    def capture():
        path = tmp_path / f'capture-{len(frames)}.png'
        image.save(path)
        frames.append(path)
        return {'image_path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest(),
            'window_size': {'width': 200, 'height': 150}, 'roi': None,
            'window_identity': {'handle': 10, 'process_id': 20, 'process_create_time': 30.0}}

    def click(x, y, **kwargs):
        clicks.append((x, y))
        ImageDraw.Draw(image).rectangle((160, 100, 190, 130), fill='green')
        return {'clicked': True, 'point': {'x': x, 'y': y}}

    monkeypatch.setattr(action, 'window_manager', manager)
    monkeypatch.setattr(action.screenshot_service, 'capture_window', lambda **kwargs: capture())
    monkeypatch.setattr(action, 'prepare_browser_content', lambda *args: None)
    monkeypatch.setattr(action, '_render_recognition_plan_overlay_for_execution', lambda p: None)
    monkeypatch.setattr(action, 'write_trace', lambda **kwargs: str(tmp_path / 'trace.json'))
    monkeypatch.setattr(action, '_rewrite_execute_trace_result', lambda **kwargs: None)
    monkeypatch.setattr(action.input_controller, 'click_point', click)

    class Coordinator:
        _owner = SimpleNamespace(call=lambda callback: callback())
        learning_context = None

        def _windows(self):
            return manager

        def execute_local_step(self, **kwargs):
            request = ExecuteRecognitionPlanRequest.model_validate(_validated_request(
                'execute_recognition_plan', kwargs['request']))
            learning_context = kwargs.get('learning_context')
            if learning_context is None:
                learning_context = self.learning_context
            with learning_capture_scope(self, learning_context), agent_grounding_scope(kwargs['grounding_target']), _local_operator_input_scope(
                manager=manager, identity_reader=reader, identity=identity,
                window_rect=(100, 200, 300, 350), enabled=lambda: True):
                result = action.execute_recognition_plan(request)
            return {'phase': 'returned', 'response': result.model_dump(),
                'observation': {'status': 'captured', 'capture': capture()}}

    provider = ChatCompletionsGrounder(api_server.profile)
    store = GroundingHandoffStore(tmp_path, owner_id='api-host')
    jobs = AgentCommandJobs(Coordinator(), store, capture,
        RecognitionSourceConfig(source='external_api', api_profile='fixture.json'), api_grounder=provider)

    def start(command_id):
        command = InstantCommand.model_validate({'kind': 'step', 'operation': 'execute_recognition_plan',
            'request': {'goal': 'Search', 'enable_post_click_verification': False}}).command()
        return dispatch_agent_command(jobs, command_id, command, {'handle': 10, 'process_id': 20})

    yield SimpleNamespace(jobs=jobs, start=start, store=store, clicks=clicks, frames=frames, image=image)
    api_server.release.set()
    assert jobs.close(timeout=5)
    provider.close()


def terminal(jobs, command_id):
    deadline = monotonic() + 6
    while monotonic() < deadline:
        state = jobs.get(command_id)
        if state['status'] in {'completed', 'failed', 'cancelled'}:
            return state
        sleep(.01)
    pytest.fail(f'command did not finish: {state["status"]}')


def test_http_to_common_action_route_and_fresh_second_operation(flow, api_server):
    for name in ('first', 'second'):
        flow.start(name)
        state = terminal(flow.jobs, name)
        assert state['status'] == 'completed', state.get('error') or state.get('result')
        assert state['action_executed'] is True
        plan = state['result']['response']['data']['result']['recognition_plan']
        assert plan['grounding_evidence']['source'] == 'external_api'
        candidate = plan['candidate_result']['candidates'][0]
        assert candidate['capture_id'] == state['recognition_calls'][0]['capture_id']
        assert candidate['source'] == 'api_visual'
        assert candidate['viewport_size'] == {'width': 200, 'height': 150}
        assert candidate['click_point'] == {'x': 65, 'y': 55}
        assert candidate['freshness']['status'] == 'revalidated'
        assert plan['narrow_search_result']['results'][0]['coordinate_source'] == 'api_visual'
        assert state['recognition_calls'][0]['provider']['returned_model'] == 'loopback-fixture'
        call = state['recognition_calls'][0]
        assert call['source'] == 'external_api'
        assert call['attempt'] == call['provider']['attempt']
        assert call['attempt']['status'] == 'success'
        assert call['attempt']['usage'] is None
        with Image.open(state['observation']['capture']['image_path']) as after:
            assert after.getpixel((170, 110)) == (0, 128, 0)
    assert flow.clicks == [(65, 55), (65, 55)]
    first, second = api_server.requests
    assert first['context']['capture_id'] != second['context']['capture_id']
    assert first['png'] != second['png']
    assert all(flow.store.get(row['context']['request_id'])['phase'] == 'completed'
        for row in api_server.requests)
    assert 'local-test-key' not in json.dumps(state)


def test_learning_observation_uses_action_capture_before_dispatch(flow, monkeypatch):
    from app.learning_memory import learning_observation_capture
    observed = {}

    def capture(coordinator, handle, pid, *, image_path, recipe):
        observed.update(handle=handle, pid=pid, image_path=image_path, recipe=recipe)
        frame = {"capture_id": "learn-current-frame", "image_path": image_path,
            "sha256": sha256(Path(image_path).read_bytes()).hexdigest(),
            "image_size": {"width": 200, "height": 150},
            "window_identity": {"handle": handle, "process_id": pid, "process_create_time": 30.0},
            "application": {"executable_name": "editor.exe"}}
        snapshot = {"provider": "windows_uia", "status": "ok", "scan_complete": True,
            "truncated": False, "capture_id": frame["capture_id"],
            "window_identity": frame["window_identity"], "controls": []}
        return frame, {"uia": {"status": "ok", "capture_id": frame["capture_id"],
            "window_identity": frame["window_identity"], "snapshot": snapshot}}

    monkeypatch.setattr(learning_observation_capture, "capture_memory_observation", capture)
    flow.jobs.coordinator.learning_context = {"event_id": "learn-event", "command_sha256": "a" * 64}
    flow.start('learning-observation')
    state = terminal(flow.jobs, 'learning-observation')
    assert state['status'] == 'completed', state.get('error')
    action = state['result']['response']['data']['result']
    observation = action['learning_observation']
    assert observation['contract_version'] == 'learning_target_observation.v1'
    assert observation['event_id'] == 'learn-event'
    assert observation['command_sha256'] == 'a' * 64
    assert 'candidate' in observation, observation.get('reason')
    assert observation['candidate'] == {'capture_id': 'learn-current-frame',
        'viewport_size': {'width': 200, 'height': 150}, 'source': 'api_visual',
        'bbox': {'x': 30, 'y': 40, 'w': 71, 'h': 31},
        'click_point': {'x': 65, 'y': 55}, 'freshness': 'current_capture'}
    assert Path(observed['image_path']).resolve() == flow.frames[2].resolve()
    assert observed['image_path'] != action['live_capture']['image_path']
    assert observed['image_path'] != flow.frames[0].as_posix()
    assert observed['recipe'] == {'scope': {'anchors': [{'kind': 'uia'}]}, 'strategies': []}
    assert any(step['name'] == 'learning_target_observation'
        for step in action['timings']['steps'])


@pytest.mark.parametrize('status,mode,code', [(401, 'found', 'api_authentication_failed'),
    (429, 'found', 'api_rate_limited'), (200, 'malformed', 'api_grounding_invalid'),
    (200, 'absent', 'request_absent')])
def test_api_failure_stops_before_input_and_next_command_can_recover(flow, api_server, status, mode, code):
    api_server.status, api_server.mode = status, mode
    flow.start('failure')
    state = terminal(flow.jobs, 'failure')
    assert state['status'] == 'failed'
    assert state['error']['code'] == code
    assert state['action_executed'] is False and flow.clicks == []
    assert len(api_server.requests) == 1
    assert len(state['recognition_calls']) == 1
    call = state['recognition_calls'][0]
    assert call['source'] == 'external_api'
    assert call['request_id'] == api_server.requests[0]['context']['request_id']
    assert call['attempt']['status'] == ('success' if code == 'request_absent' else 'failure')
    if code == 'request_absent':
        assert call['attempt'] == call['provider']['attempt']
    else:
        assert call['attempt']['usage'] is None
    api_server.status, api_server.mode = 200, 'found'
    flow.start('recovery')
    assert terminal(flow.jobs, 'recovery')['status'] == 'completed'
    assert len(flow.clicks) == 1


def test_cancel_during_http_never_dispatches_and_explicit_new_command_recovers(flow, api_server):
    api_server.release.clear()
    flow.start('cancelled')
    assert api_server.entered.wait(3)
    flow.jobs.cancel('cancelled')
    api_server.release.set()
    state = terminal(flow.jobs, 'cancelled')
    assert state['status'] == 'cancelled' and state['action_executed'] is False
    assert flow.clicks == []
    flow.start('after-cancel')
    assert terminal(flow.jobs, 'after-cancel')['status'] == 'completed'
    assert len(flow.clicks) == 1


def test_api_compact_receipt_preserves_provider_and_request_state(flow):
    from app.instant_receipt import compact_receipt
    flow.start('compact')
    state = terminal(flow.jobs, 'compact')
    receipt = compact_receipt({'request_id': 'status-1', 'result': state})
    assert receipt['agent_command']['recognition_calls'][0]['provider']['requested_model'] == 'loopback-fixture'
    assert receipt['agent_command']['recognition_calls'][0]['attempt']['status'] == 'success'
    assert receipt['agent_command']['api_request']['phase'] == 'grounding_ready'


def test_api_attempt_survives_store_resolve_failure_once(flow, api_server, monkeypatch):
    def fail_resolve(*_args, **_kwargs):
        raise ValueError('resolve_failed')
    monkeypatch.setattr(flow.store, 'resolve', fail_resolve)
    flow.start('resolve-failure')
    state = terminal(flow.jobs, 'resolve-failure')
    assert state['status'] == 'failed'
    assert state['error']['code'] == 'resolve_failed'
    assert len(api_server.requests) == 1
    assert len(state['recognition_calls']) == 1
    call = state['recognition_calls'][0]
    assert call['source'] == 'external_api'
    assert call['attempt'] == call['provider']['attempt']
    assert call['attempt']['status'] == 'success'
    persisted = json.loads(Path(flow.jobs._path('resolve-failure')).read_text(encoding='utf-8'))
    assert persisted['recognition_calls'] == state['recognition_calls']


def test_api_timeout_attempt_is_persisted(flow, api_server):
    api_server.release.clear()
    flow.jobs.api_grounder.close()
    flow.jobs.api_grounder = ChatCompletionsGrounder(
        api_server.profile.model_copy(update={'timeout_seconds': 0.05}))
    flow.start('timeout')
    assert api_server.entered.wait(3)
    state = terminal(flow.jobs, 'timeout')
    assert state['status'] == 'failed'
    assert state['error']['code'] == 'api_timeout'
    assert len(state['recognition_calls']) == 1
    call = state['recognition_calls'][0]
    assert call['source'] == 'external_api'
    assert call['attempt']['status'] == 'timeout'
    assert call['attempt']['usage'] is None


@pytest.mark.parametrize('http_status', [200, 429])
def test_real_http_attempt_projects_into_run_metrics_once(flow, api_server, http_status):
    from app.core.json_snapshot import write_json_snapshot
    from app.learning_memory.workflow_metrics import load_run_metrics
    from app.learning_memory.measurement import load_events
    api_server.status = http_status
    initial = flow.start('measured-command')
    state = terminal(flow.jobs, 'measured-command')
    session = Path(flow.store.session_root)
    command = flow.jobs._jobs['measured-command'].command
    for folder in ('commands', 'responses'):
        (session / folder).mkdir(exist_ok=True)
    write_json_snapshot(session / 'commands/measured-command.json', command)
    write_json_snapshot(session / 'responses/measured-command.json',
                        {'status': 'returned', 'command': command, 'result': initial})
    trial = {'run_id': 'measured-run', 'history': [], 'pending': {
        'step_id': 'measured-step', 'execution_request_id': 'measured-command', 'suggested_command': command}}
    for _ in range(2):
        metrics = load_run_metrics(session, trial['run_id'], trial=trial)
        assert metrics['observed']['model_calls']['grounding'] == 1
        assert metrics['observed']['status_counts'] == {'success' if http_status == 200 else 'failure': 1}
        assert metrics['total_model_calls'] is None and metrics['total_usage'] is None
    assert len(api_server.requests) == 1
    events = load_events(session, trial['run_id'])
    assert len(events) == 1
    assert events[0]['request_id'] == api_server.requests[0]['context']['request_id']
    assert events[0]['started_ns'] == state['recognition_calls'][0]['attempt']['started_ns']
    if http_status == 429:
        assert flow.clicks == [] and state['action_executed'] is False


def test_cancel_after_api_claim_before_dispatch_finishes_claim_without_input(flow, monkeypatch):
    original = flow.jobs._resolve_api
    def cancel_after_claim(job, pending):
        original(job, pending)
        flow.jobs.cancel(job.command_id)
    monkeypatch.setattr(flow.jobs, '_resolve_api', cancel_after_claim)
    flow.start('claimed-cancel')
    state = terminal(flow.jobs, 'claimed-cancel')
    assert state['status'] == 'cancelled' and flow.clicks == []
    saved = flow.store.get(state['recognition_calls'][0]['request_id'])
    assert saved['phase'] == 'completed' and saved['input_attempted'] is False
