import json
from pathlib import Path

from scripts.report_learn_fusion_model_start_preflight import report_learn_fusion_model_start_preflight


def test_model_start_preflight_accepts_blocked_pending_calibration_candidate(tmp_path: Path) -> None:
    runbook = _write_json(
        tmp_path / "runbook.json",
        {
            "contract_version": "learn_fusion_model_start_runbook_v1",
            "runbook_status": "awaiting_explicit_model_start_approval",
            "approval_required": True,
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "next_manual_action": "ask_user_to_approve_model_start_for_ready_regions",
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
    candidate = _write_json(
        tmp_path / "pathgraph_candidate.json",
        {
            "contract_version": "pathgraph_candidate_wrapper_v1",
            "validation_report": {
                "validation_status": "blocked_pending_calibration",
                "readiness_status": "blocked_from_promotion_review",
                "ready_for_runtime_pathgraph_promotion": False,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                "model_start_runbook": {
                    "runbook_status": "awaiting_explicit_model_start_approval",
                    "ready_region_numbers": [1, 2, 3],
                    "review_blocked_region_numbers": [7],
                },
            },
            "model_start_runbook": {
                "runbook_status": "awaiting_explicit_model_start_approval",
                "ready_region_numbers": [1, 2, 3],
                "review_blocked_region_numbers": [7],
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    report = report_learn_fusion_model_start_preflight(
        runbook_path=runbook,
        pathgraph_candidate_path=candidate,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["preflight_status"] == "ready_for_explicit_model_start"
    assert report["may_start_model_after_user_approval"] is True
    assert report["may_run_calibration_batch_now"] is False
    assert report["candidate_validation_status"] == "blocked_pending_calibration"
    assert report["ready_region_numbers"] == [1, 2, 3]
    assert report["review_blocked_region_numbers"] == [7]
    assert report["blockers"] == []
    assert report["safety"]["execute_binding_enabled"] is False
    assert report["safety"]["artifact_is_authorization"] is False
    assert report["safety"]["live_clicks"] == 0
    assert Path(report["report_path"]).exists()


def test_model_start_preflight_blocks_executable_or_mismatched_candidate(tmp_path: Path) -> None:
    runbook = _write_json(
        tmp_path / "runbook.json",
        {
            "runbook_status": "awaiting_explicit_model_start_approval",
            "approval_required": True,
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "commands": {"command_executes_now": False, "post_batch_refresh_command_executes_now": False},
            "expected_outputs": {"rerun_report_status": "awaiting_future_calibration_output"},
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    candidate = _write_json(
        tmp_path / "pathgraph_candidate.json",
        {
            "validation_report": {
                "validation_status": "passed_candidate",
                "ready_for_runtime_pathgraph_promotion": True,
                "execute_binding_enabled": True,
                "artifact_is_authorization": True,
                "model_start_runbook": {"ready_region_numbers": [1, 3]},
            },
            "execute_binding_enabled": True,
            "artifact_is_authorization": True,
        },
    )

    report = report_learn_fusion_model_start_preflight(
        runbook_path=runbook,
        pathgraph_candidate_path=candidate,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["preflight_status"] == "blocked"
    assert report["may_start_model_after_user_approval"] is False
    assert "candidate_not_blocked_pending_calibration" in report["blockers"]
    assert "candidate_execute_binding_enabled" in report["blockers"]
    assert "candidate_artifact_is_authorization" in report["blockers"]
    assert "candidate_ready_regions_mismatch" in report["blockers"]


def test_model_start_preflight_reads_sibling_validation_report_path(tmp_path: Path) -> None:
    runbook = _write_json(
        tmp_path / "runbook.json",
        {
            "runbook_status": "awaiting_explicit_model_start_approval",
            "approval_required": True,
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "commands": {"command_executes_now": False, "post_batch_refresh_command_executes_now": False},
            "expected_outputs": {"rerun_report_status": "awaiting_future_calibration_output"},
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    validation = _write_json(
        tmp_path / "candidate" / "promotion_validation_report.json",
        {
            "validation_status": "blocked_pending_calibration",
            "summary": {"ready_for_runtime_pathgraph_promotion": False},
            "safety": {"execute_binding_enabled": False, "artifact_is_authorization": False},
            "model_start_runbook": {
                "runbook_status": "awaiting_explicit_model_start_approval",
                "ready_region_numbers": [1, 2, 3],
                "review_blocked_region_numbers": [7],
            },
        },
    )
    candidate = _write_json(
        tmp_path / "candidate" / "pathgraph_candidate.json",
        {
            "validation_report_path": str(validation),
            "validation_status": "blocked_pending_calibration",
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "model_start_runbook": {
                "runbook_status": "awaiting_explicit_model_start_approval",
                "ready_region_numbers": [1, 2, 3],
                "review_blocked_region_numbers": [7],
            },
        },
    )

    report = report_learn_fusion_model_start_preflight(
        runbook_path=runbook,
        pathgraph_candidate_path=candidate,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["preflight_status"] == "ready_for_explicit_model_start"
    assert report["candidate_validation_status"] == "blocked_pending_calibration"
    assert report["blockers"] == []


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
