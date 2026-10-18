"""普通流程项目可安全编辑 recorded_actions 图；不创建伪界面或授权。"""

from copy import deepcopy

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest

from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
from app.desktop_review.workspace import DesktopReviewError
from tests.test_formal_graph_review_pane import qapp, _click_node, _wait
from tests.test_reviewed_action_only_graph import _rig, _scope
from tests.test_formal_fresh_graph_source import REVIEWER


def _project(host, connection, segment):
    synced = host.fresh_learning.sync_actions(**_scope(connection, segment))
    return host.facade.load_workflow_project(synced["logical_workflow_id"])


def _changes(project, *, title="保存的动作项目"):
    edges = []
    for edge in project["graph"]["edges"]:
        edges.append({
            "edge_id": edge["edge_id"], "source_node_id": edge["source_node_id"],
            "target_node_id": edge["target_node_id"], "action_type": edge["action_type"],
            "target_region_id": edge.get("target_region_id"), "expected_result": "显示详情",
            "condition": "动作完成",
        })
    return {"title": title, "edges": edges}


def test_action_project_overlay_save_is_pinned_idempotent_and_reopenable(tmp_path):
    with _rig(tmp_path) as (host, connection, segment):
        project = _project(host, connection, segment)
        saved = host.facade.save_workflow_project(project["logical_workflow_id"],
            project["content_sha256"], _changes(project), "save-action-project")
        repeated = host.facade.save_workflow_project(project["logical_workflow_id"],
            project["content_sha256"], _changes(project), "save-action-project")
        assert repeated == saved
        assert saved["snapshot_id"] and saved["source_sha256"] == project["source_sha256"]
        assert saved["graph"]["workflow"]["goal"] == "保存的动作项目"
        assert saved["artifact_is_authorization"] is False
        memory = host.facade.get_workflow_project_memory(
            connection["task_id"], project["logical_workflow_id"], saved["snapshot_id"])
        assert memory["snapshot_id"] == saved["snapshot_id"]
        assert memory["source_sha256"] == saved["source_sha256"]
        assert memory["warnings"] == [
            "每条连线只证明该动作自己的操作前后画面；不同动作之间的先后与衔接尚未证明，画面排列不是执行顺序。"]
        with pytest.raises(DesktopReviewError, match="stale_workflow_project"):
            host.facade.save_workflow_project(project["logical_workflow_id"], "0" * 64,
                _changes(project, title="不得写入"), "stale-action-project")
    reopened = host.__class__(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        assert reopened.facade.get_workflow_project_memory(
            connection["task_id"], project["logical_workflow_id"], saved["snapshot_id"]) == memory
    finally:
        reopened.close()


def test_old_action_project_snapshot_remains_immutable_after_next_overlay(tmp_path):
    with _rig(tmp_path) as (host, connection, segment):
        project = _project(host, connection, segment)
        first = host.facade.save_workflow_project(project["logical_workflow_id"],
            project["content_sha256"], _changes(project, title="第一版"), "first-overlay")
        current = host.facade.load_workflow_project(project["logical_workflow_id"])
        second = host.facade.save_workflow_project(project["logical_workflow_id"],
            current["content_sha256"], _changes(current, title="第二版"), "second-overlay")
        assert host.facade.get_workflow_project_memory(connection["task_id"],
            project["logical_workflow_id"], first["snapshot_id"])["graph"]["workflow"]["goal"] == "第一版"
        assert second["graph"]["workflow"]["goal"] == "第二版"


def test_ordinary_project_node_opens_owned_action_evidence_editor(tmp_path, qapp):
    with _rig(tmp_path) as (host, connection, segment):
        project = _project(host, connection, segment)
        pane = WorkflowProjectsPane(host.facade)
        try:
            pane._install(deepcopy(project))
            first_id = project["graph"]["nodes"][0]["node_id"]
            node_id = project["graph"]["nodes"][1]["node_id"]
            _click_node(pane, node_id)
            qapp.processEvents()
            assert pane.details.currentWidget() is pane.action_evidence_editor
            assert pane.action_evidence_editor.review_graph_button.isHidden()
            assert pane.action_evidence_editor.graph_relearn_button.isHidden()
            assert pane.action_evidence_editor.graph_box.isHidden()
            assert pane.action_evidence_editor._snapshot["content_sha256"] == project["source_sha256"]
            assert pane.action_evidence_editor._selection == ("node", node_id)
            _wait(qapp, lambda: not pane.action_evidence_editor._busy
                  and pane.action_evidence_editor.node_meaning_edit.isEnabled())
            pane.action_evidence_editor.node_meaning_edit.setText("操作后详情证据")
            QTest.mouseClick(pane.action_evidence_editor.save_node_meaning_button,
                             Qt.MouseButton.LeftButton)
            _wait(qapp, lambda: not pane.action_evidence_editor._busy
                  and pane.snapshot["source_sha256"] != project["source_sha256"])
            nodes = {item["node_id"]: item for item in pane.snapshot["graph"]["nodes"]}
            assert nodes[node_id]["display_name"] == "操作后详情证据"
            assert nodes[first_id]["display_name"] == project["graph"]["nodes"][0]["display_name"]
            pane.title_edit.setText("未保存标题")
            before = pane.snapshot["content_sha256"]
            pane.refresh()
            assert pane.snapshot["content_sha256"] == before
            assert pane.title_edit.text() == "未保存标题"
        finally:
            pane.discard_changes()
            _wait(qapp, lambda: not pane.is_busy)
            pane.close()


def test_deferred_delete_with_action_evidence_busy_has_no_picker_crash(tmp_path, qapp):
    with _rig(tmp_path) as (host, connection, segment):
        _project(host, connection, segment)
        pane = WorkflowProjectsPane(host.facade)
        pane.action_evidence_editor._busy = True
        assert pane.event(QEvent(QEvent.Type.DeferredDelete)) is True
        assert pane._delete_after_picker is True
        pane.action_evidence_editor._busy = False
        pane.action_evidence_editor.busyChanged.emit(False)
        qapp.processEvents()


def test_deferred_delete_waits_for_job_cleanup_after_result_signal(tmp_path, qapp):
    from shiboken6 import isValid

    with _rig(tmp_path) as (host, connection, segment):
        _project(host, connection, segment)
        pane = WorkflowProjectsPane(host.facade)
        pending_job = object()
        pane.action_evidence_editor._jobs.add(pending_job)
        assert pane.action_evidence_editor._busy is False
        assert pane.is_busy
        assert pane.event(QEvent(QEvent.Type.DeferredDelete)) is True
        qapp.processEvents()
        assert isValid(pane)
        pane.action_evidence_editor._jobs.clear()
        _wait(qapp, lambda: not isValid(pane))
