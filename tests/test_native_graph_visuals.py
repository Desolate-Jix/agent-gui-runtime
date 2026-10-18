from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.desktop_review.graph_view import NativeWorkflowGraphView


_APP = QApplication.instance() or QApplication([])


def _snapshot(title: str) -> dict:
    value = {
        "contract_version": "formal_graph_revision_v1",
        "logical_workflow_id": "workflow-" + "d" * 64,
        "revision": 2,
        "content_sha256": "",
        "parent_sha256": "a" * 64,
        "source_refs": {"task_id": "task", "batch_id": "batch"},
        "graph": {
            "display_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "nodes": [
                {"node_id": "node-a", "display_name": title},
                {"node_id": "node-b", "display_name": "结果"},
            ],
            "edges": [
                {
                    "edge_id": "edge-ab",
                    "source_node_id": "node-a",
                    "target_node_id": "node-b",
                    "action_type": "continue_next_step",
                },
            ],
        },
        "change": {"idempotency_key": "visual", "request_sha256": "b" * 64},
    }
    content = deepcopy(value)
    content.pop("content_sha256")
    value["content_sha256"] = hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()
    return value


def test_graph_cards_elide_long_chinese_titles_with_full_tooltips_and_blue_selection() -> None:
    title = "这是一个用于确认原生流程图节点卡片中文标题不会溢出的很长很长的名称"
    view = NativeWorkflowGraphView()
    view.set_revision(_snapshot(title))
    _APP.processEvents()

    node = view._node_items["node-a"]
    edge = view._edge_items["edge-ab"]

    assert view.backgroundBrush().color().name() == "#f4f7fb"
    assert node.label == title
    assert node.toolTip() == title
    assert node._title_text.toolTip() == title
    assert node._title_text.text().endswith("…")
    assert node._title_text.boundingRect().width() <= node.rect().width() - 28.0
    assert node._type_text.text() == "界面"
    assert node.pen().color().name() == "#dbe3ef"
    assert edge.pen().color().name() == "#52627a"

    node.setSelected(True)
    edge.setSelected(True)
    _APP.processEvents()

    assert node.pen().color().name() == "#2563eb"
    assert edge.pen().color().name() == "#2563eb"


def test_edge_label_text_renders_above_its_white_readability_backdrop_and_arrow() -> None:
    view = NativeWorkflowGraphView()
    view.resize(900, 600)
    view.show()
    view.set_revision(_snapshot("列表"))
    _APP.processEvents()

    edge = view._edge_items["edge-ab"]
    assert edge._label_text.zValue() > edge._label_background.zValue()

    image = QImage(view.viewport().size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#f4f7fb"))
    view.viewport().render(image)

    label = view.mapFromScene(edge._label_text.sceneBoundingRect()).boundingRect().intersected(image.rect())
    arrow_end = view.mapFromScene(edge.path().currentPosition())
    muted = QColor("#52627a")

    assert any(
        image.pixelColor(x, y) == muted
        for x in range(label.left(), label.right() + 1)
        for y in range(label.top(), label.bottom() + 1)
    )
    assert any(
        image.pixelColor(x, y) == muted
        for x in range(max(0, arrow_end.x() - 14), min(image.width(), arrow_end.x() + 15))
        for y in range(max(0, arrow_end.y() - 14), min(image.height(), arrow_end.y() + 15))
    )
    view.close()
