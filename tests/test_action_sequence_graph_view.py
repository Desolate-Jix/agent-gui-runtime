from PySide6.QtWidgets import QApplication

from app.desktop_review.graph_view import NativeWorkflowGraphView, _SequenceLinkItem


_APP = QApplication.instance() or QApplication([])


def _graph():
    return {
        "nodes": [
            {"node_id": "a-before", "display_name": "搜索前"},
            {"node_id": "a-after", "display_name": "结果页"},
            {"node_id": "b-before", "display_name": "结果页前"},
            {"node_id": "b-after", "display_name": "地图"},
        ],
        "edges": [
            {"edge_id": "a-edge", "source_node_id": "a-before", "target_node_id": "a-after",
             "external_step_id": "event.1", "action_type": "search"},
            {"edge_id": "b-edge", "source_node_id": "b-before", "target_node_id": "b-after",
             "external_step_id": "event.2", "action_type": "open_detail"},
        ],
        "action_sequence": [
            {"sequence_index": 1, "event_id": "event.1", "previous_event_id": None,
             "continuity_status": "recorded_sequence"},
            {"sequence_index": 2, "event_id": "event.2", "previous_event_id": "event.1",
             "continuity_status": "unknown_gap"},
        ],
    }


def test_sequence_link_is_visual_only_and_not_selectable_or_an_edge():
    view = NativeWorkflowGraphView()
    scene, nodes, edges = view._build_scene(_graph())

    assert set(edges) == {"a-edge", "b-edge"}
    links = [item for item in scene.items() if isinstance(item, _SequenceLinkItem)]
    assert len(links) == 1
    assert not links[0].flags() & links[0].GraphicsItemFlag.ItemIsSelectable
    assert links[0].acceptedMouseButtons().value == 0


def test_sequence_link_is_not_drawn_when_event_pair_is_missing():
    graph = _graph()
    graph["action_sequence"][1]["event_id"] = "missing"
    view = NativeWorkflowGraphView()
    scene, _, _ = view._build_scene(graph)
    assert not [item for item in scene.items() if isinstance(item, _SequenceLinkItem)]
