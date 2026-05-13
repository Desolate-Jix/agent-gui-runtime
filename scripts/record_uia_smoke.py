from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.runtime_artifacts import write_trace
from app.core.window_manager import window_manager
from app.evaluation.uia_smoke_eval import UIASmokeEvalCase, evaluate_cases
from app.screen_reading.uia_provider import uia_provider


DEFAULT_EXPECTED_NAMES = ["返回", "刷新", "点击此处测试"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind a window, collect a Windows UIA snapshot, and score the smoke evidence.")
    parser.add_argument("--process-name", default="msedge.exe", help="Target process name.")
    parser.add_argument("--title", default="MouseTester", help="Substring to match in the target window title.")
    parser.add_argument("--max-controls", type=int, default=250, help="Maximum UIA controls to collect.")
    parser.add_argument("--min-controls", type=int, default=50, help="Minimum controls expected for a passing smoke.")
    parser.add_argument("--min-buttons", type=int, default=5, help="Minimum button controls expected for a passing smoke.")
    parser.add_argument(
        "--expected-name",
        action="append",
        default=None,
        help="Expected substring in at least one UIA control name. Can be repeated.",
    )
    parser.add_argument("--output-dir", default="logs/evaluations", help="Directory for the JSON evaluation report.")
    args = parser.parse_args()

    expected_names = args.expected_name if args.expected_name is not None else DEFAULT_EXPECTED_NAMES
    bound_payload: dict[str, Any] | None = None
    snapshot: dict[str, Any]
    error: str | None = None

    try:
        bound = window_manager.bind_window(process_name=args.process_name, title=args.title)
        bound_payload = {
            "handle": bound.handle,
            "title": bound.title,
            "process_id": bound.process_id,
            "process_name": bound.process_name,
            "rect": {
                "left": bound.rect.left,
                "top": bound.rect.top,
                "right": bound.rect.right,
                "bottom": bound.rect.bottom,
            },
            "is_active": bound.is_active,
        }
        snapshot = uia_provider.snapshot_bound_window(max_controls=args.max_controls)
    except Exception as exc:
        error = str(exc)
        snapshot = {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "unavailable",
            "reason": "uia_smoke_failed",
            "message": error,
            "control_count": 0,
            "controls": [],
        }

    trace_payload = {
        "success": snapshot.get("status") == "ok",
        "contract_version": "uia_smoke_trace_v1",
        "request": {
            "process_name": args.process_name,
            "title": args.title,
            "max_controls": args.max_controls,
            "min_controls": args.min_controls,
            "min_buttons": args.min_buttons,
            "expected_name_contains": expected_names,
        },
        "result": {
            "bound_window": bound_payload,
            "snapshot": snapshot,
            "error": error,
        },
    }
    trace_path = write_trace(
        category="evaluation",
        operation="uia-smoke",
        payload=trace_payload,
        name_hint=args.title or args.process_name,
    )

    report = evaluate_cases(
        [
            UIASmokeEvalCase(
                case_id="live_uia_smoke",
                trace_path=trace_path,
                expected_status="ok",
                min_control_count=args.min_controls,
                min_button_count=args.min_buttons,
                expected_name_contains=expected_names,
            )
        ],
        root=ROOT,
    )
    report["generated_at"] = datetime.now().isoformat(timespec="seconds")
    report["trace_path"] = trace_path

    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"uia-smoke-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"trace_path={trace_path}")
    print(f"report_path={output_path}")
    summary = report["summary"]
    return 0 if summary["missing_case_count"] == 0 and summary["passed_case_count"] == summary["present_case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
