"""独立界面中的学习框能找到确切步骤，并保存真正消费的新定位规则。"""
from copy import deepcopy

from app.learning_memory.workspace import MemoryWorkspace
from app.learning_memory.target_resolution import resolve_target_recipe
from test_learning_synthesis import _reply, _stop, repeated_state, observation_scene
from test_workflow_steps_ui import qt_app, _wait
from test_workflow_user_journey import _run_main


def _saved(state):
    store, root, _, _, _ = state
    completion = store.control('learning_workflow', _reply(_stop(store)['synthesis_request']), 'boxes-synthesis')
    draft = completion['draft']
    with MemoryWorkspace(root) as library:
        baseline = library.load_workflow_program(draft['workflow_id'])
        program = library.save_workflow_program(draft['workflow_id'], baseline['content_sha256'],
            draft['definition'], 'boxes-save', target_recipes=[row['recipe'] for row in draft['proposed_target_recipes']])
    return store, root, program


def test_interface_links_keep_each_action_frame_and_original_versions(repeated_state):
    store, root, program = _saved(repeated_state)
    with MemoryWorkspace(root) as library:
        content = library.list_interface_contents(False, 'memory-local')[0]
        before = {path: path.read_bytes() for path in root.rglob('*.json')}
        links = library.read_interface_target_links(content['interface_id'], content['version_id'])['targets']
        assert [item['step_id'] for item in links] == ['step-1', 'step-2']
        assert all(item['program_id'] == program['program_id'] for item in links)
        assert links[0]['target_boxes'][0]['bbox'] == [35, 25, 30, 20]
        assert links[1]['target_boxes'][0]['bbox'] == [35, 25, 30, 20]
        assert links[0]['frame']['sha256'] != links[1]['frame']['sha256']
        assert {path: path.read_bytes() for path in before} == before


def test_interface_box_opens_rule_moves_target_saves_reopens_and_resolves(monkeypatch, qt_app, repeated_state):
    store, root, original = _saved(repeated_state)
    saved = []
    def edit(window):
        pane = window.interfaces.pane
        assert pane.target_choice.count() == 3
        assert pane.target_choice.currentData()['step_id'] == 'step-1'
        assert list(pane.canvas._regions) == ['strategy-0']
        assert not pane.dirty
        pane.canvas.select_region('strategy-0')
        pane._region_selected('strategy-0')
        pane.edit_target_button.click()
        editor = window.steps.target_editor
        _wait(qt_app, lambda: not window.steps.is_busy and editor._context is not None)
        assert window.tabs.currentWidget() is window.steps
        assert window.steps._selected_id == 'step-1'
        assert editor.canvas._regions['strategy-0'].bbox() == [35, 25, 30, 20]
        window.steps.goal.setText('Other action')
        editor.canvas.set_region_bbox('strategy-0', [100, 25, 40, 20])
        editor.canvas.regionGeometryChanged.emit('strategy-0', [100, 25, 40, 20])
        _wait(qt_app, lambda: not editor.is_busy)
        assert editor._preview_result['preview']['status'] == 'matched', editor.status.text()
        assert editor.fixed_control.currentData()['name'] == 'Other action'
        assert not editor.load_button.isEnabled()
        draft_rules = deepcopy(editor._strategies)
        editor.load_evidence()
        assert not editor.is_busy
        assert editor._strategies == draft_rules
        editor.apply_button.click()
        window.steps.save_button.click()
        assert not window.steps.dirty, window.steps.status.text()
        revised = deepcopy(window.steps.snapshot)
        assert revised['program_id'] != original['program_id']
        assert revised['definition']['steps'][0]['review_status'] == 'pending'
        assert revised['definition']['steps'][0]['action']['target_memory'] != original['definition']['steps'][0]['action']['target_memory']
        saved.append(revised)
        with MemoryWorkspace(root) as library:
            assert library.load_workflow_program(original['workflow_id'], original['program_id']) == original
            reference = revised['definition']['steps'][0]['action']['target_memory']
            context = library.read_target_edit_context(reference)
            result = resolve_target_recipe(library, reference, frame=context['frame'],
                observations={'uia': context['uia']}, bindings={'action': revised['definition']['steps'][0]['action']})
            assert result['status'] == 'matched'
            assert result['candidate']['bbox'] == {'x': 100, 'y': 25, 'w': 40, 'h': 20}
        assert not list((store.session / 'commands').glob('*.json'))
    _run_main(monkeypatch, qt_app, root.parent, edit, session=store.session)
    def reopen(window):
        assert window.steps.snapshot == saved[0]
        pane = window.interfaces.pane
        assert pane.target_choice.currentData()['program_id'] == saved[0]['program_id']
        assert pane.canvas._regions['strategy-0'].bbox() == [100, 25, 40, 20]
    _run_main(monkeypatch, qt_app, root.parent, reopen, session=store.session)


def test_target_link_refuses_to_replace_unsaved_step_draft(monkeypatch, qt_app, repeated_state):
    store, root, _ = _saved(repeated_state)
    def inspect(window):
        pane = window.interfaces.pane
        window.steps.step_title.setText('保留未保存修改')
        before = window.steps.definition.copy()
        assert not window.steps.open_target_link(pane.target_choice.currentData())
        assert window.steps.dirty
        assert window.steps.step_title.text() == '保留未保存修改'
        assert window.steps.definition == before
    _run_main(monkeypatch, qt_app, root.parent, inspect, session=store.session)


def test_stale_target_link_refuses_to_open_changed_program(qt_app, repeated_state):
    store, root, original = _saved(repeated_state)
    with MemoryWorkspace(root) as library:
        content = library.list_interface_contents(False, 'memory-local')[0]
        link = library.read_interface_target_links(content['interface_id'], content['version_id'])['targets'][0]
        definition = deepcopy(original['definition'])
        definition['title'] = '较新的工作流版本'
        newer = library.save_workflow_program(original['workflow_id'], original['content_sha256'], definition, 'newer-program')
    from app.learning_memory.workflow_steps_pane import WorkflowStepsPane
    from app.learning_memory.editor_client import MemoryEditorClient
    with MemoryEditorClient(root) as client:
        pane = WorkflowStepsPane(client)
        try:
            _wait(qt_app, lambda: not pane.is_busy)
            before = deepcopy(pane.snapshot)
            assert before['program_id'] == newer['program_id']
            assert not pane.open_target_link(link)
            assert pane.snapshot == before
        finally:
            pane.close()
            pane.deleteLater()
