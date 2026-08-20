from __future__ import annotations

import json
from pathlib import Path

from scripts.attach_learn_precise_understanding_fusion_status import attach_fusion_status_to_learning_trial


def test_attach_fusion_status_to_learning_trial_writes_page_detail_audit(tmp_path: Path) -> None:
    trial = tmp_path / "actual_parser_output_v1.json"
    status = tmp_path / "fusion_status.json"
    diagnosis = tmp_path / "gate_diagnosis.json"
    queue = tmp_path / "pathgraph_review_queue.json"
    preflight = tmp_path / "pathgraph_preflight_plan.json"
    proposal = tmp_path / "review_patch_proposal.json"
    batch_plan = tmp_path / "numbered_region_calibration_batch_plan.json"
    handoff = tmp_path / "learn_fusion_calibration_handoff_report.json"
    acceptance = tmp_path / "learn_fusion_calibration_batch_acceptance_report.json"
    consistency = tmp_path / "learn_fusion_handoff_consistency_report.json"
    runbook = tmp_path / "learn_fusion_model_start_runbook.json"
    trial.write_text(
        json.dumps(
            {
                "contract_version": "actual_parser_output_v1",
                "learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "SEEK results",
                    "page_details": {
                        "contract_version": "learning_draft_page_details_v1",
                        "pipeline_audit": {
                            "contract_version": "learning_draft_pipeline_audit_v1",
                            "layout_cleanup": {"output_count": 2},
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    status.write_text(
        json.dumps(
            {
                "contract_version": "learn_precise_understanding_fusion_status_report_v1",
                "source_report_path": "numbered_region_calibration_report.json",
                "full_screen_understanding_overlay_path": "full-overlay.png",
                "compiled_overlay_path": "overlay.png",
                "display_readiness": {"status": "display_ready", "item_count": 10},
                "pathgraph_preparation": {
                    "status": "blocked_from_pathgraph_candidate_review",
                    "promotable_item_count": 0,
                    "blocked_item_count": 10,
                    "required_next_evidence": ["same_screenshot_ocr_uia_or_calibrated_support"],
                },
                "summary": {"attempted": 10, "needs_human_review": 6, "safe_intercepts": 4, "real_clicks": 0},
                "calibration_status_counts": {"needs_human_review": 6, "gate_rejected": 4},
                "point_quality_counts": {"vista_point_inside_seed_bbox": 9, "vista_point_outside_seed_bbox": 1},
                "gate_safety_counts": {"passed_allowed_dry_run": 6, "passed_rejected": 4},
                "block_reason_counts": {"semantic_only_requires_cross_evidence_or_human_review": 10},
                "calibration_backlog": {
                    "contract_version": "numbered_region_calibration_backlog_v1",
                    "summary": {"uncalibrated_locator_cards": 8, "ready_for_execute_dry_run": 6},
                    "items": [{"region_no": 1, "source_item_id": "c1", "ready_for_execute_dry_run": True}],
                },
                "items": [{"region_no": 1, "source_item_id": "c1", "label": "Search input"}],
                "precise_understanding_readiness_summary": {
                    "contract_version": "precise_understanding_readiness_summary_v1",
                    "readiness_status": "needs_pending_calibration",
                    "total_locator_cards": 10,
                    "calibrated_cases": 2,
                    "uncalibrated_locator_cards": 8,
                    "calibration_coverage_rate": 0.2,
                    "pending_calibration_ready_count": 6,
                    "pending_calibration_review_count": 2,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "targeted_rerun_correction": {
                    "contract_version": "learn_fusion_targeted_rerun_correction_v1",
                    "updated_item_count": 2,
                    "updated_region_numbers": [4, 5],
                    "updated_source_item_ids": ["c4", "c5"],
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "safety": {"real_clicks": 0},
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    diagnosis.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_gate_rejection_diagnosis_report_v1",
                "summary": {
                    "attempted": 2,
                    "classification_counts": {
                        "missing_open_detail_semantic_action": 1,
                        "non_actionable_region_correctly_rejected": 1,
                    },
                    "safe_intercepts": 2,
                    "real_clicks": 0,
                },
                "cases": [
                    {"region_no": 4, "classification": "missing_open_detail_semantic_action"},
                    {"region_no": 7, "classification": "non_actionable_region_correctly_rejected"},
                ],
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    queue.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_pathgraph_review_queue_v1",
                "summary": {
                    "attempted": 10,
                    "open_detail_candidate_review": 2,
                    "same_screen_action_review": 5,
                    "geometry_review_required": 1,
                    "blocked_non_action": 2,
                    "real_clicks": 0,
                },
                "queue_items": [
                    {"region_no": 4, "review_bucket": "open_detail_candidate_review"},
                    {"region_no": 7, "review_bucket": "blocked_non_action"},
                ],
                "display_only": True,
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
                "contract_version": "learn_fusion_pathgraph_preflight_plan_v1",
                "summary": {
                    "open_detail_transition_candidates": 2,
                    "same_screen_action_candidates": 5,
                    "geometry_blockers": 1,
                    "non_action_blockers": 2,
                    "pending_calibration_ready_count": 6,
                    "pending_calibration_review_count": 2,
                    "ready_for_runtime_pathgraph_promotion": False,
                    "real_clicks": 0,
                },
                "pending_calibration_batch": {
                    "contract_version": "learn_fusion_pathgraph_pending_calibration_batch_v1",
                    "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "review_blocked_region_numbers": [7, 10],
                    "run_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2,3,6,8,9",
                    "command_executes_now": False,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "proposed_transitions": [
                    {"transition_type": "open_detail", "source_region_no": 4, "no_dispatch": True}
                ],
                "review_action_items": [{"region_no": 3, "review_bucket": "same_screen_action_review"}],
                "blocked_items": [{"region_no": 7, "review_bucket": "blocked_non_action"}],
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    proposal.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_review_patch_proposal_v1",
                "summary": {
                    "state_additions": 1,
                    "action_template_additions": 2,
                    "transition_additions": 2,
                    "blockers": 3,
                    "verification_rules": 2,
                    "review_status": "needs_human_review",
                    "ready_for_runtime_pathgraph_promotion": False,
                },
                "review_patch": {
                    "review_status": "needs_human_review",
                    "state_additions": [{"state_id": "model_detail_view"}],
                    "action_template_additions": [{"action_template_id": "a_open_detail"}],
                    "transition_additions": [{"transition_id": "t_open_detail"}],
                },
                "display_only": True,
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
                "contract_version": "numbered_region_calibration_batch_plan_v1",
                "summary": {
                    "ready_for_execute_dry_run": 6,
                    "review_before_calibration": 2,
                    "real_clicks": 0,
                    "display_only": True,
                    "execute_binding_enabled": False,
                },
                "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                "review_blocked_region_numbers": [7, 10],
                "run_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2,3,6,8,9",
                "command_executes_now": False,
                "post_batch_refresh_command_preview": "uv run python scripts\\refresh_learn_fusion_after_calibration_batch.py --trial trial.json",
                "post_batch_refresh_command_executes_now": False,
                "post_batch_refresh_requires_completed_batch": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    handoff.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_calibration_handoff_report_v1",
                "handoff_status": "ready_for_explicit_model_start",
                "safe_to_start_after_user_approval": True,
                "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                "review_blocked_region_numbers": [7, 10],
                "future_outputs": {
                    "rerun_report_status": "awaiting_future_calibration_output",
                    "post_batch_refresh_requires_completed_batch": True,
                },
                "blockers": [],
                "warnings": [],
                "safety": {
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                    "final_submit_forbidden": True,
                    "real_clicks": 0,
                    "live_fill": False,
                    "live_submit": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    acceptance.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_calibration_batch_acceptance_report_v1",
                "acceptance_status": "awaiting_future_calibration_output",
                "ready_for_post_batch_refresh": False,
                "coverage": {
                    "expected_ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "accepted_region_numbers": [],
                    "missing_ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "unexpected_region_numbers": [],
                    "review_blocked_region_numbers_in_rerun": [],
                },
                "safety": {
                    "real_clicks": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                    "final_submit_forbidden": True,
                },
                "checks": {"rerun_report_exists": False},
                "blockers": ["rerun_report_missing"],
                "warnings": [],
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    consistency.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_handoff_consistency_report_v1",
                "consistency_status": "ready_for_explicit_model_start",
                "summary": {
                    "readiness_status": "needs_pending_calibration",
                    "handoff_status": "ready_for_explicit_model_start",
                    "acceptance_status": "awaiting_future_calibration_output",
                    "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "post_batch_refresh_has_batch_plan": True,
                    "refresh_blocks_before_future_rerun": True,
                },
                "checks": {
                    "plan_post_batch_refresh_has_batch_plan": True,
                    "draft_post_batch_refresh_has_batch_plan": True,
                    "handoff_post_batch_refresh_has_batch_plan": True,
                    "refresh_blocks_before_future_rerun": True,
                },
                "blockers": [],
                "safety": {
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "runtime_pathgraph_promotion": False,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    runbook.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_model_start_runbook_v1",
                "runbook_status": "awaiting_explicit_model_start_approval",
                "approval_required": True,
                "may_start_model_after_user_approval": True,
                "may_run_calibration_batch_now": False,
                "next_manual_action": "ask_user_to_approve_model_start_for_ready_regions",
                "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                "review_blocked_region_numbers": [7, 10],
                "guards": {
                    "post_batch_refresh_has_batch_plan": True,
                    "prebatch_refresh_blocks_before_future_rerun": True,
                    "acceptance_required_before_refresh": True,
                    "accepted_for_post_batch_refresh": False,
                },
                "safety": {
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "display_only_until_user_approval": True,
                },
                "blockers": [],
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = attach_fusion_status_to_learning_trial(
        trial_path=trial,
        fusion_status_path=status,
        gate_diagnosis_path=diagnosis,
        pathgraph_review_queue_path=queue,
        pathgraph_preflight_plan_path=preflight,
        review_patch_proposal_path=proposal,
        calibration_batch_plan_path=batch_plan,
        calibration_handoff_report_path=handoff,
        calibration_batch_acceptance_report_path=acceptance,
        calibration_handoff_consistency_report_path=consistency,
        model_start_runbook_path=runbook,
        out_dir=tmp_path / "out",
    )

    output = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
    attached = output["learning_draft"]["page_details"]["pipeline_audit"]["precise_understanding_fusion_status"]
    assert result["contract_version"] == "learn_precise_understanding_fusion_status_attach_result_v1"
    assert attached["contract_version"] == "learning_draft_precise_understanding_fusion_status_v1"
    assert attached["full_screen_understanding_overlay_path"] == "full-overlay.png"
    assert attached["display_readiness"]["status"] == "display_ready"
    assert attached["pathgraph_preparation"]["status"] == "blocked_from_pathgraph_candidate_review"
    assert attached["summary"]["attempted"] == 10
    assert attached["calibration_status_counts"] == {"gate_rejected": 4, "needs_human_review": 6}
    assert attached["calibration_backlog"]["summary"]["uncalibrated_locator_cards"] == 8
    assert attached["calibration_backlog"]["items"][0]["region_no"] == 1
    assert attached["items"][0]["label"] == "Search input"
    assert attached["precise_understanding_readiness_summary"]["readiness_status"] == "needs_pending_calibration"
    assert attached["precise_understanding_readiness_summary"]["calibration_coverage_rate"] == 0.2
    assert attached["targeted_rerun_correction"]["updated_region_numbers"] == [4, 5]
    assert attached["targeted_rerun_correction"]["execute_binding_enabled"] is False
    assert attached["targeted_rerun_correction"]["artifact_is_authorization"] is False
    assert attached["gate_rejection_diagnosis"]["summary"]["classification_counts"] == {
        "missing_open_detail_semantic_action": 1,
        "non_actionable_region_correctly_rejected": 1,
    }
    assert attached["pathgraph_review_queue"]["summary"]["open_detail_candidate_review"] == 2
    assert attached["pathgraph_review_queue"]["summary"]["blocked_non_action"] == 2
    assert attached["pathgraph_review_queue"]["execute_binding_enabled"] is False
    assert attached["pathgraph_review_queue"]["artifact_is_authorization"] is False
    assert attached["pathgraph_preflight_plan"]["summary"]["open_detail_transition_candidates"] == 2
    assert attached["pathgraph_preflight_plan"]["summary"]["pending_calibration_ready_count"] == 6
    assert attached["pathgraph_preflight_plan"]["summary"]["ready_for_runtime_pathgraph_promotion"] is False
    assert attached["pathgraph_preflight_plan"]["pending_calibration_batch"]["ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert attached["pathgraph_preflight_plan"]["pending_calibration_batch"]["review_blocked_region_numbers"] == [7, 10]
    assert attached["pathgraph_preflight_plan"]["pending_calibration_batch"]["command_executes_now"] is False
    assert attached["pathgraph_preflight_plan"]["execute_binding_enabled"] is False
    assert attached["pathgraph_preflight_plan"]["artifact_is_authorization"] is False
    assert attached["review_patch_proposal"]["summary"]["action_template_additions"] == 2
    assert attached["review_patch_proposal"]["summary"]["transition_additions"] == 2
    assert attached["review_patch_proposal"]["execute_binding_enabled"] is False
    assert attached["review_patch_proposal"]["artifact_is_authorization"] is False
    assert attached["calibration_batch_plan"]["summary"]["ready_for_execute_dry_run"] == 6
    assert attached["calibration_batch_plan"]["ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert attached["calibration_batch_plan"]["review_blocked_region_numbers"] == [7, 10]
    assert attached["calibration_batch_plan"]["command_executes_now"] is False
    assert "refresh_learn_fusion_after_calibration_batch.py" in attached["calibration_batch_plan"]["post_batch_refresh_command_preview"]
    assert attached["calibration_batch_plan"]["post_batch_refresh_command_executes_now"] is False
    assert attached["calibration_batch_plan"]["post_batch_refresh_requires_completed_batch"] is True
    assert attached["calibration_batch_plan"]["execute_binding_enabled"] is False
    assert attached["calibration_batch_plan"]["artifact_is_authorization"] is False
    assert attached["calibration_handoff_report"]["handoff_status"] == "ready_for_explicit_model_start"
    assert attached["calibration_handoff_report"]["safe_to_start_after_user_approval"] is True
    assert attached["calibration_handoff_report"]["ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert attached["calibration_handoff_report"]["future_outputs"]["rerun_report_status"] == "awaiting_future_calibration_output"
    assert attached["calibration_handoff_report"]["safety"]["execute_binding_enabled"] is False
    assert attached["calibration_handoff_report"]["safety"]["artifact_is_authorization"] is False
    assert attached["calibration_handoff_report"]["safety"]["real_clicks"] == 0
    assert attached["calibration_batch_acceptance_report"]["acceptance_status"] == "awaiting_future_calibration_output"
    assert attached["calibration_batch_acceptance_report"]["ready_for_post_batch_refresh"] is False
    assert attached["calibration_batch_acceptance_report"]["coverage"]["expected_ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert attached["calibration_batch_acceptance_report"]["blockers"] == ["rerun_report_missing"]
    assert attached["calibration_batch_acceptance_report"]["safety"]["real_clicks"] == 0
    assert attached["calibration_batch_acceptance_report"]["execute_binding_enabled"] is False
    assert attached["calibration_batch_acceptance_report"]["artifact_is_authorization"] is False
    assert attached["calibration_handoff_consistency_report"]["consistency_status"] == "ready_for_explicit_model_start"
    assert attached["calibration_handoff_consistency_report"]["summary"]["post_batch_refresh_has_batch_plan"] is True
    assert attached["calibration_handoff_consistency_report"]["summary"]["refresh_blocks_before_future_rerun"] is True
    assert attached["calibration_handoff_consistency_report"]["blockers"] == []
    assert attached["calibration_handoff_consistency_report"]["safety"]["live_clicks"] == 0
    assert attached["calibration_handoff_consistency_report"]["execute_binding_enabled"] is False
    assert attached["calibration_handoff_consistency_report"]["artifact_is_authorization"] is False
    assert attached["model_start_runbook"]["runbook_status"] == "awaiting_explicit_model_start_approval"
    assert attached["model_start_runbook"]["may_start_model_after_user_approval"] is True
    assert attached["model_start_runbook"]["may_run_calibration_batch_now"] is False
    assert attached["model_start_runbook"]["ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert attached["model_start_runbook"]["guards"]["post_batch_refresh_has_batch_plan"] is True
    assert attached["model_start_runbook"]["safety"]["live_clicks"] == 0
    assert attached["model_start_runbook"]["execute_binding_enabled"] is False
    assert attached["model_start_runbook"]["artifact_is_authorization"] is False
    assert attached["execute_binding_enabled"] is False
    assert attached["artifact_is_authorization"] is False
    assert output["precise_understanding_fusion_status"] == attached
    assert Path(result["attach_report_path"]).exists()


def test_attach_fusion_status_derives_display_and_pathgraph_status_from_evidence(tmp_path: Path) -> None:
    trial = tmp_path / "trial.json"
    status = tmp_path / "fusion_status.json"
    queue = tmp_path / "queue.json"
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
    status.write_text(
        json.dumps(
            {
                "contract_version": "learn_full_screen_understanding_backlog_triage_preview_v1",
                "full_screen_understanding_overlay_path": "full-overlay.png",
                "summary": {
                    "total_locator_cards": 10,
                    "calibrated_cases": 2,
                    "uncalibrated_locator_cards": 8,
                },
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    queue.write_text(
        json.dumps(
            {
                "summary": {
                    "open_detail_candidate_review": 2,
                    "same_screen_action_review": 5,
                    "geometry_review_required": 1,
                    "blocked_non_action": 2,
                    "real_clicks": 0,
                },
                "queue_items": [{"region_no": 4}, {"region_no": 7}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = attach_fusion_status_to_learning_trial(
        trial_path=trial,
        fusion_status_path=status,
        pathgraph_review_queue_path=queue,
        out_dir=tmp_path / "out",
    )

    output = json.loads(Path(result["output_path"]).read_text(encoding="utf-8"))
    attached = output["learning_draft"]["page_details"]["pipeline_audit"]["precise_understanding_fusion_status"]
    assert attached["display_readiness"]["status"] == "display_ready"
    assert attached["display_readiness"]["full_screen_overlay_available"] is True
    assert attached["pathgraph_preparation"]["status"] == "blocked_from_pathgraph_candidate_review"
    assert attached["pathgraph_preparation"]["blocked_item_count"] == 2
    assert attached["pathgraph_preparation"]["promotable_item_count"] == 0
    assert attached["execute_binding_enabled"] is False
    assert attached["artifact_is_authorization"] is False
