"""动态目标规则的变量依赖必须在保存时可用，修改依赖会重置审核。"""
from copy import deepcopy

import pytest

from app.learning_memory.receipt_adapter import content_hash
from app.learning_memory.target_recipe import action_semantics_sha256
from app.learning_memory.workspace import MemoryWorkspace
from test_learning_action_evidence import repeated_state, _compile
from test_learning_observation_source import observation_scene
from test_workflow_target_bindings import RULE


def _definition(repeated_state, reference):
    store, root, started, _, _ = repeated_state
    draft = _compile(store, started)
    definition = deepcopy(draft['definition'])
    definition['inputs'] = [{'name': 'query', 'type': 'text', 'required': True}]
    rule = deepcopy(RULE)
    rule['constraints'][0]['value'] = reference
    recipe = deepcopy(draft['proposed_target_recipes'][0]['recipe'])
    recipe['contract_version'] = 'target_recipe.v1'
    recipe['evidence_refs'] = recipe['evidence_refs'][:1]
    recipe['strategies'] = [rule]
    first = definition['steps'][0]
    recipe['action_semantics_sha256'] = action_semantics_sha256(first['action'],
        scope=recipe['scope'], strategies=recipe['strategies'])
    recipe['recipe_id'] = 'target-recipe-' + content_hash({k: v for k, v in recipe.items() if k != 'recipe_id'})
    first['action']['target_memory']['recipe_id'] = recipe['recipe_id']
    second = deepcopy(draft['proposed_target_recipes'][1]['recipe'])
    return root, draft['workflow_id'], definition, [recipe, second]


@pytest.mark.parametrize('reference, expected', [
    ({'source': 'input', 'name': 'missing'}, 'target_input_unknown'),
    ({'source': 'output', 'step_id': 'step-2', 'name': 'value'}, 'target_upstream_output_unknown'),
])
def test_unknown_or_future_target_dependency_rejected_without_saving(repeated_state, reference, expected):
    root, workflow_id, definition, recipes = _definition(repeated_state, reference)
    with MemoryWorkspace(root) as library:
        before = library.load_workflow_program(workflow_id)
        with pytest.raises(ValueError, match=expected):
            library.save_workflow_program(workflow_id, before['content_sha256'], definition,
                                          'invalid-target-binding', target_recipes=recipes)
        assert library.load_workflow_program(workflow_id) == before
    assert not list((root / 'desktop-review/target-recipes').glob('*.json'))


def test_target_input_change_invalidates_review_and_removal_cannot_save(repeated_state):
    root, workflow_id, definition, recipes = _definition(repeated_state, {'source': 'input', 'name': 'query'})
    with MemoryWorkspace(root) as library:
        current = library.load_workflow_program(workflow_id)
        saved = library.save_workflow_program(workflow_id, current['content_sha256'], definition,
                                               'first', target_recipes=recipes)
        reviewed = deepcopy(saved['definition'])
        for step in reviewed['steps']:
            step['review_status'] = 'reviewed'
        saved = library.save_workflow_program(workflow_id, saved['content_sha256'], reviewed, 'review')
        assert saved['definition']['steps'][0]['review_status'] == 'reviewed'
        changed = deepcopy(saved['definition'])
        changed['inputs'][0]['required'] = False
        changed_saved = library.save_workflow_program(workflow_id, saved['content_sha256'], changed, 'change-input')
        assert changed_saved['definition']['steps'][0]['review_status'] == 'pending'
        assert library.load_workflow_program(workflow_id, saved['program_id']) == saved
        changed['inputs'] = []
        with pytest.raises(ValueError, match='target_input_unknown'):
            library.save_workflow_program(workflow_id, changed_saved['content_sha256'], changed, 'delete-input')


def test_row_text_comparison_rejects_nontext_variable(repeated_state):
    root, workflow_id, definition, recipes = _definition(repeated_state, {'source': 'input', 'name': 'query'})
    definition['inputs'][0]['type'] = 'number'
    with MemoryWorkspace(root) as library:
        current = library.load_workflow_program(workflow_id)
        with pytest.raises(ValueError, match='target_row_requires_text'):
            library.save_workflow_program(workflow_id, current['content_sha256'], definition,
                                          'wrong-type', target_recipes=recipes)


@pytest.mark.parametrize('entry', ['save_program', 'resolve'])
def test_direct_editorial_recipe_cannot_bypass_action_type(repeated_state, entry):
    from app.learning_memory.workflow_target_editor_service import propose_target_edit
    from app.learning_memory.target_recipe import save_target_recipe
    from app.learning_memory.target_resolution import resolve_target_recipe
    store, root, started, _, observations = repeated_state
    draft = _compile(store, started)
    original = draft['proposed_target_recipes'][0]
    with MemoryWorkspace(root) as library:
        proposed = propose_target_edit(library, original['reference'], {'kind': 'click', 'goal': 'Other action'},
            [{'kind': 'uia', 'name': 'Other action', 'control_type': 'Button'}], proposed_recipe=original['recipe'])
        recipe = proposed['recipe']
        action = {'kind': 'input_sequence', 'field_goal': 'Other action',
                  'text': {'source': 'constant', 'value': 'text'}, 'clear_existing': True, 'submit_search': False}
        recipe['action_semantics_sha256'] = action_semantics_sha256(action, scope=recipe['scope'], strategies=recipe['strategies'])
        recipe['recipe_id'] = 'target-recipe-' + content_hash({k: v for k, v in recipe.items() if k != 'recipe_id'})
        reference = {**proposed['reference'], 'recipe_id': recipe['recipe_id']}
        action['target_memory'] = reference
        if entry == 'resolve':
            save_target_recipe(library, recipe)
            result = resolve_target_recipe(library, reference, frame=observations[0]['frame'],
                observations={'uia': observations[0]['uia']}, bindings={'action': action})
            assert result['status'] == 'invalid' and result['candidate'] is None
            assert result['reason'] == 'target_edit_action_control_type_mismatch'
        else:
            definition = deepcopy(draft['definition'])
            definition['steps'][0]['action'] = action
            current = library.load_workflow_program(draft['workflow_id'])
            with pytest.raises(ValueError, match='target_edit_action_control_type_mismatch'):
                library.save_workflow_program(draft['workflow_id'], current['content_sha256'], definition,
                    'direct-bypass', target_recipes=[recipe, draft['proposed_target_recipes'][1]['recipe']])
