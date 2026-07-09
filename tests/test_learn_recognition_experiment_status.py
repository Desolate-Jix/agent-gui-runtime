from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_recognition_experiment_status import build_learn_recognition_experiment_status


def test_experiment_status_blocks_90_claim_for_fixture_only_reports(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_benchmark_report_v1",
                "source_breakdown": {
                    "fixture_only": 4,
                    "recorded_parser_output": 0,
                    "recorded_grounding_output": 0,
                    "actual_parser_call": 0,
                    "actual_grounding_call": 0,
                },
                "metrics": {
                    "parse_inventory": {"passed": 4, "attempted": 4, "rate": 1.0},
                    "actionable_classification": {"passed": 2, "attempted": 2, "rate": 1.0},
                    "roi_target_coverage": {"passed": 1, "attempted": 1, "rate": 1.0},
                    "grounding_point": {"passed": 1, "attempted": 1, "rate": 1.0},
                    "coordinate_transform": {"passed": 1, "attempted": 1, "rate": 1.0},
                    "pathgraph_candidate_validation": {"passed": 1, "attempted": 1, "rate": 1.0},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "profile_id": "learn_mode_qwen3_vl_8b",
                        "readiness_status": "actual_call_ready",
                        "mode_scope": "learn_only",
                        "max_parameters_b": 8,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_learn_recognition_experiment_status(
        benchmark_path=benchmark_path,
        readiness_path=readiness_path,
        min_actual_parser_cases=3,
        min_actual_grounding_cases=3,
        min_candidate_cases=3,
    )

    assert report["recognition_quality_target"]["claim_status"] == "not_evaluable_for_90_percent_claim"
    assert "insufficient_actual_parser_cases" in report["recognition_quality_target"]["reasons"]
    assert "insufficient_actual_grounding_cases" in report["recognition_quality_target"]["reasons"]
    assert "insufficient_pathgraph_candidate_cases" in report["recognition_quality_target"]["reasons"]
    assert report["actual_coverage"]["actual_parser_call_attempted"] == 0
    assert report["actual_coverage"]["actual_grounding_call_attempted"] == 0
    assert report["learn_recognition_stage_coverage"]["parser_actual_call"] == {
        "attempted": 0,
        "status": "not_covered",
    }
    assert report["learn_recognition_stage_coverage"]["parser_recorded_output"] == {
        "attempted": 0,
        "status": "not_covered",
    }
    assert report["learn_recognition_stage_coverage"]["candidate_classification"]["status"] == "fixture_or_recorded_only"
    assert report["learn_recognition_stage_coverage"]["roi_grounding_actual_call"]["status"] == "not_covered"
    assert report["learn_recognition_stage_coverage"]["pathgraph_candidate_validation"]["status"] == "insufficient_or_not_covered"
    assert report["source_denominator_breakdown"]["fixture_only"] == 4
    assert report["source_denominator_breakdown"]["actual_parser_call"] == 0
    assert report["source_denominator_breakdown"]["actual_grounding_call"] == 0
    assert report["source_denominator_breakdown"]["interpretation"] == "fixture and recorded outputs are not model reliability evidence"
    assert report["parser_usefulness_requirements"]["parser_useful_for_grounding_requires"] == [
        "grounding_eligible_regions > 0",
        "accepted_for_grounding > 0",
        "semantic_only_regions are separated as review_only",
        "blocked_from_grounding_reason is reported",
    ]
    assert "semantic_only_blocked_from_grounding" in report["decision_taxonomy_status"]["required_failure_categories"]
    assert "target_label_insensitive_same_point" in report["decision_taxonomy_status"]["required_failure_categories"]
    assert report["next_experiment_gate"]["status"] == "run_actual_parser_smoke_next"
    assert report["anti_inflation"]["no_headline_rate"] is True
    assert report["anti_inflation"]["fixture_only_not_model_ability"] is True
    assert "success_rate" not in json.dumps(report, ensure_ascii=False)


def test_experiment_status_aggregates_actual_parser_and_grounding_matrix(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "benchmark.json"
    benchmark_path.write_text(
        json.dumps(
            {
                "source_breakdown": {
                    "fixture_only": 0,
                    "recorded_parser_output": 0,
                    "recorded_grounding_output": 0,
                    "actual_parser_call": 2,
                    "actual_grounding_call": 0,
                },
                "metrics": {
                    "parse_inventory": {"passed": 3, "attempted": 3, "rate": 1.0},
                    "actionable_classification": {"passed": 3, "attempted": 3, "rate": 1.0},
                    "roi_target_coverage": {"passed": 3, "attempted": 3, "rate": 1.0},
                    "grounding_point": {"passed": 3, "attempted": 3, "rate": 1.0},
                    "coordinate_transform": {"passed": 3, "attempted": 3, "rate": 1.0},
                    "pathgraph_candidate_validation": {"passed": 3, "attempted": 3, "rate": 1.0},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(
        json.dumps(
            {
                "matrix_summary": {
                    "rows": [
                        {
                            "model_profile_id": "learn_grounding_vista_4b_baseline",
                            "actual_model_call": {"passed": 2, "attempted": 2, "rate": 1.0},
                            "batch_report_path": "logs/vista/report.json",
                        },
                        {
                            "model_profile_id": "learn_mode_uground_2b",
                            "actual_model_call": {"passed": 1, "attempted": 1, "rate": 1.0},
                            "batch_report_path": "logs/uground/report.json",
                        },
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    parser_report_path = tmp_path / "parser.json"
    parser_report_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "actual_parser_call": {"passed": 1, "attempted": 1, "rate": 1.0},
                    "parser_case_has_grounding_candidate": {"passed": 1, "attempted": 1, "rate": 1.0},
                    "grounding_eligible_item_yield": {"passed": 2, "attempted": 2, "rate": 1.0},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_learn_recognition_experiment_status(
        benchmark_path=benchmark_path,
        grounding_matrix_paths=[matrix_path],
        actual_parser_report_paths=[parser_report_path],
        min_actual_parser_cases=3,
        min_actual_grounding_cases=3,
        min_candidate_cases=3,
    )

    assert report["actual_coverage"]["actual_parser_call_attempted"] == 3
    assert report["actual_coverage"]["actual_grounding_call_attempted"] == 3
    assert report["learn_recognition_stage_coverage"]["parser_actual_call"]["status"] == "minimum_covered"
    assert report["learn_recognition_stage_coverage"]["roi_grounding_actual_call"]["status"] == "exploratory_saved_screenshot_only"
    assert report["source_denominator_breakdown"]["actual_parser_call"] == 3
    assert report["source_denominator_breakdown"]["actual_grounding_call"] == 3
    assert report["recognition_quality_target"]["claim_status"] == "eligible_for_quality_trend_review"
    assert report["next_experiment_gate"]["status"] == "ready_for_quality_trend_review"
    assert report["actual_coverage"]["grounding_profile_attempts"][1]["model_profile_id"] == "learn_mode_uground_2b"


def test_experiment_status_surfaces_parser_grounding_candidate_yield(tmp_path: Path) -> None:
    parser_report_path = tmp_path / "parser_batch.json"
    parser_report_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "actual_parser_call": {"passed": 5, "attempted": 5, "rate": 1.0},
                    "parser_case_has_grounding_candidate": {"passed": 2, "attempted": 5, "rate": 0.4},
                    "grounding_eligible_item_yield": {"passed": 7, "attempted": 60, "rate": 0.1167},
                },
                "actionability_summary": {
                    "cases_without_grounding_candidates": [
                        "python_homepage_saved_template_screenshot",
                        "seek_results_header_initial",
                    ],
                    "grounding_candidate_backlog": [
                        {
                            "case_id": "seek_results_header_initial",
                            "failure_category": "no_grounding_candidate",
                            "screen_inventory_count": 12,
                            "review_only_count": 12,
                            "supplemental_validity_status": "not_provided",
                            "recommended_intervention": "attach same-screenshot OCR/UIA/OmniParser/calibrated-target support or improve parser bbox alignment before PathGraph wiring",
                        }
                    ],
                    "total_screen_inventory_count": 60,
                    "total_grounding_eligible_count": 7,
                },
                "supplemental_source_validity_summary": {
                    "by_status": {"checksum_match": 2, "not_provided": 3},
                    "stale_or_invalid_cases": [],
                    "interpretation": "supplemental evidence must match the case screenshot before it can support grounding candidates",
                },
                "parser_actual_call_usefulness": {
                    "cases_useful_for_grounding": ["python_homepage_locate_trace_support_20260703", "seek_results_observe_screen"],
                    "cases_review_only_without_grounding": [
                        "python_homepage_saved_template_screenshot",
                        "seek_results_header_initial",
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_learn_recognition_experiment_status(
        actual_parser_report_paths=[parser_report_path],
        min_actual_parser_cases=1,
        min_actual_grounding_cases=1,
        min_candidate_cases=1,
    )

    assert report["actual_coverage"]["actual_parser_call_attempted"] == 5
    assert report["actual_coverage"]["parser_cases_with_grounding_candidate"] == 2
    assert report["actual_coverage"]["parser_grounding_candidate_case_attempted"] == 5
    assert report["actual_coverage"]["parser_accepted_for_grounding_item_count"] == 7
    assert report["actual_coverage"]["parser_grounding_eligible_item_count"] == 7
    assert report["actual_coverage"]["parser_screen_inventory_item_count"] == 60
    assert report["actual_coverage"]["parser_supplemental_source_validity"] == {
        "by_status": {"checksum_match": 2, "not_provided": 3},
        "stale_or_invalid_cases": [],
        "interpretation": "supplemental evidence must match the case screenshot before it can support grounding candidates",
    }
    usefulness = report["parser_actual_call_usefulness"]
    assert usefulness["parser_inventory_generated"] is True
    assert usefulness["parser_useful_for_review"] is True
    assert usefulness["parser_useful_for_grounding"] is True
    assert usefulness["semantic_only_regions"] == 53
    assert usefulness["grounding_eligible_regions"] == 7
    assert usefulness["accepted_for_grounding"] == 7
    assert usefulness["blocked_from_grounding_reason"] == ""
    assert report["actual_coverage"]["parser_cases_without_grounding_candidates"] == [
        "python_homepage_saved_template_screenshot",
        "seek_results_header_initial",
    ]
    assert report["actual_coverage"]["parser_grounding_candidate_backlog"] == [
        {
            "case_id": "seek_results_header_initial",
            "failure_category": "no_grounding_candidate",
            "screen_inventory_count": 12,
            "review_only_count": 12,
            "supplemental_validity_status": "not_provided",
            "recommended_intervention": "attach same-screenshot OCR/UIA/OmniParser/calibrated-target support or improve parser bbox alignment before PathGraph wiring",
        }
    ]
    assert report["actual_coverage"]["parser_cases_ready_for_pathgraph_candidate"] == [
        "python_homepage_locate_trace_support_20260703",
        "seek_results_observe_screen",
    ]
    assert report["pathgraph_connection_readiness"] == {
        "status": "not_ready_for_pathgraph_candidate_promotion",
        "ready_case_count": 2,
        "backlog_case_count": 1,
        "ready_cases": ["python_homepage_locate_trace_support_20260703", "seek_results_observe_screen"],
        "blocked_cases": ["seek_results_header_initial"],
        "interpretation": "parser grounding candidates are necessary before building or promoting PathGraph candidates; this is not Execute authorization",
    }
    assert "parser_grounding_candidate_yield_below_target" in report["recognition_quality_target"]["reasons"]
