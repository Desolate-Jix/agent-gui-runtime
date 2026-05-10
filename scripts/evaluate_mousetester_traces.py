from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation.mousetester_trace_eval import evaluate_cases, load_cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate MouseTester recognition/action evidence traces.")
    parser.add_argument(
        "--cases",
        default="configs/mousetester_eval_cases.json",
        help="Path to a MouseTester eval case manifest.",
    )
    parser.add_argument(
        "--output-dir",
        default="logs/evaluations",
        help="Directory for the JSON evaluation report.",
    )
    args = parser.parse_args()

    root = ROOT
    cases = load_cases(root / args.cases)
    report = evaluate_cases(cases, root=root)
    report["generated_at"] = datetime.now().isoformat(timespec="seconds")

    output_dir = root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"mousetester-trace-eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"report_path={output_path}")
    return 0 if report["summary"]["missing_case_count"] == 0 and report["summary"]["passed_case_count"] == report["summary"]["present_case_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
