from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.run_learning_interface_chain_smoke import (
    ChainSmokeCase,
    _observation_evidence,
    build_acceptance_batch_plan,
    build_resource_blocked_report,
    _two_stage_stage1_overlay_path,
    _two_stage_review_box_count,
    build_learn_calibration_metadata,
    build_manifest_cases,
    build_manifest_suite_cases,
    build_post_calibration_three_image_audit,
    build_three_image_audit,
    build_protected_cases,
    ensure_acceptance_model_stage,
    load_resume_completed_case_ids,
    audit_stage1_geometry,
    classify_chain_completion,
    classify_case_quality,
    evaluate_class_expectations,
    evaluate_saved_class_expectations,
    main,
    summarize_class_expectation_audits,
)


def test_ensure_acceptance_model_stage_waits_for_locate_model(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_ensure_model_server(**kwargs):
        calls.append(dict(kwargs))
        return {
            "stage": "locate",
            "profile": {"profile_id": "vista_4b_transformers"},
            "before": {"status": "unreachable"},
            "started": True,
            "after": {"status": "running", "model_id": "VISTA-4B"},
        }

    monkeypatch.setattr(
        "scripts.run_learning_interface_chain_smoke.ensure_model_server",
        fake_ensure_model_server,
    )

    result = ensure_acceptance_model_stage("locate", wait_seconds=120)

    assert calls == [
        {
            "stage": "locate",
            "wait_until_ready": True,
            "wait_seconds": 120,
        }
    ]
    assert result["status"] == "running"
    assert result["profile_id"] == "vista_4b_transformers"
    assert result["started"] is True


def test_ensure_acceptance_model_stage_rejects_non_running_model(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.run_learning_interface_chain_smoke.ensure_model_server",
        lambda **_kwargs: {
            "stage": "locate",
            "profile": {"profile_id": "vista_4b_transformers"},
            "before": {"status": "unreachable"},
            "started": True,
            "after": {"status": "startup_failed", "reason": "started_process_exited"},
        },
    )

    with pytest.raises(RuntimeError, match="acceptance model stage locate is not ready: startup_failed"):
        ensure_acceptance_model_stage("locate", wait_seconds=5)


def _write_acceptance_manifest(tmp_path: Path, *, name: str, case_id: str) -> Path:
    trace_path = tmp_path / f"{name}_trace.json"
    image_path = tmp_path / f"{name}_screen.png"
    trace_path.write_text('{"result": {}}\n', encoding="utf-8")
    image_path.write_bytes(f"image:{name}".encode("utf-8"))
    manifest_path = tmp_path / f"{name}_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": case_id,
                        "trace_path": str(trace_path),
                        "screenshot_path": str(image_path),
                        "trace_sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
                        "screenshot_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_build_manifest_suite_cases_combines_protected_and_holdout_manifests(tmp_path: Path) -> None:
    protected = _write_acceptance_manifest(tmp_path, name="protected", case_id="protected_case")
    holdout = _write_acceptance_manifest(tmp_path, name="holdout", case_id="holdout_case")

    cases = build_manifest_suite_cases([protected, holdout])

    assert [case.case_id for case in cases] == ["protected_case", "holdout_case"]


def test_build_manifest_suite_cases_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    first = _write_acceptance_manifest(tmp_path, name="first", case_id="duplicate_case")
    second = _write_acceptance_manifest(tmp_path, name="second", case_id="duplicate_case")

    with pytest.raises(ValueError, match="duplicate acceptance case ids: duplicate_case"):
        build_manifest_suite_cases([first, second])


def test_acceptance_batch_plan_uses_resource_recommendation_and_can_resume() -> None:
    cases = [
        ChainSmokeCase(case_id=f"case_{index}", trace_path="trace.json", source_image_path="screen.png")
        for index in range(5)
    ]
    preflight = {
        "resource_mode": "constrained",
        "model_launch_allowed": True,
        "recommended_batch_size": 2,
    }

    first = build_acceptance_batch_plan(cases, resource_preflight=preflight, batch_index=0)
    second = build_acceptance_batch_plan(cases, resource_preflight=preflight, batch_index=1)

    assert first["selected_case_ids"] == ["case_0", "case_1"]
    assert first["pending_case_ids"] == ["case_2", "case_3", "case_4"]
    assert first["batch_size"] == 2
    assert second["selected_case_ids"] == ["case_2", "case_3"]
    assert second["pending_case_ids"] == ["case_0", "case_1", "case_4"]


def test_acceptance_batch_plan_resumes_by_completed_ids_when_resource_batch_size_changes() -> None:
    cases = [
        ChainSmokeCase(case_id=f"case_{index}", trace_path="trace.json", source_image_path="screen.png")
        for index in range(5)
    ]

    first = build_acceptance_batch_plan(
        cases,
        resource_preflight={"recommended_batch_size": 2, "model_launch_allowed": True},
    )
    resumed = build_acceptance_batch_plan(
        cases,
        resource_preflight={"recommended_batch_size": 1, "model_launch_allowed": True},
        completed_case_ids=first["selected_case_ids"],
    )

    assert resumed["completed_case_ids"] == ["case_0", "case_1"]
    assert resumed["remaining_case_ids"] == ["case_2", "case_3", "case_4"]
    assert resumed["selected_case_ids"] == ["case_2"]
    assert resumed["pending_case_ids"] == ["case_3", "case_4"]


def test_acceptance_batch_plan_rejects_resume_ids_with_nonzero_batch_index() -> None:
    cases = [
        ChainSmokeCase(case_id=f"case_{index}", trace_path="trace.json", source_image_path="screen.png")
        for index in range(3)
    ]

    with pytest.raises(ValueError, match="batch_index must remain zero when completed_case_ids are supplied"):
        build_acceptance_batch_plan(
            cases,
            resource_preflight={"recommended_batch_size": 1, "model_launch_allowed": True},
            completed_case_ids=["case_0"],
            batch_index=1,
        )


def test_load_resume_completed_case_ids_reads_same_manifest_batch_reports(tmp_path: Path) -> None:
    manifest = (tmp_path / "manifest.json").resolve()
    manifest.write_text('{"cases": []}\n', encoding="utf-8")
    first_report = tmp_path / "batch_0.json"
    second_report = tmp_path / "batch_1.json"
    for path, completed in (
        (first_report, ["case_0", "case_1"]),
        (second_report, ["case_2"]),
    ):
        path.write_text(
            json.dumps(
                {
                    "contract_version": "learning_interface_chain_smoke_report_v2",
                    "status": "completed_batch",
                    "manifest_paths": [str(manifest)],
                    "completed_case_ids": completed,
                }
            ),
            encoding="utf-8",
        )

    completed = load_resume_completed_case_ids(
        [first_report, second_report],
        expected_manifest_paths=[str(manifest)],
        known_case_ids={"case_0", "case_1", "case_2", "case_3"},
    )

    assert completed == ["case_0", "case_1", "case_2"]


def test_cli_resume_report_keeps_only_unfinished_cases_pending(tmp_path: Path, monkeypatch) -> None:
    first_manifest = _write_acceptance_manifest(tmp_path, name="first", case_id="case_0")
    second_manifest = _write_acceptance_manifest(tmp_path, name="second", case_id="case_1")
    resume_report = tmp_path / "completed_batch.json"
    resume_report.write_text(
        json.dumps(
            {
                "contract_version": "learning_interface_chain_smoke_report_v2",
                "status": "completed_batch",
                "manifest_paths": [str(first_manifest.resolve()), str(second_manifest.resolve())],
                "completed_case_ids": ["case_0"],
            }
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    monkeypatch.setattr(
        "scripts.run_learning_interface_chain_smoke.build_chain_model_resource_preflight",
        lambda: {
            "resource_mode": "critical",
            "model_launch_allowed": False,
            "recommended_batch_size": 1,
            "reason_codes": ["insufficient_gpu_memory_for_profile"],
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_learning_interface_chain_smoke.py",
            "--manifest",
            str(first_manifest),
            "--manifest",
            str(second_manifest),
            "--resume-report",
            str(resume_report),
            "--out",
            str(out_dir),
            "--json",
        ],
    )

    exit_code = main()
    report = json.loads((out_dir / "learning_interface_chain_smoke_report.json").read_text(encoding="utf-8"))

    assert exit_code == 2
    assert report["completed_case_ids"] == []
    assert report["pending_case_ids"] == ["case_1"]
    assert report["batch_plan"]["completed_case_ids"] == ["case_0"]
    assert report["batch_plan"]["selected_case_ids"] == ["case_1"]
    assert report["resume_report_paths"] == [str(resume_report.resolve())]


def test_acceptance_batch_plan_filters_explicit_case_ids_before_batching() -> None:
    cases = [
        ChainSmokeCase(case_id=f"case_{index}", trace_path="trace.json", source_image_path="screen.png")
        for index in range(4)
    ]

    plan = build_acceptance_batch_plan(
        cases,
        resource_preflight={"recommended_batch_size": 8, "model_launch_allowed": True},
        requested_case_ids=["case_3", "case_1"],
        requested_batch_size=1,
        batch_index=1,
    )

    assert plan["eligible_case_ids"] == ["case_1", "case_3"]
    assert plan["selected_case_ids"] == ["case_3"]
    assert plan["pending_case_ids"] == ["case_1"]


def test_resource_blocked_report_does_not_attempt_model_or_score_cases(tmp_path: Path) -> None:
    plan = {
        "selected_case_ids": ["case_0"],
        "pending_case_ids": ["case_1"],
        "eligible_case_ids": ["case_0", "case_1"],
        "batch_size": 1,
        "batch_index": 0,
    }
    preflight = {
        "resource_mode": "critical",
        "model_launch_allowed": False,
        "recommended_batch_size": 1,
        "reason_codes": ["insufficient_gpu_memory_for_profile"],
    }

    report = build_resource_blocked_report(
        batch_plan=plan,
        resource_preflight=preflight,
        out_dir=tmp_path,
    )

    assert report["status"] == "resource_blocked"
    assert report["model_calls_attempted"] == 0
    assert report["case_count"] == 0
    assert report["invalid_case_count"] == 0
    assert report["pending_case_ids"] == ["case_0", "case_1"]
    assert report["safety"]["live_clicks"] == 0
    assert Path(report["report_path"]).exists()


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


def test_targeted_fresh_rerun_manifest_freezes_independent_expectations() -> None:
    manifest_path = Path("tests/fixtures/learning_practical_targeted_rerun_manifest_v1.json")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["used_for_rule_tuning"] is False
    assert payload["holdout_used_for_tuning"] is False

    cases = payload["cases"]
    assert [case["case_id"] for case in cases] == [
        "conversation_workspace_whatsapp_20260715",
        "holdout_qq_group_chat_20260720",
        "holdout_github_desktop_changes_20260718",
    ]
    assert all(case["expectations"] for case in cases)
    assert all(case["screenshot_sha256"] for case in cases)
    assert all(case["trace_sha256"] for case in cases)

    raw_cases = {case["case_id"]: case for case in payload["cases"]}
    assert raw_cases["conversation_workspace_whatsapp_20260715"]["expected_root_zones"] == [
        "left_nav",
        "top_bar",
        "main_content",
    ]
    assert raw_cases["holdout_qq_group_chat_20260720"]["expected_root_zones"] == [
        "left_nav",
        "top_bar",
        "main_content",
    ]
    assert raw_cases["holdout_github_desktop_changes_20260718"]["expected_root_zones"] == [
        "top_bar",
        "main_content",
    ]

    github_case = next(case for case in cases if case["app_family"] == "github_desktop")
    assert "conversation_row" in github_case["expectations"]["forbidden_group_roles"]
    assert "message_item" in github_case["expectations"]["forbidden_group_roles"]


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


def test_class_expectation_audit_scores_bar_presence_absence_and_sub_bar_roles() -> None:
    expectations = {
        "expected_bar_types": ["top_bar", "left_sidebar"],
        "expected_absent_bar_types": ["right_sidebar", "bottom_bar"],
        "expected_sub_bar_roles": ["conversation_navigation_rail", "conversation_list"],
    }
    report = {
        "ui_hierarchy": {
            "nodes": [
                {"level": "screen", "component_type": "screen", "label": "Chat"},
                {"level": "structure_region", "component_type": "top_bar", "label": "Title"},
                {"level": "structure_region", "component_type": "left_sidebar", "label": "Navigation"},
                {"level": "structure_region", "component_type": "main_content", "label": "Conversation"},
                {
                    "level": "component_group",
                    "component_type": "conversation_navigation_rail",
                    "label": "Navigation rail",
                },
                {"level": "component_group", "component_type": "conversation_list", "label": "Chats"},
            ]
        }
    }

    passed = evaluate_class_expectations(report, expectations)
    assert passed["status"] == "passed"
    assert passed["actual"]["bar_types"] == ["left_sidebar", "top_bar"]
    assert passed["actual"]["sub_bar_roles"] == [
        "conversation_list",
        "conversation_navigation_rail",
    ]

    failed_report = {
        "ui_hierarchy": {
            "nodes": [
                {"level": "screen", "component_type": "screen", "label": "Chat"},
                {"level": "structure_region", "component_type": "left_sidebar", "label": "Navigation"},
                {"level": "structure_region", "component_type": "right_sidebar", "label": "Unexpected"},
                {
                    "level": "component_group",
                    "component_type": "conversation_navigation_rail",
                    "label": "Navigation rail",
                },
            ]
        }
    }
    failed = evaluate_class_expectations(failed_report, expectations)

    assert failed["status"] == "needs_review"
    assert "missing_expected_bar_type:top_bar" in failed["issues"]
    assert "unexpected_bar_type:right_sidebar" in failed["issues"]
    assert "missing_expected_sub_bar_role:conversation_list" in failed["issues"]


def test_steam_acceptance_cases_expect_the_visible_group_chat_bottom_bar() -> None:
    manifest_path = Path("tests/fixtures/learning_practical_steam_bar_adjudication_v1.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    steam_cases = {
        case["case_id"]: case
        for case in manifest["cases"]
        if str(case.get("case_id") or "").startswith("conversation_workspace_steam_")
    }

    assert set(steam_cases) == {
        "conversation_workspace_steam_20260713",
        "conversation_workspace_steam_20260714",
    }
    for case in steam_cases.values():
        assert case["adjudication"] == "visible_docked_group_chat_bottom_area"
        assert "bottom_bar" in case["expected_bar_types"]
        assert "bottom_bar" not in case["expected_absent_bar_types"]


def test_class_expectation_audit_reads_stage1_5_chat_subregions_and_navigation_root() -> None:
    expectations = {
        "expected_bar_types": ["left_sidebar"],
        "expected_sub_bar_roles": ["conversation_navigation_rail", "conversation_list"],
    }
    report = {
        "interface_classification": {"category": "conversation_workspace"},
        "ui_hierarchy": {
            "nodes": [
                {"level": "screen", "component_type": "screen", "label": "Chat"},
                {"level": "structure_region", "component_type": "left_sidebar", "label": "Navigation"},
                {"level": "structure_region", "component_type": "main_content", "label": "Conversation"},
            ]
        },
        "stage1_5_partition": {
            "subregions": [
                {"role": "conversation_list", "bbox": {"x": 60, "y": 80, "w": 260, "h": 620}},
                {"role": "message_thread", "bbox": {"x": 320, "y": 80, "w": 680, "h": 620}},
            ]
        },
    }

    result = evaluate_class_expectations(report, expectations)

    assert result["status"] == "passed"
    assert result["actual"]["sub_bar_roles"] == [
        "conversation_list",
        "conversation_navigation_rail",
    ]
    assert result["actual"]["sub_bar_evidence_sources"] == {
        "conversation_list": "stage1_5_partition",
        "conversation_navigation_rail": "conversation_workspace_left_sidebar_root",
    }


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
