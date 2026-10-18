"""从流程图库进入现有审核面板，验证真实引用节点截图。"""
from copy import deepcopy
import pytest
from app.desktop_review.window import ReviewMainWindow, ensure_application
from app.desktop_review.workflow_library import WorkflowLibraryDialog
from test_formal_graph_exact_review import _runtime, TASK, BATCH
from test_formal_graph_review_pane import _wait


@pytest.mark.parametrize("composition", [True, False])
def test_graph_library_review_opens_composition_and_verified_evidence(tmp_path, monkeypatch, composition):
    app = ensure_application()
    store, _, facade, _ = _runtime(tmp_path)
    item = facade.import_interface_content(TASK, BATCH, "state-a")
    graph = (facade.create_workflow_graph("Explicit composition review", TASK) if composition
             else facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]}))
    graph = facade.attach_interface_to_workflow(graph["logical_workflow_id"], item["interface_id"],
        item["version_id"], graph["revision"], graph["content_sha256"], "review-entry")
    window = ReviewMainWindow(facade)
    try:
        def enter_review(dialog):
            dialog.graph_list.setCurrentRow(0)
            dialog.request_review()
            return 0
        monkeypatch.setattr(WorkflowLibraryDialog, "exec", enter_review)
        window.graph_library_action.trigger()
        _wait(app, lambda: not window._jobs and window._graph_pane is not None and not window._graph_pane._jobs)
        assert window._graph_active()
        assert window._graph_pane._snapshot["logical_workflow_id"] == graph["logical_workflow_id"]
        pane = window._graph_pane
        node = next(node for node in graph["graph"]["nodes"] if "interface_reference" in node)
        pane._node_selected(node["node_id"])
        _wait(app, lambda: not pane._jobs)
        assert pane._evidence_valid, pane.status_label.text()
        assert not pane.node_meaning_edit.isEnabled()
        assert not pane.before_canvas.isInteractive()
        assert not pane.review_graph_button.isEnabled()
        assert not pane.graph_relearn_button.isEnabled()
        evidence = facade.load_graph_node_evidence(graph["logical_workflow_id"], graph["revision"],
            graph["content_sha256"], node["node_id"])
        for key, value in (("screenshot_id", "unrelated-shot"), ("width", 999), ("sha256", "0" * 64)):
            invalid = deepcopy(evidence)
            invalid["screenshot"][key] = value
            with pytest.raises(ValueError):
                pane._validated_evidence(invalid, node["node_id"])
        source_key = "interfaces" if composition else "interface_composition"
        pane._snapshot["source_refs"][source_key] = []
        with pytest.raises(ValueError):
            pane._validated_evidence(evidence, node["node_id"])
    finally:
        _wait(app, lambda: not window._jobs and (window._graph_pane is None or not window._graph_pane._jobs))
        window.close()
        facade.close()
        store.close()
