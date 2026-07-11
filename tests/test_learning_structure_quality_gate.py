import json
from pathlib import Path

from scripts.check_learning_structure_quality import (
    check_learning_structure_quality_case,
    run_learning_structure_quality_check,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _trial_payload(*, boundary_status: str = "passed", sibling_overlap: int = 0, target_count: int = 0) -> dict:
    return {
        "contract_version": "learn_two_stage_screen_understanding_v1",
        "stage1_gate": {
            "status": "passed",
            "audit": {"screen_size": {"width": 1000, "height": 800}},
        },
        "stage1_region_localization": {
            "regions": [
                {"region_id": "top", "bbox": {"x": 0, "y": 0, "w": 1000, "h": 100}},
                {"region_id": "main", "bbox": {"x": 0, "y": 100, "w": 1000, "h": 700}},
            ]
        },
        "stage2_numbering": {
            "region_count": 2,
            "numbered_item_count": 12,
            "regions": [
                {"region_id": "top", "bbox": {"x": 0, "y": 0, "w": 1000, "h": 100}},
                {"region_id": "main", "bbox": {"x": 0, "y": 100, "w": 1000, "h": 700}},
            ],
        },
        "fusion": {
            "fused_review_box_count": 14,
            "region_content_boundary_summary": {
                "boundary_contract_status": boundary_status,
                "missing_parent_child_count": 0,
                "clipped_fused_child_count": 0,
                "outside_parent_after_clip_count": 0,
                "sibling_non_parent_overlap_count": sibling_overlap,
                "pathgraph_promotion_allowed": boundary_status == "passed",
                "promotion_blockers": ["sibling_non_parent_overlap_count"] if sibling_overlap else [],
            },
        },
        "learn_all_targets": {
            "target_count": target_count,
            "review_box_count": 14,
        },
        "model_grounding_evidence": {
            "status": "not_valid_for_model_grounding_evidence",
            "model_grounding_attempted_count": 0,
        },
    }


def test_structure_quality_marks_clean_display_candidate_but_not_runtime_ready(tmp_path: Path) -> None:
    source = _write_json(tmp_path / "case" / "trial_result.json", _trial_payload())

    result = check_learning_structure_quality_case(
        {"case_id": "clean", "trial_result_path": source.relative_to(tmp_path)},
        root=tmp_path,
    )

    assert result["passed"] is True
    assert result["quality_status"] == "display_review_candidate"
    assert result["runtime_pathgraph_ready"] is False
    assert result["checks"]["boundary_contract_passed"] is True
    assert result["interpretation"].startswith("display/review structure quality")


def test_structure_quality_sends_sibling_overlap_to_stress_only(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "case" / "trial_result.json",
        _trial_payload(boundary_status="needs_human_review", sibling_overlap=3),
    )

    result = check_learning_structure_quality_case(
        {"case_id": "python_like", "trial_result_path": source.relative_to(tmp_path)},
        root=tmp_path,
    )

    assert result["passed"] is False
    assert result["quality_status"] == "stress_only_needs_review"
    assert "boundary_contract_passed" in result["failed_checks"]
    assert result["structure_metrics"]["sibling_non_parent_overlap_count"] == 3


def test_structure_quality_detects_low_stage1_coverage(tmp_path: Path) -> None:
    payload = _trial_payload()
    payload["stage1_region_localization"]["regions"] = [
        {"region_id": "tiny", "bbox": {"x": 0, "y": 0, "w": 100, "h": 100}}
    ]
    source = _write_json(tmp_path / "case" / "trial_result.json", payload)

    result = check_learning_structure_quality_case(
        {"case_id": "bad_stage1", "trial_result_path": source.relative_to(tmp_path)},
        root=tmp_path,
    )

    assert result["passed"] is False
    assert result["quality_status"] == "blocked_structure_repair"
    assert "stage1_screen_coverage_minimum" in result["failed_checks"]


def test_structure_quality_requires_near_full_stage1_partition(tmp_path: Path) -> None:
    payload = _trial_payload()
    payload["stage1_region_localization"]["regions"] = [
        {"region_id": "top", "bbox": {"x": 0, "y": 0, "w": 1000, "h": 100}},
        {"region_id": "main", "bbox": {"x": 0, "y": 100, "w": 1000, "h": 540}},
    ]
    source = _write_json(tmp_path / "case" / "trial_result.json", payload)

    result = check_learning_structure_quality_case(
        {"case_id": "stage1_gap", "trial_result_path": source.relative_to(tmp_path)},
        root=tmp_path,
    )

    assert result["passed"] is False
    assert result["quality_status"] == "blocked_structure_repair"
    assert result["structure_metrics"]["stage1_screen_coverage_ratio"] == 0.8
    assert "stage1_partition_near_full_coverage" in result["failed_checks"]


def test_structure_quality_summary_counts_statuses(tmp_path: Path) -> None:
    clean = _write_json(tmp_path / "clean.json", _trial_payload())
    stress = _write_json(
        tmp_path / "stress.json",
        _trial_payload(boundary_status="needs_human_review", sibling_overlap=1),
    )

    report = run_learning_structure_quality_check(
        [
            {"case_id": "clean", "trial_result_path": clean.relative_to(tmp_path)},
            {"case_id": "stress", "trial_result_path": stress.relative_to(tmp_path)},
        ],
        root=tmp_path,
    )

    assert report["summary"]["attempted"] == 2
    assert report["summary"]["display_review_candidate"] == 1
    assert report["summary"]["stress_only_needs_review"] == 1
    assert report["summary"]["runtime_pathgraph_ready"] == 0
    assert report["safety_boundary"]["live_clicks"] == 0
