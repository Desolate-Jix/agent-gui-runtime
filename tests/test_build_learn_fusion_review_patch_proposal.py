from __future__ import annotations

import json
from pathlib import Path

from scripts.build_learn_fusion_review_patch_proposal import build_review_patch_proposal


def test_build_review_patch_proposal_from_preflight_plan(tmp_path: Path) -> None:
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_pathgraph_preflight_plan_v1",
                "summary": {"open_detail_transition_candidates": 1, "ready_for_runtime_pathgraph_promotion": False},
                "proposed_states": [
                    {"state_id": "seek_results", "state_role": "results_list", "candidate_only": True},
                    {"state_id": "model_detail_view", "state_role": "detail_view", "candidate_only": True},
                ],
                "proposed_transitions": [
                    {
                        "transition_id": "preflight_transition_fusion_open_detail_region_4",
                        "action_template_id": "fusion_open_detail_region_4",
                        "source_region_no": 4,
                        "source_item_id": "c4",
                        "label": "Job listing card",
                        "transition_type": "open_detail",
                        "semantic_action": "open_detail",
                        "from_state_id": "seek_results",
                        "to_state_id": "model_detail_view",
                        "target_surface": "detail_pane_or_detail_page",
                        "requires_post_action_observe": True,
                        "rough_bbox_hint": {"x": 10, "y": 20, "w": 300, "h": 120},
                        "selected_click_point": {"x": 100, "y": 80},
                        "execute_binding_enabled": True,
                        "artifact_is_authorization": True,
                    }
                ],
                "review_action_items": [{"region_no": 3, "label": "Search button"}],
                "blocked_items": [{"region_no": 8, "review_bucket": "geometry_review_required"}],
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_review_patch_proposal(preflight_plan_path=preflight_path, out_dir=tmp_path / "out")

    proposal = json.loads(Path(result["proposal_path"]).read_text(encoding="utf-8"))
    patch = proposal["review_patch"]
    assert proposal["contract_version"] == "learn_fusion_review_patch_proposal_v1"
    assert proposal["summary"]["state_additions"] == 1
    assert proposal["summary"]["region_additions"] == 1
    assert proposal["summary"]["action_template_additions"] == 1
    assert proposal["summary"]["transition_additions"] == 1
    assert patch["review_status"] == "needs_human_review"
    assert patch["source_after_review"] == "assisted_generation"
    assert patch["state_additions"][0]["state_id"] == "model_detail_view"
    assert patch["state_additions"][0]["candidate_only"] is True
    assert patch["state_additions"][0]["execute_binding_enabled"] is False
    assert patch["state_additions"][0]["artifact_is_authorization"] is False
    region = patch["region_additions"][0]
    assert region["region_id"] == "c4"
    assert region["bbox"] == {"x": 10, "y": 20, "w": 300, "h": 120}
    assert region["click_point"] == {"x": 100, "y": 80}
    assert region["execute_binding_enabled"] is False
    assert region["artifact_is_authorization"] is False
    action = patch["action_template_additions"][0]
    assert action["semantic_action"] == "open_detail"
    assert action["target_entity"] == "c4"
    assert action["execute_binding_enabled"] is False
    assert action["artifact_is_authorization"] is False
    transition = patch["transition_additions"][0]
    assert transition["transition_type"] == "open_detail"
    assert transition["execute_binding_enabled"] is False
    assert transition["artifact_is_authorization"] is False
    assert proposal["execute_binding_enabled"] is False
    assert proposal["artifact_is_authorization"] is False
