from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.attach_learn_precise_understanding_fusion_status import attach_fusion_status_to_learning_trial
from scripts.merge_learn_fusion_targeted_rerun import merge_targeted_rerun_into_fusion_status
from scripts.report_learn_fusion_calibration_batch_acceptance import report_learn_fusion_calibration_batch_acceptance
from scripts.report_learn_precise_understanding_readiness import report_precise_understanding_readiness


REPORT_NAME = "learn_fusion_after_calibration_batch_refresh_result.json"


def refresh_learn_fusion_after_calibration_batch(
    *,
    trial_path: str | Path,
    base_status_path: str | Path,
    rerun_report_path: str | Path,
    batch_plan_path: str | Path | None = None,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    acceptance_result: dict[str, Any] | None = None
    if batch_plan_path is not None:
        acceptance_result = report_learn_fusion_calibration_batch_acceptance(
            plan_path=batch_plan_path,
            rerun_report_path=rerun_report_path,
            out_dir=out / "acceptance",
            project_root=root,
        )
        if acceptance_result.get("ready_for_post_batch_refresh") is not True:
            result = _blocked_by_acceptance_result(
                trial_path=trial_path,
                base_status_path=base_status_path,
                rerun_report_path=rerun_report_path,
                batch_plan_path=batch_plan_path,
                acceptance_result=acceptance_result,
                out=out,
                root=root,
            )
            if json_stdout:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            return result

    merge_result = merge_targeted_rerun_into_fusion_status(
        base_status_path=base_status_path,
        rerun_report_path=rerun_report_path,
        out_dir=out / "merge",
        project_root=root,
    )
    attach_result = attach_fusion_status_to_learning_trial(
        trial_path=trial_path,
        fusion_status_path=merge_result["corrected_status_path"],
        out_dir=out / "attached_draft",
        project_root=root,
    )
    readiness_result = report_precise_understanding_readiness(
        draft_path=attach_result["output_path"],
        out_dir=out / "readiness",
        project_root=root,
    )

    result = {
        "contract_version": "learn_fusion_after_calibration_batch_refresh_result_v1",
        "refresh_status": "refreshed_after_calibration_batch",
        "source_trial_path": _relative_path(_resolve_path(trial_path, root), root),
        "base_status_path": _relative_path(_resolve_path(base_status_path, root), root),
        "rerun_report_path": _relative_path(_resolve_path(rerun_report_path, root), root),
        "batch_plan_path": _relative_path(_resolve_path(batch_plan_path, root), root) if batch_plan_path is not None else None,
        "acceptance_report_path": acceptance_result.get("report_path") if acceptance_result is not None else None,
        "acceptance_status": acceptance_result.get("acceptance_status") if acceptance_result is not None else "not_required",
        "acceptance_blockers": acceptance_result.get("blockers", []) if acceptance_result is not None else [],
        "merge_skipped": False,
        "attach_skipped": False,
        "readiness_skipped": False,
        "merge_report_path": merge_result["report_path"],
        "corrected_status_path": merge_result["corrected_status_path"],
        "attach_report_path": attach_result["attach_report_path"],
        "attached_draft_path": attach_result["output_path"],
        "readiness_report_path": readiness_result["report_path"],
        "updated_region_numbers": merge_result.get("updated_region_numbers", []),
        "updated_item_count": merge_result.get("updated_item_count", 0),
        "readiness_status": readiness_result.get("readiness_status"),
        "coverage_summary": readiness_result.get("coverage_summary"),
        "pending_calibration": readiness_result.get("pending_calibration"),
        "model_started": False,
        "live_clicks": 0,
        "live_fills": 0,
        "live_submits": 0,
        "runtime_pathgraph_promotion": False,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Offline refresh after a numbered-region calibration batch. "
            "It merges existing dry-run evidence, attaches the corrected fusion status to a Learning Draft, "
            "and recomputes readiness. It does not start models, click, fill, submit, or promote Runtime PathGraph."
        ),
    }
    report_path = out / REPORT_NAME
    result["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _blocked_by_acceptance_result(
    *,
    trial_path: str | Path,
    base_status_path: str | Path,
    rerun_report_path: str | Path,
    batch_plan_path: str | Path,
    acceptance_result: dict[str, Any],
    out: Path,
    root: Path,
) -> dict[str, Any]:
    report_path = out / REPORT_NAME
    result = {
        "contract_version": "learn_fusion_after_calibration_batch_refresh_result_v1",
        "refresh_status": "blocked_by_calibration_batch_acceptance",
        "source_trial_path": _relative_path(_resolve_path(trial_path, root), root),
        "base_status_path": _relative_path(_resolve_path(base_status_path, root), root),
        "rerun_report_path": _relative_path(_resolve_path(rerun_report_path, root), root),
        "batch_plan_path": _relative_path(_resolve_path(batch_plan_path, root), root),
        "acceptance_report_path": acceptance_result.get("report_path"),
        "acceptance_status": acceptance_result.get("acceptance_status"),
        "acceptance_blockers": acceptance_result.get("blockers", []),
        "merge_skipped": True,
        "attach_skipped": True,
        "readiness_skipped": True,
        "updated_region_numbers": [],
        "updated_item_count": 0,
        "readiness_status": "not_evaluated_acceptance_blocked",
        "coverage_summary": None,
        "pending_calibration": None,
        "model_started": False,
        "live_clicks": 0,
        "live_fills": 0,
        "live_submits": 0,
        "runtime_pathgraph_promotion": False,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Offline refresh was blocked before merge because the numbered-region calibration batch did not pass "
            "the acceptance gate. It did not start models, click, fill, submit, attach a draft, recompute readiness, "
            "or promote Runtime PathGraph."
        ),
        "report_path": str(report_path.resolve()),
    }
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh a Learning Draft after offline numbered-region calibration evidence is available.")
    parser.add_argument("--trial", required=True, help="Path to actual_parser_output/trial JSON containing learning_draft")
    parser.add_argument("--base-status", required=True, help="Path to base precise-understanding fusion status JSON")
    parser.add_argument("--rerun-report", required=True, help="Path to numbered_region_calibration_report.json with new evidence")
    parser.add_argument("--batch-plan", help="Optional numbered-region calibration batch plan JSON; if provided, refresh is blocked unless acceptance passes")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    refresh_learn_fusion_after_calibration_batch(
        trial_path=args.trial,
        base_status_path=args.base_status,
        rerun_report_path=args.rerun_report,
        batch_plan_path=args.batch_plan,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
