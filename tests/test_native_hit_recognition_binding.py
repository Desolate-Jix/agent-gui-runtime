"""现场字段命中只能解释结构容器，生产识别和预览必须一致复核。"""
from copy import deepcopy
from hashlib import sha256
from PIL import Image
import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent, payload_sha256
from app.agent.fresh_learning_action_preview import _decision_and_risk
from app.agent.fresh_learning_observation import _PUBLIC_RECOGNITION_KEYS, _sanitize_result
from app.operation.recognition.native_field_hit_binding import EVIDENCE_KEY
from tests.test_fill_field_direct_identity import _control, _recognize
from tests.test_fresh_text_preview import _intent_payload, _parameters


def _proof(*, image_path, uia_snapshot, point):
    field = uia_snapshot['controls'][0]
    box = field['bbox']
    with Image.open(image_path) as image:
        rgb = sha256(image.convert('RGB').crop((box['x'], box['y'], box['x']+box['w'], box['y']+box['h'])).tobytes()).hexdigest()
    target = {'window_handle':4242,'process_id':9001,'process_create_time':2.0,'window_rect':[0,0,640,480]}
    hit = {'contract_version':'windows_field_hit_observation_v1','provider':'windows_uia.from_point',
        'capture_id':'capture.hit','target_field_id':field['control_id'],'target':target,
        'runtime_id':field['runtime_id'],'control_type':field['control_type'],'bbox':box,'point':point,
        'observed_at_ns':40,'sample_count':2,'artifact_is_authorization':False,'action_executed':False}
    return {'contract_version':'current_field_hit_binding_v1','capture_id':'capture.hit',
        'screenshot_sha256':sha256(image_path.read_bytes()).hexdigest(),'uia_snapshot_sha256':payload_sha256(uia_snapshot),
        'capture_started_ns':10,'captured_at_ns':20,'before_hit_ns':30,'after_hit_ns':50,
        'target':target,'hit':hit,'pixels':{'bbox':box,'source_rgb_sha256':rgb,'before_rgb_sha256':rgb,'after_rgb_sha256':rgb}}


def _run(tmp_path, monkeypatch, *, capability=True, overlay_kind='Group', overlay_name='Canvas', mutation=None, ocr_bbox=None):
    from app.agent.native_field_hit_context import pinned_field_hit_collector
    def collect(**kwargs):
        proof = _proof(**kwargs)
        if mutation:
            mutation(proof)
        return proof
    with pinned_field_hit_collector(collect if capability else None):
        return _recognize(tmp_path, monkeypatch, controls=[_control(),
            _control(control_id='canvas', name=overlay_name, control_type=overlay_kind,
                runtime_id=[42,17,99], patterns=['Invoke'], bbox={'x':0,'y':80,'w':640,'h':400})],
            snapshot_changes={'window':{'handle':4242,'process_id':9001,'bbox':{'x':0,'y':0,'w':640,'h':480}}},
            ocr_bbox=ocr_bbox)


@pytest.mark.parametrize('overflow,allowed', [(1,True),(2,True),(3,True),(6,True),(8,False),(10,False)])
def test_native_hit_allows_only_bounded_ocr_edge_rounding(tmp_path, monkeypatch, overflow, allowed):
    result, uia, path = _run(tmp_path, monkeypatch,
        ocr_bbox={'x':24-overflow,'y':30,'width':150,'height':14})
    assert result['pre_click_decision']['allowed'] is allowed
    if allowed:
        evidence, intent = _preview_inputs(result, uia, path)
        decision, _ = _decision_and_risk(evidence, uia, intent)
        assert decision['allowed']
        candidate = result['candidate_result']['candidates'][0]
        assert candidate['element']['bbox'] == {'x':100,'y':100,'w':220,'h':36}
        assert candidate['element']['click_point'] == {'x':160,'y':115}


@pytest.mark.parametrize('overflow,capability,expected_calls,allowed',
                         [(0,True,0,True),(1,True,1,True),(1,False,0,False),(9,True,0,False)])
def test_plain_field_collects_native_hit_only_for_bounded_ocr_edge(tmp_path, monkeypatch,
        overflow, capability, expected_calls, allowed):
    from app.agent.native_field_hit_context import pinned_field_hit_collector
    calls = []
    def collect(**kwargs):
        calls.append(kwargs['point'])
        return _proof(**kwargs)
    with pinned_field_hit_collector(collect if capability else None):
        result, uia, path = _recognize(tmp_path, monkeypatch, controls=[_control()],
            snapshot_changes={'window':{'handle':4242,'process_id':9001,'bbox':{'x':0,'y':0,'w':640,'h':480}}},
            ocr_bbox={'x':24-overflow,'y':30,'width':150,'height':14})
    assert len(calls) == expected_calls
    assert result['pre_click_decision']['allowed'] is allowed
    if allowed:
        evidence, intent = _preview_inputs(result, uia, path)
        assert _decision_and_risk(evidence, uia, intent)[0]['allowed']


def _preview_inputs(result, uia, path):
    projection = _sanitize_result({k:result[k] for k in _PUBLIC_RECOGNITION_KEYS if k in result}, capture_path=path.resolve())
    evidence = {'target':{'window_handle':4242,'process_id':9001,'rect':{'x':0,'y':0,'width':640,'height':480}},
        'application':{'kind':'native','executable_path':'c:\\fixture.exe','process_create_time':2.0},
        'capture':{'capture_id':'capture.hit','screenshot_sha256':sha256(path.read_bytes()).hexdigest(),
            'viewport_size':{'width':640,'height':480},'capture_started_ns':10,'captured_at_ns':20,'observed_at_ns':60},
        'uia':{'snapshot_sha256':payload_sha256(uia)},'recognition':{'status':'completed','goal':result['goal'],
            'result_is_original':False,'result_projection_contract':'fresh_read_only_recognition_projection_v1','result':projection}}
    intent = FreshLearningIntent.from_dict({**_intent_payload(_parameters()), 'goal':result['goal']})
    return evidence, intent


@pytest.mark.parametrize('kind', ['Group','Pane','Document'])
def test_private_native_hit_flows_through_real_recognition_and_preview(tmp_path, monkeypatch, kind):
    result, uia, path = _run(tmp_path, monkeypatch, overlay_kind=kind)
    assert result['pre_click_decision']['allowed'] is True
    evidence, intent = _preview_inputs(result, uia, path)
    decision, risk = _decision_and_risk(evidence, uia, intent, original=result)
    assert decision['allowed'] and risk['risk_class'] == 'low_risk_text_input'
    assert (decision, risk) == _decision_and_risk(evidence, uia, intent)
    assert any(item.get('control_id') == 'canvas' for item in risk['evidence'])


@pytest.mark.parametrize('kind', ['Button','Hyperlink','ComboBox'])
def test_real_action_controls_cannot_be_exempted_by_field_hit(tmp_path, monkeypatch, kind):
    result, _, _ = _run(tmp_path, monkeypatch, overlay_kind=kind)
    assert result['pre_click_decision']['allowed'] is False


def test_no_private_capability_retains_rejection(tmp_path, monkeypatch):
    result, _, _ = _run(tmp_path, monkeypatch, capability=False)
    assert result['pre_click_decision']['allowed'] is False


def test_manual_text_equivalence_keeps_validated_projection_placeholder(tmp_path):
    from tests.test_fresh_text_preview import _text_previews
    from tests.test_automatic_safety_interception import _manual
    from app.agent.fresh_learning_action_preview import validate_text_execution_equivalence
    values = _text_previews(tmp_path, count=2)
    previews = [_manual(item.to_dict()).to_dict() for item in values[0]]
    validate_text_execution_equivalence(*previews)


@pytest.mark.parametrize('manual', [False, True])
def test_native_hit_survives_serialized_preview_and_fresh_equivalence(tmp_path, manual):
    import json
    from tests.test_fresh_text_preview import _text_previews
    from tests.test_automatic_safety_interception import _manual
    from app.agent.fresh_learning_action_preview import FreshLearningActionPreview, validate_text_execution_equivalence
    from tests.test_navigation_visual_stability import _rehash
    from app.agent.fresh_text_field import _field_uia_identity
    previews, _ = _text_previews(tmp_path, count=2)
    values = []
    for preview in previews:
        data = preview.to_dict()
        evidence = data['observation_evidence']
        data['uia_snapshot'].update(scan_complete=True, truncated=False)
        evidence['uia']['snapshot_sha256'] = payload_sha256(data['uia_snapshot'])
        capture = evidence['capture']
        candidate = evidence['recognition']['result']['candidate_result']['candidates'][0]
        point = candidate['element']['click_point']
        field = _field_uia_identity(data['uia_snapshot'], point)
        control = next(c for c in data['uia_snapshot']['controls'] if c['runtime_id'] == list(field['runtime_id']))
        target = {k:evidence['target'][k] for k in ('window_handle','process_id')}
        target.update(process_create_time=evidence['application']['process_create_time'],
                      window_rect=[evidence['target']['rect'][k] for k in ('x','y','width','height')])
        candidate['element']['evidence'][EVIDENCE_KEY] = {
            'contract_version':'current_field_hit_binding_v1',
            **{k:capture[k] for k in ('capture_id','screenshot_sha256','capture_started_ns','captured_at_ns')},
            'uia_snapshot_sha256':payload_sha256(data['uia_snapshot']),
            'before_hit_ns':capture['captured_at_ns'], 'after_hit_ns':capture['captured_at_ns'],
            'target':target, 'hit':{'contract_version':'windows_field_hit_observation_v1',
                'provider':'windows_uia.from_point','capture_id':capture['capture_id'],
                'target_field_id':control['control_id'],'target':target,
                'runtime_id':control['runtime_id'],'control_type':control['control_type'],
                'bbox':control['bbox'],'point':point,'observed_at_ns':capture['captured_at_ns'],
                'sample_count':2,'artifact_is_authorization':False,'action_executed':False},
            'pixels':{'bbox':control['bbox'],**{k:'a'*64 for k in
                ('source_rgb_sha256','before_rgb_sha256','after_rgb_sha256')}}}
        data = _rehash(data)
        if manual:
            data = _manual(data).to_dict()
        values.append(FreshLearningActionPreview.from_dict(json.loads(json.dumps(data))).to_dict())
    validate_text_execution_equivalence(*values)


def test_disproved_container_danger_text_is_not_removed_from_risk(tmp_path, monkeypatch):
    result, uia, path = _run(tmp_path, monkeypatch, overlay_name='Delete account')
    evidence, intent = _preview_inputs(result, uia, path)
    with pytest.raises(ValueError, match='risk blocked'):
        _decision_and_risk(evidence, uia, intent)


@pytest.mark.parametrize('change', ['capture','pixels','uia_hash','runtime','point','process','future','extra'])
def test_preview_rejects_native_hit_tampering(tmp_path, monkeypatch, change):
    result, uia, path = _run(tmp_path, monkeypatch)
    evidence, intent = _preview_inputs(result, uia, path)
    hit = evidence['recognition']['result']['candidate_result']['candidates'][0]['element']['evidence'][EVIDENCE_KEY]
    if change == 'capture': hit['capture_id'] = hit['hit']['capture_id'] = 'other'
    elif change == 'pixels': hit['pixels']['after_rgb_sha256'] = '0'*64
    elif change == 'uia_hash': hit['uia_snapshot_sha256'] = '0'*64
    elif change == 'runtime': hit['hit']['runtime_id'] = [1,2]
    elif change == 'point': hit['hit']['point'] = {'x':1,'y':1}
    elif change == 'process': hit['target']['process_create_time'] = hit['hit']['target']['process_create_time'] = 3.0
    elif change == 'future': hit['after_hit_ns'] = 100
    else: hit['trusted'] = True
    with pytest.raises(ValueError, match='(native field hit|owned capture)'):
        _decision_and_risk(evidence, uia, intent)
