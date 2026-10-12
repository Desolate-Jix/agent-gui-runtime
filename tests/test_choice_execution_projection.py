"""主 Agent 接管包必须保留原选择与置信信息，不能变成伪造概率。"""
from copy import deepcopy
from types import SimpleNamespace

from app.execution.task_plan_review import assessment_summary, policy_snapshot


def test_choice_handoff_preserves_raw_low_confidence_without_mutating_source():
    raw = {'decision_format': 'choice', 'status': 'completed', 'verdict': 'uncertain',
        'disposition': 'review_required', 'enabled_predicates': [], 'predicates': {}, 'probabilities': {},
        'choice_result': {'type': 'choice', 'name': 'current_step', 'choice': 'evidence_insufficient',
            'confidence': .19, 'probabilities': [
                {'value': 'condition_met', 'probability': .28},
                {'value': 'condition_not_met', 'probability': .26},
                {'value': 'evidence_insufficient', 'probability': .46}]}}
    original = deepcopy(raw)
    summary = assessment_summary(raw)
    assert summary['decision_format'] == 'choice'
    assert summary['choice_result'] == raw['choice_result']
    assert summary['probabilities'] == {}
    summary['choice_result']['choice'] = 'condition_met'
    assert raw == original


def test_policy_snapshot_distinguishes_choice_from_predicate():
    status = {'contract_version': 'decision_profile.v2', 'mode': 'auto',
        'profile_sha256': 'a' * 64, 'decision_format': 'choice'}
    assert policy_snapshot(SimpleNamespace(status=lambda: status)) == status
