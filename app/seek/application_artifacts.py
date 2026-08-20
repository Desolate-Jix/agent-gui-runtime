from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any


SEEK_APPLICATION_FLOW_ARTIFACT_CONTRACT = "seek_application_flow_artifact_v1"


def build_seek_application_flow_artifact(
    fill_record: dict[str, Any] | None,
    *,
    audit: dict[str, Any] | None = None,
    final_review_extraction: dict[str, Any] | None = None,
    record_path: str | Path | None = None,
    audit_path: str | Path | None = None,
    final_review_extraction_path: str | Path | None = None,
) -> dict[str, Any]:
    """Export a reviewed SEEK station-internal application fill as learning evidence."""

    record = fill_record if isinstance(fill_record, dict) else {}
    audit_payload = audit if isinstance(audit, dict) else {}
    extraction_payload = final_review_extraction if isinstance(final_review_extraction, dict) else {}
    reconciliation = (
        extraction_payload.get("review_reconciliation")
        if isinstance(extraction_payload.get("review_reconciliation"), dict)
        else {}
    )
    evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
    screenshots = list(evidence.get("screenshots") or [])
    action_traces = list(evidence.get("action_traces") or [])
    vision_traces = list(evidence.get("vision_traces") or [])
    job = record.get("job") if isinstance(record.get("job"), dict) else {}
    return {
        "contract_version": SEEK_APPLICATION_FLOW_ARTIFACT_CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_id": "seek_station_internal_application_flow_v1",
        "app_id": "seek",
        "page_type": "seek_station_internal_application",
        "milestone": {
            "status": "reviewed_stop_before_submit",
            "artifact_is_authorization": False,
            "safe_fill_primary_path_status": "needs_hardening_before_replay",
        },
        "source": {
            "record_path": str(record_path) if record_path else None,
            "audit_path": str(audit_path) if audit_path else None,
            "application_fill_record_path": str(record_path) if record_path else None,
            "final_review_audit_path": str(audit_path) if audit_path else None,
            "final_review_extraction_path": str(final_review_extraction_path) if final_review_extraction_path else None,
            "record_contract": record.get("contract_version"),
            "audit_contract": audit_payload.get("contract_version"),
            "final_review_extraction_contract": extraction_payload.get("contract_version"),
            "audit_decision": audit_payload.get("decision"),
            "final_review_extraction_status": extraction_payload.get("status"),
            "trace_paths": [*action_traces, *vision_traces],
            "screenshot_paths": screenshots,
            "job_id": record.get("job_id") or job.get("job_id"),
            "job_title": record.get("job_title") or job.get("title"),
            "company": job.get("company"),
            "reached_review_and_submit": str(record.get("stage") or "").casefold() == "review_before_submit"
            or audit_payload.get("decision") == "pass_stopped_before_final_submit",
            "final_submissions": int(record.get("final_submissions") or 0),
        },
        "job": {
            "job_id": record.get("job_id") or job.get("job_id"),
            "title": record.get("job_title") or job.get("title"),
            "company": job.get("company"),
            "apply_url": record.get("apply_url") or job.get("application_url"),
        },
        "state_sequence": _state_sequence(record),
        "states": _application_states(),
        "transitions": _application_transitions(),
        "action_templates": _application_action_templates(record),
        "verification_rules": _application_verification_rules(),
        "safety_policy": _application_safety_policy(record, audit_payload),
        "field_fill_policy": _field_fill_policy(record),
        "filled_content_summary": _filled_content_summary(record),
        "review_reconciliation": reconciliation,
        "learned_skills": _application_learned_skills(reconciliation),
        "evidence": {
            "screenshots": screenshots,
            "action_traces": action_traces,
            "vision_traces": vision_traces,
            "review_before_submit_screenshot": evidence.get("review_before_submit_screenshot"),
            "cover_letter_type_text_trace": evidence.get("cover_letter_type_text_trace")
            or evidence.get("clipboard_fix_type_text_trace"),
        },
    }


def _state_sequence(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "state_id": "choose_documents",
            "url_pattern": "/apply",
            "purpose": "keep default resume and write or replace cover letter",
            "required_evidence": ["resume_selected", "cover_letter_written"],
            "next_action": "continue_to_employer_questions",
        },
        {
            "state_id": "answer_employer_questions",
            "url_pattern": "/apply/role-requirements",
            "purpose": "answer evidence-backed employer questions",
            "required_evidence": ["all_visible_questions_answered"],
            "question_count": int(record.get("employer_question_total") or 0),
            "next_action": "continue_to_update_seek_profile",
        },
        {
            "state_id": "update_seek_profile",
            "url_pattern": "/apply/profile",
            "purpose": "review SEEK profile without persistent mutation",
            "required_evidence": ["no_add_or_edit_profile_actions_clicked"],
            "next_action": "continue_to_review",
        },
        {
            "state_id": "review_and_submit",
            "url_pattern": "/apply/review",
            "purpose": "final human review boundary",
            "required_evidence": ["final_submit_visible_blocker"],
            "next_action": "stop_before_submit",
        },
    ]


def _application_states() -> list[dict[str, Any]]:
    return [
        {
            "state_id": "seek_apply:choose_documents",
            "state_type": "form_step",
            "terminal": False,
            "purpose": "keep default documents and prepare cover letter entry",
        },
        {
            "state_id": "seek_apply:cover_letter",
            "state_type": "form_step",
            "terminal": False,
            "purpose": "fill a job-specific cover letter with safe-fill verification",
        },
        {
            "state_id": "seek_apply:answer_employer_questions",
            "state_type": "form_step",
            "terminal": False,
            "purpose": "answer employer questions from candidate profile and reviewed evidence",
        },
        {
            "state_id": "seek_apply:update_seek_profile",
            "state_type": "form_step",
            "terminal": False,
            "purpose": "continue without persistent SEEK Profile mutation",
        },
        {
            "state_id": "seek_apply:review_and_submit",
            "state_type": "review_boundary",
            "terminal": False,
            "purpose": "review filled application before human-approved final submit",
        },
        {
            "state_id": "seek_apply:final_submit_blocked",
            "state_type": "safe_terminal",
            "terminal": True,
            "purpose": "correct stop state before final submission",
        },
        {
            "state_id": "seek_apply:third_party_ats_deferred",
            "state_type": "deferred_terminal",
            "terminal": True,
            "purpose": "defer external ATS applications for later dedicated learning",
        },
        {
            "state_id": "seek_apply:blocked_upload_or_login",
            "state_type": "blocked_terminal",
            "terminal": True,
            "purpose": "stop when login, upload, captcha, or unsafe required fields appear",
        },
    ]


def _application_transitions() -> list[dict[str, Any]]:
    return [
        {
            "transition_id": "seek_apply:keep_default_documents",
            "from_state": "seek_apply:choose_documents",
            "to_state": "seek_apply:cover_letter",
            "action_template_id": "continue_keep_default_resume",
            "requires": ["default_resume_visible", "no_resume_replacement"],
        },
        {
            "transition_id": "seek_apply:fill_cover_letter",
            "from_state": "seek_apply:cover_letter",
            "to_state": "seek_apply:answer_employer_questions",
            "action_template_id": "fill_cover_letter_and_continue",
            "requires": ["safe_fill_focus_verified", "post_fill_value_verified", "submit_false"],
        },
        {
            "transition_id": "seek_apply:answer_questions",
            "from_state": "seek_apply:answer_employer_questions",
            "to_state": "seek_apply:update_seek_profile",
            "action_template_id": "answer_employer_questions_and_continue",
            "requires": ["answers_have_evidence_source", "all_visible_questions_answered"],
        },
        {
            "transition_id": "seek_apply:skip_profile_update",
            "from_state": "seek_apply:update_seek_profile",
            "to_state": "seek_apply:review_and_submit",
            "action_template_id": "continue_without_persistent_profile_update",
            "requires": ["no_add_or_edit_profile_actions_clicked", "persistent_profile_updates_zero"],
        },
        {
            "transition_id": "seek_apply:block_final_submit",
            "from_state": "seek_apply:review_and_submit",
            "to_state": "seek_apply:final_submit_blocked",
            "action_template_id": "stop_before_final_submit",
            "requires": ["final_submit_visible", "final_submissions_zero"],
        },
    ]


def _application_action_templates(record: dict[str, Any]) -> list[dict[str, Any]]:
    questions = (record.get("filled_content") or {}).get("employer_questions")
    return [
        {
            "action_id": "write_cover_letter",
            "kind": "input",
            "low_level_action_type": "type_text",
            "state_id": "choose_documents",
            "value_source": "cover_letter_draft_v1.draft",
            "submit": False,
            "requires_trace": True,
        },
        {
            "action_id": "answer_employer_questions",
            "kind": "input_or_select",
            "state_id": "answer_employer_questions",
            "question_count": len(questions) if isinstance(questions, list) else int(record.get("employer_question_total") or 0),
            "value_source": "candidate_profile_v1 + reviewed evidence",
            "requires_evidence_source": True,
        },
        {
            "action_id": "continue_without_profile_mutation",
            "kind": "click",
            "low_level_action_type": "execute_confirmed_point_or_recognition_plan",
            "state_id": "update_seek_profile",
            "forbidden_targets": ["Add role", "Add education", "Add skills", "Edit", "Submit application"],
        },
        {
            "action_id": "stop_before_final_submit",
            "kind": "guard",
            "state_id": "review_and_submit",
            "forbidden_targets": ["Submit application", "Send application", "Complete application"],
        },
        {
            "action_id": "extract_final_review",
            "kind": "read_reconcile_guard",
            "low_level_action_type": "observe_and_reconcile",
            "state_id": "review_and_submit",
            "learned_skill_ref": "skill:review_before_submit_reconciliation",
            "value_source": "current_observation + application_fill_record",
            "requires": [
                "current_review_observation",
                "submit_application_visible",
                "submit_clicks_zero",
                "final_submissions_zero",
            ],
            "checks": ["resume", "cover_letter_latest_hash", "employer_questions", "profile_not_mutated"],
            "forbidden_targets": ["Submit application", "Send application", "Complete application"],
        },
    ]


def _application_verification_rules() -> list[dict[str, Any]]:
    return [
        {"rule_id": "resume_kept", "check": "resume field exists and no resume replacement action was clicked"},
        {"rule_id": "cover_letter_filled", "check": "cover letter body exists or review page says a cover letter was written"},
        {"rule_id": "questions_answered", "check": "answered count equals employer_question_total"},
        {"rule_id": "profile_not_mutated", "check": "persistent_profile_updates == 0"},
        {"rule_id": "final_review_boundary", "check": "current_step == review_and_submit and final_submit_visible_blocker.blocked == true"},
        {"rule_id": "final_review_reconciliation", "check": "review_reconciliation.status == pass before converting run into reusable learning evidence"},
        {"rule_id": "no_final_submit", "check": "final_submissions == 0 and submit_clicks == 0"},
    ]


def _field_fill_policy(record: dict[str, Any]) -> dict[str, Any]:
    issues = record.get("known_issues_from_run")
    return {
        "contract_version": "seek_application_field_fill_policy_v1",
        "safe_fill_required_for_future_replay": True,
        "direct_type_text_is_milestone_evidence_only": True,
        "field_focus_required": True,
        "post_fill_value_verification_required": True,
        "submit_during_fill_forbidden": True,
        "known_issues_from_run": list(issues) if isinstance(issues, list) else [],
    }


def _application_safety_policy(record: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    checks = audit.get("checks") if isinstance(audit.get("checks"), dict) else {}
    return {
        "contract_version": "seek_application_safety_policy_v1",
        "artifact_is_authorization": False,
        "final_submit_forbidden": True,
        "external_apply_deferred": True,
        "default_resume_policy": "keep_seek_default_resume",
        "seek_profile_mutation_policy": "forbidden_without_explicit_user_approval",
        "profile_suggestion_policy": checks.get("seek_profile_suggestions_choice") or "not_observed",
        "final_submissions": int(record.get("final_submissions") or 0),
        "submit_clicks": int(record.get("submit_clicks") or 0),
        "audit_decision": audit.get("decision"),
    }


def _filled_content_summary(record: dict[str, Any]) -> dict[str, Any]:
    content = record.get("filled_content") if isinstance(record.get("filled_content"), dict) else {}
    cover_letter = str(content.get("cover_letter") or "")
    questions = content.get("employer_questions") if isinstance(content.get("employer_questions"), list) else []
    return {
        "resume": content.get("resume"),
        "cover_letter_length": len(cover_letter),
        "cover_letter_sha256": hashlib.sha256(cover_letter.encode("utf-8")).hexdigest() if cover_letter else None,
        "employer_question_count": len(questions),
        "seek_profile_mutation": content.get("seek_profile_mutation"),
    }


def _application_learned_skills(reconciliation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "skill_ref": "skill:review_before_submit_reconciliation",
            "contract_version": "learned_skill_v1",
            "source_app_id": "seek",
            "source_page_type": "seek_station_internal_application",
            "reusable_page_types": [
                "multi_step_application_review",
                "checkout_review_before_submit",
                "generic_form_review_before_submit",
            ],
            "purpose": "Compare the visible final review page against the saved fill record, then stop before final submit.",
            "inputs": ["current_observation", "fill_record", "flow_state"],
            "outputs": ["review_reconciliation_v1", "missing_or_mismatched_fields", "final_submit_guard"],
            "low_level_action_types": ["observe", "read", "reconcile", "guard"],
            "allowed_actions": ["safe_expand_review_section", "scroll_review_section_read_only"],
            "forbidden_actions": ["Submit application", "Send application", "Complete application"],
            "success_criteria": [
                "submit control is visible",
                "submit_clicks == 0",
                "final_submissions == 0",
                "resume matches expected document",
                "cover_letter_latest_hash is present and observed text matches key snippets",
                "all expected employer answers are present",
                "profile mutation count is zero",
            ],
            "last_reconciliation_status": reconciliation.get("status") if reconciliation else None,
            "artifact_is_authorization": False,
        }
    ]
