from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_precise_understanding_fusion_status import report_fusion_status


def test_report_fusion_status_summarizes_display_and_pathgraph_readiness(tmp_path: Path) -> None:
    source_report = tmp_path / "numbered_region_calibration_report.json"
    overlay = tmp_path / "overlay.png"
    full_overlay = tmp_path / "full-overlay.png"
    overlay.write_bytes(b"png")
    full_overlay.write_bytes(b"png")
    source_report.write_text(
        json.dumps(
            {
                "contract_version": "numbered_region_calibration_probe_v1",
                "screenshot_path": "screen.png",
                "full_screen_understanding_overlay_path": str(full_overlay),
                "compiled_overlay_path": str(overlay),
                "calibration_backlog": {
                    "contract_version": "numbered_region_calibration_backlog_v1",
                    "summary": {
                        "uncalibrated_locator_cards": 2,
                        "ready_for_execute_dry_run": 1,
                        "review_before_calibration": 1,
                        "display_only": True,
                        "execute_binding_enabled": False,
                    },
                    "items": [
                        {
                            "region_no": 4,
                            "label": "Location filter",
                            "suggested_semantic_action": "fill_field",
                            "execute_binding_enabled": False,
                        }
                    ],
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "summary": {"attempted": 3, "passed": 1, "needs_human_review": 1, "gate_rejected": 1, "real_clicks": 0},
                "fused_precise_understanding": {
                    "contract_version": "learn_precise_understanding_fusion_v1",
                    "summary": {
                        "attempted": 3,
                        "promotable_to_pathgraph_candidate_review": 1,
                        "needs_human_review": 1,
                        "safe_intercepts": 1,
                        "failed": 0,
                        "real_clicks": 0,
                    },
                    "items": [
                        {
                            "region_no": 1,
                            "label": "Search keyword field",
                            "role": "input",
                            "evidence_level": "uia_control",
                            "calibration_status": "passed",
                            "point_quality": "vista_point_inside_seed_bbox",
                            "gate_safety": "passed_allowed_dry_run",
                            "promotion_policy": {
                                "promotable_to_pathgraph_candidate_review": True,
                                "block_reason": "",
                            },
                            "trace_path": "trace-1.json",
                            "recognition_plan_trace_path": "plan-1.json",
                            "overlay_path": "overlay-1.png",
                            "real_clicks": 0,
                        },
                        {
                            "region_no": 2,
                            "label": "Job card",
                            "role": "card",
                            "evidence_level": "semantic_region_only",
                            "calibration_status": "needs_human_review",
                            "point_quality": "vista_point_inside_seed_bbox",
                            "gate_safety": "passed_allowed_dry_run",
                            "promotion_policy": {
                                "promotable_to_pathgraph_candidate_review": False,
                                "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
                            },
                            "real_clicks": 0,
                        },
                        {
                            "region_no": 3,
                            "label": "Detail placeholder",
                            "role": "region",
                            "evidence_level": "semantic_region_only",
                            "calibration_status": "gate_rejected",
                            "point_quality": "vista_point_inside_seed_bbox",
                            "gate_safety": "passed_rejected",
                            "promotion_policy": {
                                "promotable_to_pathgraph_candidate_review": False,
                                "block_reason": "pre_click_gate_rejected",
                            },
                            "real_clicks": 0,
                        },
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = report_fusion_status(report_path=source_report, out_dir=tmp_path / "status")

    assert result["contract_version"] == "learn_precise_understanding_fusion_status_report_v1"
    assert result["display_readiness"]["status"] == "display_ready"
    assert result["display_readiness"]["overlay_available"] is True
    assert result["display_readiness"]["full_screen_overlay_available"] is True
    assert result["full_screen_understanding_overlay_path"] == str(full_overlay)
    assert result["calibration_backlog"]["summary"]["uncalibrated_locator_cards"] == 2
    assert result["calibration_backlog"]["summary"]["ready_for_execute_dry_run"] == 1
    assert result["calibration_backlog"]["summary"]["review_before_calibration"] == 1
    assert result["calibration_backlog"]["items"][0]["suggested_semantic_action"] == "fill_field"
    assert result["calibration_backlog"]["execute_binding_enabled"] is False
    assert result["pathgraph_preparation"]["status"] == "partially_ready_for_human_review"
    assert result["pathgraph_preparation"]["promotable_item_count"] == 1
    assert result["pathgraph_preparation"]["blocked_item_count"] == 2
    assert result["calibration_status_counts"] == {"gate_rejected": 1, "needs_human_review": 1, "passed": 1}
    assert result["gate_safety_counts"] == {"passed_allowed_dry_run": 2, "passed_rejected": 1}
    assert result["point_quality_counts"] == {"vista_point_inside_seed_bbox": 3}
    assert "review_gate_rejection_reason_before_pathgraph_wiring" in result["pathgraph_preparation"]["required_next_evidence"]
    assert result["block_reason_counts"] == {
        "pre_click_gate_rejected": 1,
        "semantic_only_requires_cross_evidence_or_human_review": 1,
    }
    assert result["safety"]["real_clicks"] == 0
    assert result["execute_binding_enabled"] is False
    assert result["artifact_is_authorization"] is False
    assert Path(result["report_path"]).exists()
