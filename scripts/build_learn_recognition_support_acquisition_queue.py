from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_support_acquisition_queue(
    *,
    diagnosis_report_path: str | Path,
    out: str | Path | None = None,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    diagnosis_path = Path(diagnosis_report_path)
    diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8-sig"))
    if not isinstance(diagnosis, dict):
        raise ValueError("diagnosis report must be a JSON object")
    targets = diagnosis.get("support_repair_targets")
    targets = targets if isinstance(targets, list) else []
    tasks = [_task_from_target(target, root) for target in targets if isinstance(target, dict)]
    tasks = sorted(tasks, key=lambda item: (int(item.get("priority") or 99), item.get("case_id") or ""))
    preflight_ready_count = sum(1 for task in tasks if (task.get("preflight") or {}).get("status") == "ready")
    preflight_blocked_count = sum(1 for task in tasks if (task.get("preflight") or {}).get("status") == "blocked")
    report = {
        "contract_version": "learn_recognition_support_acquisition_queue_v1",
        "input_report": str(diagnosis_path),
        "summary": {
            "task_count": len(tasks),
            "missing_support_count": sum(1 for task in tasks if task.get("task_type") == "capture_same_screenshot_support"),
            "alignment_repair_count": sum(1 for task in tasks if task.get("task_type") == "repair_bbox_alignment"),
            "preflight_ready_count": preflight_ready_count,
            "preflight_blocked_count": preflight_blocked_count,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "tasks": tasks,
        "interpretation": (
            "operator acquisition queue only; it does not capture windows, start models, run grounding, "
            "authorize clicks, or prove recognition quality"
        ),
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks_performed": 0,
            "final_submit_forbidden": True,
        },
    }
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["report_path"] = str(out_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _task_from_target(target: dict[str, Any], root: Path) -> dict[str, Any]:
    case_id = str(target.get("case_id") or "").strip()
    screenshot_path = str(target.get("screenshot_path") or "").strip()
    screenshot_sha256 = str(target.get("screenshot_sha256") or "").strip()
    support_status = str(target.get("same_screenshot_support_status") or "")
    bbox_status = str(target.get("bbox_alignment_status") or "")
    root_cause = str(target.get("root_cause") or "")
    task_type = _task_type(support_status=support_status, bbox_status=bbox_status, root_cause=root_cause)
    task = {
        "case_id": case_id,
        "surface": str(target.get("surface") or ""),
        "goal": str(target.get("goal") or ""),
        "priority": 1 if task_type == "capture_same_screenshot_support" else 2,
        "task_type": task_type,
        "root_cause": root_cause,
        "current_status": str(target.get("current_status") or ""),
        "screenshot_path": screenshot_path,
        "screenshot_sha256": screenshot_sha256,
        "case_locked_by_sha256": bool(screenshot_sha256),
        "same_screenshot_support_status": support_status,
        "interactable_support_count": _int(target.get("interactable_support_count")),
        "bbox_alignment_status": bbox_status,
        "required_next_evidence": list(target.get("required_next_evidence") or []),
        "recommended_commands": _recommended_commands(
            task_type=task_type,
            case_id=case_id,
            screenshot_path=screenshot_path,
            root=root,
        ),
        "support_validation_commands": _support_validation_commands(
            task_type=task_type,
            case_id=case_id,
        ),
        "acceptance_criteria": {
            "screenshot_sha256_must_match": True,
            "support_artifact_contract": "learn_recognition_same_screenshot_support_v1",
            "same_screenshot_interactable_support_required": True,
            "bbox_alignment_required_before_grounding_eligible": True,
            "capture_task_must_reproduce_target_window": task_type == "capture_same_screenshot_support",
            "pathgraph_candidate_created": False,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks_performed": 0,
            "final_submit_forbidden": True,
        },
    }
    task["preflight"] = _preflight_task(task, root)
    return task


def _task_type(*, support_status: str, bbox_status: str, root_cause: str) -> str:
    if root_cause == "parser_bbox_alignment_failed" or bbox_status in {"failed", "needs_repair"}:
        return "repair_bbox_alignment"
    if support_status in {"matching_interactable_support_found", "same_screenshot_support_found"}:
        return "repair_bbox_alignment"
    return "capture_same_screenshot_support"


def _recommended_commands(*, task_type: str, case_id: str, screenshot_path: str, root: Path) -> list[str]:
    out_dir = f"artifacts/benchmarks/learn_recognition_support_repair/{_safe_stem(case_id)}"
    manifest_out = f"{out_dir}/learn_recognition_actual_parser_cases_with_support.json"
    support_path = _support_artifact_path(task_type=task_type, case_id=case_id)
    if task_type == "repair_bbox_alignment":
        return [
            (
                "uv run python scripts\\create_learn_recognition_calibrated_support.py "
                f"--screenshot {screenshot_path} --out-dir {out_dir}"
            ),
            (
                "uv run python scripts\\bind_learn_recognition_support_to_manifest.py "
                "--manifest artifacts\\benchmarks\\learn_recognition_actual_parser_cases_v1.json "
                f"--case-id {case_id} --support {support_path} "
                f"--out {manifest_out}"
            ),
        ]
    return [
        (
            "uv run python scripts\\capture_learn_recognition_same_screenshot_support.py "
            f"--out {out_dir} --state-hint {case_id} --json"
        ),
        (
            "uv run python scripts\\bind_learn_recognition_support_to_manifest.py "
            "--manifest artifacts\\benchmarks\\learn_recognition_actual_parser_cases_v1.json "
            f"--case-id {case_id} --support {support_path} "
            f"--out {manifest_out}"
        ),
    ]


def _support_validation_commands(*, task_type: str, case_id: str) -> list[str]:
    support_path = _support_artifact_path(task_type=task_type, case_id=case_id)
    return [
        (
            "uv run python scripts\\bind_learn_recognition_support_to_manifest.py "
            "--manifest artifacts\\benchmarks\\learn_recognition_actual_parser_cases_v1.json "
            f"--case-id {case_id} --support {support_path} --validate-only --json"
        )
    ]


def _support_artifact_path(*, task_type: str, case_id: str) -> str:
    out_dir = f"artifacts/benchmarks/learn_recognition_support_repair/{_safe_stem(case_id)}"
    if task_type == "repair_bbox_alignment":
        return f"{out_dir}\\same_screenshot_calibrated_support.json"
    return f"{out_dir}\\same_screenshot_uia_support.json"


def _preflight_task(task: dict[str, Any], root: Path) -> dict[str, Any]:
    screenshot_path = _resolve_under_root(str(task.get("screenshot_path") or ""), root)
    expected_sha256 = str(task.get("screenshot_sha256") or "").strip().lower()
    blockers: list[str] = []
    screenshot_exists = screenshot_path.exists() if screenshot_path is not None else False
    actual_sha256 = ""
    if not screenshot_exists:
        blockers.append("screenshot_missing")
        screenshot_status = "missing"
    else:
        actual_sha256 = _sha256_file(screenshot_path)
        if expected_sha256 and actual_sha256 != expected_sha256:
            blockers.append("screenshot_sha256_mismatch")
            screenshot_status = "mismatch"
        elif expected_sha256:
            screenshot_status = "match"
        else:
            blockers.append("screenshot_sha256_missing")
            screenshot_status = "missing_expected"

    script_paths = _required_script_paths(str(task.get("task_type") or ""), root)
    missing_scripts = [str(path.relative_to(root)) for path in script_paths if not path.exists()]
    if missing_scripts:
        blockers.append("required_script_missing")
    manifest_path = root / "artifacts" / "benchmarks" / "learn_recognition_actual_parser_cases_v1.json"
    if not manifest_path.exists():
        blockers.append("manifest_missing")
    task_type = str(task.get("task_type") or "")
    manual_window_reproduction_required = task_type == "capture_same_screenshot_support"

    return {
        "contract_version": "learn_recognition_support_acquisition_preflight_v1",
        "status": "blocked" if blockers else "ready",
        "blockers": blockers,
        "manual_window_reproduction_required": manual_window_reproduction_required,
        "capture_script_accepts_saved_screenshot": False if manual_window_reproduction_required else None,
        "target_screenshot_sha256": expected_sha256,
        "screenshot_exists": screenshot_exists,
        "screenshot_sha256_status": screenshot_status,
        "expected_screenshot_sha256": expected_sha256,
        "actual_screenshot_sha256": actual_sha256,
        "required_scripts_present": not missing_scripts,
        "missing_scripts": missing_scripts,
        "manifest_exists": manifest_path.exists(),
        "manifest_path": str(manifest_path.relative_to(root)),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _required_script_paths(task_type: str, root: Path) -> list[Path]:
    names = ["bind_learn_recognition_support_to_manifest.py"]
    if task_type == "repair_bbox_alignment":
        names.insert(0, "create_learn_recognition_calibrated_support.py")
    else:
        names.insert(0, "capture_learn_recognition_same_screenshot_support.py")
    return [root / "scripts" / name for name in names]


def _resolve_under_root(path_value: str, root: Path) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_stem(value: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip().lower())
    return text.strip("_") or "case"


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an operator queue for acquiring same-screenshot support.")
    parser.add_argument("--diagnosis-report", required=True)
    parser.add_argument("--out")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_support_acquisition_queue(
        diagnosis_report_path=args.diagnosis_report,
        out=args.out,
        project_root=args.project_root,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
