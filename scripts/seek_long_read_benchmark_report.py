from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONTRACT_VERSION = "seek_long_read_benchmark_report_v1"


def read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_step_reports(paths: list[Path]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for path in paths:
        if path.is_dir():
            candidates = sorted(path.rglob("step_report.json"))
        else:
            candidates = [path]
        for candidate in candidates:
            report = read_json(candidate)
            report["_source_path"] = str(candidate)
            reports.append(report)
    return reports


def build_benchmark_report(reports: list[dict[str, Any]], *, inputs: list[str] | None = None) -> dict[str, Any]:
    old_scroll_reports = [report for report in reports if _is_old_scroll_report(report)]
    batch_reports = [report for report in reports if _is_batch_read_report(report)]
    old_summary = _summarize_old_scroll(old_scroll_reports)
    batch_summary = _summarize_batch_read(batch_reports)
    comparison = _compare(old_summary, batch_summary)
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": inputs or [],
        "summary": {
            "old_scroll_report_count": old_summary["report_count"],
            "batch_report_count": batch_summary["report_count"],
            "old_unique_line_count": old_summary["unique_line_count"],
            "batch_unique_line_count": batch_summary["unique_line_count"],
            "old_wrong_scope_count": old_summary["wrong_scope_count"],
            "batch_wrong_scope_count": batch_summary["wrong_scope_count"],
            "old_total_elapsed_ms": old_summary["total_elapsed_ms"],
            "batch_total_elapsed_ms": batch_summary["total_elapsed_ms"],
            "recommended_path": comparison["recommended_path"],
        },
        "old_repeated_scroll": old_summary,
        "batch_read": batch_summary,
        "comparison": comparison,
    }


def _is_old_scroll_report(report: dict[str, Any]) -> bool:
    return report.get("step_name") == "read_detail_scroll" or isinstance(report.get("right_detail_scroll_validation"), dict)


def _is_batch_read_report(report: dict[str, Any]) -> bool:
    return report.get("step_name") == "read_detail_batch" or isinstance(report.get("read_region_batch"), dict)


def _summarize_old_scroll(reports: list[dict[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    total_new_lines = 0
    wrong_scope_count = 0
    no_progress_count = 0
    elapsed_values: list[float] = []
    for report in reports:
        validation = report.get("right_detail_scroll_validation") if isinstance(report.get("right_detail_scroll_validation"), dict) else {}
        new_lines = int(validation.get("new_unique_line_count") or 0)
        wrong_scope = bool(validation.get("wrong_scope"))
        no_progress = int(validation.get("no_progress_count") or 0)
        total_new_lines += new_lines
        wrong_scope_count += 1 if wrong_scope else 0
        no_progress_count += no_progress
        elapsed_values.extend(_elapsed_ms_values(report))
        entries.append(
            {
                "source_path": report.get("_source_path"),
                "step_index": report.get("step_index"),
                "new_unique_line_count": new_lines,
                "wrong_scope": wrong_scope,
                "no_progress_count": no_progress,
                "next_wheel_clicks": validation.get("next_wheel_clicks"),
                "adaptive_stop_reason": validation.get("adaptive_stop_reason"),
                "scroll_trace_path": _nested(report, ["scroll_response", "trace_path"]),
            }
        )
    total_elapsed = _sum_or_none(elapsed_values)
    return {
        "strategy": "old_repeated_read_detail_scroll",
        "report_count": len(reports),
        "unique_line_count": total_new_lines,
        "wrong_scope_count": wrong_scope_count,
        "no_progress_count": no_progress_count,
        "total_elapsed_ms": total_elapsed,
        "ms_per_unique_line": _ratio(total_elapsed, total_new_lines),
        "entries": entries,
    }


def _summarize_batch_read(reports: list[dict[str, Any]]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    unique_lines = 0
    capture_count = 0
    wrong_scope_count = 0
    elapsed_values: list[float] = []
    stop_reasons: dict[str, int] = {}
    for report in reports:
        batch = report.get("read_region_batch") if isinstance(report.get("read_region_batch"), dict) else report
        if batch.get("contract_version") != "read_region_batch_v1":
            continue
        report_unique_lines = int(batch.get("unique_line_count") or 0)
        report_capture_count = int(batch.get("capture_count") or len(batch.get("captures") or []))
        wrong_scope = bool(batch.get("wrong_scope_detected"))
        stop_reason = str(batch.get("stop_reason") or "unknown")
        unique_lines += report_unique_lines
        capture_count += report_capture_count
        wrong_scope_count += 1 if wrong_scope else 0
        stop_reasons[stop_reason] = stop_reasons.get(stop_reason, 0) + 1
        elapsed_values.extend(_elapsed_ms_values(report))
        entries.append(
            {
                "source_path": report.get("_source_path"),
                "step_index": report.get("step_index"),
                "capture_count": report_capture_count,
                "unique_line_count": report_unique_lines,
                "wrong_scope_detected": wrong_scope,
                "stop_reason": stop_reason,
                "capture_summaries": batch.get("captures") or [],
            }
        )
    total_elapsed = _sum_or_none(elapsed_values)
    return {
        "strategy": "new_read_detail_batch",
        "report_count": len(entries),
        "capture_count": capture_count,
        "unique_line_count": unique_lines,
        "wrong_scope_count": wrong_scope_count,
        "stop_reasons": stop_reasons,
        "total_elapsed_ms": total_elapsed,
        "ms_per_unique_line": _ratio(total_elapsed, unique_lines),
        "entries": entries,
    }


def _compare(old_summary: dict[str, Any], batch_summary: dict[str, Any]) -> dict[str, Any]:
    old_lines = int(old_summary.get("unique_line_count") or 0)
    batch_lines = int(batch_summary.get("unique_line_count") or 0)
    old_elapsed = old_summary.get("total_elapsed_ms")
    batch_elapsed = batch_summary.get("total_elapsed_ms")
    old_wrong = int(old_summary.get("wrong_scope_count") or 0)
    batch_wrong = int(batch_summary.get("wrong_scope_count") or 0)

    blockers: list[str] = []
    if not batch_summary.get("report_count"):
        blockers.append("missing_batch_read_report")
    if batch_wrong > old_wrong:
        blockers.append("batch_wrong_scope_regressed")
    if old_lines and batch_lines < max(1, int(old_lines * 0.8)):
        blockers.append("batch_unique_line_recall_too_low")

    faster = None
    if old_elapsed is not None and batch_elapsed is not None:
        faster = batch_elapsed < old_elapsed
        if not faster:
            blockers.append("batch_elapsed_not_faster")

    recommended_path = "read_detail_batch" if not blockers else "needs_more_evidence"
    return {
        "recommended_path": recommended_path,
        "blockers": blockers,
        "batch_faster_when_timed": faster,
        "unique_line_delta": batch_lines - old_lines,
        "wrong_scope_delta": batch_wrong - old_wrong,
        "elapsed_delta_ms": (batch_elapsed - old_elapsed) if old_elapsed is not None and batch_elapsed is not None else None,
        "decision_rule": "prefer batch when it has evidence, does not reduce unique-line recall below 80%, does not increase wrong-scope count, and is faster when timings exist",
    }


def _elapsed_ms_values(value: Any) -> list[float]:
    values: list[float] = []
    if isinstance(value, dict):
        timings = value.get("timings")
        if isinstance(timings, dict) and _number(timings.get("total_ms")) is not None:
            values.append(float(timings["total_ms"]))
        for key in ("scroll_response", "ui_diff_verification", "read_region_batch"):
            nested = value.get(key)
            if isinstance(nested, dict):
                values.extend(_elapsed_ms_values(nested))
        result = value.get("result")
        if isinstance(result, dict):
            values.extend(_elapsed_ms_values(result))
    return values


def _nested(value: dict[str, Any], path: list[str]) -> Any:
    current: Any = value
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum_or_none(values: list[float]) -> float | None:
    return round(sum(values), 3) if values else None


def _ratio(numerator: float | None, denominator: int) -> float | None:
    if numerator is None or denominator <= 0:
        return None
    return round(numerator / denominator, 3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare old repeated SEEK detail scrolling with read_detail_batch evidence.")
    parser.add_argument("paths", nargs="+", type=Path, help="Step report JSON files or run directories containing step_report.json files.")
    parser.add_argument("--out", type=Path, default=Path("logs/smoke/seek_long_read_benchmark_report.json"))
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args(argv)

    reports = load_step_reports(args.paths)
    result = build_benchmark_report(reports, inputs=[str(path) for path in args.paths])
    write_json(args.out, result)
    print(
        json.dumps(
            {
                "success": not result["comparison"]["blockers"],
                "recommended_path": result["comparison"]["recommended_path"],
                "summary": result["summary"],
                "out": str(args.out),
            },
            ensure_ascii=False,
        )
    )
    if args.fail_on_regression and result["comparison"]["blockers"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
