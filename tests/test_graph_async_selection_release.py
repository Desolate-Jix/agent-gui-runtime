"""异步读取原图不能在鼠标按下时禁用视图并遗留鼠标抓取。"""

import time

from app.desktop_review.graph_review_pane import GraphReviewPane
from tests.test_formal_graph_review_pane import _click_edge, _wait, qapp
from tests.test_formal_learning_segments import _perform_action
from tests.test_reviewed_action_only_graph import _rig, _scope


def test_consecutive_edge_clicks_release_mouse_while_originals_load(tmp_path, qapp, monkeypatch):
    with _rig(tmp_path) as (host, connection, segment):
        _perform_action(tmp_path / 'review', host.learning_segments,
                        host.learning_segments.recorder, host.learning_segments.capture_archive,
                        connection, segment['segment_id'], sequence=2)
        synced = host.fresh_learning.sync_actions(**_scope(connection, segment))
        graph = host.facade.load_graph_revision(synced['logical_workflow_id'])
        original = host.facade.load_graph_node_evidence

        def delayed(*args, **kwargs):
            time.sleep(0.08)
            return original(*args, **kwargs)

        monkeypatch.setattr(host.facade, 'load_graph_node_evidence', delayed)
        pane = GraphReviewPane(host.facade)
        pane.resize(1400, 850)
        pane.show()
        try:
            pane.load_graph(graph['logical_workflow_id'])
            _wait(qapp, lambda: not pane.is_busy and pane._evidence_valid)
            for edge in graph['graph']['edges']:
                _click_edge(pane, edge['edge_id'])
                _wait(qapp, lambda: not pane.is_busy and pane._evidence_valid)
                assert pane.graph_view.scene().mouseGrabberItem() is None
                assert pane._selection == ('edge', edge['edge_id'])
                assert pane.before_canvas._pixmap_item is not None
                assert pane.after_canvas._pixmap_item is not None
        finally:
            _wait(qapp, lambda: not pane.is_busy)
            pane.close()
            _wait(qapp, lambda: not pane._jobs)


def test_busy_pane_preserves_selection_until_evidence_request_finishes(tmp_path, qapp):
    with _rig(tmp_path) as (host, connection, segment):
        synced = host.fresh_learning.sync_actions(**_scope(connection, segment))
        graph = host.facade.load_graph_revision(synced['logical_workflow_id'])
        pane = GraphReviewPane(host.facade)
        pane.show()
        try:
            pane.load_graph(graph['logical_workflow_id'])
            _wait(qapp, lambda: not pane.is_busy and pane._evidence_valid)
            previous = pane._selection
            pane._set_busy(True)
            pane._edge_selected(graph['graph']['edges'][0]['edge_id'])
            assert pane._selection == previous
            assert pane.graph_view._last_selection == previous
        finally:
            pane._set_busy(False)
            pane.close()
            _wait(qapp, lambda: not pane._jobs)


def test_explicit_initial_selection_is_atomic_and_displays_requested_original(tmp_path, qapp):
    with _rig(tmp_path) as (host, connection, segment):
        synced = host.fresh_learning.sync_actions(**_scope(connection, segment))
        graph = host.facade.load_graph_revision(synced['logical_workflow_id'])
        selected = ('node', graph['graph']['nodes'][-1]['node_id'])
        pane = GraphReviewPane(host.facade)
        pane.show()
        try:
            assert pane.set_revision(graph, initial_selection=selected)
            _wait(qapp, lambda: not pane.is_busy and pane._evidence_valid)
            assert pane._selection == selected
            assert pane.graph_view._last_selection == selected
            assert pane.node_meaning_edit.text() == graph['graph']['nodes'][-1]['display_name']
            assert not pane.review_graph_button.isEnabled()
            assert not pane.graph_relearn_button.isEnabled()
            assert '操作证据图' in pane.identity_label.text()
            assert not pane.set_revision(graph, initial_selection=('node', 'missing-node'))
            assert pane._snapshot == graph
            assert pane._selection == selected and pane._evidence_valid
        finally:
            _wait(qapp, lambda: not pane.is_busy)
            pane.close()
            _wait(qapp, lambda: not pane._jobs)
