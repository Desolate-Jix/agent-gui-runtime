"""同段图保留不同观察身份，并拒绝损坏或串段的父来源。"""

import pytest

from app.desktop_review.workspace import DesktopReviewError
from tests.test_formal_fresh_graph_source import _stage, REVIEWER
from tests.test_formal_fresh_learning_observation import _owner


def test_distinct_observation_keys_preserve_both_meanings_even_with_same_packet(tmp_path):
    host, _, _, _, args, first = _stage(tmp_path)
    try:
        second = host.fresh_learning.stage(**{**args, "idempotency_key": "another-interpretation", "meaning": "同一来源的新观察提议"})
        assert second["logical_workflow_id"] == first["logical_workflow_id"]
        current = host.facade.load_graph_revision(first["logical_workflow_id"])
        assert [node["display_name"] for node in current["graph"]["nodes"]] == [args["meaning"], "同一来源的新观察提议"]
        assert current["revision"] == 2 and current["graph"]["edges"] == []
        repeated = host.fresh_learning.stage(**{**args, "idempotency_key": "another-interpretation", "meaning": "同一来源的新观察提议"})
        assert repeated == second
    finally:
        host.close()


def test_foreign_segment_source_cannot_join_current_graph(tmp_path):
    host, connection, _, _, args, first = _stage(tmp_path)
    try:
        other = host._service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": connection["task_id"], "agent_name": "other-agent"})
        segment = host._service.agent_call(other["token"], "start_learning_segment", {
            "idempotency_key": "other-segment", "title": "Another segment"})
        foreign = host.fresh_learning.stage(**{**args, "connection_id": other["connection_id"],
            "segment_id": segment["segment_id"], "idempotency_key": "foreign-observation"})
        before = host.facade.load_graph_revision(first["logical_workflow_id"])
        with pytest.raises(DesktopReviewError):
            host.facade.append_fresh_graph_source(first["logical_workflow_id"], connection["task_id"], foreign["batch_id"])
        assert host.facade.load_graph_revision(first["logical_workflow_id"]) == before
    finally:
        host.close()


def test_appended_archive_corruption_cannot_be_hidden_by_base_source(tmp_path):
    host, _, _, _, args, first = _stage(tmp_path)
    try:
        packet = _owner(tmp_path / "second").observe(target_window_handle=4242, target_process_id=9001)
        second = host.fresh_learning.stage(**{**args, "idempotency_key": "second", "packet": packet})
        current = host.facade.load_graph_revision(first["logical_workflow_id"])
        record = tmp_path / "review/runtime_state/fresh-learning-v1/records" / (second["source"]["reference"]["source_id"] + ".json")
        original = record.read_bytes()
        try:
            record.write_bytes(b"{}")
            with pytest.raises(DesktopReviewError):
                host.facade.load_graph_revision(first["logical_workflow_id"])
        finally:
            record.write_bytes(original)
        assert host.facade.load_graph_revision(first["logical_workflow_id"]) == current
    finally:
        host.close()


def test_segment_graph_does_not_truncate_at_single_batch_screenshot_limit(tmp_path):
    host, _, _, _, args, first = _stage(tmp_path)
    try:
        for number in range(2, 34):
            result = host.fresh_learning.stage(**{**args, "idempotency_key": f"observation-{number}", "meaning": f"Observation {number}"})
            assert result["logical_workflow_id"] == first["logical_workflow_id"]
        current = host.facade.load_graph_revision(first["logical_workflow_id"])
        assert len(current["graph"]["nodes"]) == 33
        assert current["graph"]["nodes"][-1]["display_name"] == "Observation 33"
        assert len(current["source_refs"]["additional_sources"]) == 32
        assert current["graph"]["edges"] == []
    finally:
        host.close()


def test_removed_segment_member_cannot_be_appended_or_resolved(tmp_path, monkeypatch):
    host, connection, segment, _, args, first = _stage(tmp_path)
    try:
        def unavailable(*_args, **_kwargs):
            raise OSError("isolated append failure")
        with monkeypatch.context() as patch:
            patch.setattr(host.facade, "append_fresh_graph_source", unavailable)
            with pytest.raises(OSError):
                host.fresh_learning.stage(**{**args, "idempotency_key": "not-yet-appended", "meaning": "第二个观察"})
        current = host.fresh_learning.segments.get(connection_id=connection["connection_id"],
            task_id=connection["task_id"], segment_id=segment["segment_id"])
        second_batch = current["observations"][1]["batch_id"]
        def remove_member(state):
            saved = state["connections"][connection["connection_id"]]["learning_segments"][segment["segment_id"]]
            saved["observations"] = saved["observations"][:1]
        host.fresh_learning.segments.store.mutate(remove_member)
        before = host.facade.load_graph_revision(first["logical_workflow_id"])
        with pytest.raises(DesktopReviewError):
            host.facade.append_fresh_graph_source(first["logical_workflow_id"], connection["task_id"], second_batch)
        with pytest.raises(DesktopReviewError):
            host.facade.load_batch_graph_revision(connection["task_id"], second_batch)
        assert host.facade.load_graph_revision(first["logical_workflow_id"]) == before
    finally:
        host.close()


def test_shared_source_is_verified_once_per_history_read_not_cached_across_reads(tmp_path, monkeypatch):
    from app.desktop_review.graph_revision import GraphRevisionService

    host, _, _, _, args, first = _stage(tmp_path)
    try:
        host.fresh_learning.stage(**{**args, "idempotency_key": "second", "meaning": "第二个观察"})
        real_read = host.facade._fresh_source_for_batch
        reads = []
        def checked_read(task, batch, original):
            reads.append(batch)
            return real_read(task, batch, original)
        monkeypatch.setattr(host.facade, "_fresh_source_for_batch", checked_read)
        reader = GraphRevisionService(host.facade)
        with host.facade._guard:
            first_read = reader.load(first["logical_workflow_id"], None)
            assert len(first_read["graph"]["nodes"]) == 2
            assert len(reads) == len(set(reads)) == 2
            reads.clear()
            assert reader.load(first["logical_workflow_id"], None) == first_read
            assert len(reads) == len(set(reads)) == 2
    finally:
        host.close()


def test_bound_batch_identity_cannot_be_rewritten_as_another_source(tmp_path):
    host, connection, _, _, _, first = _stage(tmp_path)
    try:
        before = host.facade.load_graph_revision(first["logical_workflow_id"])
        def rewrite(state):
            state["batches"][first["batch_id"]]["title"] = "被改写的同名批次"
        host.fresh_learning.segments.store.mutate(rewrite)
        with pytest.raises(DesktopReviewError):
            host.facade.append_fresh_graph_source(first["logical_workflow_id"], connection["task_id"], first["batch_id"])
        assert host.facade.load_graph_revision(first["logical_workflow_id"]) == before
    finally:
        host.close()
