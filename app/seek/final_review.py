from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.seek.application import _collect_visible_items, assess_seek_application_flow_state


SEEK_FINAL_REVIEW_EXTRACTION_CONTRACT = "seek_final_review_extraction_v1"
REVIEW_RECONCILIATION_CONTRACT = "review_reconciliation_v1"


def build_seek_final_review_extraction(
    fill_record: dict[str, Any] | None,
    *,
    observation: dict[str, Any] | None = None,
    flow_state: dict[str, Any] | None = None,
    screenshot_path: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Extract and reconcile the final SEEK review page before final submit.

    The extractor is intentionally read-only. It verifies that the current review
    page agrees with the saved fill record and that the final submit button is
    visible but was not clicked.
    """

    record = fill_record if isinstance(fill_record, dict) else {}
    observed = observation if isinstance(observation, dict) else {}
    state = flow_state if isinstance(flow_state, dict) else assess_seek_application_flow_state(observed)
    items = _collect_visible_items(observed)
    texts = [str(item.get("text") or "") for item in items if str(item.get("text") or "").strip()]
    haystack = _normalized_join(texts)

    expected = _expected_review_payload(record)
    resume = _match_expected_text(expected.get("resume"), haystack)
    cover_letter = _match_cover_letter(expected.get("cover_letter"), haystack)
    questions = _match_questions(expected.get("employer_questions"), haystack)
    profile = _profile_reconciliation(record)

    blocker = state.get("final_submit_visible_blocker") if isinstance(state.get("final_submit_visible_blocker"), dict) else {}
    submit_application_visible = bool(blocker.get("blocked")) or _contains_submit_application(texts)
    submit_clicks = int(record.get("submit_clicks") or (1 if record.get("final_submit_clicked") else 0))
    final_submissions = int(record.get("final_submissions") or (1 if record.get("final_submit_clicked") else 0))
    current_step = str(state.get("current_step") or record.get("stage") or "")
    review_step_detected = current_step == "review_and_submit" or str(record.get("stage") or "") == "review_before_submit"

    reconciliation = {
        "contract_version": REVIEW_RECONCILIATION_CONTRACT,
        "status": "pass",
        "checks": {
            "review_step_detected": review_step_detected,
            "submit_application_visible": submit_application_visible,
            "submit_clicks": submit_clicks,
            "final_submissions": final_submissions,
            "resume_verified": resume["matched"],
            "cover_letter_latest_hash": cover_letter["sha256"],
            "cover_letter_verified": cover_letter["matched"],
            "employer_questions_expected": questions["expected_count"],
            "employer_questions_matched": questions["matched_count"],
            "profile_not_mutated": profile["profile_not_mutated"],
        },
        "missing": [],
        "mismatched": [],
        "safety_decision": "stop_before_final_submit",
    }
    if not review_step_detected:
        reconciliation["missing"].append("review_step_detected")
    if not submit_application_visible:
        reconciliation["missing"].append("submit_application_visible")
    if submit_clicks != 0 or final_submissions != 0:
        reconciliation["mismatched"].append("final_submission_counters")
        reconciliation["safety_decision"] = "unsafe_final_submit_counter_seen"
    if not resume["matched"]:
        reconciliation["missing"].append("resume")
    if not cover_letter["matched"]:
        reconciliation["missing"].append("cover_letter")
    if questions["matched_count"] != questions["expected_count"]:
        reconciliation["missing"].extend(item["question"] for item in questions["missing"])
    if not profile["profile_not_mutated"]:
        reconciliation["mismatched"].append("profile_mutation")
    if reconciliation["missing"] or reconciliation["mismatched"]:
        reconciliation["status"] = "needs_review"

    return {
        "contract_version": SEEK_FINAL_REVIEW_EXTRACTION_CONTRACT,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(),
        "source": {
            "record_contract": record.get("contract_version"),
            "observation_contract": observed.get("contract_version"),
            "trace_path": observed.get("trace_path"),
            "screenshot_path": str(screenshot_path) if screenshot_path else None,
        },
        "job_id": record.get("job_id") or (record.get("job") or {}).get("job_id"),
        "job_title": record.get("job_title") or (record.get("job") or {}).get("title"),
        "current_step": current_step or None,
        "submit_application_visible": submit_application_visible,
        "submit_clicks": submit_clicks,
        "final_submissions": final_submissions,
        "observed_text_count": len(texts),
        "observed_text_sample": texts[:80],
        "resume": resume,
        "cover_letter": cover_letter,
        "employer_questions": questions,
        "profile": profile,
        "review_reconciliation": reconciliation,
        "status": "pass" if reconciliation["status"] == "pass" else "needs_review",
    }


def _expected_review_payload(record: dict[str, Any]) -> dict[str, Any]:
    content = record.get("filled_content") if isinstance(record.get("filled_content"), dict) else {}
    fields = [field for field in record.get("filled_fields") or [] if isinstance(field, dict)]
    resume = content.get("resume") or _field_value(fields, "choose_documents", "resume")
    cover_letter = content.get("cover_letter") or _field_value(fields, "choose_documents", "cover_letter")
    questions = content.get("employer_questions") if isinstance(content.get("employer_questions"), list) else []
    if not questions:
        questions = [
            {"question": field.get("field"), "answer": field.get("value"), "evidence": field.get("evidence")}
            for field in fields
            if str(field.get("step") or "") == "answer_employer_questions"
        ]
    return {
        "resume": str(resume or ""),
        "cover_letter": str(cover_letter or ""),
        "employer_questions": [question for question in questions if isinstance(question, dict)],
    }


def _field_value(fields: list[dict[str, Any]], step: str, field_name: str) -> str:
    for field in fields:
        if str(field.get("step") or "") == step and str(field.get("field") or "") == field_name:
            return str(field.get("value") or "")
    return ""


def _profile_reconciliation(record: dict[str, Any]) -> dict[str, Any]:
    fields = [field for field in record.get("filled_fields") or [] if isinstance(field, dict)]
    persistent = [
        field
        for field in fields
        if str(field.get("step") or "") == "update_seek_profile"
        and str(field.get("policy") or "") != "do_not_mutate_profile_without_explicit_user_approval"
    ]
    return {
        "profile_not_mutated": len(persistent) == 0,
        "persistent_profile_updates": len(persistent),
        "policy": "no_profile_mutation_without_explicit_user_approval",
    }


def _match_questions(questions: Any, haystack: str) -> dict[str, Any]:
    expected = [question for question in questions or [] if isinstance(question, dict)]
    summary_count = _review_answered_count(haystack)
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for index, question in enumerate(expected, start=1):
        question_text = str(question.get("question") or f"question_{index}")
        answer = str(question.get("answer") or "")
        question_matched = _match_expected_text(question_text, haystack, allow_short=False)["matched"]
        answer_match = _match_expected_text(answer, haystack, allow_short=True)
        item = {
            "index": index,
            "question": question_text,
            "answer": answer,
            "question_matched": question_matched,
            "answer_matched": answer_match["matched"],
            "answer_match_reason": answer_match["reason"],
        }
        if item["answer_matched"] and (item["question_matched"] or len(_normalize(question_text)) < 20):
            matched.append(item)
        else:
            missing.append(item)
    if missing and summary_count == len(expected):
        matched = [
            {
                "index": index,
                "question": str(question.get("question") or f"question_{index}"),
                "answer": str(question.get("answer") or ""),
                "question_matched": False,
                "answer_matched": True,
                "answer_match_reason": "review_summary_count_match",
            }
            for index, question in enumerate(expected, start=1)
        ]
        missing = []
    return {
        "expected_count": len(expected),
        "matched_count": len(matched),
        "verification_depth": "answer_text" if summary_count is None or not expected or summary_count != len(expected) else "summary_count",
        "review_summary_answered_count": summary_count,
        "matched": matched,
        "missing": missing,
    }


def _match_cover_letter(cover_letter: Any, haystack: str) -> dict[str, Any]:
    value = str(cover_letter or "")
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None
    snippets = _cover_letter_snippets(value)
    matched_snippets = [snippet for snippet in snippets if _normalize(snippet) and _normalize(snippet) in haystack]
    normalized_full = _normalize(value)
    matched = bool(value) and (
        normalized_full in haystack
        or len(matched_snippets) >= min(2, len(snippets))
        or (len(snippets) == 1 and bool(matched_snippets))
        or "youwroteacoverletterforthisapplication" in haystack
    )
    return {
        "matched": matched,
        "sha256": digest,
        "length": len(value),
        "matched_snippets": matched_snippets[:8],
        "expected_snippet_count": len(snippets),
        "reason": (
            "matched_review_text"
            if matched_snippets or normalized_full in haystack
            else (
                "review_summary_cover_letter_written"
                if matched
                else "expected_cover_letter_not_found_in_review_text"
            )
        ),
    }


def _match_expected_text(value: Any, haystack: str, *, allow_short: bool = True) -> dict[str, Any]:
    text = str(value or "").strip()
    normalized = _normalize(text)
    if not normalized:
        return {"matched": False, "reason": "empty_expected_text", "value": text}
    if normalized in haystack:
        return {"matched": True, "reason": "exact_normalized_text_match", "value": text}
    snippets = _text_snippets(text, allow_short=allow_short)
    matched = [snippet for snippet in snippets if _normalize(snippet) in haystack]
    if matched:
        return {"matched": True, "reason": "snippet_match", "value": text, "matched_snippets": matched[:5]}
    return {"matched": False, "reason": "expected_text_not_found", "value": text}


def _contains_submit_application(texts: list[str]) -> bool:
    for text in texts:
        normalized = " ".join(str(text).casefold().split())
        if normalized in {"submit application", "send application", "complete application"}:
            return True
    return False


def _review_answered_count(haystack: str) -> int | None:
    match = re.search(r"youanswered(\d+)outof(\d+)", haystack)
    if not match:
        return None
    answered = int(match.group(1))
    total = int(match.group(2))
    return answered if answered == total else None


def _normalized_join(texts: list[str]) -> str:
    return " ".join(_normalize(text) for text in texts if _normalize(text))


def _normalize(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(text).casefold())


def _cover_letter_snippets(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if len(line.strip()) >= 20]
    snippets: list[str] = []
    for line in lines:
        snippets.extend(_text_snippets(line, allow_short=False, max_items=2))
    return _dedupe(snippets)[:10]


def _text_snippets(text: str, *, allow_short: bool, max_items: int = 4) -> list[str]:
    value = " ".join(str(text or "").split())
    if not value:
        return []
    if len(value) <= 28:
        return [value] if allow_short else []
    without_parenthetical = re.sub(r"\([^)]*\)", "", value).strip()
    sentence_parts = [part.strip() for part in re.split(r"[.;!?]\s+", value) if len(part.strip()) >= 20]
    snippets: list[str] = []
    if without_parenthetical and without_parenthetical != value and (allow_short or len(without_parenthetical) >= 12):
        snippets.append(without_parenthetical)
    snippets.extend(sentence_parts[:max_items])
    if not snippets:
        snippets.append(value[:100])
    if len(value) > 140:
        snippets.append(value[-100:])
    return _dedupe(snippets)[:max_items]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalize(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result
