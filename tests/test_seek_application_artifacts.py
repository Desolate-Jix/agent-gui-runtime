from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.seek.application_artifacts import build_seek_application_flow_artifact


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seek_export_application_flow_artifact.py"
spec = importlib.util.spec_from_file_location("seek_export_application_flow_artifact", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def _record() -> dict:
    return {
        "contract_version": "seek_application_fill_record_v1",
        "job": {
            "job_id": "seek_job_1",
            "title": "Intermediate Engineer - AI Automation & Integration",
            "company": "Example Co",
            "application_url": "https://nz.seek.com/job/1/apply/review",
        },
        "filled_content": {
            "resume": "WENQING JI.pdf (SEEK default/selected resume)",
            "cover_letter": "Dear Hiring Team,\n\nI am interested in this role.\n\nKind regards,\nWenqing Ji",
            "employer_questions": [
                {
                    "question": "Which statement best describes your right to work?",
                    "answer": "I have a graduate temporary work visa",
                    "evidence": "candidate_profile.work_rights_summary",
                },
                {
                    "question": "How much notice are you required to give?",
                    "answer": "None, I'm ready to go now",
                    "evidence": "candidate_profile.availability_summary",
                },
            ],
            "seek_profile_mutation": "none",
        },
        "evidence": {
            "screenshots": ["choose.png", "questions.png", "profile.png", "review.png"],
            "action_traces": ["type-text.json"],
            "vision_traces": ["observe.json"],
            "review_before_submit_screenshot": "review.png",
            "cover_letter_type_text_trace": "type-text.json",
        },
        "known_issues_from_run": [
            "Cover-letter safe-fill path still needs refinement; direct framework type_text was used after coordinate/focus verification."
        ],
        "job_id": "seek_job_1",
        "job_title": "Intermediate Engineer - AI Automation & Integration",
        "apply_url": "https://nz.seek.com/job/1/apply/review",
        "stage": "review_before_submit",
        "submit_clicks": 0,
        "final_submissions": 0,
        "employer_question_total": 2,
    }


def _audit() -> dict:
    return {
        "contract_version": "seek_application_final_review_audit_v1",
        "decision": "pass_stopped_before_final_submit",
        "checks": {
            "final_submissions": 0,
            "submit_clicks": 0,
            "resume_kept": True,
            "cover_letter_filled": True,
            "employer_questions_answered": "2/2",
            "persistent_profile_updates": 0,
            "seek_profile_suggestions_choice": "not_shown",
        },
    }


def _final_review_extraction() -> dict:
    return {
        "contract_version": "seek_final_review_extraction_v1",
        "status": "pass",
        "review_reconciliation": {
            "contract_version": "review_reconciliation_v1",
            "status": "pass",
            "checks": {
                "submit_application_visible": True,
                "submit_clicks": 0,
                "final_submissions": 0,
                "employer_questions_expected": 2,
                "employer_questions_matched": 2,
            },
        },
    }


def test_builds_seek_application_flow_artifact_as_non_authorizing_milestone() -> None:
    artifact = build_seek_application_flow_artifact(
        _record(),
        audit=_audit(),
        final_review_extraction=_final_review_extraction(),
        record_path="application_fill_record.json",
        audit_path="final_review_audit.json",
        final_review_extraction_path="final_review_extraction.json",
    )

    assert artifact["contract_version"] == "seek_application_flow_artifact_v1"
    assert artifact["artifact_id"] == "seek_station_internal_application_flow_v1"
    assert artifact["milestone"]["artifact_is_authorization"] is False
    assert artifact["milestone"]["safe_fill_primary_path_status"] == "needs_hardening_before_replay"
    assert artifact["source"]["audit_decision"] == "pass_stopped_before_final_submit"
    assert artifact["source"]["application_fill_record_path"] == "application_fill_record.json"
    assert artifact["source"]["final_review_audit_path"] == "final_review_audit.json"
    assert artifact["source"]["final_review_extraction_path"] == "final_review_extraction.json"
    assert artifact["source"]["final_review_extraction_status"] == "pass"
    assert artifact["source"]["reached_review_and_submit"] is True
    assert artifact["source"]["final_submissions"] == 0
    assert artifact["source"]["screenshot_paths"] == ["choose.png", "questions.png", "profile.png", "review.png"]
    assert artifact["source"]["trace_paths"] == ["type-text.json", "observe.json"]
    assert artifact["job"]["title"] == "Intermediate Engineer - AI Automation & Integration"
    assert [state["state_id"] for state in artifact["state_sequence"]] == [
        "choose_documents",
        "answer_employer_questions",
        "update_seek_profile",
        "review_and_submit",
    ]
    assert {item["action_id"] for item in artifact["action_templates"]} >= {
        "write_cover_letter",
        "answer_employer_questions",
        "continue_without_profile_mutation",
        "stop_before_final_submit",
        "extract_final_review",
    }
    review_skill = next(item for item in artifact["learned_skills"] if item["skill_ref"] == "skill:review_before_submit_reconciliation")
    assert review_skill["artifact_is_authorization"] is False
    assert "generic_form_review_before_submit" in review_skill["reusable_page_types"]
    assert "Submit application" in review_skill["forbidden_actions"]
    assert artifact["review_reconciliation"]["status"] == "pass"
    assert [state["state_id"] for state in artifact["states"]] == [
        "seek_apply:choose_documents",
        "seek_apply:cover_letter",
        "seek_apply:answer_employer_questions",
        "seek_apply:update_seek_profile",
        "seek_apply:review_and_submit",
        "seek_apply:final_submit_blocked",
        "seek_apply:third_party_ats_deferred",
        "seek_apply:blocked_upload_or_login",
    ]
    assert [transition["transition_id"] for transition in artifact["transitions"]] == [
        "seek_apply:keep_default_documents",
        "seek_apply:fill_cover_letter",
        "seek_apply:answer_questions",
        "seek_apply:skip_profile_update",
        "seek_apply:block_final_submit",
    ]
    assert artifact["safety_policy"]["final_submit_forbidden"] is True
    assert artifact["safety_policy"]["artifact_is_authorization"] is False
    assert artifact["safety_policy"]["profile_suggestion_policy"] == "not_shown"
    assert artifact["field_fill_policy"]["safe_fill_required_for_future_replay"] is True
    assert artifact["field_fill_policy"]["direct_type_text_is_milestone_evidence_only"] is True
    assert artifact["filled_content_summary"]["cover_letter_length"] > 20
    assert artifact["filled_content_summary"]["cover_letter_sha256"]
    assert artifact["filled_content_summary"]["employer_question_count"] == 2


def test_application_flow_artifact_cli_writes_utf8_json(tmp_path, capsys) -> None:
    record_path = tmp_path / "application_fill_record.json"
    audit_path = tmp_path / "final_review_audit.json"
    out_path = tmp_path / "artifact.json"
    record_path.write_text(json.dumps(_record(), ensure_ascii=False), encoding="utf-8")
    audit_path.write_text(json.dumps(_audit(), ensure_ascii=False), encoding="utf-8")
    extraction_path = tmp_path / "final_review_extraction.json"
    extraction_path.write_text(json.dumps(_final_review_extraction(), ensure_ascii=False), encoding="utf-8")

    exit_code = cli.main(
        [
            "--record",
            str(record_path),
            "--audit",
            str(audit_path),
            "--final-review-extraction",
            str(extraction_path),
            "--out",
            str(out_path),
        ]
    )
    printed = json.loads(capsys.readouterr().out)
    written = json.loads(out_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert printed["success"] is True
    assert printed["contract_version"] == "seek_application_flow_artifact_v1"
    assert printed["final_review_extraction_status"] == "pass"
    assert printed["artifact_is_authorization"] is False
    assert written["contract_version"] == "seek_application_flow_artifact_v1"
    assert written["review_reconciliation"]["status"] == "pass"
    assert "Intermediate Engineer" in out_path.read_text(encoding="utf-8")
