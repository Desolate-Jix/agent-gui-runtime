import argparse

import scripts.seek_speed_demo_runner as runner

from scripts.seek_speed_demo_runner import (
    _apply_decision_allowed,
    _card_needs_scroll_into_safer_position,
    _card_prefilter_decision,
    _cards_fingerprint,
    _clamp_scroll_wheel_clicks,
    _external_apply_flow_started,
    _station_internal_application_started,
)


def test_card_prefilter_skips_summer_or_internship_cards() -> None:
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

    assert _card_prefilter_decision(summer)["decision"] == "skip"
    assert _card_prefilter_decision(internship)["decision"] == "skip"


def test_card_prefilter_keeps_regular_software_engineer_card() -> None:
    card = {
        "title": "Software Engineer",
        "company": "Absolute IT Limited",
        "classification": "Engineering - Software",
    }

    assert _card_prefilter_decision(card, learned_fast_mode=False) == {"decision": "keep", "reason": "needs_detail_read"}


def test_learned_fast_card_prefilter_keeps_generic_but_skips_senior_cards() -> None:
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

    assert _card_prefilter_decision(generic) == {"decision": "keep", "reason": "needs_detail_read"}
    assert _card_prefilter_decision(senior)["decision"] == "skip"
    assert _card_prefilter_decision(graduate) == {"decision": "keep", "reason": "needs_detail_read"}


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


def test_speed_demo_recovers_to_seek_after_external_ats_and_continues(tmp_path, monkeypatch) -> None:
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
                    "state_type": "third_party_ats",
                    "stop_reason": "third_party_ats_requires_user_review",
                    "risk_flags": ["third_party_ats"],
                }
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
    assert result["job_attempts"][0]["apply_entry_state_type"] == "third_party_ats"
    assert result["job_attempts"][0]["external_apply_recovery"]["status"] == "ok"
    assert result["job_attempts"][1]["status"] == "application_started"
    assert [step for step, _ in calls].count("open") == 2
    assert [step for step, _ in calls].count("execute_apply_entry") == 2
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
        time_budget_ms=300000.0,
        close_old_windows=False,
    )

    result = runner.run_speed_demo(args)

    assert result["status"] == "needs_work"
    assert result["application_stop_status"] == "blocked_need_user_or_gpt_decision"
    assert result["application_stop_reason"] == "risky_application_questions_require_user_or_gpt_decision"
    assert result["final_submissions"] == 0
    assert [step for step, _ in calls].count("continue_application_flow") == 2
    assert "extract_final_review" not in [step for step, _ in calls]
    assert result["final_review_status"] == "not_attempted"


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
