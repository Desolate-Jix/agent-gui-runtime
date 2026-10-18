from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt, Signal
from PySide6.QtGui import QRawFont
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.desktop_review.graph_relearn_dialog import GraphRelearnDialog
from app.desktop_review.graph_review_pane import GraphReviewPane
from app.desktop_review.window import ensure_application
from app.desktop_review.workspace import NativeReviewFacade
from tests.test_formal_graph_review_pane import (
    BATCH,
    TASK,
    TOKEN,
    _batch,
    _click_edge,
    _click_node,
    _node,
)


PW = Path(".superpowers/sdd/2026-09-10-graph-centered-formal-revision")


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    application = ensure_application()
    raw_font = QRawFont.fromFont(application.font())
    assert raw_font.isValid() and raw_font.supportsCharacter(0x4E2D)
    return application


def _wait(qapp: QApplication, predicate, timeout_ms: int = 7000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Qt asynchronous operation timed out")


def _runtime_with_agent(
    tmp_path: Path,
    agent_name: str,
) -> tuple[AgentLinkStore, AgentLinkService, NativeReviewFacade, dict, dict]:
    store = AgentLinkStore(tmp_path / "fresh-graph-ui-inbox.json")
    service = AgentLinkService(store, TOKEN)
    grant = service.reviewer_call(
        TOKEN, "create_connection", {"task_id": TASK, "agent_name": agent_name},
    )
    service.agent_call(grant["token"], "submit_batch", _batch())
    facade = NativeReviewFacade(service, TOKEN, tmp_path / "fresh-pane-artifacts")
    snapshot = facade.create_graph_revision(
        TASK, BATCH, 0, {"open-result": ["rel-open"]},
    )
    return store, service, facade, snapshot, grant


def _open_dialog(
    pane: GraphReviewPane,
    qapp: QApplication,
) -> GraphRelearnDialog:
    QTest.mouseClick(pane.graph_relearn_button, Qt.MouseButton.LeftButton)
    _wait(qapp, lambda: pane._relearn_dialog is not None)
    dialog = pane._relearn_dialog
    assert isinstance(dialog, GraphRelearnDialog)
    _wait(qapp, lambda: not dialog.is_busy and dialog.feedback is not None)
    return dialog


def _agent_candidate(
    *,
    created: dict,
    issue: dict,
    changes: list[dict],
    key: str,
) -> dict:
    return {
        "contract_version": "agent_link_graph_candidate_v1",
        "idempotency_key": key,
        "batch_id": BATCH,
        "issue_id": issue["issue_id"],
        "baseline_revision": issue["baseline_revision"],
        "review_baseline_sha256": issue["review_baseline_sha256"],
        "logical_workflow_id": created["logical_workflow_id"],
        "baseline_graph_sha256": created["content_sha256"],
        "scope": deepcopy(issue["scope"]),
        "changes": deepcopy(changes),
    }


class _HeldFinishedJob(QObject):
    succeeded = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, request_id: int, operation, parent: QObject) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self.operation = operation

    def start(self) -> None:
        try:
            self.succeeded.emit(self.request_id, self.operation())
        except Exception as error:  # pragma: no cover - narrow fake failure parity
            self.failed.emit(self.request_id, str(error))

    def release_finished(self) -> None:
        self.finished.emit()


def test_graph_relearn_native_entrypoints_exist() -> None:
    assert callable(getattr(NativeReviewFacade, "get_graph_relearn_feedback", None))
    assert callable(getattr(GraphRelearnDialog, "refresh_feedback", None))


def test_node_issue_candidate_comparison_and_explicit_adoption_round_trip(
    tmp_path: Path,
    qapp: QApplication,
) -> None:
    store, service, facade, created, grant = _runtime_with_agent(
        tmp_path, "graph-ui-candidate-agent",
    )
    source_path = (
        tmp_path / "fresh-pane-artifacts" / created["source_refs"]["original_batch_path"]
    )
    revision_path = (
        tmp_path
        / "fresh-pane-artifacts"
        / "desktop-review"
        / "graph-revisions"
        / created["logical_workflow_id"]
        / "revisions"
        / f"{created['content_sha256']}.json"
    )
    source_bytes, revision_bytes = source_path.read_bytes(), revision_path.read_bytes()
    pane = GraphReviewPane(facade)
    pane.resize(1280, 780)
    pane.show()
    revisions = QSignalSpy(pane.revisionChanged)
    try:
        assert not pane.graph_relearn_button.isEnabled()
        pane.load_graph(created["logical_workflow_id"])
        assert pane.is_busy and not pane.graph_relearn_button.isEnabled()
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 1)
        node = _node(created, "state-a")
        _click_node(pane, node["node_id"])
        assert pane.is_busy and not pane.graph_relearn_button.isEnabled()
        _wait(qapp, lambda: not pane.is_busy and pane.graph_relearn_button.isEnabled())
        pane.node_meaning_edit.setText("尚未保存")
        assert pane.is_dirty and not pane.graph_relearn_button.isEnabled()
        QTest.mouseClick(pane.revert_button, Qt.MouseButton.LeftButton)
        assert pane.graph_relearn_button.isEnabled()

        dialog = _open_dialog(pane, qapp)
        assert dialog.selection == ("node", node["node_id"])
        dialog.issue_message.setPlainText("重新核对当前节点含义")
        QTest.mouseClick(dialog.submit_issue_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not dialog.is_busy and dialog.issue_list.count() == 1)
        feedback = service.agent_call(
            grant["token"], "read_feedback", {"batch_id": BATCH},
        )
        issue = feedback["issues"][0]
        assert issue["scope"] == {"node_ids": [node["node_id"]], "edge_ids": []}
        assert dialog.issue_list.item(0).data(Qt.ItemDataRole.UserRole)["issue_id"] == issue["issue_id"]

        candidate = _agent_candidate(
            created=created,
            issue=issue,
            key="graph-ui-node-candidate",
            changes=[{
                "type": "update_node_meaning",
                "node_id": node["node_id"],
                "meaning": "Agent 候选的新节点含义",
            }, {
                "type": "update_region_bbox",
                "node_id": node["node_id"],
                "region_id": "region-state-a",
                "bbox": [12, 14, 25, 16],
            }],
        )
        submitted = service.agent_call(grant["token"], "submit_candidate", candidate)
        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not dialog.is_busy and dialog.candidate_combo.count() == 2)
        dialog.candidate_combo.setCurrentIndex(1)
        _wait(qapp, lambda: not dialog.is_busy and dialog.comparison is not None)
        assert dialog.comparison["candidate_id"] == submitted["candidate_id"]
        assert dialog.comparison["status"] == "current"
        preview = dialog.comparison["operation_previews"][0]
        assert preview["before"] == node["display_name"]
        assert preview["after"] == "Agent 候选的新节点含义"
        assert dialog.comparison["operation_previews"][1]["region_id"] == "region-state-a"
        assert pane._snapshot["revision"] == 1
        assert facade.load_graph_revision(created["logical_workflow_id"])["revision"] == 1
        render = (
            PW
            / "w3-graph-relearn-ui"
            / "graph-candidate-comparison-font-verified.png"
        )
        render.parent.mkdir(parents=True, exist_ok=True)
        assert dialog.grab().save(str(render), "PNG")
        assert render.is_file() and hashlib.sha256(render.read_bytes()).hexdigest()

        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: pane._relearn_dialog is None and revisions.count() == 2)
        _wait(qapp, lambda: not pane.is_busy)
        current = facade.load_graph_revision(created["logical_workflow_id"])
        assert current["revision"] == 2
        assert _node(current, "state-a")["display_name"] == "Agent 候选的新节点含义"
        assert next(
            item for item in _node(current, "state-a")["regions"]
            if item["region_id"] == "region-state-a"
        )["bbox"] == [12.0, 14.0, 25.0, 16.0]
        assert pane._snapshot == current
        assert source_path.read_bytes() == source_bytes
        assert revision_path.read_bytes() == revision_bytes
    finally:
        if pane._relearn_dialog is not None:
            _wait(qapp, lambda: not pane._relearn_dialog.is_busy)
            pane._relearn_dialog.reject()
        # 独立测试面板没有主窗口持有，先销毁已关闭的子对话框再释放父包装器。
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()


def test_edge_scope_stale_and_withdrawn_candidate_never_auto_adopts(
    tmp_path: Path,
    qapp: QApplication,
) -> None:
    store, service, facade, created, grant = _runtime_with_agent(
        tmp_path, "graph-ui-edge-agent",
    )
    edge = created["graph"]["edges"][0]
    requested = facade.request_graph_relearn(
        created["logical_workflow_id"],
        1,
        created["content_sha256"],
        0,
        {"node_ids": [], "edge_ids": [edge["edge_id"]]},
        "重新核对这条边",
        "graph-ui-edge-issue",
    )
    issue = service.agent_call(
        grant["token"], "read_feedback", {"batch_id": BATCH},
    )["issues"][0]
    assert issue["scope"] == {"node_ids": [], "edge_ids": [edge["edge_id"]]}
    submitted = service.agent_call(
        grant["token"],
        "submit_candidate",
        _agent_candidate(
            created=created,
            issue=issue,
            key="graph-ui-edge-candidate",
            changes=[{
                "type": "update_edge_semantics",
                "edge_id": edge["edge_id"],
                "expected_result": "候选目标可见",
                "stop_condition": "候选目标不可见即停",
                "prerequisites": ["来源仍可见"],
                "relationship_kinds": {"rel-open": "候选关系"},
            }],
        ),
    )
    pane = GraphReviewPane(facade)
    pane.resize(1200, 760)
    pane.show()
    revisions = QSignalSpy(pane.revisionChanged)
    errors = QSignalSpy(pane.errorRaised)
    try:
        pane.load_graph(created["logical_workflow_id"])
        _wait(qapp, lambda: not pane.is_busy and revisions.count() == 1)
        _click_edge(pane, edge["edge_id"])
        _wait(qapp, lambda: not pane.is_busy and pane.graph_relearn_button.isEnabled())
        dialog = _open_dialog(pane, qapp)
        assert dialog.selection == ("edge", edge["edge_id"])
        assert dialog.issue_list.count() == 1 and dialog.candidate_combo.count() == 2

        advanced = facade.apply_graph_edit(
            created["logical_workflow_id"],
            1,
            created["content_sha256"],
            {
                "type": "update_node_meaning",
                "node_id": _node(created, "state-c")["node_id"],
                "meaning": "外部人工修订",
            },
            "graph-ui-external-head",
        )
        dialog.candidate_combo.setCurrentIndex(1)
        _wait(qapp, lambda: not dialog.is_busy and dialog.comparison is not None)
        assert dialog.comparison["candidate_id"] == submitted["candidate_id"]
        assert dialog.comparison["status"] == "stale"
        assert not dialog.adopt_button.isEnabled()
        dialog.adopt_candidate()
        assert facade.load_graph_revision(created["logical_workflow_id"])["revision"] == advanced["revision"]
        assert pane._snapshot["revision"] == 1

        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        _wait(qapp, lambda: not dialog.is_busy)
        assert dialog.issue_list.count() == 1
        assert dialog.comparison is not None

        service.reviewer_call(
            TOKEN,
            "withdraw_issue",
            {
                "task_id": TASK,
                "batch_id": BATCH,
                "issue_id": issue["issue_id"],
                "expected_revision": requested["revision"],
                "idempotency_key": "graph-ui-withdraw-edge",
            },
        )
        dialog.candidate_combo.setCurrentIndex(0)
        dialog.candidate_combo.setCurrentIndex(1)
        _wait(qapp, lambda: not dialog.is_busy and dialog.comparison is not None)
        assert dialog.comparison["status"] == "withdrawn"
        assert not dialog.adopt_button.isEnabled()
        assert facade.load_graph_revision(created["logical_workflow_id"])["revision"] == 2
        assert errors.count() == 0
    finally:
        if pane._relearn_dialog is not None:
            _wait(qapp, lambda: not pane._relearn_dialog.is_busy)
            pane._relearn_dialog.reject()
        # 清空已关闭子窗口的延迟删除事件，不用延时掩盖父子对象生命周期竞态。
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        pane.close()
        _wait(qapp, lambda: not pane._jobs)
        facade.close()
        store.close()


def test_candidate_touching_an_unselected_node_is_preview_only(
    tmp_path: Path,
    qapp: QApplication,
) -> None:
    store, service, facade, created, grant = _runtime_with_agent(
        tmp_path, "graph-ui-expanded-scope-agent",
    )
    node_a = _node(created, "state-a")
    node_b = _node(created, "state-b")
    requested = facade.request_graph_relearn(
        created["logical_workflow_id"],
        1,
        created["content_sha256"],
        0,
        {"node_ids": [node_a["node_id"], node_b["node_id"]], "edge_ids": []},
        "同时检查两个节点",
        "graph-ui-expanded-scope-issue",
    )
    issue = service.agent_call(
        grant["token"], "read_feedback", {"batch_id": BATCH},
    )["issues"][0]
    submitted = service.agent_call(
        grant["token"],
        "submit_candidate",
        _agent_candidate(
            created=created,
            issue=issue,
            key="graph-ui-expanded-scope-candidate",
            changes=[
                {
                    "type": "update_node_meaning",
                    "node_id": node_a["node_id"],
                    "meaning": "候选 A",
                },
                {
                    "type": "update_node_meaning",
                    "node_id": node_b["node_id"],
                    "meaning": "候选 B",
                },
            ],
        ),
    )
    assert requested["revision"] == 1
    dialog = GraphRelearnDialog(
        facade, created, ("node", node_a["node_id"]),
    )
    dialog.show()
    try:
        _wait(qapp, lambda: not dialog.is_busy and dialog.candidate_combo.count() == 2)
        dialog.candidate_combo.setCurrentIndex(1)
        _wait(qapp, lambda: not dialog.is_busy and dialog.comparison is not None)
        assert dialog.comparison["candidate_id"] == submitted["candidate_id"]
        assert dialog.comparison["status"] == "current"
        assert "超出当前" in dialog.comparison_status.text()
        assert not dialog.adopt_button.isEnabled()
        dialog.adopt_candidate()
        assert facade.load_graph_revision(created["logical_workflow_id"])["revision"] == 1
    finally:
        dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()
        facade.close()
        store.close()


def test_busy_dialog_waits_for_worker_finished_before_escape_or_adoption_close(
    tmp_path: Path,
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, service, facade, created, grant = _runtime_with_agent(
        tmp_path, "graph-ui-held-job-agent",
    )
    node = _node(created, "state-a")
    requested = facade.request_graph_relearn(
        created["logical_workflow_id"],
        1,
        created["content_sha256"],
        0,
        {"node_ids": [node["node_id"]], "edge_ids": []},
        "检查生命周期",
        "graph-ui-held-job-issue",
    )
    issue = service.agent_call(
        grant["token"], "read_feedback", {"batch_id": BATCH},
    )["issues"][0]
    service.agent_call(
        grant["token"],
        "submit_candidate",
        _agent_candidate(
            created=created,
            issue=issue,
            key="graph-ui-held-job-candidate",
            changes=[{
                "type": "update_node_meaning",
                "node_id": node["node_id"],
                "meaning": "生命周期候选",
            }],
        ),
    )
    assert requested["revision"] == 1
    dialog = GraphRelearnDialog(facade, created, ("node", node["node_id"]))
    dialog.show()
    held: list[_HeldFinishedJob] = []
    finished = QSignalSpy(dialog.finished)
    try:
        _wait(qapp, lambda: not dialog.is_busy and dialog.candidate_combo.count() == 2)
        dialog.candidate_combo.setCurrentIndex(1)
        _wait(qapp, lambda: not dialog.is_busy and dialog.adopt_button.isEnabled())

        def make_held(request_id, operation, parent):
            job = _HeldFinishedJob(request_id, operation, parent)
            held.append(job)
            return job

        monkeypatch.setattr(
            "app.desktop_review.graph_relearn_dialog.make_job", make_held,
        )
        QTest.mouseClick(dialog.adopt_button, Qt.MouseButton.LeftButton)
        assert len(held) == 1
        assert dialog.is_busy
        assert dialog.isVisible()
        assert finished.count() == 0
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        dialog.reject()
        assert dialog.isVisible()
        assert finished.count() == 0

        held[0].release_finished()
        _wait(qapp, lambda: finished.count() == 1)
        assert not dialog.isVisible()
        assert facade.load_graph_revision(created["logical_workflow_id"])["revision"] == 2
    finally:
        if dialog.isVisible():
            dialog.reject()
        dialog.deleteLater()
        qapp.processEvents()
        facade.close()
        store.close()
