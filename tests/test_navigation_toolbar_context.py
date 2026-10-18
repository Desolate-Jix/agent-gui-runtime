"""导航复核复用通用工具栏上下文证明，不读取真实桌面。"""
from copy import deepcopy
from hashlib import sha256

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent, payload_sha256
from app.agent.fresh_learning_action_preview import (
    FreshLearningActionPreview, _decision_and_risk, validate_fresh_execution_preview,
)
from app.agent.navigation_visual_stability import NavigationVisualStabilityScope, verify_navigation_visual_stability_reference
from tests.test_navigation_visual_stability import _fixture, _rehash, _png, _current


def toolbar_fixture(*, first_learning=True):
    old, png = _fixture()
    data = old.to_dict()
    uia = data['uia_snapshot']
    target = uia['controls'][0]
    def control(cid, kind, box, ancestors, rid, name):
        bbox = dict(zip(('x', 'y', 'w', 'h'), box))
        return dict(provider='windows_uia', control_id=cid, control_type=kind, name=name,
            automation_id=cid, class_name='Synthetic', bbox=bbox, screen_bbox=deepcopy(bbox),
            enabled=True, visible=True, patterns=['Invoke'] if kind == 'Button' else [],
            runtime_id=rid, ancestor_control_ids=ancestors)
    original = control(target['control_id'], 'Button', (80,60,100,30), ['context','root'], target['runtime_id'], target['name'])
    uia['controls'] = [
        control('root', 'Window', (0,0,360,260), [], [42,1], 'Test'),
        control('context', 'Group', (0,0,240,140), ['root'], [42,2], 'Content'),
        original,
        control('toolbar', 'ToolBar', (0,210,360,40), ['root'], [42,3], 'Tools'),
        control('counter', 'Button', (290,215,40,30), ['toolbar','root'], [42,4], 'Counter 24'),
    ]
    uia.update(control_count=5, scan_complete=True, truncated=False, truncation_reason=None,
               scan_budget=1000, scan_visited_count=5)
    uia['window'].update(process_name='demo.exe', title='Test')
    evidence = data['observation_evidence']
    evidence['uia'].update(control_count=5, snapshot_sha256=payload_sha256(uia))
    if first_learning:
        data['contract_version'] = 'fresh_learning_action_preview_v1'
        data['intent'].pop('learned_control')
        evidence['recognition']['result']['candidate_result']['summary'].pop('control_target')
    intent = FreshLearningIntent.from_dict(data['intent'])
    data['pre_click_decision'], data['risk'] = _decision_and_risk(evidence, uia, intent,
        require_control_target=not first_learning)
    before = FreshLearningActionPreview.from_dict(_rehash(data))
    after = before.to_dict()
    changed_png = _png([(300,220)])
    after['observation_evidence'] = _current(before, changed_png)
    after['uia_snapshot']['controls'][-1]['name'] = 'Counter 25'
    after['observation_evidence']['uia']['snapshot_sha256'] = payload_sha256(after['uia_snapshot'])
    after['capture_source']['source_id'] = 'e' * 64
    after['pre_click_decision'], after['risk'] = _decision_and_risk(
        after['observation_evidence'], after['uia_snapshot'], intent, require_control_target=not first_learning)
    return before, FreshLearningActionPreview.from_dict(_rehash(after)), png, changed_png


@pytest.mark.parametrize('first_learning', [False, True])
def test_toolbar_context_proof_is_recomputed_for_exact_navigation(first_learning):
    before, after, png, changed = toolbar_fixture(first_learning=first_learning)
    original, current = before.to_dict(), after.to_dict()
    scope = NavigationVisualStabilityScope(before, png)
    with pytest.raises(ValueError):
        validate_fresh_execution_preview(before, after)
    proof = scope.validate(current_evidence=current['observation_evidence'], current_png_bytes=changed,
                           current_uia_snapshot=current['uia_snapshot'])
    reference = proof.to_reference()
    assert reference['contract_version'] == 'navigation_visual_stability_attestation_v2'
    assert reference['uia_stability']['changes'][0]['control_id'] == 'counter'
    validate_fresh_execution_preview(before, after, navigation_visual_proof=proof)
    verify_navigation_visual_stability_reference(reference, original['observation_evidence'],
        current['observation_evidence'], scope.expectation_reference, png, changed)
    tampered = deepcopy(reference)
    tampered['current_uia_snapshot']['controls'][-1]['name'] = 'Counter forged'
    with pytest.raises(ValueError):
        verify_navigation_visual_stability_reference(tampered, original['observation_evidence'],
            current['observation_evidence'], scope.expectation_reference, png, changed)


def test_changed_uia_requires_full_current_tree():
    before, after, png, changed = toolbar_fixture()
    with pytest.raises(ValueError, match='current context proof'):
        NavigationVisualStabilityScope(before, png).validate(
            current_evidence=after.to_dict()['observation_evidence'], current_png_bytes=changed)


def test_first_learning_disambiguation_preserves_goal_match_set_not_only_selected_label():
    from app.agent.fresh_learning_action_preview import _normalize_navigation_disambiguation
    before, _, _, _ = toolbar_fixture()
    data = before.to_dict()
    selected = data['uia_snapshot']['controls'][2]
    other = deepcopy(selected)
    other.update(control_id='related-details', name='details', bbox={'x':250,'y':120,'w':60,'h':20})
    data['uia_snapshot']['controls'].append(other)
    target = {'label': selected['name'], 'role':'button', 'control_id':selected['control_id']}
    point = {'x':130,'y':75}
    candidate = {'element':{'evidence':{'current_uia_point_disambiguation':{
        'source':'current_screenshot_vista_point_and_uia_bbox_v1',
        'screenshot_sha256':data['observation_evidence']['capture']['screenshot_sha256'],
        'point':point.copy(), 'selected_control_id':selected['control_id'],
        'excluded_control_ids':['related-details'], 'matching_control_count':2}}}}
    bad = deepcopy(candidate)
    bad['element']['evidence']['current_uia_point_disambiguation']['excluded_control_ids'] = []
    with pytest.raises(ValueError):
        _normalize_navigation_disambiguation(bad, data, point, target, direct=True)
    _normalize_navigation_disambiguation(candidate, data, point, target, direct=True)
