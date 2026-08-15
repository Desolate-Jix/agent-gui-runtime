from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.reviewed_workflow_navigation import (
    run_reviewed_workflow_navigation_live_smoke,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a reviewed multi-interface workflow through the controlled live "
            "navigation and reading chain without form fill or submit."
        )
    )
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--application-identity-key", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--runtime-endpoint", default="http://127.0.0.1:8000")
    parser.add_argument("--decision-endpoint", default="http://127.0.0.1:13240")
    parser.add_argument("--decision-model", default="qwen3-vl-8b-instruct")
    parser.add_argument("--max-steps", type=int, default=18)
    parser.add_argument("--request-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--decision-timeout-seconds", type=float, default=45.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_reviewed_workflow_navigation_live_smoke(
        project_root=Path(args.project_root).resolve(),
        application_identity_key=args.application_identity_key,
        workflow_id=args.workflow_id,
        out_dir=Path(args.out).resolve(),
        runtime_endpoint=args.runtime_endpoint,
        decision_endpoint=args.decision_endpoint,
        decision_model=args.decision_model,
        max_steps=args.max_steps,
        request_timeout_seconds=args.request_timeout_seconds,
        decision_timeout_seconds=args.decision_timeout_seconds,
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
