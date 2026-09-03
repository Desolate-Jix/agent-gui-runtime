from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

import pytest


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_inventory_counts_all_logical_bytes_under_root(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import inventory_storage

    _write(tmp_path / "weights" / "a.bin", b"abc")
    _write(tmp_path / "reports" / "trace.json", b"12345")
    report = inventory_storage(tmp_path)
    assert report["logical_bytes"] == 8
    assert report["within_cap"] is True


def test_projected_download_over_30_gib_is_rejected_before_write(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import MODEL_TEST_MAX_BYTES, assert_download_fits

    before = set(tmp_path.rglob("*"))
    with pytest.raises(ValueError, match="cap"):
        assert_download_fits(root=tmp_path, remote_bytes=MODEL_TEST_MAX_BYTES)
    assert set(tmp_path.rglob("*")) == before


def test_download_manifest_requires_immutable_revision_size_and_sha(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import register_downloaded_artifact

    weight = _write(tmp_path / "weights" / "model.bin", b"model")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["revision"] == "a" * 40
    assert payload["files"] == [{"relative_path": "weights/model.bin", "bytes": 5, "sha256": sha256(b"model").hexdigest()}]
    with pytest.raises(ValueError, match="immutable"):
        register_downloaded_artifact(root=tmp_path, provider_id="provider-b", repo_id="org/model", revision="main", files=[weight])


def test_safe_delete_rejects_root_outside_symlink_reparse_and_unregistered_path(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import delete_registered_artifact, register_downloaded_artifact

    weight = _write(tmp_path / "weights" / "model.bin", b"model")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    outside = _write(tmp_path.parent / "outside.bin", b"outside")
    payload = json.loads(manifest.read_text(encoding="utf-8")); payload["files"][0]["relative_path"] = "../outside.bin"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="outside|traversal"):
        delete_registered_artifact(root=tmp_path, manifest_path=manifest)
    assert outside.exists() and weight.exists()
    with pytest.raises(ValueError, match="root"):
        delete_registered_artifact(root=tmp_path, manifest_path=tmp_path)


def test_safe_delete_removes_only_registered_weights_and_keeps_report_manifest(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import delete_registered_artifact, register_downloaded_artifact

    weight = _write(tmp_path / "weights" / "model.bin", b"model")
    untouched = _write(tmp_path / "weights" / "keep.bin", b"keep")
    report = _write(tmp_path / "reports" / "run.json", b"report")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    receipt = delete_registered_artifact(root=tmp_path, manifest_path=manifest)
    assert receipt["deleted_count"] == 1
    assert not weight.exists()
    assert untouched.exists() and report.exists() and manifest.exists()


def test_safe_delete_rejects_windows_reparse_target(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import delete_registered_artifact, register_downloaded_artifact

    weight = _write(tmp_path / "weights" / "model.bin", b"model")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    outside = _write(tmp_path.parent / "reparse-outside.bin", b"outside")
    link = tmp_path / "weights" / "linked.bin"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("Windows symlink privilege is unavailable")
    payload = json.loads(manifest.read_text(encoding="utf-8")); payload["files"][0]["relative_path"] = "weights/linked.bin"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="reparse|symlink"):
        delete_registered_artifact(root=tmp_path, manifest_path=manifest)
    assert outside.exists()


def test_failed_staging_cleanup_obeys_the_same_root_guard(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import cleanup_failed_staging

    outside = _write(tmp_path.parent / "staging-outside" / "partial.bin", b"partial")
    with pytest.raises(ValueError, match="outside"):
        cleanup_failed_staging(root=tmp_path, staging_path=outside.parent)
    assert outside.exists()


def test_no_storage_operation_touches_incumbent_d_drive_paths(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import register_downloaded_artifact

    with pytest.raises(ValueError, match="outside"):
        register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[Path(r"D:\incumbent\model.bin")])


def test_chinese_storage_root_round_trips_as_utf8(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import register_downloaded_artifact

    root = tmp_path / "模型测试"
    weight = _write(root / "权重" / "模型.bin", b"model")
    manifest = register_downloaded_artifact(root=root, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    assert "模型" in manifest.read_text(encoding="utf-8")


def test_delete_rejects_modified_or_hardlinked_registered_file(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import delete_registered_artifact, register_downloaded_artifact

    weight = _write(tmp_path / "weights" / "model.bin", b"model")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    weight.write_bytes(b"changed")
    with pytest.raises(ValueError, match="modified"):
        delete_registered_artifact(root=tmp_path, manifest_path=manifest)
    assert weight.exists()
    if hasattr(os, "link"):
        weight.write_bytes(b"model")
        alias = tmp_path / "weights" / "alias.bin"
        try:
            os.link(weight, alias)
        except OSError:
            pytest.skip("hard links unavailable")
        with pytest.raises(ValueError, match="hardlink"):
            delete_registered_artifact(root=tmp_path, manifest_path=manifest)


def test_partial_download_never_materializes_or_registers_a_manifest(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import materialize_downloaded_artifact

    staging = tmp_path / "staging" / "provider-a" / ("a" * 40)
    _write(staging / "model.bin", b"partial")
    with pytest.raises(ValueError, match="expected"):
        materialize_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, staging_path=staging, expected_files={"model.bin": 99})
    assert not (tmp_path / "artifacts" / "provider-a").exists()
