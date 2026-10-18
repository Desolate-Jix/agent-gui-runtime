from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
from io import BytesIO
from pathlib import Path

from PIL import Image
import pytest

from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review import graph_revision
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade


def _png() -> bytes:
    image = Image.new("RGB", (96, 64), "white")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def _batch() -> dict:
    png = _png()
    return {
        "contract_version": "agent_link_v1",
        "idempotency_key": "graph-source-ownership-batch",
        "batch_id": "graph-source-ownership-batch",
        "title": "图草稿来源所有权",
        "learning_outcome": "completed",
        "screenshots": [{
            "screenshot_id": "capture-a",
            "png_base64": base64.b64encode(png).decode("ascii"),
        }],
        "interfaces": [
            {
                "interface_id": "interface-a",
                "screenshot_id": "capture-a",
                "meaning": "A",
                "regions": [{
                    "region_id": "region-a",
                    "bbox": [2.0, 3.0, 20.0, 12.0],
                    "name": "打开",
                    "meaning": "打开详情",
                }],
            },
            {"interface_id": "interface-b", "screenshot_id": "capture-a", "meaning": "B", "regions": []},
            {"interface_id": "interface-c", "screenshot_id": "capture-a", "meaning": "C", "regions": []},
        ],
        "relationships": [{
            "relationship_id": "relation-a-b",
            "from_interface_id": "interface-a",
            "to_interface_id": "interface-b",
            "kind": "到 B",
        }],
        "steps": [{
            "step_id": "step-a-b",
            "action_type": "open_detail",
            "target_region_id": "region-a",
            "start_state": "interface-a",
            "arrival_state": "interface-b",
            "prerequisites": [],
            "expected_result": "B 可见",
            "stop_condition": "停止",
        }],
        "issues": [],
    }


def _facade(tmp_path: Path, batch: dict | None = None) -> tuple[NativeReviewFacade, AgentLinkStore, AgentLinkService, Path]:
    token = "graph-source-ownership-reviewer"
    root = tmp_path / "review-artifacts"
    store = AgentLinkStore(tmp_path / "graph-source-ownership-inbox.json")
    service = AgentLinkService(store, token)
    grant = service.reviewer_call(token, "create_connection", {
        "task_id": "graph-source-ownership-task", "agent_name": "graph-source-owner",
    })
    service.agent_call(grant["token"], "submit_batch", batch or _batch())
    return NativeReviewFacade(service, token, root), store, service, root


def _node(snapshot: dict, external_id: str) -> dict:
    return next(item for item in snapshot["graph"]["nodes"] if item["external_interface_id"] == external_id)


def _duplicate_png_batch() -> dict:
    batch = _batch()
    batch["idempotency_key"] = "graph-source-ownership-duplicate-png"
    batch["batch_id"] = "graph-source-ownership-duplicate-png"
    batch["screenshots"].append({
        "screenshot_id": "capture-b", "png_base64": batch["screenshots"][0]["png_base64"],
    })
    batch["interfaces"][1] = {
        "interface_id": "interface-b", "screenshot_id": "capture-b", "meaning": "B",
        "regions": [{"region_id": "region-b", "bbox": [1.0, 1.0, 10.0, 10.0], "name": "B", "meaning": "B 区域"}],
    }
    return batch


def test_graph_draft_create_edit_reopen_preserves_original_source(tmp_path: Path) -> None:
    facade, store, service, root = _facade(tmp_path)
    try:
        loaded = facade.load_batch("graph-source-ownership-task", "graph-source-ownership-batch")
        original = deepcopy(loaded["batch"])
        original_png = base64.b64decode(original["screenshots"][0]["png_base64"])
        created = facade.create_graph_revision(
            "graph-source-ownership-task", "graph-source-ownership-batch", 0,
            step_relationships={"step-a-b": ["relation-a-b"]},
        )
        edge = created["graph"]["edges"][0]
        edited = facade.apply_graph_edit(
            created["logical_workflow_id"], created["revision"], created["content_sha256"],
            {"type": "update_edge_target", "edge_id": edge["edge_id"],
             "target_node_id": _node(created, "interface-c")["node_id"]},
            "change-edge-target-1",
        )
        assert edited["revision"] == 2
        changed_edge = edited["graph"]["edges"][0]
        assert changed_edge["target_node_id"] == _node(edited, "interface-c")["node_id"]
        assert changed_edge["external_relationships"][0]["to_interface_id"] == "interface-c"
        assert changed_edge["external_relationships"][0]["kind"] == "到 B"
        for item in [changed_edge, changed_edge["external_relationships"][0]]:
            assert item["target_semantics_status"] == "stale_after_retarget"
            assert item["requires_semantic_review"] is True
        matching_action = next(item for item in _node(edited, "interface-a")["action_candidates"] if item["external_step_id"] == "step-a-b")
        assert matching_action["target_node_id"] == _node(edited, "interface-c")["node_id"]
        assert matching_action["target_semantics_status"] == "stale_after_retarget"
        assert matching_action["requires_semantic_review"] is True
        assert changed_edge["success_conditions"] == ["B 可见"]
        assert facade.load_graph_revision(edited["logical_workflow_id"])["content_sha256"] == edited["content_sha256"]
        assert facade.load_graph_revision(edited["logical_workflow_id"], 1)["graph"]["edges"][0]["target_node_id"] == _node(created, "interface-b")["node_id"]
        assert facade.load_batch("graph-source-ownership-task", "graph-source-ownership-batch")["batch"] == original
        assert hashlib.sha256(original_png).hexdigest() == original["screenshots"][0]["sha256"]
        assert base64.b64decode(original["screenshots"][0]["png_base64"]) == original_png
        assert created["graph"]["edges"][0]["target_node_id"] == _node(created, "interface-b")["node_id"]
        assert "target_semantics_status" not in created["graph"]["edges"][0]
        facade.close()
        reopened = NativeReviewFacade(service, "graph-source-ownership-reviewer", root)
        try:
            assert _node(reopened.load_graph_revision(edited["logical_workflow_id"]), "interface-c")["node_id"] == changed_edge["target_node_id"]
        finally:
            reopened.close()
    finally:
        facade.close()
        store.close()


def test_bbox_edits_update_controls_and_reject_bad_input_without_advancing_head(tmp_path: Path) -> None:
    facade, store, _, _ = _facade(tmp_path)
    try:
        created = facade.create_graph_revision("graph-source-ownership-task", "graph-source-ownership-batch", 0)
        node = _node(created, "interface-a")
        edited = facade.apply_graph_edit(
            created["logical_workflow_id"], 1, created["content_sha256"],
            {"type": "update_region_bbox", "node_id": node["node_id"], "region_id": "region-a", "bbox": [4, 5, 30, 20]},
            "change-bbox-1",
        )
        changed_node = _node(edited, "interface-a")
        assert changed_node["regions"][0]["bbox"] == [4, 5, 30, 20]
        assert changed_node["controls"][0]["bbox"] == [4, 5, 30, 20]
        with pytest.raises(DesktopReviewError):
            facade.apply_graph_edit(
                edited["logical_workflow_id"], 2, edited["content_sha256"],
                {"type": "update_region_bbox", "node_id": node["node_id"], "region_id": "region-a", "bbox": [90, 5, 30, 20]},
                "bad-bbox",
            )
        assert facade.load_graph_revision(edited["logical_workflow_id"])["revision"] == 2
    finally:
        facade.close()
        store.close()


def test_graph_edit_concurrency_and_idempotency_are_committed_once(tmp_path: Path) -> None:
    facade, store, _, _ = _facade(tmp_path)
    try:
        created = facade.create_graph_revision("graph-source-ownership-task", "graph-source-ownership-batch", 0)
        edge = created["graph"]["edges"][0]
        operation = {"type": "update_edge_target", "edge_id": edge["edge_id"], "target_node_id": _node(created, "interface-c")["node_id"]}
        committed = facade.apply_graph_edit(created["logical_workflow_id"], 1, created["content_sha256"], operation, "same-key")
        duplicate = facade.apply_graph_edit(created["logical_workflow_id"], 1, created["content_sha256"], operation, "same-key")
        assert duplicate == committed
        with pytest.raises(DesktopReviewError):
            facade.apply_graph_edit(created["logical_workflow_id"], 1, created["content_sha256"], operation, "other-key")
        with pytest.raises(DesktopReviewError):
            facade.apply_graph_edit(created["logical_workflow_id"], 1, created["content_sha256"], {**operation, "target_node_id": _node(created, "interface-b")["node_id"]}, "same-key")
    finally:
        facade.close()
        store.close()


def test_graph_load_rejects_unsafe_or_tampered_draft_without_recreation(tmp_path: Path) -> None:
    facade, store, _, root = _facade(tmp_path)
    try:
        created = facade.create_graph_revision("graph-source-ownership-task", "graph-source-ownership-batch", 0)
        with pytest.raises(DesktopReviewError):
            facade.load_graph_revision("workflow-../unsafe")
        revision_path = root / "desktop-review" / "graph-revisions" / created["logical_workflow_id"] / "revisions" / f"{created['content_sha256']}.json"
        revision_path.write_text("{}\n", encoding="utf-8")
        with pytest.raises(DesktopReviewError):
            facade.load_graph_revision(created["logical_workflow_id"])
        assert revision_path.read_text(encoding="utf-8") == "{}\n"
    finally:
        facade.close()
        store.close()


def test_interrupted_head_switch_keeps_previous_commit_until_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    facade, store, _, _ = _facade(tmp_path)
    try:
        created = facade.create_graph_revision("graph-source-ownership-task", "graph-source-ownership-batch", 0)
        edge = created["graph"]["edges"][0]
        operation = {"type": "update_edge_target", "edge_id": edge["edge_id"], "target_node_id": _node(created, "interface-c")["node_id"]}
        real_atomic_write = graph_revision._atomic_write_bytes

        def interrupted(path: Path, payload: bytes) -> None:
            if path.name == "draft_head.json":
                raise OSError("simulated interrupted head switch")
            real_atomic_write(path, payload)

        monkeypatch.setattr(graph_revision, "_atomic_write_bytes", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            facade.apply_graph_edit(created["logical_workflow_id"], 1, created["content_sha256"], operation, "head-interrupted")
        assert facade.load_graph_revision(created["logical_workflow_id"])["revision"] == 1
        monkeypatch.setattr(graph_revision, "_atomic_write_bytes", real_atomic_write)
        retried = facade.apply_graph_edit(created["logical_workflow_id"], 1, created["content_sha256"], operation, "head-interrupted")
        assert retried["revision"] == 2
        assert retried["graph"]["display_only"] is True
        assert retried["graph"]["execute_binding_enabled"] is False
    finally:
        facade.close()
        store.close()


def test_source_evidence_tamper_is_rejected_without_graph_recreation(tmp_path: Path) -> None:
    facade, store, _, root = _facade(tmp_path)
    try:
        created = facade.create_graph_revision("graph-source-ownership-task", "graph-source-ownership-batch", 0)
        source = created["source_refs"]
        source_path = root / source["original_batch_path"]
        source_path.write_text("{}\n", encoding="utf-8")
        with pytest.raises(DesktopReviewError):
            facade.load_graph_revision(created["logical_workflow_id"])
        assert source_path.read_text(encoding="utf-8") == "{}\n"
    finally:
        facade.close()
        store.close()


def test_graph_imports_saved_workspace_without_rewriting_original_source(tmp_path: Path) -> None:
    facade, store, service, root = _facade(tmp_path)
    try:
        loaded = facade.load_batch("graph-source-ownership-task", "graph-source-ownership-batch")
        original = deepcopy(loaded["batch"])
        edited_batch = deepcopy(original)
        edited_batch["interfaces"][0]["meaning"] = "已保存的人审 A"
        edited_batch["interfaces"][0]["regions"][0]["bbox"] = [4.0, 5.0, 30.0, 20.0]
        saved = facade.save_revision("graph-source-ownership-task", "graph-source-ownership-batch", 0, edited_batch)
        created = facade.create_graph_revision("graph-source-ownership-task", "graph-source-ownership-batch", 1)
        node = _node(created, "interface-a")
        assert node["display_name"] == "已保存的人审 A"
        assert node["regions"][0]["bbox"] == [4.0, 5.0, 30.0, 20.0]
        imported = created["source_refs"]["imported_workspace"]
        assert imported["revision"] == saved["revision"] == 1
        assert (root / imported["workspace_path"]).is_file()
        original_source = json.loads((root / created["source_refs"]["original_batch_path"]).read_text(encoding="utf-8"))
        assert original_source["interfaces"][0]["meaning"] == original["interfaces"][0]["meaning"]
        assert original_source["interfaces"][0]["regions"][0]["bbox"] == original["interfaces"][0]["regions"][0]["bbox"]
        facade.close()
        reopened = NativeReviewFacade(service, "graph-source-ownership-reviewer", root)
        try:
            restored = reopened.load_graph_revision(created["logical_workflow_id"])
            assert _node(restored, "interface-a")["regions"][0]["bbox"] == [4.0, 5.0, 30.0, 20.0]
        finally:
            reopened.close()
    finally:
        facade.close()
        store.close()


def test_bbox_uses_node_evidence_path_when_distinct_screenshot_ids_share_png(tmp_path: Path) -> None:
    batch = _duplicate_png_batch()
    facade, store, _, _ = _facade(tmp_path, batch)
    try:
        created = facade.create_graph_revision("graph-source-ownership-task", batch["batch_id"], 0)
        target = _node(created, "interface-b")
        untouched = deepcopy(_node(created, "interface-a"))
        edited = facade.apply_graph_edit(
            created["logical_workflow_id"], 1, created["content_sha256"],
            {"type": "update_region_bbox", "node_id": target["node_id"], "region_id": "region-b", "bbox": [5, 6, 20, 10]},
            "duplicate-png-bbox",
        )
        assert _node(edited, "interface-b")["regions"][0]["bbox"] == [5, 6, 20, 10]
        assert _node(edited, "interface-a") == untouched
    finally:
        facade.close()
        store.close()


def test_create_does_not_reset_revised_graph_when_head_is_missing(tmp_path: Path) -> None:
    facade, store, _, root = _facade(tmp_path)
    try:
        created = facade.create_graph_revision("graph-source-ownership-task", "graph-source-ownership-batch", 0)
        changed = facade.apply_graph_edit(
            created["logical_workflow_id"], 1, created["content_sha256"],
            {"type": "update_edge_target", "edge_id": created["graph"]["edges"][0]["edge_id"],
             "target_node_id": _node(created, "interface-c")["node_id"]}, "changed-before-head-loss",
        )
        directory = root / "desktop-review" / "graph-revisions" / created["logical_workflow_id"]
        head = directory / "draft_head.json"
        # 在隔离样本中模拟头文件缺失，不动任何用户数据。
        head.replace(directory / "missing-head.fixture")
        before = {path.name: path.read_bytes() for path in (directory / "revisions").glob("*.json")}
        with pytest.raises(DesktopReviewError, match="头指针缺失"):
            facade.create_graph_revision("graph-source-ownership-task", "graph-source-ownership-batch", 0)
        assert not head.exists()
        assert {path.name: path.read_bytes() for path in (directory / "revisions").glob("*.json")} == before
        assert (directory / "revisions" / f"{changed['content_sha256']}.json").is_file()
    finally:
        facade.close()
        store.close()


def test_imported_snapshot_is_pinned_after_workspace_advances_and_detects_tamper(tmp_path: Path) -> None:
    facade, store, _, root = _facade(tmp_path)
    try:
        loaded = facade.load_batch("graph-source-ownership-task", "graph-source-ownership-batch")
        source = deepcopy(loaded["batch"])
        source["interfaces"][0]["meaning"] = "固定导入版本"
        facade.save_revision("graph-source-ownership-task", source["batch_id"], 0, source)
        graph = facade.create_graph_revision("graph-source-ownership-task", source["batch_id"], 1)
        source["interfaces"][0]["meaning"] = "后续旧工作区修改"
        facade.save_revision("graph-source-ownership-task", source["batch_id"], 1, source)
        assert facade.load_graph_revision(graph["logical_workflow_id"]) == graph
        imported = root / graph["source_refs"]["imported_workspace"]["workspace_path"]
        imported.write_bytes(imported.read_bytes() + b" ")
        with pytest.raises(DesktopReviewError, match="工作区修订摘要不匹配"):
            facade.load_graph_revision(graph["logical_workflow_id"])
    finally:
        facade.close()
        store.close()
