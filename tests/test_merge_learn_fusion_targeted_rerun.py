from __future__ import annotations

import json
from pathlib import Path

from scripts.merge_learn_fusion_targeted_rerun import merge_targeted_rerun_into_fusion_status


def test_merge_targeted_rerun_updates_matching_items_and_recomputes_counts(tmp_path: Path) -> None:
    base = tmp_path / "base_status.json"
    rerun = tmp_path / "rerun_report.json"
    base.write_text(
        json.dumps(
            {
                "contract_version": "learn_precise_understanding_fusion_status_report_v1",
                "display_readiness": {"status": "display_ready", "item_count": 3},
                "pathgraph_preparation": {"status": "blocked_from_pathgraph_candidate_review"},
                "summary": {"attempted": 3, "needs_human_review": 1, "safe_intercepts": 2, "real_clicks": 0},
                "items": [
                    {
                        "region_no": 4,
                        "source_item_id": "c4",
                        "label": "Job listing card",
                        "role": "card",
                        "calibration_status": "gate_rejected",
                        "point_quality": "vista_point_inside_seed_bbox",
                        "gate_safety": "passed_rejected",
                        "trace_path": "old-trace.json",
                        "real_clicks": 0,
                        "promotion_policy": {
                            "promotable_to_pathgraph_candidate_review": False,
                            "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
                        },
                    },
                    {
                        "region_no": 7,
                        "source_item_id": "c8",
                        "label": "Details placeholder",
                        "role": "other",
                        "calibration_status": "gate_rejected",
                        "point_quality": "vista_point_inside_seed_bbox",
                        "gate_safety": "passed_rejected",
                        "real_clicks": 0,
                        "promotion_policy": {
                            "promotable_to_pathgraph_candidate_review": False,
                            "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
                        },
                    },
                    {
                        "region_no": 1,
                        "source_item_id": "c1",
                        "label": "Search",
                        "role": "input",
                        "calibration_status": "needs_human_review",
                        "point_quality": "vista_point_inside_seed_bbox",
                        "gate_safety": "passed_allowed_dry_run",
                        "real_clicks": 0,
                        "promotion_policy": {
                            "promotable_to_pathgraph_candidate_review": False,
                            "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
                        },
                    },
                ],
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
                "fused_precise_understanding": {
                    "items": [
                        {
                            "region_no": 4,
                            "source_item_id": "c4",
                            "label": "Job listing card: Software Engineer",
                            "role": "card",
                            "calibration_status": "needs_human_review",
                            "point_quality": "vista_point_inside_seed_bbox",
                            "gate_safety": "passed_allowed_dry_run",
                            "trace_path": "new-open-detail-trace.json",
                            "recognition_plan_trace_path": "new-plan.json",
                            "overlay_path": "new-overlay.png",
                            "real_clicks": 0,
                            "promotion_policy": {
                                "promotable_to_pathgraph_candidate_review": False,
                                "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
                            },
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = merge_targeted_rerun_into_fusion_status(base_status_path=base, rerun_report_path=rerun, out_dir=tmp_path / "out")

    assert result["contract_version"] == "learn_fusion_targeted_rerun_merge_result_v1"
    assert result["updated_item_count"] == 1
    corrected = json.loads(Path(result["corrected_status_path"]).read_text(encoding="utf-8"))
    assert corrected["summary"]["attempted"] == 3
    assert corrected["summary"]["needs_human_review"] == 2
    assert corrected["summary"]["safe_intercepts"] == 1
    assert "total_locator_cards" not in corrected["summary"]
    assert "calibration_coverage_rate" not in corrected["summary"]
    assert corrected["precise_understanding_readiness_summary"]["total_locator_cards"] == 0
    assert corrected["precise_understanding_readiness_summary"]["calibration_coverage_rate"] == "not_covered"
    assert corrected["calibration_status_counts"] == {"gate_rejected": 1, "needs_human_review": 2}
    item = next(item for item in corrected["items"] if item["region_no"] == 4)
    assert item["calibration_status"] == "needs_human_review"
    assert item["gate_safety"] == "passed_allowed_dry_run"
    assert item["trace_path"] == "new-open-detail-trace.json"
    assert item["targeted_rerun_correction"]["previous_calibration_status"] == "gate_rejected"
    assert corrected["targeted_rerun_correction"]["updated_region_numbers"] == [4]
    assert corrected["execute_binding_enabled"] is False
    assert corrected["artifact_is_authorization"] is False


def test_merge_targeted_rerun_removes_batch_regions_from_pending_readiness(tmp_path: Path) -> None:
    base = tmp_path / "base_status.json"
    rerun = tmp_path / "rerun_report.json"
    base.write_text(
        json.dumps(
            {
                "contract_version": "learn_precise_understanding_fusion_status_report_v1",
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
                    {
                        "region_no": 1,
                        "source_item_id": "c1",
                        "label": "Search input",
                        "role": "input",
                        "calibration_status": "pending_calibration",
                        "point_quality": "not_checked",
                        "gate_safety": "not_checked",
                        "real_clicks": 0,
                        "promotion_policy": {
                            "promotable_to_pathgraph_candidate_review": False,
                            "block_reason": "pending_calibration",
                        },
                    },
                    {
                        "region_no": 2,
                        "source_item_id": "c2",
                        "label": "Location input",
                        "role": "input",
                        "calibration_status": "pending_calibration",
                        "point_quality": "not_checked",
                        "gate_safety": "not_checked",
                        "real_clicks": 0,
                        "promotion_policy": {
                            "promotable_to_pathgraph_candidate_review": False,
                            "block_reason": "pending_calibration",
                        },
                    },
                    {
                        "region_no": 3,
                        "source_item_id": "c3",
                        "label": "Page count text",
                        "role": "text",
                        "calibration_status": "pending_calibration",
                        "point_quality": "not_checked",
                        "gate_safety": "not_checked",
                        "real_clicks": 0,
                        "promotion_policy": {
                            "promotable_to_pathgraph_candidate_review": False,
                            "block_reason": "pending_calibration",
                        },
                    },
                    {
                        "region_no": 4,
                        "source_item_id": "c4",
                        "label": "Job card",
                        "role": "card",
                        "calibration_status": "needs_human_review",
                        "point_quality": "vista_point_inside_seed_bbox",
                        "gate_safety": "passed_allowed_dry_run",
                        "real_clicks": 0,
                        "promotion_policy": {
                            "promotable_to_pathgraph_candidate_review": False,
                            "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
                        },
                    },
                    {
                        "region_no": 5,
                        "source_item_id": "c5",
                        "label": "Apply button",
                        "role": "button",
                        "calibration_status": "needs_human_review",
                        "point_quality": "vista_point_inside_seed_bbox",
                        "gate_safety": "passed_allowed_dry_run",
                        "real_clicks": 0,
                        "promotion_policy": {
                            "promotable_to_pathgraph_candidate_review": False,
                            "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
                        },
                    },
                ],
                "calibration_backlog": {
                    "contract_version": "numbered_region_calibration_backlog_v1",
                    "summary": {
                        "uncalibrated_locator_cards": 3,
                        "ready_for_execute_dry_run": 2,
                        "review_before_calibration": 1,
                    },
                    "items": [
                        {"region_no": 1, "source_item_id": "c1", "ready_for_execute_dry_run": True},
                        {"region_no": 2, "source_item_id": "c2", "ready_for_execute_dry_run": True},
                        {"region_no": 3, "source_item_id": "c3", "ready_for_execute_dry_run": False},
                    ],
                },
                "calibration_batch_plan": {
                    "contract_version": "numbered_region_calibration_batch_plan_v1",
                    "summary": {
                        "ready_for_execute_dry_run": 2,
                        "review_before_calibration": 1,
                        "real_clicks": 0,
                    },
                    "ready_region_numbers": [1, 2],
                    "review_blocked_region_numbers": [3],
                    "ready_items": [
                        {"region_no": 1, "source_item_id": "c1"},
                        {"region_no": 2, "source_item_id": "c2"},
                    ],
                    "review_blocked_items": [{"region_no": 3, "source_item_id": "c3"}],
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
                "fused_precise_understanding": {
                    "items": [
                        {
                            "region_no": 1,
                            "source_item_id": "c1",
                            "label": "Search input",
                            "role": "input",
                            "calibration_status": "needs_human_review",
                            "point_quality": "vista_point_inside_seed_bbox",
                            "gate_safety": "passed_allowed_dry_run",
                            "trace_path": "region-1-trace.json",
                            "real_clicks": 0,
                            "promotion_policy": {
                                "promotable_to_pathgraph_candidate_review": False,
                                "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
                            },
                        },
                        {
                            "region_no": 2,
                            "source_item_id": "c2",
                            "label": "Location input",
                            "role": "input",
                            "calibration_status": "needs_human_review",
                            "point_quality": "vista_point_inside_seed_bbox",
                            "gate_safety": "passed_allowed_dry_run",
                            "trace_path": "region-2-trace.json",
                            "real_clicks": 0,
                            "promotion_policy": {
                                "promotable_to_pathgraph_candidate_review": False,
                                "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
                            },
                        },
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = merge_targeted_rerun_into_fusion_status(base_status_path=base, rerun_report_path=rerun, out_dir=tmp_path / "out")

    corrected = json.loads(Path(result["corrected_status_path"]).read_text(encoding="utf-8"))
    assert corrected["summary"]["total_locator_cards"] == 5
    assert corrected["summary"]["calibrated_cases"] == 4
    assert corrected["summary"]["uncalibrated_locator_cards"] == 1
    assert corrected["summary"]["calibration_coverage_rate"] == 0.8
    assert corrected["calibration_backlog"]["summary"]["uncalibrated_locator_cards"] == 1
    assert corrected["calibration_backlog"]["summary"]["ready_for_execute_dry_run"] == 0
    assert corrected["calibration_backlog"]["summary"]["review_before_calibration"] == 1
    assert [item["region_no"] for item in corrected["calibration_backlog"]["items"]] == [3]
    assert corrected["calibration_batch_plan"]["ready_region_numbers"] == []
    assert corrected["calibration_batch_plan"]["review_blocked_region_numbers"] == [3]
    assert corrected["pathgraph_preflight_plan"]["summary"]["pending_calibration_ready_count"] == 0
    assert corrected["pathgraph_preflight_plan"]["summary"]["pending_calibration_review_count"] == 1
    assert corrected["pathgraph_preflight_plan"]["pending_calibration_batch"]["ready_region_numbers"] == []
    assert corrected["targeted_rerun_correction"]["pending_ready_region_numbers_after_merge"] == []
    assert corrected["targeted_rerun_correction"]["pending_review_blocked_region_numbers_after_merge"] == [3]
    assert corrected["precise_understanding_readiness_summary"]["readiness_status"] == "needs_pending_calibration"
    assert corrected["precise_understanding_readiness_summary"]["calibration_coverage_rate"] == 0.8
    assert corrected["execute_binding_enabled"] is False
    assert corrected["artifact_is_authorization"] is False
