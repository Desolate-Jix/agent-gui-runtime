from __future__ import annotations

import re
from typing import Any


FINAL_SUBMIT_TERMS = {
    "review and submit",
    "submit application",
    "submit your application",
    "send application",
    "complete application",
    "finish application",
    "confirm application",
    "send your application",
    "complete your application",
    "submit",
}

LOGIN_TERMS = {"sign in", "log in", "login", "create account", "register"}
CAPTCHA_TERMS = {"captcha", "recaptcha", "i'm not a robot", "verification code"}
REVIEW_STEP_TERMS = {"review your application", "review application", "application review"}
THIRD_PARTY_ATS_TERMS = {
    "workday",
    "greenhouse",
    "lever",
    "smartrecruiters",
    "jobvite",
    "taleo",
    "successfactors",
    "bamboohr",
    "ashby",
    "workable",
}
UPLOAD_TERMS = {
    "upload resume",
    "upload cv",
    "upload cover letter",
    "attach resume",
    "attach cv",
    "attach cover letter",
}
RISKY_FORM_TERMS = {
    "salary",
    "expected salary",
    "notice period",
    "start date",
    "available to start",
    "relocate",
    "relocation",
    "visa",
    "work rights",
    "right to work",
    "background check",
    "criminal",
    "conviction",
    "health declaration",
    "medical",
}
FORM_TERMS = {"form", "question", "answer", "required field", "textarea"}
COVER_LETTER_TERMS = {"cover letter", "supporting statement"}
SCREENING_QUESTION_TERMS = {"screening question", "employer questions", "application questions"}
APPLICATION_FLOW_TERMS = {
    "apply with seek",
    "quick apply",
    "application",
    "your application",
    "cover letter",
    "resume",
    "cv",
    "screening question",
}


def assess_seek_application_flow_state(
    observation: dict[str, Any] | None,
    *,
    source_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify the page reached immediately after clicking SEEK Apply / Quick Apply."""

    payload = observation if isinstance(observation, dict) else {}
    items = _collect_visible_items(payload)
    texts = [item["text"] for item in items]
    haystack = " ".join(texts).casefold()
    flags: list[str] = []
    detected_states: list[str] = []
    state_type = "unknown_after_apply"
    stop_reason = "apply_entry_state_unclear_stop_before_form_fill"
    final_submit_blocker = _final_submit_visible_blocker(items)
    form_inventory = _application_form_inventory(items)

    if final_submit_blocker["blocked"]:
        state_type = "final_submit_visible"
        stop_reason = "final_submit_visible_stop_before_submission"
        flags.append("final_submit_visible")
        detected_states.append("final_submit_detected")
    elif _contains_any(haystack, LOGIN_TERMS):
        state_type = "login_required"
        stop_reason = "login_required"
        flags.append("login_required")
        detected_states.append("login_required")
    elif _contains_any(haystack, CAPTCHA_TERMS):
        state_type = "captcha_or_verification"
        stop_reason = "captcha_or_verification_required"
        flags.append("captcha_or_verification_required")
        detected_states.append("captcha_or_verification_required")
    elif _contains_any(haystack, THIRD_PARTY_ATS_TERMS):
        state_type = "third_party_ats"
        stop_reason = "third_party_ats_requires_user_review"
        flags.append("third_party_ats")
        detected_states.append("external_application_detected")
    elif _contains_any(haystack, UPLOAD_TERMS):
        state_type = "resume_upload_required"
        stop_reason = "resume_or_attachment_upload_requires_user_review"
        flags.append("resume_upload_required")
        detected_states.append("resume_upload_required")
    elif _contains_any(haystack, RISKY_FORM_TERMS):
        state_type = "risky_application_questions"
        stop_reason = "risky_application_questions_require_user_or_gpt_decision"
        flags.append("risky_questions_present")
        detected_states.append("risky_application_questions")
    elif _contains_any(haystack, REVIEW_STEP_TERMS):
        state_type = "review_step_detected"
        stop_reason = "review_step_stop_before_final_submit"
        detected_states.append("review_step_detected")
    elif form_inventory["screening_questions_detected"]:
        state_type = "screening_questions_detected"
        stop_reason = "screening_questions_stop_before_form_fill"
        detected_states.append("screening_questions_detected")
    elif form_inventory["cover_letter_field_detected"]:
        state_type = "cover_letter_field_detected"
        stop_reason = "cover_letter_field_detected_stop_before_paste"
        detected_states.append("cover_letter_field_detected")
    elif form_inventory["application_form_detected"]:
        state_type = "application_form_detected"
        stop_reason = "application_form_detected_stop_before_form_fill"
        detected_states.append("application_form_detected")
    elif _contains_any(haystack, APPLICATION_FLOW_TERMS):
        state_type = "application_flow_opened"
        stop_reason = "application_flow_opened_stop_before_form_fill"
        detected_states.append("application_flow_opened")
    else:
        flags.append("unknown_application_state")
        detected_states.append("unknown_application_state")

    return {
        "contract_version": "seek_application_flow_state_v1",
        "status": "blocked_need_user_or_gpt_decision",
        "state_type": state_type,
        "detected_states": detected_states,
        "stop_reason": stop_reason,
        "application_flow_started": state_type not in {"unknown_after_apply"},
        "final_submit_visible": bool(final_submit_blocker["blocked"]),
        "final_submit_visible_blocker": final_submit_blocker,
        "final_submission_performed": False,
        "risk_flags": flags,
        "application_form_inventory": form_inventory,
        "trace_path": payload.get("trace_path"),
        "source_job": {
            "job_id": (source_job or {}).get("job_id"),
            "title": (source_job or {}).get("title"),
            "company": (source_job or {}).get("company"),
        },
        "evidence": {
            "texts": texts[:120],
            "text_count": len(texts),
        },
    }


def _collect_visible_texts(payload: dict[str, Any]) -> list[str]:
    return [item["text"] for item in _collect_visible_items(payload)]


def _collect_visible_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    inventory = payload.get("screen_inventory") if isinstance(payload.get("screen_inventory"), dict) else {}
    items: list[dict[str, Any]] = []
    for collection_name in ("page_elements", "available_actions", "cards"):
        for item in inventory.get(collection_name) or []:
            if not isinstance(item, dict):
                continue
            text = _clean_text(item.get("text") or item.get("label"))
            if text:
                items.append(
                    {
                        "collection": collection_name,
                        "id": item.get("id") or item.get("element_id") or item.get("action_id") or item.get("card_id"),
                        "text": text,
                        "role": _clean_text(item.get("role") or item.get("semantic_role") or item.get("type")),
                        "bbox": item.get("bbox") or item.get("card_bbox"),
                    }
                )
    return items


def _final_submit_visible_blocker(items: list[dict[str, Any]]) -> dict[str, Any]:
    matched_terms: list[str] = []
    matched_items: list[dict[str, Any]] = []
    for item in items:
        text = str(item.get("text") or "")
        item_terms = _final_submit_terms_in_text(text)
        if not item_terms:
            continue
        if _is_negative_or_instructional_submit_text(text):
            continue
        if not _is_final_submit_action_like(item, text):
            continue
        matched_terms.extend(item_terms)
        matched_items.append(
            {
                "collection": item.get("collection"),
                "id": item.get("id"),
                "text": text,
                "role": item.get("role"),
                "bbox": item.get("bbox"),
                "matched_terms": item_terms,
            }
        )
    return {
        "contract_version": "final_submit_visible_blocker_v1",
        "enabled": True,
        "blocked": bool(matched_items),
        "matched_terms": sorted(set(matched_terms)),
        "matched_items": matched_items[:20],
        "reason": "final_submit_visible_stop_before_submission" if matched_items else "no_final_submit_visible",
    }


def _final_submit_terms_in_text(text: str) -> list[str]:
    key = text.casefold()
    matched: list[str] = []
    for term in FINAL_SUBMIT_TERMS:
        pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
        if re.search(pattern, key):
            matched.append(term)
    return matched


def _is_negative_or_instructional_submit_text(text: str) -> bool:
    key = text.casefold()
    negative_markers = (
        "do not",
        "don't",
        "never",
        "must not",
        "should not",
        "not click",
        "not press",
        "forbidden",
        "禁止",
        "不要",
        "不能",
        "不允许",
    )
    return any(marker in key for marker in negative_markers)


def _is_final_submit_action_like(item: dict[str, Any], text: str) -> bool:
    collection = str(item.get("collection") or "").casefold()
    role = str(item.get("role") or "").casefold()
    if collection == "available_actions":
        return True
    if any(token in role for token in ("button", "link", "action", "menuitem", "submit")):
        return True
    normalized = _clean_text(text)
    if len(normalized) <= 32 and len(normalized.split()) <= 4:
        return True
    return False


def _application_form_inventory(items: list[dict[str, Any]]) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for item in items:
        text = str(item.get("text") or "")
        role = str(item.get("role") or "")
        key = f"{text} {role}".casefold()
        compact = {
            "collection": item.get("collection"),
            "id": item.get("id"),
            "text": text,
            "role": role,
            "bbox": item.get("bbox"),
        }
        if item.get("collection") == "available_actions":
            actions.append(compact)
        if _contains_any(key, FORM_TERMS | COVER_LETTER_TERMS | SCREENING_QUESTION_TERMS) or "input" in key or "textarea" in key:
            fields.append(compact)
    haystack = " ".join(str(item.get("text") or "") for item in items).casefold()
    return {
        "contract_version": "application_form_inventory_v1",
        "application_form_detected": bool(fields) or _contains_any(haystack, APPLICATION_FLOW_TERMS | FORM_TERMS),
        "cover_letter_field_detected": _contains_any(haystack, COVER_LETTER_TERMS),
        "screening_questions_detected": _contains_any(haystack, SCREENING_QUESTION_TERMS),
        "field_count": len(fields),
        "action_count": len(actions),
        "fields": fields[:40],
        "actions": actions[:40],
    }


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _contains_any(haystack: str, terms: set[str]) -> bool:
    return any(term in haystack for term in terms)
