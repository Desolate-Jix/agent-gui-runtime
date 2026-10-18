"""原始观察不能混成已学习界面；学习内容可直达同段流程。"""
from app.desktop_review.learning_catalog import annotate_learning_content, learning_project_notice
from app.desktop_review.window import ReviewMainWindow, ensure_application
from tests.test_formal_fresh_graph_source import _stage
from tests.test_observed_interface_project import _complete
from tests.test_formal_fresh_learning_observation import _owner
from tests.test_formal_graph_review_pane import _wait


def test_raw_observation_is_diagnostic_and_completion_joins_existing_flow(tmp_path):
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    try:
        original = host.facade.import_interface_content(args["task_id"], staged["batch_id"], "observed-screen")
        raw = annotate_learning_content(host.facade, original)
        assert raw["learning_status"] == "observation_only"
        assert raw["learning_flow"]["logical_workflow_id"] == staged["logical_workflow_id"]
        completed = _complete(host, connection, segment, args, staged)
        assert annotate_learning_content(host.facade, completed)["learning_status"] == "interface_content"
        second = host.fresh_learning.stage(**{**args, "idempotency_key": "filled-state",
            "packet": _owner(tmp_path / "filled").observe(target_window_handle=4242, target_process_id=9001)})
        assert second["logical_workflow_id"] == staged["logical_workflow_id"]
        unlearned = host.facade.import_interface_content(args["task_id"], second["batch_id"], "observed-screen")
        assert unlearned["learning_status"] == "observation_only"
        matches = host.facade.search_interface_memory(args["task_id"])
        assert [item["interface_id"] for item in matches] == [completed["interface_id"]]
        graph = host.facade.load_workflow_project(staged["logical_workflow_id"])
        assert graph["graph"]["edges"] == []
        assert "尚未记录跳转" in learning_project_notice(graph)
    finally:
        host.close()


def test_normal_empty_interface_is_not_treated_as_automatic_observation(tmp_path):
    from test_formal_graph_exact_review import _runtime, TASK, BATCH
    store, _, facade, _ = _runtime(tmp_path)
    try:
        content = facade.import_interface_content(TASK, BATCH, "state-a")
        content["content"]["regions"] = []
        content["revision"] = 1
        view = annotate_learning_content(facade, content)
        assert view["learning_status"] == "interface_content"
        assert "learning_flow" not in view
    finally:
        store.close()


def test_closed_inbox_preserves_readable_history_without_claiming_learning_complete(tmp_path):
    host, _, _, _, args, staged = _stage(tmp_path)
    original = host.facade.import_interface_content(args["task_id"], staged["batch_id"], "observed-screen")
    host.close()
    view = annotate_learning_content(host.facade, original)
    assert view["interface_id"] == original["interface_id"]
    assert view["learning_status"] == "source_unavailable"
    assert view["learning_context_error"] == "store_closed"
    assert "learning_flow" not in view


def test_native_library_hides_capture_states_and_opens_automatic_flow(tmp_path):
    app = ensure_application()
    host, connection, segment, _, args, staged = _stage(tmp_path)
    window = None
    try:
        raw = host.facade.import_interface_content(args["task_id"], staged["batch_id"], "observed-screen")
        window = ReviewMainWindow(host.facade)
        window.open_interface_library()
        page = window._content_page
        assert page.items.count() == 0
        page.filter.setCurrentIndex(3)
        assert page.items.count() == 1
        assert page.items.item(0).data(256)["interface_id"] == raw["interface_id"]
        completed = _complete(host, connection, segment, args, staged)
        page.filter.setCurrentIndex(0)
        assert page.items.count() == 1
        assert page.items.item(0).data(256)["interface_id"] == completed["interface_id"]
        page.openLearningFlow.emit(staged["logical_workflow_id"])
        assert window._review_stack.currentWidget() is window._projects_page
        _wait(app, lambda: not window._projects_page.is_busy)
        assert window._projects_page.snapshot["logical_workflow_id"] == staged["logical_workflow_id"]
        assert window._projects_page.snapshot["graph"]["edges"] == []
    finally:
        if window is not None:
            if window._projects_page is not None:
                _wait(app, lambda: not window._projects_page.is_busy)
            window.close()
            window.deleteLater()
            app.processEvents()
        host.close()
