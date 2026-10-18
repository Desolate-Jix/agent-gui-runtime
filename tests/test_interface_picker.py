from copy import deepcopy
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QDialog

from app.desktop_review.window import ensure_application
from test_formal_graph_exact_review import _runtime, _batch, TASK, BATCH, TOKEN, BINDING

APP = ensure_application()


def wait_ready(dialog):
    deadline = time.monotonic() + 15
    while dialog.busy and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.02)
    APP.processEvents()
    assert not dialog.busy, dialog.status.text()


def wait_project_ready(pane):
    deadline = time.monotonic() + 15
    while pane.is_busy and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.02)
    assert not pane.is_busy, pane.status.text()


def dispose(widget):
    if hasattr(widget, 'is_busy'):
        wait_project_ready(widget)
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    APP.processEvents()


@pytest.fixture
def workspace(tmp_path):
    store, service, facade, _ = _runtime(tmp_path)
    values = [facade.import_interface_content(TASK, BATCH, name)
              for name in ('state-a', 'state-b', 'state-c')]
    facade.review_interface_content(values[1]['interface_id'], values[1]['revision'],
                                    values[1]['content_sha256'], deepcopy(BINDING))
    grant = service.reviewer_call(TOKEN, 'create_connection', {'task_id': 'other-task', 'agent_name': 'other'})
    batch = _batch(); batch['batch_id'] = 'other-batch'
    service.agent_call(grant['token'], 'submit_batch', batch)
    other = facade.import_interface_content('other-task', 'other-batch', 'state-a')
    graph = facade.create_workflow_graph('Picker project', TASK)
    first = values[0]
    graph = facade.attach_interface_to_workflow(graph['logical_workflow_id'], first['interface_id'],
        first['version_id'], graph['revision'], graph['content_sha256'], 'initial')
    yield facade, graph, values, other
    facade.close(); store.close()


def item_for(dialog, interface_id):
    return next(dialog.items.item(i) for i in range(dialog.items.count())
                if dialog.items.item(i).data(Qt.ItemDataRole.UserRole)['interface_id'] == interface_id)


def test_picker_shows_thumbnails_and_explains_unavailable_items(workspace):
    from app.desktop_review.interface_picker import InterfacePickerDialog
    facade, graph, values, other = workspace
    dialog = InterfacePickerDialog(facade, facade.load_workflow_project(graph['logical_workflow_id']))
    try:
        wait_ready(dialog)
        assert dialog.items.count() == 4, dialog.status.text()
        present = item_for(dialog, values[0]['interface_id'])
        assert '已在项目中' in present.text()
        assert not present.flags() & Qt.ItemFlag.ItemIsUserCheckable
        foreign = item_for(dialog, other['interface_id'])
        assert '其他学习连接' in foreign.text()
        assert not foreign.flags() & Qt.ItemFlag.ItemIsUserCheckable
        for value in values[1:]:
            item = item_for(dialog, value['interface_id'])
            assert item.flags() & Qt.ItemFlag.ItemIsUserCheckable
            assert not item.icon().isNull()
        assert not dialog.add_button.isEnabled()
    finally:
        dispose(dialog)


def test_search_keeps_multiselection_and_cancel_does_not_write(workspace):
    from app.desktop_review.interface_picker import InterfacePickerDialog
    facade, graph, values, _ = workspace
    dialog = InterfacePickerDialog(facade, facade.load_workflow_project(graph['logical_workflow_id']))
    try:
        wait_ready(dialog)
        item_for(dialog, values[1]['interface_id']).setCheckState(Qt.CheckState.Checked)
        dialog.search.setText('state-c')
        assert item_for(dialog, values[1]['interface_id']).isHidden()
        item_for(dialog, values[2]['interface_id']).setCheckState(Qt.CheckState.Checked)
        assert len(dialog.selected_references()) == 2
        assert '2' in dialog.add_button.text()
        assert '1' in dialog.selection_note.text()
        dialog.reject()
        assert facade.load_graph_revision(graph['logical_workflow_id']) == graph
    finally:
        dispose(dialog)


def test_project_picker_adds_selected_interfaces_atomically_and_opens_new_node(workspace):
    from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
    facade, graph, values, _ = workspace
    pane = WorkflowProjectsPane(facade)
    wait_project_ready(pane)
    try:
        assert pane.attach_button.text() == '＋ 添加已有界面'
        pane.attach_interface()
        dialog = pane.interface_picker
        wait_ready(dialog)
        for value in values[1:]:
            item_for(dialog, value['interface_id']).setCheckState(Qt.CheckState.Checked)
        dialog.add_selected(); wait_ready(dialog)
        assert dialog.result() == QDialog.DialogCode.Accepted, dialog.status.text()
        current = facade.load_graph_revision(graph['logical_workflow_id'])
        assert current['revision'] == graph['revision'] + 1
        assert len(pane.snapshot['graph']['nodes']) == 3
        assert not pane.snapshot['graph']['edges']
        assert pane._node_id is not None
        assert pane.interface_pane.snapshot['interface_id'] in {v['interface_id'] for v in values[1:]}
        assert pane.details.currentWidget() is pane.interface_pane
        assert '已加入 2 个界面' in pane.status.text()
        assert not current['graph']['execute_binding_enabled']
    finally:
        dispose(pane)


def test_stale_interface_preserves_selection_and_no_partial_add(workspace):
    from app.desktop_review.interface_picker import InterfacePickerDialog
    facade, graph, values, _ = workspace
    dialog = InterfacePickerDialog(facade, facade.load_workflow_project(graph['logical_workflow_id']))
    try:
        wait_ready(dialog)
        for value in values[1:]:
            item_for(dialog, value['interface_id']).setCheckState(Qt.CheckState.Checked)
        old = values[2]
        facade.save_interface_content(old['interface_id'], old['revision'], old['content_sha256'],
                                      {'meaning': 'New content after picker opened'}, 'concurrent-save')
        dialog.add_selected(); wait_ready(dialog)
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert '失败' in dialog.status.text()
        assert len(dialog.selected_references()) == 2
        assert facade.load_graph_revision(graph['logical_workflow_id']) == graph
        dialog.reload(); wait_ready(dialog)
        assert len(dialog.selected_references()) == 1
        assert '重新勾选' in dialog.status.text()
    finally:
        dispose(dialog)


def test_dirty_project_blocks_picker_without_discarding_changes(workspace):
    from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
    facade, _, _, _ = workspace
    pane = WorkflowProjectsPane(facade)
    wait_project_ready(pane)
    try:
        pane.title_edit.setText('Unsaved project')
        pane.attach_interface()
        assert pane.interface_picker is None
        assert pane.dirty
        assert pane.title_edit.text() == 'Unsaved project'
        assert '保存' in pane.status.text()
    finally:
        pane.discard_changes(); dispose(pane)


def test_add_preserves_existing_project_relationship_and_title(workspace):
    from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
    facade, graph, values, _ = workspace
    pane = WorkflowProjectsPane(facade)
    wait_project_ready(pane)
    try:
        pane.add_edge()
        pane.edge_result.setText('Existing observed condition')
        pane.title_edit.setText('Keep this project name')
        pane.save_current()
        assert not pane.dirty, pane.status.text()
        original_edges = deepcopy(pane.snapshot['graph']['edges'])
        pane.attach_interface(); dialog = pane.interface_picker
        wait_ready(dialog)
        item_for(dialog, values[1]['interface_id']).setCheckState(Qt.CheckState.Checked)
        dialog.add_selected(); wait_ready(dialog)
        assert dialog.result() == QDialog.DialogCode.Accepted, dialog.status.text()
        assert pane.snapshot['graph']['workflow']['goal'] == 'Keep this project name'
        assert pane.snapshot['graph']['edges'] == original_edges
    finally:
        dispose(pane)


def test_cancel_loading_waits_for_worker_without_writing(workspace, monkeypatch):
    from threading import Event
    from app.desktop_review.interface_picker import InterfacePickerDialog
    facade, graph, _, _ = workspace
    entered, release = Event(), Event()
    original = facade.list_interface_contents

    def held_read(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(facade, 'list_interface_contents', held_read)
    dialog = InterfacePickerDialog(facade, facade.load_workflow_project(graph['logical_workflow_id']))
    try:
        assert entered.wait(10)
        dialog.reject()
        assert dialog.busy
        assert dialog._closing
        release.set(); wait_ready(dialog)
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert facade.load_graph_revision(graph['logical_workflow_id']) == graph
    finally:
        release.set(); wait_ready(dialog); dispose(dialog)


def test_one_unreadable_thumbnail_stays_visible_with_reason(workspace, monkeypatch):
    from app.desktop_review.interface_picker import InterfacePickerDialog
    facade, graph, values, _ = workspace
    original = facade.load_interface_content_evidence

    def broken_one(interface_id, version_id=None):
        if interface_id == values[1]['interface_id']:
            raise ValueError('synthetic screenshot failure')
        return original(interface_id, version_id)

    monkeypatch.setattr(facade, 'load_interface_content_evidence', broken_one)
    dialog = InterfacePickerDialog(facade, facade.load_workflow_project(graph['logical_workflow_id']))
    try:
        wait_ready(dialog)
        broken = item_for(dialog, values[1]['interface_id'])
        assert '截图读取失败' in broken.text()
        assert not broken.flags() & Qt.ItemFlag.ItemIsUserCheckable
        assert item_for(dialog, values[2]['interface_id']).flags() & Qt.ItemFlag.ItemIsUserCheckable
    finally:
        dispose(dialog)


def test_main_window_close_does_not_release_resources_while_picker_reads(workspace, monkeypatch):
    from threading import Event
    from PySide6.QtGui import QCloseEvent
    from app.desktop_review.window import ReviewMainWindow
    facade, _, _, _ = workspace
    window = ReviewMainWindow(facade)
    window.open_graph_library()
    wait_project_ready(window._projects_page)
    entered, release = Event(), Event()
    original = facade.list_interface_contents
    closed = []

    def held_read(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(facade, 'list_interface_contents', held_read)
    monkeypatch.setattr(facade, 'close', lambda: closed.append(True))
    window._projects_page.attach_interface(); dialog = window._projects_page.interface_picker
    try:
        assert entered.wait(10)
        event = QCloseEvent(); window.closeEvent(event)
        assert not event.isAccepted()
        assert not closed
        window.open_interface_library()
        assert window._review_stack.currentWidget() is window._projects_page
    finally:
        release.set(); wait_ready(dialog); dialog.reject()
        dispose(window)


def test_parent_deferred_delete_waits_for_read_worker(workspace, monkeypatch):
    from threading import Event
    from shiboken6 import isValid
    from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
    facade, _, _, _ = workspace
    pane = WorkflowProjectsPane(facade)
    wait_project_ready(pane)
    entered, release = Event(), Event()
    original = facade.list_interface_contents

    def held_read(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(facade, 'list_interface_contents', held_read)
    pane.attach_interface(); dialog = pane.interface_picker
    try:
        assert entered.wait(10)
        pane.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert isValid(pane) and pane.is_busy
        release.set()
        deadline = time.monotonic() + 10
        while isValid(pane) and time.monotonic() < deadline:
            APP.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            time.sleep(0.02)
        assert not isValid(pane)
    finally:
        release.set()
        if isValid(pane):
            wait_ready(dialog); dispose(pane)


def test_thumbnail_bytes_must_match_evidence_digest(workspace, monkeypatch):
    from io import BytesIO
    from PIL import Image
    from app.desktop_review.interface_picker import InterfacePickerDialog
    facade, graph, _, _ = workspace
    original = facade._artifact_file
    buffer = BytesIO(); Image.new('RGB', (9, 9), 'red').save(buffer, format='PNG')

    class ChangedImage:
        def read_bytes(self):
            return buffer.getvalue()

    def changed_file(path, label):
        return ChangedImage() if label == '界面缩略图' else original(path, label)

    monkeypatch.setattr(facade, '_artifact_file', changed_file)
    dialog = InterfacePickerDialog(facade, facade.load_workflow_project(graph['logical_workflow_id']))
    try:
        wait_ready(dialog)
        assert dialog.items.count() == 4
        for index in range(dialog.items.count()):
            item = dialog.items.item(index)
            assert '截图内容已变化' in item.text()
            assert not item.flags() & Qt.ItemFlag.ItemIsUserCheckable
            assert item.icon().isNull()
    finally:
        dispose(dialog)
