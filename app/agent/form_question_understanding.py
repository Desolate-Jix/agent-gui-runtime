from __future__ import annotations

import re
from typing import Any

from app.agent.form_question_contracts import build_form_question_contract


CONTRACT_VERSION = "normalized_question_intent_v1"

_WORK_AUTH_POSITIVE = (
    ("right_to_work", re.compile(r"\bright(?:s)? to work\b")),
    ("authorized_to_work", re.compile(r"\b(?:legally )?(?:authori[sz]ed|eligible|entitled) to work\b")),
    (
        "work_without_sponsorship",
        re.compile(r"\b(?:can|able to|eligible to)?\s*work\b[^?]{0,80}\bwithout\b[^?]{0,40}\bsponsorship\b"),
    ),
)
_WORK_AUTH_NEGATED_REQUIREMENT = (
    (
        "negated_sponsorship_question",
        re.compile(
            r"\b(?:do|does|will|would)\s+(?:i|you|they|the applicant)\s+not\s+"
            r"(?:currently\s+|now\s+)?(?:require|need)\b[^?]{0,60}?\bsponsorship\b"
        ),
    ),
    (
        "negated_sponsorship_statement",
        re.compile(
            r"\b(?:i|we|the applicant)\b[^.?]{0,30}\b(?:do|does|will|would)\s+not\s+"
            r"(?:currently\s+|now\s+)?(?:require|need)\b[^?]{0,60}?\bsponsorship\b"
        ),
    ),
)
_WORK_AUTH_NEGATIVE = (
    (
        "requires_sponsorship",
        re.compile(r"\b(?:require|requires|required|requiring|need|needs|needed)\b[^?]{0,60}?\bsponsorship\b"),
    ),
    ("sponsorship_required", re.compile(r"\bsponsorship\b[^?]{0,40}\b(?:required|needed)\b")),
    (
        "unable_without_sponsorship",
        re.compile(r"\bunable to work\b[^?]{0,60}\bwithout\b[^?]{0,40}\bsponsorship\b"),
    ),
)
_INTENT_PATTERNS = (
    (
        "criminal_history",
        "sensitive",
        "blocked_sensitive",
        0.98,
        (r"\bcriminal (?:history|record)\b", r"\bconviction(?:s)?\b", r"\bcriminal offence(?:s)?\b"),
    ),
    (
        "health_information",
        "sensitive",
        "blocked_sensitive",
        0.98,
        (r"\bhealth\b", r"\bmedical condition(?:s)?\b", r"\bmedical history\b"),
    ),
    (
        "demographic_identity",
        "sensitive",
        "blocked_sensitive",
        0.98,
        (r"\bethnic(?:ity| background)\b", r"\brace\b", r"\bgender(?: identity)?\b", r"\bsex assigned\b"),
    ),
    (
        "disability_information",
        "sensitive",
        "blocked_sensitive",
        0.98,
        (r"\bdisabilit(?:y|ies)\b",),
    ),
    (
        "salary_expectation",
        "negotiable",
        "needs_user_review",
        0.96,
        (r"\bsalary\b", r"\bcompensation\b", r"\bremuneration\b", r"\bpay expectation(?:s)?\b"),
    ),
    (
        "relocation_willingness",
        "consequential",
        "needs_user_review",
        0.95,
        (r"\brelocat(?:e|ion|ing)\b",),
    ),
)
_VISA_STATUS_PATTERNS = (
    re.compile(r"\bvisa(?: status| type| conditions?| requirements?)?\b"),
    re.compile(r"\bwork permit\b"),
    re.compile(r"\bsponsorship requirements?\b"),
)
_OPEN_PROMPT = re.compile(r"^(?:tell|describe|explain|why|what|how|please describe)\b")
_PROFILE_FIELD_PATTERNS = (
    re.compile(r"\b(?:first|given|preferred|last|family) name\b"),
    re.compile(r"\bsurname\b"),
    re.compile(r"\bemail(?: address)?\b"),
    re.compile(r"\b(?:phone|mobile)(?: number)?\b"),
)


def normalize_form_question_intent(question: dict[str, Any] | None) -> dict[str, Any]:
    contract = build_form_question_contract(question)
    label = _clean(contract.get("label")).casefold()
    negated_requirement = _pattern_evidence(label, _WORK_AUTH_NEGATED_REQUIREMENT)
    positive = _pattern_evidence(label, _WORK_AUTH_POSITIVE) + negated_requirement
    negative = _pattern_evidence(label, _WORK_AUTH_NEGATIVE)
    negative = _without_overlapping_evidence(negative, negated_requirement)

    if positive or negative:
        if positive and negative:
            return _result(
                contract,
                intent="authorized_to_work_without_sponsorship",
                polarity="ambiguous",
                risk="controlled_review",
                confidence=0.0,
                recommended_policy="needs_user_review",
                evidence=positive + negative,
                blockers=["conflicting_polarity_evidence"],
            )
        return _result(
            contract,
            intent="authorized_to_work_without_sponsorship",
            polarity=(
                "affirmative_means_intent_true"
                if positive
                else "affirmative_means_intent_false"
            ),
            risk="controlled_review",
            confidence=0.96,
            recommended_policy="needs_user_review",
            evidence=positive or negative,
            blockers=["reviewed_answer_required"],
        )

    for intent, risk, policy, confidence, patterns in _INTENT_PATTERNS:
        evidence = _regex_evidence(label, intent, patterns)
        if evidence:
            return _result(
                contract,
                intent=intent,
                polarity="neutral",
                risk=risk,
                confidence=confidence,
                recommended_policy=policy,
                evidence=evidence,
                blockers=[
                    "sensitive_question_requires_human_control"
                    if policy == "blocked_sensitive"
                    else "reviewed_answer_required"
                ],
            )

    visa_evidence = _compiled_evidence(label, "visa_status", _VISA_STATUS_PATTERNS)
    if visa_evidence:
        return _result(
            contract,
            intent="visa_status",
            polarity="neutral",
            risk="complex",
            confidence=0.82,
            recommended_policy="needs_user_review",
            evidence=visa_evidence,
            blockers=["reviewed_answer_required"],
        )

    profile_evidence = _compiled_evidence(label, "profile_field", _PROFILE_FIELD_PATTERNS)
    if profile_evidence:
        return _result(
            contract,
            intent="reviewed_profile_field",
            polarity="neutral",
            risk="ordinary",
            confidence=0.9,
            recommended_policy="policy_lookup_allowed",
            evidence=profile_evidence,
            blockers=[],
        )

    field_type = _clean(contract.get("field_type")).casefold()
    open_text = field_type in {"textarea", "multiline", "long_text"} or bool(_OPEN_PROMPT.search(label))
    return _result(
        contract,
        intent="unknown_open_text" if open_text else "unknown_question",
        polarity="unknown",
        risk="unknown",
        confidence=0.2,
        recommended_policy="needs_user_review",
        evidence=[],
        blockers=["unrecognized_question_intent"],
    )


def _result(
    contract: dict[str, Any],
    *,
    intent: str,
    polarity: str,
    risk: str,
    confidence: float,
    recommended_policy: str,
    evidence: list[dict[str, Any]],
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "source_contract": contract.get("contract_version"),
        "question_id": contract.get("question_id"),
        "intent": intent,
        "polarity": polarity,
        "risk": risk,
        "confidence": confidence,
        "answer_shape": _answer_shape(contract),
        "recommended_policy": recommended_policy,
        "evidence": evidence,
        "blockers": blockers,
        "artifact_is_authorization": False,
    }


def _answer_shape(contract: dict[str, Any]) -> str:
    labels = {_clean(item.get("label")).casefold() for item in contract.get("options") or []}
    if {"yes", "no"}.issubset(labels):
        return "boolean"
    field_type = _clean(contract.get("field_type")).casefold()
    if field_type in {"textarea", "multiline", "long_text"}:
        return "open_text"
    if contract.get("options"):
        return "choice"
    return "text" if field_type in {"text", "email", "phone", "url"} else "unknown"


def _pattern_evidence(
    label: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for pattern_id, pattern in patterns:
        for match in pattern.finditer(label):
            evidence.append(
                {
                    "evidence_type": "matched_pattern",
                    "pattern_id": pattern_id,
                    "matched_text": match.group(0),
                    "match_span": [match.start(), match.end()],
                }
            )
    return evidence


def _without_overlapping_evidence(
    evidence: list[dict[str, Any]],
    exclusions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    exclusion_spans = [item.get("match_span") for item in exclusions]
    return [
        item
        for item in evidence
        if not any(_spans_overlap(item.get("match_span"), span) for span in exclusion_spans)
    ]


def _spans_overlap(left: Any, right: Any) -> bool:
    if not (
        isinstance(left, list)
        and len(left) == 2
        and isinstance(right, list)
        and len(right) == 2
    ):
        return False
    return int(left[0]) < int(right[1]) and int(right[0]) < int(left[1])


def _regex_evidence(label: str, pattern_id: str, patterns: tuple[str, ...]) -> list[dict[str, Any]]:
    return _compiled_evidence(label, pattern_id, tuple(re.compile(pattern) for pattern in patterns))


def _compiled_evidence(
    label: str,
    pattern_id: str,
    patterns: tuple[re.Pattern[str], ...],
) -> list[dict[str, Any]]:
    matches = [pattern.search(label) for pattern in patterns]
    return [
        {
            "evidence_type": "matched_pattern",
            "pattern_id": pattern_id,
            "matched_text": match.group(0),
        }
        for match in matches
        if match
    ]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
