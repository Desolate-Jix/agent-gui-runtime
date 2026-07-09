from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.draft_review import load_learning_draft_review

REPORT_NAME = "learn_fusion_demo_readiness_report.json"


def report_learn_fusion_demo_readiness(
    *,
    raw_recommended_source_path: str | Path,
    preflight_candidate_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    raw_source = _resolve_path(raw_recommended_source_path, root)
    candidate_file = _resolve_path(preflight_candidate_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    review = load_learning_draft_review(candidate_file, project_root=root)
    candidate_review = _dict(review.get("pathgraph_candidate_review"))
    readiness = _dict(candidate_review.get("pathgraph_readiness_summary"))
    preflight = _dict(candidate_review.get("model_start_preflight"))
    preflight_safety = _dict(preflight.get("safety"))
    blockers: list[str] = []

    candidate_validation_status = readiness.get("validation_status")
    preflight_status = preflight.get("preflight_status")
    if candidate_validation_status != "blocked_pending_calibration":
        blockers.append("candidate_not_blocked_pending_calibration")
    if preflight_status != "ready_for_explicit_model_start":
        blockers.append("preflight_not_ready_for_explicit_model_start")
    if preflight.get("may_start_model_after_user_approval") is not True:
        blockers.append("preflight_may_start_after_approval_false")
    if preflight.get("may_run_calibration_batch_now") is not False:
        blockers.append("preflight_may_run_now_not_false")
    if candidate_review.get("execute_binding_enabled") is not False:
        blockers.append("candidate_execute_binding_enabled")
    if candidate_review.get("artifact_is_authorization") is not False:
        blockers.append("candidate_artifact_is_authorization")
    if _int_value(preflight_safety.get("model_started")):
        blockers.append("model_started")
    if _int_value(preflight_safety.get("live_clicks")):
        blockers.append("live_clicks_detected")
    if _int_value(preflight_safety.get("live_fills")):
        blockers.append("live_fills_detected")
    if _int_value(preflight_safety.get("live_submits")):
        blockers.append("live_submits_detected")

    status = "blocked" if blockers else "ready_for_preflight_demo"
    report = {
        "contract_version": "learn_fusion_demo_readiness_v1",
        "demo_readiness_status": status,
        "raw_recommended_source_path": _relative_path(raw_source, root),
        "recommended_load_path": _relative_path(candidate_file, root),
        "candidate_validation_status": candidate_validation_status,
        "candidate_readiness_status": readiness.get("readiness_status"),
        "preflight_status": preflight_status,
        "may_start_model_after_user_approval": preflight.get("may_start_model_after_user_approval") is True,
        "may_run_calibration_batch_now": preflight.get("may_run_calibration_batch_now") is True,
        "ready_region_numbers": preflight.get("ready_region_numbers") if isinstance(preflight.get("ready_region_numbers"), list) else [],
        "review_blocked_region_numbers": (
            preflight.get("review_blocked_region_numbers")
            if isinstance(preflight.get("review_blocked_region_numbers"), list)
            else []
        ),
        "safety": {
            "model_started": bool(_int_value(preflight_safety.get("model_started"))),
            "live_clicks": _int_value(preflight_safety.get("live_clicks")),
            "live_fills": _int_value(preflight_safety.get("live_fills")),
            "live_submits": _int_value(preflight_safety.get("live_submits")),
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "blockers": sorted(set(blockers)),
        "interpretation": (
            "Offline demo readiness report for the current learn-fusion PathGraph candidate. "
            "Ready means the UI can show the candidate blocker and model-start preflight context; "
            "it does not start models, run calibration, click, fill, submit, refresh, merge, or promote Runtime PathGraph."
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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an offline learn-fusion demo readiness report.")
    parser.add_argument("--raw-recommended-source", required=True, help="Pinned raw learning draft source path")
    parser.add_argument("--preflight-candidate", required=True, help="Preflight-aware pathgraph_candidate.json path")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = report_learn_fusion_demo_readiness(
        raw_recommended_source_path=args.raw_recommended_source,
        preflight_candidate_path=args.preflight_candidate,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0 if report.get("demo_readiness_status") == "ready_for_preflight_demo" else 1


if __name__ == "__main__":
    raise SystemExit(main())
