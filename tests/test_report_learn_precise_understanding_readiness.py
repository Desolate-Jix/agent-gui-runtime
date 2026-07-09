from __future__ import annotations

import json
import hashlib
from pathlib import Path

from scripts.report_learn_precise_understanding_readiness import report_precise_understanding_readiness


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_report_precise_understanding_readiness_summarizes_pending_pathgraph_blockers(tmp_path: Path) -> None:
    draft_path = tmp_path / "actual_parser_output_with_fusion_status.json"
    draft_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_trial_result_v1",
                "learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "page_details": {
                        "pipeline_audit": {
                            "precise_understanding_fusion_status": {
                                "contract_version": "learning_draft_precise_understanding_fusion_status_v1",
                                "display_readiness": {
                                    "status": "display_ready",
                                    "full_screen_overlay_available": True,
                                    "screenshot_available": True,
                                },
                                "pathgraph_preparation": {
                                    "status": "blocked_from_pathgraph_candidate_review",
                                    "promotable_item_count": 0,
                                    "blocked_item_count": 10,
                                },
                                "summary": {
                                    "attempted": 10,
                                    "promotable_to_pathgraph_candidate_review": 0,
                                    "real_clicks": 0,
                                },
                                "calibration_backlog": {
                                    "summary": {
                                        "uncalibrated_locator_cards": 8,
                                        "ready_for_execute_dry_run": 6,
                                        "review_before_calibration": 2,
                                    },
                                },
                                "calibration_batch_plan": {
                                    "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                                    "review_blocked_region_numbers": [7, 10],
                                    "command_executes_now": False,
                                    "execute_binding_enabled": False,
                                    "artifact_is_authorization": False,
                                },
                                "pathgraph_review_queue": {
                                    "summary": {
                                        "open_detail_candidate_review": 2,
                                        "same_screen_action_review": 5,
                                        "geometry_review_required": 1,
                                        "blocked_non_action": 2,
                                    }
                                },
                                "pathgraph_preflight_plan": {
                                    "summary": {
                                        "pending_calibration_ready_count": 6,
                                        "pending_calibration_review_count": 2,
                                        "ready_for_runtime_pathgraph_promotion": False,
                                    },
                                    "pending_calibration_batch": {
                                        "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                                        "review_blocked_region_numbers": [7, 10],
                                        "command_executes_now": False,
                                        "execute_binding_enabled": False,
                                        "artifact_is_authorization": False,
                                    },
                                },
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

    result = report_precise_understanding_readiness(
        draft_path=draft_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["contract_version"] == "learn_precise_understanding_readiness_report_v1"
    assert report["readiness_status"] == "needs_pending_calibration"
    assert report["coverage_summary"] == {
        "total_locator_cards": 10,
        "calibrated_cases": 2,
        "uncalibrated_locator_cards": 8,
        "calibration_coverage_rate": 0.2,
    }
    assert report["pending_calibration"]["ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert report["pending_calibration"]["review_blocked_region_numbers"] == [7, 10]
    assert report["pathgraph_readiness"]["status"] == "blocked_from_pathgraph_candidate_review"
    assert report["pathgraph_readiness"]["ready_for_runtime_pathgraph_promotion"] is False
    assert report["next_required_steps"][0] == "run_pending_numbered_region_calibration_batch_before_pathgraph_promotion"
    assert report["safety"]["execute_binding_enabled"] is False
    assert report["safety"]["artifact_is_authorization"] is False
    assert report["safety"]["real_clicks"] == 0
    assert report["not_accuracy"] is True
    assert report["not_pathgraph_promotion"] is True


def test_report_precise_understanding_readiness_records_evidence_integrity(tmp_path: Path) -> None:
    screenshot_path = tmp_path / "captures" / "screen.png"
    overlay_path = tmp_path / "overlays" / "full_screen_overlay.png"
    screenshot_path.parent.mkdir()
    overlay_path.parent.mkdir()
    screenshot_path.write_bytes(b"fake screen bytes")
    overlay_path.write_bytes(b"fake overlay bytes")
    draft_path = tmp_path / "actual_parser_output_with_fusion_status.json"
    draft_path.write_text(
        json.dumps(
            {
                "learning_draft": {
                    "page_details": {
                        "pipeline_audit": {
                            "precise_understanding_fusion_status": {
                                "screenshot_path": str(screenshot_path.relative_to(tmp_path)),
                                "full_screen_understanding_overlay_path": str(overlay_path.relative_to(tmp_path)),
                                "display_readiness": {"status": "display_ready"},
                                "summary": {"total_locator_cards": 2, "calibrated_cases": 2, "uncalibrated_locator_cards": 0, "real_clicks": 0},
                                "pathgraph_preparation": {"status": "blocked_from_pathgraph_candidate_review"},
                                "execute_binding_enabled": False,
                                "artifact_is_authorization": False,
                            }
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = report_precise_understanding_readiness(
        draft_path=draft_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    integrity = report["evidence_integrity"]
    assert integrity["status"] == "complete"
    assert integrity["required_for_pathgraph_review"] is True
    assert integrity["missing_declared_evidence"] == []
    assert integrity["source_draft"]["exists"] is True
    assert integrity["source_draft"]["sha256"] == _sha256(draft_path)
    assert integrity["screenshot"]["exists"] is True
    assert integrity["screenshot"]["sha256"] == _sha256(screenshot_path)
    assert integrity["full_screen_understanding_overlay"]["exists"] is True
    assert integrity["full_screen_understanding_overlay"]["sha256"] == _sha256(overlay_path)


def test_report_precise_understanding_readiness_flags_missing_declared_evidence(tmp_path: Path) -> None:
    draft_path = tmp_path / "actual_parser_output_with_fusion_status.json"
    draft_path.write_text(
        json.dumps(
            {
                "learning_draft": {
                    "page_details": {
                        "pipeline_audit": {
                            "precise_understanding_fusion_status": {
                                "screenshot_path": "captures/missing_screen.png",
                                "full_screen_understanding_overlay_path": "overlays/missing_overlay.png",
                                "summary": {"total_locator_cards": 1, "calibrated_cases": 0, "uncalibrated_locator_cards": 1, "real_clicks": 0},
                                "pathgraph_preparation": {"status": "blocked_from_pathgraph_candidate_review"},
                                "execute_binding_enabled": False,
                                "artifact_is_authorization": False,
                            }
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = report_precise_understanding_readiness(
        draft_path=draft_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    integrity = report["evidence_integrity"]
    assert integrity["status"] == "missing_declared_evidence"
    assert integrity["missing_declared_evidence"] == ["screenshot", "full_screen_understanding_overlay"]
    assert "repair_missing_evidence_before_pathgraph_review" in report["next_required_steps"]


def test_report_precise_understanding_readiness_uses_pending_batch_when_backlog_missing(tmp_path: Path) -> None:
    draft_path = tmp_path / "actual_parser_output_with_fusion_status.json"
    draft_path.write_text(
        json.dumps(
            {
                "learning_draft": {
                    "page_details": {
                        "pipeline_audit": {
                            "precise_understanding_fusion_status": {
                                "summary": {"attempted": 10, "real_clicks": 0},
                                "pathgraph_preparation": {"status": "blocked_from_pathgraph_candidate_review"},
                                "pathgraph_preflight_plan": {
                                    "summary": {"ready_for_runtime_pathgraph_promotion": False},
                                    "pending_calibration_batch": {
                                        "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                                        "review_blocked_region_numbers": [7, 10],
                                    },
                                },
                                "execute_binding_enabled": False,
                                "artifact_is_authorization": False,
                            }
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = report_precise_understanding_readiness(
        draft_path=draft_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["coverage_summary"] == {
        "total_locator_cards": 10,
        "calibrated_cases": 2,
        "uncalibrated_locator_cards": 8,
        "calibration_coverage_rate": 0.2,
    }


def test_report_precise_understanding_readiness_does_not_treat_attempted_as_coverage_without_context(tmp_path: Path) -> None:
    draft_path = tmp_path / "actual_parser_output_with_fusion_status.json"
    draft_path.write_text(
        json.dumps(
            {
                "learning_draft": {
                    "page_details": {
                        "pipeline_audit": {
                            "precise_understanding_fusion_status": {
                                "summary": {"attempted": 10, "needs_human_review": 8, "safe_intercepts": 2, "real_clicks": 0},
                                "pathgraph_preparation": {"status": "blocked_from_pathgraph_candidate_review"},
                                "execute_binding_enabled": False,
                                "artifact_is_authorization": False,
                            }
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = report_precise_understanding_readiness(
        draft_path=draft_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["coverage_summary"] == {
        "total_locator_cards": 0,
        "calibrated_cases": 0,
        "uncalibrated_locator_cards": 0,
        "calibration_coverage_rate": "not_covered",
    }
    assert report["readiness_status"] == "not_covered"


def test_report_precise_understanding_readiness_ignores_default_empty_backlog_as_coverage_context(tmp_path: Path) -> None:
    draft_path = tmp_path / "actual_parser_output_with_fusion_status.json"
    draft_path.write_text(
        json.dumps(
            {
                "learning_draft": {
                    "page_details": {
                        "pipeline_audit": {
                            "precise_understanding_fusion_status": {
                                "summary": {"attempted": 10, "real_clicks": 0},
                                "pathgraph_preparation": {"status": "blocked_from_pathgraph_candidate_review"},
                                "calibration_backlog": {
                                    "contract_version": "numbered_region_calibration_backlog_v1",
                                    "summary": {
                                        "uncalibrated_locator_cards": 0,
                                        "display_only": True,
                                        "execute_binding_enabled": False,
                                    },
                                    "items": [],
                                    "display_only": True,
                                    "execute_binding_enabled": False,
                                    "artifact_is_authorization": False,
                                },
                                "execute_binding_enabled": False,
                                "artifact_is_authorization": False,
                            }
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = report_precise_understanding_readiness(
        draft_path=draft_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["coverage_summary"]["calibration_coverage_rate"] == "not_covered"
    assert report["coverage_summary"]["total_locator_cards"] == 0
