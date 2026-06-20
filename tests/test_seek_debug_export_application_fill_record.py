from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.seek.application import build_seek_application_final_review_audit


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seek_debug_export_application_fill_record.py"
spec = importlib.util.spec_from_file_location("seek_debug_export_application_fill_record", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def _write_report(run_dir: Path, index: int, name: str, payload: dict) -> Path:
    step_dir = run_dir / f"step_{index:03d}_{name}"
    step_dir.mkdir(parents=True)
    path = step_dir / "step_report.json"
    payload = {"step_index": index, "step_name": name, **payload}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_exports_debug_run_with_no_employer_questions_to_auditable_record(tmp_path: Path) -> None:
    run_dir = tmp_path / "seek_debug"
    review = tmp_path / "review.png"
    cover_trace = tmp_path / "type-text.json"
    review.write_bytes(b"png")
    cover_trace.write_text("{}", encoding="utf-8")
    state = {
        "detail": {
            "job_id": "seek_job_plexure",
            "title": "Software Engineers",
            "company": "Plexure Limited",
            "location": "Auckland CBD, Auckland (Hybrid)",
        },
        "current_job": {"job_id": "seek_job_card", "title": "Software Engineers", "company": "Plexure Limited"},
    }
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    _write_report(
        run_dir,
        1,
        "match",
        {
            "status": "ok",
            "detail": state["detail"],
            "match_decision": {"decision": "maybe_apply", "job_id": "seek_job_plexure", "title": "Software Engineers"},
        },
    )
    _write_report(
        run_dir,
        2,
        "continue_application_flow",
        {
            "status": "filled_until_review",
            "cover_letter_draft": {"status": "draft_only_not_pasted", "draft": "Dear Hiring Team,\n\nPlexure cover letter."},
            "safe_form_fill_attempt": {
                "status": "filled_until_review",
                "fields_filled": 1,
                "field_results": [
                    {
                        "filled": True,
                        "type_text_response": {"success": True, "trace_path": str(cover_trace)},
                    }
                ],
            },
            "after_image": str(tmp_path / "choose.png"),
            "trace_paths": [str(tmp_path / "observe.json")],
        },
    )
    _write_report(
        run_dir,
        3,
        "continue_application_flow",
        {
            "status": "blocked_need_user_or_gpt_decision",
            "after_image": str(review),
            "application_flow_state": {
                "contract_version": "seek_application_flow_state_v1",
                "current_step": "review_and_submit",
                "state_type": "final_submit_visible",
                "final_submit_visible_blocker": {"blocked": True, "matched_terms": ["submit application"]},
                "application_form_inventory": {
                    "actions": [
                        {
                            "text": "https://nz.seek.com/job/92763500/apply/review?sol=test",
                            "role": "input",
                        }
                    ]
                },
            },
        },
    )

    record = exporter.build_record_from_debug_run(run_dir, created_at="2026-06-20T00:00:00Z")
    audit = build_seek_application_final_review_audit(record, base_dir=Path.cwd(), created_at="2026-06-20T00:00:00Z")

    assert record["contract_version"] == "seek_application_fill_record_v1"
    assert record["job_title"] == "Software Engineers"
    assert record["apply_url"] == "https://nz.seek.com/job/92763500/apply/review?sol=test"
    assert record["employer_question_total"] == 0
    assert record["filled_content"]["employer_questions"] == []
    assert record["filled_fields"][1]["field"] == "cover_letter"
    assert record["final_submissions"] == 0
    assert audit["decision"] == "pass_stopped_before_final_submit"
    assert audit["checks"]["employer_questions_answered"] == "0/0"


def test_debug_export_cli_writes_utf8_record(tmp_path: Path, capsys) -> None:
    run_dir = tmp_path / "seek_debug"
    run_dir.mkdir()
    review = tmp_path / "review.png"
    cover_trace = tmp_path / "type-text.json"
    review.write_bytes(b"png")
    cover_trace.write_text("{}", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps({"detail": {"title": "软件工程师", "company": "Plexure Limited"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_report(
        run_dir,
        1,
        "continue_application_flow",
        {
            "status": "filled_until_review",
            "cover_letter_draft": {"status": "draft_only_not_pasted", "draft": "Dear Hiring Team,\n\n中文测试。"},
            "safe_form_fill_attempt": {
                "status": "filled_until_review",
                "fields_filled": 1,
                "field_results": [{"filled": True, "type_text_response": {"trace_path": str(cover_trace)}}],
            },
        },
    )
    _write_report(
        run_dir,
        2,
        "continue_application_flow",
        {
            "after_image": str(review),
            "application_flow_state": {
                "current_step": "review_and_submit",
                "final_submit_visible_blocker": {"blocked": True},
            },
        },
    )
    out = tmp_path / "application_fill_record.json"

    exit_code = exporter.main(["--run-dir", str(run_dir), "--out", str(out)])
    printed = json.loads(capsys.readouterr().out)
    written_text = out.read_text(encoding="utf-8")

    assert exit_code == 0
    assert printed["success"] is True
    assert "软件工程师" in written_text


def test_exports_manual_employer_questions_and_review_boundary(tmp_path: Path) -> None:
    run_dir = tmp_path / "seek_debug"
    run_dir.mkdir()
    review = tmp_path / "review.png"
    cover_trace = tmp_path / "type-text.json"
    review.write_bytes(b"png")
    cover_trace.write_text("{}", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "current_job": {
                    "job_id": "seek_job_92822270",
                    "title": "Software Engineer (Business Systems)",
                    "company": "Sourced | IT Recruitment Specialists",
                    "source_url": "https://nz.seek.com/job/92822270",
                },
                "detail": {
                    "job_id": "seek_job_92822270",
                    "title": "Software Engineer (Business Systems)",
                    "company": "Sourced | IT Recruitment Specialists",
                    "detail_url": "https://nz.seek.com/job/92822270?ref=recom-homepage",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_report(
        run_dir,
        17,
        "continue_application_flow",
        {
            "status": "continued_to_next_step",
            "cover_letter_draft": {"status": "draft_only_not_pasted", "draft": "Dear Hiring Team,\n\nSourced cover letter."},
            "safe_form_fill_attempt": {
                "status": "filled_until_review",
                "fields_filled": 1,
                "field_results": [{"filled": True, "type_text_response": {"trace_path": str(cover_trace)}}],
            },
            "after_image": str(tmp_path / "questions.png"),
        },
    )
    _write_report(
        run_dir,
        18,
        "continue_application_flow",
        {
            "status": "continued_to_next_step",
            "after_image": str(tmp_path / "review-top.png"),
            "application_flow_state": {
                "current_step": "review_and_submit",
                "final_submit_visible_blocker": {"blocked": False},
            },
        },
    )
    (run_dir / "step_018_answer_employer_questions_manual.json").write_text(
        json.dumps(
            {
                "contract_version": "seek_employer_questions_manual_debug_v1",
                "final_submissions": 0,
                "answers": [
                    {
                        "question": "Right to work in New Zealand",
                        "answer": "I have a graduate temporary work visa (e.g. post study work visa - open)",
                        "evidence": "candidate_profile_v1.work_rights_summary",
                    },
                    {
                        "question": "Do you have at least 1-2 years of experience in web application development?",
                        "answer": "Yes",
                        "evidence": "candidate_profile_v1.experience_summary",
                    },
                    {
                        "question": "Are you comfortable reading, altering and designing solutions with Java, AngularJS, React, Vue, MySQL?",
                        "answer": "Yes",
                        "evidence": "candidate_profile_v1.skills",
                    },
                    {
                        "question": "Can you start immediately or within 1-2 weeks?",
                        "answer": "Yes, I can start immediately or within 1-2 weeks.",
                        "evidence": "candidate_profile_v1.work_rights_summary",
                    },
                ],
                "captures": [{"label": "after_continue", "image_path": str(tmp_path / "profile.png")}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "step_019_review_submit_boundary.json").write_text(
        json.dumps(
            {
                "contract_version": "seek_review_submit_stop_before_submit_v1",
                "final_submissions": 0,
                "captures": [{"label": "after_review_scroll", "image_path": str(review)}],
                "texts": [{"text": "https://nz.seek.com/job/92822270/apply/review?sol=test"}, {"text": "Submit application"}],
                "final_submit_text_visible": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    record = exporter.build_record_from_debug_run(run_dir, created_at="2026-06-20T00:00:00Z")
    audit = build_seek_application_final_review_audit(record, base_dir=Path.cwd(), created_at="2026-06-20T00:00:00Z")

    assert record["status"] == "stopped_at_review_before_submit"
    assert record["stage"] == "review_before_submit"
    assert record["employer_question_total"] == 4
    assert record["filled_content"]["employer_questions"][0]["answer"].startswith("I have a graduate")
    assert record["evidence"]["final_submit_text_visible"] is True
    assert record["evidence"]["review_before_submit_screenshot"] == str(review.resolve())
    assert record["known_issues_from_run"] == [
        "Earlier Continue targeting selected a right-edge floating browser/plugin widget; the runner now rejects right-edge/header/bottom-edge Continue points before execution."
    ]
    assert audit["decision"] == "pass_stopped_before_final_submit"
    assert audit["checks"]["employer_questions_answered"] == "4/4"


def test_exports_automated_employer_questions_from_fill_attempt(tmp_path: Path) -> None:
    run_dir = tmp_path / "seek_debug"
    run_dir.mkdir()
    review = tmp_path / "review.png"
    cover_trace = tmp_path / "type-text.json"
    review.write_bytes(b"png")
    cover_trace.write_text("{}", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "detail": {
                    "job_id": "seek_job_92822270",
                    "title": "Software Engineer (Business Systems)",
                    "company": "Sourced | IT Recruitment Specialists",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    _write_report(
        run_dir,
        1,
        "continue_application_flow",
        {
            "status": "continued_to_next_step",
            "cover_letter_draft": {"draft": "Dear Hiring Team,\n\nSourced cover letter."},
            "safe_form_fill_attempt": {
                "status": "filled_until_review",
                "fields_filled": 1,
                "field_results": [{"filled": True, "type_text_response": {"trace_path": str(cover_trace)}}],
            },
        },
    )
    _write_report(
        run_dir,
        2,
        "continue_application_flow",
        {
            "status": "continued_to_next_step",
            "employer_question_fill_attempt": {
                "status": "filled_until_review",
                "answered_count": 4,
                "final_submissions": 0,
            },
            "employer_question_answer_plan": {
                "answers": [
                    {
                        "question_text": "Which statement best describes your right to work in New Zealand?",
                        "planned_answer": "I have a graduate temporary work visa (e.g. post study work visa - open)",
                        "answer_source": "candidate_profile_v1.work_rights_summary",
                        "evidence": "Post-study Open Work Visa",
                    },
                    {
                        "question_text": "Do you have at least 1-2 years of experience in web application development?",
                        "planned_answer": "Yes",
                        "answer_source": "candidate_profile_v1.experience_summary",
                        "evidence": "Frontend and backend project experience",
                    },
                    {
                        "question_text": "Are you comfortable with Java, React, Vue and MySQL?",
                        "planned_answer": "Yes",
                        "answer_source": "candidate_profile_v1.skills",
                        "evidence": "JavaScript; React; SQL",
                    },
                    {
                        "question_text": "Can you start immediately or within 1-2 weeks?",
                        "planned_answer": "Yes, I can start immediately or within 1-2 weeks.",
                        "answer_source": "candidate_profile_v1.availability_or_work_rights_summary",
                        "evidence": "Open work visa",
                    },
                ]
            },
        },
    )
    _write_report(
        run_dir,
        3,
        "continue_application_flow",
        {
            "status": "continued_to_next_step",
            "after_image": str(review),
            "final_submission_performed": False,
            "application_flow_state": {
                "current_step": "review_and_submit",
                "final_submit_visible_blocker": {"blocked": False},
            },
        },
    )

    record = exporter.build_record_from_debug_run(run_dir, created_at="2026-06-20T00:00:00Z")
    audit = build_seek_application_final_review_audit(record, base_dir=Path.cwd(), created_at="2026-06-20T00:00:00Z")

    assert record["status"] == "stopped_at_review_before_submit"
    assert record["stage"] == "review_before_submit"
    assert record["employer_question_total"] == 4
    assert record["filled_content"]["employer_questions"][3]["answer"] == "Yes, I can start immediately or within 1-2 weeks."
    assert record["evidence"]["employer_questions_report"].endswith("step_report.json")
    assert audit["decision"] == "pass_stopped_before_final_submit"
    assert audit["checks"]["employer_questions_answered"] == "4/4"


def test_export_prefers_cover_letter_revision_report(tmp_path: Path) -> None:
    run_dir = tmp_path / "seek_debug"
    run_dir.mkdir()
    old_trace = tmp_path / "old-type-text.json"
    new_trace = tmp_path / "new-type-text.json"
    review = tmp_path / "review.png"
    review_after_save = tmp_path / "review-after-save.png"
    old_trace.write_text("{}", encoding="utf-8")
    new_trace.write_text("{}", encoding="utf-8")
    review.write_bytes(b"png")
    review_after_save.write_bytes(b"png")
    _write_report(
        run_dir,
        1,
        "continue_application_flow",
        {
            "cover_letter_draft": {"draft": "Old duplicated cover letter."},
            "safe_form_fill_attempt": {
                "status": "filled_until_review",
                "fields_filled": 1,
                "field_results": [{"filled": True, "type_text_response": {"trace_path": str(old_trace)}}],
            },
        },
    )
    _write_report(
        run_dir,
        2,
        "continue_application_flow",
        {
            "after_image": str(review),
            "final_submission_performed": False,
            "application_flow_state": {"current_step": "review_and_submit"},
        },
    )
    (run_dir / "step_003_cover_letter_revision.json").write_text(
        json.dumps(
            {
                "contract_version": "seek_cover_letter_revision_v1",
                "cover_letter": "Revised cover letter.",
                "type_text_trace_path": str(new_trace),
                "captures": [{"label": "after_save", "image_path": str(review_after_save)}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    record = exporter.build_record_from_debug_run(run_dir, created_at="2026-06-20T00:00:00Z")

    assert record["filled_content"]["cover_letter"] == "Revised cover letter."
    assert record["filled_fields"][1]["value"] == "Revised cover letter."
    assert record["evidence"]["cover_letter_type_text_trace"] == str(new_trace.resolve())
    assert record["evidence"]["review_before_submit_screenshot"] == str(review_after_save.resolve())
