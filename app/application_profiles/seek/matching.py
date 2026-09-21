from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


MATCH_DECISIONS = {"strong_apply", "maybe_apply", "skip", "need_user_review"}
AGENT_REVIEW_PASS_VERDICTS = {"pass", "suitable", "open_apply_entry", "apply_entry_allowed"}
AGENT_REVIEW_REJECT_VERDICTS = {"reject", "skip", "not_suitable", "do_not_apply"}
EXPERIENCE_HARD_SKIP_MIN_YEARS = 2
EXPERIENCE_REVIEW_MIN_YEARS = 1
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
NEW_ZEALAND_LOCATION_TERMS = (
    "new zealand",
    "nz",
    "aotearoa",
    "auckland",
    "wellington",
    "christchurch",
    "canterbury",
    "hamilton",
    "tauranga",
    "dunedin",
    "queenstown",
    "nelson",
    "napier",
    "hastings",
    "palmerston north",
    "rotorua",
    "new plymouth",
    "invercargill",
)
SENIOR_TITLE_TERMS = ("senior", "principal", "staff", "lead")
SENIOR_REVIEW_TERMS = (
    "architecture",
    "architectural",
    "mentor",
    "mentoring",
    "technical leadership",
    "team leadership",
    "lead on complex",
    "take a leading role",
)
SECURITY_CLEARANCE_HARD_SKIP_TERMS = (
    "top secret special",
    "tss clearance",
    "national security clearance",
    "security clearance",
    "nz security clearance",
    "new zealand security clearance",
    "citizenship and security clearance",
    "citizen and security clearance",
    "nz citizenship and security clearance",
    "new zealand citizenship and security clearance",
)
LONG_NZ_BACKGROUND_HARD_SKIP_TERMS = (
    "10 years in new zealand",
    "10 years of new zealand",
    "10-year background",
    "10 year background",
    "checkable background",
    "10 years checkable",
)
HARDWARE_ELECTRICAL_CLASSIFICATION_TERMS = (
    "electrical/electronic engineering",
    "electrical engineering",
    "electronic engineering",
    "hardware engineering",
    "hardware engineer",
    "embedded hardware",
    "fpga",
    "pcb",
    "circuit",
    "electronics",
)
SOFTWARE_RESCUE_TERMS = (
    "embedded software",
    "software engineer",
    "software developer",
    "firmware",
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
    detail_payload = merge_seek_job_identity(card_payload, detail if isinstance(detail, dict) else {})
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

    if _agent_full_jd_review_required(profile):
        return _decision(
            decision="need_user_review",
            score=0.0,
            positive=["full_job_detail_ready_for_agent_review"],
            negative=[],
            unknowns=["agent_full_jd_review_required"],
            risk_flags=[*risk_flags, "local_keyword_suitability_screening_disabled"],
            card=card_payload,
            detail=detail_payload,
            agent_review=_agent_review_payload(card=card_payload, detail=detail_payload),
        )

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

    hard_gate = _hard_requirement_gate(title=title, job_text=job_text, detail=detail_payload)
    if hard_gate["decision"] == "skip":
        negative.append(hard_gate["summary"])
        return _decision(
            decision="skip",
            score=0.0,
            positive=positive,
            negative=negative,
            unknowns=unknowns,
            risk_flags=[*risk_flags, hard_gate["risk_flag"]],
            card=card_payload,
            detail=detail_payload,
        )

    experience_gate = _experience_gate(title=title, job_text=job_text)
    if experience_gate["decision"] == "skip":
        negative.append(experience_gate["summary"])
        return _decision(
            decision="skip",
            score=0.0,
            positive=positive,
            negative=negative,
            unknowns=unknowns,
            risk_flags=[*risk_flags, "experience_requirement_exceeds_profile_stage"],
            card=card_payload,
            detail=detail_payload,
        )
    if experience_gate["decision"] == "need_user_review":
        unknowns.append(experience_gate["summary"])
        risk_flags.append("experience_requirement_requires_review")

    matched_skills = [skill for skill in skills if _contains(job_text, skill)]
    if matched_skills:
        positive.append("matched_skills: " + ", ".join(matched_skills[:8]))
    else:
        unknowns.append("no candidate skills matched visible job detail")

    matched_roles = [role for role in target_roles if _matches_role(title, role) or _matches_role(job_text, role)]
    if matched_roles:
        positive.append("matched_target_roles: " + ", ".join(matched_roles[:5]))

    job_location = str(detail_payload.get("location") or card_payload.get("location") or "")
    if locations and job_location:
        if any(_location_matches(job_location, location) for location in locations):
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

    if "experience_requirement_requires_review" in risk_flags:
        decision_value = "need_user_review"
    elif "work_rights_or_background_check_requires_review" in risk_flags:
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
    detail_payload = merge_seek_job_identity(card, detail)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    job_id = str(detail_payload.get("job_id") or card.get("job_id") or _stable_id(card, detail_payload))
    path = directory / f"{job_id}.json"
    payload = {
        "contract_version": "saved_seek_job_record_v1",
        "job_id": job_id,
        "decision": decision,
        "card": card,
        "detail": detail_payload,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def load_agent_suitability_reviews(path: str | Path | None) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict) and isinstance(payload.get("reviews"), list):
        return [item for item in payload["reviews"] if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError("agent suitability review file must contain an object, reviews list, or list of objects")


def find_agent_suitability_review(
    reviews: list[dict[str, Any]],
    *,
    match_decision: dict[str, Any],
    card: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any] | None:
    if not reviews:
        return None
    wanted = {
        _identity_key(match_decision.get("job_id"), match_decision.get("title"), match_decision.get("company")),
        _identity_key(detail.get("job_id"), detail.get("title"), detail.get("company")),
        _identity_key(card.get("job_id"), card.get("title"), card.get("company")),
    }
    wanted = {item for item in wanted if item}
    for review in reviews:
        keys = {
            _identity_key(review.get("job_id"), review.get("title"), review.get("company")),
            _identity_key(review.get("job", {}).get("job_id") if isinstance(review.get("job"), dict) else None,
                          review.get("job", {}).get("title") if isinstance(review.get("job"), dict) else None,
                          review.get("job", {}).get("company") if isinstance(review.get("job"), dict) else None),
        }
        if any(key and key in wanted for key in keys):
            return review
    return None


def apply_agent_suitability_review(match_decision: dict[str, Any], review: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(review, dict):
        return match_decision
    verdict = _normalized_review_verdict(review)
    next_decision = "need_user_review"
    positive = _strings(match_decision.get("positive_evidence"))
    negative = _strings(match_decision.get("negative_evidence"))
    unknowns = _strings(match_decision.get("unknowns"))
    risk_flags = _strings(match_decision.get("risk_flags"))
    if verdict in AGENT_REVIEW_PASS_VERDICTS:
        next_decision = "strong_apply"
        positive = [*positive, "agent_suitability_review_passed"]
        risk_flags = [flag for flag in risk_flags if flag != "local_keyword_suitability_screening_disabled"]
        risk_flags.append("agent_full_jd_review_passed")
        unknowns = [item for item in unknowns if item != "agent_full_jd_review_required"]
    elif verdict in AGENT_REVIEW_REJECT_VERDICTS:
        next_decision = "skip"
        negative = [*negative, "agent_suitability_review_rejected"]
        risk_flags.append("agent_full_jd_review_rejected")
        unknowns = [item for item in unknowns if item != "agent_full_jd_review_required"]
    else:
        unknowns = [*unknowns, "agent_suitability_review_missing_or_needs_more_info"]
        risk_flags.append("agent_full_jd_review_not_passed")
    reviewed = {
        **match_decision,
        "decision": next_decision,
        "score": 0.0,
        "fit_summary": _fit_summary(
            decision=next_decision,
            score=0.0,
            positive=positive,
            negative=negative,
            unknowns=unknowns,
        ),
        "recommended_next_action": _recommended_next_action(next_decision),
        "positive_evidence": positive,
        "negative_evidence": negative,
        "unknowns": unknowns,
        "risk_flags": _unique_strings(risk_flags),
        "agent_suitability_review": {
            "contract_version": str(review.get("contract_version") or "agent_suitability_review_v1"),
            "verdict": verdict or "needs_more_info",
            "full_jd_reviewed": bool(review.get("full_jd_reviewed")),
            "reviewer": review.get("reviewer") or "agent",
            "reasons": _strings(review.get("reasons")),
            "risks": _strings(review.get("risks")),
            "source_path": review.get("source_path"),
        },
    }
    return reviewed


def merge_seek_job_identity(card: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    merged = dict(detail)
    for key in ("title", "company", "location", "work_type"):
        card_value = str(card.get(key) or "").strip()
        detail_value = str(merged.get(key) or "").strip()
        if not card_value:
            continue
        if not detail_value or _same_compact_text(card_value, detail_value):
            merged[key] = card_value
    return merged


def _same_compact_text(left: str, right: str) -> bool:
    return _compact_text(left) == _compact_text(right)


def _compact_text(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _valid_profile(profile: dict[str, Any] | None) -> bool:
    return isinstance(profile, dict) and bool(_strings(profile.get("skills")) or _strings(profile.get("target_roles")))


def _experience_gate(*, title: str, job_text: str) -> dict[str, Any]:
    normalized_title = _match_normalized_text(title)
    normalized_text = _match_normalized_text(job_text)
    experience_text = _experience_pattern_text(job_text)
    range_matches = re.findall(r"\b(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*(?:years|yrs)\b", experience_text)
    for lower_text, upper_text in range_matches:
        lower = int(lower_text)
        upper = int(upper_text)
        if lower >= EXPERIENCE_HARD_SKIP_MIN_YEARS:
            return {"decision": "skip", "summary": f"experience_hard_skip: requires {lower}-{upper} years"}
        if upper >= EXPERIENCE_HARD_SKIP_MIN_YEARS or lower >= EXPERIENCE_REVIEW_MIN_YEARS:
            return {"decision": "need_user_review", "summary": f"experience_requires_review: requires {lower}-{upper} years"}

    for match in re.finditer(r"\b(?:at least|minimum|min)?\s*(\d{1,2})\s*(\+)?\s*(?:years|yrs)\b", experience_text):
        years = int(match.group(1))
        has_plus = bool(match.group(2))
        if years >= EXPERIENCE_HARD_SKIP_MIN_YEARS:
            suffix = "+" if has_plus else ""
            return {"decision": "skip", "summary": f"experience_hard_skip: requires {years}{suffix} years"}
        if years >= EXPERIENCE_REVIEW_MIN_YEARS:
            suffix = "+" if has_plus else ""
            return {"decision": "need_user_review", "summary": f"experience_requires_review: requires {years}{suffix} years"}

    senior_title = any(term in normalized_title.split() for term in SENIOR_TITLE_TERMS)
    if senior_title and any(term in normalized_text for term in SENIOR_REVIEW_TERMS):
        return {"decision": "need_user_review", "summary": "experience_requires_review: senior role with architecture or leadership signals"}
    return {"decision": "none", "summary": ""}


def _hard_requirement_gate(*, title: str, job_text: str, detail: dict[str, Any]) -> dict[str, Any]:
    normalized_title = _match_normalized_text(title)
    normalized_text = _match_normalized_text(job_text)
    if any(term in normalized_text for term in SECURITY_CLEARANCE_HARD_SKIP_TERMS) and (
        "citizen" in normalized_text or "citizenship" in normalized_text or "top secret special" in normalized_text
    ):
        return {
            "decision": "skip",
            "summary": "hard_requirement_skip: citizenship_or_national_security_clearance",
            "risk_flag": "citizenship_or_national_security_clearance_hard_skip",
        }
    if any(term in normalized_text for term in LONG_NZ_BACKGROUND_HARD_SKIP_TERMS) and (
        "citizen" in normalized_text or "security" in normalized_text or "background" in normalized_text
    ):
        return {
            "decision": "skip",
            "summary": "hard_requirement_skip: long_new_zealand_background_or_residence_requirement",
            "risk_flag": "long_new_zealand_background_or_residence_hard_skip",
        }

    classification = _match_normalized_text(detail.get("classification"))
    hardware_context = " ".join([normalized_title, classification, normalized_text])
    hardware_hit = any(term in hardware_context for term in HARDWARE_ELECTRICAL_CLASSIFICATION_TERMS)
    software_rescue = any(term in normalized_title for term in SOFTWARE_RESCUE_TERMS)
    if hardware_hit and not software_rescue:
        return {
            "decision": "skip",
            "summary": "hard_requirement_skip: hardware_or_electrical_engineering_role_outside_profile",
            "risk_flag": "hardware_or_electrical_engineering_role_hard_skip",
        }
    return {"decision": "none", "summary": "", "risk_flag": ""}


def _experience_pattern_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"[^a-z0-9+\-]+", " ", text)
    return " ".join(text.split())


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
    agent_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision_value = decision if decision in MATCH_DECISIONS else "need_user_review"
    payload = {
        "contract_version": "seek_job_match_decision_v1",
        "decision": decision_value,
        "score": score,
        "job_id": detail.get("job_id") or card.get("job_id"),
        "title": detail.get("title") or card.get("title"),
        "company": detail.get("company") or card.get("company"),
        "fit_summary": _fit_summary(
            decision=decision_value,
            score=score,
            positive=positive,
            negative=negative,
            unknowns=unknowns,
        ),
        "recommended_next_action": _recommended_next_action(decision_value),
        "positive_evidence": positive,
        "negative_evidence": negative,
        "unknowns": unknowns,
        "risk_flags": risk_flags,
        "trace_path": None,
    }
    if agent_review is not None:
        payload["agent_review"] = agent_review
    return payload


def _job_text(card: dict[str, Any], detail: dict[str, Any]) -> str:
    parts: list[str] = []
    for payload in (card, detail):
        for key in ("title", "company", "location", "work_type", "classification", "salary_text"):
            parts.append(str(payload.get(key) or ""))
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        parts.extend(_strings(evidence.get("texts")))
        for section in payload.get("description_sections") or []:
            if isinstance(section, dict):
                parts.append(str(section.get("text") or ""))
        for key in ("requirements", "responsibilities", "benefits"):
            parts.extend(_strings(payload.get(key)))
    return " ".join(parts).casefold()


def _agent_full_jd_review_required(profile: dict[str, Any]) -> bool:
    preferences = profile.get("job_search_preferences") if isinstance(profile.get("job_search_preferences"), dict) else {}
    policy = str(preferences.get("screening_policy") or preferences.get("suitability_policy") or "").casefold()
    return policy in {
        "agent_full_jd_review",
        "agent_full_jd_review_required",
        "agent_review_full_detail_required",
    }


def _agent_review_payload(*, card: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "job_suitability_agent_review_payload_v1",
        "instruction": "Use the full job detail text to decide suitability. Do not decide from title or keyword matches alone.",
        "card": {
            key: card.get(key)
            for key in ("job_id", "title", "company", "location", "work_type", "salary_text", "classification", "source_url")
            if card.get(key) is not None
        },
        "detail": {
            key: detail.get(key)
            for key in ("job_id", "title", "company", "location", "work_type", "salary_text", "classification", "source_url")
            if detail.get(key) is not None
        },
        "full_job_text": _job_text_for_agent(card=card, detail=detail),
    }


def _job_text_for_agent(*, card: dict[str, Any], detail: dict[str, Any]) -> str:
    parts: list[str] = []
    for payload in (card, detail):
        for key in ("title", "company", "location", "work_type", "classification", "salary_text", "source_url"):
            value = str(payload.get(key) or "").strip()
            if value:
                parts.append(f"{key}: {value}")
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        texts = _strings(evidence.get("texts"))
        if texts:
            parts.append("visible_card_or_ocr_text: " + " | ".join(texts))
        for section in payload.get("description_sections") or []:
            if isinstance(section, dict):
                text = str(section.get("text") or "").strip()
                if text:
                    parts.append(text)
        for key in ("requirements", "responsibilities", "benefits"):
            values = _strings(payload.get(key))
            if values:
                parts.append(f"{key}: " + " | ".join(values))
    return "\n".join(parts)


def _fit_summary(
    *,
    decision: str,
    score: float,
    positive: list[str],
    negative: list[str],
    unknowns: list[str],
) -> str:
    parts = [f"{decision} with score {score:.3f}"]
    if positive:
        parts.append("positive: " + "; ".join(positive[:3]))
    if negative:
        parts.append("negative: " + "; ".join(negative[:3]))
    if unknowns:
        parts.append("needs review: " + "; ".join(unknowns[:3]))
    return ". ".join(parts) + "."


def _recommended_next_action(decision: str) -> str:
    if decision == "strong_apply":
        return "open_apply_entry_and_prepare_safe_fields"
    if decision == "maybe_apply":
        return "review_then_optionally_open_apply_entry"
    if decision == "skip":
        return "skip_job"
    return "ask_user_or_gpt_for_review"


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


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").split())
        folded = cleaned.casefold()
        if cleaned and folded not in seen:
            seen.add(folded)
            unique.append(cleaned)
    return unique


def _identity_key(job_id: Any, title: Any, company: Any) -> str:
    if str(job_id or "").strip():
        return "id:" + _compact_text(str(job_id))
    basis = "|".join([str(title or ""), str(company or "")]).strip("|")
    return "tc:" + _compact_text(basis) if basis else ""


def _normalized_review_verdict(review: dict[str, Any]) -> str:
    for key in ("verdict", "decision", "suitability", "recommendation"):
        value = str(review.get(key) or "").strip().casefold()
        if value:
            return re.sub(r"[^a-z0-9_]+", "_", value).strip("_")
    return ""


def _contains(haystack: str, needle: str) -> bool:
    normalized_needle = _match_normalized_text(needle)
    if not normalized_needle:
        return False
    return normalized_needle in _match_normalized_text(haystack)


def _location_matches(job_location: str, constraint: str) -> bool:
    if _contains(job_location, constraint) or _contains(constraint, job_location):
        return True
    normalized_constraint = _match_normalized_text(constraint)
    if normalized_constraint not in {"new zealand", "nz", "aotearoa"}:
        return False
    normalized_location = _match_normalized_text(job_location)
    return any(term in normalized_location for term in NEW_ZEALAND_LOCATION_TERMS if term not in {"new zealand", "nz", "aotearoa"})


def _matches_role(haystack: str, role: str) -> bool:
    if _contains(haystack, role):
        return True
    haystack_tokens = set(_match_normalized_text(haystack).split())
    role_tokens = [token for token in _match_normalized_text(role).split() if len(token) >= 2]
    if not role_tokens:
        return False
    return all(token in haystack_tokens or any(item.endswith(token) for item in haystack_tokens) for token in role_tokens)


def _match_normalized_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"\bapls?\b", " api ", text)
    text = re.sub(r"\bal\b", " ai ", text)
    text = re.sub(r"[^a-z0-9+#.]+", " ", text)
    return " ".join(text.split())


def _stable_id(card: dict[str, Any], detail: dict[str, Any]) -> str:
    basis = "|".join(str(item or "") for item in [detail.get("title"), detail.get("company"), card.get("title")])
    digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]
    return f"seek_job_{digest}"
