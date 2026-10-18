from __future__ import annotations

import base64
import copy
import hashlib
import json
from io import BytesIO
import os
from pathlib import Path

import pytest
from PIL import Image

from app.agent_link import AgentLinkService, AgentLinkStore
from app.agent_link.contracts import AgentLinkError
from app.desktop_review.external_mapping import build_external_workflow_review
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
from app.learn import interface_workflow_review
from app.learn.interface_workflow_review import save_interface_workflow_review_candidate


def _png_base64() -> str:
    image = Image.new("RGB", (80, 60), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def _batch() -> dict:
    return {
        "contract_version": "agent_link_v1",
        "idempotency_key": "batch-key",
        "batch_id": "batch-1",
        "title": "中文审核批次",
        "learning_outcome": "completed",
        "outcome_reason": None,
        "screenshots": [{"screenshot_id": "screen-1", "png_base64": _png_base64()}],
        "interfaces": [
            {
                "interface_id": "interface-1",
                "screenshot_id": "screen-1",
                "meaning": "原始界面含义",
                "regions": [
                    {
                        "region_id": "region-1",
                        "bbox": [2.0, 3.0, 20.0, 12.0],
                        "name": "原始按钮",
                        "meaning": "原始框含义",
                    }
                ],
            }
        ],
        "relationships": [],
        "steps": [
            {
                "step_id": "step-1",
                "action_type": "open_detail",
                "target_region_id": "region-1",
                "start_state": "interface-1",
                "arrival_state": "interface-1",
                "prerequisites": [],
                "expected_result": "详情已打开",
                "stop_condition": "停止",
            }
        ],
        "issues": [],
    }


def _facade(tmp_path: Path) -> tuple[NativeReviewFacade, AgentLinkService, str, Path]:
    return _facade_with_batch(tmp_path, _batch())


def _facade_with_batch(
    tmp_path: Path, batch: dict
) -> tuple[NativeReviewFacade, AgentLinkService, str, Path]:
    inbox = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(inbox, "reviewer-secret-value-123")
    grant = service.reviewer_call(
        "reviewer-secret-value-123",
        "create_connection",
        {"task_id": "task-1", "agent_name": "test-agent"},
    )
    service.agent_call(grant["token"], "submit_batch", batch)
    root = tmp_path / "desktop-review-data"
    return (
        NativeReviewFacade(service, "reviewer-secret-value-123", root),
        service,
        grant["token"],
        root,
    )


def _collision_batch(*, interface_ids: tuple[str, str], step_ids: tuple[str, str]) -> dict:
    batch = _batch()
    batch["idempotency_key"] = "collision-key"
    batch["batch_id"] = "collision-batch"
    batch["interfaces"] = [
        {
            "interface_id": interface_id,
            "screenshot_id": "screen-1",
            "meaning": f"界面 {index}",
            "regions": [
                {
                    "region_id": f"region-{index}",
                    "bbox": [float(index), 3.0, 20.0, 12.0],
                    "name": f"按钮 {index}",
                    "meaning": f"区域 {index}",
                }
            ],
        }
        for index, interface_id in enumerate(interface_ids, start=1)
    ]
    batch["steps"] = [
        {
            "step_id": step_id,
            "action_type": "open_detail",
            "target_region_id": f"region-{index}",
            "start_state": interface_ids[index - 1],
            "arrival_state": interface_ids[index - 1],
            "prerequisites": [],
            "expected_result": f"结果 {index}",
            "stop_condition": f"停止 {index}",
        }
        for index, step_id in enumerate(step_ids, start=1)
    ]
    return batch


@pytest.mark.parametrize(
    ("interface_ids", "step_ids"),
    [
        (("a/b", "a?b"), ("step/a", "step?a")),
        (("i" * 159 + "a", "i" * 159 + "b"), ("s" * 159 + "a", "s" * 159 + "b")),
    ],
)
def test_save_and_reload_preserves_distinct_collision_prone_external_topology(
    tmp_path: Path,
    interface_ids: tuple[str, str],
    step_ids: tuple[str, str],
) -> None:
    facade, service, _, root = _facade_with_batch(
        tmp_path, _collision_batch(interface_ids=interface_ids, step_ids=step_ids)
    )
    try:
        saved = facade.save_revision(
            "task-1", "collision-batch", 0,
            facade.load_batch("task-1", "collision-batch")["batch"],
        )
        workflow = json.loads(Path(saved["workflow_review_path"]).read_text(encoding="utf-8"))
        assert len({node["node_id"] for node in workflow["nodes"]}) == 2
        assert len({edge["edge_id"] for edge in workflow["edges"]}) == 2
        assert len(
            {
                action["action_template_id"]
                for node in workflow["nodes"]
                for action in node["action_candidates"]
            }
        ) == 2
        assert {edge["external_step_id"] for edge in workflow["edges"]} == set(step_ids)
        assert {
            action["external_step_id"]
            for node in workflow["nodes"]
            for action in node["action_candidates"]
        } == set(step_ids)

        facade.close()
        reopened = NativeReviewFacade(service, "reviewer-secret-value-123", root)
        try:
            reloaded = reopened.load_batch("task-1", "collision-batch")
            assert {item["interface_id"] for item in reloaded["batch"]["interfaces"]} == set(interface_ids)
            restored = json.loads(Path(reloaded["workflow_review_path"]).read_text(encoding="utf-8"))
            assert len({node["node_id"] for node in restored["nodes"]}) == 2
            assert len({edge["edge_id"] for edge in restored["edges"]}) == 2
        finally:
            reopened.close()
    finally:
        facade.close()


def test_external_provenance_notice_has_explicit_runtime_policy_without_authorization(tmp_path: Path) -> None:
    facade, _, _, _ = _facade(tmp_path)
    try:
        saved = facade.save_revision(
            "task-1", "batch-1", 0, facade.load_batch("task-1", "batch-1")["batch"]
        )
        review = json.loads(Path(saved["workflow_review_path"]).read_text(encoding="utf-8"))
        node = review["nodes"][0]
        notice = next(item for item in node["blockers"] if item["kind"] == "external_untrusted_source")
        assert notice["safe_stop_required"] is False
        assert node["review_status"] == "needs_human_review"
        assert node["reviewed_by_human"] is False
        assert node["artifact_is_authorization"] is False
        assert node["execute_binding_enabled"] is False
    finally:
        facade.close()


def test_long_task_and_batch_ids_have_bounded_workflow_component_for_revision_100(
    tmp_path: Path,
) -> None:
    batch = _batch()
    batch["idempotency_key"] = "long-component-key"
    batch["batch_id"] = "b" * 160
    facade, _, _, root = _facade_with_batch(tmp_path, batch)
    try:
        materialized = facade.save_revision(
            "task-1", batch["batch_id"], 0,
            facade.load_batch("task-1", batch["batch_id"])["batch"],
        )
        workflow = build_external_workflow_review(
            batch=materialized["batch"],
            task_id="t" * 160,
            source_ref=materialized["source_ref"],
            revision=100,
        )
        assert len(workflow["workflow"]["workflow_id"]) <= 128
        saved = save_interface_workflow_review_candidate(workflow, project_root=root)
        assert Path(saved["path"]).is_file()
    finally:
        facade.close()


def test_restart_rejects_tampered_materialized_editable_review_source(tmp_path: Path) -> None:
    facade, service, _, root = _facade(tmp_path)
    try:
        saved = facade.save_revision(
            "task-1", "batch-1", 0, facade.load_batch("task-1", "batch-1")["batch"]
        )
        review = json.loads(Path(saved["workflow_review_path"]).read_text(encoding="utf-8"))
        editable = root / review["nodes"][0]["editable_review_source_path"]
        assert editable.is_file()
        facade.close()

        editable_payload = json.loads(editable.read_text(encoding="utf-8"))
        editable_payload["draft"]["regions"][0]["meaning"] = "篡改后的区域语义"
        editable.write_text(
            json.dumps(editable_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        reopened = NativeReviewFacade(service, "reviewer-secret-value-123", root)
        try:
            with pytest.raises(DesktopReviewError):
                reopened.load_batch("task-1", "batch-1")
        finally:
            reopened.close()
    finally:
        facade.close()


def test_editable_review_source_equals_canonical_parent_node_projection(tmp_path: Path) -> None:
    facade, _, _, root = _facade(tmp_path)
    try:
        saved = facade.save_revision(
            "task-1", "batch-1", 0, facade.load_batch("task-1", "batch-1")["batch"]
        )
        review = json.loads(Path(saved["workflow_review_path"]).read_text(encoding="utf-8"))
        node = review["nodes"][0]
        editable = root / node["editable_review_source_path"]
        build_payload = getattr(
            interface_workflow_review,
            "build_interface_node_review_source_payload",
            None,
        )
        assert callable(build_payload)
        expected = build_payload(
            node,
            workflow_id=review["workflow"]["workflow_id"],
            project_root=root,
        )
        assert json.loads(editable.read_text(encoding="utf-8")) == expected
        expected_text = json.dumps(expected, ensure_ascii=False, indent=2) + "\n"
        assert editable.read_bytes() == expected_text.replace("\n", os.linesep).encode("utf-8")
    finally:
        facade.close()


def test_load_is_read_only_and_save_reloads_chinese_direct_edits(tmp_path: Path) -> None:
    facade, service, agent_token, root = _facade(tmp_path)
    try:
        before = list(root.rglob("*"))
        loaded = facade.load_batch("task-1", "batch-1")
        assert list(root.rglob("*")) == before
        assert loaded["revision"] == 0
        assert loaded["source"] == "untrusted_external"
        assert loaded["workflow_review_path"] is None
        assert loaded["batch"]["screenshots"][0]["sha256"]

        edited = copy.deepcopy(loaded["batch"])
        edited["interfaces"][0]["meaning"] = "人工修改后的中文界面含义"
        edited["interfaces"][0]["regions"][0]["bbox"] = [4.0, 5.0, 22.0, 14.0]
        edited["steps"][0]["expected_result"] = "人工修改后的步骤结果"
        saved = facade.save_revision("task-1", "batch-1", 0, edited)

        assert saved["revision"] == 1
        assert saved["source"] == "untrusted_external"
        assert saved["review_status"] == "needs_human_review"
        assert saved["workflow_review_path"]
        assert Path(saved["workflow_review_path"]).is_file()
        workflow = json.loads(Path(saved["workflow_review_path"]).read_text(encoding="utf-8"))
        assert workflow["artifact_is_authorization"] is False
        assert workflow["execute_binding_enabled"] is False
        assert workflow["nodes"][0]["reviewed_by_human"] is False
        assert workflow["nodes"][0]["evidence"].get("authoritative_source_ref") is None

        facade.close()
        reloaded = NativeReviewFacade(service, "reviewer-secret-value-123", root)
        try:
            snapshot = reloaded.load_batch("task-1", "batch-1")
            assert snapshot["revision"] == 1
            assert snapshot["source_ref"] == saved["source_ref"]
            assert snapshot["batch"]["interfaces"][0]["meaning"] == "人工修改后的中文界面含义"
            assert snapshot["batch"]["interfaces"][0]["regions"][0]["bbox"] == [4.0, 5.0, 22.0, 14.0]
        finally:
            reloaded.close()

        original = service.reviewer_call(
            "reviewer-secret-value-123", "get_batch", {"task_id": "task-1", "batch_id": "batch-1"}
        )["batch"]
        assert original["interfaces"][0]["meaning"] == "原始界面含义"
        assert service.agent_call(agent_token, "read_feedback", {"batch_id": "batch-1"})["revision"] == 0
    finally:
        facade.close()


def test_save_rejects_tampering_invalid_box_and_stale_revision_without_current_change(tmp_path: Path) -> None:
    facade, _, _, _ = _facade(tmp_path)
    try:
        loaded = facade.load_batch("task-1", "batch-1")
        saved = facade.save_revision("task-1", "batch-1", 0, loaded["batch"])

        stale = copy.deepcopy(saved["batch"])
        with pytest.raises(DesktopReviewError, match="stale"):
            facade.save_revision("task-1", "batch-1", 0, stale)
        assert facade.load_batch("task-1", "batch-1")["revision"] == 1

        invalid_box = copy.deepcopy(saved["batch"])
        invalid_box["interfaces"][0]["regions"][0]["bbox"] = [70.0, 50.0, 20.0, 20.0]
        with pytest.raises((DesktopReviewError, AgentLinkError)):
            facade.save_revision("task-1", "batch-1", 1, invalid_box)

        authority = copy.deepcopy(saved["batch"])
        authority["artifact_is_authorization"] = True
        with pytest.raises((DesktopReviewError, AgentLinkError)):
            facade.save_revision("task-1", "batch-1", 1, authority)

        forged_derived_hash = copy.deepcopy(saved["batch"])
        forged_derived_hash["screenshots"][0]["sha256"] = "0" * 64
        with pytest.raises(DesktopReviewError, match="派生摘要"):
            facade.save_revision("task-1", "batch-1", 1, forged_derived_hash)
        assert facade.load_batch("task-1", "batch-1")["revision"] == 1
    finally:
        facade.close()


def test_failed_current_manifest_write_does_not_publish_and_source_is_immutable(tmp_path: Path, monkeypatch) -> None:
    from app.desktop_review import workspace as workspace_module

    facade, _, _, root = _facade(tmp_path)
    try:
        loaded = facade.load_batch("task-1", "batch-1")
        first = facade.save_revision("task-1", "batch-1", 0, loaded["batch"])
        source_path = root / "desktop-review" / "sources" / first["source_ref"] / "original_batch.json"
        source_bytes = source_path.read_bytes()
        original_write = workspace_module._atomic_write_bytes

        def fail_current(path: Path, payload: bytes) -> None:
            if path.name == "current.json":
                raise OSError("simulated current manifest failure")
            original_write(path, payload)

        monkeypatch.setattr(workspace_module, "_atomic_write_bytes", fail_current)
        changed = copy.deepcopy(first["batch"])
        changed["interfaces"][0]["meaning"] = "第二个未发布修订"
        with pytest.raises(DesktopReviewError, match="persist"):
            facade.save_revision("task-1", "batch-1", 1, changed)
        assert facade.load_batch("task-1", "batch-1")["revision"] == 1
        assert source_path.read_bytes() == source_bytes
        attempts = list(
            (root / "desktop-review" / "workflow-revisions").rglob(
                "reviewed_workflow.json"
            )
        )
        assert len(attempts) == 2
        assert hashlib.sha256(source_bytes).hexdigest()
    finally:
        facade.close()


def test_restart_rejects_tampered_png_or_saved_review_without_repairing_current(tmp_path: Path) -> None:
    facade, service, _, root = _facade(tmp_path)
    try:
        saved = facade.save_revision(
            "task-1", "batch-1", 0, facade.load_batch("task-1", "batch-1")["batch"]
        )
        screenshot = next(
            (root / "desktop-review" / "sources" / saved["source_ref"] / "screenshots").glob("*.png")
        )
        original_image = screenshot.read_bytes()
        facade.close()

        screenshot.write_bytes(b"tampered png")
        reopened = NativeReviewFacade(service, "reviewer-secret-value-123", root)
        try:
            with pytest.raises(DesktopReviewError, match="截图证据摘要"):
                reopened.load_batch("task-1", "batch-1")
            assert screenshot.read_bytes() == b"tampered png"
        finally:
            reopened.close()

        screenshot.write_bytes(original_image)
        review_path = Path(saved["workflow_review_path"])
        review_path.write_bytes(b"{tampered review")
        reopened = NativeReviewFacade(service, "reviewer-secret-value-123", root)
        try:
            with pytest.raises(DesktopReviewError, match="审核文件摘要"):
                reopened.load_batch("task-1", "batch-1")
            assert review_path.read_bytes() == b"{tampered review"
        finally:
            reopened.close()
    finally:
        facade.close()
