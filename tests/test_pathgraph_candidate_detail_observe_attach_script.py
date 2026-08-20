from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from scripts.attach_pathgraph_candidate_detail_observe import attach_detail_observe_to_candidate


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVR4nGP8//8/AwMDEwMYAAAkBgMBXaJOiAAAAABJRU5ErkJggg=="
)


def test_attach_detail_observe_to_candidate_attaches_all_pending_requests(tmp_path: Path) -> None:
    from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review

    screenshot = tmp_path / "artifacts" / "screenshots" / "seek_results.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    screenshot.write_bytes(PNG_1X1)
    screenshot_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    results_trial = tmp_path / "artifacts" / "learning-runs" / "seek-results" / "trial_result.json"
    detail_trial = tmp_path / "artifacts" / "learning-runs" / "seek-detail" / "trial_result.json"
    _write_results_trial(results_trial, screenshot_sha256=screenshot_sha256)
    _write_detail_trial(detail_trial)

    build = build_pathgraph_candidate_from_review(
        results_trial.relative_to(tmp_path),
        {"review_status": "approved_as_assisted_template"},
        project_root=tmp_path,
    )

    result = attach_detail_observe_to_candidate(
        candidate_path=tmp_path / build["pathgraph_candidate_path"],
        detail_source_path=detail_trial,
        out_dir=tmp_path / "logs" / "detail_attach",
        project_root=tmp_path,
    )

    assert result["contract_version"] == "pathgraph_candidate_detail_observe_attach_result_v1"
    assert result["attachment_status"] == "attached"
    assert result["attached_request_count"] == 2
    assert result["pending_request_count"] == 2
    assert result["readiness_status"] == "needs_promotion_review"
    assert result["promotion_review_blockers"] == ["review_only_not_promoted"]
    assert result["promotion_gate_status"] == "passed_for_human_promotion_review"
    assert result["promotion_gate_failed_check_ids"] == []
    assert result["detail_surface_attachment_count"] == 2
    assert result["attached_detail_region_count"] == 2
    assert result["attached_detail_action_count"] == 1
    assert result["execute_binding_enabled"] is False
    assert result["artifact_is_authorization"] is False
    wrapper = json.loads((tmp_path / result["pathgraph_candidate_path"]).read_text(encoding="utf-8"))
    assert [item["status"] for item in wrapper["pending_detail_observe_requests"]] == ["attached", "attached"]
    assert len(wrapper["detail_surface_attachments"]) == 2
    assert Path(result["report_path"]).exists()


def _write_results_trial(path: Path, *, screenshot_sha256: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": "learning_model_trial_v1",
                "app_name": "seek",
                "best_attempt_index": 0,
                "best_learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "SEEK results with two open-detail cards.",
                    "state_guess": "seek_results",
                    "workflow_draft": {
                        "states": [{"state_id": "seek_results", "label": "SEEK results"}],
                        "action_templates": [
                            _open_detail_action("open_card_1", "job_card_1", 100),
                            _open_detail_action("open_card_2", "job_card_2", 220),
                        ],
                        "verification_rules": [{"rule_id": "v1", "label": "Re-observe selected detail pane"}],
                    },
                    "interface_draft": {
                        "regions": [
                            {"region_id": "job_card_1", "label": "Job card 1", "role": "card", "bbox": {"x": 20, "y": 100, "w": 240, "h": 90}},
                            {"region_id": "job_card_2", "label": "Job card 2", "role": "card", "bbox": {"x": 20, "y": 220, "w": 240, "h": 90}},
                        ]
                    },
                    "page_details": {
                        "screen": {
                            "source_image_path": "artifacts/screenshots/seek_results.png",
                            "source_image_sha256": screenshot_sha256,
                        }
                    },
                    "blockers": [{"blocker_id": "final_submit_forbidden", "label": "Final submit forbidden"}],
                    "safety": {"artifact_is_authorization": False, "execute_binding_enabled": False, "final_submit_forbidden": True},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _open_detail_action(action_id: str, region_id: str, y: int) -> dict:
    return {
        "action_template_id": action_id,
        "label": f"Open {region_id}",
        "semantic_action": "open_detail",
        "action_kind": "open_detail",
        "target_entity": region_id,
        "target_region_id": region_id,
        "bbox": {"x": 20, "y": y, "w": 240, "h": 90},
        "click_point": {"x": 100, "y": y + 30},
        "transition_hint": {
            "contract_version": "learn_open_detail_transition_hint_v1",
            "transition_type": "open_detail",
            "source_region_id": region_id,
            "expected_next_state_role": "detail_view",
            "target_surface": "detail_pane_or_detail_page",
            "requires_post_action_observe": True,
            "candidate_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _write_detail_trial(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": "learning_model_trial_v1",
                "app_name": "seek",
                "best_attempt_index": 0,
                "best_learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "Selected SEEK detail pane.",
                    "state_guess": "seek_job_detail",
                    "workflow_draft": {
                        "states": [{"state_id": "detail_state", "label": "Detail pane"}],
                        "action_templates": [
                            {
                                "action_template_id": "apply_entry",
                                "label": "Apply",
                                "semantic_action": "open_apply_flow",
                                "target_entity": "apply_button",
                                "bbox": {"x": 500, "y": 140, "w": 90, "h": 34},
                                "click_point": {"x": 545, "y": 157},
                                "artifact_is_authorization": False,
                                "execute_binding_enabled": False,
                            }
                        ],
                        "verification_rules": [{"rule_id": "detail_title_visible", "label": "Detail title visible"}],
                    },
                    "interface_draft": {
                        "regions": [
                            {"region_id": "detail_header", "label": "Detail header", "role": "detail_header", "bbox": {"x": 420, "y": 80, "w": 360, "h": 120}},
                            {"region_id": "apply_button", "label": "Apply", "role": "button", "bbox": {"x": 500, "y": 140, "w": 90, "h": 34}, "click_point": {"x": 545, "y": 157}},
                        ]
                    },
                    "blockers": [{"blocker_id": "final_submit_forbidden", "label": "Final submit forbidden"}],
                    "safety": {"artifact_is_authorization": False, "execute_binding_enabled": False, "final_submit_forbidden": True},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
