from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agent.navigation_reading_live_smoke import (
    run_navigation_reading_live_smoke,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a controlled live navigation, information reading, and scrolling "
            "smoke without form fill or submit."
        )
    )
    parser.add_argument("--suite", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--runtime-endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--decision-endpoint", default="http://127.0.0.1:1240")
    parser.add_argument("--decision-model", default="qwen3-vl-8b-instruct")
    parser.add_argument("--workflow-project-root", default=str(ROOT_DIR))
    parser.add_argument("--max-steps", type=int, default=18)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_navigation_reading_live_smoke(
        suite_path=args.suite,
        out_dir=args.out,
        workflow_project_root=args.workflow_project_root,
        runtime_endpoint=args.runtime_endpoint,
        decision_endpoint=args.decision_endpoint,
        decision_model=args.decision_model,
        max_steps=args.max_steps,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        controller = report["controller"]
        print(
            f"status={controller['final_status']} "
            f"stop_reason={controller.get('stop_reason')} "
            f"visited={controller['visited_interfaces']} "
            f"report={report['report_path']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
