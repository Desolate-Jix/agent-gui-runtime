"""独立动作链不能交错穿过无关节点，离屏点击必须选中确切连线。"""

from copy import deepcopy
import hashlib
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app.desktop_review.graph_view import NativeWorkflowGraphView
from tests.test_formal_graph_view import _APP, _snapshot


@pytest.mark.parametrize("second_chain", [False, True])
def test_independent_chains_keep_clickable_edges_without_unrelated_nodes(second_chain):
    snapshot = _snapshot()
    graph = snapshot["graph"]
    graph["nodes"] = [{"node_id": key, "display_name": key}
                      for key in (["node-a", "node-b", "node-c", "node-d"] if second_chain
                                  else ["node-a", "node-b", "node-c"])]
    graph["edges"] = [{"edge_id": "edge-ac", "source_node_id": "node-a",
                       "target_node_id": "node-c", "action_type": "open_detail"}]
    if second_chain:
        graph["edges"].append({"edge_id": "edge-bd", "source_node_id": "node-b",
                               "target_node_id": "node-d", "action_type": "go_back"})
    content = deepcopy(snapshot)
    content.pop("content_sha256")
    snapshot["content_sha256"] = hashlib.sha256(json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    original = deepcopy(snapshot)
    view = NativeWorkflowGraphView()
    view.resize(1100, 500)
    view.show()
    selected = []
    view.edgeSelected.connect(selected.append)
    try:
        view.set_revision(snapshot)
        _APP.processEvents()
        for edge in graph["edges"]:
            item = view._edge_items[edge["edge_id"]]
            center = item.mapToScene(item.path().pointAtPercent(0.5))
            assert not any(node.sceneBoundingRect().contains(center)
                           for node in view._node_items.values())
            point = view.mapFromScene(center)
            assert view.viewport().rect().contains(point)
            QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, point)
            _APP.processEvents()
            assert selected[-1:] == [edge["edge_id"]]
        assert snapshot == original
    finally:
        view.close()
        _APP.processEvents()
