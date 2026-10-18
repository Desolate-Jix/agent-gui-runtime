"""查询值和操作目标分开；保留歧义拒绝而不让视觉点绕过冲突。"""
from tests.test_native_vista_identity_reconciliation import _recognize, _control


def _search_controls():
    button = {**_control(control_id='search', name='搜索'), 'control_type': 'Button', 'patterns': ['Invoke']}
    field = {**_control(control_id='query', name='OpenStreetMap',
        bbox={'x': 10, 'y': 100, 'w': 140, 'h': 26}), 'control_type': 'ComboBox', 'patterns': ['Value']}
    suggestion = {**_control(control_id='suggestion', name='openstreetmap',
        bbox={'x': 10, 'y': 135, 'w': 160, 'h': 26}), 'control_type': 'ListItem', 'patterns': ['Invoke']}
    return [button, field, suggestion]


def test_query_operand_in_target_goal_is_rejected_instead_of_overriding_uia_conflict(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, controls=_search_controls(), target_text='',
        goal='点击搜索建议面板右下角蓝色搜索按钮，查询 OpenStreetMap', ocr_grounded=False)
    summary = result['candidate_result']['summary']
    assert summary['vista_direct_current_uia_identity_rejection'] == 'vista_direct_current_uia_identity_ambiguous'
    assert result['pre_click_decision']['allowed'] is False


def test_target_only_goal_resolves_unique_button_without_authorizing_unverified_ocr(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, controls=_search_controls(), target_text='',
        goal='搜索', ocr_grounded=False)
    summary = result['candidate_result']['summary']
    assert summary['vista_direct_current_uia_identity_reconciled'] is True
    assert summary.get('vista_direct_current_uia_identity_rejection') is None
    assert result['pre_click_decision']['allowed'] is False


def test_exact_short_label_matching_does_not_turn_substrings_or_negation_into_targets():
    from app.operation.recognition.candidate_ranker import _goal_label_match
    assert _goal_label_match('搜索', ['搜索'], negated=False)
    assert _goal_label_match('OK', ['OK'], negated=False)
    for goal in ('不要搜索', 'not OK', '搜索设置', 'book'):
        assert not _goal_label_match(goal, ['搜索', 'OK'], negated=False)
    assert not _goal_label_match('搜索', ['搜索'], negated=True)


def test_duplicate_short_labels_still_reject_before_selecting_by_model_point(tmp_path, monkeypatch):
    first = _search_controls()[0]
    second = {**first, 'control_id': 'another-search', 'bbox': {'x': 10, 'y': 100, 'w': 100, 'h': 24}}
    result = _recognize(tmp_path, monkeypatch, controls=[first, second], target_text='',
        goal='搜索', ocr_grounded=False, top_k=1)
    assert result['candidate_result']['summary']['vista_direct_current_uia_identity_rejection'] == 'vista_direct_current_uia_identity_ambiguous'
    assert result['pre_click_decision']['allowed'] is False


def test_short_confirm_label_cannot_be_authorized_by_exact_identity_match(tmp_path, monkeypatch):
    from app.agent.live_runtime_composition import _parse_recognition
    from app.gate.fresh_action_risk import classify_fresh_action_risk
    from tests.test_fresh_action_risk import _local, _uia
    control = {**_search_controls()[0], 'name': '确认'}
    result = _recognize(tmp_path, monkeypatch, controls=[control], target_text='',
        goal='确认', ocr_grounded=False)
    assert result['candidate_result']['summary']['vista_direct_current_uia_identity_reconciled'] is True
    candidates, _ = _parse_recognition(result)
    candidate = candidates.candidates[0]
    # 即便补充合成的精确局部匹配，独立危险门仍须拒绝；本测试不创建输入后端。
    local = _local(candidate)
    local.refined_click_point = {'x': 254, 'y': 41}
    local.matched_text_bbox = control['bbox']
    risk = classify_fresh_action_risk(proposed_semantic_action='open_detail', goal='确认',
        candidate=candidate, local=local, capture_id='fresh-capture.confirm', uia_snapshot=_uia(control))
    assert risk['hard_blocked'] is True
