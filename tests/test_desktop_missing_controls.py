from __future__ import annotations

import copy
import hashlib
import json

import pytest

from app.desktop_review.external_mapping import ExternalMappingError, assert_source_identity
from app.desktop_review.workspace import DesktopReviewError
from test_agent_link_flow_candidates import flow_batch


def test_identity_allows_only_tail_region_additions_when_explicit():
    original = flow_batch()
    edited = copy.deepcopy(original)
    edited["interfaces"][0]["regions"].append({
        "region_id": "missing-control-1", "bbox": [1.0, 2.0, 10.0, 8.0],
        "name": "遗漏按钮", "label": None, "type": None, "kind": None,
        "meaning": "尚待人工审核的按钮含义",
    })
    with pytest.raises(ExternalMappingError):
        assert_source_identity(original, edited)
    assert_source_identity(original, edited, allow_region_additions=True)


def test_identity_rejects_region_reorder_even_when_additions_allowed():
    original = flow_batch()
    edited = copy.deepcopy(original)
    edited["interfaces"][0]["regions"].append({
        "region_id": "tail", "bbox": [1.0, 2.0, 10.0, 8.0], "name": "尾部", "meaning": "尾部",
    })
    edited["interfaces"][0]["regions"][:] = edited["interfaces"][0]["regions"][::-1]
    with pytest.raises(ExternalMappingError):
        assert_source_identity(original, edited, allow_region_additions=True)


def test_submit_compare_adopt_reopen_save_and_next_feedback_keeps_added_region(tmp_path):
    from test_desktop_flow_candidates import _setup
    from test_agent_link_flow_candidates import REVIEWER_TOKEN
    _, root, store, service, grant, facade, _ = _setup(tmp_path)
    try:
        view = facade.request_relearn("task-flow", "flow-batch", 1, 0,
            {"interface_ids": ["i1", "i2"], "relationship_ids": ["rel-12"]}, "新增遗漏控件", "feedback")
        issue = view["issues"][0]
        receipt = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "idempotency_key": "missing-add", "batch_id": "flow-batch",
            "issue_id": issue["issue_id"], "baseline_revision": 1,
            "review_baseline_sha256": issue["review_baseline_sha256"], "scope": issue["scope"],
            "changes": [{"change_type": "regions_add", "interface_id": "i1", "regions": [{
                "region_id": "missing-control-1", "bbox": [1.0, 2.0, 10.0, 8.0],
                "name": "遗漏按钮", "meaning": "尚待人工审核的按钮含义"}]}],
        })
        comparison = facade.compare_relearn_candidate("task-flow", "flow-batch", 1, receipt["candidate_id"])
        assert comparison["status"] == "current"
        assert comparison["diffs"][0]["baseline"] is comparison["diffs"][0]["current"] is None
        adopted = facade.adopt_relearn_candidate("task-flow", "flow-batch", 1, receipt["candidate_id"],
            comparison["candidate_sha256"], comparison["review_baseline_sha256"], "adopt-missing")
        for mutation in ("add", "delete", "reorder"):
            invalid = copy.deepcopy(adopted["snapshot"]["batch"])
            regions = invalid["interfaces"][0]["regions"]
            if mutation == "add":
                regions.append({"region_id": "ordinary-add", "bbox": [1.0, 2.0, 5.0, 5.0], "name": "禁止", "meaning": "禁止"})
            elif mutation == "delete":
                regions.pop()
            else:
                regions[:] = regions[::-1]
            with pytest.raises(DesktopReviewError):
                facade.save_revision("task-flow", "flow-batch", 2, invalid)
            assert facade.load_batch("task-flow", "flow-batch") == adopted["snapshot"]
        saved = facade.save_revision("task-flow", "flow-batch", 2, copy.deepcopy(adopted["snapshot"]["batch"]))
        facade.close(); store.close()
        from app.agent_link import AgentLinkService, AgentLinkStore
        from app.desktop_review.workspace import NativeReviewFacade
        reopened_store = AgentLinkStore(tmp_path / "inbox.json")
        reopened_service = AgentLinkService(reopened_store, REVIEWER_TOKEN)
        reopened = NativeReviewFacade(reopened_service, REVIEWER_TOKEN, root)
        try:
            assert reopened.load_batch("task-flow", "flow-batch")["batch"] == saved["batch"]
            next_view = reopened.request_relearn("task-flow", "flow-batch", 3, 1,
                {"interface_ids": ["i1"], "relationship_ids": []}, "继续编辑新增控件", "next")
            assert next_view["issues"][-1]["review_baseline"]["batch"]["interfaces"][0]["regions"][-1]["region_id"] == "missing-control-1"
            next_issue = next_view["issues"][-1]
            followup = reopened_service.agent_call(grant["token"], "submit_candidate", {
                "contract_version": "agent_link_v1", "idempotency_key": "modify-added", "batch_id": "flow-batch",
                "issue_id": next_issue["issue_id"], "baseline_revision": 2,
                "review_baseline_sha256": next_issue["review_baseline_sha256"], "scope": next_issue["scope"],
                "changes": [{"change_type": "semantic", "target_type": "region", "target_id": "missing-control-1", "meaning": "下一轮人工修改"}],
            })
            followup_compare = reopened.compare_relearn_candidate("task-flow", "flow-batch", 3, followup["candidate_id"])
            assert followup_compare["status"] == "current"
        finally:
            reopened.close(); reopened_store.close()
    finally:
        facade.close(); store.close()


def test_chain_rejects_added_region_child_without_adoption_origin(tmp_path):
    from test_desktop_flow_candidates import _setup
    from test_agent_link_flow_candidates import REVIEWER_TOKEN
    _, root, store, service, grant, facade, _ = _setup(tmp_path)
    try:
        view = facade.request_relearn("task-flow", "flow-batch", 1, 0,
            {"interface_ids": ["i1"], "relationship_ids": []}, "新增", "origin")
        issue = view["issues"][-1]
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "idempotency_key": "origin-add", "batch_id": "flow-batch",
            "issue_id": issue["issue_id"], "baseline_revision": 1, "review_baseline_sha256": issue["review_baseline_sha256"],
            "scope": issue["scope"], "changes": [{"change_type": "regions_add", "interface_id": "i1", "regions": [{
                "region_id": "origin-only", "bbox": [1.0, 2.0, 5.0, 5.0], "name": "新增", "meaning": "新增"}]}],
        })
        comparison = facade.compare_relearn_candidate("task-flow", "flow-batch", 1, candidate["candidate_id"])
        facade.adopt_relearn_candidate("task-flow", "flow-batch", 1, candidate["candidate_id"], comparison["candidate_sha256"], comparison["review_baseline_sha256"], "origin-adopt")
        current_path = facade._workspace_dir("task-flow", "flow-batch") / "current.json"
        manifest = json.loads(current_path.read_text(encoding="utf-8"))
        snapshot_path = facade._artifact_root / manifest["workspace_path"]
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        payload["relearn_adoption"] = None
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        snapshot_path.write_bytes(encoded)
        manifest["workspace_sha256"] = hashlib.sha256(encoded).hexdigest()
        current_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        facade.close(); store.close()
        from app.agent_link import AgentLinkService, AgentLinkStore
        from app.desktop_review.workspace import NativeReviewFacade
        reopened_store = AgentLinkStore(tmp_path / "inbox.json")
        reopened = NativeReviewFacade(AgentLinkService(reopened_store, REVIEWER_TOKEN), REVIEWER_TOKEN, root)
        try:
            with pytest.raises(DesktopReviewError):
                reopened.load_batch("task-flow", "flow-batch")
        finally:
            reopened.close(); reopened_store.close()
    finally:
        facade.close(); store.close()


def test_tampered_origin_is_rejected_before_persistence_without_source_or_current_mutation(tmp_path, monkeypatch):
    from test_desktop_flow_candidates import _setup
    _, _, store, service, grant, facade, saved = _setup(tmp_path)
    try:
        source_before = service.reviewer_call("reviewer-secret-value-123", "get_batch", {
            "task_id": "task-flow", "batch_id": "flow-batch"})["batch"]
        png_before = source_before["screenshots"][0]["png_base64"]
        view = facade.request_relearn("task-flow", "flow-batch", 1, 0,
            {"interface_ids": ["i1"], "relationship_ids": []}, "来源篡改", "tamper-feedback")
        issue = view["issues"][-1]
        candidate = service.agent_call(grant["token"], "submit_candidate", {
            "contract_version": "agent_link_v1", "idempotency_key": "tamper-add", "batch_id": "flow-batch",
            "issue_id": issue["issue_id"], "baseline_revision": 1, "review_baseline_sha256": issue["review_baseline_sha256"],
            "scope": issue["scope"], "changes": [{"change_type": "regions_add", "interface_id": "i1", "regions": [{
                "region_id": "tamper-control", "bbox": [1.0, 2.0, 5.0, 5.0], "name": "新增", "meaning": "新增"}]}],
        })
        comparison = facade.compare_relearn_candidate("task-flow", "flow-batch", 1, candidate["candidate_id"])
        def artifact_hashes():
            # 当前进程独占的 owner 锁不是审核产物，不能通过第二个句柄读取。
            return {path.relative_to(facade._artifact_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in facade._artifact_root.rglob("*")
                    if path.is_file() and path != facade._workspace_root / ".owner.lock"}

        before_files = artifact_hashes()
        assert any("/revisions/" in path and path.endswith("workspace.json") for path in before_files)
        assert any(path.endswith(".png") for path in before_files)
        original_save = facade._save_revision_locked
        def tampered_save(*args, **kwargs):
            kwargs["relearn_adoption"]["candidate_sha256"] = "0" * 64
            return original_save(*args, **kwargs)
        monkeypatch.setattr(facade, "_save_revision_locked", tampered_save)
        with pytest.raises(DesktopReviewError):
            facade.adopt_relearn_candidate("task-flow", "flow-batch", 1, candidate["candidate_id"],
                comparison["candidate_sha256"], comparison["review_baseline_sha256"], "tamper-origin")
        assert facade.load_batch("task-flow", "flow-batch") == saved
        assert artifact_hashes() == before_files
        source_after = service.reviewer_call("reviewer-secret-value-123", "get_batch", {
            "task_id": "task-flow", "batch_id": "flow-batch"})["batch"]
        assert source_after == source_before
        assert source_after["screenshots"][0]["png_base64"] == png_before
    finally:
        facade.close(); store.close()
