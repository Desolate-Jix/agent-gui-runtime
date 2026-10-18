"""无可读 UIA 名称的填写目标必须由当前字段、模型原点和局部 OCR 共同证明。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.api import vision as vision_api
from app.api.application import create_runtime_app
from app.agent.live_runtime_composition import _parse_recognition
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def _control(**changes):
    value = {'provider': 'windows_uia', 'control_id': 'field-1', 'name': '\ufffc',
             'control_type': 'ComboBox', 'automation_id': 'query', 'class_name': 'Editor',
             'bbox': {'x': 100, 'y': 100, 'w': 220, 'h': 36},
             'screen_bbox': {'x': 100, 'y': 100, 'w': 220, 'h': 36},
             'enabled': True, 'visible': True, 'patterns': ['Value', 'Text', 'ExpandCollapse'],
             'runtime_id': [42, 17, 1], 'ancestor_control_ids': []}
    value.update(changes)
    return value


def _recognize(tmp_path, monkeypatch, *, controls=None, goal='Search records', raw='[250, 240]',
               ocr_text=None, ocr_bbox=None, snapshot_changes=None, semantic_action='fill_field',
               control_target=None):
    path = tmp_path / 'capture.png'
    Image.new('RGB', (640, 480), 'white').save(path)
    controls = [_control(), _control(control_id='search-button', name='Search', control_type='Button',
        patterns=['Invoke'], runtime_id=[42, 17, 2], bbox={'x': 325, 'y': 95, 'w': 50, 'h': 48},
        screen_bbox={'x': 325, 'y': 95, 'w': 50, 'h': 48})] if controls is None else controls
    uia = {'provider': 'windows_uia', 'provider_version': 'windows_uia_provider_v1',
           'status': 'ok', 'control_count': len(controls), 'controls': controls,
           'scan_complete': True, 'truncated': False, 'scan_budget': 1000,
           'scan_visited_count': len(controls)}
    uia.update(snapshot_changes or {})
    monkeypatch.setattr(vision_api.uia_provider, 'snapshot_bound_window', lambda **_: deepcopy(uia))
    monkeypatch.setattr(vision_api.VisionProviderFactory, 'load_config', lambda: {
        'vision': {'mode': 'local', 'timeout_seconds': 10, 'local_grounding': {
            'model_name': 'inclusionAI/VISTA-4B', 'endpoint': 'http://127.0.0.1:1/v1/chat/completions',
            'runtime': 'transformers', 'output_contract': 'vista_point_v1'}}})
    monkeypatch.setattr(vision_api.VisionProviderFactory, 'create', lambda **_: object())
    monkeypatch.setattr(vision_api, 'VISTA_DIRECT_IMAGES_DIR', tmp_path / 'model-crops')
    text = goal if ocr_text is None else ocr_text
    monkeypatch.setattr(vision_api.ocr_service, 'scan_image', lambda image: OCRResult(
        image_path=str(image), matches=[OCRTextMatch(text=text, score=.96,
            bbox=OCRBoundingBox(**(ocr_bbox or {'x': 28, 'y': 30, 'width': 150, 'height': 14})))]))
    prompts = []
    def model(_self, image, prompt, **kwargs):
        prompts.append(prompt)
        return {'choices': [{'message': {'content': raw}}]}
    monkeypatch.setattr(vision_api.LocalVisionProvider, '_call_openai_compatible_endpoint', model)
    with TestClient(create_runtime_app()) as client:
        response = client.post('/vision/recognition_plan', json={
            'image_path': str(path), 'provider_mode': 'local_grounding', 'task': 'locate_element',
            'goal': goal, 'agent_mode': 'execute', 'top_k': 5,
            'write_policy': {'path_graph': False, 'element_memory': False, 'trace': False},
            'metadata': {'vista_direct_grounding': {'enabled': True, 'refine': False},
                         'semantic_action': semantic_action,
                         **({'control_target': control_target} if control_target else {})}})
    assert response.status_code == 200, response.text
    assert response.json()['success'], response.text
    result = response.json()['data']['result']
    assert result['execution_path']['action_executed'] is False
    if semantic_action == 'fill_field' and result['execution_path'].get('vista_direct_point_grounding_used'):
        assert 'editable' in prompts[0].casefold()
        assert 'interior' in prompts[0].casefold()
    return result, uia, path


@pytest.mark.parametrize(('name', 'kind', 'goal'), [
    ('\ufffc', 'ComboBox', 'Search records'), ('', 'Edit', 'Project title'),
    ('  ', 'Edit', '\u641c\u7d22\u4ed3\u5e93'), ('\ufffc', 'ComboBox', 'Find files'),
    (None, 'Edit', 'Workspace name')])
def test_direct_fill_uses_current_editable_identity_and_observed_label(name, kind, goal, tmp_path, monkeypatch):
    from app.operation.recognition.editable_control_corroboration import EVIDENCE_KEY, REASON, has_current_editable_control_ocr_binding
    result, uia, path = _recognize(tmp_path, monkeypatch, controls=[_control(name=name, control_type=kind)], goal=goal)
    ranked, grounded = _parse_recognition(result)
    assert result['pre_click_decision']['allowed'] is True
    candidate, local = ranked.candidates[0], grounded.results[0]
    assert candidate.label == local.matched_text == goal
    assert candidate.role == candidate.element.role == 'input'
    assert candidate.element.interaction_type == 'focus'
    assert local.refined_click_point == {'x': 160, 'y': 115}
    assert candidate.element.bbox.to_dict() == uia['controls'][0]['bbox']
    assert candidate.element.evidence['screen_inventory_action']['label'] == name
    assert REASON in local.reasons
    assert candidate.element.evidence[EVIDENCE_KEY]['raw_name'] == name
    assert has_current_editable_control_ocr_binding(candidate, local, uia, hashlib.sha256(path.read_bytes()).hexdigest(), goal)


@pytest.mark.parametrize('case', ['readonly', 'password', 'disabled', 'visibility_unknown', 'not_editable',
    'overlap_disabled', 'overlap_unknown', 'overlap_invoke', 'duplicate_runtime', 'named_conflict',
    'other_named_target', 'truncated', 'incomplete', 'point_on_button', 'ocr_outside', 'ocr_mismatch'])
def test_unproven_field_is_not_promoted(case, tmp_path, monkeypatch):
    controls = [_control()]
    kwargs = {}
    if case in {'readonly', 'password'}:
        controls[0][case] = True
    elif case == 'disabled': controls[0]['enabled'] = False
    elif case == 'visibility_unknown': controls[0]['visible'] = None
    elif case == 'not_editable': controls[0]['patterns'] = ['Value', 'ExpandCollapse']
    elif case.startswith('overlap_'):
        other = _control(control_id='other', runtime_id=[42, 17, 2])
        if case == 'overlap_disabled': other['enabled'] = False
        elif case == 'overlap_unknown': other['visible'] = None
        else: other.update(control_type='Group', patterns=['Invoke'])
        controls.append(other)
    elif case == 'duplicate_runtime':
        controls.append(_control(control_id='other', bbox={'x': 400, 'y': 100, 'w': 100, 'h': 40}))
    elif case == 'named_conflict': controls[0]['name'] = 'Delete records'
    elif case == 'other_named_target':
        controls.append(_control(control_id='other', runtime_id=[42, 17, 2], name='Search records',
            bbox={'x': 400, 'y': 100, 'w': 100, 'h': 40}))
        kwargs['control_target'] = {'contract_version': 'recognition_control_target_v1',
            'role': 'input', 'label': 'Search records', 'source_binding_sha256': 'a' * 64}
    elif case == 'truncated': kwargs['snapshot_changes'] = {'truncated': True}
    elif case == 'incomplete': kwargs['snapshot_changes'] = {'scan_complete': False}
    elif case == 'point_on_button': kwargs['raw'] = '[700, 500]'
    elif case == 'ocr_outside': kwargs['ocr_bbox'] = {'x': 28, 'y': 3, 'width': 150, 'height': 14}
    elif case == 'ocr_mismatch': kwargs['ocr_text'] = 'Search users'
    result, _, _ = _recognize(tmp_path, monkeypatch, controls=controls, **kwargs)
    assert result['pre_click_decision']['allowed'] is False
    assert not any(item['status'] == 'grounded' for item in result['narrow_search_result']['results'])


def test_model_focus_point_need_not_be_inside_placeholder_glyphs(tmp_path, monkeypatch):
    result, _, _ = _recognize(tmp_path, monkeypatch, raw='[250, 260]')
    assert result['pre_click_decision']['allowed'] is True
    local = result['narrow_search_result']['results'][0]
    assert local['refined_click_point'] == {'x': 160, 'y': 125}
    assert local['matched_text_bbox']['y'] + local['matched_text_bbox']['h'] < 125


@pytest.mark.parametrize('fault', ['point', 'bbox', 'role', 'interaction', 'label', 'raw_name', 'source_id',
    'runtime', 'ocr_text', 'ocr_punctuation', 'ocr_bbox', 'crop', 'sha', 'reason', 'proof', 'control_target'])
def test_binding_is_recomputed_from_current_evidence(fault, tmp_path, monkeypatch):
    from app.operation.recognition.editable_control_corroboration import EVIDENCE_KEY, REASON, has_current_editable_control_ocr_binding
    result, uia, path = _recognize(tmp_path, monkeypatch)
    ranked, grounding = _parse_recognition(result)
    candidate, local = ranked.candidates[0], grounding.results[0]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    target = None
    if fault == 'point': local.refined_click_point['x'] += 1
    elif fault == 'bbox': candidate.refined_bbox['w'] += 1
    elif fault == 'role': candidate.role = 'button'
    elif fault == 'interaction': candidate.element.interaction_type = 'click'
    elif fault == 'label': candidate.label = 'Search users'
    elif fault == 'raw_name': uia['controls'][0]['name'] = 'Delete records'
    elif fault == 'source_id': candidate.element.evidence['screen_inventory_action']['source_id'] = 'search-button'
    elif fault == 'runtime': uia['controls'][0]['runtime_id'][-1] += 100
    elif fault == 'ocr_text': local.matched_text = 'Search users'
    elif fault == 'ocr_punctuation': local.matched_text += '!'
    elif fault == 'ocr_bbox': local.matched_text_bbox['x'] += 1
    elif fault == 'crop': local.crop_bbox['w'] = 1
    elif fault == 'sha': digest = 'f' * 64
    elif fault == 'reason': local.reasons.remove(REASON)
    elif fault == 'proof': candidate.element.evidence.pop(EVIDENCE_KEY)
    else: target = {'contract_version': 'recognition_control_target_v1', 'label': 'Search records',
                    'role': 'button', 'source_binding_sha256': 'a' * 64}
    assert not has_current_editable_control_ocr_binding(candidate, local, uia, digest, 'Search records', target)


def test_unreadable_name_rule_does_not_discard_real_symbols():
    from app.operation.recognition.editable_control_corroboration import _unreadable_name
    assert all(_unreadable_name(name) for name in (None, '', ' ', '\ufffc', '\ufffc \ufffc'))
    assert not any(_unreadable_name(name) for name in ('?', '\ufffd', '123', '\ufffcSearch', 0))


def test_field_identity_is_not_limited_to_inventory_top_k(tmp_path, monkeypatch):
    controls = [_control()]
    controls.extend(_control(control_id=f'button-{index}', name=f'Search archive {index}',
        control_type='Button', patterns=['Invoke'], runtime_id=[42, 17, index + 2],
        bbox={'x': 400, 'y': 200 + index * 20, 'w': 150, 'h': 18}) for index in range(10))
    result, _, _ = _recognize(tmp_path, monkeypatch, controls=controls)
    assert result['candidate_result']['summary']['screen_inventory_candidate_count'] == 5
    assert result['pre_click_decision']['allowed'] is True
    selected = result['candidate_result']['candidates'][0]
    assert selected['element']['evidence']['screen_inventory_action']['source_id'] == 'field-1'


def test_non_fill_direct_keeps_click_semantics_without_editable_binding(tmp_path, monkeypatch):
    from app.operation.recognition.editable_control_corroboration import EVIDENCE_KEY
    result, _, _ = _recognize(tmp_path, monkeypatch, semantic_action='open_detail')
    candidates = result['candidate_result']['candidates'] + result['candidate_result']['rejected']
    assert all(EVIDENCE_KEY not in c['element']['evidence'] for c in candidates)
    direct = next(c for c in candidates if c['candidate_id'].startswith('vista_direct_'))
    assert direct['role'] == 'button' and direct['element']['interaction_type'] == 'click'


def test_original_run28_full_tree_keeps_independent_invoke_overlap_rejection():
    from app.agent.fresh_learning_action_contracts import payload_sha256
    from app.agent.fresh_text_field import _field_uia_identity
    from app.operation.recognition.editable_control_corroboration import _current_editable_control
    run = Path(__file__).resolve().parents[1] / '.superpowers/sdd/2026-09-14-continuous-map/run-28'
    source = run / 'data/reviews/runtime_state/fresh-learning-v1/records/49cd1c2f9f34b7ac50941928abc26783759c7b8f1193f32f2da05f340f7f5820.json'
    if not source.exists():
        pytest.skip('本轮实测档案不随源码分发')
    raw = source.read_bytes()
    evidence = json.loads(json.loads(raw)['evidence_json'])
    uia = json.loads((run / 'responses/12-map-uia.json').read_text(encoding='utf-8'))['result']
    assert payload_sha256(uia) == evidence['uia']['snapshot_sha256']
    path = run / 'data/reviews/runtime_state/fresh-learning-v1/png' / (evidence['capture']['screenshot_sha256'] + '.png')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence['capture']['screenshot_sha256']
    direct = next(c for c in evidence['recognition']['result']['candidate_result']['rejected']
                  if c['candidate_id'].startswith('vista_direct_'))
    point = direct['element']['evidence']['vista_direct_point']['point']
    assert point == {'x': 102, 'y': 108}
    assert _field_uia_identity(uia, point)['bbox'] == {'x': 84, 'y': 103, 'w': 206, 'h': 24}
    assert _current_editable_control(uia, point, 'Search Google Maps') is None
    # 只在内存中移除已定位的独立重叠 Invoke 背景，证明拒绝原因而非冒充原帧成功。
    counterfactual = deepcopy(uia)
    counterfactual['controls'] = [c for c in counterfactual['controls'] if c['control_id'] != 'uia_222_group']
    assert _current_editable_control(counterfactual, point, 'Search Google Maps')['control_id'] == 'uia_240_ucc_1'
    assert source.read_bytes() == raw
