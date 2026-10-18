"""项目读取不可阻塞事件线程、覆盖新选择或提前释放资源。"""
from copy import deepcopy
import threading
import time

import pytest
from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import QApplication

from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), "后台项目读取未完成"


def _project(letter):
    from app.desktop_review.workflow_project import _view_digest
    value = {
        "contract_version": "workflow_project_view_v1",
        "logical_workflow_id": "workflow-" + letter * 64,
        "revision": 0, "content_sha256": "", "source_revision": 1,
        "source_sha256": letter * 64, "snapshot_id": None,
        "graph": {"workflow": {"goal": letter, "node_ids": [], "edge_ids": []},
                  "nodes": [], "edges": []},
        "warnings": [], "artifact_is_authorization": False, "execute_binding_enabled": False,
    }
    value["content_sha256"] = _view_digest(value)
    return value


class DelayedFacade:
    def __init__(self, projects=(), *, list_delay=0, load_delay=0):
        self.projects = {value["logical_workflow_id"]: value for value in projects}
        self.list_delay = list_delay
        self.load_delay = load_delay
        self.calls = []
        self.closed = False

    def list_batches(self):
        return []

    def list_workflow_projects(self):
        self.calls.append(("list", None, threading.get_ident()))
        time.sleep(self.list_delay)
        return [{"logical_workflow_id": key, "title": value["graph"]["workflow"]["goal"]}
                for key, value in self.projects.items()]

    def load_workflow_project(self, workflow_id):
        self.calls.append(("load", workflow_id, threading.get_ident()))
        time.sleep(self.load_delay)
        assert not self.closed, "资源在读取结束前被关闭"
        return deepcopy(self.projects[workflow_id])

    def close(self):
        self.closed = True


def _dispose(qapp, pane):
    _wait(qapp, lambda: not pane.is_busy)
    pane.close()
    pane.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_delayed_directory_does_not_block_constructor_or_event_loop(qapp):
    facade = DelayedFacade(list_delay=0.3)
    beats = []
    timer = QTimer()
    timer.timeout.connect(lambda: beats.append(time.monotonic()))
    timer.start(10)
    start = time.monotonic()
    pane = WorkflowProjectsPane(facade)
    elapsed = time.monotonic() - start
    try:
        assert elapsed < 0.2
        _wait(qapp, lambda: len(beats) >= 3)
        _wait(qapp, lambda: bool(facade.calls) and not pane.is_busy)
        assert facade.calls[0][2] != threading.get_ident()
        assert "还没有流程项目" in pane.status.text()
    finally:
        timer.stop()
        _dispose(qapp, pane)


def test_detail_loading_keeps_timer_alive_and_runs_off_thread(qapp):
    facade = DelayedFacade([_project('a')], load_delay=0.3)
    pane = WorkflowProjectsPane(facade)
    try:
        _wait(qapp, lambda: any(call[0] == 'load' for call in facade.calls))
        assert pane.snapshot is None
        assert "正在打开" in pane.status.text()
        assert pane.project_list.isEnabled()
        fired = []
        QTimer.singleShot(10, lambda: fired.append(True))
        _wait(qapp, lambda: fired)
        assert pane.is_busy
        _wait(qapp, lambda: not pane.is_busy)
        assert pane.snapshot['logical_workflow_id'] == _project('a')['logical_workflow_id']
        assert all(call[2] != threading.get_ident() for call in facade.calls)
    finally:
        _dispose(qapp, pane)


def test_direct_link_during_directory_load_only_loads_requested_project_once(qapp):
    facade = DelayedFacade([_project('a'), _project('b')], list_delay=0.2, load_delay=0.1)
    pane = WorkflowProjectsPane(facade)
    try:
        pane.open_project(_project('b')['logical_workflow_id'])
        pane.open_project(_project('b')['logical_workflow_id'])
        _wait(qapp, lambda: not pane.is_busy)
        assert pane.snapshot['logical_workflow_id'] == _project('b')['logical_workflow_id']
        assert [(kind, key) for kind, key, _ in facade.calls] == [
            ('list', None), ('load', _project('b')['logical_workflow_id'])]
        pane.open_project(_project('a')['logical_workflow_id'])
        pane.open_project(_project('a')['logical_workflow_id'])
        _wait(qapp, lambda: not pane.is_busy)
        assert len([call for call in facade.calls if call[0] == 'load']) == 2
    finally:
        _dispose(qapp, pane)


def test_stale_detail_is_not_installed_after_new_selection(qapp):
    facade = DelayedFacade([_project('a'), _project('b'), _project('c')], load_delay=0.15)
    pane = WorkflowProjectsPane(facade)
    installed = []
    pane.dirtyChanged.connect(lambda _: installed.append(pane.snapshot['logical_workflow_id']))
    try:
        _wait(qapp, lambda: any(call[0] == 'load' for call in facade.calls))
        pane.open_project(_project('b')['logical_workflow_id'])
        pane.open_project(_project('c')['logical_workflow_id'])
        _wait(qapp, lambda: not pane.is_busy)
        assert installed == [_project('c')['logical_workflow_id']]
        assert [key for kind, key, _ in facade.calls if kind == 'load'] == [
            _project('a')['logical_workflow_id'], _project('c')['logical_workflow_id']]
    finally:
        _dispose(qapp, pane)


def test_dirty_changes_and_selection_survive_refresh_and_switch(qapp):
    facade = DelayedFacade([_project('a'), _project('b')])
    pane = WorkflowProjectsPane(facade)
    try:
        _wait(qapp, lambda: not pane.is_busy)
        pane.title_edit.setText("未保存项目名称")
        before = len(facade.calls)
        pane.refresh()
        pane.project_list.setCurrentRow(1)
        pane.open_project(_project('b')['logical_workflow_id'])
        assert pane.dirty
        assert pane.title_edit.text() == "未保存项目名称"
        assert pane.project_list.currentRow() == 0
        assert len(facade.calls) == before
        pane._dirty = False
    finally:
        _dispose(qapp, pane)


def test_new_dirty_edit_prevents_inflight_result_replacement(qapp):
    facade = DelayedFacade([_project('a')], load_delay=0.2)
    pane = WorkflowProjectsPane(facade)
    try:
        _wait(qapp, lambda: any(call[0] == 'load' for call in facade.calls))
        pane._dirty = True
        pane.title_edit.setText("外部编辑草稿")
        _wait(qapp, lambda: not pane.is_busy)
        assert pane.snapshot is None
        assert pane.dirty and pane.title_edit.text() == "外部编辑草稿"
        assert "保留编辑" in pane.status.text()
        pane._dirty = False
    finally:
        _dispose(qapp, pane)


def test_pane_close_and_deferred_delete_wait_for_inflight_read(qapp):
    from shiboken6 import isValid
    facade = DelayedFacade([_project('a')], load_delay=0.2)
    pane = WorkflowProjectsPane(facade)
    _wait(qapp, lambda: any(call[0] == 'load' for call in facade.calls))
    assert pane.close()
    pane.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert isValid(pane) and pane.is_busy
    _wait(qapp, lambda: not isValid(pane))
    assert not facade.closed


def test_window_switches_page_immediately_and_can_leave_while_loading(qapp):
    from app.desktop_review.window import ReviewMainWindow
    facade = DelayedFacade([_project('a'), _project('b')], list_delay=0.2, load_delay=0.15)
    window = ReviewMainWindow(facade)
    try:
        start = time.monotonic()
        window.open_learning_flow(_project('b')['logical_workflow_id'])
        assert time.monotonic() - start < 0.15
        assert window._review_stack.currentWidget() is window._projects_page
        assert window._allow_daily_leave()
        assert window._projects_page.snapshot is None
        _wait(qapp, lambda: not window._projects_page.is_busy)
        assert window._projects_page.snapshot['logical_workflow_id'] == _project('b')['logical_workflow_id']
        assert len([call for call in facade.calls if call[0] == 'load']) == 1
    finally:
        _wait(qapp, lambda: not window._projects_page.is_busy)
        window.close()
        window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_window_close_finishes_automatically_without_releasing_busy_facade(qapp):
    from app.desktop_review.window import ReviewMainWindow
    facade = DelayedFacade([_project('a')], load_delay=0.2)
    window = ReviewMainWindow(facade)
    window.open_graph_library()
    _wait(qapp, lambda: any(call[0] == 'load' for call in facade.calls))
    start = time.monotonic()
    window.close()
    assert time.monotonic() - start < 0.1
    assert not facade.closed
    assert window._close_after_project_load
    _wait(qapp, lambda: facade.closed)
    assert window._projects_page.snapshot is None
    window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_window_deferred_delete_preserves_child_thread_until_finished(qapp):
    from shiboken6 import isValid
    from app.desktop_review.window import ReviewMainWindow
    facade = DelayedFacade([_project('a')], load_delay=0.2)
    window = ReviewMainWindow(facade)
    window.open_graph_library()
    _wait(qapp, lambda: any(call[0] == 'load' for call in facade.calls))
    window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert isValid(window)
    _wait(qapp, lambda: not isValid(window))


def test_summary_api_is_preferred_without_eager_loading_unselected_projects(qapp):
    class SummaryFacade(DelayedFacade):
        def list_workflow_project_summaries(self):
            return super().list_workflow_projects()

        def list_workflow_projects(self):
            raise AssertionError("摘要列表不可提前装载所有项目视图")

    facade = SummaryFacade([_project('a'), _project('b')])
    pane = WorkflowProjectsPane(facade)
    try:
        _wait(qapp, lambda: not pane.is_busy)
        assert pane.project_list.count() == 2
        assert [key for kind, key, _ in facade.calls if kind == 'load'] == [_project('a')['logical_workflow_id']]
    finally:
        _dispose(qapp, pane)


def test_returning_to_visible_project_invalidates_other_inflight_selection(qapp):
    facade = DelayedFacade([_project('a'), _project('b')], load_delay=0.08)
    pane = WorkflowProjectsPane(facade)
    try:
        _wait(qapp, lambda: not pane.is_busy)
        pane.open_project(_project('b')['logical_workflow_id'])
        pane.open_project(_project('a')['logical_workflow_id'])
        _wait(qapp, lambda: not pane.is_busy)
        assert pane.snapshot['logical_workflow_id'] == _project('a')['logical_workflow_id']
        assert pane.project_list.currentRow() == 0
    finally:
        _dispose(qapp, pane)


def test_read_error_is_visible_and_preserves_previous_snapshot(qapp):
    class BrokenFacade(DelayedFacade):
        def load_workflow_project(self, workflow_id):
            if workflow_id == _project('b')['logical_workflow_id']:
                raise ValueError("Synthetic broken project")
            return super().load_workflow_project(workflow_id)

    pane = WorkflowProjectsPane(BrokenFacade([_project('a'), _project('b')]))
    try:
        _wait(qapp, lambda: not pane.is_busy)
        pane.open_project(_project('b')['logical_workflow_id'])
        _wait(qapp, lambda: not pane.is_busy)
        assert "Synthetic broken project" in pane.status.text()
        assert pane.snapshot['logical_workflow_id'] == _project('a')['logical_workflow_id']
        assert pane.project_list.currentRow() == 0
        assert pane.title_edit.isEnabled()
    finally:
        _dispose(qapp, pane)
