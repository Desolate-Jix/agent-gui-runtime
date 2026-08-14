from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.navigation_decision_provider import (
    OpenAICompatibleNavigationDecisionProvider,
)
from app.agent.navigation_reading import validate_navigation_reading_decision
from app.agent.reviewed_workflow_navigation import (
    build_reviewed_workflow_navigation_context,
)


def run_smoke(
    *,
    project_root: Path,
    application_identity_key: str,
    workflow_id: str,
    interface_id: str,
    goal: str,
    endpoint: str,
    model_name: str,
    output_path: Path,
) -> dict[str, Any]:
    observation = {
        "contract_version": "current_interface_observation_v1",
        "interface_id": interface_id,
        "capture_id": "reviewed-workflow-offline-smoke",
        "screenshot_sha256": "0" * 64,
        "trace_path": str(output_path.with_suffix(".trace.json")),
    }
    context = build_reviewed_workflow_navigation_context(
        project_root=project_root,
        application_identity_key=application_identity_key,
        workflow_id=workflow_id,
        interface_id=interface_id,
        goal=goal,
        observation=observation,
    )
    provider = OpenAICompatibleNavigationDecisionProvider(
        endpoint=endpoint,
        model_name=model_name,
        timeout_seconds=120.0,
        temperature=0.0,
        max_tokens=256,
    )
    decision = provider.decide(context)
    plan = validate_navigation_reading_decision(context, decision)
    report = {
        "contract_version": "reviewed_workflow_navigation_smoke_report_v1",
        "source": {
            "application_identity_key": application_identity_key,
            "workflow_id": workflow_id,
            "interface_id": interface_id,
            "interface_count_requirement": "multi_interface_workflow_required",
        },
        "context_summary": {
            "choice_ids": [
                str(item.get("choice_id") or "")
                for item in context.get("choices") or []
                if isinstance(item, dict)
            ],
            "artifact_is_authorization": context.get("artifact_is_authorization"),
        },
        "decision": decision,
        "validated_plan": plan,
        "execution": {
            "attempted": False,
            "reason": "semantic Agent decision smoke only",
        },
        "artifact_is_authorization": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--application-identity-key", required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--interface-id", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:1240")
    parser.add_argument(
        "--model-name",
        default="Qwen3VL-8B-Instruct-Q4_K_M.gguf",
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = run_smoke(
        project_root=Path(args.project_root).resolve(),
        application_identity_key=args.application_identity_key,
        workflow_id=args.workflow_id,
        interface_id=args.interface_id,
        goal=args.goal,
        endpoint=args.endpoint,
        model_name=args.model_name,
        output_path=Path(args.out).resolve(),
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
