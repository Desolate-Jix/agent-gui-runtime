"""普通离屏控件修改选择语义，保留教学规则和旧程序。"""
from copy import deepcopy
import pytest

from test_workflow_steps_ui import qt_app, _wait, generated, _pane
from test_workflow_target_journey import _ready, _target_tab, _choose_control
from test_workflow_user_journey import _run_main


@pytest.mark.parametrize('combined', [False, True])
def test_intent_only_edit_requires_preview_and_survives_review_reopen(monkeypatch, qt_app, tmp_path, combined):
    from test_workflow_target_editor_service import _FullControls
    from test_learning_observation_source import observation_scene
    from test_learning_action_evidence import repeated_state
    from app.learning_memory.workspace import MemoryWorkspace
    # 本轮合成证据使用原生行名称结构，不复用实机学习资产。
    scene = observation_scene.__wrapped__(tmp_path)
    snapshot = scene[2]['uia']['snapshot']
    snapshot.update(provider='windows_uia', provider_tree_valid=True)
    for i, control in enumerate(snapshot['controls']):
        control.update(control_id=f'original-{i}', ancestor_control_ids=[])
    snapshot['controls'].extend([
        {'control_id': 'list', 'ancestor_control_ids': [], 'name': 'Results', 'control_type': 'List',
         'bbox': {'x': 80, 'y': 20, 'w': 75, 'h': 75}, 'visible': True, 'enabled': True},
        {'control_id': 'row', 'ancestor_control_ids': ['list'], 'name': 'Alpha', 'control_type': 'ListItem',
         'bbox': {'x': 82, 'y': 25, 'w': 70, 'h': 45}, 'visible': True, 'enabled': True},
        {'control_id': 'edit', 'ancestor_control_ids': ['list', 'row'], 'name': 'Alpha', 'control_type': 'Edit',
         'bbox': {'x': 85, 'y': 28, 'w': 30, 'h': 10}, 'visible': True, 'enabled': True},
    ])
    snapshot['controls'] = _FullControls(snapshot['controls'])
    store, root, _, _, _ = repeated_state.__wrapped__(scene)
    _ready(store)
    saved = []

    def edit(window):
        pane = window.steps
        pane.open_learning_button.click(); pane.save_button.click()
        _target_tab(pane)
        editor = pane.target_editor
        editor.load_button.click(); _wait(qt_app, lambda: not pane.is_busy)
        editor.mode.setCurrentIndex(editor.mode.findData('visible_row'))
        _choose_control(editor.container, 'Results')
        editor.row_type.setCurrentIndex(editor.row_type.findData('ListItem'))
        editor.property_source.setCurrentIndex(editor.property_source.findData('row'))
        editor.action_source.setCurrentIndex(editor.action_source.findData('row_name'))
        editor.constant.setText('Alpha')
        if combined:
            assert pane.selection_intent.isEnabled()
            pane.selection_intent.setCurrentIndex(pane.selection_intent.findData('ensure_selected'))
        editor.preview_button.click(); _wait(qt_app, lambda: not pane.is_busy)
        assert editor._preview_result['preview']['status'] == 'matched', editor.status.text()
        editor.apply_button.click(); pane.save_button.click()
        assert not pane.dirty, pane.status.text()
        baseline = deepcopy(pane.snapshot)
        editor.load_button.click(); _wait(qt_app, lambda: not pane.is_busy)
        teaching_recipe = deepcopy(editor._context['recipe']['editorial']['context_recipe'])
        assert pane.selection_intent.isEnabled()
        if combined:
            pane.selection_intent.setCurrentIndex(pane.selection_intent.findData(None))
        pane.selection_intent.setCurrentIndex(pane.selection_intent.findData('ensure_selected'))
        assert '确保选中' in pane.step_summary.text()
        pane.save_button.click()
        assert pane.snapshot == baseline and pane.dirty
        editor.preview_button.click(); _wait(qt_app, lambda: not pane.is_busy)
        assert editor._preview_result['preview']['status'] == 'matched', editor.status.text()
        recipe = deepcopy(editor._preview_result['recipe'])
        assert recipe['editorial']['context_recipe'] == teaching_recipe
        assert recipe['editorial']['context_recipe'].get('action_semantics_sha256') != recipe['action_semantics_sha256']
        editor.apply_button.click(); pane.save_button.click()
        assert not pane.dirty, pane.status.text()
        revised = deepcopy(pane.snapshot)
        if not combined:
            assert revised['program_id'] != baseline['program_id']
        action = revised['definition']['steps'][0]['action']
        assert action['selection_intent'] == 'ensure_selected'
        if not combined:
            assert action['target_memory'] != baseline['definition']['steps'][0]['action']['target_memory']
        assert revised['definition']['steps'][0]['review_status'] == 'pending'
        pane.review.setCurrentIndex(pane.review.findData('reviewed')); pane.save_button.click()
        assert not pane.dirty, pane.status.text()
        saved.append(deepcopy(pane.snapshot))
        with MemoryWorkspace(root) as library:
            assert library.load_workflow_program(baseline['workflow_id'], baseline['program_id']) == baseline
        assert not list((store.session / 'commands').glob('*.json'))

    _run_main(monkeypatch, qt_app, root.parent, edit, session=store.session)
    def reopen(window):
        pane = window.steps
        assert pane.snapshot == saved[0]
        assert pane.selection_intent.currentData() == 'ensure_selected'
        assert pane.review.currentData() == 'reviewed'
        assert '确保选中' in pane.step_summary.text()
        assert not pane.dirty
        pane.click_kind.setCurrentIndex(pane.click_kind.findData('double'))
        pane.save_button.click()
        assert pane.snapshot == saved[0] and pane.dirty
        assert not list((store.session / 'commands').glob('*.json'))
    _run_main(monkeypatch, qt_app, root.parent, reopen, session=store.session)


def test_ordinary_non_row_action_keeps_default_and_rejects_unsupported_intent(qt_app, generated):
    pane = _pane(qt_app, generated)
    try:
        pane.action_kind.setCurrentIndex(pane.action_kind.findData('click'))
        pane.goal.setText('Select ordinary control')
        pane.save_button.click()
        baseline = deepcopy(pane.snapshot)
        assert pane.selection_intent.currentData() is None
        assert not pane.selection_intent.isEnabled()
        assert all('selection_intent' not in step['action'] for step in baseline['definition']['steps'])
        pane.selection_intent.setCurrentIndex(pane.selection_intent.findData('ensure_selected'))
        pane.save_button.click()
        assert pane.snapshot == baseline and pane.dirty
        assert pane._target_action() is None
        assert '唯一的可见行名称规则' in pane.status.text()
    finally:
        pane.close()
