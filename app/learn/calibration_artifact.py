from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


CALIBRATION_RESULT_CONTRACT_VERSION = "learning_calibration_result_v1"
_ALLOWED_RUNTIME_ROOT_NAMES = ("artifacts", "logs")


class LearningCalibrationArtifactError(ValueError):
    """精准校准结果无法形成可信学习工件。"""


def create_learning_calibration_artifact(
    *,
    run_id: str,
    trace_path: str | Path,
    source_image_path: str | Path,
    numbering_report_path: str | Path,
    overlay_path: str | Path,
    project_root: str | Path,
) -> dict[str, Any]:
    """把最终定位 trace 固化为绑定截图和编号报告的只读校准工件。"""

    root = Path(project_root).resolve()
    allowed_roots = tuple((root / name).resolve() for name in _ALLOWED_RUNTIME_ROOT_NAMES)
    trace = _resolve_runtime_file(trace_path, project_root=root, allowed_roots=allowed_roots)
    source_image = _resolve_runtime_file(
        source_image_path,
        project_root=root,
        allowed_roots=allowed_roots,
    )
    numbering_report = _resolve_runtime_file(
        numbering_report_path,
        project_root=root,
        allowed_roots=allowed_roots,
    )
    overlay = _resolve_runtime_file(
        overlay_path,
        project_root=root,
        allowed_roots=allowed_roots,
    )
    trace_payload = _read_trace(trace)
    request = trace_payload.get("request")
    result = trace_payload.get("result")
    if trace_payload.get("success") is not True or not isinstance(request, dict) or not isinstance(result, dict):
        raise LearningCalibrationArtifactError("calibration trace did not record a successful result")

    metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
    if (
        metadata.get("learning_interface_flow") is not True
        or metadata.get("no_live_click_authorization") is not True
    ):
        raise LearningCalibrationArtifactError("calibration trace is not a no-click learning flow")

    _require_same_path(
        request.get("image_path"),
        source_image,
        project_root=root,
        allowed_roots=allowed_roots,
        label="source image",
    )
    _require_same_path(
        result.get("image_path"),
        source_image,
        project_root=root,
        allowed_roots=allowed_roots,
        label="result image",
    )
    _require_same_path(
        metadata.get("two_stage_report_path"),
        numbering_report,
        project_root=root,
        allowed_roots=allowed_roots,
        label="numbering report",
    )

    learn_targets = (
        result.get("learn_all_targets")
        if isinstance(result.get("learn_all_targets"), dict)
        else {}
    )
    _require_same_path(
        learn_targets.get("overlay_path"),
        overlay,
        project_root=root,
        allowed_roots=allowed_roots,
        label="calibration overlay",
    )
    validation = (
        learn_targets.get("vista_coordinate_validation")
        if isinstance(learn_targets.get("vista_coordinate_validation"), dict)
        else {}
    )
    batch = validation.get("batch") if isinstance(validation.get("batch"), dict) else {}
    remaining_count = _required_non_negative_int(
        batch.get("remaining_count"),
        field_name="batch.remaining_count",
    )
    resumable = batch.get("resumable") is True
    if remaining_count != 0 or resumable:
        raise LearningCalibrationArtifactError(
            "calibration trace is incomplete: "
            f"remaining_count={remaining_count}, resumable={str(resumable).lower()}"
        )

    artifact = {
        "contract_version": CALIBRATION_RESULT_CONTRACT_VERSION,
        "run_id": _safe_run_id(run_id),
        "source_image_path": _relative_path(source_image, root),
        "source_image_sha256": _sha256_file(source_image),
        "numbering_report_path": _relative_path(numbering_report, root),
        "numbering_report_sha256": _sha256_file(numbering_report),
        "calibration_trace_path": _relative_path(trace, root),
        "calibration_trace_sha256": _sha256_file(trace),
        "overlay_path": _relative_path(overlay, root),
        "overlay_sha256": _sha256_file(overlay),
        "calibration_summary": {
            "validated_count": _non_negative_int(validation.get("validated_count")),
            "failed_count": _non_negative_int(validation.get("failed_count")),
            "completed_count": _non_negative_int(batch.get("completed_count")),
            "remaining_count": remaining_count,
            "resumable": resumable,
        },
        "display_only": True,
        "candidate_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_clicks": 0,
        "final_submit_forbidden": True,
    }
    output_dir = root / "artifacts" / "learning-runs" / artifact["run_id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "calibration_result.json"
    temporary_path = output_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    return {
        "contract_version": CALIBRATION_RESULT_CONTRACT_VERSION,
        "result_path": _relative_path(output_path, root),
        "artifact": artifact,
    }


def _read_trace(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LearningCalibrationArtifactError(f"calibration trace is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise LearningCalibrationArtifactError("calibration trace must be an object")
    return payload


def _require_same_path(
    declared_path: Any,
    expected_path: Path,
    *,
    project_root: Path,
    allowed_roots: tuple[Path, ...],
    label: str,
) -> None:
    if not isinstance(declared_path, str) or not declared_path.strip():
        raise LearningCalibrationArtifactError(f"calibration trace is missing {label}")
    declared = _resolve_runtime_file(
        declared_path,
        project_root=project_root,
        allowed_roots=allowed_roots,
    )
    if declared != expected_path:
        raise LearningCalibrationArtifactError(
            f"calibration trace {label} does not match requested artifact"
        )


def _resolve_runtime_file(
    path_value: str | Path,
    *,
    project_root: Path,
    allowed_roots: tuple[Path, ...],
) -> Path:
    path = Path(path_value)
    resolved = (path if path.is_absolute() else project_root / path).resolve()
    if not any(resolved.is_relative_to(allowed_root) for allowed_root in allowed_roots):
        raise LearningCalibrationArtifactError(
            f"calibration artifact path is outside allowed runtime roots: {path_value}"
        )
    if not resolved.exists() or not resolved.is_file():
        raise LearningCalibrationArtifactError(
            f"calibration artifact file does not exist: {path_value}"
        )
    return resolved


def _safe_run_id(value: str) -> str:
    raw = str(value or "").strip()
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in raw)
    if not safe:
        raise LearningCalibrationArtifactError("run_id is required")
    return safe[:120]


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _required_non_negative_int(value: Any, *, field_name: str) -> int:
    if value is None or isinstance(value, bool):
        raise LearningCalibrationArtifactError(f"{field_name} is required")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise LearningCalibrationArtifactError(
            f"{field_name} must be a non-negative integer"
        ) from exc
    if parsed < 0:
        raise LearningCalibrationArtifactError(
            f"{field_name} must be a non-negative integer"
        )
    return parsed


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
