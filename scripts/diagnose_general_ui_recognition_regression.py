from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_general_ui_recognition_benchmark import (
    _resolve,
    _stage1_inventory_from_trace_result,
)


_REGION_ROLE_ALIASES = {
    "browser_chrome": "browser_chrome",
    "page_header": "top_bar",
    "top_bar": "top_bar",
    "left_nav": "left_nav",
    "left_sidebar": "left_nav",
    "main_content": "main_content",
    "primary_area": "main_content",
    "bottom_bar": "bottom_bar",
    "status_bar": "bottom_bar",
    "conversation_list": "conversation_list",
    "message_thread": "message_thread",
}


def _read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _canonical_region_role(region_id: str) -> str:
    normalized = str(region_id or "").casefold()
    for token, role in _REGION_ROLE_ALIASES.items():
        if token in normalized:
            return role
    return normalized.removeprefix("structure_region_")


def _stage2_region_roles(report: dict[str, Any]) -> set[str]:
    stage2 = report.get("stage2_numbering") if isinstance(report.get("stage2_numbering"), dict) else {}
    return {
        _canonical_region_role(str(region.get("region_id") or region.get("role") or ""))
        for region in stage2.get("regions", [])
        if isinstance(region, dict)
    }


def _source_inventory_ids(trace_path: str) -> set[str]:
    trace = _read_json(_resolve(trace_path))
    result = trace.get("result") if isinstance(trace.get("result"), dict) else trace
    return {
        str(item.get("item_id") or item.get("candidate_id") or "")
        for item in _stage1_inventory_from_trace_result(result)
        if isinstance(item, dict)
    }


def _assertion_map(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(assertion.get("assertion_id") or ""): assertion
        for assertion in case.get("assertions", [])
        if isinstance(assertion, dict)
    }


def _diagnose_ownership(
    mismatch: dict[str, Any],
    *,
    current_region_roles: set[str],
    source_ids: set[str],
    baseline_passed: bool,
) -> dict[str, Any]:
    failure = str(mismatch.get("failure_category") or "")
    expected_region_role = _canonical_region_role(str(mismatch.get("region_id") or ""))
    item_id = str(mismatch.get("item_id") or "")
    source_item_present = item_id in source_ids
    equivalent_region_present = expected_region_role in current_region_roles

    if failure == "ownership_region_missing" and equivalent_region_present:
        diagnosis = "benchmark_region_identity_contract_drift"
        responsibility = "benchmark_contract"
    elif failure == "ownership_region_missing":
        diagnosis = "stage1_or_stage1_5_region_regression"
        responsibility = "code_regression"
    elif failure == "ownership_item_missing" and source_item_present:
        diagnosis = "stage2_source_item_lineage_loss"
        responsibility = "code_regression"
    elif failure == "ownership_item_missing" and baseline_passed:
        diagnosis = "generated_candidate_id_contract_drift"
        responsibility = "benchmark_or_generated_contract"
    else:
        diagnosis = failure or "ownership_role_mismatch"
        responsibility = "code_regression" if baseline_passed else "unclassified"

    return {
        **mismatch,
        "expected_region_role": expected_region_role,
        "equivalent_region_present": equivalent_region_present,
        "source_item_present": source_item_present,
        "diagnosis": diagnosis,
        "responsibility": responsibility,
    }


def diagnose_reports(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    baseline_cases = {str(case.get("case_id") or ""): case for case in baseline.get("cases", [])}
    diagnoses: list[dict[str, Any]] = []
    classification_counts: dict[str, int] = {}

    for current_case in current.get("cases", []):
        if not isinstance(current_case, dict):
            continue
        case_id = str(current_case.get("case_id") or "")
        baseline_case = baseline_cases.get(case_id, {})
        same_screenshot = (
            bool(current_case.get("screenshot_sha256"))
            and current_case.get("screenshot_sha256") == baseline_case.get("screenshot_sha256")
        )
        fixture_status = "checksum_match" if same_screenshot else "stale_or_unmatched_fixture"
        current_report = _read_json(_resolve(str(current_case.get("two_stage_report_path") or "")))
        baseline_report = (
            _read_json(_resolve(str(baseline_case.get("two_stage_report_path") or "")))
            if baseline_case.get("two_stage_report_path")
            else {}
        )
        current_assertions = _assertion_map(current_case)
        baseline_assertions = _assertion_map(baseline_case)
        known_limitation_drift = current_case.get("case_outcome") == "known_limitation_drifted"
        failed_assertions: list[dict[str, Any]] = []
        for assertion in current_case.get("failed_assertions", []):
            if not isinstance(assertion, dict):
                continue
            assertion_id = str(assertion.get("assertion_id") or "")
            baseline_assertion = baseline_assertions.get(assertion_id, {})
            failed_assertions.append(
                {
                    **assertion,
                    "baseline_passed": baseline_assertion.get("passed") is True,
                    "responsibility": (
                        "known_limitation_contract"
                        if known_limitation_drift
                        else "code_regression"
                        if same_screenshot and baseline_assertion.get("passed") is True
                        else "benchmark_or_fixture_review"
                    ),
                }
            )

        source_ids = _source_inventory_ids(str(current_case.get("trace_path") or ""))
        baseline_ownership_checks = {
            str(check.get("annotation_id") or ""): check
            for check in (baseline_case.get("ownership_golden") or {}).get("checks", [])
            if isinstance(check, dict)
        }
        ownership_diagnoses = [
            _diagnose_ownership(
                mismatch,
                current_region_roles=_stage2_region_roles(current_report),
                source_ids=source_ids,
                baseline_passed=(
                    baseline_ownership_checks.get(str(mismatch.get("annotation_id") or ""), {}).get("passed") is True
                ),
            )
            for mismatch in (current_case.get("ownership_golden") or {}).get("mismatches", [])
            if isinstance(mismatch, dict)
        ]

        root_causes = sorted(
            {
                str(item.get("diagnosis") or "")
                for item in ownership_diagnoses
                if item.get("diagnosis")
            }
            | {
                "stage1_or_downstream_code_regression"
                for item in failed_assertions
                if item.get("responsibility") == "code_regression"
                and str(item.get("category") or "") in {"stage1", "stage2", "hierarchy", "semantics"}
            }
        )
        if fixture_status != "checksum_match":
            root_causes.insert(0, "stale_or_unmatched_fixture")
        if known_limitation_drift:
            root_causes.append("known_limitation_expectation_drift")
        for cause in root_causes:
            classification_counts[cause] = classification_counts.get(cause, 0) + 1

        current_classification = current_case.get("interface_classification") or {}
        class_profile = current_case.get("class_rule_profile") or {}
        diagnoses.append(
            {
                "case_id": case_id,
                "case_outcome": current_case.get("case_outcome"),
                "fixture": {
                    "status": fixture_status,
                    "screenshot_sha256": current_case.get("screenshot_sha256"),
                    "baseline_screenshot_sha256": baseline_case.get("screenshot_sha256"),
                },
                "stage1": {
                    "current_source": current_report.get("stage1_source"),
                    "baseline_source": baseline_report.get("stage1_source"),
                    "failed_assertions": [item for item in failed_assertions if item.get("category") in {"stage1", "stage2"}],
                },
                "ownership_golden": {
                    "mismatches": ownership_diagnoses,
                },
                "class_profile": {
                    "category": current_classification.get("category"),
                    "source": current_classification.get("source"),
                    "strategy": class_profile.get("primary_content_strategy"),
                    "caused_failed_assertion": any(item.get("category") == "class_profile" for item in failed_assertions),
                },
                "other_failed_assertions": [item for item in failed_assertions if item.get("category") not in {"stage1", "stage2"}],
                "root_causes": root_causes,
                "evidence": {
                    "screenshot_path": current_case.get("screenshot_path"),
                    "stage1_overlay_path": ((current_case.get("review_evidence") or {}).get("evidence_paths") or {}).get("stage1"),
                    "final_overlay_path": current_case.get("overlay_path"),
                    "review_sheet_path": (current_case.get("review_evidence") or {}).get("review_sheet_path"),
                    "trace_path": current_case.get("trace_path"),
                },
            }
        )

    return {
        "contract_version": "general_ui_recognition_regression_diagnosis_v1",
        "current_report_path": current.get("report_path"),
        "baseline_report_path": baseline.get("report_path"),
        "case_count": len(diagnoses),
        "fixture_stale_case_count": sum(1 for item in diagnoses if item["fixture"]["status"] != "checksum_match"),
        "classification_counts": classification_counts,
        "cases": diagnoses,
        "interpretation": "Fixed recorded-surface regression diagnosis; not model accuracy or general UI reliability.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose fixed general-UI benchmark regressions by layer.")
    parser.add_argument("--current", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = diagnose_reports(_read_json(args.current), _read_json(args.baseline))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps({"report_path": str(out_path), "classification_counts": payload["classification_counts"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
