from __future__ import annotations

import json
from pathlib import Path

from scripts.build_learn_fusion_pathgraph_review_queue import build_pathgraph_review_queue


def test_build_pathgraph_review_queue_splits_candidates_and_blockers(tmp_path: Path) -> None:
    status_path = tmp_path / "fusion_status.json"
    diagnosis_path = tmp_path / "gate_diagnosis.json"
    status_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_precise_understanding_fusion_status_report_v1",
                "summary": {"attempted": 4, "real_clicks": 0},
                "items": [
                    {
                        "region_no": 4,
                        "source_item_id": "c4",
                        "label": "Job listing card: Software Engineer",
                        "role": "card",
                        "calibration_status": "needs_human_review",
                        "point_quality": "vista_point_inside_seed_bbox",
                        "gate_safety": "passed_allowed_dry_run",
                        "trace_path": "trace-card.json",
                        "overlay_path": "overlay-card.png",
                        "rough_bbox_hint": {"x": 10, "y": 20, "w": 300, "h": 120},
                        "selected_click_point": {"x": 100, "y": 80},
                        "vista_point": {"x": 90, "y": 70},
                        "real_clicks": 0,
                        "targeted_rerun_correction": {
                            "contract_version": "learn_fusion_item_targeted_rerun_correction_v1",
                            "previous_calibration_status": "gate_rejected",
                            "execute_binding_enabled": False,
                            "artifact_is_authorization": False,
                        },
                    },
                    {
                        "region_no": 8,
                        "source_item_id": "c9",
                        "label": "Filter toggle",
                        "role": "toggle",
                        "calibration_status": "needs_human_review",
                        "point_quality": "vista_point_outside_seed_bbox",
                        "gate_safety": "passed_allowed_dry_run",
                        "real_clicks": 0,
                    },
                    {
                        "region_no": 7,
                        "source_item_id": "c8",
                        "label": "Job details placeholder",
                        "role": "other",
                        "calibration_status": "gate_rejected",
                        "point_quality": "vista_point_inside_seed_bbox",
                        "gate_safety": "passed_rejected",
                        "real_clicks": 0,
                    },
                    {
                        "region_no": 3,
                        "source_item_id": "c3",
                        "label": "Search button",
                        "role": "button",
                        "calibration_status": "needs_human_review",
                        "point_quality": "vista_point_inside_seed_bbox",
                        "gate_safety": "passed_allowed_dry_run",
                        "real_clicks": 0,
                    },
                ],
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    diagnosis_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_fusion_gate_rejection_diagnosis_report_v1",
                "cases": [
                    {
                        "region_no": 7,
                        "source_item_id": "c8",
                        "classification": "non_actionable_region_correctly_rejected",
                        "proposed_fix": "keep_blocked_or_mark_as_page_structure_not_action",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_pathgraph_review_queue(
        fusion_status_path=status_path,
        gate_diagnosis_path=diagnosis_path,
        out_dir=tmp_path / "out",
    )

    report = json.loads(Path(result["queue_path"]).read_text(encoding="utf-8"))
    assert report["contract_version"] == "learn_fusion_pathgraph_review_queue_v1"
    assert report["summary"]["open_detail_candidate_review"] == 1
    assert report["summary"]["same_screen_action_review"] == 1
    assert report["summary"]["geometry_review_required"] == 1
    assert report["summary"]["blocked_non_action"] == 1
    assert report["summary"]["real_clicks"] == 0
    by_region = {item["region_no"]: item for item in report["queue_items"]}
    assert by_region[4]["review_bucket"] == "open_detail_candidate_review"
    assert by_region[4]["candidate_semantic_action"] == "open_detail"
    assert by_region[4]["rough_bbox_hint"] == {"x": 10, "y": 20, "w": 300, "h": 120}
    assert by_region[4]["selected_click_point"] == {"x": 100, "y": 80}
    assert by_region[4]["required_next_evidence"] == [
        "human_review_open_detail_candidate",
        "post_action_detail_observe_after_approved_no_dispatch",
    ]
    assert by_region[8]["review_bucket"] == "geometry_review_required"
    assert by_region[7]["review_bucket"] == "blocked_non_action"
    assert by_region[3]["review_bucket"] == "same_screen_action_review"
    assert report["execute_binding_enabled"] is False
    assert report["artifact_is_authorization"] is False
    assert report["display_only"] is True
