from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PLAN_NAME = "numbered_region_calibration_batch_plan.json"


def build_numbered_region_calibration_batch_plan(
    *,
    report_path: str | Path,
    out_dir: str | Path,
    trial_path: str | Path | None = None,
    base_status_path: str | Path | None = None,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    report_file = _resolve_path(report_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)
    report = _read_json(report_file)
    backlog = report.get("calibration_backlog") if isinstance(report.get("calibration_backlog"), dict) else {}
    items = _list_of_dicts(backlog.get("items"))
    ready_items = [item for item in items if item.get("ready_for_execute_dry_run") is True]
    review_blocked_items = [item for item in items if item.get("ready_for_execute_dry_run") is not True]
    ready_region_numbers = sorted(_region_no(item) for item in ready_items if _region_no(item) > 0)
    review_blocked_region_numbers = sorted(_region_no(item) for item in review_blocked_items if _region_no(item) > 0)
    next_out = out / "next_numbered_region_calibration"
    plan_path = out / PLAN_NAME
    command_args = _run_command_args(report=report, ready_region_numbers=ready_region_numbers, next_out=next_out)
    post_batch_refresh_args = _post_batch_refresh_command_args(
        trial_path=trial_path,
        base_status_path=base_status_path,
        rerun_report_path=next_out / "numbered_region_calibration_report.json",
        batch_plan_path=plan_path,
        out_dir=out / "post_batch_refresh",
    )

    plan = {
        "contract_version": "numbered_region_calibration_batch_plan_v1",
        "source_report_path": _relative_path(report_file, root),
        "summary": {
            "ready_for_execute_dry_run": len(ready_items),
            "review_before_calibration": len(review_blocked_items),
            "real_clicks": 0,
            "display_only": True,
            "execute_binding_enabled": False,
        },
        "ready_region_numbers": ready_region_numbers,
        "review_blocked_region_numbers": review_blocked_region_numbers,
        "ready_items": ready_items,
        "review_blocked_items": review_blocked_items,
        "run_command_args": command_args,
        "run_command_preview": " ".join(command_args),
        "command_executes_now": False,
        "post_batch_refresh_command_args": post_batch_refresh_args,
        "post_batch_refresh_command_preview": " ".join(post_batch_refresh_args),
        "post_batch_refresh_command_executes_now": False,
        "post_batch_refresh_requires_completed_batch": bool(post_batch_refresh_args),
        "requires_user_or_runner_to_start_model": True,
        "start_model_flag_included": False,
        "next_output_dir": str(next_out.resolve()),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "interpretation": (
            "Offline plan for the next numbered-region Execute dry-run calibration batch. "
            "This script does not start models, click, fill, submit, or promote PathGraph assets."
        ),
    }
    plan["plan_path"] = str(plan_path.resolve())
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "numbered_region_calibration_batch_plan_build_result_v1",
        "plan_path": str(plan_path.resolve()),
        "summary": plan["summary"],
        "command_executes_now": False,
        "post_batch_refresh_command_executes_now": False,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _run_command_args(*, report: dict[str, Any], ready_region_numbers: list[int], next_out: Path) -> list[str]:
    source_arg, source_value = _calibration_source_arg(report)
    args = [
        "uv",
        "run",
        "python",
        "scripts\\run_numbered_region_calibration_probe.py",
        source_arg,
        source_value,
        "--out",
        str(next_out.resolve()),
        "--regions",
        ",".join(str(item) for item in ready_region_numbers),
    ]
    parser_output = _text(report.get("parser_output_path"))
    if parser_output and report.get("enriched_tasks_path"):
        args.extend(["--parser-output", parser_output, "--enrich-prompts"])
    return args


def _post_batch_refresh_command_args(
    *,
    trial_path: str | Path | None,
    base_status_path: str | Path | None,
    rerun_report_path: Path,
    batch_plan_path: Path,
    out_dir: Path,
) -> list[str]:
    trial = _text(trial_path)
    base_status = _text(base_status_path)
    if not trial or not base_status:
        return []
    return [
        "uv",
        "run",
        "python",
        "scripts\\refresh_learn_fusion_after_calibration_batch.py",
        "--trial",
        trial,
        "--base-status",
        base_status,
        "--rerun-report",
        str(rerun_report_path.resolve()),
        "--batch-plan",
        str(batch_plan_path.resolve()),
        "--out",
        str(out_dir.resolve()),
    ]


def _calibration_source_arg(report: dict[str, Any]) -> tuple[str, str]:
    for key in ("generated_tasks_path", "enriched_tasks_path", "tasks_path", "source_tasks_path"):
        value = _text(report.get(key))
        if value:
            return "--tasks", value
    value = _text(report.get("actual_parser_output_path"))
    if value:
        return "--actual-parser-output", value
    raise ValueError("source report does not contain generated_tasks_path, tasks_path, or actual_parser_output_path")


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


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _region_no(item: dict[str, Any]) -> int:
    try:
        return int(item.get("region_no") or 0)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an offline plan for the next numbered-region calibration batch.")
    parser.add_argument("--report", required=True, help="Path to numbered_region_calibration_report.json or compatible fusion report")
    parser.add_argument("--trial", help="Optional Learning Draft trial path for post-batch refresh command preview")
    parser.add_argument("--base-status", help="Optional base fusion status path for post-batch refresh command preview")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    build_numbered_region_calibration_batch_plan(
        report_path=args.report,
        trial_path=args.trial,
        base_status_path=args.base_status,
        out_dir=args.out,
        json_stdout=args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
