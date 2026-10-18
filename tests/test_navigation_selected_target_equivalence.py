"""多候选导航仅归一唯一选中项，其他候选证据仍完整参与比较。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.fresh_learning_action_preview import (
    FreshLearningActionPreview, _decision_and_risk, validate_navigation_execution_equivalence,
)
from app.operation.recognition.schemas import ScoreBreakdown
from tests.test_native_icon_grounding import _icon_preview
from tests.test_navigation_visual_stability import _rehash


def _finish(data):
    decision, risk = _decision_and_risk(data['observation_evidence'], data['uia_snapshot'],
        FreshLearningIntent.from_dict(data['intent']))
    data.update(pre_click_decision=decision, risk=risk)
    return FreshLearningActionPreview.from_dict(_rehash(data)).to_dict()


def _multiple(*, generation=0, selected_first=True, source='native'):
    if source == 'native':
        preview, _ = _icon_preview(generation=generation)
        data = preview.to_dict()
    else:
        from tests.test_control_ocr_consumers import _case
        data, _ = _case()
        data['observation_evidence']['capture'].update(capture_id=f'ocr-{generation}',
            capture_started_ns=100+generation*100, captured_at_ns=110+generation*100,
            observed_at_ns=140+generation*100)
    recognition = data['observation_evidence']['recognition']['result']
    candidate = deepcopy(recognition['candidate_result']['candidates'][0])
    candidate.update(candidate_id='candidate-other', element_id='element-other',
                     label='Other navigation', text='Other navigation')
    breakdown = (ScoreBreakdown(confidence_score=0.1) if selected_first else
                 ScoreBreakdown(text_similarity=1, role_score=1, policy_score=1,
                                confidence_score=1, screen_reading_score=1, state_score=1))
    candidate.update(score=breakdown.total(), score_breakdown=breakdown.to_dict())
    candidate['element'].update(element_id='element-other', label='Other navigation',
                                text='Other navigation', evidence={})
    local = deepcopy(recognition['narrow_search_result']['results'][0])
    local.update(candidate_id='candidate-other', element_id='element-other', status='point_outside_candidate',
                 coordinate_source='vista_point_v1', reasons=['point_outside_candidate'],
                 matched_text=None, matched_text_bbox=None)
    recognition['candidate_result']['candidates'].append(candidate)
    recognition['candidate_result']['margin_to_second'] = 0.8
    recognition['narrow_search_result']['results'].append(local)
    if not selected_first:
        recognition['candidate_result']['candidates'].reverse()
        recognition['narrow_search_result']['results'].reverse()
    for rank, item in enumerate(recognition['candidate_result']['candidates'], 1):
        item['rank'] = rank
    recognition['candidate_result']['recommended_candidate_id'] = recognition['candidate_result']['candidates'][0]['candidate_id']
    return _finish(data)


@pytest.mark.parametrize('selected_first', [True, False])
@pytest.mark.parametrize('source', ['native', 'ocr'])
def test_multiple_candidates_keep_one_selected_target(selected_first, source):
    before = _multiple(selected_first=selected_first, source=source)
    after = _multiple(generation=1, selected_first=selected_first, source=source)
    validate_navigation_execution_equivalence(before, after)


@pytest.mark.parametrize('change', ['candidate', 'local', 'competition'])
def test_unselected_changes_are_not_discarded(change):
    before = _multiple()
    after = _multiple(generation=1)
    recognition = after['observation_evidence']['recognition']['result']
    if change == 'candidate':
        recognition['candidate_result']['candidates'][1]['element']['description'] = 'Changed description'
    elif change == 'local':
        recognition['narrow_search_result']['results'][1]['reasons'].append('changed_evidence')
    else:
        breakdown = ScoreBreakdown(confidence_score=0.2)
        recognition['candidate_result']['candidates'][1].update(
            score=breakdown.total(), score_breakdown=breakdown.to_dict())
    after = _finish(after)
    with pytest.raises(ValueError, match='drifted'):
        validate_navigation_execution_equivalence(before, after)


@pytest.mark.parametrize('part', ['candidates', 'local', 'decisions'])
@pytest.mark.parametrize('change', ['duplicate', 'missing', 'wrong_element'])
def test_selected_triplet_rejects_ambiguous_or_missing_identity(part, change):
    from app.agent.fresh_learning_action_preview import _selected_navigation_triplet
    data = _multiple()
    recognition = data['observation_evidence']['recognition']['result']
    items = {'candidates': recognition['candidate_result']['candidates'],
             'local': recognition['narrow_search_result']['results'],
             'decisions': data['pre_click_decision']['candidate_decisions']}[part]
    if change == 'duplicate':
        items.append(deepcopy(items[0]))
    elif change == 'missing':
        items.pop(0)
    else:
        items[0]['element_id'] = 'wrong-element'
    with pytest.raises(ValueError, match='one exact selected target'):
        _selected_navigation_triplet(data)


def test_run45_trace_keeps_all_three_candidates():
    trace = Path(__file__).resolve().parents[1] / '.superpowers/sdd/2026-09-14-continuous-map/run-45/faults/preview-validation-137222176752300.json'
    if not trace.is_file():
        pytest.skip('Local run45 incident trace is not distributed')
    data = json.loads(trace.read_text(encoding='utf-8'))
    for side in ('approved', 'current'):
        FreshLearningActionPreview.from_dict(data[side])
        assert len(data[side]['observation_evidence']['recognition']['result']['candidate_result']['candidates']) == 3
    validate_navigation_execution_equivalence(data['approved'], data['current'])
