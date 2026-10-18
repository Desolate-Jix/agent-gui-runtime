"""英文首次构造与重复切换保留主题及原业务状态；仅使用离屏合成库。"""
from copy import deepcopy
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QPushButton, QMainWindow

from tests.test_workflow_steps_ui import qt_app, _wait
from tests.test_learning_synthesis import repeated_state, observation_scene
from tests.test_interface_target_box_journey import _saved


def _run_localized_main(monkeypatch, app, data_root, session, inspect):
    from scripts import run_learning_memory_workbench
    visited = []
    def event_loop():
        windows = [widget for widget in app.topLevelWidgets()
                   if isinstance(widget, QMainWindow) and hasattr(widget, 'steps')]
        assert len(windows) == 1
        window = windows[0]
        _wait(app, lambda: not window.steps.is_busy and not window.projects.is_busy
              and not window.interfaces.pane.is_busy)
        try:
            inspect(window)
            visited.append(True)
        finally:
            window.steps.run_panel._pending = None
            if window.steps.dirty:
                window.steps.discard()
            window.interfaces.pane.cancel_loading()
            window.projects.cancel_loading()
            _wait(app, lambda: not window.steps.is_busy and not window.projects.is_busy
                  and not window.interfaces.pane.is_busy)
            window.close()
            window.deleteLater()
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        return 0
    monkeypatch.setattr(app, 'exec', event_loop)
    monkeypatch.setattr(sys, 'argv', ['run_learning_memory_workbench.py', '--data-dir',
                                    str(data_root), '--session-dir', str(session)])
    assert run_learning_memory_workbench.main() == 0
    assert visited == [True]


@pytest.mark.parametrize('initial_language', ['zh-CN', 'en-US'])
def test_initial_language_keeps_button_theme_and_switches_preserve_drafts(
        initial_language, monkeypatch, qt_app, repeated_state, tmp_path):
    from app.learning_memory.workbench_i18n import initialize_i18n, bound_text
    from app.learning_memory.workbench_theme import _BUTTON_ICONS
    manager = initialize_i18n(qt_app, tmp_path / 'workbench-preferences.json', initial_language)
    store, root, _ = _saved(repeated_state)

    def inspect(window):
        pane = window.steps
        pane.run_panel._timer.stop()
        assert pane.save_button.text() == ('Save task steps' if initial_language == 'en-US' else '保存任务步骤')
        buttons = [(button, getattr(bound_text(button), 'source', bound_text(button)))
                   for button in window.findChildren(QPushButton)]
        themed = [(button, source) for button, source in buttons if source in _BUTTON_ICONS]
        assert themed
        for button, source in themed:
            assert not button.icon().isNull(), (initial_language, source, button.text())
            if source in {'保存任务步骤', '保存', '保存修改', '保存项目', '保存项目修改'}:
                assert button.property('primary') is True, (initial_language, source)
        pane.step_title.setText('用户任务步骤：未保存')
        assert pane.dirty
        definition = deepcopy(pane.definition)
        snapshot = deepcopy(pane.snapshot)
        selected = pane.steps.currentRow()
        pane.run_panel._pending = {'request_id': 'original-theme-check-id', 'action': 'continue'}
        pending = deepcopy(pane.run_panel._pending)
        def forbidden(*args, **kwargs):
            raise AssertionError('theme language switching must not send or reload')
        monkeypatch.setattr(pane.run_panel, '_start_job', forbidden)
        monkeypatch.setattr(pane, '_start_read', forbidden)
        for language in ['en-US', 'zh-CN'] * 3:
            manager.set_language(language)
            qt_app.processEvents()
            assert pane.step_title.text() == '用户任务步骤：未保存'
            assert pane.dirty and pane.definition == definition and pane.snapshot == snapshot
            assert pane.steps.currentRow() == selected
            assert pane.run_panel._pending == pending
            for button, source in themed:
                assert not button.icon().isNull(), (language, source)
            assert pane.save_button.property('primary') is True
            assert not list((store.session / 'commands').glob('*.json'))
        pane.run_panel._pending = None
        pane.discard()

    try:
        _run_localized_main(monkeypatch, qt_app, root.parent, store.session, inspect)
    finally:
        manager.set_language('zh-CN', persist=False)
