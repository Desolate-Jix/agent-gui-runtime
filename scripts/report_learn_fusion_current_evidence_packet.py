from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.draft_review import load_learning_draft_review


REPORT_NAME = "learn_fusion_current_evidence_packet.json"


def report_learn_fusion_current_evidence_packet(
    *,
    source_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    source_file = _resolve_path(source_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)

    review = load_learning_draft_review(_relative_path(source_file, root), project_root=root)
    preview = _dict(review.get("screen_understanding_preview"))
    candidate_review = _dict(review.get("pathgraph_candidate_review"))
    readiness_summary = _dict(candidate_review.get("pathgraph_readiness_summary"))
    integration = _dict(candidate_review.get("pathgraph_integration_readiness"))
    calibration_pre_run = _dict(candidate_review.get("calibration_pre_run_check"))
    draft = _dict(review.get("draft"))

    packet = {
        "contract_version": "learn_fusion_current_evidence_packet_v1",
        "source_path": _relative_path(source_file, root),
        "screen_summary": str(draft.get("screen_summary") or ""),
        "state_guess": str(draft.get("state_guess") or ""),
        "full_screen_understanding": {
            "overlay_path": preview.get("full_screen_understanding_overlay_path"),
            "compiled_overlay_path": preview.get("compiled_overlay_path"),
            "fusion_summary": _dict(preview.get("fusion_summary")),
            "display_readiness": _dict(preview.get("fusion_display_readiness")),
            "not_accuracy": preview.get("fusion_not_accuracy") is not False,
        },
        "calibration": {
            "readiness_summary": _dict(preview.get("precise_understanding_readiness_summary")),
            "backlog_summary": _dict(preview.get("calibration_backlog_summary")),
            "backlog_item_count": len(_list(preview.get("calibration_backlog_items"))),
            "batch_ready_region_numbers": _list(preview.get("calibration_batch_ready_region_numbers")),
            "batch_review_blocked_region_numbers": _list(preview.get("calibration_batch_review_blocked_region_numbers")),
            "batch_command_executes_now": preview.get("calibration_batch_command_executes_now") is True,
            "post_batch_refresh_command_executes_now": preview.get("post_batch_refresh_command_executes_now") is True,
            "pre_run_status": calibration_pre_run.get("effective_pre_run_status")
            or calibration_pre_run.get("pre_run_status"),
        },
        "pathgraph": {
            "candidate_path": candidate_review.get("pathgraph_candidate_path"),
            "validation_status": readiness_summary.get("validation_status"),
            "readiness_status": readiness_summary.get("readiness_status"),
            "ready_for_runtime_pathgraph_promotion": readiness_summary.get("ready_for_runtime_pathgraph_promotion") is True,
            "integration_readiness_status": integration.get("integration_readiness_status"),
            "integration_report_path": _display_path(integration.get("report_path"), root=root),
            "ready_for_audited_pathgraph_review": integration.get("ready_for_audited_pathgraph_review") is True,
            "ready_for_runtime_pathgraph_promotion_after_integration": (
                integration.get("ready_for_runtime_pathgraph_promotion") is True
            ),
            "blockers": _list(integration.get("blockers")),
        },
        "evidence_integrity": _dict(preview.get("evidence_integrity")),
        "next_required_steps": _next_required_steps(preview=preview, integration=integration),
        "safety": {
            "display_only": True,
            "model_started": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
        },
        "interpretation": (
            "Offline evidence packet for the current fused Learn Mode understanding. "
            "It summarizes existing screen-understanding, calibration, PathGraph, and integration-readiness evidence; "
            "it does not start models, click, fill, submit, authorize Execute, or promote Runtime PathGraph."
        ),
    }
    report_path = out / REPORT_NAME
    packet["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(packet, ensure_ascii=False, indent=2))
    return packet


def _next_required_steps(*, preview: dict[str, Any], integration: dict[str, Any]) -> list[str]:
    steps = []
    integration_steps = _list(integration.get("next_required_steps"))
    if integration_steps:
        steps.extend(str(item) for item in integration_steps if str(item).strip())
    readiness = _dict(preview.get("precise_understanding_readiness_summary"))
    if readiness.get("readiness_status") == "needs_pending_calibration":
        steps.append("run_pending_numbered_region_calibration_batch_before_pathgraph_review")
    if not steps:
        steps.append("human_audit_before_runtime_pathgraph_promotion")
    return list(dict.fromkeys(steps))


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def _display_path(value: Any, *, root: Path) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return _relative_path(_resolve_path(value, root), root)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an offline learn-fusion current evidence packet.")
    parser.add_argument("--source", required=True, help="Learning draft review source or pathgraph_candidate.json.")
    parser.add_argument("--out", required=True, help="Output directory for the evidence packet.")
    parser.add_argument("--json", action="store_true", help="Print the packet JSON to stdout.")
    args = parser.parse_args()
    report_learn_fusion_current_evidence_packet(source_path=args.source, out_dir=args.out, json_stdout=args.json)


if __name__ == "__main__":
    main()
