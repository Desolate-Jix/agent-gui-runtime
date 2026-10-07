from copy import deepcopy

import pytest

from app.learning_memory.uia_rows import resolve_uia_row, validate_visible_row_strategy
from test_workflow_uia_rows import scene


def self_scene():
    snapshot, strategy, capture, bindings = scene()
    snapshot['controls'] = [c for c in snapshot['controls'] if c['control_type'] != 'Text']
    for c in snapshot['controls']:
        if c['control_type'] == 'ListItem':
            c['name'] = 'A-1' if c['control_id'] == 'a' else 'B-2'
    strategy['properties'] = [{'property': 'record_id', 'source': 'row', 'control_type': 'ListItem', 'read': 'name'}]
    strategy['action'] = {'source': 'row', 'control_type': 'ListItem'}
    return snapshot, strategy, capture, bindings


def test_explicit_self_name_and_action_follow_current_unique_row():
    snapshot, strategy, capture, bindings = self_scene()
    assert validate_visible_row_strategy(strategy) == strategy
    result = resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)
    assert result['candidate']['action_id'] == result['candidate']['row_id'] == 'b'
    assert result['candidate']['bbox'] == snapshot['controls'][3]['bbox']
    snapshot['controls'].reverse()
    assert resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)['candidate']['action_id'] == 'b'


@pytest.mark.parametrize('mutation,reason', [('duplicate', 'visible_row_ambiguous'), ('stale', 'capture_stale'), ('bbox', 'bbox'), ('nested', 'multiple_row')])
def test_self_target_keeps_safety_gates(mutation, reason):
    snapshot, strategy, capture, bindings = self_scene()
    rows = [c for c in snapshot['controls'] if c['control_type'] == 'ListItem']
    if mutation == 'duplicate':
        rows[0]['name'] = rows[1]['name']
    elif mutation == 'stale':
        snapshot['capture_id'] = 'old'
    elif mutation == 'bbox':
        rows[1]['bbox']['x'] = 490
    else:
        rows[1]['ancestor_control_ids'].insert(0, rows[0]['control_id'])
    with pytest.raises(ValueError, match=reason):
        resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)


def test_row_source_rejects_named_action_and_wrong_type():
    _, strategy, _, _ = self_scene()
    for action in ({'source': 'row', 'control_type': 'Button'}, {'source': 'row', 'control_type': 'ListItem', 'name': 'B-2'}):
        bad = deepcopy(strategy)
        bad['action'] = action
        with pytest.raises(ValueError, match='strategy'):
            validate_visible_row_strategy(bad)


def name_scene():
    snapshot, strategy, capture, bindings = self_scene()
    strategy['action'] = {'source': 'row_name', 'control_type': 'Edit'}
    for row in list(snapshot['controls']):
        if row['control_type'] == 'ListItem':
            snapshot['controls'].append({'control_id': row['control_id'] + '-name', 'name': row['name'],
                'control_type': 'Edit', 'ancestor_control_ids': [row['control_id'], 'list'],
                'visible': True, 'enabled': True,
                'bbox': {'x': row['bbox']['x'] + 4, 'y': row['bbox']['y'], 'w': 87, 'h': row['bbox']['h']}})
    return snapshot, strategy, capture, bindings


def test_explicit_row_name_targets_current_named_child_in_multicolumn_row():
    snapshot, strategy, capture, bindings = name_scene()
    next(c for c in snapshot['controls'] if c['control_id'] == 'list')['bbox'] = {'x': 0, 'y': 40, 'w': 780, 'h': 360}
    next(c for c in snapshot['controls'] if c['control_id'] == 'b')['bbox'] = {'x': 2, 'y': 106, 'w': 760, 'h': 21}
    next(c for c in snapshot['controls'] if c['control_id'] == 'b-name')['bbox'] = {'x': 6, 'y': 106, 'w': 87, 'h': 21}
    result = resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)
    assert result['candidate']['row_id'] == 'b'
    assert result['candidate']['action_id'] == 'b-name'
    assert result['candidate']['click_point'] == {'x': 49, 'y': 116}
    assert result['candidate']['bbox']['w'] == 87
    bindings['inputs']['wanted_id'] = 'A-1'
    assert resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)['candidate']['action_id'] == 'a-name'


@pytest.mark.parametrize('mutation,reason', [('missing', 'row_action_missing'), ('duplicate', 'row_action_ambiguous'),
    ('wrong_name', 'row_action_missing'), ('nested', 'multiple_row'), ('bbox', 'bbox')])
def test_row_name_rejects_invalid_or_ambiguous_named_subregion(mutation, reason):
    snapshot, strategy, capture, bindings = name_scene()
    child = next(c for c in snapshot['controls'] if c['control_id'] == 'b-name')
    if mutation == 'missing':
        snapshot['controls'].remove(child)
    elif mutation == 'duplicate':
        duplicate = deepcopy(child)
        duplicate['control_id'] = 'duplicate-name'
        snapshot['controls'].append(duplicate)
    elif mutation == 'wrong_name':
        child['name'] = 'other'
    elif mutation == 'nested':
        child['ancestor_control_ids'].insert(0, 'a')
    else:
        child['bbox']['x'] = 480
    with pytest.raises(ValueError, match=reason):
        resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)


def test_row_name_edit_click_exception_does_not_allow_input_or_fixed_edit_click():
    from app.learning_memory.target_recipe import validate_editorial_action
    _, strategy, _, _ = name_scene()
    recipe = {'contract_version': 'target_recipe.v3', 'strategies': [strategy]}
    validate_editorial_action(recipe, {'kind': 'click', 'goal': 'Select row'})
    with pytest.raises(ValueError, match='control_type_mismatch'):
        validate_editorial_action(recipe, {'kind': 'input_sequence', 'field_goal': 'Input', 'submit_search': False})
    for selector in ({'kind': 'uia', 'control_type': 'Edit', 'name': 'Alpha'},
                     {**strategy, 'action': {'control_type': 'Edit', 'name': 'Alpha'}}):
        with pytest.raises(ValueError, match='control_type_mismatch'):
            validate_editorial_action({'contract_version': 'target_recipe.v3', 'strategies': [selector]}, {'kind': 'click', 'goal': 'Select row'})


@pytest.mark.parametrize('action_source', ['row', 'row_name'])
def test_ordinary_editor_persists_and_reopens_row_sources(tmp_path, action_source):
    from PySide6.QtWidgets import QApplication
    from app.learning_memory.workflow_target_editor import WorkflowTargetEditor
    from app.learning_memory.workflow_target_editor_service import read_target_edit_context, propose_target_edit
    from app.learning_memory.target_recipe import save_target_recipe, load_target_recipe
    from app.learning_memory.workspace import MemoryWorkspace
    from test_learning_observation_source import observation_scene
    from test_learning_action_evidence import repeated_state
    from test_workflow_target_editor_service import _draft, _FullControls
    from test_workflow_target_editor import _wait

    scene_data = observation_scene.__wrapped__(tmp_path)
    observation = scene_data[2]
    snapshot = observation['uia']['snapshot']
    snapshot.update(provider='windows_uia', provider_tree_valid=True)
    for i, c in enumerate(snapshot['controls']):
        c.update(control_id=f'original-{i}', ancestor_control_ids=[])
    snapshot['controls'].extend([
        {'control_id': 'list', 'ancestor_control_ids': [], 'name': 'Results', 'control_type': 'List',
         'bbox': {'x': 80, 'y': 20, 'w': 75, 'h': 75}, 'visible': True, 'enabled': True},
        {'control_id': 'row', 'ancestor_control_ids': ['list'], 'name': 'Alpha', 'control_type': 'ListItem',
         'bbox': {'x': 82, 'y': 25, 'w': 70, 'h': 45}, 'visible': True, 'enabled': True},
        {'control_id': 'edit', 'ancestor_control_ids': ['list', 'row'], 'name': 'Alpha', 'control_type': 'Edit',
         'bbox': {'x': 85, 'y': 28, 'w': 30, 'h': 10}, 'visible': True, 'enabled': True},
    ])
    snapshot['controls'] = _FullControls(snapshot['controls'])
    root, original = _draft(repeated_state.__wrapped__(scene_data))
    app = QApplication.instance() or QApplication([])
    action = {'kind': 'click', 'goal': 'Open row', 'target_memory': original['reference']}
    step = {'step_id': 'open', 'action': action}
    definition = {'inputs': [{'name': 'wanted', 'type': 'text'}], 'steps': [step]}

    class Facade:
        def read_target_edit_context(self, reference, proposed_recipe=None):
            with MemoryWorkspace(root) as library:
                return read_target_edit_context(library, reference, proposed_recipe=proposed_recipe)

        def propose_target_edit(self, reference, action, strategies, **kwargs):
            with MemoryWorkspace(root) as library:
                return propose_target_edit(library, reference, action, strategies, **kwargs)

    editor = WorkflowTargetEditor(Facade())
    editor.set_step(step, definition, proposed_recipes=[original['recipe']])
    editor.load_button.click()
    _wait(app, lambda: editor._context is not None and not editor.is_busy)
    editor.mode.setCurrentIndex(editor.mode.findData('visible_row'))
    editor.container.setCurrentIndex(next(i for i in range(editor.container.count()) if editor.container.itemData(i)['control_id'] == 'list'))
    editor.row_type.setCurrentIndex(editor.row_type.findData('ListItem'))
    editor.property_source.setCurrentIndex(editor.property_source.findData('row'))
    assert editor.action_source.findData(action_source) >= 0
    editor.action_source.setCurrentIndex(editor.action_source.findData(action_source))
    editor.value_source.setCurrentIndex(editor.value_source.findData('input'))
    editor.sample.setText('Alpha')
    assert editor.preview_button.isEnabled(), (editor._selector_missing, editor._editable, editor._strategies, editor.binding.currentData(), editor.property_control.currentData(), editor.row_action.currentData(), editor.status.text())
    proposals = []
    editor.proposalReady.connect(proposals.append)
    editor.preview_button.click()
    _wait(app, lambda: editor._preview_result is not None and not editor.is_busy)
    expected_box = snapshot['controls'][-2 if action_source == 'row' else -1]['bbox']
    assert editor._preview_result['preview']['candidate']['bbox'] == expected_box
    editor.apply_button.click()
    recipe = proposals[0]['result']['recipe']
    reference = proposals[0]['result']['reference']
    assert recipe['strategies'][0]['action'] == {'source': action_source, 'control_type': 'ListItem' if action_source == 'row' else 'Edit'}
    assert recipe['strategies'][0]['properties'][0]['source'] == 'row'
    with MemoryWorkspace(root) as library:
        save_target_recipe(library, recipe)
    editor.close()
    with MemoryWorkspace(root) as library:
        assert load_target_recipe(library, reference) == recipe
        context = read_target_edit_context(library, reference)
        # 原动作位于另一个控件，不能根据参数改选样例框。
        assert context['target_boxes'] == []
        from app.learning_memory.target_box_projection import project_target_boxes
        example = deepcopy(observation)
        example['candidate']['click_point'] = {'x': 90, 'y': 40}
        boxes, issues = project_target_boxes(recipe, example)
        assert not issues
        assert boxes[0]['bbox'] == [expected_box[k] for k in ('x', 'y', 'w', 'h')]
        if action_source == 'row_name':
            from app.learning_memory.workflow_target_editor_service import propose_target_box_edit
            boxed = propose_target_box_edit(library, reference, action, recipe['strategies'], 0,
                [85, 28, 10, 8], preview_inputs={'wanted': 'Alpha'})
            assert boxed['recipe']['strategies'][0]['action'] == {'source': 'row_name', 'control_type': 'Edit'}
    reopened = WorkflowTargetEditor(Facade())
    reopened.set_step({'step_id': 'open', 'action': {**action, 'target_memory': reference}}, definition)
    reopened.load_button.click()
    _wait(app, lambda: reopened._context is not None and not reopened.is_busy)
    assert reopened.property_source.currentData() == 'row'
    assert reopened.action_source.currentData() == action_source
    assert not reopened._selector_missing
    reopened.close()
