"""同段多观察经过真实宿主和原生面板积累，不推断跳转。"""

import base64

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app.agent_link.contracts import AgentLinkError
from app.desktop_review.graph_review_pane import GraphReviewPane
from app.desktop_review.host import DesktopReviewHost
from tests.test_formal_learning_observation import _rig, _request, REVIEWER
from tests.test_formal_graph_review_pane import qapp, _wait, _click_node


def test_agent_observations_share_graph_and_preserve_human_edit_and_history(tmp_path, monkeypatch):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        request = _request(segment)
        first = host._service.agent_call(connection["token"], "observe_learning_screen", request)
        graph = host.facade.load_graph_revision(first["logical_workflow_id"])
        first_node = graph["graph"]["nodes"][0]["node_id"]
        edited = host.facade.apply_graph_edit(graph["logical_workflow_id"], graph["revision"], graph["content_sha256"],
            {"type": "update_node_meaning", "node_id": first_node, "meaning": "人工修正的入口"}, "correct-entry")
        second_request = {**request, "idempotency_key": "second-screen", "meaning": "第二个观察"}
        second = host._service.agent_call(connection["token"], "observe_learning_screen", second_request)
        assert second["logical_workflow_id"] == first["logical_workflow_id"]
        assert second["review_batch_id"] == first["batch_id"]
        current = host.facade.load_graph_revision(first["logical_workflow_id"])
        assert current["revision"] == 3
        assert current["parent_sha256"] == edited["content_sha256"]
        assert len(current["graph"]["nodes"]) == 2
        assert len(set(current["graph"]["workflow"]["node_ids"])) == 2
        assert current["graph"]["edges"] == []
        assert current["graph"]["nodes"][0] == edited["graph"]["nodes"][0]
        for node, observation in zip(current["graph"]["nodes"], (first, second), strict=True):
            evidence = host.facade.load_graph_node_evidence(current["logical_workflow_id"], current["revision"],
                current["content_sha256"], node["node_id"])
            assert evidence["screenshot"]["png_bytes"] == base64.b64decode(observation["screenshot"]["png_base64"])
            assert not node["reviewed_by_human"] and not node["action_candidates"]
        assert host.facade.load_graph_revision(first["logical_workflow_id"], 1) == graph
        assert host.facade.load_batch_graph_revision(connection["task_id"], second["batch_id"]) == current
        repeated = host._service.agent_call(connection["token"], "observe_learning_screen", request)
        assert repeated["logical_workflow_id"] == first["logical_workflow_id"]
        assert repeated["graph_revision"] == current["revision"]
        assert len(captures) == 2
        assert len(host.facade.list_batches()) == 2
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        assert reopened.facade.load_graph_revision(first["logical_workflow_id"]) == current
        assert reopened.facade.load_graph_revision(first["logical_workflow_id"], 1) == graph
        assert reopened.facade.load_batch_graph_revision(connection["task_id"], second["batch_id"]) == current
        repeated = reopened._service.agent_call(connection["token"], "observe_learning_screen", second_request)
        assert repeated["graph_revision"] == 3 and len(captures) == 2
    finally:
        reopened.close()


def test_committed_second_observation_recovers_graph_append_without_recapture(tmp_path, monkeypatch):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        request = _request(segment)
        first = host._service.agent_call(connection["token"], "observe_learning_screen", request)
        append = getattr(host.facade, "append_fresh_graph_source", None)
        assert callable(append), "same-segment source append is missing"
        def unavailable(*args, **kwargs):
            raise OSError("isolated graph append failure")
        monkeypatch.setattr(host.facade, "append_fresh_graph_source", unavailable)
        second_request = {**request, "idempotency_key": "second-screen", "meaning": "新观察"}
        with pytest.raises(AgentLinkError):
            host._service.agent_call(connection["token"], "observe_learning_screen", second_request)
        assert len(captures) == 2 and len(host.facade.list_batches()) == 2
        monkeypatch.setattr(host.facade, "append_fresh_graph_source", append)
        retried = host._service.agent_call(connection["token"], "observe_learning_screen", second_request)
        assert retried["logical_workflow_id"] == first["logical_workflow_id"]
        assert retried["graph_revision"] == 2 and len(captures) == 2
        current = host.facade.load_graph_revision(first["logical_workflow_id"])
        assert len(current["graph"]["nodes"]) == 2 and current["graph"]["edges"] == []


def test_second_observation_is_editable_and_relearnable_in_native_graph(tmp_path, monkeypatch, qapp):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        request = _request(segment)
        first = host._service.agent_call(connection["token"], "observe_learning_screen", request)
        second = host._service.agent_call(connection["token"], "observe_learning_screen",
            {**request, "idempotency_key": "next-screen", "meaning": "第二个界面"})
        assert first["logical_workflow_id"] == second["logical_workflow_id"]
        pane = GraphReviewPane(host.facade)
        pane.resize(1280, 760)
        pane.show()
        try:
            current = host.facade.load_batch_graph_revision(connection["task_id"], second["batch_id"])
            node = current["graph"]["nodes"][1]
            pane.load_graph(first["logical_workflow_id"])
            _wait(qapp, lambda: not pane.is_busy and node["node_id"] in pane.graph_view._node_items)
            assert len(pane.graph_view._node_items) == 2
            _click_node(pane, node["node_id"])
            _wait(qapp, lambda: not pane.is_busy and pane.before_canvas._pixmap_item is not None)
            image = pane.before_canvas._pixmap_item.pixmap()
            assert (image.width(), image.height()) == (second["screenshot"]["width"], second["screenshot"]["height"])
            assert pane.node_meaning_edit.text() == "第二个界面"
            pane.node_meaning_edit.setText("人工修正第二个界面")
            QTest.mouseClick(pane.save_node_meaning_button, Qt.MouseButton.LeftButton)
            _wait(qapp, lambda: not pane.is_busy and not pane.is_dirty)
            edited = host.facade.load_graph_revision(first["logical_workflow_id"])
            assert edited["graph"]["nodes"][1]["display_name"] == "人工修正第二个界面"
            assert edited["graph"]["edges"] == []
            feedback = host.facade.request_graph_relearn(edited["logical_workflow_id"], edited["revision"],
                edited["content_sha256"], 0, {"node_ids": [node["node_id"]], "edge_ids": []},
                "重新检查第二个界面的含义", "relearn-second")
            read = host._service.agent_call(connection["token"], "read_feedback", {"batch_id": first["batch_id"]})
            assert read["issues"][0]["scope"]["node_ids"] == [node["node_id"]]
            assert feedback["receipt"]["revision"] == 1
        finally:
            _wait(qapp, lambda: not pane.is_busy)
            pane.close()
            _wait(qapp, lambda: not pane._jobs)
