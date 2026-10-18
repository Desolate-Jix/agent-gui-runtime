from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image

from app.learning_memory.target_recipe_proposal import propose_target_recipe
from app.learning_memory.uia_rows import resolve_uia_row
from test_target_recipe_proposal import fixture
from test_workflow_uia_rows import scene


def native_scene(tmp_path):
    event, observation, bindings = fixture(tmp_path)
    snapshot, _, capture, _ = scene()
    controls = snapshot['controls']
    controls[:] = [c for c in controls if c['control_type'] != 'Text']
    for c in controls:
        if c['control_type'] == 'ListItem':
            c['name'] = 'fresh-alpha' if c['control_id'] == 'a' else 'fresh-beta'
            controls.append({'control_id': c['control_id'] + '-name', 'name': c['name'], 'control_type': 'Edit',
                'bbox': {'x': c['bbox']['x'] + 4, 'y': c['bbox']['y'], 'w': 94, 'h': c['bbox']['h']},
                'ancestor_control_ids': [c['control_id'], 'list'], 'visible': True, 'enabled': True})
    controls.append({'control_id': 'heading', 'name': 'Name', 'control_type': 'HeaderItem', 'automation_id': 'heading',
        'bbox': {'x': 20, 'y': 20, 'w': 94, 'h': 20}, 'ancestor_control_ids': ['list'], 'visible': True, 'enabled': True})
    snapshot['controls'] = controls
    Image.new('RGB', (800, 600), 'white').save(observation['frame']['image_path'])
    digest = sha256(Path(observation['frame']['image_path']).read_bytes()).hexdigest()
    observation['frame'].update(capture_id=capture['capture_id'], window_identity=capture['window_identity'],
        image_size=capture['image_size'], window_rect=[0, 0, 800, 600], sha256=digest)
    event['before'].update(capture_id=capture['capture_id'], sha256=digest)
    bindings['interface']['source']['screenshot_sha256'] = digest
    observation['uia'] = {'status': 'ok', 'capture_id': capture['capture_id'], 'window_identity': capture['window_identity'], 'snapshot': snapshot}
    observation['candidate'] = {'capture_id': capture['capture_id'], 'viewport_size': capture['image_size'],
        'source': 'agent_visual', 'freshness': 'current_capture', 'bbox': {'x': 24, 'y': 50, 'w': 80, 'h': 40},
        'click_point': {'x': 64, 'y': 70}}
    return event, observation, bindings


def test_native_proposal_preserves_explicit_name_relation_and_current_child(tmp_path):
    event, observation, bindings = native_scene(tmp_path)
    proposal = propose_target_recipe(event=event, observation=observation, bindings=bindings)
    assert proposal['recipe'] is not None, proposal['unresolved_items']
    recipe = proposal['recipe']
    rule = recipe['strategies'][0]
    assert rule['kind'] == 'visible_row'
    assert rule['action'] == {'source': 'row_name', 'control_type': 'Edit'}
    assert rule['properties'][0]['source'] == 'row'
    assert rule['constraints'][0]['value'] == {'source': 'constant', 'value': 'fresh-alpha'}
    assert recipe['scope']['anchors'][0]['control_type'] == 'HeaderItem'
    rule['constraints'][0]['value'] = {'source': 'input', 'name': 'wanted'}
    capture = {k: deepcopy(observation['frame'][k]) for k in ('capture_id', 'window_identity', 'image_size', 'sha256')}
    capture['run_id'] = 'reuse'
    result = resolve_uia_row(observation['uia']['snapshot'], rule, capture=capture,
        bindings={'run_id': 'reuse', 'inputs': {'wanted': 'fresh-beta'}, 'outputs': {}})
    assert result['candidate']['action_id'] == 'b-name'
    assert result['candidate']['bbox']['w'] == 94


@pytest.mark.parametrize('mutation', ['duplicate_row', 'duplicate_child', 'wrong_ancestor', 'stale', 'bbox',
    'no_tree', 'incomplete', 'no_anchor', 'double', 'ordinary_edit', 'ambiguous_fixed'])
def test_native_proposal_rejects_invalid_evidence_and_does_not_escape_fixed_ambiguity(tmp_path, mutation):
    event, observation, bindings = native_scene(tmp_path)
    snapshot = observation['uia']['snapshot']
    controls = snapshot['controls']
    row = next(c for c in controls if c['control_id'] == 'a')
    child = next(c for c in controls if c['control_id'] == 'a-name')
    if mutation == 'duplicate_row':
        next(c for c in controls if c['control_id'] == 'b')['name'] = row['name']
        next(c for c in controls if c['control_id'] == 'b-name')['name'] = row['name']
    elif mutation == 'duplicate_child':
        controls.append({**deepcopy(child), 'control_id': 'second-name'})
    elif mutation == 'wrong_ancestor':
        child['ancestor_control_ids'] = ['a', 'b', 'list']
    elif mutation == 'stale':
        snapshot['capture_id'] = 'old'
    elif mutation == 'bbox':
        child['bbox']['x'] = 440
    elif mutation == 'no_tree':
        snapshot['provider_tree_valid'] = False
    elif mutation == 'incomplete':
        snapshot['scan_complete'] = False
    elif mutation == 'no_anchor':
        controls[:] = [c for c in controls if c['control_type'] != 'HeaderItem']
    elif mutation == 'double':
        bindings['action']['click_kind'] = event['action_hints']['click_kind'] = 'double'
    elif mutation == 'ordinary_edit':
        controls[:] = [c for c in controls if c['control_type'] not in {'List', 'ListItem'}]
        child['ancestor_control_ids'] = []
    else:
        for i in range(2):
            controls.append({**deepcopy(child), 'control_id': f'button-{i}', 'name': f'button-{i}', 'control_type': 'Button'})
    try:
        proposal = propose_target_recipe(event=event, observation=observation, bindings=bindings)
    except ValueError:
        return
    assert proposal['recipe'] is None


@pytest.mark.parametrize('mutation', ['constraint', 'container', 'parameterized', 'point', 'child', 'anchor', 'candidate_stale'])
def test_captured_native_proof_rejects_rehashed_strategy_or_evidence_changes(tmp_path, mutation):
    from app.learning_memory.action_evidence import validate_captured_rule
    from app.learning_memory.target_recipe import action_semantics_sha256
    event, observation, bindings = native_scene(tmp_path)
    recipe = propose_target_recipe(event=event, observation=observation, bindings=bindings)['recipe']
    source = {'event': event, 'observation': observation}
    validate_captured_rule(recipe, source)
    rule = recipe['strategies'][0]
    if mutation == 'constraint':
        rule['constraints'][0]['value']['value'] = 'fresh-beta'
    elif mutation == 'container':
        rule['container']['name'] = 'Other list'
    elif mutation == 'parameterized':
        rule['constraints'][0]['value'] = {'source': 'input', 'name': 'wanted'}
    elif mutation == 'point':
        observation['candidate']['click_point']['x'] = 400
    elif mutation == 'child':
        next(c for c in observation['uia']['snapshot']['controls'] if c['control_id'] == 'a-name')['name'] = 'other'
    elif mutation == 'anchor':
        recipe['scope']['anchors'][0]['name'] = 'Missing heading'
    else:
        observation['candidate']['capture_id'] = 'old'
    recipe['action_semantics_sha256'] = action_semantics_sha256(bindings['action'], scope=recipe['scope'], strategies=recipe['strategies'])
    with pytest.raises(ValueError):
        validate_captured_rule(recipe, source)


def test_native_relation_reaches_real_compiler_and_ordinary_editor_preview(tmp_path):
    from PySide6.QtWidgets import QApplication
    from app.learning_memory.workspace import MemoryWorkspace
    from app.learning_memory.workflow_target_editor import WorkflowTargetEditor
    from app.learning_memory.workflow_target_editor_service import read_target_edit_context, propose_target_edit
    from test_learning_observation_source import observation_scene
    from test_learning_action_evidence import repeated_state
    from test_workflow_target_editor_service import _draft, _FullControls
    from test_workflow_target_editor import _wait

    fresh = observation_scene.__wrapped__(tmp_path)
    snapshot = fresh[2]['uia']['snapshot']
    snapshot.update(provider='windows_uia', provider_tree_valid=True)
    snapshot['controls'][0].update(control_id='heading', ancestor_control_ids=[], control_type='HeaderItem')
    snapshot['controls'][1].update(control_id='name-child', ancestor_control_ids=['row', 'list'], control_type='Edit')
    snapshot['controls'].extend([
        {'control_id': 'list', 'name': None, 'automation_id': 'fresh-list', 'control_type': 'List',
         'ancestor_control_ids': [], 'visible': True, 'enabled': True, 'bbox': {'x': 30, 'y': 20, 'w': 125, 'h': 70}},
        {'control_id': 'row', 'name': 'Search', 'control_type': 'ListItem', 'ancestor_control_ids': ['list'],
         'visible': True, 'enabled': True, 'bbox': {'x': 32, 'y': 25, 'w': 120, 'h': 20}},
    ])

    class CurrentRowControls(_FullControls):
        def append(self, item):
            if len(self) >= 2:
                for row in self:
                    if row.get('control_id') == 'row':
                        row['name'] = self[1]['name']
            super().append(item)

    snapshot['controls'] = CurrentRowControls(snapshot['controls'])
    state = repeated_state.__wrapped__(fresh)
    root, original = _draft(state)
    store = state[0]
    draft = store.control('learning_workflow', {'action': 'compile', 'learning_session_id': state[2]['learning_id']}, 'second-compile')
    step = next(s for s in draft['definition']['steps'] if s['action'].get('target_memory') == original['reference'])
    assert step['review_status'] == 'pending'
    assert original['recipe']['contract_version'] == 'target_recipe.v2'
    assert original['recipe']['evidence_refs'][1]['kind'] == 'learning_action'
    assert original['recipe']['strategies'][0]['action']['source'] == 'row_name'

    class Facade:
        def read_target_edit_context(self, reference, proposed_recipe=None):
            with MemoryWorkspace(root) as library:
                return read_target_edit_context(library, reference, proposed_recipe=proposed_recipe)

        def propose_target_edit(self, reference, action, strategies, **kwargs):
            with MemoryWorkspace(root) as library:
                return propose_target_edit(library, reference, action, strategies, **kwargs)

    app = QApplication.instance() or QApplication([])
    with MemoryWorkspace(root) as library:
        read_target_edit_context(library, original['reference'], proposed_recipe=original['recipe'])
    editor = WorkflowTargetEditor(Facade())
    editor.set_step(step, draft['definition'], proposed_recipes=[original])
    editor.load_button.click()
    _wait(app, lambda: editor._context is not None and not editor.is_busy)
    assert editor.action_source.currentData() == 'row_name'
    assert editor.preview_button.isEnabled()
    editor.preview_button.click()
    _wait(app, lambda: editor._preview_result is not None and not editor.is_busy)
    assert editor._preview_result['preview']['status'] == 'matched'
    assert editor._preview_result['preview']['candidate']['bbox'] == snapshot['controls'][1]['bbox']
    editor.close()
