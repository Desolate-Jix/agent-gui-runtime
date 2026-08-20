from __future__ import annotations

import json
import re
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


CONTRACT_VERSION = "runtime_storage_cleanup_plan_v1"
DEFAULT_TARGET_ROOTS = (
    "logs/tmp",
    "artifacts/review-overlays",
)
PROTECTED_RUNTIME_ROOTS = (
    "logs/traces",
    "artifacts/learning-runs",
)
REFERENCE_ROOTS = (
    "app",
    "configs",
    "docs",
    "scripts",
    "tests",
    "logs/traces",
    "artifacts/benchmarks",
    "artifacts/golden-traces",
    "artifacts/interface-workflow-reviews",
    "artifacts/learning-runs",
    "runtime_state",
)
TEXT_SUFFIXES = {
    ".bat",
    ".cjs",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
PATH_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/])?(?:artifacts|logs)[\\/][A-Za-z0-9_.\-/\\=]+)"
)


def build_cleanup_plan(
    *,
    root: Path,
    older_than_days: int = 14,
    keep_latest_per_directory: int = 3,
    now: datetime | None = None,
    target_roots: Iterable[str] = DEFAULT_TARGET_ROOTS,
) -> dict[str, Any]:
    if older_than_days < 1:
        raise ValueError("older_than_days must be at least 1")
    if keep_latest_per_directory < 0:
        raise ValueError("keep_latest_per_directory cannot be negative")

    project_root = root.resolve()
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    cutoff = current_time - timedelta(days=older_than_days)
    normalized_targets = _validated_target_roots(project_root, target_roots)

    old_files: dict[str, Path] = {}
    retained_text_files: set[Path] = set()
    latest_protected: set[str] = set()
    scan_errors: list[dict[str, str]] = []

    for target in normalized_targets:
        files = [
            path
            for path in target.rglob("*")
            if path.is_file() and not path.is_symlink()
        ]
        for path in files:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            relative = _relative(path, project_root)
            if modified < cutoff:
                old_files[relative] = path

        if keep_latest_per_directory:
            ordered = sorted(files, key=lambda item: item.stat().st_mtime_ns, reverse=True)
            for path in ordered[:keep_latest_per_directory]:
                relative = _relative(path, project_root)
                if relative in old_files:
                    latest_protected.add(relative)
                if path.suffix.lower() in TEXT_SUFFIXES:
                    retained_text_files.add(path)

    candidates = set(old_files) - latest_protected
    reference_files = set(_iter_reference_files(project_root))
    reference_files.update(retained_text_files)
    referenced = _collect_protected_candidate_paths(
        project_root=project_root,
        candidate_paths=candidates,
        reference_files=reference_files,
        scan_errors=scan_errors,
    )
    protected = latest_protected | referenced
    delete_paths = sorted(candidates - protected)
    delete_candidates = []
    for relative in delete_paths:
        path = old_files[relative]
        stat = path.stat()
        delete_candidates.append(
            {
                "relative_path": relative,
                "size_bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )

    return {
        "contract_version": CONTRACT_VERSION,
        "mode": "dry_run",
        "root": str(project_root),
        "generated_at": current_time.isoformat(),
        "older_than_days": older_than_days,
        "cutoff": cutoff.isoformat(),
        "keep_latest_per_directory": keep_latest_per_directory,
        "keep_latest_scope": "per_target_root",
        "target_roots": [_relative(path, project_root) for path in normalized_targets],
        "delete_candidates": delete_candidates,
        "candidate_files": len(delete_candidates),
        "candidate_bytes": sum(item["size_bytes"] for item in delete_candidates),
        "protected_paths": sorted(protected),
        "protected_files": len(protected),
        "reference_scan_errors": scan_errors,
    }


def apply_cleanup_plan(
    plan: dict[str, Any],
    *,
    report_path: Path | None = None,
) -> dict[str, Any]:
    if plan.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("unsupported cleanup plan contract")
    project_root = Path(str(plan.get("root") or "")).resolve()
    allowed_roots = _validated_target_roots(project_root, plan.get("target_roots") or ())
    deleted_files = 0
    deleted_bytes = 0
    removed_directories = 0
    skipped: list[dict[str, str]] = []

    for item in plan.get("delete_candidates") or []:
        relative = str(item.get("relative_path") or "")
        path = (project_root / relative).resolve()
        if not _is_within(path, project_root) or not any(_is_within(path, root) for root in allowed_roots):
            raise ValueError(f"cleanup candidate escapes allowed roots: {relative}")
        if not path.exists():
            skipped.append({"relative_path": relative, "reason": "already_missing"})
            continue
        if path.is_symlink() or not path.is_file():
            skipped.append({"relative_path": relative, "reason": "not_regular_file"})
            continue
        stat = path.stat()
        if stat.st_size != int(item.get("size_bytes") or -1) or stat.st_mtime_ns != int(
            item.get("mtime_ns") or -1
        ):
            skipped.append({"relative_path": relative, "reason": "changed_after_plan"})
            continue
        path.unlink()
        deleted_files += 1
        deleted_bytes += stat.st_size

    for allowed_root in allowed_roots:
        if not allowed_root.exists():
            continue
        directories = sorted(
            (
                path
                for path in allowed_root.rglob("*")
                if path.is_dir() and not path.is_symlink()
            ),
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in directories:
            try:
                directory.rmdir()
            except OSError:
                continue
            removed_directories += 1

    report = {
        "contract_version": "runtime_storage_cleanup_report_v1",
        "status": "applied",
        "root": str(project_root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "older_than_days": plan.get("older_than_days"),
        "target_roots": plan.get("target_roots"),
        "planned_files": len(plan.get("delete_candidates") or []),
        "planned_bytes": int(plan.get("candidate_bytes") or 0),
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "removed_directories": removed_directories,
        "skipped": skipped,
        "protected_files": int(plan.get("protected_files") or 0),
    }
    if report_path is not None:
        destination = report_path.resolve()
        if not _is_within(destination, project_root):
            raise ValueError("cleanup report path must remain inside the project root")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def _validated_target_roots(project_root: Path, target_roots: Iterable[str]) -> list[Path]:
    validated: list[Path] = []
    protected_roots = [
        (project_root / relative).resolve() for relative in PROTECTED_RUNTIME_ROOTS
    ]
    for relative in target_roots:
        candidate = (project_root / str(relative)).resolve()
        if not _is_within(candidate, project_root):
            raise ValueError(f"cleanup target escapes project root: {relative}")
        if candidate == project_root:
            raise ValueError("project root cannot be a cleanup target")
        if any(
            _is_within(candidate, protected) or _is_within(protected, candidate)
            for protected in protected_roots
        ):
            raise ValueError(f"protected cleanup root cannot be targeted: {relative}")
        validated.append(candidate)
    return validated


def _iter_reference_files(project_root: Path) -> Iterable[Path]:
    for path in project_root.iterdir():
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield path
    for relative in REFERENCE_ROOTS:
        base = project_root / relative
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in TEXT_SUFFIXES:
                yield path


def _collect_protected_candidate_paths(
    *,
    project_root: Path,
    candidate_paths: set[str],
    reference_files: Iterable[Path],
    scan_errors: list[dict[str, str]],
) -> set[str]:
    protected: set[str] = set()
    queue: deque[Path] = deque(reference_files)
    scanned: set[Path] = set()
    while queue:
        source = queue.popleft()
        resolved_source = source.resolve()
        if resolved_source in scanned or not resolved_source.exists():
            continue
        scanned.add(resolved_source)
        try:
            references = _extract_references(resolved_source, project_root)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            scan_errors.append(
                {
                    "path": _relative(resolved_source, project_root),
                    "error": str(exc),
                }
            )
            continue
        for relative in references:
            if relative not in candidate_paths or relative in protected:
                continue
            protected.add(relative)
            candidate = project_root / relative
            if candidate.suffix.lower() in TEXT_SUFFIXES:
                queue.append(candidate)
    return protected


def _extract_references(path: Path, project_root: Path) -> set[str]:
    text = path.read_text(encoding="utf-8-sig")
    references: set[str] = set()
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
        for value in _iter_strings(payload):
            normalized = _normalize_reference(value, project_root)
            if normalized:
                references.add(normalized)
        return references

    normalized_text = text.replace("\\\\", "\\")
    for match in PATH_PATTERN.finditer(normalized_text):
        normalized = _normalize_reference(match.group("path"), project_root)
        if normalized:
            references.add(normalized)
    return references


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_strings(child)
    elif isinstance(value, str):
        yield value


def _normalize_reference(value: str, project_root: Path) -> str | None:
    raw = value.strip().strip("`'\"()[]{}.,;")
    if not raw:
        return None
    candidate = Path(raw.replace("/", "\\"))
    if not candidate.is_absolute():
        if not raw.lower().startswith(("artifacts/", "artifacts\\", "logs/", "logs\\")):
            return None
        candidate = project_root / candidate
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not _is_within(resolved, project_root):
        return None
    return _relative(resolved, project_root)


def _relative(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.resolve().relative_to(project_root).as_posix()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
