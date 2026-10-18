"""工作台导航的即时切换、键盘和减少动画行为。"""
import time
import os
from pathlib import Path

from PySide6.QtCore import Qt, QRectF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QScrollArea, QTabWidget, QWidget

from tests.test_workflow_steps_ui import qt_app, _wait
from tests.test_learning_synthesis import repeated_state, observation_scene
from tests.test_interface_target_box_journey import _saved
from tests.test_workflow_user_journey import _run_main


def test_navigation_switches_immediately_and_settles_on_last_selection(qt_app):
    from app.learning_memory.workbench_navigation import WorkbenchTabBar
    tabs = QTabWidget()
    bar = WorkbenchTabBar()
    tabs.setTabBar(bar)
    for text in ('任务步骤', '流程项目', '独立界面库'):
        tabs.addTab(QWidget(), text)
    tabs.resize(620, 360)
    tabs.show()
    qt_app.processEvents()
    bar.set_motion_enabled(True)
    try:
        for index in [1, 2, 0, 2]:
            tabs.setCurrentIndex(index)
            assert tabs.currentWidget() is tabs.widget(index)
            assert tabs.widget(index).isVisible()
        deadline = time.monotonic() + 1
        while bar.is_animating and time.monotonic() < deadline:
            qt_app.processEvents()
            time.sleep(.005)
        assert not bar.is_animating
        assert bar.indicator_rect.center().x() == QRectF(bar.tabRect(2)).center().x()
        bar.setFocus()
        QTest.keyClick(bar, Qt.Key.Key_Left)
        assert tabs.currentIndex() == 1
        assert tabs.currentWidget().isVisible()
    finally:
        tabs.close()
        tabs.deleteLater()
        qt_app.processEvents()


def test_reduced_motion_and_hide_finish_without_delaying_navigation(qt_app):
    from app.learning_memory.workbench_navigation import WorkbenchTabBar
    tabs = QTabWidget()
    bar = WorkbenchTabBar()
    tabs.setTabBar(bar)
    tabs.addTab(QWidget(), '任务步骤')
    tabs.addTab(QWidget(), '独立界面库')
    tabs.show()
    qt_app.processEvents()
    try:
        bar.set_motion_enabled(True)
        tabs.setCurrentIndex(1)
        bar.set_motion_enabled(False)
        assert not bar.is_animating
        assert tabs.currentIndex() == 1
        tabs.setCurrentIndex(0)
        assert not bar.is_animating
        bar.set_motion_enabled(True)
        tabs.setCurrentIndex(1)
        tabs.hide()
        assert not bar.is_animating
        assert tabs.currentIndex() == 1
    finally:
        tabs.close()
        tabs.deleteLater()
        qt_app.processEvents()


def test_full_workbench_theme_keeps_pages_controls_and_navigation_usable(monkeypatch, qt_app, repeated_state):
    store, root, _ = _saved(repeated_state)
    captures = os.environ.get('WORKBENCH_UI_CAPTURE_DIR')
    def inspect(window):
        assert all(not window.tabs.tabIcon(index).isNull() for index in range(3))
        assert not window.steps.save_button.icon().isNull()
        assert not window.interfaces.pane.save_button.icon().isNull()
        original_program = window.steps.snapshot['program_id']
        assert window.font().pixelSize() == 14
        assert 'Microsoft YaHei UI' in window.steps.step_title.font().families()
        window.reduced_motion_action.setChecked(True)
        for width, height in [(1440, 960), (1100, 760)]:
            window.resize(width, height)
            for index in range(3):
                window.tabs.setCurrentIndex(index)
                qt_app.processEvents()
                assert window.tabs.currentWidget().isVisible()
                assert not window.tabs.tabBar().is_animating
                assert window.width() <= width, (window.width(), width)
                assert window.height() <= height, (window.height(), height,
                    [(window.tabs.tabText(i), window.tabs.widget(i).minimumSizeHint().height())
                     for i in range(window.tabs.count())],
                    [(window.steps.editor_tabs.tabText(i),
                      window.steps.editor_tabs.widget(i).minimumSizeHint().height())
                     for i in range(window.steps.editor_tabs.count())])
                if captures:
                    path = Path(captures)
                    path.mkdir(parents=True, exist_ok=True)
                    assert window.grab().save(str(path / f'fresh-{width}-page-{index}.png'))
        window.tabs.setCurrentWidget(window.steps)
        window.steps.open_run_button.click()
        qt_app.processEvents()
        assert window.steps.editor_tabs.currentWidget() is window.steps.run_panel
        scroll = window.steps.run_panel.findChild(QScrollArea)
        assert scroll.verticalScrollBar().maximum() > 0
        scroll.ensureWidgetVisible(window.steps.run_panel.outputs)
        qt_app.processEvents()
        assert scroll.verticalScrollBar().value() > 0
        assert window.height() <= 760
        if captures:
            assert window.grab().save(str(Path(captures) / 'fresh-1100-run-scrolled.png'))
        window.tabs.setCurrentIndex(2)
        pane = window.interfaces.pane
        assert pane.target_choice.count() == 3
        assert pane.edit_target_button.isVisible() and pane.edit_target_button.isEnabled()
        pane.canvas.select_region('strategy-0')
        pane._region_selected('strategy-0')
        qt_app.processEvents()
        assert pane.region_properties.isVisible()
        assert pane.region_properties.height() >= pane.region_properties.minimumSizeHint().height()
        if captures:
            assert window.grab().save(str(Path(captures) / 'fresh-1100-target-selected.png'))
        pane.edit_target_button.click()
        _wait(qt_app, lambda: not window.steps.is_busy)
        assert window.tabs.currentWidget() is window.steps
        assert window.steps.snapshot['program_id'] == original_program
        assert not window.steps.dirty and not pane.dirty
        window.steps.step_title.setText('尚未保存的标题')
        assert window.steps.dirty
        window.chrome_close_button.click()
        assert window.isVisible() and window.steps.dirty
        window.steps.discard()
        assert not list((store.session / 'commands').glob('*.json'))
    _run_main(monkeypatch, qt_app, root.parent, inspect, session=store.session)
