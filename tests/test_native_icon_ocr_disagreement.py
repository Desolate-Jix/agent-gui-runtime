"""原生位置与 OCR 分歧分别封存，手动策略不伪造严格通过。"""
from copy import deepcopy
import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.fresh_learning_action_preview import _decision_and_risk, validate_navigation_execution_equivalence
from app.operation.recognition.native_control_ocr_observation import KEY, DISAGREEMENT
from tests.test_native_icon_grounding import _icon_preview, _run
from tests.test_automatic_safety_interception import _manual


def _data(text='Q', generation=0):
    preview, png = _icon_preview(generation=generation)
    data = preview.to_dict()
    evidence = data['observation_evidence']
    recognition = evidence['recognition']['result']
    candidate = recognition['candidate_result']['candidates'][0]
    local = recognition['narrow_search_result']['results'][0]
    crop, box = local['crop_bbox'], candidate['element']['bbox']
    candidate['element']['evidence'][KEY] = {
        'contract_version': 'native_control_ocr_observation_v1',
        'source_screenshot_sha256': evidence['capture']['screenshot_sha256'],
        'candidate_id': candidate['candidate_id'], 'element_id': candidate['element_id'],
        'crop_bbox': crop, 'target_bbox': box,
        'viewport_size': [evidence['capture']['viewport_size'][k] for k in ('width', 'height')],
        'ocr_engine': 'synthetic',
        'matches': [{'text': text, 'score': 0.624, 'bbox': {
            'x': box['x'] - crop['x'] + 2, 'y': box['y'] - crop['y'] + 2, 'width': 12, 'height': 12}}],
        'classification': 'target_text_present', 'target_match_indices': [0]}
    local['reasons'] = [r for r in local['reasons'] if r != 'local_ocr_returned_no_text'] + [DISAGREEMENT]
    return data, png


def test_real_producer_keeps_raw_q_without_strict_permission(tmp_path, monkeypatch):
    result, calls = _run(tmp_path, monkeypatch, ocr_text='Q')
    assert len(calls) == 1
    local = result['narrow_search_result']['results'][0]
    assert local['status'] == 'grounded'
    assert local['matched_text'] is None
    candidate = result['candidate_result']['candidates'][0]
    observed = candidate['element']['evidence'][KEY]
    assert observed['matches'][0]['text'] == 'Q'
    assert observed['target_match_indices'] == [0]
    assert result['pre_click_decision']['allowed'] is False
    assert DISAGREEMENT in result['pre_click_decision']['candidate_decisions'][0]['reasons']


def test_manual_preview_preserves_original_denial_and_raw_target_ocr():
    data, _ = _data()
    with pytest.raises(ValueError, match='pre-click gate rejected'):
        _decision_and_risk(data['observation_evidence'], data['uia_snapshot'], FreshLearningIntent.from_dict(data['intent']))
    value = _manual(data).to_dict()
    assert value['pre_click_decision']['allowed'] is False
    assert value['automatic_safety_report']['would_block'] is True
    assert DISAGREEMENT in value['automatic_safety_report']['reasons']
    assert any(item['source'] == 'native_control_target_ocr' and item['texts'] == ['Q'] for item in value['risk']['evidence'])


def test_manual_comparison_keeps_target_ocr_semantics_not_capture_hash():
    before, _ = _data(); after, _ = _data(generation=1)
    validate_navigation_execution_equivalence(_manual(before), _manual(after))
    changed, _ = _data('Confirm payment', generation=1)
    value = _manual(changed).to_dict()
    assert value['risk']['hard_blocked'] is True
    with pytest.raises(ValueError, match='target, geometry or bound source changed'):
        validate_navigation_execution_equivalence(_manual(before), _manual(changed))


@pytest.mark.parametrize('change', ['source', 'classification', 'indices', 'bbox', 'nan', 'missing', 'marker'])
def test_changed_disagreement_evidence_is_rejected(change):
    data, _ = _data()
    recognition = data['observation_evidence']['recognition']['result']
    candidate = recognition['candidate_result']['candidates'][0]
    observed = candidate['element']['evidence'][KEY]
    if change == 'source': observed['source_screenshot_sha256'] = 'f' * 64
    elif change == 'classification': observed['classification'] = 'empty'
    elif change == 'indices': observed['target_match_indices'] = []
    elif change == 'bbox': observed['matches'][0]['bbox']['width'] = 99999
    elif change == 'nan': observed['matches'][0]['score'] = float('nan')
    elif change == 'missing': candidate['element']['evidence'].pop(KEY)
    else: recognition['narrow_search_result']['results'][0]['reasons'].remove(DISAGREEMENT)
    with pytest.raises(ValueError):
        _manual(data)


@pytest.mark.parametrize('claim', ['local_ocr_returned_no_text', 'local_ocr_no_text_in_target'])
def test_removing_raw_fact_and_disagreement_cannot_downgrade_to_no_text(claim):
    data, _ = _data('Confirm payment')
    evidence = data['observation_evidence']
    recognition = evidence['recognition']['result']
    recognition['candidate_result']['candidates'][0]['element']['evidence'].pop(KEY)
    local = recognition['narrow_search_result']['results'][0]
    local['reasons'] = [reason for reason in local['reasons'] if reason != DISAGREEMENT] + [claim]
    with pytest.raises(ValueError, match='native control'):
        _decision_and_risk(evidence, data['uia_snapshot'], FreshLearningIntent.from_dict(data['intent']))
    with pytest.raises(ValueError, match='native control'):
        _manual(data)
