from __future__ import annotations

import hashlib
from typing import Any


def build_cover_letter_draft(
    *,
    profile: dict[str, Any] | None,
    detail: dict[str, Any] | None,
    match_decision: dict[str, Any] | None,
    application_flow_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a truthful draft-only cover letter artifact.

    This function intentionally does not paste into the UI and does not claim a real
    application was submitted. If the profile is a smoke/test profile or lacks real
    resume evidence, it returns a blocked draft artifact instead of inventing content.
    """

    profile_payload = profile if isinstance(profile, dict) else {}
    detail_payload = detail if isinstance(detail, dict) else {}
    decision_payload = match_decision if isinstance(match_decision, dict) else {}
    flow_payload = application_flow_state if isinstance(application_flow_state, dict) else {}

    title = _clean(detail_payload.get("title") or decision_payload.get("title") or "the role")
    company = _clean(detail_payload.get("company") or decision_payload.get("company") or "your team")
    job_hash = _job_hash(detail_payload)
    base = {
        "contract_version": "cover_letter_draft_v1",
        "job_hash": job_hash,
        "job_id": detail_payload.get("job_id") or decision_payload.get("job_id"),
        "title": title,
        "company": company,
        "status": "blocked_need_real_resume_profile",
        "draft": "",
        "evidence_used": [],
        "truthfulness_checks": _truthfulness_checks("", profile_payload, []),
        "blocked_reason": None,
        "source_contracts": {
            "profile": profile_payload.get("contract_version"),
            "detail": detail_payload.get("contract_version"),
            "match_decision": decision_payload.get("contract_version"),
            "application_flow_state": flow_payload.get("contract_version"),
        },
    }

    if not _profile_is_real_resume(profile_payload):
        return {**base, "blocked_reason": "candidate_profile_is_missing_or_marked_smoke_test"}

    if decision_payload.get("decision") != "strong_apply":
        return {
            **base,
            "status": "blocked_decision_not_strong_apply",
            "blocked_reason": "cover_letter_draft_requires_strong_apply_decision",
        }

    matched_skills = _matched_profile_skills(profile_payload, detail_payload, decision_payload)
    if not matched_skills:
        return {
            **base,
            "status": "blocked_no_profile_skill_evidence",
            "blocked_reason": "no profile skill evidence matched the job detail",
        }

    experience = _sentences(profile_payload.get("experience_summary"))
    if not experience:
        return {
            **base,
            "status": "blocked_need_real_resume_profile",
            "blocked_reason": "candidate_profile_missing_experience_summary",
        }

    job_themes = _job_themes(detail_payload)
    candidate_name = _clean(profile_payload.get("candidate_name") or profile_payload.get("name") or "Candidate")
    draft = _compose_draft(
        candidate_name=candidate_name,
        title=title,
        company=company,
        experience=experience[:2],
        matched_skills=matched_skills[:6],
        job_themes=job_themes[:3],
    )
    evidence_used = [
        f"Matched profile skills: {', '.join(matched_skills[:6])}",
        *[f"Profile evidence: {item}" for item in experience[:2]],
        *[f"Job detail evidence: {item}" for item in job_themes[:3]],
        *[f"Match evidence: {item}" for item in _strings(decision_payload.get("positive_evidence"))[:3]],
    ]
    return {
        **base,
        "status": "draft_only_not_pasted",
        "draft": draft,
        "evidence_used": evidence_used,
        "truthfulness_checks": _truthfulness_checks(draft, profile_payload, matched_skills),
        "blocked_reason": None,
    }


def _profile_is_real_resume(profile: dict[str, Any]) -> bool:
    purpose = _clean(profile.get("profile_purpose")).casefold()
    if not profile:
        return False
    if "smoke" in purpose or "test" in purpose:
        return False
    combined = " ".join(_strings(profile.get("experience_summary"))).casefold()
    if "do not use for real" in combined or "synthetic" in combined:
        return False
    return bool(_strings(profile.get("experience_summary")) and (_strings(profile.get("skills")) or _strings(profile.get("target_roles"))))


def _matched_profile_skills(profile: dict[str, Any], detail: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    profile_skills = _strings(profile.get("skills"))
    job_text = " ".join(
        [
            _clean(detail.get("title")),
            _clean(detail.get("company")),
            " ".join(_strings(detail.get("requirements"))),
            " ".join(_strings(detail.get("responsibilities"))),
            " ".join(_strings(detail.get("benefits"))),
            " ".join(_strings((detail.get("evidence") or {}).get("texts") if isinstance(detail.get("evidence"), dict) else [])),
            " ".join(_strings(decision.get("positive_evidence"))),
        ]
    ).casefold()
    return [skill for skill in profile_skills if skill.casefold() in job_text]


def _job_themes(detail: dict[str, Any]) -> list[str]:
    themes: list[str] = []
    for key in ("responsibilities", "requirements", "benefits"):
        themes.extend(_strings(detail.get(key)))
    if not themes:
        evidence = detail.get("evidence") if isinstance(detail.get("evidence"), dict) else {}
        themes.extend(_strings(evidence.get("texts")))
    return [_clean(item) for item in themes if _clean(item)]


def _compose_draft(
    *,
    candidate_name: str,
    title: str,
    company: str,
    experience: list[str],
    matched_skills: list[str],
    job_themes: list[str],
) -> str:
    skill_text = ", ".join(matched_skills)
    theme_text = "; ".join(job_themes) if job_themes else "the responsibilities described in the role"
    experience_text = " ".join(experience)
    return "\n\n".join(
        [
            "Dear Hiring Team,",
            f"I am interested in the {title} role at {company}. The role stood out to me because it aligns with {theme_text}.",
            f"My relevant background includes {experience_text} I can bring practical experience with {skill_text}, along with a careful, evidence-driven approach to debugging, implementation, and testing.",
            "I would welcome the opportunity to discuss how my current skills and project experience could support your team. I have kept this draft limited to the evidence available in my profile and the job description.",
            f"Kind regards,\n{candidate_name}",
        ]
    )


def _truthfulness_checks(draft: str, profile: dict[str, Any], matched_skills: list[str]) -> dict[str, bool]:
    text = draft.casefold()
    profile_skills = {skill.casefold() for skill in _strings(profile.get("skills"))}
    return {
        "does_not_claim_commercial_years": "years of commercial" not in text and "commercial years" not in text,
        "does_not_claim_submitted_application": "submitted my application" not in text and "i have applied" not in text,
        "does_not_overstate_graduation_status": "graduated" not in text or "graduated" in " ".join(_strings(profile.get("experience_summary"))).casefold(),
        "does_not_invent_skills": all(skill.casefold() in profile_skills for skill in matched_skills),
        "draft_only_not_pasted": True,
    }


def _job_hash(detail: dict[str, Any]) -> str:
    parts = [
        _clean(detail.get("job_id")),
        _clean(detail.get("title")),
        _clean(detail.get("company")),
        " ".join(_strings(detail.get("requirements"))),
        " ".join(_strings(detail.get("responsibilities"))),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _sentences(value: Any) -> list[str]:
    return [_clean(item).rstrip(".") + "." for item in _strings(value)]


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in value or [] if str(item or "").strip()]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
