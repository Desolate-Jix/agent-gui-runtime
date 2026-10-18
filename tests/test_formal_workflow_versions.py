from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from app.agent import reviewed_workflow_asset as module
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
from app.desktop_review import exact_review
from test_formal_graph_source_ownership import _facade, _batch

X = "workflow-" + "a" * 64
Y = "workflow-" + "b" * 64


def _assets(tmp_path):
    batch = _batch()
    batch["interfaces"] = batch["interfaces"][:1]
    batch["steps"][0]["arrival_state"] = "interface-a"
    batch["relationships"][0]["to_interface_id"] = "interface-a"
    facade, inbox, _, root = _facade(tmp_path, batch)
    try:
        loaded = facade.load_batch("graph-source-ownership-task", "graph-source-ownership-batch")
        saved = facade.save_revision(loaded["task_id"], loaded["batch_id"], 0, loaded["batch"])
        binding = exact_review._binding({"kind": "native", "display_name": "Fresh version test",
                         "executable_identity": "notepad.exe", "product_name": "Notepad"})
        original = exact_review.ExactReviewService(facade)._review(saved, binding,
                         {"step_relationships": {"step-a-b": ["relation-a-b"]}, "stop_interface_ids": []})
        record = {"confirmed_subject_ids": [subject["subject_id"]
                  for subject in exact_review._subjects(original, saved["batch"], [])]}
    finally:
        facade.close()
        inbox.close()
    assets = []
    for name in ("x1", "x2", "y1"):
        final = deepcopy(original)
        final["workflow"]["workflow_id"] = "fresh-version-" + name
        final["nodes"][0]["display_name"] = name
        final = exact_review._approve(final, record)
        saved = exact_review.save_interface_workflow_review_candidate(final, project_root=root, create_only=True)
        relative = exact_review._result_relative_path(root, saved, "version fixture")
        result = exact_review.compile_reviewed_workflow_asset_v2(project_root=root, source_workflow_path=relative,
                    expected_source_workflow_sha256=hashlib.sha256((root / relative).read_bytes()).hexdigest())
        assert result["status"] == "compiled", result
        assets.append(result["asset"])
    return root, assets


def _binding(logical_id, revision):
    # 本文件验证底层注册表事务；图与回执互证由后续 façade 发布整合测试覆盖。
    return {"logical_workflow_id": logical_id, "graph_revision": revision,
            "graph_sha256": hashlib.sha256(f"{logical_id}:{revision}".encode()).hexdigest(),
            "review_ref": "c" * 64, "approval_revision": 1}


def test_workflow_current_is_scoped_and_history_is_pinned_across_restart(tmp_path):
    root, (x1, x2, y1) = _assets(tmp_path)
    store = ReviewedWorkflowAssetStore(project_root=root)
    first = store.publish_version(x1, publication=_binding(X, 1), expected_registry_revision=0)
    other = store.publish_version(y1, publication=_binding(Y, 1), expected_registry_revision=1)
    newer = store.publish_version(x2, publication=_binding(X, 2), expected_registry_revision=2)
    reopened = ReviewedWorkflowAssetStore(project_root=root)
    assert reopened.registry()["current_version_by_workflow"] == {X: newer["version_id"], Y: other["version_id"]}
    current = reopened.load_workflow_version(X)
    assert current["asset"] == module.validate_reviewed_workflow_asset(x2)
    assert current["status"] == "current"
    old = reopened.load_workflow_version(X, first["version_id"])
    assert old["asset"] == module.validate_reviewed_workflow_asset(x1)
    assert old["status"] == "superseded"
    assert old["artifact_is_authorization"] is False and old["execute_binding_enabled"] is False
    with pytest.raises(ValueError):
        reopened.load_workflow_version(Y, first["version_id"])
    assert reopened.load_workflow_version(Y)["version_id"] == other["version_id"]
    before = reopened.registry_path.read_bytes()
    retried = reopened.publish_version(x1, publication=_binding(X, 1), expected_registry_revision=0)
    assert retried["version_id"] == first["version_id"]
    assert reopened.registry_path.read_bytes() == before
    assert reopened.load_workflow_version(X)["version_id"] == newer["version_id"]


def test_failed_version_publication_keeps_both_indexes_and_retry_is_atomic(tmp_path, monkeypatch):
    root, (x1, x2, _) = _assets(tmp_path)
    store = ReviewedWorkflowAssetStore(project_root=root)
    first = store.publish_version(x1, publication=_binding(X, 1), expected_registry_revision=0)
    before = store.registry_path.read_bytes()
    original_write = module._atomic_write
    def fail_head(path, payload):
        if path == store.registry_path:
            raise OSError("version registry write failure")
        original_write(path, payload)
    with monkeypatch.context() as patch:
        patch.setattr(module, "_atomic_write", fail_head)
        with pytest.raises(OSError, match="registry write failure"):
            store.publish_version(x2, publication=_binding(X, 2), expected_registry_revision=1)
    assert store.registry_path.read_bytes() == before
    assert store.load_workflow_version(X)["version_id"] == first["version_id"]
    assert x2["asset_id"] not in store.registry()["active_by_asset"]
    result = store.publish_version(x2, publication=_binding(X, 2), expected_registry_revision=1)
    assert store.load_workflow_version(X)["version_id"] == result["version_id"]
    assert store.load_active(x2["asset_id"]) == module.validate_reviewed_workflow_asset(x2)


def test_legacy_publish_does_not_create_logical_workflow_or_choose_one(tmp_path):
    root, (asset, _, _) = _assets(tmp_path)
    store = ReviewedWorkflowAssetStore(project_root=root)
    receipt = store.publish(asset, expected_registry_revision=0)
    assert receipt["status"] == "published"
    assert "current_version_by_workflow" not in store.registry()
    with pytest.raises(ValueError):
        store.load_workflow_version(X)
    assert store.load_active(asset["asset_id"]) == module.validate_reviewed_workflow_asset(asset)


def test_explicit_current_selection_and_withdrawal_do_not_choose_replacements(tmp_path):
    root, (x1, x2, y1) = _assets(tmp_path)
    store = ReviewedWorkflowAssetStore(project_root=root)
    first = store.publish_version(x1, publication=_binding(X, 1), expected_registry_revision=0)
    other = store.publish_version(y1, publication=_binding(Y, 1), expected_registry_revision=1)
    newer = store.publish_version(x2, publication=_binding(X, 2), expected_registry_revision=2)
    immutable = deepcopy(store.registry()["workflow_versions"])
    store.set_current_version(X, first["version_id"], expected_registry_revision=3)
    assert store.load_workflow_version(X)["version_id"] == first["version_id"]
    store.withdraw_version(X, first["version_id"], expected_registry_revision=4)
    with pytest.raises(ValueError):
        store.load_workflow_version(X)
    assert store.load_workflow_version(X, first["version_id"])["status"] == "withdrawn"
    with pytest.raises(ValueError):
        store.set_current_version(X, first["version_id"], expected_registry_revision=5)
    store.set_current_version(X, newer["version_id"], expected_registry_revision=5)
    assert store.load_workflow_version(Y)["version_id"] == other["version_id"]
    assert store.registry()["workflow_versions"] == immutable
    before = store.registry_path.read_bytes()
    store.withdraw_version(X, first["version_id"], expected_registry_revision=4)
    assert store.registry_path.read_bytes() == before


def test_invalid_version_publication_rejects_before_writing_orphan_objects(tmp_path):
    root, (x1, x2, _) = _assets(tmp_path)
    store = ReviewedWorkflowAssetStore(project_root=root)
    store.publish_version(x2, publication=_binding(X, 2), expected_registry_revision=0)
    before = {path.name: path.read_bytes() for path in store.objects_root.glob("*.json")}
    registry = store.registry_path.read_bytes()
    with pytest.raises(ValueError, match="downgrade"):
        store.publish_version(x1, publication=_binding(X, 1), expected_registry_revision=1)
    assert {path.name: path.read_bytes() for path in store.objects_root.glob("*.json")} == before
    assert store.registry_path.read_bytes() == registry


@pytest.mark.parametrize("mutation", ["record", "foreign_current", "missing_record", "invalid_current_id", "asset_bytes"])
def test_version_reads_reject_corrupt_metadata_or_object_without_fallback(tmp_path, mutation):
    root, (x1, _, y1) = _assets(tmp_path)
    store = ReviewedWorkflowAssetStore(project_root=root)
    first = store.publish_version(x1, publication=_binding(X, 1), expected_registry_revision=0)
    other = store.publish_version(y1, publication=_binding(Y, 1), expected_registry_revision=1)
    registry = store.registry()
    if mutation == "record":
        registry["workflow_versions"][first["version_id"]]["graph_revision"] += 1
    elif mutation == "foreign_current":
        registry["current_version_by_workflow"][X] = other["version_id"]
    elif mutation == "missing_record":
        del registry["workflow_versions"][first["version_id"]]
    elif mutation == "invalid_current_id":
        registry["current_version_by_workflow"][X] = {"version_id": first["version_id"]}
    else:
        (store.objects_root / (first["asset_sha256"] + ".json")).write_bytes(b"changed object")
    store.registry_path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")
    before = store.registry_path.read_bytes()
    with pytest.raises(ValueError):
        store.load_workflow_version(X)
    assert store.registry_path.read_bytes() == before


def test_current_reselection_checks_object_but_withdrawal_can_retire_missing_object(tmp_path):
    root, (x1, _, _) = _assets(tmp_path)
    store = ReviewedWorkflowAssetStore(project_root=root)
    first = store.publish_version(x1, publication=_binding(X, 1), expected_registry_revision=0)
    (store.objects_root / (first["asset_sha256"] + ".json")).unlink()
    with pytest.raises(ValueError, match="missing"):
        store.set_current_version(X, first["version_id"], expected_registry_revision=1)
    result = store.withdraw_version(X, first["version_id"], expected_registry_revision=1)
    assert result["status"] == "withdrawn" and result["current_version_id"] is None


def test_version_selection_failure_and_stale_cas_preserve_registry(tmp_path, monkeypatch):
    root, (x1, x2, _) = _assets(tmp_path)
    store = ReviewedWorkflowAssetStore(project_root=root)
    first = store.publish_version(x1, publication=_binding(X, 1), expected_registry_revision=0)
    store.publish_version(x2, publication=_binding(X, 2), expected_registry_revision=1)
    before = store.registry_path.read_bytes()
    with pytest.raises(ValueError, match="revision"):
        store.set_current_version(X, first["version_id"], expected_registry_revision=1)
    def fail_write(path, payload):
        raise OSError("selection write failure")
    with monkeypatch.context() as patch:
        patch.setattr(module, "_atomic_write", fail_write)
        with pytest.raises(OSError, match="selection write failure"):
            store.set_current_version(X, first["version_id"], expected_registry_revision=2)
    assert store.registry_path.read_bytes() == before
