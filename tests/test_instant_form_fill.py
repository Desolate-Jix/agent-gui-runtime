"""表单命令接入真实桥接验证和证据投影，不产生桌面输入。"""
from pathlib import Path

import pytest

from app.instant_mcp import InstantCommand, InstantSession, write_json
from app.instant_receipt import compact_receipt
from app.operation.recognition.text_match import explicit_target_role
from app.operation.recognition.control_target import uia_action_identity_matches


def test_form_command_accepts_declared_fields_without_submit():
    command = {'kind':'form_fill', 'request':{'fields':[
        {'kind':'text', 'field_goal':'Name input', 'text':'Trial'},
        {'kind':'dropdown', 'label':'Country', 'option':'New Zealand'},
        {'kind':'checkbox', 'label':'Example choice', 'checked':False},
        {'kind':'radio', 'label':'Small'},
    ]}}
    assert InstantCommand.model_validate(command).command() == command


@pytest.mark.parametrize('extra', [{'submit':True}, {'observation_condition':{}}, {'operation':'press_key'}])
def test_form_command_cannot_smuggle_extra_actions(extra):
    with pytest.raises(ValueError):
        InstantCommand.model_validate({'kind':'form_fill', 'request':{'fields':[
            {'kind':'radio','label':'Small'}]}, **extra}).command()


@pytest.mark.parametrize('status,ok', [('completed',True),('interrupted',False)])
def test_form_receipt_keeps_partial_fields_and_never_claims_task_success(tmp_path,status,ok):
    session = InstantSession(Path(__file__).resolve().parents[1],tmp_path,tmp_path,allow_local_input=True)
    session.session = tmp_path / 'session'
    (session.session / 'responses').mkdir(parents=True)
    result = {'contract_version':'form_fill_v1','status':status,'phase':'returned',
        'completed_fields':[0],'interrupted_at':1 if not ok else None,'action_executed':True,
        'fields':[{'index':0,'kind':'text','status':'completed','steps':[{'receipt':{'secret':'not compact'}}]}],
        'capture':{'image_path':'before.png','sha256':'a'*64},
        'observation':{'status':'captured','capture':{'image_path':'after.png','sha256':'b'*64}}}
    write_json(session.session/'responses'/'form-1.json',{'status':'returned','result':result})
    receipt = session.result('form-1')
    assert receipt['operation_succeeded'] is ok
    assert receipt['task_effect_verified'] is None
    assert receipt['agent_review']['verified'] is None
    assert receipt['agent_review']['after']['sha256'] == 'b'*64
    compact = compact_receipt(receipt)
    assert compact['form']['completed_fields'] == [0]
    assert compact['form']['interrupted_at'] == result['interrupted_at']
    assert 'secret' not in str(compact)


@pytest.mark.parametrize('role,kind,patterns', [
    ('dropdown','ComboBox',['ExpandCollapse','Selection']),
    ('option','ListItem',['SelectionItem']),
])
def test_declared_choice_role_does_not_match_same_named_button(role,kind,patterns):
    goal = f'Click the {role} labelled "Example"'
    assert explicit_target_role(goal) == role
    assert uia_action_identity_matches({'name':'Example','control_type':kind,'patterns':patterns},goal=goal)
    assert not uia_action_identity_matches({'name':'Example','control_type':'Button','patterns':['Invoke']},goal=goal)


@pytest.mark.parametrize('role,kind,pattern', [('dropdown','ComboBox','ExpandCollapse'),
    ('option','ListItem','SelectionItem'),('checkbox','CheckBox','Toggle'),('radio button','RadioButton','SelectionItem')])
def test_named_choice_uses_current_exact_control_primary(tmp_path,monkeypatch,role,kind,pattern):
    from PIL import Image
    from app.api import vision
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    image = tmp_path/'choice.png'
    Image.new('RGB',(800,600),'white').save(image)
    calls = []
    monkeypatch.setattr(vision,'_call_vista_point_prompt',lambda **kw:calls.append(kw) or {
        'point':{'x':120,'y':115},'provider':'test-model-boundary'})
    monkeypatch.setattr(vision.ocr_service,'scan_image',lambda p:OCRResult(image_path=str(p),matches=[]))
    goal = f'Click the {role} labelled "Example"'
    req = vision.VisionRecognitionPlanRequestModel(image_path=str(image),task='locate_element',
        goal=goal,agent_mode='execute',provider_mode='local_grounding',top_k=5,
        write_policy={'path_graph':False,'element_memory':False,'trace':False})
    tree = {'status':'ok','scan_complete':True,'truncated':False,'controls':[{
        'control_id':'choice','name':'Example','control_type':kind,'patterns':[pattern],
        'visible':True,'enabled':True,'bbox':{'x':100,'y':100,'w':100,'h':30}}]}
    with pinned_uia_snapshot(tree),pinned_runtime_output_root(tmp_path):
        res = vision._recognition_plan_from_vista_point(request=req,timer=RuntimeTimer(),
            config={'vision':{'mode':'local_grounding'}},local_config={'model_name':'test','endpoint':'http://unused.invalid'},
            image_path=image,input_image_size=vision.ImageSize(width=800,height=600),goal=goal,
            observe_reuse={},path_graph_recall={'status':'not_requested','candidates':[]})
    assert calls[0]['vista_stage'] == 'pathgraph_candidate_roi_refine'
    assert res.data['result']['recommended_target']['element']['evidence']['screen_inventory_action']['source_id'] == 'choice'
