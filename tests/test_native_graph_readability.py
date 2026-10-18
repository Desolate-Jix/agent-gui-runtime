from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
                {"node_id": "node-a", "display_name": "列表界面"},
                {"node_id": "node-b", "display_name": "详情界面"},
                {"node_id": "node-c", "display_name": "结果界面"},
            ],
            "edges": [
                {"edge_id": "edge-ab", "source_node_id": "node-a", "target_node_id": "node-b", "action_type": "open_detail"},
                {"edge_id": "edge-bc", "source_node_id": "node-b", "target_node_id": "node-c", "action_type": "continue_next_step"},
            ],
        },
        "change": {"idempotency_key": "edit", "request_sha256": "c" * 64},
    }
    content = deepcopy(value)
    content.pop("content_sha256")
    value["content_sha256"] = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    return value


def test_small_three_node_fit_keeps_labels_readable_and_click_target_generous() -> None:
    view = NativeWorkflowGraphView()
    view.resize(440, 280)
    view.show()
    view.set_revision(_snapshot())
    _APP.processEvents()
    view.readable_zoom()
    assert view.transform().m11() >= 0.9
    view.fit_graph()
    assert view.mapToScene(view.viewport().rect()).boundingRect().contains(view.scene().sceneRect())
    assert view._node_items["node-a"].rect().width() >= 190
    assert view._node_items["node-a"]._title_text.font().pointSizeF() >= 11
    assert view._edge_items["edge-ab"]._label_text.font().pointSizeF() >= 10
    assert view._edge_items["edge-ab"].shape().length() > view._edge_items["edge-ab"].path().length()
    view.close()


def test_small_graph_uses_single_row_and_readable_zoom_does_not_crop() -> None:
    view = NativeWorkflowGraphView()
    view.resize(1440, 900)
    view.show()
    view.set_revision(_snapshot())
    _APP.processEvents()

    positions = [view._node_items[node_id].pos().y() for node_id in ("node-a", "node-b", "node-c")]
    assert positions == [0.0, 0.0, 0.0]
    assert view.transform().m11() >= 0.9
    visible = view.mapToScene(view.viewport().rect()).boundingRect()
    assert visible.contains(view.scene().sceneRect())
    view.close()


def test_action_copy_is_friendly_but_raw_action_stays_in_tooltip_and_identity() -> None:
    snapshot = _snapshot()
    snapshot["graph"]["edges"].append({
        "edge_id": "edge-unknown", "source_node_id": "node-a", "target_node_id": "node-c",
        "action_type": "unknown_action",
    })
    content = deepcopy(snapshot)
    content.pop("content_sha256")
    snapshot["content_sha256"] = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    view = NativeWorkflowGraphView()
    view.set_revision(snapshot)

    assert view._node_items["node-a"]._type_text.text() == "界面"
    assert view._edge_items["edge-ab"].label == "open_detail"
    assert view._edge_items["edge-ab"].display_label == "打开详情"
    assert view._edge_items["edge-ab"].toolTip() == "open_detail"
    assert view._edge_items["edge-unknown"].display_label == "动作待核对"
    assert view._edge_items["edge-unknown"].toolTip() == "unknown_action"
    view.close()


def test_selection_is_view_only_and_does_not_mutate_graph() -> None:
    view = NativeWorkflowGraphView()
    snapshot = _snapshot()
    original = deepcopy(snapshot)
    view.set_revision(snapshot)
    view.select_node("node-b")
    view.select_edge("edge-bc")

    assert snapshot == original
    assert view._revision == original
    view.close()


def test_long_chinese_labels_have_tooltips_and_elided_titles_without_overflow() -> None:
    snapshot = _snapshot()
    long_label = "这是一个很长的中文界面标签，用于确认节点标题在小卡片中会友好截断并通过提示完整查看"
    snapshot["graph"]["nodes"][0]["display_name"] = long_label
    content = deepcopy(snapshot)
    content.pop("content_sha256")
    snapshot["content_sha256"] = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    view = NativeWorkflowGraphView()
    view.set_revision(snapshot)
    item = view._node_items["node-a"]

    assert item.toolTip() == long_label
    assert item._title_text.toolTip() == long_label
    assert item._title_text.boundingRect().width() <= item.rect().width() - 28
    view.close()
