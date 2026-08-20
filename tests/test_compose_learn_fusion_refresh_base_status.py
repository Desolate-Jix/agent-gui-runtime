from __future__ import annotations

import json
from pathlib import Path

from scripts.compose_learn_fusion_refresh_base_status import compose_learn_fusion_refresh_base_status
from scripts.refresh_learn_fusion_after_calibration_batch import refresh_learn_fusion_after_calibration_batch


def test_compose_refresh_base_preserves_items_backlog_and_pending_for_post_batch_refresh(tmp_path: Path) -> None:
    corrected_status = tmp_path / "corrected_status.json"
    full_screen_report = tmp_path / "full_screen_report.json"
    batch_plan = tmp_path / "batch_plan.json"
    preflight = tmp_path / "preflight.json"
    trial = tmp_path / "trial.json"
    rerun = tmp_path / "rerun.json"
    corrected_status.write_text(
        json.dumps(
            {
                "contract_version": "learn_precise_understanding_fusion_status_report_v1",
                "summary": {"attempted": 5, "needs_human_review": 2, "safe_intercepts": 0, "real_clicks": 0},
                "pathgraph_preparation": {"status": "blocked_from_pathgraph_candidate_review"},
                "items": [
                    _item(1, "c1", "pending_calibration"),
                    _item(2, "c2", "pending_calibration"),
                    _item(3, "c3", "pending_calibration"),
                    _item(4, "c4", "needs_human_review"),
                    _item(5, "c5", "needs_human_review"),
                ],
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    full_screen_report.write_text(
        json.dumps(
            {
                "contract_version": "learn_full_screen_understanding_backlog_triage_preview_v1",
                "full_screen_understanding_overlay_path": "full-overlay.png",
                "summary": {
                    "total_locator_cards": 5,
                    "calibrated_cases": 2,
                    "uncalibrated_locator_cards": 3,
                    "display_only": True,
                    "execute_binding_enabled": False,
                },
                "calibration_backlog": {
                    "summary": {"uncalibrated_locator_cards": 3, "ready_for_execute_dry_run": 2, "review_before_calibration": 1},
                    "items": [
                        {"region_no": 1, "source_item_id": "c1", "ready_for_execute_dry_run": True},
                        {"region_no": 2, "source_item_id": "c2", "ready_for_execute_dry_run": True},
                        {"region_no": 3, "source_item_id": "c3", "ready_for_execute_dry_run": False},
                    ],
                },
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
                "summary": {"ready_for_execute_dry_run": 2, "review_before_calibration": 1, "real_clicks": 0},
                "ready_region_numbers": [1, 2],
                "review_blocked_region_numbers": [3],
                "run_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2",
                "post_batch_refresh_command_preview": "uv run python scripts\\refresh_learn_fusion_after_calibration_batch.py",
                "post_batch_refresh_command_executes_now": False,
                "post_batch_refresh_requires_completed_batch": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    preflight.write_text(
        json.dumps(
            {
                "summary": {
                    "pending_calibration_ready_count": 2,
                    "pending_calibration_review_count": 1,
                    "ready_for_runtime_pathgraph_promotion": False,
                },
                "pending_calibration_batch": {
                    "ready_region_numbers": [1, 2],
                    "review_blocked_region_numbers": [3],
                    "command_executes_now": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    trial.write_text(
        json.dumps(
            {
                "learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "page_details": {"pipeline_audit": {}},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rerun.write_text(
        json.dumps(
            {
                "fused_precise_understanding": {
                    "items": [
                        _rerun_item(1, "c1"),
                        _rerun_item(2, "c2"),
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    compose_result = compose_learn_fusion_refresh_base_status(
        corrected_status_path=corrected_status,
        full_screen_report_path=full_screen_report,
        calibration_batch_plan_path=batch_plan,
        pathgraph_preflight_plan_path=preflight,
        out_dir=tmp_path / "compose",
    )

    refresh_result = refresh_learn_fusion_after_calibration_batch(
        trial_path=trial,
        base_status_path=compose_result["refresh_base_status_path"],
        rerun_report_path=rerun,
        out_dir=tmp_path / "refresh",
    )

    base_status = json.loads(Path(compose_result["refresh_base_status_path"]).read_text(encoding="utf-8"))
    assert base_status["summary"]["calibration_coverage_rate"] == 0.4
    assert base_status["calibration_backlog"]["summary"]["uncalibrated_locator_cards"] == 3
    assert base_status["calibration_batch_plan"]["ready_region_numbers"] == [1, 2]
    assert base_status["pathgraph_preflight_plan"]["summary"]["pending_calibration_ready_count"] == 2
    assert base_status["execute_binding_enabled"] is False
    assert base_status["artifact_is_authorization"] is False

    refreshed = json.loads(Path(refresh_result["corrected_status_path"]).read_text(encoding="utf-8"))
    assert refreshed["summary"]["calibrated_cases"] == 4
    assert refreshed["summary"]["uncalibrated_locator_cards"] == 1
    assert refreshed["summary"]["calibration_coverage_rate"] == 0.8
    assert refreshed["calibration_batch_plan"]["ready_region_numbers"] == []
    assert refreshed["pathgraph_preflight_plan"]["summary"]["pending_calibration_ready_count"] == 0
    assert refreshed["pathgraph_preflight_plan"]["summary"]["pending_calibration_review_count"] == 1


def _item(region_no: int, source_item_id: str, calibration_status: str) -> dict[str, object]:
    return {
        "region_no": region_no,
        "source_item_id": source_item_id,
        "label": f"Region {region_no}",
        "calibration_status": calibration_status,
        "real_clicks": 0,
        "promotion_policy": {
            "promotable_to_pathgraph_candidate_review": False,
            "block_reason": calibration_status,
        },
    }


def _rerun_item(region_no: int, source_item_id: str) -> dict[str, object]:
    item = _item(region_no, source_item_id, "needs_human_review")
    item["point_quality"] = "vista_point_inside_seed_bbox"
    item["gate_safety"] = "passed_allowed_dry_run"
    item["promotion_policy"] = {
        "promotable_to_pathgraph_candidate_review": False,
        "block_reason": "semantic_only_requires_cross_evidence_or_human_review",
    }
    return item
