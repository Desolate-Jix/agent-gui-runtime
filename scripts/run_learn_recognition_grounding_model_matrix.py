from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.model_server import ensure_model_server, stop_model_server
from scripts.run_learn_recognition_actual_grounding_smoke import (
    ModelCaller,
    run_actual_grounding_smoke_batch,
)


def run_grounding_model_matrix(
    *,
    manifest_path: str | Path,
    cases_json_path: str | Path,
    out_dir: str | Path,
    model_profiles: list[str],
    endpoint: str | None = None,
    model_name: str | None = None,
    timeout_seconds: float = 60.0,
    start_profiles: bool = False,
    stop_started_profiles: bool = True,
    start_wait_seconds: float = 180.0,
    model_caller: ModelCaller | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    if not model_profiles:
        raise ValueError("at least one --model-profile is required")
    manifest_path = Path(manifest_path)
    cases_json_path = Path(cases_json_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases_payload = _read_json(cases_json_path)
    cases = cases_payload.get("cases") if isinstance(cases_payload, dict) else cases_payload
    if not isinstance(cases, list):
        raise ValueError("--cases-json must contain a list or an object with cases")

    lifecycle = _start_profiles(model_profiles, wait_seconds=start_wait_seconds) if start_profiles else {
        "start_profiles_requested": False,
        "started_profiles": [],
        "skipped_profiles": [],
        "errors": [],
    }
    profile_reports: list[dict[str, Any]] = []
    try:
        for profile_id in model_profiles:
            profile_slug = _safe_path_part(_profile_label(profile_id))
            profile_out_dir = out_dir / profile_slug
            batch_report = run_actual_grounding_smoke_batch(
                manifest_path=manifest_path,
                cases=cases,
                out_dir=profile_out_dir,
                endpoint=endpoint,
                model_name=model_name,
                model_profile_id=profile_id,
                timeout_seconds=timeout_seconds,
                model_caller=model_caller,
                json_stdout=False,
            )
            profile_reports.append(_profile_report_summary(profile_id, batch_report))
    finally:
        if start_profiles and stop_started_profiles:
            lifecycle["stop_started_profiles_requested"] = True
            lifecycle["stop_results"] = _stop_started_profiles(lifecycle.get("started_profiles", []))
        elif start_profiles:
            lifecycle["stop_started_profiles_requested"] = False
            lifecycle["stop_results"] = []

    source_breakdown = _source_breakdown(cases)
    report = {
        "contract_version": "learn_recognition_grounding_model_matrix_report_v1",
        "evaluation_scope": "learn_mode_saved_screenshot_roi_grounding_matrix",
        "execution_scope": "no_action_no_execute_no_live_click",
        "reliability_status": "exploratory_insufficient_sample_size",
        "dataset_status": "targeted_hardcase_matrix",
        "selection_bias": "contains targeted hard cases derived from known failure modes",
        "not_accuracy": True,
        "not_e2e_success": True,
        "not_execute_mode_default": True,
        "manifest_path": str(manifest_path),
        "cases_json_path": str(cases_json_path),
        "candidate_set": {
            "contract_version": cases_payload.get("contract_version") if isinstance(cases_payload, dict) else "",
            "case_count": len(cases),
            "required_report_policy": cases_payload.get("required_report_policy", {}) if isinstance(cases_payload, dict) else {},
        },
        "source_breakdown": source_breakdown,
        "fresh_actual_calls": {"attempted": source_breakdown["saved_screenshot_actual_call"]},
        "precondition_stops": {
            "count": source_breakdown["precondition_stop"],
            "excluded_from_grounding_denominator": True,
        },
        "grounding_point_inside_expected_bbox_checks": _grounding_point_inside_expected_bbox_checks(profile_reports),
        "model_profiles_requested": model_profiles,
        "service_lifecycle": lifecycle,
        "profile_reports": profile_reports,
        "matrix_summary": _matrix_summary(profile_reports),
        "interpretation": (
            "comparison scaffold only; actual_model_call denominators are per profile and exclude readiness/precondition blockers; "
            "do not report this as 90% accuracy, Execute success, click authorization, or reliability"
        ),
    }
    report_path = out_dir / "learn_grounding_model_matrix_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _start_profiles(model_profiles: list[str], *, wait_seconds: float) -> dict[str, Any]:
    lifecycle = {
        "start_profiles_requested": True,
        "started_profiles": [],
        "skipped_profiles": [],
        "errors": [],
    }
    for profile_id in model_profiles:
        if Path(profile_id).suffix == ".json":
            lifecycle["skipped_profiles"].append(
                {
                    "profile_id": profile_id,
                    "reason": "path_profile_lifecycle_not_supported",
                }
            )
            continue
        try:
            result = ensure_model_server(
                stage="locate",
                profile_id=profile_id,
                wait_until_ready=True,
                wait_seconds=wait_seconds,
            )
        except Exception as exc:
            lifecycle["errors"].append(
                {
                    "profile_id": profile_id,
                    "error": str(exc),
                }
            )
            continue
        entry = {
            "profile_id": profile_id,
            "started": bool(result.get("started")),
            "before_status": _status_value(result.get("before")),
            "after_status": _status_value(result.get("after")),
            "start": result.get("start") or {},
            "profile": result.get("profile") or {},
        }
        if entry["started"]:
            lifecycle["started_profiles"].append(entry)
        else:
            lifecycle["skipped_profiles"].append(
                {
                    **entry,
                    "reason": "already_running_or_not_started",
                }
            )
    return lifecycle


def _stop_started_profiles(started_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stop_results: list[dict[str, Any]] = []
    for entry in started_profiles:
        profile = entry.get("profile") if isinstance(entry.get("profile"), dict) else {}
        profile_id = str(entry.get("profile_id") or profile.get("profile_id") or "")
        if not profile:
            stop_results.append(
                {
                    "profile_id": profile_id,
                    "stopped": False,
                    "error": "started profile missing public profile payload",
                }
            )
            continue
        try:
            result = stop_model_server(profile)
        except Exception as exc:
            stop_results.append(
                {
                    "profile_id": profile_id,
                    "stopped": False,
                    "error": str(exc),
                }
            )
            continue
        stop_results.append(
            {
                "profile_id": profile_id,
                "stopped": bool(result.get("stopped")),
                "returncode": result.get("returncode"),
                "stdout": result.get("stdout") or "",
                "stderr": result.get("stderr") or "",
                "after_status": _status_value(result.get("after")),
            }
        )
    return stop_results


def _status_value(payload: Any) -> str:
    return str(payload.get("status") or "") if isinstance(payload, dict) else ""


def _profile_report_summary(profile_id: str, batch_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_profile_id": profile_id,
        "batch_report_path": batch_report.get("report_path"),
        "case_count": batch_report.get("case_count"),
        "summary": batch_report.get("summary", {}),
        "actual_model_profile_breakdown": batch_report.get("actual_model_profile_breakdown", {}),
        "actual_grounding_failure_categories": batch_report.get("actual_grounding_failure_categories", {}),
        "interpretation": "single-profile batch report summary; inspect batch_report_path for per-case expected/actual evidence",
    }


def _matrix_summary(profile_reports: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for report in profile_reports:
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        actual = summary.get("actual_model_call") if isinstance(summary.get("actual_model_call"), dict) else {}
        rows.append(
            {
                "model_profile_id": report.get("model_profile_id"),
                "actual_model_call": {
                    "passed": actual.get("passed", 0),
                    "attempted": actual.get("attempted", 0),
                    "rate": actual.get("rate", "not_covered"),
                    "interpretation": actual.get(
                        "interpretation",
                        "fresh actual grounding calls only; not a reliability or 90% accuracy claim",
                    ),
                },
                "total_status": {
                    "passed": summary.get("passed", 0),
                    "failed": summary.get("failed", 0),
                    "blocked": summary.get("blocked", 0),
                },
                "blocked_categories": summary.get("blocked_categories", {}),
                "actual_grounding_failure_categories": report.get("actual_grounding_failure_categories", {}),
                "point_center_bias_diagnostic": summary.get("point_center_bias_diagnostic", {}),
                "batch_report_path": report.get("batch_report_path"),
            }
        )
    return {
        "profile_count": len(rows),
        "rows": rows,
        "interpretation": "matrix rows are comparable only when they use the same cases_json_path; readiness blockers are not model calls",
    }


def _source_breakdown(cases: list[dict[str, Any]]) -> dict[str, int]:
    actual = sum(1 for case in cases if case.get("expected_case_outcome") == "actual_grounding_call")
    precondition = sum(1 for case in cases if case.get("expected_case_outcome") == "blocked_precondition")
    return {
        "saved_screenshot_actual_call": actual,
        "precondition_stop": precondition,
        "live_click": 0,
        "execute_mode": 0,
    }


def _grounding_point_inside_expected_bbox_checks(profile_reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    for report in profile_reports:
        profile_id = _profile_check_key(report)
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        actual = summary.get("actual_model_call") if isinstance(summary.get("actual_model_call"), dict) else {}
        checks[profile_id] = {
            "passed": actual.get("passed", 0),
            "attempted": actual.get("attempted", 0),
            "rate": actual.get("rate", "not_covered"),
            "interpretation": "ROI saved-screenshot bbox check only; not live GUI reliability",
        }
    return checks


def _profile_check_key(report: dict[str, Any]) -> str:
    breakdown = report.get("actual_model_profile_breakdown") if isinstance(report.get("actual_model_profile_breakdown"), dict) else {}
    for bucket_name in ("actual_model_call", "blocked_or_precondition"):
        bucket = breakdown.get(bucket_name) if isinstance(breakdown.get(bucket_name), dict) else {}
        for profile_id in bucket:
            if str(profile_id).strip():
                return str(profile_id)
    return str(report.get("model_profile_id") or "")


def _profile_label(profile_id: str) -> str:
    path = Path(profile_id)
    return path.stem if path.suffix == ".json" else profile_id


def _safe_path_part(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(value)).strip("_") or "profile"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--cases-json", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model-profile", action="append", required=True)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--start-profiles", action="store_true")
    parser.add_argument("--no-stop-started-profiles", action="store_true")
    parser.add_argument("--start-wait-seconds", type=float, default=180.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    run_grounding_model_matrix(
        manifest_path=args.manifest,
        cases_json_path=args.cases_json,
        out_dir=args.out,
        model_profiles=args.model_profile,
        endpoint=args.endpoint,
        model_name=args.model,
        timeout_seconds=args.timeout_seconds,
        start_profiles=args.start_profiles,
        stop_started_profiles=not args.no_stop_started_profiles,
        start_wait_seconds=args.start_wait_seconds,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
