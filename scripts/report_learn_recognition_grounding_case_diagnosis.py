from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def build_grounding_case_diagnosis_report(
    *,
    matrix_report_path: str | Path,
    baseline_profile: str,
    comparison_profile: str | None = None,
    out_dir: str | Path,
    json_stdout: bool = False,
) -> dict[str, Any]:
    matrix_report_path = Path(matrix_report_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix = _read_json(matrix_report_path)
    rows = _matrix_rows(matrix)
    if baseline_profile not in rows:
        raise ValueError(f"baseline profile not found in matrix report: {baseline_profile}")
    if comparison_profile and comparison_profile not in rows:
        raise ValueError(f"comparison profile not found in matrix report: {comparison_profile}")

    baseline_batch_path = Path(rows[baseline_profile]["batch_report_path"])
    baseline_batch = _read_json(_resolve_relative_to(matrix_report_path.parent, baseline_batch_path))
    comparison_batch = None
    if comparison_profile:
        comparison_batch_path = Path(rows[comparison_profile]["batch_report_path"])
        comparison_batch = _read_json(_resolve_relative_to(matrix_report_path.parent, comparison_batch_path))

    comparison_index = _case_index(comparison_batch.get("case_reports", []) if comparison_batch else [])
    diagnostics: list[dict[str, Any]] = []
    failure_categories: Counter[str] = Counter()
    comparison_outcomes: Counter[str] = Counter()

    for baseline_case in baseline_batch.get("case_reports", []):
        if not _is_failed_actual_case(baseline_case):
            continue
        key = _case_key(baseline_case)
        comparison_case = comparison_index.get(key)
        failure_category = _failure_category(baseline_case)
        failure_categories[failure_category] += 1
        comparison_outcome = _comparison_outcome(comparison_case)
        comparison_outcomes[comparison_outcome] += 1
        diagnostics.append(
            {
                "diagnostic_case_id": key,
                "case_id": baseline_case.get("case_id"),
                "label": baseline_case.get("label"),
                "surface": _batch_surface(baseline_case),
                "expected_case_outcome": _batch_case(baseline_case).get("expected_case_outcome"),
                "baseline_profile": baseline_profile,
                "comparison_profile": comparison_profile,
                "source_type": baseline_case.get("source_type"),
                "screenshot_path": baseline_case.get("screenshot_path"),
                "baseline": _case_evidence(baseline_case),
                "comparison": _case_evidence(comparison_case) if comparison_case else None,
                "diagnosis": _diagnose_case(baseline_case, comparison_case),
            }
        )

    report = {
        "contract_version": "learn_recognition_grounding_case_diagnosis_v1",
        "matrix_report_path": str(matrix_report_path),
        "baseline_profile": baseline_profile,
        "comparison_profile": comparison_profile,
        "diagnostic_case_count": len(diagnostics),
        "failure_category_breakdown": dict(failure_categories),
        "comparison_outcome_breakdown": dict(comparison_outcomes),
        "diagnostic_cases": diagnostics,
        "interpretation": (
            "case-level diagnosis for failed actual grounding calls in a fixed small matrix; "
            "not 90% accuracy, not model reliability, not Execute success, not click authorization"
        ),
        "safety_boundary": {
            "real_clicks_performed": 0,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
            "live_safe_fill_attempted": 0,
        },
    }
    report_path = out_dir / "learn_grounding_case_diagnosis_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _matrix_rows(matrix: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = matrix.get("matrix_summary", {}).get("rows", [])
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("model_profile_id")): row
        for row in rows
        if isinstance(row, dict) and row.get("model_profile_id")
    }


def _case_index(case_reports: list[Any]) -> dict[str, dict[str, Any]]:
    return {
        _case_key(case): case
        for case in case_reports
        if isinstance(case, dict)
    }


def _case_key(case: dict[str, Any]) -> str:
    return f"{case.get('case_id') or ''}::{case.get('label') or ''}"


def _is_failed_actual_case(case: Any) -> bool:
    return (
        isinstance(case, dict)
        and case.get("actual_model_call_in_this_run") is True
        and case.get("status") == "failed"
    )


def _case_evidence(case: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(case, dict):
        return None
    point_quality = case.get("point_quality") if isinstance(case.get("point_quality"), dict) else {}
    validation = case.get("validation") if isinstance(case.get("validation"), dict) else {}
    normalized = case.get("normalized_grounding") if isinstance(case.get("normalized_grounding"), dict) else {}
    request = case.get("grounding_request") if isinstance(case.get("grounding_request"), dict) else {}
    target = request.get("target") if isinstance(request.get("target"), dict) else {}
    roi_crop = request.get("roi_crop") if isinstance(request.get("roi_crop"), dict) else {}
    transform = roi_crop.get("coordinate_transform") if isinstance(roi_crop.get("coordinate_transform"), dict) else {}
    return {
        "status": case.get("status"),
        "actual_model_call_in_this_run": case.get("actual_model_call_in_this_run"),
        "roi_image_path": case.get("roi_image_path"),
        "actual_grounding_output_path": case.get("actual_grounding_output_path"),
        "raw_model_output": case.get("raw_model_output"),
        "coordinate_space": normalized.get("coordinate_space"),
        "raw_output": normalized.get("raw_output"),
        "roi_candidate_bbox": point_quality.get("roi_candidate_bbox") or target.get("candidate_bbox_in_roi"),
        "screen_bbox": point_quality.get("screen_bbox") or target.get("candidate_bbox"),
        "roi_point": point_quality.get("roi_point"),
        "roi_point_source": point_quality.get("roi_point_source"),
        "screen_point": point_quality.get("screen_point") or validation.get("screen_point"),
        "point_quality_status": point_quality.get("status"),
        "point_quality_failure_category": point_quality.get("failure_category"),
        "distance_to_bbox": (point_quality.get("error") or {}).get("distance_to_bbox")
        if isinstance(point_quality.get("error"), dict)
        else None,
        "validation_status": validation.get("status"),
        "validation_failure_category": validation.get("failure_category"),
        "validation_checks": validation.get("checks") if isinstance(validation.get("checks"), dict) else {},
        "coordinate_transform": transform,
        "safety": case.get("safety") if isinstance(case.get("safety"), dict) else {},
    }


def _diagnose_case(baseline_case: dict[str, Any], comparison_case: dict[str, Any] | None) -> dict[str, Any]:
    baseline_evidence = _case_evidence(baseline_case) or {}
    checks = baseline_evidence.get("validation_checks") if isinstance(baseline_evidence.get("validation_checks"), dict) else {}
    point_failure = baseline_evidence.get("point_quality_failure_category")
    root_cause = "unknown_failed_actual_grounding_case"
    failed_layer = "unknown"
    if point_failure == "model_point_outside_roi_candidate_bbox":
        if checks.get("coordinate_transform_replay") and checks.get("uia_or_dom_or_parser_overlap"):
            root_cause = "model_returned_point_outside_candidate_bbox_with_valid_roi_and_transform"
            failed_layer = "model_point_quality"
        else:
            root_cause = "point_outside_bbox_with_possible_fixture_or_transform_gap"
            failed_layer = "evidence_or_transform_needs_review"
    comparison_status = comparison_case.get("status") if isinstance(comparison_case, dict) else "missing"
    return {
        "root_cause": root_cause,
        "failed_layer": failed_layer,
        "baseline_gate_safety": _gate_safety_status(baseline_evidence),
        "comparison_outcome": _comparison_outcome(comparison_case),
        "comparison_status": comparison_status,
        "candidate_recall_or_fixture_status": _candidate_evidence_status(checks),
        "proposed_intervention": _proposed_intervention(root_cause, comparison_status),
    }


def _gate_safety_status(evidence: dict[str, Any]) -> str:
    validation_status = evidence.get("validation_status")
    safety = evidence.get("safety") if isinstance(evidence.get("safety"), dict) else {}
    if validation_status == "rejected" and safety.get("real_clicks_performed", 0) == 0:
        return "passed_rejected_no_action"
    if validation_status == "valid_candidate" and safety.get("real_clicks_performed", 0) == 0:
        return "valid_candidate_no_action"
    return "needs_review"


def _candidate_evidence_status(checks: dict[str, Any]) -> str:
    required = [
        "bbox_inside_image",
        "uia_or_dom_or_parser_overlap",
        "coordinate_transform_replay",
        "screenshot_freshness",
    ]
    if all(checks.get(key) is True for key in required):
        return "candidate_and_fixture_evidence_present"
    missing = [key for key in required if checks.get(key) is not True]
    return "needs_review:" + ",".join(missing)


def _comparison_outcome(case: dict[str, Any] | None) -> str:
    if not isinstance(case, dict):
        return "comparison_case_missing"
    if case.get("actual_model_call_in_this_run") is not True:
        return "comparison_not_actual_call"
    if case.get("status") == "passed":
        return "comparison_passed_same_case"
    if case.get("status") == "failed":
        return "comparison_failed_same_case"
    return str(case.get("status") or "comparison_unknown_status")


def _proposed_intervention(root_cause: str, comparison_status: str) -> str:
    if root_cause == "model_returned_point_outside_candidate_bbox_with_valid_roi_and_transform":
        if comparison_status == "passed":
            return (
                "keep Validator unchanged; expand actual-call cases around small controls and compare UGround against VISTA "
                "before considering a profile default for Learn grounding"
            )
        return "keep Validator unchanged; inspect ROI crop and prompt for small-control point selection before more trials"
    return "repair fixture/coordinate evidence before using this case for model comparison"


def _failure_category(case: dict[str, Any]) -> str:
    point_quality = case.get("point_quality") if isinstance(case.get("point_quality"), dict) else {}
    validation = case.get("validation") if isinstance(case.get("validation"), dict) else {}
    return str(point_quality.get("failure_category") or validation.get("failure_category") or "unknown")


def _batch_case(case: dict[str, Any]) -> dict[str, Any]:
    return case.get("batch_case") if isinstance(case.get("batch_case"), dict) else {}


def _batch_surface(case: dict[str, Any]) -> str:
    batch_case = _batch_case(case)
    return str(batch_case.get("surface") or "")


def _resolve_relative_to(base_dir: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    if path.exists():
        return path
    return (base_dir / path).resolve()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix-report", required=True)
    parser.add_argument("--baseline-profile", required=True)
    parser.add_argument("--comparison-profile", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_grounding_case_diagnosis_report(
        matrix_report_path=args.matrix_report,
        baseline_profile=args.baseline_profile,
        comparison_profile=args.comparison_profile,
        out_dir=args.out,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
