from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_fusion_pathgraph_candidate_status import build_fusion_pathgraph_candidate_status


def test_build_fusion_pathgraph_candidate_status_summarizes_remaining_blocker(tmp_path: Path) -> None:
    candidate = tmp_path / "pathgraph_candidate.json"
    attach = tmp_path / "detail_observe_attach_result.json"
    replay = tmp_path / "pathgraph_promotion_gate_replay_report.json"
    candidate.write_text(
        json.dumps(
            {
                "contract_version": "pathgraph_candidate_v1",
                "validation_status": "passed_candidate",
                "validation_summary": {"state_count": 2, "region_count": 2, "action_template_count": 2},
                "pending_detail_observe_requests": [{"request_id": "detail_observe:a1", "status": "attached"}],
                "detail_surface_attachments": [{"attachment_id": "detail_surface:a1"}],
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    attach.write_text(
        json.dumps(
            {
                "contract_version": "pathgraph_candidate_detail_observe_attach_result_v1",
                "attachment_status": "attached",
                "attached_request_count": 1,
                "detail_surface_attachment_count": 1,
                "attached_detail_region_count": 2,
                "attached_detail_action_count": 1,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    replay.write_text(
        json.dumps(
            {
                "contract_version": "pathgraph_promotion_gate_replay_report_v1",
                "summary": {"candidate_count": 1, "blocked_from_promotion_review_count": 1},
                "cases": [
                    {
                        "candidate_path": "pathgraph_candidate.json",
                        "readiness_status": "needs_promotion_review",
                        "gate_status": "blocked_from_promotion_review",
                        "failed_check_ids": ["current_screen_freshness"],
                    }
                ],
                "safety": {"execute_binding_enabled": False, "artifact_is_authorization": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_fusion_pathgraph_candidate_status(
        candidate_path=candidate,
        detail_attach_report_path=attach,
        promotion_replay_report_path=replay,
        out_dir=tmp_path / "out",
    )

    report = json.loads(Path(result["status_report_path"]).read_text(encoding="utf-8"))
    assert report["contract_version"] == "learn_fusion_pathgraph_candidate_status_report_v1"
    assert report["summary"]["candidate_validation_status"] == "passed_candidate"
    assert report["summary"]["detail_attachment_status"] == "attached"
    assert report["summary"]["promotion_gate_status"] == "blocked_from_promotion_review"
    assert report["summary"]["remaining_failed_checks"] == ["current_screen_freshness"]
    assert report["next_required_steps"] == ["bind_current_screen_freshness_or_capture_same_screenshot_support"]
    assert report["execute_binding_enabled"] is False
    assert report["artifact_is_authorization"] is False
