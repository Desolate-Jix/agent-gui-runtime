"""无文字图标依赖真实原生命中，不使用目标提示词伪造 OCR。"""
from copy import deepcopy
from hashlib import sha256
import pytest

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.native_control_hit_context import pinned_control_hit_collector
from app.operation.recognition.native_control_hit_binding import EVIDENCE_KEY, COORDINATE_SOURCE
from tests.test_uia_learning_current_point import _recognize, _control


def _proof(*, image_path, uia_snapshot, point):
    control = uia_snapshot['controls'][0]
    target = {'window_handle':4242,'process_id':9001,'process_create_time':2.0,'window_rect':[0,0,500,360]}
    return {'contract_version':'current_control_hit_binding_v1','capture_id':'capture.icon',
        'screenshot_sha256':sha256(image_path.read_bytes()).hexdigest(),'uia_snapshot_sha256':payload_sha256(uia_snapshot),
        'capture_started_ns':10,'captured_at_ns':20,'before_hit_ns':30,'after_hit_ns':50,
        'target':target,'hit':{'contract_version':'native_control_hit_v1','provider':'windows_uia.from_point',
            'capture_id':'capture.icon','control_id':control['control_id'],'target':target,
            'accessible_name':control['name'],'runtime_id':control['runtime_id'],
            'control_type':control['control_type'],'bbox':control['bbox'],'point':point,
            'observed_at_ns':40,'sample_count':2,'pattern':'Invoke',
            'artifact_is_authorization':False,'action_executed':False},
        'pixels':{'bbox':control['bbox'],**{k:'a'*64 for k in ('source_rgb_sha256','before_rgb_sha256','after_rgb_sha256')}}}


def _run(tmp_path, monkeypatch, *, capability=True, mutation=None, ocr_text=None, controls=None):
    calls=[]
    def collect(**kwargs):
        calls.append(kwargs)
        proof=_proof(**kwargs)
        if mutation: mutation(proof)
        return proof
    with pinned_control_hit_collector(collect if capability else None):
        result=_recognize(tmp_path,monkeypatch,
            controls or [_control(runtime_id=[42,3,1])],ocr_text=ocr_text,target=None,
            snapshot_metadata={'control_count':len(controls or [None]),
                'window':{'handle':4242,'process_id':9001,'bbox':{'x':0,'y':0,'w':500,'h':360}}})
    return result,calls


def test_icon_with_native_hit_is_not_required_to_invent_ocr(tmp_path,monkeypatch):
    result,calls=_run(tmp_path,monkeypatch)
    assert result['pre_click_decision']['allowed'] is True
    assert len(calls)==1
    local=result['narrow_search_result']['results'][0]
    assert local['coordinate_source']==COORDINATE_SOURCE
    assert local['matched_text'] is None and local['matched_text_bbox'] is None
    assert result['execution_path']['action_executed'] is False


@pytest.mark.parametrize('overlap', [False, True])
def test_icon_ocr_context_is_scoped_to_actual_control(tmp_path, monkeypatch, overlap):
    from tests import test_uia_learning_current_point as fixture
    from modules.ocr.contracts import OCRBoundingBox
    if not overlap:
        monkeypatch.setattr(fixture, 'OCRBoundingBox',
            lambda **kwargs: OCRBoundingBox(x=0, y=0, width=10, height=10))
    result, calls = _run(tmp_path, monkeypatch, ocr_text='ZZZ999')
    assert result['pre_click_decision']['allowed'] is (not overlap), str(result['narrow_search_result']['results'])
    assert bool(calls)
    if overlap:
        assert 'native_control_ocr_semantic_disagreement' in result['pre_click_decision']['candidate_decisions'][0]['reasons']
    if not overlap:
        local = result['narrow_search_result']['results'][0]
        assert 'local_ocr_no_text_in_target' in local['reasons']
        assert 'local_ocr_returned_no_text' not in local['reasons']
        assert local['matched_text'] is None


@pytest.mark.parametrize('values,expected', [
    ((0, 0, 10, 10), True), ((14, 24, 10, 10), True),
    ((15, 24, 10, 10), False), ((24, 24, 5, 5), False),
    ((-1, 0, 10, 10), False), ((0, 0, 0, 10), False),
    ((95, 0, 10, 10), False), ((float('nan'), 0, 10, 10), False),
    ((float('inf'), 0, 10, 10), False), ((False, 0, 10, 10), False),
])
def test_outside_ocr_requires_valid_crop_coordinates(values, expected):
    from types import SimpleNamespace
    from app.operation.recognition.local_grounding import _ocr_outside_target
    from app.vision.schemas import BBox
    box = SimpleNamespace(**dict(zip(('x', 'y', 'width', 'height'), values)))
    assert _ocr_outside_target([SimpleNamespace(bbox=box)],
        {'x': 342, 'y': 68, 'width': 96, 'height': 100},
        BBox(x=366, y=92, w=48, h=52)) is expected


@pytest.mark.parametrize('ocr_text',[None,'Confirm payment'])
def test_no_capability_or_conflicting_text_does_not_grant_icon_grounding(tmp_path,monkeypatch,ocr_text):
    result,calls=_run(tmp_path,monkeypatch,capability=ocr_text is not None,ocr_text=ocr_text)
    assert result['pre_click_decision']['allowed'] is False
    assert bool(calls) is (ocr_text is not None)


@pytest.mark.parametrize('key',['runtime','name','pixels','uia','point','count','authorization'])
def test_native_icon_rejects_tampered_hit(tmp_path,monkeypatch,key):
    def mutate(proof):
        if key=='runtime': proof['hit']['runtime_id']=[42,99]
        elif key=='name': proof['hit']['accessible_name']='Other'
        elif key=='pixels': proof['pixels']['after_rgb_sha256']='b'*64
        elif key=='uia': proof['uia_snapshot_sha256']='b'*64
        elif key=='point': proof['hit']['point']={'x':1,'y':1}
        elif key=='count': proof['hit']['sample_count']=True
        else: proof['hit']['artifact_is_authorization']=True
    result,_=_run(tmp_path,monkeypatch,mutation=mutate)
    assert result['pre_click_decision']['allowed'] is False


def _icon_preview(*, generation=0):
    from hashlib import sha1
    from app.agent.fresh_learning_action_preview import FreshLearningActionPreview, _decision_and_risk
    from app.agent.fresh_learning_action_contracts import FreshLearningIntent
    from tests.test_navigation_visual_stability import _fixture, _rehash
    from app.operation.recognition.native_control_hit_binding import REASON
    preview,png=_fixture()
    data=preview.to_dict()
    data['intent'].pop('learned_control')
    data['contract_version']='fresh_learning_action_preview_v1'
    evidence=data['observation_evidence']; capture=evidence['capture']; uia=data['uia_snapshot']
    uia.update(scan_complete=True,truncated=False)
    control=uia['controls'][0]
    capture.update(capture_id=f'icon-{generation}',capture_started_ns=100+generation*100,
        captured_at_ns=110+generation*100,observed_at_ns=140+generation*100)
    evidence['uia']['snapshot_sha256']=payload_sha256(uia)
    projection=evidence['recognition']['result']; projection['candidate_result']['summary']={}
    candidate=projection['candidate_result']['candidates'][0]
    local=projection['narrow_search_result']['results'][0]; point=local['refined_click_point']
    candidate['element']['evidence']={'screen_inventory_action':{'source':'windows_uia.controls',
        'source_id':control['control_id'],'bbox':control['bbox']},
        'vista_direct_identity':{'source':'vista_direct_point_grounding','point':dict(point),
            'source_candidate_id':'vista_direct_'+sha1(f"{data['intent']['goal']}|{point['x']}|{point['y']}".encode()).hexdigest()[:10]}}
    target={'window_handle':4242,'process_id':9001,'process_create_time':33.5,'window_rect':[0,0,360,260]}
    candidate['element']['evidence'][EVIDENCE_KEY]={
        'contract_version':'current_control_hit_binding_v1',
        **{k:capture[k] for k in ('capture_id','screenshot_sha256','capture_started_ns','captured_at_ns')},
        'uia_snapshot_sha256':payload_sha256(uia),'before_hit_ns':capture['captured_at_ns'],
        'after_hit_ns':capture['captured_at_ns']+10,'target':target,
        'hit':{'contract_version':'native_control_hit_v1','provider':'windows_uia.from_point',
            'capture_id':capture['capture_id'],'control_id':control['control_id'],'target':target,
            'accessible_name':control['name'],'runtime_id':control['runtime_id'],
            'control_type':control['control_type'],'bbox':control['bbox'],'point':point,
            'observed_at_ns':capture['captured_at_ns']+5,'sample_count':2,'pattern':'Invoke',
            'artifact_is_authorization':False,'action_executed':False},
        'pixels':{'bbox':control['bbox'],**{k:'a'*64 for k in ('source_rgb_sha256','before_rgb_sha256','after_rgb_sha256')}}}
    local.update(matched_text=None,matched_text_bbox=None,coordinate_source=COORDINATE_SOURCE,
        reasons=['no_matching_local_ocr_text','local_ocr_returned_no_text',REASON])
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from app.agent.fresh_learning_action_preview import _parse_projected_recognition
    from app.operation.recognition.native_control_ocr_observation import KEY, record_native_ocr
    from modules.ocr.contracts import OCRResult
    parsed, _ = _parse_projected_recognition(projection)
    crop = local['crop_bbox']
    with TemporaryDirectory(prefix='native-icon-ocr-') as directory:
        image_path = Path(directory) / 'source.png'
        image_path.write_bytes(png)
        candidate['element']['evidence'][KEY] = record_native_ocr(image_path=image_path,
            image_size=(360, 260), crop={'x':crop['x'], 'y':crop['y'], 'width':crop['w'], 'height':crop['h']},
            candidate=parsed.candidates[0], ocr_result=OCRResult(image_path=str(image_path), matches=[],
                metadata={'engine':'synthetic'}))
    decision,risk=_decision_and_risk(evidence,uia,FreshLearningIntent.from_dict(data['intent']))
    data.update(pre_click_decision=decision,risk=risk)
    return FreshLearningActionPreview.from_dict(_rehash(data)),png


def test_icon_preview_reopens_and_compares_new_capture_without_fake_text():
    import json
    from app.agent.fresh_learning_action_preview import FreshLearningActionPreview,validate_navigation_execution_equivalence
    from app.agent.navigation_visual_stability import NavigationVisualStabilityScope
    from app.agent.fresh_learning_recording import fresh_target_observation
    before,png=_icon_preview(); after,_=_icon_preview(generation=1)
    reopened=FreshLearningActionPreview.from_dict(json.loads(json.dumps(before.to_dict())))
    validate_navigation_execution_equivalence(reopened.to_dict(),after.to_dict())
    scope=NavigationVisualStabilityScope(reopened,png)
    assert scope.validate(after.to_dict()['observation_evidence'],png).to_reference()['changed_pixels']==0
    assert fresh_target_observation(reopened)['text']==''


@pytest.mark.parametrize('change',['name','point','time','capture','pixels','marker'])
def test_icon_preview_rejects_changed_proof_even_when_rehashed(change):
    from app.agent.fresh_learning_action_preview import FreshLearningActionPreview
    from tests.test_navigation_visual_stability import _rehash
    preview,_=_icon_preview(); data=preview.to_dict()
    proof=data['observation_evidence']['recognition']['result']['candidate_result']['candidates'][0]['element']['evidence'][EVIDENCE_KEY]
    if change=='name': proof['hit']['accessible_name']='Other'
    elif change=='point': proof['hit']['point']={'x':81,'y':61}
    elif change=='time': proof['after_hit_ns']=999999
    elif change=='capture': proof['capture_id']=proof['hit']['capture_id']='other'
    elif change=='pixels': proof['pixels']['after_rgb_sha256']='f'*64
    else: proof['hit']['action_executed']=True
    with pytest.raises(ValueError,match='native control'):
        FreshLearningActionPreview.from_dict(_rehash(data))


def test_real_recognition_projection_preserves_native_proof_and_preview(tmp_path,monkeypatch):
    from app.agent.fresh_learning_action_preview import _decision_and_risk
    from app.agent.fresh_learning_action_contracts import FreshLearningIntent
    from app.agent.fresh_learning_observation import _PUBLIC_RECOGNITION_KEYS,_sanitize_result
    result,calls=_run(tmp_path,monkeypatch)
    uia=calls[0]['uia_snapshot']; path=calls[0]['image_path']
    evidence={'target':{'window_handle':4242,'process_id':9001,'rect':{'x':0,'y':0,'width':500,'height':360}},
        'application':{'kind':'native','executable_path':'c:\\fixture.exe','process_create_time':2.0},
        'capture':{'capture_id':'capture.icon','screenshot_sha256':sha256(path.read_bytes()).hexdigest(),
            'viewport_size':{'width':500,'height':360},'capture_started_ns':10,'captured_at_ns':20,'observed_at_ns':60},
        'uia':{'snapshot_sha256':payload_sha256(uia)},'recognition':{'status':'completed','goal':result['goal'],
            'result_is_original':False,'result_projection_contract':'fresh_read_only_recognition_projection_v1',
            'result':_sanitize_result({k:result[k] for k in _PUBLIC_RECOGNITION_KEYS if k in result},capture_path=path.resolve())}}
    intent=FreshLearningIntent.from_dict({'contract_version':'fresh_learning_action_intent_v1',
        'intent_id':'intent','session_id':'session','observation_id':'observation','source_sha256':'a'*64,
        'action_id':'icon','semantic_action':'open_detail','goal':result['goal']})
    decision,risk=_decision_and_risk(evidence,uia,intent)
    assert decision['allowed'] and risk['risk_class']=='low_risk_navigation'
    assert (decision,risk)==_decision_and_risk(evidence,uia,intent,original=result)


@pytest.mark.parametrize('change',['overlap','runtime_duplicate','disabled','hidden','truncated','no_invoke','empty_name'])
def test_native_control_proof_cannot_remove_real_ambiguity(change):
    from app.operation.recognition.native_control_hit_binding import current_icon_control
    controls=[_control(runtime_id=[42,3,1])]
    uia={'status':'ok','scan_complete':True,'truncated':False,'controls':controls}
    if change=='overlap': controls.append(_control('other',runtime_id=[42,3,2]))
    elif change=='runtime_duplicate': controls.append(_control('other',y=80,runtime_id=[42,3,1]))
    elif change=='disabled': controls[0]['enabled']=False
    elif change=='hidden': controls[0]['visible']=False
    elif change=='truncated': uia['truncated']=True
    elif change=='no_invoke': controls[0]['patterns']=[]
    else: controls[0]['name']=''
    assert current_icon_control(uia,{'x':250,'y':200}) is None


def test_icon_is_not_payment_permission():
    from app.agent.fresh_learning_action_preview import _parse_projected_recognition
    from app.gate.fresh_action_risk import classify_fresh_action_risk
    preview,_=_icon_preview(); data=preview.to_dict()
    candidate,local=_parse_projected_recognition(data['observation_evidence']['recognition']['result'])
    item=candidate.candidates[0]
    item.label=item.text=item.element.label=item.element.text='Confirm payment'
    risk=classify_fresh_action_risk(proposed_semantic_action='open_detail',goal='Confirm payment',
        candidate=item,local=local.results[0],capture_id='icon',uia_snapshot=data['uia_snapshot'])
    assert risk['hard_blocked'] is True
