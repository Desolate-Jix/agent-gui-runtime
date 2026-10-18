"""权威动作证据在同一新学习图中可审核；输入边界全部隔离。"""

from contextlib import contextmanager
from copy import deepcopy

import pytest

from app.agent_link.contracts import AgentLinkError
from app.desktop_review.action_graph_source import ActionGraphSourceReader
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.workspace import DesktopReviewError

from tests.test_formal_fresh_graph_source import _stage, REVIEWER
from tests.test_formal_learning_segments import _perform_action


@contextmanager
def _action_rig(root, *, unknown=False, pin=True):
    host, connection, segment, _, args, first = _stage(root)
    try:
        runtime, receipt, _, child = _perform_action(
            root / "review", host.learning_segments, host.learning_segments.recorder,
            host.learning_segments.capture_archive, connection, segment["segment_id"],
            sequence=1, unknown=unknown, pin=pin,
        )
        yield {"host": host, "connection": connection, "segment": segment, "first": first,
               "args": args, "runtime": runtime, "receipt": receipt, "child": child}
    finally:
        host.close()


def test_finishing_segment_projects_actual_action_and_exact_original_images(tmp_path):
    with _action_rig(tmp_path) as run:
        host, connection = run["host"], run["connection"]
        current = host._service.agent_call(connection["token"], "get_learning_segment", {"segment_id": run["segment"]["segment_id"]})
        finished = host._service.agent_call(connection["token"], "finish_learning_segment", {
            "segment_id": current["segment_id"], "expected_revision": current["revision"]})
        assert "graph" in finished, "finished learning has not reached its review graph"
        assert finished["graph"]["logical_workflow_id"] == run["first"]["logical_workflow_id"]
        snapshot = host.facade.load_graph_revision(run["first"]["logical_workflow_id"])
        assert len(snapshot["graph"]["edges"]) == 1
        assert len(snapshot["graph"]["nodes"]) == 3
        edge = snapshot["graph"]["edges"][0]
        region = snapshot["graph"]["nodes"][1]["regions"][0]
        assert region["display_only"] is True and region["reviewed_by_human"] is False
        assert region["artifact_is_authorization"] is False and region["execute_binding_enabled"] is False
        assert edge["recorded_event"]["receipt_id"] == run["receipt"].receipt_id
        assert edge["recorded_event"]["outcome"] == run["receipt"].outcome
        assert edge["reviewed_by_human"] is False
        assert edge["artifact_is_authorization"] is False and edge["execute_binding_enabled"] is False
        source = snapshot["source_refs"]["action_sources"][0]
        archive = host.learning_segments.capture_archive
        for endpoint, side in (("source_node_id", "before"), ("target_node_id", "after")):
            image = host.facade.load_graph_node_evidence(snapshot["logical_workflow_id"], snapshot["revision"],
                snapshot["content_sha256"], edge[endpoint])["screenshot"]
            capture = source["event_source"][side]
            assert image["png_bytes"] == archive.read_capture(learning_session_id=source["learning_session_id"],
                runtime_session_id=source["runtime_session_id"], capture_id=capture["capture_id"],
                screenshot_sha256=capture["screenshot_sha256"])
        repeated = host._service.agent_call(connection["token"], "finish_learning_segment", {
            "segment_id": current["segment_id"], "expected_revision": current["revision"]})
        assert repeated == finished


def _scope(run):
    return {"connection_id": run["connection"]["connection_id"],
            "task_id": run["connection"]["task_id"], "segment_id": run["segment"]["segment_id"]}


def _finish(run):
    service, token = run["host"]._service, run["connection"]["token"]
    current = service.agent_call(token, "get_learning_segment", {"segment_id": run["segment"]["segment_id"]})
    args = {"segment_id": current["segment_id"], "expected_revision": current["revision"]}
    return service.agent_call(token, "finish_learning_segment", args)


def test_get_is_read_only_and_next_observation_adds_action_without_losing_edits(tmp_path):
    with _action_rig(tmp_path) as run:
        host = run["host"]
        graph = host.facade.load_graph_revision(run["first"]["logical_workflow_id"])
        host._service.agent_call(run["connection"]["token"], "get_learning_segment",
                                 {"segment_id": run["segment"]["segment_id"]})
        assert host.facade.load_graph_revision(graph["logical_workflow_id"]) == graph
        node_id = graph["graph"]["nodes"][0]["node_id"]
        edited = host.facade.apply_graph_edit(graph["logical_workflow_id"], graph["revision"], graph["content_sha256"],
            {"type": "update_node_meaning", "node_id": node_id, "meaning": "人工保留的含义"}, "edit-anchor")
        result = host.fresh_learning.stage(**{**run["args"], "idempotency_key": "after-action"})
        current = host.facade.load_graph_revision(result["logical_workflow_id"])
        assert len(current["graph"]["nodes"]) == 4 and len(current["graph"]["edges"]) == 1
        assert current["graph"]["nodes"][0] == edited["graph"]["nodes"][0]
        assert host.facade.load_graph_revision(graph["logical_workflow_id"], graph["revision"]) == graph
        assert host.fresh_learning.stage(**run["args"])["graph_revision"] == current["revision"]
        edge = current["graph"]["edges"][0]
        corrected = host.facade.apply_graph_edit(current["logical_workflow_id"], current["revision"],
            current["content_sha256"], {"type": "update_edge_target", "edge_id": edge["edge_id"],
                                       "target_node_id": node_id}, "correct-destination")
        assert corrected["graph"]["edges"][0]["recorded_event"] == edge["recorded_event"]
        assert corrected["source_refs"] == current["source_refs"]
        assert corrected["graph"]["edges"][0]["reviewed_by_human"] is False


@pytest.mark.parametrize("unknown,pin", [(True, True), (False, False)])
def test_missing_required_evidence_is_pending_without_invented_transition(tmp_path, unknown, pin):
    with _action_rig(tmp_path, unknown=unknown, pin=pin) as run:
        host = run["host"]
        result = host.fresh_learning.sync_actions(**_scope(run))
        assert result["status"] == "pending_sources"
        assert result["projected_event_count"] == 0 and result["pending_events"]
        graph = host.facade.load_graph_revision(run["first"]["logical_workflow_id"])
        assert graph["revision"] == 1 and len(graph["graph"]["nodes"]) == 1
        assert graph["graph"]["edges"] == [] and "action_sources" not in graph["source_refs"]


def test_action_history_reopens_after_session_finish_and_connection_revocation(tmp_path):
    with _action_rig(tmp_path) as run:
        host = run["host"]
        synced = host.fresh_learning.sync_actions(**_scope(run))
        graph = host.facade.load_graph_revision(synced["logical_workflow_id"])
        source = deepcopy(graph["source_refs"]["action_sources"][0])
        _finish(run)
        assert host.facade.load_graph_revision(graph["logical_workflow_id"]) == graph
        host._service.reviewer_call(REVIEWER, "revoke_connection", {
            "connection_id": run["connection"]["connection_id"], "idempotency_key": "revoke-action"})
        assert host.facade.load_graph_revision(graph["logical_workflow_id"]) == graph
        with pytest.raises(AgentLinkError):
            host.fresh_learning.sync_actions(**_scope(run))
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        assert reopened.facade.load_graph_revision(graph["logical_workflow_id"]) == graph
        assert graph["source_refs"]["action_sources"][0] == source
    finally:
        reopened.close()


def test_corrupted_action_png_rejects_graph_without_using_cached_source(tmp_path):
    with _action_rig(tmp_path) as run:
        host = run["host"]
        synced = host.fresh_learning.sync_actions(**_scope(run))
        graph = host.facade.load_graph_revision(synced["logical_workflow_id"])
        shot = graph["source_refs"]["action_sources"][0]["screenshots"][0]
        path = tmp_path / "review" / shot["path"]
        original = path.read_bytes()
        path.write_bytes(b"isolated-corruption")
        with pytest.raises(DesktopReviewError):
            host.facade.load_graph_revision(graph["logical_workflow_id"])
        path.write_bytes(original)
        assert host.facade.load_graph_revision(graph["logical_workflow_id"]) == graph


def test_source_from_removed_child_is_rejected_even_with_original_event_and_hash(tmp_path):
    with _action_rig(tmp_path) as run:
        host = run["host"]
        reader = ActionGraphSourceReader(host.facade)
        source = reader.collect(**_scope(run))["sources"][0]
        graph = host.facade.load_graph_revision(run["first"]["logical_workflow_id"])
        def detach(state):
            segment = state["connections"][source["connection_id"]]["learning_segments"][source["segment_id"]]
            segment["children"] = []
            segment["revision"] += 1
        host.learning_segments.store.mutate(detach)
        with pytest.raises(DesktopReviewError):
            reader.validate(source, graph["source_refs"]["fresh_learning_source"])


def test_finished_segment_projection_failure_retries_without_another_action(tmp_path, monkeypatch):
    with _action_rig(tmp_path) as run:
        host = run["host"]
        scope = _scope(run)
        current = host.learning_segments.get(**scope)
        append = host.facade.append_learning_action_source
        def unavailable(*args, **kwargs):
            raise OSError("isolated graph write failure")
        monkeypatch.setattr(host.facade, "append_learning_action_source", unavailable)
        with pytest.raises(AgentLinkError) as failed:
            _finish(run)
        assert failed.value.code == "learning_graph_sync_failed"
        assert host.learning_segments.get(**scope)["status"] == "closed"
        monkeypatch.setattr(host.facade, "append_learning_action_source", append)
        retried = host._service.agent_call(run["connection"]["token"], "finish_learning_segment", {
            "segment_id": current["segment_id"], "expected_revision": current["revision"]})
        assert retried["graph"]["projected_event_count"] == 1
        source = ActionGraphSourceReader(host.facade).collect(**scope)["sources"]
        assert len(source) == 1 and source[0]["event"]["terminal"]["receipt_id"] == run["receipt"].receipt_id


def test_finish_without_observation_reports_missing_anchor_not_fake_graph(tmp_path):
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        connection = host._service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": "no-observation", "agent_name": "fresh-agent"})
        segment = host._service.agent_call(connection["token"], "start_learning_segment", {
            "idempotency_key": "empty-segment", "title": "No prior learning"})
        result = _finish({"host": host, "connection": connection, "segment": segment})
        assert result["graph"]["status"] == "missing_observation_anchor"
        assert result["graph"]["projected_event_count"] == 0
        assert result["graph"]["artifact_is_authorization"] is False
        assert host.facade.list_batches() == []
        assert not (tmp_path / "review/desktop-review/graph-revisions").exists()
    finally:
        host.close()
