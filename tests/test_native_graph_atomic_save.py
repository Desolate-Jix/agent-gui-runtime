"""原生图审核的单修订原子保存回归。"""
from copy import deepcopy
import pytest
from tests.test_formal_graph_exact_review import _runtime, _node, TASK, BATCH
from app.desktop_review.workspace import DesktopReviewError


def test_native_graph_atomic_save_commits_same_node_edits_once_and_reopens(tmp_path):
    store, _service, facade, original = _runtime(tmp_path)
    try:
        before = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
        source_before = _service.reviewer_call("fresh-graph-exact-token", "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"]
        node = _node(before, "state-a")
        saved = facade.apply_graph_edits(before["logical_workflow_id"], before["revision"], before["content_sha256"], [
            {"type": "update_node_meaning", "node_id": node["node_id"], "meaning": "人工核验含义"},
            {"type": "update_region_bbox", "node_id": node["node_id"], "region_id": "region-state-a", "bbox": [4, 5, 24, 13]},
            {"type": "update_node_recognition_text", "node_id": node["node_id"], "recognition_text": "人工识别", "source_screenshot_path": node["evidence"]["source_screenshot_path"], "source_screenshot_sha256": node["evidence"]["source_screenshot_sha256"], "bbox": [4, 5, 24, 13]},
        ], "native-atomic-save")
        assert saved["revision"] == before["revision"] + 1
        reopened = facade.load_graph_revision(saved["logical_workflow_id"], saved["revision"])
        assert reopened == saved
        assert source_before == _service.reviewer_call("fresh-graph-exact-token", "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"]
    finally:
        facade.close(); store.close()


def test_native_graph_atomic_save_rejects_later_bad_edit_without_partial_revision(tmp_path):
    store, _service, facade, _original = _runtime(tmp_path)
    try:
        before = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
        node = _node(before, "state-a")
        with pytest.raises(DesktopReviewError):
            facade.apply_graph_edits(before["logical_workflow_id"], before["revision"], before["content_sha256"], [
                {"type": "update_node_meaning", "node_id": node["node_id"], "meaning": "不会提交"},
                {"type": "update_region_bbox", "node_id": node["node_id"], "region_id": "region-state-a", "bbox": [999, 1, 2, 2]},
            ], "native-atomic-bad")
        assert facade.load_graph_revision(before["logical_workflow_id"], None) == before
    finally:
        facade.close(); store.close()


def test_atomic_save_idempotency_stale_and_crosssubject_do_not_write(tmp_path):
    store, _service, facade, _original = _runtime(tmp_path)
    try:
        before = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
        node_a, node_b = _node(before, "state-a"), _node(before, "state-b")
        ops = [{"type": "update_node_meaning", "node_id": node_a["node_id"], "meaning": "一次"}]
        saved = facade.apply_graph_edits(before["logical_workflow_id"], 1, before["content_sha256"], ops, "atomic-idempotent")
        assert facade.apply_graph_edits(before["logical_workflow_id"], 1, before["content_sha256"], ops, "atomic-idempotent") == saved
        for changed in (
            [{"type": "update_node_meaning", "node_id": node_a["node_id"], "meaning": "不同"}],
            [{"type": "update_node_meaning", "node_id": node_a["node_id"], "meaning": "甲"}, {"type": "update_node_meaning", "node_id": node_b["node_id"], "meaning": "乙"}],
            [{"type": "unknown", "node_id": node_a["node_id"]}],
        ):
            with pytest.raises(DesktopReviewError):
                facade.apply_graph_edits(before["logical_workflow_id"], 1, before["content_sha256"], changed, "atomic-idempotent" if changed[0].get("meaning") == "不同" else "atomic-invalid")
        for revision, digest in ((1, "0" * 64), (2, before["content_sha256"])):
            with pytest.raises(DesktopReviewError):
                facade.apply_graph_edits(before["logical_workflow_id"], revision, digest, ops, f"atomic-stale-{revision}")
        assert facade.load_graph_revision(before["logical_workflow_id"], None) == saved
    finally:
        facade.close(); store.close()


def test_atomic_save_retargets_and_updates_semantics_in_one_revision(tmp_path):
    store, _service, facade, _original = _runtime(tmp_path)
    try:
        before = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
        edge = before["graph"]["edges"][0]
        target = _node(before, "state-c")
        saved = facade.apply_graph_edits(before["logical_workflow_id"], 1, before["content_sha256"], [
            {"type": "update_edge_target", "edge_id": edge["edge_id"], "target_node_id": target["node_id"]},
            {"type": "update_edge_semantics", "edge_id": edge["edge_id"], "expected_result": "C 可见", "stop_condition": "C 缺失", "prerequisites": ["A 可见"], "relationship_kinds": {"rel-open": "打开 C"}},
        ], "atomic-edge")
        updated = saved["graph"]["edges"][0]
        assert updated["target_node_id"] == target["node_id"]
        assert updated["success_conditions"] == ["C 可见"]
        assert updated.get("target_semantics_status") != "stale_after_retarget"
        assert facade.load_graph_revision(saved["logical_workflow_id"], saved["revision"]) == saved
    finally:
        facade.close(); store.close()
