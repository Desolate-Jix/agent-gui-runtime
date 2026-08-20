from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPORT_NAME = "learn_fusion_calibration_handoff_report.json"


def report_learn_fusion_calibration_handoff(
    *,
    trial_path: str | Path,
    batch_plan_path: str | Path,
    refresh_base_status_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    trial_file = _resolve_path(trial_path, root)
    batch_file = _resolve_path(batch_plan_path, root)
    base_file = _resolve_path(refresh_base_status_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    trial = _read_json(trial_file)
    batch = _read_json(batch_file)
    base = _read_json(base_file)
    fusion_status = _fusion_status(trial)
    readiness = fusion_status.get("precise_understanding_readiness_summary") if isinstance(fusion_status.get("precise_understanding_readiness_summary"), dict) else {}

    blockers: list[str] = []
    warnings: list[str] = []
    ready_regions = _list_of_int(batch.get("ready_region_numbers"))
    review_regions = _list_of_int(batch.get("review_blocked_region_numbers"))
    refresh_args = _list_of_text(batch.get("post_batch_refresh_command_args"))
    refresh_trial = _arg_after(refresh_args, "--trial")
    refresh_base = _arg_after(refresh_args, "--base-status")
    rerun_report = _arg_after(refresh_args, "--rerun-report")
    rerun_file = _resolve_path(rerun_report, root) if rerun_report else None

    if not ready_regions:
        blockers.append("no_ready_regions_for_calibration")
    if batch.get("command_executes_now") is True:
        blockers.append("batch_command_executes_now_true")
    if batch.get("post_batch_refresh_command_executes_now") is True:
        blockers.append("post_batch_refresh_command_executes_now_true")
    if batch.get("start_model_flag_included") is True:
        blockers.append("batch_start_model_flag_included")
    if batch.get("execute_binding_enabled") is True:
        blockers.append("batch_execute_binding_enabled_true")
    if batch.get("artifact_is_authorization") is True:
        blockers.append("batch_artifact_is_authorization_true")
    if fusion_status.get("execute_binding_enabled") is True:
        blockers.append("trial_execute_binding_enabled_true")
    if fusion_status.get("artifact_is_authorization") is True:
        blockers.append("trial_artifact_is_authorization_true")
    if base.get("execute_binding_enabled") is True:
        blockers.append("base_execute_binding_enabled_true")
    if base.get("artifact_is_authorization") is True:
        blockers.append("base_artifact_is_authorization_true")
    if not refresh_args:
        blockers.append("post_batch_refresh_command_missing")
    if refresh_trial and not _same_path(refresh_trial, trial_file, root):
        blockers.append("post_batch_refresh_trial_mismatch")
    if refresh_base and not _same_path(refresh_base, base_file, root):
        blockers.append("post_batch_refresh_base_status_mismatch")
    if refresh_args and not refresh_trial:
        blockers.append("post_batch_refresh_trial_arg_missing")
    if refresh_args and not refresh_base:
        blockers.append("post_batch_refresh_base_status_arg_missing")
    if refresh_args and not rerun_file:
        blockers.append("post_batch_refresh_rerun_report_arg_missing")

    if readiness.get("readiness_status") != "needs_pending_calibration":
        warnings.append("readiness_status_not_needs_pending_calibration")
    if _number(readiness.get("calibration_coverage_rate")) >= 1:
        warnings.append("calibration_coverage_already_complete")

    rerun_status = "missing"
    if rerun_file is not None:
        rerun_status = "exists" if rerun_file.exists() else "awaiting_future_calibration_output"

    if blockers:
        handoff_status = "blocked"
    elif rerun_status == "exists":
        handoff_status = "ready_for_post_batch_refresh"
    else:
        handoff_status = "ready_for_explicit_model_start"

    safe_to_start = handoff_status == "ready_for_explicit_model_start"
    report = {
        "contract_version": "learn_fusion_calibration_handoff_report_v1",
        "handoff_status": handoff_status,
        "safe_to_start_after_user_approval": safe_to_start,
        "trial_path": str(trial_file),
        "batch_plan_path": str(batch_file),
        "refresh_base_status_path": str(base_file),
        "ready_region_numbers": ready_regions,
        "review_blocked_region_numbers": review_regions,
        "readiness": {
            "readiness_status": readiness.get("readiness_status"),
            "total_locator_cards": readiness.get("total_locator_cards"),
            "calibrated_cases": readiness.get("calibrated_cases"),
            "uncalibrated_locator_cards": readiness.get("uncalibrated_locator_cards"),
            "calibration_coverage_rate": readiness.get("calibration_coverage_rate"),
            "pending_calibration_ready_count": readiness.get("pending_calibration_ready_count"),
            "pending_calibration_review_count": readiness.get("pending_calibration_review_count"),
            "pathgraph_status": readiness.get("pathgraph_status"),
        },
        "commands": {
            "calibration_command_preview": batch.get("run_command_preview"),
            "post_batch_refresh_command_preview": batch.get("post_batch_refresh_command_preview"),
            "post_batch_refresh_command_args": refresh_args,
            "command_executes_now": batch.get("command_executes_now") is True,
            "post_batch_refresh_command_executes_now": batch.get("post_batch_refresh_command_executes_now") is True,
            "start_model_flag_included": batch.get("start_model_flag_included") is True,
        },
        "future_outputs": {
            "rerun_report_path": str(rerun_file) if rerun_file is not None else None,
            "rerun_report_status": rerun_status,
            "post_batch_refresh_requires_completed_batch": batch.get("post_batch_refresh_requires_completed_batch") is True,
        },
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": True,
            "real_clicks": 0,
            "live_fill": False,
            "live_submit": False,
            "interpretation": "Preflight only. It does not start models, click, fill, submit, or promote Runtime PathGraph.",
        },
        "blockers": blockers,
        "warnings": warnings,
    }
    report_path = out / REPORT_NAME
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _fusion_status(trial: dict[str, Any]) -> dict[str, Any]:
    draft = trial.get("learning_draft") if isinstance(trial.get("learning_draft"), dict) else {}
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    audit = page_details.get("pipeline_audit") if isinstance(page_details.get("pipeline_audit"), dict) else {}
    status = audit.get("precise_understanding_fusion_status")
    return status if isinstance(status, dict) else {}


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


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


def _list_of_text(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _arg_after(args: list[str], flag: str) -> str:
    try:
        index = args.index(flag)
    except ValueError:
        return ""
    if index + 1 >= len(args):
        return ""
    return args[index + 1]


def _same_path(candidate: str, expected: Path, root: Path) -> bool:
    return _resolve_path(candidate, root) == expected.resolve()


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report whether the current learn-fusion calibration batch handoff is safe and ready.")
    parser.add_argument("--trial", required=True, help="Current loadable Learning Draft artifact")
    parser.add_argument("--batch-plan", required=True, help="numbered_region_calibration_batch_plan.json")
    parser.add_argument("--refresh-base-status", required=True, help="Composed refresh base status JSON")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report_learn_fusion_calibration_handoff(
        trial_path=args.trial,
        batch_plan_path=args.batch_plan,
        refresh_base_status_path=args.refresh_base_status,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
