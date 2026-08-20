from __future__ import annotations

from pathlib import Path

from scripts.learn_sample_readiness_gate import build_readiness_gate


def _checkpoint(**summary_overrides: object) -> dict:
    summary = {
        "skill_count": 19,
        "artifact_authorizes_click": False,
        "covers_click": True,
        "covers_scroll": True,
        "covers_input": True,
        "covers_read": True,
        "covers_guarded_actions": True,
        "covers_filter_or_tab": True,
        "covers_sort_or_filter_click": True,
        "covers_table_record_open": True,
        "seek_application_flow": "pass",
        "seek_application_flow_replay": "pass",
        "seek_application_final_submit_forbidden": True,
        "seek_application_safe_fill_required": True,
        "seek_application_can_run_live_strict_replay": True,
        "write_actions_clicked": 0,
        "final_submissions": 0,
    }
    summary.update(summary_overrides)
    return {
        "contract_version": "learn_execute_mvp_checkpoint_report_v1",
        "status": "pass",
        "summary": summary,
    }


def _regression(**summary_overrides: object) -> dict:
    summary = {"baseline_count": 5, "passed": 5, "failed": 0}
    summary.update(summary_overrides)
    return {
        "contract_version": "artifact_replay_regression_report_v1",
        "status": "pass",
        "summary": summary,
        "regression_gate": {"can_continue_to_new_family": True, "blocking_failures": []},
    }


def test_readiness_gate_allows_new_sample_after_checkpoint_and_regression_pass() -> None:
    gate = build_readiness_gate(
        _checkpoint(),
        _regression(),
        template_path=Path("artifacts/templates/learn_sample_template_v1.json"),
    )

    assert gate["contract_version"] == "learn_sample_readiness_gate_v1"
    assert gate["status"] == "pass"
    assert gate["ready_for_new_learn_sample"] is True
    assert gate["next_sample_policy"]["codex_in_app_browser"] == "chatgpt_only"
    assert gate["summary"]["covers_scroll"] is True
    assert gate["summary"]["seek_application_flow"] == "pass"
    assert gate["summary"]["seek_application_flow_replay"] == "pass"
    assert gate["summary"]["seek_application_final_submit_forbidden"] is True
    assert gate["summary"]["seek_application_safe_fill_required"] is True
    assert gate["summary"]["seek_application_can_run_live_strict_replay"] is True
    assert gate["summary"]["final_submissions"] == 0
    assert gate["blocking_failures"] == []


def test_readiness_gate_blocks_new_sample_when_safety_counter_fails() -> None:
    gate = build_readiness_gate(
        _checkpoint(final_submissions=1),
        _regression(),
        template_path=Path("artifacts/templates/learn_sample_template_v1.json"),
    )

    assert gate["status"] == "fail"
    assert gate["ready_for_new_learn_sample"] is False
    assert [item["check_id"] for item in gate["blocking_failures"]] == ["final_submit_guard"]


def test_readiness_gate_blocks_new_sample_when_application_flow_missing() -> None:
    gate = build_readiness_gate(
        _checkpoint(seek_application_flow=None),
        _regression(),
        template_path=Path("artifacts/templates/learn_sample_template_v1.json"),
    )

    assert gate["status"] == "fail"
    assert gate["ready_for_new_learn_sample"] is False
    assert [item["check_id"] for item in gate["blocking_failures"]] == ["seek_application_flow"]
