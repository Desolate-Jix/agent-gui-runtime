"""目录不物化所有项目，详情候选只在本次读取中复用。"""
from unittest.mock import patch
from copy import deepcopy
from app.desktop_review.workflow_project import WorkflowProjectService
from tests.test_formal_fresh_graph_source import _stage
from tests.test_formal_fresh_learning_observation import _owner
from tests.test_observed_interface_project import _complete


def test_summary_does_not_load_interface_details(tmp_path):
    host, connection, segment, _, args, staged = _stage(tmp_path)
    try:
        _complete(host, connection, segment, args, staged)
        with patch.object(host.facade, "list_interface_contents_for_reference", side_effect=AssertionError("details read")):
            items = host.facade.list_workflow_project_summaries()
        assert len(items) == 1
        assert items[0]["logical_workflow_id"] == staged["logical_workflow_id"]
        assert items[0]["detail_loaded"] is False
        assert "project_content_sha256" not in items[0]
    finally:
        host.close()


def test_duplicate_source_scope_does_not_hide_unique_interface(tmp_path):
    host, connection, segment, _, args, staged = _stage(tmp_path)
    try:
        completed = _complete(host, connection, segment, args, staged)
        source = host.facade.load_graph_revision(staged['logical_workflow_id'])
        node = deepcopy(source['graph']['nodes'][0])
        refs = deepcopy(source['source_refs'])
        refs['additional_sources'] = [deepcopy(refs)]
        WorkflowProjectService(host.facade)._project_observed_interface(node, refs, None, fixed=False)
        assert node['interface_reference']['interface_id'] == completed['interface_id']
    finally:
        host.close()


def test_many_nodes_scan_interface_candidates_once_per_task_and_refresh_next_read(tmp_path):
    host, connection, segment, _, args, staged = _stage(tmp_path)
    try:
        first = _complete(host, connection, segment, args, staged)
        second = host.fresh_learning.stage(**{**args, "idempotency_key": "second",
            "packet": _owner(tmp_path / "second").observe(target_window_handle=4242, target_process_id=9001)})
        _complete(host, connection, segment, args, second, "Second interface")
        original = host.facade.list_interface_contents_for_reference
        with patch.object(host.facade, "list_interface_contents_for_reference", wraps=original) as calls:
            view = host.facade.load_workflow_project(staged["logical_workflow_id"])
            assert calls.call_count == 1
        assert len(view["graph"]["nodes"]) == 2
        host.facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"],
                                          {"meaning": "Changed after read"}, "change-after-read")
        updated = host.facade.load_workflow_project(staged["logical_workflow_id"])
        assert any(n["display_name"] == "Changed after read" for n in updated["graph"]["nodes"])
    finally:
        host.close()
