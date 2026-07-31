import argparse
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
    _station_internal_application_started,
)


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
    for _step, extra in calls:
        assert (extra or [])[:4] == [
            "--base-url",
            "http://runtime.test",
            "--timeout",
            "5.0",
        ]


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
