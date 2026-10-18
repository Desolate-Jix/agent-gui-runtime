"""普通窗口按钮无需先选择旧批次即可进入新内容和图库。"""
from PySide6.QtWidgets import QApplication

from app.desktop_review.content_library import InterfaceContentLibrary
from app.desktop_review.workflow_library import WorkflowLibraryDialog
from app.desktop_review.window import ReviewMainWindow
from test_formal_graph_exact_review import _runtime, TASK

_APP = QApplication.instance() or QApplication([])


def test_toolbar_opens_actual_content_and_graph_libraries_without_workspace(tmp_path, monkeypatch):
    store, _, facade, _ = _runtime(tmp_path)
    seen = []
    graph = facade.create_workflow_graph("Explicit fresh graph", TASK)
    window = ReviewMainWindow(facade)
    try:
        def content_exec(dialog):
            assert dialog.items.count() == 3
            dialog.items.setCurrentRow(0)
            assert dialog.pane.snapshot["interface_id"]
            seen.append("content")
            return 0
        def graph_exec(dialog):
            assert dialog.graph_list.count() == 1
            dialog.graph_list.setCurrentRow(0)
            assert dialog.graph_view._revision["logical_workflow_id"] == graph["logical_workflow_id"]
            seen.append("graph")
            return 0
        monkeypatch.setattr(InterfaceContentLibrary, "exec", content_exec)
        monkeypatch.setattr(WorkflowLibraryDialog, "exec", graph_exec)
        assert window.workspace is None
        window.interface_library_action.trigger()
        window.graph_library_action.trigger()
        assert seen == ["content", "graph"]
    finally:
        window.close()
        facade.close()
        store.close()
