from __future__ import annotations

import hashlib
import json
from pathlib import Path

import scripts.report_learn_fusion_calibration_pre_run_check as pre_run_check

from scripts.report_learn_fusion_calibration_pre_run_check import report_learn_fusion_calibration_pre_run_check


def test_calibration_pre_run_check_accepts_ready_approval_packet(tmp_path: Path) -> None:
    tasks = _write_json(tmp_path / "logs" / "tasks.json", {"contract_version": "tasks_v1", "tasks": []})
    batch_plan = _write_json(tmp_path / "logs" / "batch_plan.json", {"contract_version": "batch_plan_v1"})
    rerun_report = tmp_path / "logs" / "future" / "numbered_region_calibration_report.json"
    approval = _write_json(
        tmp_path / "approval_packet.json",
        {
            "contract_version": "learn_fusion_model_start_approval_packet_v1",
            "approval_packet_status": "ready_for_user_approval",
            "requires_explicit_user_approval": True,
            "approval_does_not_execute": True,
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "candidate_validation_status": "blocked_pending_calibration",
            "ready_region_numbers": [1, 2, 3],
            "review_blocked_region_numbers": [7],
            "commands": {
                "calibration_command_preview": (
                    f"uv run python scripts\\run_numbered_region_calibration_probe.py "
                    f"--tasks {tasks} --out {tmp_path / 'logs' / 'future'} --regions 1,2,3"
                ),
                "post_batch_refresh_command_preview": (
                    f"uv run python scripts\\refresh_learn_fusion_after_calibration_batch.py "
                    f"--rerun-report {rerun_report} --batch-plan {batch_plan} --out {tmp_path / 'logs' / 'refresh'}"
                ),
                "command_executes_now": False,
                "post_batch_refresh_command_executes_now": False,
            },
            "expected_outputs": {
                "rerun_report_status": "awaiting_future_calibration_output",
                "rerun_report_path": str(rerun_report),
                "post_batch_refresh_requires_completed_batch": True,
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

    report = report_learn_fusion_calibration_pre_run_check(
        approval_packet_path=approval,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["pre_run_status"] == "ready_after_explicit_approval"
    assert report["may_run_calibration_batch_now"] is False
    assert report["requires_explicit_user_approval"] is True
    assert report["approval_packet_sha256"] == hashlib.sha256(approval.read_bytes()).hexdigest()
    assert report["checks"]["tasks_file_exists"] is True
    assert report["checks"]["regions_match_ready_regions"] is True
    assert report["checks"]["refresh_rerun_report_matches_expected"] is True
    assert report["checks"]["batch_plan_exists"] is True
    assert report["safety"]["model_started"] is False
    assert report["safety"]["live_clicks"] == 0
    assert report["blockers"] == []
    assert Path(report["report_path"]).exists()


def test_calibration_pre_run_check_records_no_model_runtime_snapshot(tmp_path: Path, monkeypatch) -> None:
    tasks = _write_json(tmp_path / "logs" / "tasks.json", {"contract_version": "tasks_v1", "tasks": []})
    batch_plan = _write_json(tmp_path / "logs" / "batch_plan.json", {"contract_version": "batch_plan_v1"})
    rerun_report = tmp_path / "logs" / "future" / "numbered_region_calibration_report.json"
    approval = _write_json(
        tmp_path / "approval_packet.json",
        {
            "contract_version": "learn_fusion_model_start_approval_packet_v1",
            "approval_packet_status": "ready_for_user_approval",
            "requires_explicit_user_approval": True,
            "approval_does_not_execute": True,
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "candidate_validation_status": "blocked_pending_calibration",
            "ready_region_numbers": [1, 2, 3],
            "commands": {
                "calibration_command_preview": (
                    f"uv run python scripts\\run_numbered_region_calibration_probe.py "
                    f"--tasks {tasks} --out {tmp_path / 'logs' / 'future'} --regions 1,2,3"
                ),
                "post_batch_refresh_command_preview": (
                    f"uv run python scripts\\refresh_learn_fusion_after_calibration_batch.py "
                    f"--rerun-report {rerun_report} --batch-plan {batch_plan}"
                ),
                "command_executes_now": False,
                "post_batch_refresh_command_executes_now": False,
            },
            "expected_outputs": {
                "rerun_report_status": "awaiting_future_calibration_output",
                "rerun_report_path": str(rerun_report),
                "post_batch_refresh_requires_completed_batch": True,
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
    monkeypatch.setattr(
        pre_run_check,
        "_model_runtime_snapshot",
        lambda: {
            "contract_version": "model_runtime_snapshot_v1",
            "checked_at": "2026-07-06T09:30:00+12:00",
            "checked_ports": [11434, 1240],
            "listening_ports": [],
            "suspected_model_processes": [],
            "model_ports_clear": True,
            "model_processes_clear": True,
        },
    )

    report = report_learn_fusion_calibration_pre_run_check(
        approval_packet_path=approval,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["model_runtime_snapshot"]["model_ports_clear"] is True
    assert report["model_runtime_snapshot"]["model_processes_clear"] is True
    assert report["model_runtime_snapshot"]["checked_at"] == "2026-07-06T09:30:00+12:00"
    assert report["checks"]["no_model_ports_listening"] is True
    assert report["checks"]["no_suspected_model_processes"] is True


def test_model_runtime_snapshot_includes_checked_at_timestamp() -> None:
    snapshot = pre_run_check._model_runtime_snapshot()

    assert snapshot["contract_version"] == "model_runtime_snapshot_v1"
    assert "T" in snapshot["checked_at"]
    assert snapshot["checked_at"].endswith("+00:00")
    assert isinstance(snapshot["checked_ports"], list)


def test_suspected_model_process_filter_rejects_graphics_service_false_positive() -> None:
    assert pre_run_check._is_suspected_model_process(
        "svchost.exe",
        r"C:\Windows\System32\svchost.exe -k GraphicsPerfSvcGroup -s GraphicsPerfSvc",
    ) is False
    assert pre_run_check._is_suspected_model_process(
        "python.exe",
        r"D:\agent-gui-runtime\scripts\model_servers\vista_openai_server.py --model-name inclusionAI/VISTA-4B",
    ) is True
    assert pre_run_check._is_suspected_model_process(
        "llama-server.exe",
        r"llama-server.exe -m models\qwen3-vl-8b.gguf --port 1240",
    ) is True


def test_calibration_pre_run_check_blocks_missing_tasks_or_region_drift(tmp_path: Path) -> None:
    approval = _write_json(
        tmp_path / "approval_packet.json",
        {
            "contract_version": "learn_fusion_model_start_approval_packet_v1",
            "approval_packet_status": "ready_for_user_approval",
            "requires_explicit_user_approval": True,
            "approval_does_not_execute": True,
            "may_start_model_after_user_approval": True,
            "may_run_calibration_batch_now": False,
            "candidate_validation_status": "blocked_pending_calibration",
            "ready_region_numbers": [1, 2, 3],
            "commands": {
                "calibration_command_preview": (
                    f"uv run python scripts\\run_numbered_region_calibration_probe.py "
                    f"--tasks {tmp_path / 'missing_tasks.json'} --out {tmp_path / 'future'} --regions 1,3"
                ),
                "post_batch_refresh_command_preview": "uv run python scripts\\refresh_learn_fusion_after_calibration_batch.py",
                "command_executes_now": False,
                "post_batch_refresh_command_executes_now": False,
            },
            "expected_outputs": {
                "rerun_report_status": "awaiting_future_calibration_output",
                "rerun_report_path": str(tmp_path / "future" / "numbered_region_calibration_report.json"),
            },
            "safety": {"model_started": False, "live_clicks": 0, "live_fills": 0, "live_submits": 0},
            "blockers": [],
        },
    )

    report = report_learn_fusion_calibration_pre_run_check(
        approval_packet_path=approval,
        out_dir=tmp_path / "out",
        project_root=tmp_path,
    )

    assert report["pre_run_status"] == "blocked"
    assert "tasks_file_missing" in report["blockers"]
    assert "regions_mismatch_ready_regions" in report["blockers"]
    assert "refresh_rerun_report_missing" in report["blockers"]
    assert "batch_plan_missing" in report["blockers"]


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
