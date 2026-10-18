from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import time

from PIL import Image
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.graph_review_pane import GraphReviewPane
from app.desktop_review.workspace import NativeReviewFacade


TOKEN = "recognition-identity-token"
TASK = "recognition-identity-task"
BATCH = "recognition-identity-batch"


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _png() -> str:
    stream = BytesIO()
    Image.new("RGB", (120, 80), (230, 241, 251)).save(stream, format="PNG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def _runtime(tmp_path: Path) -> tuple[AgentLinkStore, NativeReviewFacade, dict]:
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, TOKEN)
    grant = service.reviewer_call(
        TOKEN, "create_connection", {"task_id": TASK, "agent_name": "identity-pane-agent"},
    )
    service.agent_call(grant["token"], "submit_batch", {
        "contract_version": "agent_link_v1",
        "idempotency_key": "identity-pane-submit",
        "batch_id": BATCH,
        "title": "Identity pane",
        "learning_outcome": "completed",
        "screenshots": [{"screenshot_id": "shot-a", "png_base64": _png()}],
        "interfaces": [{
            "interface_id": "state-a",
            "screenshot_id": "shot-a",
            "meaning": "State A",
            "regions": [],
        }],
        "relationships": [],
        "steps": [],
        "issues": [],
    })
    facade = NativeReviewFacade(service, TOKEN, tmp_path / "artifacts")
    return store, facade, facade.create_graph_revision(TASK, BATCH, 0, {})


def _wait(qapp: QApplication, predicate, timeout_ms: int = 5000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Qt asynchronous operation timed out")


def test_node_recognition_text_save_uses_verified_node_evidence(
    tmp_path: Path, qapp: QApplication,
) -> None:
    store, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.show()
    revisions = QSignalSpy(pane.revisionChanged)
    try:
        pane.load_graph(created["logical_workflow_id"])
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 1)
        node = created["graph"]["nodes"][0]
        pane.node_recognition_text_edit.setText("Actual visible title")
        pane.node_recognition_bbox_edit.setText("4, 6, 28, 18")
        QTest.mouseClick(pane.save_node_recognition_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 2)

        current = facade.load_graph_revision(created["logical_workflow_id"], None)
        saved = current["graph"]["nodes"][0]
        expected = {
            "contract_version": "graph_node_recognition_anchor_v1",
            "node_id": node["node_id"],
            "text": "Actual visible title",
            "source_screenshot_path": node["evidence"]["source_screenshot_path"],
            "source_screenshot_sha256": node["evidence"]["source_screenshot_sha256"],
            "bbox": [4.0, 6.0, 28.0, 18.0],
        }
        assert saved["recognition_text"] == "Actual visible title"
        assert saved["recognition_anchor"] == expected
        assert saved["regions"] == node["regions"]
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()


def test_recognition_save_is_disabled_without_current_evidence(
    tmp_path: Path, qapp: QApplication,
) -> None:
    store, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.show()
    errors = QSignalSpy(pane.errorRaised)
    try:
        pane.load_graph(created["logical_workflow_id"])
        _wait(qapp, lambda: not pane.is_busy)
        pane._invalidate_evidence(clear=True)
        pane.node_recognition_text_edit.setText("Visible title")
        pane.node_recognition_bbox_edit.setText("4, 6, 28, 18")
        assert not pane.save_node_recognition_button.isEnabled()
        pane.save_node_recognition()
        assert errors.count() == 1
        assert "证据不可用" in errors.at(0)[0]
        assert facade.load_graph_revision(created["logical_workflow_id"], None)["revision"] == 1
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()


def test_recognition_dirty_field_blocks_selection_switch(
    tmp_path: Path, qapp: QApplication,
) -> None:
    store, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.show()
    errors = QSignalSpy(pane.errorRaised)
    try:
        pane.load_graph(created["logical_workflow_id"])
        _wait(qapp, lambda: not pane.is_busy)
        node_id = created["graph"]["nodes"][0]["node_id"]
        pane.node_recognition_text_edit.setText("Unsaved visible title")
        assert pane.is_dirty
        pane._selection_requested(("node", "other-node"))
        assert pane._selection == ("node", node_id)
        assert pane.node_recognition_text_edit.text() == "Unsaved visible title"
        assert errors.count() == 1
        assert "未保存" in errors.at(0)[0]
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()


def test_recognition_save_rejects_stale_node_image_binding(
    tmp_path: Path, qapp: QApplication,
) -> None:
    store, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.show()
    errors = QSignalSpy(pane.errorRaised)
    try:
        pane.load_graph(created["logical_workflow_id"])
        _wait(qapp, lambda: not pane.is_busy)
        node = pane._selected_node()
        assert node is not None
        node["evidence"]["source_screenshot_sha256"] = "0" * 64
        pane.node_recognition_text_edit.setText("Visible title")
        pane.node_recognition_bbox_edit.setText("4, 6, 28, 18")
        pane.save_node_recognition()
        assert errors.count() == 1
        assert "绑定不可用或已过期" in errors.at(0)[0]
        assert facade.load_graph_revision(created["logical_workflow_id"], None)["revision"] == 1
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()

def test_meaning_and_region_saves_preserve_unsaved_recognition_draft(
    tmp_path: Path, qapp: QApplication,
) -> None:
    store, facade, created = _runtime(tmp_path)
    pane = GraphReviewPane(facade)
    pane.show()
    errors = QSignalSpy(pane.errorRaised)
    try:
        pane.load_graph(created["logical_workflow_id"])
        _wait(qapp, lambda: not pane.is_busy)
        pane.node_recognition_text_edit.setText("Unsaved visible title")
        pane.node_recognition_bbox_edit.setText("4, 6, 28, 18")
        pane.node_meaning_edit.setText("Unsaved meaning")
        QTest.mouseClick(pane.save_node_meaning_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not pane.is_busy)
        assert facade.load_graph_revision(created["logical_workflow_id"], None)["revision"] == 1
        assert pane.node_recognition_text_edit.text() == "Unsaved visible title"
        assert pane.node_recognition_bbox_edit.text() == "4, 6, 28, 18"

        pane.node_meaning_edit.setText("State A")
        pane.node_region_bbox_edit.setText("9, 10, 20, 16")
        QTest.mouseClick(pane.save_region_bbox_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not pane.is_busy)
        assert facade.load_graph_revision(created["logical_workflow_id"], None)["revision"] == 1
        assert pane.node_recognition_text_edit.text() == "Unsaved visible title"
        assert pane.node_recognition_bbox_edit.text() == "4, 6, 28, 18"
        assert errors.count() == 2
        assert all("识别文字" in errors.at(index)[0] for index in range(errors.count()))
    finally:
        _wait(qapp, lambda: not pane.is_busy)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()
