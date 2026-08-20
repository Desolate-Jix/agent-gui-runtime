from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_fusion_calibration_handoff import report_learn_fusion_calibration_handoff


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_handoff_preflight_is_ready_when_only_future_rerun_report_is_missing(tmp_path: Path) -> None:
    trial = _write_json(
        tmp_path / "draft.json",
        {
            "learning_draft": {
                "page_details": {
                    "pipeline_audit": {
                        "precise_understanding_fusion_status": {
                            "precise_understanding_readiness_summary": {
                                "readiness_status": "needs_pending_calibration",
                                "total_locator_cards": 10,
                                "calibrated_cases": 2,
                                "calibration_coverage_rate": 0.2,
                                "pending_calibration_ready_count": 2,
                                "pending_calibration_review_count": 1,
                                "pathgraph_status": "blocked_from_pathgraph_candidate_review",
                            },
                            "execute_binding_enabled": False,
                            "artifact_is_authorization": False,
                        }
                    }
                }
            }
        },
    )
    base = _write_json(
        tmp_path / "base.json",
        {
            "refresh_base_status": {"contract_version": "learn_fusion_refresh_base_status_v1"},
            "precise_understanding_readiness_summary": {
                "total_locator_cards": 10,
                "calibration_coverage_rate": 0.2,
            },
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    rerun = tmp_path / "future" / "numbered_region_calibration_report.json"
    batch = _write_json(
        tmp_path / "batch.json",
        {
            "ready_region_numbers": [1, 2],
            "review_blocked_region_numbers": [7],
            "run_command_preview": "uv run python scripts\\run_numbered_region_calibration_probe.py --regions 1,2",
            "command_executes_now": False,
            "post_batch_refresh_command_args": [
                "uv",
                "run",
                "python",
                "scripts\\refresh_learn_fusion_after_calibration_batch.py",
                "--trial",
                str(trial),
                "--base-status",
                str(base),
                "--rerun-report",
                str(rerun),
                "--out",
                str(tmp_path / "refresh"),
            ],
            "post_batch_refresh_command_preview": "refresh preview",
            "post_batch_refresh_command_executes_now": False,
            "start_model_flag_included": False,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = report_learn_fusion_calibration_handoff(
        trial_path=trial,
        batch_plan_path=batch,
        refresh_base_status_path=base,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert result["handoff_status"] == "ready_for_explicit_model_start"
    assert result["future_outputs"]["rerun_report_status"] == "awaiting_future_calibration_output"
    assert result["safe_to_start_after_user_approval"] is True
    assert result["ready_region_numbers"] == [1, 2]
    assert result["review_blocked_region_numbers"] == [7]
    assert result["safety"]["execute_binding_enabled"] is False
    assert result["safety"]["artifact_is_authorization"] is False


def test_handoff_preflight_blocks_executable_or_authorizing_batch_plan(tmp_path: Path) -> None:
    trial = _write_json(
        tmp_path / "draft.json",
        {
            "learning_draft": {
                "page_details": {
                    "pipeline_audit": {
                        "precise_understanding_fusion_status": {
                            "precise_understanding_readiness_summary": {"readiness_status": "needs_pending_calibration"}
                        }
                    }
                }
            }
        },
    )
    base = _write_json(tmp_path / "base.json", {"refresh_base_status": {"contract_version": "learn_fusion_refresh_base_status_v1"}})
    batch = _write_json(
        tmp_path / "batch.json",
        {
            "ready_region_numbers": [1],
            "command_executes_now": True,
            "post_batch_refresh_command_args": [],
            "post_batch_refresh_command_executes_now": True,
            "start_model_flag_included": True,
            "execute_binding_enabled": True,
            "artifact_is_authorization": True,
        },
    )

    result = report_learn_fusion_calibration_handoff(
        trial_path=trial,
        batch_plan_path=batch,
        refresh_base_status_path=base,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert result["handoff_status"] == "blocked"
    assert result["safe_to_start_after_user_approval"] is False
    assert "batch_command_executes_now_true" in result["blockers"]
    assert "batch_execute_binding_enabled_true" in result["blockers"]
    assert "batch_artifact_is_authorization_true" in result["blockers"]
    assert "post_batch_refresh_command_missing" in result["blockers"]
