"""单击类型贯穿即时契约与既有识别路由；此处不发送桌面输入。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from app.api.models.request import ExecuteRecognitionPlanRequest
from app.instant_mcp import InstantCommand
from app.desktop_review.local_action_contract import _validated_request


def test_explicit_focused_typing_preserves_selection():
    data = _validated_request('type_text', {'text': 'Wellington', 'x': 1075, 'y': 477,
                              'click_before_typing': False, 'clear_existing': False})
    assert data['click_before_typing'] is False
    assert data['clear_existing'] is False
    assert data['x'] == 1075 and data['y'] == 477


@pytest.mark.parametrize('extra', [{}, {'click_before_typing': None}, {'click_before_typing': 'false'}])
def test_focused_typing_mode_must_be_explicit(extra):
    with pytest.raises(ValueError, match='explicit'):
        _validated_request('type_text', {'text': 'probe', 'x': 1, 'y': 2, **extra})


@pytest.mark.parametrize('kind,options', [('single', {}), ('right', {'button':'right'}), ('double', {'click_count':2})])
def test_instant_click_kind_survives_validation_without_implicit_retry(kind, options):
    data=InstantCommand.model_validate({'kind':'step','operation':'execute_recognition_plan',
        'request':{'goal':'Click the word labelled alpha','click_kind':kind}}).command()['request']
    request=ExecuteRecognitionPlanRequest.model_validate(_validated_request('execute_recognition_plan',data))
    assert request.click_kind==kind and request.click_options==options
    assert request.max_execution_attempts==1
    assert not request.write_policy.path_graph and not request.write_policy.element_memory


@pytest.mark.parametrize('extra', [
    {'approved_plan_id':'old'}, {'learned_instruction_id':'old'}, {'interface_memory_id':'old'},
    {'learning_mode':'instruction'}, {'agent_mode':'learn'}, {'capture_live':False},
    {'auto_observe_learning_artifacts':True}, {'observe_trace_path':'old.json'},
])
def test_non_single_does_not_silently_reuse_single_click_learning(extra):
    with pytest.raises(ValueError,match='fresh non-learning'):
        ExecuteRecognitionPlanRequest(goal='alpha',click_kind='double',
            write_policy={'path_graph':False,'element_memory':False,'trace':True},**extra)


@pytest.mark.parametrize('kind', ['triple',2,False])
def test_unknown_click_kind_is_not_silently_single_click(kind):
    with pytest.raises(ValueError):
        ExecuteRecognitionPlanRequest(goal='alpha',click_kind=kind)


@pytest.mark.parametrize('kind,options', [('right', {'button':'right'}), ('double', {'click_count':2})])
@pytest.mark.parametrize('failure', [None, 'second_click', 'second_occluded', 'first_unknown'])
@pytest.mark.parametrize('menu_scope', [False, True])
@pytest.mark.parametrize('container_scope', [False, True])
def test_recognition_route_dispatches_selected_kind_once(monkeypatch,tmp_path,kind,options,failure,menu_scope,container_scope):
    from app.api import action
    from app.api.models.response import APIResponse
    from app.core.local_input_policy import _local_operator_input_scope
    from tests.test_local_recognition_policy import plan_fixture
    identity={'contract_version':'windows_native_identity_observation_v1','provider':'windows_native_identity',
        'status':'observed','target_window_handle':321,'process_id':12,'process_create_time':123.5,
        'executable_path':'c:\\fixture\\editor.exe'}
    bound=SimpleNamespace(handle=321,process_id=12,title='Fixture',process_name='editor.exe',
        rect=SimpleNamespace(left=100,top=200,right=1100,bottom=890))
    manager=SimpleNamespace(get_bound_window=lambda:bound)
    monkeypatch.setattr(action,'window_manager',manager)
    monkeypatch.setattr(action.screenshot_service,'capture_window',lambda **kw:{
        'image_path':'capture.png','window_size':{'width':1000,'height':690},'roi':None})
    plan = plan_fixture()
    if menu_scope:
        plan['parse_result']['screen_reading'] = {'source_layers': {'windows_uia': {
            'scan_scope': 'menu_subtree', 'scan_complete': True, 'owned_popup_handle': 900, 'controls': [{
                'control_type': 'MenuItem', 'visible': True, 'enabled': True,
                'bbox': {'x': 160, 'y': 492, 'w': 48, 'h': 48}}]}}}
    monkeypatch.setattr(action,'_run_recognition_plan_for_execution',lambda req:
        APIResponse(success=True,message='fixture',data={'result':deepcopy(plan)}))
    monkeypatch.setattr(action,'_render_recognition_plan_overlay_for_execution',lambda p:None)
    monkeypatch.setattr(action,'write_trace',lambda **kw:str(tmp_path/'trace.json'))
    monkeypatch.setattr(action,'_rewrite_execute_trace_result',lambda **kw:None)
    if container_scope:
        def visibility(plan, point, **kwargs):
            assert kwargs['click_kind'] == kind and kwargs['local_operator'] is True
            return {'scope': 'editable_container_point', 'reason': 'verified_current_edit',
                    'target_bbox': {'x': point['x'], 'y': point['y'], 'width': 1, 'height': 1}}
        monkeypatch.setattr(action, 'recognition_click_visibility', visibility)
    calls=[]
    def click(x,y,**kw):
        calls.append(kw)
        if failure:
            error=(action.TargetPointOccludedError({'reason':'target_point_occluded'})
                   if failure=='second_occluded' else RuntimeError('dispatch interrupted'))
            error.click_sequence={'requested_click_count':options.get('click_count',1),
                'completed_clicks':0 if failure=='first_unknown' else 1,
                'input_attempted':True,'button':options.get('button','left')}
            raise error
        return {'clicked':True,'window_point':{'x':x,'y':y}}
    monkeypatch.setattr(action.input_controller,'click_point',click)
    data=InstantCommand.model_validate({
        'kind':'step','operation':'execute_recognition_plan','request':{
            'goal':'alpha','click_kind':kind,'enable_post_click_verification':False}}).command()['request']
    request=ExecuteRecognitionPlanRequest.model_validate(_validated_request('execute_recognition_plan',data))
    reader=SimpleNamespace(read_identity=lambda handle:deepcopy(identity))
    with _local_operator_input_scope(manager=manager,identity_reader=reader,identity=identity,
            window_rect=(100,200,1100,890),enabled=lambda:True):
        result=action.execute_recognition_plan(request)
    assert len(calls)==1 and all(calls[0].get(k)==v for k,v in options.items())
    assert calls[0].get('expected_owned_popup_handle') == (900 if menu_scope else None)
    if container_scope:
        assert calls[0]['target_bbox'][2:] == (1, 1)
        payload = result.data.get('result', result.data)
        assert payload['click_visibility_scope']['scope'] == 'editable_container_point'
    if failure:
        assert not result.success
        expected=None if failure=='first_unknown' else True
        assert result.data['execution_path']['action_executed'] is expected
        assert result.data['agent_step_result']['action_executed'] is expected
        assert result.data['click_sequence']['input_attempted'] is True
        return
    assert result.success, result
    assert result.data['result']['click_kind']==kind
