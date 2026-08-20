from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "learn_fusion_model_start_preflight_report.json"


def report_learn_fusion_model_start_preflight(
    *,
    runbook_path: str | Path,
    pathgraph_candidate_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    runbook_file = _resolve_path(runbook_path, root)
    candidate_file = _resolve_path(pathgraph_candidate_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    runbook = _read_json(runbook_file)
    candidate = _read_json(candidate_file)
    validation, validation_file = _load_validation_report(candidate, candidate_file, root)
    candidate_runbook = _dict(candidate.get("model_start_runbook")) or _dict(validation.get("model_start_runbook"))
    commands = _dict(runbook.get("commands"))
    expected_outputs = _dict(runbook.get("expected_outputs"))
    runbook_safety = _dict(runbook.get("safety"))
    validation_summary = _dict(validation.get("summary"))
    validation_safety = _dict(validation.get("safety"))

    ready_regions = _list_of_int(runbook.get("ready_region_numbers"))
    review_blocked_regions = _list_of_int(runbook.get("review_blocked_region_numbers"))
    candidate_ready_regions = _list_of_int(candidate_runbook.get("ready_region_numbers"))
    candidate_review_blocked = _list_of_int(candidate_runbook.get("review_blocked_region_numbers"))

    blockers: list[str] = []
    if runbook.get("runbook_status") != "awaiting_explicit_model_start_approval":
        blockers.append("runbook_not_awaiting_explicit_model_start_approval")
    if runbook.get("approval_required") is not True:
        blockers.append("runbook_approval_not_required")
    if runbook.get("may_start_model_after_user_approval") is not True:
        blockers.append("runbook_may_start_after_approval_false")
    if runbook.get("may_run_calibration_batch_now") is not False:
        blockers.append("runbook_may_run_now_not_false")
    if runbook.get("display_only") is not True:
        blockers.append("runbook_not_display_only")
    if runbook.get("execute_binding_enabled") is not False:
        blockers.append("runbook_execute_binding_enabled")
    if runbook.get("artifact_is_authorization") is not False:
        blockers.append("runbook_artifact_is_authorization")
    if commands.get("command_executes_now") is not False:
        blockers.append("calibration_command_executes_now")
    if commands.get("post_batch_refresh_command_executes_now") is not False:
        blockers.append("post_batch_refresh_command_executes_now")
    if expected_outputs.get("rerun_report_status") != "awaiting_future_calibration_output":
        blockers.append("future_rerun_report_not_awaiting")
    if _int_value(runbook_safety.get("model_started")):
        blockers.append("model_already_started")
    if _int_value(runbook_safety.get("live_clicks")):
        blockers.append("live_clicks_detected")
    if _int_value(runbook_safety.get("live_fills")):
        blockers.append("live_fills_detected")
    if _int_value(runbook_safety.get("live_submits")):
        blockers.append("live_submits_detected")
    validation_status = validation.get("validation_status") or candidate.get("validation_status")
    if validation_status != "blocked_pending_calibration":
        blockers.append("candidate_not_blocked_pending_calibration")
    if validation.get("ready_for_runtime_pathgraph_promotion") is True or validation_summary.get(
        "ready_for_runtime_pathgraph_promotion"
    ) is True:
        blockers.append("candidate_ready_for_runtime_pathgraph_promotion")
    if (
        candidate.get("execute_binding_enabled") is True
        or validation.get("execute_binding_enabled") is True
        or validation_safety.get("execute_binding_enabled") is True
    ):
        blockers.append("candidate_execute_binding_enabled")
    if (
        candidate.get("artifact_is_authorization") is True
        or validation.get("artifact_is_authorization") is True
        or validation_safety.get("artifact_is_authorization") is True
    ):
        blockers.append("candidate_artifact_is_authorization")
    if candidate_ready_regions and candidate_ready_regions != ready_regions:
        blockers.append("candidate_ready_regions_mismatch")
    if candidate_review_blocked and candidate_review_blocked != review_blocked_regions:
        blockers.append("candidate_review_blocked_regions_mismatch")
    if not ready_regions:
        blockers.append("ready_regions_missing")

    preflight_status = "blocked" if blockers else "ready_for_explicit_model_start"
    report = {
        "contract_version": "learn_fusion_model_start_preflight_v1",
        "preflight_status": preflight_status,
        "may_start_model_after_user_approval": preflight_status == "ready_for_explicit_model_start",
        "may_run_calibration_batch_now": False,
        "runbook_path": _relative_path(runbook_file, root),
        "pathgraph_candidate_path": _relative_path(candidate_file, root),
        "validation_report_path": _relative_path(validation_file, root) if validation_file is not None else None,
        "runbook_status": runbook.get("runbook_status"),
        "candidate_validation_status": validation_status,
        "ready_region_numbers": ready_regions,
        "review_blocked_region_numbers": review_blocked_regions,
        "future_rerun_report_status": expected_outputs.get("rerun_report_status"),
        "future_rerun_report_path": expected_outputs.get("rerun_report_path"),
        "commands": {
            "calibration_command_preview": commands.get("calibration_command_preview"),
            "post_batch_refresh_command_preview": commands.get("post_batch_refresh_command_preview"),
            "command_executes_now": False,
            "post_batch_refresh_command_executes_now": False,
        },
        "safety": {
            "model_started": bool(_int_value(runbook_safety.get("model_started"))),
            "live_clicks": _int_value(runbook_safety.get("live_clicks")),
            "live_fills": _int_value(runbook_safety.get("live_fills")),
            "live_submits": _int_value(runbook_safety.get("live_submits")),
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "display_only": True,
        },
        "blockers": sorted(set(blockers)),
        "interpretation": (
            "Offline preflight for the next explicitly approved learn-fusion calibration batch. "
            "It does not start models, click, fill, submit, refresh, merge, or promote Runtime PathGraph."
        ),
    }
    report_path = out / REPORT_NAME
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_validation_report(candidate: dict[str, Any], candidate_file: Path, root: Path) -> tuple[dict[str, Any], Path | None]:
    embedded = _dict(candidate.get("validation_report"))
    if embedded:
        return embedded, None
    declared = candidate.get("validation_report_path")
    if isinstance(declared, str) and declared.strip():
        declared_path = _resolve_path(declared, root)
        if declared_path.exists():
            return _read_json(declared_path), declared_path
    sibling = candidate_file.parent / "promotion_validation_report.json"
    if sibling.exists():
        return _read_json(sibling), sibling
    return {}, None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_int(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the next learn-fusion model-start preflight without executing it.")
    parser.add_argument("--runbook", required=True, help="learn_fusion_model_start_runbook.json")
    parser.add_argument("--pathgraph-candidate", required=True, help="pathgraph_candidate.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = report_learn_fusion_model_start_preflight(
        runbook_path=args.runbook,
        pathgraph_candidate_path=args.pathgraph_candidate,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0 if report.get("preflight_status") == "ready_for_explicit_model_start" else 1


if __name__ == "__main__":
    raise SystemExit(main())
