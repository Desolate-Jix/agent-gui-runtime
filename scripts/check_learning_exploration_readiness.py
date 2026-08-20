from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_learning_historical_model_evidence import run_historical_model_evidence_audit
from scripts.check_learning_protected_set_review import (
    _read_json,
    _resolve_project_path,
    compare_learning_protected_archive_node,
    run_learning_protected_set_review,
)
from scripts.check_learning_structure_quality import run_learning_structure_quality_check
from scripts.report_learning_free_exploration_sources import run_free_exploration_source_inventory


DEFAULT_BASELINE = "logs/benchmarks/learning_protected_after_stage1_near_full_partition_gate_verify_20260711.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _metric_passed(report: dict[str, Any]) -> bool:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return int(summary.get("failed") or 0) == 0


def _historical_boundary_passed(report: dict[str, Any]) -> bool:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return (
        int(summary.get("invalid_files") or 0) == 0
        and bool(summary.get("model_accuracy_claim_allowed") is False)
        and int(summary.get("model_grounding_evidence_cases") or 0) == 0
    )


def _structure_boundary_passed(report: dict[str, Any]) -> bool:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return int(summary.get("blocked_structure_repair") or 0) == 0 and int(summary.get("invalid_cases") or 0) == 0


def _stage1_near_full_partition_summary(report: dict[str, Any]) -> dict[str, Any]:
    attempted = 0
    passed = 0
    required_ratio: float | str = "not_available"
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    for case in cases:
        if not isinstance(case, dict):
            continue
        checks = case.get("checks") if isinstance(case.get("checks"), dict) else {}
        metrics = case.get("structure_metrics") if isinstance(case.get("structure_metrics"), dict) else {}
        if "stage1_partition_near_full_coverage" not in checks:
            continue
        attempted += 1
        if checks.get("stage1_partition_near_full_coverage") is True:
            passed += 1
        if required_ratio == "not_available" and metrics.get("stage1_near_full_partition_required_ratio") is not None:
            required_ratio = metrics.get("stage1_near_full_partition_required_ratio")
    return {
        "attempted": attempted,
        "passed": passed,
        "required_ratio": required_ratio,
    }


def run_learning_exploration_readiness_check(
    *,
    baseline_path: str | Path = DEFAULT_BASELINE,
    checkpoint_id: str = "exploration_readiness",
    root: Path = ROOT,
) -> dict[str, Any]:
    protected_report = run_learning_protected_set_review(
        checkpoint_id=checkpoint_id,
        root=root,
    )
    baseline = _read_json(_resolve_project_path(baseline_path, root))
    protected_report["baseline_comparison"] = compare_learning_protected_archive_node(
        protected_report,
        baseline,
    )
    historical_report = run_historical_model_evidence_audit(root=root)
    structure_report = run_learning_structure_quality_check(root=root)
    free_inventory = run_free_exploration_source_inventory(root=root)
    protected_passed = _metric_passed(protected_report)
    baseline_passed = protected_report["baseline_comparison"].get("status") == "pass"
    historical_passed = _historical_boundary_passed(historical_report)
    structure_passed = _structure_boundary_passed(structure_report)
    structure_summary = structure_report.get("summary") if isinstance(structure_report.get("summary"), dict) else {}
    near_full_partition = _stage1_near_full_partition_summary(structure_report)
    intake_gate = free_inventory.get("intake_gate") if isinstance(free_inventory.get("intake_gate"), dict) else {}
    intake_allowed = bool(intake_gate.get("allowed") is True)
    free_replay_blockers = (
        intake_gate.get("blockers")
        if isinstance(intake_gate.get("blockers"), list)
        else []
    )
    runtime_pathgraph_ready = int(structure_summary.get("runtime_pathgraph_ready") or 0)
    runtime_promotion_blocked = runtime_pathgraph_ready == 0
    ready = protected_passed and baseline_passed and historical_passed and structure_passed
    ready_for_free_replay = ready and intake_allowed
    blockers: list[str] = []
    if not protected_passed:
        blockers.append("protected_set_failed")
    if not baseline_passed:
        blockers.append("protected_set_drift")
    if not historical_passed:
        blockers.append("historical_model_evidence_boundary_failed")
    if not structure_passed:
        blockers.append("structure_quality_repair_required")
    return {
        "contract_version": "learning_exploration_readiness_check_v1",
        "generated_at": _now(),
        "ready_for_new_interface_exploration": ready,
        "ready_for_free_exploration_replay": ready_for_free_replay,
        "blockers": blockers,
        "free_exploration_replay_blockers": free_replay_blockers if not ready_for_free_replay else [],
        "summary": {
            "protected_set_passed": protected_passed,
            "baseline_comparison_passed": baseline_passed,
            "historical_model_evidence_boundary_passed": historical_passed,
            "structure_quality_boundary_passed": structure_passed,
            "structure_quality_display_review_candidates": int(
                structure_summary.get("display_review_candidate") or 0
            ),
            "structure_quality_stress_only_cases": int(structure_summary.get("stress_only_needs_review") or 0),
            "structure_quality_blocked_repairs": int(structure_summary.get("blocked_structure_repair") or 0),
            "structure_quality_invalid_cases": int(structure_summary.get("invalid_cases") or 0),
            "structure_quality_runtime_pathgraph_ready": runtime_pathgraph_ready,
            "structure_stage1_near_full_partition_required_ratio": near_full_partition["required_ratio"],
            "structure_stage1_near_full_partition_passed": near_full_partition["passed"],
            "structure_stage1_near_full_partition_attempted": near_full_partition["attempted"],
            "runtime_pathgraph_promotion_blocked": runtime_promotion_blocked,
            "free_exploration_intake_allowed": intake_allowed,
            "free_exploration_candidate_count": int(free_inventory.get("candidate_count") or 0),
            "free_exploration_intake_status": str(intake_gate.get("status") or "unknown"),
            "interpretation": (
                "Pre-exploration gate for Learning Mode recognition changes. Passing means protected display "
                "baselines still load, historical Python evidence is not being treated as model accuracy, and "
                "structure-quality failures are not being promoted into Runtime PathGraph capability. "
                "Free-exploration replay readiness is reported separately because it requires a non-protected "
                "real observe trace with inventory."
            ),
        },
        "protected_set": protected_report,
        "historical_model_evidence": historical_report,
        "structure_quality": structure_report,
        "free_exploration_source_inventory": free_inventory,
        "safety_boundary": {
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "runtime_pathgraph_promotion": runtime_pathgraph_ready > 0,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the protected-set and historical-evidence gates before exploring a new interface."
    )
    parser.add_argument("--baseline", default=DEFAULT_BASELINE, help="Protected-set archive/report baseline.")
    parser.add_argument("--checkpoint-id", default="exploration_readiness", help="Archive id for this run.")
    parser.add_argument("--out", default="", help="Optional JSON report path.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout.")
    args = parser.parse_args()

    report = run_learning_exploration_readiness_check(
        baseline_path=args.baseline,
        checkpoint_id=args.checkpoint_id,
    )
    if args.out:
        out_path = _resolve_project_path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json or not args.out:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready_for_new_interface_exploration"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
