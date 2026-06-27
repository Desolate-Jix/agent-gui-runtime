from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "seek_demo_goal_completion_audit_v1"
DEFAULT_TIME_BUDGET_MS = 5 * 60 * 1000


def read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_step_reports(run_dir: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    if not run_dir.exists():
        return reports
    for path in sorted(run_dir.rglob("step_report.json")):
        report = read_json(path)
        report["_source_path"] = str(path)
        reports.append(report)
    return reports


def build_goal_completion_audit(
    *,
    run_dir: Path,
    speed_report: dict[str, Any] | None = None,
    readiness_report: dict[str, Any] | None = None,
    application_fill_record: dict[str, Any] | None = None,
    final_review_extraction: dict[str, Any] | None = None,
    step_reports: list[dict[str, Any]] | None = None,
    time_budget_ms: int = DEFAULT_TIME_BUDGET_MS,
) -> dict[str, Any]:
    speed_report = speed_report or _optional_json(run_dir / "speed_demo_report.json")
    readiness_report = readiness_report or _optional_json(run_dir / "demo_readiness_report.json")
    application_fill_record = application_fill_record or _optional_json(run_dir / "application_fill_record.json")
    final_review_extraction = final_review_extraction or _optional_json(run_dir / "final_review_extraction.json")
    reports = step_reports if step_reports is not None else load_step_reports(run_dir)

    checks = [
        _adaptive_scroll_check(speed_report, readiness_report),
        _batch_read_check(readiness_report, reports),
        _screen_understanding_check(reports),
        _form_fill_visual_check(application_fill_record, reports),
        _diff_verifier_check(reports),
        _time_and_safety_check(speed_report, readiness_report, application_fill_record, final_review_extraction, time_budget_ms),
    ]
    blockers = [item for item in checks if item["status"] != "pass"]
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "status": "pass" if not blockers else "needs_work",
        "time_budget_ms": time_budget_ms,
        "summary": {
            "check_count": len(checks),
            "passed": len(checks) - len(blockers),
            "failed": len(blockers),
            "total_ms": _number(speed_report.get("total_ms")),
            "within_budget": _truthy(speed_report.get("within_budget")),
            "readiness_status": readiness_report.get("status"),
            "final_review_status": final_review_extraction.get("status"),
            "final_submissions": _max_int(
                speed_report.get("final_submissions"),
                readiness_report.get("summary", {}).get("final_submissions") if isinstance(readiness_report.get("summary"), dict) else None,
                application_fill_record.get("final_submissions"),
                final_review_extraction.get("final_submissions"),
            ),
            "submit_clicks": _max_int(
                speed_report.get("submit_clicks"),
                readiness_report.get("summary", {}).get("submit_clicks") if isinstance(readiness_report.get("summary"), dict) else None,
                application_fill_record.get("submit_clicks"),
                final_review_extraction.get("submit_clicks"),
            ),
        },
        "checks": checks,
        "blocking_failures": blockers,
    }


def _adaptive_scroll_check(speed_report: dict[str, Any], readiness_report: dict[str, Any]) -> dict[str, Any]:
    result_scrolls = speed_report.get("result_scrolls") if isinstance(speed_report.get("result_scrolls"), list) else []
    changed = [item for item in result_scrolls if item.get("card_fingerprint_changed") is True]
    escalated = [item for item in result_scrolls if (_integer(item.get("wheel_clicks")) or 0) >= 8]
    return _check(
        "adaptive_scroll",
        bool(changed or escalated),
        "Result-list scrolling must adapt or prove that visible card content changed.",
        {
            "result_scroll_count": len(result_scrolls),
            "changed_count": len(changed),
            "max_wheel_clicks": max([_integer(item.get("wheel_clicks")) or 0 for item in result_scrolls] or [0]),
            "readiness_long_read_strategy": _nested(readiness_report, ["summary", "long_read_strategy"]),
        },
    )


def _batch_read_check(readiness_report: dict[str, Any], step_reports: list[dict[str, Any]]) -> dict[str, Any]:
    long_read = readiness_report.get("long_read") if isinstance(readiness_report.get("long_read"), dict) else {}
    unique_lines = _integer(long_read.get("batch_unique_line_count")) or 0
    batch_steps = [report for report in step_reports if isinstance(report.get("read_region_batch"), dict)]
    return _check(
        "multi_capture_batch_read",
        unique_lines > 0 and bool(batch_steps),
        "Long detail reading must use multi-capture batch OCR instead of tiny repeated human-paced scroll reads.",
        {
            "batch_unique_line_count": unique_lines,
            "batch_step_count": len(batch_steps),
            "strategy": long_read.get("strategy"),
        },
    )


def _screen_understanding_check(step_reports: list[dict[str, Any]]) -> dict[str, Any]:
    application_steps = [
        report
        for report in step_reports
        if str(report.get("step_name") or "").startswith("continue_application_flow")
        or str(report.get("step_name") or "") == "extract_final_review"
    ]
    observed_steps = [
        report
        for report in application_steps
        if isinstance(report.get("execute_observation"), dict)
        and report["execute_observation"].get("contract_version") == "execute_observation_v1"
    ]
    observe_traces = [
        trace
        for report in application_steps
        for trace in report.get("trace_paths") or []
        if "observe-screen" in str(trace)
    ]
    return _check(
        "screen_understanding_after_page_change",
        bool(application_steps) and len(observed_steps) == len(application_steps) and bool(observe_traces),
        "After entering application pages, each application step should record execute-scoped screen understanding evidence.",
        {
            "application_step_count": len(application_steps),
            "execute_observation_count": len(observed_steps),
            "observe_trace_count": len(observe_traces),
        },
    )


def _form_fill_visual_check(application_fill_record: dict[str, Any], step_reports: list[dict[str, Any]]) -> dict[str, Any]:
    filled_fields = application_fill_record.get("filled_fields") if isinstance(application_fill_record.get("filled_fields"), list) else []
    form_steps = [report for report in step_reports if isinstance(report.get("form_field_inventory"), dict)]
    post_fill = [report for report in step_reports if _contains_text(report, "post_fill_verification")]
    scroll_evidence = [report for report in form_steps if _contains_text(report, "scroll")]
    return _check(
        "visual_form_fill_with_scroll_and_verification",
        bool(filled_fields) and bool(form_steps) and bool(post_fill) and bool(scroll_evidence),
        "Form filling should use visible form inventory, page/field scroll evidence, and post-fill verification.",
        {
            "filled_field_count": len(filled_fields),
            "form_inventory_step_count": len(form_steps),
            "post_fill_verification_step_count": len(post_fill),
            "scroll_evidence_step_count": len(scroll_evidence),
        },
    )


def _diff_verifier_check(step_reports: list[dict[str, Any]]) -> dict[str, Any]:
    diff_steps = [
        report
        for report in step_reports
        if isinstance(report.get("ui_diff_verification"), dict)
        and report["ui_diff_verification"].get("contract_version") == "ui_diff_verification_v1"
    ]
    return _check(
        "diff_verifier_present",
        bool(diff_steps),
        "Before/after verification should include ui_diff_verification_v1 so changed regions can be reviewed without full-screen rereads.",
        {"ui_diff_step_count": len(diff_steps)},
    )


def _time_and_safety_check(
    speed_report: dict[str, Any],
    readiness_report: dict[str, Any],
    application_fill_record: dict[str, Any],
    final_review_extraction: dict[str, Any],
    time_budget_ms: int,
) -> dict[str, Any]:
    total_ms = _number(speed_report.get("total_ms"))
    final_submissions = _max_int(
        speed_report.get("final_submissions"),
        readiness_report.get("summary", {}).get("final_submissions") if isinstance(readiness_report.get("summary"), dict) else None,
        application_fill_record.get("final_submissions"),
        final_review_extraction.get("final_submissions"),
    )
    submit_clicks = _max_int(
        speed_report.get("submit_clicks"),
        readiness_report.get("summary", {}).get("submit_clicks") if isinstance(readiness_report.get("summary"), dict) else None,
        application_fill_record.get("submit_clicks"),
        final_review_extraction.get("submit_clicks"),
    )
    passed = (
        total_ms is not None
        and total_ms <= time_budget_ms
        and readiness_report.get("status") == "pass"
        and final_review_extraction.get("status") == "pass"
        and final_submissions == 0
        and submit_clicks == 0
    )
    return _check(
        "five_minute_review_boundary_no_submit",
        passed,
        "The demo must reach Review and submit within five minutes without clicking final submit.",
        {
            "total_ms": total_ms,
            "time_budget_ms": time_budget_ms,
            "readiness_status": readiness_report.get("status"),
            "final_review_status": final_review_extraction.get("status"),
            "final_submissions": final_submissions,
            "submit_clicks": submit_clicks,
        },
    )


def _check(check_id: str, passed: bool, message: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "message": message,
        "evidence": evidence,
    }


def _optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def _nested(value: dict[str, Any], path: list[str]) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _max_int(*values: Any) -> int:
    integers = [_integer(value) for value in values]
    present = [value for value in integers if value is not None]
    return max(present) if present else 0


def _truthy(value: Any) -> bool:
    return value is True or str(value).casefold() in {"true", "yes", "1", "pass"}


def _contains_text(value: Any, needle: str) -> bool:
    if isinstance(value, dict):
        return any(needle.casefold() in str(key).casefold() or _contains_text(item, needle) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_text(item, needle) for item in value)
    return needle.casefold() in str(value).casefold()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit whether a SEEK speed demo proves the original optimization goal.")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--time-budget-ms", type=int, default=DEFAULT_TIME_BUDGET_MS)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)

    report = build_goal_completion_audit(run_dir=args.run_dir, time_budget_ms=args.time_budget_ms)
    out = args.out or args.run_dir / "goal_completion_audit.json"
    write_json(out, report)
    print(json.dumps({"success": report["status"] == "pass", "status": report["status"], "summary": report["summary"], "out": str(out)}, ensure_ascii=False))
    if args.fail_on_error and report["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
