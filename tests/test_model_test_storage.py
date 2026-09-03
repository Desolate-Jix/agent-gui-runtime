from __future__ import annotations

from hashlib import sha256
import json
import os
import subprocess
import sys
from types import SimpleNamespace
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

    weight = _write(tmp_path / "artifacts" / "provider-a" / ("a" * 40) / "model.bin", b"model")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["revision"] == "a" * 40
    assert payload["files"] == [{"relative_path": f"artifacts/provider-a/{'a' * 40}/model.bin", "bytes": 5, "sha256": sha256(b"model").hexdigest()}]
    with pytest.raises(ValueError, match="immutable"):
        register_downloaded_artifact(root=tmp_path, provider_id="provider-b", repo_id="org/model", revision="main", files=[weight])


def test_safe_delete_rejects_root_outside_symlink_reparse_and_unregistered_path(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import delete_registered_artifact, register_downloaded_artifact

    weight = _write(tmp_path / "artifacts" / "provider-a" / ("a" * 40) / "model.bin", b"model")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    outside = _write(tmp_path.parent / "outside.bin", b"outside")
    payload = json.loads(manifest.read_text(encoding="utf-8")); payload["files"][0]["relative_path"] = "../outside.bin"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="registration"):
        delete_registered_artifact(root=tmp_path, manifest_path=manifest)
    assert outside.exists() and weight.exists()
    with pytest.raises(ValueError, match="root"):
        delete_registered_artifact(root=tmp_path, manifest_path=tmp_path)


def test_safe_delete_removes_only_registered_weights_and_keeps_report_manifest(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import delete_registered_artifact, register_downloaded_artifact

    weight = _write(tmp_path / "artifacts" / "provider-a" / ("a" * 40) / "model.bin", b"model")
    untouched = _write(tmp_path / "weights" / "keep.bin", b"keep")
    report = _write(tmp_path / "reports" / "run.json", b"report")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    receipt = delete_registered_artifact(root=tmp_path, manifest_path=manifest)
    assert receipt["deleted_count"] == 1
    assert not weight.exists()
    assert untouched.exists() and report.exists() and manifest.exists()


def test_safe_delete_rejects_windows_reparse_target(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import delete_registered_artifact, register_downloaded_artifact

    weight = _write(tmp_path / "artifacts" / "provider-a" / ("a" * 40) / "model.bin", b"model")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    outside = _write(tmp_path.parent / "reparse-outside.bin", b"outside")
    link = tmp_path / "artifacts" / "provider-a" / ("a" * 40) / "linked.bin"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("Windows symlink privilege is unavailable")
    payload = json.loads(manifest.read_text(encoding="utf-8")); payload["files"][0]["relative_path"] = f"artifacts/provider-a/{'a' * 40}/linked.bin"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="registration|reparse|symlink"):
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

    root = tmp_path / "\u6a21\u578b\u6d4b\u8bd5"
    weight = _write(root / "artifacts" / "provider-a" / ("a" * 40) / "模型.bin", b"model")
    manifest = register_downloaded_artifact(root=root, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    assert "模型" in manifest.read_text(encoding="utf-8")


def test_delete_rejects_modified_or_hardlinked_registered_file(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import delete_registered_artifact, register_downloaded_artifact

    weight = _write(tmp_path / "artifacts" / "provider-a" / ("a" * 40) / "model.bin", b"model")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[weight])
    weight.write_bytes(b"changed")
    with pytest.raises(ValueError, match="modified"):
        delete_registered_artifact(root=tmp_path, manifest_path=manifest)
    assert weight.exists()
    if hasattr(os, "link"):
        weight.write_bytes(b"model")
        alias = tmp_path / "artifacts" / "provider-a" / ("a" * 40) / "alias.bin"
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
        materialize_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, staging_path=staging, expected_files={"model.bin": 99}, expected_sha256={"model.bin": "a" * 64})
    assert not (tmp_path / "artifacts" / "provider-a").exists()


def test_registry_rejects_manifest_edit_to_another_in_root_artifact(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import delete_registered_artifact, register_downloaded_artifact

    first = _write(tmp_path / "artifacts" / "provider-a" / ("a" * 40) / "first.bin", b"first")
    second = _write(tmp_path / "artifacts" / "provider-b" / ("b" * 40) / "second.bin", b"second")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/a", revision="a" * 40, files=[first])
    register_downloaded_artifact(root=tmp_path, provider_id="provider-b", repo_id="org/b", revision="b" * 40, files=[second])
    payload = json.loads(manifest.read_text(encoding="utf-8")); payload["files"][0]["relative_path"] = f"artifacts/provider-b/{'b' * 40}/second.bin"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="registration"):
        delete_registered_artifact(root=tmp_path, manifest_path=manifest)
    assert first.exists() and second.exists()



def _expected(data: bytes) -> dict[str, str]:
    return {"model.bin": sha256(data).hexdigest()}


def test_registration_rejects_file_outside_exact_artifact_namespace(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import register_downloaded_artifact

    misplaced = _write(tmp_path / "weights" / "model.bin", b"model")
    with pytest.raises(ValueError, match="exact artifact namespace"):
        register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision="a" * 40, files=[misplaced])


@pytest.mark.parametrize("failing_name", ["manifests", "artifact-registry.json"])
def test_materialize_rolls_back_destination_and_publication_on_atomic_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing_name: str) -> None:
    import app.learn.hybrid.model_test_storage as storage

    revision = "a" * 40
    staging = _write(tmp_path / "staging" / "provider-a" / revision / "model.bin", b"model").parent
    original = storage._atomic_json

    def fail_atomic(path: Path, payload: object) -> None:
        if path.parent.name == failing_name or path.name == failing_name:
            original(path, payload)
            raise OSError("injected atomic publication failure")
        original(path, payload)

    monkeypatch.setattr(storage, "_atomic_json", fail_atomic)
    with pytest.raises(OSError, match="injected"):
        storage.materialize_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision=revision, staging_path=staging, expected_files={"model.bin": 5}, expected_sha256=_expected(b"model"))
    assert (staging / "model.bin").read_bytes() == b"model"
    assert not (tmp_path / "artifacts" / "provider-a" / revision).exists()
    assert not (tmp_path / "manifests" / f"provider-a-{revision}.json").exists()
    registry = tmp_path / "reports" / "artifact-registry.json"
    assert not registry.exists() or f"provider-a-{revision}.json" not in registry.read_text(encoding="utf-8")


def test_materialize_rehashes_after_download_verification_boundary(tmp_path: Path) -> None:
    from app.learn.hybrid.model_test_storage import materialize_downloaded_artifact

    revision = "a" * 40
    staging = _write(tmp_path / "staging" / "provider-a" / revision / "model.bin", b"correct").parent
    (staging / "model.bin").write_bytes(b"mutated")
    with pytest.raises(ValueError, match="changed"):
        materialize_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision=revision, staging_path=staging, expected_files={"model.bin": 7}, expected_sha256=_expected(b"correct"))
    assert staging.exists()
    assert not (tmp_path / "artifacts" / "provider-a" / revision).exists()


def test_deletion_journal_records_progress_and_blocks_blind_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.learn.hybrid.model_test_storage import delete_registered_artifact, register_downloaded_artifact

    revision = "a" * 40
    first = _write(tmp_path / "artifacts" / "provider-a" / revision / "first.bin", b"first")
    second = _write(tmp_path / "artifacts" / "provider-a" / revision / "second.bin", b"second")
    manifest = register_downloaded_artifact(root=tmp_path, provider_id="provider-a", repo_id="org/model", revision=revision, files=[first, second])
    original_unlink = Path.unlink

    def fail_second(self: Path, *args: object, **kwargs: object) -> None:
        if self == second:
            raise OSError("injected unlink failure")
        original_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second)
    with pytest.raises(OSError, match="injected"):
        delete_registered_artifact(root=tmp_path, manifest_path=manifest)
    journal = tmp_path / "reports" / f"provider-a-{revision}-deletion-pending.json"
    pending = json.loads(journal.read_text(encoding="utf-8"))
    assert pending["status"] == "pending"
    assert pending["deleted_files"] == [f"artifacts/provider-a/{revision}/first.bin"]
    assert pending["remaining_files"] == [f"artifacts/provider-a/{revision}/second.bin"]
    assert not first.exists() and second.exists() and manifest.exists()
    with pytest.raises(RuntimeError, match="pending"):
        delete_registered_artifact(root=tmp_path, manifest_path=manifest)


def test_quota_reservation_rejects_contention_and_cleans_lock(tmp_path: Path) -> None:
    from scripts.fetch_goal_binding_model import _quota_reservation

    with _quota_reservation(tmp_path):
        with pytest.raises(RuntimeError, match="another model acquisition"):
            with _quota_reservation(tmp_path):
                pass
    assert not (tmp_path / ".goal-binding-quota.lock").exists()


def test_quota_reservation_rejects_reparse_root_before_lock(tmp_path: Path) -> None:
    from scripts.fetch_goal_binding_model import _quota_reservation

    link = tmp_path / "linked-root"
    try:
        os.symlink(tmp_path, link, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege is unavailable")
    with pytest.raises(ValueError, match="reparse"):
        with _quota_reservation(link):
            pass
    assert not (link / ".goal-binding-quota.lock").exists()


def test_fetch_profile_uses_pinned_hf_endpoint_and_sealed_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.fetch_goal_binding_model as fetch

    revision = "a" * 40
    payload = b"model-payload"
    calls: dict[str, object] = {}

    class FakeApi:
        def __init__(self, **kwargs: object) -> None:
            calls["endpoint"] = kwargs.get("endpoint")

        def model_info(self, repo_id: str, **kwargs: object) -> object:
            calls["model_info"] = (repo_id, kwargs)
            return SimpleNamespace(sha=revision, siblings=[SimpleNamespace(rfilename="model.bin", size=len(payload), lfs={"sha256": sha256(payload).hexdigest(), "size": len(payload)})])

    def fake_download(**kwargs: object) -> str:
        calls.setdefault("downloads", []).append(kwargs)
        target = Path(str(kwargs["local_dir"])) / str(kwargs["filename"])
        _write(target, payload)
        _write(target.parent / ".cache" / "huggingface" / "metadata", b"cache")
        return str(target)

    monkeypatch.setattr(fetch, "MODEL_TEST_ROOT", tmp_path)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=FakeApi, hf_hub_download=fake_download))
    manifest = fetch.fetch_profile(profile={"provider_id": "provider-a", "repo_id": "org/model", "artifact_files": ["model.bin"]}, root=tmp_path)
    assert calls["endpoint"] == "https://huggingface.co"
    assert calls["model_info"] == ("org/model", {"revision": "main", "files_metadata": True})
    assert calls["downloads"] == [{"repo_id": "org/model", "filename": "model.bin", "revision": revision, "local_dir": tmp_path / "staging" / "provider-a" / revision, "endpoint": "https://huggingface.co"}]
    stored = tmp_path / "artifacts" / "provider-a" / revision / "model.bin"
    assert stored.read_bytes() == payload and not (tmp_path / "artifacts" / "provider-a" / revision / ".cache").exists()
    parsed = json.loads(manifest.read_text(encoding="utf-8"))
    assert parsed["files"] == [{"relative_path": f"artifacts/provider-a/{revision}/model.bin", "bytes": len(payload), "sha256": sha256(payload).hexdigest()}]


@pytest.mark.parametrize("provider, revision", [("../unsafe", "a" * 40), ("provider-a", "A" * 40)])
def test_fetch_rejects_unsafe_provider_or_nonhex_revision_before_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str, revision: str) -> None:
    import scripts.fetch_goal_binding_model as fetch

    class FakeApi:
        def __init__(self, **kwargs: object) -> None:
            pass
        def model_info(self, *args: object, **kwargs: object) -> object:
            return SimpleNamespace(sha=revision, siblings=[])

    monkeypatch.setattr(fetch, "MODEL_TEST_ROOT", tmp_path)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=FakeApi, hf_hub_download=lambda **_: None))
    with pytest.raises(ValueError):
        fetch.fetch_profile(profile={"provider_id": provider, "repo_id": "org/model", "artifact_files": ["model.bin"]}, root=tmp_path)
    assert not (tmp_path / "staging").exists()


def test_fetch_rejects_missing_or_wrong_lfs_hash_and_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.fetch_goal_binding_model as fetch

    revision = "a" * 40
    class FakeApi:
        def __init__(self, **kwargs: object) -> None:
            pass
        def model_info(self, *args: object, **kwargs: object) -> object:
            return SimpleNamespace(sha=revision, siblings=[SimpleNamespace(rfilename="model.bin", size=5, lfs={})])

    monkeypatch.setattr(fetch, "MODEL_TEST_ROOT", tmp_path)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=FakeApi, hf_hub_download=lambda **_: None))
    with pytest.raises(ValueError, match="SHA-256"):
        fetch.fetch_profile(profile={"provider_id": "provider-a", "repo_id": "org/model", "artifact_files": ["model.bin"]}, root=tmp_path)
    assert not (tmp_path / "staging").exists()



def test_fetch_rejects_wrong_hash_and_missing_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.fetch_goal_binding_model as fetch

    revision = "a" * 40
    payload = b"model"

    class FakeApi:
        def __init__(self, **kwargs: object) -> None:
            pass
        def model_info(self, *args: object, **kwargs: object) -> object:
            return SimpleNamespace(sha=revision, siblings=[SimpleNamespace(rfilename="model.bin", size=len(payload), lfs={"sha256": "b" * 64})])

    def fake_download(**kwargs: object) -> str:
        target = _write(Path(str(kwargs["local_dir"])) / str(kwargs["filename"]), payload)
        return str(target)

    monkeypatch.setattr(fetch, "MODEL_TEST_ROOT", tmp_path)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=FakeApi, hf_hub_download=fake_download))
    with pytest.raises(ValueError, match="download verification"):
        fetch.fetch_profile(profile={"provider_id": "provider-a", "repo_id": "org/model", "artifact_files": ["model.bin"]}, root=tmp_path)
    assert not (tmp_path / "artifacts").exists()

    class MissingApi(FakeApi):
        def model_info(self, *args: object, **kwargs: object) -> object:
            return SimpleNamespace(sha=revision, siblings=[])

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=MissingApi, hf_hub_download=fake_download))
    with pytest.raises(ValueError, match="size is unavailable"):
        fetch.fetch_profile(profile={"provider_id": "provider-a", "repo_id": "org/model", "artifact_files": ["model.bin"]}, root=tmp_path)
    assert not (tmp_path / "staging" / "provider-a" / revision).exists()


def test_fetch_rehashes_after_remote_verification_before_materializing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.fetch_goal_binding_model as fetch

    revision = "a" * 40
    payload = b"model"

    class FakeApi:
        def __init__(self, **kwargs: object) -> None:
            pass
        def model_info(self, *args: object, **kwargs: object) -> object:
            return SimpleNamespace(sha=revision, siblings=[SimpleNamespace(rfilename="model.bin", size=len(payload), lfs={"sha256": sha256(payload).hexdigest()})])

    def fake_download(**kwargs: object) -> str:
        target = _write(Path(str(kwargs["local_dir"])) / str(kwargs["filename"]), payload)
        return str(target)

    def mutate_after_fetch_verification(*, root: Path, staging_path: Path) -> None:
        (staging_path / "model.bin").write_bytes(b"alter")

    monkeypatch.setattr(fetch, "MODEL_TEST_ROOT", tmp_path)
    monkeypatch.setattr(fetch, "remove_huggingface_local_metadata", mutate_after_fetch_verification)
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=FakeApi, hf_hub_download=fake_download))
    with pytest.raises(ValueError, match="changed"):
        fetch.fetch_profile(profile={"provider_id": "provider-a", "repo_id": "org/model", "artifact_files": ["model.bin"]}, root=tmp_path)
    assert not (tmp_path / "artifacts").exists() and not (tmp_path / "staging" / "provider-a" / revision).exists()

def test_inventory_and_help_are_network_free_and_utf8_under_redirect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.fetch_goal_binding_model as fetch

    class Boom:
        def __init__(self, **kwargs: object) -> None:
            raise AssertionError("network client must not be created")

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=Boom, hf_hub_download=Boom))
    root = tmp_path / "\u6a21\u578b\u6d4b\u8bd5"
    _write(root / "one.bin", b"x")
    assert fetch.main(["--inventory-only", "--root", str(root)]) == 0
    completed = subprocess.run([sys.executable, "scripts/fetch_goal_binding_model.py", "--inventory-only", "--root", str(root)], cwd=Path(__file__).parents[1], capture_output=True, text=False, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=True)
    decoded = completed.stdout.decode("utf-8", errors="strict")
    assert json.loads(decoded)["root"] == str(root) and "\u6a21\u578b\u6d4b\u8bd5" in json.loads(decoded)["root"]
    help_result = subprocess.run([sys.executable, "scripts/fetch_goal_binding_model.py", "--help"], cwd=Path(__file__).parents[1], capture_output=True, text=True, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, check=True)
    assert "bounded" in help_result.stdout
