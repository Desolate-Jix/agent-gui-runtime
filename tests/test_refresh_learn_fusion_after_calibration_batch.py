from __future__ import annotations

import json
from pathlib import Path

from scripts.refresh_learn_fusion_after_calibration_batch import refresh_learn_fusion_after_calibration_batch


def test_refresh_after_calibration_batch_merges_attaches_and_reports_readiness(tmp_path: Path) -> None:
    trial = tmp_path / "actual_parser_output_v1.json"
    base_status = tmp_path / "fusion_status.json"
    rerun = tmp_path / "batch_rerun_report.json"
    batch_plan = tmp_path / "batch_plan.json"
    trial.write_text(
        json.dumps(
            {
                "contract_version": "actual_parser_output_v1",
                "learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "SEEK results",
                    "page_details": {"pipeline_audit": {}},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    base_status.write_text(
        json.dumps(
            {
                "contract_version": "learn_precise_understanding_fusion_status_report_v1",
                "source_report_path": "numbered_region_calibration_report.json",
                "full_screen_understanding_overlay_path": "full-overlay.png",
                "compiled_overlay_path": "compiled-overlay.png",
                "display_readiness": {"status": "display_ready", "item_count": 5},
                "pathgraph_preparation": {"status": "blocked_from_pathgraph_candidate_review"},
                "summary": {
                    "attempted": 5,
                    "total_locator_cards": 5,
                    "calibrated_cases": 2,
                    "uncalibrated_locator_cards": 3,
                    "needs_human_review": 2,
                    "safe_intercepts": 0,
                    "failed": 0,
                    "real_clicks": 0,
                },
                "items": [
                    _fusion_item(1, "c1", "pending_calibration"),
                    _fusion_item(2, "c2", "pending_calibration"),
                    _fusion_item(3, "c3", "pending_calibration"),
                    _fusion_item(4, "c4", "needs_human_review"),
                    _fusion_item(5, "c5", "needs_human_review"),
                ],
                "calibration_backlog": {
                    "contract_version": "numbered_region_calibration_backlog_v1",
                    "summary": {"uncalibrated_locator_cards": 3, "ready_for_execute_dry_run": 2, "review_before_calibration": 1},
                    "items": [
                        {"region_no": 1, "source_item_id": "c1", "ready_for_execute_dry_run": True},
                        {"region_no": 2, "source_item_id": "c2", "ready_for_execute_dry_run": True},
                        {"region_no": 3, "source_item_id": "c3", "ready_for_execute_dry_run": False},
                    ],
                },
                "calibration_batch_plan": {
                    "contract_version": "numbered_region_calibration_batch_plan_v1",
                    "summary": {"ready_for_execute_dry_run": 2, "review_before_calibration": 1, "real_clicks": 0},
                    "ready_region_numbers": [1, 2],
                    "review_blocked_region_numbers": [3],
                    "run_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2",
                    "command_executes_now": False,
                },
                "pathgraph_preflight_plan": {
                    "summary": {
                        "pending_calibration_ready_count": 2,
                        "pending_calibration_review_count": 1,
                        "ready_for_runtime_pathgraph_promotion": False,
                    },
                    "pending_calibration_batch": {
                        "ready_region_numbers": [1, 2],
                        "review_blocked_region_numbers": [3],
                        "run_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2",
                        "command_executes_now": False,
                    },
                },
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rerun.write_text(
        json.dumps(
            {
                "contract_version": "numbered_region_calibration_probe_v1",
                "screenshot_path": "fresh-screenshot.png",
                "full_screen_understanding_overlay_path": "fresh-full-overlay.png",
                "compiled_overlay_path": "fresh-compiled-overlay.png",
                "fused_precise_understanding": {
                    "items": [
                        _rerun_item(1, "c1"),
                        _rerun_item(2, "c2"),
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    batch_plan.write_text(
        json.dumps(
            {
                "contract_version": "learning_draft_numbered_region_calibration_batch_plan_v1",
                "ready_region_numbers": [1, 2],
                "review_blocked_region_numbers": [3],
                "command_executes_now": False,
                "post_batch_refresh_command_executes_now": False,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = refresh_learn_fusion_after_calibration_batch(
        trial_path=trial,
        base_status_path=base_status,
        rerun_report_path=rerun,
        batch_plan_path=batch_plan,
        out_dir=tmp_path / "out",
    )

    assert result["contract_version"] == "learn_fusion_after_calibration_batch_refresh_result_v1"
    assert result["refresh_status"] == "refreshed_after_calibration_batch"
    assert result["acceptance_status"] == "accepted_for_post_batch_refresh"
    assert result["acceptance_blockers"] == []
    assert result["merge_skipped"] is False
    assert result["attach_skipped"] is False
    assert result["readiness_skipped"] is False
    assert result["updated_region_numbers"] == [1, 2]
    assert result["readiness_status"] == "needs_pending_calibration"
    assert result["execute_binding_enabled"] is False
    assert result["artifact_is_authorization"] is False
    assert result["model_started"] is False
    assert Path(result["corrected_status_path"]).exists()
    assert Path(result["attached_draft_path"]).exists()
    assert Path(result["readiness_report_path"]).exists()

    corrected = json.loads(Path(result["corrected_status_path"]).read_text(encoding="utf-8"))
    assert corrected["source_report_path"] == str(rerun.resolve())
    assert corrected["screenshot_path"] == "fresh-screenshot.png"
    assert corrected["full_screen_understanding_overlay_path"] == "fresh-full-overlay.png"
    assert corrected["compiled_overlay_path"] == "fresh-compiled-overlay.png"
    assert corrected["summary"]["calibrated_cases"] == 4
    assert corrected["calibration_batch_plan"]["ready_region_numbers"] == []
    assert corrected["pathgraph_preflight_plan"]["summary"]["pending_calibration_ready_count"] == 0

    attached = json.loads(Path(result["attached_draft_path"]).read_text(encoding="utf-8"))
    fusion = attached["learning_draft"]["page_details"]["pipeline_audit"]["precise_understanding_fusion_status"]
    assert fusion["source_calibration_report_path"] == str(rerun.resolve())
    assert fusion["full_screen_understanding_overlay_path"] == "fresh-full-overlay.png"
    assert fusion["compiled_overlay_path"] == "fresh-compiled-overlay.png"
    assert fusion["calibration_batch_plan"]["ready_region_numbers"] == []
    assert fusion["pathgraph_preflight_plan"]["pending_calibration_batch"]["review_blocked_region_numbers"] == [3]
    assert fusion["precise_understanding_readiness_summary"]["calibration_coverage_rate"] == 0.8

    readiness = json.loads(Path(result["readiness_report_path"]).read_text(encoding="utf-8"))
    assert readiness["coverage_summary"]["calibration_coverage_rate"] == 0.8
    assert readiness["pending_calibration"]["ready_region_numbers"] == []
    assert readiness["pending_calibration"]["review_blocked_region_numbers"] == [3]
    assert readiness["execute_binding_enabled"] is False
    assert readiness["artifact_is_authorization"] is False


def test_refresh_after_calibration_batch_blocks_merge_when_acceptance_fails(tmp_path: Path) -> None:
    trial = tmp_path / "actual_parser_output_v1.json"
    base_status = tmp_path / "fusion_status.json"
    rerun = tmp_path / "batch_rerun_report.json"
    batch_plan = tmp_path / "batch_plan.json"
    trial.write_text(
        json.dumps(
            {
                "contract_version": "actual_parser_output_v1",
                "learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "SEEK results",
                    "page_details": {"pipeline_audit": {}},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    base_status.write_text(
        json.dumps(
            {
                "contract_version": "learn_precise_understanding_fusion_status_report_v1",
                "items": [_fusion_item(1, "c1", "pending_calibration"), _fusion_item(2, "c2", "pending_calibration")],
                "summary": {"real_clicks": 0},
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    batch_plan.write_text(
        json.dumps(
            {
                "contract_version": "learning_draft_numbered_region_calibration_batch_plan_v1",
                "ready_region_numbers": [1, 2],
                "review_blocked_region_numbers": [],
                "command_executes_now": False,
                "post_batch_refresh_command_executes_now": False,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rerun.write_text(
        json.dumps(
            {
                "contract_version": "numbered_region_calibration_probe_v1",
                "summary": {"real_clicks": 0},
                "fused_precise_understanding": {"items": [_rerun_item(1, "c1")]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = refresh_learn_fusion_after_calibration_batch(
        trial_path=trial,
        base_status_path=base_status,
        rerun_report_path=rerun,
        batch_plan_path=batch_plan,
        out_dir=tmp_path / "out",
    )

    assert result["refresh_status"] == "blocked_by_calibration_batch_acceptance"
    assert result["acceptance_status"] == "blocked_calibration_batch_invalid"
    assert result["acceptance_blockers"] == ["missing_ready_regions"]
    assert result["merge_skipped"] is True
    assert result["attach_skipped"] is True
    assert result["readiness_skipped"] is True
    assert result["execute_binding_enabled"] is False
    assert result["artifact_is_authorization"] is False
    assert result["model_started"] is False
    assert result["live_clicks"] == 0
    assert not (tmp_path / "out" / "merge").exists()
    assert not (tmp_path / "out" / "attached_draft").exists()
    assert not (tmp_path / "out" / "readiness").exists()

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["refresh_status"] == "blocked_by_calibration_batch_acceptance"
    assert report["acceptance_report_path"] == result["acceptance_report_path"]


def _fusion_item(region_no: int, source_item_id: str, calibration_status: str) -> dict[str, object]:
    return {
        "region_no": region_no,
        "source_item_id": source_item_id,
        "label": f"Region {region_no}",
        "role": "input",
        "calibration_status": calibration_status,
        "point_quality": "not_checked",
        "gate_safety": "not_checked",
        "real_clicks": 0,
        "promotion_policy": {
            "promotable_to_pathgraph_candidate_review": False,
            "block_reason": calibration_status,
        },
    }


def _rerun_item(region_no: int, source_item_id: str) -> dict[str, object]:
    item = _fusion_item(region_no, source_item_id, "needs_human_review")
    item["point_quality"] = "vista_point_inside_seed_bbox"
    item["gate_safety"] = "passed_allowed_dry_run"
    item["trace_path"] = f"region-{region_no}-trace.json"
    item["promotion_policy"] = {
        "promotable_to_pathgraph_candidate_review": False,
        "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
    }
    return item
