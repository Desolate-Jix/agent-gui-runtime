"""真实识别前端输出经过公共投影后，预览仍须重算当前字段 OCR 身份。"""
from copy import deepcopy
from hashlib import sha256

from PIL import Image
import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent, payload_sha256
from app.agent.fresh_learning_action_preview import _decision_and_risk, _parse_projected_recognition
from app.agent.fresh_learning_observation import _PUBLIC_RECOGNITION_KEYS, _sanitize_result
from app.agent.live_runtime_composition import _parse_recognition
from app.operation.recognition.editable_control_corroboration import EVIDENCE_KEY, REASON
from tests.test_fill_field_direct_identity import _recognize
from tests.test_fresh_text_preview import _intent_payload, _parameters


def _inputs(tmp_path, monkeypatch):
    result, uia, path = _recognize(tmp_path, monkeypatch)
    assert result['pre_click_decision']['allowed'] is True, result['pre_click_decision']
    assert EVIDENCE_KEY in result['candidate_result']['candidates'][0]['element']['evidence']
    projection = _sanitize_result({key: result[key] for key in _PUBLIC_RECOGNITION_KEYS if key in result},
                                  capture_path=path.resolve())
    candidates, local = _parse_recognition(result)
    for item in local.results:
        item.crop_path = None
    assert (candidates, local) == _parse_projected_recognition(projection)
    with Image.open(path) as image:
        width, height = image.size
    uia = deepcopy(uia)
    uia['window'] = {'handle': 4242, 'process_id': 9001,
                     'bbox': {'x': 0, 'y': 0, 'w': width, 'h': height}}
    evidence = {'target': {'window_handle': 4242, 'process_id': 9001,
                          'rect': {'x': 0, 'y': 0, 'width': width, 'height': height}},
                'capture': {'capture_id': 'capture.synthetic.editable',
                            'screenshot_sha256': sha256(path.read_bytes()).hexdigest(),
                            'viewport_size': {'width': width, 'height': height}},
                'uia': {'snapshot_sha256': payload_sha256(uia)},
                'recognition': {'status': 'completed', 'goal': result['goal'],
                                'result_is_original': False,
                                'result_projection_contract': 'fresh_read_only_recognition_projection_v1',
                                'result': projection}}
    intent = FreshLearningIntent.from_dict({**_intent_payload(_parameters()), 'goal': result['goal']})
    return evidence, uia, intent, result


def test_first_learning_editable_alias_survives_projection_and_risk_recomputation(tmp_path, monkeypatch):
    evidence, uia, intent, original = _inputs(tmp_path, monkeypatch)
    projected = _decision_and_risk(evidence, uia, intent)
    assert projected == _decision_and_risk(evidence, uia, intent, original=original)
    decision, risk = projected
    assert decision['allowed'] is True
    assert risk['hard_blocked'] is False
    assert risk['risk_class'] == 'low_risk_text_input'


@pytest.mark.parametrize('mutation', ['proof_hash', 'missing_proof', 'missing_reason', 'wrong_semantics',
                                      'changed_uia_name', 'changed_uia_readonly', 'orphan_reason'])
def test_recomputed_preview_rejects_editable_alias_tampering(tmp_path, monkeypatch, mutation):
    evidence, uia, intent, _ = _inputs(tmp_path, monkeypatch)
    projection = evidence['recognition']['result']
    candidate = projection['candidate_result']['candidates'][0]
    local = next(item for item in projection['narrow_search_result']['results']
                 if item['candidate_id'] == candidate['candidate_id'])
    proof = candidate['element']['evidence'][EVIDENCE_KEY]
    if mutation == 'proof_hash':
        proof['screenshot_sha256'] = '0' * 64
    elif mutation == 'missing_proof':
        del candidate['element']['evidence'][EVIDENCE_KEY]
    elif mutation == 'missing_reason':
        local['reasons'].remove(REASON)
    elif mutation == 'wrong_semantics':
        payload = intent.to_dict()
        payload.pop('text_parameters_ref')
        payload['semantic_action'] = 'open_detail'
        intent = FreshLearningIntent.from_dict(payload)
    elif mutation in {'changed_uia_name', 'changed_uia_readonly'}:
        target = next(c for c in uia['controls'] if c['control_id'] == proof['control_id'])
        if mutation == 'changed_uia_name':
            target['name'] = 'Different account field'
        else:
            target['is_read_only'] = True
        evidence['uia']['snapshot_sha256'] = payload_sha256(uia)
    else:
        local['candidate_id'] = 'orphan.editable'
        projection['narrow_search_result']['recommended_candidate_id'] = 'orphan.editable'
    expected = 'grounding identities' if mutation == 'orphan_reason' else 'editable field OCR binding'
    with pytest.raises(ValueError, match=expected):
        _decision_and_risk(evidence, uia, intent)
