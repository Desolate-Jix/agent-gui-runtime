import json
from pathlib import Path

from scripts.report_learn_fusion_demo_readiness import report_learn_fusion_demo_readiness


def test_demo_readiness_prefers_preflight_candidate_over_raw_pinned_source(tmp_path: Path) -> None:
    raw_source = tmp_path / "logs" / "benchmarks" / "current" / "actual_parser_output_with_fusion_status.json"
    reviewed_source = tmp_path / "artifacts" / "learning-draft-review" / "current" / "reviewed_template_candidate.json"
    candidate_source = reviewed_source.parent / "pathgraph_candidate" / "pathgraph_candidate.json"
    validation_source = candidate_source.parent / "promotion_validation_report.json"
    preflight_source = candidate_source.parent / "learn_fusion_model_start_preflight_report.json"

    _write_trial(raw_source)
    _write_reviewed(reviewed_source)
    validation_source.parent.mkdir(parents=True, exist_ok=True)
    validation_source.write_text(
        json.dumps(
            {
                "contract_version": "pathgraph_candidate_validation_report_v1",
                "validation_status": "blocked_pending_calibration",
                "summary": {"ready_for_runtime_pathgraph_promotion": False},
                "safety": {"execute_binding_enabled": False, "artifact_is_authorization": False},
                "model_start_runbook": {"runbook_status": "awaiting_explicit_model_start_approval"},
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
                "reviewed_template_candidate_path": "artifacts/learning-draft-review/current/reviewed_template_candidate.json",
                "validation_report_path": "artifacts/learning-draft-review/current/pathgraph_candidate/promotion_validation_report.json",
                "validation_status": "blocked_pending_calibration",
                "model_start_runbook": {"runbook_status": "awaiting_explicit_model_start_approval"},
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
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

    report = report_learn_fusion_demo_readiness(
        raw_recommended_source_path=raw_source,
        preflight_candidate_path=candidate_source,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["demo_readiness_status"] == "ready_for_preflight_demo"
    assert report["recommended_load_path"] == "artifacts/learning-draft-review/current/pathgraph_candidate/pathgraph_candidate.json"
    assert report["raw_recommended_source_path"] == "logs/benchmarks/current/actual_parser_output_with_fusion_status.json"
    assert report["candidate_validation_status"] == "blocked_pending_calibration"
    assert report["preflight_status"] == "ready_for_explicit_model_start"
    assert report["may_run_calibration_batch_now"] is False
    assert report["safety"]["execute_binding_enabled"] is False
    assert report["safety"]["artifact_is_authorization"] is False
    assert report["blockers"] == []
    assert Path(report["report_path"]).exists()


def _write_trial(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": "learning_model_trial_v1",
                "best_learning_draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "SEEK results",
                    "state_guess": "seek_results",
                    "workflow_draft": {"states": [{"state_id": "results"}], "action_templates": []},
                    "interface_draft": {"regions": []},
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_reviewed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": "reviewed_template_candidate_v1",
                "draft": {
                    "contract_version": "learning_template_draft_v1",
                    "screen_summary": "SEEK results",
                    "state_guess": "seek_results",
                    "workflow_draft": {"states": [{"state_id": "results"}], "action_templates": []},
                    "interface_draft": {"regions": []},
                },
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
