from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "seek_demo_readiness_report_v1"
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


def build_demo_readiness_report(
    *,
    run_dir: Path | None,
    step_reports: list[dict[str, Any]],
    application_fill_record: dict[str, Any] | None = None,
    final_review_audit: dict[str, Any] | None = None,
    long_read_benchmark: dict[str, Any] | None = None,
    time_budget_ms: int = DEFAULT_TIME_BUDGET_MS,
) -> dict[str, Any]:
    final_submissions = _final_submissions(step_reports, application_fill_record, final_review_audit)
    submit_clicks = _submit_clicks(step_reports, application_fill_record, final_review_audit)
    review_reached = _review_reached(step_reports, application_fill_record, final_review_audit)
    application_started = _application_started(step_reports, application_fill_record)
    long_read = _long_read_summary(step_reports, long_read_benchmark)
    screenshots = _screenshots(step_reports)
    traces = _trace_paths(step_reports)
    timings = _timing_summary(step_reports)
    duration_ms = timings.get("duration_ms")
    checks = [
        _check("opened_or_selected_job", _has_step(step_reports, {"execute_card", "verify_detail", "match"}), "At least one job card/detail was opened or verified."),
        _check("detail_read_evidence", long_read["has_batch_read"] or _has_step(step_reports, {"read_detail_scroll"}), "Job detail has batch or scroll-read evidence.", long_read),
        _check("application_started", application_started, "A station-internal application flow was reached."),
        _check("review_page_reached", review_reached, "Run reached Review and submit or final-review audit evidence."),
        _check("no_final_submission", final_submissions == 0 and submit_clicks == 0, "Final submission remains untouched.", {"final_submissions": final_submissions, "submit_clicks": submit_clicks}),
        _check("has_screenshot_evidence", len(screenshots) >= 3, "Step reports include before/after/observe screenshot evidence.", {"screenshot_count": len(screenshots)}),
        _check("has_trace_evidence", len(traces) >= 1, "Step reports include trace evidence.", {"trace_count": len(traces)}),
    ]
    if duration_ms is not None:
        checks.append(
            _check(
                "within_demo_time_budget",
                duration_ms <= time_budget_ms,
                "Run is within the configured demo time budget.",
                {"duration_ms": duration_ms, "time_budget_ms": time_budget_ms},
            )
        )
    else:
        checks.append(
            _check(
                "within_demo_time_budget",
                False,
                "Run duration could not be measured from step timestamps.",
                {"time_budget_ms": time_budget_ms},
            )
        )
    blockers = [item for item in checks if item["status"] != "pass"]
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not blockers else "needs_work",
        "run_dir": str(run_dir) if run_dir else None,
        "time_budget_ms": time_budget_ms,
        "summary": {
            "step_count": len(step_reports),
            "duration_ms": duration_ms,
            "review_page_reached": review_reached,
            "application_started": application_started,
            "final_submissions": final_submissions,
            "submit_clicks": submit_clicks,
            "screenshot_count": len(screenshots),
            "trace_count": len(traces),
            "long_read_strategy": long_read["strategy"],
            "long_read_recommended_path": long_read.get("recommended_path"),
        },
        "long_read": long_read,
        "timings": timings,
        "evidence": {
            "screenshots": screenshots[:80],
            "trace_paths": traces[:80],
            "application_fill_record_contract": application_fill_record.get("contract_version") if isinstance(application_fill_record, dict) else None,
            "final_review_audit_decision": _nested(final_review_audit or {}, ["decision"]) or _nested(final_review_audit or {}, ["summary", "decision"]),
        },
        "checks": checks,
        "blocking_failures": blockers,
    }


def _check(check_id: str, passed: bool, message: str, evidence: Any = None) -> dict[str, Any]:
    item: dict[str, Any] = {"check_id": check_id, "status": "pass" if passed else "fail", "message": message}
    if evidence is not None:
        item["evidence"] = evidence
    return item


def _has_step(step_reports: list[dict[str, Any]], names: set[str]) -> bool:
    return any(str(report.get("step_name") or "") in names for report in step_reports)


def _application_started(step_reports: list[dict[str, Any]], application_fill_record: dict[str, Any] | None) -> bool:
    if application_fill_record:
        return True
    return any(str(report.get("step_name") or "") in {"execute_apply_entry", "continue_application_flow", "extract_final_review"} for report in step_reports)


def _review_reached(
    step_reports: list[dict[str, Any]],
    application_fill_record: dict[str, Any] | None,
    final_review_audit: dict[str, Any] | None,
) -> bool:
    if _truthy(_nested(final_review_audit or {}, ["summary", "review_page_reached"])):
        return True
    decision = str(_nested(final_review_audit or {}, ["decision"]) or _nested(final_review_audit or {}, ["summary", "decision"]) or "")
    if "stopped_before_final_submit" in decision:
        return True
    if application_fill_record and _contains_text(application_fill_record, "review_and_submit"):
        return True
    for report in step_reports:
        flow = report.get("application_flow_state") if isinstance(report.get("application_flow_state"), dict) else {}
        if flow.get("current_step") == "review_and_submit" or flow.get("state_type") == "final_submit_visible":
            return True
        observation = report.get("execute_observation") if isinstance(report.get("execute_observation"), dict) else {}
        if observation.get("page_state") == "review_before_submit":
            return True
    return False


def _final_submissions(
    step_reports: list[dict[str, Any]],
    application_fill_record: dict[str, Any] | None,
    final_review_audit: dict[str, Any] | None,
) -> int:
    values = [_integer(_nested(final_review_audit or {}, ["summary", "final_submissions"]))]
    values.append(_integer((final_review_audit or {}).get("final_submissions")))
    values.append(_integer((application_fill_record or {}).get("final_submissions")))
    for report in step_reports:
        values.append(_integer(report.get("final_submissions")))
        extraction = report.get("final_review_extraction") if isinstance(report.get("final_review_extraction"), dict) else {}
        values.append(_integer(extraction.get("final_submissions")))
    present = [value for value in values if value is not None]
    return max(present) if present else 0


def _submit_clicks(
    step_reports: list[dict[str, Any]],
    application_fill_record: dict[str, Any] | None,
    final_review_audit: dict[str, Any] | None,
) -> int:
    values = [_integer(_nested(final_review_audit or {}, ["summary", "submit_clicks"]))]
    values.append(_integer((final_review_audit or {}).get("submit_clicks")))
    values.append(_integer((application_fill_record or {}).get("submit_clicks")))
    for report in step_reports:
        values.append(_integer(report.get("submit_clicks")))
        extraction = report.get("final_review_extraction") if isinstance(report.get("final_review_extraction"), dict) else {}
        values.append(_integer(extraction.get("submit_clicks")))
    present = [value for value in values if value is not None]
    return max(present) if present else 0


def _long_read_summary(step_reports: list[dict[str, Any]], benchmark: dict[str, Any] | None) -> dict[str, Any]:
    batch_reports = [report for report in step_reports if isinstance(report.get("read_region_batch"), dict)]
    scroll_reports = [report for report in step_reports if isinstance(report.get("right_detail_scroll_validation"), dict)]
    strategy = "read_detail_batch" if batch_reports else ("read_detail_scroll" if scroll_reports else "none")
    return {
        "strategy": strategy,
        "has_batch_read": bool(batch_reports),
        "batch_report_count": len(batch_reports),
        "scroll_report_count": len(scroll_reports),
        "batch_unique_line_count": sum(_integer(_nested(report, ["read_region_batch", "unique_line_count"])) or 0 for report in batch_reports),
        "scroll_new_unique_line_count": sum(_integer(_nested(report, ["right_detail_scroll_validation", "new_unique_line_count"])) or 0 for report in scroll_reports),
        "recommended_path": _nested(benchmark or {}, ["summary", "recommended_path"]) or _nested(benchmark or {}, ["comparison", "recommended_path"]),
    }


def _screenshots(step_reports: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for report in step_reports:
        for key in ("before_image", "after_image", "observe_image"):
            value = report.get(key)
            if isinstance(value, str) and value and value not in out:
                out.append(value)
    return out


def _trace_paths(step_reports: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for report in step_reports:
        for value in report.get("trace_paths") or []:
            if isinstance(value, str) and value and value not in out:
                out.append(value)
        for key in ("observe_trace", "trace_path"):
            value = report.get(key)
            if isinstance(value, str) and value and value not in out:
                out.append(value)
    return out


def _timing_summary(step_reports: list[dict[str, Any]]) -> dict[str, Any]:
    created = [_parse_time(report.get("created_at")) for report in step_reports]
    created = [value for value in created if value is not None]
    duration_ms = None
    if len(created) >= 2:
        duration_ms = round((max(created) - min(created)).total_seconds() * 1000, 3)
    return {
        "started_at": min(created).isoformat() if created else None,
        "ended_at": max(created).isoformat() if created else None,
        "duration_ms": duration_ms,
    }


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def _truthy(value: Any) -> bool:
    return value is True or str(value).casefold() in {"true", "yes", "1", "pass"}


def _contains_text(value: Any, needle: str) -> bool:
    if isinstance(value, dict):
        return any(_contains_text(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_contains_text(item, needle) for item in value)
    return needle.casefold() in str(value).casefold()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a SEEK job-application demo readiness report.")
    parser.add_argument("--run-dir", type=Path, default=Path("logs/smoke/seek_debug_step_run_latest"))
    parser.add_argument("--application-fill-record", type=Path)
    parser.add_argument("--final-review-audit", type=Path)
    parser.add_argument("--long-read-benchmark", type=Path)
    parser.add_argument("--time-budget-ms", type=int, default=DEFAULT_TIME_BUDGET_MS)
    parser.add_argument("--out", type=Path, default=Path("logs/smoke/seek_demo_readiness_report.json"))
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)

    report = build_demo_readiness_report(
        run_dir=args.run_dir,
        step_reports=load_step_reports(args.run_dir),
        application_fill_record=read_json(args.application_fill_record) if args.application_fill_record else None,
        final_review_audit=read_json(args.final_review_audit) if args.final_review_audit else None,
        long_read_benchmark=read_json(args.long_read_benchmark) if args.long_read_benchmark else None,
        time_budget_ms=args.time_budget_ms,
    )
    write_json(args.out, report)
    print(
        json.dumps(
            {
                "success": report["status"] == "pass",
                "status": report["status"],
                "summary": report["summary"],
                "out": str(args.out),
            },
            ensure_ascii=False,
        )
    )
    if args.fail_on_error and report["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
