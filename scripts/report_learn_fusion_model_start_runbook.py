from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "learn_fusion_model_start_runbook.json"


def report_learn_fusion_model_start_runbook(
    *,
    batch_plan_path: str | Path,
    handoff_report_path: str | Path,
    acceptance_report_path: str | Path,
    consistency_report_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    plan_file = _resolve_path(batch_plan_path, root)
    handoff_file = _resolve_path(handoff_report_path, root)
    acceptance_file = _resolve_path(acceptance_report_path, root)
    consistency_file = _resolve_path(consistency_report_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    plan = _read_json(plan_file)
    handoff = _read_json(handoff_file)
    acceptance = _read_json(acceptance_file)
    consistency = _read_json(consistency_file)

    handoff_commands = _dict(handoff.get("commands"))
    handoff_future = _dict(handoff.get("future_outputs"))
    consistency_summary = _dict(consistency.get("summary"))
    consistency_safety = _dict(consistency.get("safety"))
    handoff_safety = _dict(handoff.get("safety"))
    acceptance_safety = _dict(acceptance.get("safety"))

    ready_regions = _list_of_int(handoff.get("ready_region_numbers")) or _list_of_int(plan.get("ready_region_numbers"))
    review_regions = _list_of_int(handoff.get("review_blocked_region_numbers")) or _list_of_int(
        plan.get("review_blocked_region_numbers")
    )
    refresh_args = _list_of_text(handoff_commands.get("post_batch_refresh_command_args")) or _list_of_text(
        plan.get("post_batch_refresh_command_args")
    )
    has_batch_plan = (
        consistency_summary.get("post_batch_refresh_has_batch_plan") is True
        or "--batch-plan" in refresh_args
        or "--batch-plan" in str(handoff_commands.get("post_batch_refresh_command_preview") or "")
        or "--batch-plan" in str(plan.get("post_batch_refresh_command_preview") or "")
    )
    prebatch_refresh_blocks = consistency_summary.get("refresh_blocks_before_future_rerun") is True

    blockers: list[str] = []
    blockers.extend(f"handoff:{item}" for item in _list_of_text(handoff.get("blockers")))
    blockers.extend(f"acceptance:{item}" for item in _list_of_text(acceptance.get("blockers")) if item != "rerun_report_missing")
    blockers.extend(f"consistency:{item}" for item in _list_of_text(consistency.get("blockers")))
    if plan.get("command_executes_now") is True or handoff_commands.get("command_executes_now") is True:
        blockers.append("calibration_command_executes_now")
    if plan.get("post_batch_refresh_command_executes_now") is True or handoff_commands.get("post_batch_refresh_command_executes_now") is True:
        blockers.append("post_batch_refresh_command_executes_now")
    if plan.get("execute_binding_enabled") is True or handoff_safety.get("execute_binding_enabled") is True:
        blockers.append("execute_binding_enabled")
    if plan.get("artifact_is_authorization") is True or handoff_safety.get("artifact_is_authorization") is True:
        blockers.append("artifact_is_authorization")
    if not ready_regions:
        blockers.append("ready_regions_missing")
    if not has_batch_plan:
        blockers.append("post_batch_refresh_missing_batch_plan")
    if not prebatch_refresh_blocks:
        blockers.append("prebatch_refresh_block_not_verified")
    if _int_value(consistency_safety.get("model_started")):
        blockers.append("model_already_started_in_consistency_report")
    if _int_value(consistency_safety.get("live_clicks")) or _int_value(handoff_safety.get("real_clicks")) or _int_value(
        acceptance_safety.get("real_clicks")
    ):
        blockers.append("live_clicks_detected")

    handoff_ready = handoff.get("handoff_status") == "ready_for_explicit_model_start"
    consistency_ready = consistency.get("consistency_status") == "ready_for_explicit_model_start"
    acceptance_waiting = acceptance.get("acceptance_status") == "awaiting_future_calibration_output"
    accepted_for_refresh = acceptance.get("ready_for_post_batch_refresh") is True

    if blockers:
        status = "blocked"
    elif accepted_for_refresh:
        status = "ready_for_post_batch_refresh"
    elif handoff_ready and consistency_ready and acceptance_waiting:
        status = "awaiting_explicit_model_start_approval"
    else:
        status = "blocked"
        blockers.append("unexpected_handoff_acceptance_state")

    may_start_after_approval = status == "awaiting_explicit_model_start_approval"
    report = {
        "contract_version": "learn_fusion_model_start_runbook_v1",
        "runbook_status": status,
        "approval_required": may_start_after_approval,
        "may_start_model_after_user_approval": may_start_after_approval,
        "may_run_calibration_batch_now": False,
        "next_manual_action": _next_manual_action(status),
        "batch_plan_path": _relative_path(plan_file, root),
        "handoff_report_path": _relative_path(handoff_file, root),
        "acceptance_report_path": _relative_path(acceptance_file, root),
        "consistency_report_path": _relative_path(consistency_file, root),
        "ready_region_numbers": ready_regions,
        "review_blocked_region_numbers": review_regions,
        "commands": {
            "calibration_command_preview": handoff_commands.get("calibration_command_preview") or plan.get("run_command_preview"),
            "post_batch_refresh_command_preview": handoff_commands.get("post_batch_refresh_command_preview")
            or plan.get("post_batch_refresh_command_preview"),
            "post_batch_refresh_command_args": refresh_args,
            "command_executes_now": False,
            "post_batch_refresh_command_executes_now": False,
        },
        "expected_outputs": {
            "rerun_report_path": handoff_future.get("rerun_report_path"),
            "rerun_report_status": handoff_future.get("rerun_report_status"),
            "post_batch_refresh_requires_completed_batch": True,
        },
        "guards": {
            "post_batch_refresh_has_batch_plan": has_batch_plan,
            "prebatch_refresh_blocks_before_future_rerun": prebatch_refresh_blocks,
            "acceptance_required_before_refresh": True,
            "accepted_for_post_batch_refresh": accepted_for_refresh,
        },
        "safety": {
            "model_started": bool(_int_value(consistency_safety.get("model_started"))),
            "live_clicks": max(
                _int_value(consistency_safety.get("live_clicks")),
                _int_value(handoff_safety.get("real_clicks")),
                _int_value(acceptance_safety.get("real_clicks")),
            ),
            "live_fills": _int_value(consistency_safety.get("live_fills")),
            "live_submits": _int_value(consistency_safety.get("live_submits")),
            "final_submit_forbidden": True,
            "display_only_until_user_approval": True,
        },
        "blockers": sorted(set(blockers)),
        "warnings": [],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Offline runbook for the next numbered-region calibration batch. "
            "It does not start models, click, fill, submit, refresh, merge, or promote Runtime PathGraph."
        ),
    }
    report_path = out / REPORT_NAME
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _next_manual_action(status: str) -> str:
    if status == "awaiting_explicit_model_start_approval":
        return "ask_user_to_approve_model_start_for_ready_regions"
    if status == "ready_for_post_batch_refresh":
        return "run_gated_post_batch_refresh"
    return "repair_handoff_package_before_model_start"


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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_text(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


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
    parser = argparse.ArgumentParser(description="Build the next learn-fusion model-start runbook without executing it.")
    parser.add_argument("--batch-plan", required=True, help="numbered_region_calibration_batch_plan.json")
    parser.add_argument("--handoff-report", required=True, help="learn_fusion_calibration_handoff_report.json")
    parser.add_argument("--acceptance-report", required=True, help="learn_fusion_calibration_batch_acceptance_report.json")
    parser.add_argument("--consistency-report", required=True, help="learn_fusion_handoff_consistency_report.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report_learn_fusion_model_start_runbook(
        batch_plan_path=args.batch_plan,
        handoff_report_path=args.handoff_report,
        acceptance_report_path=args.acceptance_report,
        consistency_report_path=args.consistency_report,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
