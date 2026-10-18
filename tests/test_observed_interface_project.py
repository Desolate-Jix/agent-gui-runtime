from __future__ import annotations
from copy import deepcopy
from pathlib import Path

import pytest
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.observed_interface_learning import submit_observed_interface_learning
from app.desktop_review.workflow_project import WorkflowProjectService
from tests.test_formal_fresh_graph_source import _stage


def _complete(host, connection, segment, args, result, meaning="完成观察"):
    batch_id = result["batch_id"]
    current = host.facade.import_interface_content(args["task_id"], batch_id, "observed-screen")
    return submit_observed_interface_learning(
        host.facade, connection_id=connection["connection_id"], task_id=args["task_id"],
        segment_id=segment["segment_id"], batch_id=batch_id,
        expected_revision=current["revision"], expected_sha256=current["content_sha256"],
        meaning=meaning, recognition_text="整页 OCR", regions=[{
            "bbox": [2, 3, 20, 12], "name": "按钮", "kind": "button",
            "meaning": "可观察控件", "recognition_text": "确定",
        }], idempotency_key="complete-observed")


def test_completed_observed_interface_projects_into_same_raw_node_without_duplication(tmp_path: Path):
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    try:
        raw = host.facade.load_graph_revision(result["logical_workflow_id"])
        raw_node = raw["graph"]["nodes"][0]
        raw_png = host.facade.load_graph_node_evidence(raw["logical_workflow_id"], raw["revision"], raw["content_sha256"], raw_node["node_id"])["screenshot"]["png_bytes"]
        completed = _complete(host, connection, segment, args, result)
        view = host.facade.load_workflow_project(result["logical_workflow_id"])
        node = view["graph"]["nodes"][0]
        assert len(view["graph"]["nodes"]) == 1 and node["node_id"] == raw_node["node_id"]
        assert node["display_name"] == "完成观察" and node["recognition_text"] == "整页 OCR"
        assert node["interface_reference"]["content_sha256"] == completed["content_sha256"]
        assert node["evidence"] == raw_node["evidence"]
        assert node["action_candidates"] == [] and node["artifact_is_authorization"] is False
        assert host.facade.load_graph_node_evidence(raw["logical_workflow_id"], raw["revision"], raw["content_sha256"], raw_node["node_id"])["screenshot"]["png_bytes"] == raw_png
    finally:
        host.close()


def test_current_view_tracks_latest_edit_but_fixed_memory_snapshot_stays_pinned(tmp_path: Path):
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    try:
        _complete(host, connection, segment, args, result, "首版观察")
        dynamic = host.facade.load_workflow_project(result["logical_workflow_id"])
        fixed = host.facade.get_workflow_project_memory(args["task_id"], result["logical_workflow_id"])
        pinned = fixed["snapshot_id"]
        content = host.facade.load_interface_content(dynamic["graph"]["nodes"][0]["interface_reference"]["interface_id"])
        host.facade.save_interface_content(content["interface_id"], content["revision"], content["content_sha256"], {"meaning": "后续独立修改"}, "later-edit")
        current = host.facade.load_workflow_project(result["logical_workflow_id"])
        historical = WorkflowProjectService(host.facade).load_snapshot(pinned)
        assert current["graph"]["nodes"][0]["display_name"] == "后续独立修改"
        assert historical["graph"]["nodes"][0]["display_name"] == "首版观察"
        assert historical["graph"]["nodes"][0]["node_id"] == current["graph"]["nodes"][0]["node_id"]
    finally:
        host.close()


def test_project_edge_save_reopen_uses_linked_node_and_wrong_candidate_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    try:
        _complete(host, connection, segment, args, result)
        service = WorkflowProjectService(host.facade)
        current = service.load(result["logical_workflow_id"])
        node_id = current["graph"]["nodes"][0]["node_id"]
        # 错误 task/source 候选不得自动关联。
        original = host.facade.list_interface_contents_for_reference
        def foreign(*a, **k):
            values = deepcopy(original(*a, **k))
            for value in values:
                value["source"]["task_id"] = "foreign-task"
            return values
        monkeypatch.setattr(host.facade, "list_interface_contents_for_reference", foreign)
        raw_view = service._build_view(host.facade.load_graph_revision(result["logical_workflow_id"]), None, None, fixed=False)
        assert "interface_reference" not in raw_view["graph"]["nodes"][0]
        monkeypatch.setattr(host.facade, "list_interface_contents_for_reference", original)
        edge = {"edge_id": "edge-editorial", "source_node_id": node_id, "target_node_id": node_id,
                "action_type": "observe", "target_region_id": None, "expected_result": "仍在当前界面", "condition": "可见"}
        saved = service.save(result["logical_workflow_id"], current["content_sha256"], {"edges": [edge]}, "edge-save")
        reopened = service.load(result["logical_workflow_id"])
        assert reopened["graph"]["edges"][0]["expected_result"] == "仍在当前界面"
        assert reopened["graph"]["nodes"][0]["node_id"] == node_id
        assert reopened["artifact_is_authorization"] is False and reopened["execute_binding_enabled"] is False
    finally:
        host.close()



def test_unpinned_old_snapshot_stays_raw_after_later_interface_completion(tmp_path: Path):
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    try:
        before = host.facade.get_workflow_project_memory(args["task_id"], result["logical_workflow_id"])
        assert "interface_reference" not in before["graph"]["nodes"][0]
        _complete(host, connection, segment, args, result, "完成后界面")
        current = host.facade.load_workflow_project(result["logical_workflow_id"])
        historical = host.facade.get_workflow_project_memory(args["task_id"], result["logical_workflow_id"], before["snapshot_id"])
        assert current["graph"]["nodes"][0]["display_name"] == "完成后界面"
        assert "interface_reference" not in historical["graph"]["nodes"][0]
        assert historical["graph"]["nodes"][0]["display_name"] != "完成后界面"
    finally:
        host.close()


def test_additional_sources_project_distinct_completed_capture_without_merging_nodes(tmp_path: Path):
    from tests.test_formal_fresh_learning_observation import _owner
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    try:
        second_packet = _owner(tmp_path / "second-capture").observe(target_window_handle=4242, target_process_id=9001)
        second_args = {**args, "idempotency_key": "second-screen", "title": "Second screen", "meaning": "第二观察" , "packet": second_packet}
        second = host.fresh_learning.stage(**{**second_args, "connection_id": connection["connection_id"], "segment_id": segment["segment_id"]})
        raw = host.facade.load_graph_revision(result["logical_workflow_id"])
        assert raw["revision"] >= 2 and len(raw["graph"]["nodes"]) == 2
        second_current = host.facade.import_interface_content(args["task_id"], second["batch_id"], "observed-screen")
        submit_observed_interface_learning(host.facade, connection_id=connection["connection_id"], task_id=args["task_id"], segment_id=segment["segment_id"], batch_id=second["batch_id"], expected_revision=second_current["revision"], expected_sha256=second_current["content_sha256"], meaning="第二完成", recognition_text="第二 OCR", regions=[{"bbox": [0, 0, 1, 1], "name": "第二框", "kind": "control", "meaning": "第二含义"}], idempotency_key="complete-second")
        view = host.facade.load_workflow_project(result["logical_workflow_id"])
        assert len(view["graph"]["nodes"]) == 2
        assert sum(node.get("display_name") == "第二完成" for node in view["graph"]["nodes"]) == 1
        assert len({node["node_id"] for node in view["graph"]["nodes"]}) == 2
    finally:
        host.close()


def test_corrupt_linked_interface_evidence_surfaces_in_current_view(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    try:
        _complete(host, connection, segment, args, result)
        original = host.facade.load_interface_content_evidence
        def corrupt(*_args, **_kwargs):
            raise ValueError("synthetic linked evidence corruption")
        monkeypatch.setattr(host.facade, "load_interface_content_evidence", corrupt)
        with pytest.raises(Exception, match="synthetic linked evidence corruption"):
            host.facade.load_workflow_project(result["logical_workflow_id"])
        monkeypatch.setattr(host.facade, "load_interface_content_evidence", original)
    finally:
        host.close()


def test_completed_link_survives_real_host_store_close_and_reopen(tmp_path: Path):
    from app.desktop_review.host import DesktopReviewHost
    host, connection, segment, _packet, args, result = _stage(tmp_path)
    _complete(host, connection, segment, args, result, "可重开界面")
    host.close()
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", "fresh-graph-reviewer")
    try:
        view = reopened.facade.load_workflow_project(result["logical_workflow_id"])
        assert view["graph"]["nodes"][0]["display_name"] == "可重开界面"
        assert len(view["graph"]["nodes"]) == 1
    finally:
        reopened.close()
