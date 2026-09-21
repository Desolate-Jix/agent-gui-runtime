from __future__ import annotations

import hashlib
import re
from typing import Any


SENSITIVE_TERMS = {
    "salary",
    "expected salary",
    "notice period",
    "start date",
    "available to start",
    "relocate",
    "relocation",
    "background check",
    "criminal",
    "conviction",
    "health declaration",
    "medical",
    "disability",
}
UPLOAD_TERMS = {"upload", "attach resume", "attach cv", "attach cover letter", "file"}
FINAL_SUBMIT_TERMS = {"submit", "send application", "complete application", "review and submit", "finish application"}
SAFE_PROFILE_FIELDS = {
    "name": ("candidate_name", "name"),
    "full name": ("candidate_name", "name"),
    "first name": ("first_name", "given_name", "candidate_first_name"),
    "given name": ("first_name", "given_name", "candidate_first_name"),
    "last name": ("last_name", "surname", "family_name", "candidate_last_name"),
    "surname": ("last_name", "surname", "family_name", "candidate_last_name"),
    "preferred name": ("preferred_name", "first_name", "given_name"),
    "email": ("email", "email_address"),
    "e-mail": ("email", "email_address"),
    "phone": ("phone", "phone_number", "mobile"),
    "mobile": ("mobile", "phone", "phone_number"),
    "city": ("city", "current_city", "location_city"),
    "suburb": ("suburb", "current_suburb"),
    "github": ("github", "github_url", "github_profile"),
    "git hub": ("github", "github_url", "github_profile"),
    "linkedin": ("linkedin", "linkedin_url", "linkedin_profile"),
    "linked in": ("linkedin", "linkedin_url", "linkedin_profile"),
    "portfolio": ("portfolio", "portfolio_url", "website"),
    "website": ("website", "portfolio_url", "personal_website"),
}
SIMPLE_TEXT_ROLE_TERMS = {"input", "text_input", "textbox", "text", "email", "tel", "url"}


def build_application_answer_plan(
    *,
    profile: dict[str, Any] | None,
    application_flow_state: dict[str, Any] | None,
    cover_letter_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify visible application fields without filling anything."""

    profile_payload = profile if isinstance(profile, dict) else {}
    flow = application_flow_state if isinstance(application_flow_state, dict) else {}
    draft = cover_letter_draft if isinstance(cover_letter_draft, dict) else {}
    blocker = flow.get("final_submit_visible_blocker") if isinstance(flow.get("final_submit_visible_blocker"), dict) else {}
    inventory = flow.get("application_form_inventory") if isinstance(flow.get("application_form_inventory"), dict) else {}
    fields = [item for item in inventory.get("fields") or [] if isinstance(item, dict)]
    actions = [item for item in inventory.get("actions") or [] if isinstance(item, dict)]
    items = [*fields, *actions]
    planned = [_classify_item(item, profile_payload, draft) for item in items]
    if blocker.get("blocked") is True:
        for item in blocker.get("matched_items") or []:
            if isinstance(item, dict):
                planned.append(
                    {
                        "category": "danger_final_submit",
                        "label": _clean(item.get("text")),
                        "reason": "final_submit_visible_blocker",
                        "source": item,
                        "answer_source": None,
                        "value_preview": None,
                    }
                )
    counts = {category: 0 for category in ("auto_safe_known", "needs_user_review", "blocked_sensitive", "unsupported", "danger_final_submit")}
    for item in planned:
        category = item.get("category")
        if category in counts:
            counts[category] += 1
    status = "blocked_final_submit_visible" if counts["danger_final_submit"] else ("planned_only_not_filled" if planned else "no_fields_detected")
    return {
        "contract_version": "application_answer_plan_v1",
        "status": status,
        "filled": False,
        "field_count": len(fields),
        "action_count": len(actions),
        "counts": counts,
        "planned_answers": planned[:80],
        "stop_reason": "final_submit_visible_stop_before_answering" if counts["danger_final_submit"] else "read_only_answer_plan_no_fill",
        "source_contracts": {
            "profile": profile_payload.get("contract_version"),
            "application_flow_state": flow.get("contract_version"),
            "cover_letter_draft": draft.get("contract_version"),
        },
    }


def _classify_item(item: dict[str, Any], profile: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    label = _clean(item.get("text") or item.get("label"))
    key = f"{label} {_clean(item.get('role'))}".casefold()
    simple_text_field = _is_simple_text_field(item)
    category = "needs_user_review"
    reason = "open_question_or_unmapped_field"
    answer_source = None
    value = None

    if _contains_any(key, FINAL_SUBMIT_TERMS) and not _is_generic_generated_submit_label(item, label):
        category = "danger_final_submit"
        reason = "final_submit_action_visible"
    elif _contains_any(key, UPLOAD_TERMS):
        category = "unsupported"
        reason = "file_upload_requires_user_review"
    elif _contains_any(key, SENSITIVE_TERMS):
        category = "blocked_sensitive"
        reason = "sensitive_or_uncertain_question"
    elif simple_text_field and _looks_like_cover_letter_body(label):
        if draft.get("status") == "draft_only_not_pasted" and _clean(draft.get("draft")):
            category = "auto_safe_known"
            reason = "cover_letter_body_field_detected"
            answer_source = "cover_letter_draft_v1.draft"
            value = _clean(draft.get("draft"))
        else:
            category = "needs_user_review"
            reason = "cover_letter_draft_missing_or_blocked"
    elif "visa" in key or "right to work" in key or "work rights" in key:
        work_rights = _clean(profile.get("work_rights_summary"))
        if work_rights and work_rights.casefold() not in {"unknown", "unspecified", "n/a"}:
            category = "auto_safe_known"
            reason = "profile_work_rights_available"
            answer_source = "candidate_profile_v1.work_rights_summary"
            value = work_rights
        else:
            category = "blocked_sensitive"
            reason = "work_rights_unknown_or_sensitive"
    elif "cover letter" in key or "supporting statement" in key:
        if _is_cover_letter_option_control(key):
            category = "unsupported"
            reason = "cover_letter_option_control_not_textarea"
        elif simple_text_field and draft.get("status") == "draft_only_not_pasted" and _clean(draft.get("draft")):
            category = "auto_safe_known"
            reason = "cover_letter_draft_available_but_not_pasted"
            answer_source = "cover_letter_draft_v1.draft"
            value = _clean(draft.get("draft"))
        else:
            category = "needs_user_review"
            reason = "cover_letter_draft_missing_or_blocked"
    else:
        for term, profile_keys in sorted(SAFE_PROFILE_FIELDS.items(), key=lambda entry: len(entry[0]), reverse=True):
            if term in key and simple_text_field:
                value = _first_profile_value(profile, profile_keys)
                if value:
                    category = "auto_safe_known"
                    reason = f"profile_{term.replace(' ', '_')}_available"
                    answer_source = f"candidate_profile_v1.{profile_keys[0]}"
                    value = value
                break

    return {
        "category": category,
        "label": label,
        "reason": reason,
        "source": {
            "collection": item.get("collection"),
            "id": item.get("id"),
            "role": item.get("role"),
            "bbox": item.get("bbox"),
            "source_text": item.get("source_text"),
        },
        "answer_source": answer_source,
        "value_preview": _redacted_value_preview(value, answer_source=answer_source),
        "value_length": len(value) if value else 0,
        "value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None,
    }


def _redacted_value_preview(value: str | None, *, answer_source: str | None) -> str | None:
    if not value:
        return None
    source = str(answer_source or "")
    if source == "cover_letter_draft_v1.draft":
        kind = "cover_letter"
    elif "email" in source:
        kind = "email"
    elif "phone" in source or "mobile" in source:
        kind = "phone"
    elif "name" in source:
        kind = "name"
    else:
        kind = "profile_value"
    return f"<redacted:{kind}:len={len(value)}>"


def _first_profile_value(profile: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _clean(profile.get(key))
        if value:
            return value
    return None


def _contains_any(haystack: str, terms: set[str]) -> bool:
    for term in terms:
        if " " in term or "-" in term:
            if term in haystack:
                return True
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", haystack):
            return True
    return False


def _is_simple_text_field(item: dict[str, Any]) -> bool:
    role = _clean(item.get("role") or item.get("type") or item.get("input_type")).casefold()
    if not role:
        return False
    if any(term in role for term in ("button", "checkbox", "radio", "select", "dropdown", "file")):
        return False
    return any(term in role for term in SIMPLE_TEXT_ROLE_TERMS)


def _looks_like_cover_letter_body(label: str) -> bool:
    lowered = _clean(label).casefold()
    return lowered.startswith("dear ") and len(lowered) > 120


def _is_cover_letter_option_control(key: str) -> bool:
    return any(
        phrase in key
        for phrase in (
            "upload a cover letter",
            "upload cover letter",
            "write a cover letter",
            "don't include a cover letter",
            "dont include a cover letter",
        )
    )


def _is_generic_generated_submit_label(item: dict[str, Any], label: str) -> bool:
    source_id = str(item.get("id") or "").casefold()
    collection = str(item.get("collection") or "").casefold()
    key = _clean(label).casefold()
    return collection == "available_actions" and source_id.startswith("action_screen_") and key in {"submit", "submit button"}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())
