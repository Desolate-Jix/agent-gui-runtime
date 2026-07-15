from __future__ import annotations

from pathlib import Path

from scripts.run_learning_interface_chain_smoke import (
    _observation_evidence,
    _two_stage_stage1_overlay_path,
    _two_stage_review_box_count,
    build_learn_calibration_metadata,
    build_manifest_cases,
    build_post_calibration_three_image_audit,
    build_three_image_audit,
    build_protected_cases,
    audit_stage1_geometry,
    classify_chain_completion,
    classify_case_quality,
    evaluate_class_expectations,
    evaluate_saved_class_expectations,
    summarize_class_expectation_audits,
)


def test_build_manifest_cases_uses_current_valid_recursive_surfaces() -> None:
    cases = build_manifest_cases(Path("artifacts/benchmarks/interface_class_recursive_manifest_v1.json"))

    assert len(cases) == 9
    assert all(Path(case.trace_path).exists() for case in cases)
    assert all(Path(case.source_image_path).exists() for case in cases)
    assert all(case.trace_sha256 for case in cases)
    assert all(case.source_image_sha256 for case in cases)
    assert all(case.expectations.get("expected_interface_category") for case in cases)
    assert not any("qq" in case.case_id.lower() for case in cases)
    assert not any("calculator" in case.case_id.lower() for case in cases)
    assert any(case.case_id == "conversation_workspace_whatsapp_20260715" for case in cases)


def test_class_expectation_audit_scores_strategy_structure_roles_and_contamination() -> None:
    expectations = {
        "expected_interface_category": "settings_dashboard",
        "expected_class_strategy": "independent_control_cards",
        "min_structure_regions": 2,
        "required_structure_types": ["top_bar", "main_content"],
        "min_hierarchy_nodes": 5,
        "required_group_roles": {"tile_card_parent": 2},
        "forbidden_group_roles": ["media_card_group"],
        "forbidden_item_roles": ["recommendation_item"],
        "forbidden_label_tokens": ["apple music"],
    }
    report = {
        "interface_classification": {"category": "settings_dashboard"},
        "class_rule_profile": {"primary_content_strategy": "independent_control_cards"},
        "ui_hierarchy": {
            "nodes": [
                {"level": "screen", "component_type": "screen", "label": "Settings"},
                {"level": "structure_region", "component_type": "top_bar", "label": "Header"},
                {"level": "structure_region", "component_type": "main_content", "label": "Settings grid"},
                {"level": "component_group", "component_type": "tile_card_parent", "label": "System"},
                {"level": "component_group", "component_type": "tile_card_parent", "label": "Devices"},
            ]
        },
    }

    passed = evaluate_class_expectations(report, expectations)
    assert passed["status"] == "passed"
    assert passed["issues"] == []
    assert passed["actual"]["group_role_counts"]["tile_card_parent"] == 2

    contaminated = {
        **report,
        "interface_classification": {"category": "media_catalog"},
        "ui_hierarchy": {
            "nodes": [
                *report["ui_hierarchy"]["nodes"],
                {"level": "component_group", "component_type": "media_card_group", "label": "Apple Music"},
            ]
        },
    }
    failed = evaluate_class_expectations(contaminated, expectations)
    assert failed["status"] == "needs_review"
    assert "interface_category_mismatch" in failed["issues"]
    assert "forbidden_group_role_present:media_card_group" in failed["issues"]
    assert "forbidden_label_token_present:apple music" in failed["issues"]


def test_class_expectation_needs_review_blocks_quality_and_chain_completion() -> None:
    class_audit = {
        "status": "needs_review",
        "issues": ["missing_structure_type:top_bar"],
    }
    summary = {
        "case_id": "file_browser_system_drive",
        "two_stage": {"success": True, "stage1_gate_status": "passed", "stage2_numbering_skipped": False},
        "stage1_geometry_audit": {"status": "passed"},
        "class_expectation_audit": class_audit,
        "deep_calibration": {"success": True, "calibration_target_count": 25},
        "three_image_audit": {"complete": True, "final_fusion_verified": True},
        "trial": {
            "success": True,
            "draft_section_counts": {"regions": 25},
            "two_stage_review_region_count": 25,
        },
        "page_detail": {"success": True, "region_count": 25},
        "scaffold": {
            "success": True,
            "page_detail_readonly_pathgraph_preview_status": "page_detail_readonly_preview_ready",
        },
    }

    quality = classify_case_quality(summary)
    completion = classify_chain_completion(summary)

    assert quality["status"] == "needs_review"
    assert "class_expectation_needs_review" in quality["issues"]
    assert completion["success"] is False
    assert "class_expectation_needs_review" in completion["issues"]


def test_class_expectation_summary_keeps_pass_review_and_not_covered_separate() -> None:
    summary = summarize_class_expectation_audits(
        [
            {"class_expectation_audit": {"status": "passed"}},
            {"class_expectation_audit": {"status": "needs_review"}},
            {"class_expectation_audit": {"status": "not_covered"}},
        ]
    )

    assert summary == {
        "passed": 1,
        "needs_review": 1,
        "not_covered": 1,
        "interpretation": "Class-rule conformance counts only; not recognition accuracy evidence.",
    }


def test_saved_class_expectation_audit_reads_full_report_not_trimmed_api_response(tmp_path: Path) -> None:
    report_path = tmp_path / "trial_result.json"
    report_path.write_text(
        """
{
  "interface_classification": {"category": "file_browser"},
  "class_rule_profile": {"primary_content_strategy": "row_table_first"},
  "ui_hierarchy": {
    "nodes": [
      {"level": "structure_region", "component_type": "top_bar", "label": "Ribbon"},
      {"level": "structure_region", "component_type": "left_sidebar", "label": "Navigation"},
      {"level": "structure_region", "component_type": "main_content", "label": "Files"}
    ]
  }
}
""".strip(),
        encoding="utf-8",
    )

    audit = evaluate_saved_class_expectations(
        {"report_path": str(report_path)},
        {
            "expected_interface_category": "file_browser",
            "expected_class_strategy": "row_table_first",
            "min_structure_regions": 3,
            "required_structure_types": ["top_bar", "left_sidebar", "main_content"],
        },
    )

    assert audit["status"] == "passed"
    assert audit["evidence_source"] == "saved_two_stage_report"
    assert audit["report_path"] == str(report_path)


def test_three_image_audit_requires_source_stage1_and_final_paths(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    stage1 = tmp_path / "stage1.png"
    final = tmp_path / "final.png"
    for path in (source, stage1, final):
        path.write_bytes(b"png-evidence")

    audit = build_three_image_audit(
        source_path=str(source),
        stage1_path=str(stage1),
        final_path=str(final),
    )

    assert audit["complete"] is True
    assert audit["source"]["path"] == str(source)
    assert audit["stage1_bar_localization"]["path"] == str(stage1)
    assert audit["final_fused_overlay"]["path"] == str(final)
    assert len(audit["source"]["sha256"]) == 64


def test_post_calibration_three_image_audit_requires_verified_final_fusion(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    stage1 = tmp_path / "stage1.png"
    stage2 = tmp_path / "stage2.png"
    final = tmp_path / "final.png"
    for path in (source, stage1, stage2, final):
        path.write_bytes(b"png-evidence")

    audit = build_post_calibration_three_image_audit(
        source_path=str(source),
        stage1_path=str(stage1),
        stage2_path=str(stage2),
        deep_calibration={
            "success": True,
            "overlay_path": str(final),
            "final_fusion_overlay": True,
            "base_visual_source": "two_stage_numbered_overlay",
        },
    )

    assert audit["complete"] is True
    assert audit["final_fused_overlay"]["path"] == str(final)
    assert audit["final_fused_overlay"]["path"] != str(stage2)

    invalid = build_post_calibration_three_image_audit(
        source_path=str(source),
        stage1_path=str(stage1),
        stage2_path=str(stage2),
        deep_calibration={
            "success": True,
            "overlay_path": str(final),
            "final_fusion_overlay": False,
            "base_visual_source": "source_screenshot",
        },
    )

    assert invalid["complete"] is False
    assert invalid["final_fused_overlay"]["path"] == ""
    assert invalid["stage2_numbered_overlay"]["path"] == str(stage2)


def test_stage1_geometry_audit_rejects_unsupported_topbar_extent(tmp_path: Path) -> None:
    report_path = tmp_path / "trial_result.json"
    report_path.write_text(
        """
{
  "stage1_structure": {
    "structure_regions": [
      {"region_id": "structure_region_page_header", "zone_id": "page_header", "bbox": {"x": 10, "y": 8, "w": 980, "h": 50}}
    ]
  },
  "stage1_region_localization": {
    "regions": [
      {"region_id": "structure_region_top_bar", "zone_id": "top_bar", "bbox": {"x": 0, "y": 0, "w": 1000, "h": 180}},
      {"region_id": "structure_region_primary_area", "zone_id": "primary_area", "bbox": {"x": 0, "y": 180, "w": 1000, "h": 620}}
    ]
  }
}
""".strip(),
        encoding="utf-8",
    )

    audit = audit_stage1_geometry(str(report_path))

    assert audit["status"] == "needs_review"
    assert audit["issues"] == ["top_bar_extent_not_supported_by_page_header_evidence"]
    assert audit["top_bar_bottom"] == 180
    assert audit["page_header_evidence_bottom"] == 58


def test_stage1_geometry_audit_accepts_adjacent_evidence_boundaries(tmp_path: Path) -> None:
    report_path = tmp_path / "trial_result.json"
    report_path.write_text(
        """
{
  "stage1_structure": {
    "structure_regions": [
      {"region_id": "structure_region_page_header", "zone_id": "page_header", "bbox": {"x": 10, "y": 8, "w": 980, "h": 50}}
    ]
  },
  "stage1_region_localization": {
    "regions": [
      {"region_id": "structure_region_top_bar", "zone_id": "top_bar", "bbox": {"x": 0, "y": 0, "w": 1000, "h": 68}},
      {"region_id": "structure_region_primary_area", "zone_id": "primary_area", "bbox": {"x": 0, "y": 68, "w": 1000, "h": 732}}
    ]
  }
}
""".strip(),
        encoding="utf-8",
    )

    audit = audit_stage1_geometry(str(report_path))

    assert audit["status"] == "passed"
    assert audit["issues"] == []


def test_build_protected_cases_uses_three_surfaces_and_python_override() -> None:
    cases = build_protected_cases(Path("logs/benchmarks/learn_three_surface_regression_20260710_v5"))

    assert [case.case_id for case in cases] == ["applemusic", "qq", "python_org"]
    assert all(case.trace_path for case in cases)
    assert all(case.source_image_path for case in cases)
    python_case = next(case for case in cases if case.case_id == "python_org")
    assert "locate-target__python-org" in python_case.source_image_path


def test_chain_smoke_uses_the_same_full_numbered_calibration_contract_as_panel() -> None:
    metadata = build_learn_calibration_metadata("artifacts/learning-runs/apple/report.json")

    assert metadata["learn_all_targets"] is True
    assert metadata["two_stage_report_path"] == "artifacts/learning-runs/apple/report.json"
    assert metadata["learn_vista_coordinate_validation"] == {
        "enabled": True,
        "max_targets": "all",
        "stop_on_failure": False,
        "use_numbered_overlay": True,
    }


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

    calibrated_without_legacy_review_boxes = classify_case_quality(
        {
            "case_id": "apple_music",
            "two_stage": {"stage2_numbering_skipped": False},
            "deep_calibration": {"review_box_count": 0, "calibration_target_count": 37},
            "trial": {"draft_section_counts": {"regions": 32}, "two_stage_review_region_count": 40},
            "page_detail": {"region_count": 48},
            "scaffold": {"page_detail_readonly_pathgraph_preview_status": "page_detail_readonly_preview_ready"},
        }
    )
    assert calibrated_without_legacy_review_boxes["status"] == "review_only_chain_ready"
    assert "missing_deep_review_boxes" not in calibrated_without_legacy_review_boxes["issues"]


def test_classify_case_quality_rejects_blocked_stage1_or_skipped_stage2() -> None:
    blocked = classify_case_quality(
        {
            "case_id": "steam_friends",
            "two_stage": {
                "stage1_gate_status": "blocked_before_stage2_numbering",
                "stage2_numbering_skipped": True,
            },
            "deep_calibration": {"review_box_count": 3, "calibration_target_count": 3},
            "trial": {"draft_section_counts": {"regions": 3}, "two_stage_review_region_count": 3},
            "page_detail": {"region_count": 3},
            "scaffold": {"page_detail_readonly_pathgraph_preview_status": "page_detail_readonly_preview_ready"},
        }
    )

    assert blocked["status"] == "needs_review"
    assert "stage1_gate_not_passed" in blocked["issues"]
    assert "stage2_numbering_skipped" in blocked["issues"]

    geometry_mismatch = classify_case_quality(
        {
            "case_id": "generic_sparse_editor",
            "two_stage": {"stage1_gate_status": "passed", "stage2_numbering_skipped": False},
            "stage1_geometry_audit": {
                "status": "needs_review",
                "issues": ["top_bar_extent_not_supported_by_page_header_evidence"],
            },
            "deep_calibration": {"calibration_target_count": 3},
            "trial": {"draft_section_counts": {"regions": 3}, "two_stage_review_region_count": 3},
            "page_detail": {"region_count": 3},
            "scaffold": {"page_detail_readonly_pathgraph_preview_status": "page_detail_readonly_preview_ready"},
        }
    )
    assert geometry_mismatch["status"] == "needs_review"
    assert "stage1_geometry_needs_review" in geometry_mismatch["issues"]


def test_chain_completion_requires_stage1_gate_and_stage2_numbering() -> None:
    blocked = classify_chain_completion(
        {
            "two_stage": {
                "success": True,
                "stage1_gate_status": "blocked_before_stage2_numbering",
                "stage2_numbering_skipped": True,
            },
            "deep_calibration": {"success": True},
            "trial": {"success": True},
            "page_detail": {"success": True},
            "scaffold": {"success": True},
        }
    )

    assert blocked["transport_success"] is True
    assert blocked["success"] is False
    assert blocked["issues"] == [
        "stage1_gate_not_passed",
        "stage2_numbering_skipped",
        "three_image_audit_incomplete",
        "final_fusion_not_verified",
    ]

    complete = classify_chain_completion(
        {
            "two_stage": {"success": True, "stage1_gate_status": "passed", "stage2_numbering_skipped": False},
            "deep_calibration": {"success": True},
            "three_image_audit": {"complete": True, "final_fusion_verified": True},
            "trial": {"success": True},
            "page_detail": {"success": True},
            "scaffold": {"success": True},
        }
    )
    assert complete["transport_success"] is True
    assert complete["success"] is True
    assert complete["issues"] == []

    geometry_blocked = classify_chain_completion(
        {
            "two_stage": {"success": True, "stage1_gate_status": "passed", "stage2_numbering_skipped": False},
            "stage1_geometry_audit": {"status": "needs_review"},
            "deep_calibration": {"success": True},
            "three_image_audit": {"complete": True, "final_fusion_verified": True},
            "trial": {"success": True},
            "page_detail": {"success": True},
            "scaffold": {"success": True},
        }
    )
    assert geometry_blocked["success"] is False
    assert geometry_blocked["issues"] == ["stage1_geometry_needs_review"]

    missing_final_fusion = classify_chain_completion(
        {
            "two_stage": {"success": True, "stage1_gate_status": "passed", "stage2_numbering_skipped": False},
            "deep_calibration": {"success": True},
            "three_image_audit": {"complete": False, "final_fusion_verified": False},
            "trial": {"success": True},
            "page_detail": {"success": True},
            "scaffold": {"success": True},
        }
    )
    assert missing_final_fusion["transport_success"] is True
    assert missing_final_fusion["success"] is False
    assert missing_final_fusion["issues"] == ["three_image_audit_incomplete", "final_fusion_not_verified"]


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

    recursive_case = classify_case_quality(
        {
            "case_id": "documentation_portal_python_home",
            "two_stage": {"stage1_gate_status": "passed", "stage2_numbering_skipped": False},
            "deep_calibration": {"calibration_target_count": 20},
            "trial": {"draft_section_counts": {"regions": 20}, "two_stage_review_region_count": 20},
            "page_detail": {"region_count": 20},
            "scaffold": {"page_detail_readonly_pathgraph_preview_status": "page_detail_readonly_preview_ready"},
            "three_image_audit": {"complete": True},
        }
    )
    assert recursive_case["status"] == "stress_only_needs_review"
    assert "python_org_stress_sample" in recursive_case["issues"]


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


def test_stage1_overlay_path_reads_same_saved_two_stage_report(tmp_path: Path) -> None:
    report_path = tmp_path / "artifacts" / "learning-runs" / "case" / "trial_result.json"
    stage1_path = tmp_path / "artifacts" / "review-overlays" / "case-stage1.png"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    stage1_path.parent.mkdir(parents=True, exist_ok=True)
    stage1_path.write_bytes(b"stage1")
    report_path.write_text(
        """
{
  "stage1_region_localization": {
    "overlay_path": "artifacts/review-overlays/case-stage1.png"
  },
  "fusion": {
    "stage1_structure_overlay_path": "artifacts/review-overlays/wrong.png"
  }
}
""".strip(),
        encoding="utf-8",
    )

    assert _two_stage_stage1_overlay_path({"report_path": str(report_path)}, project_root=tmp_path) == str(stage1_path)


def test_observation_evidence_preserves_stage2_calibration_targets_for_draft_fusion() -> None:
    calibration_target = {
        "candidate_id": "stage2:main:search",
        "label": "Search",
        "role": "input",
        "bbox": {"x": 10, "y": 20, "w": 200, "h": 32},
        "click_point": {"x": 110, "y": 36},
        "coordinate_validation": {"status": "valid", "click_point_inside_bbox": True},
        "calibration_only": True,
    }

    evidence = _observation_evidence(
        observe_result={"image_size": {"width": 800, "height": 600}},
        image_path="artifacts/screenshots/example.png",
        locate_result={},
        learn_targets={
            "status": "ready",
            "target_count": 0,
            "targets": [],
            "calibration_target_count": 1,
            "calibration_targets": [calibration_target],
            "review_boxes": [],
            "vista_coordinate_validation": {"validated_count": 1},
        },
    )

    assert evidence["calibrated_targets"] == [calibration_target]
    assert evidence["learn_all_targets_summary"]["calibration_target_count"] == 1
    assert evidence["learn_all_targets_summary"]["coordinate_calibration_status"] == "model_validation_completed"
