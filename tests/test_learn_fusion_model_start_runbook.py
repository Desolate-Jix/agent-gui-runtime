from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_fusion_model_start_runbook import report_learn_fusion_model_start_runbook


def test_model_start_runbook_waits_for_explicit_approval_with_gated_refresh(tmp_path: Path) -> None:
    plan = _write_json(
        tmp_path / "plan.json",
        {
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "run_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2,3",
            "command_executes_now": False,
            "post_batch_refresh_command_preview": "uv run python scripts\\refresh_learn_fusion_after_calibration_batch.py --batch-plan plan.json",
            "post_batch_refresh_command_args": [
                "uv",
                "run",
                "python",
                "scripts\\refresh_learn_fusion_after_calibration_batch.py",
                "--batch-plan",
                str(tmp_path / "plan.json"),
            ],
            "post_batch_refresh_command_executes_now": False,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    handoff = _write_json(
        tmp_path / "handoff.json",
        {
            "handoff_status": "ready_for_explicit_model_start",
            "safe_to_start_after_user_approval": True,
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "commands": {
                "calibration_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2,3",
                "post_batch_refresh_command_preview": "uv run python scripts\\refresh_learn_fusion_after_calibration_batch.py --batch-plan plan.json",
                "post_batch_refresh_command_args": [
                    "uv",
                    "run",
                    "python",
                    "scripts\\refresh_learn_fusion_after_calibration_batch.py",
                    "--batch-plan",
                    str(plan),
                ],
                "command_executes_now": False,
                "post_batch_refresh_command_executes_now": False,
                "start_model_flag_included": False,
            },
            "future_outputs": {
                "rerun_report_path": str(tmp_path / "future" / "numbered_region_calibration_report.json"),
                "rerun_report_status": "awaiting_future_calibration_output",
            },
            "safety": {"real_clicks": 0, "execute_binding_enabled": False, "artifact_is_authorization": False},
            "blockers": [],
        },
    )
    acceptance = _write_json(
        tmp_path / "acceptance.json",
        {
            "acceptance_status": "awaiting_future_calibration_output",
            "ready_for_post_batch_refresh": False,
            "coverage": {
                "expected_ready_region_numbers": [1, 2, 3],
                "missing_ready_region_numbers": [1, 2, 3],
            },
            "safety": {"real_clicks": 0, "execute_binding_enabled": False, "artifact_is_authorization": False},
            "blockers": ["rerun_report_missing"],
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    consistency = _write_json(
        tmp_path / "consistency.json",
        {
            "consistency_status": "ready_for_explicit_model_start",
            "summary": {
                "post_batch_refresh_has_batch_plan": True,
                "refresh_blocks_before_future_rerun": True,
            },
            "safety": {
                "model_started": False,
                "live_clicks": 0,
                "live_fills": 0,
                "live_submits": 0,
            },
            "blockers": [],
        },
    )

    result = report_learn_fusion_model_start_runbook(
        batch_plan_path=plan,
        handoff_report_path=handoff,
        acceptance_report_path=acceptance,
        consistency_report_path=consistency,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert result["runbook_status"] == "awaiting_explicit_model_start_approval"
    assert result["approval_required"] is True
    assert result["may_start_model_after_user_approval"] is True
    assert result["may_run_calibration_batch_now"] is False
    assert result["ready_region_numbers"] == [1, 2, 3]
    assert result["review_blocked_region_numbers"] == [7]
    assert result["expected_outputs"]["rerun_report_status"] == "awaiting_future_calibration_output"
    assert result["guards"]["post_batch_refresh_has_batch_plan"] is True
    assert result["guards"]["prebatch_refresh_blocks_before_future_rerun"] is True
    assert result["safety"]["model_started"] is False
    assert result["safety"]["live_clicks"] == 0
    assert result["execute_binding_enabled"] is False
    assert result["artifact_is_authorization"] is False
    assert result["next_manual_action"] == "ask_user_to_approve_model_start_for_ready_regions"


def test_model_start_runbook_blocks_ungated_or_inconsistent_package(tmp_path: Path) -> None:
    plan = _write_json(
        tmp_path / "plan.json",
        {
            "ready_region_numbers": [1],
            "review_blocked_region_numbers": [],
            "run_command_preview": "calibrate",
            "command_executes_now": True,
            "post_batch_refresh_command_args": [],
            "post_batch_refresh_command_executes_now": False,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    handoff = _write_json(
        tmp_path / "handoff.json",
        {
            "handoff_status": "blocked",
            "safe_to_start_after_user_approval": False,
            "ready_region_numbers": [1],
            "commands": {"command_executes_now": True},
            "future_outputs": {"rerun_report_status": "missing"},
            "safety": {"real_clicks": 0, "execute_binding_enabled": False, "artifact_is_authorization": False},
            "blockers": ["batch_command_executes_now_true"],
        },
    )
    acceptance = _write_json(
        tmp_path / "acceptance.json",
        {
            "acceptance_status": "awaiting_future_calibration_output",
            "ready_for_post_batch_refresh": False,
            "coverage": {"expected_ready_region_numbers": [1]},
            "safety": {"real_clicks": 0, "execute_binding_enabled": False, "artifact_is_authorization": False},
            "blockers": ["rerun_report_missing"],
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    consistency = _write_json(
        tmp_path / "consistency.json",
        {
            "consistency_status": "blocked",
            "summary": {
                "post_batch_refresh_has_batch_plan": False,
                "refresh_blocks_before_future_rerun": False,
            },
            "safety": {"model_started": False, "live_clicks": 0},
            "blockers": ["plan_post_batch_refresh_missing_batch_plan_arg"],
        },
    )

    result = report_learn_fusion_model_start_runbook(
        batch_plan_path=plan,
        handoff_report_path=handoff,
        acceptance_report_path=acceptance,
        consistency_report_path=consistency,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert result["runbook_status"] == "blocked"
    assert result["may_start_model_after_user_approval"] is False
    assert result["may_run_calibration_batch_now"] is False
    assert "handoff:batch_command_executes_now_true" in result["blockers"]
    assert "consistency:plan_post_batch_refresh_missing_batch_plan_arg" in result["blockers"]
    assert "post_batch_refresh_missing_batch_plan" in result["blockers"]


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
