"""Explicit, lazy Hugging Face acquisition for bounded GoalBinding model tests."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha1, sha256
import json
import os
from pathlib import Path
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_PROFILE_DIRECTORY = _REPOSITORY_ROOT / "configs" / "model_profiles"
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from app.learn.hybrid.model_test_storage import (
    MODEL_TEST_ROOT,
    assert_download_fits,
    cleanup_failed_staging,
    inventory_storage,
    materialize_downloaded_artifact,
    remove_huggingface_local_metadata,
)
from app.learn.hybrid.model_test_storage import _immutable_revision, _safe_component
from app.learn.hybrid import model_test_storage as _storage


def _digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _profile(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("model profile is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError("model profile is invalid")
    return value


def _alias(profile: dict[str, object], primary: str, legacy: str) -> object:
    if primary in profile and legacy in profile and profile[primary] != profile[legacy]:
        raise ValueError(f"profile conflicts with checked-in identity: {primary}/{legacy}")
    return profile.get(primary, profile.get(legacy))


def _artifact_names(names: object) -> list[str]:
    if not isinstance(names, list):
        raise ValueError("profile artifact declaration is invalid")
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not name or "\\" in name:
            raise ValueError("unsafe checkpoint artifact path")
        parts = name.split("/")
        for part in parts:
            base = part.split(".", 1)[0].upper()
            if (not part or part in {".", ".."} or part.endswith((".", " "))
                    or any(ord(char) < 32 or char in '<>:"|?*' for char in part)
                    or base in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}):
                raise ValueError(f"unsafe checkpoint artifact path: {name}")
        folded = name.casefold()
        if parts[0].casefold() in {".cache", ".goal-binding-transaction.json"}:
            raise ValueError(f"unsafe checkpoint artifact path: {name}")
        if folded in seen:
            raise ValueError(f"duplicate checkpoint artifact path: {name}")
        seen.add(folded)
    for name in seen:
        parts = name.split("/")
        if any("/".join(parts[:index]) in seen for index in range(1, len(parts))):
            raise ValueError(f"checkpoint artifact path collision: {name}")
    return names


def project_profile(*, profile: dict[str, object] | None = None, provider_id: str | None = None,
                    repo_id: str | None = None, full_checkpoint: bool = False) -> dict[str, object]:
    """Project checked-in identities without importing a model client or writing storage."""
    canonical = [_profile(path) for path in sorted(_PROFILE_DIRECTORY.glob("*.json"))]
    canonical = [item for item in canonical if item.get("contract_version") == "goal_binding_model_profile_v1"]
    if profile is None:
        if provider_id is None and repo_id is None:
            raise ValueError("a profile or checked-in provider/repository selector is required")
        matches = [item for item in canonical if (provider_id is None or item.get("provider_id") == provider_id)
                   and (repo_id is None or item.get("repository_id") == repo_id)]
        if len(matches) != 1:
            raise ValueError("selectors must resolve a unique checked-in profile")
        profile = matches[0]
    provider = profile.get("provider_id")
    repository = _alias(profile, "repository_id", "repo_id")
    revision = _alias(profile, "upstream_revision", "revision")
    if (provider_id is not None and provider_id != provider) or (repo_id is not None and repo_id != repository):
        raise ValueError("selectors conflict with checked-in profile identity")
    if not isinstance(provider, str) or provider in {".", ".."} or not isinstance(repository, str) or not repository:
        raise ValueError("profile artifact declaration is invalid")
    _safe_component(provider, name="provider_id")
    matches = [item for item in canonical if item.get("provider_id") == provider or item.get("repository_id") == repository
               or (profile.get("profile_id") is not None and item.get("profile_id") == profile["profile_id"])]
    checkpoint = full_checkpoint or profile.get("full_checkpoint") is True
    if matches or profile.get("contract_version") == "goal_binding_model_profile_v1":
        matches = [item for item in matches if item.get("provider_id") == provider and item.get("repository_id") == repository]
        if len(matches) != 1:
            raise ValueError("profile must resolve a unique checked-in identity")
        selected = matches[0]
        if revision != selected.get("upstream_revision"):
            raise ValueError("profile revision does not match checked-in revision")
        if "profile_id" in profile and profile["profile_id"] != selected.get("profile_id"):
            raise ValueError("profile_id does not match checked-in identity")
        _immutable_revision(revision)
        checkpoint = checkpoint or selected.get("runtime", {}).get("kind") != "llama_cpp"
        requested = []
        if not checkpoint:
            for artifact in selected.get("artifacts", []):
                if artifact.get("role") not in {"model", "mmproj"}:
                    continue
                parts = artifact.get("relative_path", "").split("/", 3)
                if len(parts) != 4 or parts[:2] != ["artifacts", provider] or parts[2] not in {"not_acquired", revision}:
                    raise ValueError("checked-in artifact path is invalid")
                requested.append(parts[3])
    else:
        if provider_id is not None or repo_id is not None or "repository_id" in profile or "upstream_revision" in profile:
            raise ValueError("profile must resolve a unique checked-in identity")
        # 旧的独立文件声明保留显式解析分支；规范档案绝不回退到 main。
        revision = profile.get("revision", "main")
        requested = profile.get("artifact_files", [])
        if checkpoint:
            _immutable_revision(revision)
    requested = _artifact_names(requested)
    if not checkpoint and not requested:
        raise ValueError("profile artifact declaration is invalid")
    if not isinstance(revision, str) or not revision:
        raise ValueError("profile revision is invalid")
    return {"provider_id": provider, "repo_id": repository, "revision": revision,
            "artifact_files": requested, "full_checkpoint": checkpoint}


def _field(value: object, name: str) -> object:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _hex_digest(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(char in "0123456789abcdef" for char in value)


def _git_blob_digest(path: Path, size: int) -> str:
    value = sha1(b"blob " + str(size).encode("ascii") + b"\0")
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _same_production_root(root: Path) -> bool:
    """Compare lexical absolute paths without creating or resolving the target."""
    return os.path.normcase(os.path.normpath(os.path.abspath(str(root)))) == os.path.normcase(os.path.normpath(os.path.abspath(str(MODEL_TEST_ROOT))))


def _reject_reparse_root(root: Path) -> None:
    """Do not create a quota lock through a pre-existing reparse point."""
    candidate = Path(root).absolute()
    for parent in (candidate, *candidate.parents):
        if not parent.exists():
            continue
        info = parent.lstat()
        if parent.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400):
            raise ValueError("model-test root contains a reparse point")


@contextmanager
def _quota_reservation(root: Path):
    _reject_reparse_root(root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".goal-binding-quota.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("another model acquisition holds the root quota reservation") from exc
            locked = True
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("another model acquisition holds the root quota reservation") from exc
            locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _transaction_marker(*, provider_id: str, repo_id: str, revision: str) -> dict[str, str]:
    return {"contract_version": "goal_binding_model_download_transaction_v1", "provider_id": provider_id, "repo_id": repo_id, "revision": revision}


def _recover_or_create_staging(*, root: Path, provider_id: str, repo_id: str, revision: str) -> Path:
    staging = root / "staging" / provider_id / revision
    marker = staging / ".goal-binding-transaction.json"
    expected_marker = _transaction_marker(provider_id=provider_id, repo_id=repo_id, revision=revision)
    if staging.exists():
        _storage._guard(root, staging)
        _storage._guard(root, marker)
        try:
            actual_marker = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("abandoned staging has no valid transaction marker") from exc
        if actual_marker != expected_marker:
            raise ValueError("abandoned staging transaction marker does not match the requested artifact")
        cleanup_failed_staging(root=root, staging_path=staging)
    staging = _storage._guarded_directory(root, "staging", provider_id, revision)
    _storage._atomic_json(staging / ".goal-binding-transaction.json", expected_marker)
    return staging


def _configure_xet(root: Path) -> Path:
    xet_cache = root / ".cache" / "huggingface" / "xet"
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["HF_XET_CACHE"] = str(xet_cache)
    return xet_cache


def _pin_imported_hub_xet(module: object, xet_cache: Path) -> None:
    """Override constants too when a host imported huggingface_hub before this script."""
    constants = getattr(module, "constants", None)
    if constants is not None:
        if hasattr(constants, "HF_HUB_DISABLE_XET"):
            setattr(constants, "HF_HUB_DISABLE_XET", True)
        if hasattr(constants, "HF_XET_CACHE"):
            setattr(constants, "HF_XET_CACHE", str(xet_cache))


def fetch_profile(*, profile: dict[str, object], root: Path, full_checkpoint: bool = False) -> Path:
    """Resolve and download only explicitly declared files; imported lazily on request."""
    if not _same_production_root(Path(root)):
        raise ValueError("production acquisition is pinned to E:\\模型测试; injected roots are test-only library primitives")
    profile = project_profile(profile=profile, full_checkpoint=full_checkpoint)
    provider_id, repo_id, requested = profile["provider_id"], profile["repo_id"], profile["artifact_files"]
    root = _storage._require_model_test_root(Path(root))
    _reject_reparse_root(root)
    xet_cache = _configure_xet(root)
    try:
        import huggingface_hub
        _pin_imported_hub_xet(huggingface_hub, xet_cache)
        HfApi, hf_hub_download = huggingface_hub.HfApi, huggingface_hub.hf_hub_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required only for an explicit fetch") from exc
    api = HfApi(endpoint="https://huggingface.co")
    requested_revision = profile["revision"]
    info = api.model_info(repo_id, revision=requested_revision, files_metadata=True)
    revision = getattr(info, "sha", None)
    try:
        _immutable_revision(revision)
    except ValueError as exc:
        raise ValueError("Hugging Face did not resolve an immutable lowercase commit") from exc
    if not isinstance(revision, str):
        raise ValueError("Hugging Face did not resolve an immutable commit")
    if _hex_digest(requested_revision, 40) and revision != requested_revision:
        raise ValueError("Hugging Face resolved revision does not match the requested immutable revision")
    sibling_items = list(getattr(info, "siblings", ()) or ())
    names = _artifact_names([_field(item, "rfilename") for item in sibling_items])
    siblings = dict(zip(names, sibling_items))
    if profile["full_checkpoint"]:
        requested = names
        if not requested:
            raise ValueError("Hugging Face checkpoint metadata is empty")
    expected: dict[str, int] = {}
    expected_hashes: dict[str, str] = {}
    remote_hashes: dict[str, str] = {}
    blob_hashes: dict[str, str] = {}
    for name in requested:
        sibling = siblings.get(name)
        size = _field(sibling, "size")
        lfs = _field(sibling, "lfs")
        if size is None:
            size = _field(lfs, "size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f"Hugging Face size is unavailable for {name}")
        expected[name] = size
        if lfs is not None:
            oid = _field(lfs, "sha256") or _field(lfs, "oid")
            if not _hex_digest(oid, 64):
                raise ValueError(f"Hugging Face SHA-256 is unavailable for {name}")
            remote_hashes[name] = oid
        else:
            blob = _field(sibling, "blob_id") or _field(sibling, "blobId")
            if blob is not None:
                if not _hex_digest(blob, 40):
                    raise ValueError(f"Hugging Face Git blob hash is invalid for {name}")
                blob_hashes[name] = blob
    with _quota_reservation(root):
        _storage._guarded_directory(root, ".cache", "huggingface", "xet")
        assert_download_fits(root=root, remote_bytes=sum(expected.values()))
        staging = _recover_or_create_staging(root=root, provider_id=provider_id, repo_id=repo_id, revision=revision)
        try:
            for name in requested:
                downloaded = Path(hf_hub_download(repo_id=repo_id, filename=name, revision=revision, local_dir=staging, endpoint="https://huggingface.co"))
                target = staging / name
                if downloaded.resolve() != target.resolve():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(downloaded.read_bytes())
                _storage._guard(root, target)
                digest = _digest(target)
                if (target.stat().st_size != expected[name]
                        or (name in remote_hashes and digest != remote_hashes[name])
                        or (name in blob_hashes and _git_blob_digest(target, expected[name]) != blob_hashes[name])):
                    raise ValueError(f"download verification failed for {name}")
                expected_hashes[name] = digest
            remove_huggingface_local_metadata(root=root, staging_path=staging)
            marker = staging / ".goal-binding-transaction.json"
            marker.unlink()
            return materialize_downloaded_artifact(root=root, provider_id=provider_id, repo_id=repo_id, revision=revision, staging_path=staging, expected_files=expected, expected_sha256=expected_hashes)
        except BaseException:
            if staging.exists():
                cleanup_failed_staging(root=root, staging_path=staging)
            raise


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Fetch a bounded, immutable GoalBinding model artifact.")
    parser.add_argument("--root", type=Path, default=MODEL_TEST_ROOT)
    parser.add_argument("--inventory-only", action="store_true", help="Print logical storage usage without network or writes.")
    parser.add_argument("--profile", type=Path, help="Explicit JSON profile required for network acquisition.")
    parser.add_argument("--provider-id", help="Select a unique checked-in provider identity.")
    parser.add_argument("--repo-id", help="Select or verify the exact checked-in repository identity.")
    parser.add_argument("--full-checkpoint", action="store_true", help="Fetch every file in pinned checkpoint metadata.")
    args = parser.parse_args(argv)
    if args.inventory_only:
        print(json.dumps(inventory_storage(args.root), ensure_ascii=False, sort_keys=True))
        return 0
    try:
        profile = project_profile(profile=_profile(args.profile) if args.profile is not None else None,
                                  provider_id=args.provider_id, repo_id=args.repo_id, full_checkpoint=args.full_checkpoint)
    except ValueError as exc:
        parser.error(str(exc))
    if not _same_production_root(args.root):
        parser.error("production acquisition is pinned to E:\\模型测试; --root is inventory-only")
    manifest = fetch_profile(profile=profile, root=args.root)
    print(json.dumps({"manifest_path": str(manifest), "artifact_is_authorization": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
