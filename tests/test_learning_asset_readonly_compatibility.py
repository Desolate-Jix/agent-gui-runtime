"""旧格式只读兼容的离线证据；不迁移原件、不把旧资产当作新学习。"""

import hashlib
import json

import pytest

from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
from tests.test_reviewed_interface_memory import _write_reviewed_candidate
from tests.test_reviewed_workflow_asset_v2 import _asset


def _snapshot(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def test_supported_legacy_and_v2_stores_reload_without_migration_or_writes(tmp_path):
    legacy = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    legacy.publish(source_path=_write_reviewed_candidate(tmp_path), interface_id="legacy_search", expected_registry_revision=0)
    modern = ReviewedWorkflowAssetStore(project_root=tmp_path)
    asset = _asset()
    modern.publish(asset, expected_registry_revision=0)
    before = _snapshot(tmp_path)

    old_loaded = ReviewedInterfaceMemoryStore(project_root=tmp_path).load_active("legacy_search")
    new_loaded = ReviewedWorkflowAssetStore(project_root=tmp_path).load_active(asset["asset_id"])

    assert old_loaded["contract_version"] == "reviewed_interface_memory_v1"
    assert new_loaded["contract_version"] == "reviewed_workflow_asset_v2"
    assert old_loaded["artifact_is_authorization"] is False
    assert new_loaded["safety"]["artifact_is_authorization"] is False
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("contract", ["reviewed_workflow_asset_registry_v1", "unknown_future_registry"])
def test_unsupported_registry_is_rejected_and_preserved(tmp_path, contract):
    store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    store.registry_path.parent.mkdir(parents=True)
    store.registry_path.write_text(json.dumps({"contract_version": contract}), encoding="utf-8")
    before = _snapshot(tmp_path)
    with pytest.raises(ValueError, match="invalid registry contract"):
        store.load_active("legacy_search")
    assert _snapshot(tmp_path) == before


def test_corrupt_legacy_object_fails_closed_without_repairing_it(tmp_path):
    store = ReviewedInterfaceMemoryStore(project_root=tmp_path)
    published = store.publish(source_path=_write_reviewed_candidate(tmp_path), interface_id="legacy_search", expected_registry_revision=0)
    object_path = tmp_path / published["object_path"]
    object_path.write_bytes(object_path.read_bytes() + b"\n")
    before = _snapshot(tmp_path)
    with pytest.raises(ValueError, match="checksum"):
        ReviewedInterfaceMemoryStore(project_root=tmp_path).load_active("legacy_search")
    assert _snapshot(tmp_path) == before
