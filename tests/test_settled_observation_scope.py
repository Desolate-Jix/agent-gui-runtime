"""同一步只采一张正式后图；所有桌面、输入与模型边界均为离线替身。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from app.execution import local_direct_step as direct
from tests.test_local_step_timings import timed_scene


_REAL_POST_ACTION = direct._post_action


@pytest.fixture
def observation_route(timed_scene, monkeypatch, tmp_path):
    from app.api import action
    from app.api.models.response import APIResponse
    from app.core import verifier
    from app.core.local_input_policy import _local_operator_input_scope
    from tests.test_local_recognition_policy import plan_fixture

    co, state, clock, _ = timed_scene
    manager = co._windows()
    bound = manager.bind_window_by_handle(321)
    bound.title, bound.process_name, bound.is_active = 'Fixture', 'editor.exe', True
    bound.rect.right, bound.rect.bottom = 1000, 690
    manager.get_bound_window = lambda: bound
    state.dispatched = False
    captures = []

    def capture(root, **kwargs):
        purpose = kwargs['purpose']
        state.events.append(purpose)
        path = root / (str(len(captures)) + '.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (1000, 690), 'black' if state.dispatched else 'white').save(path)
        captures.append(path)
        return {'image_path': str(path), 'image_width': 1000, 'image_height': 690,
            'window_size': {'width': 1000, 'height': 690}, 'roi': None}

    class Capture:
        def __init__(self, **kwargs):
            self.root = kwargs['capture_dir']

        def capture_window(self, **kwargs):
            return capture(self.root, **kwargs)

    monkeypatch.setattr(direct, 'ScreenshotService', Capture)
    monkeypatch.setattr(direct, '_post_action', _REAL_POST_ACTION)
    monkeypatch.setattr(direct, '_local_operator_input_scope', _local_operator_input_scope)
    monkeypatch.setattr(action, 'window_manager', manager)
    monkeypatch.setattr(verifier, 'window_manager', manager)
    monkeypatch.setattr(action.screenshot_service, 'capture_window',
        lambda **kwargs: capture(tmp_path / 'route-captures', **kwargs))
    monkeypatch.setattr(action, 'prepare_browser_content', lambda *args: None)
    def plan(request):
        value = plan_fixture(request.image_path)
        value['grounding_evidence'] = {'source': 'external_api', 'evidence_source': 'api_visual'}
        value['candidate_result']['candidates'][0]['source'] = 'api_visual'
        return APIResponse(success=True, message='synthetic model', data={'result': value})

    monkeypatch.setattr(action, '_run_recognition_plan_for_execution', plan)
    monkeypatch.setattr(action, '_render_recognition_plan_overlay_for_execution', lambda plan: None)
    monkeypatch.setattr(action, 'write_trace', lambda **kwargs: str(tmp_path / 'trace.json'))
    monkeypatch.setattr(action, '_rewrite_execute_trace_result', lambda **kwargs: None)

    def click(x, y, **kwargs):
        state.events.append('dispatch')
        state.dispatched = True
        return {'clicked': True, 'window_handle': 321, 'window_point': {'x': x, 'y': y}}

    monkeypatch.setattr(action.input_controller, 'click_point', click)

    def diff(self, **kwargs):
        state.events.append('diagnostic_diff')
        return {'available': True, 'changed': True}

    monkeypatch.setattr(verifier.Verifier, '_compare_images', diff)

    def diagnostic_wait(seconds):
        state.events.append('diagnostic_wait')
        clock.advance(seconds * 1000)

    def settled_wait(seconds):
        state.events.append('settled_wait')
        clock.advance(seconds * 1000)
        return False

    monkeypatch.setattr(verifier.time, 'sleep', diagnostic_wait)
    monkeypatch.setattr(co._cancel_wait, 'wait', settled_wait)

    def run(request_updates=None, **options):
        return co.execute_local_step(target_window_handle=321, target_process_id=12,
            operation='execute_recognition_plan', request={'goal': 'Fixture target', **(request_updates or {})},
            include_observation=True, **options)

    return SimpleNamespace(co=co, state=state, run=run, captures=captures, manager=manager,
        action=action, verifier=verifier)


@pytest.mark.parametrize('wait_ms', [0, 2000])
def test_local_generic_diagnostic_uses_one_new_settled_after(observation_route, wait_ms):
    scene = observation_route
    receipt = scene.run(observation_wait_ms=wait_ms)
    assert receipt['response']['success'] is True, receipt['response']
    assert receipt['phase'] == 'returned'
    events = scene.state.events
    assert events.count('dispatch') == 1
    assert events.count('settled_wait') == (1 if wait_ms else 0)
    assert 'diagnostic_wait' not in events
    assert 'post_action' not in events and 'diagnostic_diff' not in events
    assert events.count('pre_action') == events.count('local-direct-post-action') == 1
    assert events.index('pre_action') < events.index('dispatch') < events.index('local-direct-post-action')
    if wait_ms:
        assert events.index('dispatch') < events.index('settled_wait') < events.index('local-direct-post-action')
    after, before = receipt['observation']['capture'], receipt['capture']
    assert after['image_path'] != before['image_path']
    assert after['sha256'] == sha256(Path(after['image_path']).read_bytes()).hexdigest()
    assert after['sha256'] != before['sha256']
    assert after['frame_id'] == 'after_settled'
    assert receipt['observation']['render_grace_ms'] == wait_ms
    assert receipt['observation']['authorizes_action'] is False
    assert receipt['effect_verified'] is False and receipt['automatic_retry_allowed'] is False
    diagnostic = receipt['response']['data']['result']['post_click_verification']
    assert diagnostic['verified'] is None
    assert diagnostic['diagnostic_status'] == 'deferred_to_settled_observation'
    assert diagnostic['observation_ref']['step_id'] == receipt['step_id']
    assert diagnostic['observation_ref']['field'] == 'observation.capture'
    assert not diagnostic.get('after', {}).get('image_path')


def test_final_after_capture_failure_never_reports_effect_success_or_retries(observation_route, monkeypatch):
    scene = observation_route

    def fail(*args, **kwargs):
        raise ValueError('synthetic after unavailable')

    monkeypatch.setattr(direct, '_capture_observation', fail)
    receipt = scene.run()
    assert receipt['response']['success'] is True
    assert receipt['response']['data']['result']['execution_path']['action_executed'] is True
    assert receipt['phase'] == 'returned_observation_unavailable'
    assert receipt['observation']['status'] == 'unavailable'
    assert receipt['effect_verified'] is False and receipt['automatic_retry_allowed'] is False
    assert scene.state.events.count('dispatch') == 1
    assert 'post_action' not in scene.state.events


def test_without_outer_observation_original_diagnostic_is_retained(observation_route):
    scene = observation_route
    receipt = scene.co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='execute_recognition_plan', request={'goal': 'Fixture target'}, include_observation=False)
    assert receipt['response']['success'] is True
    assert scene.state.events.count('diagnostic_wait') == 1
    assert scene.state.events.count('post_action') == scene.state.events.count('diagnostic_diff') == 1
    assert 'local-direct-post-action' not in scene.state.events


def _scope(scene, **changes):
    from app.core.settled_observation_scope import _settled_observation_scope
    from app.execution.local_action_contract import _validated_request
    identity = direct.WindowsNativeIdentityReader(window_manager=scene.manager).read_identity(321)
    options = dict(owner=scene.co, manager=scene.manager, identity=identity,
        window_rect=(0, 0, 1000, 690), step_id='local-step-fixture',
        request=_validated_request('execute_recognition_plan', {'goal': 'Fixture target'}),
        caller=scene.action.execute_recognition_plan, verifier=scene.action.verifier)
    options.update(changes)
    return _settled_observation_scope(**options)


def _claim(scene, **changes):
    from app.core.settled_observation_scope import claim_settled_observation
    from app.execution.local_action_contract import _validated_request
    values = dict(manager=scene.manager,
        request=_validated_request('execute_recognition_plan', {'goal': 'Fixture target'}),
        caller=scene.action.execute_recognition_plan, verifier=scene.action.verifier)
    values.update(changes)
    return claim_settled_observation(**values)


def _local_scope(scene):
    from app.core.local_input_policy import _local_operator_input_scope
    reader = direct.WindowsNativeIdentityReader(window_manager=scene.manager)
    return _local_operator_input_scope(manager=scene.manager, identity_reader=reader,
        identity=reader.read_identity(321), window_rect=(0, 0, 1000, 690), enabled=lambda: True)


def test_scope_claim_is_single_use_and_bound_to_caller_request_and_verifier(observation_route):
    scene = observation_route
    with _local_scope(scene), _scope(scene):
        assert _claim(scene, caller=lambda: None) is None
        assert _claim(scene, request={'goal': 'other target'}) is None
        assert _claim(scene, verifier=scene.verifier.Verifier()) is None
        permit = _claim(scene)
        assert permit is not None
        assert _claim(scene) is None
        result = scene.action.verifier.verify_action('execute_recognition_plan',
            judged_by_agent=True, before_state={'window_handle': 321}, click_result={'clicked': True},
            _settled_observation_permit=permit)
        assert result['verified'] is None and 'diagnostic_wait' not in scene.state.events
        with pytest.raises(PermissionError):
            scene.action.verifier.verify_action('execute_recognition_plan', judged_by_agent=True,
                _settled_observation_permit=permit)


def test_scope_is_revoked_on_exception_and_cannot_escape_in_copied_context(observation_route):
    from contextvars import copy_context
    scene = observation_route
    copied = None
    with _local_scope(scene):
        with pytest.raises(RuntimeError, match='synthetic interruption'):
            with _scope(scene):
                copied = copy_context()
                raise RuntimeError('synthetic interruption')
        assert _claim(scene) is None
        assert copied.run(_claim, scene) is None
        with _scope(scene):
            assert _claim(scene) is not None


def test_scope_rejects_nested_thread_and_window_reuse(observation_route):
    from contextvars import copy_context
    from concurrent.futures import ThreadPoolExecutor
    scene = observation_route
    with _local_scope(scene), _scope(scene):
        with pytest.raises(PermissionError):
            with _scope(scene):
                pass
        copied = copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(copied.run, _claim, scene).result() is None
        bound = scene.manager.get_bound_window()
        bound.rect.right += 1
        assert _claim(scene) is None
        bound.rect.right -= 1
        assert _claim(scene) is not None


def test_request_metadata_cannot_create_a_deferred_diagnostic(observation_route):
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.execution.local_action_contract import _validated_request
    scene = observation_route
    request = _validated_request('execute_recognition_plan', {'goal': 'Fixture target',
        'metadata': {'settled_observation_scope': True, 'skip_post_verification': True}})
    with _local_scope(scene):
        result = scene.action.execute_recognition_plan(ExecuteRecognitionPlanRequest.model_validate(request))
    assert result.success is True
    assert 'diagnostic_wait' in scene.state.events and 'post_action' in scene.state.events
    assert result.data['result']['post_click_verification'].get('diagnostic_status') is None


def test_scope_rejects_same_hwnd_pid_with_different_process_creation(observation_route):
    scene = observation_route
    identity = direct.WindowsNativeIdentityReader(window_manager=scene.manager).read_identity(321)
    identity['process_create_time'] += 1
    with _local_scope(scene), _scope(scene, identity=identity):
        assert _claim(scene) is None


@pytest.mark.parametrize('policy', [
    {'navigation': {'required': False}},
    {'expected_semantic_rule': 'search_results_list_becomes_visible'},
])
def test_special_verification_policy_keeps_original_diagnostic(observation_route, policy):
    scene = observation_route
    receipt = scene.run(request_updates={'metadata': {'verification_policy': policy}})
    assert receipt['response']['success'] is True
    assert scene.state.events.count('diagnostic_wait') == 1
    assert scene.state.events.count('post_action') == scene.state.events.count('diagnostic_diff') == 1
    assert receipt['response']['data']['result']['post_click_verification'].get('diagnostic_status') is None


def test_condition_observation_keeps_original_diagnostic(observation_route, monkeypatch):
    scene = observation_route
    monkeypatch.setattr(direct, 'UIATextConditionProbe', lambda *args: lambda: {})
    monkeypatch.setattr(direct, 'observe_until_condition',
        lambda probe, capture, baseline, **kwargs: (capture(), {'status': 'matched'}))
    receipt = scene.run(observation_condition={'text': 'Fixture ready', 'control_type': 'Text'})
    assert receipt['response']['success'] is True
    assert scene.state.events.count('diagnostic_wait') == 1
    assert scene.state.events.count('post_action') == 1
    assert receipt['observation']['capture']['observation_stage'] == 'after_condition_wait'


def test_semantic_verification_keeps_original_generic_and_semantic_checks(observation_route, monkeypatch):
    scene = observation_route
    monkeypatch.setattr(scene.action, 'should_verify_mouse_tester_semantics', lambda **kwargs: True)

    def semantic(**kwargs):
        scene.state.events.append('semantic_verification')
        assert kwargs['generic_verification']['after']['image_path']
        return {'applicable': True, 'verified': True}

    monkeypatch.setattr(scene.action, 'verify_mouse_tester_post_click_semantics', semantic)
    receipt = scene.run()
    assert receipt['response']['success'] is True
    assert scene.state.events.count('diagnostic_wait') == scene.state.events.count('semantic_verification') == 1
    assert receipt['response']['data']['result']['semantic_post_click_verification']['applicable'] is True


def test_learning_capture_keeps_original_diagnostic_and_learning_evidence(observation_route, monkeypatch):
    scene = observation_route

    def learning(**kwargs):
        scene.state.events.append('learning_capture')
        return {'event_id': 'fixture-learning', 'status': 'observed'}

    monkeypatch.setattr(scene.action, 'observe_learning_target', learning)
    receipt = scene.run(learning_context={'event_id': 'fixture-learning', 'command_sha256': 'fixture-command'})
    assert receipt['response']['success'] is True
    assert scene.state.events.count('diagnostic_wait') == scene.state.events.count('learning_capture') == 1
    assert receipt['response']['data']['result']['learning_observation']['event_id'] == 'fixture-learning'


@pytest.mark.parametrize('visual', [False, True])
def test_native_focus_target_keeps_diagnostic_while_visual_focus_can_share_after(
        observation_route, monkeypatch, visual):
    from app.core import local_text_focus
    scene = observation_route
    monkeypatch.setattr(local_text_focus, 'probe_local_focus_target', lambda *args, **kwargs: {
        'window_handle': 321, 'process_id': 12, 'process_create_time': 123.5,
        'window_rect': [0, 0, 1000, 690], 'runtime_id': [42, 1],
        'control_type': 'Edit', 'bbox': [160, 492, 48, 48]})
    target_type = local_text_focus.VisualTextFocusTarget if visual else local_text_focus.LocalTextFocusTarget
    receipt = scene.run(focus_target=target_type(321, 12))
    assert receipt['response']['success'] is True, receipt['response']
    assert scene.state.events.count('dispatch') == 1
    assert scene.state.events.count('diagnostic_wait') == (0 if visual else 1)
    assert receipt['observation']['capture']['frame_id'] == 'after_settled'


def test_cancelled_final_wait_keeps_dispatch_fact_without_a_substitute_after(observation_route, monkeypatch):
    scene = observation_route
    monkeypatch.setattr(scene.co._cancel_wait, 'wait', lambda seconds: True)
    receipt = scene.run()
    assert receipt['phase'] == 'returned_observation_unavailable'
    assert receipt['response']['data']['result']['execution_path']['action_executed'] is True
    assert receipt['effect_verified'] is False and receipt['observation']['status'] == 'unavailable'
    assert scene.state.events.count('dispatch') == 1
    assert 'post_action' not in scene.state.events and 'local-direct-post-action' not in scene.state.events
    assert receipt['automatic_retry_allowed'] is False


def test_two_local_steps_never_reuse_the_first_step_capability_or_after(observation_route):
    scene = observation_route
    first, second = scene.run(), scene.run()
    assert scene.state.events.count('dispatch') == scene.state.events.count('settled_wait') == 2
    assert 'diagnostic_wait' not in scene.state.events
    assert first['step_id'] != second['step_id']
    assert first['observation']['capture']['image_path'] != second['observation']['capture']['image_path']
    for receipt in (first, second):
        reference = receipt['response']['data']['result']['post_click_verification']['observation_ref']
        assert reference['step_id'] == receipt['step_id']


def test_forged_or_expired_permit_cannot_defer_a_verifier(observation_route):
    scene = observation_route
    with pytest.raises(PermissionError):
        scene.action.verifier.verify_action('execute_recognition_plan', judged_by_agent=True,
            _settled_observation_permit={'step_id': 'local-step-forged'})
    with _local_scope(scene):
        with _scope(scene):
            permit = _claim(scene)
        with pytest.raises(PermissionError):
            scene.action.verifier.verify_action('execute_recognition_plan', judged_by_agent=True,
                before_state={'window_handle': 321}, click_result={'clicked': True},
                _settled_observation_permit=permit)
    assert 'post_action' not in scene.state.events and 'dispatch' not in scene.state.events


@pytest.mark.parametrize('secondary', ['condition_met', 'condition_not_met'])
def test_primary_and_ordinary_review_finish_before_any_deferred_diagnostic(
        observation_route, monkeypatch, tmp_path, secondary):
    from tests.test_decision_choice import runtime, choice_reply
    from app.execution.action_review import CANDIDATE_CONDITION
    scene = observation_route
    service, calls, client = runtime(tmp_path, monkeypatch, body=choice_reply('condition_not_met'),
        profile={'ordinary_review': 'on_reject', 'request_cap': 8,
            'auto_conditions': [CANDIDATE_CONDITION]})
    original = service._provider.judge

    def judge(payload):
        scene.state.events.append('primary_review')
        return original(payload)

    def review(payload):
        scene.state.events.append('ordinary_review')
        return {'request_sha256': payload['request_sha256'], 'review_result': {
            'type': 'choice', 'name': 'current_step', 'choice': secondary},
            'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2},
            'http_elapsed_ms': 1, 'server_processing_ms': None, 'provider_request_id': 'offline-secondary'}

    monkeypatch.setattr(service._provider, 'judge', judge)
    monkeypatch.setattr(service._provider, 'review', review)
    scene.co._decision_service = service
    context = {'schema': 'action_review_context.v1', 'run_id': 'fixture-run', 'step_id': 'open',
        'attempt_id': 'fixture-attempt', 'budget_ms': 30000, 'plan': {'schema_version': 'task_plan.v2',
        'title': 'Fixture task', 'inputs': {}, 'steps': [{'step_id': 'open',
            'action': {'kind': 'click', 'goal': 'Fixture target', 'click_kind': 'single'},
            'verification': {'kind': 'agent_judgment'}}]}}
    try:
        receipt = scene.run(action_review=context)
        assert len(calls) == 1
        assert scene.state.events.count('primary_review') == scene.state.events.count('ordinary_review') == 1
        assert scene.state.events.index('primary_review') < scene.state.events.index('ordinary_review')
        if secondary == 'condition_met':
            assert receipt['response']['success'] is True, receipt['response']
            assert scene.state.events.index('ordinary_review') < scene.state.events.index('dispatch')
            assert scene.state.events.count('dispatch') == 1
            assert 'diagnostic_wait' not in scene.state.events
        else:
            assert receipt['response']['success'] is False
            assert receipt['phase'] == 'not_dispatched'
            assert 'dispatch' not in scene.state.events
    finally:
        service.close()
        client.close()
