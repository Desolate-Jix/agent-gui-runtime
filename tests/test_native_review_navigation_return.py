from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_formal_graph_review_pane import _runtime, _wait, _batch, TOKEN, BATCH
from tests.test_desktop_review_window import _Facade, _wait_workers
from app.desktop_review.window import ReviewMainWindow, ensure_application
from PySide6.QtCore import QCoreApplication, QEvent


def _dispose(window, app):
    _wait(app, lambda: not window._jobs and (window._graph_pane is None or (
        not window._graph_pane.is_busy and not window._graph_pane._jobs)))
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_return_from_graph_to_inbox_then_graph_review_reopens_current_workspace(tmp_path) -> None:
    app = ensure_application()
    store, _, facade, graph = _runtime(tmp_path)
    window = ReviewMainWindow(facade)
    try:
        window.open_graph_review(graph["logical_workflow_id"])
        _wait(app, lambda: window._graph_pane is not None and not window._graph_pane.is_busy and not window._jobs)
        window.inbox_action.trigger()
        assert not window._graph_active()
        window.graph_review_action.trigger()
        _wait(app, lambda: window._graph_pane is not None and not window._graph_pane.is_busy and not window._jobs)
        assert window._graph_active()
    finally:
        _wait(app, lambda: window._graph_pane is None or (not window._graph_pane.is_busy and not window._graph_pane._jobs))
        _dispose(window, app)
        facade.close()
        store.close()


def test_selected_new_batch_wins_over_last_direct_graph_id(monkeypatch) -> None:
    app = ensure_application()
    facade = _Facade([])
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(facade, "load_batch_graph_revision", lambda task, batch: (calls.append((task, batch)) or {}), raising=False)
    window = ReviewMainWindow(facade)
    try:
        window._workspace = {"task_id": "new-task", "batch_id": "new-batch"}
        window._last_open_graph_id = "old-graph"
        window.open_graph_review()
        _wait(app, lambda: not window._jobs)
        assert calls == [("new-task", "new-batch")]
    finally:
        _wait_workers(window)
        _dispose(window, app)


def test_graph_review_without_workspace_or_last_graph_is_explicitly_blocked() -> None:
    window = ReviewMainWindow(_Facade([]))
    try:
        window.open_graph_review()
        assert "先从收件箱选择内容" in window.status.currentMessage()
    finally:
        _wait_workers(window)
        _dispose(window, ensure_application())


def test_failed_graph_install_cannot_poison_return_target(tmp_path, monkeypatch) -> None:
    app = ensure_application()
    store, _, facade, graph = _runtime(tmp_path)
    window = ReviewMainWindow(facade)
    try:
        window.open_graph_review(graph["logical_workflow_id"])
        _wait(app, lambda: window._graph_pane is not None and not window._graph_pane.is_busy and not window._jobs)
        invalid_id = "workflow-" + "f" * 64
        monkeypatch.setattr(facade, "load_graph_revision", lambda *args: {"logical_workflow_id": invalid_id})
        window.open_graph_review(invalid_id)
        _wait(app, lambda: not window._jobs)
        assert window._last_open_graph_id == graph["logical_workflow_id"]
        assert window._graph_pane._snapshot == graph
    finally:
        _dispose(window, app)
        facade.close()
        store.close()


def test_direct_graph_return_keeps_context_until_a_batch_is_explicitly_selected(tmp_path, monkeypatch) -> None:
    app = ensure_application()
    store, _, facade, graph = _runtime(tmp_path)
    window = ReviewMainWindow(facade)
    try:
        window._workspace = facade.load_batch("fresh-pane-task", "fresh-pane-batch")
        window.open_graph_review(graph["logical_workflow_id"])
        _wait(app, lambda: window._graph_pane is not None and not window._graph_pane.is_busy and not window._jobs)
        calls = []
        monkeypatch.setattr(facade, "load_batch_graph_revision", lambda *args: (calls.append(args) or {}))
        window.inbox_action.trigger()
        window.graph_review_action.trigger()
        _wait(app, lambda: not window._jobs and not window._graph_pane.is_busy)
        assert calls == []
        assert window._graph_active()
    finally:
        _dispose(window, app)
        facade.close()
        store.close()


def test_real_batch_selection_clears_the_previous_graph_context(tmp_path) -> None:
    app = ensure_application()
    store, service, facade, first = _runtime(tmp_path)
    second_task = "second-navigation-task"
    grant = service.reviewer_call(TOKEN, "create_connection", {"task_id": second_task, "agent_name": "fresh-second-agent"})
    second_batch = _batch()
    second_batch["batch_id"] = "second-navigation-batch"
    second_batch["idempotency_key"] = "second-navigation-submit"
    service.agent_call(grant["token"], "submit_batch", second_batch)
    second = facade.create_graph_revision(second_task, second_batch["batch_id"], 0, {"open-result": ["rel-open"]})
    window = ReviewMainWindow(facade)
    try:
        window.show()
        window.open_graph_review(first["logical_workflow_id"])
        _wait(app, lambda: window._graph_pane is not None and not window._graph_pane.is_busy and not window._jobs)
        window.inbox_action.trigger()
        from PySide6.QtCore import Qt
        item = next(window.batch_tree.topLevelItem(i) for i in range(window.batch_tree.topLevelItemCount())
                    if window.batch_tree.topLevelItem(i).data(0, int(Qt.ItemDataRole.UserRole) + 2)[0] == second_task)
        window.batch_tree.setCurrentItem(item)
        _wait(app, lambda: not window._jobs and window.workspace is not None
              and window.workspace["task_id"] == second_task)
        assert window._last_open_graph_id is None
        window.graph_review_action.trigger()
        _wait(app, lambda: not window._jobs and not window._graph_pane.is_busy)
        assert window._graph_pane._snapshot["logical_workflow_id"] == second["logical_workflow_id"]
    finally:
        _dispose(window, app)
        facade.close()
        store.close()


def test_unassigned_single_interface_ingress_does_not_create_a_graph(tmp_path) -> None:
    from app.agent_link import AgentLinkService, AgentLinkStore
    from app.desktop_review.workspace import NativeReviewFacade

    store = AgentLinkStore(tmp_path / "standalone-inbox.json")
    service = AgentLinkService(store, TOKEN)
    grant = service.reviewer_call(TOKEN, "create_connection", {"task_id": "standalone-task", "agent_name": "fresh-interface-agent"})
    batch = _batch()
    batch["interfaces"] = batch["interfaces"][:1]
    batch["screenshots"] = batch["screenshots"][:1]
    batch["steps"] = []
    batch["relationships"] = []
    facade = NativeReviewFacade(service, TOKEN, tmp_path / "standalone-artifacts")
    try:
        service.agent_call(grant["token"], "submit_batch", batch)
        loaded = facade.load_batch("standalone-task", BATCH)
        assert len(loaded["batch"]["interfaces"]) == 1
        assert loaded["batch"]["steps"] == []
        assert loaded["batch"]["relationships"] == []
        assert not (facade._workspace_root / "graph-revisions").exists()
    finally:
        facade.close()
        store.close()


def test_failed_explicit_batch_selection_cannot_fall_back_to_old_graph(tmp_path, monkeypatch) -> None:
    app = ensure_application()
    store, _, facade, graph = _runtime(tmp_path)
    window = ReviewMainWindow(facade)
    try:
        window.open_graph_review(graph["logical_workflow_id"])
        _wait(app, lambda: window._graph_pane is not None and not window._graph_pane.is_busy and not window._jobs)
        window.inbox_action.trigger()
        def fail(*_args):
            raise ValueError("missing selected batch")
        monkeypatch.setattr(facade, "load_batch", fail)
        window.load_batch("unavailable-task", "unavailable-batch")
        _wait(app, lambda: not window._jobs)
        window.graph_review_action.trigger()
        _wait(app, lambda: not window._jobs and not window._graph_pane.is_busy)
        assert not window._graph_active()
        assert "所选内容尚未读取成功" in window.status.currentMessage()
        assert window._graph_pane._snapshot == graph
    finally:
        _dispose(window, app)
        facade.close()
        store.close()
