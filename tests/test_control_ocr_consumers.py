"""当前控件内 OCR 词组证据必须逐消费者重算，不能由旧几何旁路。"""

from copy import deepcopy

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent, payload_sha256
from app.agent.fresh_learning_action_preview import (
    _decision_and_risk, _parse_projected_recognition, validate_fresh_execution_preview,
    validate_navigation_execution_equivalence,
)
from app.agent.learned_control_reference import recognition_target_from_learned_control, validate_current_learned_control
from app.agent.navigation_visual_stability import _selected_target
from app.operation.recognition.control_corroboration import EVIDENCE_KEY, REASON, current_control_ocr_binding
from tests.test_navigation_execution_equivalence import _direct, _proof
from tests.test_navigation_visual_stability import _current, _far_pixels, _fixture, _png, _revalidate_preview


def _parts(data):
    evidence = data['observation_evidence']
    candidates, local = _parse_projected_recognition(evidence['recognition']['result'])
    return candidates.candidates[0], local.results[0], FreshLearningIntent.from_dict(data['intent'])


def _seal(data):
    candidate, local, _ = _parts(data)
    proof = current_control_ocr_binding(candidate, local, data['uia_snapshot'],
        data['observation_evidence']['capture']['screenshot_sha256'])
    assert proof is not None
    data['observation_evidence']['recognition']['result']['candidate_result']['candidates'][0]['element']['evidence'][EVIDENCE_KEY] = proof


def _case(*, full_ocr=False, role='button', label='View details product guide', phrase='View details'):
    preview, png = _fixture()
    data = preview.to_dict()
    binding = data['intent']['learned_control']
    binding['region'].update(recognition_text=label, kind=role, name=label)
    binding['binding_sha256'] = payload_sha256({k: v for k, v in binding.items() if k != 'binding_sha256'})
    data['intent']['goal'] = label
    evidence = data['observation_evidence']
    evidence['recognition']['goal'] = label
    projection = evidence['recognition']['result']
    for item in (projection, projection['candidate_result'], projection['narrow_search_result']):
        item['goal'] = label
    projection['candidate_result']['summary']['control_target'] = recognition_target_from_learned_control(binding, semantic_action='open_detail')
    candidate = projection['candidate_result']['candidates'][0]
    candidate.update(label=label, text=label, role=role)
    candidate['element'].update(label=label, text=label, role=role)
    control = data['uia_snapshot']['controls'][0]
    control.update(name=label, control_type='Button' if role == 'button' else 'Hyperlink')
    data['uia_snapshot'].update(scan_complete=True, truncated=False, scan_budget=1000, scan_visited_count=1,
        truncation_reason=None)
    local = projection['narrow_search_result']['results'][0]
    local.update(matched_text=label if full_ocr else phrase,
        matched_text_bbox=deepcopy(control['bbox']) if full_ocr else {'x': 85, 'y': 63, 'w': 35, 'h': 12})
    local['reasons'].append(REASON)
    _direct(data, local['refined_click_point'])
    candidate['element']['evidence']['screen_inventory_action'] = {
        'source': 'windows_uia.controls', 'source_id': control['control_id'], 'bbox': deepcopy(control['bbox']),
    }
    evidence['uia']['snapshot_sha256'] = payload_sha256(data['uia_snapshot'])
    _seal(data)
    return data, png


def _consume(kind, data):
    evidence = data['observation_evidence']
    candidate, local, intent = _parts(data)
    if kind == 'preview':
        return _decision_and_risk(evidence, data['uia_snapshot'], intent, require_control_target=True)
    if kind == 'navigation':
        return _selected_target(evidence, data['uia_snapshot'], intent)
    return validate_current_learned_control(intent.learned_control, candidate, local, data['uia_snapshot'],
        evidence['application'], control_target=recognition_target_from_learned_control(intent.learned_control, semantic_action='open_detail'),
        screenshot_sha256=evidence['capture']['screenshot_sha256'])


@pytest.mark.parametrize('kind', ['preview', 'learned', 'navigation'])
@pytest.mark.parametrize('role', ['button', 'link'])
@pytest.mark.parametrize('label,phrase', [('View details product guide', 'View details'), ('查看详情 产品指南', '查看详情')])
def test_current_control_phrase_and_point_outside_text_are_consumed_without_changing_raw_evidence(kind, role, label, phrase):
    data, _ = _case(role=role, label=label, phrase=phrase)
    before = deepcopy(data)
    _consume(kind, data)
    assert data == before


@pytest.mark.parametrize('kind', ['preview', 'learned', 'navigation'])
@pytest.mark.parametrize('damage', ['missing', 'hash', 'point', 'unknown'])
def test_claimed_control_proof_is_rechecked_even_when_old_full_text_geometry_passes(kind, damage):
    data, _ = _case(full_ocr=True)
    evidence = data['observation_evidence']['recognition']['result']['candidate_result']['candidates'][0]['element']['evidence']
    if damage == 'missing': evidence.pop(EVIDENCE_KEY)
    elif damage == 'hash': evidence[EVIDENCE_KEY]['screenshot_sha256'] = 'f' * 64
    elif damage == 'point': evidence[EVIDENCE_KEY]['point']['x'] += 1
    else: evidence[EVIDENCE_KEY]['unexpected'] = True
    with pytest.raises(ValueError, match='current control OCR'):
        _consume(kind, data)


def test_learned_consumer_without_current_capture_hash_cannot_accept_new_proof():
    data, _ = _case(full_ocr=True)
    candidate, local, intent = _parts(data)
    with pytest.raises(ValueError, match='current control OCR'):
        validate_current_learned_control(intent.learned_control, candidate, local, data['uia_snapshot'],
            data['observation_evidence']['application'], control_target=recognition_target_from_learned_control(intent.learned_control, semantic_action='open_detail'))


@pytest.mark.parametrize('spacing_changed', [False, True])
def test_current_control_proof_hash_and_point_are_rebound_for_each_visual_frame(spacing_changed):
    data, png = _case(role='link')
    original = _revalidate_preview(data)
    changed_png = _png(_far_pixels())
    data = original.to_dict()
    data['observation_evidence'] = _current(original, changed_png)
    data['capture_source']['source_id'] = 'e' * 64
    point = data['observation_evidence']['recognition']['result']['narrow_search_result']['results'][0]['refined_click_point']
    point['x'] += 2
    if spacing_changed:
        data['observation_evidence']['recognition']['result']['narrow_search_result']['results'][0]['matched_text'] = 'View\tdetails'
    _direct(data, point)
    _seal(data)
    current = _revalidate_preview(data)
    frozen = (original.to_dict(), current.to_dict())
    assert validate_navigation_execution_equivalence(original, current) is None
    assert validate_fresh_execution_preview(original, current,
        navigation_visual_proof=_proof(original, current, png, changed_png)) is None
    assert (original.to_dict(), current.to_dict()) == frozen


@pytest.mark.parametrize('kind', ['preview', 'learned', 'navigation'])
@pytest.mark.parametrize('damage', ['truncated', 'runtime', 'source', 'ocr_outside', 'overlap', 'phrase'])
def test_current_control_source_and_complete_uia_are_not_replaced_by_cached_proof(kind, damage):
    data, _ = _case(full_ocr=True)
    uia = data['uia_snapshot']
    projection = data['observation_evidence']['recognition']['result']
    candidate = projection['candidate_result']['candidates'][0]
    local = projection['narrow_search_result']['results'][0]
    if damage == 'truncated': uia.update(scan_complete=False, truncated=True)
    elif damage == 'runtime': uia['controls'][0]['runtime_id'][-1] += 1
    elif damage == 'source': candidate['element']['evidence']['vista_direct_identity']['source'] = 'historical'
    elif damage == 'ocr_outside': local['matched_text_bbox']['x'] += 100
    elif damage == 'phrase': local['matched_text'] = 'View details Submit'
    else:
        other = deepcopy(uia['controls'][0])
        other.update(control_id='overlap', runtime_id=[42, 7, 10])
        uia['controls'].append(other)
        uia['control_count'] = uia['scan_visited_count'] = data['observation_evidence']['uia']['control_count'] = 2
    data['observation_evidence']['uia']['snapshot_sha256'] = payload_sha256(uia)
    with pytest.raises(ValueError, match='current control OCR'):
        _consume(kind, data)


def test_different_but_independently_valid_ocr_box_is_not_silently_normalized():
    data, png = _case()
    original = _revalidate_preview(data)
    changed_png = _png(_far_pixels())
    data = original.to_dict()
    data['observation_evidence'] = _current(original, changed_png)
    data['capture_source']['source_id'] = 'e' * 64
    data['observation_evidence']['recognition']['result']['narrow_search_result']['results'][0]['matched_text_bbox']['x'] += 1
    _seal(data)
    current = _revalidate_preview(data)
    proof = _proof(original, current, png, changed_png)
    with pytest.raises(ValueError, match='drifted'):
        validate_fresh_execution_preview(original, current, navigation_visual_proof=proof)
