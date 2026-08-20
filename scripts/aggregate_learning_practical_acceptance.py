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

from scripts.run_learning_interface_chain_smoke import build_manifest_suite_cases


def aggregate_acceptance_reports(
    batch_reports: list[dict[str, Any]],
    *,
    expected_case_ids: list[str],
) -> dict[str, Any]:
    """汇总可续跑批次，严格区分证据收集完成和质量结果。"""
    expected = [str(case_id).strip() for case_id in expected_case_ids if str(case_id).strip()]
    if not expected:
        raise ValueError("acceptance aggregate requires expected case ids")
    if len(expected) != len(set(expected)):
        duplicates = sorted(case_id for case_id in set(expected) if expected.count(case_id) > 1)
        raise ValueError(f"duplicate expected case ids: {', '.join(duplicates)}")

    expected_set = set(expected)
    completed: dict[str, dict[str, Any]] = {}
    duplicate_completed: set[str] = set()
    resource_blocked_report_count = 0
    safety_totals = {"live_clicks": 0, "live_fills": 0, "live_submits": 0}
    unsafe_flags: list[str] = []

    for report_index, report in enumerate(batch_reports):
        if report.get("contract_version") != "learning_interface_chain_smoke_report_v2":
            raise ValueError(f"batch report {report_index} has unsupported contract_version")
        status = str(report.get("status") or "").strip()
        if status not in {"completed_batch", "resource_blocked"}:
            raise ValueError(f"batch report {report_index} has unsupported status: {status or '<missing>'}")
        cases = [item for item in report.get("cases") or [] if isinstance(item, dict)]
        declared_completed = [str(case_id) for case_id in report.get("completed_case_ids") or []]
        actual_completed = [str(item.get("case_id") or "").strip() for item in cases]
        if declared_completed != actual_completed:
            raise ValueError(f"batch report {report_index} completed_case_ids do not match cases")
        if status == "resource_blocked":
            resource_blocked_report_count += 1
            if cases or int(report.get("model_calls_attempted") or 0) != 0:
                raise ValueError(f"resource-blocked report {report_index} contains attempted cases")

        for case in cases:
            case_id = str(case.get("case_id") or "").strip()
            if case_id not in expected_set:
                raise ValueError(f"unexpected completed case id: {case_id or '<missing>'}")
            if case_id in completed:
                duplicate_completed.add(case_id)
            else:
                completed[case_id] = case

        safety = report.get("safety") if isinstance(report.get("safety"), dict) else {}
        for key in safety_totals:
            safety_totals[key] += int(safety.get(key) or 0)
        if safety.get("execute_binding_enabled") is True:
            unsafe_flags.append(f"report_{report_index}:execute_binding_enabled")
        if safety.get("runtime_pathgraph_promotion") is True:
            unsafe_flags.append(f"report_{report_index}:runtime_pathgraph_promotion")

    if duplicate_completed:
        raise ValueError(f"duplicate completed case ids: {', '.join(sorted(duplicate_completed))}")

    completed_ids = [case_id for case_id in expected if case_id in completed]
    pending_ids = [case_id for case_id in expected if case_id not in completed]
    completed_cases = [completed[case_id] for case_id in completed_ids]
    metrics = {
        "three_image_audit": _metric(
            sum(1 for case in completed_cases if _dict(case.get("three_image_audit")).get("complete") is True),
            len(completed_cases),
            "three-image evidence completeness only; not recognition accuracy",
        ),
        "chain_completion": _metric(
            sum(1 for case in completed_cases if case.get("chain_success") is True),
            len(completed_cases),
            "display/review chain completion only; not Execute or unattended reliability",
        ),
        "class_expectation": _class_expectation_metric(completed_cases),
    }
    failure_cases = [_failure_case(case) for case in completed_cases if _case_needs_review(case)]
    safety_ok = not unsafe_flags and all(value == 0 for value in safety_totals.values())
    collection_status = "collection_complete" if not pending_ids else "pending_cases"
    if not completed_cases:
        quality_status = "not_covered"
    elif failure_cases or not safety_ok:
        quality_status = "needs_review"
    else:
        quality_status = "review_evidence_complete"

    return {
        "contract_version": "learning_practical_acceptance_aggregate_v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "expected_case_count": len(expected),
        "completed_case_count": len(completed_ids),
        "pending_case_count": len(pending_ids),
        "completed_case_ids": completed_ids,
        "pending_case_ids": pending_ids,
        "collection_status": collection_status,
        "quality_status": quality_status,
        "resource_blocked_report_count": resource_blocked_report_count,
        "metrics": metrics,
        "failure_cases": failure_cases,
        "safety": {
            **safety_totals,
            "execute_binding_enabled": any("execute_binding_enabled" in item for item in unsafe_flags),
            "runtime_pathgraph_promotion": any("runtime_pathgraph_promotion" in item for item in unsafe_flags),
            "unsafe_flags": unsafe_flags,
            "passed": safety_ok,
        },
        "cases": completed_cases,
        "interpretation": (
            "Resumable Learning Mode acceptance evidence aggregation. Collection completion, quality checks, and "
            "safety are separate; this report does not provide a total accuracy or unattended-use claim."
        ),
    }


def collect_batch_report_paths(
    *,
    batch_report_paths: list[Path],
    resume_aggregate_paths: list[Path],
) -> list[Path]:
    """从上一版聚合报告继承批次来源，并追加本轮批次。"""
    collected: list[Path] = []
    seen: set[str] = set()
    for aggregate_path in resume_aggregate_paths:
        resolved_aggregate = _resolve_path(aggregate_path)
        aggregate = _read_json(resolved_aggregate)
        if aggregate.get("contract_version") != "learning_practical_acceptance_aggregate_v1":
            raise ValueError(f"unsupported practical acceptance aggregate: {resolved_aggregate}")
        for raw_path in aggregate.get("batch_report_paths") or []:
            resolved = _resolve_path(Path(str(raw_path)))
            key = str(resolved).casefold()
            if key not in seen:
                seen.add(key)
                collected.append(resolved)
    for batch_report_path in batch_report_paths:
        resolved = _resolve_path(batch_report_path)
        key = str(resolved).casefold()
        if key not in seen:
            seen.add(key)
            collected.append(resolved)
    if not collected:
        raise ValueError("acceptance aggregate requires at least one batch report")
    return collected


def build_acceptance_aggregate(
    *,
    manifest_paths: list[Path],
    batch_report_paths: list[Path],
    out_dir: Path,
    resume_aggregate_paths: list[Path] | None = None,
) -> dict[str, Any]:
    manifests = [_resolve_path(path) for path in manifest_paths]
    resume_aggregates = [_resolve_path(path) for path in resume_aggregate_paths or []]
    reports = collect_batch_report_paths(
        batch_report_paths=batch_report_paths,
        resume_aggregate_paths=resume_aggregates,
    )
    expected_cases = build_manifest_suite_cases(manifests)
    expected_manifest_set = {str(path) for path in manifests}
    payloads: list[dict[str, Any]] = []
    for report_path in reports:
        report = _read_json(report_path)
        recorded_manifests = {str(_resolve_path(Path(value))) for value in report.get("manifest_paths") or []}
        if recorded_manifests and recorded_manifests != expected_manifest_set:
            raise ValueError(f"batch report manifest set mismatch: {report_path}")
        payloads.append(report)
    aggregate = aggregate_acceptance_reports(
        payloads,
        expected_case_ids=[case.case_id for case in expected_cases],
    )
    out_dir = _resolve_path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "learning_practical_acceptance_aggregate_report.json"
    aggregate.update(
        {
            "manifest_paths": [str(path) for path in manifests],
            "batch_report_paths": [str(path) for path in reports],
            "resume_aggregate_paths": [str(path) for path in resume_aggregates],
            "report_path": str(report_path),
        }
    )
    report_path.write_text(json.dumps(aggregate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return aggregate


def _metric(passed: int, attempted: int, interpretation: str) -> dict[str, Any]:
    return {
        "passed": passed,
        "attempted": attempted,
        "rate": round(passed / attempted, 4) if attempted else "not_covered",
        "interpretation": interpretation,
    }


def _class_expectation_metric(cases: list[dict[str, Any]]) -> dict[str, Any]:
    covered = [
        _dict(case.get("class_expectation_audit"))
        for case in cases
        if str(_dict(case.get("class_expectation_audit")).get("status") or "") != "not_covered"
    ]
    return _metric(
        sum(1 for audit in covered if audit.get("status") == "passed"),
        len(covered),
        "manifest expectation checks only; not general interface-classification reliability",
    )


def _case_needs_review(case: dict[str, Any]) -> bool:
    return (
        _dict(case.get("three_image_audit")).get("complete") is not True
        or case.get("chain_success") is not True
        or str(_dict(case.get("class_expectation_audit")).get("status") or "not_covered") == "needs_review"
    )


def _failure_case(case: dict[str, Any]) -> dict[str, Any]:
    chain = _dict(case.get("chain_completion"))
    three_image = _dict(case.get("three_image_audit"))
    class_audit = _dict(case.get("class_expectation_audit"))
    failed_requirements = list(chain.get("failed_requirements") or [])
    if three_image.get("complete") is not True and "three_image_audit" not in failed_requirements:
        failed_requirements.append("three_image_audit")
    stage1_evidence = _dict(three_image.get("stage1_bar_localization") or three_image.get("stage1"))
    final_evidence = _dict(three_image.get("final_fused_overlay") or three_image.get("final"))
    if three_image.get("complete") is not True:
        failure_category = "three_image_evidence_incomplete"
    elif str(class_audit.get("status") or "not_covered") == "needs_review":
        failure_category = "class_expectation_needs_review"
    elif case.get("chain_success") is not True:
        failure_category = "chain_completion_needs_review"
    else:
        failure_category = "quality_review_required"
    return {
        "case_id": case.get("case_id"),
        "failure_category": failure_category,
        "failed_requirements": failed_requirements,
        "class_expectation_issues": list(class_audit.get("issues") or []),
        "quality_status": _dict(case.get("quality")).get("status"),
        "case_report_path": case.get("case_report_path"),
        "source_image_path": _dict(three_image.get("source")).get("path"),
        "stage1_image_path": stage1_evidence.get("path"),
        "final_image_path": final_evidence.get("path"),
        "trace_path": case.get("source_trace_path"),
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON report must be an object: {path}")
    return payload


def _resolve_path(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate resumable Learning Mode practical-acceptance batches.")
    parser.add_argument("--manifest", action="append", default=[], help="Expected manifest; repeat for the full suite.")
    parser.add_argument("--batch-report", action="append", default=[], help="New completed or resource-blocked batch report.")
    parser.add_argument(
        "--resume-aggregate",
        action="append",
        default=[],
        help="Prior aggregate whose batch-report sources should be inherited; repeat as needed.",
    )
    parser.add_argument("--out", required=True, help="Output directory.")
    parser.add_argument("--json", action="store_true", help="Print JSON report.")
    args = parser.parse_args()
    manifests = list(args.manifest or []) or [
        "artifacts/benchmarks/interface_class_recursive_manifest_v1.json",
        "tests/fixtures/learning_surface_adapter_holdout_manifest_v1.json",
    ]
    report = build_acceptance_aggregate(
        manifest_paths=[Path(value) for value in manifests],
        batch_report_paths=[Path(value) for value in args.batch_report or []],
        out_dir=Path(args.out),
        resume_aggregate_paths=[Path(value) for value in args.resume_aggregate or []],
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"collection_status={report['collection_status']}")
        print(f"quality_status={report['quality_status']}")
        print(f"report_path={report['report_path']}")
    if report["collection_status"] != "collection_complete":
        return 2
    return 0 if report["quality_status"] == "review_evidence_complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
