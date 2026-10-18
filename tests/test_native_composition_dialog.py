from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.desktop_review.content_library import WorkflowCompositionDialog
from tests.test_formal_graph_review_pane import _runtime


_APP = QApplication.instance() or QApplication([])


def test_composition_dialog_actual_facade_create_attach_and_empty_input_feedback(tmp_path) -> None:
    store, _, facade, graph = _runtime(tmp_path)
    try:
        interface = facade.import_interface_content("fresh-pane-task", "fresh-pane-batch", "state-a")
        dialog = WorkflowCompositionDialog(facade, interface)
        dialog._attach()
        assert "选择" in dialog.status.text()
        dialog._create()
        assert "请输入" in dialog.status.text()
        dialog.title_edit.setText("独立界面流程")
        dialog._create()
        assert "已新建并加入" in dialog.status.text()
        graphs = facade.list_workflow_graphs()
        created = next(item for item in graphs if item["title"] == "独立界面流程")
        loaded = facade.load_graph_revision(created["logical_workflow_id"], None)
        assert len(loaded["graph"]["nodes"]) == 1
        assert loaded["graph"]["edges"] == []
        dialog.detach.click()
        assert "已移除" in dialog.status.text(), dialog.status.text()
        assert facade.load_graph_revision(created["logical_workflow_id"])["graph"]["nodes"] == []
        dialog.attach.click()
        assert "已加入" in dialog.status.text(), dialog.status.text()
        assert facade.load_graph_revision(created["logical_workflow_id"])["graph"]["edges"] == []
        dialog.close()
    finally:
        facade.close(); store.close()
