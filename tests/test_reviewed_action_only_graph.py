"""Reviewed replay 的权威动作可独立形成待审核图，不伪造 fresh 观察。"""

from contextlib import contextmanager
from copy import deepcopy

import pytest

from app.desktop_review.action_graph_source import ActionGraphSourceReader
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.workspace import DesktopReviewError
from app.desktop_review.exact_review import ExactReviewError
from tests.test_formal_fresh_graph_source import REVIEWER
from tests.test_formal_learning_segments import _perform_action


@contextmanager
def _rig(root, *, action=True, unknown=False, pin=True):
    host = DesktopReviewHost(root / "inbox.json", root / "review", REVIEWER)
    connection = host._service.reviewer_call(REVIEWER, "create_connection", {
        "task_id": "reviewed-action-only", "agent_name": "reviewed-agent"})
    segment = host._service.agent_call(connection["token"], "start_learning_segment", {
        "idempotency_key": "action-only-segment", "title": "Reviewed replay"})
    try:
        if action:
            _perform_action(root / "review", host.learning_segments,
                            host.learning_segments.recorder, host.learning_segments.capture_archive,
                            connection, segment["segment_id"], sequence=1, unknown=unknown, pin=pin)
        yield host, connection, segment
    finally:
        host.close()


def _scope(connection, segment):
    return {"connection_id": connection["connection_id"], "task_id": connection["task_id"],
            "segment_id": segment["segment_id"]}


def test_complete_recorded_action_creates_strict_action_only_graph(tmp_path):
    with _rig(tmp_path) as (host, connection, segment):
        result = host.fresh_learning.sync_actions(**_scope(connection, segment))
        assert result["status"] == "synchronized" and result["projected_event_count"] == 1
        graph = host.facade.load_graph_revision(result["logical_workflow_id"])
        assert graph["source_refs"]["kind"] == "recorded_actions"
        assert "batch_id" not in graph["source_refs"] and "fresh_learning_source" not in graph["source_refs"]
        assert graph["source_refs"]["anchor_event_id"] == graph["source_refs"]["action_sources"][0]["event_id"]
        assert len(graph["graph"]["nodes"]) == 2 and len(graph["graph"]["edges"]) == 1
        assert graph["graph"]["artifact_is_authorization"] is False
        assert graph["graph"]["execute_binding_enabled"] is False
        assert host.facade.list_batches() == []
        listed = host.facade.list_workflow_graphs()
        assert any(item["logical_workflow_id"] == graph["logical_workflow_id"] for item in listed)
        project = host.facade.load_workflow_project(graph["logical_workflow_id"])
        memory = host.facade.get_workflow_project_memory(
            connection["task_id"], graph["logical_workflow_id"])
        assert project["logical_workflow_id"] == graph["logical_workflow_id"]
        assert memory["logical_workflow_id"] == graph["logical_workflow_id"]
        assert len(memory["graph"]["edges"]) == 1
        edge = graph["graph"]["edges"][0]
        for node_id in (edge["source_node_id"], edge["target_node_id"]):
            evidence = host.facade.load_graph_node_evidence(
                graph["logical_workflow_id"], graph["revision"], graph["content_sha256"], node_id)
            assert evidence["screenshot"]["png_bytes"].startswith(b"\x89PNG")


def test_action_only_sync_is_idempotent_and_preserves_manual_edit(tmp_path):
    with _rig(tmp_path) as (host, connection, segment):
        scope = _scope(connection, segment)
        first = host.fresh_learning.sync_actions(**scope)
        graph = host.facade.load_graph_revision(first["logical_workflow_id"])
        node = graph["graph"]["nodes"][0]["node_id"]
        edited = host.facade.apply_graph_edit(graph["logical_workflow_id"], graph["revision"],
            graph["content_sha256"], {"type": "update_node_meaning", "node_id": node,
                                      "meaning": "人工保留"}, "keep-edit")
        repeated = host.fresh_learning.sync_actions(**scope)
        assert repeated["logical_workflow_id"] == first["logical_workflow_id"]
        assert host.facade.load_graph_revision(first["logical_workflow_id"])["graph"]["nodes"][0] == edited["graph"]["nodes"][0]
        workflow_id = first["logical_workflow_id"]
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        assert reopened.facade.load_graph_revision(workflow_id)["graph"]["nodes"][0] == edited["graph"]["nodes"][0]
    finally:
        reopened.close()


def test_finish_learning_segment_projects_two_actions_once_and_closes(tmp_path):
    with _rig(tmp_path) as (host, connection, segment):
        _perform_action(tmp_path / "review", host.learning_segments,
                        host.learning_segments.recorder, host.learning_segments.capture_archive,
                        connection, segment["segment_id"], sequence=2)
        current = host._service.agent_call(connection["token"], "get_learning_segment",
                                           {"segment_id": segment["segment_id"]})
        args = {"segment_id": segment["segment_id"], "expected_revision": current["revision"]}
        finished = host._service.agent_call(connection["token"], "finish_learning_segment", args)
        assert finished["status"] == "closed"
        assert finished["graph"]["status"] == "synchronized"
        assert finished["graph"]["projected_event_count"] == 2
        repeated = host._service.agent_call(connection["token"], "finish_learning_segment", args)
        assert repeated == finished


@pytest.mark.parametrize("unknown,pin", [(True, True), (False, False)])
def test_missing_action_evidence_stays_pending_without_graph(tmp_path, unknown, pin):
    with _rig(tmp_path, unknown=unknown, pin=pin) as (host, connection, segment):
        result = host.fresh_learning.sync_actions(**_scope(connection, segment))
        assert result["status"] == "pending_sources" and result["projected_event_count"] == 0
        assert result["pending_events"]
        assert not (tmp_path / "review/desktop-review/graph-revisions").exists()


def test_empty_segment_keeps_missing_observation_anchor(tmp_path):
    with _rig(tmp_path, action=False) as (host, connection, segment):
        result = host.fresh_learning.sync_actions(**_scope(connection, segment))
        assert result["status"] == "missing_observation_anchor"
        assert result["projected_event_count"] == 0


def test_action_only_source_rejects_rewrite_and_foreign_scope(tmp_path):
    with _rig(tmp_path) as (host, connection, segment):
        scope = _scope(connection, segment)
        result = host.fresh_learning.sync_actions(**scope)
        graph = host.facade.load_graph_revision(result["logical_workflow_id"])
        source = graph["source_refs"]["action_sources"][0]
        changed = deepcopy(source)
        changed["event"]["terminal"]["outcome"] = "INDETERMINATE"
        with pytest.raises(DesktopReviewError):
            host.facade.append_learning_action_source(graph["logical_workflow_id"], changed)
        with pytest.raises(DesktopReviewError):
            ActionGraphSourceReader(host.facade).validate(source, {**scope, "segment_id": "foreign"})


def test_action_only_original_png_tamper_is_rejected(tmp_path):
    with _rig(tmp_path) as (host, connection, segment):
        result = host.fresh_learning.sync_actions(**_scope(connection, segment))
        graph = host.facade.load_graph_revision(result["logical_workflow_id"])
        shot = graph["source_refs"]["action_sources"][0]["screenshots"][0]
        path = tmp_path / "review" / shot["path"]
        original = path.read_bytes()
        path.write_bytes(b"tampered")
        with pytest.raises(DesktopReviewError):
            host.facade.load_graph_revision(graph["logical_workflow_id"])
        path.write_bytes(original)


def test_legacy_publish_and_relearn_reject_before_side_effects(tmp_path):
    with _rig(tmp_path) as (host, connection, segment):
        result = host.fresh_learning.sync_actions(**_scope(connection, segment))
        graph = host.facade.load_graph_revision(result["logical_workflow_id"])
        before = host.learning_segments.store.read(lambda value: deepcopy(value))
        with pytest.raises(ExactReviewError, match="纯动作图"):
            host.facade.prepare_graph_exact_review(graph["logical_workflow_id"], graph["revision"],
                                                   graph["content_sha256"], {})
        with pytest.raises(DesktopReviewError, match="纯动作图"):
            host.facade.request_graph_relearn(graph["logical_workflow_id"], graph["revision"],
                graph["content_sha256"], 0, {"node_ids": [], "edge_ids": []},
                "unsupported", "action-only-relearn")
        assert host.learning_segments.store.read(lambda value: deepcopy(value)) == before
        assert not (tmp_path / "review/desktop-review/exact-staging").exists()


def test_later_complete_event_fixes_anchor_and_earlier_event_does_not_split_graph(tmp_path, monkeypatch):
    with _rig(tmp_path) as (host, connection, segment):
        _perform_action(tmp_path / "review", host.learning_segments,
                        host.learning_segments.recorder, host.learning_segments.capture_archive,
                        connection, segment["segment_id"], sequence=2)
        scope = _scope(connection, segment)
        reader = ActionGraphSourceReader(host.facade)
        actual = reader.collect(**scope)
        assert len(actual["sources"]) == 2
        collect = ActionGraphSourceReader.collect
        monkeypatch.setattr(ActionGraphSourceReader, "collect",
                            lambda self, **kwargs: {"sources": [actual["sources"][1]], "pending_events": []})
        first = host.fresh_learning.sync_actions(**scope)
        graph = host.facade.load_graph_revision(first["logical_workflow_id"])
        node = graph["graph"]["nodes"][0]["node_id"]
        edited = host.facade.apply_graph_edit(graph["logical_workflow_id"], graph["revision"],
            graph["content_sha256"], {"type": "update_node_meaning", "node_id": node,
                                      "meaning": "锚点后人工编辑"}, "late-first-edit")
        monkeypatch.setattr(ActionGraphSourceReader, "collect", collect)
        synced = host.fresh_learning.sync_actions(**scope)
        final = host.facade.load_graph_revision(synced["logical_workflow_id"])
        assert synced["logical_workflow_id"] == first["logical_workflow_id"]
        assert len(final["source_refs"]["action_sources"]) == 2
        assert len({item["event_id"] for item in final["source_refs"]["action_sources"]}) == 2
        assert next(item for item in final["graph"]["nodes"] if item["node_id"] == node) == edited["graph"]["nodes"][0]
