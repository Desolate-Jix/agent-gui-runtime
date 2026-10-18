"""新观察节点符合不可变审核 ID 约束；历史投影不随修复改写。"""
from copy import deepcopy

import pytest

from app.desktop_review.graph_revision import GraphRevisionService
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.workspace import DesktopReviewError
from app.learn.review_write_guard import validate_immutable_components
from tests.test_formal_fresh_graph_source import REVIEWER, _stage


def _append(host, args, key):
    result = host.fresh_learning.stage(**{**args, "idempotency_key": key})
    return host.facade.load_graph_revision(result["logical_workflow_id"])


def test_added_fresh_node_can_enter_exact_review_and_reopen_without_id_overflow(tmp_path):
    host, connection, segment, packet, args, result = _stage(tmp_path)
    try:
        first = host.facade.load_graph_revision(result["logical_workflow_id"])
        graph = _append(host, args, "second-source")
        validate_immutable_components(graph["graph"]["workflow"]["workflow_id"], graph["graph"]["nodes"])
        assert len({node["node_id"] for node in graph["graph"]["nodes"]}) == 2
        assert graph["graph"]["nodes"][0] == first["graph"]["nodes"][0]
        second = graph["graph"]["nodes"][1]
        source = graph["source_refs"]["additional_sources"][0]
        assert source["node_id_scheme"] == "sha256_v2"
        assert second["evidence"]["source_sha256"] == source["batch_sha256"]
        assert second["external_interface_id"] == "observed-screen"
        prepared = host.facade.prepare_graph_exact_review(
            graph["logical_workflow_id"], graph["revision"], graph["content_sha256"],
            {"kind": "web", "display_name": "Fresh fixture", "canonical_origin": "https://fresh.example"}, [])
        assert not any(subject["confirmed"] for subject in prepared["subjects"])
        assert host.facade.load_graph_revision(first["logical_workflow_id"], first["revision"]) == first
        assert _append(host, args, "second-source") == graph
    finally:
        host.close()
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        assert reopened.facade.load_graph_revision(graph["logical_workflow_id"]) == graph
    finally:
        reopened.close()


def test_unversioned_old_projection_replays_unchanged_while_new_append_is_compact(tmp_path, monkeypatch):
    host, connection, segment, packet, args, result = _stage(tmp_path)
    original_ref = GraphRevisionService._fresh_source_ref

    def old_ref(self, *values):
        result = original_ref(self, *values)
        result.pop("node_id_scheme", None)
        return result

    try:
        # 仅模拟旧生产者的来源标记缺席，旧算法仍由实际重放器执行。
        with monkeypatch.context() as old:
            old.setattr(GraphRevisionService, "_fresh_source_ref", old_ref)
            legacy = _append(host, args, "legacy-second")
        old_node = legacy["graph"]["nodes"][1]
        assert len(old_node["node_id"]) > 128
        assert "node_id_scheme" not in legacy["source_refs"]["additional_sources"][0]
        assert host.facade.load_graph_revision(legacy["logical_workflow_id"]) == legacy
        mixed = _append(host, args, "new-third")
        assert mixed["graph"]["nodes"][:2] == legacy["graph"]["nodes"]
        assert len(mixed["graph"]["nodes"][2]["node_id"]) <= 128
        assert host.facade.load_graph_revision(legacy["logical_workflow_id"], legacy["revision"]) == legacy
        # 保留旧图不意味着它已可发布，既有写入约束不能被放宽。
        with pytest.raises(ValueError, match="1-128"):
            validate_immutable_components(mixed["graph"]["workflow"]["workflow_id"], mixed["graph"]["nodes"])
    finally:
        host.close()
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        assert reopened.facade.load_graph_revision(legacy["logical_workflow_id"], legacy["revision"]) == legacy
        assert reopened.facade.load_graph_revision(mixed["logical_workflow_id"]) == mixed
    finally:
        reopened.close()


@pytest.mark.parametrize("scheme", [None, "legacy_v1", "unknown", True])
def test_explicit_unknown_node_id_scheme_is_rejected_before_replay(tmp_path, scheme):
    host, connection, segment, packet, args, result = _stage(tmp_path)
    try:
        graph = _append(host, args, "second")
        refs = deepcopy(graph["source_refs"]["additional_sources"][0])
        refs["node_id_scheme"] = scheme
        with pytest.raises(DesktopReviewError, match="node_id_scheme"):
            GraphRevisionService(host.facade)._validate_source_ref(refs, allow_additional=False)
    finally:
        host.close()


def test_base_source_cannot_claim_supplemental_id_scheme(tmp_path):
    host, connection, segment, packet, args, result = _stage(tmp_path)
    try:
        graph = host.facade.load_graph_revision(result["logical_workflow_id"])
        refs = deepcopy(graph["source_refs"])
        refs["node_id_scheme"] = "sha256_v2"
        with pytest.raises(DesktopReviewError, match="node_id_scheme"):
            GraphRevisionService(host.facade)._validate_source_ref(refs, allow_additional=True)
    finally:
        host.close()


def test_removing_scheme_cannot_reinterpret_existing_compact_child_as_legacy(tmp_path):
    host, connection, segment, packet, args, result = _stage(tmp_path)
    try:
        parent = host.facade.load_graph_revision(result["logical_workflow_id"])
        child = _append(host, args, "second")
        mutated = deepcopy(child)
        mutated["source_refs"]["additional_sources"][0].pop("node_id_scheme")
        mutated["change"]["source_append"].pop("node_id_scheme")
        # 即使来源列表和 change 同步改动，真实重放仍不能把紧凑 ID 当旧 ID。
        with pytest.raises(DesktopReviewError, match="重放结果不一致"):
            GraphRevisionService(host.facade)._validate_source_append(parent, mutated)
        assert host.facade.load_graph_revision(child["logical_workflow_id"]) == child
    finally:
        host.close()
