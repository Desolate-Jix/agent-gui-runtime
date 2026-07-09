from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_fusion_model_start_approval_packet import (
    report_learn_fusion_model_start_approval_packet,
)


def test_model_start_approval_packet_collects_non_executing_ready_handoff(tmp_path: Path) -> None:
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
            "commands": {
                "calibration_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2,3",
                "post_batch_refresh_command_preview": "uv run python scripts\\refresh_learn_fusion_after_calibration_batch.py --batch-plan plan.json",
                "command_executes_now": False,
                "post_batch_refresh_command_executes_now": False,
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

    report = report_learn_fusion_model_start_approval_packet(
        runbook_path=runbook,
        preflight_report_path=preflight,
        demo_readiness_report_path=demo,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["approval_packet_status"] == "ready_for_user_approval"
    assert report["requires_explicit_user_approval"] is True
    assert report["approval_does_not_execute"] is True
    assert report["may_start_model_after_user_approval"] is True
    assert report["may_run_calibration_batch_now"] is False
    assert report["candidate_validation_status"] == "blocked_pending_calibration"
    assert report["ready_region_numbers"] == [1, 2, 3]
    assert report["review_blocked_region_numbers"] == [7]
    assert report["commands"]["command_executes_now"] is False
    assert report["commands"]["post_batch_refresh_command_executes_now"] is False
    assert report["safety"]["execute_binding_enabled"] is False
    assert report["safety"]["artifact_is_authorization"] is False
    assert report["blockers"] == []
    assert Path(report["report_path"]).exists()


def test_model_start_approval_packet_blocks_drift_or_executable_commands(tmp_path: Path) -> None:
    runbook = _write_json(
        tmp_path / "runbook.json",
        {
            "runbook_status": "awaiting_explicit_model_start_approval",
            "approval_required": True,
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "commands": {
                "calibration_command_preview": "calibrate",
                "command_executes_now": True,
                "post_batch_refresh_command_executes_now": False,
            },
            "expected_outputs": {"rerun_report_status": "awaiting_future_calibration_output"},
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    preflight = _write_json(
        tmp_path / "preflight.json",
        {
            "preflight_status": "ready_for_explicit_model_start",
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "candidate_validation_status": "blocked_pending_calibration",
            "ready_region_numbers": [1, 3],
            "review_blocked_region_numbers": [7],
            "commands": {"command_executes_now": False, "post_batch_refresh_command_executes_now": False},
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "blockers": [],
        },
    )
    demo = _write_json(
        tmp_path / "demo.json",
        {
            "demo_readiness_status": "blocked",
            "candidate_validation_status": "blocked_pending_calibration",
            "preflight_status": "blocked",
            "may_run_calibration_batch_now": False,
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "blockers": ["preflight_not_ready_for_explicit_model_start"],
        },
    )

    report = report_learn_fusion_model_start_approval_packet(
        runbook_path=runbook,
        preflight_report_path=preflight,
        demo_readiness_report_path=demo,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["approval_packet_status"] == "blocked"
    assert report["may_start_model_after_user_approval"] is False
    assert "calibration_command_executes_now" in report["blockers"]
    assert "ready_regions_mismatch" in report["blockers"]
    assert "demo:preflight_not_ready_for_explicit_model_start" in report["blockers"]


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
