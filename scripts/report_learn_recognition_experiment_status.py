from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


QUALITY_TARGET = 0.9
DEFAULT_MIN_ACTUAL_PARSER_CASES = 30
DEFAULT_MIN_ACTUAL_GROUNDING_CASES = 30
DEFAULT_MIN_CANDIDATE_CASES = 10


def build_learn_recognition_experiment_status(
    *,
    benchmark_path: str | Path | None = None,
    readiness_path: str | Path | None = None,
    grounding_matrix_paths: list[str | Path] | None = None,
    actual_parser_report_paths: list[str | Path] | None = None,
    out: str | Path | None = None,
    quality_target: float = QUALITY_TARGET,
    min_actual_parser_cases: int = DEFAULT_MIN_ACTUAL_PARSER_CASES,
    min_actual_grounding_cases: int = DEFAULT_MIN_ACTUAL_GROUNDING_CASES,
    min_candidate_cases: int = DEFAULT_MIN_CANDIDATE_CASES,
    json_stdout: bool = False,
) -> dict[str, Any]:
    benchmark = _read_optional_json(benchmark_path)
    readiness = _read_optional_json(readiness_path)
    grounding_matrices = [_read_optional_json(path) for path in grounding_matrix_paths or []]
    parser_reports = [_read_optional_json(path) for path in actual_parser_report_paths or []]

    layer_metrics = _layer_metrics(benchmark)
    actual_coverage = _actual_coverage(
        benchmark=benchmark,
        grounding_matrices=grounding_matrices,
        parser_reports=parser_reports,
    )
    readiness_summary = _readiness_summary(readiness)
    target_eval = _quality_target_evaluation(
        layer_metrics=layer_metrics,
        actual_coverage=actual_coverage,
        quality_target=quality_target,
        min_actual_parser_cases=min_actual_parser_cases,
        min_actual_grounding_cases=min_actual_grounding_cases,
        min_candidate_cases=min_candidate_cases,
    )
    report = {
        "contract_version": "learn_recognition_experiment_status_v1",
        "input_reports": {
            "benchmark_path": str(benchmark_path or ""),
            "readiness_path": str(readiness_path or ""),
            "grounding_matrix_paths": [str(path) for path in grounding_matrix_paths or []],
            "actual_parser_report_paths": [str(path) for path in actual_parser_report_paths or []],
        },
        "recognition_quality_target": {
            "target_rate": quality_target,
            "claim_status": target_eval["claim_status"],
            "reasons": target_eval["reasons"],
            "minimum_evidence_policy": {
                "min_actual_parser_cases": min_actual_parser_cases,
                "min_actual_grounding_cases": min_actual_grounding_cases,
                "min_pathgraph_candidate_cases": min_candidate_cases,
            },
            "interpretation": (
                "target gate only; this report does not prove 90% recognition quality unless all "
                "minimum actual-call and candidate-connection evidence is present"
            ),
        },
        "layer_metrics": layer_metrics,
        "actual_coverage": actual_coverage,
        "learn_recognition_stage_coverage": _stage_coverage(
            benchmark=benchmark,
            layer_metrics=layer_metrics,
            actual_coverage=actual_coverage,
            min_actual_parser_cases=min_actual_parser_cases,
            min_actual_grounding_cases=min_actual_grounding_cases,
            min_candidate_cases=min_candidate_cases,
        ),
        "source_denominator_breakdown": _source_denominator_breakdown(
            benchmark=benchmark,
            actual_coverage=actual_coverage,
        ),
        "parser_usefulness_requirements": _parser_usefulness_requirements(),
        "parser_actual_call_usefulness": _parser_actual_call_usefulness(actual_coverage),
        "pathgraph_connection_readiness": _pathgraph_connection_readiness(actual_coverage),
        "decision_taxonomy_status": _decision_taxonomy_status(),
        "model_readiness": readiness_summary,
        "next_experiment_gate": _next_experiment_gate(target_eval, readiness_summary, actual_coverage),
        "anti_inflation": {
            "no_headline_rate": True,
            "fixture_only_not_model_ability": True,
            "recorded_output_not_fresh_actual_call": True,
            "pathgraph_candidate_not_execute_authorization": True,
            "no_live_click": True,
            "no_live_safe_fill": True,
            "no_submit": True,
        },
        "recommended_next_work": _recommended_next_work(target_eval, readiness_summary, actual_coverage),
    }
    if out:
        out_path = Path(out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["report_path"] = str(out_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _layer_metrics(benchmark: dict[str, Any]) -> dict[str, Any]:
    metrics = benchmark.get("metrics") if isinstance(benchmark.get("metrics"), dict) else {}
    names = [
        "parse_inventory",
        "actionable_classification",
        "form_field_classification",
        "semantic_only_rejection",
        "non_actionable_leaked_to_grounding",
        "roi_target_coverage",
        "grounding_point",
        "coordinate_transform",
        "pathgraph_candidate_validation",
    ]
    result = {name: _metric(metrics.get(name)) for name in names}
    result["source_breakdown"] = benchmark.get("source_breakdown") if isinstance(benchmark.get("source_breakdown"), dict) else {}
    result["parser_reliability_status"] = str(benchmark.get("parser_reliability_status") or "not_reported")
    result["grounding_reliability_status"] = str(benchmark.get("grounding_reliability_status") or "not_reported")
    result["interpretation"] = "layer metrics keep denominators separate; no combined headline rate is produced"
    return result


def _actual_coverage(
    *,
    benchmark: dict[str, Any],
    grounding_matrices: list[dict[str, Any]],
    parser_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    source_breakdown = benchmark.get("source_breakdown") if isinstance(benchmark.get("source_breakdown"), dict) else {}
    parser_from_benchmark = _int(source_breakdown.get("actual_parser_call"))
    grounding_from_benchmark = _int(source_breakdown.get("actual_grounding_call"))
    parser_from_reports = sum(_metric_attempted((report.get("metrics") or {}).get("actual_parser_call")) for report in parser_reports)
    parser_candidate_attempted = sum(
        _metric_attempted((report.get("metrics") or {}).get("parser_case_has_grounding_candidate"))
        for report in parser_reports
    )
    parser_candidate_passed = sum(
        _int(((report.get("metrics") or {}).get("parser_case_has_grounding_candidate") or {}).get("passed"))
        for report in parser_reports
        if isinstance((report.get("metrics") or {}).get("parser_case_has_grounding_candidate"), dict)
    )
    parser_item_attempted = sum(
        _metric_attempted((report.get("metrics") or {}).get("grounding_eligible_item_yield"))
        for report in parser_reports
    )
    parser_item_passed = sum(
        _int(((report.get("metrics") or {}).get("grounding_eligible_item_yield") or {}).get("passed"))
        for report in parser_reports
        if isinstance((report.get("metrics") or {}).get("grounding_eligible_item_yield"), dict)
    )
    cases_without_grounding_candidates: list[str] = []
    cases_ready_for_pathgraph_candidate: list[str] = []
    grounding_candidate_backlog: list[dict[str, Any]] = []
    supplemental_source_validity = {
        "by_status": {},
        "stale_or_invalid_cases": [],
        "interpretation": "supplemental evidence must match the case screenshot before it can support grounding candidates",
    }
    for report in parser_reports:
        summary = report.get("actionability_summary") if isinstance(report.get("actionability_summary"), dict) else {}
        cases = summary.get("cases_without_grounding_candidates")
        if isinstance(cases, list):
            cases_without_grounding_candidates.extend(str(case) for case in cases)
        backlog = summary.get("grounding_candidate_backlog")
        if isinstance(backlog, list):
            grounding_candidate_backlog.extend(item for item in backlog if isinstance(item, dict))
        usefulness = report.get("parser_actual_call_usefulness") if isinstance(report.get("parser_actual_call_usefulness"), dict) else {}
        ready_cases = usefulness.get("cases_useful_for_grounding")
        if isinstance(ready_cases, list):
            _extend_unique(cases_ready_for_pathgraph_candidate, (str(case) for case in ready_cases))
        _merge_supplemental_source_validity(
            supplemental_source_validity,
            report.get("supplemental_source_validity_summary"),
        )
    grounding_from_matrices = 0
    grounding_profiles: list[dict[str, Any]] = []
    for matrix in grounding_matrices:
        rows = (((matrix.get("matrix_summary") or {}).get("rows")) if isinstance(matrix.get("matrix_summary"), dict) else [])
        for row in rows if isinstance(rows, list) else []:
            actual = row.get("actual_model_call") if isinstance(row.get("actual_model_call"), dict) else {}
            attempted = _metric_attempted(actual)
            grounding_from_matrices += attempted
            grounding_profiles.append(
                {
                    "model_profile_id": row.get("model_profile_id"),
                    "attempted": attempted,
                    "passed": _int(actual.get("passed")),
                    "rate": actual.get("rate", "not_covered"),
                    "batch_report_path": row.get("batch_report_path"),
                }
            )
    return {
        "actual_parser_call_attempted": parser_from_benchmark + parser_from_reports,
        "actual_grounding_call_attempted": grounding_from_benchmark + grounding_from_matrices,
        "parser_cases_with_grounding_candidate": parser_candidate_passed,
        "parser_grounding_candidate_case_attempted": parser_candidate_attempted,
        "parser_grounding_candidate_case_rate": (
            "not_covered" if parser_candidate_attempted == 0 else round(parser_candidate_passed / parser_candidate_attempted, 4)
        ),
        "parser_accepted_for_grounding_item_count": parser_item_passed,
        "parser_grounding_eligible_item_count": parser_item_passed,
        "parser_screen_inventory_item_count": parser_item_attempted,
        "parser_grounding_eligible_item_rate": (
            "not_covered" if parser_item_attempted == 0 else round(parser_item_passed / parser_item_attempted, 4)
        ),
        "parser_cases_without_grounding_candidates": cases_without_grounding_candidates,
        "parser_cases_ready_for_pathgraph_candidate": cases_ready_for_pathgraph_candidate,
        "parser_grounding_candidate_backlog": grounding_candidate_backlog,
        "parser_supplemental_source_validity": supplemental_source_validity,
        "actual_parser_sources": {
            "benchmark_source_breakdown": parser_from_benchmark,
            "actual_parser_reports": parser_from_reports,
        },
        "actual_grounding_sources": {
            "benchmark_source_breakdown": grounding_from_benchmark,
            "grounding_model_matrices": grounding_from_matrices,
        },
        "grounding_profile_attempts": grounding_profiles,
        "interpretation": "fresh actual calls only; fixture and recorded-only cases are excluded from these counts",
    }


def _extend_unique(target: list[str], values: Any) -> None:
    seen = set(target)
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        target.append(item)
        seen.add(item)


def _merge_supplemental_source_validity(target: dict[str, Any], source: Any) -> None:
    if not isinstance(source, dict):
        return
    target_by_status = target.setdefault("by_status", {})
    source_by_status = source.get("by_status") if isinstance(source.get("by_status"), dict) else {}
    for status, count in source_by_status.items():
        key = str(status)
        target_by_status[key] = _int(target_by_status.get(key)) + _int(count)
    source_stale = source.get("stale_or_invalid_cases")
    if isinstance(source_stale, list):
        target.setdefault("stale_or_invalid_cases", []).extend(item for item in source_stale if isinstance(item, dict))


def _stage_coverage(
    *,
    benchmark: dict[str, Any],
    layer_metrics: dict[str, Any],
    actual_coverage: dict[str, Any],
    min_actual_parser_cases: int,
    min_actual_grounding_cases: int,
    min_candidate_cases: int,
) -> dict[str, Any]:
    source_breakdown = benchmark.get("source_breakdown") if isinstance(benchmark.get("source_breakdown"), dict) else {}
    parser_actual = _int(actual_coverage.get("actual_parser_call_attempted"))
    grounding_actual = _int(actual_coverage.get("actual_grounding_call_attempted"))
    recorded_parser = _int(source_breakdown.get("recorded_parser_output"))
    candidate_attempted = _metric_attempted(layer_metrics.get("actionable_classification"))
    pathgraph_attempted = _metric_attempted(layer_metrics.get("pathgraph_candidate_validation"))
    return {
        "parser_actual_call": {
            "attempted": parser_actual,
            "status": _minimum_status(parser_actual, min_actual_parser_cases),
        },
        "parser_recorded_output": {
            "attempted": recorded_parser,
            "status": "not_covered" if recorded_parser == 0 else "partially_covered",
        },
        "candidate_classification": {
            "attempted": candidate_attempted,
            "status": "not_covered" if candidate_attempted == 0 else "fixture_or_recorded_only",
            "interpretation": "classification coverage must be separated from actual parser model ability",
        },
        "roi_grounding_actual_call": {
            "attempted": grounding_actual,
            "status": _minimum_status(grounding_actual, min_actual_grounding_cases, covered_label="exploratory_saved_screenshot_only"),
        },
        "pathgraph_candidate_validation": {
            "attempted": pathgraph_attempted,
            "status": _minimum_status(pathgraph_attempted, min_candidate_cases),
            "interpretation": "pathgraph candidate validation is downstream pipeline coverage, not execute authorization",
        },
    }


def _minimum_status(attempted: int, minimum: int, *, covered_label: str = "minimum_covered") -> str:
    if attempted <= 0:
        return "not_covered"
    if attempted < minimum:
        return "insufficient_or_not_covered"
    return covered_label


def _source_denominator_breakdown(
    *,
    benchmark: dict[str, Any],
    actual_coverage: dict[str, Any],
) -> dict[str, Any]:
    source_breakdown = benchmark.get("source_breakdown") if isinstance(benchmark.get("source_breakdown"), dict) else {}
    return {
        "fixture_only": _int(source_breakdown.get("fixture_only")),
        "recorded_parser_output": _int(source_breakdown.get("recorded_parser_output")),
        "recorded_grounding_output": _int(source_breakdown.get("recorded_grounding_output")),
        "actual_parser_call": _int(actual_coverage.get("actual_parser_call_attempted")),
        "actual_grounding_call": _int(actual_coverage.get("actual_grounding_call_attempted")),
        "interpretation": "fixture and recorded outputs are not model reliability evidence",
    }


def _parser_usefulness_requirements() -> dict[str, Any]:
    return {
        "parser_useful_for_grounding_requires": [
            "grounding_eligible_regions > 0",
            "accepted_for_grounding > 0",
            "semantic_only_regions are separated as review_only",
            "blocked_from_grounding_reason is reported",
        ],
        "interpretation": "actual parser output must distinguish review evidence from grounding-eligible candidates",
    }


def _parser_actual_call_usefulness(actual_coverage: dict[str, Any]) -> dict[str, Any]:
    actual_parser_attempted = _int(actual_coverage.get("actual_parser_call_attempted"))
    inventory_count = _int(actual_coverage.get("parser_screen_inventory_item_count"))
    grounding_eligible = _int(actual_coverage.get("parser_grounding_eligible_item_count"))
    accepted_items = _int(actual_coverage.get("parser_accepted_for_grounding_item_count"))
    accepted_cases = _int(actual_coverage.get("parser_cases_with_grounding_candidate"))
    return {
        "parser_inventory_generated": actual_parser_attempted > 0 and inventory_count > 0,
        "parser_useful_for_review": actual_parser_attempted > 0 and inventory_count > 0,
        "parser_useful_for_grounding": actual_parser_attempted > 0 and grounding_eligible > 0 and accepted_cases > 0,
        "semantic_only_regions": max(0, inventory_count - grounding_eligible),
        "grounding_eligible_regions": grounding_eligible,
        "accepted_for_grounding": accepted_items,
        "blocked_from_grounding_reason": (
            "semantic_region_only_without_interactable_evidence"
            if actual_parser_attempted > 0 and grounding_eligible == 0
            else ""
        ),
        "interpretation": "review usefulness is not grounding usefulness unless grounding-eligible candidates are produced",
    }


def _pathgraph_connection_readiness(actual_coverage: dict[str, Any]) -> dict[str, Any]:
    ready_cases = [
        str(case)
        for case in actual_coverage.get("parser_cases_ready_for_pathgraph_candidate", [])
        if str(case).strip()
    ]
    backlog = actual_coverage.get("parser_grounding_candidate_backlog")
    backlog_items = backlog if isinstance(backlog, list) else []
    blocked_cases = [
        str(item.get("case_id"))
        for item in backlog_items
        if isinstance(item, dict) and str(item.get("case_id") or "").strip()
    ]
    if blocked_cases:
        status = "not_ready_for_pathgraph_candidate_promotion"
    elif ready_cases:
        status = "candidate_ready_for_pathgraph_review"
    else:
        status = "not_covered"
    return {
        "status": status,
        "ready_case_count": len(ready_cases),
        "backlog_case_count": len(blocked_cases),
        "ready_cases": ready_cases,
        "blocked_cases": blocked_cases,
        "interpretation": "parser grounding candidates are necessary before building or promoting PathGraph candidates; this is not Execute authorization",
    }


def _decision_taxonomy_status() -> dict[str, Any]:
    return {
        "status": "required_before_more_model_trials",
        "required_failure_categories": [
            "target_label_insensitive_same_point",
            "wide_bbox_click_target_ambiguity",
            "off_center_roi_bias",
            "multi_candidate_crop_confusion",
            "split_roi_required",
            "semantic_only_blocked_from_grounding",
            "non_actionable_leaked_to_grounding",
            "ocr_only_text_sent_to_grounding",
            "wrong_surface_grounding_blocked",
        ],
        "interpretation": "taxonomy is for explaining learn-mode recognition failures; it is not a prompt tuning result",
    }


def _readiness_summary(readiness: dict[str, Any]) -> dict[str, Any]:
    profiles = readiness.get("profiles") if isinstance(readiness.get("profiles"), list) else []
    ready_profiles = [profile for profile in profiles if profile.get("readiness_status") == "actual_call_ready"]
    learn_only_under_12b = [
        profile
        for profile in profiles
        if profile.get("mode_scope") in {"learn_only", "learn"}
        and isinstance(profile.get("max_parameters_b"), (int, float))
        and float(profile.get("max_parameters_b")) <= 12
    ]
    return {
        "profile_count": len(profiles),
        "actual_call_ready_profile_count": len(ready_profiles),
        "actual_call_ready_profiles": [profile.get("profile_id") for profile in ready_profiles],
        "learn_under_12b_profile_count": len(learn_only_under_12b),
        "learn_under_12b_profiles": [profile.get("profile_id") for profile in learn_only_under_12b],
        "interpretation": "readiness means callable profile metadata/path/endpoint state only; it is not model quality evidence",
    }


def _quality_target_evaluation(
    *,
    layer_metrics: dict[str, Any],
    actual_coverage: dict[str, Any],
    quality_target: float,
    min_actual_parser_cases: int,
    min_actual_grounding_cases: int,
    min_candidate_cases: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    if actual_coverage["actual_parser_call_attempted"] < min_actual_parser_cases:
        reasons.append("insufficient_actual_parser_cases")
    if actual_coverage["actual_grounding_call_attempted"] < min_actual_grounding_cases:
        reasons.append("insufficient_actual_grounding_cases")
    candidate_case_attempted = _int(actual_coverage.get("parser_grounding_candidate_case_attempted"))
    candidate_case_rate = actual_coverage.get("parser_grounding_candidate_case_rate")
    if candidate_case_attempted > 0 and isinstance(candidate_case_rate, (int, float)) and float(candidate_case_rate) < quality_target:
        reasons.append("parser_grounding_candidate_yield_below_target")
    elif actual_coverage["actual_parser_call_attempted"] > 0 and candidate_case_attempted == 0:
        reasons.append("parser_grounding_candidate_yield_not_covered")
    candidate_metric = layer_metrics.get("pathgraph_candidate_validation") or {}
    if _metric_attempted(candidate_metric) < min_candidate_cases:
        reasons.append("insufficient_pathgraph_candidate_cases")
    for metric_name in (
        "parse_inventory",
        "actionable_classification",
        "roi_target_coverage",
        "grounding_point",
        "coordinate_transform",
        "pathgraph_candidate_validation",
    ):
        metric = layer_metrics.get(metric_name) or {}
        rate = metric.get("rate")
        if isinstance(rate, (int, float)) and float(rate) < quality_target:
            reasons.append(f"{metric_name}_below_target")
        elif rate == "not_covered":
            reasons.append(f"{metric_name}_not_covered")
    claim_status = "eligible_for_quality_trend_review" if not reasons else "not_evaluable_for_90_percent_claim"
    return {"claim_status": claim_status, "reasons": sorted(set(reasons))}


def _next_experiment_gate(
    target_eval: dict[str, Any],
    readiness_summary: dict[str, Any],
    actual_coverage: dict[str, Any],
) -> dict[str, Any]:
    if (
        readiness_summary["actual_call_ready_profile_count"] == 0
        and actual_coverage["actual_parser_call_attempted"] == 0
        and actual_coverage["actual_grounding_call_attempted"] == 0
    ):
        status = "blocked_until_model_profile_ready"
    elif actual_coverage["actual_parser_call_attempted"] == 0:
        status = "run_actual_parser_smoke_next"
    elif actual_coverage["actual_grounding_call_attempted"] == 0:
        status = "run_grounding_model_matrix_next"
    elif target_eval["claim_status"] != "eligible_for_quality_trend_review":
        status = "expand_actual_case_coverage_next"
    else:
        status = "ready_for_quality_trend_review"
    return {
        "status": status,
        "interpretation": "next gate selects experiment work; it does not promote or authorize learned artifacts",
    }


def _recommended_next_work(
    target_eval: dict[str, Any],
    readiness_summary: dict[str, Any],
    actual_coverage: dict[str, Any],
) -> list[str]:
    work: list[str] = []
    if "insufficient_actual_parser_cases" in target_eval["reasons"]:
        work.append("Run actual parser smoke/matrix on fixed screenshots for Learn Fast candidates.")
    if (
        "parser_grounding_candidate_yield_below_target" in target_eval["reasons"]
        or "parser_grounding_candidate_yield_not_covered" in target_eval["reasons"]
    ):
        work.append("Diagnose parser actionability: actual parser inventory must produce grounding-eligible candidates before PathGraph connection.")
    if "insufficient_actual_grounding_cases" in target_eval["reasons"]:
        work.append("Run grounding model matrix on the same ROI cases for VISTA/UGround/other <12B profiles.")
    if "insufficient_pathgraph_candidate_cases" in target_eval["reasons"]:
        work.append("Enable pathgraph_candidate_validation expectations on more benchmark cases.")
    if readiness_summary["actual_call_ready_profile_count"] == 0:
        work.append("Materialize or start at least one learn-only <12B profile before measuring model output.")
    if not work and actual_coverage["actual_grounding_call_attempted"] > 0:
        work.append("Inspect per-case failures before tuning prompts or adding new models.")
    return work


def _metric(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"passed": 0, "attempted": 0, "rate": "not_covered"}
    attempted = _int(value.get("attempted"))
    passed = _int(value.get("passed"))
    return {
        "passed": passed,
        "attempted": attempted,
        "rate": "not_covered" if attempted == 0 else value.get("rate", round(passed / attempted, 4)),
    }


def _metric_attempted(value: Any) -> int:
    return _int(value.get("attempted")) if isinstance(value, dict) else 0


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _read_optional_json(path_value: str | Path | None) -> dict[str, Any]:
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark")
    parser.add_argument("--readiness")
    parser.add_argument("--grounding-matrix", action="append", default=None)
    parser.add_argument("--actual-parser-report", action="append", default=None)
    parser.add_argument("--out")
    parser.add_argument("--quality-target", type=float, default=QUALITY_TARGET)
    parser.add_argument("--min-actual-parser-cases", type=int, default=DEFAULT_MIN_ACTUAL_PARSER_CASES)
    parser.add_argument("--min-actual-grounding-cases", type=int, default=DEFAULT_MIN_ACTUAL_GROUNDING_CASES)
    parser.add_argument("--min-candidate-cases", type=int, default=DEFAULT_MIN_CANDIDATE_CASES)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_learn_recognition_experiment_status(
        benchmark_path=args.benchmark,
        readiness_path=args.readiness,
        grounding_matrix_paths=args.grounding_matrix,
        actual_parser_report_paths=args.actual_parser_report,
        out=args.out,
        quality_target=args.quality_target,
        min_actual_parser_cases=args.min_actual_parser_cases,
        min_actual_grounding_cases=args.min_actual_grounding_cases,
        min_candidate_cases=args.min_candidate_cases,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
