"""人工保存工作区后，学习同步仍复用原图，不能覆盖修订或伪造跳转。"""

from copy import deepcopy

import pytest

from app.desktop_review.workspace import DesktopReviewError
from app.desktop_review.host import DesktopReviewHost
from tests.test_formal_fresh_graph_source import REVIEWER, _stage


@pytest.mark.parametrize("operation", ["retry", "append", "sync"])
def test_learning_sync_after_manual_workspace_save_preserves_graph(tmp_path, operation):
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    try:
        facade = host.facade
        task, batch = connection["task_id"], staged["batch_id"]
        loaded = facade.load_batch(task, batch)
        changed = deepcopy(loaded["batch"])
        changed["interfaces"][0]["meaning"] = "\u4eba\u5de5\u4fdd\u5b58\u7684\u754c\u9762"
        saved = facade.save_revision(task, batch, loaded["revision"], changed)
        graph = facade.load_graph_revision(staged["logical_workflow_id"])
        node = graph["graph"]["nodes"][0]
        edited = facade.apply_graph_edit(graph["logical_workflow_id"], graph["revision"],
            graph["content_sha256"], {"type": "update_node_meaning", "node_id": node["node_id"],
            "meaning": "\u56fe\u4e2d\u72ec\u7acb\u4fee\u6b63"}, "manual-graph-edit")
        if operation == "sync":
            result = host.fresh_learning.sync_actions(connection_id=connection["connection_id"],
                task_id=task, segment_id=segment["segment_id"])
            assert result["status"] == "synchronized"
        else:
            result = host.fresh_learning.stage(**{**args,
                **({"idempotency_key": "another-screen"} if operation == "append" else {})})
        actual = facade.load_graph_revision(result["logical_workflow_id"])
        assert result["logical_workflow_id"] == staged["logical_workflow_id"]
        assert actual["graph"]["nodes"][0] == edited["graph"]["nodes"][0]
        assert actual["graph"]["edges"] == []
        assert len(actual["graph"]["nodes"]) == (2 if operation == "append" else 1)
        assert facade.load_batch(task, batch) == saved
        assert facade.load_graph_revision(graph["logical_workflow_id"], graph["revision"]) == graph
        if operation != "append":
            assert actual == edited
        with pytest.raises(DesktopReviewError, match="stale_revision"):
            facade.create_graph_revision(task, batch, 0)
    finally:
        host.close()
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        assert reopened.facade.load_graph_revision(actual["logical_workflow_id"]) == actual
        assert reopened.facade.load_batch(task, batch) == saved
    finally:
        reopened.close()
