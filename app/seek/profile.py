from __future__ import annotations

from typing import Any


SAFE_FILL_PROFILE_FIELDS = {
    "candidate_name": ("candidate_name", "name"),
    "first_name": ("first_name", "given_name", "candidate_first_name"),
    "last_name": ("last_name", "surname", "family_name", "candidate_last_name"),
    "preferred_name": ("preferred_name",),
    "email": ("email", "email_address"),
    "phone": ("phone", "phone_number", "mobile"),
    "city": ("city", "current_city", "location_city"),
    "suburb": ("suburb", "current_suburb"),
    "github": ("github", "github_url", "github_profile"),
    "linkedin": ("linkedin", "linkedin_url", "linkedin_profile"),
    "portfolio": ("portfolio", "portfolio_url", "website", "personal_website"),
}

OPTIONAL_PROFILE_FIELDS = {
    "education_summary": ("education_summary", "education", "study_summary"),
    "availability_summary": ("availability_summary", "availability", "notice_period"),
    "avoid_roles_or_exclusions": ("avoid_roles", "excluded_roles", "do_not_apply_to", "avoid_companies"),
    "salary_preference": ("salary_preference", "salary_expectation"),
}


def assess_candidate_profile_readiness(profile: dict[str, Any] | None) -> dict[str, Any]:
    payload = profile if isinstance(profile, dict) else {}
    purpose = _clean(payload.get("profile_purpose")).casefold()
    experience = _strings(payload.get("experience_summary"))
    skills = _strings(payload.get("skills"))
    target_roles = _strings(payload.get("target_roles"))
    location_constraints = _strings(payload.get("location_constraints"))
    work_rights_summary = _clean(payload.get("work_rights_summary"))
    profile_source = _clean(payload.get("profile_source"))
    real_user_profile_source = profile_source == "real_user_candidate_profile_v1"
    smoke_markers = _smoke_or_test_markers(purpose=purpose, experience=experience)
    safe_fill_values = _safe_fill_values(payload)
    missing: list[str] = []
    if not payload:
        missing.append("candidate_profile_json")
    if payload and not real_user_profile_source:
        missing.append("profile_source_real_user_candidate_profile_v1")
    if smoke_markers:
        missing.append("real_profile_purpose")
    if not experience:
        missing.append("experience_summary")
    if not (skills or target_roles):
        missing.append("skills_or_target_roles")
    if not location_constraints:
        missing.append("location_constraints")
    if not work_rights_summary or work_rights_summary.casefold() in {"unknown", "unspecified", "n/a", "none"}:
        missing.append("work_rights_summary")
    if not safe_fill_values:
        missing.append("at_least_one_safe_text_field_value")
    optional_gaps = _optional_profile_gaps(payload)
    matching_ready = bool(payload and not smoke_markers and (skills or target_roles) and location_constraints)
    cover_letter_ready = bool(payload and real_user_profile_source and not smoke_markers and experience and (skills or target_roles))
    safe_fill_ready = bool(payload and real_user_profile_source and not smoke_markers and safe_fill_values)
    live_smoke_ready = bool(matching_ready and cover_letter_ready and safe_fill_ready and work_rights_summary and "work_rights_summary" not in missing)
    return {
        "contract_version": "candidate_profile_readiness_v1",
        "profile_present": bool(payload),
        "profile_source": profile_source or None,
        "real_user_profile_source": real_user_profile_source,
        "pii_redaction_enabled": True,
        "is_smoke_or_test_profile": bool(smoke_markers),
        "smoke_or_test_markers": smoke_markers,
        "matching_ready": matching_ready,
        "cover_letter_ready": cover_letter_ready,
        "safe_fill_ready": safe_fill_ready,
        "live_smoke_ready": live_smoke_ready,
        "safe_fill_values": safe_fill_values,
        "missing_requirements": missing,
        "optional_profile_gaps": optional_gaps,
        "decision": "ready_for_single_safe_field_live_smoke" if live_smoke_ready else "blocked_need_real_candidate_profile",
        "notes": [
            "Do not fabricate name/email/phone/profile URLs for live safe-fill.",
            "Matching requires target skills or roles plus location constraints.",
            "Cover letter generation still requires strong_apply and job-specific evidence.",
            "Sensitive answers such as work rights may still require user review in the live application flow.",
        ],
    }


def _safe_fill_values(profile: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for field_name, keys in SAFE_FILL_PROFILE_FIELDS.items():
        value = _first_value(profile, keys)
        if value:
            values.append({"field": field_name, "source_keys": list(keys), "value_length": len(value)})
    return values


def _smoke_or_test_markers(*, purpose: str, experience: list[str]) -> list[str]:
    text = " ".join([purpose, *experience]).casefold()
    markers: list[str] = []
    phrase_markers = {
        "smoke": ("smoke", "smoke_test", "smoke test"),
        "synthetic": ("synthetic",),
        "do not use for real": ("do not use for real", "not user resume", "not a real resume"),
    }
    test_phrases = (
        "test_profile",
        "test profile",
        "test only",
        "testing only",
        "for testing",
        "dummy test",
    )
    for marker, phrases in phrase_markers.items():
        if any(phrase in text for phrase in phrases):
            markers.append(marker)
    if any(phrase in text for phrase in test_phrases):
        markers.append("test")
    return markers


def _first_value(profile: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _clean(profile.get(key))
        if value and value.casefold() not in {"unknown", "unspecified", "n/a", "none"}:
            return value
    return None


def _optional_profile_gaps(profile: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    for field_name, keys in OPTIONAL_PROFILE_FIELDS.items():
        if not _first_value(profile, keys):
            gaps.append(field_name)
    return gaps


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in value or [] if str(item or "").strip()]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
