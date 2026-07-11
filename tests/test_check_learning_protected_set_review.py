import json
from pathlib import Path

from PIL import Image

from scripts.check_learning_protected_set_review import (
    check_learning_protected_case,
    compare_learning_protected_archive_node,
    run_learning_protected_set_review,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_protected_case_accepts_review_scaffold_with_overlay_and_refs(tmp_path: Path) -> None:
    overlay = tmp_path / "artifacts" / "review-overlays" / "demo.png"
    overlay.parent.mkdir(parents=True)
    Image.new("RGB", (12, 10), "white").save(overlay)
    page_detail = tmp_path / "artifacts" / "learning-runs" / "demo" / "learn_page_detail_candidate.json"
    _write_json(
        page_detail,
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "summary": {"title": "Demo"},
            "compiled_overlay_path": str(overlay.relative_to(tmp_path)).replace("\\", "/"),
            "full_screen_understanding_overlay_path": str(overlay.relative_to(tmp_path)).replace("\\", "/"),
            "layout": {
                "sections": [{"section_id": "main", "label": "Main"}],
                "regions": [{"region_id": "card", "label": "Card", "source_section_id": "main"}],
            },
        },
    )
    scaffold = _write_json(
        tmp_path / "artifacts" / "learning-runs" / "demo" / "learn_mode_demo_scaffold.json",
        {
            "contract_version": "learn_mode_demo_scaffold_v1",
            "source_path": str(page_detail.relative_to(tmp_path)).replace("\\", "/"),
            "page_detail_candidate": json.loads(page_detail.read_text(encoding="utf-8")),
        },
    )

    result = check_learning_protected_case(
        {"case_id": "demo", "source_path": scaffold.relative_to(tmp_path)},
        root=tmp_path,
    )

    assert result["passed"] is True
    assert result["display_summary"]["region_count"] == 1
    assert result["display_summary"]["action_template_count"] == 1
    assert result["display_summary"]["states_with_refs_count"] == 1
    assert result["checks"]["uses_review_overlay"] is True


def test_protected_case_records_source_override_without_model_accuracy_claim(tmp_path: Path) -> None:
    overlay = tmp_path / "artifacts" / "review-overlays" / "python.png"
    overlay.parent.mkdir(parents=True)
    Image.new("RGB", (12, 10), "white").save(overlay)
    run_dir = tmp_path / "artifacts" / "learning-runs" / "python"
    page_detail = _write_json(
        run_dir / "learn_page_detail_candidate.json",
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "compiled_overlay_path": str(overlay.relative_to(tmp_path)).replace("\\", "/"),
            "full_screen_understanding_overlay_path": str(overlay.relative_to(tmp_path)).replace("\\", "/"),
            "layout": {
                "sections": [{"section_id": "main"}],
                "regions": [{"region_id": "search", "source_section_id": "main"}],
            },
        },
    )
    scaffold = _write_json(
        run_dir / "learn_mode_demo_scaffold.json",
        {
            "contract_version": "learn_mode_demo_scaffold_v1",
            "source_path": str(page_detail.relative_to(tmp_path)).replace("\\", "/"),
            "page_detail_candidate": json.loads(page_detail.read_text(encoding="utf-8")),
        },
    )
    _write_json(
        run_dir / "trial_result.json",
        {
            "source_image_override": {
                "status": "applied",
                "applied": True,
                "reason": "explicit_source_image_override",
                "original_path": "missing.png",
                "path": "artifacts/screenshots/python.png",
            },
            "model_grounding_evidence": {
                "status": "not_valid_for_model_grounding_evidence",
                "model_grounding_attempted_count": 0,
                "model_call_plan_is_recommendation_only": True,
            },
        },
    )

    result = check_learning_protected_case(
        {
            "case_id": "python",
            "source_path": scaffold.relative_to(tmp_path),
            "expect_source_image_override": True,
        },
        root=tmp_path,
    )

    assert result["passed"] is True
    assert result["source_image_override"]["applied"] is True
    assert result["checks"]["source_override_expectation_met"] is True
    assert result["model_grounding_evidence"]["model_accuracy_claim_allowed"] is False
    assert "not model accuracy evidence" in result["model_grounding_evidence"]["interpretation"]


def test_protected_set_summary_reports_failures(tmp_path: Path) -> None:
    report = run_learning_protected_set_review(
        [{"case_id": "missing", "source_path": "artifacts/missing.json"}],
        root=tmp_path,
    )

    assert report["summary"]["attempted"] == 1
    assert report["summary"]["passed"] == 0
    assert report["summary"]["failed"] == 1
    assert report["cases"][0]["errors"] == ["source_missing"]


def test_protected_set_checkpoint_archives_case_nodes_and_safety_boundary(tmp_path: Path) -> None:
    overlay = tmp_path / "artifacts" / "review-overlays" / "demo.png"
    overlay.parent.mkdir(parents=True)
    Image.new("RGB", (12, 10), "white").save(overlay)
    page_detail = tmp_path / "artifacts" / "learning-runs" / "demo" / "learn_page_detail_candidate.json"
    _write_json(
        page_detail,
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "compiled_overlay_path": str(overlay.relative_to(tmp_path)).replace("\\", "/"),
            "full_screen_understanding_overlay_path": str(overlay.relative_to(tmp_path)).replace("\\", "/"),
            "layout": {
                "sections": [{"section_id": "main"}],
                "regions": [{"region_id": "card", "source_section_id": "main"}],
            },
        },
    )
    scaffold = _write_json(
        tmp_path / "artifacts" / "learning-runs" / "demo" / "learn_mode_demo_scaffold.json",
        {
            "contract_version": "learn_mode_demo_scaffold_v1",
            "source_path": str(page_detail.relative_to(tmp_path)).replace("\\", "/"),
            "page_detail_candidate": json.loads(page_detail.read_text(encoding="utf-8")),
        },
    )

    report = run_learning_protected_set_review(
        [{"case_id": "demo", "source_path": scaffold.relative_to(tmp_path)}],
        root=tmp_path,
        checkpoint_id="demo_checkpoint",
    )

    archive = report["archive_node"]
    assert archive["contract_version"] == "learning_protected_archive_node_v1"
    assert archive["checkpoint_id"] == "demo_checkpoint"
    assert archive["status"] == "pass"
    assert archive["cases"][0]["case_id"] == "demo"
    assert archive["cases"][0]["region_count"] == 1
    assert "check_learning_protected_set_review.py" in archive["anti_pollution_policy"]["before_new_interface"]
    assert archive["safety_boundary"]["execute_binding_enabled"] is False
    assert archive["safety_boundary"]["live_clicks"] == 0
    assert "not model accuracy" in archive["interpretation"]


def test_protected_set_checkpoint_archives_structure_quality(tmp_path: Path) -> None:
    overlay = tmp_path / "artifacts" / "review-overlays" / "demo.png"
    overlay.parent.mkdir(parents=True)
    Image.new("RGB", (12, 10), "white").save(overlay)
    run_dir = tmp_path / "artifacts" / "learning-runs" / "demo"
    page_detail = _write_json(
        run_dir / "learn_page_detail_candidate.json",
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "compiled_overlay_path": str(overlay.relative_to(tmp_path)).replace("\\", "/"),
            "full_screen_understanding_overlay_path": str(overlay.relative_to(tmp_path)).replace("\\", "/"),
            "layout": {
                "sections": [{"section_id": "main"}],
                "regions": [{"region_id": "card", "source_section_id": "main"}],
            },
        },
    )
    scaffold = _write_json(
        run_dir / "learn_mode_demo_scaffold.json",
        {
            "contract_version": "learn_mode_demo_scaffold_v1",
            "source_path": str(page_detail.relative_to(tmp_path)).replace("\\", "/"),
            "page_detail_candidate": json.loads(page_detail.read_text(encoding="utf-8")),
        },
    )
    _write_json(
        run_dir / "trial_result.json",
        {
            "stage1_gate": {"status": "passed", "audit": {"screen_size": {"width": 100, "height": 100}}},
            "stage1_region_localization": {"regions": [{"bbox": {"x": 0, "y": 0, "w": 100, "h": 100}}]},
            "stage2_numbering": {"region_count": 1, "numbered_item_count": 2},
            "fusion": {
                "fused_review_box_count": 2,
                "region_content_boundary_summary": {
                    "boundary_contract_status": "passed",
                    "missing_parent_child_count": 0,
                    "outside_parent_after_clip_count": 0,
                    "sibling_non_parent_overlap_count": 0,
                },
            },
            "learn_all_targets": {"target_count": 0},
            "model_grounding_evidence": {"model_grounding_attempted_count": 0},
        },
    )

    report = run_learning_protected_set_review(
        [{"case_id": "demo", "source_path": scaffold.relative_to(tmp_path)}],
        root=tmp_path,
        checkpoint_id="demo_checkpoint",
    )

    archived_case = report["archive_node"]["cases"][0]
    assert archived_case["structure_quality_status"] == "display_review_candidate"
    assert archived_case["structure_stage1_near_full_partition_required_ratio"] == 0.98
    assert archived_case["structure_stage2_numbered_item_count"] == 2
    assert archived_case["structure_fused_review_box_count"] == 2
    assert archived_case["structure_runtime_pathgraph_ready"] is False


def test_protected_archive_comparison_passes_for_same_checkpoint(tmp_path: Path) -> None:
    report = _minimal_archive_report("demo", region_count=1)

    comparison = compare_learning_protected_archive_node(report, json.loads(json.dumps(report)))

    assert comparison["status"] == "pass"
    assert comparison["mismatch_count"] == 0
    assert comparison["compared_case_count"] == 1


def test_protected_archive_comparison_fails_on_case_drift(tmp_path: Path) -> None:
    baseline = _minimal_archive_report("demo", region_count=1)
    current = _minimal_archive_report("demo", region_count=2)

    comparison = compare_learning_protected_archive_node(current, baseline)

    assert comparison["status"] == "fail"
    assert comparison["mismatch_count"] == 1
    assert comparison["mismatches"][0]["case_id"] == "demo"
    assert comparison["mismatches"][0]["field"] == "region_count"
    assert comparison["mismatches"][0]["baseline"] == 1
    assert comparison["mismatches"][0]["current"] == 2


def test_protected_archive_comparison_fails_on_structure_quality_drift() -> None:
    baseline = _minimal_archive_report("demo", region_count=1)
    current = _minimal_archive_report("demo", region_count=1)
    baseline["archive_node"]["cases"][0]["structure_quality_status"] = "display_review_candidate"
    current["archive_node"]["cases"][0]["structure_quality_status"] = "stress_only_needs_review"

    comparison = compare_learning_protected_archive_node(current, baseline)

    assert comparison["status"] == "fail"
    assert comparison["mismatches"][0]["field"] == "structure_quality_status"
    assert comparison["mismatches"][0]["baseline"] == "display_review_candidate"
    assert comparison["mismatches"][0]["current"] == "stress_only_needs_review"


def test_protected_archive_comparison_allows_legacy_baseline_without_structure_fields() -> None:
    baseline = _minimal_archive_report("demo", region_count=1)
    current = _minimal_archive_report("demo", region_count=1)
    current["archive_node"]["cases"][0]["structure_quality_status"] = "display_review_candidate"
    current["archive_node"]["cases"][0]["structure_stage1_near_full_partition_required_ratio"] = 0.98

    comparison = compare_learning_protected_archive_node(current, baseline)

    assert comparison["status"] == "pass"
    assert comparison["mismatch_count"] == 0
    assert "structure_quality_status" in comparison["legacy_skipped_optional_fields"]
    assert "structure_stage1_near_full_partition_required_ratio" in comparison["legacy_skipped_optional_fields"]


def _minimal_archive_report(case_id: str, *, region_count: int) -> dict:
    return {
        "contract_version": "learning_protected_set_review_check_v1",
        "summary": {"failed": 0},
        "archive_node": {
            "contract_version": "learning_protected_archive_node_v1",
            "checkpoint_id": "baseline",
            "cases": [
                {
                    "case_id": case_id,
                    "source_path": f"artifacts/{case_id}.json",
                    "compiled_overlay_path": f"artifacts/review-overlays/{case_id}.png",
                    "state_count": 1,
                    "region_count": region_count,
                    "action_template_count": 1,
                    "page_detail_section_count": 1,
                    "passed": True,
                    "model_grounding_status": "not_valid_for_model_grounding_evidence",
                }
            ],
        },
    }
