"""同一已认证字段可新审点击后提交；旧点击许可不能重复使用。"""
from copy import deepcopy
from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from app.core.visual_submit_target import VisualSubmitTarget, prepare_visual_submit, perform_visual_submit
from app.core.agent_grounding_target import agent_grounding_scope
from app.core.local_keyboard_target import issue_visual_keyboard_target
from app.execution.action_review import action_review_scope, CANDIDATE_CONDITION
from app.execution.action_review_dispatch import review_original_action
from tests.test_visual_field_proof import scene, assess, executed_focus, controller_scene, FIELD, TEXT, NATIVE, capture


@pytest.fixture
def submission(scene, monkeypatch):
    s = scene
    s.context['native_field_evidence'] = False
    s.service.profile = s.service.profile.model_copy(update={'auto_conditions':(
        *s.service.profile.auto_conditions, CANDIDATE_CONDITION)})
    executed_focus(s.focus)
    proof = assess(s, phase='value')
    keyboard = issue_visual_keyboard_target(proof, 'press_key', submit_search=True)
    context = {'schema':'action_review_context.v1','run_id':'run','attempt_id':'attempt','step_id':'field',
        'budget_ms':30000,'plan':{'schema_version':'task_plan.v2','title':'Search','inputs':{},'steps':[
            {'step_id':'field','action':{'kind':'input_sequence','field_goal':FIELD['field_goal'],
                'text':TEXT,'clear_existing':True,'submit_search':True},'verification':{'kind':'agent_judgment'}}]}}
    target = VisualSubmitTarget(keyboard, action_review=context)
    controller, events, captures = controller_scene(s, monkeypatch)
    from app.core import local_input_policy
    from app.core.input_controller import window_manager
    monkeypatch.setattr(local_input_policy,'current_local_operator_identity',lambda manager: deepcopy(NATIVE))
    monkeypatch.setattr(local_input_policy,'require_local_operator_input',lambda manager: True)
    monkeypatch.setattr(window_manager,'read_owned_foreground_popup',lambda bound: None)
    return NS(s=s, target=target, keyboard=keyboard, context=context, controller=controller,
        events=events,captures=captures,manager=window_manager)


@contextmanager
def reviewed(v):
    frame = capture(v.s.root,'submit-current')
    with agent_grounding_scope(v.target), action_review_scope(v.s.service, context=v.context,
            deadline_ns=v.s.context['deadline_ns'], cancelled=v.s.context.get('cancelled')):
        plan = v.target.plan(image_path=frame['image_path'], goal=FIELD['field_goal'], identity=NATIVE)
        candidate = plan['recommended_target']
        review = review_original_action(capture=frame,identity=NATIVE,candidate=candidate,
            point=FIELD['click_point'],goal=FIELD['field_goal'],click_kind='single',manager=v.manager,
            validate_binding=lambda:(NATIVE,candidate))
        v.target.before_dispatch(FIELD['click_point'],NATIVE)
        prepare_visual_submit(v.manager,FIELD['click_point'],review)
        yield plan


def click():
    return {'clicked':True,'window_point':deepcopy(FIELD['click_point']),'window_handle':10}


def test_current_candidate_review_then_immediate_enter_uses_no_focus_capture(submission):
    from app.core.input_controller import VK_RETURN
    v = submission
    with reviewed(v) as plan:
        assert plan['recommended_target']['source'] == 'verified_visual_field'
        assert plan['execution_path']['external_grounding_used'] is False
        count = len(v.s.requests)
        v.events.append('gated-click')
        output = {}
        perform_visual_submit(v.controller,v.manager,FIELD['click_point'],click(),output=output)
        assert len(v.s.requests) == count
        assert v.events == ['gated-click',(VK_RETURN,)] and v.captures == []
        assert output['visual_submit']['key_dispatch']['dispatch'] == 'completed'
        assert output['visual_submit']['key_result']['pressed'] is True
        with pytest.raises(ValueError,match='consumed'):
            perform_visual_submit(v.controller,v.manager,FIELD['click_point'],click(),output={})


def test_duplicate_value_capability_cannot_create_second_click(submission):
    with pytest.raises(ValueError,match='already_issued'):
        VisualSubmitTarget(submission.keyboard,action_review=submission.context)


@pytest.mark.parametrize('fault',['point','identity','unreviewed'])
def test_changed_binding_or_missing_review_prevents_click_authority(submission,fault):
    v = submission
    frame = capture(v.s.root,'submit-unreviewed')
    with agent_grounding_scope(v.target):
        v.target.plan(image_path=frame['image_path'],goal=FIELD['field_goal'],identity=NATIVE)
        identity,point = deepcopy(NATIVE),deepcopy(FIELD['click_point'])
        if fault == 'point': point['x'] += 1
        if fault == 'identity': identity['process_id'] += 1
        with pytest.raises(ValueError):
            v.target.before_dispatch(point,identity)
    assert v.events == []


def test_cancel_after_review_preserves_click_but_no_enter(submission):
    v = submission
    cancelled = [False]
    object.__setattr__(v.keyboard.proof,'_cancelled',lambda: cancelled[0])
    with reviewed(v):
        cancelled[0] = True
        output = {}
        with pytest.raises(ValueError,match='cancelled'):
            perform_visual_submit(v.controller,v.manager,FIELD['click_point'],click(),output=output)
        assert output['visual_submit']['key_dispatch']['dispatch'] == 'not_started'
        assert output['visual_submit']['key_result'] is None and v.events == []


def test_partial_real_key_exception_remains_unknown(submission,monkeypatch):
    v = submission
    def fail(keys):
        v.events.append('partial-key')
        raise RuntimeError('offline partial key')
    monkeypatch.setattr(v.controller,'_press_chord',fail)
    with reviewed(v):
        output = {}
        with pytest.raises(RuntimeError,match='partial key'):
            perform_visual_submit(v.controller,v.manager,FIELD['click_point'],click(),output=output)
        assert output['visual_submit']['key_dispatch']['dispatch'] == 'started'
        assert output['visual_submit']['key_dispatch']['action_executed'] is None


@pytest.mark.parametrize('fault',[None,'candidate_refused','partial_key'])
def test_submit_through_real_recognition_api(submission,monkeypatch,fault):
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.core.local_input_policy import _local_operator_input_scope
    from app.core.window_manager import WindowRect
    from app.core.input_controller import VK_RETURN
    import app.core.input_controller as native
    v = submission
    frame = capture(v.s.root,'api-submit-current')
    bound = v.manager.get_bound_window()
    bound.rect = WindowRect(0,0,180,90)
    monkeypatch.setattr(v.controller,'_focus_window',lambda _:v.events.append('click-focus'))
    monkeypatch.setattr(v.controller,'_send_move',lambda *args:v.events.append('move'))
    monkeypatch.setattr(v.controller,'_send_mouse_flags',lambda flag:v.events.append(('mouse',flag)))
    monkeypatch.setattr(native.win32api,'GetCursorPos',lambda:(40,30))
    monkeypatch.setattr(v.manager,'get_owned_foreground_popup_handle',lambda _:None)
    for method in ('validate_bound_point_visibility','validate_bound_capture_visibility','validate_bound_region_visibility'):
        monkeypatch.setattr(v.manager,method,lambda **kw:{'allowed':True})
    monkeypatch.setattr(action,'window_manager',v.manager)
    monkeypatch.setattr(action,'input_controller',v.controller)
    monkeypatch.setattr(action.screenshot_service,'capture_window',lambda **kw:{
        'image_path':frame['image_path'],'window_size':frame['window_size'],'roi':None})
    monkeypatch.setattr(action,'prepare_browser_content',lambda *a:None)
    monkeypatch.setattr(action,'_render_recognition_plan_overlay_for_execution',lambda *a:None)
    monkeypatch.setattr(action,'write_trace',lambda **kw:str(v.s.root/'submit-api-trace.json'))
    monkeypatch.setattr(action,'_rewrite_execute_trace_result',lambda **kw:None)
    if fault == 'candidate_refused':
        v.s.probabilities[0] = .01
    if fault == 'partial_key':
        def fail(keys):
            v.events.append(tuple(keys))
            raise RuntimeError('partial Enter backend')
        monkeypatch.setattr(v.controller,'_press_chord',fail)
    with _local_operator_input_scope(manager=v.manager,identity_reader=NS(read_identity=lambda _:deepcopy(NATIVE)),
            identity=NATIVE,window_rect=[0,0,180,90],enabled=lambda:True), agent_grounding_scope(v.target), \
            action_review_scope(v.s.service,context=v.context,deadline_ns=v.s.context['deadline_ns']):
        response = action.execute_recognition_plan(ExecuteRecognitionPlanRequest(goal=FIELD['field_goal'],
            enable_post_click_verification=False,max_attempts=1))
    data = response.data.get('result',response.data)
    assert response.success is (fault is None), response
    if fault == 'candidate_refused':
        assert v.events == [] and 'visual_submit' not in data
    else:
        assert data['click_result']['clicked'] is True
        assert data['visual_submit']['key_dispatch']['dispatch'] == ('started' if fault else 'completed')
        assert data['execution_path']['external_grounding_used'] is False
        assert data['execution_path']['verified_field_grounding_used'] is True
        assert v.events[-1] == (VK_RETURN,) and v.captures == []
