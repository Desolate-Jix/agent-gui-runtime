from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.report_pathgraph_promotion_gate_replay import build_promotion_gate_replay_report


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x01\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_promotion_gate_replay_reports_non_demo_candidate_gate_branches(tmp_path: Path) -> None:
    from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review

    image_path = tmp_path / "artifacts" / "screenshots" / "screen.png"
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(PNG_1X1)
    image_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()

    matched_trial = _write_trial(
        tmp_path / "artifacts" / "learning-runs" / "matched" / "trial_result.json",
        source_image_path="artifacts/screenshots/screen.png",
        source_image_sha256=image_sha256,
    )
    stale_trial = _write_trial(
        tmp_path / "artifacts" / "learning-runs" / "stale" / "trial_result.json",
        source_image_path="artifacts/screenshots/screen.png",
        source_image_sha256="0" * 64,
    )
    matched = build_pathgraph_candidate_from_review(
        "artifacts/learning-runs/matched/trial_result.json",
        _review_patch(),
        project_root=tmp_path,
    )
    stale = build_pathgraph_candidate_from_review(
        stale_trial.relative_to(tmp_path),
        _review_patch(),
        project_root=tmp_path,
    )

    report = build_promotion_gate_replay_report(
        candidate_paths=[
            tmp_path / matched["pathgraph_candidate_path"],
            tmp_path / stale["pathgraph_candidate_path"],
        ],
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["contract_version"] == "pathgraph_promotion_gate_replay_report_v1"
    assert report["summary"] == {
        "candidate_count": 2,
        "non_demo_candidate_count": 2,
        "demo_candidate_count": 0,
        "passed_for_human_promotion_review_count": 1,
        "non_demo_passed_for_human_promotion_review_count": 1,
        "demo_passed_for_human_promotion_review_count": 0,
        "blocked_from_promotion_review_count": 1,
        "non_demo_blocked_from_promotion_review_count": 1,
        "demo_blocked_from_promotion_review_count": 0,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    cases = {case["case_id"]: case for case in report["cases"]}
    assert cases["matched"]["fixture_kind"] == "non_demo_candidate"
    assert cases["matched"]["gate_status"] == "passed_for_human_promotion_review"
    assert cases["matched"]["failed_check_ids"] == []
    assert cases["matched"]["source_freshness_summary"]["checksum_status"] == "matched"
    assert cases["matched"]["reviewed_template_candidate_path"].endswith("reviewed_template_candidate.json")
    assert cases["matched"]["execute_binding_enabled"] is False
    assert cases["stale"]["fixture_kind"] == "non_demo_candidate"
    assert cases["stale"]["gate_status"] == "blocked_from_promotion_review"
    assert cases["stale"]["failed_check_ids"] == ["current_screen_freshness"]
    assert cases["stale"]["source_freshness_summary"]["checksum_status"] == "mismatch"
    assert Path(report["report_path"]).exists()


def _write_trial(
    path: Path,
    *,
    source_image_path: str,
    source_image_sha256: str,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    case_id = path.parent.name
    path.write_text(
        json.dumps(
            {
                "contract_version": "learning_model_trial_v1",
                "app_name": "demo",
                "best_attempt_index": 0,
                "best_learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": f"Promotion gate replay {case_id}",
                    "state_guess": case_id,
                    "workflow_draft": {
                        "states": [{"state_id": case_id, "label": case_id, "page_type": "search_page"}],
                        "action_templates": [
                            {
                                "action_template_id": "search_action",
                                "label": "Search",
                                "semantic_action": "fill_field",
                                "target_entity": "search_region",
                                "bbox": {"x": 10, "y": 12, "w": 80, "h": 20},
                                "click_point": {"x": 40, "y": 20},
                            }
                        ],
                        "verification_rules": [{"rule_id": "v1", "label": "Search field remains visible"}],
                    },
                    "interface_draft": {
                        "regions": [
                            {
                                "region_id": "search_region",
                                "label": "Search input",
                                "role": "text_input",
                                "bbox": {"x": 8, "y": 10, "w": 96, "h": 28},
                                "click_point": {"x": 42, "y": 22},
                            }
                        ]
                    },
                    "page_details": {
                        "screen": {
                            "source_image_path": source_image_path,
                            "source_image_sha256": source_image_sha256,
                        }
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
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _review_patch() -> dict:
    return {
        "review_status": "approved_as_assisted_template",
        "region_bbox_updates": {
            "search_region": {
                "bbox": {"x": 8, "y": 10, "w": 96, "h": 28},
                "click_point": {"x": 42, "y": 22},
            }
        },
        "action_bbox_updates": {
            "search_action": {
                "bbox": {"x": 10, "y": 12, "w": 80, "h": 20},
                "click_point": {"x": 40, "y": 20},
            }
        },
    }
