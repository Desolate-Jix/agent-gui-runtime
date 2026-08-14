from __future__ import annotations

import hashlib
import re
from typing import Any

from app.agent.form_question_contracts import build_form_question_contract
from app.agent.form_question_understanding import normalize_form_question_intent


DECISION_CONTRACT_VERSION = "form_answer_decision_v1"
PLAN_CONTRACT_VERSION = "form_answer_plan_v1"

SENSITIVE_PATTERNS = (
    r"\bethnic(?:ity| background)\b",
    r"\brace\b",
    r"\bgender(?: identity)?\b",
    r"\bsex assigned\b",
    r"\bdisabilit(?:y|ies)\b",
    r"\bhealth\b",
    r"\bmedical condition\b",
    r"\bcriminal (?:history|record)\b",
    r"\bconviction\b",
)
REVIEW_PATTERNS = (
    r"\bsalary\b",
    r"\bcompensation\b",
    r"\bremuneration\b",
    r"\brelocat(?:e|ion)\b",
    r"\bvisa\b",
    r"\bsponsorship\b",
    r"\bright to work\b",
    r"\bwork rights?\b",
)
FINAL_LABELS = {
    "submit",
    "submit application",
    "send",
    "send application",
    "complete",
    "complete application",
    "confirm",
    "confirm application",
    "review and submit",
}


def plan_form_answer(
    *,
    question: dict[str, Any] | None,
    evidence: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    contract = build_form_question_contract(question)
    understanding = normalize_form_question_intent(contract)
    evidence_items = [item for item in evidence or [] if isinstance(item, dict)]
    policy, reason, selected = _classify(contract, evidence_items, understanding)
    value = _clean(selected.get("value")) if selected else ""
    evidence_id = _clean(selected.get("evidence_id")) if selected else ""
    return {
        "contract_version": DECISION_CONTRACT_VERSION,
        "question_id": contract["question_id"],
        "label": contract["label"],
        "field_type": contract["field_type"],
        "question_understanding": understanding,
        "policy": policy,
        "reason": reason,
        "evidence_refs": [evidence_id] if evidence_id else [],
        "value_reference": evidence_id or None,
        "proposed_value": None,
        "value_preview": _redacted_preview(value, field_type=contract["field_type"]) if value else None,
        "value_length": len(value),
        "value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None,
        "pii_redacted": True,
        "artifact_is_authorization": False,
    }


def build_form_answer_plan(
    *,
    inventory: dict[str, Any] | None,
    evidence: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    payload = inventory if isinstance(inventory, dict) else {}
    questions = _inventory_items(payload)
    decisions = [plan_form_answer(question=question, evidence=evidence) for question in questions]
    counts: dict[str, int] = {}
    for decision in decisions:
        policy = str(decision["policy"])
        counts[policy] = counts.get(policy, 0) + 1
    return {
        "contract_version": PLAN_CONTRACT_VERSION,
        "source_contract": payload.get("contract_version"),
        "capture_id": payload.get("capture_id"),
        "decisions": decisions,
        "policy_counts": counts,
        "pii_redacted": True,
        "fill_attempted": False,
        "submit_attempted": False,
        "artifact_is_authorization": False,
    }


def _classify(
    question: dict[str, Any],
    evidence: list[dict[str, Any]],
    understanding: dict[str, Any],
) -> tuple[str, str, dict[str, Any] | None]:
    label = _clean(question.get("label")).casefold()
    risk = _clean(question.get("risk")).casefold()
    field_type = _clean(question.get("field_type")).casefold()
    if risk == "final_submit" or label in FINAL_LABELS:
        return "final_submit", "final_submit_is_not_answerable", None
    if risk == "unsupported_file_upload" or field_type == "file_upload":
        reviewed_file = _reviewed_file_evidence(question, evidence)
        if reviewed_file:
            return (
                "reviewed_file_upload",
                "human_reviewed_single_use_file_available",
                reviewed_file,
            )
        return "unsupported", "file_upload_requires_user_review", None
    normalized_policy = _clean(understanding.get("recommended_policy")).casefold()
    normalized_intent = _clean(understanding.get("intent")).casefold()
    if normalized_policy == "blocked_sensitive":
        return "blocked_sensitive", "sensitive_question_requires_human_control", None
    if normalized_policy == "needs_user_review" and normalized_intent not in {
        "unknown_open_text",
        "unknown_question",
    }:
        return "needs_user_review", "normalized_question_requires_review", None
    if _matches_any(label, SENSITIVE_PATTERNS):
        return "blocked_sensitive", "sensitive_question_requires_human_control", None
    if _matches_any(label, REVIEW_PATTERNS):
        return "needs_user_review", "negotiable_or_complex_question", None
    if question.get("disabled") is True:
        return "needs_user_review", "field_disabled", None

    derived = _reviewed_derived_evidence(question, evidence)
    if derived:
        return "derived_with_evidence", "reviewed_question_specific_answer", derived

    if normalized_policy == "needs_user_review":
        return "needs_user_review", "unknown_or_unmapped_question", None

    field_key = _profile_field_key(question)
    profile_evidence = _reviewed_profile_evidence(field_key, evidence) if field_key else None
    if profile_evidence:
        return "auto_fill", "reviewed_profile_evidence_available", profile_evidence
    return "needs_user_review", "unknown_or_unmapped_question", None


def _inventory_items(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for collection in ("questions", "fields"):
        for item in inventory.get(collection) or []:
            if not isinstance(item, dict):
                continue
            item_id = _clean(item.get("question_id") or item.get("field_id") or item.get("id"))
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            items.append(item)
    for action in inventory.get("danger_actions") or []:
        if not isinstance(action, dict):
            continue
        action_id = _clean(action.get("action_id") or action.get("id"))
        if action_id and action_id in seen_ids:
            continue
        if action_id:
            seen_ids.add(action_id)
        items.append(action)
    return items


def _reviewed_derived_evidence(
    question: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any] | None:
    question_id = _clean(question.get("question_id"))
    for item in evidence:
        if (
            item.get("reviewed") is True
            and _clean(item.get("kind")).casefold() == "derived_answer"
            and _clean(item.get("question_id")) == question_id
            and _clean(item.get("evidence_id"))
            and _clean(item.get("value"))
        ):
            return item
    return None


def _reviewed_file_evidence(
    question: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> dict[str, Any] | None:
    question_id = _clean(question.get("question_id"))
    for item in evidence:
        if (
            item.get("contract_version") == "reviewed_file_evidence_v1"
            and _clean(item.get("kind")).casefold() == "reviewed_file"
            and item.get("reviewed") is True
            and item.get("human_approved") is True
            and item.get("single_use") is True
            and _clean(item.get("question_id")) == question_id
            and _clean(item.get("evidence_id"))
        ):
            return item
    return None


def _reviewed_profile_evidence(field_key: str, evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in evidence:
        if (
            item.get("reviewed") is True
            and _clean(item.get("field_key")).casefold() == field_key
            and _clean(item.get("evidence_id"))
            and _clean(item.get("value"))
        ):
            return item
    return None


def _profile_field_key(question: dict[str, Any]) -> str | None:
    label = _clean(question.get("label")).casefold()
    field_type = _clean(question.get("field_type")).casefold()
    if "preferred name" in label:
        return "preferred_name"
    if "first name" in label or "given name" in label:
        return "first_name"
    if "last name" in label or "family name" in label or "surname" in label:
        return "last_name"
    if field_type == "email" or "email" in label:
        return "email"
    if field_type == "phone" or "phone" in label or "mobile" in label:
        return "phone"
    return None


def _matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, value) for pattern in patterns)


def _redacted_preview(value: str, *, field_type: str) -> str:
    kind = field_type if field_type in {"email", "phone"} else "profile_value"
    return f"<redacted:{kind}:len={len(value)}>"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
