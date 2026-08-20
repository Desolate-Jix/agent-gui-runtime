from __future__ import annotations

import json
from pathlib import Path

from scripts.seek_application_flow_replay_report import build_seek_application_flow_replay_report, main


def _read_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def test_application_flow_replay_report_builds_strict_live_replay_plan() -> None:
    artifact = _read_json("artifacts/seek/learned_seek_application_flow_plexure_20260620.json")

    report = build_seek_application_flow_replay_report(artifact)

    assert report["contract_version"] == "seek_application_flow_replay_report_v1"
    assert report["status"] == "pass"
    assert report["summary"]["can_run_live_strict_replay"] is True
    assert report["summary"]["employer_question_count"] == 0
    assert report["summary"]["safe_fill_required"] is True
    assert report["summary"]["field_focus_required"] is True
    assert report["summary"]["post_fill_value_verification_required"] is True
    assert report["summary"]["final_submit_forbidden"] is True
    assert report["summary"]["final_submissions"] == 0
    assert [item["transition_id"] for item in report["timeline"]] == [
        "seek_apply:keep_default_documents",
        "seek_apply:fill_cover_letter",
        "seek_apply:answer_questions",
        "seek_apply:skip_profile_update",
        "seek_apply:block_final_submit",
    ]
    fill_steps = [item for item in report["timeline"] if item["requires_safe_fill_focus"]]
    assert [item["action"] for item in fill_steps] == [
        "fill_cover_letter_and_continue",
        "answer_employer_questions_and_continue",
    ]
    assert all(item["allows_final_submit"] is False for item in report["timeline"])
    assert all(item["requires_screenshot_before"] is True for item in report["timeline"])
    assert report["timeline"][-1]["low_level_action_type"] == "guard"
    assert report["timeline"][-1]["requires_screenshot_after"] is False


def test_application_flow_replay_report_blocks_when_safe_fill_not_required() -> None:
    artifact = _read_json("artifacts/seek/learned_seek_application_flow_plexure_20260620.json")
    artifact["field_fill_policy"]["safe_fill_required_for_future_replay"] = False

    report = build_seek_application_flow_replay_report(artifact)

    assert report["status"] == "fail"
    assert report["summary"]["can_run_live_strict_replay"] is False
    assert [item["check_id"] for item in report["blocking_failures"]] == ["safe_fill_required"]


def test_application_flow_replay_report_cli_writes_report(tmp_path, capsys) -> None:
    out_path = tmp_path / "replay.json"

    exit_code = main(["--out", str(out_path), "--fail-on-error"])
    printed = json.loads(capsys.readouterr().out)
    report = json.loads(out_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert printed["success"] is True
    assert printed["summary"]["can_run_live_strict_replay"] is True
    assert report["contract_version"] == "seek_application_flow_replay_report_v1"
