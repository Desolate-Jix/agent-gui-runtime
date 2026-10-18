from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.audit import add_audit_check, audit_counts, audit_decision, int_value, list_of_dicts, recursive_values


AUDIT_CONTRACT = "seek_mvp_run_audit_v1"


def audit_seek_mvp_run(
    report: dict[str, Any] | None,
    *,
    trace: dict[str, Any] | None = None,
    report_path: str | Path | None = None,
    trace_path: str | Path | None = None,
    stage: str = "no_apply",
    min_jobs: int = 5,
    max_jobs: int | None = 10,
    trace_artifacts: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit a SEEK MVP report and traversal trace against the current stage gates."""

    payload = report if isinstance(report, dict) else {}
    trace_payload = trace if isinstance(trace, dict) else None
    checks: list[dict[str, Any]] = []

    add_audit_check(
        checks,
        "report_contract",
        payload.get("contract_version") == "seek_mvp_run_report_v1",
        "report must be seek_mvp_run_report_v1",
        actual=payload.get("contract_version"),
    )
    _add_check(
        checks,
        "final_submissions_zero",
        int_value(payload.get("final_submissions")) == 0,
        "final_submissions must stay 0",
        actual=payload.get("final_submissions"),
    )
    add_audit_check(
        checks,
        "submit_clicks_zero",
        int_value(payload.get("submit_clicks")) == 0,
        "Submit / Send / Complete clicks must stay 0",
        actual=payload.get("submit_clicks"),
    )
    add_audit_check(
        checks,
        "wrong_scope_scrolls_zero",
        _accuracy(payload).get("wrong_scope_scroll_count") in (0, None),
        "SEEK nested scrolls must target the intended container",
        actual=_accuracy(payload).get("wrong_scope_scroll_count"),
    )
    add_audit_check(
        checks,
        "accuracy_summary_pass",
        _accuracy(payload).get("status") in ("pass", None),
        "accuracy_summary.status must be pass when present",
        actual=_accuracy(payload).get("status"),
    )

    jobs_seen = int_value(payload.get("jobs_seen"))
    jobs_opened = int_value(payload.get("jobs_opened"))
    jobs_fully_read = int_value(payload.get("jobs_fully_read"))
    add_audit_check(checks, "jobs_seen_min", jobs_seen >= min_jobs, f"jobs_seen must be >= {min_jobs}", actual=jobs_seen)
    if max_jobs is not None:
        add_audit_check(checks, "jobs_seen_max", jobs_seen <= max_jobs, f"jobs_seen should be <= {max_jobs}", actual=jobs_seen, severity="warn")
    add_audit_check(checks, "jobs_opened_min", jobs_opened >= min_jobs, f"jobs_opened must be >= {min_jobs}", actual=jobs_opened)
    add_audit_check(checks, "jobs_fully_read_min", jobs_fully_read >= min_jobs, f"jobs_fully_read must be >= {min_jobs}", actual=jobs_fully_read)
    add_audit_check(
        checks,
        "match_decision_coverage",
        len(list_of_dicts(payload.get("match_decisions"))) >= jobs_opened,
        "each opened job should have a match decision",
        actual=len(list_of_dicts(payload.get("match_decisions"))),
        expected=jobs_opened,
    )

    expected_trace_path = str(trace_path or payload.get("traversal_trace_path") or "")
    add_audit_check(
        checks,
        "traversal_trace_path_present",
        bool(expected_trace_path),
        "report must include traversal_trace_path",
        actual=expected_trace_path or None,
    )
    add_audit_check(
        checks,
        "traversal_trace_contract",
        bool(trace_payload and trace_payload.get("contract_version") == "seek_mvp_traversal_trace_v1"),
        "traversal trace must be seek_mvp_traversal_trace_v1",
        actual=(trace_payload or {}).get("contract_version") if trace_payload else None,
    )
    if trace_payload:
        _audit_trace_payload(checks, payload, trace_payload)
        if trace_artifacts is not None:
            _audit_trace_artifacts(checks, trace_payload, trace_artifacts)

    strong_or_maybe = int_value(payload.get("strong_apply")) + int_value(payload.get("maybe_apply"))
    saved_jobs = list_of_dicts(payload.get("saved_jobs"))
    add_audit_check(
        checks,
        "suitable_jobs_saved",
        len(saved_jobs) >= strong_or_maybe,
        "strong_apply and maybe_apply jobs should have saved records",
        actual=len(saved_jobs),
        expected=strong_or_maybe,
        severity="warn" if strong_or_maybe == 0 else "fail",
    )

    if stage in {"apply_entry", "full_mvp"}:
        _audit_apply_entry(checks, payload)
    _audit_profile_gate_respected(checks, payload)
    if stage == "full_mvp":
        _audit_full_mvp(checks, payload)

    counts = audit_counts(checks)
    decision = audit_decision(checks)
    return {
        "contract_version": AUDIT_CONTRACT,
        "stage": stage,
        "decision": decision,
        "report_path": str(report_path) if report_path else None,
        "traversal_trace_path": expected_trace_path or None,
        "summary": {
            "jobs_seen": jobs_seen,
            "jobs_opened": jobs_opened,
            "jobs_fully_read": jobs_fully_read,
            "strong_apply": int_value(payload.get("strong_apply")),
            "maybe_apply": int_value(payload.get("maybe_apply")),
            "application_flows_started": int_value(payload.get("application_flows_started")),
            "cover_letters_generated": int_value(payload.get("cover_letters_generated")),
            "forms_filled_until_review": int_value(payload.get("forms_filled_until_review")),
            "final_submissions": int_value(payload.get("final_submissions")),
            "elapsed_ms": payload.get("elapsed_ms"),
        },
        "counts": counts,
        "checks": checks,
        "next_step": _next_step(stage, decision, payload),
    }


def _audit_trace_payload(checks: list[dict[str, Any]], report: dict[str, Any], trace: dict[str, Any]) -> None:
    events = _list_of_dicts(trace.get("traversal_events"))
    scroll_events = _list_of_dicts(trace.get("scroll_events"))
    trace_match_decisions = _list_of_dicts(trace.get("match_decisions"))
    _add_check(
        checks,
        "trace_traversal_events_present",
        len(events) >= _int(report.get("jobs_opened")),
        "trace should include traversal events for opened jobs",
        actual=len(events),
        expected=_int(report.get("jobs_opened")),
    )
    opened_clicks = [
        event
        for event in events
        if isinstance(event.get("card_click"), dict) and event["card_click"].get("opened") is True
    ]
    _add_check(
        checks,
        "trace_card_click_open_evidence",
        len(opened_clicks) >= _int(report.get("jobs_opened")),
        "trace should show opened card-click evidence for each opened job",
        actual=len(opened_clicks),
        expected=_int(report.get("jobs_opened")),
    )
    missing_click_traces = [
        event.get("index")
        for event in opened_clicks
        if not (event.get("card_click") or {}).get("trace_path")
        and not (event.get("card_click") or {}).get("recognition_plan_trace_path")
    ]
    _add_check(
        checks,
        "trace_card_click_paths_present",
        not missing_click_traces,
        "opened card clicks should keep action or recognition-plan trace paths",
        actual=missing_click_traces,
    )
    incomplete_details = [
        event.get("index")
        for event in events
        if isinstance(event.get("detail_read"), dict) and event["detail_read"].get("complete") is not True
    ]
    _add_check(
        checks,
        "trace_detail_reads_complete",
        not incomplete_details,
        "trace detail_read.complete should be true for audited opened jobs",
        actual=incomplete_details,
    )
    wrong_results_scrolls = [
        scroll.get("trace_path") or scroll.get("target_container_id")
        for scroll in scroll_events
        if scroll.get("target_container_id") not in (None, "seek:results_list")
    ]
    _add_check(
        checks,
        "trace_results_scroll_scope",
        not wrong_results_scrolls,
        "trace-level results-list scrolls must target seek:results_list",
        actual=wrong_results_scrolls,
    )
    wrong_detail_scrolls = []
    for event in events:
        detail_read = event.get("detail_read") if isinstance(event.get("detail_read"), dict) else {}
        for scroll in _list_of_dicts(detail_read.get("scrolls")):
            if scroll.get("target_container_id") not in (None, "seek:job_detail"):
                wrong_detail_scrolls.append(scroll.get("trace_path") or scroll.get("target_container_id"))
    _add_check(
        checks,
        "trace_detail_scroll_scope",
        not wrong_detail_scrolls,
        "trace-level detail scrolls must target seek:job_detail",
        actual=wrong_detail_scrolls,
    )
    _add_check(
        checks,
        "trace_match_decisions_present",
        len(trace_match_decisions) >= _int(report.get("jobs_opened")),
        "trace should include match decisions for opened jobs",
        actual=len(trace_match_decisions),
        expected=_int(report.get("jobs_opened")),
    )
    safety = trace.get("safety") if isinstance(trace.get("safety"), dict) else {}
    _add_check(
        checks,
        "trace_safety_final_submissions_zero",
        _int(safety.get("final_submissions")) == 0,
        "trace safety must keep final_submissions=0",
        actual=safety.get("final_submissions"),
    )
    invalid_match_decisions = [
        item.get("decision")
        for item in trace_match_decisions
        if item.get("decision") not in {"strong_apply", "maybe_apply", "skip", "need_user_review"}
    ]
    _add_check(
        checks,
        "trace_match_decision_values_valid",
        not invalid_match_decisions,
        "trace match decisions must use the SEEK decision enum",
        actual=invalid_match_decisions,
    )
    saved_decision_errors = [
        item.get("decision")
        for item in _list_of_dicts(trace.get("saved_jobs"))
        if item.get("decision") and item.get("decision") not in {"strong_apply", "maybe_apply"}
    ]
    _add_check(
        checks,
        "trace_saved_jobs_only_suitable",
        not saved_decision_errors,
        "saved jobs must only be strong_apply or maybe_apply",
        actual=saved_decision_errors,
    )


def _audit_trace_artifacts(
    checks: list[dict[str, Any]],
    trace: dict[str, Any],
    trace_artifacts: dict[str, dict[str, Any]],
) -> None:
    events = _list_of_dicts(trace.get("traversal_events"))
    opened_events = [
        event
        for event in events
        if isinstance(event.get("card_click"), dict) and event["card_click"].get("opened") is True
    ]
    missing_files: list[str] = []
    missing_seed: list[Any] = []
    missing_coordinate_source: list[Any] = []
    missing_pre_click: list[Any] = []
    missing_post_click: list[Any] = []
    risky_no_apply_targets: list[Any] = []
    for event in opened_events:
        card_click = event.get("card_click") if isinstance(event.get("card_click"), dict) else {}
        paths = [str(path) for path in [card_click.get("trace_path"), card_click.get("recognition_plan_trace_path")] if path]
        artifacts = [trace_artifacts[path] for path in paths if path in trace_artifacts]
        if paths and not artifacts:
            missing_files.extend(paths)
            continue
        combined = {"artifacts": artifacts}
        seeded = recursive_values(combined, "seeded_candidate")
        seeded_used = recursive_values(combined, "seeded_candidate_used")
        coordinate_sources = [str(value) for value in recursive_values(combined, "coordinate_source")]
        allowed_values = recursive_values(combined, "allowed")
        verified_values = recursive_values(combined, "verified") + recursive_values(combined, "success")
        labels = [str(value).casefold() for value in recursive_values(combined, "label") + recursive_values(combined, "selected_texts")]
        if not seeded or True not in seeded_used:
            missing_seed.append(event.get("index"))
        if not any("seeded_candidate_v1_validated_by_vista" in source for source in coordinate_sources):
            missing_coordinate_source.append(event.get("index"))
        if True not in allowed_values:
            missing_pre_click.append(event.get("index"))
        if True not in verified_values:
            missing_post_click.append(event.get("index"))
        if any(_looks_like_apply_or_submit_label(label) for label in labels):
            risky_no_apply_targets.append(event.get("index"))
    _add_check(
        checks,
        "trace_artifact_files_present",
        not missing_files,
        "referenced card-click trace artifacts must exist when artifact checking is enabled",
        actual=missing_files[:10],
    )
    _add_check(
        checks,
        "trace_artifact_seeded_candidate_used",
        not missing_seed,
        "opened SEEK card clicks should show seeded_candidate_v1 usage",
        actual=missing_seed,
    )
    _add_check(
        checks,
        "trace_artifact_seeded_coordinate_source",
        not missing_coordinate_source,
        "opened SEEK card clicks should use seed-validated VISTA coordinates",
        actual=missing_coordinate_source,
    )
    _add_check(
        checks,
        "trace_artifact_pre_click_allowed",
        not missing_pre_click,
        "opened SEEK card clicks should include pre_click_decision_v1.allowed=true evidence",
        actual=missing_pre_click,
    )
    _add_check(
        checks,
        "trace_artifact_post_click_verified",
        not missing_post_click,
        "opened SEEK card clicks should include post-click verification evidence",
        actual=missing_post_click,
    )
    _add_check(
        checks,
        "trace_artifact_no_apply_or_submit_card_click",
        not risky_no_apply_targets,
        "no-apply card traversal must not click Apply, Save, Submit, Send, or Complete controls",
        actual=risky_no_apply_targets,
    )


def _audit_apply_entry(checks: list[dict[str, Any]], report: dict[str, Any]) -> None:
    apply_entries = _list_of_dicts(report.get("apply_entries"))
    _add_check(
        checks,
        "apply_entry_started",
        _int(report.get("application_flows_started")) >= 1 and bool(apply_entries),
        "Apply Entry stage requires at least one application flow and apply entry record",
        actual={"application_flows_started": report.get("application_flows_started"), "apply_entries": len(apply_entries)},
    )
    stopped_safely = [
        entry
        for entry in apply_entries
        if entry.get("status") == "blocked_need_user_or_gpt_decision"
        and entry.get("final_submission_performed") is not True
    ]
    _add_check(
        checks,
        "apply_entry_stopped_before_submit",
        bool(stopped_safely),
        "Apply Entry must stop before final submit",
        actual=[entry.get("stop_reason") for entry in apply_entries],
    )
    _add_check(
        checks,
        "pre_apply_detail_verification_ok",
        any((entry.get("pre_apply_detail_verification") or {}).get("ok") is True for entry in apply_entries),
        "Apply Entry should revalidate the current detail pane before clicking Apply",
        actual=[entry.get("pre_apply_detail_verification") for entry in apply_entries],
    )
    _add_check(
        checks,
        "final_submit_guard_active",
        report.get("final_submit_guard_active") is True
        or any((entry.get("final_submit_guard") or {}).get("enabled") is True for entry in apply_entries),
        "Apply Entry must have final_submit_guard_v1 evidence",
        actual=report.get("final_submit_guard_active"),
    )
    _add_check(
        checks,
        "application_flow_blocker_recorded",
        any(
            isinstance(entry.get("application_flow_state"), dict)
            or isinstance(entry.get("final_submit_visible_blocker"), dict)
            for entry in apply_entries
        ),
        "Apply Entry should record application state or final-submit blocker evidence",
        actual=[
            {
                "has_application_flow_state": isinstance(entry.get("application_flow_state"), dict),
                "has_final_submit_visible_blocker": isinstance(entry.get("final_submit_visible_blocker"), dict),
            }
            for entry in apply_entries
        ],
        severity="warn",
    )


def _audit_profile_gate_respected(checks: list[dict[str, Any]], report: dict[str, Any]) -> None:
    readiness = report.get("candidate_profile_readiness") if isinstance(report.get("candidate_profile_readiness"), dict) else {}
    if readiness.get("decision") != "blocked_need_real_candidate_profile":
        return
    apply_entries = _list_of_dicts(report.get("apply_entries"))
    blocked_before_click = all(
        entry.get("status") == "blocked_need_real_candidate_profile"
        and entry.get("executed") is not True
        and entry.get("application_flow_started") is not True
        for entry in apply_entries
    )
    no_apply_started = _int(report.get("application_flows_started")) == 0 and not apply_entries
    _add_check(
        checks,
        "blocked_profile_did_not_enter_apply",
        no_apply_started or blocked_before_click,
        "blocked_need_real_candidate_profile must not click Apply or enter the application flow",
        actual={
            "application_flows_started": report.get("application_flows_started"),
            "apply_entries": len(apply_entries),
        },
    )
    _add_check(
        checks,
        "blocked_profile_no_cover_letter_or_fill",
        _int(report.get("cover_letters_generated")) == 0
        and _int(report.get("form_fields_filled")) == 0
        and not _list_of_dicts(report.get("safe_form_fill_attempts")),
        "blocked_need_real_candidate_profile must not generate live cover letters or fill fields",
        actual={
            "cover_letters_generated": report.get("cover_letters_generated"),
            "form_fields_filled": report.get("form_fields_filled"),
            "safe_form_fill_attempts": len(_list_of_dicts(report.get("safe_form_fill_attempts"))),
        },
    )


def _audit_full_mvp(checks: list[dict[str, Any]], report: dict[str, Any]) -> None:
    readiness = report.get("candidate_profile_readiness") if isinstance(report.get("candidate_profile_readiness"), dict) else {}
    _add_check(
        checks,
        "real_profile_ready",
        readiness.get("decision") == "ready_for_single_safe_field_live_smoke",
        "full MVP requires a real candidate_profile_v1 readiness pass",
        actual=readiness.get("decision"),
    )
    _add_check(
        checks,
        "cover_letter_generated",
        _int(report.get("cover_letters_generated")) >= 1,
        "full MVP requires a truthful draft cover letter generated from real profile and job detail",
        actual=report.get("cover_letters_generated"),
    )
    _add_check(
        checks,
        "form_fill_attempt_recorded",
        bool(_list_of_dicts(report.get("safe_form_fill_attempts"))),
        "full MVP requires a safe-fill attempt or preview trace before stopping",
        actual=len(_list_of_dicts(report.get("safe_form_fill_attempts"))),
    )


def _add_check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    message: str,
    *,
    actual: Any = None,
    expected: Any = None,
    severity: str = "fail",
) -> None:
    add_audit_check(checks, check_id, passed, message, actual=actual, expected=expected, severity=severity)


def _next_step(stage: str, decision: str, report: dict[str, Any]) -> str:
    if decision != "pass":
        return "inspect_failed_audit_checks_before_more_live_actions"
    if stage == "no_apply":
        readiness = report.get("candidate_profile_readiness") if isinstance(report.get("candidate_profile_readiness"), dict) else {}
        if readiness.get("decision") != "ready_for_single_safe_field_live_smoke":
            return "prepare_real_candidate_profile_v1_then_rerun_readiness"
        if _int(report.get("strong_apply")) > 0:
            return "run_one_apply_entry_readonly_for_strong_apply_without_safe_fill"
        return "rerun_real_profile_matching_until_strong_apply_or_user_review"
    if stage == "apply_entry":
        return "inspect_answer_plan_and_safe_fill_preview_before_single_field_safe_fill"
    return "report_to_gpt_for_final_review_before_shutdown"


def _accuracy(report: dict[str, Any]) -> dict[str, Any]:
    accuracy = report.get("accuracy_summary")
    return accuracy if isinstance(accuracy, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return list_of_dicts(value)


def _int(value: Any) -> int:
    return int_value(value)


def _looks_like_apply_or_submit_label(label: str) -> bool:
    text = " ".join(label.casefold().split())
    risky_terms = (
        "apply",
        "quick apply",
        "save",
        "submit",
        "send application",
        "complete application",
        "finish application",
    )
    return any(term in text for term in risky_terms)
