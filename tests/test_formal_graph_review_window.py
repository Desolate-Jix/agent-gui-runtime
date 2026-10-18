import time

from app.desktop_review.window import ReviewMainWindow, ensure_application
from test_formal_graph_source_ownership import _facade


def _wait(window):
    app = ensure_application()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        time.sleep(0.01)
        app.processEvents()
        pane = getattr(window, '_graph_pane', None)
        if window._operation == 'idle' and not window._jobs and pane is not None and not pane.is_busy:
            return
    raise AssertionError('graph window did not finish loading: ' + window.status.currentMessage())


def test_window_opens_real_graph_pane_without_rewriting_batch_or_enabling_old_save(tmp_path):
    ensure_application()
    facade, store, _, _ = _facade(tmp_path)
    graph = facade.create_graph_revision('graph-source-ownership-task', 'graph-source-ownership-batch', 0)
    before = facade.load_batch('graph-source-ownership-task', 'graph-source-ownership-batch')
    window = ReviewMainWindow(facade)
    try:
        window.open_graph_review(graph['logical_workflow_id'])
        _wait(window)
        assert window.centralWidget().currentWidget() is window._graph_pane
        assert not window.save_action.isEnabled()
        assert not window.exact_review_action.isEnabled()
        assert facade.load_graph_revision(graph['logical_workflow_id']) == graph
        window.save_current()
        assert facade.load_batch('graph-source-ownership-task', 'graph-source-ownership-batch') == before
        assert window.show_inbox() is True
        assert window.centralWidget().currentWidget() is window._legacy_review
    finally:
        if getattr(window, '_graph_pane', None) is not None:
            _wait(window)
        window.close()
        store.close()
