"""真实 owner、动作路由和判断服务联调；仅桌面与 HTTP 传输使用替身。"""
from copy import deepcopy
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from app.execution.local_direct_step import _post_action as REAL_POST_ACTION
from tests.test_local_step_timings import timed_scene


@pytest.fixture
def popup_route(timed_scene, tmp_path, monkeypatch):
    from app.api import action
    from app.api.models.response import APIResponse
    from app.core import local_text_focus
    from app.core.local_input_policy import _local_operator_input_scope
    from app.execution import local_direct_step as direct
    from app.execution.popup_decision import POPUP_CONTINUE_CONDITION, PopupContinuationGuard
    from tests.test_adaptive_decision_policy import service
    from tests.test_local_recognition_policy import plan_fixture

    coordinator = timed_scene[0]
    image_path = tmp_path / 'popup-frame.png'
    Image.new('RGB', (1000, 690), 'white').save(image_path)
    identity = {'contract_version': 'windows_native_identity_observation_v1', 'provider': 'windows_native_identity',
        'status': 'observed', 'target_window_handle': 321, 'process_id': 12, 'process_create_time': 123.5,
        'executable_path': 'c:\\fixture\\editor.exe'}
    bound = SimpleNamespace(handle=321, process_id=12, title='Fresh synthetic browser', process_name='editor.exe',
        rect=SimpleNamespace(left=100, top=200, right=1100, bottom=890))
    state = SimpleNamespace(popup=322, explicit=False, clicks=[], captures=[], probes=0, clients=[])
    manager = SimpleNamespace(bind_window_by_handle=lambda handle: bound, get_bound_window=lambda: bound,
        get_owned_foreground_popup_handle=lambda current: state.popup,
        read_owned_foreground_popup=lambda current: ({'handle': state.popup, 'parent_handle': 321,
            'process_id': 12, 'parent_enabled': True, 'rect': [300, 300, 700, 500]} if state.popup else None),
        validate_bound_point_visibility=lambda **kwargs:
            {'allowed': True, 'hit_window': {'root_handle': 321}})
    reader = SimpleNamespace(read_identity=lambda handle: deepcopy(identity))
    coordinator._windows = lambda: manager
    monkeypatch.setattr(direct, 'WindowsNativeIdentityReader', lambda **kwargs: reader)
    monkeypatch.setattr(direct, '_local_operator_input_scope', _local_operator_input_scope)
    monkeypatch.setattr(direct, '_post_action', REAL_POST_ACTION)
    monkeypatch.setattr(action, 'window_manager', manager)

    def capture(**kwargs):
        state.captures.append(kwargs.get('purpose'))
        return {'image_path': str(image_path), 'window_size': {'width': 1000, 'height': 690},
            'image_width': 1000, 'image_height': 690, 'roi': None}

    monkeypatch.setattr(direct, 'ScreenshotService', lambda **kwargs: SimpleNamespace(capture_window=capture))
    monkeypatch.setattr(action.screenshot_service, 'capture_window', capture)
    monkeypatch.setattr(action, 'prepare_browser_content', lambda *args: None)
    monkeypatch.setattr(action, '_render_recognition_plan_overlay_for_execution', lambda plan: None)
    monkeypatch.setattr(action, 'write_trace', lambda **kwargs: str(tmp_path / 'trace.json'))
    monkeypatch.setattr(action, '_rewrite_execute_trace_result', lambda **kwargs: None)
    monkeypatch.setattr(action, '_capture_pre_action_state_with_foreground_retry', lambda **kwargs: ({}, 0))

    def recognize(request):
        plan = plan_fixture(str(image_path))
        box = {'x': 160, 'y': 40, 'w': 480, 'h': 32}
        candidate = plan['candidate_result']['candidates'][0]
        candidate['element']['bbox'] = box
        plan['recommended_target'] = deepcopy(candidate)
        plan['narrow_search_result']['results'][0]['refined_click_point'] = {'x': 184, 'y': 56}
        if state.explicit:
            plan['parse_result']['screen_reading'] = {'source_layers': {'windows_uia': {
                'scan_scope': 'menu_subtree', 'scan_complete': True, 'owned_popup_handle': 322,
                'controls': [{'control_type': 'MenuItem', 'visible': True, 'enabled': True, 'bbox': box}]}}}
        return APIResponse(success=True, message='synthetic current target', data={'result': plan})

    monkeypatch.setattr(action, '_run_recognition_plan_for_execution', recognize)

    def probe(*args, **kwargs):
        state.probes += 1
        return {'control_type': 'Edit', 'runtime_id': [42, 1]}

    monkeypatch.setattr(local_text_focus, 'probe_local_focus_target', probe)

    def click(x, y, **kwargs):
        guard = kwargs.get('popup_continuation_guard')
        if guard is not None:
            assert type(guard) is PopupContinuationGuard
            guard.validate_command(bound=bound, point=(x, y), bbox=kwargs['target_bbox'],
                popup_handle=state.popup, click_count=1)
            guard.verify_current()
        validator = kwargs.get('pre_input_validator')
        if validator is not None:
            validator()
        state.clicks.append((x, y, kwargs))
        return {'clicked': True, 'window_point': {'x': x, 'y': y}}

    monkeypatch.setattr(action.input_controller, 'click_point', click)

    def run(*, popup=True, outcome='continue', explicit=False, combined=False):
        from app.execution.action_review import CANDIDATE_CONDITION
        state.popup = 322 if popup else None
        state.explicit = explicit
        runtime, requests, client = service(tmp_path, monkeypatch,
            review=0.97 if outcome == 'review_required' else 0.01,
            profile={'auto_conditions': [CANDIDATE_CONDITION if combined else POPUP_CONTINUE_CONDITION]})
        state.clients.append((runtime, client))
        coordinator._decision_service = None if outcome == 'unavailable' else runtime
        target = None if explicit else local_text_focus.LocalTextFocusTarget(321, 12)
        receipt = coordinator.execute_local_step(target_window_handle=321, target_process_id=12,
            operation='execute_recognition_plan', focus_target=target, execution_request_id='popup-route-1',
            **({'action_review': {'schema': 'action_review_context.v1', 'run_id': 'popup-run',
                'attempt_id': 'attempt-1', 'step_id': 'focus', 'budget_ms': 5000,
                'plan': {'schema_version': 'task_plan.v2', 'title': 'Search Java documentation', 'inputs': {},
                    'steps': [{'step_id': 'focus', 'action': {'kind': 'click', 'goal': 'Focus the address bar'},
                        'verification': {'kind': 'agent_judgment'}}]}}} if combined else {}),
            request={'goal': 'Select the explicit menu item' if explicit else 'Focus the address bar',
                'enable_post_click_verification': False, 'max_execution_attempts': 1,
                'auto_observe_learning_artifacts': False,
                'write_policy': {'path_graph': False, 'element_memory': False, 'trace': False}})
        return receipt, requests, runtime

    yield SimpleNamespace(run=run, state=state)
    for runtime, client in state.clients:
        runtime.close()
        client.close()


def test_popup_continue_reaches_original_click_with_real_guard(popup_route):
    from app.core.receipt_action import _receipt_action
    from app.execution.popup_decision import POPUP_CONTINUE_CONDITION
    receipt, requests, runtime = popup_route.run()
    assert receipt['phase'] == 'returned' and _receipt_action(receipt, 'execute_recognition_plan') is True, receipt['response']
    assert len(requests) == 1 and len(popup_route.state.clicks) == 1
    x, y, options = popup_route.state.clicks[0]
    assert (x, y) == (184, 56) and options['target_bbox'] == (160, 40, 480, 32)
    assert options.get('popup_continuation_guard') is not None
    assert POPUP_CONTINUE_CONDITION in json.dumps(json.loads(requests[0].content))
    assert receipt['popup_decision_judgment']['adopted'] is True
    assert receipt['response']['data']['result']['popup_decision_judgment']['freshness_revalidated'] is True
    assert popup_route.state.probes == 2
    assert popup_route.state.captures.count('popup-decision-current') == 2
    with pytest.raises(ValueError, match='scope_unavailable'):
        options['popup_continuation_guard'].verify_current()


@pytest.mark.parametrize('outcome,calls,reason', [('review_required', 1, 'popup_decision_review_required'),
    ('unavailable', 0, 'popup_decision_unavailable')])
def test_popup_main_routes_strict_zero_input(popup_route, outcome, calls, reason):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    receipt, requests, runtime = popup_route.run(outcome=outcome)
    assert receipt['phase'] == 'not_dispatched' and receipt['action_executed'] is False
    assert popup_route.state.clicks == [] and len(requests) == calls
    assert receipt['response']['error']['code'] == reason
    assert recognition_plan_rejected_before_dispatch(receipt['response']) is True
    assert receipt['popup_decision_judgment']['adopted'] is False
    assert receipt['automatic_retry_allowed'] is False


@pytest.mark.parametrize('popup,explicit', [(False, False), (True, True)])
def test_no_popup_or_explicit_popup_target_adds_no_ignore_decision(popup_route, popup, explicit):
    receipt, requests, runtime = popup_route.run(popup=popup, explicit=explicit)
    assert receipt['phase'] == 'returned' and len(popup_route.state.clicks) == 1
    assert requests == [] and 'popup-decision-current' not in popup_route.state.captures
    options = popup_route.state.clicks[0][2]
    assert options.get('popup_continuation_guard') is None
    if explicit:
        assert options['expected_owned_popup_handle'] == 322


@pytest.mark.parametrize('outcome,allowed', [('continue', True), ('review_required', False)])
def test_combined_candidate_review_reuses_exact_popup_guard(popup_route, outcome, allowed):
    receipt, requests, runtime = popup_route.run(combined=True, outcome=outcome)
    assert len(requests) == 1
    if allowed:
        assert receipt['response']['success'], receipt['response'].get('error')
    assert len(popup_route.state.clicks) == int(allowed), receipt['response']
    if allowed:
        assert receipt['response']['data']['result']['popup_decision_judgment']['additional_requests'] == 0
        assert receipt['action_assessment']['scope'] == 'candidate'
    else:
        assert receipt['phase'] == 'not_dispatched' and receipt['action_executed'] is False
