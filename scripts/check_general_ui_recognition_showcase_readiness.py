from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def evaluate_readiness(benchmark: dict[str, Any], panel_smoke: dict[str, Any]) -> dict[str, Any]:
    summary = benchmark.get("summary") if isinstance(benchmark.get("summary"), dict) else {}
    ownership = (
        benchmark.get("ownership_golden_holdout")
        if isinstance(benchmark.get("ownership_golden_holdout"), dict)
        else {}
    )
    review = (
        benchmark.get("review_evidence_summary")
        if isinstance(benchmark.get("review_evidence_summary"), dict)
        else {}
    )
    safety = benchmark.get("safety") if isinstance(benchmark.get("safety"), dict) else {}
    side_effects = (
        safety.get("declared_side_effect_counts")
        if isinstance(safety.get("declared_side_effect_counts"), dict)
        else {}
    )
    blocking_gates: list[dict[str, Any]] = []
    needs_review_gates: list[dict[str, Any]] = []

    def gate(
        gate_id: str,
        passed: bool,
        *,
        expected: Any,
        actual: Any,
        severity: str,
    ) -> None:
        if passed:
            return
        item = {
            "gate_id": gate_id,
            "severity": severity,
            "expected": expected,
            "actual": actual,
        }
        (blocking_gates if severity == "blocking" else needs_review_gates).append(item)

    gate(
        "benchmark_contract",
        benchmark.get("contract_version") == "general_ui_recognition_benchmark_report_v1",
        expected="general_ui_recognition_benchmark_report_v1",
        actual=benchmark.get("contract_version"),
        severity="blocking",
    )
    fixture_failures = benchmark.get("fixture_validity_failures") or []
    gate(
        "fixture_validity",
        not fixture_failures and int(summary.get("invalid_fixture_count") or 0) == 0,
        expected=0,
        actual=len(fixture_failures) + int(summary.get("invalid_fixture_count") or 0),
        severity="blocking",
    )
    gate(
        "ownership_fixture_valid",
        ownership.get("fixture_status") == "valid",
        expected="valid",
        actual=ownership.get("fixture_status"),
        severity="blocking",
    )
    gate(
        "review_evidence_valid",
        int(review.get("invalid") or 0) == 0,
        expected=0,
        actual=review.get("invalid"),
        severity="blocking",
    )
    static_audit = safety.get("static_source_audit") if isinstance(safety.get("static_source_audit"), dict) else {}
    gate(
        "offline_runner_static_safety",
        static_audit.get("passed") is True,
        expected=True,
        actual=static_audit.get("passed"),
        severity="blocking",
    )
    gate(
        "no_execute_binding",
        safety.get("execute_binding_enabled") is False,
        expected=False,
        actual=safety.get("execute_binding_enabled"),
        severity="blocking",
    )
    gate(
        "no_runtime_pathgraph_promotion",
        safety.get("runtime_pathgraph_promotion") is False,
        expected=False,
        actual=safety.get("runtime_pathgraph_promotion"),
        severity="blocking",
    )
    for key in ("live_clicks", "live_fills", "live_submits"):
        gate(
            f"no_{key}",
            int(side_effects.get(key) or 0) == 0,
            expected=0,
            actual=side_effects.get(key),
            severity="blocking",
        )

    gate(
        "panel_contract",
        panel_smoke.get("contract_version") == "general_ui_recognition_panel_smoke_v1",
        expected="general_ui_recognition_panel_smoke_v1",
        actual=panel_smoke.get("contract_version"),
        severity="blocking",
    )
    gate(
        "actual_panel_source",
        panel_smoke.get("source") == "actual_local_panel",
        expected="actual_local_panel",
        actual=panel_smoke.get("source"),
        severity="blocking",
    )
    for viewport_name in ("desktop", "mobile"):
        viewport = panel_smoke.get(viewport_name) if isinstance(panel_smoke.get(viewport_name), dict) else {}
        gate(
            f"panel_{viewport_name}_screenshot",
            bool(str(viewport.get("screenshot_path") or "").strip()),
            expected="non-empty screenshot path",
            actual=viewport.get("screenshot_path"),
            severity="blocking",
        )
        for field in ("compiled_overlay_rendered", "hierarchy_rendered", "page_details_rendered"):
            gate(
                f"panel_{viewport_name}_{field}",
                viewport.get(field) is True,
                expected=True,
                actual=viewport.get(field),
                severity="blocking",
            )
        gate(
            f"panel_{viewport_name}_horizontal_overflow",
            viewport.get("horizontal_overflow") is False,
            expected=False,
            actual=viewport.get("horizontal_overflow"),
            severity="blocking",
        )
    gate(
        "panel_no_execute_binding",
        panel_smoke.get("execute_binding_enabled") is False,
        expected=False,
        actual=panel_smoke.get("execute_binding_enabled"),
        severity="blocking",
    )
    gate(
        "panel_artifact_not_authorization",
        panel_smoke.get("artifact_is_authorization") is False,
        expected=False,
        actual=panel_smoke.get("artifact_is_authorization"),
        severity="blocking",
    )

    valid_case_count = int(summary.get("valid_case_count") or 0)
    family_count = int(summary.get("supported_application_family_count") or 0)
    owner_attempted = int(ownership.get("attempted") or 0)
    owner_family_count = int(ownership.get("annotated_application_family_count") or 0)
    gate(
        "valid_case_coverage",
        valid_case_count >= 8,
        expected={"min": 8},
        actual=valid_case_count,
        severity="needs_review",
    )
    gate(
        "application_family_diversity",
        family_count >= 8,
        expected={"min": 8},
        actual=family_count,
        severity="needs_review",
    )
    gate(
        "ownership_holdout_sample_size",
        owner_attempted >= 30,
        expected={"min": 30},
        actual=owner_attempted,
        severity="needs_review",
    )
    gate(
        "ownership_holdout_family_diversity",
        owner_family_count >= 8,
        expected={"min": 8},
        actual=owner_family_count,
        severity="needs_review",
    )
    gate(
        "ownership_holdout_no_mismatch",
        not (ownership.get("mismatches") or []),
        expected=0,
        actual=len(ownership.get("mismatches") or []),
        severity="needs_review",
    )
    gate(
        "review_evidence_complete",
        int(review.get("available") or 0) >= valid_case_count and valid_case_count > 0,
        expected={"min": valid_case_count},
        actual=int(review.get("available") or 0),
        severity="needs_review",
    )
    gate(
        "explicit_failure_sample",
        int(summary.get("known_limitation_count") or 0) >= 1 and bool(benchmark.get("known_limitations")),
        expected={"min": 1},
        actual=int(summary.get("known_limitation_count") or 0),
        severity="needs_review",
    )

    status = "blocked" if blocking_gates else ("needs_review" if needs_review_gates else "ready")
    return {
        "contract_version": "general_ui_recognition_showcase_readiness_v1",
        "status": status,
        "ready": status == "ready",
        "blocked": status == "blocked",
        "blocking_gates": blocking_gates,
        "needs_review_gates": needs_review_gates,
        "failed_gate_ids": [item["gate_id"] for item in [*blocking_gates, *needs_review_gates]],
        "evidence": {
            "benchmark_contract": benchmark.get("contract_version"),
            "panel_smoke_contract": panel_smoke.get("contract_version"),
            "valid_case_count": valid_case_count,
            "supported_application_family_count": family_count,
            "ownership_annotation_count": owner_attempted,
            "ownership_application_family_count": owner_family_count,
            "review_sheet_count": int(review.get("available") or 0),
        },
        "interpretation": (
            "Showcase evidence gate only; ready does not mean model accuracy, live GUI reliability, or Execute authorization."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check General UI recognition showcase readiness.")
    parser.add_argument("--benchmark-report", required=True)
    parser.add_argument("--panel-smoke", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    benchmark_path = Path(args.benchmark_report)
    panel_smoke_path = Path(args.panel_smoke)
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8-sig"))
    panel_smoke = json.loads(panel_smoke_path.read_text(encoding="utf-8-sig"))
    report = evaluate_readiness(benchmark, panel_smoke)
    report["benchmark_report_path"] = str(benchmark_path)
    report["panel_smoke_path"] = str(panel_smoke_path)
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"status={report['status']}")
        print(f"report_path={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
