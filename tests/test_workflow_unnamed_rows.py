"""无名容器和记录专属 ID 仍须按当前唯一行绑定，歧义不能通过。"""
from copy import deepcopy

import pytest

from app.learning_memory.uia_rows import resolve_uia_row, validate_visible_row_strategy
from tests.test_workflow_uia_rows import scene
from tests.test_workflow_target_editor import _editor, STEP, DEFINITION
from tests.test_workflow_steps_ui import qt_app


def unnamed_scene():
    snapshot, strategy, capture, bindings = scene()
    snapshot['controls'][0]['name'] = None
    strategy['container'].pop('name')
    for control in snapshot['controls'][1:]:
        if control.get('automation_id'):
            control['automation_id'] = control['ancestor_control_ids'][0] + '.' + control['automation_id']
    strategy['properties'][0].pop('automation_id')
    strategy['action'].pop('automation_id')
    return snapshot, strategy, capture, bindings


def test_unnamed_identified_container_resolves_different_current_rows():
    snapshot, strategy, capture, bindings = unnamed_scene()
    for value, expected in [('A-1', 'ab'), ('B-2', 'bb')]:
        bindings['inputs']['wanted_id'] = value
        result = resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)
        assert result['candidate']['action_id'] == expected


@pytest.mark.parametrize('member,reason', [('list', 'container_ambiguous'),
    ('bid', 'property_ambiguous'), ('bb', 'ambiguous')])
def test_optional_child_ids_never_hide_container_property_or_action_ambiguity(member, reason):
    snapshot, strategy, capture, bindings = unnamed_scene()
    duplicate = deepcopy(next(row for row in snapshot['controls'] if row['control_id'] == member))
    duplicate['control_id'] += '-duplicate'
    snapshot['controls'].append(duplicate)
    with pytest.raises(ValueError, match=reason):
        resolve_uia_row(snapshot, strategy, capture=capture, bindings=bindings)


@pytest.mark.parametrize('selector', [{'control_type': 'Group'},
    {'control_type': 'Group', 'automation_id': ''},
    {'control_type': 'Group', 'automation_id': '  '}])
def test_unnamed_container_still_requires_nonempty_identity(selector):
    _, strategy, _, _ = unnamed_scene()
    strategy['container'] = selector
    with pytest.raises(ValueError, match='strategy'):
        validate_visible_row_strategy(strategy)


def test_editor_explicit_child_identity_choice_survives_reload(tmp_path):
    app, facade, editor = _editor(tmp_path)
    context = deepcopy(facade.context)
    context['controls'][0]['name'] = None
    for cid, suffix in [('text', 'recordId'), ('open', 'openDetail')]:
        control = next(row for row in context['controls'] if row['control_id'] == cid)
        control['automation_id'] = 'row-a.' + suffix
    context['recipe']['strategies'][0]['automation_id'] = 'row-a.openDetail'
    row_b = deepcopy(context['controls'][1])
    row_b['control_id'] = 'row-b'
    context['controls'].append(row_b)
    for cid in ['text', 'open']:
        child = deepcopy(next(row for row in context['controls'] if row['control_id'] == cid))
        child.update(control_id=cid + '-b', ancestor_control_ids=['row-b', 'list'],
                     automation_id=child['automation_id'].replace('row-a.', 'row-b.'))
        if cid == 'text':
            child['name'] = 'B-2'
        context['controls'].append(child)
    try:
        editor.set_step(STEP, DEFINITION)
        editor._install_context(context)
        assert editor.container.count() == 1
        editor.mode.setCurrentIndex(editor.mode.findData('visible_row'))
        editor.row_type.setCurrentIndex(editor.row_type.findData('ListItem'))
        editor.value_source.setCurrentIndex(editor.value_source.findData('input'))
        editor.sample.setText('B-2')
        original = editor._strategy()
        assert original['properties'][0]['automation_id'].startswith('row-')
        assert original['action']['automation_id'].startswith('row-')
        editor.property_id_required.setChecked(False)
        editor.action_id_required.setChecked(False)
        modified = editor._strategy()
        assert modified['container'] == {'control_type': 'List', 'automation_id': 'results'}
        assert 'automation_id' not in modified['properties'][0]
        assert modified['action'] == {'control_type': 'Button', 'name': 'Open'}
        assert modified['constraints'][0]['value'] == {'source': 'input', 'name': 'wanted'}
        context['recipe']['strategies'] = [modified]
        editor.set_step(STEP, DEFINITION)
        editor._install_context(context)
        assert not editor.property_id_required.isChecked()
        assert not editor.action_id_required.isChecked()
        editor.sample.setText('A-1')
        assert editor._strategy() == modified
        assert editor.preview_button.isEnabled()
        assert not facade.proposals
    finally:
        editor.close()


def test_main_saves_unnamed_container_and_reopens_current_row_binding(monkeypatch, qt_app, tmp_path):
    from PySide6.QtWidgets import QTableWidgetItem
    from tests.test_workflow_target_editor_service import row_state
    from tests.test_workflow_target_journey import _ready, _target_tab, _wait, _run_main
    state = row_state(tmp_path, unnamed_dynamic=True)
    store, root = state[:2]
    _ready(store)
    saved = {}

    def edit(window):
        pane = window.steps
        pane.open_learning_button.click()
        pane.save_button.click()
        original = pane.snapshot
        pane.add_input.click()
        pane.inputs.setItem(0, 0, QTableWidgetItem('wanted'))
        _target_tab(pane)
        editor = pane.target_editor
        editor.load_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        editor.mode.setCurrentIndex(editor.mode.findData('visible_row'))
        editor.row_type.setCurrentIndex(editor.row_type.findData('ListItem'))
        editor.value_source.setCurrentIndex(editor.value_source.findData('input'))
        editor.sample.setText('Beta')
        editor.property_id_required.setChecked(False)
        editor.action_id_required.setChecked(False)
        editor.preview_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        preview = editor._preview_result
        assert preview['preview']['status'] == 'matched', editor.status.text()
        assert preview['preview']['candidate']['bbox']['y'] == 75
        editor.apply_button.click()
        pane.save_button.click()
        assert not pane.dirty, pane.status.text()
        assert pane.snapshot['program_id'] != original['program_id']
        saved.update(snapshot=deepcopy(pane.snapshot), rule=deepcopy(preview['recipe']['strategies'][0]))
        assert not list((store.session / 'commands').glob('*.json'))

    _run_main(monkeypatch, qt_app, root.parent, edit, session=store.session)

    def reopen(window):
        pane = window.steps
        assert pane.snapshot == saved['snapshot']
        _target_tab(pane)
        editor = pane.target_editor
        editor.load_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        assert not editor.property_id_required.isChecked() and not editor.action_id_required.isChecked()
        assert not editor._selector_missing
        assert editor.sample.text() == ''
        editor.sample.setText('Alpha')
        editor.preview_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        assert editor._preview_result['preview']['status'] == 'matched', editor.status.text()
        assert editor._preview_result['preview']['candidate']['bbox']['y'] == 50
        assert editor._strategy() == saved['rule']
        assert not list((store.session / 'commands').glob('*.json'))
        import os
        capture_path = os.environ.get('WORKFLOW_UNNAMED_CAPTURE')
        if capture_path:
            window.resize(1200, 950)
            pane.editor_tabs.currentWidget().ensureWidgetVisible(editor.action_id_required)
            qt_app.processEvents()
            assert window.grab().save(capture_path)

    _run_main(monkeypatch, qt_app, root.parent, reopen, session=store.session)
