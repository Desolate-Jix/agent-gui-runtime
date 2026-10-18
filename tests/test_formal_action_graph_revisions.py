from __future__ import annotations

from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app.desktop_review.action_graph_source import ActionGraphSourceReader
from app.desktop_review.graph_revision import GraphRevisionService
from app.desktop_review.graph_review_pane import GraphReviewPane
from app.desktop_review.workspace import DesktopReviewError
from tests.test_formal_action_graph_projection import _action_rig
from tests.test_formal_graph_review_pane import _click_edge, _wait, qapp


def test_append_action_source_replays_exact_projection_and_is_idempotent(tmp_path):
    with _action_rig(tmp_path) as run:
        facade = run["host"].facade
        reader = ActionGraphSourceReader(facade)
        collected = reader.collect(
            connection_id=run["connection"]["connection_id"],
            task_id=run["connection"]["task_id"],
            segment_id=run["segment"]["segment_id"],
        )
        source = collected["sources"][0]
        initial = facade.load_graph_revision(run["first"]["logical_workflow_id"])

        appended = facade.append_learning_action_source(
            initial["logical_workflow_id"], source,
        )

        assert appended["revision"] == initial["revision"] + 1
        assert appended["change"]["action_append"] == source
        assert appended["source_refs"]["action_sources"] == [source]
        assert appended["source_refs"]["screenshots"] == initial["source_refs"]["screenshots"]
        assert appended["graph"]["workflow"]["node_ids"] == [
            item["node_id"] for item in appended["graph"]["nodes"]
        ]
        assert appended["graph"]["workflow"]["edge_ids"] == [
            item["edge_id"] for item in appended["graph"]["edges"]
        ]
        assert facade.append_learning_action_source(
            initial["logical_workflow_id"], source,
        ) == appended


def test_append_action_source_rejects_changed_parent_for_same_event(tmp_path):
    with _action_rig(tmp_path) as run:
        facade = run["host"].facade
        reader = ActionGraphSourceReader(facade)
        source = reader.collect(
            connection_id=run["connection"]["connection_id"],
            task_id=run["connection"]["task_id"],
            segment_id=run["segment"]["segment_id"],
        )["sources"][0]
        initial = facade.load_graph_revision(run["first"]["logical_workflow_id"])
        facade.append_learning_action_source(initial["logical_workflow_id"], source)
        changed = deepcopy(source)
        changed["event"]["terminal"]["outcome"] = "INDETERMINATE"
        assert changed["source_sha256"] == source["source_sha256"]

        with pytest.raises(DesktopReviewError):
            facade.append_learning_action_source(initial["logical_workflow_id"], changed)


def test_action_source_validation_memo_binds_full_source_and_fresh_scope(tmp_path):
    with _action_rig(tmp_path) as run:
        facade = run["host"].facade
        source = ActionGraphSourceReader(facade).collect(
            connection_id=run["connection"]["connection_id"],
            task_id=run["connection"]["task_id"],
            segment_id=run["segment"]["segment_id"],
        )["sources"][0]
        snapshot = facade.load_graph_revision(run["first"]["logical_workflow_id"])
        base_fresh = snapshot["source_refs"]["fresh_learning_source"]
        service = GraphRevisionService(facade)
        service._verified_action_source_reads = set()
        service._validate_action_source(source, base_fresh)

        changed_source = deepcopy(source)
        changed_source["event"]["terminal"]["outcome"] = "INDETERMINATE"
        assert changed_source["source_sha256"] == source["source_sha256"]
        with pytest.raises(DesktopReviewError):
            service._validate_action_source(changed_source, base_fresh)

        changed_base = deepcopy(base_fresh)
        changed_base["segment_id"] = "segment.other"
        with pytest.raises(DesktopReviewError):
            service._validate_action_source(source, changed_base)


def test_native_pane_loads_actual_action_edge_before_and_after_png(tmp_path, qapp):
    with _action_rig(tmp_path) as run:
        facade = run["host"].facade
        source = ActionGraphSourceReader(facade).collect(
            connection_id=run["connection"]["connection_id"],
            task_id=run["connection"]["task_id"],
            segment_id=run["segment"]["segment_id"],
        )["sources"][0]
        initial = facade.load_graph_revision(run["first"]["logical_workflow_id"])
        snapshot = facade.append_learning_action_source(
            initial["logical_workflow_id"], source,
        )
        edge = snapshot["graph"]["edges"][0]
        expected = {
            item["screenshot_id"]: (item["width"], item["height"])
            for item in source["screenshots"]
        }
        pane = GraphReviewPane(facade)
        pane.resize(1280, 760)
        pane.show()
        try:
            pane.load_graph(snapshot["logical_workflow_id"])
            _wait(qapp, lambda: not pane.is_busy and edge["edge_id"] in pane.graph_view._edge_items)
            _click_edge(pane, edge["edge_id"])
            _wait(qapp, lambda: not pane.is_busy and pane.before_canvas._pixmap_item is not None and pane.after_canvas._pixmap_item is not None)
            before = pane.before_canvas._pixmap_item.pixmap()
            after = pane.after_canvas._pixmap_item.pixmap()
            assert (before.width(), before.height()) == expected["action-png-" + source["event_source"]["before"]["screenshot_sha256"]]
            assert (after.width(), after.height()) == expected["action-png-" + source["event_source"]["after"]["screenshot_sha256"]]
        finally:
            _wait(qapp, lambda: not pane.is_busy)
            pane.close()
            _wait(qapp, lambda: not pane._jobs)


def test_action_validation_memo_does_not_trust_claimed_hash_or_foreign_scope(tmp_path):
    from app.desktop_review.graph_revision import GraphRevisionService

    with _action_rig(tmp_path) as run:
        facade = run["host"].facade
        source = ActionGraphSourceReader(facade).collect(
            connection_id=run["connection"]["connection_id"], task_id=run["connection"]["task_id"],
            segment_id=run["segment"]["segment_id"],
        )["sources"][0]
        graph = facade.load_graph_revision(run["first"]["logical_workflow_id"])
        base = graph["source_refs"]["fresh_learning_source"]
        service = GraphRevisionService(facade)
        service._verified_action_source_reads = set()
        service._validate_action_source(source, base)
        changed = deepcopy(source)
        changed["event"]["terminal"]["outcome"] = "INDETERMINATE"
        with pytest.raises(DesktopReviewError):
            service._validate_action_source(changed, base)
        with pytest.raises(DesktopReviewError):
            service._validate_action_source(source, {**base, "segment_id": "foreign-segment"})


def test_pane_accepts_shared_action_png_but_rejects_conflicting_ref(tmp_path, qapp):
    from tests.test_formal_action_graph_projection import _finish
    from tests.test_formal_fresh_graph_source import _stage
    from tests.test_formal_learning_segments import _perform_action

    host, connection, segment, _, _, first = _stage(tmp_path)
    try:
        for _ in range(2):
            _perform_action(tmp_path / "review", host.learning_segments, host.learning_segments.recorder,
                            host.learning_segments.capture_archive, connection, segment["segment_id"], sequence=1)
        _finish({"host": host, "connection": connection, "segment": segment})
        snapshot = host.facade.load_graph_revision(first["logical_workflow_id"])
        actions = snapshot["source_refs"]["action_sources"]
        assert len(actions) == 2 and actions[0]["screenshots"] == actions[1]["screenshots"]
        assert len(snapshot["graph"]["nodes"]) == 5 and len(snapshot["graph"]["edges"]) == 2
        node_id = snapshot["graph"]["edges"][1]["source_node_id"]
        evidence = host.facade.load_graph_node_evidence(snapshot["logical_workflow_id"], snapshot["revision"],
                                                      snapshot["content_sha256"], node_id)
        pane = GraphReviewPane(host.facade)
        try:
            pane._snapshot = snapshot
            assert pane._validated_evidence(evidence, node_id) == evidence
            actions[1]["screenshots"][0]["width"] += 1
            with pytest.raises(ValueError):
                pane._validated_evidence(evidence, node_id)
        finally:
            pane.close()
    finally:
        host.close()
