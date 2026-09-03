"""Explicit, lazy Hugging Face acquisition for bounded GoalBinding model tests."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
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
)


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


def fetch_profile(*, profile: dict[str, object], root: Path) -> Path:
    """Resolve and download only explicitly declared files; imported lazily on request."""
    provider_id, repo_id, requested = profile.get("provider_id"), profile.get("repo_id"), profile.get("artifact_files")
    if not isinstance(provider_id, str) or not isinstance(repo_id, str) or not isinstance(requested, list) or not requested or any(not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts for name in requested):
        raise ValueError("profile artifact declaration is invalid")
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError as exc:
        raise RuntimeError("huggingface_hub is required only for an explicit fetch") from exc
    api = HfApi()
    requested_revision = profile.get("revision", "main")
    info = api.model_info(repo_id, revision=requested_revision)
    revision = getattr(info, "sha", None)
    if not isinstance(revision, str) or len(revision) != 40:
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
        oid = lfs.get("oid") if isinstance(lfs, dict) else getattr(lfs, "oid", None)
        if isinstance(oid, str) and len(oid) == 64:
            expected_hashes[name] = oid
    assert_download_fits(root=root, remote_bytes=sum(expected.values()))
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    staging = root / "staging" / provider_id / revision
    if staging.exists():
        raise ValueError("provider-specific staging already exists")
    try:
        for name in requested:
            downloaded = Path(hf_hub_download(repo_id=repo_id, filename=name, revision=revision, local_dir=staging, local_dir_use_symlinks=False))
            target = staging / name
            if downloaded.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(downloaded.read_bytes())
            if target.stat().st_size != expected[name] or (name in expected_hashes and _digest(target) != expected_hashes[name]):
                raise ValueError(f"download verification failed for {name}")
        return materialize_downloaded_artifact(root=root, provider_id=provider_id, repo_id=repo_id, revision=revision, staging_path=staging, expected_files=expected)
    except BaseException:
        if staging.exists():
            cleanup_failed_staging(root=root, staging_path=staging)
        raise


def main(argv: list[str] | None = None) -> int:
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
    manifest = fetch_profile(profile=_profile(args.profile), root=args.root)
    print(json.dumps({"manifest_path": str(manifest), "artifact_is_authorization": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
