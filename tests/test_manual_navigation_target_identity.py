"""手动策略仍绑定当前命中控件，不把整页同名控件当成歧义。"""
from copy import deepcopy

import pytest

from app.agent.fresh_learning_action_contracts import payload_sha256
from tests.test_automatic_safety_interception import _manual, _low_score


def _duplicate(*, overlap=False):
    data, _ = _low_score()
    data['intent'].pop('learned_control', None)
    data['observation_evidence']['recognition']['result']['candidate_result']['summary'].pop('control_target', None)
    uia = data['uia_snapshot']
    original = uia['controls'][0]
    duplicate = deepcopy(original)
    duplicate['control_id'] = 'other-same-name'
    duplicate['runtime_id'] = [42, 999]
    if not overlap:
        duplicate['bbox'] = {'x': 230, 'y': 140, 'w': 100, 'h': 30}
        duplicate['screen_bbox'] = dict(duplicate['bbox'])
    uia['controls'].append(duplicate)
    uia['control_count'] = len(uia['controls'])
    data['observation_evidence']['uia'].update(
        control_count=uia['control_count'], snapshot_sha256=payload_sha256(uia))
    return data


def test_manual_same_name_outside_selected_point_does_not_block():
    preview = _manual(_duplicate()).to_dict()
    assert preview['action_selection']['selected_click_point'] == {'x': 130, 'y': 75}


def test_manual_same_name_overlapping_selected_point_remains_ambiguous():
    with pytest.raises(ValueError, match='one identifiable current UIA control'):
        _manual(_duplicate(overlap=True))
