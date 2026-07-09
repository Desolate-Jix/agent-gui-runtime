from __future__ import annotations

import json
from pathlib import Path

from scripts.build_learn_fusion_pathgraph_preflight import build_pathgraph_preflight_plan


def test_build_pathgraph_preflight_plan_from_review_queue(tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_pathgraph_review_queue_v1",
                "summary": {
                    "attempted": 4,
                    "open_detail_candidate_review": 1,
                    "same_screen_action_review": 1,
                    "geometry_review_required": 1,
                    "blocked_non_action": 1,
                    "real_clicks": 0,
                },
                "queue_items": [
                    {
                        "region_no": 4,
                        "source_item_id": "c4",
                        "label": "Job listing card: Software Engineer",
                        "role": "card",
                        "review_bucket": "open_detail_candidate_review",
                        "candidate_semantic_action": "open_detail",
                        "trace_path": "trace-card.json",
                        "overlay_path": "overlay-card.png",
                        "rough_bbox_hint": {"x": 10, "y": 20, "w": 300, "h": 120},
                        "selected_click_point": {"x": 100, "y": 80},
                        "required_next_evidence": [
                            "human_review_open_detail_candidate",
                            "post_action_detail_observe_after_approved_no_dispatch",
                        ],
                        "real_clicks": 0,
                    },
                    {
                        "region_no": 3,
                        "source_item_id": "c3",
                        "label": "Search button",
                        "role": "button",
                        "review_bucket": "same_screen_action_review",
                        "candidate_semantic_action": "click_or_toggle_review",
                        "real_clicks": 0,
                    },
                    {
                        "region_no": 8,
                        "source_item_id": "c9",
                        "label": "Filter toggle",
                        "role": "toggle",
                        "review_bucket": "geometry_review_required",
                        "real_clicks": 0,
                    },
                    {
                        "region_no": 7,
                        "source_item_id": "c8",
                        "label": "Job details placeholder",
                        "role": "other",
                        "review_bucket": "blocked_non_action",
                        "real_clicks": 0,
                    },
                ],
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    batch_plan_path = tmp_path / "numbered_region_calibration_batch_plan.json"
    batch_plan_path.write_text(
        json.dumps(
            {
                "contract_version": "numbered_region_calibration_batch_plan_v1",
                "summary": {
                    "ready_for_execute_dry_run": 6,
                    "review_before_calibration": 2,
                    "real_clicks": 0,
                    "execute_binding_enabled": False,
                },
                "ready_region_numbers": [1, 2, 3, 6, 8, 9],
                "review_blocked_region_numbers": [7, 10],
                "run_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2,3,6,8,9",
                "command_executes_now": False,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_pathgraph_preflight_plan(
        queue_path=queue_path,
        calibration_batch_plan_path=batch_plan_path,
        out_dir=tmp_path / "out",
    )

    plan = json.loads(Path(result["preflight_plan_path"]).read_text(encoding="utf-8"))
    assert plan["contract_version"] == "learn_fusion_pathgraph_preflight_plan_v1"
    assert plan["summary"]["open_detail_transition_candidates"] == 1
    assert plan["summary"]["same_screen_action_candidates"] == 1
    assert plan["summary"]["geometry_blockers"] == 1
    assert plan["summary"]["non_action_blockers"] == 1
    assert plan["summary"]["pending_calibration_ready_count"] == 6
    assert plan["summary"]["pending_calibration_review_count"] == 2
    assert plan["summary"]["ready_for_runtime_pathgraph_promotion"] is False
    assert plan["pending_calibration_batch"]["ready_region_numbers"] == [1, 2, 3, 6, 8, 9]
    assert plan["pending_calibration_batch"]["review_blocked_region_numbers"] == [7, 10]
    assert plan["pending_calibration_batch"]["command_executes_now"] is False
    assert plan["pending_calibration_batch"]["execute_binding_enabled"] is False
    assert plan["pending_calibration_batch"]["artifact_is_authorization"] is False
    assert "run_pending_numbered_region_calibration_batch_before_pathgraph_promotion" in plan["next_required_steps"]
    assert plan["proposed_states"] == [
        {"state_id": "seek_results", "state_role": "results_list", "candidate_only": True},
        {"state_id": "model_detail_view", "state_role": "detail_view", "candidate_only": True},
    ]
    transition = plan["proposed_transitions"][0]
    assert transition["transition_type"] == "open_detail"
    assert transition["from_state_id"] == "seek_results"
    assert transition["to_state_id"] == "model_detail_view"
    assert transition["requires_post_action_observe"] is True
    assert transition["rough_bbox_hint"] == {"x": 10, "y": 20, "w": 300, "h": 120}
    assert transition["selected_click_point"] == {"x": 100, "y": 80}
    assert transition["no_dispatch"] is True
    assert transition["artifact_is_authorization"] is False
    assert plan["review_action_items"][0]["review_bucket"] == "same_screen_action_review"
    assert {item["review_bucket"] for item in plan["blocked_items"]} == {"geometry_review_required", "blocked_non_action"}
    assert plan["execute_binding_enabled"] is False
    assert plan["artifact_is_authorization"] is False
