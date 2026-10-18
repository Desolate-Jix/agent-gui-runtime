"""完整 VISTA 识别入口的离线边界：合成 PNG、固定 UIA、模型点和 OCR 替身，无真实输入。"""

from copy import deepcopy

from PIL import Image
import pytest

from app.api import vision
from app.agent.live_runtime_composition import _parse_recognition
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from app.vision.schemas import ImageSize
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

TARGET = {'contract_version': 'recognition_control_target_v1', 'label': '搜索',
          'role': 'button', 'source_binding_sha256': 'a' * 64}
GOAL = '点击搜索建议面板右下角蓝色搜索按钮，查询 OpenStreetMap'


def _control(name='搜索', *, ident='search', kind='Button', x=223, y=131):
    return {'provider': 'windows_uia', 'control_id': ident, 'name': name,
        'control_type': kind, 'enabled': True, 'visible': True,
        'bbox': {'x': x, 'y': y, 'w': 95, 'h': 32},
        'patterns': ['Value'] if kind == 'Edit' else ['Invoke']}


def _run(tmp_path, monkeypatch, *, controls=None, point=None, ocr_text='搜索',
         target=TARGET, top_k=5, status='ok', metadata=None, observe_reuse=None,
         recall=None, direct=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / 'synthetic-search.png'
    Image.new('RGB', (500, 300), 'white').save(path)
    controls = [_control()] if controls is None else controls
    point = {'x': 269, 'y': 146} if point is None else point
    calls = []
    def model(**kwargs):
        calls.append(kwargs)
        return {'point': deepcopy(point), 'provider': 'synthetic-point'}
    def ocr(path):
        return OCRResult(image_path=str(path), matches=[] if ocr_text is None else [
            OCRTextMatch(text=ocr_text, score=.99,
                bbox=OCRBoundingBox(x=24, y=24, width=95, height=32))])
    monkeypatch.setattr(vision, '_call_vista_point_prompt', model)
    monkeypatch.setattr(vision.ocr_service, 'scan_image', ocr)
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(path), task='locate_element',
        goal=GOAL, provider_mode='local_grounding', agent_mode='execute', top_k=top_k,
        write_policy={'path_graph': False, 'element_memory': False, 'trace': False},
        metadata={'control_target': deepcopy(target),
            'vista_direct_grounding': {'enabled': direct, 'refine': False, 'max_edge': 1024}, **(metadata or {})})
    snapshot = {'provider': 'windows_uia', 'provider_version': 'windows_uia_provider_v1',
        'status': status, 'controls': deepcopy(controls)}
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={'vision': {'mode': 'local_grounding'}}, local_config={'model_name': 'offline'},
            image_path=path, input_image_size=ImageSize(width=500, height=300), goal=GOAL,
            observe_reuse=observe_reuse or {}, path_graph_recall=recall or {'status': 'not_requested', 'candidates': []})
    assert response.success, response
    result = response.data['result']
    _parse_recognition(result)
    return result, calls


def test_exact_target_excludes_search_word_clutter_before_ranking(tmp_path, monkeypatch):
    controls = [_control(), _control('地址和搜索栏', ident='address', kind='Edit', x=10, y=80),
        _control('清除搜索框内容', ident='clear', x=10, y=120),
        _control('设为默认搜索', ident='default', x=10, y=165),
        _control('OpenStreetMap', ident='query', kind='Edit', x=10, y=210)]
    result, calls = _run(tmp_path, monkeypatch, controls=controls)
    ranked = result['candidate_result']
    assert result['goal'] == ranked['goal'] == result['narrow_search_result']['goal'] == GOAL
    assert ranked['summary']['control_target'] == TARGET
    assert ranked['summary']['vista_direct_current_uia_identity_reconciled'] is True
    assert [c['label'] for c in ranked['candidates']] == ['搜索']
    assert len(ranked['rejected']) >= 4
    assert ranked['margin_to_second'] == ranked['candidates'][0]['score']
    assert result['pre_click_decision']['allowed'] is True
    assert len(calls) == 1 and 'button' in calls[0]['prompt'] and '搜索' in calls[0]['prompt']
    assert GOAL in calls[0]['prompt'] and TARGET['source_binding_sha256'] not in calls[0]['prompt']


@pytest.mark.parametrize('case', ['duplicate', 'duplicate_top1', 'role', 'missing', 'unavailable',
    'point_outside', 'ocr_missing', 'ocr_wrong', 'ocr_substring', 'direct_disabled', 'disabled', 'hidden'])
def test_target_never_falls_back_when_primary_evidence_disagrees(tmp_path, monkeypatch, case):
    controls = [_control()]
    args = {}
    if case.startswith('duplicate'):
        # 同名且同点仍重叠时拒绝；异框候选另由本次截图点消歧回归覆盖。
        controls.append(_control(ident='other-search'))
        if case == 'duplicate_top1':
            args['top_k'] = 1
    elif case == 'role':
        controls[0].update(control_type='Edit', patterns=['Value'])
    elif case == 'missing':
        controls = []
    elif case == 'unavailable':
        args['status'] = 'unavailable'
    elif case == 'point_outside':
        args['point'] = {'x': 180, 'y': 146}
    elif case == 'ocr_missing':
        args['ocr_text'] = None
    elif case == 'ocr_wrong':
        args['ocr_text'] = '确认'
    elif case == 'ocr_substring':
        args['ocr_text'] = '搜索设置'
    elif case == 'direct_disabled':
        args['direct'] = False
    elif case == 'disabled':
        controls[0]['enabled'] = False
    elif case == 'hidden':
        controls[0]['visible'] = False
    result, _ = _run(tmp_path, monkeypatch, controls=controls, **args)
    assert result['pre_click_decision']['allowed'] is False
    assert result['pre_click_decision']['selected_click_point'] is None
    assert result['candidate_result']['summary']['control_target'] == TARGET


@pytest.mark.parametrize('args', [
    {'observe_reuse': {'screen_inventory': {}}},
    {'recall': {'candidates': [{'label': '搜索'}]}},
    {'metadata': {'visual_asset_recall': {'matches': [{}]}}},
    {'metadata': {'seeded_candidate': {'label': '搜索', 'bbox': {'x': 1, 'y': 1, 'w': 50, 'h': 30}}}},
])
def test_target_rejects_old_inventory_or_recall_instead_of_borrowing_coordinates(tmp_path, monkeypatch, args):
    with pytest.raises(ValueError, match='fresh recognition'):
        _run(tmp_path, monkeypatch, **args)


def test_wide_actionable_role_remains_current_and_unique(tmp_path, monkeypatch):
    target = {**TARGET, 'role': 'control'}
    result, _ = _run(tmp_path, monkeypatch, target=target)
    assert result['pre_click_decision']['allowed'] is True
    result, _ = _run(tmp_path, monkeypatch, target=target, controls=[_control(),
        _control(ident='same-name-field', kind='Edit')])
    assert result['pre_click_decision']['allowed'] is False


def test_exact_target_can_distinguish_same_text_wrong_role_but_not_skip_risk(tmp_path, monkeypatch):
    result, _ = _run(tmp_path, monkeypatch, controls=[_control(),
        _control(ident='same-name-input', kind='Edit', x=10, y=210)])
    assert result['pre_click_decision']['allowed'] is True
    from app.gate.fresh_action_risk import classify_fresh_action_risk
    from tests.test_fresh_action_risk import _uia
    control = _control('确认')
    result, _ = _run(tmp_path, monkeypatch, target={**TARGET, 'label': '确认'},
        controls=[control], ocr_text='确认')
    candidates, local = _parse_recognition(result)
    assert candidates.candidates
    risk = classify_fresh_action_risk(proposed_semantic_action='open_detail', goal=GOAL,
        candidate=candidates.candidates[0], local=local.results[0], capture_id='offline.confirm',
        uia_snapshot=_uia(control))
    assert risk['hard_blocked'] is True
