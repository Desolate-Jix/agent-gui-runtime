"""原生审核导航改版不改变数据操作或开发者入口。"""
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QPushButton, QToolBar
from PySide6.QtTest import QTest

from app.desktop_review.window import ReviewMainWindow, ensure_application
from tests.test_desktop_review_window import _Facade, _wait_workers


def test_review_navigation_is_native_persistent_and_keeps_developer_actions():
    ensure_application()
    window = ReviewMainWindow(_Facade([]))
    try:
        rail = window.findChild(QToolBar, "reviewNavigation")
        assert rail is not None
        assert window.toolBarArea(rail) == Qt.ToolBarArea.LeftToolBarArea
        assert not rail.isMovable()
        assert all(action in rail.actions() for action in (
            window.inbox_action, window.graph_review_action, window.workflow_library_action,
        ))
        assert all(action in window.developer_menu.actions() for action in (
            window.connections_action, window.single_step_action, window.model_setup_action,
        ))
        assert window.inbox_action.isChecked()
        assert not window.graph_review_action.isChecked()
        assert window.header_title.text() == "待审核流程"
        assert not window.workspace and not window.is_dirty
    finally:
        _wait_workers(window)
        window.close()


def test_full_window_header_does_not_clip_title_or_refresh_control():
    app = ensure_application()
    window = ReviewMainWindow(_Facade([]))
    try:
        for width, height in ((1440, 900), (1080, 680)):
            window.resize(width, height)
            window.show()
            app.processEvents()
            QTest.qWait(20)
            header = window.findChild(QToolBar, "reviewHeader")
            refresh = header.widgetForAction(window.refresh_action)
            assert window.header_title.height() >= window.header_title.fontMetrics().height()
            assert refresh.height() >= refresh.sizeHint().height()
            assert window.width() == width and window.height() == height
    finally:
        _wait_workers(window)
        window.close()


def test_reduce_motion_setting_is_independent_of_review_and_save_state():
    ensure_application()
    window = ReviewMainWindow(_Facade([]))
    try:
        assert window.reduce_motion_action.isCheckable()
        window.reduce_motion_action.setChecked(True)
        assert window._animations_enabled is False
        window.reduce_motion_action.setChecked(False)
        assert window._animations_enabled is True
        assert not window.workspace and not window.is_dirty
        assert not window.save_action.isEnabled()
    finally:
        _wait_workers(window)
        window.close()


def test_navigation_follows_actual_view_and_never_discards_graph_edits(tmp_path):
    from tests.test_formal_graph_review_pane import _runtime, _wait

    app = ensure_application()
    store, _, facade, graph = _runtime(tmp_path)
    window = ReviewMainWindow(facade)
    try:
        window.open_graph_review(graph["logical_workflow_id"])
        _wait(app, lambda: window._graph_pane is not None and not window._graph_pane.is_busy and not window._jobs)
        pane = window._graph_pane
        assert window.graph_review_action.isChecked()
        assert not window.inbox_action.isChecked()
        pane.node_meaning_edit.setText("待保存的人工修改")
        assert pane.is_dirty
        window.inbox_action.trigger()
        assert window._graph_active() and pane.is_dirty
        assert window.graph_review_action.isChecked() and not window.inbox_action.isChecked()
        window.reduce_motion_action.setChecked(True)
        assert not pane.animations_enabled and pane.is_dirty
        pane.revert_edits()
        _wait(app, lambda: not pane.is_busy)
        window.inbox_action.trigger()
        assert not window._graph_active()
        assert window.inbox_action.isChecked()
        assert window.source_status.text() == "来源：尚未加载"
        assert window.revision_status.text() == "修订：—"
    finally:
        if window._graph_pane is not None:
            _wait(app, lambda: not window._graph_pane.is_busy and not window._graph_pane._jobs)
            window._graph_pane._set_dirty(False)
        _wait_workers(window)
        window.close()
        facade.close()
        store.close()


def test_graph_evidence_headers_remain_readable_in_full_window(tmp_path):
    from tests.test_formal_graph_review_pane import _runtime, _wait

    app = ensure_application()
    store, _, facade, graph = _runtime(tmp_path)
    window = ReviewMainWindow(facade)
    window.resize(1080, 680)
    window.show()
    try:
        window.open_graph_review(graph["logical_workflow_id"])
        _wait(app, lambda: window._graph_pane is not None and not window._graph_pane.is_busy and not window._jobs)
        pane = window._graph_pane
        for kind in ("node", "edge"):
            if kind == "edge":
                pane._edge_selected(graph["graph"]["edges"][0]["edge_id"])
                _wait(app, lambda: not pane.is_busy and not pane._jobs)
            app.processEvents()
            for label in (pane.before_title_label, pane.after_title_label):
                if label.isVisible():
                    assert label.width() >= label.fontMetrics().horizontalAdvance(label.text())
                    assert label.height() >= label.fontMetrics().height()
            for box in (pane.before_box, pane.after_box):
                if box.isVisible():
                    for button in box.findChildren(QPushButton):
                        if button.isVisible():
                            left = button.mapTo(box, QPoint()).x()
                            assert 0 <= left and left + button.width() <= box.width()
            assert pane.review_graph_button.mapTo(window, QPoint()).y() + pane.review_graph_button.height() <= window.height()
            assert window.width() == 1080
    finally:
        if window._graph_pane is not None:
            _wait(app, lambda: not window._graph_pane.is_busy and not window._graph_pane._jobs)
        _wait_workers(window)
        window.close()
        facade.close()
        store.close()
