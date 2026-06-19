from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.seek.audit import audit_seek_mvp_run


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seek_mvp_report_audit.py"
spec = importlib.util.spec_from_file_location("seek_mvp_report_audit", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def _event(index: int) -> dict:
    return {
        "index": index,
        "job_id": f"job-{index}",
        "card": {"title": f"Software Engineer {index}", "company": "Example"},
        "card_click": {
            "opened": True,
            "trace_path": f"logs/traces/actions/card-{index}.json",
            "recognition_plan_trace_path": f"logs/traces/vision/card-{index}.json",
        },
        "detail_read": {
            "title": f"Software Engineer {index}",
            "company": "Example",
            "trace_paths": [f"logs/traces/vision/detail-{index}.json"],
            "complete": True,
            "missing_evidence": [],
            "scrolls": [
                {
                    "target_container_id": "seek:job_detail",
                    "trace_path": f"logs/traces/actions/detail-scroll-{index}.json",
                }
            ],
        },
        "match_decision": {"decision": "strong_apply" if index == 0 else "maybe_apply", "score": 0.8},
    }


def _report_and_trace(*, jobs: int = 5, trace_path: str = "logs/traces/seek/demo.json") -> tuple[dict, dict]:
    match_decisions = [
        {"contract_version": "seek_job_match_decision_v1", "decision": "strong_apply" if index == 0 else "maybe_apply", "score": 0.8}
        for index in range(jobs)
    ]
    report = {
        "contract_version": "seek_mvp_run_report_v1",
        "mode": "no_apply_traversal",
        "jobs_seen": jobs,
        "jobs_opened": jobs,
        "jobs_fully_read": jobs,
        "strong_apply": 1,
        "maybe_apply": jobs - 1,
        "skip": 0,
        "need_user_review": 0,
        "application_flows_started": 0,
        "cover_letters_generated": 0,
        "forms_filled_until_review": 0,
        "form_fields_filled": 0,
        "continue_clicks": 0,
        "submit_clicks": 0,
        "final_submissions": 0,
        "match_decisions": match_decisions,
        "saved_jobs": [{"path": f"artifacts/seek/saved/job-{index}.json"} for index in range(jobs)],
        "results_list_scrolls": [
            {"target_container_id": "seek:results_list", "trace_path": "logs/traces/actions/results-scroll.json"}
        ],
        "accuracy_summary": {
            "contract_version": "seek_mvp_accuracy_summary_v1",
            "jobs_seen": jobs,
            "jobs_opened": jobs,
            "jobs_fully_read": jobs,
            "wrong_scope_scroll_count": 0,
            "status": "pass",
        },
        "traversal_trace_path": trace_path,
        "elapsed_ms": 1234,
    }
    trace = {
        "contract_version": "seek_mvp_traversal_trace_v1",
        "source_report_contract": "seek_mvp_run_report_v1",
        "mode": "no_apply_traversal",
        "traversal_events": [_event(index) for index in range(jobs)],
        "scroll_events": [{"target_container_id": "seek:results_list", "trace_path": "logs/traces/actions/results-scroll.json"}],
        "match_decisions": match_decisions,
        "saved_jobs": report["saved_jobs"],
        "apply_entries": [],
        "application_answer_plans": [],
        "safe_form_fill_attempts": [],
        "accuracy_summary": report["accuracy_summary"],
        "safety": {
            "continue_clicks": 0,
            "submit_clicks": 0,
            "form_fields_filled": 0,
            "final_submissions": 0,
            "final_submit_guard_active": False,
        },
    }
    return report, trace


def test_audit_passes_no_apply_5_job_report_with_trace() -> None:
    report, trace = _report_and_trace()
    report["candidate_profile_readiness"] = {"decision": "blocked_need_real_candidate_profile"}

    audit = audit_seek_mvp_run(report, trace=trace, stage="no_apply", min_jobs=5)

    assert audit["contract_version"] == "seek_mvp_run_audit_v1"
    assert audit["decision"] == "pass"
    assert audit["counts"]["failed"] == 0
    assert audit["summary"]["jobs_fully_read"] == 5
    assert audit["next_step"] == "prepare_real_candidate_profile_v1_then_rerun_readiness"


def test_audit_flags_submit_and_wrong_scroll_scope() -> None:
    report, trace = _report_and_trace()
    report["submit_clicks"] = 1
    report["accuracy_summary"]["status"] = "needs_review"
    report["accuracy_summary"]["wrong_scope_scroll_count"] = 1
    trace["traversal_events"][0]["detail_read"]["scrolls"][0]["target_container_id"] = "seek:page"

    audit = audit_seek_mvp_run(report, trace=trace, stage="no_apply", min_jobs=5)
    failed = {check["id"] for check in audit["checks"] if check["status"] == "fail"}

    assert audit["decision"] == "needs_review"
    assert "submit_clicks_zero" in failed
    assert "wrong_scope_scrolls_zero" in failed
    assert "trace_detail_scroll_scope" in failed


def test_audit_apply_entry_requires_stop_and_guard_evidence() -> None:
    report, trace = _report_and_trace(jobs=1)
    report.update(
        {
            "application_flows_started": 1,
            "final_submit_guard_active": True,
            "apply_entries": [
                {
                    "status": "blocked_need_user_or_gpt_decision",
                    "stop_reason": "application_form_detected_stop_before_form_fill",
                    "application_flow_started": True,
                    "final_submission_performed": False,
                    "pre_apply_detail_verification": {"ok": True},
                    "final_submit_guard": {"enabled": True, "allowed": True},
                    "application_flow_state": {"state_type": "application_form_detected"},
                }
            ],
        }
    )

    audit = audit_seek_mvp_run(report, trace=trace, stage="apply_entry", min_jobs=1)

    assert audit["decision"] == "pass"
    assert audit["next_step"] == "inspect_answer_plan_and_safe_fill_preview_before_single_field_safe_fill"


def test_cli_writes_audit_and_fails_for_missing_trace(tmp_path, capsys) -> None:
    report, _trace = _report_and_trace(trace_path="missing-trace.json")
    report_path = tmp_path / "report.json"
    out_path = tmp_path / "audit.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    exit_code = cli.main(["--report", str(report_path), "--out", str(out_path), "--fail-if-needs-review"])
    printed = json.loads(capsys.readouterr().out)
    audit = json.loads(out_path.read_text(encoding="utf-8"))

    assert exit_code == 2
    assert printed["decision"] == "needs_review"
    assert audit["contract_version"] == "seek_mvp_run_audit_v1"
    assert any(check["id"] == "traversal_trace_contract" and check["status"] == "fail" for check in audit["checks"])


def test_cli_reads_relative_trace_and_passes(tmp_path, capsys) -> None:
    report, trace = _report_and_trace(trace_path="trace.json")
    report_path = tmp_path / "report.json"
    trace_path = tmp_path / "trace.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")

    exit_code = cli.main(["--report", str(report_path), "--trace", str(trace_path), "--mode", "readonly", "--out", str(tmp_path / "audit.json")])
    printed = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert printed["decision"] == "pass"


def test_cli_check_trace_files_reads_seeded_artifacts(tmp_path, capsys) -> None:
    report, trace = _report_and_trace(jobs=1, trace_path=str(tmp_path / "trace.json"))
    action_trace = tmp_path / "card-action.json"
    recognition_trace = tmp_path / "card-recognition.json"
    trace["traversal_events"][0]["card_click"]["trace_path"] = str(action_trace)
    trace["traversal_events"][0]["card_click"]["recognition_plan_trace_path"] = str(recognition_trace)
    artifact = {
        "seeded_candidate": {"contract_version": "seeded_candidate_v1"},
        "seeded_candidate_used": True,
        "coordinate_source": "seeded_candidate_v1_validated_by_vista_point_v1",
        "pre_click_decision": {"allowed": True},
        "post_click_verification": {"verified": True},
        "selected_candidate": {"label": "Software Engineer"},
    }
    report_path = tmp_path / "report.json"
    trace_path = tmp_path / "trace.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    trace_path.write_text(json.dumps(trace, ensure_ascii=False), encoding="utf-8")
    action_trace.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
    recognition_trace.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")

    exit_code = cli.main(["--report", str(report_path), "--check-trace-files", "--min-jobs", "1"])
    printed = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert printed["decision"] == "pass"


def test_audit_flags_blocked_profile_that_entered_apply() -> None:
    report, trace = _report_and_trace()
    report.update(
        {
            "candidate_profile_readiness": {"decision": "blocked_need_real_candidate_profile"},
            "application_flows_started": 1,
            "apply_entries": [{"status": "blocked_need_user_or_gpt_decision", "executed": True, "application_flow_started": True}],
        }
    )

    audit = audit_seek_mvp_run(report, trace=trace, stage="no_apply", min_jobs=5)
    failed = {check["id"] for check in audit["checks"] if check["status"] == "fail"}

    assert audit["decision"] == "needs_review"
    assert "blocked_profile_did_not_enter_apply" in failed


def test_audit_checks_seeded_trace_artifacts_when_supplied() -> None:
    report, trace = _report_and_trace(jobs=1)
    artifact = {
        "contract_version": "action_trace_v1",
        "recognition_plan": {
            "seeded_candidate": {"contract_version": "seeded_candidate_v1"},
            "seeded_candidate_used": True,
            "coordinate_source": "seeded_candidate_v1_validated_by_vista_point_v1",
        },
        "pre_click_decision": {"contract_version": "pre_click_decision_v1", "allowed": True},
        "post_click_verification": {"verified": True},
        "selected_candidate": {"label": "Software Engineer 0"},
    }

    audit = audit_seek_mvp_run(
        report,
        trace=trace,
        stage="no_apply",
        min_jobs=1,
        trace_artifacts={
            "logs/traces/actions/card-0.json": artifact,
            "logs/traces/vision/card-0.json": artifact,
        },
    )

    assert audit["decision"] == "pass"
    assert all(
        check["status"] == "pass"
        for check in audit["checks"]
        if check["id"].startswith("trace_artifact_")
    )


def test_audit_flags_missing_seeded_trace_artifact_evidence() -> None:
    report, trace = _report_and_trace(jobs=1)
    artifact = {
        "contract_version": "action_trace_v1",
        "pre_click_decision": {"contract_version": "pre_click_decision_v1", "allowed": True},
        "post_click_verification": {"verified": True},
        "selected_candidate": {"label": "Apply"},
    }

    audit = audit_seek_mvp_run(
        report,
        trace=trace,
        stage="no_apply",
        min_jobs=1,
        trace_artifacts={"logs/traces/actions/card-0.json": artifact},
    )
    failed = {check["id"] for check in audit["checks"] if check["status"] == "fail"}

    assert audit["decision"] == "needs_review"
    assert "trace_artifact_seeded_candidate_used" in failed
    assert "trace_artifact_seeded_coordinate_source" in failed
    assert "trace_artifact_no_apply_or_submit_card_click" in failed
