from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_recognition_grounding_case_diagnosis import (
    build_grounding_case_diagnosis_report,
)


def test_grounding_case_diagnosis_compares_failed_baseline_to_passing_profile(tmp_path: Path) -> None:
    baseline_batch = _batch_report(
        [
            _actual_case(
                label="SEEK search button",
                status="failed",
                roi_point={"x": 36, "y": 24},
                failure_category="model_point_outside_roi_candidate_bbox",
                validation_status="rejected",
            )
        ]
    )
    comparison_batch = _batch_report(
        [
            _actual_case(
                label="SEEK search button",
                status="passed",
                roi_point={"x": 92, "y": 48},
                failure_category=None,
                validation_status="valid_candidate",
            )
        ]
    )
    baseline_path = tmp_path / "vista" / "batch.json"
    comparison_path = tmp_path / "uground" / "batch.json"
    baseline_path.parent.mkdir()
    comparison_path.parent.mkdir()
    baseline_path.write_text(json.dumps(baseline_batch, ensure_ascii=False), encoding="utf-8")
    comparison_path.write_text(json.dumps(comparison_batch, ensure_ascii=False), encoding="utf-8")
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(
        json.dumps(
            {
                "matrix_summary": {
                    "rows": [
                        {
                            "model_profile_id": "vista",
                            "batch_report_path": str(baseline_path),
                        },
                        {
                            "model_profile_id": "uground",
                            "batch_report_path": str(comparison_path),
                        },
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_grounding_case_diagnosis_report(
        matrix_report_path=matrix_path,
        baseline_profile="vista",
        comparison_profile="uground",
        out_dir=tmp_path / "diagnosis",
    )

    assert report["diagnostic_case_count"] == 1
    assert report["failure_category_breakdown"] == {"model_point_outside_roi_candidate_bbox": 1}
    assert report["comparison_outcome_breakdown"] == {"comparison_passed_same_case": 1}
    case = report["diagnostic_cases"][0]
    assert case["diagnostic_case_id"] == "recorded_parser_seek_search_header_controls::SEEK search button"
    assert case["baseline"]["roi_candidate_bbox"] == {"x": 46, "y": 24, "w": 92, "h": 48}
    assert case["baseline"]["screen_bbox"] == {"x": 1820, "y": 184, "w": 92, "h": 48}
    assert case["comparison"]["point_quality_status"] == "passed_inside_expected_bbox"
    assert case["diagnosis"]["failed_layer"] == "model_point_quality"
    assert case["diagnosis"]["root_cause"] == "model_returned_point_outside_candidate_bbox_with_valid_roi_and_transform"
    assert case["diagnosis"]["baseline_gate_safety"] == "passed_rejected_no_action"
    assert case["diagnosis"]["comparison_outcome"] == "comparison_passed_same_case"
    assert "not 90% accuracy" in report["interpretation"]
    assert report["safety_boundary"]["real_clicks_performed"] == 0
    assert report["safety_boundary"]["execute_binding_enabled"] is False
    assert Path(report["report_path"]).exists()


def test_grounding_case_diagnosis_requires_valid_profiles(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.json"
    matrix_path.write_text(json.dumps({"matrix_summary": {"rows": []}}, ensure_ascii=False), encoding="utf-8")

    try:
        build_grounding_case_diagnosis_report(
            matrix_report_path=matrix_path,
            baseline_profile="missing",
            out_dir=tmp_path / "diagnosis",
        )
    except ValueError as exc:
        assert "baseline profile not found" in str(exc)
    else:
        raise AssertionError("expected missing baseline profile to raise ValueError")


def _batch_report(cases: list[dict]) -> dict:
    return {
        "contract_version": "learn_actual_grounding_smoke_batch_report_v1",
        "case_reports": cases,
    }


def _actual_case(
    *,
    label: str,
    status: str,
    roi_point: dict[str, int],
    failure_category: str | None,
    validation_status: str,
) -> dict:
    validation_failure = "point_outside_bbox" if validation_status == "rejected" else None
    point_quality_status = "failed_outside_expected_bbox" if status == "failed" else "passed_inside_expected_bbox"
    return {
        "status": status,
        "source_type": "actual_grounding_call",
        "actual_model_call_in_this_run": True,
        "case_id": "recorded_parser_seek_search_header_controls",
        "label": label,
        "screenshot_path": "screen.png",
        "roi_image_path": "roi.png",
        "actual_grounding_output_path": "actual_grounding_output_v1.json",
        "raw_model_output": "[36, 24]",
        "normalized_grounding": {
            "coordinate_space": "roi_local_point",
            "raw_output": [roi_point["x"], roi_point["y"]],
        },
        "grounding_request": {
            "target": {
                "candidate_bbox": {"x": 1820, "y": 184, "w": 92, "h": 48},
                "candidate_bbox_in_roi": {"x": 46, "y": 24, "w": 92, "h": 48},
            },
            "roi_crop": {
                "coordinate_transform": {
                    "contract_version": "coordinate_transform_v1",
                    "roi_bbox": {"x": 1774, "y": 160, "w": 184, "h": 96},
                    "crop_size": {"width": 184, "height": 96},
                    "scale_x": 1.0,
                    "scale_y": 1.0,
                }
            },
        },
        "validation": {
            "status": validation_status,
            "failure_category": validation_failure,
            "checks": {
                "point_inside_bbox": status == "passed",
                "bbox_inside_image": True,
                "ocr_anchor_overlap": True,
                "uia_or_dom_or_parser_overlap": True,
                "coordinate_transform_replay": True,
                "screenshot_freshness": True,
                "not_non_actionable_content": True,
                "not_danger_zone": True,
            },
        },
        "point_quality": {
            "status": point_quality_status,
            "failure_category": failure_category,
            "roi_point": roi_point,
            "roi_point_source": "restored_local_point",
            "roi_candidate_bbox": {"x": 46, "y": 24, "w": 92, "h": 48},
            "screen_point": {"x": 1810, "y": 184},
            "screen_bbox": {"x": 1820, "y": 184, "w": 92, "h": 48},
            "error": {"distance_to_bbox": 10.0 if status == "failed" else 0.0},
        },
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks_performed": 0,
            "final_submit_forbidden": True,
        },
        "batch_case": {
            "surface": "seek_results_header",
            "expected_case_outcome": "actual_grounding_call",
            "interpretation": "metadata only",
        },
    }
