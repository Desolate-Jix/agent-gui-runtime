from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_fusion_handoff_consistency import report_learn_fusion_handoff_consistency


def test_handoff_consistency_passes_gated_current_package(tmp_path: Path) -> None:
    draft = _write_json(
        tmp_path / "logs" / "draft.json",
        _draft_payload(post_batch_refresh_command_preview="refresh --batch-plan plan.json"),
    )
    plan = _write_json(
        tmp_path / "logs" / "plan.json",
        _plan_payload(
            draft=draft,
            base=tmp_path / "logs" / "base.json",
            rerun=tmp_path / "future" / "numbered_region_calibration_report.json",
            plan=tmp_path / "logs" / "plan.json",
        ),
    )
    handoff = _write_json(
        tmp_path / "logs" / "handoff.json",
        {
            "contract_version": "learn_fusion_calibration_handoff_report_v1",
            "handoff_status": "ready_for_explicit_model_start",
            "ready_region_numbers": [1, 2],
            "review_blocked_region_numbers": [7],
            "commands": {
                "post_batch_refresh_command_args": _refresh_args(
                    draft=draft,
                    base=tmp_path / "logs" / "base.json",
                    rerun=tmp_path / "future" / "numbered_region_calibration_report.json",
                    plan=plan,
                ),
                "post_batch_refresh_command_executes_now": False,
                "command_executes_now": False,
                "start_model_flag_included": False,
            },
            "future_outputs": {"rerun_report_status": "awaiting_future_calibration_output"},
            "safety": {"execute_binding_enabled": False, "artifact_is_authorization": False, "real_clicks": 0},
            "blockers": [],
        },
    )
    acceptance = _write_json(
        tmp_path / "logs" / "acceptance.json",
        {
            "contract_version": "learn_fusion_calibration_batch_acceptance_report_v1",
            "acceptance_status": "awaiting_future_calibration_output",
            "ready_for_post_batch_refresh": False,
            "coverage": {
                "expected_ready_region_numbers": [1, 2],
                "missing_ready_region_numbers": [1, 2],
            },
            "safety": {"real_clicks": 0, "execute_binding_enabled": False, "artifact_is_authorization": False},
            "blockers": ["rerun_report_missing"],
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )
    refresh_block = _write_json(
        tmp_path / "logs" / "refresh_block.json",
        {
            "contract_version": "learn_fusion_after_calibration_batch_refresh_result_v1",
            "refresh_status": "blocked_by_calibration_batch_acceptance",
            "acceptance_status": "awaiting_future_calibration_output",
            "acceptance_blockers": ["rerun_report_missing"],
            "merge_skipped": True,
            "attach_skipped": True,
            "readiness_skipped": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "model_started": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
    )

    result = report_learn_fusion_handoff_consistency(
        draft_path=draft,
        batch_plan_path=plan,
        handoff_report_path=handoff,
        acceptance_report_path=acceptance,
        refresh_result_path=refresh_block,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert result["consistency_status"] == "ready_for_explicit_model_start"
    assert result["blockers"] == []
    assert result["checks"]["plan_post_batch_refresh_has_batch_plan"] is True
    assert result["checks"]["draft_post_batch_refresh_has_batch_plan"] is True
    assert result["checks"]["refresh_blocks_before_future_rerun"] is True
    assert result["safety"]["model_started"] is False
    assert result["safety"]["live_clicks"] == 0


def test_handoff_consistency_blocks_legacy_refresh_command_without_batch_plan(tmp_path: Path) -> None:
    draft = _write_json(
        tmp_path / "logs" / "draft.json",
        _draft_payload(post_batch_refresh_command_preview="refresh without gate"),
    )
    plan = _write_json(
        tmp_path / "logs" / "plan.json",
        _plan_payload(
            draft=draft,
            base=tmp_path / "logs" / "base.json",
            rerun=tmp_path / "future" / "numbered_region_calibration_report.json",
            plan=None,
        ),
    )
    handoff = _write_json(
        tmp_path / "logs" / "handoff.json",
        {
            "handoff_status": "ready_for_explicit_model_start",
            "ready_region_numbers": [1, 2],
            "commands": {"post_batch_refresh_command_args": _refresh_args(draft=draft, base=tmp_path / "logs" / "base.json", rerun=tmp_path / "future" / "numbered_region_calibration_report.json", plan=None)},
            "safety": {"execute_binding_enabled": False, "artifact_is_authorization": False, "real_clicks": 0},
            "blockers": [],
        },
    )
    acceptance = _write_json(
        tmp_path / "logs" / "acceptance.json",
        {
            "acceptance_status": "awaiting_future_calibration_output",
            "ready_for_post_batch_refresh": False,
            "coverage": {"expected_ready_region_numbers": [1, 2]},
            "safety": {"real_clicks": 0, "execute_binding_enabled": False, "artifact_is_authorization": False},
            "blockers": ["rerun_report_missing"],
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    )

    result = report_learn_fusion_handoff_consistency(
        draft_path=draft,
        batch_plan_path=plan,
        handoff_report_path=handoff,
        acceptance_report_path=acceptance,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert result["consistency_status"] == "blocked"
    assert "plan_post_batch_refresh_missing_batch_plan_arg" in result["blockers"]
    assert "draft_post_batch_refresh_missing_batch_plan_arg" in result["blockers"]
    assert "handoff_post_batch_refresh_missing_batch_plan_arg" in result["blockers"]


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _refresh_args(*, draft: Path, base: Path, rerun: Path, plan: Path | None) -> list[str]:
    args = [
        "uv",
        "run",
        "python",
        "scripts\\refresh_learn_fusion_after_calibration_batch.py",
        "--trial",
        str(draft),
        "--base-status",
        str(base),
        "--rerun-report",
        str(rerun),
    ]
    if plan is not None:
        args.extend(["--batch-plan", str(plan)])
    args.extend(["--out", str(draft.parent / "refresh")])
    return args


def _plan_payload(*, draft: Path, base: Path, rerun: Path, plan: Path | None) -> dict:
    args = _refresh_args(draft=draft, base=base, rerun=rerun, plan=plan)
    return {
        "contract_version": "numbered_region_calibration_batch_plan_v1",
        "ready_region_numbers": [1, 2],
        "review_blocked_region_numbers": [7],
        "command_executes_now": False,
        "post_batch_refresh_command_args": args,
        "post_batch_refresh_command_preview": " ".join(args),
        "post_batch_refresh_command_executes_now": False,
        "start_model_flag_included": False,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _draft_payload(*, post_batch_refresh_command_preview: str) -> dict:
    return {
        "contract_version": "actual_parser_output_v1",
        "learning_draft": {
            "contract_version": "learning_template_draft_v1",
            "screen_summary": "SEEK results",
            "regions": [],
            "action_templates": [],
            "page_details": {
                "pipeline_audit": {
                    "precise_understanding_fusion_status": {
                        "precise_understanding_readiness_summary": {
                            "readiness_status": "needs_pending_calibration",
                            "total_locator_cards": 10,
                            "calibrated_cases": 2,
                            "uncalibrated_locator_cards": 8,
                            "calibration_coverage_rate": 0.2,
                            "pending_calibration_ready_count": 2,
                            "pending_calibration_review_count": 1,
                            "pathgraph_status": "blocked_from_pathgraph_candidate_review",
                        },
                        "calibration_batch_plan": {
                            "ready_region_numbers": [1, 2],
                            "review_blocked_region_numbers": [7],
                            "post_batch_refresh_command_preview": post_batch_refresh_command_preview,
                            "post_batch_refresh_command_executes_now": False,
                            "execute_binding_enabled": False,
                            "artifact_is_authorization": False,
                        },
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    }
                }
            },
        },
    }
