from __future__ import annotations

import json
from pathlib import Path

from scripts.build_numbered_region_calibration_batch_plan import build_numbered_region_calibration_batch_plan


def test_build_numbered_region_calibration_batch_plan_splits_ready_and_review_items(tmp_path: Path) -> None:
    report_path = tmp_path / "numbered_region_calibration_report.json"
    tasks_path = tmp_path / "generated_numbered_region_tasks.json"
    report_path.write_text(
        json.dumps(
            {
                "contract_version": "numbered_region_calibration_probe_v1",
                "generated_tasks_path": str(tasks_path),
                "calibration_backlog": {
                    "contract_version": "numbered_region_calibration_backlog_v1",
                    "summary": {
                        "uncalibrated_locator_cards": 3,
                        "ready_for_execute_dry_run": 2,
                        "review_before_calibration": 1,
                        "display_only": True,
                        "execute_binding_enabled": False,
                    },
                    "items": [
                        {
                            "region_no": 1,
                            "label": "Search keyword field",
                            "suggested_semantic_action": "fill_field",
                            "calibration_lane": "ready_for_execute_dry_run",
                            "ready_for_execute_dry_run": True,
                        },
                        {
                            "region_no": 3,
                            "label": "Search button",
                            "suggested_semantic_action": "click_target",
                            "calibration_lane": "ready_for_execute_dry_run",
                            "ready_for_execute_dry_run": True,
                        },
                        {
                            "region_no": 7,
                            "label": "Job details placeholder",
                            "suggested_semantic_action": "click_target",
                            "calibration_lane": "review_before_calibration",
                            "ready_for_execute_dry_run": False,
                            "review_reason": "non_actionable_or_page_structure_role",
                        },
                    ],
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_numbered_region_calibration_batch_plan(report_path=report_path, out_dir=tmp_path / "out")

    plan = json.loads(Path(result["plan_path"]).read_text(encoding="utf-8"))
    assert plan["contract_version"] == "numbered_region_calibration_batch_plan_v1"
    assert plan["summary"] == {
        "ready_for_execute_dry_run": 2,
        "review_before_calibration": 1,
        "real_clicks": 0,
        "display_only": True,
        "execute_binding_enabled": False,
    }
    assert plan["ready_region_numbers"] == [1, 3]
    assert plan["review_blocked_region_numbers"] == [7]
    assert plan["run_command_args"] == [
        "uv",
        "run",
        "python",
        "scripts\\run_numbered_region_calibration_probe.py",
        "--tasks",
        str(tasks_path),
        "--out",
        str((tmp_path / "out" / "next_numbered_region_calibration").resolve()),
        "--regions",
        "1,3",
    ]
    assert "--start-model" not in plan["run_command_args"]
    assert plan["command_executes_now"] is False
    assert plan["ready_items"][0]["region_no"] == 1
    assert plan["review_blocked_items"][0]["review_reason"] == "non_actionable_or_page_structure_role"
    assert plan["execute_binding_enabled"] is False
    assert plan["artifact_is_authorization"] is False
    assert result["summary"]["ready_for_execute_dry_run"] == 2


def test_build_numbered_region_calibration_batch_plan_accepts_preview_source_tasks_path(tmp_path: Path) -> None:
    report_path = tmp_path / "preview_report.json"
    tasks_path = tmp_path / "source_tasks.json"
    report_path.write_text(
        json.dumps(
            {
                "contract_version": "learn_full_screen_understanding_backlog_triage_preview_v1",
                "source_tasks_path": str(tasks_path),
                "calibration_backlog": {
                    "items": [
                        {
                            "region_no": 6,
                            "label": "Save search",
                            "ready_for_execute_dry_run": True,
                            "calibration_lane": "ready_for_execute_dry_run",
                        }
                    ]
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_numbered_region_calibration_batch_plan(report_path=report_path, out_dir=tmp_path / "out")

    plan = json.loads(Path(result["plan_path"]).read_text(encoding="utf-8"))
    assert plan["ready_region_numbers"] == [6]
    assert plan["run_command_args"][4:6] == ["--tasks", str(tasks_path)]


def test_build_numbered_region_calibration_batch_plan_can_preview_post_batch_refresh_command(tmp_path: Path) -> None:
    report_path = tmp_path / "numbered_region_calibration_report.json"
    tasks_path = tmp_path / "generated_numbered_region_tasks.json"
    trial_path = tmp_path / "actual_parser_output_with_fusion_status.json"
    base_status_path = tmp_path / "learn_precise_understanding_fusion_status_report.json"
    report_path.write_text(
        json.dumps(
            {
                "contract_version": "numbered_region_calibration_probe_v1",
                "generated_tasks_path": str(tasks_path),
                "calibration_backlog": {
                    "items": [
                        {"region_no": 1, "label": "Search", "ready_for_execute_dry_run": True},
                        {"region_no": 7, "label": "Placeholder", "ready_for_execute_dry_run": False},
                    ]
                },
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_numbered_region_calibration_batch_plan(
        report_path=report_path,
        out_dir=tmp_path / "out",
        trial_path=trial_path,
        base_status_path=base_status_path,
    )

    plan = json.loads(Path(result["plan_path"]).read_text(encoding="utf-8"))
    assert plan["post_batch_refresh_command_args"] == [
        "uv",
        "run",
        "python",
        "scripts\\refresh_learn_fusion_after_calibration_batch.py",
        "--trial",
        str(trial_path),
        "--base-status",
        str(base_status_path),
        "--rerun-report",
        str((tmp_path / "out" / "next_numbered_region_calibration" / "numbered_region_calibration_report.json").resolve()),
        "--batch-plan",
        str((tmp_path / "out" / "numbered_region_calibration_batch_plan.json").resolve()),
        "--out",
        str((tmp_path / "out" / "post_batch_refresh").resolve()),
    ]
    assert "refresh_learn_fusion_after_calibration_batch.py" in plan["post_batch_refresh_command_preview"]
    assert plan["post_batch_refresh_command_executes_now"] is False
    assert plan["post_batch_refresh_requires_completed_batch"] is True
    assert plan["execute_binding_enabled"] is False
    assert plan["artifact_is_authorization"] is False
