from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.seek.audit import audit_seek_mvp_run


def read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def resolve_trace_path(report_path: Path, report: dict[str, Any]) -> Path | None:
    raw = report.get("traversal_trace_path")
    if not raw:
        return None
    trace_path = Path(str(raw))
    if trace_path.is_absolute():
        return trace_path
    if trace_path.exists():
        return trace_path
    candidate = report_path.parent / trace_path
    return candidate


def build_report_audit(
    *,
    report_path: str | Path,
    trace_path: str | Path | None = None,
    stage: str = "no_apply",
    min_jobs: int = 5,
    max_jobs: int | None = 10,
    check_trace_files: bool = False,
) -> dict[str, Any]:
    path = Path(report_path)
    report = read_json(path)
    resolved_trace_path = Path(trace_path) if trace_path else resolve_trace_path(path, report)
    trace = read_json(resolved_trace_path) if resolved_trace_path and resolved_trace_path.exists() else None
    trace_artifacts = collect_trace_artifacts(trace) if check_trace_files and trace else None
    return audit_seek_mvp_run(
        report,
        trace=trace,
        report_path=path,
        trace_path=resolved_trace_path,
        stage=stage,
        min_jobs=min_jobs,
        max_jobs=max_jobs,
        trace_artifacts=trace_artifacts,
    )


def collect_trace_artifacts(trace: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for event in trace.get("traversal_events") or []:
        if not isinstance(event, dict):
            continue
        card_click = event.get("card_click") if isinstance(event.get("card_click"), dict) else {}
        for key in ("trace_path", "recognition_plan_trace_path"):
            raw_path = card_click.get(key)
            if not raw_path:
                continue
            path = Path(str(raw_path))
            if path.exists():
                try:
                    artifacts[str(raw_path)] = read_json(path)
                except (OSError, json.JSONDecodeError, ValueError):
                    artifacts[str(raw_path)] = {"contract_version": "unreadable_trace_artifact_v1", "path": str(raw_path)}
    return artifacts


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a SEEK MVP run report and traversal trace.")
    parser.add_argument("--report", type=Path, required=True, help="seek_mvp_run_report_v1 JSON path.")
    parser.add_argument("--trace", type=Path, default=None, help="Optional explicit seek_mvp_traversal_trace_v1 JSON path.")
    parser.add_argument("--out", type=Path, default=None, help="Optional seek_mvp_run_audit_v1 output path.")
    parser.add_argument("--stage", "--mode", dest="stage", choices=["no_apply", "readonly", "apply_entry", "safe_fill", "full_mvp"], default="no_apply")
    parser.add_argument("--min-jobs", type=int, default=5)
    parser.add_argument("--max-jobs", type=int, default=10)
    parser.add_argument(
        "--check-trace-files",
        action="store_true",
        help="Read referenced action/recognition traces and audit seeded candidate, gate, and verification evidence.",
    )
    parser.add_argument(
        "--fail-if-needs-review",
        "--fail-on-error",
        dest="fail_if_needs_review",
        action="store_true",
        help="Exit 2 when the audit decision is not pass.",
    )
    args = parser.parse_args(argv)
    stage = {"readonly": "no_apply", "safe_fill": "full_mvp"}.get(args.stage, args.stage)

    audit = build_report_audit(
        report_path=args.report,
        trace_path=args.trace,
        stage=stage,
        min_jobs=args.min_jobs,
        max_jobs=args.max_jobs,
        check_trace_files=args.check_trace_files,
    )
    if args.out:
        _write_json(args.out, audit)
    summary = {
        "success": True,
        "decision": audit.get("decision"),
        "stage": audit.get("stage"),
        "report_path": audit.get("report_path"),
        "traversal_trace_path": audit.get("traversal_trace_path"),
        "counts": audit.get("counts"),
        "next_step": audit.get("next_step"),
        "out": str(args.out) if args.out else None,
    }
    print(json.dumps(summary, ensure_ascii=False))
    if args.fail_if_needs_review and audit.get("decision") != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
