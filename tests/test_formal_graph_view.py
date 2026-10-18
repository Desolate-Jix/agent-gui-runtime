from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.desktop_review.graph_view import NativeWorkflowGraphView


_APP = QApplication.instance() or QApplication([])


def _snapshot() -> dict:
    value = {
        "contract_version": "formal_graph_revision_v1",
        "logical_workflow_id": "workflow-" + "a" * 64,
        "revision": 2,
        "content_sha256": "",
        "parent_sha256": "b" * 64,
        "source_refs": {"task_id": "task", "batch_id": "batch"},
        "graph": {
            "display_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "nodes": [
                {"node_id": "node-a", "display_name": "列表"},
                {"node_id": "node-b", "display_name": "详情"},
                {"node_id": "node-c", "display_name": "结果"},
            ],
            "edges": [
                {"edge_id": "edge-ab-1", "source_node_id": "node-a", "target_node_id": "node-b", "action_type": "open_detail"},
                {"edge_id": "edge-ab-2", "source_node_id": "node-a", "target_node_id": "node-b", "label": "备用路径", "action_type": "observe"},
                {"edge_id": "edge-ba", "source_node_id": "node-b", "target_node_id": "node-a", "action_type": "go_back"},
                {"edge_id": "edge-bb", "source_node_id": "node-b", "target_node_id": "node-b", "action_type": "refresh"},
                {"edge_id": "edge-bc", "source_node_id": "node-b", "target_node_id": "node-c", "action_type": "continue_next_step"},
            ],
        },
        "change": {"idempotency_key": "edit", "request_sha256": "c" * 64},
    }
    content = deepcopy(value)
    content.pop("content_sha256")
    value["content_sha256"] = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return value


def _process() -> None:
    _APP.processEvents()


def test_set_revision_renders_every_stable_node_edge_and_explicit_labels() -> None:
    view = NativeWorkflowGraphView()
    view.resize(900, 600)
    view.set_revision(_snapshot())
    _process()

    assert set(view._node_items) == {"node-a", "node-b", "node-c"}
    assert set(view._edge_items) == {"edge-ab-1", "edge-ab-2", "edge-ba", "edge-bb", "edge-bc"}
    assert view._node_items["node-a"].label == "列表"
    assert view._edge_items["edge-ab-1"].label == "open_detail"
    assert view._edge_items["edge-ab-2"].label == "备用路径"
    assert all(not item.path().isEmpty() for item in view._edge_items.values())


def test_parallel_return_and_self_loop_paths_are_all_geometrically_distinct() -> None:
    view = NativeWorkflowGraphView()
    view.resize(900, 600)
    view.set_revision(_snapshot())

    paths = {identity: item.path().toFillPolygon().boundingRect() for identity, item in view._edge_items.items()}
    assert paths["edge-ab-1"] != paths["edge-ab-2"]
    assert paths["edge-ab-1"] != paths["edge-ba"]
    assert paths["edge-bb"].width() > 0 and paths["edge-bb"].height() > 0


def test_real_offscreen_click_emits_exact_node_and_edge_ids() -> None:
    view = NativeWorkflowGraphView()
    view.resize(900, 600)
    view.show()
    view.set_revision(_snapshot())
    _process()
    nodes: list[str] = []
    edges: list[str] = []
    view.nodeSelected.connect(nodes.append)
    view.edgeSelected.connect(edges.append)

    node_point = view.mapFromScene(view._node_items["node-a"].sceneBoundingRect().center())
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, node_point)
    _process()
    edge_point = view.mapFromScene(view._edge_items["edge-bc"].path().pointAtPercent(0.5))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, edge_point)
    _process()

    assert nodes == ["node-a"]
    assert edges == ["edge-bc"]


def test_programmatic_selection_is_silent_and_does_not_duplicate_selection_loops() -> None:
    view = NativeWorkflowGraphView()
    view.set_revision(_snapshot())
    nodes: list[str] = []
    edges: list[str] = []
    view.nodeSelected.connect(nodes.append)
    view.edgeSelected.connect(edges.append)

    view.select_node("node-b")
    view.select_node("node-b")
    view.select_edge("edge-bc")
    view.select_edge("edge-bc")
    _process()

    assert nodes == [] and edges == []
    assert view.scene().selectedItems() == [view._edge_items["edge-bc"]]
    with pytest.raises(ValueError, match="unknown node"):
        view.select_node("missing")


def test_set_revision_deep_copies_and_invalid_replacement_is_atomic() -> None:
    view = NativeWorkflowGraphView()
    original = _snapshot()
    view.set_revision(original)
    scene = view.scene()
    original["graph"]["nodes"][0]["display_name"] = "被外部改写"
    assert view._node_items["node-a"].label == "列表"

    for mutation in (
        lambda item: item["graph"]["nodes"].append(deepcopy(item["graph"]["nodes"][0])),
        lambda item: item["graph"]["edges"][0].__setitem__("target_node_id", "missing"),
        lambda item: item["graph"]["edges"][0].__setitem__("target_node_id", {"id": "node-b"}),
        lambda item: item["graph"]["edges"].append(deepcopy(item["graph"]["edges"][0])),
        lambda item: item.__setitem__("revision", 1),
        lambda item: item["graph"].__setitem__("artifact_is_authorization", True),
    ):
        invalid = _snapshot()
        mutation(invalid)
        content = deepcopy(invalid)
        content.pop("content_sha256")
        invalid["content_sha256"] = hashlib.sha256(
            json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        with pytest.raises(ValueError):
            view.set_revision(invalid)
        assert view.scene() is scene
        assert set(view._node_items) == {"node-a", "node-b", "node-c"}


def test_fit_zoom_pan_and_clear_are_view_only() -> None:
    view = NativeWorkflowGraphView()
    view.resize(640, 420)
    view.show()
    value = _snapshot()
    original = deepcopy(value)
    view.set_revision(value)
    view.fit_graph()
    initial = view.transform().m11()
    view.set_zoom_percent(300)
    assert view.transform().m11() != initial
    _process()
    before = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
    start = view.viewport().rect().center()
    finish = start - QPoint(45, 30)
    QTest.mousePress(view.viewport(), Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(view.viewport(), finish)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, finish)
    _process()
    after = (view.horizontalScrollBar().value(), view.verticalScrollBar().value())
    assert after != before
    view.clear_graph()

    assert not view.scene().items()
    assert value == original


def test_real_deselection_allows_same_node_to_be_selected_again() -> None:
    view = NativeWorkflowGraphView()
    view.resize(900, 600)
    view.show()
    view.set_revision(_snapshot())
    _process()
    selected: list[str] = []
    view.nodeSelected.connect(selected.append)
    point = view.mapFromScene(view._node_items["node-a"].sceneBoundingRect().center())
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(3, 3))
    assert not view.scene().selectedItems()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert selected == ["node-a", "node-a"]
    view.close()


def test_actual_graph_owner_snapshot_is_read_without_edit_or_execution(tmp_path) -> None:
    from test_formal_graph_source_ownership import _facade

    facade, store, _, _ = _facade(tmp_path)
    view = NativeWorkflowGraphView()
    try:
        snapshot = facade.create_graph_revision(
            "graph-source-ownership-task", "graph-source-ownership-batch", 0,
            step_relationships={"step-a-b": ["relation-a-b"]},
        )
        view.set_revision(snapshot)
        assert len(view._node_items) == 3 and len(view._edge_items) == 1
        edge_id = snapshot["graph"]["edges"][0]["edge_id"]
        view.select_edge(edge_id)
        assert view.scene().selectedItems() == [view._edge_items[edge_id]]
        assert facade.load_graph_revision(snapshot["logical_workflow_id"]) == snapshot
    finally:
        view.close()
        facade.close()
        store.close()
