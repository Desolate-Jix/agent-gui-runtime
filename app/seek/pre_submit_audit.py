from __future__ import annotations

import re
from typing import Any


CONTRACT_VERSION = "final_submit_decision_v1"
CONTRACT_DURATION_TERMS = (
    "contract",
    "fixed term",
    "fixed-term",
    "ftc",
    "temporary",
    "temp",
    "6 month",
    "six month",
)


def build_seek_final_submit_decision(
    *,
    job: dict[str, Any] | None,
    match_decision: dict[str, Any] | None,
    application_answers: list[dict[str, Any]] | None = None,
    user_preferences: dict[str, Any] | None = None,
    gpt_review: dict[str, Any] | None = None,
    user_reviewed_current_job: bool = False,
    user_override_match_review: bool = False,
) -> dict[str, Any]:
    """Build the structured audit required before a SEEK final submit."""

    job_payload = job if isinstance(job, dict) else {}
    decision_payload = match_decision if isinstance(match_decision, dict) else {}
    preferences = user_preferences if isinstance(user_preferences, dict) else {}
    gpt_payload = gpt_review if isinstance(gpt_review, dict) else {}
    answers = [item for item in application_answers or [] if isinstance(item, dict)]

    risk_flags: list[str] = []
    warnings: list[str] = []
    block_reasons: list[str] = []
    match_value = str(decision_payload.get("decision") or "")

    if not match_value:
        risk_flags.append("missing_current_live_match_decision")
        block_reasons.append("missing_current_live_match_decision")
    elif match_value != "strong_apply" and not user_override_match_review:
        block_reasons.append("match_decision_not_strong_apply")

    location_text = str(job_payload.get("location") or "")
    if _prefers_auckland(preferences) and location_text and "auckland" not in location_text.casefold():
        warnings.append("non_auckland_location_requires_review")
        if not user_reviewed_current_job:
            block_reasons.append("non_auckland_location_not_reviewed")

    job_text = _job_text(job_payload)
    if any(term in job_text for term in CONTRACT_DURATION_TERMS):
        warnings.append("contract_duration_requires_review")
        if not user_reviewed_current_job:
            block_reasons.append("contract_duration_not_reviewed")

    unsupported_answer_risks = _unsupported_yes_answer_risks(answers)
    if unsupported_answer_risks:
        risk_flags.append("unsupported_yes_answer")
        block_reasons.append("unsupported_answer_or_hard_risk_present")

    if not user_reviewed_current_job:
        block_reasons.append("current_job_not_user_reviewed")

    gpt_decision = str(gpt_payload.get("submit_recommendation") or gpt_payload.get("decision") or "")
    if gpt_decision in {"do_not_submit", "need_user_review", "maybe_apply_pending_user_review"}:
        block_reasons.append("gpt_review_did_not_recommend_submit")

    unique_block_reasons = _unique(block_reasons)
    allow_final_submit = not unique_block_reasons
    return {
        "contract_version": CONTRACT_VERSION,
        "app": "seek",
        "job_identity": {
            "job_id": job_payload.get("job_id"),
            "title": job_payload.get("title"),
            "company": job_payload.get("company"),
            "location": job_payload.get("location"),
            "work_type": job_payload.get("work_type"),
        },
        "user_preferences_applied": preferences,
        "match_decision": match_value or "need_user_review",
        "match_score": decision_payload.get("score"),
        "user_reviewed_current_job": bool(user_reviewed_current_job),
        "user_override_match_review": bool(user_override_match_review),
        "gpt_review": gpt_payload,
        "unsupported_yes_answers": bool(unsupported_answer_risks),
        "unsupported_answer_risks": unsupported_answer_risks,
        "risk_flags": _unique(risk_flags),
        "warnings": _unique(warnings),
        "block_reasons": unique_block_reasons,
        "allow_final_submit": allow_final_submit,
        "submit_gate": "allow" if allow_final_submit else "block",
    }


def _prefers_auckland(preferences: dict[str, Any]) -> bool:
    values = preferences.get("preferred_locations") or preferences.get("locations") or []
    if isinstance(values, str):
        values = [values]
    return any("auckland" in str(item or "").casefold() for item in values)


def _job_text(job: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "company", "location", "work_type", "classification", "salary_text", "summary", "description"):
        parts.append(str(job.get(key) or ""))
    for section in job.get("description_sections") or []:
        if isinstance(section, dict):
            parts.append(str(section.get("text") or ""))
        else:
            parts.append(str(section or ""))
    return " ".join(parts).casefold()


def _unsupported_yes_answer_risks(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for answer in answers:
        value = str(answer.get("answer") or answer.get("value") or "").strip().casefold()
        if value not in {"yes", "true"}:
            continue
        supported = answer.get("supported_by_profile")
        evidence = answer.get("evidence")
        if supported is True or (isinstance(evidence, list) and evidence):
            continue
        risks.append(
            {
                "question": answer.get("question") or answer.get("label"),
                "answer": answer.get("answer") or answer.get("value"),
                "reason": "yes_answer_without_profile_evidence",
            }
        )
    return risks


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", "_", str(value or "").strip())
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result
