"""同次生产采图只承接报告前图，不共享跨步骤截图或跳过派发安全检查。"""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import time

import pytest

from app.execution import local_direct_step as direct
from app.execution.local_action_contract import _validated_request
from tests.test_settled_observation_scope import observation_route, _scope, _local_scope
from tests.test_local_step_timings import timed_scene
from app.api.action import _run_recognition_plan_for_execution as _REAL_AGENT_PLAN
from tests.test_grounding_identity_wiring import case as identity_case


@pytest.fixture
def sharing_route(observation_route, monkeypatch, tmp_path):
    scene = observation_route
    original = scene.action.screenshot_service.capture_window

    def capture(**kwargs):
        result = original(**kwargs)
        return {**result, 'window_rect': [0, 0, 1000, 690],
                'capture_visibility': {'contract_version': 'bound_capture_visibility_v2', 'allowed': True,
                    'coordinate_space': 'window', 'bound_window_handle': 321, 'occluded_regions': [], 'masked': False}}

    monkeypatch.setattr(scene.action.screenshot_service, 'capture_window', capture)
    from PIL import Image
    from app.core.agent_grounding_target import AgentGroundingTarget, current_agent_grounding
    source = tmp_path / 'delegated-source.png'
    Image.new('RGB', (1000, 690), 'white').save(source)
    scene.target_state = {'phase': 'executing', 'request_id': 'offline-grounding', 'goal': 'Fixture target',
        'expires_at': time.time() + 180, 'configuration': {'source': 'external_api'},
        'capture': {'capture_id': 'source-capture', 'image_path': str(source),
            'sha256': sha256(source.read_bytes()).hexdigest(), 'image_size': {'width': 1000, 'height': 690},
            'window_identity': {'handle': 321, 'process_id': 12, 'process_create_time': 123.5}},
        'result': {'schema_version': 'grounding.v1', 'request_id': 'offline-grounding',
            'capture_id': 'source-capture', 'coordinate_space': 'capture_image_pixels',
            'image_size': {'width': 1000, 'height': 690}, 'status': 'found',
            'selected_candidate_id': 'current', 'candidates': [{'id': 'current', 'label': 'Fixture target',
                'bbox': {'x': 160, 'y': 492, 'width': 48, 'height': 48},
                'click_point': {'x': 184, 'y': 516}, 'evidence_source': 'api_visual'}]}}
    scene.make_target = lambda: AgentGroundingTarget(scene.target_state)
    scene.request = {'goal': 'Fixture target', 'metadata': {}}
    scene.run_without_target = scene.run
    scene.run = lambda request_updates=None, **options: scene.run_without_target(
        request_updates, grounding_target=scene.make_target(), **options)
    model_boundary = scene.action._run_recognition_plan_for_execution

    def plan(request):
        # 委派目标走正式适配器；无内部目标时，模型调用边界仍沿用离线替身。
        return (_REAL_AGENT_PLAN(request) if current_agent_grounding() is not None else model_boundary(request))

    monkeypatch.setattr(scene.action, '_run_recognition_plan_for_execution', plan)
    return scene


def test_default_metadata_uses_formal_resolver_for_real_internal_target(sharing_route):
    from app.core.agent_grounding_target import agent_grounding_scope
    from app.core.settled_observation_scope import before_capture_sharing_eligible
    from app.api.models.request import ExecuteRecognitionPlanRequest
    request = _validated_request('execute_recognition_plan', sharing_route.request)
    assert request['metadata'] == {}
    _, effective = sharing_route.action._execute_plan_request_defaults(ExecuteRecognitionPlanRequest.model_validate(request))
    assert effective['execution_grounding'] == 'direct_visual'
    with agent_grounding_scope(sharing_route.make_target()):
        assert before_capture_sharing_eligible(request, shared_observation=True)


def test_default_delegated_request_real_post_action_captures_once_without_public_switch(sharing_route):
    scene = sharing_route
    receipt = scene.run()
    assert receipt['response']['success'] is True, receipt['response']
    assert receipt['request']['metadata'] == {}
    assert scene.state.events.count('local-direct-no-learning') == 0
    assert scene.state.events.count('recognition_plan_execution') == 1
    assert scene.state.events.count('agent-grounding-dispatch-check') == 1
    assert scene.state.events.count('dispatch') == 1
    assert receipt['before_capture_status'] == 'captured'


def test_real_issued_visual_submit_target_shares_default_request_without_reissuing_proof(identity_case):
    from app.core.agent_grounding_target import agent_grounding_scope
    from app.core.local_keyboard_target import issue_visual_keyboard_target
    from app.core.visual_submit_target import VisualSubmitTarget
    from app.core.settled_observation_scope import before_capture_sharing_eligible
    from tests.test_grounding_identity_wiring import candidate_review, compound_receipt, value_proof
    candidate_review(identity_case)
    compound_receipt(identity_case)
    proof = value_proof(identity_case, compound=True)
    target = VisualSubmitTarget(issue_visual_keyboard_target(proof, 'press_key', submit_search=True),
        action_review=identity_case.context)
    request = _validated_request('execute_recognition_plan', {'goal': target.goal})
    assert request['metadata'] == {}
    calls = len(identity_case.provider.calls)
    with agent_grounding_scope(target):
        assert before_capture_sharing_eligible(request, shared_observation=True)
    assert not target.input_claimed and len(identity_case.provider.calls) == calls


@pytest.mark.parametrize('source', ['approved_plan_id', 'learned_instruction_id', 'interface_memory_id',
    'interface_memory_action_id', 'learning_mode', 'image_path', 'observe_trace_path'])
def test_public_direct_visual_flag_cannot_override_formal_source_route(sharing_route, source):
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.core.agent_grounding_target import agent_grounding_scope
    from app.core.settled_observation_scope import before_capture_sharing_eligible
    request = ExecuteRecognitionPlanRequest.model_validate({**sharing_route.request,
        source: 'prior-source', 'metadata': {'execution_grounding': 'direct_visual'}}).model_dump()
    with agent_grounding_scope(sharing_route.make_target()):
        assert not before_capture_sharing_eligible(request, shared_observation=True)


def test_public_direct_visual_flag_without_internal_target_keeps_outer_capture(sharing_route):
    scene = sharing_route
    receipt = scene.run_without_target({'metadata': {'execution_grounding': 'direct_visual'}})
    assert receipt['response']['success'] is True
    assert scene.state.events.count('local-direct-no-learning') == 1
    assert 'before_capture_status' not in receipt


def test_same_inner_capture_is_copied_and_persisted_before_dispatch(sharing_route, monkeypatch):
    scene = sharing_route
    original = scene.action.input_controller.click_point

    def click(*args, **kwargs):
        reports = list(scene.co._runtime_output_root.glob('local-direct-steps/*/report.json'))
        saved = json.loads(reports[-1].read_text(encoding='utf-8'))
        assert saved['before_capture_status'] == 'captured'
        assert saved['capture']['frame_id'] == 'before_input'
        assert Path(saved['capture']['image_path']).exists()
        scene.state.events.append('before_persist_verified')
        return original(*args, **kwargs)

    monkeypatch.setattr(scene.action.input_controller, 'click_point', click)
    receipt = scene.run(scene.request)
    assert receipt['response']['success'] is True, receipt['response']
    events = scene.state.events
    assert events.count('local-direct-no-learning') == 0
    assert events.count('recognition_plan_execution') == 1
    assert events.count('local-direct-post-action') == events.count('dispatch') == 1
    assert events.index('before_persist_verified') < events.index('dispatch')
    source = receipt['response']['data']['result']['live_capture']['image_path']
    copied = Path(receipt['capture']['image_path'])
    assert copied != Path(source) and copied.parent.name == 'captures'
    assert copied.read_bytes() == Path(source).read_bytes()
    assert receipt['capture']['sha256'] == sha256(copied.read_bytes()).hexdigest()
    assert receipt['capture']['image_path'] != receipt['observation']['capture']['image_path']
    assert copied not in scene.captures


def test_inner_capture_failure_is_unavailable_without_fabricated_zero_input_proof(sharing_route, monkeypatch):
    scene = sharing_route
    from app.core.local_step_no_dispatch import pre_capture_failure_verified

    def failed(**kwargs):
        raise OSError('synthetic route capture failure')

    monkeypatch.setattr(scene.action.screenshot_service, 'capture_window', failed)
    receipt = scene.run(scene.request)
    assert receipt.get('capture') is None
    assert receipt['before_capture_status'] == 'unavailable'
    assert receipt['response']['success'] is False
    assert receipt['effect_verified'] is False
    assert not pre_capture_failure_verified(receipt)
    assert 'dispatch' not in scene.state.events
    assert 'local-direct-no-learning' not in scene.state.events


def test_copied_before_remains_independent_of_the_shared_source_file(sharing_route):
    receipt = sharing_route.run(sharing_route.request)
    copied = Path(receipt['capture']['image_path'])
    original = copied.read_bytes()
    source = Path(receipt['capture']['source_image_path'])
    source.write_bytes(b'synthetic later source replacement')
    assert copied.read_bytes() == original
    assert sha256(original).hexdigest() == receipt['capture']['sha256']


def test_before_report_persistence_failure_prevents_input(sharing_route, monkeypatch):
    scene = sharing_route
    original = direct._write_report
    failed = []

    def write(output, report):
        if not failed and report.get('before_capture_status') == 'captured':
            failed.append(True)
            raise OSError('synthetic persistence failure')
        return original(output, report)

    monkeypatch.setattr(direct, '_write_report', write)
    receipt = scene.run(scene.request)
    assert failed == [True]
    assert receipt['response']['success'] is False
    assert receipt['effect_verified'] is False and 'dispatch' not in scene.state.events


def test_shared_before_still_validates_coordinates_before_copying(sharing_route, tmp_path):
    scene = sharing_route
    capture = scene.action.screenshot_service.capture_window(purpose='coordinate-fixture')
    identity = direct.WindowsNativeIdentityReader(window_manager=scene.manager).read_identity(321)
    output = tmp_path / 'should-not-exist'
    with pytest.raises(ValueError, match='outside the current screenshot'):
        direct._copy_before_capture(capture, output, {'x': 1000, 'y': 20}, identity, (0, 0, 1000, 690))
    assert not output.exists()


@pytest.mark.parametrize('field,value', [('allowed', False), ('coordinate_space', 'screen')])
def test_copy_rejects_unapproved_or_wrong_space_visibility(sharing_route, tmp_path, field, value):
    scene = sharing_route
    capture = scene.action.screenshot_service.capture_window(purpose='visibility-fixture')
    capture['capture_visibility'][field] = value
    identity = direct.WindowsNativeIdentityReader(window_manager=scene.manager).read_identity(321)
    with pytest.raises(ValueError, match='before_capture window binding invalid'):
        direct._copy_before_capture(capture, tmp_path / 'invalid', {}, identity, (0, 0, 1000, 690))


def test_real_screenshot_return_shape_publishes_and_copies_partial_masked_png(sharing_route, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    from app.core import screenshot
    scene = sharing_route
    visibility = {'contract_version': 'bound_capture_visibility_v2', 'allowed': True,
        'reason': 'capture_window_partially_occluded', 'bound_window_handle': 321,
        'occluded_regions': [{'x': 900, 'y': 0, 'width': 100, 'height': 60}]}
    monkeypatch.setattr(scene.manager, 'validate_bound_capture_visibility',
        lambda **kwargs: deepcopy(visibility), raising=False)

    class Backend:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def grab(self, monitor):
            assert monitor == {'left': 0, 'top': 0, 'width': 1000, 'height': 690}
            return SimpleNamespace(size=(1000, 690), bgra=b'\xff\xff\xff\x00' * (1000 * 690))

    monkeypatch.setattr(screenshot, 'MSS_BACKEND_AVAILABLE', True)
    monkeypatch.setattr(screenshot, 'mss', Backend)
    captured = screenshot.ScreenshotService(window_manager=scene.manager,
        capture_dir=tmp_path / 'actual-service').capture_window(focus_window=False)
    identity = direct.WindowsNativeIdentityReader(window_manager=scene.manager).read_identity(321)
    received = []

    def copy(capture):
        received.append(direct._copy_before_capture(capture, tmp_path / 'step', {}, identity, (0, 0, 1000, 690)))

    with _local_scope(scene), _scope(scene,
            request=_validated_request('execute_recognition_plan', scene.request), before_capture=copy):
        assert _publish(scene, captured)
    copied = received[0]
    assert copied['roi'] is None and copied['window_rect'] == [0, 0, 1000, 690]
    assert copied['capture_visibility'] == captured['capture_visibility']
    assert copied['capture_visibility']['masked'] is True
    assert Path(copied['image_path']).read_bytes() == Path(captured['image_path']).read_bytes()
    with Image.open(copied['image_path']) as image:
        assert image.getpixel((950, 20)) == (32, 32, 32)
        assert image.getpixel((25, 20)) == (255, 255, 255)


def test_candidate_rejection_still_has_the_real_persisted_before(sharing_route, monkeypatch):
    from app.api.models.response import APIResponse, ErrorModel
    scene = sharing_route
    monkeypatch.setattr(scene.action, '_run_recognition_plan_for_execution', lambda request:
        APIResponse(success=False, message='candidate rejected', error=ErrorModel(code='no_candidate')))
    receipt = scene.run(scene.request)
    assert receipt['before_capture_status'] == 'captured'
    assert Path(receipt['capture']['image_path']).exists()
    assert receipt['response']['success'] is False
    assert 'dispatch' not in scene.state.events


def test_cancel_during_capture_stops_before_publish_or_input(sharing_route, monkeypatch):
    scene = sharing_route
    original = scene.action.screenshot_service.capture_window

    def cancelled(**kwargs):
        value = original(**kwargs)
        scene.co._cancel_wait.set()
        return value

    monkeypatch.setattr(scene.action.screenshot_service, 'capture_window', cancelled)
    receipt = scene.run(scene.request)
    assert receipt['response']['success'] is False
    assert receipt['before_capture_status'] == 'unavailable'
    assert receipt['effect_verified'] is False and 'dispatch' not in scene.state.events


def test_forged_success_json_cannot_replace_missing_internal_publish(sharing_route, monkeypatch):
    scene = sharing_route
    monkeypatch.setattr(direct, '_post_action', lambda *_: {'success': True, 'data': {'result': {
        'live_capture': {'image_path': 'fake.png'}, 'execution_path': {'action_executed': True}}}})
    with pytest.raises(ValueError, match='before_capture'):
        scene.run(scene.request)
    saved = json.loads(next(scene.co._runtime_output_root.glob('local-direct-steps/*/report.json')).read_text(encoding='utf-8'))
    assert saved['phase'] == 'result_unknown'
    assert saved.get('capture') is None and saved['before_capture_status'] == 'unavailable'
    assert saved['effect_verified'] is False and saved['automatic_retry_allowed'] is False


@pytest.mark.parametrize('mode', ['without_target', 'no_observation', 'dry_run', 'learning'])
def test_ineligible_routes_keep_the_original_outer_capture(sharing_route, mode):
    scene = sharing_route
    if mode == 'without_target':
        receipt = scene.run_without_target()
    elif mode == 'no_observation':
        receipt = scene.co.execute_local_step(target_window_handle=321, target_process_id=12,
            operation='execute_recognition_plan', request=scene.request, include_observation=False)
    elif mode == 'dry_run':
        receipt = scene.run({**scene.request, 'dry_run': True})
    else:
        # 学习上下文是独立证据链；直接测试资格函数，不虚构学习回执。
        from app.core.settled_observation_scope import before_capture_sharing_eligible
        request = _validated_request('execute_recognition_plan', scene.request)
        assert not before_capture_sharing_eligible(request, shared_observation=False)
        return
    assert receipt['capture']['image_path']
    assert scene.state.events.count('local-direct-no-learning') == 1


def _publish(scene, capture, **changes):
    from app.core.settled_observation_scope import publish_before_capture
    values = dict(manager=scene.manager, request=_validated_request('execute_recognition_plan', scene.request),
        caller=scene.action.execute_recognition_plan, verifier=scene.action.verifier, capture=capture)
    values.update(changes)
    return publish_before_capture(**values)


@pytest.mark.parametrize('fault', ['request', 'caller', 'verifier', 'window', 'identity', 'thread'])
def test_publish_requires_same_scope_request_thread_and_window(sharing_route, fault):
    scene = sharing_route
    received = []
    request = _validated_request('execute_recognition_plan', scene.request)
    with _local_scope(scene), _scope(scene, request=request, before_capture=received.append):
        if fault == 'window':
            scene.manager.get_bound_window().rect.right += 1
        elif fault == 'identity':
            from app.core.local_input_policy import _LOCAL_INPUT_POLICY
            _LOCAL_INPUT_POLICY.get()['identity']['process_create_time'] += 1
        changes = ({'request': {**request, 'goal': 'other'}} if fault == 'request' else
            {'caller': lambda: None} if fault == 'caller' else
            {'verifier': object()} if fault == 'verifier' else {})
        if fault == 'thread':
            context = copy_context()
            with ThreadPoolExecutor(max_workers=1) as pool:
                with pytest.raises(PermissionError):
                    pool.submit(context.run, _publish, scene, {}, **changes).result()
        else:
            with pytest.raises(PermissionError):
                _publish(scene, {}, **changes)
    assert received == []


def test_publish_is_single_use_and_revoked_after_scope(sharing_route):
    scene = sharing_route
    received = []
    capture = {'image_path': 'only forwarded to an internal callback'}
    request = _validated_request('execute_recognition_plan', scene.request)
    with _local_scope(scene):
        with _scope(scene, request=request, before_capture=received.append):
            assert _publish(scene, capture)
            assert received == [capture] and received[0] is not capture
            with pytest.raises(PermissionError):
                _publish(scene, capture)
            copied = copy_context()
        assert copied.run(_publish, scene, capture) is False
