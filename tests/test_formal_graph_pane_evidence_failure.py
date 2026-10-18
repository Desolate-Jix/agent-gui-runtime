from PySide6.QtTest import QSignalSpy

from app.desktop_review.graph_review_pane import GraphReviewPane
from test_formal_graph_review_pane import _runtime, _wait, _node, _click_node, qapp


def test_failed_selection_evidence_does_not_present_previous_node_screenshot(tmp_path, qapp):
    store, _, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.resize(1280, 760)
    pane.show()
    errors = QSignalSpy(pane.errorRaised)
    try:
        pane.set_revision(created)
        _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
        assert pane.before_canvas._pixmap_item is not None
        node_b = _node(created, 'state-b')
        facade.apply_graph_edit(
            created['logical_workflow_id'], 1, created['content_sha256'],
            {'type': 'update_node_meaning', 'node_id': node_b['node_id'], 'meaning': 'Changed externally'},
            'fresh-evidence-failure-advance',
        )
        _click_node(pane, node_b['node_id'])
        _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
        assert errors.count() >= 1
        assert pane.node_id_label.text() == node_b['node_id']
        assert pane.before_canvas._pixmap_item is None
        assert pane.after_canvas._pixmap_item is None
    finally:
        _wait(qapp, lambda: not pane.is_busy and not pane._jobs)
        pane.close()
        facade.close()
        store.close()
