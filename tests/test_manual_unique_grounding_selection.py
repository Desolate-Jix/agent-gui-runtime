"""人工策略只能选择唯一完整几何证据，不以第一项或分数替代。"""
from copy import deepcopy

import pytest

from app.agent.automatic_safety_policy import action_selection
from app.operation.recognition.schemas import CandidateRankResult, LocalGroundingResult
from tests.test_fresh_action_risk import _candidate, _local


def _case():
    other = _candidate('Other', candidate_id='candidate.other')
    other.element_id = other.element.element_id = 'element.other'
    chosen = _candidate('Search')
    other.score, chosen.score = 0.99, 0.1
    first, second = _local(other), _local(chosen)
    first.status = 'point_outside_candidate'
    decision = {'allowed': False, 'selected_candidate_id': None, 'selected_element_id': None,
                'selected_click_point': None, 'reasons': ['local_ocr_text_mismatch']}
    return decision, CandidateRankResult(candidates=[other, chosen]), LocalGroundingResult(results=[first, second])


def test_only_grounded_pair_is_selected_without_rewriting_strict_advice():
    decision, candidates, local = _case()
    original = deepcopy((decision, candidates, local))
    result = action_selection(decision, candidates, local, automatic_safety_interception=False)
    assert result == {'selected_candidate_id': 'candidate.view', 'selected_element_id': 'element.view',
                      'selected_click_point': {'x': 150, 'y': 105}}
    assert (decision, candidates, local) == original
    assert decision['allowed'] is False
    result['selected_click_point']['x'] = 0
    assert local.results[1].refined_click_point['x'] == 150


@pytest.mark.parametrize('damage', ['no_grounded', 'two_grounded', 'missing_local', 'missing_candidate',
    'duplicate_local', 'duplicate_candidate', 'duplicate_element', 'wrong_element', 'wrong_embedded_element',
    'point_missing', 'point_bool', 'point_outside', 'refined_outside', 'box_missing', 'box_extra',
    'unknown_local', 'invalid_candidate', 'invalid_local'])
def test_incomplete_or_ambiguous_geometry_is_rejected(damage):
    decision, candidates, local = _case()
    if damage == 'no_grounded': local.results[1].status = 'unverified'
    elif damage == 'two_grounded': local.results[0].status = 'grounded'
    elif damage == 'missing_local': local.results.pop()
    elif damage == 'missing_candidate': candidates.candidates.pop()
    elif damage == 'duplicate_local': local.results.append(deepcopy(local.results[1]))
    elif damage == 'duplicate_candidate': candidates.candidates.append(deepcopy(candidates.candidates[1]))
    elif damage == 'duplicate_element': candidates.candidates[0].element_id = candidates.candidates[1].element_id
    elif damage == 'wrong_element': local.results[1].element_id = 'wrong'
    elif damage == 'wrong_embedded_element': candidates.candidates[1].element.element_id = 'wrong'
    elif damage == 'point_missing': local.results[1].refined_click_point = None
    elif damage == 'point_bool': local.results[1].refined_click_point['x'] = True
    elif damage == 'point_outside': local.results[1].refined_click_point['x'] = 0
    elif damage == 'refined_outside': candidates.candidates[1].refined_bbox['x'] = 200
    elif damage == 'box_missing': candidates.candidates[1].refined_bbox.pop('w')
    elif damage == 'box_extra': candidates.candidates[1].refined_bbox['extra'] = 1
    elif damage == 'unknown_local': local.results[0].candidate_id = 'unknown'
    elif damage == 'invalid_candidate': candidates.candidates[1] = {}
    else: local.results[1] = {}
    with pytest.raises(ValueError):
        action_selection(decision, candidates, local, automatic_safety_interception=False)


def test_single_candidate_manual_and_strict_behaviour_remain_compatible():
    decision, candidates, local = _case()
    candidates.candidates.pop(0)
    local.results.pop(0)
    result = action_selection(decision, candidates, local, automatic_safety_interception=False)
    assert result['selected_candidate_id'] == 'candidate.view'
    with pytest.raises(ValueError, match='pre-click gate rejected'):
        action_selection(decision, candidates, local)
    decision.update(allowed=True, **result)
    assert action_selection(decision, candidates, local) == result
    assert action_selection(decision, candidates, local, automatic_safety_interception=False) == result
