from __future__ import annotations

import json
from pathlib import Path

from app.learn.draft_review import load_learning_draft_review
from scripts.build_learn_precise_understanding_candidate import build_learn_precise_understanding_candidate


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_precise_understanding_candidate_compiles_backlog_and_dry_run_evidence(tmp_path: Path) -> None:
    screenshot = tmp_path / "artifacts" / "screen.png"
    full_overlay = tmp_path / "logs" / "full_overlay.png"
    compiled_overlay = tmp_path / "logs" / "compiled_overlay.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    full_overlay.parent.mkdir(parents=True, exist_ok=True)
    screenshot.write_bytes(b"screen")
    full_overlay.write_bytes(b"full")
    compiled_overlay.write_bytes(b"compiled")
    calibration_report = _write_json(
        tmp_path / "logs" / "numbered_region_calibration_report.json",
        {
            "contract_version": "numbered_region_calibration_probe_v1",
            "screenshot_path": str(screenshot.relative_to(tmp_path)),
            "summary": {"attempted": 3, "real_clicks": 0},
            "fused_precise_understanding": {
                "contract_version": "learn_precise_understanding_fusion_v1",
                "items": [
                    {
                        "region_no": 1,
                        "source_item_id": "c1",
                        "label": "Search input",
                        "role": "input",
                        "rough_bbox_hint": {"x": 10, "y": 20, "w": 120, "h": 30},
                        "vista_point": {"x": 30, "y": 30},
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
                        "region_no": 4,
                        "source_item_id": "c4",
                        "label": "Job card",
                        "role": "card",
                        "rough_bbox_hint": {"x": 20, "y": 80, "w": 160, "h": 80},
                        "vista_point": {"x": 50, "y": 100},
                        "calibration_status": "passed",
                        "point_quality": "vista_point_inside_seed_bbox",
                        "gate_safety": "passed_allowed_dry_run",
                        "promotion_policy": {
                            "promotable_to_pathgraph_candidate_review": True,
                            "block_reason": "",
                        },
                        "real_clicks": 0,
                    },
                    {
                        "region_no": 7,
                        "source_item_id": "c7",
                        "label": "Placeholder",
                        "role": "region",
                        "rough_bbox_hint": {"x": 200, "y": 80, "w": 100, "h": 80},
                        "vista_point": {"x": 220, "y": 100},
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
    )
    reviewed = _write_json(
        tmp_path / "artifacts" / "candidate" / "reviewed_template_candidate.json",
        {
            "contract_version": "reviewed_template_candidate_v1",
            "draft": {
                "contract_version": "learning_template_draft_v1",
                "screen_summary": "SEEK results.",
                "state_guess": "seek_results",
                "page_details": {
                    "pipeline_audit": {
                        "precise_understanding_fusion_status": {
                            "full_screen_understanding_overlay_path": str(full_overlay.relative_to(tmp_path)),
                            "compiled_overlay_path": str(compiled_overlay.relative_to(tmp_path)),
                            "screenshot_path": str(screenshot.relative_to(tmp_path)),
                            "source_calibration_report_path": str(calibration_report.relative_to(tmp_path)),
                            "summary": {
                                "total_locator_cards": 4,
                                "calibrated_cases": 2,
                                "uncalibrated_locator_cards": 2,
                                "calibration_coverage_rate": 0.5,
                                "real_clicks": 0,
                            },
                            "calibration_backlog": {
                                "summary": {"uncalibrated_locator_cards": 2},
                                "items": [
                                    {
                                        "region_no": 1,
                                        "source_item_id": "c1",
                                        "label": "Search input",
                                        "rough_bbox_hint": {"x": 10, "y": 20, "w": 120, "h": 30},
                                        "required_next_step": "run_execute_dry_run_calibration_for_numbered_region",
                                    },
                                    {
                                        "region_no": 7,
                                        "source_item_id": "c7",
                                        "label": "Placeholder",
                                        "rough_bbox_hint": {"x": 200, "y": 80, "w": 100, "h": 80},
                                    },
                                ],
                            },
                            "calibration_batch_plan": {
                                "ready_region_numbers": [1],
                                "review_blocked_region_numbers": [7],
                                "command_executes_now": False,
                                "post_batch_refresh_command_executes_now": False,
                            },
                            "execute_binding_enabled": False,
                            "artifact_is_authorization": False,
                        }
                    }
                },
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    validation = _write_json(
        tmp_path / "artifacts" / "candidate" / "promotion_validation_report.json",
        {
            "contract_version": "pathgraph_candidate_validation_report_v1",
            "validation_status": "blocked_pending_calibration",
        },
    )
    candidate = _write_json(
        tmp_path / "artifacts" / "candidate" / "pathgraph_candidate.json",
        {
            "contract_version": "pathgraph_candidate_v1",
            "reviewed_template_candidate_path": str(reviewed.relative_to(tmp_path)),
            "validation_report_path": str(validation.relative_to(tmp_path)),
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = build_learn_precise_understanding_candidate(
        source_path=candidate.relative_to(tmp_path),
        out_dir=tmp_path / "artifacts" / "candidate",
        project_root=tmp_path,
    )

    assert result["contract_version"] == "learn_precise_understanding_candidate_v1"
    assert result["readiness_status"] == "needs_pending_calibration"
    assert result["summary"]["total_regions"] == 3
    assert result["summary"]["pending_calibration_count"] == 1
    assert result["summary"]["review_blocked_count"] == 1
    assert result["summary"]["pathgraph_candidate_review_ready_count"] == 1
    assert result["summary"]["real_clicks"] == 0
    by_region = {item["region_no"]: item for item in result["items"]}
    assert by_region[1]["calibration_state"] == "pending_execute_dry_run_calibration"
    assert by_region[4]["calibration_state"] == "calibrated_review_only"
    assert by_region[4]["pathgraph_candidate_review_state"] == "candidate_for_human_pathgraph_review"
    assert by_region[7]["calibration_state"] == "review_before_calibration"
    assert result["safety"]["model_started"] is False
    assert result["safety"]["runtime_pathgraph_promotion"] is False
    assert Path(result["report_path"]).exists()
    review = load_learning_draft_review(candidate.relative_to(tmp_path), project_root=tmp_path)
    sidecar = review["pathgraph_candidate_review"]["precise_understanding_candidate"]
    summary_sidecar = review["pathgraph_candidate_review"]["pathgraph_readiness_summary"]["precise_understanding_candidate"]
    assert sidecar["readiness_status"] == "needs_pending_calibration"
    assert summary_sidecar["summary"]["pending_calibration_count"] == 1
