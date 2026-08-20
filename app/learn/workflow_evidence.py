from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.learn.workflow_state import LEARNING_WORKFLOW_COMPLETION_EVIDENCE


EVIDENCE_INTEGRITY_CONTRACT_VERSION = "learning_workflow_evidence_integrity_v1"
WORKFLOW_LINEAGE_CONTRACT_VERSION = "learning_workflow_lineage_v1"
_ALLOWED_RUNTIME_ROOT_NAMES = ("artifacts", "logs")
_CAPTURE_HASH_FIELDS = ("capture_sha256", "source_image_sha256", "screenshot_sha256")
_CAPTURE_PATH_FIELDS = ("source_image_path", "screenshot_path")
_NUMBERING_REPORT_HASH_FIELD = "numbering_report_sha256"
_REVISION_FIELDS = (
    "source_graph_revision",
    "reviewed_graph_revision",
    "final_numbering_revision",
)


class LearningWorkflowEvidenceError(ValueError):
    """学习工作流产物证据无法在本地可信复盘。"""


def verify_learning_workflow_completion_evidence(
    *,
    stage: str,
    outcome: str,
    evidence_refs: dict[str, Any] | None,
    project_root: str | Path,
    previous_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """验证完成阶段引用的本地产物，并附加文件摘要与跨阶段身份链。"""

    verified_refs = deepcopy(evidence_refs) if isinstance(evidence_refs, dict) else {}
    if outcome != "completed":
        return verified_refs

    required_fields = LEARNING_WORKFLOW_COMPLETION_EVIDENCE.get(stage)
    if required_fields is None:
        raise LearningWorkflowEvidenceError(f"unknown learning workflow stage: {stage}")

    root = Path(project_root).resolve()
    allowed_roots = tuple((root / name).resolve() for name in _ALLOWED_RUNTIME_ROOT_NAMES)
    verified_artifacts: dict[str, dict[str, Any]] = {}
    resolved_artifacts: dict[str, Path] = {}
    for field in required_fields:
        path_value = verified_refs.get(field)
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        resolved = _resolve_evidence_path(
            path_value,
            project_root=root,
            allowed_roots=allowed_roots,
        )
        sha256 = _sha256_file(resolved)
        expected_sha256 = _expected_sha256(verified_refs, field)
        if expected_sha256 and expected_sha256.casefold() != sha256:
            raise LearningWorkflowEvidenceError(
                f"workflow evidence checksum mismatch for {field}: "
                f"expected {expected_sha256}, actual {sha256}"
            )
        verified_artifacts[field] = {
            "relative_path": resolved.relative_to(root).as_posix(),
            "sha256": sha256,
            "size_bytes": resolved.stat().st_size,
        }
        resolved_artifacts[field] = resolved

    verified_refs["evidence_integrity"] = {
        "contract_version": EVIDENCE_INTEGRITY_CONTRACT_VERSION,
        "verified": len(verified_artifacts) == len(required_fields),
        "allowed_runtime_roots": list(_ALLOWED_RUNTIME_ROOT_NAMES),
        "artifacts": verified_artifacts,
        "artifact_count": len(verified_artifacts),
    }
    verified_refs["workflow_lineage"] = _verify_workflow_lineage(
        stage=stage,
        resolved_artifacts=resolved_artifacts,
        verified_artifacts=verified_artifacts,
        previous_state=previous_state,
        project_root=root,
        allowed_roots=allowed_roots,
    )
    return verified_refs


def _verify_workflow_lineage(
    *,
    stage: str,
    resolved_artifacts: dict[str, Path],
    verified_artifacts: dict[str, dict[str, Any]],
    previous_state: dict[str, Any] | None,
    project_root: Path,
    allowed_roots: tuple[Path, ...],
) -> dict[str, Any]:
    previous_capture, previous_revisions = _previous_lineage(previous_state)
    previous_numbering_report = _previous_numbering_report_sha256(previous_state)
    artifact_fields_checked = list(resolved_artifacts)

    if stage == "bind_capture":
        image = verified_artifacts.get("image_path") or {}
        capture_sha256 = str(image.get("sha256") or "").strip().casefold()
        return {
            "contract_version": WORKFLOW_LINEAGE_CONTRACT_VERSION,
            "status": "anchor_established" if capture_sha256 else "not_covered",
            "capture_anchor_sha256": capture_sha256,
            "declared_capture_sha256": capture_sha256,
            "declared_capture_paths": [str(image.get("relative_path") or "")] if image else [],
            "declared_revisions": {},
            "artifact_fields_checked": artifact_fields_checked,
            "not_covered_reason": "" if capture_sha256 else "bind_capture_artifact_missing",
        }

    declared = _extract_artifact_lineage(
        resolved_artifacts,
        project_root=project_root,
        allowed_roots=allowed_roots,
    )
    declared_capture = str(declared.get("capture_sha256") or "").strip().casefold()
    if previous_capture and declared_capture and previous_capture != declared_capture:
        raise LearningWorkflowEvidenceError(
            "workflow capture lineage mismatch: "
            f"expected {previous_capture}, declared {declared_capture}"
        )

    declared_revisions = declared.get("revisions") if isinstance(declared.get("revisions"), dict) else {}
    for field in _REVISION_FIELDS:
        previous_value = str(previous_revisions.get(field) or "").strip()
        declared_value = str(declared_revisions.get(field) or "").strip()
        if previous_value and declared_value and previous_value != declared_value:
            raise LearningWorkflowEvidenceError(
                f"workflow {field} lineage mismatch: "
                f"expected {previous_value}, declared {declared_value}"
            )

    declared_numbering_report = str(
        declared.get("numbering_report_sha256") or ""
    ).strip().casefold()
    if (
        stage == "precise_calibration"
        and previous_numbering_report
        and declared_numbering_report != previous_numbering_report
    ):
        raise LearningWorkflowEvidenceError(
            "workflow numbering report lineage mismatch: "
            f"expected {previous_numbering_report}, declared {declared_numbering_report or 'missing'}"
        )

    if previous_capture and declared_capture:
        status = "verified"
        not_covered_reason = ""
    elif previous_capture:
        status = "not_covered"
        not_covered_reason = "artifact_did_not_declare_capture_identity"
    else:
        status = "not_covered"
        not_covered_reason = "bind_capture_lineage_anchor_missing"

    return {
        "contract_version": WORKFLOW_LINEAGE_CONTRACT_VERSION,
        "status": status,
        "capture_anchor_sha256": previous_capture,
        "declared_capture_sha256": declared_capture,
        "declared_capture_paths": declared.get("capture_paths") or [],
        "declared_revisions": declared_revisions,
        "source_numbering_report_sha256": declared_numbering_report,
        "artifact_fields_checked": artifact_fields_checked,
        "identity_sources": declared.get("identity_sources") or [],
        "not_covered_reason": not_covered_reason,
    }


def _extract_artifact_lineage(
    resolved_artifacts: dict[str, Path],
    *,
    project_root: Path,
    allowed_roots: tuple[Path, ...],
) -> dict[str, Any]:
    capture_hashes: set[str] = set()
    capture_paths: set[str] = set()
    revision_values: dict[str, set[str]] = {field: set() for field in _REVISION_FIELDS}
    numbering_report_hashes: set[str] = set()
    identity_sources: list[str] = []

    for field, path in resolved_artifacts.items():
        if path.suffix.casefold() != ".json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LearningWorkflowEvidenceError(
                f"workflow evidence JSON is invalid for {field}: {exc}"
            ) from exc
        collected = _collect_declared_lineage(payload)
        if any(collected.values()):
            identity_sources.append(field)
        capture_hashes.update(collected["capture_hashes"])
        capture_paths.update(collected["capture_paths"])
        numbering_report_hashes.update(collected["numbering_report_hashes"])
        for revision_field in _REVISION_FIELDS:
            revision_values[revision_field].update(collected["revisions"][revision_field])

    if len(capture_hashes) > 1:
        raise LearningWorkflowEvidenceError(
            "workflow artifact contains conflicting capture identities: "
            f"{sorted(capture_hashes)}"
        )
    for field, values in revision_values.items():
        if len(values) > 1:
            raise LearningWorkflowEvidenceError(
                f"workflow artifact contains conflicting {field} identities: {sorted(values)}"
            )
    if len(numbering_report_hashes) > 1:
        raise LearningWorkflowEvidenceError(
            "workflow artifact contains conflicting numbering report identities: "
            f"{sorted(numbering_report_hashes)}"
        )

    resolved_capture_hashes: set[str] = set()
    normalized_capture_paths: list[str] = []
    for path_value in sorted(capture_paths):
        resolved = _resolve_evidence_path(
            path_value,
            project_root=project_root,
            allowed_roots=allowed_roots,
        )
        resolved_capture_hashes.add(_sha256_file(resolved))
        normalized_capture_paths.append(resolved.relative_to(project_root).as_posix())
    if len(resolved_capture_hashes) > 1:
        raise LearningWorkflowEvidenceError(
            "workflow artifact declares multiple different source screenshots"
        )
    if capture_hashes and resolved_capture_hashes and capture_hashes != resolved_capture_hashes:
        raise LearningWorkflowEvidenceError(
            "workflow artifact capture hash does not match its declared source screenshot"
        )

    declared_capture = next(iter(capture_hashes or resolved_capture_hashes), "")
    return {
        "capture_sha256": declared_capture,
        "capture_paths": normalized_capture_paths,
        "revisions": {
            field: next(iter(values), "")
            for field, values in revision_values.items()
            if values
        },
        "numbering_report_sha256": next(iter(numbering_report_hashes), ""),
        "identity_sources": identity_sources,
    }


def _collect_declared_lineage(payload: Any) -> dict[str, Any]:
    capture_hashes: set[str] = set()
    capture_paths: set[str] = set()
    revisions: dict[str, set[str]] = {field: set() for field in _REVISION_FIELDS}
    numbering_report_hashes: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _CAPTURE_HASH_FIELDS and isinstance(item, str) and item.strip():
                    capture_hashes.add(item.strip().casefold())
                elif key in _CAPTURE_PATH_FIELDS and isinstance(item, str) and item.strip():
                    capture_paths.add(item.strip())
                elif key in _REVISION_FIELDS and isinstance(item, str) and item.strip():
                    revisions[key].add(item.strip())
                elif (
                    key == _NUMBERING_REPORT_HASH_FIELD
                    and isinstance(item, str)
                    and item.strip()
                ):
                    numbering_report_hashes.add(item.strip().casefold())
                elif isinstance(item, (dict, list)):
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    walk(item)

    walk(payload)
    return {
        "capture_hashes": capture_hashes,
        "capture_paths": capture_paths,
        "revisions": revisions,
        "numbering_report_hashes": numbering_report_hashes,
    }


def _previous_lineage(previous_state: dict[str, Any] | None) -> tuple[str, dict[str, str]]:
    if not isinstance(previous_state, dict):
        return "", {}
    stages = previous_state.get("stages")
    if not isinstance(stages, dict):
        return "", {}
    stage_order = previous_state.get("stage_order")
    ordered_stages = stage_order if isinstance(stage_order, list) else list(stages)
    capture_values: set[str] = set()
    revision_values: dict[str, set[str]] = {field: set() for field in _REVISION_FIELDS}
    for stage in ordered_stages:
        record = stages.get(stage)
        if not isinstance(record, dict):
            continue
        evidence_refs = record.get("evidence_refs")
        if not isinstance(evidence_refs, dict):
            continue
        lineage = evidence_refs.get("workflow_lineage")
        if not isinstance(lineage, dict):
            continue
        capture = str(lineage.get("capture_anchor_sha256") or "").strip().casefold()
        if capture:
            capture_values.add(capture)
        revisions = lineage.get("declared_revisions")
        if not isinstance(revisions, dict):
            continue
        for field in _REVISION_FIELDS:
            value = str(revisions.get(field) or "").strip()
            if value:
                revision_values[field].add(value)

    if len(capture_values) > 1:
        raise LearningWorkflowEvidenceError(
            f"workflow history contains conflicting capture anchors: {sorted(capture_values)}"
        )
    for field, values in revision_values.items():
        if len(values) > 1:
            raise LearningWorkflowEvidenceError(
                f"workflow history contains conflicting {field} values: {sorted(values)}"
            )
    return (
        next(iter(capture_values), ""),
        {
            field: next(iter(values))
            for field, values in revision_values.items()
            if values
        },
    )


def _previous_numbering_report_sha256(previous_state: dict[str, Any] | None) -> str:
    if not isinstance(previous_state, dict):
        return ""
    stages = previous_state.get("stages")
    numbered_map = stages.get("numbered_map") if isinstance(stages, dict) else None
    evidence_refs = (
        numbered_map.get("evidence_refs")
        if isinstance(numbered_map, dict)
        else None
    )
    integrity = (
        evidence_refs.get("evidence_integrity")
        if isinstance(evidence_refs, dict)
        else None
    )
    artifacts = integrity.get("artifacts") if isinstance(integrity, dict) else None
    report = artifacts.get("report_path") if isinstance(artifacts, dict) else None
    return str(report.get("sha256") or "").strip().casefold() if isinstance(report, dict) else ""


def _resolve_evidence_path(
    path_value: str,
    *,
    project_root: Path,
    allowed_roots: tuple[Path, ...],
) -> Path:
    candidate = Path(path_value.strip())
    resolved = (candidate if candidate.is_absolute() else project_root / candidate).resolve()
    if not any(resolved.is_relative_to(allowed_root) for allowed_root in allowed_roots):
        raise LearningWorkflowEvidenceError(
            f"workflow evidence path is outside allowed runtime roots: {path_value}"
        )
    if not resolved.exists():
        raise LearningWorkflowEvidenceError(f"workflow evidence file does not exist: {path_value}")
    if not resolved.is_file():
        raise LearningWorkflowEvidenceError(f"workflow evidence path is not a file: {path_value}")
    return resolved


def _expected_sha256(evidence_refs: dict[str, Any], field: str) -> str:
    aliases = [f"{field}_sha256"]
    if field == "image_path":
        aliases.extend(("image_sha256", "screenshot_sha256"))
    for alias in aliases:
        value = evidence_refs.get(alias)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
