from __future__ import annotations

from pathlib import Path

from scripts.run_learning_interface_chain_smoke import (
    _two_stage_review_box_count,
    build_protected_cases,
    classify_case_quality,
)


def test_build_protected_cases_uses_three_surfaces_and_python_override() -> None:
    cases = build_protected_cases(Path("logs/benchmarks/learn_three_surface_regression_20260710_v5"))

    assert [case.case_id for case in cases] == ["applemusic", "qq", "python_org"]
    assert all(case.trace_path for case in cases)
    assert all(case.source_image_path for case in cases)
    python_case = next(case for case in cases if case.case_id == "python_org")
    assert "locate-target__python-org" in python_case.source_image_path


def test_classify_case_quality_keeps_review_only_boundaries() -> None:
    good = classify_case_quality(
        {
            "case_id": "applemusic",
            "two_stage": {"stage2_numbering_skipped": False},
            "deep_calibration": {"review_box_count": 12, "target_count": 0},
            "trial": {"draft_section_counts": {"regions": 8}, "two_stage_review_region_count": 8},
            "page_detail": {"region_count": 8},
            "scaffold": {"page_detail_readonly_pathgraph_preview_status": "page_detail_readonly_preview_ready"},
        }
    )
    assert good["status"] == "review_only_chain_ready"
    assert good["runtime_pathgraph_ready"] is False

    weak = classify_case_quality({"deep_calibration": {"review_box_count": 0}, "trial": {}})
    assert weak["status"] == "needs_review"
    assert "missing_deep_review_boxes" in weak["issues"]

    empty_review_inventory = classify_case_quality(
        {
            "case_id": "applemusic",
            "two_stage": {"stage2_numbering_skipped": False},
            "deep_calibration": {"review_box_count": 12, "target_count": 0},
            "trial": {"draft_section_counts": {"regions": 8}, "two_stage_review_region_count": 0},
            "page_detail": {"region_count": 8},
            "scaffold": {"page_detail_readonly_pathgraph_preview_status": "page_detail_readonly_preview_ready"},
        }
    )
    assert empty_review_inventory["status"] == "needs_review"
    assert "missing_two_stage_review_regions" in empty_review_inventory["issues"]


def test_python_org_chain_quality_is_stress_sample_not_ready_candidate() -> None:
    python_summary = classify_case_quality(
        {
            "case_id": "python_org",
            "two_stage": {"stage2_numbering_skipped": False},
            "deep_calibration": {"review_box_count": 69, "target_count": 2, "validated_count": 2},
            "trial": {"draft_section_counts": {"regions": 32}, "two_stage_review_region_count": 32},
            "page_detail": {"region_count": 32},
            "scaffold": {"page_detail_readonly_pathgraph_preview_status": "page_detail_readonly_preview_ready"},
        }
    )

    assert python_summary["status"] == "stress_only_needs_review"
    assert "python_org_stress_sample" in python_summary["issues"]
    assert python_summary["runtime_pathgraph_ready"] is False


def test_two_stage_review_box_count_reads_saved_report_when_response_omits_fusion(tmp_path: Path) -> None:
    report_path = tmp_path / "artifacts" / "learning-runs" / "case" / "trial_result.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        """
{
  "fusion": {
    "fused_review_boxes": [
      {"region_id": "a"},
      {"region_id": "b"},
      {"region_id": "c"}
    ]
  }
}
""".strip(),
        encoding="utf-8",
    )

    assert _two_stage_review_box_count({"report_path": str(report_path)}) == 3
    assert _two_stage_review_box_count({"fusion_status": {"summary": {"fused_review_box_count": 5}}}) == 5
