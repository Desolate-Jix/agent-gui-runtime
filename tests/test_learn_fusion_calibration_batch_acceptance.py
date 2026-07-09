from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_fusion_calibration_batch_acceptance import (
    report_learn_fusion_calibration_batch_acceptance,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _plan_payload() -> dict:
    return {
        "contract_version": "learning_draft_numbered_region_calibration_batch_plan_v1",
        "ready_region_numbers": [1, 2],
        "review_blocked_region_numbers": [7],
        "command_executes_now": False,
        "post_batch_refresh_command_executes_now": False,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _rerun_payload(*, regions: list[int], real_clicks: int = 0) -> dict:
    return {
        "contract_version": "numbered_region_calibration_report_v1",
        "region_numbers": regions,
        "summary": {
            "attempted": len(regions),
            "needs_human_review": len(regions),
            "real_clicks": real_clicks,
        },
        "fused_precise_understanding": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "items": [
                {
                    "region_no": region,
                    "source_item_id": f"c{region}",
                    "calibration_status": "needs_human_review",
                    "gate_safety": "passed_allowed_dry_run",
                    "real_clicks": real_clicks if index == 0 else 0,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
                for index, region in enumerate(regions)
            ],
        },
    }


def test_calibration_batch_acceptance_passes_complete_no_dispatch_batch(tmp_path: Path) -> None:
    plan_path = tmp_path / "logs" / "plan.json"
    rerun_path = tmp_path / "logs" / "rerun" / "numbered_region_calibration_report.json"
    _write_json(plan_path, _plan_payload())
    _write_json(rerun_path, _rerun_payload(regions=[1, 2]))

    result = report_learn_fusion_calibration_batch_acceptance(
        plan_path=plan_path,
        rerun_report_path=rerun_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["acceptance_status"] == "accepted_for_post_batch_refresh"
    assert report["ready_for_post_batch_refresh"] is True
    assert report["coverage"]["expected_ready_region_numbers"] == [1, 2]
    assert report["coverage"]["accepted_region_numbers"] == [1, 2]
    assert report["coverage"]["missing_ready_region_numbers"] == []
    assert report["coverage"]["unexpected_region_numbers"] == []
    assert report["safety"]["real_clicks"] == 0
    assert report["checks"]["region_coverage_complete"] is True
    assert report["checks"]["no_real_clicks"] is True
    assert report["execute_binding_enabled"] is False
    assert report["artifact_is_authorization"] is False


def test_calibration_batch_acceptance_reports_awaiting_future_output(tmp_path: Path) -> None:
    plan_path = tmp_path / "logs" / "plan.json"
    rerun_path = tmp_path / "logs" / "missing" / "numbered_region_calibration_report.json"
    _write_json(plan_path, _plan_payload())

    result = report_learn_fusion_calibration_batch_acceptance(
        plan_path=plan_path,
        rerun_report_path=rerun_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["acceptance_status"] == "awaiting_future_calibration_output"
    assert report["ready_for_post_batch_refresh"] is False
    assert report["blockers"] == ["rerun_report_missing"]
    assert report["checks"]["rerun_report_exists"] is False


def test_calibration_batch_acceptance_rejects_region_mismatch_and_real_clicks(tmp_path: Path) -> None:
    plan_path = tmp_path / "logs" / "plan.json"
    rerun_path = tmp_path / "logs" / "rerun" / "numbered_region_calibration_report.json"
    _write_json(plan_path, _plan_payload())
    _write_json(rerun_path, _rerun_payload(regions=[1, 7, 9], real_clicks=1))

    result = report_learn_fusion_calibration_batch_acceptance(
        plan_path=plan_path,
        rerun_report_path=rerun_path,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    report = json.loads(Path(result["report_path"]).read_text(encoding="utf-8"))
    assert report["acceptance_status"] == "blocked_calibration_batch_invalid"
    assert report["ready_for_post_batch_refresh"] is False
    assert report["coverage"]["missing_ready_region_numbers"] == [2]
    assert report["coverage"]["unexpected_region_numbers"] == [9]
    assert report["coverage"]["review_blocked_region_numbers_in_rerun"] == [7]
    assert report["safety"]["real_clicks"] == 1
    assert "missing_ready_regions" in report["blockers"]
    assert "review_blocked_regions_rerun_attempted" in report["blockers"]
    assert "real_clicks_detected" in report["blockers"]
