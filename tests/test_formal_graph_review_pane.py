from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import time

from PIL import Image
import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.graph_review_pane import GraphReviewPane
from app.desktop_review.workspace import NativeReviewFacade


TOKEN = "fresh-pane-token"
TASK = "fresh-pane-task"
BATCH = "fresh-pane-batch"


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    return app


def _png(colour: tuple[int, int, int]) -> str:
    stream = BytesIO()
    Image.new("RGB", (120, 80), colour).save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def _batch() -> dict:
    screenshots = [
        {"screenshot_id": "shot-a", "png_base64": _png((230, 241, 251))},
        {"screenshot_id": "shot-b", "png_base64": _png((238, 248, 232))},
        {"screenshot_id": "shot-c", "png_base64": _png((251, 239, 229))},
    ]
    interfaces = []
    for index, name in enumerate(("state-a", "state-b", "state-c")):
        regions = [{
            "region_id": f"region-{name}",
            "bbox": [4 + index, 6, 28, 18],
            "name": f"Region {name}",
            "meaning": f"Control {name}",
        }]
        if name == "state-a":
            regions.append({
                "region_id": "region-state-a-secondary",
                "bbox": [54, 34, 30, 20],
                "name": "Secondary A",
                "meaning": "Secondary control A",
            })
        interfaces.append({
            "interface_id": name,
            "screenshot_id": f"shot-{name[-1]}",
            "meaning": f"Meaning {name}",
            "regions": regions,
        })
    return {
        "contract_version": "agent_link_v1",
        "idempotency_key": "fresh-pane-submit",
        "batch_id": BATCH,
        "title": "Fresh graph review pane",
        "learning_outcome": "completed",
        "screenshots": screenshots,
        "interfaces": interfaces,
        "relationships": [{
            "relationship_id": "rel-open",
            "from_interface_id": "state-a",
            "to_interface_id": "state-b",
            "kind": "opens B",
        }],
        "steps": [{
            "step_id": "open-result",
            "action_type": "open_detail",
            "target_region_id": "region-state-a",
            "start_state": "state-a",
            "arrival_state": "state-b",
            "prerequisites": ["A ready"],
            "expected_result": "B visible",
            "stop_condition": "B absent",
        }],
        "issues": [],
    }


def _runtime(tmp_path: Path) -> tuple[AgentLinkStore, AgentLinkService, NativeReviewFacade, dict]:
    store = AgentLinkStore(tmp_path / "fresh-pane-inbox.json")
    service = AgentLinkService(store, TOKEN)
    grant = service.reviewer_call(
        TOKEN, "create_connection", {"task_id": TASK, "agent_name": "fresh-pane-agent"},
    )
    batch = _batch()
    service.agent_call(grant["token"], "submit_batch", batch)
    facade = NativeReviewFacade(service, TOKEN, tmp_path / "fresh-pane-artifacts")
    snapshot = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
    return store, service, facade, snapshot


def _wait(qapp: QApplication, predicate, timeout_ms: int = 5000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Qt asynchronous operation timed out")


def _node(snapshot: dict, external_id: str) -> dict:
    return next(item for item in snapshot["graph"]["nodes"] if item["external_interface_id"] == external_id)


def _click_node(pane: GraphReviewPane, node_id: str) -> None:
    item = pane.graph_view._node_items[node_id]
    pane.graph_view.centerOn(item)
    QApplication.instance().processEvents()
    QTest.mouseClick(
        pane.graph_view.viewport(), Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier, QPoint(3, 3),
    )
    rect = item.sceneBoundingRect()
    point = pane.graph_view.mapFromScene(rect.topLeft() + QPointF(12, 12))
    QTest.mouseClick(
        pane.graph_view.viewport(), Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier, point,
    )


def _click_edge(pane: GraphReviewPane, edge_id: str) -> None:
    item = pane.graph_view._edge_items[edge_id]
    point = pane.graph_view.mapFromScene(item.mapToScene(item.path().pointAtPercent(0.5)))
    QTest.mouseClick(
        pane.graph_view.viewport(), Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier, point,
    )


def test_node_and_region_edits_round_trip_without_touching_source_history(
    tmp_path: Path, qapp: QApplication,
) -> None:
    store, service, facade, created = _runtime(tmp_path)
    source_path = tmp_path / "fresh-pane-artifacts" / created["source_refs"]["original_batch_path"]
    r1_path = (
        tmp_path / "fresh-pane-artifacts" / "desktop-review" / "graph-revisions"
        / created["logical_workflow_id"] / "revisions" / f"{created['content_sha256']}.json"
    )
    source_bytes, r1_bytes = source_path.read_bytes(), r1_path.read_bytes()
    original_batch = deepcopy(service.reviewer_call(TOKEN, "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"])
    pane = GraphReviewPane(facade)
    pane.resize(1280, 760)
    pane.show()
    qapp.processEvents()
    assert pane.graph_view.viewport().width() >= 300
    revisions = QSignalSpy(pane.revisionChanged)
    try:
        pane.load_graph(created["logical_workflow_id"])
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 1)
        node_a = _node(created, "state-a")
        _click_node(pane, _node(created, "state-b")["node_id"])
        assert pane.is_busy
        assert not pane.node_meaning_edit.isEnabled()
        assert not pane.before_canvas.isEnabled()
        _wait(qapp, lambda: not pane.is_busy)
        _click_node(pane, node_a["node_id"])
        _wait(qapp, lambda: not pane.is_busy and pane.before_canvas._pixmap_item is not None)
        assert pane.before_canvas._image_identity[:3] == (
            created["logical_workflow_id"], node_a["node_id"], "shot-a",
        )
        secondary = pane.before_canvas._regions["region-state-a-secondary"]
        secondary_point = pane.before_canvas.mapFromScene(secondary.sceneBoundingRect().center())
        QTest.mouseClick(pane.before_canvas.viewport(), Qt.MouseButton.LeftButton, pos=secondary_point)
        assert pane.node_region_combo.currentData() == "region-state-a-secondary"
        pane.node_region_combo.setCurrentIndex(pane.node_region_combo.findData("region-state-a"))
        assert pane.before_canvas._regions["region-state-a"].isSelected()

        pane.node_meaning_edit.setText("Discard this change")
        QTest.mouseClick(pane.revert_button, Qt.MouseButton.LeftButton)
        assert not pane.is_dirty
        assert pane.node_meaning_edit.isEnabled()
        assert pane.review_graph_button.isEnabled()

        pane.node_meaning_edit.setText("A reviewed meaning")
        assert pane.is_dirty
        QTest.mouseClick(pane.save_node_meaning_button, Qt.MouseButton.LeftButton)
        assert pane.is_busy and not pane.node_meaning_edit.isEnabled()
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 2)
        current = facade.load_graph_revision(created["logical_workflow_id"], None)
        assert current["revision"] == 2
        assert _node(current, "state-a")["display_name"] == "A reviewed meaning"

        pane.node_region_combo.setCurrentIndex(0)
        pane.node_region_bbox_edit.setText("8, 9, 32, 20")
        QTest.mouseClick(pane.save_region_bbox_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 3)
        current = facade.load_graph_revision(created["logical_workflow_id"], None)
        assert _node(current, "state-a")["regions"][0]["bbox"] == [8.0, 9.0, 32.0, 20.0]
        assert service.reviewer_call(TOKEN, "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"] == original_batch
        assert source_path.read_bytes() == source_bytes
        assert r1_path.read_bytes() == r1_bytes
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()


def test_edge_selection_shows_both_originals_and_saves_target_then_semantics(
    tmp_path: Path, qapp: QApplication,
) -> None:
    store, _, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.resize(1280, 760)
    pane.show()
    revisions = QSignalSpy(pane.revisionChanged)
    reviewed = QSignalSpy(pane.reviewRequested)
    try:
        pane.load_graph(created["logical_workflow_id"])
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 1)
        edge = created["graph"]["edges"][0]
        node_a, node_b, node_c = (_node(created, value) for value in ("state-a", "state-b", "state-c"))
        _click_edge(pane, edge["edge_id"])
        _wait(qapp, lambda: not pane.is_busy and pane.after_canvas._pixmap_item is not None)
        assert pane.before_canvas._image_identity[:3] == (
            created["logical_workflow_id"], node_a["node_id"], "shot-a",
        )
        assert pane.after_canvas._image_identity[:3] == (
            created["logical_workflow_id"], node_b["node_id"], "shot-b",
        )
        assert pane.edge_action_label.text() == "打开详情（Agent 声明，待核对）"
        assert pane.edge_action_label.toolTip() == "open_detail"
        assert pane.edge_target_region_combo.currentData() == "region-state-a"

        pane.edge_target_node_combo.setCurrentIndex(
            pane.edge_target_node_combo.findData(node_c["node_id"]),
        )
        QTest.mouseClick(pane.save_edge_target_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 2)
        assert "需要修正" in pane.stale_semantics_label.text()
        assert pane.graph_view._edge_items[edge["edge_id"]].isSelected()

        pane.edge_prerequisites_edit.setPlainText('["A ready"]')
        pane.edge_expected_result_edit.setText("C result visible")
        pane.edge_stop_condition_edit.setText("C result absent")
        pane.edge_relationship_kinds_edit.setPlainText('{"rel-open":"opens corrected C"}')
        QTest.mouseClick(pane.save_edge_semantics_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 3)
        current = facade.load_graph_revision(created["logical_workflow_id"], None)
        saved = current["graph"]["edges"][0]
        assert saved["target_node_id"] == node_c["node_id"]
        assert saved["success_conditions"] == ["C result visible"]
        assert saved["failure_conditions"] == ["C result absent"]
        assert saved["external_relationships"][0]["kind"] == "opens corrected C"
        assert pane.graph_view._edge_items[edge["edge_id"]].isSelected()

        pane.edge_target_region_combo.setCurrentIndex(0)
        pane.before_canvas.select_region("region-state-a")
        assert pane.graph_view._edge_items[edge["edge_id"]].isSelected()
        QTest.mouseClick(pane.review_graph_button, Qt.MouseButton.LeftButton)
        assert reviewed.count() == 1 and reviewed.at(0)[0]["revision"] == 3
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()


def test_unsaved_selection_is_restored_and_stale_failure_retains_fields(
    tmp_path: Path, qapp: QApplication,
) -> None:
    store, _, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.resize(1100, 720)
    pane.show()
    revisions = QSignalSpy(pane.revisionChanged)
    errors = QSignalSpy(pane.errorRaised)
    try:
        pane.load_graph(created["logical_workflow_id"])
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 1)
        node_a, node_b, node_c = (_node(created, value) for value in ("state-a", "state-b", "state-c"))
        _click_node(pane, node_a["node_id"])
        _wait(qapp, lambda: not pane.is_busy)
        pane.node_meaning_edit.setText("Unsaved A")
        _click_node(pane, node_b["node_id"])
        qapp.processEvents()
        assert pane.graph_view._node_items[node_a["node_id"]].isSelected()
        assert pane.node_meaning_edit.text() == "Unsaved A"
        assert pane.is_dirty and any("未保存" in errors.at(index)[0] for index in range(errors.count()))

        advanced = facade.apply_graph_edit(
            created["logical_workflow_id"], 1, created["content_sha256"],
            {"type": "update_node_meaning", "node_id": node_c["node_id"], "meaning": "External C"},
            "fresh-pane-external-change",
        )
        pane.set_revision(advanced)
        assert pane.graph_view._revision["revision"] == 1
        assert pane.node_meaning_edit.text() == "Unsaved A" and pane.is_dirty
        QTest.mouseClick(pane.save_node_meaning_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not pane.is_busy and errors.count() >= 2)
        assert revisions.count() == 1
        assert pane.node_meaning_edit.text() == "Unsaved A"
        assert pane.is_dirty
        assert pane.graph_view._revision["revision"] == 1

        QTest.mouseClick(pane.revert_button, Qt.MouseButton.LeftButton)
        assert not pane.is_dirty
        assert pane.node_meaning_edit.text() == node_a["display_name"]
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()
