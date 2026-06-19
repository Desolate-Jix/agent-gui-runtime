from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


MATCH_DECISIONS = {"strong_apply", "maybe_apply", "skip", "need_user_review"}
WORK_RIGHTS_REVIEW_TERMS = (
    "visa",
    "sponsorship",
    "sponsor",
    "citizen",
    "citizenship",
    "permanent resident",
    "residency",
    "security clearance",
    "police check",
    "background check",
)


def load_candidate_profile(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    profile_path = Path(path)
    if not profile_path.exists():
        raise FileNotFoundError(f"candidate profile not found: {profile_path}")
    payload = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("candidate profile must be a JSON object")
    payload.setdefault("contract_version", "candidate_profile_v1")
    return payload


def score_seek_job(
    *,
    profile: dict[str, Any] | None,
    card: dict[str, Any] | None,
    detail: dict[str, Any] | None,
    detail_complete: bool = True,
    missing_detail_evidence: list[str] | None = None,
) -> dict[str, Any]:
    """Score a SEEK job against a candidate profile without inventing missing experience."""

    card_payload = card if isinstance(card, dict) else {}
    detail_payload = detail if isinstance(detail, dict) else {}
    if not detail_complete:
        missing = [str(item) for item in missing_detail_evidence or [] if str(item or "").strip()]
        return _decision(
            decision="need_user_review",
            score=0.0,
            positive=[],
            negative=[],
            unknowns=["job detail incomplete"] + [f"missing_detail_evidence: {', '.join(missing)}"] if missing else ["job detail incomplete"],
            risk_flags=["do_not_invent_experience", "detail_incomplete_do_not_apply"],
            card=card_payload,
            detail=detail_payload,
        )
    if not _valid_profile(profile):
        return _decision(
            decision="need_user_review",
            score=0.0,
            positive=[],
            negative=[],
            unknowns=["candidate_profile_v1 missing or incomplete"],
            risk_flags=["do_not_invent_experience"],
            card=card_payload,
            detail=detail_payload,
        )

    assert profile is not None
    job_text = _job_text(card_payload, detail_payload)
    skills = _strings(profile.get("skills"))
    target_roles = _strings(profile.get("target_roles"))
    locations = _strings(profile.get("location_constraints"))
    excluded_roles = _profile_terms(profile, "avoid_roles", "excluded_roles", "do_not_apply_to")
    excluded_companies = _profile_terms(profile, "avoid_companies", "do_not_apply_to")
    preferred_work_modes = _profile_terms(profile, "preferred_work_modes", "work_modes")
    positive: list[str] = []
    negative: list[str] = []
    unknowns: list[str] = []
    risk_flags = ["do_not_invent_experience"]
    title = str(detail_payload.get("title") or card_payload.get("title") or "")
    company = str(detail_payload.get("company") or card_payload.get("company") or "")

    matched_excluded_roles = [term for term in excluded_roles if _contains(title, term) or _contains(job_text, term)]
    matched_excluded_companies = [term for term in excluded_companies if _contains(company, term)]
    if matched_excluded_roles or matched_excluded_companies:
        if matched_excluded_roles:
            negative.append("excluded_role_or_term_matches: " + ", ".join(matched_excluded_roles[:5]))
        if matched_excluded_companies:
            negative.append("excluded_company_matches: " + ", ".join(matched_excluded_companies[:5]))
        return _decision(
            decision="skip",
            score=0.0,
            positive=positive,
            negative=negative,
            unknowns=unknowns,
            risk_flags=[*risk_flags, "candidate_profile_exclusion_matched"],
            card=card_payload,
            detail=detail_payload,
        )

    matched_skills = [skill for skill in skills if _contains(job_text, skill)]
    if matched_skills:
        positive.append("matched_skills: " + ", ".join(matched_skills[:8]))
    else:
        unknowns.append("no candidate skills matched visible job detail")

    matched_roles = [role for role in target_roles if _contains(title, role) or _contains(job_text, role)]
    if matched_roles:
        positive.append("matched_target_roles: " + ", ".join(matched_roles[:5]))

    job_location = str(detail_payload.get("location") or card_payload.get("location") or "")
    if locations and job_location:
        if any(_contains(job_location, location) or _contains(location, job_location) for location in locations):
            positive.append(f"location_matches: {job_location}")
        else:
            negative.append(f"location_mismatch: {job_location}")
    elif locations:
        unknowns.append("job location missing")

    matched_work_modes = [mode for mode in preferred_work_modes if _contains(job_text, mode)]
    if matched_work_modes:
        positive.append("matched_preferred_work_modes: " + ", ".join(matched_work_modes[:5]))
    elif preferred_work_modes:
        unknowns.append("preferred work mode not visible in job detail")

    work_rights_review_terms = [term for term in WORK_RIGHTS_REVIEW_TERMS if _contains(job_text, term)]
    if work_rights_review_terms:
        unknowns.append("work_rights_or_background_check_requires_review: " + ", ".join(work_rights_review_terms[:5]))
        risk_flags.append("work_rights_or_background_check_requires_review")

    score = 0.2
    score += min(0.45, 0.09 * len(matched_skills))
    if matched_roles:
        score += 0.2
    if any(item.startswith("location_matches") for item in positive):
        score += 0.15
    if matched_work_modes:
        score += 0.05
    if negative:
        score -= 0.3
    score = max(0.0, min(1.0, round(score, 3)))

    if "work_rights_or_background_check_requires_review" in risk_flags:
        decision_value = "need_user_review"
    elif negative and score < 0.45:
        decision_value = "skip"
    elif score >= 0.7 and matched_skills:
        decision_value = "strong_apply"
    elif score >= 0.45 and (matched_skills or matched_roles):
        decision_value = "maybe_apply"
    else:
        decision_value = "need_user_review"
    return _decision(
        decision=decision_value,
        score=score,
        positive=positive,
        negative=negative,
        unknowns=unknowns,
        risk_flags=risk_flags,
        card=card_payload,
        detail=detail_payload,
    )


def save_suitable_job_record(
    *,
    decision: dict[str, Any],
    card: dict[str, Any],
    detail: dict[str, Any],
    output_dir: str | Path = "artifacts/seek/saved-jobs",
) -> str | None:
    if decision.get("decision") not in {"strong_apply", "maybe_apply"}:
        return None
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    job_id = str(detail.get("job_id") or card.get("job_id") or _stable_id(card, detail))
    path = directory / f"{job_id}.json"
    payload = {
        "contract_version": "saved_seek_job_record_v1",
        "job_id": job_id,
        "decision": decision,
        "card": card,
        "detail": detail,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _valid_profile(profile: dict[str, Any] | None) -> bool:
    return isinstance(profile, dict) and bool(_strings(profile.get("skills")) or _strings(profile.get("target_roles")))


def _decision(
    *,
    decision: str,
    score: float,
    positive: list[str],
    negative: list[str],
    unknowns: list[str],
    risk_flags: list[str],
    card: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": "seek_job_match_decision_v1",
        "decision": decision if decision in MATCH_DECISIONS else "need_user_review",
        "score": score,
        "job_id": detail.get("job_id") or card.get("job_id"),
        "title": detail.get("title") or card.get("title"),
        "company": detail.get("company") or card.get("company"),
        "positive_evidence": positive,
        "negative_evidence": negative,
        "unknowns": unknowns,
        "risk_flags": risk_flags,
        "trace_path": None,
    }


def _job_text(card: dict[str, Any], detail: dict[str, Any]) -> str:
    parts: list[str] = []
    for payload in (card, detail):
        for key in ("title", "company", "location", "work_type", "classification", "salary_text"):
            parts.append(str(payload.get(key) or ""))
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        parts.extend(_strings(evidence.get("texts")))
        for key in ("requirements", "responsibilities", "benefits"):
            parts.extend(_strings(payload.get(key)))
    return " ".join(parts).casefold()


def _strings(value: Any) -> list[str]:
    return [str(item).strip() for item in value or [] if str(item or "").strip()]


def _profile_terms(profile: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = profile.get(key)
        if isinstance(value, str):
            values.append(value)
        else:
            values.extend(_strings(value))
    seen: set[str] = set()
    unique: list[str] = []
    for item in values:
        cleaned = " ".join(str(item or "").split())
        folded = cleaned.casefold()
        if cleaned and folded not in seen:
            seen.add(folded)
            unique.append(cleaned)
    return unique


def _contains(haystack: str, needle: str) -> bool:
    return str(needle or "").casefold().strip() in str(haystack or "").casefold()


def _stable_id(card: dict[str, Any], detail: dict[str, Any]) -> str:
    basis = "|".join(str(item or "") for item in [detail.get("title"), detail.get("company"), card.get("title")])
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"seek_job_{digest}"
