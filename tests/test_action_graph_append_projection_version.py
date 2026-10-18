"""动作追加的无效来源投影版本兼容既有只读图历史。"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib

import pytest

from app.agent.live_controller import LiveControllerDecision
from app.desktop_review.action_graph_source import ActionGraphSourceReader, project_action_source
from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.graph_revision import GraphRevisionService
from app.desktop_review.workspace import DesktopReviewError
from tests.test_fresh_scroll_dispatch import _scroll_runtime


@contextmanager
def _real_unknown_scroll_source(root, monkeypatch):
    with _scroll_runtime(root) as (
        host, _owner, runtime, _claims, native_input, _session, scope, intent,
    ):
        original_scroll = native_input.scroll_window

        def lose_result(**kwargs):
            original_scroll(**kwargs)
            raise OSError("synthetic wheel result loss")

        monkeypatch.setattr(native_input, "scroll_window", lose_result)
        actual_sync = host.fresh_learning.sync_actions
        monkeypatch.setattr(
            host.fresh_learning, "sync_actions",
            lambda **_scope: {"status": "synchronized"},
        )
        claim = runtime.request_grounded_confirmation(
            intent.to_dict(), target_process_id=9001,
        )
        assert not isinstance(claim, LiveControllerDecision), claim
        confirmation_id = claim.grounded_confirmation.confirmation_id
        runtime.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id, decision="approved",
        )
        receipt = runtime.consume_grounded_confirmation(
            confirmation_id=confirmation_id,
        )
        assert not isinstance(receipt, LiveControllerDecision), receipt
        assert receipt.outcome == "EXECUTION_UNKNOWN"
        assert receipt.evidence.scroll_verification["after"] is None
        assert len(native_input.calls) == 1
        monkeypatch.setattr(host.fresh_learning, "sync_actions", actual_sync)

        collected = ActionGraphSourceReader(host.facade).collect(**scope)
        assert collected["pending_events"] == []
        assert len(collected["sources"]) == 1
        source = collected["sources"][0]
        assert source["event_source"]["after_observation_present"] is False
        projected = project_action_source(source)
        assert len(projected["nodes"]) == 1
        assert projected["edges"] == []
        assert projected["invalid_sources"][0]["kind"] == "missing_after_observation"

        reference = runtime._binding.source.reference()
        parent = host.facade.create_graph_revision(
            scope["task_id"], reference["batch_id"], 0,
        )
        assert parent["revision"] == 1
        yield host, scope, source, projected, parent, actual_sync


def _action_child(service, parent, source, projected, *, version):
    refs = deepcopy(parent["source_refs"])
    refs.setdefault("action_sources", []).append(deepcopy(source))
    graph = deepcopy(parent["graph"])
    graph["nodes"].extend(deepcopy(projected["nodes"]))
    graph["edges"].extend(deepcopy(projected["edges"]))
    if version == 1:
        graph["invalid_sources"].extend(deepcopy(projected["invalid_sources"]))
    graph["workflow"]["node_ids"].extend(item["node_id"] for item in projected["nodes"])
    graph["workflow"]["edge_ids"].extend(item["edge_id"] for item in projected["edges"])
    request_sha = hashlib.sha256(canonical_json_bytes({
        "logical_workflow_id": parent["logical_workflow_id"],
        "parent_sha256": parent["content_sha256"], "source": source,
    })).hexdigest()
    return service._snapshot(
        logical_id=parent["logical_workflow_id"], revision=parent["revision"] + 1,
        parent_sha256=parent["content_sha256"], source_refs=refs, graph=graph,
        idempotency_key="legacy-missing-after", request_sha256=request_sha,
        action_append=source, action_invalid_sources_version=version,
    )


def test_old_unversioned_real_missing_after_append_reopens_without_edge(
    tmp_path, monkeypatch,
):
    with _real_unknown_scroll_source(tmp_path, monkeypatch) as (
        host, _scope, source, projected, parent, _sync,
    ):
        service = GraphRevisionService(host.facade)
        child = _action_child(service, parent, source, projected, version=None)
        service._write_committed(child)

        loaded = host.facade.load_graph_revision(parent["logical_workflow_id"])
        assert "action_invalid_sources_version" not in loaded["change"]
        assert loaded["graph"]["edges"] == []
        assert loaded["graph"]["invalid_sources"] == []
        action_nodes = [node for node in loaded["graph"]["nodes"]
                        if node.get("surface_type") == "recorded_action_observation"]
        assert len(action_nodes) == 1
        assert action_nodes[0]["blockers"] == projected["invalid_sources"]


def test_new_real_missing_after_append_versions_invalid_and_rejects_damage(
    tmp_path, monkeypatch,
):
    with _real_unknown_scroll_source(tmp_path, monkeypatch) as (
        host, scope, _source, projected, parent, sync,
    ):
        synchronized = sync(**scope)
        loaded = host.facade.load_graph_revision(synchronized["logical_workflow_id"])
        assert loaded["change"]["action_invalid_sources_version"] == 1
        assert loaded["graph"]["invalid_sources"] == projected["invalid_sources"]

        service = GraphRevisionService(host.facade)
        missing_invalid = deepcopy(loaded)
        missing_invalid["graph"]["invalid_sources"] = []
        missing_invalid["content_sha256"] = service._content_sha(missing_invalid)
        with pytest.raises(DesktopReviewError):
            service._validate_action_append(parent, missing_invalid)

        for invalid_version in (None, True, 2):
            unknown = deepcopy(loaded)
            unknown["change"]["action_invalid_sources_version"] = invalid_version
            unknown["content_sha256"] = service._content_sha(unknown)
            with pytest.raises(DesktopReviewError, match="版本不受支持"):
                service._validate_snapshot(unknown)
