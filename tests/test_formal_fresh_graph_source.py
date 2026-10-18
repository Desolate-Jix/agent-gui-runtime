"""全新无资产观察进入同一原生图，并保留原图与父来源。"""

from copy import deepcopy

import pytest

from app.agent_link.contracts import AgentLinkError
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.workspace import DesktopReviewError
from tests.test_formal_fresh_learning_observation import _owner


REVIEWER = "fresh-graph-reviewer"


def _stage(root, packet=None):
    host = DesktopReviewHost(root / "inbox.json", root / "review", REVIEWER)
    try:
        assert hasattr(host, "fresh_learning"), "fresh observation graph ingress is missing"
        service = host._service
        connection = service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": "fresh-screen-task", "agent_name": "fresh-agent",
        })
        segment = service.agent_call(connection["token"], "start_learning_segment", {
            "idempotency_key": "new-segment", "title": "New unlearned application",
        })
        if packet is None:
            packet = _owner(root / "capture").observe(target_window_handle=4242, target_process_id=9001)
        args = {"connection_id": connection["connection_id"], "task_id": connection["task_id"],
                "segment_id": segment["segment_id"], "idempotency_key": "first-screen",
                "title": "First screen", "meaning": "\u5f85\u5ba1\u6838\u7684\u65b0\u754c\u9762", "packet": packet}
        result = host.fresh_learning.stage(**args)
        return host, connection, segment, packet, args, result
    except Exception:
        host.close()
        raise


def test_fresh_observation_has_one_reviewable_node_original_png_and_no_fake_action(tmp_path):
    host, connection, segment, packet, args, result = _stage(tmp_path)
    try:
        graph = host.facade.load_graph_revision(result["logical_workflow_id"])
        assert len(graph["graph"]["nodes"]) == 1 and graph["graph"]["edges"] == []
        node = graph["graph"]["nodes"][0]
        assert node["reviewed_by_human"] is False and node["action_candidates"] == []
        assert node["display_name"] == args["meaning"]
        evidence = host.facade.load_graph_node_evidence(graph["logical_workflow_id"], graph["revision"],
            graph["content_sha256"], node["node_id"])
        assert evidence["screenshot"]["png_bytes"] == packet.png_bytes
        assert graph["source_refs"]["fresh_learning_source"]["reference"]["capture_id"] == packet.evidence()["capture"]["capture_id"]
        assert host.fresh_learning.stage(**args)["logical_workflow_id"] == result["logical_workflow_id"]
        assert len(host.facade.list_batches()) == 1
        assert not (tmp_path / "review/runtime_state/reviewed-workflow-assets-v2").exists()
        current = host._service.agent_call(connection["token"], "get_learning_segment", {"segment_id": segment["segment_id"]})
        assert len(current["observations"]) == 1 and current["children"] == []
        edited = host.facade.apply_graph_edit(graph["logical_workflow_id"], graph["revision"], graph["content_sha256"],
            {"type": "update_node_meaning", "node_id": node["node_id"], "meaning": "\u4eba\u5de5\u4fee\u6b63\u7684\u65b0\u754c\u9762"}, "correct-meaning")
        assert edited["revision"] == 2 and edited["source_refs"] == graph["source_refs"]
        assert edited["graph"]["nodes"][0]["reviewed_by_human"] is False
    finally:
        host.close()
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        actual = reopened.facade.load_graph_revision(result["logical_workflow_id"])
        assert actual["graph"]["nodes"][0]["display_name"] == "\u4eba\u5de5\u4fee\u6b63\u7684\u65b0\u754c\u9762"
        assert reopened.facade.load_graph_revision(result["logical_workflow_id"], 1)["graph"]["nodes"][0]["display_name"] == args["meaning"]
    finally:
        reopened.close()


@pytest.mark.parametrize("changed_field", ["meaning", "title", "packet"])
def test_same_stage_key_changed_meaning_or_source_is_not_silent_reuse(tmp_path, changed_field):
    host, connection, segment, packet, args, result = _stage(tmp_path)
    try:
        changed_value = (_owner(tmp_path / "new-capture").observe(target_window_handle=4242, target_process_id=9001)
                         if changed_field == "packet" else "Different proposal")
        with pytest.raises(AgentLinkError) as changed:
            host.fresh_learning.stage(**{**args, changed_field: changed_value})
        assert changed.value.code == "idempotency_conflict"
        other = host._service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": connection["task_id"], "agent_name": "other-agent",
        })
        with pytest.raises(AgentLinkError) as foreign:
            host.fresh_learning.stage(**{**args, "connection_id": other["connection_id"]})
        assert foreign.value.code == "not_found"
    finally:
        host.close()


def test_graph_does_not_downgrade_when_its_fresh_parent_is_missing(tmp_path):
    host, connection, segment, packet, args, result = _stage(tmp_path)
    try:
        archive_root = tmp_path / "review/runtime_state/fresh-learning-v1"
        records = list(archive_root.rglob("*.json"))
        assert records
        originals = [(path, path.read_bytes()) for path in records]
        try:
            for path, _raw in originals:
                path.write_bytes(b"{}")
            with pytest.raises(DesktopReviewError):
                host.facade.load_graph_revision(result["logical_workflow_id"])
        finally:
            for path, raw in originals:
                path.write_bytes(raw)
    finally:
        host.close()


def test_fresh_graph_can_record_scoped_relearning_feedback(tmp_path):
    host, connection, segment, packet, args, result = _stage(tmp_path)
    try:
        graph = host.facade.load_graph_revision(result["logical_workflow_id"])
        node_id = graph["graph"]["nodes"][0]["node_id"]
        feedback = host.facade.request_graph_relearn(graph["logical_workflow_id"], graph["revision"],
            graph["content_sha256"], 0, {"node_ids": [node_id], "edge_ids": []},
            "Check this newly observed meaning", "fresh-issue")
        assert feedback["receipt"]["revision"] == 1
        read = host._service.agent_call(connection["token"], "read_feedback", {"batch_id": result["batch_id"]})
        assert read["issues"][0]["scope"]["node_ids"] == [node_id]
    finally:
        host.close()
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        read = reopened._service.agent_call(connection["token"], "read_feedback", {"batch_id": result["batch_id"]})
        assert read["issues"][0]["scope"]["node_ids"] == [node_id]
        assert reopened.facade.load_graph_revision(result["logical_workflow_id"])["content_sha256"] == graph["content_sha256"]
    finally:
        reopened.close()


def test_segment_capacity_rejects_new_observation_without_corrupting_reopen(tmp_path):
    host, connection, segment, packet, args, result = _stage(tmp_path)
    try:
        assert host.fresh_learning.stage(**args)["logical_workflow_id"] == result["logical_workflow_id"]
        # 直接构造满段夹具，避免为容量边界重复建 255 张无关图。
        def fill(state):
            stored = state["connections"][connection["connection_id"]]["learning_segments"][segment["segment_id"]]
            original = state["batches"][result["batch_id"]]
            for index in range(255):
                batch_id = f"capacity-fixture-{index}"
                batch = {**deepcopy(original), "batch_id": batch_id, "idempotency_key": batch_id}
                state["batches"][batch_id] = batch
                state["feedback"][batch_id] = {"revision": 0, "history": [], "issues": {}}
                stored["observations"].append({"batch_id": batch_id, "source": deepcopy(batch["fresh_learning_source"])})
            stored["revision"] += 255
        host._service._store.mutate(fill)
        before = (tmp_path / "inbox.json").read_bytes()
        # 满段只验证准入和重开；同段积累及重试由独立图回归覆盖。
        with pytest.raises(AgentLinkError) as full:
            host.fresh_learning.stage(**{**args, "idempotency_key": "beyond-capacity"})
        assert full.value.code == "learning_capacity_exceeded"
        assert (tmp_path / "inbox.json").read_bytes() == before
    finally:
        host.close()
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        current = reopened._service.agent_call(connection["token"], "get_learning_segment", {"segment_id": segment["segment_id"]})
        assert len(current["observations"]) == 256
    finally:
        reopened.close()


@pytest.mark.parametrize("stop", ["finish", "revoke"])
def test_inactive_scope_cannot_stage_another_fresh_screen(tmp_path, stop):
    host, connection, segment, packet, args, _ = _stage(tmp_path)
    try:
        if stop == "finish":
            current = host._service.agent_call(connection["token"], "get_learning_segment", {"segment_id": segment["segment_id"]})
            host._service.agent_call(connection["token"], "finish_learning_segment", {
                "segment_id": segment["segment_id"], "expected_revision": current["revision"],
            })
        else:
            host._service.reviewer_call(REVIEWER, "revoke_connection", {
                "connection_id": connection["connection_id"], "idempotency_key": "revoke-fresh",
            })
        before = (tmp_path / "inbox.json").read_bytes()
        with pytest.raises(AgentLinkError):
            host.fresh_learning.stage(**{**args, "idempotency_key": "after-stop"})
        assert (tmp_path / "inbox.json").read_bytes() == before
    finally:
        host.close()
