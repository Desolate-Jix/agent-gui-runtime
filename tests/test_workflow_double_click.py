"""真实点击种类贯穿教学定义、原命令和普通编辑，不复用旧坐标。"""
from copy import deepcopy
import pytest

from test_workflow_learning_compiler import recorded, LEARNING
from test_workflow_program import program_service, WORKFLOW
from test_workflow_steps_ui import generated, qt_app, _pane
from app.learning_memory.workflow_compiler import compile_workflow_draft
from app.learning_memory.workflow_trial import _command
from app.learning_memory.workflow_program import validate_definition, _draft
from app.execution.local_action_contract import _validated_request

def test_recorded_double_click_compiles_without_downgrading(recorded):
    library, bundle, memory = recorded
    event = bundle['segments'][0]['events'][0]
    event.update(kind='step', operation='execute_recognition_plan', action_hints={'goal': '打开当前选中的目录', 'click_kind': 'double'})
    edge = memory['graph']['edges'][0]
    edge.update(operation='execute_recognition_plan', action_hints=deepcopy(event['action_hints']))
    draft = compile_workflow_draft(library, learning_session_id=LEARNING, parameter_bindings={}, annotations={})
    assert len(draft['definition']['steps']) == 1
    action = draft['definition']['steps'][0]['action']
    assert action == {'kind': 'click', 'goal': '打开当前选中的目录', 'click_kind': 'double'}
    assert draft['evidence_refs'][0]['event_id'] == 'run1'
    assert draft['proposed_target_recipes'] == []

def test_double_trial_uses_fresh_original_command():
    command = _command({'action': {'kind': 'click', 'goal': '打开当前选中的目录', 'click_kind': 'double'}}, {}, {})
    assert command == {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': {'goal': '打开当前选中的目录', 'click_kind': 'double'}}
    request = _validated_request(command['operation'], command['request'])
    assert request['click_kind'] == 'double' and request['capture_live'] is True
    assert request['learning_mode'] is None and request['max_execution_attempts'] == 1
    with pytest.raises(ValueError):
        _validated_request(command['operation'], {**command['request'], 'image_path': 'old.png'})

def test_legacy_click_stays_single():
    assert _command({'action': {'kind': 'click', 'goal': '选择目录'}}, {}, {})['request']['click_kind'] == 'single'

def test_double_persists_and_semantic_edit_requires_new_review(program_service):
    draft = program_service.load(WORKFLOW)
    definition = deepcopy(draft['definition'])
    definition['steps'][0]['action'] = {'kind': 'click', 'goal': '打开当前选中的目录', 'click_kind': 'double'}
    definition['steps'][1]['action']['goal'] = '返回'
    validate_definition(definition, {'home', 'results'})
    saved = program_service.save(WORKFLOW, draft['content_sha256'], definition, 'double-save')
    reviewed = deepcopy(saved['definition'])
    reviewed['steps'][0]['review_status'] = 'reviewed'
    approved = program_service.save(WORKFLOW, saved['content_sha256'], reviewed, 'double-review')
    edited = deepcopy(approved['definition'])
    edited['steps'][0]['action']['click_kind'] = 'single'
    changed = program_service.save(WORKFLOW, approved['content_sha256'], edited, 'single-edit')
    assert changed['definition']['steps'][0]['review_status'] == 'pending'
    assert program_service.load(WORKFLOW, approved['program_id'])['definition']['steps'][0]['action']['click_kind'] == 'double'

def test_click_kind_rejects_right_and_non_click(program_service):
    definition = program_service.load(WORKFLOW)['definition']
    definition['steps'][1]['action']['goal'] = '返回'
    definition['steps'][1]['action']['click_kind'] = 'right'
    with pytest.raises(ValueError):
        validate_definition(definition, {'home', 'results'})
    definition['steps'][1]['action'] = {'kind': 'read_text', 'goal': '读取', 'click_kind': 'double'}
    with pytest.raises(ValueError):
        validate_definition(definition, {'home', 'results'})

def test_double_definition_cannot_reuse_saved_target_memory(program_service):
    definition = program_service.load(WORKFLOW)['definition']
    definition['steps'][1]['action'] = {'kind': 'click', 'goal': '打开当前选中的目录', 'click_kind': 'double',
        'target_memory': {'recipe_id': 'target-recipe-' + 'c' * 64, 'interface_key': 'home', 'state_key': 'home'}}
    with pytest.raises(ValueError, match='task_program_double_click_target_memory_unsupported'):
        validate_definition(definition, {'home', 'results'})

def test_double_draft_does_not_inherit_old_single_target_memory():
    memory = {'graph': {'workflow': {'goal': '打开目录'}, 'edges': [{'edge_id': 'edge-double',
        'source_node_id': 'home', 'target_node_id': 'detail', 'provenance': 'observed_action_agent_judged',
        'operation': 'execute_recognition_plan', 'action_hints': {'goal': '打开当前选中的目录', 'click_kind': 'double',
            'target_memory': {'recipe_id': 'target-recipe-' + 'c' * 64, 'interface_key': 'home', 'state_key': 'home'}}}]}}
    assert 'target_memory' not in _draft(memory)['steps'][0]['action']

def test_ordinary_editor_shows_double_and_invalidates_changed_review(qt_app, generated):
    pane = _pane(qt_app, generated)
    try:
        pane.action_kind.setCurrentIndex(pane.action_kind.findData('click'))
        pane.goal.setText('打开当前选中的目录')
        assert pane.click_kind.findData('double') >= 0
        pane.click_kind.setCurrentIndex(pane.click_kind.findData('double'))
        pane.save_button.click()
        assert pane.snapshot['definition']['steps'][0]['action']['click_kind'] == 'double'
        pane.review.setCurrentIndex(pane.review.findData('reviewed'))
        pane.save_button.click()
        assert pane.snapshot['definition']['steps'][0]['review_status'] == 'reviewed'
        pane.click_kind.setCurrentIndex(pane.click_kind.findData('single'))
        pane.save_button.click()
        assert pane.snapshot['definition']['steps'][0]['review_status'] == 'pending'
        assert pane.click_kind.currentData() == 'single'
    finally:
        pane.close()
