from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_fusion_current_evidence_packet import report_learn_fusion_current_evidence_packet


def test_current_evidence_packet_summarizes_precise_understanding_and_pathgraph(tmp_path: Path) -> None:
    draft_path = tmp_path / "artifacts" / "learning-draft-review" / "sample" / "actual_parser_output_with_fusion_status.json"
    candidate_dir = tmp_path / "artifacts" / "learning-draft-review" / "sample" / "pathgraph_candidate"
    candidate_path = candidate_dir / "pathgraph_candidate.json"
    validation_path = candidate_dir / "promotion_validation_report.json"
    integration_path = candidate_dir / "learn_fusion_pathgraph_integration_readiness_report.json"
    draft_path.parent.mkdir(parents=True)
    candidate_dir.mkdir(parents=True)
    draft_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_trial_result_v1",
                "learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "SEEK results full-screen understanding.",
                    "state_guess": "seek_results",
                    "page_details": {
                        "pipeline_audit": {
                            "precise_understanding_fusion_status": {
                                "contract_version": "learning_draft_precise_understanding_fusion_status_v1",
                                "full_screen_understanding_overlay_path": "artifacts/overlays/full.png",
                                "compiled_overlay_path": "artifacts/overlays/compiled.png",
                                "display_readiness": {"status": "display_ready"},
                                "summary": {
                                    "total_locator_cards": 10,
                                    "calibrated_cases": 2,
                                    "uncalibrated_locator_cards": 8,
                                    "calibration_coverage_rate": 0.2,
                                    "real_clicks": 0,
                                },
                                "calibration_backlog": {
                                    "summary": {
                                        "uncalibrated_locator_cards": 8,
                                        "ready_for_execute_dry_run": 6,
                                        "review_before_calibration": 2,
                                    },
                                    "items": [{"region_no": 1}, {"region_no": 2}],
                                },
                                "calibration_batch_plan": {
                                    "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                                    "review_blocked_region_numbers": [7, 10],
                                    "command_executes_now": False,
                                    "post_batch_refresh_command_executes_now": False,
                                },
                                "pathgraph_preparation": {"status": "blocked_from_pathgraph_candidate_review"},
                                "execute_binding_enabled": False,
                                "artifact_is_authorization": False,
                            }
                        }
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    validation_path.write_text(
        json.dumps(
            {
                "contract_version": "pathgraph_candidate_validation_report_v1",
                "validation_status": "blocked_pending_calibration",
                "summary": {"readiness_status": "blocked_from_promotion_review"},
                "safety": {"execute_binding_enabled": False, "artifact_is_authorization": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(
            {
                "contract_version": "pathgraph_candidate_v1",
                "reviewed_template_candidate_path": str(draft_path.relative_to(tmp_path)),
                "validation_report_path": str(validation_path.relative_to(tmp_path)),
                "validation_status": "blocked_pending_calibration",
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    integration_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_pathgraph_integration_readiness_report_v1",
                "integration_readiness_status": "blocked_pending_calibration",
                "report_path": str(integration_path.resolve()),
                "ready_for_audited_pathgraph_review": False,
                "ready_for_runtime_pathgraph_promotion": False,
                "blockers": ["pending_calibration_required"],
                "next_required_steps": ["run_approved_numbered_region_calibration_batch"],
                "safety": {"execute_binding_enabled": False, "artifact_is_authorization": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    packet = report_learn_fusion_current_evidence_packet(
        source_path=candidate_path.relative_to(tmp_path),
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    report = json.loads(Path(packet["report_path"]).read_text(encoding="utf-8"))
    assert report["contract_version"] == "learn_fusion_current_evidence_packet_v1"
    assert report["screen_summary"] == "SEEK results full-screen understanding."
    assert report["full_screen_understanding"]["overlay_path"] == "artifacts/overlays/full.png"
    assert report["full_screen_understanding"]["fusion_summary"]["calibration_coverage_rate"] == 0.2
    assert report["calibration"]["backlog_item_count"] == 2
    assert report["calibration"]["batch_ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert report["calibration"]["batch_command_executes_now"] is False
    assert report["pathgraph"]["candidate_path"] == str(candidate_path.relative_to(tmp_path)).replace("\\", "/")
    assert report["pathgraph"]["integration_readiness_status"] == "blocked_pending_calibration"
    assert report["pathgraph"]["integration_report_path"] == str(integration_path.relative_to(tmp_path)).replace("\\", "/")
    assert report["pathgraph"]["ready_for_runtime_pathgraph_promotion_after_integration"] is False
    assert report["pathgraph"]["blockers"] == ["pending_calibration_required"]
    assert report["next_required_steps"][0] == "run_approved_numbered_region_calibration_batch"
    assert report["safety"]["model_started"] is False
    assert report["safety"]["live_clicks"] == 0
    assert report["safety"]["execute_binding_enabled"] is False
    assert report["safety"]["runtime_pathgraph_promotion"] is False
