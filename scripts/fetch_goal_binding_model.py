"""Explicit, lazy Hugging Face acquisition for bounded GoalBinding model tests."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
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
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("another model acquisition holds the root quota reservation") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("reserved\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        if lock.exists():
            lock.unlink()


def fetch_profile(*, profile: dict[str, object], root: Path) -> Path:
    """Resolve and download only explicitly declared files; imported lazily on request."""
    if not _same_production_root(Path(root)):
        raise ValueError("production acquisition is pinned to E:\\模型测试; injected roots are test-only library primitives")
    provider_id, repo_id, requested = profile.get("provider_id"), profile.get("repo_id"), profile.get("artifact_files")
    if not isinstance(provider_id, str) or not isinstance(repo_id, str) or not isinstance(requested, list) or not requested or any(not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts for name in requested):
        raise ValueError("profile artifact declaration is invalid")
    _safe_component(provider_id, name="provider_id")
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required only for an explicit fetch") from exc
    api = HfApi(endpoint="https://huggingface.co")
    requested_revision = profile.get("revision", "main")
    info = api.model_info(repo_id, revision=requested_revision, files_metadata=True)
    revision = getattr(info, "sha", None)
    try:
        _immutable_revision(revision)
    except ValueError as exc:
        raise ValueError("Hugging Face did not resolve an immutable lowercase commit") from exc
    if not isinstance(revision, str):
        raise ValueError("Hugging Face did not resolve an immutable commit")
    siblings = {getattr(item, "rfilename", None): item for item in getattr(info, "siblings", ())}
    expected: dict[str, int] = {}
    expected_hashes: dict[str, str] = {}
    for name in requested:
        sibling = siblings.get(name)
        size = getattr(sibling, "size", None)
        lfs = getattr(sibling, "lfs", None)
        if not isinstance(size, int) and isinstance(lfs, dict):
            size = lfs.get("size")
        if not isinstance(size, int) or size < 0:
            raise ValueError(f"Hugging Face size is unavailable for {name}")
        expected[name] = size
        oid = (lfs.get("sha256") or lfs.get("oid")) if isinstance(lfs, dict) else (getattr(lfs, "sha256", None) or getattr(lfs, "oid", None))
        if not isinstance(oid, str) or len(oid) != 64 or any(char not in "0123456789abcdef" for char in oid):
            raise ValueError(f"Hugging Face SHA-256 is unavailable for {name}")
        expected_hashes[name] = oid
    root = Path(root)
    with _quota_reservation(root):
        assert_download_fits(root=root, remote_bytes=sum(expected.values()))
        staging = root / "staging" / provider_id / revision
        if staging.exists():
            raise ValueError("provider-specific staging already exists")
        try:
            for name in requested:
                downloaded = Path(hf_hub_download(repo_id=repo_id, filename=name, revision=revision, local_dir=staging, endpoint="https://huggingface.co"))
                target = staging / name
                if downloaded.resolve() != target.resolve():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(downloaded.read_bytes())
                if target.stat().st_size != expected[name] or (name in expected_hashes and _digest(target) != expected_hashes[name]):
                    raise ValueError(f"download verification failed for {name}")
            remove_huggingface_local_metadata(root=root, staging_path=staging)
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
    args = parser.parse_args(argv)
    if args.inventory_only:
        print(json.dumps(inventory_storage(args.root), ensure_ascii=False, sort_keys=True))
        return 0
    if args.profile is None:
        parser.error("--profile is required unless --inventory-only is used")
    if not _same_production_root(args.root):
        parser.error("production acquisition is pinned to E:\\模型测试; --root is inventory-only")
    manifest = fetch_profile(profile=_profile(args.profile), root=args.root)
    print(json.dumps({"manifest_path": str(manifest), "artifact_is_authorization": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
