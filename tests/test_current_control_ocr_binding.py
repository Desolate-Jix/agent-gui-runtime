"""多行可点击控件的文字和点击点可以分离，但不能借用邻居或过期证据。"""
from copy import deepcopy
from hashlib import sha256

from PIL import Image
import pytest

from app.api import vision
from app.core.runtime_artifacts import pinned_runtime_output_root
from app.operation.recognition.control_corroboration import (
    current_control_ocr_binding, has_current_control_ocr_binding, EVIDENCE_KEY, REASON,
)
from modules.ocr.contracts import OCRResult, OCRTextMatch, OCRBoundingBox
from tests.test_fresh_action_risk import _candidate, _local, _control, _uia


def _case():
    candidate = _candidate('Atlas Maps https://maps.example.test', role='link')
    local = _local(candidate, matched_text='https://maps.example.test')
    local.refined_click_point = {'x': 125, 'y': 88}
    local.matched_text_bbox = {'x': 110, 'y': 107, 'w': 140, 'h': 15}
    local.coordinate_source = 'vista_point_v1_corroborated_by_local_ocr'
    control = _control('official-link', candidate.label, candidate.element.bbox.to_dict(), control_type='Hyperlink')
    control['runtime_id'] = [42, 100, 3]
    uia = {**_uia(control), 'scan_complete': True, 'truncated': False}
    candidate.element.evidence.update(
        screen_inventory_action={'source': 'windows_uia.controls', 'source_id': control['control_id'],
                                 'bbox': deepcopy(control['bbox'])},
        vista_direct_identity={'source': 'vista_direct_point_grounding', 'point': dict(local.refined_click_point)})
    return candidate, local, uia


def test_current_clickable_control_can_have_multiline_text_away_from_point():
    candidate, local, uia = _case()
    proof = current_control_ocr_binding(candidate, local, uia, 'a' * 64)
    assert proof is not None and proof['point'] == {'x': 125, 'y': 88}
    candidate.element.evidence[EVIDENCE_KEY] = proof
    local.reasons.append(REASON)
    assert has_current_control_ocr_binding(candidate, local, uia, 'a' * 64)
    assert not has_current_control_ocr_binding(candidate, local, uia, 'b' * 64)


@pytest.mark.parametrize('mutation', ['point_outside', 'ocr_outside', 'crop_outside', 'foreign_text',
    'substring_word', 'disabled', 'hidden', 'incomplete', 'truncated', 'duplicate_id',
    'wrong_source', 'wrong_model_point', 'wrong_role', 'field', 'refined_bbox',
    'overlap_point', 'overlap_ocr', 'overlap_ocr_partial', 'unknown_visibility',
    'missing_invoke', 'foreign_candidate', 'foreign_element', 'url_punctuation', 'coordinate_source', 'menu_overlap'])
def test_missing_or_conflicting_current_evidence_cannot_corroborate(mutation):
    candidate, local, uia = _case()
    control = uia['controls'][0]
    if mutation == 'point_outside': local.refined_click_point['x'] = 0
    elif mutation == 'ocr_outside': local.matched_text_bbox['x'] = 0
    elif mutation == 'crop_outside': local.crop_bbox['x'] = 200
    elif mutation == 'foreign_text': local.matched_text = 'Apply now'
    elif mutation == 'substring_word': local.matched_text = 'tl as'
    elif mutation == 'disabled': control['enabled'] = False
    elif mutation == 'hidden': control['visible'] = False
    elif mutation == 'incomplete': uia['scan_complete'] = False
    elif mutation == 'truncated': uia['truncated'] = True
    elif mutation == 'duplicate_id': uia['controls'].append(deepcopy(control))
    elif mutation == 'wrong_source': candidate.element.evidence['screen_inventory_action']['source_id'] = 'other'
    elif mutation == 'wrong_model_point': candidate.element.evidence['vista_direct_identity']['point']['x'] += 1
    elif mutation == 'wrong_role': control['control_type'] = 'Button'
    elif mutation == 'field': candidate.role = candidate.element.role = 'input'
    elif mutation == 'refined_bbox': candidate.refined_bbox['w'] += 1
    elif mutation == 'missing_invoke': control['patterns'] = ['Value']
    elif mutation == 'foreign_candidate': local.candidate_id = 'other'
    elif mutation == 'foreign_element': local.element_id = 'other'
    elif mutation == 'url_punctuation': local.matched_text = 'https://maps-example.test'
    elif mutation == 'coordinate_source': local.coordinate_source = 'foreign_crop_coordinates'
    elif mutation == 'menu_overlap':
        uia['controls'].append(_control('menu', 'Menu', deepcopy(local.matched_text_bbox), control_type='MenuItem'))
        uia['controls'][-1]['patterns'] = []
    else:
        box = {'x': 120, 'y': 80, 'w': 10, 'h': 15} if mutation == 'overlap_point' else (
            {'x': 248, 'y': 115, 'w': 10, 'h': 10} if mutation == 'overlap_ocr_partial'
            else {'x': 110, 'y': 105, 'w': 145, 'h': 20})
        other = _control('neighbor', 'Other', box)
        if mutation == 'unknown_visibility': other['visible'] = None
        uia['controls'].append(other)
    assert current_control_ocr_binding(candidate, local, uia, 'a' * 64) is None


def test_real_local_ocr_pipeline_preserves_model_provenance_for_multiline_control(tmp_path, monkeypatch):
    candidate, local, uia = _case()
    source = tmp_path / 'frame.png'
    Image.new('RGB', (800, 600), 'white').save(source)
    # 局部图左上角为(76,56)，文字仍在当前控件内部而不在模型点上。
    monkeypatch.setattr(vision.ocr_service, 'scan_image', lambda path: OCRResult(image_path=str(path), matches=[
        OCRTextMatch(text=local.matched_text, score=.99, bbox=OCRBoundingBox(x=34, y=51, width=140, height=15))]))
    with pinned_runtime_output_root(tmp_path / 'output'):
        result = vision._corroborate_vista_direct_point(image_path=source, goal=candidate.label,
            candidate=candidate, point=local.refined_click_point, app_name='synthetic', uia_snapshot=uia)
    assert result.status == 'grounded' and result.refined_click_point == {'x': 180, 'y': 114}
    assert candidate.element.evidence['vista_direct_identity']['point'] == local.refined_click_point
    assert result.matched_text_bbox == local.matched_text_bbox and REASON in result.reasons
    assert has_current_control_ocr_binding(candidate, result, uia, sha256(source.read_bytes()).hexdigest())


@pytest.mark.parametrize('control_type', ['MenuItem', 'TabItem', 'TreeItem', 'ListItem', 'RadioButton', 'SplitButton'])
def test_patternless_clickable_neighbors_cannot_lend_their_text(control_type):
    candidate, local, uia = _case()
    other = _control('neighbor', 'Other', deepcopy(local.matched_text_bbox), control_type=control_type)
    other['patterns'] = []
    uia['controls'].append(other)
    assert current_control_ocr_binding(candidate, local, uia, 'a' * 64) is None


@pytest.mark.parametrize('ancestor_type,proven', [('Group', True), ('Group', False), ('Button', True)])
def test_only_proven_structural_ancestors_can_enclose_the_target(ancestor_type, proven):
    candidate, local, uia = _case()
    ancestor = _control('parent', '', {'x': 0, 'y': 0, 'w': 500, 'h': 400}, control_type=ancestor_type)
    if proven:
        uia['controls'][0]['ancestor_control_ids'] = ['parent']
    uia['controls'].append(ancestor)
    assert (current_control_ocr_binding(candidate, local, uia, 'a' * 64) is not None) == (ancestor_type == 'Group' and proven)


@pytest.mark.parametrize('proven,patterns,expected', [
    (True, [], True), (False, [], False), (True, ['Invoke'], False),
    (True, ['SelectionItem'], False), (True, ['Toggle'], False), (True, None, False)])
def test_noninteractive_list_ancestor_does_not_compete_with_child_link(proven, patterns, expected):
    candidate, local, uia = _case()
    ancestor = _control('parent', 'Result summary', {'x': 0, 'y': 0, 'w': 500, 'h': 400}, control_type='ListItem')
    ancestor['patterns'] = patterns
    if proven:
        uia['controls'][0]['ancestor_control_ids'] = ['parent']
    uia['controls'].append(ancestor)
    assert (current_control_ocr_binding(candidate, local, uia, 'a' * 64) is not None) == expected
