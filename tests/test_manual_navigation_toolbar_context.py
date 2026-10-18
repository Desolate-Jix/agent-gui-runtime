"""人工策略模式复用同一工具栏上下文证明，不放宽当前目标身份。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.fresh_learning_action_preview import (
    FreshLearningActionPreview, validate_fresh_execution_preview,
    validate_navigation_execution_equivalence,
)
from app.agent.navigation_visual_stability import (
    NavigationVisualStabilityScope, verify_navigation_visual_stability_reference,
)
from tests.test_automatic_safety_interception import _manual
from tests.test_navigation_toolbar_context import toolbar_fixture


def _case():
    before, after, png, changed = toolbar_fixture()
    return _manual(before.to_dict()), _manual(after.to_dict()), png, changed


def test_manual_toolbar_counter_requires_typed_proof_and_reopens():
    before, after, png, changed = _case()
    original, current = before.to_dict(), after.to_dict()
    scope = NavigationVisualStabilityScope(before, png)
    with pytest.raises(ValueError):
        validate_fresh_execution_preview(before, after)
    proof = scope.validate(current['observation_evidence'], changed, current['uia_snapshot'])
    reference = proof.to_reference()
    assert reference['contract_version'] == 'navigation_visual_stability_attestation_v2'
    assert reference['policy'] == 'manual_pixels_observation_v1'
    assert reference['uia_stability']['changes'][0]['control_id'] == 'counter'
    reopened = FreshLearningActionPreview.from_dict(json.loads(json.dumps(current)))
    validate_fresh_execution_preview(before, reopened, navigation_visual_proof=proof)
    verify_navigation_visual_stability_reference(reference, original['observation_evidence'],
        current['observation_evidence'], scope.expectation_reference, png, changed)
    assert current['uia_snapshot']['controls'][-1]['name'] == 'Counter 25'
    tampered = deepcopy(reference)
    tampered['current_uia_snapshot']['controls'][-1]['name'] = 'Forged'
    with pytest.raises(ValueError):
        verify_navigation_visual_stability_reference(tampered, original['observation_evidence'],
            current['observation_evidence'], scope.expectation_reference, png, changed)


def test_manual_counter_without_current_tree_is_rejected():
    before, after, png, changed = _case()
    with pytest.raises(ValueError, match='current context proof'):
        NavigationVisualStabilityScope(before, png).validate(after.to_dict()['observation_evidence'], changed)


def test_manual_context_without_native_runtime_identity_fails_explicitly():
    before, after, png, changed = _case()
    previews = []
    for preview in (before, after):
        data = preview.to_dict()
        data['uia_snapshot']['controls'][2].pop('runtime_id')
        data['observation_evidence']['uia']['snapshot_sha256'] = payload_sha256(data['uia_snapshot'])
        previews.append(_manual(data))
    before, after = previews
    with pytest.raises(ValueError, match='runtime identity'):
        NavigationVisualStabilityScope(before, png).validate(
            after.to_dict()['observation_evidence'], changed, after.to_dict()['uia_snapshot'])


@pytest.mark.parametrize('change', ['target_runtime', 'target_bbox', 'toolbar_bbox', 'counter_role',
    'counter_patterns', 'target_danger', 'content_name', 'incomplete', 'point_outside'])
def test_manual_context_does_not_accept_other_uia_changes(change):
    before, after, png, changed = _case()
    data = after.to_dict()
    controls = data['uia_snapshot']['controls']
    if change == 'target_runtime': controls[2]['runtime_id'] = [42, 99]
    elif change == 'target_bbox':
        controls[2]['bbox']['w'] += 1
        controls[2]['screen_bbox']['w'] += 1
    elif change == 'toolbar_bbox': controls[3]['bbox']['w'] -= 1
    elif change == 'counter_role': controls[-1]['control_type'] = 'Edit'
    elif change == 'counter_patterns': controls[-1]['patterns'] = ['Invoke', 'Value']
    elif change == 'target_danger': controls[2]['name'] = 'Confirm payment'
    elif change == 'content_name': controls[1]['name'] = 'Changed content'
    elif change == 'incomplete': data['uia_snapshot']['scan_complete'] = False
    else:
        data['observation_evidence']['recognition']['result']['narrow_search_result']['results'][0]['refined_click_point'] = {'x': 0, 'y': 0}
    data['observation_evidence']['uia']['snapshot_sha256'] = payload_sha256(data['uia_snapshot'])
    with pytest.raises(ValueError):
        current = _manual(data)
        proof = NavigationVisualStabilityScope(before, png).validate(
            current.to_dict()['observation_evidence'], changed, data['uia_snapshot'])
        validate_fresh_execution_preview(before, current, navigation_visual_proof=proof)


def test_manual_context_keeps_original_policy_rejection_as_warning():
    from app.operation.recognition.schemas import ScoreBreakdown
    before, after, png, changed = _case()
    previews = []
    for item in (before, after):
        data = item.to_dict()
        candidate = data['observation_evidence']['recognition']['result']['candidate_result']['candidates'][0]
        breakdown = ScoreBreakdown(text_similarity=1)
        candidate.update(score=breakdown.total(), score_breakdown=breakdown.to_dict())
        previews.append(_manual(data))
    before, after = previews
    assert before.to_dict()['pre_click_decision']['allowed'] is False
    assert after.to_dict()['automatic_safety_report']['would_block'] is True
    proof = NavigationVisualStabilityScope(before, png).validate(
        after.to_dict()['observation_evidence'], changed, after.to_dict()['uia_snapshot'])
    validate_fresh_execution_preview(before, after, navigation_visual_proof=proof)


def test_run47_counter_only_trace_replays_existing_context_policy():
    path = Path(__file__).resolve().parents[1] / '.superpowers/sdd/2026-09-14-continuous-map/run-47/faults/preview-validation-137868871666900.json'
    if not path.is_file():
        pytest.skip('Local run47 incident trace is not distributed')
    trace = json.loads(path.read_text(encoding='utf-8'))
    validate_navigation_execution_equivalence(trace['approved'], trace['current'])
