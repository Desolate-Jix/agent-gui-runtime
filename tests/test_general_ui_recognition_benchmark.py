from __future__ import annotations

import hashlib
import json

import scripts.run_general_ui_recognition_benchmark as benchmark_module
from PIL import Image
from scripts.run_general_ui_recognition_benchmark import (
    _evaluate_ownership_golden,
    _fixture_error,
    _load_ownership_golden_manifest,
    _runner_safety_audit,
    _summarize_ownership_golden,
    _write_case_review_sheet,
    evaluate_case_report,
    run_benchmark,
    summarize_metrics,
)


def _report(
    *,
    gate_status: str = "passed",
    group_roles: list[str] | None = None,
    item_roles: list[str] | None = None,
    validation_overrides: dict | None = None,
    structure_types: list[str] | None = None,
    interface_category: str = "generic",
    class_strategy: str = "evidence_balanced",
) -> dict:
    roles = list(group_roles or ["list_group"])
    validation = {
        "orphan_node_count": 0,
        "duplicate_primary_owner_count": 0,
        "child_outside_parent_count": 0,
        "clipped_node_count": 0,
        "cycle_node_count": 0,
        "unreachable_from_root_count": 0,
    }
    validation.update(validation_overrides or {})
    return {
        "interface_classification": {
            "contract_version": "learn_interface_classification_v1",
            "category": interface_category,
            "source": "model_output",
            "status": "accepted",
            "confidence": 0.99,
            "safety_policy_override_allowed": False,
        },
        "class_rule_profile": {
            "primary_content_strategy": class_strategy,
            "safety_policy_override_allowed": False,
        },
        "stage1_gate": {"status": gate_status},
        "stage1_region_localization": {
            "localized_region_count": len(structure_types or ["top_bar", "main_content"]),
            "regions": [
                {
                    "region_id": f"structure_region_{region_type}",
                    "zone_id": region_type,
                    "label": region_type,
                }
                for region_type in (structure_types or ["top_bar", "main_content"])
            ],
        },
        "stage2_numbering": {
            "skipped": gate_status != "passed",
            "regions": [
                {
                    "subregion_groups": [
                        {"group_id": f"group_{index}", "role": role, "member_item_ids": []}
                        for index, role in enumerate(roles, start=1)
                    ],
                    "numbered_items": [
                        {"item_id": f"item_{index}", "role": role}
                        for index, role in enumerate(item_roles or [], start=1)
                    ],
                }
            ]
            if gate_status == "passed"
            else [],
        },
        "fusion": {"compiled_overlay_path": "artifacts/review-overlays/example.png"},
        "ui_hierarchy": {
            "contract_version": "ui_hierarchy_graph_v1",
            "nodes": [{"node_id": "uih:screen", "label": "Screen"}] * 12,
            "validation": validation,
        },
        "learning_draft": {
            "contract_version": "learning_template_draft_v1",
            "regions": [{"region_id": "main"}],
            "safety": {
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                "runtime_pathgraph_promotion": False,
            },
        },
    }


def test_supported_case_checks_hierarchy_and_semantic_expectations() -> None:
    case = {
        "case_id": "python",
        "expected_outcome": "supported",
        "expectations": {
            "min_structure_regions": 2,
            "min_hierarchy_nodes": 10,
            "required_group_roles": {"list_group": 1},
            "forbidden_label_tokens": ["apple music"],
        },
    }

    result = evaluate_case_report(case, _report())

    assert result["case_outcome"] == "supported_pass"
    assert result["capability_pass"] is True
    assert result["safety_pass"] is True
    assert all(assertion["passed"] for assertion in result["assertions"])


def test_supported_case_checks_model_category_and_selected_class_strategy() -> None:
    case = {
        "case_id": "python",
        "expected_outcome": "supported",
        "expectations": {
            "expected_interface_category": "documentation_portal",
            "expected_class_strategy": "text_structure_first",
        },
    }

    result = evaluate_case_report(
        case,
        _report(
            interface_category="documentation_portal",
            class_strategy="text_structure_first",
        ),
    )

    assert result["case_outcome"] == "supported_pass"
    assert result["interface_classification"]["category"] == "documentation_portal"
    assert result["class_rule_profile"]["primary_content_strategy"] == "text_structure_first"
    assert {item["assertion_id"] for item in result["assertions"]} >= {
        "expected_interface_category",
        "expected_class_strategy",
        "class_profile_cannot_override_safety",
    }


def test_supported_case_fails_when_model_category_does_not_match_fixture() -> None:
    case = {
        "case_id": "steam",
        "expected_outcome": "supported",
        "expectations": {
            "expected_interface_category": "conversation_workspace",
            "expected_class_strategy": "conversation_rows",
        },
    }

    result = evaluate_case_report(
        case,
        _report(interface_category="file_browser", class_strategy="row_table_first"),
    )

    assert result["case_outcome"] == "supported_fail"
    assert {item["assertion_id"] for item in result["failed_assertions"]} >= {
        "expected_interface_category",
        "expected_class_strategy",
    }


def test_known_failure_is_not_counted_as_capability_pass() -> None:
    case = {
        "case_id": "nvidia",
        "expected_outcome": "known_stage1_blocker",
        "expectations": {"expected_stage1_gate_status": "blocked_before_stage2_numbering"},
    }

    result = evaluate_case_report(case, _report(gate_status="blocked_before_stage2_numbering", group_roles=[]))

    assert result["case_outcome"] == "known_limitation_reproduced"
    assert result["capability_pass"] is False
    assert result["known_limitation_reproduced"] is True


def test_known_hierarchy_review_requires_the_expected_review_evidence() -> None:
    case = {
        "case_id": "transparent_overlay",
        "expected_outcome": "known_hierarchy_review",
        "expectations": {
            "expected_stage1_gate_status": "passed",
            "expected_hierarchy_status": "needs_review",
            "expected_min_clipped_nodes": 1,
        },
    }

    result = evaluate_case_report(
        case,
        _report(validation_overrides={"status": "needs_review", "clipped_node_count": 1}),
    )

    assert result["case_outcome"] == "known_limitation_reproduced"
    assert result["known_limitation_reproduced"] is True
    assert {item["assertion_id"] for item in result["assertions"]} >= {
        "hierarchy_expected_status",
        "hierarchy_expected_min_clipped_nodes",
    }


def test_summary_separates_cases_families_invalid_and_known_failures() -> None:
    cases = [
        {
            "case_id": "a1",
            "app_family": "apple",
            "case_outcome": "supported_pass",
            "capability_pass": True,
            "repeated_application_state": True,
            "interface_classification": {"category": "media_catalog", "source": "model_output", "status": "accepted"},
        },
        {
            "case_id": "a2",
            "app_family": "apple",
            "case_outcome": "supported_fail",
            "capability_pass": False,
            "repeated_application_state": True,
            "interface_classification": {"category": "media_catalog", "source": "model_output", "status": "accepted"},
        },
        {
            "case_id": "nvidia",
            "app_family": "nvidia",
            "case_outcome": "known_limitation_reproduced",
            "capability_pass": False,
        },
    ]
    invalid = [{"case_id": "stale", "failure_category": "stale_fixture"}]

    summary = summarize_metrics(cases, invalid)

    assert summary["case_count"] == 4
    assert summary["application_family_count"] == 2
    assert summary["supported_application_family_count"] == 1
    assert summary["supported_capability"]["passed"] == 1
    assert summary["supported_capability"]["attempted"] == 2
    assert summary["known_limitation_count"] == 1
    assert summary["invalid_fixture_count"] == 1
    assert summary["coverage_status"] == "fixed_recorded_surface_coverage"
    assert summary["reliability_status"] == "insufficient_application_diversity"
    media = summary["class_profile_coverage"]["categories"]["media_catalog"]
    assert media["case_count"] == 2
    assert media["application_family_count"] == 1
    assert media["recursive_state_case_count"] == 2
    assert media["reliability_status"] == "insufficient_sample_size_and_application_diversity"
    assert summary["class_profile_coverage"]["interpretation"].startswith("Model-selected class profiles")
    assert "overall_success_rate" not in summary


def test_fixture_validation_pins_trace_and_screenshot_checksums(tmp_path) -> None:
    trace = tmp_path / "trace.json"
    screenshot = tmp_path / "screen.png"
    trace.write_text("{}", encoding="utf-8")
    screenshot.write_bytes(b"png")
    case = {
        "case_id": "pinned",
        "trace_sha256": "wrong",
        "screenshot_sha256": "wrong",
    }

    error = _fixture_error(case, trace_path=trace, image_path=screenshot)

    assert error["failure_category"] == "stale_trace_fixture"
    assert error["expected_trace_checksum"] == "wrong"
    assert error["actual_trace_checksum"]


def test_supported_case_rejects_forbidden_leaf_role_pollution() -> None:
    case = {
        "case_id": "settings",
        "expected_outcome": "supported",
        "expectations": {"forbidden_item_roles": ["recommendation_item", "news_card"]},
    }

    result = evaluate_case_report(case, _report(item_roles=["recommendation_item"]))

    assert result["case_outcome"] == "supported_fail"
    assert result["item_role_counts"]["recommendation_item"] == 1
    assert any(
        assertion["assertion_id"] == "forbidden_item_role:recommendation_item" and not assertion["passed"]
        for assertion in result["assertions"]
    )


def test_supported_case_rejects_clipped_cyclic_or_unreachable_hierarchy() -> None:
    result = evaluate_case_report(
        {"case_id": "invalid_hierarchy", "expected_outcome": "supported"},
        _report(
            validation_overrides={
                "clipped_node_count": 1,
                "cycle_node_count": 2,
                "unreachable_from_root_count": 2,
            }
        ),
    )

    assert result["case_outcome"] == "supported_fail"
    failed_ids = {assertion["assertion_id"] for assertion in result["failed_assertions"]}
    assert {"clipped_node_count", "cycle_node_count", "unreachable_from_root_count"} <= failed_ids


def test_runner_safety_audit_does_not_present_declared_zeroes_as_runtime_measurement() -> None:
    audit = _runner_safety_audit()

    assert audit["runner_mode"] == "offline_fixed_artifact_replay"
    assert audit["runtime_action_trace_covered"] is False
    assert audit["runtime_measured_side_effect_counts"] == "not_covered"
    assert audit["counter_evidence_status"] == "declared_by_offline_runner_design_not_runtime_measured"
    assert audit["static_source_audit"]["passed"] is True
    assert audit["static_source_audit"]["direct_forbidden_imports"] == []


def test_supported_case_requires_named_structure_types_not_only_region_count() -> None:
    case = {
        "case_id": "chat",
        "expected_outcome": "supported",
        "expectations": {
            "min_structure_regions": 4,
            "required_structure_types": ["top_bar", "left_sidebar", "main_content", "right_sidebar"],
        },
    }

    result = evaluate_case_report(
        case,
        _report(structure_types=["top_bar", "primary_area", "right_sidebar", "bottom_bar"]),
    )

    assert result["case_outcome"] == "supported_fail"
    failed_ids = {assertion["assertion_id"] for assertion in result["failed_assertions"]}
    assert "required_structure_type:left_sidebar" in failed_ids
    assert "required_structure_type:main_content" not in failed_ids


def test_browser_chrome_structure_satisfies_top_bar_requirement() -> None:
    case = {
        "case_id": "file_browser_with_browser_chrome",
        "expected_outcome": "supported",
        "expectations": {
            "min_structure_regions": 2,
            "required_structure_types": ["top_bar", "main_content"],
        },
    }

    result = evaluate_case_report(
        case,
        _report(structure_types=["browser_chrome", "main_content"]),
        check_artifact_files=False,
    )

    assert result["case_outcome"] == "supported_pass"


def test_supported_case_checks_shared_vertical_lane_boundaries() -> None:
    report = _report(structure_types=["top_bar", "left_sidebar", "main_content", "right_sidebar"])
    for region, bbox in zip(
        report["stage1_region_localization"]["regions"],
        (
            {"x": 0, "y": 0, "w": 820, "h": 100},
            {"x": 0, "y": 100, "w": 240, "h": 940},
            {"x": 240, "y": 120, "w": 390, "h": 920},
            {"x": 630, "y": 100, "w": 190, "h": 940},
        ),
    ):
        region["bbox"] = bbox
    case = {
        "case_id": "chat_lanes",
        "expected_outcome": "supported",
        "expectations": {
            "shared_vertical_lane_types": ["left_sidebar", "main_content", "right_sidebar"],
            "shared_vertical_lane_tolerance_px": 2,
        },
    }

    result = evaluate_case_report(case, report)

    assert result["case_outcome"] == "supported_fail"
    assertion = next(
        assertion for assertion in result["assertions"] if assertion["assertion_id"] == "shared_vertical_lane_boundaries"
    )
    assert assertion["passed"] is False
    assert assertion["actual"]["main_content"] == {"top": 120, "bottom": 1040}


def test_supported_case_checks_horizontal_lane_tiling_without_gaps_or_overlap() -> None:
    report = _report(structure_types=["top_bar", "left_sidebar", "main_content", "right_sidebar"])
    for region, bbox in zip(
        report["stage1_region_localization"]["regions"],
        (
            {"x": 0, "y": 0, "w": 820, "h": 100},
            {"x": 16, "y": 100, "w": 238, "h": 940},
            {"x": 254, "y": 100, "w": 375, "h": 940},
            {"x": 629, "y": 100, "w": 191, "h": 940},
        ),
    ):
        region["bbox"] = bbox
    case = {
        "case_id": "chat_tiling",
        "expected_outcome": "supported",
        "expectations": {
            "horizontal_lane_tiling_types": ["left_sidebar", "main_content", "right_sidebar"],
            "horizontal_lane_tolerance_px": 2,
            "expected_screen_width": 820,
        },
    }

    result = evaluate_case_report(case, report)

    assert result["case_outcome"] == "supported_fail"
    assertion = next(
        assertion for assertion in result["assertions"] if assertion["assertion_id"] == "horizontal_lane_tiling"
    )
    assert assertion["passed"] is False
    assert assertion["actual"]["left_edge"] == 16


def test_ownership_golden_scores_expected_owner_role_from_resolved_map() -> None:
    report = _report(group_roles=["list_row", "tile_card_parent"])
    region = report["stage2_numbering"]["regions"][0]
    region["region_id"] = "structure_region_main_content"
    region["subregion_groups"] = [
        {"group_id": "list_row_1", "role": "list_row", "member_item_ids": ["ocr_1"]},
        {"group_id": "tile_1", "role": "tile_card_parent", "member_item_ids": ["ocr_2"]},
    ]
    region["ownership_resolution"] = {
        "source_item_owner_map": {"ocr_1": "list_row_1", "ocr_2": "tile_1"},
    }
    annotations = [
        {
            "annotation_id": "python_list_row",
            "region_id": "structure_region_main_content",
            "item_id": "ocr_1",
            "expected_owner_role": "list_row",
        },
        {
            "annotation_id": "python_tile",
            "region_id": "structure_region_main_content",
            "item_id": "ocr_2",
            "expected_owner_role": "tile_card_parent",
        },
    ]

    result = _evaluate_ownership_golden(report, annotations)

    assert result["source"] == "human_curated"
    assert result["passed"] == 2
    assert result["attempted"] == 2
    assert result["rate"] == 1.0
    assert result["used_for_rule_tuning"] is False
    assert result["mismatches"] == []


def test_ownership_golden_exposes_wrong_role_and_missing_item() -> None:
    report = _report(group_roles=["tile_card_parent"])
    region = report["stage2_numbering"]["regions"][0]
    region["region_id"] = "structure_region_main_content"
    region["subregion_groups"] = [
        {"group_id": "tile_1", "role": "tile_card_parent", "member_item_ids": ["ocr_1"]},
    ]
    region["ownership_resolution"] = {"source_item_owner_map": {"ocr_1": "tile_1"}}
    annotations = [
        {
            "annotation_id": "wrong_role",
            "region_id": "structure_region_main_content",
            "item_id": "ocr_1",
            "expected_owner_role": "list_row",
        },
        {
            "annotation_id": "missing_item",
            "region_id": "structure_region_main_content",
            "item_id": "ocr_missing",
            "expected_owner_role": "list_row",
        },
    ]

    result = _evaluate_ownership_golden(report, annotations)

    assert result["passed"] == 0
    assert result["attempted"] == 2
    assert result["rate"] == 0.0
    assert {item["failure_category"] for item in result["mismatches"]} == {
        "ownership_role_mismatch",
        "ownership_item_missing",
    }


def test_ownership_golden_manifest_is_checksum_pinned_and_grouped_by_case(tmp_path) -> None:
    golden_path = tmp_path / "ownership.json"
    golden_path.write_text(
        '{"contract_version":"general_ui_ownership_golden_holdout_v1","annotations":['
        '{"annotation_id":"a1","case_id":"python","region_id":"main","item_id":"ocr_1",'
        '"expected_owner_role":"list_row","source":"human_curated"}]}'
        ,
        encoding="utf-8",
    )
    checksum = hashlib.sha256(golden_path.read_bytes()).hexdigest()
    manifest = {
        "ownership_golden_manifest_path": str(golden_path),
        "ownership_golden_manifest_sha256": checksum,
    }

    result = _load_ownership_golden_manifest(manifest)

    assert result["status"] == "valid"
    assert result["annotation_count"] == 1
    assert result["annotations_by_case"]["python"][0]["annotation_id"] == "a1"


def test_stale_ownership_golden_manifest_is_invalid_and_not_scored(tmp_path) -> None:
    golden_path = tmp_path / "ownership.json"
    golden_path.write_text(
        '{"contract_version":"general_ui_ownership_golden_holdout_v1","annotations":[]}',
        encoding="utf-8",
    )

    result = _load_ownership_golden_manifest(
        {
            "ownership_golden_manifest_path": str(golden_path),
            "ownership_golden_manifest_sha256": "stale",
        }
    )
    summary = _summarize_ownership_golden([], result)

    assert result["status"] == "invalid"
    assert result["failure_category"] == "stale_ownership_golden_fixture"
    assert summary["attempted"] == 0
    assert summary["rate"] == "not_covered"
    assert summary["fixture_status"] == "invalid"


def test_ownership_golden_summary_aggregates_only_human_checks() -> None:
    case_results = [
        {
            "app_family": "python",
            "ownership_golden": {"passed": 2, "attempted": 3, "mismatches": [{"annotation_id": "a3"}]},
        },
        {"app_family": "qq", "ownership_golden": {"passed": 1, "attempted": 1, "mismatches": []}},
        {"ownership_golden": {"passed": 99, "attempted": 99, "source": "fixture_only"}},
    ]

    summary = _summarize_ownership_golden(case_results, {"status": "valid", "annotation_count": 4})

    assert summary["passed"] == 3
    assert summary["attempted"] == 4
    assert summary["rate"] == 0.75
    assert summary["used_for_rule_tuning"] is False
    assert summary["mismatches"] == [{"annotation_id": "a3"}]
    assert summary["annotated_case_count"] == 2
    assert summary["annotated_application_family_count"] == 2
    assert summary["coverage_status"] == "fixed_human_owner_role_holdout"
    assert summary["reliability_status"] == "insufficient_sample_size_and_application_diversity"
    assert summary["annotation_reliability_threshold"] == 30
    assert summary["application_family_reliability_threshold"] == 8


def test_case_report_includes_independent_ownership_golden_result() -> None:
    report = _report(group_roles=["list_row"])
    region = report["stage2_numbering"]["regions"][0]
    region["region_id"] = "structure_region_main_content"
    region["subregion_groups"] = [
        {"group_id": "list_row_1", "role": "list_row", "member_item_ids": ["ocr_1"]},
    ]
    region["ownership_resolution"] = {"source_item_owner_map": {"ocr_1": "list_row_1"}}

    result = evaluate_case_report(
        {"case_id": "python", "expected_outcome": "supported"},
        report,
        ownership_annotations=[
            {
                "annotation_id": "python_row",
                "region_id": "structure_region_main_content",
                "item_id": "ocr_1",
                "expected_owner_role": "list_row",
            }
        ],
    )

    assert result["ownership_golden"]["passed"] == 1
    assert result["ownership_golden"]["attempted"] == 1


def test_run_benchmark_loads_checksum_pinned_ownership_holdout(tmp_path, monkeypatch) -> None:
    trace_path = tmp_path / "trace.json"
    image_path = tmp_path / "screen.png"
    golden_path = tmp_path / "ownership.json"
    manifest_path = tmp_path / "manifest.json"
    trace_path.write_text("{}", encoding="utf-8")
    image_path.write_bytes(b"fixed-screen")
    golden_path.write_text(
        json.dumps(
            {
                "contract_version": "general_ui_ownership_golden_holdout_v1",
                "annotations": [
                    {
                        "annotation_id": "python_row",
                        "case_id": "python",
                        "region_id": "structure_region_main_content",
                        "item_id": "ocr_1",
                        "expected_owner_role": "list_row",
                        "source": "human_curated",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            {
                "contract_version": "general_ui_recognition_manifest_v1",
                "ownership_golden_manifest_path": str(golden_path),
                "ownership_golden_manifest_sha256": hashlib.sha256(golden_path.read_bytes()).hexdigest(),
                "cases": [
                    {
                        "case_id": "python",
                        "app_family": "python",
                        "expected_outcome": "supported",
                        "trace_path": str(trace_path),
                        "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
                        "screenshot_path": str(image_path),
                        "screenshot_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                        "expectations": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report = _report(group_roles=["list_row"])
    stage1_path = tmp_path / "stage1.png"
    final_path = tmp_path / "final.png"
    Image.new("RGB", (320, 200), "blue").save(stage1_path)
    Image.new("RGB", (320, 200), "orange").save(final_path)
    Image.new("RGB", (320, 200), "white").save(image_path)
    manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_payload["cases"][0]["screenshot_sha256"] = hashlib.sha256(image_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    report["stage1_region_localization"]["overlay_path"] = str(stage1_path)
    report["fusion"]["compiled_overlay_path"] = str(final_path)
    region = report["stage2_numbering"]["regions"][0]
    region["region_id"] = "structure_region_main_content"
    region["subregion_groups"] = [
        {"group_id": "list_row_1", "role": "list_row", "member_item_ids": ["ocr_1"]},
    ]
    region["ownership_resolution"] = {"source_item_owner_map": {"ocr_1": "list_row_1"}}
    monkeypatch.setattr(benchmark_module, "_build_case_report", lambda **_: report)

    result = run_benchmark(manifest_path=manifest_path, out_dir=tmp_path / "out")

    assert result["ownership_golden_holdout"]["fixture_status"] == "valid"
    assert result["ownership_golden_holdout"]["passed"] == 1
    assert result["ownership_golden_holdout"]["attempted"] == 1
    assert result["cases"][0]["ownership_golden"]["passed"] == 1
    assert result["cases"][0]["review_evidence"]["status"] == "available"
    assert result["review_evidence_summary"]["available"] == 1
    assert result["review_evidence_summary"]["invalid"] == 0


def test_case_review_sheet_requires_and_renders_same_size_original_stage1_final(tmp_path) -> None:
    original = tmp_path / "original.png"
    stage1 = tmp_path / "stage1.png"
    final = tmp_path / "final.png"
    for path, color in ((original, "white"), (stage1, "blue"), (final, "orange")):
        Image.new("RGB", (320, 200), color).save(path)
    report = {
        "stage1_region_localization": {"overlay_path": str(stage1)},
        "fusion": {"compiled_overlay_path": str(final)},
        "ui_hierarchy": {
            "summary": {
                "node_count": 18,
                "structure_region_count": 3,
                "component_count": 8,
                "content_count": 4,
                "level_counts": {"section": 2, "component_group": 3},
            },
            "validation": {"passed": True, "orphan_node_count": 0},
        },
    }

    result = _write_case_review_sheet(
        case_id="sample",
        report=report,
        source_image_path=original,
        case_dir=tmp_path / "case",
    )

    assert result["status"] == "available"
    assert result["same_source_dimensions"] is True
    assert result["panel_count"] == 4
    assert result["review_sheet_path"].endswith("review_sheet.png")
    assert (tmp_path / "case" / "review_sheet.png").exists()
    assert result["hierarchy_counts"] == {
        "nodes": 18,
        "structure_regions": 3,
        "sections": 2,
        "component_groups": 3,
        "components": 8,
        "content_nodes": 4,
    }


def test_case_review_sheet_rejects_missing_or_mismatched_evidence(tmp_path) -> None:
    original = tmp_path / "original.png"
    stage1 = tmp_path / "stage1.png"
    final = tmp_path / "final.png"
    Image.new("RGB", (320, 200), "white").save(original)
    Image.new("RGB", (300, 200), "blue").save(stage1)
    Image.new("RGB", (320, 200), "orange").save(final)

    result = _write_case_review_sheet(
        case_id="mismatch",
        report={
            "stage1_region_localization": {"overlay_path": str(stage1)},
            "fusion": {"compiled_overlay_path": str(final)},
        },
        source_image_path=original,
        case_dir=tmp_path / "case",
    )

    assert result["status"] == "invalid"
    assert result["failure_category"] == "review_evidence_dimension_mismatch"
    assert not (tmp_path / "case" / "review_sheet.png").exists()
