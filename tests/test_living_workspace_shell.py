from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QToolBar
from PySide6.QtTest import QTest
import time
from app.desktop_review.window import ReviewMainWindow, ensure_application
from test_formal_graph_exact_review import _runtime, TASK, BATCH

APP = ensure_application()


def wait_project_ready(pane):
    deadline = time.monotonic() + 15
    while pane.is_busy and time.monotonic() < deadline:
        APP.processEvents()
        time.sleep(0.02)
    assert not pane.is_busy, pane.status.text()


def test_shared_host_startup_lands_on_daily_page_and_shuts_down(tmp_path):
    from app.desktop_review.host import DesktopReviewHost
    host = DesktopReviewHost(tmp_path/'inbox.json', tmp_path/'reviews', 'fresh-living-startup-token')
    window = ReviewMainWindow(host.facade, connections=host.connections, startup=host.start, shutdown=host.close)
    try:
        for _ in range(750):
            APP.processEvents()
            if window._content_page is not None: break
            time.sleep(0.02)
        assert window._content_page is not None, window.status.currentMessage()
        assert window._review_stack.currentWidget() is window._content_page
    finally:
        window.close()
        for _ in range(750):
            APP.processEvents()
            if window._host_closed: break
            time.sleep(0.02)
        assert window._host_closed
        window.deleteLater(); QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        host.close()


def test_daily_pages_are_embedded_and_unsaved_interface_blocks_navigation(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    window = ReviewMainWindow(facade)
    try:
        assert hasattr(window, '_content_page')
        window.open_interface_library(pending_only=True)
        page = window._content_page
        assert window._review_stack.currentWidget() is page
        assert page.embedded
        nav = window.findChild(QToolBar, 'reviewNavigation')
        labels = [a.text() for a in nav.actions() if a.text()]
        assert '新学内容' in labels and '界面库' in labels and '流程项目' in labels
        assert not {'待审核流程', '流程图审核', '已发布流程'} & set(labels)
        page.items.setCurrentRow(0)
        page.pane.meaning_edit.setText('Unsaved interface edit')
        assert page.dirty
        window.open_graph_library()
        assert window._review_stack.currentWidget() is page
        page.pane.save_changes()
        assert not page.dirty
        window.open_graph_library()
        assert window._review_stack.currentWidget() is window._projects_page
        wait_project_ready(window._projects_page)
        window.open_interface_library()
        assert window._review_stack.currentWidget() is page
        assert page.filter.currentIndex() == 0
    finally:
        if hasattr(window, '_content_page') and window._content_page:
            window._content_page.pane.discard_changes()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        store.close()


def test_project_opens_latest_interface_without_separate_review(tmp_path):
    from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
    store, _, facade, _ = _runtime(tmp_path)
    try:
        original = facade.import_interface_content(TASK, BATCH, 'state-a')
        graph = facade.create_workflow_graph('A living project', TASK)
        facade.attach_interface_to_workflow(graph['logical_workflow_id'], original['interface_id'],
            original['version_id'], graph['revision'], graph['content_sha256'], 'attach')
        latest = facade.save_interface_content(original['interface_id'], original['revision'],
            original['content_sha256'], {'meaning': 'Latest saved meaning'}, 'save')
        pane = WorkflowProjectsPane(facade)
        wait_project_ready(pane)
        assert pane.snapshot is not None, pane.status.text()
        pane.node_selected(pane.snapshot['graph']['nodes'][0]['node_id'])
        assert pane.interface_pane.snapshot['version_id'] == latest['version_id']
        assert not pane.interface_pane._read_only
        assert pane.graph_view._revision['contract_version'] == 'workflow_project_view_v1'
        assert not pane.dirty
        pane.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        facade.close()
        store.close()


def test_project_relationship_edits_save_reopen_remove_and_detach_without_deleting_interface(tmp_path):
    from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, 'state-a')
        second = facade.import_interface_content(TASK, BATCH, 'state-b')
        graph = facade.create_workflow_graph('Editable relationship', TASK)
        for value in (first, second):
            graph = facade.attach_interface_to_workflow(graph['logical_workflow_id'], value['interface_id'],
                value['version_id'], graph['revision'], graph['content_sha256'], value['interface_id'])
        pane = WorkflowProjectsPane(facade)
        wait_project_ready(pane)
        pane.add_edge()
        pane.edge_region.setCurrentIndex(1)
        pane.edge_result.setText('Second interface visible')
        pane.save_current()
        assert not pane.dirty, pane.status.text()
        assert len(pane.snapshot['graph']['edges']) == 1
        pane.edge_selected(pane.snapshot['graph']['edges'][0]['edge_id'])
        pane.edge_condition.setText('Only after search')
        pane.title_edit.setText('Renamed project')
        pane.save_current()
        assert not pane.dirty, pane.status.text()
        pane.refresh()
        wait_project_ready(pane)
        assert pane.project_list.item(0).text() == 'Renamed project'
        assert pane.snapshot['graph']['edges'][0]['condition'] == 'Only after search'
        pane.edge_selected(pane.snapshot['graph']['edges'][0]['edge_id'])
        pane.remove_edge(); pane.save_current()
        assert not pane.dirty, pane.status.text()
        assert pane.snapshot['graph']['edges'] == []
        pane.node_selected(pane.snapshot['graph']['nodes'][0]['node_id'])
        interface_id = pane.interface_pane.snapshot['interface_id']
        pane.detach_interface()
        assert len(pane.snapshot['graph']['nodes']) == 1, pane.status.text()
        assert facade.load_interface_content(interface_id)
        pane.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        facade.close(); store.close()


def test_region_edit_controls_persist_full_metadata_and_bbox_and_optional_binding(tmp_path):
    from app.desktop_review.interface_pane import InterfaceReviewPane
    store, _, facade, _ = _runtime(tmp_path)
    try:
        value = facade.import_interface_content(TASK, BATCH, 'state-a')
        pane = InterfaceReviewPane(facade)
        errors = []; pane.errorRaised.connect(errors.append)
        pane.set_snapshot(value)
        region = value['content']['regions'][0]
        pane._region_selected(region['region_id'])
        assert not pane.dirty
        pane.region_name_edit.setText('Editable search')
        pane.region_kind_edit.setText('button')
        pane.region_text_edit.clear()
        pane.region_meaning_edit.setText('Search this query')
        pane.bbox_spins[2].setValue(30)
        pane.save_changes()
        assert not pane.dirty, errors
        saved = facade.load_interface_content(value['interface_id'])
        assert saved['content']['regions'][0]['name'] == 'Editable search'
        assert saved['content']['regions'][0]['recognition_text'] == ''
        assert saved['content']['regions'][0]['bbox'][2] == 30
        pane.add_region(); pane.save_changes()
        assert not pane.dirty, errors
        assert len(pane.snapshot['content']['regions']) == 2
        added_id = pane.snapshot['content']['regions'][-1]['region_id']
        pane._region_selected(added_id); pane.remove_selected_region(); pane.save_changes()
        assert len(pane.snapshot['content']['regions']) == 1, errors
        pane.binding_name.setText('Fresh app'); pane.binding_identity.setText('fresh.exe')
        pane.save_changes(); assert not pane.dirty, errors
        pane.binding_name.clear(); pane.binding_identity.clear()
        pane.save_changes(); assert not pane.dirty, errors
        assert pane.snapshot['application_binding'] is None
        pane.deleteLater(); QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        facade.close(); store.close()
