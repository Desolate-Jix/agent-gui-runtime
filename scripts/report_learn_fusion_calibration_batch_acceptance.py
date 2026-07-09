from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPORT_NAME = "learn_fusion_calibration_batch_acceptance_report.json"


def report_learn_fusion_calibration_batch_acceptance(
    *,
    plan_path: str | Path,
    rerun_report_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    plan_file = _resolve_path(plan_path, root)
    rerun_file = _resolve_path(rerun_report_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    plan = _read_json(plan_file)
    expected_ready = _list_of_int(plan.get("ready_region_numbers"))
    review_blocked = _list_of_int(plan.get("review_blocked_region_numbers"))
    blockers: list[str] = []
    warnings: list[str] = []
    if plan.get("command_executes_now") is True:
        blockers.append("plan_command_executes_now")
    if plan.get("post_batch_refresh_command_executes_now") is True:
        blockers.append("post_batch_refresh_command_executes_now")
    if plan.get("execute_binding_enabled") is True:
        blockers.append("plan_execute_binding_enabled")
    if plan.get("artifact_is_authorization") is True:
        blockers.append("plan_artifact_is_authorization")

    if not rerun_file.exists():
        blockers.append("rerun_report_missing")
        report = _base_report(
            root=root,
            plan_file=plan_file,
            rerun_file=rerun_file,
            acceptance_status="awaiting_future_calibration_output",
            ready_for_post_batch_refresh=False,
            expected_ready=expected_ready,
            review_blocked=review_blocked,
            accepted_regions=[],
            blockers=blockers,
            warnings=warnings,
            real_clicks=0,
            checks={"rerun_report_exists": False},
        )
        return _write_report(report, out=out, json_stdout=json_stdout)

    rerun = _read_json(rerun_file)
    fused = rerun.get("fused_precise_understanding") if isinstance(rerun.get("fused_precise_understanding"), dict) else {}
    items = _list_of_dicts(fused.get("items"))
    report_regions = _list_of_int(rerun.get("region_numbers"))
    item_regions = sorted({region for region in (_int_or_none(item.get("region_no")) for item in items) if region is not None})
    accepted_regions = sorted(set(item_regions or report_regions))
    missing_ready = [region for region in expected_ready if region not in accepted_regions]
    unexpected = [region for region in accepted_regions if region not in expected_ready and region not in review_blocked]
    attempted_review_blocked = [region for region in accepted_regions if region in review_blocked]
    summary = rerun.get("summary") if isinstance(rerun.get("summary"), dict) else {}
    real_clicks = max(_int_value(summary.get("real_clicks")), sum(_int_value(item.get("real_clicks")) for item in items))
    no_execute_binding = (
        fused.get("execute_binding_enabled") is not True
        and all(item.get("execute_binding_enabled") is not True for item in items)
    )
    no_authorization = (
        fused.get("artifact_is_authorization") is not True
        and all(item.get("artifact_is_authorization") is not True for item in items)
    )
    if missing_ready:
        blockers.append("missing_ready_regions")
    if unexpected:
        blockers.append("unexpected_regions")
    if attempted_review_blocked:
        blockers.append("review_blocked_regions_rerun_attempted")
    if real_clicks:
        blockers.append("real_clicks_detected")
    if not no_execute_binding:
        blockers.append("execute_binding_enabled")
    if not no_authorization:
        blockers.append("artifact_is_authorization")
    if not items:
        warnings.append("rerun_items_missing")

    checks = {
        "rerun_report_exists": True,
        "region_coverage_complete": not missing_ready and not unexpected and not attempted_review_blocked,
        "no_real_clicks": real_clicks == 0,
        "execute_binding_disabled": no_execute_binding,
        "artifact_is_authorization_false": no_authorization,
        "post_batch_refresh_preview_only": plan.get("post_batch_refresh_command_executes_now") is not True,
    }
    status = "accepted_for_post_batch_refresh" if not blockers else "blocked_calibration_batch_invalid"
    report = _base_report(
        root=root,
        plan_file=plan_file,
        rerun_file=rerun_file,
        acceptance_status=status,
        ready_for_post_batch_refresh=not blockers,
        expected_ready=expected_ready,
        review_blocked=review_blocked,
        accepted_regions=accepted_regions,
        blockers=blockers,
        warnings=warnings,
        real_clicks=real_clicks,
        checks=checks,
    )
    report["coverage"].update(
        {
            "missing_ready_region_numbers": missing_ready,
            "unexpected_region_numbers": unexpected,
            "review_blocked_region_numbers_in_rerun": attempted_review_blocked,
        }
    )
    report["rerun_summary"] = summary
    return _write_report(report, out=out, json_stdout=json_stdout)


def _base_report(
    *,
    root: Path,
    plan_file: Path,
    rerun_file: Path,
    acceptance_status: str,
    ready_for_post_batch_refresh: bool,
    expected_ready: list[int],
    review_blocked: list[int],
    accepted_regions: list[int],
    blockers: list[str],
    warnings: list[str],
    real_clicks: int,
    checks: dict[str, bool],
) -> dict[str, Any]:
    missing_ready = [region for region in expected_ready if region not in accepted_regions]
    unexpected = [region for region in accepted_regions if region not in expected_ready and region not in review_blocked]
    attempted_review_blocked = [region for region in accepted_regions if region in review_blocked]
    return {
        "contract_version": "learn_fusion_calibration_batch_acceptance_report_v1",
        "plan_path": _relative_path(plan_file, root),
        "rerun_report_path": _relative_path(rerun_file, root),
        "acceptance_status": acceptance_status,
        "ready_for_post_batch_refresh": ready_for_post_batch_refresh,
        "coverage": {
            "expected_ready_region_numbers": expected_ready,
            "accepted_region_numbers": accepted_regions,
            "missing_ready_region_numbers": missing_ready,
            "unexpected_region_numbers": unexpected,
            "review_blocked_region_numbers_in_rerun": attempted_review_blocked,
        },
        "safety": {
            "real_clicks": real_clicks,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": True,
            "no_dispatch_required": True,
        },
        "checks": checks,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Offline acceptance gate for a future numbered-region calibration batch. "
            "It does not start models, click, fill, submit, refresh, merge, or promote Runtime PathGraph."
        ),
    }


def _write_report(report: dict[str, Any], *, out: Path, json_stdout: bool) -> dict[str, Any]:
    report_path = out / REPORT_NAME
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "learn_fusion_calibration_batch_acceptance_result_v1",
        "report_path": str(report_path.resolve()),
        "acceptance_status": report["acceptance_status"],
        "ready_for_post_batch_refresh": report["ready_for_post_batch_refresh"],
        "blockers": report["blockers"],
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


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


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _list_of_int(value: Any) -> list[int]:
    result: list[int] = []
    if not isinstance(value, list):
        return result
    for item in value:
        parsed = _int_or_none(item)
        if parsed is not None:
            result.append(parsed)
    return result


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: Any) -> int:
    parsed = _int_or_none(value)
    return parsed if parsed is not None else 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a future numbered-region calibration batch before refresh.")
    parser.add_argument("--plan", required=True, help="Path to numbered-region calibration batch plan JSON")
    parser.add_argument("--rerun-report", required=True, help="Path to future numbered-region calibration report JSON")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report_learn_fusion_calibration_batch_acceptance(
        plan_path=args.plan,
        rerun_report_path=args.rerun_report,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
