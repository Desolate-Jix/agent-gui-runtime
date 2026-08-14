from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.learn.draft_review import load_learning_draft_review
from app.main import app


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_model_review_route_preserves_legacy_response_and_safety(monkeypatch) -> None:
    import app.api.panel as panel_api

    monkeypatch.setattr(
        panel_api,
        "run_panel_learning_model_review_repair",
        lambda **_kwargs: {
            "status": "safe_stop",
            "calibration_permission": False,
            "integrity_gate": {"status": "failed"},
            "final_stage2_report_path": "artifacts/final.json",
            "final_numbering_revision": 3,
        },
    )
    monkeypatch.setattr(
        panel_api,
        "write_trace",
        lambda **_kwargs: "logs/traces/review.json",
    )

    response = panel_api.run_learning_model_review_repair_endpoint(
        panel_api.PanelRunLearningModelReviewRepairRequest(
            two_stage_report_path="artifacts/input.json",
            screenshot_path="artifacts/input.png",
            composite_overlay_path="artifacts/overlay.png",
        )
    )

    payload = response.model_dump(mode="json")
    assert payload["success"] is True
    assert payload["message"] == "Learning model review and repair stopped safely"
    assert payload["data"]["status"] == "safe_stop"
    assert payload["data"]["calibration_permission"] is False
    assert payload["data"]["real_clicks"] == 0
    assert payload["data"]["live_fills"] == 0
    assert payload["data"]["live_submits"] == 0
    assert payload["data"]["trace_path"] == "logs/traces/review.json"
    assert payload["error"] is None


def test_model_review_route_preserves_legacy_failure_response(monkeypatch) -> None:
    import app.api.panel as panel_api

    def fail_review(**_kwargs):
        raise RuntimeError("review failed")

    monkeypatch.setattr(
        panel_api,
        "run_panel_learning_model_review_repair",
        fail_review,
    )

    response = panel_api.run_learning_model_review_repair_endpoint(
        panel_api.PanelRunLearningModelReviewRepairRequest(
            two_stage_report_path="artifacts/input.json",
            screenshot_path="artifacts/input.png",
            composite_overlay_path="artifacts/overlay.png",
        )
    )

    payload = response.model_dump(mode="json")
    assert payload == {
        "success": False,
        "message": "Learning model review and repair failed",
        "data": {
            "status": "safe_stop",
            "calibration_permission": False,
            "real_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
        "error": {
            "code": "learning_model_review_repair_failed",
            "details": "review failed",
        },
    }


def _write_trial(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": "learning_model_trial_v1",
                "app_name": "seek",
                "best_attempt_index": 0,
                "best_learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "Search surface with one query field.",
                    "state_guess": "job_search_initial",
                    "workflow_draft": {
                        "states": [
                            {"state_id": "s1", "label": "Search page", "page_type": "search_page"}
                        ],
                        "action_templates": [
                            {
                                "action_template_id": "a1",
                                "label": "Type query",
                                "semantic_action": "fill_field",
                                "target_entity": "r1",
                                "bbox": {"x": 10, "y": 20, "w": 80, "h": 24},
                                "click_point": {"x": 50, "y": 32},
                            }
                        ],
                        "verification_rules": [],
                    },
                    "interface_draft": {
                        "regions": [
                            {
                                "region_id": "r1",
                                "label": "Search input",
                                "role": "text_input",
                                "bbox": {"x": 8, "y": 18, "w": 100, "h": 30},
                                "click_point": {"x": 58, "y": 33},
                            }
                        ]
                    },
                    "safety": {
                        "observation_only": True,
                        "final_submit_blocked": True,
                    },
                    "agent_decision_points": [{"decision_id": "ask_before_submit"}],
                    "operation_skills": ["observe_screen", "locate_element"],
                    "gate_contracts": ["final_submit_guard_v1"],
                    "learning_source": "observe_model+coordinate_calibration",
                    "notes": ["calibrated evidence should stay visible"],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_open_detail_trial(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": "learning_model_trial_v1",
                "app_name": "seek",
                "best_attempt_index": 0,
                "best_learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "SEEK results with a job card.",
                    "state_guess": "seek_results",
                    "workflow_draft": {
                        "states": [
                            {"state_id": "seek_results", "label": "SEEK results", "page_type": "results_page"}
                        ],
                        "action_templates": [
                            {
                                "action_template_id": "open_card_1",
                                "label": "Job listing card: Software Engineer Specialist - Integration",
                                "semantic_action": "open_detail",
                                "action_kind": "open_detail",
                                "target_entity": "job_card_1",
                                "target_region_id": "job_card_1",
                                "bbox": {"x": 656, "y": 518, "w": 470, "h": 378},
                                "click_point": {"x": 891, "y": 707},
                                "requires_gate": True,
                                "artifact_is_authorization": False,
                                "execute_binding_enabled": False,
                                "transition_hint": {
                                    "contract_version": "learn_open_detail_transition_hint_v1",
                                    "transition_type": "open_detail",
                                    "source_region_id": "job_card_1",
                                    "expected_next_state_role": "detail_view",
                                    "target_surface": "detail_pane_or_detail_page",
                                    "requires_post_action_observe": True,
                                    "candidate_only": True,
                                    "artifact_is_authorization": False,
                                    "execute_binding_enabled": False,
                                },
                            }
                        ],
                        "verification_rules": [{"rule_id": "v1", "label": "Re-observe detail after opening card"}],
                    },
                    "interface_draft": {
                        "regions": [
                            {
                                "region_id": "job_card_1",
                                "label": "Job listing card",
                                "role": "card",
                                "bbox": {"x": 656, "y": 518, "w": 470, "h": 378},
                                "click_point": {"x": 891, "y": 707},
                            }
                        ]
                    },
                    "blockers": [{"blocker_id": "final_submit_forbidden", "label": "Final submit forbidden"}],
                    "safety": {
                        "artifact_is_authorization": False,
                        "execute_binding_enabled": False,
                        "final_submit_forbidden": True,
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_detail_surface_trial(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": "learning_model_trial_v1",
                "app_name": "seek",
                "best_attempt_index": 0,
                "best_learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "SEEK detail pane for selected job.",
                    "state_guess": "seek_job_detail",
                    "workflow_draft": {
                        "states": [
                            {"state_id": "detail_state", "label": "Job detail", "page_type": "detail_view"}
                        ],
                        "action_templates": [
                            {
                                "action_template_id": "apply_entry_1",
                                "label": "Apply entry",
                                "semantic_action": "open_apply_flow",
                                "target_entity": "apply_button_1",
                                "bbox": {"x": 1200, "y": 220, "w": 120, "h": 44},
                                "click_point": {"x": 1260, "y": 242},
                                "requires_gate": True,
                                "artifact_is_authorization": False,
                                "execute_binding_enabled": False,
                            }
                        ],
                        "verification_rules": [{"rule_id": "detail_title_visible", "label": "Detail title visible"}],
                    },
                    "interface_draft": {
                        "regions": [
                            {
                                "region_id": "detail_header_1",
                                "label": "Software Engineer Specialist - Integration",
                                "role": "detail_header",
                                "bbox": {"x": 1160, "y": 120, "w": 620, "h": 160},
                            },
                            {
                                "region_id": "apply_button_1",
                                "label": "Apply",
                                "role": "button",
                                "bbox": {"x": 1200, "y": 220, "w": 120, "h": 44},
                                "click_point": {"x": 1260, "y": 242},
                            },
                        ]
                    },
                    "blockers": [{"blocker_id": "final_submit_forbidden", "label": "Final submit forbidden"}],
                    "safety": {
                        "artifact_is_authorization": False,
                        "execute_binding_enabled": False,
                        "final_submit_forbidden": True,
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_load_learning_draft_review_defaults_to_human_review_and_no_execute(tmp_path: Path) -> None:
    from app.learn.draft_review import load_learning_draft_review

    trial_path = tmp_path / "artifacts" / "learning-runs" / "sample" / "trial_result.json"
    _write_trial(trial_path)

    review = load_learning_draft_review(trial_path, project_root=tmp_path)

    assert review["contract_version"] == "learning_draft_review_v1"
    assert review["review_status"] == "needs_human_review"
    assert review["draft_only"] is True
    assert review["no_click_authorization"] is True
    assert review["execute_binding_enabled"] is False
    assert review["counts_as_pure_model_generated"] is False
    assert review["artifact_is_authorization"] is False
    assert review["final_submit_forbidden"] is True
    assert review["real_action_requires_gate"] is True
    assert review["authorization_scope"] == "display_and_review_only"
    assert review["source"]["source_trial_path"] == "artifacts/learning-runs/sample/trial_result.json"
    assert review["draft"]["states"][0]["state_id"] == "s1"
    assert review["draft"]["regions"][0]["region_id"] == "r1"
    assert review["draft"]["action_templates"][0]["action_template_id"] == "a1"
    assert review["draft"]["blockers"] == []
    assert review["draft"]["verification_rules"] == []
    assert review["draft"]["agent_decision_points"][0]["decision_id"] == "ask_before_submit"
    assert review["draft"]["operation_skills"] == ["observe_screen", "locate_element"]
    assert review["draft"]["gate_contracts"] == ["final_submit_guard_v1"]
    assert review["draft"]["learning_source"] == "observe_model+coordinate_calibration"
    assert review["draft"]["notes"] == ["calibrated evidence should stay visible"]
    assert review["screen_understanding_preview"]["source_status"] == "not_available"
    assert review["screen_understanding_preview"]["execute_binding_enabled"] is False


def test_load_learning_draft_review_exposes_screen_understanding_preview(tmp_path: Path) -> None:
    from app.learn.draft_review import load_learning_draft_review

    source_path = tmp_path / "artifacts" / "learning-recognition" / "pipeline_result.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_pipeline_result_v1",
                "screen_inventory": [
                    {"item_id": "v1", "label": "Hero code sample"},
                    {"item_id": "u1", "label": "Search"},
                ],
                "classification": {
                    "rejected_non_actionable": [
                        {
                            "item_id": "v1",
                            "label": "Hero code sample",
                            "item_type": "layout",
                            "role": "card",
                            "bbox": {"x": 100, "y": 100, "w": 300, "h": 180},
                            "source_evidence": ["vision"],
                            "evidence_level": "semantic_region_only",
                            "grounding_eligible": False,
                            "review_only": True,
                            "grounding_block_reason": "semantic_region_only_without_interactable_evidence",
                        }
                    ],
                    "accepted_for_grounding": [
                        {
                            "item_id": "u1",
                            "label": "Search",
                            "item_type": "actionable",
                            "role": "button",
                            "bbox": {"x": 980, "y": 140, "w": 92, "h": 36},
                            "source_evidence": ["vision", "uia"],
                            "evidence_level": "cross_evidence_grounded",
                            "grounding_eligible": True,
                            "review_only": False,
                            "metadata": {
                                "cross_evidence": {
                                    "support_item_id": "uia_search",
                                    "iou": 0.82,
                                }
                            },
                        }
                    ],
                    "needs_human_review": [],
                    "danger_zones": [],
                },
                "learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "Search page.",
                    "state_guess": "search_page",
                    "states": [{"state_id": "s1", "label": "Search page"}],
                    "regions": [{"region_id": "r1", "label": "Search"}],
                    "action_templates": [{"action_template_id": "a1", "label": "Search", "target_entity": "r1"}],
                    "blockers": [],
                    "verification_rules": [],
                    "safety": {"final_submit_forbidden": True},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    review = load_learning_draft_review(source_path, project_root=tmp_path)
    preview = review["screen_understanding_preview"]

    assert preview["contract_version"] == "screen_understanding_preview_v1"
    assert preview["source_status"] == "available"
    assert preview["display_only"] is True
    assert preview["execute_binding_enabled"] is False
    assert preview["counts"] == {
        "inventory_items": 2,
        "review_only_regions": 1,
        "grounding_candidates": 1,
        "danger_zones": 0,
    }
    assert preview["review_only_regions"][0]["grounding_block_reason"] == "semantic_region_only_without_interactable_evidence"
    assert preview["grounding_candidates"][0]["evidence_level"] == "cross_evidence_grounded"
    assert preview["grounding_candidates"][0]["cross_evidence"]["support_item_id"] == "uia_search"


def test_load_learning_draft_review_exposes_full_screen_fusion_overlay_preview(tmp_path: Path) -> None:
    from app.learn.draft_review import load_learning_draft_review

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "seek_results.png"
    overlay_path = tmp_path / "logs" / "benchmarks" / "fusion" / "full_screen_understanding_overlay.png"
    compiled_overlay_path = tmp_path / "logs" / "benchmarks" / "fusion" / "selected_regions.png"
    source_status_path = tmp_path / "logs" / "benchmarks" / "fusion" / "source_status.json"
    source_calibration_path = tmp_path / "logs" / "benchmarks" / "fusion" / "calibration_report.json"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(b"fake screenshot bytes")
    overlay_path.write_bytes(b"fake png bytes")
    compiled_overlay_path.write_bytes(b"fake selected overlay bytes")
    source_status_path.write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    source_calibration_path.write_text(json.dumps({"calibration": "ok"}), encoding="utf-8")
    source_path = tmp_path / "artifacts" / "learning-recognition" / "trial_result.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_trial_result_v1",
                "learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "SEEK results page.",
                    "state_guess": "seek_results",
                    "states": [{"state_id": "seek_results", "label": "SEEK results"}],
                    "regions": [],
                    "action_templates": [],
                    "blockers": [],
                    "verification_rules": [],
                    "page_details": {
                        "pipeline_audit": {
                            "precise_understanding_fusion_status": {
                                "contract_version": "learn_precise_understanding_fusion_status_report_v1",
                                "screenshot_path": "artifacts/screenshots/seek_results.png",
                                "source_status_report_path": "logs/benchmarks/fusion/source_status.json",
                                "source_calibration_report_path": "logs/benchmarks/fusion/calibration_report.json",
                                "full_screen_understanding_overlay_path": str(overlay_path),
                                "compiled_overlay_path": "logs/benchmarks/fusion/selected_regions.png",
                                "summary": {
                                    "total_locator_cards": 10,
                                    "calibrated_cases": 2,
                                    "uncalibrated_locator_cards": 8,
                                },
                                "calibration_backlog": {
                                    "contract_version": "numbered_region_calibration_backlog_v1",
                                    "summary": {
                                        "uncalibrated_locator_cards": 8,
                                        "display_only": True,
                                        "execute_binding_enabled": False,
                                    },
                                    "items": [
                                        {
                                            "region_no": 1,
                                            "label": "Search keyword field",
                                            "suggested_semantic_action": "fill_field",
                                        }
                                    ],
                                    "execute_binding_enabled": False,
                                },
                                "calibration_batch_plan": {
                                    "contract_version": "learning_draft_numbered_region_calibration_batch_plan_v1",
                                    "summary": {
                                        "ready_for_execute_dry_run": 6,
                                        "review_before_calibration": 2,
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
                                },
                                "calibration_handoff_report": {
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
                                        "execute_binding_enabled": False,
                                        "artifact_is_authorization": False,
                                        "real_clicks": 0,
                                        "live_fill": False,
                                        "live_submit": False,
                                    },
                                },
                                "calibration_batch_acceptance_report": {
                                    "contract_version": "learning_draft_calibration_batch_acceptance_report_v1",
                                    "acceptance_status": "awaiting_future_calibration_output",
                                    "ready_for_post_batch_refresh": False,
                                    "coverage": {
                                        "expected_ready_region_numbers": [1, 2, 3, 6, 8, 9],
                                        "accepted_region_numbers": [],
                                        "missing_ready_region_numbers": [1, 2, 3, 6, 8, 9],
                                        "unexpected_region_numbers": [],
                                        "review_blocked_region_numbers_in_rerun": [],
                                    },
                                    "checks": {"rerun_report_exists": False},
                                    "blockers": ["rerun_report_missing"],
                                    "warnings": [],
                                    "safety": {
                                        "execute_binding_enabled": False,
                                        "artifact_is_authorization": False,
                                        "real_clicks": 0,
                                    },
                                },
                                "calibration_handoff_consistency_report": {
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
                                        "draft_loads": True,
                                        "plan_post_batch_refresh_has_batch_plan": True,
                                        "draft_post_batch_refresh_has_batch_plan": True,
                                        "handoff_post_batch_refresh_has_batch_plan": True,
                                        "refresh_blocks_before_future_rerun": True,
                                    },
                                    "blockers": [],
                                    "safety": {
                                        "execute_binding_enabled": False,
                                        "artifact_is_authorization": False,
                                        "model_started": False,
                                        "live_clicks": 0,
                                        "live_fills": 0,
                                        "live_submits": 0,
                                    },
                                },
                                "model_start_runbook": {
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
                                    },
                                    "blockers": [],
                                    "execute_binding_enabled": False,
                                    "artifact_is_authorization": False,
                                },
                                "pathgraph_preparation": {
                                    "status": "blocked_from_pathgraph_candidate_review",
                                    "promotable_item_count": 0,
                                    "blocked_item_count": 10,
                                },
                                "display_readiness": {"status": "display_ready"},
                                "not_accuracy": True,
                                "execute_binding_enabled": False,
                                "artifact_is_authorization": False,
                            }
                        }
                    },
                    "safety": {"final_submit_forbidden": True},
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    review = load_learning_draft_review(source_path, project_root=tmp_path)
    preview = review["screen_understanding_preview"]

    assert preview["source_status"] == "available"
    assert preview["evidence_integrity"]["status"] == "complete"
    assert preview["evidence_integrity"]["missing_declared_evidence"] == []
    assert preview["evidence_integrity"]["screenshot"]["exists"] is True
    assert preview["evidence_integrity"]["screenshot"]["sha256"] == hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    assert preview["evidence_integrity"]["full_screen_understanding_overlay"]["exists"] is True
    assert preview["evidence_integrity"]["compiled_overlay"]["exists"] is True
    assert preview["evidence_integrity"]["source_status_report"]["exists"] is True
    assert preview["evidence_integrity"]["source_calibration_report"]["exists"] is True
    assert preview["full_screen_understanding_overlay_path"] == "logs/benchmarks/fusion/full_screen_understanding_overlay.png"
    assert preview["compiled_overlay_path"] == "logs/benchmarks/fusion/selected_regions.png"
    assert preview["fusion_summary"] == {
        "total_locator_cards": 10,
        "calibrated_cases": 2,
        "uncalibrated_locator_cards": 8,
    }
    assert preview["calibration_backlog_summary"]["uncalibrated_locator_cards"] == 8
    assert preview["calibration_backlog_items"][0]["suggested_semantic_action"] == "fill_field"
    assert preview["calibration_batch_plan_summary"]["ready_for_execute_dry_run"] == 6
    assert preview["calibration_batch_ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert preview["calibration_batch_review_blocked_region_numbers"] == [7, 10]
    assert preview["calibration_batch_run_command_preview"].endswith("--regions 1,2,3,6,8,9")
    assert preview["calibration_batch_command_executes_now"] is False
    assert "refresh_learn_fusion_after_calibration_batch.py" in preview["post_batch_refresh_command_preview"]
    assert preview["post_batch_refresh_command_executes_now"] is False
    assert preview["post_batch_refresh_requires_completed_batch"] is True
    assert preview["calibration_handoff_report"]["handoff_status"] == "ready_for_explicit_model_start"
    assert preview["calibration_handoff_report"]["safe_to_start_after_user_approval"] is True
    assert preview["calibration_handoff_report"]["ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert preview["calibration_handoff_report"]["future_outputs"]["rerun_report_status"] == "awaiting_future_calibration_output"


    assert preview["calibration_handoff_report"]["safety"]["real_clicks"] == 0
    assert preview["calibration_batch_acceptance_report"]["acceptance_status"] == "awaiting_future_calibration_output"
    assert preview["calibration_batch_acceptance_report"]["ready_for_post_batch_refresh"] is False
    assert preview["calibration_batch_acceptance_report"]["coverage"]["expected_ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert preview["calibration_batch_acceptance_report"]["coverage"]["missing_ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert preview["calibration_batch_acceptance_report"]["blockers"] == ["rerun_report_missing"]
    assert preview["calibration_batch_acceptance_report"]["safety"]["real_clicks"] == 0
    assert preview["calibration_handoff_consistency_report"]["consistency_status"] == "ready_for_explicit_model_start"
    assert preview["calibration_handoff_consistency_report"]["summary"]["post_batch_refresh_has_batch_plan"] is True
    assert preview["calibration_handoff_consistency_report"]["summary"]["refresh_blocks_before_future_rerun"] is True
    assert preview["calibration_handoff_consistency_report"]["checks"]["plan_post_batch_refresh_has_batch_plan"] is True
    assert preview["calibration_handoff_consistency_report"]["blockers"] == []
    assert preview["calibration_handoff_consistency_report"]["safety"]["live_clicks"] == 0
    assert preview["model_start_runbook"]["runbook_status"] == "awaiting_explicit_model_start_approval"
    assert preview["model_start_runbook"]["may_start_model_after_user_approval"] is True
    assert preview["model_start_runbook"]["may_run_calibration_batch_now"] is False
    assert preview["model_start_runbook"]["ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert preview["model_start_runbook"]["guards"]["prebatch_refresh_blocks_before_future_rerun"] is True
    assert preview["model_start_runbook"]["safety"]["live_clicks"] == 0
    assert preview["precise_understanding_readiness_summary"] == {
        "readiness_status": "needs_pending_calibration",
        "total_locator_cards": 10,
        "calibrated_cases": 2,
        "uncalibrated_locator_cards": 8,
        "calibration_coverage_rate": 0.2,
        "pending_calibration_ready_count": 6,
        "pending_calibration_review_count": 2,
        "pathgraph_status": "blocked_from_pathgraph_candidate_review",
        "ready_for_runtime_pathgraph_promotion": False,
        "display_only": True,
        "not_accuracy": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    assert preview["display_only"] is True
    assert preview["execute_binding_enabled"] is False
    assert preview["artifact_is_authorization"] is False
    assert preview["interpretation"].startswith("screen understanding preview only")


def test_load_learning_draft_review_prefers_current_two_stage_fusion_overlay(tmp_path: Path) -> None:
    current_overlay = tmp_path / "artifacts" / "review-overlays" / "current_fusion.png"
    previous_overlay = tmp_path / "artifacts" / "review-overlays" / "previous_fusion.png"
    current_overlay.parent.mkdir(parents=True, exist_ok=True)
    current_overlay.write_bytes(b"current fusion")
    previous_overlay.write_bytes(b"previous fusion")
    source_path = tmp_path / "artifacts" / "learning-runs" / "trial_result.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_recognition_trial_result_v1",
                "learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "Current learning run.",
                    "state_guess": "current_state",
                    "states": [],
                    "regions": [],
                    "action_templates": [],
                    "blockers": [],
                    "verification_rules": [],
                    "page_details": {
                        "two_stage_understanding": {
                            "fusion": {
                                "compiled_overlay_path": "artifacts/review-overlays/current_fusion.png",
                                "full_screen_understanding_overlay_path": "artifacts/review-overlays/current_fusion.png",
                                "summary": {"fused_review_box_count": 8},
                            }
                        },
                        "precise_understanding_fusion_status": {
                            "compiled_overlay_path": "artifacts/review-overlays/previous_fusion.png",
                            "full_screen_understanding_overlay_path": "artifacts/review-overlays/previous_fusion.png",
                            "summary": {"fused_review_box_count": 2},
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    review = load_learning_draft_review(source_path, project_root=tmp_path)
    preview = review["screen_understanding_preview"]

    assert preview["compiled_overlay_path"] == "artifacts/review-overlays/current_fusion.png"
    assert preview["full_screen_understanding_overlay_path"] == "artifacts/review-overlays/current_fusion.png"
    assert preview["fusion_summary"] == {"fused_review_box_count": 8}


def test_panel_learning_recognition_trial_loads_as_review_and_candidate() -> None:
    client = TestClient(app)

    response = client.post(
        "/panel/run_learning_recognition_trial",
        json={
            "app_name": "python_org",
            "state_hint": "python_homepage",
            "summary": "Python homepage with a search input.",
            "observation_evidence": {
                "contract_version": "panel_learning_draft_observation_evidence_v1",
                "screen_size": {"width": 1200, "height": 800},
                "current_image_path": "artifacts/screenshots/sample_python_homepage.png",
                "coordinate_overlay_path": "logs/overlays/sample_python_homepage_overlay.png",
                "calibrated_targets": [
                    {
                        "candidate_id": "search_input",
                        "label": "Search input",
                        "role": "input",
                        "bbox": {"x": 800, "y": 120, "w": 240, "h": 36},
                        "click_point": {"x": 920, "y": 138},
                        "coordinate_validation": {
                            "status": "valid",
                            "bbox_present": True,
                            "click_point_present": True,
                            "bbox_inside_image": True,
                            "click_point_inside_image": True,
                            "click_point_inside_bbox": True,
                        },
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["contract_version"] == "panel_learning_recognition_trial_run_v1"
    assert data["artifact_type"] == "learn_recognition_trial"
    assert data["draft_only"] is True
    assert data["execute_binding_enabled"] is False
    assert data["real_clicks"] == 0
    assert data["summary"]["draft_section_counts"]["regions"] == 1
    assert data["summary"]["draft_section_counts"]["action_templates"] == 1

    trial_path = data["trial_path"]
    review_response = client.post("/panel/load_learning_draft_review", json={"source_path": trial_path})
    assert review_response.status_code == 200
    review_body = review_response.json()
    assert review_body["success"] is True
    review = review_body["data"]
    assert review["draft_only"] is True
    assert review["execute_binding_enabled"] is False
    assert review["draft"]["regions"][0]["label"] == "Search input"
    assert review["draft"]["action_templates"][0]["low_level_action_type"] == "input"
    assert review["draft"]["action_templates"][0]["click_point"] == {"x": 920, "y": 138}

    candidate_response = client.post(
        "/panel/generate_pathgraph_candidate",
        json={"source_path": trial_path, "review_patch": {}},
    )
    assert candidate_response.status_code == 200
    candidate_body = candidate_response.json()
    assert candidate_body["success"] is True
    candidate = candidate_body["data"]
    assert candidate["validation_status"] == "passed_candidate"
    assert candidate["execute_binding_enabled"] is False
    assert candidate["final_submit_forbidden"] is True


def test_panel_learning_recognition_trial_records_verified_model_trace_provenance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.api import panel as panel_api

    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    trace_path = _write_json(
        tmp_path / "logs" / "traces" / "vision" / "observe.json",
        {
            "success": True,
            "result": {
                "image_path": "artifacts/screenshots/current.png",
                "model_io": {
                    "contract_version": "model_io_trace_v1",
                    "status": "success",
                    "provider": "local",
                    "model_name": "Qwen3VL-8B",
                    "raw_text": "{\"contract_version\":\"vision_regions_v1\"}",
                },
            },
        },
    )

    response = TestClient(app).post(
        "/panel/run_learning_recognition_trial",
        json={
            "app_name": "sample_app",
            "state_hint": "sample_state",
            "summary": "Sample surface.",
            "observation_evidence": {
                "contract_version": "panel_learning_draft_observation_evidence_v1",
                "screen_size": {"width": 800, "height": 600},
                "current_image_path": "artifacts/screenshots/current.png",
                "model_roles": {
                    "screen_understanding": {
                        "model_profile_id": "qwen3_vl_8b_q4_k_m",
                        "trace_path": str(trace_path.relative_to(tmp_path)),
                    }
                },
            },
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    saved = json.loads((tmp_path / data["trial_path"]).read_text(encoding="utf-8-sig"))
    assert saved["actual_model_call_in_this_run"] is True
    assert saved["model_generated"] is True
    assert saved["model_provenance"]["actual_model_call_evidence_count"] == 1
    assert saved["model_provenance"]["evidence"][0]["model_name"] == "Qwen3VL-8B"
    assert saved["real_clicks"] == 0
    assert saved["execute_binding_enabled"] is False


def test_panel_learning_recognition_trial_attaches_two_stage_fusion_status(tmp_path: Path, monkeypatch) -> None:
    from app.api import panel as panel_api

    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    report_path = tmp_path / "logs" / "benchmarks" / "two_stage" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_two_stage_screen_understanding_v1",
                "fusion_status": {
                    "contract_version": "learn_precise_understanding_fusion_status_report_v1",
                    "compiled_overlay_path": "artifacts/review-overlays/fused_overlay.png",
                    "full_screen_understanding_overlay_path": "artifacts/review-overlays/full_overlay.png",
                    "summary": {"fused_review_box_count": 2},
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "stage1_gate": {"status": "blocked_before_stage2_numbering"},
                "stage2_numbering_skipped": True,
                "fusion": {
                    "fused_review_boxes": [
                        {"region_id": "review_1"},
                        {"region_id": "review_2"},
                    ]
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    client = TestClient(app)

    response = client.post(
        "/panel/run_learning_recognition_trial",
        json={
            "app_name": "python_org",
            "state_hint": "python_homepage",
            "summary": "Python homepage with a search input.",
            "two_stage_report_path": "logs/benchmarks/two_stage/report.json",
            "observation_evidence": {
                "contract_version": "panel_learning_draft_observation_evidence_v1",
                "screen_size": {"width": 1200, "height": 800},
                "current_image_path": "artifacts/screenshots/sample_python_homepage.png",
                "review_boxes": [
                    {
                        "candidate_id": "hero_panel",
                        "label": "Hero panel",
                        "role": "review_only",
                        "bbox": {"x": 100, "y": 160, "w": 500, "h": 240},
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    }
                ],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["summary"]["two_stage_report_attached"] is True
    assert body["data"]["summary"]["two_stage_stage1_gate_status"] == "blocked_before_stage2_numbering"
    assert body["data"]["summary"]["two_stage_stage2_numbering_skipped"] is True
    assert body["data"]["summary"]["two_stage_review_box_count"] == 2
    assert body["data"]["summary"]["precise_understanding_status"] == "review_overlay_attached_stage1_blocked"
    trial_path = body["data"]["trial_path"]
    saved = json.loads((tmp_path / trial_path).read_text(encoding="utf-8"))
    assert saved["precise_understanding_status"] == "review_overlay_attached_stage1_blocked"
    attached = saved["learning_draft"]["page_details"]["pipeline_audit"]["precise_understanding_fusion_status"]
    assert attached["compiled_overlay_path"] == "artifacts/review-overlays/fused_overlay.png"
    assert attached["source_two_stage_report_path"] == "logs/benchmarks/two_stage/report.json"
    assert attached["stage1_gate_status"] == "blocked_before_stage2_numbering"
    assert attached["stage2_numbering_skipped"] is True
    assert attached["review_box_count"] == 2

    review_response = client.post("/panel/load_learning_draft_review", json={"source_path": trial_path})
    assert review_response.status_code == 200
    review = review_response.json()["data"]
    preview = review["screen_understanding_preview"]
    assert preview["compiled_overlay_path"] == "artifacts/review-overlays/fused_overlay.png"
    assert preview["full_screen_understanding_overlay_path"] == "artifacts/review-overlays/full_overlay.png"
    assert preview["display_only"] is True
    assert preview["execute_binding_enabled"] is False
    assert preview["artifact_is_authorization"] is False


def test_panel_learning_recognition_trial_persists_current_calibrated_fusion_overlay(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.api import panel as panel_api

    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    report_path = tmp_path / "artifacts" / "learning-runs" / "two-stage" / "trial_result.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_two_stage_screen_understanding_v1",
                "fusion_status": {
                    "compiled_overlay_path": "artifacts/review-overlays/stage2.png",
                    "full_screen_understanding_overlay_path": "artifacts/review-overlays/stage2.png",
                    "summary": {"fused_review_box_count": 3},
                },
                "stage1_gate": {"status": "passed"},
                "stage2_numbering": {"regions": [{"region_id": "main"}]},
                "fusion": {"fused_review_boxes": [{"region_id": "review_1"}]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overlay_path = tmp_path / "artifacts" / "review-overlays" / "calibrated-fusion.png"
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_bytes(b"calibrated fusion")

    response = TestClient(app).post(
        "/panel/run_learning_recognition_trial",
        json={
            "app_name": "steamwebhelper",
            "state_hint": "friends",
            "two_stage_report_path": "artifacts/learning-runs/two-stage/trial_result.json",
            "observation_evidence": {
                "contract_version": "panel_learning_draft_observation_evidence_v1",
                "current_image_path": "artifacts/screenshots/steam.png",
                "coordinate_overlay_path": "artifacts/review-overlays/calibrated-fusion.png",
                "coordinate_overlay": {
                    "contract_version": "learn_target_coordinate_overlay_v1",
                    "status": "ready",
                    "base_visual_source": "two_stage_numbered_overlay",
                    "final_fusion_overlay": True,
                },
                "learn_all_targets_summary": {
                    "calibration_target_count": 4,
                    "vista_validated_count": 4,
                    "coordinate_calibration_status": "model_validation_completed",
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    saved = json.loads((tmp_path / body["data"]["trial_path"]).read_text(encoding="utf-8"))
    status = saved["learning_draft"]["page_details"]["pipeline_audit"][
        "precise_understanding_fusion_status"
    ]
    assert status["compiled_overlay_path"] == "artifacts/review-overlays/calibrated-fusion.png"
    assert status["full_screen_understanding_overlay_path"] == "artifacts/review-overlays/calibrated-fusion.png"
    assert status["calibration_overlay_path"] == "artifacts/review-overlays/calibrated-fusion.png"
    assert status["stage2_compiled_overlay_path"] == "artifacts/review-overlays/stage2.png"
    assert status["display_overlay_source"] == "two_stage_plus_precise_calibration"

    review = TestClient(app).post(
        "/panel/load_learning_draft_review",
        json={"source_path": body["data"]["trial_path"]},
    ).json()["data"]
    assert review["screen_understanding_preview"]["compiled_overlay_path"] == (
        "artifacts/review-overlays/calibrated-fusion.png"
    )


def test_attach_two_stage_fusion_status_keeps_current_pipeline_overlay() -> None:
    from app.api import panel as panel_api

    result = {
        "learning_draft": {
            "page_details": {
                "pipeline_audit": {
                    "precise_understanding_fusion_status": {
                        "compiled_overlay_path": "artifacts/review-overlays/current_fusion.png",
                        "full_screen_understanding_overlay_path": "artifacts/review-overlays/current_full.png",
                        "summary": {"fused_review_box_count": 7},
                    }
                }
            }
        }
    }
    previous_report = {
        "compiled_overlay_path": "artifacts/review-overlays/previous_fusion.png",
        "full_screen_understanding_overlay_path": "artifacts/review-overlays/previous_full.png",
        "stage1_gate_status": "passed",
        "source_two_stage_report_path": "artifacts/learning-runs/previous/report.json",
    }

    panel_api._attach_two_stage_fusion_status_to_learning_result(result, previous_report)

    page_details = result["learning_draft"]["page_details"]
    attached = page_details["pipeline_audit"]["precise_understanding_fusion_status"]
    assert attached["compiled_overlay_path"] == "artifacts/review-overlays/current_fusion.png"
    assert attached["full_screen_understanding_overlay_path"] == "artifacts/review-overlays/current_full.png"
    assert attached["summary"] == {"fused_review_box_count": 7}
    assert attached["stage1_gate_status"] == "passed"
    assert attached["source_two_stage_report_path"] == "artifacts/learning-runs/previous/report.json"
    assert page_details["compiled_overlay_path"] == "artifacts/review-overlays/current_fusion.png"
    assert page_details["full_screen_understanding_overlay_path"] == "artifacts/review-overlays/current_full.png"


def test_attach_two_stage_fusion_status_prefers_verified_calibrated_fusion_over_stale_current_overlay() -> None:
    from app.api import panel as panel_api

    result = {
        "learning_draft": {
            "page_details": {
                "pipeline_audit": {
                    "precise_understanding_fusion_status": {
                        "compiled_overlay_path": "artifacts/review-overlays/stage2.png",
                        "full_screen_understanding_overlay_path": "artifacts/review-overlays/stage2.png",
                    }
                }
            }
        }
    }
    calibrated = {
        "compiled_overlay_path": "artifacts/review-overlays/calibrated-fusion.png",
        "full_screen_understanding_overlay_path": "artifacts/review-overlays/calibrated-fusion.png",
        "stage2_compiled_overlay_path": "artifacts/review-overlays/stage2.png",
        "final_fusion_overlay": True,
        "display_overlay_source": "two_stage_plus_precise_calibration",
    }

    panel_api._attach_two_stage_fusion_status_to_learning_result(result, calibrated)

    attached = result["learning_draft"]["page_details"]["pipeline_audit"][
        "precise_understanding_fusion_status"
    ]
    assert attached["compiled_overlay_path"] == "artifacts/review-overlays/calibrated-fusion.png"
    assert attached["final_fusion_overlay"] is True


def test_load_learning_draft_review_prefers_verified_calibrated_fusion_over_two_stage_overlay(
    tmp_path: Path,
) -> None:
    stage2 = tmp_path / "artifacts" / "review-overlays" / "stage2.png"
    calibrated = tmp_path / "artifacts" / "review-overlays" / "calibrated.png"
    stage2.parent.mkdir(parents=True, exist_ok=True)
    stage2.write_bytes(b"stage2")
    calibrated.write_bytes(b"calibrated")
    source = tmp_path / "artifacts" / "learning-runs" / "trial_result.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        json.dumps(
            {
                "learning_draft": {
                    "screen_summary": "test",
                    "states": [],
                    "regions": [],
                    "action_templates": [],
                    "blockers": [],
                    "verification_rules": [],
                    "page_details": {
                        "two_stage_understanding": {
                            "fusion": {"compiled_overlay_path": "artifacts/review-overlays/stage2.png"}
                        },
                        "pipeline_audit": {
                            "precise_understanding_fusion_status": {
                                "compiled_overlay_path": "artifacts/review-overlays/calibrated.png",
                                "final_fusion_overlay": True,
                                "display_overlay_source": "two_stage_plus_precise_calibration",
                            }
                        },
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    preview = load_learning_draft_review(source, project_root=tmp_path)["screen_understanding_preview"]

    assert preview["compiled_overlay_path"] == "artifacts/review-overlays/calibrated.png"


def test_panel_learning_recognition_trial_uses_two_stage_numbered_items_when_calibration_has_no_targets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.api import panel as panel_api

    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    report_path = tmp_path / "logs" / "benchmarks" / "two_stage" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_two_stage_screen_understanding_v1",
                "report_identity": "authoritative_two_stage_fixture",
                "stage1_gate": {"status": "passed"},
                "stage2_numbering_skipped": False,
                "stage2_numbering": {
                    "contract_version": "learn_stage2_region_numbering_v1",
                    "region_count": 1,
                    "numbered_item_count": 1,
                    "regions": [
                        {
                            "region_id": "structure_region_main_content",
                            "label": "Main content",
                            "bbox": {"x": 90, "y": 120, "w": 900, "h": 620},
                            "numbered_items": [
                                {
                                    "number": "3.1",
                                    "item_id": "stage2_card_1",
                                    "label": "Featured album card",
                                    "role": "recommendation_item",
                                    "bbox": {"x": 160, "y": 220, "w": 220, "h": 260},
                                    "review_only": True,
                                    "execute_binding_enabled": False,
                                    "artifact_is_authorization": False,
                                }
                            ],
                        }
                    ],
                },
                "fusion": {
                    "compiled_overlay_path": "artifacts/review-overlays/fused_overlay.png",
                    "fused_review_boxes": [],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    client = TestClient(app)

    response = client.post(
        "/panel/run_learning_recognition_trial",
        json={
            "app_name": "apple_music",
            "state_hint": "apple_music_home",
            "summary": "Apple Music home screen with cards.",
            "two_stage_report_path": "logs/benchmarks/two_stage/report.json",
            "observation_evidence": {
                "contract_version": "panel_learning_draft_observation_evidence_v1",
                "screen_size": {"width": 1000, "height": 800},
                "current_image_path": "artifacts/screenshots/apple_music.png",
                "calibrated_targets": [],
                "review_boxes": [],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["summary"]["two_stage_report_attached"] is True
    assert data["summary"]["screen_inventory_count"] >= 1
    assert data["summary"]["draft_section_counts"]["regions"] >= 1
    assert data["summary"]["grounding_validation_count"] == 0
    assert data["learn_all_targets"]["status"] == "review_boxes_ready"
    assert data["learn_all_targets"]["target_count"] == 0
    assert data["learn_all_targets"]["review_box_count"] == 1
    assert data["learn_all_targets"]["artifact_is_authorization"] is False
    assert data["learn_all_targets"]["execute_binding_enabled"] is False

    saved = json.loads((tmp_path / data["trial_path"]).read_text(encoding="utf-8"))
    assert saved["two_stage_understanding"]["report_identity"] == "authoritative_two_stage_fixture"
    assert [
        item["region_id"] for item in saved["two_stage_understanding"]["stage2_numbering"]["regions"]
    ] == ["structure_region_main_content"]
    labels = {item["label"] for item in saved["learning_draft"]["regions"]}
    assert "Featured album card" in labels
    assert saved["learning_draft"]["execute_binding_enabled"] is False
    assert saved["learning_draft"]["artifact_is_authorization"] is False


def test_panel_deterministic_partition_report_flows_into_page_detail_and_readonly_pathgraph(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.api import panel as panel_api

    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    overlay_path = tmp_path / "artifacts" / "review-overlays" / "deterministic_fusion.png"
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_bytes(b"deterministic-fusion-overlay")
    report_path = tmp_path / "logs" / "benchmarks" / "deterministic" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_two_stage_screen_understanding_v1",
                "report_identity": "deterministic_partition_fixture",
                "stage1_source": "deterministic_root_partition_v1",
                "stage1_gate": {"status": "passed"},
                "stage1_regions": [
                    {
                        "region_id": "structure_region_main_content",
                        "label": "Main content",
                        "role": "primary_content",
                        "bbox": {"x": 0, "y": 0, "w": 1000, "h": 800},
                        "rough_bbox": {"x": 0, "y": 0, "w": 1000, "h": 800},
                        "precise_bbox": {"x": 0, "y": 0, "w": 1000, "h": 800},
                    }
                ],
                "stage2_numbering_skipped": False,
                "stage2_numbering": {
                    "contract_version": "learn_stage2_region_numbering_v1",
                    "region_count": 1,
                    "numbered_item_count": 2,
                    "regions": [
                        {
                            "region_id": "structure_region_main_content",
                            "label": "Main content",
                            "role": "primary_content",
                            "bbox": {"x": 0, "y": 0, "w": 1000, "h": 800},
                            "numbered_items": [
                                {
                                    "number": "1.1",
                                    "item_id": "stage2_search_input",
                                    "label": "Search input",
                                    "role": "text_input",
                                    "bbox": {"x": 80, "y": 70, "w": 520, "h": 48},
                                    "review_only": True,
                                    "execute_binding_enabled": False,
                                    "artifact_is_authorization": False,
                                },
                                {
                                    "number": "1.2",
                                    "item_id": "stage2_result_card",
                                    "label": "Result card",
                                    "role": "content_card",
                                    "bbox": {"x": 80, "y": 160, "w": 520, "h": 180},
                                    "review_only": True,
                                    "execute_binding_enabled": False,
                                    "artifact_is_authorization": False,
                                },
                            ],
                        }
                    ],
                },
                "execution_evidence": {
                    "stage1_engine": "deterministic_root_partition_v1",
                    "stage2_engine": "deterministic_partition_content_recognition_v1",
                    "actual_model_calls": 0,
                    "legacy_bar_postprocessing_applied": False,
                },
                "fusion": {
                    "compiled_overlay_path": "artifacts/review-overlays/deterministic_fusion.png",
                    "full_screen_understanding_overlay_path": "artifacts/review-overlays/deterministic_fusion.png",
                    "fused_review_boxes": [],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    client = TestClient(app)

    trial_response = client.post(
        "/panel/run_learning_recognition_trial",
        json={
            "app_name": "deterministic_fixture",
            "state_hint": "search_results",
            "summary": "Deterministic partition learning fixture.",
            "two_stage_report_path": "logs/benchmarks/deterministic/report.json",
            "observation_evidence": {
                "contract_version": "panel_learning_draft_observation_evidence_v1",
                "screen_size": {"width": 1000, "height": 800},
                "current_image_path": "artifacts/screenshots/deterministic_fixture.png",
                "calibrated_targets": [],
                "review_boxes": [],
            },
        },
    )
    assert trial_response.status_code == 200
    trial = trial_response.json()
    assert trial["success"] is True
    trial_path = trial["data"]["trial_path"]

    page_detail_response = client.post(
        "/panel/create_page_detail_candidate",
        json={"source_path": trial_path},
    )
    assert page_detail_response.status_code == 200
    page_detail = page_detail_response.json()
    assert page_detail["success"] is True
    page_detail_data = page_detail["data"]
    assert page_detail_data["source_detail_shape"] == "learn_two_stage_screen_understanding_v1"
    assert page_detail_data["summary"]["region_count"] == 2
    assert page_detail_data["summary"]["section_count"] >= 1
    assert page_detail_data["compiled_overlay_path"] == "artifacts/review-overlays/deterministic_fusion.png"

    scaffold_response = client.post(
        "/panel/create_learning_demo_scaffold",
        json={"source_path": page_detail_data["report_path"]},
    )
    assert scaffold_response.status_code == 200
    scaffold = scaffold_response.json()
    assert scaffold["success"] is True
    scaffold_data = scaffold["data"]
    assert scaffold_data["display_readiness"]["pathgraph_detail_can_show_page_detail"] is True
    assert scaffold_data["display_readiness"]["page_detail_readonly_pathgraph_preview_available"] is True
    assert scaffold_data["summary"]["page_detail_readonly_pathgraph_preview_region_count"] == 2
    assert scaffold_data["summary"]["page_detail_readonly_pathgraph_preview_action_count"] >= 1
    assert scaffold_data["safety"]["live_clicks"] == 0
    assert scaffold_data["safety"]["live_fills"] == 0
    assert scaffold_data["safety"]["live_submits"] == 0

    review_response = client.post(
        "/panel/load_learning_draft_review",
        json={"source_path": scaffold_data["report_path"]},
    )
    assert review_response.status_code == 200
    review = review_response.json()
    assert review["success"] is True
    review_data = review["data"]
    assert len(review_data["draft"]["regions"]) == 2
    assert "pathgraph_candidate_review" in review_data
    assert review_data["pathgraph_candidate_review"]["artifact_is_authorization"] is False
    assert review_data["execute_binding_enabled"] is False
    assert review_data["no_click_authorization"] is True


def test_recognition_task_calibrated_target_replay_uses_merged_support_point() -> None:
    from app.learn.workflow_tasks import recognition

    result = recognition._calibrated_target_grounding(
        item={
            "bbox": {"x": 1012, "y": 0, "w": 48, "h": 42},
            "metadata": {
                "source": "vision",
                "layout_cleanup": {
                    "status": "merged_duplicate",
                    "merged_support": {
                        "click_point": {"x": 1036, "y": 21},
                        "coordinate_validation": {
                            "status": "valid",
                            "click_point_present": True,
                            "click_point_inside_bbox": True,
                        },
                        "coordinate_source": "precise_locator_v1",
                    },
                },
            },
        },
        roi_crop={"contract_version": "learn_roi_crop_v1"},
    )

    assert result["screen_point"] == {"x": 1036, "y": 21}
    assert result["debug"]["point_source"] == "layout_cleanup.merged_support.click_point"
    assert result["debug"]["coordinate_source"] == "precise_locator_v1"


def test_panel_learning_recognition_trial_uses_review_boxes_as_read_only_inventory() -> None:
    client = TestClient(app)

    response = client.post(
        "/panel/run_learning_recognition_trial",
        json={
            "app_name": "apple_music",
            "state_hint": "apple_music_home",
            "summary": "Apple Music home screen with albums and section headings.",
            "observation_evidence": {
                "contract_version": "panel_learning_draft_observation_evidence_v1",
                "screen_size": {"width": 1138, "height": 997},
                "current_image_path": "artifacts/screenshots/apple_music.png",
                "coordinate_overlay_path": "artifacts/review-overlays/apple_music_learn_targets.png",
                "review_boxes": [
                    {
                        "candidate_id": "learn_ocr_text_home",
                        "label": "主页",
                        "role": "ocr_text_review_only",
                        "bbox": {"x": 94, "y": 98, "w": 68, "h": 38},
                        "review_status": "ocr_text_review_only",
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    },
                    {
                        "candidate_id": "learn_ocr_text_album",
                        "label": "能量充电",
                        "role": "ocr_text_review_only",
                        "bbox": {"x": 135, "y": 329, "w": 162, "h": 45},
                        "review_status": "ocr_text_review_only",
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    },
                ],
                "calibrated_targets": [],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["execute_binding_enabled"] is False
    assert data["real_clicks"] == 0
    assert data["summary"]["draft_section_counts"]["regions"] >= 2
    assert data["summary"]["draft_section_counts"]["action_templates"] == 0

    trial_path = data["trial_path"]
    review_response = client.post("/panel/load_learning_draft_review", json={"source_path": trial_path})
    assert review_response.status_code == 200
    review = review_response.json()["data"]
    labels = {item["label"] for item in review["draft"]["regions"]}
    assert {"主页", "能量充电"} <= labels
    assert review["draft"]["action_templates"] == []


def test_load_learning_draft_review_accepts_reviewed_candidate_and_top_level_draft(tmp_path: Path) -> None:
    from app.learn.draft_review import load_learning_draft_review

    candidate_path = tmp_path / "artifacts" / "learning-draft-review" / "candidate.json"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
        json.dumps(
            {
                "contract_version": "reviewed_template_candidate_v1",
                "draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "Reviewed search page.",
                    "state_guess": "reviewed_search",
                    "states": [{"state_id": "s_top", "label": "Reviewed state"}],
                    "regions": [{"region_id": "r_top", "label": "Reviewed region"}],
                    "action_templates": [{"action_template_id": "a_top", "label": "Reviewed action"}],
                    "blockers": [{"blocker_id": "b_top", "label": "Final submit blocked"}],
                    "verification_rules": [{"rule_id": "v_top", "label": "Verify reviewed field"}],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    review = load_learning_draft_review(candidate_path, project_root=tmp_path)

    assert review["draft"]["state_guess"] == "reviewed_search"
    assert review["draft"]["states"][0]["state_id"] == "s_top"
    assert review["draft"]["regions"][0]["region_id"] == "r_top"
    assert review["draft"]["action_templates"][0]["action_template_id"] == "a_top"
    assert review["draft"]["blockers"][0]["blocker_id"] == "b_top"
    assert review["draft"]["verification_rules"][0]["rule_id"] == "v_top"


def test_save_reviewed_template_candidate_forces_mixed_source_and_safety(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    trial_path = tmp_path / "artifacts" / "learning-runs" / "sample" / "trial_result.json"
    _write_trial(trial_path)

    result = save_reviewed_template_candidate(
        trial_path,
        {
            "review_status": "approved_as_assisted_template",
            "source_after_review": "pure_model_generated",
            "artifact_is_authorization": True,
            "execute_binding_enabled": True,
            "final_submit_forbidden": False,
            "blockers": [
                {
                    "blocker_id": "b1",
                    "label": "Final submit remains blocked",
                    "linked_action_template_id": "a1",
                    "linked_region_id": "r1",
                }
            ],
            "verification_rules": [
                {
                    "rule_id": "v1",
                    "label": "Search field text is visible before continuing",
                    "linked_action_template_id": "a1",
                    "linked_region_id": "r1",
                }
            ],
            "region_label_updates": {"r1": "Reviewed search input"},
            "action_label_updates": {"a1": "Reviewed type query"},
            "action_region_bindings": {"a1": "r1"},
        },
        project_root=tmp_path,
    )

    output_path = tmp_path / result["reviewed_template_candidate_path"]
    candidate = json.loads(output_path.read_text(encoding="utf-8"))

    assert candidate["contract_version"] == "reviewed_template_candidate_v1"
    assert candidate["review_status"] == "approved_as_assisted_template"
    assert candidate["source_after_review"] == "mixed"
    assert candidate["counts_as_pure_model_generated"] is False
    assert candidate["artifact_is_authorization"] is False
    assert candidate["final_submit_forbidden"] is True
    assert candidate["real_action_requires_gate"] is True
    assert candidate["execute_binding_enabled"] is False
    assert candidate["authorization_scope"] == "display_and_review_only"
    assert candidate["reviewed_by_human"] is True
    assert candidate["draft"]["regions"][0]["label"] == "Reviewed search input"
    assert candidate["draft"]["action_templates"][0]["label"] == "Reviewed type query"
    assert candidate["draft"]["action_templates"][0]["target_entity"] == "r1"
    assert candidate["draft"]["blockers"][0]["blocker_id"] == "b1"
    assert candidate["draft"]["verification_rules"][0]["rule_id"] == "v1"
    assert candidate["audit"]["source_trial_path"] == "artifacts/learning-runs/sample/trial_result.json"
    assert candidate["audit"]["changes_summary"]


def test_save_interface_workflow_node_review_skips_related_sidecar_discovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.learn.draft_review as draft_review_module

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "workspace.png"
    screenshot_path.parent.mkdir(parents=True)
    Image.new("RGB", (320, 180), "white").save(screenshot_path)
    source_path = _write_json(
        tmp_path
        / "artifacts"
        / "interface-workflow-reviews"
        / "workflow_demo"
        / "node-review-sources"
        / "workspace.json",
        {
            "contract_version": "interface_workflow_node_review_source_v1",
            "workflow_id": "workflow_demo",
            "node_id": "workspace",
            "draft": {
                "contract_version": "learning_template_draft_v1",
                "screen_summary": "Operations Workspace",
                "state_guess": "workspace",
                "states": [],
                "regions": [],
                "action_templates": [],
                "blockers": [],
                "verification_rules": [],
                "page_details": {
                    "screen": {
                        "summary": "Operations Workspace",
                        "source_image_path": "artifacts/screenshots/workspace.png",
                    }
                },
                "safety": {
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                    "final_submit_forbidden": True,
                },
            },
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
    )
    calls: list[bool] = []
    original = draft_review_module._learning_demo_artifact_review

    def capture_discovery(*args, discover_related_sidecars: bool = True, **kwargs):
        calls.append(discover_related_sidecars)
        return original(
            *args,
            discover_related_sidecars=discover_related_sidecars,
            **kwargs,
        )

    monkeypatch.setattr(
        draft_review_module,
        "_learning_demo_artifact_review",
        capture_discovery,
    )

    result = draft_review_module.save_reviewed_template_candidate(
        source_path,
        {"review_status": "needs_human_review"},
        project_root=tmp_path,
    )

    assert calls == [False]
    assert (tmp_path / result["reviewed_template_candidate_path"]).is_file()


def test_save_reviewed_template_candidate_accepts_review_only_pathgraph_additions(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    trial_path = tmp_path / "artifacts" / "learning-runs" / "sample" / "trial_result.json"
    _write_trial(trial_path)

    result = save_reviewed_template_candidate(
        trial_path,
        {
            "review_status": "needs_human_review",
            "source_after_review": "assisted_generation",
            "state_additions": [
                {
                    "state_id": "model_detail_view",
                    "state_role": "detail_view",
                    "candidate_only": True,
                }
            ],
            "action_template_additions": [
                {
                    "action_template_id": "fusion_open_detail_region_4",
                    "label": "Open detail candidate",
                    "semantic_action": "open_detail",
                    "target_entity": "r1",
                    "execute_binding_enabled": True,
                    "artifact_is_authorization": True,
                }
            ],
            "transition_additions": [
                {
                    "transition_id": "preflight_transition_fusion_open_detail_region_4",
                    "transition_type": "open_detail",
                    "from_state_id": "seek_results",
                    "to_state_id": "model_detail_view",
                    "action_template_id": "fusion_open_detail_region_4",
                    "execute_binding_enabled": True,
                    "artifact_is_authorization": True,
                }
            ],
        },
        project_root=tmp_path,
    )

    candidate = json.loads((tmp_path / result["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))
    added_action = next(item for item in candidate["draft"]["action_templates"] if item["action_template_id"] == "fusion_open_detail_region_4")
    added_transition = next(item for item in candidate["draft"]["transitions"] if item["transition_id"] == "preflight_transition_fusion_open_detail_region_4")
    assert any(item["state_id"] == "model_detail_view" for item in candidate["draft"]["states"])
    assert added_action["semantic_action"] == "open_detail"
    assert added_action["execute_binding_enabled"] is False
    assert added_action["artifact_is_authorization"] is False
    assert added_action["candidate_only"] is True
    assert added_transition["transition_type"] == "open_detail"
    assert added_transition["execute_binding_enabled"] is False
    assert added_transition["artifact_is_authorization"] is False
    assert added_transition["candidate_only"] is True
    assert "state_additions:1" in candidate["audit"]["changes_summary"]
    assert "action_template_additions:1" in candidate["audit"]["changes_summary"]
    assert "transition_additions:1" in candidate["audit"]["changes_summary"]


def test_panel_learning_draft_review_routes_load_and_save(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    trial_path = tmp_path / "artifacts" / "learning-runs" / "sample" / "trial_result.json"
    _write_trial(trial_path)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    load_payload = client.post(
        "/panel/load_learning_draft_review",
        json={"source_path": "artifacts/learning-runs/sample/trial_result.json"},
    ).json()

    assert load_payload["success"] is True
    assert load_payload["data"]["review_status"] == "needs_human_review"
    assert load_payload["data"]["no_click_authorization"] is True
    assert load_payload["data"]["execute_binding_enabled"] is False

    save_payload = client.post(
        "/panel/save_learning_draft_review",
        json={
            "source_path": "artifacts/learning-runs/sample/trial_result.json",
            "review_patch": {
                "review_status": "needs_human_review",
                "blockers": [{"blocker_id": "b1", "label": "Needs final safety review"}],
            },
        },
    ).json()

    assert save_payload["success"] is True
    saved_path = tmp_path / save_payload["data"]["reviewed_template_candidate_path"]
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["artifact_is_authorization"] is False
    assert saved["execute_binding_enabled"] is False


def test_panel_learning_draft_review_fast_load_skips_related_sidecar_discovery(
    monkeypatch,
) -> None:
    import app.api.panel as panel_api

    calls: list[dict[str, object]] = []

    def fake_load_learning_draft_review(
        source_path,
        *,
        project_root,
        discover_related_sidecars,
    ):
        calls.append(
            {
                "source_path": source_path,
                "project_root": project_root,
                "discover_related_sidecars": discover_related_sidecars,
            }
        )
        return {
            "contract_version": "learning_draft_review_v1",
            "source": {"source_path": source_path},
            "draft": {"regions": [], "action_templates": []},
        }

    monkeypatch.setattr(panel_api, "load_learning_draft_review", fake_load_learning_draft_review)
    monkeypatch.setattr(panel_api, "write_trace", lambda **_kwargs: "logs/traces/fast-load.json")

    response = panel_api.load_learning_draft_review_endpoint(
        panel_api.PanelLoadLearningDraftReviewRequest(
            source_path="artifacts/learning-runs/sample/trial_result.json",
            discover_related_sidecars=False,
        )
    )

    assert response.success is True
    assert calls == [
        {
            "source_path": "artifacts/learning-runs/sample/trial_result.json",
            "project_root": panel_api.ROOT_DIR,
            "discover_related_sidecars": False,
        }
    ]


def test_panel_attaches_detail_observe_result_review_only(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    results_path = tmp_path / "artifacts" / "learning-runs" / "open-detail" / "trial_result.json"
    detail_path = tmp_path / "artifacts" / "learning-runs" / "detail" / "trial_result.json"
    _write_open_detail_trial(results_path)
    _write_detail_surface_trial(detail_path)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    build_payload = client.post(
        "/panel/generate_pathgraph_candidate",
        json={
            "source_path": "artifacts/learning-runs/open-detail/trial_result.json",
            "review_patch": {"review_status": "approved_as_assisted_template"},
        },
    ).json()
    assert build_payload["success"] is True

    attach_payload = client.post(
        "/panel/attach_detail_observe_result",
        json={
            "candidate_path": build_payload["data"]["pathgraph_candidate_path"],
            "request_id": "detail_observe:open_card_1",
            "detail_source_path": "artifacts/learning-runs/detail/trial_result.json",
        },
    ).json()

    assert attach_payload["success"] is True
    data = attach_payload["data"]
    assert data["contract_version"] == "detail_observe_attachment_result_v1"
    assert data["execute_binding_enabled"] is False
    assert data["artifact_is_authorization"] is False
    assert data["detail_surface_attachments"][0]["no_dispatch"] is True
    assert data["precise_understanding_summary"]["detail_surface_attachment_count"] == 1
    assert data["pending_detail_observe_requests"][0]["request_id"] == "detail_observe:open_card_1"
    assert data["pending_detail_observe_requests"][0]["status"] == "attached"
    assert data["trace_path"]


def test_panel_lists_recent_learning_draft_sources(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    pinned_source = (
        tmp_path
        / "logs"
        / "benchmarks"
        / "learn_pathgraph_readiness_with_handoff_20260706"
        / "actual_parser_output_with_fusion_status.json"
    )
    detail_path = tmp_path / "artifacts" / "learning-runs" / "detail" / "trial_result.json"
    reviewed_source = tmp_path / "artifacts" / "learning-draft-review" / "sample" / "reviewed_template_candidate.json"
    candidate_dir = tmp_path / "artifacts" / "learning-draft-review" / "sample" / "pathgraph_candidate"
    candidate_source = candidate_dir / "pathgraph_candidate.json"
    validation_source = candidate_dir / "promotion_validation_report.json"
    preflight_source = candidate_dir / "learn_fusion_model_start_preflight_report.json"
    demo_readiness_source = candidate_dir / "learn_fusion_demo_readiness_report.json"
    approval_packet_source = candidate_dir / "learn_fusion_model_start_approval_packet.json"
    calibration_pre_run_source = candidate_dir / "learn_fusion_calibration_pre_run_check_report.json"
    pathgraph_integration_source = candidate_dir / "learn_fusion_pathgraph_integration_readiness_report.json"
    current_evidence_packet_source = candidate_dir / "learn_fusion_current_evidence_packet.json"
    demo_goal_readiness_source = candidate_dir / "learning_mode_demo_goal_readiness_report.json"
    bad_path = tmp_path / "artifacts" / "learning-runs" / "bad" / "trial_result.json"
    _write_detail_surface_trial(pinned_source)
    pinned_payload = json.loads(pinned_source.read_text(encoding="utf-8"))
    pinned_payload["best_learning_draft"]["page_details"] = {
        "pipeline_audit": {
            "precise_understanding_fusion_status": {
                "full_screen_understanding_overlay_path": "logs/benchmarks/learn_pathgraph_readiness_with_handoff_20260706/full_screen_understanding_overlay.png",
                "compiled_overlay_path": "logs/benchmarks/learn_pathgraph_readiness_with_handoff_20260706/compiled_overlay.png",
                "summary": {
                    "total_locator_cards": 10,
                    "calibrated_cases": 2,
                    "uncalibrated_locator_cards": 8,
                    "calibration_coverage_rate": 0.2,
                    "real_clicks": 0,
                },
                "precise_understanding_readiness_summary": {
                    "readiness_status": "needs_pending_calibration",
                    "calibration_coverage_rate": 0.2,
                    "pending_calibration_ready_count": 6,
                    "pending_calibration_review_count": 2,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "calibration_batch_plan": {
                    "summary": {
                        "ready_for_execute_dry_run": 6,
                        "review_before_calibration": 2,
                        "execute_binding_enabled": False,
                    },
                    "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "review_blocked_region_numbers": [7, 10],
                    "command_executes_now": False,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "calibration_handoff_report": {
                    "handoff_status": "ready_for_explicit_model_start",
                    "safe_to_start_after_user_approval": True,
                    "future_outputs": {"rerun_report_status": "awaiting_future_calibration_output"},
                    "safety": {
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                        "real_clicks": 0,
                    },
                },
                "calibration_handoff_consistency_report": {
                    "consistency_status": "ready_for_explicit_model_start",
                    "summary": {
                        "post_batch_refresh_has_batch_plan": True,
                        "refresh_blocks_before_future_rerun": True,
                    },
                    "blockers": [],
                    "safety": {
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                        "model_started": False,
                        "live_clicks": 0,
                    },
                },
                "model_start_runbook": {
                    "runbook_status": "awaiting_explicit_model_start_approval",
                    "approval_required": True,
                    "may_start_model_after_user_approval": True,
                    "may_run_calibration_batch_now": False,
                    "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "review_blocked_region_numbers": [7, 10],
                    "guards": {
                        "post_batch_refresh_has_batch_plan": True,
                        "prebatch_refresh_blocks_before_future_rerun": True,
                    },
                    "safety": {
                        "model_started": False,
                        "live_clicks": 0,
                        "live_fills": 0,
                        "live_submits": 0,
                    },
                    "blockers": [],
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        }
    }
    pinned_source.write_text(json.dumps(pinned_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_detail_surface_trial(detail_path)
    _write_detail_surface_trial(reviewed_source)
    candidate_dir.mkdir(parents=True, exist_ok=True)
    validation_source.write_text(
        json.dumps(
            {
                "contract_version": "pathgraph_candidate_validation_report_v1",
                "validation_status": "blocked_pending_calibration",
                "summary": {"ready_for_runtime_pathgraph_promotion": False},
                "safety": {"execute_binding_enabled": False, "artifact_is_authorization": False},
                "model_start_runbook": {
                    "runbook_status": "awaiting_explicit_model_start_approval",
                    "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "review_blocked_region_numbers": [7, 10],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    candidate_source.write_text(
        json.dumps(
            {
                "contract_version": "pathgraph_candidate_v1",
                "reviewed_template_candidate_path": "artifacts/learning-draft-review/sample/reviewed_template_candidate.json",
                "validation_report_path": "artifacts/learning-draft-review/sample/pathgraph_candidate/promotion_validation_report.json",
                "validation_status": "blocked_pending_calibration",
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                "model_start_runbook": {
                    "runbook_status": "awaiting_explicit_model_start_approval",
                    "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "review_blocked_region_numbers": [7, 10],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    preflight_source.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_model_start_preflight_v1",
                "preflight_status": "ready_for_explicit_model_start",
                "may_start_model_after_user_approval": True,
                "may_run_calibration_batch_now": False,
                "candidate_validation_status": "blocked_pending_calibration",
                "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                "review_blocked_region_numbers": [7, 10],
                "safety": {
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "blockers": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    demo_readiness_source.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_demo_readiness_v1",
                "demo_readiness_status": "ready_for_preflight_demo",
                "recommended_load_path": "artifacts/learning-draft-review/sample/pathgraph_candidate/pathgraph_candidate.json",
                "candidate_validation_status": "blocked_pending_calibration",
                "preflight_status": "ready_for_explicit_model_start",
                "may_run_calibration_batch_now": False,
                "safety": {
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "blockers": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    approval_packet_source.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_model_start_approval_packet_v1",
                "approval_packet_status": "ready_for_user_approval",
                "requires_explicit_user_approval": True,
                "approval_does_not_execute": True,
                "may_start_model_after_user_approval": True,
                "may_run_calibration_batch_now": False,
                "candidate_validation_status": "blocked_pending_calibration",
                "preflight_status": "ready_for_explicit_model_start",
                "demo_readiness_status": "ready_for_preflight_demo",
                "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                "review_blocked_region_numbers": [7, 10],
                "safety": {
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "blockers": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    approval_packet_sha256 = hashlib.sha256(approval_packet_source.read_bytes()).hexdigest()
    calibration_pre_run_source.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_calibration_pre_run_check_v1",
                "pre_run_status": "ready_after_explicit_approval",
                "approval_packet_path": str(approval_packet_source.relative_to(tmp_path)),
                "approval_packet_sha256": approval_packet_sha256,
                "requires_explicit_user_approval": True,
                "may_start_model_after_user_approval": True,
                "may_run_calibration_batch_now": False,
                "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                "command_region_numbers": [1, 2, 3, 6, 8, 9],
                "safety": {
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "model_runtime_snapshot": {
                    "contract_version": "model_runtime_snapshot_v1",
                    "checked_at": "2026-07-06T09:30:00+12:00",
                    "model_ports_clear": True,
                    "model_processes_clear": True,
                    "listening_ports": [],
                    "suspected_model_processes": [],
                },
                "blockers": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    pathgraph_integration_source.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_pathgraph_integration_readiness_report_v1",
                "integration_readiness_status": "blocked_pending_calibration",
                "report_path": "artifacts/learning-draft-review/sample/pathgraph_candidate/learn_fusion_pathgraph_integration_readiness_report.json",
                "candidate_validation_status": "blocked_pending_calibration",
                "ready_for_audited_pathgraph_review": False,
                "ready_for_runtime_pathgraph_promotion": False,
                "blockers": ["pending_calibration_required"],
                "safety": {
                    "display_only": True,
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                    "runtime_pathgraph_promotion": False,
                },
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    current_evidence_packet_source.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_current_evidence_packet_v1",
                "report_path": "artifacts/learning-draft-review/sample/pathgraph_candidate/learn_fusion_current_evidence_packet.json",
                "calibration": {
                    "readiness_summary": {
                        "readiness_status": "needs_pending_calibration",
                        "calibration_coverage_rate": 0.2,
                        "pending_calibration_ready_count": 6,
                        "pending_calibration_review_count": 2,
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    },
                    "batch_ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "batch_review_blocked_region_numbers": [7, 10],
                },
                "pathgraph": {
                    "integration_readiness_status": "blocked_pending_calibration",
                    "ready_for_runtime_pathgraph_promotion_after_integration": False,
                },
                "safety": {
                    "display_only": True,
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                    "runtime_pathgraph_promotion": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    demo_goal_readiness_source.write_text(
        json.dumps(
            {
                "contract_version": "learning_mode_demo_goal_readiness_v1",
                "report_path": "artifacts/learning-draft-review/sample/pathgraph_candidate/learning_mode_demo_goal_readiness_report.json",
                "demo_goal_status": "display_demo_ready_official_goal_blocked",
                "display_demo_ready": True,
                "final_goal_complete": False,
                "blocking_reasons": [
                    "official_candidate_not_fully_system_model_generated",
                    "pending_calibration_remaining",
                ],
                "summary": {
                    "passed_requirement_count": 7,
                    "failed_requirement_count": 2,
                    "not_covered_requirement_count": 0,
                },
                "fresh_model_chain_acceptance": {
                    "contract_version": "learning_mode_fresh_model_chain_acceptance_v1",
                    "acceptance_status": "blocked_mixed_or_assisted_evidence",
                    "accepted": False,
                    "counts_as_final_goal_completion": False,
                    "actual_model_call_evidence_count": 1,
                    "assisted_or_human_review_evidence_count": 2,
                    "source_breakdown": {
                        "actual_model_call": 1,
                        "assisted_or_human_review": 2,
                        "fixture_only": 0,
                        "recorded_model_output": 0,
                    },
                    "blocking_reasons": [
                        "contains_assisted_or_human_review_evidence",
                        "pending_calibration_remaining",
                    ],
                    "replacement_plan": {
                        "contract_version": "learning_mode_fresh_model_chain_replacement_plan_v1",
                        "replacement_required": True,
                        "plan_status": "blocked_until_explicit_model_start_approval",
                        "sources_to_replace": ["assisted_or_human_review"],
                        "required_source_type": "actual_model_call",
                        "replacement_steps": [
                            {
                                "step_id": "obtain_explicit_model_start_approval",
                                "command_executes_now": False,
                            },
                            {
                                "step_id": "run_fresh_numbered_region_calibration",
                                "command_executes_now": False,
                            },
                            {
                                "step_id": "refresh_model_generated_scaffold",
                                "command_executes_now": False,
                            },
                            {
                                "step_id": "rerun_goal_readiness_audit",
                            },
                        ],
                    },
                },
                "presentation_acceptance": {
                    "contract_version": "learning_interface_presentation_acceptance_v1",
                    "accepted": False,
                    "acceptance_status": "not_covered",
                    "same_source_three_image_evidence": False,
                    "frontend_revision_matches": False,
                    "desktop_viewport_covered": False,
                    "narrow_viewport_covered": False,
                    "blocking_reasons": ["missing_presentation_evidence"],
                },
                "demo_chain_manifest": {
                    "contract_version": "learning_mode_demo_chain_manifest_v1",
                    "demo_stage_order": [
                        "full_screen_understanding_numbered_regions",
                        "selection_map_precise_understanding",
                        "pathgraph_model_preview",
                        "template_like_page_detail",
                    ],
                    "chain_can_be_demoed": True,
                    "chain_is_final_goal_complete": False,
                    "final_goal_blockers": [
                        "official_candidate_not_fully_system_model_generated",
                        "pending_calibration_remaining",
                    ],
                    "steps": [
                        {
                            "stage_id": "full_screen_understanding_numbered_regions",
                            "stage_ready_for_display": True,
                            "proof_fields": ["artifact_sha256_prefix"],
                        },
                        {
                            "stage_id": "selection_map_precise_understanding",
                            "stage_ready_for_display": True,
                            "proof_fields": ["artifact_sha256_prefix", "region_count"],
                        },
                        {
                            "stage_id": "pathgraph_model_preview",
                            "stage_ready_for_display": True,
                            "proof_fields": ["action_count", "artifact_sha256_prefix", "region_count"],
                        },
                        {
                            "stage_id": "template_like_page_detail",
                            "stage_ready_for_display": True,
                            "proof_fields": [
                                "artifact_sha256_prefix",
                                "bbox_region_count",
                                "layout_mode",
                                "layout_section_count",
                                "operation_kinds",
                                "readiness_status",
                            ],
                        },
                    ],
                },
                "safety": {
                    "display_only": True,
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                    "runtime_pathgraph_promotion": False,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(
        panel_api,
        "PINNED_LEARNING_DRAFT_SOURCE_PATHS",
        [
            "logs/benchmarks/learn_pathgraph_readiness_with_handoff_20260706/actual_parser_output_with_fusion_status.json"
        ],
    )

    client = TestClient(app)
    payload = client.get("/panel/learning_draft_sources", params={"limit": 16, "include_recent": "true"}).json()

    assert payload["success"] is True
    data = payload["data"]
    assert data["contract_version"] == "panel_learning_draft_sources_v1"
    source_paths = [item["source_path"] for item in data["sources"]]
    assert source_paths[0] == "logs/benchmarks/learn_pathgraph_readiness_with_handoff_20260706/actual_parser_output_with_fusion_status.json"
    assert data["sources"][0]["source_category"] == "recommended_current_precise_understanding"
    assert data["sources"][0]["pinned"] is True
    assert data["sources"][0]["readiness_status"] == "needs_pending_calibration"
    assert data["sources"][0]["calibration_coverage_rate"] == 0.2
    assert data["sources"][0]["pending_calibration_ready_count"] == 6
    assert data["sources"][0]["handoff_status"] == "ready_for_explicit_model_start"
    assert data["sources"][0]["rerun_report_status"] == "awaiting_future_calibration_output"
    assert data["sources"][0]["safe_to_start_after_user_approval"] is True
    assert data["sources"][0]["consistency_status"] == "ready_for_explicit_model_start"
    assert data["sources"][0]["post_batch_refresh_has_batch_plan"] is True
    assert data["sources"][0]["refresh_blocks_before_future_rerun"] is True
    assert data["sources"][0]["consistency_blocker_count"] == 0
    assert data["sources"][0]["runbook_status"] == "awaiting_explicit_model_start_approval"
    assert data["sources"][0]["approval_required"] is True
    assert data["sources"][0]["may_start_model_after_user_approval"] is True
    assert data["sources"][0]["may_run_calibration_batch_now"] is False
    assert data["sources"][0]["runbook_ready_region_count"] == 6
    assert data["sources"][0]["runbook_review_blocked_region_count"] == 2
    assert data["sources"][0]["runbook_blocker_count"] == 0
    assert "artifacts/learning-runs/detail/trial_result.json" in source_paths
    assert "artifacts/learning-draft-review/sample/reviewed_template_candidate.json" in source_paths
    candidate_entry = next(
        item
        for item in data["sources"]
        if item["source_path"] == "artifacts/learning-draft-review/sample/reviewed_template_candidate.json"
        and item.get("pathgraph_candidate_path") == "artifacts/learning-draft-review/sample/pathgraph_candidate/pathgraph_candidate.json"
    )
    assert candidate_entry["preflight_status"] == "ready_for_explicit_model_start"
    assert candidate_entry["preflight_may_start_model_after_user_approval"] is True
    assert candidate_entry["preflight_may_run_calibration_batch_now"] is False


    assert candidate_entry["preflight_blocker_count"] == 0
    assert candidate_entry["demo_readiness_status"] == "ready_for_preflight_demo"
    assert candidate_entry["demo_readiness_may_run_calibration_batch_now"] is False
    assert candidate_entry["demo_readiness_blocker_count"] == 0
    assert candidate_entry["approval_packet_status"] == "ready_for_user_approval"
    assert candidate_entry["approval_packet_requires_explicit_user_approval"] is True
    assert candidate_entry["approval_packet_may_run_calibration_batch_now"] is False
    assert candidate_entry["approval_packet_blocker_count"] == 0
    assert candidate_entry["calibration_pre_run_status"] == "ready_after_explicit_approval"
    assert candidate_entry["calibration_pre_run_may_run_calibration_batch_now"] is False
    assert candidate_entry["calibration_pre_run_checked_at"] == "2026-07-06T09:30:00+12:00"
    assert candidate_entry["calibration_pre_run_model_ports_clear"] is True
    assert candidate_entry["calibration_pre_run_model_processes_clear"] is True
    assert candidate_entry["calibration_pre_run_approval_packet_checksum_status"] == "matched"
    assert candidate_entry["pathgraph_integration_status"] == "blocked_pending_calibration"
    assert candidate_entry["pathgraph_integration_ready_for_audited_review"] is False
    assert candidate_entry["pathgraph_integration_ready_for_runtime_promotion"] is False
    assert candidate_entry["pathgraph_integration_blocker_count"] == 1
    assert (
        candidate_entry["pathgraph_integration_report_path"]
        == "artifacts/learning-draft-review/sample/pathgraph_candidate/learn_fusion_pathgraph_integration_readiness_report.json"
    )
    assert candidate_entry["current_evidence_packet_status"] == "available"
    assert (
        candidate_entry["current_evidence_packet_path"]
        == "artifacts/learning-draft-review/sample/pathgraph_candidate/learn_fusion_current_evidence_packet.json"
    )
    assert candidate_entry["current_evidence_packet_coverage"] == 0.2
    assert candidate_entry["current_evidence_packet_integration_status"] == "blocked_pending_calibration"
    assert candidate_entry["current_evidence_packet_runtime_promotion"] is False
    assert candidate_entry["current_evidence_packet_model_started"] is False
    assert candidate_entry["learning_demo_goal_status"] == "display_demo_ready_official_goal_blocked"
    assert candidate_entry["learning_demo_chain_can_be_demoed"] is True
    assert candidate_entry["learning_demo_chain_final_complete"] is False
    assert candidate_entry["learning_demo_chain_ready_step_count"] == 4
    assert candidate_entry["learning_demo_chain_total_step_count"] == 4
    assert candidate_entry["learning_demo_chain_missing_proof_count"] == 0
    assert candidate_entry["learning_demo_chain_blocker_count"] == 2
    assert candidate_entry["fresh_model_acceptance_status"] == "blocked_mixed_or_assisted_evidence"
    assert candidate_entry["fresh_model_chain_accepted"] is False
    assert candidate_entry["fresh_model_counts_as_final_goal_completion"] is False
    assert candidate_entry["fresh_model_actual_model_call_evidence_count"] == 1
    assert candidate_entry["fresh_model_assisted_or_human_review_evidence_count"] == 2
    assert candidate_entry["fresh_model_acceptance_blocker_count"] == 2
    assert candidate_entry["fresh_model_source_breakdown_actual_model_call"] == 1
    assert candidate_entry["fresh_model_source_breakdown_assisted_or_human_review"] == 2
    assert candidate_entry["fresh_model_replacement_required"] is True
    assert candidate_entry["fresh_model_replacement_plan_status"] == "blocked_until_explicit_model_start_approval"
    assert candidate_entry["fresh_model_replacement_sources_to_replace"] == ["assisted_or_human_review"]
    assert candidate_entry["fresh_model_replacement_required_source_type"] == "actual_model_call"
    assert candidate_entry["fresh_model_replacement_step_count"] == 4
    assert candidate_entry["presentation_acceptance_status"] == "not_covered"
    assert candidate_entry["presentation_accepted"] is False
    assert candidate_entry["presentation_same_source_three_image_evidence"] is False
    assert candidate_entry["presentation_frontend_revision_matches"] is False
    assert candidate_entry["presentation_desktop_viewport_covered"] is False
    assert candidate_entry["presentation_narrow_viewport_covered"] is False
    assert candidate_entry["presentation_blocker_count"] == 1
    assert candidate_entry["fresh_model_replacement_command_executes_now_count"] == 0
    assert candidate_entry["candidate_validation_status"] == "blocked_pending_calibration"
    assert "artifacts/learning-runs/bad/trial_result.json" not in source_paths
    first = next(item for item in data["sources"] if item["source_path"] == "artifacts/learning-runs/detail/trial_result.json")
    assert first["screen_summary"] == "SEEK detail pane for selected job."
    assert first["state_guess"] == "seek_job_detail"
    assert first["action_template_count"] == 1
    assert first["execute_binding_enabled"] is False
    assert first["artifact_is_authorization"] is False
    assert data["skipped_count"] == 1


def test_panel_does_not_inject_legacy_benchmark_sources_into_current_evidence_library() -> None:
    import app.api.panel as panel_api

    assert panel_api.PINNED_LEARNING_DRAFT_SOURCE_PATHS == []


def test_panel_does_not_fall_back_to_legacy_benchmark_sources(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    benchmark_source = tmp_path / "logs" / "benchmarks" / "legacy" / "learn_mode_demo_scaffold.json"
    _write_detail_surface_trial(benchmark_source)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    data = panel_api._list_recent_learning_draft_sources(limit=10)

    assert data["sources"] == []
    assert data["targeted_benchmark_scan_performed"] is False
    assert data["targeted_benchmark_roots"] == []


def test_panel_learning_draft_sources_limits_pinned_entries_to_current_demo_set(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    pinned_paths = [
        "logs/benchmarks/current_a/learn_mode_demo_scaffold.json",
        "logs/benchmarks/current_b/learn_mode_demo_scaffold.json",
        "logs/benchmarks/current_c/learn_mode_demo_scaffold.json",
        "logs/benchmarks/legacy_v105/learn_mode_demo_scaffold.json",
    ]
    for index, path_text in enumerate(pinned_paths):
        path = tmp_path / path_text
        _write_detail_surface_trial(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["best_learning_draft"]["screen_summary"] = f"pinned {index}"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(panel_api, "PINNED_LEARNING_DRAFT_SOURCE_PATHS", pinned_paths)

    data = panel_api._list_recent_learning_draft_sources(limit=10)
    pinned_sources = [item for item in data["sources"] if item.get("pinned") is True]

    assert data["max_pinned_sources"] == 3
    assert [item["source_path"] for item in pinned_sources] == pinned_paths[:3]
    assert pinned_paths[3] not in [item["source_path"] for item in data["sources"]]


def test_panel_learning_draft_sources_recommends_latest_display_complete_draft(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    pinned_path_text = "logs/benchmarks/pinned/learn_mode_demo_scaffold.json"
    pinned_path = tmp_path / pinned_path_text
    _write_json(
        pinned_path,
        {
            "contract_version": "learn_mode_demo_scaffold_v1",
            "page_detail_candidate": {
                "contract_version": "learn_page_detail_candidate_v1",
                "screen_summary": "Pinned review source",
                "layout": {
                    "bounds": {"x": 0, "y": 0, "w": 320, "h": 240},
                    "sections": [{"section_id": "main", "label": "Main", "bbox": {"x": 0, "y": 0, "w": 320, "h": 240}}],
                    "regions": [{"region_id": "r1", "label": "Main", "role": "review_only", "source_section_id": "main", "bbox": {"x": 10, "y": 10, "w": 100, "h": 80}}],
                },
            },
        },
    )

    current_path = tmp_path / "artifacts" / "learning-runs" / "current" / "trial_result.json"
    _write_trial(current_path)
    screenshot_path = tmp_path / "artifacts" / "screenshots" / "current.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(b"display evidence")
    current_payload = json.loads(current_path.read_text(encoding="utf-8"))
    current_payload["best_learning_draft"]["page_details"] = {
        "screen": {"image_path": "artifacts/screenshots/current.png"}
    }
    current_path.write_text(json.dumps(current_payload, ensure_ascii=False), encoding="utf-8")

    stale_intermediate = tmp_path / "artifacts" / "learning-runs" / "newer" / "final_stage2_for_calibration.json"
    _write_trial(stale_intermediate)
    stale_intermediate.touch()

    for index in range(8):
        incomplete_path = (
            tmp_path
            / "artifacts"
            / "learning-runs"
            / f"newer_incomplete_{index}"
            / "trial_result.json"
        )
        _write_trial(incomplete_path)

    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(panel_api, "PINNED_LEARNING_DRAFT_SOURCE_PATHS", [pinned_path_text])

    payload = TestClient(app).get("/panel/learning_draft_sources").json()

    assert payload["success"] is True
    data = payload["data"]
    sources = data["sources"]
    recommended = [item for item in sources if item.get("recommended_for_panel_review") is True]
    assert data["include_recent"] is True
    assert len(recommended) == 1
    assert recommended[0]["source_path"] == "artifacts/learning-runs/current/trial_result.json"
    assert recommended[0]["display_completeness_status"] == "ready"
    assert recommended[0]["source_image_path"] == "artifacts/screenshots/current.png"
    assert recommended[0]["source_image_exists"] is True
    assert recommended[0]["pinned"] is False
    assert not any(item["source_path"].endswith("final_stage2_for_calibration.json") for item in sources)
    assert data["candidate_scan_count"] >= 9


def test_panel_learning_draft_sources_avoids_unbounded_recursive_glob(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    pinned_path_text = "logs/benchmarks/pinned/learn_mode_demo_scaffold.json"
    pinned_path = tmp_path / pinned_path_text
    _write_json(
        pinned_path,
        {
            "contract_version": "learn_mode_demo_scaffold_v1",
            "page_detail_candidate": {
                "contract_version": "learn_page_detail_candidate_v1",
                "screen_summary": "Pinned review source",
                "layout": {
                    "bounds": {"x": 0, "y": 0, "w": 320, "h": 240},
                    "sections": [
                        {"section_id": "main", "label": "Main", "bbox": {"x": 0, "y": 0, "w": 320, "h": 240}}
                    ],
                    "regions": [
                        {
                            "region_id": "r1",
                            "label": "Main",
                            "role": "review_only",
                            "source_section_id": "main",
                            "bbox": {"x": 10, "y": 10, "w": 100, "h": 80},
                        }
                    ],
                },
            },
        },
    )
    current_path = tmp_path / "artifacts" / "learning-runs" / "current" / "trial_result.json"
    _write_trial(current_path)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(panel_api, "PINNED_LEARNING_DRAFT_SOURCE_PATHS", [pinned_path_text])

    def fail_rglob(*args, **kwargs):
        raise AssertionError("unbounded Path.rglob must not be used for panel history discovery")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    data = panel_api._list_recent_learning_draft_sources(limit=3)

    assert data["candidate_scan_count"] == 1
    assert {item["source_path"] for item in data["sources"]} == {
        pinned_path_text,
        "artifacts/learning-runs/current/trial_result.json",
    }


def test_learning_review_loads_adjacent_sidecar_before_global_search(tmp_path: Path, monkeypatch) -> None:
    import app.learn.draft_review as draft_review

    wrapper_path = tmp_path / "logs" / "case" / "wrapper.json"
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text("{}", encoding="utf-8")
    sidecar_path = wrapper_path.parent / "learn_page_detail_candidate.json"
    sidecar_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_page_detail_candidate_v1",
                "source_path": "logs/case/wrapper.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fail_rglob(*args, **kwargs):
        raise AssertionError("global sidecar rglob must not run when the adjacent sidecar matches")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    result = draft_review._load_sidecar_by_source_path(
        wrapper_path=wrapper_path,
        root=tmp_path,
        file_name="learn_page_detail_candidate.json",
        contract_version="learn_page_detail_candidate_v1",
    )

    assert result["source_path"] == "logs/case/wrapper.json"


def test_learning_review_fast_list_mode_skips_global_candidate_sidecar_search(
    tmp_path: Path, monkeypatch
) -> None:
    import app.learn.draft_review as draft_review

    reviewed_path = tmp_path / "artifacts" / "learning-runs" / "case" / "trial_result.json"
    _write_trial(reviewed_path)
    wrapper_path = tmp_path / "artifacts" / "learning-runs" / "case" / "pathgraph_candidate.json"
    _write_json(
        wrapper_path,
        {
            "contract_version": "pathgraph_candidate_v1",
            "reviewed_template_candidate_path": str(reviewed_path.relative_to(tmp_path)),
            "validation_status": "blocked_pending_calibration",
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    draft_review.clear_learning_draft_sidecar_cache()

    def fail_rglob(*args, **kwargs):
        raise AssertionError("fast panel source loading must not run a global sidecar search")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    result = draft_review.load_learning_draft_review(
        wrapper_path,
        project_root=tmp_path,
        discover_related_sidecars=False,
    )

    assert result["contract_version"] == "learning_draft_review_v1"
    assert result["pathgraph_candidate_review"]["contract_version"] == "pathgraph_candidate_review_v1"


def test_learning_draft_source_candidate_filter_only_accepts_reviewable_artifacts() -> None:
    import app.api.panel as panel_api

    assert panel_api._is_learning_draft_source_candidate_file(Path("trial_result.json")) is True
    assert panel_api._is_learning_draft_source_candidate_file(Path("reviewed_template_candidate.json")) is True
    assert panel_api._is_learning_draft_source_candidate_file(Path("pathgraph_candidate.json")) is True
    assert panel_api._is_learning_draft_source_candidate_file(Path("final_stage2_for_calibration.json")) is False
    assert panel_api._is_learning_draft_source_candidate_file(Path("model_review_report.json")) is False


def test_direct_page_detail_and_scaffold_sources_load_as_review_only(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    page_detail = _write_json(
        tmp_path / "logs" / "benchmarks" / "direct_page_detail" / "learn_page_detail_candidate.json",
        {
            "contract_version": "learn_page_detail_candidate_v1",
            "screen_summary": "Direct page detail source",
            "readiness_status": "needs_page_detail_review",
            "screenshot_path": "artifacts/screenshots/source.png",
            "compiled_overlay_path": "artifacts/review-overlays/compiled.png",
            "full_screen_understanding_overlay_path": "artifacts/review-overlays/full.png",
            "summary": {"region_count": 1, "section_count": 1, "possible_operation_count": 1},
            "layout": {
                "bounds": {"x": 0, "y": 0, "w": 320, "h": 180},
                "sections": [
                    {
                        "section_id": "main_content",
                        "label": "Main content",
                        "bbox": {"x": 0, "y": 0, "w": 320, "h": 180},
                        "region_count": 1,
                    }
                ],
                "regions": [
                    {
                        "region_id": "main_card",
                        "label": "Main card",
                        "role": "card",
                        "source_section_id": "main_content",
                        "bbox": {"x": 20, "y": 30, "w": 120, "h": 80},
                        "possible_operation": {"kind": "read_only"},
                    }
                ],
            },
            "safety": {
                "display_only": True,
                "model_started": False,
                "live_clicks": 0,
                "live_fills": 0,
                "live_submits": 0,
                "execute_binding_enabled": False,
                "runtime_pathgraph_promotion": False,
            },
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    scaffold = _write_json(
        tmp_path / "logs" / "benchmarks" / "direct_scaffold" / "learn_mode_demo_scaffold.json",
        {
            "contract_version": "learn_mode_demo_scaffold_v1",
            "source_path": str(page_detail.relative_to(tmp_path)).replace("\\", "/"),
            "page_detail_candidate": json.loads(page_detail.read_text(encoding="utf-8")),
            "summary": {"failure_count": 0, "page_detail_region_count": 1, "page_detail_section_count": 1},
            "display_readiness": {
                "pathgraph_detail_can_show_page_detail": True,
                "template_like_layout_available": True,
            },
            "safety": {
                "display_only": True,
                "model_started": False,
                "live_clicks": 0,
                "live_fills": 0,
                "live_submits": 0,
                "execute_binding_enabled": False,
                "runtime_pathgraph_promotion": False,
            },
        },
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    page_review = load_learning_draft_review(page_detail.relative_to(tmp_path), project_root=tmp_path)
    scaffold_review = load_learning_draft_review(scaffold.relative_to(tmp_path), project_root=tmp_path)

    assert page_review["draft"]["screen_summary"] == "Direct page detail source"
    assert page_review["draft"]["states"][0]["region_refs"] == ["main_card"]
    assert page_review["draft"]["states"][0]["action_template_refs"] == ["review_main_card"]
    assert page_review["draft"]["regions"][0]["region_id"] == "main_card"
    assert page_review["draft"]["regions"][0]["state_id"] == "main_content"
    assert page_review["draft"]["action_templates"][0]["state_id"] == "main_content"
    assert page_review["draft"]["action_templates"][0]["target_region_id"] == "main_card"
    page_details = page_review["draft"]["page_details"]
    assert [item["region_id"] for item in page_details["review_only_regions"]] == ["main_card"]
    assert page_details["grounding_candidates"] == []
    assert page_details["danger_zones"] == []
    assert page_details["inventory_summary"] == {
        "screen_inventory_count": 1,
        "accepted_for_grounding_count": 0,
        "rejected_non_actionable_count": 1,
        "grounding_validation_count": 0,
    }
    assert page_review["screen_understanding_preview"]["compiled_overlay_path"] == (
        "artifacts/review-overlays/compiled.png"
    )
    assert page_review["screen_understanding_preview"]["full_screen_understanding_overlay_path"] == (
        "artifacts/review-overlays/full.png"
    )
    assert page_review["screen_understanding_preview"]["counts"] == {
        "inventory_items": 1,
        "review_only_regions": 1,
        "grounding_candidates": 0,
        "danger_zones": 0,
    }
    assert [item["item_id"] for item in page_review["screen_understanding_preview"]["review_only_regions"]] == [
        "main_card"
    ]
    assert page_review["pathgraph_candidate_review"]["page_detail_candidate"]["contract_version"] == (
        "learn_page_detail_candidate_v1"
    )
    assert scaffold_review["screen_understanding_preview"]["compiled_overlay_path"] == (
        "artifacts/review-overlays/compiled.png"
    )
    assert scaffold_review["screen_understanding_preview"]["full_screen_understanding_overlay_path"] == (
        "artifacts/review-overlays/full.png"
    )
    assert scaffold_review["screen_understanding_preview"]["counts"] == {
        "inventory_items": 1,
        "review_only_regions": 1,
        "grounding_candidates": 0,
        "danger_zones": 0,
    }
    assert [item["item_id"] for item in scaffold_review["screen_understanding_preview"]["review_only_regions"]] == [
        "main_card"
    ]
    assert scaffold_review["draft"]["states"][0]["region_refs"] == ["main_card"]
    assert scaffold_review["draft"]["states"][0]["action_template_refs"] == ["review_main_card"]
    assert scaffold_review["pathgraph_candidate_review"]["learn_mode_demo_scaffold"]["contract_version"] == (
        "learn_mode_demo_scaffold_v1"
    )
    assert scaffold_review["pathgraph_candidate_review"]["page_detail_candidate"]["layout"]["sections"][0][
        "section_id"
    ] == "main_content"

    payload = TestClient(app).get("/panel/learning_draft_sources", params={"include_recent": "true"}).json()

    assert payload["success"] is True
    sources = {item["source_path"]: item for item in payload["data"]["sources"]}
    assert str(page_detail.relative_to(tmp_path)).replace("\\", "/") not in sources
    assert str(scaffold.relative_to(tmp_path)).replace("\\", "/") not in sources
    assert payload["data"]["targeted_benchmark_scan_performed"] is False


def test_panel_create_model_start_approval_packet_endpoint_is_no_execute(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    runbook = _write_json(
        tmp_path / "runbook.json",
        {
            "contract_version": "learn_fusion_model_start_runbook_v1",
            "runbook_status": "awaiting_explicit_model_start_approval",
            "approval_required": True,
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "commands": {
                "calibration_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2,3",
                "post_batch_refresh_command_preview": "uv run python scripts\\refresh_learn_fusion_after_calibration_batch.py --batch-plan plan.json",
                "command_executes_now": False,
                "post_batch_refresh_command_executes_now": False,
            },
            "expected_outputs": {
                "rerun_report_status": "awaiting_future_calibration_output",
                "rerun_report_path": "logs/future/numbered_region_calibration_report.json",
            },
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    preflight = _write_json(
        tmp_path / "preflight.json",
        {
            "contract_version": "learn_fusion_model_start_preflight_v1",
            "preflight_status": "ready_for_explicit_model_start",
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "candidate_validation_status": "blocked_pending_calibration",
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "commands": {"command_executes_now": False, "post_batch_refresh_command_executes_now": False},
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "blockers": [],
        },
    )
    demo = _write_json(
        tmp_path / "demo.json",
        {
            "contract_version": "learn_fusion_demo_readiness_v1",
            "demo_readiness_status": "ready_for_preflight_demo",
            "candidate_validation_status": "blocked_pending_calibration",
            "preflight_status": "ready_for_explicit_model_start",
            "may_run_calibration_batch_now": False,
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "blockers": [],
        },
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    response = client.post(
        "/panel/create_model_start_approval_packet",
        json={
            "runbook_path": "runbook.json",
            "preflight_report_path": "preflight.json",
            "demo_readiness_report_path": "demo.json",
            "out_dir": "candidate",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["approval_packet_status"] == "ready_for_user_approval"
    assert data["approval_does_not_execute"] is True
    assert data["may_run_calibration_batch_now"] is False
    assert data["safety"]["live_clicks"] == 0
    assert data["safety"]["execute_binding_enabled"] is False
    assert data["trace_path"]
    assert (tmp_path / "candidate" / "learn_fusion_model_start_approval_packet.json").exists()


def test_panel_create_model_start_approval_packet_endpoint_can_infer_from_candidate(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    reviewed = _write_json(
        tmp_path / "artifacts" / "sample" / "reviewed_template_candidate.json",
        {
            "contract_version": "reviewed_template_candidate_v1",
            "draft": {
                "contract_version": "learning_template_draft_v1",
                "screen_summary": "SEEK results",
                "state_guess": "seek_results",
                "states": [{"state_id": "seek_results", "label": "SEEK results"}],
                "regions": [],
                "action_templates": [],
                "blockers": [],
                "verification_rules": [],
            },
        },
    )
    candidate_dir = tmp_path / "artifacts" / "sample" / "candidate"
    runbook_source = _write_json(
        tmp_path / "artifacts" / "sample" / "learn_fusion_model_start_runbook.json",
        {
            "contract_version": "learn_fusion_model_start_runbook_v1",
            "runbook_status": "awaiting_explicit_model_start_approval",
            "approval_required": True,
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "commands": {
                "calibration_command_preview": "calibrate",
                "post_batch_refresh_command_preview": "refresh",
                "command_executes_now": False,
                "post_batch_refresh_command_executes_now": False,
            },
            "expected_outputs": {
                "rerun_report_status": "awaiting_future_calibration_output",
                "rerun_report_path": "logs/future/report.json",
            },
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    candidate = _write_json(
        candidate_dir / "pathgraph_candidate.json",
        {
            "contract_version": "pathgraph_candidate_v1",
            "reviewed_template_candidate_path": str(reviewed.relative_to(tmp_path)),
            "validation_status": "blocked_pending_calibration",
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "model_start_runbook": {
                "contract_version": "learn_fusion_model_start_runbook_v1",
                "runbook_status": "awaiting_explicit_model_start_approval",
                "approval_required": True,
                "may_start_model_after_user_approval": True,
                "may_run_calibration_batch_now": False,
                "ready_region_numbers": [1, 2, 3],
                "review_blocked_region_numbers": [7],
                "commands": {
                    "calibration_command_preview": "calibrate",
                    "post_batch_refresh_command_preview": "refresh",
                    "command_executes_now": False,
                    "post_batch_refresh_command_executes_now": False,
                },
                "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
        },
    )
    _write_json(
        candidate_dir / "learn_fusion_model_start_preflight_report.json",
        {
            "contract_version": "learn_fusion_model_start_preflight_v1",
            "preflight_status": "ready_for_explicit_model_start",
            "runbook_path": str(runbook_source.relative_to(tmp_path)),
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "candidate_validation_status": "blocked_pending_calibration",
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "commands": {"command_executes_now": False, "post_batch_refresh_command_executes_now": False},
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "blockers": [],
        },
    )
    _write_json(
        candidate_dir / "learn_fusion_demo_readiness_report.json",
        {
            "contract_version": "learn_fusion_demo_readiness_v1",
            "demo_readiness_status": "ready_for_preflight_demo",
            "candidate_validation_status": "blocked_pending_calibration",
            "preflight_status": "ready_for_explicit_model_start",
            "may_run_calibration_batch_now": False,
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "blockers": [],
        },
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    response = client.post(
        "/panel/create_model_start_approval_packet",
        json={"candidate_path": str(candidate.relative_to(tmp_path))},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["approval_packet_status"] == "ready_for_user_approval"
    assert data["runbook_path"] == "artifacts/sample/learn_fusion_model_start_runbook.json"
    assert data["report_path"].endswith("candidate\\learn_fusion_model_start_approval_packet.json")
    assert not (candidate_dir / "learn_fusion_model_start_runbook_embedded.json").exists()


def test_panel_create_calibration_pre_run_check_endpoint_is_no_execute(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api
    import scripts.report_learn_fusion_calibration_pre_run_check as pre_run_check

    tasks = _write_json(tmp_path / "logs" / "tasks.json", {"contract_version": "tasks_v1", "tasks": []})
    batch_plan = _write_json(tmp_path / "logs" / "batch_plan.json", {"contract_version": "batch_plan_v1"})
    rerun_report = tmp_path / "logs" / "future" / "numbered_region_calibration_report.json"
    approval = _write_json(
        tmp_path / "candidate" / "learn_fusion_model_start_approval_packet.json",
        {
            "contract_version": "learn_fusion_model_start_approval_packet_v1",
            "approval_packet_status": "ready_for_user_approval",
            "requires_explicit_user_approval": True,
            "approval_does_not_execute": True,
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "candidate_validation_status": "blocked_pending_calibration",
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "commands": {
                "calibration_command_preview": (
                    f"uv run python scripts\\run_numbered_region_calibration_probe.py "
                    f"--tasks {tasks} --out {tmp_path / 'logs' / 'future'} --regions 1,2,3"
                ),
                "post_batch_refresh_command_preview": (
                    f"uv run python scripts\\refresh_learn_fusion_after_calibration_batch.py "
                    f"--rerun-report {rerun_report} --batch-plan {batch_plan} --out {tmp_path / 'logs' / 'refresh'}"
                ),
                "command_executes_now": False,
                "post_batch_refresh_command_executes_now": False,
            },
            "expected_outputs": {
                "rerun_report_status": "awaiting_future_calibration_output",
                "rerun_report_path": str(rerun_report),
                "post_batch_refresh_requires_completed_batch": True,
            },
            "safety": {
                "model_started": False,
                "live_clicks": 0,
                "live_fills": 0,
                "live_submits": 0,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            "blockers": [],
        },
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(
        pre_run_check,
        "_model_runtime_snapshot",
        lambda: {
            "contract_version": "model_runtime_snapshot_v1",
            "checked_ports": [],
            "listening_ports": [],
            "suspected_model_processes": [],
            "model_ports_clear": True,
            "model_processes_clear": True,
            "interpretation": "test fixture; no model runtime was contacted",
        },
    )

    client = TestClient(app)
    response = client.post(
        "/panel/create_calibration_pre_run_check",
        json={"approval_packet_path": str(approval.relative_to(tmp_path)), "out_dir": "candidate"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["pre_run_status"] == "ready_after_explicit_approval"
    assert data["requires_explicit_user_approval"] is True
    assert data["may_run_calibration_batch_now"] is False
    assert data["checks"]["tasks_file_exists"] is True
    assert data["checks"]["regions_match_ready_regions"] is True
    assert data["safety"]["model_started"] is False
    assert data["safety"]["live_clicks"] == 0
    assert data["safety"]["live_fills"] == 0
    assert data["safety"]["live_submits"] == 0
    assert data["safety"]["execute_binding_enabled"] is False
    assert data["safety"]["artifact_is_authorization"] is False
    assert data["trace_path"]
    assert (tmp_path / "candidate" / "learn_fusion_calibration_pre_run_check_report.json").exists()


def test_panel_create_pathgraph_integration_readiness_endpoint_is_no_execute(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    candidate_dir = tmp_path / "artifacts" / "candidate"
    reviewed = _write_json(
        candidate_dir / "reviewed_template_candidate.json",
        {
            "contract_version": "reviewed_template_candidate_v1",
            "draft": {
                "contract_version": "learning_template_draft_v1",
                "screen_summary": "SEEK results with pending calibration.",
                "state_guess": "seek_results",
                "states": [{"state_id": "seek_results", "label": "SEEK results"}],
                "regions": [{"region_id": "job_card_1", "label": "Job card"}],
                "action_templates": [
                    {
                        "action_template_id": "open_job_card",
                        "semantic_action": "open_detail",
                        "target_entity": "job_card_1",
                    }
                ],
                "blockers": [{"blocker_id": "final_submit_forbidden"}],
                "verification_rules": [{"rule_id": "post_action_observe"}],
            },
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
            "counts_as_pure_model_generated": False,
        },
    )
    validation = _write_json(
        candidate_dir / "promotion_validation_report.json",
        {
            "contract_version": "pathgraph_candidate_validation_report_v1",
            "validation_status": "blocked_pending_calibration",
            "checks": [{"check_id": "precise_understanding_ready_for_pathgraph_candidate", "passed": False}],
            "summary": {
                "precise_understanding_readiness_summary": {
                    "readiness_status": "needs_pending_calibration",
                    "pending_calibration_ready_count": 3,
                },
                "evidence_integrity": {"status": "complete"},
            },
            "precise_understanding_readiness_summary": {
                "readiness_status": "needs_pending_calibration",
                "pending_calibration_ready_count": 3,
            },
            "evidence_integrity": {"status": "complete"},
            "pending_detail_observe_requests": [],
            "safety": {
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                "final_submit_forbidden": True,
            },
        },
    )
    candidate = _write_json(
        candidate_dir / "pathgraph_candidate.json",
        {
            "contract_version": "pathgraph_candidate_v1",
            "reviewed_template_candidate_path": str(reviewed.relative_to(tmp_path)),
            "validation_report_path": str(validation.relative_to(tmp_path)),
            "validation_status": "blocked_pending_calibration",
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
        },
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    response = client.post(
        "/panel/create_pathgraph_integration_readiness",
        json={"candidate_path": str(candidate.relative_to(tmp_path))},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["integration_readiness_status"] == "blocked_pending_calibration"
    assert data["ready_for_audited_pathgraph_review"] is False
    assert data["ready_for_runtime_pathgraph_promotion"] is False
    assert data["blockers"] == ["pending_calibration_required"]
    assert data["safety"]["execute_binding_enabled"] is False
    assert data["safety"]["artifact_is_authorization"] is False
    assert data["trace_path"]
    assert (candidate_dir / "learn_fusion_pathgraph_integration_readiness_report.json").exists()


def test_panel_create_current_evidence_packet_endpoint_is_no_execute(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    candidate_dir = tmp_path / "artifacts" / "candidate"
    reviewed = _write_json(
        candidate_dir / "reviewed_template_candidate.json",
        {
            "contract_version": "reviewed_template_candidate_v1",
            "draft": {
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
                                "execute_binding_enabled": False,
                                "artifact_is_authorization": False,
                            },
                            "pathgraph_preparation": {"status": "blocked_from_pathgraph_candidate_review"},
                            "execute_binding_enabled": False,
                            "artifact_is_authorization": False,
                        }
                    }
                },
            },
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
        },
    )
    validation = _write_json(
        candidate_dir / "promotion_validation_report.json",
        {
            "contract_version": "pathgraph_candidate_validation_report_v1",
            "validation_status": "blocked_pending_calibration",
            "summary": {"ready_for_runtime_pathgraph_promotion": False},
            "safety": {"execute_binding_enabled": False, "artifact_is_authorization": False},
        },
    )
    integration = _write_json(
        candidate_dir / "learn_fusion_pathgraph_integration_readiness_report.json",
        {
            "contract_version": "learn_fusion_pathgraph_integration_readiness_report_v1",
            "integration_readiness_status": "blocked_pending_calibration",
            "report_path": "artifacts/candidate/learn_fusion_pathgraph_integration_readiness_report.json",
            "ready_for_audited_pathgraph_review": False,
            "ready_for_runtime_pathgraph_promotion": False,
            "blockers": ["pending_calibration_required"],
            "next_required_steps": ["run_approved_numbered_region_calibration_batch"],
            "safety": {"execute_binding_enabled": False, "artifact_is_authorization": False},
        },
    )
    candidate = _write_json(
        candidate_dir / "pathgraph_candidate.json",
        {
            "contract_version": "pathgraph_candidate_v1",
            "reviewed_template_candidate_path": str(reviewed.relative_to(tmp_path)),
            "validation_report_path": str(validation.relative_to(tmp_path)),
            "pathgraph_integration_readiness_report_path": str(integration.relative_to(tmp_path)),
            "validation_status": "blocked_pending_calibration",
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    response = client.post(
        "/panel/create_current_evidence_packet",
        json={"source_path": str(candidate.relative_to(tmp_path))},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["contract_version"] == "learn_fusion_current_evidence_packet_v1"
    assert data["full_screen_understanding"]["fusion_summary"]["calibration_coverage_rate"] == 0.2
    assert data["calibration"]["batch_ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert data["pathgraph"]["integration_readiness_status"] == "blocked_pending_calibration"
    assert data["pathgraph"]["ready_for_runtime_pathgraph_promotion_after_integration"] is False
    assert data["safety"]["model_started"] is False
    assert data["safety"]["live_clicks"] == 0
    assert data["safety"]["execute_binding_enabled"] is False
    assert data["trace_path"]
    assert (candidate_dir / "learn_fusion_current_evidence_packet.json").exists()
    from app.learn.draft_review import load_learning_draft_review

    review = load_learning_draft_review(candidate.relative_to(tmp_path), project_root=tmp_path)
    candidate_review = review["pathgraph_candidate_review"]
    packet = candidate_review["current_evidence_packet"]
    summary_packet = candidate_review["pathgraph_readiness_summary"]["current_evidence_packet"]
    assert packet["contract_version"] == "learn_fusion_current_evidence_packet_v1"
    assert summary_packet["pathgraph"]["integration_readiness_status"] == "blocked_pending_calibration"
    assert packet["safety"]["model_started"] is False
    assert packet["safety"]["runtime_pathgraph_promotion"] is False


def test_panel_generate_pathgraph_candidate_blocks_recommended_pending_calibration_source(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    source_path = (
        tmp_path
        / "logs"
        / "benchmarks"
        / "learn_pathgraph_readiness_with_handoff_20260706"
        / "actual_parser_output_with_fusion_status.json"
    )
    _write_trial(source_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    draft = payload["best_learning_draft"]
    draft["blockers"] = [{"blocker_id": "final_submit_forbidden", "reason": "final submit is forbidden"}]
    draft["verification_rules"] = [{"rule_id": "post_action_observe_required", "description": "observe after action"}]
    draft["page_details"] = {
        "pipeline_audit": {
            "precise_understanding_fusion_status": {
                "contract_version": "learning_draft_precise_understanding_fusion_status_v1",
                "summary": {
                    "total_locator_cards": 10,
                    "calibrated_cases": 2,
                    "uncalibrated_locator_cards": 8,
                    "calibration_coverage_rate": 0.2,
                    "real_clicks": 0,
                },
                "calibration_batch_plan": {
                    "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "review_blocked_region_numbers": [7, 10],
                    "run_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2,3,6,8,9",
                    "command_executes_now": False,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
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
                "model_start_runbook": {
                    "contract_version": "learning_draft_model_start_runbook_v1",
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
                    },
                    "safety": {
                        "model_started": False,
                        "live_clicks": 0,
                        "live_fills": 0,
                        "live_submits": 0,
                    },
                    "blockers": [],
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        }
    }
    source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    response = client.post(
        "/panel/generate_pathgraph_candidate",
        json={
            "source_path": "logs/benchmarks/learn_pathgraph_readiness_with_handoff_20260706/actual_parser_output_with_fusion_status.json",
            "review_patch": {
                "review_status": "approved_as_assisted_template",
                "source_after_review": "assisted_generation",
            },
        },
    ).json()

    assert response["success"] is True
    data = response["data"]
    assert data["validation_status"] == "blocked_pending_calibration"
    assert data["execute_binding_enabled"] is False
    assert data["artifact_is_authorization"] is False
    assert data["precise_understanding_readiness_summary"]["readiness_status"] == "needs_pending_calibration"
    assert data["model_start_runbook"]["runbook_status"] == "awaiting_explicit_model_start_approval"
    assert data["model_start_runbook"]["may_start_model_after_user_approval"] is True
    assert data["model_start_runbook"]["may_run_calibration_batch_now"] is False
    assert data["model_start_runbook"]["ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    validation_report = json.loads((tmp_path / data["validation_report_path"]).read_text(encoding="utf-8"))
    readiness_check = next(
        item for item in validation_report["checks"] if item["check_id"] == "precise_understanding_ready_for_pathgraph_candidate"
    )
    assert readiness_check["passed"] is False
    assert readiness_check["details"]["model_start_runbook"]["runbook_status"] == "awaiting_explicit_model_start_approval"
    assert validation_report["model_start_runbook"]["next_manual_action"] == "ask_user_to_approve_model_start_for_ready_regions"
    assert validation_report["safety"]["execute_binding_enabled"] is False
    assert validation_report["safety"]["artifact_is_authorization"] is False
    wrapper = json.loads((tmp_path / data["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    assert wrapper["model_start_runbook"]["may_run_calibration_batch_now"] is False


def test_save_learning_draft_review_applies_manual_bbox_updates(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    trial_path = tmp_path / "artifacts" / "learning-runs" / "sample" / "trial_result.json"
    _write_trial(trial_path)

    result = save_reviewed_template_candidate(
        "artifacts/learning-runs/sample/trial_result.json",
        {
            "region_bbox_updates": {
                "r1": {
                    "bbox": {"x": 120, "y": 140, "width": 260, "height": 48},
                    "click_point": {"x": 250, "y": 164},
                }
            },
            "action_bbox_updates": {
                "a1": {
                    "bbox": {"x": 130, "y": 150, "w": 210, "h": 36},
                    "click_point": {"x": 235, "y": 168},
                }
            },
        },
        project_root=tmp_path,
    )

    saved = json.loads((tmp_path / result["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))
    region = saved["draft"]["regions"][0]
    action = saved["draft"]["action_templates"][0]

    assert region["bbox"] == {"x": 120, "y": 140, "w": 260, "h": 48}
    assert region["click_point"] == {"x": 250, "y": 164}
    assert region["human_review"]["bbox_edited"] is True
    assert region["human_review"]["previous_bbox"] == {"x": 8, "y": 18, "w": 100, "h": 30}
    assert region["human_review"]["previous_click_point"] == {"x": 58, "y": 33}
    assert action["bbox"] == {"x": 130, "y": 150, "w": 210, "h": 36}
    assert action["click_point"] == {"x": 235, "y": 168}
    assert action["human_review"]["bbox_edited"] is True
    assert action["human_review"]["previous_bbox"] == {"x": 10, "y": 20, "w": 80, "h": 24}
    assert action["human_review"]["previous_click_point"] == {"x": 50, "y": 32}
    assert "region_bbox:r1" in saved["audit"]["changes_summary"]
    assert "action_bbox:a1" in saved["audit"]["changes_summary"]
    assert saved["audit"]["manual_bbox_edit_summary"] == {
        "contract_version": "manual_bbox_edit_summary_v1",
        "edited_region_count": 1,
        "edited_action_count": 1,
        "edited_total": 2,
        "point_inside_bbox_passed": 2,
        "point_inside_bbox_failed": 0,
        "invalid_geometry_count": 0,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    assert saved["audit"]["source_freshness_summary"] == {
        "contract_version": "source_freshness_summary_v1",
        "source_image_status": "missing",
        "checksum_status": "missing",
        "freshness_status": "warning",
        "warning_count": 2,
        "warnings": ["missing_source_image", "missing_source_image_sha256"],
        "source_image_path": "",
        "source_image_sha256": "",
        "actual_source_image_sha256": "",
        "source_image_evidence_source": "missing",
        "checksum_binding_status": "missing",
        "edited_geometry_requires_review": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    assert result["manual_bbox_edit_summary"]["edited_total"] == 2
    assert result["source_freshness_summary"]["freshness_status"] == "warning"
    assert saved["artifact_is_authorization"] is False
    assert saved["execute_binding_enabled"] is False


def test_save_learning_draft_review_prunes_deleted_ids_from_derived_evidence_and_keeps_additions(
    tmp_path: Path,
) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    trial_path = tmp_path / "artifacts" / "learning-runs" / "deletion-consistency" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    draft = payload["best_learning_draft"]
    draft["workflow_draft"]["states"][0].update(
        {
            "region_refs": ["r1", "r_keep"],
            "action_template_refs": ["a1", "a_keep"],
        }
    )
    draft["interface_draft"]["regions"].append(
        {
            "region_id": "r_keep",
            "label": "Keep region",
            "role": "button",
            "bbox": {"x": 140, "y": 18, "w": 100, "h": 30},
        }
    )
    draft["workflow_draft"]["action_templates"].append(
        {
            "action_template_id": "a_keep",
            "label": "Keep action",
            "semantic_action": "read_only",
            "target_entity": "r_keep",
            "bbox": {"x": 142, "y": 20, "w": 80, "h": 24},
        }
    )
    hierarchy = {
        "contract_version": "ui_hierarchy_graph_v1",
        "root_node_id": "uih:screen",
        "nodes": [
            {
                "node_id": "uih:screen",
                "source_ref": "screen",
                "children": ["uih:r1", "uih:r_keep", "uih:a1", "uih:a_keep"],
            },
            {"node_id": "uih:r1", "source_ref": "r1", "children": []},
            {
                "node_id": "uih:r_keep",
                "source_ref": "r_keep",
                "children": [],
            },
            {
                "node_id": "uih:a1",
                "source_ref": "a1",
                "children": [],
            },
            {
                "node_id": "uih:a_keep",
                "source_ref": "a_keep",
                "children": [],
            },
        ],
        "edges": [
            {"source": "uih:screen", "target": "uih:r1"},
            {"source": "uih:screen", "target": "uih:r_keep"},
            {"source": "uih:screen", "target": "uih:a1"},
            {"source": "uih:screen", "target": "uih:a_keep"},
        ],
        "summary": {"node_count": 5},
    }
    draft["ui_hierarchy"] = hierarchy
    draft["page_details"] = {
        "layout": {
            "sections": [
                {
                    "section_id": "main",
                    "regions": [
                        {"region_id": "r1", "label": "Deleted PII region"},
                        {"region_id": "r_keep", "label": "Keep region"},
                    ],
                    "operation_links": [
                        {"region_id": "r1", "action_template_id": "a1"},
                        {"region_id": "r_keep", "action_template_id": "a1"},
                        {"region_id": "r_keep", "action_template_id": "a_keep"},
                    ],
                }
            ],
            "regions": [
                {"region_id": "r1", "label": "Deleted PII region"},
                {"region_id": "r_keep", "label": "Keep region"},
            ],
        },
        "review_only_regions": [
            {"region_id": "r1", "label": "Deleted PII region"},
            {"region_id": "r_keep", "label": "Keep region"},
        ],
        "ui_hierarchy": hierarchy,
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = save_reviewed_template_candidate(
        "artifacts/learning-runs/deletion-consistency/trial_result.json",
        {
            "region_deletions": ["r1"],
            "action_deletions": ["a1"],
            "region_additions": [
                {
                    "region_id": "r_new",
                    "label": "New reviewed region",
                    "role": "button",
                    "bbox": {"x": 250, "y": 18, "w": 100, "h": 30},
                }
            ],
            "action_template_additions": [
                {
                    "action_template_id": "a_new",
                    "label": "New reviewed action",
                    "semantic_action": "read_only",
                    "target_entity": "r_new",
                    "bbox": {"x": 252, "y": 20, "w": 80, "h": 24},
                }
            ],
        },
        project_root=tmp_path,
    )

    saved = json.loads((tmp_path / result["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))
    reviewed = saved["draft"]
    assert [item["region_id"] for item in reviewed["regions"]] == ["r_keep", "r_new"]
    assert [item["action_template_id"] for item in reviewed["action_templates"]] == ["a_keep", "a_new"]
    assert reviewed["states"][0]["region_refs"] == ["r_keep"]
    assert reviewed["states"][0]["action_template_refs"] == ["a_keep"]

    page_details = reviewed["page_details"]
    section = page_details["layout"]["sections"][0]
    assert [item["region_id"] for item in section["regions"]] == ["r_keep"]
    assert [item["region_id"] for item in section["operation_links"]] == ["r_keep"]
    assert [item["region_id"] for item in page_details["layout"]["regions"]] == ["r_keep"]
    assert [item["region_id"] for item in page_details["review_only_regions"]] == ["r_keep"]

    for hierarchy_key in ("ui_hierarchy",):
        node_ids = {item["node_id"] for item in reviewed[hierarchy_key]["nodes"]}
        assert node_ids == {"uih:screen", "uih:r_keep", "uih:a_keep"}
        assert reviewed[hierarchy_key]["nodes"][0]["children"] == ["uih:r_keep", "uih:a_keep"]
    page_hierarchy = page_details["ui_hierarchy"]
    assert {item["node_id"] for item in page_hierarchy["nodes"]} == {
        "uih:screen",
        "uih:r_keep",
        "uih:a_keep",
    }
    assert page_hierarchy["nodes"][0]["children"] == ["uih:r_keep", "uih:a_keep"]
    assert "Deleted PII region" not in json.dumps(reviewed, ensure_ascii=False)
    assert saved["artifact_is_authorization"] is False
    assert saved["execute_binding_enabled"] is False
    assert saved["final_submit_forbidden"] is True


def test_save_learning_draft_review_writes_versioned_human_review_patch(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "manual-review.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "manual-review" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/manual-review.png",
            "source_image_sha256": screenshot_sha256,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = save_reviewed_template_candidate(
        "artifacts/learning-runs/manual-review/trial_result.json",
        {
            "contract_version": "human_review_patch_v1",
            "screenshot_path": "artifacts/screenshots/manual-review.png",
            "screenshot_sha256": screenshot_sha256,
            "reason": "人工修正搜索框范围",
            "operations": [
                {
                    "op": "update_bbox",
                    "target_kind": "region",
                    "target_id": "r1",
                    "before_bbox": {"x": 8, "y": 18, "w": 100, "h": 30},
                    "after_bbox": {"x": 12, "y": 22, "w": 140, "h": 36},
                }
            ],
        },
        project_root=tmp_path,
    )

    patch_path = tmp_path / result["human_review_patch_path"]
    patch = json.loads(patch_path.read_text(encoding="utf-8"))
    reviewed = json.loads((tmp_path / result["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))

    assert patch["contract_version"] == "human_review_patch_v1"
    assert patch["revision"] == 1
    assert patch["screenshot_sha256"] == screenshot_sha256
    assert patch["operations"][0]["before_bbox"] == {"x": 8, "y": 18, "w": 100, "h": 30}
    assert patch["operations"][0]["after_bbox"] == {"x": 12, "y": 22, "w": 140, "h": 36}
    assert patch["artifact_is_authorization"] is False
    assert patch["execute_binding_enabled"] is False
    assert reviewed["draft"]["regions"][0]["bbox"] == {"x": 12, "y": 22, "w": 140, "h": 36}
    assert reviewed["audit"]["human_review_patch_path"] == result["human_review_patch_path"]
    assert result["human_review_patch_revision"] == 1
    overlay_path = tmp_path / result["reviewed_overlay_path"]
    assert overlay_path.exists()
    assert reviewed["draft"]["numbered_map_path"] == result["reviewed_overlay_path"]
    assert reviewed["draft"]["page_details"]["compiled_overlay_path"] == result["reviewed_overlay_path"]


def _write_ownership_ambiguity_trial(
    tmp_path: Path,
    *,
    second_conflict: bool = False,
) -> tuple[Path, str]:
    screenshot_path = tmp_path / "artifacts" / "screenshots" / "ownership-review.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 480), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "ownership-review" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    groups = [
        {
            "group_id": "topbar_control_strip_4",
            "member_item_ids": ["visual_control_1_6"],
            "current_evidence_member_count": 1,
        },
        {
            "group_id": "topbar_control_cluster_4_1",
            "parent_group_id": "topbar_control_strip_4",
            "member_item_ids": ["visual_control_1_6"],
            "member_numbers": ["1.9"],
            "current_evidence_member_count": 1,
        },
        {
            "group_id": "topbar_semantic_group_4_1",
            "parent_group_id": "topbar_control_strip_4",
            "member_item_ids": ["visual_control_1_6"],
            "member_numbers": ["1.9"],
            "current_evidence_member_count": 1,
        },
    ]
    numbered_items = [{"item_id": "visual_control_1_6", "number": "1.9"}]
    if second_conflict:
        groups.extend(
            [
                {
                    "group_id": "secondary_cluster",
                    "parent_group_id": "topbar_control_strip_4",
                    "member_item_ids": ["visual_control_1_7"],
                    "member_numbers": ["1.10"],
                },
                {
                    "group_id": "secondary_semantic",
                    "parent_group_id": "topbar_control_strip_4",
                    "member_item_ids": ["visual_control_1_7"],
                    "member_numbers": ["1.10"],
                },
            ]
        )
        numbered_items.append({"item_id": "visual_control_1_7", "number": "1.10"})
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/ownership-review.png",
            "source_image_sha256": screenshot_sha256,
        },
        "two_stage_understanding": {
            "stage2_numbering": {
                "contract_version": "learn_stage2_numbering_v1",
                "regions": [
                    {
                        "region_id": "structure_region_top_bar",
                        "numbered_items": numbered_items,
                        "subregion_groups": groups,
                        "stage2_streams": {
                            "contract_version": "learn_stage2_dual_streams_v1",
                            "semantic_groups": deepcopy(groups),
                        },
                    }
                ],
                "display_only": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        },
    }
    trial_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return trial_path, screenshot_sha256


def _ownership_review_patch(screenshot_sha256: str) -> dict:
    return {
        "contract_version": "human_review_patch_v1",
        "screenshot_path": "artifacts/screenshots/ownership-review.png",
        "screenshot_sha256": screenshot_sha256,
        "reason": "人工确认 control cluster 是唯一 leaf owner",
        "source": "human_panel_editor_v1",
        "review_status": "approved_as_assisted_template",
        "operations": [
            {
                "op": "resolve_ownership",
                "target_kind": "ownership",
                "target_id": "visual_control_1_6",
                "region_id": "structure_region_top_bar",
                "before_parent_group_ids": [
                    "topbar_control_cluster_4_1",
                    "topbar_semantic_group_4_1",
                ],
                "after_parent_group_id": "topbar_control_cluster_4_1",
                "reason": "人工依据截图选择唯一父组",
            }
        ],
    }


def test_human_review_resolves_leaf_ownership_as_canonical_revision(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    trial_path, screenshot_sha256 = _write_ownership_ambiguity_trial(tmp_path)
    result = save_reviewed_template_candidate(
        trial_path,
        _ownership_review_patch(screenshot_sha256),
        project_root=tmp_path,
    )

    candidate = json.loads(
        (tmp_path / result["reviewed_template_candidate_path"]).read_text(encoding="utf-8")
    )
    patch = json.loads(
        (tmp_path / result["human_review_patch_path"]).read_text(encoding="utf-8")
    )
    ownership = candidate["draft"]["page_details"]["hierarchy_ownership_review"]
    stage2 = candidate["draft"]["page_details"]["two_stage_understanding"]["stage2_numbering"]
    groups = {group["group_id"]: group for group in stage2["regions"][0]["subregion_groups"]}
    mirror_groups = {
        group["group_id"]: group
        for group in stage2["regions"][0]["stage2_streams"]["semantic_groups"]
    }

    assert result["review_status"] == "needs_human_review"
    assert candidate["review_status"] == "needs_human_review"
    assert ownership["contract_version"] == "hierarchy_ownership_review_revision_v1"
    assert ownership["status"] == "corrected_needs_integrity_revalidation"
    assert ownership["integrity_revalidation_status"] == "pending"
    assert ownership["agent_usable"] is False
    assert ownership["reviewed_by_human"] is True
    assert ownership["human_review_provenance"]["source"] == "human_panel_editor_v1"
    assert ownership["evidence_lineage"]["source_draft_path"].endswith("ownership-review/trial_result.json")
    assert ownership["evidence_lineage"]["source_draft_sha256"]
    assert ownership["evidence_lineage"]["screenshot_sha256"] == screenshot_sha256
    assert ownership["source_stage2_sha256"] != ownership["reviewed_stage2_sha256"]
    assert ownership["canonical_revision_sha256"]
    assert ownership["corrections"][0]["item_id"] == "visual_control_1_6"
    assert ownership["corrections"][0]["removed_from_group_ids"] == ["topbar_semantic_group_4_1"]
    assert groups["topbar_control_cluster_4_1"]["member_item_ids"] == ["visual_control_1_6"]
    assert groups["topbar_semantic_group_4_1"]["member_item_ids"] == []
    assert groups["topbar_semantic_group_4_1"]["member_numbers"] == []
    assert groups["topbar_semantic_group_4_1"]["current_evidence_member_count"] == 0
    assert mirror_groups["topbar_semantic_group_4_1"]["member_item_ids"] == []
    assert mirror_groups["topbar_semantic_group_4_1"]["member_numbers"] == []
    assert mirror_groups["topbar_semantic_group_4_1"]["current_evidence_member_count"] == 0
    assert mirror_groups["topbar_control_cluster_4_1"]["member_item_ids"] == [
        "visual_control_1_6"
    ]
    assert patch["hierarchy_ownership_review"] == ownership
    assert candidate["audit"]["hierarchy_ownership_review"] == ownership
    assert result["hierarchy_ownership_review"] == ownership
    assert candidate["artifact_is_authorization"] is False
    assert candidate["execute_binding_enabled"] is False


def test_human_review_accepts_explicit_leaf_and_parent_ownership_targets(
    tmp_path: Path,
) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    trial_path, screenshot_sha256 = _write_ownership_ambiguity_trial(tmp_path)
    review_patch = _ownership_review_patch(screenshot_sha256)
    operation = review_patch["operations"][0]
    selected_parent_id = operation.pop("after_parent_group_id")
    operation.update(
        {
            "target_kind": "leaf",
            "parent_target_kind": "parent",
            "parent_target_id": selected_parent_id,
        }
    )

    result = save_reviewed_template_candidate(
        trial_path,
        review_patch,
        project_root=tmp_path,
    )

    persisted_patch = json.loads(
        (tmp_path / result["human_review_patch_path"]).read_text(encoding="utf-8")
    )
    normalized = persisted_patch["operations"][0]
    assert normalized["target_kind"] == "ownership"
    assert normalized["target_id"] == "visual_control_1_6"
    assert normalized["after_parent_group_id"] == "topbar_control_cluster_4_1"
    assert result["review_status"] == "needs_human_review"
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (
            {"target_id": "unknown_leaf"},
            "ownership item does not exist",
        ),
        (
            {"parent_target_id": "unknown_parent"},
            "ownership parent group does not exist",
        ),
        (
            {"parent_target_kind": "region"},
            "invalid ownership parent target",
        ),
        (
            {"after_parent_group_id": "topbar_semantic_group_4_1"},
            "ownership parent targets disagree",
        ),
    ],
)
def test_human_review_explicit_ownership_target_fails_closed(
    tmp_path: Path,
    mutation: dict,
    error: str,
) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    trial_path, screenshot_sha256 = _write_ownership_ambiguity_trial(tmp_path)
    review_patch = _ownership_review_patch(screenshot_sha256)
    operation = review_patch["operations"][0]
    selected_parent_id = operation.pop("after_parent_group_id")
    operation.update(
        {
            "target_kind": "leaf",
            "parent_target_kind": "parent",
            "parent_target_id": selected_parent_id,
            **mutation,
        }
    )

    with pytest.raises(ValueError, match=error):
        save_reviewed_template_candidate(
            trial_path,
            review_patch,
            project_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda operation: operation.update(target_id="unknown_item"), "ownership item does not exist"),
        (
            lambda operation: operation.update(after_parent_group_id="unknown_parent"),
            "ownership parent group does not exist",
        ),
        (
            lambda operation: operation.update(before_parent_group_ids=["topbar_semantic_group_4_1"]),
            "ownership parent set is stale",
        ),
    ],
)
def test_human_review_ownership_correction_rejects_invalid_identity_or_parent(
    tmp_path: Path,
    mutate,
    error: str,
) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    trial_path, screenshot_sha256 = _write_ownership_ambiguity_trial(tmp_path)
    review_patch = _ownership_review_patch(screenshot_sha256)
    mutate(review_patch["operations"][0])

    with pytest.raises(ValueError, match=error):
        save_reviewed_template_candidate(trial_path, review_patch, project_root=tmp_path)


@pytest.mark.parametrize(
    ("mirror_mutation", "error"),
    [
        ("stale", "ownership mirror is stale"),
        ("missing", "semantic group mirror is missing"),
    ],
)
def test_human_review_ownership_correction_rejects_invalid_semantic_group_mirror(
    tmp_path: Path,
    mirror_mutation: str,
    error: str,
) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    trial_path, screenshot_sha256 = _write_ownership_ambiguity_trial(tmp_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    region = payload["best_learning_draft"]["page_details"]["two_stage_understanding"][
        "stage2_numbering"
    ]["regions"][0]
    semantic_groups = region["stage2_streams"]["semantic_groups"]
    target_index = next(
        index
        for index, group in enumerate(semantic_groups)
        if group["group_id"] == "topbar_semantic_group_4_1"
    )
    if mirror_mutation == "stale":
        semantic_groups[target_index]["member_item_ids"] = []
        semantic_groups[target_index]["member_numbers"] = []
    else:
        semantic_groups.pop(target_index)
    trial_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=error):
        save_reviewed_template_candidate(
            trial_path,
            _ownership_review_patch(screenshot_sha256),
            project_root=tmp_path,
        )


def test_human_review_ownership_correction_rejects_remaining_multiple_owners(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    trial_path, screenshot_sha256 = _write_ownership_ambiguity_trial(
        tmp_path,
        second_conflict=True,
    )
    with pytest.raises(ValueError, match="multiple leaf ownership remains"):
        save_reviewed_template_candidate(
            trial_path,
            _ownership_review_patch(screenshot_sha256),
            project_root=tmp_path,
        )


def test_save_learning_draft_review_refreshes_manual_edit_and_review_overlay(tmp_path: Path) -> None:
    from app.learn.draft_review import load_learning_draft_review, save_reviewed_template_candidate

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "manual-panel-refresh.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "manual-panel-refresh" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/manual-panel-refresh.png",
            "source_image_sha256": screenshot_sha256,
        },
        "two_stage_understanding": {
            "fusion": {
                "compiled_overlay_path": "artifacts/review-overlays/stale-before-manual-save.png",
                "full_screen_understanding_overlay_path": "artifacts/review-overlays/stale-before-manual-save.png",
            }
        },
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = save_reviewed_template_candidate(
        "artifacts/learning-runs/manual-panel-refresh/trial_result.json",
        {
            "manual_edit": {
                "target_region_id": "r1",
                "target_action_template_id": "a1",
                "region_label": "人工修正后的搜索区",
                "region_role": "review_only",
                "region_section": "main_content",
                "possible_operation": "read_only",
                "may_enter_pathgraph_draft": True,
                "needs_recalibration": False,
                "notes": "人工审核后应立即显示",
            }
        },
        project_root=tmp_path,
    )

    refreshed = load_learning_draft_review(
        result["reviewed_template_candidate_path"],
        project_root=tmp_path,
    )
    region = refreshed["draft"]["regions"][0]
    action = refreshed["draft"]["action_templates"][0]

    assert region["label"] == "人工修正后的搜索区"
    assert region["role"] == "review_only"
    assert region["parent_region_id"] == "main_content"
    assert region["description"] == "人工审核后应立即显示"
    assert region["may_enter_pathgraph_draft"] is True
    assert region["needs_recalibration"] is False
    assert action["semantic_action"] == "read_only"
    assert action["action_type"] == "read_only"
    assert refreshed["screen_understanding_preview"]["compiled_overlay_path"] == result["reviewed_overlay_path"]


def test_save_learning_draft_review_rejects_stale_human_review_screenshot(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "stale-review.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    original_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "stale-review" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/stale-review.png",
            "source_image_sha256": original_sha256,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Image.new("RGB", (320, 240), "black").save(screenshot_path)

    with pytest.raises(ValueError, match="screenshot checksum mismatch"):
        save_reviewed_template_candidate(
            "artifacts/learning-runs/stale-review/trial_result.json",
            {
                "contract_version": "human_review_patch_v1",
                "screenshot_path": "artifacts/screenshots/stale-review.png",
                "screenshot_sha256": original_sha256,
                "operations": [
                    {
                        "op": "update_bbox",
                        "target_kind": "region",
                        "target_id": "r1",
                        "before_bbox": {"x": 8, "y": 18, "w": 100, "h": 30},
                        "after_bbox": {"x": 12, "y": 22, "w": 140, "h": 36},
                    }
                ],
            },
            project_root=tmp_path,
        )


def test_save_learning_draft_review_rejects_corrupt_source_image(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "corrupt-review.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    screenshot_path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x01\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "corrupt-review" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/corrupt-review.png",
            "source_image_sha256": screenshot_sha256,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="human_review_patch screenshot is not a decodable image"):
        save_reviewed_template_candidate(
            "artifacts/learning-runs/corrupt-review/trial_result.json",
            {
                "contract_version": "human_review_patch_v1",
                "screenshot_path": "artifacts/screenshots/corrupt-review.png",
                "screenshot_sha256": screenshot_sha256,
                "operations": [],
            },
            project_root=tmp_path,
        )


def test_human_review_patch_rejects_bbox_outside_source_image(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "bbox-bounds.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "bbox-bounds" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/bbox-bounds.png",
            "source_image_sha256": screenshot_sha256,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside screenshot bounds"):
        save_reviewed_template_candidate(
            "artifacts/learning-runs/bbox-bounds/trial_result.json",
            {
                "contract_version": "human_review_patch_v1",
                "screenshot_path": "artifacts/screenshots/bbox-bounds.png",
                "screenshot_sha256": screenshot_sha256,
                "operations": [
                    {
                        "op": "update_bbox",
                        "target_kind": "region",
                        "target_id": "r1",
                        "before_bbox": {"x": 8, "y": 18, "w": 100, "h": 30},
                        "after_bbox": {"x": 300, "y": 20, "w": 40, "h": 30},
                    }
                ],
            },
            project_root=tmp_path,
        )


def test_human_review_patch_rejects_parent_cycle(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "parent-cycle.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "parent-cycle" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/parent-cycle.png",
            "source_image_sha256": screenshot_sha256,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="parent cycle"):
        save_reviewed_template_candidate(
            "artifacts/learning-runs/parent-cycle/trial_result.json",
            {
                "contract_version": "human_review_patch_v1",
                "screenshot_path": "artifacts/screenshots/parent-cycle.png",
                "screenshot_sha256": screenshot_sha256,
                "operations": [
                    {
                        "op": "add",
                        "target_kind": "region",
                        "target_id": "r2",
                        "item": {"label": "Results", "bbox": {"x": 160, "y": 40, "w": 140, "h": 160}},
                    },
                    {
                        "op": "update_parent",
                        "target_kind": "region",
                        "target_id": "r1",
                        "before_value": "",
                        "after_value": "r2",
                    },
                    {
                        "op": "update_parent",
                        "target_kind": "region",
                        "target_id": "r2",
                        "before_value": "",
                        "after_value": "r1",
                    },
                ],
            },
            project_root=tmp_path,
        )


def test_human_review_patch_supports_add_delete_role_and_parent_changes(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "structural-review.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "structural-review" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/structural-review.png",
            "source_image_sha256": screenshot_sha256,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = save_reviewed_template_candidate(
        "artifacts/learning-runs/structural-review/trial_result.json",
        {
            "contract_version": "human_review_patch_v1",
            "screenshot_path": "artifacts/screenshots/structural-review.png",
            "screenshot_sha256": screenshot_sha256,
            "operations": [
                {
                    "op": "add",
                    "target_kind": "region",
                    "target_id": "r2",
                    "item": {
                        "region_id": "r2",
                        "label": "Results area",
                        "role": "review_only",
                        "bbox": {"x": 160, "y": 40, "w": 140, "h": 160},
                    },
                },
                {
                    "op": "update_role",
                    "target_kind": "region",
                    "target_id": "r1",
                    "before_value": "text_input",
                    "after_value": "input",
                },
                {
                    "op": "update_parent",
                    "target_kind": "region",
                    "target_id": "r1",
                    "before_value": "",
                    "after_value": "r2",
                },
                {
                    "op": "delete",
                    "target_kind": "action",
                    "target_id": "a1",
                },
            ],
        },
        project_root=tmp_path,
    )

    reviewed = json.loads((tmp_path / result["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))
    regions = {item["region_id"]: item for item in reviewed["draft"]["regions"]}

    assert set(regions) == {"r1", "r2"}
    assert regions["r1"]["role"] == "input"
    assert regions["r1"]["parent_region_id"] == "r2"
    assert regions["r2"]["candidate_only"] is True
    assert regions["r2"]["execute_binding_enabled"] is False
    assert reviewed["draft"]["action_templates"] == []
    assert "region_add:r2" in result["changes_summary"]
    assert "region_role:r1" in result["changes_summary"]
    assert "region_parent:r1" in result["changes_summary"]
    assert "action_delete:a1" in result["changes_summary"]


def test_human_review_patch_preserves_agent_readable_metadata_without_authorization(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "metadata-review.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "metadata-review" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/metadata-review.png",
            "source_image_sha256": screenshot_sha256,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = save_reviewed_template_candidate(
        "artifacts/learning-runs/metadata-review/trial_result.json",
        {
            "contract_version": "human_review_patch_v1",
            "screenshot_path": "artifacts/screenshots/metadata-review.png",
            "screenshot_sha256": screenshot_sha256,
            "operations": [
                {
                    "op": "update_metadata",
                    "target_kind": "region",
                    "target_id": "r1",
                    "after_metadata": {
                        "label": "Search button",
                        "description": "Opens the application search surface.",
                        "semantic_action": "open_search",
                        "input_semantics": "none",
                        "destination": {
                            "kind": "interface",
                            "target_interface_id": "search_surface",
                        },
                        "verification_rule": "Search input becomes visible.",
                        "risk_level": "normal",
                        "requires_confirmation": False,
                        "artifact_is_authorization": True,
                        "execute_binding_enabled": True,
                    },
                }
            ],
        },
        project_root=tmp_path,
    )

    reviewed = json.loads((tmp_path / result["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))
    region = next(item for item in reviewed["draft"]["regions"] if item["region_id"] == "r1")
    assert region["label"] == "Search button"
    assert region["description"] == "Opens the application search surface."
    assert region["destination"]["target_interface_id"] == "search_surface"
    assert region["verification_rule"] == "Search input becomes visible."
    assert region["artifact_is_authorization"] is False
    assert region["execute_binding_enabled"] is False
    assert reviewed["artifact_is_authorization"] is False
    assert reviewed["execute_binding_enabled"] is False
    assert "region_metadata:r1" in result["changes_summary"]


def test_structured_editor_metadata_overrides_empty_legacy_manual_edit(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "structured-review.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "structured-review" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/structured-review.png",
            "source_image_sha256": screenshot_sha256,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = save_reviewed_template_candidate(
        "artifacts/learning-runs/structured-review/trial_result.json",
        {
            "contract_version": "human_review_patch_v1",
            "screenshot_path": "artifacts/screenshots/structured-review.png",
            "screenshot_sha256": screenshot_sha256,
            "manual_edit": {
                "target_region_id": "r1",
                "region_label": "",
                "region_role": "",
                "region_section": "",
                "notes": "",
            },
            "operations": [
                {
                    "op": "update_metadata",
                    "target_kind": "region",
                    "target_id": "r1",
                    "after_metadata": {
                        "label": "Incident report",
                        "description": "Opens the incident report for complete reading.",
                        "semantic_action": "open_detail",
                        "action_type": "open_detail",
                        "destination": {
                            "kind": "interface",
                            "target_interface_id": "incident_detail",
                        },
                        "verification_rule": "Incident detail is visible.",
                        "risk_level": "normal",
                        "requires_confirmation": False,
                    },
                }
            ],
        },
        project_root=tmp_path,
    )

    reviewed = json.loads((tmp_path / result["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))
    region = next(item for item in reviewed["draft"]["regions"] if item["region_id"] == "r1")
    assert region["label"] == "Incident report"
    assert region["description"] == "Opens the incident report for complete reading."
    assert region["destination"]["target_interface_id"] == "incident_detail"
    assert region["verification_rule"] == "Incident detail is visible."


def test_panel_save_learning_draft_review_rebuilds_readonly_pathgraph(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "panel-review.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "panel-review" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": "artifacts/screenshots/panel-review.png",
            "source_image_sha256": screenshot_sha256,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    response = TestClient(app).post(
        "/panel/save_learning_draft_review",
        json={
            "source_path": "artifacts/learning-runs/panel-review/trial_result.json",
            "review_patch": {
                "contract_version": "human_review_patch_v1",
                "screenshot_path": "artifacts/screenshots/panel-review.png",
                "screenshot_sha256": screenshot_sha256,
                "operations": [
                    {
                        "op": "update_bbox",
                        "target_kind": "region",
                        "target_id": "r1",
                        "before_bbox": {"x": 8, "y": 18, "w": 100, "h": 30},
                        "after_bbox": {"x": 12, "y": 22, "w": 140, "h": 36},
                    }
                ],
            },
        },
    ).json()

    assert response["success"] is True
    data = response["data"]
    assert (tmp_path / data["reviewed_overlay_path"]).exists()
    assert (tmp_path / data["pathgraph_candidate_path"]).exists()
    assert (tmp_path / data["runtime_path_graph_candidate_path"]).exists()
    assert data["execute_binding_enabled"] is False
    assert data["artifact_is_authorization"] is False
    assert data["correction_memory"]["status"] == "candidate"
    assert data["correction_memory"]["production_eligible"] is False
    wrapper = json.loads((tmp_path / data["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    assert wrapper["correction_memory"] == data["correction_memory"]


def test_save_learning_draft_review_uses_fusion_screenshot_for_source_freshness(tmp_path: Path) -> None:
    from app.learn.draft_review import save_reviewed_template_candidate

    screenshot_path = tmp_path / "artifacts" / "screenshots" / "fusion.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "fusion" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {"image_path": ""},
        "precise_understanding_fusion_status": {
            "contract_version": "learn_precise_understanding_fusion_status_v1",
            "screenshot_path": "artifacts/screenshots/fusion.png",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    result = save_reviewed_template_candidate(
        "artifacts/learning-runs/fusion/trial_result.json",
        {},
        project_root=tmp_path,
    )

    saved = json.loads((tmp_path / result["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))
    freshness = saved["audit"]["source_freshness_summary"]

    assert freshness["freshness_status"] == "verified"
    assert freshness["source_image_status"] == "available"
    assert freshness["checksum_status"] == "matched"
    assert freshness["source_image_path"] == "artifacts/screenshots/fusion.png"
    assert freshness["source_image_sha256"] == screenshot_sha256
    assert freshness["actual_source_image_sha256"] == screenshot_sha256
    assert freshness["source_image_evidence_source"] == "page_details.precise_understanding_fusion_status"
    assert freshness["checksum_binding_status"] == "computed_from_existing_fusion_source"
    assert freshness["warnings"] == []
    assert result["source_freshness_summary"]["freshness_status"] == "verified"


def test_load_learning_draft_review_binds_fusion_screenshot_checksum_for_editor(tmp_path: Path) -> None:
    screenshot_path = tmp_path / "artifacts" / "screenshots" / "editor-fusion.png"
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "editor-fusion" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "precise_understanding_fusion_status": {
            "contract_version": "learn_precise_understanding_fusion_status_v1",
            "screenshot_path": "artifacts/screenshots/editor-fusion.png",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    review = load_learning_draft_review(
        "artifacts/learning-runs/editor-fusion/trial_result.json",
        project_root=tmp_path,
    )

    screen = review["draft"]["page_details"]["screen"]
    assert screen["source_image_path"] == "artifacts/screenshots/editor-fusion.png"
    assert screen["source_image_sha256"] == screenshot_sha256
    assert screen["screen_size"] == {"width": 320, "height": 240}
    assert screen["source_image_binding_source"] == "page_details.precise_understanding_fusion_status"


def test_load_learning_draft_review_materializes_external_source_image_for_panel_editor(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    screenshot_path = tmp_path / "external-source.png"
    Image.new("RGB", (320, 240), "white").save(screenshot_path)
    screenshot_sha256 = hashlib.sha256(screenshot_path.read_bytes()).hexdigest()
    trial_path = project_root / "artifacts" / "learning-runs" / "external-editor" / "trial_result.json"
    _write_trial(trial_path)
    payload = json.loads(trial_path.read_text(encoding="utf-8"))
    payload["best_learning_draft"]["page_details"] = {
        "screen": {
            "source_image_path": str(screenshot_path),
            "source_image_sha256": screenshot_sha256,
        }
    }
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    review = load_learning_draft_review(
        "artifacts/learning-runs/external-editor/trial_result.json",
        project_root=project_root,
    )

    screen = review["draft"]["page_details"]["screen"]
    materialized_path = project_root / screen["source_image_path"]
    assert screen["source_image_path"].startswith(
        "artifacts/learning-draft-review/source-images/"
    )
    assert materialized_path.read_bytes() == screenshot_path.read_bytes()
    assert screen["source_image_sha256"] == screenshot_sha256
    assert screen["screen_size"] == {"width": 320, "height": 240}


def test_panel_run_learning_model_trial_saves_raw_draft_preview(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    image_path = tmp_path / "artifacts" / "screenshots" / "current.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x01\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    def fake_trial(**kwargs):
        assert kwargs["image_path"] == image_path.resolve()
        return {
            "contract_version": "learning_model_trial_v1",
            "status": "needs_more_learning",
            "image_path": str(image_path.resolve()),
            "app_name": kwargs["app_name"],
            "state_hint": kwargs["state_hint"],
            "best_attempt_index": 0,
            "best_score_percent": 0,
            "attempt_count": 1,
            "target_contract": {"contract_version": "learning_template_target_v1", "reference_template": None},
            "best_learning_draft": {
                "contract_version": "learning_template_draft_v1",
                "workflow_draft": {"states": [{"state_id": "s1"}], "action_templates": [{"action_template_id": "a1"}]},
                "interface_draft": {"regions": [{"region_id": "r1"}]},
                "blockers": [],
                "verification_rules": [],
            },
            "safety": {"real_clicks_performed": 0, "promotion_allowed": False},
        }

    monkeypatch.setattr(panel_api, "build_learning_model_trial", fake_trial)

    client = TestClient(app)
    payload = client.post(
        "/panel/run_learning_model_trial",
        json={
            "image_path": "artifacts/screenshots/current.png",
            "app_name": "demo",
            "state_hint": "home",
            "max_attempts": 1,
        },
    ).json()

    assert payload["success"] is True
    data = payload["data"]
    assert data["artifact_type"] == "raw_learning_trial"
    assert data["draft_only"] is True
    assert data["draft_graph_preview"] is True
    assert data["runtime_path_graph"] is False
    assert data["promotion_allowed"] is False
    assert data["artifact_is_authorization"] is False
    assert data["execute_binding_enabled"] is False
    assert data["real_clicks"] == 0
    assert data["reference_available"] is False
    assert data["best_score_percent"] is None
    assert data["alignment_score"] == "not_available"
    assert data["trial_path"].startswith("artifacts\\learning-runs\\") or data["trial_path"].startswith("artifacts/learning-runs/")

    saved_path = tmp_path / data["trial_path"]
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    assert saved["artifact_type"] == "raw_learning_trial"
    assert saved["draft_only"] is True
    assert saved["artifact_is_authorization"] is False
    assert saved["execute_binding_enabled"] is False
    assert saved["panel_learning_studio"]["display_only"] is True


def test_panel_run_learning_model_trial_rejects_images_outside_artifacts_or_logs(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not an image")
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    payload = client.post(
        "/panel/run_learning_model_trial",
        json={"image_path": str(outside), "app_name": "demo"},
    ).json()

    assert payload["success"] is False
    assert payload["error"]["code"] == "learning_trial_image_not_allowed"


def test_panel_generates_non_executable_pathgraph_candidate_from_review(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    trial_path = tmp_path / "artifacts" / "learning-runs" / "sample" / "trial_result.json"
    _write_trial(trial_path)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    payload = client.post(
        "/panel/generate_pathgraph_candidate",
        json={
            "source_path": "artifacts/learning-runs/sample/trial_result.json",
            "review_patch": {
                "review_status": "approved_as_assisted_template",
                "region_bbox_updates": {
                    "r1": {
                        "bbox": {"x": 120, "y": 140, "width": 260, "height": 48},
                        "click_point": {"x": 250, "y": 164},
                    }
                },
                "action_bbox_updates": {
                    "a1": {
                        "bbox": {"x": 130, "y": 150, "w": 210, "h": 36},
                        "click_point": {"x": 235, "y": 168},
                    }
                },
                "blockers": [{"blocker_id": "b1", "label": "Stop on final submit"}],
                "verification_rules": [{"rule_id": "v1", "label": "Confirm target region is visible"}],
            },
        },
    ).json()

    assert payload["success"] is True
    data = payload["data"]
    assert data["artifact_type"] == "pathgraph_candidate"
    assert data["validation_status"] == "passed_candidate"
    assert data["counts_as_pure_model_generated"] is False
    assert data["artifact_is_authorization"] is False
    assert data["execute_binding_enabled"] is False
    assert data["final_submit_forbidden"] is True
    assert data["manual_bbox_edit_summary"]["edited_total"] == 2

    wrapper = json.loads((tmp_path / data["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    graph = json.loads((tmp_path / data["runtime_path_graph_candidate_path"]).read_text(encoding="utf-8"))
    report = json.loads((tmp_path / data["validation_report_path"]).read_text(encoding="utf-8"))
    assert wrapper["contract_version"] == "pathgraph_candidate_v1"
    assert wrapper["validation_status"] == "passed_candidate"
    assert wrapper["manual_bbox_edit_summary"]["point_inside_bbox_passed"] == 2
    assert wrapper["source_freshness_summary"]["freshness_status"] == "warning"
    assert graph["contract_version"] == "runtime_path_graph_v1"
    assert graph["candidate_contract_version"] == "runtime_path_graph_candidate_v1"
    assert graph["candidate_mode"] is True
    assert graph["artifact_is_authorization"] is False
    assert graph["execute_binding_enabled"] is False
    assert report["summary"]["operation_dispatch"] == "not_executed"
    assert report["summary"]["manual_bbox_edit_summary"]["edited_total"] == 2
    assert report["summary"]["source_freshness_summary"]["warning_count"] == 2
    assert report["manual_bbox_edit_summary"]["execute_binding_enabled"] is False
    assert report["source_freshness_summary"]["edited_geometry_requires_review"] is True
    assert all(item["passed"] for item in report["checks"])

    for source_path in (data["pathgraph_candidate_path"], data["validation_report_path"]):
        load_payload = client.post(
            "/panel/load_learning_draft_review",
            json={"source_path": source_path},
        ).json()
        assert load_payload["success"] is True
        assert load_payload["data"]["draft"]["states"][0]["state_id"] == "s1"
        assert load_payload["data"]["draft"]["regions"][0]["region_id"] == "r1"
        assert load_payload["data"]["draft"]["action_templates"][0]["action_template_id"] == "a1"
        assert load_payload["data"]["audit"]["source_freshness_summary"]["freshness_status"] == "warning"
    assert load_payload["data"]["audit"]["source_freshness_summary"]["warning_count"] == 2


def test_pathgraph_candidate_blocks_pending_precise_understanding_calibration(tmp_path: Path) -> None:
    from app.learn.draft_review import load_learning_draft_review
    from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review

    source_path = tmp_path / "artifacts" / "learning-runs" / "pending-fusion" / "trial_result.json"
    _write_trial(source_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    draft = payload["best_learning_draft"]
    draft["blockers"] = [{"blocker_id": "b1", "label": "Stop on final submit"}]
    draft["verification_rules"] = [{"rule_id": "v1", "label": "Confirm target region is visible"}]
    draft["page_details"] = {
        "pipeline_audit": {
            "precise_understanding_fusion_status": {
                "summary": {
                    "total_locator_cards": 10,
                    "calibrated_cases": 2,
                    "uncalibrated_locator_cards": 8,
                    "real_clicks": 0,
                },
                "pathgraph_preparation": {
                    "status": "blocked_from_pathgraph_candidate_review",
                    "promotable_item_count": 0,
                    "blocked_item_count": 10,
                },
                "calibration_batch_plan": {
                    "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                    "review_blocked_region_numbers": [7, 10],
                    "command_executes_now": False,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "model_start_runbook": {
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
                    },
                    "safety": {
                        "model_started": False,
                        "live_clicks": 0,
                        "live_fills": 0,
                        "live_submits": 0,
                    },
                    "blockers": [],
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                "not_accuracy": True,
            }
        }
    }
    source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    result = build_pathgraph_candidate_from_review(
        source_path,
        {
            "review_status": "approved_as_assisted_template",
            "blockers": draft["blockers"],
            "verification_rules": draft["verification_rules"],
        },
        project_root=tmp_path,
    )

    report = json.loads((tmp_path / result["validation_report_path"]).read_text(encoding="utf-8"))
    wrapper = json.loads((tmp_path / result["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    preflight_sidecar = tmp_path / result["pathgraph_candidate_path"] / ".." / "learn_fusion_model_start_preflight_report.json"
    preflight_sidecar = preflight_sidecar.resolve()
    preflight_sidecar.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_model_start_preflight_v1",
                "preflight_status": "ready_for_explicit_model_start",
                "may_start_model_after_user_approval": True,
                "may_run_calibration_batch_now": False,
                "candidate_validation_status": "blocked_pending_calibration",
                "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                "review_blocked_region_numbers": [7, 10],
                "safety": {
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "blockers": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    demo_readiness_sidecar = tmp_path / result["pathgraph_candidate_path"] / ".." / "learn_fusion_demo_readiness_report.json"
    demo_readiness_sidecar = demo_readiness_sidecar.resolve()
    demo_readiness_sidecar.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_demo_readiness_v1",
                "demo_readiness_status": "ready_for_preflight_demo",
                "recommended_load_path": result["pathgraph_candidate_path"],
                "candidate_validation_status": "blocked_pending_calibration",
                "preflight_status": "ready_for_explicit_model_start",
                "may_run_calibration_batch_now": False,
                "safety": {
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "blockers": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    approval_packet_sidecar = tmp_path / result["pathgraph_candidate_path"] / ".." / "learn_fusion_model_start_approval_packet.json"
    approval_packet_sidecar = approval_packet_sidecar.resolve()
    approval_packet_sidecar.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_model_start_approval_packet_v1",
                "approval_packet_status": "ready_for_user_approval",
                "requires_explicit_user_approval": True,
                "approval_does_not_execute": True,
                "may_start_model_after_user_approval": True,
                "may_run_calibration_batch_now": False,
                "candidate_validation_status": "blocked_pending_calibration",
                "preflight_status": "ready_for_explicit_model_start",
                "demo_readiness_status": "ready_for_preflight_demo",
                "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                "review_blocked_region_numbers": [7, 10],
                "safety": {
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "blockers": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    approval_packet_sha256 = hashlib.sha256(approval_packet_sidecar.read_bytes()).hexdigest()
    calibration_pre_run_sidecar = (
        tmp_path / result["pathgraph_candidate_path"] / ".." / "learn_fusion_calibration_pre_run_check_report.json"
    )
    calibration_pre_run_sidecar = calibration_pre_run_sidecar.resolve()
    calibration_pre_run_sidecar.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_calibration_pre_run_check_v1",
                "pre_run_status": "ready_after_explicit_approval",
                "approval_packet_path": str(approval_packet_sidecar.relative_to(tmp_path)),
                "approval_packet_sha256": approval_packet_sha256,
                "requires_explicit_user_approval": True,
                "may_start_model_after_user_approval": True,
                "may_run_calibration_batch_now": False,
                "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                "command_region_numbers": [1, 2, 3, 6, 8, 9],
                "checks": {"tasks_file_exists": True, "regions_match_ready_regions": True},
                "safety": {
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "blockers": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    pathgraph_integration_sidecar = (
        tmp_path / result["pathgraph_candidate_path"] / ".." / "learn_fusion_pathgraph_integration_readiness_report.json"
    )
    pathgraph_integration_sidecar = pathgraph_integration_sidecar.resolve()
    pathgraph_integration_sidecar.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_pathgraph_integration_readiness_report_v1",
                "integration_readiness_status": "blocked_pending_calibration",
                "candidate_validation_status": "blocked_pending_calibration",
                "ready_for_audited_pathgraph_review": False,
                "ready_for_runtime_pathgraph_promotion": False,
                "blockers": ["pending_calibration_required"],
                "next_required_steps": [
                    "run_approved_numbered_region_calibration_batch",
                    "run_gated_post_batch_refresh",
                ],
                "safety": {
                    "model_started": False,
                    "live_clicks": 0,
                    "live_fills": 0,
                    "live_submits": 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    assert result["validation_status"] == "blocked_pending_calibration"
    assert wrapper["validation_status"] == "blocked_pending_calibration"
    readiness = report["summary"]["precise_understanding_readiness_summary"]
    assert readiness["readiness_status"] == "needs_pending_calibration"
    assert readiness["pending_calibration_ready_count"] == 6
    failed = {item["check_id"] for item in report["checks"] if item["passed"] is False}
    assert "precise_understanding_ready_for_pathgraph_candidate" in failed
    assert report["model_start_runbook"]["runbook_status"] == "awaiting_explicit_model_start_approval"
    assert wrapper["model_start_runbook"]["may_run_calibration_batch_now"] is False
    loaded = load_learning_draft_review(result["pathgraph_candidate_path"], project_root=tmp_path)
    candidate_review = loaded["pathgraph_candidate_review"]
    assert candidate_review["model_start_runbook"]["runbook_status"] == "awaiting_explicit_model_start_approval"
    assert candidate_review["model_start_runbook"]["may_start_model_after_user_approval"] is True
    assert candidate_review["model_start_runbook"]["may_run_calibration_batch_now"] is False
    assert candidate_review["model_start_preflight"]["preflight_status"] == "ready_for_explicit_model_start"
    assert candidate_review["demo_readiness"]["demo_readiness_status"] == "ready_for_preflight_demo"
    assert candidate_review["model_start_approval_packet"]["approval_packet_status"] == "ready_for_user_approval"
    assert candidate_review["model_start_approval_packet"]["approval_does_not_execute"] is True
    assert candidate_review["model_start_approval_packet"]["may_run_calibration_batch_now"] is False
    assert candidate_review["calibration_pre_run_check"]["pre_run_status"] == "ready_after_explicit_approval"
    assert candidate_review["calibration_pre_run_check"]["may_run_calibration_batch_now"] is False
    assert candidate_review["calibration_pre_run_check"]["approval_packet_checksum_status"] == "matched"
    assert candidate_review["calibration_pre_run_check"]["effective_pre_run_status"] == "ready_after_explicit_approval"
    assert candidate_review["calibration_pre_run_check"]["effective_may_run_calibration_batch_now"] is False
    assert candidate_review["calibration_pre_run_check"]["approval_packet_current_sha256"] == approval_packet_sha256
    assert candidate_review["calibration_pre_run_check"]["safety"]["live_clicks"] == 0
    assert candidate_review["pathgraph_integration_readiness"]["integration_readiness_status"] == "blocked_pending_calibration"
    assert candidate_review["pathgraph_integration_readiness"]["ready_for_audited_pathgraph_review"] is False
    assert candidate_review["pathgraph_integration_readiness"]["ready_for_runtime_pathgraph_promotion"] is False
    assert candidate_review["pathgraph_integration_readiness"]["blockers"] == ["pending_calibration_required"]
    assert candidate_review["pathgraph_readiness_summary"]["demo_readiness"]["may_run_calibration_batch_now"] is False
    assert (
        candidate_review["pathgraph_readiness_summary"]["model_start_approval_packet"]["approval_packet_status"]
        == "ready_for_user_approval"
    )
    assert (
        candidate_review["pathgraph_readiness_summary"]["calibration_pre_run_check"]["pre_run_status"]
        == "ready_after_explicit_approval"
    )
    assert (
        candidate_review["pathgraph_readiness_summary"]["calibration_pre_run_check"]["approval_packet_checksum_status"]
        == "matched"
    )
    assert (
        candidate_review["pathgraph_readiness_summary"]["pathgraph_integration_readiness"][
            "integration_readiness_status"
        ]
        == "blocked_pending_calibration"
    )
    assert candidate_review["pathgraph_readiness_summary"]["model_start_preflight"]["may_run_calibration_batch_now"] is False
    assert candidate_review["pathgraph_readiness_summary"]["model_start_runbook"]["ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert report["safety"]["execute_binding_enabled"] is False
    assert report["safety"]["artifact_is_authorization"] is False


def test_pathgraph_candidate_marks_stale_calibration_pre_run_when_approval_packet_changes(tmp_path: Path) -> None:
    from app.learn.draft_review import load_learning_draft_review

    candidate_dir = tmp_path / "artifacts" / "learning-draft-review" / "candidate"
    source_path = candidate_dir / "source_trial.json"
    _write_detail_surface_trial(source_path)
    candidate_path = candidate_dir / "pathgraph_candidate.json"
    candidate_path.write_text(
        json.dumps(
            {
                "contract_version": "pathgraph_candidate_v1",
                "reviewed_template_candidate_path": str(source_path.relative_to(tmp_path)),
                "pathgraph_candidate": {
                    "contract_version": "runtime_path_graph_candidate_v1",
                    "states": [{"state_id": "detail_state", "label": "Job detail"}],
                    "regions": [{"region_id": "apply_button_1", "label": "Apply"}],
                    "action_templates": [
                        {
                            "action_template_id": "apply_entry_1",
                            "semantic_action": "open_apply_flow",
                            "target_entity": "apply_button_1",
                            "target_region_id": "apply_button_1",
                        }
                    ],
                    "blockers": [],
                    "verification_rules": [],
                },
                "validation_status": "blocked_pending_calibration",
                "readiness_summary": {"readiness_status": "needs_pending_calibration"},
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    approval_packet_sidecar = candidate_dir / "learn_fusion_model_start_approval_packet.json"
    approval_packet_sidecar.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_model_start_approval_packet_v1",
                "approval_packet_status": "ready_for_user_approval",
                "requires_explicit_user_approval": True,
                "approval_does_not_execute": True,
                "may_run_calibration_batch_now": False,
                "safety": {"live_clicks": 0, "live_fills": 0, "live_submits": 0},
                "blockers": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    stale_sha256 = hashlib.sha256(approval_packet_sidecar.read_bytes()).hexdigest()
    approval_packet_sidecar.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_model_start_approval_packet_v1",
                "approval_packet_status": "ready_for_user_approval",
                "requires_explicit_user_approval": True,
                "approval_does_not_execute": True,
                "may_run_calibration_batch_now": False,
                "safety": {"live_clicks": 0, "live_fills": 0, "live_submits": 0},
                "blockers": [],
                "reviewer_note": "approval packet changed after pre-run evidence was generated",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    current_sha256 = hashlib.sha256(approval_packet_sidecar.read_bytes()).hexdigest()
    calibration_pre_run_sidecar = candidate_dir / "learn_fusion_calibration_pre_run_check_report.json"
    calibration_pre_run_sidecar.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_calibration_pre_run_check_v1",
                "pre_run_status": "ready_after_explicit_approval",
                "approval_packet_path": str(approval_packet_sidecar.relative_to(tmp_path)),
                "approval_packet_sha256": stale_sha256,
                "requires_explicit_user_approval": True,
                "may_run_calibration_batch_now": False,
                "safety": {"live_clicks": 0, "live_fills": 0, "live_submits": 0},
                "blockers": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    loaded = load_learning_draft_review(candidate_path, project_root=tmp_path)
    calibration_pre_run = loaded["pathgraph_candidate_review"]["calibration_pre_run_check"]

    assert stale_sha256 != current_sha256
    assert calibration_pre_run["approval_packet_checksum_status"] == "mismatch"
    assert calibration_pre_run["approval_packet_current_sha256"] == current_sha256
    assert calibration_pre_run["effective_pre_run_status"] == "stale_pre_run_evidence"
    assert calibration_pre_run["effective_may_run_calibration_batch_now"] is False
    assert calibration_pre_run["stale_pre_run_evidence"] is True
    assert calibration_pre_run["blockers"][0]["blocker_id"] == "approval_packet_checksum_mismatch"
    assert (
        loaded["pathgraph_candidate_review"]["pathgraph_readiness_summary"]["calibration_pre_run_check"][
            "approval_packet_checksum_status"
        ]
        == "mismatch"
    )


def test_pathgraph_candidate_blocks_missing_precise_understanding_evidence(tmp_path: Path) -> None:
    from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review

    source_path = tmp_path / "artifacts" / "learning-runs" / "missing-evidence" / "trial_result.json"
    _write_trial(source_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    draft = payload["best_learning_draft"]
    draft["blockers"] = [{"blocker_id": "b1", "label": "Stop on final submit"}]
    draft["verification_rules"] = [{"rule_id": "v1", "label": "Confirm target region is visible"}]
    draft["page_details"] = {
        "pipeline_audit": {
            "precise_understanding_fusion_status": {
                "screenshot_path": "artifacts/screenshots/missing_seek_results.png",
                "full_screen_understanding_overlay_path": "logs/benchmarks/missing/full_screen_overlay.png",
                "summary": {
                    "total_locator_cards": 1,
                    "calibrated_cases": 1,
                    "uncalibrated_locator_cards": 0,
                    "real_clicks": 0,
                },
                "pathgraph_preparation": {
                    "status": "needs_pathgraph_review",
                    "promotable_item_count": 1,
                    "blocked_item_count": 0,
                },
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                "not_accuracy": True,
            }
        }
    }
    source_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    result = build_pathgraph_candidate_from_review(
        source_path,
        {
            "review_status": "approved_as_assisted_template",
            "blockers": draft["blockers"],
            "verification_rules": draft["verification_rules"],
        },
        project_root=tmp_path,
    )

    report = json.loads((tmp_path / result["validation_report_path"]).read_text(encoding="utf-8"))
    wrapper = json.loads((tmp_path / result["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    assert result["validation_status"] == "blocked_missing_evidence"
    assert wrapper["validation_status"] == "blocked_missing_evidence"
    integrity = report["summary"]["evidence_integrity"]
    assert integrity["status"] == "missing_declared_evidence"
    assert integrity["missing_declared_evidence"] == ["screenshot", "full_screen_understanding_overlay"]
    failed = {item["check_id"] for item in report["checks"] if item["passed"] is False}
    assert "precise_understanding_evidence_integrity_complete" in failed
    assert report["safety"]["execute_binding_enabled"] is False
    assert report["safety"]["artifact_is_authorization"] is False


def test_pathgraph_candidate_turns_open_detail_hint_into_candidate_transition(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api

    trial_path = tmp_path / "artifacts" / "learning-runs" / "open-detail" / "trial_result.json"
    _write_open_detail_trial(trial_path)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    payload = client.post(
        "/panel/generate_pathgraph_candidate",
        json={
            "source_path": "artifacts/learning-runs/open-detail/trial_result.json",
            "review_patch": {"review_status": "approved_as_assisted_template"},
        },
    ).json()

    assert payload["success"] is True
    data = payload["data"]
    reviewed = json.loads((tmp_path / data["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))
    wrapper = json.loads((tmp_path / data["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    graph = json.loads((tmp_path / data["runtime_path_graph_candidate_path"]).read_text(encoding="utf-8"))
    interface_map = json.loads((tmp_path / data["interface_map_candidate_path"]).read_text(encoding="utf-8"))
    report = json.loads((tmp_path / data["validation_report_path"]).read_text(encoding="utf-8"))

    summary = reviewed["audit"]["precise_understanding_summary"]
    assert summary["contract_version"] == "precise_understanding_summary_v1"
    assert summary["region_count"] == 1
    assert summary["action_template_count"] == 1
    assert summary["open_detail_transition_hint_count"] == 1
    assert summary["execute_binding_enabled"] is False
    assert wrapper["precise_understanding_summary"] == summary
    assert report["precise_understanding_summary"] == summary

    action = graph["action_templates"][0]
    assert action["transition_hint"]["contract_version"] == "learn_open_detail_transition_hint_v1"
    assert action["transition_hint"]["execute_binding_enabled"] is False

    detail_state = next(item for item in graph["states"] if item["state_id"] == "model_detail_view")
    assert detail_state["page_type"] == "detail_view"
    assert detail_state["candidate_only"] is True
    assert detail_state["execute_binding_enabled"] is False

    transition = next(item for item in graph["transitions"] if item["action_template_id"] == "open_card_1")
    assert transition["transition_type"] == "open_detail"
    assert transition["from_state_id"] == "seek_results"
    assert transition["to_state_id"] == "model_detail_view"
    assert transition["target_surface"] == "detail_pane_or_detail_page"
    assert transition["requires_post_action_observe"] is True
    assert transition["candidate_only"] is True
    assert transition["artifact_is_authorization"] is False
    assert transition["execute_binding_enabled"] is False
    assert interface_map["transitions"][0]["to_state_id"] == "model_detail_view"

    request = wrapper["pending_detail_observe_requests"][0]
    assert request["contract_version"] == "pending_detail_observe_request_v1"
    assert request["source_action_template_id"] == "open_card_1"
    assert request["from_state_id"] == "seek_results"
    assert request["target_state_id"] == "model_detail_view"
    assert request["target_surface"] == "detail_pane_or_detail_page"
    assert request["requires_user_review"] is True
    assert request["no_dispatch"] is True
    assert request["execute_binding_enabled"] is False
    assert report["pending_detail_observe_requests"] == wrapper["pending_detail_observe_requests"]
    assert data["pending_detail_observe_requests"] == wrapper["pending_detail_observe_requests"]


def test_attach_detail_observe_result_merges_detail_surface_review_only(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api
    from app.learn.pathgraph_candidate import attach_detail_observe_result_to_candidate

    results_path = tmp_path / "artifacts" / "learning-runs" / "open-detail" / "trial_result.json"
    detail_path = tmp_path / "artifacts" / "learning-runs" / "detail" / "trial_result.json"
    _write_open_detail_trial(results_path)
    _write_detail_surface_trial(detail_path)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    build_payload = client.post(
        "/panel/generate_pathgraph_candidate",
        json={
            "source_path": "artifacts/learning-runs/open-detail/trial_result.json",
            "review_patch": {"review_status": "approved_as_assisted_template"},
        },
    ).json()
    assert build_payload["success"] is True

    attach_result = attach_detail_observe_result_to_candidate(
        tmp_path / build_payload["data"]["pathgraph_candidate_path"],
        request_id="detail_observe:open_card_1",
        detail_source_path=detail_path,
        project_root=tmp_path,
    )

    wrapper = json.loads((tmp_path / attach_result["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    graph = json.loads((tmp_path / attach_result["runtime_path_graph_candidate_path"]).read_text(encoding="utf-8"))
    interface_map = json.loads((tmp_path / attach_result["interface_map_candidate_path"]).read_text(encoding="utf-8"))
    report = json.loads((tmp_path / attach_result["validation_report_path"]).read_text(encoding="utf-8"))

    assert attach_result["contract_version"] == "detail_observe_attachment_result_v1"
    assert attach_result["execute_binding_enabled"] is False
    assert attach_result["artifact_is_authorization"] is False
    assert len(wrapper["detail_surface_attachments"]) == 1
    attachment = wrapper["detail_surface_attachments"][0]
    assert attachment["contract_version"] == "detail_surface_attachment_v1"
    assert attachment["request_id"] == "detail_observe:open_card_1"
    assert attachment["target_state_id"] == "model_detail_view"
    assert attachment["region_count"] == 2
    assert attachment["action_template_count"] == 1
    assert attachment["no_dispatch"] is True
    assert attachment["execute_binding_enabled"] is False
    assert wrapper["pending_detail_observe_requests"][0]["status"] == "attached"
    assert wrapper["precise_understanding_summary"]["detail_surface_attachment_count"] == 1
    assert wrapper["precise_understanding_summary"]["region_count"] == 3
    assert wrapper["precise_understanding_summary"]["action_template_count"] == 2
    assert report["detail_surface_attachments"] == wrapper["detail_surface_attachments"]

    detail_state = next(item for item in graph["states"] if item["state_id"] == "model_detail_view")
    assert "model_detail_view::detail_header_1" in detail_state["region_refs"]
    assert any(item["region_id"] == "model_detail_view::detail_header_1" for item in interface_map["regions"])
    detail_action = next(item for item in graph["action_templates"] if item["action_template_id"] == "model_detail_view::apply_entry_1")
    assert detail_action["target_entity"] == "model_detail_view::apply_button_1"
    assert detail_action["state_id"] == "model_detail_view"
    assert detail_action["execute_binding_enabled"] is False

    from app.learn.draft_review import load_learning_draft_review

    loaded_review = load_learning_draft_review(tmp_path / attach_result["pathgraph_candidate_path"], project_root=tmp_path)
    candidate_review = loaded_review["pathgraph_candidate_review"]
    assert candidate_review["contract_version"] == "pathgraph_candidate_review_v1"
    assert candidate_review["execute_binding_enabled"] is False
    assert candidate_review["artifact_is_authorization"] is False
    assert candidate_review["detail_surface_attachments"][0]["request_id"] == "detail_observe:open_card_1"
    assert candidate_review["pending_detail_observe_requests"][0]["status"] == "attached"
    assert candidate_review["detail_region_count"] == 2
    assert candidate_review["detail_action_template_count"] == 1
    assert candidate_review["attached_detail_regions"][0]["region_id"].startswith("model_detail_view::")
    assert candidate_review["attached_detail_actions"][0]["action_template_id"] == "model_detail_view::apply_entry_1"
    readiness = candidate_review["pathgraph_readiness_summary"]
    assert readiness["contract_version"] == "pathgraph_candidate_readiness_summary_v1"
    assert readiness["readiness_status"] == "needs_promotion_review"
    assert readiness["state_count"] == 2
    assert readiness["region_count"] == 3
    assert readiness["action_template_count"] == 2
    assert readiness["detail_surface_attachment_count"] == 1
    assert readiness["pending_detail_observe_request_count"] == 1
    assert readiness["attached_detail_region_count"] == 2
    assert readiness["attached_detail_action_count"] == 1
    assert readiness["execute_binding_enabled"] is False
    assert readiness["artifact_is_authorization"] is False
    assert "review_only_not_promoted" in readiness["promotion_review_blockers"]
    gate = readiness["promotion_review_gate"]
    assert gate["contract_version"] == "pathgraph_promotion_review_gate_v1"
    assert gate["gate_status"] == "blocked_from_promotion_review"
    check_ids = {item["check_id"]: item for item in gate["checks"]}
    assert check_ids["current_screen_freshness"]["passed"] is False
    assert check_ids["action_taxonomy"]["passed"] is True
    assert check_ids["verification_rules"]["passed"] is True
    assert check_ids["blockers_present"]["passed"] is True
    assert check_ids["final_submit_safety"]["passed"] is True
    assert check_ids["no_dispatch_policy"]["passed"] is True
    assert gate["execute_binding_enabled"] is False
    assert gate["artifact_is_authorization"] is False


def test_create_assisted_template_review_package_requires_passed_gate(tmp_path: Path, monkeypatch) -> None:
    import app.api.panel as panel_api
    from app.learn.assisted_template_review import (
        create_assisted_template_acceptance_suggestions,
        create_assisted_template_acceptance_simulation,
        create_assisted_template_asset_candidate,
        create_assisted_template_audited_promotion_request,
        create_assisted_template_graph_draft,
        create_assisted_template_promotion_preflight,
        create_assisted_template_review_package,
        load_assisted_template_review_package,
        save_assisted_template_review_decisions,
    )
    from app.learn.pathgraph_candidate import attach_detail_observe_result_to_candidate

    results_path = tmp_path / "artifacts" / "learning-runs" / "open-detail" / "trial_result.json"
    detail_path = tmp_path / "artifacts" / "learning-runs" / "detail" / "trial_result.json"
    _write_open_detail_trial(results_path)
    _write_detail_surface_trial(detail_path)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    client = TestClient(app)
    build_payload = client.post(
        "/panel/generate_pathgraph_candidate",
        json={
            "source_path": "artifacts/learning-runs/open-detail/trial_result.json",
            "review_patch": {"review_status": "approved_as_assisted_template"},
        },
    ).json()
    assert build_payload["success"] is True
    attach_result = attach_detail_observe_result_to_candidate(
        tmp_path / build_payload["data"]["pathgraph_candidate_path"],
        request_id="detail_observe:open_card_1",
        detail_source_path=detail_path,
        project_root=tmp_path,
    )
    candidate_path = tmp_path / attach_result["pathgraph_candidate_path"]

    blocked_response = client.post(
        "/panel/create_assisted_template_review_package",
        json={"candidate_path": attach_result["pathgraph_candidate_path"]},
    ).json()
    assert blocked_response["success"] is False
    assert blocked_response["error"]["code"] == "assisted_template_review_package_failed"
    assert "not ready for human promotion review" in blocked_response["error"]["details"]

    wrapper = json.loads(candidate_path.read_text(encoding="utf-8"))
    wrapper["source_freshness_summary"] = {
        "contract_version": "source_freshness_summary_v1",
        "source_image_status": "available",
        "checksum_status": "matched",
        "freshness_status": "verified",
        "warning_count": 0,
        "warnings": [],
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    candidate_path.write_text(json.dumps(wrapper, ensure_ascii=False, indent=2), encoding="utf-8")

    result = create_assisted_template_review_package(
        attach_result["pathgraph_candidate_path"],
        review_decision="approved_for_assisted_template_asset",
        reviewer_note="fixture review",
        project_root=tmp_path,
    )
    assert result["contract_version"] == "assisted_template_review_package_create_v1"
    assert result["promotion_gate_status"] == "passed_for_human_promotion_review"
    assert result["remaining_failed_checks"] == []
    assert result["ready_for_runtime_pathgraph_promotion"] is False
    assert result["execute_binding_enabled"] is False
    assert result["artifact_is_authorization"] is False

    package = json.loads((tmp_path / result["package_path"]).read_text(encoding="utf-8"))
    assert package["contract_version"] == "assisted_template_review_package_v1"
    assert package["review_decision"] == "approved_for_assisted_template_asset"
    assert package["reviewer_note"] == "fixture review"
    assert package["promotion_review_gate"]["gate_status"] == "passed_for_human_promotion_review"
    assert package["summary"]["ready_for_runtime_pathgraph_promotion"] is False
    assert package["execute_binding_enabled"] is False
    assert package["artifact_is_authorization"] is False
    assert package["final_submit_forbidden"] is True
    assert {item["item_type"] for item in package["checklist_items"]} >= {"state", "region", "action", "transition"}
    loaded_package = load_assisted_template_review_package(result["package_path"], project_root=tmp_path)
    assert loaded_package["contract_version"] == "assisted_template_review_package_v1"
    assert loaded_package["package_path"] == result["package_path"]
    assert loaded_package["package_sha256"]
    assert loaded_package["execute_binding_enabled"] is False
    assert loaded_package["artifact_is_authorization"] is False
    assert len(loaded_package["checklist_items"]) == len(package["checklist_items"])

    first_state = next(item for item in loaded_package["checklist_items"] if item["item_type"] == "state")
    first_action = next(item for item in loaded_package["checklist_items"] if item["item_type"] == "action")
    suggestions_result = create_assisted_template_acceptance_suggestions(result["package_path"], project_root=tmp_path)
    assert suggestions_result["contract_version"] == "assisted_template_acceptance_suggestions_create_v1"
    assert suggestions_result["suggestion_status"] == "ready_for_human_review"
    assert suggestions_result["summary"]["suggestion_count"] >= 1
    assert suggestions_result["ready_for_runtime_pathgraph_promotion"] is False
    assert suggestions_result["execute_binding_enabled"] is False
    assert suggestions_result["artifact_is_authorization"] is False
    suggestions = json.loads((tmp_path / suggestions_result["suggestions_path"]).read_text(encoding="utf-8"))
    assert suggestions["contract_version"] == "assisted_template_acceptance_suggestions_v1"
    assert suggestions["artifact_is_authorization"] is False
    assert suggestions["execute_binding_enabled"] is False
    first_action_suggestion = next(
        item for item in suggestions["suggestions"] if item["suggestion_id"] == f"linked_acceptance:{first_action['item_id']}"
    )
    assert {"item_type": "action", "item_id": first_action["item_id"]} in first_action_suggestion["items"]
    assert first_action_suggestion["recommended_decision"] == "accepted"
    loaded_with_suggestions = load_assisted_template_review_package(result["package_path"], project_root=tmp_path)
    assert loaded_with_suggestions["acceptance_suggestions"]["load_status"] == "loaded"
    assert loaded_with_suggestions["acceptance_suggestions"]["summary"]["suggestion_count"] >= 1
    simulation_result = create_assisted_template_acceptance_simulation(result["package_path"], project_root=tmp_path)
    assert simulation_result["contract_version"] == "assisted_template_acceptance_simulation_create_v1"
    assert simulation_result["simulation_status"] == "would_make_preflight_ready_for_audit_request_preview"
    assert simulation_result["selected_suggestion_ids"]
    assert simulation_result["ready_for_runtime_pathgraph_promotion"] is False
    assert simulation_result["execute_binding_enabled"] is False
    assert simulation_result["artifact_is_authorization"] is False
    simulation = json.loads((tmp_path / simulation_result["simulation_path"]).read_text(encoding="utf-8"))
    assert simulation["contract_version"] == "assisted_template_acceptance_simulation_v1"
    assert simulation["simulated_asset_validation_summary"]["validation_status"] == "passed_manual_asset_checks"
    assert simulation["simulated_preflight"]["preflight_status"] == "ready_for_audited_runtime_promotion_review"
    assert simulation["simulated_preflight"]["ready_for_runtime_pathgraph_promotion"] is False
    assert simulation["artifact_is_authorization"] is False
    assert simulation["execute_binding_enabled"] is False
    loaded_with_simulation = load_assisted_template_review_package(result["package_path"], project_root=tmp_path)
    assert loaded_with_simulation["acceptance_simulation"]["load_status"] == "loaded"
    assert loaded_with_simulation["acceptance_simulation"]["simulation_status"] == "would_make_preflight_ready_for_audit_request_preview"
    pending_record_result = save_assisted_template_review_decisions(
        result["package_path"],
        [{"item_type": first_state["item_type"], "item_id": first_state["item_id"], "decision": "pending_review"}],
        overall_decision="needs_changes",
        project_root=tmp_path,
    )
    empty_asset_result = create_assisted_template_asset_candidate(
        result["package_path"],
        review_record_path=pending_record_result["review_record_path"],
        project_root=tmp_path,
    )
    assert empty_asset_result["contract_version"] == "assisted_template_asset_candidate_create_v1"
    assert empty_asset_result["asset_candidate_status"] == "no_accepted_items"
    assert empty_asset_result["summary"]["accepted_total_count"] == 0
    assert empty_asset_result["ready_for_runtime_pathgraph_promotion"] is False
    assert empty_asset_result["execute_binding_enabled"] is False
    assert empty_asset_result["artifact_is_authorization"] is False
    loaded_with_pending_record = load_assisted_template_review_package(result["package_path"], project_root=tmp_path)
    assert loaded_with_pending_record["review_record"]["load_status"] == "loaded"
    assert loaded_with_pending_record["review_record"]["decision_summary"]["pending_review"] == 1
    assert loaded_with_pending_record["asset_candidate"]["load_status"] == "loaded"
    assert loaded_with_pending_record["asset_candidate"]["asset_candidate_status"] == "no_accepted_items"

    record_result = save_assisted_template_review_decisions(
        result["package_path"],
        [
            {
                "item_type": first_state["item_type"],
                "item_id": first_state["item_id"],
                "decision": "accepted",
                "note": "state reviewed for assisted template",
                "overrides": {
                    "label": "Reviewed results state",
                    "semantic_action": "reviewed_state",
                    "target_entity": "reviewed_target",
                    "execute_binding_enabled": True,
                },
            },
            {"item_type": first_action["item_type"], "item_id": first_action["item_id"], "decision": "needs_changes", "note": "label review"},
            {"item_type": "state", "item_id": "does_not_exist", "decision": "accepted"},
        ],
        overall_decision="needs_changes",
        reviewer_note="manual fixture review",
        project_root=tmp_path,
    )
    assert record_result["contract_version"] == "assisted_template_review_record_save_v1"
    assert record_result["decision_summary"] == {
        "accepted": 1,
        "needs_changes": 1,
        "rejected": 0,
        "pending_review": 0,
        "total": 2,
    }
    assert record_result["execute_binding_enabled"] is False
    record = json.loads((tmp_path / record_result["review_record_path"]).read_text(encoding="utf-8"))
    assert record["contract_version"] == "assisted_template_review_record_v1"
    assert len(record["item_decisions"]) == 2
    accepted_decision = next(item for item in record["item_decisions"] if item["decision"] == "accepted")
    assert accepted_decision["note"] == "state reviewed for assisted template"
    assert accepted_decision["overrides"] == {
        "label": "Reviewed results state",
        "semantic_action": "reviewed_state",
        "target_entity": "reviewed_target",
    }
    assert record["artifact_is_authorization"] is False
    assert record["execute_binding_enabled"] is False
    asset_result = create_assisted_template_asset_candidate(
        result["package_path"],
        review_record_path=record_result["review_record_path"],
        project_root=tmp_path,
    )
    assert asset_result["contract_version"] == "assisted_template_asset_candidate_create_v1"
    assert asset_result["asset_candidate_status"] == "ready_for_manual_template_asset_review"
    assert asset_result["summary"]["accepted_state_count"] == 1
    assert asset_result["summary"]["accepted_action_template_count"] == 0
    assert asset_result["summary"]["accepted_total_count"] == 1
    assert asset_result["summary"]["asset_validation_status"] == "passed_manual_asset_checks"
    assert asset_result["asset_validation_summary"]["validation_status"] == "passed_manual_asset_checks"
    assert asset_result["ready_for_runtime_pathgraph_promotion"] is False
    assert asset_result["execute_binding_enabled"] is False
    assert asset_result["artifact_is_authorization"] is False
    asset = json.loads((tmp_path / asset_result["asset_candidate_path"]).read_text(encoding="utf-8"))
    assert asset["contract_version"] == "assisted_template_asset_candidate_v1"
    assert asset["asset_candidate_status"] == "ready_for_manual_template_asset_review"
    assert len(asset["accepted_items"]["states"]) == 1
    assert asset["accepted_items"]["states"][0]["state_id"] == first_state["item_id"]
    assert asset["accepted_items"]["states"][0]["label"] == "Reviewed results state"
    assert asset["accepted_items"]["states"][0]["semantic_action"] == "reviewed_state"
    assert asset["accepted_items"]["states"][0]["target_entity"] == "reviewed_target"
    assert asset["accepted_items"]["states"][0]["human_review_note"] == "state reviewed for assisted template"
    assert asset["accepted_items"]["states"][0]["human_review_overrides"] == {
        "label": "Reviewed results state",
        "semantic_action": "reviewed_state",
        "target_entity": "reviewed_target",
    }
    assert asset["accepted_items"]["states"][0]["execute_binding_enabled"] is False
    assert asset["accepted_items"]["action_templates"] == []
    assert asset["accepted_item_keys"][0]["note"] == "state reviewed for assisted template"
    assert asset["accepted_item_keys"][0]["overrides"]["label"] == "Reviewed results state"
    assert asset["asset_validation_summary"]["error_count"] == 0
    assert asset["ready_for_runtime_pathgraph_promotion"] is False
    graph_draft_result = create_assisted_template_graph_draft(asset_result["asset_candidate_path"], project_root=tmp_path)
    assert graph_draft_result["contract_version"] == "assisted_template_graph_draft_create_v1"
    assert graph_draft_result["graph_draft_status"] == "ready_for_manual_pathgraph_review"
    assert graph_draft_result["summary"]["state_count"] == 1
    assert graph_draft_result["summary"]["asset_validation_status"] == "passed_manual_asset_checks"
    assert len(graph_draft_result["states"]) == 1
    assert graph_draft_result["states"][0]["state_id"] == first_state["item_id"]
    assert graph_draft_result["action_templates"] == []
    assert graph_draft_result["ready_for_runtime_pathgraph_promotion"] is False
    graph_draft = json.loads((tmp_path / graph_draft_result["graph_draft_path"]).read_text(encoding="utf-8"))
    assert graph_draft["contract_version"] == "assisted_template_graph_draft_v1"
    assert graph_draft["states"][0]["execute_binding_enabled"] is False
    assert graph_draft["execute_binding_enabled"] is False
    preflight_result = create_assisted_template_promotion_preflight(result["package_path"], project_root=tmp_path)
    assert preflight_result["contract_version"] == "assisted_template_promotion_preflight_create_v1"
    assert preflight_result["preflight_status"] == "ready_for_audited_runtime_promotion_review"
    assert preflight_result["ready_for_runtime_pathgraph_promotion"] is False
    assert preflight_result["execute_binding_enabled"] is False
    assert preflight_result["artifact_is_authorization"] is False
    preflight = json.loads((tmp_path / preflight_result["preflight_path"]).read_text(encoding="utf-8"))
    assert preflight["contract_version"] == "assisted_template_promotion_preflight_v1"
    assert preflight["audit_required_before_runtime_promotion"] is True
    assert preflight["checks"]["asset_validation_passed"] is True
    assert preflight["checks"]["graph_draft_ready"] is True
    assert preflight["checks"]["accepted_items_exported_to_graph"] is True
    assert preflight["blocker_details"] == []
    assert preflight["ready_for_runtime_pathgraph_promotion"] is False
    assert preflight["execute_binding_enabled"] is False
    request_result = create_assisted_template_audited_promotion_request(result["package_path"], project_root=tmp_path)
    assert request_result["contract_version"] == "assisted_template_audited_promotion_request_create_v1"
    assert request_result["request_status"] == "ready_for_external_audited_promotion_design"
    assert request_result["ready_for_runtime_pathgraph_promotion"] is False
    assert request_result["execute_binding_enabled"] is False
    assert request_result["artifact_is_authorization"] is False
    request_payload = json.loads((tmp_path / request_result["request_path"]).read_text(encoding="utf-8"))
    assert request_payload["contract_version"] == "assisted_template_audited_promotion_request_v1"
    assert request_payload["requires_separate_audited_promotion_path"] is True
    assert request_payload["ready_for_runtime_pathgraph_promotion"] is False
    assert request_payload["execute_binding_enabled"] is False
    loaded_with_asset = load_assisted_template_review_package(result["package_path"], project_root=tmp_path)
    assert loaded_with_asset["review_record"]["load_status"] == "loaded"
    assert loaded_with_asset["review_record"]["decision_summary"]["accepted"] == 1
    assert loaded_with_asset["asset_candidate"]["load_status"] == "loaded"
    assert loaded_with_asset["asset_candidate"]["asset_candidate_status"] == "ready_for_manual_template_asset_review"
    assert loaded_with_asset["asset_candidate"]["summary"]["accepted_total_count"] == 1
    assert loaded_with_asset["asset_candidate"]["asset_validation_summary"]["validation_status"] == "passed_manual_asset_checks"

    action_only_record = save_assisted_template_review_decisions(
        result["package_path"],
        [
            {
                "item_type": first_action["item_type"],
                "item_id": first_action["item_id"],
                "decision": "accepted",
                "overrides": {"semantic_action": "open_detail", "target_entity": first_action["target_entity"]},
            }
        ],
        overall_decision="accepted_for_assisted_template_review",
        project_root=tmp_path,
    )
    action_only_asset_result = create_assisted_template_asset_candidate(
        result["package_path"],
        review_record_path=action_only_record["review_record_path"],
        project_root=tmp_path,
    )
    assert action_only_asset_result["asset_validation_summary"]["validation_status"] == "needs_manual_fix"
    assert action_only_asset_result["asset_validation_summary"]["error_count"] >= 1
    assert {
        issue["check_id"] for issue in action_only_asset_result["asset_validation_summary"]["issues"]
    } >= {"action_target_region_not_accepted"}
    blocked_graph_result = create_assisted_template_graph_draft(
        action_only_asset_result["asset_candidate_path"],
        project_root=tmp_path,
    )
    assert blocked_graph_result["graph_draft_status"] == "blocked_by_asset_validation"
    assert blocked_graph_result["asset_validation_summary"]["validation_status"] == "needs_manual_fix"
    blocked_preflight_result = create_assisted_template_promotion_preflight(result["package_path"], project_root=tmp_path)
    assert blocked_preflight_result["preflight_status"] == "blocked_before_runtime_promotion_review"
    assert "asset_validation_passed" in blocked_preflight_result["blockers"]
    assert blocked_preflight_result["blocker_details"]
    asset_blocker = next(
        item for item in blocked_preflight_result["blocker_details"] if item["check_id"] == "asset_validation_passed"
    )
    assert asset_blocker["severity"] == "blocking"
    assert asset_blocker["recommended_action"]
    assert asset_blocker["runtime_promotion_allowed"] is False
    with pytest.raises(ValueError, match="preflight is not ready"):
        create_assisted_template_audited_promotion_request(result["package_path"], project_root=tmp_path)

    api_response = client.post(
        "/panel/create_assisted_template_review_package",
        json={
            "candidate_path": attach_result["pathgraph_candidate_path"],
            "review_decision": "approved_for_assisted_template_asset",
            "reviewer_note": "panel route",
        },
    ).json()
    assert api_response["success"] is True
    assert api_response["data"]["package_path"] == result["package_path"]
    assert api_response["data"]["execute_binding_enabled"] is False
    assert api_response["data"]["artifact_is_authorization"] is False

    load_response = client.post(
        "/panel/load_assisted_template_review_package",
        json={"package_path": result["package_path"]},
    ).json()
    assert load_response["success"] is True
    assert load_response["data"]["contract_version"] == "assisted_template_review_package_v1"
    assert load_response["data"]["package_path"] == result["package_path"]
    assert load_response["data"]["execute_binding_enabled"] is False
    assert load_response["data"]["artifact_is_authorization"] is False
    assert load_response["data"]["acceptance_suggestions"]["load_status"] == "loaded"

    suggestions_response = client.post(
        "/panel/create_assisted_template_acceptance_suggestions",
        json={"package_path": result["package_path"]},
    ).json()
    assert suggestions_response["success"] is True
    assert suggestions_response["data"]["suggestion_status"] == "ready_for_human_review"
    assert suggestions_response["data"]["summary"]["suggestion_count"] >= 1
    assert suggestions_response["data"]["ready_for_runtime_pathgraph_promotion"] is False
    assert suggestions_response["data"]["execute_binding_enabled"] is False
    assert suggestions_response["data"]["artifact_is_authorization"] is False

    simulation_response = client.post(
        "/panel/create_assisted_template_acceptance_simulation",
        json={"package_path": result["package_path"]},
    ).json()
    assert simulation_response["success"] is True
    assert simulation_response["data"]["simulation_status"] == "would_make_preflight_ready_for_audit_request_preview"
    assert simulation_response["data"]["selected_suggestion_ids"]
    assert simulation_response["data"]["ready_for_runtime_pathgraph_promotion"] is False
    assert simulation_response["data"]["execute_binding_enabled"] is False
    assert simulation_response["data"]["artifact_is_authorization"] is False

    save_response = client.post(
        "/panel/save_assisted_template_review_decisions",
        json={
            "package_path": result["package_path"],
            "overall_decision": "accepted_for_assisted_template_review",
            "decisions": [
                {"item_type": first_state["item_type"], "item_id": first_state["item_id"], "decision": "accepted"}
            ],
        },
    ).json()
    assert save_response["success"] is True
    assert save_response["data"]["decision_summary"]["accepted"] == 1
    assert save_response["data"]["ready_for_runtime_pathgraph_promotion"] is False
    assert save_response["data"]["execute_binding_enabled"] is False

    asset_response = client.post(
        "/panel/create_assisted_template_asset_candidate",
        json={"package_path": result["package_path"]},
    ).json()
    assert asset_response["success"] is True
    assert asset_response["data"]["asset_candidate_status"] == "ready_for_manual_template_asset_review"
    assert asset_response["data"]["summary"]["accepted_total_count"] == 1
    assert asset_response["data"]["ready_for_runtime_pathgraph_promotion"] is False
    assert asset_response["data"]["execute_binding_enabled"] is False
    assert asset_response["data"]["artifact_is_authorization"] is False

    graph_response = client.post(
        "/panel/create_assisted_template_graph_draft",
        json={"asset_candidate_path": asset_response["data"]["asset_candidate_path"]},
    ).json()
    assert graph_response["success"] is True
    assert "states" in graph_response["data"]
    assert "action_templates" in graph_response["data"]
    assert graph_response["data"]["graph_draft_status"] in {
        "ready_for_manual_pathgraph_review",
        "blocked_by_asset_validation",
        "no_accepted_items",
    }
    assert graph_response["data"]["ready_for_runtime_pathgraph_promotion"] is False
    assert graph_response["data"]["execute_binding_enabled"] is False

    preflight_response = client.post(
        "/panel/create_assisted_template_promotion_preflight",
        json={"package_path": result["package_path"]},
    ).json()
    assert preflight_response["success"] is True
    assert preflight_response["data"]["preflight_status"] in {
        "ready_for_audited_runtime_promotion_review",
        "blocked_before_runtime_promotion_review",
    }
    assert preflight_response["data"]["ready_for_runtime_pathgraph_promotion"] is False
    assert preflight_response["data"]["execute_binding_enabled"] is False

    request_response = client.post(
        "/panel/create_assisted_template_audited_promotion_request",
        json={"package_path": result["package_path"]},
    ).json()
    assert request_response["success"] is True
    assert request_response["data"]["request_status"] == "ready_for_external_audited_promotion_design"
    assert request_response["data"]["ready_for_runtime_pathgraph_promotion"] is False
    assert request_response["data"]["execute_binding_enabled"] is False
    assert request_response["data"]["artifact_is_authorization"] is False


def test_default_learning_draft_demo_artifacts_load() -> None:
    from app.learn.draft_review import load_learning_draft_review

    paths = [
        Path("artifacts/learning-draft-review/branch_hub_2584f138b7/reviewed_template_candidate.json"),
        Path("artifacts/learning-draft-review/branch_hub_2584f138b7/pathgraph_candidate/pathgraph_candidate.json"),
        Path("artifacts/learning-draft-review/branch_hub_2584f138b7/pathgraph_candidate/promotion_validation_report.json"),
    ]

    for path in paths:
        assert path.exists()
        review = load_learning_draft_review(path)
        assert len(review["draft"]["states"]) == 1
        assert len(review["draft"]["regions"]) == 3
        assert len(review["draft"]["action_templates"]) == 3
