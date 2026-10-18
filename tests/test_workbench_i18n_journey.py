"""全新合成内容的离屏语言切换；不调用桌面输入或模型。"""
from copy import deepcopy
import re

from PySide6.QtWidgets import QLabel, QAbstractButton, QGroupBox
from tests.test_workflow_steps_ui import qt_app, _wait
from tests.test_learning_synthesis import repeated_state, observation_scene
from tests.test_interface_target_box_journey import _saved
from tests.test_workflow_user_journey import _run_main


def test_switch_languages_retains_library_edits_selection_and_pending_request(monkeypatch, qt_app, repeated_state, tmp_path):
    from app.learning_memory.workbench_i18n import initialize_i18n
    manager = initialize_i18n(qt_app, tmp_path / 'workbench-preferences.json', 'zh_CN')
    store, root, _ = _saved(repeated_state)
    def inspect(window):
        window.steps.run_panel._timer.stop()
        pane = window.steps
        selected = pane.steps.currentRow()
        snapshot = deepcopy(pane.snapshot)
        pane.step_title.setText('任务步骤')
        assert pane.dirty
        definition = deepcopy(pane.definition)
        target_draft = pane.target_editor._has_unapplied_changes
        pending = {'request_id': 'test-existing-id', 'action': 'continue'}
        panel = pane.run_panel
        panel._pending = pending
        original_pending = deepcopy(pending)
        def forbidden(*args, **kwargs):
            raise AssertionError('language switching must not send or reload anything')
        monkeypatch.setattr(panel, '_start_job', forbidden)
        monkeypatch.setattr(pane, '_start_read', forbidden)
        window.tabs.setCurrentIndex(2)
        for locale in ['en-US', 'zh-CN'] * 4:
            manager.set_language(locale)
            qt_app.processEvents()
            assert pane.step_title.text() == '任务步骤'
            assert pane.snapshot == snapshot and pane.definition == definition and pane.dirty
            assert pane.steps.currentRow() == selected
            assert panel._pending == original_pending
            assert pane.target_editor._has_unapplied_changes == target_draft
            assert window.tabs.currentIndex() == 2
            assert pane.review.currentData() == 'pending'
            assert not list((store.session / 'commands').glob('*.json'))
            if locale == 'en-US':
                assert [window.tabs.tabText(i) for i in range(3)] == ['Task steps', 'Workflow projects', 'Standalone interface library']
                assert pane.save_button.text() == 'Save task steps'
                assert pane.review.currentText() == 'Pending review'
                assert 'reviewed' in pane.definition_summary.text().lower()
                assert 'Synthesized or edited' in pane.step_summary.text()
                assert 'Pending review' in pane.steps.currentItem().text()
                for button in window.findChildren(QAbstractButton):
                    assert not re.search('[\u4e00-\u9fff]', button.text()), (type(button).__name__, button.text())
        panel._pending = None
        manager.set_language('en-US')
        pane.review.setCurrentIndex(pane.review.findData('reviewed'))
        pane.save()
        assert not pane.dirty, pane.status.text()
        saved = pane.facade.load_workflow_program(pane.snapshot['workflow_id'], pane.snapshot['program_id'])
        step = saved['definition']['steps'][selected]
        assert step['title'] == '任务步骤'
        assert step['review_status'] == 'reviewed'
        assert step['action']['kind'] == snapshot['definition']['steps'][selected]['action']['kind']
        manager.set_language('zh-CN')
    _run_main(monkeypatch, qt_app, root.parent, inspect, session=store.session)
