"""仅输入层明确首次按下前拒绝，才能贯通零派发回执和终态释放。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from tests.test_local_step_timings import timed_scene
from tests.test_recognition_dispatch_boundary import owner, sequence
from tests.test_nonmodal_popup_parent_click import scene as native_popup_scene


@pytest.fixture
def visibility_route(tmp_path, monkeypatch):
    from PIL import Image
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.api.models.response import APIResponse
    from app.core.local_input_policy import _local_operator_input_scope
    from app.core import local_text_focus
    from tests.test_local_recognition_policy import plan_fixture

    identity = {'contract_version': 'windows_native_identity_observation_v1', 'provider': 'windows_native_identity',
        'status': 'observed', 'target_window_handle': 321, 'process_id': 12, 'process_create_time': 123.5,
        'executable_path': 'c:\\fixture\\editor.exe'}
    bound = SimpleNamespace(handle=321, process_id=12, title='Fresh synthetic editor', process_name='editor.exe',
        rect=SimpleNamespace(left=100, top=200, right=1100, bottom=890))
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    image_path = tmp_path / 'capture.png'
    Image.new('RGB', (1000, 690), 'white').save(image_path)
    monkeypatch.setattr(action, 'window_manager', manager)
    monkeypatch.setattr(action.screenshot_service, 'capture_window', lambda **kw:
        {'image_path': str(image_path), 'window_size': {'width': 1000, 'height': 690}, 'roi': None})
    monkeypatch.setattr(action, 'prepare_browser_content', lambda *args: None)
    monkeypatch.setattr(action, '_run_recognition_plan_for_execution', lambda request:
        APIResponse(success=True, message='synthetic evidence', data={'result': deepcopy(plan_fixture(str(image_path)))}))
    monkeypatch.setattr(action, '_render_recognition_plan_overlay_for_execution', lambda plan: None)
    monkeypatch.setattr(action, 'write_trace', lambda **kw: str(tmp_path / 'trace.json'))
    monkeypatch.setattr(action, '_rewrite_execute_trace_result', lambda **kw: None)
    monkeypatch.setattr(action, '_capture_pre_action_state_with_foreground_retry', lambda **kw: ({}, 0))
    events = []

    def run(*, flag=False, click_sequence=None, region=False, after_confirmed=False, malformed=False,
            decision_phase=None, decision_reason='popup_decision_review_required', native_error=None):
        events.clear()
        point = {'contract_version': 'bound_point_visibility_v1', 'window_point': {'x': 184, 'y': 516},
            'allowed': not not region, 'reason': 'target_point_visible' if region else 'target_point_not_owned_by_foreground_popup'}
        evidence = ({'allowed': False, 'reason': 'target_region_occluded', 'point_visibility': point,
            'region_visibility': {'allowed': False, 'reason': 'target_region_occluded'}} if region else point)
        if malformed:
            evidence['allowed'] = True
        def decision_reject():
            from app.execution.decision_check import DecisionCheckRejected
            raise DecisionCheckRejected(decision_reason, {'status': 'review_required', 'verdict': 'uncertain',
                'reason': 'popup_requires_main', 'adopted': False, 'authorizes_action': False,
                'automatic_retry_allowed': False})
        def probe(*args, **kwargs):
            if decision_phase == 'before':
                events.append('decision_before')
                decision_reject()
            return {'control_type': 'Edit', 'runtime_id': [42, 1]}
        monkeypatch.setattr(local_text_focus, 'probe_local_focus_target', probe)
        def reject():
            if native_error is not None:
                error = action.TargetPointOccludedError(deepcopy(native_error.evidence),
                    button_down_attempted=native_error.button_down_attempted)
                if hasattr(native_error, 'click_sequence'):
                    error.click_sequence = deepcopy(native_error.click_sequence)
                raise error
            error = action.TargetPointOccludedError(deepcopy(evidence))
            # 模拟输入层内部证明；旧异常没有该字段时必须保持未知。
            if flag != 'missing':
                error.button_down_attempted = flag
            if click_sequence is not None:
                error.click_sequence = deepcopy(click_sequence)
            raise error
        def click(*args, **kwargs):
            events.append('click_point')
            if after_confirmed:
                return {'clicked': True}
            if decision_phase == 'click':
                decision_reject()
            reject()
        def verify(*args, **kwargs):
            events.append('verify_after_confirmed')
            if decision_phase == 'confirmed':
                decision_reject()
            reject()
        monkeypatch.setattr(action.input_controller, 'click_point', click)
        monkeypatch.setattr(action.verifier, 'verify_action', verify)
        request = ExecuteRecognitionPlanRequest(goal='Focus the fresh field', max_execution_attempts=1,
            enable_post_click_verification=after_confirmed, auto_observe_learning_artifacts=False,
            write_policy={'path_graph': False, 'element_memory': False, 'trace': False})
        with _local_operator_input_scope(manager=manager,
                identity_reader=SimpleNamespace(read_identity=lambda handle: deepcopy(identity)), identity=identity,
                window_rect=(100, 200, 1100, 890), enabled=lambda: True), local_text_focus.local_text_focus_scope(
                    local_text_focus.LocalTextFocusTarget(321, 12)):
            return action.execute_recognition_plan(request).model_dump()
    return SimpleNamespace(run=run, events=events)


@pytest.mark.parametrize('region', [False, True])
def test_explicit_before_first_down_visibility_rejection_is_strict_zero(visibility_route, region):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    response = visibility_route.run(region=region)
    data = response['data']
    assert response['success'] is False and data.get('execution_path', {}).get('action_executed', 'missing') is False, response
    assert data.get('dispatch_status') == 'not_dispatched' and data.get('dispatch_stage') == 'point_visibility'
    assert data['input_started'] is False and data['attempts'] == []
    assert data['point_visibility_no_dispatch'] == {'contract_version': 'point_visibility_no_dispatch.v1',
        'stage': 'before_first_mouse_down', 'button_down_attempted': False, 'reason_code': response['error']['code']}
    assert data['agent_step_result']['action_executed'] is False
    assert recognition_plan_rejected_before_dispatch(response) is True
    assert visibility_route.events == ['click_point']


@pytest.mark.parametrize('failure', ['visibility', 'decision', 'native_popup'])
def test_real_zero_producer_owner_sequence_and_terminal_preserve_no_dispatch(
        visibility_route, timed_scene, monkeypatch, tmp_path, failure, native_rejection):
    from tests.test_session_input_terminal import save, inspect
    response = visibility_route.run(decision_phase='before' if failure == 'decision' else None,
        native_error=native_rejection('parent_initial') if failure == 'native_popup' else None)
    local = owner(timed_scene, monkeypatch, response)
    assert local['phase'] == 'not_dispatched' and local['action_executed'] is False
    result = sequence(timed_scene, monkeypatch, response)
    assert result['status'] == 'interrupted' and result['action_executed'] is False
    assert result['steps'][0]['status'] == 'not_dispatched' and result['completed_steps'] == []
    root = tmp_path / 'terminal'
    command = {'kind': 'input_sequence', 'request': {'field_goal': 'Focus the fresh field',
        'text': 'fresh synthetic text', 'submit_search': False}}
    save(root, 'commands', 'original', command)
    save(root, 'responses', 'original', {'status': 'returned', 'command': command, 'result': result})
    checked = inspect(root)['commands']['original']
    assert checked['action_executed'] is False and checked['terminal_status'] == 'interrupted'


@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('failure', ['visibility', 'decision', 'native_popup'])
def test_real_zero_sequence_releases_runner_failure_or_cancel_and_owned_close(
        visibility_route, timed_scene, monkeypatch, tmp_path, cancel, failure, native_rejection):
    from app.core.json_snapshot import write_json_snapshot
    from tests.test_task_plan_contract import plan
    from tests.test_task_plan_runner import scene
    result = sequence(timed_scene, monkeypatch,
        visibility_route.run(decision_phase='before' if failure == 'decision' else None,
            native_error=native_rejection('parent_initial') if failure == 'native_popup' else None))
    source = plan(verification={'kind': 'agent_judgment'})
    source['schema_version'] = 'task_plan.v2'
    source['steps'][0]['action'] = {'kind': 'input_sequence', 'field_goal': 'Focus the fresh field',
        'text': 'fresh synthetic text', 'clear_existing': True, 'submit_search': False}
    def forbidden(*args, **kwargs):
        pytest.fail('已知零输入失败不得请求 Decision')
    root = tmp_path / 'queue'
    root.mkdir()
    s = scene(root, monkeypatch, source=source, decision=SimpleNamespace(evaluate=forbidden))
    pending = s.runtime.backend.status(s.run_id)['pending']
    path = root / 'responses' / (pending['execution_request_id'] + '.json')
    write_json_snapshot(path, {'status': 'returned', 'command': deepcopy(pending['suggested_command']), 'result': result})
    before = path.read_bytes()
    if cancel:
        s.runtime.control({'action': 'cancel', 'run_id': s.run_id}, 'cancel-original')
    final = s.runtime.tick(force=True)
    assert final['status'] == ('cancelled' if cancel else 'failed') and final['pending'] is None
    assert final['history'][0]['original_input_status'] == 'failed' and final['history'][0]['action_executed'] is False
    s.runtime.admit('owned-close', {'kind': 'close_launched_window', 'request': {}})
    assert len(list(root.glob('commands/*.json'))) == 1 and path.read_bytes() == before


@pytest.mark.parametrize('flag', ['missing', None, True, 0, 'false'])
def test_absent_or_non_false_input_layer_marker_stays_unknown(visibility_route, timed_scene, monkeypatch, flag):
    response = visibility_route.run(flag=flag)
    local = owner(timed_scene, monkeypatch, response)
    assert response['data']['execution_path']['action_executed'] is None
    assert local['phase'] == 'result_unknown' and local.get('action_executed') is not False


@pytest.mark.parametrize('reason', ['popup_decision_review_required', 'popup_decision_unavailable',
    'popup_decision_stale', 'decision_check_rejected'])
def test_local_before_input_decision_rejection_has_strict_zero_proof(visibility_route, reason):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    response = visibility_route.run(decision_phase='before', decision_reason=reason)
    data = response['data']
    assert recognition_plan_rejected_before_dispatch(response) is True
    assert data['dispatch_stage'] == 'decision_check' and data['input_started'] is False
    assert data['decision_check_no_dispatch'] == {'contract_version': 'decision_check_no_dispatch.v1',
        'stage': 'before_click_point', 'click_dispatch_started': False, 'reason_code': reason}
    assert visibility_route.events == ['decision_before']


@pytest.mark.parametrize('phase', ['click', 'confirmed'])
def test_decision_exception_after_dispatch_entry_is_never_zero(visibility_route, phase):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    response = visibility_route.run(decision_phase=phase, after_confirmed=phase == 'confirmed')
    assert response['data']['execution_path']['action_executed'] is (True if phase == 'confirmed' else None)
    assert recognition_plan_rejected_before_dispatch(response) is False


@pytest.mark.parametrize('damage', ['proof', 'phase', 'reason', 'judgment', 'status', 'verdict', 'retry', 'point'])
def test_tampered_decision_zero_proof_is_not_accepted(visibility_route, damage):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    response = visibility_route.run(decision_phase='before')
    data = response['data']
    if damage == 'proof':
        data.pop('decision_check_no_dispatch', None)
    elif damage == 'phase':
        data.setdefault('decision_check_no_dispatch', {})['click_dispatch_started'] = 0
    elif damage == 'reason':
        data.setdefault('decision_check_no_dispatch', {})['reason_code'] = 'other'
    elif damage == 'judgment':
        data.pop('decision_judgment', None)
    elif damage in {'status', 'verdict'}:
        data['decision_judgment'][damage] = 'other'
    elif damage == 'retry':
        data['automatic_retry_allowed'] = True
    else:
        data['selected_click_point']['x'] += 1
    assert recognition_plan_rejected_before_dispatch(response) is False


@pytest.mark.parametrize('conflict', ['sequence_started', 'sequence_completed', 'confirmed', 'allowed'])
def test_partial_or_confirmed_input_and_conflicting_visibility_never_claim_zero(visibility_route, conflict):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    sequence = {'requested_click_count': 2, 'completed_clicks': 0, 'input_attempted': True, 'button': 'left'}
    if conflict == 'sequence_completed':
        sequence['completed_clicks'] = 1
    response = visibility_route.run(click_sequence=sequence if conflict.startswith('sequence') else None,
        after_confirmed=conflict == 'confirmed', malformed=conflict == 'allowed')
    expected = True if conflict in {'sequence_completed', 'confirmed'} else None
    assert response['data']['execution_path']['action_executed'] is expected
    assert response['data']['agent_step_result']['action_executed'] is expected
    assert recognition_plan_rejected_before_dispatch(response) is False


@pytest.mark.parametrize('damage', ['proof', 'proof_zero', 'stage', 'reason', 'allowed', 'point', 'error',
    'input', 'execution', 'step', 'attempt', 'fallback'])
def test_incomplete_or_tampered_visibility_proof_is_not_zero(visibility_route, timed_scene, monkeypatch, damage):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    response = visibility_route.run()
    data = response['data']
    if damage == 'proof':
        data.pop('point_visibility_no_dispatch', None)
    elif damage == 'proof_zero':
        data.setdefault('point_visibility_no_dispatch', {})['button_down_attempted'] = 0
    elif damage == 'stage':
        data['dispatch_stage'] = 'after_input'
    elif damage == 'reason':
        data.setdefault('point_visibility_no_dispatch', {})['reason_code'] = 'other'
    elif damage == 'allowed':
        response['error']['details']['allowed'] = True
    elif damage == 'point':
        data['selected_click_point']['x'] += 1
    elif damage == 'error':
        response['error']['code'] = 'unrelated'
    elif damage == 'input':
        data['input_started'] = True
    elif damage == 'execution':
        data['execution_path']['action_executed'] = True
    elif damage == 'step':
        data['agent_step_result']['action_executed'] = True
    elif damage == 'attempt':
        data['attempts'] = [{'click_result': {'clicked': True}}]
    else:
        data.setdefault('fallback_plan', {})['attempt_count'] = 1
    assert recognition_plan_rejected_before_dispatch(response) is False
    local = owner(timed_scene, monkeypatch, response)
    assert local['phase'] == 'result_unknown' and local.get('action_executed') is not False


@pytest.fixture
def native_rejection(native_popup_scene, monkeypatch):
    from app.core import input_controller as inputs
    from app.core.window_manager import WindowRect
    from app.execution.popup_decision import PopupContinuationGuard, _ISSUER

    controller, manager, bound, state = native_popup_scene
    bound.handle, bound.process_id, bound.rect = 321, 12, WindowRect(100, 200, 1100, 890)
    state.owner, state.hit = 321, 321
    monkeypatch.setattr(inputs.win32gui, 'GetAncestor', lambda h, flag: 321 if flag == 3 and h == 200 else h)
    monkeypatch.setattr(manager, '_get_process_id', lambda h: 12)
    monkeypatch.setattr(controller, '_resolve_window_and_screen_point', lambda **kw:
        {'window_x': 184, 'window_y': 516, 'screen_x': 284, 'screen_y': 716})
    monkeypatch.setattr(inputs.win32api, 'GetCursorPos', lambda: (284, 716))

    def reject(kind):
        state.events.clear()
        state.enabled = True
        overlap = kind == 'parent_initial'
        monkeypatch.setattr(inputs.win32gui, 'GetWindowRect', lambda h:
            ((330, 729, 500, 850) if overlap else (500, 800, 700, 880))
            if h == 200 else (100, 200, 1100, 890))
        calls = []
        def verify():
            calls.append(1)
            if kind == 'guard_final' or (kind == 'second_guard' and len(calls) == 2):
                raise ValueError('guard_changed')
            if kind == 'parent_final':
                state.enabled = False
        click_count = 2 if kind == 'second_guard' else 1
        approved = PopupContinuationGuard(_ISSUER,
            scope={'active': kind != 'guard_command'}, bound=bound, point=(184, 516),
            bbox=(150, 500, 100, 30), popup_handle=200, click_count=click_count, verify=verify)
        with pytest.raises(inputs.TargetPointOccludedError) as caught:
            controller.click_point(184, 516, hold_ms=0, target_bbox=(150, 500, 100, 30),
                click_count=click_count, popup_continuation_guard=approved)
        assert state.events == (['down', 'up'] if kind == 'second_guard' else [])
        return caught.value
    return reject


@pytest.mark.parametrize('kind', ['parent_initial', 'guard_command', 'parent_final', 'guard_final'])
def test_native_pre_down_rejection_produces_bound_zero_receipt(native_rejection, visibility_route, kind):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    error = native_rejection(kind)
    response = visibility_route.run(native_error=error)
    assert response['data']['execution_path']['action_executed'] is False, response
    assert recognition_plan_rejected_before_dispatch(response) is True
    proof = response['error']['details']['input_dispatch_boundary']
    assert proof == {'contract_version': 'click_input_boundary.v1', 'stage': 'before_first_mouse_down',
        'button_down_attempted': False, 'window_point': {'x': 184, 'y': 516},
        'screen_point': {'x': 284, 'y': 716}, 'bound_window': {'handle': 321, 'process_id': 12,
            'rect': [100, 200, 1100, 890]}, 'button': 'left', 'requested_click_count': 1,
        'reason_code': error.evidence['reason']}


def test_native_second_click_refusal_and_old_unbound_receipt_remain_nonzero_or_unknown(
        native_rejection, visibility_route):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    error = native_rejection('second_guard')
    assert error.button_down_attempted is True and 'input_dispatch_boundary' not in error.evidence
    response = visibility_route.run(native_error=error)
    assert response['data']['execution_path']['action_executed'] is True
    assert recognition_plan_rejected_before_dispatch(response) is False
    old = native_rejection('parent_initial')
    old.evidence.pop('input_dispatch_boundary', None)
    response = visibility_route.run(native_error=old)
    assert response['data']['execution_path']['action_executed'] is None
    assert recognition_plan_rejected_before_dispatch(response) is False


@pytest.mark.parametrize('damage', ['stage', 'zero', 'point', 'screen', 'window', 'rect', 'reason',
    'count', 'button', 'extra', 'window_valid', 'pid_valid', 'count_valid', 'button_valid', 'request_missing'])
def test_native_zero_boundary_tampering_is_not_accepted(native_rejection, visibility_route, damage):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    error = native_rejection('parent_initial')
    response = visibility_route.run(native_error=error)
    assert recognition_plan_rejected_before_dispatch(response) is True
    proof = response['error']['details']['input_dispatch_boundary']
    if damage == 'stage':
        proof['stage'] = 'after_mouse_down'
    elif damage == 'zero':
        proof['button_down_attempted'] = 0
    elif damage == 'point':
        proof['window_point']['x'] += 1
    elif damage == 'screen':
        proof['screen_point']['y'] += 1
    elif damage == 'window':
        proof['bound_window']['handle'] = True
    elif damage == 'rect':
        proof['bound_window']['rect'][2] = 100
    elif damage == 'reason':
        proof['reason_code'] = 'other'
    elif damage == 'count':
        proof['requested_click_count'] = True
    elif damage == 'button':
        proof['button'] = 'other'
    elif damage == 'window_valid':
        proof['bound_window']['handle'] += 1
    elif damage == 'pid_valid':
        proof['bound_window']['process_id'] += 1
    elif damage == 'count_valid':
        proof['requested_click_count'] = 2
    elif damage == 'button_valid':
        proof['button'] = 'right'
    elif damage == 'request_missing':
        response['data'].pop('input_dispatch_request')
    else:
        proof['trusted'] = True
    assert recognition_plan_rejected_before_dispatch(response) is False


@pytest.mark.parametrize('damage', ['window', 'pid', 'count', 'button'])
def test_native_zero_sequence_cannot_override_mismatched_dispatch_binding(
        native_rejection, visibility_route, damage):
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    error = native_rejection('guard_final')
    proof = error.evidence['input_dispatch_boundary']
    if damage in {'window', 'pid'}:
        proof['bound_window']['handle' if damage == 'window' else 'process_id'] += 1
    elif damage == 'count':
        proof['requested_click_count'] = 2
    else:
        proof['button'] = 'right'
    response = visibility_route.run(native_error=error)
    assert response['data']['execution_path']['action_executed'] is None
    assert recognition_plan_rejected_before_dispatch(response) is False
