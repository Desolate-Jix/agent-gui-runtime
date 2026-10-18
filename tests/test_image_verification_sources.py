"""结果原图候选只取固定目标状态的成功后帧。"""
from pathlib import Path

import pytest

from app.learning_memory.workspace import MemoryWorkspace
from test_learning_action_evidence import repeated_state
from test_learning_observation_source import observation_scene


def test_options_include_each_successful_after_image_not_only_representative(repeated_state):
    from app.learning_memory.image_verification_sources import read_workflow_image_options
    store, root, started, events, _ = repeated_state
    draft = store.control('learning_workflow', {'action': 'compile',
        'learning_session_id': started['learning_id']}, 'image-options-compile')
    with MemoryWorkspace(root) as library:
        program = library.load_workflow_program(draft['workflow_id'])
        target = program['definition']['steps'][0]['target_node_id']
        options = read_workflow_image_options(library, draft['workflow_id'], program['project_snapshot_id'], target)
    assert {item['reference_sha256'] for item in options} == {event['after']['sha256'] for event in events}
    assert len(options) == 2
    assert all(item['reference_size'] == [160, 100] and Path(item['image_path']).is_file() for item in options)
    assert events[0]['before']['sha256'] not in {item['reference_sha256'] for item in options}


def test_absent_target_is_rejected_instead_of_showing_other_states(repeated_state):
    from app.learning_memory.image_verification_sources import read_workflow_image_options
    store, root, started, _, _ = repeated_state
    draft = store.control('learning_workflow', {'action': 'compile',
        'learning_session_id': started['learning_id']}, 'image-options-compile')
    with MemoryWorkspace(root) as library:
        program = library.load_workflow_program(draft['workflow_id'])
        with pytest.raises(ValueError, match='image_check_target_not_in_snapshot'):
            read_workflow_image_options(library, draft['workflow_id'], program['project_snapshot_id'], 'other-state')


def test_closed_default_draft_does_not_enable_image_verification(repeated_state):
    store, _root, started, _, _ = repeated_state
    draft = store.control('learning_workflow', {'action': 'compile',
        'learning_session_id': started['learning_id']}, 'image-options-default')
    assert all('image_check' not in step.get('verification', {}) for step in draft['definition']['steps'])


def test_learning_cannot_bind_another_event_as_the_expected_result(repeated_state):
    store, _root, started, events, _ = repeated_state
    check = {'contract_version': 'workflow_image_check.v1',
        'reference_sha256': events[1]['after']['sha256'], 'reference_size': [160, 100],
        'template_bbox': [10, 10, 30, 30], 'search_roi': [0, 0, 160, 100], 'threshold': 0.95}
    with pytest.raises(ValueError, match='image_check_reference_not_event_after'):
        store.control('learning_workflow', {'action': 'compile',
            'learning_session_id': started['learning_id'],
            'annotations': {'click-0': {'verification': {'kind': 'agent_judgment', 'image_check': check}}}},
            'image-options-wrong-result')
