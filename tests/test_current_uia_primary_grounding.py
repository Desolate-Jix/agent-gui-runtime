"""全新输入框应使用当前 UIA 与模型交叉定位，不依赖旧记录或框内文字。"""
from copy import deepcopy

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.api import vision as vision_api
from app.api.application import create_runtime_app
from app.agent.live_runtime_composition import _matching_pairs, _parse_recognition
from modules.ocr.contracts import OCRResult


def _control(**changes):
    result = {
        'provider': 'windows_uia', 'control_id': 'editor-1', 'name': '文本编辑器',
        'control_type': 'Edit', 'automation_id': '15', 'class_name': 'Edit',
        'bbox': {'x': 100, 'y': 100, 'w': 300, 'h': 200},
        'screen_bbox': {'x': 100, 'y': 100, 'w': 300, 'h': 200},
        'enabled': True, 'visible': True, 'patterns': ['Value', 'Text'],
    }
    result.update(changes)
    return result


def _recognize(tmp_path, monkeypatch, *, controls=None, goal='文本编辑器', raw='[500, 500]', top_k=5, status='ok', semantic_action=None):
    image_path = tmp_path / 'capture.png'
    Image.new('RGB', (600, 400), 'white').save(image_path)
    controls = [_control()] if controls is None else controls
    snapshot = {'provider': 'windows_uia', 'provider_version': 'windows_uia_provider_v1',
                'status': status, 'control_count': len(controls), 'controls': controls}
    monkeypatch.setattr(vision_api.uia_provider, 'snapshot_bound_window', lambda **_: deepcopy(snapshot))
    monkeypatch.setattr(vision_api.VisionProviderFactory, 'load_config', lambda: {
        'vision': {'mode': 'local', 'timeout_seconds': 10, 'local_grounding': {
            'model_name': 'inclusionAI/VISTA-4B', 'endpoint': 'http://127.0.0.1:1/v1/chat/completions',
            'runtime': 'transformers', 'output_contract': 'vista_point_v1',
        }},
    })
    monkeypatch.setattr(vision_api.VisionProviderFactory, 'create', lambda **_: object())
    monkeypatch.setattr(vision_api, 'VISTA_DIRECT_IMAGES_DIR', tmp_path / 'model-crops')
    monkeypatch.setattr(vision_api.ocr_service, 'scan_image', lambda path: OCRResult(image_path=str(path), matches=[]))
    calls = []

    def model(_self, path, prompt, **_kwargs):
        calls.append({'path': str(path), 'prompt': prompt})
        return {'choices': [{'message': {'content': raw}}]}

    monkeypatch.setattr(vision_api.LocalVisionProvider, '_call_openai_compatible_endpoint', model)
    with TestClient(create_runtime_app()) as client:
        response = client.post('/vision/recognition_plan', json={
            'image_path': str(image_path), 'provider_mode': 'local_grounding',
            'task': 'locate_element', 'goal': goal, 'agent_mode': 'execute', 'top_k': top_k,
            'write_policy': {'path_graph': False, 'element_memory': False, 'trace': False},
            'metadata': {'vista_direct_grounding': {'enabled': True, 'refine': False},
                         **({'semantic_action': semantic_action} if semantic_action is not None else {})},
        })
    assert response.status_code == 200, response.text
    assert response.json()['success'], response.text
    result = response.json()['data']['result']
    assert result['execution_path']['action_executed'] is False
    return result, calls


def test_new_exact_editor_is_grounded_by_current_uia_and_model_without_history(tmp_path, monkeypatch):
    result, calls = _recognize(tmp_path, monkeypatch, semantic_action='fill_field')
    assert any(g['status'] == 'grounded' for g in result['narrow_search_result']['results'])
    candidates, local = _parse_recognition(result)
    anchor = {'kind': 'control', 'label': '文本编辑器', 'text_field_id': 'editor'}
    pairs = _matching_pairs(candidates, local, anchor)
    assert len(pairs) == 1
    candidate, grounding = pairs[0]
    assert candidate.role == 'input'
    assert candidate.candidate_id == candidates.recommended_candidate_id == local.recommended_candidate_id
    assert grounding.refined_click_point == {'x': 250, 'y': 200}
    assert len(calls) == 1
    assert result['execution_path']['vista_direct_point_grounding_used'] is False
    assert result['candidate_result']['summary']['vista_roi_source'] == 'current_uia_candidate_v1'
    assert result['seeded_candidate'] is None


def test_model_disagreement_cannot_use_uia_center_as_fallback(tmp_path, monkeypatch):
    result, _ = _recognize(tmp_path, monkeypatch, raw='[0, 0]', semantic_action='fill_field')
    # 未验证候选可以用于诊断显示，但 Gate 不得选中候选或产生点击点。
    assert result['pre_click_decision']['selected_candidate_id'] is None
    assert result['pre_click_decision']['selected_click_point'] is None
    assert all(g['status'] != 'grounded' for g in result['narrow_search_result']['results'])
    assert result['pre_click_decision']['allowed'] is False


def test_model_disagreement_does_not_ground_an_unevaluated_similar_field(tmp_path, monkeypatch):
    result, _ = _recognize(tmp_path, monkeypatch, raw='[0, 0]', semantic_action='fill_field', controls=[_control(),
        _control(control_id='editor-2', automation_id='16', name='文本编辑框',
            bbox={'x': 430, 'y': 100, 'w': 120, 'h': 200},
            screen_bbox={'x': 430, 'y': 100, 'w': 120, 'h': 200})])
    assert result['pre_click_decision']['selected_candidate_id'] is None
    assert result['pre_click_decision']['selected_click_point'] is None
    assert all(g['status'] != 'grounded' for g in result['narrow_search_result']['results'])
    assert result['pre_click_decision']['allowed'] is False


@pytest.mark.parametrize('case', ['semantic_label', 'duplicate_top_k_one', 'overlapping_duplicates', 'hidden', 'disabled', 'failed_snapshot'])
def test_untrusted_or_ambiguous_editor_is_not_promoted(case, tmp_path, monkeypatch):
    options = {}
    if case == 'semantic_label':
        options['goal'] = '空白文本编辑区域'
    elif case == 'duplicate_top_k_one':
        options.update(top_k=1, controls=[_control(), _control(control_id='editor-2', automation_id='16',
            bbox={'x': 430, 'y': 100, 'w': 120, 'h': 200},
            screen_bbox={'x': 430, 'y': 100, 'w': 120, 'h': 200})])
    elif case == 'overlapping_duplicates':
        options['controls'] = [_control(), _control(control_id='editor-2', automation_id='16',
            bbox={'x': 110, 'y': 110, 'w': 300, 'h': 200},
            screen_bbox={'x': 110, 'y': 110, 'w': 300, 'h': 200})]
    elif case == 'hidden':
        options['controls'] = [_control(visible=False)]
    elif case == 'disabled':
        options['controls'] = [_control(enabled=False)]
    else:
        options['status'] = 'failed'
    result, _ = _recognize(tmp_path, monkeypatch, semantic_action='fill_field', **options)
    assert result['pre_click_decision']['selected_candidate_id'] is None
    assert result['pre_click_decision']['selected_click_point'] is None
    assert all(g['status'] != 'grounded' for g in result['narrow_search_result']['results'])
    assert result['pre_click_decision']['allowed'] is False
