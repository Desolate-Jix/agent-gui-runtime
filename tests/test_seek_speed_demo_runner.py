import argparse
import hashlib
import json
from pathlib import Path

import scripts.seek_speed_demo_runner as runner

from scripts.seek_speed_demo_runner import (
    _apply_decision_allowed,
    _card_needs_scroll_into_safer_position,
    _card_prefilter_decision,
    _cards_fingerprint,
    _clamp_scroll_wheel_clicks,
    _external_apply_flow_started,
    _persist_multi_interface_workflow,
    _station_internal_application_started,
    _write_speed_demo_result,
)


def _write_approved_live_fill_preflight(
    tmp_path: Path,
    *,
    field_id: str,
) -> tuple[Path, str]:
    path = tmp_path / "approved-live-safe-fill-preflight.json"
    path.write_text(
        json.dumps(
            {
                "contract_version": "seek_live_safe_fill_preflight_v1",
                "status": "ready_for_human_review",
                "approval_state": "awaiting_explicit_approval",
                "field": {
                    "id": field_id,
                    "label": "Email",
                    "field_type": "email",
                    "risk_class": "ordinary_field",
                },
                "value_evidence": {
                    "answer_source": "candidate_profile.email",
                    "value_length": 20,
                    "value_hash": "a" * 64,
                    "value_redacted": True,
                },
                "safety": {
                    "max_fields": 1,
                    "cover_letter_fill_allowed": False,
                    "continue_allowed": False,
                    "final_submit_allowed": False,
                    "artifact_is_authorization": False,
                },
                "pii_redacted": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_speed_demo_report_includes_multi_interface_workflow_projection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    projected = {
        "contract_version": "continuous_workflow_projection_result_v1",
        "status": "saved_needs_human_review",
        "interface_count": 3,
        "transition_count": 2,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    monkeypatch.setattr(
        runner,
        "_persist_multi_interface_workflow",
        lambda **kwargs: projected,
    )

    report = _write_speed_demo_result(
        tmp_path,
        started=runner.time.perf_counter(),
        args=argparse.Namespace(
            time_budget_ms=60_000,
            disable_learned_fast_mode=False,
        ),
        steps=[],
        job_attempts=[],
        result_scrolls=[],
        status="safe_stop",
        stop_reason="application_entry_reached",
    )

    saved = json.loads((tmp_path / "speed_demo_report.json").read_text(encoding="utf-8"))
    assert report["multi_interface_workflow"] == projected
    assert saved["multi_interface_workflow"] == projected
    assert saved["multi_interface_workflow"]["interface_count"] == 3
    assert saved["final_submissions"] == 0
    assert saved["submit_clicks"] == 0


def test_multi_interface_workflow_is_not_covered_without_continuous_session(
    tmp_path: Path,
) -> None:
    result = _persist_multi_interface_workflow(
        run_dir=tmp_path,
        args=argparse.Namespace(url="https://example.test"),
    )

    assert result["status"] == "not_covered"
    assert result["reason"] == "continuous_session_not_available"
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False


def test_card_prefilter_never_skips_jobs_before_agent_reads_detail() -> None:
    summer = {
        "title": "SOFTWARE ENGINEER SUMMER",
        "company": "TRV Trading",
        "classification": "SOFTWARE ENGINEER SUMMER",
    }
    internship = {
        "title": "Research/Developer Summer",
        "company": "INTERNSHIP / GRADUATE",
        "classification": "",
    }

    assert _card_prefilter_decision(summer) == {
        "decision": "keep",
        "reason": "agent_requires_full_detail",
    }
    assert _card_prefilter_decision(internship) == {
        "decision": "keep",
        "reason": "agent_requires_full_detail",
    }


def test_card_prefilter_keeps_regular_software_engineer_card() -> None:
    card = {
        "title": "Software Engineer",
        "company": "Absolute IT Limited",
        "classification": "Engineering - Software",
    }

    assert _card_prefilter_decision(card, learned_fast_mode=False) == {
        "decision": "keep",
        "reason": "agent_requires_full_detail",
    }


def test_learned_fast_mode_does_not_restore_local_keyword_filtering() -> None:
    generic = {
        "title": "Software Engineer",
        "company": "Absolute IT Limited",
        "classification": "Engineering - Software",
    }
    senior = {
        "title": "Senior Software Engineer",
        "company": "Local Co",
        "classification": "Engineering - Software",
    }
    graduate = {
        "title": "Graduate Software Engineer",
        "company": "Local Co",
        "classification": "Engineering - Software",
    }

    for card in (generic, senior, graduate):
        assert _card_prefilter_decision(card) == {
            "decision": "keep",
            "reason": "agent_requires_full_detail",
        }


def test_low_visible_card_requires_scroll_before_click() -> None:
    low_card = {"card_bbox": {"x": 650, "y": 1260, "w": 220, "h": 120}}
    middle_card = {"card_bbox": {"x": 650, "y": 760, "w": 220, "h": 160}}

    assert _card_needs_scroll_into_safer_position(low_card, window_height=1400) is True
    assert _card_needs_scroll_into_safer_position(middle_card, window_height=1400) is False


def test_cards_fingerprint_tracks_visible_job_identity() -> None:
    cards = [
        {"title": "Software Engineer", "company": "Absolute IT Limited", "location": "Auckland CBD"},
        {"title": "Senior Web Software Engineer", "company": "Serato Limited", "location": "Ponsonby"},
    ]

    assert _cards_fingerprint(cards) == (
        "Software Engineer|Absolute IT Limited|Auckland CBD",
        "Senior Web Software Engineer|Serato Limited|Ponsonby",
    )


def test_maybe_apply_requires_explicit_runner_flag() -> None:
    assert _apply_decision_allowed("strong_apply", allow_maybe_apply=False) is True
    assert _apply_decision_allowed("maybe_apply", allow_maybe_apply=False) is False
    assert _apply_decision_allowed("maybe_apply", allow_maybe_apply=True) is True


def test_speed_demo_scroll_wheel_clicks_clamped_to_action_api_contract() -> None:
    assert _clamp_scroll_wheel_clicks(0) == 1
    assert _clamp_scroll_wheel_clicks(12) == 12
    assert _clamp_scroll_wheel_clicks(27) == 20


def test_speed_demo_passes_agent_suitability_review_to_full_detail_match(tmp_path, monkeypatch) -> None:
    review_path = tmp_path / "agent-review.json"
    review_path.write_text('{"verdict":"pass"}', encoding="utf-8")
    calls: list[tuple[str, list[str] | None]] = []

    def fake_run_step(run_dir, step, extra=None):
        calls.append((step, extra))
        if step == "extract_cards":
            return {
                "status": "ok",
                "cards_payload": {
                    "jobs": [
                        {
                            "title": "Graduate Trading Manager - AI & Algorithms",
                            "company": "Liger Trading NZ",
                            "location": "Queenstown",
                        }
                    ]
                },
            }
        if step == "match":
            return {
                "status": "ok",
                "match_decision": {"decision": "skip"},
                "detail": {
                    "title": "Graduate Trading Manager - AI & Algorithms",
                    "company": "Liger Trading NZ",
                },
            }
        return {"status": "ok"}

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    args = _continuous_args(
        tmp_path,
        continuous_session=False,
        agent_suitability_review=str(review_path),
    )

    runner.run_speed_demo(args)

    match_extra = next(extra for step, extra in calls if step == "match")
    assert match_extra is not None
    assert match_extra[-2:] == ["--agent-suitability-review", str(review_path)]


def test_speed_demo_continues_after_non_external_apply_skip_to_station_internal_apply(tmp_path, monkeypatch) -> None:
    cards = [
        {"title": "Software Engineer Integration", "company": "AIA", "location": "Auckland"},
        {"title": "Graduate Software Developer", "company": "Local Co", "location": "Auckland"},
    ]
    match_payloads = [
        {
            "status": "ok",
            "match_decision": {"decision": "strong_apply"},
            "detail": {"title": "Software Engineer Integration", "company": "AIA"},
        },
        {
            "status": "ok",
            "match_decision": {"decision": "strong_apply"},
            "detail": {"title": "Graduate Software Developer", "company": "Local Co"},
        },
    ]
    execute_apply_payloads = [
        {
            "status": "blocked_need_user_or_gpt_decision",
            "apply_entry": {
                "application_flow_started": False,
                "stop_reason": "apply_entry_did_not_start_flow",
            },
        },
        {
            "status": "blocked_need_user_or_gpt_decision",
            "apply_entry": {"application_flow_started": True},
        },
    ]
    calls: list[tuple[str, list[str] | None]] = []

    def fake_run_step(run_dir, step, extra=None):
        calls.append((step, extra))
        if step == "extract_cards":
            return {"status": "ok", "cards_payload": {"jobs": cards}}
        if step == "match":
            return match_payloads.pop(0)
        if step == "execute_apply_entry":
            return execute_apply_payloads.pop(0)
        if step == "extract_final_review":
            return {"status": "ok"}
        return {"status": "ok"}

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(runner, "build_record_from_debug_run", lambda run_dir: {"steps": []})
    monkeypatch.setattr(runner, "build_seek_application_flow_artifact", lambda *args, **kwargs: {"contract_version": "test"})
    monkeypatch.setattr(runner, "load_step_reports", lambda run_dir: [])
    monkeypatch.setattr(
        runner,
        "build_demo_readiness_report",
        lambda **kwargs: {"status": "needs_work", "final_submissions": 0, "submit_clicks": 0},
    )

    args = argparse.Namespace(
        run_dir=tmp_path,
        base_url="http://127.0.0.1:8000",
        timeout=1.0,
        url="https://nz.seek.com/graduate-jobs/in-All-Auckland",
        job_index=0,
        max_jobs=2,
        allow_maybe_apply=True,
        visible_jobs_per_page=2,
        max_result_scrolls=0,
        results_scroll_wheel_clicks=9,
        window_width=2560,
        window_height=1400,
        wheel_clicks=9,
        batch_max_captures=1,
        batch_stop_after_no_new_content=1,
        post_apply_capture_wait_seconds=1.0,
        max_application_steps=0,
        max_safe_fields_to_fill=0,
        time_budget_ms=300000.0,
        close_old_windows=False,
    )

    result = runner.run_speed_demo(args)

    assert result["job_attempts"][0]["status"] == "skipped_apply_entry_execute"
    assert result["job_attempts"][0]["apply_entry_stop_reason"] == "apply_entry_did_not_start_flow"
    assert result["job_attempts"][1]["status"] == "application_started"
    assert "dry_run_card" not in [step for step, _ in calls]
    assert "dry_run_apply_entry" not in [step for step, _ in calls]


def test_station_internal_apply_rejects_third_party_ats_even_if_flow_started() -> None:
    execute_apply = {
        "status": "blocked_need_user_or_gpt_decision",
        "post_apply_wait": {
            "application_flow_state": {
                "application_flow_started": True,
                "state_type": "third_party_ats",
                "stop_reason": "third_party_ats_requires_user_review",
                "risk_flags": ["third_party_ats"],
            }
        },
    }

    assert _station_internal_application_started(execute_apply) is False
    assert _external_apply_flow_started(execute_apply) is True


def test_speed_demo_safe_stops_after_external_ats_login_required(tmp_path, monkeypatch) -> None:
    cards = [
        {"title": "Software Engineer Integration", "company": "AIA", "location": "Auckland"},
        {"title": "Graduate Software Developer", "company": "Local Co", "location": "Auckland"},
    ]
    match_payloads = [
        {
            "status": "ok",
            "match_decision": {"decision": "strong_apply"},
            "detail": {"title": "Software Engineer Integration", "company": "AIA"},
        },
        {
            "status": "ok",
            "match_decision": {"decision": "strong_apply"},
            "detail": {"title": "Graduate Software Developer", "company": "Local Co"},
        },
    ]
    execute_apply_payloads = [
        {
            "status": "blocked_need_user_or_gpt_decision",
            "post_apply_wait": {
                "application_flow_state": {
                    "application_flow_started": False,
                    "state_type": "login_required",
                    "stop_reason": "login_required",
                    "risk_flags": ["third_party_ats", "login_required"],
                }
            },
        },
    ]
    calls: list[tuple[str, list[str] | None]] = []

    def fake_run_step(run_dir, step, extra=None):
        calls.append((step, extra))
        if step == "extract_cards":
            return {"status": "ok", "cards_payload": {"jobs": cards}}
        if step == "match":
            return match_payloads.pop(0)
        if step == "execute_apply_entry":
            return execute_apply_payloads.pop(0)
        if step == "extract_final_review":
            return {"status": "ok"}
        return {"status": "ok"}

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(runner, "build_record_from_debug_run", lambda run_dir: {"steps": []})
    monkeypatch.setattr(runner, "build_seek_application_flow_artifact", lambda *args, **kwargs: {"contract_version": "test"})
    monkeypatch.setattr(runner, "load_step_reports", lambda run_dir: [])
    monkeypatch.setattr(
        runner,
        "build_demo_readiness_report",
        lambda **kwargs: {"status": "needs_work", "final_submissions": 0, "submit_clicks": 0},
    )

    args = argparse.Namespace(
        run_dir=tmp_path,
        base_url="http://127.0.0.1:8000",
        timeout=1.0,
        url="https://nz.seek.com/graduate-jobs/in-All-Auckland",
        job_index=0,
        max_jobs=2,
        allow_maybe_apply=True,
        visible_jobs_per_page=2,
        max_result_scrolls=0,
        results_scroll_wheel_clicks=9,
        window_width=2560,
        window_height=1400,
        wheel_clicks=9,
        batch_max_captures=1,
        batch_stop_after_no_new_content=1,
        post_apply_capture_wait_seconds=1.0,
        max_application_steps=0,
        max_safe_fields_to_fill=0,
        time_budget_ms=300000.0,
        close_old_windows=False,
    )

    result = runner.run_speed_demo(args)

    assert result["job_attempts"][0]["status"] == "skipped_apply_entry_execute"
    assert result["job_attempts"][0]["apply_entry_state_type"] == "login_required"
    assert result["status"] == "safe_stop"
    assert result["stop_reason"] == "external_ats_login_required_safe_stop"
    assert result["safe_stop"]["reason"] == "external_ats_login_required"
    assert result["state_machine_failure"]["category"] == "surface_drift_prevented"
    assert [step for step, _ in calls].count("open") == 1
    assert [step for step, _ in calls].count("execute_apply_entry") == 1
    executed_steps = [step for step, _ in calls]
    after_apply_steps = executed_steps[executed_steps.index("execute_apply_entry") + 1 :]
    assert "extract_cards" not in after_apply_steps
    assert "dry_run_card" not in [step for step, _ in calls]
    assert "dry_run_apply_entry" not in [step for step, _ in calls]
    assert (tmp_path / "speed_demo_report.json").exists()


def test_speed_demo_does_not_extract_cards_after_last_apply_skip(tmp_path, monkeypatch) -> None:
    cards = [{"title": "Software Engineer Integration", "company": "AIA", "location": "Auckland"}]
    calls: list[tuple[str, list[str] | None]] = []

    def fake_run_step(run_dir, step, extra=None):
        calls.append((step, extra))
        if step == "extract_cards":
            return {"status": "ok", "cards_payload": {"jobs": cards}}
        if step == "match":
            return {
                "status": "ok",
                "match_decision": {"decision": "strong_apply"},
                "detail": {"title": "Software Engineer Integration", "company": "AIA"},
            }
        if step == "execute_apply_entry":
            return {
                "status": "blocked_need_user_or_gpt_decision",
                "apply_entry": {
                    "application_flow_started": False,
                    "state_type": "third_party_ats",
                    "stop_reason": "third_party_ats_deferred",
                },
            }
        return {"status": "ok"}

    monkeypatch.setattr(runner, "_run_step", fake_run_step)

    args = argparse.Namespace(
        run_dir=tmp_path,
        base_url="http://127.0.0.1:8000",
        timeout=1.0,
        url="https://nz.seek.com/graduate-jobs/in-All-Auckland",
        job_index=0,
        max_jobs=1,
        allow_maybe_apply=True,
        visible_jobs_per_page=2,
        max_result_scrolls=0,
        results_scroll_wheel_clicks=9,
        window_width=2560,
        window_height=1400,
        wheel_clicks=9,
        batch_max_captures=1,
        batch_stop_after_no_new_content=1,
        post_apply_capture_wait_seconds=1.0,
        max_application_steps=0,
        max_safe_fields_to_fill=0,
        time_budget_ms=300000.0,
        close_old_windows=False,
    )

    result = runner.run_speed_demo(args)

    assert result["status"] == "needs_work"
    assert result["stop_reason"] == "external_apply_flow_opened_no_remaining_job_budget"
    assert [step for step, _ in calls].count("extract_cards") == 1


def test_speed_demo_records_apply_entry_block_from_execute_step(tmp_path, monkeypatch) -> None:
    cards = [{"title": "Embedded Software Engineer", "company": "Garmin", "location": "Auckland"}]
    calls: list[tuple[str, list[str] | None]] = []

    def fake_run_step(run_dir, step, extra=None):
        calls.append((step, extra))
        if step == "extract_cards":
            return {"status": "ok", "cards_payload": {"jobs": cards}}
        if step == "match":
            return {
                "status": "ok",
                "match_decision": {"decision": "strong_apply"},
                "detail": {"title": "Embedded Software Engineer", "company": "Garmin"},
            }
        if step == "execute_apply_entry":
            return {
                "status": "blocked_need_user_or_gpt_decision",
                "apply_entry": {"stop_reason": "pre_apply_detail_verification_failed"},
            }
        return {"status": "ok"}

    monkeypatch.setattr(runner, "_run_step", fake_run_step)

    args = argparse.Namespace(
        run_dir=tmp_path,
        base_url="http://127.0.0.1:8000",
        timeout=1.0,
        url="https://nz.seek.com/graduate-jobs/in-All-Auckland",
        job_index=0,
        max_jobs=1,
        allow_maybe_apply=True,
        visible_jobs_per_page=1,
        max_result_scrolls=0,
        results_scroll_wheel_clicks=9,
        window_width=2560,
        window_height=1400,
        wheel_clicks=9,
        batch_max_captures=1,
        batch_stop_after_no_new_content=1,
        post_apply_capture_wait_seconds=1.0,
        max_application_steps=0,
        max_safe_fields_to_fill=0,
        time_budget_ms=300000.0,
        close_old_windows=False,
    )

    result = runner.run_speed_demo(args)

    assert result["status"] == "needs_work"
    assert result["job_attempts"][0]["status"] == "skipped_apply_entry_execute"
    assert result["job_attempts"][0]["apply_entry_stop_reason"] == "pre_apply_detail_verification_failed"
    assert "dry_run_apply_entry" not in [step for step, _ in calls]


def test_speed_demo_reports_controlled_stop_on_risky_application_questions(tmp_path, monkeypatch) -> None:
    cards = [{"title": "Embedded Software Engineer", "company": "Garmin", "location": "Auckland"}]
    calls: list[tuple[str, list[str] | None]] = []
    continue_payloads = [
        {
            "status": "continued_to_next_step",
            "next_allowed_steps": ["continue_application_flow", "capture"],
            "application_flow_state": {"current_step": "answer_employer_questions"},
        },
        {
            "status": "blocked_need_user_or_gpt_decision",
            "next_allowed_steps": ["capture"],
            "application_flow_state": {
                "current_step": "answer_employer_questions",
                "stop_reason": "risky_application_questions_require_user_or_gpt_decision",
                "final_submission_performed": False,
            },
        },
    ]

    def fake_run_step(run_dir, step, extra=None):
        calls.append((step, extra))
        if step == "extract_cards":
            return {"status": "ok", "cards_payload": {"jobs": cards}}
        if step == "match":
            return {
                "status": "ok",
                "match_decision": {"decision": "strong_apply"},
                "detail": {"title": "Embedded Software Engineer", "company": "Garmin"},
            }
        if step == "execute_apply_entry":
            return {
                "status": "blocked_need_user_or_gpt_decision",
                "apply_entry": {"application_flow_started": True},
            }
        if step == "continue_application_flow":
            return continue_payloads.pop(0)
        if step == "extract_final_review":
            return {"status": "needs_review"}
        return {"status": "ok"}

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(runner, "build_record_from_debug_run", lambda run_dir: {"steps": []})
    monkeypatch.setattr(runner, "build_seek_application_flow_artifact", lambda *args, **kwargs: {"contract_version": "test"})
    monkeypatch.setattr(runner, "load_step_reports", lambda run_dir: [])
    monkeypatch.setattr(
        runner,
        "build_demo_readiness_report",
        lambda **kwargs: {"status": "pass", "final_submissions": 0, "submit_clicks": 0},
    )

    approved_preflight_path, approved_preflight_sha256 = _write_approved_live_fill_preflight(
        tmp_path,
        field_id="email-field",
    )
    args = argparse.Namespace(
        run_dir=tmp_path,
        base_url="http://127.0.0.1:8000",
        timeout=1.0,
        url="https://nz.seek.com/graduate-jobs/in-All-Auckland",
        job_index=0,
        max_jobs=1,
        allow_maybe_apply=True,
        visible_jobs_per_page=1,
        max_result_scrolls=0,
        results_scroll_wheel_clicks=9,
        window_width=2560,
        window_height=1400,
        wheel_clicks=9,
        batch_max_captures=1,
        batch_stop_after_no_new_content=1,
        post_apply_capture_wait_seconds=1.0,
        max_application_steps=2,
        max_safe_fields_to_fill=1,
        approve_live_safe_fill=True,
        approved_live_field_id="email-field",
        approved_live_fill_preflight=approved_preflight_path,
        approved_live_fill_preflight_sha256=approved_preflight_sha256,
        time_budget_ms=300000.0,
        close_old_windows=False,
    )

    result = runner.run_speed_demo(args)

    assert result["status"] == "needs_work"
    assert result["application_stop_status"] == "blocked_need_user_or_gpt_decision"
    assert result["application_stop_reason"] == "risky_application_questions_require_user_or_gpt_decision"
    assert result["final_submissions"] == 0
    assert [step for step, _ in calls].count("continue_application_flow") == 2
    continue_args = [extra for step, extra in calls if step == "continue_application_flow"]
    for extra in continue_args:
        assert extra is not None
        assert "--fill-safe-fields" in extra
        assert extra[extra.index("--max-safe-fields-to-fill") + 1] == "1"
        assert extra[extra.index("--approved-live-field-id") + 1] == "email-field"
        assert "--allow-cover-letter-fill" not in extra
    assert "extract_final_review" not in [step for step, _ in calls]
    assert result["final_review_status"] == "not_attempted"


def test_finish_application_flow_read_only_inventory_runs_once_without_fill_flags(tmp_path) -> None:
    calls: list[tuple[str, list[str] | None]] = []

    def fake_run(step: str, extra: list[str] | None = None) -> dict:
        calls.append((step, extra))
        assert step == "continue_application_flow"
        return {
            "status": "read_only_inventory_ready",
            "read_only_inventory": True,
            "live_fill_attempted": False,
            "submit_clicks": 0,
            "final_submission_performed": False,
            "trace_paths": ["logs/observe.json"],
            "before_image": "artifacts/screenshots/form.png",
            "form_field_inventory": {
                "contract_version": "form_question_inventory_v1",
                "capture_id": "capture-1",
                "fields": [
                    {"field_id": "email", "label": "Email", "field_type": "email", "risk_class": "ordinary_field"},
                    {"field_id": "resume", "label": "Resume", "field_type": "file_upload", "risk_class": "unsupported_file_upload"},
                ],
                "questions": [],
                "danger_actions": [
                    {"action_id": "submit", "text": "Submit application", "risk_class": "final_submit"}
                ],
                "fill_attempted": False,
                "submit_attempted": False,
                "artifact_is_authorization": False,
            },
            "employer_question_inventory": {
                "contract_version": "employer_question_inventory_v1",
                "questions": [
                    {"question_id": "visa", "question_text": "Visa status", "risk_class": "needs_user_review"}
                ],
            },
            "application_answer_plan": {
                "contract_version": "application_answer_plan_v1",
                "answers": [{"field_id": "email", "policy": "auto_fill", "value": "must-not-leak@example.invalid"}],
            },
            "employer_question_answer_plan": {
                "contract_version": "employer_question_answer_plan_v1",
                "answers": [{"question_id": "visa", "policy": "needs_user_review", "planned_answer": "must-not-leak"}],
            },
            "next_allowed_steps": ["capture"],
        }

    args = argparse.Namespace(
        run_dir=tmp_path,
        read_only_inventory=True,
        max_application_steps=6,
        max_safe_fields_to_fill=5,
        time_budget_ms=300000.0,
    )

    result = runner._finish_application_flow(
        run_dir=tmp_path,
        started=runner.time.perf_counter(),
        args=args,
        run=fake_run,
        budget_exhausted=lambda **_kwargs: False,
        steps=[],
        job_attempts=[],
        result_scrolls=[],
    )

    assert calls == [("continue_application_flow", ["--read-only-inventory"])]
    assert result["status"] == "pass"
    assert result["stop_reason"] == "read_only_inventory_complete"
    assert result["live_fill_attempted"] is False
    assert result["submit_clicks"] == 0
    assert result["final_submissions"] == 0
    report_path = Path(result["read_only_inventory_report_path"])
    report_text = report_path.read_text(encoding="utf-8")
    assert "must-not-leak@example.invalid" not in report_text
    assert "must-not-leak" not in report_text
    report = json.loads(report_text)
    assert report["contract_version"] == "seek_read_only_inventory_checkpoint_v1"
    assert report["summary"]["field_count"] == 2
    assert report["summary"]["question_count"] == 1
    assert report["summary"]["unsupported_count"] == 1
    assert report["summary"]["final_action_count"] == 1
    assert [item["id"] for item in report["human_review"]["ordinary_fields"]] == ["email"]
    assert [item["id"] for item in report["human_review"]["unsupported_uploads"]] == ["resume"]
    assert [item["question_id"] for item in report["human_review"]["review_required_questions"]] == [
        "visa"
    ]
    assert report["human_review"]["sensitive_questions"] == []
    assert [item["id"] for item in report["human_review"]["final_actions"]] == ["submit"]
    assert report["human_review"]["interpretation"] == (
        "human-review buckets only; no field value is authorized or filled"
    )


def test_read_only_inventory_checkpoint_rejects_write_attempts() -> None:
    checkpoint = runner._build_read_only_inventory_checkpoint(
        {
            "status": "read_only_inventory_ready",
            "read_only_inventory": True,
            "form_field_inventory": {
                "contract_version": "form_question_inventory_v1",
                "fields": [],
                "questions": [],
                "danger_actions": [],
                "fill_attempted": True,
                "submit_attempted": True,
            },
            "safe_form_fill_attempt": {"fields_filled": 1, "final_submissions": 0},
        }
    )

    assert checkpoint["status"] == "needs_work"
    assert checkpoint["safety"]["live_fill_attempted"] is True
    assert checkpoint["safety"]["submit_clicks"] == 1


def test_live_safe_fill_preflight_projects_one_redacted_field_for_human_review() -> None:
    checkpoint = runner._build_read_only_inventory_checkpoint(
        {
            "status": "read_only_inventory_ready",
            "read_only_inventory": True,
            "before_image": "artifacts/screenshots/application-form.png",
            "trace_paths": ["logs/observe-form.json"],
            "form_field_inventory": {
                "contract_version": "form_question_inventory_v1",
                "fields": [
                    {
                        "field_id": "email",
                        "label": "Email",
                        "field_type": "email",
                        "risk_class": "ordinary_field",
                        "required": True,
                    }
                ],
                "questions": [],
                "danger_actions": [],
                "fill_attempted": False,
                "submit_attempted": False,
            },
            "application_answer_plan": {
                "contract_version": "application_answer_plan_v1",
                "answers": [
                    {
                        "field_id": "email",
                        "policy": "auto_fill",
                        "answer_source": "candidate_profile.email",
                        "value": "must-not-leak@example.invalid",
                    }
                ],
            },
        }
    )

    preflight = runner._build_live_safe_fill_preflight(
        checkpoint,
        field_id="email",
        current_flow_state={"state_type": "seek_easy_apply", "current_step": "Contact details"},
    )

    serialized = json.dumps(preflight, ensure_ascii=False)
    assert "must-not-leak@example.invalid" not in serialized
    assert preflight["contract_version"] == "seek_live_safe_fill_preflight_v1"
    assert preflight["status"] == "ready_for_human_review"
    assert preflight["approval_state"] == "awaiting_explicit_approval"
    assert preflight["field"] == {
        "id": "email",
        "label": "Email",
        "field_type": "email",
        "risk_class": "ordinary_field",
        "required": True,
    }
    assert preflight["value_evidence"]["answer_source"] == "candidate_profile.email"
    assert preflight["value_evidence"]["value_redacted"] is True
    assert preflight["value_evidence"]["value_length"] > 0
    assert preflight["value_evidence"]["value_hash"]
    assert preflight["safety"] == {
        "max_fields": 1,
        "cover_letter_fill_allowed": False,
        "continue_allowed": False,
        "final_submit_allowed": False,
        "artifact_is_authorization": False,
    }
    assert preflight["evidence"]["screenshot_paths"] == [
        "artifacts/screenshots/application-form.png"
    ]


def test_prepare_live_safe_fill_writes_preflight_without_fill_or_continue(tmp_path) -> None:
    calls: list[tuple[str, list[str] | None]] = []

    def fake_run(step: str, extra: list[str] | None = None) -> dict:
        calls.append((step, extra))
        assert step == "continue_application_flow"
        assert extra == ["--read-only-inventory"]
        return {
            "status": "read_only_inventory_ready",
            "read_only_inventory": True,
            "live_fill_attempted": False,
            "submit_clicks": 0,
            "final_submissions": 0,
            "before_image": "artifacts/screenshots/application-form.png",
            "trace_paths": ["logs/observe-form.json"],
            "application_flow_state": {
                "state_type": "seek_easy_apply",
                "current_step": "Contact details",
            },
            "form_field_inventory": {
                "contract_version": "form_question_inventory_v1",
                "fields": [
                    {
                        "field_id": "email",
                        "label": "Email",
                        "field_type": "email",
                        "risk_class": "ordinary_field",
                    }
                ],
                "questions": [],
                "danger_actions": [],
                "fill_attempted": False,
                "submit_attempted": False,
            },
            "application_answer_plan": {
                "contract_version": "application_answer_plan_v1",
                "answers": [
                    {
                        "field_id": "email",
                        "policy": "auto_fill",
                        "answer_source": "candidate_profile.email",
                        "value": "must-not-leak@example.invalid",
                    }
                ],
            },
        }

    args = argparse.Namespace(
        run_dir=tmp_path,
        read_only_inventory=False,
        prepare_live_safe_fill=True,
        prepare_live_safe_fill_field_id="email",
        approve_live_safe_fill=False,
        max_application_steps=6,
        time_budget_ms=300000.0,
    )

    result = runner._finish_application_flow(
        run_dir=tmp_path,
        started=runner.time.perf_counter(),
        args=args,
        run=fake_run,
        budget_exhausted=lambda **_kwargs: False,
        steps=[],
        job_attempts=[],
        result_scrolls=[],
    )

    assert calls == [("continue_application_flow", ["--read-only-inventory"])]
    assert result["status"] == "needs_work"
    assert result["stop_reason"] == "live_safe_fill_preflight_ready"
    assert result["live_fill_attempted"] is False
    assert result["submit_clicks"] == 0
    assert result["final_submissions"] == 0
    report_path = Path(result["live_safe_fill_preflight_path"])
    report_text = report_path.read_text(encoding="utf-8")
    assert "must-not-leak@example.invalid" not in report_text
    assert json.loads(report_text)["status"] == "ready_for_human_review"


def test_finish_application_flow_requires_explicit_live_fill_approval(tmp_path) -> None:
    calls: list[str] = []

    def forbidden_run(step: str, extra: list[str] | None = None) -> dict:
        calls.append(step)
        raise AssertionError(f"unexpected live-fill step: {step} {extra}")

    args = argparse.Namespace(
        run_dir=tmp_path,
        read_only_inventory=False,
        approve_live_safe_fill=False,
        max_application_steps=1,
        max_safe_fields_to_fill=1,
        time_budget_ms=300000.0,
    )

    result = runner._finish_application_flow(
        run_dir=tmp_path,
        started=runner.time.perf_counter(),
        args=args,
        run=forbidden_run,
        budget_exhausted=lambda **_kwargs: False,
        steps=[],
        job_attempts=[],
        result_scrolls=[],
    )

    assert calls == []
    assert result["status"] == "needs_work"
    assert result["stop_reason"] == "live_safe_fill_approval_required"
    assert result["live_fill_attempted"] is False
    assert result["submit_clicks"] == 0
    assert result["final_submissions"] == 0


def test_finish_application_flow_requires_explicit_live_field_id(tmp_path) -> None:
    calls: list[str] = []

    def forbidden_run(step: str, extra: list[str] | None = None) -> dict:
        calls.append(step)
        raise AssertionError(f"unexpected live-fill step: {step} {extra}")

    args = argparse.Namespace(
        run_dir=tmp_path,
        read_only_inventory=False,
        approve_live_safe_fill=True,
        approved_live_field_id=None,
        max_application_steps=1,
        max_safe_fields_to_fill=1,
        time_budget_ms=300000.0,
    )

    result = runner._finish_application_flow(
        run_dir=tmp_path,
        started=runner.time.perf_counter(),
        args=args,
        run=forbidden_run,
        budget_exhausted=lambda **_kwargs: False,
        steps=[],
        job_attempts=[],
        result_scrolls=[],
    )

    assert calls == []
    assert result["status"] == "needs_work"
    assert result["stop_reason"] == "approved_live_field_id_required"
    assert result["live_fill_attempted"] is False
    assert result["submit_clicks"] == 0
    assert result["final_submissions"] == 0


def test_finish_application_flow_requires_bound_approved_preflight(tmp_path) -> None:
    calls: list[str] = []

    def forbidden_run(step: str, extra: list[str] | None = None) -> dict:
        calls.append(step)
        raise AssertionError(f"unexpected live-fill step: {step} {extra}")

    args = argparse.Namespace(
        run_dir=tmp_path,
        read_only_inventory=False,
        approve_live_safe_fill=True,
        approved_live_field_id="email-field",
        approved_live_fill_preflight=None,
        approved_live_fill_preflight_sha256=None,
        max_application_steps=1,
        time_budget_ms=300000.0,
    )

    result = runner._finish_application_flow(
        run_dir=tmp_path,
        started=runner.time.perf_counter(),
        args=args,
        run=forbidden_run,
        budget_exhausted=lambda **_kwargs: False,
        steps=[],
        job_attempts=[],
        result_scrolls=[],
    )

    assert calls == []
    assert result["status"] == "needs_work"
    assert result["stop_reason"] == "approved_live_fill_preflight_required"
    assert result["live_fill_attempted"] is False
    assert result["submit_clicks"] == 0
    assert result["final_submissions"] == 0


def test_finish_application_flow_rejects_tampered_approved_preflight(tmp_path) -> None:
    path, expected_sha256 = _write_approved_live_fill_preflight(
        tmp_path,
        field_id="email-field",
    )
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    args = argparse.Namespace(
        run_dir=tmp_path,
        read_only_inventory=False,
        approve_live_safe_fill=True,
        approved_live_field_id="email-field",
        approved_live_fill_preflight=path,
        approved_live_fill_preflight_sha256=expected_sha256,
        max_application_steps=1,
        time_budget_ms=300000.0,
    )

    result = runner._finish_application_flow(
        run_dir=tmp_path,
        started=runner.time.perf_counter(),
        args=args,
        run=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected run")),
        budget_exhausted=lambda **_kwargs: False,
        steps=[],
        job_attempts=[],
        result_scrolls=[],
    )

    assert result["status"] == "needs_work"
    assert result["stop_reason"] == "approved_live_fill_preflight_invalid"
    assert result["approved_live_fill_preflight_validation"]["reason"] == "checksum_mismatch"


def test_cp14_apply_preflight_passes_only_with_fresh_capture_and_audit_evidence(tmp_path) -> None:
    capture_path = tmp_path / "pre-apply.png"
    capture_path.write_bytes(b"current-capture")
    trace_path = tmp_path / "match-report.json"
    trace_path.write_text("{}", encoding="utf-8")
    args = argparse.Namespace(
        read_only_inventory=True,
        continuous_session=True,
        approve_quick_apply_entry=True,
    )

    preflight = runner._build_cp14_apply_preflight(
        args=args,
        steps=[
            {"step_name": "bind_and_resize_verify", "status": "ok"},
            {"step_name": "match", "status": "ok", "report_path": str(trace_path)},
        ],
        capture_payload={"status": "ok", "after_image": str(capture_path)},
        match_payload={"status": "ok", "match_decision": {"decision": "strong_apply"}},
        runtime_preflight_payload={
            "runtime_health": {"success": True},
            "model_resource_preflight": {
                "status": "ready",
                "model_launch_allowed": True,
                "recommended_batch_size": 8,
                "gpu": {"available": True},
            },
            "model_status": {"status": "running"},
        },
    )

    assert preflight["status"] == "pass"
    assert all(check["passed"] for check in preflight["checks"])
    assert preflight["safety"]["live_fill_allowed"] is False
    assert preflight["safety"]["final_submit_allowed"] is False


def test_cp14_apply_preflight_fails_closed_when_evidence_is_missing(tmp_path) -> None:
    args = argparse.Namespace(
        read_only_inventory=False,
        continuous_session=False,
        approve_quick_apply_entry=True,
    )

    preflight = runner._build_cp14_apply_preflight(
        args=args,
        steps=[{"step_name": "bind_and_resize_verify", "status": "ok"}],
        capture_payload={"status": "ok", "after_image": str(tmp_path / "missing.png")},
        match_payload={"status": "ok", "match_decision": {"decision": "strong_apply"}},
        runtime_preflight_payload={
            "runtime_health": {"success": False},
            "model_resource_preflight": {
                "status": "degraded",
                "model_launch_allowed": False,
                "recommended_batch_size": 1,
                "gpu": {"available": False},
            },
            "model_status": {"status": "unreachable"},
        },
    )

    assert preflight["status"] == "failed"
    failed = {check["name"] for check in preflight["checks"] if not check["passed"]}
    assert failed == {
        "continuous_session_enabled",
        "read_only_inventory_enabled",
        "fresh_capture_exists",
        "trace_report_exists",
        "runtime_health_ready",
        "gpu_resource_capacity_ready",
        "locate_model_service_ready",
    }


def test_cp14_runtime_preflight_reuses_common_gpu_and_model_checks(monkeypatch) -> None:
    profile = {"profile_id": "vista_4b_transformers", "gpu_memory_gib": 10}
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(
        runner,
        "_get_json",
        lambda base_url, endpoint, timeout: calls.append(
            ("health", (base_url, endpoint, timeout))
        )
        or {"success": True, "data": {"status": "ok"}},
    )
    monkeypatch.setattr(
        runner,
        "profile_for_stage",
        lambda stage: calls.append(("profile", stage)) or profile,
    )
    monkeypatch.setattr(
        runner,
        "build_model_resource_preflight",
        lambda selected: calls.append(("resource", selected))
        or {
            "status": "ready",
            "model_launch_allowed": True,
            "recommended_batch_size": 2,
            "gpu": {"available": True},
        },
    )
    monkeypatch.setattr(
        runner,
        "check_model_server",
        lambda selected, timeout: calls.append(("model", (selected, timeout)))
        or {"status": "running"},
    )

    result = runner._collect_cp14_runtime_preflight(
        argparse.Namespace(base_url="http://127.0.0.1:8000", timeout=120.0)
    )

    assert result["runtime_health"]["success"] is True
    assert result["model_resource_preflight"]["recommended_batch_size"] == 2
    assert result["model_status"]["status"] == "running"
    assert calls == [
        ("health", ("http://127.0.0.1:8000", "/health", 5.0)),
        ("profile", "locate"),
        ("resource", profile),
        ("model", (profile, 2.0)),
    ]


def test_cp14_runtime_preflight_reports_health_failure_without_raising(monkeypatch) -> None:
    profile = {"profile_id": "vista_4b_transformers", "gpu_memory_gib": 10}
    monkeypatch.setattr(
        runner,
        "_get_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("runtime unavailable")),
    )
    monkeypatch.setattr(runner, "profile_for_stage", lambda _stage: profile)
    monkeypatch.setattr(
        runner,
        "build_model_resource_preflight",
        lambda _profile: {
            "status": "ready",
            "model_launch_allowed": True,
            "gpu": {"available": True},
        },
    )
    monkeypatch.setattr(
        runner,
        "check_model_server",
        lambda _profile, timeout: {"status": "running", "timeout": timeout},
    )

    result = runner._collect_cp14_runtime_preflight(
        argparse.Namespace(base_url="http://127.0.0.1:8000", timeout=120.0)
    )

    assert result["runtime_health"] == {
        "success": False,
        "error_code": "runtime_health_preflight_failed",
        "details": "runtime unavailable",
    }
    assert result["model_resource_preflight"]["status"] == "ready"
    assert result["model_status"]["status"] == "running"


def test_speed_demo_extracts_final_review_only_after_review_step(tmp_path, monkeypatch) -> None:
    cards = [{"title": "Graduate Software Engineer", "company": "Local Co", "location": "Auckland"}]
    calls: list[tuple[str, list[str] | None]] = []

    def fake_run_step(run_dir, step, extra=None):
        calls.append((step, extra))
        if step == "extract_cards":
            return {"status": "ok", "cards_payload": {"jobs": cards}}
        if step == "match":
            return {
                "status": "ok",
                "match_decision": {"decision": "strong_apply"},
                "detail": {"title": "Graduate Software Engineer", "company": "Local Co"},
            }
        if step == "execute_apply_entry":
            return {
                "status": "blocked_need_user_or_gpt_decision",
                "apply_entry": {"application_flow_started": True},
            }
        if step == "continue_application_flow":
            return {
                "status": "stopped_at_final_submit_visible",
                "next_allowed_steps": [],
                "application_flow_state": {
                    "current_step": "review_and_submit",
                    "state_type": "final_submit_visible",
                    "final_submission_performed": False,
                },
            }
        if step == "extract_final_review":
            extraction_path = tmp_path / "final_review_extraction.json"
            extraction_path.write_text(
                '{"status":"pass","final_submissions":0,"submit_clicks":0}',
                encoding="utf-8",
            )
            return {"status": "ok", "final_review_extraction_path": str(extraction_path)}
        return {"status": "ok"}

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(runner, "build_record_from_debug_run", lambda run_dir: {"steps": []})
    monkeypatch.setattr(runner, "build_seek_application_flow_artifact", lambda *args, **kwargs: {"contract_version": "test"})
    monkeypatch.setattr(runner, "load_step_reports", lambda run_dir: [])
    monkeypatch.setattr(
        runner,
        "build_demo_readiness_report",
        lambda **kwargs: {"status": "pass", "final_submissions": 0, "submit_clicks": 0},
    )

    approved_preflight_path, approved_preflight_sha256 = _write_approved_live_fill_preflight(
        tmp_path,
        field_id="email-field",
    )
    args = argparse.Namespace(
        run_dir=tmp_path,
        base_url="http://127.0.0.1:8000",
        timeout=1.0,
        url="https://nz.seek.com/graduate-jobs/in-All-Auckland",
        job_index=0,
        max_jobs=1,
        allow_maybe_apply=True,
        visible_jobs_per_page=1,
        max_result_scrolls=0,
        results_scroll_wheel_clicks=9,
        window_width=2560,
        window_height=1400,
        wheel_clicks=9,
        batch_max_captures=1,
        batch_stop_after_no_new_content=1,
        post_apply_capture_wait_seconds=1.0,
        max_application_steps=1,
        max_safe_fields_to_fill=1,
        approve_live_safe_fill=True,
        approved_live_field_id="email-field",
        approved_live_fill_preflight=approved_preflight_path,
        approved_live_fill_preflight_sha256=approved_preflight_sha256,
        time_budget_ms=300000.0,
        close_old_windows=False,
    )

    result = runner.run_speed_demo(args)

    assert result["status"] == "pass"
    assert calls[-1][0] == "extract_final_review"
    assert result["final_submissions"] == 0


def test_speed_demo_reads_detail_batch_without_full_verify_after_card_click(tmp_path, monkeypatch) -> None:
    cards = [{"title": "Graduate Developer", "company": "Local Co", "location": "Auckland"}]
    calls: list[tuple[str, list[str] | None]] = []

    def fake_run_step(run_dir, step, extra=None):
        calls.append((step, extra))
        if step == "extract_cards":
            return {"status": "ok", "cards_payload": {"jobs": cards}}
        if step == "match":
            return {"status": "ok", "match_decision": {"decision": "skip"}}
        return {"status": "ok"}

    monkeypatch.setattr(runner, "_run_step", fake_run_step)

    args = argparse.Namespace(
        run_dir=tmp_path / "speed",
        base_url="http://runtime.test",
        timeout=5.0,
        url="https://nz.seek.com/graduate-jobs/in-All-Auckland",
        job_index=0,
        max_jobs=1,
        allow_maybe_apply=False,
        visible_jobs_per_page=1,
        max_result_scrolls=0,
        results_scroll_wheel_clicks=9,
        window_width=2560,
        window_height=1400,
        wheel_clicks=9,
        batch_max_captures=3,
        batch_stop_after_no_new_content=2,
        post_apply_capture_wait_seconds=0.0,
        max_application_steps=0,
        max_safe_fields_to_fill=0,
        time_budget_ms=120000.0,
        close_old_windows=False,
    )

    result = runner.run_speed_demo(args)
    step_names = [step for step, _extra in calls]

    assert result["status"] == "needs_work"
    assert "execute_card" in step_names
    assert "read_detail_batch" in step_names
    assert "verify_detail" not in step_names
    assert step_names.index("execute_card") < step_names.index("read_detail_batch") < step_names.index("match")
    for _step, extra in calls:
        assert (extra or [])[:4] == [
            "--base-url",
            "http://runtime.test",
            "--timeout",
            "5.0",
        ]


def test_speed_demo_does_not_match_incomplete_detail(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_run_step(run_dir, step, extra=None):
        calls.append(step)
        if step == "extract_cards":
            return {
                "status": "ok",
                "cards_payload": {
                    "jobs": [{"title": "Graduate Developer", "company": "Local Co", "location": "Auckland"}]
                },
            }
        if step == "read_detail_batch":
            return {
                "status": "ok",
                "read_complete": False,
                "read_state": "max_captures",
                "stop_reason": "max_captures",
            }
        if step == "match":
            raise AssertionError("incomplete detail must not reach match")
        return {"status": "ok"}

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    args = argparse.Namespace(
        run_dir=tmp_path / "speed",
        base_url="http://runtime.test",
        timeout=5.0,
        url="https://nz.seek.com/graduate-jobs/in-All-Auckland",
        job_index=0,
        max_jobs=1,
        allow_maybe_apply=False,
        visible_jobs_per_page=1,
        max_result_scrolls=0,
        results_scroll_wheel_clicks=9,
        window_width=2560,
        window_height=1400,
        wheel_clicks=9,
        batch_max_captures=2,
        batch_stop_after_no_new_content=1,
        post_apply_capture_wait_seconds=0.0,
        max_application_steps=0,
        max_safe_fields_to_fill=0,
        time_budget_ms=120000.0,
        close_old_windows=False,
    )

    result = runner.run_speed_demo(args)

    assert "match" not in calls
    assert result["job_attempts"][0]["status"] == "skipped_detail_incomplete"
    assert result["job_attempts"][0]["reason"] == "max_captures"


class _ContinuousMemoryStore:
    def __init__(self, active: dict[str, str]) -> None:
        self.active = active

    def registry(self) -> dict:
        return {"active_by_interface": dict(self.active)}

    def load_active(self, interface_id: str) -> dict:
        return {"interface_id": interface_id}


def _continuous_args(tmp_path, **overrides):
    values = {
        "run_dir": tmp_path / "continuous-speed",
        "base_url": "http://runtime.test",
        "timeout": 5.0,
        "url": "https://nz.seek.com/software-engineer-jobs/in-All-Auckland",
        "job_index": 0,
        "max_jobs": 1,
        "allow_maybe_apply": False,
        "visible_jobs_per_page": 1,
        "max_result_scrolls": 0,
        "results_scroll_wheel_clicks": 9,
        "window_width": 2560,
        "window_height": 1400,
        "wheel_clicks": 9,
        "batch_max_captures": 2,
        "batch_stop_after_no_new_content": 1,
        "post_apply_capture_wait_seconds": 0.0,
        "max_application_steps": 2,
        "max_safe_fields_to_fill": 2,
        "time_budget_ms": 120000.0,
        "close_old_windows": False,
        "continuous_session": True,
        "resume_continuous_session": False,
        "approve_quick_apply_entry": False,
        "approve_live_safe_fill": False,
        "agent_suitability_review": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _evidenced_step_payload(tmp_path, step: str, payload: dict | None = None) -> dict:
    image = tmp_path / f"{step}.png"
    image.write_bytes(f"image:{step}".encode("utf-8"))
    trace = tmp_path / f"{step}.json"
    trace.write_text("{}", encoding="utf-8")
    return {
        "status": "ok",
        "after_image": str(image),
        "trace_paths": [str(trace)],
        **(payload or {}),
    }


def test_continuous_demo_waits_for_apply_entry_confirmation_before_click(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    cards = [{"title": "Graduate Software Engineer", "company": "Local Co", "location": "Auckland"}]

    def fake_run_step(run_dir, step, extra=None):
        calls.append(step)
        if step == "extract_cards":
            return _evidenced_step_payload(tmp_path, step, {"cards_payload": {"jobs": cards}})
        if step == "match":
            return {
                "status": "ok",
                "match_decision": {"decision": "strong_apply"},
                "detail": {"title": cards[0]["title"], "company": cards[0]["company"]},
            }
        return _evidenced_step_payload(tmp_path, step)

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(
        runner,
        "_build_reviewed_memory_store",
        lambda: _ContinuousMemoryStore({"seek_results_reviewed_current": "results-memory"}),
    )

    result = runner.run_speed_demo(_continuous_args(tmp_path))

    session = json.loads(Path(result["continuous_session_path"]).read_text(encoding="utf-8"))
    assert result["status"] == "awaiting_confirmation"
    assert result["stop_reason"] == "quick_apply_entry_confirmation_required"
    assert session["status"] == "awaiting_apply_entry_confirmation"
    assert session["pending_apply_confirmation"]["job_title"] == cards[0]["title"]
    assert "execute_apply_entry" not in calls


def test_cp14_live_uat_stops_before_apply_when_preflight_capture_is_missing(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    capture_count = 0
    cards = [{"title": "Graduate Software Engineer", "company": "Local Co", "location": "Auckland"}]

    def fake_run_step(run_dir, step, extra=None):
        nonlocal capture_count
        calls.append(step)
        if step == "extract_cards":
            return _evidenced_step_payload(tmp_path, step, {"cards_payload": {"jobs": cards}})
        if step == "read_detail_batch":
            return _evidenced_step_payload(tmp_path, step, {"read_complete": True})
        if step == "match":
            return _evidenced_step_payload(
                tmp_path,
                step,
                {
                    "match_decision": {"decision": "strong_apply"},
                    "detail": {"title": cards[0]["title"], "company": cards[0]["company"]},
                },
            )
        if step == "capture":
            capture_count += 1
            if capture_count == 2:
                payload = _evidenced_step_payload(tmp_path, "preflight-capture")
                Path(payload["after_image"]).unlink()
                return payload
        return _evidenced_step_payload(tmp_path, step)

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(
        runner,
        "_collect_cp14_runtime_preflight",
        lambda _args: {
            "runtime_health": {"success": True},
            "model_resource_preflight": {
                "status": "ready",
                "model_launch_allowed": True,
                "gpu": {"available": True},
            },
            "model_status": {"status": "running"},
        },
    )
    monkeypatch.setattr(
        runner,
        "_build_reviewed_memory_store",
        lambda: _ContinuousMemoryStore({"seek_results_reviewed_current": "results-memory"}),
    )

    result = runner.run_speed_demo(
        _continuous_args(
            tmp_path,
            approve_quick_apply_entry=True,
            read_only_inventory=True,
            cp14_live_uat=True,
        )
    )

    assert result["status"] == "needs_work"
    assert result["stop_reason"] == "cp14_apply_preflight_failed"
    assert "execute_apply_entry" not in calls
    assert Path(result["cp14_preflight_report_path"]).is_file()


def test_cp14_live_uat_rehearsal_enters_apply_once_then_reads_inventory_without_fill(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, list[str]]] = []
    cards = [{"title": "Graduate Software Engineer", "company": "Local Co", "location": "Auckland"}]

    def fake_run_step(run_dir, step, extra=None):
        step_args = list(extra or [])
        calls.append((step, step_args))
        payload: dict = {"step_name": step}
        if step == "extract_cards":
            payload["cards_payload"] = {"jobs": cards}
        elif step == "read_detail_batch":
            payload["read_complete"] = True
        elif step == "match":
            payload.update(
                {
                    "match_decision": {"decision": "strong_apply"},
                    "detail": {"title": cards[0]["title"], "company": cards[0]["company"]},
                }
            )
        elif step == "execute_apply_entry":
            payload.update(
                {
                    "status": "blocked_need_user_or_gpt_decision",
                    "apply_entry": {
                        "application_flow_started": True,
                        "state_type": "application_form",
                        "current_step": "personal_details",
                    },
                }
            )
        elif step == "continue_application_flow":
            payload.update(
                {
                    "status": "read_only_inventory_ready",
                    "read_only_inventory": True,
                    "live_fill_attempted": False,
                    "submit_clicks": 0,
                    "final_submission_performed": False,
                    "form_field_inventory": {
                        "contract_version": "form_question_inventory_v1",
                        "fields": [{"field_id": "first_name", "policy": "allowed"}],
                        "questions": [],
                        "danger_actions": [{"label": "Submit application"}],
                        "fill_attempted": False,
                        "submit_attempted": False,
                        "artifact_is_authorization": False,
                    },
                    "employer_question_inventory": {
                        "contract_version": "employer_question_inventory_v1",
                        "questions": [],
                    },
                    "application_answer_plan": {"answers": []},
                    "employer_question_answer_plan": {"answers": []},
                    "next_allowed_steps": ["capture"],
                }
            )
        return _evidenced_step_payload(tmp_path, step, payload)

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(
        runner,
        "_collect_cp14_runtime_preflight",
        lambda _args: {
            "runtime_health": {"success": True},
            "model_resource_preflight": {
                "status": "ready",
                "resource_mode": "normal",
                "model_launch_allowed": True,
                "recommended_batch_size": 4,
                "reason_codes": [],
                "gpu": {"available": True},
            },
            "model_status": {"status": "running", "model_id": "locate-test"},
        },
    )
    monkeypatch.setattr(
        runner,
        "_build_reviewed_memory_store",
        lambda: _ContinuousMemoryStore(
            {
                "seek_results_reviewed_current": "results-memory",
                "seek_quick_apply_personal_details": "quick-apply-memory",
            }
        ),
    )

    result = runner.run_speed_demo(
        _continuous_args(
            tmp_path,
            approve_quick_apply_entry=True,
            read_only_inventory=True,
            cp14_live_uat=True,
        )
    )

    step_names = [step for step, _ in calls]
    continue_args = [args for step, args in calls if step == "continue_application_flow"]
    assert result["status"] == "pass"
    assert result["stop_reason"] == "read_only_inventory_complete"
    assert step_names.count("execute_apply_entry") == 1
    assert step_names.count("continue_application_flow") == 1
    assert continue_args == [["--base-url", "http://runtime.test", "--timeout", "5.0", "--read-only-inventory"]]
    assert not any(
        flag in arg
        for _, args in calls
        for arg in args
        for flag in ("--fill-safe-fields", "--allow-cover-letter-fill", "--continue", "--submit")
    )
    assert result["live_fill_attempted"] is False
    assert result["submit_clicks"] == 0
    assert result["final_submissions"] == 0
    assert Path(result["cp14_preflight_report_path"]).is_file()
    assert Path(result["read_only_inventory_report_path"]).is_file()


def test_continuous_demo_pauses_unknown_quick_apply_before_fill(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    cards = [{"title": "Graduate Software Engineer", "company": "Local Co", "location": "Auckland"}]

    def fake_run_step(run_dir, step, extra=None):
        calls.append(step)
        if step == "extract_cards":
            return _evidenced_step_payload(tmp_path, step, {"cards_payload": {"jobs": cards}})
        if step == "match":
            return {
                "status": "ok",
                "match_decision": {"decision": "strong_apply"},
                "detail": {"title": cards[0]["title"], "company": cards[0]["company"]},
            }
        if step == "execute_apply_entry":
            return _evidenced_step_payload(
                tmp_path,
                step,
                {
                    "status": "blocked_need_user_or_gpt_decision",
                    "apply_entry": {
                        "application_flow_started": True,
                        "state_type": "application_form",
                        "current_step": "answer_employer_questions",
                    },
                },
            )
        return _evidenced_step_payload(tmp_path, step)

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(
        runner,
        "_build_reviewed_memory_store",
        lambda: _ContinuousMemoryStore({"seek_results_reviewed_current": "results-memory"}),
    )

    result = runner.run_speed_demo(
        _continuous_args(
            tmp_path,
            approve_quick_apply_entry=True,
        )
    )

    session = json.loads(Path(result["continuous_session_path"]).read_text(encoding="utf-8"))
    checkpoint = json.loads(Path(result["continuous_checkpoint_path"]).read_text(encoding="utf-8"))
    assert result["status"] == "paused_for_learning"
    assert result["stop_reason"] == "reviewed_quick_apply_memory_required"
    assert session["pending_learning"]["interface_id"] == "seek_quick_apply_answer_employer_questions"
    assert checkpoint["phase"] == "quick_apply"
    assert "continue_application_flow" not in calls


def test_continuous_demo_resumes_same_quick_apply_after_memory_publish(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    cards = [{"title": "Graduate Software Engineer", "company": "Local Co", "location": "Auckland"}]
    memory_store = _ContinuousMemoryStore({"seek_results_reviewed_current": "results-memory"})

    def fake_run_step(run_dir, step, extra=None):
        calls.append(step)
        if step == "extract_cards":
            return _evidenced_step_payload(tmp_path, step, {"cards_payload": {"jobs": cards}})
        if step == "match":
            return {
                "status": "ok",
                "match_decision": {"decision": "strong_apply"},
                "detail": {"title": cards[0]["title"], "company": cards[0]["company"]},
            }
        if step == "execute_apply_entry":
            return _evidenced_step_payload(
                tmp_path,
                step,
                {
                    "status": "blocked_need_user_or_gpt_decision",
                    "apply_entry": {
                        "application_flow_started": True,
                        "state_type": "application_form",
                        "current_step": "answer_employer_questions",
                    },
                },
            )
        if step == "continue_application_flow":
            return _evidenced_step_payload(
                tmp_path,
                step,
                {
                    "status": "stopped_at_final_submit_visible",
                    "next_allowed_steps": [],
                    "application_flow_state": {
                        "current_step": "review_and_submit",
                        "state_type": "final_submit_visible",
                        "final_submit_visible": True,
                        "final_submission_performed": False,
                    },
                },
            )
        if step == "extract_final_review":
            extraction_path = tmp_path / "continuous_final_review.json"
            extraction_path.write_text(
                '{"status":"pass","final_submissions":0,"submit_clicks":0}',
                encoding="utf-8",
            )
            return _evidenced_step_payload(
                tmp_path,
                step,
                {
                    "final_review_extraction_path": str(extraction_path),
                    "final_submissions": 0,
                    "submit_clicks": 0,
                },
            )
        return _evidenced_step_payload(tmp_path, step)

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(runner, "_build_reviewed_memory_store", lambda: memory_store)
    monkeypatch.setattr(runner, "build_record_from_debug_run", lambda run_dir: {"steps": [], "final_submissions": 0})
    monkeypatch.setattr(
        runner,
        "build_seek_application_flow_artifact",
        lambda *args, **kwargs: {"contract_version": "test"},
    )
    monkeypatch.setattr(runner, "load_step_reports", lambda run_dir: [])
    monkeypatch.setattr(
        runner,
        "build_demo_readiness_report",
        lambda **kwargs: {"status": "pass", "final_submissions": 0, "submit_clicks": 0},
    )

    first = runner.run_speed_demo(
        _continuous_args(
            tmp_path,
            approve_quick_apply_entry=True,
        )
    )
    assert first["status"] == "paused_for_learning"

    memory_store.active["seek_quick_apply_answer_employer_questions"] = "questions-memory"
    approved_preflight_path, approved_preflight_sha256 = _write_approved_live_fill_preflight(
        tmp_path,
        field_id="email-field",
    )
    second_call_start = len(calls)
    second = runner.run_speed_demo(
        _continuous_args(
            tmp_path,
                approve_quick_apply_entry=True,
                approve_live_safe_fill=True,
                approved_live_field_id="email-field",
                approved_live_fill_preflight=approved_preflight_path,
                approved_live_fill_preflight_sha256=approved_preflight_sha256,
                resume_continuous_session=True,
        )
    )

    resumed_calls = calls[second_call_start:]
    session = json.loads(Path(second["continuous_session_path"]).read_text(encoding="utf-8"))
    assert "open" not in resumed_calls
    assert "extract_cards" not in resumed_calls
    assert resumed_calls[0] == "continue_application_flow"
    assert second["status"] == "safe_stop"
    assert second["stop_reason"] == "final_submit_visible"
    assert second["final_submissions"] == 0
    assert second["submit_clicks"] == 0
    assert session["status"] == "safe_stop"
    assert session["safety"]["final_submit_executed"] is False


def test_continuous_demo_resumes_after_user_confirms_apply_entry(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    cards = [{"title": "Graduate Software Engineer", "company": "Local Co", "location": "Auckland"}]
    memory_store = _ContinuousMemoryStore({"seek_results_reviewed_current": "results-memory"})

    def fake_run_step(run_dir, step, extra=None):
        calls.append(step)
        if step == "extract_cards":
            return _evidenced_step_payload(tmp_path, step, {"cards_payload": {"jobs": cards}})
        if step == "match":
            return {
                "status": "ok",
                "match_decision": {"decision": "strong_apply"},
                "detail": {"title": cards[0]["title"], "company": cards[0]["company"]},
            }
        if step == "execute_apply_entry":
            return _evidenced_step_payload(
                tmp_path,
                step,
                {
                    "status": "blocked_need_user_or_gpt_decision",
                    "apply_entry": {
                        "application_flow_started": True,
                        "state_type": "application_form",
                        "current_step": "answer_employer_questions",
                    },
                },
            )
        return _evidenced_step_payload(tmp_path, step)

    monkeypatch.setattr(runner, "_run_step", fake_run_step)
    monkeypatch.setattr(runner, "_build_reviewed_memory_store", lambda: memory_store)

    first = runner.run_speed_demo(_continuous_args(tmp_path))
    assert first["status"] == "awaiting_confirmation"

    second_call_start = len(calls)
    second = runner.run_speed_demo(
        _continuous_args(
            tmp_path,
            approve_quick_apply_entry=True,
            resume_continuous_session=True,
        )
    )

    resumed_calls = calls[second_call_start:]
    session = json.loads(Path(second["continuous_session_path"]).read_text(encoding="utf-8"))
    assert resumed_calls == ["execute_apply_entry"]
    assert second["status"] == "paused_for_learning"
    assert session["status"] == "paused_for_learning"
    assert session["pending_learning"]["interface_id"] == "seek_quick_apply_answer_employer_questions"
