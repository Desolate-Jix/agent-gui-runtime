from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterable


CONTRACT_VERSION = "application_learning_history_cleanup_plan_v1"
REPORT_CONTRACT_VERSION = "application_learning_history_cleanup_report_v1"
PROTECTED_ROOTS = (
    "artifacts/benchmarks",
    "artifacts/learning-correction-memory",
    "tests/fixtures",
)
ALLOWED_DELETE_ROOTS = (
    "artifacts/interface-assets",
    "artifacts/interface-workflow-reviews",
    "artifacts/agent-memory/objects",
    "artifacts/agent-memory/execution-feedback",
    "artifacts/learning-runs",
    "artifacts/manual-runtime-validation",
    "artifacts/learning-draft-review",
)


def build_application_history_cleanup_plan(
    *,
    project_root: str | Path,
    application_identity_keys: set[str],
    interface_id_prefixes: tuple[str, ...],
    learning_run_name_tokens: tuple[str, ...],
) -> dict[str, Any]:
    """生成只删除指定应用学习历史的审计计划。"""

    root = Path(project_root).resolve()
    identity_keys = {
        str(value).strip().casefold()
        for value in application_identity_keys
        if str(value).strip()
    }
    prefixes = tuple(
        str(value).strip().casefold()
        for value in interface_id_prefixes
        if str(value).strip()
    )
    run_tokens = tuple(
        str(value).strip().casefold()
        for value in learning_run_name_tokens
        if str(value).strip()
    )
    if not identity_keys and not prefixes and not run_tokens:
        raise ValueError("cleanup selector is empty")

    delete_paths: set[str] = set()
    registry_updates: dict[str, dict[str, Any]] = {}
    removed_workflow_ids: list[str] = []
    removed_interface_ids: list[str] = []

    _collect_interface_asset_paths(
        root=root,
        identity_keys=identity_keys,
        delete_paths=delete_paths,
    )
    removed_workflow_ids.extend(
        _collect_workflow_history(
            root=root,
            identity_keys=identity_keys,
            delete_paths=delete_paths,
            registry_updates=registry_updates,
        )
    )
    removed_interface_ids.extend(
        _collect_agent_memory_history(
            root=root,
            interface_prefixes=prefixes,
            delete_paths=delete_paths,
            registry_updates=registry_updates,
        )
    )
    _collect_learning_run_paths(
        root=root,
        run_tokens=run_tokens,
        delete_paths=delete_paths,
    )
    _validate_delete_paths(root, delete_paths)

    return {
        "contract_version": CONTRACT_VERSION,
        "mode": "dry_run",
        "project_root": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "selectors": {
            "application_identity_keys": sorted(identity_keys),
            "interface_id_prefixes": list(prefixes),
            "learning_run_name_tokens": list(run_tokens),
        },
        "delete_paths": sorted(delete_paths),
        "registry_updates": registry_updates,
        "removed_workflow_ids": sorted(set(removed_workflow_ids)),
        "removed_interface_ids": sorted(set(removed_interface_ids)),
        "protected_roots": list(PROTECTED_ROOTS),
        "class_rules_preserved": True,
        "benchmark_and_fixtures_preserved": True,
    }


def apply_application_history_cleanup_plan(
    plan: dict[str, Any],
    *,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """原子更新索引后应用已审计的删除计划。"""

    if plan.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("invalid application history cleanup plan")
    root = Path(str(plan.get("project_root") or "")).resolve()
    delete_paths = [
        str(value).replace("\\", "/").strip("/")
        for value in plan.get("delete_paths") or []
    ]
    _validate_delete_paths(root, delete_paths)

    registry_updates = plan.get("registry_updates")
    if not isinstance(registry_updates, dict):
        raise ValueError("cleanup plan registry updates are invalid")
    for relative_path, payload in registry_updates.items():
        target = _resolve_inside_root(root, relative_path)
        _atomic_write_json(target, payload)

    deleted: list[str] = []
    missing: list[str] = []
    for relative_path in delete_paths:
        target = _resolve_inside_root(root, relative_path)
        if not target.exists():
            missing.append(relative_path)
            continue
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        deleted.append(relative_path)

    report = {
        "contract_version": REPORT_CONTRACT_VERSION,
        "status": "applied",
        "project_root": str(root),
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "deleted_paths": deleted,
        "missing_paths": missing,
        "removed_workflow_ids": list(plan.get("removed_workflow_ids") or []),
        "removed_interface_ids": list(plan.get("removed_interface_ids") or []),
        "protected_roots": list(PROTECTED_ROOTS),
        "class_rules_preserved": True,
        "benchmark_and_fixtures_preserved": True,
    }
    if report_path is not None:
        resolved_report = _resolve_inside_root(root, report_path)
        _atomic_write_json(resolved_report, report)
        report["report_path"] = _relative(resolved_report, root)
    return report


def _collect_interface_asset_paths(
    *,
    root: Path,
    identity_keys: set[str],
    delete_paths: set[str],
) -> None:
    assets_root = root / "artifacts/interface-assets"
    if not assets_root.is_dir():
        return
    for registry_path in assets_root.glob("*/registry.json"):
        payload = _read_json(registry_path)
        identity_key = str(
            payload.get("application_identity_key")
            or (payload.get("application_identity") or {}).get("identity_key")
            or ""
        ).casefold()
        if identity_key in identity_keys:
            delete_paths.add(_relative(registry_path.parent, root))


def _collect_workflow_history(
    *,
    root: Path,
    identity_keys: set[str],
    delete_paths: set[str],
    registry_updates: dict[str, dict[str, Any]],
) -> list[str]:
    registry_path = root / "artifacts/interface-workflow-reviews/registry.json"
    if not registry_path.is_file():
        return []
    registry = _read_json(registry_path)
    applications = registry.get("applications")
    workflows = registry.get("workflows")
    applications = applications if isinstance(applications, dict) else {}
    workflows = workflows if isinstance(workflows, dict) else {}
    removed_ids = [
        workflow_id
        for workflow_id, record in workflows.items()
        if isinstance(record, dict)
        and str(record.get("application_identity_key") or "").casefold()
        in identity_keys
    ]
    next_registry = deepcopy(registry)
    next_registry["applications"] = {
        key: value
        for key, value in applications.items()
        if str(key).casefold() not in identity_keys
    }
    next_registry["workflows"] = {
        key: value for key, value in workflows.items() if key not in removed_ids
    }
    if removed_ids:
        next_registry["registry_revision"] = int(
            next_registry.get("registry_revision") or 0
        ) + 1
        registry_updates[_relative(registry_path, root)] = next_registry
    for workflow_id in removed_ids:
        record = workflows[workflow_id]
        workflow_path = _resolve_declared_path(root, record.get("path"))
        if workflow_path is not None:
            delete_paths.add(_relative(workflow_path.parent, root))
    return removed_ids


def _collect_agent_memory_history(
    *,
    root: Path,
    interface_prefixes: tuple[str, ...],
    delete_paths: set[str],
    registry_updates: dict[str, dict[str, Any]],
) -> list[str]:
    registry_path = root / "artifacts/agent-memory/registry.json"
    if not registry_path.is_file():
        return []
    registry = _read_json(registry_path)
    active = registry.get("active_by_interface")
    objects = registry.get("objects")
    events = registry.get("events")
    active = active if isinstance(active, dict) else {}
    objects = objects if isinstance(objects, dict) else {}
    events = events if isinstance(events, list) else []
    removed_ids = [
        interface_id
        for interface_id in active
        if _has_prefix(interface_id, interface_prefixes)
    ]
    removed_objects = {
        object_sha256: record
        for object_sha256, record in objects.items()
        if isinstance(record, dict)
        and str(record.get("interface_id") or "") in removed_ids
    }
    kept_sources = {
        str(record.get("source_candidate_path") or "")
        for object_sha256, record in objects.items()
        if object_sha256 not in removed_objects and isinstance(record, dict)
    }
    next_registry = deepcopy(registry)
    next_registry["active_by_interface"] = {
        key: value for key, value in active.items() if key not in removed_ids
    }
    next_registry["objects"] = {
        key: value for key, value in objects.items() if key not in removed_objects
    }
    next_registry["events"] = [
        event
        for event in events
        if not isinstance(event, dict)
        or str(event.get("interface_id") or "") not in removed_ids
    ]
    if removed_ids:
        next_registry["registry_revision"] = int(
            next_registry.get("registry_revision") or 0
        ) + 1
        registry_updates[_relative(registry_path, root)] = next_registry
    for record in removed_objects.values():
        object_path = _resolve_declared_path(root, record.get("object_path"))
        if object_path is not None:
            delete_paths.add(_relative(object_path, root))
        source_value = str(record.get("source_candidate_path") or "")
        if source_value and source_value not in kept_sources:
            source_path = _resolve_declared_path(root, source_value)
            if source_path is not None:
                delete_paths.add(_relative(source_path, root))
    for interface_id in removed_ids:
        feedback_path = (
            root / "artifacts/agent-memory/execution-feedback" / interface_id
        )
        if feedback_path.exists():
            delete_paths.add(_relative(feedback_path, root))
    return removed_ids


def _collect_learning_run_paths(
    *,
    root: Path,
    run_tokens: tuple[str, ...],
    delete_paths: set[str],
) -> None:
    runs_root = root / "artifacts/learning-runs"
    if not runs_root.is_dir():
        return
    for path in runs_root.iterdir():
        name = path.name.casefold()
        if any(token in name for token in run_tokens):
            delete_paths.add(_relative(path, root))


def _validate_delete_paths(root: Path, paths: Iterable[str]) -> None:
    allowed_roots = [_resolve_inside_root(root, value) for value in ALLOWED_DELETE_ROOTS]
    protected_roots = [_resolve_inside_root(root, value) for value in PROTECTED_ROOTS]
    for value in paths:
        target = _resolve_inside_root(root, value)
        if any(target == protected or protected in target.parents for protected in protected_roots):
            raise ValueError(f"cleanup path is protected: {value}")
        if not any(target == allowed or allowed in target.parents for allowed in allowed_roots):
            raise ValueError(f"cleanup path is outside allowed roots: {value}")


def _resolve_declared_path(root: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _resolve_inside_root(root: Path, value: str | Path) -> Path:
    path = Path(value)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"cleanup path is outside project root: {value}")
    return resolved


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _has_prefix(value: str, prefixes: tuple[str, ...]) -> bool:
    normalized = str(value or "").casefold()
    return any(normalized.startswith(prefix) for prefix in prefixes)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
