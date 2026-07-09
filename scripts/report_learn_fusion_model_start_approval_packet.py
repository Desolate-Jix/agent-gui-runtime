from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_NAME = "learn_fusion_model_start_approval_packet.json"


def report_learn_fusion_model_start_approval_packet(
    *,
    runbook_path: str | Path,
    preflight_report_path: str | Path,
    demo_readiness_report_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    runbook_file = _resolve_path(runbook_path, root)
    preflight_file = _resolve_path(preflight_report_path, root)
    demo_file = _resolve_path(demo_readiness_report_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    runbook = _read_json(runbook_file)
    preflight = _read_json(preflight_file)
    demo = _read_json(demo_file)

    runbook_commands = _dict(runbook.get("commands"))
    preflight_commands = _dict(preflight.get("commands"))
    runbook_safety = _dict(runbook.get("safety"))
    preflight_safety = _dict(preflight.get("safety"))
    demo_safety = _dict(demo.get("safety"))
    expected_outputs = _dict(runbook.get("expected_outputs"))

    ready_regions = _list_of_int(runbook.get("ready_region_numbers"))
    preflight_ready_regions = _list_of_int(preflight.get("ready_region_numbers"))
    review_regions = _list_of_int(runbook.get("review_blocked_region_numbers"))
    preflight_review_regions = _list_of_int(preflight.get("review_blocked_region_numbers"))

    blockers: list[str] = []
    blockers.extend(f"preflight:{item}" for item in _list_of_text(preflight.get("blockers")))
    blockers.extend(f"demo:{item}" for item in _list_of_text(demo.get("blockers")))
    if runbook.get("runbook_status") != "awaiting_explicit_model_start_approval":
        blockers.append("runbook_not_awaiting_explicit_model_start_approval")
    if runbook.get("approval_required") is not True:
        blockers.append("runbook_approval_not_required")
    if runbook.get("may_start_model_after_user_approval") is not True:
        blockers.append("runbook_may_start_after_approval_false")
    if runbook.get("may_run_calibration_batch_now") is not False:
        blockers.append("runbook_may_run_now_not_false")
    if preflight.get("preflight_status") != "ready_for_explicit_model_start":
        blockers.append("preflight_not_ready_for_explicit_model_start")
    if preflight.get("may_start_model_after_user_approval") is not True:
        blockers.append("preflight_may_start_after_approval_false")
    if preflight.get("may_run_calibration_batch_now") is not False:
        blockers.append("preflight_may_run_now_not_false")
    if demo.get("demo_readiness_status") != "ready_for_preflight_demo":
        blockers.append("demo_not_ready_for_preflight_demo")
    if demo.get("may_run_calibration_batch_now") is True:
        blockers.append("demo_may_run_now_true")
    if preflight.get("candidate_validation_status") != "blocked_pending_calibration":
        blockers.append("candidate_not_blocked_pending_calibration")
    if expected_outputs.get("rerun_report_status") != "awaiting_future_calibration_output":
        blockers.append("future_rerun_report_not_awaiting")
    if not ready_regions:
        blockers.append("ready_regions_missing")
    if preflight_ready_regions and preflight_ready_regions != ready_regions:
        blockers.append("ready_regions_mismatch")
    if preflight_review_regions and preflight_review_regions != review_regions:
        blockers.append("review_blocked_regions_mismatch")
    if runbook_commands.get("command_executes_now") is True or preflight_commands.get("command_executes_now") is True:
        blockers.append("calibration_command_executes_now")
    if (
        runbook_commands.get("post_batch_refresh_command_executes_now") is True
        or preflight_commands.get("post_batch_refresh_command_executes_now") is True
    ):
        blockers.append("post_batch_refresh_command_executes_now")
    if not (runbook_commands.get("calibration_command_preview") or preflight_commands.get("calibration_command_preview")):
        blockers.append("calibration_command_preview_missing")
    if not (
        runbook_commands.get("post_batch_refresh_command_preview")
        or preflight_commands.get("post_batch_refresh_command_preview")
    ):
        blockers.append("post_batch_refresh_command_preview_missing")
    if _any_true(runbook.get("execute_binding_enabled"), runbook_safety.get("execute_binding_enabled")):
        blockers.append("execute_binding_enabled")
    if _any_true(runbook.get("artifact_is_authorization"), runbook_safety.get("artifact_is_authorization")):
        blockers.append("artifact_is_authorization")
    if max(
        _int_value(runbook_safety.get("model_started")),
        _int_value(preflight_safety.get("model_started")),
        _int_value(demo_safety.get("model_started")),
    ):
        blockers.append("model_already_started")
    if max(
        _int_value(runbook_safety.get("live_clicks")),
        _int_value(preflight_safety.get("live_clicks")),
        _int_value(demo_safety.get("live_clicks")),
    ):
        blockers.append("live_clicks_detected")
    if max(
        _int_value(runbook_safety.get("live_fills")),
        _int_value(preflight_safety.get("live_fills")),
        _int_value(demo_safety.get("live_fills")),
    ):
        blockers.append("live_fills_detected")
    if max(
        _int_value(runbook_safety.get("live_submits")),
        _int_value(preflight_safety.get("live_submits")),
        _int_value(demo_safety.get("live_submits")),
    ):
        blockers.append("live_submits_detected")

    status = "blocked" if blockers else "ready_for_user_approval"
    report = {
        "contract_version": "learn_fusion_model_start_approval_packet_v1",
        "approval_packet_status": status,
        "requires_explicit_user_approval": status == "ready_for_user_approval",
        "approval_does_not_execute": True,
        "may_start_model_after_user_approval": status == "ready_for_user_approval",
        "may_run_calibration_batch_now": False,
        "next_manual_action": (
            "ask_user_to_approve_model_start_for_ready_regions"
            if status == "ready_for_user_approval"
            else "repair_approval_packet_before_model_start"
        ),
        "runbook_path": _relative_path(runbook_file, root),
        "preflight_report_path": _relative_path(preflight_file, root),
        "demo_readiness_report_path": _relative_path(demo_file, root),
        "candidate_validation_status": preflight.get("candidate_validation_status"),
        "preflight_status": preflight.get("preflight_status"),
        "demo_readiness_status": demo.get("demo_readiness_status"),
        "ready_region_numbers": ready_regions,
        "review_blocked_region_numbers": review_regions,
        "commands": {
            "calibration_command_preview": runbook_commands.get("calibration_command_preview")
            or preflight_commands.get("calibration_command_preview"),
            "post_batch_refresh_command_preview": runbook_commands.get("post_batch_refresh_command_preview")
            or preflight_commands.get("post_batch_refresh_command_preview"),
            "command_executes_now": False,
            "post_batch_refresh_command_executes_now": False,
        },
        "expected_outputs": {
            "rerun_report_status": expected_outputs.get("rerun_report_status"),
            "rerun_report_path": expected_outputs.get("rerun_report_path"),
            "post_batch_refresh_requires_completed_batch": True,
        },
        "safety": {
            "model_started": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "final_submit_forbidden": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "display_only_until_explicit_approval": True,
        },
        "blockers": sorted(set(blockers)),
        "interpretation": (
            "Offline approval packet for asking the user whether to start the learn-fusion locate model. "
            "Generating this packet does not start models, run calibration, click, fill, submit, refresh, merge, "
            "or promote Runtime PathGraph."
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


def _any_true(*values: Any) -> bool:
    return any(value is True for value in values)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a no-execute learn-fusion model-start approval packet.")
    parser.add_argument("--runbook", required=True, help="learn_fusion_model_start_runbook.json")
    parser.add_argument("--preflight-report", required=True, help="learn_fusion_model_start_preflight_report.json")
    parser.add_argument("--demo-readiness-report", required=True, help="learn_fusion_demo_readiness_report.json")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    report = report_learn_fusion_model_start_approval_packet(
        runbook_path=args.runbook,
        preflight_report_path=args.preflight_report,
        demo_readiness_report_path=args.demo_readiness_report,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0 if report.get("approval_packet_status") == "ready_for_user_approval" else 1


if __name__ == "__main__":
    raise SystemExit(main())
