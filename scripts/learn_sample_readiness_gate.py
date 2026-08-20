from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_CHECKPOINT = Path("logs/smoke/learn_execute_mvp_checkpoint_20260620.json")
DEFAULT_REGRESSION = Path("logs/smoke/artifact_replay_regression_20260619.json")
DEFAULT_TEMPLATE = Path("artifacts/templates/learn_sample_template_v1.json")


def read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def check(check_id: str, passed: bool, message: str, evidence: Any = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "message": message,
    }
    if evidence is not None:
        item["evidence"] = evidence
    return item


def build_readiness_gate(
    checkpoint: dict[str, Any],
    regression: dict[str, Any],
    *,
    template_path: Path = DEFAULT_TEMPLATE,
) -> dict[str, Any]:
    checkpoint_summary = checkpoint.get("summary") if isinstance(checkpoint.get("summary"), dict) else {}
    regression_summary = regression.get("summary") if isinstance(regression.get("summary"), dict) else {}
    regression_gate = regression.get("regression_gate") if isinstance(regression.get("regression_gate"), dict) else {}
    baseline_count = int(regression_summary.get("baseline_count") or 0)
    passed_count = int(regression_summary.get("passed") or 0)
    required_coverage = [
        "covers_click",
        "covers_scroll",
        "covers_input",
        "covers_read",
        "covers_guarded_actions",
        "covers_filter_or_tab",
        "covers_sort_or_filter_click",
        "covers_table_record_open",
    ]
    coverage_checks = [
        check(
            key,
            checkpoint_summary.get(key) is True,
            f"checkpoint summary requires {key}=true",
            checkpoint_summary.get(key),
        )
        for key in required_coverage
    ]
    checks = [
        check("checkpoint_status", checkpoint.get("status") == "pass", "Learn/Execute checkpoint passed", checkpoint.get("status")),
        check(
            "seek_application_flow",
            checkpoint_summary.get("seek_application_flow") == "pass",
            "SEEK station-internal application-flow artifact checkpoint passed",
            checkpoint_summary.get("seek_application_flow"),
        ),
        check(
            "seek_application_final_submit_forbidden",
            checkpoint_summary.get("seek_application_final_submit_forbidden") is True,
            "SEEK application-flow artifact keeps final submit forbidden",
            checkpoint_summary.get("seek_application_final_submit_forbidden"),
        ),
        check(
            "seek_application_safe_fill_required",
            checkpoint_summary.get("seek_application_safe_fill_required") is True,
            "SEEK application-flow replay requires safe-fill verification",
            checkpoint_summary.get("seek_application_safe_fill_required"),
        ),
        check(
            "seek_application_flow_replay",
            checkpoint_summary.get("seek_application_flow_replay") == "pass"
            and checkpoint_summary.get("seek_application_can_run_live_strict_replay") is True,
            "SEEK application-flow dry-run replay plan is ready for live strict replay",
            {
                "seek_application_flow_replay": checkpoint_summary.get("seek_application_flow_replay"),
                "seek_application_can_run_live_strict_replay": checkpoint_summary.get("seek_application_can_run_live_strict_replay"),
            },
        ),
        check(
            "regression_status",
            regression.get("status") == "pass" and regression_gate.get("can_continue_to_new_family") is True,
            "artifact replay regression passed and allows a new family",
            {"status": regression.get("status"), "can_continue_to_new_family": regression_gate.get("can_continue_to_new_family")},
        ),
        check(
            "five_baselines",
            baseline_count >= 5 and passed_count == baseline_count,
            "at least five learned baselines passed",
            {"baseline_count": baseline_count, "passed": passed_count},
        ),
        *coverage_checks,
        check(
            "artifact_not_authorization",
            checkpoint_summary.get("artifact_authorizes_click") is False,
            "learned artifacts remain evidence, not click authorization",
            checkpoint_summary.get("artifact_authorizes_click"),
        ),
        check(
            "write_guard",
            int(checkpoint_summary.get("write_actions_clicked") or 0) == 0,
            "checkpoint clicked no write actions",
            checkpoint_summary.get("write_actions_clicked"),
        ),
        check(
            "final_submit_guard",
            int(checkpoint_summary.get("final_submissions") or 0) == 0,
            "checkpoint made no final submissions",
            checkpoint_summary.get("final_submissions"),
        ),
        check(
            "template_available",
            template_path.exists(),
            "learn_sample_template_v1 is available for the next sample",
            str(template_path),
        ),
    ]
    blockers = [item for item in checks if item["status"] != "pass"]
    return {
        "contract_version": "learn_sample_readiness_gate_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not blockers else "fail",
        "ready_for_new_learn_sample": not blockers,
        "next_sample_policy": {
            "codex_in_app_browser": "chatgpt_only",
            "test_panel_target": "external_browser_or_native_app",
            "required_sequence": [
                "observe_or_available_actions_dry_run",
                "execute_step_dry_run",
                "single_safe_live_action",
                "small_task_run",
                "add_to_regression_suite",
            ],
        },
        "inputs": {
            "checkpoint_contract": checkpoint.get("contract_version"),
            "regression_contract": regression.get("contract_version"),
            "template_path": str(template_path),
        },
        "summary": {
            "baseline_count": baseline_count,
            "passed_baselines": passed_count,
            "skill_count": checkpoint_summary.get("skill_count"),
            "covers_click": checkpoint_summary.get("covers_click"),
            "covers_scroll": checkpoint_summary.get("covers_scroll"),
            "covers_input": checkpoint_summary.get("covers_input"),
            "covers_read": checkpoint_summary.get("covers_read"),
            "covers_guarded_actions": checkpoint_summary.get("covers_guarded_actions"),
            "seek_application_flow": checkpoint_summary.get("seek_application_flow"),
            "seek_application_final_submit_forbidden": checkpoint_summary.get("seek_application_final_submit_forbidden"),
            "seek_application_safe_fill_required": checkpoint_summary.get("seek_application_safe_fill_required"),
            "seek_application_flow_replay": checkpoint_summary.get("seek_application_flow_replay"),
            "seek_application_can_run_live_strict_replay": checkpoint_summary.get("seek_application_can_run_live_strict_replay"),
            "artifact_authorizes_click": checkpoint_summary.get("artifact_authorizes_click"),
            "write_actions_clicked": checkpoint_summary.get("write_actions_clicked"),
            "final_submissions": checkpoint_summary.get("final_submissions"),
        },
        "checks": checks,
        "blocking_failures": blockers,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate whether a new Learn Mode sample may start.")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--regression", type=Path, default=DEFAULT_REGRESSION)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--out", type=Path, default=Path("logs/smoke/learn_sample_readiness_gate_20260620.json"))
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)

    gate = build_readiness_gate(read_json(args.checkpoint), read_json(args.regression), template_path=args.template)
    write_json(args.out, gate)
    print(
        json.dumps(
            {
                "success": gate["status"] == "pass",
                "status": gate["status"],
                "ready_for_new_learn_sample": gate["ready_for_new_learn_sample"],
                "summary": gate["summary"],
                "out": str(args.out),
            },
            ensure_ascii=False,
        )
    )
    if args.fail_on_error and gate["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
