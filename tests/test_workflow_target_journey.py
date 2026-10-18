"""从真实主窗口修改目标规则，使用新合成学习证据并保留原版本。"""
from copy import deepcopy
import os
import pytest

from PySide6.QtWidgets import QTableWidgetItem

from app.learning_memory.workspace import MemoryWorkspace
from test_learning_synthesis import _reply, _stop, repeated_state, observation_scene
from test_workflow_steps_ui import qt_app, _wait
from test_workflow_user_journey import _run_main


def _choose_control(combo, name):
    index = next(i for i in range(combo.count()) if combo.itemData(i).get('name') == name)
    combo.setCurrentIndex(index)


def _target_tab(pane):
    pane.editor_tabs.setCurrentIndex(next(i for i in range(pane.editor_tabs.count())
        if pane.editor_tabs.tabText(i) == '目标规则'))


def _ready(store):
    request = _stop(store)['synthesis_request']
    return store.control('learning_workflow', _reply(request), 'generated-for-editor')


def test_main_target_edit_preview_apply_save_reopen_preserves_original(monkeypatch, qt_app, repeated_state):
    store, root, _, _, _ = repeated_state
    _ready(store)
    saved = []
    def inspect(window):
        pane = window.steps
        pane.open_learning_button.click()
        pane.save_button.click()
        assert not pane.dirty
        baseline = deepcopy(pane.snapshot)
        original_recipes = {path: path.read_bytes() for path in (root / 'desktop-review/target-recipes').glob('*.json')}
        saved.append(baseline)
        _target_tab(pane)
        editor = pane.target_editor
        editor.load_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        _choose_control(editor.fixed_control, 'Other action')
        assert pane.dirty and editor.has_unapplied_changes
        pane.steps.setCurrentRow(1)
        assert pane._selected_id == 'step-1'
        pane.save_button.click()
        assert pane.snapshot == baseline and '未应用' in pane.status.text()
        pane.goal.setText('Other action')
        editor.preview_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        assert editor._preview_result['preview']['status'] == 'matched', editor.status.text()
        if os.environ.get('WORKFLOW_TARGET_CAPTURE'):
            window.resize(1320, 1000)
            qt_app.processEvents()
            assert editor.apply_button.isVisible()
            assert not editor.container.isVisible()
            assert window.grab().save(os.environ['WORKFLOW_TARGET_CAPTURE'])
        assert {path: path.read_bytes() for path in (root / 'desktop-review/target-recipes').glob('*.json')} == original_recipes
        assert pane.snapshot == baseline
        editor.apply_button.click()
        assert not editor.has_unapplied_changes
        assert pane._step()['action']['target_memory'] != baseline['definition']['steps'][0]['action']['target_memory']
        pane.save_button.click()
        assert not pane.dirty, pane.status.text()
        edited = deepcopy(pane.snapshot)
        saved.append(edited)
        assert edited['program_id'] != baseline['program_id']
        assert edited['definition']['steps'][0]['provenance'] == 'editorial'
        assert edited['definition']['steps'][0]['review_status'] == 'pending'
        with MemoryWorkspace(root) as library:
            assert library.load_workflow_program(baseline['workflow_id'], baseline['program_id']) == baseline
        editor.load_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        assert editor.fixed_control.currentData()['name'] == 'Other action'
        assert editor._context['recipe']['editorial']['validation'] == 'unverified'
        assert not list((store.session / 'commands').glob('*.json'))
    _run_main(monkeypatch, qt_app, root.parent, inspect, session=store.session)
    def reopen(window):
        pane = window.steps
        assert pane.snapshot == saved[1]
        _target_tab(pane)
        pane.target_editor.load_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        assert pane.target_editor.fixed_control.currentData()['name'] == 'Other action'
        assert not pane.dirty
    _run_main(monkeypatch, qt_app, root.parent, reopen, session=store.session)


@pytest.mark.parametrize("compound", [False, True])
def test_main_visible_row_binds_new_input_and_reopens_without_preview_value(monkeypatch, qt_app, tmp_path, compound):
    from test_workflow_target_editor_service import row_state
    store, root, _, _, _ = row_state(tmp_path)
    _ready(store)
    def edit(window):
        pane = window.steps
        pane.open_learning_button.click()
        pane.save_button.click()
        _target_tab(pane)
        editor = pane.target_editor
        editor.load_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        pane.editor_tabs.setCurrentIndex(next(i for i in range(pane.editor_tabs.count())
            if pane.editor_tabs.tabText(i) == '工作流输入'))
        pane.add_input.click()
        pane.inputs.setItem(0, 0, QTableWidgetItem('wanted'))
        _target_tab(pane)
        editor.mode.setCurrentIndex(editor.mode.findData('visible_row'))
        assert '可见行' in editor.strategy_choice.currentText()
        _choose_control(editor.container, 'Results')
        editor.row_type.setCurrentIndex(editor.row_type.findData('ListItem'))
        _choose_control(editor.property_control, 'Alpha')
        _choose_control(editor.row_action, 'Open')
        editor.value_source.setCurrentIndex(editor.value_source.findData('input'))
        assert editor.binding.currentData() == (None, 'wanted')
        editor.sample.setText('Alpha')
        if compound:
            editor.condition_add.click()
            _choose_control(editor.property_control, 'Alpha')
            editor.operator.setCurrentIndex(editor.operator.findData('contains'))
            editor.constant.setText('Al')
            assert editor.condition_choice.count() == 2
        pane.goal.setText('Open selected record')
        editor.preview_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        assert editor._preview_result['preview']['status'] == 'matched', editor.status.text()
        if compound and os.environ.get('WORKFLOW_COMPOUND_CAPTURE'):
            window.resize(1320, 1000)
            qt_app.processEvents()
            assert window.grab().save(os.environ['WORKFLOW_COMPOUND_CAPTURE'])
            scroll = pane.editor_tabs.currentWidget()
            scroll.ensureWidgetVisible(editor.apply_button)
            qt_app.processEvents()
            detail_path = os.path.splitext(os.environ['WORKFLOW_COMPOUND_CAPTURE'])[0] + '-conditions.png'
            assert window.grab().save(detail_path)
        editor.apply_button.click()
        pane.save_button.click()
        assert not pane.dirty, pane.status.text()
        reference = pane.snapshot['definition']['steps'][0]['action']['target_memory']
        context = pane.facade.read_target_edit_context(reference)
        rule = context['recipe']['strategies'][0]
        assert rule['constraints'][0]['value'] == {'source': 'input', 'name': 'wanted'}
        assert len(rule['constraints']) == (2 if compound else 1)
        if compound:
            assert rule['constraints'][1]['value'] == {'source': 'constant', 'value': 'Al'}
        assert context['recipe']['contract_version'] == 'target_recipe.v3'
        assert 'preview_inputs' not in context['recipe']
        assert not list((store.session / 'commands').glob('*.json'))
    _run_main(monkeypatch, qt_app, root.parent, edit, session=store.session)
    def reopened(window):
        pane = window.steps
        _target_tab(pane)
        pane.target_editor.load_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        editor = pane.target_editor
        assert editor.mode.currentData() == 'visible_row'
        assert editor.value_source.currentData() == 'input'
        assert editor.binding.currentData() == (None, 'wanted')
        assert editor.sample.text() == ''
        assert editor.condition_choice.count() == (2 if compound else 1)
        if compound:
            editor.condition_choice.setCurrentIndex(1)
            assert editor.constant.text() == 'Al'
            assert editor.operator.currentData() == 'contains'
        assert not pane.dirty
    _run_main(monkeypatch, qt_app, root.parent, reopened, session=store.session)
