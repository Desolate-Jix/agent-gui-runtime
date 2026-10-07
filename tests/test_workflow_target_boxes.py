"""目标框必须转为原动作截图上的可执行语义。"""
from copy import deepcopy

import pytest

from app.learning_memory import workflow_target_editor_service as service
from app.learning_memory.target_recipe import save_target_recipe, load_target_recipe
from app.learning_memory.workspace import MemoryWorkspace
from test_learning_action_evidence import repeated_state
from test_learning_observation_source import observation_scene
from test_workflow_target_editor_service import _draft, row_state, _FullControls
from app.learning_memory.target_box_projection import project_target_boxes


def test_read_projects_full_control_and_edit_reopens_new_rule(repeated_state):
    root, original = _draft(repeated_state)
    with MemoryWorkspace(root) as library:
        context = service.read_target_edit_context(library, original['reference'], proposed_recipe=original['recipe'])
        box = context['target_boxes'][0]
        assert box['bbox'] == [35, 25, 30, 20]
        assert box['region_id'] == 'strategy-0'
        result = service.propose_target_box_edit(library, original['reference'],
            {'kind': 'click', 'goal': 'Other action'}, original['recipe']['strategies'], 0,
            [105, 28, 20, 10], proposed_recipe=original['recipe'])
        assert result['selected_control_bbox'] == [100, 25, 40, 20]
        assert result['preview']['candidate']['bbox'] == {'x': 100, 'y': 25, 'w': 40, 'h': 20}
        save_target_recipe(library, original['recipe'])
        save_target_recipe(library, result['recipe'])
        assert load_target_recipe(library, original['reference']) == original['recipe']
        assert load_target_recipe(library, result['reference'])['strategies'][0]['name'] == 'Other action'


@pytest.mark.parametrize('box', [[-1, 25, 5, 5], [155, 95, 10, 10], [1, 60, 5, 5], [35, 25, 105, 20]])
def test_invalid_or_multiple_target_box_rejected(repeated_state, box):
    root, original = _draft(repeated_state)
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError, match='target_box_'):
            service.propose_target_box_edit(library, original['reference'], {'kind': 'click', 'goal': 'Choose'},
                original['recipe']['strategies'], 0, box, proposed_recipe=original['recipe'])


def test_row_box_preserves_dynamic_conditions_and_requires_matching_preview(tmp_path):
    root, original = _draft(row_state(tmp_path))
    rule = {'kind': 'visible_row', 'container': {'name': 'Results', 'control_type': 'List'},
        'row': {'control_type': 'ListItem'},
        'properties': [{'property': 'title', 'control_type': 'Text', 'read': 'name'}],
        'constraints': [{'property': 'title', 'operator': 'eq', 'value': {'source': 'input', 'name': 'wanted'}}],
        'action': {'name': 'Open', 'control_type': 'Button'}}
    before = deepcopy(rule)
    with MemoryWorkspace(root) as library:
        result = service.propose_target_box_edit(library, original['reference'], {'kind': 'click', 'goal': 'Open'},
            [rule], 0, [123, 53, 20, 10], proposed_recipe=original['recipe'], preview_inputs={'wanted': 'Alpha'})
        assert result['recipe']['strategies'] == [before]
        assert rule == before
        assert result['preview']['status'] == 'matched'
        with pytest.raises(ValueError, match='target_box_preview_not_matched'):
            service.propose_target_box_edit(library, original['reference'], {'kind': 'click', 'goal': 'Open'},
                [rule], 0, [123, 53, 20, 10], proposed_recipe=original['recipe'])
        context = service.read_target_edit_context(library, result['reference'], proposed_recipe=result['recipe'])
        assert context['target_boxes'] == []
        assert context['box_issues']


def test_overlapping_executable_controls_rejected(tmp_path):
    scene = observation_scene.__wrapped__(tmp_path)
    scene[2]['uia']['snapshot']['controls'].append({'control_id': 'overlap', 'ancestor_control_ids': [],
        'name': 'Overlap', 'control_type': 'Button', 'visible': True, 'enabled': True,
        'bbox': {'x': 110, 'y': 28, 'w': 20, 'h': 10}})
    root, original = _draft(repeated_state.__wrapped__(scene))
    with MemoryWorkspace(root) as library:
        with pytest.raises(ValueError, match='target_box_ambiguous'):
            service.propose_target_box_edit(library, original['reference'], {'kind': 'click', 'goal': 'Choose'},
                original['recipe']['strategies'], 0, [112, 30, 10, 5], proposed_recipe=original['recipe'])


def test_row_projection_is_only_original_example_and_not_constraint_verdict(tmp_path):
    state = row_state(tmp_path, compound=True)
    observation = deepcopy(state[4][1])
    control = next(c for c in observation['uia']['snapshot']['controls'] if c['control_id'] == 'open-b')
    observation['candidate']['click_point'] = {'x': 130, 'y': 80}
    observation['candidate']['bbox'] = control['bbox']
    rule = {'kind': 'visible_row', 'container': {'name': 'Results', 'control_type': 'List'},
        'row': {'control_type': 'ListItem'}, 'action': {'name': 'Open', 'control_type': 'Button'},
        'properties': [], 'constraints': []}
    boxes, issues = project_target_boxes({'strategies': [rule]}, observation)
    assert issues == []
    assert boxes[0]['bbox'] == [120, 75, 30, 14]
    assert boxes[0]['meaning'] == 'learning_example'
    duplicate = deepcopy(control)
    duplicate['control_id'] = 'duplicate'
    observation['uia']['snapshot']['controls'].append(duplicate)
    boxes, issues = project_target_boxes({'strategies': [rule]}, observation)
    assert boxes == [] and issues[0]['reason'] == 'target_box_control_not_unique'


def test_row_box_switches_action_without_pinning_dynamic_row(tmp_path):
    scene = observation_scene.__wrapped__(tmp_path)
    controls = scene[2]['uia']['snapshot']['controls']
    for index, control in enumerate(controls):
        control.update(control_id=f'old-{index}', ancestor_control_ids=[])
    scene[2]['uia']['snapshot'].update(provider='windows_uia', provider_tree_valid=True)
    controls.extend([
        {'control_id': 'list', 'ancestor_control_ids': [], 'name': 'Results', 'control_type': 'List',
         'bbox': {'x': 85, 'y': 20, 'w': 70, 'h': 70}, 'visible': True, 'enabled': True},
        {'control_id': 'row', 'ancestor_control_ids': ['list'], 'name': '', 'control_type': 'ListItem',
         'bbox': {'x': 90, 'y': 22, 'w': 60, 'h': 65}, 'visible': True, 'enabled': True},
        {'control_id': 'title', 'ancestor_control_ids': ['list', 'row'], 'name': 'Alpha', 'control_type': 'Text',
         'bbox': {'x': 92, 'y': 47, 'w': 20, 'h': 8}, 'visible': True, 'enabled': True},
        {'control_id': 'open', 'ancestor_control_ids': ['list', 'row'], 'name': 'Open', 'control_type': 'Button',
         'automation_id': 'row-specific-open', 'bbox': {'x': 100, 'y': 60, 'w': 40, 'h': 20}, 'visible': True, 'enabled': True},
        {'control_id': 'alternate', 'ancestor_control_ids': ['list', 'row'], 'name': 'Alternate', 'control_type': 'Button',
         'automation_id': 'row-specific-alternate', 'bbox': {'x': 92, 'y': 60, 'w': 6, 'h': 20}, 'visible': True, 'enabled': True}])
    scene[2]['uia']['snapshot']['controls'] = _FullControls(controls)
    root, original = _draft(repeated_state.__wrapped__(scene))
    with MemoryWorkspace(root) as library:
        context = service.read_target_edit_context(library, original['reference'], proposed_recipe=original['recipe'])
        # 此控件没有行祖先，不能仅凭几何归属动态行。
        rule = {'kind': 'visible_row', 'container': {'name': 'Results', 'control_type': 'List'},
            'row': {'control_type': 'ListItem'},
            'properties': [{'property': 'title', 'control_type': 'Text', 'read': 'name'}],
            'constraints': [{'property': 'title', 'operator': 'eq', 'value': {'source': 'input', 'name': 'wanted'}}],
            'action': {'name': 'Open', 'control_type': 'Button'}}
        with pytest.raises(ValueError, match='target_box_row_control_not_unique'):
            service.propose_target_box_edit(library, original['reference'], {'kind': 'click', 'goal': 'Other'},
                [rule], 0, [105, 28, 20, 10], proposed_recipe=original['recipe'], preview_inputs={'wanted': 'Alpha'})
        result = service.propose_target_box_edit(library, original['reference'], {'kind': 'click', 'goal': 'Alternate'},
            [rule], 0, [93, 65, 3, 10], proposed_recipe=original['recipe'], preview_inputs={'wanted': 'Alpha'})
        assert result['recipe']['strategies'][0]['action'] == {'name': 'Alternate', 'control_type': 'Button'}
        assert 'automation_id' not in result['recipe']['strategies'][0]['action']
        assert result['preview']['candidate']['bbox'] == {'x': 92, 'y': 60, 'w': 6, 'h': 20}
        assert result['recipe']['strategies'][0]['constraints'] == rule['constraints']
