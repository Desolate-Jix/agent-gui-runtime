from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QCoreApplication, QEvent, Qt

from test_formal_graph_exact_review import BINDING, BATCH, TASK, _runtime
from app.desktop_review.window import ensure_application


_APP = ensure_application()


def _dispose(dialog) -> None:
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()


def test_empty_library_is_independent_from_pending_batches_and_explains_entry(tmp_path):
    from app.desktop_review.workflow_library import WorkflowLibraryDialog

    store, _, facade, _ = _runtime(tmp_path)
    try:
        dialog = WorkflowLibraryDialog(facade)
        try:
            assert dialog.graph_list.count() == 0
            assert "没有已保存流程图" in dialog.status.text()
            assert "当前工作区" in dialog.status.text()
            assert not dialog.review_button.isEnabled()
        finally:
            _dispose(dialog)
    finally:
        facade.close()
        store.close()


def test_library_selects_real_graph_and_opens_its_exact_interface_version(tmp_path):
    from app.desktop_review.workflow_library import WorkflowLibraryDialog

    store, _, facade, _ = _runtime(tmp_path)
    try:
        v1 = facade.import_interface_content(TASK, BATCH, "state-a")
        facade.review_interface_content(v1["interface_id"], v1["revision"], v1["content_sha256"], deepcopy(BINDING))
        graph = facade.create_workflow_graph("Synthetic standalone workflow", TASK)
        attached = facade.attach_interface_to_workflow(
            graph["logical_workflow_id"], v1["interface_id"], v1["version_id"],
            graph["revision"], graph["content_sha256"], "workflow-library-v1",
        )
        v2 = facade.save_interface_content(
            v1["interface_id"], v1["revision"], v1["content_sha256"],
            {"meaning": "Synthetic newer draft"}, "workflow-library-v2",
        )
        dialog = WorkflowLibraryDialog(facade)
        try:
            assert dialog.graph_list.count() == 1
            dialog.graph_list.setCurrentRow(0)
            assert dialog.graph_view._revision["logical_workflow_id"] == attached["logical_workflow_id"]
            assert dialog.node_list.count() == 1
            dialog.node_list.setCurrentRow(0)
            dialog.open_exact_reference()
            assert dialog.interface_pane.snapshot["version_id"] == v1["version_id"]
            assert not dialog.interface_pane.save_button.isEnabled()
            assert not dialog.interface_pane.review_button.isEnabled()
            dialog.edit_latest_interface()
            assert dialog.interface_pane.snapshot["version_id"] == v2["version_id"]
            assert dialog.interface_pane.save_button.isEnabled()
            assert "旧版" in dialog.status.text()
        finally:
            _dispose(dialog)
    finally:
        facade.close()
        store.close()


def test_library_attaches_detaches_only_membership_and_emits_review_request(tmp_path):
    from app.desktop_review.workflow_library import WorkflowLibraryDialog

    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        second = facade.import_interface_content(TASK, BATCH, "state-b")
        for value in (first, second):
            facade.review_interface_content(value["interface_id"], value["revision"], value["content_sha256"], deepcopy(BINDING))
        graph = facade.create_workflow_graph("Synthetic composition only", TASK)
        graph = facade.attach_interface_to_workflow(
            graph["logical_workflow_id"], first["interface_id"], first["version_id"],
            graph["revision"], graph["content_sha256"], "workflow-library-first",
        )
        dialog = WorkflowLibraryDialog(facade)
        try:
            dialog.graph_list.setCurrentRow(0)
            index = next(
                row for row in range(dialog.interface_versions.count())
                if dialog.interface_versions.itemData(row, Qt.ItemDataRole.UserRole)["interface_id"] == second["interface_id"]
            )
            dialog.interface_versions.setCurrentIndex(index)
            dialog.attach_selected_interface()
            assert dialog.graph_view._revision["revision"] == graph["revision"] + 1
            assert dialog.node_list.count() == 2
            second_row = next(
                row for row in range(dialog.node_list.count())
                if dialog.node_list.item(row).data(Qt.ItemDataRole.UserRole)["interface_reference"]["interface_id"] == second["interface_id"]
            )
            dialog.node_list.setCurrentRow(second_row)
            dialog.open_exact_reference()
            assert dialog.interface_pane.snapshot["interface_id"] == second["interface_id"]
            dialog.node_list.setCurrentRow(1 - second_row)
            assert dialog.interface_pane.isHidden()
            assert dialog._reference is None
            dialog.node_list.setCurrentRow(second_row)
            dialog.detach_selected_reference()
            assert dialog.node_list.count() == 1
            requested: list[str] = []
            dialog.reviewRequested.connect(requested.append)
            dialog.request_review()
            assert requested == [graph["logical_workflow_id"]]
            assert "审核、发布和执行仍是独立步骤" in dialog.status.text()
        finally:
            _dispose(dialog)
    finally:
        facade.close()
        store.close()


def test_library_refuses_refresh_switch_or_reject_while_latest_editor_is_dirty(tmp_path):
    from app.desktop_review.workflow_library import WorkflowLibraryDialog

    store, _, facade, _ = _runtime(tmp_path)
    try:
        version = facade.import_interface_content(TASK, BATCH, "state-a")
        facade.review_interface_content(version["interface_id"], version["revision"], version["content_sha256"], deepcopy(BINDING))
        first = facade.create_workflow_graph("Synthetic guarded first", TASK)
        first = facade.attach_interface_to_workflow(
            first["logical_workflow_id"], version["interface_id"], version["version_id"],
            first["revision"], first["content_sha256"], "workflow-library-guard-first",
        )
        other = facade.import_interface_content(TASK, BATCH, "state-b")
        facade.review_interface_content(other["interface_id"], other["revision"], other["content_sha256"], deepcopy(BINDING))
        first = facade.attach_interface_to_workflow(
            first["logical_workflow_id"], other["interface_id"], other["version_id"],
            first["revision"], first["content_sha256"], "workflow-library-guard-second",
        )
        second = facade.create_workflow_graph("Synthetic guarded second", TASK)
        dialog = WorkflowLibraryDialog(facade)
        try:
            first_row = next(
                row for row in range(dialog.graph_list.count())
                if dialog.graph_list.item(row).data(Qt.ItemDataRole.UserRole)["logical_workflow_id"] == first["logical_workflow_id"]
            )
            second_row = next(
                row for row in range(dialog.graph_list.count())
                if dialog.graph_list.item(row).data(Qt.ItemDataRole.UserRole)["logical_workflow_id"] == second["logical_workflow_id"]
            )
            dialog.graph_list.setCurrentRow(first_row)
            first_node_row = next(
                row for row in range(dialog.node_list.count())
                if dialog.node_list.item(row).data(Qt.ItemDataRole.UserRole)["interface_reference"]["interface_id"] == version["interface_id"]
            )
            other_node_row = next(
                row for row in range(dialog.node_list.count())
                if dialog.node_list.item(row).data(Qt.ItemDataRole.UserRole)["interface_reference"]["interface_id"] == other["interface_id"]
            )
            dialog.node_list.setCurrentRow(first_node_row)
            dialog.open_exact_reference()
            dialog.edit_latest_interface()
            dialog.interface_pane.meaning_edit.setText("Unsaved synthetic edit")
            assert dialog.interface_pane.dirty
            dialog.refresh()
            assert dialog.interface_pane.dirty
            dialog.node_list.setCurrentRow(other_node_row)
            assert dialog.node_list.currentItem().data(Qt.ItemDataRole.UserRole)["interface_reference"]["interface_id"] == version["interface_id"]
            dialog.graph_list.setCurrentRow(second_row)
            assert dialog.graph_view._revision["logical_workflow_id"] == first["logical_workflow_id"]
            assert dialog.graph_list.currentItem().data(Qt.ItemDataRole.UserRole)["logical_workflow_id"] == first["logical_workflow_id"]
            dialog.show()
            _APP.processEvents()
            dialog.reject()
            assert dialog.isVisible()
            assert "先保存或放弃" in dialog.status.text()
            dialog.interface_pane.discard_changes()
        finally:
            _dispose(dialog)
    finally:
        facade.close()
        store.close()
