"""Fail-closed storage and deletion boundary for disposable model-test artifacts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile


MODEL_TEST_ROOT = Path(r"E:\模型测试")
MODEL_TEST_MAX_BYTES = 32_212_254_720
_STAGING_MARGIN_NUMERATOR = 105
_MANIFEST_VERSION = "model_test_artifact_manifest_v1"
_RESERVED_TOP_LEVEL = frozenset({"manifests", "reports", "staging"})
_REGISTRY_NAME = "artifact-registry.json"


def _is_reparse(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError as exc:
        raise ValueError("storage target is unavailable") from exc
    return stat.S_ISLNK(mode) or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_component(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in value):
        raise ValueError(f"{name} is unsafe")
    return value


def _immutable_revision(value: str) -> str:
    if not isinstance(value, str) or len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("revision must be an immutable lowercase 40-character commit")
    return value


def _within(root: Path, target: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(target))) == str(root)
    except ValueError:
        return False


def _guard(root: Path, target: Path, *, allow_root: bool = False) -> tuple[Path, Path]:
    root_abs = root.absolute()
    target_abs = target.absolute()
    if not _within(root_abs, target_abs):
        raise ValueError("storage target is outside the configured root")
    try:
        root_resolved = root.resolve(strict=True)
        target_resolved = target.resolve(strict=True)
    except OSError as exc:
        raise ValueError("storage target is unavailable") from exc
    if not _within(root_resolved, target_resolved):
        raise ValueError("storage target escapes root through traversal or reparse point")
    if not allow_root and target_resolved == root_resolved:
        raise ValueError("storage root itself is never a deletion target")
    relative = target_abs.relative_to(root_abs)
    current = root_abs
    if _is_reparse(current):
        raise ValueError("storage root is a reparse point")
    for part in relative.parts:
        current /= part
        if _is_reparse(current):
            raise ValueError("storage target contains a symlink or reparse point")
    return root_resolved, target_resolved


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _guarded_directory(root: Path, *parts: str) -> Path:
    """Create a guarded internal directory; callers must not treat injected roots as production authority."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    current = root
    if _is_reparse(current):
        raise ValueError("storage root is a reparse point")
    for part in parts:
        current /= part
        if current.exists() and _is_reparse(current):
            raise ValueError("storage destination contains a symlink or reparse point")
        current.mkdir(exist_ok=True)
        if _is_reparse(current):
            raise ValueError("storage destination became a reparse point")
    return current


def _remove_if_own_manifest(path: Path, *, provider_id: str, revision: str) -> None:
    """Remove a transaction's manifest only when its identity is still ours."""
    if not path.exists() or _is_reparse(path):
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(payload, Mapping) and payload.get("contract_version") == _MANIFEST_VERSION and payload.get("provider_id") == provider_id and payload.get("revision") == revision:
        path.unlink()


def _restore_registry(path: Path, previous: bytes | None) -> None:
    """Best-effort rollback for a registry replacement owned by this transaction."""
    if previous is None:
        if path.exists() and not _is_reparse(path):
            path.unlink()
        return
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.rollback.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(previous)
            handle.flush()
            os.fsync(handle.fileno())
        if _is_reparse(temporary) or _is_reparse(path.parent):
            raise ValueError("storage rollback destination is a reparse point")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    parent = path.parent
    if _is_reparse(parent):
        raise ValueError("storage destination parent is a reparse point")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if _is_reparse(temporary) or _is_reparse(parent):
            raise ValueError("storage temporary destination is a reparse point")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _logical_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    result: list[Path] = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        current = Path(directory)
        for name in list(dirs):
            candidate = current / name
            if _is_reparse(candidate):
                dirs.remove(name)
                result.append(candidate)
        for name in files:
            result.append(current / name)
    return result


def inventory_storage(root: Path = MODEL_TEST_ROOT) -> dict[str, object]:
    """Return logical bytes without creating the storage root or opening a network client."""
    root = Path(root)
    total = 0
    files = 0
    for path in _logical_files(root):
        try:
            info = path.lstat()
        except OSError as exc:
            raise ValueError("storage inventory changed while scanning") from exc
        if stat.S_ISREG(info.st_mode):
            total += info.st_size
            files += 1
    return {"root": str(root), "logical_bytes": total, "file_count": files, "max_bytes": MODEL_TEST_MAX_BYTES, "within_cap": total <= MODEL_TEST_MAX_BYTES}


def assert_download_fits(*, root: Path, remote_bytes: int) -> None:
    if isinstance(remote_bytes, bool) or not isinstance(remote_bytes, int) or remote_bytes < 0:
        raise ValueError("remote_bytes is invalid")
    current = int(inventory_storage(root)["logical_bytes"])
    staged = (remote_bytes * _STAGING_MARGIN_NUMERATOR + 99) // 100
    if current + staged > MODEL_TEST_MAX_BYTES:
        raise ValueError("projected model download exceeds the 30 GiB storage cap")


def _manifest_path(root: Path, provider_id: str, revision: str) -> Path:
    return root / "manifests" / f"{provider_id}-{revision}.json"


def _validate_registered_file(root: Path, path: Path) -> tuple[Path, str]:
    root_resolved, resolved = _guard(root, path)
    relative = resolved.relative_to(root_resolved)
    if not relative.parts or relative.parts[0] in _RESERVED_TOP_LEVEL:
        raise ValueError("registered file is not a model weight or runtime file")
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("registered target is not a regular file")
    if getattr(info, "st_nlink", 1) != 1:
        raise ValueError("registered target has hardlink ambiguity")
    return resolved, relative.as_posix()


def register_downloaded_artifact(*, root: Path, provider_id: str, repo_id: str, revision: str, files: Sequence[Path]) -> Path:
    _safe_component(provider_id, name="provider_id")
    _immutable_revision(revision)
    if not isinstance(repo_id, str) or not repo_id.strip() or not isinstance(files, Sequence) or isinstance(files, (str, bytes)) or not files:
        raise ValueError("artifact registration is invalid")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for file in files:
        if not isinstance(file, Path):
            raise ValueError("registered file path is invalid")
        resolved, relative = _validate_registered_file(root, file)
        namespace = Path("artifacts") / provider_id / revision
        if not Path(relative).is_relative_to(namespace):
            raise ValueError("registered file is outside its exact artifact namespace")
        if relative in seen:
            raise ValueError("registered file is duplicated")
        seen.add(relative)
        entries.append({"relative_path": relative, "bytes": resolved.stat().st_size, "sha256": _sha256(resolved)})
    entries.sort(key=lambda entry: str(entry["relative_path"]))
    manifest = _guarded_directory(root, "manifests") / _manifest_path(root, provider_id, revision).name
    if manifest.exists():
        raise ValueError("artifact manifest already exists")
    payload = {"contract_version": _MANIFEST_VERSION, "provider_id": provider_id, "repo_id": repo_id, "revision": revision, "files": entries, "artifact_is_authorization": False}
    registry_path = _guarded_directory(root, "reports") / _REGISTRY_NAME
    previous_registry = registry_path.read_bytes() if registry_path.exists() else None
    registry: dict[str, object] = {"contract_version": "model_test_artifact_registry_v1", "manifests": {}}
    if previous_registry is not None:
        try:
            loaded = json.loads(previous_registry.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("artifact registry is invalid") from exc
        if not isinstance(loaded, dict) or loaded.get("contract_version") != registry["contract_version"] or not isinstance(loaded.get("manifests"), dict):
            raise ValueError("artifact registry is invalid")
        registry = loaded
    records = registry["manifests"]
    assert isinstance(records, dict)
    key = manifest.relative_to(Path(root).resolve()).as_posix()
    if key in records:
        raise ValueError("artifact registry already contains manifest")
    try:
        _atomic_json(manifest, payload)
        records[key] = sha256(manifest.read_bytes()).hexdigest()
        _atomic_json(registry_path, registry)
    except BaseException:
        # A failed registry publication must never make a movable artifact look registered.
        try:
            _restore_registry(registry_path, previous_registry)
        finally:
            _remove_if_own_manifest(manifest, provider_id=provider_id, revision=revision)
        raise
    return manifest


def _load_manifest(root: Path, manifest_path: Path) -> tuple[dict[str, object], Path, Path]:
    root_resolved, resolved_manifest = _guard(root, manifest_path)
    if resolved_manifest.parent != root_resolved / "manifests":
        raise ValueError("manifest is not stored in the root manifests directory")
    try:
        payload = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("manifest is unreadable") from exc
    if not isinstance(payload, Mapping) or payload.get("contract_version") != _MANIFEST_VERSION:
        raise ValueError("manifest is invalid")
    provider = payload.get("provider_id")
    revision = payload.get("revision")
    _safe_component(provider, name="provider_id")
    _immutable_revision(revision)
    if resolved_manifest != _manifest_path(root_resolved, provider, revision):
        raise ValueError("manifest path does not match its identity")
    registry_path = root_resolved / "reports" / _REGISTRY_NAME
    _guard(root_resolved, registry_path)
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("artifact registry is unavailable") from exc
    key = resolved_manifest.relative_to(root_resolved).as_posix()
    if not isinstance(registry, Mapping) or not isinstance(registry.get("manifests"), Mapping) or registry["manifests"].get(key) != sha256(resolved_manifest.read_bytes()).hexdigest():
        raise ValueError("manifest does not match durable registration")
    if not isinstance(payload.get("files"), list) or not payload["files"]:
        raise ValueError("manifest files are invalid")
    return dict(payload), root_resolved, resolved_manifest


def delete_registered_artifact(*, root: Path, manifest_path: Path) -> dict[str, object]:
    payload, root_resolved, resolved_manifest = _load_manifest(Path(root), Path(manifest_path))
    reports = _guarded_directory(root_resolved, "reports")
    journal = reports / f"{payload['provider_id']}-{payload['revision']}-deletion-pending.json"
    if journal.exists():
        try:
            existing = json.loads(journal.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("deletion journal is unreadable") from exc
        if isinstance(existing, Mapping) and existing.get("status") == "pending":
            raise RuntimeError("registered artifact has a pending deletion journal")
        raise ValueError("deletion journal already exists")
    registered: list[Path] = []
    seen: set[str] = set()
    for entry in payload["files"]:
        if not isinstance(entry, Mapping) or set(entry) != {"relative_path", "bytes", "sha256"}:
            raise ValueError("manifest entry is invalid")
        relative, expected_bytes, expected_sha = entry["relative_path"], entry["bytes"], entry["sha256"]
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("manifest entry has outside traversal")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes < 0 or not isinstance(expected_sha, str) or len(expected_sha) != 64:
            raise ValueError("manifest entry is invalid")
        candidate = root_resolved / Path(relative)
        namespace = Path("artifacts") / str(payload["provider_id"]) / str(payload["revision"])
        if not Path(relative).is_relative_to(namespace):
            raise ValueError("manifest entry is outside its exact artifact namespace")
        resolved, actual_relative = _validate_registered_file(root_resolved, candidate)
        if actual_relative != relative or relative in seen:
            raise ValueError("manifest entry is unregistered or duplicated")
        seen.add(relative)
        if resolved.stat().st_size != expected_bytes or _sha256(resolved) != expected_sha:
            raise ValueError("registered file was modified")
        registered.append(resolved)
    all_files = sorted(seen)
    deleted: list[str] = []
    remaining = list(all_files)
    journal_payload: dict[str, object] = {
        "contract_version": "model_test_artifact_deletion_journal_v1",
        "manifest_path": str(resolved_manifest),
        "files": all_files,
        "deleted_files": deleted,
        "remaining_files": remaining,
        "status": "pending",
    }
    _atomic_json(journal, journal_payload)
    for file in registered:
        file.unlink()
        relative = file.relative_to(root_resolved).as_posix()
        deleted.append(relative)
        remaining.remove(relative)
        journal_payload["deleted_files"] = list(deleted)
        journal_payload["remaining_files"] = list(remaining)
        _atomic_json(journal, journal_payload)
    receipt = {"contract_version": "model_test_artifact_deletion_receipt_v1", "provider_id": payload["provider_id"], "revision": payload["revision"], "deleted_count": len(registered), "deleted_files": sorted(seen), "manifest_path": str(resolved_manifest), "verified": True}
    receipt_path = reports / f"{payload['provider_id']}-{payload['revision']}-deletion.json"
    _atomic_json(receipt_path, receipt)
    _atomic_json(journal, {**journal_payload, "status": "complete", "receipt_path": str(receipt_path)})
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def cleanup_failed_staging(*, root: Path, staging_path: Path) -> None:
    root_resolved, staging = _guard(Path(root), Path(staging_path))
    relative = staging.relative_to(root_resolved)
    if not relative.parts or relative.parts[0] != "staging":
        raise ValueError("staging target is outside the guarded staging directory")
    for path in sorted(_logical_files(staging), key=lambda item: len(item.parts), reverse=True):
        _guard(root_resolved, path)
        if path.is_file():
            path.unlink()
    for directory, _, _ in os.walk(staging, topdown=False, followlinks=False):
        current = Path(directory)
        _guard(root_resolved, current)
        current.rmdir()


def remove_huggingface_local_metadata(*, root: Path, staging_path: Path) -> None:
    """Remove only Hugging Face local-dir metadata after it was charged to quota."""
    root_resolved, staging = _guard(Path(root), Path(staging_path))
    metadata = staging / ".cache" / "huggingface"
    if not metadata.exists():
        return
    _guard(root_resolved, metadata)
    for path in sorted(_logical_files(metadata), key=lambda item: len(item.parts), reverse=True):
        _guard(root_resolved, path)
        if path.is_file():
            path.unlink()
    for directory, _, _ in os.walk(metadata, topdown=False, followlinks=False):
        current = Path(directory)
        _guard(root_resolved, current)
        current.rmdir()
    cache = staging / ".cache"
    if cache.exists() and not any(cache.iterdir()):
        cache.rmdir()


def materialize_downloaded_artifact(*, root: Path, provider_id: str, repo_id: str, revision: str, staging_path: Path, expected_files: Mapping[str, int], expected_sha256: Mapping[str, str]) -> Path:
    _safe_component(provider_id, name="provider_id")
    _immutable_revision(revision)
    root = Path(root)
    root_resolved, staging = _guard(root, Path(staging_path))
    if staging.relative_to(root_resolved).parts[:2] != ("staging", provider_id):
        raise ValueError("staging target is outside provider-specific staging")
    if not isinstance(expected_files, Mapping) or not expected_files or not isinstance(expected_sha256, Mapping):
        raise ValueError("expected files are invalid")
    actual = {path.relative_to(staging).as_posix(): path for path in _logical_files(staging) if path.is_file()}
    if set(actual) != set(expected_files) or set(expected_sha256) != set(expected_files) or any(not isinstance(name, str) or not isinstance(size, int) or size < 0 or actual[name].stat().st_size != size for name, size in expected_files.items()):
        raise ValueError("downloaded files do not match expected bytes")
    if any(not isinstance(expected_sha256[name], str) or len(expected_sha256[name]) != 64 or any(char not in "0123456789abcdef" for char in expected_sha256[name]) for name in expected_files):
        raise ValueError("downloaded files do not have closed SHA-256 expectations")
    # Rehash at the commit boundary, not only after the remote client returns.
    if any(_sha256(actual[name]) != expected_sha256[name] for name in expected_files):
        raise ValueError("downloaded files changed after verification")
    destination_parent = _guarded_directory(root_resolved, "artifacts", provider_id)
    destination = destination_parent / revision
    if destination.exists():
        raise ValueError("artifact destination already exists")
    if _is_reparse(destination_parent):
        raise ValueError("artifact destination parent is a reparse point")
    staging.rename(destination)
    try:
        return register_downloaded_artifact(root=root_resolved, provider_id=provider_id, repo_id=repo_id, revision=revision, files=sorted(actual_path for actual_path in destination.rglob("*") if actual_path.is_file()))
    except BaseException:
        if destination.exists() and not staging.exists():
            _guard(root_resolved, destination)
            destination.rename(staging)
        raise
